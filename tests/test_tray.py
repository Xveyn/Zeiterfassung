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


def test_build_menu_model_structure():
    from src.tray import build_menu_model
    show = lambda: None
    quit_ = lambda: None
    vis = lambda: True
    actions = [("Senden", lambda: None, None), ("Sync", lambda: None, vis)]
    model = build_menu_model(show, quit_, actions)
    assert [(e.kind, e.label) for e in model] == [
        ("item", "Anzeigen"),
        ("separator", None),
        ("item", "Senden"),
        ("item", "Sync"),
        ("separator", None),
        ("item", "Beenden"),
    ]
    assert model[0].callback is show
    assert model[-1].callback is quit_
    sync = next(e for e in model if e.label == "Sync")
    assert sync.visible is vis


def test_build_menu_model_no_actions_single_separator():
    from src.tray import build_menu_model
    model = build_menu_model(lambda: None, lambda: None, [])
    assert [e.kind for e in model] == ["item", "separator", "item"]
