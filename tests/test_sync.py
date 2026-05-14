from src.sync import _merge_one


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
