"""UpdatesTab._apply: erneute Hash-Prüfung unmittelbar vor dem Anwenden
(Nachtrag zu Task 9, Re-Review-Auflage). Duck-Typed Stand-in wie in
test_ui_apply_pending_update.py/test_ui_update_routing.py — `_apply`/
`_fail_update` fassen nur Tk-Funktionsaufrufe an, die über die Modulnamen
in `tab_updates.py` monkeypatchbar sind; ein `MagicMock()` steht für
`self.frame`/`self._check_btn`/etc., echte Widgets sind nicht nötig.
"""

import hashlib
import os
import platform
from types import MethodType
from unittest.mock import MagicMock

import src.dialogs.settings_dialog.tab_updates as tab_updates_module
from src.dialogs.settings_dialog.tab_updates import UpdatesTab


class _FakeSettings:
    def __init__(self, data=None):
        self._data = data or {}
        self.set_many_calls = []

    def get(self, key):
        return self._data.get(key, "")

    def set_many(self, updates):
        self.set_many_calls.append(dict(updates))
        self._data.update(updates)


class _FakePlan:
    def __init__(self, target=r"C:\Apps\Zeiterfassung\Zeiterfassung.exe"):
        self.target = target


def _fake_tab():
    """UpdatesTab-Stand-in ohne echten Tk-Aufbau: `_apply`/`_fail_update`
    gebunden ans Fake-Objekt (Muster wie `_tray_app` in
    test_ui_update_routing.py). `frame`/`_check_btn`/`_download_btn`/
    `_status_label` bleiben MagicMocks — `_apply` ruft auf ihnen nur
    Funktionen auf, die hier per Modul-Patch abgefangen werden."""
    fake = MagicMock()
    fake._settings = _FakeSettings()
    fake._apply = MethodType(UpdatesTab._apply, fake)
    fake._fail_update = MethodType(UpdatesTab._fail_update, fake)
    return fake


def _patch_widget_calls(monkeypatch, apply_windows_calls=None, apply_linux_calls=None):
    monkeypatch.setattr(tab_updates_module, "set_primary_button_enabled",
                        lambda *a, **k: None)
    monkeypatch.setattr(tab_updates_module, "set_secondary_button_enabled",
                        lambda *a, **k: None)
    if apply_windows_calls is not None:
        monkeypatch.setattr(
            tab_updates_module, "apply_windows",
            lambda *a, **k: apply_windows_calls.append(a) or True)
    if apply_linux_calls is not None:
        monkeypatch.setattr(
            tab_updates_module, "apply_linux",
            lambda *a, **k: apply_linux_calls.append(a) or None)


def test_apply_refuses_to_install_when_file_is_missing(monkeypatch, tmp_path):
    """Zwischen Download-Ende und Anwenden kann die Datei verschwunden sein
    (Aufräum-Tools, manuelles Löschen) — dann darf nicht installiert werden."""
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    apply_windows_calls = []
    errors = []
    _patch_widget_calls(monkeypatch, apply_windows_calls=apply_windows_calls)
    monkeypatch.setattr(tab_updates_module, "themed_showerror",
                        lambda parent, title, message: errors.append(message))

    fake = _fake_tab()
    local = str(tmp_path / "does-not-exist.exe")

    fake._apply(_FakePlan(), local, "ab" * 32)

    assert apply_windows_calls == []
    assert errors, "es muss eine Fehlermeldung ueber _fail_update kommen"
    assert fake._settings.set_many_calls == []  # pending_update_* nicht geleert


def test_apply_refuses_to_install_when_hash_no_longer_matches(monkeypatch, tmp_path):
    """Kernanforderung (Re-Review-Auflage): existiert die Datei zwar noch,
    stimmt aber ihr Hash nicht mehr (z.B. weil ein zeitgleicher stiller
    Automatik-Download denselben Zielpfad ueberschrieben hat), wird NICHT
    installiert — und die Datei wird weggeraeumt."""
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    apply_windows_calls = []
    errors = []
    _patch_widget_calls(monkeypatch, apply_windows_calls=apply_windows_calls)
    monkeypatch.setattr(tab_updates_module, "themed_showerror",
                        lambda parent, title, message: errors.append(message))

    local = tmp_path / "setup.exe"
    local.write_bytes(b"veraendert, seit der Download fertig war")
    expected = hashlib.sha256(b"das urspruenglich geladene Original").hexdigest()

    fake = _fake_tab()
    fake._apply(_FakePlan(), str(local), expected)

    assert apply_windows_calls == [], (
        "apply_windows darf bei Hash-Mismatch NICHT aufgerufen werden")
    assert errors
    assert not local.exists(), "eine Datei mit falschem Hash darf nicht liegen bleiben"


def test_apply_installs_on_windows_when_hash_still_matches(monkeypatch, tmp_path):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    apply_windows_calls = []
    _patch_widget_calls(monkeypatch, apply_windows_calls=apply_windows_calls)

    content = b"echtes, unveraendertes Update"
    digest = hashlib.sha256(content).hexdigest()
    local = tmp_path / "setup.exe"
    local.write_bytes(content)
    plan = _FakePlan()

    fake = _fake_tab()
    fake._apply(plan, str(local), digest)

    # restart=True: der Sofort-Weg startet die App wieder, weil der Nutzer
    # eben geklickt hat und weiterarbeiten will (Gegenstueck: der
    # Beenden-Weg in ui.py, der mit False anwendet).
    assert apply_windows_calls == [(plan.target, str(local), os.getpid(), True)]
    # pending_update_* wird beim Sofort-Anwenden geleert (bestehendes
    # Verhalten, unveraendert durch diesen Fix).
    assert fake._settings.set_many_calls == [
        {"pending_update_path": "", "pending_update_sha256": ""},
    ]


def test_apply_installs_on_linux_when_hash_still_matches(monkeypatch, tmp_path):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    apply_linux_calls = []
    _patch_widget_calls(monkeypatch, apply_linux_calls=apply_linux_calls)
    # os.execv NIE wirklich ausfuehren (ersetzt sonst den Testprozess) — nur
    # dieser eine Aufruf wird abgefangen, der Rest von os bleibt echt.
    execv_calls = []
    monkeypatch.setattr(os, "execv", lambda path, args: execv_calls.append((path, args)))

    content = b"echtes AppImage-Update"
    digest = hashlib.sha256(content).hexdigest()
    local = tmp_path / "app.AppImage"
    local.write_bytes(content)
    plan = _FakePlan(target="/home/u/Apps/Zeiterfassung.AppImage")

    fake = _fake_tab()
    fake._apply(plan, str(local), digest)

    assert apply_linux_calls == [(plan.target, str(local))]
    assert execv_calls == [(plan.target, [plan.target])]


def test_apply_removes_a_differently_named_pending_download(monkeypatch, tmp_path):
    """Seit jeder Lauf einen eigenen Zielnamen traegt (F1), ist die still
    vorbereitete Datei eine ANDERE als die eben geladene. Der Sofort-Weg
    gewinnt gegen „beim Beenden" — die vorbereitete Datei wuerde sonst als
    ~65-MB-Leiche liegen bleiben, weil kein spaeterer Lauf sie mehr
    ueberschreibt."""
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    apply_windows_calls = []
    _patch_widget_calls(monkeypatch, apply_windows_calls=apply_windows_calls)

    content = b"echtes, unveraendertes Update"
    digest = hashlib.sha256(content).hexdigest()
    local = tmp_path / "Zeiterfassung_Setup-1-aaaa.exe"
    local.write_bytes(content)
    pending = tmp_path / "Zeiterfassung_Setup-1-bbbb.exe"
    pending.write_bytes(b"still vorbereitet, jetzt ueberholt")

    fake = _fake_tab()
    fake._settings = _FakeSettings({"pending_update_path": str(pending),
                                    "pending_update_sha256": "cd" * 32})

    fake._apply(_FakePlan(), str(local), digest)

    assert apply_windows_calls, "das eben geladene Update wird angewendet"
    assert not pending.exists(), "die ueberholte Datei bleibt sonst liegen"
    assert local.exists(), "die eben geladene Datei darf NICHT geloescht werden"


def test_apply_removes_the_download_when_the_helper_cannot_be_started(
        monkeypatch, tmp_path):
    """L1: `pending_update_*` ist beim Erreichen dieses Zweigs bereits
    geleert — es gibt danach keine Referenz mehr auf die Datei. Ohne
    Aufraeumen bleiben ~65 MB dauerhaft im %TEMP%; genau das sagt der
    Docstring von `download_dest` zu (und die beiden anderen Fehlerzweige
    dieser Funktion halten es ein)."""
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    _patch_widget_calls(monkeypatch)
    monkeypatch.setattr(tab_updates_module, "apply_windows",
                        lambda *a, **k: False)
    errors = []
    monkeypatch.setattr(tab_updates_module, "themed_showerror",
                        lambda parent, title, message: errors.append(message))

    content = b"echtes, unveraendertes Update"
    digest = hashlib.sha256(content).hexdigest()
    local = tmp_path / "Zeiterfassung_Setup-1-aaaa.exe"
    local.write_bytes(content)

    fake = _fake_tab()
    fake._apply(_FakePlan(), str(local), digest)

    assert errors, "der Nutzer bekommt weiterhin eine Fehlermeldung"
    assert not local.exists(), (
        "die Datei bleibt sonst dauerhaft liegen — niemand kennt ihren "
        "Pfad noch")
