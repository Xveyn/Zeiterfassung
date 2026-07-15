# Monatlicher Sende-Reminder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine optionale, monatliche Toast-Erinnerung „Arbeitszeiten verschicken" hinzufügen, die an einem konfigurierbaren Tag im Monat + Uhrzeit feuert, dabei kürzere Monate (28/29/30 Tage) korrekt auf den letzten Tag clamped, und nach verpasstem Zeitpunkt (App war zu) beim nächsten Start nachholt.

**Architecture:** Exakt derselbe Zwei-Schichten-Schnitt wie der bestehende Reservierungs-Reminder: eine reine, Tk-freie Fälligkeitslogik (`src/send_reminder.py`) + eine dünne `root.after`-Poll-Naht (`src/send_reminder_scheduler.py`), die über den bestehenden `TrayIcon.notify()`-Kanal benachrichtigt. Settings-Erweiterung (4 neue gerätelokale Keys) + neuer Block im App-Settings-Tab + Verdrahtung in `ui.py::App` nach demselben Muster wie `reminders_enabled`/`ReminderScheduler`.

**Tech Stack:** Python 3.10, Tkinter, pytest. Keine neuen Abhängigkeiten (`calendar` ist Stdlib).

## Global Constraints

- Fired-Zustand wird **persistiert** (nicht nur im Speicher wie beim Reservierungs-Reminder) — neues Settings-Feld `send_reminder_last_fired_month` (ISO `"YYYY-MM"`), gerätelokal.
- Tag im Monat (1–31) wird auf die tatsächliche Monatslänge **geclamped** (`calendar.monthrange`), kein separater „letzter Tag"-Spezialwert.
- Alle vier neuen Settings-Keys sind gerätelokal — **nicht** in `SYNCED_SETTING_KEYS`.
- Eigenständiger Toggle (`send_reminder_enabled`), **nicht** an `reminders_enabled` gekoppelt.
- Datumskonvention: intern ISO (`send_reminder_last_fired_month` als `"YYYY-MM"`, nie in der UI angezeigt); UI zeigt nur die Tageszahl (1–31) + Uhrzeit-Dropdown; der Toast-Text zeigt den Monat als deutschen Namen (`MONTHS_DE`) — nirgends ein rohes `isoformat()`/`str()`-Datum in der UI.
- Catch-up nach App-Start: erster Poll-Tick zeitnah (`_INITIAL_DELAY_MS = 2000`, identisch zu `ReminderScheduler`) — ist der Fällig-Zeitpunkt bereits verstrichen, feuert der Toast beim ersten Tick.
- Plattform-Gate identisch zum bestehenden `tray.is_supported()` (Windows voll, macOS hinter `ZEIT_MACOS_TRAY=1` dormant, Linux kein Tray) — keine Erweiterung in diesem Plan.
- Toast ist rein informativ, kein Klick-Handler.

---

## Task 1: Pure Fälligkeitslogik (`src/send_reminder.py`)

**Files:**
- Create: `src/send_reminder.py`
- Test: `tests/test_send_reminder.py`

**Interfaces:**
- Produces:
  - `scheduled_datetime(year: int, month: int, day: int, time_str: str) -> datetime.datetime | None`
  - `is_due(now_dt: datetime.datetime, day: int, time_str: str, last_fired_month: str) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_send_reminder.py`:

```python
import datetime

from src.send_reminder import is_due, scheduled_datetime


def test_scheduled_datetime_clamps_day_31_in_february():
    assert scheduled_datetime(2026, 2, 31, "18:00") == datetime.datetime(2026, 2, 28, 18, 0)


def test_scheduled_datetime_clamps_day_31_in_april():
    assert scheduled_datetime(2026, 4, 31, "18:00") == datetime.datetime(2026, 4, 30, 18, 0)


def test_scheduled_datetime_no_clamp_needed():
    assert scheduled_datetime(2026, 7, 15, "09:30") == datetime.datetime(2026, 7, 15, 9, 30)


def test_scheduled_datetime_invalid_time_returns_none():
    assert scheduled_datetime(2026, 7, 15, "kaputt") is None
    assert scheduled_datetime(2026, 7, 15, None) is None


def test_is_due_before_scheduled_time():
    now = datetime.datetime(2026, 7, 15, 17, 59)
    assert is_due(now, 15, "18:00", "") is False


def test_is_due_at_scheduled_time():
    now = datetime.datetime(2026, 7, 15, 18, 0)
    assert is_due(now, 15, "18:00", "") is True


def test_is_due_already_fired_this_month():
    now = datetime.datetime(2026, 7, 15, 18, 5)
    assert is_due(now, 15, "18:00", "2026-07") is False


def test_is_due_catch_up_after_missed_moment():
    # App war den ganzen Monat zu, wird erst nach dem Fällig-Zeitpunkt gestartet.
    now = datetime.datetime(2026, 7, 20, 9, 0)
    assert is_due(now, 15, "18:00", "2026-06") is True


def test_is_due_fired_in_previous_month_new_month_not_yet_due():
    now = datetime.datetime(2026, 7, 10, 8, 0)
    assert is_due(now, 15, "18:00", "2026-06") is False


def test_is_due_invalid_time_never_due():
    now = datetime.datetime(2026, 7, 20, 9, 0)
    assert is_due(now, 15, "kaputt", "") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_send_reminder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.send_reminder'`

- [ ] **Step 3: Write the implementation**

Create `src/send_reminder.py`:

```python
"""Pure Fälligkeits-Logik für den monatlichen Sende-Reminder (Tk-frei).

Ermittelt, ob am `now_dt` der konfigurierte Tag/Uhrzeit für die Erinnerung
"Arbeitszeiten verschicken" erreicht oder überschritten ist und für den
aktuellen Monat noch nicht gefeuert wurde. Tage jenseits der Monatslänge
(z.B. 31 im Februar) clampen auf den letzten Tag des Monats.
"""
import calendar
import datetime


def scheduled_datetime(year, month, day, time_str):
    """Fällig-Zeitpunkt für (year, month); `day` wird auf die tatsächliche
    Monatslänge geclamped (Tag 31 im Februar -> 28./29., im April -> 30.).
    `time_str` ungültig/kein 'HH:MM' -> None."""
    hh_mm = _parse_hhmm(time_str)
    if hh_mm is None:
        return None
    last_day = calendar.monthrange(year, month)[1]
    actual_day = min(max(day, 1), last_day)
    hh, mm = hh_mm
    return datetime.datetime(year, month, actual_day, hh, mm)


def _parse_hhmm(value):
    if not isinstance(value, str):
        return None
    try:
        hh, mm = value.split(":")
        return int(hh), int(mm)
    except (ValueError, TypeError):
        return None


def is_due(now_dt, day, time_str, last_fired_month):
    """True, wenn `now_dt` den Fällig-Zeitpunkt des aktuellen Monats erreicht
    hat und dieser Monat (`'YYYY-MM'`) noch nicht in `last_fired_month`
    steht."""
    current_month = f"{now_dt.year:04d}-{now_dt.month:02d}"
    if last_fired_month == current_month:
        return False
    due_at = scheduled_datetime(now_dt.year, now_dt.month, day, time_str)
    if due_at is None:
        return False
    return now_dt >= due_at
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_send_reminder.py -v`
Expected: PASS — 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/send_reminder.py tests/test_send_reminder.py
git commit -m "$(cat <<'EOF'
feat(send-reminder): pure Fälligkeitslogik für monatlichen Sende-Reminder

Clamped den konfigurierten Tag im Monat auf die tatsächliche Monatslänge
(Feb 28/29, 30-Tage-Monate) und erkennt verpasste Zeitpunkte für den
Catch-up nach App-Start.
EOF
)"
```

---

## Task 2: Poll-Scheduler (`src/send_reminder_scheduler.py`)

**Files:**
- Create: `src/send_reminder_scheduler.py`
- Test: `tests/test_send_reminder_scheduler.py`

**Interfaces:**
- Consumes: `src.send_reminder.is_due(now_dt, day, time_str, last_fired_month) -> bool` (Task 1); `src.time_utils.MONTHS_DE` (1-indexiert, `MONTHS_DE[7] == "Juli"`).
- Produces: `SendReminderScheduler(root, settings, get_tray, now_provider=datetime.datetime.now)` mit `.start()`, `.stop()`, `.poll(now_dt) -> bool` (True, wenn benachrichtigt wurde).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_send_reminder_scheduler.py`:

```python
import datetime

from src.send_reminder_scheduler import SendReminderScheduler


class _FakeTray:
    def __init__(self):
        self.messages = []

    def notify(self, message, title="Zeiterfassung"):
        self.messages.append(message)


class _FakeSettings:
    def __init__(self, data):
        self._data = data

    def get(self, key):
        return self._data[key]

    def set(self, key, value):
        self._data[key] = value


def _now(day, h, m):
    return datetime.datetime(2026, 7, day, h, m)


def _make(settings_data, tray):
    return SendReminderScheduler(
        root=None,
        settings=_FakeSettings(settings_data),
        get_tray=lambda: tray,
    )


def test_poll_fires_when_due_and_persists_month():
    tray = _FakeTray()
    settings_data = {
        "send_reminder_day": 15, "send_reminder_time": "18:00",
        "send_reminder_last_fired_month": "",
    }
    sched = _make(settings_data, tray)
    assert sched.poll(_now(15, 18, 0)) is True
    assert len(tray.messages) == 1 and "Juli" in tray.messages[0]
    assert settings_data["send_reminder_last_fired_month"] == "2026-07"


def test_poll_second_call_same_month_no_repeat():
    tray = _FakeTray()
    settings_data = {
        "send_reminder_day": 15, "send_reminder_time": "18:00",
        "send_reminder_last_fired_month": "",
    }
    sched = _make(settings_data, tray)
    sched.poll(_now(15, 18, 0))
    assert sched.poll(_now(15, 18, 5)) is False
    assert len(tray.messages) == 1


def test_poll_before_due_time_no_notify():
    tray = _FakeTray()
    settings_data = {
        "send_reminder_day": 15, "send_reminder_time": "18:00",
        "send_reminder_last_fired_month": "",
    }
    sched = _make(settings_data, tray)
    assert sched.poll(_now(15, 17, 59)) is False
    assert tray.messages == []


def test_poll_no_tray_is_noop():
    settings_data = {
        "send_reminder_day": 15, "send_reminder_time": "18:00",
        "send_reminder_last_fired_month": "",
    }
    sched = _make(settings_data, tray=None)
    assert sched.poll(_now(15, 18, 0)) is False


def test_poll_catch_up_after_missed_moment():
    tray = _FakeTray()
    settings_data = {
        "send_reminder_day": 15, "send_reminder_time": "18:00",
        "send_reminder_last_fired_month": "2026-06",
    }
    sched = _make(settings_data, tray)
    # App startet erst am 20., lange nach dem Fällig-Zeitpunkt.
    assert sched.poll(_now(20, 9, 0)) is True
    assert settings_data["send_reminder_last_fired_month"] == "2026-07"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_send_reminder_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.send_reminder_scheduler'`

- [ ] **Step 3: Write the implementation**

Create `src/send_reminder_scheduler.py`:

```python
"""Periodischer Sende-Reminder-Check auf dem Tk-Thread.

Dünne Naht über die pure Logik in src/send_reminder.py: prüft minütlich, ob
der konfigurierte Tag/Uhrzeit für "Arbeitszeiten verschicken" erreicht ist,
und schickt ggf. einen Toast über das Tray-Icon. Der zuletzt benachrichtigte
Monat wird in settings persistiert (send_reminder_last_fired_month), damit
der Toast über App-Neustarts hinweg nur einmal pro Monat erscheint.
"""
import datetime
import logging

from src import send_reminder
from src.time_utils import MONTHS_DE

log = logging.getLogger(__name__)

_INITIAL_DELAY_MS = 2000   # erster Tick zeitnah — fängt 'App startet nach Fällig-Zeitpunkt'.
_INTERVAL_MS = 60_000      # danach minütlich.


class SendReminderScheduler:
    def __init__(self, root, settings, get_tray, now_provider=datetime.datetime.now):
        self._root = root
        self._settings = settings
        self._get_tray = get_tray
        self._now = now_provider
        self._after_id = None

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
            log.exception("Sende-Reminder-Tick fehlgeschlagen")
        finally:
            self._after_id = self._root.after(_INTERVAL_MS, self._tick)

    def poll(self, now_dt):
        """Ein Durchlauf: Fälligkeit prüfen, ggf. benachrichtigen und den
        Monat persistieren. Gibt True zurück, wenn benachrichtigt wurde (für
        Tests). Ohne Tray: no-op."""
        tray = self._get_tray()
        if tray is None:
            return False
        day = self._settings.get("send_reminder_day")
        time_str = self._settings.get("send_reminder_time")
        last_fired = self._settings.get("send_reminder_last_fired_month")
        if not send_reminder.is_due(now_dt, day, time_str, last_fired):
            return False
        tray.notify(_toast_text(now_dt))
        self._settings.set(
            "send_reminder_last_fired_month",
            f"{now_dt.year:04d}-{now_dt.month:02d}",
        )
        return True


def _toast_text(now_dt):
    """Deutscher Toast-Text mit dem aktuellen Monat."""
    return f"Zeit, deine Arbeitszeiten für {MONTHS_DE[now_dt.month]} zu verschicken."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_send_reminder_scheduler.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/send_reminder_scheduler.py tests/test_send_reminder_scheduler.py
git commit -m "$(cat <<'EOF'
feat(send-reminder): Poll-Scheduler für monatlichen Sende-Reminder

Dünne root.after-Naht über send_reminder.is_due, analog zu
ReminderScheduler. Persistiert den zuletzt benachrichtigten Monat in
settings statt nur im Speicher.
EOF
)"
```

---

## Task 3: Settings-Defaults (`src/settings.py`)

**Files:**
- Modify: `src/settings.py:51-56`
- Test: `tests/test_settings.py:748-753` (Einfügepunkt, danach)

**Interfaces:**
- Produces: `DEFAULTS["send_reminder_enabled"] == False`, `DEFAULTS["send_reminder_day"] == 1`, `DEFAULTS["send_reminder_time"] == "18:00"`, `DEFAULTS["send_reminder_last_fired_month"] == ""`. Keine der vier Keys in `SYNCED_SETTING_KEYS`.

- [ ] **Step 1: Write the failing test**

In `tests/test_settings.py`, direkt nach `test_reminder_defaults_present_and_device_local` (endet bei Zeile 753) einfügen:

```python
def test_send_reminder_defaults_present_and_device_local():
    from src.settings import DEFAULTS, SYNCED_SETTING_KEYS
    assert DEFAULTS["send_reminder_enabled"] is False
    assert DEFAULTS["send_reminder_day"] == 1
    assert DEFAULTS["send_reminder_time"] == "18:00"
    assert DEFAULTS["send_reminder_last_fired_month"] == ""
    assert "send_reminder_enabled" not in SYNCED_SETTING_KEYS
    assert "send_reminder_day" not in SYNCED_SETTING_KEYS
    assert "send_reminder_time" not in SYNCED_SETTING_KEYS
    assert "send_reminder_last_fired_month" not in SYNCED_SETTING_KEYS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_settings.py::test_send_reminder_defaults_present_and_device_local -v`
Expected: FAIL — `KeyError: 'send_reminder_enabled'`

- [ ] **Step 3: Add the defaults**

In `src/settings.py`, Zeile 54-55 sind aktuell:

```python
    "reminders_enabled": False,
    "reminder_minutes_before": 15,
```

Direkt danach einfügen (vor `"sender_email": "",`):

```python
    "reminders_enabled": False,
    "reminder_minutes_before": 15,
    "send_reminder_enabled": False,
    "send_reminder_day": 1,
    "send_reminder_time": "18:00",
    "send_reminder_last_fired_month": "",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_settings.py::test_send_reminder_defaults_present_and_device_local -v`
Expected: PASS — 1 passed

Run: `pytest tests/test_settings.py -v`
Expected: alle Tests weiterhin PASS (kein bestehender Test iteriert blind über alle `DEFAULTS`-Keys)

- [ ] **Step 5: Commit**

```bash
git add src/settings.py tests/test_settings.py
git commit -m "$(cat <<'EOF'
feat(send-reminder): Settings-Defaults für monatlichen Sende-Reminder

Vier neue gerätelokale Keys (enabled/day/time/last_fired_month), analog
zu reminders_enabled/reminder_minutes_before.
EOF
)"
```

---

## Task 4: Settings-Dialog UI (App-Tab + Save-Wiring)

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_app.py:9-12` (Import), `:126-165` (UI-Block + exponierte Vars)
- Modify: `src/dialogs/settings_dialog/dialog.py:161-162` (updates-Dict)

**Interfaces:**
- Consumes: `settings.get("send_reminder_enabled"/"send_reminder_day"/"send_reminder_time")` (Task 3); `TIME_VALUES`/`dark_combo` aus `src.theme`.
- Produces: `AppTab` exponiert zusätzlich `.send_reminder_enabled_var` (`tk.BooleanVar`), `.send_reminder_day_var` (`tk.StringVar`, Werte `"1"`–`"31"`), `.send_reminder_time_var` (`tk.StringVar`, Werte aus `TIME_VALUES`). `dialog.py::save_settings` schreibt `send_reminder_enabled`/`send_reminder_day`/`send_reminder_time` ins `updates`-Dict.

Kein automatisierter Test (Tk-Widget-Aufbau, wie der Rest von `tab_app.py`/`dialog.py` — Projekt-Konvention: „Scheduler/Tray/Dialog: Tk-/Display-abhängig → kein CI-Test"). Verifikation über Import-Check + `ruff` + manuellen Settings-Dialog-Test in Task 6.

- [ ] **Step 1: Import `TIME_VALUES` in `tab_app.py`**

`src/dialogs/settings_dialog/tab_app.py:9-12` ist aktuell:

```python
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL, TEXT, TEXT_MUTED,
    dark_combo,
)
```

Ändern zu:

```python
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL, TEXT, TEXT_MUTED,
    TIME_VALUES, dark_combo,
)
```

- [ ] **Step 2: Neuen UI-Block in `tab_app.py` einfügen**

`src/dialogs/settings_dialog/tab_app.py:152-156` ist aktuell:

```python
        tk.Label(
            app_frame, text="Nur für Reservierungen mit Kategorie.", font=FONT_SMALL,
            bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

        self.frame = frame
```

Ändern zu (neuer Block zwischen dem bestehenden Reservierungs-Reminder-Hinweis und `self.frame = frame`):

```python
        tk.Label(
            app_frame, text="Nur für Reservierungen mit Kategorie.", font=FONT_SMALL,
            bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

        send_reminder_enabled_var = tk.BooleanVar(value=settings.get("send_reminder_enabled"))
        tk.Checkbutton(
            app_frame, text="Erinnerung zum Verschicken der Arbeitszeiten",
            variable=send_reminder_enabled_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).pack(anchor="w", pady=(8, 0))

        send_reminder_row = tk.Frame(app_frame, bg=BG)
        send_reminder_row.pack(anchor="w", pady=(4, 0))
        tk.Label(
            send_reminder_row, text="Tag im Monat:",
            font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT, padx=(0, 8))
        send_reminder_day_var = tk.StringVar(
            value=str(settings.get("send_reminder_day")))
        dark_combo(
            send_reminder_row, send_reminder_day_var,
            [str(d) for d in range(1, 32)], width=4,
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(
            send_reminder_row, text="um", font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT, padx=(0, 8))
        send_reminder_time_var = tk.StringVar(value=settings.get("send_reminder_time"))
        dark_combo(
            send_reminder_row, send_reminder_time_var, TIME_VALUES, width=6,
        ).pack(side=tk.LEFT)
        tk.Label(
            app_frame, text="Bei kürzeren Monaten wird auf den letzten Tag verschoben.",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

        self.frame = frame
```

- [ ] **Step 3: Neue Vars exponieren**

`src/dialogs/settings_dialog/tab_app.py:163-165` (Ende von `__init__`) ist aktuell:

```python
        self.reminders_enabled_var = reminders_enabled_var
        self.reminder_minutes_var = reminder_minutes_var
```

Ändern zu:

```python
        self.reminders_enabled_var = reminders_enabled_var
        self.reminder_minutes_var = reminder_minutes_var
        self.send_reminder_enabled_var = send_reminder_enabled_var
        self.send_reminder_day_var = send_reminder_day_var
        self.send_reminder_time_var = send_reminder_time_var
```

- [ ] **Step 4: `save_settings` in `dialog.py` erweitern**

`src/dialogs/settings_dialog/dialog.py:161-162` ist aktuell:

```python
            "reminders_enabled": app.reminders_enabled_var.get(),
            "reminder_minutes_before": reminder_minutes,
```

Ändern zu:

```python
            "reminders_enabled": app.reminders_enabled_var.get(),
            "reminder_minutes_before": reminder_minutes,
            "send_reminder_enabled": app.send_reminder_enabled_var.get(),
            "send_reminder_day": int(app.send_reminder_day_var.get()),
            "send_reminder_time": app.send_reminder_time_var.get(),
```

(Beide Comboboxes sind `state="readonly"` — Werte kommen garantiert aus der vorgegebenen Liste, kein eigener Parser/Validierungspfad nötig, Muster wie `"default_pause": int(work.pause_var.get())`.)

- [ ] **Step 5: Import-Check + Lint**

Run: `python -c "import src.dialogs.settings_dialog.tab_app; import src.dialogs.settings_dialog.dialog"`
Expected: kein Output, Exit-Code 0

Run: `ruff check src/dialogs/settings_dialog/tab_app.py src/dialogs/settings_dialog/dialog.py`
Expected: `All checks passed!`

Run: `pytest -q`
Expected: alle bestehenden Tests weiterhin grün (keine Regressionen)

- [ ] **Step 6: Commit**

```bash
git add src/dialogs/settings_dialog/tab_app.py src/dialogs/settings_dialog/dialog.py
git commit -m "$(cat <<'EOF'
feat(send-reminder): Settings-UI für monatlichen Sende-Reminder

Neuer Block im App-Tab: Checkbox + Tag-im-Monat/Uhrzeit-Dropdowns,
Hinweis auf das Clamping bei kürzeren Monaten.
EOF
)"
```

---

## Task 5: App-Verdrahtung (`src/ui.py`)

**Files:**
- Modify: `src/ui.py:23` (Import), `:98-111` (Konstruktor), `:365-366` (Settings-`on_change`), `:395-467` (`_apply_tray_setting`/neue `_apply_send_reminder_setting`), `:625-634` (`_quit_with_sync_push`), `:672-675` (`restart_for_scaling`)

**Interfaces:**
- Consumes: `SendReminderScheduler` (Task 2), `settings.get("send_reminder_enabled")` (Task 3).
- Produces: `App._send_reminders` (`SendReminderScheduler`-Instanz), `App._apply_send_reminder_setting()`.

Kein automatisierter Test (Tk-App-Klasse). Verifikation über Import-Check + `ruff` + vollen `pytest`-Lauf + manuellen Smoke-Test.

- [ ] **Step 1: Import ergänzen**

`src/ui.py:23` ist aktuell:

```python
from src.reminder_scheduler import ReminderScheduler
```

Ändern zu:

```python
from src.reminder_scheduler import ReminderScheduler
from src.send_reminder_scheduler import SendReminderScheduler
```

- [ ] **Step 2: Scheduler im Konstruktor anlegen**

`src/ui.py:98-102` ist aktuell:

```python
        self._reminders = ReminderScheduler(
            self.root, self.settings, self.storage,
            self.reservation_store, lambda: self._tray,
        )
        self._build_header()
```

Ändern zu:

```python
        self._reminders = ReminderScheduler(
            self.root, self.settings, self.storage,
            self.reservation_store, lambda: self._tray,
        )
        self._send_reminders = SendReminderScheduler(
            self.root, self.settings, lambda: self._tray,
        )
        self._build_header()
```

- [ ] **Step 3: Beim Start anwenden**

`src/ui.py:109-111` ist aktuell:

```python
        self._apply_always_on_top()
        self._apply_tray_setting()
        self._apply_reminder_setting()
```

Ändern zu:

```python
        self._apply_always_on_top()
        self._apply_tray_setting()
        self._apply_reminder_setting()
        self._apply_send_reminder_setting()
```

- [ ] **Step 4: Nach Settings-Speicherung anwenden**

`src/ui.py:364-366` ist aktuell:

```python
            self._apply_always_on_top()
            self._apply_tray_setting()
            self._apply_reminder_setting()
```

Ändern zu:

```python
            self._apply_always_on_top()
            self._apply_tray_setting()
            self._apply_reminder_setting()
            self._apply_send_reminder_setting()
```

- [ ] **Step 5: `want_tray` um dritten Kanal erweitern**

`src/ui.py:404-408` ist aktuell:

```python
        from src.tray import TrayIcon, is_supported

        # Tray dient zweierlei: Minimize-to-Tray UND als Toast-Kanal für
        # Reservierungs-Erinnerungen. Es läuft, sobald EINES aktiv ist.
        want_tray = (bool(self.settings.get("minimize_to_tray"))
                     or bool(self.settings.get("reminders_enabled")))
```

Ändern zu:

```python
        from src.tray import TrayIcon, is_supported

        # Tray dient mehrerem: Minimize-to-Tray UND als Toast-Kanal für
        # Reservierungs- und Sende-Erinnerungen. Es läuft, sobald EINES aktiv ist.
        want_tray = (bool(self.settings.get("minimize_to_tray"))
                     or bool(self.settings.get("reminders_enabled"))
                     or bool(self.settings.get("send_reminder_enabled")))
```

- [ ] **Step 6: Beide Fallback-Reset-Stellen erweitern**

`src/ui.py:411-421` ist aktuell:

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

Ändern zu:

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
                self.settings.set("send_reminder_enabled", False)
                return
```

`src/ui.py:440-449` ist aktuell:

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

Ändern zu:

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
                self.settings.set("send_reminder_enabled", False)
                return
```

- [ ] **Step 7: Neue `_apply_send_reminder_setting`-Methode**

`src/ui.py:456-467` (`_apply_reminder_setting`, endet vor `_restore_from_tray`) ist aktuell:

```python
    def _apply_reminder_setting(self):
        """Startet/stoppt den Reminder-Poll abhängig vom Setting. Braucht ein
        laufendes Tray-Icon als Toast-Kanal — ohne Tray wird gestoppt.

        MUSS nach `_apply_tray_setting()` laufen (liest `self._tray`): erst wird
        der Tray-Kanal (de)aktiviert, dann der Poll daran gekoppelt. Beide
        Call-Sites (__init__, Settings-`_on_change`) halten diese Reihenfolge."""
        want = bool(self.settings.get("reminders_enabled")) and self._tray is not None
        if want:
            self._reminders.start()
        else:
            self._reminders.stop()

    def _restore_from_tray(self):
```

Ändern zu:

```python
    def _apply_reminder_setting(self):
        """Startet/stoppt den Reminder-Poll abhängig vom Setting. Braucht ein
        laufendes Tray-Icon als Toast-Kanal — ohne Tray wird gestoppt.

        MUSS nach `_apply_tray_setting()` laufen (liest `self._tray`): erst wird
        der Tray-Kanal (de)aktiviert, dann der Poll daran gekoppelt. Beide
        Call-Sites (__init__, Settings-`_on_change`) halten diese Reihenfolge."""
        want = bool(self.settings.get("reminders_enabled")) and self._tray is not None
        if want:
            self._reminders.start()
        else:
            self._reminders.stop()

    def _apply_send_reminder_setting(self):
        """Startet/stoppt den monatlichen Sende-Reminder-Poll abhängig vom
        Setting. Braucht ein laufendes Tray-Icon als Toast-Kanal — ohne Tray
        wird gestoppt.

        MUSS nach `_apply_tray_setting()` laufen (liest `self._tray`), wie
        `_apply_reminder_setting()`."""
        want = bool(self.settings.get("send_reminder_enabled")) and self._tray is not None
        if want:
            self._send_reminders.start()
        else:
            self._send_reminders.stop()

    def _restore_from_tray(self):
```

- [ ] **Step 8: Beide Shutdown-Stellen ergänzen**

`src/ui.py:625-634` (`_quit_with_sync_push`) ist aktuell:

```python
    def _quit_with_sync_push(self):
        """Push zum Drive (falls aktiv) und App komplett beenden. Wird vom
        normalen X-Klick (ohne Tray) und vom Tray-Menü-„Beenden" aufgerufen."""
        self._sync.push_on_quit()
        if self._tray is not None:
            self._tray.stop()
        self._reminders.stop()
        if self._single_instance is not None:
            self._single_instance.release()
        self.root.destroy()
```

Ändern zu:

```python
    def _quit_with_sync_push(self):
        """Push zum Drive (falls aktiv) und App komplett beenden. Wird vom
        normalen X-Klick (ohne Tray) und vom Tray-Menü-„Beenden" aufgerufen."""
        self._sync.push_on_quit()
        if self._tray is not None:
            self._tray.stop()
        self._reminders.stop()
        self._send_reminders.stop()
        if self._single_instance is not None:
            self._single_instance.release()
        self.root.destroy()
```

`src/ui.py:672-675` (Ende von `restart_for_scaling`) ist aktuell:

```python
        if self._tray is not None:
            self._tray.stop()
        self._reminders.stop()
        self.root.destroy()
```

Ändern zu:

```python
        if self._tray is not None:
            self._tray.stop()
        self._reminders.stop()
        self._send_reminders.stop()
        self.root.destroy()
```

- [ ] **Step 9: Import-Check + Lint + voller Testlauf**

Run: `python -c "import src.ui"`
Expected: kein Output, Exit-Code 0

Run: `ruff check src/ui.py`
Expected: `All checks passed!`

Run: `pytest -q`
Expected: alle Tests grün (keine Regressionen durch die Verdrahtung)

- [ ] **Step 10: Commit**

```bash
git add src/ui.py
git commit -m "$(cat <<'EOF'
feat(send-reminder): App-Verdrahtung für monatlichen Sende-Reminder

SendReminderScheduler analog zu ReminderScheduler eingehängt: Tray läuft
jetzt auch für send_reminder_enabled, dritter _apply_*_setting-Zweig,
Stop an beiden Shutdown-Pfaden.
EOF
)"
```

- [ ] **Step 11: Manueller Smoke-Test**

App starten: `python -m src.main`

1. Einstellungen öffnen → Tab „App" → „Erinnerung zum Verschicken der
   Arbeitszeiten" aktivieren, Tag = heutiger Tag, Uhrzeit = aktuelle Uhrzeit
   + 2 Minuten (auf 5-Minuten-Raster runden) → Speichern.
2. ~2 Minuten warten → Toast „Zeit, deine Arbeitszeiten für {Monat} zu
   verschicken." sollte erscheinen (Tray-Icon muss dafür sichtbar sein,
   Windows vorausgesetzt).
3. App beenden, in den Einstellungen die Uhrzeit auf eine bereits
   vergangene Zeit (heute) zurücksetzen, `settings.json` prüfen:
   `send_reminder_last_fired_month` auf den Vormonat setzen (simuliert
   „letzten Monat gefeuert, diesen Monat noch nicht"), App neu starten →
   Toast sollte innerhalb der ersten ~5 Sekunden erscheinen (Catch-up).
4. Tag auf `31` stellen, in Gedanken für einen 30-Tage-Monat durchspielen
   (z.B. `scheduled_datetime(2026, 4, 31, ...)` in einer Python-Shell
   gegenprüfen) — kein UI-Crash, Verhalten wie in Task 1 getestet.

---

## Task 6: Dokumentation (`CLAUDE.md` / `src/CLAUDE.md`)

**Files:**
- Modify: `CLAUDE.md:295-296`
- Modify: `src/CLAUDE.md:150`

Kein Test — reine Doku-Pflege (Projekt-Konvention: „Kein testbares Verhalten
(Wiring/Config/Rename/Doc) → kein Test"), aber vom Root-`CLAUDE.md`
("Diese Datei pflegen") und `src/CLAUDE.md` explizit verlangt.

- [ ] **Step 1: Root-`CLAUDE.md` Modulliste ergänzen**

`CLAUDE.md:295-296` ist aktuell:

```
- `src/reminders.py` — pure Fälligkeits-Logik für Reservierungs-Erinnerungen (Tk-frei); `src/reminder_scheduler.py` — periodischer Reminder-Poll (root.after) → Toast über Tray
```

Ändern zu:

```
- `src/reminders.py` — pure Fälligkeits-Logik für Reservierungs-Erinnerungen (Tk-frei); `src/reminder_scheduler.py` — periodischer Reminder-Poll (root.after) → Toast über Tray
- `src/send_reminder.py` — pure Fälligkeits-Logik für den monatlichen Sende-Reminder (Tk-frei), Tag im Monat auf die tatsächliche Monatslänge geclamped; `src/send_reminder_scheduler.py` — periodischer Poll (root.after) → Toast über Tray, Fired-Zustand persistiert in Settings (einmal pro Monat, auch über Neustarts hinweg)
```

- [ ] **Step 2: `src/CLAUDE.md` Architektur-Absatz ergänzen**

`src/CLAUDE.md:150` ist aktuell:

```
  `reminders.py` — pure Fälligkeits-Logik für Reservierungs-Erinnerungen (Tk-frei, `now` als Parameter): pro heutigem reservierten Slot mit Kategorie ohne erfasste Ist-Zeit `upcoming` (N Min vor Ende) oder `missed` (nach Ende). Der `ReminderScheduler` (`reminder_scheduler.py`) pollt minütlich über `root.after` und schickt fällige Toasts über `App._tray`.
```

Ändern zu:

```
  `reminders.py` — pure Fälligkeits-Logik für Reservierungs-Erinnerungen (Tk-frei, `now` als Parameter): pro heutigem reservierten Slot mit Kategorie ohne erfasste Ist-Zeit `upcoming` (N Min vor Ende) oder `missed` (nach Ende). Der `ReminderScheduler` (`reminder_scheduler.py`) pollt minütlich über `root.after` und schickt fällige Toasts über `App._tray`. Analog dazu `send_reminder.py`/`send_reminder_scheduler.py`: ein einzelner Fällig-Zeitpunkt pro Monat (Tag + Uhrzeit, Tag auf die Monatslänge geclamped) statt Slot-Fenster; der Fired-Zustand wird bewusst **persistiert** (`settings.send_reminder_last_fired_month`, `"YYYY-MM"`) statt nur im Speicher gehalten wie beim Reservierungs-Reminder — verhindert wiederholte Toasts bei App-Neustarts im selben Monat.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md src/CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: send_reminder/send_reminder_scheduler in Architektur-Docs aufnehmen

EOF
)"
```
