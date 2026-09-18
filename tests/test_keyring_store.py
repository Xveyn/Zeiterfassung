"""Tests für den Schlüsselbund-Zugriff: Keyring-Pfad, Datei-Fallback,
Watchdog und die reine Zustandslogik persist_password.

`keyring` wird im Produktivcode lazy innerhalb der Funktionen importiert
(CI-Pflicht). Die Tests schieben deshalb ein Fake-Modul in sys.modules,
statt das echte Backend des Testrechners anzufassen — ein Test darf keine
Einträge im Windows-Anmeldeinformationsmanager hinterlassen.
"""

import logging
import sys
import threading

from src import keyring_store


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


def test_get_secret_returns_none_when_the_backend_is_unavailable_without_fallback(
        monkeypatch):
    """F1: `None` muss sich von einem tatsächlich leeren Passwort ("")
    unterscheiden lassen — sonst meldet sich der Aufrufer mit einem leeren
    Passwort beim Server an, statt das fehlende Secret zu melden."""
    monkeypatch.setitem(sys.modules, "keyring", None)
    assert keyring_store.get_secret(_record()) is None


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


def test_get_secret_signals_unavailable_on_timeout_without_fallback(
        fake_keyring, monkeypatch):
    """F1: ohne lokale Fallback-Kopie muss der Timeout-Fall als `None`
    erkennbar sein — die bisherige stille Degradierung auf "" ließ den
    Aufrufer sich mit einem leeren Passwort anmelden, der Server antwortete
    535, und der Nutzer suchte das Problem beim Passwort statt beim
    Schlüsselbund."""
    gate = threading.Event()
    fake_keyring(block=gate)
    monkeypatch.setattr(keyring_store, "WATCHDOG_TIMEOUT", 0.05)
    try:
        assert keyring_store.get_secret(_record()) is None
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


# --- Kein Record-Wert im Log ---------------------------------------------

def test_delete_secret_does_not_log_the_record_id(fake_keyring, caplog):
    """Die id stammt aus einem Record, der im Datei-Fallback das
    Klartext-Passwort traegt. Ein Feld aus so einem Dict gehoert nicht ins
    Log — `logs/zeiterfassung.log` ist ungehaertet und genau die Datei, die
    Nutzer bei Problemen anhaengen. Die Meldung bleibt ohne die id
    aussagekraeftig."""
    fake_keyring(working=False)
    with caplog.at_level(logging.DEBUG, logger="src.keyring_store"):
        keyring_store.delete_secret("rec-4711-abcdef")
    assert "rec-4711-abcdef" not in caplog.text


def test_delete_secret_timeout_does_not_log_the_record_id(
        fake_keyring, caplog, monkeypatch):
    """Derselbe Grund im Timeout-Zweig."""
    gate = threading.Event()
    fake_keyring(block=gate)
    monkeypatch.setattr(keyring_store, "WATCHDOG_TIMEOUT", 0.05)
    try:
        with caplog.at_level(logging.DEBUG, logger="src.keyring_store"):
            keyring_store.delete_secret("rec-4711-abcdef")
    finally:
        gate.set()
    assert "rec-4711-abcdef" not in caplog.text


# --- schlüsselbasiert: put / fetch / remove (#101) -------------------------


def _entry(key):
    return (keyring_store.service_for(key), key)


def test_service_is_per_entry():
    """Ein Service je Eintrag: WinVaultKeyring schichtet mehrere Nutzernamen
    unter EINEM Service per ungeschütztem Lesen-Ändern-Schreiben um."""
    assert keyring_store.service_for("webhook:w1") == "Zeiterfassung:webhook:w1"


def test_put_and_fetch_roundtrip(fake_keyring):
    fake = fake_keyring()
    assert keyring_store.put("google-oauth:abc", "1//refresh") is True
    assert fake.store[_entry("google-oauth:abc")] == "1//refresh"
    assert keyring_store.fetch("google-oauth:abc") == "1//refresh"


def test_smtp_entries_stay_under_the_plain_service(fake_keyring):
    fake = fake_keyring()
    keyring_store.set_secret("rec-1", "pw")
    keyring_store.put("webhook:w1", "tok")
    assert (keyring_store.SERVICE, "rec-1") in fake.store
    assert _entry("webhook:w1") in fake.store


def test_fetch_returns_empty_string_for_a_missing_entry(fake_keyring):
    fake_keyring()
    assert keyring_store.fetch("google-oauth:abc") == ""


def test_put_and_fetch_without_backend(fake_keyring):
    fake_keyring(working=False)
    assert keyring_store.put("k", "v") is False
    assert keyring_store.fetch("k") is None


def test_put_skips_an_unchanged_value(fake_keyring):
    """Nur bei Änderung schreiben: jeder Token-Refresh schriebe sonst neu
    (macOS: SecItemDelete+SecItemAdd, nicht atomar)."""
    fake = fake_keyring()
    keyring_store.put("k", "v")
    del fake.store[_entry("k")]           # „hinter dem Rücken" entfernt
    assert keyring_store.put("k", "v") is True
    assert _entry("k") not in fake.store  # gleicher Wert: nicht erneut geschrieben
    assert keyring_store.put("k", "w") is True
    assert fake.store[_entry("k")] == "w"


def test_put_and_fetch_give_up_when_the_keyring_blocks(fake_keyring, monkeypatch):
    import threading
    monkeypatch.setattr(keyring_store, "WATCHDOG_TIMEOUT", 0.05)
    release = threading.Event()
    fake_keyring(block=release)
    try:
        assert keyring_store.put("k", "v") is False
        assert keyring_store.fetch("k") is None
    finally:
        release.set()


def test_remove_deletes_and_is_quiet_when_missing(fake_keyring):
    fake = fake_keyring()
    keyring_store.put("k", "v")
    keyring_store.remove("k")
    assert _entry("k") not in fake.store
    keyring_store.remove("k")             # fehlt: kein Fehler
    assert keyring_store.put("k", "v") is True
    assert fake.store[_entry("k")] == "v"  # Cache nach remove geleert


def test_put_fetch_remove_never_log_key_or_value(fake_keyring, caplog):
    import logging
    fake_keyring(working=False)
    with caplog.at_level(logging.DEBUG, logger="src.keyring_store"):
        keyring_store.put("google-oauth:geheimer-schluessel", "1//geheim")
        keyring_store.fetch("google-oauth:geheimer-schluessel")
        keyring_store.remove("google-oauth:geheimer-schluessel")
    assert "geheimer-schluessel" not in caplog.text
    assert "1//geheim" not in caplog.text


def test_fetch_does_not_let_a_later_put_skip(fake_keyring):
    """fetch füllt den Cache nicht: sonst könnte ein veralteter Lesewert ein
    späteres put mit genau diesem Wert verschlucken."""
    fake = fake_keyring()
    fake.store[_entry("k")] = "v"
    assert keyring_store.fetch("k") == "v"
    del fake.store[_entry("k")]
    assert keyring_store.put("k", "v") is True
    assert fake.store[_entry("k")] == "v"


def test_concurrent_puts_leave_cache_and_backend_in_agreement(fake_keyring):
    import sys
    import threading
    fake = fake_keyring()
    module = sys.modules["keyring"]
    entered, release = threading.Event(), threading.Event()
    original = module.set_password

    def gated(service, account, password):
        if password == "vA":
            entered.set()
            release.wait(5)
        original(service, account, password)

    module.set_password = gated
    a = threading.Thread(target=keyring_store.put, args=("k", "vA"))
    a.start()
    assert entered.wait(5)
    b = threading.Thread(target=keyring_store.put, args=("k", "vB"))
    b.start()
    b.join(0.2)
    assert b.is_alive()                     # wartet auf den laufenden Schreibvorgang
    release.set()
    a.join(5)
    b.join(5)
    assert keyring_store._known["k"] == fake.store[_entry("k")] == "vB"


def _count_writes(monkeypatch):
    """Ersetzt set_password des Fake-Moduls durch eine mitschreibende Hülle."""
    import sys
    module = sys.modules["keyring"]
    original = module.set_password
    writes = []

    def counting(service, account, password):
        writes.append(account)
        original(service, account, password)

    monkeypatch.setattr(module, "set_password", counting)
    return writes


def test_put_does_not_rewrite_a_value_the_backend_already_holds(fake_keyring, monkeypatch):
    """W1: nach einem Neustart ist der Cache leer. Statt den unveränderten
    Wert neu zu schreiben (macOS: SecItemDelete + SecItemAdd), liest put ihn
    erst — gleicher Wert, kein Schreiben."""
    fake = fake_keyring()
    fake.store[_entry("k")] = "v"
    writes = _count_writes(monkeypatch)

    assert keyring_store.put("k", "v") is True
    assert writes == []
    assert keyring_store._known["k"] == "v"


def test_put_writes_when_the_backend_holds_another_value(fake_keyring, monkeypatch):
    fake = fake_keyring()
    fake.store[_entry("k")] = "alt"
    writes = _count_writes(monkeypatch)

    assert keyring_store.put("k", "neu") is True
    assert writes == ["k"]
    assert fake.store[_entry("k")] == "neu"


def test_put_still_writes_when_reading_fails(fake_keyring, monkeypatch):
    import sys
    fake = fake_keyring()

    def broken_read(service, account):
        raise RuntimeError("Lesen kaputt")

    monkeypatch.setattr(sys.modules["keyring"], "get_password", broken_read)

    assert keyring_store.put("k", "v") is True
    assert fake.store[_entry("k")] == "v"


def test_put_without_backend_logs_no_traceback(fake_keyring, caplog):
    """Ohne Schlüsselbund scheitert put bei JEDEM Start — ein Traceback pro
    Start wäre Rauschen im Log. Der Typ des Fehlers reicht."""
    import logging
    fake_keyring(working=False)
    with caplog.at_level(logging.DEBUG, logger="src.keyring_store"):
        assert keyring_store.put("k", "v") is False
    records = [r for r in caplog.records if r.name == "src.keyring_store"]
    assert records
    assert all(r.exc_info is None for r in records)
    assert "RuntimeError" in caplog.text


def test_put_gives_up_without_writing_when_the_read_hangs(fake_keyring, monkeypatch):
    """Hängt schon das Lesen, schreibt put nicht mehr hinterher — sonst
    kostete ein hängender Schlüsselbund pro Eintrag zweimal den Watchdog."""
    import sys
    import threading
    monkeypatch.setattr(keyring_store, "WATCHDOG_TIMEOUT", 0.05)
    fake_keyring()
    module = sys.modules["keyring"]
    release = threading.Event()
    writes = []
    module.get_password = lambda service, account: release.wait(5)
    module.set_password = lambda *a: writes.append(a)
    try:
        assert keyring_store.put("k", "v") is False
    finally:
        release.set()
    assert writes == []
