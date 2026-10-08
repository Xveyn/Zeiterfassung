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
    monkeypatch.setattr(removal, "disable_autostart", lambda system=None: None)


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
    monkeypatch.setattr(removal, "disable_autostart", lambda system=None: None)

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


def test_app_file_command_linux_quotes_path():
    cmd = removal.app_file_command("Linux", "/home/u/My Apps/Z's.AppImage")
    assert cmd == "rm -- '/home/u/My Apps/Z'\"'\"'s.AppImage'"


def test_app_file_command_only_for_linux_with_file():
    assert removal.app_file_command("Linux", None) is None
    assert removal.app_file_command("Darwin", "/Applications/Zeiterfassung.app") is None


def test_summary_shows_terminal_command():
    text = removal.format_summary([], "/home/u/Z.AppImage", False,
                                  command="rm -- /home/u/Z.AppImage")
    assert "Terminal" in text
    assert "rm -- /home/u/Z.AppImage" in text


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


# --- Review-Fixes (Final) ---------------------------------------------------

def test_macos_autostart_removes_plist_without_launchctl(tmp_path, monkeypatch):
    """I4: `launchctl unload` beendet den per RunAtLoad gestarteten Prozess —
    also die App selbst. Auf macOS wird nur die plist gelöscht."""
    plist = tmp_path / "LaunchAgents" / "com.margenheld.zeiterfassung.plist"
    _touch(plist)
    monkeypatch.setattr(removal.secret_migration, "forget_all", lambda base: None)
    monkeypatch.setattr(removal, "macos_plist_path", lambda: str(plist))

    def unload():
        raise AssertionError("launchctl darf auf macOS nicht laufen")

    monkeypatch.setattr(removal, "disable_autostart", unload)

    results = removal.execute_removal(str(tmp_path / "data"), False, "Darwin")

    assert all(r.ok for r in results), results
    assert not plist.exists()


def test_linux_autostart_still_uses_disable_autostart(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(removal.secret_migration, "forget_all", lambda base: None)
    monkeypatch.setattr(removal, "disable_autostart", calls.append)

    removal.execute_removal(str(tmp_path), False, "Linux")

    # Die Plattform kommt aus dem Plan, nicht aus einer zweiten Abfrage (M9).
    assert calls == ["Linux"]


def test_summary_states_keyring_is_not_verified():
    """I3 / Review Focus 1: ✓ heißt „ausgeführt“, nicht „nachgeprüft“."""
    text = removal.format_summary([StepResult("Schlüsselbund-Einträge", True)],
                                  None, had_token=False)
    assert "nicht nachgeprüft" in text


def test_summary_without_keyring_step_has_no_keyring_hint():
    text = removal.format_summary([StepResult("Autostart", True)], None, False)
    assert "nicht nachgeprüft" not in text


def test_credential_temp_files_removed_without_data(tmp_path, quiet):
    """M3: mkstemp-Reste der Secret-Schreiber tragen Klartext."""
    for name in (".smtp-ab.tmp", ".webhooks-ab.tmp", ".instance-secret-ab.tmp"):
        _touch(tmp_path / name)
    _touch(tmp_path / "zeiterfassung.json.ab.tmp")

    removal.execute_removal(str(tmp_path), False, "Linux")

    for name in (".smtp-ab.tmp", ".webhooks-ab.tmp", ".instance-secret-ab.tmp"):
        assert not (tmp_path / name).exists()
    assert (tmp_path / "zeiterfassung.json.ab.tmp").exists()   # gehört zum Häkchen


def test_api_token_and_its_leftovers_removed_without_data(tmp_path, quiet):
    for name in ("api-token", ".api-token-ab.tmp", "api-token.corrupt-20261006"):
        _touch(tmp_path / name)
    _touch(tmp_path / "zeiterfassung.json")          # Nutzerdaten bleiben ohne Häkchen

    removal.execute_removal(str(tmp_path), False, "Linux")

    for name in ("api-token", ".api-token-ab.tmp", "api-token.corrupt-20261006"):
        assert not (tmp_path / name).exists()
    assert (tmp_path / "zeiterfassung.json").exists()


def test_user_data_temp_files_removed_with_data(tmp_path, quiet):
    _touch(tmp_path / "zeiterfassung.json.ab.tmp")
    _touch(tmp_path / "sync_history.json.tmp")

    removal.execute_removal(str(tmp_path), True, "Linux")

    assert not tmp_path.exists()


def test_settings_file_is_removed_last(tmp_path, monkeypatch):
    _populate(tmp_path)
    order = []
    real_remove = os.remove

    def recording(path, *a, **k):
        order.append(os.path.basename(path))
        return real_remove(path, *a, **k)

    monkeypatch.setattr(os, "remove", recording)

    removal._delete_user_data(str(tmp_path))

    assert order[-1] == "settings.json"


def test_special_characters_in_base_path(tmp_path, quiet):
    base = tmp_path / "a[1] (x86)"
    _touch(base / "webhooks.json.corrupt-1")
    _touch(base / ".smtp-x.tmp")

    results = removal.execute_removal(str(base), False, "Linux")

    assert all(r.ok for r in results), results
    assert not (base / "webhooks.json.corrupt-1").exists()
    assert not (base / ".smtp-x.tmp").exists()


def test_real_forget_all_removes_keyring_entry_and_files(tmp_path, monkeypatch,
                                                         fake_keyring):
    """Kein Stub: Schlüssel aus token.json → Eintrag weg, dann die Dateien."""
    import json

    from src import keyring_store, oauth_utils

    fake = fake_keyring()
    key = "google-oauth:k1"
    fake.store[(keyring_store.service_for(key), key)] = "1//r"
    (tmp_path / "token.json").write_text(
        json.dumps({oauth_utils.REFRESH_TOKEN_KEY: key, "token": "t"}),
        encoding="utf-8")
    monkeypatch.setattr(removal, "disable_autostart", lambda system=None: None)

    results = removal.execute_removal(str(tmp_path), False, "Linux")

    assert all(r.ok for r in results), results
    assert fake.store == {}
    assert not (tmp_path / "token.json").exists()


# --- RemovalState: darf jetzt entfernt werden? ------------------------------

def test_state_begin_takes_the_guard_and_never_gives_it_back():
    import threading

    guard = threading.Lock()
    state = removal.RemovalState()

    assert state.begin(guard) is True
    assert state.active is True
    assert guard.locked()


def test_state_begin_refuses_while_a_sync_holds_the_guard():
    """I5 / Review Focus 5: nichts wird angetastet."""
    import threading

    guard = threading.Lock()
    guard.acquire()
    state = removal.RemovalState()

    assert state.begin(guard) is False
    assert state.active is False


def test_state_begin_without_a_guard():
    state = removal.RemovalState()
    assert state.begin(None) is True and state.active is True


def test_state_claim_tells_a_second_call_from_a_running_sync():
    """M11: der zweite Aufruf sieht den selbst belegten Guard — das ist kein Sync."""
    import threading

    guard = threading.Lock()
    state = removal.RemovalState()

    assert state.claim(guard) == "started"
    assert state.claim(guard) == "running"
    assert state.active is True


def test_state_claim_reports_a_real_sync():
    import threading

    guard = threading.Lock()
    guard.acquire()
    state = removal.RemovalState()

    assert state.claim(guard) == "sync"
    assert state.active is False


def test_state_admits_everything_until_active_then_only_forced():
    """I2: fremde Callbacks anderer Worker dürfen nichts mehr schreiben."""
    state = removal.RemovalState()
    assert state.admits(False) is True

    state.begin(None)

    assert state.admits(False) is False
    assert state.admits(True) is True


def test_foreign_files_keep_the_folder_and_say_so(tmp_path):
    """M4 (#204): ✓ allein ließe den Nutzer glauben, der Ordner sei weg."""
    _touch(tmp_path / "fremd.txt")

    results = removal.run_removal(
        [("Datenordner", lambda: removal._remove_dir_if_empty(str(tmp_path)))])

    assert results[0].ok and "fremde Dateien" in results[0].note
    text = removal.format_summary(results, None, False)
    assert "✓ Datenordner — bleibt" in text


def test_empty_folder_is_removed_without_a_note(tmp_path):
    results = removal.run_removal(
        [("Datenordner", lambda: removal._remove_dir_if_empty(str(tmp_path)))])

    assert results == [StepResult("Datenordner", True)]
    assert not tmp_path.exists()


TRANSLOCATED = ("/private/var/folders/zy/jmx4mdfx6s36fdtd0_4ndl7c0000gn/T/"
                "AppTranslocation/613DF902-6BE1-4C37-A4C2-34/d/"
                "Zeiterfassung.app/Contents/MacOS/Zeiterfassung")


def test_translocated_app_has_no_file_hint():
    """M6: der Pfad unter AppTranslocation ist schreibgeschützt und dem Nutzer
    unbekannt — ihn zu nennen wäre falsch."""
    assert removal.is_translocated("Darwin", TRANSLOCATED)
    assert removal.app_file_hint("Darwin", {}, TRANSLOCATED) is None


def test_normal_mac_app_is_not_translocated():
    exe = "/Applications/Zeiterfassung.app/Contents/MacOS/Zeiterfassung"
    assert not removal.is_translocated("Darwin", exe)
    assert removal.app_file_hint("Darwin", {}, exe) == "/Applications/Zeiterfassung.app"


def test_translocation_marker_only_counts_on_macos():
    assert not removal.is_translocated("Linux", TRANSLOCATED)


def test_summary_explains_translocation_instead_of_a_path():
    text = removal.format_summary([StepResult("Autostart", True)], None,
                                  had_token=False, translocated=True)
    assert "App Translocation" in text
    assert "AppTranslocation" not in text  # kein Pfad
    assert "lösche sie selbst" not in text


def test_pending_update_keys_cleared_when_settings_stay(tmp_path, quiet):
    """M7: ohne „Nutzerdaten" bleibt settings.json — sie darf nicht auf die
    gelöschte Update-Datei zeigen."""
    pending = tmp_path / ".Zeiterfassung.update-1-ab"
    _touch(pending)
    cleared = []

    removal.execute_removal(str(tmp_path), False, "Linux",
                            pending_update_path=str(pending),
                            clear_pending=lambda: cleared.append(pending.exists()))

    # Geleert wird erst, nachdem die Datei weg ist.
    assert cleared == [False]


def test_pending_update_keys_untouched_when_settings_go(tmp_path, quiet):
    """Mit Häkchen verschwindet settings.json ohnehin; ein Schreiben davor
    wäre überflüssig, eines danach legte sie neu an."""
    pending = tmp_path / ".Zeiterfassung.update-1-ab"
    _touch(pending)
    cleared = []

    removal.execute_removal(str(tmp_path), True, "Linux",
                            pending_update_path=str(pending),
                            clear_pending=lambda: cleared.append(1))

    assert cleared == []
    assert not pending.exists()


def test_pending_update_keys_kept_when_file_cannot_be_deleted(tmp_path, quiet,
                                                              monkeypatch):
    pending = tmp_path / ".Zeiterfassung.update-1-ab"
    _touch(pending)
    cleared = []

    def boom(_path):
        raise OSError("gesperrt")

    monkeypatch.setattr(removal.self_update, "discard_download", boom)

    results = removal.execute_removal(str(tmp_path), False, "Linux",
                                      pending_update_path=str(pending),
                                      clear_pending=lambda: cleared.append(1))

    assert cleared == []
    assert [r.ok for r in results if r.name == "Vorbereitetes Update"] == [False]
