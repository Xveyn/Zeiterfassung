# tests/test_api_server.py
import http.client
import json
import logging
import socket
import threading
import time

import pytest

from src import api_server
from src.api_auth import single_token_verifier
from src.api_routes import ApiContext
from src.api_server import MAX_BODY_BYTES, ApiServer
from src.storage import Storage
from tests.conftest import ist_slot

TOKEN = "T" * 43


def make_context(tmp_path, storage=None):
    if storage is None:
        storage = Storage(str(tmp_path / "zeiterfassung.json"), device_id="dev")
        storage.save("2026-01-05", [ist_slot("08:00", "12:00", 0, "Projekt")])
    return ApiContext(storage=storage, settings={"device_name": "Test"},
                      app_version=lambda: "9.9.9")


@pytest.fixture
def server(tmp_path):
    srv = ApiServer(make_context(tmp_path), single_token_verifier(TOKEN), port=0)
    srv.start()
    yield srv
    srv.stop()


def http_call(server, method, path, headers=None, body=None, drop=(), token=TOKEN):
    """Eine Anfrage; Header-Werte dürfen Listen sein (doppelte Header)."""
    merged = {} if token is None else {"Authorization": f"Bearer {token}"}
    merged.update(headers or {})
    for name in drop:
        merged.pop(name, None)
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    try:
        conn.putrequest(method, path, skip_host="Host" in merged,
                        skip_accept_encoding=True)
        for name, value in merged.items():
            for single in (value if isinstance(value, list) else [value]):
                conn.putheader(name, single)
        if body is not None and "Content-Length" not in merged:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body)
        response = conn.getresponse()
        raw = response.read()
        return response, (json.loads(raw) if raw else None), raw
    finally:
        conn.close()


def error_code(parsed):
    return parsed["error"]["code"]


# --- Grundverhalten und Antwort-Header --------------------------------------

def test_status_with_valid_token(server):
    response, body, _ = http_call(server, "GET", "/v1/status")

    assert response.status == 200
    assert body["app_version"] == "9.9.9" and body["device_name"] == "Test"
    assert response.getheader("Content-Type") == "application/json; charset=utf-8"
    assert response.getheader("Cache-Control") == "no-store"
    assert response.getheader("X-Content-Type-Options") == "nosniff"


def test_entries_are_served_end_to_end(server):
    response, body, _ = http_call(server, "GET", "/v1/entries?from=2026-01-01&to=2026-01-31")

    assert response.status == 200
    assert body["entries"]["2026-01-05"]["slots"][0]["kategorie"] == "Projekt"


def test_server_header_hides_the_python_version(server):
    response, _, _ = http_call(server, "GET", "/v1/status")
    assert response.getheader("Server") == "Zeiterfassung-API"


def test_no_response_ever_carries_cors_headers(server):
    for method, path, token in [("GET", "/v1/status", TOKEN), ("GET", "/v1/status", None),
                                ("OPTIONS", "/v1/status", TOKEN), ("GET", "/nope", TOKEN)]:
        response, _, _ = http_call(server, method, path, token=token)
        cors = [n for n, _ in response.getheaders() if n.lower().startswith("access-control")]
        assert cors == [], (method, path, cors)


# --- Auth am Draht -----------------------------------------------------------

def test_missing_and_wrong_token_are_401_with_challenge(server):
    for token in (None, "falsch"):
        response, body, raw = http_call(server, "GET", "/v1/status", token=token)
        assert response.status == 401 and error_code(body) == "unauthorized"
        assert response.getheader("WWW-Authenticate") == "Bearer"
        assert TOKEN.encode() not in raw


def test_unknown_path_without_token_does_not_leak_existence(server):
    response, body, _ = http_call(server, "GET", "/v1/gibt-es-nicht", token=None)
    assert response.status == 401


def test_unknown_path_with_token_is_404_json(server):
    response, body, _ = http_call(server, "GET", "/v1/gibt-es-nicht")
    assert (response.status, error_code(body)) == (404, "not_found")


def test_options_head_patch_trace_and_unknown_methods_are_405_with_allow(server):
    for method in ("OPTIONS", "HEAD", "PATCH", "TRACE", "FOO"):
        response, _, _ = http_call(server, method, "/v1/status")
        assert response.status == 405, method
        assert response.getheader("Allow") == "DELETE, GET, POST, PUT"


def test_wrong_host_origin_and_sec_fetch_are_403(server):
    cases = [({"Host": "evil.example"}, "bad_host"),
             ({"Origin": "https://evil.example"}, "bad_origin"),
             ({"Sec-Fetch-Site": "cross-site"}, "browser_request")]
    for headers, code in cases:
        response, body, _ = http_call(server, "GET", "/v1/status", headers)
        assert (response.status, error_code(body)) == (403, code), headers


def test_a_write_without_json_content_type_is_415(server):
    response, body, _ = http_call(server, "PUT", "/v1/entries/2026-01-05", body=b"{}",
                                  headers={"Content-Type": "text/plain"})
    assert (response.status, error_code(body)) == (415, "unsupported_media_type")


# --- Review Focus 2: böse Header und Bodies ----------------------------------

@pytest.mark.parametrize("name", ["Host", "Authorization", "Origin", "Content-Type",
                                  "Content-Length"])
def test_duplicate_single_value_headers_are_400(server, name):
    values = {"Host": ["127.0.0.1", "evil.example"],
              "Authorization": [f"Bearer {TOKEN}", "Bearer x"],
              "Origin": ["a", "b"], "Content-Type": ["application/json"] * 2,
              "Content-Length": ["0", "0"]}[name]
    response, body, _ = http_call(server, "GET", "/v1/status", {name: values})
    assert (response.status, error_code(body)) == (400, "duplicate_header")


def test_chunked_transfer_encoding_is_400(server):
    response, body, _ = http_call(server, "GET", "/v1/status",
                                  {"Transfer-Encoding": "chunked"})
    assert (response.status, error_code(body)) == (400, "unsupported_encoding")


# Nicht dabei: Werte, die der Client selbst nicht senden kann (Nicht-Latin-1)
# oder die der Header-Parser vor dem Server zu einer gültigen Zahl trimmt (" 5").
@pytest.mark.parametrize("value", ["abc", "-1", "1.5", "²", "0x10", ""])
def test_invalid_content_length_is_400(server, value):
    response, body, _ = http_call(server, "GET", "/v1/status", {"Content-Length": value})
    assert (response.status, error_code(body)) == (400, "invalid_content_length")


@pytest.mark.parametrize("value", [str(MAX_BODY_BYTES + 1), "9" * 5000])
def test_oversized_body_is_413_without_reading_it(server, value):
    response, body, _ = http_call(server, "GET", "/v1/status", {"Content-Length": value})
    assert (response.status, error_code(body)) == (413, "payload_too_large")


def test_truncated_body_is_400(server):
    sock = socket.create_connection(("127.0.0.1", server.port), timeout=5)
    try:
        sock.sendall((f"GET /v1/status HTTP/1.0\r\nHost: 127.0.0.1:{server.port}\r\n"
                      f"Authorization: Bearer {TOKEN}\r\nContent-Length: 50\r\n\r\nkurz").encode())
        sock.shutdown(socket.SHUT_WR)
        raw = b""
        while chunk := sock.recv(4096):
            raw += chunk
    finally:
        sock.close()
    head, _, payload = raw.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.0 400")
    assert json.loads(payload)["error"]["code"] == "incomplete_body"


def test_protocol_errors_get_a_json_error_not_html(server):
    # 150 Header: `http.server` lehnt mit 431 ab, und zwar über `send_error` —
    # das ist überschrieben und muss JSON liefern statt der HTML-Seite.
    sock = socket.create_connection(("127.0.0.1", server.port), timeout=5)
    try:
        sock.sendall(b"GET /v1/status HTTP/1.0\r\n" + b"X: 1\r\n" * 150 + b"\r\n")
        raw = b""
        while chunk := sock.recv(4096):
            raw += chunk
    finally:
        sock.close()
    head, _, payload = raw.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.0 431")
    assert json.loads(payload)["error"]["code"] == "http_error"
    assert b"<html" not in raw.lower()


def test_path_forms_are_not_reinterpreted(server):
    # Host explizit setzen: `http.client` leitet ihn bei einer absoluten URL
    # sonst aus der URL ab (evil.example) und der Test träfe 403 statt 404.
    host = {"Host": f"127.0.0.1:{server.port}"}
    for path in ("/v1/status#x", "http://evil.example/v1/status"):
        response, _, _ = http_call(server, "GET", path, host)
        assert response.status == 404, path


def test_leading_double_slash_never_reaches_a_different_resource(server):
    # `http.server` kollabiert führende Schrägstriche selbst (gh-87389, je nach
    # Python-Patchversion): `//v1/status` kommt als `/v1/status` an. Beides ist
    # unkritisch — der Pfad ist authentifiziert und trifft dieselbe Ressource —,
    # aber nie etwas anderes. Das Routing selbst lehnt `//v1/status` ab
    # (test_api_routes).
    response, body, _ = http_call(server, "GET", "//v1/status")
    assert response.status in (200, 404)
    if response.status == 200:
        assert "api_version" in body


def test_too_many_query_fields_are_400(server):
    query = "&".join(f"a{i}=1" for i in range(500))
    response, body, _ = http_call(server, "GET", f"/v1/entries?{query}")
    assert response.status == 400


def test_slow_client_is_dropped_and_the_server_keeps_serving(server, monkeypatch):
    monkeypatch.setattr(api_server._Handler, "timeout", 0.3)
    sock = socket.create_connection(("127.0.0.1", server.port), timeout=5)
    try:
        time.sleep(0.8)
        assert sock.recv(100) == b""          # Server hat die Verbindung geschlossen
    finally:
        sock.close()

    assert http_call(server, "GET", "/v1/status")[0].status == 200


def test_unexpected_handler_error_is_500_without_details(tmp_path, caplog):
    class Broken:
        def get_all(self):
            raise RuntimeError("geheime Details")

        def get(self, date_str):
            raise RuntimeError("geheime Details")

    srv = ApiServer(make_context(tmp_path, storage=Broken()), single_token_verifier(TOKEN))
    srv.start()
    try:
        with caplog.at_level(logging.ERROR):
            response, body, raw = http_call(srv, "GET", "/v1/entries")
    finally:
        srv.stop()

    assert (response.status, error_code(body)) == (500, "internal_error")
    assert b"geheime" not in raw
    assert "API-Anfrage fehlgeschlagen" in caplog.text


def test_concurrent_requests_are_all_served(server):
    results = []

    def worker():
        results.append(http_call(server, "GET", "/v1/status")[0].status)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [200] * 20


# --- Verifier-Tausch (Token-Rotation) ------------------------------------------

def test_set_verifier_switches_the_accepted_token_atomically(server):
    server.set_verifier(single_token_verifier("N" * 43))

    assert http_call(server, "GET", "/v1/status", token=TOKEN)[0].status == 401
    assert http_call(server, "GET", "/v1/status", token="N" * 43)[0].status == 200


# --- Review Focus 3: Bind, Port, Stopp -------------------------------------------

def test_server_binds_loopback_only(server):
    assert server._httpd.server_address[0] == "127.0.0.1"
    assert server.port > 0


def test_second_server_on_the_same_port_fails(server, tmp_path):
    other = ApiServer(make_context(tmp_path), single_token_verifier(TOKEN), port=server.port)
    with pytest.raises(OSError):
        other.start()


def test_stop_releases_the_port_and_a_new_start_succeeds(tmp_path):
    first = ApiServer(make_context(tmp_path), single_token_verifier(TOKEN), port=0)
    first.start()
    port = first.port
    first.stop()

    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)

    again = ApiServer(make_context(tmp_path), single_token_verifier(TOKEN), port=port)
    again.start()
    try:
        assert http_call(again, "GET", "/v1/status")[0].status == 200
    finally:
        again.stop()


def test_stop_is_idempotent_and_port_needs_a_running_server(tmp_path):
    srv = ApiServer(make_context(tmp_path), single_token_verifier(TOKEN))
    srv.stop()                                  # nie gestartet: kein Fehler
    srv.start()
    srv.stop()
    srv.stop()
    with pytest.raises(RuntimeError):
        _ = srv.port


def test_start_twice_is_a_programming_error(server):
    with pytest.raises(RuntimeError):
        server.start()


def test_start_does_not_resolve_the_host_name(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("socket.getfqdn kann bei kaputtem DNS hängen")

    monkeypatch.setattr(socket, "getfqdn", boom)
    srv = ApiServer(make_context(tmp_path), single_token_verifier(TOKEN))
    srv.start()
    srv.stop()
