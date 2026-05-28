import importlib
import pathlib
import subprocess
import sys

import pytest


def test_activate_patches_module_functions(tmp_path):
    from src import drive, gcal, mail
    from src.dev import activate, fakes

    # Originale merken, um nach dem Test wiederherzustellen
    originals = {
        (mail, "get_gmail_service"): mail.get_gmail_service,
        (mail, "send_email"): mail.send_email,
        (drive, "get_drive_service"): drive.get_drive_service,
        (drive, "find_sync_file"): drive.find_sync_file,
        (drive, "download"): drive.download,
        (drive, "upload"): drive.upload,
        (gcal, "get_calendar_service"): gcal.get_calendar_service,
        (gcal, "list_app_events"): gcal.list_app_events,
        (gcal, "create_event"): gcal.create_event,
        (gcal, "update_event"): gcal.update_event,
        (gcal, "delete_event"): gcal.delete_event,
    }
    try:
        activate(str(tmp_path))
        assert mail.send_email is fakes.fake_send_email
        assert mail.get_gmail_service is fakes.fake_get_gmail_service
        assert drive.upload is fakes.fake_upload
        assert drive.find_sync_file is fakes.fake_find_sync_file
        assert gcal.create_event is fakes.fake_create_event
        assert gcal.list_app_events is fakes.fake_list_app_events
        # Seed lief mit
        assert (tmp_path / "zeiterfassung.json").exists()
    finally:
        for (module, name), fn in originals.items():
            setattr(module, name, fn)


def test_normal_import_does_not_load_dev():
    """Ein Import von src.main (ohne --dev) zieht src.dev NICHT mit rein."""
    pytest.importorskip("tkinter")  # CI ohne tkinter überspringt diesen Guard
    repo = pathlib.Path(__file__).resolve().parents[1]
    code = (
        "import sys; import src.main; "
        "leaked = [m for m in sys.modules if m.startswith('src.dev')]; "
        "assert not leaked, leaked"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=str(repo),
    )
    assert result.returncode == 0, result.stderr


def test_log_handler_formats_record():
    import logging as _logging
    from src.dev.console import _TkLogHandler

    captured = []

    class _FakeWidget:
        def config(self, **k): pass
        def insert(self, *a): captured.append(a[1])
        def see(self, *a): pass

    class _FakeRoot:
        def after(self, _delay, fn, *args):
            fn(*args)  # synchron ausführen statt über die Tk-Eventloop

    handler = _TkLogHandler(_FakeWidget(), _FakeRoot())
    record = _logging.LogRecord("zeiterfassung.dev", _logging.INFO,
                                "x.py", 1, "Hallo Welt", None, None)
    handler.emit(record)
    assert any("Hallo Welt" in line for line in captured)
