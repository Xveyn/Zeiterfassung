"""Ablage der Box-Geheimnisse der Relay-Kopplung (#358)."""
import json
import logging
import os
import stat
import sys

import pytest

from src import mobile_box_store, secure_file
from src.mobile_box_store import MobileBoxReadOnly, MobileBoxStore
from src.mobile_relay_codec import BOX_SECRET_RE

A = "A" * 43
B = "B" * 43
NOW = "2026-11-02T10:00:00Z"


def store(tmp_path):
    return MobileBoxStore(str(tmp_path / "mobile_box.json"))


def counting_writes(monkeypatch):
    writes = []
    real = secure_file.write_secret_json
    monkeypatch.setattr(mobile_box_store, "write_secret_json",
                        lambda *a, **k: (writes.append(1), real(*a, **k))[1])
    return writes


def test_a_new_store_is_empty(tmp_path):
    s = store(tmp_path)
    assert s.pending() is None
    assert s.known_ids() == []
    assert s.all_secrets() == []
    assert s.get("phone-0001") is None
    assert s.read_only is False
    assert not (tmp_path / "mobile_box.json").exists()


def test_open_pending_creates_a_valid_secret_and_returns_the_old_one(tmp_path):
    s = store(tmp_path)
    first, old = s.open_pending(NOW)
    assert old is None and BOX_SECRET_RE.fullmatch(first)
    assert s.pending() == first
    second, old = s.open_pending(NOW)
    assert old == first and second != first and BOX_SECRET_RE.fullmatch(second)
    assert store(tmp_path).pending() == second


def test_bind_moves_the_pending_secret_to_the_device(tmp_path):
    s = store(tmp_path)
    secret, _ = s.open_pending(NOW)
    assert s.bind("phone-0001") == (secret, None)
    assert s.pending() is None
    assert s.get("phone-0001") == secret
    again = store(tmp_path)
    assert again.get("phone-0001") == secret and again.pending() is None


def test_bind_without_pending_does_nothing(tmp_path, monkeypatch):
    writes = counting_writes(monkeypatch)
    s = store(tmp_path)
    assert s.bind("phone-0001") == (None, None)
    assert writes == []
    assert s.known_ids() == []


def test_bind_with_a_matching_expected_secret_binds(tmp_path):
    s = store(tmp_path)
    secret, _ = s.open_pending(NOW)
    assert s.bind("phone-0001", secret) == (secret, None)
    assert s.get("phone-0001") == secret and s.pending() is None


def test_bind_with_a_stale_expected_secret_does_nothing_and_keeps_the_pending_one(tmp_path, monkeypatch):
    s = store(tmp_path)
    old, _ = s.open_pending(NOW)
    new, _ = s.open_pending(NOW)
    writes = counting_writes(monkeypatch)
    assert s.bind("phone-0001", old) == (None, None)
    assert writes == []
    assert s.pending() == new and s.known_ids() == []


def test_bind_with_expected_but_no_pending_does_nothing(tmp_path, monkeypatch):
    s = store(tmp_path)
    writes = counting_writes(monkeypatch)
    assert s.bind("phone-0001", A) == (None, None)
    assert writes == [] and s.known_ids() == []


def test_bind_rejects_an_invalid_device_id_and_changes_nothing(tmp_path):
    s = store(tmp_path)
    secret, _ = s.open_pending(NOW)
    with pytest.raises(ValueError):
        s.bind("")
    assert s.pending() == secret and s.known_ids() == []


def test_bind_returns_the_replaced_secret_when_the_device_pairs_again(tmp_path):
    s = store(tmp_path)
    first, _ = s.open_pending(NOW)
    s.bind("phone-0001")
    second, _ = s.open_pending(NOW)
    assert s.bind("phone-0001") == (second, first)
    assert s.get("phone-0001") == second


def test_remove_and_retain_return_the_removed_secrets(tmp_path):
    s = store(tmp_path)
    a, _ = s.open_pending(NOW)
    s.bind("phone-0001")
    b, _ = s.open_pending(NOW)
    s.bind("phone-0002")
    c, _ = s.open_pending(NOW)
    s.bind("phone-0003")
    assert s.remove("phone-0001") == a
    assert s.remove("phone-0001") is None
    assert s.retain(["phone-0003", "phone-0009"]) == {"phone-0002": b}
    assert s.known_ids() == ["phone-0003"]
    assert store(tmp_path).known_ids() == ["phone-0003"]
    assert s.get("phone-0003") == c


def test_retain_and_remove_without_a_change_do_not_write(tmp_path, monkeypatch):
    s = store(tmp_path)
    s.open_pending(NOW)
    s.bind("phone-0001")
    writes = counting_writes(monkeypatch)
    assert s.retain(["phone-0001"]) == {}
    assert s.remove("nobody") is None
    assert writes == []


def test_clear_pending(tmp_path, monkeypatch):
    s = store(tmp_path)
    secret, _ = s.open_pending(NOW)
    assert s.clear_pending() == secret
    assert s.pending() is None and store(tmp_path).pending() is None
    writes = counting_writes(monkeypatch)
    assert s.clear_pending() is None
    assert writes == []


def test_all_secrets_lists_pending_first_then_devices_by_id(tmp_path):
    s = store(tmp_path)
    s.open_pending(NOW)
    s.bind("phone-0002")
    s.open_pending(NOW)
    s.bind("phone-0001")
    pending, _ = s.open_pending(NOW)
    got = s.all_secrets()
    assert got == [pending, s.get("phone-0001"), s.get("phone-0002")]


def test_all_secrets_has_no_duplicates(tmp_path):
    path = tmp_path / "mobile_box.json"
    path.write_text(json.dumps({"schema_version": 1, "pending": {"secret": A, "created_at": NOW},
                                "devices": {"phone-0001": {"secret": A}, "phone-0002": {"secret": B}}}),
                    encoding="utf-8")
    assert MobileBoxStore(str(path)).all_secrets() == [A, B]


def test_nothing_is_written_when_nothing_changes(tmp_path, monkeypatch):
    s = store(tmp_path)
    writes = counting_writes(monkeypatch)
    s.pending()
    s.get("x")
    s.known_ids()
    s.all_secrets()
    s.retain([])
    s.remove("x")
    s.clear_pending()
    s.bind("phone-0001")
    assert writes == []
    s.open_pending(NOW)
    assert len(writes) == 1


def test_the_file_is_written_through_write_secret_json_and_survives_a_reload(tmp_path, monkeypatch):
    calls = []
    real = secure_file.write_secret_json
    monkeypatch.setattr(mobile_box_store, "write_secret_json",
                        lambda *a, **k: (calls.append((a, k)), real(*a, **k))[1])
    s = store(tmp_path)
    secret, _ = s.open_pending(NOW)
    assert len(calls) == 1 and calls[0][1]["prefix"] == ".mobile_box-"
    data = json.loads((tmp_path / "mobile_box.json").read_text(encoding="utf-8"))
    assert data == {"schema_version": 1, "pending": {"secret": secret, "created_at": NOW}, "devices": {}}
    s.bind("phone-0001")
    data = json.loads((tmp_path / "mobile_box.json").read_text(encoding="utf-8"))
    assert data["pending"] is None and data["devices"] == {"phone-0001": {"secret": secret}}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-Rechte")
def test_the_file_is_private(tmp_path):
    store(tmp_path).open_pending(NOW)
    assert stat.S_IMODE(os.stat(tmp_path / "mobile_box.json").st_mode) == 0o600


def test_a_broken_file_is_quarantined_and_the_store_starts_empty(tmp_path):
    path = tmp_path / "mobile_box.json"
    path.write_text("{kaputt", encoding="utf-8")
    assert MobileBoxStore(str(path)).known_ids() == []
    assert list(tmp_path.glob("mobile_box.json.corrupt-*"))


def test_a_non_object_top_level_is_quarantined(tmp_path):
    path = tmp_path / "mobile_box.json"
    path.write_text("[1]", encoding="utf-8")
    s = MobileBoxStore(str(path))
    assert s.known_ids() == [] and s.read_only is False
    assert list(tmp_path.glob("mobile_box.json.corrupt-*"))


def test_an_unreadable_file_makes_the_store_read_only(tmp_path, monkeypatch):
    def boom(path):
        raise OSError("gesperrt")
    monkeypatch.setattr(mobile_box_store, "load_json_or_quarantine", boom)
    s = store(tmp_path)
    assert s.read_only is True
    with pytest.raises(MobileBoxReadOnly):
        s.open_pending(NOW)


def test_a_newer_schema_makes_the_store_read_only_and_never_overwrites(tmp_path):
    path = tmp_path / "mobile_box.json"
    text = json.dumps({"schema_version": 99, "pending": None, "devices": {"phone-0001": {"secret": A}}})
    path.write_text(text, encoding="utf-8")
    s = MobileBoxStore(str(path))
    assert s.read_only is True and s.known_ids() == []
    with pytest.raises(MobileBoxReadOnly):
        s.open_pending(NOW)
    with pytest.raises(MobileBoxReadOnly):
        s.bind("phone-0002")
    with pytest.raises(MobileBoxReadOnly):
        s.clear_pending()
    with pytest.raises(MobileBoxReadOnly):
        s.remove("phone-0001")
    with pytest.raises(MobileBoxReadOnly):
        s.retain([])
    assert s.pending() is None
    assert path.read_text(encoding="utf-8") == text


def test_invalid_secrets_in_the_file_are_dropped(tmp_path):
    path = tmp_path / "mobile_box.json"
    path.write_text(json.dumps({"schema_version": 1,
                                "pending": {"secret": "kurz", "created_at": NOW},
                                "devices": {"phone-0001": {"secret": A}, "phone-0002": {"secret": "x"},
                                            "phone-0003": "A", "": {"secret": B}, "phone-0004": {"secret": 5}}}),
                    encoding="utf-8")
    s = MobileBoxStore(str(path))
    assert s.pending() is None and s.known_ids() == ["phone-0001"]


@pytest.mark.parametrize("pending", [{"secret": A, "created_at": 5}, {"secret": A}, "A", [1], 7])
def test_a_malformed_pending_is_dropped(tmp_path, pending):
    path = tmp_path / "mobile_box.json"
    path.write_text(json.dumps({"schema_version": 1, "pending": pending, "devices": {}}), encoding="utf-8")
    assert MobileBoxStore(str(path)).pending() is None


def test_a_non_object_devices_section_is_ignored(tmp_path):
    path = tmp_path / "mobile_box.json"
    path.write_text(json.dumps({"schema_version": 1, "pending": None, "devices": [1]}), encoding="utf-8")
    assert MobileBoxStore(str(path)).known_ids() == []


def test_a_write_error_rolls_back_and_raises(tmp_path, monkeypatch):
    s = store(tmp_path)
    first, _ = s.open_pending(NOW)
    s.bind("phone-0001")
    second, _ = s.open_pending(NOW)
    monkeypatch.setattr(mobile_box_store, "write_secret_json",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("Platte voll")))
    with pytest.raises(OSError):
        s.open_pending(NOW)
    assert s.pending() == second
    with pytest.raises(OSError):
        s.bind("phone-0001")
    assert s.pending() == second and s.get("phone-0001") == first
    with pytest.raises(OSError):
        s.bind("phone-0002")
    assert s.pending() == second and s.known_ids() == ["phone-0001"]
    with pytest.raises(OSError):
        s.clear_pending()
    assert s.pending() == second
    with pytest.raises(OSError):
        s.remove("phone-0001")
    assert s.get("phone-0001") == first
    with pytest.raises(OSError):
        s.retain([])
    assert s.get("phone-0001") == first


def test_a_write_error_on_the_first_open_leaves_the_store_empty(tmp_path, monkeypatch):
    s = store(tmp_path)
    monkeypatch.setattr(mobile_box_store, "write_secret_json",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("Platte voll")))
    with pytest.raises(OSError):
        s.open_pending(NOW)
    assert s.pending() is None


def test_no_secret_reaches_the_log(tmp_path, caplog, monkeypatch):
    path = tmp_path / "mobile_box.json"
    path.write_text(json.dumps({"schema_version": 1, "pending": {"secret": A, "created_at": NOW},
                                "devices": {"phone-0001": {"secret": B}, "phone-0002": {"secret": "x" + B}}}),
                    encoding="utf-8")
    with caplog.at_level(logging.DEBUG):
        s = MobileBoxStore(str(path))
        new, old = s.open_pending(NOW)
        bound, replaced = s.bind("phone-0001")
        s.bind("phone-0003")
        s.remove("phone-0001")
        s.retain([])
        s.clear_pending()
        monkeypatch.setattr(mobile_box_store, "write_secret_json",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("Platte voll " + new)))
        with pytest.raises(OSError):
            s.open_pending(NOW)
    text = caplog.text + "".join(str(r.exc_text) for r in caplog.records)
    for secret in (A, B, new, old, bound, replaced):
        if secret:
            assert secret not in text
    assert "1 unbrauchbare" in caplog.text


def test_reads_never_wait_for_a_write_in_progress(tmp_path, monkeypatch):
    """Der Mobil-Tab liest im UI-Poll (`RelayService.states_by_device`); ein Schreibvorgang unter
    Windows läuft durch `icacls` und darf ihn nicht anhalten."""
    import threading
    s = store(tmp_path)
    s.open_pending(NOW)
    s.bind("phone-0001")
    inside, release = threading.Event(), threading.Event()
    real = secure_file.write_secret_json

    def slow(*args, **kwargs):
        inside.set()
        release.wait(5)
        return real(*args, **kwargs)

    monkeypatch.setattr(mobile_box_store, "write_secret_json", slow)
    writer = threading.Thread(target=lambda: s.open_pending(NOW), daemon=True)
    writer.start()
    assert inside.wait(5)
    seen = {}
    reader = threading.Thread(target=lambda: seen.update(
        ids=s.known_ids(), secret=s.get("phone-0001"), pending=s.pending(),
        every=s.all_secrets()), daemon=True)
    reader.start()
    reader.join(1)
    release.set()
    writer.join(5)
    assert not reader.is_alive(), "ein Lesezugriff wartet auf den Schreibvorgang"
    assert seen["ids"] == ["phone-0001"] and seen["pending"] is None   # Stand vor dem Schreiben


def test_reads_follow_every_committed_change_and_not_a_failed_one(tmp_path, monkeypatch):
    s = store(tmp_path)
    secret, _ = s.open_pending(NOW)
    assert s.pending() == secret
    s.bind("phone-0001")
    assert s.pending() is None and s.get("phone-0001") == secret
    monkeypatch.setattr(mobile_box_store, "write_secret_json",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("voll")))
    with pytest.raises(OSError):
        s.remove("phone-0001")
    assert s.known_ids() == ["phone-0001"]                  # gescheitert: Lesestand unverändert
    monkeypatch.undo()
    s.remove("phone-0001")
    assert s.known_ids() == [] and s.get("phone-0001") is None
