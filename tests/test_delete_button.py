"""Sichtbarkeit des macOS-Lösch-Buttons in der Tageszelle.

Reine Entscheidungslogik `_should_show_delete_button`. Die Tk-Verdrahtung
(_add_delete_button, Aufruf in _build_day_cell, Hover-Repaint) ist UI-Schicht
und wird wie üblich manuell auf macOS verifiziert.
"""
from src.theme import _should_show_delete_button


def test_not_macos_never_shows():
    assert _should_show_delete_button(False, True, True) is False
    assert _should_show_delete_button(False, True, False) is False
    assert _should_show_delete_button(False, False, True) is False


def test_macos_without_deletable_units_hidden():
    assert _should_show_delete_button(True, False, False) is False


def test_macos_with_entry_shows():
    assert _should_show_delete_button(True, True, False) is True


def test_macos_with_reservation_only_shows():
    assert _should_show_delete_button(True, False, True) is True


def test_macos_with_both_shows():
    assert _should_show_delete_button(True, True, True) is True


def test_delete_button_shown_for_vacation_only_day():
    # Ein reiner Urlaubstag ist löschbar (die ganze Periode) — auf macOS
    # braucht er daher das ✕, weil <Button-3> dort unzuverlässig ist.
    assert _should_show_delete_button(True, False, False, True) is True


def test_delete_button_hidden_without_any_unit():
    assert _should_show_delete_button(True, False, False, False) is False


def test_delete_button_stays_windows_only_negative_for_vacation():
    assert _should_show_delete_button(False, False, False, True) is False
