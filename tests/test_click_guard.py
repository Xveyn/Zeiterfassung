"""Stray-Klick-Guard (#44): Klicks unmittelbar nach Dialog-Schließen
unterdrücken, damit ein durchschlagender Schließ-Klick nicht versehentlich
eine Kalenderzelle trifft.

Getestet wird die reine Entscheidungslogik `_stray_click_suppressed`. Die Tk-
Verdrahtung (Stempel in `center_dialog_on_parent`, Guard in
`_open_dialog`/`_delete_day`) ist UI-Schicht und wird wie dort üblich manuell
verifiziert.
"""
from src.theme import _stray_click_suppressed, STRAY_CLICK_GUARD_S


def test_no_dialog_closed_never_suppresses():
    # closed_at = 0/None → es wurde nie ein Dialog geschlossen → Klick erlaubt.
    assert _stray_click_suppressed(0, 1000.0) is False
    assert _stray_click_suppressed(None, 1000.0) is False


def test_click_within_window_is_suppressed():
    closed = 1000.0
    assert _stray_click_suppressed(closed, closed + STRAY_CLICK_GUARD_S / 2) is True


def test_click_after_window_is_allowed():
    closed = 1000.0
    assert _stray_click_suppressed(closed, closed + STRAY_CLICK_GUARD_S * 2) is False


def test_window_boundary_is_exclusive():
    # Genau am Fensterende nicht mehr unterdrücken (Grenze offen).
    closed = 1000.0
    assert _stray_click_suppressed(closed, closed + STRAY_CLICK_GUARD_S) is False


def test_clock_anomaly_now_before_close_not_suppressed():
    # now < closed_at (mit time.monotonic praktisch unmöglich) → defensiv erlauben.
    assert _stray_click_suppressed(1000.0, 999.0) is False
