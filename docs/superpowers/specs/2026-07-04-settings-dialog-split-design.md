# Settings-Dialog: Aufteilung pro Tab (Audit H4)

> Design-Spec, 2026-07-04. Behebt Audit-Finding **H4** — `open_settings_dialog`
> ist eine ~900-Zeilen-God-Function. Branch `fix/settings-dialog-split`
> (gestackt auf #123 `fix/settings-dialog-threadvertrag`, da dieselbe Datei).

## Problem

`src/dialogs/settings_dialog.py` (Stand nach H5: 977 Zeilen) besteht fast
vollständig aus **einer** Funktion `open_settings_dialog` (Z. 75–977):

| Abschnitt | Zeilen | Umfang |
|---|---|---|
| Chrome + Notebook + `label`/`subheader`-Helfer | 75–121 | ~50 |
| Tab Arbeitszeit (Wochentag-Zeiten, Pause, WSL) | 123–212 | ~90 |
| Tab Bericht & Mail | 215–253 | ~40 |
| Tab Google (Konto/Sync/Kalender, alle 6 H5-Worker) | 256–696 | **~440** |
| Tab App (Bundesland, Checkboxen, Reminder, Skalierung) | 699–835 | ~140 |
| `save_settings` (Cross-Tab-Validierung + Persist) | 840–968 | ~130 |
| Buttons/Escape/Center | 970–977 | ~8 |

Dutzende Closures teilen sich einen Scope; `save_settings` liest ~25
Tk-Variablen aus allen vier Tabs plus `cal_map`/`tabs`/`notebook`. `src/CLAUDE.md`
beschreibt `App` als „kein God-Object mehr" — die Komplexität ist faktisch in
diesen Dialog gewandert (so auch das Audit).

## Entscheidungen (mit dem Nutzer abgestimmt)

1. **Ansatz A — Paket-Split pro Tab.** `settings_dialog.py` wird zum Paket;
   eine Klasse pro Tab (Audit-Hinweis „analog `_ImportSummaryDialog` als
   Klasse"). Kein Ansatz B (Funktions-Extraktion im selben File) und kein
   Ansatz C (verteilter `validate()`/`collect()`-Tab-Vertrag).
2. **`save_settings` bleibt zentral und ablaufidentisch** in `dialog.py` —
   die heikle Reihenfolge (Work-Validierung → WSL-Datum → Autostart-Toggle
   mit Abbruch **vor** jedem Persist → Reminder-Validierung → ein
   `apply_updates` → gcal-Kalender-ID nur bei geladener `cal_map` →
   WSL-Perioden-Scan → `on_change()` → `destroy()` → ggf.
   `on_request_restart`) wird **nicht** auf die Tabs verteilt. Nur die
   Variablen-Zugriffe wechseln von Closure-Scope auf Tab-Attribute.
3. **Verhaltensgleich pro Stelle** — reiner Struktur-Umbau, keine
   UI-/Logik-Änderung. Review-Kriterium wie bei den Refactors #49/DT-3.

## Ziel-Struktur

```
src/dialogs/settings_dialog/
  __init__.py     — re-exportiert open_settings_dialog + build_oauth_enable_task
  dialog.py       — open_settings_dialog: Chrome, Notebook, Tab-Instanzen,
                    save_settings, Buttons/Escape/Center        (~260 Zeilen)
  oauth_task.py   — build_oauth_enable_task (generischer OAuth-Toggle-Builder,
                    kein Tab-Bezug — eigenes Modul statt tab_google, damit die
                    bestehenden Tests genau EINE neue Import-Stelle haben)
  _shared.py      — label(...) / subheader(...) Grid-Helfer     (~25 Zeilen)
  tab_work.py     — class WorkTab                               (~150 Zeilen)
  tab_mail.py     — class MailTab                               (~70 Zeilen)
  tab_google.py   — class GoogleTab                             (~450 Zeilen)
  tab_app.py      — class AppTab                                (~170 Zeilen)
```

Alle bestehenden Import-Pfade bleiben gültig:
- `src/ui.py`: `from src.dialogs.settings_dialog import open_settings_dialog` —
  unverändert (Re-Export in `__init__.py`).
- `tests/test_settings_dialog.py`: importiert künftig aus
  `src.dialogs.settings_dialog.oauth_task` (einzige nötige Test-Änderung,
  weil der Test `sd.messagebox` **im Modul der Funktion** monkeypatcht —
  ein Paket-`__init__`-Re-Export reicht dafür nicht).

`tab_google.py` mit ~450 Zeilen bleibt das größte Modul — bewusst: eine
Verantwortlichkeit (Google-Integrations-UI), vom Audit ist nur der
Per-Tab-Schnitt gefordert. Eine weitere Unterteilung (Konto/Sync/Kalender)
ist YAGNI.

## Tab-Klassen-Vertrag

Jede Tab-Klasse baut in `__init__` ihre Widgets in den übergebenen
Notebook-Frame und exponiert als **Attribute** genau das, was `dialog.py`
(insb. `save_settings`) liest. Kein `validate()`/`collect()`-Protokoll.

```python
class WorkTab:
    def __init__(self, frame, dialog, settings): ...
    # frame           — der Notebook-Tab-Frame (für notebook.select bei Fehlern)
    # start_vars      — dict[weekday_key, tk.StringVar]
    # end_vars        — dict[weekday_key, tk.StringVar]
    # pause_var       — tk.StringVar
    # wsl_enabled_var — tk.BooleanVar
    # wsl_start_vars  — (day_var, month_var, year_var)  je tk.StringVar
    # wsl_end_vars    — (day_var, month_var, year_var)
    # wsl_hours_var   — tk.StringVar
    # (dialog nur als Parent für open_category_dialog)

class MailTab:
    def __init__(self, frame, settings): ...
    # frame, recipient_var, name_var, rate_var, subject_var, greeting_var,
    # content_text (tk.Text), closing_text (tk.Text)

class GoogleTab:
    def __init__(self, frame, dialog, settings, base_path, on_change, runner,
                 storage, conflicts_store, reservation_store,
                 data_lock, sync_guard): ...
    # frame, cal_map (dict summary->id, von _populate_calendars mutiert,
    #                 von save_settings gelesen), cal_var (tk.StringVar)
    # Alles andere (creds-Status-Timer, Absender, Sync-Toggle, Konflikte,
    # Import, Reconnect, Kompaktierung, Kalenderliste) bleibt intern.

class AppTab:
    def __init__(self, frame, settings): ...
    # frame, state_var, show_weekend_var, autostart_var, always_on_top_var,
    # minimize_to_tray_var, scale_var (tk.DoubleVar),
    # reminders_enabled_var, reminder_minutes_var
```

Festlegungen im Detail:

- **`_shared.py`:** `label(parent_frame, text, row, col=0, **grid_kw)` und
  `subheader(parent_frame, text, row, top_pad=16)` — byte-gleich zu heute
  (Z. 109–120), nur `parent_frame` explizit statt Closure-`BG`/`FONT`-Zugriff
  (die Theme-Konstanten importiert `_shared.py` selbst).
- **`WorkTab`** enthält `_wsl_date_row` als private Methode; der
  „Kategorien verwalten"-Button nutzt `dialog` als Parent (deshalb der Param).
- **`GoogleTab`** übernimmt `creds_path = os.path.join(base_path,
  "credentials.json")` (heute Z. 95 — wird nur im Google-Tab genutzt) und den
  periodischen `dialog.after(500, refresh_status)`-Timer unverändert. Die
  H5-Worker (`runner.run`-Muster, `winfo_exists`-Guards, Persistenz im `fn`)
  ziehen **unverändert** mit um — H4 darf H5 nicht aufweichen.
- **`AppTab`:** der `ttk.Style` für den Skalierungs-Slider wird mit dem
  Tab-Frame als Master erzeugt (`ttk.Style(frame)`) — Styles sind
  Interpreter-global, das `dialog`-Handle ist dafür nicht nötig.
- **`dialog.py`** behält: `create_dialog`, `apply_combobox_style`/
  `apply_notebook_style`, Notebook + 4 Frames, `tabs`-Dict
  (`{"work": work.frame, ...}`), `save_settings` (liest `work.*`, `mail.*`,
  `google.cal_map`/`cal_var`, `app.*`), Speichern/Abbrechen-Buttons,
  `attach_unfocus_on_click`, Escape-Bind, `center_dialog_on_parent`.
- **`oauth_task.py`:** `build_oauth_enable_task` zieht unverändert um
  (inkl. Docstring); `tab_google.py` importiert es von dort.

## Migrationspfad (pro Schritt grün)

1. **Paket-Skelett:** `settings_dialog.py` → `settings_dialog/dialog.py`
   (inhaltlich unverändert) + `__init__.py`-Re-Exports +
   `build_oauth_enable_task` → `oauth_task.py` + Test-Import angepasst.
2. **`_shared.py` + `WorkTab`** herauslösen; `save_settings` liest `work.*`.
3. **`MailTab`**, 4. **`AppTab`**, 5. **`GoogleTab`** (der Brocken, zuletzt —
   das Muster steht dann).
6. **Doku:** `src/CLAUDE.md` (Dialoge-Absatz: Paket-Struktur + Tab-Vertrag;
   der Satz zur H5-Runner-Konvention bleibt korrekt).

Nach jedem Schritt: Gesamtsuite (750) + `ruff check .` grün. Kein Schritt
lässt die App in einem nicht-lauffähigen Zwischenzustand.

## Verifikation

- **Suite + Ruff** nach jedem Migrationsschritt (die 5 Builder-Tests aus H5
  laufen weiter; nur ihr Import-Pfad ändert sich in Schritt 1).
- **Import-Smoke:** `python -c "import src.ui"` nach jedem Schritt.
- **Interaktiver End-Smoke (Nutzer):** Dialog öffnen, alle 4 Tabs durchsehen,
  einmal Speichern mit geänderten Werten, einmal Validierungsfehler
  provozieren (z. B. Reminder-Minuten „abc") → springt auf den App-Tab.
- **Zeilen-Bilanz als Abnahme:** `dialog.py` ≤ ~300 Zeilen; kein Modul außer
  `tab_google.py` über ~200; `open_settings_dialog` enthält keine
  Widget-Bau-Blöcke der Tabs mehr.

## Ausdrücklich außerhalb des Scopes

- **Keine Verhaltensänderung** — auch keine „Gelegenheits-Fixes" (z. B. der
  hartkodierte Font `("Segoe UI", 8)` in Z. 252 / Audit-Randnotiz, M14
  Datums-Zeilen-Deduplizierung, M10 Blocking-Sendepfad). Solche Funde werden
  notiert, nicht gefixt.
- **Kein Tab-Vertrag mit `validate()`/`collect()`** (Ansatz C) — bewusst
  verworfen, siehe Entscheidungen.
- **Keine neuen Tests für Tk-gebundene Tab-Klassen** (M16-Konvention);
  abgesichert wird über Suite + Smoke.
