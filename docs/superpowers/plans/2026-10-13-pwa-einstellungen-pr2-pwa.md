# Einstellungen und Kategorien in der Handy-PWA — PR 2: PWA

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Button unten links heißt „Einstellungen“ und öffnet einen Dialog mit den Reitern Verbindung, Kategorien und Updates. Im Reiter „Kategorien“ legt die PWA Kategorien an, benennt sie um, sortiert und löscht sie und setzt je Kategorie Start, Ende und Pause; der Abgleich schreibt das zum Desktop zurück.

**Architecture:** Die Kategorien sind **ein Block** im Store (`categories` und `category_times` zusammen, mit `dirty_version`/`synced_version`/`error`/`modified_at` in der Meta). Die reine Logik (Zeilen, Prüfung, Kurzfassung) steht in `pwa/categories.js`. Der Abgleich sendet `settings` im ersten Päckchen, die Antwort ersetzt den lokalen Stand, außer er wurde inzwischen erneut geändert. Eine kleine Ergänzung am Desktop (`writable_settings` in der Antwort) liefert die Feature-Erkennung. Der bisherige `connectionDialog` wird zu `settingsDialog` mit Reitern.

**Tech Stack:** reines JavaScript (ES-Module, kein Build), `node --test`; Python für die Gegenprobe am Desktop.

**Spec:** `docs/superpowers/specs/2026-10-13-pwa-einstellungen-kategorien-design.md`, Abschnitt „PR 2: PWA“. Der Desktop-Teil (Prüfung, Merge, Antwort nach dem Anwenden) ist mit #311 gemerged. **Ergänzung zur Spec**, die beim Planen aufgefallen ist: `defaults.category_times` gibt es seit #288, es taugt also nicht zur Erkennung eines Desktops mit #311. Ein Desktop ohne #311 würde `settings` still ignorieren, die PWA zeigte „gespeichert“, und die nächste Antwort setzte die Kategorien zurück. Deshalb Task 1: die Antwort nennt die schreibbaren Einstellungen.

## Global Constraints

- `PROTOCOL` bleibt `2`, alles additiv (`pwa/CLAUDE.md`, „Kompatibilität“, Regeln 1–2). Die Feature-Erkennung hängt an `writable_settings` in der Antwort (Task 1); fehlt es, ist „Kategorien bearbeiten“ aus, die Liste bleibt lesbar.
- Anfrage: `settings: {categories: {value, modified_at}, category_times: {value, modified_at}}`, beide Schlüssel **immer zusammen** (ein Block); nur im ersten Päckchen eines Abgleichs; ohne nicht übertragenen Block fehlt das Feld ganz.
- Prüfung in der PWA wie am Desktop (`src/mobile_settings.py`): ≤100 Kategorien, Namen getrimmt, nicht leer, ≤100 Zeichen (Code Points), eindeutig, keine Steuerzeichen (`Cc`/`Cs`); Uhrzeit `HH:MM`; Pause ganze Zahl 0–1440; Start/Ende: Ende nach Start, wenn beide gesetzt sind (nur PWA).
- Eine Kategorie im Modus `per_day` (am Desktop eingestellt) wird **nie** verändert: Name, Position und Löschen gehen, ihre Zeiten werden beim Speichern **unverändert** zurückgeschickt.
- Umbenennen und Löschen schreiben keine bestehenden Einträge um; der Dialog sagt das.
- Die DOM-Schicht baut Elemente nur über `h()` und Textknoten, nie `innerHTML` (ein Test verbietet es). Texte deutsch. `PRECACHE` ergänzen (`shell.test.js`). **Kein** Versionsbump in `pwa/package.json` (Release-PR).
- Branch `feat/pwa-einstellungen-dialog`, Commits `type(scope): …` auf Deutsch. Kommentare/Docstrings deutsch, Stil wie die vorhandenen Module.

## Review Focus

1. Kategorien am Handy speichern, **während** der Abgleich läuft: die lokale Fassung bleibt dirty, die Antwort überschreibt sie nicht. → Task 3
2. Eine `per_day`-Kategorie: Umbenennen, Sortieren und Speichern lassen ihre Wochentag-Zeiten bitgleich stehen. → Task 2
3. Ein Desktop ohne `writable_settings`: kein Bearbeiten, kein Senden, kein „gespeichert“; ein bereits dirty Block bleibt liegen, geht aber nicht hinaus und zählt nicht als „nicht übertragen“. → Task 3 und 4
4. `422` für den Block (z. B. 101 Kategorien am Desktop): der Block wird als abgelehnt markiert, die Tage gehen im nächsten Abgleich durch, der Fehler steht im Reiter. → Task 4
5. Öffnen der Einstellungen verliert keine Eingaben beim Reiterwechsel; Schließen mit ungespeicherten Änderungen fragt. → Task 6
6. Der Kategorie-Picker im Tages-Editor zeigt nach dem Speichern sofort die neuen Namen. → Task 3

---

## Dateien

| Datei | Verantwortung |
|---|---|
| `src/mobile_sync.py`, `tests/test_mobile_sync.py`, `tests/test_mobile_contract.py`, `pwa/test/fixtures/sync-response.json` | `writable_settings` in der Antwort (Task 1) |
| `pwa/categories.js` (neu), `pwa/test/categories.test.js` (neu) | Zeilen, Block, Prüfung, Kurzfassung — rein |
| `pwa/store.js` | Block in der Meta, Speichern, Snapshot, Anwenden, Zähler |
| `pwa/sync.js` | `writable_settings` lesen, `settings` senden, `422` zuordnen |
| `pwa/view-model.js` | Reiter und Kategorien-Modell |
| `pwa/views.js`, `pwa/app.js`, `pwa/app.css`, `pwa/messages.js`, `pwa/sw-core.js` | Dialog mit Reitern, Kategorien-Reiter, Verdrahtung |
| `pwa/test/fixtures/sync-request.json` | Live-Beispiel um `settings` erweitert |
| `pwa/CLAUDE.md`, `src/CLAUDE.md`, `CLAUDE.md`, `README.md`, Spec | Doku |

---

### Task 1: Desktop — `writable_settings` in der Antwort

**Files:**
- Modify: `src/mobile_sync.py`, `pwa/test/fixtures/sync-response.json`, `src/CLAUDE.md`
- Test: `tests/test_mobile_sync.py`, `tests/test_mobile_contract.py`, `tests/test_mobile_routes.py`

**Interfaces:**
- Produces: jede Sync-Antwort trägt `"writable_settings": ["categories", "category_times"]` (`mobile_settings.SETTING_KEYS` als Liste).

- [ ] **Step 1: Failing tests**

`tests/test_mobile_sync.py`:

```python
def test_the_response_names_the_settings_the_phone_may_write(env):
    response = run_settings(env, {})
    assert response["writable_settings"] == ["categories", "category_times"]
```

`tests/test_mobile_contract.py` (die vorhandene Formprüfung `test_the_response_example_has_the_shape_the_server_really_sends` vergleicht die Schlüssel von Beispiel und echter Antwort; das Beispiel wird in Step 3 erweitert, dort schlägt der Test sonst rot an):

```python
def test_the_response_example_lists_the_writable_settings():
    example = load("sync-response.json")
    assert example["writable_settings"] == ["categories", "category_times"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_mobile_sync.py tests/test_mobile_contract.py -q -k "writable"`
Expected: FAIL (`KeyError: 'writable_settings'`).

- [ ] **Step 3: Implementation**

`src/mobile_sync.py`, in `build_response` dem Antwort-Dict hinzufügen (neben `"desktop": dict(desktop)`):

```python
        # Welche Einstellungen das Handy schreiben darf — daran erkennt die PWA einen Desktop, der
        # `settings` versteht (Feature-Erkennung; `defaults.category_times` gibt es schon länger).
        "writable_settings": list(mobile_settings.SETTING_KEYS),
```

`pwa/test/fixtures/sync-response.json`: `"writable_settings": ["categories", "category_times"]` ergänzen (Schlüsselreihenfolge wie die Datei). Die eingefrorenen `compat/*-pre-settings.json` bleiben unberührt. `src/CLAUDE.md`: im `mobile_sync`-Absatz einen Satz „Die Antwort trägt `writable_settings` (Feature-Erkennung der PWA).“

- [ ] **Step 4: Run to verify pass**

Run: `pytest -q --ignore=tests/test_qr.py && (cd pwa && node --test) && ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mobile_sync.py src/CLAUDE.md pwa/test/fixtures/sync-response.json tests/test_mobile_sync.py tests/test_mobile_contract.py
git commit -m "feat(mobil): Antwort nennt die schreibbaren Einstellungen (Feature-Erkennung der PWA)"
```

---

### Task 2: `pwa/categories.js` — rein

**Files:**
- Create: `pwa/categories.js`, `pwa/test/categories.test.js`
- Modify: `pwa/sw-core.js` (`PRECACHE`)

**Interfaces:**
- Produces:
  - `MAX_CATEGORIES = 100`, `MAX_NAME_LENGTH = 100`, `MAX_PAUSE = 1440`
  - `categoryRows(categories: string[], categoryTimes: object) → Row[]` mit `Row = { name, mode: 'general' | 'per_day', start, end, pause, raw }` (`start`/`end`/`pause` Texte, `''` = Standard; `raw` ist bei `per_day` der unveränderte Eintrag, sonst `null`)
  - `rowsToBlock(rows) → { categories: string[], category_times: object }` (getrimmte Namen, `per_day` unverändert aus `raw`, allgemeine Zeilen nur mit gesetzten Feldern, leere entfallen)
  - `validateCategoryRows(rows) → { ok, message }`
  - `timesSummary(row) → string` (`'08:00–16:00, 30 min Pause'`, `'ab 08:00'`, `'bis 16:00'`, `'30 min Pause'`, `'—'`, `'pro Wochentag'`)
  - `moveRow(rows, index, direction) → Row[]` (neues Array; ungültige Bewegung gibt das Original zurück)
  - `blockSignature(categories, categoryTimes) → string` (reihenfolgetreu für Namen, schlüsselsortiert für Zeiten)

- [ ] **Step 1: Failing tests**

```js
// pwa/test/categories.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  MAX_CATEGORIES, blockSignature, categoryRows, moveRow, rowsToBlock, timesSummary, validateCategoryRows,
} from '../categories.js';

const PER_DAY = { mode: 'per_day', pause: 15, days: { fri: { start: '07:00', end: '11:00' }, mon: {} } };
const TIMES = { Projekt: { start: '09:00', end: '17:00', pause: 45 }, Support: PER_DAY };

test('rows read names in order with general times as text and per_day entries kept raw', () => {
  const rows = categoryRows(['Projekt', 'Intern', 'Support'], TIMES);

  assert.deepEqual(rows.map((r) => [r.name, r.mode]), [['Projekt', 'general'], ['Intern', 'general'], ['Support', 'per_day']]);
  assert.deepEqual([rows[0].start, rows[0].end, rows[0].pause], ['09:00', '17:00', '45']);
  assert.deepEqual([rows[1].start, rows[1].end, rows[1].pause], ['', '', '']);
  assert.deepEqual(rows[2].raw, PER_DAY);
});

test('the block round trip keeps names, order and a per_day entry bit-identical', () => {
  const rows = categoryRows(['Projekt', 'Intern', 'Support'], TIMES);

  const block = rowsToBlock(rows);

  assert.deepEqual(block.categories, ['Projekt', 'Intern', 'Support']);
  assert.deepEqual(block.category_times, TIMES);
  assert.notEqual(block.category_times.Support, PER_DAY);           // eine Kopie, nicht dieselbe Referenz
});

test('renaming or moving a per_day row does not touch its times', () => {
  let rows = categoryRows(['Support', 'Projekt'], TIMES);
  rows[0].name = '  Support neu ';
  rows = moveRow(rows, 0, +1);

  const block = rowsToBlock(rows);

  assert.deepEqual(block.categories, ['Projekt', 'Support neu']);
  assert.deepEqual(block.category_times['Support neu'], PER_DAY);
});

test('general rows keep only the fields that are set; pause 0 is a value', () => {
  const rows = categoryRows(['A', 'B', 'C'], {});
  rows[0].start = '08:00';
  rows[1].pause = '0';

  assert.deepEqual(rowsToBlock(rows).category_times, { A: { start: '08:00' }, B: { pause: 0 } });
});

test('moving a row swaps neighbours and ignores moves past the ends', () => {
  const rows = categoryRows(['A', 'B', 'C'], {});
  assert.deepEqual(moveRow(rows, 1, -1).map((r) => r.name), ['B', 'A', 'C']);
  assert.deepEqual(moveRow(rows, 1, +1).map((r) => r.name), ['A', 'C', 'B']);
  assert.equal(moveRow(rows, 0, -1), rows);
  assert.equal(moveRow(rows, 2, +1), rows);
});

const row = (over = {}) => ({ name: 'A', mode: 'general', start: '', end: '', pause: '', raw: null, ...over });

test('a valid list passes', () => {
  assert.equal(validateCategoryRows([row(), row({ name: 'B', start: '08:00', end: '16:00', pause: '30' })]).ok, true);
});

for (const [label, rows, part] of [
  ['an empty name', [row({ name: '  ' })], 'Name'],
  ['a duplicate after trimming', [row(), row({ name: ' A ' })], 'doppelt'],
  ['a name over 100 characters', [row({ name: 'x'.repeat(101) })], '100'],
  ['a control character in the name', [row({ name: 'a\tb' })], 'Zeichen'],
  ['101 categories', Array.from({ length: MAX_CATEGORIES + 1 }, (_, i) => row({ name: `K${i}` })), '100'],
  ['a start that is not HH:MM', [row({ start: '9:00' })], 'Start'],
  ['an end that is not HH:MM', [row({ end: '25:00' })], 'Ende'],
  ['an end before the start', [row({ start: '12:00', end: '09:00' })], 'Ende'],
  ['an end equal to the start', [row({ start: '12:00', end: '12:00' })], 'Ende'],
  ['a negative pause', [row({ pause: '-1' })], 'Pause'],
  ['a pause over 1440', [row({ pause: '1441' })], 'Pause'],
  ['a pause that is not a whole number', [row({ pause: '1.5' })], 'Pause'],
  ['a pause that is text', [row({ pause: 'abc' })], 'Pause'],
]) {
  test(`validation rejects ${label}`, () => {
    const check = validateCategoryRows(rows);
    assert.equal(check.ok, false);
    assert.match(check.message, new RegExp(part));
  });
}

test('start and end alone are fine, a per_day row is not checked for times', () => {
  assert.equal(validateCategoryRows([row({ start: '08:00' }), row({ name: 'B', end: '16:00' })]).ok, true);
  assert.equal(validateCategoryRows([row({ name: 'P', mode: 'per_day', raw: PER_DAY })]).ok, true);
});

test('the summary reads the times in one short line', () => {
  assert.equal(timesSummary(row({ start: '08:00', end: '16:00', pause: '30' })), '08:00–16:00, 30 min Pause');
  assert.equal(timesSummary(row({ start: '08:00' })), 'ab 08:00');
  assert.equal(timesSummary(row({ end: '16:00' })), 'bis 16:00');
  assert.equal(timesSummary(row({ pause: '0' })), '0 min Pause');
  assert.equal(timesSummary(row()), '—');
  assert.equal(timesSummary(row({ mode: 'per_day', raw: PER_DAY })), 'pro Wochentag');
});

test('the signature depends on the order of names but not on the key order of the times', () => {
  assert.equal(blockSignature(['A', 'B'], { A: { start: '08:00', end: '09:00' } }),
    blockSignature(['A', 'B'], { A: { end: '09:00', start: '08:00' } }));
  assert.notEqual(blockSignature(['A', 'B'], {}), blockSignature(['B', 'A'], {}));
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd pwa && node --test test/categories.test.js`
Expected: FAIL (`Cannot find module '../categories.js'`).

- [ ] **Step 3: Implementation**

```js
// pwa/categories.js
// Kategorien und ihre Standardzeiten ohne DOM: Zeilen für den Editor, der Block für den Abgleich,
// die Prüfung und die Kurzfassung. Gegenstück zu `src/mobile_settings.py` (Prüfung der Anfrage) und
// zu `collect_categories` am Desktop. Eine Kategorie im Modus „pro Wochentag“ (`per_day`) bearbeitet
// die PWA nicht: ihr Eintrag wandert unverändert durch (`raw`).
import { parseTime } from './minutes.js';

export const MAX_CATEGORIES = 100;
export const MAX_NAME_LENGTH = 100;
export const MAX_PAUSE = 1440;

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const hasOwn = (object, key) => Object.hasOwn(object, key);

export function categoryRows(categories, categoryTimes) {
  const times = isObject(categoryTimes) ? categoryTimes : {};
  return categories.map((name) => {
    const entry = hasOwn(times, name) && isObject(times[name]) ? times[name] : null;
    if (entry && entry.mode === 'per_day') {
      return { name, mode: 'per_day', start: '', end: '', pause: '', raw: structuredClone(entry) };
    }
    return {
      name, mode: 'general', raw: null,
      start: entry?.start ?? '', end: entry?.end ?? '',
      pause: Number.isInteger(entry?.pause) ? String(entry.pause) : '',
    };
  });
}

export function rowsToBlock(rows) {
  const categories = [];
  const category_times = {};
  for (const row of rows) {
    const name = row.name.trim();
    categories.push(name);
    if (row.mode === 'per_day') {
      category_times[name] = structuredClone(row.raw);
      continue;
    }
    const entry = {};
    if (row.start !== '') entry.start = row.start;
    if (row.end !== '') entry.end = row.end;
    if (row.pause !== '') entry.pause = Number(row.pause);
    if (Object.keys(entry).length > 0) category_times[name] = entry;
  }
  return { categories, category_times };
}

function isControl(character) {
  const code = character.codePointAt(0);
  return code < 0x20 || (code >= 0x7f && code <= 0x9f) || (code >= 0xd800 && code <= 0xdfff);
}

export function validateCategoryRows(rows) {
  if (rows.length > MAX_CATEGORIES) return { ok: false, message: `Höchstens ${MAX_CATEGORIES} Kategorien.` };
  const seen = new Set();
  for (const row of rows) {
    const name = row.name.trim();
    if (name === '') return { ok: false, message: 'Der Name einer Kategorie darf nicht leer sein.' };
    if ([...name].length > MAX_NAME_LENGTH) {
      return { ok: false, message: `Der Name „${name.slice(0, 20)}…“ ist länger als ${MAX_NAME_LENGTH} Zeichen (höchstens ${MAX_NAME_LENGTH}).` };
    }
    if ([...name].some(isControl)) return { ok: false, message: `Der Name „${name}“ enthält ungültige Zeichen.` };
    if (seen.has(name)) return { ok: false, message: `Der Name „${name}“ kommt doppelt vor.` };
    seen.add(name);
    if (row.mode === 'per_day') continue;
    const start = row.start === '' ? null : parseTime(row.start);
    const end = row.end === '' ? null : parseTime(row.end);
    if (row.start !== '' && start === null) return { ok: false, message: `„${name}“: Start muss HH:MM sein.` };
    if (row.end !== '' && end === null) return { ok: false, message: `„${name}“: Ende muss HH:MM sein.` };
    if (start !== null && end !== null && end <= start) {
      return { ok: false, message: `„${name}“: Ende muss nach dem Start liegen.` };
    }
    if (row.pause !== '') {
      const pause = Number(row.pause);
      if (!/^[0-9]+$/.test(row.pause) || !Number.isInteger(pause) || pause > MAX_PAUSE) {
        return { ok: false, message: `„${name}“: Pause muss eine ganze Zahl von 0 bis ${MAX_PAUSE} Minuten sein.` };
      }
    }
  }
  return { ok: true };
}

export function timesSummary(row) {
  if (row.mode === 'per_day') return 'pro Wochentag';
  const parts = [];
  if (row.start && row.end) parts.push(`${row.start}–${row.end}`);
  else if (row.start) parts.push(`ab ${row.start}`);
  else if (row.end) parts.push(`bis ${row.end}`);
  if (row.pause !== '') parts.push(`${row.pause} min Pause`);
  return parts.length ? parts.join(', ') : '—';
}

export function moveRow(rows, index, direction) {
  const target = index + direction;
  if (target < 0 || target >= rows.length) return rows;
  const next = [...rows];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (isObject(value)) return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
  return value;
}

/** Gleichheit zweier Blöcke: Reihenfolge der Namen zählt, die Schlüsselreihenfolge der Zeiten nicht. */
export function blockSignature(categories, categoryTimes) {
  return JSON.stringify([categories, stable(categoryTimes ?? {})]);
}
```

`pwa/sw-core.js`: `'./categories.js',` hinter `'./reservations.js',` eintragen.

Hinweis: `parseTime` in `minutes.js` akzeptiert `HH:MM` (Zeile `export function parseTime`); sollte es auch `9:00` annehmen, den Test „a start that is not HH:MM“ gegen das echte Verhalten prüfen und die Zeitprüfung hier auf `/^([01]\d|2[0-3]):[0-5]\d$/` stützen.

- [ ] **Step 4: Run to verify pass**

Run: `cd pwa && node --test`
Expected: PASS (inklusive `shell.test.js`).

- [ ] **Step 5: Commit**

```bash
git add pwa/categories.js pwa/test/categories.test.js pwa/sw-core.js
git commit -m "feat(pwa): Kategorien-Logik — Zeilen, Block, Prüfung, Kurzfassung"
```

---

### Task 3: Store — Block in der Meta

**Files:**
- Modify: `pwa/store.js`
- Test: `pwa/test/store.test.js`

**Interfaces:**
- Consumes: Task 2 (`blockSignature`, `validateCategoryRows`, `categoryRows`).
- Produces (`Store`):
  - Meta: `settings_writable: false` (Default; von `applyResponse` aus `parsed.writable_settings`), `categories_edit: null` (oder `{ modified_at, dirty_version, synced_version, error }`)
  - `async saveCategories({ categories, category_times })` — wirft bei ungültigem Block oder wenn `settings_writable` falsch ist; ein unveränderter Block ist ein No-op
  - `snapshotSettings() → { settings: {categories: {value, modified_at}, category_times: {value, modified_at}}, settingsVersion } | null` (`null`, wenn nichts zu senden ist)
  - `async markSettingsError(message, version)`
  - `categoriesDirty() → boolean`
  - `pendingCount()`/`errorCount()` zählen den Block, solange `settings_writable` wahr ist
  - `applyResponse`: `parsed.writable_settings` (Array oder fehlend) → `settings_writable`; Kategorien und `defaults.category_times` werden nur ersetzt, wenn der Block nicht dirty ist oder genau der gesendete Stand bestätigt wird

- [ ] **Step 1: Failing tests** (`make`, `parsedResponse`, `emptySnapshot`, `RES_TODAY` und `clock` stehen in der Datei; `parsedResponse` bleibt unverändert, die neuen Tests setzen `defaults` und `writable_settings` über den Helfer `withDesktop` unten)

```js
// --- Kategorien-Block --------------------------------------------------------------------------------

const DEFAULTS = { pause: 0, weekdays: {}, category_times: { Projekt: { start: '09:00', end: '17:00', pause: 45 } } };
const withDesktop = (over = {}) => parsedResponse({
  categories: ['Projekt', 'Intern'], defaults: structuredClone(DEFAULTS),
  writable_settings: ['categories', 'category_times'], ...over });
const settingsSnapshot = (store) => ({ ...emptySnapshot(), ...(store.snapshotSettings() ?? {}) });

async function writable() {
  const made = await make();
  await made.store.applyResponse(withDesktop(), emptySnapshot(), RES_TODAY);
  return made;
}

test('saving categories changes the local view at once and marks the block dirty', async () => {
  const { store } = await writable();

  await store.saveCategories({ categories: ['Neu', 'Projekt'],
    category_times: { Projekt: { start: '08:00' } } });

  const meta = store.getMeta();
  assert.deepEqual(meta.categories, ['Neu', 'Projekt']);
  assert.deepEqual(meta.defaults.category_times, { Projekt: { start: '08:00' } });
  assert.equal(store.categoriesDirty(), true);
  assert.equal(store.pendingCount(), 1);
});

test('saving an unchanged block is a no-op', async () => {
  const { store } = await writable();
  await store.saveCategories({ categories: ['Projekt', 'Intern'], category_times: DEFAULTS.category_times });
  assert.equal(store.categoriesDirty(), false);
  assert.equal(store.getMeta().categories_edit, null);
});

test('an invalid block throws and changes nothing', async () => {
  const { store } = await writable();
  await assert.rejects(() => store.saveCategories({ categories: ['A', 'A'], category_times: {} }), /doppelt/);
  assert.deepEqual(store.getMeta().categories, ['Projekt', 'Intern']);
});

test('without writable_settings saving is refused', async () => {
  const { store } = await make();
  await store.applyResponse(withDesktop({ writable_settings: undefined }), emptySnapshot(), RES_TODAY);
  await assert.rejects(() => store.saveCategories({ categories: ['X'], category_times: {} }), /Desktop/);
  assert.equal(store.getMeta().settings_writable, false);
});

test('the snapshot carries both keys with one stamp and the version; clean or rejected blocks send nothing', async () => {
  const { store } = await writable();
  assert.equal(store.snapshotSettings(), null);
  await store.saveCategories({ categories: ['Neu'], category_times: {} });

  const snapshot = store.snapshotSettings();

  assert.deepEqual(Object.keys(snapshot.settings).sort(), ['categories', 'category_times']);
  assert.deepEqual(snapshot.settings.categories.value, ['Neu']);
  assert.equal(snapshot.settings.categories.modified_at, snapshot.settings.category_times.modified_at);
  assert.equal(snapshot.settingsVersion, 1);

  await store.markSettingsError('abgelehnt', snapshot.settingsVersion);
  assert.equal(store.snapshotSettings(), null);
  assert.equal(store.errorCount(), 1);
});

test('a confirmed block becomes clean and the desktop state replaces the local one', async () => {
  const { store } = await writable();
  await store.saveCategories({ categories: ['Neu'], category_times: {} });
  const snapshot = settingsSnapshot(store);

  await store.applyResponse(withDesktop({ categories: ['Neu'], defaults: { ...DEFAULTS, category_times: {} } }),
    snapshot, RES_TODAY);

  assert.equal(store.categoriesDirty(), false);
  assert.deepEqual(store.getMeta().categories, ['Neu']);
});

test('a block edited while the request was in flight stays local and dirty', async () => {
  const { store } = await writable();
  await store.saveCategories({ categories: ['Eins'], category_times: {} });
  const snapshot = settingsSnapshot(store);
  await store.saveCategories({ categories: ['Eins', 'Zwei'], category_times: {} });

  await store.applyResponse(withDesktop({ categories: ['Eins'], defaults: { ...DEFAULTS, category_times: {} } }),
    snapshot, RES_TODAY);

  assert.deepEqual(store.getMeta().categories, ['Eins', 'Zwei']);
  assert.equal(store.categoriesDirty(), true);
});

test('a dirty block that was not sent survives a response with other categories', async () => {
  const { store } = await writable();
  await store.saveCategories({ categories: ['Lokal'], category_times: {} });

  await store.applyResponse(withDesktop({ categories: ['Desktop'] }), emptySnapshot(), RES_TODAY);

  assert.deepEqual(store.getMeta().categories, ['Lokal']);
  assert.equal(store.categoriesDirty(), true);
});

test('other defaults still follow the desktop while the block is dirty', async () => {
  const { store } = await writable();
  await store.saveCategories({ categories: ['Lokal'], category_times: {} });

  await store.applyResponse(withDesktop({ defaults: { ...DEFAULTS, pause: 30 } }), emptySnapshot(), RES_TODAY);

  assert.equal(store.getMeta().defaults.pause, 30);
  assert.deepEqual(store.getMeta().defaults.category_times, {});
});

test('a desktop that drops writable_settings hides the block: it neither counts nor is sent', async () => {
  const { store } = await writable();
  await store.saveCategories({ categories: ['Lokal'], category_times: {} });

  await store.applyResponse(withDesktop({ writable_settings: undefined }), emptySnapshot(), RES_TODAY);

  assert.equal(store.pendingCount(), 0);
  assert.equal(store.snapshotSettings(), null);
  assert.equal(store.categoriesDirty(), true);                       // bleibt liegen für später
});

test('the category block survives a reload', async () => {
  const { store, adapter } = await writable();
  await store.saveCategories({ categories: ['Neu'], category_times: {} });

  const second = new Store(adapter);
  await second.load();

  assert.deepEqual(second.getMeta().categories, ['Neu']);
  assert.equal(second.categoriesDirty(), true);
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd pwa && node --test test/store.test.js`
Expected: FAIL (`store.saveCategories is not a function` u. a.).

- [ ] **Step 3: Implementation** (`pwa/store.js`)

Importe: `import { blockSignature, categoryRows, validateCategoryRows } from './categories.js';`

`DEFAULT_META` ergänzen:

```js
  settings_writable: false,   // Desktop versteht `settings` (Feld `writable_settings` in der Antwort); sonst ist das Bearbeiten aus
  categories_edit: null,      // Kategorien-Block des Handys: { modified_at, dirty_version, synced_version, error } oder null
```

Hilfen (Modulebene):

```js
const editDirty = (edit) => Boolean(edit) && edit.dirty_version > edit.synced_version;
```

Methoden (hinter `errorCount`):

```js
  // --- Kategorien (Einstellungen) --------------------------------------------------------------

  categoriesDirty() {
    return editDirty(this._meta.categories_edit);
  }

  /** Speichert den Kategorien-Block (Namen und Standardzeiten zusammen). Die lokale Ansicht
   *  (`categories`, `defaults.category_times`) ändert sich sofort; der Abgleich schickt den Block. */
  async saveCategories({ categories, category_times: categoryTimes }) {
    if (!this._meta.settings_writable || !this._meta.defaults) {
      throw new Error('Der Desktop unterstützt das Bearbeiten der Kategorien nicht. Bitte die Desktop-App aktualisieren.');
    }
    const check = validateCategoryRows(categoryRows(categories, categoryTimes));
    if (!check.ok) throw new Error(check.message);
    if (blockSignature(categories, categoryTimes)
      === blockSignature(this._meta.categories, this._meta.defaults.category_times)) return;
    const old = this._meta.categories_edit;
    await this.setMeta({
      categories: structuredClone(categories),
      defaults: { ...this._meta.defaults, category_times: structuredClone(categoryTimes) },
      categories_edit: {
        modified_at: this._stampAfter(old?.modified_at),
        dirty_version: (old ? old.dirty_version : 0) + 1,
        synced_version: old ? old.synced_version : 0,
        error: null,
      },
    });
  }

  /** Der Block für den nächsten Abgleich (`null`: nichts zu senden, abgelehnt oder Desktop versteht es nicht). */
  snapshotSettings() {
    const edit = this._meta.categories_edit;
    if (!this._meta.settings_writable || !editDirty(edit) || edit.error || !this._meta.defaults) return null;
    return {
      settings: {
        categories: { value: structuredClone(this._meta.categories), modified_at: edit.modified_at },
        category_times: { value: structuredClone(this._meta.defaults.category_times), modified_at: edit.modified_at },
      },
      settingsVersion: edit.dirty_version,
    };
  }

  async markSettingsError(message, version) {
    const edit = this._meta.categories_edit;
    if (!edit || (version !== undefined && edit.dirty_version !== version)) return;
    await this.setMeta({ categories_edit: { ...edit, error: String(message) } });
  }
```

`pendingCount()` und `errorCount()`: den Block mitzählen, solange `this._meta.settings_writable` wahr ist:

```js
    const block = this._meta.settings_writable ? this._meta.categories_edit : null;
    // pendingCount: + (editDirty(block) ? 1 : 0);  errorCount: + (block?.error ? 1 : 0)
```

`applyResponse`: vor dem Setzen von `this._meta` bestimmen und im Meta-Objekt ersetzen:

```js
    const edit = this._meta.categories_edit;
    const sentSettings = snapshot.settingsVersion;
    const confirmed = editDirty(edit) && sentSettings !== undefined && sentSettings === edit.dirty_version;
    const keepLocal = editDirty(edit) && !confirmed;
    const nextDefaults = structuredClone(parsed.defaults ?? null);
    if (keepLocal && nextDefaults && this._meta.defaults) {
      nextDefaults.category_times = structuredClone(this._meta.defaults.category_times);
    }
```

und im `this._meta = {...}`:

```js
      settings_writable: Array.isArray(parsed.writable_settings)
        && parsed.writable_settings.includes('categories') && parsed.writable_settings.includes('category_times'),
      categories: keepLocal ? this._meta.categories : [...parsed.categories],
      defaults: nextDefaults,
      categories_edit: confirmed ? { ...edit, synced_version: edit.dirty_version, error: null } : edit,
```

(die bisherigen Zeilen `categories: [...parsed.categories]` und `defaults: structuredClone(parsed.defaults ?? null)` entfallen). Ein Desktop ohne `writable_settings` liefert hier `settings_writable: false`; ein dirty Block bleibt liegen.

- [ ] **Step 4: Run to verify pass**

Run: `cd pwa && node --test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pwa/store.js pwa/test/store.test.js
git commit -m "feat(pwa): Kategorien-Block im Store — speichern, senden, bestätigen"
```

---

### Task 4: `sync.js` — Antwort lesen, Block senden, Ablehnung zuordnen

**Files:**
- Modify: `pwa/sync.js`, `pwa/test/fixtures/sync-request.json`, `tests/test_mobile_contract.py`
- Test: `pwa/test/sync.test.js`, `pwa/test/compat.test.js`

**Interfaces:**
- Consumes: Task 3 (`snapshotSettings`, `markSettingsError`, `parsed.writable_settings`).
- Produces: `parseSyncResponse` liefert `writable_settings: string[]` (nur Strings aus der Antwort, sonst `[]`); `SyncError.setting` (`'categories' | 'category_times' | null`); der Client sendet `settings` im ersten Päckchen.

- [ ] **Step 1: Failing tests** (`make`, `fixture`, `reply`, `SLOT`, `NOW` stehen in `sync.test.js`; Muster der Reservierungs-Tests dort)

```js
// --- Einstellungen ----------------------------------------------------------------------------------

test('the response lists the writable settings; a response without the field gives an empty list', () => {
  assert.deepEqual(parseSyncResponse(fixture('sync-response.json')).writable_settings, ['categories', 'category_times']);
  assert.deepEqual(parseSyncResponse(fixture('compat/sync-response-pre-settings.json')).writable_settings, []);
  assert.deepEqual(parseSyncResponse({ ...fixture('sync-response.json'), writable_settings: ['x', 5] }).writable_settings, ['x']);
});

test('a rejected setting is told apart from a rejected day', () => {
  const error = classifyHttpError(422, { error: { code: 'invalid_entry', message: 'Einstellung category_times: Pause ist ungültig.' } });
  assert.deepEqual([error.setting, error.day, error.dayKind], ['category_times', null, null]);
  assert.equal(classifyHttpError(422, { error: { code: 'invalid_entry', message: '2026-10-07: kaputt' } }).setting, null);
});

test('a dirty category block goes out in the first request only, with one stamp for both keys', async () => {
  const { store, client, fetchFn } = await make();
  await store.applyResponse(parseSyncResponse(fixture('sync-response.json')),
    { entries: {}, versions: {}, reservations: {}, reservationVersions: {} }, '2026-10-08');
  await store.saveCategories({ categories: ['Neu'], category_times: { Neu: { start: '09:00' } } });

  await client.sync();

  const sent = fetchFn.calls[0].plain.settings;
  assert.deepEqual(Object.keys(sent).sort(), ['categories', 'category_times']);
  assert.deepEqual(sent.categories.value, ['Neu']);
  assert.equal(sent.categories.modified_at, sent.category_times.modified_at);
  assert.equal(store.categoriesDirty(), false);
});

test('a sync without a dirty block sends no settings field', async () => {
  const { store, client, fetchFn } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  await client.sync();
  assert.equal('settings' in fetchFn.calls[0].plain, false);
});

test('a 422 for the block marks only the block; the next sync goes through without it', async () => {
  let n = 0;
  const { store, client, fetchFn } = await make({ handler: () => {
    n += 1;
    return n === 1
      ? reply(422, { error: { code: 'invalid_entry', message: 'Einstellung categories: höchstens 100 Kategorien.' } }, { sealed: true })
      : reply(200, fixture('sync-response.json'));
  } });
  await store.applyResponse(parseSyncResponse(fixture('sync-response.json')),
    { entries: {}, versions: {}, reservations: {}, reservationVersions: {} }, '2026-10-08');
  await store.saveCategories({ categories: ['Neu'], category_times: {} });

  await assert.rejects(() => client.sync(), (error) => error.kind === 'invalid_entry' && error.setting === 'categories');
  assert.equal(store.getMeta().categories_edit.error !== null, true);

  await client.sync();
  assert.equal('settings' in fetchFn.calls[1].plain, false);
});
```

`compat.test.js`: ein Test für `sync-response-pre-settings.json` (`writable_settings` leer, Einträge unverändert gelesen).

Live-Beispiel erweitern: `pwa/test/fixtures/sync-request.json` bekommt `"settings": {"categories": {"value": ["Projekt", "Intern"], "modified_at": "2026-10-07T18:45:00Z"}, "category_times": {"value": {"Projekt": {"start": "09:00", "end": "17:00", "pause": 45}}, "modified_at": "2026-10-07T18:45:00Z"}}`. Der vorhandene Formtest „a sync sends bearer, request shape and the dirty days…“ vergleicht die Schlüssel des echten Requests mit dem Beispiel: er braucht im Aufbau einen dirty Block (`applyResponse` der Fixture-Antwort, dann `saveCategories`) und prüft `Object.keys(call.plain.settings)` gegen das Beispiel. Python (`tests/test_mobile_contract.py`): in `test_the_sync_request_example_has_the_shape_the_phone_sends` `set(example) - {"reservations", "settings"}` statt `- {"reservations"}`, und

```python
def test_the_live_request_example_carries_settings_the_server_reads():
    example = load("sync-request.json")
    assert example["settings"]

    parsed = mobile_sync.parse_request(
        json.dumps(example).encode(), now=example["client_time"],
        today=datetime.date.fromisoformat(example["client_time"][:10]))

    assert sorted(parsed.settings) == ["categories", "category_times"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd pwa && node --test test/sync.test.js test/compat.test.js`
Expected: FAIL.

- [ ] **Step 3: Implementation** (`pwa/sync.js`)

`SyncError`-Konstruktor: Parameter `setting = null`, in `Object.assign` aufnehmen. `classifyHttpError`:

```js
  const setting = kind === 'invalid_entry' ? (/^Einstellung (categories|category_times):/.exec(message)?.[1] ?? null) : null;
  // … in new SyncError({ …, day, dayKind, setting, supportedProtocol })
```

`parseSyncResponse` dem Ergebnis hinzufügen:

```js
    writable_settings: Array.isArray(raw.writable_settings) ? raw.writable_settings.filter((key) => typeof key === 'string') : [],
```

`_run`/`_runOnce`: der Parameter `withReservations` heißt jetzt `first` (er gilt für beide Zusatzfelder). Nach dem Reservierungs-Snapshot:

```js
    const settings = first ? this._store.snapshotSettings() : null;
    if (settings) Object.assign(snapshot, settings); else snapshot.settingsVersion = undefined;
```

Payload: `...(settings ? { settings: settings.settings } : {})`. Im `catch`, neben der Tageszuordnung:

```js
      if (error instanceof SyncError && error.kind === 'invalid_entry' && error.setting) {
        await this._store.markSettingsError(error.message, snapshot.settingsVersion);
      }
```

- [ ] **Step 4: Run to verify pass**

Run: `cd pwa && node --test && cd .. && pytest tests/test_mobile_contract.py -q && ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pwa/sync.js pwa/test pwa/CLAUDE.md tests/test_mobile_contract.py
git commit -m "feat(pwa): Kategorien im Abgleich — senden, Ablehnung dem Block zuordnen"
```

---

### Task 5: `view-model.js` — Reiter und Kategorien-Modell

**Files:**
- Modify: `pwa/view-model.js`
- Test: `pwa/test/view-model.test.js`

**Interfaces:**
- Consumes: Task 2 (`categoryRows`, `timesSummary`), Task 3 (`settings_writable`, `categories_edit`).
- Produces:
  - `SETTINGS_TABS = ['connection', 'categories', 'updates']` und `settingsTabLabel(key)` (`'Verbindung'`, `'Kategorien'`, `'Updates'`)
  - `categoriesModel({ categories, defaults, writable, edit }) → { rows, editable, hint, error, dirty }`: `rows` aus `categoryRows(categories, defaults?.category_times ?? {})` mit `summary` je Zeile; `editable` = `writable && defaults !== null`; `hint` ist `''` oder der Text für einen älteren Desktop („Die Desktop-App ist älter … Kategorien lassen sich dort bearbeiten.“); `error` = `edit?.error ?? null`; `dirty` = `Boolean(edit) && edit.dirty_version > edit.synced_version`
  - `categoryRemovalText(name) → string` (Bestätigungstext mit dem Hinweis auf bestehende Einträge)
  - `categoryRenameHint = 'Bestehende Einträge behalten den alten Namen.'` (Konstante)

- [ ] **Step 1: Failing tests**

```js
// --- Einstellungen / Kategorien -----------------------------------------------------------------------

import { SETTINGS_TABS, categoriesModel, categoryRemovalText, categoryRenameHint, settingsTabLabel } from '../view-model.js';

test('the settings tabs are connection, categories, updates, in that order, with German labels', () => {
  assert.deepEqual(SETTINGS_TABS, ['connection', 'categories', 'updates']);
  assert.deepEqual(SETTINGS_TABS.map(settingsTabLabel), ['Verbindung', 'Kategorien', 'Updates']);
});

test('the categories model lists rows with a summary and is editable with a writable desktop', () => {
  const model = categoriesModel({ categories: ['Projekt', 'Support'], writable: true,
    defaults: { category_times: { Projekt: { start: '09:00', end: '17:00', pause: 45 },
      Support: { mode: 'per_day', days: {} } } }, edit: null });

  assert.equal(model.editable, true);
  assert.deepEqual(model.rows.map((r) => r.summary), ['09:00–17:00, 45 min Pause', 'pro Wochentag']);
  assert.equal(model.hint, '');
  assert.equal(model.dirty, false);
});

test('an older desktop leaves the list readable but not editable, with a hint', () => {
  const model = categoriesModel({ categories: ['A'], writable: false, defaults: { category_times: {} }, edit: null });
  assert.equal(model.editable, false);
  assert.match(model.hint, /Desktop-App/);
  assert.equal(model.rows.length, 1);
});

test('without any defaults the list is still readable', () => {
  const model = categoriesModel({ categories: ['A'], writable: true, defaults: null, edit: null });
  assert.equal(model.editable, false);
  assert.equal(model.rows[0].summary, '—');
});

test('the model reports a dirty and a rejected block', () => {
  const model = categoriesModel({ categories: ['A'], writable: true, defaults: { category_times: {} },
    edit: { modified_at: 'x', dirty_version: 2, synced_version: 1, error: 'Einstellung categories: zu viele' } });
  assert.equal(model.dirty, true);
  assert.equal(model.error, 'Einstellung categories: zu viele');
});

test('removing and renaming say that existing entries keep the old name', () => {
  assert.match(categoryRemovalText('Projekt'), /Projekt/);
  assert.match(categoryRemovalText('Projekt'), /behalten/);
  assert.match(categoryRenameHint, /alten Namen/);
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd pwa && node --test test/view-model.test.js`
Expected: FAIL.

- [ ] **Step 3: Implementation** (`pwa/view-model.js`)

`import { categoryRows, timesSummary } from './categories.js';` und:

```js
// --- Einstellungen ---------------------------------------------------------------------------------

export const SETTINGS_TABS = ['connection', 'categories', 'updates'];
const TAB_LABELS = { connection: 'Verbindung', categories: 'Kategorien', updates: 'Updates' };
export const settingsTabLabel = (key) => TAB_LABELS[key];

export const categoryRenameHint = 'Bestehende Einträge behalten den alten Namen.';

export function categoryRemovalText(name) {
  return `Die Kategorie „${name}“ wird gelöscht. Bestehende Einträge behalten ihren Namen, sie erscheint nur nicht mehr in der Auswahl.`;
}

/** Der Reiter „Kategorien“: Zeilen mit Kurzfassung, ob bearbeitet werden darf (der Desktop versteht
 *  `settings`) und der Zustand des Blocks. Ein älterer Desktop lässt die Liste lesbar, aber nicht
 *  bearbeitbar (Feature-Erkennung wie bei den Reservierungen). */
export function categoriesModel({ categories, defaults, writable, edit }) {
  const rows = categoryRows(categories, defaults?.category_times ?? {}).map((row) => ({
    ...row, summary: timesSummary(row) }));
  const editable = Boolean(writable) && defaults !== null && defaults !== undefined;
  return {
    rows,
    editable,
    hint: editable ? '' : 'Die Desktop-App ist älter als diese Seite: Kategorien lassen sich nur dort bearbeiten. Bitte die Desktop-App aktualisieren.',
    error: edit?.error ?? null,
    dirty: Boolean(edit) && edit.dirty_version > edit.synced_version,
  };
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd pwa && node --test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pwa/view-model.js pwa/test/view-model.test.js
git commit -m "feat(pwa): Modell für die Einstellungen — Reiter und Kategorienliste"
```

---

### Task 6: Oberfläche — Einstellungen-Dialog mit Reitern, Kategorien-Reiter

**Files:**
- Modify: `pwa/views.js`, `pwa/app.js`, `pwa/app.css`, `pwa/messages.js`
- Test: `pwa/test/shell.test.js` bleibt grün (kein `innerHTML`); `pwa/test/messages.test.js`, falls es den Text mit „Verbindung“ prüft; die DOM-Schicht wird von Hand im Browser geprüft (Step 5).

**Interfaces:**
- Consumes: Tasks 2–5.
- Produces: `settingsDialog(model, handlers)` ersetzt `connectionDialog`; `categoryEditDialog(row, handlers)`; der Button unten links heißt „Einstellungen“ (`data-focus="settings"`).

**Entwurf.**
- `statusBar`: `button('Einstellungen', handlers.settings, '', { 'data-focus': 'settings' })`; `app.js`: `statusBar({ sync, settings: () => this.openSettings() })`, `openConnection` → `openSettings(initialTab = 'connection')`.
- `settingsDialog({ tab, connection, updates, categories }, handlers)`: Überschrift „Einstellungen“, Reiterzeile im Stil der Editor-Reiter (`role="tablist"`, `aria-selected`), drei Bereiche, die per `hidden` umgeschaltet werden (Zustand bleibt beim Wechsel erhalten). „Verbindung“ ist der Inhalt des bisherigen Dialogs ohne Updates und ohne „Schließen“ (Adresse, Desktop, Version, Plattform, Kopplung gültig bis, dauerhafter Speicher, Verlauf mit „Auf 90 Tage zurücksetzen“, `desktopHint`, „QR neu scannen / Neu koppeln“). „Updates“: Handy-App-Version, Status, „Nach Updates suchen“, „Jetzt neu laden“, „Updates automatisch einspielen“ (unverändert aus dem alten Dialog, gleiche Handler). Darunter eine Schließen-Zeile.
- Kategorien-Reiter: oben `hint` (älterer Desktop) und `error` (`role="alert"`, der Fehler des abgelehnten Blocks); die Liste (`ul.categories`) mit je Zeile: Name, `summary` (`class="muted"`), Buttons `▲`/`▼` (`aria-label` „Nach oben“/„Nach unten“, an den Enden `disabled`) und ein Zeilen-Button zum Bearbeiten (nur `editable`). `+ Kategorie` (nur `editable`). `Speichern` (`primary`), `disabled`, solange nichts geändert oder die Prüfung (`validateCategoryRows`) fehlschlägt; die Prüfmeldung steht darunter. Der Reiter hält `rows` als eigenen Zustand (Kopie von `categoryRows`); jede Änderung (Umbenennen, Zeiten, Sortieren, Löschen, Hinzufügen) ändert nur diesen Zustand.
- `categoryEditDialog(row, { onDone, onRemove })`: Unterdialog (`h('dialog')`, wie der Kategorie-Picker) mit Name, Start, Ende, Pause (`type="time"`/`number`, leer = „globaler Standard“, Platzhalter „Standard“), dem Hinweis `categoryRenameHint`, „Löschen“ (öffnet `confirmDialog` mit `categoryRemovalText`) und „Fertig“. Eine `per_day`-Zeile zeigt statt der Zeitfelder „Pro Wochentag eingestellt — am Desktop bearbeiten.“ und erlaubt nur Name und Löschen.
- „Speichern“ ruft `handlers.saveCategories(rows)`: es prüft den Stand wie die Tages-Editoren (`dayChanged`-Muster: ist `blockSignature` des Stores seit dem Öffnen ein anderer, kommt einmalig die Warnung „Die Kategorien wurden inzwischen aktualisiert (Abgleich). Nochmaliges Speichern überschreibt die neuere Fassung.“), ruft `store.saveCategories(rowsToBlock(rows))`, danach `this.render()` und `this.scheduleSyncAfterSave()`; eine Ausnahme wird als Meldung im Reiter gezeigt.
- Schließen mit ungespeicherten Änderungen: `confirmDialog({ title: 'Änderungen verwerfen?', … })`.
- `messages.js`: im Text der Zeitüberschreitung „unter „Verbindung““ → „unter Einstellungen → Verbindung“; `views.js`/`pairView`-Texte, die „Verbindung“ als Knopf meinen, ebenso.
- `app.css`: Reiterzeile (die vorhandenen `.tabs`-Regeln wiederverwenden), `.categories` (Liste ohne Aufzählungszeichen, Zeilen wie `.day`-Karten, Buttons mit `min-height: var(--tap)`), Dialog scrollbar (`max-height: 90vh; overflow-y: auto`).

- [ ] **Step 1: `views.js` und `app.js` umbauen** wie im Entwurf. Den bisherigen Inhalt von `connectionDialog` nicht neu erfinden: die Teile (Zeilen `h('dl', …)`, Update-Bedienung, `resetWindow`, Neu koppeln) in die beiden Reiter verschieben, Handler und IDs behalten (`auto-update`, `data-focus`-Schlüssel).
- [ ] **Step 2: `messages.js`/`app.css`/`pwa/sw-core.js`** anpassen (kein neues Laufzeitmodul in diesem Task; `categories.js` steht seit Task 2 in `PRECACHE`).
- [ ] **Step 3: Automatische Prüfung**

Run: `cd pwa && node --check app.js && node --check views.js && node --test`
Expected: PASS (inklusive `shell.test.js`: kein `innerHTML`, `PRECACHE` vollständig).

- [ ] **Step 4: Von Hand im Browser** (UI wird nicht automatisiert getestet). `python scripts/pwa_devserver.py --reservations` starten (legt Kategorien `Projekt` mit Zeiten, `Support` pro Wochentag und `Intern` an), mit dem ausgegebenen Link koppeln, dann:
  1. Der Button unten links heißt „Einstellungen“; der Dialog zeigt die Reiter Verbindung / Kategorien / Updates; „Verbindung“ und „Updates“ verhalten sich wie vorher.
  2. „Kategorien“ zeigt die drei Kategorien mit Kurzfassung; `Support` zeigt „pro Wochentag“.
  3. Umbenennen, Zeiten ändern, Sortieren, Löschen, `+ Kategorie`; „Speichern“ ist erst nach einer gültigen Änderung aktiv; ungültige Eingaben zeigen die Meldung.
  4. Nach „Speichern“ steht der Block in `settings.json` des Desktops (Pfad im Dev-Server-Log), `Support` mit unveränderten Wochentag-Zeiten.
  5. Der Kategorie-Picker im Tages-Editor zeigt sofort die neuen Namen.
  6. Reiterwechsel verliert keine Eingaben; Schließen mit ungespeicherten Änderungen fragt.
  7. Ohne Eingriff am Desktop ändern (Datei `settings.json` ist im Dev-Server nicht live editierbar): den Fall „älterer Desktop“ mit einer Antwort ohne `writable_settings` per Browser-Konsole prüfen (`store`-Meta setzen: `settings_writable: false`) — Bearbeiten ist aus, Hinweis sichtbar.
- [ ] **Step 5: Commit**

```bash
git add pwa/views.js pwa/app.js pwa/app.css pwa/messages.js
git commit -m "feat(pwa): Einstellungen-Dialog mit Reitern und Kategorien-Verwaltung"
```

---

### Task 7: Doku

**Files:**
- Modify: `pwa/CLAUDE.md`, `src/CLAUDE.md`, `CLAUDE.md`, `README.md`, Spec

- [ ] **Step 1: `pwa/CLAUDE.md`**
  - Modulliste: `categories.js` (Zeilen, Block, Prüfung, Kurzfassung; per_day durchgereicht).
  - Neuer Abschnitt „Einstellungen und Kategorien“: Dialog mit Reitern (Verbindung, Kategorien, Updates), Block in der Meta (`categories_edit`, `settings_writable`), Senden im ersten Päckchen mit einem Stempel für beide Schlüssel, Bestätigung/„während des Requests geändert“, `422` je Block, Feature-Erkennung über `writable_settings` (ältere Desktops: lesbar, nicht bearbeitbar; ein dirty Block bleibt liegen und zählt nicht), per_day wird nie verändert, Umbenennen/Löschen schreiben nichts um, Grenzen (100/100/1440), Konflikte nur am Desktop, vorgehende Handy-Uhr (Konflikt „Handy gegen Handy“, kein Datenverlust).
  - Kompatibilität: „neue PWA, alter Desktop“ um `writable_settings` ergänzen; `DB`-Version bleibt 2 (der Block liegt in der Meta).
  - „Entwickeln und prüfen“: der Dev-Server legt Kategorien mit Zeiten an.
- [ ] **Step 2: `src/CLAUDE.md`** — Satz, dass die PWA seit PR 2 `settings` sendet (Verweis auf `pwa/CLAUDE.md`), `writable_settings` (aus Task 1 schon eingetragen).
- [ ] **Step 3: Wurzel-`CLAUDE.md`** — Zeile `pwa/`: Kategorien-Verwaltung; `src/mobile_settings.py`: Gegenstück `pwa/categories.js`.
- [ ] **Step 4: `README.md`**, Abschnitt „Handy-Erfassung“: ein Satz, dass sich Kategorien samt Standardzeiten auch am Handy verwalten lassen (Einstellungen → Kategorien), mit `*(ab --VERSION--)*` am fetten Namen bzw. am neuen Satz nach der Regel der Wurzel-`CLAUDE.md`.
- [ ] **Step 5: Spec** — Abschnitt „PR 2: PWA“ um die Feature-Erkennung über `writable_settings` ergänzen (statt „Antwort ohne `category_times`“) und das ändern, was sich beim Bauen verändert hat.
- [ ] **Step 6: Prüfen und committen**

Run: `pytest tests/test_claude_md_claims.py -q && ruff check .`
Expected: PASS.

```bash
git add pwa/CLAUDE.md src/CLAUDE.md CLAUDE.md README.md docs/superpowers/specs/2026-10-13-pwa-einstellungen-kategorien-design.md
git commit -m "docs(pwa): Einstellungen und Kategorien in der Handy-PWA"
```

---

## Abschluss

- [ ] Vollständiger Lauf: `pytest -q --ignore=tests/test_qr.py`, `ruff check .`, `(cd pwa && node --test)`.
- [ ] Browser-Prüfung aus Task 6, Step 4 ist Pflicht: die DOM-Schicht hat keinen automatisierten Test.
- [ ] PR gegen `master`, Titel `feat(pwa): Einstellungen und Kategorien in der Handy-PWA (PR 2/2)`, **kein** `release:*`-Label, **kein** Versionsbump in `pwa/package.json` (Release-PR). Nach dem Merge ist die PWA sofort live; ein Desktop ohne #311 zeigt „Kategorien bearbeiten“ nie an (Feature-Erkennung). Ein Pre-Release des Desktops ist vor dem Release sinnvoll, damit die echte Kopplung gegen den neuen Stand getestet werden kann.

## Self-Review

- **Spec-Abdeckung:** Button „Einstellungen“ und Reiter Verbindung/Kategorien/Updates → T6; Kategorien (Namen + Standardzeiten, sortieren, per_day unverändert, Hinweise beim Umbenennen/Löschen, Prüfungen, „inzwischen aktualisiert“-Warnung, älterer Desktop) → T2/T3/T5/T6; Block im Store mit Dirty-Logik und Race → T3; Senden/`422` → T4; Doku inkl. README → T7. Die Ergänzung `writable_settings` (T1) steht ausdrücklich als Spec-Änderung in Kopf und T7.
- **Platzhalter-Scan:** Task 6 beschreibt die DOM-Schicht als Entwurf mit Verhalten statt als vollständigen Code, weil sie am vorhandenen `connectionDialog`/`editorDialog` hängt, die der Ausführende zuerst liest; die drei Test-Rümpfe-Hinweise in Task 4 („Aufbau im Formtest“) nennen die Stelle. Sonst keine offenen Stellen.
- **Typkonsistenz:** `saveCategories({categories, category_times})`, `snapshotSettings() → {settings, settingsVersion}`, `markSettingsError(message, version)`, `categoriesDirty()`, `settings_writable`, `categories_edit`, `parsed.writable_settings`, `SyncError.setting` werden in T3/T4/T5/T6 gleich benannt; die Zeilenform `{name, mode, start, end, pause, raw}` ist in T2 definiert und in T5/T6 unverändert verwendet.
