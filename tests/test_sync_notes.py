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


# --- Gelöste Konflikte ---------------------------------------------------------

T2_PLUS = "2026-05-14T11:00:01Z"


def _resolved(resolution, *, candidates=(), resolved_at=T2, resolved_by="A", id_="c1"):
    return {"id": id_, "kind": "entry", "key": DAY, "candidates": list(candidates),
            "detected_at": T1, "resolved": True, "resolution": resolution,
            "resolved_at": resolved_at, "resolved_by": resolved_by}


def _stores(tmp_path):
    from src.conflicts_store import ConflictsStore
    from src.settings import Settings
    from src.storage import Storage
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    settings = Settings(str(tmp_path / "s.json"))
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    return storage, settings, conflicts


def _open_conflict(*candidates):
    return {"id": "c1", "kind": "entry", "key": DAY, "candidates": list(candidates),
            "detected_at": T1, "resolved": False, "resolution": None,
            "resolved_at": None, "resolved_by": None}


def _plain(slots):
    return [{k: s[k] for k in ("start", "end", "pause", "kategorie")} for s in slots]


def test_resolving_takes_the_notes_of_the_chosen_candidate(tmp_path):
    storage, settings, conflicts = _stores(tmp_path)
    cand_a = _entry(T1, "A", slots=[_slot(pause=30)], notes={"08:00": "KA"})
    cand_b = _entry(T2, "B", notes={"08:00": "KB"})
    storage.save(DAY, [{**_slot(), "notiz": "KB"}])
    conflicts.save_all([_open_conflict(cand_a, cand_b)])

    sync.resolve_conflict("c1", {"slots": _plain(cand_a["slots"])}, conflicts, storage,
                          settings, device_id="A")

    assert storage.get(DAY)["slots"][0]["notiz"] == "KA"
    assert storage.get_all_raw()[DAY]["notes"] == {"08:00": "KA"}
    assert conflicts.get_all()[0]["resolution"]["notes"] == {"08:00": "KA"}


def test_resolving_a_keyless_candidate_inherits_from_the_other_candidate(tmp_path):
    storage, settings, conflicts = _stores(tmp_path)
    cand_a = _entry(T1, "A", slots=[_slot(pause=30)], notes={"08:00": "KA"})
    cand_b = _entry(T2, "B")
    storage.save(DAY, [{**_slot(), "notiz": "KB"}])
    conflicts.save_all([_open_conflict(cand_a, cand_b)])

    sync.resolve_conflict("c1", {"slots": _plain(cand_b["slots"])}, conflicts, storage,
                          settings, device_id="A")

    assert storage.get(DAY)["slots"][0]["notiz"] == "KA"
    assert conflicts.get_all()[0]["resolution"]["notes"] == {"08:00": "KA"}


def test_resolving_without_any_notes_writes_no_notes(tmp_path):
    storage, settings, conflicts = _stores(tmp_path)
    cand_a = _entry(T1, "A", slots=[_slot(pause=30)])
    cand_b = _entry(T2, "B")
    storage.save(DAY, [_slot()])
    conflicts.save_all([_open_conflict(cand_a, cand_b)])

    sync.resolve_conflict("c1", {"slots": _plain(cand_a["slots"])}, conflicts, storage,
                          settings, device_id="A")

    assert "notes" not in conflicts.get_all()[0]["resolution"]
    assert "notes" not in storage.get_all_raw()[DAY]


def test_resolving_with_delete_keeps_working(tmp_path):
    storage, settings, conflicts = _stores(tmp_path)
    cand = _entry(T1, "A", notes={"08:00": "KA"})
    storage.save(DAY, [{**_slot(), "notiz": "KA"}])
    conflicts.save_all([_open_conflict(cand)])

    sync.resolve_conflict("c1", {"deleted": True}, conflicts, storage, settings,
                          device_id="A")

    assert storage.get(DAY) is None
    assert storage.get_all_raw()[DAY]["notes"] == {}
    assert conflicts.get_all()[0]["resolution"]["notes"] == {}


def test_old_device_stripping_the_resolved_day_heals_after_one_merge():
    resolution = {"slots": [_slot()], "deleted": False, "notes": {"08:00": "K"}}
    conflict = _resolved(resolution, resolved_at=T2, resolved_by="A")
    local_entry = _entry(T2, "A", notes={"08:00": "K"})
    local = {**_doc({DAY: local_entry}), "conflicts": [conflict]}
    remote = {**_doc({DAY: old_rewrite(local_entry, modified_at=T2, device_id="A")}),
              "conflicts": [conflict]}

    merged = merge(local, remote, T0)
    result = merged["entries"][DAY]
    assert result["notes"] == {"08:00": "K"}
    assert result["modified_at"] == T2_PLUS
    assert result["modified_at"] > conflict["resolved_at"]
    assert merge(remote, local, T0)["entries"] == merged["entries"]
    assert merge(merged, remote, T0)["entries"] == merged["entries"]


def test_stripped_day_on_both_sides_heals_from_the_resolution():
    resolution = {"slots": [_slot()], "deleted": False, "notes": {"08:00": "K"}}
    conflict = _resolved(resolution, resolved_at=T2, resolved_by="A")
    stripped = _entry(T2, "A")
    doc = {**_doc({DAY: stripped}), "conflicts": [conflict]}

    merged = merge(doc, doc, T0)
    assert merged["entries"][DAY]["notes"] == {"08:00": "K"}
    assert merged["entries"][DAY]["modified_at"] == T2_PLUS
    assert merge(merged, doc, T0)["entries"] == merged["entries"]
    assert merge(doc, merged, T0)["entries"] == merged["entries"]


def test_old_resolution_takes_the_notes_of_the_matching_candidate():
    cand_a = _entry(T1, "A", notes={"08:00": "KA"})
    cand_b = _entry(T1, "B", slots=[_slot(pause=30)], notes={"08:00": "KB"})
    conflict = _resolved({"slots": [_slot(pause=30)]}, candidates=[cand_a, cand_b],
                         resolved_at=T3, resolved_by="C")
    current = _entry(T2, "A", notes={"08:00": "KA"})
    merged = merge({**_doc({DAY: current}), "conflicts": [conflict]}, _doc(), T0)
    result = merged["entries"][DAY]
    assert result["notes"] == {"08:00": "KB"}
    assert result["modified_at"] == T3
    assert result["slots"][0]["pause"] == 30


def test_two_resolutions_with_notes_apply_order_independently():
    x = _resolved({"slots": [_slot()], "notes": {"08:00": "X"}}, id_="c1",
                  resolved_at=T2, resolved_by="A")
    y = _resolved({"slots": [_slot()]}, id_="c2", resolved_at=T2, resolved_by="B",
                  candidates=[_entry(T1, "B", notes={"08:00": "Y"})])
    base = {DAY: _entry(T1, "A", notes={"08:00": "Z"})}
    one = merge({**_doc(base), "conflicts": [x, y]}, _doc(), T0)
    two = merge({**_doc(base), "conflicts": [y, x]}, _doc(), T0)
    assert one["entries"] == two["entries"]
    assert one["entries"][DAY]["device_id"] == "B"
    assert one["entries"][DAY]["notes"] == {"08:00": "Y"}


def test_resolution_without_notes_and_no_notes_anywhere_is_unchanged():
    conflict = _resolved({"slots": [_slot(pause=30)]}, candidates=[_entry(T1, "A")],
                         resolved_at=T3, resolved_by="C")
    merged = merge({**_doc({DAY: _entry(T2, "A")}), "conflicts": [conflict]}, _doc(), T0)
    assert merged["entries"][DAY] == {"slots": [_slot(pause=30)], "modified_at": T3,
                                      "device_id": "C", "deleted": False}


@pytest.mark.parametrize("conflict_patch", [
    {"resolution": "kaputt"},
    {"resolution": ["x"]},
    {"candidates": "kaputt"},
    {"candidates": [None, 3, {"slots": "x", "notes": ["y"]}]},
    {"resolution": {"slots": [_slot()], "notes": "kaputt"}},
    {"resolution": {"slots": [_slot()], "notes": {"08:00": ["x"], 3: "y"}}},
    {"resolution": {"slots": [_slot(start=["08:00"])], "notes": {"08:00": "K"}}},
    {"resolution": {"slots": "kaputt"}},
    {"resolved_at": 5},
    {"resolved_by": ["x"]},
    {"key": ["2026-05-14"]},
    {"key": None},
])
def test_foreign_resolution_data_does_not_raise_and_stays_symmetric(conflict_patch):
    conflict = {**_resolved({"slots": [_slot()]}, resolved_at=T2), **conflict_patch}
    a = {**_doc({DAY: _entry(T1, "A", notes={"08:00": "K"})}), "conflicts": [conflict]}
    b = _doc({DAY: _entry("9999-12-31T23:59:59Z", "B")})
    ab, ba = merge(a, b, T0), merge(b, a, T0)
    assert ab["entries"] == ba["entries"]


def test_bump_onto_the_resolution_stamp_is_decided_by_the_device_both_ways():
    """Die Anhebung kann einen Stand genau auf `resolved_at` heben; dann
    entscheidet wie bei jedem sekundengleichen Stand das Gerät, symmetrisch."""
    keyed = _entry(T1, "A", notes={"08:00": "K"})
    stale = old_rewrite(keyed, modified_at="2026-05-14T10:59:59Z", device_id="Z", pause=15)
    conflict = _resolved({"slots": [_slot()], "notes": {"08:00": "R"}},
                         resolved_at=T2, resolved_by="A")
    a = {**_doc({DAY: keyed}), "conflicts": [conflict]}
    b = _doc({DAY: stale})
    ab, ba = merge(a, b, T0), merge(b, a, T0)
    assert ab["entries"] == ba["entries"]
    assert ab["entries"][DAY]["modified_at"] == T2
    assert ab["entries"][DAY]["device_id"] == "Z"
    assert merge(ab, b, T0)["entries"] == ab["entries"]


def test_resolution_does_not_refill_a_day_recreated_later_without_notes():
    """Ein gelöster Konflikt bleibt bis zur Kompaktierung in der Liste; ein Tag, der
    danach gelöscht und ohne Notiz neu angelegt wurde, bekommt die Notiz der
    Auflösung nicht zurück und keinen angehobenen Stempel."""
    conflict = _resolved({"slots": [_slot()], "deleted": False, "notes": {"08:00": "K"}},
                         resolved_at=T2, resolved_by="A")
    recreated = _entry(T3, "A")
    a = {**_doc({DAY: recreated}), "conflicts": [conflict]}
    b = {**_doc({DAY: recreated}), "conflicts": [conflict]}
    for merged in (merge(a, b, T0), merge(b, a, T0), merge(a, _doc(), T0), merge(_doc(), a, T0)):
        assert merged["entries"][DAY] == recreated


def test_resolution_does_not_refill_a_keyless_day_of_another_device():
    conflict = _resolved({"slots": [_slot()], "deleted": False, "notes": {"08:00": "K"}},
                         resolved_at=T2, resolved_by="A")
    other = _entry(T2, "B")
    merged = merge({**_doc({DAY: other}), "conflicts": [conflict]}, _doc(), T0)
    assert merged["entries"][DAY] == other


# --- Gelöschte Tage behalten den Schlüssel `notes` --------------------------------


def test_resolution_applied_as_deleted_leaves_a_keyed_tombstone_both_ways():
    base = _entry(T1, "A", notes={"08:00": "K"})
    conflict = _resolved({"slots": [], "deleted": True}, candidates=[base, _entry(T1, "B")],
                         resolved_at=T3, resolved_by="C")
    a = {**_doc({DAY: base}), "conflicts": [conflict]}
    b = {**_doc({DAY: _entry(T2, "B", notes={"08:00": "K"})}), "conflicts": [conflict]}
    for merged in (merge(a, b, T0), merge(b, a, T0)):
        assert merged["entries"][DAY] == {"slots": [], "modified_at": T3, "device_id": "C",
                                          "deleted": True, "notes": {}}


def test_resolution_applied_as_deleted_takes_the_key_from_a_candidate():
    conflict = _resolved({"slots": [], "deleted": True},
                         candidates=[_entry(T1, "A"), _entry(T1, "B", notes={"08:00": "K"})],
                         resolved_at=T3, resolved_by="C")
    merged = merge({**_doc({DAY: _entry(T2, "A")}), "conflicts": [conflict]}, _doc(), T0)
    assert merged["entries"][DAY]["notes"] == {}
    other = {**conflict, "id": "c2", "candidates": [], "resolved_by": "D"}
    one = merge({**_doc({DAY: _entry(T2, "A")}), "conflicts": [conflict, other]}, _doc(), T0)
    two = merge({**_doc({DAY: _entry(T2, "A")}), "conflicts": [other, conflict]}, _doc(), T0)
    assert one["entries"] == two["entries"]
    assert one["entries"][DAY]["device_id"] == "D" and "notes" not in one["entries"][DAY]


def test_resolution_applied_as_deleted_without_any_key_is_a_four_key_tombstone():
    conflict = _resolved({"slots": [], "deleted": True}, candidates=[_entry(T1, "A")],
                         resolved_at=T3, resolved_by="C")
    merged = merge({**_doc({DAY: _entry(T2, "A")}), "conflicts": [conflict]}, _doc(), T0)
    assert merged["entries"][DAY] == {"slots": [], "modified_at": T3, "device_id": "C",
                                      "deleted": True}


def test_keyed_tombstone_does_not_pass_on_notes_and_loses_to_a_newer_day():
    tombstone = _entry(T2, "A", slots=[], deleted=True, notes={})
    stale = _entry(T1, "B", notes={"08:00": "K"})
    ab, ba = _both(tombstone, stale)
    assert ab["entries"] == ba["entries"]
    assert ab["entries"][DAY] == tombstone
    newer_old = old_rewrite(_entry(T3, "C"), modified_at=T3, device_id="C")
    ab, ba = _both(tombstone, newer_old)
    assert ab["entries"] == ba["entries"]
    assert ab["entries"][DAY] == {**newer_old, "notes": {}, "modified_at": "2026-05-14T12:00:01Z"}


def test_delete_and_recreate_without_a_note_does_not_bring_it_back_from_a_stale_device(
        tmp_path, monkeypatch):
    """Zwei neue Geräte: A löscht einen Tag mit Notiz und legt ihn ohne Notiz neu an;
    B hält noch den Stand mit Notiz. Weder B noch A bekommen die Notiz zurück."""
    import src.storage as storage_mod
    from src.storage import Storage
    stamps = iter(["2026-05-14T10:00:00Z", "2026-05-14T11:00:00Z", "2026-05-14T12:00:00Z"])
    monkeypatch.setattr(storage_mod, "utc_now_iso", lambda: next(stamps))
    a = Storage(str(tmp_path / "a.json"), device_id="A")
    b = Storage(str(tmp_path / "b.json"), device_id="B")
    a.save(DAY, [{**_slot(), "notiz": "K"}])
    b.apply_merge(a.get_all_raw())
    a.delete(DAY)
    a.save(DAY, [{**_slot(), "notiz": ""}])
    pulled = "2026-05-14T10:30:00Z"

    on_b = merge(_doc(b.get_all_raw()), _doc(a.get_all_raw()), pulled)
    b.apply_merge(on_b["entries"])
    on_a = merge(_doc(a.get_all_raw()), _doc(b.get_all_raw()), pulled)
    a.apply_merge(on_a["entries"])

    for store in (a, b):
        assert "notiz" not in store.get(DAY)["slots"][0]
        assert store.get_all_raw()[DAY]["notes"] == {}
        assert store.get_all_raw()[DAY]["modified_at"] == "2026-05-14T12:00:00Z"
    assert on_b["conflicts"] == [] and on_a["conflicts"] == []


def test_day_recreated_without_the_key_over_a_keyed_tombstone_takes_the_marker():
    """Ein Handy oder ein altes Gerät legt einen gelöschten Tag ohne `notes` neu an; der
    Tombstone trägt den Schlüssel. Der neue Tag bekommt `{}`, und ein Gerät, das noch den
    Stand vor dem Löschen hält, füllt die alte Notiz nicht nach."""
    tombstone = _entry(T2, "A", slots=[], deleted=True, notes={})
    recreated = old_rewrite(_entry(T3, "P"), modified_at=T3, device_id="P")
    pulled = "2026-05-14T11:30:00Z"
    ab, ba = _both(tombstone, recreated, pulled)
    assert ab["entries"] == ba["entries"]
    result = ab["entries"][DAY]
    assert result == {**recreated, "notes": {}, "modified_at": "2026-05-14T12:00:01Z"}
    assert ab["conflicts"] == ba["conflicts"] == []

    stale = _entry(T1, "B", notes={"08:00": "K"})
    ab, ba = _both(stale, result, pulled)
    assert ab["entries"] == ba["entries"]
    assert ab["entries"][DAY] == result


def test_day_recreated_without_the_key_over_a_four_key_tombstone_is_unchanged():
    tombstone = _entry(T2, "A", slots=[], deleted=True)
    recreated = old_rewrite(_entry(T3, "P"), modified_at=T3, device_id="P")
    ab, ba = _both(tombstone, recreated, "2026-05-14T11:30:00Z")
    assert ab["entries"][DAY] == recreated
    assert ba["entries"][DAY] == recreated
    assert ab["entries"][DAY]["modified_at"] == T3


def test_compaction_and_orphan_sweep_drop_keyed_tombstones(tmp_path):
    storage, settings, conflicts = _stores(tmp_path)
    storage.save(DAY, [{**_slot(), "notiz": "K"}])
    storage.delete(DAY)
    assert storage.get_all_raw()[DAY]["notes"] == {}
    sync.compact_local(storage, settings, conflicts, "9999-01-01T00:00:00Z")
    assert storage.get_all_raw() == {}

    storage.save(DAY, [{**_slot(), "notiz": "K"}])
    storage.delete(DAY)
    settings.set("gc_watermark", "")
    assert sync.drop_orphan_tombstones(storage, settings) == 1
    assert storage.get_all_raw() == {}


def test_old_write_in_the_resolution_second_wins_after_the_bump():
    """Bekannte Grenze: ohne Notizen entschiede die Geräte-ID ("0" < "A", die Auflösung
    gewänne); der ergänzte alte Stand liegt nach der Anhebung eine Sekunde später."""
    keyed = _entry(T1, "A", notes={"08:00": "K"})
    old = old_rewrite(keyed, modified_at=T2, device_id="0", pause=15)
    conflict = _resolved({"slots": [_slot()], "notes": {"08:00": "R"}},
                         resolved_at=T2, resolved_by="A")
    a = {**_doc({DAY: keyed}), "conflicts": [conflict]}
    ab, ba = merge(a, _doc({DAY: old}), T0), merge(_doc({DAY: old}), a, T0)
    assert ab["entries"] == ba["entries"]
    assert ab["entries"][DAY]["modified_at"] == T2_BUMPED
    assert ab["entries"][DAY]["device_id"] == "0"

    plain = _resolved({"slots": [_slot()]}, resolved_at=T2, resolved_by="A")
    without = merge({**_doc({DAY: _entry(T1, "A")}), "conflicts": [plain]},
                    _doc({DAY: old}), T0)
    assert without["entries"][DAY]["device_id"] == "A"


def test_resolving_with_a_slot_level_note_stores_four_field_slots(tmp_path):
    storage, settings, conflicts = _stores(tmp_path)
    cand_a = _entry(T1, "A", slots=[_slot(pause=30)], notes={"08:00": "KA"})
    cand_b = _entry(T2, "B")
    storage.save(DAY, [_slot()])
    conflicts.save_all([_open_conflict(cand_a, cand_b)])

    chosen = {"slots": [{**_slot(pause=30), "notiz": " Neu "}], "deleted": False}
    sync.resolve_conflict("c1", chosen, conflicts, storage, settings, device_id="A")

    resolution = conflicts.get_all()[0]["resolution"]
    assert resolution["slots"] == [_slot(pause=30)]
    assert all(set(s) == {"start", "end", "pause", "kategorie"} for s in resolution["slots"])
    assert resolution["notes"] == {"08:00": "Neu"}
    assert storage.get(DAY)["slots"][0]["notiz"] == "Neu"
    assert storage.get_all_raw()[DAY]["notes"] == {"08:00": "Neu"}
    assert chosen["slots"][0]["notiz"] == " Neu "


def test_an_explicit_empty_slot_note_counts_as_given(tmp_path):
    storage, settings, conflicts = _stores(tmp_path)
    cand_a = _entry(T1, "A", slots=[_slot(pause=30)], notes={"08:00": "KA"})
    storage.save(DAY, [{**_slot(pause=30), "notiz": "KA"}])
    conflicts.save_all([_open_conflict(cand_a, _entry(T2, "B"))])

    sync.resolve_conflict("c1", {"slots": [{**_slot(pause=30), "notiz": ""}]}, conflicts,
                          storage, settings, device_id="A")

    resolution = conflicts.get_all()[0]["resolution"]
    assert resolution["slots"] == [_slot(pause=30)]
    assert resolution["notes"] == {}
    assert "notiz" not in storage.get(DAY)["slots"][0]
    assert storage.get_all_raw()[DAY]["notes"] == {}


def test_slots_without_a_note_key_still_inherit_next_to_given_ones(tmp_path):
    storage, settings, conflicts = _stores(tmp_path)
    late = _slot(start="13:00", end="17:00")
    cand = _entry(T1, "A", slots=[_slot(end="12:00"), late],
                  notes={"08:00": "K8", "13:00": "K13"})
    storage.save(DAY, [_slot(end="12:00"), late])
    conflicts.save_all([_open_conflict(cand, _entry(T2, "B"))])

    chosen = {"slots": [{**_slot(end="12:00"), "notiz": "Neu"}, dict(late)]}
    sync.resolve_conflict("c1", chosen, conflicts, storage, settings, device_id="A")

    assert conflicts.get_all()[0]["resolution"]["notes"] == {"08:00": "Neu", "13:00": "K13"}


# --- Gespeicherter Tag und Auflösung stimmen im Schlüssel überein -----------------

def _pin_clock(monkeypatch, stamp):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "utc_now_iso", lambda: stamp)
    monkeypatch.setattr(sync, "utc_now_iso", lambda: stamp)


def _local_doc(storage, conflicts):
    return {**_doc(storage.get_all_raw()), "conflicts": conflicts.get_all()}


def test_resolving_as_deleted_takes_the_key_of_a_candidate_into_store_and_resolution(
        tmp_path, monkeypatch):
    """Der Tag am auflösenden Gerät hat keinen Schlüssel (ein Löschen ohne Notizen), der
    andere Kandidat trägt eine Notiz. Tombstone und Auflösung tragen beide `{}`."""
    storage, settings, conflicts = _stores(tmp_path)
    keyed = _entry(T1, "B", notes={"08:00": "K"})
    tomb = _entry(T2, "A", slots=[], deleted=True)
    storage.apply_merge({DAY: tomb})
    conflicts.save_all([_open_conflict(tomb, keyed)])
    _pin_clock(monkeypatch, T3)

    sync.resolve_conflict("c1", {"slots": [], "deleted": True}, conflicts, storage, settings,
                          device_id="A")

    stored = storage.get_all_raw()[DAY]
    assert stored == {"slots": [], "modified_at": T3, "device_id": "A", "deleted": True,
                      "notes": {}}
    assert conflicts.get_all()[0]["resolution"]["notes"] == {}
    mine = _local_doc(storage, conflicts)
    peer = {**_doc({DAY: keyed}), "conflicts": [_open_conflict(tomb, keyed)]}
    for merged in (merge(mine, peer, T0), merge(peer, mine, T0)):
        assert merged["entries"][DAY] == stored

    later = "2026-05-14T13:00:00Z"
    _pin_clock(monkeypatch, later)
    storage.save(DAY, [_slot()])
    recreated = storage.get_all_raw()[DAY]
    assert recreated["notes"] == {}
    mine = _local_doc(storage, conflicts)
    stale = _doc({DAY: keyed})
    for merged in (merge(mine, stale, T2), merge(stale, mine, T2)):
        assert merged["entries"][DAY] == recreated


@pytest.mark.parametrize("chosen", [
    {"slots": [{**_slot(pause=30), "notiz": ""}], "deleted": False},
    {"slots": [_slot(pause=30)], "deleted": False, "notes": {}},
    {"slots": [_slot(pause=30)], "deleted": False, "notes": {"09:00": "ohne Slot"}},
])
def test_resolving_with_empty_notes_on_a_never_noted_day_writes_no_key_and_bumps_nothing(
        tmp_path, monkeypatch, chosen):
    storage, settings, conflicts = _stores(tmp_path)
    cand_a = _entry(T1, "A", slots=[_slot(pause=30)])
    cand_b = _entry(T2, "B")
    storage.apply_merge({DAY: cand_b})
    conflicts.save_all([_open_conflict(cand_a, cand_b)])
    _pin_clock(monkeypatch, T3)

    sync.resolve_conflict("c1", chosen, conflicts, storage, settings, device_id="A")

    stored = storage.get_all_raw()[DAY]
    assert stored == {"slots": [_slot(pause=30)], "modified_at": T3, "device_id": "A",
                      "deleted": False}
    resolution = conflicts.get_all()[0]["resolution"]
    assert "notes" not in resolution and resolution["slots"] == [_slot(pause=30)]
    mine = _local_doc(storage, conflicts)
    peer = {**_doc({DAY: cand_b}), "conflicts": [_open_conflict(cand_a, cand_b)]}
    for merged in (merge(mine, peer, T0), merge(peer, mine, T0), merge(mine, mine, T0)):
        assert merged["entries"][DAY] == stored


def test_resolving_with_a_keyed_empty_candidate_on_a_keyless_day_needs_no_extra_round(
        tmp_path, monkeypatch):
    storage, settings, conflicts = _stores(tmp_path)
    cand_a = _entry(T1, "A", slots=[_slot(pause=30)], notes={})
    cand_b = _entry(T2, "B")
    storage.apply_merge({DAY: cand_b})
    conflicts.save_all([_open_conflict(cand_a, cand_b)])
    _pin_clock(monkeypatch, T3)

    sync.resolve_conflict("c1", {"slots": [_slot(pause=30)]}, conflicts, storage, settings,
                          device_id="A")

    stored = storage.get_all_raw()[DAY]
    assert stored["notes"] == {} and stored["modified_at"] == T3
    assert conflicts.get_all()[0]["resolution"]["notes"] == {}
    mine = _local_doc(storage, conflicts)
    peer = {**_doc({DAY: cand_b}), "conflicts": [_open_conflict(cand_a, cand_b)]}
    for merged in (merge(mine, peer, T0), merge(peer, mine, T0), merge(mine, mine, T0)):
        assert merged["entries"][DAY] == stored


def test_two_old_resolutions_of_a_noted_day_with_the_same_stamp_are_idempotent():
    """Zwei Auflösungen desselben Tages mit gleichem `resolved_at` und `resolved_by`, keine
    trägt `notes` (ein altes Gerät hat beide gelöst). Welche gilt, entscheidet ihr eigener
    Inhalt; ein zweiter Merge wechselt nicht zur anderen."""
    entry = _entry(T1, "A", notes={"08:00": "K8"})
    first = _resolved({"slots": [_slot(start="09:00")], "deleted": False},
                      resolved_by="O", id_="c0")
    second = _resolved({"slots": [_slot(pause=30)], "deleted": False},
                       resolved_by="O", id_="c1")
    for conflicts in ([first, second], [second, first]):
        b = {**_doc({DAY: entry}), "conflicts": conflicts}
        for ab in (merge(_doc(), b, T1), merge(b, _doc(), T1)):
            again = merge(ab, ab, T1)
            assert again["entries"] == ab["entries"]
            assert merge(again, again, T1)["entries"] == ab["entries"]


def test_resolving_with_the_older_card_keeps_its_notes(tmp_path):
    """Gleiche Slots, verschiedene Notizen: die gewählte (ältere) Karte bestimmt die Notiz,
    nicht der jüngere Kandidat."""
    from src import conflict_view
    storage, settings, conflicts = _stores(tmp_path)
    older = _entry(T1, "A", notes={"08:00": "Alt"})
    younger = _entry(T2, "B", notes={"08:00": "Neu"})
    storage.save(DAY, [{**_slot(), "notiz": "Neu"}])
    conflicts.save_all([_open_conflict(older, younger)])

    sync.resolve_conflict("c1", conflict_view.entry_choice(older), conflicts, storage,
                          settings, device_id="A")

    assert storage.get(DAY)["slots"][0]["notiz"] == "Alt"
    assert conflicts.get_all()[0]["resolution"]["notes"] == {"08:00": "Alt"}
