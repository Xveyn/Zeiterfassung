"""Der Dialog „Datenschutzhinweise“ (Einstellungen → App) ist Tk-Code und wird nicht automatisiert aufgebaut
(Scope-Grenze, Wurzel-`CLAUDE.md`). Dieser Test hält am Quelltext fest, woran das Verhalten hängt: der Button
im eigenen Abschnitt, der lazy Import, das Laden über den Ressourcenpfad samt Ersatztext und dass Links nur
über `is_web_url` geöffnet werden."""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
TAB_APP = SRC / "dialogs" / "settings_dialog" / "tab_app.py"
DIALOG = SRC / "dialogs" / "privacy_dialog.py"


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _calls(tree, dotted):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node.func) == dotted:
            found.append(node)
    return found


def test_tab_app_has_the_privacy_button_in_its_own_section():
    source = TAB_APP.read_text(encoding="utf-8")
    assert 'form.section("Datenschutz")' in source
    assert '"Datenschutzhinweise"' in source
    tree = _tree(TAB_APP)
    top_level_imports = [
        node for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module and "privacy_dialog" in node.module]
    assert top_level_imports == [], "privacy_dialog darf nicht auf Modulebene importiert werden (Importzyklus)"
    lazy = [
        node for func in ast.walk(tree) if isinstance(func, ast.FunctionDef)
        for node in ast.walk(func)
        if isinstance(node, ast.ImportFrom) and node.module == "src.dialogs.privacy_dialog"]
    assert lazy, "der Dialog wird lazy in einer Methode importiert"


def test_the_privacy_section_comes_after_the_data_section():
    source = TAB_APP.read_text(encoding="utf-8")
    assert source.index('form.section("Daten")') < source.index('form.section("Datenschutz")')


def test_the_dialog_loads_through_the_resource_path_and_falls_back():
    source = DIALOG.read_text(encoding="utf-8")
    for needed in ("get_resource_path", "load_privacy_doc", "fallback_blocks", "parse_privacy_markdown"):
        assert needed in source, needed


def test_links_open_only_through_is_web_url():
    tree = _tree(DIALOG)
    opens = _calls(tree, "webbrowser.open")
    assert opens, "der Dialog öffnet keine Links mehr"
    for func in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        inside = [c for c in ast.walk(func) if isinstance(c, ast.Call) and ast.unparse(c.func) == "webbrowser.open"]
        if inside:
            assert "is_web_url" in ast.unparse(func), f"{func.name} öffnet einen Link ohne is_web_url"


def test_the_dialog_is_read_only_and_uses_the_theme_widgets():
    source = DIALOG.read_text(encoding="utf-8")
    assert "dark_text(" in source
    assert 'state="disabled"' in source or "state=tk.DISABLED" in source
    assert "Vertical.TScrollbar" in source
    assert "px(" in source


def test_visible_lines_shrinks_the_text_to_the_screen_but_keeps_a_minimum():
    from src.dialogs.privacy_dialog import visible_lines
    assert visible_lines(2000, 20) == 26            # genug Platz: die bevorzugte Höhe
    assert visible_lines(400, 20) == 20             # knapp: so viele Zeilen, wie hineinpassen
    assert visible_lines(50, 20) == 8               # sehr knapp: nie unter dem Minimum
    assert visible_lines(400, 0) == 26              # unbekannte Zeilenhöhe: bevorzugte Höhe


def test_the_text_shows_no_focus_frame_and_stays_out_of_the_tab_order():
    """`dark_text` zeichnet einen Fokusrahmen in der Akzentfarbe (für Eingabefelder gedacht). Die Hinweise sind
    nur zum Lesen: kein Rahmen, kein Tab-Stopp; Mausrad, Auswahl und Kopieren bleiben."""
    tree = _tree(DIALOG)
    configured = {}
    for call in _calls(tree, "text.configure"):
        for keyword in call.keywords:
            if keyword.arg:
                configured[keyword.arg] = ast.unparse(keyword.value)
    assert configured.get("highlightthickness") == "0"
    assert configured.get("takefocus") == "0"


def test_code_spans_are_set_apart_by_colour_only_without_a_background_box():
    """Ein hinterlegter Kasten reicht bei einzelnen Wörtern über die Zeilenhöhe hinaus und wirkt wie ein
    heller Fleck im Fließtext; Code hebt sich allein durch die gedämpfte Schriftfarbe ab."""
    tree = _tree(DIALOG)
    code_tags = [call for call in _calls(tree, "text.tag_configure")
                 if call.args and ast.unparse(call.args[0]) == "'code'"]
    assert len(code_tags) == 1
    options = {keyword.arg for keyword in code_tags[0].keywords}
    assert "foreground" in options
    assert "background" not in options
