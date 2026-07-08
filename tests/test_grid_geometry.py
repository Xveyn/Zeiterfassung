"""repin_geometry: die fixe Fensterbreite ratcht (waechst mit, schrumpft nie).

Hintergrund: ohne Stundenlohn ist der Footer schmal, mit Lohn breit
(_update_footer, width 16 vs 40). Startet die App ohne Lohn, pinnt
measure_max_width die schmale Breite. Traegt der Nutzer spaeter einen Lohn ein,
wird der Footer breit und repin_geometry waechst das Fenster. Entfernt er ihn
wieder, darf das Fenster NICHT zurueckschrumpfen — sonst springt die Breite bei
jedem Lohn-Ein/Aus. Tk-frei ueber ein gemocktes root."""

from unittest.mock import MagicMock

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
