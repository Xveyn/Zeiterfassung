import datetime

from src.time_utils import (
    format_date, format_hours_colon, format_hours_hm, format_iso_date,
    format_iso_datetime, format_iso_weekday_date, local_date_of_iso,
)


def test_format_date_from_date_object():
    assert format_date(datetime.date(2026, 6, 2)) == "02.06.2026"


def test_format_date_from_datetime_object():
    # Nimmt auch datetime (Zeitanteil wird ignoriert) — deutsches TT.MM.JJJJ.
    assert format_date(datetime.datetime(2026, 12, 5, 14, 30)) == "05.12.2026"


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


def test_format_iso_weekday_date_monday():
    # 13.07.2026 ist ein Montag.
    assert format_iso_weekday_date("2026-07-13") == "Montag - 13.07.2026"


def test_format_iso_weekday_date_sunday_from_timestamp():
    # 05.07.2026 ist ein Sonntag; Zeitstempel-Prefix wird akzeptiert.
    assert format_iso_weekday_date("2026-07-05T09:00:00Z") == "Sonntag - 05.07.2026"


def test_format_iso_weekday_date_empty_uses_fallback():
    assert format_iso_weekday_date("", fallback="—") == "—"
    assert format_iso_weekday_date(None, fallback="—") == "—"


def test_format_iso_weekday_date_unparsable_falls_back_to_raw_prefix():
    assert format_iso_weekday_date("2026-13-99") == "2026-13-99"


def test_format_hours_hm_stunden_und_minuten():
    assert format_hours_hm(52.84) == "52 h 50 min"


def test_format_hours_hm_volle_stunde_ohne_minuten():
    assert format_hours_hm(7.0) == "7 h"


def test_format_hours_hm_unter_einer_stunde():
    assert format_hours_hm(0.5) == "30 min"


def test_format_hours_hm_null():
    assert format_hours_hm(0.0) == "0 h"


def test_format_hours_hm_rundet_auf_ganze_minuten():
    # 7.17h = 430.2 Min -> 430 Min, kein "7 h 10.2 min"
    assert format_hours_hm(7.17) == "7 h 10 min"


def test_format_hours_colon_stunden_und_minuten():
    assert format_hours_colon(5.67) == "5:40"


def test_format_hours_colon_volle_stunde_mit_nullminuten():
    # Kompaktform fuellt anders als format_hours_hm immer auf H:MM auf —
    # die Kachel-Spalte soll nicht je nach Tag springen.
    assert format_hours_colon(7.0) == "7:00"


def test_format_hours_colon_unter_einer_stunde():
    assert format_hours_colon(0.5) == "0:30"


def test_format_hours_colon_null():
    assert format_hours_colon(0.0) == "0:00"


# --- local_date_of_iso: UTC-Zeitstempel → lokales Kalenderdatum -------------

def test_local_date_of_iso_converts_utc_to_local():
    # 23:30 UTC ist in einer Zone mit positivem Offset bereits der Folgetag.
    # Fester Offset statt der echten Systemzone: der Test muss überall gelten.
    tz = datetime.timezone(datetime.timedelta(hours=2))
    assert local_date_of_iso("2026-09-11T23:30:00Z", tz=tz) == datetime.date(2026, 9, 12)


def test_local_date_of_iso_keeps_same_day_when_no_rollover():
    tz = datetime.timezone(datetime.timedelta(hours=2))
    assert local_date_of_iso("2026-09-12T08:00:00Z", tz=tz) == datetime.date(2026, 9, 12)


def test_local_date_of_iso_accepts_offset_suffix():
    tz = datetime.timezone(datetime.timedelta(hours=2))
    assert local_date_of_iso("2026-09-11T23:30:00+00:00", tz=tz) == datetime.date(2026, 9, 12)


def test_local_date_of_iso_plain_date_is_taken_as_is():
    # Ein reines Datum trägt keine Uhrzeit — es umzurechnen wäre geraten.
    tz = datetime.timezone(datetime.timedelta(hours=-8))
    assert local_date_of_iso("2026-09-12", tz=tz) == datetime.date(2026, 9, 12)


def test_local_date_of_iso_naive_timestamp_is_treated_as_utc():
    # Alt-Werte ohne Z-Suffix: der Store schrieb immer UTC.
    tz = datetime.timezone(datetime.timedelta(hours=2))
    assert local_date_of_iso("2026-09-11T23:30:00", tz=tz) == datetime.date(2026, 9, 12)


def test_local_date_of_iso_empty_is_none():
    assert local_date_of_iso("") is None
    assert local_date_of_iso(None) is None


def test_local_date_of_iso_unparsable_is_none():
    assert local_date_of_iso("kein-datum") is None
