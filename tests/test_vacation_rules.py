"""Reine Urlaubs-Regeln (Tk-frei, ohne Store)."""

import pytest

from src.vacations import (
    CappedDay, apportion_minutes, cap_by_worktime, cap_notice, conflicting_days,
    expand_days,
    periods_overlap,
    total_minutes,
)


# ---------------------------------------------------------------- expand_days

def test_expand_days_covers_every_calendar_day():
    days = expand_days("2026-04-13", "2026-04-20", 480, "")
    assert sorted(days) == [
        "2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16",
        "2026-04-17", "2026-04-18", "2026-04-19", "2026-04-20",
    ]


def test_expand_days_zeroes_weekend():
    days = expand_days("2026-04-13", "2026-04-20", 480, "")
    assert days["2026-04-18"] == 0  # Samstag
    assert days["2026-04-19"] == 0  # Sonntag
    assert days["2026-04-13"] == 480  # Montag


def test_expand_days_zeroes_holiday_for_state():
    # 2026-01-01 ist bundesweit Feiertag; 2026-01-06 nur in BY/BW/ST.
    bayern = expand_days("2026-01-01", "2026-01-07", 480, "BY")
    assert bayern["2026-01-01"] == 0
    assert bayern["2026-01-06"] == 0
    assert bayern["2026-01-07"] == 480


def test_expand_days_without_state_keeps_holidays_paid():
    # Ohne Bundesland liefert get_holidays ein leeres Dict — nur Wochenenden
    # fallen dann auf 0.
    ohne = expand_days("2026-01-01", "2026-01-02", 480, "")
    assert ohne["2026-01-01"] == 480


def test_expand_days_spans_year_boundary():
    days = expand_days("2026-12-28", "2027-01-04", 480, "BY")
    assert len(days) == 8
    assert days["2026-12-28"] == 480
    assert days["2027-01-01"] == 0  # Neujahr
    assert days["2027-01-04"] == 480


def test_expand_days_single_day():
    assert expand_days("2026-04-13", "2026-04-13", 480, "") == {"2026-04-13": 480}


def test_expand_days_reversed_range_is_empty():
    assert expand_days("2026-04-20", "2026-04-13", 480, "") == {}


# ---------------------------------------------------------- apportion_minutes

def test_apportion_minutes_even_split():
    assert apportion_minutes(2400, 6) == [400, 400, 400, 400, 400, 400]


def test_apportion_minutes_remainder_goes_to_front():
    assert apportion_minutes(2400, 7) == [343, 343, 343, 343, 343, 343, 342]


@pytest.mark.parametrize("total", [0, 1, 59, 2400, 2401, 9999])
@pytest.mark.parametrize("n", [1, 2, 3, 5, 6, 7, 30, 31])
def test_apportion_minutes_always_sums_exactly(total, n):
    parts = apportion_minutes(total, n)
    assert len(parts) == n
    assert sum(parts) == total
    assert all(p >= 0 for p in parts)


def test_apportion_minutes_zero_days():
    assert apportion_minutes(2400, 0) == []


# ------------------------------------------------------------ periods_overlap

def _period(name, date_from, date_to, deleted=False):
    return {"name": name, "from": date_from, "to": date_to,
            "days": {}, "gcal_event_id": None,
            "modified_at": "2026-08-30T10:00:00Z", "deleted": deleted}


def test_periods_overlap_detects_true_overlap():
    periods = {"a": _period("Sommer", "2026-07-01", "2026-07-14")}
    assert periods_overlap(periods, None, "2026-07-10", "2026-07-20") == "Sommer"


def test_periods_overlap_detects_touching_edge():
    periods = {"a": _period("Sommer", "2026-07-01", "2026-07-14")}
    assert periods_overlap(periods, None, "2026-07-14", "2026-07-20") == "Sommer"


def test_periods_overlap_detects_enclosure():
    periods = {"a": _period("Sommer", "2026-07-05", "2026-07-10")}
    assert periods_overlap(periods, None, "2026-07-01", "2026-07-31") == "Sommer"


def test_periods_overlap_allows_adjacent_ranges():
    periods = {"a": _period("Sommer", "2026-07-01", "2026-07-14")}
    assert periods_overlap(periods, None, "2026-07-15", "2026-07-20") is None


def test_periods_overlap_excludes_self_when_editing():
    periods = {"a": _period("Sommer", "2026-07-01", "2026-07-14")}
    assert periods_overlap(periods, "a", "2026-07-05", "2026-07-20") is None


def test_periods_overlap_ignores_tombstones():
    periods = {"a": _period("Sommer", "2026-07-01", "2026-07-14", deleted=True)}
    assert periods_overlap(periods, None, "2026-07-10", "2026-07-20") is None


# -------------------------------------------------------------- total_minutes

def test_total_minutes_sums_over_minutes():
    assert total_minutes({"2026-04-13": 480, "2026-04-14": 240}) == 720


def test_total_minutes_empty():
    assert total_minutes({}) == 0


def test_period_for_day_finds_the_covering_period():
    from src.vacations import period_for_day
    periods = {"a1": {**_period("Sommer", "2026-07-01", "2026-07-02"),
                      "days": {"2026-07-01": 480, "2026-07-02": 0}}}
    hit = period_for_day(periods, "2026-07-02")
    assert hit["name"] == "Sommer"
    assert hit["id"] == "a1"
    assert period_for_day(periods, "2026-07-03") is None


def test_period_for_day_returns_a_detached_days_copy():
    from src.vacations import period_for_day
    periods = {"a1": {**_period("Sommer", "2026-07-01", "2026-07-01"),
                      "days": {"2026-07-01": 480}}}
    hit = period_for_day(periods, "2026-07-01")
    hit["days"]["2026-07-01"] = 0
    assert periods["a1"]["days"]["2026-07-01"] == 480


# ---------------------------------------------------------- conflicting_days

def test_conflicting_days_finds_a_day_with_recorded_time():
    days = {"2026-04-13": 480, "2026-04-14": 480}
    assert conflicting_days(days, ["2026-04-14"], []) == ["2026-04-14"]


def test_conflicting_days_finds_a_day_with_a_reservation():
    days = {"2026-04-13": 480, "2026-04-14": 480}
    assert conflicting_days(days, [], ["2026-04-13"]) == ["2026-04-13"]


def test_conflicting_days_is_empty_without_overlap():
    days = {"2026-04-13": 480, "2026-04-14": 480}
    assert conflicting_days(days, ["2026-04-20"], ["2026-04-21"]) == []


def test_conflicting_days_ignores_days_without_vacation_hours():
    # Sa/So und Feiertage stehen mit 0 Minuten in der Periode: sie halten den
    # Zeitraum zusammen, sind aber KEIN Urlaubstag. Wer am Samstag mitten im
    # Urlaub arbeitet, soll den Urlaub trotzdem darueber legen koennen.
    days = {"2026-04-17": 480, "2026-04-18": 0, "2026-04-19": 0}
    assert conflicting_days(days, ["2026-04-18"], ["2026-04-19"]) == []


def test_conflicting_days_reports_sorted_and_deduplicated():
    days = {"2026-04-13": 480, "2026-04-14": 480, "2026-04-15": 480}
    # 2026-04-14 traegt Ist-Zeit UND Reservierung — trotzdem nur einmal.
    assert conflicting_days(
        days, ["2026-04-15", "2026-04-14"], ["2026-04-14", "2026-04-13"]
    ) == ["2026-04-13", "2026-04-14", "2026-04-15"]


# ------------------------------------------------------------ cap_by_worktime

def _entry(*slots):
    """Eintrag im Storage-Format aus (start, end)-Paaren."""
    return {"slots": [{"start": s, "end": e, "pause": 0, "kategorie": ""}
                      for s, e in slots]}


def test_cap_by_worktime_leaves_days_without_worktime_alone():
    days = {"2026-09-01": 480, "2026-09-02": 480}
    capped, hits = cap_by_worktime(days, {})
    assert capped == days
    assert hits == []


def test_cap_by_worktime_reduces_vacation_by_the_worked_minutes():
    # 8 h Urlaub, 4 h erfasste Ist-Zeit -> der Tag verguetet 8 h, nicht 12 h.
    days = {"2026-09-01": 480}
    entries = {"2026-09-01": _entry(("08:00", "12:00"))}
    capped, hits = cap_by_worktime(days, entries)
    assert capped == {"2026-09-01": 240}
    assert len(hits) == 1
    assert hits[0].date == "2026-09-01"
    assert hits[0].vacation == 480
    assert hits[0].work == 240
    assert hits[0].capped == 240


def test_cap_by_worktime_floors_at_zero():
    # Mehr gearbeitet als Urlaub am Tag -> 0, nie negativ.
    days = {"2026-09-01": 240}
    entries = {"2026-09-01": _entry(("08:00", "16:00"))}
    capped, hits = cap_by_worktime(days, entries)
    assert capped == {"2026-09-01": 0}
    assert hits[0].capped == 0


def test_cap_by_worktime_ignores_days_without_vacation_hours():
    # Sa/So und Feiertage stehen mit 0 Minuten in der Periode. Dort DARF
    # Arbeitszeit liegen (dokumentierte Ausnahme) — nichts zu kappen, nichts
    # zu melden.
    days = {"2026-09-05": 0}
    entries = {"2026-09-05": _entry(("08:00", "12:00"))}
    capped, hits = cap_by_worktime(days, entries)
    assert capped == {"2026-09-05": 0}
    assert hits == []


def test_cap_by_worktime_sums_multiple_slots_over_minutes():
    # Zwei Slots am selben Tag: 2 h + 1.5 h = 210 min gegen 480 min Urlaub.
    days = {"2026-09-01": 480}
    entries = {"2026-09-01": _entry(("08:00", "10:00"), ("13:00", "14:30"))}
    capped, hits = cap_by_worktime(days, entries)
    assert capped == {"2026-09-01": 270}
    assert hits[0].work == 210


def test_cap_by_worktime_honours_the_pause_of_a_slot():
    days = {"2026-09-01": 480}
    entries = {"2026-09-01": {"slots": [
        {"start": "08:00", "end": "12:00", "pause": 30, "kategorie": ""}]}}
    capped, _ = cap_by_worktime(days, entries)
    assert capped == {"2026-09-01": 270}  # 480 - (240 - 30)


def test_cap_by_worktime_reports_hits_chronologically():
    days = {"2026-09-03": 480, "2026-09-01": 480, "2026-09-02": 480}
    entries = {
        "2026-09-03": _entry(("08:00", "09:00")),
        "2026-09-01": _entry(("08:00", "09:00")),
    }
    _, hits = cap_by_worktime(days, entries)
    assert [h.date for h in hits] == ["2026-09-01", "2026-09-03"]


def test_cap_by_worktime_does_not_mutate_its_input():
    days = {"2026-09-01": 480}
    entries = {"2026-09-01": _entry(("08:00", "12:00"))}
    cap_by_worktime(days, entries)
    assert days == {"2026-09-01": 480}


def test_cap_by_worktime_handles_empty_inputs():
    assert cap_by_worktime({}, {}) == ({}, [])


# ----------------------------------------------------------------- cap_notice

def test_cap_notice_is_empty_without_hits():
    assert cap_notice([]) == ""


def test_cap_notice_names_a_single_day_and_its_hours():
    hits = [CappedDay("2026-09-01", 480, 240, 240)]
    text = cap_notice(hits)
    assert "1 Tag" in text
    assert "01.09.2026" in text
    assert "4.0h" in text


def test_cap_notice_lists_up_to_three_days():
    hits = [
        CappedDay("2026-09-01", 480, 60, 420),
        CappedDay("2026-09-02", 480, 60, 420),
        CappedDay("2026-09-03", 480, 60, 420),
    ]
    text = cap_notice(hits)
    assert "3 Tagen" in text
    assert "01.09.2026" in text
    assert "03.09.2026" in text
    assert "3.0h" in text  # 3 x 60 min gekuerzt


def test_cap_notice_drops_the_list_beyond_three_days():
    hits = [CappedDay(f"2026-09-0{i}", 480, 60, 420) for i in range(1, 5)]
    text = cap_notice(hits)
    assert "4 Tagen" in text
    assert "01.09.2026" not in text  # Liste waere zu lang, nur die Zahl
