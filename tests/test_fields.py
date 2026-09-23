"""Tests für FieldSet (settings_dialog/fields.py, #132) — mit Fakes statt Tk."""

import pytest

from src.dialogs.settings_dialog.fields import FieldSet


class FakeVar:
    def __init__(self, value):
        self.value = value
        self.traces = []
        self.set_log = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        self.set_log.append(value)
        for cb in self.traces:
            cb("PY_VAR0", "", "write")

    def trace_add(self, mode, cb):
        assert mode == "write"
        self.traces.append(cb)


class FakeEvent:
    def __init__(self, widget):
        self.widget = widget


class FakeText:
    """Ahmt tk.Text nach: Modified-Flag + <<Modified>> bei jedem Flag-Wechsel."""

    def __init__(self, content=""):
        self.content = content
        self.modified = bool(content)   # insert beim Aufbau setzt das Flag
        self.handlers = []

    def get(self, start, end):
        assert (start, end) == ("1.0", "end-1c")
        return self.content

    def delete(self, start, end):
        self._change("")

    def insert(self, index, text):
        self._change(self.content + text)

    def bind(self, seq, fn, add=None):
        assert seq == "<<Modified>>" and add == "+"
        self.handlers.append(fn)

    def edit_modified(self, flag=None):
        if flag is None:
            return self.modified
        if flag != self.modified:
            self.modified = flag
            self._fire()

    def type(self, text):
        self._change(self.content + text)

    def _change(self, content):
        self.content = content
        if not self.modified:
            self.modified = True
            self._fire()

    def _fire(self):
        for fn in list(self.handlers):
            fn(FakeEvent(self))


def test_values_reads_vars_and_texts():
    fs = FieldSet()
    fs.add("name", FakeVar("Anna"))
    fs.add("on", FakeVar(True))
    fs.add_text("body", FakeText("Hallo\nWelt"))
    assert fs.values() == {"name": "Anna", "on": True, "body": "Hallo\nWelt"}


def test_values_never_parses():
    # "abc" im Stundenfeld bleibt Text — values() läuft bei jedem Tastendruck
    # und darf nicht werfen.
    fs = FieldSet()
    fs.add("hours", FakeVar("abc"))
    assert fs.values() == {"hours": "abc"}


def test_read_transforms_the_value():
    fs = FieldSet()
    fs.add("scale", FakeVar(101.3), read=lambda v: round(v / 5) * 5)
    assert fs.values() == {"scale": 100}


def test_add_returns_the_var():
    var = FakeVar("x")
    assert FieldSet().add("k", var) is var


def test_duplicate_key_raises():
    fs = FieldSet()
    fs.add("k", FakeVar(1))
    with pytest.raises(ValueError):
        fs.add("k", FakeVar(2))
    with pytest.raises(ValueError):
        fs.add_text("k", FakeText())


def test_var_write_notifies():
    fs = FieldSet()
    var = fs.add("k", FakeVar("a"))
    calls = []
    fs.on_edit(lambda: calls.append(1))
    var.set("b")
    assert calls == [1]


def test_text_typing_notifies_every_time():
    fs = FieldSet()
    text = fs.add_text("body", FakeText("Hallo"))
    calls = []
    fs.on_edit(lambda: calls.append(1))
    text.type("!")
    text.type("?")
    # Ohne Zurücksetzen des Modified-Flags käme nur das erste Tippen an.
    assert calls == [1, 1]


def test_add_text_resets_flag_from_initial_insert():
    text = FakeText("vorbelegt")
    FieldSet().add_text("body", text)
    assert text.modified is False


def test_load_sets_vars_and_texts():
    fs = FieldSet()
    var = fs.add("name", FakeVar("Ben"))
    text = fs.add_text("body", FakeText("neu"))
    fs.load({"name": "Anna", "body": "alt"})
    assert var.value == "Anna"
    assert text.content == "alt"


def test_load_ignores_unknown_and_missing_keys():
    fs = FieldSet()
    var = fs.add("name", FakeVar("Ben"))
    fs.load({"other": 1})
    assert var.value == "Ben"


def test_load_follows_registration_order():
    # Die Datumszeile klemmt den Tag bei JEDEM Schreibzugriff auf die
    # Monatslänge — Jahr und Monat müssen vor dem Tag stehen, egal in
    # welcher Reihenfolge das Dict kommt.
    order = []
    fs = FieldSet()
    for key in ("year", "month", "day"):
        var = fs.add(key, FakeVar("0"))
        var.traces.append(lambda *_a, k=key: order.append(k))
    fs.load({"day": "31", "month": "1", "year": "2026"})
    assert order == ["year", "month", "day"]


def test_keys_in_registration_order():
    fs = FieldSet()
    fs.add("b", FakeVar(1))
    fs.add_text("a", FakeText())
    assert fs.keys() == ["b", "a"]


def test_empty_fieldset():
    fs = FieldSet()
    assert fs.values() == {}
    fs.load({"x": 1})
