"""UpdatesTab._maybe_start_auto_update: der stille Automatik-Download aus dem
Updates-Tab (Abschluss-Review F2).

Gegenstueck zu `test_ui_update_routing.py::
test_maybe_auto_update_reuses_pending_download_without_redownloading` — die
Regel „liegt schon eine geprüfte Datei, wird NICHT erneut geladen" galt bis
zum Abschluss-Review nur auf der ui.py-Seite. Duck-Typed Stand-in wie in
test_tab_updates_apply.py: die Methode fasst nur `self._settings` und
`self._start_self_update` an.
"""

from types import MethodType
from unittest.mock import MagicMock

from src.dialogs.settings_dialog.tab_updates import UpdatesTab


class _FakeSettings:
    def __init__(self, data=None):
        self._data = data or {}

    def get(self, key):
        return self._data.get(key, "")


def _fake_tab(settings_data):
    fake = MagicMock()
    fake._settings = _FakeSettings(settings_data)
    fake._can_self_update = True
    fake._updating = False
    fake._maybe_start_auto_update = MethodType(
        UpdatesTab._maybe_start_auto_update, fake)
    return fake


class _Rel:
    version = "1.9.0"


def test_auto_update_starts_when_enabled_and_nothing_is_pending():
    fake = _fake_tab({"auto_update_enabled": True})
    rel = _Rel()

    fake._maybe_start_auto_update(rel)

    fake._start_self_update.assert_called_once_with(rel, auto=True)


def test_auto_update_skips_when_a_verified_download_is_already_pending():
    """Kern von F2: ohne diesen Guard laedt jedes Oeffnen des Updates-Tabs
    dieselben ~65 MB erneut, obwohl die geprüfte Datei laengst bereitliegt
    und beim naechsten Beenden installiert wird."""
    fake = _fake_tab({
        "auto_update_enabled": True,
        "pending_update_path": r"C:\Temp\Zeiterfassung_Setup-4711-ab12cd34.exe",
    })

    fake._maybe_start_auto_update(_Rel())

    fake._start_self_update.assert_not_called()


def test_auto_update_skips_when_the_setting_is_off():
    fake = _fake_tab({"auto_update_enabled": False})

    fake._maybe_start_auto_update(_Rel())

    fake._start_self_update.assert_not_called()


def test_auto_update_skips_when_the_platform_cannot_self_update():
    fake = _fake_tab({"auto_update_enabled": True})
    fake._can_self_update = False

    fake._maybe_start_auto_update(_Rel())

    fake._start_self_update.assert_not_called()
