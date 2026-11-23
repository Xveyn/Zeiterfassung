"""Erb-Regel im Merge: ein Stand ohne `notes` erbt die Notizen der anderen Seite.

Der Fall dahinter: eine ältere App-Version speichert einen Tag neu, baut den
Eintrag aus vier Schlüsseln (ohne `notes`), und ihr neuerer Stempel gewinnt.
"""

import pytest

from src import sync
from src.sync import merge

T0 = "2026-05-13T00:00:00Z"   # last_pull_at
T1 = "2026-05-14T10:00:00Z"
T2 = "2026-05-14T11:00:00Z"
T2_BUMPED = "2026-05-14T11:00:01Z"
T3 = "2026-05-14T12:00:00Z"
DAY = "2026-05-14"


def _slot(start="08:00", end="16:00", pause=0, kategorie=""):
    return {"start": start, "end": end, "pause": pause, "kategorie": kategorie}


def _entry(modified_at, device_id, *, slots=None, notes=None, deleted=False):
    entry = {"slots": [_slot()] if slots is None else slots, "modified_at": modified_at,
             "device_id": device_id, "deleted": deleted}
    if notes is not None:
        entry["notes"] = notes
    return entry


def _doc(entries=None):
    return {"schema_version": sync.SCHEMA_VERSION, "entries": entries or {},
            "settings": {}, "conflicts": []}


def old_rewrite(entry, *, modified_at, device_id, **slot_changes):
    """Der Eintrag so, wie eine alte Version ihn schreibt: vier Schlüssel, kein `notes`."""
    slots = [{**s, **slot_changes} for s in entry["slots"]]
    return {"slots": slots, "modified_at": modified_at, "device_id": device_id,
            "deleted": entry.get("deleted", False)}


def _both(a, b, last_pull_at=T0):
    ab = merge(_doc({DAY: a}), _doc({DAY: b}), last_pull_at)
    ba = merge(_doc({DAY: b}), _doc({DAY: a}), last_pull_at)
    return ab, ba


def test_old_device_changes_pause_and_the_note_survives():
    local = _entry(T1, "A", notes={"08:00": "K"})
    remote = old_rewrite(local, modified_at=T2, device_id="C", pause=30)
    merged = merge(_doc({DAY: local}), _doc({DAY: remote}), "2026-05-14T10:30:00Z")
    result = merged["entries"][DAY]
    assert result["slots"][0]["pause"] == 30
    assert result["notes"] == {"08:00": "K"}
    assert result["modified_at"] == T2_BUMPED
    assert result["device_id"] == "C"
    assert merged["conflicts"] == []


def test_old_device_changes_pause_sides_swapped():
    local = _entry(T1, "A", notes={"08:00": "K"})
    remote = old_rewrite(local, modified_at=T2, device_id="C", pause=30)
    pull = "2026-05-14T10:30:00Z"
    ab = merge(_doc({DAY: local}), _doc({DAY: remote}), pull)
    ba = merge(_doc({DAY: remote}), _doc({DAY: local}), pull)
    assert ab["entries"] == ba["entries"]
    assert ba["conflicts"] == []


def test_old_device_changes_start_time_and_the_note_has_no_slot():
    local = _entry(T1, "A", notes={"08:00": "K"})
    remote = old_rewrite(local, modified_at=T2, device_id="C", start="09:00")
    ab, ba = _both(local, remote, "2026-05-14T10:30:00Z")
    result = ab["entries"][DAY]
    assert result["notes"] == {}
    assert result["modified_at"] == T2_BUMPED
    assert ab["entries"] == ba["entries"]


def test_deliberately_emptied_notes_are_not_refilled():
    older = _entry(T1, "A", notes={"08:00": "K"})
    newer = _entry(T3, "B", notes={})
    ab, ba = _both(older, newer, "2026-05-14T10:30:00Z")
    result = ab["entries"][DAY]
    assert result["notes"] == {}
    assert result["modified_at"] == T3
    assert ab["entries"] == ba["entries"]


def test_keyless_newer_state_inherits_the_empty_notes():
    emptied = _entry(T1, "A", notes={})
    newer = old_rewrite(emptied, modified_at=T2, device_id="C", pause=15)
    ab, ba = _both(emptied, newer, "2026-05-14T10:30:00Z")
    result = ab["entries"][DAY]
    assert result["notes"] == {}
    assert result["modified_at"] == T2_BUMPED
    assert ab["entries"] == ba["entries"]


def test_without_notes_on_either_side_the_winner_is_unchanged():
    a = _entry(T1, "A")
    b = _entry(T2, "B", slots=[_slot("09:00")])
    ab, ba = _both(a, b)
    assert ab["entries"][DAY] == b
    assert ba["entries"][DAY] == b
    assert "notes" not in ab["entries"][DAY]
    assert ab["entries"][DAY]["modified_at"] == T2
    assert len(ab["conflicts"]) == len(ba["conflicts"]) == 1


def test_same_stamp_and_device_with_and_without_notes_keeps_the_notes():
    keyed = _entry(T1, "C", notes={"08:00": "K"})
    keyless = _entry(T1, "C")
    ab, ba = _both(keyed, keyless)
    result = ab["entries"][DAY]
    assert result["notes"] == {"08:00": "K"}
    assert result["modified_at"] == "2026-05-14T10:00:01Z"
    assert ab["entries"] == ba["entries"]
    assert ab["conflicts"] == ba["conflicts"] == []


def test_two_new_devices_supplementing_the_same_old_state_agree():
    pull = "2026-05-14T10:30:00Z"
    x_local = _entry(T1, "A", notes={"08:00": "K"})
    y_local = _entry(T1, "A", notes={"08:00": "K"})
    old = old_rewrite(x_local, modified_at=T2, device_id="C", pause=30)
    x = merge(_doc({DAY: x_local}), _doc({DAY: old}), pull)
    y = merge(_doc({DAY: old}), _doc({DAY: y_local}), pull)
    both = merge(x, y, pull)
    assert both["conflicts"] == []
    assert both["entries"][DAY] == x["entries"][DAY] == y["entries"][DAY]


def test_note_only_change_on_both_sides_is_a_conflict():
    a = _entry(T1, "A", notes={"08:00": "Kunde A"})
    b = _entry(T2, "B", notes={"08:00": "Kunde B"})
    ab, ba = _both(a, b)
    assert len(ab["conflicts"]) == 1
    notes = sorted(c["notes"]["08:00"] for c in ab["conflicts"][0]["candidates"])
    assert notes == ["Kunde A", "Kunde B"]
    assert ab["entries"] == ba["entries"]


def test_conflict_candidates_keep_their_original_stamps():
    pull = T0
    keyed = _entry(T1, "A", notes={"08:00": "K"})
    old = old_rewrite(keyed, modified_at=T2, device_id="C", pause=30)
    merged = merge(_doc({DAY: keyed}), _doc({DAY: old}), pull)
    assert len(merged["conflicts"]) == 1
    stamps = sorted((c["modified_at"], c["device_id"])
                    for c in merged["conflicts"][0]["candidates"])
    assert stamps == [(T1, "A"), (T2, "C")]
    assert merged["entries"][DAY]["modified_at"] == T2_BUMPED
    assert merged["entries"][DAY]["notes"] == {"08:00": "K"}


def test_newer_tombstone_beats_a_living_day_with_notes():
    living = _entry(T1, "A", notes={"08:00": "K"})
    tomb = _entry(T2, "B", slots=[], deleted=True)
    ab, ba = _both(living, tomb, "2026-05-14T10:30:00Z")
    assert ab["entries"][DAY] == tomb
    assert ba["entries"][DAY] == tomb


def test_unreadable_stamp_does_not_inherit_and_stays_symmetric():
    keyless = _entry("", "C")
    keyed = _entry(T1, "A", notes={"08:00": "K"})
    ab, ba = _both(keyless, keyed)
    assert ab["entries"] == ba["entries"]
    assert ab["entries"][DAY] == keyed


@pytest.mark.parametrize("other", [
    _entry(T2, "B"),
    _entry(T2, "B", notes={"08:00": "K"}),
    _entry(T2, "B", slots=[], deleted=True),
])
def test_broken_notes_value_does_not_raise(other):
    broken = _entry(T1, "A", notes="kaputt")
    ab, ba = _both(broken, other)
    assert ab["entries"] == ba["entries"]


@pytest.mark.parametrize("start", [["08:00"], {"x": 1}])
def test_unhashable_start_does_not_raise_and_stays_symmetric(start):
    foreign = _entry(T2, "B", slots=[_slot(start=start)])
    keyed = _entry(T1, "A", notes={"08:00": "K"})
    ab, ba = _both(foreign, keyed)
    assert ab["entries"] == ba["entries"]


def test_stamp_at_the_end_of_the_range_does_not_inherit_and_stays_symmetric():
    keyless = _entry("9999-12-31T23:59:59Z", "C")
    keyed = _entry(T1, "A", notes={"08:00": "K"})
    ab, ba = _both(keyless, keyed)
    assert ab["entries"] == ba["entries"]
    assert ab["entries"][DAY] == keyless


def test_stamp_before_year_1000_is_not_bumped_past_real_stamps():
    old = "0500-01-01T00:00:00Z"
    keyless = _entry(old, "C")
    keyed = _entry(old, "C", notes={"08:00": "K"})
    ab, ba = _both(keyless, keyed)
    assert ab["entries"] == ba["entries"]
    assert ab["entries"][DAY]["modified_at"] == old
