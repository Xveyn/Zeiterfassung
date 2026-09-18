"""Wie `App` den UpdateCoordinator verdrahtet (R11, Xveyn#123).

Der Update-Lebenszyklus selbst liegt in `src/update_coordinator.py` und wird
in `test_update_coordinator*.py` geprüft. Hier bleibt, was `App` behält: den
Tray-Eintrag und den Gurt vor `root.destroy()`.
"""

from unittest.mock import MagicMock

from src.ui import App


class _FakeSettings:
    def __init__(self, data):
        self._data = data

    def get(self, key):
        return self._data.get(key, "")


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
    fake.settings = _FakeSettings({"pending_update_path": r"C:\Temp\setup.exe"})
    fake._single_instance = None
    fake._apply_pending_update = MagicMock(
        side_effect=OSError("kein Platz mehr in %TEMP%"))

    App._quit_with_sync_push(fake)

    fake.root.destroy.assert_called_once_with()
