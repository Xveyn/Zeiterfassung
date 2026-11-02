# tests/test_relay_adapter.py
"""Der Adapter zwischen Relay-Nutzlast und `mobile_routes.dispatch` (#358), gegen echte Stores,
echtes `dispatch` und echte Umschläge des Test-Handys."""
from __future__ import annotations

import dataclasses
import json
import logging

import pytest

from src import api_server, mobile_crypto as mc, mobile_keys, mobile_pairing, mobile_routes
from src.api_routes import ApiResponse
from src.mobile_relay_codec import MAX_PAYLOAD, encode_too_large_response
from src.relay_adapter import RelayAdapter
from src.time_utils import utc_now_iso
from tests.mobile_phone import FakeRing, Phone
from tests.test_mobile_service import make_service


@pytest.fixture(autouse=True)
def ring(monkeypatch):
    """Kein Test fasst den echten Schlüsselbund an."""
    fake = FakeRing()
    monkeypatch.setattr(mobile_keys, "keyring_store", fake)
    return fake


@pytest.fixture
def ctx(tmp_path):
    _service, _settings, context = make_service(tmp_path)
    return context


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def frame(path, token, envelope, *, v=1):
    return json.dumps({"v": v, "path": path, "token": token, "envelope": envelope}).encode()


def answer(raw):
    assert raw is not None
    return json.loads(raw)


def new_code(ctx):
    code = mobile_pairing.normalize_code(ctx.pairing.open())
    assert code is not None
    return code


def pair_payload(ctx, phone):
    code = new_code(ctx)
    envelope = phone.pair_request(code)
    return code, envelope, frame("/v1/pair", None, envelope)


def paired(ctx, adapter, phone=None):
    phone = phone or Phone()
    code, _env, payload = pair_payload(ctx, phone)
    phone.open_pair_response(code, answer(adapter.handle(payload))["body"])
    return phone


def sync_body(entries=None):
    return {"protocol": mc.PROTOCOL, "client_time": utc_now_iso(), "last_pull_at": "",
            "entries": entries or {}}


def sync_payload(phone, *, seq=None, body=None, token=None):
    envelope = phone.sync_request(body or sync_body(), seq=seq)
    return envelope, frame("/v1/sync", token if token is not None else phone.token, envelope)


def counting_dispatch(monkeypatch):
    calls = []
    original = mobile_routes.dispatch

    def spy(request, context, principal):
        calls.append(request.path)
        return original(request, context, principal)
    monkeypatch.setattr(mobile_routes, "dispatch", spy)
    return calls


# --- Kopplung -------------------------------------------------------------------------------------

def test_a_pair_request_is_answered_and_the_phone_can_open_the_answer(ctx):
    adapter = RelayAdapter(ctx)
    phone = Phone()
    code, envelope, payload = pair_payload(ctx, phone)

    res = answer(adapter.handle(payload))
    opened = phone.open_pair_response(code, res["body"])

    assert list(res) == ["v", "status", "seq", "n", "body"]
    assert res["v"] == 1 and res["status"] == 200
    assert res["n"] == envelope["n"] and res["seq"] == envelope["seq"] == 1
    assert opened["token"] and ctx.devices.get(phone.device_id) is not None


def test_the_same_pair_request_twice_gets_the_identical_answer_and_pairs_once(ctx, monkeypatch):
    adapter = RelayAdapter(ctx)
    phone = Phone()
    code, _env, payload = pair_payload(ctx, phone)
    calls = counting_dispatch(monkeypatch)

    first = adapter.handle(payload)
    second = adapter.handle(payload)

    assert first is not None and second == first
    assert answer(second)["status"] == 200                     # kein 403 für den verbrauchten Code
    assert calls == ["/v1/pair"]
    assert mobile_pairing.pair_count(ctx.devices.get(phone.device_id)) == 1
    phone.open_pair_response(code, answer(second)["body"])


def test_a_different_pair_request_is_answered_fresh_and_a_failed_pair_is_not_cached(ctx, monkeypatch):
    adapter = RelayAdapter(ctx)
    calls = counting_dispatch(monkeypatch)
    _c1, _e1, first = pair_payload(ctx, Phone("phone-0001"))
    one = adapter.handle(first)
    _c2, _e2, second = pair_payload(ctx, Phone("phone-0002"))   # ein neuer Code ersetzt den alten
    two = adapter.handle(second)
    ctx.pairing.open()
    wrong_env = Phone("phone-0003").pair_request(mobile_pairing.generate_code())
    wrong = frame("/v1/pair", None, wrong_env)
    refused = answer(adapter.handle(wrong))
    refused_again = answer(adapter.handle(wrong))

    assert answer(one)["status"] == answer(two)["status"] == 200 and one != two
    assert refused["status"] == 403 and refused["body"]["error"]["code"] == "invalid_code"
    assert refused["n"] == wrong_env["n"] and refused["seq"] == 1
    assert refused_again == refused
    assert calls == ["/v1/pair"] * 4                            # der Fehlversuch ging zweimal durch


def test_the_pair_cache_is_bounded_and_expires(ctx, monkeypatch):
    clock = Clock()
    adapter = RelayAdapter(ctx, clock=clock)
    payloads, answers = [], []
    for i in range(9):                                          # cache_size ist 8
        payload = pair_payload(ctx, Phone(f"phone-{i:04d}"))[2]
        payloads.append(payload)
        answers.append(adapter.handle(payload))
    calls = counting_dispatch(monkeypatch)

    newest = adapter.handle(payloads[8])
    oldest = answer(adapter.handle(payloads[0]))

    assert all(answer(a)["status"] == 200 for a in answers)
    assert newest == answers[8] and calls == ["/v1/pair"]        # nur der älteste ist raus
    assert oldest["status"] == 403
    clock.t += 330.0
    assert adapter.handle(payloads[7]) == answers[7]             # genau die Lebensdauer: noch gültig
    clock.t += 0.5
    assert answer(adapter.handle(payloads[7]))["status"] == 403
    assert calls == ["/v1/pair"] * 2


def test_a_pair_request_after_a_replayed_sync_is_not_blocked_by_last_seq(ctx):
    adapter = RelayAdapter(ctx)
    phone = paired(ctx, adapter)
    _env, first = sync_payload(phone)
    assert answer(adapter.handle(first))["status"] == 200
    assert adapter.handle(first) is None

    code, envelope, payload = pair_payload(ctx, phone)
    res = answer(adapter.handle(payload))
    phone.open_pair_response(code, res["body"])
    _env2, again = sync_payload(phone)                          # wieder seq 1

    assert res["status"] == 200 and res["n"] == envelope["n"]
    assert ctx.devices.get(phone.device_id)["last_seq"] == 0   # Neu-Koppeln setzt zurück
    assert answer(adapter.handle(again))["status"] == 200
    assert ctx.devices.get(phone.device_id)["last_seq"] == 1


# --- Abgleich -------------------------------------------------------------------------------------

def test_a_sync_request_is_answered_and_applied(ctx):
    adapter = RelayAdapter(ctx)
    phone = paired(ctx, adapter)
    entries = {"2026-10-07": {"slots": [{"start": "08:00", "end": "12:00", "pause": 0,
                                         "kategorie": "Projekt"}],
                              "modified_at": "2026-10-07T18:30:00Z", "deleted": False}}
    envelope, payload = sync_payload(phone, body=sync_body(entries))

    res = answer(adapter.handle(payload))
    opened = phone.open_sync_response(res["body"])

    assert res["v"] == 1 and res["status"] == 200
    assert res["seq"] == envelope["seq"] == 1 and res["n"] == envelope["n"]
    assert "token" in opened
    assert ctx.devices.get(phone.device_id)["last_seq"] == 1
    assert ctx.storage.get_all_raw()["2026-10-07"]["device_id"] == phone.device_id


def test_a_replayed_or_older_seq_gets_no_answer(ctx, monkeypatch):
    adapter = RelayAdapter(ctx)
    phone = paired(ctx, adapter)
    _e1, first = sync_payload(phone, seq=1)
    _e2, third = sync_payload(phone, seq=3)
    assert answer(adapter.handle(first))["status"] == 200
    assert answer(adapter.handle(third))["status"] == 200
    calls = counting_dispatch(monkeypatch)
    _e3, older = sync_payload(phone, seq=2)

    assert adapter.handle(third) is None
    assert adapter.handle(older) is None
    assert adapter.handle(first) is None
    assert calls == []                                          # nie ein 409 aus dispatch
    assert ctx.devices.get(phone.device_id)["last_seq"] == 3


def test_last_seq_comes_from_the_device_record_not_from_the_adapter(ctx):
    phone = paired(ctx, RelayAdapter(ctx))
    _e1, first = sync_payload(phone)
    assert answer(RelayAdapter(ctx).handle(first))["status"] == 200

    restarted = RelayAdapter(ctx)                               # „Neustart“: kein Zustand im Speicher

    assert restarted.handle(first) is None
    _e2, second = sync_payload(phone)
    assert answer(restarted.handle(second))["status"] == 200


def test_sync_with_an_invalid_envelope_seq_gets_no_answer(ctx, monkeypatch):
    adapter = RelayAdapter(ctx)
    phone = paired(ctx, adapter)
    envelope, _payload = sync_payload(phone)
    calls = counting_dispatch(monkeypatch)

    for seq in (None, 0, -1, "1", True, 2**53):
        broken = dict(envelope)
        if seq is None:
            del broken["seq"]
        else:
            broken["seq"] = seq
        assert adapter.handle(frame("/v1/sync", phone.token, broken)) is None
    assert calls == []


def test_a_revoked_or_expired_token_gets_a_plain_401_with_the_nonce(ctx, monkeypatch):
    adapter = RelayAdapter(ctx)
    phone = paired(ctx, adapter)
    calls = counting_dispatch(monkeypatch)

    expired_env, expired_payload = sync_payload(phone)
    expired = answer(RelayAdapter(dataclasses.replace(ctx, now=lambda: "2099-01-01T00:00:00Z"))
                     .handle(expired_payload))
    unknown_env, unknown_payload = sync_payload(phone, token="unknown-token")
    unknown = answer(adapter.handle(unknown_payload))
    ctx.devices.save(mobile_pairing.revoke(ctx.devices.get(phone.device_id)))
    revoked_env, revoked_payload = sync_payload(phone)
    revoked = answer(adapter.handle(revoked_payload))

    for res, env, code in ((expired, expired_env, "token_expired"),
                           (unknown, unknown_env, "unauthorized"),
                           (revoked, revoked_env, "token_revoked")):
        assert res["v"] == 1 and res["status"] == 401
        assert res["n"] == env["n"] and res["seq"] == env["seq"]
        assert res["body"] == {"error": {"code": code, "message": api_server._AUTH_MESSAGES[code]}}
    assert calls == []


def test_a_device_record_gone_after_the_check_is_unauthorized(ctx, monkeypatch):
    adapter = RelayAdapter(ctx)
    phone = paired(ctx, adapter)
    envelope, payload = sync_payload(phone)
    monkeypatch.setattr(ctx.devices, "get", lambda _device_id: None)

    res = answer(adapter.handle(payload))

    assert res["status"] == 401 and res["body"]["error"]["code"] == "unauthorized"
    assert res["n"] == envelope["n"]


def test_protocol_errors_of_dispatch_pass_through_with_the_nonce(ctx):
    adapter = RelayAdapter(ctx)
    phone = paired(ctx, adapter)
    plain = {"v": 1, "seq": 5, "n": "A" * 16}                   # kein Umschlag v2
    wrong_key = Phone(phone.device_id)
    wrong_key.key, wrong_key.seq = mc.new_device_key(), 1
    foreign = wrong_key.sync_request(sync_body())

    protocol = answer(adapter.handle(frame("/v1/sync", phone.token, plain)))
    decrypt = answer(adapter.handle(frame("/v1/sync", phone.token, foreign)))
    pair_plain = answer(adapter.handle(frame("/v1/pair", None, plain)))

    assert protocol["status"] == 400 and protocol["body"]["error"]["code"] == "invalid_protocol"
    assert protocol["n"] == "A" * 16 and protocol["seq"] == 5
    assert decrypt["status"] == 400 and decrypt["body"]["error"]["code"] == "decrypt_failed"
    assert decrypt["n"] == foreign["n"] and decrypt["seq"] == 2
    assert pair_plain["status"] == 400 and pair_plain["body"]["error"]["code"] == "invalid_protocol"
    # Ein nicht entschlüsseltes Paket rückt den Zähler nicht vor: seq 2 ginge noch durch.
    assert ctx.devices.get(phone.device_id)["last_seq"] == 0


# --- Feindliches und Fehler -----------------------------------------------------------------------

def test_hostile_payloads_get_no_answer_and_never_raise(ctx, monkeypatch):
    adapter = RelayAdapter(ctx)
    phone = paired(ctx, adapter)
    envelope, _payload = sync_payload(phone)
    calls = counting_dispatch(monkeypatch)
    no_n = {k: v for k, v in envelope.items() if k != "n"}
    long_n = dict(envelope, n="A" * 17)
    hostile = [
        b"", b"not json", b"\xff\xfe", b"[]", b"null", b'{"v":1}',
        frame("/v1/sync", phone.token, envelope, v=2),
        frame("/v1/ping", phone.token, envelope),
        frame("../x", phone.token, envelope),
        frame("/v1/sync", phone.token, no_n),
        frame("/v1/sync", phone.token, long_n),
        frame("/v1/pair", None, no_n),
        frame("/v1/pair", None, long_n),
        frame("/v1/sync", None, envelope),
        json.dumps({"v": 1, "path": "/v1/sync", "envelope": envelope}).encode(),
        frame("/v1/sync", phone.token, ["not", "an", "object"]),
        b"x" * (MAX_PAYLOAD + 1),
    ]

    for payload in hostile:
        assert adapter.handle(payload) is None
    assert calls == []


def test_an_exception_in_dispatch_becomes_a_500_with_the_nonce_and_no_details(ctx, monkeypatch, caplog):
    adapter = RelayAdapter(ctx)
    phone = paired(ctx, adapter)
    real_dispatch = mobile_routes.dispatch

    def boom(request, context, principal):
        raise RuntimeError("secret-details")
    monkeypatch.setattr(mobile_routes, "dispatch", boom)
    pair_env = Phone("phone-0009").pair_request(new_code(ctx))
    sync_env, sync_frame = sync_payload(phone)

    with caplog.at_level(logging.DEBUG):
        raws = [adapter.handle(frame("/v1/pair", None, pair_env)), adapter.handle(sync_frame)]

    for raw, env in zip(raws, (pair_env, sync_env), strict=True):
        assert raw is not None and b"secret-details" not in raw
        res = answer(raw)
        assert res["status"] == 500 and res["body"]["error"]["code"] == "internal"
        assert res["n"] == env["n"] and res["seq"] == env["seq"]
    assert "RuntimeError" in caplog.text and "secret-details" not in caplog.text
    # Die gescheiterte Kopplung liegt nicht im Zwischenspeicher.
    monkeypatch.setattr(mobile_routes, "dispatch", real_dispatch)
    assert answer(adapter.handle(frame("/v1/pair", None, pair_env)))["status"] == 200


def test_an_oversized_answer_falls_back_to_the_413_frame(ctx, monkeypatch):
    adapter = RelayAdapter(ctx)
    phone = paired(ctx, adapter)
    monkeypatch.setattr(mobile_routes, "dispatch",
                        lambda request, context, principal: ApiResponse(200, {"x": "a" * MAX_PAYLOAD}))
    envelope, payload = sync_payload(phone)

    raw = adapter.handle(payload)

    assert raw == encode_too_large_response(envelope["seq"], envelope["n"])
    assert answer(raw)["status"] == 413


def test_an_unserializable_answer_becomes_a_500_with_the_nonce(ctx, monkeypatch):
    adapter = RelayAdapter(ctx)
    phone = paired(ctx, adapter)
    monkeypatch.setattr(mobile_routes, "dispatch",
                        lambda request, context, principal: ApiResponse(200, {"x": float("nan")}))
    envelope, payload = sync_payload(phone)

    res = answer(adapter.handle(payload))

    assert res["status"] == 500 and res["body"]["error"]["code"] == "internal"
    assert res["n"] == envelope["n"] and res["seq"] == envelope["seq"]


def test_shutdown_in_progress_is_answered_with_the_503_of_dispatch(ctx):
    phone = paired(ctx, RelayAdapter(ctx))
    closing = RelayAdapter(dataclasses.replace(ctx, closing=lambda: True))
    envelope, payload = sync_payload(phone)

    res = answer(closing.handle(payload))

    assert res["status"] == 503 and res["body"]["error"]["code"] == "shutting_down"
    assert res["n"] == envelope["n"] and res["seq"] == envelope["seq"]


def test_the_adapter_logs_no_token_envelope_or_secret(ctx, monkeypatch, caplog):
    secrets = []
    with caplog.at_level(logging.DEBUG):
        adapter = RelayAdapter(ctx)
        phone = Phone()
        code, pair_env, payload = pair_payload(ctx, phone)
        adapter.handle(payload)
        adapter.handle(payload)
        phone.open_pair_response(code, answer(adapter.handle(payload))["body"])
        sync_env, sync_frame = sync_payload(phone)
        token = phone.token
        adapter.handle(sync_frame)
        adapter.handle(sync_frame)                               # Replay
        adapter.handle(frame("/v1/sync", "unknown-token", sync_payload(phone)[0]))
        adapter.handle(b"not json")
        ctx.pairing.open()
        adapter.handle(frame("/v1/pair", None, Phone().pair_request(mobile_pairing.generate_code())))
        monkeypatch.setattr(mobile_routes, "dispatch", lambda *a: (_ for _ in ()).throw(
            RuntimeError(f"boom {token}")))
        _e, boom = sync_payload(phone)
        adapter.handle(boom)
        secrets = [code, token, "unknown-token", phone.token, pair_env["c"], sync_env["c"],
                   pair_env["n"], sync_env["n"], mc.b64e(phone.key or b"")]

    assert caplog.records
    for record in caplog.records:
        text = record.getMessage() + (record.exc_text or "")
        if record.exc_info:
            text += repr(record.exc_info[1])
        for secret in secrets:
            assert secret not in text, record.name
