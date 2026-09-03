"""App._apply_pending_update: Anwenden eines vorbereiteten Auto-Updates beim
Beenden (Task 9). Duck-Typed Stand-in wie in test_ui_update_routing.py — die
Methode selbst fasst nur `self.settings` an, keine Tk-Widgets.
"""

import os
import platform

from src.ui import App


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
    def __init__(self, settings_data):
        self.settings = _FakeSettings(settings_data)


def test_apply_pending_update_clears_pending_settings_immediately(monkeypatch, tmp_path):
    """Die Settings werden VOR der Pruefung geleert — ein Fehlschlag danach
    darf den naechsten Start nicht wieder mit demselben (evtl. kaputten)
    Pfad starten lassen."""
    path = str(tmp_path / "missing-setup.exe")
    fake = _FakeApp({"pending_update_path": path, "pending_update_sha256": "abc"})

    App._apply_pending_update(fake, path)

    assert fake.settings.set_many_calls == [
        {"pending_update_path": "", "pending_update_sha256": ""},
    ]


def test_apply_pending_update_skips_silently_when_file_missing(monkeypatch, tmp_path):
    path = str(tmp_path / "does-not-exist.exe")
    fake = _FakeApp({"pending_update_path": path, "pending_update_sha256": "deadbeef"})

    calls = []
    monkeypatch.setattr("src.ui.apply_windows",
                        lambda *a, **k: calls.append(("windows", a)))
    monkeypatch.setattr("src.ui.apply_linux",
                        lambda *a, **k: calls.append(("linux", a)))

    App._apply_pending_update(fake, path)

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
    monkeypatch.setattr("src.ui.apply_windows",
                        lambda *a, **k: calls.append(("windows", a)))
    monkeypatch.setattr("src.ui.apply_linux",
                        lambda *a, **k: calls.append(("linux", a)))

    App._apply_pending_update(fake, str(path))

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
        "src.ui.apply_windows",
        lambda exe, setup, pid: calls.append((exe, setup, pid)) or True,
    )
    monkeypatch.setattr(
        "src.ui.apply_linux",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("apply_linux nicht erwartet")),
    )

    App._apply_pending_update(fake, str(path))

    assert calls == [(sys.executable, str(path), os.getpid())]


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
        "src.ui.apply_linux",
        lambda appimage, downloaded: calls.append((appimage, downloaded)),
    )
    monkeypatch.setattr(
        "src.ui.apply_windows",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("apply_windows nicht erwartet")),
    )

    App._apply_pending_update(fake, str(path))

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
        "src.ui.apply_linux", lambda *a, **k: calls.append(a))

    App._apply_pending_update(fake, str(path))

    assert calls == []
