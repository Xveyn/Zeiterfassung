"""Pure Logik der Standardzeiten-Darstellung (Allgemein / Tageweise)."""

from src import default_times as dt
from src.settings import DEFAULTS, WEEKDAY_KEYS


def _days(value):
    return {k: value for k in WEEKDAY_KEYS}


def test_default_mode_is_unset_so_the_tab_infers_it():
    assert DEFAULTS["default_times_mode"] == ""


def test_mode_label_code_roundtrip():
    for code in (dt.MODE_GENERAL, dt.MODE_PER_DAY):
        assert dt.mode_code(dt.mode_label(code)) == code


def test_unknown_label_is_per_day_so_no_day_values_are_dropped():
    assert dt.mode_code("???") == dt.MODE_PER_DAY


def test_days_differ():
    assert not dt.days_differ(_days("08:00"), _days("16:00"))
    assert dt.days_differ({**_days("08:00"), "fri": "07:00"}, _days("16:00"))
    assert dt.days_differ(_days("08:00"), {**_days("16:00"), "sun": "12:00"})


def test_resolve_mode_prefers_a_valid_stored_value():
    # Auch wenn die Tage gleich sind: wer Tageweise gewählt hat, behält es.
    assert dt.resolve_mode("per_day", _days("08:00"), _days("16:00")) == "per_day"
    assert dt.resolve_mode("general", {**_days("08:00"), "fri": "07:00"},
                           _days("16:00")) == "general"


def test_resolve_mode_infers_when_unset_or_invalid():
    equal = (_days("08:00"), _days("16:00"))
    varied = ({**_days("08:00"), "fri": "07:00"}, _days("16:00"))
    for stored in ("", None, "bogus", 3):
        assert dt.resolve_mode(stored, *equal) == "general"
        assert dt.resolve_mode(stored, *varied) == "per_day"


def test_general_from_days_takes_monday():
    starts = {**_days("08:00"), "mon": "06:30"}
    ends = {**_days("16:00"), "mon": "14:30"}
    assert dt.general_from_days(starts, ends) == ("06:30", "14:30")


def test_days_for_per_day_copies_general_when_all_days_equal():
    starts, ends = dt.days_for_per_day(_days("08:00"), _days("16:00"),
                                       "09:00", "17:00")
    assert starts == _days("09:00")
    assert ends == _days("17:00")


def test_days_for_per_day_keeps_differing_days():
    # Hin- und Herschalten vor dem Speichern darf keine Tageswerte kosten.
    start_in = {**_days("08:00"), "tue": "10:00"}
    starts, ends = dt.days_for_per_day(start_in, _days("16:00"), "09:00", "17:00")
    assert starts == start_in
    assert ends == _days("16:00")
    assert starts is not start_in


def test_spread_writes_all_fourteen_keys():
    out = dt.spread("09:00", "17:30")
    assert len(out) == 14
    for key in WEEKDAY_KEYS:
        assert out[f"default_start_{key}"] == "09:00"
        assert out[f"default_end_{key}"] == "17:30"
