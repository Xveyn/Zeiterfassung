"""Cursor der Boxen (`have`, dauerhaft), #358."""
import json
import os

from src import mobile_box_cursor
from src.mobile_box_cursor import MobileBoxCursor

SECRET = "A" * 43
OTHER = "B" * 43


def _path(tmp_path):
    return str(tmp_path / "mobile_box_cursor.json")


def test_get_default_is_zero(tmp_path):
    assert MobileBoxCursor(_path(tmp_path)).get(SECRET) == 0


def test_advance_only_forward(tmp_path):
    cursor = MobileBoxCursor(_path(tmp_path))
    assert cursor.advance(SECRET, 5) is True
    assert cursor.advance(SECRET, 5) is False
    assert cursor.advance(SECRET, 3) is False
    assert cursor.get(SECRET) == 5


def test_persists_across_instances(tmp_path):
    MobileBoxCursor(_path(tmp_path)).advance(SECRET, 7)
    assert MobileBoxCursor(_path(tmp_path)).get(SECRET) == 7


def test_file_holds_digest_not_secret(tmp_path):
    MobileBoxCursor(_path(tmp_path)).advance(SECRET, 7)
    text = open(_path(tmp_path), encoding="utf-8").read()
    assert SECRET not in text
    data = json.loads(text)
    assert data["schema_version"] == 1
    assert list(data["have"].values()) == [7]


def test_reset_and_retain(tmp_path):
    cursor = MobileBoxCursor(_path(tmp_path))
    cursor.advance(SECRET, 4)
    cursor.advance(OTHER, 9)
    cursor.reset(SECRET)
    assert cursor.get(SECRET) == 0
    assert MobileBoxCursor(_path(tmp_path)).get(SECRET) == 0
    cursor.advance(SECRET, 2)
    cursor.retain([OTHER])
    assert cursor.get(SECRET) == 0 and cursor.get(OTHER) == 9
    assert MobileBoxCursor(_path(tmp_path)).get(OTHER) == 9


def test_write_failure_keeps_memory(tmp_path, monkeypatch):
    def boom(path, obj):
        raise OSError("voll")
    monkeypatch.setattr(mobile_box_cursor, "atomic_write_json", boom)
    cursor = MobileBoxCursor(_path(tmp_path))
    assert cursor.advance(SECRET, 3) is True
    assert cursor.get(SECRET) == 3


def test_corrupt_file_is_quarantined(tmp_path):
    path = _path(tmp_path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{nicht json")
    cursor = MobileBoxCursor(path)
    assert cursor.get(SECRET) == 0
    assert not os.path.exists(path)
    assert any(".corrupt-" in n for n in os.listdir(tmp_path))


def test_invalid_versions_are_dropped(tmp_path):
    path = _path(tmp_path)
    good = mobile_box_cursor._digest(SECRET)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"schema_version": 1, "have": {
            good: 5, "x": 3, mobile_box_cursor._digest(OTHER): -1}}, fh)
    cursor = MobileBoxCursor(path)
    assert cursor.get(SECRET) == 5
    assert cursor.get(OTHER) == 0
    assert cursor.advance(SECRET, 2**31) is False
    assert cursor.advance(SECRET, -1) is False
