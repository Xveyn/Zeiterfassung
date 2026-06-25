# Design: ui.py entflechten — Duplikat-Helfer + BackgroundTaskRunner

**Issue:** #49 (Refactor: ui.py God-Object entflechten + interne Thread-/Hover-Duplikation)
**Scope dieses PRs:** Erster Schritt — alle vier billigen Duplikat-Helfer **plus** eine
Verantwortlichkeit (Background-Tasks) in eine eigene Klasse auslagern. Erfüllt alle vier
Akzeptanzkriterien von #49; weitere Extraktionen (GridRenderer, SyncOrchestrator) bleiben
Folge-PRs.

**Leitprinzip:** Verhalten bleibt unverändert (AC 4). Kein Big-Bang — nur Dedup + eine
saubere Extraktion mit klarer Schnittstelle.

## Ausgangslage

`src/ui.py` ist ~1541 Zeilen; die `App`-Klasse vermengt Rendering, Sync, Background-Tasks,
Dialog-Routing und Tray. Konkret dedupliziert werden in diesem PR:

- **Worker-Thread-Muster** 7× nahezu identisch: `_proactive_token_refresh`,
  `_proactive_sender_email_fetch`, `_proactive_update_check`,
  `_proactive_calendar_reconcile`, `_trigger_calendar_reconcile`, `_on_sync_clicked`,
  `_tray_sync`. Alle bauen `threading.Thread(target=worker, daemon=True).start()` und
  marshallen ihr Ergebnis per `self._marshal_to_ui(lambda: on_done(result))`.
- **Hover** `_cell_hover(frame, day_lbl, time_lbl, bg)` / `_empty_hover(frame, day_lbl, bg)`
  — identischer Overlay-Färb-Kern (Frame + Labels + `_reservation_marker` + `_delete_button`),
  Unterschied nur das zusätzliche `time_lbl`.
- **Probe-Label** in `_refresh_month` und `_refresh_week` doppelt: `probe_width`,
  `entry_time_font`, `holiday_name_font`, Mess-Probe.
- **Navigation** `_prev` / `_next` strukturgleich (nur ±1 Monat bzw. ±7 Tage).

## Teil A — Vier Duplikat-Helfer (in `App`)

### A1. `_navigate(direction)` ersetzt `_prev`/`_next`

`direction ∈ {-1, +1}`.

```python
def _navigate(self, direction):
    if self.view_mode == "month":
        m = self.month + direction
        if m < 1:    self.month, self.year = 12, self.year - 1
        elif m > 12: self.month, self.year = 1, self.year + 1
        else:        self.month = m
    else:
        monday = get_week_dates(self.iso_year, self.current_week)[0] \
                 + datetime.timedelta(days=7 * direction)
        self.iso_year, self.current_week = monday.isocalendar()[:2]
    self._refresh()
```

Die zwei Key-Bindings (`<Left>`/`<Right>`) rufen `_navigate(-1)`/`_navigate(+1)`.
`_prev`/`_next` entfallen (keine externen Caller — nur die zwei Lambdas).

### A2. `_hover(frame, bg, *labels)` vereint `_cell_hover`/`_empty_hover`

```python
@staticmethod
def _hover(frame, bg, *labels):
    frame.config(bg=bg)
    for lbl in labels:
        lbl.config(bg=bg)
    # Eck-Overlays mitfärben, sonst bleibt beim Hover ein andersfarbiges
    # Rechteck stehen. Nur bg — die fg des Lösch-Buttons steuert dessen
    # eigener Enter/Leave-Handler.
    for attr in ("_reservation_marker", "_delete_button"):
        w = getattr(frame, attr, None)
        if w is not None:
            w.config(bg=bg)
```

Aufrufer:
- Entry-Zelle (`_build_entry_cell`): `_hover(c, bg, day_lbl, time_lbl)`
- Holiday-Zelle (`_build_holiday_cell`): `_hover(c, bg, day_lbl, name_lbl)`
- Empty-Zelle (`_build_empty_cell`): `_hover(c, bg, day_lbl)`

### A3. `_cell_layout_metrics(frame)` zieht das doppelte Probe-Pattern zusammen

Neue Modul-Konstanten: `PROBE_WIDTH_WIDE = 12`, `PROBE_WIDTH_NARROW = 8`, `PROBE_HEIGHT = 3`.

```python
def _cell_layout_metrics(self, frame):
    """Misst die natürliche Pixelgröße einer Standard-Tageszelle (Probe-Label)
    und liefert die layout-abhängigen Größen. Bei ausgeblendetem Wochenende
    (5 statt 7 Spalten) breitere Zellen + größere Zeit-/Feiertagsschrift."""
    wide_cells = not self.settings.get("show_weekend")
    probe_width = PROBE_WIDTH_WIDE if wide_cells else PROBE_WIDTH_NARROW
    entry_time_font = FONT if wide_cells else FONT_SMALL
    holiday_name_font = FONT if wide_cells else FONT_SMALL
    probe = tk.Label(frame, text="", font=FONT, width=probe_width, height=PROBE_HEIGHT)
    probe.update_idletasks()
    cell_size = (probe.winfo_reqwidth(), probe.winfo_reqheight())
    probe.destroy()
    return cell_size, entry_time_font, holiday_name_font, wide_cells
```

`_refresh_month`/`_refresh_week` rufen den Helfer statt der inline-Blöcke. Die
ausführlichen Erklär-Kommentare (Feiertagszellen-Fixierung, Reihenhöhe) bleiben an den
Aufrufstellen bzw. wandern in den Helfer. Die `holiday_max_len`-Logik bleibt lokal
(Month: `12 if wide_cells else 9`; Week: unverändert), da sie sich je Ansicht unterscheidet.

## Teil B — `BackgroundTaskRunner` (neues Modul `src/background_tasks.py`)

Eigene Verantwortlichkeit: **Background-Ausführung + die proaktiven Startup-Tasks**.
Pure Mechanik, keine Tk-Imports, keine Google-Imports auf Modulebene. `run_calendar_reconcile`
aus `src.main` bleibt Lazy-Import **innerhalb** der Methode (verhindert Circular-Import, da
`src.main` `App` aus `ui` zieht — wie schon im Bestandscode).

### Schnittstelle

```python
class BackgroundTaskRunner:
    def __init__(self, marshal, settings, base_path, reservation_store,
                 reservations_active):
        self._marshal = marshal                          # App._marshal_to_ui
        self._settings = settings
        self._base_path = base_path
        self._reservation_store = reservation_store
        self._reservations_active = reservations_active  # App._reservations_active (callable)

    def run(self, fn, on_done=None):
        """fn() im Daemon-Thread ausführen; dessen Rückgabe via marshal an
        on_done auf dem UI-Thread liefern. Der eine Thread-Helfer (AC 1)."""
        def worker():
            result = fn()
            if on_done is not None:
                self._marshal(lambda: on_done(result))
        threading.Thread(target=worker, daemon=True).start()
```

`run()` ist **der** Thread-Helfer — auch die in `App` verbleibenden Sync-Methoden
(`_on_sync_clicked`, `_tray_sync`) nutzen ihn statt eigener `threading.Thread`-Kopien.
Damit existiert das Muster nur noch an einer Stelle.

### Die fünf proaktiven Tasks

Die Klasse entscheidet (Guards) und macht das Background-I/O; UI-Arbeit (Dialoge, Banner,
Refresh) bleibt in `App` und kommt als Callback rein.

| Methode | Guard | Background-I/O | UI-Callback (App) |
|---|---|---|---|
| `refresh_token(on_auth_error, on_error)` | — | `refresh_token_if_needed` | Dialog bei auth/unerwartet |
| `fetch_sender_email()` | `token.json` existiert | `fetch_user_email` | setzt `settings` selbst (via marshal) |
| `check_update(on_result)` | `should_check_today` | `check_latest_release` + `is_newer` | `_handle_update_check_result` |
| `reconcile_on_start(on_ok)` | `reservations_active()` | `run_calendar_reconcile` | `_refresh` (nur bei ok) |
| `trigger_reconcile(on_done)` | `reservations_active()` | `run_calendar_reconcile` | `_on_reconcile_done(result)` |

`refresh_token`: Die Fehler-**Klassifizierung** wandert in den Worker (`fn` liefert
`None` | `("auth", msg)` | `("error", tb)`), das **Anzeigen** in den App-Callback. Das ist
sauberer als der Bestand (dort marshallte der Worker selbst Dialoge). `TokenNetworkError`
bleibt still (Offline-Start nicht stören).

### Wiring in `App`

```python
# __init__:
self._bg = BackgroundTaskRunner(
    self._marshal_to_ui, self.settings, self.base_path,
    self.reservation_store, self._reservations_active,
)
...
self._bg.refresh_token(
    on_auth_error=lambda msg: themed_showinfo(self.root, "Gmail-Anmeldung abgelaufen", ...),
    on_error=lambda tb: themed_showinfo(self.root, "Token-Refresh fehlgeschlagen", tb),
)
self._bg.fetch_sender_email()
self._bg.check_update(on_result=self._handle_update_check_result)
self._bg.reconcile_on_start(on_ok=self._refresh)
```

`_trigger_calendar_reconcile` (nach Reservierungs-Speichern) →
`self._bg.trigger_reconcile(self._on_reconcile_done)`.

Die alten `_proactive_*`-Methoden und `_trigger_calendar_reconcile` entfallen aus `App`;
`_reservations_active`, `_handle_update_check_result`, `_on_reconcile_done`,
`_marshal_to_ui` bleiben in `App` (UI-/State-nah).

## Tests

Neues `tests/test_background_tasks.py` (das Modul ist ohne Tk/Display testbar):

- `run(fn, on_done)` führt `fn` aus und liefert dessen Ergebnis an `on_done` — mit
  synchronem Fake-`marshal` (ruft den Callback sofort) und `threading.Event` zum Abwarten
  des Worker-Threads.
- `run(fn)` ohne `on_done` ruft nichts zurück, führt `fn` aber aus.
- Guards: `check_update` ruft `check_latest_release` **nicht**, wenn `should_check_today`
  False ist; `reconcile_on_start`/`trigger_reconcile` laufen nicht, wenn
  `reservations_active()` False liefert. (Monkeypatch der I/O-Funktionen.)
- `fetch_sender_email` bricht ohne `token.json` früh ab.

Bestehende Suite bleibt grün: `tests/test_ui_delete.py` u.a. importieren `src.ui`; die
genutzten Modul-Funktionen (`_delete_action`, `_classify_sync_error`,
`_friendly_sync_message`, `_show_sync_error`) bleiben unangetastet.

## Verifikation (AC 4 — Verhalten unverändert)

Manuell per In-Place-Build (`build.py` → Exe nach `%LOCALAPPDATA%\Programs\Zeiterfassung\`),
geprüft werden:

- Month/Week-Wechsel (Tab) und Vor/Zurück-Navigation (`<Left>`/`<Right>`, Tray)
- Hover über Entry-, Holiday-, Empty- und Nur-Reservierungs-Zellen (Overlay färbt mit)
- Manueller Sync (Status-Label) und Tray-Sync (Toast)
- Update-Banner-Pfad bzw. stiller Offline-Start

## Nicht-Ziele (Folge-PRs)

- `GridRenderer` (Rendering-Extraktion) — größter Volumen-Gewinn, höchste Kopplung.
- `SyncOrchestrator` (Sync + Status + Pull-Callbacks).
- Weitere Aufteilung des Dialog-Routings / Tray-Managements.
