"""Die Auto-Update-Policy (R9, Xveyn#123): Häkchen, Plattform, vorbereitete
Datei, EIN gemeinsamer Guard, Laden+Prüfen, Persistieren.
"""

from types import MethodType
from unittest.mock import MagicMock

import pytest

import src.dialogs.settings_dialog.tab_updates as tab_module
from src.dialogs.settings_dialog.tab_updates import UpdatesTab
from src.self_update import DownloadedUpdate, UpdatePlan
from src.ui import App


class _Rel:
    release_id = "1.9.0"
    version = "1.9.0"


class _FakeSettings:
    def __init__(self, data=None):
        self._data = data or {}

    def get(self, key):
        return self._data.get(key, "")

    def set(self, key, value):
        self._data[key] = value

    def set_many(self, updates):
        self._data.update(updates)


class _DeferredRunner:
    """Stand-in für `App._bg`: sammelt Jobs, `flush()` führt sie aus wie der
    echte Runner (fn im Worker, on_done danach im UI-Thread). Solange nicht
    geflusht ist, läuft der Download also noch."""

    def __init__(self):
        self.jobs = []

    def run(self, fn, on_done=None):
        self.jobs.append((fn, on_done))

    def flush(self):
        jobs, self.jobs = self.jobs, []
        for fn, on_done in jobs:
            result = fn()
            if on_done is not None:
                on_done(result)


_PLAN = UpdatePlan(asset_url="https://x/exe", asset_name="Zeiterfassung_Setup.exe",
                   sums_url="https://x/sums", target=r"C:\Apps\Z.exe")


def test_startup_check_and_updates_tab_never_download_twice(monkeypatch):
    """Der Defekt hinter R9: der Start-Check der App lädt still, der Nutzer
    klickt im Banner „Update installieren" — das öffnet den Updates-Tab, dessen
    eigener Check ebenfalls still lud. `pending_update_path` war dann noch
    leer (der erste Download lief ja noch), und keiner der beiden Guards
    kannte den anderen: zwei ~65-MB-Downloads, die Datei des Verlierers blieb
    in %TEMP% liegen. Beide echten Einstiege, ein gemeinsamer AutoUpdater."""
    import platform

    import src.auto_update as auto_update
    import src.ui as ui_module

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(ui_module, "today_iso", lambda: "2026-09-18")
    monkeypatch.setattr(auto_update, "supports_self_update", lambda *a, **k: True)
    monkeypatch.setattr(auto_update, "plan_update", lambda *a, **k: _PLAN)
    monkeypatch.setattr(tab_module, "set_secondary_button_enabled",
                        lambda *a, **k: None)
    downloads = []

    def fake_download(plan, dest, on_progress=None):
        downloads.append(dest)
        return DownloadedUpdate(path=dest, sha256="ab" * 32)

    monkeypatch.setattr(auto_update, "download_and_verify_update", fake_download)

    settings = _FakeSettings({"auto_update_enabled": True})
    runner = _DeferredRunner()
    banner = MagicMock()
    updater = auto_update.AutoUpdater(settings, runner,
                                      on_ready=banner.show_ready_to_install)

    app = MagicMock()
    app.settings = settings
    app._tray = None
    app._update_banner = banner
    app._auto_updater = updater

    tab = MagicMock()
    tab._settings = settings
    tab._auto_updater = updater
    tab._maybe_start_auto_update = MethodType(UpdatesTab._maybe_start_auto_update, tab)
    tab._on_auto_update_finished = MethodType(UpdatesTab._on_auto_update_finished, tab)

    rel = _Rel()
    App._on_update_check_result(app, rel, True)   # Start-Check der App
    tab._maybe_start_auto_update(rel)             # Tab-Check, Download läuft noch
    runner.flush()

    assert len(downloads) == 1
    assert settings.get("pending_update_path") == downloads[0]
    tab._status_label.config.assert_called_with(
        text="Update bereit — wird beim Beenden installiert")


# --- AutoUpdater: die eine Policy ------------------------------------------


class _Ready:
    """Zeichnet die `on_ready`-Aufrufe auf (der Banner in der echten App)."""

    def __init__(self):
        self.releases = []

    def __call__(self, release):
        self.releases.append(release)


def _updater(monkeypatch, settings_data, *, supported=True, plan=_PLAN,
             result=None):
    """Baut einen AutoUpdater mit aufgeschobenem Runner. Mockt wird nur die
    Netz-/Plattform-Ebene; Guard, Persistieren und Rückmeldung laufen echt.
    Liefert (updater, settings, runner, ready, downloads)."""
    import platform

    import src.auto_update as auto_update

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(auto_update, "supports_self_update",
                        lambda *a, **k: supported)
    monkeypatch.setattr(auto_update, "plan_update", lambda *a, **k: plan)
    downloads = []

    def fake_download(plan_arg, dest, on_progress=None):
        downloads.append((plan_arg, dest))
        if on_progress is not None:
            on_progress("Lade … 42 %")   # wie download_and_verify_update
        if result is not None:
            return result
        return DownloadedUpdate(path=dest, sha256="ab" * 32)

    monkeypatch.setattr(auto_update, "download_and_verify_update", fake_download)
    settings = _FakeSettings(settings_data)
    runner = _DeferredRunner()
    ready = _Ready()
    updater = auto_update.AutoUpdater(settings, runner, on_ready=ready)
    return updater, settings, runner, ready, downloads


def test_does_nothing_when_the_setting_is_off(monkeypatch):
    updater, _, runner, ready, _ = _updater(
        monkeypatch, {"auto_update_enabled": False})

    assert updater.maybe_start(_Rel()) == "disabled"
    assert runner.jobs == []
    assert ready.releases == []


def test_does_nothing_where_the_platform_cannot_self_update(monkeypatch):
    updater, _, runner, _, _ = _updater(
        monkeypatch, {"auto_update_enabled": True}, supported=False)

    assert updater.maybe_start(_Rel()) == "unsupported"
    assert runner.jobs == []


def test_a_pending_download_is_reused_and_only_made_visible_again(monkeypatch):
    """Liegt schon eine geprüfte Datei bereit (die App wurde seither nicht
    beendet), lädt KEIN Check dieselben ~65 MB erneut — egal ob er von der
    App oder vom Updates-Tab kommt. Der Banner wird nur aufgefrischt."""
    updater, _, runner, ready, _ = _updater(monkeypatch, {
        "auto_update_enabled": True,
        "pending_update_path": r"C:\Temp\Zeiterfassung_Setup-4711-ab12cd34.exe",
    })
    rel = _Rel()

    assert updater.maybe_start(rel) == "pending"
    assert runner.jobs == []
    assert ready.releases == [rel]


def test_a_blocked_plan_starts_nothing_and_leaves_the_guard_free(monkeypatch):
    from src.self_update import UpdateBlocked

    updater, _, runner, _, _ = _updater(
        monkeypatch, {"auto_update_enabled": True}, plan=UpdateBlocked("nope"))

    assert updater.maybe_start(_Rel()) == "blocked"
    assert runner.jobs == []
    assert updater.busy is False


def test_success_persists_the_verified_file_and_reports_ready(monkeypatch):
    import os
    import tempfile

    updater, settings, runner, ready, downloads = _updater(
        monkeypatch, {"auto_update_enabled": True})
    finished = []
    rel = _Rel()

    assert updater.maybe_start(rel, on_finished=finished.append) == "started"
    runner.flush()

    assert len(downloads) == 1
    used_plan, used_dest = downloads[0]
    assert used_plan is _PLAN
    assert os.path.dirname(used_dest) == tempfile.gettempdir()
    assert used_dest != os.path.join(tempfile.gettempdir(), _PLAN.asset_name), (
        "Der Zielname muss pro Lauf eindeutig sein (s. download_dest)")
    assert settings.get("pending_update_path") == used_dest
    assert settings.get("pending_update_sha256") == "ab" * 32
    assert ready.releases == [rel]
    assert finished == [True]
    assert updater.busy is False


def test_failure_persists_nothing_and_frees_the_guard(monkeypatch):
    """Unbeobachteter Lauf: kein Dialog, keine Datei vorgemerkt, nur der
    Guard frei — der nächste Check versucht es erneut."""
    updater, settings, runner, ready, _ = _updater(
        monkeypatch, {"auto_update_enabled": True},
        result="Der Download ist fehlgeschlagen.")
    finished = []

    updater.maybe_start(_Rel(), on_finished=finished.append)
    runner.flush()

    assert settings.get("pending_update_path") == ""
    assert ready.releases == []
    assert finished == [False]
    assert updater.busy is False


def test_progress_reaches_the_caller_that_asked_for_it(monkeypatch):
    updater, _, runner, _, _ = _updater(
        monkeypatch, {"auto_update_enabled": True})
    seen = []

    updater.maybe_start(_Rel(), on_progress=seen.append)
    runner.flush()

    assert seen == ["Lade … 42 %"]


def test_a_second_check_during_the_download_joins_instead_of_downloading(
        monkeypatch):
    """Der Kern von R9: ein zweiter Auslöser, während der erste Download
    noch läuft, lädt nicht selbst — er erfährt aber, wie der laufende
    ausgeht (der Updates-Tab zeigt sonst ewig „wird geladen")."""
    updater, _, runner, _, downloads = _updater(
        monkeypatch, {"auto_update_enabled": True})
    first, second, progress = [], [], []

    assert updater.maybe_start(_Rel(), on_finished=first.append) == "started"
    assert updater.maybe_start(_Rel(), on_progress=progress.append,
                               on_finished=second.append) == "busy"
    runner.flush()

    assert len(downloads) == 1
    assert first == [True]
    assert second == [True]
    assert progress == ["Lade … 42 %"]


def test_a_manual_download_cannot_start_while_the_background_one_runs(
        monkeypatch):
    updater, _, runner, _, _ = _updater(monkeypatch, {"auto_update_enabled": True})

    updater.maybe_start(_Rel())

    assert updater.acquire_manual() is False
    runner.flush()
    assert updater.acquire_manual() is True


def test_no_background_download_starts_while_a_manual_one_runs(monkeypatch):
    updater, _, runner, _, _ = _updater(
        monkeypatch, {"auto_update_enabled": True})
    updater.acquire_manual()

    assert updater.maybe_start(_Rel()) == "busy"
    assert runner.jobs == []

    updater.release_manual()
    assert updater.maybe_start(_Rel()) == "started"


# --- manual_outcome: Ergebnis des Ein-Klick-Wegs ---------------------------

@pytest.mark.parametrize("ok, dialog_alive, expected", [
    # Fehler bei offenem Dialog: der Nutzer hat geklickt und wartet → Dialog.
    (False, True, "show_error"),
    # Fehler bei geschlossenem Dialog: niemand mehr da, der ihn liest.
    (False, False, "log"),
    # Erfolg bei offenem Dialog: sofort installieren, die App beendet sich.
    (True, True, "apply"),
    # Erfolg bei geschlossenem Dialog: NICHT hinter dem Rücken installieren —
    # und nicht liegen lassen (seit download_dest räumt kein Lauf sie weg).
    (True, False, "discard"),
])
def test_manual_outcome(ok, dialog_alive, expected):
    from src.auto_update import manual_outcome

    assert manual_outcome(ok, dialog_alive) == expected
