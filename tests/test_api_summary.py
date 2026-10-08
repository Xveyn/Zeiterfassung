# tests/test_api_summary.py
import datetime

import pytest

from src.api_summary import category_names, holidays_for, parse_month, parse_week, parse_year

D = datetime.date


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
