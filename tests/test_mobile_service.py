# tests/test_mobile_service.py
import http.client
import json
import socket
import threading

import pytest

from src import mobile_pairing, mobile_routes
from src.api_auth import ANONYMOUS
from src.api_routes import ApiRequest
from src.conflicts_store import ConflictsStore
from src.mobile_pairing import PairingSession
from src.mobile_service import (
    DEFAULT_PORT, REASON_ADDRESS_GONE, REASON_INVALID_PORT, REASON_NO_ADDRESS,
    REASON_PORT_IN_USE, STATE_ERROR, STATE_OFF, STATE_RUNNING, STATE_STARTING, MobileService,
    MobileStatus,
)
from src.mobile_store import MobileStore
from src.settings import DEFAULTS, Settings
from src.storage import Storage
from src.time_utils import utc_now_iso

ORIGIN = "https://xveyn.github.io"
LOOPBACK = "127.0.0.1"


def free_port():
    with socket.socket() as sock:
        sock.bind((LOOPBACK, 0))
        return sock.getsockname()[1]


def sync_run(fn, on_done=None):
    result = fn()
    if on_done is not None:
        on_done(result)


def make_service(tmp_path, *, enabled=True, port=None, address="", candidates=(LOOPBACK,),
                 run=sync_run, statuses=None):
    settings = Settings(str(tmp_path / "settings.json"))
    settings.device_id_for_sync = "DESK"
    settings.set_many({"mobile_enabled": enabled, "mobile_port": port or free_port(),
                       "mobile_address": address})
    ctx = mobile_routes.MobileContext(
        pairing=PairingSession(),
        devices=MobileStore(str(tmp_path / "mobile_devices.json")),
        devices_lock=threading.RLock(),
        storage=Storage(str(tmp_path / "zeiterfassung.json"), device_id="DESK"),
        settings=settings,
        conflicts_store=ConflictsStore(str(tmp_path / "conflicts.json")),
        base=str(tmp_path), desktop_name=lambda: "Desktop")
    on_status = statuses.append if statuses is not None else None
    service = MobileService(settings, ctx, run=run, on_status=on_status,
                            lan_candidates=lambda: list(candidates))
    return service, settings, ctx


def http_call(port, method, path, *, token=None, body=None, origin=ORIGIN, host=None):
    conn = http.client.HTTPConnection(LOOPBACK, port, timeout=5)
    try:
        headers = {}
        if origin:
            headers["Origin"] = origin
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if host:
            headers["Host"] = host
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.putrequest(method, path, skip_host=host is not None, skip_accept_encoding=True)
        for name, value in headers.items():
            conn.putheader(name, value)
        if payload is not None:
            conn.putheader("Content-Length", str(len(payload)))
        conn.endheaders(payload)
        response = conn.getresponse()
        raw = response.read()
        return response, (json.loads(raw) if raw else None)
    finally:
        conn.close()


def port_is_closed(port):
    try:
        socket.create_connection((LOOPBACK, port), timeout=1).close()
    except OSError:
        return True
    return False


@pytest.fixture
def started(tmp_path):
    service, settings, ctx = make_service(tmp_path)
    service.apply()
    yield service, settings, ctx
    service.shutdown()


# --- Defaults -----------------------------------------------------------------------------------------

def test_the_default_port_matches_the_settings_default():
    assert DEFAULT_PORT == DEFAULTS["mobile_port"] == 17654


# --- Zustände -------------------------------------------------------------------------------------------

def test_a_disabled_service_runs_nothing(tmp_path):
    service, _settings, _ctx = make_service(tmp_path, enabled=False)
    service.apply()
    assert service.status == MobileStatus(STATE_OFF)


def test_an_enabled_service_binds_the_chosen_address_and_answers(started):
    service, _settings, ctx = started

    assert service.status.state == STATE_RUNNING and service.status.address == LOOPBACK
    port = service.status.port
    record, token = mobile_pairing.issue_device("phone-0001", "Pixel", utc_now_iso())
    ctx.devices.save(record)
    response, body = http_call(port, "GET", "/v1/ping", token=token)

    assert response.status == 200 and body["protocol"] == 1
    assert response.getheader("Access-Control-Allow-Origin") == ORIGIN


def test_the_server_only_accepts_the_exact_host_and_origin(started):
    service, _settings, _ctx = started
    port = service.status.port

    wrong_host, _b = http_call(port, "GET", "/v1/ping", host="evil.example:80")
    wrong_origin, _b2 = http_call(port, "GET", "/v1/ping", origin="https://evil.example")
    no_token, body = http_call(port, "GET", "/v1/ping")

    assert wrong_host.status == 403 and wrong_origin.status == 403
    assert no_token.status == 401 and body["error"]["code"] == "unauthorized"


def test_the_local_api_surface_is_not_reachable_through_the_phone_server(started):
    service, _settings, ctx = started
    record, token = mobile_pairing.issue_device("phone-0001", "Pixel", utc_now_iso())
    ctx.devices.save(record)

    for path in ("/v1/status", "/v1/entries", "/v1/entries/2026-10-07"):
        response, _body = http_call(service.status.port, "GET", path, token=token)
        assert response.status == 404


def test_pairing_and_syncing_work_end_to_end_over_a_real_socket(started):
    service, _settings, ctx = started
    port = service.status.port
    code = service.pairing.open()

    paired, body = http_call(port, "POST", "/v1/pair", body={
        "code": code, "device_name": "Pixel", "device_id": "phone-0001"})
    token = body["token"]
    entries = {"2026-10-07": {"slots": [{"start": "08:00", "end": "12:00", "pause": 0,
                                         "kategorie": "Projekt"}],
                              "modified_at": "2026-10-07T18:30:00Z", "deleted": False}}
    synced, answer = http_call(port, "POST", "/v1/sync", token=token, body={
        "protocol": 1, "client_time": utc_now_iso(), "entries": entries})
    renewed = answer["token"]
    still_old, _b = http_call(port, "GET", "/v1/ping", token=token)       # Karenz
    new_ok, _b2 = http_call(port, "GET", "/v1/ping", token=renewed)

    assert paired.status == 200 and synced.status == 200
    assert ctx.storage.get_all_raw()["2026-10-07"]["device_id"] == "phone-0001"
    assert still_old.status == 200 and new_ok.status == 200
    assert paired.getheader("Access-Control-Allow-Origin") == ORIGIN


def test_a_refused_pairing_has_no_token_in_the_answer(started):
    service, _settings, _ctx = started
    service.pairing.open()

    response, body = http_call(service.status.port, "POST", "/v1/pair", body={
        "code": "AAAA-AAAA", "device_name": "P", "device_id": "phone-0001"})

    assert response.status == 403 and "token" not in json.dumps(body)


def test_switching_off_stops_the_server_and_closes_the_pairing_session(tmp_path):
    service, settings, _ctx = make_service(tmp_path)
    service.apply()
    port = service.status.port
    service.pairing.open()

    settings.set("mobile_enabled", False)
    service.apply()

    assert service.status == MobileStatus(STATE_OFF)
    assert port_is_closed(port) and not service.pairing.is_active()


def test_changing_the_port_restarts_on_the_new_one(tmp_path):
    service, settings, _ctx = make_service(tmp_path)
    service.apply()
    first = service.status.port
    second = free_port()

    settings.set("mobile_port", second)
    service.apply()

    assert service.status.state == STATE_RUNNING and service.status.port == second
    assert port_is_closed(first)
    service.shutdown()


def test_applying_again_without_a_change_keeps_the_server_and_the_code(started):
    service, _settings, _ctx = started
    service.pairing.open()

    service.apply()

    assert service.status.state == STATE_RUNNING and service.pairing.is_active()


@pytest.mark.parametrize("bad", [0, 80, 70000, "abc", None, True, 17654.5])
def test_an_invalid_port_is_an_error(tmp_path, bad):
    service, settings, _ctx = make_service(tmp_path)
    settings.set("mobile_port", bad)

    service.apply()

    assert service.status == MobileStatus(STATE_ERROR, None, None, REASON_INVALID_PORT)


def test_no_lan_address_is_an_error_and_starts_nothing(tmp_path):
    service, _settings, _ctx = make_service(tmp_path, candidates=())

    service.apply()

    assert service.status.state == STATE_ERROR and service.status.reason == REASON_NO_ADDRESS


def test_a_vanished_address_is_an_error_and_never_replaced_silently(tmp_path):
    service, _settings, _ctx = make_service(tmp_path, address="192.168.77.5",
                                            candidates=(LOOPBACK, "10.0.0.5"))

    service.apply()

    assert service.status.state == STATE_ERROR and service.status.reason == REASON_ADDRESS_GONE
    assert service.status.address == "192.168.77.5"


def test_a_running_server_stops_when_its_address_vanishes(tmp_path):
    candidates = [LOOPBACK]
    service, _settings, _ctx = make_service(tmp_path, address=LOOPBACK, candidates=candidates)
    service.apply()
    port = service.status.port
    assert service.status.state == STATE_RUNNING

    candidates[:] = ["10.0.0.5"]                  # die Adresse ist weg (anderes WLAN)
    service.apply()

    assert service.status.reason == REASON_ADDRESS_GONE and port_is_closed(port)


def test_a_busy_port_is_reported(tmp_path):
    port = free_port()
    with socket.socket() as blocker:
        blocker.bind((LOOPBACK, port))
        blocker.listen(1)
        service, _settings, _ctx = make_service(tmp_path, port=port)

        service.apply()

    assert service.status.state == STATE_ERROR and service.status.reason == REASON_PORT_IN_USE


def test_apply_shows_starting_before_the_worker_ran(tmp_path):
    queued = []
    service, _settings, _ctx = make_service(tmp_path, run=lambda fn, done=None: queued.append((fn, done)))

    service.apply()

    assert service.status.state == STATE_STARTING and len(queued) == 1


def test_the_status_callback_gets_the_current_status(tmp_path):
    statuses = []
    service, _settings, _ctx = make_service(tmp_path, statuses=statuses)

    service.apply()

    assert statuses and statuses[-1].state == STATE_RUNNING
    service.shutdown()


def test_shutdown_stops_the_server_and_blocks_new_starts_until_reopened(tmp_path):
    service, _settings, _ctx = make_service(tmp_path)
    service.apply()
    port = service.status.port

    service.shutdown()
    service.apply()

    assert port_is_closed(port) and service.status.state == STATE_OFF
    service.reopen()
    service.apply()
    assert service.status.state == STATE_RUNNING
    service.shutdown()


def test_routes_refuse_work_after_shutdown(tmp_path):
    service, _settings, ctx = make_service(tmp_path)
    service.apply()
    code = service.pairing.open()
    service.shutdown()
    request = ApiRequest("POST", "/v1/pair", {}, json.dumps(
        {"code": code, "device_id": "phone-0001"}).encode())

    response = mobile_routes.dispatch(request, service._context, ANONYMOUS)

    assert response.status == 503 and response.body["error"]["code"] == "shutting_down"


# --- Geräte und Koppel-Link ------------------------------------------------------------------------------

def test_devices_can_be_listed_and_revoked(started):
    service, _settings, ctx = started
    a, token_a = mobile_pairing.issue_device("phone-aaaa", "Zeta", utc_now_iso())
    b, token_b = mobile_pairing.issue_device("phone-bbbb", "Alpha", utc_now_iso())
    ctx.devices.save(a)
    ctx.devices.save(b)

    assert [d["name"] for d in service.list_devices()] == ["Alpha", "Zeta"]
    assert service.revoke("phone-aaaa") is True and service.revoke("unbekannt") is False
    port = service.status.port
    revoked, body = http_call(port, "GET", "/v1/ping", token=token_a)
    other, _b = http_call(port, "GET", "/v1/ping", token=token_b)

    assert revoked.status == 401 and body["error"]["code"] == "token_revoked"
    assert other.status == 200


def test_revoke_all_revokes_every_device_and_counts_them(started):
    service, _settings, ctx = started
    tokens = []
    for index in range(3):
        record, token = mobile_pairing.issue_device(f"phone-000{index}", f"P{index}", utc_now_iso())
        ctx.devices.save(record)
        tokens.append(token)

    assert service.revoke_all() == 3
    for token in tokens:
        response, body = http_call(service.status.port, "GET", "/v1/ping", token=token)
        assert response.status == 401 and body["error"]["code"] == "token_revoked"
    assert service.revoke_all() == 3                          # idempotent, zählt die vorhandenen


def test_the_pair_link_carries_address_port_and_the_canonical_code(started):
    service, _settings, _ctx = started
    port = service.status.port

    assert service.pair_link("K7M2-9QXA") == (
        f"https://xveyn.github.io/Zeiterfassung/#pair=127.0.0.1:{port}:K7M29QXA")
    assert service.pair_link("k7m2 9qxa") == service.pair_link("K7M2-9QXA")
    assert service.pair_link("kein code") is None


def test_there_is_no_pair_link_while_the_server_is_not_running(tmp_path):
    service, _settings, _ctx = make_service(tmp_path, enabled=False)
    service.apply()
    assert service.pair_link("K7M2-9QXA") is None


def test_there_is_no_pair_link_for_a_vanished_address(tmp_path):
    # Der Zustand trägt die gewählte Adresse, der Server läuft aber nicht: ein Link
    # (und damit ein QR-Code) auf diese Adresse führte ins Leere.
    service, _settings, _ctx = make_service(tmp_path, address="192.168.77.5",
                                            candidates=(LOOPBACK,))
    service.apply()

    assert service.status.address == "192.168.77.5" and service.status.state == STATE_ERROR
    assert service.pair_link("K7M2-9QXA") is None
