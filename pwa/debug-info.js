// pwa/debug-info.js
// Technischer Zustand für den Debug-Reiter: bereits gesammelte Parameter rein, beschriftete Zeilen raus.
// Ohne DOM und Browser-API. Bewusst nie dabei: Gerätemodell, Gerätename, Adressen, Geräte-ID — der Text
// wird in Fehlerberichte kopiert. Alles Fehlende heißt `unbekannt`.

const UNKNOWN = 'unbekannt';

/** Eine Browser-Abfrage mit Obergrenze: Ergebnis (auch `undefined`), bei Fehler, Verweigerung oder Zeitüberschreitung
 *  `null` — nie eine Ausnahme und nie länger als `ms`. */
export async function capped(lookup, ms = 2000) {
  let timer;
  try {
    const timeout = new Promise((resolve) => { timer = setTimeout(() => resolve(null), ms); });
    return await Promise.race([Promise.resolve().then(lookup), timeout]);
  } catch {
    return null; // Abfrage nicht verfügbar oder verweigert
  } finally {
    clearTimeout(timer);
  }
}

/** `getRegistration()` liefert `undefined`, wenn nichts registriert ist (das ist eine Auskunft), `null` steht für
 *  eine gescheiterte Abfrage (`capped`). */
export function workerFromRegistration(registration) {
  if (registration === null) return null;
  if (registration === undefined) return { active: false, waiting: false };
  return { active: Boolean(registration.active), waiting: Boolean(registration.waiting) };
}

const text = (value) => (typeof value === 'string' && value.trim() ? value.trim() : null);

/** Name und Hauptversion aus dem User-Agent. Reihenfolge zählt: Edge, Opera und Samsung tragen auch `Chrome/`. */
function browserName(userAgent) {
  const ua = text(userAgent);
  if (!ua) return null;
  const rules = [
    [/(?:EdgA|EdgiOS|Edg)\/(\d+)/, 'Edge'],
    [/SamsungBrowser\/(\d+)/, 'Samsung Internet'],
    [/(?:OPR|OPT)\/(\d+)/, 'Opera'],
    [/(?:Firefox|FxiOS)\/(\d+)/, 'Firefox'],
    [/(?:Chrome|CriOS)\/(\d+)/, 'Chrome'],
    [/Version\/(\d+)[^ ]* (?:Mobile\/[^ ]+ )?Safari\//, 'Safari'],
  ];
  for (const [pattern, name] of rules) {
    const match = pattern.exec(ua);
    if (match) return `${name} ${match[1]}`;
  }
  return null;
}

/** Chrome friert die Android-Version im User-Agent ein; `platformVersion` aus den Client-Hinweisen ist die echte. */
function osName(userAgent, platformVersion) {
  const ua = text(userAgent);
  if (!ua) return null;
  if (/Android/.test(ua)) {
    const hinted = /^(\d+)/.exec(text(platformVersion) ?? '');
    const fromUa = /Android (\d+)/.exec(ua);
    const major = hinted?.[1] ?? fromUa?.[1];
    return major ? `Android ${major}` : 'Android';
  }
  const ios = /(?:iPhone )?OS (\d+)[_\d]* like Mac OS X/.exec(ua);
  if (ios) return `iOS ${ios[1]}`;
  if (/Windows/.test(ua)) return 'Windows';
  if (/Mac OS X/.test(ua)) return 'macOS';
  if (/CrOS/.test(ua)) return 'ChromeOS';
  if (/Linux/.test(ua)) return 'Linux';
  return null;
}

const yesNo = (value) => (typeof value === 'boolean' ? (value ? 'ja' : 'nein') : null);

function workerText(worker) {
  if (!worker || typeof worker !== 'object') return null;
  if (worker.waiting) return 'wartet auf Neustart';
  return worker.active ? 'aktiv' : 'nicht registriert';
}

function notificationText(permission, subscribed) {
  if (permission === 'denied') return 'blockiert';
  if (permission === 'default') return 'nicht gefragt';
  if (permission !== 'granted') return null;
  const sub = yesNo(subscribed);
  return sub ? `erlaubt, Abo ${sub}` : 'erlaubt';
}

function storageText(storage) {
  if (!storage || typeof storage !== 'object') return null;
  const parts = [];
  const persisted = yesNo(storage.persisted);
  if (persisted) parts.push(`dauerhaft ${persisted}`);
  if (Number.isFinite(storage.usage) && storage.usage >= 0) {
    const mb = storage.usage / 1048576;
    parts.push(mb > 0 && mb < 1 ? '< 1 MB' : `${Math.round(mb)} MB`);
  }
  return parts.length ? parts.join(', ') : null;
}

function screenText(screen) {
  if (!screen || !Number.isFinite(screen.width) || !Number.isFinite(screen.height)) return null;
  return `${screen.width} × ${screen.height}`;
}

/** @returns {Array<{label: string, value: string}>} immer die zwölf Zeilen in fester Reihenfolge */
export function describeEnvironment(env) {
  const e = env && typeof env === 'object' ? env : {};
  const pairing = { lan: 'LAN', relay: 'Relay' }[e.pairing];
  const rows = [
    ['Browser', browserName(e.userAgent)],
    ['Betriebssystem', osName(e.userAgent, e.platformVersion)],
    ['Als App installiert', yesNo(e.standalone)],
    ['Online', yesNo(e.online)],
    ['Sprache', text(e.language)],
    ['Bildschirm', screenText(e.screen)],
    ['Build', text(e.build)],
    ['Service Worker', workerText(e.worker)],
    ['Benachrichtigungen', notificationText(e.notification, e.subscribed)],
    ['Speicher', storageText(e.storage)],
    ['Kopplungsweg', pairing ?? null],
    ['Protokoll', Number.isInteger(e.protocol) ? String(e.protocol) : null],
  ];
  return rows.map(([label, value]) => ({ label, value: value ?? UNKNOWN }));
}
