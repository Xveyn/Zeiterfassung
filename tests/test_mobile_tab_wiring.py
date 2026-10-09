# tests/test_mobile_tab_wiring.py
"""Der Reiter „Mobil" muss im Einstellungsdialog stehen, wenn der Dienst übergeben wird.
Tk-Code läuft hier nicht (entschiedene Scope-Grenze), deshalb prüft der Test die
Verdrahtung am Quelltext."""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
DIALOG = SRC / "dialogs" / "settings_dialog" / "dialog.py"
TAB = SRC / "dialogs" / "settings_dialog" / "tab_mobile.py"
TREE = ast.parse(DIALOG.read_text(encoding="utf-8"))


def _open_settings_dialog():
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == "open_settings_dialog":
            return node
    raise AssertionError("open_settings_dialog fehlt")


def test_the_dialog_takes_an_optional_mobile_service():
    args = _open_settings_dialog().args
    names = [a.arg for a in args.args + args.kwonlyargs]
    assert "mobile_service" in names


def test_the_mobile_tab_sits_between_api_and_app_and_only_exists_with_a_service():
    source = DIALOG.read_text(encoding="utf-8")
    assert "from src.dialogs.settings_dialog.tab_mobile import MobileTab" in source
    api, mobile, app = (source.index('tabs["api"] = api'),
                        source.index('tabs["mobile"] = mobile'),
                        source.index('tabs["app"] = app'))
    assert api < mobile < app
    assert "if mobile_service is not None" in source


def test_the_tab_title_and_interface():
    tab = ast.parse(TAB.read_text(encoding="utf-8"))
    cls = next(n for n in tab.body if isinstance(n, ast.ClassDef) and n.name == "MobileTab")
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    assert {"values", "load", "validate", "save"} <= methods
    assert 'self.title = "Mobil"' in TAB.read_text(encoding="utf-8")


def test_the_first_enable_asks_before_anything_is_switched_on():
    source = TAB.read_text(encoding="utf-8")
    assert "FIRST_ENABLE_NOTICE" in source and "mobile_notice_accepted" in source
    # Die Zustimmung wird erst nach der Antwort gespeichert, nicht beim Anzeigen.
    assert source.index("themed_askyesno") < source.index('"mobile_notice_accepted", True')


def test_the_tab_never_calls_the_service_writes_in_the_ui_thread():
    """`revoke`/`revoke_all` schreiben eine Datei: sie dürfen nur als Referenz oder in
    einem Lambda an `runner.run` hängen, nie direkt im UI-Thread gerufen werden."""
    tree = ast.parse(TAB.read_text(encoding="utf-8"))
    inside_lambda = {id(n) for lam in ast.walk(tree) if isinstance(lam, ast.Lambda)
                     for n in ast.walk(lam)}
    direct = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr in ("revoke", "revoke_all") and id(n) not in inside_lambda]
    assert direct == [], "revoke/revoke_all gehören in den Worker (runner.run)"
    assert "self._service.revoke" in TAB.read_text(encoding="utf-8")


def _tab_method(name):
    tree = ast.parse(TAB.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MobileTab")
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _self_calls(func, method):
    return [n for n in ast.walk(func) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == method
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"]


def test_every_poll_refreshes_the_buttons():
    # Sonst bleibt „Gerät koppeln …" nach dem Einschalten grau, bis sich die Geräteliste
    # ändert — und umgekehrt sieht es nach dem Stoppen noch bedienbar aus.
    assert _self_calls(_tab_method("_poll"), "_sync_buttons")


def test_a_failed_revoke_is_shown_and_releases_the_tab():
    source = TAB.read_text(encoding="utf-8")
    assert "revoke_outcome" in source and "themed_showerror" in source
    revoked = _tab_method("_revoked")
    assert _self_calls(revoked, "_sync_buttons")
    busy = [n for n in ast.walk(revoked) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Attribute) and t.attr == "_busy" for t in n.targets)]
    assert busy, "_revoked muss _busy zurücksetzen"


def test_the_pair_dialog_imports_on_its_own():
    # Dialog → Paket settings_dialog (wegen tab_rules) → tab_mobile → Dialog wäre ein
    # Zyklus. In der App half nur die Importreihenfolge; ein Test, der den Dialog zuerst
    # importiert, scheiterte. Frischer Prozess, damit kein früherer Import mitspielt.
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "-c", "import src.dialogs.mobile_pair_dialog"],
        cwd=SRC.parent, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
