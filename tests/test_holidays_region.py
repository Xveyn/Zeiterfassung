import time
from datetime import date

import holidays

from src.holidays_region import (
    REGIONS, _holidays_cached, get_holidays, normalize_region, region_label,
)

STATES = REGIONS["DE"]


def test_states_list_starts_with_empty_option():
    assert STATES[0] == ("", "— kein Bundesland —")


def test_states_list_contains_all_16_bundeslaender():
    codes = {code for code, _ in STATES if code}
    expected = {
        "BW", "BY", "BE", "BB", "HB", "HH", "HE", "MV",
        "NI", "NW", "RP", "SL", "SN", "ST", "SH", "TH",
    }
    assert codes == expected


def test_empty_state_returns_empty_dict():
    assert get_holidays("DE", "", 2026) == {}


def test_invalid_state_returns_empty_dict():
    assert get_holidays("DE", "XX", 2026) == {}


def test_bayern_has_heilige_drei_koenige():
    h = get_holidays("DE", "BY", 2026)
    assert date(2026, 1, 6) in h


def test_berlin_has_frauentag_but_not_heilige_drei_koenige():
    h = get_holidays("DE", "BE", 2026)
    assert date(2026, 3, 8) in h
    assert date(2026, 1, 6) not in h


def test_tag_der_deutschen_einheit_in_every_state():
    for code, _ in STATES:
        if not code:
            continue
        assert date(2026, 10, 3) in get_holidays("DE", code, 2026)


def test_holiday_names_are_german():
    h = get_holidays("DE", "BY", 2026)
    assert h[date(2026, 10, 3)] == "Tag der Deutschen Einheit"
    assert h[date(2026, 1, 6)] == "Heilige Drei Könige"


def test_returned_dict_is_independent_copy():
    h1 = get_holidays("DE", "BY", 2026)
    h1[date(2099, 1, 1)] = "MUTATION"
    h2 = get_holidays("DE", "BY", 2026)
    assert date(2099, 1, 1) not in h2


def test_get_holidays_matches_germany_for_every_region():
    for code, _ in REGIONS["DE"]:
        if not code:
            continue
        assert get_holidays("DE", code, 2026) == dict(
            holidays.Germany(subdiv=code, years=2026, language="de"))


def test_empty_or_unknown_region_gives_no_holidays():
    assert get_holidays("DE", "", 2026) == {}
    assert get_holidays("DE", "XX", 2026) == {}
    assert get_holidays("FR", "BY", 2026) == {}


def test_normalize_region():
    assert normalize_region("DE", "BY") == "BY"
    assert normalize_region("DE", "XX") == ""
    assert normalize_region("DE", None) == ""
    assert normalize_region("DE", 5) == ""


def test_region_label():
    assert region_label("DE", "BY") == "Bayern"
    assert region_label("DE", "") == "— kein Bundesland —"
    assert region_label("FR", "BY") == ""


# --- Resilienz gegen transiente OSError (#116, gettext-Race im
# Onefile-Build beim Neustart für UI-Skalierung) ---


def test_oserror_retry_still_applies(monkeypatch):
    _holidays_cached.cache_clear()
    monkeypatch.setattr(time, "sleep", lambda s: None)

    real = holidays.country_holidays
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise FileNotFoundError(
                "No translation file found for domain: 'DE'")
        return real(*args, **kwargs)

    monkeypatch.setattr(holidays, "country_holidays", flaky)

    h = get_holidays("DE", "BY", 2031)

    assert calls["n"] == 3
    assert date(2031, 10, 3) in h


def test_persistent_failure_falls_back_to_empty_dict(monkeypatch):
    _holidays_cached.cache_clear()
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def always_fails(*args, **kwargs):
        raise OSError("No translation file found for domain: 'DE'")

    monkeypatch.setattr(holidays, "country_holidays", always_fails)

    assert get_holidays("DE", "BY", 2032) == {}
    _holidays_cached.cache_clear()
