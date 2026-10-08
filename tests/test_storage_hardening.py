# tests/test_storage_hardening.py
"""Ein beschädigter oder fremder Stand darf `Storage` nie zum Absturz bringen.

Zwei Linien: beim Laden wird die STRUKTUR repariert (mit Sicherung), und an der
Lese-Grenze (`get`/`get_all`) werden die WERTE bereinigt (`sanitize_slot`). Das
Original bleibt dort unangetastet, damit der Sync keine spontanen Änderungen sieht.
"""
import pytest

from src.storage import MAX_PAUSE_MINUTES, Storage, sanitize_slot
from tests.conftest import ist_slot

DAY = "2026-01-05"


def entry(slots, deleted=False):
    return {"slots": slots, "modified_at": "2026-01-05T08:00:00Z", "device_id": "x",
            "deleted": deleted}


# --- sanitize_slot ------------------------------------------------------------------------------

@pytest.mark.parametrize("junk", [None, "x", 5, 5.5, True, ["a"], ()])
def test_a_non_object_slot_is_dropped(junk):
    assert sanitize_slot(junk) is None


@pytest.mark.parametrize("pause", [None, True, False, "30", "", 30.5, -1, -0.5,
                                   MAX_PAUSE_MINUTES + 1, float("inf"), float("-inf"),
                                   float("nan"), 10 ** 400, [30], {"a": 1}])
def test_an_unusable_pause_becomes_zero(pause):
    assert sanitize_slot(ist_slot("08:00", "12:00", pause))["pause"] == 0


@pytest.mark.parametrize("pause,expected", [(0, 0), (30, 30), (30.0, 30),
                                            (MAX_PAUSE_MINUTES, MAX_PAUSE_MINUTES)])
def test_a_usable_pause_is_kept_as_an_int(pause, expected):
    clean = sanitize_slot(ist_slot("08:00", "12:00", pause))
    assert clean["pause"] == expected and type(clean["pause"]) is int


@pytest.mark.parametrize("junk", [None, 5, True, ["08:00"], {"a": 1}])
def test_start_and_end_must_be_text(junk):
    clean = sanitize_slot({"start": junk, "end": junk, "pause": 0, "kategorie": ""})
    assert (clean["start"], clean["end"]) == (None, None)


@pytest.mark.parametrize("junk", [None, 5, True, ["x"]])
def test_a_non_text_category_becomes_empty(junk):
    assert sanitize_slot(ist_slot("08:00", "12:00", 0, junk))["kategorie"] == ""


def test_missing_fields_get_their_defaults():
    assert sanitize_slot({"start": "08:00", "end": "12:00"}) == ist_slot("08:00", "12:00", 0, "")
    assert sanitize_slot({}) == ist_slot(None, None, 0, "")


def test_a_clean_slot_is_unchanged_and_other_keys_survive():
    slot = dict(ist_slot("08:00", "12:00", 30, "Büro"), extra=1)
    assert sanitize_slot(slot) == slot


def test_sanitize_returns_a_copy():
    slot = ist_slot("08:00", "12:00", None)
    clean = sanitize_slot(slot)
    clean["start"] = "99:99"
    assert slot == ist_slot("08:00", "12:00", None)


# --- Lese-Grenze: get / get_all ---------------------------------------------------------------------

@pytest.fixture
def storage(tmp_path):
    return Storage(str(tmp_path / "z.json"), device_id="dev")


def test_get_all_skips_non_object_entries_and_drops_non_object_slots(storage):
    storage._data.update({
        "2026-01-05": None, "2026-01-06": "x", "2026-01-07": ["a"], "2026-01-08": 5,
        "2026-01-09": entry(["x", None, ist_slot("08:00", "09:00")]),
        "2026-01-10": entry("kaputt"), "2026-01-11": {"modified_at": "a"},
    })

    assert storage.get_all() == {
        "2026-01-09": {"slots": [ist_slot("08:00", "09:00")]},
        "2026-01-10": {"slots": []},
        "2026-01-11": {"slots": []},
    }


def test_get_treats_a_non_object_entry_as_absent(storage):
    storage._data[DAY] = "x"
    assert storage.get(DAY) is None


def test_get_cleans_the_values_of_a_slot(storage):
    storage._data[DAY] = entry([{"start": "08:00", "end": "12:00", "pause": None,
                                 "kategorie": 7}])
    assert storage.get(DAY) == {"slots": [ist_slot("08:00", "12:00", 0, "")]}


def test_reading_never_changes_the_raw_data(storage):
    raw = entry([{"start": "08:00", "end": "12:00", "pause": float("inf")}, "x"])
    storage._data[DAY] = raw
    snapshot = repr(raw)

    storage.get_all()
    storage.get(DAY)

    assert repr(storage.get_all_raw()[DAY]) == snapshot


def test_a_returned_slot_is_a_copy(storage):
    storage.save(DAY, [ist_slot("08:00", "12:00")])
    storage.get(DAY)["slots"][0]["start"] = "x"
    assert storage.get(DAY)["slots"][0]["start"] == "08:00"


def test_hours_can_be_computed_for_every_cleaned_slot(storage):
    from src.time_utils import calculate_hours
    storage._data[DAY] = entry([ist_slot("08:00", "12:00", pause)
                                for pause in (None, "x", float("nan"), 10 ** 400, True)])
    for slot in storage.get(DAY)["slots"]:
        assert calculate_hours(slot["start"], slot["end"], slot["pause"]) == 4.0
