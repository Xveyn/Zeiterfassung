# tests/test_mobile_relay_codec.py
"""Codec des Relay-Abgleichs (#358): jede Zeile der Vertrags-Fixture, dazu feindliche Eingaben."""
import json
import pathlib
import re

import pytest

from src import mobile_relay_codec as codec
from src.mobile_relay_codec import FrameError, FrameTooLarge
from src.mobile_routes import PWA_URL
from tests.test_mobile_contract import load

FX = load("relay-frames.json")
assert FX["requests"] and FX["responses"] and FX["links"] and FX["messages"] and FX["puts"]
ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN = "Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYmE"
N = "AAECAwQFBgcICQoL"
ENV = {"v": 2, "seq": 7, "n": N, "c": "q83vASNFZ4mrze8BI0VniQ"}


def _req(**over):
    base = {"v": 1, "path": "/v1/sync", "token": TOKEN, "envelope": dict(ENV)}
    base.update(over)
    return json.dumps(base).encode()


def test_constants_match_the_fixture_and_the_relay():
    c = FX["constants"]
    assert codec.SUBPROTOCOL == c["subprotocol"] == "zeit.v1"
    assert codec.MAX_FRAME == c["max_frame"]
    assert codec.MAX_PAYLOAD == c["max_payload"] == codec.MAX_FRAME - 1
    assert codec.PUTS_PER_MINUTE == c["puts_per_minute"]
    assert (codec.TYPE_PUT, codec.TYPE_SLOT, codec.TYPE_OK) == (
        c["types"]["put"], c["types"]["slot"], c["types"]["ok"])
    src = (ROOT / "relay" / "src" / "validate.js").read_text(encoding="utf-8")
    frame = re.search(r"maxFrame:\s*([\d_]+)", src)
    puts = re.search(r"putsPerMinute:\s*([\d_]+)", src)
    assert frame and puts
    assert int(frame.group(1).replace("_", "")) == codec.MAX_FRAME
    assert int(puts.group(1).replace("_", "")) == codec.PUTS_PER_MINUTE


@pytest.mark.parametrize("row", FX["puts"], ids=lambda r: r["name"])
def test_encode_put_matches_fixture(row):
    assert codec.encode_put(bytes.fromhex(row["payload_hex"])).hex() == row["hex"]


def test_encode_put_limits():
    assert len(codec.encode_put(b"a" * codec.MAX_PAYLOAD)) == codec.MAX_FRAME
    with pytest.raises(FrameTooLarge) as exc:
        codec.encode_put(b"a" * (codec.MAX_PAYLOAD + 1))
    assert exc.value.code == "too_large"
    assert FrameTooLarge("x").code == "too_large"
    assert FrameError("x").code == "invalid_frame"
    with pytest.raises(FrameError):
        codec.encode_put("text")  # type: ignore[arg-type]
    # Bytes statt Zeichen: Umlaute zaehlen doppelt
    with pytest.raises(FrameTooLarge):
        codec.encode_response(200, {"t": "ö" * (codec.MAX_PAYLOAD // 2)}, 1, N)
    overhead = len(b'{"v":1,"status":200,"seq":1,"n":"AAECAwQFBgcICQoL","body":{"t":""}}')
    fill = "a" * (codec.MAX_PAYLOAD - overhead)
    assert len(codec.encode_response(200, {"t": fill}, 1, N)) == codec.MAX_PAYLOAD
    with pytest.raises(FrameTooLarge):
        codec.encode_response(200, {"t": fill + "a"}, 1, N)


@pytest.mark.parametrize("row", FX["messages"], ids=lambda r: r["name"])
def test_decode_message_matches_every_fixture_vector(row):
    msg = codec.decode_message(bytes.fromhex(row["hex"]))
    want = row["decoded"]
    if want is None:
        assert msg is None
        return
    assert msg is not None
    assert msg.kind == want["kind"]
    assert msg.ver == want["ver"]
    assert msg.data.hex() == (want["data_hex"] or "")


def test_decode_message_ignores_text_and_unknown_types():
    assert codec.decode_message("hallo") is None
    assert codec.decode_message(b"\x09\x00\x00\x00\x01") is None
    assert codec.decode_message(None) is None  # type: ignore[arg-type]
    msg = codec.decode_message(bytearray(b"\x03\x00\x00\x00\x01"))  # type: ignore[arg-type]
    assert msg is not None and msg.kind == "ok"


@pytest.mark.parametrize("row", [r for r in FX["requests"] if r["ok"]], ids=lambda r: r["name"])
def test_decode_request_accepts_every_ok_fixture_case(row):
    req = codec.decode_request(row["json"].encode())
    assert req.path == row["path"]
    assert req.token == row["token"]
    assert req.seq == row["seq"]
    assert req.n == row["n"]
    assert isinstance(req.envelope, dict)


@pytest.mark.parametrize("row", [r for r in FX["requests"] if not r["ok"]], ids=lambda r: r["name"])
def test_decode_request_rejects_every_bad_fixture_case_with_frame_error_only(row):
    with pytest.raises(FrameError) as exc:
        codec.decode_request(row["json"].encode())
    assert type(exc.value) is FrameError


HOSTILE = [
    b"", b"\xff", b"\xef\xbb\xbf" + _req(), b"[]", b"null", b"1", b'"x"',
    b"[" * 100_000, b'{"a":' * 100_000,
    b'{"v":1,"path":"/v1/sync","token":"a","envelope":NaN}',
    b'{"v":1,"path":"/v1/sync","token":"a","envelope":{"x":Infinity}}',
    b'{"v":1,"path":"/v1/sync","token":"a","envelope":{"x":-Infinity}}',
    b'{"v":' + b"9" * 4000 + b',"path":"/v1/sync","token":"a","envelope":{}}',
    b'{"v":' + b"9" * 5000 + b',"path":"/v1/sync","token":"a","envelope":{}}',
    b'{"v":true,"path":"/v1/sync","token":"a","envelope":{}}',
    b'{"v":1,"path":["/v1/sync"],"token":"a","envelope":{}}',
    b'{"v":1,"path":"/v1/sync","token":5,"envelope":{}}',
    b'{"v":1,"path":"/v1/sync","token":"a\\n","envelope":{}}',
    b'{"v":1,"path":"/v1/sync","token":"a","envelope":{}} trailing',
]


@pytest.mark.parametrize("data", HOSTILE, ids=lambda d: repr(d[:30]))
def test_decode_request_hostile_input_raises_only_frame_error(data):
    with pytest.raises(FrameError):
        codec.decode_request(data)


def test_hugely_nested_but_small_valid_json_is_not_a_crash():
    deep = b'{"v":1,"path":"/v1/sync","token":"a","envelope":' + b"[" * 100_000 + b"]" * 100_000 + b"}"
    with pytest.raises(FrameError):
        codec.decode_request(deep)


def test_decode_request_rejects_oversized_and_non_bytes():
    with pytest.raises(FrameTooLarge):
        codec.decode_request(b" " * (codec.MAX_PAYLOAD + 1))
    with pytest.raises(FrameError):
        codec.decode_request("text")  # type: ignore[arg-type]


@pytest.mark.parametrize("seq", [1.5, -1, "1", True, False, 2**53, 0, None, [1], {}])
def test_bad_envelope_seq_is_a_valid_request_with_seq_none(seq):
    assert codec.decode_request(_req(envelope=dict(ENV, seq=seq))).seq is None


def test_envelope_seq_rejects_bool_zero_negative_text_float_and_huge():
    for bad in (True, False, 0, -1, "7", 1.5, 2**53, 2**4000, None, [], {}):
        assert codec.envelope_seq({"seq": bad}) is None
    assert codec.envelope_seq({}) is None
    assert codec.envelope_seq("x") is None
    assert codec.envelope_seq([1]) is None
    assert codec.envelope_seq({"seq": 1}) == 1
    assert codec.envelope_seq({"seq": 2**53 - 1}) == 2**53 - 1


@pytest.mark.parametrize("token", ["a\n", "a b", "ä", "x" * 513, "", 5, True])
def test_bad_tokens_are_rejected(token):
    with pytest.raises(FrameError):
        codec.decode_request(_req(token=token))


def test_token_null_only_for_pair_and_boundaries():
    assert codec.decode_request(_req(path="/v1/pair", token=None)).token is None
    absent = json.dumps({"v": 1, "path": "/v1/pair", "envelope": dict(ENV)}).encode()
    with pytest.raises(FrameError) as exc:
        codec.decode_request(absent)  # Schlüssel fehlt ist nicht dasselbe wie null
    assert type(exc.value) is FrameError
    with pytest.raises(FrameError):
        codec.decode_request(_req(path="/v1/sync", token=None))
    assert codec.decode_request(_req(token="x" * 512)).token == "x" * 512
    assert codec.decode_request(_req(token="!~")).token == "!~"


@pytest.mark.parametrize("row", [r for r in FX["responses"] if r["ok"]], ids=lambda r: r["name"])
def test_encode_response_round_trips_with_the_fixture_response_shape(row):
    out = codec.encode_response(row["status"], row["body"], row["seq"], row["n"])
    parsed = json.loads(out.decode("utf-8"))
    assert parsed == {"v": 1, "status": row["status"], "seq": row["seq"], "n": row["n"],
                      "body": row["body"]}
    assert list(parsed) == ["v", "status", "seq", "n", "body"]


CANONICAL_RESPONSES = [r for r in FX["responses"] if r["ok"] and r.get("canonical")]


def test_canonical_response_rows_cover_umlaut_and_too_large():
    assert len(CANONICAL_RESPONSES) >= 3
    assert any("Größe" in r["json"] for r in CANONICAL_RESPONSES)
    assert any(r["status"] == 413 for r in CANONICAL_RESPONSES)


@pytest.mark.parametrize("row", CANONICAL_RESPONSES, ids=lambda r: r["name"])
def test_encode_response_emits_exactly_the_canonical_fixture_bytes(row):
    # Byte-genau: kompakte Trenner, Reihenfolge v,status,seq,n,body, ensure_ascii=False, UTF-8.
    out = codec.encode_response(row["status"], row["body"], row["seq"], row["n"])
    assert out == row["json"].encode("utf-8")


@pytest.mark.parametrize("status", [99, 600, True, "200", 200.0, None, -1])
def test_encode_response_rejects_bad_status(status):
    with pytest.raises(FrameError):
        codec.encode_response(status, {}, 1, N)


@pytest.mark.parametrize("seq", [0, -1, True, 1.5, "7", 2**53])
def test_encode_response_rejects_bad_seq(seq):
    with pytest.raises(FrameError):
        codec.encode_response(200, {}, seq, N)


@pytest.mark.parametrize("n", [N[:-1], N + "A", N[:-1] + "+", N[:-1] + "=", N[:-1] + "\n", N + "\n",
                               "", 7, True, [N]])
def test_encode_response_rejects_bad_nonce(n):
    with pytest.raises(FrameError):
        codec.encode_response(200, {}, 1, n)


def test_encode_response_rejects_unserialisable_bodies_and_accepts_edges():
    for body in (object(), {"x": float("nan")}, {1, 2}):
        with pytest.raises(FrameError):
            codec.encode_response(200, body, 1, N)
    assert codec.encode_response(100, {}, None, None)
    assert codec.encode_response(599, {}, 2**53 - 1, "-_0123456789abcd")


def test_envelope_nonce_accepts_exactly_16_base64url_chars():
    assert codec.envelope_nonce(ENV) == N
    assert codec.envelope_nonce({"n": "-_0123456789abcd"}) == "-_0123456789abcd"
    for bad in (N[:-1], N + "A", N[:-1] + "+", N[:-1] + "=", N[:-1] + "\n", N + "\n", "", 7, None,
                True, [N], {}):
        assert codec.envelope_nonce({"n": bad}) is None
    for junk in (None, 5, N, [N], {}):
        assert codec.envelope_nonce(junk) is None


def test_request_with_invalid_nonce_is_valid_with_n_none():
    for bad in (N + "A", N[:-1], 7, None):
        req = codec.decode_request(_req(envelope=dict(ENV, n=bad)))
        assert req.n is None
        assert req.seq == 7
    assert codec.decode_request(_req()).n == N


def test_too_large_response_matches_the_fixture_and_always_fits():
    row = next(r for r in FX["responses"] if r["ok"] and r["status"] == 413)
    out = codec.encode_too_large_response(row["seq"], row["n"])
    assert out == row["json"].encode("utf-8")
    parsed = json.loads(out.decode("utf-8"))
    assert parsed["body"]["error"]["code"] == "response_too_large"
    assert len(out) <= codec.MAX_PAYLOAD
    assert len(codec.encode_too_large_response(2**53 - 1, N)) < 1024
    assert json.loads(codec.encode_too_large_response(None, None))["n"] is None
    with pytest.raises(FrameError):
        codec.encode_too_large_response(0, N)
    with pytest.raises(FrameError):
        codec.encode_too_large_response(7, "kurz")


def test_should_answer():
    assert codec.should_answer(5, 4) is True
    assert codec.should_answer(5, 5) is False
    assert codec.should_answer(4, 5) is False
    assert codec.should_answer(None, 0) is False
    assert codec.should_answer(1, 0) is True


def test_generate_box_secret_has_43_base64url_chars_and_differs_each_time():
    a, b = codec.generate_box_secret(), codec.generate_box_secret()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", a)
    assert a != b
    assert codec.BOX_SECRET_RE.fullmatch(a)


@pytest.mark.parametrize("row", [r for r in FX["links"] if r["kind"] == "relay"],
                         ids=lambda r: r["url"][:40])
def test_relay_link_matches_every_fixture_relay_link(row):
    if not row["url"].startswith(PWA_URL):
        pytest.skip("Nur-Fragment-Zeile")
    assert codec.relay_link(row["secret"], row["code"]) == row["url"]
    assert codec.relay_link(row["secret"], row["code"].lower()) == row["url"]


def test_relay_link_rejects_bad_ones():
    row = next(r for r in FX["links"] if r["kind"] == "relay")
    s, c = row["secret"], row["code"]
    for bad in (s[:-1], s + "A", s[:-1] + "+", s[:-1] + "\n", ""):
        assert codec.relay_link(bad, c) is None
    for letter in "01OIL":
        assert codec.relay_link(s, c[:-1] + letter) is None
    assert codec.relay_link(s, c[:-1]) is None
    assert codec.relay_link(s, None) is None  # type: ignore[arg-type]
    assert codec.relay_link(None, c) is None  # type: ignore[arg-type]


def test_relay_link_fits_qr_version_10():
    pytest.importorskip("segno")
    from src import qr as qrmod
    link = codec.relay_link(codec.generate_box_secret(), "K7M29QXAK7M29QXAK7M29QXAK7M2")
    assert link is not None
    assert len(qrmod.qr_matrix(link)) <= 57
