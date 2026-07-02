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
    assert isinstance(res[0], Reminder)
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
