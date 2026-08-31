"""Tests für den gerätelokalen SMTP-Kontenspeicher.

Spiegelt tests/test_webhook_store.py: Validierung, Quarantäne bei kaputter
Datei, Read-Only bei neuerer schema_version, Rollback bei Schreibfehlern,
Härtung auf der Temp-Datei.
"""

import json
import os
import threading

import pytest

from src import smtp_store
from src.smtp_store import SmtpStore, SmtpStoreReadOnly, validate_record


def _record(**overrides):
    base = {
        "id": "rec-1", "name": "Firma", "enabled": True,
        "host": "mail.example.com", "port": 587, "security": "starttls",
        "username": "user@example.com", "from_addr": "user@example.com",
        "recipient": "buchhaltung@example.com",
        "password_location": "keyring",
    }
    base.update(overrides)
    return base


# --- validate_record -------------------------------------------------------

def test_new_id_is_unique():
    assert smtp_store.new_id() != smtp_store.new_id()


def test_valid_record_passes():
    ok, msg = validate_record(_record(), [])
    assert ok, msg


@pytest.mark.parametrize("overrides,fragment", [
    ({"name": "   "}, "Namen"),
    ({"host": ""}, "Server"),
    ({"port": 0}, "Port"),
    ({"port": 70000}, "Port"),
    ({"port": "587"}, "Port"),
    ({"port": True}, "Port"),
    ({"security": "tls"}, "Verschlüsselung"),
    ({"from_addr": ""}, "Absenderadresse"),
    ({"recipient": ""}, "Empfängeradresse"),
])
def test_invalid_records_are_rejected(overrides, fragment):
    ok, msg = validate_record(_record(**overrides), [])
    assert not ok
    assert fragment in msg


def test_empty_username_is_allowed():
    """Interner Relay ohne Auth — Benutzer darf leer bleiben."""
    ok, msg = validate_record(_record(username=""), [])
    assert ok, msg


def test_record_without_password_key_passes_and_is_not_mentioned():
    """Bei aktivem Schlüsselbund steht das Passwort gar nicht im Datensatz.
    validate_record darf es deshalb weder fordern noch erwähnen — die Regel
    „bei gesetztem Benutzer ist ein Passwort Pflicht" gehört in den Dialog."""
    candidate = _record(username="user@example.com")
    assert "password" not in candidate
    ok, msg = validate_record(candidate, [])
    assert ok
    assert "asswort" not in msg


def test_duplicate_name_is_rejected():
    existing = [_record(id="rec-0", name="Firma")]
    ok, msg = validate_record(_record(id="rec-1", name="firma"), existing)
    assert not ok
    assert "bereits" in msg


def test_renaming_itself_is_allowed():
    existing = [_record(id="rec-1", name="Firma")]
    ok, msg = validate_record(_record(id="rec-1", name="Firma"), existing)
    assert ok, msg


@pytest.mark.parametrize("field", ["from_addr", "recipient"])
def test_control_chars_in_addresses_are_rejected(field):
    ok, msg = validate_record(_record(**{field: "a@b\r\nBcc: c@d"}), [])
    assert not ok
    assert "Steuerzeichen" in msg


# --- Persistenz ------------------------------------------------------------

def test_save_and_reload(tmp_path):
    path = str(tmp_path / "smtp.json")
    SmtpStore(path).save(_record())
    assert [r["name"] for r in SmtpStore(path).get_all()] == ["Firma"]


def test_save_replaces_by_id(tmp_path):
    store = SmtpStore(str(tmp_path / "smtp.json"))
    store.save(_record())
    store.save(_record(name="Neu"))
    assert [r["name"] for r in store.get_all()] == ["Neu"]


def test_enabled_filters_disabled_accounts(tmp_path):
    store = SmtpStore(str(tmp_path / "smtp.json"))
    store.save(_record(id="a", name="An", enabled=True))
    store.save(_record(id="b", name="Aus", enabled=False))
    assert [r["name"] for r in store.enabled()] == ["An"]


def test_get_all_returns_a_copy(tmp_path):
    store = SmtpStore(str(tmp_path / "smtp.json"))
    store.save(_record())
    store.get_all()[0]["name"] = "manipuliert"
    assert store.get_all()[0]["name"] == "Firma"


def test_delete_removes_the_account(tmp_path):
    store = SmtpStore(str(tmp_path / "smtp.json"))
    store.save(_record())
    store.delete("rec-1")
    assert store.get_all() == []


def test_store_does_not_know_the_keyring_at_all():
    """Der Store bleibt reine Dateipersistenz; das Secret raeumt der Aufrufer
    ab (tab_smtp._remove). Sonst faesst jeder Test, der delete ruft, den
    echten Credential Manager der Entwicklermaschine an — und blockiert auf
    Linux womoeglich."""
    assert not hasattr(smtp_store, "keyring_store")


def test_lock_can_be_injected(tmp_path):
    lock = threading.RLock()
    store = SmtpStore(str(tmp_path / "smtp.json"), lock=lock)
    store.save(_record())
    assert store.get_all()[0]["id"] == "rec-1"


def test_failed_write_rolls_back_the_in_memory_list(tmp_path, monkeypatch):
    """Sonst zeigt die Liste den Eintrag, auf Platte steht nichts, und
    auffallen wuerde es erst nach dem Neustart."""
    store = SmtpStore(str(tmp_path / "smtp.json"))
    store.save(_record())

    def boom():
        raise OSError("Platte voll")

    monkeypatch.setattr(store, "_save_to_disk", boom)
    with pytest.raises(OSError):
        store.save(_record(id="rec-2", name="Zweite"))
    assert [r["id"] for r in store.get_all()] == ["rec-1"]


def test_hardening_runs_on_the_temp_file(tmp_path, monkeypatch):
    """chmod und icacls muessen auf der TEMP-Datei laufen: sonst gaebe es ein
    Fenster, in dem smtp.json schon am Zielpfad steht, aber noch die
    geerbten Rechte traegt."""
    seen = []
    monkeypatch.setattr(smtp_store, "harden_windows_acl", seen.append)
    path = str(tmp_path / "smtp.json")
    SmtpStore(path).save(_record())
    assert seen
    assert seen[0] != path
    assert os.path.basename(seen[0]).startswith(".smtp-")


# --- Laden, Quarantäne, Read-Only ------------------------------------------

def test_corrupt_file_is_quarantined(tmp_path):
    path = tmp_path / "smtp.json"
    path.write_text("{kein json", encoding="utf-8")
    store = SmtpStore(str(path))
    assert store.get_all() == []
    assert not path.exists()
    assert any(p.name.startswith("smtp.json.corrupt-") for p in tmp_path.iterdir())


def test_newer_schema_version_is_read_only(tmp_path):
    path = tmp_path / "smtp.json"
    path.write_text(json.dumps(
        {"schema_version": smtp_store.SCHEMA_VERSION + 1, "accounts": []}),
        encoding="utf-8")
    store = SmtpStore(str(path))
    with pytest.raises(SmtpStoreReadOnly):
        store.save(_record())


def test_unreadable_file_is_not_quarantined(tmp_path, monkeypatch):
    """Ein kurzzeitig gesperrtes File (Virenscanner, Backup) ist kein
    defektes File — die Konfiguration samt Passwoertern darf nicht wegfliegen."""
    path = tmp_path / "smtp.json"
    path.write_text(json.dumps({"schema_version": 1, "accounts": []}),
                    encoding="utf-8")

    real_open = open

    def flaky_open(file, *args, **kwargs):
        if str(file) == str(path):
            raise OSError("gesperrt")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", flaky_open)
    store = SmtpStore(str(path))
    monkeypatch.undo()
    assert path.exists()
    with pytest.raises(SmtpStoreReadOnly):
        store.save(_record())


def test_malformed_record_is_skipped(tmp_path):
    path = tmp_path / "smtp.json"
    path.write_text(json.dumps({"schema_version": 1, "accounts": [
        _record(id="gut", name="Gut"),
        {"id": "kaputt"},
        "kein dict",
    ]}), encoding="utf-8")
    assert [r["id"] for r in SmtpStore(str(path)).get_all()] == ["gut"]


def test_record_with_unknown_security_is_skipped_on_load(tmp_path):
    """Der wichtigste Ladetest: validate_record laeuft beim Laden NIE, und
    smtp._open verbindet bei einem unbekannten Wert gar nicht erst. Ein
    solcher Datensatz darf deshalb erst gar nicht in der Ziel-Auswahl
    erscheinen — dasselbe Muster, das webhook_store fuer die URL faehrt."""
    path = tmp_path / "smtp.json"
    path.write_text(json.dumps({"schema_version": 1, "accounts": [
        _record(id="gut", name="Gut"),
        _record(id="boese", name="Boese", security="TLS"),
    ]}), encoding="utf-8")
    assert [r["id"] for r in SmtpStore(str(path)).get_all()] == ["gut"]


def test_saved_file_is_not_world_readable(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX-Modusbits gibt es unter Windows nicht; dort greift "
                    "harden_windows_acl (s. test_hardening_runs_on_the_temp_file)")
    path = str(tmp_path / "smtp.json")
    SmtpStore(path).save(_record())
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
