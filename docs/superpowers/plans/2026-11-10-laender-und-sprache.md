# Land, Region und Sprache — Implementierungsplan (Teil 1: Kern und PWA)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land/Region als Codes, ein Locale für Datum/Zeit und eine Textschicht samt eigener Sprach-Einstellung in der PWA — Text bleibt deutsch, Verhalten für `DE` bitgleich.

**Architecture:** Desktop: `holidays_region` (Codes statt Labels) plus einmalige gerätelokale Migration `state` → `country`/`region`; ein Locale-Formatierer für Datumsanzeige. Abgleich und Kopplung reichen `country` und `language` additiv durch (`PROTOCOL` bleibt 2). PWA: `i18n.js` mit Katalog `i18n/de.js`, eigener Sprach-Einstellung (beim Koppeln vom Desktop übernommen) und Locale-Formatierer; ein Ratschen-Test verbietet neue deutsche Literale in schon umgestellten Dateien.

**Tech Stack:** Python 3.12 (`holidays==0.99`, pytest), PWA in reinem JavaScript (`node --test`, JSDoc/`@ts-check`).

**Spec:** `docs/superpowers/specs/2026-11-10-laender-und-sprache-design.md`

**Nicht in diesem Plan** (eigene Pläne, wenn dieser durch ist — beide brauchen vorher eine Inventur, die hier noch nicht seriös planbar ist): Desktop-Textschicht samt Aufbrechen der großen Dialoge (Stufe 3) und Länder-Beschriftung des Arbeitsrechts (Stufe 5). Der Integrations-Branch geht erst mit ihnen nach `master`.

## Global Constraints

- Alle Stack-PRs zielen auf den Integrations-Branch, nie auf `master`; kein Versionsbump, kein CHANGELOG, kein `release:*`-Label, kein `--VERSION--`-Platzhalter (Spec, „Entscheidungen").
- Text bleibt **deutsch**; Verhalten, Berichte, Summen und API-Antworten für `country="DE"` bitgleich (Spec, Anti-Ziel).
- ISO bleibt intern (Storage-Keys, Sync-Doc, gcal-Payloads); nur Anzeige ändert sich.
- `state` bleibt in den Settings stehen; `country` ist nie leer (Default `"DE"`); `region == ""` heißt „kein Bundesland" (Spec, „Annahmen").
- Neue Abgleich-Felder sind additiv, `PROTOCOL` bleibt 2; fehlen sie, gilt `DE`/`de` bzw. `de-DE`.
- `country`, `region`, `language` sind gerätelokal, **nicht** in `SYNCED_SETTING_KEYS`.
- Catch-all-Handler loggen oder begründen (`tests/test_catch_all_handlers.py`); Kommentare sagen das Warum, keine Historie.
- Tk-freie Module mit Whitelist-Eintrag in `tests/test_type_annotations.py` tragen volle Annotationen und `# pyright: reportOptionalMemberAccess=true`.
- Der Retry gegen #116/#37 (`OSError` beim Laden der Übersetzung) bleibt für den neuen Einstieg erhalten.

## Review Focus

Eingaben, die kein Task der Spec ausdrücklich nennt; jede Zeile hat unten ihren Test im besitzenden Task.

1. Beschädigter `state` (Nicht-String, `"XX"`, `None`) → `region == ""`, keine Ausnahme (Task 2).
2. Ein Gerät, das schon migriert wurde, überschreibt `region` nie erneut aus `state` (Task 2).
3. PWA gegen alten Desktop ohne `language`/`country`: `de`/`DE`, und eine bereits gewählte PWA-Sprache wird beim Koppeln nicht überschrieben (Tasks 7, 10).
4. Unbekannter oder kaputter Locale-Tag (`"xx"`, `""`, `"de_DE"`): Fallback `de-DE`, kein `RangeError` aus `Intl` (Tasks 6, 9).
5. Strenge API-Clients: `/v1/holidays` liefert `state` unverändert weiter (Task 5).

---

## Korrekturen aus dem Review (verbindlich — bei Widerspruch gilt dieser Block vor den Task-Texten)

Ein unabhängiges Review gegen den Code hat die folgenden Punkte belegt. Neue Entscheidungen sind als **[E]** markiert und in der Übergabe an den Nutzer aufgeführt.

**Ausführungsreihenfolge:** Task 1, 2, **4, 3**, 5, 6, 7, 8, 9, 10, 11–14, 15. Der Dialog (Task 4) schreibt zuerst `country`/`region` **und** `state`; danach stellt Task 3 die Leser um. So ist jeder PR allein grün.

**Allgemein (alle Tasks):** Jeder Task nennt Tests und Fixtures, die er anfasst; vor dem Commit läuft die **ganze** Suite (`pytest`, in der PWA `cd pwa && node --test && npm run typecheck`). Brechende Alt-Tests werden im selben PR angepasst, aber nur dort, wo sich der Vertrag bewusst ändert.

- **[E] `state` wird beim Speichern mitgeschrieben**, solange `country == "DE"` (`state = region`). So zeigt ein Downgrade die aktuelle Region (Spec-Annahme „bleibt stehen" wird zu „bleibt aktuell"). `region_migrated` und der Test „Region ändert `state` nicht" in Task 4 entfallen bzw. kehren sich um (`test_saving_region_mirrors_state_for_de`).
- **[E] Alias in `/v1/holidays`:** `state` ist `region` **normalisiert**; ein roher unbekannter Wert (`"XX"`) kommt nur aus beschädigten Settings und wird zu `""`. Für gültige Werte bitgleich. `tests/test_api_summary.py:82–86` wird entsprechend angepasst.
- **[E] PWA-Textumfang:** Alle **Nutzertexte** wandern in den Katalog, in jeder Datei. **Log-Kontexte** (erstes Argument von `logFailure(...)` und `this._log(...)`), Protokoll-/Krypto-Fehlertexte (`crypto.js`, `relay-frame.js`, `db.js`) und `console`-Ausgaben bleiben deutsch und sind ausgenommen (analog zur Spec für den Desktop).

**Task 1 (zusätzlich):** `scripts/demo_data.py:47` (Import) und `:172` (schreibt `country`/`region` statt `state`), `tests/test_demo_data.py`, `tests/test_tab_rules.py:7,28,116` (importiert `STATES`), `tests/test_type_annotations.py:116` (Whitelist-Eintrag `src/holidays_region.py`), Retry-Tests `tests/test_holidays_de.py:97,115` (patchen künftig `holidays.country_holidays`), Namensnennungen in `CLAUDE.md:935,1616`, `src/CLAUDE.md:753`, `CONTRIBUTING.md:177`, `src/settings.py:251`, `src/updater.py:55`, `src/send_reminder.py:104`. Der Satz zu `test_claude_md_claims.py` entfällt. **[E] Die Regel „leerer Code = keine Feiertage" gilt je Land** (`REGIONS`-Eintrag `""` markiert es); ein Land ohne Unterteilung bekäme Feiertage.

**Task 2:** `migrate_state(settings: _Writable)` mit einem eigenen `Protocol` (`get`, `set_many`) statt `SettingsLike`; Tests bauen ein echtes `Settings(tmp_path)` wie `tests/test_dpi.py:_settings`, keinen `FakeSettings`. Zusätzlich `region.normalize_language(value: object) -> str` und `normalize_country(value: object) -> str` (Task 7 braucht sie getrennt).

**Task 4 (korrigiert):** Die Funktion heißt `tab_rules.work_updates(raw, old)` (`tab_rules.py:93`), Tests in `tests/test_tab_rules.py` (nicht `test_settings_dialog.py`). Es brechen und werden angepasst: `test_work_updates_carries_state_and_weekend` (Z. 114) und `test_tabs_together_write_exactly_the_legacy_keys` (Z. 327, `_legacy_keys_base` Z. 306: Schlüsselmenge `country`, `region`, `state`). Neuer Test: `test_saving_region_mirrors_state_for_de`.

**Task 3 (erweitert):**
- Durchreich-Funktionen bekommen `country: str = "DE"` als Keyword **nach** `state`-losem Muster, d. h. der Parameter `state` heißt künftig `region`, `country` kommt als Keyword mit Default: `vacations._holiday_dates`/`expand_days` (`vacations.py:54,65`), `vacation_plan.plan_vacation_save` (`vacation_plan.py:29`; Aufrufer `api_routes.py:554`, `vacation_dialog.py:316`), `send_reminder.free_dates_for_month` (Z. 99), die Funktion bei `send_reminder.py:198`, `monthly_anchor_dates` (Aufrufer `send_dialog.py:104`, `send_reminder_scheduler.py:96`). `vacations.py` und `vacation_plan.py` gehören in die Files.
- Der AST-Test beschränkt sich auf Empfänger `settings`, `_settings`, `ctx.settings`; erlaubt bleiben nur `src/region.py` und `src/dialogs/settings_dialog/tab_rules.py` (schreibt `state`, K1). `api_summary.py` ist **nicht** ausgenommen (der Alias ist ein Ausgabefeld, kein Lesen).
- Fixtures mit `{"state": …}` ziehen auf `country`/`region` um: `tests/test_api_summary.py:66–86`, `tests/test_api_routes.py:789–796`, `tests/test_api_vacations.py:30,111`, `tests/test_send_reminder.py:299`, `tests/test_send_reminder_scheduler.py:21`, `tests/test_period_picker.py:83,95`.

**Task 5:** zusätzlich `tests/test_api_routes.py` (exakter Body-Vergleich `{"year","state","country","region","holidays"}`); `holidays_for` reicht `settings["language"]` (normalisiert) als `language` an `get_holidays` durch (K6).

**Task 6 (erweitert):** Tabelle enthält Langmuster, Kurzmuster ohne Jahr (`get_week_label:174`, `grid_renderer.py:889` `f"{day}.{month}."`) und Wochentagsnamen (`format_iso_weekday_date`, `WEEKDAYS_DE_FULL`). Die Inventur sucht zusätzlich `\.month\}|\.day\}`.

**Task 7 (korrigiert):** Der einzige Aufrufer von `desktop_info` ist `mobile_routes.py:372`; `:260` ist die Kopplungsantwort. Bereinigung über `normalize_language`/`normalize_country` (Task 2), nicht `locale_for`. Pflicht-Anpassungen: `tests/test_mobile_contract.py:155,234` (exakter `shape(...)`-Vergleich), `pwa/test/fixtures/sync-response.json` (Block `desktop`) und `pair-response.json`, `tests/test_mobile_sync.py:196` (`DESKTOP`). Nach `pwa/CLAUDE.md` Regel 4 (Z. 181–198) wird der Vorgänger der Antwort **vor** der Änderung nach `pwa/test/compat/` eingefroren (`compat.test.js`, Doku); für die Kopplungsantwort gibt es noch keinen eingefrorenen Stand, er wird angelegt.

**Task 8 (korrigiert):**
- **Schritt 0 — Inventur per Skript** (`scripts/` oder einmalig im Test): listet je `pwa/*.js` die Nutzertexte. `PENDING` enthält **jede** Datei mit Treffern, mindestens `sync.js`, `lock.js`, `minutes.js`, `store.js`, `relay-transport.js`, `relay-client.js`, `update-policy.js`, `vault.js`, `sw-repair.js`, `push-policy.js`, `unpair.js` zusätzlich zur bisherigen Liste; Tasks 11–14 erhalten diese Dateien (Zuschnitt nach Inventur: je Task höchstens eine große Datei oder drei kleine).
- Ratsche: **kein** Umlaut-Filter. Für nicht mehr in `PENDING` stehende Dateien gilt: außer in `t(`, `logFailure(`, `this._log(` und einer expliziten, kommentierten Erlaubnisliste kein String-Literal mit Leerzeichen oder Großbuchstaben am Anfang. Die Literal-Erkennung ist ein kleiner Tokenizer im Test (Kommentare, Template-Strings, Apostrophe in Kommentaren beachten), keine neue Abhängigkeit (`pwa` läuft ohne `npm ci`). Schlüssel dürfen nur als Literal übergeben werden (`t('…')`, keine dynamischen Schlüssel).
- `./i18n.js` und `./i18n/de.js` gehören **zwingend** in `PRECACHE` (`pwa/sw-core.js`), sonst bricht `pwa/test/shell.test.js:33–38`. `<html lang="de">` bleibt im HTML (`shell.test.js:120` verlangt es, Inline-Skripte sind verboten); `lang` wird nur zur Laufzeit gesetzt.
- Prüfen gegen `pwa/test/log-contexts.test.js` (verlangt Text-Literale in `logFailure`-Kontexten; die Ratsche nimmt sie aus).

**Task 9 (korrigiert):** `Intl.DateTimeFormat.supportedLocalesOf` wirft bei `'de_DE'`, `''`, `'xx-ZZZ'`, `'-'`, `'de-'` selbst `RangeError` (in Node gemessen). `localeTag` prüft per Regex `^[a-z]{2,3}(-[A-Z]{2})?$` **und** `try/catch` um `Intl`. Die gemeinte Funktion heißt `localTime` (`view-model.js:62–66`), nicht `formatTime`. `view-model.js:122` (`formatDateDe(...).slice(0, 6)`) und `WEEKDAYS` (Z. 18) hängen am deutschen Muster und kommen mit: Kurzdatum über den Formatierer, Wochentage in den Katalog. `pwa/sw-core.js`: `./locale.js` in `PRECACHE`.

**Task 10 (korrigiert):** Die Kopplungsantwort liest `pwa/sync.js` (`_pairExchange` Z. 262–276, `pairingMeta` Z. 152–155), nicht `pairing.js`; Tests in `pwa/test/sync.test.js`. `desktop.country`/`language` fallen heute in `pwa/defaults.js:75–79` (`parseDesktopInfo`) weg — `defaults.js` und `defaults.test.js` gehören in den Task, ebenso `store.js:38` (Typedef) und `:614`.

**Task 14 (ergänzt):** `push-message.js` läuft im Service Worker (`sw.js:8`), mit eigener Modulinstanz und ohne `document`. **[E]** Der Service Worker liest die Sprache aus der Meta in IndexedDB beim Start eines Push-Handlers (`getLanguage` aus dem Store); Fallback `de`. Ist das aufwändig, bleibt es als dokumentierte Grenze in `pwa/CLAUDE.md` (Entscheidung beim Bauen, im PR zu begründen).

**Task 15 (ergänzt):** `tests/test_pwa_claude_md_claims.py`, `CONTRIBUTING.md:177`.

---

## PR 1 — Land/Region-Modul

### Task 1: `holidays_region` ersetzt `holidays_de`

**Files:**
- Rename: `src/holidays_de.py` → `src/holidays_region.py`; `tests/test_holidays_de.py` → `tests/test_holidays_region.py` (`git mv`)
- Modify: alle Importe von `src.holidays_de` (`vacations.py`, `api_summary.py`, `grid_renderer.py`, `send_reminder.py`, `vacation_dialog.py`, `entry_dialog.py`, `tab_work.py`, `tab_rules.py`) — in diesem Task nur der Modulname, nicht die Signatur
- Test: `tests/test_holidays_region.py`

**Interfaces:**
- Produces (`src/holidays_region.py`):
  - `COUNTRIES: list[tuple[str, str]]` = `[("DE", "Deutschland")]`
  - `REGIONS: dict[str, list[tuple[str, str]]]` — `"DE"` trägt die heutige `STATES`-Liste (inkl. `("", "— kein Bundesland —")`)
  - `region_label(country: str, region: str) -> str` (Anzeige, `""` bei Unbekanntem)
  - `normalize_region(country: str, region: object) -> str` — gültiger Code oder `""`
  - `get_holidays(country: str, region: str, year: int, language: str = "de") -> dict[date, str]`
- Entfällt: `code_for_state_label`, `STATES` (Aufrufer in Task 3/4 umgestellt; bis dahin delegiert ein dünner Alias nicht — Task 1 stellt die Aufrufer selbst um, siehe Step 4)

- [ ] **Step 1: Failing tests** in `tests/test_holidays_region.py` (die vorhandenen Tests mitnehmen, Aufrufe auf `get_holidays("DE", code, year)`), neu:
  - `test_get_holidays_matches_germany_for_every_region`: für jede `REGIONS["DE"]`-Region mit Code gilt `get_holidays("DE", code, 2026) == dict(holidays.Germany(subdiv=code, years=2026, language="de"))`
  - `test_empty_or_unknown_region_gives_no_holidays`: `get_holidays("DE", "", 2026) == {}`, `("DE", "XX", 2026) == {}`, `("FR", "BY", 2026) == {}`
  - `test_normalize_region`: `normalize_region("DE", "BY") == "BY"`, `("DE", "XX") == ""`, `("DE", None) == ""`, `("DE", 5) == ""`
  - `test_region_label`: `region_label("DE", "BY") == "Bayern"`, `region_label("DE", "") == "— kein Bundesland —"`
  - `test_oserror_retry_still_applies`: `holidays.country_holidays` per `monkeypatch` zweimal `OSError`, dann Erfolg → Ergebnis nicht leer; dreimal `OSError` → `{}` (Muster der bisherigen Retry-Tests)
- [ ] **Step 2:** `pytest tests/test_holidays_region.py -v` → FAIL (Modul fehlt)
- [ ] **Step 3: `git mv`, dann implementieren.** `_holidays_cached(country, region, year, language)` ruft `holidays.country_holidays(country, subdiv=region, years=year, language=language)`, Retry-Schleife unverändert. `get_holidays` liefert `{}` für `region not in` gültige Codes des Landes (ein leerer Code ist **kein** gültiger Code — heutiges Verhalten).
- [ ] **Step 4: Aufrufer anpassen**, so wenig wie möglich: jeder bisherige `get_holidays(state, y)` wird `get_holidays("DE", state, y)`; `tab_work` nutzt `REGIONS["DE"]` statt `STATES`, `tab_rules` ersetzt `code_for_state_label` durch eine Rückabbildung über `REGIONS["DE"]` (Label → Code, nur an dieser Stelle; Task 4 ersetzt sie durch Codes).
- [ ] **Step 5:** `pytest` (ganze Suite) → alle grün. `tests/test_claude_md_claims.py` prüfen, falls es den Modulnamen kennt.
- [ ] **Step 6: Commit** `refactor(feiertage): holidays_region mit Land und Region als Codes`

---

## PR 2 — Settings und Migration

### Task 2: `country`/`region` in den Settings, einmalige Migration

**Files:**
- Modify: `src/settings.py` (Defaults), `src/main.py:388` (neben `dpi.migrate_ui_scale(settings)`)
- Create: `src/region.py`
- Test: `tests/test_region.py`, `tests/test_settings.py`
- Modify: `tests/test_type_annotations.py` (Whitelist)

**Interfaces:**
- Consumes: `holidays_region.normalize_region`, `Settings.get/set_many`
- Produces (`src/region.py`):
  - `MIGRATED_KEY = "region_migrated"`
  - `country_region(settings: SettingsLike) -> tuple[str, str]` — liest `country` (ungültig/leer → `"DE"`) und `region` (über `normalize_region`)
  - `migrate_state(settings: SettingsLike) -> bool` — True, wenn migriert wurde
- Settings-Defaults: `"country": "DE"`, `"region": ""`, `"region_migrated": False` (alle gerätelokal, mit Kommentar warum)

- [ ] **Step 1: Failing tests** (`tests/test_region.py`, `FakeSettings`-Dict im Stil von `tests/test_dpi.py`):
  - `test_migrate_copies_valid_state`: `{"state": "BY"}` → `country == "DE"`, `region == "BY"`, Marker True, `state` weiter `"BY"`
  - `test_migrate_garbled_state_gives_empty_region` (**Review Focus 1**): parametrisiert `"XX"`, `None`, `5`, `["BY"]` → `region == ""`, keine Ausnahme, Marker True
  - `test_migrate_runs_only_once` (**Review Focus 2**): nach der Migration `state` auf `"HH"` ändern, `migrate_state` erneut → `region` bleibt `"BY"`, Rückgabe False
  - `test_country_region_defaults`: leere Settings → `("DE", "")`; `{"country": "ZZ"}` → `("DE", "")`
  - `test_new_keys_are_device_local`: keiner der drei Keys steht in `SYNCED_SETTING_KEYS`
- [ ] **Step 2:** `pytest tests/test_region.py -v` → FAIL
- [ ] **Step 3: Implement** `src/region.py` (kein Tk, volle Annotationen, Whitelist-Zeile) und die Defaults; `main.py` ruft `region.migrate_state(settings)` direkt nach `dpi.migrate_ui_scale(settings)`.
- [ ] **Step 4:** `pytest tests/test_region.py tests/test_settings.py tests/test_type_annotations.py -v` → PASS
- [ ] **Step 5: Commit** `feat(einstellungen): country und region, einmalige Migration aus state`

---

## PR 3 — Aufrufer lesen Land und Region

### Task 3: alle `settings.get("state")`-Leser auf `country_region`

**Files:**
- Modify: `src/grid_renderer.py` (2 Stellen), `src/dialogs/entry_dialog.py`, `src/dialogs/send_dialog.py`, `src/dialogs/vacation_dialog.py`, `src/send_reminder.py` (`monthly.get("state", "")`), `src/send_reminder_scheduler.py`, `src/mobile_reminders.py`, `src/api_routes.py`, `src/api_summary.py`
- Test: je vorhandene Testdatei des Moduls; neu `tests/test_state_readers.py`

**Interfaces:**
- Consumes: `region.country_region(settings) -> tuple[str, str]`, `get_holidays(country, region, year)`
- `send_reminder`/`mobile_reminders` tragen heute `"state"` in einem Dict (`monthly`); es bekommt zusätzlich `"country"` (Lesen über `.get("country", "DE")`, damit ältere Dicts weiterlaufen).

- [ ] **Step 1: Failing test** `test_no_module_reads_state_key_directly`: AST-Scan über `src/**/*.py` nach `.get("state")`/`["state"]` auf Settings-artigen Objekten; erlaubt sind nur `src/region.py`, `src/api_summary.py` (Alias, Task 5) und `src/dialogs/settings_dialog/google_tab_task.py`/`tab_google.py` (anderer Begriff). Plus pro Modul ein Test, dass `{"country": "DE", "region": "BY"}` (ohne `state`) dieselben Feiertage liefert wie vorher `{"state": "BY"}`.
- [ ] **Step 2:** → FAIL
- [ ] **Step 3: Umstellen.** Jede Stelle holt `country, region = country_region(settings)` und ruft `get_holidays(country, region, year)`; kein Verhalten ändert sich, `state` wird nicht mehr gelesen.
- [ ] **Step 4:** `pytest` → alle grün (Berichte, Urlaub, Erinnerungen bitgleich)
- [ ] **Step 5: Commit** `refactor(feiertage): Aufrufer lesen country und region statt state`

---

## PR 4 — Einstellungen-Dialog

### Task 4: Region per Code wählen, Hinweis zum Länderwechsel

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_work.py:44-58,220`, `src/dialogs/settings_dialog/tab_rules.py:27,114`
- Test: `tests/test_settings_dialog.py` (Tk-freier Teil in `tab_rules`)

**Interfaces:**
- Consumes: `REGIONS`, `COUNTRIES`, `region_label`
- Produces: `tab_rules.collect(...)` liefert `"country"` und `"region"` (Codes) statt `"state"`; die Auswahl hält Label-zu-Code **nur zur Anzeige** (Zuordnung aus `REGIONS`, nie aus dem übersetzten Text). Ein Land-Dropdown erscheint erst, wenn `len(COUNTRIES) > 1`.

- [ ] **Step 1: Failing tests:** `test_collect_returns_region_code` (Auswahl „Bayern" → `{"country": "DE", "region": "BY"}`, `"state"` nicht im Ergebnis); `test_unknown_label_gives_empty_region`; `test_changing_region_keeps_state_key_untouched` (gespeicherte Settings behalten `state`).
- [ ] **Step 2:** → FAIL
- [ ] **Step 3: Implement.** Der Hinweis unter dem Feld lautet: „Für Feiertage und Urlaub. Bereits angelegte Urlaube werden bei einem Wechsel nicht neu berechnet." (Spec, „Bekannte Grenzen").
- [ ] **Step 4:** `pytest tests/test_settings_dialog.py -v` → PASS; `tests/test_pixel_scaling.py` weiter grün
- [ ] **Step 5: Commit** `feat(einstellungen): Region per Code, Hinweis zum Wechsel`

---

## PR 5 — API additiv

### Task 5: `/v1/holidays` trägt `country` und `region` neben `state`

**Files:**
- Modify: `src/api_summary.py:holidays_for`, Doku-Zeile in `src/api_routes.py`
- Test: `tests/test_api_summary.py`

**Interfaces:** `holidays_for(settings, year)` liefert `{"year", "state", "country", "region", "holidays"}`; `state` ist exakt `region` für `country == "DE"` (Alias, **Review Focus 5**).

- [ ] **Step 1: Failing tests:** `test_holidays_keeps_state_alias` (bei `region="BY"` ist `state == "BY"`, `country == "DE"`, `region == "BY"`, `holidays` identisch zur bisherigen Liste); `test_holidays_without_region_is_empty_with_empty_state`.
- [ ] **Step 2:** → FAIL · **Step 3:** implementieren · **Step 4:** `pytest tests/test_api_summary.py tests/test_api_routes.py -v` → PASS
- [ ] **Step 5: Commit** `feat(api): holidays liefert country und region, state bleibt Alias`

---

## PR 6 — Locale auf dem Desktop

### Task 6: Datumsanzeige über ein Locale

**Files:**
- Create: `src/locale_format.py`
- Modify: `src/time_utils.py` (`format_date`, `format_iso_date`, `format_iso_weekday_date`, `format_iso_datetime`), `src/settings.py` (Default `"language": "de"`, gerätelokal), `src/main.py` (`locale_format.set_active(locale_for(language, country))` beim Start)
- Test: `tests/test_locale_format.py`, `tests/test_time_utils.py`
- Modify: `tests/test_type_annotations.py` (Whitelist)

**Interfaces:**
- Produces (`src/locale_format.py`): `DEFAULT_LOCALE = "de-DE"`; `locale_for(language: object, country: object) -> str` (Form `"de-DE"`, Ungültiges → `DEFAULT_LOCALE`); `date_pattern(locale: str) -> str` (strftime-Muster, unbekannt → Muster von `DEFAULT_LOCALE`); `set_active(locale: str) -> None`; `active() -> str`.
- `time_utils.format_date(d, locale: str | None = None)`, `format_iso_date(iso, fallback="—", locale=None)`, `format_iso_datetime(...)` und `format_iso_weekday_date(...)` nehmen optional ein Locale, sonst `active()`.

- [ ] **Step 1: Failing tests:** `test_locale_for_valid_and_invalid` (`("de","DE") == "de-DE"`; `("", "DE")`, `(None, None)`, `("xx", "ZZZ")`, `("de_DE", "")` → `"de-DE"`) (**Review Focus 4**); `test_unknown_locale_falls_back_to_default_pattern`; `test_format_iso_date_uses_given_locale` mit einem **künstlich** registrierten Muster (`monkeypatch` auf die Tabelle, `"%Y/%m/%d"`) — damit es vor dem zweiten echten Format etwas zu prüfen gibt; `test_default_output_unchanged` (`format_iso_date("2026-06-02") == "02.06.2026"`, `format_iso_datetime("2026-06-02T14:30:00Z") == "02.06.2026 14:30"`).
- [ ] **Step 2:** → FAIL · **Step 3:** implementieren (Tabelle `_PATTERNS = {"de-DE": "%d.%m.%Y"}`); eine Inventur-Suche (`grep -rn "strftime\|isoformat()" src` auf Anzeige-Stellen) wird als Liste in der PR-Beschreibung festgehalten, Fundstellen, die an den Helfern vorbeiformatieren, werden umgestellt.
- [ ] **Step 4:** `pytest` → grün · **Step 5: Commit** `feat(anzeige): Datumsformat über Locale aus Sprache und Land`

---

## PR 7 — Abgleich trägt Land und Sprache

### Task 7: `country` und `language` additiv in Kopplung und Abgleich

**Files:**
- Modify: `src/mobile_sync.py:desktop_info` (+ Aufrufer `src/mobile_routes.py:260,372`), die Kopplungsantwort in `src/mobile_routes.py`
- Test: `tests/test_mobile_sync.py`, `tests/test_mobile_routes.py`, `tests/test_mobile_contract.py`
- Fixture: `pwa/test/fixtures/` (Vertrags-Fixture der Antwort, falls dort `desktop` steht)

**Interfaces:** `desktop_info(name, version, system, *, language="de", country="DE") -> dict[str, str]` trägt zusätzlich `language` und `country`; die Kopplungsantwort trägt beide Felder (Quelle: `settings["language"]`, `region.country_region(settings)[0]`).

- [ ] **Step 1: Failing tests:** `test_desktop_info_carries_language_and_country`; `test_pair_answer_carries_language_and_country`; `test_older_pwa_ignores_new_fields` (die Antwort bleibt ein Superset der bisherigen Felder; `PROTOCOL == 2`).
- [ ] **Step 2:** → FAIL · **Step 3:** implementieren; ungültige Werte werden über `locale_format.locale_for` bereinigt, bevor sie ans Handy gehen (Fremddaten-Regel).
- [ ] **Step 4:** `pytest tests/test_mobile_*.py -v` → PASS · **Step 5: Commit** `feat(mobil): Abgleich und Kopplung tragen language und country (additiv)`

---

## PR 8 — PWA: Fundament

### Task 8: Textschicht `i18n.js` und Ratschen-Test

**Files:**
- Create: `pwa/i18n.js`, `pwa/i18n/de.js`, `pwa/test/i18n.test.js`, `pwa/test/i18n-literals.test.js`
- Modify: `pwa/index.html`, `pwa/datenschutz.html` (`lang` wird beim Start gesetzt), `pwa/sw-core.js` (neue Dateien in die Precache-Liste, falls dort geführt)

**Interfaces:**
- Produces (`pwa/i18n.js`, `@ts-check`): `DEFAULT_LANGUAGE = 'de'`; `normalizeLanguage(value: unknown): string`; `setLanguage(lang: string): void` (setzt auch `document.documentElement.lang`, wo ein `document` existiert); `getLanguage(): string`; `t(key: string, params?: Record<string, string | number>): string` — ersetzt `{name}`-Platzhalter, ein unbekannter Schlüssel liefert den **Schlüssel selbst** und meldet über `console.warn`.
- `pwa/i18n/de.js`: `export default { 'schlüssel.punktiert': 'Text mit {param}' }`.

- [ ] **Step 1: Failing tests:** `t` ersetzt Parameter und lässt unbekannte Platzhalter stehen; `normalizeLanguage('xx') === 'de'`, `(undefined) === 'de'`; `every key in de.js is used by some t('…') call and every t('…') key exists` (Scan über `pwa/*.js`); **Ratschen-Test** `i18n-literals.test.js`: liest alle `pwa/*.js` außer einer `PENDING`-Liste (zunächst `messages.js`, `view-model.js`, `views.js`, `app.js`, `categories.js`, `push-message.js`, `diagnose.js`, `privacy-view.js`, `i18n/de.js`) und schlägt an, wenn ein String-Literal Umlaute/ß enthält.
- [ ] **Step 2:** `cd pwa && node --test` → FAIL · **Step 3:** implementieren · **Step 4:** `node --test` und `npm run typecheck` → PASS
- [ ] **Step 5: Commit** `feat(pwa): Textschicht i18n mit Katalog und Ratschen-Test`

### Task 9: Locale-Formatierer statt `formatDateDe`/`'de-DE'`

**Files:**
- Create: `pwa/locale.js`, `pwa/test/locale.test.js`
- Modify: `pwa/minutes.js:formatDateDe` (bleibt als dünner Aufrufer des neuen Formatierers, Name unverändert, damit Task 11–14 nicht kollidieren), `pwa/view-model.js:65`

**Interfaces:** `localeTag(language: unknown, country: unknown): string` (Fallback `'de-DE'`, **nie** ein Wurf — `Intl` wirft `RangeError` bei kaputten Tags, deshalb Prüfung gegen `Intl.DateTimeFormat.supportedLocalesOf`); `setLocale(tag: string): void`; `formatDate(iso: string, tag?: string): string` — `de-DE` ergibt `TT.MM.JJJJ`.

- [ ] **Step 1: Failing tests:** `formatDate('2026-06-02') === '02.06.2026'`; `localeTag('xx','ZZZ')`, `('', '')`, `('de_DE', 'DE')` → `'de-DE'` (**Review Focus 4**); `formatTime`-Aufruf mit kaputtem Tag wirft nicht; bestehende `minutes.test.js`-/`view-model.test.js`-Erwartungen bleiben unverändert grün.
- [ ] **Step 2–4:** rot → implementieren → `node --test` grün · **Step 5: Commit** `feat(pwa): Locale-Formatierer für Datum und Zeit`

### Task 10: Eigene Sprach-Einstellung, Übernahme beim Koppeln

**Files:**
- Modify: `pwa/store.js` (Meta `language`, `country`), `pwa/pairing.js` (Kopplungsantwort lesen), `pwa/sync.js` (`desktop.country` aus der Abgleich-Antwort), `pwa/app.js`, `pwa/views.js` (Einstellungs-Zeile „Sprache", einzige Option vorerst Deutsch)
- Test: `pwa/test/store.test.js`, `pwa/test/pairing.test.js`, `pwa/test/sync.test.js`

**Interfaces:** `Meta.language: string | null` (`null` = nie gewählt), `Meta.country: string`; `adoptDesktopLanguage(meta, desktop)` setzt `language` **nur** wenn `meta.language === null`.

- [ ] **Step 1: Failing tests:** Kopplung gegen Desktop mit `language: 'de'` → `meta.language === 'de'`; Kopplung gegen **alten** Desktop ohne Felder → `'de'`/`'DE'` (**Review Focus 3**); zweite Kopplung überschreibt eine gewählte Sprache nicht; Abgleich mit `desktop.country` aktualisiert `meta.country`, nie `language`; Meta älterer Version (ohne Felder) lädt ohne Fehler.
- [ ] **Step 2–4:** rot → implementieren → `node --test`, `npm run typecheck` grün
- [ ] **Step 5: Commit** `feat(pwa): eigene Sprach-Einstellung, Übernahme beim Koppeln`

---

## PR 9–12 — PWA: Texte in den Katalog

### Tasks 11–14: je eine Datei(gruppe), immer nach demselben Muster

Reihenfolge nach Größe und Risiko: **11** `pwa/messages.js`; **12** `pwa/view-model.js`; **13** `pwa/views.js`; **14** `pwa/app.js` und die kleinen Dateien (`categories.js`, `push-message.js`, `diagnose.js`, `privacy-view.js`).

**Files je Task:** die genannte Datei, `pwa/i18n/de.js`, `pwa/test/i18n-literals.test.js` (Datei aus `PENDING` streichen), die zugehörige Testdatei.

**Regeln (gelten für jeden dieser Tasks):**
- Zusammengesetzte Sätze werden **ein** Schlüssel mit Parametern (`offlineText`: `t('fehler.offline.mit_adresse', { base, address })` statt Stringkette), kein Satz aus Fragmenten.
- Anrede, Wortlaut und Satzzeichen bleiben **1:1** (Du/Sie-Mischung inklusive; Vereinheitlichung ist ein eigener Schritt danach, Spec Punkt 3).
- Schlüssel sind sprechend und nach Bereich gegliedert (`fehler.*`, `editor.*`, `woche.*`, `einstellungen.*`).

- [ ] **Step 1: Failing test:** die Datei aus `PENDING` streichen → `i18n-literals.test.js` schlägt an und nennt die Fundstellen. Bestehende Tests der Datei (`messages.test.js` usw.) sind die Äquivalenz-Prüfung: **sie dürfen nicht angepasst werden**, nur die Ausgabe muss gleich bleiben.
- [ ] **Step 2:** `cd pwa && node --test` → FAIL (Literale gefunden)
- [ ] **Step 3: Texte ausziehen** → Katalogeintrag, im Code `t('…')`.
- [ ] **Step 4:** `node --test` und `npm run typecheck` → PASS; `pwa/test/layout.test.js` und `contrast.test.js` unverändert grün.
- [ ] **Step 5: Commit** `refactor(pwa): <Datei> auf die Textschicht umgestellt`

Task 13 (`views.js`, 111 Fundstellen) wird bei Bedarf in zwei PRs geteilt (Wochen-/Tagesansicht, Einstellungen); die Teilung legt der Bauende fest.

---

## PR 13 — Doku und Abnahme

### Task 15: Doku nachziehen und Abnahme-Liste

**Files:**
- Modify: `CLAUDE.md` (Struktur: `holidays_region`, `region`, `locale_format`; „Datumsformat": Locale; Urlaub: Länderwechsel), `src/CLAUDE.md`, `pwa/CLAUDE.md` (Textschicht, `i18n.js`, Ratsche, Locale), `docs/known-limitations.md` (Länderwechsel korrigiert keine Perioden)
- Test: `tests/test_claude_md_claims.py`, `tests/test_catch_all_handlers.py`

- [ ] **Step 1:** Doku anpassen; `pytest tests/test_claude_md_claims.py` → grün (Behauptungen parsen aus der Datei, Umformulierungen ziehen das Muster im Test mit).
- [ ] **Step 2: Abnahme vor dem Merge nach `master`** (Checkliste in der PR-Beschreibung des letzten PRs, hier **nicht** abgehakt): vollständige Suite grün; `cd pwa && node --test && npm run typecheck`; `cd relay && npm test` unberührt grün; PWA lokal über `python scripts/pwa_devserver.py` im Browser; Test am echten Handy (Android, iPhone) mit neuer **und** (falls möglich) alter Desktop-Version; Desktop unter Linux und Windows; macOS über einen Pre-Release, sobald die Desktop-Texte (Folgeplan) betroffen sind; Gesamtreview des Integrations-Branches.
- [ ] **Step 3: Commit** `docs: Land, Region, Locale und Textschicht`
