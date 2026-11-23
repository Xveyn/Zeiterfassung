import json

import pytest
from src.storage import Storage

D = "2026-11-03"


def _slot(start="08:00", end="12:00", pause=0, kat="", **extra):
    return {"start": start, "end": end, "pause": pause, "kategorie": kat, **extra}


def _disk(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "z.json")


@pytest.fixture
def st(path):
    return Storage(path, device_id="dev")


def test_without_note_entry_has_exactly_four_keys(st, path):
    st.save(D, [_slot()])
    entry = _disk(path)[D]
    assert list(entry) == ["slots", "modified_at", "device_id", "deleted"]
    assert "notiz" not in st.get(D)["slots"][0]


def test_note_goes_to_notes_dict(st, path):
    st.save(D, [_slot(notiz=" Kunde Mustermann ")])
    entry = _disk(path)[D]
    assert entry["slots"] == [_slot()]
    assert entry["notes"] == {"08:00": "Kunde Mustermann"}
    assert st.get(D)["slots"][0]["notiz"] == "Kunde Mustermann"
    assert st.get_all()[D]["slots"][0]["notiz"] == "Kunde Mustermann"


def test_save_without_notiz_inherits(st, path):
    st.save(D, [_slot(notiz="x")])
    st.save(D, [_slot(pause=15)])
    assert _disk(path)[D]["notes"] == {"08:00": "x"}
    assert st.get(D)["slots"][0]["notiz"] == "x"


def test_empty_notiz_clears_but_key_sticks(st, path):
    st.save(D, [_slot(notiz="x")])
    st.save(D, [_slot(notiz="")])
    assert _disk(path)[D]["notes"] == {}
    assert "notiz" not in st.get(D)["slots"][0]


def test_changed_start_drops_note(st, path):
    st.save(D, [_slot(notiz="x")])
    st.save(D, [_slot(start="09:00")])
    assert _disk(path)[D]["notes"] == {}


def test_tombstone_does_not_inherit(st, path):
    st.save(D, [_slot(notiz="x")])
    st.delete(D)
    st.save(D, [_slot()])
    assert _disk(path)[D]["notes"] == {}
    assert "notiz" not in st.get(D)["slots"][0]


def test_deleting_a_day_with_the_key_leaves_a_keyed_tombstone(st, path):
    st.save(D, [_slot(notiz="x")])
    st.delete(D)
    entry = _disk(path)[D]
    assert entry["deleted"] is True and entry["slots"] == []
    assert entry["notes"] == {}
    st.delete(D)
    assert _disk(path)[D]["notes"] == {}


def test_deleting_a_day_whose_notes_were_emptied_keeps_the_key(st, path):
    st.save(D, [_slot(notiz="x")])
    st.save(D, [_slot(notiz="")])
    st.delete(D)
    assert _disk(path)[D]["notes"] == {}


def test_recreating_after_a_keyed_tombstone_writes_the_key_and_inherits_nothing(st, path):
    st.save(D, [_slot(notiz="x")])
    st.delete(D)
    st.save(D, [_slot(notiz="")])
    assert _disk(path)[D]["notes"] == {}
    st.delete(D)
    st.save_many({D: {"slots": [_slot()]}})
    assert _disk(path)[D]["notes"] == {}
    assert "notiz" not in st.get(D)["slots"][0]


def test_recreating_after_a_keyed_tombstone_takes_a_new_note(st, path):
    st.save(D, [_slot(notiz="x")])
    st.delete(D)
    st.save(D, [_slot(notiz="y")])
    assert _disk(path)[D]["notes"] == {"08:00": "y"}


_NOTELESS_TOMBSTONE = """{
  "2026-11-03": {
    "slots": [],
    "modified_at": "2026-11-03T09:00:00Z",
    "device_id": "dev",
    "deleted": true
  }
}"""

_NOTELESS_RECREATED = """{
  "2026-11-03": {
    "slots": [
      {
        "start": "08:00",
        "end": "12:00",
        "pause": 0,
        "kategorie": ""
      }
    ],
    "modified_at": "2026-11-03T10:00:00Z",
    "device_id": "dev",
    "deleted": false
  }
}"""


def test_delete_and_recreate_without_notes_writes_todays_bytes(st, path, monkeypatch):
    import src.storage as storage_mod
    stamps = iter(["2026-11-03T08:00:00Z", "2026-11-03T09:00:00Z", "2026-11-03T10:00:00Z"])
    monkeypatch.setattr(storage_mod, "utc_now_iso", lambda: next(stamps))
    st.save(D, [_slot()])
    st.delete(D)
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == _NOTELESS_TOMBSTONE
    st.save(D, [_slot(notiz="")])
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == _NOTELESS_RECREATED


def test_save_many_inherits(st, path):
    st.save_many({D: {"slots": [_slot(notiz="x")]}})
    assert _disk(path)[D]["notes"] == {"08:00": "x"}
    st.save_many({D: {"slots": [_slot(pause=5)]}})
    assert _disk(path)[D]["notes"] == {"08:00": "x"}


def _foreign(path, entry):
    base = {"modified_at": "2026-11-03T10:00:00Z", "device_id": "o", "deleted": False}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({D: {**base, **entry}}, fh)
    return Storage(path, device_id="dev")


@pytest.mark.parametrize("notes", ["x", {"08:00": 5}, {"08:00": "a\nb"}, {"08:00": "y" * 300},
                                   {"08:00": "\ud800"}])
def test_foreign_notes_do_not_raise(path, notes):
    st = _foreign(path, {"slots": [_slot()], "notes": notes})
    slots = st.get(D)["slots"]
    note = slots[0].get("notiz", "")
    assert "\n" not in note and len(note) <= 200
    assert "\ud800" not in note
    st.save(D, st.get(D)["slots"])
    assert list(_disk(path)[D]["notes"]).count("08:00") <= 1


def test_raw_slot_notiz_is_dropped(path):
    st = _foreign(path, {"slots": [_slot(notiz="roh")]})
    assert "notiz" not in st.get(D)["slots"][0]
    st.save(D, st.get(D)["slots"])
    assert "notes" not in _disk(path)[D]


def test_duplicate_starts(path):
    st = _foreign(path, {"slots": [_slot(), _slot(end="13:00")], "notes": {"08:00": "n"}})
    slots = st.get(D)["slots"]
    assert [s.get("notiz") for s in slots] == ["n", "n"]
    st.save(D, slots)
    assert _disk(path)[D]["notes"] == {"08:00": "n"}
