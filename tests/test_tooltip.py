# tests/test_tooltip.py
import tkinter as tk  # noqa: F401 — Import-Smoke wie test_logging_setup; CI hat tkinter

from src.tooltip import _should_hide_tip


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
