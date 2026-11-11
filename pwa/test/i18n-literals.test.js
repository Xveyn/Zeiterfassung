// pwa/test/i18n-literals.test.js
// Ratsche gegen neue Nutzertexte im Quelltext: Texte gehören über `t('…')` in den Katalog
// (pwa/i18n/de.js). Geprüft wird am Quelltext mit dem Tokenizer aus test/literals.js, nur die
// Dateien direkt unter pwa/ (der Katalog selbst liegt in i18n/).
//
// Ausgenommen sind: die Argumente von `t(`, der Kontext (erstes Argument) von `logFailure(` und
// `this._log(` sowie jede `console.*(`-Ausgabe — Log-Texte bleiben deutsch.
//
// PENDING sind die Dateien, die noch nicht umgestellt sind. Jede Umstellungs-Aufgabe nimmt ihre
// Dateien aus dieser Liste heraus; der Test verlangt das auch: eine Datei in PENDING ohne Treffer
// ist ein Fehler. Neu erzeugen/prüfen: `node scripts/pwa_text_inventory.mjs [--list]`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { scanLiterals } from './literals.js';
import { looksLikeText } from './text-rule.js';

const root = new URL('../', import.meta.url);
const sources = readdirSync(root).filter((f) => f.endsWith('.js')).sort();

// Stand der Inventur (Treffer in Klammern: Nutzertexte außerhalb der Ausnahmen).
const PENDING = new Set([
  'debug-info.js',     // 27
  'debug-log.js',      // 4
  'pairing.js',        // 1
  'privacy-view.js',   // 4
  'scanner.js',        // 2
  'shift-policy.js',   // 3
  'sw-repair.js',      // 7
  'vault.js',          // 4
]);

// Protokoll-/Krypto-Fehlertexte und Test-Adapter: bleiben deutsch und technisch (Entscheidung der
// Spec, wie am Desktop die Log-Texte), werden nicht angezeigt, sondern über Fehlerarten abgebildet.
const FILE_EXEMPT = new Set(['crypto.js', 'relay-frame.js', 'db.js', 'memory-adapter.js']);

// Einzelne technische Literale in sonst fertigen Dateien (Datei → Texte, mit Grund).
const ALLOWED = {
  'app.js': ['PushManager', 'Notification',               // Feature-Erkennung (Browser-API-Namen)
    '(display-mode: standalone)',                       // Media-Query
    'Zustand',                                          // Zeilenname des Debug-Blocks, mit debug-info.js entscheiden
    'Kein Export vorbereitet', 'Protokoll nicht geleert'], // interne Errors, nie angezeigt (views.js/unpair.js fangen sie mit eigenem Text bzw. Log)
  'lock.js': ['Zeitüberschreitung',                     // Meldung der AbortError-Ausnahme, nie angezeigt (`reasonOf` wählt nach `name`)
    'Zeiterfassung'],                                   // Produktname als rp-/Anzeigename des Passkeys
  'unpair.js': ['Abmeldung am Desktop', 'Push abmelden', 'Sitzungsmerker löschen', 'Protokoll löschen',
    'Lokale Daten löschen', 'Neu laden'],               // Schrittnamen: nur Log-Kontext (`log(step, error)` → Debug-Protokoll), nie angezeigt
  'browser-policy.js': ['Chromium'],                    // Markenname im User-Agent-Vergleich
  'push-blob.js': ['Kein Schlüssel für Benachrichtigungen.', 'Blob zu kurz.'], // Fehler von `open`: nur im Service Worker, dort per logFailure('Push entschlüsseln') im Debug-Protokoll, nie angezeigt
  'diagnose.js': ['[Zeiterfassung] ${}: ${}',            // console-Präfix
    'Failed to update a ServiceWorker: '],               // Chromes englischer Fehlertext, wird nur abgeschnitten
  'view-model.js': ['Bestehende Einträge behalten den alten Namen.'], // exportierte Konstante, von view-model.test.js als String geprüft; mit views.js umstellen (Funktion + Schlüssel)
  'views.js': ['Enter', 'Escape'],                       // KeyboardEvent.key-Werte
  'relay-client.js': ['BMZUZQIW3QNwt2vJp3q47zAAx4lLADWA0_r3kQQeyMT3d_GXsyyTjNlgBd1fOMtuZvlJhsLu1QRbHsT0hQHzC20', // öffentlicher VAPID-Schlüssel
    'Bearer ${}'],                                      // HTTP-Kopfzeile
  'relay-transport.js': ['Error', // Name der Abbruch-Ausnahme
    // Meldungen der Transportfehler: nie angezeigt, `describeError` wählt den Text nach `kind`/`code`; sie landen nur im Debug-Protokoll
    'Der Relay ist nicht erreichbar.',
    'Der Desktop antwortet nicht.',
    'Zu viele Anfragen an den Relay.',
    'Eine zweite Verbindung dieser Web-App hat übernommen.',
    'Der Relay hat die Verbindung abgelehnt.',
    'Die Anfrage ist für den Relay zu groß.',
    'Der Relay kennt nur POST-Anfragen.'],
  'sync.js': [
    // `SyncError`-Meldungen von Protokoll-/Krypto-/Zustandsfehlern: nie angezeigt (`describeError` wählt den Text nach `kind`),
    // nur im Debug-Protokoll; wie die Fehlertexte in crypto.js technisch und deutsch
    'Ungültiger Tag in der Antwort: ${}',
    'Ungültiger Eintrag in der Antwort: ${}',
    'Unbekanntes Protokoll des Desktops.',
    'Antwort ohne gültiges Token.',
    'Antwort ohne Ablauf.',
    'Antwort ohne Serverzeit.',
    'Antwort ohne last_pull_at.',
    'Antwort ohne excluded.',
    'Antwort mit ungültigem Lesefenster.',
    'Antwort ohne Einträge.',
    'Antwort mit ungültigen Kategorien.',
    'Antwort ohne Konfliktliste.',
    'Ungültiger Konflikt in der Antwort.',
    'Die Antwort des Desktops ließ sich nicht entschlüsseln.',
    'Unerwartete, nicht verschlüsselte Fehlerantwort.',
    'Die Antwort des Desktops ist nicht verschlüsselt.',
    'Der Code hat nicht das richtige Format.',
    'Die Adresse muss im privaten Netz liegen.',
    'Der Koppel-Link ist ungültig.',
    'Ungültige Antwort beim Koppeln.',
    'Noch nicht gekoppelt.',
    'Ungültige Antwort auf die Erreichbarkeitsprüfung.',
    'Diese Kopplung ist noch nicht verschlüsselt. Bitte neu koppeln.'],
  'transport.js': ['Bearer ${}', 'Content-Type'],        // HTTP-Kopfzeilen
};

export function findings(source, file = '') {
  const allowed = new Set(ALLOWED[file] ?? []);
  return scanLiterals(source).filter((l) => !l.exempt && l.callee !== 't' && looksLikeText(l.text) && !allowed.has(l.text));
}
const read = (file) => readFileSync(new URL(file, root), 'utf8');

test('scan: texts outside t(, logFailure(, this._log( and console are found; contexts and keys are not', () => {
  const source = [
    "t('a.b');",
    "logFailure('Abgleich fehlgeschlagen', e);",
    "this._log('Antwort übergangen', e);",
    "console.warn('Das ist Log', 'noch mehr Log');",
    "const x = 'Ein Text';",
    "const url = `Fehler ${code} aufgetreten`;",
    "const cls = 'hint warn'; const kind = 'GET'; const id = 'a.b';",
    "// 'Kommentar mit Text'",
    "/* 'Block Text' */ const re = /'Nicht Text'/g;",
    "const d = a / b; const s = 'Nach Division';",
    "const n = `Aussen ${`Innen Text`}`;",
  ].join('\n');
  const texts = findings(source).map((l) => l.text);
  assert.deepEqual(texts, ['Ein Text', 'Fehler ${} aufgetreten', 'Nach Division', 'Innen Text', 'Aussen ${}']);
});

test('scan: an apostrophe in a comment does not open a literal', () => {
  const source = "// it's a comment\nconst x = 'Text hier';\n";
  assert.deepEqual(findings(source).map((l) => l.text), ['Text hier']);
});

for (const file of sources) {
  if (FILE_EXEMPT.has(file)) continue;
  if (PENDING.has(file)) {
    test(`${file}: still has user texts (else remove it from PENDING)`, () => {
      assert.ok(findings(read(file), file).length > 0, `${file} ist umgestellt: aus PENDING nehmen`);
    });
  } else {
    test(`${file}: no user texts outside t(…)`, () => {
      const hits = findings(read(file), file).map((l) => `${file}:${l.line} ${JSON.stringify(l.text)}`);
      assert.deepEqual(hits, [], 'Text gehört in pwa/i18n/de.js und über t(\'…\') in den Code');
    });
  }
}

test('PENDING and the exemptions name existing files', () => {
  for (const file of [...PENDING, ...FILE_EXEMPT, ...Object.keys(ALLOWED)]) assert.ok(sources.includes(file), file);
});
