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


def _make(reservation_by_date, entry_by_date, tray, minutes=15, enabled=True):
    settings = {"reminder_minutes_before": minutes, "reservations_enabled": enabled}
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


def test_poll_is_silent_when_reservations_are_off():
    tray = _FakeTray()
    sched = _make(
        {"2026-07-02": {"slots": [{"start": "09:00", "end": "17:00", "kategorie": "A"}]}},
        {}, tray, enabled=False)
    assert sched.poll(_now(16, 50)) == []
    assert tray.messages == []


# --- Handy deckt den Toast ab (#331) ---------------------------------------------------------

def _make_covered(reservation_by_date, entry_by_date, tray, covers):
    sched = _make(reservation_by_date, entry_by_date, tray)
    sched._phone_covers = covers
    return sched


_RES = {"2026-07-02": {"slots": [{"start": "09:00", "end": "17:00", "kategorie": "A"}]}}


def test_no_toast_when_the_phone_covers_the_reservation_reminder():
    tray = _FakeTray()
    asked = []
    sched = _make_covered(_RES, {}, tray, lambda kind: (asked.append(kind), True)[1])
    fired = sched.poll(_now(16, 50))
    assert len(fired) == 1 and tray.messages == []
    assert asked == ["reservation"]


def test_a_covered_reminder_is_still_marked_so_it_does_not_come_back_later():
    tray = _FakeTray()
    covered = {"on": True}
    sched = _make_covered(_RES, {}, tray, lambda kind: covered["on"])
    sched.poll(_now(16, 50))
    covered["on"] = False                       # das Handy fällt aus der Deckung
    assert sched.poll(_now(16, 55)) == []
    assert tray.messages == []


def test_the_toast_comes_when_the_phone_does_not_cover():
    tray = _FakeTray()
    sched = _make_covered(_RES, {}, tray, lambda kind: False)
    sched.poll(_now(16, 50))
    assert len(tray.messages) == 1


def test_without_a_phone_check_the_toast_always_comes():
    tray = _FakeTray()
    sched = _make(_RES, {}, tray)
    sched.poll(_now(16, 50))
    assert len(tray.messages) == 1
