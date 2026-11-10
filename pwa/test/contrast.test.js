// pwa/test/contrast.test.js
// Kontrast nach WCAG 2.x, gemessen am echten Stylesheet: Normaltext mindestens 4,5:1, Rahmen und Schalter-Spur
// (Bedienelemente) mindestens 3:1. Die Farben kommen aus `:root` von `app.css`, nicht aus einer Kopie im Test.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const css = readFileSync(new URL('../app.css', import.meta.url), 'utf8');

const token = (name) => {
  const match = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(css);
  assert.ok(match, `Token --${name} fehlt in :root`);
  return match[1];
};

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const ratio = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

// Flächen, auf denen Text steht: die Tokens plus die festen Farben aus dem Stylesheet.
const surfaces = () => ({
  bg: token('bg'), cell: token('cell'), 'cell-hover': token('cell-hover'), weekend: token('weekend'), entry: token('entry'),
  statusbar: '#101a30', 'dirty-bar': '#3a2f10', 'pill-ok': '#14351f',
});

const atLeast = (label, a, b, min) => assert.ok(ratio(a, b) >= min, `${label}: ${ratio(a, b).toFixed(2)}:1 (mindestens ${min}:1)`);

test('normal text and muted text reach 4.5:1 on every surface they sit on', () => {
  for (const [name, surface] of Object.entries(surfaces())) {
    atLeast(`text auf ${name}`, token('text'), surface, 4.5);
    atLeast(`muted auf ${name}`, token('muted'), surface, 4.5);
  }
});

test('accent text (links, errors, the plus) reaches 4.5:1 on the surfaces it sits on', () => {
  for (const [name, surface] of Object.entries(surfaces())) atLeast(`accent-text auf ${name}`, token('accent-text'), surface, 4.5);
});

test('white text on the accent fill and its hover reaches 4.5:1; the fill is still a visible outline (3:1) on the page', () => {
  atLeast('weiss auf accent', '#ffffff', token('accent'), 4.5);
  atLeast('weiss auf accent-hover', '#ffffff', token('accent-hover'), 4.5);
  atLeast('accent als Rand auf bg', token('accent'), token('bg'), 3);
});

test('status colours stay readable on the surfaces they use', () => {
  for (const name of ['bg', 'cell', 'entry', 'dirty-bar', 'pill-ok']) {
    atLeast(`ok auf ${name}`, token('ok'), surfaces()[name], 4.5);
    atLeast(`warn auf ${name}`, token('warn'), surfaces()[name], 4.5);
  }
});

test('borders of fields and the switch track reach 3:1 against the page', () => {
  atLeast('line auf bg', token('line'), token('bg'), 3);
  atLeast('line auf cell', token('line'), token('cell'), 3);
});

test('text never uses the fill colour; accent text and the control line come from their own tokens', () => {
  assert.doesNotMatch(css, /(?<![-\w])color:\s*var\(--accent\)/);              // Text: --accent-text
  const withLine = [/border: 1px solid var\(--line\)/g, /background: var\(--line\)/g]
    .map((pattern) => (css.match(pattern) || []).length);
  assert.ok(withLine[0] >= 3, 'Felder, Auswahl und Chips nutzen --line');
  assert.ok(withLine[1] >= 1, 'die Schalter-Spur nutzt --line');
  assert.doesNotMatch(css, /input, select \{[^}]*#2a3a5a/);
  assert.doesNotMatch(css, /input\.switch-input \{[^}]*#2a3a5a/);
});

test('the shift hint under the time fields is muted text, its live value normal text, never dimmed', () => {
  const rule = (selector) => (css.match(new RegExp(`${selector.replace(/[.]/g, '\\.')} \\{([^}]*)\\}`)) || [])[1] || '';
  assert.match(rule('.slot .shift-hint'), /color: var\(--muted\)/);            // --muted erreicht 4,5:1 auf der Dialogfläche (--bg)
  assert.match(rule('.slot .shift-hint.live'), /color: var\(--text\)/);
  assert.doesNotMatch(rule('.slot .shift-hint') + rule('.slot .shift-hint.live'), /opacity/);
  assert.match(css, /dialog \{[^}]*background: var\(--bg\)/);                 // die Fläche, gegen die oben gemessen wird
});
