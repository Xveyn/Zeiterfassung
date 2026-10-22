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
import { addDays, isIsoDate, localIsoDate, normalizeSlots, utcStamp, validateSlots } from './minutes.js';
import {
  RESERVATION_HORIZON_DAYS, normalizeReservationSlots, reservationEditable, reservationSignature,
  validateReservationSlots,
} from './reservations.js';
import { blockSignature, categoryRows, validateCategoryRows } from './categories.js';

const DEFAULT_META = Object.freeze({
  address: null,
  token: '',
  token_expires_at: '',
  key: '',                 // Geräteschlüssel k_dev (base64url), kommt verschlüsselt mit der Kopplungsantwort (#249)
  seq: 0,                  // höchster gesendeter Anfragezähler (Replay-Schutz); wird VOR dem Senden abgelegt
  device_id: '',
  desktop_name: '',
  last_pull_at: '',
  categories: [],
  defaults: null,          // Standardzeiten des Desktops (#288); null bei älterem Desktop
  desktop: { name: '', version: '', platform: '' },
  window_days: 90,
  window_wish: 90,         // gewünschtes Fenster in Tagen (#250); der Desktop deckelt
  window_wish_acked: 90,   // der Wunsch, zu dem die letzte angewandte Antwort gehört (#292)
  window_max: null,        // Obergrenze des Desktops; null = kam nicht mit (älterer Desktop)
  window_max_known: false, // erst nach der ersten angewandten Antwort wahr; vorher weiß man nichts
  auto_update: false,      // Updates der PWA automatisch einspielen (#290); gerätelokal, Standard aus
  reservations_enabled: false, // Desktop bietet Reservierungen an (Feld in der Antwort); fehlt es, bleibt alles verborgen
  settings_writable: false,   // Desktop versteht `settings` (Feld `writable_settings` in der Antwort); sonst ist das Bearbeiten aus
  reminders: null,            // Block `reminders` der letzten Antwort (#331); null = Desktop kennt ihn nicht
  push_enabled: false,        // Benachrichtigungen in diesem Gerät eingeschaltet (#331); die Erlaubnis selbst liegt im Browser
  push_signature: null,       // Signatur des zuletzt an den Relay gesendeten Plans
  push_sent_at: 0,            // wann das war (ms); nach 12 h wird auch ein unveränderter Plan erneuert
  relay_secret: '',           // Geheimnis dieses Handys beim Push-Relay (Identität und Bearer); gerätelokal
  categories_edit: null,      // Kategorien-Block des Handys: { modified_at, dirty_version, synced_version, error } oder null
  excluded: false,
  conflicts: [],
  server_time: '',
});

const MAX_RESERVATIONS_PER_REQUEST = 400;      // Gegenstück zu `MAX_RESERVATIONS` in src/mobile_reservations.py
const FUTURE_LIMIT_MS = 14 * 60 * 1000;
const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isDirty = (record) => record.dirty_version > record.synced_version;
const editDirty = (edit) => Boolean(edit) && edit.dirty_version > edit.synced_version;

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
    this._reservations = new Map();
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
    this._reservations.clear();
    for (const { key, value } of await this._adapter.getAll('reservations')) {
      const record = isObject(value) ? {
        entry: value.entry,
        dirty_version: value.dirty_version,
        synced_version: Number.isInteger(value.synced_version) ? value.synced_version : 0,
        error: typeof value.error === 'string' ? value.error : null,
      } : null;
      if (record && validRecord(key, record)) this._reservations.set(key, record);
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
   *  welchem Stand gesendet wurde (`applyResponse` vergleicht danach). Mit `limit` nur die
   *  neuesten `limit` Tage (der Desktop nimmt höchstens 400 je Anfrage), ohne die Tage in `skip`; der Rest bleibt
   *  „nicht übertragen“ und geht im nächsten Durchgang hinaus. */
  snapshotDirty(limit = Infinity, skip = new Set()) {
    const entries = {};
    const versions = {};
    const dates = limit === Infinity ? this.dirtyDates() : [...this.dirtyDates()].sort().reverse();
    for (const date of dates) {
      const record = this._days.get(date);
      if (record.error || skip.has(date)) continue;
      if (Object.keys(entries).length >= limit) break;
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

  _stampAfter(previous, foreign = false) {
    const now = this._now();
    let stamp = utcStamp(now);
    const before = Date.parse(previous);
    if (!Number.isNaN(before) && stamp <= previous) {
      // Mindestens eine Sekunde nach dem bisherigen Stempel — aber nie mehr als
      // FUTURE_LIMIT_MS vor der Uhr: der Server lehnt Stempel mehr als 15 Minuten in der
      // Zukunft ab, und ein vorauslaufender Stempel vom Desktop (Gerät mit falscher Uhr)
      // machte sonst jede Änderung daran zu einem dauerhaften 422. Verliert die Änderung
      // dann gegen den Desktop-Stand, meldet der Abgleich einen Konflikt statt zu klemmen.
      // Nur für Stempel eines ANDEREN Geräts: ein eigener früherer Stempel (Uhr
      // inzwischen zurückgestellt) muss überboten werden, sonst verlöre die Änderung in LWW
      // gegen den eigenen älteren Eintrag.
      const wanted = before + 1000;
      stamp = utcStamp(new Date(foreign ? Math.min(wanted, now.getTime() + FUTURE_LIMIT_MS) : wanted));
    }
    return stamp;
  }

  _isForeign(record) {
    return Boolean(record) && record.entry.device_id !== this._meta.device_id;
  }

  _putIn(map, storeName, date, entry, ops) {
    const old = map.get(date);
    const record = {
      entry,
      dirty_version: (old ? old.dirty_version : 0) + 1,
      synced_version: old ? old.synced_version : 0,
      error: null,
    };
    map.set(date, record);
    ops.push({ store: storeName, op: 'put', key: date, value: record });
  }

  _put(date, entry, ops) {
    this._putIn(this._days, 'entries', date, entry, ops);
  }

  /** Speichert einen Tag (geprüfte Slots). Wirft bei ungültigen Slots oder Datum. */
  async saveDay(date, slots) {
    if (!isIsoDate(date)) throw new Error(`Ungültiges Datum: ${date}`);
    const normalized = normalizeSlots(slots);
    const check = validateSlots(normalized);
    if (!check.ok) throw new Error(check.message);
    const old = this._days.get(date);
    if (old && !old.entry.deleted && signature(old.entry.slots) === signature(normalized)) {
      if (old.error) {                                             // erneut speichern = erneut versuchen
        old.error = null;
        await this._adapter.batch([{ store: 'entries', op: 'put', key: date, value: old }]);
      }
      return;
    }
    const ops = [];
    this._put(date, {
      slots: normalized,
      modified_at: this._stampAfter(old?.entry.modified_at, this._isForeign(old)),
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
      modified_at: this._stampAfter(old.entry.modified_at, this._isForeign(old)),
      device_id: this._meta.device_id,
      deleted: true,
    }, ops);
    await this._adapter.batch(ops);
  }

  /** Markiert einen Tag als vom Server abgelehnt — aber nur, wenn er noch die Version hat, die
   *  gesendet wurde (`version`): wurde er seither geändert, gilt die Ablehnung der älteren
   *  Fassung nicht für die neue. */
  async markDayError(date, message, version) {
    const record = this._days.get(date);
    if (!record) return;
    if (version !== undefined && record.dirty_version !== version) return;
    record.error = String(message);
    await this._adapter.batch([{ store: 'entries', op: 'put', key: date, value: record }]);
  }

  // --- Reservierungen --------------------------------------------------------------------------

  reservationDates() {
    return [...this._reservations.keys()].sort();
  }

  getReservation(date) {
    const record = this._reservations.get(date);
    if (!record) return null;
    return {
      slots: structuredClone(record.entry.slots),
      modified_at: record.entry.modified_at,
      deleted: record.entry.deleted,
      dirty: isDirty(record),
      error: record.error,
    };
  }

  /** Nicht übertragene Änderungen: Ist-Zeiten und Reservierungen zusammen (Statuszeile). */
  pendingCount() {
    const block = this._meta.settings_writable && editDirty(this._meta.categories_edit) ? 1 : 0;
    if (!this._meta.reservations_enabled) return this.dirtyDates().length + block;
    return this.dirtyDates().length + block
      + [...this._reservations.values()].filter((record) => isDirty(record)).length;
  }

  /** Tage mit abgelehntem Stand, Ist-Zeiten und Reservierungen zusammen. Ist die Funktion verborgen
   *  (der Desktop bietet sie nicht an), zählen Reservierungen nicht: man könnte sie nicht ansehen. */
  errorCount() {
    const reservations = this._meta.reservations_enabled ? [...this._reservations.values()] : [];
    const block = this._meta.settings_writable && this._meta.categories_edit?.error ? 1 : 0;
    return [...this._days.values(), ...reservations].filter((record) => record.error).length + block;
  }

  // --- Kategorien (Einstellungen) --------------------------------------------------------------

  categoriesDirty() {
    return editDirty(this._meta.categories_edit);
  }

  /** Speichert den Kategorien-Block (Namen und Standardzeiten zusammen). Die lokale Ansicht
   *  (`categories`, `defaults.category_times`) ändert sich sofort; der Abgleich schickt den Block. */
  async saveCategories({ categories, category_times: categoryTimes }) {
    if (!this._meta.settings_writable || !this._meta.defaults) {
      throw new Error('Der Desktop unterstützt das Bearbeiten der Kategorien nicht. Bitte die Desktop-App aktualisieren.');
    }
    const check = validateCategoryRows(categoryRows(categories, categoryTimes));
    if (!check.ok) throw new Error(check.message);
    if (blockSignature(categories, categoryTimes)
      === blockSignature(this._meta.categories, this._meta.defaults.category_times)) return;
    const old = this._meta.categories_edit;
    await this.setMeta({
      categories: structuredClone(categories),
      defaults: { ...this._meta.defaults, category_times: structuredClone(categoryTimes) },
      categories_edit: {
        modified_at: this._stampAfter(old?.modified_at),
        dirty_version: (old ? old.dirty_version : 0) + 1,
        synced_version: old ? old.synced_version : 0,
        error: null,
      },
    });
  }

  /** Der Block für den nächsten Abgleich (`null`: nichts zu senden, abgelehnt oder Desktop versteht es nicht). */
  snapshotSettings() {
    const edit = this._meta.categories_edit;
    if (!this._meta.settings_writable || !editDirty(edit) || edit.error || !this._meta.defaults) return null;
    return {
      settings: {
        categories: { value: structuredClone(this._meta.categories), modified_at: edit.modified_at },
        category_times: { value: structuredClone(this._meta.defaults.category_times), modified_at: edit.modified_at },
      },
      settingsVersion: edit.dirty_version,
    };
  }

  async markSettingsError(message, version) {
    const edit = this._meta.categories_edit;
    if (!edit || (version !== undefined && edit.dirty_version !== version)) return;
    await this.setMeta({ categories_edit: { ...edit, error: String(message) } });
  }

  /** Speichert die Reservierung eines Tages. Wirft bei ungültigen Slots oder Datum. */
  async saveReservation(date, slots) {
    if (!isIsoDate(date)) throw new Error(`Ungültiges Datum: ${date}`);
    // Der Desktop lehnt Tage hinter heute + 365 mit der ganzen Anfrage ab: gar nicht erst annehmen.
    if (!reservationEditable(date, localIsoDate(this._now()))) {
      throw new Error(`Reservierungen sind nur für heute und höchstens ${RESERVATION_HORIZON_DAYS - 1} Tage im Voraus möglich (365 Tage).`);
    }
    const normalized = normalizeReservationSlots(slots);
    const check = validateReservationSlots(normalized);
    if (!check.ok) throw new Error(check.message);
    const old = this._reservations.get(date);
    if (old && !old.entry.deleted && reservationSignature(old.entry.slots) === reservationSignature(normalized)) {
      if (old.error) {                                             // erneut speichern = erneut versuchen
        old.error = null;
        await this._adapter.batch([{ store: 'reservations', op: 'put', key: date, value: old }]);
      }
      return;
    }
    const ops = [];
    this._putIn(this._reservations, 'reservations', date, {
      slots: normalized, modified_at: this._stampAfter(old?.entry.modified_at), deleted: false,
    }, ops);
    await this._adapter.batch(ops);
  }

  /** „Tag leeren“ für die Reservierung: ein Tombstone, den der nächste Abgleich überträgt. */
  async clearReservation(date) {
    const old = this._reservations.get(date);
    if (!old || old.entry.deleted) return;
    if (old.synced_version === 0) {            // der Desktop kennt den Tag nie: kein Tombstone nötig
      this._reservations.delete(date);
      await this._adapter.batch([{ store: 'reservations', op: 'delete', key: date }]);
      return;
    }
    const ops = [];
    this._putIn(this._reservations, 'reservations', date, {
      slots: [], modified_at: this._stampAfter(old.entry.modified_at), deleted: true,
    }, ops);
    await this._adapter.batch(ops);
  }

  async markReservationError(date, message, version) {
    const record = this._reservations.get(date);
    if (!record) return;
    if (version !== undefined && record.dirty_version !== version) return;
    record.error = String(message);
    await this._adapter.batch([{ store: 'reservations', op: 'put', key: date, value: record }]);
  }

  /** Was der nächste Abgleich an Reservierungen schickt: dirty Tage ohne Fehler, neueste zuerst,
   *  höchstens `limit` (der Desktop nimmt höchstens 400). Form der Anfrage: `{slots, modified_at,
   *  deleted}` — ohne `device_id`, ohne `pause`. */
  snapshotReservations(limit = MAX_RESERVATIONS_PER_REQUEST) {
    const reservations = {};
    const reservationVersions = {};
    for (const date of this.reservationDates().reverse()) {
      const record = this._reservations.get(date);
      if (!isDirty(record) || record.error) continue;
      if (Object.keys(reservations).length >= limit) break;
      reservations[date] = {
        slots: structuredClone(record.entry.slots),
        modified_at: record.entry.modified_at,
        deleted: record.entry.deleted,
      };
      reservationVersions[date] = record.dirty_version;
    }
    return { reservations, reservationVersions };
  }

  /** Wendet die `reservations` der Antwort an (`null`: der Desktop bietet sie nicht an — lokal bleibt
   *  alles stehen, nur die Funktion ist verborgen). Gleiche Regeln wie bei den Ist-Zeiten: ein
   *  gesendeter, unveränderter Tag wird vom Desktop-Stand ersetzt, ein inzwischen geänderter bleibt.
   *  Ein sauberer Tag, den die Antwort nicht kennt, ist am Desktop gelöscht oder vergangen — aber nur
   *  bis `heute + 365`; dahinter gehört er dem Desktop nicht. Ein gesendeter, unveränderter Tag, den
   *  die Antwort nicht kennt, ist erledigt (Tombstone eingelöst, oder vergangen und vom Desktop still
   *  verworfen). */
  _applyReservations(parsed, snapshot, today, ops) {
    // Ein abgelehnter Tag, der inzwischen vergangen ist, lässt sich nicht mehr bearbeiten und würde
    // nie wieder gesendet: aufräumen, sonst bliebe er als „abgelehnt“ und „nicht übertragen“ stehen.
    for (const [date, record] of [...this._reservations]) {
      if (record.error && date < today) {
        this._reservations.delete(date);
        ops.push({ store: 'reservations', op: 'delete', key: date });
      }
    }
    if (parsed.reservations === null || parsed.reservations === undefined) return;
    const remote = new Map(Object.entries(parsed.reservations));
    const horizon = addDays(today, RESERVATION_HORIZON_DAYS);
    const sentVersions = snapshot.reservationVersions ?? {};

    for (const [date, entry] of remote) {
      if (!isIsoDate(date)) continue;
      const record = this._reservations.get(date);
      const sent = sentVersions[date];
      if (record && isDirty(record) && !(sent !== undefined && sent === record.dirty_version)) continue;
      const next = {
        entry: { slots: structuredClone(entry.slots), modified_at: entry.modified_at, deleted: false },
        dirty_version: record ? record.dirty_version : 0,
        synced_version: record ? record.dirty_version : 0,
        error: null,
      };
      this._reservations.set(date, next);
      ops.push({ store: 'reservations', op: 'put', key: date, value: next });
    }
    for (const [date, record] of [...this._reservations]) {
      if (remote.has(date)) continue;
      const sent = sentVersions[date];
      const dropSent = isDirty(record) && sent !== undefined && sent === record.dirty_version;
      const dropClean = !isDirty(record) && date <= horizon;
      if (dropSent || dropClean) {
        this._reservations.delete(date);
        ops.push({ store: 'reservations', op: 'delete', key: date });
      }
    }
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
        // Bei `excluded` verwirft der Desktop gesendete Tage per Self-Heal (Handy länger
        // offline als die letzte Kompaktierung). Das Handy schickt aber nur Tage, die es
        // seit dem letzten Abgleich geändert hat: das ist Arbeit, keine Wiederbelebung.
        // Sie bleibt liegen; der nächste Abgleich (last_pull_at liegt dann hinter dem
        // Watermark) nimmt sie an.
        if (sent !== undefined && sent === record.dirty_version && !parsed.excluded) {
          this._drop(date, ops);
        }
      } else if ((date >= innerFrom && date <= innerTo) || date < pruneBefore || date > pruneAfter) {
        this._drop(date, ops);
      }
    }

    this._applyReservations(parsed, snapshot, today, ops);

    // Kategorien-Block: bestätigt, wenn genau der gesendete Stand noch gilt; ein dirty, nicht
    // (mehr) gesendeter Block bleibt lokal stehen, der Desktop-Stand ersetzt ihn dann nicht.
    const edit = this._meta.categories_edit;
    const sentSettings = snapshot.settingsVersion;
    const confirmed = editDirty(edit) && sentSettings !== undefined && sentSettings === edit.dirty_version;
    const keepLocal = editDirty(edit) && !confirmed;
    const nextDefaults = structuredClone(parsed.defaults ?? null);
    if (keepLocal && nextDefaults && this._meta.defaults) {
      nextDefaults.category_times = structuredClone(this._meta.defaults.category_times);
    }

    this._meta = {
      ...this._meta,
      reminders: parsed.reminders ? structuredClone(parsed.reminders) : null,
      reservations_enabled: parsed.reservations !== null && parsed.reservations !== undefined,
      last_pull_at: parsed.last_pull_at,
      server_time: parsed.server_time,
      settings_writable: Array.isArray(parsed.writable_settings)
        && parsed.writable_settings.includes('categories') && parsed.writable_settings.includes('category_times'),
      categories: keepLocal ? this._meta.categories : [...parsed.categories],
      defaults: nextDefaults,
      categories_edit: confirmed ? { ...edit, synced_version: edit.dirty_version, error: null } : edit,
      desktop: { ...parsed.desktop },
      window_days: parsed.window_days,
      window_max: parsed.window_max ?? null,
      window_max_known: true,
      window_wish_acked: parsed.window_wish_sent ?? this._meta.window_wish_acked,
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
