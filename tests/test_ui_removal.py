"""`ui.App` während „Zeiterfassung entfernen" (#50): was gesperrt ist.

Muster wie `test_ui_update_wiring.py`: `App`-Methoden gegen ein `MagicMock`,
die Entscheidungen selbst liegen Tk-frei in `removal.RemovalState`."""

from unittest.mock import MagicMock

from src.ui import App


def _fake(active):
    fake = MagicMock()
    fake._removal.active = active
    fake._removal.admits.return_value = not active
    return fake


def test_close_is_ignored_while_removing():
    """I1: der reguläre Beenden-Pfad würde ein vorbereitetes Update anwenden,
    das Verstecken im Tray ließe kein Fenster zurück."""
    fake = _fake(active=True)

    App._on_close(fake)

    fake._quit_with_sync_push.assert_not_called()
    fake.root.withdraw.assert_not_called()


def test_close_still_quits_when_not_removing():
    fake = _fake(active=False)
    fake.settings.get.return_value = False

    App._on_close(fake)

    fake._quit_with_sync_push.assert_called_once()


def test_settings_cannot_be_opened_while_removing(monkeypatch):
    opened = []
    monkeypatch.setattr("src.ui.open_settings_dialog",
                        lambda *a, **k: opened.append(k))

    App._open_settings(_fake(active=True))

    assert opened == []


def test_day_dialog_cannot_be_opened_while_removing():
    fake = _fake(active=True)

    App._open_dialog(fake, "2026-10-02")

    fake.conflicts_store.unresolved_entry_keys.assert_not_called()


def test_foreign_callbacks_are_dropped_while_removing():
    """I2: ein Update-Check darf `settings.json` nicht neu anlegen."""
    fake = _fake(active=True)

    App._marshal_to_ui(fake, lambda: None)

    fake.root.after.assert_not_called()


def test_the_removal_finish_callback_still_passes():
    fake = _fake(active=True)
    fake._removal.admits.side_effect = lambda forced: forced

    App._marshal_to_ui(fake, lambda: None, force=True)

    fake.root.after.assert_called_once()


def test_remove_application_refuses_while_a_sync_runs_and_touches_nothing():
    """I5 / Review Focus 5."""
    fake = _fake(active=False)
    fake._removal.begin.return_value = False

    assert App.remove_application(fake, True) is False

    fake._tray.stop.assert_not_called()
    fake._reminders.stop.assert_not_called()
    fake._bg.run.assert_not_called()
