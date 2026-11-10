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
  'app.js',            // 24
  'categories.js',     // 20
  'debug-info.js',     // 27
  'debug-log.js',      // 4
  'lock.js',           // 14
  'messages.js',       // 35
  'minutes.js',        // 14
  'pairing.js',        // 1
  'privacy-view.js',   // 4
  'push-blob.js',      // 3
  'push-message.js',   // 22
  'push-policy.js',    // 5
  'relay-client.js',   // 13
  'relay-transport.js', // 8
  'scanner.js',        // 2
  'shift-policy.js',   // 3
  'store.js',          // 4
  'sw-repair.js',      // 7
  'sync-errors.js',    // 1
  'sync.js',           // 25
  'unpair.js',         // 6
  'update-policy.js',  // 7
  'vault.js',          // 4
  'view-model.js',     // 102
  'views.js',          // 194
]);

// Protokoll-/Krypto-Fehlertexte und Test-Adapter: bleiben deutsch und technisch (Entscheidung der
// Spec, wie am Desktop die Log-Texte), werden nicht angezeigt, sondern über Fehlerarten abgebildet.
const FILE_EXEMPT = new Set(['crypto.js', 'relay-frame.js', 'db.js', 'memory-adapter.js']);

// Einzelne technische Literale in sonst fertigen Dateien (Datei → Texte, mit Grund).
const ALLOWED = {
  'browser-policy.js': ['Chromium'],                    // Markenname im User-Agent-Vergleich
  'diagnose.js': ['[Zeiterfassung] ${}: ${}',            // console-Präfix
    'Failed to update a ServiceWorker: '],               // Chromes englischer Fehlertext, wird nur abgeschnitten
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
