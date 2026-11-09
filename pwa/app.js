// pwa/app.js
// Verdrahtung: Zustand der Oberfläche, Ereignisse, Abgleich-Auslöser, Service Worker. Die
// Entscheidungen stehen in den getesteten Modulen (`view-model.js`, `sync-policy.js`,
// `messages.js`); hier wird nur zusammengesteckt.
import { addDays, formatDateDe, isIsoDate, localIsoDate, mondayOf, utcStamp } from './minutes.js';
import { weekdayKey } from './defaults.js';
import { reservationEditable } from './reservations.js';
import { planReminders, signature } from './reminders-plan.js';
import { messageFor, testResultText } from './push-message.js';
import { idbKeyStore, seal } from './push-blob.js';
import { permissionState, shouldSchedule } from './push-policy.js';
import { RelayClient, RelayError, VAPID_PUBLIC, newSecret, syncSchedule } from './relay-client.js';
import { DEFAULT_WISH, aheadDays, olderState } from './window-policy.js';
import { DEFAULT_DEVICE_NAME, PROTOCOL, deviceNameFromUserAgent, isPairFragment, parseHostPort, parsePairLink } from './pairing.js';
import { openDatabase, requestPersistentStorage } from './db.js';
import { VaultError, createVaultAdapter, idbVaultKeyStore } from './vault.js';
import { Store } from './store.js';
import { SyncClient, SyncError, clockSkewMs } from './sync.js';
import { isPaired } from './transport.js';
import { shouldQueue, shouldSync } from './sync-policy.js';
import { errorDetail, logFailure, setLogSink, withDetail } from './diagnose.js';
import { createDebugLog, deliverExport, formatExport } from './debug-log.js';
import { capped, describeEnvironment, workerFromRegistration } from './debug-info.js';
import { idbLogStore } from './log-store.js';
import { swipeDirection } from './swipe-policy.js';
import { shouldApplyUpdate, shouldCheckForUpdate } from './update-policy.js';
import { blockSignature, rowsToBlock } from './categories.js';
import {
  categoriesModel, conflictsModel, connectionLabel, dayChanged, dayTitle, desktopHint, editLock, editorRows, focusKeyToRestore, hintsModel, olderModel, pushModel, reservationRows,
  iosInstallHint, isSetupPhase, pairingAfterBack, reservationRowsToSlots, rowsToSlots, setupModel, statusModel, reachedAfterSyncError, unpairDialogModel, validateReservationRows, validateRows, weekModel,
} from './view-model.js';
import { BUILD, CACHE_PREFIX } from './sw-core.js';
import { describeRepair, repairServiceWorker } from './sw-repair.js';
import { createUnpairRunner } from './unpair.js';
import { clear, focusByKey, focusState, h } from './dom.js';
import {
  conflictsDialog, confirmDialog, editorDialog, fatalView, hintsHost, pairView,
  lockDialog, patchHints, scanDialog, settingsDialog, statusBar, unpairDialog, vaultView, weekView,
} from './views.js';
import { canScan, scanForPairLink } from './scanner.js';
import { browserKind, isStandalone } from './browser-policy.js';
import { describeError, describeVaultError } from './messages.js';
import {
  createLockController, createLockCredential, createSessionSlot, disableLock, enableLock, lockErrorText, lockModel, lockSupport, normalizeLockDelay,
  unlockWithCredential,
} from './lock.js';

const LOCK_LEFT_KEY = 'zeiterfassung-lock-left-at';   // wann die entsperrte Seite zuletzt verlassen wurde (nur dieser Tab)
const SAVE_SYNC_DELAY_MS = 2000;
const SWIPE_CLICK_GUARD_MS = 400;
const PUSH_JOB_WAIT_MS = 3000;          // so lange wartet das Trennen auf einen laufenden Zeitplan-Versand

class App {
  constructor(root, store, client, initialHash = location.hash,
    { resetLocalData = async () => {}, wipeLocalData = async () => {}, reload = () => location.reload() } = {}) {
    this.initialHash = initialHash;
    this.resetLocalData = resetLocalData;       // löscht alle lokalen Daten und lädt neu (Notausgang der Sperre)
    this.wipeLocalData = wipeLocalData;         // nur das Löschen, wirft bei einem Fehler (Trennen, #499)
    this.reload = reload;
    this.unpairing = false;                     // ab der Bestätigung geht nichts mehr an den Desktop (ein `put` ersetzte die Abmeldung)
    // Vor allem anderen: ab hier landet jedes `logFailure` auch im Protokoll.
    this.debugLog = createDebugLog({ store: idbLogStore() });
    setLogSink((context, error) => this.debugLog.recordError(context, error));
    this.debugLog.prune();
    this.root = root;
    this.store = store;
    this.client = client;
    this.screen = 'week';
    this.anchor = localIsoDate(new Date());
    this.online = navigator.onLine !== false;
    this.syncing = false;
    this.lastError = null;
    this.lastAttemptAt = 0;
    this.deviceModel = '';
    this.skewMs = 0;
    this.persistent = null;
    this.persistRefused = false;
    this.updateReady = false;
    this.registration = null;
    this.updateState = 'serviceWorker' in navigator ? 'idle' : 'unsupported';
    this.updateDetail = '';
    this.lastUpdateCheckAt = 0;
    this.checkingUpdate = false;
    this.applyRequested = false;     // für den wartenden Worker ist SKIP_WAITING schon raus (keine Neulade-Schleife)
    this.pairing = { address: '', code: '', deviceName: '', busy: false, error: '', relay: null };
    this.saveTimer = null;
    this.pushTimer = null;
    this.pushBusy = false;
    this.pushJob = null;                   // läuft `updatePushSchedule`, dessen Ende (Trennen wartet darauf)
    this.lockElement = null;               // die Sperre (#490) liegt als Dialog über allem
    this.lockSlot = createSessionSlot(() => sessionStorage, LOCK_LEFT_KEY);
    this.lockCtl = createLockController({
      getMeta: () => this.store.getMeta(),
      now: () => Date.now(),
      unlockCredential: (id) => this.unlockCredential(id),
      onLock: () => this.showLock(),
      onUnlock: (day) => this.afterUnlock(day),
      // Ein Neuladen (Wischen zum Aktualisieren) innerhalb der Frist fragt nicht erneut; `sessionStorage` gilt je Tab.
      session: this.lockSlot,
    });
    this.lockSupportState = { available: false, reason: 'pending' };
    this.pushError = null;
    this.relay = new RelayClient();
    this.keys = idbKeyStore();
    this.queued = false;
    this.reloading = false;
    this.shell = null;          // persistente Teile der Wochenansicht (Hinweise, Statuszeile)
    this.lastFocusKey = null;
    this.hintHandlers = {
      pair: () => { this.screen = 'pair'; this.render(); },
      rescan: () => { this.screen = 'pair'; this.render(); },
      retry: () => this.trigger('manual'),
      reload: () => this.reloadForUpdate(),
      // Hinweise bleiben über Renders stehen: der Stand wird beim Klick gelesen, nicht beim Bau.
      conflicts: () => conflictsDialog(this.conflictList(), { openDay: (date) => this.openDay(date) }),
      persist: () => this.askPersistentStorage(),
      dismiss: (id) => this.dismissHint(id),
    };
  }

  /** „Dauerhaft sichern“: der Browser entscheidet selbst, die Anfrage kommt hier aus einer Nutzergeste. */
  async askPersistentStorage() {
    this.persistent = await requestPersistentStorage();
    this.persistRefused = !this.persistent;
    this.render();
    return this.persistent;
  }

  /** Schließt einen schließbaren Hinweis. Bisher gibt es nur den Speicher-Hinweis; er bleibt 7 Tage weg. */
  async dismissHint(id) {
    if (id !== 'storage') return;
    await this.store.setMeta({ storage_hint_dismissed_at: Date.now() });
    this.render();
  }

  get paired() {
    return isPaired(this.store.getMeta());
  }

  async start() {
    this.captureFragment(this.initialHash);
    if (!this.paired) this.screen = 'pair';
    if (!this.paired) this.loadDeviceModel();
    window.addEventListener('online', () => { this.online = true; this.trigger('online'); this.render(); });
    window.addEventListener('hashchange', () => { if (this.captureFragment()) this.render(); });
    window.addEventListener('offline', () => { this.online = false; this.render(); });
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible') { this.lockCtl.hidden(); return; }
      this.lockCtl.visible();
      if (!this.locked) this.trigger('visible');       // gesperrt: kein Abgleich; das Entsperren holt ihn nach
      this.updatePushSchedule();
      this.checkForUpdate('visible');
      this.maybeApplyUpdate();
    });
    // Zurück aus dem Back-Forward-Cache gibt es kein `visibilitychange`, das die Frist prüft.
    window.addEventListener('pagehide', () => this.lockCtl.hidden());
    window.addEventListener('pageshow', (event) => { if (event.persisted) this.lockCtl.visible(); });
    // Ein Dialog, der sich schließt, kann der letzte Grund gewesen sein, ein wartendes Update aufzuschieben.
    // `close` bubbelt nicht: Capture fängt es am Dokument.
    document.addEventListener('close', () => this.maybeApplyUpdate(), true);
    this.registerServiceWorker();
    this.listenForNotificationClicks();
    this.render();
    // Bei jedem Start gesperrt, sobald die Sperre eingeschaltet ist: im selben Zug wie das erste Rendern, ohne Blitz.
    this.lockCtl.start();
    this.lockSupportNow();            // im Hintergrund: die Einstellungen warten höchstens kurz darauf
    this.persistent = await requestPersistentStorage();
    this.render();
    this.trigger('start');
    this.updatePushSchedule();
    this.openDayFromLink();
  }

  // --- Sperre (#490) -----------------------------------------------------------------------------

  /** Kann dieses Gerät die Sperre anbieten? Bei jedem Öffnen der Einstellungen neu gefragt (lokal und billig): wer während der
   *  Sitzung Bildschirmsperre oder Biometrie einrichtet, soll dafür nicht neu laden müssen. */
  lockSupportNow() {
    return lockSupport({
      credentials: navigator.credentials, publicKeyCredential: globalThis.PublicKeyCredential, secure: window.isSecureContext,
    }).then((support) => { this.lockSupportState = support; return support; });
  }

  lockModelNow() {
    return lockModel({ meta: this.store.getMeta(), support: this.lockSupportState });
  }

  get locked() {
    return this.lockCtl.locked;
  }

  unlockCredential(id) {
    return unlockWithCredential({
      credentials: navigator.credentials, rpId: location.hostname, id,
      onError: (error) => logFailure('Sperre: Entsperren', error),
    });
  }

  showLock() {
    this.lockElement = lockDialog({
      isLocked: () => this.locked,
      unlock: () => this.unlockFromDialog(),
      reset: () => this.resetLocalData(),
    });
  }

  async unlockFromDialog() {
    let result;
    try {
      result = await this.lockCtl.unlock();
    } catch (error) {
      // `unlockWithCredential` wirft nie; ein Fehler im Ablauf selbst darf die Sperre nicht ohne Meldung und Notausgang lassen.
      logFailure('Sperre: Entsperren', error);
      result = { ok: false, reason: 'failed' };
    }
    return result.ok ? { ok: true } : { ok: false, text: lockErrorText(result.reason) };
  }

  /** Läuft, nachdem der Controller entsperrt hat (`locked` ist schon falsch, sonst öffnete sich der Dialog im `close`-Handler wieder). */
  afterUnlock(day) {
    this.lockElement?.close();
    this.lockElement?.remove();
    this.lockElement = null;
    this.trigger('visible');                   // der Abgleich, den das Zurückkehren gesperrt ausgelassen hat
    if (day) this.showDay(day);
  }

  async createLock() {
    const created = await createLockCredential({
      credentials: navigator.credentials, rpId: location.hostname,
      onError: (error) => logFailure('Sperre: Passkey anlegen', error),
    });
    return created.ok ? { ok: true, id: created.id } : { ok: false, error: lockErrorText(created.reason) };
  }

  /** Probe-Entsperrung des neuen Passkeys; erst danach gilt die Sperre. */
  async confirmLock(id) {
    const result = await enableLock({ id, probe: (credential) => this.unlockCredential(credential), setMeta: (patch) => this.store.setMeta(patch) });
    if (!result.ok) return { ok: false, error: `${lockErrorText(result.reason)} Die Sperre bleibt aus.` };
    return { ok: true, model: this.lockModelNow() };
  }

  async removeLock() {
    const result = await disableLock({
      meta: this.store.getMeta(), probe: (credential) => this.unlockCredential(credential), setMeta: (patch) => this.store.setMeta(patch) });
    if (!result.ok) return { ok: false, model: this.lockModelNow(), error: `${lockErrorText(result.reason)} Die Sperre bleibt an.` };
    return { ok: true, model: this.lockModelNow() };
  }

  async setLockDelay(ms) {
    await this.store.setMeta({ lock_delay_ms: normalizeLockDelay(ms) });
    return this.lockModelNow();
  }

  // --- Benachrichtigungen (#331) -----------------------------------------------------------------

  /** Ein Klick auf eine Benachrichtigung öffnet die App mit `?open=<Tag>`, eine schon offene bekommt
   *  den Tag als Nachricht des Service Workers. */
  openDayFromLink() {
    const date = new URLSearchParams(location.search).get('open');
    if (date === null) return;
    history.replaceState(null, '', location.pathname + location.hash);
    if (isIsoDate(date) && this.paired && this.screen === 'week') this.openDay(date);
  }

  listenForNotificationClicks() {
    if (!('serviceWorker' in navigator)) return;
    navigator.serviceWorker.addEventListener('message', (event) => {
      const data = event.data;
      if (data && data.type === 'OPEN_DAY' && isIsoDate(data.date) && this.paired && this.screen === 'week') this.openDay(data.date);
    });
  }

  pushSupported() {
    return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  }

  async subscription() {
    if (!this.pushSupported()) return null;
    const registration = await navigator.serviceWorker.getRegistration();
    return registration ? registration.pushManager.getSubscription() : null;
  }

  async pushState() {
    const supported = this.pushSupported();
    return permissionState({
      supported, permission: supported ? Notification.permission : 'default',
      subscribed: supported && Boolean(await this.subscription()), enabled: Boolean(this.store.getMeta().push_enabled),
    });
  }

  async pushModelNow() {
    const meta = this.store.getMeta();
    return pushModel({
      state: await this.pushState(), lastError: this.pushError, desktopReady: Boolean(meta.reminders),
      canTest: Boolean(meta.relay_secret),
    });
  }

  /** Einschalten (aus einem Klick): Erlaubnis holen, Abo anlegen, am Relay anmelden, Plan senden. */
  async enablePush() {
    this.pushError = null;
    try {
      if (!this.pushSupported() || (await Notification.requestPermission()) !== 'granted') return;
      const registration = await navigator.serviceWorker.ready;
      const subscription = (await registration.pushManager.getSubscription())
        ?? await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: base64UrlToBytes(VAPID_PUBLIC) });
      const secret = this.store.getMeta().relay_secret || newSecret();
      await this.store.setMeta({ push_enabled: true, relay_secret: secret, push_signature: null, push_sent_at: 0 });
      await this.relay.registerDevice(secret, subscription.toJSON());
      await this.updatePushSchedule();
      this.trigger('manual');                       // der Desktop erfährt das Geheimnis im nächsten Abgleich
    } catch (error) {
      if (!(error instanceof RelayError)) logFailure('Benachrichtigungen einschalten', error);
      this.pushError = error instanceof RelayError ? error.message : withDetail('Die Benachrichtigungen ließen sich nicht einschalten.', error);
    }
  }

  /** Lässt den Relay sofort eine Testbenachrichtigung senden; liefert den Text für die Anzeige. Wirft nie. */
  async sendTestPush() {
    const { relay_secret: secret } = this.store.getMeta();
    if (!secret) return testResultText('no_subscription');
    try {
      await this.relay.sendTest(secret);
      return testResultText('ok');
    } catch (error) {
      return error instanceof RelayError ? testResultText(error.kind, error.cause) : testResultText('server');
    }
  }

  // --- Trennen (#499) ------------------------------------------------------------------------------

  /** Die Rückfrage vor „Trennen und lokale Daten löschen“. Beim Öffnen läuft immer ein Abgleich (im WLAN die einzige
   *  Erreichbarkeitsprüfung, außerdem frischt er die Fähigkeit des Desktops auf); ein laufender wird abgewartet. Erst
   *  „Ja, trennen und löschen“ führt aus: Abmeldung, Push, Sitzungsmerker, Protokoll, `wipe()`, Neuladen. */
  openUnpair() {
    let dialog;
    let model = null;
    const runner = createUnpairRunner({
      notifyDesktop: async () => (await this.client.unpair()).state,
      disablePush: () => this.disablePush(),
      clearSession: () => this.lockSlot.write(null),
      clearDebug: async () => { if (!(await this.debugLog.clear())) throw new Error('Protokoll nicht geleert'); },
      wipe: async () => { await this.wipeLocalData(); this.store.freeze(); },
      reload: () => this.reload(),
      // Der Schritt steht im Text: `logFailure` verlangt ein festes Wort als Kontext, die Schrittnamen sind feste Wörter.
      log: (step, error) => logFailure('Trennen und lokale Daten löschen', new Error(`${step}: ${errorDetail(error)}`)),
    });
    const check = async () => {
      dialog.update({ phase: 'checking' });
      // Erreicht heißt: der Desktop hat geantwortet, oder der Relay hat die Anfrage angenommen und nur der Desktop
      // schweigt (`desktop_silent`): dann läge die Abmeldung in der Box. Alles andere (Relay oder Desktop nicht
      // erreichbar, Fehler am Handy) lässt sie verloren gehen. Der Grund des Scheiterns bleibt unprotokolliert: der
      // Abgleich läuft hier am normalen Weg (Reiter, Debug-Protokoll) vorbei, die Rückfrage braucht nur „erreicht oder nicht“.
      let reached = true;
      try {
        const result = await this.client.sync();
        reached = !result.discarded;
      } catch (error) {
        reached = reachedAfterSyncError(error);
      }
      const meta = this.store.getMeta();
      model = unpairDialogModel({ reached, openDays: this.store.pendingCount(), desktopUnpair: meta.desktop_unpair });
      dialog.update({ phase: 'ready', model });
    };
    const confirm = async () => {
      this.unpairing = true;
      clearTimeout(this.saveTimer);
      clearTimeout(this.pushTimer);
      dialog.update({ phase: 'running', model });
      // Ein laufender Zeitplan-Versand legte das Relay-Objekt nach dem Löschen neu an und schriebe Meta in den geleerten Vault.
      if (this.pushJob) await Promise.race([this.pushJob, new Promise((resolve) => setTimeout(resolve, PUSH_JOB_WAIT_MS))]);
      const result = await runner();
      if (!result.ok) {
        // `unpairing` bleibt gesetzt: die Abmeldung liegt womöglich schon in der Box, ein weiterer Abgleich ersetzte sie.
        dialog.update({ phase: 'error', model,
          error: 'Die lokalen Daten ließen sich nicht löschen. Bitte erneut versuchen.' });
      }
    };
    dialog = unpairDialog({ retry: check, confirm });
    check();
    return dialog;
  }

  async disablePush() {
    this.pushError = null;
    const { relay_secret: secret } = this.store.getMeta();
    try {
      await (await this.subscription())?.unsubscribe();
      if (secret) await this.relay.deleteDevice(secret);
    } catch (error) {
      // Ein nicht erreichbarer Relay lässt das Objekt dort stehen; es räumt sich nach 90 Tagen selbst auf.
      if (!(error instanceof RelayError)) logFailure('Benachrichtigungen ausschalten', error);
      this.pushError = error instanceof RelayError ? error.message : null;
    }
    await this.store.setMeta({ push_enabled: false, push_signature: null, push_sent_at: 0 });
  }

  /** Kurz nach einer Änderung neu planen, statt bei jedem Tastendruck des Nutzers. */
  schedulePushUpdate() {
    clearTimeout(this.pushTimer);
    this.pushTimer = setTimeout(() => this.updatePushSchedule(), SAVE_SYNC_DELAY_MS);
  }

  /** Plan neu berechnen und, wenn er sich geändert hat, verschlüsselt an den Relay schicken. Scheitert
   *  der Relay, bleibt es ein Hinweis im Reiter: Speichern und Abgleich laufen unabhängig davon. */
  async updatePushSchedule() {
    if (this.pushBusy || this.unpairing) return;
    this.pushBusy = true;
    let release;
    this.pushJob = new Promise((resolve) => { release = resolve; });     // `openUnpair` wartet darauf, bevor es löscht
    try {
      const meta = this.store.getMeta();
      const state = await this.pushState();
      if (state !== 'on' || !meta.reminders || !meta.relay_secret) return;
      const today = localIsoDate(new Date());
      const since = (dates) => dates.filter((date) => date >= today);
      const items = planReminders({
        reservations: meta.reservations_enabled
          ? Object.fromEntries(since(this.store.reservationDates()).map((date) => [date, this.store.getReservation(date)])) : {},
        entries: Object.fromEntries(since(this.store.days()).map((date) => [date, this.store.getDay(date)])),
        reminders: meta.reminders, now: new Date(),
      });
      const plan = signature(items);
      const now = Date.now();
      if (!shouldSchedule({ state, remindersPresent: true, lastSignature: meta.push_signature, signature: plan,
        lastSentAt: meta.push_sent_at, now })) return;
      const subscription = await this.subscription();
      const blobs = [];
      for (const item of items) blobs.push({ id: item.id, fire_at: utcStamp(item.fireAt), blob: await seal(this.keys, messageFor(item)) });
      if (this.unpairing) return;                          // inzwischen getrennt: kein Relay-Objekt neu anlegen
      await syncSchedule({ client: this.relay, secret: meta.relay_secret, subscription: subscription.toJSON(), items: blobs });
      if (this.unpairing) return;
      await this.store.setMeta({ push_signature: plan, push_sent_at: now });
      this.pushError = null;
    } catch (error) {
      if (!(error instanceof RelayError)) logFailure('Benachrichtigungs-Zeitplan senden', error);
      this.pushError = error instanceof RelayError ? error.message : withDetail('Der Zeitplan für die Benachrichtigungen ließ sich nicht senden.', error);
    } finally {
      this.pushBusy = false;
      release();
    }
  }

  // --- Koppeln über den Link -------------------------------------------------------------------

  /** `hash` ist das Fragment, das der Start schon vor dem Öffnen des Speichers aus der Adresszeile genommen
   *  hat (`main`); sonst das aktuelle. */
  captureFragment(hash = location.hash) {
    const link = parsePairLink(hash);
    scrubPairFragment();
    if (!link) return false;
    this.applyPairLink(link);
    this.screen = 'pair';
    return true;
  }

  /** Ein gelesener Koppel-Link (aus der Adresszeile oder dem Scanner) füllt die Koppel-Seite: ein
   *  Relay-Link merkt sich das Geheimnis nur im Speicher, die Seite zeigt es nie. */
  applyPairLink(link) {
    if (link.kind === 'relay') {
      this.pairing = { ...this.pairing, address: '', code: link.code, relay: { secret: link.secret }, error: '' };
    } else {
      this.pairing = { ...this.pairing, address: `${link.host}:${link.port}`, code: link.code, relay: null, error: '' };
    }
  }

  async submitPairing({ address, code, deviceName }) {
    const relay = this.pairing.relay;
    const target = relay ? null : parseHostPort(address);
    if (!relay && !target) {
      this.pairing = { ...this.pairing, address, code, deviceName, busy: false, error: 'Die Adresse muss eine private IPv4-Adresse sein, zum Beispiel 192.168.178.20:17654.' };
      this.render();
      return;
    }
    const usedCode = relay ? this.pairing.code : code;
    this.pairing = { ...this.pairing, address, code: usedCode, deviceName, busy: true, error: '' };
    this.render();
    try {
      const name = deviceName.trim() || DEFAULT_DEVICE_NAME;
      if (relay) await this.client.pairRelay({ secret: relay.secret, code: usedCode, deviceName: name });
      else await this.client.pair({ host: target.host, port: target.port, code, deviceName: name });
      await this.store.setMeta({ device_name: deviceName.trim() });
      this.pairing = { address: '', code: '', deviceName: '', busy: false, error: '', relay: null };
      this.lastError = null;
      this.screen = 'week';
      this.render();
      this.trigger('manual');
    } catch (error) {
      this.pairing = { ...this.pairing, address, code: usedCode, deviceName, busy: false,
        error: describeError(error, this.errorEnv(address, relay ? 'relay' : 'lan')).text };
      this.render();
    }
  }

  async scanPairing() {
    const abort = new AbortController();
    const { video, message } = scanDialog(() => abort.abort());
    try {
      const link = await scanForPairLink(video, abort.signal, (text) => { message.textContent = text; });
      if (link) {
        document.querySelector('dialog[open]')?.close();
        this.applyPairLink(link);
        this.render();
      }
    } catch (error) {
      logFailure('Kamera beim Koppeln', error);
      message.textContent = withDetail('Die Kamera ist nicht verfügbar oder nicht freigegeben. Bitte Adresse und Code eintippen oder die Kamera-App benutzen.', error);
    }
  }

  // --- Abgleich ----------------------------------------------------------------------------------

  trigger(name) {
    if (this.unpairing) return;
    const allowed = shouldSync({
      trigger: name, paired: this.paired, syncing: this.syncing, online: this.online,
      now: Date.now(), lastAttemptAt: this.lastAttemptAt, lastError: this.lastError,
    });
    if (allowed) this.runSync();
    else if (shouldQueue({ trigger: name, paired: this.paired, syncing: this.syncing })) this.queued = true;
  }

  scheduleSyncAfterSave() {
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => this.trigger('save'), SAVE_SYNC_DELAY_MS);
    this.schedulePushUpdate();                            // auch ohne Netz zum Desktop: der Relay ist ein anderer Weg
  }

  async runSync() {
    this.syncing = true;
    this.lastAttemptAt = Date.now();
    this.render();
    const startedAt = Date.now();
    try {
      const result = await this.client.sync();
      if (!result.discarded) this.debugLog.recordSync({ result: 'ok', ms: Date.now() - startedAt, ...result });
      this.lastError = null;
      if (!result.discarded) this.skewMs = clockSkewMs(this.store.getMeta().server_time, new Date());
      this.updatePushSchedule();
    } catch (error) {
      this.debugLog.recordSync({ result: error?.kind ?? error?.name, ms: Date.now() - startedAt });
      this.lastError = error instanceof SyncError ? error
        : new SyncError({ kind: 'client_error', message: String(error?.message ?? error) });
    } finally {
      this.syncing = false;
      this.render();
      if (this.queued) {                                  // ein Speichern/Knopfdruck kam währenddessen
        this.queued = false;
        this.trigger('manual');
      } else {
        this.maybeApplyUpdate();                          // ein Abgleich war der Grund, ein Update aufzuschieben
      }
    }
  }

  // --- Anzeige -----------------------------------------------------------------------------------

  /** Vorschlag für das Namensfeld; das Modell aus den Client-Hinweisen kommt erst asynchron (`loadDeviceModel`). */
  suggestedDeviceName() {
    return deviceNameFromUserAgent(navigator.userAgent, { maxTouchPoints: navigator.maxTouchPoints, model: this.deviceModel });
  }

  /** Chrome versteckt das Modell im User-Agent; die Client-Hinweise liefern es, nur auf Anfrage. Fehlen sie
   *  (Safari, Firefox) oder scheitert die Anfrage, bleibt es beim Vorschlag ohne Modell. */
  async loadDeviceModel() {
    try {
      const values = await navigator.userAgentData?.getHighEntropyValues?.(['model']);
      this.deviceModel = values?.model || '';
    } catch {
      this.deviceModel = ''; // Hinweise verweigert: der Name bleibt der neutrale Vorschlag
    }
    // Nur das noch unberührte Pairing-Formular nachziehen; ein getippter Name bleibt stehen.
    if (this.deviceModel && this.screen === 'pair' && !this.pairing.deviceName) this.render();
  }

  conflictList() {
    return conflictsModel(this.store.getMeta().conflicts);
  }

  render() {
    const focusKey = focusKeyToRestore({ ...focusState(this.root), last: this.lastFocusKey });
    if (this.screen === 'pair') {
      this.shell = null;
      clear(this.root);
      const env = this.errorEnv('');
      this.root.append(pairView({
        address: this.pairing.address, code: this.pairing.code,
        deviceName: this.pairing.deviceName || this.store.getMeta().device_name || this.suggestedDeviceName(),
        error: this.pairing.error,
        busy: this.pairing.busy, canScan: canScan(), canCancel: this.paired, canBack: !this.paired, relay: Boolean(this.pairing.relay),
        installHint: iosInstallHint(env),
        setup: isSetupPhase(this.pairing) ? setupModel({ browser: env.browser, standalone: env.standalone, canScan: canScan() }) : null,
      }, {
        submit: (values) => this.submitPairing(values),
        change: (field, value) => { this.pairing[field] = value; },
        scan: () => this.scanPairing(),
        manual: () => { this.pairing = { ...this.pairing, manual: true }; this.render(); },
        back: () => { this.pairing = pairingAfterBack(this.pairing); this.render(); },
        cancel: () => { this.pairing = { ...this.pairing, manual: false }; this.screen = 'week'; this.render(); },
      }));
      this.lastFocusKey = focusByKey(this.root, focusKey) ? focusKey : null;
      return;
    }
    const meta = this.store.getMeta();
    const conflicts = this.conflictList();
    const model = weekModel({
      getDay: (date) => this.store.getDay(date), anchor: this.anchor, today: localIsoDate(new Date()),
      conflictDates: conflicts.map((conflict) => conflict.date), windowDays: meta.window_days, aheadDays: aheadDays(meta.window_ahead),
      getReservation: (date) => this.store.getReservation(date), reservationsEnabled: meta.reservations_enabled,
    });
    model.older = olderModel(olderState({
      firstDay: model.days[0].date, today: localIsoDate(new Date()), windowDays: meta.window_days,
      windowMax: meta.window_max, maxKnown: meta.window_max_known, acked: meta.window_wish_acked,
    }));
    const hints = hintsModel({
      lastError: this.lastError, excluded: meta.excluded, skewMs: this.skewMs, persistent: this.persistent,
      dismissedAt: meta.storage_hint_dismissed_at, persistRefused: this.persistRefused,
      updateReady: this.updateReady, conflictCount: conflicts.length,
      errorDays: this.store.errorCount(), errorEnv: this.errorEnv(meta.address ? `${meta.address.host}:${meta.address.port}` : '', meta.transport),
    });
    if (!this.shell) this.shell = this.buildShell();
    patchHints(this.shell.hints, hints, this.hintHandlers);
    this.shell.week.replaceChildren(weekView(model, {
      previous: () => this.shiftWeek(-1),
      next: () => this.shiftWeek(1),
      today: () => { this.anchor = localIsoDate(new Date()); this.render(); },
      openDay: (date) => this.openDay(date),
      older: (wish) => this.loadOlder(wish),
    }));
    this.shell.status.update(statusModel({
      paired: this.paired, online: this.online, syncing: this.syncing, pending: this.store.pendingCount(),
      lastSyncAt: meta.server_time,
    }));
    this.lastFocusKey = focusByKey(this.root, focusKey) ? focusKey : null;
  }

  /** Hinweise und Statuszeile werden einmal gebaut und danach nur gepatcht (Live-Regionen, Fokus). */
  buildShell() {
    clear(this.root);
    const hints = hintsHost();
    const week = h('div', {});
    const status = statusBar({ sync: () => this.trigger('manual'), settings: () => this.openSettings() });
    const main = h('main', {}, hints, week);
    this.watchSwipe(main);
    this.root.append(main, status.element);
    return { hints, week, status };
  }

  /** Was die Fehlermeldung über Browser, Adresse und Weg zum Desktop wissen darf (#275, #358). */
  errorEnv(address, transport = this.store.getMeta().transport) {
    const standalone = isStandalone({
      navigatorStandalone: navigator.standalone,
      displayModeStandalone: globalThis.matchMedia?.('(display-mode: standalone)')?.matches,
    });
    return { browser: browserKind(navigator.userAgent, navigator.userAgentData), address, transport, standalone };
  }

  /** Parameter für `describeEnvironment` (Debug-Reiter). Jede Abfrage für sich und alle nebeneinander: scheitert oder
   *  fehlt eine, ist sie `null`, nie eine Ausnahme; jede wartet höchstens 2 s (`capped`), die Gesamtdauer liegt also
   *  ebenfalls bei etwa 2 s. Vom Gerät nur `platformVersion` — das Modell steht nie im Bericht. */
  async collectDebugEnv() {
    const known = (lookup) => capped(lookup).then((value) => value ?? null);
    const registrationLookup = capped(() => navigator.serviceWorker.getRegistration());
    const [registration, permission, persisted, usage, meta, subscribed, platformVersion, standalone, userAgent, online,
      language, screenSize, build] = await Promise.all([
      registrationLookup,
      known(() => Notification.permission),
      known(() => navigator.storage.persisted()),
      known(async () => (await navigator.storage.estimate()).usage),
      known(() => this.store.getMeta()),
      registrationLookup.then((reg) => (reg ? known(async () => Boolean(await reg.pushManager.getSubscription())) : null)),
      known(async () => {
        const values = await navigator.userAgentData.getHighEntropyValues(['platformVersion']);
        return values.platformVersion || null;
      }),
      known(() => isStandalone({
        navigatorStandalone: navigator.standalone,
        displayModeStandalone: globalThis.matchMedia('(display-mode: standalone)').matches,
      })),
      known(() => navigator.userAgent),
      known(() => navigator.onLine !== false && this.online),
      known(() => navigator.language),
      known(() => ({ width: screen.width, height: screen.height })),
      known(() => BUILD),
    ]);
    return {
      userAgent,
      platformVersion,
      standalone,
      online,
      language,
      screen: screenSize,
      build,
      worker: workerFromRegistration(registration),
      notification: permission,
      subscribed,
      storage: persisted === null && usage === null ? null : { persisted, usage },
      pairing: meta?.transport === 'relay' ? 'relay' : (meta && isPaired(meta) ? 'lan' : null),
      protocol: PROTOCOL,
    };
  }

  shiftWeek(weeks) {
    this.anchor = addDays(this.anchor, weeks * 7);
    this.render();
  }

  /** Wisch nach links/rechts wechselt die Woche wie ‹ und ›. Die Buttons bleiben; entschieden wird in
   *  `swipe-policy.js`. Einmal am `main` gebunden, es überlebt das Neuzeichnen der Woche. */
  watchSwipe(main) {
    let start = null;
    let swipedAt = -Infinity;
    main.addEventListener('pointerdown', (event) => {
      const idle = this.screen === 'week' && !document.querySelector('dialog[open]');
      start = idle && event.isPrimary ? { x: event.clientX, y: event.clientY, at: event.timeStamp } : null;
    });
    main.addEventListener('pointercancel', () => { start = null; });
    main.addEventListener('pointerup', (event) => {
      const from = start;
      start = null;
      if (!from) return;
      const direction = swipeDirection({
        pointerType: event.pointerType, width: main.clientWidth, startX: from.x, startY: from.y,
        endX: event.clientX, endY: event.clientY, durationMs: event.timeStamp - from.at,
      });
      if (!direction) return;
      swipedAt = event.timeStamp;
      this.shiftWeek(direction === 'next' ? 1 : -1);
    });
    // Ein Wisch, der auf einem Tag endet, darf dessen Editor nicht öffnen.
    main.addEventListener('click', (event) => {
      if (event.timeStamp - swipedAt < SWIPE_CLICK_GUARD_MS) { event.stopPropagation(); event.preventDefault(); }
    }, true);
  }

  /** Export-Text samt Datei, vorab gebaut: Kopieren und Teilen brauchen die Nutzergeste, und Safari/iOS verwirft sie
   *  nach einem `await`. Neu gebaut bei jedem Laden, Löschen und Haltezeit-Wechsel. */
  buildDebugExport(info, entries) {
    const text = formatExport({ info, entries });
    this.debugExport = { text, file: new File([text], 'zeiterfassung-debug.txt', { type: 'text/plain' }) };
  }

  /** Modell des Debug-Reiters, beim Zeigen des Reiters geladen. Wirft nie: scheitert etwas, bleibt der Block leer. */
  async loadDebug() {
    let info = [{ label: 'Zustand', value: 'unbekannt' }];
    let entries = [];
    let retention = 7;
    try {
      info = describeEnvironment(await this.collectDebugEnv());
      entries = await this.debugLog.entries();
      retention = await this.debugLog.retentionDays();
    } catch {
      // Der Reiter zeigt, was er hat; kopiert wird dann ebenfalls nur das.
    }
    this.debugInfo = info;
    this.buildDebugExport(info, entries);
    return { info, entries, retention, persistent: this.debugLog.isPersistent() };
  }

  async refreshDebug() {
    const entries = await this.debugLog.entries();
    this.buildDebugExport(this.debugInfo ?? [], entries);
    return { entries, persistent: this.debugLog.isPersistent() };
  }

  /** `true`, wenn das Protokoll wirklich leer ist; sonst bleibt der Export-Text, bis `refreshDebug` neu liest. */
  async clearDebug() {
    const cleared = await this.debugLog.clear();
    if (cleared) this.buildDebugExport(this.debugInfo ?? [], []);
    return cleared;
  }

  /** Läuft synchron bis zum Aufruf der Zwischenablage (keine Wartepunkte davor). */
  copyDebug() {
    const text = this.debugExport?.text;
    if (text == null) return Promise.resolve('failed');
    const fallback = () => {
      try {
        // Im Dialog, nicht im body: außerhalb eines offenen modalen Dialogs ist alles inert und `select()` greift nicht.
        const host = [...document.querySelectorAll('dialog[open]')].pop() ?? document.body;
        const area = h('textarea', { readonly: true, class: 'clipboard-proxy' }, text);
        host.append(area);
        area.select();
        const ok = document.execCommand('copy');
        area.remove();
        return ok ? 'copied' : 'failed';
      } catch {
        return 'failed';
      }
    };
    if (!navigator.clipboard?.writeText) return Promise.resolve(fallback());
    try {
      return navigator.clipboard.writeText(text).then(() => 'copied', fallback);
    } catch {
      return Promise.resolve(fallback());
    }
  }

  /** Wie `copyDebug`: `canShare`/`share` laufen vor jedem Wartepunkt. */
  shareDebug() {
    const { text, file } = this.debugExport ?? {};
    if (!file) return Promise.reject(new Error('Kein Export vorbereitet'));
    return deliverExport(text, {
      canShare: () => Boolean(navigator.canShare?.({ files: [file] })),
      share: () => navigator.share({ files: [file] }),
      download: () => {
        const url = URL.createObjectURL(file);
        const link = h('a', { href: url, download: file.name });
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      },
    });
  }

  async openSettings(initialTab = 'connection') {
    const meta = this.store.getMeta();
    const push = await this.pushModelNow();
    // Höchstens kurz: ein Browser, der die Abfrage nicht beantwortet, soll die Einstellungen (Neu koppeln, Updates) nicht sperren.
    await Promise.race([this.lockSupportNow(), new Promise((resolve) => setTimeout(resolve, 1000))]);
    if (this.locked) return;              // während des Wartens gesperrt: ein Dialog läge über der Sperre
    const returnKey = focusState(this.root).activeKey;
    const signature = (m) => blockSignature(m.categories, m.defaults?.category_times ?? {});
    let baseline = signature(meta);   // Stand beim Öffnen: Speichern prüft, ob der Abgleich ihn inzwischen geändert hat
    const dialog = settingsDialog({
      tab: initialTab,
      connection: {
        desktopName: meta.desktop_name,
        desktop: meta.desktop,
        window: { days: meta.window_days, max: meta.window_max, wish: meta.window_wish, ahead: meta.window_ahead },
        hint: desktopHint(meta),
        address: connectionLabel(meta),
        transport: meta.transport,
        persistent: this.persistent,
        tokenUntil: meta.token_expires_at ? formatDateDe(meta.token_expires_at.slice(0, 10)) : '',
        online: this.online, lastSyncAt: meta.server_time,
        push,
        lock: this.lockModelNow(),
      },
      updates: { build: BUILD, update: { state: this.updateState, detail: this.updateDetail, auto: Boolean(meta.auto_update) } },
      categories: categoriesModel({
        categories: meta.categories, defaults: meta.defaults, writable: meta.settings_writable, edit: meta.categories_edit,
      }),
    }, {
      loadDebug: () => this.loadDebug(),
      copyDebug: () => this.copyDebug(),
      shareDebug: () => this.shareDebug(),
      clearDebug: () => this.clearDebug(),
      setRetention: (days) => this.debugLog.setRetentionDays(days),
      refreshDebug: () => this.refreshDebug(),
      pair: () => { this.screen = 'pair'; this.render(); },
      repairUpdates: () => this.repairServiceWorker(),
      checkUpdate: async () => ({ state: await this.checkForUpdate('manual'), detail: this.updateDetail }),
      resetWindow: () => this.resetWindow(),
      testPush: () => this.sendTestPush(),
      persist: () => this.askPersistentStorage(),
      setPush: async (on) => {
        if (on) await this.enablePush(); else await this.disablePush();
        return this.pushModelNow();
      },
      unpair: () => this.openUnpair(),
      createLock: () => this.createLock(),
      confirmLock: (id) => this.confirmLock(id),
      removeLock: () => this.removeLock(),
      setLockDelay: (ms) => this.setLockDelay(ms),
      applyUpdate: () => this.reloadForUpdate(),
      setAutoUpdate: async (on) => {
        await this.store.setMeta({ auto_update: on });
        this.maybeApplyUpdate();
      },
      saveCategories: async (rows) => {
        const current = signature(this.store.getMeta());
        if (current !== baseline) {
          baseline = current;   // bewusst gewarnt: das nächste Speichern überschreibt
          return 'Die Kategorien wurden inzwischen aktualisiert (Abgleich). Nochmaliges Speichern überschreibt die neuere Fassung.';
        }
        try {
          await this.store.saveCategories(rowsToBlock(rows));
        } catch (error) {
          return String(error?.message ?? error);
        }
        baseline = signature(this.store.getMeta());
        this.render();
        this.scheduleSyncAfterSave();
        return null;
      },
    });
    dialog.addEventListener('close', () => { focusByKey(this.root, returnKey); });
  }

  /** Ein später geöffneter modaler Dialog läge über der Sperre: gesperrt wird der Tag erst nach dem Entsperren geöffnet. */
  openDay(date) {
    this.lockCtl.openDay(date, (day) => this.showDay(day));
  }

  showDay(date) {
    const day = this.store.getDay(date);
    const meta = this.store.getMeta();
    const today = localIsoDate(new Date());
    const returnKey = focusState(this.root).activeKey;
    let baseline = day;         // Stand beim Öffnen: Speichern prüft, ob der Tag inzwischen anders ist
    // Außerhalb dessen, was das Handy vom Desktop kennt, ist die Arbeitszeit gesperrt (#273).
    const lock = editLock({ date, today, meta, hasRecord: Boolean(day) });
    // Reservierungen nur, wenn der Desktop sie anbietet und der Tag heute oder später ist.
    const reservationOn = meta.reservations_enabled && reservationEditable(date, today);
    const reservation = reservationOn ? this.store.getReservation(date) : null;
    let reservationBaseline = reservation;
    // Desktop versteht die Pause an Reservierungen (#455). Der Wert bleibt bei geöffnetem Dialog fest: ein Abgleich,
    // der das Flag dreht, ändert ihn nicht (der Draht ist getrennt in `snapshotReservations` gesperrt).
    const pauseEnabled = Boolean(meta.reservation_pause);
    // An Tagen nach heute öffnet der Editor bei der Reservierung: die Ist-Zeilen sind mit den
    // Standardzeiten vorbelegt, ein Speichern dort legte sonst still eine Ist-Zeit an.
    const startWith = reservationOn && date > today ? 'reservation' : 'work';
    const dialog = editorDialog({
      title: dayTitle(date),
      rows: editorRows(day, meta.defaults, weekdayKey(date), reservation),
      categories: meta.categories,
      defaults: meta.defaults,
      weekday: weekdayKey(date),
      errors: { work: day?.error ?? null, reservation: reservation?.error ?? null },
      lock,
      canClear: Boolean(day && !day.deleted),
      validate: (rows) => validateRows(rows),
      reservation: reservationOn ? {
        rows: reservationRows(reservation, meta.defaults, weekdayKey(date), { pauseEnabled }),
        canClear: Boolean(reservation && !reservation.deleted),
        validate: (rows) => validateReservationRows(rows, { pauseEnabled }),
      } : null,
      startWith,
      pauseEnabled,
    }, {
      loadOlder: () => { dialog.close(); this.loadOlder(lock.wish); },
      save: async (kind, rows) => {
        if (kind === 'reservation') {
          const current = this.store.getReservation(date);
          if (dayChanged(reservationBaseline, current)) {
            reservationBaseline = current;   // bewusst gewarnt: das nächste Speichern überschreibt
            return 'Diese Reservierung wurde inzwischen aktualisiert (Abgleich). Nochmaliges Speichern überschreibt die neuere Fassung.';
          }
          try {
            await this.store.saveReservation(date, reservationRowsToSlots(rows, { pauseEnabled }));
          } catch (error) {
            return String(error?.message ?? error);
          }
        } else {
          if (lock) return lock.text;          // der Editor sperrt schon; hier die zweite Sicherung
          const current = this.store.getDay(date);
          if (dayChanged(baseline, current)) {
            baseline = current;   // bewusst gewarnt: das nächste Speichern überschreibt
            return 'Dieser Tag wurde inzwischen aktualisiert (Abgleich). Nochmaliges Speichern überschreibt die neuere Fassung.';
          }
          try {
            await this.store.saveDay(date, rowsToSlots(rows));
          } catch (error) {
            return String(error?.message ?? error);
          }
        }
        this.render();
        this.scheduleSyncAfterSave();
        return null;
      },
      clear: (kind, dialog) => confirmDialog(kind === 'reservation' ? {
        title: 'Reservierung löschen?',
        text: `Die Reservierung vom ${formatDateDe(date)} wird gelöscht (beim nächsten Abgleich auch am Desktop).`,
        confirmLabel: 'Reservierung löschen',
      } : {
        title: 'Tag leeren?', text: `Alle Einträge vom ${formatDateDe(date)} werden gelöscht (beim nächsten Abgleich auch am Desktop).`,
        confirmLabel: 'Tag leeren',
      }, async () => {
        try {
          if (kind === 'reservation') await this.store.clearReservation(date);
          else await this.store.clearDay(date);
        } catch (error) {
          dialog.querySelector('.error-text').textContent = String(error?.message ?? error);
          return;
        }
        dialog.close();
        this.render();
        this.scheduleSyncAfterSave();
      }),
    });
    // Der Opener wird bei jedem Render ersetzt; der Browser kann den Fokus nach dem Schließen nicht zurückgeben.
    dialog.addEventListener('close', () => { focusByKey(this.root, returnKey); });
  }

  // --- Service Worker ----------------------------------------------------------------------------

  async registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    try {
      const registration = await navigator.serviceWorker.register('./sw.js', { type: 'module' });
      this.registration = registration;
      const watch = (worker) => worker?.addEventListener('statechange', () => {
        if (worker.state === 'installed' && navigator.serviceWorker.controller) this.markUpdateReady();
      });
      if (registration.waiting && navigator.serviceWorker.controller) this.markUpdateReady();
      watch(registration.installing);
      registration.addEventListener('updatefound', () => watch(registration.installing));
      navigator.serviceWorker.addEventListener('controllerchange', () => { if (this.reloading) location.reload(); });
      this.checkForUpdate('start');
    } catch (error) {
      // Ohne Service Worker läuft die App online weiter; offline starten kann sie dann nicht.
      logFailure('Service Worker registrieren', error);
      this.updateState = 'error';
      this.updateDetail = errorDetail(error);
    }
  }

  /** „Reparieren“ (#390): Service Worker neu einrichten, Einträge und Kopplung bleiben. Bei Erfolg lädt die Seite
   *  neu (der neue Worker übernimmt sie); sonst `{ ok: false, text }`. */
  async repairServiceWorker() {
    try {
      await repairServiceWorker({
        serviceWorker: navigator.serviceWorker, cacheStorage: globalThis.caches, prefix: CACHE_PREFIX,
        scriptUrl: './sw.js', fetchFn: (url, options) => fetch(url, options), online: navigator.onLine,
      });
    } catch (error) {
      logFailure('Service Worker reparieren', error.cause ?? error);
      return { ok: false, text: describeRepair(error) };
    }
    location.reload();
    return { ok: true, text: '' };
  }

  markUpdateReady() {
    this.updateReady = true;
    this.updateState = 'available';
    this.render();
    this.maybeApplyUpdate();
  }

  /** Sucht nach einer neuen Version (der Browser tut das von sich aus nur bei einer Navigation) und
   *  liefert den Zustand für die Anzeige: current / available / offline / error / unsupported. */
  async checkForUpdate(trigger) {
    const supported = Boolean(this.registration);
    if (!shouldCheckForUpdate({ trigger, now: Date.now(), lastCheckAt: this.lastUpdateCheckAt,
      online: this.online, checking: this.checkingUpdate, supported })) {
      return this.checkingUpdate ? 'checking' : this.updateState;
    }
    this.checkingUpdate = true;
    this.lastUpdateCheckAt = Date.now();
    this.updateState = 'checking';
    this.updateDetail = '';
    try {
      await this.registration.update();
      const worker = this.registration.installing;
      if (worker) {
        await new Promise((resolve) => {
          const settled = () => { if (['installed', 'activated', 'redundant'].includes(worker.state)) resolve(); };
          worker.addEventListener('statechange', settled);
          settled();
        });
      }
      if (this.updateReady || this.registration.waiting) this.markUpdateReady();
      else this.updateState = 'current';
    } catch (error) {
      logFailure('Update-Suche', error);
      this.updateState = navigator.onLine === false ? 'offline' : 'error';
      this.updateDetail = errorDetail(error);
    } finally {
      this.checkingUpdate = false;
    }
    return this.updateState;
  }

  /** Spielt ein wartendes Update ein, wenn der Nutzer das erlaubt hat und es gerade nichts stört. */
  maybeApplyUpdate() {
    if (!shouldApplyUpdate({
      autoUpdate: Boolean(this.store.getMeta().auto_update), updateReady: this.updateReady,
      dialogOpen: document.querySelector('dialog[open]') !== null, syncing: this.syncing,
      requested: this.applyRequested,
    })) return;
    this.applyRequested = true;
    this.reloadForUpdate();
  }

  /** „Ältere Zeiten laden“: den Wunsch erhöhen und abgleichen; der Desktop gewährt, was er darf. */
  async loadOlder(wish) {
    await this.store.setMeta({ window_wish: wish });
    this.trigger('manual');
  }

  async resetWindow() {
    await this.store.setMeta({ window_wish: DEFAULT_WISH });
    this.trigger('manual');
  }

  async reloadForUpdate() {
    let registration = await navigator.serviceWorker.getRegistration();
    if (!registration?.waiting) {
      await this.checkForUpdate('manual');          // z. B. „Neu laden“ nach einer Protokoll-Meldung
      registration = await navigator.serviceWorker.getRegistration();
    }
    if (!registration?.waiting) { location.reload(); return; }
    this.reloading = true;
    registration.waiting.postMessage({ type: 'SKIP_WAITING' });
  }
}

function base64UrlToBytes(text) {
  const raw = atob(text.replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (char) => char.charCodeAt(0));
}

/** Das Fragment trägt den Einmalcode und bei einem Relay-Link das Geheimnis der Box: nie in der Adresszeile oder
 *  im Verlauf stehen lassen, auch wenn der Link unbrauchbar ist. */
function scrubPairFragment() {
  if (isPairFragment(location.hash)) history.replaceState(null, '', location.pathname + location.search);
}

async function main() {
  const root = document.getElementById('app');
  // Vor allem anderen: scheitert der Speicher (privates Fenster), zeigt `fatalView` die Seite, und das Fragment
  // stünde sonst weiter in der Adresszeile. Der Link selbst geht an die App, sie koppelt daraus.
  const startHash = location.hash;
  scrubPairFragment();
  let store;
  let vault;
  // Notausgang des Fehlerbildschirms und der Sperre: alles Lokale löschen, dann neu laden (nicht übertragene Tage gehen verloren).
  const resetLocalData = async () => {
    try {
      await vault.wipe();
    } catch (wipeError) {
      logFailure('Lokale Daten löschen', wipeError);
    }
    location.reload();
  };
  try {
    vault = createVaultAdapter(await openDatabase(), { keys: idbVaultKeyStore() });
    store = new Store(vault);
    await store.load();
  } catch (error) {
    if (error instanceof VaultError) {
      // Verschlüsselte Daten ohne passenden Schlüssel: nie als „leer“ weiterlaufen, der nächste Speichervorgang
      // überschriebe sie. Der Nutzer entscheidet, ob er neu koppelt (löscht die lokalen Daten).
      logFailure('Verschlüsselte Daten öffnen', error);
      root.append(vaultView(describeVaultError(error), { reload: () => location.reload(), reset: resetLocalData }));
      return;
    }
    logFailure('Speicher des Browsers öffnen', error);
    root.append(fatalView(withDetail('Der Speicher des Browsers ist nicht verfügbar (privates Fenster oder gesperrt?). Ohne ihn kann diese App keine Einträge sichern.', error)));
    return;
  }
  if (vault.encrypting) {
    try {
      await vault.migrate();
    } catch (error) {
      logFailure('Vorhandene Daten verschlüsseln', error);       // kein Grund, die App nicht zu starten: es bleibt Klartext
    }
  }
  await new App(root, store, new SyncClient({ store }), startHash,
    { resetLocalData, wipeLocalData: () => vault.wipe() }).start();
}

main();
