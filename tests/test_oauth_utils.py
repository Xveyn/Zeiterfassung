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

from src.oauth_utils import write_token, discard_token_for_scope_upgrade, read_granted_scopes


def _windows_env(monkeypatch, events, *, run=None):
    """Stellt eine Windows-Umgebung nach und protokolliert die Reihenfolge von
    icacls-Aufruf und os.replace in `events`. Das Verhalten von icacls selbst
    (Principal-Ableitung, Fehlerpfade) prüft `tests/test_secure_file.py`."""
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
    monkeypatch.setenv("USERDOMAIN", "MACHINE")
    monkeypatch.setenv("USERNAME", "sven")


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


def test_discard_keeps_token_when_scopes_field_is_not_a_list(tmp_path):
    """Ein `scopes`-Feld, das keine Liste ist, gilt als unbrauchbar (nicht als
    „keine Scopes"): read_granted_scopes liefert None, und konservativ bleibt
    der Token liegen, statt einen womöglich gültigen wegzuwerfen. Vor der
    Umstellung auf read_granted_scopes wurde er hier gelöscht — die Änderung
    ist beabsichtigt und wird hier festgehalten."""
    path = str(tmp_path / "token.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"token": "t", "scopes": "gmail.send"}, f)

    assert discard_token_for_scope_upgrade(path, ["gmail.send"]) is False
    assert os.path.exists(path)


def test_read_granted_scopes_returns_the_list(tmp_path):
    path = str(tmp_path / "token.json")
    _write_token_file(path, ["a", "b"])

    assert read_granted_scopes(path) == ["a", "b"]


def test_read_granted_scopes_returns_none_for_missing_file(tmp_path):
    assert read_granted_scopes(str(tmp_path / "fehlt.json")) is None


def test_read_granted_scopes_returns_none_for_broken_json(tmp_path):
    path = str(tmp_path / "token.json")
    with open(path, "w") as f:
        f.write("not json")

    assert read_granted_scopes(path) is None


def test_read_granted_scopes_returns_empty_list_when_key_missing(tmp_path):
    """Lesbare Datei ohne scopes-Key: leere Liste, NICHT None — der Aufrufer
    unterscheidet „nichts gewährt" von „nicht lesbar"."""
    path = str(tmp_path / "token.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"token": "t"}, f)

    assert read_granted_scopes(path) == []


def test_read_granted_scopes_returns_none_for_non_list_scopes(tmp_path):
    """Ein scopes-Feld, das keine Liste ist, ist unbrauchbar — nicht als
    „keine Scopes" durchwinken."""
    path = str(tmp_path / "token.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"token": "t", "scopes": "gmail.send"}, f)

    assert read_granted_scopes(path) is None


def test_read_granted_scopes_returns_none_for_non_dict_root(tmp_path):
    """Syntaktisch gültiges JSON mit Nicht-Objekt-Wurzel (z.B. [] oder "x" oder
    123, plausibel bei Teilschreibvorgängen, Plattenfehlern oder manueller
    Bearbeitung) würde einen AttributeError werfen bei .get(). Die Funktion
    muss auf dict prüfen und konservativ None liefern."""
    path = str(tmp_path / "token.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump([], f)

    assert read_granted_scopes(path) is None
