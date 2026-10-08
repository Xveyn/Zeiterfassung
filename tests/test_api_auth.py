# tests/test_api_auth.py
import hmac
import logging
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys

import pytest

from src import api_auth
from src.api_auth import (
    ALLOWED_METHODS, ANONYMOUS, SCOPE_LOCAL, SCOPE_MOBILE, TOKEN_FILENAME, AuthResult,
    Denied, Policy, Principal, authorize, authorize_public, generate_token,
    load_or_create_token, read_token, require_scope, rotate_token, single_token_verifier,
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


# --- Windows-Eigenheiten und Aufräumen -------------------------------------

def test_replace_is_retried_when_the_target_is_briefly_locked(tmp_path, monkeypatch):
    real_replace = os.replace
    calls = []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("kurz gesperrt (Virenscanner)")
        real_replace(src, dst)

    monkeypatch.setattr(api_auth.os, "replace", flaky)
    monkeypatch.setattr(api_auth.time, "sleep", lambda seconds: None)

    token = load_or_create_token(str(tmp_path))

    assert token is not None and len(calls) == 3
    assert (tmp_path / TOKEN_FILENAME).read_text(encoding="ascii") == token


def test_permanent_lock_gives_no_token_after_five_attempts(tmp_path, monkeypatch):
    calls = []

    def locked(src, dst):
        calls.append(1)
        raise PermissionError("dauerhaft gesperrt")

    monkeypatch.setattr(api_auth.os, "replace", locked)
    monkeypatch.setattr(api_auth.time, "sleep", lambda seconds: None)

    assert load_or_create_token(str(tmp_path)) is None
    assert len(calls) == 5
    assert list(tmp_path.iterdir()) == []


def test_failing_chmod_does_not_prevent_the_token(tmp_path, monkeypatch):
    def no_chmod(path, mode):
        raise OSError("chmod nicht möglich")

    monkeypatch.setattr(api_auth.os, "chmod", no_chmod)

    assert load_or_create_token(str(tmp_path)) is not None


def test_failing_cleanup_does_not_mask_the_original_error(tmp_path, monkeypatch):
    def boom(src, dst):
        raise OSError("replace failed")

    def no_remove(path):
        raise OSError("remove failed")

    monkeypatch.setattr(api_auth.os, "replace", boom)
    monkeypatch.setattr(api_auth.os, "remove", no_remove)

    # Direkt gegen den Schreiber: load_or_create_token würde beide OSError zu None
    # verschmelzen und den Test vakuös machen.
    with pytest.raises(OSError, match="replace failed"):
        api_auth._write_token_atomic(str(tmp_path / TOKEN_FILENAME), generate_token())


# --- Review-Fixes: Bestandsdatei, Länge, gitignore, Log ---------------------

@pytest.mark.skipif(sys.platform == "win32",
                    reason="chmod 0600 ist unter Windows ein No-op (dort greift die ACL)")
def test_existing_token_file_with_loose_mode_is_tightened_on_load(tmp_path):
    path = tmp_path / TOKEN_FILENAME
    token = generate_token()
    path.write_text(token, encoding="ascii")
    os.chmod(path, 0o644)                      # Editor/echo > api-token mit umask 022

    assert load_or_create_token(str(tmp_path)) == token
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_existing_token_file_is_acl_hardened_on_load(tmp_path, monkeypatch):
    path = tmp_path / TOKEN_FILENAME
    path.write_text(generate_token(), encoding="ascii")
    calls = []
    monkeypatch.setattr(api_auth, "harden_windows_acl", calls.append)

    load_or_create_token(str(tmp_path))

    assert calls == [str(path)]


@pytest.mark.parametrize("length", [31, 32, 42, 44, 128, 129])
def test_token_of_the_wrong_length_is_replaced(tmp_path, length):
    path = tmp_path / TOKEN_FILENAME
    weak = "a" * length
    path.write_text(weak, encoding="ascii")

    token = load_or_create_token(str(tmp_path))

    assert token != weak and _TOKEN_RE.fullmatch(token)
    assert path.read_text(encoding="ascii") == token


def test_token_of_exactly_43_characters_is_kept(tmp_path):
    existing = "a" * 43
    (tmp_path / TOKEN_FILENAME).write_text(existing, encoding="ascii")

    assert load_or_create_token(str(tmp_path)) == existing


@pytest.mark.skipif(shutil.which("git") is None, reason="git nicht verfügbar")
@pytest.mark.parametrize("name", ["api-token", "api-token.corrupt-20261006",
                                  ".api-token-ab12.tmp"])
def test_api_token_files_are_gitignored(name):
    # Im Dev-Modus ist das Repo-Root der Datenordner: ein `git add -A` darf
    # kein Bearer-Token committen.
    root = pathlib.Path(__file__).resolve().parent.parent
    result = subprocess.run(["git", "check-ignore", "-q", name], cwd=root)
    assert result.returncode == 0, f"{name} ist nicht in .gitignore"


def test_secrets_never_appear_in_log_output(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    leaked = "GEHEIM" * 7                      # ungültiger Dateiinhalt, 42 Zeichen
    (tmp_path / TOKEN_FILENAME).write_text(leaked, encoding="ascii")

    fresh = load_or_create_token(str(tmp_path))                 # ungültig → neu
    load_or_create_token(str(tmp_path / "gibt-es-nicht"))       # nicht schreibbar
    with pytest.raises(OSError):
        rotate_token(str(tmp_path / "gibt-es-nicht"))

    assert caplog.text                                           # es wurde geloggt
    assert leaked not in caplog.text and fresh not in caplog.text


# --- Rotation ---------------------------------------------------------------

def test_rotate_token_replaces_file_and_returns_the_new_token(tmp_path):
    old = load_or_create_token(str(tmp_path))

    new = rotate_token(str(tmp_path))

    assert new != old and _TOKEN_RE.fullmatch(new)
    assert (tmp_path / TOKEN_FILENAME).read_text(encoding="ascii") == new


def test_failed_rotation_keeps_the_old_token(tmp_path, monkeypatch):
    old = load_or_create_token(str(tmp_path))

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(api_auth.os, "replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        rotate_token(str(tmp_path))
    monkeypatch.undo()

    assert (tmp_path / TOKEN_FILENAME).read_text(encoding="ascii") == old
    assert [p.name for p in tmp_path.iterdir()] == [TOKEN_FILENAME]


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


@pytest.mark.parametrize("method", ["get", "Get", "put", "pOST", "delete", "poſt"])
def test_method_names_are_case_sensitive(method):
    # RFC 9110: Methoden sind case-sensitive. `authorize` und das Routing
    # (exakter Vergleich) sehen sonst zwei verschiedene Anfragen — und mit
    # schreibenden Methoden zählt das.
    result = call(method)
    assert (result.status, result.code) == (405, "method_not_allowed")


@pytest.mark.parametrize("method", [None, 5, b"GET"])
def test_non_string_methods_are_405_not_an_exception(method):
    result = authorize(method, {"Host": GOOD_HOST, "Authorization": f"Bearer {TOKEN}"},
                       POLICY, VERIFY)
    assert result.status == 405


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


def test_sec_fetch_site_is_checked_before_the_token():
    result = call(extra={"Sec-Fetch-Site": "cross-site"}, drop=("Authorization",))
    assert (result.status, result.code) == (403, "browser_request")


def test_overlong_bearer_value_never_reaches_the_verifier():
    seen = []

    def spy(candidate):
        seen.append(candidate)
        return None

    base = {"Host": GOOD_HOST}
    authorize("GET", {**base, "Authorization": "Bearer " + "A" * 10_000}, POLICY, spy)
    assert seen == []
    authorize("GET", {**base, "Authorization": "Bearer " + "A" * 50}, POLICY, spy)
    assert seen == ["A" * 50]


def test_origin_is_checked_before_the_token():
    result = call(extra={"Origin": "https://evil.example"}, drop=("Authorization",))
    assert result.status == 403


# --- Verifier und Scope -----------------------------------------------------

def test_verifier_accepts_only_the_exact_token():
    assert VERIFY(TOKEN) is not None
    assert VERIFY(TOKEN + "x") is None
    assert VERIFY("") is None


def test_verifier_refuses_to_be_built_without_a_token():
    with pytest.raises(ValueError):
        single_token_verifier("")


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


# --- read_token: rein lesend (PR 3, Settings-Tab „Token kopieren") --------------

def test_read_token_returns_the_stored_token(tmp_path):
    token = generate_token()
    (tmp_path / TOKEN_FILENAME).write_text(token, encoding="ascii")

    assert read_token(str(tmp_path)) == token


def test_read_token_tolerates_a_trailing_newline(tmp_path):
    token = generate_token()
    (tmp_path / TOKEN_FILENAME).write_bytes(token.encode("ascii") + b"\r\n")

    assert read_token(str(tmp_path)) == token


def test_read_token_without_a_file_is_none_and_creates_nothing(tmp_path):
    assert read_token(str(tmp_path)) is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("content", [b"", b"zu-kurz", b"x" * 5000, b"\xff\xfe" * 30,
                                     b"a" * 42, b"a" * 44])
def test_read_token_with_invalid_content_is_none_and_leaves_the_file_alone(tmp_path, content):
    path = tmp_path / TOKEN_FILENAME
    path.write_bytes(content)

    assert read_token(str(tmp_path)) is None
    assert path.read_bytes() == content


def test_read_token_unreadable_is_none(tmp_path, monkeypatch):
    (tmp_path / TOKEN_FILENAME).write_text(generate_token(), encoding="ascii")
    real_open = open

    def fake_open(file, *args, **kwargs):
        if os.fspath(file).endswith(TOKEN_FILENAME):
            raise PermissionError("denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(api_auth, "open", fake_open, raising=False)

    assert read_token(str(tmp_path)) is None


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Dateimodi sind unter Windows kein Maßstab")
def test_read_token_does_not_touch_the_file_mode(tmp_path):
    path = tmp_path / TOKEN_FILENAME
    path.write_text(generate_token(), encoding="ascii")
    os.chmod(path, 0o644)

    read_token(str(tmp_path))

    assert stat.S_IMODE(os.stat(path).st_mode) == 0o644


def test_read_token_never_hardens_the_file(tmp_path, monkeypatch):
    (tmp_path / TOKEN_FILENAME).write_text(generate_token(), encoding="ascii")
    calls = []
    monkeypatch.setattr(api_auth, "harden_windows_acl", calls.append)

    read_token(str(tmp_path))

    assert calls == []                  # `icacls` bis 15 s: nichts für „nur kopieren"


# --- Härtung aus dem Review von PR 1 (#233) ------------------------------------------

def test_a_token_file_with_a_utf8_bom_is_still_the_token(tmp_path):
    token = generate_token()
    (tmp_path / TOKEN_FILENAME).write_bytes(b"\xef\xbb\xbf" + token.encode("ascii") + b"\r\n")

    assert load_or_create_token(str(tmp_path)) == token
    assert read_token(str(tmp_path)) == token


@pytest.mark.parametrize("content", [
    "utf16", "nul-in-the-middle", "non-ascii-in-the-middle", "bom-then-junk",
])
def test_a_token_file_that_is_not_ascii_is_not_a_token_and_never_crashes(tmp_path, content):
    token = generate_token()
    data = {
        "utf16": b"\xff\xfe" + token.encode("utf-16-le"),
        "nul-in-the-middle": token[:20].encode() + b"\x00" + token[21:].encode(),
        "non-ascii-in-the-middle": token[:20].encode() + b"\xc3\xa4" + token[22:].encode(),
        "bom-then-junk": b"\xef\xbb\xbf" + b"zu-kurz",
    }[content]
    (tmp_path / TOKEN_FILENAME).write_bytes(data)

    assert read_token(str(tmp_path)) is None
    fresh = load_or_create_token(str(tmp_path))
    assert fresh is not None and fresh != token


def test_an_auth_result_with_status_200_but_no_principal_is_not_ok():
    assert not AuthResult(200, "ok").ok
    assert not AuthResult(200, "ok", None).ok


def test_the_host_header_is_trimmed_of_http_whitespace_only():
    policy = Policy.loopback(17653)
    verify = single_token_verifier("a" * 43)
    ok = authorize("GET", {"Host": " \t127.0.0.1:17653 \t", "Authorization": "Bearer " + "a" * 43},
                   policy, verify)
    assert ok.status == 200
    for junk in ("\u00a0127.0.0.1:17653", "127.0.0.1:17653\u2028", "\x85127.0.0.1:17653"):
        assert authorize("GET", {"Host": junk, "Authorization": "Bearer " + "a" * 43},
                         policy, verify).code == "bad_host"


class _WriteSpy:
    """Reicht alles an die echte Datei durch und merkt sich, wann geschrieben wird."""

    def __init__(self, handle, events):
        self._handle, self._events = handle, events

    def write(self, data):
        self._events.append("write")
        return self._handle.write(data)

    def __enter__(self):
        self._handle.__enter__()
        return self

    def __exit__(self, *exc):
        return self._handle.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._handle, name)


def test_the_token_is_hardened_before_it_is_written(tmp_path, monkeypatch):
    events = []
    real_fdopen, real_harden = os.fdopen, api_auth.harden_windows_acl
    monkeypatch.setattr(os, "fdopen", lambda *a, **k: _WriteSpy(real_fdopen(*a, **k), events))
    monkeypatch.setattr(api_auth, "harden_windows_acl",
                        lambda path: (events.append("harden"), real_harden(path))[1])

    token = load_or_create_token(str(tmp_path))

    assert events == ["harden", "write"]                      # nie umgekehrt
    assert (tmp_path / TOKEN_FILENAME).read_text(encoding="ascii") == token


# --- Denied und öffentliche Routen (#221) ------------------------------------------------------

LAN_POLICY = Policy(allowed_hosts=frozenset({"192.168.1.20:17654"}),
                    allowed_origins=frozenset({"https://xveyn.github.io"}),
                    bind_host="192.168.1.20")
LAN_HEADERS = {"Host": "192.168.1.20:17654", "Origin": "https://xveyn.github.io",
               "Authorization": "Bearer abc", "Content-Type": "application/json"}


@pytest.mark.parametrize("code", ["token_expired", "token_revoked"])
def test_a_denied_verdict_becomes_a_401_with_its_own_code(code):
    result = authorize("POST", LAN_HEADERS, LAN_POLICY, lambda token: Denied(code))
    assert (result.status, result.code, result.principal) == (401, code, None)


def test_an_unknown_token_is_still_plain_unauthorized():
    result = authorize("POST", LAN_HEADERS, LAN_POLICY, lambda token: None)
    assert (result.status, result.code) == (401, "unauthorized")


def test_a_principal_with_the_mobile_scope_passes():
    principal = Principal("device-0001", frozenset({SCOPE_MOBILE}))
    result = authorize("POST", LAN_HEADERS, LAN_POLICY, lambda token: principal)
    assert result.ok and result.principal is principal
    assert require_scope(principal, SCOPE_MOBILE).ok
    assert require_scope(principal, SCOPE_LOCAL).status == 403


def test_the_gates_still_run_before_the_verifier():
    called = []

    def verifier(token):
        called.append(token)
        return Denied("token_expired")

    wrong_host = dict(LAN_HEADERS, Host="evil.example:17654")
    assert authorize("POST", wrong_host, LAN_POLICY, verifier).code == "bad_host"
    assert authorize("POST", dict(LAN_HEADERS, Origin="https://evil.example"),
                     LAN_POLICY, verifier).code == "bad_origin"
    assert called == []


def test_public_authorize_needs_no_token_and_yields_the_anonymous_principal():
    headers = {k: v for k, v in LAN_HEADERS.items() if k != "Authorization"}

    result = authorize_public("POST", headers, LAN_POLICY)

    assert result.ok and result.principal is ANONYMOUS
    assert ANONYMOUS.scopes == frozenset()
    assert require_scope(ANONYMOUS, SCOPE_MOBILE).status == 403


def test_public_authorize_ignores_an_authorization_header():
    assert authorize_public("POST", LAN_HEADERS, LAN_POLICY).ok


@pytest.mark.parametrize("override,expected", [
    ({"Host": "evil.example:17654"}, (403, "bad_host")),
    ({"Origin": "https://evil.example"}, (403, "bad_origin")),
    ({"Sec-Fetch-Site": "cross-site"}, (403, "browser_request")),
    ({"Content-Type": "text/plain"}, (415, "unsupported_media_type")),
])
def test_public_authorize_keeps_the_other_gates(override, expected):
    headers = dict(LAN_HEADERS, **override)
    result = authorize_public("POST", headers, LAN_POLICY)
    assert (result.status, result.code) == expected and result.principal is None


def test_public_authorize_rejects_unknown_methods():
    assert authorize_public("PATCH", LAN_HEADERS, LAN_POLICY).status == 405
    assert authorize_public("OPTIONS", LAN_HEADERS, LAN_POLICY).status == 405
