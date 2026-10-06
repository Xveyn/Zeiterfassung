# tests/test_api_auth.py
import hmac
import os
import re
import stat
import sys

import pytest

from src import api_auth
from src.api_auth import (
    ALLOWED_METHODS, SCOPE_LOCAL, TOKEN_FILENAME, AuthResult, Policy, Principal,
    authorize, generate_token, load_or_create_token, require_scope, rotate_token,
    single_token_verifier,
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")


# --- Token erzeugen ---------------------------------------------------------

def test_generate_token_is_urlsafe_and_256_bit():
    assert _TOKEN_RE.fullmatch(generate_token())


def test_generate_token_is_unique():
    assert len({generate_token() for _ in range(50)}) == 50


# --- Datei: anlegen, laden, härten -----------------------------------------

def test_load_or_create_creates_file_and_returns_token(tmp_path):
    token = load_or_create_token(str(tmp_path))

    assert token is not None and _TOKEN_RE.fullmatch(token)
    assert (tmp_path / TOKEN_FILENAME).read_text(encoding="ascii") == token


def test_load_or_create_is_stable_across_calls(tmp_path):
    first = load_or_create_token(str(tmp_path))
    assert load_or_create_token(str(tmp_path)) == first


@pytest.mark.skipif(sys.platform == "win32",
                    reason="chmod 0600 ist unter Windows ein No-op (dort greift die ACL)")
def test_token_file_is_owner_only(tmp_path):
    load_or_create_token(str(tmp_path))

    mode = stat.S_IMODE(os.stat(tmp_path / TOKEN_FILENAME).st_mode)
    assert mode == 0o600


def test_acl_hardening_runs_on_temp_file_before_replace(tmp_path, monkeypatch):
    seen = []

    def fake_harden(path):
        seen.append((os.path.basename(path),
                     (tmp_path / TOKEN_FILENAME).exists()))

    monkeypatch.setattr(api_auth, "harden_windows_acl", fake_harden)

    load_or_create_token(str(tmp_path))

    assert len(seen) == 1
    name, target_exists = seen[0]
    assert name.startswith(".api-token-") and name.endswith(".tmp")
    assert target_exists is False      # gehärtet, BEVOR die Datei sichtbar wird


# --- Review Focus 3: beschädigte oder von Hand bearbeitete Datei -----------

def test_trailing_newline_is_tolerated(tmp_path):
    token = generate_token()
    (tmp_path / TOKEN_FILENAME).write_bytes(token.encode("ascii") + b"\r\n")

    assert load_or_create_token(str(tmp_path)) == token


@pytest.mark.parametrize("content", [
    b"",
    b"zu-kurz",
    b"x" * 5000,
    b"\xff\xfe" * 30,
    b"mit leerzeichen " + b"a" * 40,
])
def test_invalid_token_file_is_replaced_by_a_fresh_token(tmp_path, content):
    path = tmp_path / TOKEN_FILENAME
    path.write_bytes(content)

    token = load_or_create_token(str(tmp_path))

    assert token is not None and _TOKEN_RE.fullmatch(token)
    assert path.read_text(encoding="ascii") == token


# --- Fail-closed ------------------------------------------------------------

def test_unreadable_token_file_gives_no_token_and_is_not_overwritten(tmp_path, monkeypatch):
    path = tmp_path / TOKEN_FILENAME
    original = generate_token()
    path.write_text(original, encoding="ascii")
    real_open = open

    def fake_open(file, *args, **kwargs):
        if os.fspath(file) == str(path):
            raise PermissionError("denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(api_auth, "open", fake_open, raising=False)

    assert load_or_create_token(str(tmp_path)) is None
    monkeypatch.undo()
    assert path.read_text(encoding="ascii") == original


def test_unwritable_directory_gives_no_token(tmp_path):
    assert load_or_create_token(str(tmp_path / "gibt-es-nicht")) is None


def test_failed_replace_gives_no_token_and_leaves_no_temp_file(tmp_path, monkeypatch):
    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(api_auth.os, "replace", boom)

    assert load_or_create_token(str(tmp_path)) is None
    assert list(tmp_path.iterdir()) == []


def test_no_temp_files_remain_after_success(tmp_path):
    load_or_create_token(str(tmp_path))
    rotate_token(str(tmp_path))

    assert [p.name for p in tmp_path.iterdir()] == [TOKEN_FILENAME]


# --- Rotation ---------------------------------------------------------------

def test_rotate_token_replaces_file_and_returns_the_new_token(tmp_path):
    old = load_or_create_token(str(tmp_path))

    new = rotate_token(str(tmp_path))

    assert new != old and _TOKEN_RE.fullmatch(new)
    assert (tmp_path / TOKEN_FILENAME).read_text(encoding="ascii") == new


def test_rotate_token_raises_when_it_cannot_write(tmp_path):
    with pytest.raises(OSError):
        rotate_token(str(tmp_path / "gibt-es-nicht"))


# --- authorize --------------------------------------------------------------

PORT = 17653
GOOD_HOST = f"127.0.0.1:{PORT}"
TOKEN = "T" * 43
VERIFY = single_token_verifier(TOKEN)
POLICY = Policy.loopback(PORT)
JSON_CT = {"Content-Type": "application/json"}


def call(method="GET", extra=None, drop=(), policy=POLICY):
    headers = {"Host": GOOD_HOST, "Authorization": f"Bearer {TOKEN}"}
    headers.update(extra or {})
    for name in drop:
        headers.pop(name, None)
    return authorize(method, headers, policy, VERIFY)


def test_policy_loopback_allows_ip_and_localhost_with_port():
    assert POLICY.allowed_hosts == {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
    assert POLICY.allowed_origins == frozenset()
    assert POLICY.bind_host == "127.0.0.1"


def test_valid_get_is_accepted_with_local_scope():
    result = call()

    assert result.ok and result.status == 200
    assert result.principal is not None
    assert SCOPE_LOCAL in result.principal.scopes


@pytest.mark.parametrize("method", ["PUT", "POST"])
def test_valid_write_with_json_is_accepted(method):
    assert call(method, JSON_CT).ok


def test_delete_needs_no_content_type():
    assert call("DELETE").ok


def test_method_name_is_case_insensitive():
    assert call("get").ok


def test_header_names_are_case_insensitive():
    result = authorize("GET", {"host": GOOD_HOST, "AUTHORIZATION": f"Bearer {TOKEN}"},
                       POLICY, VERIFY)
    assert result.ok


# --- Methoden ---------------------------------------------------------------

@pytest.mark.parametrize("method", ["OPTIONS", "HEAD", "PATCH", "TRACE", "CONNECT"])
def test_other_methods_are_405_even_with_a_valid_token(method):
    result = call(method)
    assert (result.status, result.code) == (405, "method_not_allowed")


def test_options_never_reveals_anything_to_unauthenticated_callers():
    result = authorize("OPTIONS", {"Host": "evil.example"}, POLICY, VERIFY)
    assert result.status == 405


def test_allowed_methods_constant():
    assert ALLOWED_METHODS == {"GET", "PUT", "POST", "DELETE"}


# --- Host (Review Focus 1) --------------------------------------------------

@pytest.mark.parametrize("host", [
    "evil.example",
    "evil.example:17653",
    "127.0.0.1",                        # ohne Port
    "127.0.0.1:1",
    "127.0.0.1:17653.evil.example",     # Suffix
    "localhost:17653.evil.example",
    "",
])
def test_wrong_host_is_403(host):
    result = call(extra={"Host": host})
    assert (result.status, result.code) == (403, "bad_host")


def test_missing_host_is_403():
    result = call(drop=("Host",))
    assert (result.status, result.code) == (403, "bad_host")


@pytest.mark.parametrize("host", [f"localhost:{PORT}", f"LOCALHOST:{PORT}",
                                  f"  127.0.0.1:{PORT}  "])
def test_host_is_case_insensitive_and_trimmed(host):
    assert call(extra={"Host": host}).ok


# --- Origin (Review Focus 4) ------------------------------------------------

@pytest.mark.parametrize("origin", ["https://evil.example", "null", "",
                                    f"http://{GOOD_HOST}"])
def test_any_origin_is_403_while_the_allowlist_is_empty(origin):
    result = call(extra={"Origin": origin})
    assert (result.status, result.code) == (403, "bad_origin")


def test_origin_on_the_allowlist_passes_and_others_still_fail():
    policy = Policy(allowed_hosts=POLICY.allowed_hosts,
                    allowed_origins=frozenset({"https://pwa.example"}))

    assert call(extra={"Origin": "https://pwa.example"}, policy=policy).ok
    assert call(extra={"Origin": "https://other.example"}, policy=policy).status == 403
    assert call(extra={"Origin": "null"}, policy=policy).status == 403


# --- Sec-Fetch-Site ---------------------------------------------------------

@pytest.mark.parametrize("name", ["Sec-Fetch-Site", "SEC-FETCH-SITE"])
@pytest.mark.parametrize("value", ["cross-site", "same-origin", "none", ""])
def test_sec_fetch_site_is_403(name, value):
    result = call(extra={name: value})
    assert (result.status, result.code) == (403, "browser_request")


# --- Bearer (Review Focus 2) ------------------------------------------------

@pytest.mark.parametrize("authorization", [
    "Basic abc",
    "Bearer",
    "Bearer ",
    "Bearer    ",
    f"Bearer {TOKEN[:-1]}",              # Präfix
    f"Bearer {TOKEN}x",
    "Bearer ünïcödé-töken",
    "Bearer " + "A" * 10_000,
    f"Bearer {TOKEN} extra",
    TOKEN,                               # ohne Schema
    "",
])
def test_bad_authorization_is_401_and_never_raises(authorization):
    result = call(extra={"Authorization": authorization})
    assert (result.status, result.code) == (401, "unauthorized")
    assert result.principal is None


def test_missing_authorization_is_401():
    assert call(drop=("Authorization",)).status == 401


@pytest.mark.parametrize("authorization", [f"bearer {TOKEN}", f"BEARER {TOKEN}",
                                           f"Bearer   {TOKEN}  "])
def test_scheme_is_case_insensitive_and_whitespace_is_trimmed(authorization):
    assert call(extra={"Authorization": authorization}).ok


# --- Content-Type (Review Focus 5) -----------------------------------------

@pytest.mark.parametrize("method", ["PUT", "POST"])
@pytest.mark.parametrize("content_type", [
    None,
    "text/plain",
    "application/x-www-form-urlencoded",
    "multipart/form-data; boundary=x",
    "application/jsonx",
    "application/json-patch+json",
    "json",
])
def test_writes_need_application_json(method, content_type):
    extra = {} if content_type is None else {"Content-Type": content_type}
    result = call(method, extra)
    assert (result.status, result.code) == (415, "unsupported_media_type")


@pytest.mark.parametrize("content_type", ["application/json", "Application/JSON",
                                          "application/json; charset=utf-8",
                                          " application/json ;charset=UTF-8"])
def test_json_content_type_variants_are_accepted(content_type):
    assert call("PUT", {"Content-Type": content_type}).ok


def test_get_ignores_content_type():
    assert call("GET", {"Content-Type": "text/plain"}).ok


# --- Reihenfolge ------------------------------------------------------------

def test_host_is_checked_before_the_token():
    result = call(extra={"Host": "evil.example"}, drop=("Authorization",))
    assert result.status == 403


def test_token_is_checked_before_the_content_type():
    result = call("PUT", {"Content-Type": "text/plain"}, drop=("Authorization",))
    assert result.status == 401


def test_origin_is_checked_before_the_token():
    result = call(extra={"Origin": "https://evil.example"}, drop=("Authorization",))
    assert result.status == 403


# --- Verifier und Scope -----------------------------------------------------

def test_verifier_accepts_only_the_exact_token():
    assert VERIFY(TOKEN) is not None
    assert VERIFY(TOKEN + "x") is None
    assert VERIFY("") is None


def test_verifier_uses_constant_time_comparison(monkeypatch):
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(api_auth.hmac, "compare_digest", spy)

    VERIFY("irgendwas")

    assert len(calls) == 1
    assert all(isinstance(x, bytes) for x in calls[0])


def test_verifier_survives_lone_surrogates():
    assert VERIFY("\ud800abc") is None


def test_require_scope_checks_membership():
    local = Principal("local", frozenset({SCOPE_LOCAL}))
    mobile = Principal("pixel", frozenset({"mobile-sync"}))

    assert require_scope(local, SCOPE_LOCAL).ok
    denied = require_scope(mobile, SCOPE_LOCAL)
    assert (denied.status, denied.code) == (403, "insufficient_scope")


def test_results_never_contain_the_token():
    for result in (call(), call(extra={"Authorization": f"Bearer {TOKEN}x"}),
                   call(extra={"Host": "evil.example"})):
        assert TOKEN not in repr(result)
        assert TOKEN not in result.code


def test_auth_result_ok_follows_status():
    assert AuthResult(200, "ok", Principal("p", frozenset())).ok
    assert not AuthResult(401, "unauthorized").ok
