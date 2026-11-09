"""ScaleWatcher (Xveyn#201): meldet nur Übergänge des Zustands „Skalierung
passt nicht zum Monitor“, nicht jeden Tick."""

from src.scale_watch import ScaleWatcher


class FakeRoot:
    def __init__(self):
        self.scheduled = []
        self.cancelled = []

    def after(self, ms, fn):
        self.scheduled.append((ms, fn))
        return f"id{len(self.scheduled)}"

    def after_cancel(self, ident):
        self.cancelled.append(ident)


def make(states):
    root, seen = FakeRoot(), []
    it = iter(states)
    watcher = ScaleWatcher(root, lambda: next(it), seen.append)
    return watcher, root, seen


def test_reports_only_transitions():
    watcher, _, seen = make([False, True, True, False, False])
    for _ in range(5):
        watcher.poll()
    assert seen == [True, False]


def test_no_report_while_everything_matches():
    watcher, _, seen = make([False, False])
    watcher.poll()
    watcher.poll()
    assert seen == []


def test_start_is_idempotent_and_stop_cancels():
    watcher, root, _ = make([])
    watcher.start()
    watcher.start()
    assert len(root.scheduled) == 1
    watcher.stop()
    assert root.cancelled == ["id1"]
    watcher.stop()
    assert root.cancelled == ["id1"]


def test_tick_reschedules_even_if_check_raises():
    root, seen = FakeRoot(), []

    def boom():
        raise RuntimeError("x")
    watcher = ScaleWatcher(root, boom, seen.append)
    watcher.start()
    root.scheduled[0][1]()
    assert len(root.scheduled) == 2
    assert seen == []


# --- Automatischer Neustart (Xveyn#201) -------------------------------------

from src.scale_watch import MIN_UPTIME_S, may_auto_restart  # noqa: E402


def _ok(**over):
    args = dict(enabled=True, mismatch=True, dialog_open=False,
                bg_busy=False, uptime_s=MIN_UPTIME_S)
    args.update(over)
    return may_auto_restart(**args)


def test_auto_restart_when_everything_allows_it():
    assert _ok() is True


def test_auto_restart_needs_the_setting():
    assert _ok(enabled=False) is False


def test_auto_restart_needs_a_mismatch():
    assert _ok(mismatch=False) is False


def test_auto_restart_never_with_a_dialog_open():
    assert _ok(dialog_open=True) is False


def test_auto_restart_waits_for_background_jobs():
    assert _ok(bg_busy=True) is False


def test_auto_restart_not_right_after_start():
    """Schutz vor einer Neustart-Schleife bei flatterndem Xft.dpi."""
    assert _ok(uptime_s=MIN_UPTIME_S - 1) is False
