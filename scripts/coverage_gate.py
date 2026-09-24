"""Coverage-Untergrenze fuer die Tk-freien Module.

Die Gesamt-Coverage taugt hier nicht als Gate: Tk-gebundener Code wird
bewusst nicht automatisiert getestet (s. CLAUDE.md, „Getestet wird Logik,
nicht UI"), und sein Anteil drueckt die Gesamtzahl auf rund 60 %. Ein
`fail_under` darauf faerbte den Build dauerhaft rot oder muesste so niedrig
liegen, dass er nichts mehr misst. Deshalb gibt es weiterhin **kein**
`fail_under` in `pyproject.toml` (Audit N24).

Gemessen wird stattdessen genau der Teil, fuer den die Scope-Grenze die
Tests verspricht: alle Module unter `src/`, die `tkinter` nicht importieren.
Die Einteilung laeuft ueber den AST, nicht ueber eine Liste — ein neues
Tk-freies Modul faellt damit ohne Zutun unter das Gate.

    pytest --cov=src --cov-report=json
    python scripts/coverage_gate.py [coverage.json]

Laeuft im `coverage`-Job von `test.yml`. Reine stdlib.
"""

import ast
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Untergrenze in Prozent (Anweisungen + Zweige, wie `coverage report`).
# Gesetzt nach der **CI-Messung** (ubuntu/3.12), nicht nach einer lokalen:
# plattformabhaengige Zweige (`dpi.py`, Autostart, Pfade) laufen je
# Betriebssystem anders, lokal unter Windows liegt die Zahl etwas anders.
# Eine Ratsche: steigt die Messung deutlich, wird der Wert nachgezogen —
# das Skript meldet das —, gesenkt wird er nur mit Begruendung im PR.
FLOOR = 91.0  # CI-Messung bei Einfuehrung: 92,0 %

# Ab diesem Abstand zur Messung schlaegt das Skript vor, FLOOR anzuheben.
RATCHET_HINT = 2.0

# Tk-frei, aber trotzdem nicht Teil des Gates. Die Tray-Backends haengen an
# pystray, PyObjC bzw. D-Bus und lassen sich nur auf ihrer eigenen Plattform
# mit echter Sitzung ausfuehren; ihre testbare Logik liegt bereits getrennt in
# `tray/model.py` und `MenuState`. Mitgezaehlt wuerde ihre Zahl davon
# abhaengen, auf welchem Runner gemessen wird.
EXEMPT = {
    "src/tray/windows.py": "pystray-Backend, braucht eine Windows-Sitzung",
    "src/tray/mac.py": "NSStatusItem-Backend, braucht macOS + PyObjC",
    "src/tray/linux.py": "StatusNotifierItem-Backend, braucht eine D-Bus-Sitzung",
}


def imports_tkinter(source):
    """True, wenn der Quelltext `tkinter` importiert — egal wo im Modul."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        else:
            continue
        if any(name.split(".")[0] == "tkinter" for name in names):
            return True
    return False


def _normalize(path):
    # coverage.json schreibt die Pfade mit dem Trenner des Messrechners.
    return path.replace("\\", "/")


def measure(report, read_source):
    """Coverage der Tk-freien, nicht ausgenommenen Module.

    `report` ist das geparste coverage.json, `read_source(path)` liefert den
    Quelltext zu einem Pfad daraus. Ergebnis: dict mit `covered`, `total`,
    `percent` und `modules` (Liste aus `(pfad, prozent, einheiten)`)."""
    covered = total = 0
    modules = []
    for path, data in report["files"].items():
        name = _normalize(path)
        if name in EXEMPT or imports_tkinter(read_source(path)):
            continue
        summary = data["summary"]
        units = summary["num_statements"] + summary.get("num_branches", 0)
        hits = summary["covered_lines"] + summary.get("covered_branches", 0)
        covered += hits
        total += units
        modules.append((name, 100.0 * hits / units if units else 100.0, units))
    percent = 100.0 * covered / total if total else 100.0
    return {"covered": covered, "total": total, "percent": percent,
            "modules": modules}


def stale_exemptions(report):
    """Ausnahmen, deren Datei nicht mehr im Bericht steht. Eine verwaiste
    Ausnahme ist ein Fehler: sie haette sonst beim naechsten Modul gleichen
    Namens still gegriffen."""
    present = {_normalize(path) for path in report["files"]}
    return sorted(set(EXEMPT) - present)


def _read_source(path):
    full = path if os.path.isabs(path) else os.path.join(_ROOT, path)
    with open(full, encoding="utf-8") as fh:
        return fh.read()


def main(argv):
    report_path = argv[1] if len(argv) > 1 else "coverage.json"
    try:
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
    except OSError as exc:
        print(f"::error::{report_path} nicht lesbar ({exc}) - vorher "
              f"`pytest --cov=src --cov-report=json` laufen lassen.")
        return 2

    stale = stale_exemptions(report)
    if stale:
        print(f"::error::Ausnahmen ohne Datei im Bericht: {', '.join(stale)} "
              f"— EXEMPT in scripts/coverage_gate.py nachziehen.")
        return 1

    result = measure(report, _read_source)
    percent = result["percent"]
    print(f"Tk-freie Module: {percent:.1f} % "
          f"({result['covered']}/{result['total']} Anweisungen + Zweige, "
          f"{len(result['modules'])} Module, Untergrenze {FLOOR:.1f} %)")
    print("Schwaechste Module:")
    for name, pct, units in sorted(result["modules"], key=lambda m: m[1])[:10]:
        print(f"  {pct:5.1f} %  {units:5d}  {name}")

    if percent < FLOOR:
        print(f"::error::Coverage der Tk-freien Module {percent:.1f} % liegt "
              f"unter der Untergrenze {FLOOR:.1f} % (scripts/coverage_gate.py). "
              f"Neue Logik gehoert getestet - s. CLAUDE.md, 'Tests / CI'.")
        return 1
    if percent - FLOOR >= RATCHET_HINT:
        print(f"::notice::Coverage {percent:.1f} % liegt deutlich ueber der "
              f"Untergrenze {FLOOR:.1f} % - FLOOR in scripts/coverage_gate.py "
              f"nachziehen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
