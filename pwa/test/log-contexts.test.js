// pwa/test/log-contexts.test.js
// Der Kontext eines Protokolleintrags ist fester Text: durch ihn darf nie ein Nutzerwert ins Debug-
// Protokoll gelangen (Namen, Adressen, Geheimnisse). Geprüft wird am Quelltext.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const root = new URL('../', import.meta.url);
const LITERAL = /^(?:'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\$]|\\.|\$(?!\{))*`)\s*[,)]/;

function offenders(file, callee) {
  const source = readFileSync(new URL(file, root), 'utf8');
  const call = new RegExp(`(?<![\\w.])${callee}\\(`, 'g');
  const bad = [];
  let found = 0;
  for (const match of source.matchAll(call)) {
    const rest = source.slice(match.index + match[0].length).trimStart();
    if (/^(?:async\s+)?(?:function|\w+\s*\{)/.test(rest)) continue;   // eine Deklaration, kein Aufruf
    found += 1;
    if (!LITERAL.test(rest)) bad.push(rest.slice(0, 60));
  }
  return { bad, found };
}

for (const file of ['app.js', 'sw.js', 'sync.js']) {
  test(`${file}: logFailure gets a text literal as context`, () => {
    const { bad, found } = offenders(file, 'logFailure');
    assert.ok(found > 0, 'keine Aufrufe gefunden: Muster veraltet?');
    assert.deepEqual(bad, []);
  });
}

test('relay-transport.js: every log call gets a text literal as context', () => {
  const source = readFileSync(new URL('relay-transport.js', root), 'utf8');
  const calls = [...source.matchAll(/\bthis\._log\(\s*([^,)]*)/g)];
  assert.ok(calls.length > 0, 'keine Aufrufe gefunden: Muster veraltet?');
  for (const [, first] of calls) {
    assert.match(first.trim(), /^'(?:[^'\\\n]|\\.)*'$|^"(?:[^"\\\n]|\\.)*"$/, first);
  }
});
