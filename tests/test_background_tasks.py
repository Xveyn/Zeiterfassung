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
        storage=overrides.pop("storage", None),
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


def test_check_update_skips_when_not_due(monkeypatch):
    import src.background_tasks as bg
    monkeypatch.setattr(bg, "should_check_today", lambda v: False)
    called = {"n": 0}
    monkeypatch.setattr(bg, "check_latest_release",
                        lambda repo: called.__setitem__("n", called["n"] + 1))
    r = _runner(settings={"last_update_check_at": None})
    # settings als dict -> .get reicht; should_check_today ist gepatcht
    r.check_update(on_result=lambda rel, newer: None)
    import time
    time.sleep(0.2)
    assert called["n"] == 0


def test_reconcile_on_start_skips_when_reservations_inactive():
    ran = {"n": 0}
    r = _runner(reservations_active=lambda: False)
    r.reconcile_on_start(on_ok=lambda result: ran.__setitem__("n", ran["n"] + 1))
    import time
    time.sleep(0.2)
    assert ran["n"] == 0


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


def test_reconcile_on_start_passes_storage_and_result_to_on_ok(monkeypatch):
    import src.main as main_module

    captured = {}

    def fake_reconcile(reservation_store, settings, base_path, storage):
        captured["storage"] = storage
        return {"ok": True, "error": "", "tb": "", "limit_warnings": ["w"]}

    monkeypatch.setattr(main_module, "run_calendar_reconcile", fake_reconcile)

    received = {}
    sentinel_storage = object()
    r = _runner(reservations_active=lambda: True, storage=sentinel_storage)
    r.reconcile_on_start(on_ok=lambda result: received.__setitem__("result", result))

    import time
    time.sleep(0.2)
    assert captured["storage"] is sentinel_storage
    assert received["result"]["limit_warnings"] == ["w"]


def test_trigger_reconcile_passes_storage_through(monkeypatch):
    import src.main as main_module

    captured = {}

    def fake_reconcile(reservation_store, settings, base_path, storage):
        captured["storage"] = storage
        return {"ok": True, "error": "", "tb": "", "limit_warnings": []}

    monkeypatch.setattr(main_module, "run_calendar_reconcile", fake_reconcile)

    done = threading.Event()
    sentinel_storage = object()
    r = _runner(reservations_active=lambda: True, storage=sentinel_storage)
    r.trigger_reconcile(lambda result: done.set())

    assert done.wait(timeout=5)
    assert captured["storage"] is sentinel_storage
