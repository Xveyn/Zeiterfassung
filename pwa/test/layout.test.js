// pwa/test/layout.test.js
// Das Layout der Web-App wird im Browser geprüft (Playwright gegen den Dev-Server, s. pwa/CLAUDE.md); Node hat
// kein DOM. Diese Zusicherungen halten am Quelltext fest, woran die gefundenen Fehler hingen: ein schwebender
// ×-Knopf im Slot, die zweispaltige Liste der Einstellungen, ein Fuß, der bei wenig Höhe aus dem Dialog fällt.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const css = readFileSync(new URL('../app.css', import.meta.url), 'utf8');
const views = readFileSync(new URL('../views.js', import.meta.url), 'utf8');

/** Der Rumpf der ersten Regel mit genau diesem Selektor, sonst Fehler (ein Test, der sein Ziel nicht mehr
 *  findet, ist rot). */
function rule(selector, source = css) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`(?:^|\\n)\\s*${escaped}\\s*\\{([^}]*)\\}`).exec(source);
  assert.ok(match, `Regel nicht gefunden: ${selector}`);
  return match[1];
}

test('the remove button of a slot does not float: it would squeeze the time fields next to it', () => {
  assert.doesNotMatch(rule('.slot .remove'), /float/);
});

test('a slot with several rows has a header row that holds the label and the remove button', () => {
  const head = rule('.slot-head');
  assert.match(head, /display:\s*flex/);
  assert.match(head, /justify-content:\s*space-between/);
  assert.match(views, /class: 'slot-head'/);
});

test('the settings list stacks label above value on narrow screens', () => {
  const media = /@media \(max-width: (\d+)px\)\s*\{[^@]*?\.settings-dialog dl\s*\{[^}]*grid-template-columns:\s*1fr/.exec(css);
  assert.ok(media, 'keine einspaltige Liste für schmale Breiten');
  assert.ok(Number(media[1]) >= 400, 'die Grenze liegt unter den gängigen Handybreiten');
});

test('the settings tabs shrink their text on very narrow screens instead of being cut off', () => {
  assert.match(css, /@media \(max-width: \d+px\)\s*\{[^@]*?\.settings-dialog \.tabs button\s*\{[^}]*font-size/);
});

test('hints break long unbroken text such as an address instead of running out of the card', () => {
  assert.match(rule('.hint'), /overflow-wrap:\s*anywhere/);
});

test('only the footer buttons of a dialog stay in view when it scrolls (landscape phones)', () => {
  const footer = rule('dialog > .buttons, dialog > form > .buttons');
  assert.match(footer, /position:\s*sticky/);
  assert.match(footer, /bottom:/);
  assert.match(footer, /background:/);
});

test('button groups inside a panel (updates, connection, categories) do not stick: they would cover the text below', () => {
  // Der Fehler: `dialog .buttons` galt für jede Gruppe, auch die „Nach Updates suchen / Reparieren“ im Reiter
  // „Updates“; sie klebte am Rand und deckte den Hinweis darunter ab.
  assert.doesNotMatch(rule('dialog .buttons'), /position:\s*sticky/);
});

test('time inputs step in five minutes and snap on change', () => {
  assert.doesNotMatch(views, /type: 'time', step: 60/);
  assert.match(views, /TIME_STEP_MINUTES \* 60/);
  assert.match(views, /\? snapTime :/);
  assert.match(views, /onchange/);
});

test('the pause fields step in five minutes and snap on change like the desktop picker', () => {
  assert.match(views, /\? snapPause :/);
  assert.equal((views.match(/'Pause \(Min\)', \{[^}]*step: TIME_STEP_MINUTES/g) || []).length, 2);
});

test('the reservation pause field is the same field as the actual-time one, shown only with the flag', () => {
  // Ein Feld, eine Zeile: gleiche Breitenregeln, gleiche Rasterung; nur die Bedingung unterscheidet sich.
  assert.match(views, /\(withPause \|\| pauseEnabled\) && field\(index, 'pause', 'Pause \(Min\)', \{ type: 'number', inputmode: 'numeric', min: 0, step: TIME_STEP_MINUTES \}\)/);
  assert.equal((views.match(/field\(index, 'pause'/g) || []).length, 1);
});

test('the calendar note sits only in the reservation tab and only with the flag', () => {
  assert.equal((views.match(/RESERVATION_CALENDAR_NOTE/g) || []).length, 2);     // Import + eine Verwendung
  assert.match(views, /!withPause && pauseEnabled && h\('p', \{ class: 'muted'[^)]*RESERVATION_CALENDAR_NOTE/);
  assert.match(views, /withPause: false, pauseEnabled/);
  assert.match(views, /categoryDisplay\(state\[index\], defaults, weekday, withPause\);/);   // Reservierungspause setzt kein `*`
});

test('on narrow phones the dialog buttons use less padding so Cancel and Save stay on one row', () => {
  assert.match(css, /@media \(max-width: 3\d\dpx\)\s*\{[^@]*?dialog \.buttons button\s*\{[^}]*padding/);
});

test('the page behind an open dialog does not scroll', () => {
  assert.match(css, /html:has\(dialog\[open\]\)\s*\{[^}]*overflow:\s*hidden/);
  assert.match(rule('dialog'), /overscroll-behavior:\s*contain/);
});

test('a day whose reservation is done shows no planned list', () => {
  assert.match(views, /day\.reservation\?\.slots\.length > 0/);
});

test('the privacy notice is linked from the pairing screen and the connection tab, opening safely in a new tab', () => {
  assert.match(views, /import \{ PRIVACY_URL \} from '\.\/relay-client\.js'/);
  assert.match(views, /href: PRIVACY_URL, target: '_blank', rel: 'noopener noreferrer'/);
  assert.match(readFileSync(new URL('../relay-client.js', import.meta.url), 'utf8'), /export const PRIVACY_URL = '\.\/datenschutz\.html';/);
  // Beide Stellen rufen den Helfer: der Koppel-Bildschirm und der Reiter Verbindung.
  const pair = /export function pairView[\s\S]*?\n\}\r?\n/.exec(views)[0];
  const connection = /function connectionPanel[\s\S]*?\n\}\r?\n/.exec(views)[0];
  assert.match(pair, /privacyLink\(\)/);
  assert.match(connection, /privacyLink\(\)/);
});

test('links in the web app use the accent colour, not the browser default', () => {
  assert.match(css, /(?:^|\n)a\s*\{[^}]*color:\s*var\(--accent\)/);
});
