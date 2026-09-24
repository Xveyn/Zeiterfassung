"""Systemskalierung unter Windows (#157): DPI-Awareness und Systemfaktor.

Die Win32-Aufrufe selbst sind nicht Teil dieser Tests — sie kommen als
Funktionen herein. Geprüft wird die Entscheidung darum herum, vor allem die
beiden Zusagen, an denen der Umbau hängt: außerhalb von Windows passiert
**nichts** (macOS ist nicht testbar, der Weg muss dort ein No-op sein), und
ohne gesetzte Awareness bleibt der Faktor 1,0 — sonst streckte Windows das
Fenster und die App skalierte obendrauf.
"""

import pytest

from src import dpi


def _fail():
    raise AssertionError("darf außerhalb von Windows nicht aufgerufen werden")


@pytest.mark.parametrize("value,expected", [
    (96, 1.0),
    (120, 1.25),
    (144, 1.5),
    (168, 1.75),
    (192, 2.0),
])
def test_scale_from_dpi(value, expected):
    assert dpi.scale_from_dpi(value) == expected


@pytest.mark.parametrize("value", [None, 0, -96])
def test_scale_from_dpi_without_usable_value_is_neutral(value):
    assert dpi.scale_from_dpi(value) == 1.0


@pytest.mark.parametrize("system", ["Darwin", "Linux"])
def test_init_system_scale_is_a_noop_outside_windows(system):
    assert dpi.init_system_scale(system, set_aware=_fail, get_dpi=_fail) == 1.0


def test_init_system_scale_uses_system_dpi_once_aware():
    calls = []
    factor = dpi.init_system_scale(
        "Windows", set_aware=lambda: calls.append("aware") or True,
        get_dpi=lambda: 144)
    assert factor == 1.5
    assert calls == ["aware"]


def test_init_system_scale_stays_neutral_when_awareness_fails():
    """Ohne Awareness streckt Windows das Fenster selbst — ein zusätzlicher
    Faktor skalierte doppelt."""
    factor = dpi.init_system_scale(
        "Windows", set_aware=lambda: False, get_dpi=lambda: 144)
    assert factor == 1.0


def test_init_system_scale_remembers_the_factor(monkeypatch):
    monkeypatch.setattr(dpi, "_system_scale", 1.0)
    dpi.init_system_scale("Windows", set_aware=lambda: True, get_dpi=lambda: 120)
    assert dpi.system_scale() == 1.25


class _FakeRoot:
    def __init__(self):
        self.calls = []

        class _Tk:
            def call(_self, *args):
                self.calls.append(args)

        self.tk = _Tk()


def test_pin_tk_scaling_sets_the_96_dpi_value_on_windows():
    """Tk leitet `tk scaling` in einem DPI-aware Prozess aus der echten
    Auflösung ab und vergrößerte Punkt-Schriften damit selbst — zusätzlich zu
    `init_fonts`. Festgenagelt auf 96 dpi bleibt `init_fonts` der eine Hebel."""
    root = _FakeRoot()
    dpi.pin_tk_scaling(root, "Windows")
    assert root.calls == [("tk", "scaling", 96 / 72)]


@pytest.mark.parametrize("system", ["Darwin", "Linux"])
def test_pin_tk_scaling_leaves_other_platforms_alone(system):
    """Auf macOS wirkt `tk scaling` auf Pixel- statt Punkt-Schriften — ein
    Festnageln veränderte dort die Schriftgrößen."""
    root = _FakeRoot()
    dpi.pin_tk_scaling(root, system)
    assert root.calls == []


def test_scale_hint_is_silent_at_100_percent():
    assert dpi.scale_hint(1.0) is None


def test_scale_hint_names_the_windows_percentage():
    hint = dpi.scale_hint(1.5)
    assert hint is not None
    assert "150 %" in hint
