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


def _top_level_statement(func, call):
    """Die direkte Anweisung im Funktionskörper, die `call` enthält."""
    for stmt in func.body:
        if any(node is call for node in ast.walk(stmt)):
            return stmt
    raise AssertionError("Aufruf nicht im Funktionskörper")


def test_shutdown_is_unconditional_in_every_exit_path():
    # Ein `shutdown()` in einem if/try-Zweig würde bei fehlender Bedingung
    # übersprungen: z. B. im Restart-Pfad nur bei gesetztem _single_instance.
    for name in ("_quit_with_sync_push", "remove_application", "restart_for_scaling"):
        func = _function(name)
        call = _self_calls(func, "_api", "shutdown")[0]
        stmt = _top_level_statement(func, call)
        assert isinstance(stmt, ast.Expr) and stmt.value is call, (
            f"{name}: self._api.shutdown() muss eine eigene Anweisung auf oberster "
            "Ebene sein, nicht in einem Zweig")


def test_removal_shuts_the_api_down_only_after_it_was_admitted():
    # `claim == "sync"` lehnt das Entfernen ab („alles unangetastet"): wäre die
    # API vorher gestoppt, bliebe sie danach dauerhaft tot.
    func = _function("remove_application")
    shutdown = _top_level_statement(func, _self_calls(func, "_api", "shutdown")[0])
    claims = [stmt for stmt in func.body
              if isinstance(stmt, ast.Assign)
              and any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr == "claim" for n in ast.walk(stmt))]
    refusals = [stmt for stmt in func.body if isinstance(stmt, ast.If)
                and any(isinstance(n, ast.Constant) and n.value == "sync"
                        for n in ast.walk(stmt.test))]
    assert claims and refusals
    assert func.body.index(shutdown) > func.body.index(refusals[0]) > func.body.index(claims[0])


# --- Settings-Tab (PR 3) -------------------------------------------------------

DIALOG = (pathlib.Path(__file__).resolve().parent.parent / "src" / "dialogs"
          / "settings_dialog" / "dialog.py")
DIALOG_TREE = ast.parse(DIALOG.read_text(encoding="utf-8"))


def _dialog_function():
    for node in ast.walk(DIALOG_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == "open_settings_dialog":
            return node
    raise AssertionError("open_settings_dialog fehlt")


def test_the_app_hands_its_api_service_to_the_settings_dialog():
    call = [n for n in ast.walk(_function("_open_settings"))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "open_settings_dialog"][0]
    keywords = {kw.arg: kw.value for kw in call.keywords}
    assert "api_service" in keywords
    value = keywords["api_service"]
    assert (isinstance(value, ast.Attribute) and value.attr == "_api"
            and isinstance(value.value, ast.Name) and value.value.id == "self")


def test_the_dialog_accepts_api_service_as_an_optional_keyword():
    args = _dialog_function().args
    names = [a.arg for a in args.kwonlyargs] + [a.arg for a in args.args]
    assert "api_service" in names
    defaults = dict(zip([a.arg for a in args.kwonlyargs], args.kw_defaults, strict=True))
    assert isinstance(defaults["api_service"], ast.Constant) and defaults["api_service"].value is None


def test_the_api_tab_sits_between_google_and_app_and_only_with_a_service():
    func = _dialog_function()
    order = []          # (Zeile, Schlüssel) aller `tabs[...] = …` und des Literals
    for node in ast.walk(func):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Subscript)
                and isinstance(node.targets[0].value, ast.Name)
                and node.targets[0].value.id == "tabs"
                and isinstance(node.targets[0].slice, ast.Constant)):
            order.append((node.lineno, node.targets[0].slice.value))
    # Seit #221 steht „mobile“ (ebenfalls nur mit Dienst) zwischen „api“ und „app“.
    assert [key for _, key in sorted(order)] == ["api", "mobile", "app", "updates"]
    # Der Eintrag „api" steht unter einer Bedingung (kein Dienst, kein Tab).
    api_assign = [n for n in ast.walk(func) if isinstance(n, ast.If)
                  and any(isinstance(s, ast.Assign) and isinstance(s.targets[0], ast.Subscript)
                          and isinstance(s.targets[0].slice, ast.Constant)
                          and s.targets[0].slice.value == "api" for s in n.body)]
    assert api_assign


def _api_tab_calls(func):
    return [n for n in ast.walk(func)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "ApiTab"]


def test_the_api_tab_is_only_built_when_a_service_is_given():
    # Ohne den Guard fiele der Dialog ohne Dienst mit KeyError ("api" fehlt in
    # `frames`) — ui.py übergibt den Dienst zwar immer, aber der Dialog soll
    # auch ohne ihn funktionieren.
    func = _dialog_function()
    guarded = [stmt for stmt in ast.walk(func)
               if isinstance(stmt, ast.If) and ast.unparse(stmt.test) == "api_service is not None"
               and _api_tab_calls(stmt)]
    assert guarded, "ApiTab(...) muss unter `if api_service is not None:` gebaut werden"
    assert len(_api_tab_calls(func)) == 1


def test_the_api_tab_gets_its_arguments_in_the_expected_order():
    call = _api_tab_calls(_dialog_function())[0]
    assert [ast.unparse(a) for a in call.args] == [
        "frames['api']", "dialog", "settings", "api_service", "runner"]


# --- PR 4: Schreibzugriff in der App ---------------------------------------------------------------

def test_the_api_context_carries_the_locks_stores_and_the_refresh_callback():
    init = _function("__init__")
    contexts = [n for n in ast.walk(init)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "ApiContext"]
    assert len(contexts) == 1
    keywords = {kw.arg: ast.unparse(kw.value) for kw in contexts[0].keywords}
    assert keywords["data_lock"] == "self._data_lock"
    assert keywords["conflicts_store"] == "self.conflicts_store"
    assert keywords["vacation_store"] == "self.vacation_store"
    # Der Server-Thread berührt nie ein Widget: Neuzeichnen nur über den Marshal.
    assert keywords["on_change"] == "self._api_refresh.request"


def test_the_api_is_shut_down_before_the_final_sync_push():
    # Sonst könnte eine schreibende Route nach dem Push-Snapshot noch Daten
    # ändern, die dann nie mehr hochgeladen werden.
    func = _function("_quit_with_sync_push")
    shutdown = _top_level_statement(func, _self_calls(func, "_api", "shutdown")[0])
    push = _top_level_statement(func, _self_calls(func, "_sync", "push_on_quit")[0])
    assert func.body.index(shutdown) < func.body.index(push)



def test_api_refreshes_are_coalesced_and_marshalled_to_the_ui_thread():
    # 365 PUTs eines Backfill-Skripts dürfen nicht 365 volle Grid-Refreshs queuen
    # (je rund 0,3–0,9 s); der Server-Thread berührt nie ein Widget.
    init = _function("__init__")
    built = [ast.unparse(n.value) for n in ast.walk(init)
             if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Attribute) and t.attr == "_api_refresh" for t in n.targets)]
    assert built == ["RefreshCoalescer(self._marshal_to_ui, self._refresh)"]
