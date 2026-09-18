"""Tests der Tk-freien Formular-Logik (theme/form_logic.py, #132)."""

import pytest

from src.theme.form_logic import (
    BODY_MAX_HEIGHT,
    MIN_BODY_HEIGHT,
    SCREEN_MARGIN,
    body_height,
    enabled_states,
    is_descendant,
    wheel_route,
    wheel_units,
)


# --- enabled_states ---------------------------------------------------------

def test_top_level_group_follows_its_switch():
    assert enabled_states({"g0": None}, {"g0": True}) == {"g0": True}
    assert enabled_states({"g0": None}, {"g0": False}) == {"g0": False}


def test_nested_group_needs_every_switch_above():
    parents = {"g0": None, "g1": "g0"}
    assert enabled_states(parents, {"g0": True, "g1": True}) == {"g0": True, "g1": True}
    # Unterpunkt an, Hauptpunkt aus → Unterpunkt bleibt grau.
    assert enabled_states(parents, {"g0": False, "g1": True})["g1"] is False
    assert enabled_states(parents, {"g0": True, "g1": False})["g1"] is False


def test_three_levels_deep():
    parents = {"a": None, "b": "a", "c": "b"}
    values = {"a": True, "b": False, "c": True}
    assert enabled_states(parents, values) == {"a": True, "b": False, "c": False}


def test_missing_switch_value_counts_as_off():
    assert enabled_states({"g0": None, "g1": "g0"}, {"g1": True}) == {"g0": False, "g1": False}


def test_missing_ancestor_group_still_counts_its_switch_value():
    """Der Vorfahr einer Gruppe muss nicht selbst ein Eintrag in `parents`
    sein (z.B. eine Gruppe ohne eigenen `depends_on`-Aufruf) — sein Wert im
    `values`-Dict zählt trotzdem. Fehlt dort auch sein Wert, gilt er als aus
    (dieselbe Regel wie bei einem bekannten Vorfahren, s.
    `test_missing_switch_value_counts_as_off`)."""
    parents = {"g1": "g0"}
    assert enabled_states(parents, {"g0": True, "g1": True})["g1"] is True
    assert enabled_states(parents, {"g0": False, "g1": True})["g1"] is False
    assert enabled_states(parents, {"g1": True})["g1"] is False


def test_cycle_is_a_programming_error():
    with pytest.raises(ValueError):
        enabled_states({"a": "b", "b": "a"}, {"a": True, "b": True})


# --- wheel_units ------------------------------------------------------------

def test_x11_buttons_4_and_5():
    assert wheel_units("Linux", 0, 4) == -1
    assert wheel_units("Linux", 0, 5) == 1


def test_windows_delta_in_multiples_of_120():
    assert wheel_units("Windows", 120, None) == -1
    assert wheel_units("Windows", -240, None) == 2


def test_windows_touchpad_fraction_still_moves_one_step():
    assert wheel_units("Windows", 30, None) == -1
    assert wheel_units("Windows", -30, None) == 1


def test_macos_raw_delta():
    assert wheel_units("Darwin", 3, None) == -3
    assert wheel_units("Darwin", -1, None) == 1


def test_zero_delta_does_not_scroll():
    assert wheel_units("Windows", 0, None) == 0
    assert wheel_units("Darwin", 0, None) == 0


# --- wheel_route ------------------------------------------------------------

def test_self_scrolling_widgets_keep_the_wheel():
    assert wheel_route("Text") == "widget"
    assert wheel_route("Listbox") == "widget"


def test_combobox_is_protected():
    assert wheel_route("TCombobox") == "form_block"


def test_spinbox_is_protected():
    # Spinbox (tk) und TSpinbox (ttk) ändern beim Rad ebenfalls ihren Wert —
    # dieselbe Falle wie bei der Combobox.
    assert wheel_route("TSpinbox") == "form_block"
    assert wheel_route("Spinbox") == "form_block"


def test_everything_else_scrolls_the_form():
    for cls in ("Label", "Frame", "Entry", "Checkbutton", "Canvas", "TScrollbar"):
        assert wheel_route(cls) == "form"


# --- is_descendant ----------------------------------------------------------

def test_descendant_by_tk_path():
    assert is_descendant(".!toplevel.!canvas.!frame.!label", ".!toplevel.!canvas")
    assert is_descendant(".!toplevel.!canvas", ".!toplevel.!canvas")


def test_sibling_with_common_prefix_is_not_a_descendant():
    # ".!canvas2" beginnt mit ".!canvas", ist aber ein Geschwister.
    assert not is_descendant(".!toplevel.!canvas2.!label", ".!toplevel.!canvas")


def test_everything_descends_from_root():
    assert is_descendant(".!toplevel", ".")


# --- body_height ------------------------------------------------------------

def test_short_content_keeps_its_natural_height():
    assert body_height(300, 1.0, 1440) == 300


def test_capped_at_max_height_times_scale():
    assert body_height(2000, 1.0, 1440) == BODY_MAX_HEIGHT
    assert body_height(2000, 1.5, 1440) == round(BODY_MAX_HEIGHT * 1.5)


def test_capped_by_screen_height():
    # 1.5 × 600 = 900, aber 1000 − 1.5 × 160 = 760 ist enger.
    assert body_height(2000, 1.5, 1000) == 1000 - round(SCREEN_MARGIN * 1.5)


def test_tiny_screen_keeps_a_usable_minimum():
    assert body_height(2000, 2.0, 400) == MIN_BODY_HEIGHT


def test_minimum_never_pads_short_content():
    assert body_height(120, 2.0, 400) == 120
