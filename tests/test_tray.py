# tests/test_tray.py
import pytest

from src import tray


@pytest.mark.parametrize("system,optin,expected", [
    ("Windows", None, True),
    ("Linux", None, False),
    ("Darwin", None, False),   # dormant-Default
    ("Darwin", "1", True),     # opt-in für den Mac-Tester
])
def test_is_supported_staging(system, optin, expected, monkeypatch):
    monkeypatch.setattr("src.tray.platform.system", lambda: system)
    if optin is None:
        monkeypatch.delenv("ZEIT_MACOS_TRAY", raising=False)
    else:
        monkeypatch.setenv("ZEIT_MACOS_TRAY", optin)
    assert tray.is_supported() is expected
