# ui.py-Entflechtung (Helfer + BackgroundTaskRunner) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die billigen Duplikate in `src/ui.py` über Helfer zusammenführen und die Background-Tasks in eine eigene Klasse `BackgroundTaskRunner` (`src/background_tasks.py`) auslagern — erfüllt alle vier Akzeptanzkriterien von Issue #49.

**Architecture:** Vier Helfer (`_navigate`, `_hover`, `_cell_layout_metrics`) bleiben Methoden/Statics von `App`. Die proaktiven Worker und die Thread-Mechanik wandern in eine neue, Tk-freie Klasse `BackgroundTaskRunner`; `App` konstruiert sie und übergibt UI-Arbeit als Callbacks. Verhalten bleibt unverändert.

**Tech Stack:** Python 3, Tkinter, pytest. Reine stdlib im neuen Modul (keine Tk-/Google-Imports auf Modulebene; `run_calendar_reconcile` Lazy-Import in der Methode).

## Global Constraints

- Verhalten unverändert (AC 4) — UI manuell verifiziert (Month/Week, Navigation, Hover, Sync, Tray).
- `src/background_tasks.py`: **keine** Tk-Imports, **keine** Google-Imports auf Modulebene. `from src.main import run_calendar_reconcile` bleibt Lazy-Import **innerhalb** der Methode (Circular-Import-Schutz: `src.main` importiert `App` aus `ui`).
- Datum intern ISO, UI deutsch (hier nicht berührt, aber nicht brechen).
- Lint: `python -m ruff check .` muss grün sein.
- Tests: `python -m pytest` grün (lokal sind Google-Libs installiert).
- Commit-Messages enden mit `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- PowerShell 5.1: keine `&&`-Verkettung; `;` oder `if ($?) { }`.

---

### Task 1: `_navigate(direction)` ersetzt `_prev`/`_next`

**Files:**
- Modify: `src/ui.py` (Methoden `_prev`/`_next` bei ~540-568; Key-Bindings bei ~210-211)
- Test: `tests/test_ui_navigate.py` (neu)

**Interfaces:**
- Produces: `App._navigate(self, direction)` — `direction ∈ {-1, +1}`; mutiert `self.year`/`self.month` (month-Modus) bzw. `self.iso_year`/`self.current_week` (week-Modus) und ruft `self._refresh()`.

- [ ] **Step 1: Failing test schreiben**

`tests/test_ui_navigate.py`:
```python
"""_navigate ersetzt _prev/_next. Getestet ohne Tk über einen Stub mit den
relevanten Attributen; _refresh ist ein No-op."""

import datetime

from src.ui import App


class _Stub:
    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.refreshed = 0

    def _refresh(self):
        self.refreshed += 1


def _nav(stub, direction):
    App._navigate(stub, direction)


def test_month_forward_within_year():
    s = _Stub(view_mode="month", year=2026, month=6)
    _nav(s, +1)
    assert (s.year, s.month) == (2026, 7)
    assert s.refreshed == 1


def test_month_backward_wraps_to_previous_year():
    s = _Stub(view_mode="month", year=2026, month=1)
    _nav(s, -1)
    assert (s.year, s.month) == (2025, 12)


def test_month_forward_wraps_to_next_year():
    s = _Stub(view_mode="month", year=2026, month=12)
    _nav(s, +1)
    assert (s.year, s.month) == (2027, 1)


def test_week_forward_advances_seven_days():
    # KW 26/2026 -> +1 Woche = KW 27
    s = _Stub(view_mode="week", iso_year=2026, current_week=26)
    _nav(s, +1)
    assert (s.iso_year, s.current_week) == (2026, 27)


def test_week_backward_crosses_year_boundary():
    # KW 1/2026 -> -1 Woche landet in 2025
    s = _Stub(view_mode="week", iso_year=2026, current_week=1)
    _nav(s, -1)
    assert s.iso_year == 2025
    assert s.current_week >= 52
```

- [ ] **Step 2: Test failt sehen**

Run: `python -m pytest tests/test_ui_navigate.py -q`
Expected: FAIL — `AttributeError: type object 'App' has no attribute '_navigate'`.

- [ ] **Step 3: `_navigate` implementieren, `_prev`/`_next` entfernen**

In `src/ui.py` die beiden Methoden `_prev` und `_next` (ganzer Block ~540-568) ersetzen durch:
```python
    def _navigate(self, direction):
        """Blättert die Ansicht um `direction` Einheiten (-1 zurück, +1 vor):
        im Monatsmodus ±1 Monat (mit Jahreswechsel), im Wochenmodus ±7 Tage."""
        if self.view_mode == "month":
            m = self.month + direction
            if m < 1:
                self.month, self.year = 12, self.year - 1
            elif m > 12:
                self.month, self.year = 1, self.year + 1
            else:
                self.month = m
        else:
            monday = get_week_dates(self.iso_year, self.current_week)[0] \
                + datetime.timedelta(days=7 * direction)
            self.iso_year, self.current_week = monday.isocalendar()[:2]
        self._refresh()
```

- [ ] **Step 4: Key-Bindings umbiegen**

In `src/ui.py` (~210-211):
```python
        self.root.bind("<Left>", lambda e: self._prev())
        self.root.bind("<Right>", lambda e: self._next())
```
ersetzen durch:
```python
        self.root.bind("<Left>", lambda e: self._navigate(-1))
        self.root.bind("<Right>", lambda e: self._navigate(+1))
```

- [ ] **Step 5: Sicherstellen, dass keine `_prev`/`_next`-Referenzen übrig sind**

Run: `python -m pytest tests/test_ui_navigate.py -q ; python -m ruff check src/ui.py`
Grep zur Kontrolle: es darf kein `self._prev(` / `self._next(` mehr geben.
Expected: Tests PASS, Lint grün.

- [ ] **Step 6: Commit**

```
git add src/ui.py tests/test_ui_navigate.py
git commit -m "refactor(ui): _prev/_next zu _navigate(direction) zusammenfuehren (#49)"
```

---

### Task 2: `_hover(frame, bg, *labels)` vereint `_cell_hover`/`_empty_hover`

**Files:**
- Modify: `src/ui.py` (Statics `_cell_hover` ~1278, `_empty_hover` ~1293; Call-Sites ~855-856, ~936-937, ~1266-1269)
- Test: `tests/test_ui_hover.py` (neu)

**Interfaces:**
- Produces: `App._hover(frame, bg, *labels)` (staticmethod) — setzt `bg` auf `frame`, jedes Label in `labels` und die Overlay-Widgets `frame._reservation_marker` / `frame._delete_button` falls vorhanden.

- [ ] **Step 1: Failing test schreiben**

`tests/test_ui_hover.py`:
```python
"""_hover faerbt Frame, uebergebene Labels und vorhandene Eck-Overlays."""

from src.ui import App


class _FakeWidget:
    def __init__(self):
        self.bg = None

    def config(self, bg):
        self.bg = bg


def test_hover_colors_frame_and_labels():
    frame, day, time = _FakeWidget(), _FakeWidget(), _FakeWidget()
    App._hover(frame, "#123456", day, time)
    assert frame.bg == "#123456"
    assert day.bg == "#123456"
    assert time.bg == "#123456"


def test_hover_colors_overlay_widgets_when_present():
    frame = _FakeWidget()
    frame._reservation_marker = _FakeWidget()
    frame._delete_button = _FakeWidget()
    App._hover(frame, "#abcdef")
    assert frame._reservation_marker.bg == "#abcdef"
    assert frame._delete_button.bg == "#abcdef"


def test_hover_without_overlays_does_not_fail():
    frame, day = _FakeWidget(), _FakeWidget()
    App._hover(frame, "#000000", day)
    assert frame.bg == "#000000"
    assert day.bg == "#000000"
```

- [ ] **Step 2: Test failt sehen**

Run: `python -m pytest tests/test_ui_hover.py -q`
Expected: FAIL — `AttributeError: type object 'App' has no attribute '_hover'`.

- [ ] **Step 3: `_hover` implementieren, `_cell_hover`/`_empty_hover` entfernen**

In `src/ui.py` den ganzen Block der beiden Statics (`_cell_hover` ~1278-1291 und `_empty_hover` ~1292-1304, inkl. der `@staticmethod`-Dekoratoren) ersetzen durch:
```python
    @staticmethod
    def _hover(frame, bg, *labels):
        """Faerbt Zelle + uebergebene Labels beim Hover. Die Eck-Overlays
        (_reservation_marker, macOS-_delete_button) werden mitgefaerbt, sonst
        bleibt ein andersfarbiges Rechteck stehen. Nur bg — die fg des
        Loesch-Buttons steuert dessen eigener Enter/Leave-Handler."""
        frame.config(bg=bg)
        for lbl in labels:
            lbl.config(bg=bg)
        for attr in ("_reservation_marker", "_delete_button"):
            w = getattr(frame, attr, None)
            if w is not None:
                w.config(bg=bg)
```

- [ ] **Step 4: Call-Sites umstellen**

Entry-Zelle (`src/ui.py` ~855-856):
```python
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, tl=time_lbl, hb=hover_bg: self._cell_hover(c, dl, tl, hb))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, tl=time_lbl, ob=bg: self._cell_hover(c, dl, tl, ob))
```
→
```python
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, tl=time_lbl, hb=hover_bg: self._hover(c, hb, dl, tl))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, tl=time_lbl, ob=bg: self._hover(c, ob, dl, tl))
```

Empty-Zelle (`src/ui.py` ~936-937):
```python
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, hb=hover_bg: self._empty_hover(c, dl, hb))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, ob=bg: self._empty_hover(c, dl, ob))
```
→
```python
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, hb=hover_bg: self._hover(c, hb, dl))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, ob=bg: self._hover(c, ob, dl))
```

Holiday-Zelle (`src/ui.py` ~1266-1269):
```python
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, nl=name_lbl:
                self._cell_hover(c, dl, nl, HOLIDAY_BG_HOVER))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, nl=name_lbl:
                self._cell_hover(c, dl, nl, HOLIDAY_BG))
```
→
```python
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, nl=name_lbl:
                self._hover(c, HOLIDAY_BG_HOVER, dl, nl))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, nl=name_lbl:
                self._hover(c, HOLIDAY_BG, dl, nl))
```

- [ ] **Step 5: Tests + Lint, keine `_cell_hover`/`_empty_hover`-Reste**

Run: `python -m pytest tests/test_ui_hover.py -q ; python -m ruff check src/ui.py`
Grep-Kontrolle: kein `_cell_hover` / `_empty_hover` mehr im Code.
Expected: PASS, Lint grün.

- [ ] **Step 6: Commit**

```
git add src/ui.py tests/test_ui_hover.py
git commit -m "refactor(ui): _cell_hover/_empty_hover zu _hover zusammenfuehren (#49)"
```

---

### Task 3: `_cell_layout_metrics(frame)` entdoppelt das Probe-Pattern

**Files:**
- Modify: `src/ui.py` (Konstanten oben; Probe-Block in `_refresh_month` ~1094-1105 und `_refresh_week` ~1178-1184)

**Interfaces:**
- Produces: `App._cell_layout_metrics(self, frame) -> (cell_size, entry_time_font, holiday_name_font, wide_cells)` — `cell_size` ist `(reqwidth, reqheight)` eines Probe-Labels.
- Produces: Modulkonstanten `PROBE_WIDTH_WIDE = 12`, `PROBE_WIDTH_NARROW = 8`, `PROBE_HEIGHT = 3`.

*Kein Headless-Unit-Test (braucht Tk-Display); Verifikation über bestehende Render-Pfade + manuelles AC-4-Smoke in Task 7.*

- [ ] **Step 1: Konstanten + Methode anlegen**

In `src/ui.py` nach den Imports (vor `class App` bzw. zu den bestehenden Modul-Konstanten) ergänzen:
```python
# Probe-Label-Geometrie zur Zellgroessen-Messung (Month- und Week-Render teilen sie).
PROBE_WIDTH_WIDE = 12    # ausgeblendetes Wochenende -> breitere Zellen
PROBE_WIDTH_NARROW = 8   # 7-Spalten-Modus
PROBE_HEIGHT = 3
```

Als neue Methode in `App` (z.B. direkt vor `_refresh_month`):
```python
    def _cell_layout_metrics(self, frame):
        """Misst die natuerliche Pixelgroesse einer Standard-Tageszelle (Probe-
        Label) und liefert die layout-abhaengigen Groessen.

        Bei ausgeblendetem Wochenende (5 statt 7 Spalten) bleibt mehr Horizontal-
        platz pro Spalte: breitere Zellen und groessere Zeit-/Feiertagsschrift
        (FONT statt FONT_SMALL), damit z.B. '09:30-17:00' bequem lesbar bleibt.
        Holiday-Zellen werden spaeter auf `cell_size` fixiert, damit lange
        Feiertagsnamen die Spalte nicht aufweiten (Header-Reflow/Flackern)."""
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

- [ ] **Step 2: `_refresh_month` umstellen**

In `src/ui.py` den Block ~1094-1105 (von `wide_cells = not self.settings.get("show_weekend")` bis `probe.destroy()`) ersetzen durch:
```python
        cell_size, entry_time_font, holiday_name_font, wide_cells = \
            self._cell_layout_metrics(new_frame)
```
Die nachfolgende Nutzung (`holiday_max_len=12 if wide_cells else 9`, `entry_time_font`, `holiday_name_font`, `cell_size`) bleibt unverändert.

- [ ] **Step 3: `_refresh_week` umstellen**

In `src/ui.py` den analogen Block ~1178-1184 ersetzen durch:
```python
        cell_size, entry_time_font, holiday_name_font, wide_cells = \
            self._cell_layout_metrics(new_frame)
```
Falls `_refresh_week` `wide_cells` nicht weiterverwendet, ist die Variable ungenutzt → dann in der Entpackung durch `_` ersetzen, damit Lint (F841) nicht meckert. (Vor dem Commit per Lint prüfen.)

- [ ] **Step 4: Lint + voller Testlauf (Render-Pfade dürfen nicht brechen)**

Run: `python -m ruff check src/ui.py ; python -m pytest -q`
Expected: Lint grün; Tests PASS (gleiche Anzahl wie vorher).

- [ ] **Step 5: Commit**

```
git add src/ui.py
git commit -m "refactor(ui): Probe-Label-Messung in _cell_layout_metrics buendeln (#49)"
```

---

### Task 4: `BackgroundTaskRunner.run()` — neues Modul + Thread-Helfer

**Files:**
- Create: `src/background_tasks.py`
- Test: `tests/test_background_tasks.py` (neu)

**Interfaces:**
- Produces: `BackgroundTaskRunner(marshal, settings, base_path, reservation_store, reservations_active)`
- Produces: `BackgroundTaskRunner.run(self, fn, on_done=None)` — führt `fn()` im Daemon-Thread aus und liefert dessen Rückgabe via `marshal(lambda: on_done(result))`. `marshal` ist eine Callable `(callback) -> None`.

- [ ] **Step 1: Failing test schreiben**

`tests/test_background_tasks.py`:
```python
"""BackgroundTaskRunner: run() fuehrt fn im Thread aus und liefert das
Ergebnis ueber marshal an on_done. marshal wird im Test synchron gefakt."""

import threading

from src.background_tasks import BackgroundTaskRunner


def _runner(**overrides):
    kw = dict(
        marshal=lambda cb: cb(),          # synchron ausfuehren
        settings=overrides.pop("settings", {}),
        base_path=overrides.pop("base_path", "."),
        reservation_store=overrides.pop("reservation_store", None),
        reservations_active=overrides.pop("reservations_active", lambda: False),
    )
    kw.update(overrides)
    return BackgroundTaskRunner(**kw)


def test_run_executes_fn_and_delivers_result_to_on_done():
    done = threading.Event()
    received = {}

    def on_done(result):
        received["value"] = result
        done.set()

    _runner().run(lambda: 42, on_done)

    assert done.wait(timeout=5)
    assert received["value"] == 42


def test_run_without_on_done_still_executes_fn():
    ran = threading.Event()

    def fn():
        ran.set()
        return None

    _runner().run(fn)

    assert ran.wait(timeout=5)
```

- [ ] **Step 2: Test failt sehen**

Run: `python -m pytest tests/test_background_tasks.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.background_tasks'`.

- [ ] **Step 3: Modul mit `run()` implementieren**

`src/background_tasks.py`:
```python
"""Hintergrund-Tasks der App (Token-Refresh, Sender-Email, Update-Check,
Kalender-Reconcile) und die gemeinsame Thread-Mechanik.

Tk-frei und ohne Google-Imports auf Modulebene: `run_calendar_reconcile`
wird lazy in der Methode importiert (Circular-Import-Schutz — src.main zieht
App aus src.ui). UI-Arbeit (Dialoge, Banner, Refresh) macht die Klasse nicht
selbst, sondern liefert Ergebnisse ueber `marshal` an Callbacks der App.
"""

import logging
import os
import threading
import traceback

from src.mail import (
    fetch_user_email,
    refresh_token_if_needed,
    TokenAuthError,
    TokenNetworkError,
)
from src.updater import check_latest_release, is_newer, should_check_today
from src.version import VERSION

log = logging.getLogger(__name__)


class BackgroundTaskRunner:
    def __init__(self, marshal, settings, base_path, reservation_store,
                 reservations_active):
        self._marshal = marshal                          # App._marshal_to_ui
        self._settings = settings
        self._base_path = base_path
        self._reservation_store = reservation_store
        self._reservations_active = reservations_active  # callable -> bool

    def run(self, fn, on_done=None):
        """Fuehrt fn() in einem Daemon-Thread aus und liefert dessen Rueckgabe
        via marshal an on_done auf dem UI-Thread."""
        def worker():
            result = fn()
            if on_done is not None:
                self._marshal(lambda: on_done(result))
        threading.Thread(target=worker, daemon=True).start()
```

- [ ] **Step 4: Tests grün**

Run: `python -m pytest tests/test_background_tasks.py -q`
Expected: PASS (2 Tests).

- [ ] **Step 5: Commit**

```
git add src/background_tasks.py tests/test_background_tasks.py
git commit -m "feat(ui): BackgroundTaskRunner mit run()-Thread-Helfer (#49)"
```

---

### Task 5: `refresh_token` + `fetch_sender_email` in den Runner

**Files:**
- Modify: `src/background_tasks.py` (zwei Methoden ergänzen)
- Modify: `src/ui.py` (`_proactive_token_refresh`/`_proactive_sender_email_fetch` entfernen; `__init__`-Wiring; Runner konstruieren)
- Test: `tests/test_background_tasks.py` (Guard-Test für `fetch_sender_email`)

**Interfaces:**
- Consumes: `BackgroundTaskRunner.run` (Task 4).
- Produces: `BackgroundTaskRunner.refresh_token(self, on_auth_error, on_error)` — `on_auth_error(msg: str)`, `on_error(tb: str)`.
- Produces: `BackgroundTaskRunner.fetch_sender_email(self)` — setzt bei neuer Adresse `settings["sender_email"]` via marshal; no-op ohne `token.json`.
- Produces: `App._bg` (Instanz von `BackgroundTaskRunner`), gesetzt in `__init__`.

- [ ] **Step 1: Guard-Test für `fetch_sender_email` schreiben**

In `tests/test_background_tasks.py` ergänzen:
```python
def test_fetch_sender_email_noop_without_token(tmp_path):
    # base_path ohne token.json -> fetch_user_email darf nicht aufgerufen werden
    import src.background_tasks as bg

    called = {"n": 0}
    orig = bg.fetch_user_email
    bg.fetch_user_email = lambda *a, **k: called.__setitem__("n", called["n"] + 1) or ""
    try:
        _runner(base_path=str(tmp_path)).fetch_sender_email()
        import time
        time.sleep(0.2)
    finally:
        bg.fetch_user_email = orig
    assert called["n"] == 0
```

- [ ] **Step 2: Test failt sehen**

Run: `python -m pytest tests/test_background_tasks.py::test_fetch_sender_email_noop_without_token -q`
Expected: FAIL — `AttributeError: 'BackgroundTaskRunner' object has no attribute 'fetch_sender_email'`.

- [ ] **Step 3: Methoden im Runner implementieren**

In `src/background_tasks.py` in der Klasse ergänzen:
```python
    def refresh_token(self, on_auth_error, on_error):
        """Erneuert den Gmail-Token beim Start im Hintergrund. Auth-Fehler ->
        on_auth_error(msg); unerwartete Fehler -> on_error(traceback);
        Netzwerkfehler werden still uebergangen (Offline-Start)."""
        token_path = os.path.join(self._base_path, "token.json")

        def fn():
            try:
                refresh_token_if_needed(
                    token_path,
                    sync_enabled=self._settings.get("sync_enabled"),
                    gcal_enabled=self._settings.get("gcal_enabled"),
                )
                return None
            except TokenAuthError as e:
                return ("auth", str(e))
            except TokenNetworkError:
                return None
            except Exception:
                log.exception("Token-Refresh fehlgeschlagen")
                return ("error", traceback.format_exc())

        def on_done(outcome):
            if outcome is None:
                return
            kind, payload = outcome
            if kind == "auth":
                on_auth_error(payload)
            else:
                on_error(payload)

        self.run(fn, on_done)

    def fetch_sender_email(self):
        """Holt einmalig pro Start die authentifizierte E-Mail ueber OAuth2-
        Userinfo und cached sie in settings.sender_email. Still bei fehlendem
        Token/Netz/Scope (der naechste Send-Dialog triggert den Re-Consent)."""
        token_path = os.path.join(self._base_path, "token.json")
        if not os.path.exists(token_path):
            return

        def fn():
            try:
                email = fetch_user_email(
                    token_path,
                    sync_enabled=self._settings.get("sync_enabled"),
                    gcal_enabled=self._settings.get("gcal_enabled"),
                )
            except Exception:
                log.exception("sender_email-Fetch fehlgeschlagen")
                return None
            return email

        def on_done(email):
            if email and email != self._settings.get("sender_email"):
                self._settings.set("sender_email", email)

        self.run(fn, on_done)
```

- [ ] **Step 4: Runner in `App.__init__` konstruieren + verdrahten**

In `src/ui.py` oben den Import ergänzen (zu den `from src...`-Imports):
```python
from src.background_tasks import BackgroundTaskRunner
```

In `App.__init__`, vor den bisherigen `self._proactive_*`-Aufrufen (~221-226), den Runner anlegen:
```python
        self._bg = BackgroundTaskRunner(
            self._marshal_to_ui, self.settings, self.base_path,
            self.reservation_store, self._reservations_active,
        )
```

Die beiden Zeilen
```python
        self._proactive_token_refresh()
        self._proactive_sender_email_fetch()
```
ersetzen durch:
```python
        self._bg.refresh_token(
            on_auth_error=lambda msg: themed_showinfo(
                self.root,
                "Gmail-Anmeldung abgelaufen",
                "Der Gmail-Token konnte nicht automatisch erneuert werden:\n\n"
                f"{msg}\n\n"
                "Beim nächsten Senden wirst du zur erneuten Anmeldung aufgefordert.",
            ),
            on_error=lambda tb: themed_showinfo(
                self.root, "Token-Refresh fehlgeschlagen", tb,
            ),
        )
        self._bg.fetch_sender_email()
```

- [ ] **Step 5: Alte Methoden entfernen**

In `src/ui.py` die Methoden `_proactive_token_refresh` (~229-262) und `_proactive_sender_email_fetch` (~264-290) vollständig löschen.

- [ ] **Step 6: Tests + Lint**

Run: `python -m pytest tests/test_background_tasks.py -q ; python -m ruff check src/ui.py src/background_tasks.py`
Grep-Kontrolle: kein `_proactive_token_refresh` / `_proactive_sender_email_fetch` mehr.
Expected: PASS, Lint grün.

- [ ] **Step 7: Commit**

```
git add src/ui.py src/background_tasks.py tests/test_background_tasks.py
git commit -m "refactor(ui): Token-Refresh + Sender-Email in BackgroundTaskRunner (#49)"
```

---

### Task 6: `check_update` + `reconcile_on_start` + `trigger_reconcile` in den Runner

**Files:**
- Modify: `src/background_tasks.py` (drei Methoden)
- Modify: `src/ui.py` (`_proactive_update_check`/`_proactive_calendar_reconcile`/`_trigger_calendar_reconcile` entfernen; `__init__`-Wiring; Caller von `_trigger_calendar_reconcile`)
- Test: `tests/test_background_tasks.py` (Guard-Tests)

**Interfaces:**
- Consumes: `BackgroundTaskRunner.run`, `self._reservations_active`, `self._settings`.
- Produces: `BackgroundTaskRunner.check_update(self, on_result)` — `on_result(release, newer: bool)`; läuft nur wenn `should_check_today(...)`.
- Produces: `BackgroundTaskRunner.reconcile_on_start(self, on_ok)` — `on_ok()` nur bei Erfolg; guard `reservations_active()`.
- Produces: `BackgroundTaskRunner.trigger_reconcile(self, on_done)` — `on_done(result: dict)`; guard `reservations_active()`.

- [ ] **Step 1: Guard-Tests schreiben**

In `tests/test_background_tasks.py` ergänzen:
```python
def test_check_update_skips_when_not_due(monkeypatch):
    import src.background_tasks as bg
    monkeypatch.setattr(bg, "should_check_today", lambda v: False)
    called = {"n": 0}
    monkeypatch.setattr(bg, "check_latest_release",
                        lambda repo: called.__setitem__("n", called["n"] + 1))
    r = _runner(settings={"last_update_check_at": None})
    # settings als dict -> .get reicht; should_check_today ist gepatcht
    r.check_update(on_result=lambda rel, newer: None)
    import time
    time.sleep(0.2)
    assert called["n"] == 0


def test_reconcile_on_start_skips_when_reservations_inactive():
    ran = {"n": 0}
    r = _runner(reservations_active=lambda: False)
    r.reconcile_on_start(on_ok=lambda: ran.__setitem__("n", ran["n"] + 1))
    import time
    time.sleep(0.2)
    assert ran["n"] == 0
```

Hinweis: `_runner`-Settings ist ein dict; `check_update` nutzt nur `should_check_today` (gepatcht) und `check_latest_release` (gepatcht) — `settings.get` wird nicht gebraucht. dict besitzt `.get`.

- [ ] **Step 2: Tests failen sehen**

Run: `python -m pytest tests/test_background_tasks.py -k "check_update or reconcile_on_start" -q`
Expected: FAIL — Methoden existieren noch nicht.

- [ ] **Step 3: Methoden im Runner implementieren**

In `src/background_tasks.py` in der Klasse ergänzen:
```python
    def check_update(self, on_result):
        """Fragt 1x pro Kalendertag GitHub nach einer neueren Version. `is_newer`
        wird bereits im Worker ausgewertet, damit on_result(release, newer) im
        UI-Thread keine ungeschuetzte Logik mehr ausfuehrt. Fehler still."""
        if not should_check_today(self._settings.get("last_update_check_at")):
            return

        def fn():
            try:
                release = check_latest_release("MargenHeld/Zeiterfassung")
                if release is None:
                    return None
                return (release, is_newer(VERSION, release.version))
            except Exception:
                log.exception("Update-Check fehlgeschlagen")
                return None

        def on_done(result):
            if result is None:
                return
            release, newer = result
            on_result(release, newer)

        self.run(fn, on_done)

    def reconcile_on_start(self, on_ok):
        """Gleicht beim Start die Reservierungen mit dem Google Kalender ab.
        Fehler werden STILL geloggt (Offline-Start nicht stoeren); bei Erfolg
        on_ok() im UI-Thread."""
        if not self._reservations_active():
            return

        def fn():
            from src.main import run_calendar_reconcile
            return run_calendar_reconcile(
                self._reservation_store, self._settings, self._base_path)

        def on_done(result):
            if result.get("ok"):
                on_ok()

        self.run(fn, on_done)

    def trigger_reconcile(self, on_done):
        """Stoesst nach einer Reservierungsaenderung den Abgleich an. Das
        Ergebnis geht IMMER an on_done(result) (User hat aktiv gespeichert und
        erwartet Feedback)."""
        if not self._reservations_active():
            return

        def fn():
            from src.main import run_calendar_reconcile
            return run_calendar_reconcile(
                self._reservation_store, self._settings, self._base_path)

        self.run(fn, on_done)
```

- [ ] **Step 4: `App.__init__`-Wiring**

In `src/ui.py` die Zeilen
```python
        self._update_banner = None
        self._proactive_update_check()
        self._proactive_calendar_reconcile()
```
ersetzen durch:
```python
        self._update_banner = None
        self._bg.check_update(on_result=self._handle_update_check_result)
        self._bg.reconcile_on_start(on_ok=self._refresh)
```

- [ ] **Step 5: Caller von `_trigger_calendar_reconcile` umbiegen**

Es gibt genau zwei Stellen in `src/ui.py`:

(a) Direkter Aufruf in `_delete_day` (~1380):
```python
        if res_touched:
            self._trigger_calendar_reconcile()
```
→
```python
        if res_touched:
            self._bg.trigger_reconcile(self._on_reconcile_done)
```

(b) Als no-arg Callback an `open_entry_dialog` in `_open_dialog` (~1394):
```python
            trigger_reconcile=self._trigger_calendar_reconcile,
```
→
```python
            trigger_reconcile=lambda: self._bg.trigger_reconcile(self._on_reconcile_done),
```
(`open_entry_dialog` ruft `trigger_reconcile()` argumentlos — das Lambda erhält diese Signatur.)

- [ ] **Step 6: Alte Methoden entfernen**

In `src/ui.py` `_proactive_update_check`, `_proactive_calendar_reconcile` und `_trigger_calendar_reconcile` vollständig löschen. `_reservations_active`, `_handle_update_check_result`, `_on_reconcile_done` BLEIBEN.

- [ ] **Step 7: Tests + Lint**

Run: `python -m pytest tests/test_background_tasks.py -q ; python -m ruff check src/ui.py src/background_tasks.py`
Grep-Kontrolle: kein `_proactive_update_check` / `_proactive_calendar_reconcile` / `_trigger_calendar_reconcile` mehr.
Expected: PASS, Lint grün.

- [ ] **Step 8: Commit**

```
git add src/ui.py src/background_tasks.py tests/test_background_tasks.py
git commit -m "refactor(ui): Update-Check + Kalender-Reconcile in BackgroundTaskRunner (#49)"
```

---

### Task 7: Sync-Methoden über `run()` + Gesamtverifikation

**Files:**
- Modify: `src/ui.py` (`_on_sync_clicked` ~1444-1459, `_tray_sync` ~1470-1487)

**Interfaces:**
- Consumes: `App._bg.run` (Task 4).

- [ ] **Step 1: `_on_sync_clicked` über `run()` führen**

In `src/ui.py` den Worker-Teil von `_on_sync_clicked`:
```python
        self.sync_status_label.config(text="Synchronisiere…")
        import threading
        from src.main import _run_push_blocking
        def _do():
            result = _run_push_blocking(
                self.storage, self.settings, self.conflicts_store,
                self.base_path, timeout_seconds=15,
            )
            self._marshal_to_ui(lambda: self._on_manual_sync_done(result))
        threading.Thread(target=_do, daemon=True).start()
```
ersetzen durch:
```python
        self.sync_status_label.config(text="Synchronisiere…")
        from src.main import _run_push_blocking
        self._bg.run(
            lambda: _run_push_blocking(
                self.storage, self.settings, self.conflicts_store,
                self.base_path, timeout_seconds=15,
            ),
            self._on_manual_sync_done,
        )
```

- [ ] **Step 2: `_tray_sync` über `run()` führen**

In `src/ui.py` den Worker-Teil von `_tray_sync`:
```python
        import threading
        from src.main import _run_push_blocking

        def _do():
            result = _run_push_blocking(
                self.storage, self.settings, self.conflicts_store,
                self.base_path, timeout_seconds=15,
            )
            self._marshal_to_ui(lambda: self._on_tray_sync_done(result))
        threading.Thread(target=_do, daemon=True).start()
```
ersetzen durch:
```python
        from src.main import _run_push_blocking
        self._bg.run(
            lambda: _run_push_blocking(
                self.storage, self.settings, self.conflicts_store,
                self.base_path, timeout_seconds=15,
            ),
            self._on_tray_sync_done,
        )
```

- [ ] **Step 3: `threading`-Import prüfen**

Nach den Tasks nutzt `src/ui.py` ggf. kein `threading` mehr direkt. Grep `threading` in `src/ui.py`: wenn keine Verwendung mehr → `import threading` (Zeile ~10) entfernen. Wenn noch verwendet → lassen. Lint (F401) entscheidet mit.

- [ ] **Step 4: Voller Testlauf + Lint**

Run: `python -m pytest -q ; python -m ruff check .`
Expected: alle Tests PASS (bestehende + neue `test_ui_navigate`, `test_ui_hover`, `test_background_tasks`); Lint grün.

- [ ] **Step 5: Manuelle AC-4-Verifikation (In-Place-Build)**

Build + Exe ersetzen (Inno fehlt lokal → nur PyInstaller-Artefakt in den Install-Ordner kopieren):
```
python build.py
```
Dann die gebaute App starten und prüfen:
- Month↔Week-Toggle (Tab), Vor/Zurück mit `<Left>`/`<Right>`.
- Hover über Entry-, Holiday-, Empty- und Nur-Reservierungs-Zelle (Eck-Overlay färbt mit).
- Manueller Sync (Status-Label „Synchronisiere…“ → Ergebnis), Tray-Sync (Toast).
- App-Start ohne Internet: kein Fehlerdialog (stiller Offline-Pfad).

Falls Build/Start hier nicht möglich: mindestens `python -m src.main` aus dem Repo starten und dieselben Punkte prüfen.

- [ ] **Step 6: Commit**

```
git add src/ui.py
git commit -m "refactor(ui): Sync-Methoden ueber BackgroundTaskRunner.run() (#49)"
```

---

## Self-Review

**Spec coverage:**
- AC 1 (Thread-Muster über einen Helper): Task 4 (`run()`) + Tasks 5/6 (proaktive) + Task 7 (Sync). ✓
- AC 2 (Hover + Probe dedupliziert): Task 2 (`_hover`) + Task 3 (`_cell_layout_metrics`). ✓ (Navigation als Bonus-Dedup in Task 1.)
- AC 3 (≥1 Verantwortlichkeit ausgelagert): Tasks 4–6 (`BackgroundTaskRunner`). ✓
- AC 4 (Verhalten unverändert, manuell): Task 7 Step 5. ✓

**Type-Konsistenz:** `run(fn, on_done)`, `refresh_token(on_auth_error, on_error)`, `fetch_sender_email()`, `check_update(on_result)`, `reconcile_on_start(on_ok)`, `trigger_reconcile(on_done)`, `_navigate(direction)`, `_hover(frame, bg, *labels)`, `_cell_layout_metrics(frame) -> (cell_size, entry_time_font, holiday_name_font, wide_cells)` — über alle Tasks konsistent verwendet.

**Platzhalter:** keine.

**Offene Risiken:**
- `_trigger_calendar_reconcile`-Caller (Task 6 Step 5): exakte Stelle per Grep verifizieren, bevor entfernt wird.
- `threading`/`wide_cells`-Import-/Variablen-Reste: durch Lint (F401/F841) in Tasks 3 & 7 abgesichert.
