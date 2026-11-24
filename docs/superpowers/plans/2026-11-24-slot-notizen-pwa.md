# Notiz am Slot, PR 3: Handy-PWA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Handy-PWA zeigt die Notiz eines Ist-Zeit-Slots (Wochenliste, Konfliktversionen), lässt sie im Tages-Editor setzen (Eingabefeld mit aufklappbarer Liste der bisherigen Notizen) und schickt sie an den Desktop, ohne je Notizen am Desktop zu löschen, die sie nicht kennt.

**Architecture:** Der Desktop liefert seit #527 `notiz` an jedem Slot der Antwort und die Fähigkeit `slot_notes: true`, und er nimmt `notiz` je Tag an allen Slots oder an keinem an (gemischt: `422 invalid_entry`). Die PWA liest beides (Feature-Erkennung), hält die Notiz am Slot ihres Speichers und merkt sich je Tag, ob sie dessen Notizen kennt (`notes_known` am Datensatz, nicht im Eintrag). Die Regeln der Notiz liegen DOM-frei in einem neuen `pwa/notes.js`, Gegenstück zu `src/slot_notes.py`, gehalten über die gemeinsame Fixture `pwa/test/fixtures/note-cases.json`.

**Tech Stack:** reines JavaScript ohne Build und ohne Abhängigkeiten, `node --test` (Node 22 in CI, lokal v20); Python-Vertragstests (`pytest`).

**Spec:** `docs/superpowers/specs/2026-11-23-slot-notizen-design.md`, Abschnitte „Handy-PWA“, „Ausgabewege“ (Handy-Abgleich), „Regeln der Notiz“. Repo-Regeln: `pwa/CLAUDE.md` (Kompatibilität, Regel 2 und 4; Tests; Kontrast; Übergänge), Wurzel-`CLAUDE.md` („Kommentare und Docstrings“).

**Stapel:** der Branch `feat/slot-notizen-pwa` liegt auf `feat/slot-notizen-desktop` (#530, PR 2): dort hat `slot_notes.suggestions` die Reihenfolge „Kategorie zuerst, dann alle übrigen“, die Task 1 in JavaScript nachbaut und über die Fixture prüft. Der PR geht gegen `feat/slot-notizen-desktop` und wandert nach dem Merge von #530 von selbst auf `master`. Darauf folgt der Release-PR. PR-Text `Closes #519` (letzter Teil), kein `release:*`-Label.

## Global Constraints

- Kein Versionssprung: `PROTOCOL` 2, IndexedDB-`VERSION` unverändert (neue Felder liegen in Meta und Datensatz, kein neuer Object Store).
- Ohne `slot_notes` in der letzten Antwort: kein Notizfeld, keine Notiz in Anzeige und Anfrage — die PWA verhält sich wie heute (Anfrage Byte für Byte wie heute).
- Gesendet wird `notiz` nur für Tage mit `notes_known`, dann an **jedem** Slot des Tages (`""` = keine Notiz); sonst an **keinem**. Nie gemischt.
- Notiz-Regeln nur aus `pwa/notes.js` (`cleanNote`, `checkNote`, `groupKey`, `MAX_NOTE_LEN` = 200 Code Points, getrimmt wie `trim()` samt U+FEFF, keine `Cc`/`Cs`/`Zl`/`Zp`); Gleichlauf mit Python über `note-cases.json`.
- Fremddaten aus der Antwort werfen nie: eine unbrauchbare `notiz` wird bereinigt bzw. leer.
- DOM nur über `createElement`/Textknoten (Test verbietet `innerHTML`); Farben nur aus den Tokens in `app.css`, Text mindestens 4,5:1 (`test/contrast.test.js`), neue Flächen dort eintragen; Animationen höchstens 200 ms, nur `transform`/`opacity`; Hover nur in `@media (hover: hover)`.
- `PRECACHE` in `sw-core.js` listet jede neue Laufzeitdatei (`test/shell.test.js`).
- Kommentare sagen das Warum, keine Historie. Commits enden mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` und `Claude-Session: https://claude.ai/code/session_01C9TQTpqHqaEXeGMCPPoL1c`.

## Review Focus

1. Ein Tag, der vor `slot_notes` lokal geändert und noch nicht übertragen wurde, geht nach dem ersten Abgleich mit `slot_notes` **ohne** `notiz` hinaus; die Notizen am Desktop bleiben. → Task 2
2. Ein am Desktop mit Notiz gespeicherter Tag kommt an, wird am Handy nur in der Pause geändert: die Anfrage trägt die Notiz unverändert an diesem Slot, `""` an den übrigen. → Task 2
3. Eine reine Notiz-Änderung am Handy gilt als Änderung (wird übertragen). → Task 2
4. Das Dropdown mit 20 langen Notizen bei 280 px: kein waagerechtes Scrollen, Einträge mit „…“ gekürzt, Liste scrollt in sich, Fußknöpfe des Dialogs bleiben sichtbar. → Task 3
5. Eine Notiz mit 201 Zeichen oder einem Zeilenumbruch (eingefügt): Fehler am Feld, nichts gespeichert. → Task 3

## File Structure

| Datei | Aufgabe |
|---|---|
| `pwa/notes.js` (neu) | Regeln: `cleanNote`, `checkNote`, `groupKey`, `noteSuggestions`, `MAX_NOTE_LEN` |
| `pwa/test/notes.test.js` (neu), `pwa/test/fixtures/note-cases.json` | Gleichlauf mit Python, Fälle für Vorschläge |
| `pwa/sync.js`, `pwa/minutes.js`, `pwa/store.js` | Lesen, Speichern, Senden |
| `pwa/test/fixtures/sync-request.json`, `compat/sync-request-pre-notes.json` (neu) | Vertrag der Anfrage |
| `pwa/view-model.js`, `pwa/views.js`, `pwa/app.js`, `pwa/app.css` | Editor, Woche, Konflikte, Einstellung |
| `pwa/sw-core.js` | `PRECACHE` + `./notes.js` |
| `pwa/CLAUDE.md`, `README.md`, `CLAUDE.md` | Doku |

---

### Task 1: Notiz-Regeln in JavaScript (`notes.js`)

**Files:** Create `pwa/notes.js`, `pwa/test/notes.test.js`. Modify `pwa/test/fixtures/note-cases.json`, `tests/test_slot_notes.py`, `pwa/sw-core.js` (`PRECACHE`).

**Interfaces (Produces):**

```js
export const MAX_NOTE_LEN = 200;
export function cleanNote(value) {}          // Fremddaten → string, wirft nie (wie slot_notes.clean_note)
export function checkNote(value) {}          // Eingabe → {ok: true, note} | {ok: false, message}
export function groupKey(note) {}            // trim + toLowerCase
export function noteSuggestions(days, kategorie, limit = 20) {}   // days: {ISO: {slots:[{kategorie, notiz}]}} → string[]
```

- `checkNote`-Meldungen (deutsch, eine Zeile): „Höchstens 200 Zeichen.“ und „Nur eine Zeile, keine Steuerzeichen.“
- `noteSuggestions`: dieselbe Regel wie `slot_notes.suggestions` (#530): Tage absteigend nach Datum, je Tag gespeicherte Reihenfolge; erst Slots der Kategorie, dann alle übrigen; je `groupKey` einmal; gelöschte Tage (`deleted`) übergehen.
- Code Points zählen mit `[...text].length`, nicht `text.length`.

- [ ] **Step 1:** In `note-cases.json` einen Block `"suggestions"` ergänzen: `[{"days": {...}, "kategorie": "Montage", "out": [...]}, …]` — mindestens die beiden Fälle aus `tests/test_slot_notes.py::test_suggestions_newest_first_once_per_group_key` und `test_suggestions_offer_a_note_of_another_category_once` (App-Form-Slots mit `notiz`), dazu einen Fall mit `limit` (Feld `"limit"`).
- [ ] **Step 2:** `tests/test_slot_notes.py`: ein Test liest `suggestions` aus der Fixture und prüft `slot_notes.suggestions` dagegen (Muster: die vorhandenen Fixture-Tests der Datei).
- [ ] **Step 3:** `pwa/test/notes.test.js`: dieselben Blöcke der Fixture (`clean`, `check`, `group_key`, `suggestions` — die Schlüssel stehen in der Datei) gegen `notes.js`; zusätzlich: 200 Emoji gültig, 201 ungültig; `cleanNote(5) === ''`.
- [ ] **Step 4:** Tests rot sehen (`cd pwa && node --test test/notes.test.js`), `notes.js` schreiben, grün; `./notes.js` in `PRECACHE`.
- [ ] **Step 5:** `pytest tests/test_slot_notes.py -q`, `cd pwa && node --test`. Commit `feat(pwa): Regeln der Notiz am Slot als notes.js (Refs #519)`.

---

### Task 2: Lesen, Speichern und Senden der Notiz

**Files:** Modify `pwa/sync.js`, `pwa/minutes.js`, `pwa/store.js`, `pwa/test/sync.test.js`, `pwa/test/store.test.js`, `pwa/test/compat.test.js`, `pwa/test/fixtures/sync-request.json`, `tests/test_mobile_contract.py`. Create `pwa/test/fixtures/compat/sync-request-pre-notes.json`.

**Interfaces (Produces):**
- `parseSyncResponse(raw).slot_notes: boolean`; Slots in `entries` und in Konflikt-`versions` tragen `notiz` (string, über `cleanNote`), wenn die Antwort `slot_notes: true` nennt, sonst nicht.
- `normalizeSlots` behält `notiz` (string; sonst entfällt der Schlüssel).
- Meta `slot_notes: boolean` (Standard `false`), gesetzt aus jeder angewandten Antwort.
- Datensatz eines Tages: zusätzlich `notes_known: boolean` (fehlt = `false`).
- `Store.saveDay(date, slots, { notesKnown = false } = {})`: `notes_known` des Datensatzes = `notesKnown || bisheriger Wert`.
- `signature(slots)` schließt `notiz ?? ''` ein.
- `snapshotDirty`: je Tag, wenn `meta.slot_notes && record.notes_known`: jeder Slot mit `notiz` (fehlend → `''`); sonst jeder Slot **ohne** `notiz`.
- `applyResponse`: übernommene Tage bekommen `notes_known = parsed.slot_notes`.

- [ ] **Step 1 (Vertrag zuerst):** `sync-request.json` unverändert nach `compat/sync-request-pre-notes.json` kopieren (Regel 4 in `pwa/CLAUDE.md`: vor der Änderung einfrieren). Dann im Live-Beispiel an allen Slots **eines** Tages `notiz` setzen (eine Notiz, sonst `""`); die übrigen Tage bleiben ohne.
- [ ] **Step 2:** `tests/test_mobile_contract.py`: der Desktop nimmt das Live-Beispiel an und speichert die Notiz (Muster der vorhandenen Tests mit `sync-request.json`); das eingefrorene ebenso, ohne Notiz-Schlüssel im gespeicherten Tag. `pwa/test/compat.test.js`: das eingefrorene Beispiel bleibt das, was die PWA ohne `slot_notes` sendet.
- [ ] **Step 3: Tests (`store.test.js`, `sync.test.js`), rot sehen:**
  - Antwort mit `slot_notes: true` und Notiz → Slot im Speicher trägt `notiz`, Datensatz `notes_known`; Antwort ohne `slot_notes` → kein `notiz`, `notes_known` falsch.
  - Review Focus 1: Tag vor `slot_notes` lokal geändert (dirty), dann Antwort mit `slot_notes` (Tag nicht gesendet oder geändert) → nächster `snapshotDirty` ohne `notiz` an diesem Tag.
  - Review Focus 2: bekannter Tag mit Notiz an Slot 08:00, Pause geändert über `saveDay` ohne `notiz` an den Slots aber mit `notesKnown` aus dem Datensatz → Anfrage trägt die Notiz an 08:00 — **dafür** übergibt der Aufrufer die Slots mit `notiz` (Task 3); hier: `saveDay` mit Slots inkl. `notiz` → `snapshotDirty` trägt sie, `""` an den übrigen.
  - Review Focus 3: nur `notiz` geändert → Tag wird dirty.
  - Gemischt nie: jeder gesendete Tag hat `notiz` an allen oder an keinem Slot (über mehrere Tage prüfen).
  - Ohne `slot_notes`: `snapshotDirty` gleich wie vorher (Vergleich mit dem eingefrorenen Beispiel, Muster der vorhandenen `sync.test.js`-Tests zu `sync-request.json`).
  - Konflikt-Versionen tragen `notiz`, wenn `slot_notes`.
- [ ] **Step 4:** Umsetzen. `parseEntry`/`cleanSlots` bekommen das Flag; unbrauchbare `notiz` → `cleanNote`.
- [ ] **Step 5:** `cd pwa && node --test`, `pytest tests/test_mobile_contract.py tests/test_mobile_sync.py -q`, `npm run typecheck` in `pwa/` (Node ≥ 22: `export PATH=$HOME/.nvm/versions/node/v22.23.4/bin:$PATH`; `store.js`, `sync.js`, `view-model.js` tragen `// @ts-check`). Commit `feat(pwa): Notiz am Slot lesen, speichern und senden (Refs #519)`.

---

### Task 3: Notizfeld im Tages-Editor

**Files:** Modify `pwa/view-model.js`, `pwa/views.js`, `pwa/app.js`, `pwa/app.css`, `pwa/test/view-model.test.js`, `pwa/test/layout.test.js`, `pwa/test/contrast.test.js`.

**Interfaces:**
- `editorRows(...)`: jede Zeile trägt `notiz` (`slot.notiz ?? ''`); `nextRow`, `freshRow`, `suggestedRow`: `notiz: ''`.
- `rowsToSlots(rows, { notes = false } = {})`: mit `notes` trägt jeder Slot `notiz` (getrimmt über `checkNote`), sonst keiner. Eine Zeile, die nur eine Notiz trägt, ist nicht leer (`isBlank` prüft auch `notiz`) und fällt der Prüfung auf (Start/Ende fehlen).
- `validateRows(rows, { notes = false } = {})`: zusätzlich `checkNote` je Zeile; Feldfehler über `rowProblems(row, { notes })` → `problems.notiz`.
- `editorDialog(..., { notes: { suggest: (kategorie) => string[] } | null })`: `null` = kein Feld.
- `app.js`: `notes` nur mit `meta.slot_notes`; `suggest` über `noteSuggestions(Store-Tage, kategorie)`; `save` ruft `saveDay(date, rowsToSlots(rows, { notes: true }), { notesKnown })` mit `notesKnown = record.notes_known || rows.some(r => r.notiz.trim())`.

**Das Feld** (Spec „Handy-PWA“, Mockup im Canvas „PWA Notiz am Slot“): unter Pause/Kategorie `label` „Notiz“, dann ein Rahmen `.combo` mit `<input type="text" placeholder="optional" maxlength` nicht gesetzt (die Prüfung meldet), `autocomplete="off"`, `role="combobox"`, `aria-expanded`, `aria-controls`) und rechts ein Knopf ▾ (`aria-label` „Bisherige Notizen zeigen“). Die Liste (`role="listbox"`, Einträge als Knöpfe) liegt im Fluss **unter** dem Feld (kein schwebendes Popup: im `<dialog>` und auf iOS verlässlicher), höchstens ~5 Einträge hoch, scrollt in sich; Gruppenkopf „Weitere Notizen“ vor den Einträgen anderer Kategorien (die Kopfzeile mit dem Kategorienamen entfällt, wenn es keine eigenen gibt). Auf: ▾ oder Eingabe (dann gefiltert nach `groupKey`-Teilstring). Zu: Auswahl, ▾, Escape (ohne den Dialog zu schließen), Fokus verlässt Feld und Liste. Ohne Vorschläge zeigt ▾ nichts an und ist ausgegraut. Die Zeile wird beim Öffnen/Schließen nicht neu gebaut (Fokus).

- [ ] **Step 1: Tests (`view-model.test.js`):** `editorRows` übernimmt `notiz`; `rowsToSlots` mit/ohne `notes`; Zeile nur mit Notiz ist nicht leer; `validateRows` meldet 201 Zeichen und Zeilenumbruch, Feldfehler `notiz`; Filterfunktion der Liste (falls DOM-frei herausgezogen, z. B. `filterSuggestions(list, text)`).
- [ ] **Step 2:** `layout.test.js`: `.combo`-Regeln vorhanden, die Liste hat `max-height` und `overflow-y: auto`, kein festes `width` in px; `contrast.test.js`: Liste und Gruppenkopf auf ihrer Fläche.
- [ ] **Step 3:** Umsetzen, rot → grün; ganze PWA-Suite.
- [ ] **Step 4: Browser-Prüfung** gegen `python scripts/pwa_devserver.py` (Hinweise in `pwa/CLAUDE.md` „Entwickeln und prüfen“ und Memory „PWA-Browsertests“): 280/320/390 px und Querformat; Feld zu/auf, Filter, Auswahl, Speichern und Abgleich mit dem Dev-Desktop (Notiz kommt dort an), Review Focus 4 und 5. Screenshots unter `.playwright-mcp/`, nicht ins Repo committen.
- [ ] **Step 5:** Commit `feat(pwa): Notizfeld mit aufklappbaren Vorschlägen im Tages-Editor (Refs #519)`.

---

### Task 4: Anzeige in Woche und Konflikten, Einstellung

**Files:** Modify `pwa/view-model.js`, `pwa/views.js`, `pwa/app.js`, `pwa/app.css`, `pwa/store.js` (Meta-Standard), Tests dazu.

**Interfaces:**
- Meta `note_display`: `'line'` (Vorgabe) | `'inline'`; Unbekanntes gilt als `'line'` (`normalizeNoteDisplay`).
- `weekModel`: `day.slots` wird eine Liste von `{ text, note }` (`note` leer ohne Notiz); bei `'inline'` steht die Notiz in `text` (`… · Montage · Kunde Mustermann`) und `note` ist leer. Reservierungen unverändert (Text).
- Konfliktversionen: `{ text, note }` wie `'line'`.
- `dayRow`/`conflictsDialog`: die Notiz als eigenes `span.note` (grau, `--muted`, eine Zeile, `text-overflow: ellipsis`).
- Einstellungen › Verbindung: Abschnitt „Notizen“ (nur mit `meta.slot_notes`) unter „Zeiten verschieben“, `select` „In der Wochenliste“: „Eigene Zeile“ / „Hinter der Kategorie“; Muster `shiftSection` + `handlers.setShiftStep`.
- Das `aria-label` des Tages bleibt unverändert.

- [ ] Tests (`view-model.test.js`): beide Darstellungen, ohne Notiz identisch zu heute (Text gleich), Konflikt mit Notiz; `layout.test.js`: `.note` gekürzt; `contrast.test.js`: `.note` auf `--entry`, `--weekend`, `--cell`.
- [ ] Umsetzen, Browser-Blick auf Woche (beide Einstellungen) und Konfliktdialog bei 320 px.
- [ ] Commit `feat(pwa): Notiz in Wochenliste und Konflikten, Darstellung einstellbar (Refs #519)`.

---

### Task 5: Doku und Gesamtprüfung

**Files:** `pwa/CLAUDE.md` (Modulliste `notes.js`; Abschnitt zur Notiz: Feature-Erkennung, `notes_known`-Regel und warum, Feld, Einstellung; Regel 4 um `compat/sync-request-pre-notes.json` ergänzen und den Satz „die PWA liest es noch nicht“ ersetzen), `README.md` (Abschnitt Handy-Erfassung: ein Satz zur Notiz mit `*(ab --VERSION--)*`, falls die Desktop-Zeile ihn nicht schon abdeckt), `CLAUDE.md` (Eintrag `src/slot_notes.py`: „das Gegenstück der PWA liest später dieselbe Datei“ → Gegenwart, `pwa/notes.js`), `docs/known-limitations.md` (Abschnitt Notizen: ein unbekannter Tag, den der Nutzer mit einer Notiz speichert, sendet `""` an den übrigen Slots und kann dort eine Desktop-Notiz entfernen, die das Handy nie sah).

- [ ] Gesamtprüfung: `.venv/bin/python -m pytest -q`, `ruff check .`, pyright wie in Memory „Lokale Prüfwerkzeuge“, `cd pwa && node --test`, `npm run typecheck` (Node 22), `biome lint` auf sauberem Export.
- [ ] Commit `docs(pwa): Notiz am Slot beschreiben (Refs #519)`.
