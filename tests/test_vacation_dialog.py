"""Tk-freie Planungslogik des Urlaubs-Dialogs (M16: Verhalten gehört in pure
Funktionen, nicht ins Widget)."""

import pytest

from src.dialogs.vacation_dialog import (
    _format_day_list, blocking_days, parse_hours, plan_vacation_save,
    prune_overrides,
)


def test_plan_rejects_empty_name():
    result = plan_vacation_save("", "2026-07-01", "2026-07-03",
                                "per_day", 8.0, {}, "")
    assert result["error"] == "Bitte einen Namen für den Urlaub eingeben."


def test_plan_rejects_reversed_range():
    result = plan_vacation_save("Sommer", "2026-07-10", "2026-07-01",
                                "per_day", 8.0, {}, "")
    assert result["error"] == "Das Bis-Datum liegt vor dem Von-Datum."


def test_plan_rejects_negative_hours():
    result = plan_vacation_save("Sommer", "2026-07-01", "2026-07-03",
                                "per_day", -1.0, {}, "")
    assert result["error"] == "Die Stundenzahl darf nicht negativ sein."


def test_plan_per_day_fills_workdays():
    result = plan_vacation_save("Sommer", "2026-07-01", "2026-07-05",
                                "per_day", 8.0, {}, "")
    assert result["error"] is None
    # Mi 01. bis Fr 03. je 480, Sa 04./So 05. auf 0.
    assert result["days"] == {
        "2026-07-01": 480, "2026-07-02": 480, "2026-07-03": 480,
        "2026-07-04": 0, "2026-07-05": 0,
    }


def test_plan_total_distributes_over_workdays_only():
    # 20 h auf die drei Werktage → 400 min je Tag, Wochenende bleibt 0.
    result = plan_vacation_save("Sommer", "2026-07-01", "2026-07-05",
                                "total", 20.0, {}, "")
    assert result["days"] == {
        "2026-07-01": 400, "2026-07-02": 400, "2026-07-03": 400,
        "2026-07-04": 0, "2026-07-05": 0,
    }
    assert sum(result["days"].values()) == 1200


def test_plan_total_remainder_never_gets_lost():
    result = plan_vacation_save("Sommer", "2026-07-01", "2026-07-03",
                                "total", 10.0, {}, "")
    assert sum(result["days"].values()) == 600


def test_plan_total_without_workdays_is_an_error():
    # Reines Wochenende: es gibt keinen Tag, auf den verteilt werden könnte.
    result = plan_vacation_save("Sommer", "2026-07-04", "2026-07-05",
                                "total", 10.0, {}, "")
    assert result["error"] == (
        "Im Zeitraum liegt kein Arbeitstag, auf den die Stunden verteilt "
        "werden könnten."
    )


def test_plan_overrides_win():
    result = plan_vacation_save("Sommer", "2026-07-01", "2026-07-03",
                                "per_day", 8.0, {"2026-07-02": 240}, "")
    assert result["days"]["2026-07-02"] == 240
    assert result["days"]["2026-07-01"] == 480


def test_plan_overrides_outside_range_are_ignored():
    result = plan_vacation_save("Sommer", "2026-07-01", "2026-07-02",
                                "per_day", 8.0, {"2026-09-09": 999}, "")
    assert "2026-09-09" not in result["days"]


def test_plan_honours_state_holidays():
    result = plan_vacation_save("Neujahr", "2026-01-01", "2026-01-02",
                                "per_day", 8.0, {}, "BY")
    assert result["days"]["2026-01-01"] == 0
    assert result["days"]["2026-01-02"] == 480


# ------------------------------------------------- Rueckrechnung Sammelwert

def test_dominant_minutes_finds_the_common_day_length():
    from src.dialogs.vacation_dialog import _dominant_minutes
    assert _dominant_minutes(
        {"a": 360, "b": 360, "c": 360, "d": 0, "e": 240}) == 360


def test_dominant_minutes_ignores_zero_days():
    from src.dialogs.vacation_dialog import _dominant_minutes
    assert _dominant_minutes({"a": 0, "b": 0}) == 0
    assert _dominant_minutes({}) == 0


def test_dominant_minutes_breaks_ties_deterministically():
    from src.dialogs.vacation_dialog import _dominant_minutes
    assert _dominant_minutes({"a": 240, "b": 480}) == 480


def test_format_hours_uses_german_decimal_comma():
    from src.dialogs.vacation_dialog import _format_hours
    assert _format_hours(480) == "8,00"
    assert _format_hours(390) == "6,50"
    assert _format_hours(0) == "0,00"


# ---------------------------------------------------------- _format_day_list

def test_format_day_list_renders_german_dates():
    assert _format_day_list(["2026-07-01", "2026-07-02"]) == (
        "01.07.2026" + chr(10) + "02.07.2026")


def test_format_day_list_truncates_long_lists():
    days = [f"2026-07-{d:02d}" for d in range(1, 15)]
    lines = _format_day_list(days, limit=3).split(chr(10))
    assert lines[:3] == ["01.07.2026", "02.07.2026", "03.07.2026"]
    assert lines[3] == "… und 11 weitere"


def test_format_day_list_without_truncation_has_no_suffix():
    assert "weitere" not in _format_day_list(["2026-07-01"], limit=3)


# --------------------------------------------------- Obergrenze / Zahleneingabe

def test_plan_rejects_more_than_24_hours_per_day():
    result = plan_vacation_save("Test", "2026-09-01", "2026-09-30",
                                "per_day", 48.0, {}, "")
    assert result["error"] == "Mehr als 24 Stunden pro Tag gibt es nicht."
    assert result["days"] == {}


def test_plan_accepts_exactly_24_hours_per_day():
    result = plan_vacation_save("Test", "2026-09-01", "2026-09-02",
                                "per_day", 24.0, {}, "")
    assert result["error"] is None
    assert result["days"]["2026-09-01"] == 1440


def test_plan_rejects_total_that_exceeds_24_hours_per_workday():
    # 01.-30.09.2026 hat 22 Arbeitstage; 1056 h waeren 48 h pro Tag.
    result = plan_vacation_save("Test", "2026-09-01", "2026-09-30",
                                "total", 1056.0, {}, "")
    assert "22 Arbeitstage" in result["error"]
    assert "24 Stunden pro Arbeitstag" in result["error"]
    assert result["days"] == {}


def test_plan_rejects_an_override_above_24_hours():
    result = plan_vacation_save("Test", "2026-09-01", "2026-09-03",
                                "per_day", 8.0, {"2026-09-02": 1500}, "")
    assert "02.09.2026" in result["error"]
    assert result["days"] == {}


def test_plan_rejects_a_non_numeric_value():
    result = plan_vacation_save("Test", "2026-09-01", "2026-09-03",
                                "per_day", None, {}, "")
    assert result["error"] == "Bitte eine Zahl in das Stundenfeld eingeben."
    assert result["days"] == {}


# --- R13: was bisher nur in den Closures von _open_edit_dialog stand -------


@pytest.mark.parametrize("text, expected", [
    ("8", 8.0),
    ("7,5", 7.5),
    ("7.5", 7.5),
    ("", 0.0),          # leeres Feld zählt als 0, nicht als Fehler
    ("abc", None),      # keine Zahl -> None, kein Sentinel wie -1
    ("-2", -2.0),       # das Vorzeichen bewertet plan_vacation_save
])
def test_parse_hours(text, expected):
    assert parse_hours(text) == expected


def test_prune_overrides_drops_days_outside_a_valid_plan():
    overrides = {"2026-08-03": 240, "2026-08-12": 120}
    plan = {"error": None, "days": {"2026-08-03": 480, "2026-08-04": 480}}

    assert prune_overrides(overrides, plan) == {"2026-08-03": 240}


def test_prune_overrides_keeps_everything_while_the_plan_is_invalid():
    """Wer „48" ins Stundenfeld tippt und danach das Datum korrigiert, darf
    seine von Hand gesetzten Tage nicht verlieren: ein Fehler-Plan hat leere
    `days`, gemessen daran läge jede Überschreibung „außerhalb"."""
    overrides = {"2026-08-03": 240, "2026-08-12": 120}
    plan = {"error": "Mehr als 24 Stunden pro Tag gibt es nicht.", "days": {}}

    assert prune_overrides(overrides, plan) == overrides


def test_prune_overrides_returns_a_new_dict():
    overrides = {"2026-08-12": 120}

    prune_overrides(overrides, {"error": None, "days": {}})

    assert overrides == {"2026-08-12": 120}


_DAYS = {"2026-10-05": 480, "2026-10-06": 480, "2026-10-10": 0}
_WITH_SLOT = {"slots": [{"start": "09:00", "end": "10:00"}]}


def test_blocking_days_counts_work_time_with_slots():
    entries = {"2026-10-05": _WITH_SLOT, "2026-10-06": {"slots": []}}

    assert blocking_days(_DAYS, entries, None, calendar_active=False) == ["2026-10-05"]


def test_blocking_days_ignores_zero_minute_days():
    """Ein Samstag mitten im Urlaub trägt 0 Minuten — wer dort arbeitet,
    blockiert den Urlaub nicht."""
    entries = {"2026-10-10": _WITH_SLOT}

    assert blocking_days(_DAYS, entries, None, calendar_active=False) == []


@pytest.mark.parametrize("calendar_active, expected", [
    (False, []),                # unsichtbare Reservierung: keine Sackgasse
    (True, ["2026-10-06"]),
])
def test_blocking_days_counts_reservations_only_with_active_calendar(
        calendar_active, expected):
    reservations = {"2026-10-06": _WITH_SLOT}

    assert blocking_days(_DAYS, None, reservations, calendar_active) == expected
