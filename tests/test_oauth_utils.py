"""Tests für die zentralisierten OAuth-Helfer (Issue #47).

write_token: atomar + 0o600. discard_token_for_scope_upgrade: löscht den Token
nur, wenn die gespeicherten Scopes die angeforderten nicht abdecken."""

import json
import os
import platform
import stat
import subprocess
from unittest.mock import MagicMock

import pytest

from src.oauth_utils import write_token, discard_token_for_scope_upgrade


def _windows_env(monkeypatch, events, *, run=None, domain="MACHINE", user="sven"):
    """Stellt eine Windows-Umgebung nach und protokolliert die Reihenfolge von
    icacls-Aufruf und os.replace in `events`."""
    def default_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_run(cmd, **kwargs):
        events.append(("icacls", list(cmd)))
        return (run or default_run)(cmd, **kwargs)

    real_replace = os.replace

    def tracking_replace(src, dst):
        events.append(("replace", src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(os, "replace", tracking_replace)
    if domain is None:
        monkeypatch.delenv("USERDOMAIN", raising=False)
    else:
        monkeypatch.setenv("USERDOMAIN", domain)
    if user is None:
        monkeypatch.delenv("USERNAME", raising=False)
    else:
        monkeypatch.setenv("USERNAME", user)


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


def test_write_token_retries_transient_permission_error(tmp_path, monkeypatch):
    """Regression #135: ein transienter Windows-PermissionError (AV-Scan/offenes
    Handle blockiert os.replace, WinError 5/32) wird per Retry überbrückt — der
    Token landet trotzdem sauber auf der Platte."""
    path = str(tmp_path / "token.json")
    creds = MagicMock()
    creds.to_json.return_value = '{"token": "abc"}'

    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(13, "Zugriff verweigert")
        return real_replace(src, dst)

    monkeypatch.setattr("src.oauth_utils.os.replace", flaky_replace)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    write_token(creds, path)

    assert calls["n"] == 2  # ein Fehlschlag, dann Erfolg
    with open(path) as f:
        assert f.read() == '{"token": "abc"}'


def test_write_token_reraises_persistent_permission_error(tmp_path, monkeypatch):
    """Bleibt der PermissionError dauerhaft, werden alle Versuche ausgeschöpft
    und der Fehler durchgereicht (nicht still verschluckt); keine Temp-Reste."""
    path = str(tmp_path / "token.json")
    creds = MagicMock()
    creds.to_json.return_value = "{}"

    calls = {"n": 0}

    def always_fail(src, dst):
        calls["n"] += 1
        raise PermissionError(13, "Zugriff verweigert")

    monkeypatch.setattr("src.oauth_utils.os.replace", always_fail)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    with pytest.raises(PermissionError):
        write_token(creds, path)

    assert calls["n"] > 1  # es wurde wiederholt, nicht nur einmal versucht
    assert os.listdir(str(tmp_path)) == []  # tmp aufgeräumt, kein token.json


def test_write_token_hardens_acl_on_windows_before_replace(tmp_path, monkeypatch):
    """Audit M8: chmod ist auf Windows ein No-op — dort bekommt die Datei
    stattdessen eine explizite ACL nur für den aktuellen Benutzer (icacls,
    Vererbung entfernt). Gehärtet wird die Temp-Datei VOR dem os.replace, damit
    token.json nie kurzzeitig mit geerbten Rechten sichtbar ist."""
    path = str(tmp_path / "token.json")
    creds = MagicMock()
    creds.to_json.return_value = "{}"
    events = []
    _windows_env(monkeypatch, events)

    write_token(creds, path)

    assert [e[0] for e in events] == ["icacls", "replace"]
    argv = events[0][1]
    assert argv[0] == "icacls"
    assert argv[1].endswith(".tmp")  # die Temp-Datei, nicht das fertige token.json
    assert "/inheritance:r" in argv  # geerbte ACEs (u.a. Administratoren) raus
    assert "/grant:r" in argv
    assert "MACHINE\\sven:(F)" in argv


def test_write_token_grants_bare_username_without_userdomain(tmp_path, monkeypatch):
    """Ohne USERDOMAIN (exotische Umgebung) bleibt der nackte Benutzername —
    icacls löst den lokal auf, statt dass das Härten ganz ausfällt."""
    path = str(tmp_path / "token.json")
    creds = MagicMock()
    creds.to_json.return_value = "{}"
    events = []
    _windows_env(monkeypatch, events, domain=None)

    write_token(creds, path)

    assert "sven:(F)" in events[0][1]


def test_write_token_skips_hardening_without_username(tmp_path, monkeypatch):
    """Ohne benennbaren Principal wird nicht geraten: kein icacls-Aufruf, und
    der Token landet trotzdem auf der Platte (Persistenz geht vor Härtung)."""
    path = str(tmp_path / "token.json")
    creds = MagicMock()
    creds.to_json.return_value = '{"token": "abc"}'
    events = []
    _windows_env(monkeypatch, events, domain=None, user=None)

    write_token(creds, path)

    assert [e[0] for e in events] == ["replace"]
    with open(path) as f:
        assert f.read() == '{"token": "abc"}'


def test_write_token_does_not_call_icacls_off_windows(tmp_path, monkeypatch):
    """Auf POSIX erledigt das chmod 0600 die Arbeit — kein icacls-Prozess."""
    path = str(tmp_path / "token.json")
    creds = MagicMock()
    creds.to_json.return_value = "{}"
    events = []
    _windows_env(monkeypatch, events)
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    write_token(creds, path)

    assert [e[0] for e in events] == ["replace"]


def test_write_token_survives_missing_icacls(tmp_path, monkeypatch):
    """Fehlt icacls (abgespecktes Windows, PATH kaputt), darf die
    Token-Persistenz nicht scheitern — Härtung ist Beiwerk, nicht Bedingung."""
    path = str(tmp_path / "token.json")
    creds = MagicMock()
    creds.to_json.return_value = '{"token": "abc"}'

    def boom(cmd, **kwargs):
        raise FileNotFoundError(2, "icacls nicht gefunden")

    events = []
    _windows_env(monkeypatch, events, run=boom)

    write_token(creds, path)

    with open(path) as f:
        assert f.read() == '{"token": "abc"}'


def test_write_token_logs_warning_when_icacls_fails(tmp_path, monkeypatch, caplog):
    """Ein icacls-Fehlschlag wird geloggt statt still verschluckt (N13-Muster) —
    der Token wird trotzdem geschrieben."""
    path = str(tmp_path / "token.json")
    creds = MagicMock()
    creds.to_json.return_value = "{}"

    def failing(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 5, "", "Zugriff verweigert")

    events = []
    _windows_env(monkeypatch, events, run=failing)

    with caplog.at_level("WARNING"):
        write_token(creds, path)

    assert os.path.exists(path)
    assert any("icacls" in r.message.lower() or "acl" in r.message.lower()
               for r in caplog.records), caplog.text


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
