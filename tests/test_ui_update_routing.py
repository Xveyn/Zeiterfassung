"""Reine Routing-Entscheidung für Update-Benachrichtigungen (Toast vs.
Banner vs. schon gesehen) plus die Verdrahtung über App._on_update_check_result.
"""

from unittest.mock import MagicMock

from src.ui import App, _route_update_notification


class _Rel:
    def __init__(self, version):
        self.version = version


class _FakeSettings:
    def __init__(self, data):
        self._data = data

    def get(self, key):
        return self._data.get(key, "")

    def set(self, key, value):
        self._data[key] = value


class _FakeApp:
    """Duck-Typed Stand-in für App mit nur den gelesenen Attributen."""

    def __init__(self, tray, settings_data):
        self.settings = _FakeSettings(settings_data)
        self._tray = tray
        self._update_banner = MagicMock()


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
