"""repin_geometry: die fixe Fensterbreite ratcht (waechst mit, schrumpft nie).

Hintergrund: ohne Stundenlohn ist der Footer schmal, mit Lohn breit
(_update_footer, width 16 vs 40). Startet die App ohne Lohn, pinnt
measure_max_width die schmale Breite. Traegt der Nutzer spaeter einen Lohn ein,
wird der Footer breit und repin_geometry waechst das Fenster. Entfernt er ihn
wieder, darf das Fenster NICHT zurueckschrumpfen — sonst springt die Breite bei
jedem Lohn-Ein/Aus. Tk-frei ueber ein gemocktes root."""

from unittest.mock import MagicMock
import tkinter

from src.grid_renderer import GridRenderer


def _renderer_with_root(reqwidth, reqheight=400):
    root = MagicMock()
    root.winfo_reqwidth.return_value = reqwidth
    root.winfo_reqheight.return_value = reqheight
    settings = MagicMock(get=lambda k, d=None: d)
    r = GridRenderer(
        root=root, storage=object(), settings=settings,
        reservation_store=None, conflicts_store=None,
        on_cell_click=lambda d: None, on_cell_right_click=lambda d: None,
        reservations_active=lambda: False,
    )
    return r, root


def test_repin_grows_and_pins_wide_footer():
    r, root = _renderer_with_root(reqwidth=721)
    r._fixed_width = 552  # measure_max_width hat schmal gepinnt (Start ohne Lohn)
    r.repin_geometry()
    assert r._fixed_width == 721
    root.geometry.assert_called_once_with("721x400")


def test_repin_does_not_shrink_below_widest_seen():
    r, root = _renderer_with_root(reqwidth=721)
    r._fixed_width = 552
    r.repin_geometry()  # Lohn gesetzt -> breit (721)

    # Lohn wieder entfernt: reqwidth faellt zurueck auf schmal, Fenster bleibt breit
    root.winfo_reqwidth.return_value = 482
    r.repin_geometry()
    assert r._fixed_width == 721
    assert root.geometry.call_args_list[-1].args[0] == "721x400"


def test_repin_suppressed_during_measure_leaves_geometry_untouched():
    r, root = _renderer_with_root(reqwidth=721)
    r._fixed_width = 552
    r._suppress_geometry = True
    r.repin_geometry()
    root.geometry.assert_not_called()
    assert r._fixed_width == 552  # kein Ratchet waehrend der Vorab-Messung


# --- workweek_only: Nur-Werktage-Modus für Kalender-Spalten ---


def _renderer_with_settings(**values):
    """GridRenderer mit gestubbten Settings; nicht gesetzte Keys → None."""
    root = MagicMock()
    root.winfo_reqwidth.return_value = 700
    root.winfo_reqheight.return_value = 400
    settings = MagicMock(get=lambda k, d=None: values.get(k, d))
    return GridRenderer(
        root=root, storage=object(), settings=settings,
        reservation_store=None, conflicts_store=None,
        on_cell_click=lambda d: None, on_cell_right_click=lambda d: None,
        reservations_active=lambda: False,
    )


def test_workweek_only_hides_weekend_even_when_show_weekend_is_on():
    """Der Nur-Werktage-Modus überstimmt den Kalender-Schalter — sonst stünde
    im App-Tab ein Haken, der sichtbar nichts tut."""
    r = _renderer_with_settings(show_weekend=True, workweek_only=True)
    assert r._visible_day_count() == 5


def test_show_weekend_still_governs_when_workweek_only_is_off():
    assert _renderer_with_settings(
        show_weekend=True, workweek_only=False)._visible_day_count() == 7
    assert _renderer_with_settings(
        show_weekend=False, workweek_only=False)._visible_day_count() == 5


def test_cell_metrics_respect_workweek_only():
    """_cell_layout_metrics muss wide_cells aus _visible_day_count ableiten,
    nicht show_weekend erneut lesen. Sonst haben 5-Spalten-Layouts die
    Zell-Metriken für 7 Spalten (kleinere Schrift, gedrängter)."""
    root = MagicMock()
    root.winfo_reqwidth.return_value = 700
    root.winfo_reqheight.return_value = 400
    root.pack_slaves.return_value = []
    settings = MagicMock(get=lambda k, d=None: {
        "show_weekend": True,
        "workweek_only": True,
    }.get(k, d))
    r = GridRenderer(
        root=root, storage=object(), settings=settings,
        reservation_store=None, conflicts_store=None,
        on_cell_click=lambda d: None, on_cell_right_click=lambda d: None,
        reservations_active=lambda: False,
    )
    # Mit Tk-Frame für die Probe-Messung
    frame = tkinter.Frame()
    cell_size, entry_font, holiday_font, wide_cells = r._cell_layout_metrics(frame)
    frame.destroy()
    # Bei workweek_only=True sind 5 Spalten sichtbar → wide_cells MUSS True sein
    assert wide_cells is True, (
        "workweek_only=True → 5 Spalten sichtbar → wide_cells=True "
        "(nicht aus show_weekend=True ablesen)"
    )
