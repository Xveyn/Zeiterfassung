from unittest.mock import MagicMock

import pytest

from src.ui import App


def _app(state="normal", tray=None):
    fake = MagicMock()
    fake.root.state.return_value = state
    fake._tray = tray
    fake._marshal_to_ui.side_effect = lambda fn, force=False: fn()
    fake._show_unpair_notice.side_effect = lambda *a: App._show_unpair_notice(fake, *a)
    return fake


@pytest.mark.parametrize("state", ["normal", "zoomed"])
def test_a_visible_window_gets_a_dialog(monkeypatch, state):
    shown = []
    monkeypatch.setattr("src.ui.themed_showinfo", lambda *a: shown.append(a))
    tray = MagicMock()

    App._on_mobile_unpaired(_app(state, tray), "phone-0001", "Pixel")

    assert len(shown) == 1 and "Pixel" in shown[0][2]
    tray.notify.assert_not_called()


def test_a_hidden_window_with_a_tray_gets_a_toast(monkeypatch):
    shown = []
    monkeypatch.setattr("src.ui.themed_showinfo", lambda *a: shown.append(a))
    tray = MagicMock()

    App._on_mobile_unpaired(_app("withdrawn", tray), "phone-0001", "Pixel")

    assert shown == []
    (text,), _ = tray.notify.call_args
    assert "Pixel" in text


def test_a_hidden_window_without_a_tray_only_logs_the_id_never_the_name(monkeypatch, caplog):
    shown = []
    monkeypatch.setattr("src.ui.themed_showinfo", lambda *a: shown.append(a))

    with caplog.at_level("INFO", logger="src.ui"):
        App._on_mobile_unpaired(_app("withdrawn", None), "phone-0001", "Pixel von Sven")

    assert shown == []
    assert "phone-0001" in caplog.text and "Pixel von Sven" not in caplog.text


def test_a_failing_notify_does_not_escape(monkeypatch):
    tray = MagicMock()
    tray.notify.side_effect = RuntimeError("D-Bus weg")

    App._on_mobile_unpaired(_app("withdrawn", tray), "phone-0001", "Pixel")      # wirft nicht


def test_a_failing_dialog_does_not_escape(monkeypatch):
    def boom(*_a):
        raise RuntimeError("Fenster zerstört")
    monkeypatch.setattr("src.ui.themed_showinfo", boom)

    App._on_mobile_unpaired(_app("normal", None), "phone-0001", "Pixel")        # wirft nicht


def test_it_goes_through_the_ui_thread_marshal():
    fake = _app("normal", None)
    fake._marshal_to_ui.side_effect = lambda fn, force=False: None             # nichts läuft sofort

    App._on_mobile_unpaired(fake, "phone-0001", "Pixel")

    fake._marshal_to_ui.assert_called_once()
    fake._show_unpair_notice.assert_not_called()
