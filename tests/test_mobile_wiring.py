# tests/test_mobile_wiring.py
"""Die Handy-Instanz muss an allen Stellen stehen, an denen die App Ressourcen freigibt
oder neu startet — sonst bleibt ein Port im LAN offen. Tk-Code läuft hier nicht
(entschiedene Scope-Grenze), deshalb prüft der Test die Verdrahtung am Quelltext."""
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


def test_the_app_takes_a_mobile_store_and_builds_the_service_in_init():
    init = _function("__init__")
    assert "mobile_store" in [a.arg for a in init.args.args + init.args.kwonlyargs]
    assigned = [t for node in ast.walk(init) if isinstance(node, ast.Assign)
                for t in node.targets if isinstance(t, ast.Attribute) and t.attr == "_mobile"]
    assert assigned, "App.__init__ muss self._mobile anlegen"


def test_the_setting_is_applied_at_start_and_after_every_settings_save():
    assert _self_method_calls(_function("__init__"), "_apply_mobile_setting")
    assert _self_method_calls(_function("_open_settings"), "_apply_mobile_setting")


def test_apply_mobile_setting_delegates_to_the_service():
    assert _self_calls(_function("_apply_mobile_setting"), "_mobile", "apply")


def test_every_exit_path_shuts_the_phone_server_down():
    for name in ("_quit_with_sync_push", "remove_application", "restart_for_scaling"):
        assert _self_calls(_function(name), "_mobile", "shutdown"), (
            f"{name} muss self._mobile.shutdown() rufen")


def test_the_quit_stops_the_phone_server_before_the_final_push():
    quit_ = _function("_quit_with_sync_push")
    shutdown = _self_calls(quit_, "_mobile", "shutdown")[0]
    push = _self_calls(quit_, "_sync", "push_on_quit")[0]
    assert shutdown.lineno < push.lineno


def test_the_restart_frees_the_port_before_spawning_and_recovers_on_failure():
    restart = _function("restart_for_scaling")
    shutdown = _self_calls(restart, "_mobile", "shutdown")[0]
    spawn = [n for n in ast.walk(restart)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "Popen"][0]
    assert shutdown.lineno < spawn.lineno
    assert _self_calls(restart, "_mobile", "reopen")
    assert _self_calls(restart, "_mobile", "apply")


def test_removal_stops_the_phone_server_before_any_background_job_is_queued():
    removal = _function("remove_application")
    shutdown = _self_calls(removal, "_mobile", "shutdown")[0]
    queued = _self_calls(removal, "_bg", "run")[0]
    assert shutdown.lineno < queued.lineno


def test_the_settings_dialog_gets_the_service():
    source = ast.get_source_segment(UI.read_text(encoding="utf-8"), _function("_open_settings"))
    assert "mobile_service=self._mobile" in source


def test_main_builds_the_store_in_the_data_folder_and_passes_it_on():
    source = MAIN.read_text(encoding="utf-8")
    assert 'MobileStore(os.path.join(base, "mobile_devices.json"))' in source
    assert "mobile_store=mobile_store" in source
