"""Wie `App` den UpdateCoordinator verdrahtet (R11, Xveyn#123).

Der Update-Lebenszyklus selbst liegt in `src/update_coordinator.py` und wird
in `test_update_coordinator*.py` geprüft. Hier bleibt, was `App` behält: den
Tray-Eintrag und den Gurt vor `root.destroy()`.
"""

from unittest.mock import MagicMock

from src.ui import App


def test_tray_menu_offers_update_check():
    """Der Eintrag hängt in derselben actions-Liste wie die anderen
    Tray-Aktionen — damit rendern ihn beide Backends (pystray/NSStatusItem)."""
    fake = MagicMock()
    labels = [label for label, _cb, _vis in App._tray_actions(fake)]
    assert "Nach Updates suchen" in labels
    entry = next(a for a in App._tray_actions(fake) if a[0] == "Nach Updates suchen")
    assert entry[2] is None          # immer sichtbar, kein Settings-Gate
    assert callable(entry[1])


def test_quit_with_sync_push_destroys_the_window_even_if_applying_raises(monkeypatch):
    """F3-Zusage: NICHTS zwischen dem Anwenden und `root.destroy()` darf das
    Beenden aufhalten. Bleibt wider Erwarten doch eine Exception uebrig,
    wird sie geloggt — das Fenster geht trotzdem zu."""
    fake = MagicMock()
    fake._single_instance = None
    fake._updates.apply_pending_on_quit.side_effect = OSError(
        "kein Platz mehr in %TEMP%")

    App._quit_with_sync_push(fake)

    fake._updates.apply_pending_on_quit.assert_called_once_with()
    fake.root.destroy.assert_called_once_with()


def test_quit_applies_the_pending_update_before_destroying_the_window():
    """Die Reihenfolge ist die Zusage: erst anwenden, dann `destroy()` —
    umgekehrt hätte `apply_pending_on_quit` kein Gegenüber mehr, und unter
    Windows startet der Helfer erst, wenn die App weg ist."""
    fake = MagicMock()
    fake._single_instance = None
    order = []
    fake._updates.apply_pending_on_quit.side_effect = lambda: order.append("apply")
    fake.root.destroy.side_effect = lambda: order.append("destroy")

    App._quit_with_sync_push(fake)

    assert order == ["apply", "destroy"]


def test_settings_dialog_gets_the_coordinators_auto_updater(monkeypatch):
    """Updates-Tab und Start-Check müssen DENSELBEN AutoUpdater teilen (R9),
    sonst gäbe es wieder zwei Guards. pyright meldet einen Tippfehler an
    dieser Stelle nur als Warnung — deshalb dieser Test."""
    captured = {}
    monkeypatch.setattr("src.ui.open_settings_dialog",
                        lambda *a, **k: captured.update(k))
    fake = MagicMock()

    App._open_settings(fake)

    assert captured["auto_updater"] is fake._updates.auto_updater


def test_tray_update_entry_runs_the_coordinator_check():
    """Der Tray-Eintrag marshallt auf den Tk-Thread (wie alle Einträge) und
    landet beim Coordinator — nicht mehr in einer App-Methode."""
    fake = MagicMock()
    entry = next(a for a in App._tray_actions(fake) if a[0] == "Nach Updates suchen")

    entry[1]()

    fake.root.after.assert_called_once_with(0, fake._updates.tray_check)
