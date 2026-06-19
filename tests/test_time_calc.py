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
