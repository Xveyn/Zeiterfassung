import pytest

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
    assert cap_notice(hits, kind="sick") == (
        "An 4 Tagen ist Arbeitszeit erfasst; "
        "die Krankheitsstunden sind dort um insgesamt 4.0h gekürzt.")


def test_cap_notice_sick_lists_exactly_three_days():
    hits = [CappedDay(f"2026-09-0{i}", 480, 60, 420) for i in (1, 2, 3)]
    assert cap_notice(hits, kind="sick") == (
        "An 3 Tagen (01.09.2026, 02.09.2026, 03.09.2026) ist Arbeitszeit "
        "erfasst; die Krankheitsstunden sind dort um insgesamt 3.0h gekürzt.")


def test_cap_notice_rejects_unknown_kind():
    with pytest.raises(ValueError):
        cap_notice([CappedDay("2026-09-01", 480, 240, 240)], kind="krank")
    with pytest.raises(ValueError):
        cap_notice([], kind="krank")


def _entries(work_minutes):
    if not work_minutes:
        return {}
    end = f"{8 + work_minutes // 60:02d}:{work_minutes % 60:02d}"
    return {"2026-06-03": {"slots": [{"start": "08:00", "end": end}]}}


def test_cut_without_sick_equals_cap_by_worktime():
    e = _entries(120)
    v = {"2026-06-03": 480, "2026-06-04": 480}
    cut = absence.cut_absences(e, v, {})
    capped, hits = absence.cap_by_worktime(v, e)
    assert cut.vacation == capped
    assert cut.vacation_capped == hits
    assert cut.sick == {}
    assert cut.sick_capped == []
    assert cut.sick_on_vacation == []


def test_sick_zeroes_vacation_and_reports_it():
    v = {"2026-06-04": 480, "2026-06-03": 480, "2026-06-05": 0, "2026-06-06": 480}
    s = {"2026-06-04": 480, "2026-06-03": 480, "2026-06-05": 0}
    cut = absence.cut_absences({}, v, s)
    assert cut.vacation == {"2026-06-04": 0, "2026-06-03": 0,
                            "2026-06-05": 0, "2026-06-06": 480}
    assert cut.sick == s
    assert cut.sick_on_vacation == ["2026-06-03", "2026-06-04"]
    assert v["2026-06-03"] == 480 and s["2026-06-04"] == 480


def test_sick_is_capped_before_vacation():
    e = _entries(120)
    cut = absence.cut_absences(e, {"2026-06-03": 480}, {"2026-06-03": 450})
    assert cut.vacation == {"2026-06-03": 0}
    assert cut.sick == {"2026-06-03": 330}
    assert cut.vacation_capped == []
    assert [h.date for h in cut.sick_capped] == ["2026-06-03"]


@pytest.mark.parametrize("work", [0, 120, 600])
@pytest.mark.parametrize("vac", [None, 0, 480])
@pytest.mark.parametrize("sick", [None, 0, 450])
def test_day_never_exceeds_max_of_work_and_absence(work, vac, sick):
    day = "2026-06-03"
    v = {} if vac is None else {day: vac}
    s = {} if sick is None else {day: sick}
    cut = absence.cut_absences(_entries(work), v, s)
    absence_in = sick if sick is not None else (vac or 0)
    total = work + cut.vacation.get(day, 0) + cut.sick.get(day, 0)
    assert total <= max(work, absence_in)


def test_sick_on_vacation_notice_wording():
    assert absence.sick_on_vacation_notice([]) == ""
    assert absence.sick_on_vacation_notice(["2026-06-03"]) == (
        "An 1 Tag (03.06.2026) lag Krankheit im Urlaub; "
        "dieser Tag zählt als Krankheit.")
    assert absence.sick_on_vacation_notice(["2026-06-03", "2026-06-04"]) == (
        "An 2 Tagen (03.06.2026, 04.06.2026) lag Krankheit im Urlaub; "
        "diese Tage zählen als Krankheit.")
    days = [f"2026-06-0{i}" for i in range(1, 5)]
    assert absence.sick_on_vacation_notice(days) == (
        "An 4 Tagen lag Krankheit im Urlaub; diese Tage zählen als Krankheit.")


# ----- cut_for_output: die eine Entscheidung „Häkchen aus oder Schnitt“ -----

@pytest.mark.parametrize("work", [0, 120, 600])
@pytest.mark.parametrize("vacation", [{}, {"2026-06-03": 480, "2026-06-04": 0},
                                      {"2026-06-03": 60, "2026-06-05": 480}])
def test_cut_for_output_without_sick_is_cap_by_worktime(work, vacation):
    entries = _entries(work)
    capped, hits = absence.cap_by_worktime(vacation, entries)
    cut = absence.cut_for_output(entries, vacation, None)
    assert cut.vacation == capped
    assert list(cut.vacation) == list(capped)
    assert cut.vacation_capped == hits
    assert (cut.sick, cut.sick_capped, cut.sick_on_vacation) == ({}, [], [])


def test_cut_for_output_with_sick_is_cut_absences():
    entries = _entries(120)
    vacation = {"2026-06-03": 480, "2026-06-04": 480}
    sick = {"2026-06-03": 450, "2026-06-05": 0}
    assert absence.cut_for_output(entries, vacation, sick) == (
        absence.cut_absences(entries, vacation, sick))
    assert absence.cut_for_output(entries, vacation, {}) == (
        absence.cut_absences(entries, vacation, {}))


def test_cut_for_output_leaves_inputs_alone():
    vacation = {"2026-06-03": 480}
    sick = {"2026-06-03": 480}
    absence.cut_for_output(_entries(120), vacation, sick)
    absence.cut_for_output(_entries(120), vacation, None)
    assert vacation == {"2026-06-03": 480} and sick == {"2026-06-03": 480}
