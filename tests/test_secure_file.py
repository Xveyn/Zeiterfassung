"""Tests für das plattformabhängige Härten von Secret-Dateien (Audit M8).

`harden_windows_acl` beschränkt die ACL einer Datei auf den aktuellen Benutzer.
Auf POSIX ist es ein No-op — dort erledigt `chmod 0600` die Arbeit. Genutzt von
`oauth_utils.write_token` (token.json) und `single_instance` (instance-secret).
"""

import platform
import subprocess

from src.secure_file import harden_windows_acl


def _windows(monkeypatch, calls, *, result=None, raises=None,
             domain="MACHINE", user="sven"):
    def run(cmd, **_kwargs):
        calls.append(list(cmd))
        if raises is not None:
            raise raises
        return result if result is not None else subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "run", run)
    if domain is None:
        monkeypatch.delenv("USERDOMAIN", raising=False)
    else:
        monkeypatch.setenv("USERDOMAIN", domain)
    if user is None:
        monkeypatch.delenv("USERNAME", raising=False)
    else:
        monkeypatch.setenv("USERNAME", user)


def test_drops_inheritance_and_grants_only_current_user(monkeypatch, tmp_path):
    """Geerbte ACEs (SYSTEM, lokale Administratoren) fliegen raus, übrig bleibt
    genau ein Berechtigter. Vollzugriff, weil ein späteres os.replace DELETE auf
    der Zieldatei braucht."""
    path = str(tmp_path / "secret")
    calls = []
    _windows(monkeypatch, calls)

    harden_windows_acl(path)

    assert calls == [["icacls", path, "/inheritance:r", "/grant:r", "MACHINE\\sven:(F)"]]


def test_falls_back_to_bare_username_without_userdomain(monkeypatch, tmp_path):
    path = str(tmp_path / "secret")
    calls = []
    _windows(monkeypatch, calls, domain=None)

    harden_windows_acl(path)

    assert calls[0][-1] == "sven:(F)"


def test_skips_when_user_cannot_be_named(monkeypatch, tmp_path, caplog):
    """Ohne benennbaren Principal wird nicht geraten — ein falscher Name härtete
    entweder nichts oder sperrte den eigenen Prozess aus."""
    path = str(tmp_path / "secret")
    calls = []
    _windows(monkeypatch, calls, user=None, domain=None)

    with caplog.at_level("WARNING"):
        harden_windows_acl(path)

    assert calls == []
    assert caplog.records


def test_is_a_noop_off_windows(monkeypatch, tmp_path):
    path = str(tmp_path / "secret")
    calls = []
    _windows(monkeypatch, calls)
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    harden_windows_acl(path)

    assert calls == []


def test_missing_icacls_is_logged_not_raised(monkeypatch, tmp_path, caplog):
    """Härtung ist Beiwerk: fehlt icacls (abgespecktes Windows, PATH kaputt),
    darf der aufrufende Schreibpfad nicht scheitern."""
    path = str(tmp_path / "secret")
    calls = []
    _windows(monkeypatch, calls, raises=FileNotFoundError(2, "icacls fehlt"))

    with caplog.at_level("WARNING"):
        harden_windows_acl(path)  # darf nicht werfen

    assert caplog.records


def test_nonzero_exit_is_logged(monkeypatch, tmp_path, caplog):
    """Ein Fehlschlag wird geloggt statt still verschluckt (N13-Muster)."""
    path = str(tmp_path / "secret")
    calls = []
    _windows(monkeypatch, calls,
             result=subprocess.CompletedProcess(["icacls"], 5, "", "Zugriff verweigert"))

    with caplog.at_level("WARNING"):
        harden_windows_acl(path)

    assert any("5" in r.getMessage() for r in caplog.records), caplog.text


# --- write_secret_json (#249) -----------------------------------------------------------------

import json
import os
import stat

import pytest

from src import secure_file


def test_write_secret_json_writes_private_atomic_and_leaves_no_temp(tmp_path):
    path = tmp_path / "secret.json"
    secure_file.write_secret_json(str(path), {"a": 1, "ä": "ö"}, prefix=".sec-")
    assert json.loads(path.read_text("utf-8")) == {"a": 1, "ä": "ö"}
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["secret.json"]


def test_write_secret_json_hardens_the_temp_file_before_the_rename(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr(secure_file, "harden_windows_acl", lambda p: order.append(("harden", os.path.basename(p))))
    real_replace = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (order.append(("replace", os.path.basename(a))), real_replace(a, b))[1])
    secure_file.write_secret_json(str(tmp_path / "s.json"), {}, prefix=".sec-")
    assert [step for step, _ in order] == ["harden", "replace"]
    assert order[0][1] == order[1][1] and order[0][1].startswith(".sec-")      # dieselbe Temp-Datei


def test_write_secret_json_cleans_up_and_keeps_the_old_file_on_any_error(tmp_path, monkeypatch):
    path = tmp_path / "s.json"
    secure_file.write_secret_json(str(path), {"old": True}, prefix=".sec-")
    monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("voll")))
    with pytest.raises(OSError):
        secure_file.write_secret_json(str(path), {"new": True}, prefix=".sec-")
    assert json.loads(path.read_text("utf-8")) == {"old": True}
    assert [p.name for p in tmp_path.iterdir()] == ["s.json"]


def test_write_secret_json_cleans_up_when_serialising_fails(tmp_path):
    with pytest.raises(TypeError):
        secure_file.write_secret_json(str(tmp_path / "s.json"), {"x": object()}, prefix=".sec-")
    assert list(tmp_path.iterdir()) == []


def test_write_secret_json_retries_a_blocked_rename(tmp_path, monkeypatch):
    attempts = []
    real_replace = os.replace
    def flaky(a, b):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("Virenscanner")
        return real_replace(a, b)
    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)
    secure_file.write_secret_json(str(tmp_path / "s.json"), {"a": 1}, prefix=".sec-")
    assert len(attempts) == 3 and (tmp_path / "s.json").exists()


def test_write_secret_json_gives_up_after_five_blocked_renames(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError("x")))
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(PermissionError):
        secure_file.write_secret_json(str(tmp_path / "s.json"), {}, prefix=".sec-")
    assert list(tmp_path.iterdir()) == []
