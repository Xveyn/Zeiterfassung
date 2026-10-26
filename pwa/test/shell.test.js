// pwa/test/shell.test.js
// Die Hülle der PWA: Manifest, Icons, Service-Worker-Kern, index.html — alles, was ohne
// Browser prüfbar ist, damit Auslieferungsfehler (fehlende Datei, vergessener Cache-Eintrag,
// Platzhalter) in der CI auffallen statt auf dem Handy.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

import { BUILD, CACHE_NAME, CACHE_PREFIX, PRECACHE, shouldHandle } from '../sw-core.js';

const root = new URL('..', import.meta.url).pathname;
const read = (name) => readFileSync(join(root, name), 'utf8');

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const EXCLUDED = new Set(['package.json', 'sw.js', 'memory-adapter.js']);
const runtimeFiles = () => walk(root)
  .map((path) => relative(root, path))
  .filter((path) => !path.startsWith('test/') && !path.startsWith('node_modules/') && !path.endsWith('.md')
    && !EXCLUDED.has(path))
  .sort();

// --- Vorab-Cache -----------------------------------------------------------------------------------

test('every runtime file is precached and every precache entry exists', () => {
  const listed = PRECACHE.filter((entry) => entry !== './').map((entry) => entry.replace(/^\.\//, '')).sort();
  assert.deepEqual(listed, runtimeFiles());
  assert.ok(PRECACHE.includes('./'), 'die Startseite unter dem Ordner-Pfad fehlt');
  for (const entry of listed) assert.ok(existsSync(join(root, entry)), entry);
});

test('precache entries are relative so the site works under /Zeiterfassung/', () => {
  for (const entry of PRECACHE) assert.match(entry, /^\.\//, entry);
});

test('the build id is a placeholder in the repository and part of the cache name', () => {
  assert.equal(BUILD, '__BUILD__');
  assert.equal(CACHE_NAME, `${CACHE_PREFIX}${BUILD}`);
  assert.equal(read('sw-core.js').split('__BUILD__').length - 1, 1, 'der Platzhalter muss genau einmal vorkommen');
});

// --- Welche Anfragen der Service Worker anfasst ---------------------------------------------------

const SELF = 'https://xveyn.github.io/Zeiterfassung/sw.js';

test('the service worker handles only its own precached GET requests', () => {
  const yes = ['https://xveyn.github.io/Zeiterfassung/', 'https://xveyn.github.io/Zeiterfassung/index.html',
    'https://xveyn.github.io/Zeiterfassung/app.js', 'https://xveyn.github.io/Zeiterfassung/icons/icon-192.png',
    'https://xveyn.github.io/Zeiterfassung/index.html?x=1', 'https://xveyn.github.io/Zeiterfassung/#pair=1'];
  for (const url of yes) assert.equal(shouldHandle('GET', url, SELF), true, url);
});

test('requests to the desktop and anything foreign pass by the service worker', () => {
  const no = ['http://192.168.178.20:17654/v1/sync', 'http://192.168.178.20:17654/v1/ping',
    'https://example.org/Zeiterfassung/app.js', 'https://xveyn.github.io/anderes-projekt/app.js',
    'https://xveyn.github.io/Zeiterfassung/unbekannt.js', 'https://xveyn.github.io/Zeiterfassung/test/store.test.js'];
  for (const url of no) assert.equal(shouldHandle('GET', url, SELF), false, url);
});

test('only GET is handled', () => {
  for (const method of ['POST', 'PUT', 'DELETE', 'HEAD', 'OPTIONS']) {
    assert.equal(shouldHandle(method, 'https://xveyn.github.io/Zeiterfassung/app.js', SELF), false, method);
  }
});

test('a broken URL never throws', () => {
  assert.equal(shouldHandle('GET', 'kein url', SELF), false);
  assert.equal(shouldHandle('GET', 'https://xveyn.github.io/Zeiterfassung/app.js', 'kaputt'), false);
});

test('the service worker also works on the local dev origin', () => {
  assert.equal(shouldHandle('GET', 'http://localhost:8099/app.js', 'http://localhost:8099/sw.js'), true);
  assert.equal(shouldHandle('GET', 'http://localhost:8099/', 'http://localhost:8099/sw.js'), true);
});

// --- Manifest und Icons ----------------------------------------------------------------------------

function pngSize(path) {
  const buffer = readFileSync(path);
  assert.equal(buffer.subarray(1, 4).toString(), 'PNG', path);
  return [buffer.readUInt32BE(16), buffer.readUInt32BE(20)];
}

test('the manifest is installable', () => {
  const manifest = JSON.parse(read('manifest.webmanifest'));
  assert.equal(manifest.name, 'Zeiterfassung');
  assert.ok(manifest.short_name.length <= 12);
  assert.equal(manifest.start_url, './');
  assert.equal(manifest.scope, './');
  assert.equal(manifest.display, 'standalone');
  assert.equal(manifest.lang, 'de');
  assert.equal(manifest.version, '__BUILD__', 'Metadaten tragen die Build-Kennung (pwa_stamp.py)');
  const css = read('app.css');
  assert.equal(manifest.background_color, /--bg:\s*(#[0-9a-f]{6})/i.exec(css)[1]);
  assert.equal(manifest.theme_color, manifest.background_color);
  const sizes = new Map(manifest.icons.map((icon) => [icon.src, icon]));
  for (const [src, expected, purpose] of [
    ['icons/icon-192.png', [192, 192], 'any'], ['icons/icon-512.png', [512, 512], 'any'],
    ['icons/icon-maskable-512.png', [512, 512], 'maskable']]) {
    const icon = sizes.get(src);
    assert.ok(icon, src);
    assert.equal(icon.type, 'image/png');
    assert.equal(icon.purpose, purpose);
    assert.equal(icon.sizes, `${expected[0]}x${expected[1]}`);
    assert.deepEqual(pngSize(join(root, src)), expected, src);
  }
});

// --- index.html --------------------------------------------------------------------------------------

test('index.html wires manifest, icons, styles and the app module with relative paths', () => {
  const html = read('index.html');
  assert.match(html, /<html lang="de"/);
  assert.match(html, /<meta name="viewport" content="width=device-width, initial-scale=1/);
  assert.match(html, /<meta name="theme-color" content="#1a1a2e"/);
  assert.match(html, /<link rel="manifest" href="manifest\.webmanifest"/);
  assert.match(html, /<link rel="stylesheet" href="app\.css"/);
  assert.match(html, /<script type="module" src="app\.js"/);
  assert.match(html, /<div id="app"/);
  assert.match(html, /<noscript>/);
  assert.doesNotMatch(html, /(?:src|href)="\//, 'absolute Pfade brechen unter /Zeiterfassung/');
  assert.doesNotMatch(html, /<script(?![^>]*\bsrc=)[^>]*>/, 'kein Inline-Skript');
});

// --- Keine HTML-Einschleusung ---------------------------------------------------------------------------

test('no runtime script uses an HTML-injection API', () => {
  const forbidden = /\binnerHTML\b|\bouterHTML\b|\binsertAdjacentHTML\b|document\.write|\beval\s*\(|new Function\s*\(/;
  for (const file of runtimeFiles().filter((path) => path.endsWith('.js'))) {
    assert.doesNotMatch(read(file), forbidden, file);
  }
});

test('the app logs no secrets', () => {
  for (const file of runtimeFiles().filter((path) => path.endsWith('.js'))) {
    assert.doesNotMatch(read(file), /console\.\w+\([^)]*(token|code|device_name)/i, file);
  }
});

test('the pages workflow does not publish markdown from pwa/', () => {
  const workflow = readFileSync(new URL('../../.github/workflows/pages.yml', import.meta.url), 'utf8');
  assert.match(workflow, /--exclude '\*\.md'/);
});

// --- Native append/replaceChildren bekommen keine Arrays -----------------------------------------------
// Nur `h()` glättet Arrays. Das native `Element.append` macht aus einem Array den Text
// „[object HTMLDivElement],…“ — ein `.map(` als Argument muss dort gespreizt werden (`...xs.map(…)`).

/** Die Argumente des Aufrufs, der bei `open` (Index der öffnenden Klammer) beginnt, auf oberster Ebene
 *  getrennt. Zeichenketten werden übersprungen, damit Klammern darin nicht zählen. */
function topLevelArguments(source, open) {
  const args = [];
  let depth = 0;
  let current = '';
  for (let i = open; i < source.length; i += 1) {
    const char = source[i];
    if (char === '\'' || char === '"' || char === '`') {
      let j = i + 1;
      while (j < source.length && source[j] !== char) j += source[j] === '\\' ? 2 : 1;
      current += source.slice(i, j + 1);
      i = j;
      continue;
    }
    if ('([{'.includes(char)) { depth += 1; if (depth === 1) continue; }
    if (')]}'.includes(char)) { depth -= 1; if (depth === 0) { args.push(current); return args; } }
    if (char === ',' && depth === 1) { args.push(current); current = ''; continue; }
    current += char;
  }
  throw new Error('unbalancierte Klammern');
}

/** Native Aufrufe mit einem ungespreizten `.map(`-Argument, als „Datei:Zeile“. */
function unspreadMapArguments(source, file) {
  const findings = [];
  for (const match of source.matchAll(/\.(?:append|replaceChildren)\(/g)) {
    const open = match.index + match[0].length - 1;
    for (const arg of topLevelArguments(source, open)) {
      // Ein Argument, das selbst eine `.map(`-Kette ist (nicht gespreizt, nicht in `h(…)` verschachtelt).
      if (/^\s*[\w$][\w$.]*\.map\(/.test(arg)) {
        findings.push(`${file}:${source.slice(0, match.index).split('\n').length}`);
      }
    }
  }
  return findings;
}

test('the guard flags an un-spread map in a native append, but not a spread or one inside h()', () => {
  assert.deepEqual(unspreadMapArguments("el.append(h('p'), xs.map((x) => x));", 'a'), ['a:1']);
  assert.deepEqual(unspreadMapArguments('el.replaceChildren(...xs.map((x) => x));', 'a'), []);
  assert.deepEqual(unspreadMapArguments("el.append(h('ul', {}, xs.map((x) => h('li', {}, x))));", 'a'), []);
  assert.deepEqual(unspreadMapArguments("el.append(h('p', {}, 'a, (b'), ys.map(f));", 'a'), ['a:1']);
});

test('native append/replaceChildren never receive an un-spread array from .map()', () => {
  for (const file of ['views.js', 'app.js']) {
    assert.deepEqual(unspreadMapArguments(read(file), file), []);
  }
});

test('the service worker shows a notification for every push and handles the click', () => {
  const worker = read('sw.js');
  assert.match(worker, /addEventListener\('push'/);
  assert.match(worker, /addEventListener\('notificationclick'/);
  // Chrome verlangt eine sichtbare Benachrichtigung je Push (userVisibleOnly): der Fehlerpfad der
  // Entschlüsselung darf sie nicht auslassen.
  const push = worker.slice(worker.indexOf("addEventListener('push'"), worker.indexOf("addEventListener('notificationclick'"));
  assert.match(push, /catch/);
  assert.match(push, /showNotification/);
  assert.ok(push.indexOf('catch') < push.lastIndexOf('showNotification'), 'nach dem Fehlerpfad folgt die Anzeige');
});

test('the service worker recognises the test payload before it tries to decrypt', () => {
  const worker = read('sw.js');
  const push = worker.slice(worker.indexOf("addEventListener('push'"), worker.indexOf("addEventListener('notificationclick'"));
  assert.match(push, /TEST_PAYLOAD/);
  assert.match(push, /describeTest/);
  assert.ok(push.indexOf('TEST_PAYLOAD') < push.indexOf('open('), 'erst die Test-Nutzlast, dann das Entschlüsseln');
});

test('notifications carry no large icon: Chrome on Android already shows the app icon in the header (#355)', () => {
  const worker = read('sw.js');
  const push = worker.slice(worker.indexOf("addEventListener('push'"), worker.indexOf("addEventListener('notificationclick'"));
  assert.doesNotMatch(push, /\bicon\s*:/);
});

test('the settings tabs can shrink below their text width so three of them fit a 360 px phone (#363)', () => {
  const css = read('app.css');
  const rule = css.match(/^\.tabs button \{([^}]*)\}/m);
  assert.ok(rule, 'Regel ".tabs button" nicht gefunden');
  // Ohne `min-width: 0` lässt `flex: 1` die Knöpfe nicht unter ihre Textbreite schrumpfen: bei 360–390 px
  // ragt der dritte Reiter aus dem Dialog und der Dialog scrollt waagerecht.
  assert.match(rule[1], /min-width:\s*0/);
});
