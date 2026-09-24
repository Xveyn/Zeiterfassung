"""Tests der Tk-freien Logik des Einstellungs-Dialogs (form_model.py, #132)."""

import pytest

from src.dialogs.settings_dialog.form_model import (
    SaveCoordinator, SaveOutcome, is_dirty
)


def test_identical_values_are_clean():
    assert not is_dirty({"a": 1, "b": "x"}, {"a": 1, "b": "x"})


def test_changed_value_is_dirty():
    assert is_dirty({"name": "Anna"}, {"name": "Ben"})


def test_number_and_numeric_string_are_equal():
    # Settings speichern 20.0, ein Entry liefert "20" — keine Änderung.
    assert not is_dirty({"h": 20.0}, {"h": "20"})
    assert not is_dirty({"h": 20}, {"h": 20.0})
    assert not is_dirty({"h": "20.5"}, {"h": 20.5})
    assert not is_dirty({"h": " 20 "}, {"h": 20})


def test_time_string_stays_a_string():
    assert not is_dirty({"t": "08:00"}, {"t": "08:00"})
    assert is_dirty({"t": "08:00"}, {"t": "08:30"})


def test_bool_is_not_confused_with_number():
    assert is_dirty({"on": True}, {"on": 1})
    assert is_dirty({"on": False}, {"on": "0"})


def test_line_endings_are_normalized():
    assert not is_dirty({"text": "a\r\nb"}, {"text": "a\nb"})


def test_trailing_whitespace_in_text_counts():
    assert is_dirty({"text": "Gruß"}, {"text": "Gruß "})


def test_missing_or_extra_key_is_dirty():
    assert is_dirty({"a": 1}, {"a": 1, "b": 2})
    assert is_dirty({"a": 1, "b": 2}, {"a": 1})


def test_nested_structures_are_compared_deeply():
    assert not is_dirty({"d": {"x": "1"}}, {"d": {"x": 1}})
    assert is_dirty({"l": [1, 2]}, {"l": [1, 3]})


def test_none_is_its_own_value():
    assert not is_dirty({"v": None}, {"v": None})
    assert is_dirty({"v": None}, {"v": ""})


# ---- SaveCoordinator (PR 2) ------------------------------------------------


class FakeTab:
    """Tab-Attrappe: `state` ist der Formularstand, `save` protokolliert."""

    def __init__(self, title="Tab", values=None, error=None, outcome=None):
        self.title = title
        self.state = dict(values or {})
        self.error = error
        self.outcome = outcome or SaveOutcome(saved=True)
        self.saved = []
        self.loaded = []

    def values(self):
        return dict(self.state)

    def validate(self):
        return self.error

    def save(self):
        self.saved.append(dict(self.state))
        return self.outcome

    def load(self, values):
        self.loaded.append(dict(values))
        self.state = dict(values)


def make(tabs, current="a", answer="cancel"):
    log = {"asked": [], "errors": [], "changes": 0, "restarts": 0}

    def ask(title):
        log["asked"].append(title)
        return answer

    def on_change():
        log["changes"] += 1

    def on_restart():
        log["restarts"] += 1

    coord = SaveCoordinator(
        tabs, current, ask=ask,
        show_error=lambda title, msg: log["errors"].append((title, msg)),
        on_change=on_change, on_restart=on_restart)
    return coord, log


def test_fresh_tabs_are_clean():
    coord, _ = make({"a": FakeTab(values={"x": "1"}), "b": FakeTab()})
    assert not coord.dirty()
    assert not coord.dirty("b")


def test_unknown_current_raises():
    with pytest.raises(KeyError):
        make({"a": FakeTab()}, current="zzz")


def test_edit_makes_current_dirty_and_undo_cleans():
    tab = FakeTab(values={"x": "1"})
    coord, _ = make({"a": tab})
    tab.state["x"] = "2"
    assert coord.dirty()
    tab.state["x"] = "1"
    assert not coord.dirty()


def test_switch_from_clean_tab_does_not_ask():
    coord, log = make({"a": FakeTab(), "b": FakeTab()})
    assert coord.request_switch("b")
    assert coord.current == "b"
    assert log["asked"] == []


def test_switch_to_current_tab_is_a_no_op():
    tab = FakeTab(values={"x": "1"})
    coord, log = make({"a": tab})
    tab.state["x"] = "2"
    assert coord.request_switch("a")
    assert log["asked"] == []


def test_switch_cancel_stays():
    tab = FakeTab(title="Arbeitszeit", values={"x": "1"})
    coord, log = make({"a": tab, "b": FakeTab()}, answer="cancel")
    tab.state["x"] = "2"
    assert not coord.request_switch("b")
    assert coord.current == "a"
    assert log["asked"] == ["Arbeitszeit"]
    assert tab.saved == [] and tab.loaded == []


def test_switch_discard_loads_baseline_and_moves_on():
    tab = FakeTab(values={"x": "1"})
    coord, log = make({"a": tab, "b": FakeTab()}, answer="discard")
    tab.state["x"] = "2"
    assert coord.request_switch("b")
    assert coord.current == "b"
    assert tab.loaded == [{"x": "1"}]
    assert tab.saved == []
    assert log["changes"] == 0


def test_switch_save_saves_rebaselines_and_moves_on():
    tab = FakeTab(values={"x": "1"})
    coord, log = make({"a": tab, "b": FakeTab()}, answer="save")
    tab.state["x"] = "2"
    assert coord.request_switch("b")
    assert tab.saved == [{"x": "2"}]
    assert log["changes"] == 1
    assert not coord.dirty("a")


def test_switch_save_with_validation_error_stays():
    tab = FakeTab(values={"x": "1"}, error=("Ungültig", "Mo: Ende vor Start"))
    coord, log = make({"a": tab, "b": FakeTab()}, answer="save")
    tab.state["x"] = "2"
    assert not coord.request_switch("b")
    assert coord.current == "a"
    assert log["errors"] == [("Ungültig", "Mo: Ende vor Start")]
    assert tab.saved == []
    assert coord.dirty()


def test_save_aborted_by_tab_keeps_dirty():
    # Autostart scheitert / Skalierungs-Rückfrage verneint: der Tab bricht
    # selbst ab (und hat seine Meldung schon gezeigt).
    tab = FakeTab(values={"x": "1"}, outcome=SaveOutcome(saved=False))
    coord, log = make({"a": tab, "b": FakeTab()}, answer="save")
    tab.state["x"] = "2"
    assert not coord.request_switch("b")
    assert not coord.save_current()
    assert coord.dirty()
    assert log["changes"] == 0
    assert log["errors"] == []


def test_switch_with_restart_returns_false():
    # Skalierung gespeichert: die App startet neu, der Dialog geht mit —
    # ein anschließendes Umschalten liefe ins Leere.
    tab = FakeTab(values={"s": 100}, outcome=SaveOutcome(saved=True, restart=True))
    coord, log = make({"a": tab, "b": FakeTab()}, answer="save")
    tab.state["s"] = 150
    assert not coord.request_switch("b")
    assert log["changes"] == 1
    assert log["restarts"] == 1


def test_save_current_on_clean_tab_does_nothing():
    tab = FakeTab(values={"x": "1"})
    coord, log = make({"a": tab})
    assert coord.save_current()
    assert tab.saved == []
    assert log["changes"] == 0


def test_save_current_saves_once_and_does_not_ask():
    tab = FakeTab(values={"x": "1"})
    coord, log = make({"a": tab})
    tab.state["x"] = "2"
    assert coord.save_current()
    assert tab.saved == [{"x": "2"}]
    assert log["changes"] == 1
    assert log["asked"] == []
    assert not coord.dirty()


def test_save_current_validation_error():
    tab = FakeTab(values={"x": "1"}, error=("T", "M"))
    coord, log = make({"a": tab})
    tab.state["x"] = "2"
    assert not coord.save_current()
    assert log["errors"] == [("T", "M")]


def test_save_current_with_restart_reports_success():
    tab = FakeTab(values={"s": 100}, outcome=SaveOutcome(saved=True, restart=True))
    coord, log = make({"a": tab})
    tab.state["s"] = 150
    assert coord.save_current()
    assert log["restarts"] == 1


def test_closed_after_restart_via_save_button():
    # Der Speichern-Knopf fragt danach den Dialog ab (Knopf grau/aktiv). Nach
    # dem Neustart ist der Tcl-Interpreter weg, schon `winfo_exists` wirft
    # dann TclError — der Aufrufer muss es vorher wissen.
    tab = FakeTab(values={"s": 100}, outcome=SaveOutcome(saved=True, restart=True))
    coord, _log = make({"a": tab})
    assert not coord.closed
    tab.state["s"] = 150
    coord.save_current()
    assert coord.closed


def test_closed_after_restart_via_leave():
    tab = FakeTab(values={"s": 100}, outcome=SaveOutcome(saved=True, restart=True))
    coord, _log = make({"a": tab, "b": FakeTab()}, answer="save")
    tab.state["s"] = 150
    coord.request_switch("b")
    assert coord.closed


def test_not_closed_after_plain_save():
    tab = FakeTab(values={"x": "1"})
    coord, _log = make({"a": tab})
    tab.state["x"] = "2"
    coord.save_current()
    assert not coord.closed


def test_close_clean_does_not_ask():
    coord, log = make({"a": FakeTab()})
    assert coord.request_close()
    assert log["asked"] == []


def test_close_dirty_follows_answer():
    for answer, expected in (("cancel", False), ("discard", True), ("save", True)):
        tab = FakeTab(values={"x": "1"})
        coord, _ = make({"a": tab}, answer=answer)
        tab.state["x"] = "2"
        assert coord.request_close() is expected, answer


def test_only_current_tab_is_asked_about():
    # Ein anderer Tab mit Änderungen kann gar nicht entstehen (Verlassen
    # fragt) — aber wenn doch, entscheidet nur der aktive.
    a, b = FakeTab(values={"x": "1"}), FakeTab(values={"y": "1"})
    coord, log = make({"a": a, "b": b})
    b.state["y"] = "2"
    assert coord.request_close()
    assert log["asked"] == []


def test_tab_without_values_is_never_dirty():
    coord, log = make({"a": FakeTab(values={}), "b": FakeTab()})
    assert coord.request_switch("b")
    assert log["asked"] == []


def test_rebaseline_whole_tab():
    tab = FakeTab(values={"cal": "primary"})
    coord, _ = make({"a": tab})
    tab.state["cal"] = "Arbeit"          # Liste nachgeladen, Klarname statt ID
    coord.rebaseline("a")
    assert not coord.dirty()


def test_rebaseline_fields_keeps_other_edits():
    tab = FakeTab(values={"cal": "primary", "device_name": ""})
    coord, _ = make({"a": tab})
    tab.state["device_name"] = "Laptop"  # Nutzer tippt …
    tab.state["cal"] = "Arbeit"          # … während die Liste nachlädt
    coord.rebaseline("a", ["cal"])
    assert coord.dirty()
    tab.state["device_name"] = ""
    assert not coord.dirty()


def test_switch_after_move_asks_about_new_current():
    a = FakeTab(title="A", values={"x": "1"})
    b = FakeTab(title="B", values={"y": "1"})
    coord, log = make({"a": a, "b": b}, answer="cancel")
    assert coord.request_switch("b")
    b.state["y"] = "2"
    assert not coord.request_switch("a")
    assert log["asked"] == ["B"]
