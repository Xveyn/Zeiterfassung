"""Tests für den Schlüsselbund-Zugriff: Keyring-Pfad, Datei-Fallback,
Watchdog und die reine Zustandslogik persist_password.

`keyring` wird im Produktivcode lazy innerhalb der Funktionen importiert
(CI-Pflicht). Die Tests schieben deshalb ein Fake-Modul in sys.modules,
statt das echte Backend des Testrechners anzufassen — ein Test darf keine
Einträge im Windows-Anmeldeinformationsmanager hinterlassen.
"""

import sys
import threading
import types

import pytest

from src import keyring_store


class _FakeKeyring:
    def __init__(self, working=True, block=None):
        self.working = working
        self.block = block          # threading.Event: blockiert bis gesetzt
        self.store = {}

    def _guard(self):
        if self.block is not None:
            self.block.wait()
        if not self.working:
            raise RuntimeError("No recommended backend was available")

    def set_password(self, service, account, password):
        self._guard()
        self.store[(service, account)] = password

    def get_password(self, service, account):
        self._guard()
        return self.store.get((service, account))

    def delete_password(self, service, account):
        self._guard()
        del self.store[(service, account)]


@pytest.fixture
def fake_keyring(monkeypatch):
    def _install(working=True, block=None):
        fake = _FakeKeyring(working=working, block=block)
        module = types.ModuleType("keyring")
        module.set_password = fake.set_password
        module.get_password = fake.get_password
        module.delete_password = fake.delete_password
        monkeypatch.setitem(sys.modules, "keyring", module)
        return fake
    return _install


def _record(**over):
    base = {"id": "rec-1", "name": "Firma", "password_location": "keyring"}
    base.update(over)
    return base


# --- set_secret / get_secret / delete_secret -------------------------------

def test_set_secret_uses_keyring_when_available(fake_keyring):
    fake = fake_keyring()
    assert keyring_store.set_secret("rec-1", "geheim") == "keyring"
    assert fake.store[(keyring_store.SERVICE, "rec-1")] == "geheim"


def test_set_secret_falls_back_to_file_without_backend(fake_keyring):
    """Linux ohne Secret Service: das Feature muss trotzdem funktionieren."""
    fake_keyring(working=False)
    assert keyring_store.set_secret("rec-1", "geheim") == "file"


def test_set_secret_falls_back_when_keyring_is_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    assert keyring_store.set_secret("rec-1", "geheim") == "file"


def test_get_secret_reads_from_keyring(fake_keyring):
    fake_keyring()
    keyring_store.set_secret("rec-1", "geheim")
    assert keyring_store.get_secret(_record()) == "geheim"


def test_get_secret_reads_from_record_when_location_is_file(fake_keyring):
    """Beim Datei-Fallback wird der Schlüsselbund gar nicht erst gefragt."""
    fake_keyring(working=False)
    record = _record(password_location="file", password="geheim")
    assert keyring_store.get_secret(record) == "geheim"


def test_get_secret_returns_empty_string_when_nothing_is_stored(fake_keyring):
    fake_keyring()
    assert keyring_store.get_secret(_record(id="unbekannt")) == ""


def test_delete_secret_removes_the_entry(fake_keyring):
    """Ohne das bliebe das Secret nach dem Löschen des Kontos verwaist."""
    fake = fake_keyring()
    keyring_store.set_secret("rec-1", "geheim")
    keyring_store.delete_secret("rec-1")
    assert (keyring_store.SERVICE, "rec-1") not in fake.store


def test_delete_secret_is_quiet_when_nothing_is_stored(fake_keyring):
    fake_keyring()
    keyring_store.delete_secret("gibt-es-nicht")


# --- Watchdog --------------------------------------------------------------

def test_set_secret_gives_up_when_the_keyring_blocks(fake_keyring, monkeypatch):
    """Der eigentliche Grund für den Watchdog: auf Linux ruft
    keyring.get_preferred_collection() ein collection.unlock() OHNE Timeout.
    Blockiert das, kehrt der Worker nie zurück, BackgroundTaskRunner ruft
    on_done nie, und der Sende-Dialog steht dauerhaft auf „Sende…"."""
    gate = threading.Event()
    fake_keyring(block=gate)
    monkeypatch.setattr(keyring_store, "WATCHDOG_TIMEOUT", 0.05)
    try:
        assert keyring_store.set_secret("rec-1", "geheim") == "file"
    finally:
        gate.set()


def test_get_secret_gives_up_when_the_keyring_blocks(fake_keyring, monkeypatch):
    gate = threading.Event()
    fake_keyring(block=gate)
    monkeypatch.setattr(keyring_store, "WATCHDOG_TIMEOUT", 0.05)
    try:
        record = _record(password="notfall")
        assert keyring_store.get_secret(record) == "notfall"
    finally:
        gate.set()


def test_delete_secret_gives_up_when_the_keyring_blocks(fake_keyring, monkeypatch):
    gate = threading.Event()
    fake_keyring(block=gate)
    monkeypatch.setattr(keyring_store, "WATCHDOG_TIMEOUT", 0.05)
    try:
        keyring_store.delete_secret("rec-1")   # kehrt zurück, statt zu hängen
    finally:
        gate.set()


# --- persist_password ------------------------------------------------------

def test_persist_password_new_password_goes_to_the_keyring(fake_keyring):
    fake = fake_keyring()
    result = keyring_store.persist_password(_record(), "neu")
    assert result["password_location"] == "keyring"
    assert "password" not in result
    assert fake.store[(keyring_store.SERVICE, "rec-1")] == "neu"


def test_persist_password_new_password_falls_back_into_the_record(fake_keyring):
    fake_keyring(working=False)
    result = keyring_store.persist_password(_record(), "neu")
    assert result["password_location"] == "file"
    assert result["password"] == "neu"


def test_persist_password_empty_keeps_the_stored_file_password(fake_keyring):
    """Nur den Port geändert und gespeichert: das Passwort darf nicht
    verschwinden. Genau dieser Fall lebte vorher nur in einer Dialog-Closure
    und war durch nichts gedeckt."""
    fake_keyring(working=False)
    stored = _record(password_location="file", password="alt")
    result = keyring_store.persist_password(_record(), "", stored=stored)
    assert result["password_location"] == "file"
    assert result["password"] == "alt"


def test_persist_password_empty_keeps_the_keyring_location(fake_keyring):
    fake_keyring()
    stored = _record(password_location="keyring")
    result = keyring_store.persist_password(_record(), "", stored=stored)
    assert result["password_location"] == "keyring"
    assert "password" not in result


def test_persist_password_does_not_mutate_its_input(fake_keyring):
    fake_keyring()
    candidate = _record()
    keyring_store.persist_password(candidate, "neu")
    assert candidate == _record()
