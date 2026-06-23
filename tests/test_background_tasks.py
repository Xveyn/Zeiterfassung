"""BackgroundTaskRunner: run() fuehrt fn im Thread aus und liefert das
Ergebnis ueber marshal an on_done. marshal wird im Test synchron gefakt."""

import threading

from src.background_tasks import BackgroundTaskRunner


def _runner(**overrides):
    kw = dict(
        marshal=lambda cb: cb(),          # synchron ausfuehren
        settings=overrides.pop("settings", {}),
        base_path=overrides.pop("base_path", "."),
        reservation_store=overrides.pop("reservation_store", None),
        reservations_active=overrides.pop("reservations_active", lambda: False),
    )
    kw.update(overrides)
    return BackgroundTaskRunner(**kw)


def test_run_executes_fn_and_delivers_result_to_on_done():
    done = threading.Event()
    received = {}

    def on_done(result):
        received["value"] = result
        done.set()

    _runner().run(lambda: 42, on_done)

    assert done.wait(timeout=5)
    assert received["value"] == 42


def test_run_without_on_done_still_executes_fn():
    ran = threading.Event()

    def fn():
        ran.set()
        return None

    _runner().run(fn)

    assert ran.wait(timeout=5)
