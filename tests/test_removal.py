"""„Zeiterfassung entfernen" (#50): Plan, Ausführung, Hinweise — Tk-frei."""

import os
import re

import pytest

from src import removal
from src.removal import StepResult


def _touch(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _populate(base, *, credentials=True, data=True):
    if credentials:
        for name in removal.CREDENTIAL_FILES:
            _touch(base / name)
    if data:
        for name in (*removal.USER_DATA_FILES, removal.SETTINGS_FILE):
            _touch(base / name)
        _touch(base / removal.LOGS_DIR / "zeiterfassung.log")


@pytest.fixture
def quiet(monkeypatch):
    """Schlüsselbund und Autostart sind hier nicht das Thema."""
    monkeypatch.setattr(removal.secret_migration, "forget_all", lambda base: None)
    monkeypatch.setattr(removal, "disable_autostart", lambda: None)


def _names(steps):
    return [name for name, _fn in steps]


# --- Verfügbarkeit ----------------------------------------------------------

@pytest.mark.parametrize("system, frozen, expected", [
    ("Linux", True, True), ("Darwin", True, True),
    ("Windows", True, False), ("Linux", False, False), ("Darwin", False, False),
])
def test_is_available(system, frozen, expected):
    assert removal.is_available(system, frozen) is expected


# --- Plan -------------------------------------------------------------------

def test_plan_is_empty_on_windows(tmp_path):
    assert removal.plan_removal(str(tmp_path), True, "Windows") == []


def test_plan_linux_with_data_in_order(tmp_path):
    steps = removal.plan_removal(str(tmp_path), True, "Linux",
                                 pending_update_path="/x/.u")
    assert _names(steps) == [
        "Schlüsselbund-Einträge", "Autostart", "Menüeintrag",
        "Vorbereitetes Update", "Zugangsdaten",
        "Zeiten, Einstellungen und Protokoll", "Datenordner",
    ]


def test_plan_macos_has_no_menu_entry_step(tmp_path):
    steps = removal.plan_removal(str(tmp_path), False, "Darwin")
    assert _names(steps) == ["Schlüsselbund-Einträge", "Autostart", "Zugangsdaten"]


def test_plan_without_data_skips_data_and_folder(tmp_path):
    names = _names(removal.plan_removal(str(tmp_path), False, "Linux"))
    assert "Zeiten, Einstellungen und Protokoll" not in names
    assert "Datenordner" not in names


def test_keyring_runs_before_any_file_is_deleted(tmp_path, monkeypatch):
    """Die Schlüssel stehen in token.json/webhooks.json/smtp.json — erst
    abräumen, dann löschen."""
    _populate(tmp_path)
    seen = {}
    monkeypatch.setattr(removal.secret_migration, "forget_all",
                        lambda base: seen.update(token=(tmp_path / "token.json").exists()))
    monkeypatch.setattr(removal, "disable_autostart", lambda: None)

    removal.execute_removal(str(tmp_path), True, "Linux")

    assert seen == {"token": True}


# --- Ausführung -------------------------------------------------------------

def test_run_removal_isolates_failures():
    calls = []

    def boom():
        raise OSError("gesperrt")

    steps = [("a", lambda: calls.append("a")), ("b", boom),
             ("c", lambda: calls.append("c"))]

    results = removal.run_removal(steps)

    assert calls == ["a", "c"]
    assert [(r.name, r.ok) for r in results] == [("a", True), ("b", False), ("c", True)]
    assert "gesperrt" in results[1].error


def test_execute_removal_never_raises(tmp_path, monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("Plan kaputt")

    monkeypatch.setattr(removal, "plan_removal", broken)

    results = removal.execute_removal(str(tmp_path), True, "Linux")

    assert len(results) == 1 and results[0].ok is False
    assert "Plan kaputt" in results[0].error


# --- Dateischritte ----------------------------------------------------------

def test_credentials_removed_user_data_kept_without_data(tmp_path, quiet):
    _populate(tmp_path)

    results = removal.execute_removal(str(tmp_path), False, "Linux")

    assert all(r.ok for r in results)
    for name in removal.CREDENTIAL_FILES:
        assert not (tmp_path / name).exists()
    for name in (*removal.USER_DATA_FILES, removal.SETTINGS_FILE):
        assert (tmp_path / name).exists()
    assert (tmp_path / removal.LOGS_DIR).is_dir()


def test_credential_quarantine_removed_without_data(tmp_path, quiet):
    """Eine Quarantäne-Kopie von webhooks.json trägt dieselben Secrets."""
    _touch(tmp_path / "webhooks.json.corrupt-20260101")
    _touch(tmp_path / ".token-abc.tmp")
    _touch(tmp_path / "zeiterfassung.json.corrupt-20260101")

    removal.execute_removal(str(tmp_path), False, "Linux")

    assert not (tmp_path / "webhooks.json.corrupt-20260101").exists()
    assert not (tmp_path / ".token-abc.tmp").exists()
    # Nutzerdaten-Quarantäne gehört zum Häkchen, nicht zu den Zugangsdaten.
    assert (tmp_path / "zeiterfassung.json.corrupt-20260101").exists()


def test_user_data_removed_with_data_and_empty_dir_goes(tmp_path, quiet):
    base = tmp_path / "Zeiterfassung"
    _populate(base)
    _touch(base / "zeiterfassung.json.corrupt-20260101")

    results = removal.execute_removal(str(base), True, "Linux")

    assert all(r.ok for r in results), results
    assert not base.exists()


def test_data_dir_kept_with_foreign_file(tmp_path, quiet):
    _populate(tmp_path)
    _touch(tmp_path / "meine-notizen.txt")

    results = removal.execute_removal(str(tmp_path), True, "Linux")

    assert all(r.ok for r in results), results
    assert (tmp_path / "meine-notizen.txt").exists()
    assert not (tmp_path / "settings.json").exists()


def test_missing_files_are_not_errors(tmp_path, quiet):
    results = removal.execute_removal(str(tmp_path), True, "Linux")

    assert all(r.ok for r in results), results


def test_linux_menu_entry_and_icon_removed(tmp_path, monkeypatch, quiet):
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    entry = xdg / "applications" / "Zeiterfassung.desktop"
    base = xdg / "Zeiterfassung"
    _touch(entry)
    _touch(base / "icon.png")

    results = removal.execute_removal(str(base), False, "Linux")

    assert all(r.ok for r in results), results
    assert not entry.exists()
    assert not (base / "icon.png").exists()


def test_pending_update_file_discarded(tmp_path, quiet):
    pending = tmp_path / ".Zeiterfassung.update-1-ab"
    _touch(pending)

    removal.execute_removal(str(tmp_path), False, "Linux",
                            pending_update_path=str(pending))

    assert not pending.exists()


# --- Hinweise ---------------------------------------------------------------

def test_app_file_hint_linux():
    env = {"APPIMAGE": "/home/u/Apps/Zeiterfassung-1.0-x86_64.AppImage"}
    assert (removal.app_file_hint("Linux", env, "/tmp/.mount_x/Zeiterfassung")
            == "/home/u/Apps/Zeiterfassung-1.0-x86_64.AppImage")


def test_app_file_hint_linux_without_appimage():
    assert removal.app_file_hint("Linux", {}, "/opt/z/Zeiterfassung") is None


def test_app_file_hint_macos_walks_up_to_bundle():
    exe = "/Applications/Zeiterfassung.app/Contents/MacOS/Zeiterfassung"
    assert removal.app_file_hint("Darwin", {}, exe) == "/Applications/Zeiterfassung.app"


def test_app_file_hint_macos_without_bundle():
    assert removal.app_file_hint("Darwin", {}, "/usr/local/bin/zeit") is None


def test_summary_lists_steps_and_app_file():
    text = removal.format_summary(
        [StepResult("Autostart", True), StepResult("Zugangsdaten", False, "OSError: x")],
        "/home/u/Z.AppImage", had_token=False)
    assert "✓ Autostart" in text
    assert "✗ Zugangsdaten — OSError: x" in text
    assert "/home/u/Z.AppImage" in text
    assert "myaccount.google.com" not in text


def test_summary_mentions_google_only_with_token():
    text = removal.format_summary([], None, had_token=True)
    assert "https://myaccount.google.com/permissions" in text


def test_summary_always_points_to_readme():
    """Review Focus 1: der Schlüsselbund-Schritt meldet ✓ auch bei einem
    geschluckten Fehler — der Hinweis auf die Handarbeit muss immer da sein."""
    text = removal.format_summary([StepResult("Schlüsselbund-Einträge", True)],
                                  None, had_token=False)
    assert "Vollständig entfernen" in text


# --- Listen gegen den Windows-Uninstaller ----------------------------------

def _installer():
    path = os.path.join(os.path.dirname(__file__), "..", "installer.iss")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_credential_files_match_installer():
    names = set(re.findall(r'Type: files; Name: "\{app\}\\([^"]+)"', _installer()))
    assert names == set(removal.CREDENTIAL_FILES)


def test_user_data_files_match_installer():
    names = set(re.findall(r"DeleteFile\(ExpandConstant\('\{app\}\\([^']+)'\)\)",
                           _installer()))
    assert names == {*removal.USER_DATA_FILES, removal.SETTINGS_FILE}
