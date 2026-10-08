# tests/test_storage_hardening.py
"""Ein beschädigter oder fremder Stand darf `Storage` nie zum Absturz bringen.

Zwei Linien: beim Laden wird die STRUKTUR repariert (mit Sicherung), und an der
Lese-Grenze (`get`/`get_all`) werden die WERTE bereinigt (`sanitize_slot`). Das
Original bleibt dort unangetastet, damit der Sync keine spontanen Änderungen sieht.
"""
import json
import logging
import math
import os

import pytest

from src.storage import MAX_PAUSE_MINUTES, Storage, sanitize_slot
from tests.conftest import ist_slot

DAY = "2026-01-05"


def entry(slots, deleted=False):
    return {"slots": slots, "modified_at": "2026-01-05T08:00:00Z", "device_id": "x",
            "deleted": deleted}


def write(tmp_path, content, name="z.json"):
    path = tmp_path / name
    path.write_text(content if isinstance(content, str) else json.dumps(content),
                    encoding="utf-8")
    return str(path)


def backups(tmp_path):
    return sorted(p.name for p in tmp_path.iterdir() if ".corrupt-" in p.name)


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


# --- Laden: Struktur --------------------------------------------------------------------------------------

@pytest.mark.parametrize("content", ["[]", "[1, 2]", '"text"', "42", "true", "3.5"])
def test_a_non_object_top_level_is_quarantined_and_the_app_starts_empty(tmp_path, content, caplog):
    path = write(tmp_path, content)

    with caplog.at_level(logging.WARNING):
        storage = Storage(path, device_id="dev")

    assert storage.get_all() == {}
    assert not os.path.exists(path)
    (name,) = backups(tmp_path)
    assert (tmp_path / name).read_text(encoding="utf-8") == content          # Inhalt gerettet
    assert "Top-Level" in caplog.text and "Quarantäne" in caplog.text
    storage.save(DAY, [ist_slot("08:00", "09:00")])                          # und benutzbar
    assert Storage(path, device_id="dev").get(DAY) == {"slots": [ist_slot("08:00", "09:00")]}


def test_non_object_entries_are_dropped_with_a_backup_and_the_file_is_healed(tmp_path, caplog):
    original = {"2026-01-05": entry([ist_slot("08:00", "09:00")]), "2026-01-06": None,
                "2026-01-07": "x", "2026-01-08": [1]}
    path = write(tmp_path, original)

    with caplog.at_level(logging.WARNING):
        storage = Storage(path, device_id="dev")

    assert list(storage.get_all()) == ["2026-01-05"]
    (name,) = backups(tmp_path)
    assert json.loads((tmp_path / name).read_text(encoding="utf-8")) == original
    assert "Sicherung" in caplog.text
    assert sorted(json.loads(open(path, encoding="utf-8").read())) == ["2026-01-05"]   # geheilt


def test_a_healed_file_makes_no_second_backup_on_the_next_start(tmp_path):
    path = write(tmp_path, {"2026-01-05": None, "2026-01-06": entry(["x"])})
    Storage(path, device_id="dev")
    assert len(backups(tmp_path)) == 1

    Storage(path, device_id="dev")
    Storage(path, device_id="dev")

    assert len(backups(tmp_path)) == 1


def test_broken_slot_lists_are_repaired(tmp_path):
    path = write(tmp_path, {
        "2026-01-05": entry(["x", None, ist_slot("08:00", "09:00"), 5]),
        "2026-01-06": entry("kaputt"), "2026-01-07": entry(None), "2026-01-08": entry({"a": 1}),
    })

    storage = Storage(path, device_id="dev")

    raw = storage.get_all_raw()
    assert raw["2026-01-05"]["slots"] == [ist_slot("08:00", "09:00")]
    assert [raw[d]["slots"] for d in ("2026-01-06", "2026-01-07", "2026-01-08")] == [[], [], []]
    assert len(backups(tmp_path)) == 1


def test_repair_keeps_metadata_and_tombstones(tmp_path):
    tomb = entry([], deleted=True)
    path = write(tmp_path, {"2026-01-05": entry(["x", ist_slot("08:00", "09:00")]),
                            "2026-01-06": tomb})

    raw = Storage(path, device_id="dev").get_all_raw()

    assert raw["2026-01-05"]["modified_at"] == "2026-01-05T08:00:00Z"
    assert raw["2026-01-05"]["device_id"] == "x"
    assert raw["2026-01-06"] == tomb


def test_unusual_values_stay_raw_on_disk_but_are_clean_when_read(tmp_path):
    odd = {"start": "08:00", "end": "12:00", "pause": None, "kategorie": ""}
    path = write(tmp_path, {DAY: entry([odd])})

    storage = Storage(path, device_id="dev")

    assert storage.get_all_raw()[DAY]["slots"] == [odd]                      # Sync sieht das Original
    assert storage.get(DAY) == {"slots": [ist_slot("08:00", "12:00", 0, "")]}
    assert backups(tmp_path) == []                                           # kein Anlass zur Reparatur


def test_a_clean_file_is_neither_backed_up_nor_rewritten(tmp_path):
    path = write(tmp_path, {DAY: entry([ist_slot("08:00", "09:00")])})
    os.utime(path, (1_000_000_000, 1_000_000_000))

    Storage(path, device_id="dev")

    assert backups(tmp_path) == []
    assert os.path.getmtime(path) == 1_000_000_000


def test_legacy_entries_are_still_migrated_next_to_broken_ones(tmp_path):
    path = write(tmp_path, {"2026-01-05": {"start": "08:00", "end": "09:00", "pause": 15},
                            "2026-01-06": None})

    storage = Storage(path, device_id="dev")

    assert storage.get(DAY) == {"slots": [ist_slot("08:00", "09:00", 15)]}


def test_without_a_backup_nothing_is_written_back(tmp_path, monkeypatch, caplog):
    original = {DAY: entry([ist_slot("08:00", "09:00")]), "2026-01-06": None}
    path = write(tmp_path, original)

    def refuse(*_args):
        raise OSError("Platte voll")
    monkeypatch.setattr("src.storage.backup_corrupt", refuse)

    with caplog.at_level(logging.WARNING):
        storage = Storage(path, device_id="dev")

    assert list(storage.get_all()) == [DAY]                                  # der Start gelingt
    assert json.loads(open(path, encoding="utf-8").read()) == original       # Datei unberührt
    assert "nicht auf die Platte" in caplog.text


def test_a_failing_heal_write_does_not_stop_the_start(tmp_path, monkeypatch):
    path = write(tmp_path, {DAY: entry([ist_slot("08:00", "09:00")]), "2026-01-06": None})

    def refuse(self):
        raise OSError("schreibgeschützt")
    monkeypatch.setattr(Storage, "_save_to_disk", refuse)

    assert list(Storage(path, device_id="dev").get_all()) == [DAY]


def test_nan_never_reaches_a_reader(tmp_path):
    path = write(tmp_path, '{"2026-01-05": {"slots": [{"start": "08:00", "end": "12:00", '
                           '"pause": NaN, "kategorie": ""}], "modified_at": "a", '
                           '"device_id": "x", "deleted": false}}')
    pause = Storage(path, device_id="dev").get(DAY)["slots"][0]["pause"]
    assert pause == 0 and not math.isnan(pause)


# --- Review-Befunde (I2, M3) ---------------------------------------------------------------------------

def test_a_lone_surrogate_next_to_a_broken_entry_does_not_stop_the_start(tmp_path, caplog):
    # Das Zurückschreiben scheitert mit UnicodeEncodeError (ein ValueError, kein OSError).
    path = write(tmp_path, '{"2026-01-05": {"slots": [{"start": "08:00", "end": "09:00", '
                           '"pause": 0, "kategorie": "\\ud83d"}], "modified_at": "a", '
                           '"device_id": "x", "deleted": false}, "2026-01-06": null}')
    before = open(path, encoding="utf-8").read()

    with caplog.at_level(logging.WARNING):
        storage = Storage(path, device_id="dev")

    assert list(storage.get_all()) == [DAY]
    assert open(path, encoding="utf-8").read() == before                 # nichts überschrieben
    assert "nicht auf die Platte" in caplog.text


def test_a_heal_that_cannot_be_written_back_makes_one_backup_not_one_per_start(tmp_path):
    path = write(tmp_path, '{"2026-01-05": {"slots": [{"start": "08:00", "end": "09:00", '
                           '"pause": 0, "kategorie": "\\ud83d"}], "modified_at": "a", '
                           '"device_id": "x", "deleted": false}, "2026-01-06": null}')

    for _ in range(3):
        Storage(path, device_id="dev")

    assert len(backups(tmp_path)) == 1


def test_a_healed_file_is_not_backed_up_again_on_later_starts(tmp_path, monkeypatch):
    import src.storage as storage_module
    calls = []
    real = storage_module.backup_corrupt
    monkeypatch.setattr(storage_module, "backup_corrupt",
                        lambda *a: calls.append(a) or real(*a))
    path = write(tmp_path, {"2026-01-06": None, DAY: entry([ist_slot("08:00", "09:00")])})

    for _ in range(3):
        Storage(path, device_id="dev")

    assert len(calls) == 1                                  # nur der erste Start hat gesichert
