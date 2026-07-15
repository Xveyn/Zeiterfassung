"""Pure Kernlogik des gemeinsamen Datums-Zeilen-Widgets (Audit M14).

Nur `max_day_for` ist Tk-frei testbar; der Widget-Aufbau (build_date_row)
braucht ein Tk-Display und wird — wie der Rest der Tk-Schicht — nicht headless
getestet."""

from src.dialogs.date_row import max_day_for


def test_max_day_for_leap_february():
    assert max_day_for("2", "2024") == 29


def test_max_day_for_common_february():
    assert max_day_for("2", "2023") == 28


def test_max_day_for_30_day_month():
    assert max_day_for("4", "2024") == 30


def test_max_day_for_31_day_month():
    assert max_day_for("1", "2024") == 31


def test_max_day_for_non_numeric_falls_back_to_31():
    # Robustheits-Kern: der Combobox kann während der Eingabe einen
    # nicht-numerischen Zwischenwert tragen — vorher crashten period_picker
    # und tab_work hier (Audit M14).
    assert max_day_for("abc", "2024") == 31
    assert max_day_for("2", "") == 31


def test_max_day_for_out_of_range_month_falls_back_to_31():
    assert max_day_for("13", "2024") == 31
    assert max_day_for("0", "2024") == 31
