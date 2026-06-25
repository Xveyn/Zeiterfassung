# tests/test_tooltip.py
import tkinter as tk  # noqa: F401 — Import-Smoke wie test_logging_setup; CI hat tkinter

import src.tooltip as tooltip
from src.tooltip import _should_hide_tip


class _FakeTip:
    """Minimaler Stand-in für _Tooltip — nur das, was die Single-Active-Registry
    berührt (tk-frei, kein Display nötig)."""

    def __init__(self):
        self.close_calls = 0

    def _close(self):
        self.close_calls += 1
        tooltip._clear_active_tip(self)


def _reset_active():
    tooltip._active_tip = None


def test_showing_new_tooltip_closes_previous():
    # Kern von #66: ein neues Tooltip schließt das vorher sichtbare.
    _reset_active()
    a, b = _FakeTip(), _FakeTip()
    tooltip._set_active_tip(a)
    tooltip._set_active_tip(b)
    assert a.close_calls == 1
    assert b.close_calls == 0
    assert tooltip._active_tip is b


def test_reactivating_same_tooltip_does_not_close_itself():
    _reset_active()
    a = _FakeTip()
    tooltip._set_active_tip(a)
    tooltip._set_active_tip(a)
    assert a.close_calls == 0
    assert tooltip._active_tip is a


def test_clear_active_only_clears_when_it_is_the_active_one():
    _reset_active()
    a, b = _FakeTip(), _FakeTip()
    tooltip._set_active_tip(a)
    tooltip._clear_active_tip(b)  # b ist nicht aktiv -> no-op
    assert tooltip._active_tip is a
    tooltip._clear_active_tip(a)
    assert tooltip._active_tip is None


def test_hide_when_minimized_even_if_pointer_over_widget():
    # Kern des Bugs: Fenster iconified, Zeiger steht (mangels <Leave>) noch
    # mitten im Widget — trotzdem schließen.
    rects = [(0, 0, 100, 50)]
    assert _should_hide_tip("iconic", rects, (10, 10)) is True


def test_hide_when_withdrawn_to_tray():
    rects = [(0, 0, 100, 50)]
    assert _should_hide_tip("withdrawn", rects, (10, 10)) is True


def test_stay_open_when_normal_and_pointer_inside():
    rects = [(0, 0, 100, 50)]
    assert _should_hide_tip("normal", rects, (10, 10)) is False


def test_stay_open_when_zoomed_and_pointer_inside():
    # Maximiertes Fenster ('zoomed') ist sichtbar -> offen lassen.
    rects = [(0, 0, 100, 50)]
    assert _should_hide_tip("zoomed", rects, (10, 10)) is False


def test_hide_when_pointer_outside_all_widgets():
    rects = [(0, 0, 100, 50)]
    assert _should_hide_tip("normal", rects, (500, 500)) is True


def test_hide_when_no_widgets_left():
    # Alle getrackten Widgets zerstört (Kalender-Re-Render) -> schließen.
    assert _should_hide_tip("normal", [], (10, 10)) is True


def test_pointer_on_lower_right_edge_is_outside():
    # Halb-offenes Intervall (wx <= x < wx+ww): x+w / y+h zählen nicht mehr dazu.
    rects = [(0, 0, 100, 50)]
    assert _should_hide_tip("normal", rects, (100, 50)) is True


def test_multiple_widgets_pointer_over_second():
    # Geteiltes Tooltip (Frame + Children): Zeiger über irgendeinem -> offen.
    rects = [(0, 0, 100, 50), (200, 0, 100, 50)]
    assert _should_hide_tip("normal", rects, (250, 10)) is False
