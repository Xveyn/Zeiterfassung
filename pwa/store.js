// pwa/store.js
// Lokaler Zustand der Handy-Erfassung: erfasste Tage, die Warteschlange der noch nicht
// übertragenen und die Meta-Daten (Adresse, Token, Kategorien …). Rein bis auf den
// Adapter, der das Schreiben übernimmt (IndexedDB in `db.js`, Speicher in den Tests).
//
// Jeder Tag trägt `dirty_version` (steigt mit jeder Änderung) und `synced_version` (der
// Stand, den der Desktop bestätigt hat); „nicht übertragen“ heißt `dirty_version >
// synced_version`. Das schließt die Lücke zwischen Senden und Antwort: wurde der Tag
// inzwischen erneut geändert, bleibt die lokale Fassung stehen und der nächste Abgleich
// merged erneut.
//
// Jede mutierende Methode ändert den Cache synchron und ruft danach EINMAL
// `adapter.batch(ops)`: ein Tag und das neue Token werden nie getrennt geschrieben.
// Transaktionen entstehen in Aufrufreihenfolge, eine zusätzliche Warteschlange braucht
// es nicht. Scheitert das Schreiben, wirft die Methode; der Cache ist dem Speicher dann
// voraus, und die Oberfläche meldet den Fehler.
import { addDays, isIsoDate, normalizeSlots, utcStamp, validateSlots } from './minutes.js';

const DEFAULT_META = Object.freeze({
  address: null,
  token: '',
  token_expires_at: '',
  device_id: '',
  desktop_name: '',
  last_pull_at: '',
  categories: [],
  window_days: 90,
  excluded: false,
  conflicts: [],
  server_time: '',
});

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isDirty = (record) => record.dirty_version > record.synced_version;

function signature(slots) {
  // Reihenfolge der Slots ist keine Änderung (wie am Desktop).
  return JSON.stringify(slots.map((s) => [s.start, s.end, s.pause, s.kategorie]).sort());
}

function validRecord(date, record) {
  if (!isIsoDate(date) || !isObject(record) || !isObject(record.entry)) return false;
  const { entry } = record;
  return Array.isArray(entry.slots) && typeof entry.modified_at === 'string'
    && typeof entry.deleted === 'boolean'
    && Number.isInteger(record.dirty_version) && Number.isInteger(record.synced_version);
}

export class Store {
  constructor(adapter, now = () => new Date()) {
    this._adapter = adapter;
    this._now = now;
    this._days = new Map();
    this._meta = structuredClone(DEFAULT_META);
  }

  /** Liest alles aus dem Adapter. Unbrauchbare Datensätze werden übersprungen, nie geworfen:
   *  eine kaputte Zeile darf die App nicht am Start hindern. */
  async load() {
    this._days.clear();
    for (const { key, value } of await this._adapter.getAll('entries')) {
      const record = isObject(value) ? {
        entry: value.entry,
        dirty_version: value.dirty_version,
        synced_version: Number.isInteger(value.synced_version) ? value.synced_version : 0,
        error: typeof value.error === 'string' ? value.error : null,
      } : null;
      if (record && validRecord(key, record)) this._days.set(key, record);
    }
    const stored = (await this._adapter.getAll('meta')).find((row) => row.key === 'meta');
    this._meta = { ...structuredClone(DEFAULT_META), ...(stored && isObject(stored.value) ? stored.value : {}) };
  }

  // --- Lesen -----------------------------------------------------------------------------------

  getMeta() {
    return structuredClone(this._meta);
  }

  days() {
    return [...this._days.keys()].sort();
  }

  getDay(date) {
    const record = this._days.get(date);
    if (!record) return null;
    return {
      slots: structuredClone(record.entry.slots),
      modified_at: record.entry.modified_at,
      deleted: record.entry.deleted,
      dirty: isDirty(record),
      error: record.error,
    };
  }

  dirtyDates() {
    return this.days().filter((date) => isDirty(this._days.get(date)));
  }

  /** Was der nächste Abgleich schickt: nur Tage ohne Fehler. `versions` merkt sich, mit
   *  welchem Stand gesendet wurde (`applyResponse` vergleicht danach). */
  snapshotDirty() {
    const entries = {};
    const versions = {};
    for (const date of this.dirtyDates()) {
      const record = this._days.get(date);
      if (record.error) continue;
      entries[date] = {
        slots: structuredClone(record.entry.slots),
        modified_at: record.entry.modified_at,
        device_id: this._meta.device_id,
        deleted: record.entry.deleted,
      };
      versions[date] = record.dirty_version;
    }
    return { entries, versions };
  }

  // --- Schreiben -------------------------------------------------------------------------------

  async setMeta(patch) {
    this._meta = { ...this._meta, ...structuredClone(patch) };
    await this._adapter.batch([{ store: 'meta', op: 'put', key: 'meta', value: this._meta }]);
  }

  _stampAfter(previous) {
    let stamp = utcStamp(this._now());
    if (previous && stamp <= previous) {
      stamp = utcStamp(new Date(Date.parse(previous) + 1000));
    }
    return stamp;
  }

  _put(date, entry, ops) {
    const old = this._days.get(date);
    const record = {
      entry,
      dirty_version: (old ? old.dirty_version : 0) + 1,
      synced_version: old ? old.synced_version : 0,
      error: null,
    };
    this._days.set(date, record);
    ops.push({ store: 'entries', op: 'put', key: date, value: record });
  }

  /** Speichert einen Tag (geprüfte Slots). Wirft bei ungültigen Slots oder Datum. */
  async saveDay(date, slots) {
    if (!isIsoDate(date)) throw new Error(`Ungültiges Datum: ${date}`);
    const normalized = normalizeSlots(slots);
    const check = validateSlots(normalized);
    if (!check.ok) throw new Error(check.message);
    const old = this._days.get(date);
    if (old && !old.entry.deleted && signature(old.entry.slots) === signature(normalized)) return;
    const ops = [];
    this._put(date, {
      slots: normalized,
      modified_at: this._stampAfter(old?.entry.modified_at),
      device_id: this._meta.device_id,
      deleted: false,
    }, ops);
    await this._adapter.batch(ops);
  }

  /** „Tag leeren“: ein Tombstone, den der nächste Abgleich überträgt. */
  async clearDay(date) {
    const old = this._days.get(date);
    if (!old || old.entry.deleted) return;
    const ops = [];
    this._put(date, {
      slots: [],
      modified_at: this._stampAfter(old.entry.modified_at),
      device_id: this._meta.device_id,
      deleted: true,
    }, ops);
    await this._adapter.batch(ops);
  }

  async markDayError(date, message) {
    const record = this._days.get(date);
    if (!record) return;
    record.error = String(message);
    await this._adapter.batch([{ store: 'entries', op: 'put', key: date, value: record }]);
  }

  /** Wendet eine geprüfte Antwort an (`sync.parseSyncResponse`). `snapshot` ist, was gesendet
   *  wurde, `today` das lokale Datum des Handys.
   *
   *  - Gesendeter Tag, seither unverändert: der Stand des Desktops ersetzt ihn, der Tag ist
   *    sauber. Seither geändert: die lokale Fassung bleibt, der nächste Abgleich merged erneut.
   *  - Tag, den die Antwort nicht kennt: sauber und im INNEREN Fenster → lokal entfernt; ein
   *    gesendeter, unveränderter (der Desktop hat ihn verworfen, `excluded`) ebenso; ein
   *    nicht übertragener bleibt. Aus „nicht im Fenster“ folgt nie ein Löschen.
   *  - Sauber und weit außerhalb des Fensters → aufgeräumt; außerhalb bleiben nur noch nicht
   *    übertragene Tage.
   *  Das Fenster der PWA ist enger als das des Desktops (die PWA kennt nur ihr eigenes
   *  Datum): Randtage gehören dem Desktop. */
  async applyResponse(parsed, snapshot, today) {
    const ops = [];
    const remote = new Map(Object.entries(parsed.entries));
    const windowStart = addDays(today, -parsed.window_days);
    const innerFrom = addDays(windowStart, 1);
    const innerTo = addDays(today, -1);
    const pruneBefore = addDays(windowStart, -1);
    const pruneAfter = addDays(today, 1);

    for (const [date, entry] of remote) {
      if (!isIsoDate(date)) continue;
      const record = this._days.get(date);
      const sent = snapshot.versions[date];
      if (record && isDirty(record) && !(sent !== undefined && sent === record.dirty_version)) continue;
      const next = {
        entry: structuredClone(entry),
        dirty_version: record ? record.dirty_version : 0,
        synced_version: record ? record.dirty_version : 0,
        error: null,
      };
      this._days.set(date, next);
      ops.push({ store: 'entries', op: 'put', key: date, value: next });
    }

    for (const [date, record] of [...this._days]) {
      if (remote.has(date)) {
        if (!isDirty(record) && (date < pruneBefore || date > pruneAfter)) {
          this._drop(date, ops);
        }
        continue;
      }
      const sent = snapshot.versions[date];
      if (isDirty(record)) {
        if (sent !== undefined && sent === record.dirty_version) this._drop(date, ops);
      } else if ((date >= innerFrom && date <= innerTo) || date < pruneBefore || date > pruneAfter) {
        this._drop(date, ops);
      }
    }

    this._meta = {
      ...this._meta,
      last_pull_at: parsed.last_pull_at,
      server_time: parsed.server_time,
      categories: [...parsed.categories],
      window_days: parsed.window_days,
      excluded: parsed.excluded,
      conflicts: structuredClone(parsed.conflicts),
      token: parsed.token,
      token_expires_at: parsed.expires_at,
    };
    ops.push({ store: 'meta', op: 'put', key: 'meta', value: this._meta });
    await this._adapter.batch(ops);
  }

  _drop(date, ops) {
    this._days.delete(date);
    ops.push({ store: 'entries', op: 'delete', key: date });
  }
}
