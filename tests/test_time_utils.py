from src.time_utils import format_iso_date, format_iso_datetime


def test_format_iso_date_from_timestamp():
    assert format_iso_date("2026-06-02T14:30:00Z") == "02.06.2026"


def test_format_iso_date_from_plain_date():
    assert format_iso_date("2026-06-02") == "02.06.2026"


def test_format_iso_date_empty_uses_fallback():
    assert format_iso_date("", fallback="noch nie") == "noch nie"
    assert format_iso_date(None, fallback="noch nie") == "noch nie"


def test_format_iso_date_too_short_uses_fallback():
    assert format_iso_date("2026-06", fallback="—") == "—"


def test_format_iso_date_unparsable_falls_back_to_raw_prefix():
    # Regex-valide Länge, aber unmögliches Datum → roher 10-Zeichen-Prefix.
    assert format_iso_date("2026-13-99T00:00:00Z") == "2026-13-99"


def test_format_iso_datetime_with_time():
    assert format_iso_datetime("2026-06-02T14:30:00Z") == "02.06.2026 14:30"


def test_format_iso_datetime_space_separator():
    assert format_iso_datetime("2026-06-02 09:05:00") == "02.06.2026 09:05"


def test_format_iso_datetime_date_only_no_time():
    assert format_iso_datetime("2026-06-02") == "02.06.2026"


def test_format_iso_datetime_empty_uses_fallback():
    assert format_iso_datetime("", fallback="") == ""
