// pwa/debug-info.js
// Technischer Zustand für den Debug-Reiter: bereits gesammelte Parameter rein, beschriftete Zeilen raus.
// Ohne DOM und Browser-API. Bewusst nie dabei: Gerätemodell, Gerätename, Adressen, Geräte-ID — der Text
// wird in Fehlerberichte kopiert. Alles Fehlende heißt `unbekannt`.
// Die Zeilen stehen im Debug-Reiter und gehen unverändert in den Export; die Texte kommen daher aus dem Katalog
// (erst zur Laufzeit, nie beim Import). Eigennamen von Browsern und Systemen sind keine Übersetzung.
import { t } from './i18n.js';

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

const yesNo = (value) => (typeof value === 'boolean'
  ? (value ? t('einstellungen.verbindung.ja') : t('einstellungen.verbindung.nein')) : null);

function workerText(worker) {
  if (!worker || typeof worker !== 'object') return null;
  if (worker.waiting) return t('debug.worker.wartet');
  return worker.active ? t('debug.worker.aktiv') : t('debug.worker.nicht_registriert');
}

function notificationText(permission, subscribed) {
  if (permission === 'denied') return t('debug.benachrichtigung.blockiert');
  if (permission === 'default') return t('debug.benachrichtigung.nicht_gefragt');
  if (permission !== 'granted') return null;
  const sub = yesNo(subscribed);
  return sub ? t('debug.benachrichtigung.erlaubt_abo', { abo: sub }) : t('debug.benachrichtigung.erlaubt');
}

function storageText(storage) {
  if (!storage || typeof storage !== 'object') return null;
  const parts = [];
  const persisted = yesNo(storage.persisted);
  if (persisted) parts.push(t('debug.speicher.dauerhaft', { wert: persisted }));
  if (Number.isFinite(storage.usage) && storage.usage >= 0) {
    const mb = storage.usage / 1048576;
    parts.push(mb > 0 && mb < 1 ? t('debug.speicher.unter_1mb') : t('debug.speicher.mb', { mb: Math.round(mb) }));
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
    [t('debug.zeile.browser'), browserName(e.userAgent)],
    [t('debug.zeile.betriebssystem'), osName(e.userAgent, e.platformVersion)],
    [t('debug.zeile.installiert'), yesNo(e.standalone)],
    [t('debug.zeile.online'), yesNo(e.online)],
    [t('debug.zeile.sprache'), text(e.language)],
    [t('debug.zeile.bildschirm'), screenText(e.screen)],
    [t('debug.zeile.build'), text(e.build)],
    [t('debug.zeile.service_worker'), workerText(e.worker)],
    [t('debug.zeile.benachrichtigungen'), notificationText(e.notification, e.subscribed)],
    [t('debug.zeile.speicher'), storageText(e.storage)],
    [t('debug.zeile.kopplungsweg'), pairing ?? null],
    [t('debug.zeile.protokoll'), Number.isInteger(e.protocol) ? String(e.protocol) : null],
  ];
  return rows.map(([label, value]) => ({ label, value: value ?? t('einstellungen.verbindung.unbekannt') }));
}
