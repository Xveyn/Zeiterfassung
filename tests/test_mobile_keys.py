# tests/test_mobile_keys.py
import base64
import json
import os
import stat
import time

import pytest

from src import mobile_keys
from src.mobile_keys import MobileKeyStore, MobileKeysReadOnly

KEY = bytes(range(32))
ID = "phone-0001"


class FakeRing:
    """Ersetzt keyring_store: put/fetch/remove wie dort (fetch: None = nicht ermittelbar, "" = kein Eintrag)."""
    def __init__(self):
        self.items, self.available, self.calls = {}, True, []

    def put(self, key, value):
        self.calls.append(("put", key))
        if not self.available:
            return False
        self.items[key] = value
        return True

    def fetch(self, key):
        self.calls.append(("fetch", key))
        if not self.available:
            return None
        return self.items.get(key, "")

    def remove(self, key):
        self.calls.append(("remove", key))
        self.items.pop(key, None)


@pytest.fixture
def ring(monkeypatch):
    fake = FakeRing()
    monkeypatch.setattr(mobile_keys, "keyring_store", fake)
    return fake


def store_at(tmp_path):
    return MobileKeyStore(str(tmp_path / "mobile_keys.json"))


def file_of(tmp_path):
    return json.loads((tmp_path / "mobile_keys.json").read_text("utf-8"))


# --- put/get: Cache und Datei ----------------------------------------------------------------

def test_put_serves_from_the_cache_and_writes_the_file_first(tmp_path, ring):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    assert store.get(ID) == KEY
    assert file_of(tmp_path)["keys"][ID]["location"] == "file"
    assert ring.calls == []                                       # put berührt den Schlüsselbund nie


def test_get_never_calls_the_keyring(tmp_path, ring):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    for _ in range(5):
        store.get(ID)
        store.get("unknown-device")
    assert ring.calls == []


def test_a_file_key_survives_a_restart(tmp_path, ring):
    store_at(tmp_path).put(ID, KEY)
    assert store_at(tmp_path).get(ID) == KEY


def test_put_replaces_an_existing_key(tmp_path, ring):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    store.put(ID, bytes(32))
    assert store.get(ID) == bytes(32) and store_at(tmp_path).get(ID) == bytes(32)


# --- migrate: Datei -> Schlüsselbund ----------------------------------------------------------

def test_migrate_moves_the_key_and_empties_the_file_entry(tmp_path, ring):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    assert store.migrate() == 1
    entry = file_of(tmp_path)["keys"][ID]
    assert entry == {"location": "keyring"}                       # kein Schlüssel mehr in der Datei
    assert KEY.hex() not in (tmp_path / "mobile_keys.json").read_text("utf-8")
    assert store.get(ID) == KEY and store.where() == {ID: "keyring"}
    assert ring.items["mobile:" + ID]                              # liegt unter dem erwarteten Namen


def test_migrate_keeps_the_file_when_no_keyring_is_available(tmp_path, ring):
    ring.available = False
    store = store_at(tmp_path)
    store.put(ID, KEY)
    assert store.migrate() == 0
    assert file_of(tmp_path)["keys"][ID]["location"] == "file" and store.get(ID) == KEY
    assert store.where() == {ID: "file"}


def test_migrate_rewrites_the_file_only_after_a_successful_read_back(tmp_path, ring, monkeypatch):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    monkeypatch.setattr(ring, "fetch", lambda key: "etwas-anderes")   # Zurücklesen stimmt nicht
    assert store.migrate() == 0
    assert file_of(tmp_path)["keys"][ID]["location"] == "file"


def test_migrate_is_idempotent_and_retries_later(tmp_path, ring):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    ring.available = False
    assert store.migrate() == 0
    ring.available = True
    assert store.migrate() == 1 and store.migrate() == 0


# --- load: Schlüsselbund -> Cache -------------------------------------------------------------

def test_a_restart_has_no_key_until_load_runs(tmp_path, ring):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    store.migrate()
    fresh = store_at(tmp_path)
    assert fresh.get(ID) is None                                  # Cache noch leer, kein Blockieren
    assert fresh.load() is True
    assert fresh.get(ID) == KEY


def test_load_stops_at_the_first_unreadable_key_and_reports_it(tmp_path, ring):
    store = store_at(tmp_path)
    for n in range(3):
        store.put(f"phone-000{n}", KEY)
    store.migrate()
    ring.available = False
    ring.calls.clear()
    fresh = store_at(tmp_path)
    assert fresh.load() is False
    assert len([c for c in ring.calls if c[0] == "fetch"]) == 1   # nicht 3 mal den Watchdog abwarten


def test_request_load_is_throttled_and_fills_the_cache_in_the_background(tmp_path, ring):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    store.migrate()
    fresh = store_at(tmp_path)
    fresh.request_load(ID)
    deadline = time.time() + 2
    while fresh.get(ID) is None and time.time() < deadline:
        time.sleep(0.01)
    assert fresh.get(ID) == KEY
    ring.calls.clear()
    fresh.request_load("phone-9999")
    fresh.request_load("phone-9999")
    time.sleep(0.2)
    assert len([c for c in ring.calls if c == ("fetch", "mobile:phone-9999")]) <= 1    # gedrosselt


# --- remove / retain --------------------------------------------------------------------------

def test_remove_clears_cache_file_and_keyring(tmp_path, ring):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    store.migrate()
    store.remove(ID)
    assert store.get(ID) is None and ID not in file_of(tmp_path)["keys"]
    assert "mobile:" + ID not in ring.items


def test_remove_an_unknown_device_is_not_an_error(tmp_path, ring):
    store_at(tmp_path).remove("phone-9999")


def test_retain_drops_keys_of_unknown_devices_everywhere(tmp_path, ring):
    store = store_at(tmp_path)
    store.put("a" * 8, KEY)
    store.put("b" * 8, KEY)
    store.migrate()
    store.retain(["a" * 8])
    assert store.get("a" * 8) == KEY and store.get("b" * 8) is None
    assert "mobile:" + "b" * 8 not in ring.items and "mobile:" + "a" * 8 in ring.items


# --- Datei: Härtung, Fehler, Fremddaten -------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="POSIX-Rechte")
def test_the_file_is_private_and_atomic(tmp_path, ring):
    store_at(tmp_path).put(ID, KEY)
    path = tmp_path / "mobile_keys.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["mobile_keys.json"]     # keine Temp-Reste


def test_the_hardening_helper_runs_for_every_write(tmp_path, ring, monkeypatch):
    calls = []
    monkeypatch.setattr("src.secure_file.harden_windows_acl", lambda p: calls.append(p))
    store = store_at(tmp_path)
    store.put(ID, KEY)
    store.migrate()
    assert len(calls) == 2                                         # put und Umzug schreiben die Datei


def test_a_corrupt_file_is_quarantined_and_starts_empty(tmp_path, ring):
    (tmp_path / "mobile_keys.json").write_text("{kaputt", encoding="utf-8")
    store = store_at(tmp_path)
    assert store.get(ID) is None
    assert any(p.name.startswith("mobile_keys.json.corrupt-") for p in tmp_path.iterdir())


def test_broken_entries_are_skipped_not_fatal(tmp_path, ring):
    good = "A" * 43
    (tmp_path / "mobile_keys.json").write_text(json.dumps({"schema_version": 1, "keys": {
        "phone-0001": {"location": "file", "key": "!!"}, "phone-0002": 5, "x": {"location": "file", "key": good},
        "phone-0003": {"location": "file", "key": good}, "phone-0004": {"location": "wolke"},
        "phone-0005": {"location": "keyring"}}}), encoding="utf-8")
    store = store_at(tmp_path)
    for broken in ("phone-0001", "phone-0002", "x", "phone-0004"):
        assert store.get(broken) is None and broken not in store.where()
    assert store.get("phone-0003") is not None
    assert store.where()["phone-0005"] == "keyring"


def test_a_newer_schema_makes_the_store_read_only_and_untouched(tmp_path, ring):
    original = json.dumps({"schema_version": 99, "keys": {}})
    (tmp_path / "mobile_keys.json").write_text(original, encoding="utf-8")
    store = store_at(tmp_path)
    with pytest.raises(MobileKeysReadOnly):
        store.put(ID, KEY)
    assert (tmp_path / "mobile_keys.json").read_text("utf-8") == original


def test_a_failed_write_rolls_the_memory_back(tmp_path, ring, monkeypatch):
    store = store_at(tmp_path)
    monkeypatch.setattr("os.replace", lambda a, b: (_ for _ in ()).throw(OSError("voll")))
    with pytest.raises(OSError):
        store.put(ID, KEY)
    assert store.get(ID) is None


def test_no_secret_in_the_log(tmp_path, ring, caplog):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    store.migrate()
    ring.available = False
    store_at(tmp_path).load()
    (tmp_path / "mobile_keys.json").write_text("{kaputt", encoding="utf-8")
    store_at(tmp_path)
    secret_forms = (KEY.hex(), base64.urlsafe_b64encode(KEY).rstrip(b"=").decode("ascii"))
    assert not any(form in caplog.text for form in secret_forms)


def test_a_key_removed_while_it_migrates_leaves_nothing_behind_in_the_keyring(tmp_path, ring):
    # Widerruf während des Umzugs: der Schlüssel darf nicht als verwaistes Geheimnis im Schlüsselbund bleiben
    # (forget_all und retain arbeiten nur über die Datei und fänden ihn nie wieder).
    store = store_at(tmp_path)
    store.put("a" * 8, KEY)
    store.put("b" * 8, KEY)
    original_put = ring.put

    def put_then_revoke_b(key, value):
        result = original_put(key, value)
        if key == "mobile:" + "a" * 8:
            store.remove("b" * 8)
        return result
    ring.put = put_then_revoke_b

    store.migrate()

    assert "mobile:" + "b" * 8 not in ring.items
    assert file_of(tmp_path)["keys"] == {"a" * 8: {"location": "keyring"}}


def test_a_re_paired_key_is_not_removed_by_the_migration_of_the_old_one(tmp_path, ring):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    original_put = ring.put

    def put_then_repair(key, value):
        result = original_put(key, value)
        store.put(ID, bytes(reversed(range(32))))                     # neu gekoppelt: anderer Schlüssel
        return result
    ring.put = put_then_repair

    assert store.migrate() == 0
    assert store.get(ID) == bytes(reversed(range(32)))
    assert file_of(tmp_path)["keys"][ID]["location"] == "file"        # der neue wartet auf seinen Umzug
