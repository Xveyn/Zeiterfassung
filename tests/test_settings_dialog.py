"""build_oauth_enable_task: fn/on_done-Kontrakt eines OAuth-Aktivieren-Toggles,
headless (der Dialog selbst ist Tk-gebunden, M16)."""

from unittest.mock import MagicMock

import src.dialogs.settings_dialog as sd
from src.dialogs.settings_dialog import build_oauth_enable_task


class _FakeSettings:
    def __init__(self):
        self.sets = []

    def set(self, key, value):
        self.sets.append((key, value))


class _FakeCheckbox:
    """Fake tk.Checkbutton: steuerbares winfo_exists + config-Rekorder."""
    def __init__(self, alive=True):
        self._alive = alive
        self.config_calls = []

    def winfo_exists(self):
        return self._alive

    def config(self, **kwargs):
        self.config_calls.append(kwargs)


class _FakeVar:
    def __init__(self):
        self.value = True

    def set(self, v):
        self.value = v


def _build(*, service_ok=True, alive=True, on_success_ui=None):
    settings = _FakeSettings()
    checkbox = _FakeCheckbox(alive=alive)
    var = _FakeVar()
    on_change = MagicMock()

    def service_fn():
        if not service_ok:
            raise RuntimeError("boom")

    fn, on_done = build_oauth_enable_task(
        service_fn=service_fn, settings=settings, setting_key="sync_enabled",
        checkbox=checkbox, toggle_var=var, on_change=on_change,
        dialog=object(), error_title="Titel",
        on_success_dialog_ui=on_success_ui,
    )
    return settings, checkbox, var, on_change, fn, on_done


def test_success_persists_and_updates_ui(monkeypatch):
    monkeypatch.setattr(sd.messagebox, "showerror", lambda *a, **k: None)
    ui = MagicMock()
    settings, checkbox, var, on_change, fn, on_done = _build(on_success_ui=ui)
    on_done(fn())
    assert settings.sets == [("sync_enabled", True)]
    on_change.assert_called_once_with()
    assert {"state": "normal"} in checkbox.config_calls
    ui.assert_called_once_with()
    assert var.value is True  # kein Revert


def test_success_persists_even_when_dialog_closed(monkeypatch):
    monkeypatch.setattr(sd.messagebox, "showerror", lambda *a, **k: None)
    ui = MagicMock()
    settings, checkbox, var, on_change, fn, on_done = _build(alive=False,
                                                             on_success_ui=ui)
    on_done(fn())
    assert settings.sets == [("sync_enabled", True)]   # Persistenz überlebt
    on_change.assert_called_once_with()                 # root-scoped, läuft
    assert checkbox.config_calls == []                  # kein Widget-Zugriff
    ui.assert_not_called()                              # Dialog-Kosmetik übersprungen


def test_failure_no_persist_and_reverts(monkeypatch):
    errors = []
    monkeypatch.setattr(sd.messagebox, "showerror",
                        lambda *a, **k: errors.append(a))
    settings, checkbox, var, on_change, fn, on_done = _build(service_ok=False)
    on_done(fn())
    assert settings.sets == []          # keine Persistenz bei Fehler
    on_change.assert_not_called()
    assert {"state": "normal"} in checkbox.config_calls
    assert var.value is False           # Revert
    assert errors                       # Fehler-Messagebox gezeigt


def test_failure_dialog_closed_skips_all_ui(monkeypatch):
    errors = []
    monkeypatch.setattr(sd.messagebox, "showerror",
                        lambda *a, **k: errors.append(a))
    settings, checkbox, var, on_change, fn, on_done = _build(service_ok=False,
                                                             alive=False)
    on_done(fn())
    assert settings.sets == []
    on_change.assert_not_called()
    assert checkbox.config_calls == []
    assert var.value is True            # kein Revert (Dialog weg)
    assert errors == []


def test_success_without_on_success_ui(monkeypatch):
    monkeypatch.setattr(sd.messagebox, "showerror", lambda *a, **k: None)
    settings, checkbox, var, on_change, fn, on_done = _build(on_success_ui=None)
    on_done(fn())  # darf nicht werfen
    assert settings.sets == [("sync_enabled", True)]
    assert {"state": "normal"} in checkbox.config_calls
