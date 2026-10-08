# tests/test_api_summary.py
import datetime
import logging

import pytest

from src.api_summary import (
    category_names, holidays_for, parse_month, parse_week, parse_year, summarize,
)
from src.weekly_limit import week_ist_minutes
from tests.conftest import ist_slot

D = datetime.date
JAN = (D(2026, 1, 1), D(2026, 1, 31))


# --- Pfad-Parser ------------------------------------------------------------------

def test_parse_month_gives_first_and_last_day():
    assert parse_month("2026-02") == (D(2026, 2, 1), D(2026, 2, 28))
    assert parse_month("2024-02") == (D(2024, 2, 1), D(2024, 2, 29))
    assert parse_month("2026-12") == (D(2026, 12, 1), D(2026, 12, 31))


@pytest.mark.parametrize("raw", [
    "2026-13", "2026-00", "2026-1", "26-01", "2026-01-01", " 2026-01", "2026-01 ",
    "٢٠٢٦-٠١", "0000-01", "9999-01", "", "2026/01",
])
def test_parse_month_rejects_bad_input(raw):
    assert parse_month(raw) is None


def test_parse_week_gives_monday_and_sunday():
    assert parse_week("2026-W01") == (D(2025, 12, 29), D(2026, 1, 4))
    assert parse_week("2026-W53") == (D(2026, 12, 28), D(2027, 1, 3))   # 2026 hat 53 Wochen


@pytest.mark.parametrize("raw", [
    "2025-W53", "2026-W00", "2026-W54", "2026-w01", "2026-W1", "2026W01",
    "2026-W01-1", "٢٠٢٦-W01", "0000-W01", "9999-W01", "",
])
def test_parse_week_rejects_bad_input(raw):
    assert parse_week(raw) is None


def test_parse_year():
    assert parse_year("2026") == 2026
    for raw in ("26", "20260", "٢٠٢٦", " 2026", "2026 ", ""):
        assert parse_year(raw) is None


# --- Kategorien und Feiertage ---------------------------------------------------------

def test_category_names_keeps_order_and_drops_junk():
    settings = {"categories": ["Projekt", "", "  ", "Büro", "Projekt", 5, None]}
    assert category_names(settings) == ["Projekt", "Büro"]


@pytest.mark.parametrize("value", [None, "Projekt", 5, {"a": 1}])
def test_category_names_tolerates_a_non_list(value):
    assert category_names({"categories": value}) == []
    assert category_names({}) == []


def test_holidays_for_a_state_are_sorted_with_german_names():
    result = holidays_for({"state": "BY"}, 2026)
    dates = [h["date"] for h in result["holidays"]]
    assert result["year"] == 2026 and result["state"] == "BY"
    assert dates == sorted(dates)
    assert {"date": "2026-01-01", "name": "Neujahr"} in result["holidays"]
    assert "2026-01-06" in dates                       # Heilige Drei Könige gilt in Bayern
    assert "2026-11-01" in dates                       # Allerheiligen


def test_holidays_differ_by_state():
    bayern = {h["date"] for h in holidays_for({"state": "BY"}, 2026)["holidays"]}
    berlin = {h["date"] for h in holidays_for({"state": "BE"}, 2026)["holidays"]}
    assert "2026-01-06" in bayern and "2026-01-06" not in berlin


@pytest.mark.parametrize("settings", [{}, {"state": ""}, {"state": None}, {"state": 5},
                                      {"state": "XX"}])
def test_holidays_without_a_valid_state_are_empty(settings):
    result = holidays_for(settings, 2026)
    assert result["holidays"] == []
    assert result["state"] in ("", "XX")


def day(*slots):
    return {"slots": list(slots)}


def run(entries, settings=None, vacation=None, span=JAN):
    return summarize(span[0], span[1], entries, {} if settings is None else settings,
                     {} if vacation is None else vacation)


# --- Summen -------------------------------------------------------------------------------

def test_totals_days_and_range_are_in_whole_minutes():
    entries = {
        "2026-01-05": day(ist_slot("08:00", "12:00", 0, "Projekt")),
        "2026-01-20": day(ist_slot("09:00", "17:00", 30, "Büro")),
        "2026-02-03": day(ist_slot("10:00", "11:00")),                 # außerhalb
    }

    result = run(entries)

    assert (result["from"], result["to"]) == ("2026-01-01", "2026-01-31")
    assert result["total_minutes"] == 240 + 450
    assert result["days"] == [
        {"date": "2026-01-05", "minutes": 240, "slots": 1},
        {"date": "2026-01-20", "minutes": 450, "slots": 1},
    ]


def test_range_bounds_are_inclusive():
    entries = {"2026-01-01": day(ist_slot("08:00", "09:00")),
               "2026-01-31": day(ist_slot("08:00", "09:00")),
               "2025-12-31": day(ist_slot("08:00", "09:00")),
               "2026-02-01": day(ist_slot("08:00", "09:00"))}
    assert [d["date"] for d in run(entries)["days"]] == ["2026-01-01", "2026-01-31"]


def test_sum_is_over_minutes_not_rounded_decimal_hours():
    # 100 + 100 + 160 Minuten: als Dezimalstunden je Slot gerundet ergäbe das 6,01 h
    entries = {"2026-01-05": day(ist_slot("08:00", "09:40"), ist_slot("10:00", "11:40"),
                                 ist_slot("12:00", "14:40"))}
    result = run(entries)
    assert result["total_minutes"] == 360
    assert result["days"][0] == {"date": "2026-01-05", "minutes": 360, "slots": 3}


def test_a_day_without_slots_is_left_out():
    result = run({"2026-01-05": {"slots": []}, "2026-01-06": day(ist_slot("08:00", "09:00"))})
    assert [d["date"] for d in result["days"]] == ["2026-01-06"]


def test_empty_store_gives_zeroes():
    result = run({})
    assert result["total_minutes"] == 0 and result["days"] == []
    assert result["by_category"] == [] and result["pause_warnings"] == []
    assert result["vacation_minutes"] == 0 and result["payable_minutes"] == 0


def test_keys_that_are_not_days_are_ignored():
    entries = {"kaputt": day(ist_slot("08:00", "09:00")),
               "20260105": day(ist_slot("08:00", "09:00")),
               "2026-01-05": day(ist_slot("08:00", "09:00"))}
    assert [d["date"] for d in run(entries)["days"]] == ["2026-01-05"]


def test_inputs_are_not_mutated():
    entries = {"2026-01-05": day(ist_slot("08:00", "12:00", 0, "A"))}
    vacation = {"2026-01-06": 480}
    before = (repr(entries), repr(vacation))
    run(entries, vacation=vacation)
    assert (repr(entries), repr(vacation)) == before


# --- Kategorien ---------------------------------------------------------------------------

def test_by_category_is_sorted_by_minutes_then_name_and_keeps_the_empty_one():
    entries = {"2026-01-05": day(
        ist_slot("08:00", "09:00", 0, "Büro"), ist_slot("09:00", "12:00", 0, "Projekt"),
        ist_slot("12:00", "13:00", 0, "Abwesend"), ist_slot("13:00", "14:00"))}
    assert run(entries)["by_category"] == [
        {"kategorie": "Projekt", "minutes": 180},
        {"kategorie": "Abwesend", "minutes": 60},
        {"kategorie": "Büro", "minutes": 60},
        {"kategorie": "", "minutes": 60},
    ]


def test_by_category_adds_up_across_days_and_equals_the_total():
    entries = {"2026-01-05": day(ist_slot("08:00", "10:00", 0, "A")),
               "2026-01-06": day(ist_slot("08:00", "09:30", 0, "A"), ist_slot("10:00", "11:00", 0, "B"))}
    result = run(entries)
    assert {c["kategorie"]: c["minutes"] for c in result["by_category"]} == {"A": 210, "B": 60}
    assert sum(c["minutes"] for c in result["by_category"]) == result["total_minutes"]


def test_a_non_string_category_counts_as_uncategorised():
    entries = {"2026-01-05": day({"start": "08:00", "end": "09:00", "pause": 0, "kategorie": 5})}
    assert run(entries)["by_category"] == [{"kategorie": "", "minutes": 60}]


# --- Wochen und Wochenlimit ------------------------------------------------------------------

def test_weeks_lists_every_iso_week_the_range_touches():
    weeks = run({})["weeks"]
    assert [(w["iso_year"], w["iso_week"]) for w in weeks] == [
        (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5)]


def test_a_week_total_covers_the_whole_week_not_only_the_range():
    # 2025-12-30 liegt in KW 1 (29.12.–04.01.), aber nicht im Januar
    entries = {"2025-12-30": day(ist_slot("08:00", "10:00")),
               "2026-01-05": day(ist_slot("08:00", "09:00"))}

    result = run(entries)

    assert result["total_minutes"] == 60
    assert result["weeks"][0]["total_minutes"] == 120
    assert result["weeks"][1]["total_minutes"] == 60


def test_week_total_equals_the_weekly_limit_module():
    entries = {"2026-01-05": day(ist_slot("08:00", "09:40"), ist_slot("10:00", "11:40")),
               "2026-01-07": day(ist_slot("12:00", "14:40")),
               "2026-01-09": day(ist_slot("08:00", "13:00", 30))}
    result = run(entries)
    assert result["weeks"][1]["total_minutes"] == week_ist_minutes(entries, 2026, 2)


LIMIT = {"werkstudent_limit_enabled": True, "werkstudent_limit_start": "2026-01-01",
         "werkstudent_limit_end": "2026-12-31", "werkstudent_limit_max_hours": 20.0}


def test_limit_is_off_by_default():
    for week in run({"2026-01-05": day(ist_slot("08:00", "20:00"))})["weeks"]:
        assert week["limit_minutes"] is None and week["exceeded"] is False


def test_exceeding_the_limit_is_flagged_exactly_above_it():
    exactly = {"2026-01-05": day(ist_slot("08:00", "20:00")),                     # 12 h
               "2026-01-06": day(ist_slot("08:00", "16:00"))}                     # + 8 h = 20 h
    over = dict(exactly, **{"2026-01-07": day(ist_slot("08:00", "08:01"))})

    week = run(exactly, LIMIT)["weeks"][1]
    assert (week["limit_minutes"], week["total_minutes"], week["exceeded"]) == (1200, 1200, False)

    week = run(over, LIMIT)["weeks"][1]
    assert (week["total_minutes"], week["exceeded"]) == (1201, True)


def test_the_limit_applies_only_to_weeks_inside_its_period():
    settings = dict(LIMIT, werkstudent_limit_start="2026-01-12", werkstudent_limit_end="2026-01-18")
    limits = [w["limit_minutes"] for w in run({}, settings)["weeks"]]
    assert limits == [None, None, 1200, None, None]


def test_an_unreadable_limit_drops_the_limit_and_logs(caplog):
    with caplog.at_level(logging.WARNING, logger="src.api_summary"):
        result = run({"2026-01-05": day(ist_slot("08:00", "20:00"))},
                     dict(LIMIT, werkstudent_limit_max_hours=None))
    assert all(w["limit_minutes"] is None and not w["exceeded"] for w in result["weeks"])
    assert "Wochenlimit" in caplog.text


# --- Pausenpflicht -------------------------------------------------------------------------------

def test_pause_warning_names_the_day_and_the_numbers():
    entries = {"2026-01-06": day(ist_slot("08:00", "15:00", 0)),                    # 7 h ohne Pause
               "2026-01-05": day(ist_slot("08:00", "16:00", 30)),                   # 7,5 h, 30 Min: ok
               "2026-01-07": day(ist_slot("08:00", "19:00", 30))}                   # 10,5 h, 30 < 45
    result = run(entries, {"pause_warning_enabled": True})
    assert result["pause_warnings"] == [
        {"date": "2026-01-06", "worked_minutes": 420, "actual_pause_minutes": 0,
         "required_pause_minutes": 30},
        {"date": "2026-01-07", "worked_minutes": 630, "actual_pause_minutes": 30,
         "required_pause_minutes": 45},
    ]


def test_exactly_six_hours_needs_no_pause():
    entries = {"2026-01-06": day(ist_slot("08:00", "14:00", 0))}
    assert run(entries, {"pause_warning_enabled": True})["pause_warnings"] == []


def test_pause_warnings_follow_the_setting():
    entries = {"2026-01-06": day(ist_slot("08:00", "15:00", 0))}
    assert run(entries, {"pause_warning_enabled": False})["pause_warnings"] == []
    assert run(entries, {})["pause_warnings"] == []


# --- Urlaub ----------------------------------------------------------------------------------------

def test_without_vacation_payable_equals_total():
    result = run({"2026-01-05": day(ist_slot("08:00", "12:00"))})
    assert (result["vacation_minutes"], result["payable_minutes"]) == (0, 240)
    assert result["vacation_capped_days"] == []


def test_vacation_in_range_is_added_to_payable_but_not_to_total():
    entries = {"2026-01-05": day(ist_slot("08:00", "12:00"))}
    vacation = {"2026-01-12": 480, "2026-01-13": 480, "2026-01-17": 0,
                "2025-12-31": 480, "2026-02-02": 480}                        # die letzten zwei außerhalb

    result = run(entries, vacation=vacation)

    assert result["total_minutes"] == 240
    assert result["vacation_minutes"] == 960
    assert result["payable_minutes"] == 1200


def test_vacation_is_capped_by_the_work_on_the_same_day_and_says_so():
    entries = {"2026-01-12": day(ist_slot("08:00", "12:00"))}                 # 240 Min Arbeit
    result = run(entries, vacation={"2026-01-12": 480, "2026-01-13": 480})

    assert result["vacation_minutes"] == 240 + 480
    assert result["payable_minutes"] == 240 + 240 + 480
    assert result["vacation_capped_days"] == [
        {"date": "2026-01-12", "vacation_minutes": 480, "work_minutes": 240,
         "counted_minutes": 240}]


def test_zero_minute_vacation_days_do_not_cap_work():
    entries = {"2026-01-17": day(ist_slot("08:00", "12:00"))}                 # Samstag im Urlaub
    result = run(entries, vacation={"2026-01-17": 0})
    assert result["vacation_minutes"] == 0 and result["vacation_capped_days"] == []


def test_junk_vacation_values_are_ignored():
    vacation = {"2026-01-12": True, "2026-01-13": "480", "2026-01-14": 1.5, "kaputt": 480,
                "2026-01-15": 60}
    assert run({}, vacation=vacation)["vacation_minutes"] == 60


# --- Fremddaten ----------------------------------------------------------------------------------------

def test_an_odd_stored_slot_counts_zero_and_never_raises(caplog):
    entries = {"2026-01-05": day(ist_slot("08:00", "09:00"),
                                 {"start": "09:00", "end": "10:00", "pause": None},
                                 {"start": None, "end": None}, "kein-slot"),
               "2026-01-06": {"slots": "kaputt"}, "2026-01-07": "kaputt", "2026-01-08": None}

    with caplog.at_level(logging.WARNING, logger="src.api_summary"):
        result = run(entries, {"pause_warning_enabled": True})

    assert result["total_minutes"] == 60
    assert [d["date"] for d in result["days"]] == ["2026-01-05"]
    assert "Slot nicht berechenbar" in caplog.text


def test_odd_data_on_one_day_does_not_hide_the_pause_warning_of_another(caplog):
    entries = {"2026-01-05": day({"start": "08:00", "end": "17:00"}, {"end": "18:00"}),
               "2026-01-06": day(ist_slot("08:00", "15:00", 0))}
    with caplog.at_level(logging.WARNING, logger="src.api_summary"):
        result = run(entries, {"pause_warning_enabled": True})
    assert [w["date"] for w in result["pause_warnings"]] == ["2026-01-06"]
    assert result["total_minutes"] == 540 + 420
    assert "Pausenpflicht für 2026-01-05" in caplog.text
    assert all(r.exc_info is None for r in caplog.records)        # kein Traceback je Anfrage


# --- Review-Befunde (I1, M1, M2, M3) ----------------------------------------------------------------

@pytest.mark.parametrize("override", [
    {"werkstudent_limit_max_hours": float("inf")},
    {"werkstudent_limit_max_hours": float("-inf")},
    {"werkstudent_limit_max_hours": float("nan")},
    {"werkstudent_limit_max_hours": 1e999},
    {"werkstudent_limit_max_hours": 1e308},
    {"werkstudent_limit_max_hours": "viel"},
    {"werkstudent_limit_start": 20260101},
    {"werkstudent_limit_start": True},
    {"werkstudent_limit_end": ["x"]},
], ids=["inf", "-inf", "nan", "1e999", "1e308", "text", "start-int", "start-bool", "end-list"])
def test_odd_limit_settings_drop_the_limit_and_never_raise(override, caplog):
    entries = {"2026-01-05": day(ist_slot("08:00", "20:00"))}
    with caplog.at_level(logging.WARNING, logger="src.api_summary"):
        result = run(entries, dict(LIMIT, **override))
    assert result["total_minutes"] == 720
    assert all(w["limit_minutes"] is None and w["exceeded"] is False for w in result["weeks"])
    assert len(caplog.records) == 1                       # einmal je Anfrage, nicht je Woche
    assert "Wochenlimit" in caplog.text


@pytest.mark.parametrize("pause", [float("-inf"), float("inf"), float("nan"), 10 ** 400],
                         ids=["-inf", "inf", "nan", "huge-int"])
def test_an_absurd_stored_pause_counts_zero_and_never_raises(pause):
    entries = {"2026-01-05": day(ist_slot("08:00", "12:00"), ist_slot("13:00", "14:00", pause))}
    result = run(entries, {"pause_warning_enabled": True})
    assert result["total_minutes"] == 240
    assert result["weeks"][1]["total_minutes"] == 240


def test_an_odd_slot_on_one_vacation_day_does_not_switch_off_the_cap_for_the_others():
    entries = {"2026-01-12": day(ist_slot("08:00", "12:00")),
               "2026-01-13": day({"start": "08:00", "end": "12:00", "pause": None})}

    result = run(entries, vacation={"2026-01-12": 480, "2026-01-13": 480})

    assert result["vacation_minutes"] == (480 - 240) + 480
    assert [d["date"] for d in result["vacation_capped_days"]] == ["2026-01-12"]


def test_every_slot_is_computed_once_per_request(caplog):
    entries = {"2026-01-05": day(ist_slot("08:00", "09:00"),
                                 {"start": "09:00", "end": "10:00", "pause": None})}
    with caplog.at_level(logging.WARNING, logger="src.api_summary"):
        run(entries, {"pause_warning_enabled": True})
    odd = [r for r in caplog.records if "Slot nicht berechenbar" in r.getMessage()]
    assert len(odd) == 1


def test_the_warning_for_an_odd_slot_is_short_and_has_no_traceback(caplog):
    entries = {"2026-01-05": day({"start": "08:00", "end": "09:00", "pause": None,
                                  "kategorie": "GEHEIM" * 100})}
    with caplog.at_level(logging.WARNING, logger="src.api_summary"):
        run(entries)
    record = caplog.records[0]
    assert record.exc_info is None
    assert len(record.getMessage()) < 200 and "GEHEIM" not in record.getMessage()
