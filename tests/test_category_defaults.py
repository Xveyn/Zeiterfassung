"""Pure Logik für die Per-Kategorie-Standardzeiten (Start/Ende/Pause).

resolve_slot_defaults wendet einen Per-Feld-Fallback auf die globalen
Standardwerte an; rename/remove halten das category_times-Dict konsistent
zur Kategorie-Liste."""

from src.category_defaults import resolve_slot_defaults

G = ("08:00", "16:00", 30)  # globale Standardwerte (start, end, pause)


# --- resolve_slot_defaults ---


def test_unknown_category_falls_back_to_global():
    assert resolve_slot_defaults({}, "Office", *G) == ("08:00", "16:00", 30)


def test_empty_category_string_falls_back_to_global():
    times = {"Office": {"start": "09:00", "end": "17:00", "pause": 0}}
    assert resolve_slot_defaults(times, "", *G) == ("08:00", "16:00", 30)


def test_full_category_overrides_all_fields():
    times = {"Office": {"start": "09:00", "end": "17:00", "pause": 45}}
    assert resolve_slot_defaults(times, "Office", *G) == ("09:00", "17:00", 45)


def test_per_field_fallback_missing_keys():
    """Fehlende Keys im Eintrag → globaler Fallback pro Feld."""
    times = {"Office": {"start": "09:00"}}
    assert resolve_slot_defaults(times, "Office", *G) == ("09:00", "16:00", 30)


def test_per_field_fallback_empty_strings():
    """Leere Strings zählen wie 'nicht gesetzt' → globaler Fallback."""
    times = {"Office": {"start": "", "end": "", "pause": ""}}
    assert resolve_slot_defaults(times, "Office", *G) == ("08:00", "16:00", 30)


def test_pause_zero_is_kept_not_treated_as_unset():
    times = {"Office": {"pause": 0}}
    assert resolve_slot_defaults(times, "Office", *G) == ("08:00", "16:00", 0)


def test_pause_string_is_coerced_to_int():
    times = {"Office": {"pause": "45"}}
    assert resolve_slot_defaults(times, "Office", *G) == ("08:00", "16:00", 45)


def test_pause_garbage_falls_back_to_global():
    times = {"Office": {"pause": "abc"}}
    assert resolve_slot_defaults(times, "Office", *G) == ("08:00", "16:00", 30)


def test_non_dict_entry_falls_back_to_global():
    times = {"Office": "kaputt"}
    assert resolve_slot_defaults(times, "Office", *G) == ("08:00", "16:00", 30)
