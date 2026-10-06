# tests/test_api_auth.py
import os
import re
import stat
import sys

import pytest

from src import api_auth
from src.api_auth import (
    TOKEN_FILENAME, generate_token, load_or_create_token, rotate_token,
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
