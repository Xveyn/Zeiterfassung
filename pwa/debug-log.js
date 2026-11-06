// pwa/debug-log.js
// Kern des Debug-Protokolls: nur bereinigte Ereignisse, Aufräumen nach Alter und Anzahl, Export.
// DOM-frei; der Speicher kommt herein (IndexedDB in der Seite und im Service Worker, im Speicher in Tests).
// Protokollieren darf nie selbst scheitern: bei einem Speicherfehler wechselt der Kern auf ein Array im Speicher.
import { scrubText } from './log-scrub.js';

export const RETENTION_CHOICES = [1, 7, 30];
export const DEFAULT_RETENTION_DAYS = 7;
export const MAX_ENTRIES = 500;

const RETENTION_KEY = 'log_retention_days';
const DAY_MS = 86_400_000;
const NAME_RE = /^[A-Za-z][A-Za-z0-9_]{0,59}$/;
const RESULT_RE = /^[A-Za-z][A-Za-z0-9_]{0,39}$/;
const SYNC_NUMBERS = ['ms', 'sent', 'received', 'conflicts', 'window'];

function count(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;
}

/** Fehlerereignis; Fremdobjekte (Getter, die werfen) ergeben leere Felder statt einer Ausnahme. */
export function errorEvent(context, error) {
  let name = '';
  let detail = '';
  try {
    if (typeof error === 'string') {
      detail = scrubText(error);
    } else if (error && typeof error === 'object') {
      const rawName = error.name;
      if (typeof rawName === 'string' && NAME_RE.test(rawName)) name = rawName;
      detail = scrubText(error.message);
    }
  } catch {
    // Ein feindliches Fehlerobjekt darf das Protokollieren nicht kippen; es bleibt bei leeren Feldern.
  }
  return { kind: 'error', fields: { context: scrubText(context), name, detail } };
}

/** Abgleich-Ereignis: Positivliste, Zahlen ganzzahlig ≥ 0. */
export function syncEvent(summary) {
  const s = summary && typeof summary === 'object' ? summary : {};
  const fields = { result: typeof s.result === 'string' && RESULT_RE.test(s.result) ? s.result : 'error' };
  for (const key of SYNC_NUMBERS) fields[key] = count(s[key]);
  return { kind: 'sync', fields };
}

function stamp(date) {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function createDebugLog({ store, now = () => new Date() }) {
  let persistent = true;
  let memory = [];
  let memoryId = 1;

  function fallBack() {
    persistent = false;
  }

  async function read() {
    if (persistent) {
      try {
        return await store.all();
      } catch {
        fallBack();
      }
    }
    return memory.slice();
  }

  async function retentionDays() {
    try {
      const value = await store.getConfig(RETENTION_KEY);
      return RETENTION_CHOICES.includes(value) ? value : DEFAULT_RETENTION_DAYS;
    } catch {
      return DEFAULT_RETENTION_DAYS;
    }
  }

  async function prune() {
    try {
      const limit = now().getTime() - (await retentionDays()) * DAY_MS;
      const rows = await read();
      const drop = new Set();
      for (const row of rows) {
        const time = Date.parse(row.at);
        if (Number.isFinite(time) && time < limit) drop.add(row.id);
      }
      const kept = rows.filter((r) => !drop.has(r.id));
      for (const row of kept.slice(0, Math.max(0, kept.length - MAX_ENTRIES))) drop.add(row.id);
      if (drop.size === 0) return;
      const ids = [...drop];
      if (persistent) {
        try {
          await store.remove(ids);
          return;
        } catch {
          fallBack();
          return;
        }
      }
      memory = memory.filter((r) => !drop.has(r.id));
    } catch {
      // Aufräumen ist Pflege, kein Pflichtteil: ein Fehler hier darf nie nach außen dringen.
    }
  }

  async function record(event) {
    try {
      const entry = { at: stamp(now()), ...event };
      if (persistent) {
        try {
          await store.add(entry);
        } catch {
          fallBack();
        }
      }
      if (!persistent) memory.push({ id: memoryId++, ...entry });
    } catch {
      // Protokollieren darf nie selbst scheitern.
    }
    await prune();
  }

  return {
    recordError: (context, error) => record(errorEvent(context, error)),
    recordSync: (summary) => record(syncEvent(summary)),
    async entries() {
      return (await read()).reverse();
    },
    async clear() {
      memory = [];
      // Auch im Speicher-Modus: der Ausfall kann vorübergehend gewesen sein, dann liegen in IndexedDB noch Einträge,
      // die sonst nach einem Neuladen wieder auftauchten. Liefert `true`, wenn der Speicher wirklich geleert ist, sonst `false`.
      try {
        await store.clear();
        return true;
      } catch {
        return false; // der Aufrufer meldet „nicht gelöscht“, die Einträge im Speicher sind trotzdem weg
      }
    },
    retentionDays,
    async setRetentionDays(days) {
      if (!RETENTION_CHOICES.includes(days)) throw new RangeError(`Haltezeit ${String(days)} nicht erlaubt`);
      await store.setConfig(RETENTION_KEY, days);
      await prune();
    },
    prune,
    isPersistent: () => persistent,
  };
}

/** Eine Zeile je Eintrag; Fehler als WARN, Abgleiche als INFO. */
export function formatEntry(entry) {
  const f = entry.fields || {};
  if (entry.kind === 'error') {
    return `${entry.at} WARN ${f.context}: ${f.name ? `${f.name}: ` : ''}${f.detail}`;
  }
  if (entry.kind === 'sync') {
    return `${entry.at} INFO Abgleich ${f.result}, ${f.ms} ms, gesendet ${f.sent}, empfangen ${f.received}, `
      + `Konflikte ${f.conflicts}, Fenster ${f.window}`;
  }
  return `${entry.at} INFO ${entry.kind}`;
}

// Gespeichertes wird beim Export erneut bereinigt: ein Eintrag aus einer älteren Fassung der Regeln
// darf das Handy nicht mit einer Adresse verlassen.
function rescrub(entry) {
  const at = typeof entry.at === 'string' ? entry.at : '';
  const f = entry.fields || {};
  if (entry.kind === 'sync') return { at, ...syncEvent(f) };
  return { at, ...errorEvent(f.context, { name: f.name, message: f.detail }) };
}

/** Kopfzeilen `Label: Wert` (feste, geprüfte Werte, unverändert), Leerzeile, Einträge neueste zuerst. */
export function formatExport({ info = [], entries = [] }) {
  const head = info.map(({ label, value }) => `${label}: ${value}`);
  const lines = entries
    .map(rescrub)
    .map((e, i) => ({ e, i }))
    .sort((a, b) => (a.e.at < b.e.at ? 1 : a.e.at > b.e.at ? -1 : a.i - b.i))
    .map(({ e }) => formatEntry(e));
  return [...head, '', ...lines].join('\n');
}

/** Teilen, wo möglich; sonst (oder bei einem Fehler des Teilens) als Datei. Abbruch durch den Nutzer ist kein Fehler. */
export async function deliverExport(text, { canShare, share, download }) {
  if (canShare()) {
    try {
      await share(text);
      return 'shared';
    } catch (error) {
      if (error && error.name === 'AbortError') return 'cancelled';
    }
  }
  await download(text);
  return 'downloaded';
}
