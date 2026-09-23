"""Tests der Tk-freien Logik des Einstellungs-Dialogs (form_model.py, #132)."""

from src.dialogs.settings_dialog.form_model import is_dirty


def test_identical_values_are_clean():
    assert not is_dirty({"a": 1, "b": "x"}, {"a": 1, "b": "x"})


def test_changed_value_is_dirty():
    assert is_dirty({"name": "Anna"}, {"name": "Ben"})


def test_number_and_numeric_string_are_equal():
    # Settings speichern 20.0, ein Entry liefert "20" — keine Änderung.
    assert not is_dirty({"h": 20.0}, {"h": "20"})
    assert not is_dirty({"h": 20}, {"h": 20.0})
    assert not is_dirty({"h": "20.5"}, {"h": 20.5})
    assert not is_dirty({"h": " 20 "}, {"h": 20})


def test_time_string_stays_a_string():
    assert not is_dirty({"t": "08:00"}, {"t": "08:00"})
    assert is_dirty({"t": "08:00"}, {"t": "08:30"})


def test_bool_is_not_confused_with_number():
    assert is_dirty({"on": True}, {"on": 1})
    assert is_dirty({"on": False}, {"on": "0"})


def test_line_endings_are_normalized():
    assert not is_dirty({"text": "a\r\nb"}, {"text": "a\nb"})


def test_trailing_whitespace_in_text_counts():
    assert is_dirty({"text": "Gruß"}, {"text": "Gruß "})


def test_missing_or_extra_key_is_dirty():
    assert is_dirty({"a": 1}, {"a": 1, "b": 2})
    assert is_dirty({"a": 1, "b": 2}, {"a": 1})


def test_nested_structures_are_compared_deeply():
    assert not is_dirty({"d": {"x": "1"}}, {"d": {"x": 1}})
    assert is_dirty({"l": [1, 2]}, {"l": [1, 3]})


def test_none_is_its_own_value():
    assert not is_dirty({"v": None}, {"v": None})
    assert is_dirty({"v": None}, {"v": ""})
