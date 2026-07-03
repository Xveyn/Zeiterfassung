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
