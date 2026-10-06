# tests/test_api_wiring.py
"""Die API muss an allen Stellen stehen, an denen die App Ressourcen freigibt
oder neu startet. Tk-Code läuft hier nicht (entschiedene Scope-Grenze), deshalb
prüft der Test die Verdrahtung am Quelltext."""
import ast
import pathlib

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "ui.py"
TREE = ast.parse(UI.read_text(encoding="utf-8"))


def _function(name):
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} fehlt in src/ui.py")


def _self_calls(func, owner, method):
    """Aufrufe `self.<owner>.<method>(...)` innerhalb von `func`."""
    found = []
    for node in ast.walk(func):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        target = node.func
        if (target.attr == method and isinstance(target.value, ast.Attribute)
                and target.value.attr == owner
                and isinstance(target.value.value, ast.Name)
                and target.value.value.id == "self"):
            found.append(node)
    return found


def _self_method_calls(func, method):
    return [n for n in ast.walk(func)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == method and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "self"]


def test_the_api_service_is_built_in_init():
    init = _function("__init__")
    assigned = [t for node in ast.walk(init) if isinstance(node, ast.Assign)
                for t in node.targets if isinstance(t, ast.Attribute) and t.attr == "_api"]
    assert assigned, "App.__init__ muss self._api anlegen"


def test_the_setting_is_applied_at_start_and_after_every_settings_save():
    assert _self_method_calls(_function("__init__"), "_apply_api_setting")
    assert _self_method_calls(_function("_open_settings"), "_apply_api_setting")


def test_apply_api_setting_delegates_to_the_service():
    assert _self_calls(_function("_apply_api_setting"), "_api", "apply")


def test_every_exit_path_shuts_the_api_down():
    for name in ("_quit_with_sync_push", "remove_application", "restart_for_scaling"):
        assert _self_calls(_function(name), "_api", "shutdown"), (
            f"{name} muss self._api.shutdown() rufen")


def test_the_restart_frees_the_port_before_spawning_and_recovers_on_failure():
    restart = _function("restart_for_scaling")
    shutdown = _self_calls(restart, "_api", "shutdown")[0]
    spawn = [n for n in ast.walk(restart)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "Popen"][0]
    # Port VOR dem Spawn freigeben, sonst findet die neue Instanz ihn belegt.
    assert shutdown.lineno < spawn.lineno
    # Scheitert Popen, läuft die App weiter — die API muss zurückkommen.
    assert _self_calls(restart, "_api", "reopen")
    assert _self_calls(restart, "_api", "apply")


def test_removal_stops_the_api_before_any_background_job_is_queued():
    removal = _function("remove_application")
    shutdown = _self_calls(removal, "_api", "shutdown")[0]
    queued = _self_calls(removal, "_bg", "run")[0]
    assert shutdown.lineno < queued.lineno
