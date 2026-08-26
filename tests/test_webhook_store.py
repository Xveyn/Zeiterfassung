"""WebhookStore: gerätelokale, gehärtete Persistenz der Webhook-Liste."""

import json

import pytest

import src.webhook_store as whs
from src.webhook_store import WebhookStore, new_id, validate_record


def _record(**over):
    base = {
        "id": "id-1", "name": "Server", "url": "https://example.com/hook",
        "enabled": True, "payload": {"json": True, "pdf": False},
        "auth": {"mode": "none"},
    }
    base.update(over)
    return base


def _store(tmp_path):
    return WebhookStore(str(tmp_path / "webhooks.json"))


def test_starts_empty_without_file(tmp_path):
    assert _store(tmp_path).get_all() == []


def test_save_and_reload_round_trip(tmp_path):
    path = str(tmp_path / "webhooks.json")
    WebhookStore(path).save(_record())
    assert WebhookStore(path).get_all() == [_record()]


def test_save_replaces_by_id(tmp_path):
    store = _store(tmp_path)
    store.save(_record())
    store.save(_record(name="Neu"))
    assert [w["name"] for w in store.get_all()] == ["Neu"]


def test_delete_removes_only_the_named_one(tmp_path):
    store = _store(tmp_path)
    store.save(_record(id="a"))
    store.save(_record(id="b", name="B"))
    store.delete("a")
    assert [w["id"] for w in store.get_all()] == ["b"]


def test_enabled_skips_disabled(tmp_path):
    store = _store(tmp_path)
    store.save(_record(id="a"))
    store.save(_record(id="b", name="B", enabled=False))
    assert [w["id"] for w in store.enabled()] == ["a"]


def test_get_all_returns_deep_copies(tmp_path):
    """Flache Kopien reichen nicht — `auth` und `payload` sind verschachtelt."""
    store = _store(tmp_path)
    store.save(_record())
    got = store.get_all()[0]
    got["name"] = "mutiert"
    got["auth"]["mode"] = "hmac"
    got["payload"]["pdf"] = True
    fresh = store.get_all()[0]
    assert fresh["name"] == "Server"
    assert fresh["auth"]["mode"] == "none"
    assert fresh["payload"]["pdf"] is False


def test_unreadable_file_is_not_quarantined(tmp_path, monkeypatch):
    """Ein gesperrtes File ist kein defektes File: umbenennen hieße, eine
    intakte Konfiguration samt Secrets wegzuwerfen."""
    path = tmp_path / "webhooks.json"
    path.write_text(json.dumps({"schema_version": 1, "webhooks": []}),
                    encoding="utf-8")
    real_open = open

    def boom(file, *a, **k):
        if str(file) == str(path):
            raise PermissionError("gesperrt")
        return real_open(file, *a, **k)

    monkeypatch.setattr("builtins.open", boom)
    store = WebhookStore(str(path))
    assert store.get_all() == []
    assert path.exists()
    assert not list(tmp_path.glob("webhooks.json.corrupt-*"))


def test_unreadable_file_refuses_to_be_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "webhooks.json"
    path.write_text("{}", encoding="utf-8")
    real_open = open

    def boom(file, *a, **k):
        if str(file) == str(path):
            raise PermissionError("gesperrt")
        return real_open(file, *a, **k)

    monkeypatch.setattr("builtins.open", boom)
    store = WebhookStore(str(path))
    monkeypatch.undo()
    with pytest.raises(whs.WebhookStoreReadOnly):
        store.save(_record())


def test_failed_write_rolls_back_the_in_memory_list(tmp_path, monkeypatch):
    """Sonst zeigte die Liste einen Eintrag, den es auf Platte nie gab."""
    store = _store(tmp_path)
    store.save(_record(id="a"))
    monkeypatch.setattr(whs.WebhookStore, "_save_to_disk",
                        lambda self: (_ for _ in ()).throw(OSError("voll")))
    with pytest.raises(OSError):
        store.save(_record(id="b", name="B"))
    assert [w["id"] for w in store.get_all()] == ["a"]


def test_record_with_unsafe_url_is_skipped_on_load(tmp_path):
    """Sonst erschiene der Eintrag in der Ziel-Auswahl und scheiterte erst
    beim Senden."""
    path = tmp_path / "webhooks.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "webhooks": [_record(id="unsicher", url="http://erp.example.com/x"),
                     _record(id="gut")],
    }), encoding="utf-8")
    assert [w["id"] for w in WebhookStore(str(path)).get_all()] == ["gut"]


def test_corrupt_file_is_quarantined(tmp_path, caplog):
    path = tmp_path / "webhooks.json"
    path.write_text("{kaputt", encoding="utf-8")
    store = WebhookStore(str(path))
    assert store.get_all() == []
    assert list(tmp_path.glob("webhooks.json.corrupt-*"))
    assert not path.exists()


def test_invalid_record_is_skipped_rest_survives(tmp_path, caplog):
    path = tmp_path / "webhooks.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "webhooks": [
            {"id": "kaputt"},                       # Pflichtfelder fehlen
            _record(id="gut"),
        ],
    }), encoding="utf-8")
    store = WebhookStore(str(path))
    assert [w["id"] for w in store.get_all()] == ["gut"]


def test_newer_schema_version_is_left_alone(tmp_path):
    """Ein älterer Build darf eine neuere Datei nicht überschreiben."""
    path = tmp_path / "webhooks.json"
    original = json.dumps({"schema_version": 99, "webhooks": [_record()]})
    path.write_text(original, encoding="utf-8")
    store = WebhookStore(str(path))
    assert store.get_all() == []
    assert path.read_text(encoding="utf-8") == original
    # Der eigentliche Schutz: ein Speichervorgang darf die Datei nicht
    # anfassen — und muss das melden statt still zu verschlucken.
    with pytest.raises(whs.WebhookStoreReadOnly):
        store.save(_record())
    assert path.read_text(encoding="utf-8") == original


def test_hardening_runs_on_the_temp_file(tmp_path, monkeypatch):
    """Auf der Temp-Datei, VOR os.replace — sonst läge die Datei kurz mit
    geerbten Rechten am Zielpfad (Muster wie oauth_utils.write_token)."""
    hardened = []
    monkeypatch.setattr(whs, "harden_windows_acl", hardened.append)
    path = tmp_path / "webhooks.json"
    WebhookStore(str(path)).save(_record())
    assert hardened, "harden_windows_acl wurde nicht aufgerufen"
    assert hardened[0] != str(path)
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


def test_new_id_is_unique():
    assert new_id() != new_id()


def test_validate_record_requires_name():
    ok, msg = validate_record(_record(name="  "), [])
    assert ok is False
    assert msg


def test_validate_record_rejects_duplicate_name_case_insensitive():
    ok, msg = validate_record(_record(id="b", name="SERVER"), [_record(id="a")])
    assert ok is False
    assert msg


def test_validate_record_allows_renaming_itself():
    ok, _ = validate_record(_record(id="a", name="Server"), [_record(id="a")])
    assert ok is True


def test_validate_record_rejects_http_to_public_host():
    ok, msg = validate_record(_record(url="http://erp.example.com/x"), [])
    assert ok is False
    assert "https" in msg


def test_validate_record_requires_a_payload():
    ok, msg = validate_record(_record(payload={"json": False, "pdf": False}), [])
    assert ok is False
    assert msg


@pytest.mark.parametrize("auth", [
    {"mode": "header", "header": "Authorization", "value": ""},
    {"mode": "hmac", "header": "X-Sig", "prefix": "sha256=", "secret": ""},
])
def test_validate_record_requires_secret_for_auth_modes(auth):
    ok, msg = validate_record(_record(auth=auth), [])
    assert ok is False
    assert msg


def test_uses_the_injected_lock(tmp_path):
    """Die Signatur ist einheitlich mit den übrigen Stores (`lock=`-Parameter,
    Audit H1/H2) — ein injizierter Lock wird also übernommen. `main.py`
    injiziert ihn für `WebhookStore` aber bewusst NICHT: Webhooks nehmen an
    keinem Sync-Flow teil, es gibt also keine übergreifende Invariante mit den
    anderen Stores zu wahren (siehe src/CLAUDE.md, Webhook-Store-Absatz)."""
    import threading
    lock = threading.RLock()
    store = WebhookStore(str(tmp_path / "webhooks.json"), lock=lock)
    assert store._lock is lock


def test_creates_own_lock_without_injection(tmp_path):
    assert _store(tmp_path)._lock is not None
