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


# --- Erfolgspfade (Xveyn#401): eine INFO-Zeile mit Zählwerten und Dauer ---------

import json as _json  # noqa: E402
import threading  # noqa: E402

from src.conflicts_store import ConflictsStore  # noqa: E402
from src.settings import Settings  # noqa: E402
from src.storage import Storage  # noqa: E402
from tests.conftest import ist_slot as _slot  # noqa: E402


def _env(tmp_path, monkeypatch):
    from src import drive
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    storage.save("2026-06-09", [_slot("09:00", "17:00")])
    settings = Settings(str(tmp_path / "s.json"))
    settings.device_id_for_sync = "A"
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    remote = _json.dumps({"schema_version": 2, "entries": {}, "settings": {},
                          "conflicts": [], "meta": {"gc_watermark": ""}}).encode()
    monkeypatch.setattr(drive, "get_drive_service", lambda *a, **k: object())
    monkeypatch.setattr(drive, "find_sync_file", lambda service: "file-1")
    monkeypatch.setattr(drive, "download", lambda service, fid: (remote, "etag-x"))
    monkeypatch.setattr(drive, "upload", lambda *a, **k: ("file-1", "etag-new"))
    return storage, settings, conflicts


def _runtime_records(caplog, level):
    return [r for r in caplog.records
            if r.name == "src.sync_runtime" and r.levelno == level]


def test_pull_success_logs_one_info_line(tmp_path, monkeypatch, caplog):
    storage, settings, conflicts = _env(tmp_path, monkeypatch)
    got = {}
    with caplog.at_level(logging.INFO, logger="src.sync_runtime"):
        sync_runtime.run_pull_in_background(
            storage, settings, conflicts, str(tmp_path),
            lambda ok, error, tb="": got.update(ok=ok))
    assert got["ok"] is True
    lines = [r.getMessage() for r in _runtime_records(caplog, logging.INFO)]
    assert len(lines) == 1
    assert lines[0].startswith("Sync pull ok (1 Einträge, 0 Konflikte) in ")
    assert lines[0].endswith(" s")
    # nur Zählwerte, nie Inhalte
    assert "2026-06-09" not in lines[0]


def test_push_success_logs_one_info_line(tmp_path, monkeypatch, caplog):
    storage, settings, conflicts = _env(tmp_path, monkeypatch)
    with caplog.at_level(logging.INFO, logger="src.sync_runtime"):
        res = sync_runtime.run_push_blocking(storage, settings, conflicts, str(tmp_path))
    assert res["ok"] is True
    lines = [r.getMessage() for r in _runtime_records(caplog, logging.INFO)]
    assert len(lines) == 1 and lines[0].startswith("Sync push ok (1 Einträge")


def test_compaction_success_logs_one_info_line(tmp_path, monkeypatch, caplog):
    storage, settings, conflicts = _env(tmp_path, monkeypatch)
    with caplog.at_level(logging.INFO, logger="src.sync_runtime"):
        res = sync_runtime.run_compaction_blocking(
            storage, settings, conflicts, str(tmp_path))
    assert res["ok"] is True
    lines = [r.getMessage() for r in _runtime_records(caplog, logging.INFO)]
    assert len(lines) == 1 and lines[0].startswith("Kompaktierung ok (")


def test_failed_sync_logs_no_ok_line(tmp_path, monkeypatch, caplog):
    from src import drive
    storage, settings, conflicts = _env(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise DriveAuthError("invalid_grant")
    monkeypatch.setattr(drive, "get_drive_service", boom)
    with caplog.at_level(logging.INFO, logger="src.sync_runtime"):
        res = sync_runtime.run_push_blocking(storage, settings, conflicts, str(tmp_path))
    assert res["ok"] is False
    assert _runtime_records(caplog, logging.INFO) == []


def test_busy_guard_is_logged_on_debug_only(tmp_path, monkeypatch, caplog):
    storage, settings, conflicts = _env(tmp_path, monkeypatch)
    guard = threading.Lock()
    guard.acquire()
    with caplog.at_level(logging.DEBUG, logger="src.sync_runtime"):
        res = sync_runtime.run_push_blocking(
            storage, settings, conflicts, str(tmp_path), sync_guard=guard)
    assert res.get("skipped") is True
    assert _runtime_records(caplog, logging.INFO) == []
    debug = [r.getMessage() for r in _runtime_records(caplog, logging.DEBUG)]
    assert any("Sync push übersprungen" in m for m in debug)


def test_calendar_reconcile_success_logs_one_info_line(tmp_path, monkeypatch, caplog):
    from src import gcal, reservations_sync
    storage, settings, _ = _env(tmp_path, monkeypatch)
    settings.set_many({"gcal_enabled": True, "gcal_calendar_id": "cal"})
    monkeypatch.setattr(gcal, "get_calendar_service", lambda *a, **k: object())
    monkeypatch.setattr(reservations_sync, "reconcile_reservations",
                        lambda *a, **k: {"imported_dates": {"2026-07-01", "2026-07-02"}})
    with caplog.at_level(logging.INFO, logger="src.sync_runtime"):
        res = sync_runtime.run_calendar_reconcile(
            object(), settings, str(tmp_path), storage)
    assert res["ok"] is True
    lines = [r.getMessage() for r in _runtime_records(caplog, logging.INFO)]
    assert len(lines) == 1
    assert "Reservierungen: 2 Tage importiert" in lines[0]
    assert "Urlaub-Push: aus" in lines[0]
