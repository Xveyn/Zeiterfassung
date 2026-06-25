"""SyncOrchestrator: reine Formatier-Helfer (ohne Tk) + Klassen-Tests."""

from unittest.mock import MagicMock

from src.sync_orchestrator import SyncOrchestrator, _status_text, _tray_toast


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


# ---------------------------------------------------------------------------
# SyncOrchestrator class tests
# ---------------------------------------------------------------------------

class _FakeRunner:
    def __init__(self, execute=True):
        self.calls = []
        self._execute = execute

    def run(self, fn, on_done=None):
        self.calls.append((fn, on_done))
        if self._execute:
            result = fn()
            if on_done is not None:
                on_done(result)


class _FakeLabel:
    def __init__(self):
        self.text = None

    def config(self, text):
        self.text = text


def _orch(sync_enabled=True, execute_runner=False, get_tray=lambda: None,
          conflicts=0, on_refresh=None):
    _vals = {"sync_enabled": sync_enabled, "last_pull_at": None}
    settings = MagicMock(get=lambda k, d=None: _vals.get(k, d))
    conflicts_store = MagicMock(count_unresolved=lambda: conflicts)
    runner = _FakeRunner(execute=execute_runner)
    orch = SyncOrchestrator(
        root=object(), storage=object(), settings=settings,
        conflicts_store=conflicts_store, base_path=".", runner=runner,
        on_refresh=on_refresh or (lambda: None), get_tray=get_tray,
    )
    return orch, runner


def test_on_sync_clicked_disabled_does_not_run(monkeypatch):
    import src.sync_orchestrator as so
    shown = []
    monkeypatch.setattr(so, "themed_showinfo",
                        lambda *a, **k: shown.append(a))
    orch, runner = _orch(sync_enabled=False)
    orch.on_sync_clicked()
    assert runner.calls == []
    assert shown  # Hinweis-Dialog gezeigt


def test_on_sync_clicked_enabled_sets_label_and_runs():
    orch, runner = _orch(sync_enabled=True, execute_runner=False)
    label = _FakeLabel()
    orch.attach_widgets(sync_button=object(), status_label=label,
                        next_button=object())
    orch.on_sync_clicked()
    assert label.text == "Synchronisiere…"
    assert len(runner.calls) == 1
    assert runner.calls[0][1] == orch._on_manual_done


def test_on_tray_done_notifies_with_toast():
    tray = MagicMock()
    orch, _ = _orch(get_tray=lambda: tray, conflicts=2)
    # ohne attach_widgets -> update_status_label() no-op (status_label None)
    orch._on_tray_done({"ok": True})
    tray.notify.assert_called_once_with("Synchronisiert — 2 Konflikte offen.",
                                        title="")


def test_on_tray_done_without_tray_does_not_crash():
    orch, _ = _orch(get_tray=lambda: None)
    orch._on_tray_done({"ok": True})  # darf nicht werfen


def test_push_on_quit_disabled_is_noop():
    orch, _ = _orch(sync_enabled=False)
    # darf nicht werfen und nichts pushen (Guard greift vor dem Lazy-Import)
    orch.push_on_quit()
