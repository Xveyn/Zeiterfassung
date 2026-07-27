"""Nur-Werktage-Modus: Prädikat, Report-Filter und Zähler für die Hinweiszeile.

Pure Logik ohne Tk und ohne Storage — die Einstellung kommt als Stub herein."""

import datetime

from src.workweek import count_weekend_entries, filter_for_report, is_weekend


class _Settings:
    def __init__(self, workweek_only):
        self._value = workweek_only

    def get(self, key):
        assert key == "workweek_only"
        return self._value


def _entries(*dates):
    return {d: {"slots": [{"start": "08:00", "end": "16:00", "pause": 30}]} for d in dates}


# 2026-07-27 ist ein Montag, 2026-08-01 ein Samstag, 2026-08-02 ein Sonntag.

def test_saturday_and_sunday_are_weekend():
    assert is_weekend("2026-08-01") is True
    assert is_weekend("2026-08-02") is True


def test_weekdays_are_not_weekend():
    assert is_weekend("2026-07-27") is False
    assert is_weekend("2026-07-31") is False


def test_unparsable_key_is_not_weekend():
    """Filtern darf nichts verschlucken, das es nicht sicher zuordnen kann."""
    assert is_weekend("kaputt") is False
    assert is_weekend("") is False
    assert is_weekend(None) is False


def test_filter_is_a_noop_when_setting_is_off():
    entries = _entries("2026-07-27", "2026-08-01")
    result = filter_for_report(entries, _Settings(False))
    assert result is entries          # nicht einmal kopiert


def test_filter_drops_weekend_days_when_setting_is_on():
    entries = _entries("2026-07-27", "2026-07-31", "2026-08-01", "2026-08-02")
    result = filter_for_report(entries, _Settings(True))
    assert sorted(result) == ["2026-07-27", "2026-07-31"]


def test_filter_leaves_the_input_untouched():
    """Die Daten bleiben — gefiltert wird eine Kopie."""
    entries = _entries("2026-07-27", "2026-08-01")
    filter_for_report(entries, _Settings(True))
    assert sorted(entries) == ["2026-07-27", "2026-08-01"]


def test_filter_handles_empty_and_weekend_free_input():
    assert filter_for_report({}, _Settings(True)) == {}
    entries = _entries("2026-07-27")
    assert filter_for_report(entries, _Settings(True)) == entries


def test_count_weekend_entries_in_range():
    entries = _entries("2026-07-27", "2026-08-01", "2026-08-02")
    n = count_weekend_entries(
        entries, datetime.date(2026, 7, 27), datetime.date(2026, 8, 2))
    assert n == 2


def test_count_respects_the_range_bounds_inclusively():
    entries = _entries("2026-08-01", "2026-08-02")
    same_day = count_weekend_entries(
        entries, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
    assert same_day == 1
    outside = count_weekend_entries(
        entries, datetime.date(2026, 7, 1), datetime.date(2026, 7, 31))
    assert outside == 0


def test_count_is_zero_without_weekend_entries():
    entries = _entries("2026-07-27", "2026-07-31")
    n = count_weekend_entries(
        entries, datetime.date(2026, 7, 1), datetime.date(2026, 8, 31))
    assert n == 0
