# Pause an Reservierungen — PWA-Strang Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die PWA zeigt und sendet die Pause an Reservierungen, sobald der Desktop `reservation_pause` meldet, und rechnet „Noch ausstehend“ netto.

**Architecture:** `pause` ist ein Slot-Feld der Reservierung (Standard 0). Die Netto-Rechnung nutzt das vorhandene `slotMinutes` (zieht `slot.pause` ab). Das Eingabefeld und das Senden hängen am Meta-Flag `reservation_pause` (Feature-Erkennung, kein Versionsvergleich). Gespeicherte Pausen bleiben bei verlorenem Flag erhalten, werden aber nicht gesendet.

**Tech Stack:** Reines JavaScript ohne Build, `node --test` in `pwa/`.

**Spec:** `docs/superpowers/specs/2026-11-05-reservierung-pause-design.md` (Issue #455). **Voraussetzung:** der Desktop-Strang (`2026-11-05-reservierung-pause-desktop.md`) ist umgesetzt. Dieser Strang lebt auf dem Branch `feat/reservierung-pause-pwa`, abgezweigt von der Spitze von `feat/reservierung-pause` (der Dev-Server und der Ende-zu-Ende-Test nutzen die echte Handy-Instanz des neuen Desktops). Zum Ausrollen wird er nach der **Veröffentlichung** von 1.27.0 mit `git rebase --onto master feat/reservierung-pause feat/reservierung-pause-pwa` zu einem reinen PWA-PR gegen `master`; vorher darf er nie nach `master` (Pages deployt sofort).

## Global Constraints

- `PROTOCOL` bleibt **2**; Fähigkeit ist das Top-Level-Feld `reservation_pause: true` der Abgleich-Antwort (Meta-Flag `reservation_pause`).
- Ohne Flag: kein Pausenfeld, keine Pause in der Anfrage, Verhalten wie vor der Änderung.
- Pause: ganze Minuten, ≥ 0, kleiner als die Spanne (`validateSlots`), Eingabe rastet auf 5 Minuten (`snapPause`, `step` 5).
- Fehlt das Flag später (Reservierungen am Desktop aus, Desktop zurückgestuft): gespeicherte Pausen bleiben, „Noch ausstehend“ rechnet netto weiter, gesendet wird keine Pause; lokale Daten werden nie gelöscht.
- Hinweis zum Kalender: „Der Google-Kalender-Termin zeigt die volle Zeitspanne, die Pause wird dort nicht abgezogen.“
- Eingefrorene `compat/*-pre-pause.json` (Desktop-Strang Task 0) werden **nie** mitgezogen; die PWA muss sie weiter verstehen. Die Live-Fixtures `sync-request.json`/`sync-response.json` ändert **nur** der Desktop-Strang; dieser Strang liest sie.
- **Vorbelegung:** eine neue Reservierungszeile bekommt mit Flag die Standardpause (wie eine Ist-Zeile, über `freshRow`); ohne Flag trägt der Slot **kein** `pause`. Der Ist-Vorschlag aus einer Reservierung mit `pause: 0` nimmt weiter die Standardpause (Bestandsschutz), mit `pause > 0` deren Wert.
- Bestehende Tests, die die alte Form festnageln, werden bewusst und einzeln umgeschrieben (`pwa/test/reservations.test.js`: normalize/Signatur; `pwa/test/store.test.js:~580` „snapshot … without a pause“ gilt nur noch ohne Flag), nie zu lockereren Assertions.
- Keine eigene PWA-Version, kein Bump. Jeder Task: Teilbranch `feat/reservierung-pause-pwa-<teil>`, PR mit Ziel `feat/reservierung-pause`, `Refs #455`.

## Review Focus

- Antwort ohne Flag (älterer Desktop, Fixture `compat/sync-response-pre-pause.json`): kein Feld, nichts gesendet, „Noch ausstehend“ unverändert (Task 2, 3).
- Flag verschwindet nach vorherigem Speichern einer Pause: Pause bleibt lokal, wird nicht gesendet, nichts geht verloren (Task 2).
- Pausenfeld leer oder Text → wie 0, kein `NaN` in „Noch ausstehend“ (Task 1, 3).
- Pause ≥ Spanne im Formular → Fehlermeldung am Tag statt Absturz oder stillem Verwerfen (Task 1, 3).
- Heute teilweise erledigte Reservierung (`openReservationSlots`) zählt nur offene Slots, netto (Task 1).
- Pause aus Fremddaten ≥ Spanne oder riesig → 0 Minuten, nie negativ, kein `NaN` (Task 1).
- Mehrfach-Abgleich neue PWA ↔ neuer Desktop: Pause bleibt über drei Abgleiche stabil, `dirtyCount` 0, kein erneutes Senden; Pausen-Änderung auf beiden Seiten konvergiert (Task 2b).
- Frozen-Antwort ohne Flag läuft durch `SyncClient.sync()` samt Folgeanfrage: die Anfrage trägt **kein** `pause` und die Ansicht blendet kein Feld ein — der Test wird rot, sobald jemand die Fähigkeits-Erkennung entfernt oder hart auf `true` setzt (Task 2).
- Neue Reservierungszeile ohne Flag bekommt nicht stillschweigend eine gespeicherte Standardpause (Task 3).

---

### Task 1: Modell und Rechnung (`pwa/reservations.js`)

**Files:** Modify `pwa/reservations.js`; Test `pwa/test/reservations.test.js`

**Interfaces:** Produces: `normalizeReservationSlots(raw)` liefert `{start, end, kategorie, pause}` (`pause`: ganze Zahl ≥ 0, sonst 0); `validateReservationSlots(slots)` prüft die Pause wie bei Ist-Zeiten (über `validateSlots`, kein Überschreiben mehr mit 0); `reservationSignature(slots)` zählt `pause` mit; `pendingReservationMinutes` rechnet `slotMinutes({start, end, pause})`.

- [ ] **Step 1: Failing tests** in `pwa/test/reservations.test.js` (die vorhandenen, die `pause` verwerfen lassen, werden umgeschrieben):
  - `normalizeReservationSlots` behält `pause: 30`, macht `'30'`, `-5`, `1.5`, `undefined` zu 0, verwirft `gcal_event_id` weiter.
  - `validateReservationSlots([{start:'08:00', end:'08:30', kategorie:'A', pause:30}])` → nicht ok, Meldung nennt „Pause (30 Min) muss kleiner als die Arbeitszeit“.
  - `reservationSignature` unterscheidet zwei Slots, die sich nur in `pause` unterscheiden.
  - `pendingReservationMinutes` für das Beispiel aus dem Anlass: Slots 08:00–15:30 p30, 08:00–15:30 p30, 08:00–14:30 p30 → **1200**; ohne `pause` an den Slots → 1290.
  - Heute: `openReservationSlots` + Netto: zwei Slots gleicher Kategorie, ein Ist-Slot erledigt den früheren → nur der andere zählt, netto.
  - Fremddaten: `pendingReservationMinutes` mit Pause ≥ Spanne (`end−start`) oder `pause: 1e9` → 0 für diesen Slot, Summe nie negativ und nie `NaN`.
- [ ] **Step 2:** `cd pwa && node --test test/reservations.test.js` → FAIL.
- [ ] **Step 3:** Implementieren; Kommentar „`pause` gibt es bei Reservierungen nicht“ (Z. 25–26) durch die neue Regel ersetzen.
- [ ] **Step 4:** PASS. **Step 5:** Commit `feat(pwa): Reservierungs-Slot mit Pause, Ausstehend netto (Refs #455)`.

### Task 2: Abgleich und Flag (`pwa/sync.js`, `pwa/store.js`)

**Files:** Modify `pwa/sync.js`, `pwa/store.js`; Test `pwa/test/sync.test.js`, `pwa/test/store.test.js`, `pwa/test/compat.test.js` (Fixtures nur lesen, s. Global Constraints)

**Interfaces:**
- `parseReservations(raw)` übernimmt `pause` (ganze Zahl ≥ 0, sonst 0) je Slot.
- Meta-Feld `reservation_pause: false` (Standard in der Meta-Vorlage, `store.js` Z. 44ff.), gesetzt beim Anwenden der Antwort neben `reservations_enabled` (Z. ~536) auf `parsed.reservation_pause === true`.
- `Store.snapshotReservations()` lässt `pause` an den Slots **weg**, solange `reservation_pause` falsch ist (sonst unverändert).

- [ ] **Step 1: Failing tests:**
  - `parseReservations` mit Slot `pause: 30` liefert 30, ohne Feld 0, mit `'x'` 0.
  - Anwenden einer Antwort mit `reservation_pause: true` setzt das Meta-Flag; ohne das Feld (Fixture `compat/sync-response-pre-pause.json`) bleibt es falsch.
  - `snapshotReservations` mit Flag: Slot enthält `pause`; ohne Flag: Slot hat **genau** `{start, end, kategorie}` (Test aus `store.test.js:580` bleibt für diesen Fall gültig).
  - Flag-Verlust: erst Antwort mit Flag, lokal Pause 30 gespeichert, dann Antwort ohne Flag → gespeicherter Slot behält `pause: 30`, `snapshotReservations` sendet sie nicht, `pendingReservationMinutes` rechnet netto.
  - Desktop-Antwort ersetzt den Slot samt Pause (`_applyReservations`): Pause vom Desktop geändert → lokal übernommen, solange der Tag nicht lokal geändert ist.
  - `compat.test.js`: `compat/sync-response-pre-pause.json` wird weiter verstanden (kein Wurf, Pause 0) **und** trägt Selbstschutz wie das Muster dort: `assert.ok(!('reservation_pause' in doc))`, Reservierungen nicht leer, kein Slot mit `pause`.
  - **Echte Parser-Kette statt handgebautem `parsed`** (`store.test.js` baut `parsedWith` von Hand, das bleibt für Altes; die neuen Tests gehen durch `parseSyncResponse`): `parseSyncResponse(fixture('sync-response.json')).reservation_pause === true`; `parseSyncResponse(fixture('compat/sync-response-pre-pause.json')).reservation_pause === false`; danach `store.applyResponse(parsed)` und `getMeta().reservation_pause` entsprechend; `parseSyncResponse(live).reservations[<Tag>].slots[0].pause === 30` (damit die Live-Fixture auch von der JS-Seite gelesen und gegen Drift festgenagelt ist; Python liest sie schon in `test_mobile_contract.py`).
  - **Übergangs-Test mit `SyncClient.sync()`** (Harness `fetchFn.calls` in `sync.test.js`, Muster „Abgleich über den Relay“): Fake-Desktop liefert die **eingefrorene Antwort ohne Flag**; `store.saveReservation(d, [{start, end, kategorie, pause: 30}])` (Pause von Hand eingeschleust), `client.sync()`, erneut `saveReservation` mit anderer Zeit, zweites `sync()`. Assert: in beiden Anfragen hat der Slot **genau** die Schlüssel `start`, `end`, `kategorie`; `getMeta().reservation_pause === false`; `pendingReservationMinutes` rechnet mit der gespeicherten Pause netto. Dieselbe Sequenz mit der Live-Antwort (Flag `true`): `calls[1]…slots[0].pause === 30`. Entfernt jemand die Erkennung, wird einer der beiden Fälle rot.
- [ ] **Step 2:** `node --test` → FAIL.
- [ ] **Step 3:** Implementieren; Kommentare in `store.js` (Z. 396 „ohne `pause`“) korrigieren.
- [ ] **Step 4:** `cd pwa && node --test` → PASS. **Step 5:** Commit `feat(pwa): Pause im Abgleich, Fähigkeit reservation_pause (Refs #455)`.

### Task 2b: Ende-zu-Ende-Zyklen neue PWA ↔ neuer Desktop

**Files:** Create `tests/test_mobile_reservation_pause_e2e.py`; Modify `tests/mobile_apply_probe.mjs` (Probe-Eingabe um Reservierungs-Schritte erweitern); Muster: `tests/test_mobile_window_e2e.py`.

**Interfaces:** Echtes `mobile_sync.perform_sync` mit echtem `ReservationStore` (tmp-Pfad) → echte Antwort → Probe (Node): `parseSyncResponse` + `Store.applyResponse` mit `memory-adapter` → Zustand zurück (Slots mit Pause, `dirtyCount`, `getMeta().reservation_pause`) → nächste Anfrage der PWA aus `snapshotReservations`.

- [ ] **Step 1: Failing tests** (Reservierungen und Flag an, je mehrere Abgleiche):
  - **Zyklus A (stabil):** Desktop-Slot `pause=30`, PWA hat ihn nach Abgleich 1; Abgleiche 2 und 3 ohne Änderung → Pause bleibt 30 in Desktop-Store **und** PWA-Store, `reservations_changed` ist `False`, `dirtyCount` 0, die Anfrage enthält die Reservierung nicht erneut.
  - **Zyklus B (PWA ändert):** PWA setzt Pause 45 → Abgleich → Desktop-Store 45, Antwort 45, PWA sauber.
  - **Zyklus C (Desktop ändert):** Desktop `save()` mit Pause 20 → nächster Abgleich holt 20 in die PWA.
  - **Zyklus D (Konflikt):** Änderung der Pause auf beiden Seiten; der neuere Stempel gewinnt, beide konvergieren, der unterlegene Wert ist weg (festgehalten, nicht gelöst).
  - **Zyklus E (Flag fehlt):** Antwort ohne `reservation_pause` nach vorherigem Speichern → Pause bleibt lokal, wird nicht gesendet.
- [ ] **Step 2:** `pytest tests/test_mobile_reservation_pause_e2e.py -v` → FAIL (vor Task 1–3) bzw. PASS. **Step 3:** Commit `test(reservierung): Ende-zu-Ende-Zyklen mit der echten Handy-Instanz (Refs #455)`.

### Task 3: Oberfläche (`pwa/view-model.js`, `pwa/views.js`, `pwa/app.css`)

**Files:** Modify `pwa/view-model.js`, `pwa/views.js`, `pwa/messages.js` (Text), Test `pwa/test/view-model.test.js`, `pwa/test/layout.test.js`

**Interfaces:**
- `reservationRows(...)`/`reservationRowsToSlots(rows)`/`validateReservationRows(rows)` führen `pause` (String im Formular, Zahl im Slot; leer → 0).
- `slotText(slot)` nennt die Pause wie bei Ist-Zeiten (`· 30 min Pause`) auch für Reservierungs-Slots mit `pause > 0` („geplant …“).
- `suggestedRow` (nicht exportiert; getestet über `editorRows(null, defaults, weekday, reservation)`) nimmt `slots[0].pause`, wenn sie `> 0` ist, sonst weiter die Standardpause (Bestandsschutz: ältere Reservierungen tragen 0).
- `reservationRows(reservation, defaults, weekday, { pauseEnabled })` nutzt `editorRows`, dessen `freshRow` heute die Standardpause in jede neue Zeile legt; `reservationRowsToSlots(rows, { pauseEnabled })` schreibt `pause` **nur** mit `pauseEnabled`, sonst bleibt der Slot bei `{start, end, kategorie}` (verhindert, dass jede neue Reservierung ohne Flag stillschweigend eine Pause speichert).
- `slotSection(...)` zeigt das Pausenfeld im Reiter „Reservierung“ nur mit `withPause` **und** Flag (neuer Parameter `pauseEnabled`), `step` 5 (`snapPause`); darunter die Hinweiszeile zum Kalendertermin (`RESERVATION_CALENDAR_NOTE`, Konstante in `messages.js`).

- [ ] **Step 1: Failing tests:** `slotText` mit/ohne Pause; Ist-Vorschlag (`editorRows` mit Reservierung): Reservierung `pause: 30` → Zeile 30, `pause: 0` oder fehlend → Standardpause; `reservationRowsToSlots(rows, {pauseEnabled: true})` macht `''` und `'0'` zu 0 und `'30'` zu 30, **ohne** `pauseEnabled` hat jeder Slot genau `{start, end, kategorie}`; neue Reservierungszeile: mit Flag Standardpause vorbelegt, ohne Flag wird nichts davon gespeichert; `validateReservationRows` lehnt Pause ≥ Spanne ab (Meldung wie `validateSlots`); `weekModel`: Beispiel-Woche (drei Reservierungstage wie in Task 1) → `pendingLabel` `20 h`-Format laut `formatMinutes` (`pendingMinutes === 1200`); `layout.test.js`: das neue Pausenfeld hat dieselben Breitenregeln wie das Ist-Pausenfeld (Quelltext-Test nach dem Muster der vorhandenen), und der Hinweis ist nur im Reservierungs-Reiter und nur mit Flag im Quelltext verdrahtet.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implementieren (nur `createElement`/Textknoten, kein `innerHTML`); ohne Flag bleibt der Reiter exakt wie bisher.
- [ ] **Step 4:** `cd pwa && node --test` → PASS. **Step 5:** Commit `feat(pwa): Pausenfeld an Reservierungen mit Hinweis zum Kalendertermin (Refs #455)`.

### Task 4: Doku und Prüfung im Dev-Setup

**Files:** Modify `pwa/CLAUDE.md`

- [ ] **Step 1:** `pwa/CLAUDE.md` aktualisieren: Modul `reservations.js` („ohne Pause“ → neue Regel), Abschnitt „Reservierungen“ (Form auf dem Draht mit `pause`, Feature-Flag `reservation_pause`, Netto-Rechnung, Kalendertermin brutto, Flag-Verlust), „Kompatibilität“ (eingefrorener Stand `compat/*-pre-pause.json` in der Aufzählung von Regel 4), Satz „der Desktop lehnt jedes weitere Feld am Slot ab“ streichen.
- [ ] **Step 2:** `cd pwa && node --test` → alles PASS; `pytest tests/test_mobile_contract.py` → PASS.
- [ ] **Step 3:** Handprüfung mit `python scripts/pwa_devserver.py --reservations` (Playwright laut `pwa/CLAUDE.md`, Layout 320–1024 px): Reservierung mit Pause anlegen, „Noch ausstehend“ zeigt netto, Pause bleibt nach Abgleich; mit einem Desktop-Stand ohne Flag (Server mit älterem Branch oder Fixture) erscheint kein Feld. Relay-Weg bleibt hier ungeprüft (Dev-Server kann ihn nicht), das Ergebnis im PR vermerken.
- [ ] **Step 4:** Commit `docs(pwa): Pause an Reservierungen (Refs #455)`. Der Strang geht nach `master`, sobald das Desktop-Release (1.27.0) **veröffentlicht** ist; kein `release:*`-Label nötig (die PWA hat keine eigene Version).
