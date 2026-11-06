// pwa/log-scrub.js
// Bereinigung für das Debug-Protokoll: ein Text darf das Handy nur ohne Adressen, Namen, Schlüssel
// und Zeiten verlassen (kopiert wird er in Tickets). DOM-frei; Ergebnis ist idempotent, weil die
// Platzhalter selbst von keiner Regel getroffen werden.

export const DEFAULT_MAX_LENGTH = 240;

// Endungen, die Dateinamen sind und keine Hosts (`sw.js`).
const FILE_EXTENSIONS = new Set(['js', 'mjs', 'json', 'css', 'html', 'txt']);

const URL_RE = /\b[a-z][a-z0-9+.-]*:\/\/[^\s"'<>)]+/gi;
// Pfade nach den URLs (deren Pfadteil ist dann schon weg). Unix: absolut, mindestens zwei Segmente (`and/or`, `/sw.js` bleiben).
const UNIX_PATH_RE = /(?<![\w<>.:/\\-])\/(?:[^\s/"'<>]+\/)+[^\s/"'<>]+/g;
const WIN_PATH_RE = /(?<![\w])[A-Za-z]:[\\/][^\s"'<>]+/g;
const UNC_PATH_RE = /\\\\[^\s\\"'<>]+\\[^\s"'<>]+/g;
const MAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/g;
const IPV6_BRACKET_RE = /\[[0-9a-fA-F:.]+\](?::\d{1,5})?/g;
// Auch IPv4-gemappt (`::ffff:1.2.3.4`). Kandidaten aus Hex und Doppelpunkten; nur mit `::` oder allen acht Gruppen eine Adresse,
// sonst wäre `08:00:30` eine.
const IPV6_RE = /(?<![\w:])(?:[0-9a-f]{0,4}:){2,7}(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9a-f]{0,4})(?![\w:])/gi;
const IPV4_RE = /\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b/g;
const HOST_RE = /\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+([a-z]{2,})\b(?::\d{1,5})?/gi;
const LOCALHOST_RE = /\blocalhost\b(?::\d{1,5})?/gi;
// Mindestens eine Ziffer: ohne sie träfe die Regel lange Bezeichner wie `ServiceWorkerRegistration`.
const KEY_RE = /(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])/g;
const ISO_DATE_RE = /(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)/g;
const DE_DATE_RE = /\b\d{1,2}\.\d{1,2}\.\d{4}\b/g;
const TIME_RE = /(?<!\d)\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?!\d)/g;
const QUOTED_RE = /"[^"]*"/g;

function isIpv6(candidate) {
  return candidate.includes('::') || candidate.split(':').length === 8;
}

/** Text ohne Adressen, Mails, Hosts, Schlüssel, Pfade, Daten und Zeiten, in einer Zeile und gekürzt. */
export function scrubText(value, maxLength = DEFAULT_MAX_LENGTH) {
  if (typeof value !== 'string') return '';
  let text = value
    .replace(URL_RE, '<url>')
    .replace(UNC_PATH_RE, '<pfad>')
    .replace(WIN_PATH_RE, '<pfad>')
    .replace(UNIX_PATH_RE, '<pfad>')
    .replace(MAIL_RE, '<mail>')
    .replace(IPV6_BRACKET_RE, '<ip>')
    .replace(IPV6_RE, (m) => (isIpv6(m) ? '<ip>' : m))
    .replace(IPV4_RE, '<ip>')
    .replace(HOST_RE, (m, tld) => (FILE_EXTENSIONS.has(tld.toLowerCase()) ? m : '<host>'))
    .replace(LOCALHOST_RE, '<host>')
    .replace(KEY_RE, (m) => (/\d/.test(m) ? '<schlüssel>' : m))
    .replace(ISO_DATE_RE, '<datum>')
    .replace(DE_DATE_RE, '<datum>')
    .replace(TIME_RE, '<zeit>')
    .replace(QUOTED_RE, '<text>');
  text = text.replace(/\s+/g, ' ').trim();
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}
