"""BackgroundTaskRunner: run() fuehrt fn im Thread aus und liefert das
Ergebnis ueber marshal an on_done. marshal wird im Test synchron gefakt."""

import os
import threading

import pytest

import src.background_tasks as bg
from src.background_tasks import BackgroundTaskRunner
from src.mail import TokenAuthError, TokenNetworkError
from src.settings import Settings


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


def test_run_swallows_and_logs_fn_exception(caplog):
    # N19: wirft fn() unerwartet, darf der Worker nicht still sterben —
    # der Fehler wird geloggt und on_done feuert NICHT (kein halber Zustand).
    import logging
    entered = threading.Event()
    on_done_called = threading.Event()

    def boom():
        entered.set()
        raise RuntimeError("kaputt")

    with caplog.at_level(logging.ERROR):
        _runner().run(boom, on_done=lambda _r: on_done_called.set())
        assert entered.wait(timeout=5)          # fn lief
        assert not on_done_called.wait(timeout=0.5)  # on_done NICHT gefeuert

    assert any("Hintergrund-Task fehlgeschlagen" in r.message for r in caplog.records)


def test_check_update_skips_when_not_due(monkeypatch):
    import src.background_tasks as bg
    monkeypatch.setattr(bg, "should_check", lambda last, freq: False)
    called = {"n": 0}
    monkeypatch.setattr(bg, "check_for_update",
                        lambda repo, include: called.__setitem__("n", called["n"] + 1))
    r = _runner(settings={
        "last_update_check_at": None, "update_check_frequency": "daily",
    })
    r.check_update(on_result=lambda rel, newer: None)
    import time
    time.sleep(0.2)
    assert called["n"] == 0


def test_check_update_reads_frequency_from_settings(monkeypatch):
    import src.background_tasks as bg
    seen = {}

    def fake_should_check(last, freq):
        seen["frequency"] = freq
        return False

    monkeypatch.setattr(bg, "should_check", fake_should_check)
    r = _runner(settings={
        "last_update_check_at": None, "update_check_frequency": "weekly",
    })
    r.check_update(on_result=lambda rel, newer: None)
    import time
    time.sleep(0.2)
    assert seen["frequency"] == "weekly"


def test_check_update_uses_stable_channel_by_default(monkeypatch):
    import src.background_tasks as bg
    seen = {}

    def fake_check(repo, include):
        seen["include"] = include
        return None            # None, damit der Worker sauber abbricht

    monkeypatch.setattr(bg, "should_check", lambda last, freq: True)
    monkeypatch.setattr(bg, "check_for_update", fake_check)
    r = _runner(settings={
        "last_update_check_at": None, "update_check_frequency": "daily",
        "prerelease_updates_enabled": False,
    })
    r.check_update(on_result=lambda rel, newer: None)
    import time
    time.sleep(0.2)
    assert seen["include"] is False


def test_check_update_passes_prerelease_flag_from_settings(monkeypatch):
    import src.background_tasks as bg
    seen = {}

    def fake_check(repo, include):
        seen["include"] = include
        return None

    monkeypatch.setattr(bg, "should_check", lambda last, freq: True)
    monkeypatch.setattr(bg, "check_for_update", fake_check)
    r = _runner(settings={
        "last_update_check_at": None, "update_check_frequency": "daily",
        "prerelease_updates_enabled": True,
    })
    r.check_update(on_result=lambda rel, newer: None)
    import time
    time.sleep(0.2)
    assert seen["include"] is True


def test_check_update_compares_against_installed_release_id(monkeypatch):
    import src.background_tasks as bg
    from src.updater import Release

    release = Release(
        version="1.19.0", html_url="x", assets=(),
        release_id="1.19.0-pre.2", is_prerelease=True,
    )
    monkeypatch.setattr(bg, "should_check", lambda last, freq: True)
    monkeypatch.setattr(bg, "check_for_update", lambda repo, include: release)
    monkeypatch.setattr(bg, "installed_release_id", lambda: "1.19.0-pre.1")
    got = {}
    r = _runner(settings={
        "last_update_check_at": None, "update_check_frequency": "daily",
        "prerelease_updates_enabled": True,
    })
    r.check_update(on_result=lambda rel, newer: got.update(rel=rel, newer=newer))
    import time
    time.sleep(0.3)
    assert got["newer"] is True
    assert got["rel"] is release


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
    import src.background_tasks as bt_module

    captured = {}

    def fake_reconcile(reservation_store, settings, base_path, storage, data_lock=None,
                       vacation_store=None):
        captured["storage"] = storage
        return {"ok": True, "error": "", "tb": "", "limit_warnings": ["w"]}

    monkeypatch.setattr(bt_module, "run_calendar_reconcile", fake_reconcile)

    received = {}
    sentinel_storage = object()
    r = _runner(reservations_active=lambda: True, storage=sentinel_storage)
    r.reconcile_on_start(on_ok=lambda result: received.__setitem__("result", result))

    import time
    time.sleep(0.2)
    assert captured["storage"] is sentinel_storage
    assert received["result"]["limit_warnings"] == ["w"]


def test_trigger_reconcile_passes_storage_through(monkeypatch):
    import src.background_tasks as bt_module

    captured = {}

    def fake_reconcile(reservation_store, settings, base_path, storage, data_lock=None,
                       vacation_store=None):
        captured["storage"] = storage
        return {"ok": True, "error": "", "tb": "", "limit_warnings": []}

    monkeypatch.setattr(bt_module, "run_calendar_reconcile", fake_reconcile)

    done = threading.Event()
    sentinel_storage = object()
    r = _runner(reservations_active=lambda: True, storage=sentinel_storage)
    r.trigger_reconcile(lambda result: done.set())

    assert done.wait(timeout=5)
    assert captured["storage"] is sentinel_storage


# --- refresh_token / fetch_sender_email ------------------------------------
#
# Beide liefern ihr Ergebnis über on_done im UI-Thread aus. Der Marshal-Fake
# meldet, wann das passiert ist — so wartet der Test auf das Ende des
# Workers statt auf eine geratene Schlafdauer.

def _runner_reporting_done(**overrides):
    finished = threading.Event()

    def marshal(callback):
        try:
            callback()
        finally:
            finished.set()

    return _runner(marshal=marshal, **overrides), finished


def _fake_refresh(monkeypatch, raises=None, calls=None):
    def fake(token_path, sync_enabled=False, gcal_enabled=False):
        if calls is not None:
            calls.append((token_path, sync_enabled, gcal_enabled))
        if raises is not None:
            raise raises

    monkeypatch.setattr(bg, "refresh_token_if_needed", fake)


def test_refresh_token_reports_an_auth_error(monkeypatch):
    """Widerrufener Token: der Nutzer muss es erfahren, sonst scheitert erst
    der nächste Versand."""
    _fake_refresh(monkeypatch, raises=TokenAuthError("Token widerrufen"))
    auth_errors, errors = [], []
    runner, finished = _runner_reporting_done()

    runner.refresh_token(on_auth_error=auth_errors.append, on_error=errors.append)

    assert finished.wait(timeout=5)
    assert auth_errors == ["Token widerrufen"]
    assert errors == []


@pytest.mark.parametrize("raises", [
    pytest.param(TokenNetworkError("offline"), id="offline"),
    pytest.param(None, id="erfolgreich"),
])
def test_refresh_token_stays_silent_when_offline_or_fine(monkeypatch, raises):
    """Ein Offline-Start ist kein Fehler — ein Dialog beim Hochfahren im Zug
    wäre genau die Störung, die der stille Refresh vermeiden soll."""
    _fake_refresh(monkeypatch, raises=raises)
    auth_errors, errors = [], []
    runner, finished = _runner_reporting_done()

    runner.refresh_token(on_auth_error=auth_errors.append, on_error=errors.append)

    assert finished.wait(timeout=5)
    assert auth_errors == []
    assert errors == []


def test_refresh_token_reports_an_unexpected_error_with_traceback(monkeypatch):
    """--noconsole schluckt stderr: der Traceback im Dialog ist die einzige
    Spur eines unerwarteten Fehlers."""
    _fake_refresh(monkeypatch, raises=ValueError("token.json kaputt"))
    auth_errors, errors = [], []
    runner, finished = _runner_reporting_done()

    runner.refresh_token(on_auth_error=auth_errors.append, on_error=errors.append)

    assert finished.wait(timeout=5)
    assert auth_errors == []
    assert len(errors) == 1
    assert "Traceback" in errors[0]
    assert "ValueError: token.json kaputt" in errors[0]


def test_refresh_token_requests_the_scopes_of_all_enabled_features(monkeypatch, tmp_path):
    """Gmail, Drive und Kalender teilen einen Token. Refresht der Start ihn
    ohne die Flags, fehlen danach die Scopes der eingeschalteten Features."""
    calls = []
    _fake_refresh(monkeypatch, calls=calls)
    runner, finished = _runner_reporting_done(
        base_path=str(tmp_path),
        settings={"sync_enabled": True, "gcal_enabled": True})

    runner.refresh_token(on_auth_error=lambda msg: None, on_error=lambda tb: None)

    assert finished.wait(timeout=5)
    assert calls == [(os.path.join(str(tmp_path), "token.json"), True, True)]


def _sender_email_setup(tmp_path, monkeypatch, fetched):
    (tmp_path / "token.json").write_text("{}", encoding="utf-8")
    settings = Settings(str(tmp_path / "settings.json"))
    settings.set("sender_email", "alt@example.com")
    monkeypatch.setattr(
        bg, "fetch_user_email",
        lambda token_path, sync_enabled=False, gcal_enabled=False: fetched)
    return _runner_reporting_done(settings=settings, base_path=str(tmp_path))


def test_fetch_sender_email_caches_a_changed_address(tmp_path, monkeypatch):
    runner, finished = _sender_email_setup(tmp_path, monkeypatch, "neu@example.com")

    runner.fetch_sender_email()

    assert finished.wait(timeout=5)
    assert Settings(str(tmp_path / "settings.json")).get("sender_email") == "neu@example.com"


@pytest.mark.parametrize("fetched", [
    pytest.param("", id="leer"),
    pytest.param(None, id="keine-antwort"),
])
def test_fetch_sender_email_keeps_the_cached_address_without_a_result(
        tmp_path, monkeypatch, fetched):
    """Kein Ergebnis heißt „nicht ermittelbar“, nicht „keine Adresse“ — der
    Cache darf davon nicht geleert werden."""
    runner, finished = _sender_email_setup(tmp_path, monkeypatch, fetched)

    runner.fetch_sender_email()

    assert finished.wait(timeout=5)
    assert Settings(str(tmp_path / "settings.json")).get("sender_email") == "alt@example.com"


@pytest.mark.parametrize("outcome", ["ok", "auth", "error", "keyring"])
def test_start_refresh_calls_on_finished_after_every_outcome(outcome, monkeypatch):
    """Der Umzug der Zugangsdaten hängt an on_finished (#101) — er muss nach
    JEDEM Ausgang kommen, sonst zöge eine Installation nie um."""
    from src import background_tasks
    from src.mail import TokenAuthError
    from src.oauth_utils import TokenKeyringUnavailable

    def fake_refresh(*a, **k):
        if outcome == "auth":
            raise TokenAuthError("invalid_grant")
        if outcome == "error":
            raise RuntimeError("kaputt")
        if outcome == "keyring":
            raise TokenKeyringUnavailable()
        return "valid"

    monkeypatch.setattr(background_tasks, "refresh_token_if_needed", fake_refresh)
    runner = background_tasks.BackgroundTaskRunner.__new__(background_tasks.BackgroundTaskRunner)
    runner._base_path = "."
    runner._settings = {"sync_enabled": False, "gcal_enabled": False}
    runner.run = lambda fn, on_done: on_done(fn())  # pyright: ignore[reportOptionalCall]
    events = []

    runner.refresh_token(on_auth_error=lambda m: events.append("auth"),
                         on_error=lambda tb: events.append("error"),
                         on_finished=lambda: events.append("finished"))

    assert events[-1] == "finished" and events.count("finished") == 1
    assert ("auth" in events) == (outcome == "auth")
    assert ("error" in events) == (outcome == "error")
