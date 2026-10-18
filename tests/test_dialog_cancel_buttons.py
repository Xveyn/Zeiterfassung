"""Speichern-Dialoge brauchen einen Abbrechen-Knopf (Xveyn#320).

UI wird hier nicht automatisiert getestet (s. CLAUDE.md, „Getestet wird Logik,
nicht UI"); wie `test_dialog_reveal.py` prüft das der Quelltext.
"""
import pathlib

import pytest

DIALOGS = pathlib.Path(__file__).resolve().parent.parent / "src" / "dialogs"


@pytest.mark.parametrize("name", ["entry_dialog.py", "category_dialog.py"])
def test_save_dialog_has_cancel_button(name):
    source = (DIALOGS / name).read_text(encoding="utf-8")
    assert '"Abbrechen"' in source


def test_category_dialog_has_no_misleading_close_button():
    source = (DIALOGS / "category_dialog.py").read_text(encoding="utf-8")
    assert '"Schließen"' not in source
