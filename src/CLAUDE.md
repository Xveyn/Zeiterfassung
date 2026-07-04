# src/ — Architektur & Aufbau

Detail-Referenz zum inneren Aufbau von `src/`. Ergänzt die Modul-Liste und die
Konventionen aus der Projekt-`CLAUDE.md` im Repo-Root (Datumsformat, Klick-Modell,
UTF-8-Mail-Pipeline, Lazy-Google-Imports für CI) — die gelten hier weiter und werden
**nicht** wiederholt.

> **Diese Datei pflegen.** Wer eine Verantwortlichkeit verschiebt, eine Komponente
> hinzufügt/entfernt oder einen der unten beschriebenen Verträge ändert, aktualisiert
> diese Datei im selben PR. Sie ist die Karte des Aufbaus; veraltet ist sie schlimmer
> als gar nicht vorhanden.

## Schichten-Überblick

```
main.py  ── Einstiegspunkt: Tk-Root + Storage/Settings/App, --minimized, Sync-Pull-Thread
   │
   ▼
ui.py::App  ── schlanker KOORDINATOR (kein God-Object mehr)
   ├─ besitzt: Datum/View-State (year/month/view_mode/iso_year/current_week),
   │           Header-/Footer-/Tray-Chrome, Dialog-Routing, Navigation
   ├─ delegiert an vier Komponenten ▼
   │
   ├─ GridRenderer        (grid_renderer.py)   — Kalender-/Grid-Rendering
   ├─ BackgroundTaskRunner(background_tasks.py) — Hintergrund-Worker + Thread-Mechanik
   ├─ SyncOrchestrator    (sync_orchestrator.py)— Drive-Sync (manuell/Tray/Pull/Quit)
   └─ UpdateBanner        (update_banner.py)    — GitHub-Release-Hinweis
```

`App` hält den fachlichen Zustand und die Widget-Chrome (Header/Footer/Tray), die
Komponenten kapseln je eine Verantwortlichkeit. Datenfluss läuft App → Komponente
(per Methodenaufruf / Konstruktor), Rückfluss per **injizierten Callbacks** (App reicht
z.B. `_open_dialog`/`_refresh` rein) — die Komponenten importieren `src.ui` **nicht**
(kein Zyklus).

## Die vier App-Komponenten und ihre Verträge

### GridRenderer (`grid_renderer.py`)
Rendering der Monats-/Wochenansicht inkl. Double-Buffer und Fenster-Geometrie.
- **Datum/View gehört App**, nicht dem Renderer: `refresh(view_mode, year, month, iso_year,
  current_week)` bekommt den aktuellen Stand pro Render übergeben (kein Dual-State).
  `App._refresh()` ist nur ein dünner Shim, der diese 5 Werte weiterreicht — er ist der
  **eine** Render-Eintritt für alle Aufrufer (Navigation, Dialog-`on_change`, Sync-/
  Reconcile-Callbacks `on_refresh`/`on_ok`).
- **Interaktion injiziert:** `on_cell_click` (= `App._open_dialog`), `on_cell_right_click`
  (= `App._delete_day`), `reservations_active` (= `App._reservations_active`). Die Zellen
  binden diese Callbacks, nicht App-Methoden direkt.
- **Widgets:** der Renderer besitzt `grid_container` + die zwei Double-Buffer-Frames
  (`build_grid(parent)`); `header_label`/`footer_label` werden in `App._build_header`/
  `_build_footer` erzeugt und per `attach_labels(...)` nachgereicht (der Renderer beschreibt
  sie). `measure_max_width(...)` pinnt vor `mainloop()` die Fensterbreite (4-Kombi-Probing).
- **Fenster-Geometrie:** `repin_geometry()` setzt Breite (≥ gemessenes Maximum) und Höhe
  (aktuelle reqheight) neu auf das fixe Fenster. Genutzt vom View-/Spalten-Wechsel in
  `refresh()`, beim Wechsel der Footer-Reservierungsbreite (Stundenlohn zur Laufzeit
  gesetzt/entfernt — `_update_footer` reserviert 16 vs. 40 Zeichen, s.u.) **und** extern vom
  `UpdateBanner` (als `on_resize`), dessen Ein-/Ausblenden die nötige Höhe ändert, ohne
  View/Spalten zu wechseln. `resizable(False, False)` bleibt.
- `_fmt_slot_line` ist `@staticmethod`; `App._delete_day` ruft es als
  `GridRenderer._fmt_slot_line(...)` (bleibt in App, nutzt aber den Renderer-Static).

### BackgroundTaskRunner (`background_tasks.py`)
Thread-Mechanik **und** die proaktiven Startup-Tasks.
- `run(fn, on_done=None)` ist **der** Thread-Helfer: führt `fn()` im Daemon-Thread aus,
  liefert das Ergebnis via `marshal` (= `App._marshal_to_ui`) an `on_done` auf dem
  **UI-Thread**. Auch `SyncOrchestrator` nutzt `run()` — es gibt nur dieses eine Muster.
- Eigene Tasks: `refresh_token`, `fetch_sender_email`, `check_update`, `reconcile_on_start`,
  `trigger_reconcile`. UI-Arbeit (Dialoge/Banner/Refresh) bleibt in App und kommt als Callback.
- Tk-frei, keine Google-Imports auf Modulebene; `run_calendar_reconcile` wird **lazy in der
  Methode** aus `src.main` importiert (Circular-Import-Schutz: `main → ui → background_tasks`).

### SyncOrchestrator (`sync_orchestrator.py`)
Drive-Sync: manueller Sync, Tray-Sync, Pull-Callbacks, Status-Label, Quit-Push, Fehler-
Aufbereitung (`_classify_sync_error`/`_friendly_sync_message`/`_show_sync_error` — auch von
Tests genutzt). Reine Formatier-Helfer `_status_text`/`_tray_toast` sind ohne Tk testbar.
- Header-Widgets per `attach_widgets(...)`; Tray **lazy** über `get_tray=lambda: App._tray`
  (einzige Quelle bleibt `App._tray`); `_run_push_blocking` lazy aus `src.main`.
- `App.on_sync_pull_success`/`on_sync_pull_error` bleiben als dünne Delegatoren (Public-API
  für `main.py`). `tray.stop()`/`root.destroy()` bleiben in `App._quit_with_sync_push`.

### UpdateBanner (`update_banner.py`)
Banner über dem Kalender (anzeigen/Download/ausblenden). `handle_check_result(release, newer)`
ist das `on_result` von `BackgroundTaskRunner.check_update`. Pack-Anker **lazy** über
`get_anchor=lambda: App._renderer.grid_container` (Grid existiert erst nach dem Build).
`on_resize` (= `App._renderer.repin_geometry`) wird in `_show`/`_dismiss` aufgerufen, damit
das fixe Fenster auf die geänderte Banner-Höhe nachzieht (sonst Footer abgeschnitten, #92).

## Threading-Modell

Genau ein Muster: Hintergrundarbeit über `BackgroundTaskRunner.run(fn, on_done)`; jede
State-/Widget-Mutation aus einem Worker läuft über `App._marshal_to_ui` (`root.after(0, …)`,
gegen `TclError` abgesichert, falls das Fenster zwischenzeitlich zu ist). Keine direkten
`threading.Thread`-Aufrufe in `ui.py` mehr.

**Datenschicht-Locking (Audit H1/H2/M1):** Alle vier Stores
(`storage`/`settings`/`conflicts_store`/`reservations`) teilen sich einen in
`main()` erzeugten `RLock` (Konstruktor-Param `lock=`; ohne Injektion legt
jeder Store einen eigenen an — Tests bleiben unverändert). Die Sync-Flows
(`_run_pull_in_background`/`_run_push_blocking`/`_run_compaction_blocking`/
`reconcile_reservations`) klammern Snapshot→Merge→Apply mit diesem `data_lock`
— **nie über Netzwerk-Calls**. Ein separater plain `threading.Lock`
(`sync_guard`) serialisiert alle Drive-Sync-Einstiege (Startup-Pull, Manual-,
Tray-, Quit-Push, Kompaktierung): non-blocking-skip mit
`{"skipped": True}`-Result, nur der Quit-Push wartet (`guard_timeout=5`).
Acquired UND released wird der Guard im innersten Worker-Thread (`finally`,
nach der letzten Store-Mutation) — nie in UI-Callbacks, nie beim Join-Timeout;
er MUSS plain `Lock` bleiben (cross-thread release). Neue Sync-Einstiege
müssen beide Locks respektieren. Design:
`docs/superpowers/specs/2026-07-04-datenschicht-threadsicherheit-design.md`.

## Daten- & Persistenz-Schicht

- `storage.py` — Ist-Zeiten (JSON, Schlüssel = ISO-Datum). `reservations.py` — Reservierungen
  (zukünftige Soll-Zeiten, eigenes Konzept). `settings.py` — Einstellungen mit Defaults.
- `conflicts_store.py` — lokale Sync-Konfliktliste. `category_defaults.py` — Default-Kategorien.
- `sync.py` — pure Sync-Logik (LWW-Merge, Konflikterkennung); importiert
  `SYNCED_SETTING_KEYS` aus `settings.py` (Single Source of Truth, nicht hier neu definieren).
  `share.py` — Export/Import als Share-JSON. `weekly_limit.py` — pure Wochenstunden-Limit-Check
  (Werkstudenten-Privileg, #98). Kein eigener Persistenz-Zustand, operiert auf
  `Storage.get_all()`-Dicts und den `werkstudent_limit_*`-Settings-Keys.
  `reminders.py` — pure Fälligkeits-Logik für Reservierungs-Erinnerungen (Tk-frei, `now` als Parameter): pro heutigem reservierten Slot mit Kategorie ohne erfasste Ist-Zeit `upcoming` (N Min vor Ende) oder `missed` (nach Ende). Der `ReminderScheduler` (`reminder_scheduler.py`) pollt minütlich über `root.after` und schickt fällige Toasts über `App._tray`.

## Google-Integration (alle Wrapper mit Lazy-Imports für CI ohne requirements.txt)

`mail.py` (Gmail/OAuth, `token.json`/`credentials.json`), `drive.py` (Drive appDataFolder-Sync),
`gcal.py` (Calendar), `reservations_sync.py` (Abgleich Reservierungen ↔ Kalender). Alle teilen
denselben OAuth-Token; Scope-Upgrade erzwingt frischen Consent.

## Berichte & Plattform/Infra

- `report.py` — HTML-Mail + PDF (xhtml2pdf **lazy**), gruppiert pro ISO-KW.
- `theme.py`/`tooltip.py` — UI-Hilfen (Farben/Fonts/themed Dialoge, `_hover`-Overlays).
- `time_utils.py` — Stunden, KW-Labels, `format_iso_date`/`format_iso_datetime`.
- `holidays_de.py`, `paths.py` (`get_base_path` Frozen-vs-Repo), `updater.py`
  (GitHub-Releases, stdlib-only, 1×/Tag), `platform_open.py`, `logging_setup.py`,
  `version.py` (einzige Versions-Quelle).
- `autostart.py` — plattformabhängig (Windows-Registry HKCU Run / macOS-LaunchAgent / Linux-.desktop).
  Windows-Backend nutzt den **Registry-Wert `Zeiterfassung`** (Wertname = `installer.iss` → strukturell
  ein Eintrag); `import winreg` lazy (CI-Ubuntu). `is_autostart_enabled()` liest den echten Zustand
  (Registry-Wert **oder** Alt-Startup-Shortcut als Fallback, falls Migration scheitert).
  `migrate_legacy_autostart()` überführt Alt-Shortcuts in den Registry-Key, ist aber frozen-gated
  (Repo-Modus: No-op, würde andernfalls python.exe+Repo ins Register schreiben und bestehende
  Shortcuts beschädigen).
- `single_instance.py` — Tk-freier Single-Instance-Guard. Erste Instanz leitet einen Port aus
  `get_base_path()` ab und bindet einen Listener (`SO_EXCLUSIVEADDRUSE` Windows, `SO_REUSEADDR` Unix).
  Folgeinstanzen melden sich per SHOW/PING-Protokoll und beenden sich. `main.py` ruft `acquire()`
  vor dem Tk-Aufbau, `serve(show_fn)` danach. `App.restart_for_scaling` und `_quit_with_sync_push`
  rufen `release()`. Blockiert den Start nie — ist der Port von Fremd-Software belegt (keine ZEIT-OK),
  läuft die App ungeschützt weiter (geloggt, akzeptierter Degraded-Fall).
- `tray.py` (Fassade) + `tray_mac.py` (natives macOS-NSStatusItem-Backend, #88).

Das Tray-Icon läuft, sobald `minimize_to_tray` **oder** `reminders_enabled` aktiv ist (`ui.py::_apply_tray_setting`); bei nur `reminders_enabled` dient es ausschließlich als Toast-Kanal.

## Dialoge (`src/dialogs/`)

Modale Tk-Dialoge, von `App` geroutet (Klick-Modell: Linksklick = bearbeiten, Rechtsklick =
löschen — siehe Root-`CLAUDE.md`): `entry_dialog` (Tages-Dialog, rein zum Speichern),
`send_dialog`, `export_dialog` (Zeitraum-Modal → PDF lokal speichern),
`settings_dialog` (4 Tabs über `ttk.Notebook`: Arbeitszeit / Bericht & Mail / Google / App; Dark-Styling via `theme.apply_notebook_style`), `share_dialog`, `import_dialog`, `category_dialog`,
`conflicts_dialog`. `period_picker` ist kein Dialog, sondern der von
`send_dialog` + `export_dialog` geteilte Zeitraum+Kategorie+Vorschau-Baustein.

## Wo gehört neuer Code hin?

- Rendering/Zell-Logik → `grid_renderer.py`. Neuer Hintergrund-Task → `background_tasks.py`
  (über `run()`). Sync-Verhalten → `sync_orchestrator.py`. Reine Persistenz/Logik → der
  passende Store bzw. `sync.py`/`share.py` (Tk-frei, gut testbar).
- In `App` (ui.py) bleibt nur Koordination: Datum/View-State, Chrome-Aufbau, Dialog-Routing,
  Navigation, das `_marshal_to_ui`/`_refresh`-Glue. Wächst eine Verantwortlichkeit dort, ist
  das das Signal für die nächste Komponente — und für ein Update dieser Datei.
