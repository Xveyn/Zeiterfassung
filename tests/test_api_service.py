# tests/test_api_service.py
import http.client
import socket
import threading
import time

import pytest

from src import api_service
from src.api_routes import ApiContext
from src.api_service import (
    DEFAULT_PORT, REASON_CLOSED, REASON_INVALID_PORT, REASON_PORT_IN_USE,
    REASON_ROTATE_FAILED, REASON_TOKEN_UNAVAILABLE, STATE_ERROR, STATE_OFF,
    STATE_RUNNING, STATE_STARTING, ApiService, ApiStatus, RefreshCoalescer, RotateResult,
    parse_port,
)
from src.settings import DEFAULTS
from src.storage import Storage


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def sync_run(fn, on_done=None):
    result = fn()
    if on_done is not None:
        on_done(result)


def make_service(tmp_path, settings, run=sync_run, statuses=None):
    storage = Storage(str(tmp_path / "zeiterfassung.json"), device_id="dev")
    context = ApiContext(storage=storage, settings=settings, app_version=lambda: "t")
    on_status = statuses.append if statuses is not None else None
    return ApiService(settings, str(tmp_path), context, run=run, on_status=on_status)


def token_of(tmp_path):
    return (tmp_path / "api-token").read_text(encoding="ascii")


def get_status_code(port, token):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", "/v1/status", headers={"Authorization": f"Bearer {token}"})
        response = conn.getresponse()
        response.read()
        return response.status
    finally:
        conn.close()


def port_is_closed(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return True
    return False


# --- parse_port -----------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (17653, 17653), ("17653", 17653), (" 8080 ", 8080), (1024, 1024), (65535, 65535),
    (1023, None), (0, None), (80, None), (65536, None), (70000, None), (-5, None),
    ("abc", None), ("", None), ("17653.5", None), (17653.0, None), (None, None),
    (True, None), ("٨٠٨٠", None), ("9" * 5000, None), ([8080], None),
])
def test_parse_port(value, expected):
    assert parse_port(value) == expected


def test_default_port_matches_the_settings_default():
    assert DEFAULT_PORT == DEFAULTS["api_port"]


# --- Aus, Ein, Aus --------------------------------------------------------------------

def test_disabled_by_default_starts_nothing_and_creates_no_token(tmp_path):
    service = make_service(tmp_path, {"api_enabled": False, "api_port": free_port()})

    service.apply()

    assert service.status == ApiStatus(STATE_OFF)
    assert not (tmp_path / "api-token").exists()


def test_enabling_starts_the_server_with_the_stored_token(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})

    service.apply()
    try:
        assert service.status == ApiStatus(STATE_RUNNING, port)
        assert get_status_code(port, token_of(tmp_path)) == 200
        assert get_status_code(port, "falsch") == 401
    finally:
        service.shutdown()


def test_disabling_stops_the_server_and_frees_the_port(tmp_path):
    port = free_port()
    settings = {"api_enabled": True, "api_port": port}
    service = make_service(tmp_path, settings)
    service.apply()

    settings["api_enabled"] = False
    service.apply()

    assert service.status == ApiStatus(STATE_OFF)
    assert port_is_closed(port)


def test_changing_the_port_rebinds(tmp_path):
    first, second = free_port(), free_port()
    settings = {"api_enabled": True, "api_port": first}
    service = make_service(tmp_path, settings)
    service.apply()
    try:
        settings["api_port"] = second
        service.apply()

        assert service.status == ApiStatus(STATE_RUNNING, second)
        assert port_is_closed(first)
        assert get_status_code(second, token_of(tmp_path)) == 200
    finally:
        service.shutdown()


def test_applying_the_same_settings_twice_keeps_the_running_server(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()
    try:
        server = service._server
        token = token_of(tmp_path)

        service.apply()

        assert service._server is server
        assert token_of(tmp_path) == token
    finally:
        service.shutdown()


# --- Review Focus 5: ungültige Settings ---------------------------------------------------

@pytest.mark.parametrize("bad", ["abc", 0, 80, 70000, None, True, "", "17653.5", -5])
def test_invalid_port_is_an_error_status_without_server_or_token(tmp_path, bad):
    service = make_service(tmp_path, {"api_enabled": True, "api_port": bad})

    service.apply()

    assert service.status == ApiStatus(STATE_ERROR, None, REASON_INVALID_PORT)
    assert service._server is None
    assert not (tmp_path / "api-token").exists()


def test_port_in_use_is_reported_and_recovers_when_freed(tmp_path):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    try:
        service.apply()
        assert service.status == ApiStatus(STATE_ERROR, port, REASON_PORT_IN_USE)

        blocker.close()
        service.apply()
        assert service.status == ApiStatus(STATE_RUNNING, port)
    finally:
        blocker.close()
        service.shutdown()


def test_unusable_token_location_is_an_error_status(tmp_path):
    missing = tmp_path / "gibt-es-nicht"
    storage = Storage(str(tmp_path / "z.json"), device_id="dev")
    settings = {"api_enabled": True, "api_port": free_port()}
    context = ApiContext(storage=storage, settings=settings, app_version=lambda: "t")
    service = ApiService(settings, str(missing), context, run=sync_run)

    service.apply()

    assert service.status == ApiStatus(STATE_ERROR, None, REASON_TOKEN_UNAVAILABLE)
    assert service._server is None


def test_status_changes_are_reported_to_the_callback(tmp_path):
    port = free_port()
    statuses = []
    settings = {"api_enabled": True, "api_port": port}
    service = make_service(tmp_path, settings, statuses=statuses)

    service.apply()
    settings["api_enabled"] = False
    service.apply()

    assert statuses == [ApiStatus(STATE_RUNNING, port), ApiStatus(STATE_OFF)]


# --- Review Focus 4: Beenden und Entfernen -----------------------------------------------------

def test_shutdown_stops_the_server_and_blocks_further_applies(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()

    service.shutdown()
    assert port_is_closed(port)

    service.apply()                              # darf nichts mehr starten
    assert port_is_closed(port)


def test_reopen_allows_starting_again(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()
    service.shutdown()

    service.reopen()
    service.apply()
    try:
        assert service.status == ApiStatus(STATE_RUNNING, port)
    finally:
        service.shutdown()


def test_shutdown_before_the_worker_runs_prevents_any_start(tmp_path):
    jobs = []
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port},
                           run=lambda fn, on_done=None: jobs.append(fn))
    service.apply()

    service.shutdown()
    jobs[0]()                                    # der Worker läuft erst jetzt

    assert port_is_closed(port)
    assert not (tmp_path / "api-token").exists()


def test_shutdown_during_the_token_load_neither_blocks_nor_starts(tmp_path, monkeypatch):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    real_loader = api_service.load_or_create_token
    elapsed = []

    def loader(base_path):
        token = real_loader(base_path)
        began = time.monotonic()
        service.shutdown(lock_timeout=0.05)      # Worker hält den Lock
        elapsed.append(time.monotonic() - began)
        return token

    monkeypatch.setattr(api_service, "load_or_create_token", loader)

    service.apply()

    assert elapsed and elapsed[0] < 1.0
    assert service.status.state != STATE_RUNNING
    assert port_is_closed(port)


def test_unexpected_errors_in_the_worker_become_an_error_status(tmp_path, monkeypatch, caplog):
    service = make_service(tmp_path, {"api_enabled": True, "api_port": free_port()})

    def boom(base_path):
        raise RuntimeError("unerwartet")

    monkeypatch.setattr(api_service, "load_or_create_token", boom)

    service.apply()

    assert service.status.state == STATE_ERROR
    assert "Lokale API" in caplog.text


def test_concurrent_applies_end_in_one_running_server(tmp_path):
    port = free_port()
    threads = []
    statuses = []

    def thread_run(fn, on_done=None):
        def body():
            result = fn()
            if on_done is not None:
                on_done(result)
        thread = threading.Thread(target=body)
        threads.append(thread)
        thread.start()

    service = make_service(tmp_path, {"api_enabled": True, "api_port": port},
                           run=thread_run, statuses=statuses)
    try:
        for _ in range(10):
            service.apply()
        for thread in threads:
            thread.join()

        assert service.status == ApiStatus(STATE_RUNNING, port)
        assert all(s == ApiStatus(STATE_RUNNING, port) for s in statuses)
        assert get_status_code(port, token_of(tmp_path)) == 200
    finally:
        service.shutdown()


# --- PR 3: Zustand „startet", aktueller Status, Rotation, Token lesen -------------

def deferred_run(jobs):
    def run(fn, on_done=None):
        jobs.append((fn, on_done))
    return run


def test_apply_shows_starting_before_the_worker_has_run(tmp_path):
    jobs = []
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port},
                           run=deferred_run(jobs))

    service.apply()
    assert service.status == ApiStatus(STATE_STARTING, port)

    fn, on_done = jobs[0]
    on_done(fn())
    try:
        assert service.status == ApiStatus(STATE_RUNNING, port)
    finally:
        service.shutdown()


def test_apply_does_not_flash_starting_while_the_server_already_runs(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()                                     # läuft
    jobs = []
    service._run = deferred_run(jobs)                   # ab hier verzögert
    try:
        service.apply()

        assert service.status == ApiStatus(STATE_RUNNING, port)
        fn, _ = jobs[0]
        assert fn() == ApiStatus(STATE_RUNNING, port)   # „läuft schon" meldet RUNNING
    finally:
        service.shutdown()


@pytest.mark.parametrize("settings", [
    {"api_enabled": False, "api_port": 17653},
    {"api_enabled": True, "api_port": "abc"},
])
def test_apply_shows_no_starting_when_nothing_will_start(tmp_path, settings):
    jobs = []
    service = make_service(tmp_path, dict(settings), run=deferred_run(jobs))

    service.apply()

    assert service.status.state == STATE_OFF


def test_status_callback_reports_the_current_status_not_a_late_workers_result(tmp_path):
    port = free_port()
    jobs, statuses = [], []
    settings = {"api_enabled": True, "api_port": port}
    service = make_service(tmp_path, settings, run=deferred_run(jobs), statuses=statuses)
    service.apply()
    first_fn, first_done = jobs[0]
    first_result = first_fn()                           # RUNNING
    settings["api_enabled"] = False
    service.apply()
    second_fn, second_done = jobs[1]
    second_done(second_fn())                            # OFF

    first_done(first_result)                            # kommt zu spät an

    assert statuses == [ApiStatus(STATE_OFF), ApiStatus(STATE_OFF)]


def test_rotate_switches_the_token_of_the_running_server_without_a_restart(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()
    try:
        old, server = token_of(tmp_path), service._server

        result = service.rotate()

        new = token_of(tmp_path)
        assert result == RotateResult(True) and new != old
        assert service._server is server
        assert get_status_code(port, old) == 401
        assert get_status_code(port, new) == 200
    finally:
        service.shutdown()


def test_rotate_without_a_server_writes_the_token_and_starts_nothing(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": False, "api_port": port})

    result = service.rotate()

    assert result == RotateResult(True)
    assert (tmp_path / "api-token").exists() and port_is_closed(port)


def test_failed_rotation_keeps_the_old_token_valid(tmp_path, monkeypatch):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()
    try:
        old = token_of(tmp_path)

        def boom(base_path):
            raise OSError("nicht schreibbar")

        monkeypatch.setattr(api_service, "rotate_token", boom)

        result = service.rotate()

        assert result == RotateResult(False, REASON_ROTATE_FAILED)
        assert token_of(tmp_path) == old
        assert get_status_code(port, old) == 200
    finally:
        service.shutdown()


def test_rotate_after_shutdown_is_refused_and_changes_nothing(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()
    old = token_of(tmp_path)
    service.shutdown()

    result = service.rotate()

    assert result == RotateResult(False, REASON_CLOSED)
    assert token_of(tmp_path) == old


def test_rotation_is_serialized_against_a_start_in_progress(tmp_path, monkeypatch):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    entered, release = threading.Event(), threading.Event()
    real_loader = api_service.load_or_create_token

    def slow_loader(base_path):
        token = real_loader(base_path)
        entered.set()
        assert release.wait(5)
        return token

    monkeypatch.setattr(api_service, "load_or_create_token", slow_loader)
    starter = threading.Thread(target=service._reconcile)
    starter.start()
    assert entered.wait(5)
    rotated = []
    rotator = threading.Thread(target=lambda: rotated.append(service.rotate()))
    rotator.start()

    rotator.join(0.3)
    assert rotator.is_alive(), "rotate() hätte auf den laufenden Start warten müssen"
    release.set()
    starter.join(5)
    rotator.join(5)

    try:
        assert rotated == [RotateResult(True)]
        # Die Datei trägt das neue Token — und genau das akzeptiert der Server.
        assert get_status_code(port, token_of(tmp_path)) == 200
    finally:
        service.shutdown()


def test_read_token_returns_the_file_token_and_creates_nothing(tmp_path):
    service = make_service(tmp_path, {"api_enabled": False, "api_port": 17653})

    assert service.read_token() is None
    assert list(tmp_path.glob("api-token*")) == []

    (tmp_path / "api-token").write_text("a" * 43, encoding="ascii")
    assert service.read_token() == "a" * 43


def test_a_stale_starting_status_is_corrected_when_the_server_already_runs(tmp_path):
    # Rennen: `apply()` liest „läuft noch nicht" und schreibt STARTING, der Worker
    # des vorigen `apply()` startet den Server aber schon. Der nächste Worker darf
    # dieses STARTING nicht durchreichen.
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()
    try:
        service._status = ApiStatus(STATE_STARTING, port)

        assert service._reconcile() == ApiStatus(STATE_RUNNING, port)
    finally:
        service.shutdown()



# --- Review PR 4: Refresh bündeln, Schreiben beim Beenden sperren --------------------------------------

def test_refresh_requests_are_coalesced_into_one_scheduled_run():
    scheduled, ran = [], []
    coalescer = RefreshCoalescer(scheduled.append, lambda: ran.append(1))

    for _ in range(1000):                   # ein Backfill-Skript mit 1000 PUTs
        coalescer.request()

    assert len(scheduled) == 1 and ran == []
    scheduled[0]()
    assert ran == [1]


def test_a_request_after_the_run_schedules_again():
    scheduled, ran = [], []
    coalescer = RefreshCoalescer(scheduled.append, lambda: ran.append(1))
    coalescer.request()
    scheduled.pop()()

    coalescer.request()

    assert len(scheduled) == 1


def test_a_failing_schedule_does_not_wedge_the_coalescer():
    calls = []

    def schedule(fn):
        calls.append(fn)
        raise RuntimeError("Fenster weg")

    coalescer = RefreshCoalescer(schedule, lambda: None)
    with pytest.raises(RuntimeError):
        coalescer.request()
    with pytest.raises(RuntimeError):
        coalescer.request()                 # „ansteht“ wurde zurückgesetzt

    assert len(calls) == 2


def test_a_failing_action_still_clears_the_pending_flag():
    scheduled = []

    def action():
        raise ValueError("kaputt")

    coalescer = RefreshCoalescer(scheduled.append, action)
    coalescer.request()
    with pytest.raises(ValueError):
        scheduled.pop()()

    coalescer.request()

    assert len(scheduled) == 1


def test_concurrent_requests_schedule_exactly_once():
    scheduled = []
    coalescer = RefreshCoalescer(scheduled.append, lambda: None)
    barrier = threading.Barrier(20)

    def worker():
        barrier.wait()
        coalescer.request()

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(scheduled) == 1


def test_the_write_context_knows_when_the_service_is_closing(tmp_path):
    service = make_service(tmp_path, {"api_enabled": False, "api_port": 17653})
    assert service._context.closing() is False

    service.shutdown()
    assert service._context.closing() is True

    service.reopen()
    assert service._context.closing() is False


# --- Härtung aus dem Review von PR 3 (#233) -----------------------------------------------

def test_an_unexpected_error_in_rotation_is_a_failed_result_not_a_dead_worker(tmp_path, monkeypatch, caplog):
    service = make_service(tmp_path, {"api_enabled": False, "api_port": free_port()})

    def boom(base_path):
        raise ValueError("kein OSError")

    monkeypatch.setattr(api_service, "rotate_token", boom)

    with caplog.at_level("WARNING"):
        result = service.rotate()

    assert result == RotateResult(False, REASON_ROTATE_FAILED)
    assert "konnte nicht erneuert" in caplog.text


def test_a_successful_rotation_clears_the_token_unavailable_error(tmp_path, monkeypatch):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    monkeypatch.setattr(api_service, "load_or_create_token", lambda base_path: None)
    service.apply()
    assert service.status.reason == "token_unavailable"
    monkeypatch.undo()                                  # das Token ist wieder erzeugbar
    try:
        result = service.rotate()

        assert result == RotateResult(True)
        assert service.status.state == STATE_RUNNING and service.status.port == port
        assert get_status_code(port, token_of(tmp_path)) == 200
    finally:
        service.shutdown()


def test_a_shutdown_that_gave_up_during_a_rotation_still_stops_the_server(tmp_path, monkeypatch):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()
    assert not port_is_closed(port)
    entered, release = threading.Event(), threading.Event()
    real = api_service.rotate_token

    def slow(base_path):
        entered.set()
        release.wait(5)
        return real(base_path)

    monkeypatch.setattr(api_service, "rotate_token", slow)
    worker = threading.Thread(target=service.rotate)
    worker.start()
    assert entered.wait(5)

    service.shutdown(lock_timeout=0.05)                 # wartet nicht auf die Rotation
    assert not port_is_closed(port)                     # der Server läuft noch ...
    release.set()
    worker.join(5)

    assert port_is_closed(port)                         # ... bis die Rotation fertig ist
    assert service.status.state == STATE_OFF
