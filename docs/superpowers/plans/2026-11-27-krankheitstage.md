# Krankheitstage, Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kalendertage lassen sich als Krankheitstage mit fortgezahlten Stunden markieren. Sie reisen per Drive-Sync und zum Handy und erscheinen im Kalender, auf Wunsch im Bericht und im Webhook sowie in der lokalen API.

**Architecture:** Ein Datensatz je Kalendertag in `sick.json` (`SickStore`). Im Sync-Doc liegen die Tage als optionaler Bereich `sick`, Abgleich je Tag nach „neuer gewinnt“, ohne Konflikte und ohne Schema-Sprung. Die Regeln liegen Tk-frei an einer Stelle:
- `src/sick_plan.py`: Vorbelegung, Durchschnitt, Sperren, Hinweise.
- `src/absence.py`: gemeinsamer Zeitraum-Kern mit Urlaub, „Krankheit gewinnt“ und Kappung.

Desktop-Dialog, lokale API und Handy-Abgleich rufen dieselben Funktionen. Das Handy markiert nur Tage, die Minuten rechnet der Desktop.

**Tech Stack:** Python 3.12 (Tk-freie Kernmodule, Tkinter-Oberfläche), pytest, ruff, pyright 1.1.411. PWA: reines JavaScript mit `// @ts-check`, `node --test`, biome, tsc.

**Spec:** `docs/superpowers/specs/2026-11-27-krankheitstage-design.md` (Commit `90afdce`). Der Plan argumentiert aus der Spec; wer einen Task umsetzt, liest beide.

## Global Constraints

- **Keine Versionssprünge:** `sync.SCHEMA_VERSION` bleibt 4, `share.SCHEMA_VERSION` 3, `mobile_sync.PROTOCOL` 2 und `webhook.PAYLOAD_SCHEMA_VERSION` 2.
- **Bitgleich ohne Krankheit:**
  - Ohne Krankheitstage fehlt der Bereich `sick` im Sync-Doc.
  - Ohne Häkchen „Krankheit ausweisen“ sind Bericht (HTML, PDF) und Webhook-Dokument bitgleich zu heute.
  - API-Zahlen bleiben für Nutzer ohne Krankheitstage gleich.
- **Minuten:** ganze Zahl 0–1440 je Tag. Ein Block umfasst höchstens 366 Tage, der Sechs-Wochen-Hinweis greift ab 43 Kalendertagen (`> 42`).
- **Einstellung `sick_hours_basis`:** Werte `"standard"` (Vorgabe) und `"average_3m"`. Sie steht in `SYNCED_SETTING_KEYS`, jeder andere Wert gilt als `"standard"`.
- **Datenschutz:** Gesundheitsdaten stehen nie im Log, in Fehlermeldungen außerhalb der App oder im Debug-Protokoll der PWA. Ein Log nennt höchstens Anzahlen, nie Datum oder Minuten eines Krankheitstags.
- **Nie:** Krankheit in der Teilen-Datei (`share.py`) oder im Google-Kalender.
- **Format:** Datum intern ISO, in der UI `TT.MM.JJJJ` über `time_utils.format_iso_date`. Summen nur über Minuten (Wurzel-`CLAUDE.md`, „Stunden“).
- **Tk-freie neue Module:**
  - vollständig annotiert, in `ANNOTATED_MODULES` (`tests/test_type_annotations.py`) eingetragen;
  - tragen `# pyright: reportOptionalMemberAccess=true`;
  - fallen unter die Coverage-Untergrenze.
- **Regeln aus der Wurzel-`CLAUDE.md`:**
  - Jeder Catch-all loggt oder trägt eine Begründung.
  - Pixelwerte über `theme.px()`.
  - `create_dialog` immer gepaart mit `center_dialog_on_parent`.
  - Kommentare nennen das Warum, keine Historie.
- **Texte (sachlich, keine Rechtsberatung):**
  - `HINT_SIX_WEEKS` = „Die Entgeltfortzahlung endet in der Regel nach sechs Wochen; danach zahlt meist die Krankenkasse. Welche Tage zählen, klärt dein Arbeitgeber.“
  - `HINT_SUGGESTION` = „Die Stunden sind ein Vorschlag. Abgerechnet wird beim Arbeitgeber; Wartezeit und Tarifvertrag kennt die App nicht.“
  - `HINT_AU` = „Frag deinen Arbeitgeber, ab wann eine Arbeitsunfähigkeitsbescheinigung nötig ist.“
  - `HINT_AVERAGE_FALLBACK` = „Im Zeitraum davor ist keine Arbeitszeit erfasst; vorbelegt ist die Standardzeit des Wochentags.“
  - `HINT_SICK_ON_VACATION` = „Krankheit im Urlaub zählt hier als Krankheit. Damit die Urlaubstage gutgeschrieben werden, verlangt der Arbeitgeber in der Regel ein ärztliches Attest.“
- **Branches:** gestapelt.
  - PR 1 liegt auf `feat/krankheitstage` (Basis `chore/neues-app-icon`).
  - Jeder weitere PR bekommt einen eigenen Branch vom Kopf des vorigen: `feat/krank-2-sync`, `feat/krank-3-desktop`, `feat/krank-4-ausgabe`, `feat/krank-5-api`, `feat/krank-6-handy`, `feat/krank-7-pwa`.
- **Commits:** bleiben lokal und enden mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Push, PR und Issue nur nach Rückfrage beim Nutzer.
- **Am Ende jedes PRs, bevor er geöffnet wird:**
  - Volle Suite: `.venv/bin/python -m pytest -q`.
  - `ruff check .`
  - pyright: `uvx --quiet pyright@1.1.411 --pythonpath .venv/bin/python`. Bekannt und nicht vom Branch: 5 Fehler zu `websockets`.
  - Coverage-Gate: `pytest --cov=src --cov-report=json tests/ -q && python scripts/coverage_gate.py coverage.json`.
  - Bei PWA-Anteilen:
    - `cd pwa && node --test`
    - `npm run typecheck`
    - biome auf einem sauberen `git archive`-Export.
  - Danach ein kritisches Review durch Fable (Agent mit `model: fable`, nur lesen): Brief mit Spec, Diff und Prüffragen. Die Befunde gegenprüfen und berechtigte per TDD einarbeiten.
  - Dann den Nutzer fragen, ob der PR geöffnet wird: Basis ist der vorige Branch, `Refs #521`, und der letzte PR trägt `Closes #521`.

## Review Focus

Diese fünf Eingaben oder Fehlerlagen deckt keine Testliste der Spec ab. Jede hat ihren Test in dem Task, dem der Code gehört.

1. **Ein Gerät kehrt nach der Kompaktierung zurück (`excluded`), und das Drive-Doc stammt gerade von einem alten Desktop ohne Bereich `sick`.**
   - Erwartet: das Gerät behält seine Krankheitstage.
   - Die Self-Heal-Regel darf nur gegen einen vorhandenen Bereich greifen, nie gegen einen fehlenden.
   - Test: `test_excluded_device_keeps_sick_days_when_remote_lacks_section` (Task 6).
2. **Ein Drive-Doc mit kaputtem Krankheits-Datensatz** (`minutes: "8h"`, fehlendes `modified_at`, Bereich ist eine Liste).
   - Erwartet: das Doc gilt als gültig, der Datensatz wird übersprungen, der lokale Stand bleibt.
   - Tests: `test_broken_sick_section_keeps_doc_valid_and_local_days`, `test_bad_sick_record_is_skipped_not_merged` (Task 6).
3. **Über den Sync kommt ein unbekannter Wert für `sick_hours_basis`** (neueres Gerät, Fremddaten).
   - Erwartet: Dialog, API und Handy-Abgleich rechnen wie `"standard"`, ohne Ausnahme.
   - Test: `test_prefill_unknown_basis_counts_as_standard` (Task 4).
4. **Im Referenzzeitraum des Durchschnitts liegt ein kaputter Slot** (`end` fehlt, `pause: None`).
   - Erwartet: der Slot zählt nicht, der Dialog öffnet trotzdem.
   - Test: `test_average_ignores_malformed_slots` (Task 4).
5. **Das Handy meldet einen Tag krank, auf dem der Desktop inzwischen Ist-Zeit hat.**
   - Erwartet: der Abgleich nimmt ihn an und rechnet die Minuten, die Auswertung kappt die Krankheit um die Ist-Zeit.
   - Test: `test_phone_sick_day_over_worktime_is_accepted_and_capped` (Task 16).

## Bewusste Abweichung von der Spec

Die Spec nennt für `409 sick_day` einen neuen Eintrag in `pwa/test/fixtures/errors.json`. Der Code kommt aber nur aus der lokalen API (`api_entry_write.check_day_writable`), nie aus der Handy-Instanz. `tests/test_mobile_contract.py` sucht gesendete Codes nur in `mobile_routes.py`, `mobile_sync.py`, `api_server.py` und `api_auth.py`, und die PWA bekommt den Code nie zu sehen. Ein Eintrag dort wäre deshalb toter Vertrag, und `errors.json` bleibt unverändert. Die Fehler der Handy-Anfrage zu `sick` laufen über das vorhandene `422 invalid_entry`.

## Dateien im Überblick

| Datei | Rolle | PR |
|---|---|---|
| `src/absence.py` (neu) | Zeitraum-Kern für Urlaub und Krankheit: Datumsreihe, Feiertage, Verteilung, Kappung, Hinweistexte; dazu `cut_absences` („Krankheit gewinnt“) | 1, 2 |
| `src/sick_days.py` (neu) | `SickStore`, Bereinigung der Datensätze, Blockbildung | 2 |
| `src/sick_plan.py` (neu) | Grundlage, Vorbelegung, Durchschnitt, Planen, Sperren, Hinweise, Speichern samt Reservierungen | 2, 3 |
| `src/sync.py`, `src/sync_journal.py`, `src/sync_runtime.py`, `src/main.py` | Bereich `sick` im Sync und Verdrahtung | 2 |
| `src/sick_view.py` (neu) | Anzeigetexte: Blockbeschriftung, Tooltip, Verwaltungsliste | 3 |
| `src/dialogs/sick_dialog.py` (neu) | Krankheits-Dialog und „Krankheit verwalten“ | 3 |
| `src/grid_renderer.py`, `src/ui.py`, `src/dialogs/entry_dialog.py`, `src/dialogs/vacation_dialog.py`, `src/dialogs/settings_dialog/tab_work.py`, `src/theme/*` | Kalender, Klicks, Sperre im Urlaubs-Dialog | 3 |
| `src/report.py`, `src/webhook.py`, `src/dialogs/period_picker.py`, Senden/Export | Ausgabewege | 4 |
| `src/api_sick_write.py` (neu), `src/api_routes.py`, `src/api_entry_write.py`, `src/api_summary.py` | Lokale API | 5 |
| `src/mobile_sick.py` (neu), `src/mobile_sync.py`, `src/mobile_routes.py` | Handy-Abgleich, Desktop-Seite | 6 |
| `pwa/sick.js` (neu), `pwa/store.js`, `pwa/sync.js`, `pwa/sync-errors.js`, `pwa/view-model.js`, `pwa/views.js`, `pwa/app.js`, `pwa/app.css` | PWA | 7 |

---

## PR 1: Zeitraum-Kern (Branch `feat/krankheitstage`)

### Task 1: `src/absence.py` herausziehen, `cap_notice` für Krankheit

**Files:**
- Create: `src/absence.py`, `tests/test_absence.py`
- Modify: `src/vacations.py` (Helfer entfernen, aus `absence` importieren und re-exportieren), `src/vacation_plan.py` (`format_day_list` re-exportieren), `tests/test_type_annotations.py`, `CLAUDE.md` (Struktur: eine Zeile zu `src/absence.py`)

**Interfaces:**
- Produces, alles in `src/absence.py`:
  - `date_range(date_from: str, date_to: str) -> list[datetime.date]`
  - `holiday_dates(days: list[datetime.date], state: str) -> set[datetime.date]`
  - `apportion_minutes(total: int, n: int) -> list[int]`
  - `@dataclass(frozen=True) class CappedDay(date: str, minutes: int, work: int, capped: int)` mit der Property `vacation -> int` (gibt `minutes`; hält `api_summary` und die Tests unverändert)
  - `cap_by_worktime(day_minutes: dict[str, int], entries: dict[str, Any]) -> tuple[dict[str, int], list[CappedDay]]`
  - `cap_notice(hits: list[CappedDay], kind: str = "vacation") -> str` mit `kind` aus `"vacation"`/`"sick"`
  - `format_day_list(days: list[str], limit: int = 8) -> str`
- Re-exports unter den alten Namen:
  - `vacations`: `apportion_minutes`, `CappedDay`, `cap_by_worktime`, `cap_notice`
  - `vacation_plan`: `format_day_list`

- [ ] **Step 1: Failing tests in `tests/test_absence.py`**

```python
def test_vacation_names_are_the_shared_functions():
    assert vacations.cap_by_worktime is absence.cap_by_worktime
    assert vacations.cap_notice is absence.cap_notice
    assert vacations.CappedDay is absence.CappedDay
    assert vacations.apportion_minutes is absence.apportion_minutes
    assert vacation_plan.format_day_list is absence.format_day_list

def test_capped_day_keeps_vacation_alias():
    assert CappedDay("2026-09-01", 480, 240, 240).vacation == 480

def test_cap_notice_sick_single_day():
    assert cap_notice([CappedDay("2026-09-01", 480, 240, 240)], kind="sick") == (
        "An 1 Tag (01.09.2026) ist Arbeitszeit erfasst; "
        "die Krankheitsstunden sind dort um 4.0h gekürzt.")

def test_cap_notice_sick_lists_up_to_three_days():
    hits = [CappedDay(f"2026-09-0{i}", 480, 60, 420) for i in (1, 2)]
    assert cap_notice(hits, kind="sick") == (
        "An 2 Tagen (01.09.2026, 02.09.2026) ist Arbeitszeit erfasst; "
        "die Krankheitsstunden sind dort um insgesamt 2.0h gekürzt.")

def test_cap_notice_sick_drops_list_beyond_three_days():
    hits = [CappedDay(f"2026-09-0{i}", 480, 60, 420) for i in range(1, 5)]
    assert cap_notice(hits, kind="sick").startswith("An 4 Tagen ist Arbeitszeit erfasst;")
```

- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_absence.py -q`. Erwartet: FAIL, `ModuleNotFoundError: src.absence`.
- [ ] **Step 3: Implementieren.**
  - Die Funktionen ziehen wortgleich um. `_date_range`/`_holiday_dates` heißen dort ohne Unterstrich.
  - Der Urlaubswortlaut von `cap_notice` bleibt bytegleich, sein Docstring nennt beide Arten.
  - `vacations.py` importiert die Namen und re-exportiert sie (`__all__` oder `# noqa: F401` mit Begründung).
  - `absence.py` kommt in `ANNOTATED_MODULES`.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_absence.py tests/test_vacation_rules.py tests/test_vacations.py tests/test_vacation_dialog.py tests/test_report.py tests/test_webhook.py tests/test_api_summary.py tests/test_type_annotations.py -q`. Erwartet: PASS, die Urlaubs-Tests sind unverändert.
- [ ] **Step 5: Commit** `refactor(urlaub): Zeitraum-Kern nach absence.py für Urlaub und Krankheit`.
- [ ] **Step 6: PR-Abschluss** (Global Constraints). Zur Spec gehört der Commit `90afdce`, er geht mit diesem PR hinaus.

---

## PR 2: `SickStore`, Regeln und Sync (Branch `feat/krank-2-sync`)

### Task 2: `src/sick_days.py`, Store und Blöcke

**Files:**
- Create: `src/sick_days.py`, `tests/test_sick_days.py`
- Modify: `tests/test_type_annotations.py`

**Interfaces:**
- Produces:
  - `SickDay = dict[str, Any]`, Form `{minutes, modified_at, device_id, deleted}`.
  - `MAX_MINUTES = 1440`
  - `REQUIRED_SICK_KEYS = frozenset({"minutes", "modified_at", "device_id", "deleted"})`
  - `clean_record(raw: object) -> SickDay | None`: Objekt mit `minutes` int (nicht bool) 0–1440, `modified_at` str, `device_id` str, `deleted` bool. Ein Tombstone bekommt `minutes = 0`. Der Rückgabewert trägt genau die vier Schlüssel.
  - `clean_section(raw: object) -> dict[str, SickDay]`:
    - Ein Nicht-Objekt ergibt `{}`.
    - Ein Schlüssel muss ein gültiges ISO-Datum `YYYY-MM-DD` sein.
    - Unbrauchbares entfällt. Geloggt wird nur die Anzahl (`"%d unbrauchbare Krankheitstage verworfen"`), nie ein Datum.
  - `runs(dates: Iterable[str]) -> list[tuple[str, str]]`: maximale Folgen lückenloser Daten, chronologisch.
  - `@dataclass(frozen=True) class SickBlock(date_from: str, date_to: str, days: dict[str, int])` mit der Property `total_minutes -> int`.
  - `class SickStore(filepath: str = "sick.json", device_id: str = "", lock: threading.RLock | None = None)`:
    - `day_minutes() -> dict[str, int]`: nur lebende Tage.
    - `is_sick(date_str: str) -> bool`
    - `block_for(date_str: str) -> SickBlock | None`
    - `blocks() -> list[SickBlock]`: chronologisch.
    - `save_range(days: dict[str, int]) -> None`: lebend, Stempel `utc_now_iso()`, eigenes `device_id`. Wirft `ValueError` bei Minuten außerhalb 0–1440 oder einem Nicht-Datum.
    - `replace_block(old_dates: Iterable[str], days: dict[str, int]) -> None`: alte Tage außerhalb von `days` werden Tombstones, alles in **einem** Schreibvorgang.
    - `delete_days(dates: Iterable[str]) -> None`: Tombstones.
    - `get_all_raw() -> dict[str, SickDay]`: Kopie inklusive Tombstones.
    - `apply_merge(merged: dict[str, SickDay]) -> None`: ersetzt den Stand; `ValueError`, wenn ein Pflichtfeld fehlt.
  - Mechanik:
    - `json_store.load_json_or_quarantine`, dann `clean_section`.
    - Geschrieben wird über `json_store.atomic_write_json`.
    - Scheitert das Schreiben, rollt der Speicher zurück (`except BaseException: …; raise`, wie `Storage.apply_merge`).

- [ ] **Step 1: Failing tests in `tests/test_sick_days.py`**
  - `test_save_range_writes_live_days_with_stamp_and_device`: `save_range({"2026-03-02": 450})` ergibt in `get_all_raw()` den Eintrag `{"minutes": 450, "deleted": False, "device_id": "dev-a", "modified_at": <utc_now_iso gepatcht>}`.
  - `test_day_minutes_skips_tombstones`
  - `test_delete_days_writes_tombstones_with_zero_minutes`
  - `test_block_for_spans_month_and_year_boundary`: Tage 2026-12-30 bis 2027-01-02, dann `block_for("2027-01-01") == SickBlock("2026-12-30", "2027-01-02", {…})`.
  - `test_block_for_stops_at_gap_and_at_tombstone`
  - `test_blocks_are_chronological_and_total_minutes_sums`
  - `test_replace_block_tombstones_days_outside_new_range`
  - `test_load_skips_bad_records_and_logs_no_dates`: Datei mit `{"2026-03-02": {"minutes": "8h", …}, "kaputt": {…}}`; `caplog` enthält „2 unbrauchbare“ und kein `2026-`.
  - `test_corrupt_file_is_quarantined`: ungültiges JSON → Datei `sick.json.corrupt-*` existiert, Store leer.
  - `test_failed_write_rolls_back_memory`: `atomic_write_json` wirft `OSError`; danach ist `day_minutes()` unverändert.
  - `test_save_range_rejects_out_of_range_minutes`: 1441 und −1 werfen `ValueError`.
  - `test_clean_section_drops_non_dict_and_bad_keys`: `clean_section([]) == {}`, `clean_section("x") == {}`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_sick_days.py -q`. Erwartet: FAIL (Modul fehlt).
- [ ] **Step 3:** Implementieren und in `ANNOTATED_MODULES` eintragen.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_sick_days.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q`. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(krank): SickStore mit Tagesdatensätzen und Blöcken`.

### Task 3: Einstellung `sick_hours_basis` und Grundlagen in `sick_plan`

**Files:**
- Create: `src/sick_plan.py` (nur der Teil dieses Tasks), `tests/test_sick_plan.py`
- Modify: `src/settings.py` (Default, `SYNCED_SETTING_KEYS`), `src/conflict_view.py` (`SETTING_LABELS`, Anzeigewert), `tests/test_type_annotations.py`

**Interfaces:**
- Produces:
  - `sick_plan.BASES = ("standard", "average_3m")`
  - `sick_plan.BASIS_LABELS = {"standard": "Standardzeit des Wochentags", "average_3m": "Durchschnitt der letzten 3 Monate"}`
  - `sick_plan.normalize_basis(value: object) -> str`
  - `settings["sick_hours_basis"]` mit dem Default `"standard"`
  - `conflict_view.SETTING_LABELS["sick_hours_basis"] = "Grundlage der Krankheitsstunden"`

- [ ] **Step 1: Failing tests**
  - `test_normalize_basis`: `normalize_basis("average_3m") == "average_3m"`; für `"kaputt"`, `None` und `3` jeweils `"standard"`.
  - In `tests/test_settings.py`: `test_fresh_settings_do_not_sync_sick_basis_until_set`. Ein frisches `Settings` liefert in `get_synced_doc()` keinen Schlüssel `sick_hours_basis`, nach `set_synced("sick_hours_basis", "average_3m")` schon.
  - In `tests/test_conflict_view.py`: `test_sick_basis_value_is_shown_in_words`. Der Anzeigewert für `"average_3m"` ist `"Durchschnitt der letzten 3 Monate"` (Muster `slot_order_mode`, `conflict_view.py:145`).
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_sick_plan.py tests/test_conflict_view.py tests/test_settings.py -q`. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren. Der Wert des Konflikts läuft über `normalize_basis`, dann über `BASIS_LABELS`.
- [ ] **Step 4:** Dieselben Tests laufen lassen. Erwartet: PASS. Der vorhandene Test „Label für jeden synchronisierten Schlüssel“ ist grün.
- [ ] **Step 5: Commit** `feat(krank): synchronisierte Grundlage der Krankheitsstunden`.

### Task 4: Vorbelegung, Durchschnitt, Planen, Sperren und Hinweise

**Files:**
- Modify: `src/sick_plan.py`, `tests/test_sick_plan.py`

**Interfaces:**
- Consumes:
  - `absence.date_range`, `absence.holiday_dates`, `absence.format_day_list`
  - `time_utils.calculate_hours`, `time_utils.hours_to_minutes`
  - `settings.SettingsLike`, `settings.WEEKDAY_KEYS`
- Produces, alles in `src/sick_plan.py`:
  - Konstanten: `SIX_WEEKS_DAYS = 42`, `MAX_BLOCK_DAYS = 366`, `MAX_MINUTES_PER_DAY = 1440` und die fünf Texte aus den Global Constraints.
  - `reservation_net_minutes(reservation: Mapping[str, Any] | None) -> int`: Summe je Slot aus Spanne minus `pause`. Kaputte Slots zählen 0.
  - `standard_minutes(day: datetime.date, settings: SettingsLike) -> int`: `default_start_<tag>` bis `default_end_<tag>` minus `default_pause`. Untergrenze 0, unlesbare Zeiten ergeben 0.
  - `reference_period(first_day: datetime.date, entries: Mapping[str, Any]) -> tuple[datetime.date, datetime.date] | None`:
    - Beginn ist derselbe Tag drei Monate vor `first_day`, auf die Monatslänge geklemmt. Ende ist `first_day − 1 Tag`.
    - Der Beginn rückt auf den ersten Tag mit Ist-Slots im ganzen Bestand vor.
    - `None`, wenn dieser Tag nach dem Ende liegt oder es keinen gibt.
  - `average_minutes(first_day: datetime.date, *, entries: Mapping[str, Any], vacation_days: Mapping[str, int], sick_days: Mapping[str, int], state: str) -> int | None`:
    - Zähler: Ist-Minuten aller Tage im Zeitraum, Wochenende eingeschlossen.
    - Nenner: Mo–Fr ohne Feiertage.
    - Aus beiden fallen Tage mit Urlaubs- oder Krankheitsminuten > 0.
    - Ergebnis: `min(1440, zähler // nenner)`. `None`, wenn Zähler oder Nenner 0 ist.
    - Ein Slot, der `calculate_hours` scheitern lässt oder unlesbar ist, zählt 0 (`try` eng um den einen Slot; der Handler trägt die Begründung „Fremddaten aus dem Sync“).
  - `@dataclass(frozen=True) class Prefill(days: dict[str, int], basis_used: str, hints: list[str])`
  - `prefill(date_from: str, date_to: str, *, basis: str, entries: Mapping[str, Any], reservations: Mapping[str, Any] | None, vacation_days: Mapping[str, int], sick_days: Mapping[str, int], settings: SettingsLike) -> Prefill`:
    - Reihenfolge je Tag:
      1. Eine Reservierung mit Slots ergibt `reservation_net_minutes`. `reservations` ist `None`, wenn Reservierungen nicht aktiv sind; der Aufrufer prüft das mit `reservations_active`.
      2. Sonst Sa/So oder ein Feiertag von `settings["state"]`: 0.
      3. Sonst die Grundlage.
    - `basis` läuft über `normalize_basis`.
    - Bei `average_3m` ohne Wert gilt `basis_used = "standard"` und `hints` enthält `HINT_AVERAGE_FALLBACK`.
  - `plan_sick_save(date_from: str, date_to: str, prefilled: Mapping[str, int], overrides: Mapping[str, int]) -> dict[str, Any]` liefert `{"error": str | None, "days": dict[str, int]}`:
    - Bis vor Von ergibt „Das Bis-Datum liegt vor dem Von-Datum.“
    - Mehr als 366 Tage ergibt „Ein Krankheitszeitraum darf höchstens 366 Tage umfassen.“
    - Overrides gelten nur innerhalb des Zeitraums, mit `max(0, …)`.
    - Mehr als 1440 Minuten ergibt eine Meldung mit `format_day_list` wie in `plan_vacation_save`.
  - `work_blocking_days(days: Mapping[str, int], entries: Mapping[str, Any]) -> list[str]`: Tage mit Minuten > 0, an denen Ist-Slots liegen; sortiert.
  - `sick_blocking_vacation(vacation_days: Mapping[str, int], sick_days: Mapping[str, int]) -> list[str]`: Tage, an denen beide Minuten > 0 sind; sortiert.
  - `block_hints(days: Mapping[str, int]) -> list[str]`: immer `HINT_SUGGESTION`, bei `len(days) > 42` zuerst `HINT_SIX_WEEKS`.

- [ ] **Step 1: Failing tests (`tests/test_sick_plan.py`; `settings` ist ein Dict mit `.get`)**
  - `test_prefill_takes_reservation_net_minutes_even_on_weekend`: Sa 2026-06-06 mit Reservierung 09:00–13:00 und Pause 30 ergibt `days == {"2026-06-06": 210}`.
  - `test_prefill_ignores_reservations_when_none_passed`: derselbe Tag mit `reservations=None` ergibt 0.
  - `test_prefill_weekend_and_holiday_are_zero`: `state="BY"`, Do 2026-06-04 (Fronleichnam) und So 2026-06-07 ergeben 0.
  - `test_prefill_without_state_counts_holiday_as_workday`: `state=""` und 2026-06-04 ergeben die Standardzeit.
  - `test_prefill_standard_uses_weekday_times_minus_pause`: `default_start_mon "08:00"`, `default_end_mon "16:30"`, `default_pause 30`, Mo 2026-03-02 ergeben 480.
  - `test_standard_minutes_never_negative`
  - Gemeinsames Szenario für den Durchschnitt:
    - Ist-Zeit nur Mo/Mi/Fr je 480 in den Wochen ab 2026-03-02 und 2026-03-09.
    - Erster erfasster Tag ist 2026-03-02.
    - Der Block beginnt am Mo 2026-03-16.
    - Zeitraum 2026-03-02–2026-03-15 mit 10 Werktagen und 2880 Minuten.
  - `test_average_spreads_over_workdays`: `average_minutes(...) == 288`, und `prefill("2026-03-16", "2026-03-20", basis="average_3m", …).days` summiert 1440, also dieselbe Wochensumme wie im Referenzzeitraum.
  - `test_average_excludes_vacation_and_sick_days`: Urlaub 480 am Di 2026-03-03 ergibt `2880 // 9 == 320`. Ein Krankheitstag 450 am Do 2026-03-05 statt des Urlaubs ergibt ebenfalls 320.
  - `test_average_counts_weekend_work`: dazu Sa 2026-03-07 mit 240 ergibt `3120 // 10 == 312`.
  - `test_average_skips_holidays_in_denominator`: `state="BY"`, Ist-Zeit ab Mo 2026-01-05 (5 Tage × 480), Block ab Mo 2026-01-19; der 06.01. fehlt im Nenner, also `2400 // 9 == 266`.
  - `test_reference_period_three_months_back_across_year`: Bestand ab 2025-01-01, Block ab 2026-01-10 ergibt `(2025-10-10, 2026-01-09)`.
  - `test_reference_period_clamps_to_month_length`: Block ab 2026-05-31 ergibt Beginn 2026-02-28.
  - `test_reference_period_starts_at_first_recorded_day`
  - `test_average_none_without_worktime_falls_back_with_hint`: `prefill(..., basis="average_3m")` ergibt `basis_used == "standard"` und `HINT_AVERAGE_FALLBACK in hints`.
  - `test_average_floors_and_caps`: Zähler 1001 über 2 Werktage ergibt 500; riesige Ist-Zeit ergibt 1440.
  - `test_average_ignores_malformed_slots` (Review Focus 4): ein Slot `{"start": "08:00"}` und einer mit `pause: None` im Zeitraum werfen nicht und zählen 0.
  - `test_prefill_unknown_basis_counts_as_standard` (Review Focus 3)
  - `test_plan_rejects_reversed_range_and_too_long_block`: 367 Tage ergeben einen Fehler, 366 Tage nicht.
  - `test_plan_overrides_win_inside_range_only`
  - `test_plan_rejects_override_above_24h`
  - `test_work_blocking_days_only_counts_days_with_minutes`: Ist-Zeit am Sa mit 0 Minuten sperrt nicht.
  - `test_sick_blocking_vacation`
  - `test_block_hints_six_weeks_from_43_days`: 42 Tage ergeben `[HINT_SUGGESTION]`, 43 Tage `[HINT_SIX_WEEKS, HINT_SUGGESTION]`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_sick_plan.py -q`. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_sick_plan.py tests/test_catch_all_handlers.py -q`. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(krank): Vorbelegung der Stunden und Durchschnitt der letzten drei Monate`.

### Task 5: „Krankheit gewinnt“ in `absence.cut_absences`

**Files:**
- Modify: `src/absence.py`, `tests/test_absence.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class AbsenceCut`:
    - `vacation: dict[str, int]`
    - `sick: dict[str, int]`
    - `vacation_capped: list[CappedDay]`
    - `sick_capped: list[CappedDay]`
    - `sick_on_vacation: list[str]`
  - `cut_absences(entries: dict[str, Any], vacation_days: dict[str, int], sick_days: dict[str, int]) -> AbsenceCut`, in dieser Reihenfolge:
    1. Jeder Tag in `sick_days` (lebend, auch mit 0 Minuten) setzt Urlaubsminuten > 0 auf 0 und landet in `sick_on_vacation`.
    2. `cap_by_worktime` kappt die Krankheit.
    3. `cap_by_worktime` kappt den Urlaub.
  - `sick_on_vacation_notice(dates: list[str]) -> str`:
    - Einzahl: „An 1 Tag (03.06.2026) lag Krankheit im Urlaub; dieser Tag zählt als Krankheit.“
    - Mehrzahl: „An 2 Tagen (03.06.2026, 04.06.2026) lag Krankheit im Urlaub; diese Tage zählen als Krankheit.“
    - Die Liste entfällt ab 4 Tagen wie bei `cap_notice`. Ohne Tage `""`.

- [ ] **Step 1: Failing tests**
  - `test_cut_without_sick_equals_cap_by_worktime`: `cut_absences(e, v, {})`; `vacation` und `vacation_capped` gleichen `cap_by_worktime(v, e)`, `sick == {}`.
  - `test_sick_zeroes_vacation_and_reports_it`
  - `test_sick_is_capped_before_vacation`: Tag mit Urlaub 480, Krankheit 450 und Ist 120 ergibt Urlaub 0, Krankheit 330; der Urlaub erscheint nicht in `vacation_capped`.
  - `test_day_never_exceeds_max_of_work_and_absence`: parametrisiert über Kombinationen aus Ist ∈ {0, 120, 600}, Urlaub ∈ {absent, 0, 480}, Krankheit ∈ {absent, 0, 450}. Je Tag gilt `work + vacation + sick <= max(work, sick_in if sick present else vacation_in)`.
  - `test_sick_on_vacation_notice_wording`
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_absence.py -q`. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Dieselben Tests laufen lassen. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(krank): Krankheit gewinnt über Urlaub, Kappung durch Ist-Zeit`.

### Task 6: Bereich `sick` in der Sync-Engine

**Files:**
- Modify: `src/sync.py` (Modul-Docstring, `merge`, `build_local_doc`, `apply_merged_doc`, `compact_local`, `drop_orphan_tombstones`), `tests/test_sync_determinism.py`
- Create: `tests/test_sync_sick.py`

**Interfaces:**
- Consumes: `sick_days.SickStore`, `sick_days.clean_section` (nur unter `TYPE_CHECKING` für den Typ).
- Produces, alle mit dem neuen Schlüsselwort `sick_store: SickStore | None = None`:
  - `build_local_doc(storage, settings, conflicts_store, sick_store=None) -> Doc`: setzt `doc["sick"] = sick_store.get_all_raw()` nur, wenn der Store mindestens einen Datensatz hat.
  - `merge(local, remote, last_pull_at) -> Doc` (Signatur unverändert):
    - `merged["sick"]` entsteht nur, wenn eine Seite den Schlüssel trägt.
    - Je Tag gewinnt `_lww_winner` über `clean_section` beider Seiten.
    - Self-Heal wie bei den Einträgen, aber nur, wenn `isinstance(remote.get("sick"), dict)`.
    - Ruhende Tombstones (`_is_settled_entry`) entfallen nach dem Watermark.
    - Nie ein Konflikt.
  - `apply_merged_doc(merged_doc, storage, settings, conflicts_store, sick_store=None)`: schreibt `sick_store.apply_merge(clean_section(merged_doc["sick"]))` nur, wenn `"sick" in merged_doc` und der Store da ist.
  - `compact_local(storage, settings, conflicts_store, now, sick_store=None)`: entfernt ruhende Krankheits-Tombstones.
  - `drop_orphan_tombstones(storage, settings, sick_store=None) -> int`: zählt verworfene Krankheits-Tombstones mit.
  - `validate_remote_doc`: unverändert. Ein kaputter Bereich `sick` ist kein Fehler.

- [ ] **Step 1: Failing tests in `tests/test_sync_sick.py`** (Stores auf `tmp_path`, `utc_now_iso` gepatcht)
  - `test_doc_without_sick_days_has_no_section`: `build_local_doc(..., sick_store=empty)` und `build_local_doc(...)` haben dieselben Schlüssel; `"sick" not in doc`.
  - `test_merge_without_sick_on_either_side_has_no_section`
  - `test_merge_takes_newer_record_per_day_symmetric`: `merge(a, b)["sick"] == merge(b, a)["sick"]`.
  - `test_tombstone_beats_older_save`
  - `test_missing_section_never_deletes`: lokale Tage bleiben, wenn `remote` keinen Bereich hat.
  - `test_excluded_device_keeps_sick_days_when_remote_lacks_section` (Review Focus 1): `last_pull_at < remote gc_watermark`, kein Bereich `sick` remote, alter lebender Tag lokal; der Tag bleibt.
  - `test_excluded_device_drops_old_sick_day_missing_from_remote_section`: Remote trägt `"sick": {}`; der Tag entfällt wie ein Eintrag.
  - `test_broken_sick_section_keeps_doc_valid_and_local_days` (Review Focus 2): `remote["sick"] = ["x"]`, dann gilt `validate_remote_doc(remote) == (True, "")` und `merge` behält den lokalen Stand. Der Bereich ist kein Objekt, Self-Heal greift also nicht.
  - `test_bad_sick_record_is_skipped_not_merged` (Review Focus 2): Remote-Tag mit `minutes: "8h"` und jüngerem Stempel; der lokale Datensatz gewinnt.
  - `test_apply_writes_store_only_when_doc_has_section`
  - `test_compact_strips_settled_sick_tombstones`
  - `test_sweep_drops_sick_tombstones_only_when_never_synced`
  - In `tests/test_sync_determinism.py`: `sick` in die Permutations-Docs aufnehmen (mindestens ein Tag, auf dem zwei Seiten im selben Zeitstempel verschiedene Minuten tragen).
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_sync_sick.py tests/test_sync_determinism.py -q`. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren. Im Modul-Docstring kommt `sick` in die Doc-Struktur, mit einem Absatz „additiv ohne Schema-Bump, Fehlen heißt nie gelöscht“ nach dem Muster von `devices`.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_sync_sick.py tests/test_sync_determinism.py tests/ -q -k "sync"`. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(krank): Krankheitstage im Sync-Doc, additiv ohne Schema-Bump`.

### Task 7: Verdrahtung: Journal, Runtime, Start und Entfernen

**Files:**
- Modify:
  - `src/sync_journal.py`: `apply_merged_doc_journaled(..., sick_store=None)`, `recover_pending_apply(journal_path, storage, settings, conflicts_store, sick_store=None)`.
  - `src/sync_runtime.py`: `run_pull_in_background`, `run_push_blocking` und `run_compaction_blocking` bekommen je `sick_store=None` und reichen es an Build, Apply und Compact weiter.
  - `src/main.py`:
    - `SickStore(os.path.join(base, "sick.json"), device_id=device_id, lock=data_lock)` direkt nach `vacation_store`.
    - Der Store geht an `recover_pending_apply`, `_sweep_orphan_tombstones(..., sick_store=…)`, den Start-Pull und `App(..., sick_store=…)`.
  - `src/ui.py`: `App.__init__(..., sick_store=None)`, `self.sick_store`; weiter an `SyncOrchestrator` und den Einstellungen-Dialog bis zur Kompaktierung in `tab_google`.
  - `src/sync_orchestrator.py`, `src/dialogs/settings_dialog/dialog.py`, `src/dialogs/settings_dialog/tab_google.py`.
  - `src/removal.py`: `"sick.json"` in `USER_DATA_FILES`.
  - `installer.iss`: `DeleteMatching('sick.json.corrupt-*');` und `DeleteFile(ExpandConstant('{app}\sick.json'));` neben den Urlaubszeilen.
  - `.gitignore`: `sick.json*`.
  - `src/CLAUDE.md`: Abschnitt „Tombstone-Lebenszyklus“ und `sync.py`.
  - `CLAUDE.md`: Struktur, Zeilen zu `sick_days.py` und `sick_plan.py`.
- Test: `tests/test_sync_journal.py`, `tests/test_sync.py` (Push und Kompaktierung mit gefälschtem Drive), `tests/test_removal.py`.

**Interfaces:**
- Consumes: Task 6.
- Produces: `App.sick_store` (oder `None`). Die Tasks 9 bis 16 lesen ihn.

- [ ] **Step 1: Failing tests**
  - `test_recover_pending_apply_restores_sick_days`: ein Journal mit `sick` wird nach dem „Absturz“ angewendet.
  - `test_push_uploads_sick_section`: nach dem Muster der vorhandenen Push-Tests mit gefälschtem Drive. Das hochgeladene Doc trägt `sick`.
  - `test_compaction_strips_settled_sick_tombstones_end_to_end`
  - `tests/test_removal.py` wird rot, sobald `sick.json` nur in einer der beiden Listen steht; erst beide ändern.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_sync_journal.py tests/test_sync.py tests/test_removal.py -q`. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren. Der Default `None` hält alle bisherigen Aufrufer und Tests unverändert.
- [ ] **Step 4:** Volle Suite. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(krank): SickStore in Start, Sync, Kompaktierung und Entfernen`.
- [ ] **Step 6: PR-Abschluss** (Global Constraints). PR „Krankheitstage 2/7: Store, Regeln und Sync“.

---

## PR 3: Desktop-Oberfläche (Branch `feat/krank-3-desktop`, Label `platform:macos`)

### Task 8: Palette, macOS-✕ und Anzeigetexte

**Files:**
- Create: `src/sick_view.py`, `tests/test_sick_view.py`
- Modify:
  - `src/theme/palette.py`: `SICK_BG`, `SICK_BG_HOVER`, `SICK_ACCENT`. Die Werte wählt der Builder. Vorschlag: `#4c1d3d`/`#65274f`/`#f472b6`. Der Kontrast von `TEXT` auf `SICK_BG` liegt mindestens beim Kontrast von `TEXT` auf `VACATION_BG`.
  - `src/theme/geometry.py`: `_should_show_delete_button(is_macos, has_entry, has_reservation, has_vacation=False, has_sick=False)`.
  - `src/theme/__init__.py`: Re-exports.
  - `tests/test_type_annotations.py`
  - `tests/test_delete_button.py` (vorhandener Test zu `_should_show_delete_button`).

**Interfaces:**
- Produces, alles in `src/sick_view.py`:
  - `block_label(block: SickBlock) -> str`: „Krankheit 02.03.2026 – 06.03.2026“; ein einzelner Tag „Krankheit 02.03.2026“.
  - `delete_key(block: SickBlock) -> str`: `"sick:" + block.date_from`.
  - `cell_tooltip(date_str: str, block: SickBlock, *, vacation_name: str | None = None, holiday: str | None = None) -> str`:
    - Zeile 1: „Krank (02.03.2026 – 06.03.2026)“.
    - Zeile 2 nur bei Minuten > 0: `format_minutes_hm` des Tages.
    - Danach „Urlaub „Name““ und „Feiertag: Name“, wenn übergeben.
  - `manager_rows(blocks: list[SickBlock]) -> list[tuple[str, str]]`: neueste zuerst, als (Zeitraum, `format_minutes_hm(total)`).

- [ ] **Step 1: Failing tests:** `test_block_label_single_and_range`, `test_cell_tooltip_without_hours_on_zero_day`, `test_cell_tooltip_names_vacation_and_holiday`, `test_manager_rows_newest_first`, `test_delete_button_shows_for_sick_on_macos_only`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_sick_view.py tests/test_delete_button.py -q`. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Dieselben Tests plus `tests/test_type_annotations.py`. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(krank): Anzeigetexte, Farben und macOS-Löschknopf für Krankheit`.

### Task 9: Krankheits-Dialog und „Krankheit verwalten“

**Files:**
- Create: `src/dialogs/sick_dialog.py`
- Modify:
  - `src/sick_plan.py`: Tk-freier Speicherkern, Test in `tests/test_sick_plan.py`.
  - `src/dialogs/settings_dialog/tab_work.py`: der Knopf „Krankheit verwalten“ steht in `specs` direkt nach „Urlaub verwalten“.
  - `src/dialogs/settings_dialog/dialog.py`: Durchreichen von `sick_store`, `storage`, `reservation_store` und `vacation_store`.

**Interfaces:**
- Produces:
  - `sick_plan.reservation_dates_in(days: Mapping[str, int], reservations: Mapping[str, Any] | None) -> list[str]`: Tage des Blocks mit Reservierungs-Slots.
  - `sick_plan.commit_sick_block(sick_store: SickStore, reservation_store: Any, *, old_dates: Iterable[str], days: dict[str, int], delete_reservations: bool) -> list[str]`:
    - Schreibt `replace_block` (oder `save_range`, wenn `old_dates` leer ist).
    - Löscht danach die Reservierungen der Tage über `reservation_store.delete`, nur mit `delete_reservations` und nur, wenn der Store da ist.
    - Liefert die gelöschten Reservierungstage. Die Minuten wurden vorher geplant (Spec, „Reihenfolge“).
  - `open_sick_dialog(parent, *, sick_store, storage, settings, date_from: str, date_to: str | None = None, reservation_store=None, vacation_store=None, on_change=None, on_reservations_deleted=None) -> None`. Liegt `date_from` in einem Block, öffnet der Dialog diesen Block zum Bearbeiten: Von/Bis aus dem Block, seine Tage als Overrides.
  - `open_sick_manager(parent, *, sick_store, storage, settings, reservation_store=None, vacation_store=None, on_change=None, on_reservations_deleted=None) -> None`

- [ ] **Step 1: Failing tests (Tk-frei)**
  - `test_commit_deletes_reservations_only_when_asked`
  - `test_commit_tombstones_days_outside_edited_block`
  - `test_reservation_dates_in_lists_days_with_slots`
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_sick_plan.py -q`. Erwartet: FAIL.
- [ ] **Step 3: Kern implementieren, dann den Dialog bauen.** Der Dialog nutzt `create_dialog`/`Form`, wie `vacation_dialog`:
  - Von und Bis über `date_row`.
  - Zwei Radiobuttons mit `BASIS_LABELS`, vorbelegt aus `normalize_basis(settings.get("sick_hours_basis"))`. Ein Wechsel setzt `settings.set_synced("sick_hours_basis", …)` erst beim Speichern.
  - Eine aufklappbare Tagesliste. Neu gerechnet wird über `prefill`, von Hand geänderte Tage hält `vacation_dialog.prune_overrides`.
  - Summe und `prefill(...).hints` + `block_hints(...)`.
  - Das Häkchen „Reservierungen in diesem Zeitraum löschen“ (Vorgabe an), nur sichtbar bei `reservation_dates_in(...)` ≠ leer und aktiven Reservierungen.
  - `HINT_AU`; ohne Bundesland derselbe Hinweis wie im Urlaubs-Dialog.
  - `HINT_SICK_ON_VACATION`, sobald der Block Urlaubstage mit Minuten > 0 berührt (`sick_blocking_vacation(vacation_store.day_minutes(), days)` ist nicht leer).
  - Beim Speichern:
    1. `plan_sick_save` prüfen.
    2. `work_blocking_days` prüfen; bei einem Treffer `themed_showerror` mit „An diesen Tagen ist bereits Arbeitszeit erfasst:\n\n“ + `format_day_list` + „\n\nKrankheit und Arbeitszeit schließen sich am selben Tag aus; zuerst die Einträge löschen oder einen anderen Zeitraum wählen.“
    3. Unter `data_lock` (falls übergeben) `commit_sick_block` aufrufen.
    4. `on_change()`, und wenn Reservierungen gelöscht wurden, `on_reservations_deleted()`.
  - Verwaltung: Liste aus `manager_rows`, Knöpfe Neu, Bearbeiten und Löschen (mit Bestätigung), dazu der Hinweis „Löschen geht auch per Rechtsklick im Kalender.“
  - `px()` für jede Pixelangabe, `center_dialog_on_parent` je Dialog.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_sick_plan.py tests/test_dialog_reveal.py tests/test_pixel_scaling.py tests/test_catch_all_handlers.py -q`. Erwartet: PASS. Von Hand mit `python -m src.main` prüfen:
  - Einen Block anlegen und bearbeiten.
  - Die Grundlage wechseln.
  - Mit und ohne Häkchen speichern.
  - Die Ist-Zeit-Sperre auslösen.
- [ ] **Step 5: Commit** `feat(krank): Krankheits-Dialog und Verwaltung in den Einstellungen`.

### Task 10: Kalender, Klicks, Tages-Dialog und Urlaubs-Sperre

**Files:**
- Modify:
  - `src/grid_renderer.py`: `GridRenderer(..., sick_store=None)`; `_build_sick_cell` nach dem Muster von `_build_vacation_cell`. Krankheit gewinnt über Urlaub, Feiertag und Wochenende. Zelltext „krank“, Stundenzeile bei Minuten > 0, Tooltip über `sick_view.cell_tooltip`, genau ein `attach_tooltip`, ✕ mit `has_sick`.
  - `src/ui.py`:
    - `_open_dialog`: vor der Urlaubsprüfung öffnet ein Krankheitstag mit Minuten > 0 `open_sick_dialog(date_from=date_str)`. Die Urlaubsmeldung wird zu `themed_ask_action(...)` mit dem Knopf „Krank melden…“; bei `True` folgt `open_sick_dialog(date_from=date_str)`.
    - `_delete_day`: Einheit `sick_view.delete_key(block)` mit `block_label(block)`. Ist sie die einzige Einheit, fragt `themed_askyesno` „{block_label} komplett löschen?“. Gelöscht wird mit `sick_store.delete_days(block.days)`.
    - Weiterreichen an Renderer, Einstellungen, Tages-Dialog, Senden und Export.
  - `src/theme/messagebox.py`: `themed_ask_action(parent, title: str, message: str, action_label: str, close_label: str = "Schließen") -> bool`, Re-export in `theme/__init__.py`.
  - `src/dialogs/entry_dialog.py`: `open_entry_dialog(..., on_report_sick=None)` mit dem Knopf „Krank melden…“ im Fuß. Er schließt den Tages-Dialog und ruft dann `on_report_sick()`; das ist kein Löschweg.
  - `src/dialogs/vacation_dialog.py`: `open_vacation_dialog(..., sick_store=None)` reicht bis `_save` durch. Nach `blocking_days` folgt `sick_blocking_vacation(plan_days, sick_store.day_minutes())`. Bei Treffern erscheint `themed_showerror` mit „An diesen Tagen bist du krank gemeldet:\n\n“ + `format_day_list` + „\n\nEinen Urlaub über Krankheitstage legt die App nicht an; Krankheit im Urlaub trägst du als Krankheit ein.“
  - `README.md`: eine Feature-Zeile `**Krankheitstage** *(ab --VERSION--)* — …`.
  - `CLAUDE.md`:
    - Abschnitt „Urlaub“: die Meldung am Urlaubstag hat „Krank melden…“.
    - „Kalender-Interaktion“: Krankheit als löschbare Einheit und ✕.
    - Struktur: `sick_view.py`, `sick_dialog.py`.
  - `src/CLAUDE.md`: Dialoge.
- Test: `tests/test_ui_delete.py` (vorhandenes Muster), `tests/test_vacation_dialog.py`.

**Interfaces:**
- Consumes: Tasks 4, 8 und 9.

- [ ] **Step 1: Failing tests**
  - `test_delete_day_offers_whole_sick_block`: im Muster von `test_ui_delete.py`; die Auswahl enthält `"sick:2026-03-02"` und löscht alle Tage des Blocks.
  - `test_vacation_save_blocked_by_sick_days`: falls der Kern Tk-frei prüfbar ist; sonst über `sick_blocking_vacation` in Task 4 abgedeckt.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_ui_delete.py tests/test_vacation_dialog.py -q`. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Volle Suite. Von Hand prüfen:
  - Farben in Monats- und Wochenansicht.
  - Tooltip über Urlaub und Feiertag.
  - Linksklick auf einen Krankheitstag, auf einen 0-Minuten-Krankheitstag und auf einen Urlaubstag (dort „Krank melden…“).
  - Rechtsklick-Auswahl.
  - „Krank melden…“ im Tages-Dialog.
  - Die Urlaubs-Sperre.
- [ ] **Step 5: Commit** `feat(krank): Krankheit im Kalender, beim Klicken und im Urlaubs-Dialog`.
- [ ] **Step 6: PR-Abschluss.** Label `platform:macos`, vor dem Merge einen Pre-Release für das macOS-✕ vorschlagen.

---

## PR 4: Ausgabewege (Branch `feat/krank-4-ausgabe`)

### Task 11: Bericht (Mail-HTML und PDF)

**Files:**
- Modify: `src/report.py`, `tests/test_report.py` (gegebenenfalls `tests/test_report_pdf_layout.py`)

**Interfaces:**
- Consumes: `absence.cut_absences`, `absence.cap_notice(kind="sick")`, `absence.sick_on_vacation_notice`.
- Produces: `generate_report(..., sick_days: dict[str, int] | None = None)` und `generate_pdf(..., sick_days: dict[str, int] | None = None)`.
  - `None` heißt: Häkchen aus, der heutige Pfad bleibt unverändert.
  - Ein Dict heißt: Häkchen an, Snapshot des Stores, ungefiltert wie `vacation_days`.
- Regeln:
  - Mit `sick_days` rechnen beide Funktionen über `cut_absences(range_entries, vacation_in_range, sick_in_range)`.
  - Der Urlaubs-Block bleibt; sein Total „Zu vergüten gesamt“ steht **nur** darin, wenn kein Krankheits-Block folgt.
  - Der Krankheits-Block hat die Kopfzeile „Krankheit“/„Stunden“ und Zeilen je Folge über `_vacation_runs`; der Name bleibt, der Docstring nennt beide Arten. Er trägt das Total `work + vacation + sick`, das damit am Ende steht.
  - Fußnoten in dieser Reihenfolge, je über `report._cap_footnote`-Stil:
    1. Urlaubs-Kappung (unter dem Urlaubs-Block).
    2. Krankheits-Kappung.
    3. `sick_on_vacation_notice`, unter dem letzten Block.
  - Leer ist der Bericht nur ohne Ist-Zeit, ohne Urlaubsminute **und** ohne Krankheitsminute.

- [ ] **Step 1: Failing tests**
  - `test_report_is_bit_identical_without_sick_flag`: `generate_report(..., vacation_days=v)` ist gleich `generate_report(..., vacation_days=v, sick_days=None)` und gleich `generate_report(..., vacation_days=v, sick_days={})`; dasselbe für das PDF-HTML.
  - `test_sick_block_lists_runs_and_total_comes_last`:
    - Ist 480 am 2026-03-02, Urlaub 480 am 2026-03-03, Krankheit 450 am 2026-03-04 und 2026-03-05.
    - Der Block „Krankheit“ zeigt „04.03.2026 – 05.03.2026“ und `15.0h`.
    - „Zu vergüten gesamt“ steht genau einmal da, mit `31.0h`, und nach „Krankheit“.
  - `test_sick_wins_over_vacation_with_footnote`
  - `test_sick_capped_by_worktime_footnote`: Fußnote im Krankheitswortlaut.
  - `test_month_cut_through_sick_block_adds_up`: Ist + Urlaub + Krankheit gleich „Zu vergüten gesamt“ in Minuten.
  - `test_report_with_only_sick_days_is_not_empty`
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_report.py -q`. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren. Die Urlaubs-Logik wird in einen gemeinsamen Helfer `_absence_section(...) -> str` gezogen, den beide Funktionen rufen.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_report.py tests/test_report_pdf_layout.py -q`. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(krank): Krankheit im Bericht, „Zu vergüten gesamt“ am Ende`.

### Task 12: Webhook

**Files:**
- Modify: `src/webhook.py`, `tests/test_webhook.py`

**Interfaces:**
- Produces: `build_json_payload(..., sick_days: dict[str, int] | None = None)`.
  - `None`: das Dokument ist unverändert, ohne die Schlüssel `sick`/`sick_minutes`.
  - Ein Dict: über `cut_absences` gegen `ranged`. Dazu kommen `"sick"` (alle lebenden Tage im Zeitraum, gekappt, auch 0-Minuten-Tage, `{}` ohne Tage) und `"sick_minutes"` (Summe, 0 ohne Tage).
  - `vacation` (wenn nicht `None`) trägt dann die Werte nach „Krankheit gewinnt“.

- [ ] **Step 1: Failing tests**
  - `test_payload_without_sick_flag_has_no_sick_keys`
  - `test_payload_with_sick_flag_always_has_both_fields`: `sick_days={}` ergibt `sick == {}` und `sick_minutes == 0`.
  - `test_sick_cuts_vacation_only_with_flag`
  - `test_sick_capped_by_worktime_in_payload`
  - `test_schema_version_stays_2`
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_webhook.py -q`. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren, den Docstring zu den Feldern ergänzen.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_webhook.py tests/test_claude_md_claims.py -q`. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(krank): Krankheit im Webhook, nur mit Häkchen`.

### Task 13: Zeitraum-Picker, Senden und Export

**Files:**
- Modify:
  - `src/dialogs/period_picker.py`
  - `src/dialogs/send_dialog.py`, `src/dialogs/send_task.py`
  - `src/dialogs/export_dialog.py`, `src/dialogs/export_task.py`
  - `src/ui.py`: `sick_store` an Senden und Export.
  - `CLAUDE.md`:
    - Abschnitt „Urlaub“: Liste der Ausgabewege und der Kappung.
    - `webhook.py`: die neuen Felder.
  - `src/CLAUDE.md`
- Test: `tests/test_period_picker.py` (dort liegt auch `period_has_no_content`), `tests/test_send_task.py`, `tests/test_export_task.py`.

**Interfaces:**
- Produces:
  - `period_picker.absence_preview(date_from, date_to, all_entries, categories, vacation_days, sick_days) -> tuple[int, int, list[str]]`: Urlaubsminuten, Krankheitsminuten und Hinweistexte, aus derselben Rechnung wie der Bericht. `vacation_preview` bleibt als dünne Hülle oder wird durch sie ersetzt.
  - `build_period_picker(..., sick_store=None)`. Das Häkchen „Krankheit ausweisen“ (Vorgabe aus) wird nur gebaut, wenn `workweek.filter_for_report(sick_store.day_minutes(), settings)` eine Minute > 0 hat. `handle.get_show_sick() -> bool`.
  - Die Vorschau zeigt zusätzlich „+ X h Krankheit“.
  - `send_dialog.period_has_no_content(ranged, vacation_days, date_from, date_to, sick_days=None) -> bool`.
  - `perform_send(..., sick_days=None)` und `export_task.…(..., sick_days=None)` reichen den Wert bis `generate_report`/`generate_pdf`/`build_json_payload` durch.

- [ ] **Step 1: Failing tests:** `test_absence_preview_matches_report_numbers`, `test_period_with_only_sick_days_has_content`, `test_send_task_passes_sick_days_to_report_and_webhook`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_period_picker.py tests/test_send_task.py tests/test_export_task.py -q`. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Volle Suite. Von Hand Senden und Export mit und ohne Häkchen prüfen, die Vorschau gegen den Bericht.
- [ ] **Step 5: Commit** `feat(krank): Häkchen „Krankheit ausweisen“ in Senden und Export`.
- [ ] **Step 6: PR-Abschluss.**

---

## PR 5: Lokale API und Datenschutz (Branch `feat/krank-5-api`)

### Task 14: Routen, Sperren und Auswertung

**Files:**
- Create: `src/api_sick_write.py`, `tests/test_api_sick_write.py`, `tests/test_api_sick.py`
- Modify:
  - `src/api_routes.py`: `ApiContext.sick_store: Any = None`, drei Routen, `_summary`, Sperre in `_post_vacation`.
  - `src/api_entry_write.py`: `check_day_writable(..., sick_store: Any = None)`.
  - `src/api_summary.py`: `summarize(..., sick_days: Mapping[str, int] | None = None)`.
  - `src/ui.py`: `ApiContext(..., sick_store=self.sick_store)`.
  - `tests/test_api_summary.py`, `tests/test_api_routes.py`, `tests/test_api_vacations.py`, `tests/test_type_annotations.py`.

**Interfaces:**
- Produces:
  - `api_sick_write`:
    - `@dataclass(frozen=True) class SickRequest(date_from: str, date_to: str, basis: str | None, overrides: dict[str, int])`
    - `parse_sick_body(body: bytes) -> SickRequest`: Schlüssel `from`/`to` als Pflicht, `basis`/`day_hours` optional.
    - Fehler:
      - Unbekannte Schlüssel: 400 `invalid_body`.
      - `basis` nicht in `BASES`: 422 `invalid_basis`.
      - Mehr als 366 Tage: 422 `period_too_long`.
      - `day_hours` wie in `api_vacation_write`: 422 `invalid_day_hours`.
  - `GET /v1/sick?from&to` liefert `{"sick": [{"from", "to", "days", "total_minutes"}]}`. Das sind die Blöcke, die den Bereich schneiden, ungekappt.
  - `POST /v1/sick`:
    - Rechnet `prefill(..., basis=parsed.basis or settings["sick_hours_basis"])` und dann `plan_sick_save`; ein Fehler ergibt 422 `invalid_sick`.
    - Unter dem Lock: `work_blocking_days` ergibt 409 `work_on_sick_days`, dann `save_range`.
    - Antwort 201 mit dem Block plus `warnings` (ohne Bundesland `_NO_STATE_WARNING`); danach `_notify(ctx)`.
    - Reservierungen bleiben.
  - `DELETE /v1/sick/{date}`: ohne Block 404 `not_found`, sonst `delete_days(block.days)` und 200 `{"from", "to", "deleted": true}`; danach `_notify`.
  - Ohne `ctx.sick_store` antworten alle drei mit 409 `sick_unavailable` (Muster `_vacation_store`).
  - `check_day_writable`: bei `for_save` und Krankheitsminuten > 0 `WriteError(409, "sick_day", "Für diesen Tag ist Krankheit eingetragen. An einem Krankheitstag lässt sich keine Arbeitszeit erfassen; die Krankheit zuerst in der App löschen.")`. `DELETE` bleibt erlaubt.
  - `_post_vacation`: Treffer von `sick_blocking_vacation` ergeben 409 `sick_on_vacation_days` mit „An diesen Tagen bist du krank gemeldet: …“.
  - `summarize`:
    - Rechnet über `cut_absences` gegen den robusten `work`-Ausschnitt.
    - Neue Felder `sick_minutes` (0 ohne Krankheit) und `sick_capped_days` (`[{"date", "sick_minutes", "work_minutes", "counted_minutes"}]`).
    - `vacation_minutes` ist an Krankheitstagen 0, `payable_minutes = total + vacation + sick`.
    - Ohne Krankheitstage bleiben alle bisherigen Zahlen gleich.

- [ ] **Step 1: Failing tests:** Parser (gültig, unbekannte Schlüssel, Basis, 367 Tage, `day_hours` außerhalb), die drei Routen, `409 sick_day` bei `PUT`, `DELETE` bleibt 200, `409 sick_on_vacation_days`, `test_summary_without_sick_days_is_unchanged`, `test_summary_sick_wins_and_is_payable`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_api_sick_write.py tests/test_api_sick.py tests/test_api_summary.py tests/test_api_routes.py tests/test_api_vacations.py -q`. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren. Die Routen kommen in `ROUTES` nach den Urlaubs-Routen.
- [ ] **Step 4:** Dieselben Tests laufen lassen, dazu `tests/test_mobile_contract.py`. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(krank): Krankheitstage in der lokalen API`.

### Task 15: Datenschutzhinweise und API-Doku

**Files:**
- Modify:
  - `docs/datenschutz.md`: ein Abschnitt zu Krankheitstagen mit den vier Punkten der Spec, „Datenschutz und Entfernen“.
  - `pwa/test/fixtures/privacy-blocks.json`: neu erzeugen mit `python scripts/privacy_fixtures.py`.
  - `src/CLAUDE.md`: Routen der lokalen API, `api_sick_write`.
  - `CLAUDE.md`: Struktur, `api_sick_write.py`.

- [ ] **Step 1:** Text schreiben und das Fixture neu erzeugen.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_privacy_doc.py -q && (cd pwa && node --test test/privacy-doc.test.js)`. Erwartet: PASS.
- [ ] **Step 3: Commit** `docs(krank): Datenschutzhinweise zu Krankheitstagen`.
- [ ] **Step 4: PR-Abschluss.**

---

## PR 6: Handy-Abgleich, Desktop-Seite (Branch `feat/krank-6-handy`)

### Task 16: `sick` in Anfrage und Antwort, eingefrorene Formen

**Files:**
- Create:
  - `pwa/test/fixtures/compat/sync-request-pre-sick.json` und `sync-response-pre-sick.json` als **wortgleiche Kopien** der heutigen `sync-request.json`/`sync-response.json`, im ersten Commit dieses Tasks.
  - `src/mobile_sick.py`, `tests/test_mobile_sick.py`
- Modify:
  - `src/mobile_sync.py`: `SyncRequest.sick`, `parse_request`, `perform_sync`, `build_response`.
  - `src/mobile_routes.py`: `MobileContext.sick_store: Any = None`, `vacation_store: Any = None`; an `perform_sync`.
  - `src/ui.py`: Kontext der Handy-Instanz.
  - `pwa/test/fixtures/sync-request.json`, `sync-response.json`: Live-Fixtures mit `sick` und `sick_days`.
  - `tests/test_mobile_contract.py`, `tests/test_mobile_sync.py`, `tests/test_type_annotations.py`.
  - `src/CLAUDE.md`: `mobile_sync.py`. `CLAUDE.md`: Struktur, `mobile_sick.py`.

**Interfaces:**
- Produces, in `src/mobile_sick.py`:
  - `MAX_SICK_DAYS = 400`
  - `class SickError(Exception)` mit `message`.
  - `parse_sick(raw: object, *, now_dt: datetime.datetime, parse_utc: Callable[[object], datetime.datetime | None], skew_limit: datetime.timedelta) -> dict[str, dict[str, Any]]`:
    - Ein Tag ist `{modified_at, deleted, minutes?}`; `minutes` ist eine ganze Zahl 0–1440 oder fehlt.
    - Unbekannte Felder, ein ungültiges Datum, ein Datum außerhalb von `check_date_range` und ein Stempel mehr als 15 Minuten in der Zukunft sind ein `SickError`.
    - Die Meldung beginnt mit `"Krankheit YYYY-MM-DD: …"` (Muster `"Reservierung …"`, damit die PWA den Tag zuordnet).
  - `phone_records(parsed: Mapping[str, Mapping[str, Any]], *, desktop_raw: Mapping[str, SickDay], computed: Mapping[str, int], device_id: str, floor: str) -> dict[str, SickDay]`:
    - Für einen Tombstone gilt `minutes` 0.
    - Ein lebender Tag ohne `minutes` behält die Minuten eines lebenden Desktop-Tags, sonst gilt `computed[date]`.
    - `modified_at = max(stamp, floor)`; `device_id` kommt aus dem Token.
  - `build_sick(raw: Mapping[str, SickDay], *, first: str, last: str, sent: Iterable[str]) -> dict[str, dict[str, Any]]`: Form `{ISO: {minutes, modified_at, deleted}}` im Fenster plus die gesendeten Tage.
- Produces, in `src/mobile_sync.py`:
  - `SyncRequest.sick: dict[str, dict[str, Any]]`, Vorgabe leer.
  - `parse_request` liest `"sick"` immer und macht aus `SickError` `SyncError(422, "invalid_entry", …)`.
  - `perform_sync(..., sick_store=None, vacation_store=None)`, unter `data_lock` und **vor** `merge_phone`:
    - `computed` aus `sick_plan.prefill` je lückenloser Folge der Handy-Tage ohne Minuten.
    - Eingaben: `basis = settings["sick_hours_basis"]`, Reservierungen aus `reservation_store.get_all()` (nur bei `reservations_active`), Einträge `storage.get_all()` und `vacation_store.day_minutes()` (oder `{}`).
    - `_phone_doc` bekommt `"sick": phone_records(...)` nur bei nicht leerem `request.sick`.
    - `build_local_doc`/`apply_merged_doc_journaled` mit `sick_store`.
  - `build_response(..., sick: Mapping[str, Any] | None = None)`. Ist es gesetzt, kommen dazu:
    - `response["sick_days"] = True` (Fähigkeit),
    - `response["sick"] = dict(sick)`.
  - `perform_sync` setzt es, sobald `sick_store` da ist, über `build_sick` mit demselben Fenster wie die Einträge (`first` aus dem gewährten Fenster, `last = heute + WINDOW_AHEAD_DAYS`). Der Block zählt nicht ins Mengenbudget von `fit_window`.

- [ ] **Step 1: Fixtures einfrieren und committen** (`test(handy): Formen vor den Krankheitstagen einfrieren`).
- [ ] **Step 2: Failing tests**
  - `test_request_without_sick_is_accepted`: `compat/sync-request-pre-sick.json` geht durch `parse_request`.
  - `test_parse_sick_rejects_bad_minutes_future_stamp_and_unknown_field`: jeweils 422 `invalid_entry`, Meldung beginnt mit `"Krankheit 2026-"`.
  - `test_desktop_fills_missing_minutes_from_standard`
  - `test_desktop_keeps_minutes_of_existing_sick_day`
  - `test_sick_minutes_come_from_reservation_deleted_in_same_request`: Reservierung 09:00–13:00 am Desktop; die Anfrage trägt `sick` für diesen Tag **und** den Reservierungs-Tombstone. Ergebnis: der Tag hat 240 Minuten, die Reservierung ist gelöscht.
  - `test_phone_stamp_raised_to_last_pull_plus_one`
  - `test_phone_sick_day_over_worktime_is_accepted_and_capped` (Review Focus 5): Ist-Zeit 120 am Tag; der Abgleich antwortet 200; `api_summary.summarize(..., sick_days=store.day_minutes())` liefert `sick_capped_days` mit `counted_minutes == minutes − 120`.
  - `test_response_carries_capability_and_window_days`
  - `test_response_without_sick_store_has_no_capability`
  - In `tests/test_mobile_contract.py`: die Live-Fixtures tragen `sick_days: true` und `sick`; der Gegentest mit `compat/sync-response-pre-sick.json` nach dem Muster der vorhandenen `pre-*`-Tests.
- [ ] **Step 3:** `.venv/bin/python -m pytest tests/test_mobile_sick.py tests/test_mobile_sync.py tests/test_mobile_contract.py -q`. Erwartet: FAIL.
- [ ] **Step 4:** Implementieren.
- [ ] **Step 5:** Volle Suite, dazu `cd pwa && node --test`: die PWA liest die geänderten Live-Fixtures. Erwartet: PASS.
- [ ] **Step 6: Commit** `feat(krank): Krankheitstage im Handy-Abgleich (Desktop-Seite)`.
- [ ] **Step 7: PR-Abschluss.**

---

## PR 7: PWA (Branch `feat/krank-7-pwa`)

Vor dem Start `pwa/CLAUDE.md` lesen: Kompatibilität (Regel 2, Feature-Erkennung), Reservierungen, Debug-Protokoll, `log-scrub`.

### Task 17: Logik, Speicher und Abgleich

**Files:**
- Create: `pwa/sick.js` (`// @ts-check`), `pwa/test/sick.test.js`
- Modify:
  - `pwa/sync.js`: `parseSyncResponse`, `_runOnce`.
  - `pwa/sync-errors.js`: die Regex nimmt `Krankheit ` auf, `dayKind: 'sick'`.
  - `pwa/store.js`: Meta und Methoden.
  - `pwa/test/store.test.js`, `pwa/test/sync.test.js`, `pwa/test/compat.test.js`.

**Interfaces:**
- Produces:
  - `sick.js`:
    - `parseSickBlock(raw: unknown) -> Record<string, {minutes: number, modified_at: string, deleted: boolean}> | null`: Fremddaten, kaputte Tage entfallen.
    - `sickRange(from: string, to: string) -> string[]`
    - `blockOf(days: Record<string, {deleted: boolean}>, date: string) -> {from: string, to: string, dates: string[]} | null`: nur lebende, lückenlose Tage.
    - `workBlockedDates(dates: string[], getDay: (d: string) => any) -> string[]`
    - `reservationDatesIn(dates: string[], getReservation: (d: string) => any) -> string[]`
  - `parseSyncResponse(raw)` ergibt zusätzlich `sick_days: raw.sick_days === true` und `sick: raw.sick_days === true ? parseSickBlock(raw.sick) : null`.
  - Meta (`@typedef Meta`):
    - `sick_capable: boolean`, Vorgabe `false`.
    - `sick: Record<string, SickRecord>`, Vorgabe `{}`.
    - `SickRecord = {minutes: number | null, modified_at: string, deleted: boolean, dirty_version: number, synced_version: number, error: string | null}`.
  - Store:
    - `markSick(from: string, to: string) -> Promise<void>`
    - `clearSick(dates: string[]) -> Promise<void>`: Ein Tag mit `synced_version` 0 wird nur lokal verworfen.
    - `sickDays() -> Record<string, SickRecord>`
    - `snapshotSick() -> {sick: Record<string, {modified_at: string, deleted: boolean}>, sickVersions: Record<string, number>}`: nie mit `minutes`.
    - `markSickError(date, message, version)`
  - `applyResponse`:
    - Bestätigt gesendete Tage.
    - Ersetzt nicht-dirty Tage durch `parsed.sick`.
    - Räumt außerhalb des Fensters wie bei den Einträgen.
    - Setzt `sick_capable = parsed.sick_days`.
    - Lokal Gespeichertes wird ohne Fähigkeit **nie** gelöscht.
  - `_runOnce`: `sick` geht nur im ersten Päckchen und nur bei `meta.sick_capable` mit nicht leerem Snapshot hinaus. Ein `invalid_entry` mit `dayKind === 'sick'` ruft `markSickError`.

- [ ] **Step 1: Failing tests**
  - `parseSickBlock` mit Fremddaten.
  - `blockOf` über den Monatswechsel.
  - `markSick`, dann Snapshot ohne `minutes`.
  - Ohne `sick_capable` wird nichts gesendet und nichts gelöscht.
  - Eine Antwort mit `sick` bestätigt und übernimmt.
  - Die `pre-sick`-Antwort lässt die Meta ohne Fähigkeit.
  - `classifyHttpError` mit „Krankheit 2026-03-02: …“ ergibt `dayKind 'sick'`.
  - `clearSick` auf einen nie gesyncten Tag verwirft lokal.
- [ ] **Step 2:** `cd pwa && node --test`. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren. Der Speicher liegt in der Meta, ohne IndexedDB-Upgrade (`db.js` `VERSION` bleibt 2).
- [ ] **Step 4:** `cd pwa && node --test && npm run typecheck`. `sick.js` trägt `// @ts-check`, die `tsconfig`-Liste wächst, wenn nötig. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(pwa): Krankheitstage speichern und abgleichen`.

### Task 18: Oberfläche

**Files:**
- Modify:
  - `pwa/view-model.js`:
    - `weekModel` gibt je Tag `sick: {minutes: number | null} | null` aus.
    - `editLock` sperrt einen Krankheitstag: Text „An diesem Tag bist du krank gemeldet.“ und die Aktion „Krankheit entfernen“.
    - Neu ist `sickDialogModel({date, today, meta, getDay, getReservation})`. Es liefert das späteste Bis-Datum (Fensterende), die Sichtbarkeit des Reservierungs-Häkchens und die Ist-Zeit-Sperre.
  - `pwa/views.js`: Zeile „krank“ und Stunden in `dayRow`; `sickDialog(...)` mit Bis-Datum und Häkchen „Reservierungen in diesem Zeitraum löschen“ (Vorgabe an); der Knopf „Krank melden“ im Tages-Editor.
  - `pwa/app.js`: Verdrahtung.
    - Speichern: `markSick`, mit Häkchen `clearReservation` je Tag, dann Abgleich anstoßen.
    - Entfernen: Bestätigung, dann `clearSick(block.dates)`.
  - `pwa/app.css`: Krankheitsfarbe.
  - `pwa/test/view-model.test.js`, `pwa/test/contrast.test.js`, `pwa/test/layout.test.js` (falls betroffen).

- [ ] **Step 1: Failing tests**
  - `weekModel` markiert Krankheitstage.
  - `editLock` sperrt Arbeitszeit an Krankheitstagen.
  - `sickDialogModel`: Bis-Datum nicht hinter dem Fensterende; Häkchen nur bei Reservierungen am Desktop und im Zeitraum; Sperre bei Ist-Zeit.
  - Außerhalb des Fensters gesperrt (#273).
  - Kontrast der neuen Farbe.
- [ ] **Step 2:** `cd pwa && node --test`. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren. Kein Krankheitsdatum ins Debug-Protokoll, die Positivliste in `log-scrub` bleibt unverändert.
- [ ] **Step 4:** `cd pwa && node --test && npm run typecheck`, dazu biome auf dem Export. Browser-Test mit `python scripts/pwa_devserver.py`:
  - Krank melden mit und ohne Reservierungen.
  - Ein Desktop ohne Fähigkeit, nachgestellt mit einem älteren Fixture.
  - „Krankheit entfernen“.
  - Gesperrte Arbeitszeit.
- [ ] **Step 5: Commit** `feat(pwa): Krankheit melden und anzeigen`.

### Task 19: Doku und Gesamtprüfung

**Files:**
- Modify:
  - `pwa/CLAUDE.md`: Abschnitt „Krankheitstage“ (Fähigkeit, Meta-Speicher, kein `minutes` auf dem Draht, Reservierungs-Tombstones im selben Abgleich).
  - `README.md`: die Zeile aus Task 10 um das Handy ergänzen.
  - `tests/test_pwa_claude_md_claims.py`, wenn eine Behauptung dazukommt.

- [ ] **Step 1:** Doku schreiben.
- [ ] **Step 2:** Alle Prüfungen der Global Constraints (Python und PWA). Erwartet: alles grün.
- [ ] **Step 3: Commit** `docs(krank): PWA-Doku und README`.
- [ ] **Step 4: PR-Abschluss.** Dieser PR trägt `Closes #521`.

---

## Nach den sieben PRs (nur nach Rückfrage)

- Pre-Release über alle drei Plattformen plus Android und iOS (`release.yml`, Häkchen `prerelease`).
- Prüfliste als eigenes Issue nach dem Muster #267/#487:
  - Sync zwischen neuem und altem Desktop.
  - Alte PWA mit neuem Desktop.
  - Bericht und Webhook mit und ohne Häkchen.
  - macOS-✕.
  - Handy mit Reservierungen.
- Im Release-PR: CHANGELOG-Abschnitt, `python scripts/resolve_readme_version.py`, Label `release:minor`.
