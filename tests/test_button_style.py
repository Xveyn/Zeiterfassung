"""Farben der Label-Buttons nach Rolle und Zustand (Tk-frei)."""

import pytest

from src.theme import palette
from src.theme.widgets import button_colors


def test_primary_enabled_uses_the_accent():
    c = button_colors(primary=True, enabled=True)
    assert c["bg"] == palette.ACCENT and c["hover_bg"] == palette.ACCENT_HOVER


def test_primary_disabled_is_dimmed_without_hover():
    c = button_colors(primary=True, enabled=False)
    assert c["bg"] == c["hover_bg"] == palette.ACCENT_DISABLED
    assert c["fg"] == palette.TEXT_MUTED


def test_secondary_enabled_is_neutral():
    c = button_colors(primary=False, enabled=True)
    assert c["bg"] == palette.CELL_BG and c["hover_bg"] == palette.ENTRY_BG


def test_secondary_disabled_only_dims_the_text():
    c = button_colors(primary=False, enabled=False)
    assert c["bg"] == c["hover_bg"] == palette.CELL_BG
    assert c["fg"] == palette.TEXT_MUTED


@pytest.mark.parametrize("primary", [True, False])
@pytest.mark.parametrize("enabled", [True, False])
def test_existing_helpers_use_the_same_colors(primary, enabled):
    """`set_primary_button_enabled`/`set_secondary_button_enabled` und der neue
    Rollenwechsel dürfen nicht auseinanderlaufen — sonst sieht derselbe Knopf
    je nach Weg anders aus."""
    from src.theme import widgets

    class Btn:
        def __init__(self):
            self._colors = {}
            self._label = self

        def config(self, **kw):
            pass

    btn = Btn()
    (widgets.set_primary_button_enabled if primary
     else widgets.set_secondary_button_enabled)(btn, enabled)
    assert btn._colors == button_colors(primary=primary, enabled=enabled)
