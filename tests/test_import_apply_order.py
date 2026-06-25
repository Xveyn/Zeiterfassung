"""Regression: der „Importiert"-Bestätigungsdialog muss erscheinen, solange
sein Parent (der Settings-Dialog) noch lebt. on_change() zerstört den Parent
(settings_dialog._after_import ruft dialog.destroy()), also muss themed_showinfo
VOR on_change() laufen — sonst TclError: bad window path name."""

from unittest.mock import Mock

import src.dialogs.import_dialog as import_dialog
from src.dialogs.import_dialog import _ImportSummaryDialog


def test_apply_shows_info_before_on_change(monkeypatch):
    calls = []

    monkeypatch.setattr(
        import_dialog, "themed_showinfo",
        lambda *a, **k: calls.append("info"),
    )

    dlg = _ImportSummaryDialog.__new__(_ImportSummaryDialog)
    dlg.parent = object()
    dlg.top = Mock()
    dlg.on_change = lambda: calls.append("on_change")

    dlg._apply([(lambda dec: None, [{"date": "2026-06-02"}])])

    assert calls == ["info", "on_change"], (
        "themed_showinfo muss vor on_change laufen (on_change zerstört den Parent)"
    )
