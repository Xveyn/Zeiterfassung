# Reservierungs-Erinnerungen mit Toast — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine optionale Toast-Erinnerung, die feuert, wenn ein reservierter Zeitslot mit Kategorie endet, ohne dass für diese Kategorie am selben Tag Ist-Zeit erfasst wurde — plus eine dedizierte Checkbox zum Aktivieren und ein validiertes „N Minuten vor Ende".

**Architecture:** Pure Entscheidungslogik in `src/reminders.py` (Tk-frei, `now` als Parameter). Ein `ReminderScheduler` (`src/reminder_scheduler.py`) pollt periodisch über `root.after`, liest heutige Reservierungen + Ist-Zeiten und schickt fällige Toasts über das bestehende Tray-`notify()`. Der Tray wird vom Minimize-to-Tray entkoppelt (läuft künftig bei `minimize_to_tray` ODER `reminders_enabled`). Zwei neue gerätelokale Settings + Controls im App-Tab des (getabbten) Settings-Dialogs.

**Tech Stack:** Python 3, Tkinter (`root.after`-Loop), bestehendes pystray-/NSStatusItem-Tray über `src/tray.py`.

**Referenz-Spec:** `docs/superpowers/specs/2026-07-02-reservation-reminders-design.md`

## Global Constraints

- **Match-Regel:** Reminder nur, wenn an dem Tag KEIN Ist-Zeit-Slot mit derselben (nicht-leeren) Kategorie existiert. Kategorie-Ebene, keine Zeitfenster-Überlappung.
- **Nur kategorisierte Reservierungen** lösen aus; leere Kategorie → ignoriert. Der UI-Block sagt das dem Nutzer („Nur für Reservierungen mit Kategorie.").
- **Zwei sich ausschließende Typen pro Slot:** `now >= end` → `missed`; sonst `now >= max(start, end − N)` → `upcoming`; sonst nicht fällig. Pro Slot feuert genau einer (Zeit-Reihenfolge + `already_fired`).
- **N (Minuten):** Ganzzahl **0–120**, Default **15**, Schritt 5, validiert. `N ≥ Slotlänge` → `upcoming` bei `start`.
- **Nur heutige** Reservierungen. `already_fired` **nur im Speicher** (Neustart darf erneut feuern).
- **Kanal entkoppelt:** Tray läuft bei `minimize_to_tray` ODER `reminders_enabled`; gestoppt nur wenn beide aus. Scheiterte die Tray-Erzeugung → beide auslösenden Settings zurücksetzen.
- **Plattform:** Notifications folgen dem bestehenden `tray.is_supported()`-Gate (Windows voll, macOS nur mit `ZEIT_MACOS_TRAY=1`, Linux nicht). Kein macOS-Ausbau.
- Neue Settings **gerätelokal**: `reminders_enabled` (bool, False), `reminder_minutes_before` (int, 15) in `DEFAULTS`, **NICHT** in `SYNCED_SETTING_KEYS`.
- `settings.py` bleibt stdlib-only (kein holidays/google/Tk-Import).
- Zeiten sind `"HH:MM"`-Strings; intern ISO-Datum. Datumsanzeige-Konvention hier nicht betroffen (Toast zeigt die `end`-Uhrzeit als `HH:MM`).
- `pytest` + `ruff check .` müssen grün bleiben. Tk-/Display-abhängige Teile (Dialog, App-Wiring) haben KEINEN CI-Test — lokal per Screenshot/manuell verifizieren.

---

### Task 1: Pure Reminder-Logik (`src/reminders.py`)

**Files:**
- Create: `src/reminders.py`
- Test: `tests/test_reminders.py`

**Interfaces:**
- Produces:
  - `Reminder = namedtuple("Reminder", ["key", "kind", "kategorie", "end"])` — `kind ∈ {"upcoming","missed"}`, `key = (date_iso, start_str, end_str, kategorie)`, `end` = rohe `"HH:MM"`.
  - `due_reminders(reserved_slots, logged_categories, now_dt, minutes_before, already_fired) -> list[Reminder]`
    - `reserved_slots`: Iterable von `{"start","end","kategorie"}`-Dicts.
    - `logged_categories`: `set[str]` der heute erfassten, nicht-leeren Kategorien.
    - `now_dt`: `datetime.datetime` (naiv, lokal).
    - `minutes_before`: `int`.
    - `already_fired`: `set` von `key`s.

- [ ] **Step 1: Failing test schreiben**

`tests/test_reminders.py`:

```python
import datetime

from src.reminders import Reminder, due_reminders


def _now(h, m):
    # Fester Referenztag 2026-07-02 (Do), lokal-naiv.
    return datetime.datetime(2026, 7, 2, h, m)


SLOT = {"start": "09:00", "end": "17:00", "kategorie": "Projekt A"}


def test_before_window_none():
    assert due_reminders([SLOT], set(), _now(16, 30), 15, set()) == []


def test_within_window_upcoming():
    res = due_reminders([SLOT], set(), _now(16, 50), 15, set())
    assert len(res) == 1
    assert res[0].kind == "upcoming"
    assert res[0].kategorie == "Projekt A"
    assert res[0].end == "17:00"
    assert res[0].key == ("2026-07-02", "09:00", "17:00", "Projekt A")


def test_after_end_missed():
    res = due_reminders([SLOT], set(), _now(17, 30), 15, set())
    assert len(res) == 1 and res[0].kind == "missed"


def test_category_already_logged_none():
    assert due_reminders([SLOT], {"Projekt A"}, _now(16, 55), 15, set()) == []


def test_empty_category_skipped():
    slot = {"start": "09:00", "end": "17:00", "kategorie": ""}
    assert due_reminders([slot], set(), _now(17, 30), 15, set()) == []


def test_already_fired_none():
    key = ("2026-07-02", "09:00", "17:00", "Projekt A")
    assert due_reminders([SLOT], set(), _now(16, 55), 15, {key}) == []


def test_n_larger_than_slot_fires_at_start():
    # N=600 Min -> end-N liegt vor start; Fenster beginnt bei start (09:00).
    assert due_reminders([SLOT], set(), _now(8, 59), 600, set()) == []
    res = due_reminders([SLOT], set(), _now(9, 1), 600, set())
    assert len(res) == 1 and res[0].kind == "upcoming"


def test_invalid_time_skipped():
    bad = {"start": "09:00", "end": "kaputt", "kategorie": "X"}
    assert due_reminders([bad], set(), _now(17, 30), 15, set()) == []


def test_missed_takes_precedence_over_upcoming_window():
    # now == end -> missed (nicht upcoming), auch wenn end im [end-N,end)-Rand liegt.
    res = due_reminders([SLOT], set(), _now(17, 0), 15, set())
    assert len(res) == 1 and res[0].kind == "missed"
```

- [ ] **Step 2: Test rot verifizieren**

Run: `pytest tests/test_reminders.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.reminders'`).

- [ ] **Step 3: `src/reminders.py` implementieren**

```python
"""Pure Reminder-Entscheidungslogik (Tk-frei, keine datetime.now()-Bindung).

Ermittelt, für welche heutigen reservierten Slots eine Toast-Erinnerung fällig
ist: 'upcoming' (N Minuten vor Ende, während man im Slot ist) oder 'missed'
(Slot-Ende bereits vorbei). Beides nur für Slots mit gesetzter Kategorie, deren
Kategorie am Tag noch nicht als Ist-Zeit erfasst wurde. Pro Slot feuert genau
einer der beiden Typen — garantiert durch die Zeit-Reihenfolge (missed vor dem
upcoming-Fenster) plus das already_fired-Set beim Aufrufer.
"""
import datetime
from collections import namedtuple

Reminder = namedtuple("Reminder", ["key", "kind", "kategorie", "end"])


def _parse_hhmm(date, value):
    """'HH:MM' + date -> datetime; None/ungültig -> None."""
    if not isinstance(value, str):
        return None
    try:
        hh, mm = value.split(":")
        return datetime.datetime(date.year, date.month, date.day, int(hh), int(mm))
    except (ValueError, TypeError):
        return None


def due_reminders(reserved_slots, logged_categories, now_dt,
                  minutes_before, already_fired):
    """Liefert die fälligen Reminder für die heutigen reservierten Slots.

    reserved_slots: Iterable von {start, end, kategorie}.
    logged_categories: set der heute als Ist-Zeit erfassten nicht-leeren Kategorien.
    now_dt: datetime 'jetzt' (naiv, lokal — das Datum von now_dt ist 'heute').
    minutes_before: int N (>= 0).
    already_fired: set von keys, die bereits benachrichtigt wurden.

    key = (now_dt.date().isoformat(), start_str, end_str, kategorie).
    Fällig, wenn Kategorie gesetzt UND nicht in logged_categories UND key nicht
    in already_fired:
      now >= end                         -> 'missed'
      now >= max(start, end - N Minuten) -> 'upcoming'
      sonst                              -> nicht fällig.
    """
    date = now_dt.date()
    delta = datetime.timedelta(minutes=minutes_before)
    out = []
    for slot in reserved_slots:
        kategorie = (slot.get("kategorie") or "").strip()
        if not kategorie or kategorie in logged_categories:
            continue
        start = _parse_hhmm(date, slot.get("start"))
        end = _parse_hhmm(date, slot.get("end"))
        if start is None or end is None:
            continue
        key = (date.isoformat(), slot.get("start"), slot.get("end"), kategorie)
        if key in already_fired:
            continue
        if now_dt >= end:
            out.append(Reminder(key, "missed", kategorie, slot.get("end")))
        elif now_dt >= max(start, end - delta):
            out.append(Reminder(key, "upcoming", kategorie, slot.get("end")))
    return out
```

- [ ] **Step 4: Test grün verifizieren**

Run: `pytest tests/test_reminders.py -q`
Expected: PASS (9 Tests).

- [ ] **Step 5: Ruff**

Run: `ruff check src/reminders.py tests/test_reminders.py`
Expected: All checks passed.

- [ ] **Step 6: Commit**

```bash
git add src/reminders.py tests/test_reminders.py
git commit -m "feat(reminders): pure Fälligkeits-Logik für Reservierungs-Erinnerungen"
```

---

### Task 2: Settings-Keys + Validator (`src/settings.py`)

**Files:**
- Modify: `src/settings.py` (DEFAULTS um 2 Keys ergänzen; `parse_reminder_minutes` neu)
- Test: `tests/test_settings.py` (Validator-Tests ergänzen)

**Interfaces:**
- Produces: `parse_reminder_minutes(raw) -> int | None` — Ganzzahl in `[0,120]` oder `None`.
- Produces: Default-Keys `reminders_enabled` (bool, False), `reminder_minutes_before` (int, 15). **Nicht** in `SYNCED_SETTING_KEYS`.

- [ ] **Step 1: Failing test schreiben**

Ans Ende von `tests/test_settings.py` anhängen:

```python
# --- parse_reminder_minutes (Reservierungs-Erinnerungen) ---
from src.settings import parse_reminder_minutes  # noqa: E402


def test_parse_reminder_minutes_valid():
    assert parse_reminder_minutes("15") == 15
    assert parse_reminder_minutes("0") == 0
    assert parse_reminder_minutes("120") == 120
    assert parse_reminder_minutes(30) == 30


def test_parse_reminder_minutes_out_of_range():
    assert parse_reminder_minutes("121") is None
    assert parse_reminder_minutes("-1") is None


def test_parse_reminder_minutes_non_numeric():
    assert parse_reminder_minutes("abc") is None
    assert parse_reminder_minutes("") is None
    assert parse_reminder_minutes("15.5") is None
    assert parse_reminder_minutes(None) is None


def test_reminder_defaults_present_and_device_local():
    from src.settings import DEFAULTS, SYNCED_SETTING_KEYS
    assert DEFAULTS["reminders_enabled"] is False
    assert DEFAULTS["reminder_minutes_before"] == 15
    assert "reminders_enabled" not in SYNCED_SETTING_KEYS
    assert "reminder_minutes_before" not in SYNCED_SETTING_KEYS
```

- [ ] **Step 2: Test rot verifizieren**

Run: `pytest tests/test_settings.py -k reminder -q`
Expected: FAIL (`ImportError: cannot import name 'parse_reminder_minutes'`).

- [ ] **Step 3: DEFAULTS ergänzen**

In `src/settings.py::DEFAULTS`, direkt nach der Zeile `"minimize_to_tray": False,` einfügen:

```python
    "reminders_enabled": False,
    "reminder_minutes_before": 15,
```

- [ ] **Step 4: Validator implementieren**

In `src/settings.py` direkt nach `parse_hourly_rate` (nach dessen `return 0.0`-Zeile) einfügen:

```python
def parse_reminder_minutes(raw):
    """Parst die 'Minuten vor Ende'-Eingabe zu int in [0, 120]. Ungültig
    (nicht-numerisch, negativ, > 120, Kommazahl) -> None. Der Dialog nutzt None
    als Fehlersignal (anders als parse_hourly_rate, das tolerant auf 0.0 fällt —
    hier ist eine bewusste Validierung gewünscht)."""
    try:
        value = int(str(raw).strip())
    except (ValueError, TypeError, AttributeError):
        return None
    if 0 <= value <= 120:
        return value
    return None
```

- [ ] **Step 5: Tests grün verifizieren**

Run: `pytest tests/test_settings.py -k reminder -q`
Expected: PASS (4 Tests).

- [ ] **Step 6: Volle Settings-Tests + Ruff**

Run: `pytest tests/test_settings.py -q`
Expected: PASS (bestehende + neue).
Run: `ruff check src/settings.py tests/test_settings.py`
Expected: All checks passed.

- [ ] **Step 7: Commit**

```bash
git add src/settings.py tests/test_settings.py
git commit -m "feat(settings): reminders_enabled/reminder_minutes_before + parse_reminder_minutes"
```

---

### Task 3: Scheduler (`src/reminder_scheduler.py`)

**Files:**
- Create: `src/reminder_scheduler.py`
- Test: `tests/test_reminder_scheduler.py`

**Interfaces:**
- Consumes: `src.reminders.due_reminders` (Task 1); `settings.get("reminder_minutes_before")`; `storage.get(date)`/`reservation_store.get(date)` → `{"slots":[...]}` oder `None`; `tray.notify(text)`.
- Produces: `ReminderScheduler(root, settings, storage, reservation_store, get_tray, now_provider=datetime.datetime.now)` mit Methoden `start()`, `stop()`, `poll(now_dt) -> list[Reminder]`.

**Design-Notiz:** `poll(now_dt)` enthält die gesamte testbare Logik (Stores lesen → `due_reminders` → `tray.notify` → markieren) und braucht KEIN Tk-Event-Loop. `start()`/`stop()` sind die dünne `root.after`-Hülle. Tests rufen `poll()` direkt mit Fakes.

- [ ] **Step 1: Failing test schreiben**

`tests/test_reminder_scheduler.py`:

```python
import datetime

from src.reminder_scheduler import ReminderScheduler


class _FakeTray:
    def __init__(self):
        self.messages = []

    def notify(self, message, title="Zeiterfassung"):
        self.messages.append(message)


class _FakeStore:
    def __init__(self, by_date):
        self._by_date = by_date

    def get(self, date_str):
        return self._by_date.get(date_str)


def _now(h, m):
    return datetime.datetime(2026, 7, 2, h, m)


def _make(reservation_by_date, entry_by_date, tray, minutes=15):
    settings = {"reminder_minutes_before": minutes}
    return ReminderScheduler(
        root=None,
        settings=type("S", (), {"get": staticmethod(lambda k: settings[k])})(),
        storage=_FakeStore(entry_by_date),
        reservation_store=_FakeStore(reservation_by_date),
        get_tray=lambda: tray,
    )


def test_poll_fires_upcoming_and_marks():
    tray = _FakeTray()
    sched = _make(
        {"2026-07-02": {"slots": [{"start": "09:00", "end": "17:00", "kategorie": "A"}]}},
        {},  # keine Ist-Zeit
        tray,
    )
    fired = sched.poll(_now(16, 50))
    assert len(fired) == 1 and fired[0].kind == "upcoming"
    assert len(tray.messages) == 1 and "A" in tray.messages[0]
    # zweiter Poll im selben Fenster -> kein erneuter Toast (already_fired).
    assert sched.poll(_now(16, 55)) == []
    assert len(tray.messages) == 1


def test_poll_no_tray_is_noop():
    sched = _make(
        {"2026-07-02": {"slots": [{"start": "09:00", "end": "17:00", "kategorie": "A"}]}},
        {}, tray=None,
    )
    sched._get_tray = lambda: None
    assert sched.poll(_now(16, 50)) == []


def test_poll_skips_when_category_logged():
    tray = _FakeTray()
    sched = _make(
        {"2026-07-02": {"slots": [{"start": "09:00", "end": "17:00", "kategorie": "A"}]}},
        {"2026-07-02": {"slots": [{"start": "09:00", "end": "12:00", "pause": 0, "kategorie": "A"}]}},
        tray,
    )
    assert sched.poll(_now(16, 50)) == []
    assert tray.messages == []


def test_poll_clears_fired_on_date_change():
    tray = _FakeTray()
    sched = _make(
        {"2026-07-02": {"slots": [{"start": "09:00", "end": "17:00", "kategorie": "A"}]}},
        {}, tray,
    )
    sched.poll(_now(16, 50))
    # Neuer Tag -> _fired wird geleert (keine Reservierung am 03. -> trotzdem kein Crash).
    other = datetime.datetime(2026, 7, 3, 8, 0)
    assert sched.poll(other) == []
    assert sched._fired_date == "2026-07-03"
```

- [ ] **Step 2: Test rot verifizieren**

Run: `pytest tests/test_reminder_scheduler.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.reminder_scheduler'`).

- [ ] **Step 3: `src/reminder_scheduler.py` implementieren**

```python
"""Periodischer Reservierungs-Erinnerungs-Check auf dem Tk-Thread.

Dünne Naht über die pure Logik in src/reminders.py: liest heutige
Reservierungen + Ist-Zeiten, ermittelt fällige Toasts (upcoming/missed) und
schickt sie über das Tray-Icon. Das Scheduling nutzt root.after; die eigentliche
Entscheidung liegt in reminders.due_reminders (Tk-frei, testbar). poll() enthält
die gesamte testbare Logik und braucht keinen Event-Loop.
"""
import datetime
import logging

from src import reminders

log = logging.getLogger(__name__)

_INITIAL_DELAY_MS = 2000   # erster Tick zeitnah — fängt 'App startet nach Ende'.
_INTERVAL_MS = 60_000      # danach minütlich.


class ReminderScheduler:
    def __init__(self, root, settings, storage, reservation_store, get_tray,
                 now_provider=datetime.datetime.now):
        self._root = root
        self._settings = settings
        self._storage = storage
        self._reservation_store = reservation_store
        self._get_tray = get_tray
        self._now = now_provider
        self._after_id = None
        self._fired = set()
        self._fired_date = None

    def start(self):
        """Plant den ersten Tick zeitnah + danach im Intervall. Idempotent."""
        if self._after_id is not None:
            return
        self._after_id = self._root.after(_INITIAL_DELAY_MS, self._tick)

    def stop(self):
        """Bricht den geplanten Tick ab. Idempotent."""
        if self._after_id is not None:
            try:
                self._root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _tick(self):
        try:
            self.poll(self._now())
        except Exception:
            log.exception("Reminder-Tick fehlgeschlagen")
        finally:
            self._after_id = self._root.after(_INTERVAL_MS, self._tick)

    def poll(self, now_dt):
        """Ein Durchlauf: fällige Reminder ermitteln, benachrichtigen, markieren.
        Gibt die gefeuerten Reminder zurück (für Tests). Ohne Tray: no-op."""
        tray = self._get_tray()
        if tray is None:
            return []
        today = now_dt.date().isoformat()
        if self._fired_date != today:
            self._fired.clear()
            self._fired_date = today
        reservation = self._reservation_store.get(today)
        reserved_slots = reservation.get("slots", []) if reservation else []
        entry = self._storage.get(today)
        logged = {
            (s.get("kategorie") or "").strip()
            for s in (entry.get("slots", []) if entry else [])
            if (s.get("kategorie") or "").strip()
        }
        minutes = self._settings.get("reminder_minutes_before")
        due = reminders.due_reminders(
            reserved_slots, logged, now_dt, minutes, self._fired)
        for rem in due:
            tray.notify(_toast_text(rem))
            self._fired.add(rem.key)
        return due


def _toast_text(rem):
    """Deutscher Toast-Text je Typ."""
    if rem.kind == "missed":
        return f"'{rem.kategorie}' (bis {rem.end}) heute ohne erfasste Arbeitszeit."
    return (f"Reservierung '{rem.kategorie}' endet um {rem.end} — "
            "Arbeitszeit noch nicht eingetragen.")
```

- [ ] **Step 4: Tests grün verifizieren**

Run: `pytest tests/test_reminder_scheduler.py -q`
Expected: PASS (4 Tests).

- [ ] **Step 5: Ruff**

Run: `ruff check src/reminder_scheduler.py tests/test_reminder_scheduler.py`
Expected: All checks passed.

- [ ] **Step 6: Commit**

```bash
git add src/reminder_scheduler.py tests/test_reminder_scheduler.py
git commit -m "feat(reminders): ReminderScheduler — periodischer Poll + Toast-Dispatch"
```

---

### Task 4: Settings-Dialog UI (App-Tab)

**Files:**
- Modify: `src/dialogs/settings_dialog.py` (Import; Benachrichtigungs-Block im App-Tab; `save_settings`: Validierung + `updates`)

**Interfaces:**
- Consumes: `parse_reminder_minutes` (Task 2); Settings-Keys `reminders_enabled`/`reminder_minutes_before`.
- Der App-Tab-Frame ist `app_frame` (pack-Container), das Tab-Mapping ist `tabs["app"]`, der Fehler-Sprung erfolgt via `notebook.select(tabs["app"])` (bestehendes Muster).

- [ ] **Step 1: Import ergänzen**

In `src/dialogs/settings_dialog.py` die bestehende Zeile
```python
from src.settings import WEEKDAY_KEYS, clamp_ui_scale, parse_hourly_rate, resolve_calendar_id
```
ersetzen durch:
```python
from src.settings import (
    WEEKDAY_KEYS, clamp_ui_scale, parse_hourly_rate,
    parse_reminder_minutes, resolve_calendar_id,
)
```

- [ ] **Step 2: Benachrichtigungs-Block in den App-Tab einfügen**

In `src/dialogs/settings_dialog.py` direkt NACH dem „Darstellung"-Block — also nach dem Label
```python
    tk.Label(
        app_frame, text="Änderung startet die App neu.", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).pack(anchor="w", pady=(2, 0))
```
folgenden Block einfügen (vor `# ===================== Speichern / Buttons =====================`):

```python
    # --- Benachrichtigungen (Reservierungs-Erinnerungen, gerätelokal) ---
    tk.Label(
        app_frame, text="— Benachrichtigungen —", font=FONT_BOLD,
        bg=BG, fg=TEXT_MUTED,
    ).pack(pady=(12, 4))

    reminders_enabled_var = tk.BooleanVar(value=settings.get("reminders_enabled"))
    tk.Checkbutton(
        app_frame, text="Erinnerungen als Toast anzeigen",
        variable=reminders_enabled_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT, cursor="hand2",
    ).pack(anchor="w")

    reminder_row = tk.Frame(app_frame, bg=BG)
    reminder_row.pack(anchor="w", pady=(4, 0))
    tk.Label(
        reminder_row, text="Erinnerung Minuten vor Ende der Reservierung:",
        font=FONT, bg=BG, fg=TEXT,
    ).pack(side=tk.LEFT, padx=(0, 8))
    reminder_minutes_var = tk.StringVar(
        value=str(settings.get("reminder_minutes_before")))
    dark_combo(
        reminder_row, reminder_minutes_var,
        [str(m) for m in range(0, 121, 5)], width=4,
    ).pack(side=tk.LEFT)
    tk.Label(
        app_frame, text="Nur für Reservierungen mit Kategorie.", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).pack(anchor="w", pady=(2, 0))
```

- [ ] **Step 3: Validierung in `save_settings` ergänzen**

In `save_settings`, direkt VOR der Zeile `hourly_rate = parse_hourly_rate(rate_var.get())` einfügen:

```python
        reminder_minutes = parse_reminder_minutes(reminder_minutes_var.get())
        if reminder_minutes is None:
            notebook.select(tabs["app"])
            themed_showerror(
                dialog, "Erinnerungszeit ungültig",
                "Bitte eine ganze Zahl zwischen 0 und 120 Minuten angeben.",
            )
            return
```

- [ ] **Step 4: Keys ins `updates`-Dict aufnehmen**

Im `updates`-Dict in `save_settings` nach der Zeile `"minimize_to_tray": minimize_to_tray_var.get(),` einfügen:

```python
            "reminders_enabled": reminders_enabled_var.get(),
            "reminder_minutes_before": reminder_minutes,
```

- [ ] **Step 5: Bestehende Tests + Ruff**

Run: `pytest -q`
Expected: PASS (kein Test instanziiert den Dialog; Settings-Tests grün).
Run: `ruff check src/dialogs/settings_dialog.py`
Expected: All checks passed (kein ungenutzter Import — `parse_reminder_minutes` wird genutzt).

- [ ] **Step 6: Screenshot-Verifikation (App-Tab)**

Scratchpad-Skript `verify_notifications_tab.py` schreiben und ausführen (rendert den Dialog, wählt den App-Tab, screenshottet):

```python
import os, tempfile, tkinter as tk
from PIL import ImageGrab
from src.settings import Settings
from src.theme import init_fonts
from src.dialogs.settings_dialog import open_settings_dialog

OUT = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp()
st = Settings(os.path.join(tmp, "settings.json"))
root = tk.Tk(); root.withdraw()
init_fonts(root, st.get("ui_scale"))
open_settings_dialog(root, st, tmp, lambda: None)
dialog = root.winfo_children()[0]
nb = [w for w in dialog.winfo_children() if w.winfo_class() == "TNotebook"][0]

def do():
    nb.select(3)  # App-Tab
    dialog.geometry("+0+0"); dialog.attributes("-topmost", True); dialog.lift()
    dialog.update_idletasks(); dialog.update()
    x, y = dialog.winfo_rootx(), dialog.winfo_rooty()
    w, h = dialog.winfo_width(), dialog.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(os.path.join(OUT, "notif_tab.png"))
    print(f"saved {w}x{h}")
    root.destroy()

root.after(500, do)
root.mainloop()
```

Run: `python verify_notifications_tab.py`
Expected: PNG mit dem App-Tab. Prüfen (Read-Tool): Block „— Benachrichtigungen —" mit Checkbox, Minuten-Combo (0–120) und Hinweis „Nur für Reservierungen mit Kategorie." sichtbar; Tab passt weiterhin (keine Beschneidung der Buttons).

- [ ] **Step 7: Commit**

```bash
git add src/dialogs/settings_dialog.py
git commit -m "feat(settings-ui): Benachrichtigungs-Block im App-Tab (Checkbox + Minuten + Hinweis)"
```

---

### Task 5: App-Verdrahtung (`src/ui.py`)

**Files:**
- Modify: `src/ui.py` (Import; Scheduler-Konstruktion; `_apply_tray_setting` entkoppeln; `_apply_reminder_setting`; `__init__`/`_on_change`-Aufrufe; Quit-Pfade)

**Interfaces:**
- Consumes: `ReminderScheduler` (Task 3); Settings-Keys (Task 2).

- [ ] **Step 1: Import ergänzen**

In `src/ui.py` bei den Komponenten-Imports (dort, wo `GridRenderer`/`SyncOrchestrator`/`BackgroundTaskRunner`/`UpdateBanner` importiert werden) ergänzen:
```python
from src.reminder_scheduler import ReminderScheduler
```
(Falls diese als Sammelimport `from src.xyz import ...` stehen, eine analoge eigene Zeile hinzufügen — Modul-Ebene, kein Google/Tk-Sonderfall.)

- [ ] **Step 2: Scheduler konstruieren**

In `App.__init__`, direkt nach dem `GridRenderer`-Block (nach `self._renderer = GridRenderer(...)`, vor `self._build_header()`) einfügen:

```python
        self._reminders = ReminderScheduler(
            self.root, self.settings, self.storage,
            self.reservation_store, lambda: self._tray,
        )
```

- [ ] **Step 3: `_apply_tray_setting` entkoppeln**

In `src/ui.py::_apply_tray_setting` die Zeile
```python
        want_tray = bool(self.settings.get("minimize_to_tray"))
```
ersetzen durch:
```python
        # Tray dient zweierlei: Minimize-to-Tray UND als Toast-Kanal für
        # Reservierungs-Erinnerungen. Es läuft, sobald EINES aktiv ist.
        want_tray = (bool(self.settings.get("minimize_to_tray"))
                     or bool(self.settings.get("reminders_enabled")))
```

Und die beiden Fallback-Pfade, die bisher nur `minimize_to_tray` zurücksetzen, um `reminders_enabled` ergänzen. Konkret die Stelle
```python
            if not is_supported():
                themed_showinfo(
                    self.root,
                    "Infobereich-Icon",
                    "Das Minimieren in den Infobereich ist auf dieser Plattform "
                    "nicht zuverlässig nutzbar (typisch Linux). Option wurde "
                    "wieder deaktiviert.",
                )
                self.settings.set("minimize_to_tray", False)
                return
```
ersetzen durch:
```python
            if not is_supported():
                themed_showinfo(
                    self.root,
                    "Infobereich-Icon / Benachrichtigungen",
                    "Infobereich-Icon und Toast-Benachrichtigungen sind auf "
                    "dieser Plattform nicht zuverlässig nutzbar (typisch Linux). "
                    "Die Optionen wurden wieder deaktiviert.",
                )
                self.settings.set("minimize_to_tray", False)
                self.settings.set("reminders_enabled", False)
                return
```
und den Except-Fallback
```python
            except Exception as e:
                logging.getLogger(__name__).exception("Tray-Start fehlgeschlagen")
                themed_showerror(
                    self.root,
                    "Infobereich-Icon",
                    f"Tray-Icon konnte nicht gestartet werden:\n\n{e}",
                )
                self.settings.set("minimize_to_tray", False)
                return
```
ersetzen durch:
```python
            except Exception as e:
                logging.getLogger(__name__).exception("Tray-Start fehlgeschlagen")
                themed_showerror(
                    self.root,
                    "Infobereich-Icon",
                    f"Tray-Icon konnte nicht gestartet werden:\n\n{e}",
                )
                self.settings.set("minimize_to_tray", False)
                self.settings.set("reminders_enabled", False)
                return
```

- [ ] **Step 4: `_apply_reminder_setting` hinzufügen**

In `src/ui.py` direkt nach der `_apply_tray_setting`-Methode (nach deren `elif not want_tray ...`-Block) einfügen:

```python
    def _apply_reminder_setting(self):
        """Startet/stoppt den Reminder-Poll abhängig vom Setting. Braucht ein
        laufendes Tray-Icon als Toast-Kanal — ohne Tray wird gestoppt."""
        want = bool(self.settings.get("reminders_enabled")) and self._tray is not None
        if want:
            self._reminders.start()
        else:
            self._reminders.stop()
```

- [ ] **Step 5: Aufrufe in `__init__` und `_on_change` ergänzen**

In `App.__init__` direkt nach `self._apply_tray_setting()` einfügen:
```python
        self._apply_reminder_setting()
```

In der `_on_change`-Closure in `_open_settings` direkt nach dem dortigen `self._apply_tray_setting()` einfügen:
```python
            self._apply_reminder_setting()
```

- [ ] **Step 6: Scheduler in den Quit-Pfaden stoppen**

In `_quit_with_sync_push` direkt vor `self.root.destroy()` einfügen:
```python
        self._reminders.stop()
```
In `restart_for_scaling` im Erfolgspfad direkt vor `self.root.destroy()` (nach dem `if self._tray is not None: self._tray.stop()`) einfügen:
```python
        self._reminders.stop()
```

- [ ] **Step 7: Import-Smoke + Suite + Ruff**

Run: `python -c "import src.ui"`
Expected: kein Fehler.
Run: `pytest -q`
Expected: PASS (bestehende Suite unverändert grün).
Run: `ruff check src/ui.py`
Expected: All checks passed.

- [ ] **Step 8: Manuelle Verifikation (Windows, lokal)**

Kurzskript-frei per echter App:
1. `python -m src.main` starten.
2. Einstellungen → App-Tab → „Erinnerungen als Toast anzeigen" AN, Minuten z.B. 15, speichern. (Tray-Icon erscheint, auch ohne Minimize-to-Tray.)
3. Für heute eine Reservierung mit Kategorie anlegen (Google-Kalender-Sync aktiv), deren Ende in < 15 Min liegt, ohne Ist-Zeit derselben Kategorie.
4. Innerhalb ~1 Min erscheint ein `upcoming`-Toast. Trägt man die Ist-Zeit (gleiche Kategorie) ein, kommt kein weiterer.
5. Für den `missed`-Pfad: App schließen, eine Reservierung anlegen, deren Ende in der Vergangenheit liegt (bzw. warten), App neu starten → `missed`-Toast beim ersten Tick.

Ergebnis im Report festhalten (welche Toasts erschienen). Kein CI-Test (Display/Tray nötig).

- [ ] **Step 9: Commit**

```bash
git add src/ui.py
git commit -m "feat(ui): Tray vom Minimize entkoppeln + ReminderScheduler verdrahten"
```

---

### Task 6: Doku nachziehen

**Files:**
- Modify: `src/CLAUDE.md` (neue Module + Tray-Entkopplung)
- Modify: `CLAUDE.md` (Repo-Root, Modul-Liste)

**Interfaces:** keine.

- [ ] **Step 1: `src/CLAUDE.md` ergänzen**

Im Abschnitt „## Daten- & Persistenz-Schicht" nach dem `weekly_limit.py`-Satz einen Satz ergänzen:

> `reminders.py` — pure Fälligkeits-Logik für Reservierungs-Erinnerungen (Tk-frei, `now` als Parameter): pro heutigem reservierten Slot mit Kategorie ohne erfasste Ist-Zeit `upcoming` (N Min vor Ende) oder `missed` (nach Ende). Der `ReminderScheduler` (`reminder_scheduler.py`) pollt minütlich über `root.after` und schickt Toasts über `App._tray`.

Im Abschnitt „### … Tray"/Infra-Teil (bei der `tray.py`-Nennung in „## Berichte & Plattform/Infra") ergänzen:

> Das Tray-Icon läuft, sobald `minimize_to_tray` **oder** `reminders_enabled` aktiv ist (`ui.py::_apply_tray_setting`); bei nur `reminders_enabled` dient es ausschließlich als Toast-Kanal.

- [ ] **Step 2: Root-`CLAUDE.md` Modul-Liste ergänzen**

In `CLAUDE.md` (Repo-Root) im Abschnitt „## Struktur" nach dem `src/reservations_sync.py`-Eintrag zwei Einträge ergänzen:

```
- `src/reminders.py` — pure Fälligkeits-Logik für Reservierungs-Erinnerungen (Tk-frei)
- `src/reminder_scheduler.py` — periodischer Reminder-Poll (root.after) → Toast über Tray
```

- [ ] **Step 3: Commit**

```bash
git add src/CLAUDE.md CLAUDE.md
git commit -m "docs: Reservierungs-Erinnerungen (reminders + scheduler + Tray-Entkopplung)"
```

---

## Self-Review (durch den Plan-Autor bereits durchlaufen)

- **Spec-Abdeckung:** Match-Regel + Typen + N-Fenster (Task 1); Settings-Keys device-local + Validator (Task 2); Scheduler/Poll/Toast-Texte + already_fired/Datumswechsel + no-tray-Guard (Task 3); UI-Block + Validierung + Hinweis (Task 4); Tray-Entkopplung + Fallback-Reset beider Keys + Scheduler-Lifecycle + Quit (Task 5); Doku (Task 6). Plattform-Gate erbt Task 5 vom bestehenden `is_supported()`.
- **Platzhalter:** keine — vollständiger Code je Schritt.
- **Typ-/Namenskonsistenz:** `due_reminders(reserved_slots, logged_categories, now_dt, minutes_before, already_fired)` und `Reminder(key, kind, kategorie, end)` identisch in Task 1 (Def), Task 3 (Aufruf) und den Tests. `parse_reminder_minutes` identisch Task 2/4. `ReminderScheduler(root, settings, storage, reservation_store, get_tray, now_provider=…)` identisch Task 3/5. Settings-Keys `reminders_enabled`/`reminder_minutes_before` durchgängig.
- **Pre-Release-Hinweis:** Beim PR (stacked auf #112) vorschlagen — Tray/Notify auf macOS/Linux nicht Windows-verifizierbar; macOS bleibt hinter `ZEIT_MACOS_TRAY` dormant.
