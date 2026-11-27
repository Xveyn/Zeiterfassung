import glob
import json
import logging

import pytest

from src import sick_days
from src.sick_days import SickBlock, SickStore, clean_section


@pytest.fixture
def store(tmp_path):
    return SickStore(str(tmp_path / "sick.json"), device_id="dev-a")


def _rec(minutes=480, deleted=False):
    return {"minutes": minutes, "modified_at": "2026-03-01T10:00:00Z",
            "device_id": "dev-x", "deleted": deleted}


def test_save_range_writes_live_days_with_stamp_and_device(store, monkeypatch):
    monkeypatch.setattr(sick_days, "utc_now_iso", lambda: "2026-03-02T08:00:00Z")
    store.save_range({"2026-03-02": 450})
    assert store.get_all_raw() == {"2026-03-02": {
        "minutes": 450, "deleted": False, "device_id": "dev-a",
        "modified_at": "2026-03-02T08:00:00Z"}}


def test_day_minutes_skips_tombstones(store):
    store.save_range({"2026-03-02": 480, "2026-03-03": 480})
    store.delete_days(["2026-03-03"])
    assert store.day_minutes() == {"2026-03-02": 480}
    assert store.is_sick("2026-03-02")
    assert not store.is_sick("2026-03-03")


def test_delete_days_writes_tombstones_with_zero_minutes(store):
    store.save_range({"2026-03-02": 480})
    store.delete_days(["2026-03-02"])
    rec = store.get_all_raw()["2026-03-02"]
    assert rec["deleted"] is True and rec["minutes"] == 0


def test_block_for_spans_month_and_year_boundary(store):
    days = {"2026-12-30": 480, "2026-12-31": 480, "2027-01-01": 0, "2027-01-02": 0}
    store.save_range(days)
    assert store.block_for("2027-01-01") == SickBlock("2026-12-30", "2027-01-02", days)
    assert store.block_for("2027-01-03") is None


def test_block_for_stops_at_gap_and_at_tombstone(store):
    store.save_range({"2026-03-02": 480, "2026-03-03": 480, "2026-03-04": 480,
                      "2026-03-06": 480})
    store.delete_days(["2026-03-04"])
    block = store.block_for("2026-03-02")
    assert block == SickBlock("2026-03-02", "2026-03-03",
                              {"2026-03-02": 480, "2026-03-03": 480})
    other = store.block_for("2026-03-06")
    assert other is not None and other.date_from == "2026-03-06"


def test_blocks_are_chronological_and_total_minutes_sums(store):
    store.save_range({"2026-05-04": 60, "2026-03-02": 480, "2026-03-03": 240})
    blocks = store.blocks()
    assert [b.date_from for b in blocks] == ["2026-03-02", "2026-05-04"]
    assert blocks[0].total_minutes == 720


def test_replace_block_tombstones_days_outside_new_range(store):
    store.save_range({"2026-03-02": 480, "2026-03-03": 480, "2026-03-04": 480})
    store.replace_block(["2026-03-02", "2026-03-03", "2026-03-04"],
                        {"2026-03-03": 300, "2026-03-04": 480})
    assert store.day_minutes() == {"2026-03-03": 300, "2026-03-04": 480}
    assert store.get_all_raw()["2026-03-02"]["deleted"] is True


def test_load_skips_bad_records_and_logs_no_dates(tmp_path, caplog):
    path = tmp_path / "sick.json"
    path.write_text(json.dumps({
        "2026-03-02": {"minutes": "8h", "modified_at": "x", "device_id": "d",
                       "deleted": False},
        "kaputt": _rec(),
        "2026-03-03": _rec(),
    }), encoding="utf-8")
    with caplog.at_level(logging.DEBUG):
        s = SickStore(str(path))
    assert s.day_minutes() == {"2026-03-03": 480}
    assert "2 unbrauchbare" in caplog.text
    assert "2026-" not in caplog.text


def test_corrupt_file_is_quarantined(tmp_path):
    path = tmp_path / "sick.json"
    path.write_text("{nope", encoding="utf-8")
    s = SickStore(str(path))
    assert s.day_minutes() == {}
    assert glob.glob(str(path) + ".corrupt-*")


def test_failed_write_rolls_back_memory(store, monkeypatch):
    store.save_range({"2026-03-02": 480})

    def boom(path, obj):
        raise OSError("voll")
    monkeypatch.setattr(sick_days, "atomic_write_json", boom)
    with pytest.raises(OSError):
        store.save_range({"2026-03-03": 480})
    with pytest.raises(OSError):
        store.delete_days(["2026-03-02"])
    assert store.day_minutes() == {"2026-03-02": 480}


@pytest.mark.parametrize("minutes", [1441, -1])
def test_save_range_rejects_out_of_range_minutes(store, minutes):
    with pytest.raises(ValueError):
        store.save_range({"2026-03-02": minutes})
    assert store.day_minutes() == {}


def test_save_range_rejects_non_date(store):
    with pytest.raises(ValueError):
        store.save_range({"morgen": 60})


def test_clean_section_drops_non_dict_and_bad_keys():
    assert clean_section([]) == {}
    assert clean_section("x") == {}


def test_clean_record_tombstone_gets_zero_minutes_and_exact_keys():
    rec = sick_days.clean_record({**_rec(300, True), "extra": 1})
    assert rec == {"minutes": 0, "modified_at": "2026-03-01T10:00:00Z",
                   "device_id": "dev-x", "deleted": True}
    assert sick_days.clean_record({**_rec(), "minutes": True}) is None
    assert sick_days.clean_record({**_rec(), "minutes": 1441}) is None


def test_apply_merge_requires_keys_and_replaces(store):
    store.save_range({"2026-03-02": 480})
    with pytest.raises(ValueError):
        store.apply_merge({"2026-03-03": {"minutes": 1}})
    assert store.day_minutes() == {"2026-03-02": 480}
    store.apply_merge({"2026-03-03": _rec(60)})
    assert store.day_minutes() == {"2026-03-03": 60}


def test_runs():
    assert sick_days.runs(["2026-03-04", "2026-03-02", "2026-03-03", "2026-03-09"]) == [
        ("2026-03-02", "2026-03-04"), ("2026-03-09", "2026-03-09")]
    assert sick_days.runs([]) == []
