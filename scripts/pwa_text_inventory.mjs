// Inventur der Nutzertexte in pwa/*.js: je Datei die String-Literale, die wie Text aussehen
// (ein Buchstabe und Leerraum oder Großbuchstabe am Anfang), außerhalb von t(, logFailure(,
// this._log( und console.*(. Grundlage der PENDING-Liste in pwa/test/i18n-literals.test.js.
//   node scripts/pwa_text_inventory.mjs          # Zusammenfassung
//   node scripts/pwa_text_inventory.mjs --list   # mit allen Fundstellen
import { readdirSync, readFileSync } from 'node:fs';
import { scanLiterals } from '../pwa/test/literals.js';
import { looksLikeText } from '../pwa/test/text-rule.js';

const root = new URL('../pwa/', import.meta.url);
const list = process.argv.includes('--list');
let total = 0;
for (const file of readdirSync(root).filter((f) => f.endsWith('.js')).sort()) {
  const hits = scanLiterals(readFileSync(new URL(file, root), 'utf8')).filter((l) => !l.exempt && looksLikeText(l.text));
  if (!hits.length) continue;
  total += hits.length;
  console.log(`${file}: ${hits.length}`);
  if (list) for (const h of hits) console.log(`  ${h.line}: ${JSON.stringify(h.text)}`);
}
console.log(`insgesamt: ${total}`);
