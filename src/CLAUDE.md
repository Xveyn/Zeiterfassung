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
  `_build_footer` erzeugt und per `attach_labels(header_label, footer_label,
  header_width_spacer)` nachgereicht (der Renderer beschreibt sie). `header_label` selbst
  hängt **nicht** im pack-Fluss von `header_frame`, sondern wird per `place(relx=0.5, …)`
  absolut auf die Fensterbreite zentriert — sonst würde es je nach Breite der rechten
  Sync-Button-Gruppe (Status-Text ändert sich laufend) sichtbar verrutschen. Damit
  `header_label`s Breitenbedarf trotzdem in `measure_max_width` einfließt (place-Kinder
  zählen nicht zur reqwidth), steht an seiner alten pack-Position ein unsichtbarer
  `header_width_spacer`, dessen `font`/`width` `refresh()` synchron zum echten
  `header_label` hält. `measure_max_width(...)` pinnt vor `mainloop()` die Fensterbreite
  (4-Kombi-Probing).
- **Fenster-Geometrie:** `repin_geometry()` setzt Breite (≥ gemessenes Maximum) und Höhe
  (aktuelle reqheight) neu auf das fixe Fenster. Genutzt vom View-/Spalten-Wechsel in
  `refresh()`, beim Wechsel der Footer-Reservierungsbreite (Stundenlohn zur Laufzeit
  gesetzt/entfernt — `_update_footer` reserviert 20 vs. 42 Zeichen, s.u.) **und** extern vom
  `UpdateBanner` (als `on_resize`), dessen Ein-/Ausblenden die nötige Höhe ändert, ohne
  View/Spalten zu wechseln. `resizable(False, False)` bleibt. Die **Breite ratcht**:
  `_fixed_width` wächst mit der breitesten je angeforderten reqwidth mit, schrumpft aber nie
  wieder — startet die App ohne Lohn (schmaler Footer, `measure_max_width` pinnt schmal) und
  der Nutzer trägt später einen Lohn ein, wächst das Fenster einmalig auf die breite Variante
  und bleibt dort. Ohne Ratchet spränge es bei jedem Lohn-Ein/Aus zwischen schmal und breit
  (Test: `tests/test_grid_geometry.py`). Die Höhe ratcht bewusst nicht (Banner braucht beide
  Richtungen).
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
Banner über dem Kalender (anzeigen/Download/ausblenden). `show_if_newer(release)` prüft nur
`dismissed_version` und zeigt ggf. an; Persistenz von `last_update_check_at` und Toast-vs.-
Banner-Routing liegen in `ui.py::_on_update_check_result` bzw.
`_route_update_notification(...)`. Pack-Anker **lazy** über
`get_anchor=lambda: App._renderer.grid_container` (Grid existiert erst nach dem Build).
`on_resize` (= `App._renderer.repin_geometry`) wird in `_show`/`_dismiss` aufgerufen, damit
das fixe Fenster auf die geänderte Banner-Höhe nachzieht (sonst Footer abgeschnitten, #92).

## Threading-Modell

Genau ein Muster: Hintergrundarbeit über `BackgroundTaskRunner.run(fn, on_done)`; jede
State-/Widget-Mutation aus einem Worker läuft über `App._marshal_to_ui` (`root.after(0, …)`,
gegen `TclError` abgesichert, falls das Fenster zwischenzeitlich zu ist). Keine direkten
`threading.Thread`-Aufrufe in `ui.py` **oder den Dialogen** mehr — auch `settings_dialog`
routet seine Worker seit Audit H5 über einen injizierten `BackgroundTaskRunner`
(`open_settings_dialog(..., runner=App._bg)`): Persistenz im Worker (überlebt
Dialog-Close), UI-Feedback im `winfo_exists`-geschützten `on_done`.

Ebenso routen `send_dialog`/`share_dialog`/`export_dialog` ihre blockierenden
Operationen (PDF-Erzeugung, `get_gmail_service` inkl. OAuth, `send_email`) über
den injizierten `runner` (Audit M10): der blockierende Kern liegt Tk-frei in
`send_task`/`share_task`/`export_task` (`perform_*`, getestet); die zwei
Netz-Kerne teilen sich `mail_task.classify_mail_error`. `on_done` macht das
`winfo_exists`-gegatete Feedback, Persistenz passiert im Worker (überlebt
Dialog-Close), der Primär-Button ist während des Laufs deaktiviert.

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
  `SYNCED_SETTING_KEYS` aus `settings.py` **und** `_REQUIRED_ENTRY_KEYS` aus `storage.py`
  (beide Single Source of Truth, nicht hier neu definieren). `validate_remote_doc`
  prüft ein migriertes Remote-Doc auf die Merge-Invarianten (Pflichtfelder,
  `modified_at`-Typ), bevor ein `KeyError`/`ValueError` mitten im Merge landet
  (Audit M5) — die Sync-Flows in `main.py` behandeln ein invalides Doc wie
  korruptes JSON (quarantänen/leer weitermergen).

  **Tombstone-Lebenszyklus (Audit N6).** Ein Tombstone (`deleted: True`) hat
  genau einen Zweck: beim Merge ein veraltetes Save eines anderen Geräts zu
  schlagen. Er wird auf drei Wegen wieder los — und nur auf diesen:
  1. **Kompaktierung** (`compact_local` via `main._run_compaction_blocking`) —
     setzt das `gc_watermark` und strippt settled Tombstones lokal wie remote.
     Der einzige Weg für Geräte, die am Sync teilnehmen; der Button hängt
     deshalb an „hat je gesynct", nicht an `sync_enabled` (sonst säßen
     Abschalter dauerhaft auf ihren Tombstones).
  2. **Reconcile** für Reservierungen (`reservations_sync._merge_one_date`,
     Fall 3) — löst den Tombstone gegen die Kalender-Events ein.
  3. **Startup-Sweep** (`sync.drop_orphan_tombstones` /
     `reservations_sync.drop_orphan_reservation_tombstones`, gebündelt in
     `main._sweep_orphan_tombstones`) — verwirft Tombstones auf Rechnern, die
     **nie** gesynct/abgeglichen haben (`never_synced` / `never_reconciled`).
     Dort gibt es keinen Partner, gegen den sie je wirken könnten.

  Die Bedingung des Sweeps ist bewusst eng: Feature AUS reicht nicht, es muss
  **nie an** gewesen sein. Wer den Sync abschaltet, dessen Remote kennt die
  gelöschten Tage weiter — ein verworfener Tombstone hieße, dass sie beim
  Wiedereinschalten zurückkommen. Wer einen vierten Weg baut, muss diese
  Unterscheidung mitziehen.

  „Nie gesynct/abgeglichen" leiten `never_synced`/`never_reconciled` aus
  settings.json ab — das allein genügt dem Sweep aber **nicht**: ein korruptes
  settings.json setzt `Settings` auf Defaults zurück (M4) und ließe einen
  tatsächlich gesyncten Rechner wie jungfräulich aussehen (→ Resurrection).
  Deshalb vetoed der persistente `sync_history`-Marker (eigene Datei
  `sync_history.json`, übersteht einen settings.json-Reset) den jeweiligen
  Sweep, sobald je gesynct/abgeglichen wurde. Der Marker wird genau dort
  gesetzt, wo `last_pull_at`/`last_calendar_sync_at` gesetzt werden, und ist
  fail-safe (unlesbar → als gesetzt behandeln). Ein neuer Sync/Reconcile-Pfad
  muss ihn mitsetzen.
- `sync_history.py` — persistenter „hat je gesynct/abgeglichen"-Marker
  (`sync_history.json`, write-once, Tk-frei, fail-safe). Vetoed den
  N6-Startup-Sweep, damit ein settings.json-Reset (M4) einen gesyncten Rechner
  nicht wie jungfräulich aussehen lässt (s. Tombstone-Lebenszyklus oben).
- `sync_journal.py` — Crash-Recovery für `sync.apply_merged_doc` (Audit M6): dessen
  vier Store-Writes sind einzeln atomar, die Sequenz nicht. `apply_merged_doc_journaled`
  schreibt den `merged_doc` erst durable (`fsync`) in ein Write-Ahead-Journal
  (`sync-apply.journal` im Base-Dir), dann die Stores, dann löscht es das Journal.
  `main.py` ruft die drei Sync-Apply-Stellen (Pull/Push/Kompaktierung) darüber; beim
  Start holt `recover_pending_apply` ein übriggebliebenes Journal idempotent nach
  (alle vier Ops sind Full-Replace). **Kein** Sync-Doc-Feld — rein lokaler
  Recovery-Zustand.
  `share.py` — Export/Import als Share-JSON. `weekly_limit.py` — pure Wochenstunden-Limit-Check
  (Werkstudenten-Privileg, #98). Kein eigener Persistenz-Zustand, operiert auf
  `Storage.get_all()`-Dicts und den `werkstudent_limit_*`-Settings-Keys.
  `pause_requirement.py` — pure Pausenpflicht-Check nach §4 ArbZG (30 Min ab
  >6h, 45 Min ab >9h Netto-Arbeitszeit), analog `weekly_limit.py` aber ohne
  Zeitraum-Konzept (die Pflicht gilt für jeden Tag einzeln). Zählt nur die
  `pause`-Felder der Slots — eine Lücke zwischen zwei Slots desselben Tages
  (z.B. Mittagspause per Kommen/Gehen) zählt nicht mit; `entry_dialog.py`
  macht das im Warntext transparent. `pause_warning_enabled` ist Default
  `True` (Opt-out), anders als das Werkstudenten-Limit (Opt-in) — die Pflicht
  betrifft praktisch jeden Angestellten in DE, ist kein Sonderfall.
  `workweek.py` — Nur-Werktage-Modus (`workweek_only`, synchronisiert). `is_weekend`
  (unlesbarer Schlüssel → False, Filtern darf nichts verschlucken),
  `filter_for_report` (inaktiv → dasselbe Dict, kein Kopieren) und
  `count_weekend_entries` für die Hinweiszeile. Gefiltert wird am **Snapshot**
  (`storage.get_all()` in send_dialog/export_dialog/period_picker), NICHT in
  `report.py` — das bleibt settings-frei, und Mail-HTML, PDF und Vorschau sehen
  dadurch automatisch dieselben Daten. Im Kalender überstimmt die Flag
  `show_weekend` (`grid_renderer._visible_day_count`); in den Standardzeiten
  entfallen die Sa/So-Zeilen, ihre `StringVar`s aber nicht — der Speicherpfad
  schreibt weiter alle sieben Tage, damit die Werte erhalten bleiben. Bewusst
  unberührt: Werkstudenten-Limit (zählt real geleistete Stunden), Teilen und
  Kalender-Abgleich.
  `reminders.py` — pure Fälligkeits-Logik für Reservierungs-Erinnerungen (Tk-frei, `now` als Parameter): pro heutigem reservierten Slot mit Kategorie ohne erfasste Ist-Zeit `upcoming` (N Min vor Ende) oder `missed` (nach Ende). Der `ReminderScheduler` (`reminder_scheduler.py`) pollt minütlich über `root.after` und schickt fällige Toasts über `App._tray`; auf Windows via `tray.notify_action` mit „Arbeitszeit eintragen"-Button (WinRT, Fallback Plain-Toast), der den Slot als Ist-Zeit schreibt (`_log_reservation` → `ist_slot_from_reservation`, Pause aus Kategorie-Default). Analog dazu `send_reminder.py`/`send_reminder_scheduler.py`: ein einzelner Fällig-Zeitpunkt pro Monat (Tag + Uhrzeit, Tag auf die Monatslänge geclamped) statt Slot-Fenster; der Fired-Zustand wird bewusst **persistiert** (`settings.send_reminder_last_fired_month`, `"YYYY-MM"`) statt nur im Speicher gehalten wie beim Reservierungs-Reminder — verhindert wiederholte Toasts bei App-Neustarts im selben Monat.

## Google-Integration (alle Wrapper mit Lazy-Imports für CI ohne requirements.txt)

`mail.py` (Gmail/OAuth, `token.json`/`credentials.json`), `drive.py` (Drive appDataFolder-Sync),
`gcal.py` (Calendar), `reservations_sync.py` (Abgleich Reservierungen ↔ Kalender). Alle teilen
denselben OAuth-Token; Scope-Upgrade erzwingt frischen Consent.

Geschrieben wird der Token ausschließlich über `oauth_utils.write_token`: Temp-Datei →
Härtung → `os.replace` (mit `PermissionError`-Retry, #135). Zur Härtung siehe
`secure_file` unten.

`drive.find_sync_file` liefert bei mehreren Treffern deterministisch die
**älteste** Datei (`createdTime`, Tie-Break `id`) — der appDataFolder kennt kein
atomares create-if-not-exists, zwei Geräte können beim Erst-Setup also beide
anlegen (Audit M3). Die Regel ist die einzige Klammer, die alle Geräte auf
dieselbe Datei zwingt: ohne sie liefen die Stände auseinander, und da die
Drive-API ohne `orderBy` keine Sortierung garantiert, könnte sogar dasselbe
Gerät zwischen zwei Syncs die andere Datei erwischen. Wer die Auswahl anfasst,
muss sie deterministisch **und** über alle Geräte gleich halten.

## Berichte & Plattform/Infra

- `report.py` — HTML-Mail + PDF (xhtml2pdf **lazy**), gruppiert pro ISO-KW.
- `theme.py`/`tooltip.py` — UI-Hilfen (Farben/Fonts/themed Dialoge, `_hover`-Overlays).
- `time_utils.py` — Stunden, KW-Labels, `format_iso_date`/`format_iso_datetime`.
- `holidays_de.py`, `paths.py` (`get_base_path` Frozen-vs-Repo), `updater.py`
  (GitHub-Releases, stdlib-only, Frequenz über `update_check_frequency`, Pre-Release-Opt-in über `prerelease_updates_enabled`), `changelog.py`
  (lädt/parst den Changelog-Abschnitt einer Release-Version vom GitHub-Tag), `platform_open.py`, `logging_setup.py`,
  `version.py` (einzige Versions-Quelle).
- `autostart.py` — plattformabhängig (Windows-Registry HKCU Run / macOS-LaunchAgent / Linux-.desktop).
  Windows-Backend nutzt den **Registry-Wert `Zeiterfassung`** (Wertname = `installer.iss` → strukturell
  ein Eintrag); `import winreg` lazy (CI-Ubuntu). `is_autostart_enabled()` liest den echten Zustand
  (Registry-Wert **oder** Alt-Startup-Shortcut als Fallback, falls Migration scheitert).
  `migrate_legacy_autostart()` überführt Alt-Shortcuts in den Registry-Key, ist aber frozen-gated
  (Repo-Modus: No-op, würde andernfalls python.exe+Repo ins Register schreiben und bestehende
  Shortcuts beschädigen).
- `secure_file.py` — Zugriffsschutz für die beiden lokal abgelegten Secrets: `token.json`
  (`oauth_utils.write_token`) und `instance-secret` (`single_instance._write_secret_atomic`).
  Beide Schreibpfade laufen Temp-Datei → `chmod 0600` → `harden_windows_acl` → `os.replace`.
  Unter Windows ist chmod ein No-op, deshalb dort zusätzlich `icacls /inheritance:r
  /grant:r <user>:(F)` (Audit M8): geerbte ACEs (u.a. SYSTEM, lokale Administratoren) raus,
  genau ein Berechtigter bleibt. **Vollzugriff** statt R/W, weil das spätere `os.replace`
  DELETE auf der Zieldatei braucht; **auf der Temp-Datei**, damit die Datei nie kurz mit
  geerbten Rechten am Zielpfad liegt. Best-effort und nie fatal (fehlendes `icacls`, kein
  benennbarer Principal → loggen und weiter): ungehärtet ist der Status quo, eine
  gescheiterte Persistenz wäre eine Regression. Eigenes Modul, damit `single_instance`
  nichts aus dem OAuth-Umfeld importieren muss (und keiner den privaten Namen des anderen
  nutzt, Audit N17). Wer einen dritten Secret-Schreibpfad baut, ruft diesen Helfer mit auf.
- `single_instance.py` — Tk-freier Single-Instance-Guard. Erste Instanz leitet einen Port aus
  `get_base_path()` ab und bindet einen Listener (`SO_EXCLUSIVEADDRUSE` Windows, `SO_REUSEADDR` Unix).
  Folgeinstanzen melden sich per SHOW/PING-Protokoll und beenden sich. `main.py` ruft `acquire()`
  vor dem Tk-Aufbau, `serve(show_fn)` danach. `App.restart_for_scaling` und `_quit_with_sync_push`
  rufen `release()`. Blockiert den Start nie — ist der Port von Fremd-Software belegt (keine ZEIT-OK),
  läuft die App ungeschützt weiter (geloggt, akzeptierter Degraded-Fall).
- `device_id.py` — stabile, hardware-abgeleitete Geräte-ID (`derive_device_id()`, SHA-256 mit
  App-Salt über Windows `MachineGuid`/macOS `IOPlatformUUID`/Linux `/etc/machine-id`) für installierte
  Builds; übersteht damit eine Neuinstallation, anders als eine reine Zufalls-UUID. `main.py::
  _ensure_device_id` nutzt das NUR bei `sys.frozen` — Repo-/Skript-Modus (`python -m src.main`) bleibt
  bewusst bei der alten, in `settings.json` persistierten Zufalls-UUID (sonst hätte eine parallel zu
  einer echten Installation laufende Dev-Instanz auf demselben Rechner dieselbe device_id). Resolver
  liefern `None` statt zu werfen; `_ensure_device_id` fällt dann ebenfalls auf die Zufalls-UUID zurück.
- `main.py::_hold_app_mutex` — hält einen benannten Win32-Mutex (`_APP_MUTEX_NAME`, nur installierte
  Windows-Builds) für die Prozesslaufzeit; reiner Existenz-Marker für `installer.iss` (`AppMutex=`
  dort muss exakt zum Namen hier passen). Setup erkennt darüber eine laufende Instanz und lässt den
  User sie manuell schließen (Retry-Dialog), statt des Default-Wegs (`CloseApplications`/Restart
  Manager), der bei aktivem Minimize-to-Tray scheitert (`App._on_close` behandelt das dabei
  gesendete `WM_CLOSE` nur als Fenster-Verstecken).
- `tray.py` (Fassade; Seams: `notify`, `notify_action` für Windows-Interactive-Toasts) + `tray_mac.py` (natives macOS-NSStatusItem-Backend, #88).

Das Tray-Icon läuft, sobald `minimize_to_tray` **oder** `reminders_enabled` aktiv ist (`ui.py::_apply_tray_setting`); bei nur `reminders_enabled` dient es ausschließlich als Toast-Kanal.

Die Menüeinträge kommen aus **`ui.py::App._tray_actions()`** — eine Liste `(label, callback,
visible)`, die beide Backends rendern (pystray-Schleife bzw. `tray.build_menu_model`). Neue
Einträge gehören dorthin, nicht in ein Backend. Die Callbacks laufen im Backend-Thread und
marshallen selbst per `root.after(0, …)`. „Nach Updates suchen" (`_tray_check_update`) ist der
einzige Eintrag mit eigenem Hintergrund-Job: er übergeht den Frequenz-Throttle des
Hintergrund-Checks, meldet sein Ergebnis in **jedem** Fall als Toast (`updater.
manual_check_toast_text`) und blockt über `_update_check_running` den Doppelklick.

## Dialoge (`src/dialogs/`)

Modale Tk-Dialoge, von `App` geroutet (Klick-Modell: Linksklick = bearbeiten, Rechtsklick =
löschen — siehe Root-`CLAUDE.md`): `entry_dialog` (Tages-Dialog, rein zum Speichern),
`send_dialog`, `export_dialog` (Zeitraum-Modal → PDF lokal speichern),
`settings_dialog/` (Paket, Audit H4: `dialog.py` trägt Chrome + zentrales,
ablaufidentisches `save_settings`; je Tab eine Klasse in `tab_work/`
`tab_mail`/`tab_google`/`tab_app`/`tab_updates`.py, die ihre Tk-Variablen als
Attribute für `save_settings` exponiert; `tab_updates` startet seinen Live-Check
bewusst erst per `<<NotebookTabChanged>>`, nicht schon beim Dialog-Öffnen;
`oauth_task.py` = H5-OAuth-Toggle-Builder; Dark-Styling weiter via
`theme.apply_notebook_style`), `share_dialog`, `import_dialog`, `category_dialog`,
`conflicts_dialog`, `scopes_dialog`. `period_picker` ist kein Dialog, sondern der von
`send_dialog` + `export_dialog` geteilte Zeitraum+Kategorie+Vorschau-Baustein.

`scopes_dialog` zeigt read-only, welche OAuth-Scopes im `token.json` gewährt sind,
bewertet gegen die aktuell gebrauchten (`mail.scope_overview`): ✓ genutzt, ○ gewährt
aber Funktion aus, ✗ gebraucht aber fehlt. Bewusst ein Modal statt einer Liste im
Google-Tab (der ist mit 480 px schon der größte im Notebook) — und es liest
`token.json` beim Öffnen, ist also ohne Poll immer aktuell.

Neben dem „Anzeigen"-Button steht die Kurzfassung aus `mail.scope_summary`:
„n von m Berechtigungen" mit ✓ (alles Gebrauchte da) / ○ (Kern da, eine zuschaltbare
Funktion wartet auf ihren Scope) / ✗ (Kern-Scope fehlt — schlägt jede vollständige
Kür durch), plus „nicht angemeldet" bzw. „nicht lesbar" ohne verwertbares Token.
Gezählt wird nur, was die **eingeschalteten** Funktionen brauchen: ungenutzte und
unbekannte Scopes gehören nicht in den Nenner, sonst wüchse er mit jeder Altlast.
Aktuell gehalten wird die Zeile vom **vorhandenen** 500ms-Poll der
credentials.json-Zeile (`tab_google.refresh_scopes_status`), mit mtime/size-Cache
auf `token.json` — so zieht sie sowohl nach einem Re-Consent als auch nach dem
Umlegen der Sync-/Kalender-Schalter nach, ohne zweiten Timer und ohne die Datei
zweimal pro Sekunde zu lesen.

`App._open_dialog` (Linksklick-Handler) prüft zuerst `conflicts_store.unresolved_entry_keys()`:
liegt für den Tag ein ungelöster Sync-Konflikt (Ist-Zeit zwischen zwei Geräten
widersprüchlich), öffnet sich `ConflictsDialog` mit `filter_key=date_str` statt des
normalen `entry_dialog` — die Ist-Zeit steht buchstäblich zur Debatte, normales
Editieren würde einen der beiden Kandidaten überschreiben. `filter_key` filtert
`_unresolved` auf genau den einen Tag (nicht nur Vorselektion in der vollen Liste) und
blendet die Listbox aus (`_build`: `self.right` nimmt die volle Dialogbreite) — nach dem
Auflösen schließt sich der Dialog selbst, statt "wähle den nächsten" zu zeigen (es gibt
in dieser gefilterten Ansicht keinen nächsten). Zweiter, weiterhin bestehender Einstieg:
Einstellungen → Google-Tab → „Konflikte ansehen" (ungefiltert, volle Liste, auch
`kind == "setting"`-Konflikte, die kein Kalendertag abbilden kann). `ConflictsDialog`
nimmt optional `on_resolved` (von beiden
Einstiegen auf `App._refresh`/`on_change` gesetzt) — ohne den Callback bliebe die
Kalenderzelle hinter dem Dialog nach dem Auflösen auf dem alten Stand.

Alle Dialoge beziehen ihre Fenster-Chrome über `theme.create_dialog(...)`
(Audit M13); Content-Styles (`apply_combobox_style`/`apply_notebook_style`/
`attach_unfocus_on_click`) und `center_dialog_on_parent` ruft jeder Dialog
selbst nach dem Aufbau.

## Wo gehört neuer Code hin?

- Rendering/Zell-Logik → `grid_renderer.py`. Neuer Hintergrund-Task → `background_tasks.py`
  (über `run()`). Sync-Verhalten → `sync_orchestrator.py`. Reine Persistenz/Logik → der
  passende Store bzw. `sync.py`/`share.py` (Tk-frei, gut testbar).
- In `App` (ui.py) bleibt nur Koordination: Datum/View-State, Chrome-Aufbau, Dialog-Routing,
  Navigation, das `_marshal_to_ui`/`_refresh`-Glue. Wächst eine Verantwortlichkeit dort, ist
  das das Signal für die nächste Komponente — und für ein Update dieser Datei.
