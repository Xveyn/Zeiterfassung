from src.sync import _merge_one, merge


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
