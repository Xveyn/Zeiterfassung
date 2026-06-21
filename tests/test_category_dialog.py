"""collect_categories baut aus den Inline-Zeilen (Name + Start/Ende/Pause) die
beiden persistierten Strukturen: die categories-Liste und das category_times-
Dict. STANDARD/leere Felder entfallen → Per-Feld-Fallback auf global."""

from src.dialogs.category_dialog import STANDARD, collect_categories


def _row(name, start=STANDARD, end=STANDARD, pause=STANDARD):
    return {"name": name, "start": start, "end": end, "pause": pause}


def test_empty_rows_yield_empty_structures():
    assert collect_categories([]) == ([], {})


def test_name_only_row_has_no_times():
    cats, times = collect_categories([_row("Office")])
    assert cats == ["Office"]
    assert times == {}


def test_full_row_persists_all_fields():
    cats, times = collect_categories([_row("Office", "09:00", "17:00", "30")])
    assert cats == ["Office"]
    assert times == {"Office": {"start": "09:00", "end": "17:00", "pause": 30}}


def test_partial_row_only_persists_set_fields():
    cats, times = collect_categories([_row("Office", start="09:00")])
    assert cats == ["Office"]
    assert times == {"Office": {"start": "09:00"}}


def test_pause_zero_is_kept():
    _, times = collect_categories([_row("Office", pause="0")])
    assert times == {"Office": {"pause": 0}}


def test_name_is_trimmed():
    cats, _ = collect_categories([_row("  Office  ")])
    assert cats == ["Office"]


def test_empty_name_row_is_skipped():
    cats, times = collect_categories([_row("   ", "09:00", "17:00", "30")])
    assert cats == []
    assert times == {}


def test_duplicate_name_keeps_first_occurrence():
    rows = [
        _row("Office", "09:00", "17:00", "30"),
        _row("Office", "10:00", "18:00", "45"),
    ]
    cats, times = collect_categories(rows)
    assert cats == ["Office"]
    assert times == {"Office": {"start": "09:00", "end": "17:00", "pause": 30}}


def test_order_is_preserved():
    cats, _ = collect_categories([_row("B"), _row("A"), _row("C")])
    assert cats == ["B", "A", "C"]


def test_multiple_categories_mixed_times():
    rows = [
        _row("Office", "09:00", "17:00", "30"),
        _row("Homeoffice"),
        _row("Kunde", start="08:00"),
    ]
    cats, times = collect_categories(rows)
    assert cats == ["Office", "Homeoffice", "Kunde"]
    assert times == {
        "Office": {"start": "09:00", "end": "17:00", "pause": 30},
        "Kunde": {"start": "08:00"},
    }
