"""Tests für scripts/coverage_gate.py.

Das Gate misst nur die Tk-freien Module (s. CLAUDE.md, „Tests / CI"). Getestet
werden die Einteilung, die Rechnung und die Ausnahmeliste — letztere gegen das
echte `src/`, damit eine Ausnahme nicht still ins Leere zeigt. Das Skript liegt
in `scripts/` und ist kein Package, wird also über seinen Pfad geladen —
Muster wie tests/test_release_notes.py.
"""

import importlib.util
import json
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "coverage_gate.py"
_spec = importlib.util.spec_from_file_location("_coverage_gate", _SCRIPT)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def _file(statements, covered, branches=0, covered_branches=0):
    return {"summary": {"num_statements": statements, "covered_lines": covered,
                        "num_branches": branches,
                        "covered_branches": covered_branches}}


# --- imports_tkinter -------------------------------------------------------

def test_import_tkinter_is_tk_bound():
    assert gate.imports_tkinter("import tkinter as tk\n")


def test_from_tkinter_submodule_is_tk_bound():
    assert gate.imports_tkinter("from tkinter import ttk\n")


def test_lazy_import_inside_function_is_tk_bound():
    assert gate.imports_tkinter("def f():\n    import tkinter\n")


def test_pure_module_is_not_tk_bound():
    assert not gate.imports_tkinter("import json\nfrom src import storage\n")


def test_similar_name_is_not_tkinter():
    assert not gate.imports_tkinter("import tkinterx\n")


# --- measure ---------------------------------------------------------------

def test_measure_counts_statements_and_branches():
    report = {"files": {"src/a.py": _file(10, 8, branches=4, covered_branches=2)}}
    result = gate.measure(report, lambda _p: "")
    assert (result["covered"], result["total"]) == (10, 14)
    assert round(result["percent"], 2) == round(100 * 10 / 14, 2)


def test_measure_skips_tk_bound_modules():
    report = {"files": {"src/pure.py": _file(10, 10),
                        "src/ui.py": _file(100, 0)}}
    sources = {"src/pure.py": "", "src/ui.py": "import tkinter\n"}
    result = gate.measure(report, sources.__getitem__)
    assert result["percent"] == 100.0
    assert [m[0] for m in result["modules"]] == ["src/pure.py"]


def test_measure_skips_exempt_modules_with_windows_paths():
    # coverage.json auf Windows schreibt Backslashes.
    report = {"files": {"src\\tray\\windows.py": _file(100, 0),
                        "src\\pure.py": _file(10, 5)}}
    result = gate.measure(report, lambda _p: "")
    assert result["percent"] == 50.0


def test_measure_empty_module_counts_as_full():
    report = {"files": {"src/__init__.py": _file(0, 0)}}
    result = gate.measure(report, lambda _p: "")
    assert result["percent"] == 100.0


# --- Ausnahmen -------------------------------------------------------------

def test_stale_exemption_is_reported():
    report = {"files": {"src/pure.py": _file(1, 1)}}
    assert gate.stale_exemptions(report) == sorted(gate.EXEMPT)


def test_exemptions_exist_and_are_tk_free():
    """Eine Ausnahme für ein Tk-Modul wäre wirkungslos, eine für eine
    verschwundene Datei griffe still beim nächsten gleichnamigen Modul."""
    for name in gate.EXEMPT:
        path = _ROOT / name
        assert path.is_file(), name
        assert not gate.imports_tkinter(path.read_text(encoding="utf-8")), name


def test_real_split_puts_ui_and_storage_on_the_expected_sides():
    read = lambda name: (_ROOT / name).read_text(encoding="utf-8")  # noqa: E731
    assert gate.imports_tkinter(read("src/ui.py"))
    assert not gate.imports_tkinter(read("src/storage.py"))


# --- main ------------------------------------------------------------------

def _run(tmp_path, monkeypatch, percent_hits):
    report = {"files": {"src/pure.py": _file(100, percent_hits)}
              | {name: _file(1, 0) for name in gate.EXEMPT}}
    target = tmp_path / "coverage.json"
    target.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(gate, "_read_source", lambda _p: "")
    return gate.main(["coverage_gate.py", str(target)])


def test_main_fails_below_floor(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gate, "FLOOR", 80.0)
    assert _run(tmp_path, monkeypatch, 79) == 1
    assert "::error::" in capsys.readouterr().out


def test_main_passes_at_floor(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gate, "FLOOR", 80.0)
    assert _run(tmp_path, monkeypatch, 80) == 0
    assert "::notice::" not in capsys.readouterr().out


def test_main_suggests_ratchet_when_well_above(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gate, "FLOOR", 80.0)
    assert _run(tmp_path, monkeypatch, 90) == 0
    assert "::notice::" in capsys.readouterr().out


def test_main_missing_report_is_an_error(tmp_path, capsys):
    assert gate.main(["coverage_gate.py", str(tmp_path / "fehlt.json")]) == 2
    assert "::error::" in capsys.readouterr().out
