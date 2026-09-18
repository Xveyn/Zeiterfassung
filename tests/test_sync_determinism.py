"""Merge-Determinismus und Testlücken der Konfliktlogik (#142).

Der Merge muss unabhängig davon sein, welches Gerät „lokal" und welches
„remote" ist — sonst behält bei einem sekundengleichen Gleichstand jedes Gerät
seinen eigenen Wert, und die Stände laufen auseinander. Tiebreaker überall:
Zeitstempel, dann Gerät, dann der Wert selbst.
"""

import json
import random
import re

import pytest

from src import devices, sync, sync_journal
from src.conflicts_store import ConflictsStore
from src.settings import SYNCED_SETTING_KEYS, Settings
from src.storage import Storage
from src.sync import _equivalent_unresolved_exists, _merge_conflict_pair, merge, resolve_conflict

T0 = "2026-05-13T00:00:00Z"   # last_pull_at
T1 = "2026-05-14T10:00:00Z"
T2 = "2026-05-14T11:00:00Z"


def _e(start, modified_at, device_id, deleted=False):
    slots = [] if deleted else [{"start": start, "end": "16:00", "pause": 30, "kategorie": ""}]
    return {"slots": slots, "modified_at": modified_at, "device_id": device_id,
            "deleted": deleted}


def _s(value, modified_at, device_id):
    return {"value": value, "modified_at": modified_at, "device_id": device_id}


def _doc(entries=None, settings=None, conflicts=None):
    return {"schema_version": sync.SCHEMA_VERSION, "entries": entries or {},
            "settings": settings or {}, "conflicts": conflicts or []}


def _conflict(id_, key="2026-05-14", kind="entry", resolved=False, resolution=None,
              resolved_at=None, resolved_by=None):
    return {"id": id_, "kind": kind, "key": key, "candidates": [],
            "detected_at": T1, "resolved": resolved, "resolution": resolution,
            "resolved_at": resolved_at, "resolved_by": resolved_by}


def _canon(doc):
    """Inhaltlicher Vergleich: zufällige Konflikt-IDs und `detected_at`
    fallen weg, Listenreihenfolgen zählen nicht."""
    def conflict_view(c):
        return json.dumps({
            "kind": c["kind"], "key": c["key"], "resolved": c.get("resolved"),
            "resolution": c.get("resolution"), "resolved_at": c.get("resolved_at"),
            "resolved_by": c.get("resolved_by"),
            "candidates": sorted(json.dumps(x, sort_keys=True) for x in c["candidates"]),
        }, sort_keys=True)
    return {
        "entries": json.dumps(doc["entries"], sort_keys=True),
        "settings": json.dumps(doc["settings"], sort_keys=True),
        "devices": json.dumps(doc.get("devices", {}), sort_keys=True),
        "conflicts": sorted(conflict_view(c) for c in doc["conflicts"]),
    }


# --- Tiebreaker ------------------------------------------------------------


def test_same_second_edits_resolve_to_the_same_winner_on_both_devices():
    a = _doc(entries={"2026-05-14": _e("08:00", T1, "A")})
    b = _doc(entries={"2026-05-14": _e("09:00", T1, "B")})
    ab, ba = merge(a, b, T0), merge(b, a, T0)
    assert ab["entries"] == ba["entries"]
    assert ab["entries"]["2026-05-14"]["device_id"] == "B"   # höheres Gerät gewinnt
    assert len(ab["conflicts"]) == len(ba["conflicts"]) == 1  # Konflikt bleibt erkannt


def test_equal_values_pick_the_same_metadata_both_ways():
    a = _doc(entries={"2026-05-14": _e("08:00", T1, "A")})
    b = _doc(entries={"2026-05-14": _e("08:00", T1, "B")})
    assert merge(a, b, T0)["entries"] == merge(b, a, T0)["entries"]


def test_setting_tie_is_symmetric():
    a = _doc(settings={"recipient": _s("a@x.de", T1, "A")})
    b = _doc(settings={"recipient": _s("b@x.de", T1, "B")})
    assert merge(a, b, T0)["settings"] == merge(b, a, T0)["settings"]


def test_unresolved_loses_to_resolved_in_both_orders():
    open_ = _conflict("c")
    done = _conflict("c", resolved=True, resolution={"slots": []}, resolved_at=T1,
                     resolved_by="A")
    assert _merge_conflict_pair(open_, done) is done
    assert _merge_conflict_pair(done, open_) is done


def test_resolution_tie_is_order_independent():
    x = _conflict("c", resolved=True, resolution={"slots": [], "deleted": True},
                  resolved_at=T1, resolved_by="A")
    y = _conflict("c", resolved=True, resolution={"slots": []},
                  resolved_at=T1, resolved_by="B")
    assert _merge_conflict_pair(x, y) is _merge_conflict_pair(y, x)
    assert _merge_conflict_pair(x, y)["resolved_by"] == "B"


def test_two_resolutions_for_one_key_apply_order_independently():
    x = _conflict("c1", resolved=True, resolution={"slots": [], "deleted": True},
                  resolved_at=T2, resolved_by="A")
    y = _conflict("c2", resolved=True, resolution={"slots": []},
                  resolved_at=T2, resolved_by="B")
    base = {"2026-05-14": _e("08:00", T1, "A")}
    one = merge(_doc(entries=base, conflicts=[x, y]), _doc(), T0)
    two = merge(_doc(entries=base, conflicts=[y, x]), _doc(), T0)
    assert one["entries"] == two["entries"]
    assert one["entries"]["2026-05-14"]["device_id"] == "B"


def test_device_registry_tie_is_symmetric():
    a = {"dev": {"name": "Laptop", "updated_at": T1}}
    b = {"dev": {"name": "Desktop", "updated_at": T1}}
    assert devices.merge_registries(a, b) == devices.merge_registries(b, a)


# --- Resolutions gegen den aktuellen Stand ---------------------------------


@pytest.mark.parametrize("kind,key,current,resolution", [
    ("entry", "2026-05-14", _e("08:00", T2, "A"), {"slots": []}),
    ("setting", "recipient", _s("a@x.de", T2, "A"), {"value": "alt@x.de"}),
])
def test_older_resolution_does_not_overwrite_newer_value(kind, key, current, resolution):
    c = _conflict("c", kind=kind, key=key, resolved=True, resolution=resolution,
                  resolved_at=T1, resolved_by="B")
    section = "entries" if kind == "entry" else "settings"
    merged = merge(_doc(**{section: {key: current}}, conflicts=[c]), _doc(), T0)
    assert merged[section][key] == current


@pytest.mark.parametrize("kind,key,current,resolution,field,expected", [
    ("entry", "2026-05-14", _e("08:00", T1, "A"), {"slots": [], "deleted": True},
     "deleted", True),
    ("setting", "recipient", _s("a@x.de", T1, "A"), {"value": "neu@x.de"},
     "value", "neu@x.de"),
])
def test_newer_resolution_overwrites(kind, key, current, resolution, field, expected):
    c = _conflict("c", kind=kind, key=key, resolved=True, resolution=resolution,
                  resolved_at=T2, resolved_by="B")
    section = "entries" if kind == "entry" else "settings"
    merged = merge(_doc(**{section: {key: current}}, conflicts=[c]), _doc(), T0)
    assert merged[section][key][field] == expected
    assert merged[section][key]["modified_at"] == T2


# --- Dedupe ----------------------------------------------------------------


def _with_candidates(c, *cands):
    c = dict(c)
    c["candidates"] = [{"modified_at": m, "device_id": d} for m, d in cands]
    return c


def test_dedupe_ignores_a_new_conflict_that_is_already_resolved():
    new = _with_candidates(_conflict("n", resolved=True), (T1, "A"))
    assert _equivalent_unresolved_exists([_with_candidates(_conflict("e"), (T1, "A"))],
                                         new) is False


def test_dedupe_skips_resolved_and_other_kind_or_key():
    new = _with_candidates(_conflict("n"), (T1, "A"), (T2, "B"))
    existing = [
        _with_candidates(_conflict("r", resolved=True), (T1, "A"), (T2, "B")),
        _with_candidates(_conflict("k", kind="setting"), (T1, "A"), (T2, "B")),
        _with_candidates(_conflict("x", key="2026-05-15"), (T1, "A"), (T2, "B")),
    ]
    assert _equivalent_unresolved_exists(existing, new) is False
    existing.append(_with_candidates(_conflict("same"), (T2, "B"), (T1, "A")))
    assert _equivalent_unresolved_exists(existing, new) is True


# --- Auflösen „Tag löschen" --------------------------------------------------


def test_resolving_an_entry_conflict_with_delete_removes_the_day(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    storage.save("2026-05-14", [{"start": "08:00", "end": "16:00", "pause": 30,
                                 "kategorie": ""}])
    settings = Settings(str(tmp_path / "s.json"))
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    conflicts.save_all([_conflict("c")])

    resolve_conflict("c", {"deleted": True}, conflicts, storage, settings, device_id="A")

    assert storage.get("2026-05-14") is None
    assert conflicts.get_all()[0]["resolved"] is True


# --- Journal: Aufräumen bei Schreibfehler -----------------------------------


def test_journal_write_error_removes_the_temp_file_and_reraises(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("Platte voll")

    monkeypatch.setattr(sync_journal.json, "dump", boom)
    with pytest.raises(OSError):
        sync_journal._atomic_write_json(str(tmp_path / "j.journal"), {"a": 1})
    assert list(tmp_path.iterdir()) == []


# --- Zeitstempel-Format ------------------------------------------------------


def test_lww_timestamps_have_one_fixed_format():
    """LWW vergleicht Zeitstempel als Strings — das ist nur korrekt, solange
    alle Schreiber exakt dasselbe Format liefern (UTC, `Z`, Sekunden)."""
    from src.time_utils import utc_now_iso
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", utc_now_iso())


def test_every_hand_written_timestamp_format_matches_utc_now_iso():
    """Wer in src/ einen Zeitstempel per strftime baut, nutzt dasselbe Format
    wie utc_now_iso — sonst verglichen sich `…Z` und `+00:00` falsch."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "src"
    formats = set()
    for path in root.rglob("*.py"):
        formats |= set(re.findall(r'strftime\("(%Y-%m-%dT[^"]*)"\)',
                                  path.read_text(encoding="utf-8")))
    assert formats == {"%Y-%m-%dT%H:%M:%SZ"}


# --- Permutation: kommutativ und idempotent ----------------------------------


_KEYS = ["2026-05-14", "2026-05-15", "2026-05-16"]
_TIMES = [T0, T1, T2]
_DEVICES = ["A", "B"]


def _random_doc(rng):
    entries = {}
    for key in _KEYS:
        if rng.random() < 0.7:
            entries[key] = _e(rng.choice(["08:00", "09:00"]), rng.choice(_TIMES),
                              rng.choice(_DEVICES), deleted=rng.random() < 0.2)
    settings = {}
    if rng.random() < 0.7:
        settings["recipient"] = _s(rng.choice(["a@x.de", "b@x.de"]),
                                   rng.choice(_TIMES), rng.choice(_DEVICES))
    conflicts = []
    for i in range(rng.randint(0, 2)):
        resolved = rng.random() < 0.6
        kind = rng.choice(["entry", "setting"])
        conflicts.append(_conflict(
            f"c{i}", kind=kind,
            key=rng.choice(_KEYS) if kind == "entry" else "recipient",
            resolved=resolved,
            resolution=(({"slots": [], "deleted": rng.random() < 0.5} if kind == "entry"
                         else {"value": rng.choice(["a@x.de", "c@x.de"])})
                        if resolved else None),
            resolved_at=rng.choice(_TIMES) if resolved else None,
            resolved_by=rng.choice(_DEVICES) if resolved else None))
    doc = _doc(entries, settings, conflicts)
    doc["devices"] = {"A": {"name": rng.choice(["Laptop", "Büro"]),
                            "updated_at": rng.choice(_TIMES)}}
    return doc


def test_merge_is_commutative_and_idempotent_over_random_docs():
    assert "recipient" in SYNCED_SETTING_KEYS
    rng = random.Random(142)
    for _ in range(500):
        a, b = _random_doc(rng), _random_doc(rng)
        ab, ba = merge(a, b, T0), merge(b, a, T0)
        assert _canon(ab) == _canon(ba)
        assert _canon(merge(ab, ab, T0)) == _canon(ab)
