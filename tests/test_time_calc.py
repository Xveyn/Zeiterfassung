from src.time_utils import parse_time, calculate_hours, validate_entry

def test_parse_valid_time():
    assert parse_time("08:00") == (8, 0)
    assert parse_time("16:30") == (16, 30)

def test_parse_invalid_time():
    assert parse_time("abc") is None
    assert parse_time("25:00") is None
    assert parse_time("12:60") is None
    assert parse_time("") is None

def test_calculate_hours():
    assert calculate_hours("08:00", "16:30") == 8.5
    assert calculate_hours("09:00", "17:00") == 8.0
    assert calculate_hours("06:00", "06:30") == 0.5

def test_validate_entry_valid():
    ok, msg = validate_entry("08:00", "16:30")
    assert ok is True

def test_validate_entry_invalid_format():
    ok, msg = validate_entry("abc", "16:30")
    assert ok is False

def test_validate_entry_end_before_start():
    ok, msg = validate_entry("17:00", "08:00")
    assert ok is False

def test_calculate_hours_with_pause():
    assert calculate_hours("08:00", "16:30", pause_minutes=30) == 8.0
    assert calculate_hours("09:00", "17:00", pause_minutes=60) == 7.0
    assert calculate_hours("08:00", "16:30", pause_minutes=0) == 8.5

def test_calculate_hours_default_no_pause():
    # Existing behavior unchanged when pause_minutes not provided
    assert calculate_hours("08:00", "16:30") == 8.5


from src.time_utils import slots_overlap, validate_slots


def _s(start, end, pause=0, kategorie=""):
    return {"start": start, "end": end, "pause": pause, "kategorie": kategorie}


def test_slots_overlap_false_for_disjoint():
    assert slots_overlap([_s("08:00", "12:00"), _s("13:00", "17:00")]) is False


def test_slots_overlap_false_for_adjacent():
    # Ende == Start des nächsten ist erlaubt (angrenzend, nicht überlappend)
    assert slots_overlap([_s("08:00", "12:00"), _s("12:00", "17:00")]) is False


def test_slots_overlap_true_for_overlap():
    assert slots_overlap([_s("08:00", "13:00"), _s("12:00", "17:00")]) is True


def test_slots_overlap_detects_unsorted_input():
    # Reihenfolge egal: zweite Liste ist nicht nach start sortiert
    assert slots_overlap([_s("13:00", "17:00"), _s("08:00", "13:30")]) is True


def test_slots_overlap_ignores_unparsable_times():
    # Ein Slot mit kaputter Zeit wird übersprungen (validate_slots fängt ihn ab)
    assert slots_overlap([_s("abc", "xyz"), _s("08:00", "12:00")]) is False


def test_slots_overlap_empty_and_single():
    assert slots_overlap([]) is False
    assert slots_overlap([_s("08:00", "16:00")]) is False


def test_validate_slots_ok_single():
    ok, msg = validate_slots([_s("08:00", "16:30", 30)])
    assert ok is True
    assert msg == ""


def test_validate_slots_ok_multiple_disjoint():
    ok, _ = validate_slots([_s("08:00", "12:00", 0, "Büro"), _s("13:00", "17:00", 30, "HO")])
    assert ok is True


def test_validate_slots_empty_is_ok():
    assert validate_slots([]) == (True, "")


def test_validate_slots_rejects_overlap():
    ok, msg = validate_slots([_s("08:00", "13:00"), _s("12:00", "17:00")])
    assert ok is False
    assert "überlapp" in msg.lower()


def test_validate_slots_rejects_bad_slot():
    ok, msg = validate_slots([_s("17:00", "08:00")])  # Ende vor Start
    assert ok is False


def test_validate_slots_rejects_pause_too_big():
    ok, msg = validate_slots([_s("08:00", "09:00", 90)])  # Pause > Arbeitszeit
    assert ok is False


def test_validate_slots_without_pause_ignores_pause():
    # Reservierungs-Slots: pause wird ignoriert (with_pause=False), kein Pausenfehler
    ok, msg = validate_slots([_s("08:00", "09:00", 999)], with_pause=False)
    assert ok is True


def test_validate_period_from_after_to_is_invalid():
    import datetime
    from src.time_utils import validate_period
    ok, msg = validate_period(datetime.date(2026, 3, 31), datetime.date(2026, 3, 1))
    assert ok is False
    assert "Von-Datum" in msg


def test_validate_period_equal_dates_ok():
    import datetime
    from src.time_utils import validate_period
    ok, msg = validate_period(datetime.date(2026, 3, 1), datetime.date(2026, 3, 1))
    assert ok is True
    assert msg == ""


def test_validate_period_from_before_to_ok():
    import datetime
    from src.time_utils import validate_period
    ok, _ = validate_period(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))
    assert ok is True
