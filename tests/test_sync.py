import json as _json

import pytest

from src.conflicts_store import ConflictsStore
from src.settings import Settings
from src.storage import Storage
from src.sync import _merge_one, apply_merged_doc, build_local_doc, merge, resolve_conflict


def _e(start, end, pause, modified_at, device_id="d", deleted=False):
    return {
        "start": start, "end": end, "pause": pause,
        "modified_at": modified_at, "device_id": device_id, "deleted": deleted,
    }


def test_merge_one_local_only_keeps_local():
    local = _e("08:00", "16:00", 30, "2026-05-14T10:00:00Z")
    merged, conflict = _merge_one(local, None, "2026-05-13T00:00:00Z")
    assert merged is local
    assert conflict is None


def test_merge_one_remote_only_keeps_remote():
    remote = _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z")
    merged, conflict = _merge_one(None, remote, "2026-05-13T00:00:00Z")
    assert merged is remote
    assert conflict is None


def test_merge_one_equal_values_no_conflict():
    e1 = _e("08:00", "16:00", 30, "2026-05-14T10:00:00Z")
    e2 = _e("08:00", "16:00", 30, "2026-05-14T11:00:00Z")
    merged, conflict = _merge_one(e1, e2, "2026-05-13T00:00:00Z")
    assert conflict is None
    # bei gleichen Values darf irgendeine Seite gewinnen, aber kein Conflict
    assert merged["start"] == "08:00"


def test_merge_one_only_local_changed_no_conflict():
    """remote.modified_at < last_pull_at: nur local hat sich geändert, kein Conflict."""
    local = _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z")  # changed after last_pull
    remote = _e("08:00", "16:00", 30, "2026-05-10T00:00:00Z")  # before last_pull
    merged, conflict = _merge_one(local, remote, "2026-05-13T00:00:00Z")
    assert conflict is None
    assert merged is local


def test_merge_one_only_remote_changed_no_conflict():
    local = _e("08:00", "16:00", 30, "2026-05-10T00:00:00Z")
    remote = _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z")
    merged, conflict = _merge_one(local, remote, "2026-05-13T00:00:00Z")
    assert conflict is None
    assert merged is remote


def test_merge_one_both_changed_creates_conflict():
    local = _e("08:00", "16:00", 30, "2026-05-14T10:00:00Z", device_id="A")
    remote = _e("09:00", "17:00", 30, "2026-05-14T11:00:00Z", device_id="B")
    merged, conflict = _merge_one(local, remote, "2026-05-13T00:00:00Z")
    assert conflict is not None
    assert conflict["kind"] == "entry"
    # provisorischer Wert = jüngerer (LWW)
    assert merged is remote
    # Beide Kandidaten im Conflict
    candidate_devices = sorted(c["device_id"] for c in conflict["candidates"])
    assert candidate_devices == ["A", "B"]


# --- Task 2.2: Tombstone tests ---

def test_merge_one_tombstone_wins_when_only_remote_changed():
    local = _e("08:00", "16:00", 30, "2026-05-01T10:00:00Z")  # before last_pull
    remote = _e(None, None, None, "2026-05-14T10:00:00Z", deleted=True)
    merged, conflict = _merge_one(local, remote, "2026-05-10T00:00:00Z")
    assert merged is remote
    assert merged["deleted"] is True
    assert conflict is None


def test_merge_one_tombstone_vs_edit_creates_conflict_when_both_changed():
    local = _e("08:00", "16:00", 30, "2026-05-14T09:00:00Z")
    remote = _e(None, None, None, "2026-05-14T10:00:00Z", deleted=True)
    merged, conflict = _merge_one(local, remote, "2026-05-13T00:00:00Z")
    assert conflict is not None
    # LWW: jüngerer gewinnt provisorisch
    assert merged is remote


# --- Task 2.3: merge() for Entries ---

def _doc(entries=None, settings=None, conflicts=None):
    return {
        "schema_version": 1,
        "entries": entries or {},
        "settings": settings or {},
        "conflicts": conflicts or [],
    }


def test_merge_empty_docs_returns_empty():
    merged = merge(_doc(), _doc(), "2026-05-13T00:00:00Z")
    assert merged["entries"] == {}
    assert merged["settings"] == {}
    assert merged["conflicts"] == []


def test_merge_local_only_entry_preserved():
    local = _doc(entries={"2026-05-14": _e("08:00", "16:00", 30, "2026-05-14T10:00:00Z")})
    merged = merge(local, _doc(), "2026-05-13T00:00:00Z")
    assert "2026-05-14" in merged["entries"]


def test_merge_remote_only_entry_added():
    remote = _doc(entries={"2026-05-14": _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z")})
    merged = merge(_doc(), remote, "2026-05-13T00:00:00Z")
    assert merged["entries"]["2026-05-14"]["start"] == "09:00"


def test_merge_conflict_creates_conflict_object():
    local = _doc(entries={"D": _e("08:00", "16:00", 30, "2026-05-14T09:00:00Z", "A")})
    remote = _doc(entries={"D": _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z", "B")})
    merged = merge(local, remote, "2026-05-13T00:00:00Z")
    assert len(merged["conflicts"]) == 1
    c = merged["conflicts"][0]
    assert c["kind"] == "entry"
    assert c["key"] == "D"
    assert c["resolved"] is False


def test_merge_no_conflict_when_only_one_side_changed():
    local = _doc(entries={"D": _e("08:00", "16:00", 30, "2026-05-01T09:00:00Z")})
    remote = _doc(entries={"D": _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z")})
    merged = merge(local, remote, "2026-05-10T00:00:00Z")
    assert merged["conflicts"] == []
    assert merged["entries"]["D"]["start"] == "09:00"


# --- Task 2.4: merge() for Settings (Whitelist) ---

def _s(value, modified_at, device_id="d"):
    return {"value": value, "modified_at": modified_at, "device_id": device_id}


def test_merge_setting_local_only():
    local = _doc(settings={"recipient": _s("a@b.de", "2026-05-14T10:00:00Z")})
    merged = merge(local, _doc(), "2026-05-13T00:00:00Z")
    assert merged["settings"]["recipient"]["value"] == "a@b.de"


def test_merge_setting_conflict_creates_setting_conflict():
    local = _doc(settings={
        "recipient": _s("a@b.de", "2026-05-14T09:00:00Z", "A"),
    })
    remote = _doc(settings={
        "recipient": _s("x@y.de", "2026-05-14T10:00:00Z", "B"),
    })
    merged = merge(local, remote, "2026-05-13T00:00:00Z")
    assert len(merged["conflicts"]) == 1
    assert merged["conflicts"][0]["kind"] == "setting"
    assert merged["conflicts"][0]["key"] == "recipient"


def test_merge_setting_ignores_non_whitelisted():
    """Settings außerhalb der SYNCED_SETTING_KEYS werden im Merge ignoriert."""
    local = _doc(settings={"autostart": _s(True, "2026-05-14T10:00:00Z")})
    remote = _doc(settings={"autostart": _s(False, "2026-05-14T11:00:00Z")})
    merged = merge(local, remote, "2026-05-13T00:00:00Z")
    assert "autostart" not in merged["settings"]


# --- Task 2.5: Conflict-list merge + idempotency ---

def _conflict(id_, key="D", kind="entry", resolved=False,
              resolution=None, resolved_at=None, resolved_by=None,
              candidates=None):
    return {
        "id": id_, "kind": kind, "key": key,
        "candidates": candidates or [],
        "detected_at": "2026-05-14T10:00:00Z",
        "resolved": resolved, "resolution": resolution,
        "resolved_at": resolved_at, "resolved_by": resolved_by,
    }


def test_merge_conflicts_union_by_id():
    local = _doc(conflicts=[_conflict("c-1"), _conflict("c-2")])
    remote = _doc(conflicts=[_conflict("c-2"), _conflict("c-3")])
    merged = merge(local, remote, "2026-05-13T00:00:00Z")
    ids = sorted(c["id"] for c in merged["conflicts"])
    assert ids == ["c-1", "c-2", "c-3"]


def test_merge_conflicts_resolved_wins_over_unresolved():
    """Wenn dasselbe Konflikt-ID auf einer Seite resolved ist, gilt resolved."""
    resolved = _conflict("c-1", resolved=True,
                         resolution={"start": "08:00", "end": "16:00", "pause": 30},
                         resolved_at="2026-05-14T11:00:00Z",
                         resolved_by="A")
    unresolved = _conflict("c-1", resolved=False)
    merged = merge(_doc(conflicts=[resolved]), _doc(conflicts=[unresolved]),
                    "2026-05-13T00:00:00Z")
    assert len(merged["conflicts"]) == 1
    assert merged["conflicts"][0]["resolved"] is True


def test_merge_conflicts_lww_on_resolved_at_when_both_resolved():
    c_a = _conflict("c-1", resolved=True,
                    resolution={"start": "08:00"}, resolved_at="2026-05-14T11:00:00Z",
                    resolved_by="A")
    c_b = _conflict("c-1", resolved=True,
                    resolution={"start": "09:00"}, resolved_at="2026-05-14T12:00:00Z",
                    resolved_by="B")
    merged = merge(_doc(conflicts=[c_a]), _doc(conflicts=[c_b]), "2026-05-13T00:00:00Z")
    assert len(merged["conflicts"]) == 1
    assert merged["conflicts"][0]["resolved_by"] == "B"


def test_merge_idempotent_does_not_duplicate_unresolved_conflict():
    """Bei wiederholtem merge mit denselben Inputs entsteht kein zweiter Eintrag."""
    local = _doc(
        entries={"D": _e("08:00", "16:00", 30, "2026-05-14T09:00:00Z", "A")},
        conflicts=[_conflict("c-1", key="D",
                              candidates=[_e("08:00", "16:00", 30, "2026-05-14T09:00:00Z", "A"),
                                          _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z", "B")])],
    )
    remote = _doc(entries={"D": _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z", "B")})
    merged = merge(local, remote, "2026-05-13T00:00:00Z")
    # Conflict für D existiert schon → kein neuer
    entry_conflicts_for_d = [c for c in merged["conflicts"]
                              if c["kind"] == "entry" and c["key"] == "D"]
    assert len(entry_conflicts_for_d) == 1
    assert entry_conflicts_for_d[0]["id"] == "c-1"


# --- Task 2.6: Resolution-Propagation ---

def test_merge_applies_resolved_conflict_to_entry():
    """Resolved Konflikt aktualisiert merged.entries auf die Resolution."""
    resolved = _conflict("c-1", key="D",
                         resolved=True,
                         resolution={"start": "10:00", "end": "18:00", "pause": 30},
                         resolved_at="2026-05-14T12:00:00Z",
                         resolved_by="A")
    local = _doc(
        entries={"D": _e("08:00", "16:00", 30, "2026-05-14T11:00:00Z")},
        conflicts=[resolved],
    )
    remote = _doc(entries={"D": _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z")})
    merged = merge(local, remote, "2026-05-13T00:00:00Z")
    e = merged["entries"]["D"]
    assert e["start"] == "10:00"
    assert e["end"] == "18:00"
    assert e["modified_at"] == "2026-05-14T12:00:00Z"
    assert e["device_id"] == "A"
    assert e["deleted"] is False


def test_merge_applies_resolved_setting_conflict():
    resolved = _conflict("c-1", kind="setting", key="recipient",
                         resolved=True, resolution={"value": "final@x.de"},
                         resolved_at="2026-05-14T12:00:00Z", resolved_by="A")
    local = _doc(
        settings={"recipient": _s("a@b.de", "2026-05-14T09:00:00Z")},
        conflicts=[resolved],
    )
    merged = merge(local, _doc(), "2026-05-13T00:00:00Z")
    assert merged["settings"]["recipient"]["value"] == "final@x.de"
    assert merged["settings"]["recipient"]["device_id"] == "A"


# --- Task 2.7: build_local_doc + apply_merged_doc ---

def test_build_local_doc_includes_storage_settings_conflicts(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    storage.save("2026-05-14", "08:00", "16:00", 30)
    settings = Settings(str(tmp_path / "s.json"))
    settings.device_id_for_sync = "A"
    settings.set_synced("recipient", "a@b.de")
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    conflicts.save_all([{"id": "c-1", "kind": "entry", "key": "D", "resolved": False}])

    doc = build_local_doc(storage, settings, conflicts)
    assert "2026-05-14" in doc["entries"]
    assert doc["settings"]["recipient"]["value"] == "a@b.de"
    assert doc["conflicts"][0]["id"] == "c-1"
    assert doc["schema_version"] == 2


def test_round_trip_no_loss(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    storage.save("2026-05-14", "08:00", "16:00", 30)
    settings = Settings(str(tmp_path / "s.json"))
    settings.device_id_for_sync = "A"
    settings.set_synced("name", "Max")
    conflicts = ConflictsStore(str(tmp_path / "c.json"))

    local = build_local_doc(storage, settings, conflicts)
    merged = merge(local, _doc(), "2025-01-01T00:00:00Z")
    apply_merged_doc(merged, storage, settings, conflicts)

    assert storage.get("2026-05-14") == {"start": "08:00", "end": "16:00", "pause": 30}
    assert settings.get("name") == "Max"


# --- Task 2.8: resolve_conflict ---

def test_resolve_entry_conflict_updates_storage_and_marks_resolved(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    settings = Settings(str(tmp_path / "s.json"))
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    conflicts.save_all([{
        "id": "c-1", "kind": "entry", "key": "2026-05-14",
        "candidates": [
            {"start": "08:00", "end": "16:00", "pause": 30,
             "modified_at": "2026-05-14T09:00:00Z", "device_id": "A", "deleted": False},
            {"start": "09:00", "end": "17:00", "pause": 30,
             "modified_at": "2026-05-14T10:00:00Z", "device_id": "B", "deleted": False},
        ],
        "detected_at": "2026-05-14T11:00:00Z",
        "resolved": False, "resolution": None,
        "resolved_at": None, "resolved_by": None,
    }])

    chosen = {"start": "09:00", "end": "17:00", "pause": 30}
    resolve_conflict("c-1", chosen, conflicts, storage, settings, device_id="A")

    # storage hat den Wert
    assert storage.get("2026-05-14") == {"start": "09:00", "end": "17:00", "pause": 30}
    # conflict ist resolved
    c = conflicts.get_all()[0]
    assert c["resolved"] is True
    assert c["resolution"] == chosen
    assert c["resolved_by"] == "A"
    assert c["resolved_at"].endswith("Z")


def test_resolve_setting_conflict_updates_settings(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    settings = Settings(str(tmp_path / "s.json"))
    settings.device_id_for_sync = "A"
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    conflicts.save_all([{
        "id": "c-2", "kind": "setting", "key": "recipient",
        "candidates": [
            {"value": "a@b.de", "modified_at": "...", "device_id": "A"},
            {"value": "x@y.de", "modified_at": "...", "device_id": "B"},
        ],
        "detected_at": "...", "resolved": False, "resolution": None,
        "resolved_at": None, "resolved_by": None,
    }])
    resolve_conflict("c-2", {"value": "x@y.de"}, conflicts, storage, settings, device_id="A")
    assert settings.get("recipient") == "x@y.de"
    assert conflicts.get_all()[0]["resolved"] is True


def test_main_pull_quarantines_corrupt_remote():
    """Wenn die Drive-Datei kein gültiges JSON ist, wird sie via Drive umbenannt
    und der Pull behandelt sie als 'leer'.
    Wir testen das auf der Sync-Engine-Ebene: parse_remote_or_quarantine sollte
    bei kaputtem Inhalt ein leeres Doc zurückgeben und einen Callback aufrufen."""
    from src.main import _parse_remote_or_quarantine

    quarantined = []
    def fake_quarantine(file_id):
        quarantined.append(file_id)

    doc = _parse_remote_or_quarantine(b"not json{{{", "file-1", fake_quarantine)
    assert doc == {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
    assert quarantined == ["file-1"]


def test_main_pull_returns_doc_when_valid_json():
    from src.main import _parse_remote_or_quarantine
    raw = _json.dumps({"schema_version": 1, "entries": {"D": {}}, "settings": {}, "conflicts": []})
    doc = _parse_remote_or_quarantine(raw.encode(), "file-1", lambda fid: None)
    assert "D" in doc["entries"]


def test_resolve_nonexistent_conflict_raises(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    settings = Settings(str(tmp_path / "s.json"))
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    with pytest.raises(KeyError):
        resolve_conflict("missing", {}, conflicts, storage, settings, device_id="A")


# --- Tombstone-Kompaktierung: Watermark-Propagation ---

def _meta_doc(entries=None, conflicts=None, watermark=""):
    d = _doc(entries=entries, conflicts=conflicts)
    d["schema_version"] = 2
    d["meta"] = {"gc_watermark": watermark}
    return d


def test_merge_watermark_propagates_max():
    local = _meta_doc(watermark="2026-05-01T00:00:00Z")
    remote = _meta_doc(watermark="2026-05-10T00:00:00Z")
    merged = merge(local, remote, "2026-04-01T00:00:00Z")
    assert merged["meta"]["gc_watermark"] == "2026-05-10T00:00:00Z"


def test_merge_watermark_monotonic_local_wins_when_remote_missing_meta():
    """v1-Remote ohne meta darf das lokale Watermark nicht zurücksetzen."""
    local = _meta_doc(watermark="2026-05-10T00:00:00Z")
    remote = _doc()  # schema_version 1, kein meta
    merged = merge(local, remote, "2026-04-01T00:00:00Z")
    assert merged["meta"]["gc_watermark"] == "2026-05-10T00:00:00Z"


def test_merge_no_meta_either_side_yields_empty_watermark():
    merged = merge(_doc(), _doc(), "2026-04-01T00:00:00Z")
    assert merged["meta"]["gc_watermark"] == ""


def test_build_local_doc_includes_watermark_from_settings(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    settings = Settings(str(tmp_path / "s.json"))
    settings.set("gc_watermark", "2026-05-10T00:00:00Z")
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    doc = build_local_doc(storage, settings, conflicts)
    assert doc["meta"]["gc_watermark"] == "2026-05-10T00:00:00Z"


def test_apply_merged_doc_persists_watermark(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    settings = Settings(str(tmp_path / "s.json"))
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    merged = _meta_doc(watermark="2026-05-11T00:00:00Z")
    apply_merged_doc(merged, storage, settings, conflicts)
    assert settings.get("gc_watermark") == "2026-05-11T00:00:00Z"


# --- Regel 1: settled Tombstones droppen ---

def test_merge_drops_settled_entry_tombstone():
    wm = "2026-05-10T00:00:00Z"
    local = _meta_doc(
        entries={"D": _e(None, None, None, "2026-05-05T00:00:00Z", deleted=True)},
        watermark=wm,
    )
    merged = merge(local, _meta_doc(watermark=wm), "2026-04-01T00:00:00Z")
    assert "D" not in merged["entries"]


def test_merge_keeps_tombstone_at_or_after_watermark():
    wm = "2026-05-10T00:00:00Z"
    # genau auf der Grenze: strikt < → bleibt
    local = _meta_doc(
        entries={"D": _e(None, None, None, wm, deleted=True)},
        watermark=wm,
    )
    merged = merge(local, _meta_doc(watermark=wm), "2026-04-01T00:00:00Z")
    assert "D" in merged["entries"]


def test_merge_keeps_live_entry_older_than_watermark():
    """Regel 1 entfernt nur deleted-Einträge, keine lebenden.
    last_pull_at == wm → Gerät ist nicht excluded (kein Regel-2-Eingriff)."""
    wm = "2026-05-10T00:00:00Z"
    local = _meta_doc(
        entries={"D": _e("08:00", "16:00", 30, "2026-05-05T00:00:00Z")},
        watermark=wm,
    )
    merged = merge(local, _meta_doc(watermark=wm), wm)
    assert "D" in merged["entries"]


def test_merge_compaction_propagates_and_sticks():
    """Gerät B hält lokalen Tombstone, pullt kompaktierten Remote (ohne D,
    Watermark gesetzt) → B verwirft den Tombstone, lädt ihn nicht erneut hoch."""
    wm = "2026-05-10T00:00:00Z"
    local = _meta_doc(  # B hat den alten Tombstone noch
        entries={"D": _e(None, None, None, "2026-05-05T00:00:00Z", deleted=True)},
        watermark="",
    )
    remote = _meta_doc(entries={}, watermark=wm)  # bereits kompaktiert
    merged = merge(local, remote, "2026-05-06T00:00:00Z")
    assert "D" not in merged["entries"]
    assert merged["meta"]["gc_watermark"] == wm


def test_merge_recovers_after_failed_compaction_push():
    """Partial-Failure: lokal wurde kompaktiert (Watermark=now gesetzt), aber der
    Push schlug fehl → Remote trägt den Tombstone noch. Beim nächsten Sync gewinnt
    das höhere lokale Watermark monoton und Regel 1 entfernt den Remote-Tombstone."""
    now = "2026-06-09T12:00:00Z"
    local = _meta_doc(entries={}, watermark=now)  # lokal schon kompaktiert
    remote = _meta_doc(  # Remote hat den alten Tombstone noch, altes/leeres Watermark
        entries={"D": _e(None, None, None, "2026-05-05T00:00:00Z", deleted=True)},
        watermark="",
    )
    merged = merge(local, remote, "2026-05-06T00:00:00Z")
    assert "D" not in merged["entries"]
    assert merged["meta"]["gc_watermark"] == now


def test_merge_drops_settled_resolved_conflict():
    wm = "2026-05-10T00:00:00Z"
    c = _conflict("c-1", resolved=True, resolution={"start": "08:00"},
                  resolved_at="2026-05-05T00:00:00Z", resolved_by="A")
    local = _meta_doc(conflicts=[c], watermark=wm)
    merged = merge(local, _meta_doc(watermark=wm), "2026-04-01T00:00:00Z")
    assert merged["conflicts"] == []


def test_merge_keeps_resolved_conflict_without_resolved_at():
    """Defensiv: resolved=True aber resolved_at None/'' → nicht droppen (kein Crash)."""
    wm = "2026-05-10T00:00:00Z"
    c = _conflict("c-1", resolved=True, resolution={"start": "08:00"},
                  resolved_at=None, resolved_by="A")
    local = _meta_doc(conflicts=[c], watermark=wm)
    merged = merge(local, _meta_doc(watermark=wm), "2026-04-01T00:00:00Z")
    assert len(merged["conflicts"]) == 1


def test_merge_keeps_unresolved_conflict_regardless_of_watermark():
    wm = "2026-05-10T00:00:00Z"
    c = _conflict("c-1", resolved=False)
    local = _meta_doc(conflicts=[c], watermark=wm)
    merged = merge(local, _meta_doc(watermark=wm), "2026-04-01T00:00:00Z")
    assert len(merged["conflicts"]) == 1


def test_merge_no_drop_when_watermark_empty():
    """Backwards-compat: ohne Watermark verhält sich merge wie bisher."""
    local = _doc(entries={"D": _e(None, None, None, "2026-05-05T00:00:00Z", deleted=True)})
    merged = merge(local, _doc(), "2026-04-01T00:00:00Z")
    assert "D" in merged["entries"]


# --- Regel 2: Self-Heal-Suppression ---

def test_merge_suppresses_stale_live_entry_for_excluded_device():
    """Zurückkehrendes Gerät (last_pull_at < remote.watermark) verwirft einen
    alten, anderswo gelöschten-und-kompaktierten Tag statt ihn aufstehen zu lassen."""
    wm = "2026-05-10T00:00:00Z"
    local = _meta_doc(
        entries={"D": _e("08:00", "16:00", 30, "2026-05-05T00:00:00Z")},  # alt, lebend
        watermark="",
    )
    remote = _meta_doc(entries={}, watermark=wm)  # D wurde anderswo kompaktiert
    # last_pull_at < remote.watermark → excluded
    merged = merge(local, remote, "2026-05-06T00:00:00Z")
    assert "D" not in merged["entries"]


def test_merge_first_sync_device_keeps_history():
    """Erstsync (last_pull_at == '') ist NICHT excluded → Historie bleibt/lädt hoch."""
    wm = "2026-05-10T00:00:00Z"
    local = _meta_doc(
        entries={"D": _e("08:00", "16:00", 30, "2026-05-05T00:00:00Z")},
        watermark="",
    )
    remote = _meta_doc(entries={}, watermark=wm)
    merged = merge(local, remote, "")  # Erstsync
    assert merged["entries"]["D"]["start"] == "08:00"


def test_merge_keeps_fresh_offline_edit_for_excluded_device():
    """Excluded, aber Eintrag NEUER als Watermark → echter Offline-Edit, bleibt."""
    wm = "2026-05-10T00:00:00Z"
    local = _meta_doc(
        entries={"D": _e("08:00", "16:00", 30, "2026-05-15T00:00:00Z")},  # > watermark
        watermark="",
    )
    remote = _meta_doc(entries={}, watermark=wm)
    merged = merge(local, remote, "2026-05-06T00:00:00Z")  # excluded
    assert merged["entries"]["D"]["start"] == "08:00"


def test_merge_no_suppression_when_remote_present():
    """Suppression greift nur bei remote-fehlendem Key."""
    wm = "2026-05-10T00:00:00Z"
    local = _meta_doc(
        entries={"D": _e("08:00", "16:00", 30, "2026-05-05T00:00:00Z")},
        watermark="",
    )
    remote = _meta_doc(
        entries={"D": _e("09:00", "17:00", 30, "2026-05-04T00:00:00Z")},
        watermark=wm,
    )
    merged = merge(local, remote, "2026-05-06T00:00:00Z")
    assert "D" in merged["entries"]


# --- Kompaktierungs-Helfer ---

from src.sync import compact_local, _remote_is_pre_v2


def test_compact_local_strips_stores_and_sets_watermark(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    storage.save("LIVE", "08:00", "16:00", 30)
    storage.save("DEL", "08:00", "16:00", 30)
    storage.delete("DEL")  # Tombstone
    settings = Settings(str(tmp_path / "s.json"))
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    conflicts.save_all([
        {"id": "c-1", "kind": "entry", "key": "X", "candidates": [],
         "detected_at": "...", "resolved": True, "resolution": {"start": "08:00"},
         "resolved_at": "2026-05-05T00:00:00Z", "resolved_by": "A"},
        {"id": "c-2", "kind": "entry", "key": "Y", "candidates": [],
         "detected_at": "...", "resolved": False, "resolution": None,
         "resolved_at": None, "resolved_by": None},
    ])
    # Watermark unzweideutig in der Zukunft jeder realen delete()-Stempelung
    # (storage.delete stempelt modified_at = wall-clock UTC); sonst flippt
    # der Strip ab dem Watermark-Zeitpunkt (_is_settled_entry nutzt strikt <).
    now = "2099-01-01T00:00:00Z"
    compact_local(storage, settings, conflicts, now)

    assert settings.get("gc_watermark") == now
    raw = storage.get_all_raw()
    assert "DEL" not in raw            # Tombstone gestrippt
    assert "LIVE" in raw               # lebend bleibt
    remaining = [c["id"] for c in conflicts.get_all()]
    assert remaining == ["c-2"]        # nur unresolved bleibt


def test_remote_is_pre_v2():
    assert _remote_is_pre_v2({"schema_version": 1, "entries": {}}) is True
    assert _remote_is_pre_v2({"schema_version": 2, "entries": {}}) is True  # kein meta
    assert _remote_is_pre_v2({"schema_version": 2, "meta": {"gc_watermark": ""}}) is False
    assert _remote_is_pre_v2({"schema_version": 2, "meta": {}}) is True     # meta ohne key


# --- Forward-Compat-Guard: neueres Remote-Schema nicht crashen/überschreiben ---

from src.sync import _remote_is_newer, NEWER_REMOTE_VERSION_MSG, SCHEMA_VERSION


def test_remote_is_newer():
    assert _remote_is_newer({"schema_version": SCHEMA_VERSION + 1, "entries": {}}) is True
    assert _remote_is_newer({"schema_version": 99, "entries": {}}) is True
    assert _remote_is_newer({"schema_version": SCHEMA_VERSION, "entries": {}}) is False
    assert _remote_is_newer({"schema_version": 1, "entries": {}}) is False
    assert _remote_is_newer({"entries": {}}) is False  # fehlend -> 1


def _v3_remote_bytes():
    """Ein Remote-Doc im v3-Slot-Format, wie es eine neuere App schreibt:
    Einträge haben `slots` statt der flachen start/end/pause-Keys."""
    return _json.dumps({
        "schema_version": 3,
        "entries": {
            "2026-06-04": {
                "slots": [{"start": "08:00", "end": "16:00", "pause": 30,
                           "kategorie": "Arbeit"}],
                "modified_at": "2026-06-04T10:00:00Z",
                "device_id": "B", "deleted": False,
            }
        },
        "settings": {}, "conflicts": [],
        "meta": {"gc_watermark": ""},
    }, ensure_ascii=False).encode("utf-8")


def test_apply_merge_crashes_on_v3_entry_without_guard(tmp_path):
    """Beleg für den Grund des Guards: ohne ihn würde das v3-Doc in
    apply_merge hart abbrechen (fehlende start/end/pause)."""
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    v3_entries = {
        "2026-06-04": {"slots": [{"start": "08:00", "end": "16:00"}],
                       "modified_at": "2026-06-04T10:00:00Z",
                       "device_id": "B", "deleted": False}
    }
    with pytest.raises(ValueError):
        storage.apply_merge(v3_entries)


def test_run_pull_aborts_on_newer_remote(tmp_path, monkeypatch):
    """Pull gegen ein v3-Remote: Callback meldet ok=False mit der Update-
    Meldung, NICHTS wird lokal angewendet (kein Crash), last_pull_at bleibt
    unverändert."""
    from src import drive
    import src.main as main

    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    settings = Settings(str(tmp_path / "s.json"))
    settings.device_id_for_sync = "A"
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    before_pull_at = settings.get("last_pull_at")

    monkeypatch.setattr(drive, "get_drive_service", lambda *a, **k: object())
    monkeypatch.setattr(drive, "find_sync_file", lambda service: "file-1")
    monkeypatch.setattr(drive, "download", lambda service, fid: (_v3_remote_bytes(), "etag-x"))

    received = {}
    def ui_callback(ok, error, tb=""):
        received["ok"] = ok
        received["error"] = error

    main._run_pull_in_background(storage, settings, conflicts, str(tmp_path), ui_callback)

    assert received["ok"] is False
    assert str(received["error"]) == NEWER_REMOTE_VERSION_MSG
    assert storage.get_all_raw() == {}              # nichts angewendet
    assert settings.get("last_pull_at") == before_pull_at  # unverändert
