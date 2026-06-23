"""SyncOrchestrator: reine Formatier-Helfer (ohne Tk)."""

from src.sync_orchestrator import _status_text, _tray_toast


def test_status_text_no_conflicts_shows_last_pull():
    assert _status_text(0, "2026-06-14") == "✓ 14.06.2026"


def test_status_text_never_pulled_fallback():
    assert _status_text(0, None) == "✓ noch nie"


def test_status_text_single_conflict_singular():
    assert _status_text(1, "2026-06-14") == "⚠ 1 Konflikt"


def test_status_text_multiple_conflicts_plural():
    assert _status_text(3, "2026-06-14") == "⚠ 3 Konflikte"


def test_tray_toast_ok_no_conflicts():
    assert _tray_toast(True, 0, None) == "Synchronisiert."


def test_tray_toast_ok_single_conflict():
    assert _tray_toast(True, 1, None) == "Synchronisiert — 1 Konflikt offen."


def test_tray_toast_ok_multiple_conflicts():
    assert _tray_toast(True, 2, None) == "Synchronisiert — 2 Konflikte offen."


def test_tray_toast_failure():
    assert _tray_toast(False, 0, "boom") == "Sync fehlgeschlagen:\nboom"
