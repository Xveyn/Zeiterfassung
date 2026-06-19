from src.dialogs.conflicts_dialog import _entry_chosen, _fmt_entry_candidate


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
