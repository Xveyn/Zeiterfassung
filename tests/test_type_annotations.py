"""Schutztest für die Typannotationen der Tk-freien Module (#72).

Warum ein Test und keine Linter-Regel: `reportMissingParameterType` ließe sich
in `pyproject.toml` nur **global** oder per `executionEnvironments` scharf
schalten — und die sind **verzeichnisgebunden** (`root = "<dir>"`). Die
Tk-freien Module liegen aber flach in `src/` direkt neben `ui.py`/`theme/`,
deren 6 % Annotationsquote eine bewusste Entscheidung ist (Tkinter-Widgets
werden mit `None` initialisiert und später gesetzt, s. `pyproject.toml`).
Global scharf zu schalten färbte die UI-Schicht rot.

Der Test hält stattdessen eine explizite Whitelist: was einmal annotiert ist,
bleibt es. Die Liste wächst pro PR mit — Muster wie
`test_sync_reexports_settings_whitelist`.

**Ein Modul hier einzutragen ist eine Zusage**, keine Formalie: Rückgabetyp und
alle Parameter, und zwar die *richtigen* — eine falsche Annotation ist
schlimmer als keine, weil sich der nächste Leser darauf verlässt.
"""

import ast
import pathlib

import pytest

# Vollständig annotierte Tk-freie Module. Nur ergänzen, wenn `pytest` danach
# grün ist — und nur für Module ohne Tk-Import.
ANNOTATED_MODULES = [
    "src/time_utils.py",
    "src/webhook.py",
    "src/smtp.py",
    "src/share.py",
    "src/workweek.py",
    "src/reminders.py",
    "src/pause_requirement.py",
    "src/weekly_limit.py",
    "src/send_reminder.py",
    "src/report.py",
    "src/mime_message.py",
    # Infra-/Plattform-Schicht
    "src/paths.py",
    "src/version.py",
    "src/device_id.py",
    "src/devices.py",
    "src/secure_file.py",
    "src/keyring_store.py",
    "src/updater.py",
    "src/changelog.py",
    "src/desktop_entry.py",
    "src/oauth_utils.py",
    "src/sync_journal.py",
    "src/autostart.py",
    "src/single_instance.py",
    # Bereits vor #72 vollstaendig annotiert — hier gelistet, damit sie
    # nicht unbemerkt zurueckfallen koennen.
    "src/storage.py",
    "src/settings.py",
    "src/reservations.py",
    "src/vacations.py",
    "src/vacations_sync.py",
    "src/conflicts_store.py",
    "src/sync.py",
    "src/sync_history.py",
    "src/json_store.py",
    "src/webhook_store.py",
    "src/holidays_de.py",
    "src/platform_open.py",
]

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _missing_annotations(path: pathlib.Path):
    """(qualifizierter Name, was fehlt) für jede unvollständige Funktion."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    stack: list[tuple[ast.AST, str]] = [(tree, "")]
    while stack:
        node, prefix = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                args = child.args
                params = (args.posonlyargs + args.args + args.kwonlyargs
                          + [a for a in (args.vararg, args.kwarg) if a is not None])
                for a in params:
                    if a.arg in ("self", "cls"):
                        continue
                    if a.annotation is None:
                        out.append((name, f"Parameter '{a.arg}'"))
                if child.returns is None:
                    out.append((name, "Rückgabetyp"))
                stack.append((child, f"{name}."))
            elif isinstance(child, ast.ClassDef):
                stack.append((child, f"{child.name}."))
    return out


@pytest.mark.parametrize("module", ANNOTATED_MODULES)
def test_module_is_fully_annotated(module):
    path = REPO_ROOT / module
    assert path.exists(), f"{module} steht in der Whitelist, existiert aber nicht"
    missing = _missing_annotations(path)
    assert not missing, (
        f"{module} steht in ANNOTATED_MODULES, es fehlen aber Annotationen:\n"
        + "\n".join(f"  {name}: {what}" for name, what in sorted(missing))
    )


@pytest.mark.parametrize("module", ANNOTATED_MODULES)
def test_annotated_modules_stay_tk_free(module):
    """Die Whitelist ist für die Tk-freie Schicht gedacht. Zöge ein Modul
    später Tk herein, gehörte es nicht mehr hierher — und der Test soll das
    sagen, statt stumm weiterzulaufen."""
    source = (REPO_ROOT / module).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    assert "tkinter" not in imported, f"{module} importiert tkinter"


def test_whitelist_has_no_duplicates():
    assert len(ANNOTATED_MODULES) == len(set(ANNOTATED_MODULES))
