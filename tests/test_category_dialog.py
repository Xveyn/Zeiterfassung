"""collect_categories baut aus den Inline-Zeilen (Name + Start/Ende/Pause) die
beiden persistierten Strukturen: die categories-Liste und das category_times-
Dict. STANDARD/leere Felder entfallen → Per-Feld-Fallback auf global."""

from src.dialogs.category_dialog import (
    STANDARD, collect_categories, row_defaults_from_entry,
)


def _row(name, start=STANDARD, end=STANDARD, pause=STANDARD,
         mode="general", days=None):
    return {"name": name, "start": start, "end": end, "pause": pause,
            "mode": mode, "days": days or {}}


def _pd_days(**kw):
    """kw wie mon=("09:00","18:00") → {"mon": {"start":..,"end":..}}."""
    return {k: {"start": v[0], "end": v[1]} for k, v in kw.items()}


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


def test_per_day_row_builds_nested_entry():
    rows = [_row("Homeoffice", mode="per_day", pause="0",
                 days=_pd_days(mon=("09:00", "18:00"), fri=("09:00", "14:00")))]
    cats, times = collect_categories(rows)
    assert cats == ["Homeoffice"]
    assert times == {"Homeoffice": {
        "mode": "per_day", "pause": 0,
        "days": {"mon": {"start": "09:00", "end": "18:00"},
                 "fri": {"start": "09:00", "end": "14:00"}},
    }}


def test_per_day_empty_fields_drop_out():
    rows = [_row("X", mode="per_day",
                 days=_pd_days(mon=("09:00", STANDARD), tue=(STANDARD, STANDARD)))]
    _, times = collect_categories(rows)
    # tue komplett leer entfällt; mon behält nur start
    assert times == {"X": {"mode": "per_day", "days": {"mon": {"start": "09:00"}}}}


def test_per_day_without_any_data_is_dropped():
    rows = [_row("X", mode="per_day", pause=STANDARD,
                 days=_pd_days(mon=(STANDARD, STANDARD)))]
    cats, times = collect_categories(rows)
    assert cats == ["X"]
    assert times == {}


def test_per_day_with_only_pause_keeps_entry():
    rows = [_row("X", mode="per_day", pause="45", days={})]
    _, times = collect_categories(rows)
    assert times == {"X": {"mode": "per_day", "days": {}, "pause": 45}}


def test_hydrate_general_entry():
    r = row_defaults_from_entry({"start": "09:30", "end": "17:00", "pause": 30})
    assert r["mode"] == "general"
    assert (r["start"], r["end"], r["pause"]) == ("09:30", "17:00", "30")


def test_hydrate_per_day_entry_fills_all_days():
    e = {"mode": "per_day", "pause": 0,
         "days": {"mon": {"start": "09:00", "end": "18:00"}}}
    r = row_defaults_from_entry(e)
    assert r["mode"] == "per_day"
    assert r["pause"] == "0"
    assert r["days"]["mon"] == {"start": "09:00", "end": "18:00"}
    # nicht gesetzte Tage → STANDARD in beiden Feldern
    assert r["days"]["sun"] == {"start": STANDARD, "end": STANDARD}


def test_hydrate_corrupt_entry_is_general_standard():
    r = row_defaults_from_entry("kaputt")
    assert r["mode"] == "general"
    assert (r["start"], r["end"], r["pause"]) == (STANDARD, STANDARD, STANDARD)


def test_roundtrip_preserves_per_day_entry():
    e = {"mode": "per_day", "pause": 0,
         "days": {"mon": {"start": "09:00", "end": "18:00"},
                  "fri": {"start": "09:00", "end": "14:00"}}}
    cats, times = collect_categories([{"name": "Homeoffice", **row_defaults_from_entry(e)}])
    assert cats == ["Homeoffice"]
    assert times == {"Homeoffice": e}


def test_roundtrip_preserves_general_entry():
    e = {"start": "09:30", "end": "17:00", "pause": 30}
    _, times = collect_categories([{"name": "Office", **row_defaults_from_entry(e)}])
    assert times == {"Office": e}
