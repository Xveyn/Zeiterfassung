"""UpdateCoordinator._apply_pending_update / apply_pending_on_quit: Anwenden
eines vorbereiteten Auto-Updates beim Beenden (Task 9, seit R11 im
Coordinator). Die Assertions sind beim Umzug aus `App` wortgleich geblieben.
"""

import os
import platform
from unittest.mock import MagicMock

from src.update_coordinator import UpdateCoordinator


class _FakeSettings:
    def __init__(self, data):
        self._data = data
        self.set_many_calls = []

    def get(self, key):
        return self._data.get(key, "")

    def set_many(self, updates):
        self.set_many_calls.append(dict(updates))
        self._data.update(updates)


class _FakeApp:
    """Hält die Settings unter dem Namen, unter dem die Tests sie bis R11 an
    `App` fanden; `coordinator` ist das Objekt unter Test."""

    def __init__(self, settings_data):
        self.settings = _FakeSettings(settings_data)
        self.coordinator = UpdateCoordinator(
            self.settings, MagicMock(), MagicMock(), lambda: None)


def test_apply_pending_update_clears_pending_settings_immediately(monkeypatch, tmp_path):
    """Die Settings werden VOR der Pruefung geleert — ein Fehlschlag danach
    darf den naechsten Start nicht wieder mit demselben (evtl. kaputten)
    Pfad starten lassen."""
    path = str(tmp_path / "missing-setup.exe")
    fake = _FakeApp({"pending_update_path": path, "pending_update_sha256": "abc"})

    fake.coordinator._apply_pending_update(path)

    assert fake.settings.set_many_calls == [
        {"pending_update_path": "", "pending_update_sha256": ""},
    ]


def test_apply_pending_update_skips_silently_when_file_missing(monkeypatch, tmp_path):
    path = str(tmp_path / "does-not-exist.exe")
    fake = _FakeApp({"pending_update_path": path, "pending_update_sha256": "deadbeef"})

    calls = []
    monkeypatch.setattr("src.update_coordinator.apply_windows",
                        lambda *a, **k: calls.append(("windows", a)))
    monkeypatch.setattr("src.update_coordinator.apply_linux",
                        lambda *a, **k: calls.append(("linux", a)))

    fake.coordinator._apply_pending_update(path)

    assert calls == []


def test_apply_pending_update_skips_when_hash_no_longer_matches(monkeypatch, tmp_path):
    """Erneute Pruefung unmittelbar vor dem Anwenden (Kern der Anforderung):
    existiert die Datei zwar noch, stimmt aber ihr Hash nicht mehr (z.B. weil
    zwischenzeitlich ueberschrieben), wird NICHT installiert."""
    path = tmp_path / "setup.exe"
    path.write_bytes(b"vermeintliches Update")
    fake = _FakeApp({"pending_update_path": str(path),
                     "pending_update_sha256": "0" * 64})

    calls = []
    monkeypatch.setattr("src.update_coordinator.apply_windows",
                        lambda *a, **k: calls.append(("windows", a)))
    monkeypatch.setattr("src.update_coordinator.apply_linux",
                        lambda *a, **k: calls.append(("linux", a)))

    fake.coordinator._apply_pending_update(str(path))

    assert calls == []


def test_apply_pending_update_applies_on_windows_with_verified_file(monkeypatch, tmp_path):
    """Kernverhalten: existiert die Datei und stimmt ihr Hash noch, wird unter
    Windows `apply_windows(sys.executable, path, pid)` aufgerufen."""
    import hashlib
    import sys

    path = tmp_path / "setup.exe"
    content = b"echtes Update"
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    fake = _FakeApp({"pending_update_path": str(path),
                     "pending_update_sha256": digest})

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    calls = []
    monkeypatch.setattr(
        "src.update_coordinator.apply_windows",
        lambda exe, setup, pid, restart: calls.append((exe, setup, pid, restart)) or True,
    )
    monkeypatch.setattr(
        "src.update_coordinator.apply_linux",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("apply_linux nicht erwartet")),
    )

    fake.coordinator._apply_pending_update(str(path))

    assert calls == [(sys.executable, str(path), os.getpid(), False)]


def test_apply_pending_update_applies_on_linux_with_appimage_env(monkeypatch, tmp_path):
    import hashlib

    path = tmp_path / "app.AppImage"
    content = b"echtes Update"
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    fake = _FakeApp({"pending_update_path": str(path),
                     "pending_update_sha256": digest})

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setenv("APPIMAGE", "/pfad/zur/app.AppImage")
    calls = []
    monkeypatch.setattr(
        "src.update_coordinator.apply_linux",
        lambda appimage, downloaded: calls.append((appimage, downloaded)),
    )
    monkeypatch.setattr(
        "src.update_coordinator.apply_windows",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("apply_windows nicht erwartet")),
    )

    fake.coordinator._apply_pending_update(str(path))

    assert calls == [("/pfad/zur/app.AppImage", str(path))]


def test_apply_pending_update_does_nothing_on_linux_without_appimage_env(monkeypatch, tmp_path):
    """Ohne $APPIMAGE (z.B. Repo-/Skript-Modus) gibt es keine laufende
    AppImage zum Ersetzen — der Aufruf bleibt aus, statt mit einem leeren
    Pfad zu scheitern."""
    import hashlib

    path = tmp_path / "app.AppImage"
    content = b"echtes Update"
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    fake = _FakeApp({"pending_update_path": str(path),
                     "pending_update_sha256": digest})

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.delenv("APPIMAGE", raising=False)
    calls = []
    monkeypatch.setattr(
        "src.update_coordinator.apply_linux", lambda *a, **k: calls.append(a))

    fake.coordinator._apply_pending_update(str(path))

    assert calls == []


# --- Aufraeumen der geladenen Datei (Abschluss-Review F6/F7) ----------------
#
# Seit jeder Download-Lauf einen eigenen Namen traegt
# (`self_update.download_dest`), ueberschreibt kein spaeterer Lauf mehr eine
# liegengebliebene Datei — jeder Fehlerpfad muss selbst aufraeumen, sonst
# sammeln sich ~65-MB-Leichen. `sweep_appimage_backup` raeumt nur `.old`.


def test_apply_pending_update_deletes_the_file_when_hash_no_longer_matches(
        monkeypatch, tmp_path):
    path = tmp_path / "setup.exe"
    path.write_bytes(b"vermeintliches Update")
    fake = _FakeApp({"pending_update_path": str(path),
                     "pending_update_sha256": "0" * 64})
    monkeypatch.setattr("src.update_coordinator.apply_windows", lambda *a, **k: True)
    monkeypatch.setattr("src.update_coordinator.apply_linux", lambda *a, **k: None)

    fake.coordinator._apply_pending_update(str(path))

    assert not path.exists(), "die verworfene Datei bleibt sonst dauerhaft liegen"


def test_apply_pending_update_deletes_the_file_when_apply_linux_fails(
        monkeypatch, tmp_path, caplog):
    """Beim Beenden darf KEINE Meldung erscheinen (die App macht zu) — der
    Fehlertext von `apply_linux` gehoert aber ins Log, und die geladene
    Datei weg."""
    import hashlib
    import logging

    path = tmp_path / "app.AppImage"
    content = b"echtes Update"
    path.write_bytes(content)
    fake = _FakeApp({"pending_update_path": str(path),
                     "pending_update_sha256": hashlib.sha256(content).hexdigest()})

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setenv("APPIMAGE", "/pfad/zur/app.AppImage")
    monkeypatch.setattr(
        "src.update_coordinator.apply_linux",
        lambda appimage, downloaded: "Die alte AppImage ließ sich nicht sichern: nope")

    with caplog.at_level(logging.WARNING, logger="src.update_coordinator"):
        fake.coordinator._apply_pending_update(str(path))

    assert not path.exists(), "die nicht uebernommene Datei bleibt sonst liegen"
    assert "nicht sichern" in caplog.text, (
        "der Fehlertext von apply_linux darf nicht verworfen werden")


def test_apply_pending_update_deletes_the_file_when_apply_windows_fails(
        monkeypatch, tmp_path):
    import hashlib

    path = tmp_path / "setup.exe"
    content = b"echtes Update"
    path.write_bytes(content)
    fake = _FakeApp({"pending_update_path": str(path),
                     "pending_update_sha256": hashlib.sha256(content).hexdigest()})

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr("src.update_coordinator.apply_windows", lambda *a, **k: False)

    fake.coordinator._apply_pending_update(str(path))

    assert not path.exists()


# --- Neu mit R11: der Einstieg beim Beenden -------------------------------


def test_apply_pending_on_quit_touches_nothing_without_a_pending_update(monkeypatch):
    """Der Normalfall beim Beenden: nichts vorbereitet — dann wird weder
    geleert noch angewendet."""
    fake = _FakeApp({})
    monkeypatch.setattr(
        "src.update_coordinator.apply_windows",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("nicht anwenden")))

    fake.coordinator.apply_pending_on_quit()

    assert fake.settings.set_many_calls == []


def test_apply_pending_on_quit_applies_exactly_the_pending_file(monkeypatch, tmp_path):
    import hashlib
    import sys

    path = tmp_path / "setup.exe"
    content = b"echtes Update"
    path.write_bytes(content)
    fake = _FakeApp({"pending_update_path": str(path),
                     "pending_update_sha256": hashlib.sha256(content).hexdigest()})
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    calls = []
    monkeypatch.setattr(
        "src.update_coordinator.apply_windows",
        lambda exe, setup, pid, restart: calls.append((exe, setup, pid, restart)) or True)

    fake.coordinator.apply_pending_on_quit()

    assert calls == [(sys.executable, str(path), os.getpid(), False)]
