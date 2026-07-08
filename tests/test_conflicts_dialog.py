import types
from unittest.mock import MagicMock

from src.dialogs import conflicts_dialog
from src.dialogs.conflicts_dialog import (
    ConflictsDialog, _entry_chosen, _fmt_entry_candidate,
)


def _cand(slots=None, deleted=False, modified_at="2026-05-20T10:00:00Z", device_id="devABCDEF"):
    c = {"modified_at": modified_at, "device_id": device_id, "deleted": deleted}
    if slots is not None:
        c["slots"] = slots
    return c


def test_entry_chosen_carries_slots():
    cand = _cand(slots=[{"start": "08:00", "end": "16:00", "pause": 30, "kategorie": "Büro"}])
    assert _entry_chosen(cand) == {
        "slots": [{"start": "08:00", "end": "16:00", "pause": 30, "kategorie": "Büro"}],
        "deleted": False,
    }


def test_entry_chosen_multi_slot_not_lost():
    slots = [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "A"},
             {"start": "13:00", "end": "17:00", "pause": 30, "kategorie": "B"}]
    assert _entry_chosen(_cand(slots=slots))["slots"] == slots


def test_entry_chosen_deleted_candidate():
    assert _entry_chosen(_cand(slots=[], deleted=True)) == {"slots": [], "deleted": True}


def test_fmt_entry_candidate_lists_slots():
    cand = _cand(slots=[{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Büro"},
                        {"start": "13:00", "end": "17:00", "pause": 30, "kategorie": ""}])
    text = _fmt_entry_candidate(cand)
    assert "08:00—12:00" in text
    assert "Büro" in text
    assert "13:00—17:00" in text


def test_fmt_entry_candidate_deleted():
    assert "GELÖSCHT" in _fmt_entry_candidate(_cand(slots=[], deleted=True))


# --- Doppel-Resolve-Guard (Follow-up #134 / Audit H3) -----------------------
# Seit #122 sind die A/B-Buttons nur noch OPTISCH disabled — der command feuert
# weiter. Gegen einen zweiten Klick auf den bereits aufgelösten Konflikt schützt
# allein der _selected-Guard in _resolve_with_candidate (is-None-Check + Reset
# auf None nach dem Resolve). Headless getestet über einen Stub-`self`, ohne
# Tk-Root: sync.resolve_conflict wird gezählt, die Tk-berührenden Helfer sind
# gemockt.

def _dialog_stub(selected):
    stub = types.SimpleNamespace(
        _selected=selected,
        _data_lock=None,
        settings=MagicMock(),
        storage=MagicMock(),
        conflicts_store=MagicMock(),
        top=MagicMock(),
        btn_a=MagicMock(),
        btn_b=MagicMock(),
        detail_label=MagicMock(),
        _refresh_list=MagicMock(),
    )
    stub.settings.get.return_value = "devABCDEF"
    return stub


def _setting_conflict():
    return {"id": "c1", "kind": "setting", "key": "stundenlohn",
            "candidates": [{"value": "A"}, {"value": "B"}]}


def test_resolve_noop_when_nothing_selected(monkeypatch):
    calls = []
    monkeypatch.setattr(conflicts_dialog.sync, "resolve_conflict",
                        lambda *a, **k: calls.append(1))
    stub = _dialog_stub(selected=None)

    ConflictsDialog._resolve_with_candidate(stub, 0)

    assert calls == []
    stub._refresh_list.assert_not_called()


def test_resolve_resets_selected_after_success(monkeypatch):
    monkeypatch.setattr(conflicts_dialog.sync, "resolve_conflict",
                        lambda *a, **k: None)
    monkeypatch.setattr(conflicts_dialog, "set_secondary_button_enabled",
                        lambda *a, **k: None)
    stub = _dialog_stub(selected=_setting_conflict())

    ConflictsDialog._resolve_with_candidate(stub, 0)

    # Guard-Reset ist PFLICHT — sonst löst ein Folgeklick den alten Konflikt neu.
    assert stub._selected is None
    stub._refresh_list.assert_called_once()


def test_second_resolve_is_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(conflicts_dialog.sync, "resolve_conflict",
                        lambda *a, **k: calls.append(1))
    monkeypatch.setattr(conflicts_dialog, "set_secondary_button_enabled",
                        lambda *a, **k: None)
    stub = _dialog_stub(selected=_setting_conflict())

    ConflictsDialog._resolve_with_candidate(stub, 0)  # löst auf
    ConflictsDialog._resolve_with_candidate(stub, 0)  # muss No-op sein

    assert len(calls) == 1
    stub._refresh_list.assert_called_once()
