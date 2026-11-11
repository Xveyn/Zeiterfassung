// pwa/test/i18n.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { DEFAULT_LANGUAGE, getLanguage, normalizeLanguage, setLanguage, t } from '../i18n.js';
import de from '../i18n/de.js';
import { scanLiterals } from './literals.js';

const root = new URL('../', import.meta.url);

function quiet(fn) {
  const original = console.warn;
  const warnings = [];
  console.warn = (...args) => warnings.push(args.join(' '));
  try { return { value: fn(), warnings }; } finally { console.warn = original; }
}

test('t replaces parameters and leaves unknown placeholders standing', () => {
  assert.equal(t('i18n.beispiel', { name: 'Anna', count: 3 }), 'Hallo Anna, es sind 3 Einträge.');
  assert.equal(t('i18n.beispiel', { name: 'Anna' }), 'Hallo Anna, es sind {count} Einträge.');
  assert.equal(t('i18n.ohne_parameter'), 'Nur Text');
  assert.equal(t('i18n.beispiel'), 'Hallo {name}, es sind {count} Einträge.');
});

test('an unknown key returns the key and warns', () => {
  const { value, warnings } = quiet(() => t('gibt.es.nicht'));
  assert.equal(value, 'gibt.es.nicht');
  assert.equal(warnings.length, 1);
});

test('normalizeLanguage falls back to the default', () => {
  assert.equal(DEFAULT_LANGUAGE, 'de');
  for (const bad of ['xx', undefined, null, 5, '', {}]) assert.equal(normalizeLanguage(bad), 'de');
  assert.equal(normalizeLanguage('de'), 'de');
  assert.equal(normalizeLanguage('DE-at'), 'de');
});

test('setLanguage sets lang on the document where there is one and never throws without', () => {
  setLanguage('xx');
  assert.equal(getLanguage(), 'de');
  const had = Object.getOwnPropertyDescriptor(globalThis, 'document');
  globalThis.document = { documentElement: { lang: '' } };
  try {
    setLanguage('de');
    assert.equal(globalThis.document.documentElement.lang, 'de');
  } finally {
    if (had) Object.defineProperty(globalThis, 'document', had); else delete globalThis.document;
  }
  assert.doesNotThrow(() => setLanguage('de'));
});

// --- Katalog gegen Aufrufe ---------------------------------------------------------------------------

const sources = readdirSync(root).filter((f) => f.endsWith('.js') && f !== 'i18n.js');
const used = new Set();
const dynamic = [];
for (const file of sources) {
  const source = readFileSync(new URL(file, root), 'utf8');
  for (const l of scanLiterals(source)) if (l.callee === 't') used.add(l.text);
  // Schlüssel nur als Literal: `t(` gefolgt von etwas anderem als einem Anführungszeichen
  for (const m of source.matchAll(/(?<![\w.$])t\(\s*(?!['"])/g)) {
    if (!/\bfunction\s+$/.test(source.slice(0, m.index))) dynamic.push(`${file}@${m.index}`);
  }
}

test('every t(…) key exists in the catalog', () => {
  const missing = [...used].filter((key) => !(key in de));
  assert.deepEqual(missing, []);
});

test('every catalog key is used by a t(…) call (keys of the layer itself are `i18n.*`)', () => {
  const unused = Object.keys(de).filter((key) => !key.startsWith('i18n.') && !used.has(key));
  assert.deepEqual(unused, []);
});

test('keys are passed as literals, never computed', () => {
  assert.deepEqual(dynamic, []);
});

test('catalog keys are dotted lowercase names and texts are strings', () => {
  for (const [key, text] of Object.entries(de)) {
    assert.match(key, /^[a-z0-9_]+(\.[a-z0-9_]+)+$/, key);
    assert.equal(typeof text, 'string', key);
  }
});
