"""Der Tk-freie Kern des gemeinsamen Listen-Tabs (R12, Xveyn#123): Zeilentext
und Lösch-Worker. Das Verhalten der beiden konkreten Tabs prüft
`test_record_list_tabs.py`."""

from unittest.mock import MagicMock

import pytest

from src.dialogs.settings_dialog._record_list_tab import remove_record, row_text


class _ReadOnly(Exception):
    pass


@pytest.mark.parametrize("record, detail, expected", [
    ({"name": "Firma", "enabled": True}, "smtp.example.org",
     "  ✓  Firma  —  smtp.example.org"),
    ({"name": "Archiv", "enabled": False}, "?", "  ○  Archiv  —  ?"),
    ({"enabled": True}, "x", "  ✓    —  x"),
])
def test_row_text(record, detail, expected):
    assert row_text(record, detail) == expected


def test_remove_record_runs_the_hook_after_a_successful_delete():
    order = []
    store = MagicMock()
    store.delete.side_effect = lambda rid: order.append(("delete", rid))

    result = remove_record(store, "a1", _ReadOnly,
                           after_delete=lambda rid: order.append(("hook", rid)))

    assert result == {"ok": True}
    assert order == [("delete", "a1"), ("hook", "a1")]


@pytest.mark.parametrize("error", [_ReadOnly("nur lesen"), OSError("voll")])
def test_remove_record_reports_a_failed_write_and_skips_the_hook(error):
    hook = MagicMock()
    store = MagicMock()
    store.delete.side_effect = error

    result = remove_record(store, "a1", _ReadOnly, after_delete=hook)

    assert result == {"ok": False, "error": error}
    hook.assert_not_called()


def test_remove_record_lets_unexpected_errors_through():
    """Nur der Schreibschutz und OSError sind erwartete Fehler — alles andere
    ist ein Bug und darf nicht als „Nicht entfernt" getarnt werden."""
    store = MagicMock()
    store.delete.side_effect = KeyError("id")

    with pytest.raises(KeyError):
        remove_record(store, "a1", _ReadOnly)
