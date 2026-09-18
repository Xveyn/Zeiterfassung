from unittest.mock import MagicMock

import pytest

from src.secret_migration import MigrationReport
from src.ui import App


def _app(state="normal", tray=None):
    fake = MagicMock()
    fake.root.state.return_value = state
    fake._tray = tray
    return fake


@pytest.mark.parametrize("state", ["normal", "zoomed"])
def test_notice_is_a_dialog_when_the_window_is_visible(monkeypatch, state):
    shown = []
    monkeypatch.setattr("src.ui.themed_showinfo", lambda *a: shown.append(a))
    App._on_secrets_migrated(_app(state), MigrationReport(token_moved=True))
    assert len(shown) == 1 and shown[0][1] == "Zugangsdaten im Schlüsselbund"


def test_notice_is_a_toast_when_started_minimized(monkeypatch):
    shown = []
    monkeypatch.setattr("src.ui.themed_showinfo", lambda *a: shown.append(a))
    tray = MagicMock()
    App._on_secrets_migrated(_app("withdrawn", tray), MigrationReport(token_moved=True))
    assert shown == []
    tray.notify.assert_called_once_with("Zugangsdaten liegen jetzt im Schlüsselbund.")


def test_no_notice_when_nothing_moved(monkeypatch):
    shown = []
    monkeypatch.setattr("src.ui.themed_showinfo", lambda *a: shown.append(a))
    tray = MagicMock()
    App._on_secrets_migrated(_app("normal", tray), MigrationReport())
    assert shown == [] and not tray.notify.called
