# Desktop-Textschicht — Implementierungsplan (Teil 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die deutschen Oberflächentexte des Desktops (Dialoge, Einstellungen, Hauptfenster, Meldungen, Tray) liegen in einem Katalog und werden über `t()` gelesen — Text bleibt Deutsch, Anzeige bitgleich.

**Architecture:** Paket `src/i18n/` (`t`, `N_`, Sprache, Katalog in Bereichsmodulen `src/i18n/de/*.py`) im Muster der PWA-Textschicht; die Sprache kommt aus `settings["language"]` (Teil 1). Eine AST-Ratsche (`tests/test_desktop_texts.py`, Regel wie unten) verbietet deutsche Literale in jeder umgestellten Datei; ein Skript (`scripts/desktop_text_check.py`) liefert die Inventur **und** belegt je Commit mechanisch, dass jeder entfernte Text als Katalogwert wieder vorkommt. Umgestellt wird in Gruppen, jede allein grün.

**Tech Stack:** Python 3.12, Tkinter, pytest, pyright (CI).

**Spec:** `docs/superpowers/specs/2026-11-10-laender-und-sprache-design.md` (Stufe 3). Teil 1: `docs/superpowers/plans/2026-11-10-laender-und-sprache.md` (PWA-Textschicht; deren Regeln gelten sinngemäß). Dieser Plan wurde vor der Ausführung von einem unabhängigen Review gegen den Code geprüft; dessen Befunde sind eingearbeitet.

## Global Constraints

- **Oberfläche heißt: was der Nutzer in einem Fenster, Dialog, Toast, Tooltip, Tray-Menü, Banner oder Systemmenü liest — gleich aus welchem Modul der Text kommt.** Maßgeblich ist der **Verbraucher**, nicht der Dateiname: Texte in `time_utils.py`, `mail.py`, `share.py`, `webhook.py`, `smtp.py`, `sync.py`, `vacations.py` usw., die in einem Dialog erscheinen (auch über `str(e)`, `result["detail"]`, `ShareValidationError.reason`), sind **im Umfang** und kommen in den Katalog.
- **Nicht im Umfang (Teil 3):** PDF-Bericht und Mail-/Teilen-/Webhook-**Inhalte** (`report.py`, `share_message.py`, Payload-Texte, Anhangsnamen), die Mail-Vorlagen-Defaults in `settings.py`, Kalendertermin-Texte (`gcal.py`), API-Antworttexte, die nie in der UI erscheinen (`api_*.py`), Handy-/Relay-Protokolltexte (`mobile_*.py`, `relay_*.py`, `ws_client.py`), Berichts-Wochentage/-Monate (`DAYS_DE`/`MONTHS_DE` in `report.py`). Dateien, in denen nur Teile Ausgabe sind, stehen **nicht** in `FILE_EXEMPT`, sondern per `ALLOWED` je Text mit Verbraucherangabe.
- **Ein Text, der in UI und in API/Bericht erscheint** (z. B. `time_utils.validate_slots`-Fehler, `vacations.cap_notice`): er kommt in den Katalog und folgt der Oberflächensprache; API und Bericht übernehmen den Text unverändert (heute identisch). Teil 3 trennt bei Bedarf.
- Log-Texte (`.debug/.info/.warning/.error/.exception/.critical`-Argumente und die benannten Log-Helfer, z. B. `_log_skipped`) bleiben deutsch. **`raise`-Argumente sind keine Ausnahmeklasse:** jeder deutsche Text in einer Exception steht entweder im Katalog oder in `ALLOWED` mit der Angabe, warum er den Nutzer nie erreicht (Verbraucher bis zum Dialog verfolgt — Fehlerklasse aus Teil 1).
- **Sentinel-Texte** (ein Text dient zugleich als Erkennungsmerkmal im Programmfluss: `NEWER_REMOTE_VERSION_MSG`, `REAUTH_REQUIRED_MSG`, `SYNC_TIMEOUT_MSG`, `KEYRING_UNAVAILABLE_MSG`, `NO_CATEGORY_LABEL` als API-verbotener Name) bleiben Konstanten (`ALLOWED`, Grund „Erkennungsmerkmal“) und bekommen einen **getrennten** Anzeigetext im Katalog. Erzeuger (Worker) und Vergleicher (UI) lösen sonst zu verschiedenen Zeitpunkten auf.
- **Text bleibt 1:1** (Wortlaut, Anrede, Satzzeichen, Glyphen `✓ ✗ ⚠ ● ＋` gehören zum Katalogtext, ein Schlüssel je Anzeige). Zusammengesetzte Sätze werden **ein** Schlüssel mit Parametern, keine Fragmentketten. **Plural:** zwei Schlüssel (`….eins`/`….viele`), keine Suffix-Bastelei.
- **Schlüssel nur als Literal** im `t(`-Aufruf. Tabellen Code → Text verwenden den Marker `N_("schluessel")` (Identität; die Ratsche liest ihn als Schlüsselliteral) und lösen beim Aufruf mit `t(TABELLE[code])` auf.
- **Aufgelöst wird beim Aufruf, nie bei der Modul-Initialisierung** (Tabellen, Default-Argumente, Klassenattribute, `Form`-Deklarationen). Label↔Code-Umkehrtabellen (`_CODE_FOR_LABEL` u. ä.) entstehen **beim Aufruf**. Gespeichert werden Codes; der Katalog ändert nie einen gespeicherten Wert.
- **Tests:** Assertions und Erwartungswerte bleiben unverändert. Erlaubt und verlangt ist die **mechanische** Umstellung von Tests, die eine Textkonstante importieren (`tr.TOKEN_MISSING` → `tr.token_missing()`, `FAILURE_TEXTS[k]` → `t(FAILURE_TEXTS[k])`) sowie von Quelltext-Pins deutscher Literale (nur auf den Schlüssel im Quelltext umstellen und den Wortlaut zusätzlich gegen den Katalog pinnen). Jeder Task listet die betroffenen Testdateien (aus dem Review: s. je Task). Fehlt ein Test für einen Text, kommt vorher ein Charakterisierungstest — für Tk-Aufbau ohne Test ersetzt das die mechanische Äquivalenzprüfung (nächster Punkt).
- **Mechanische Äquivalenz:** `scripts/desktop_text_check.py --base <ref> --files <…>` vergleicht je Datei die Textliterale (f-Strings als `{}`-normalisiertes Template) von `<ref>` mit den Katalogwerten der neu hinzugekommenen `t("…")`/`N_("…")`-Schlüssel als Multimenge; Abweichungen (zusammengezogene Ketten) werden im Commit aufgelistet und begründet. Jeder Konvertierungs-Task führt sie aus.
- `t(key, /, **params)`: Schlüssel positionsgebunden, Ersetzen der `{name}`-Platzhalter in **einem** Durchlauf per Regex (kein `str.format`; Parameterwerte dürfen `{…}` enthalten), unbekannte Platzhalter bleiben stehen, unbekannter Schlüssel liefert den Schlüssel und loggt einmal je Schlüssel.
- **Die Wahrheit über unterstützte Sprachen liegt in `src/i18n`** (`LANGUAGES`, `normalize_language`); `region.normalize_language`/`region.LANGUAGES` verweisen darauf. Importrichtung: `region` → `i18n`, `locale_format` → `region`; `src/i18n` importiert nichts aus `src`.
- **`set_language` läuft direkt nach dem Bau der `Settings` in `main.py`** (vor `Storage` und allem, was Texte erzeugt), nicht erst bei `locale_format.set_active`. Texte, die schon beim Laden eines Stores entstehen (`Storage`-Reparaturhinweis), werden **zum Anzeigen** gebaut: der Store hält Zähler/Codes, nicht den fertigen Satz; der Log-Satz bleibt deutsch.
- Nicht verändern: Pixel- und Schriftregeln (`theme.px`, benannte Fonts, `tests/test_pixel_scaling.py`), das Aufbrechen der großen Dialogfunktionen (eigenes Vorhaben danach), Release-Dateien (`version.py`-Bump, `CHANGELOG.md`, Labels).
- **pyright (CI) ist strenger als der lokale Lauf:** vor jedem Commit `pyright` (1.1.411) laufen lassen — Wegwerf-venv, `pip install pyright==1.1.411`, `--pythonpath` auf die Projekt-Python. Whitelist-Module (`tests/test_type_annotations.py`) behalten volle Annotationen und die pyright-Direktive; `src/i18n/` und seine Bereichsmodule kommen selbst hinein.
- Konfliktfreiheit im Katalog: je Bereich ein Modul (`allgemein`, `meldungen`, `einstellungen`, `dialoge`, `hauptfenster`); ein Test verbietet doppelte Schlüssel über Module hinweg. PyInstaller findet die Module über statische Importe (kein `importlib`).

## Review Focus

1. Ein Text wird zur Importzeit aufgelöst (Tabellen, Defaults, `_CODE_FOR_LABEL`) und bleibt in der Startsprache.
2. Ein Schlüssel, zwei Verwendungsorte mit verschiedenem Alttext (die Äquivalenzprüfung zeigt es).
3. Ein Text gilt als „nie angezeigt“, erreicht den Nutzer aber über `str(e)`/`result["detail"]`/Dialog (Verbraucher bis zum Dialog verfolgen, mit Fundstelle im `ALLOWED`-Kommentar).
4. Ein Sentinel-Text wird versehentlich zur `t()`-Funktion (Erzeuger und Vergleicher lösen zu verschiedenen Zeitpunkten auf).
5. Threads: `t()` aus Worker-Threads (nur lesend; `set_language` nur beim Start).
6. `FILE_EXEMPT` hält volle relative Pfade: `dialogs/mobile_pair_dialog.py` darf nie durch `mobile_*.py` ausgenommen sein.
7. Ein Test importiert noch eine entfernte Textkonstante, ein Quelltext-Test sucht noch das Literal.

---

### Task 1: Fundament — Textschicht, Ratsche, Äquivalenz-Skript

**Files:**
- Create: `src/i18n/__init__.py`, `src/i18n/de/__init__.py`, `src/i18n/de/allgemein.py`, `src/i18n/de/meldungen.py`, `src/i18n/de/einstellungen.py`, `src/i18n/de/dialoge.py`, `src/i18n/de/hauptfenster.py` (zunächst nur Seed-Schlüssel), `scripts/desktop_text_check.py`, `tests/test_i18n.py`, `tests/test_desktop_texts.py`
- Modify: `src/main.py` (Sprache direkt nach `Settings`), `src/region.py` (Alias), `tests/test_type_annotations.py`, `tests/test_region.py`, `tests/test_mobile_routes.py` (≈226, 244), `tests/test_mobile_defaults.py` (≈85) — die drei Monkeypatches zeigen auf `src.i18n.LANGUAGES`

**Interfaces:**
- Produces (`src/i18n/__init__.py`, voll annotiert, pyright-Direktive): `DEFAULT_LANGUAGE = "de"`; `LANGUAGES: tuple[str, ...]`; `normalize_language(value: object) -> str` (`"de-AT"` → `"de"`, Fremdes → `"de"`; die strikte Variante der Alt-Funktion lebt als `region.normalize_language` weiter und delegiert nur die **Mengen**-Wahrheit); `set_language(lang: object) -> None`; `get_language() -> str`; `t(key: str, /, **params: object) -> str`; `N_(key: str) -> str` (Identität). Katalog: `TEXTS: dict[str, str]` aus den Bereichsmodulen (Vereinigung, Test auf Duplikate).

- [ ] **Step 1: Failing tests** `tests/test_i18n.py`: Parametersubstitution (auch Wert mit `{x}`, Parameter namens `key`), unbekannter Platzhalter bleibt, unbekannter Schlüssel → Schlüssel + eine Warnung, `normalize_language`-Fälle, `set_language("xx")` → `de`, `N_("a.b") == "a.b"`, keine Duplikatschlüssel über die Bereichsmodule; Autouse-Fixture setzt die Sprache zurück.
- [ ] **Step 2:** `pytest tests/test_i18n.py -v` → FAIL.
- [ ] **Step 3: Implement** das Paket (Seed-Schlüssel `i18n.beispiel`/`i18n.ohne_parameter`, vom Unused-Check ausgenommen); `main.py` ruft `i18n.set_language(settings.get("language"))` direkt nach dem Bau der `Settings`; `region` delegiert, die drei Monkeypatch-Tests ziehen um, `tests/test_region.py` um `de-AT` ergänzen.
- [ ] **Step 4: Ratsche** `tests/test_desktop_texts.py` — liest `src/**/*.py` (relative Pfade!), baut je **Textliteral** (f-Strings als ein `{}`-normalisiertes Template). Regel „Text“: enthält ein Wort mit Kleinbuchstaben **und** (Leerzeichen **oder** Großbuchstabe am Anfang **oder** Umlaut/ß); **kein** Text sind: Wörter ohne Kleinbuchstaben (`APPIMAGE`, `RGBA`), Bezeichner-/Dotted-/CamelCase-/Pfad-/Format-Strings (`^[A-Za-z_][\w.\-/%:<>@#+ ]*$` ohne Leerzeichen), die globale Technik-Menge `{"Windows", "Linux", "Darwin", "Zeiterfassung"}`. **Kontext-Ausnahmen per AST:** Docstrings; Argumente von `.debug/.info/.warning/.error/.exception/.critical` und der Log-Helfer-Liste; Argumente von `os.environ.get`, `os.path.join`, `re.compile`, `startswith/endswith`, `namedtuple`, `add_header/send_header`; Schlüsselwörter `style=`, `font=`, `name=`, `sticky=`, `compound=`, `anchor=`, `orient=`, `state=`, `relief=`, `cursor=`, `show=`; Subscript-/Dict-Schlüssel; `__all__`; Annotationen; Vergleiche mit `platform.system()`. `t(`/`N_(`-Argumente sind Schlüsselliterale. `FILE_EXEMPT`: **volle relative Pfade** mit Grund (`report.py`, `share_message.py`, `settings.py` (Mail-Vorlagen), `gcal.py`, `api_*.py`, `mobile_*.py`, `relay_*.py`, `ws_client.py`, …; ein Test prüft, dass jede Datei existiert und keine Datei unter `dialogs/`, `theme/`, `tray/` darin steht). `ALLOWED` je Datei: enge Einzeltexte mit Grund/Verbraucher. `PENDING`: alle übrigen Dateien mit Fundstellen (aus dem Skript, Step 5). Für Dateien außerhalb von `PENDING`/`FILE_EXEMPT`: kein Textliteral außerhalb der Ausnahmen/`ALLOWED`. Schlägt an: eine PENDING-Datei ohne Fundstellen; ein veralteter `ALLOWED`-Eintrag; ein `t("…")`/`N_("…")`-Schlüssel ohne Katalogeintrag; ein Katalogschlüssel (außer `i18n.*`), der nirgends benutzt wird; ein dynamisch gebauter Schlüssel.
- [ ] **Step 5: Skript** `scripts/desktop_text_check.py` mit `--list` (Inventur je Datei) und `--base <ref> --files …` (Äquivalenzprüfung, s. Constraints). Es teilt die Regel mit der Ratsche (eine Quelle, kein zweiter Parser); `PENDING` in der Ratsche wird aus der Inventur gebaut und im Test als Liste festgeschrieben.
- [ ] **Step 6:** `python -m pytest -q`, `ruff check .`, pyright → grün. Messung der Regel dokumentieren (Anzahl `ALLOWED`-Einträge, Falschpositive je Kategorie) im Bericht; ist sie nach der Verfeinerung noch über ~150 `ALLOWED`-Einträge, meldet der Implementierer das als Konzern. Commit `feat(i18n): Textschicht, Ratsche und Äquivalenzskript für den Desktop`.

### Task 2: Geteilte Tk-freie Bausteine (UI **und** API/Bericht/Dialog)

**Files:** `src/time_utils.py` (Validierungsmeldungen ≈124–145/311/318, `format_minutes_hm` „h“/„min“, KW-Label ≈188; Kurz-/Monatsnamen: `DAYS_DE`/`MONTHS_DE` für die **Anzeige** über `locale_format` ergänzen — Kurznamen und Monate je Locale in die eine Tabelle; `report.py` behält seine Listen bis Teil 3), `src/vacations.py` (≈215–230 `cap_notice`, ≈324–330 Fehlertexte), `src/default_times.py` (`MODE_LABELS`, `_CODE_FOR_LABEL` beim Aufruf), `src/send_reminder.py` (`SHIFT_LABELS` ≈52–66 als `N_`-Tabelle, Tooltip-Zeile ≈316–323), `src/dpi.py` (`scale_hint` ≈347), `src/version.py` (`UPDATES_UNSUPPORTED_HINT`), `src/changelog.py` (`NO_CHANGES_NOTICE`), `src/privacy_doc.py` (`FALLBACK_TEXT`), `src/oauth_utils.py` (Anzeigetexte `KEYRING_UNAVAILABLE_TITLE/_HINT`; das Erkennungsmerkmal `KEYRING_UNAVAILABLE_MSG` bleibt Konstante), `src/mail.py` (Scope-Labels ≈43–47, `friendly_token_message` ≈304–331, Fehlertexte ≈289–297/366–369), `src/dialogs/slot_rows.py` (Konstanten wie `NO_CATEGORY_LABEL` — Sentinel/API-Spiegel: Anzeigetext getrennt, `api_entry_write`-Konstante und `tests/test_api_entry_write.py:142` bleiben).
**Tests (mechanisch):** `tests/test_tab_rules.py` (`SHIFT_LABELS`, `FREQUENCY_OPTIONS`-Zugriffe), `tests/test_changelog.py:7,454,458`, `tests/test_entry_dialog.py:4,35–99`, `tests/test_time_utils.py`, `tests/test_vacations*.py`, `tests/test_send_reminder*.py`, `tests/test_settings_dialog.py:118–146`, `tests/test_dpi.py`.
- [ ] Je Datei: Äquivalenzprüfung, Datei aus `PENDING`, Commit `refactor(i18n): <Dateien> auf die Textschicht umgestellt`.

### Task 3: Meldungsbausteine und Tray

**Files:** `src/theme/messagebox.py` (Standardbeschriftungen), `src/update_banner.py` (`_LABEL_INSTALL`/`_LABEL_DOWNLOAD`; `tests/test_update_banner.py:176–177` mechanisch), `src/scale_banner.py`, `src/unpair_notice.py`, `src/tray/model.py` (≈26/33 „Anzeigen“/„Beenden“), `src/tray/windows.py` (≈83/95), `src/logging_setup.py` (nativer Fehlerdialog ≈125), `src/main.py` (stderr-/Dialogmeldungen ≈151–173), `src/desktop_entry.py` (`Comment=` ≈131, erscheint im Systemmenü).
Die Texte der Tray-Menüeinträge (`App._tray_actions`) gehören zu Task 11 (`ui.py`).
- [ ] Je Datei wie Task 2.

### Task 4: Zustands- und Meldungsmodule

**Files:** `src/conflict_view.py` (`SETTING_LABELS` als `N_`-Tabelle; `OWN_TITLE`/`OTHER_TITLE`/`NO_CATEGORY`/`DELETED_TEXT`; `tests/test_conflict_view.py:52,90,104,117,163,190,197` mechanisch, die Abdeckungsprüfung gegen `SYNCED_SETTING_KEYS` bleibt), `src/storage.py` (Reparaturhinweis: Zähler statt fertigem Satz, `repair_notice_text`/`repair_toast_text` bauen den Text zum Anzeigen; Log-Satz deutsch), `src/removal.py` (Schrittkennung getrennt vom Anzeigenamen: `BOX_STEP`/`KEYRING_STEP`, „Zugangsdaten“/„Autostart“; `tests/test_removal.py:750,763,782,791` mechanisch), `src/updater.py` (`FAILURE_TEXTS` als `N_`-Tabelle; `tests/test_updater.py:11,260,512,516,623–644`, `tests/test_update_coordinator.py:12,232,242`), `src/self_update.py` (Anzeigetexte; das cmd-Skript ≈417–433 ist Technik → `ALLOWED`), `src/update_coordinator.py`, `src/secret_migration.py` (≈151–184 Dialog/Toast), `src/weekly_limit.py`, `src/reminder_scheduler.py`, `src/send_reminder_scheduler.py` (Toast, `MONTHS_DE`-Satz ≈146 über `locale_format`), `src/sync_orchestrator.py` (Sentinel `NEWER_REMOTE_VERSION_MSG`/`REAUTH_REQUIRED_MSG`/`SYNC_TIMEOUT_MSG` getrennt von den Anzeigetexten; `tests/test_ui_sync_errors.py:37–39`, `tests/test_sync_runtime_logging.py:10,24`; Plural „Konflikt“/„Konflikte“), `src/sync.py` (nur der Sentinel/Anzeigetext `NEWER_REMOTE_VERSION_MSG`), `src/dialogs/settings_dialog/oauth_task.py`, `src/dialogs/settings_dialog/google_tab_task.py` (Zustände bleiben Codes).
- [ ] Je Datei wie Task 2; Sentinel-Fälle mit zusätzlichem Test, dass Erzeuger und Vergleicher dieselbe Konstante nutzen.

### Task 5: Stores, Validierung und Versandmeldungen für Dialoge

**Files:** `src/smtp_store.py` (≈84–107 `validate_record`), `src/webhook_store.py` (≈75–103), `src/webhook_secrets.py` (≈190–193), `src/vacation_plan.py`, `src/webhook.py` (URL-Prüfung ≈103–110/168, `detail` ≈443/467 — das Ergebnis erscheint im Versand-Ergebnisdialog), `src/smtp.py` (≈95/240), `src/mime_message.py` (≈37–40, über `send_task.py` im Ergebnisdialog), `src/share.py` (30 `ShareValidationError`-Texte ≈59–230, im Import-Dialog gezeigt), `src/dialogs/mail_task.py`, `tests/test_send_task_dispatch.py:338–341,374` (`_KIND_TEXTS` als `N_`-Tabelle).
Hier gilt die Regel „Verbraucher bis zum Dialog“: Texte, die nur in Payload/Header landen, bleiben deutsch (`ALLOWED`, Grund „Ausgabe/Teil 3“).
- [ ] Je Datei wie Task 2.

### Task 6: Einstellungen, Teil 1

**Files:** `src/dialogs/settings_dialog/tab_rules.py` (**vollständig**, inklusive Kopplungs-/Relay-/API-Texte und `_RELAY_STATE_TEXTS`, `RELAY_PAIR_*`, `PAIR_INTRO_*`, `FIRST_ENABLE_NOTICE`, `REVOKE_ERROR_TEXT`, `DISMISS_ERROR_TEXT`, `TOKEN_MISSING`, `AUTO_ADDRESS`, `API_ROUTES`: ≈45 Zugriffe in `tests/test_tab_rules.py` mechanisch umstellen), `tab_work.py`, `tab_reminders.py`, `tab_app.py`, `tab_sending.py`, `form_model.py`, `dialog.py`, Reitertitel (zur Aufrufzeit lesen).
**Quelltext-Test:** `tests/test_privacy_dialog_wiring.py:27–28` (Schlüssel im Quelltext + Wortlaut gegen Katalog).
- [ ] Datei für Datei; `tab_rules.py` verlässt `PENDING` mit dem Task.

### Task 7: Einstellungen, Teil 2

**Files:** `tab_google.py`, `tab_updates.py`, `tab_api.py`, `tab_mobile.py`, `tab_smtp.py`, `tab_webhooks.py`, `_record_list_tab.py`, `src/dialogs/scopes_dialog.py` (`_LEGEND`, Glyphen im Text); `_TOKEN_MARKS` o. ä. als `N_`-Tabellen.
**Quelltext-Tests:** `tests/test_mobile_tab_wiring.py:42,47,130`.

### Task 8: Dialoge A

**Files:** `src/dialogs/period_picker.py` (hängt an `vacations.cap_notice` aus Task 2), `category_dialog.py`, `conflicts_dialog.py` (`DONE_TEXT`, `'ZEITEN · '`), `entry_dialog.py` (≈408 Zeilen; nur Texte; `RESERVATION_CALENDAR_NOTE` als Funktion samt `src/CLAUDE.md`-Verweis und `tests/test_entry_dialog.py:320`), `date_row.py` (falls Text).
**Quelltext-Tests:** `tests/test_dialog_cancel_buttons.py:16,21`.

### Task 9: Dialoge B

**Files:** `src/dialogs/send_task.py` (Ergebnistexte, `format_result_summary`, Glyphen), `send_dialog.py`, `export_dialog.py`, `share_task.py`, `share_dialog.py` (≈406 Zeilen), `import_dialog.py` (61 Fundstellen).
Nicht: Mail-Betreff/-Body/Anhangsname (`share_message.py`, Vorlagen) — Teil 3.

### Task 10: Dialoge C

**Files:** `src/dialogs/smtp_dialog.py`, `webhook_dialog.py`, `vacation_dialog.py` (Texte ≈542–544 aus `vacations`), `mobile_pair_dialog.py`, `removal_dialog.py`, `privacy_dialog.py` (nur Dialog-Chrome; `docs/datenschutz.md` bleibt).

### Task 11: Hauptfenster

**Files:** `src/ui.py` (**einmal**, inklusive `_tray_actions`, `_on_reconcile_done`, `remove_application`, Toasts, Meldungsdialoge ≈266/407–412), `src/grid_renderer.py` (Tooltips, Wochentags-Überschriften über `locale_format`), `src/background_tasks.py` (falls Text).

### Task 12: Abschluss — Ratsche scharf, Doku, Abnahme

**Files:** `tests/test_desktop_texts.py` (`PENDING` leer, Mechanismus durch „alle Dateien geprüft“ ersetzen wie in der PWA), `CLAUDE.md`, `src/CLAUDE.md` (Abschnitt „Textschicht“, wo neue Texte hingehören, was deutsch bleibt; alle Verweise auf entfernte Konstanten: `RESERVATION_CALENDAR_NOTE`, `KEYRING_UNAVAILABLE_TITLE/_HINT`, `RELAY_PAIR_REFUSED_TEXT/_ERROR_TEXT`, `REAUTH_REQUIRED_MSG`, `FAILURE_TEXTS`, `SETTING_LABELS`), `docs/known-limitations.md` (Teil-3-Liste der noch angezeigten deutschen Ausgaben und was die Sprache nicht erfasst), `CONTRIBUTING.md`.
- [ ] Gesamtreview des Branches (stärkstes Modell).
- [ ] **Abnahme** (Checkliste in der PR-Beschreibung): Tray-Menü und Toast je Plattform, Start mit `--minimized`, Fehlerpfade mit zusammengesetzten Texten (Versand-Ergebnis, Sync-Fehler, Import einer ungültigen Datei, Kopplungs-Dialog), Linux-AppImage (onefile) als Paketierungsprobe für `src/i18n`, Windows-Setup über einen **Pre-Release über alle drei Plattformen** (Plattformcode betroffen: `tray/*`).

---

**Teil 3 (eigener Plan danach):** Ausgabesprache (PDF, Mail-/Teilen-/Webhook-Inhalte, Berichts-Wochentage/-Monate, Mail-Vorlagen als Settings-Werte — Defaults und Migration), Kalendertermin-Texte, API-Antworttexte, Länder-Beschriftung des Arbeitsrechts (Stufe 5), optional Zerlegen der großen Dialogfunktionen.
