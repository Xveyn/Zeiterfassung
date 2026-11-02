"""„Log-Ordner öffnen" im App-Tab (Xveyn#409): öffnet `logs/`, meldet kuratiert,
wenn es ihn noch nicht gibt, und behandelt Fehler wie der Datenordner-Knopf."""
import types

import pytest

import src.dialogs.settings_dialog.tab_app as tab_app
from src.logging_setup import LOG_SUBDIR


def _tab(base):
    tab = object.__new__(tab_app.AppTab)
    tab._base_path = str(base)
    tab._dialog = "dialog"
    return tab


@pytest.fixture
def calls(monkeypatch):
    got = types.SimpleNamespace(opened=[], info=[], errors=[])
    monkeypatch.setattr(tab_app, "open_folder", lambda p: got.opened.append(p))
    monkeypatch.setattr(tab_app, "themed_showinfo",
                        lambda parent, title, msg, **k: got.info.append((parent, title, msg)))
    monkeypatch.setattr(tab_app.messagebox, "showerror",
                        lambda title, msg, **k: got.errors.append((title, msg)))
    return got


def test_opens_the_logs_folder(tmp_path, calls):
    (tmp_path / LOG_SUBDIR).mkdir()
    _tab(tmp_path)._open_log_folder()
    assert calls.opened == [str(tmp_path / LOG_SUBDIR)]
    assert calls.info == [] and calls.errors == []


def test_missing_logs_folder_is_a_curated_info_not_a_traceback(tmp_path, calls):
    _tab(tmp_path)._open_log_folder()
    assert calls.opened == []
    assert calls.errors == []
    assert len(calls.info) == 1
    assert calls.info[0][0] == "dialog"
    assert "Log" in calls.info[0][2]


def test_open_failure_shows_the_native_error_with_traceback(tmp_path, calls, monkeypatch):
    (tmp_path / LOG_SUBDIR).mkdir()

    def boom(path):
        raise OSError("kein Dateimanager")
    monkeypatch.setattr(tab_app, "open_folder", boom)
    _tab(tmp_path)._open_log_folder()
    assert len(calls.errors) == 1
    assert "kein Dateimanager" in calls.errors[0][1]


def test_data_folder_button_still_opens_the_base_path(tmp_path, calls):
    _tab(tmp_path)._open_data_folder()
    assert calls.opened == [str(tmp_path)]
