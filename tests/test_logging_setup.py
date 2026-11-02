# tests/test_logging_setup.py
import logging
import sys
import tkinter as tk
from logging.handlers import RotatingFileHandler

import pytest

from src.logging_setup import (
    setup_logging, get_log_path, LOG_SUBDIR, LOGFILE_NAME, QUIET_LOGGERS,
)


@pytest.fixture
def isolated_logging():
    """Fixture: Speichert + restored Root-Logger und Excepthooks pro Test."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_quiet = {n: logging.getLogger(n).level for n in QUIET_LOGGERS}
    saved_excepthook = sys.excepthook
    saved_tk_hook = tk.Tk.report_callback_exception
    yield
    # Cleanup: Handler schließen, damit das Logfile nicht von Windows gelockt bleibt.
    for handler in root.handlers:
        if handler not in saved_handlers:
            handler.close()
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    for name, level in saved_quiet.items():
        logging.getLogger(name).setLevel(level)
    sys.excepthook = saved_excepthook
    tk.Tk.report_callback_exception = saved_tk_hook


def test_setup_logging_creates_subdir_and_logfile(tmp_path, isolated_logging):
    log_path = setup_logging(str(tmp_path))
    assert log_path == str(tmp_path / LOG_SUBDIR / LOGFILE_NAME)
    assert (tmp_path / LOG_SUBDIR).is_dir()


def test_setup_logging_writes_log_records(tmp_path, isolated_logging):
    log_path = setup_logging(str(tmp_path))
    logging.getLogger("test").info("hallo welt")
    for h in logging.getLogger().handlers:
        h.flush()
    with open(log_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "hallo welt" in content
    assert "INFO" in content


def test_setup_logging_is_idempotent(tmp_path, isolated_logging):
    setup_logging(str(tmp_path))
    setup_logging(str(tmp_path))
    handlers = [
        h for h in logging.getLogger().handlers
        if isinstance(h, RotatingFileHandler)
    ]
    assert len(handlers) == 1


def test_setup_logging_installs_sys_excepthook(tmp_path, isolated_logging):
    original = sys.excepthook
    setup_logging(str(tmp_path))
    assert sys.excepthook is not original


def test_setup_logging_installs_tk_callback_excepthook(tmp_path, isolated_logging):
    original = tk.Tk.report_callback_exception
    setup_logging(str(tmp_path))
    assert tk.Tk.report_callback_exception is not original


def test_get_log_path_does_not_create_dir(tmp_path):
    path = get_log_path(str(tmp_path))
    assert path == str(tmp_path / LOG_SUBDIR / LOGFILE_NAME)
    assert not (tmp_path / LOG_SUBDIR).exists()


def _console_handlers():
    return [h for h in logging.getLogger().handlers
            if type(h) is logging.StreamHandler]


def test_setup_logging_console_adds_stream_handler_once(tmp_path, isolated_logging):
    setup_logging(str(tmp_path), console=True)
    setup_logging(str(tmp_path), console=True)
    assert len(_console_handlers()) == 1


def test_setup_logging_without_console_adds_no_stream_handler(tmp_path, isolated_logging):
    setup_logging(str(tmp_path), console=False)
    assert _console_handlers() == []


def test_setup_logging_console_auto_follows_frozen(tmp_path, isolated_logging, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    setup_logging(str(tmp_path))
    assert _console_handlers() == []


def test_setup_logging_console_auto_in_source_mode(tmp_path, isolated_logging, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    setup_logging(str(tmp_path))
    assert len(_console_handlers()) == 1


def test_log_level_env_overrides_default(tmp_path, isolated_logging, monkeypatch):
    monkeypatch.setenv("ZEITERFASSUNG_LOG_LEVEL", "debug")
    setup_logging(str(tmp_path), console=False)
    assert logging.getLogger().level == logging.DEBUG


@pytest.mark.parametrize("value", ["", "quatsch", "42"])
def test_log_level_env_invalid_falls_back_to_default(
        tmp_path, isolated_logging, monkeypatch, value):
    monkeypatch.setenv("ZEITERFASSUNG_LOG_LEVEL", value)
    setup_logging(str(tmp_path), console=False)
    assert logging.getLogger().level == logging.INFO


def test_noisy_third_party_loggers_are_quieted(tmp_path, isolated_logging):
    setup_logging(str(tmp_path), console=False)
    for name, level in QUIET_LOGGERS.items():
        assert logging.getLogger(name).level == level


def test_noisy_loggers_stay_loud_under_debug(tmp_path, isolated_logging, monkeypatch):
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)
    monkeypatch.setenv("ZEITERFASSUNG_LOG_LEVEL", "DEBUG")
    setup_logging(str(tmp_path), console=False)
    for name in QUIET_LOGGERS:
        assert logging.getLogger(name).level == logging.NOTSET


def test_googleapiclient_http_is_not_quieted():
    # Die 403-Warnungen dort sind das Signal für einen fehlenden Scope (#45).
    assert "googleapiclient.http" not in QUIET_LOGGERS
