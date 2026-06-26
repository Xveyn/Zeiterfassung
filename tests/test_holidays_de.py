from datetime import date

from src.holidays_de import STATES, get_holidays


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
    assert get_holidays("", 2026) == {}


def test_invalid_state_returns_empty_dict():
    assert get_holidays("XX", 2026) == {}


def test_bayern_has_heilige_drei_koenige():
    h = get_holidays("BY", 2026)
    assert date(2026, 1, 6) in h


def test_berlin_has_frauentag_but_not_heilige_drei_koenige():
    h = get_holidays("BE", 2026)
    assert date(2026, 3, 8) in h
    assert date(2026, 1, 6) not in h


def test_tag_der_deutschen_einheit_in_every_state():
    for code, _ in STATES:
        if not code:
            continue
        assert date(2026, 10, 3) in get_holidays(code, 2026)


def test_holiday_names_are_german():
    h = get_holidays("BY", 2026)
    assert h[date(2026, 10, 3)] == "Tag der Deutschen Einheit"
    assert h[date(2026, 1, 6)] == "Heilige Drei Könige"


def test_returned_dict_is_independent_copy():
    h1 = get_holidays("BY", 2026)
    h1[date(2099, 1, 1)] = "MUTATION"
    h2 = get_holidays("BY", 2026)
    assert date(2099, 1, 1) not in h2


# --- code_for_state_label (Issue #51: extrahiert aus settings_dialog) ---


def test_code_for_state_label_known():
    from src.holidays_de import code_for_state_label
    assert code_for_state_label("Bayern") == "BY"


def test_code_for_state_label_empty_option_maps_to_empty_code():
    from src.holidays_de import code_for_state_label
    assert code_for_state_label("— kein Bundesland —") == ""


def test_code_for_state_label_unknown_label_is_empty():
    from src.holidays_de import code_for_state_label
    assert code_for_state_label("Atlantis") == ""
