# tests/test_tray_linux.py
"""Pure Menü-/Icon-Logik des Linux-SNI-Backends (#42).

Läuft auf JEDER Plattform: das Modul importiert dbus_fast und PIL nur lazy in
Funktionen, hier wird ausschließlich die D-Bus-freie Schicht geprüft.
"""

from src.tray import build_menu_model
from src.tray_linux import MenuState, build_menu_nodes


def _model(sync_visible=True):
    """Menü-Modell wie es ui.py liefert: Anzeigen | — | Senden, Sync | — | Beenden."""
    return build_menu_model(
        lambda: None, lambda: None,
        [("Senden", lambda: None, None),
         ("Sync", lambda: None, lambda: sync_visible)],
    )


def test_nodes_have_sequential_ids_starting_at_one():
    nodes = build_menu_nodes(_model())
    assert [n.id for n in nodes] == [1, 2, 3, 4, 5, 6]


def test_separators_are_typed_and_carry_no_label():
    nodes = build_menu_nodes(_model())
    separators = [n for n in nodes if n.props.get("type") == "separator"]
    assert len(separators) == 2
    assert all("label" not in n.props for n in separators)


def test_items_carry_label_and_are_enabled():
    nodes = build_menu_nodes(_model())
    labels = [n.props["label"] for n in nodes if n.props["type"] == "standard"]
    assert labels == ["Anzeigen", "Senden", "Sync", "Beenden"]
    assert all(n.props["enabled"] is True
               for n in nodes if n.props["type"] == "standard")


def test_layout_root_is_a_submenu_with_all_children():
    state = MenuState(_model())
    root_id, root_props, children = state.layout()
    assert root_id == 0
    assert root_props["children-display"] == "submenu"
    assert [child_id for child_id, _props, _kids in children] == [1, 2, 3, 4, 5, 6]


def test_visible_callable_is_evaluated_into_the_layout():
    state = MenuState(_model(sync_visible=False))
    _root_id, _root_props, children = state.layout()
    by_label = {props.get("label"): props for _id, props, _kids in children}
    assert by_label["Sync"]["visible"] is False
    assert by_label["Senden"]["visible"] is True


def test_refresh_bumps_revision_only_when_visibility_changed():
    visible = {"sync": True}
    model = build_menu_model(
        lambda: None, lambda: None,
        [("Sync", lambda: None, lambda: visible["sync"])],
    )
    state = MenuState(model)
    before = state.revision

    assert state.refresh() is False
    assert state.revision == before

    visible["sync"] = False
    assert state.refresh() is True
    assert state.revision == before + 1


def test_dispatch_calls_the_callback_of_that_node():
    clicked = []
    model = build_menu_model(
        lambda: clicked.append("show"), lambda: clicked.append("quit"),
        [("Senden", lambda: clicked.append("send"), None)],
    )
    state = MenuState(model)
    send_id = next(n.id for n in build_menu_nodes(model)
                   if n.props.get("label") == "Senden")

    assert state.dispatch(send_id) is True
    assert clicked == ["send"]


def test_dispatch_on_separator_or_unknown_id_is_a_noop():
    state = MenuState(_model())
    assert state.dispatch(2) is False      # Separator
    assert state.dispatch(99) is False     # gibt es nicht


def test_throwing_visible_callable_keeps_the_entry_visible():
    def boom():
        raise RuntimeError("Settings nicht lesbar")

    model = build_menu_model(lambda: None, lambda: None,
                             [("Sync", lambda: None, boom)])
    state = MenuState(model)
    _root_id, _root_props, children = state.layout()
    by_label = {props.get("label"): props for _id, props, _kids in children}
    assert by_label["Sync"]["visible"] is True


def test_throwing_callback_does_not_escape_dispatch():
    def boom():
        raise RuntimeError("Dialog kaputt")

    model = build_menu_model(lambda: None, lambda: None,
                             [("Senden", boom, None)])
    state = MenuState(model)
    send_id = next(n.id for n in build_menu_nodes(model)
                   if n.props.get("label") == "Senden")
    assert state.dispatch(send_id) is True   # geschluckt, nicht geworfen


import os

import pytest

from src.tray_linux import argb32_from_rgba, icon_pixmaps


def test_argb32_reorders_one_pixel():
    # RGBA (1,2,3,4) → ARGB (4,1,2,3): SNI erwartet ARGB32 in Network-Byte-Order.
    assert argb32_from_rgba(bytes([1, 2, 3, 4])) == bytes([4, 1, 2, 3])


def test_argb32_reorders_every_pixel_and_keeps_length():
    rgba = bytes([1, 2, 3, 4, 10, 20, 30, 40])
    assert argb32_from_rgba(rgba) == bytes([4, 1, 2, 3, 40, 10, 20, 30])
    assert len(argb32_from_rgba(rgba)) == len(rgba)


def test_icon_pixmaps_without_png_returns_empty_list(tmp_path):
    # Kein Wurf: ein Item ohne Pixmap ist besser als gar kein Tray.
    assert icon_pixmaps(str(tmp_path)) == []


def test_icon_pixmaps_reads_the_app_icon_in_requested_sizes():
    pytest.importorskip("PIL")  # nicht in requirements-test.txt
    # Repo-Root aus __file__ ableiten statt "." — der Test darf nicht davon
    # abhängen, aus welchem Verzeichnis pytest gestartet wurde.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pixmaps = icon_pixmaps(repo_root, sizes=(16, 32))
    assert [(w, h) for w, h, _data in pixmaps] == [(16, 16), (32, 32)]
    assert len(pixmaps[0][2]) == 16 * 16 * 4
    assert len(pixmaps[1][2]) == 32 * 32 * 4


from src.tray_linux import _safe


def test_safe_swallows_a_throwing_callback():
    def boom():
        raise RuntimeError("kaputt")

    _safe(boom)   # darf nicht durchschlagen


def test_safe_runs_a_normal_callback():
    calls = []
    _safe(lambda: calls.append("ran"))
    assert calls == ["ran"]


from src.tray_linux import LinuxTrayBackend


def test_backend_keeps_the_facade_constructor_signature():
    """Die Fassade instanziiert alle Backends gleich (tray.TrayIcon.start)."""
    backend = LinuxTrayBackend("res", on_show=lambda: None,
                               on_quit=lambda: None, actions=[])
    assert backend.resource_path == "res"


def test_icon_pixmaps_returns_pixmaps_only_when_png_present(tmp_path):
    """`icon_pixmaps` nimmt einen einzelnen Pfad entgegen — dieser Test prüft
    nur "PNG vorhanden -> Pixmaps, PNG fehlt -> leere Liste", bereits
    abgedeckt von `test_icon_pixmaps_reads_the_app_icon_in_requested_sizes`
    und `test_icon_pixmaps_without_png_returns_empty_list` nebenan. Die
    eigentliche Unterscheidung resource_path vs. get_base_path() (der
    Linux-Icon-Befund) prüft `tests/test_paths.py::
    test_is_not_the_data_dir_when_they_differ` — dort liegen beide Pfade
    tatsächlich nebeneinander vor."""
    pytest.importorskip("PIL")
    from PIL import Image
    bundle = tmp_path / "bundle" / "assets"
    bundle.mkdir(parents=True)
    Image.new("RGBA", (8, 8), (1, 2, 3, 4)).save(bundle / "margenheld-icon.png")
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    assert icon_pixmaps(str(tmp_path / "bundle"), sizes=(8,)) != []
    assert icon_pixmaps(str(data_dir), sizes=(8,)) == []


def test_stop_without_start_is_a_noop():
    backend = LinuxTrayBackend("base", on_show=lambda: None, on_quit=lambda: None)
    backend.stop()
    backend.stop()   # idempotent, auch mehrfach


def test_notify_without_start_is_a_noop():
    backend = LinuxTrayBackend("base", on_show=lambda: None, on_quit=lambda: None)
    backend.notify("hallo")   # darf nicht werfen


def test_start_raises_when_no_session_bus_is_reachable(monkeypatch):
    """Ohne Session-Bus muss start() SYNCHRON werfen — ui.py::_apply_tray_setting
    fängt das, zeigt eine Meldung und schaltet die Optionen ab."""
    pytest.importorskip("dbus_fast")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/nonexistent/zeit-test")
    backend = LinuxTrayBackend(".", on_show=lambda: None, on_quit=lambda: None)
    with pytest.raises(Exception):  # noqa: B017 — Verbindungsfehler ist je nach Umgebung ein anderer Typ, Test prüft nur "wirft synchron"
        backend.start()
    backend.stop()   # muss auch nach fehlgeschlagenem Start aufräumbar sein


import asyncio


def test_stop_reaps_a_thread_still_hanging_after_a_start_timeout(monkeypatch):
    """Regression für Review-Finding 3: `_stopping` muss VOR `_serve` existieren
    (jetzt in `_run` angelegt statt in `_serve` nach dem Bus-Connect). Sonst
    fände ein stop() während eines Start-Timeouts kein Event zum
    Signalisieren vor, verbuchte Thread/Event trotzdem als erledigt (auf
    None) — ein späterer stop() hätte den tatsächlich noch laufenden Thread
    nie mehr erreicht, weil ihm dafür schlicht das Mittel fehlte.

    `_serve` wird durch eine Fake-Coroutine ersetzt, die absichtlich länger
    braucht als `START_TIMEOUT_S` (simuliert ein hängendes `connect()`) — kein
    `dbus_fast` nötig, läuft auf jeder Plattform. Existiert `self._stopping`
    zu diesem Zeitpunkt NICHT (Bug), hat die Fake-Coroutine kein Mittel, um
    von außen aufgeweckt zu werden, und bleibt bewusst lange hängen — genau
    das reproduziert den gemeldeten Zustand statt ihn nur zu behaupten.
    """

    async def fake_serve(self, ready):
        await asyncio.sleep(0.2)   # simuliert eine _serve, die länger als START_TIMEOUT_S braucht
        stopping = self._stopping
        if stopping is None:
            # Ohne den Fix gibt es an dieser Stelle kein Event — die
            # Coroutine hat keine Möglichkeit, von stop() erreicht zu werden,
            # und hängt (hier absichtlich weit über SHUTDOWN_TIMEOUT_S
            # hinaus) unsichtbar weiter.
            await asyncio.sleep(10)
            return
        await stopping.wait()

    monkeypatch.setattr(LinuxTrayBackend, "_serve", fake_serve)

    backend = LinuxTrayBackend("base", on_show=lambda: None, on_quit=lambda: None)
    backend.START_TIMEOUT_S = 0.05

    # Anders als beim echten Bus-Fehlerpfad ist der Exception-Typ hier
    # deterministisch: fake_serve löst `ready` erst nach 0.2s auf, also läuft
    # start() immer in den START_TIMEOUT_S-Zweig (RuntimeError).
    with pytest.raises(RuntimeError):
        backend.start()

    thread = backend._thread
    assert thread is not None and thread.is_alive()

    backend.stop()

    assert not thread.is_alive()
