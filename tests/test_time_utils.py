import datetime

import pytest

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


# --- Zeitpunkte in Ortszeit (#534) -------------------------------------------
#
# Zeitpunkte (`…Z`, `±HH:MM`) werden zur Anzeige in die Ortszeit umgerechnet, Kalendertage nie.
# Feste Offsets statt der Systemzone: die Tests müssen überall gelten.

CET = datetime.timezone(datetime.timedelta(hours=1))
CEST = datetime.timezone(datetime.timedelta(hours=2))
PST = datetime.timezone(datetime.timedelta(hours=-8))


def _berlin():
    zoneinfo = pytest.importorskip("zoneinfo")
    try:
        return zoneinfo.ZoneInfo("Europe/Berlin")
    except zoneinfo.ZoneInfoNotFoundError:
        pytest.skip("keine Zeitzonendaten")


def test_format_iso_datetime_shows_local_time():
    # Das Beispiel aus #534: um 18:45 MEZ gespeichert, als 17:45 UTC abgelegt.
    assert format_iso_datetime("2026-11-25T17:45:00Z", tz=CET) == "25.11.2026 18:45"


def test_format_iso_datetime_follows_summer_and_winter_time():
    berlin = _berlin()
    assert format_iso_datetime("2026-06-02T14:30:00Z", tz=berlin) == "02.06.2026 16:30"
    assert format_iso_datetime("2026-11-25T17:45:00Z", tz=berlin) == "25.11.2026 18:45"


def test_format_iso_datetime_moves_the_date_across_midnight():
    assert format_iso_datetime("2026-11-25T23:30:00Z", tz=CET) == "26.11.2026 00:30"
    assert format_iso_datetime("2026-11-26T05:00:00Z", tz=PST) == "25.11.2026 21:00"


def test_format_iso_datetime_accepts_an_offset_instead_of_z():
    assert format_iso_datetime("2026-11-25T23:30:00+00:00", tz=CET) == "26.11.2026 00:30"
    assert format_iso_datetime("2026-11-26T00:30:00+01:00", tz=datetime.timezone.utc) == "25.11.2026 23:30"


def test_a_timestamp_without_zone_counts_as_utc():
    # Wie `local_date_of_iso`: alle eigenen Schreiber setzen `Z`, ein Wert ohne Zone kommt nur aus
    # Fremddaten, und das Modul hat für Zeitpunkte genau eine Regel.
    assert format_iso_datetime("2026-11-25T23:30:00", tz=CET) == "26.11.2026 00:30"
    assert format_iso_datetime("2026-11-25 23:30:00", tz=CET) == "26.11.2026 00:30"


def test_format_iso_date_of_a_timestamp_is_the_local_date():
    assert format_iso_date("2026-11-25T23:30:00Z", tz=CET) == "26.11.2026"
    assert format_iso_weekday_date("2026-07-12T23:30:00Z", tz=CEST) == "Montag - 13.07.2026"


def test_a_calendar_day_is_never_shifted():
    # Ein Kalendertag trägt keine Uhrzeit: der Tag, an dem gearbeitet wurde, bleibt dieser Tag.
    assert format_iso_date("2026-06-02", tz=PST) == "02.06.2026"
    assert format_iso_datetime("2026-06-02", tz=PST) == "02.06.2026"
    assert format_iso_weekday_date("2026-07-13", tz=PST) == "Montag - 13.07.2026"
    assert local_date_of_iso("2026-06-02", tz=PST) == datetime.date(2026, 6, 2)


def test_without_tz_the_display_zone_is_used(monkeypatch):
    monkeypatch.setattr("src.time_utils.local_zone", lambda: CET)
    assert format_iso_datetime("2026-11-25T17:45:00Z") == "25.11.2026 18:45"
    assert format_iso_date("2026-11-25T23:30:00Z") == "26.11.2026"
    assert local_date_of_iso("2026-11-25T23:30:00Z") == datetime.date(2026, 11, 26)


def test_the_display_zone_is_the_system_zone(system_zone):
    from src import time_utils
    assert time_utils.local_zone() is None          # `astimezone(None)` nimmt die Zone des Systems


def test_unconvertible_timestamps_fall_back_to_the_raw_text():
    # Fremddaten: am Rand des Datumsbereichs scheitert die Umrechnung; angezeigt wird dann roh,
    # geworfen wird nie.
    # (Das Jahr 1 schreibt `strftime` plattformabhängig ohne führende Nullen, deshalb nur das Ende.)
    assert format_iso_datetime("0001-01-01T00:30:00Z", tz=PST).endswith(" 00:30")
    assert format_iso_date("9999-12-31T23:30:00Z", tz=CEST) == "31.12.9999"
    assert format_iso_datetime("2026-13-99T25:99:00Z", tz=CET) == "2026-13-99 25:99"
    assert local_date_of_iso("0001-01-01T00:30:00Z", tz=PST) is None


def test_the_system_zone_never_raises_on_extreme_timestamps(system_zone):
    # `astimezone(None)` fragt die Zone des Systems (`time.localtime`); unter Windows wirft das vor
    # 1970 und nach 3000 `OSError`. Fremddaten (Sync-Doc, Teilen-Datei) dürfen die Anzeige nicht sprengen.
    for stamp in ("1969-07-20T20:17:00Z", "3001-01-01T00:00:00Z", "2026-11-25T17:45:00Z"):
        assert isinstance(format_iso_datetime(stamp), str)
        assert isinstance(format_iso_date(stamp), str)
        assert isinstance(format_iso_weekday_date(stamp), str)
        local_date_of_iso(stamp)


def test_non_strings_give_the_fallback_instead_of_raising():
    for value in (12345678901, 3.5, {"a": 1}, ["2026-06-02"], b"2026-06-02T14:30:00Z"):
        assert format_iso_datetime(value, fallback="?") == "?"        # type: ignore[arg-type]
        assert format_iso_date(value, fallback="?") == "?"            # type: ignore[arg-type]
        assert format_iso_weekday_date(value, fallback="?") == "?"    # type: ignore[arg-type]
        assert local_date_of_iso(value) is None                       # type: ignore[arg-type]


def test_a_lowercase_z_is_utc_as_well():
    assert format_iso_datetime("2026-11-25T23:30:00z", tz=CET) == "26.11.2026 00:30"
