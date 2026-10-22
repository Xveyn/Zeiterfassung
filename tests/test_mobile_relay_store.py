"""Ablage der Relay-Geheimnisse der Handys (#331)."""
import json
import os
import stat
import sys

import pytest

from src import mobile_relay_store, secure_file
from src.mobile_relay_store import MobileRelayStore

A = "A" * 43
B = "B" * 43


def store(tmp_path):
    return MobileRelayStore(str(tmp_path / "mobile_relay.json"))


def test_a_secret_survives_a_restart(tmp_path):
    assert store(tmp_path).set("phone-0001", A) is True
    assert store(tmp_path).get("phone-0001") == A


def test_set_reports_a_change_and_writes_only_then(tmp_path, monkeypatch):
    writes = []
    real = secure_file.write_secret_json
    monkeypatch.setattr(mobile_relay_store, "write_secret_json",
                        lambda *a, **k: (writes.append(1), real(*a, **k))[1])
    s = store(tmp_path)
    assert s.set("phone-0001", A) is True
    assert s.set("phone-0001", A) is False
    assert s.set("phone-0001", B) is True
    assert len(writes) == 2


def test_an_unknown_device_has_no_secret(tmp_path):
    assert store(tmp_path).get("nobody") is None


def test_remove_returns_the_secret_and_forgets_it(tmp_path):
    s = store(tmp_path)
    s.set("phone-0001", A)
    assert s.remove("phone-0001") == A
    assert s.remove("phone-0001") is None
    assert store(tmp_path).get("phone-0001") is None


def test_retain_keeps_only_the_listed_devices_and_returns_the_dropped_secrets(tmp_path):
    s = store(tmp_path)
    s.set("phone-0001", A)
    s.set("phone-0002", B)
    assert s.retain(["phone-0002"]) == {"phone-0001": A}
    assert s.known_ids() == {"phone-0002"}
    assert store(tmp_path).known_ids() == {"phone-0002"}


def test_retain_without_a_change_does_not_write(tmp_path, monkeypatch):
    s = store(tmp_path)
    s.set("phone-0001", A)
    monkeypatch.setattr(mobile_relay_store, "write_secret_json",
                        lambda *a, **k: pytest.fail("geschrieben"))
    assert s.retain(["phone-0001", "phone-0009"]) == {}


@pytest.mark.parametrize("secret", ["", "kurz", "A" * 44, "ä" * 43, None, 5, "A" * 42 + "="])
def test_an_unusable_secret_is_refused(tmp_path, secret):
    s = store(tmp_path)
    with pytest.raises(ValueError):
        s.set("phone-0001", secret)
    assert s.known_ids() == set()


def test_a_bad_device_id_is_refused(tmp_path):
    with pytest.raises(ValueError):
        store(tmp_path).set("", A)


def test_a_broken_file_is_quarantined_and_the_store_starts_empty(tmp_path):
    path = tmp_path / "mobile_relay.json"
    path.write_text("{kaputt", encoding="utf-8")
    assert MobileRelayStore(str(path)).known_ids() == set()
    assert list(tmp_path.glob("mobile_relay.json.corrupt-*"))


def test_unusable_entries_are_skipped_on_load(tmp_path):
    path = tmp_path / "mobile_relay.json"
    path.write_text(json.dumps({"schema_version": 1, "secrets": {
        "phone-0001": A, "phone-0002": "kurz", "phone-0003": 5, "": B}}), encoding="utf-8")
    assert MobileRelayStore(str(path)).known_ids() == {"phone-0001"}


def test_a_newer_schema_is_neither_read_nor_overwritten(tmp_path):
    path = tmp_path / "mobile_relay.json"
    text = json.dumps({"schema_version": 99, "secrets": {"phone-0001": A}})
    path.write_text(text, encoding="utf-8")
    s = MobileRelayStore(str(path))
    assert s.known_ids() == set()
    with pytest.raises(mobile_relay_store.MobileRelayReadOnly):
        s.set("phone-0002", B)
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-Rechte")
def test_the_file_is_private(tmp_path):
    store(tmp_path).set("phone-0001", A)
    assert stat.S_IMODE(os.stat(tmp_path / "mobile_relay.json").st_mode) == 0o600


def test_a_failing_write_rolls_the_memory_back(tmp_path, monkeypatch):
    s = store(tmp_path)
    s.set("phone-0001", A)
    monkeypatch.setattr(mobile_relay_store, "write_secret_json",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("Platte voll")))
    with pytest.raises(OSError):
        s.set("phone-0001", B)
    assert s.get("phone-0001") == A
    with pytest.raises(OSError):
        s.set("phone-0002", B)
    assert s.known_ids() == {"phone-0001"}


def test_nothing_in_the_log_carries_a_secret(tmp_path, caplog):
    import logging
    path = tmp_path / "mobile_relay.json"
    path.write_text(json.dumps({"schema_version": 1, "secrets": {"phone-0001": A, "phone-0002": "x" + B}}),
                    encoding="utf-8")
    with caplog.at_level(logging.DEBUG):
        s = MobileRelayStore(str(path))
        s.set("phone-0003", B)
    assert A not in caplog.text and B not in caplog.text
