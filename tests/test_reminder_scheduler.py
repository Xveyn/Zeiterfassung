import datetime

from src.reminder_scheduler import ReminderScheduler


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


def _now(h, m):
    return datetime.datetime(2026, 7, 2, h, m)


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
