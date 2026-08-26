import datetime

from src.send_reminder_scheduler import SendReminderScheduler


class _FakeTray:
    def __init__(self):
        self.messages = []

    def notify(self, message, title="Zeiterfassung"):
        self.messages.append(message)


_DEFAULTS = {
    "send_reminder_day": 15, "send_reminder_time": "18:00",
    "send_reminder_last_fired_month": "",
    "send_reminder_weekend_shift": "none",
    "send_reminder_shift_holidays": False,
    "send_reminder_reservations_enabled": False,
    "gcal_enabled": False,
    "state": "",
}


class _FakeSettings:
    def __init__(self, data):
        # Fehlende Keys in das ÜBERGEBENE Dict fuellen, nicht in eine Kopie:
        # die bestehenden Tests pruefen send_reminder_last_fired_month direkt
        # an ihrem settings_data.
        for key, value in _DEFAULTS.items():
            data.setdefault(key, value)
        self._data = data

    def get(self, key):
        return self._data[key]

    def set(self, key, value):
        self._data[key] = value


class _FakeReservationStore:
    def __init__(self, data=None):
        self._data = data or {}

    def get(self, date_str):
        return self._data.get(date_str)


def _now(day, h, m):
    return datetime.datetime(2026, 7, day, h, m)


def _make(settings_data, tray, reservation_store=None):
    return SendReminderScheduler(
        root=None,
        settings=_FakeSettings(settings_data),
        get_tray=lambda: tray,
        reservation_store=reservation_store,
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


def _res_store(date_str, end, minutes):
    return _FakeReservationStore({
        date_str: {"slots": [{"start": "08:00", "end": end, "kategorie": "",
                              "send_reminder_minutes": minutes}]}})


def test_day_reminder_fires_before_reservation_end():
    tray = _FakeTray()
    sched = _make(
        {"send_reminder_reservations_enabled": True, "gcal_enabled": True,
         "send_reminder_last_fired_month": "2026-07"},
        tray, _res_store("2026-07-15", "17:00", 15))
    assert sched.poll(_now(15, 16, 44)) is False
    assert sched.poll(_now(15, 16, 45)) is True
    assert "17:00" in tray.messages[0] and "verschicken" in tray.messages[0]


def test_day_reminder_fires_only_once_per_day():
    tray = _FakeTray()
    sched = _make(
        {"send_reminder_reservations_enabled": True, "gcal_enabled": True,
         "send_reminder_last_fired_month": "2026-07"},
        tray, _res_store("2026-07-15", "17:00", 15))
    sched.poll(_now(15, 16, 45))
    assert sched.poll(_now(15, 16, 46)) is False
    assert len(tray.messages) == 1


def test_day_reminder_resets_on_new_day():
    tray = _FakeTray()
    store = _FakeReservationStore({
        "2026-07-15": {"slots": [{"start": "08:00", "end": "17:00",
                                  "kategorie": "", "send_reminder_minutes": 15}]},
        "2026-07-16": {"slots": [{"start": "08:00", "end": "17:00",
                                  "kategorie": "", "send_reminder_minutes": 15}]},
    })
    sched = _make(
        {"send_reminder_reservations_enabled": True, "gcal_enabled": True,
         "send_reminder_last_fired_month": "2026-07"}, tray, store)
    sched.poll(_now(15, 16, 45))
    assert sched.poll(_now(16, 16, 45)) is True
    assert len(tray.messages) == 2


def test_day_reminder_needs_both_switches():
    tray = _FakeTray()
    store = _res_store("2026-07-15", "17:00", 15)
    off = _make({"send_reminder_reservations_enabled": False,
                 "gcal_enabled": True,
                 "send_reminder_last_fired_month": "2026-07"}, tray, store)
    assert off.poll(_now(15, 16, 45)) is False
    no_gcal = _make({"send_reminder_reservations_enabled": True,
                     "gcal_enabled": False,
                     "send_reminder_last_fired_month": "2026-07"}, tray, store)
    assert no_gcal.poll(_now(15, 16, 45)) is False
    assert tray.messages == []


def test_day_reminder_without_store_is_noop():
    tray = _FakeTray()
    sched = _make({"send_reminder_reservations_enabled": True,
                   "gcal_enabled": True,
                   "send_reminder_last_fired_month": "2026-07"}, tray)
    assert sched.poll(_now(15, 16, 45)) is False


def test_both_channels_can_fire_on_the_same_day():
    tray = _FakeTray()
    sched = _make(
        {"send_reminder_day": 15, "send_reminder_time": "16:00",
         "send_reminder_reservations_enabled": True, "gcal_enabled": True},
        tray, _res_store("2026-07-15", "17:00", 15))
    assert sched.poll(_now(15, 16, 45)) is True
    assert len(tray.messages) == 2


def test_monthly_channel_uses_weekend_shift():
    # 15.08.2026 ist ein Samstag; vorziehen -> Fr 14.08.
    tray = _FakeTray()
    sched = _make({"send_reminder_day": 15, "send_reminder_time": "18:00",
                   "send_reminder_weekend_shift": "backward"}, tray)
    assert sched.poll(datetime.datetime(2026, 8, 14, 18, 0)) is True
    assert "August" in tray.messages[0]
