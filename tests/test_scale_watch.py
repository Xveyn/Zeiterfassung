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
