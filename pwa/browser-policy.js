// pwa/browser-policy.js
// Welche Engine steckt hinter dem Browser, und sperrt sie den Zugriff einer https-Seite auf den Rechner
// im WLAN (`http://<LAN-IP>`)? Reine Entscheidung ohne Browser-API (getestet in test/browser-policy.test.js);
// die Umgebung (`navigator.userAgent`, `navigator.userAgentData`) kommt als Parameter herein.
//
// Ein `fetch`-Fehler verrät den Grund nicht: der Rechner kann aus sein oder der Browser die Verbindung
// sperren. Deshalb dient das hier nur dazu, eine Meldung nach einem Fehlschlag um die wahrscheinliche
// Ursache zu ergänzen (#275) — nie, den Zugriff vorab zu verweigern.

/** `'chromium'` | `'firefox'` | `'ios'` | `'safari'` | `'unknown'`. Jeder Browser auf dem iPhone/iPad ist
 *  WebKit, auch einer namens „Chrome“ oder „Firefox“; deshalb zuerst. */
export function browserKind(userAgent, userAgentData) {
  const ua = typeof userAgent === 'string' ? userAgent : '';
  if (/iPhone|iPad|iPod/.test(ua)) return 'ios';
  if (/Firefox\//.test(ua)) return 'firefox';
  const brands = Array.isArray(userAgentData?.brands) ? userAgentData.brands : [];
  if (brands.some((entry) => entry?.brand === 'Chromium') || /Chrome\/|Chromium\//.test(ua)) return 'chromium';
  if (/Safari\//.test(ua)) return 'safari';
  return 'unknown';
}

/** Engines, die eine https-Seite nicht auf `http://` im WLAN zugreifen lassen (Mixed Content):
 *  bei Safari/iOS beobachtet (#358), bei Firefox aus demselben Mechanismus geschlossen. */
export function blocksLan(kind) {
  return kind === 'firefox' || kind === 'ios' || kind === 'safari';
}
