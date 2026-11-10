import datetime

import pytest

from src import locale_format
from src.time_utils import (
    format_date, format_iso_date, format_iso_datetime, format_iso_weekday_date,
    get_week_label,
)


@pytest.fixture(autouse=True)
def _reset_locale():
    before = locale_format.active()
    yield
    locale_format.set_active(before)


@pytest.fixture
def slash_locale(monkeypatch):
    monkeypatch.setitem(locale_format._PATTERNS, "xx-YY", {
        "date": "%Y/%m/%d", "short": "%m/%d", "weekday_date": "{date} ({weekday})"})
    monkeypatch.setitem(locale_format._WEEKDAYS, "xx-YY", ["A", "B", "C", "D", "E", "F", "G"])
    return "xx-YY"


def test_locale_for_valid_and_invalid():
    assert locale_format.locale_for("de", "DE") == "de-DE"
    for args in (("", "DE"), (None, None), ("xx", "ZZZ"), ("de_DE", "")):
        assert locale_format.locale_for(*args) == "de-DE"


def test_unknown_locale_falls_back_to_default_pattern():
    assert locale_format.date_pattern("zz-ZZ") == locale_format.date_pattern("de-DE")


def test_format_iso_date_uses_given_locale(slash_locale):
    assert format_iso_date("2026-06-02", locale=slash_locale) == "2026/06/02"
    assert format_iso_datetime("2026-06-02T14:30:00Z", locale=slash_locale) == "2026/06/02 14:30"
    assert format_iso_weekday_date("2026-06-02", locale=slash_locale) == "2026/06/02 (B)"
    assert format_date(datetime.date(2026, 6, 2), slash_locale) == "2026/06/02"


def test_active_locale_is_default(slash_locale):
    locale_format.set_active(slash_locale)
    assert format_iso_date("2026-06-02") == "2026/06/02"
    assert get_week_label(2026, 14).startswith("KW 14 · 03/30")


def test_default_output_unchanged():
    assert format_iso_date("2026-06-02") == "02.06.2026"
    assert format_iso_datetime("2026-06-02T14:30:00Z") == "02.06.2026 14:30"
    assert format_iso_weekday_date("2026-06-02") == "Dienstag - 02.06.2026"
    assert get_week_label(2026, 14) == "KW 14 · 30.03. – 05.04.2026"
