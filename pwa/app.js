// pwa/app.js
// Verdrahtung: Zustand der Oberfläche, Ereignisse, Abgleich-Auslöser, Service Worker. Die
// Entscheidungen stehen in den getesteten Modulen (`view-model.js`, `sync-policy.js`,
// `messages.js`); hier wird nur zusammengesteckt.
import { addDays, formatDateDe, localIsoDate, mondayOf } from './minutes.js';
import { deviceNameFromUserAgent, parseHostPort, parsePairFragment } from './pairing.js';
import { openDatabase, requestPersistentStorage } from './db.js';
import { Store } from './store.js';
import { SyncClient, SyncError, clockSkewMs } from './sync.js';
import { shouldSync } from './sync-policy.js';
import {
  conflictsModel, editorRows, hintsModel, rowsToSlots, statusModel, validateRows, weekModel,
} from './view-model.js';
import { BUILD } from './sw-core.js';
import { clear } from './dom.js';
import {
  conflictsDialog, confirmDialog, connectionDialog, editorDialog, fatalView, hintsView, pairView,
  scanDialog, setPairError, statusBar, weekView,
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
    this.pairing = { address: '', code: '', busy: false };
    this.saveTimer = null;
  }

  get paired() {
    const meta = this.store.getMeta();
    return Boolean(meta.token && meta.address);
  }

  async start() {
    this.captureFragment();
    if (!this.paired) this.screen = 'pair';
    window.addEventListener('online', () => { this.online = true; this.trigger('online'); this.render(); });
    window.addEventListener('offline', () => { this.online = false; this.render(); });
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') this.trigger('visible'); });
    this.registerServiceWorker();
    this.render();
    this.persistent = await requestPersistentStorage();
    this.render();
    this.trigger('start');
  }

  // --- Koppeln über den Link -------------------------------------------------------------------

  captureFragment() {
    const link = parsePairFragment(location.hash);
    if (!link) return;
    this.pairing = { ...this.pairing, address: `${link.host}:${link.port}`, code: link.code };
    this.screen = 'pair';
    // Das Fragment trägt den Einmalcode: nicht in der Adresszeile oder im Verlauf stehen lassen.
    history.replaceState(null, '', location.pathname + location.search);
  }

  async submitPairing({ address, code, deviceName }) {
    const target = parseHostPort(address);
    if (!target) {
      setPairError('Die Adresse muss eine private IPv4-Adresse sein, zum Beispiel 192.168.178.20:17654.');
      return;
    }
    this.pairing = { address, code, busy: true };
    this.render();
    try {
      await this.client.pair({ host: target.host, port: target.port, code, deviceName: deviceName.trim() || 'Android-Handy' });
      await this.store.setMeta({ device_name: deviceName.trim() });
      this.pairing = { address: '', code: '', busy: false };
      this.lastError = null;
      this.screen = 'week';
      this.render();
      this.trigger('manual');
    } catch (error) {
      this.pairing = { address, code, busy: false };
      this.render();
      setPairError(describeError(error).text);
    }
  }

  async scanPairing() {
    const abort = new AbortController();
    const { video, message } = scanDialog(() => abort.abort());
    try {
      const link = await scanForPairLink(video, abort.signal, (text) => { message.textContent = text; });
      if (link) {
        document.querySelector('dialog[open]')?.close();
        this.pairing = { ...this.pairing, address: `${link.host}:${link.port}`, code: link.code };
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
    }
  }

  // --- Anzeige -----------------------------------------------------------------------------------

  conflictList() {
    return conflictsModel(this.store.getMeta().conflicts);
  }

  render() {
    clear(this.root);
    if (this.screen === 'pair') {
      this.root.append(pairView({
        address: this.pairing.address, code: this.pairing.code,
        deviceName: this.store.getMeta().device_name || deviceNameFromUserAgent(navigator.userAgent),
        busy: this.pairing.busy, canScan: canScan(), canCancel: this.paired,
      }, {
        submit: (values) => this.submitPairing(values),
        scan: () => this.scanPairing(),
        cancel: () => { this.screen = 'week'; this.render(); },
      }));
      return;
    }
    const meta = this.store.getMeta();
    const conflicts = this.conflictList();
    const model = weekModel({
      getDay: (date) => this.store.getDay(date), anchor: this.anchor, today: localIsoDate(new Date()),
      conflictDates: conflicts.map((conflict) => conflict.date),
    });
    const hints = hintsModel({
      lastError: this.lastError, excluded: meta.excluded, skewMs: this.skewMs, persistent: this.persistent,
      updateReady: this.updateReady, conflictCount: conflicts.length,
      errorDays: this.store.days().filter((date) => this.store.getDay(date).error).length,
    });
    const handlers = {
      pair: () => { this.screen = 'pair'; this.render(); },
      rescan: () => { this.screen = 'pair'; this.render(); },
      retry: () => this.trigger('manual'),
      reload: () => this.reloadForUpdate(),
      conflicts: () => conflictsDialog(conflicts, { openDay: (date) => this.openDay(date) }),
    };
    const main = weekView(model, {
      previous: () => { this.anchor = addDays(this.anchor, -7); this.render(); },
      next: () => { this.anchor = addDays(this.anchor, 7); this.render(); },
      today: () => { this.anchor = localIsoDate(new Date()); this.render(); },
      openDay: (date) => this.openDay(date),
    });
    main.prepend(hintsView(hints, handlers));
    this.root.append(main, statusBar(statusModel({
      paired: this.paired, online: this.online, syncing: this.syncing, pending: this.store.dirtyDates().length,
      lastSyncAt: meta.server_time,
    }), {
      sync: () => this.trigger('manual'),
      connection: () => this.openConnection(),
    }));
  }

  openConnection() {
    const meta = this.store.getMeta();
    connectionDialog({
      desktopName: meta.desktop_name,
      address: meta.address ? `${meta.address.host}:${meta.address.port}` : '',
      build: BUILD,
      persistent: this.persistent,
      tokenUntil: meta.token_expires_at ? formatDateDe(meta.token_expires_at.slice(0, 10)) : '',
    }, { pair: () => { this.screen = 'pair'; this.render(); } });
  }

  openDay(date) {
    const day = this.store.getDay(date);
    const meta = this.store.getMeta();
    const beyondWindow = date > addDays(localIsoDate(new Date()), 1);
    editorDialog({
      title: `${formatDateDe(date)}`,
      rows: editorRows(day),
      categories: meta.categories,
      error: day?.error ?? null,
      beyondWindow,
      canClear: Boolean(day && !day.deleted),
      validate: (rows) => validateRows(rows),
    }, {
      save: async (rows) => {
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
        await this.store.clearDay(date);
        dialog.close();
        this.render();
        this.scheduleSyncAfterSave();
      }),
    });
  }

  // --- Service Worker ----------------------------------------------------------------------------

  async registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    try {
      const registration = await navigator.serviceWorker.register('./sw.js', { type: 'module' });
      const watch = (worker) => worker?.addEventListener('statechange', () => {
        if (worker.state === 'installed' && navigator.serviceWorker.controller) {
          this.updateReady = true;
          this.render();
        }
      });
      if (registration.waiting && navigator.serviceWorker.controller) { this.updateReady = true; this.render(); }
      watch(registration.installing);
      registration.addEventListener('updatefound', () => watch(registration.installing));
      navigator.serviceWorker.addEventListener('controllerchange', () => { if (this.reloading) location.reload(); });
    } catch {
      // Ohne Service Worker läuft die App online weiter; offline starten kann sie dann nicht.
      this.persistentSwFailed = true;
    }
  }

  async reloadForUpdate() {
    const registration = await navigator.serviceWorker.getRegistration();
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
