"""Die Listen-Tabs „SMTP" und „Webhooks" in den Einstellungen (R12, Xveyn#123).

Charakterisierung: diese Tests sind VOR dem Zusammenlegen der beiden Tabs
gegen den alten Code geschrieben und laufen danach unverändert weiter — sie
sind der Beleg, dass R12 nichts am Verhalten ändert.

Deshalb hängen sie an nichts, was der Umbau verschiebt: die Tabs werden über
`cls.__new__` ohne Tk-Aufbau erzeugt (die echten Methoden, echte Klassen-
attribute), und die Tk-Dialogfunktionen werden in dem Modul gepatcht, in dem
`_remove` tatsächlich definiert ist.
"""

import sys
from unittest.mock import MagicMock

import pytest

from src import keyring_store
from src.dialogs.settings_dialog import tab_smtp, tab_webhooks
from src.dialogs.settings_dialog.tab_smtp import SmtpTab
from src.dialogs.settings_dialog.tab_webhooks import WebhooksTab
from src.smtp_store import SmtpStoreReadOnly
from src.webhook_store import WebhookStoreReadOnly


class _ImmediateRunner:
    def run(self, fn, on_done=None):
        result = fn()
        if on_done is not None:
            on_done(result)


def _tab(cls, records, *, dialog_alive=True):
    """Ein Tab ohne Tk-Aufbau: echte Methoden, Listbox/Dialog als Mocks."""
    tab = cls.__new__(cls)
    tab.frame = MagicMock()
    tab._dialog = MagicMock()
    tab._dialog.winfo_exists.return_value = dialog_alive
    tab._parent = MagicMock(name="parent")
    tab._store = MagicMock()
    tab._store.get_all.return_value = records
    tab._runner = _ImmediateRunner()
    tab._listbox = MagicMock()
    tab._empty = MagicMock()
    tab._records = []
    return tab


def _dialog_module(cls):
    """Das Modul, in dem `_remove` lebt — dort sind die Dialogfunktionen
    gebunden, die ein Test ersetzen muss."""
    return sys.modules[cls._remove.__module__]


def _answer(monkeypatch, cls, yes):
    asked, errors = [], []
    module = _dialog_module(cls)
    monkeypatch.setattr(module, "themed_askyesno",
                        lambda parent, title, text: asked.append((parent, title, text)) or yes)
    monkeypatch.setattr(module, "themed_showerror",
                        lambda parent, title, text: errors.append((parent, title, text)))
    return asked, errors


def _select(tab, index):
    tab.refresh()
    tab._listbox.curselection.return_value = (index,)


def _rows(tab):
    return [c.args[1] for c in tab._listbox.insert.call_args_list]


_SMTP = [
    {"id": "s0", "name": "Firma", "enabled": True, "host": "smtp.example.org"},
    {"id": "s1", "name": "Privat", "enabled": False},
]
_HOOKS = [
    {"id": "w0", "name": "Zeitkonto", "enabled": True,
     "url": "https://hooks.example.org/zeit"},
    {"id": "w1", "name": "Archiv", "enabled": False,
     "url": "https://archiv.example.net:8443/in"},
    {"id": "w2", "name": "Kaputt", "enabled": True, "url": "keine-url"},
]


# --- Zeilen der Liste ------------------------------------------------------


def test_smtp_rows_show_mark_name_and_host():
    tab = _tab(SmtpTab, _SMTP)

    tab.refresh()

    assert _rows(tab) == [
        "  ✓  Firma  —  smtp.example.org",
        "  ○  Privat  —  ?",
    ]


def test_webhook_rows_show_the_hostname_of_the_url():
    tab = _tab(WebhooksTab, _HOOKS)

    tab.refresh()

    assert _rows(tab) == [
        "  ✓  Zeitkonto  —  hooks.example.org",
        "  ○  Archiv  —  archiv.example.net",
        "  ✓  Kaputt  —  ?",
    ]


@pytest.mark.parametrize("cls", [SmtpTab, WebhooksTab])
def test_refresh_clears_the_list_first(cls):
    tab = _tab(cls, [])

    tab.refresh()

    tab._listbox.delete.assert_called_once_with(0, "end")
    assert tab._listbox.insert.call_args_list == []


@pytest.mark.parametrize("cls", [SmtpTab, WebhooksTab])
def test_empty_list_shows_the_empty_text(cls):
    tab = _tab(cls, [])

    tab.refresh()

    tab._empty.grid.assert_called_once_with()
    tab._empty.grid_remove.assert_not_called()


def test_filled_list_hides_the_empty_text():
    tab = _tab(SmtpTab, _SMTP)

    tab.refresh()

    tab._empty.grid_remove.assert_called_once_with()
    tab._empty.grid.assert_not_called()


@pytest.mark.parametrize("cls", [SmtpTab, WebhooksTab])
def test_without_store_the_list_stays_empty(cls):
    tab = _tab(cls, [])
    tab._store = None

    tab.refresh()

    assert tab._records == []


# --- Hinzufügen / Bearbeiten ----------------------------------------------


@pytest.mark.parametrize("cls, module, opener", [
    (SmtpTab, tab_smtp, "open_smtp_dialog"),
    (WebhooksTab, tab_webhooks, "open_webhook_dialog"),
])
def test_add_and_edit_open_the_dialog_of_their_kind(monkeypatch, cls, module, opener):
    calls = []
    monkeypatch.setattr(module, opener, lambda *a, **k: calls.append((a, k)))
    tab = _tab(cls, _SMTP if cls is SmtpTab else _HOOKS)
    _select(tab, 0)

    tab._add()
    tab._edit()

    assert calls == [
        ((tab._dialog, tab._store, tab._runner), {"on_saved": tab.refresh}),
        ((tab._dialog, tab._store, tab._runner),
         {"record": tab._records[0], "on_saved": tab.refresh}),
    ]


@pytest.mark.parametrize("cls, module, opener", [
    (SmtpTab, tab_smtp, "open_smtp_dialog"),
    (WebhooksTab, tab_webhooks, "open_webhook_dialog"),
])
def test_add_without_store_and_edit_without_selection_do_nothing(
        monkeypatch, cls, module, opener):
    calls = []
    monkeypatch.setattr(module, opener, lambda *a, **k: calls.append((a, k)))
    tab = _tab(cls, [])
    tab.refresh()
    tab._listbox.curselection.return_value = ()

    tab._edit()
    tab._store = None
    tab._add()

    assert calls == []


# --- Entfernen -------------------------------------------------------------


@pytest.mark.parametrize("cls, title", [
    (SmtpTab, "SMTP-Konto entfernen"),
    (WebhooksTab, "Webhook entfernen"),
])
def test_remove_asks_first_and_does_nothing_on_no(monkeypatch, cls, title):
    asked, _ = _answer(monkeypatch, cls, yes=False)
    tab = _tab(cls, _SMTP if cls is SmtpTab else _HOOKS)
    _select(tab, 0)

    tab._remove()

    name = tab._records[0]["name"]
    assert asked == [(tab._dialog, title, f"„{name}“ wirklich entfernen?")]
    tab._store.delete.assert_not_called()


@pytest.mark.parametrize("cls", [SmtpTab, WebhooksTab])
def test_remove_without_selection_asks_nothing(monkeypatch, cls):
    asked, _ = _answer(monkeypatch, cls, yes=True)
    tab = _tab(cls, [])
    tab.refresh()
    tab._listbox.curselection.return_value = ()

    tab._remove()

    assert asked == []


def test_smtp_remove_deletes_the_secret_only_after_the_record(monkeypatch):
    """Erst die Datei, dann der Schlüsselbund — sonst stünde ein Konto ohne
    Passwort in der Datei, wenn das Schreiben scheitert."""
    _answer(monkeypatch, SmtpTab, yes=True)
    order = []
    monkeypatch.setattr(keyring_store, "delete_secret",
                        lambda account_id: order.append(("secret", account_id)))
    tab = _tab(SmtpTab, _SMTP)
    tab._store.delete.side_effect = lambda rid: order.append(("record", rid))
    _select(tab, 0)

    tab._remove()

    assert order == [("record", "s0"), ("secret", "s0")]


@pytest.mark.parametrize("error", [SmtpStoreReadOnly("schreibgeschützt"),
                                   OSError("Platte voll")])
def test_smtp_remove_keeps_the_secret_when_the_record_stays(monkeypatch, error):
    _, errors = _answer(monkeypatch, SmtpTab, yes=True)
    secrets = []
    monkeypatch.setattr(keyring_store, "delete_secret", secrets.append)
    tab = _tab(SmtpTab, _SMTP)
    tab._store.delete.side_effect = error
    _select(tab, 0)

    tab._remove()

    assert secrets == []
    assert errors == [(tab._dialog, "Nicht entfernt",
                       f"Das SMTP-Konto konnte nicht entfernt werden:\n\n{error}")]


def test_webhook_remove_never_touches_the_smtp_keyring(monkeypatch):
    _answer(monkeypatch, WebhooksTab, yes=True)
    secrets = []
    monkeypatch.setattr(keyring_store, "delete_secret", secrets.append)
    tab = _tab(WebhooksTab, _HOOKS)
    _select(tab, 0)

    tab._remove()

    tab._store.delete.assert_called_once_with("w0")
    assert secrets == []


def test_webhook_remove_forgets_its_keyring_entry_after_the_record(monkeypatch):
    _answer(monkeypatch, WebhooksTab, yes=True)
    order = []
    monkeypatch.setattr(keyring_store, "remove", lambda key: order.append(("remove", key)))
    tab = _tab(WebhooksTab, _HOOKS)
    tab._store.delete.side_effect = lambda rid: order.append(("delete", rid))
    _select(tab, 0)

    tab._remove()

    assert order == [("delete", "w0"), ("remove", "webhook:w0")]


def test_webhook_remove_keeps_the_keyring_entry_when_the_write_fails(monkeypatch):
    _answer(monkeypatch, WebhooksTab, yes=True)
    removed = []
    monkeypatch.setattr(keyring_store, "remove", removed.append)
    tab = _tab(WebhooksTab, _HOOKS)
    tab._store.delete.side_effect = OSError("Platte voll")
    _select(tab, 0)

    tab._remove()

    assert removed == []


@pytest.mark.parametrize("error", [WebhookStoreReadOnly("schreibgeschützt"),
                                   OSError("Platte voll")])
def test_webhook_remove_reports_a_failed_write(monkeypatch, error):
    _, errors = _answer(monkeypatch, WebhooksTab, yes=True)
    tab = _tab(WebhooksTab, _HOOKS)
    tab._store.delete.side_effect = error
    _select(tab, 0)

    tab._remove()

    assert errors == [(tab._dialog, "Nicht entfernt",
                       f"Der Webhook konnte nicht entfernt werden:\n\n{error}")]


@pytest.mark.parametrize("cls, error", [
    (SmtpTab, OSError("Platte voll")),
    (WebhooksTab, OSError("Platte voll")),
])
def test_a_failed_remove_goes_to_the_parent_when_the_dialog_is_closed(
        monkeypatch, cls, error):
    """Ein Schreibfehler darf nie still bleiben — auch nicht, wenn der
    Einstellungen-Dialog inzwischen zu ist."""
    monkeypatch.setattr(keyring_store, "delete_secret", lambda _id: None)
    _, errors = _answer(monkeypatch, cls, yes=True)
    tab = _tab(cls, _SMTP if cls is SmtpTab else _HOOKS, dialog_alive=False)
    tab._store.delete.side_effect = error
    _select(tab, 0)
    tab._listbox.reset_mock()

    tab._remove()

    assert [target for target, _t, _m in errors] == [tab._parent]
    tab._listbox.delete.assert_not_called()     # kein refresh auf totem Dialog


@pytest.mark.parametrize("cls", [SmtpTab, WebhooksTab])
def test_a_successful_remove_refreshes_the_open_list(monkeypatch, cls):
    monkeypatch.setattr(keyring_store, "delete_secret", lambda _id: None)
    _, errors = _answer(monkeypatch, cls, yes=True)
    tab = _tab(cls, _SMTP if cls is SmtpTab else _HOOKS)
    _select(tab, 0)
    tab._listbox.reset_mock()

    tab._remove()

    assert errors == []
    tab._listbox.delete.assert_called_once_with(0, "end")
