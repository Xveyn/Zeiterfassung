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


class _FakeButton:
    """Fake für den Sync-Button: winfo_ismapped für update_status_label
    (meldet sich als bereits gepackt). Das optische Enable/Disable läuft über
    theme.set_icon_button_enabled, das die Tests im Orchestrator-Namespace
    monkeypatchen (der echte icon_button ist ein _LabelButton mit `_label`)."""
    def winfo_ismapped(self):
        return True


def _patch_dim(monkeypatch):
    """Ersetzt set_icon_button_enabled im Orchestrator durch einen Rekorder und
    gibt die Aufrufliste [(button, enabled), ...] zurück."""
    import src.sync_orchestrator as so
    calls = []
    monkeypatch.setattr(so, "set_icon_button_enabled",
                        lambda btn, enabled, **k: calls.append((btn, enabled)))
    return calls


def _orch(sync_enabled=True, execute_runner=False, get_tray=lambda: None,
          conflicts=0, on_refresh=None, data_lock=None, sync_guard=None):
    _vals = {"sync_enabled": sync_enabled, "last_pull_at": None}
    settings = MagicMock(get=lambda k, d=None: _vals.get(k, d))
    conflicts_store = MagicMock(count_unresolved=lambda: conflicts)
    runner = _FakeRunner(execute=execute_runner)
    orch = SyncOrchestrator(
        root=object(), storage=object(), settings=settings,
        conflicts_store=conflicts_store, base_path=".", runner=runner,
        on_refresh=on_refresh or (lambda: None), get_tray=get_tray,
        data_lock=data_lock, sync_guard=sync_guard,
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


def test_on_sync_clicked_enabled_sets_label_and_runs(monkeypatch):
    _patch_dim(monkeypatch)
    orch, runner = _orch(sync_enabled=True, execute_runner=False)
    label = _FakeLabel()
    orch.attach_widgets(sync_button=_FakeButton(), status_label=label,
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


def test_on_sync_clicked_dims_button(monkeypatch):
    calls = _patch_dim(monkeypatch)
    orch, runner = _orch(sync_enabled=True, execute_runner=False)
    label, button = _FakeLabel(), _FakeButton()
    orch.attach_widgets(sync_button=button, status_label=label,
                        next_button=object())
    orch.on_sync_clicked()
    assert calls == [(button, False)]   # optisch deaktiviert (kein -state!)
    assert orch._sync_in_progress is True


def test_on_manual_done_reenables_button(monkeypatch):
    calls = _patch_dim(monkeypatch)
    orch, _ = _orch(sync_enabled=True)
    label, button = _FakeLabel(), _FakeButton()
    orch.attach_widgets(sync_button=button, status_label=label,
                        next_button=object())
    orch._on_manual_done({"ok": True})
    assert calls == [(button, True)]    # optisch wieder aktiv
    assert orch._sync_in_progress is False


def test_on_sync_clicked_reentrant_is_noop(monkeypatch):
    # Der icon_button ist nur optisch deaktivierbar; das _sync_in_progress-Flag
    # trägt den No-op. Runner führt NICHT aus -> _on_manual_done setzt das Flag
    # nicht zurück, der zweite Klick muss folgenlos bleiben.
    _patch_dim(monkeypatch)
    orch, runner = _orch(sync_enabled=True, execute_runner=False)
    label, button = _FakeLabel(), _FakeButton()
    orch.attach_widgets(sync_button=button, status_label=label,
                        next_button=object())
    orch.on_sync_clicked()
    orch.on_sync_clicked()              # zweiter Klick während laufendem Sync
    assert len(runner.calls) == 1       # war ein No-op


def test_on_manual_done_skipped_shows_no_error(monkeypatch):
    import src.sync_orchestrator as so
    _patch_dim(monkeypatch)
    errors = []
    monkeypatch.setattr(so, "_show_sync_error", lambda *a, **k: errors.append(a))
    refreshed = []
    orch, _ = _orch(sync_enabled=True, on_refresh=lambda: refreshed.append(1))
    label, button = _FakeLabel(), _FakeButton()
    orch.attach_widgets(sync_button=button, status_label=label,
                        next_button=object())
    orch._on_manual_done({"ok": False, "skipped": True})
    assert errors == []          # kein Fehlerdialog — anderer Sync läuft nur
    assert refreshed == []       # kein Refresh nötig, nichts hat sich geändert
    assert orch._sync_in_progress is False


def test_on_tray_done_skipped_no_toast():
    tray = MagicMock()
    orch, _ = _orch(get_tray=lambda: tray)
    orch._on_tray_done({"ok": False, "skipped": True})
    tray.notify.assert_not_called()


def test_push_passes_lock_guard_and_timeouts(monkeypatch):
    captured = {}

    def fake(storage, settings, conflicts_store, base, timeout_seconds=5, **kw):
        captured.update(kw)
        captured["timeout_seconds"] = timeout_seconds
        return {"ok": True}

    monkeypatch.setattr("src.main._run_push_blocking", fake)
    lock, guard = object(), object()
    orch, _ = _orch(sync_enabled=True, data_lock=lock, sync_guard=guard)
    orch._push()
    assert captured["data_lock"] is lock
    assert captured["sync_guard"] is guard
    assert captured["guard_timeout"] == 0
    assert captured["timeout_seconds"] == 15


def test_push_on_quit_uses_guard_timeout(monkeypatch):
    captured = {}

    def fake(storage, settings, conflicts_store, base, timeout_seconds=5, **kw):
        captured.update(kw)
        captured["timeout_seconds"] = timeout_seconds
        return {"ok": True}

    monkeypatch.setattr("src.main._run_push_blocking", fake)
    orch, _ = _orch(sync_enabled=True)
    orch.push_on_quit()
    assert captured["guard_timeout"] == 5
    assert captured["timeout_seconds"] == 10


def test_push_on_quit_skipped_logs_no_dialog(monkeypatch):
    import src.sync_orchestrator as so
    errors = []
    monkeypatch.setattr(so, "_show_sync_error", lambda *a, **k: errors.append(a))
    monkeypatch.setattr("src.main._run_push_blocking",
                        lambda *a, **k: {"ok": False, "skipped": True})
    orch, _ = _orch(sync_enabled=True)
    orch.push_on_quit()
    assert errors == []
