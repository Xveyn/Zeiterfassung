# tests/test_mobile_routes.py
import datetime
import json
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


# --- pair ---------------------------------------------------------------------------------------------

def pair_body(code, device_id=PHONE, name="Pixel von Sven", **extra):
    doc = {"code": code, "device_name": name, "device_id": device_id}
    doc.update(extra)
    return json.dumps(doc).encode()


def pair(env, code, **kwargs):
    return call(env, "POST", "/v1/pair", body=pair_body(code, **kwargs))


def test_the_pair_route_is_the_only_public_one(env):
    surface = mobile_routes.surface(env.ctx)

    assert surface.public == frozenset({("POST", "/v1/pair")})
    assert surface.methods == frozenset({"GET", "POST"})
    assert surface.route_methods("/v1/pair") == frozenset({"POST"})


def test_a_correct_code_pairs_the_device_and_returns_its_token(env):
    code = env.ctx.pairing.open()

    response = pair(env, code)

    assert response.status == 200
    body = response.body
    assert set(body) == {"token", "expires_at", "window_days", "desktop_name", "protocol"}
    assert (body["window_days"], body["desktop_name"], body["protocol"]) == (90, "Desktop", 1)
    assert body["expires_at"] == "2026-11-07T12:00:00Z"
    stored = env.ctx.devices.get(PHONE)
    assert stored["name"] == "Pixel von Sven" and stored["token_hash"] == mobile_pairing.hash_token(body["token"])
    assert isinstance(principal_for(env, body["token"]), MobilePrincipal)
    with open(env.ctx.devices.filepath, encoding="utf-8") as handle:
        assert body["token"] not in handle.read()                  # nur der Hash steht in der Datei


def test_the_code_is_single_use(env):
    code = env.ctx.pairing.open()
    assert pair(env, code).status == 200

    again = pair(env, code, device_id="phone-0002")

    assert again.status == 403 and error_code(again) == "invalid_code"
    assert env.ctx.devices.get("phone-0002") is None


def test_a_wrong_code_and_no_active_code_give_one_shared_answer(env):
    env.ctx.pairing.open()
    wrong = pair(env, "AAAA-AAAA")
    env.ctx.pairing.close()
    nothing_active = pair(env, "AAAA-AAAA")

    assert wrong.status == nothing_active.status == 403
    assert wrong.body == nothing_active.body and error_code(wrong) == "invalid_code"


def test_an_expired_code_gives_the_same_answer(env):
    code = env.ctx.pairing.open()
    env.clock["pairing"] += 300                                  # genau die Gültigkeit

    expired = pair(env, code)

    assert expired.status == 403 and expired.body == pair(env, "AAAA-AAAA").body


def test_five_wrong_codes_lock_the_session_even_for_the_right_one(env):
    code = env.ctx.pairing.open()

    results = [pair(env, "AAAA-AAAA").status for _ in range(5)]
    locked = pair(env, "AAAA-AAAA")
    right_but_locked = pair(env, code)

    assert results == [403] * 5
    assert locked.status == 429 and error_code(locked) == "pairing_locked"
    assert right_but_locked.status == 429
    assert env.ctx.devices.get(PHONE) is None


@pytest.mark.parametrize("device_id", [None, "", "kurz", "a" * 65, "mit leerzeichen!", 5, ["x"], "٢" * 10])
def test_an_invalid_device_id_is_400_without_looking_at_the_code(env, device_id):
    code = env.ctx.pairing.open()
    body = json.dumps({"code": code, "device_name": "P", "device_id": device_id}).encode()

    response = call(env, "POST", "/v1/pair", body=body)
    wrong_code = call(env, "POST", "/v1/pair", body=json.dumps(
        {"code": "AAAA-AAAA", "device_name": "P", "device_id": device_id}).encode())

    assert response.status == 400 and error_code(response) == "invalid_json"
    assert wrong_code.status == 400 and wrong_code.body == response.body      # kein Orakel
    assert pair(env, code).status == 200                                       # Code nicht verbrannt


def test_a_request_with_a_bad_device_id_never_counts_as_a_failed_attempt(env):
    code = env.ctx.pairing.open()
    for _ in range(10):
        call(env, "POST", "/v1/pair", body=json.dumps(
            {"code": "AAAA-AAAA", "device_id": "x"}).encode())

    assert pair(env, code).status == 200


@pytest.mark.parametrize("raw", [
    b"", b"{kaputt", b"[]", b'"x"', b"5", b'{"code": NaN}', b'{"a":1,"a":2}',
    pytest.param(b"[" * 100000, id="deep-nesting"), b"\xff",
])
def test_a_malformed_pair_body_is_400_invalid_json(env, raw):
    env.ctx.pairing.open()

    response = call(env, "POST", "/v1/pair", body=raw)

    assert response.status == 400 and error_code(response) == "invalid_json"


@pytest.mark.parametrize("protocol", [0, 2, "1", 1.0, True, None, [1]])
def test_a_present_but_wrong_protocol_is_400_invalid_protocol(env, protocol):
    code = env.ctx.pairing.open()

    response = pair(env, code, protocol=protocol)

    assert response.status == 400 and error_code(response) == "invalid_protocol"
    assert pair(env, code).status == 200                                       # Code nicht verbrannt


def test_protocol_one_is_accepted(env):
    assert pair(env, env.ctx.pairing.open(), protocol=1).status == 200


@pytest.mark.parametrize("code", [None, 5, "", ["x"], {"a": 1}, "٢" * 8, "A" * 5000])
def test_a_junk_code_is_a_failed_attempt_not_an_error(env, code):
    env.ctx.pairing.open()

    response = call(env, "POST", "/v1/pair", body=json.dumps(
        {"code": code, "device_name": "P", "device_id": PHONE}).encode())

    assert response.status == 403 and error_code(response) == "invalid_code"


def test_a_junk_name_becomes_the_default_name(env):
    code = env.ctx.pairing.open()
    body = json.dumps({"code": code, "device_id": PHONE, "device_name": "Pi\nxel\x00"}).encode()

    assert call(env, "POST", "/v1/pair", body=body).status == 200
    assert env.ctx.devices.get(PHONE)["name"] == "Pixel"


def test_pairing_again_keeps_the_sync_identity_and_lifts_a_revocation(env):
    old, _token = add_device(env, now="2026-10-01T08:00:00Z")
    old["last_pull_at"] = "2026-10-07T09:00:00Z"
    env.ctx.devices.save(mobile_pairing.revoke(old))
    code = env.ctx.pairing.open()

    response = pair(env, code, name="Pixel neu")

    assert response.status == 200
    stored = env.ctx.devices.get(PHONE)
    assert stored["created_at"] == "2026-10-01T08:00:00Z" and stored["last_pull_at"] == "2026-10-07T09:00:00Z"
    assert stored["revoked"] is False and stored["name"] == "Pixel neu"
    assert isinstance(principal_for(env, response.body["token"]), MobilePrincipal)


def test_pairing_is_refused_while_the_app_closes_and_keeps_the_code(env):
    code = env.ctx.pairing.open()
    closing = mobile_routes.MobileContext(**{**env.ctx.__dict__, "closing": lambda: True})

    response = mobile_routes.dispatch(
        ApiRequest("POST", "/v1/pair", {}, pair_body(code)), closing, ANONYMOUS)

    assert response.status == 503 and error_code(response) == "shutting_down"
    assert pair(env, code).status == 200


def test_a_query_string_on_pair_is_rejected(env):
    response = call(env, "POST", "/v1/pair", body=pair_body("AAAA-AAAA"), query={"x": ["1"]})
    assert response.status == 400 and error_code(response) == "unknown_parameter"


# --- sync ----------------------------------------------------------------------------------------------

SLOT = {"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}


def sync_body(env, entries=None, **over):
    doc = {"protocol": 1, "client_time": env.clock["now"], "last_pull_at": "",
           "entries": entries or {}}
    doc.update(over)
    return json.dumps(doc).encode()


def day(modified_at="2026-10-07T18:30:00Z", slots=(SLOT,), deleted=False):
    return {"slots": list(slots), "modified_at": modified_at, "deleted": deleted}


def sync(env, token, entries=None, **over):
    return call(env, "POST", "/v1/sync", body=sync_body(env, entries, **over), token=token)


def test_a_sync_applies_the_days_and_renews_the_token(env):
    record, token = add_device(env)

    response = sync(env, token, {"2026-10-07": day()})

    assert response.status == 200
    body = response.body
    assert body["protocol"] == 1 and body["server_time"] == NOW and body["last_pull_at"] == NOW
    assert body["entries"]["2026-10-07"]["device_id"] == PHONE
    assert env.ctx.storage.get_all_raw()["2026-10-07"]["device_id"] == PHONE
    assert body["token"] != token and body["expires_at"] == "2026-11-07T12:00:00Z"
    stored = env.ctx.devices.get(PHONE)
    assert stored["token_hash"] == mobile_pairing.hash_token(body["token"])
    assert stored["last_pull_at"] == NOW and stored["last_seen"] == NOW
    assert env.changes == [1]


def test_the_old_token_works_for_ten_minutes_after_the_renewal_and_the_new_one_always(env):
    _record, old = add_device(env)
    new = sync(env, old).body["token"]

    env.clock["now"] = "2026-10-08T12:10:00Z"
    inside = principal_for(env, old)
    env.clock["now"] = "2026-10-08T12:10:01Z"

    assert isinstance(inside, MobilePrincipal) and inside.via_previous is True
    assert principal_for(env, old) is None
    assert isinstance(principal_for(env, new), MobilePrincipal)


def test_a_lost_answer_twice_does_not_lock_the_phone_out(env):
    _record, t1 = add_device(env)
    sync(env, t1)                                            # Antwort mit t2 geht verloren
    env.clock["now"] = "2026-10-08T12:05:00Z"

    second = sync(env, t1)                                   # Handy sendet weiter mit t1
    t3 = second.body["token"]                                # auch diese Antwort geht verloren
    env.clock["now"] = "2026-10-08T12:06:00Z"

    assert second.status == 200
    assert isinstance(principal_for(env, t1), MobilePrincipal)      # t1 gilt noch
    assert isinstance(principal_for(env, t3), MobilePrincipal)


def test_a_rejected_sync_neither_renews_the_token_nor_moves_last_pull_at(env):
    record, token = add_device(env)
    before = env.ctx.devices.get(PHONE)

    bad_json = call(env, "POST", "/v1/sync", body=b"{kaputt", token=token)
    skew = sync(env, token, client_time="2026-10-08T13:00:00Z")
    invalid = sync(env, token, {"2026-10-07": day(slots=())})

    assert (bad_json.status, skew.status, invalid.status) == (400, 409, 422)
    assert error_code(skew) == "clock_skew" and error_code(invalid) == "invalid_entry"
    assert env.ctx.devices.get(PHONE) == before
    assert env.ctx.storage.get_all_raw() == {} and env.changes == []


def test_a_busy_sync_guard_is_503_and_keeps_the_token(env):
    _record, token = add_device(env)
    before = env.ctx.devices.get(PHONE)
    guard = threading.Lock()
    guard.acquire()
    busy = mobile_routes.MobileContext(**{**env.ctx.__dict__, "sync_guard": guard})

    response = mobile_routes.dispatch(
        ApiRequest("POST", "/v1/sync", {}, sync_body(env)), busy, principal_for(env, token))

    assert response.status == 503 and error_code(response) == "busy"
    assert env.ctx.devices.get(PHONE) == before


def test_a_device_revoked_between_the_check_and_the_handler_is_refused(env):
    record, token = add_device(env)
    principal = principal_for(env, token)                      # der Prüfer war schon durch
    env.ctx.devices.save(mobile_pairing.revoke(record))

    response = call(env, "POST", "/v1/sync", body=sync_body(env, {"2026-10-07": day()}),
                    principal=principal)

    assert response.status == 401 and error_code(response) == "token_revoked"
    assert env.ctx.storage.get_all_raw() == {}


def test_a_sync_is_refused_while_the_app_closes(env):
    _record, token = add_device(env)
    closing = mobile_routes.MobileContext(**{**env.ctx.__dict__, "closing": lambda: True})

    response = mobile_routes.dispatch(
        ApiRequest("POST", "/v1/sync", {}, sync_body(env)), closing, principal_for(env, token))

    assert response.status == 503 and error_code(response) == "shutting_down"
    assert env.ctx.storage.get_all_raw() == {}


def test_last_pull_at_is_saved_with_the_apply_so_a_repeated_first_sync_adds_no_conflict(env):
    # Vertrag aus #254. Erstabgleich: der Desktop kennt den Tag anders.
    env.ctx.storage.apply_merge({"2026-10-07": {
        "slots": [{"start": "09:00", "end": "13:00", "pause": 0, "kategorie": ""}],
        "modified_at": "2026-10-07T20:00:00Z", "device_id": "DESK", "deleted": False}})
    _record, token = add_device(env)
    entries = {"2026-10-07": day(modified_at="2026-10-07T18:30:00Z")}

    first = sync(env, token, entries)
    assert env.ctx.devices.get(PHONE)["last_pull_at"] == NOW
    again = sync(env, token, entries)                          # Antwort ging verloren, gleicher Request

    assert first.status == again.status == 200
    assert len(env.ctx.conflicts_store.get_all()) == 1


def test_a_failing_on_change_does_not_turn_a_saved_sync_into_a_500(env, caplog):
    _record, token = add_device(env)

    def boom():
        raise RuntimeError("UI weg")
    failing = mobile_routes.MobileContext(**{**env.ctx.__dict__, "on_change": boom})

    response = mobile_routes.dispatch(
        ApiRequest("POST", "/v1/sync", {}, sync_body(env, {"2026-10-07": day()})), failing,
        principal_for(env, token))

    assert response.status == 200 and "2026-10-07" in env.ctx.storage.get_all_raw()


def test_syncing_does_not_touch_other_devices(env):
    _a, token_a = add_device(env, "phone-aaaa", "A")
    b, _token_b = add_device(env, "phone-bbbb", "B")

    sync(env, token_a, {"2026-10-07": day()})

    assert env.ctx.devices.get("phone-bbbb") == b


def test_the_response_contains_the_new_token_but_neither_the_old_one_nor_any_hash(env):
    record, token = add_device(env)

    body = sync(env, token, {"2026-10-07": day()}).body
    text = json.dumps(body)

    assert body["token"] in text and token not in text
    assert record["token_hash"] not in text and mobile_pairing.hash_token(body["token"]) not in text


def test_two_concurrent_syncs_of_one_device_never_lose_a_renewal(env):
    _record, token = add_device(env)
    principal = principal_for(env, token)
    results = []

    def run():
        results.append(call(env, "POST", "/v1/sync", body=sync_body(env), principal=principal))

    threads = [threading.Thread(target=run) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    tokens = [r.body["token"] for r in results]
    hashes = {mobile_pairing.hash_token(t) for t in tokens}
    stored = env.ctx.devices.get(PHONE)
    assert all(r.status == 200 for r in results) and len(set(tokens)) == 8
    # Die Abgleiche laufen nacheinander durch den Lock: gespeichert ist das Token des
    # zuletzt fertigen. Alle acht kamen mit dem Ausgangstoken, dessen Antworten (T1 …)
    # nie ausgeliefert sein müssen — also bleibt der Ausgangstoken das vorherige.
    assert stored["token_hash"] in hashes
    assert stored["previous_token_hash"] == mobile_pairing.hash_token(token)



def test_the_route_table_has_exactly_the_four_routes(env):
    assert mobile_routes.methods_for_path("/v1/pair") == frozenset({"POST"})
    assert mobile_routes.methods_for_path("/v1/ping") == frozenset({"GET"})
    assert mobile_routes.methods_for_path("/v1/categories") == frozenset({"GET"})
    assert mobile_routes.methods_for_path("/v1/sync") == frozenset({"POST"})
    assert mobile_routes.methods_for_path("/v1/entries") == frozenset()
    assert mobile_routes.routed_methods() == frozenset({"GET", "POST"})
    assert mobile_routes.surface(env.ctx).public == frozenset({("POST", "/v1/pair")})


def test_a_request_verified_before_a_concurrent_renewal_still_keeps_the_old_token_alive(env):
    # Zwei Anfragen mit T0 werden geprüft, bevor die erste speichert (Client-Timeout,
    # Wiederholung). Die zweite sieht beim Prüfen "aktuell", ist beim Speichern aber das
    # vorherige Token — und darf das noch nie ausgelieferte T1 nicht verdrängen.
    _record, t0 = add_device(env)
    first, second = principal_for(env, t0), principal_for(env, t0)
    assert not first.via_previous and not second.via_previous

    call(env, "POST", "/v1/sync", body=sync_body(env), principal=first)      # Antwort geht verloren
    call(env, "POST", "/v1/sync", body=sync_body(env), principal=second)     # Antwort geht verloren

    assert isinstance(principal_for(env, t0), MobilePrincipal)               # T0 gilt noch


def test_a_request_whose_token_was_replaced_by_a_new_pairing_is_refused(env):
    record, token = add_device(env)
    stale = principal_for(env, token)
    env.ctx.pairing.open()
    fresh, _new_token = mobile_pairing.issue_device(PHONE, "Pixel neu", NOW, record)
    env.ctx.devices.save(fresh)                                  # erneut gekoppelt: neues Token

    response = call(env, "POST", "/v1/sync", body=sync_body(env, {"2026-10-07": day()}),
                    principal=stale)

    assert response.status == 401 and error_code(response) == "unauthorized"
    assert env.ctx.storage.get_all_raw() == {}
    assert env.ctx.devices.get(PHONE)["previous_token_hash"] == ""     # nichts in die Karenz geschoben


def test_a_request_whose_token_expired_before_the_handler_ran_is_refused(env):
    _record, token = add_device(env)
    principal = principal_for(env, token)
    env.clock["now"] = "2026-11-07T12:00:00Z"                    # genau expires_at

    response = call(env, "POST", "/v1/sync", body=sync_body(env, {"2026-10-07": day()}),
                    principal=principal)

    assert response.status == 401 and error_code(response) == "token_expired"
    assert env.ctx.storage.get_all_raw() == {}
