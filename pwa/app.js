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
import { deviceNameFromUserAgent, parseHostPort, parsePairFragment } from './pairing.js';
import { openDatabase, requestPersistentStorage } from './db.js';
import { Store } from './store.js';
import { SyncClient, SyncError, clockSkewMs } from './sync.js';
import { shouldQueue, shouldSync } from './sync-policy.js';
import { errorDetail, logFailure, withDetail } from './diagnose.js';
import { swipeDirection } from './swipe-policy.js';
import { shouldApplyUpdate, shouldCheckForUpdate } from './update-policy.js';
import { blockSignature, rowsToBlock } from './categories.js';
import {
  categoriesModel, conflictsModel, dayChanged, desktopHint, editLock, editorRows, focusKeyToRestore, hintsModel, olderModel, pushModel, reservationRows,
  reservationRowsToSlots, rowsToSlots, statusModel, validateReservationRows, validateRows, weekModel,
} from './view-model.js';
import { BUILD } from './sw-core.js';
import { clear, focusByKey, focusState, h } from './dom.js';
import {
  conflictsDialog, confirmDialog, editorDialog, fatalView, hintsHost, pairView,
  patchHints, scanDialog, settingsDialog, statusBar, weekView,
} from './views.js';
import { canScan, scanForPairLink } from './scanner.js';
import { browserKind } from './browser-policy.js';
import { describeError } from './messages.js';

const SAVE_SYNC_DELAY_MS = 2000;
const SWIPE_CLICK_GUARD_MS = 400;

class App {
  constructor(root, store, client) {
    this.root = root;
    this.store = store;
    this.client = client;
    this.screen = 'week';
    this.anchor = localIsoDate(new Date());
    this.online = navigator.onLine !== false;
    this.syncing = false;
    this.lastError = null;
    this.lastAttemptAt = 0;
    this.skewMs = 0;
    this.persistent = null;
    this.updateReady = false;
    this.registration = null;
    this.updateState = 'serviceWorker' in navigator ? 'idle' : 'unsupported';
    this.updateDetail = '';
    this.lastUpdateCheckAt = 0;
    this.checkingUpdate = false;
    this.applyRequested = false;     // für den wartenden Worker ist SKIP_WAITING schon raus (keine Neulade-Schleife)
    this.pairing = { address: '', code: '', deviceName: '', busy: false, error: '' };
    this.saveTimer = null;
    this.pushTimer = null;
    this.pushBusy = false;
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
    };
  }

  get paired() {
    const meta = this.store.getMeta();
    return Boolean(meta.token && meta.address);
  }

  async start() {
    this.captureFragment();
    if (!this.paired) this.screen = 'pair';
    window.addEventListener('online', () => { this.online = true; this.trigger('online'); this.render(); });
    window.addEventListener('hashchange', () => { if (this.captureFragment()) this.render(); });
    window.addEventListener('offline', () => { this.online = false; this.render(); });
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible') return;
      this.trigger('visible');
      this.updatePushSchedule();
      this.checkForUpdate('visible');
      this.maybeApplyUpdate();
    });
    // Ein Dialog, der sich schließt, kann der letzte Grund gewesen sein, ein wartendes Update aufzuschieben.
    // `close` bubbelt nicht: Capture fängt es am Dokument.
    document.addEventListener('close', () => this.maybeApplyUpdate(), true);
    this.registerServiceWorker();
    this.listenForNotificationClicks();
    this.render();
    this.persistent = await requestPersistentStorage();
    this.render();
    this.trigger('start');
    this.updatePushSchedule();
    this.openDayFromLink();
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
      return testResultText(error instanceof RelayError ? error.kind : 'server');
    }
  }

  async disablePush() {
    this.pushError = null;
    const { relay_secret: secret } = this.store.getMeta();
    try {
      (await this.subscription())?.unsubscribe();
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
    if (this.pushBusy) return;
    this.pushBusy = true;
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
      await syncSchedule({ client: this.relay, secret: meta.relay_secret, subscription: subscription.toJSON(), items: blobs });
      await this.store.setMeta({ push_signature: plan, push_sent_at: now });
      this.pushError = null;
    } catch (error) {
      if (!(error instanceof RelayError)) logFailure('Benachrichtigungs-Zeitplan senden', error);
      this.pushError = error instanceof RelayError ? error.message : withDetail('Der Zeitplan für die Benachrichtigungen ließ sich nicht senden.', error);
    } finally {
      this.pushBusy = false;
    }
  }

  // --- Koppeln über den Link -------------------------------------------------------------------

  captureFragment() {
    const link = parsePairFragment(location.hash);
    if (!link) return false;
    this.pairing = { ...this.pairing, address: `${link.host}:${link.port}`, code: link.code, error: '' };
    this.screen = 'pair';
    // Das Fragment trägt den Einmalcode: nicht in der Adresszeile oder im Verlauf stehen lassen.
    history.replaceState(null, '', location.pathname + location.search);
    return true;
  }

  async submitPairing({ address, code, deviceName }) {
    const target = parseHostPort(address);
    if (!target) {
      this.pairing = { address, code, deviceName, busy: false, error: 'Die Adresse muss eine private IPv4-Adresse sein, zum Beispiel 192.168.178.20:17654.' };
      this.render();
      return;
    }
    this.pairing = { address, code, deviceName, busy: true, error: '' };
    this.render();
    try {
      await this.client.pair({ host: target.host, port: target.port, code, deviceName: deviceName.trim() || 'Android-Handy' });
      await this.store.setMeta({ device_name: deviceName.trim() });
      this.pairing = { address: '', code: '', deviceName: '', busy: false, error: '' };
      this.lastError = null;
      this.screen = 'week';
      this.render();
      this.trigger('manual');
    } catch (error) {
      this.pairing = { address, code, deviceName, busy: false, error: describeError(error, this.errorEnv(address)).text };
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
        this.pairing = { ...this.pairing, address: `${link.host}:${link.port}`, code: link.code, error: '' };
        this.render();
      }
    } catch (error) {
      logFailure('Kamera beim Koppeln', error);
      message.textContent = withDetail('Die Kamera ist nicht verfügbar oder nicht freigegeben. Bitte Adresse und Code eintippen oder die Kamera-App benutzen.', error);
    }
  }

  // --- Abgleich ----------------------------------------------------------------------------------

  trigger(name) {
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
    try {
      const result = await this.client.sync();
      this.lastError = null;
      if (!result.discarded) this.skewMs = clockSkewMs(this.store.getMeta().server_time, new Date());
      this.updatePushSchedule();
    } catch (error) {
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

  conflictList() {
    return conflictsModel(this.store.getMeta().conflicts);
  }

  render() {
    const focusKey = focusKeyToRestore({ ...focusState(this.root), last: this.lastFocusKey });
    if (this.screen === 'pair') {
      this.shell = null;
      clear(this.root);
      this.root.append(pairView({
        address: this.pairing.address, code: this.pairing.code,
        deviceName: this.pairing.deviceName || this.store.getMeta().device_name || deviceNameFromUserAgent(navigator.userAgent),
        error: this.pairing.error,
        busy: this.pairing.busy, canScan: canScan(), canCancel: this.paired,
      }, {
        submit: (values) => this.submitPairing(values),
        change: (field, value) => { this.pairing[field] = value; },
        scan: () => this.scanPairing(),
        cancel: () => { this.screen = 'week'; this.render(); },
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
      updateReady: this.updateReady, conflictCount: conflicts.length,
      errorDays: this.store.errorCount(), errorEnv: this.errorEnv(meta.address ? `${meta.address.host}:${meta.address.port}` : ''),
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

  /** Was die Fehlermeldung über Browser und Adresse wissen darf (#275). */
  errorEnv(address) {
    return { browser: browserKind(navigator.userAgent, navigator.userAgentData), address };
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

  async openSettings(initialTab = 'connection') {
    const meta = this.store.getMeta();
    const push = await this.pushModelNow();
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
        address: meta.address ? `${meta.address.host}:${meta.address.port}` : '',
        persistent: this.persistent,
        tokenUntil: meta.token_expires_at ? formatDateDe(meta.token_expires_at.slice(0, 10)) : '',
        push,
      },
      updates: { build: BUILD, update: { state: this.updateState, detail: this.updateDetail, auto: Boolean(meta.auto_update) } },
      categories: categoriesModel({
        categories: meta.categories, defaults: meta.defaults, writable: meta.settings_writable, edit: meta.categories_edit,
      }),
    }, {
      pair: () => { this.screen = 'pair'; this.render(); },
      checkUpdate: async () => ({ state: await this.checkForUpdate('manual'), detail: this.updateDetail }),
      resetWindow: () => this.resetWindow(),
      testPush: () => this.sendTestPush(),
      setPush: async (on) => {
        if (on) await this.enablePush(); else await this.disablePush();
        return this.pushModelNow();
      },
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

  openDay(date) {
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
    // An Tagen nach heute öffnet der Editor bei der Reservierung: die Ist-Zeilen sind mit den
    // Standardzeiten vorbelegt, ein Speichern dort legte sonst still eine Ist-Zeit an.
    const startWith = reservationOn && date > today ? 'reservation' : 'work';
    const dialog = editorDialog({
      title: `${formatDateDe(date)}`,
      rows: editorRows(day, meta.defaults, weekdayKey(date), reservation),
      categories: meta.categories,
      defaults: meta.defaults,
      weekday: weekdayKey(date),
      errors: { work: day?.error ?? null, reservation: reservation?.error ?? null },
      lock,
      canClear: Boolean(day && !day.deleted),
      validate: (rows) => validateRows(rows),
      reservation: reservationOn ? {
        rows: reservationRows(reservation, meta.defaults, weekdayKey(date)),
        canClear: Boolean(reservation && !reservation.deleted),
        validate: (rows) => validateReservationRows(rows),
      } : null,
      startWith,
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
            await this.store.saveReservation(date, reservationRowsToSlots(rows));
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

async function main() {
  const root = document.getElementById('app');
  let store;
  try {
    store = new Store(await openDatabase());
    await store.load();
  } catch (error) {
    logFailure('Speicher des Browsers öffnen', error);
    root.append(fatalView(withDetail('Der Speicher des Browsers ist nicht verfügbar (privates Fenster oder gesperrt?). Ohne ihn kann diese App keine Einträge sichern.', error)));
    return;
  }
  await new App(root, store, new SyncClient({ store })).start();
}

main();
