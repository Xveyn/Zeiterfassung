from src.weekly_limit import (
    check_dates_for_warnings, check_week_limit, format_limit_warnings,
    is_limit_active, period_scan_needed, scan_period_for_warnings, week_ist_minutes,
)


def _settings(enabled=True, start="2026-04-01", end="2026-07-15", max_hours=20.0):
    return {
        "werkstudent_limit_enabled": enabled,
        "werkstudent_limit_start": start,
        "werkstudent_limit_end": end,
        "werkstudent_limit_max_hours": max_hours,
    }


def _wsl(enabled=True, start="2026-04-01", end="2026-07-15", max_hours=20.0):
    return {"enabled": enabled, "start": start, "end": end, "max_hours": max_hours}


def _entry(slots):
    return {"slots": slots}


from tests.conftest import ist_slot as _slot  # geteilte Ist-Zeit-Factory (Audit N22)


def test_is_limit_active_false_when_disabled():
    assert is_limit_active(_settings(enabled=False), "2026-05-04") is False


def test_is_limit_active_false_without_period():
    assert is_limit_active(_settings(start="", end=""), "2026-05-04") is False


def test_is_limit_active_false_outside_period():
    assert is_limit_active(_settings(), "2026-08-01") is False


def test_is_limit_active_true_inside_period():
    assert is_limit_active(_settings(), "2026-05-04") is True


def test_week_ist_minutes_sums_all_categories_across_week():
    # KW 19/2026: Mo 2026-05-04 .. So 2026-05-10
    all_entries = {
        "2026-05-04": _entry([_slot("08:00", "12:00", kategorie="Büro")]),
        "2026-05-06": _entry([_slot("08:00", "12:00"),
                              _slot("13:00", "16:00", kategorie="Homeoffice")]),
    }
    assert week_ist_minutes(all_entries, 2026, 19) == 11 * 60


def test_week_ist_minutes_ignores_dates_outside_week():
    all_entries = {"2026-04-27": _entry([_slot("08:00", "16:00")])}  # KW 18
    assert week_ist_minutes(all_entries, 2026, 19) == 0


def test_week_ist_minutes_sums_minutes_not_rounded_hours():
    """Xveyn#171: calculate_hours rundet pro Slot auf 0,01 h. 100 + 100 + 160
    Minuten sind exakt 6:00 h — als Dezimalstunden summiert (1,67 + 1,67 +
    2,67) wurden daraus 6,01."""
    all_entries = {"2026-05-04": _entry([
        _slot("08:00", "09:40"), _slot("10:00", "11:40"), _slot("12:00", "14:40"),
    ])}
    assert week_ist_minutes(all_entries, 2026, 19) == 360


def test_check_week_limit_no_false_warning_from_rounding_drift():
    all_entries = {"2026-05-04": _entry([
        _slot("08:00", "09:40"), _slot("10:00", "11:40"), _slot("12:00", "14:40"),
    ])}
    assert check_week_limit(_settings(max_hours=6.0), all_entries, "2026-05-04") is None


def test_check_week_limit_warns_one_minute_over():
    all_entries = {"2026-05-04": _entry([
        _slot("08:00", "09:40"), _slot("10:00", "11:40"), _slot("12:00", "14:41"),
    ])}
    result = check_week_limit(_settings(max_hours=6.0), all_entries, "2026-05-04")
    assert result is not None
    assert result["total_minutes"] == 361


def test_check_week_limit_none_when_under_limit():
    all_entries = {"2026-05-04": _entry([_slot("08:00", "12:00")])}
    assert check_week_limit(_settings(), all_entries, "2026-05-04") is None


def test_check_week_limit_none_when_exactly_at_limit():
    all_entries = {
        "2026-05-04": _entry([_slot("08:00", "18:00")]),  # 10h
        "2026-05-05": _entry([_slot("08:00", "18:00")]),  # 10h -> 20h total
    }
    assert check_week_limit(_settings(), all_entries, "2026-05-04") is None


def test_check_week_limit_none_when_inactive():
    all_entries = {
        d: _entry([_slot("08:00", "18:00")])
        for d in ("2026-05-04", "2026-05-05", "2026-05-06")
    }
    assert check_week_limit(_settings(enabled=False), all_entries, "2026-05-04") is None


def test_check_week_limit_returns_overshoot_when_over_limit():
    all_entries = {
        "2026-05-04": _entry([_slot("08:00", "18:00")]),  # 10h
        "2026-05-05": _entry([_slot("08:00", "18:00")]),  # 10h
        "2026-05-06": _entry([_slot("08:00", "13:00")]),  # 5h -> 25h total
    }
    result = check_week_limit(_settings(), all_entries, "2026-05-04")
    assert result == {
        "iso_year": 2026, "iso_week": 19, "total_minutes": 25 * 60,
        "limit_minutes": 20 * 60,
    }


def test_check_dates_for_warnings_dedupes_per_week():
    all_entries = {
        "2026-05-04": _entry([_slot("08:00", "20:00")]),  # 12h, KW 19
        "2026-05-05": _entry([_slot("08:00", "20:00")]),  # 12h -> 24h in KW 19
    }
    warnings = check_dates_for_warnings(
        _settings(), all_entries, ["2026-05-04", "2026-05-05", "2026-05-06"])
    assert len(warnings) == 1
    assert warnings[0]["iso_week"] == 19


def test_check_dates_for_warnings_skips_inactive_date_but_checks_active_one_in_same_week():
    """Regression (Adversarial-Review): Zeitraum startet mitten in der Woche
    — ein Datum VOR dem Start darf die Woche nicht als 'gesehen' markieren,
    sonst wird ein späteres, aktives Datum derselben ISO-Woche fälschlich
    übersprungen und ein realer Verstoß bleibt unbemerkt."""
    all_entries = {
        "2026-05-04": _entry([_slot("08:00", "18:00")]),  # Mo, vor Zeitraumstart, 10h
        "2026-05-07": _entry([_slot("08:00", "19:00")]),  # Do, im Zeitraum, 11h -> 21h total
    }
    warnings = check_dates_for_warnings(
        _settings(start="2026-05-06", end="2026-07-15"),
        all_entries, ["2026-05-04", "2026-05-07"])
    assert len(warnings) == 1
    assert warnings[0]["iso_week"] == 19


def test_scan_period_for_warnings_empty_when_disabled():
    assert scan_period_for_warnings(_settings(enabled=False), {}) == []


def test_scan_period_for_warnings_finds_all_overshooting_weeks():
    all_entries = {
        "2026-04-06": _entry([_slot("06:00", "20:00")]),  # KW 15, 14h — under
        "2026-05-04": _entry([_slot("06:00", "20:00")]),  # KW 19, 14h
        "2026-05-05": _entry([_slot("06:00", "20:00")]),  # KW 19, 14h -> 28h, over
    }
    warnings = scan_period_for_warnings(
        _settings(start="2026-04-01", end="2026-05-10"), all_entries)
    assert [w["iso_week"] for w in warnings] == [19]


def test_format_limit_warnings_lists_each_week():
    text = format_limit_warnings([
        {"iso_year": 2026, "iso_week": 19, "total_minutes": 25 * 60 + 10,
         "limit_minutes": 20 * 60},
    ])
    # Anzeige wie überall in der UI über Minuten (CLAUDE.md), nicht dezimal.
    assert "25 h 10 min" in text
    assert "Limit 20 h" in text


def test_period_scan_needed_false_when_still_disabled():
    assert period_scan_needed(_wsl(enabled=False), _wsl(enabled=False)) is False


def test_period_scan_needed_true_on_activation():
    assert period_scan_needed(_wsl(enabled=False), _wsl(enabled=True)) is True


def test_period_scan_needed_false_when_deactivated():
    assert period_scan_needed(_wsl(enabled=True), _wsl(enabled=False)) is False


def test_period_scan_needed_true_on_period_change():
    assert period_scan_needed(_wsl(), _wsl(end="2026-08-01")) is True


def test_period_scan_needed_true_on_hours_change():
    """Adversarial-Review-Fix: eine Verschärfung des Stundenlimits bei
    unverändertem Zeitraum muss den Bestandsscan auch auslösen — genau dort
    werden neue Verstöße gegen bestehende Daten sichtbar."""
    assert period_scan_needed(_wsl(max_hours=20.0), _wsl(max_hours=10.0)) is True


def test_period_scan_needed_false_when_nothing_changed():
    assert period_scan_needed(_wsl(), _wsl()) is False
