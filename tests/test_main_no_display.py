"""Start ohne Display (#145): verständliche Meldung statt nacktem Abbruch.

Per SSH, in einer TTY oder einem Container scheitert schon `tk.Tk()`. Vorher
stand im Terminal nur „Failed to execute script 'main'", der Grund landete im
Log. Geprüft wird `main._create_root` mit einer Fake-Fabrik — ohne echtes Tk.
"""

import io
import logging
import tkinter as tk

import pytest

from src import main as main_mod


def _failing(message):
    def factory():
        raise tk.TclError(message)
    return factory


def test_root_is_returned_when_tk_starts():
    sentinel = object()
    assert main_mod._create_root(lambda: sentinel) is sentinel


def test_missing_display_exits_with_a_clear_message(monkeypatch, caplog):
    stderr = io.StringIO()
    monkeypatch.setattr(main_mod.sys, "stderr", stderr)

    with caplog.at_level(logging.ERROR, logger="src.main"):
        with pytest.raises(SystemExit) as exc_info:
            main_mod._create_root(
                _failing("no display name and no $DISPLAY environment variable"))

    assert exc_info.value.code == 1
    assert "Kein Display gefunden" in stderr.getvalue()
    assert "grafische Sitzung" in stderr.getvalue()
    assert "Kein Display gefunden" in caplog.text


def test_other_tk_start_errors_name_the_original_cause(monkeypatch):
    """Nicht jeder TclError beim Start ist das Display (z. B. fehlende
    Tcl-Bibliothek) — dann steht der Originaltext in der Meldung."""
    stderr = io.StringIO()
    monkeypatch.setattr(main_mod.sys, "stderr", stderr)

    with pytest.raises(SystemExit):
        main_mod._create_root(_failing("Can't find a usable init.tcl"))

    assert "Can't find a usable init.tcl" in stderr.getvalue()
    assert "Kein Display gefunden" not in stderr.getvalue()


def test_no_stderr_under_noconsole_still_exits_cleanly(monkeypatch):
    """Windows-Build mit --noconsole: sys.stderr ist None. Der Hinweis darf
    dann nicht selbst zum nächsten Absturz werden."""
    monkeypatch.setattr(main_mod.sys, "stderr", None)

    with pytest.raises(SystemExit) as exc_info:
        main_mod._create_root(_failing("no display name"))

    assert exc_info.value.code == 1
