# Arbeitszeit per Toast-Button eintragen — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reservierungs-Erinnerungen bekommen auf Windows einen echten Button „Arbeitszeit eintragen"; ein Klick schreibt den Reservierungs-Slot als Ist-Zeit.

**Architecture:** Reine, testbare Nähte (Slot-Builder in `reminders.py`, Scheduler-Logik) + eine dünne WinRT-Toast-Naht im Windows-Tray-Backend, die bei fehlender Lib/Nicht-Windows still auf den bestehenden Plain-Toast zurückfällt. Der Button-Callback marshallt wie die Tray-Actions per `root.after(0, …)` auf den Tk-Thread und schreibt unter dem geteilten `data_lock` in den Storage.

**Tech Stack:** Python 3.10, Tkinter, pystray (bestehend), `windows-toasts` (WinRT, neu, nur Windows), pytest.

## Global Constraints

- **Python-Floor 3.10** — jede gepinnte Version muss 3.10 unterstützen (CI-/Release-Python).
- **`windows-toasts` ist Windows-only** (`; sys_platform == "win32"` in `requirements.txt`) und wird **lazy** importiert (nur im interaktiven Notify-Pfad), mit `# pyright: ignore[reportMissingImports]` an der Import-Zeile — exakt wie pystray/pyobjc. `import src.tray`/`import src.ui` müssen ohne die Lib durchlaufen.
- **`windows-toasts` NICHT in `requirements-test.txt`** — der WinRT-Toast wird nicht in CI getestet, nur manuell. Testbare Nähte laufen ohne die Lib.
- **Datumsformat intern ISO** (`YYYY-MM-DD`), UI-Text **deutsch**.
- **Commit-Trailer** an jedem Commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Nur **kategorisierte** Reservierungen lösen Reminder/Button aus (bestehende Vorbedingung).

---

## File Structure

- `src/reminders.py` — **Modify:** neue pure Funktion `ist_slot_from_reservation(...)` neben `due_reminders`.
- `src/reminder_scheduler.py` — **Modify:** `notify_action` statt `notify`; `_make_log_action`/`_log_reservation`; Konstruktor um `data_lock`/`on_logged`.
- `src/tray.py` — **Modify:** `AUMID`-Konstante; `notify_action` auf Fassade + `_PystrayBackend` (+ `_show_interactive_toast`, `_live_toasts`).
- `src/tray_mac.py` — **Modify:** `notify_action` (delegiert an `notify`).
- `src/ui.py` — **Modify:** `ReminderScheduler` mit `data_lock`/`on_logged`/`marshal` konstruieren; AUMID-Literal auf `tray.AUMID` deduplizieren.
- `requirements.txt`, `README.md`, `build.py` — **Modify:** Dependency + WinRT-Bündelung. (Keine `main.py`/`installer.iss`-Änderung — die AUMID-Registrierung in `ui.py` besteht bereits.)
- Tests: `tests/test_reminders.py`, `tests/test_reminder_scheduler.py`, `tests/test_tray.py` — **Modify.**

---

### Task 1: Pure Slot-Builder `ist_slot_from_reservation`

**Files:**
- Modify: `src/reminders.py`
- Test: `tests/test_reminders.py`

**Interfaces:**
- Consumes: `src.category_defaults.resolve_slot_defaults(category_times, kategorie, weekday_key, g_start, g_end, g_pause) -> (start, end, pause)` (bestehend).
- Produces: `ist_slot_from_reservation(res_slot: dict, category_times: dict, weekday_key: str, default_pause: int) -> {"start", "end", "pause", "kategorie"}`. `start`/`end`/`kategorie` aus `res_slot`; `pause` aus dem Per-Kategorie-Default (Fallback `default_pause`).

- [ ] **Step 1: Write the failing tests**

In `tests/test_reminders.py` ergänzen (Import oben erweitern und Tests anhängen):

```python
from src.reminders import Reminder, due_reminders, ist_slot_from_reservation


def test_ist_slot_uses_reservation_times_and_default_pause():
    slot = ist_slot_from_reservation(
        {"start": "09:00", "end": "17:00", "kategorie": "A"}, {}, "thu", 30)
    assert slot == {"start": "09:00", "end": "17:00", "pause": 30, "kategorie": "A"}


def test_ist_slot_uses_category_pause_override():
    slot = ist_slot_from_reservation(
        {"start": "09:00", "end": "17:00", "kategorie": "A"},
        {"A": {"pause": 45}}, "thu", 30)
    assert slot["pause"] == 45


def test_ist_slot_per_day_mode_pause_from_toplevel():
    slot = ist_slot_from_reservation(
        {"start": "09:00", "end": "17:00", "kategorie": "A"},
        {"A": {"mode": "per_day", "pause": 15, "days": {}}}, "thu", 30)
    assert slot["pause"] == 15


def test_ist_slot_strips_category_whitespace():
    slot = ist_slot_from_reservation(
        {"start": "09:00", "end": "17:00", "kategorie": "  A  "}, {}, "thu", 30)
    assert slot["kategorie"] == "A"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reminders.py -k ist_slot -v`
Expected: FAIL with `ImportError: cannot import name 'ist_slot_from_reservation'`.

- [ ] **Step 3: Implement the function**

In `src/reminders.py` den Import oben ergänzen (nach den bestehenden Imports):

```python
from src.category_defaults import resolve_slot_defaults
```

Und die Funktion am Dateiende anhängen:

```python
def ist_slot_from_reservation(res_slot, category_times, weekday_key, default_pause):
    """Baut aus einem Reservierungs-Slot (Soll) den Ist-Zeit-Slot fürs Eintragen.

    start/end/kategorie stammen aus der Reservierung; die Pause wird aus dem
    Per-Kategorie-Default abgeleitet (resolve_slot_defaults, Fallback
    default_pause) — genau wie beim manuellen Anlegen im Tages-Dialog. Start/Ende
    aus resolve_slot_defaults werden bewusst verworfen (die Reservierung ist die
    Quelle der Zeiten).
    """
    kategorie = (res_slot.get("kategorie") or "").strip()
    _, _, pause = resolve_slot_defaults(
        category_times, kategorie, weekday_key, None, None, default_pause)
    return {
        "start": res_slot.get("start"),
        "end": res_slot.get("end"),
        "pause": pause,
        "kategorie": kategorie,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reminders.py -v`
Expected: PASS (neue + bestehende Tests).

- [ ] **Step 5: Commit**

```bash
git add src/reminders.py tests/test_reminders.py
git commit -m "feat(reminders): ist_slot_from_reservation (Soll->Ist mit Kategorie-Pause)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `notify_action` im Tray (interaktiver Windows-Toast + Fallback)

**Files:**
- Modify: `src/tray.py`
- Modify: `src/tray_mac.py`
- Test: `tests/test_tray.py`

**Interfaces:**
- Produces:
  - `src.tray.AUMID: str` — App-User-Model-ID-Konstante (auch von `main.py` genutzt).
  - `TrayIcon.notify_action(message, title="Zeiterfassung", action_label="", on_action=None)` — zeigt auf Windows einen Toast mit Button `action_label`, dessen Klick `on_action()` auslöst; sonst/bei Fehler Plain-`notify(message, title)`.
  - `_PystrayBackend.notify_action(...)` gleiche Signatur; `_PystrayBackend._show_interactive_toast(message, title, action_label, on_action) -> bool`.
- Consumes: bestehendes `_PystrayBackend.notify(message, title)`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_tray.py` anhängen:

```python
def test_notify_action_falls_back_to_notify(monkeypatch):
    from src.tray import _PystrayBackend
    b = _PystrayBackend("base", on_show=lambda: None, on_quit=lambda: None)
    calls = {}
    monkeypatch.setattr(b, "_show_interactive_toast", lambda *a: False)
    monkeypatch.setattr(
        b, "notify", lambda m, t="Zeiterfassung": calls.__setitem__("notify", (m, t)))
    b.notify_action("msg", "Titel", "Eintragen", lambda: None)
    assert calls["notify"] == ("msg", "Titel")


def test_notify_action_interactive_path_wins(monkeypatch):
    from src.tray import _PystrayBackend
    b = _PystrayBackend("base", on_show=lambda: None, on_quit=lambda: None)
    calls = {"notify": 0}
    monkeypatch.setattr(b, "_show_interactive_toast", lambda *a: True)
    monkeypatch.setattr(
        b, "notify", lambda m, t="Zeiterfassung": calls.__setitem__("notify", calls["notify"] + 1))
    b.notify_action("msg", "Titel", "Eintragen", lambda: None)
    assert calls["notify"] == 0  # interaktiver Pfad übernahm, kein Fallback
```

Den bestehenden `FakeBackend` in `test_facade_instantiates_and_delegates` um `notify_action` erweitern und dort assertion ergänzen:

```python
        def notify_action(self, message, title="Zeiterfassung", action_label="", on_action=None):
            seen["notify_action"] = (message, title, action_label)
```

Direkt nach `icon.notify("hallo")`/dessen assert einfügen:

```python
    icon.notify_action("m", "T", "Eintragen", lambda: None)
    assert seen["notify_action"] == ("m", "T", "Eintragen")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tray.py -v`
Expected: FAIL (`AttributeError: '_PystrayBackend' object has no attribute 'notify_action'` bzw. Fassade delegiert nicht).

- [ ] **Step 3: Implement in `src/tray.py`**

Nahe dem Datei-Anfang (nach den Imports) die Konstante ergänzen. **Wichtig:** exakt
der String, den `ui.py` bereits als Prozess-AUMID setzt und als HKCU-Key
registriert (kleingeschrieben, namespaced) — NICHT neu erfinden:

```python
# App-User-Model-ID (Single Source). ui.py setzt sie bereits als Prozess-AUMID
# und registriert den HKCU-Key Software\Classes\AppUserModelId\<AUMID> mit
# DisplayName — genau das, was windows-toasts für die Action-Center-Aktivierung
# des Toast-Buttons braucht. Der InteractableWindowsToaster nutzt dieselbe ID.
AUMID = "margenheld.zeiterfassung"
```

In `_PystrayBackend.__init__` die Toast-Referenzliste ergänzen (nach `self._thread = None`):

```python
        self._live_toasts = []  # starke Refs auf angezeigte interaktive Toasts (GC-Schutz)
```

In `_PystrayBackend` (z.B. direkt nach `notify`) einfügen:

```python
    def notify_action(self, message, title="Zeiterfassung", action_label="", on_action=None):
        """Wie notify(), aber mit einem Aktions-Button auf dem Toast (Windows/WinRT).

        Fällt bei Nicht-Windows, fehlender windows-toasts-Lib oder jedem Fehler
        still auf den bestehenden Plain-Toast (notify) zurück."""
        if action_label and on_action is not None and \
                self._show_interactive_toast(message, title, action_label, on_action):
            return
        self.notify(message, title)

    def _show_interactive_toast(self, message, title, action_label, on_action):
        """Windows-only: interaktiver WinRT-Toast mit einem Button.

        windows-toasts wird LAZY importiert (nicht in CI-Deps, wie pystray). Der
        on_activated-Callback läuft auf einem WinRT-Thread — on_action marshallt
        selbst auf den Tk-Thread (Aufrufer-Vertrag, s. ReminderScheduler). Jeder
        Fehler/fehlende Lib → False, Aufrufer fällt auf notify() zurück."""
        import platform
        if platform.system() != "Windows":
            return False
        try:
            from windows_toasts import (  # pyright: ignore[reportMissingImports]  # nicht in CI-Test-Deps
                InteractableWindowsToaster, Toast, ToastButton,
            )
            toaster = InteractableWindowsToaster("Zeiterfassung", AUMID)
            toast = Toast()
            toast.text_fields = [message]
            toast.AddAction(ToastButton(action_label, "log"))
            # on_activated feuert AUCH bei Klick auf den Toast-Körper — nur der
            # Button (arguments == "log") soll eintragen.
            def _on_activated(args):
                if getattr(args, "arguments", None) == "log":
                    on_action()
            toast.on_activated = _on_activated
            toaster.show_toast(toast)
            # Starke Refs halten, sonst GC → Callback tot. Auf die letzten paar
            # begrenzen, damit die Liste nicht unbegrenzt wächst.
            self._live_toasts.append((toaster, toast))
            del self._live_toasts[:-8]
            return True
        except Exception:
            logging.getLogger(__name__).exception(
                "Interaktiver Toast fehlgeschlagen — Fallback auf notify()")
            return False
```

In der `TrayIcon`-Fassade (nach `notify`) delegieren:

```python
    def notify_action(self, message, title="Zeiterfassung", action_label="", on_action=None):
        if self._backend is not None:
            self._backend.notify_action(message, title, action_label, on_action)
```

- [ ] **Step 4: Implement in `src/tray_mac.py`**

In `MacTrayBackend` (nach `notify`) ergänzen:

```python
    def notify_action(self, message, title="Zeiterfassung", action_label="", on_action=None):
        """macOS kennt (noch) keine interaktiven Toast-Buttons — Plain-Toast."""
        self.notify(message, title)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_tray.py -v`
Expected: PASS. Zusätzlich `pytest tests/test_tray_mac.py -v` bleibt grün.

- [ ] **Step 6: Commit**

```bash
git add src/tray.py src/tray_mac.py tests/test_tray.py
git commit -m "feat(tray): notify_action mit interaktivem Windows-Toast-Button

WinRT-Button via windows-toasts (lazy, Windows-only); Fallback auf Plain-
notify() bei Nicht-Windows/fehlender Lib/Fehler. AUMID-Konstante.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Scheduler nutzt `notify_action` + trägt Ist-Zeit ein

**Files:**
- Modify: `src/reminder_scheduler.py`
- Test: `tests/test_reminder_scheduler.py`

**Interfaces:**
- Consumes: `ist_slot_from_reservation(...)` (Task 1), `TrayIcon.notify_action(...)` (Task 2), `src.settings.WEEKDAY_KEYS: tuple`.
- Produces:
  - `ReminderScheduler(root, settings, storage, reservation_store, get_tray, now_provider=…, data_lock=None, on_logged=None, marshal=None)`.
  - `ReminderScheduler._log_reservation(today: str, res_slot: dict)` — trägt den Ist-Slot ein und ruft `on_logged`.
  - `poll` ruft pro fälligem Reminder `tray.notify_action(text, "Zeiterfassung", "Arbeitszeit eintragen", on_action)`.
  - `marshal` = `App._marshal_to_ui` (Tk-frei injiziert): schiebt den Button-Callback vom WinRT-Hintergrundthread zweifach-TclError-sicher auf den Tk-Thread. Default (Tests) `None` → `lambda fn: fn()` (inline).

- [ ] **Step 1: Write/adjust the failing tests**

In `tests/test_reminder_scheduler.py` die `_FakeTray`- und `_FakeStore`-Klassen ersetzen bzw. erweitern und `_make` um Settings-Keys ergänzen:

```python
class _FakeTray:
    def __init__(self):
        self.calls = []  # (message, title, action_label, on_action)

    def notify_action(self, message, title, action_label, on_action):
        self.calls.append((message, title, action_label, on_action))

    @property
    def messages(self):  # Rückwärtskompat für bestehende Asserts
        return [c[0] for c in self.calls]


class _FakeStore:
    def __init__(self, by_date):
        self._by_date = by_date

    def get(self, date_str):
        return self._by_date.get(date_str)

    def save(self, date_str, slots):
        self._by_date[date_str] = {"slots": slots}


def _make(reservation_by_date, entry_by_date, tray, minutes=15):
    settings = {
        "reminder_minutes_before": minutes,
        "category_times": {},
        "default_pause": 30,
    }
    return ReminderScheduler(
        root=None,
        settings=type("S", (), {"get": staticmethod(lambda k: settings[k])})(),
        storage=_FakeStore(entry_by_date),
        reservation_store=_FakeStore(reservation_by_date),
        get_tray=lambda: tray,
    )
```

Neue Tests anhängen:

```python
def test_poll_uses_notify_action_with_log_button():
    tray = _FakeTray()
    sched = _make(
        {"2026-07-02": {"slots": [{"start": "09:00", "end": "17:00", "kategorie": "A"}]}},
        {}, tray,
    )
    sched.poll(_now(16, 50))
    assert len(tray.calls) == 1
    message, title, label, on_action = tray.calls[0]
    assert title == "Zeiterfassung"
    assert label == "Arbeitszeit eintragen"
    assert callable(on_action)


def test_log_reservation_appends_ist_slot_and_refreshes():
    tray = _FakeTray()
    sched = _make(
        {"2026-07-02": {"slots": [{"start": "09:00", "end": "17:00", "kategorie": "A"}]}},
        {}, tray,
    )
    refreshed = []
    sched._on_logged = lambda: refreshed.append(True)
    sched._log_reservation(
        "2026-07-02", {"start": "09:00", "end": "17:00", "kategorie": "A"})
    entry = sched._storage.get("2026-07-02")
    assert entry["slots"] == [
        {"start": "09:00", "end": "17:00", "pause": 30, "kategorie": "A"}]
    assert refreshed == [True]


def test_log_reservation_appends_next_to_existing_ist_slot():
    tray = _FakeTray()
    sched = _make(
        {"2026-07-02": {"slots": [{"start": "13:00", "end": "17:00", "kategorie": "B"}]}},
        {"2026-07-02": {"slots": [{"start": "09:00", "end": "12:00", "pause": 0, "kategorie": "A"}]}},
        tray,
    )
    sched._log_reservation(
        "2026-07-02", {"start": "13:00", "end": "17:00", "kategorie": "B"})
    assert len(sched._storage.get("2026-07-02")["slots"]) == 2


def test_toast_button_callback_logs_end_to_end():
    """poll -> notify_action -> Button-Callback (marshal default = inline) trägt
    ein und ruft on_logged."""
    tray = _FakeTray()
    sched = _make(
        {"2026-07-02": {"slots": [{"start": "09:00", "end": "17:00", "kategorie": "A"}]}},
        {}, tray,
    )
    logged = []
    sched._on_logged = lambda: logged.append(True)
    sched.poll(_now(16, 50))
    on_action = tray.calls[0][3]
    on_action()  # marshal-Default führt inline aus
    slots = sched._storage.get("2026-07-02")["slots"]
    assert slots[-1] == {"start": "09:00", "end": "17:00", "pause": 30, "kategorie": "A"}
    assert logged == [True]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reminder_scheduler.py -v`
Expected: FAIL (`_log_reservation` fehlt; `poll` ruft noch `notify`, nicht `notify_action`).

- [ ] **Step 3: Implement in `src/reminder_scheduler.py`**

Imports oben ergänzen:

```python
import contextlib

from src import reminders
from src.settings import WEEKDAY_KEYS
```

Konstruktor um drei Parameter erweitern und Felder setzen:

```python
    def __init__(self, root, settings, storage, reservation_store, get_tray,
                 now_provider=datetime.datetime.now, data_lock=None,
                 on_logged=None, marshal=None):
        self._root = root
        self._settings = settings
        self._storage = storage
        self._reservation_store = reservation_store
        self._get_tray = get_tray
        self._now = now_provider
        self._after_id = None
        self._fired = set()
        self._fired_date = None
        self._data_lock = data_lock if data_lock is not None else contextlib.nullcontext()
        self._on_logged = on_logged
        # marshal schiebt den WinRT-Callback TclError-sicher auf den Tk-Thread
        # (= App._marshal_to_ui). Default (Tests): inline ausführen.
        self._marshal = marshal if marshal is not None else (lambda fn: fn())
```

Die `notify`-Schleife in `poll` ersetzen:

```python
        for rem in due:
            res_slot = {"start": rem.key[1], "end": rem.key[2], "kategorie": rem.kategorie}
            tray.notify_action(
                _toast_text(rem), "Zeiterfassung",
                "Arbeitszeit eintragen", self._make_log_action(today, res_slot))
            self._fired.add(rem.key)
        return due
```

Zwei Methoden ergänzen (nach `poll`):

```python
    def _make_log_action(self, today, res_slot):
        """0-arg-Callback für den Toast-Button. Läuft auf dem WinRT-Hintergrund-
        thread und marshallt via self._marshal (= App._marshal_to_ui) TclError-
        sicher auf den Tk-Thread — NICHT roh via root.after (das umginge den
        doppelten TclError-Schutz, wenn das Fenster beim Klick schon zu ist)."""
        return lambda: self._marshal(
            lambda: self._log_reservation(today, res_slot))

    def _log_reservation(self, today, res_slot):
        """Trägt den Reservierungs-Slot als Ist-Zeit ein (an heutige Slots
        angehängt) und stößt den UI-Refresh an. Read-modify-write unter data_lock."""
        category_times = self._settings.get("category_times") or {}
        default_pause = self._settings.get("default_pause")
        weekday_key = WEEKDAY_KEYS[datetime.date.fromisoformat(today).weekday()]
        ist_slot = reminders.ist_slot_from_reservation(
            res_slot, category_times, weekday_key, default_pause)
        with self._data_lock:
            entry = self._storage.get(today)
            slots = list(entry.get("slots", [])) if entry else []
            slots.append(ist_slot)
            self._storage.save(today, slots)
        if self._on_logged is not None:
            self._on_logged()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reminder_scheduler.py -v`
Expected: PASS (neue + bestehende Tests).

- [ ] **Step 5: Commit**

```bash
git add src/reminder_scheduler.py tests/test_reminder_scheduler.py
git commit -m "feat(reminders): Toast-Button trägt Reservierung als Ist-Zeit ein

poll() nutzt notify_action mit 'Arbeitszeit eintragen'; der Callback
marshallt auf den Tk-Thread und schreibt den Ist-Slot unter data_lock.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: App-Verdrahtung (`data_lock` + `on_logged` + `marshal`; AUMID dedup)

**Files:**
- Modify: `src/ui.py` (ReminderScheduler-Konstruktion, ~Zeile 137–140; AUMID-Literal ~Zeile 79)

**Interfaces:**
- Consumes: `ReminderScheduler(..., data_lock=…, on_logged=…, marshal=…)` (Task 3). `data_lock` ist der in `App.__init__` bereits vorhandene Parameter (wird an `_bg`/`_sync` gereicht). `on_logged=self._refresh`, `marshal=self._marshal_to_ui`. `src.tray.AUMID` (Task 2).

- [ ] **Step 1: Change the construction**

In `src/ui.py` die `ReminderScheduler`-Instanziierung ersetzen:

```python
        self._reminders = ReminderScheduler(
            self.root, self.settings, self.storage,
            self.reservation_store, lambda: self._tray,
            data_lock=data_lock, on_logged=self._refresh,
            marshal=self._marshal_to_ui,
        )
```

- [ ] **Step 2: AUMID-Literal auf die geteilte Konstante deduplizieren**

In `src/ui.py` das lokale Literal (aktuell `app_aumid = "margenheld.zeiterfassung"`,
~Zeile 79) durch einen Import der Single-Source-Konstante ersetzen, damit
`ui.py` und der Toaster garantiert denselben String nutzen:

```python
        from src.tray import AUMID as app_aumid
```

(Der restliche AUMID-Block in `ui.py` — `SetCurrentProcessExplicitAppUserModelID(app_aumid)`
und die HKCU-Registrierung — bleibt **unverändert**; er nutzt jetzt nur die
importierte Konstante statt eines lokalen Literals.)

- [ ] **Step 3: Verify the suite still imports & passes**

Run: `pytest tests/ -q`
Expected: PASS — insbesondere alle Tests, die `src.ui` importieren, laufen weiter (keine Signatur-/Importfehler).

- [ ] **Step 4: Run lint + typecheck**

Run: `ruff check . ; pyright`
Expected: keine neuen Fehler.

- [ ] **Step 5: Commit**

```bash
git add src/ui.py
git commit -m "feat(ui): ReminderScheduler mit data_lock + on_logged + marshal; AUMID dedup

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Dependency & Build (Windows-Integration)

**Files:**
- Modify: `requirements.txt`, `README.md`, `build.py`

**Interfaces:**
- Consumes: die bestehende AUMID-Registrierung in `ui.py` (Prozess-AUMID + HKCU-Key, unverändert) — **keine** neue `main.py`- oder `installer.iss`-Änderung nötig (s. Spec-Abschnitt „AUMID": die Laufzeit-Registrierung in `ui.py` deckt die Action-Center-Aktivierung ab; `windows-toasts` `register_hkey_aumid` macht dasselbe).
- Hinweis: Dieser Task ist **nicht** CI-unit-testbar (WinRT + Frozen-Build) → Abnahme per lokalem/CI-Build + manueller Toast-Verifikation.

- [ ] **Step 1: Dependency pinnen**

In `requirements.txt` nach der `pyobjc`-Zeile ergänzen:

```
Windows-Toasts==1.3.1; sys_platform == "win32"
```

Vor dem Commit verifizieren: PyPI `requires_python` von `Windows-Toasts==1.3.1` schließt **3.10** ein (tut es — `>=3.9`, Classifier 3.9–3.12; zieht `winrt-runtime~=3.0` + `winrt-Windows.*`-Projektionen). Falls eine neuere gepinnte Version gewählt wird, erneut gegen 3.10 prüfen.

- [ ] **Step 2: README-Abhängigkeitstabelle ergänzen**

In `README.md` in der Abhängigkeiten-Tabelle (dort, wo `pyobjc-framework-Cocoa` als macOS-only geführt wird) eine Zeile für `Windows-Toasts` (Windows-only, „interaktive Toast-Buttons für Reservierungs-Erinnerungen") ergänzen. Analog formatieren wie die bestehenden Zeilen.

- [ ] **Step 3: Build — WinRT-Pakete bündeln (`build.py`)**

Im **Windows**-Zweig `build_windows()` die `extra_args`-Liste um die WinRT-Collects ergänzen (NICHT in `_pyinstaller_common`, sonst versuchen macOS/Linux es auch). `windows-toasts==1.3.1` zieht die modularen PyWinRT-Projektionspakete — jedes einzeln sammeln (`--collect-all winrt` allein greift über die Namespace-Paket-Grenzen **nicht** zuverlässig):

```python
    cmd = _pyinstaller_common([
        "--onefile",
        "--noconsole",
        "--icon", "assets/margenheld-icon.ico",
        "--collect-all", "windows_toasts",
        "--collect-all", "winrt_runtime",
        "--collect-all", "winrt.windows.data.xml.dom",
        "--collect-all", "winrt.windows.foundation",
        "--collect-all", "winrt.windows.foundation.collections",
        "--collect-all", "winrt.windows.ui.notifications",
    ])
```

**Verifizieren (empirisch, Step 4):** Zeigt der Frozen-Build einen `ModuleNotFoundError` für ein weiteres `winrt.*`-Submodul, dieses als zusätzliches `--collect-all` ergänzen (iterativ mit `--debug imports` nachziehen). Die `.pyd`-Binaries kommen nur über `--collect-all` mit (nicht über `--hidden-import`).

- [ ] **Step 4: Manuelle Verifikation (Windows)**

1. `pip install -r requirements.txt` (zieht `windows-toasts` + winrt).
2. `python -m src.main` starten; in den Einstellungen `reminders_enabled` aktivieren.
3. Für **heute** eine Reservierung mit Kategorie (ohne erfasste Ist-Zeit) anlegen, sodass ein `upcoming`- oder `missed`-Toast fällig wird.
4. Toast erscheint mit Button **„Arbeitszeit eintragen"** → klicken (am **Live-Banner**; laut Recherche feuert der Callback dort in-process zuverlässig).
5. Prüfen: Der Tag hat jetzt eine Ist-Zeit mit den Reservierungs-Zeiten und der erwarteten Pause; der Kalender ist aktualisiert; kein erneuter Toast für dieselbe Kategorie. Klick auf den Toast-**Körper** (nicht den Button) trägt **nichts** ein (arguments-Gate).
6. Frozen-Build gegen die Bündelung testen: `python build.py` (oder Workflow **Build** → Windows-Artefakt), die entpackte `Zeiterfassung.exe` starten und Schritt 3–5 wiederholen — stellt sicher, dass die WinRT-Pakete korrekt gebündelt sind (kein `ModuleNotFoundError` beim Toast).

- [ ] **Step 5: Commit**

```bash
git add requirements.txt README.md build.py
git commit -m "build(win): windows-toasts + winrt bündeln für Toast-Button

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Doku-Abgleich (`src/CLAUDE.md`)

**Files:**
- Modify: `src/CLAUDE.md` (Reminder-/Tray-Abschnitt)

- [ ] **Step 1: Verantwortlichkeits-Notizen aktualisieren**

Im `reminders.py`/`reminder_scheduler.py`-Eintrag ergänzen, dass der Scheduler auf Windows via `tray.notify_action` einen „Arbeitszeit eintragen"-Button anbietet (WinRT, Fallback Plain-Toast), der den Reservierungs-Slot als Ist-Zeit einträgt. Beim Tray-Abschnitt `notify_action` als neue Naht erwähnen. Knapp halten, Stil der Datei spiegeln.

- [ ] **Step 2: Commit**

```bash
git add src/CLAUDE.md
git commit -m "docs(src): Toast-Button-Naht (notify_action) dokumentieren

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (durchgeführt)

- **Spec-Coverage:** Dependency+CI (Task 5 + Global Constraints), Notify-Layer (Task 2), Slot-Bauen pur (Task 1), Scheduler-Verdrahtung (Task 3), App-Verdrahtung + AUMID-Dedup (Task 4), Build/WinRT (Task 5), Tests (Tasks 1–3), Doku (Task 6), Plattform-Hinweis/Pre-Release (Task-5-Verifikation + Global Constraints). Beide-Typen-Button & Pause-aus-Kategorie: Task 1 + Task 3. Kein-Dedup: bewusst nicht implementiert (Spec-Nicht-Ziel).
- **AUMID (Review-Fix F1):** Keine neue/zweite AUMID — `tray.AUMID = "margenheld.zeiterfassung"` ist Single Source, `ui.py` setzt Prozess-AUMID + HKCU-Key bereits (Task 4 dedupliziert nur das Literal). Keine `main.py`/`installer.iss`-Änderung.
- **Marshalling (Review-Fix F2):** Button-Callback läuft auf WinRT-Thread → via injiziertes `marshal` (= `App._marshal_to_ui`, doppelter TclError-Schutz), nicht roh `root.after`.
- **Placeholder-Scan:** Die einzigen „verifizieren"-Stellen (Pin-Version, WinRT-`--collect-all`-Vollständigkeit) sind explizite empirische Prüf-Schritte mit Default-Wert + Fallback-Anweisung, keine offenen TODOs.
- **Typkonsistenz:** `notify_action(message, title, action_label, on_action)` identisch in Fassade/Backend/Fake-Tray/Aufrufer; `ist_slot_from_reservation(res_slot, category_times, weekday_key, default_pause)` identisch in Task 1 (Def) und Task 3 (Aufruf); `AUMID` in Task 2 (Def), Task 4 (Nutzung).
