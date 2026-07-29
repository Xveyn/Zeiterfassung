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
