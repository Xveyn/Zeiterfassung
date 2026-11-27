"""Krankheitstage im Sync-Doc: Bereich `sick`, additiv ohne Schema-Bump.

Fehlt der Bereich (ein Gerät bis 1.29 lässt ihn beim Hochladen weg), heißt das
nie „gelöscht“. Je Tag gewinnt der neuere Datensatz, Konflikte gibt es nicht.
"""

import logging

import pytest

from src import sick_days, sync
from src.conflicts_store import ConflictsStore
from src.settings import Settings
from src.sick_days import SickStore
from src.storage import Storage
from src.sync import (
    apply_merged_doc, build_local_doc, compact_local, drop_orphan_tombstones, merge,
    validate_remote_doc,
)

T0 = "2026-03-01T00:00:00Z"   # last_pull_at
T1 = "2026-03-02T10:00:00Z"
T2 = "2026-03-02T11:00:00Z"
WM = "2026-03-10T00:00:00Z"   # gc_watermark nach einer Kompaktierung
OLD = "2026-03-05T00:00:00Z"  # vor dem Watermark
FRESH = "2026-03-12T00:00:00Z"  # nach dem Watermark

_MISSING = object()


def _rec(minutes, modified_at, device_id, deleted=False):
    return {"minutes": 0 if deleted else minutes, "modified_at": modified_at,
            "device_id": device_id, "deleted": deleted}


def _doc(sick=_MISSING, watermark=""):
    doc = {"schema_version": sync.SCHEMA_VERSION, "entries": {}, "settings": {},
           "conflicts": [], "meta": {"gc_watermark": watermark}}
    if sick is not _MISSING:
        doc["sick"] = sick
    return doc


@pytest.fixture
def stamp(monkeypatch):
    """Feste Stempel für die Stores (Krankheit und Ist-Zeit)."""
    now = {"value": T1}
    monkeypatch.setattr(sick_days, "utc_now_iso", lambda: now["value"])
    return now


def _stores(tmp_path, device="A"):
    storage = Storage(str(tmp_path / f"z-{device}.json"), device_id=device)
    settings = Settings(str(tmp_path / f"s-{device}.json"))
    settings.device_id_for_sync = device
    conflicts = ConflictsStore(str(tmp_path / f"c-{device}.json"))
    sick = SickStore(str(tmp_path / f"sick-{device}.json"), device_id=device)
    return storage, settings, conflicts, sick


# --- build_local_doc ---------------------------------------------------------


def test_doc_without_sick_days_has_no_section(tmp_path, stamp):
    storage, settings, conflicts, sick = _stores(tmp_path)
    with_store = build_local_doc(storage, settings, conflicts, sick_store=sick)
    without = build_local_doc(storage, settings, conflicts)
    assert with_store.keys() == without.keys()
    assert "sick" not in with_store


def test_doc_with_only_a_tombstone_carries_the_section(tmp_path, stamp):
    storage, settings, conflicts, sick = _stores(tmp_path)
    sick.save_range({"2026-03-02": 480})
    sick.delete_days(["2026-03-02"])
    doc = build_local_doc(storage, settings, conflicts, sick_store=sick)
    assert doc["sick"] == {"2026-03-02": _rec(0, T1, "A", deleted=True)}


# --- merge -------------------------------------------------------------------


def test_merge_without_sick_on_either_side_has_no_section():
    assert "sick" not in merge(_doc(), _doc(), T0)


def test_merge_takes_newer_record_per_day_symmetric():
    a = _doc({"2026-03-02": _rec(480, T1, "A"), "2026-03-03": _rec(240, T2, "A")})
    b = _doc({"2026-03-02": _rec(300, T2, "B"), "2026-03-03": _rec(120, T1, "B"),
              "2026-03-04": _rec(60, T1, "B")})
    ab, ba = merge(a, b, T0), merge(b, a, T0)
    assert ab["sick"] == ba["sick"] == {
        "2026-03-02": _rec(300, T2, "B"),
        "2026-03-03": _rec(240, T2, "A"),
        "2026-03-04": _rec(60, T1, "B"),
    }
    # Beide Seiten haben nach dem letzten Abgleich geändert: trotzdem kein Konflikt.
    assert ab["conflicts"] == ba["conflicts"] == []


def test_tombstone_beats_older_save():
    live = _doc({"2026-03-02": _rec(480, T1, "A")})
    gone = _doc({"2026-03-02": _rec(0, T2, "B", deleted=True)})
    for merged in (merge(live, gone, T0), merge(gone, live, T0)):
        assert merged["sick"] == {"2026-03-02": _rec(0, T2, "B", deleted=True)}


def test_missing_section_never_deletes():
    days = {"2026-03-02": _rec(480, T1, "A"), "2026-03-03": _rec(0, T1, "A", deleted=True)}
    assert merge(_doc(days), _doc(), T0)["sick"] == days
    assert merge(_doc(), _doc(days), T0)["sick"] == days


def test_excluded_device_keeps_sick_days_when_remote_lacks_section():
    """Ein Gerät bis 1.29 hat den Bereich beim Hochladen weggelassen; das
    zurückkehrende Gerät darf daraus keine Löschung machen."""
    local = _doc({"2026-03-02": _rec(480, OLD, "A")})
    remote = _doc(watermark=WM)
    merged = merge(local, remote, T0)   # last_pull_at < Watermark: excluded
    assert merged["sick"] == {"2026-03-02": _rec(480, OLD, "A")}


def test_excluded_device_keeps_old_sick_day_missing_from_remote_section():
    """Auch ein vorhandener Bereich ohne den Tag heißt nicht „gelöscht“: ein
    neueres Gerät, das den Tag nie gesehen hat, kann ihn ohne ihn hochgeladen
    haben. Kein Self-Heal für Krankheitstage."""
    local = _doc({"2026-03-02": _rec(480, OLD, "A")})
    remote = _doc({}, watermark=WM)
    merged = merge(local, remote, T0)   # last_pull_at < Watermark: excluded
    assert merged["sick"] == {"2026-03-02": _rec(480, OLD, "A")}


def test_excluded_device_keeps_sick_day_whose_remote_record_is_broken():
    """Ein unbrauchbarer Remote-Datensatz verdrängt den lokalen Tag nicht, auch
    nicht auf einem Gerät, das über eine Kompaktierung hinweg offline war."""
    local = _doc({"2026-03-02": _rec(480, OLD, "A")})
    remote = _doc({"2026-03-02": {"minutes": "8h", "modified_at": FRESH,
                                  "device_id": "B", "deleted": False}}, watermark=WM)
    merged = merge(local, remote, T0)
    assert merged["sick"] == {"2026-03-02": _rec(480, OLD, "A")}


def test_broken_sick_section_keeps_doc_valid_and_local_days():
    remote = _doc(["x"], watermark=WM)
    assert validate_remote_doc(remote) == (True, "")
    local = _doc({"2026-03-02": _rec(480, OLD, "A")})
    merged = merge(local, remote, T0)   # last_pull_at < Watermark: excluded
    assert merged["sick"] == {"2026-03-02": _rec(480, OLD, "A")}


def test_broken_sick_section_is_logged_without_dates(caplog):
    caplog.set_level(logging.DEBUG)
    merge(_doc(), _doc(["2026-03-02", 480]), T0)
    assert caplog.records, "ein kaputter Bereich wird geloggt"
    assert "2026-03-02" not in caplog.text
    assert "480" not in caplog.text


def test_bad_sick_record_is_skipped_not_merged():
    local = _doc({"2026-03-02": _rec(480, T1, "A")})
    remote = _doc({"2026-03-02": {"minutes": "8h", "modified_at": T2,
                                  "device_id": "B", "deleted": False}})
    assert merge(local, remote, T0)["sick"] == {"2026-03-02": _rec(480, T1, "A")}
    assert merge(remote, local, T0)["sick"] == {"2026-03-02": _rec(480, T1, "A")}


def test_merge_strips_settled_sick_tombstones():
    local = _doc({"2026-03-02": _rec(0, OLD, "A", deleted=True),
                  "2026-03-03": _rec(0, FRESH, "A", deleted=True),
                  "2026-03-04": _rec(480, OLD, "A")})
    merged = merge(local, _doc(watermark=WM), "")
    assert merged["sick"] == {"2026-03-03": _rec(0, FRESH, "A", deleted=True),
                              "2026-03-04": _rec(480, OLD, "A")}


# --- apply_merged_doc --------------------------------------------------------


def test_apply_writes_store_only_when_doc_has_section(tmp_path, stamp):
    storage, settings, conflicts, sick = _stores(tmp_path)
    sick.save_range({"2026-03-02": 480})
    before = sick.get_all_raw()

    apply_merged_doc(_doc(), storage, settings, conflicts, sick_store=sick)
    assert sick.get_all_raw() == before

    apply_merged_doc(_doc({"2026-03-05": _rec(240, T2, "B")}), storage, settings,
                     conflicts, sick_store=sick)
    assert sick.get_all_raw() == {"2026-03-05": _rec(240, T2, "B")}

    # Ohne Store wird der Bereich übergangen, nicht verlangt.
    apply_merged_doc(_doc({"2026-03-06": _rec(60, T2, "B")}), storage, settings, conflicts)
    assert sick.get_all_raw() == {"2026-03-05": _rec(240, T2, "B")}


def test_round_trip_between_two_desktops(tmp_path, stamp):
    a = _stores(tmp_path, "A")
    b = _stores(tmp_path, "B")
    a[3].save_range({"2026-03-02": 480, "2026-03-03": 450})
    stamp["value"] = T2
    b[3].save_range({"2026-03-03": 300})

    doc_a = build_local_doc(*a[:3], sick_store=a[3])
    doc_b = build_local_doc(*b[:3], sick_store=b[3])
    merged = merge(doc_a, doc_b, T0)
    apply_merged_doc(merged, *a[:3], sick_store=a[3])

    assert a[3].day_minutes() == {"2026-03-02": 480, "2026-03-03": 300}


# --- Kompaktierung und Startup-Sweep ----------------------------------------


def test_compact_strips_settled_sick_tombstones(tmp_path, stamp):
    storage, settings, conflicts, sick = _stores(tmp_path)
    sick.save_range({"2026-03-02": 480, "2026-03-03": 480})
    sick.delete_days(["2026-03-03"])

    compact_local(storage, settings, conflicts, "2099-01-01T00:00:00Z", sick_store=sick)

    assert sick.get_all_raw() == {"2026-03-02": _rec(480, T1, "A")}
    reloaded = SickStore(str(tmp_path / "sick-A.json"), device_id="A")
    assert "2026-03-03" not in reloaded.get_all_raw()


def test_compact_without_sick_tombstones_writes_no_sick_file(tmp_path):
    storage, settings, conflicts, sick = _stores(tmp_path)
    compact_local(storage, settings, conflicts, "2099-01-01T00:00:00Z", sick_store=sick)
    assert not (tmp_path / "sick-A.json").exists()


def test_sweep_drops_sick_tombstones_only_when_never_synced(tmp_path, stamp):
    storage, settings, conflicts, sick = _stores(tmp_path)
    sick.save_range({"2026-03-02": 480, "2026-03-03": 480})
    sick.delete_days(["2026-03-03"])
    storage.save("2026-03-04", [{"start": "08:00", "end": "16:00", "pause": 30,
                                 "kategorie": ""}])
    storage.delete("2026-03-04")

    settings.set("sync_enabled", False)
    settings.set("last_pull_at", "2026-02-28T10:00:00Z")
    assert drop_orphan_tombstones(storage, settings, sick_store=sick) == 0
    assert sick.get_all_raw()["2026-03-03"]["deleted"] is True

    settings.set("last_pull_at", "")
    assert drop_orphan_tombstones(storage, settings, sick_store=sick) == 2
    assert sick.get_all_raw() == {"2026-03-02": _rec(480, T1, "A")}
    assert "2026-03-04" not in storage.get_all_raw()
