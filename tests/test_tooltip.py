# tests/test_tooltip.py
import tkinter as tk  # noqa: F401 — Import-Smoke wie test_logging_setup; CI hat tkinter

import src.tooltip as tooltip
from src.tooltip import _resolve_text, _should_hide_tip


class _FakeTip:
    """Minimaler Stand-in für _Tooltip — nur das, was die Single-Active-Registry
    berührt (tk-frei, kein Display nötig)."""

    def __init__(self, window=None):
        self.close_calls = 0
        self.window = window

    def _close(self):
        self.close_calls += 1
        tooltip._clear_active_tip(self)

    def _detach_window(self):
        window, self.window = self.window, None
        tooltip._clear_active_tip(self)
        return window


def _reset_active():
    tooltip._active_tip = None


def test_new_tooltip_takes_over_the_open_window():
    """Nur eines gleichzeitig (#66) — aber ohne Fenster abzubauen: ein neues
    Tooltip übernimmt das offene Fenster des alten. Abbauen und neu anlegen
    blendete KWin bei jeder Zelle aus (Schleppe beim Weiterfahren)."""
    _reset_active()
    window = object()
    a, b = _FakeTip(window), _FakeTip()
    tooltip._active_tip = a
    assert tooltip._claim_active(b) is window
    assert a.window is None
    assert a.close_calls == 0
    assert tooltip._active_tip is b


def test_claim_without_open_tooltip_yields_no_window():
    _reset_active()
    b = _FakeTip()
    assert tooltip._claim_active(b) is None
    assert tooltip._active_tip is b


def test_reclaiming_same_tooltip_keeps_its_window():
    _reset_active()
    window = object()
    a = _FakeTip(window)
    tooltip._active_tip = a
    assert tooltip._claim_active(a) is None
    assert a.window is window
    assert tooltip._active_tip is a


def test_clear_active_only_clears_when_it_is_the_active_one():
    _reset_active()
    a, b = _FakeTip(), _FakeTip()
    tooltip._active_tip = a
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


def test_hide_when_grab_active_even_if_pointer_over_widget():
    # Ein modaler Dialog (z.B. Löschen-Bestätigung) hält den Tk-Grab. Das
    # Tooltip-Toplevel ist -topmost und bliebe sonst optisch über dem Dialog
    # liegen, obwohl der Zeiger (mangels <Leave>) noch im Widget steht.
    rects = [(0, 0, 100, 50)]
    assert _should_hide_tip("normal", rects, (10, 10), grab_active=True) is True


def test_resolve_text_returns_plain_string_unchanged():
    assert _resolve_text("Einstellungen") == "Einstellungen"


def test_resolve_text_calls_callable_at_display_time():
    # Kern der dynamischen Variante: die Pfeil-Buttons blättern je nach
    # Ansicht Monate oder Wochen — der Text muss beim Anzeigen entstehen,
    # nicht beim Anhängen.
    view = {"mode": "month"}

    def label():
        return "Vorheriger Monat" if view["mode"] == "month" else "Vorherige Woche"

    assert _resolve_text(label) == "Vorheriger Monat"
    view["mode"] = "week"
    assert _resolve_text(label) == "Vorherige Woche"


def test_resolve_text_of_none_is_empty_string():
    # Leerer Text unterdrückt die Anzeige (siehe _show) — None darf dabei
    # nicht durchschlagen und ein "None"-Popup erzeugen.
    assert _resolve_text(None) == ""


def test_resolve_text_stringifies_callable_result():
    assert _resolve_text(lambda: "") == ""


# --- Anzeigeverzögerung ------------------------------------------------------
# Ohne Verzögerung erzeugte jede Zelle, über die der Zeiger huscht, ein eigenes
# Fenster und zerstörte es Millisekunden später. Auf KDE blendete KWin jedes
# davon noch aus — ungemalte als graue Rechtecke, gemalte als Schleppe.

def test_first_tooltip_waits_for_the_show_delay():
    _reset_active()
    assert tooltip._show_delay_ms(tooltip._active_tip) == tooltip.SHOW_DELAY_MS
    assert tooltip.SHOW_DELAY_MS > 0


def test_tooltip_follows_immediately_while_another_is_open():
    """Wer einen Tooltip schon sieht, will beim Weiterfahren den nächsten
    sofort — wie System-Tooltips."""
    _reset_active()
    a = _FakeTip()
    tooltip._active_tip = a
    assert tooltip._show_delay_ms(tooltip._active_tip) == 0

