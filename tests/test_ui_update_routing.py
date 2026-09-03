"""Reine Routing-Entscheidung für Update-Benachrichtigungen (Toast vs.
Banner vs. schon gesehen) plus die Verdrahtung über App._on_update_check_result.
"""

from types import MethodType
from unittest.mock import MagicMock

from src.ui import App, _route_update_notification


class _Rel:
    def __init__(self, release_id, is_prerelease=False):
        self.release_id = release_id
        self.version = release_id.split("-pre.")[0]
        self.is_prerelease = is_prerelease


class _FakeSettings:
    def __init__(self, data):
        self._data = data

    def get(self, key):
        return self._data.get(key, "")

    def set(self, key, value):
        self._data[key] = value

    def set_many(self, updates):
        self._data.update(updates)


class _FakeRunner:
    """Stand-in für BackgroundTaskRunner: sammelt Jobs, `flush()` führt sie aus
    wie der echte Runner (fn im Worker, on_done danach im UI-Thread)."""

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


class _FakeApp:
    """Duck-Typed Stand-in für App mit nur den gelesenen Attributen."""

    def __init__(self, tray, settings_data):
        self.settings = _FakeSettings(settings_data)
        self._tray = tray
        self._update_banner = MagicMock()
        self._bg = _FakeRunner()
        self._update_check_running = False
        self.root = MagicMock()
        self._sync = MagicMock()
        # Stub statt echter Automatik-Logik: die Routing-Tests in dieser
        # Datei prüfen Toast/Banner, nicht den Auto-Update-Trigger — der hat
        # eigene Tests weiter unten (App._maybe_auto_update direkt gebunden).
        self._maybe_auto_update = MagicMock()


class _FakeTray:
    def __init__(self):
        self.messages = []

    def notify(self, message, title="Zeiterfassung"):
        self.messages.append(message)


def test_tray_active_and_not_yet_shown_fires_toast():
    action, text = _route_update_notification(_Rel("1.9.0"), True, "")
    assert action == "toast"
    assert "1.9.0" in text


def test_tray_active_and_already_shown_does_nothing():
    action, text = _route_update_notification(_Rel("1.9.0"), True, "1.9.0")
    assert action == "none"
    assert text is None


def test_tray_active_different_version_already_shown_fires_toast():
    action, text = _route_update_notification(_Rel("1.9.0"), True, "1.8.0")
    assert action == "toast"


def test_no_tray_routes_to_banner():
    action, text = _route_update_notification(_Rel("1.9.0"), False, "")
    assert action == "banner"
    assert text is None


def test_no_tray_routes_to_banner_even_if_already_toast_shown():
    action, text = _route_update_notification(_Rel("1.9.0"), False, "1.9.0")
    assert action == "banner"


def test_on_update_check_result_persists_check_date_even_when_not_newer(monkeypatch):
    import src.ui as ui_module

    monkeypatch.setattr(ui_module, "today_iso", lambda: "2026-07-15")
    fake = _FakeApp(tray=None, settings_data={})
    App._on_update_check_result(fake, _Rel("1.9.0"), False)
    assert fake.settings.get("last_update_check_at") == "2026-07-15"
    fake._update_banner.show_if_newer.assert_not_called()


def test_on_update_check_result_tray_active_fires_toast_and_persists(monkeypatch):
    import src.ui as ui_module

    monkeypatch.setattr(ui_module, "today_iso", lambda: "2026-07-15")
    tray = _FakeTray()
    fake = _FakeApp(tray=tray, settings_data={"update_toast_shown_version": ""})
    App._on_update_check_result(fake, _Rel("1.9.0"), True)
    assert len(tray.messages) == 1
    assert "1.9.0" in tray.messages[0]
    assert fake.settings.get("update_toast_shown_version") == "1.9.0"
    fake._update_banner.show_if_newer.assert_not_called()


def test_on_update_check_result_no_tray_routes_to_banner(monkeypatch):
    import src.ui as ui_module

    monkeypatch.setattr(ui_module, "today_iso", lambda: "2026-07-15")
    fake = _FakeApp(tray=None, settings_data={"update_toast_shown_version": ""})
    rel = _Rel("1.9.0")
    App._on_update_check_result(fake, rel, True)
    fake._update_banner.show_if_newer.assert_called_once_with(rel)


def test_new_prerelease_number_fires_toast_again():
    # pre.1 wurde bereits gemeldet, pre.2 ist ein neuer Build.
    action, text = _route_update_notification(
        _Rel("1.19.0-pre.2", is_prerelease=True), True, "1.19.0-pre.1",
    )
    assert action == "toast"
    assert "Vorabversion 1.19.0-pre.2" in text


def test_same_prerelease_number_does_nothing():
    action, text = _route_update_notification(
        _Rel("1.19.0-pre.2", is_prerelease=True), True, "1.19.0-pre.2",
    )
    assert action == "none"
    assert text is None


def test_on_update_check_result_persists_release_id_not_base_version(monkeypatch):
    import src.ui as ui_module

    monkeypatch.setattr(ui_module, "today_iso", lambda: "2026-07-22")
    tray = _FakeTray()
    fake = _FakeApp(tray=tray, settings_data={"update_toast_shown_version": ""})
    App._on_update_check_result(fake, _Rel("1.19.0-pre.2", is_prerelease=True), True)
    assert fake.settings.get("update_toast_shown_version") == "1.19.0-pre.2"


# --- Tray-Menüpunkt „Nach Updates suchen" ---------------------------------

def _tray_app(monkeypatch, release, installed="1.19.1", settings_data=None):
    """App-Stand-in mit gestubbtem Update-Check. `release` ist das Ergebnis von
    check_for_update — eine Release, None (kein Fund/kein Netz) oder eine
    Exception-Instanz, die der Stub wirft."""
    import src.ui as ui_module

    monkeypatch.setattr(ui_module, "today_iso", lambda: "2026-07-27")
    monkeypatch.setattr(ui_module, "installed_release_id", lambda: installed)

    def fake_check(repo, include_prereleases, **kwargs):
        if isinstance(release, Exception):
            raise release
        return release

    monkeypatch.setattr(ui_module, "check_for_update", fake_check)
    fake = _FakeApp(tray=_FakeTray(), settings_data=settings_data or {})
    # Der Worker-Callback ist eine echte App-Methode: gebunden ans Fake-Objekt
    # läuft im Test derselbe Code wie in der App.
    fake._on_tray_check_update_result = MethodType(
        App._on_tray_check_update_result, fake)
    return fake


def test_tray_menu_offers_update_check():
    """Der Eintrag hängt in derselben actions-Liste wie die anderen
    Tray-Aktionen — damit rendern ihn beide Backends (pystray/NSStatusItem)."""
    fake = _FakeApp(tray=_FakeTray(), settings_data={})
    labels = [label for label, _cb, _vis in App._tray_actions(fake)]
    assert "Nach Updates suchen" in labels
    entry = next(a for a in App._tray_actions(fake) if a[0] == "Nach Updates suchen")
    assert entry[2] is None          # immer sichtbar, kein Settings-Gate
    assert callable(entry[1])


def test_tray_check_toasts_found_update_and_marks_it_shown(monkeypatch):
    fake = _tray_app(monkeypatch, _Rel("1.20.0"),
                     settings_data={"update_toast_shown_version": ""})

    App._tray_check_update(fake)
    fake._bg.flush()

    assert len(fake._tray.messages) == 1
    assert "1.20.0" in fake._tray.messages[0]
    assert fake.settings.get("last_update_check_at") == "2026-07-27"
    # Der Hintergrund-Check soll dieselbe Version nicht gleich nochmal toasten.
    assert fake.settings.get("update_toast_shown_version") == "1.20.0"


def test_tray_check_toasts_even_when_up_to_date(monkeypatch):
    """Der bewusste Unterschied zum Hintergrund-Check: hier hat der Nutzer
    gefragt, also bekommt er auch bei „nichts Neues" eine Antwort."""
    fake = _tray_app(monkeypatch, _Rel("1.19.1"),
                     settings_data={"update_toast_shown_version": ""})

    App._tray_check_update(fake)
    fake._bg.flush()

    assert fake._tray.messages == ["Du hast die aktuelle Version (1.19.1)."]
    assert fake.settings.get("update_toast_shown_version") == ""


def test_tray_check_reports_failure_without_burning_the_check_date(monkeypatch):
    """Eine gescheiterte Prüfung darf nicht als „heute schon geprüft" gelten —
    sonst schweigt auch der Hintergrund-Check für den Rest des Tages."""
    fake = _tray_app(monkeypatch, OSError("kein Netz"), settings_data={})

    App._tray_check_update(fake)
    fake._bg.flush()

    assert fake._tray.messages == ["Prüfung fehlgeschlagen — keine Verbindung?"]
    assert fake.settings.get("last_update_check_at") == ""


def test_tray_check_ignores_second_click_while_running(monkeypatch):
    fake = _tray_app(monkeypatch, _Rel("1.20.0"),
                     settings_data={"update_toast_shown_version": ""})

    App._tray_check_update(fake)
    App._tray_check_update(fake)   # Doppelklick, während der erste läuft

    assert len(fake._bg.jobs) == 1


def test_tray_check_is_possible_again_after_a_failure(monkeypatch):
    """Das Lauf-Flag muss auch im Fehlerfall wieder freigegeben werden, sonst
    ist der Menüpunkt nach einem Netzausfall dauerhaft tot."""
    fake = _tray_app(monkeypatch, OSError("kein Netz"), settings_data={})

    App._tray_check_update(fake)
    fake._bg.flush()
    App._tray_check_update(fake)

    assert len(fake._bg.jobs) == 1


# --- App._maybe_auto_update (Task 9, Nachtrag: periodischer Hintergrund-Check
# statt nur der manuelle Check im Updates-Tab) -----------------------------


def _bind_auto_update(fake):
    """Ersetzt den MagicMock-Stub aus _FakeApp durch die echte Methode,
    gebunden ans Fake-Objekt (Muster wie `_tray_app` weiter oben)."""
    fake._maybe_auto_update = MethodType(App._maybe_auto_update, fake)
    fake._auto_update_running = False
    return fake


def test_on_update_check_result_triggers_auto_update_when_newer(monkeypatch):
    import src.ui as ui_module

    monkeypatch.setattr(ui_module, "today_iso", lambda: "2026-07-15")
    fake = _FakeApp(tray=None, settings_data={"update_toast_shown_version": ""})
    rel = _Rel("1.9.0")

    App._on_update_check_result(fake, rel, True)

    fake._maybe_auto_update.assert_called_once_with(rel)


def test_on_update_check_result_does_not_trigger_auto_update_when_not_newer(monkeypatch):
    import src.ui as ui_module

    monkeypatch.setattr(ui_module, "today_iso", lambda: "2026-07-15")
    fake = _FakeApp(tray=None, settings_data={})

    App._on_update_check_result(fake, _Rel("1.9.0"), False)

    fake._maybe_auto_update.assert_not_called()


def test_maybe_auto_update_skips_when_setting_off():
    fake = _bind_auto_update(_FakeApp(tray=None, settings_data={"auto_update_enabled": False}))

    App._maybe_auto_update(fake, _Rel("1.9.0"))

    assert fake._bg.jobs == []


def test_maybe_auto_update_skips_when_platform_cannot_self_update(monkeypatch):
    import src.ui as ui_module

    monkeypatch.setattr(ui_module, "supports_self_update", lambda *a, **k: False)
    fake = _bind_auto_update(_FakeApp(tray=None, settings_data={"auto_update_enabled": True}))

    App._maybe_auto_update(fake, _Rel("1.9.0"))

    assert fake._bg.jobs == []


def test_maybe_auto_update_skips_when_already_running(monkeypatch):
    import src.ui as ui_module

    monkeypatch.setattr(ui_module, "supports_self_update", lambda *a, **k: True)
    fake = _bind_auto_update(_FakeApp(tray=None, settings_data={"auto_update_enabled": True}))
    fake._auto_update_running = True

    App._maybe_auto_update(fake, _Rel("1.9.0"))

    assert fake._bg.jobs == []


def test_maybe_auto_update_reuses_pending_download_without_redownloading(monkeypatch):
    """Liegt schon eine vorbereitete Datei (voriger Check hat schon geladen,
    App wurde noch nicht beendet), wird NICHT erneut geladen — nur der
    Banner erneut gezeigt."""
    import src.ui as ui_module

    monkeypatch.setattr(ui_module, "supports_self_update", lambda *a, **k: True)
    fake = _bind_auto_update(_FakeApp(tray=None, settings_data={
        "auto_update_enabled": True,
        "pending_update_path": r"C:\Temp\Zeiterfassung_Setup.exe",
    }))
    rel = _Rel("1.9.0")

    App._maybe_auto_update(fake, rel)

    assert fake._bg.jobs == []
    fake._update_banner.show_ready_to_install.assert_called_once_with(rel)


def test_maybe_auto_update_does_nothing_when_plan_is_blocked(monkeypatch):
    import src.ui as ui_module
    from src.self_update import UpdateBlocked

    monkeypatch.setattr(ui_module, "supports_self_update", lambda *a, **k: True)
    monkeypatch.setattr(ui_module, "plan_update", lambda *a, **k: UpdateBlocked("nope"))
    fake = _bind_auto_update(_FakeApp(tray=None, settings_data={"auto_update_enabled": True}))

    App._maybe_auto_update(fake, _Rel("1.9.0"))

    assert fake._bg.jobs == []
    assert fake._auto_update_running is False


def test_maybe_auto_update_downloads_and_persists_pending_update_on_success(monkeypatch):
    import platform

    import os
    import tempfile

    import src.ui as ui_module
    from src.self_update import DownloadedUpdate, UpdatePlan

    monkeypatch.setattr(ui_module, "supports_self_update", lambda *a, **k: True)
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    plan = UpdatePlan(asset_url="https://x/exe", asset_name="Zeiterfassung_Setup.exe",
                      sums_url="https://x/sums", target=r"C:\Apps\Z.exe")
    monkeypatch.setattr(ui_module, "plan_update", lambda *a, **k: plan)
    # Der tatsaechliche Zielpfad (local) wird von _maybe_auto_update selbst
    # ueber `self_update.download_dest` gebaut (wie im Updates-Tab) — NICHT
    # aus downloaded.path, das ist nur das Ergebnis der (gemockten)
    # download_and_verify_update. Der Name ist pro Lauf eindeutig, deshalb
    # wird er hier nicht vorhergesagt, sondern abgefangen und geprueft.
    downloaded = DownloadedUpdate(path="egal", sha256="ab" * 32)
    calls = []
    monkeypatch.setattr(
        ui_module, "download_and_verify_update",
        lambda plan_arg, dest, **k: calls.append((plan_arg, dest)) or downloaded)

    fake = _bind_auto_update(_FakeApp(tray=None, settings_data={"auto_update_enabled": True}))
    rel = _Rel("1.9.0")

    App._maybe_auto_update(fake, rel)
    fake._bg.flush()

    assert len(calls) == 1
    used_plan, used_dest = calls[0]
    assert used_plan is plan
    assert used_dest.startswith(tempfile.gettempdir())
    assert used_dest.endswith(".exe")
    assert used_dest != os.path.join(tempfile.gettempdir(), plan.asset_name), (
        "Der Zielname muss pro Lauf eindeutig sein — ein fester Name laesst "
        "zwei parallele Downloads in dieselbe Datei schreiben (F1)")
    assert fake.settings.get("pending_update_path") == downloaded.path
    assert fake.settings.get("pending_update_sha256") == downloaded.sha256
    assert fake._auto_update_running is False
    fake._update_banner.show_ready_to_install.assert_called_once_with(rel)


def test_maybe_auto_update_logs_and_resets_flag_on_download_failure(monkeypatch):
    """Kernanforderung: ein Fehlschlag im stillen Pfad zeigt KEINEN Dialog
    und setzt weder pending_update_path noch die Banner-Rückmeldung — nur
    der Guard wird zurückgesetzt, damit der nächste Check es erneut
    versucht."""
    import platform

    import src.ui as ui_module
    from src.self_update import UpdatePlan

    monkeypatch.setattr(ui_module, "supports_self_update", lambda *a, **k: True)
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    plan = UpdatePlan(asset_url="https://x/exe", asset_name="Zeiterfassung_Setup.exe",
                      sums_url="https://x/sums", target=r"C:\Apps\Z.exe")
    monkeypatch.setattr(ui_module, "plan_update", lambda *a, **k: plan)
    monkeypatch.setattr(ui_module, "download_and_verify_update",
                        lambda *a, **k: "Der Download ist fehlgeschlagen.")

    fake = _bind_auto_update(_FakeApp(tray=None, settings_data={"auto_update_enabled": True}))

    App._maybe_auto_update(fake, _Rel("1.9.0"))
    fake._bg.flush()

    assert fake.settings.get("pending_update_path") == ""
    assert fake._auto_update_running is False
    fake._update_banner.show_ready_to_install.assert_not_called()
