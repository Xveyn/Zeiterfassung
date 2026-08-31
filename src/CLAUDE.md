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
main.py  ── Einstiegspunkt (nur Bootstrap): Tk-Root + Storage/Settings/App,
   │         --minimized, startet den Sync-Pull-Thread
   │            └─ sync_runtime.py — Pull/Push/Kompaktierung/Reconcile (die Flows selbst)
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
- Tk-frei, keine Google-Imports auf Modulebene; `run_calendar_reconcile` kommt
  seit R1 als normaler **Top-Level-Import aus `src.sync_runtime`**
  (`background_tasks.py:16`) — vorher lag es in `src.main` und musste wegen
  des damaligen Circular-Import-Risikos lazy importiert werden.

### SyncOrchestrator (`sync_orchestrator.py`)
Drive-Sync: manueller Sync, Tray-Sync, Pull-Callbacks, Status-Label, Quit-Push, Fehler-
Aufbereitung (`_classify_sync_error`/`_friendly_sync_message`/`_show_sync_error` — auch von
Tests genutzt). Reine Formatier-Helfer `_status_text`/`_tray_toast` sind ohne Tk testbar.
- Header-Widgets per `attach_widgets(...)`; Tray **lazy** über `get_tray=lambda: App._tray`
  (einzige Quelle bleibt `App._tray`); `run_push_blocking` kommt aus `src.sync_runtime`
  (seit R1 ein normaler Top-Level-Import — vorher lazy aus `src.main`).
- `App.on_sync_pull_success`/`on_sync_pull_error` bleiben als dünne Delegatoren (Public-API
  für `main.py`). `tray.stop()`/`root.destroy()` bleiben in `App._quit_with_sync_push`.

### UpdateBanner (`update_banner.py`)
Banner über dem Kalender (anzeigen/Download/ausblenden). `show_if_newer(release)` prüft nur
`dismissed_version` und zeigt ggf. an; Persistenz von `last_update_check_at` und Toast-vs.-
Banner-Routing liegen in `ui.py::_on_update_check_result` bzw.
`_route_update_notification(...)`. Pack-Anker **lazy** über
`get_anchor=lambda: App._renderer.grid_container` (Grid existiert erst nach dem Build).
`on_resize` (= `App._renderer.repin_geometry`) wird in `_show`/`_dismiss` aufgerufen, damit
das fixe Fenster auf die geänderte Banner-Höhe nachzieht (sonst Footer abgeschnitten, margenheld/Zeiterfassung#92).

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
`send_task.perform_send` ist dabei ein **Dispatcher** über beliebig viele
Kanäle (Mail + jeder ausgewählte Webhook): jeder Kanal läuft unabhängig,
ein Fehler in einem bricht die übrigen nicht ab, und der Dispatcher liefert
pro Kanal genau ein Result-Dict statt selbst zu werfen (Vertrag wie die
einzelnen Kanäle, `webhook.deliver` eingeschlossen).

**Datenschicht-Locking (Audit H1/H2/M1):** Fünf der sechs Stores
(`storage`/`settings`/`conflicts_store`/`reservations`/`vacations`) teilen
sich einen in `main()` erzeugten `RLock` (Konstruktor-Param `lock=`; ohne
Injektion legt jeder Store einen eigenen an — Tests bleiben unverändert); nur
`webhook_store` bringt bewusst seinen eigenen mit (s. „Daten- &
Persistenz-Schicht" unten). Die Sync-Flows
(`_run_pull_in_background`/`run_push_blocking`/`_run_compaction_blocking`/
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

Dass der `data_lock` nicht über die Netzwerk-Calls reicht, lässt im Push ein
TOCTOU-Fenster zwischen `drive.download` und `drive.upload` offen: ein zweites
Gerät kann dazwischen hochladen, unser Upload überschreibt dessen Stand. Das
ist ein **bewusst akzeptierter Trade-off** (Audit M2, Xveyn/Zeiterfassung#46),
kein offener Punkt — File-level Optimistic Locking, ein `version`-basiertes
Retry-on-conflict und Drive Content Restrictions sind geprüft und verworfen.
Begründung und die Grenze der LWW-Heilung stehen im Docstring von
`drive.py::upload`; wer das Fenster erneut angehen will, fängt dort an.

**Urlaub reist als Snapshot, nicht als Store.** `send_task.perform_send` und
`export_task.perform_export_pdf` bekommen `vacation_days` als fertiges
`{ISO: minutes}`-Dict, das der Dialog-Thread über
`VacationStore.day_minutes()` gezogen hat. Die Worker greifen nie selbst auf
den Store zu — dieselbe Regel wie beim Entries-Snapshot.

## Daten- & Persistenz-Schicht

- `json_store.py` — **die gemeinsame Mechanik, und der einzige Ort für zwei Regeln** (R2):
  `atomic_write_json(path, obj)` (Temp → `flush`+`fsync` → `os.replace`, Temp-Cleanup und
  `OSError` weiterreichen, wenn das Rename scheitert = **N1**) und
  `load_json_or_quarantine(path)` → Objekt oder `None`, wobei eine unparsebare Datei nach
  `<name>.corrupt-<stamp>` verschoben und geloggt wird (**N4**). Genutzt von `storage`,
  `reservations`, `conflicts_store` (beide Helfer) und `settings` (nur der Schreib-Helfer).
  Wer einen neuen JSON-Store baut, nimmt diese beiden Funktionen — nicht die Mechanik
  erneut abschreiben.
  **Bewusst eigen geblieben:** `settings._quarantine_corrupt` und
  `webhook_store._quarantine` (beide greifen auch bei nicht-Dict-Toplevel, tragen einen
  Grund in der Meldung und **schlucken** einen gescheiterten Rename, damit der Start
  weiterläuft); `sync_journal._atomic_write_json` (schreibt über `tempfile.mkstemp` und ist
  die Crash-Recovery-Schicht selbst); die Secret-Schreiber `webhook_store`/`oauth_utils`/
  `single_instance` (brauchen zusätzlich ACL-Härtung + Rename-Retry, s. `secure_file.py`).
- `storage.py` — Ist-Zeiten (JSON, Schlüssel = ISO-Datum). `reservations.py` — Reservierungen
  (zukünftige Soll-Zeiten, eigenes Konzept). `settings.py` — Einstellungen mit Defaults.
- `conflicts_store.py` — lokale Sync-Konfliktliste. `category_defaults.py` — Default-Kategorien.
- `webhook_store.py` — gerätelokaler Store der Webhook-Konfiguration
  (`webhooks.json`). Bekommt bewusst **nicht** den geteilten `data_lock` aus
  dem „Datenschicht-Locking"-Absatz oben, sondern legt sich einen eigenen an
  (`main.py` instanziiert ihn ohne `lock=`): Webhooks nehmen an keinem
  Sync-Flow teil (kein Snapshot→Merge→Apply, kein Journal, kein Feld im
  Sync-Doc), es gibt also keine übergreifende Invariante mitzuziehen — und den
  Lock trotzdem zu teilen hätte einen realen Preis, weil `save`/`delete` ihn
  über den `icacls`-Subprozess (bis 15 s + Retries) halten und damit jeden
  anderen Store blockierten. Details/Tests: `tests/test_store_locking.py`.
  Enthält Konfiguration **und** Secrets, wird deshalb wie `token.json`
  gehärtet geschrieben (`secure_file.harden_windows_acl`, s.u.) und steht
  **nicht** im Sync-Doc.

  `VacationStore` (`vacations.json`) hängt am geteilten `data_lock` wie
  `Storage`, `Settings`, `ConflictsStore` und `ReservationStore` — anders als
  `WebhookStore`, der bewusst seinen eigenen mitbringt. Er ist gerätelokal:
  kein `device_id`-Feld, kein Zweig im Sync-Doc, kein Eintrag im Share-Doc.

  **Tombstones nur mit Kalender-Event.** `VacationStore.delete` entfernt den
  Record direkt, wenn er keine `gcal_event_id` trägt — nur mit Event gibt es
  draußen etwas aufzuräumen, und nur dann kann `reconcile_vacations` den
  Tombstone einlösen. Ein bedingungsloser Tombstone (wie bei den
  Reservierungen, die per Definition am Kalender hängen) wäre auf jedem Rechner
  ohne Google unsterblich. Rest-Risiko: wurde eine Periode gepusht und der
  Kalender-Sync danach abgeschaltet, bleibt ihr Tombstone liegen, bis der Sync
  wieder läuft — bewusst akzeptiert, statt dafür einen vierten Startup-Sweep zu
  bauen.
- `devices.py` — **Geräte-Registry** für die Anzeige: `{device_id: {name, updated_at}}`,
  im Sync-Doc unter `devices`. Übersetzt die `device_id` in einen lesbaren Namen
  (Konfliktdialog, `_fmt_*_candidate`). Tk- und I/O-frei; der eigene Name steht
  gerätelokal in `settings.device_name`, der Spiegel der anderen in
  `settings.known_devices` — **nicht** in `SYNCED_SETTING_KEYS` (ein
  synchronisierter Key wäre ein einziger globaler Wert, die Geräte würden ihn
  sich gegenseitig überschreiben; deshalb die Registry mit `device_id` als
  Schlüssel). `build_local_doc` setzt darin den eigenen Eintrag
  (`with_own_entry`, neuer Zeitstempel nur bei echter Namensänderung),
  `merge` vereinigt beide Seiten per LWW, `apply_merged_doc` schreibt den
  Spiegel zurück — aber **nur, wenn das Doc den Key führt**: ein älterer
  Client liefert ihn nicht mit, und der Spiegel darf davon nicht leergeräumt
  werden. Das Feld ist bewusst **additiv ohne Schema-Bump** (SCHEMA_VERSION
  bleibt 4, s. Docstring in `sync.py`); alles hier behandelt seine Eingabe als
  Fremddaten, und jeder Ausfall endet in der gekürzten ID statt in einem Fehler.

  **Zwei Eigenheiten, die man kennen muss:** Ein geleerter Name wird zum
  **Grabstein** (`name: ""` mit frischem Stempel) statt zu einer Abwesenheit —
  die Union kennt keine Abwesenheit, ein entfernter Eintrag verlöre gegen die
  ältere Kopie eines anderen Geräts und der gelöschte Name käme global zurück.
  Und die Registry hat **keinen GC-Pfad**: weder `compact_local` noch der
  Tombstone-Lebenszyklus fassen `devices` an (es gibt nichts abzugleichen), sie
  ist additiv bis `MAX_DEVICES` und wirft dann die ältesten Einträge weg. Wer
  hier einen GC sucht: es gibt bewusst keinen.
- `sync.py` — pure Sync-Logik (LWW-Merge, Konflikterkennung); importiert
  `SYNCED_SETTING_KEYS` aus `settings.py` **und** `_REQUIRED_ENTRY_KEYS` aus `storage.py`
  (beide Single Source of Truth, nicht hier neu definieren). `validate_remote_doc`
  prüft ein migriertes Remote-Doc auf die Merge-Invarianten (Pflichtfelder,
  `modified_at`-Typ), bevor ein `KeyError`/`ValueError` mitten im Merge landet
  (Audit M5) — die Sync-Flows in `sync_runtime.py` behandeln ein invalides Doc wie
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
- `sync_runtime.py` — die **Flows** über `sync.py` (die Engine): `run_pull_in_background`
  (Thread + `ui_callback`), `run_push_blocking`, `run_compaction_blocking` und
  `run_calendar_reconcile`, dazu die Helfer `_parse_remote_or_quarantine`/`_lock_ctx`.
  Bis R1 (#49/#51) lagen sie in `main.py` — vier Module importierten deshalb lazy
  zurück nach `src.main` („Circular-Import-Schutz"). Jetzt normale Top-Level-Importe;
  `main.py` ist wieder reiner Bootstrap. Die Google-Wrapper zieht das Modul **lazy in
  den Funktionen** (CI ohne `requirements.txt`), die Lock-Invarianten H1/H2 stehen in
  den jeweiligen Docstrings. Aufrufer: `main.py` (Startup-Pull), `sync_orchestrator.py`
  (Push), `background_tasks.py` (Reconcile), `tab_google.py` (Kompaktierung).
- `sync_history.py` — persistenter „hat je gesynct/abgeglichen"-Marker
  (`sync_history.json`, write-once, Tk-frei, fail-safe). Vetoed den
  N6-Startup-Sweep, damit ein settings.json-Reset (M4) einen gesyncten Rechner
  nicht wie jungfräulich aussehen lässt (s. Tombstone-Lebenszyklus oben).
- `sync_journal.py` — Crash-Recovery für `sync.apply_merged_doc` (Audit M6): dessen
  Store-Writes sind einzeln atomar, die Sequenz nicht. `apply_merged_doc_journaled`
  schreibt den `merged_doc` erst durable (`fsync`) in ein Write-Ahead-Journal
  (`sync-apply.journal` im Base-Dir), dann die Stores, dann löscht es das Journal.
  `sync_runtime.py` ruft die drei Sync-Apply-Stellen (Pull/Push/Kompaktierung) darüber; beim
  Start holt `recover_pending_apply` ein übriggebliebenes Journal idempotent nach
  (alle Ops sind Full-Replace). **Kein** Sync-Doc-Feld — rein lokaler
  Recovery-Zustand.
  `share.py` — Export/Import als Share-JSON. `weekly_limit.py` — pure Wochenstunden-Limit-Check
  (Werkstudenten-Privileg, margenheld/Zeiterfassung#98). Kein eigener Persistenz-Zustand, operiert auf
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
  `count_weekend_entries` für die Hinweiszeile. Letzteres zählt auf dem
  **ungefilterten** Snapshot (sonst wäre die Zahl per Konstruktion 0), dabei
  aber **ohne** den Kategorie-Filter — anders als die Stundenvorschau eine
  Zeile darüber, die mit `handle.get_categories()` rechnet
  (`period_picker._update_total`). Wer alle Kategorien der Wochenend-Einträge
  abwählt, bekommt die Einträge trotzdem gemeldet. Bekannte kosmetische
  Ungenauigkeit, kein Datenfehler: der Bericht filtert unabhängig davon
  korrekt. Gefiltert wird am **Snapshot**
  (`storage.get_all()` in send_dialog/export_dialog/period_picker), NICHT in
  `report.py` — das bleibt settings-frei, und Mail-HTML, PDF und Vorschau sehen
  dadurch automatisch dieselben Daten. Im Kalender überstimmt die Flag
  `show_weekend` (`grid_renderer._visible_day_count`); in den Standardzeiten
  entfallen die Sa/So-Zeilen, ihre `StringVar`s aber nicht — der Speicherpfad
  schreibt weiter alle sieben Tage, damit die Werte erhalten bleiben. Bewusst
  unberührt: Werkstudenten-Limit (zählt real geleistete Stunden), Teilen und
  Kalender-Abgleich.
  `reminders.py` — pure Fälligkeits-Logik für Reservierungs-Erinnerungen (Tk-frei, `now` als Parameter): pro heutigem reservierten Slot mit Kategorie ohne erfasste Ist-Zeit `upcoming` (N Min vor Ende) oder `missed` (nach Ende). Der `ReminderScheduler` (`reminder_scheduler.py`) pollt minütlich über `root.after` und schickt fällige Toasts über `App._tray`. Analog dazu `send_reminder.py`/`send_reminder_scheduler.py`, dort aber mit **zwei Kanälen** in einem Poll. **Monatlich**: ein einzelner Fällig-Zeitpunkt pro Monat (Tag + Uhrzeit, Tag auf die Monatslänge geclamped, optional von arbeitsfreien Tagen weg verschoben) statt Slot-Fenster; der Fired-Zustand wird bewusst **persistiert** (`settings.send_reminder_last_fired_month`, `"YYYY-MM"`) statt nur im Speicher gehalten wie beim Reservierungs-Reminder — verhindert wiederholte Toasts bei App-Neustarts im selben Monat. **Tagesbezogen**: der `SendReminderScheduler` bekommt zusätzlich den `reservation_store` durchgereicht und feuert, wenn eine heutige Reservierung mit gesetztem `send_reminder_minutes` ausläuft; dieser Kanal verlangt neben dem Haupt-Schalter `send_reminder_reservations_enabled` **und** `gcal_enabled` (ohne Kalender-Abgleich zeigt die App gar keine Reservierungen, s. `App._reservations_active`) und dedupliziert — anders als der Monats-Kanal — nur im Speicher, tageweise: ein persistierter Marker müsste in `reservations.json` landen und würde dort `modified_at` anfassen, was einen gcal-Push auslöst.

## Google-Integration (alle Wrapper mit Lazy-Imports für CI ohne requirements.txt)

`mail.py` (Gmail/OAuth, `token.json`/`credentials.json`), `drive.py` (Drive appDataFolder-Sync),
`gcal.py` (Calendar), `reservations_sync.py` (Abgleich Reservierungen ↔ Kalender),
`vacations_sync.py` (Einwegs-Push der Urlaubsperioden). Alle teilen
denselben OAuth-Token; Scope-Upgrade erzwingt frischen Consent.

Geschrieben wird der Token ausschließlich über `oauth_utils.write_token`: Temp-Datei →
Härtung → `os.replace` (mit `PermissionError`-Retry, margenheld/Zeiterfassung#135). Zur Härtung siehe
`secure_file` unten.

`drive.find_sync_file` liefert bei mehreren Treffern deterministisch die
**älteste** Datei (`createdTime`, Tie-Break `id`) — der appDataFolder kennt kein
atomares create-if-not-exists, zwei Geräte können beim Erst-Setup also beide
anlegen (Audit M3). Die Regel ist die einzige Klammer, die alle Geräte auf
dieselbe Datei zwingt: ohne sie liefen die Stände auseinander, und da die
Drive-API ohne `orderBy` keine Sortierung garantiert, könnte sogar dasselbe
Gerät zwischen zwei Syncs die andere Datei erwischen. Wer die Auswahl anfasst,
muss sie deterministisch **und** über alle Geräte gleich halten.

**Zwei Marker-Werte unter demselben Schlüssel.** `gcal.APP_MARKER_KEY`
(`zeiterfassung`) trägt entweder `reservation` oder `vacation`.
`list_app_events` und `list_app_vacations` filtern **serverseitig** auf ihren
Wert und bekommen die Events des jeweils anderen gar nicht erst zurück — der
Reservierungs-Reconcile kann Urlaubs-Events also weder adoptieren noch als
verwaiste App-Events löschen. Mit einem gemeinsamen Wert hinge das daran, dass
`parse_event` für Ganztags-Events `None` liefert; ein Detail, das jederzeit
kippen könnte. Wer einen dritten Event-Typ ergänzt, vergibt einen dritten
Wert.

## Berichte & Plattform/Infra

- `report.py` — HTML-Mail + PDF (xhtml2pdf **lazy**), gruppiert pro ISO-KW.
- `theme/` — Dark-Theme als Paket (R3, vorher eine 1075-Zeilen-Datei): `palette`
  (Konstanten, hängt an nichts) → `fonts` (benannte Tk-Fonts, `init_fonts`/`scaled_size`)
  → `widgets` (Widget-Fabriken, ttk-Styles); daneben `geometry`
  (`center_dialog_on_parent` + die Tk-freien Prädikate `_stray_click_suppressed`/
  `_should_show_delete_button`), `chrome` (Win32-Fensterchrome, `create_dialog`) und
  `messagebox` (themed Drop-ins, nutzt chrome/widgets/geometry). Die Schichtung ist
  zyklenfrei und in genau dieser Reihenfolge importierbar.
  **Importiert wird weiterhin `from src.theme import …`**, nicht aus den Teilmodulen —
  `__init__.py` re-exportiert die Oberfläche. Wer etwas ergänzt, legt es ins passende
  Teilmodul und trägt es dort nach.
- `tooltip.py` — Hover-Tooltips (`attach_tooltip`). Ein Aufruf bindet **einen**
  Tooltip an ein Widget oder eine Widget-Gruppe; `text` darf ein
  `Callable[[], str]` sein, das erst beim Anzeigen ausgewertet wird
  (`_resolve_text`) — so hängen die Header-Pfeile ihren Text an die aktuelle
  Ansicht. Die Sichtbarkeits-Entscheidung liegt Tk-frei in
  `_should_hide_tip` (minimiert/withdrawn, fremder Grab, Zeiger draußen).
  Konvention, wo Tooltips hingehören: Root-`CLAUDE.md`, Abschnitt „Tooltips".
- `time_utils.py` — Stunden, KW-Labels, `format_iso_date`/`format_iso_datetime`.
- `holidays_de.py`, `paths.py` (`get_base_path` Frozen-vs-Repo), `updater.py`
  (GitHub-Releases, stdlib-only, Frequenz über `update_check_frequency`, Pre-Release-Opt-in über `prerelease_updates_enabled`), `changelog.py`
  (lädt/parst den Changelog-Abschnitt einer Release-Version vom GitHub-Tag), `platform_open.py`, `logging_setup.py`,
  `version.py` (einzige Versions-Quelle).
  `get_resource_path()` ist das Gegenstück: gebündelte Programmdaten
  (`sys._MEIPASS`), nicht Nutzerdaten. Icon-/Asset-Zugriffe gehen über diese
  Funktion — über `get_base_path()` fanden sie auf Linux und macOS nichts.
- `src/desktop_entry.py` — Freedesktop-`.desktop`-Dateien: schreibt den
  Menüeintrag (`$XDG_DATA_HOME/applications/`, Fallback `~/.local/share/…`)
  und besitzt die `Exec=`-Quoting-Regel (`exec_line`, Audit N17), die
  `autostart.py` mitbenutzt — `autostart.py` schreibt sein `[Desktop Entry]`
  aber weiterhin selbst (andere Keys, kein gemeinsamer Renderer). `ensure_icon`
  legt eine persistente Icon-Kopie im Datenverzeichnis ab, weil `Icon=` den
  AppImage-Mount überleben muss.
- `autostart.py` — plattformabhängig (Windows-Registry HKCU Run / macOS-LaunchAgent / Linux-.desktop).
  Windows-Backend nutzt den **Registry-Wert `Zeiterfassung`** (Wertname = `installer.iss` → strukturell
  ein Eintrag); `import winreg` lazy (CI-Ubuntu). `is_autostart_enabled()` liest den echten Zustand
  (Registry-Wert **oder** Alt-Startup-Shortcut als Fallback, falls Migration scheitert).
  `migrate_legacy_autostart()` überführt Alt-Shortcuts in den Registry-Key, ist aber frozen-gated
  (Repo-Modus: No-op, würde andernfalls python.exe+Repo ins Register schreiben und bestehende
  Shortcuts beschädigen).
- `secure_file.py` — Zugriffsschutz für die drei lokal abgelegten Secrets: `token.json`
  (`oauth_utils.write_token`), `instance-secret` (`single_instance._write_secret_atomic`)
  und `webhooks.json` (`webhook_store._save_to_disk`, dritter Schreibpfad — enthält
  Auth-Token/HMAC-Secrets der konfigurierten Webhooks). Alle drei Schreibpfade laufen
  Temp-Datei → `chmod 0600` → `harden_windows_acl` → `os.replace`.
  Unter Windows ist chmod ein No-op, deshalb dort zusätzlich `icacls /inheritance:r
  /grant:r <user>:(F)` (Audit M8): geerbte ACEs (u.a. SYSTEM, lokale Administratoren) raus,
  genau ein Berechtigter bleibt. **Vollzugriff** statt R/W, weil das spätere `os.replace`
  DELETE auf der Zieldatei braucht; **auf der Temp-Datei**, damit die Datei nie kurz mit
  geerbten Rechten am Zielpfad liegt. Best-effort und nie fatal (fehlendes `icacls`, kein
  benennbarer Principal → loggen und weiter): ungehärtet ist der Status quo, eine
  gescheiterte Persistenz wäre eine Regression. Eigenes Modul, damit `single_instance`
  nichts aus dem OAuth-Umfeld importieren muss (und keiner den privaten Namen des anderen
  nutzt, Audit N17). Wer einen vierten Secret-Schreibpfad baut, ruft diesen Helfer mit auf.
  **Aufrufhäufigkeit:** der Helfer hängt an `write_token`, läuft also bei *jedem*
  Token-Refresh in Mail-, Drive- und Kalender-Pfad — ein `icacls`-Subprozess pro
  Refresh, nicht einmalig beim Anlegen. Unkritisch, weil alle diese Pfade in den
  Worker-Threads des `BackgroundTaskRunner` laufen (die UI blockiert nicht) und der
  Aufruf ein `timeout=15` trägt. Wissen fürs Debugging: liegen die Daten auf einem
  hängenden Netzlaufwerk, verzögert sich der Token-Schreibvorgang um bis zu diese
  15s pro Refresh. Wer den Helfer in einen UI-Thread-Pfad hängt, muss das prüfen.
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
- `tray/` — Paket seit R7 (#51), Importpfad bleibt `src.tray`: `__init__.py` ist die
  Fassade (`TrayIcon`, `is_supported`, die beiden Opt-in-Gates, `_select_backend`),
  `model.py` das backend-agnostische Menü-Modell (`build_menu_model` — die testbare
  Naht), und je ein Backend in `windows.py` (pystray), `mac.py` (natives
  NSStatusItem, margenheld/Zeiterfassung#88) und `linux.py` (StatusNotifierItem über
  D-Bus, margenheld/Zeiterfassung#42). Vorher lag der Windows-Backend in der Fassade,
  während die anderen beiden eigene Module hatten.
  **Zwei Regeln, die den Schnitt tragen:** `__init__` lädt mac/linux ausschließlich
  **lazy** in `_select_backend` (sonst zöge `src.ui → src.tray` PyObjC bzw. dbus_fast
  auf die falsche Plattform), und die Backends importieren `build_menu_model` aus
  `tray/model.py`, **nicht** aus dem Paket-`__init__` — so zeigt jede Kante nach unten.
  Beide Nicht-Windows-Backends sind dormant hinter einer Opt-in-Env-Var, bis ihr
  manuelles Plattform-Gate grün ist.

Das Tray-Icon läuft, sobald `minimize_to_tray` **oder** `reminders_enabled` aktiv ist (`ui.py::_apply_tray_setting`); bei nur `reminders_enabled` dient es ausschließlich als Toast-Kanal.

Die Menüeinträge kommen aus **`ui.py::App._tray_actions()`** — eine Liste `(label, callback,
visible)`, die beide Backends rendern (pystray-Schleife bzw. `tray.build_menu_model`). Neue
Einträge gehören dorthin, nicht in ein Backend. Die Callbacks laufen im Backend-Thread und
marshallen selbst per `root.after(0, …)`. „Nach Updates suchen" (`_tray_check_update`) ist der
einzige Eintrag mit eigenem Hintergrund-Job: er übergeht den Frequenz-Throttle des
Hintergrund-Checks, meldet sein Ergebnis in **jedem** Fall als Toast (`updater.
manual_check_toast_text`) und blockt über `_update_check_running` den Doppelklick.

Die `visible`-Callable wird auf Windows und Linux LIVE ausgewertet (pystray baut
das Popup neu, dbusmenu fragt vor jedem Öffnen `AboutToShow`), auf macOS ist sie
ein Snapshot vom Tray-Start.

## Dialoge (`src/dialogs/`)

Modale Tk-Dialoge, von `App` geroutet (Klick-Modell: Linksklick = bearbeiten, Rechtsklick =
löschen — siehe Root-`CLAUDE.md`): `entry_dialog` (Tages-Dialog, rein zum Speichern;
die Slot-Zeilen beider Blöcke baut seit R5 `slot_rows.SlotRowList` — Ist-Zeit mit,
Reservierung ohne Pause-Spalte, `on_value_changed` hängt den Erinnerungs-Block an
Zeit-/Kategorieänderungen. Dort liegen auch die Tk-freien Anzeige-Helfer
`category_*`/`slot_category_display`, die `entry_dialog` re-exportiert),
`send_dialog`, `export_dialog` (Zeitraum-Modal → PDF lokal speichern),
`webhook_dialog` (Anlegen/Bearbeiten eines Webhooks inkl. Testversand; Validierung
über `webhook_store.validate_record`, Versand über `webhook.deliver`, beide Tk-frei),
`settings_dialog/` (Paket, Audit H4: `dialog.py` trägt Chrome + zentrales,
ablaufidentisches `save_settings`; je Tab eine Klasse in `tab_work/`
`tab_mail`/`tab_google`/`tab_app`/`tab_updates`/`tab_webhooks`.py, die ihre Tk-Variablen
als Attribute für `save_settings` exponiert — **außer** `tab_webhooks`: als einziger Tab
exponiert er dafür **keine** Variablen, Webhooks liegen im eigenen `webhook_store` und
werden vom `webhook_dialog` direkt gespeichert; `tab_updates` startet seinen Live-Check
bewusst erst per `<<NotebookTabChanged>>`, nicht schon beim Dialog-Öffnen;
`oauth_task.py` = H5-OAuth-Toggle-Builder; Dark-Styling weiter via
`theme.apply_notebook_style`).
`GoogleTab` ist seit R4-Stufe 1 (#51) in drei Sektionsmethoden gebaut —
`_build_account_section` / `_build_sync_section` / `_build_calendar_section`, jede
Interaktion eine eigene Methode statt einer Closure im Konstruktor. Geteilter
Zustand liegt auf `self`; die Row-Nummern reicht `_build_sync_section` als
Rückgabewert an die Kalender-Sektion weiter, weil Konflikt- und
Kompaktier-Zeile nur unter Bedingungen erscheinen. Neue Interaktionen dort als
Methode ergänzen, nicht als verschachtelte Funktion.
Die blockierenden Kerne liegen seit Stufe 2 Tk-frei in
`settings_dialog/google_tab_task.py` (Muster wie `send_task`/`share_task`, M10):
`fetch_sender_email` / `load_calendars` / `reconnect_drive` liefern ein
Result-Dict und **werfen nie**; `open_drive_service` / `open_calendar_service`
sind die `service_fn`-Einstiege für `oauth_task.build_oauth_enable_task` und
**werfen** bewusst (der Builder fängt selbst und dreht den Toggle zurück). Im
Tab bleibt `runner.run(fn, on_done)` plus die Widget-Kosmetik im `on_done`.
Getestet in `tests/test_google_tab_task.py` — die erste echte Abdeckung des
Tabs. Neue Netz-/OAuth-Arbeit des Tabs gehört dorthin, nicht in eine Closure.
Weitere Dialoge: `share_dialog`, `import_dialog`, `category_dialog`,
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
credentials.json-Zeile (`GoogleTab._refresh_scopes_status`), mit mtime/size-Cache
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
  (über `run()`). Sync-**Bedienung** (Buttons, Status, Fehlermeldungen) → `sync_orchestrator.py`,
  ein neuer Sync-/Reconcile-**Flow** (Drive/Kalender sprechen, mergen, hochladen) →
  `sync_runtime.py`. Reine Persistenz/Logik → der passende Store bzw. `sync.py`/`share.py`
  (Tk-frei, gut testbar).
- **Nicht** nach `main.py`: der Einstiegspunkt ist Bootstrap (Stores bauen, Wiring,
  `_hold_app_mutex`/`_ensure_device_id`/`_sweep_orphan_tombstones`/`_refresh_linux_integration`).
  Wer dort Fachlogik ablegt, erzeugt wieder den Zyklus, den R1 aufgelöst hat — Symptom ist
  ein `from src.main import …` mitten in einer Funktion.
- In `App` (ui.py) bleibt nur Koordination: Datum/View-State, Chrome-Aufbau, Dialog-Routing,
  Navigation, das `_marshal_to_ui`/`_refresh`-Glue. Wächst eine Verantwortlichkeit dort, ist
  das das Signal für die nächste Komponente — und für ein Update dieser Datei.
