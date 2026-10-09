# tests/test_mobile_routes.py
import datetime
import threading
import types

import pytest

from src import mobile_pairing, mobile_routes
from src.api_auth import ANONYMOUS, SCOPE_LOCAL, SCOPE_MOBILE, Denied, Principal
from src.api_routes import ApiRequest
from src.conflicts_store import ConflictsStore
from src.mobile_pairing import PairingSession
from src.mobile_routes import MobilePrincipal
from src.mobile_store import MobileStore
from src.settings import Settings
from src.storage import Storage

NOW = "2026-10-08T12:00:00Z"
TODAY = datetime.date(2026, 10, 8)
PHONE = "phone-0001"


def make_env(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    settings.device_id_for_sync = "DESK"
    clock = {"now": NOW, "pairing": 1000.0}
    changes = []
    ctx = mobile_routes.MobileContext(
        pairing=PairingSession(lambda: clock["pairing"]),
        devices=MobileStore(str(tmp_path / "mobile_devices.json")),
        devices_lock=threading.RLock(),
        storage=Storage(str(tmp_path / "zeiterfassung.json"), device_id="DESK"),
        settings=settings,
        conflicts_store=ConflictsStore(str(tmp_path / "conflicts.json")),
        base=str(tmp_path),
        desktop_name=lambda: "Desktop",
        now=lambda: clock["now"],
        today=lambda: TODAY,
        on_change=lambda: changes.append(1))
    return types.SimpleNamespace(ctx=ctx, clock=clock, changes=changes)


@pytest.fixture
def env(tmp_path):
    return make_env(tmp_path)


def add_device(env, device_id=PHONE, name="Pixel", now=NOW):
    record, token = mobile_pairing.issue_device(device_id, name, now)
    env.ctx.devices.save(record)
    return record, token


def principal_for(env, token):
    return mobile_routes.make_verifier(env.ctx.devices, env.ctx.now)(token)


def call(env, method, path, *, body=b"", query=None, token=None, principal=None):
    if principal is None:
        principal = ANONYMOUS if token is None else principal_for(env, token)
    request = ApiRequest(method, path, query or {}, body)
    return mobile_routes.dispatch(request, env.ctx, principal)


def error_code(response):
    return response.body["error"]["code"]


# --- Prüfer ---------------------------------------------------------------------------------------

def test_a_valid_token_yields_a_mobile_principal_with_the_record(env):
    record, token = add_device(env)

    principal = principal_for(env, token)

    assert isinstance(principal, MobilePrincipal)
    assert principal.name == PHONE and principal.scopes == frozenset({SCOPE_MOBILE})
    assert principal.record["id"] == PHONE and principal.via_previous is False


def test_the_previous_token_is_flagged_as_such(env):
    record, token = add_device(env)
    renewed, _new = mobile_pairing.renew(record, NOW)
    env.ctx.devices.save(renewed)

    principal = principal_for(env, token)

    assert isinstance(principal, MobilePrincipal) and principal.via_previous is True


def test_an_expired_token_is_denied_as_expired(env):
    _record, token = add_device(env)
    env.clock["now"] = "2026-11-07T12:00:00Z"                 # genau expires_at

    assert principal_for(env, token) == Denied("token_expired")


def test_a_revoked_token_is_denied_as_revoked(env):
    record, token = add_device(env)
    env.ctx.devices.save(mobile_pairing.revoke(record))

    assert principal_for(env, token) == Denied("token_revoked")


@pytest.mark.parametrize("junk", ["", "x" * 43, "x" * 5000, "\ud800", "a b"])
def test_an_unknown_token_is_not_recognised(env, junk):
    add_device(env)
    assert principal_for(env, junk) is None


# --- Routing ----------------------------------------------------------------------------------------

def test_the_route_table_knows_only_its_own_routes():
    assert mobile_routes.methods_for_path("/v1/ping") == frozenset({"GET"})
    assert mobile_routes.methods_for_path("/v1/categories") == frozenset({"GET"})
    assert mobile_routes.methods_for_path("/v1/entries") == frozenset()      # nichts von der lokalen API
    assert mobile_routes.methods_for_path("/v1/status") == frozenset()
    assert mobile_routes.routed_methods() == frozenset({"GET"})


def test_the_surface_enables_cors_and_has_no_public_route_yet(env):
    surface = mobile_routes.surface(env.ctx)

    assert surface.public == frozenset()
    assert surface.cors is True and surface.methods == frozenset({"GET"})
    assert surface.route_methods("/v1/ping") == frozenset({"GET"})


def test_an_unknown_path_is_404(env):
    _record, token = add_device(env)
    for path in ("/v1/entries", "/v1/status", "/v1/ping/", "/v1/PING", "/"):
        assert call(env, "GET", path, token=token).status == 404


def test_a_wrong_method_is_405_with_allow(env):
    _record, token = add_device(env)

    response = call(env, "POST", "/v1/ping", token=token)

    assert response.status == 405 and response.headers["Allow"] == "GET"
    assert call(env, "POST", "/v1/categories", token=token).headers["Allow"] == "GET"


def test_query_parameters_are_rejected(env):
    _record, token = add_device(env)
    for path in ("/v1/ping", "/v1/categories"):
        response = call(env, "GET", path, token=token, query={"x": ["1"]})
        assert response.status == 400 and error_code(response) == "unknown_parameter"


def test_a_principal_without_the_mobile_scope_is_refused(env):
    local = Principal("local", frozenset({SCOPE_LOCAL}))

    assert call(env, "GET", "/v1/ping", principal=local).status == 403
    anonymous = call(env, "GET", "/v1/ping")
    assert anonymous.status == 403 and error_code(anonymous) == "insufficient_scope"


# --- ping und categories -------------------------------------------------------------------------

def test_ping_reports_protocol_time_and_window(env):
    _record, token = add_device(env)

    response = call(env, "GET", "/v1/ping", token=token)

    assert response.status == 200
    assert response.body == {"protocol": 1, "server_time": NOW, "window_days": 90}


def test_categories_are_the_configured_names_without_blanks_and_duplicates(env):
    _record, token = add_device(env)
    env.ctx.settings.set("categories", ["Projekt", "", "Projekt", "Intern"])

    response = call(env, "GET", "/v1/categories", token=token)

    assert response.status == 200 and response.body == {"categories": ["Projekt", "Intern"]}
