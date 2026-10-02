"""`BackgroundTaskRunner.wait_idle` (#50): das Entfernen wartet laufende
Hintergrundjobs ab, bevor es Dateien löscht."""

import threading

from src.background_tasks import BackgroundTaskRunner


def _runner():
    return BackgroundTaskRunner(
        marshal=lambda fn: fn(), settings=None, base_path="",
        reservation_store=None, reservations_active=lambda: False)


def test_idle_runner_returns_immediately():
    assert _runner().wait_idle(0.5) is True


def test_wait_idle_waits_for_a_running_job():
    runner = _runner()
    release = threading.Event()
    runner.run(release.wait)

    assert runner.wait_idle(0.05) is False        # Job läuft noch
    release.set()
    assert runner.wait_idle(2.0) is True


def test_wait_idle_can_ignore_the_caller_itself():
    """Der Entfern-Worker läuft selbst über `run` und zählt sich nicht mit."""
    runner = _runner()
    seen = {}
    done = threading.Event()

    def work():
        seen["idle"] = runner.wait_idle(1.0, own=1)
        done.set()

    runner.run(work)

    assert done.wait(2.0)
    assert seen["idle"] is True


def test_a_failing_job_still_counts_as_finished():
    runner = _runner()

    def boom():
        raise RuntimeError("kaputt")

    runner.run(boom)

    assert runner.wait_idle(2.0) is True
