# Pause an Reservierungen — Desktop-Strang Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Desktop nimmt, speichert, liefert und zeigt eine optionale Pause an Reservierungs-Slots und meldet dem Handy die Fähigkeit `reservation_pause`.

**Architecture:** `pause` ist ein additives Slot-Feld (Standard 0). Ein fehlendes `pause` in einer Anfrage wird nur bei gleichem Index **und** gleichem `start`/`end` vom alten Slot geerbt (`reservations.inherit_pause`). `PROTOCOL` bleibt 2. Der Google-Termin bleibt brutto und trägt die Pause nur als private Eigenschaft plus Hinweis in der Beschreibung.

**Tech Stack:** Python 3.12, Tkinter (nur Task 4), pytest, bestehende Stores und `gcal`-Wrapper.

**Spec:** `docs/superpowers/specs/2026-11-05-reservierung-pause-design.md` (Issue #455). Gegenstück: `2026-11-05-reservierung-pause-pwa.md` (erst **nach** dem Release dieses Strangs).

## Global Constraints

- `PROTOCOL` bleibt **2**; neue Fähigkeit heißt `reservation_pause` (Top-Level-Feld der Abgleich-Antwort, nur bei eingeschalteten Reservierungen).
- Pause: ganze Minuten, ≥ 0, kleiner als die Arbeitszeit (`validate_entry`); API-Fehler 422 `invalid_slot` bzw. `invalid_pause`.
- Fehlendes `pause` erbt nur bei gleichem Index **und** gleichem `start`/`end`, sonst 0. Ein vorhandenes `pause` (auch 0) wird übernommen.
- Last-Writer-Wins über den ganzen Tag (`_phone_key`), keine Feldlogik in `merge_phone`.
- Teilen (`share.py`), Berichte, Wochenlimit, Pausenpflicht, Erinnerungen, Relay bleiben **unverändert**.
- Kalendertermin: Zeit brutto, Titel unverändert; Beschreibung nennt bei Pause > 0 „Zeitspanne brutto, Pause N min nicht abgezogen“; `extendedProperties.private.pause` als String. Fehlende Eigenschaft = 0 und gilt als gleich einer lokalen 0 (kein Massen-Update).
- Release 1.27.0 (Minor); README-Zeilen mit `*(ab --VERSION--)*`; `src/CLAUDE.md` im selben PR pflegen.
- Jeder Task: eigener Teilbranch `feat/reservierung-pause-<teil>`, PR mit Ziel `feat/reservierung-pause`, `Refs #455`.
- **Branch-Struktur:** `feat/reservierung-pause` trägt **nur** diesen Desktop-Strang und geht als Release-PR nach `master`. Der PWA-Strang entsteht auf einem zweiten Branch `feat/reservierung-pause-pwa`, der von der Spitze dieses Branches abzweigt (der Dev-Server braucht den neuen Desktop). Nach dem Release wird er mit `git rebase --onto master feat/reservierung-pause feat/reservierung-pause-pwa` zu einem reinen PWA-PR gegen `master`. Ein Merge von `feat/reservierung-pause-pwa` nach `master` **vor** der Veröffentlichung von 1.27.0 ist verboten (Pages deployt sofort).
- **Live-Fixtures** (`pwa/test/fixtures/sync-request.json`, `sync-response.json`) ändert **ausschließlich** dieser Strang (Task 2); der PWA-Strang liest sie nur. Sonst bleibt `rebuilt == example["reservations"]` (`tests/test_mobile_contract.py`) im falschen Strang rot.
- **Vorbelegung:** eine neue Reservierungszeile mit Pausenfeld bekommt die Standardpause (Kategorie, sonst global) wie eine Ist-Zeile (meine Entscheidung; sonst müsste der Nutzer sie jedes Mal tippen).
- **Gleichstand im LWW** (`_phone_key`): `pause` zählt über `normalize_pause` mit, ein Alt-Slot ohne Schlüssel zählt als 0. Bei exakt gleichem Stempel entscheidet weiter die JSON-Ordnung des Inhalts; das wird nicht gelöst, sondern in einem Test festgehalten.
- **Bestehende Tests, die die alte Form festnageln, werden bewusst und einzeln umgeschrieben (Liste in Task 1–3, 5); keine Assertion wird zu `in` oder `>=` gelockert.** Ein Plan-Eintrag oder Slot ohne `pause`-Schlüssel bei `pause == 0` bleibt bitgleich zu heute, wo das ohne Informationsverlust geht (Kalender-Plan, Task 5).

## Review Focus

- Alte PWA sendet einen Slot ohne `pause` → die am Desktop gesetzte Pause bleibt (Task 1, 2).
- Slot wird mitten in der Liste eingefügt oder entfernt → kein Slot erbt eine fremde Pause (Task 1).
- Von außen gesetzte Pause, die nicht in `PAUSE_VALUES` liegt (37) → bleibt im Dialog sichtbar und übersteht das Speichern (Task 4).
- Kalendertermin aus der Zeit vor dem Release (ohne `pause`-Eigenschaft) bei lokaler Pause 0 → kein Update (Task 5).
- Ungültige Pause (negativ, `true`, `30.0`, `"30"`, ≥ Spanne) → 422, kein Absturz, Store unverändert (Task 2, 3).
- Mehrfach-Abgleich einer alten Handy-Version (Antwort auf drei Felder projiziert, zurückgeschickt) gegen den neuen Desktop → Pause bleibt, zweiter unveränderter Abgleich ist ein No-op ohne Kalender-Update (Task 2b).
- Teil-Löschen eines Reservierungs-Slots am Desktop (`ui.py` speichert `res_keep` aus `get_all()` zurück) → die übrigen Slots behalten ihre Pause (Task 1).
- Share-Import überschreibt eine am Desktop gesetzte Pause mit 0 und der Export leakt kein `pause` ins Share-Doc (Task 3) — bewusst, aber festgehalten und im CHANGELOG genannt.
- Kalender: nach dem Update eines Termins löst der zweite Lauf **kein** weiteres Update aus; Pause 30 → 0 erzeugt keinen Dauer-Diff (Task 5).

---

### Task 0: Vertrags-Fixtures einfrieren

**Files:**
- Create: `pwa/test/fixtures/compat/sync-request-pre-pause.json`, `pwa/test/fixtures/compat/sync-response-pre-pause.json`
- Modify: `tests/test_mobile_contract.py`

**Interfaces:** Produces: die beiden Dateien als byte-genaue Kopien von `pwa/test/fixtures/sync-request.json` und `sync-response.json` **vor** jeder Vertragsänderung. Spätere Tasks ändern nur die Live-Fixtures.

- [ ] **Step 1:** Die beiden Live-Fixtures nach `compat/…-pre-pause.json` kopieren (`cp`), vor jeder anderen Änderung.
- [ ] **Step 2:** Test `test_pre_pause_request_still_accepted` nach dem Muster der vorhandenen `pre-reservations`-Tests: `parse_request(pre_pause_request, …)` wirft nicht, jeder Reservierungs-Slot hat danach **kein** `pause`-Schlüssel (fehlt = „nicht angegeben“; wird in Task 2 relevant). **Selbstschutz gegen leere Tests** (wie das vorhandene `assert.ok(!('reservations' in doc))` der JS-Seite): vor der Schleife `assert parsed.reservations` (nicht leer), und ein Test `test_pre_pause_fixtures_are_really_pre_pause` prüft in beiden eingefrorenen Dateien, dass kein Slot `pause` trägt und die Antwort **kein** `reservation_pause` führt, bei nicht leeren Reservierungen.
- [ ] **Step 3:** `pytest tests/test_mobile_contract.py -v` → PASS (Zustand heute: Slots tragen nur drei Felder).
- [ ] **Step 4:** Commit `test(reservierung): Vertragsstand vor der Pause einfrieren (Refs #455)`.

### Task 1: Datenmodell und Erben (`src/reservations.py`)

**Files:** Modify `src/reservations.py`; Test `tests/test_reservations.py`

**Interfaces:**
- Produces: `normalize_pause(value: Any) -> int` (int in [0, 1440], alles andere inkl. `bool`/`float`/`str` → 0); `inherit_pause(old_slots: list[Slot], new_slots: list[dict[str, Any]]) -> list[dict[str, Any]]` (setzt `pause` an jedem neuen Slot **ohne** `pause`-Schlüssel auf `old_slots[i]["pause"]`, wenn `i` existiert und `start`/`end` gleich sind, sonst 0; Slots mit `pause`-Schlüssel bleiben unverändert).
- Slot-Form des Stores: `{start, end, kategorie, gcal_event_id, send_reminder_minutes, pause}`; `get_all()` liefert `pause` in der User-Shape.

- [ ] **Step 1: Failing tests** in `tests/test_reservations.py`:
  - `test_slot_defaults_pause_to_zero`: gespeicherter Alt-Slot ohne `pause` liest als `pause == 0`.
  - `test_save_keeps_pause_and_get_all_returns_it`: `save("2026-12-01", [{"start":"08:00","end":"15:30","kategorie":"A","pause":30}])` → `get_all()` Slot hat `pause == 30`.
  - `test_normalize_pause_rejects_bad_values`: `normalize_pause(True)`, `(30.0)`, `("30")`, `(-1)`, `(1441)` → 0; `(30)` → 30.
  - `test_inherit_pause_same_index_same_times` / `test_inherit_pause_not_for_inserted_slot` (vorher `[A 08–12 p30]`, neu `[B 06–07, A 08–12]` ohne pause → beide 0) / `test_inherit_keeps_explicit_zero` (`pause: 0` im neuen Slot bleibt 0, auch wenn alt 30).
  - `test_merge_phone_inherits_pause_when_absent` (alter Slot pause 30, Handy-Tag mit neuerem Stempel, Slot ohne `pause`-Schlüssel → danach 30) und `test_merge_phone_takes_explicit_pause`.
  - `_phone_key`/LWW (drei Tests, Stempel jeweils gleich): **A** `test_phone_key_old_slot_without_key_equals_zero`: Store-Datei von Hand **ohne** `pause`-Schlüssel (Alt-Format über `_migrate_legacy_reservations`-Pfad), Handy sendet denselben Tag mit `pause: 0` → `merge_phone` liefert `False`, Datei-mtime und Inhalt unverändert (kein Dauer-Diff `None` ↔ `0`). **B** Handy `pause: 45` gegen Store `30` → `True`, danach 45. **C** Handy `pause: 0` gegen Store `30` → das Ergebnis wird als Assertion festgehalten (nach der JSON-Ordnung gewinnt die größere Pause, hier also der Store; Kommentar im Test nennt das als bekannte Eigenheit bei Gleichstand).
  - `test_inherit_pause_cases` (parametrisiert, `inherit_pause` direkt): gleicher Index+Zeiten → erbt; nur `kategorie` geändert, Zeiten gleich → erbt; nur `end` geändert → 0 (Pause geht verloren, gewollt); zwei Slots vertauscht → beide 0; erster Slot entfernt → Folgeslot erbt nichts; Index jenseits von `old_slots` → 0; alter Slot ohne `pause`-Schlüssel → 0; explizites `pause: 0` bleibt 0.
  - `test_partial_delete_keeps_other_slots_pause`: der Teil-Lösch-Pfad aus `ui.py` (`_delete_action(res_slots, selected, "reservation")` liefert `res_keep`, `save(date, res_keep)`) als reiner Test ohne Tk: zwei Slots (Pause 30 und 45), einer wird gelöscht → der andere hat danach noch seine Pause (setzt voraus, dass `_user_shape` `pause` liefert).
- [ ] **Step 2:** `pytest tests/test_reservations.py -v` → FAIL (`normalize_pause` fehlt).
- [ ] **Step 3:** Implementieren: `normalize_pause`, `inherit_pause`; `pause` in `_normalize_slot`, in der Migration alter Einträge, in `_user_shape`, in `_phone_key` (zählt mit); `merge_phone` ruft `inherit_pause(old_slots, incoming["slots"])` **vor** dem `_phone_key`-Vergleich; Docstring/Kommentar der Slot-Form (Zeile 9 und 29–35) nachziehen.
- [ ] **Step 4:** `pytest tests/test_reservations.py -v` → PASS.
- [ ] **Step 5:** Commit `feat(reservierung): Pause im Reservierungs-Slot, Erben nur bei gleichem Slot (Refs #455)`.

### Task 2: Handy-Abgleich (`mobile_reservations.py`, `mobile_sync.py`)

**Files:** Modify `src/mobile_reservations.py`, `src/mobile_sync.py`, `pwa/test/fixtures/sync-request.json`, `pwa/test/fixtures/sync-response.json`; Test `tests/test_mobile_reservations.py`, `tests/test_mobile_contract.py`

**Interfaces:**
- Consumes: `reservations.normalize_pause`, `inherit_pause` (Task 1).
- Produces: `parse_reservations` liefert Slots `{start, end, kategorie}` **plus `pause` nur, wenn die Anfrage es nannte**; `build_reservations` liefert **immer** `pause: int`; die Antwort trägt `reservation_pause: true`, wenn `reservations` in ihr steht.

- [ ] **Step 1: Failing tests:**
  - Der bestehende Test, der `{**SLOT, "pause": 30}` auf drei Felder kürzt (`tests/test_mobile_reservations.py:30-33`), wird zu `test_parse_keeps_pause_when_given` (Ergebnis-Slot enthält `pause == 30`) geändert; neu `test_parse_leaves_pause_absent_when_not_given` (kein Schlüssel).
  - `test_parse_rejects_bad_pause`: `pause` = `-1`, `True`, `30.0`, `"30"`, ≥ Spanne (Slot 08:00–08:30, Pause 30) → `ReservationError` mit Text `Reservierung <Datum>: …`.
  - `test_build_always_returns_pause`: Store-Slot ohne `pause` → Antwort-Slot `pause == 0`.
  - Vertragstest: Antwort aus `perform_sync` mit Reservierungen enthält `reservation_pause is True`; ohne eingeschaltete Reservierungen fehlt das Feld.
  - `test_old_pwa_request_keeps_desktop_pause`: Store hat Slot pause 30; Anfrage nach `compat/sync-request-pre-pause.json`-Form mit gleichem Slot (neuerer Stempel) → danach `pause == 30`.
  - **Bestehende Tests, die bewusst umgeschrieben werden** (Soll jeweils exakt, nicht gelockert): `tests/test_mobile_reservations.py` `test_a_valid_day_is_parsed_to_the_three_phone_fields` (heißt danach `…_to_the_phone_fields`, Ergebnis enthält `pause` nur bei Angabe); `tests/test_mobile_contract.py` (Reservierungs-Roundtrip gegen die neuen Live-Fixtures, `rebuilt == example["reservations"]` bleibt strikt).
- [ ] **Step 2:** `pytest tests/test_mobile_reservations.py tests/test_mobile_contract.py -v` → FAIL.
- [ ] **Step 3:** `_parse_day`: Slots aus `parse_slots(slots_raw)` übernehmen, `pause` nur bei `"pause" in raw_item` (positionsweise Zuordnung zu `slots_raw`); `_clean_slots` mit `normalize_pause`; `mobile_sync` setzt `reservation_pause` neben `reservations` (Stelle der Antwort mit dem Feld `reservations`); Docstrings („pause gibt es nicht“, `mobile_reservations.py:10-11`) korrigieren. Live-Fixtures um `pause` an einem Slot und `reservation_pause: true` ergänzen.
- [ ] **Step 4:** Tests PASS; zusätzlich `pytest tests/test_mobile_contract.py -v` mit den eingefrorenen Fixtures grün.
- [ ] **Step 5:** Commit `feat(reservierung): Pause im Handy-Abgleich, Fähigkeit reservation_pause (Refs #455)`.

### Task 2b: Übergangs-Test alte Handy-Version gegen neuen Desktop (Zyklen)

**Files:** Create `tests/test_mobile_reservation_pause_transition.py`; nutzt `tests/mobile_phone.py` (Handy-Simulation auf Python-Seite) und die Muster aus `tests/test_mobile_window_e2e.py`.

**Interfaces:** Consumes den echten `mobile_sync.perform_sync` mit echtem `ReservationStore` (tmp-Pfad) und `build_response`. Das „alte Handy“ ist eine Hilfsklasse im Test, die **wie die alte PWA** arbeitet: sie projiziert jede Antwort-Reservierung auf `{start, end, kategorie}` (so macht es `parseReservations` der alten PWA, `pwa/sync.js`) und schickt nur diese drei Felder zurück.

- [ ] **Step 1: Failing tests** (jeweils mehrere Abgleiche hintereinander):
  - `test_old_phone_three_syncs_keep_desktop_pause`: Desktop-Slot `pause=30`; altes Handy gleicht dreimal ab, ohne etwas zu ändern → Pause bleibt 30 im Store **und** in jeder Antwort, `reservations_changed` ist ab dem zweiten Abgleich `False`, es entsteht keine Kalender-Änderung (`on_reservations_change` wird nicht gerufen).
  - `test_old_phone_edit_category_keeps_pause_edit_time_loses_it`: das alte Handy ändert nur die Kategorie → Pause bleibt; ändert es das Ende → Pause ist 0 (dokumentiertes Verhalten, im CHANGELOG genannt).
  - `test_old_phone_new_day_gets_zero_pause`: neuer Tag ohne `pause` → 0, danach stabil.
  - `test_new_desktop_response_carries_flag_and_pause`: die Antwort trägt `reservation_pause is True` und je Slot `pause`; das alte Handy ignoriert beides ohne Fehler (Projektion).
- [ ] **Step 2:** `pytest tests/test_mobile_reservation_pause_transition.py -v` → FAIL (vor Task 1/2) bzw. PASS (danach). **Step 3:** Commit `test(reservierung): Übergang alte Handy-Version gegen neuen Desktop (Refs #455)`.

### Task 3: Lokale API (`api_reservation_write.py`, `api_routes.py`)

**Files:** Modify `src/api_reservation_write.py`, `src/api_routes.py`; Test `tests/test_api_reservation_write.py`, `tests/test_api_reservations.py`

**Interfaces:** Consumes `reservations.inherit_pause`. Produces: Body-Slot darf `pause` tragen (optional); GET und PUT-Antwort liefern `pause` je Slot (immer); PUT ohne `pause` im Slot erbt nach `inherit_pause`. README-Abschnitt „Reservierungen“ passend ändern.

- [ ] **Step 1: Failing tests:** die zwei Tests, die `pause` mit 422 erwarten (`test_api_reservation_write.py:31`, `:71-72`), werden zu `…accepts_pause` (Ergebnis-Slot hat `pause == 30`) und `…rejects_bad_pause` (`-1`, `true`, `30.0` → 422 `invalid_pause`; Pause ≥ Spanne → 422 `invalid_slots`); neu: `test_put_without_pause_inherits_for_unchanged_slot` und `test_put_with_inserted_slot_inherits_nothing`; `test_get_returns_pause`; `test_put_unchanged_body_with_same_pause_is_not_a_change` (`changed` bleibt False).
  - Bewusst umzuschreibende Bestandstests: `tests/test_api_reservation_write.py` (Pause-422-Tests, bei Z. ~31 und ~66–72) **und** `tests/test_api_reservations.py` (Test mit `{"pause": 5}` → 422, bei Z. ~271) werden zu den neuen Annahme-/Ablehnungs-Tests.
  - Share (`tests/test_share.py`, neu, ohne bestehende Tests anzufassen): `test_export_does_not_leak_pause` (Store-Slot mit Pause → Share-Doc-Slot hat genau `{start, end, kategorie}`, validiert gegen `share.py` v3) und `test_import_overwrites_desktop_pause_with_zero` (festgehalten, Kommentar verweist auf Design „Teilen bleibt ohne Pause“).
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** `parse_reservation_body` (Z. ~66–68 entfernen, `pause` an Slots ohne Standard durchreichen, Docstring Z. 8 ändern); `_wire_reservation_slots` um `pause`; `_put_reservation` ruft `inherit_pause` vor dem Vergleich `existing_slots != slots`.
- [ ] **Step 4:** PASS. **Step 5:** Commit `feat(api): Pause an Reservierungen (Refs #455)`.

### Task 4: Dialog und Tooltip

**Files:** Modify `src/dialogs/entry_dialog.py`, `src/dialogs/slot_rows.py`, `src/grid_renderer.py`, `src/time_utils.py` (nur falls nötig); Test `tests/test_entry_dialog.py`, `tests/test_grid_renderer.py`

**Interfaces:** `plan_entry_save(ist_slots, res_slots, show_reservation)` validiert Reservierungen mit `with_pause=True`; `GridRenderer._fmt_slot_line(slot)` hängt `  · N min Pause` an, wenn `slot.get("pause", 0) > 0`; Hinweiszeile `RESERVATION_CALENDAR_NOTE = "Der Google-Kalender-Termin zeigt die volle Zeitspanne, die Pause wird dort nicht abgezogen."` (Konstante in `entry_dialog.py`), nur sichtbar bei aktivem Kalender-Abgleich (`gcal_enabled`).

- [ ] **Step 1: Failing tests:** `plan_entry_save` lehnt Reservierungs-Slot mit Pause ≥ Spanne ab und lässt Pause 30 bei 08:00–15:30 zu; `save_all`-Ergebnis (`res_slots`) enthält `pause`; `test_free_pause_value_roundtrips` (Reservierung mit `pause: 37` → Zeile zeigt 37, Speichern liefert 37, nicht 35/40); `slot_rows.pause_choices(current: int, values: Sequence[int]) -> list[int]` (neu, Tk-frei, Auswahl der Pause-Combobox: `values` plus `current`, falls dort nicht enthalten, aufsteigend) mit Test: `pause_choices(37, PAUSE_VALUES)` enthält 37 und die Standardwerte, `pause_choices(30, PAUSE_VALUES)` ändert nichts; eine neue Reservierungszeile ist mit `default_pause` vorbelegt (Konstruktor-Argument ist schon `default_pause`, `entry_dialog.py` Z. ~309); `_fmt_slot_line({"start":"08:00","end":"15:30","kategorie":"A","pause":30})` enthält `30 min Pause`, ohne Pause bleibt die Zeile wie bisher; Ist-Vorbelegung aus einer Reservierung mit `pause: 30` nimmt 30 statt `default_pause`; `slot_category_display` markiert eine abweichende Reservierungs-Pause **nicht** mit `*` (`pause=None` dort bleibt).
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Reservierungs-`SlotRowList` mit `with_pause=True` (Z. 301–322), `save_all` (`res_slots` um `pause`), `plan_entry_save` (Z. 71), Vorbelegung (Z. 274–280), Tooltip-Zeile, Hinweis. Freier Wert: dieselbe Behandlung wie die Ist-Zeit-Pause-Combobox.
- [ ] **Step 4:** `pytest tests/test_entry_dialog.py tests/test_grid_renderer.py tests/test_pixel_scaling.py -v` → PASS. **Step 5:** Commit `feat(reservierung): Pause im Tages-Dialog und Tooltip (Refs #455)`.

### Task 5: Google-Kalender

**Files:** Modify `src/gcal.py`, `src/reservations_sync.py`; Test `tests/test_gcal.py`, `tests/test_reservations_sync.py`

**Interfaces:**
- `gcal.event_payload(date_str, start, end, kategorie, modified_at, pause=0)`, `gcal.create_event(service, calendar_id, date_str, start, end, kategorie, modified_at, pause=0)`, `gcal.update_event(service, calendar_id, event_id, date_str, start, end, kategorie, modified_at, pause=0)`.
- `gcal.parse_event` liefert zusätzlich `pause: int` (fehlend/ungültig → 0).
- `reservations_sync`: `_slot_from_event(ev, reminder_minutes=None, pause=None)` (`pause=None` → `ev["pause"]`); Plan-Einträge für `create`/`update` tragen `pause`.

- [ ] **Step 1: Failing tests:** `event_payload(..., pause=30)` → `description` enthält „Zeitspanne brutto, Pause 30 min nicht abgezogen“ und `extendedProperties.private["pause"] == "30"`; mit `pause=0` bleibt `description == EVENT_DESCRIPTION` und die Eigenschaft fehlt; Titel unverändert; `parse_event` ohne Eigenschaft → `pause == 0`; Reconcile: lokaler Slot pause 30 + Termin ohne Eigenschaft → `plan["update"]` enthält ihn (einmaliges Nachziehen); lokaler Slot pause 0 + Termin ohne Eigenschaft → **kein** Update; Pause-Änderung allein löst Update aus; `_adopt_remote` (Remote gewinnt) übernimmt `pause` aus dem Termin, fällt bei fehlender Eigenschaft auf die lokale Pause über `event_id` zurück, neuer Remote-Termin ohne lokalen Slot → 0; `reconcile_reservations` reicht `pause` an `gcal.create_event`/`update_event` (Mock prüft Argument).
  - **Folgelauf und Erhalt** (Fake-Kalender-Service, der den Event-Body speichert und `update`-Aufrufe zählt): `test_second_run_after_update_is_quiet` (Slot pause 30, Termin ohne Eigenschaft → Lauf 1: ein `update`, Termin trägt jetzt `private.pause == "30"`; Lauf 2: **null** weitere `update`); `test_pause_30_to_0_no_permanent_diff` (Update ersetzt den Body, die Eigenschaft verschwindet, Lauf danach: kein weiteres Update); `test_local_wins_run_keeps_pause_in_store` (`reconcile_reservations`, Event vorhanden, lokal neuer: danach `store.get_all_raw()[d]["slots"][0]["pause"] == 30`, auch nach `apply_reconciled`); `test_remote_wins_run_without_property_keeps_local_pause_via_event_id`.
  - **Bestehende Tests, die bewusst angepasst werden:** `tests/test_reservations_sync.py` (Plan-Dicts bei `create`/`update` und der Slot-Vergleich mit `send_reminder_minutes: None`, bei Z. ~29, ~55, ~77, ~112): Plan-Einträge erhalten `pause` **nur bei `pause > 0`**, damit alle Bestandsassertions mit Pause 0 unverändert grün bleiben; `tests/test_reservations.py` (Vergleich von `store.get(...)` mit der alten User-Shape bei Z. ~94) wird um `"pause": 0` ergänzt.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Umsetzen wie in den Interfaces; Update-Vergleich (`reservations_sync.py` Z. 127–136) um `pause`; Plan-Dicts (Z. 98–106, 129–145) um `pause`; `_pauses_by_event_id(local)` analog `_reminders_by_event_id`.
- [ ] **Step 4:** PASS. **Step 5:** Commit `feat(reservierung): Pause im Kalender-Abgleich, Termin bleibt brutto (Refs #455)`.

### Task 6: Doku und Release-Vorbereitung

**Files:** Modify `src/CLAUDE.md`, `CLAUDE.md` (Modul-Einträge `reservations.py`, `mobile_reservations.py`, `api_reservation_write.py`), `README.md`, `CHANGELOG.md`, `src/version.py`

- [ ] **Step 1:** `src/CLAUDE.md` (Abschnitte `mobile_sync.py`, `api_reservation_write.py`, Dialoge: „Reservierung ohne Pause-Spalte“), Wurzel-`CLAUDE.md` und README (`*(ab --VERSION--)*` an den neuen Zeilen, API-Beschreibung ohne „ohne `pause`“) nachziehen.
- [ ] **Step 2:** `src/version.py` auf `1.27.0`, `CHANGELOG.md`-Abschnitt (Pause an Reservierungen, Kalendertermin bleibt brutto, API, Handy-Abgleich; **ausdrücklich nennen:** eine ältere Handy-Version, die Start/Ende einer Reservierung ändert, setzt deren Pause auf 0; Teilen überträgt keine Pause und ein Import setzt sie auf 0), `python scripts/resolve_readme_version.py`.
- [ ] **Step 3:** `pytest` (alles) → PASS; `ruff check .` und `pyright` sauber; `tests/test_claude_md_claims.py` grün.
- [ ] **Step 4:** Commit `docs(reservierung): Pause an Reservierungen, Release 1.27.0 vorbereitet (Refs #455)`. Der PR nach `master` trägt das Label `release:minor` und wird **vor** dem PWA-Strang gemergt und veröffentlicht.
