"""Schutztest für die Paarungs-Regel `create_dialog` ↔ `center_dialog_on_parent`.

Seit Xveyn#34 erzeugt `theme.create_dialog` den Dialog **verborgen**
(`withdraw`) und `center_dialog_on_parent` macht ihn wieder sichtbar. Das
löst das helle Aufblitzen der Titelleiste, hängt aber an einer Bedingung:
**wer `create_dialog` ruft, muss `center_dialog_on_parent` rufen.** Sonst
baut sich der Dialog vollständig auf, nimmt womöglich den Fokus — und ist
nie zu sehen.

Das ist die unangenehmste Sorte Fehler: kein Traceback, keine Log-Zeile,
`--noconsole` verschluckt ohnehin stderr. Der Nutzer klickt, und nichts
passiert. Deshalb hier eine Assertion statt eines Kommentars.

Die Paarung war schon vor der Änderung Konvention (jeder Dialog zentriert
sich am Ende seines Aufbaus) — neu ist nur, dass ihr Bruch jetzt sichtbare
Folgen hat. Muster wie `test_type_annotations.py` und
`test_catch_all_handlers.py`: dokumentierte Konvention als Test, reine
stdlib, läuft in der bestehenden Matrix mit.

Geprüft wird **pro Funktion**, nicht pro Datei: eine Datei mit zwei Dialogen
könnte sonst einen davon vergessen und bliebe grün.
"""

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

# `chrome.py` definiert create_dialog selbst und `messagebox.py`… ruft beide,
# ist also kein Sonderfall. Ausgenommen ist nur die Definitionsdatei.
_DEFINING_FILES = {"chrome.py", "geometry.py"}


def _called_names(node):
    """Alle aufgerufenen Namen im Teilbaum — inklusive verschachtelter
    Funktionen, weil ein Dialog seinen Zentrier-Aufruf auch in einem
    Callback machen darf."""
    names = set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _functions_creating_dialogs():
    """[(datei, funktion, aufgerufene_namen)] für jede Funktion, die
    `create_dialog` ruft."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name in _DEFINING_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = _called_names(node)
            if "create_dialog" in names:
                found.append((path.relative_to(SRC.parent), node.name, names))
    return found


def test_every_create_dialog_is_paired_with_a_center_call():
    offenders = [
        f"{path}::{func}"
        for path, func, names in _functions_creating_dialogs()
        if "center_dialog_on_parent" not in names
    ]
    assert not offenders, (
        "create_dialog erzeugt den Dialog verborgen; sichtbar macht ihn erst "
        "center_dialog_on_parent (s. theme/chrome.py). Ohne den Aufruf bleibt "
        "der Dialog unsichtbar — ohne Fehlermeldung.\n"
        "Betroffen: " + ", ".join(offenders))


def test_the_check_actually_finds_the_dialogs():
    """Ein Parser, der nichts findet, prüft nichts — und wäre grün."""
    found = _functions_creating_dialogs()
    assert len(found) >= 15, (
        f"Nur {len(found)} create_dialog-Aufrufer gefunden; im Repo sind es "
        "deutlich mehr. Vermutlich hat sich der Aufrufname geändert und der "
        "Test läuft ins Leere.")
