"""UpdateCoordinator (R11, Xveyn#123): Routing der Update-Benachrichtigung
(Toast vs. Banner vs. schon gesehen), Ergebnis des Start-Checks, Tray-Check
und Auslösen des stillen Downloads.

Bis R11 lagen diese Tests gegen `App`; die Assertions sind beim Umzug
wortgleich geblieben — nur Aufbau und Aufruf haben sich geändert.
"""

from unittest.mock import MagicMock

from src.update_coordinator import UpdateCoordinator, route_update_notification


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
        self.check_update_calls = []

    def run(self, fn, on_done=None):
        self.jobs.append((fn, on_done))

    def check_update(self, on_result):
        self.check_update_calls.append(on_result)

    def flush(self):
        jobs, self.jobs = self.jobs, []
        for fn, on_done in jobs:
            result = fn()
            if on_done is not None:
                on_done(result)


class _Harness:
    """Die Abhängigkeiten eines UpdateCoordinators unter denselben Namen, unter
    denen die Tests sie bis R11 an `App` fanden — so bleiben die Assertions
    wortgleich. `coordinator` ist das Objekt unter Test."""

    def __init__(self, tray, settings_data):
        self.settings = _FakeSettings(settings_data)
        self._tray = tray
        self._update_banner = MagicMock()
        self._bg = _FakeRunner()
        self.coordinator = UpdateCoordinator(
            self.settings, self._bg, self._update_banner, lambda: self._tray)
        # Stub statt echter Automatik-Logik: die Tests in dieser Datei prüfen
        # Toast/Banner, nicht die Auto-Update-Policy — die hat eigene Tests
        # in test_auto_update.py.
        self._auto_updater = MagicMock()
        self.coordinator.auto_updater = self._auto_updater


class _FakeTray:
    def __init__(self):
        self.messages = []

    def notify(self, message, title="Zeiterfassung"):
        self.messages.append(message)


def test_tray_active_and_not_yet_shown_fires_toast():
    action, text = route_update_notification(_Rel("1.9.0"), True, "")
    assert action == "toast"
    assert "1.9.0" in text


def test_tray_active_and_already_shown_does_nothing():
    action, text = route_update_notification(_Rel("1.9.0"), True, "1.9.0")
    assert action == "none"
    assert text is None


def test_tray_active_different_version_already_shown_fires_toast():
    action, text = route_update_notification(_Rel("1.9.0"), True, "1.8.0")
    assert action == "toast"


def test_no_tray_routes_to_banner():
    action, text = route_update_notification(_Rel("1.9.0"), False, "")
    assert action == "banner"
    assert text is None


def test_no_tray_routes_to_banner_even_if_already_toast_shown():
    action, text = route_update_notification(_Rel("1.9.0"), False, "1.9.0")
    assert action == "banner"


def test_on_update_check_result_persists_check_date_even_when_not_newer(monkeypatch):
    import src.update_coordinator as coordinator_module

    monkeypatch.setattr(coordinator_module, "today_iso", lambda: "2026-07-15")
    fake = _Harness(tray=None, settings_data={})
    fake.coordinator.on_check_result(_Rel("1.9.0"), False)
    assert fake.settings.get("last_update_check_at") == "2026-07-15"
    fake._update_banner.show_if_newer.assert_not_called()


def test_on_update_check_result_tray_active_fires_toast_and_persists(monkeypatch):
    import src.update_coordinator as coordinator_module

    monkeypatch.setattr(coordinator_module, "today_iso", lambda: "2026-07-15")
    tray = _FakeTray()
    fake = _Harness(tray=tray, settings_data={"update_toast_shown_version": ""})
    fake.coordinator.on_check_result(_Rel("1.9.0"), True)
    assert len(tray.messages) == 1
    assert "1.9.0" in tray.messages[0]
    assert fake.settings.get("update_toast_shown_version") == "1.9.0"
    fake._update_banner.show_if_newer.assert_not_called()


def test_on_update_check_result_no_tray_routes_to_banner(monkeypatch):
    import src.update_coordinator as coordinator_module

    monkeypatch.setattr(coordinator_module, "today_iso", lambda: "2026-07-15")
    fake = _Harness(tray=None, settings_data={"update_toast_shown_version": ""})
    rel = _Rel("1.9.0")
    fake.coordinator.on_check_result(rel, True)
    fake._update_banner.show_if_newer.assert_called_once_with(rel)


def test_new_prerelease_number_fires_toast_again():
    # pre.1 wurde bereits gemeldet, pre.2 ist ein neuer Build.
    action, text = route_update_notification(
        _Rel("1.19.0-pre.2", is_prerelease=True), True, "1.19.0-pre.1",
    )
    assert action == "toast"
    assert "Vorabversion 1.19.0-pre.2" in text


def test_same_prerelease_number_does_nothing():
    action, text = route_update_notification(
        _Rel("1.19.0-pre.2", is_prerelease=True), True, "1.19.0-pre.2",
    )
    assert action == "none"
    assert text is None


def test_on_update_check_result_persists_release_id_not_base_version(monkeypatch):
    import src.update_coordinator as coordinator_module

    monkeypatch.setattr(coordinator_module, "today_iso", lambda: "2026-07-22")
    tray = _FakeTray()
    fake = _Harness(tray=tray, settings_data={"update_toast_shown_version": ""})
    fake.coordinator.on_check_result(_Rel("1.19.0-pre.2", is_prerelease=True), True)
    assert fake.settings.get("update_toast_shown_version") == "1.19.0-pre.2"


# --- Tray-Menüpunkt „Nach Updates suchen" ---------------------------------

def _tray_app(monkeypatch, release, installed="1.19.1", settings_data=None):
    """Coordinator-Harness mit gestubbtem Update-Check. `release` ist das
    Ergebnis von check_for_update — eine Release, None (kein Fund/kein Netz)
    oder eine Exception-Instanz, die der Stub wirft."""
    import src.update_coordinator as coordinator_module

    monkeypatch.setattr(coordinator_module, "today_iso", lambda: "2026-07-27")
    monkeypatch.setattr(coordinator_module, "installed_release_id", lambda: installed)

    def fake_check(repo, include_prereleases, **kwargs):
        if isinstance(release, Exception):
            raise release
        return release

    monkeypatch.setattr(coordinator_module, "check_for_update", fake_check)
    fake = _Harness(tray=_FakeTray(), settings_data=settings_data or {})
    return fake


def test_tray_check_toasts_found_update_and_marks_it_shown(monkeypatch):
    fake = _tray_app(monkeypatch, _Rel("1.20.0"),
                     settings_data={"update_toast_shown_version": ""})

    fake.coordinator.tray_check()
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

    fake.coordinator.tray_check()
    fake._bg.flush()

    assert fake._tray.messages == ["Du hast die aktuelle Version (1.19.1)."]
    assert fake.settings.get("update_toast_shown_version") == ""


def test_tray_check_reports_failure_without_burning_the_check_date(monkeypatch):
    """Eine gescheiterte Prüfung darf nicht als „heute schon geprüft" gelten —
    sonst schweigt auch der Hintergrund-Check für den Rest des Tages."""
    fake = _tray_app(monkeypatch, OSError("kein Netz"), settings_data={})

    fake.coordinator.tray_check()
    fake._bg.flush()

    assert fake._tray.messages == ["Prüfung fehlgeschlagen — keine Verbindung?"]
    assert fake.settings.get("last_update_check_at") == ""


def test_tray_check_ignores_second_click_while_running(monkeypatch):
    fake = _tray_app(monkeypatch, _Rel("1.20.0"),
                     settings_data={"update_toast_shown_version": ""})

    fake.coordinator.tray_check()
    fake.coordinator.tray_check()   # Doppelklick, während der erste läuft

    assert len(fake._bg.jobs) == 1


def test_tray_check_is_possible_again_after_a_failure(monkeypatch):
    """Das Lauf-Flag muss auch im Fehlerfall wieder freigegeben werden, sonst
    ist der Menüpunkt nach einem Netzausfall dauerhaft tot."""
    fake = _tray_app(monkeypatch, OSError("kein Netz"), settings_data={})

    fake.coordinator.tray_check()
    fake._bg.flush()
    fake.coordinator.tray_check()

    assert len(fake._bg.jobs) == 1


# --- Auslöser des stillen Downloads (die Policy selbst: test_auto_update.py) --


def test_on_update_check_result_triggers_auto_update_when_newer(monkeypatch):
    import src.update_coordinator as coordinator_module

    monkeypatch.setattr(coordinator_module, "today_iso", lambda: "2026-07-15")
    fake = _Harness(tray=None, settings_data={"update_toast_shown_version": ""})
    rel = _Rel("1.9.0")

    fake.coordinator.on_check_result(rel, True)

    fake._auto_updater.maybe_start.assert_called_once_with(rel)


def test_on_update_check_result_does_not_trigger_auto_update_when_not_newer(monkeypatch):
    import src.update_coordinator as coordinator_module

    monkeypatch.setattr(coordinator_module, "today_iso", lambda: "2026-07-15")
    fake = _Harness(tray=None, settings_data={})

    fake.coordinator.on_check_result(_Rel("1.9.0"), False)

    fake._auto_updater.maybe_start.assert_not_called()


# --- Neu mit R11: Verträge, die es bisher nicht als Test gab --------------


def test_start_hands_the_check_result_to_on_check_result():
    """`start()` ersetzt den Aufruf `_bg.check_update(...)` aus
    `App.__init__`: genau ein Check, dessen Ergebnis im Coordinator landet."""
    fake = _Harness(tray=None, settings_data={})

    fake.coordinator.start()

    assert fake._bg.check_update_calls == [fake.coordinator.on_check_result]


def test_the_auto_updater_reports_ready_to_the_banner(monkeypatch):
    """Der Coordinator baut den AutoUpdater (R9) selbst — dessen `on_ready`
    muss beim Banner ankommen, sonst sieht niemand, dass ein vorbereitetes
    Update beim Beenden installiert wird."""
    import src.auto_update as auto_update

    monkeypatch.setattr(auto_update, "supports_self_update", lambda *a, **k: True)
    banner = MagicMock()
    settings = _FakeSettings({
        "auto_update_enabled": True,
        "pending_update_path": r"C:\Temp\Zeiterfassung_Setup-1-ab.exe",
    })
    coordinator = UpdateCoordinator(settings, _FakeRunner(), banner, lambda: None)
    rel = _Rel("1.9.0")

    assert coordinator.auto_updater.maybe_start(rel) == "pending"
    banner.show_ready_to_install.assert_called_once_with(rel)
