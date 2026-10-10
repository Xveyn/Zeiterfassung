# tests/test_mobile_crypto.py
import json
import pathlib

import pytest

from src import mobile_crypto as mc

VECTORS = json.loads((pathlib.Path(__file__).resolve().parent.parent
                      / "pwa" / "test" / "fixtures" / "crypto-vectors.json").read_text("utf-8"))
KEY = bytes(range(32))
KW = dict(direction="req", method="POST", path="/v1/sync", device_id="phone-0001", seq=7)


def sealed(plaintext=b'{"a":1}', **over):
    return mc.seal(KEY, plaintext=plaintext, **{**KW, **over})


def test_round_trip_and_envelope_shape():
    envelope = sealed()
    assert set(envelope) == {"v", "seq", "n", "c"}
    assert envelope["v"] == 2 and envelope["seq"] == 7
    assert mc.open_envelope(KEY, envelope, **{k: v for k, v in KW.items() if k != "seq"}) == b'{"a":1}'


def test_every_message_gets_a_fresh_nonce():
    assert len({sealed()["n"] for _ in range(200)}) == 200


@pytest.mark.parametrize("field,value", [("direction", "res"), ("method", "GET"),
                                         ("path", "/v1/ping"), ("device_id", "phone-0002")])
def test_aad_binds_direction_method_path_and_device(field, value):
    envelope = sealed()
    args = {k: v for k, v in KW.items() if k != "seq"}
    args[field] = value
    with pytest.raises(mc.CryptoError) as excinfo:
        mc.open_envelope(KEY, envelope, **args)
    assert excinfo.value.code == "decrypt_failed"


def test_aad_binds_the_sequence_number():
    envelope = sealed()
    envelope["seq"] = 8
    with pytest.raises(mc.CryptoError) as excinfo:
        mc.open_envelope(KEY, envelope, **{k: v for k, v in KW.items() if k != "seq"})
    assert excinfo.value.code == "decrypt_failed"


def test_a_flipped_bit_in_the_ciphertext_or_nonce_fails():
    for field in ("c", "n"):
        envelope = sealed()
        raw = bytearray(mc.b64d(envelope[field]))
        raw[0] ^= 1
        envelope[field] = mc.b64e(bytes(raw))
        with pytest.raises(mc.CryptoError):
            mc.open_envelope(KEY, envelope, **{k: v for k, v in KW.items() if k != "seq"})


def test_a_wrong_key_fails():
    with pytest.raises(mc.CryptoError) as excinfo:
        mc.open_envelope(bytes(32), sealed(), **{k: v for k, v in KW.items() if k != "seq"})
    assert excinfo.value.code == "decrypt_failed"


@pytest.mark.parametrize("bad", [
    None, [], "x", {}, {"v": 2}, {"v": 1, "seq": 1, "n": "A" * 16, "c": "A" * 40},
    {"v": 2, "seq": 0, "n": "A" * 16, "c": "A" * 40}, {"v": 2, "seq": True, "n": "A" * 16, "c": "A" * 40},
    {"v": 2, "seq": 2 ** 53, "n": "A" * 16, "c": "A" * 40}, {"v": 2, "seq": 1.5, "n": "A" * 16, "c": "A" * 40},
    {"v": 2, "seq": 1, "n": "AAAA", "c": "A" * 40}, {"v": 2, "seq": 1, "n": "A" * 16, "c": "AAAA"},
    {"v": 2, "seq": 1, "n": "A" * 16, "c": "A" * 40, "x": 1},
    {"v": 2, "seq": 1, "n": "A" * 15 + "=", "c": "A" * 40},
    {"v": 2, "seq": 1, "n": "A" * 16, "c": "A!" * 20},
])
def test_malformed_envelopes_are_refused_before_decrypting(bad):
    assert not mc.is_envelope(bad)
    with pytest.raises(mc.CryptoError) as excinfo:
        mc.open_envelope(KEY, bad, direction="req", method="POST", path="/v1/sync", device_id="d" * 8)
    assert excinfo.value.code == "invalid_envelope"


def test_base64url_is_strict():
    assert mc.b64d(mc.b64e(bytes(range(40)))) == bytes(range(40))
    for text in ("AA==", "A", "AA AA", "AA+/", "é"):
        with pytest.raises(mc.CryptoError):
            mc.b64d(text)


def test_request_and_response_keys_differ_and_depend_on_the_secret():
    request, response = mc.device_keys(KEY)
    assert request != response and len(request) == len(response) == 32
    assert mc.device_keys(bytes(32)) != (request, response)
    pair_request, pair_response = mc.pair_keys("K7M29QXA" * 3 + "K7M2")
    assert pair_request != pair_response and pair_request != request


def test_a_request_cannot_be_replayed_as_a_response():
    request_key, response_key = mc.device_keys(KEY)
    envelope = mc.seal(request_key, plaintext=b"x", **KW)
    with pytest.raises(mc.CryptoError):
        mc.open_envelope(response_key, envelope, **{**{k: v for k, v in KW.items() if k != "seq"}, "direction": "res"})


def test_new_device_keys_are_random_32_bytes():
    keys = {mc.new_device_key() for _ in range(50)}
    assert len(keys) == 50 and all(len(k) == 32 for k in keys)


def test_vectors_match_what_python_computes():
    # Dieselbe Datei prüft pwa/test/crypto.test.js: Gleichlauf der beiden Sprachen.
    code = VECTORS["code"]
    pair_request, pair_response = mc.pair_keys(code)
    assert pair_request.hex() == VECTORS["pair_request_key"]
    assert pair_response.hex() == VECTORS["pair_response_key"]
    request, response = mc.device_keys(bytes.fromhex(VECTORS["device_key"]))
    assert request.hex() == VECTORS["request_key"] and response.hex() == VECTORS["response_key"]
    for case in VECTORS["cases"]:
        key = bytes.fromhex(case["key"])
        envelope = mc.seal(key, direction=case["direction"], method=case["method"], path=case["path"],
                           device_id=case["device_id"], seq=case["seq"],
                           plaintext=case["plaintext"].encode("utf-8"), nonce=bytes.fromhex(case["nonce"]))
        assert envelope == case["envelope"]
        assert mc.open_envelope(key, case["envelope"], direction=case["direction"], method=case["method"],
                                path=case["path"], device_id=case["device_id"]) == case["plaintext"].encode("utf-8")
