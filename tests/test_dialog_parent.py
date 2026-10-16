"""Dialoge mit einem Widget statt eines Fensters als Parent (Xveyn#295).

`Update installieren` übergab den Reiter-Frame an `themed_showerror`;
`center_dialog_on_parent` rief darauf `wm_maxsize()` — das es nur auf
`Tk`/`Toplevel` gibt — und der Fehlerdialog starb, bevor er sichtbar wurde.

Tk-frei über Stubs, die Tk nachbilden: der Frame-Stub besitzt **nur**
`winfo_toplevel`, jeder andere Zugriff wirft `AttributeError` wie am echten
Frame. Wer den Frame statt seines Fensters benutzt, fällt also durch.
"""

import ast
import pathlib
from unittest.mock import MagicMock

import pytest

from src.theme import geometry


class _ToplevelStub:
    def winfo_toplevel(self):
        return self

    def wm_maxsize(self):
        return (1920, 1050)

    def winfo_viewable(self):
        return True

    def winfo_rootx(self):
        return 100

    def winfo_rooty(self):
        return 80

    def winfo_width(self):
        return 800

    def winfo_height(self):
        return 600


class _FrameStub:
    """Ein Widget, das kein Fenster ist: kennt nur sein Toplevel."""

    def __init__(self, toplevel):
        self._toplevel = toplevel

    def winfo_toplevel(self):
        return self._toplevel


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(geometry.platform, "system", lambda: "Linux")


def test_workarea_for_frame_uses_its_toplevel(linux):
    top = _ToplevelStub()
    assert geometry.workarea_for(_FrameStub(top)) == (0, 0, 1920, 1050)


def test_workarea_for_toplevel_unchanged(linux):
    top = _ToplevelStub()
    assert geometry.workarea_for(top) == (0, 0, 1920, 1050)


def test_center_dialog_with_frame_parent_binds_to_its_toplevel(linux):
    top = _ToplevelStub()
    dialog = MagicMock()
    dialog.winfo_reqwidth.return_value = 300
    dialog.winfo_reqheight.return_value = 200
    dialog._zeit_reveal = None

    geometry.center_dialog_on_parent(dialog, _FrameStub(top))

    # transient an das Fenster, nicht an den Frame
    dialog.transient.assert_called_once_with(top)
    # zentriert über dem Fenster: 100 + (800-300)//2, 80 + (600-200)//2
    dialog.geometry.assert_called_once_with("+350+280")


def _themed_calls_with_self_frame(path):
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        first = node.args[0]
        if (name.startswith("themed_")
                and isinstance(first, ast.Attribute) and first.attr == "frame"
                and isinstance(first.value, ast.Name) and first.value.id == "self"):
            hits.append(node.lineno)
    return hits


def test_updates_tab_passes_window_not_frame_to_themed_dialogs():
    hits = _themed_calls_with_self_frame(
        "src/dialogs/settings_dialog/tab_updates.py")
    assert hits == [], (
        f"themed_* mit self.frame als Parent in Zeilen {hits}: der Frame ist "
        "kein Fenster — self.frame.winfo_toplevel() übergeben (Xveyn#295).")
