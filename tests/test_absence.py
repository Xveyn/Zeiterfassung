from src import absence, vacation_plan, vacations
from src.absence import CappedDay, cap_notice


def test_vacation_names_are_the_shared_functions():
    assert vacations.cap_by_worktime is absence.cap_by_worktime
    assert vacations.cap_notice is absence.cap_notice
    assert vacations.CappedDay is absence.CappedDay
    assert vacations.apportion_minutes is absence.apportion_minutes
    assert vacation_plan.format_day_list is absence.format_day_list


def test_capped_day_keeps_vacation_alias():
    assert CappedDay("2026-09-01", 480, 240, 240).vacation == 480


def test_cap_notice_sick_single_day():
    assert cap_notice([CappedDay("2026-09-01", 480, 240, 240)], kind="sick") == (
        "An 1 Tag (01.09.2026) ist Arbeitszeit erfasst; "
        "die Krankheitsstunden sind dort um 4.0h gekürzt.")


def test_cap_notice_sick_lists_up_to_three_days():
    hits = [CappedDay(f"2026-09-0{i}", 480, 60, 420) for i in (1, 2)]
    assert cap_notice(hits, kind="sick") == (
        "An 2 Tagen (01.09.2026, 02.09.2026) ist Arbeitszeit erfasst; "
        "die Krankheitsstunden sind dort um insgesamt 2.0h gekürzt.")


def test_cap_notice_sick_drops_list_beyond_three_days():
    hits = [CappedDay(f"2026-09-0{i}", 480, 60, 420) for i in range(1, 5)]
    assert cap_notice(hits, kind="sick").startswith("An 4 Tagen ist Arbeitszeit erfasst;")
