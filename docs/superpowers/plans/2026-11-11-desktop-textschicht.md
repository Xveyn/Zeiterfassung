# Desktop-Textschicht — Implementierungsplan (Teil 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die deutschen Oberflächentexte des Desktops (Dialoge, Einstellungen, Hauptfenster, Meldungen, Tray) liegen in einem Katalog und werden über `t()` gelesen — Text bleibt Deutsch, Verhalten und Anzeige bitgleich.

**Architecture:** Paket `src/i18n/` (`t`, Sprache, Katalog `de.py`) im Muster der PWA-Textschicht; die Sprache kommt aus `settings["language"]` (Teil 1). Eine AST-Ratsche (`tests/test_desktop_texts.py`) verbietet deutsche Literale in jeder umgestellten Datei; eine Inventur (`scripts/desktop_text_inventory.py`) liefert die Arbeitsliste. Umgestellt wird in Gruppen von Dateien, jede allein grün.

**Tech Stack:** Python 3.12, Tkinter, pytest, pyright (CI).

**Spec:** `docs/superpowers/specs/2026-11-10-laender-und-sprache-design.md` (Stufe 3). Teil 1: `docs/superpowers/plans/2026-11-10-laender-und-sprache.md` (PWA-Textschicht; deren Regeln gelten sinngemäß).

## Global Constraints

- Nur **Oberfläche**: Dialoge, Einstellungen, Hauptfenster, Meldungsdialoge, Tray, Toasts, Banner, Tooltips. **Nicht** in diesem Teil (Teil 3): Ausgabetexte (PDF-Bericht, Mail- und Teilen-Texte, Webhook-Payload, `DAYS_DE`/`MONTHS_DE` im Bericht, Mail-Vorlagen in den Settings), API-Fehlertexte (`api_*.py`), Texte an die Handy-PWA (`mobile_*.py`, `relay_*`), Sync-Engine-Meldungen. Diese Dateien stehen in `FILE_EXEMPT` der Ratsche, jede mit Grund „Teil 3“ oder „Protokoll“.
- Log-Texte (`log.*`), Exception-Texte, die nie angezeigt werden, Docstrings und Kommentare bleiben deutsch und sind ausgenommen.
- Text, Wortlaut, Anrede, Satzzeichen und Reihenfolge bleiben **1:1**; jede Anzeige ist bitgleich zu vorher. Zusammengesetzte Sätze werden **ein** Schlüssel mit Parametern, keine Fragmentketten.
- Schlüssel stehen nur als **Literal** im `t(`-Aufruf (die Ratsche liest sie am Quelltext); aufgelöst wird beim **Aufruf**, nie bei der Modul-Initialisierung (`LABELS = {…t(…)…}` auf Modulebene bliebe für immer in der Startsprache).
- Bestehende Tests bleiben unverändert grün (sie beweisen die Bitgleichheit); fehlt ein Test für einen Text, kommt vorher ein Charakterisierungstest. Ausnahme nur, wo ein Test einen Text als Quelltext-Literal festnagelt: dort nur diese Zeile auf den Schlüssel umstellen und den Wortlaut zusätzlich gegen den Katalog pinnen.
- Pixel- und Schriftregeln (`theme.px`, benannte Fonts, `tests/test_pixel_scaling.py`) bleiben unberührt; Texte ändern sich nicht, also ändern sich Breiten nicht.
- Kein Aufbrechen der großen Dialogfunktionen (`open_entry_dialog` u. a.) in diesem Teil: die Texte werden darin ersetzt, die Funktionen bleiben im Zuschnitt. Ein späteres Zerlegen ist ein eigenes Vorhaben.
- Zwei Fehlerklassen aus Teil 1, die hier gezielt zu prüfen sind: (1) ein Text gilt als „nie angezeigt“, erreicht den Nutzer aber über `str(e)`/`result["error"]`/`messagebox` doch — vor jeder Ausnahme alle Verbraucher verfolgen; (2) pyright (CI) ist strenger als der lokale Lauf — vor jedem Commit `pyright` laufen lassen (Binary: `pip install pyright==1.1.411` in ein Wegwerf-venv, `--pythonpath` auf die Projekt-Python).
- Tk-freie Module mit Eintrag in `tests/test_type_annotations.py` behalten volle Annotationen und die pyright-Direktive; `src/i18n/` kommt dort selbst hinein.
- Nichts Release-Bezogenes (`version.py`, `CHANGELOG.md`, Labels); die README-Regel (`*(ab --VERSION--)*`) gilt nur, wenn ein Nutzer-sichtbares Feature dazukommt — hier keins.

## Review Focus

1. Ein Text wird zur Modul-Initialisierung aufgelöst und bleibt in der Startsprache (Tabellen, Tupel, Defaults von Funktionsparametern auf Modulebene).
2. Ein Katalogschlüssel hat zwei Verwendungsorte mit **verschiedenem** Alttext (zusammengelegt, weil „gleich aussehend“).
3. Ein Text erreicht den Nutzer über einen Pfad, der als „log-only“ ausgenommen wurde (Exception → Dialog, Worker-Result → `messagebox`).
4. Threads: `t()` aus Worker-Threads (nur lesender Zugriff; `set_language` nur beim Start) — kein Schreibzugriff zur Laufzeit.
5. PyInstaller-Build: das Paket `src/i18n/` wird über normale Importe gefunden, keine Datenfiles, keine dynamischen Importe (`importlib`) im Katalog.

---

### Task 1: Textschicht, Ratsche und Inventur (Fundament)

**Files:**
- Create: `src/i18n/__init__.py`, `src/i18n/de.py`, `scripts/desktop_text_inventory.py`, `tests/test_i18n.py`, `tests/test_desktop_texts.py`
- Modify: `src/main.py` (Sprache setzen, neben `locale_format.set_active`), `tests/test_type_annotations.py` (Whitelist)

**Interfaces:**
- Produces (`src/i18n/__init__.py`, voll annotiert): `DEFAULT_LANGUAGE = "de"`; `LANGUAGES: tuple[str, ...]` (Codes der Kataloge); `normalize_language(value: object) -> str` (nutzt `region.normalize_language` nicht erneut — die Wahrheit über unterstützte Sprachen liegt künftig hier; `region.LANGUAGES` verweist auf `i18n.LANGUAGES`); `set_language(lang: str) -> None`; `get_language() -> str`; `t(key: str, **params: object) -> str` — ersetzt `{name}`-Platzhalter, lässt unbekannte stehen; unbekannter Schlüssel liefert den **Schlüssel** und loggt eine Warnung (einmal je Schlüssel).
- Katalog `src/i18n/de.py`: `TEXTS: dict[str, str]`.

- [ ] **Step 1: Failing tests** `tests/test_i18n.py`: Parametersubstitution (`t("i18n.beispiel", name="X")`), unbekannter Platzhalter bleibt stehen, unbekannter Schlüssel liefert Schlüssel, `normalize_language("de-AT") == "de"`, `("xx") == "de"`, `(None) == "de"`, `set_language("xx")` fällt auf `de`; Autouse-Fixture setzt die Sprache zurück.
- [ ] **Step 2:** `pytest tests/test_i18n.py -v` → FAIL.
- [ ] **Step 3: Implement** das Paket (zwei Seed-Schlüssel `i18n.beispiel`/`i18n.ohne_parameter` im Katalog, vom Unused-Check ausgenommen wie in der PWA); `main.py` ruft `i18n.set_language(settings.get("language"))` direkt vor `locale_format.set_active(...)`.
- [ ] **Step 4: Inventur-Skript** `scripts/desktop_text_inventory.py [--list]`: AST über `src/`, meldet je Datei deutsche **Oberflächenliterale** (String-Konstanten und f-String-Teile, die nach der Regel unten „Text“ sind), ausgenommen Docstrings, `log.*`-Argumente, Kommentare und `raise`-Argumente. Regel „Text“: Literal mit Leerzeichen **oder** mit Großbuchstabe am Anfang **oder** mit Umlaut/ß, nicht Bezeichner-artig (`^[a-z_][a-z0-9_.-]*$`).
- [ ] **Step 5: Ratsche** `tests/test_desktop_texts.py`: liest `src/**/*.py`; `FILE_EXEMPT` (Dateien mit Grund; mindestens `report.py`, `share_message.py`, `share.py`, `mail.py`, `mime_message.py`, `webhook.py`, `api_*.py`, `mobile_*.py`, `relay_*.py`, `sync.py`, `holidays_region.py`, `locale_format.py`, `time_utils.py` (Datumsnamen, Teil 3)), `ALLOWED` je Datei (enge, kommentierte Einzeltexte), `PENDING` = alle übrigen Dateien mit Fundstellen aus der Inventur. Für Dateien außerhalb von `PENDING`/`FILE_EXEMPT`: kein Textliteral außerhalb von `t(`, `log.*(`, Docstrings und `ALLOWED`. Schlägt an, wenn eine PENDING-Datei keine Fundstellen mehr hat (nur Verkleinern), und prüft veraltete `ALLOWED`-Einträge. Zusätzlich: jeder Schlüssel in `t("…")` existiert im Katalog, jeder Katalogschlüssel (außer `i18n.*`) wird benutzt, Schlüssel nur als Literal.
- [ ] **Step 6:** `python -m pytest -q`, `ruff check .`, pyright (siehe Constraints) → grün. Commit `feat(i18n): Textschicht, Ratsche und Inventur für den Desktop`.

### Task 2: Meldungsdialoge, Tooltips, Banner, Tray-Texte (kleine UI-Bausteine)

**Files:** `src/theme/messagebox.py`, `src/theme/*` (nur sichtbare Texte), `src/tooltip.py`, `src/update_banner.py`, `src/scale_banner.py`, `src/tray/*` (Menütexte kommen aus `ui.py::_tray_actions`, dort Task 8), `src/unpair_notice.py`; Tests der jeweiligen Module; `tests/test_desktop_texts.py` (PENDING kürzen).
Umzustellende Texte: Standardbeschriftungen der themed Dialoge („OK“, „Abbrechen“, „Ja“, „Nein“, …), Banner-Texte, Hinweistexte. Regeln: Konstanten, die Texte halten, werden Funktionen; `theme.messagebox` bleibt Drop-in-kompatibel (Aufruferschnittstelle unverändert).
- [ ] Je Datei: Charakterisierungstest bei fehlender Abdeckung → Datei aus `PENDING` streichen (Ratsche rot) → Texte ausziehen → grün → Commit `refactor(i18n): <Dateien> auf die Textschicht umgestellt`.

### Task 3: Tk-freie Textmodule der Oberfläche

**Files:** `src/conflict_view.py` (`SETTING_LABELS`, Karten, Titel — die `SETTING_LABELS`-Abdeckungsprüfung gegen `SYNCED_SETTING_KEYS` bleibt), `src/vacation_plan.py` (nur Nutzertexte), `src/removal.py` (Hinweise, Schrittbeschreibungen), `src/storage.py` (`repair_notice_text`, `repair_toast_text`), `src/updater.py` (`FAILURE_TEXTS`, `manual_check_toast_text`), `src/self_update.py` (Anzeige-Texte), `src/sync_orchestrator.py` (Statustext, Toasts, Fehlermeldungen), `src/weekly_limit.py`, `src/pause_requirement.py`, `src/reminders.py`/`reminder_scheduler.py`/`send_reminder_scheduler.py` (Toast-Texte), `src/dialogs/settings_dialog/tab_rules.py` bleibt Task 4.
Wichtig: viele dieser Module sind Tk-frei und in der Annotations-Whitelist — Signaturen bleiben, nur Texte wandern. Jeder Text mit Nutzersichtbarkeit wird über **alle Verbraucher** verfolgt (Review Focus 3); `classify_sync_error`/`_friendly_sync_message` liefern Texte an `messagebox` → Katalog.
- [ ] Je Modul wie in Task 2; Tests der Module bleiben unverändert (sie pinnen die Texte).

### Task 4: Einstellungen, Teil 1 — `tab_rules`, `tab_work`, `tab_reminders`, `tab_app`, `tab_sending`, `form_model`

**Files:** `src/dialogs/settings_dialog/tab_rules.py` (rund 70 Texte: Validierungsmeldungen, Statuszeilen, Hinweise — Tk-frei, größte Einzeldatei), `tab_work.py`, `tab_reminders.py`, `tab_app.py`, `tab_sending.py`, `form_model.py`, `dialog.py` (Reiter-/Knopftexte, Rückfragen beim Verlassen); `tests/test_tab_rules.py` bleibt unverändert grün.
Besonderheiten: Reitertitel kommen aus `tab.title` (zur Aufrufzeit lesen); die Texte von `test_tabs_together_write_exactly_the_legacy_keys` betreffen Schlüssel, nicht Anzeige.

### Task 5: Einstellungen, Teil 2 — `tab_google`, `tab_updates`, `tab_api`, `tab_mobile`, `tab_smtp`, `tab_webhooks`, `_record_list_tab`, `scopes`/`oauth`-Texte

**Files:** die genannten Module unter `src/dialogs/settings_dialog/` und `src/dialogs/scopes_dialog.py`. `google_tab_task.py`: das Result-Dict trägt Zustände, keine Texte (Zustand → Text im Tab); `_TOKEN_MARKS` o. Ä. Modul-Tabellen werden Funktionen.

### Task 6: Dialoge A — Tages-Dialog und Kategorien

**Files:** `src/dialogs/entry_dialog.py` (408 Zeilen, nur Texte), `slot_rows.py`, `category_dialog.py`, `conflicts_dialog.py`, `date_row.py`, `period_picker.py`.
`RESERVATION_CALENDAR_NOTE`: das Desktop-Gegenstück zur PWA-Konstante (Modulkonstante mit Text) wird eine Funktion; `tests` und `src/CLAUDE.md` (Verweis) ziehen mit.

### Task 7: Dialoge B — Versand, Export, Teilen, Import

**Files:** `src/dialogs/send_dialog.py`, `send_task.py` (nur die Nutzer-sichtbaren Ergebnistexte; Kanal-Result-Dicts tragen Codes), `export_dialog.py`, `export_task.py`, `share_dialog.py` (406 Zeilen), `share_task.py`, `import_dialog.py`.
Nicht: Betreff/Body/Anhangsname der Mail (`share_message.py`, Mail-Vorlagen) — Teil 3.

### Task 8: Dialoge C — SMTP, Webhook, Urlaub, Handy-Kopplung, Entfernen, Datenschutz

**Files:** `src/dialogs/smtp_dialog.py`, `webhook_dialog.py`, `vacation_dialog.py`, `mobile_pair_dialog.py`, `removal_dialog.py`, `privacy_dialog.py` (nur Dialog-Chrome; der Dokumentinhalt `docs/datenschutz.md` bleibt), `mobile_pair`-Texte aus `tab_rules`.

### Task 9: Hauptfenster

**Files:** `src/ui.py` (rund 39 Texte: Header-/Footer-Beschriftungen, Tray-Menü `_tray_actions`, Toasts, Meldungen), `src/grid_renderer.py` (Tooltips der Zellen, Wochentags-Überschriften soweit sie nicht schon `locale_format` nutzen; `_build_tooltip_text`), `src/ui.py::remove_application`-Texte.
Hinweis: Wochentags- und Monatsnamen der **Anzeige** kommen bereits über `locale_format` bzw. `time_utils`; Namen in Berichten bleiben Teil 3.

### Task 10: Abschluss — Ratsche scharf, Doku, Abnahme

**Files:** `tests/test_desktop_texts.py` (`PENDING` leer, Mechanismus durch „alle Dateien geprüft“ ersetzen wie in der PWA), `CLAUDE.md`, `src/CLAUDE.md` (Abschnitt „Textschicht“, wo neue Texte hingehören, was deutsch bleibt), `docs/known-limitations.md` (Ausgaben noch deutsch, Teil 3), `CONTRIBUTING.md`.
- [ ] Gesamtreview des Branches (stärkstes Modell), dann Abnahme am Desktop (Linux, Windows; macOS über Pre-Release, da Dialoge plattformübergreifend betroffen sind) — Checkliste in der PR-Beschreibung.

---

**Teil 3 (eigener Plan danach):** Ausgabesprache (PDF, Mail, Teilen, Webhook, Wochentage/Monate im Bericht, Mail-Vorlagen als Settings-Werte — Frage der Defaults und Migration), API-/Handy-Texte, Länder-Beschriftung des Arbeitsrechts (Stufe 5), optional Zerlegen der großen Dialogfunktionen.
