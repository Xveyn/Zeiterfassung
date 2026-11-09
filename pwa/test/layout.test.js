// pwa/test/layout.test.js
// Das Layout der Web-App wird im Browser geprüft (Playwright gegen den Dev-Server, s. pwa/CLAUDE.md); Node hat
// kein DOM. Diese Zusicherungen halten am Quelltext fest, woran die gefundenen Fehler hingen: ein schwebender
// ×-Knopf im Slot, die zweispaltige Liste der Einstellungen, ein Fuß, der bei wenig Höhe aus dem Dialog fällt.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const css = readFileSync(new URL('../app.css', import.meta.url), 'utf8');
const views = readFileSync(new URL('../views.js', import.meta.url), 'utf8');
const app = readFileSync(new URL('../app.js', import.meta.url), 'utf8');

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
  assert.match(views, /const showPause = withPause \|\| pauseEnabled;/);
  assert.match(views, /showPause && field\(index, 'pause', 'Pause \(Min\)', \{ type: 'number', inputmode: 'numeric', min: 0, step: TIME_STEP_MINUTES \}\)/);
  assert.equal((views.match(/field\(index, 'pause'/g) || []).length, 1);
});

test('app.js hands pauseEnabled to the rows, the validation, the save and the editor', () => {
  assert.match(app, /reservationRows\(reservation, meta\.defaults, weekdayKey\(date\), \{ pauseEnabled \}\)/);
  assert.match(app, /validateReservationRows\(rows, \{ pauseEnabled \}\)/);
  assert.match(app, /reservationRowsToSlots\(rows, \{ pauseEnabled \}\)/);
  assert.match(app, /startWith,\s*pauseEnabled,/);
});

test('the calendar note sits only in the reservation tab and only with the flag', () => {
  assert.match(readFileSync(new URL('../messages.js', import.meta.url), 'utf8'), /RESERVATION_CALENDAR_NOTE = 'Falls dein Desktop mit dem Google-Kalender abgleicht: Der Termin zeigt die volle Zeitspanne, die Pause wird dort nicht abgezogen\.'/);
  assert.equal((views.match(/RESERVATION_CALENDAR_NOTE/g) || []).length, 2);     // Import + eine Verwendung
  assert.match(views, /!withPause && pauseEnabled && h\('p', \{ class: 'muted note' \}, 'ⓘ ', RESERVATION_CALENDAR_NOTE/);
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
  assert.match(css, /(?:^|\n)a\s*\{[^}]*color:\s*var\(--accent-text\)/);
});

test('a dismissible hint leaves room for its close button so the text never runs under it', () => {
  assert.match(rule('.hint.dismissible'), /padding-right:\s*52px/);          // Knopf 44 px + Rand
  assert.match(rule('.hint .dismiss'), /min-width:\s*var\(--tap\)/);
  assert.match(views, /hint\.dismissible && button\('✕'/);
  assert.match(views, /'aria-label': 'Hinweis schließen'/);
});

test('the “heute” label sits in the date column, not beside the weekday (the column is only 48 px wide)', () => {
  assert.match(views, /day\.isToday && h\('div', \{ class: 'tag' \}, 'heute'\)/);
  assert.match(css, /\.day \.tag \{[^}]*display: inline-block/);
  assert.match(css, /grid-template-columns: 48px 1fr auto/);
});

test('the editor rows that use display:flex still honour [hidden] (day total, net line)', () => {
  const css = readFileSync(new URL('../app.css', import.meta.url), 'utf8');
  assert.match(css, /\.daysum\[hidden\][^{]*\{ display: none; \}/);
  assert.match(css, /\.slot \.net\[hidden\]/);
});

test('the unsaved-categories bar sits above the list, carries the save button and honours [hidden]', () => {
  const panel = /function categoriesPanel[\s\S]*?\n\}\r?\n/.exec(views)[0];
  assert.match(panel, /h\('div', \{ class: 'dirty', role: 'status' \}, h\('span', \{\}, 'Änderungen nicht gespeichert'\), save\)/);
  assert.ok(panel.indexOf('dirtyBar,') < panel.indexOf('    list,'));
  assert.match(panel, /dirtyBar\.hidden = !\(model\.editable && dirty\(\)\)/);
  assert.match(css, /\.dirty\[hidden\] \{ display: none; \}/);                // display:flex überstimmt sonst `hidden`
});

test('buttons outside dialogs (pairing screen) keep a gap so Cancel and Pair do not read as one button', () => {
  assert.match(rule('main .buttons'), /gap:\s*8px/);
});

test('the push switch is a real checkbox with role switch, fixed size, and does not inherit the full-width input style', () => {
  assert.match(views, /type: 'checkbox', role: 'switch', class: 'switch-input'/);
  assert.match(rule('input.switch-input'), /width:\s*46px/);
  assert.match(rule('input.switch-input'), /appearance:\s*none/);
  assert.match(views, /h\('label', \{ class: 'switch', for: 'push-toggle' \}/);   // das Label macht die ganze Zeile antippbar
});

test('technical details are folded away; the state card and the storage notice come first', () => {
  const panel = /function connectionPanel[\s\S]*?\n\}\r?\n/.exec(views)[0];
  assert.ok(panel.indexOf("class: 'status-card'") < panel.indexOf('notice,'));
  assert.ok(panel.indexOf('notice,') < panel.indexOf('pushSection(push, handlers)'));
  assert.ok(panel.indexOf("h('details', { class: 'tech' }") > panel.indexOf('pushSection(push, handlers)'));
  assert.match(panel, /h\('summary', \{\}, 'Technische Details'\)/);
});

test('the storage notice never hands null to the native replaceChildren (it would print “null”)', () => {
  assert.match(views, /replaceChildren\(\.\.\.\[h\('div', \{\}, model\.text\)[^\]]*\]\.filter\(Boolean\)\)/);
});

test('on phones the settings dialog fills the screen with a header and a scrolling body; on wide screens it stays a dialog', () => {
  const media = /@media \(max-width: 600px\) \{([\s\S]*?)\n\}/.exec(css.slice(css.indexOf('Einstellungen auf dem Handy')));
  assert.ok(media, 'Media-Query für schmale Bildschirme fehlt');
  assert.match(media[1], /\.settings-dialog \{[^}]*width: 100vw[^}]*height: 100dvh/);
  assert.match(media[1], /\.settings-dialog\[open\] \{ display: flex/);       // nur offen: `display` überstimmt sonst das Verborgene des geschlossenen Dialogs
  assert.match(media[1], /\.settings-body \{[^}]*overflow-y: auto/);
  assert.match(media[1], /\.settings-dialog > \.buttons \{ display: none; \}/);
  assert.match(css, /\.settings-head \.back \{ display: none;/);               // breit: kein ‹
  assert.match(views, /h\('div', \{ class: 'settings-head' \}/);
  assert.match(views, /'aria-label': 'Zurück', 'data-focus': 'settings-back'/);
});

test('every dialog opens through openDialog, which ties it to the browser history (back gesture closes it) — except the lock', () => {
  // Drei Aufrufe von `showModal()`: `openDialog`, die Sperre und deren Wiederöffnen. Die Sperre darf nicht am Verlauf hängen,
  // sonst schlösse sie die Zurück-Geste.
  assert.equal((views.match(/\.showModal\(\)/g) || []).length, 3);
  assert.match(views, /dialogHistory\.attach\(dialog\);\s*\n\s*document\.body\.append\(dialog\);/);
  assert.match(views, /window\.addEventListener\('popstate', listener\)/);
});

test('the lock dialog stays out of the browser history and cannot be dismissed', () => {
  const source = /export function lockDialog[\s\S]*?\n}\n/.exec(views)?.[0];
  assert.ok(source, 'lockDialog fehlt');
  assert.doesNotMatch(source, /openDialog\(|dialogHistory|history\./);
  assert.match(source, /dialog\.addEventListener\('cancel', \(event\) => event\.preventDefault\(\)\)/);
  assert.match(source, /dialog\.addEventListener\('close', \(\) => \{ if \(handlers\.isLocked\(\)\) dialog\.showModal\(\); \}\)/);
});

test('the stylesheet closes every block: a missing brace would swallow the rest of the file into the last @media query', () => {
  const code = css.replace(/\/\*[\s\S]*?\*\//g, '').replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, '""');
  let depth = 0;
  for (const char of code) {
    if (char === '{') depth += 1;
    if (char === '}') depth -= 1;
    assert.ok(depth >= 0, 'eine schließende Klammer zu viel');
  }
  assert.equal(depth, 0, 'am Dateiende ist ein Block offen (alles dahinter gilt nur innerhalb von dessen @media)');
});

test('the hidden button groups of the lock section really disappear (display: flex would override `hidden`)', () => {
  assert.match(rule('.lock .buttons[hidden]'), /display:\s*none/);
  assert.match(rule('.lock-dialog .buttons[hidden]'), /display:\s*none/);
  assert.match(rule('.lock-dialog button[hidden]'), /display:\s*none/);
});

test('the lock dialog covers the whole screen on every width', () => {
  assert.match(rule('.lock-dialog'), /width:\s*100vw/);
  assert.match(rule('.lock-dialog'), /height:\s*100dvh/);
  assert.match(rule('.lock-dialog'), /border-radius:\s*0/);
  assert.match(rule('.lock-dialog[open]'), /display:\s*flex/);       // nur offen: `display` überstimmt sonst das Verborgene des geschlossenen Dialogs
});

test('the settings dialog still asks before it closes with unsaved categories, also for the back gesture (cancel event)', () => {
  const settings = /export function settingsDialog[\s\S]*?\n\}\r?\n/.exec(views)[0];
  assert.match(settings, /dialog\.addEventListener\('cancel', \(event\) => \{\s*\n\s*if \(!cats\.dirty\(\)\) return;\s*\n\s*event\.preventDefault\(\);\s*\n\s*closeThen\(\);/);
});

test('the settings dialog starts with focus on the active tab, not on the back button in the header', () => {
  assert.match(views, /tabs\[initial\]\.autofocus = true;/);
});

// --- Übergänge (#461) ------------------------------------------------------------------------------------------

/** Alle Zeitangaben (ms) hinter `animation:`/`transition:` im Stylesheet. */
function motionDurations() {
  const found = [];
  for (const [, value] of css.matchAll(/(?:^|[;{\s])(?:animation|transition)\s*:\s*([^;}]+)/g)) {
    for (const [, number, unit] of value.matchAll(/(?<![\w.-])(\d*\.?\d+)(ms|s)\b/g)) found.push(Number(number) * (unit === 's' ? 1000 : 1));
  }
  return found;
}

test('every animation and transition is short: at most 200 ms (the app is used in passing)', () => {
  const durations = motionDurations();
  assert.ok(durations.length >= 4, 'es gibt Übergänge');
  assert.ok(durations.every((ms) => ms <= 200), `zu lang: ${durations.filter((ms) => ms > 200)}`);
});

test('keyframes move only transform and opacity (cheap on weak phones, no layout work)', () => {
  const blocks = [...css.matchAll(/@keyframes\s+([\w-]+)\s*\{((?:[^{}]*\{[^}]*\})*)\s*\}/g)];
  assert.ok(blocks.length >= 3, 'es gibt Keyframes');
  for (const [, name, body] of blocks) {
    const properties = [...body.matchAll(/([\w-]+)\s*:/g)].map((match) => match[1]);
    assert.ok(properties.every((property) => ['opacity', 'transform'].includes(property)), `${name}: ${properties}`);
  }
});

test('reduced motion switches all animations and transitions off', () => {
  const block = /@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}/.exec(css);
  assert.ok(block, 'Block für reduzierte Bewegung fehlt');
  assert.match(block[1], /animation:\s*none\s*!important/);
  assert.match(block[1], /transition:\s*none\s*!important/);
});

test('dialogs and their backdrop fade in; only the hints host animates new hints, not the week (it is rebuilt on every render)', () => {
  assert.match(css, /dialog\[open\] \{ animation: dialog-in/);
  assert.match(css, /dialog\[open\]::backdrop \{ animation: backdrop-in/);
  assert.match(css, /\.hints \.hint \{ animation: hint-in/);
  assert.doesNotMatch(css, /(?:^|\n)\.hint \{[^}]*animation/);
  assert.doesNotMatch(css, /\.week[^{]*\{[^}]*animation/);
});

test('a dialog footer with a delete button keeps Cancel and Save together: delete on the left, the pair wraps as one', () => {
  assert.match(rule('.buttons .destructive'), /margin-right:\s*auto/);
  assert.match(rule('.buttons .button-group'), /display:\s*flex/);
  // Der Tages-Editor und „Kategorie bearbeiten“ bauen ihre Fußzeile über denselben Helfer.
  assert.match(views, /function footerButtons\(destructive, cancel, primary\)/);
  assert.equal((views.match(/footerButtons\(/g) || []).length, 3);               // Definition + zwei Aufrufer
  assert.match(views, /footerButtons\(\s*clearButton,/);
  assert.match(views, /footerButtons\(\s*remove,/);
  assert.match(views, /button\('Tag leeren', \(\) => handlers\.clear\(active, dialog\), 'link destructive'\)/);
  assert.match(views, /'link destructive', \{ 'data-focus': 'category-remove' \}/);
});

// --- Antippen auf Touch-Geräten ---------------------------------------------------------------------------------

test('no native tap highlight: Android would flash the tapped day and leave it lingering over the opening dialog', () => {
  assert.match(rule(':root'), /-webkit-tap-highlight-color:\s*transparent/);
});

test('hover colours only apply where hovering exists; on touch a tap leaves :hover stuck on the element', () => {
  assert.doesNotMatch(css, /(?:^|\n)button:hover/);
  assert.doesNotMatch(css, /(?:^|\n)button\.primary:hover/);
  const block = /@media \(hover: hover\) \{([\s\S]*?)\n\}/.exec(css);
  assert.ok(block, 'Block für Geräte mit Hover fehlt');
  assert.match(block[1], /button:hover \{ background: var\(--cell-hover\); \}/);
  assert.match(block[1], /button\.primary:hover \{ background: var\(--accent-hover\); \}/);
});

test('the four settings tabs are sized by their text, not in equal boxes (Verbindung is wider than Debug)', () => {
  // Der Fehler: `.tabs button { flex: 1 }` macht alle Reiter gleich breit; bei vier Reitern auf 280 px ist die Box
  // schmaler als „Verbindung“, der Text läuft in den Nachbarn.
  assert.match(rule('.settings-dialog .tabs'), /gap:\s*[0-4]px/);
  assert.match(rule('.settings-dialog .tabs button'), /flex:\s*1 1 auto/);
});

test('below 340 px the settings tabs get a smaller font and a tighter gap', () => {
  const media = /@media \(max-width: 340px\) \{\n([\s\S]*?)\n\}/.exec(css);
  assert.ok(media, 'keine Regel für sehr schmale Breiten');
  assert.match(media[1], /\.settings-dialog \.tabs button\s*\{[^}]*font-size:\s*\.7rem/);
  assert.match(media[1], /\.settings-dialog \.tabs\s*\{[^}]*gap:\s*[0-3]px/);
});

// --- Einrichtungs-Screen (#496) ---------------------------------------------------------------------

test('the setup screen has no opacity: later steps stay readable, only their number turns grey', () => {
  const rules = [...css.matchAll(/(^|\n)(\.setup[^{]*)\{([^}]*)\}/g)];
  assert.ok(rules.length > 10, 'the setup rules exist');
  for (const [, , selector, body] of rules) assert.doesNotMatch(body, /opacity/, selector);
  assert.match(css, /\.setup-step\.later \.num \{ background: var\(--line\); \}/);
});

test('the privacy link of the setup screen is grey, so the main button is the only red target', () => {
  assert.match(css, /\.setup-foot a \{ color: var\(--muted\); \}/);
  assert.doesNotMatch(css, /\.setup[^{]*\{[^}]*color:\s*var\(--accent-text\)/);
});

test('the scrollbar gutter stays reserved, so the page does not jump sideways when content grows past the screen', () => {
  assert.match(rule('html'), /scrollbar-gutter:\s*stable/);
});
