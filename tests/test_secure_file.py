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
