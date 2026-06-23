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


def test_fetch_sender_email_noop_without_token(tmp_path):
    # base_path ohne token.json -> fetch_user_email darf nicht aufgerufen werden
    import src.background_tasks as bg

    called = {"n": 0}
    orig = bg.fetch_user_email
    bg.fetch_user_email = lambda *a, **k: called.__setitem__("n", called["n"] + 1) or ""
    try:
        _runner(base_path=str(tmp_path)).fetch_sender_email()
        import time
        time.sleep(0.2)
    finally:
        bg.fetch_user_email = orig
    assert called["n"] == 0
