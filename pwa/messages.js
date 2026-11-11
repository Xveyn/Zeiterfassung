// pwa/messages.js
// Fehler einordnen für Menschen: jede `SyncError.kind` bekommt einen deutschen Text und einen
// Ausweg. Die Arten stehen in `test/fixtures/errors.json`; der Test verlangt für jede einen
// eigenen Text, damit ein neuer Fehlercode im Server nicht als „unbekannter Fehler" endet.

import { blocksLan } from './browser-policy.js';
import { t } from './i18n.js';
import { PROTOCOL } from './pairing.js';

const ADDRESS_RE = /^\d{1,3}(\.\d{1,3}){3}:\d{1,5}$/;

function repairText(code) {
  if (code === 'token_revoked') return t('fehler.neu_koppeln.token_revoked');
  if (code === 'token_expired') return t('fehler.neu_koppeln.token_expired');
  return t('fehler.neu_koppeln.unbekannt');
}

function vaultText(code) {
  if (code === 'key_unavailable') return t('fehler.vault.key_unavailable');
  if (code === 'unsupported') return t('fehler.vault.unsupported');
  return t('fehler.vault.unreadable');
}

function defaultError() {
  return { text: t('fehler.abgleich_fehlgeschlagen'), action: 'retry' };
}

/** Text für „offline“. Ein Netzfehler verrät den Grund nicht (Rechner aus oder Browser sperrt): der Text nennt
 *  deshalb beides, bei einem Browser, der den Zugriff bekanntermaßen sperrt, die wahrscheinlichere Ursache
 *  zuerst, und einen Test, der die beiden trennt (#275). Die Adresse erscheint nur in der Form `host:port`. */
function offlineText({ browser, address } = {}) {
  const base = blocksLan(browser) ? t('fehler.offline.browser_sperrt') : t('fehler.offline.lan');
  if (typeof address !== 'string' || !ADDRESS_RE.test(address) || Number(address.split(':')[1]) > 65535) return base;
  return t('fehler.offline.mit_adresse', { base, address });
}

/** Text und Ausweg, wenn der Speicher verschlüsselte Daten enthält, die sich nicht öffnen lassen (`vault.js`).
 *  `canReset`: Neu koppeln (löscht die lokalen Daten) ist sinnvoll; bei einem neueren Format nicht, dort hilft nur
 *  die neue Version. Ein unbekannter Fehler bietet das Neu-Koppeln an, damit der Nutzer nie in einer Sackgasse landet. */
export function describeVaultError(error) {
  const code = error && typeof error === 'object' ? error.code : undefined;
  return { text: vaultText(code), canReset: code !== 'unsupported' };
}

/** @param {unknown} error
 *  @param {{browser?: string, address?: string}} [env] Browser-Art (`browser-policy.browserKind`) und
 *  Adresse des Desktops; nur der Text für „offline“ nutzt sie. */
export function describeError(error, env = {}) {
  if (!error || typeof error !== 'object' || typeof error.kind !== 'string') return defaultError();
  const server = typeof error.message === 'string' ? error.message : '';
  switch (error.kind) {
    case 'offline':
      if (env.transport === 'relay') return { text: t('fehler.offline.relay'), action: 'retry' };
      return { text: offlineText(env), action: 'rescan' };
    case 'desktop_silent':
      return { text: t('fehler.desktop_schweigt'), action: 'retry' };
    case 'throttled':
      return { text: t('fehler.zu_viele_anfragen'), action: 'retry' };
    case 'too_large':
      return { text: error.code === 'request_too_large' ? t('fehler.zu_gross.anfrage') : t('fehler.zu_gross.antwort'), action: null };
    case 'timeout':
      return { text: t('fehler.zeitueberschreitung'), action: 'retry' };
    case 'address':
      return { text: t('fehler.falsche_adresse'), action: 'rescan' };
    case 'repair':
      return { text: repairText(error.code), action: 'pair' };
    case 'not_paired':
      return { text: t('fehler.nicht_gekoppelt'), action: 'pair' };
    case 'browser':
      return { text: t('fehler.browser_cross_site'), action: null };
    case 'invalid_code':
      return { text: t('fehler.code_ungueltig'), action: 'pair' };
    case 'clock_skew':
      return { text: t('fehler.uhr_abweichung'), action: null };
    case 'invalid_entry':
      return { text: t('fehler.tag_abgelehnt', { grund: server || t('fehler.tag_abgelehnt.ohne_grund') }), action: null };
    case 'crypto':
      return { text: t('fehler.verschluesselung.passt_nicht'), action: 'pair' };
    case 'encryption':
      return { text: t('fehler.verschluesselung.fehlt'), action: 'pair' };
    case 'transient':
      if (error.code === 'replaced') return { text: t('fehler.verbindung_ersetzt'), action: 'retry' };
      if (error.code === 'key_unavailable') {
        return { text: t('fehler.schluesselbund'), action: 'retry' };
      }
      return { text: t('fehler.desktop_beschaeftigt'), action: 'retry' };
    case 'server':
      return { text: t('fehler.desktop_intern'), action: 'retry' };
    case 'protocol': {
      // Nennt der Desktop sein Protokoll (#290), sagen wir, welche Seite die ältere ist. Die Zahl kommt im
      // Klartext und ist damit nur ein Hinweis, kein Beleg.
      const theirs = error.supportedProtocol;
      if (Number.isInteger(theirs) && theirs > 0 && theirs < PROTOCOL) {
        return { text: t('fehler.protokoll.desktop_aelter'), action: null };
      }
      if (Number.isInteger(theirs) && theirs > PROTOCOL) {
        return { text: t('fehler.protokoll.desktop_neuer'), action: 'reload' };
      }
      return { text: t('fehler.protokoll.unpassend'), action: null };
    }
    case 'client_error':
      return { text: t('fehler.anfrage_abgelehnt', { grund: server || t('fehler.anfrage_abgelehnt.ohne_grund') }), action: null };
    default:
      return defaultError();
  }
}
