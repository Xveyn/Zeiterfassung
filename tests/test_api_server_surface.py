# tests/test_api_server_surface.py
import http.client
import json

import pytest

from src.api_auth import SCOPE_MOBILE, Denied, Policy, Principal
from src.api_routes import ApiRequest, ApiResponse
from src.api_server import ApiServer, Surface

ORIGIN = "https://xveyn.github.io"
GOOD, EXPIRED, REVOKED = "G" * 43, "E" * 43, "R" * 43
ROUTES = {"/v1/ping": frozenset({"GET"}), "/v1/pair": frozenset({"POST"}),
          "/v1/sync": frozenset({"POST"})}


def verify(token):
    if token == GOOD:
        return Principal("device-0001", frozenset({SCOPE_MOBILE}))
    if token == EXPIRED:
        return Denied("token_expired")
    if token == REVOKED:
        return Denied("token_revoked")
    return None


def make_surface(calls, *, cors=False):
    def dispatch(request: ApiRequest, principal: Principal) -> ApiResponse:
        if request.path not in ROUTES:
            return ApiResponse(404, {"error": {"code": "not_found", "message": "Unbekannt."}})
        calls.append((request.method, request.path, principal.name))
        return ApiResponse(200, {"who": principal.name, "path": request.path,
                                 "body": request.body.decode("utf-8")})

    return Surface(dispatch=dispatch, methods=frozenset({"GET", "POST"}),
                   route_methods=lambda path: ROUTES.get(path, frozenset()),
                   public=frozenset({("POST", "/v1/pair")}), cors=cors)


@pytest.fixture
def make_server():
    servers = []

    def build(*, cors=False, verifier=verify):
        calls = []

        def policy_for(port):
            return Policy(allowed_hosts=frozenset({f"127.0.0.1:{port}"}),
                          allowed_origins=frozenset({ORIGIN}), bind_host="127.0.0.1")

        server = ApiServer(None, verifier, port=0, policy_for_port=policy_for,
                           surface=make_surface(calls, cors=cors))
        server.start()
        server.calls = calls
        servers.append(server)
        return server

    yield build
    for server in servers:
        server.stop()


def call(server, method, path, headers=None, body=None, token=GOOD):
    merged = {} if token is None else {"Authorization": f"Bearer {token}"}
    merged.update(headers or {})
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    try:
        conn.putrequest(method, path, skip_host="Host" in merged, skip_accept_encoding=True)
        for name, value in merged.items():
            conn.putheader(name, value)
        if body is not None:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body)
        response = conn.getresponse()
        raw = response.read()
        return response, (json.loads(raw) if raw else None), raw
    finally:
        conn.close()


JSON = {"Content-Type": "application/json"}


def code(parsed):
    return parsed["error"]["code"]


# --- Surface statt ApiContext -------------------------------------------------------------------

def test_the_dispatch_of_the_surface_serves_authenticated_routes(make_server):
    server = make_server()

    response, body, _ = call(server, "GET", "/v1/ping")

    assert response.status == 200 and body["who"] == "device-0001"
    assert server.calls == [("GET", "/v1/ping", "device-0001")]


def test_a_server_needs_a_context_or_a_surface():
    with pytest.raises(ValueError):
        ApiServer(None, verify)


@pytest.mark.parametrize("token,expected", [
    (EXPIRED, "token_expired"), (REVOKED, "token_revoked"), ("X" * 43, "unauthorized"),
    (None, "unauthorized"),
])
def test_denied_verdicts_reach_the_client_as_401(make_server, token, expected):
    server = make_server()

    response, body, _ = call(server, "GET", "/v1/ping", token=token)

    assert response.status == 401 and code(body) == expected
    assert response.getheader("WWW-Authenticate") == "Bearer"
    assert server.calls == []


def test_a_verifier_that_raises_is_a_500_without_details(make_server):
    def broken(token):
        raise RuntimeError("geheimer Zustand")

    server = make_server(verifier=broken)

    response, body, raw = call(server, "GET", "/v1/ping")

    assert response.status == 500 and code(body) == "internal_error"
    assert b"geheimer" not in raw and server.calls == []


def test_the_allow_header_of_a_405_comes_from_the_surface(make_server):
    server = make_server()

    response, body, _ = call(server, "PATCH", "/v1/ping")

    assert response.status == 405 and response.getheader("Allow") == "GET, POST"


# --- öffentliche Routen -----------------------------------------------------------------------------

def test_a_public_route_needs_no_token(make_server):
    server = make_server()

    response, body, _ = call(server, "POST", "/v1/pair", JSON, b'{"code": "x"}', token=None)

    assert response.status == 200 and body["who"] == "anonymous"
    assert server.calls == [("POST", "/v1/pair", "anonymous")]


def test_a_public_route_ignores_an_authorization_header(make_server):
    server = make_server()

    _, body, _ = call(server, "POST", "/v1/pair", JSON, b"{}", token=EXPIRED)

    assert body["who"] == "anonymous"


@pytest.mark.parametrize("method,path", [
    ("GET", "/v1/pair"), ("POST", "/v1/pair/"), ("POST", "/v1/pair/x"), ("POST", "/v1/pairs"),
    ("POST", "/v1/sync"), ("PUT", "/v1/pair"),
])
def test_only_the_exact_method_and_path_are_public(make_server, method, path):
    server = make_server()

    response, body, _ = call(server, method, path, JSON, b"{}", token=None)

    assert response.status == 401 and code(body) == "unauthorized"
    assert server.calls == []


@pytest.mark.parametrize("headers,status,expected", [
    ({"Content-Type": "text/plain"}, 415, "unsupported_media_type"),
    ({"Origin": "https://evil.example", **JSON}, 403, "bad_origin"),
    ({"Sec-Fetch-Site": "cross-site", **JSON}, 403, "browser_request"),
    ({"Host": "evil.example", **JSON}, 403, "bad_host"),
])
def test_a_public_route_keeps_the_other_gates(make_server, headers, status, expected):
    server = make_server()

    response, body, _ = call(server, "POST", "/v1/pair", headers, b"{}", token=None)

    assert response.status == status and code(body) == expected
    assert server.calls == []


def test_the_query_string_does_not_turn_a_protected_path_public(make_server):
    server = make_server()

    response, body, _ = call(server, "POST", "/v1/sync?x=/v1/pair", JSON, b"{}", token=None)

    assert response.status == 401 and server.calls == []


# --- CORS ---------------------------------------------------------------------------------------------

def preflight(server, path="/v1/sync", method="POST", headers=None, drop=()):
    merged = {"Origin": ORIGIN, "Access-Control-Request-Method": method,
              "Access-Control-Request-Headers": "authorization, content-type"}
    merged.update(headers or {})
    for name in drop:
        merged.pop(name, None)
    return call(server, "OPTIONS", path, merged, token=None)


def test_a_preflight_is_a_204_without_body_and_needs_no_token(make_server):
    server = make_server(cors=True)

    response, body, raw = preflight(server)

    assert response.status == 204 and raw == b"" and body is None
    assert response.getheader("Content-Type") is None
    assert response.getheader("Access-Control-Allow-Origin") == ORIGIN
    assert response.getheader("Vary") == "Origin"
    assert response.getheader("Access-Control-Allow-Methods") == "POST"
    assert response.getheader("Access-Control-Allow-Headers") == "Authorization, Content-Type"
    assert response.getheader("Access-Control-Max-Age") == "600"
    assert response.getheader("Access-Control-Allow-Credentials") is None
    assert response.getheader("Access-Control-Allow-Private-Network") is None
    assert server.calls == []                          # der Preflight trägt keine Daten


def test_the_preflight_answers_the_private_network_request(make_server):
    server = make_server(cors=True)

    response, _, _ = preflight(server, headers={"Access-Control-Request-Private-Network": "true"})

    assert response.getheader("Access-Control-Allow-Private-Network") == "true"


@pytest.mark.parametrize("kwargs,status", [
    ({"headers": {"Origin": "https://evil.example"}}, 403),
    ({"drop": ("Origin",)}, 403),
    ({"headers": {"Host": "evil.example"}}, 403),
    ({"path": "/v1/unbekannt"}, 404),
    ({"path": "/v1/ping", "method": "POST"}, 405),                  # /v1/ping kennt nur GET
    ({"method": "DELETE"}, 405),
    ({"drop": ("Access-Control-Request-Method",)}, 405),
])
def test_a_refused_preflight_has_no_cors_headers(make_server, kwargs, status):
    server = make_server(cors=True)

    response, body, _ = preflight(server, **kwargs)

    assert response.status == status and "error" in body
    assert response.getheader("Access-Control-Allow-Origin") is None
    assert response.getheader("Access-Control-Allow-Methods") is None
    assert server.calls == []


def test_responses_for_the_allowed_origin_carry_cors_headers_even_when_they_are_errors(make_server):
    server = make_server(cors=True)

    ok, _, _ = call(server, "GET", "/v1/ping", {"Origin": ORIGIN})
    expired, body, _ = call(server, "GET", "/v1/ping", {"Origin": ORIGIN}, token=EXPIRED)
    missing, _, _ = call(server, "GET", "/v1/unbekannt", {"Origin": ORIGIN})

    for response in (ok, expired, missing):
        assert response.getheader("Access-Control-Allow-Origin") == ORIGIN
        assert response.getheader("Vary") == "Origin"
        assert response.getheader("Access-Control-Allow-Credentials") is None
    assert (ok.status, expired.status, missing.status) == (200, 401, 404)
    assert code(body) == "token_expired"


def test_a_public_route_answers_the_allowed_origin_too(make_server):
    server = make_server(cors=True)

    response, _, _ = call(server, "POST", "/v1/pair", {"Origin": ORIGIN, **JSON}, b"{}", token=None)

    assert response.status == 200
    assert response.getheader("Access-Control-Allow-Origin") == ORIGIN


def test_a_server_error_carries_cors_headers_for_the_allowed_origin(make_server):
    def broken(token):
        raise RuntimeError("x")

    server = make_server(cors=True, verifier=broken)

    response, body, _ = call(server, "GET", "/v1/ping", {"Origin": ORIGIN})

    assert response.status == 500
    assert response.getheader("Access-Control-Allow-Origin") == ORIGIN


def test_a_foreign_origin_gets_a_403_without_cors_headers(make_server):
    server = make_server(cors=True)

    response, body, _ = call(server, "GET", "/v1/ping", {"Origin": "https://evil.example"})

    assert response.status == 403 and code(body) == "bad_origin"
    assert response.getheader("Access-Control-Allow-Origin") is None


def test_requests_without_origin_get_no_cors_headers(make_server):
    server = make_server(cors=True)

    response, _, _ = call(server, "GET", "/v1/ping")

    assert response.status == 200
    assert response.getheader("Access-Control-Allow-Origin") is None
    assert response.getheader("Vary") is None


def test_without_the_cors_switch_options_stays_a_405(make_server):
    server = make_server(cors=False)

    response, body, _ = preflight(server)

    assert response.status == 405
    assert response.getheader("Access-Control-Allow-Origin") is None
    ok, _, _ = call(server, "GET", "/v1/ping", {"Origin": ORIGIN})
    assert ok.getheader("Access-Control-Allow-Origin") is None


def test_a_public_route_stays_public_with_a_query_string(make_server):
    server = make_server()

    response, body, _ = call(server, "POST", "/v1/pair?x=1", JSON, b"{}", token=None)

    assert response.status == 200 and body["who"] == "anonymous"
    assert server.calls == [("POST", "/v1/pair", "anonymous")]


def test_a_preflight_204_carries_no_bytes_after_the_headers(make_server):
    # http.client ignoriert bei 204 einen mitgesendeten Body: erst der Rohsocket zeigt ihn.
    import socket
    server = make_server(cors=True)
    request = (f"OPTIONS /v1/sync HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n"
               f"Origin: {ORIGIN}\r\nAccess-Control-Request-Method: POST\r\n"
               "Connection: close\r\n\r\n").encode()
    with socket.create_connection(("127.0.0.1", server.port), timeout=5) as sock:
        sock.sendall(request)
        raw = b""
        while chunk := sock.recv(4096):
            raw += chunk

    head, _, rest = raw.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.0 204") and rest == b""
    lines = [line.lower() for line in head.split(b"\r\n")]
    assert not any(line.startswith(b"content-type:") for line in lines)
    assert b"content-length: 0" in lines
