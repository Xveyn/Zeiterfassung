# tests/test_api_entry_write.py
import datetime
import json
import logging

import pytest

from src import api_entry_write as w
from src.api_entry_write import WriteError
from src.conflicts_store import ConflictsStore
from src.vacations import VacationStore


def body(slots=None, **extra):
    payload = {"slots": [{"start": "08:00", "end": "12:00"}] if slots is None else slots}
    payload.update(extra)
    return json.dumps(payload).encode("utf-8")


def error_of(callable_, *args, **kwargs):
    with pytest.raises(WriteError) as info:
        callable_(*args, **kwargs)
    return info.value


# --- parse_day_body: Erfolg ---------------------------------------------------------

def test_minimal_slot_gets_the_defaults():
    assert w.parse_day_body(body()) == [
        {"start": "08:00", "end": "12:00", "pause": 0, "kategorie": ""}]


def test_full_slot_and_the_category_is_stripped():
    slots = w.parse_day_body(body([
        {"start": "08:00", "end": "12:00", "pause": 15, "kategorie": "  Projekt A  "},
        {"start": "12:00", "end": "16:30"}]))      # angrenzend ist keine Überlappung

    assert slots == [
        {"start": "08:00", "end": "12:00", "pause": 15, "kategorie": "Projekt A"},
        {"start": "12:00", "end": "16:30", "pause": 0, "kategorie": ""}]


def test_a_non_ascii_category_is_fine():
    slots = w.parse_day_body(body([{"start": "08:00", "end": "09:00",
                                    "kategorie": "Büro – Übergabe ✓"}]))
    assert slots[0]["kategorie"] == "Büro – Übergabe ✓"


# --- Review Focus 1: Form des Bodys -------------------------------------------------------

@pytest.mark.parametrize("raw", [
    b"", b"{", b"\xff\xfe", b"nicht json", b"[]", b"null", b'"x"', b"5", b"true",
    b"{}", b'{"slots": 5}', b'{"slots": {}}', b'{"slots": "x"}', b'{"slots": null}',
    b'{"slots": [], "x": 1}', b'{"slotz": []}',
    b'{"slots": NaN}', b'{"slots": Infinity}', b'{"slots": [{"start": NaN}]}',
    b'{"slots": [], "slots": []}',                       # doppelter Schlüssel
])
def test_a_malformed_body_is_400(raw):
    error = error_of(w.parse_day_body, raw)
    assert error.status == 400 and error.code in {
        "invalid_json", "invalid_body", "invalid_encoding"}


# Kurze IDs sind Pflicht: pytest macht die Parameter zur Test-ID und legt sie in die
# Umgebungsvariable PYTEST_CURRENT_TEST — unter Windows sind Werte dort auf 32 767
# Zeichen begrenzt, ein 100 000 Zeichen langer Bytes-Parameter ließ das Setup scheitern.
@pytest.mark.parametrize("raw", [
    pytest.param(b"[" * 100_000, id="verschachtelte-liste"),            # RecursionError im Parser
    pytest.param(b'{"slots": ' + b"[" * 100_000 + b"}", id="verschachtelte-slots"),
])
def test_deeply_nested_json_is_400_never_an_exception(raw):
    error = error_of(w.parse_day_body, raw)
    assert error.status == 400


def test_an_empty_slot_list_is_422_and_points_to_delete():
    error = error_of(w.parse_day_body, body([]))
    assert (error.status, error.code) == (422, "empty_slots")
    assert "DELETE" in error.message


def test_too_many_slots_is_422():
    slots = [{"start": f"{h:02d}:00", "end": f"{h:02d}:30"} for h in range(24)] * 3
    error = error_of(w.parse_day_body, body(slots))
    assert (error.status, error.code) == (422, "too_many_slots")


@pytest.mark.parametrize("slot", [
    "08:00", 5, None, [], [1, 2],
    {}, {"start": "08:00"}, {"end": "12:00"},
    {"start": "08:00", "end": "12:00", "extra": 1},
    {"start": "08:00", "end": "12:00", "Pause": 5},
])
def test_a_slot_of_the_wrong_shape_is_422(slot):
    error = error_of(w.parse_day_body, body([slot]))
    assert (error.status, error.code) == (422, "invalid_slot")


@pytest.mark.parametrize("value", [
    "8:00", "24:00", "08:60", "0800", "08:0", "08:000", " 08:00", "08:00 ", "08:00\n",
    "٠٨:٠٠", "", "ab:cd", 800, None, True, ["08:00"],
])
@pytest.mark.parametrize("field", ["start", "end"])
def test_times_must_be_exactly_hh_mm(field, value):
    slot = {"start": "08:00", "end": "12:00"}
    slot[field] = value
    error = error_of(w.parse_day_body, body([slot]))
    assert (error.status, error.code) == (422, "invalid_time")


@pytest.mark.parametrize("pause", [True, False, "30", 1.5, 30.0, -1, None, [5], {"m": 5}])
def test_pause_must_be_a_whole_number_of_minutes(pause):
    error = error_of(w.parse_day_body, body([{"start": "08:00", "end": "12:00", "pause": pause}]))
    assert (error.status, error.code) == (422, "invalid_pause")


@pytest.mark.parametrize("category", [5, None, ["a"], {"a": 1}, True,
                                      "a\nb", "a\x00b", "a\x7fb", "a\tb", "x" * 101,
                                      "\ud800", "A\ud83d", "\udc00x", "a\x85b", "a\x9fb"])
def test_a_bad_category_is_422(category):
    error = error_of(w.parse_day_body, body([{"start": "08:00", "end": "12:00",
                                              "kategorie": category}]))
    assert (error.status, error.code) == (422, "invalid_category")


def test_a_category_of_exactly_100_characters_is_fine():
    slots = w.parse_day_body(body([{"start": "08:00", "end": "12:00", "kategorie": "x" * 100}]))
    assert len(slots[0]["kategorie"]) == 100


@pytest.mark.parametrize("slots", [
    [{"start": "12:00", "end": "08:00"}],                                     # Ende vor Start
    [{"start": "08:00", "end": "08:00"}],                                     # Ende = Start
    [{"start": "08:00", "end": "09:00", "pause": 60}],                        # Pause = Arbeitszeit
    [{"start": "08:00", "end": "12:00"}, {"start": "11:00", "end": "13:00"}],  # Überlappung
])
def test_the_ui_rules_for_slots_apply(slots):
    error = error_of(w.parse_day_body, body(slots))
    assert (error.status, error.code) == (422, "invalid_slots")
    assert error.message


# --- check_date_range ------------------------------------------------------------------------

@pytest.mark.parametrize("day", [datetime.date(2000, 1, 1), datetime.date(2026, 10, 7),
                                 datetime.date(2100, 12, 31)])
def test_dates_inside_the_range_pass(day):
    w.check_date_range(day)


@pytest.mark.parametrize("day", [datetime.date(1999, 12, 31), datetime.date(1970, 1, 1),
                                 datetime.date(2101, 1, 1), datetime.date(1, 1, 1)])
def test_dates_outside_the_range_are_422(day):
    error = error_of(w.check_date_range, day)
    assert (error.status, error.code) == (422, "date_out_of_range")


# --- check_day_writable ---------------------------------------------------------------------------

@pytest.fixture
def conflicts(tmp_path):
    store = ConflictsStore(str(tmp_path / "conflicts.json"))
    store.save_all([
        {"id": "c-1", "kind": "entry", "key": "2026-05-14", "resolved": False},
        {"id": "c-2", "kind": "entry", "key": "2026-05-15", "resolved": True},
        {"id": "c-3", "kind": "setting", "key": "2026-05-16", "resolved": False},
    ])
    return store


@pytest.fixture
def vacations(tmp_path):
    store = VacationStore(str(tmp_path / "vacations.json"))
    store.save(None, "Sommer", "2026-07-01", "2026-07-05", {
        "2026-07-01": 480, "2026-07-02": 480, "2026-07-03": 0,     # 3.: Feiertag/Wochenende
        "2026-07-04": 0, "2026-07-05": 0})
    return store


@pytest.mark.parametrize("for_save", [True, False])
def test_an_unresolved_entry_conflict_blocks_save_and_delete(conflicts, for_save):
    error = error_of(w.check_day_writable, "2026-05-14", conflicts_store=conflicts,
                     vacation_store=None, for_save=for_save)
    assert (error.status, error.code) == (409, "sync_conflict")


@pytest.mark.parametrize("day", ["2026-05-15", "2026-05-16", "2026-05-17"])
def test_resolved_other_kind_and_unrelated_days_are_free(conflicts, day):
    w.check_day_writable(day, conflicts_store=conflicts, vacation_store=None, for_save=True)


def test_a_vacation_day_with_minutes_blocks_saving(vacations):
    error = error_of(w.check_day_writable, "2026-07-01", conflicts_store=None,
                     vacation_store=vacations, for_save=True)
    assert (error.status, error.code) == (409, "vacation_day")
    assert "Sommer" in error.message


def test_a_vacation_day_does_not_block_deleting(vacations):
    w.check_day_writable("2026-07-01", conflicts_store=None, vacation_store=vacations,
                         for_save=False)


@pytest.mark.parametrize("day", ["2026-07-03", "2026-07-04", "2026-06-30", "2026-07-06"])
def test_zero_minute_days_and_days_outside_the_period_are_free(vacations, day):
    w.check_day_writable(day, conflicts_store=None, vacation_store=vacations, for_save=True)


def test_missing_stores_mean_no_extra_rules():
    w.check_day_writable("2026-05-14", conflicts_store=None, vacation_store=None, for_save=True)


# --- warnings_for ----------------------------------------------------------------------------------

LIMIT = {"werkstudent_limit_enabled": True, "werkstudent_limit_start": "2026-01-01",
         "werkstudent_limit_end": "2026-12-31", "werkstudent_limit_max_hours": 20,
         "pause_warning_enabled": True}


def five_hours(pause=30):
    return {"slots": [{"start": "09:00", "end": "14:00", "pause": pause, "kategorie": ""}]}


def week_entries():
    # Mo–Do 2026-10-05..08, je 5 h (Pause 30 min: netto 4:30 h)
    return {f"2026-10-0{d}": five_hours() for d in (5, 6, 7, 8)}


def test_the_weekly_limit_is_a_warning_with_the_new_day_counted():
    slots = [{"start": "08:00", "end": "13:00", "pause": 0, "kategorie": ""}]    # +5 h
    warnings = w.warnings_for(LIMIT, week_entries(), "2026-10-09", slots)

    limit = [x for x in warnings if x["code"] == "weekly_limit"]
    assert len(limit) == 1
    assert limit[0]["limit_minutes"] == 1200
    assert limit[0]["total_minutes"] == 4 * 270 + 300 and limit[0]["iso_week"] == 41


def test_the_new_day_replaces_the_old_one_instead_of_counting_twice():
    entries = week_entries()
    entries["2026-10-09"] = {"slots": [{"start": "06:00", "end": "20:00", "pause": 0,
                                        "kategorie": ""}]}          # 14 h, wird ersetzt
    slots = [{"start": "08:00", "end": "09:00", "pause": 0, "kategorie": ""}]

    warnings = w.warnings_for(LIMIT, entries, "2026-10-09", slots)

    assert [x for x in warnings if x["code"] == "weekly_limit"] == []


def test_the_pause_requirement_is_a_warning():
    slots = [{"start": "08:00", "end": "16:00", "pause": 0, "kategorie": ""}]    # 8 h ohne Pause

    warnings = w.warnings_for(LIMIT, {}, "2026-10-09", slots)

    assert {"code": "pause_requirement", "worked_minutes": 480,
            "actual_pause_minutes": 0, "required_pause_minutes": 30} in warnings


def test_a_sufficient_pause_gives_no_warning():
    slots = [{"start": "08:00", "end": "16:00", "pause": 30, "kategorie": ""}]
    assert w.warnings_for(LIMIT, {}, "2026-10-09", slots) == []


def test_disabled_checks_give_no_warnings():
    off = {**LIMIT, "werkstudent_limit_enabled": False, "pause_warning_enabled": False}
    slots = [{"start": "06:00", "end": "20:00", "pause": 0, "kategorie": ""}]
    assert w.warnings_for(off, week_entries(), "2026-10-09", slots) == []


def test_warnings_do_not_mutate_the_callers_entries():
    entries = week_entries()
    before = json.dumps(entries, sort_keys=True)
    w.warnings_for(LIMIT, entries, "2026-10-09",
                   [{"start": "08:00", "end": "13:00", "pause": 0, "kategorie": ""}])
    assert json.dumps(entries, sort_keys=True) == before



# --- Review PR 4: Surrogate, Kodierung, Warnungen -------------------------------------------------

def test_a_lone_surrogate_can_never_reach_the_store():
    # Ein Skript, das einen Namen mitten in einem Emoji kürzt, erzeugt \ud83d. Im
    # Store würde es jedes spätere Speichern an `UnicodeEncodeError` scheitern lassen.
    raw = b'{"slots": [{"start": "08:00", "end": "09:00", "kategorie": "A\\ud83d"}]}'
    error = error_of(w.parse_day_body, raw)
    assert (error.status, error.code) == (422, "invalid_category")


def test_a_utf8_bom_is_ignored():
    # Windows PowerShell 5.1: `Set-Content -Encoding UTF8` schreibt ein BOM.
    slots = w.parse_day_body(b"\xef\xbb\xbf" + body())
    assert slots[0]["start"] == "08:00"


@pytest.mark.parametrize("raw", [
    body().decode("utf-8").encode("utf-16"),                       # `>` / Out-File
    '{"slots": [{"start": "08:00", "end": "09:00", "kategorie": "Büro"}]}'.encode("cp1252"),
])
def test_other_encodings_get_a_clear_encoding_error(raw):
    error = error_of(w.parse_day_body, raw)
    assert (error.status, error.code) == (400, "invalid_encoding")
    assert "UTF-8" in error.message


def test_warnings_never_block_a_write_even_on_odd_stored_data(caplog):
    # Der Sync validiert Slot-Inhalte nicht; ein gespeicherter Slot mit pause=None
    # ließ `week_ist_minutes` mit TypeError scheitern und damit das Schreiben.
    entries = {"2026-10-08": {"slots": [{"start": "08:00", "end": "17:00",
                                         "pause": None, "kategorie": ""}]}}
    slots = [{"start": "08:00", "end": "09:00", "pause": 0, "kategorie": ""}]
    with caplog.at_level(logging.ERROR):
        assert w.warnings_for(LIMIT, entries, "2026-10-09", slots) == []
    assert "Warnungen" in caplog.text


def test_a_failing_weekly_check_does_not_hide_the_pause_warning():
    entries = {"2026-10-08": {"slots": [{"start": "08:00", "end": "17:00",
                                         "pause": None, "kategorie": ""}]}}
    slots = [{"start": "08:00", "end": "16:00", "pause": 0, "kategorie": ""}]   # 8 h ohne Pause
    codes = [x["code"] for x in w.warnings_for(LIMIT, entries, "2026-10-09", slots)]
    assert codes == ["pause_requirement"]
