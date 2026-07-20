from src.pause_requirement import check_day_pause, required_pause_minutes


def _settings(enabled=True):
    return {"pause_warning_enabled": enabled}


def _slot(start, end, pause=0):
    return {"start": start, "end": end, "pause": pause}


def test_required_pause_minutes_none_up_to_six_hours():
    assert required_pause_minutes(6.0) == 0


def test_required_pause_minutes_zero_for_short_day():
    assert required_pause_minutes(2.5) == 0


def test_required_pause_minutes_thirty_over_six_hours():
    assert required_pause_minutes(6.01) == 30


def test_required_pause_minutes_thirty_at_nine_hours():
    assert required_pause_minutes(9.0) == 30


def test_required_pause_minutes_fortyfive_over_nine_hours():
    assert required_pause_minutes(9.01) == 45


def test_check_day_pause_none_when_disabled():
    # 8h Arbeit ohne jede Pause wäre ein klarer Verstoß, aber die Warnung ist
    # per Setting deaktiviert.
    slots = [_slot("08:00", "16:00", pause=0)]
    assert check_day_pause(_settings(enabled=False), slots) is None


def test_check_day_pause_none_without_slots():
    assert check_day_pause(_settings(), []) is None


def test_check_day_pause_none_under_six_hours_regardless_of_pause():
    slots = [_slot("08:00", "13:30", pause=0)]  # 5.5h
    assert check_day_pause(_settings(), slots) is None


def test_check_day_pause_none_when_pause_sufficient():
    slots = [_slot("08:00", "16:30", pause=30)]  # 8h netto, 30 Min Pause
    assert check_day_pause(_settings(), slots) is None


def test_check_day_pause_none_when_pause_exactly_meets_requirement():
    slots = [_slot("08:00", "17:00", pause=45)]  # 8.25h netto, genau 45 Min
    assert check_day_pause(_settings(), slots) is None


def test_check_day_pause_violation_when_pause_missing():
    slots = [_slot("08:00", "16:00", pause=0)]  # 8h netto, keine Pause
    result = check_day_pause(_settings(), slots)
    assert result == {
        "worked_hours": 8.0, "actual_pause_minutes": 0, "required_pause_minutes": 30,
    }


def test_check_day_pause_violation_over_nine_hours_needs_fortyfive():
    slots = [_slot("07:00", "17:00", pause=30)]  # 9.5h netto, nur 30 Min
    result = check_day_pause(_settings(), slots)
    assert result == {
        "worked_hours": 9.5, "actual_pause_minutes": 30, "required_pause_minutes": 45,
    }


def test_check_day_pause_sums_pause_across_multiple_slots():
    slots = [
        _slot("08:00", "12:00", pause=15),
        _slot("13:00", "17:15", pause=15),
    ]  # netto 3.75h + 4h = 7.75h, Pause 15+15=30 -> ausreichend fuer >6-9h
    assert check_day_pause(_settings(), slots) is None


def test_check_day_pause_multiple_slots_violation():
    slots = [
        _slot("08:00", "12:00", pause=0),
        _slot("13:00", "17:00", pause=0),
    ]  # netto 8h, keine Pause in den Slots eingetragen
    result = check_day_pause(_settings(), slots)
    assert result == {
        "worked_hours": 8.0, "actual_pause_minutes": 0, "required_pause_minutes": 30,
    }
