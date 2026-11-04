# tests/test_relay_wiring.py
"""Der Relay-Dienst (#358) muss an denselben Stellen stehen wie die Handy-Instanz.
Tk-Code läuft hier nicht (Scope-Grenze), deshalb prüft der Test den Quelltext."""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "src"
UI = ROOT / "ui.py"
MAIN = ROOT / "main.py"
TREE = ast.parse(UI.read_text(encoding="utf-8"))


def _function(name):
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} fehlt in src/ui.py")


def _self_calls(func, owner, method):
    found = []
    for node in ast.walk(func):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        t = node.func
        if (t.attr == method and isinstance(t.value, ast.Attribute)
                and t.value.attr == owner and isinstance(t.value.value, ast.Name)
                and t.value.value.id == "self"):
            found.append(node)
    return found


def test_relay_shutdown_in_all_three_exit_paths():
    for name in ("_quit_with_sync_push", "remove_application", "restart_for_scaling"):
        assert _self_calls(_function(name), "_relay", "shutdown"), name
    quit_ = _function("_quit_with_sync_push")
    assert (_self_calls(quit_, "_relay", "shutdown")[0].lineno
            < _self_calls(quit_, "_sync", "push_on_quit")[0].lineno)
    removal = _function("remove_application")
    assert (_self_calls(removal, "_relay", "shutdown")[0].lineno
            < _self_calls(removal, "_bg", "run")[0].lineno)
    restart = _function("restart_for_scaling")
    spawn = [n for n in ast.walk(restart) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "Popen"][0]
    assert _self_calls(restart, "_relay", "shutdown")[0].lineno < spawn.lineno


def test_relay_reopen_after_failed_restart():
    restart = _function("restart_for_scaling")
    assert _self_calls(restart, "_relay", "reopen")
    assert _self_calls(restart, "_relay", "apply")


def test_relay_apply_follows_mobile_apply():
    assert _self_calls(_function("_apply_mobile_setting"), "_relay", "apply")


def test_every_relay_call_is_guarded_against_none():
    """Jeder Aufruf von self._relay.<x>() steht in einem `if self._relay is not None`
    (Ausnahme: der Aufbau selbst in __init__, wo er gerade gebaut wurde)."""
    init = _function("__init__")
    inside_init = {id(n) for n in ast.walk(init)}
    parents = {}
    for node in ast.walk(TREE):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    for node in ast.walk(TREE):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "_relay"
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "self"):
            if id(node) in inside_init:
                continue
            cur, guarded = node, False
            while id(cur) in parents:
                cur = parents[id(cur)]
                if isinstance(cur, ast.If) and "_relay" in ast.unparse(cur.test):
                    guarded = True
                    break
            assert guarded, f"ungeschützter Aufruf in Zeile {node.lineno}"


def test_relay_is_built_after_the_mobile_service_and_cleanup_is_wired():
    source = UI.read_text(encoding="utf-8")
    assert "mobile_box_store=None" in source and "mobile_box_cursor=None" in source
    assert "RelayService(" in source
    assert "self._mobile.context" in source
    assert "self._mobile.set_box_cleanup(self._relay.forget_devices)" in source
    assert source.index("self._mobile = MobileService(") < source.index("RelayService(")


def test_main_builds_box_store_and_cursor_in_base_dir():
    source = MAIN.read_text(encoding="utf-8")
    assert 'MobileBoxStore(os.path.join(base, "mobile_box.json"))' in source
    assert 'MobileBoxCursor(os.path.join(base, "mobile_box_cursor.json"))' in source
    assert "mobile_box_store=mobile_box_store" in source
    assert "mobile_box_cursor=mobile_box_cursor" in source


def test_relay_none_without_stores():
    source = UI.read_text(encoding="utf-8")
    assert "self._relay = None" in source
    assert "self._mobile is not None and mobile_box_store is not None" in source
    assert "and mobile_box_cursor is not None):" in source


def test_the_settings_dialog_gets_the_relay_service():
    for node in ast.walk(TREE):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "open_settings_dialog"):
            kwargs = {k.arg: ast.unparse(k.value) for k in node.keywords}
            assert kwargs.get("relay_service") == "self._relay"
            return
    raise AssertionError("open_settings_dialog wird in src/ui.py nicht aufgerufen")


def test_the_relay_pair_dialog_closes_through_the_worker():
    """`close_pairing` blockiert (Datei, Netz): im Koppel-Dialog nur als Argument von
    `runner.run(...)`, nie als direkter Aufruf im UI-Thread."""
    path = ROOT / "dialogs" / "mobile_pair_dialog.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {id(c): n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    uses = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "close_pairing"]
    assert uses, "der Dialog räumt die Relay-Seite nicht ab"
    for use in uses:
        call = parents[id(use)]
        assert isinstance(call, ast.Call) and use in call.args, "close_pairing direkt aufgerufen"
        assert ast.unparse(call.func) == "self._runner.run"
