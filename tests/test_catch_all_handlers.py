"""Schutztest für die Catch-all-Konvention (Xveyn/Zeiterfassung#73).

`src/` hält rund 90 Handler auf `except Exception` / `except BaseException`.
Die Dichte ist unkritisch und begründet — Bootstrap, Threading-Ränder und
Best-Effort-Plattformaufrufe sind genau die Stellen, an denen ein Catch-all
hingehört. Was auffallen muss, ist nicht die Zahl, sondern ein Handler, der
**schweigt, ohne zu sagen warum**: `--noconsole` unterdrückt stderr, ein
stummes `pass` ist damit endgültig.

Warum ein Test und keine Linter-Regel: `ruff`s `BLE001` (blind-except) meckert
jeden Catch-all an, also auch die ~90 korrekten — reines Rauschen mit
anschließender `noqa`-Flut. Diese Regel prüft stattdessen das, worauf es
ankommt. Muster wie `test_type_annotations.py`.

Die Regel (s. CLAUDE.md, „UI-Fehler sichtbar machen"): ein Catch-all **loggt,
meldet oder trägt eine Begründung**. Der Kommentar muss im Handler selbst
stehen — eine Begründung zwölf Zeilen weiter oben im Docstring sieht der
Leser an der Fundstelle nicht.
"""

import ast
import io
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

_LOGS = re.compile(
    r"\b(logging|logger|_?log)\s*\.\s*\w+\(|exc_info|traceback\.|\.exception\(")
_REPORTS = re.compile(r"showerror|showwarning|showinfo|messagebox")


def _catch_all_handlers():
    """(Pfad, Zeile, Handler-Quelltext) je Catch-all unter src/."""
    for path in sorted(SRC.rglob("*.py")):
        source = io.open(path, encoding="utf-8").read()
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            caught = ast.unparse(node.type) if node.type is not None else "bare"
            if caught not in ("Exception", "BaseException", "bare"):
                continue
            span = "\n".join(lines[node.lineno - 1: node.body[-1].end_lineno])
            yield path, node.lineno, span, node


def test_every_catch_all_logs_reports_or_explains_itself():
    offenders = []
    for path, lineno, span, node in _catch_all_handlers():
        body = "\n".join(span.splitlines()[1:])
        if _LOGS.search(body) or _REPORTS.search(body):
            continue
        if any(isinstance(n, ast.Raise) for n in ast.walk(node)):
            continue
        if "#" in span:          # Begründung als Kommentar im Handler
            continue
        offenders.append(f"{path.relative_to(SRC.parent)}:{lineno}")

    assert not offenders, (
        "Catch-all ohne Log, Meldung oder Begründung "
        f"({len(offenders)}):\n  " + "\n  ".join(offenders))


def test_bare_except_is_not_used():
    """`except:` faengt auch KeyboardInterrupt/SystemExit — dafuer gibt es
    `except BaseException` mit anschliessendem `raise` (Aufraeumpfade)."""
    bare = [f"{p.relative_to(SRC.parent.parent)}:{ln}"
            for p, ln, _, node in _catch_all_handlers() if node.type is None]
    assert bare == [], f"nacktes `except:` gefunden: {bare}"


def test_base_exception_handlers_hand_the_error_on():
    """`except BaseException` faengt auch KeyboardInterrupt/SystemExit. Das ist
    nur zulaessig, wenn der Handler den Fehler nicht behaelt: entweder wirft er
    ihn erneut (Aufraeumpfade rund um `os.replace`) oder er reicht ihn weiter.

    Weitergabe erkennt der Test daran, dass der gebundene Name im Body vorkommt
    — `keyring_store` faengt im Sekundaer-Thread bewusst ALLES (ein Thread hat
    keinen eigenen Excepthook), legt die Exception ab, und der Aufrufer-Thread
    wirft sie erneut. Ein Handler, der den Namen gar nicht anfasst, laesst den
    Fehler dagegen wirklich fallen.
    """
    offenders = []
    for path, lineno, _span, node in _catch_all_handlers():
        if node.type is None or ast.unparse(node.type) != "BaseException":
            continue
        if any(isinstance(n, ast.Raise) for n in ast.walk(node)):
            continue
        if node.name and any(isinstance(n, ast.Name) and n.id == node.name
                             for n in ast.walk(node)):
            continue
        offenders.append(f"{path.relative_to(SRC.parent)}:{lineno}")
    assert not offenders, (
        "`except BaseException` ohne `raise` und ohne Weitergabe "
        f"({len(offenders)}):\n  " + "\n  ".join(offenders))
