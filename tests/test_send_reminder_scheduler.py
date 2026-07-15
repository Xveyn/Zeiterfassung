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
