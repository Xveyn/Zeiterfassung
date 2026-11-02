# tests/test_sync_runtime_logging.py
"""Auth-Fehler im Sync-Log: eine WARNING-Zeile, kein Traceback (Xveyn#401)."""
import logging

import pytest

from src import sync_runtime
from src.drive import DriveAuthError
from src.gcal import CalendarAuthError
from src.oauth_utils import REAUTH_REQUIRED_MSG, TokenKeyringUnavailable


def _failure(caplog, error):
    with caplog.at_level(logging.DEBUG, logger="src.sync_runtime"):
        try:
            raise error
        except Exception as e:
            sync_runtime._log_failure("Sync pull failed", e)
    return [r for r in caplog.records if r.name == "src.sync_runtime"]


@pytest.mark.parametrize("error", [
    DriveAuthError("invalid_grant: Token has been expired or revoked."),
    CalendarAuthError(REAUTH_REQUIRED_MSG),
    TokenKeyringUnavailable(),
])
def test_expected_auth_failure_is_one_warning_without_traceback(caplog, error):
    records = _failure(caplog, error)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].exc_info is None
    assert "Sync pull failed" in records[0].getMessage()
    assert str(error) in records[0].getMessage()


def test_unexpected_failure_keeps_traceback(caplog):
    records = _failure(caplog, RuntimeError("kaputt"))
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None
    assert records[0].exc_info[0] is RuntimeError
