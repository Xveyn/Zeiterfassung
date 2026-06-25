"""Tests für die zentralisierten OAuth-Helfer (Issue #47).

write_token: atomar + 0o600. discard_token_for_scope_upgrade: löscht den Token
nur, wenn die gespeicherten Scopes die angeforderten nicht abdecken."""

import json
import os
import stat
from unittest.mock import MagicMock

from src.oauth_utils import write_token, discard_token_for_scope_upgrade


def test_write_token_writes_creds_json(tmp_path):
    path = str(tmp_path / "token.json")
    creds = MagicMock()
    creds.to_json.return_value = '{"token": "abc"}'

    write_token(creds, path)

    with open(path) as f:
        assert f.read() == '{"token": "abc"}'


def test_write_token_sets_0o600_permissions(tmp_path):
    path = str(tmp_path / "token.json")
    creds = MagicMock()
    creds.to_json.return_value = "{}"

    write_token(creds, path)

    mode = stat.S_IMODE(os.stat(path).st_mode)
    # Auf POSIX exakt 0o600; auf Windows ignoriert das OS die Permission-Bits,
    # daher nur dort prüfen.
    if os.name == "posix":
        assert mode == 0o600


def test_write_token_atomic_no_leftover_tmp_files(tmp_path):
    path = str(tmp_path / "token.json")
    creds = MagicMock()
    creds.to_json.return_value = '{"token": "abc"}'

    write_token(creds, path)

    names = os.listdir(str(tmp_path))
    assert names == ["token.json"], f"unerwartete Temp-Reste: {names}"


def test_write_token_overwrites_existing(tmp_path):
    path = str(tmp_path / "token.json")
    with open(path, "w") as f:
        f.write("old")
    creds = MagicMock()
    creds.to_json.return_value = "new"

    write_token(creds, path)

    with open(path) as f:
        assert f.read() == "new"


def _write_token_file(path, scopes):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"token": "t", "scopes": scopes}, f)


def test_discard_returns_false_when_all_scopes_covered(tmp_path):
    path = str(tmp_path / "token.json")
    _write_token_file(path, ["a", "b", "c"])

    assert discard_token_for_scope_upgrade(path, ["a", "b"]) is False
    assert os.path.exists(path)


def test_discard_removes_token_when_scope_missing(tmp_path):
    path = str(tmp_path / "token.json")
    _write_token_file(path, ["a"])

    assert discard_token_for_scope_upgrade(path, ["a", "b"]) is True
    assert not os.path.exists(path)


def test_discard_returns_false_on_unreadable_token(tmp_path):
    """Defektes/leeres JSON darf den Token nicht löschen — spiegelt das
    bisherige `except: pass` (Token unangetastet, kein erzwungener Flow)."""
    path = str(tmp_path / "token.json")
    with open(path, "w") as f:
        f.write("not json")

    assert discard_token_for_scope_upgrade(path, ["a"]) is False
    assert os.path.exists(path)


def test_discard_treats_missing_scopes_key_as_no_coverage(tmp_path):
    path = str(tmp_path / "token.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"token": "t"}, f)

    assert discard_token_for_scope_upgrade(path, ["a"]) is True
    assert not os.path.exists(path)
