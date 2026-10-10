# tests/test_mobile_routes.py
import base64
import dataclasses
import datetime
import json
import logging
import threading
import time
import types

import pytest

from src import mobile_crypto as mc
from src import mobile_keys, mobile_pairing, mobile_routes
from src.api_auth import ANONYMOUS, SCOPE_LOCAL, SCOPE_MOBILE, Denied, Principal
from src.api_routes import ApiRequest
from src.conflicts_store import ConflictsStore
from src.mobile_keys import MobileKeyStore
from src.mobile_pairing import PairingSession
from src.mobile_routes import MobilePrincipal
from src.mobile_store import MobileStore
from src.settings import Settings
from src.storage import Storage
from tests.mobile_phone import SYNC_BODY, FakeRing, Phone

NOW = "2026-10-08T12:00:00Z"
TODAY = datetime.date(2026, 10, 8)
PHONE = "phone-0001"
DEVICE_KEY = bytes(range(32))


def make_env(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    settings.device_id_for_sync = "DESK"
    clock = {"now": NOW, "pairing": 1000.0}
    changes = []
    keys_path = tmp_path / "mobile_keys.json"
    ctx = mobile_routes.MobileContext(
        pairing=PairingSession(lambda: clock["pairing"]),
        devices=MobileStore(str(tmp_path / "mobile_devices.json")),
        devices_lock=threading.RLock(),
        keys=MobileKeyStore(str(keys_path)),
        storage=Storage(str(tmp_path / "zeiterfassung.json"), device_id="DESK"),
        settings=settings,
        conflicts_store=ConflictsStore(str(tmp_path / "conflicts.json")),
        base=str(tmp_path),
        desktop_name=lambda: "Desktop",
        now=lambda: clock["now"],
        today=lambda: TODAY,
        on_change=lambda: changes.append(1))
    return types.SimpleNamespace(ctx=ctx, clock=clock, changes=changes, phones={}, keys_path=keys_path,
                                 ring=None)


@pytest.fixture
def env(tmp_path, monkeypatch):
    environment = make_env(tmp_path)
    environment.ring = FakeRing()
    monkeypatch.setattr(mobile_keys, "keyring_store", environment.ring)
    return environment


def add_device(env, device_id=PHONE, name="Pixel", now=NOW, with_key=True):
    """Ein gekoppeltes Handy samt Schlüssel (Standard) — liefert wie bisher (Datensatz, Token)."""
    record, token = mobile_pairing.issue_device(device_id, name, now)
    env.ctx.devices.save(record)
    phone = Phone(device_id, name)
    phone.token = token
    if with_key:
        phone.key = DEVICE_KEY
        env.ctx.keys.put(device_id, DEVICE_KEY)
    env.phones[device_id] = phone
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


def is_sealed(body):
    return isinstance(body, dict) and set(body) == {"v", "seq", "n", "c"}


def opened(env, response, device=PHONE):
    """Die Antwort wie die PWA sieht: ein Umschlag wird mit dem Geräteschlüssel geöffnet (Erfolg
    **und** Fehler nach dem Entschlüsseln), alles andere bleibt Klartext."""
    body = response.body
    if is_sealed(body):
        body = env.phones[device].open_sync_response(body)
    return types.SimpleNamespace(status=response.status, body=body, headers=response.headers,
                                 raw=response.body)


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
    for path in ("/v1/entries", "/v1/status", "/v1/categories", "/v1/ping/", "/v1/PING", "/"):
        assert call(env, "GET", path, token=token).status == 404


def test_a_wrong_method_is_405_with_allow(env):
    _record, token = add_device(env)

    response = call(env, "POST", "/v1/ping", token=token)

    assert response.status == 405 and response.headers["Allow"] == "GET"


def test_query_parameters_are_rejected(env):
    _record, token = add_device(env)
    response = call(env, "GET", "/v1/ping", token=token, query={"x": ["1"]})
    assert response.status == 400 and error_code(response) == "unknown_parameter"


def test_a_principal_without_the_mobile_scope_is_refused(env):
    local = Principal("local", frozenset({SCOPE_LOCAL}))

    assert call(env, "GET", "/v1/ping", principal=local).status == 403
    anonymous = call(env, "GET", "/v1/ping")
    assert anonymous.status == 403 and error_code(anonymous) == "insufficient_scope"


# --- ping ---------------------------------------------------------------------------------------------

def test_ping_stays_plaintext_and_reports_protocol_time_and_window(env):
    _record, token = add_device(env)

    response = call(env, "GET", "/v1/ping", token=token)

    assert response.status == 200
    assert response.body == {"protocol": 2, "server_time": NOW, "window_days": 90}


def test_the_categories_route_is_gone(env):
    _record, token = add_device(env)
    assert call(env, "GET", "/v1/categories", token=token).status == 404
    env.ctx.settings.set("categories", ["Kunde Geheim"])
    assert "Kunde Geheim" not in json.dumps(call(env, "GET", "/v1/ping", token=token).body)


# --- pair ---------------------------------------------------------------------------------------------

def pair_envelope(code, **kwargs):
    return Phone().pair_request(code, **kwargs)


def pair(env, code, phone=None, **kwargs):
    """Koppelt über einen Umschlag; bei Erfolg wird die Antwort mit dem Code geöffnet."""
    phone = phone or Phone(kwargs.pop("device_id", PHONE))
    kwargs.setdefault("device_id", phone.device_id)
    response = call(env, "POST", "/v1/pair", body=json.dumps(phone.pair_request(code, **kwargs)).encode())
    body = response.body
    if response.status == 200:
        body = phone.open_pair_response(code, response.body)
    return types.SimpleNamespace(status=response.status, body=body, raw=response.body, phone=phone)


def new_code(env):
    return mobile_pairing.normalize_code(env.ctx.pairing.open())


def test_the_pair_route_is_the_only_public_one(env):
    surface = mobile_routes.surface(env.ctx)

    assert surface.public == frozenset({("POST", "/v1/pair")})
    assert surface.methods == frozenset({"GET", "POST"})
    assert surface.route_methods("/v1/pair") == frozenset({"POST"})


def test_a_correct_code_pairs_the_device_and_returns_token_and_key_only_inside_the_envelope(env):
    code = new_code(env)

    response = pair(env, code, name="Pixel von Sven")

    assert response.status == 200 and is_sealed(response.raw)               # nichts im Klartext
    raw = json.dumps(response.raw)
    body = response.body
    assert set(body) == {"token", "expires_at", "window_days", "desktop_name", "protocol", "key"}
    assert (body["window_days"], body["desktop_name"], body["protocol"]) == (90, "Desktop", 2)
    assert body["token"] not in raw and body["key"] not in raw and "Desktop" not in raw
    assert body["expires_at"] == "2026-11-07T12:00:00Z"
    stored = env.ctx.devices.get(PHONE)
    assert stored["name"] == "Pixel von Sven" and stored["token_hash"] == mobile_pairing.hash_token(body["token"])
    assert stored["last_seq"] == 0
    assert env.ctx.keys.get(PHONE) == response.phone.key and len(response.phone.key) == 32
    assert isinstance(principal_for(env, body["token"]), MobilePrincipal)
    with open(env.ctx.devices.filepath, encoding="utf-8") as handle:
        assert body["token"] not in handle.read()                  # nur der Hash steht in der Datei


def test_the_pairing_key_is_random_per_pairing(env):
    keys = set()
    for index in range(3):
        code = new_code(env)
        keys.add(pair(env, code, device_id=f"phone-000{index}").phone.key)
    assert len(keys) == 3


def test_a_plaintext_pair_request_is_refused_and_does_not_burn_the_code(env):
    code = new_code(env)
    body = json.dumps({"protocol": 2, "code": code, "device_id": PHONE, "device_name": "x"}).encode()

    response = call(env, "POST", "/v1/pair", body=body)

    assert (response.status, error_code(response)) == (400, "invalid_protocol")
    assert env.ctx.pairing.is_active()
    assert pair(env, code).status == 200


def test_the_code_is_single_use(env):
    code = new_code(env)
    assert pair(env, code).status == 200

    again = pair(env, code, device_id="phone-0002")

    assert again.status == 403 and error_code(again) == "invalid_code"
    assert env.ctx.devices.get("phone-0002") is None and env.ctx.keys.get("phone-0002") is None


def test_a_wrong_code_and_no_active_code_give_one_shared_answer(env):
    env.ctx.pairing.open()
    wrong = pair(env, mobile_pairing.generate_code())
    env.ctx.pairing.close()
    nothing_active = pair(env, mobile_pairing.generate_code())

    assert wrong.status == nothing_active.status == 403
    assert wrong.body == nothing_active.body and error_code(wrong) == "invalid_code"
    assert env.ctx.devices.get_all() == [] and env.ctx.keys.get(PHONE) is None


def test_an_expired_code_gives_the_same_answer(env):
    code = new_code(env)
    env.clock["pairing"] += 300                                  # genau die Gültigkeit

    expired = pair(env, code)

    assert expired.status == 403 and expired.body == pair(env, mobile_pairing.generate_code()).body


def test_five_wrong_codes_lock_the_session_even_for_the_right_one(env):
    code = new_code(env)

    results = [pair(env, mobile_pairing.generate_code()).status for _ in range(5)]
    locked = pair(env, mobile_pairing.generate_code())
    right_but_locked = pair(env, code)

    assert results == [403] * 5
    assert locked.status == 429 and error_code(locked) == "pairing_locked"
    assert right_but_locked.status == 429
    assert env.ctx.devices.get(PHONE) is None


@pytest.mark.parametrize("device_id", [None, "", "kurz", "a" * 65, "mit leerzeichen!", 5, ["x"], "٢" * 10])
def test_an_invalid_device_id_inside_the_envelope_is_a_failed_attempt_and_keeps_the_code(env, device_id):
    code = new_code(env)
    request_key, _ = mc.pair_keys(code)
    plain = json.dumps({"protocol": 2, "device_name": "P", "device_id": device_id}).encode()
    envelope = mc.seal(request_key, direction="req", method="POST", path="/v1/pair", device_id="-",
                       seq=1, plaintext=plain)

    response = call(env, "POST", "/v1/pair", body=json.dumps(envelope).encode())

    assert (response.status, error_code(response)) == (403, "invalid_code")
    assert env.ctx.pairing.is_active()                                       # Code nicht verbrannt
    assert pair(env, code).status == 200


def test_a_wrong_protocol_inside_the_envelope_is_a_failed_attempt(env):
    for protocol in (0, 1, 3, "2", 2.0, True, None, [2]):
        code = new_code(env)                                                  # frischer Code, Sperre aufgehoben
        response = pair(env, code, protocol=protocol)
        assert (response.status, error_code(response)) == (403, "invalid_code"), protocol
        assert env.ctx.pairing.is_active()                                    # nicht verbrannt


@pytest.mark.parametrize("raw", [
    b"", b"{kaputt", b"[]", b'"x"', b"5", b'{"a":1,"a":2}', pytest.param(b"[" * 100000, id="deep-nesting"),
    b"\xff",
])
def test_a_malformed_pair_body_is_400_invalid_json(env, raw):
    env.ctx.pairing.open()

    response = call(env, "POST", "/v1/pair", body=raw)

    assert response.status == 400 and error_code(response) == "invalid_json"


@pytest.mark.parametrize("envelope", [
    {}, {"v": 2}, {"v": 1, "seq": 1, "n": "A" * 16, "c": "A" * 40},
    {"v": 2, "seq": 1, "n": "x", "c": "y"}, {"v": 2, "seq": 0, "n": "A" * 16, "c": "A" * 40},
    {"v": 2, "seq": 1, "n": "A" * 16, "c": "A" * 40, "extra": 1},
])
def test_a_malformed_envelope_never_pairs_and_never_crashes(env, envelope):
    env.ctx.pairing.open()

    response = call(env, "POST", "/v1/pair", body=json.dumps(envelope).encode())

    assert response.status in (400, 403) and env.ctx.devices.get_all() == []


def test_a_junk_name_becomes_the_default_name(env):
    code = new_code(env)

    assert pair(env, code, name="Pi\nxel\x00").status == 200
    assert env.ctx.devices.get(PHONE)["name"] == "Pixel"


def test_pairing_again_keeps_the_sync_identity_creates_a_new_key_and_resets_the_counter(env):
    old, _token = add_device(env, now="2026-10-01T08:00:00Z")
    old["last_pull_at"] = "2026-10-07T09:00:00Z"
    env.ctx.devices.save(mobile_pairing.with_seq(mobile_pairing.revoke(old), 9))
    code = new_code(env)

    response = pair(env, code, name="Pixel neu")

    assert response.status == 200
    stored = env.ctx.devices.get(PHONE)
    assert stored["created_at"] == "2026-10-01T08:00:00Z" and stored["last_pull_at"] == "2026-10-07T09:00:00Z"
    assert stored["revoked"] is False and stored["name"] == "Pixel neu" and stored["last_seq"] == 0
    assert env.ctx.keys.get(PHONE) == response.phone.key != DEVICE_KEY
    assert isinstance(principal_for(env, response.body["token"]), MobilePrincipal)


def test_pairing_is_refused_while_the_app_closes_and_keeps_the_code(env):
    code = new_code(env)
    closing = dataclasses.replace(env.ctx, closing=lambda: True)

    response = mobile_routes.dispatch(
        ApiRequest("POST", "/v1/pair", {}, json.dumps(pair_envelope(code)).encode()), closing, ANONYMOUS)

    assert response.status == 503 and error_code(response) == "shutting_down"
    assert pair(env, code).status == 200


def test_a_query_string_on_pair_is_rejected(env):
    response = call(env, "POST", "/v1/pair", body=json.dumps(pair_envelope(mobile_pairing.generate_code())).encode(),
                    query={"x": ["1"]})
    assert response.status == 400 and error_code(response) == "unknown_parameter"


def test_on_paired_runs_after_the_pairing_with_key_and_record_in_place(env):
    seen = []
    env.ctx = dataclasses.replace(
        env.ctx, on_paired=lambda: seen.append((env.ctx.keys.get(PHONE) is not None,
                                                env.ctx.devices.get(PHONE) is not None)))
    assert pair(env, new_code(env)).status == 200
    assert seen == [(True, True)]


def test_a_failing_on_paired_does_not_fail_the_pairing(env):
    def boom():
        raise RuntimeError("x")
    env.ctx = dataclasses.replace(env.ctx, on_paired=boom)
    assert pair(env, new_code(env)).status == 200


# --- sync ----------------------------------------------------------------------------------------------

SLOT = {"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}


def sync_doc(env, entries=None, **over):
    doc = {"protocol": 2, "client_time": env.clock["now"], "last_pull_at": "", "entries": entries or {}}
    doc.update(over)
    return doc


def sync_body(env, entries=None, device=PHONE, seq=None, **over):
    """Der Body eines Abgleichs als Umschlag (jeder Aufruf zählt den Zähler des Handys hoch)."""
    return json.dumps(env.phones[device].sync_request(sync_doc(env, entries, **over), seq=seq)).encode()


def day(modified_at="2026-10-07T18:30:00Z", slots=(SLOT,), deleted=False):
    return {"slots": list(slots), "modified_at": modified_at, "deleted": deleted}


def sync(env, token, entries=None, device=PHONE, seq=None, **over):
    body = sync_body(env, entries, device=device, seq=seq, **over)
    return opened(env, call(env, "POST", "/v1/sync", body=body, token=token), device)


def unchanged_but_seq(record):
    return {k: v for k, v in record.items() if k != "last_seq"}


def test_a_sync_applies_the_days_and_renews_the_token_inside_the_envelope(env):
    record, token = add_device(env)
    body = sync_body(env, {"2026-10-07": day()})
    raw = call(env, "POST", "/v1/sync", body=body, token=token)

    assert raw.status == 200 and is_sealed(raw.body)
    assert token not in json.dumps(raw.body)
    response = opened(env, raw)
    body = response.body
    assert body["protocol"] == 2 and body["server_time"] == NOW and body["last_pull_at"] == NOW
    assert body["entries"]["2026-10-07"]["device_id"] == PHONE
    assert env.ctx.storage.get_all_raw()["2026-10-07"]["device_id"] == PHONE
    assert body["token"] != token and body["expires_at"] == "2026-11-07T12:00:00Z"
    stored = env.ctx.devices.get(PHONE)
    assert stored["token_hash"] == mobile_pairing.hash_token(body["token"])
    assert stored["last_pull_at"] == NOW and stored["last_seen"] == NOW and stored["last_seq"] == 1
    assert env.changes == [1]


def test_a_plaintext_sync_body_is_refused(env):
    _record, token = add_device(env)
    response = call(env, "POST", "/v1/sync", body=json.dumps(SYNC_BODY).encode(), token=token)
    assert (response.status, error_code(response)) == (400, "invalid_protocol")
    assert env.ctx.storage.get_all_raw() == {}


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

    second = sync(env, t1)                                   # Handy sendet weiter mit t1 (höherer Zähler)
    t3 = second.body["token"]                                # auch diese Antwort geht verloren
    env.clock["now"] = "2026-10-08T12:06:00Z"

    assert second.status == 200
    assert isinstance(principal_for(env, t1), MobilePrincipal)      # t1 gilt noch
    assert isinstance(principal_for(env, t3), MobilePrincipal)


def test_a_rejected_sync_neither_renews_the_token_nor_moves_last_pull_at_but_stores_the_counter(env):
    record, token = add_device(env)
    before = env.ctx.devices.get(PHONE)

    bad_json = call(env, "POST", "/v1/sync", body=b"{kaputt", token=token)
    skew = sync(env, token, client_time="2026-10-08T13:00:00Z")
    invalid = sync(env, token, {"2026-10-07": day(slots=())})

    assert (bad_json.status, skew.status, invalid.status) == (400, 409, 422)
    assert error_code(skew) == "clock_skew" and error_code(invalid) == "invalid_entry"
    after = env.ctx.devices.get(PHONE)
    assert unchanged_but_seq(after) == unchanged_but_seq(before)             # Token, last_pull_at, last_seen
    assert after["last_seq"] == 2                                            # beide entschlüsselten Pakete gezählt
    assert env.ctx.storage.get_all_raw() == {} and env.changes == []


def test_a_busy_sync_guard_is_503_sealed_and_keeps_the_token(env):
    _record, token = add_device(env)
    before = env.ctx.devices.get(PHONE)
    guard = threading.Lock()
    guard.acquire()
    busy = dataclasses.replace(env.ctx, sync_guard=guard)

    raw = mobile_routes.dispatch(
        ApiRequest("POST", "/v1/sync", {}, sync_body(env)), busy, principal_for(env, token))
    response = opened(env, raw)

    assert is_sealed(raw.body) and response.status == 503 and error_code(response) == "busy"
    assert unchanged_but_seq(env.ctx.devices.get(PHONE)) == unchanged_but_seq(before)


def test_a_device_revoked_between_the_check_and_the_handler_is_refused(env):
    record, token = add_device(env)
    principal = principal_for(env, token)                      # der Prüfer war schon durch
    env.ctx.devices.save(mobile_pairing.revoke(record))

    response = call(env, "POST", "/v1/sync", body=sync_body(env, {"2026-10-07": day()}), principal=principal)

    assert response.status == 401 and error_code(response) == "token_revoked"
    assert env.ctx.storage.get_all_raw() == {}


def test_a_sync_is_refused_while_the_app_closes(env):
    _record, token = add_device(env)
    closing = dataclasses.replace(env.ctx, closing=lambda: True)

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
    again = sync(env, token, entries)                          # Antwort ging verloren, gleicher Inhalt, neuer Zähler

    assert first.status == again.status == 200
    assert len(env.ctx.conflicts_store.get_all()) == 1


def test_a_failing_on_change_does_not_turn_a_saved_sync_into_a_500(env):
    _record, token = add_device(env)

    def boom():
        raise RuntimeError("UI weg")
    failing = dataclasses.replace(env.ctx, on_change=boom)

    response = mobile_routes.dispatch(
        ApiRequest("POST", "/v1/sync", {}, sync_body(env, {"2026-10-07": day()})), failing,
        principal_for(env, token))

    assert response.status == 200 and "2026-10-07" in env.ctx.storage.get_all_raw()


def test_syncing_does_not_touch_other_devices(env):
    _a, token_a = add_device(env, "phone-aaaa", "A")
    b, _token_b = add_device(env, "phone-bbbb", "B")

    sync(env, token_a, {"2026-10-07": day()}, device="phone-aaaa")

    assert env.ctx.devices.get("phone-bbbb") == b


def test_the_raw_response_contains_neither_the_new_nor_the_old_token_nor_any_content(env):
    record, token = add_device(env)
    env.ctx.settings.set("categories", ["Kunde Geheim"])

    raw = call(env, "POST", "/v1/sync", body=sync_body(env, {"2026-10-07": day()}), token=token)
    new = opened(env, raw).body["token"]
    text = json.dumps(raw.body)

    assert set(raw.body) == {"v", "seq", "n", "c"}
    for secret in (new, token, record["token_hash"], mobile_pairing.hash_token(new), "2026-10-07", "Projekt",
                   "Kunde Geheim", "entries", "categories"):
        assert secret not in text


def test_concurrent_syncs_of_one_device_never_lose_a_renewal_and_never_apply_a_stale_counter(env):
    _record, token = add_device(env)
    principal = principal_for(env, token)
    bodies = [sync_body(env) for _ in range(8)]                              # Zähler 1 … 8
    results = []

    def run(body):
        results.append(call(env, "POST", "/v1/sync", body=body, principal=principal))

    threads = [threading.Thread(target=run, args=(body,)) for body in bodies]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    statuses = sorted({r.status for r in results})
    assert set(statuses) <= {200, 409} and 200 in statuses                     # nur steigende Zähler kommen durch
    stored = env.ctx.devices.get(PHONE)
    accepted = [r for r in results if r.status == 200]
    hashes = set()
    phone = env.phones[PHONE]
    for response in accepted:
        # Antworten zu verschiedenen Zählern: mit dem Zähler der jeweiligen Anfrage öffnen
        seq = response.body["seq"]
        _, response_key = mc.device_keys(DEVICE_KEY)
        answer = json.loads(mc.open_envelope(response_key, response.body, direction="res", method="POST",
                                             path="/v1/sync", device_id=PHONE, seq=seq))
        hashes.add(mobile_pairing.hash_token(answer["token"]))
    assert phone is not None and stored["token_hash"] in hashes
    assert stored["previous_token_hash"] == mobile_pairing.hash_token(token)
    assert stored["last_seq"] == max(r.body["seq"] for r in accepted)


def test_the_route_table_has_exactly_the_three_routes(env):
    assert mobile_routes.methods_for_path("/v1/pair") == frozenset({"POST"})
    assert mobile_routes.methods_for_path("/v1/ping") == frozenset({"GET"})
    assert mobile_routes.methods_for_path("/v1/sync") == frozenset({"POST"})
    assert mobile_routes.methods_for_path("/v1/categories") == frozenset()
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
    fresh, _new_token = mobile_pairing.issue_device(PHONE, "Pixel neu", NOW, record)
    env.ctx.devices.save(fresh)                                  # erneut gekoppelt: neues Token

    response = call(env, "POST", "/v1/sync", body=sync_body(env, {"2026-10-07": day()}), principal=stale)

    assert response.status == 401 and error_code(response) == "unauthorized"
    assert env.ctx.storage.get_all_raw() == {}
    assert env.ctx.devices.get(PHONE)["previous_token_hash"] == ""     # nichts in die Karenz geschoben


def test_a_request_whose_token_expired_before_the_handler_ran_is_refused(env):
    _record, token = add_device(env)
    principal = principal_for(env, token)
    env.clock["now"] = "2026-11-07T12:00:00Z"                    # genau expires_at

    response = call(env, "POST", "/v1/sync", body=sync_body(env, {"2026-10-07": day()}), principal=principal)

    assert response.status == 401 and error_code(response) == "token_expired"
    assert env.ctx.storage.get_all_raw() == {}


# --- Verschlüsselung des Abgleichs ---------------------------------------------------------------------

def test_replay_of_the_same_envelope_is_refused(env):
    _record, token = add_device(env)
    body = sync_body(env)
    assert call(env, "POST", "/v1/sync", body=body, token=token).status == 200

    again = call(env, "POST", "/v1/sync", body=body, token=token)           # Karenz-Token, alter Umschlag

    assert (again.status, error_code(again)) == (409, "replay")


def test_a_lower_or_equal_sequence_number_is_refused_a_higher_one_accepted(env):
    _record, token = add_device(env)
    assert sync(env, token, seq=5).status == 200
    for seq in (5, 4, 1):
        refused = call(env, "POST", "/v1/sync", body=sync_body(env, seq=seq), token=token)
        assert (refused.status, error_code(refused)) == (409, "replay"), seq
    assert sync(env, token, seq=6).status == 200


def test_an_envelope_made_for_another_device_does_not_decrypt(env):
    a_record, a_token = add_device(env, "phone-aaaa", "A")
    b_record, b_token = add_device(env, "phone-bbbb", "B")
    env.ctx.keys.put("phone-bbbb", bytes(reversed(range(32))))              # eigener Schlüssel
    stolen = sync_body(env, device="phone-aaaa")

    response = call(env, "POST", "/v1/sync", body=stolen, token=b_token)

    assert (response.status, error_code(response)) == (400, "decrypt_failed")
    assert env.ctx.devices.get("phone-bbbb") == b_record


def test_an_envelope_for_another_path_or_direction_does_not_decrypt(env):
    _record, token = add_device(env)
    request_key, response_key = mc.device_keys(DEVICE_KEY)
    plain = json.dumps(sync_doc(env)).encode()
    for key, kwargs in ((request_key, {"path": "/v1/ping"}), (response_key, {"direction": "res"}),
                        (request_key, {"method": "GET"})):
        parts = {"direction": "req", "method": "POST", "path": "/v1/sync", "device_id": PHONE, "seq": 1}
        parts.update(kwargs)
        envelope = mc.seal(key, plaintext=plain, **parts)
        response = call(env, "POST", "/v1/sync", body=json.dumps(envelope).encode(), token=token)
        assert (response.status, error_code(response)) == (400, "decrypt_failed"), kwargs


def test_a_tampered_ciphertext_is_decrypt_failed_and_changes_nothing(env):
    _record, token = add_device(env)
    envelope = env.phones[PHONE].sync_request(sync_doc(env))
    raw = bytearray(mc.b64d(envelope["c"]))
    raw[0] ^= 1
    envelope["c"] = mc.b64e(bytes(raw))
    before = env.ctx.devices.get(PHONE)

    response = call(env, "POST", "/v1/sync", body=json.dumps(envelope).encode(), token=token)

    assert (response.status, error_code(response)) == (400, "decrypt_failed")
    assert env.ctx.devices.get(PHONE) == before                              # Zähler und Token unverändert


def test_a_device_without_a_key_must_pair_again(env):
    _record, token = add_device(env, with_key=False)
    phone = env.phones[PHONE]
    phone.key = DEVICE_KEY                                                  # das Handy hat einen, der Desktop keinen

    response = call(env, "POST", "/v1/sync", body=sync_body(env), token=token)

    assert (response.status, error_code(response)) == (401, "encryption_required")


def test_errors_after_decryption_are_sealed_and_do_not_leak_the_day(env):
    _record, token = add_device(env)

    raw = call(env, "POST", "/v1/sync", body=sync_body(env, {"2026-10-07": day(slots=(
        {"start": "12:00", "end": "08:00", "pause": 0, "kategorie": ""},))}), token=token)

    assert raw.status == 422 and is_sealed(raw.body) and "2026-10-07" not in json.dumps(raw.body)
    inner = opened(env, raw)
    assert error_code(inner) == "invalid_entry" and "2026-10-07" in inner.body["error"]["message"]


def test_the_counter_is_stored_even_when_the_sync_fails_after_decryption(env):
    _record, token = add_device(env)
    body = sync_body(env, client_time="2026-10-08T13:00:00Z")                # > 15 Minuten Abweichung

    first = call(env, "POST", "/v1/sync", body=body, token=token)
    again = call(env, "POST", "/v1/sync", body=body, token=token)            # derselbe Umschlag noch einmal

    assert first.status == 409 and is_sealed(first.body)
    assert env.ctx.devices.get(PHONE)["last_seq"] == 1
    assert (again.status, error_code(again)) == (409, "replay")              # nicht noch einmal einspielbar


def test_a_keyring_key_that_is_not_loaded_yet_is_503_and_changes_nothing(env):
    record, token = add_device(env)
    env.ctx.keys.migrate()                                                  # der Schlüssel zieht in den (Fake-)Schlüsselbund
    fresh = MobileKeyStore(str(env.keys_path))                              # Neustart: Cache leer
    env.ctx = dataclasses.replace(env.ctx, keys=fresh)
    before = env.ctx.devices.get(PHONE)

    response = call(env, "POST", "/v1/sync", body=sync_body(env), token=token)

    assert (response.status, error_code(response)) == (503, "key_unavailable")
    assert env.ctx.devices.get(PHONE) == before                              # Zähler und Token unverändert
    deadline = time.time() + 2                                              # Nachladen im Hintergrund
    while fresh.get(PHONE) is None and time.time() < deadline:
        time.sleep(0.01)
    assert sync(env, token).status == 200


def test_the_503_answer_does_not_wait_for_a_hanging_keyring(env):
    record, token = add_device(env)
    env.ctx.keys.migrate()
    env.ctx = dataclasses.replace(env.ctx, keys=MobileKeyStore(str(env.keys_path)))      # Neustart, Cache leer
    release = threading.Event()
    original = env.ring.fetch
    env.ring.fetch = lambda key: (release.wait(5), original(key))[1]                      # der Schlüsselbund hängt
    try:
        started = time.time()
        response = call(env, "POST", "/v1/sync", body=sync_body(env), token=token)
        assert (response.status, error_code(response)) == (503, "key_unavailable")
        assert time.time() - started < 1                                                  # nicht auf ihn gewartet
    finally:
        release.set()


def test_the_hot_path_never_touches_the_keyring(env, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("Schlüsselbund im heißen Pfad")
    monkeypatch.setattr(mobile_keys, "keyring_store", types.SimpleNamespace(put=boom, fetch=boom, remove=boom))
    _record, token = add_device(env)
    assert pair(env, new_code(env), device_id="phone-0002").status == 200
    assert sync(env, token).status == 200
    assert call(env, "GET", "/v1/ping", token=token).status == 200


def test_nothing_in_the_logs_names_secrets(env, caplog):
    caplog.set_level(logging.DEBUG)
    code = new_code(env)
    paired = pair(env, code, name="Pixel Geheim")
    token = paired.body["token"]
    env.phones[PHONE] = paired.phone
    ok = opened(env, call(env, "POST", "/v1/sync", body=json.dumps(paired.phone.sync_request(sync_doc(
        env, {"2026-10-07": day()}))).encode(), token=token), PHONE)
    call(env, "POST", "/v1/sync", body=json.dumps(paired.phone.sync_request(sync_doc(
        env, {"2026-10-07": day(slots=())}))).encode(), token=ok.body["token"])      # 422
    call(env, "POST", "/v1/sync", body=b'{"v":2}', token=ok.body["token"])
    key_forms = (paired.phone.key.hex(), base64.urlsafe_b64encode(paired.phone.key).rstrip(b"=").decode(),
                 mc.b64e(paired.phone.key))
    for secret in (code, token, ok.body["token"], *key_forms, "Projekt"):
        assert secret not in caplog.text, secret
