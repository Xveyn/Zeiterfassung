// pwa/app.js
// Verdrahtung: Zustand der Oberfläche, Ereignisse, Abgleich-Auslöser, Service Worker. Die
// Entscheidungen stehen in den getesteten Modulen (`view-model.js`, `sync-policy.js`,
// `messages.js`); hier wird nur zusammengesteckt.
import { addDays, formatDateDe, localIsoDate, mondayOf } from './minutes.js';
import { weekdayKey } from './defaults.js';
import { DEFAULT_WISH, olderState } from './window-policy.js';
import { deviceNameFromUserAgent, parseHostPort, parsePairFragment } from './pairing.js';
import { openDatabase, requestPersistentStorage } from './db.js';
import { Store } from './store.js';
import { SyncClient, SyncError, clockSkewMs } from './sync.js';
import { shouldQueue, shouldSync } from './sync-policy.js';
import { shouldApplyUpdate, shouldCheckForUpdate } from './update-policy.js';
import {
  conflictsModel, dayChanged, desktopHint, editorRows, focusKeyToRestore, hintsModel, olderModel, rowsToSlots, statusModel, validateRows, weekModel,
} from './view-model.js';
import { BUILD } from './sw-core.js';
import { clear, focusByKey, focusState, h } from './dom.js';
import {
  conflictsDialog, confirmDialog, connectionDialog, editorDialog, fatalView, hintsHost, pairView,
  patchHints, scanDialog, statusBar, weekView,
} from './views.js';
import { canScan, scanForPairLink } from './scanner.js';
import { describeError } from './messages.js';

const SAVE_SYNC_DELAY_MS = 2000;

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
    this.lastUpdateCheckAt = 0;
    this.checkingUpdate = false;
    this.applyRequested = false;     // für den wartenden Worker ist SKIP_WAITING schon raus (keine Neulade-Schleife)
    this.pairing = { address: '', code: '', deviceName: '', busy: false, error: '' };
    this.saveTimer = null;
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
      this.checkForUpdate('visible');
      this.maybeApplyUpdate();
    });
    // Ein Dialog, der sich schließt, kann der letzte Grund gewesen sein, ein wartendes Update aufzuschieben.
    // `close` bubbelt nicht: Capture fängt es am Dokument.
    document.addEventListener('close', () => this.maybeApplyUpdate(), true);
    this.registerServiceWorker();
    this.render();
    this.persistent = await requestPersistentStorage();
    this.render();
    this.trigger('start');
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
      this.pairing = { address, code, deviceName, busy: false, error: describeError(error).text };
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
    } catch {
      message.textContent = 'Die Kamera ist nicht verfügbar oder nicht freigegeben. Bitte Adresse und Code eintippen oder die Kamera-App benutzen.';
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
  }

  async runSync() {
    this.syncing = true;
    this.lastAttemptAt = Date.now();
    this.render();
    try {
      const result = await this.client.sync();
      this.lastError = null;
      if (!result.discarded) this.skewMs = clockSkewMs(this.store.getMeta().server_time, new Date());
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
      conflictDates: conflicts.map((conflict) => conflict.date), windowDays: meta.window_days,
    });
    model.older = olderModel(olderState({
      firstDay: model.days[0].date, today: localIsoDate(new Date()), windowDays: meta.window_days,
      windowMax: meta.window_max, wish: meta.window_wish,
    }));
    const hints = hintsModel({
      lastError: this.lastError, excluded: meta.excluded, skewMs: this.skewMs, persistent: this.persistent,
      updateReady: this.updateReady, conflictCount: conflicts.length,
      errorDays: this.store.days().filter((date) => this.store.getDay(date).error).length,
    });
    if (!this.shell) this.shell = this.buildShell();
    patchHints(this.shell.hints, hints, this.hintHandlers);
    this.shell.week.replaceChildren(weekView(model, {
      previous: () => { this.anchor = addDays(this.anchor, -7); this.render(); },
      next: () => { this.anchor = addDays(this.anchor, 7); this.render(); },
      today: () => { this.anchor = localIsoDate(new Date()); this.render(); },
      openDay: (date) => this.openDay(date),
      older: (wish) => this.loadOlder(wish),
    }));
    this.shell.status.update(statusModel({
      paired: this.paired, online: this.online, syncing: this.syncing, pending: this.store.dirtyDates().length,
      lastSyncAt: meta.server_time,
    }));
    this.lastFocusKey = focusByKey(this.root, focusKey) ? focusKey : null;
  }

  /** Hinweise und Statuszeile werden einmal gebaut und danach nur gepatcht (Live-Regionen, Fokus). */
  buildShell() {
    clear(this.root);
    const hints = hintsHost();
    const week = h('div', {});
    const status = statusBar({ sync: () => this.trigger('manual'), connection: () => this.openConnection() });
    this.root.append(h('main', {}, hints, week), status.element);
    return { hints, week, status };
  }

  openConnection() {
    const meta = this.store.getMeta();
    connectionDialog({
      desktopName: meta.desktop_name,
      desktop: meta.desktop,
      update: { state: this.updateState, auto: Boolean(meta.auto_update) },
      window: { days: meta.window_days, max: meta.window_max, wish: meta.window_wish },
      hint: desktopHint(meta),
      address: meta.address ? `${meta.address.host}:${meta.address.port}` : '',
      build: BUILD,
      persistent: this.persistent,
      tokenUntil: meta.token_expires_at ? formatDateDe(meta.token_expires_at.slice(0, 10)) : '',
    }, {
      pair: () => { this.screen = 'pair'; this.render(); },
      checkUpdate: () => this.checkForUpdate('manual'),
      resetWindow: () => this.resetWindow(),
      applyUpdate: () => this.reloadForUpdate(),
      setAutoUpdate: async (on) => {
        await this.store.setMeta({ auto_update: on });
        this.maybeApplyUpdate();
      },
    });
  }

  openDay(date) {
    const day = this.store.getDay(date);
    const meta = this.store.getMeta();
    const today = localIsoDate(new Date());
    const returnKey = focusState(this.root).activeKey;
    let baseline = day;         // Stand beim Öffnen: Speichern prüft, ob der Tag inzwischen anders ist
    const outsideWindow = date > addDays(today, 1) || date < addDays(today, -meta.window_days);
    const dialog = editorDialog({
      title: `${formatDateDe(date)}`,
      rows: editorRows(day, meta.defaults, weekdayKey(date)),
      categories: meta.categories,
      defaults: meta.defaults,
      weekday: weekdayKey(date),
      error: day?.error ?? null,
      outsideWindow,
      canClear: Boolean(day && !day.deleted),
      validate: (rows) => validateRows(rows),
    }, {
      save: async (rows) => {
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
        this.render();
        this.scheduleSyncAfterSave();
        return null;
      },
      clear: (dialog) => confirmDialog({
        title: 'Tag leeren?', text: `Alle Einträge vom ${formatDateDe(date)} werden gelöscht (beim nächsten Abgleich auch am Desktop).`,
        confirmLabel: 'Tag leeren',
      }, async () => {
        try {
          await this.store.clearDay(date);
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
    } catch {
      // Ohne Service Worker läuft die App online weiter; offline starten kann sie dann nicht.
      this.updateState = 'unsupported';
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
    } catch {
      this.updateState = navigator.onLine === false ? 'offline' : 'error';
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

async function main() {
  const root = document.getElementById('app');
  let store;
  try {
    store = new Store(await openDatabase());
    await store.load();
  } catch {
    root.append(fatalView('Der Speicher des Browsers ist nicht verfügbar (privates Fenster oder gesperrt?). Ohne ihn kann diese App keine Einträge sichern.'));
    return;
  }
  await new App(root, store, new SyncClient({ store })).start();
}

main();
