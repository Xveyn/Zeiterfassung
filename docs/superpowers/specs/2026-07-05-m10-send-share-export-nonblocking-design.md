# Design: Sende-/Teil-/Export-Pfade nicht mehr blockierend (Audit M10)

> Stand 2026-07-05. Adressiert Audit-Finding **M10**: `send_dialog`,
> `share_dialog` und `export_dialog` führen ihre blockierenden Operationen
> (PDF-Erzeugung, `get_gmail_service` inkl. evtl. interaktivem OAuth-Browser-
> Flow, `send_email`) synchron im Klick-Handler aus. Während das läuft, friert
> die Tk-Mainloop ein — im OAuth-Fall potenziell unbegrenzt.

## Ziel

Alle blockierenden Operationen der drei Dialoge laufen über den bereits
existierenden `BackgroundTaskRunner` (das eine Threading-Muster des Projekts,
`src/CLAUDE.md`). Kein Verhaltensbruch gegenüber heute — dieselben Meldungen,
dieselbe Persistenz, nur nicht mehr auf dem UI-Thread. `settings_dialog` (Audit
H5) ist die Vorlage.

**Basis:** der lokale Audit-Stack (gestackt auf die offenen PRs). M10 setzt
voraus: #121 (geteilter Store-Lock — `settings.set`/Store-Reads aus Workern
sind damit threadsicher), #122 (`theme.create_dialog`-Stand der Dialoge),
#123 (etabliertes `runner=`-Injektionsmuster). Der GitHub-Diff des M10-PRs
enthält die Stack-Commits mit, bis die unterliegenden PRs gemergt sind.

## Grundmuster

Analog H5 (`oauth_task.py`):

- Der **blockierende Kern** jedes Dialogs wandert in ein eigenes, **Tk-freies**
  Modul (`send_task.py` / `share_task.py` / `export_task.py`) als reine Funktion
  `perform_*(...) -> dict`. Sie läuft im Worker-Thread, fängt ihre Exceptions
  selbst, wirft nie, und **persistiert selbst** (z. B. `settings.set`) — läuft
  also im Thread und überlebt einen Dialog-Close.
- Die Dialog-Datei baut die `perform_*`-Eingaben auf dem UI-Thread zusammen,
  deaktiviert den Primär-Button und startet den Worker über
  `runner.run(fn, on_done)`.
- `on_done` (UI-Thread via `App._marshal_to_ui`) macht das Feedback,
  `winfo_exists`-gegated. `on_done` bleibt **in der Dialog-Datei** (Tk-gebunden);
  nur der Tk-freie Kern liegt im `*_task.py`-Modul.

## Aufteilung pro Dialog

### `send_dialog` → `send_task.perform_send`

**UI-Thread (vor dem Worker):** Datum/Zeitraum validieren; `entries =
storage.get_all()` (frischer Snapshot); `generate_report(...)` für den
„Keine Einträge"-Frühabbruch (rein, schnell, kein Netz) — bei `html is None`
Info-Modal und **ohne** Worker-Start zurück; `subject`/`label`/`pdf_filename`
berechnen; Button deaktivieren + Text „Sende…"; `runner.run`.

**Worker (`perform_send`):**
`generate_pdf` → `get_gmail_service` (inkl. evtl. OAuth-Browser-Flow) →
`send_email` → best-effort `fetch_user_email` + `settings.set("sender_email", …)`.
Signatur (keyword-only): `date_from, date_to, entries, name, categories,
category_breakdown, credentials_path, token_path, recipient, subject, html,
sync_enabled, gcal_enabled, settings`.

### `share_dialog` → `share_task.perform_share`

**UI-Thread:** Datentyp-/Kategorie-/Empfänger-Validierung; **`build_share_doc`
+ `serialize_share_doc`** (schneller Doc-Bau — bleibt auf dem UI-Thread, damit
der Payload ein Klick-Zeit-Snapshot ist und keine Store-Objekte in den Worker
wandern); `subject`/`html`/`filename` berechnen; Button deaktivieren +
„Teile…"; `runner.run`.

**Worker (`perform_share`):**
`get_gmail_service` → `send_email` → optional
`settings.set("share_recipient", …)` wenn „Als Standard speichern".
Signatur (keyword-only): `payload, filename, credentials_path, token_path,
recipient, subject, html, sync_enabled, gcal_enabled, save_default, settings`.

### `export_dialog` → `export_task.perform_export_pdf`

Kein Netz — der einzige blockierende Teil ist `generate_pdf`.

**Worker (`perform_export_pdf`):** nur `generate_pdf`. Signatur:
`date_from, date_to, entries, name, categories, category_breakdown`. Result
trägt bei Erfolg die `pdf_bytes`.

**`on_done` (UI-Thread):** bei Fehler Meldung; bei `pdf_bytes is None`
„Keine Einträge"-Info; sonst `filedialog.asksaveasfilename` (**muss** auf dem
UI-Thread laufen) → Datei schreiben → Erfolgs-Toast. Der Datei-Write ist
schnelles lokales IO und bleibt im `on_done`.

**Close-Sonderfall Export:** ist der Dialog beim `on_done` bereits zu, wird
das Ergebnis **verworfen** (kein nachträglicher Speichern-Dialog) — anders als
bei Send/Share ist noch nichts passiert; Schließen ist hier die
Abbrechen-Geste.

## Result-Dict & Fehlerabbildung

`perform_*` liefert:

- Erfolg: `{"ok": True, ...}` (Export zusätzlich `"pdf_bytes"`).
- Fehler: `{"ok": False, "kind": <k>, "error": e, "tb": <traceback|None>}` mit
  `kind ∈ {"filenotfound", "offline", "error"}`.
  - `filenotfound` — `get_gmail_service`/credentials fehlen (heute: eigener
    `except FileNotFoundError`).
  - `offline` — `is_offline_error(e)` ist True.
  - `error` — sonst; `tb = traceback.format_exc()`.

`on_done` mappt `kind` **1:1 auf das heutige Verhalten**:
`filenotfound` → `themed_showerror("Fehler", str(e))`;
`offline` → themed „Keine Internetverbindung"-Meldung;
`error` → `messagebox.showerror(..., traceback)`.

## Lauf-Feedback, Re-Entrancy, Close

- **Re-Entrancy:** `set_primary_button_enabled` ist laut Docstring
  (`theme.py`) **nur Optik** — die Klick-Bindung bleibt aktiv. Jeder
  `do_*`-Handler führt daher einen expliziten **`busy`-Guard** (Closure-Flag):
  bei laufender Operation ist der Klick ein No-op. Gleiches Muster wie der
  bestehende Kategorie-No-op in `export_dialog.do_export`.
- **Feedback:** Primär-Button `set_primary_button_enabled(btn, False)` + Text →
  „Sende…"/„Teile…"/„Erzeuge…". Da `primary_button` ein Frame+Label-Konstrukt
  ist (kein `config(text=…)` von außen; `_label` ist privat), kommt ein
  kleiner Helfer **`theme.set_button_text(btn, text)`** dazu — kein
  `_label`-Zugriff aus den Dialogen (vgl. Audit N17).
- **Fehler:** `busy`-Flag zurücksetzen; Button reaktivieren + Originaltext
  zurück (im `winfo_exists`-Guard). Im `share_dialog` läuft die Reaktivierung
  über `_refresh_send_btn()` (nicht blind enablen — der Button-Zustand hängt
  dort zusätzlich an Datentyp-/Kategorie-Checkboxen).
- **Erfolg:** Dialog schließen (falls noch offen) + Erfolgs-Toast auf `parent`.
- **Close während der Operation (Send/Share):** Der Worker läuft zu Ende (eine
  ggf. schon abgesendete Mail lässt sich nicht zurückholen; Persistenz
  überlebt). `on_done` findet den Dialog per `winfo_exists` weg →
  Ergebnis-Toast auf `parent`; auch der Traceback-Fehlerfall geht dann auf
  `parent` statt `dialog`. (Export: siehe Close-Sonderfall oben — Ergebnis
  wird verworfen.)

## Verdrahtung

- `open_send_dialog` / `open_share_dialog` / `open_export_dialog` bekommen einen
  **required** `runner`-Parameter (kein zweiter, synchroner Codepfad — konsistent
  mit `open_settings_dialog(..., runner=...)`).
- `ui.py` reicht `runner=self._bg` an allen drei Öffnungsstellen durch
  (`_send_report`, `_share`, `_export_pdf`).

## Tests

Tk-freie Unit-Tests je `perform_*` (in `tests/`), mit gemocktem
`generate_pdf` / `get_gmail_service` / `send_email` / `fetch_user_email`
(`build_share_doc` läuft auf dem UI-Thread und braucht keinen Mock —
`perform_share` bekommt den fertigen `payload`):

- Erfolg → `{"ok": True}` (+ `pdf_bytes` beim Export); Persistenz
  (`settings.set`) wurde aufgerufen — auch im „Dialog weg"-Fall, weil sie im
  Worker passiert.
- `offline` → `is_offline_error`-Pfad, `kind == "offline"`.
- generischer Fehler → `kind == "error"`, `tb` gesetzt.
- `FileNotFoundError` → `kind == "filenotfound"`.

Die dünne Tk-Verdrahtung (`do_send`/`do_share`/`do_export`-Closures, Button-
State) bleibt — wie bei H5 — ununit-getestet (headless-CI-Grenze, Audit M16).

## Betroffene Dateien

- **neu:** `src/dialogs/send_task.py`, `src/dialogs/share_task.py`,
  `src/dialogs/export_task.py`; `tests/test_send_task.py`,
  `tests/test_share_task.py`, `tests/test_export_task.py`.
- **geändert:** `src/dialogs/send_dialog.py`, `share_dialog.py`,
  `export_dialog.py` (Kern raus, Threading rein, `runner`-Param), `src/ui.py`
  (3× `runner=self._bg`), `src/theme.py` (neuer Helfer `set_button_text`),
  `src/CLAUDE.md` (Threading-Modell: send/share/export routen jetzt ebenfalls
  über den Runner).

## Nicht-Ziele (YAGNI)

- Kein Fortschrittsbalken / kein separates Status-Label (Button-Text reicht).
- Kein Abbrechen einer laufenden Operation (Netz-Call ist nicht rücknehmbar).
- Kein Backgrounding des lokalen Datei-Writes im Export (schnelles lokales IO).
