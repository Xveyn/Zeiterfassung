# tests/test_single_instance.py
import os
import socket
import sys
import threading
import time

import pytest

from src.single_instance import _SECRET_LEN, _derive_port, acquire

def _wait_for_calls(calls, expected, timeout=3.0):
    """Wartet, bis der SHOW-Callback mindestens `expected`-mal lief."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(calls) >= expected:
            return True
        time.sleep(0.005)
    return len(calls) >= expected


@pytest.fixture
def fast_ack(monkeypatch):
    """Drückt `_ACK_TIMEOUT` für die Tests, deren Laufzeit an genau diesem
    Timeout hängt (Squatter antwortet nie, stiller Peer sendet nie, Handshake
    ohne Secret läuft ins serverseitige recv-Timeout).

    Geprüft wird dort *was bei Timeout passiert*, nicht *wie lange er dauert* —
    die Abdeckung bleibt also identisch. Das Modul liest die Konstante bei
    jedem Aufruf aus dem Modul-Namespace (`_handle_conn`, `_notify_primary`),
    deshalb greift das Monkeypatching auch im schon laufenden Accept-Thread.

    0,5 s statt noch kleiner: in denselben Tests muss ein *echter*
    Localhost-Roundtrip zuverlässig hineinpassen (der SHOW-Versuch in
    `test_silent_connection_does_not_wedge_listener`). Ein Loopback-Roundtrip
    liegt bei <1 ms, 0,5 s lässt also auch unter CI-Last reichlich Luft."""
    import src.single_instance as si
    monkeypatch.setattr(si, "_ACK_TIMEOUT", 0.5)


def test_derive_port_deterministic_and_in_range():
    p1 = _derive_port(r"C:\Users\a\Zeiterfassung")
    p2 = _derive_port(r"C:\Users\a\Zeiterfassung")
    assert p1 == p2
    assert 20000 <= p1 < 32000


def test_derive_port_differs_per_path():
    assert _derive_port("/home/a") != _derive_port("/home/b")


@pytest.mark.skipif(sys.platform != "win32", reason="normcase ist nur auf Windows case-/separator-normalisierend")
def test_derive_port_normalizes_case_and_separators():
    a = _derive_port(r"C:\Users\A\Zeiterfassung")
    b = _derive_port(r"c:/users/a/zeiterfassung")
    assert a == b


def test_first_acquire_is_primary_second_exits(tmp_path):
    base = str(tmp_path)
    g1 = acquire(base, show_requested=True)
    try:
        assert g1 is not None and g1.bound is True
        g2 = acquire(base, show_requested=True)
        assert g2 is None            # Geschwister erkannt → Aufrufer beendet sich
    finally:
        g1.release()


def test_show_fires_callback_ping_does_not(tmp_path):
    """SHOW holt das Fenster nach vorn, PING nicht.

    „PING feuert NICHT" wird über eine **Barriere** bewiesen statt über eine
    Wartezeit: `_accept_loop` behandelt Verbindungen sequenziell (`_handle_conn`
    läuft inline, nicht in einem Thread), ein danach abgeschicktes SHOW kommt
    also erst dran, wenn das PING fertig behandelt ist. Lief der Callback bis
    dahin genau zweimal — die beiden SHOWs —, hat das PING ihn nicht ausgelöst.

    Das ist stärker als das frühere `wait(timeout=…) is False`: keine
    Timing-Annahme, kein Sleep, und ein verspätet feuerndes PING fällt auf,
    statt durch ein zu kurzes Fenster zu rutschen."""
    base = str(tmp_path)
    g1 = acquire(base, show_requested=True)
    calls = []
    g1.serve(lambda: calls.append(1))
    try:
        assert acquire(base, show_requested=True) is None       # SHOW
        assert _wait_for_calls(calls, 1) is True

        assert acquire(base, show_requested=False) is None      # PING
        assert acquire(base, show_requested=True) is None       # Barriere-SHOW
        assert _wait_for_calls(calls, 2) is True
        assert len(calls) == 2       # das PING hat nicht gefeuert
    finally:
        g1.release()


def test_pending_show_before_serve_fires_on_serve(tmp_path):
    base = str(tmp_path)
    g1 = acquire(base, show_requested=True)
    try:
        assert acquire(base, show_requested=True) is None   # SHOW vor serve()
        fired = threading.Event()
        g1.serve(lambda: fired.set())                        # gepuffertes SHOW feuert nach
        assert fired.wait(timeout=3.0) is True
    finally:
        g1.release()


def test_silent_connection_does_not_wedge_listener(tmp_path, fast_ack):
    base = str(tmp_path)
    g1 = acquire(base, show_requested=True)
    fired = threading.Event()
    g1.serve(lambda: fired.set())
    try:
        # Ein Peer verbindet sich und hält die Verbindung offen, OHNE etwas zu senden.
        port = _derive_port(base)
        silent = socket.create_connection(("127.0.0.1", port), timeout=2.0)
        try:
            # Der Listener darf nicht dauerhaft wedgen: nach dem Timeout der stillen
            # Verbindung muss ein echtes SHOW wieder bestätigt werden. Der erste
            # Versuch überlappt zeitlich mit dem serverseitigen recv-Timeout-Fenster
            # der stillen Verbindung (beide nutzen _ACK_TIMEOUT und starten praktisch
            # gleichzeitig) und darf knapp scheitern — das ist ein Timing-Artefakt,
            # kein Bug. Ohne Fix (Accept-Loop wedgt für immer) würde dagegen JEDER
            # Versuch bis zum Ablauf des Deadline-Fensters scheitern.
            deadline = time.monotonic() + 10.0
            acked = False
            while not acked and time.monotonic() < deadline:
                acked = acquire(base, show_requested=True) is None
            assert acked is True
            assert fired.wait(timeout=3.0) is True
        finally:
            silent.close()
    finally:
        g1.release()


def test_foreign_occupant_yields_degraded_primary(tmp_path, fast_ack):
    base = str(tmp_path)
    port = _derive_port(base)
    squatter = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    squatter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    squatter.bind(("127.0.0.1", port))
    squatter.listen(1)
    try:
        g = acquire(base, show_requested=True)   # Port belegt, kein ZEIT-OK
        assert g is not None and g.bound is False  # degradiert, aber Start läuft
    finally:
        squatter.close()


def test_handshake_without_secret_is_rejected(tmp_path, fast_ack):
    """N9: Ein Client, der das instance-secret NICHT kennt (nur das Magic
    schickt), darf KEIN ZEIT-OK bekommen und den SHOW-Callback nicht auslösen."""
    base = str(tmp_path)
    g1 = acquire(base, show_requested=True)
    calls = []
    g1.serve(lambda: calls.append(1))
    try:
        port = _derive_port(base)
        with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
            sock.sendall(b"ZEIT-SHOW")          # Magic ohne Secret
            sock.settimeout(5.0)
            try:
                reply = sock.recv(16)
            except socket.timeout:
                reply = b""
        assert reply != b"ZEIT-OK"
        # Barriere (wie im PING-Test): ein legitimes SHOW muss danach genau
        # EINMAL gefeuert haben. Wäre der unauthentifizierte Versuch
        # durchgekommen, stünde hier 2.
        assert acquire(base, show_requested=True) is None
        assert _wait_for_calls(calls, 1) is True
        assert len(calls) == 1
    finally:
        g1.release()


def test_handshake_with_wrong_secret_is_rejected(tmp_path, fast_ack):
    """N9, der eigentliche Kern: ein Client mit FALSCHEM Secret bekommt kein
    ZEIT-OK und loest den SHOW-Callback nicht aus.

    Abgrenzung zum Test darueber: der schickt nur das Magic (9 Bytes) und
    landet damit schon im Short-Read-Zweig von `_recv_exactly` (liefert `b""`)
    — das Magic passt dann nie, die Verbindung wird verworfen, bevor
    Laengenpruefung oder `hmac.compare_digest` ueberhaupt greifen. Erst volle
    41 Bytes mit falschem Secret pruefen die Authentifizierung selbst.

    Ohne diesen Fall blieb die `compare_digest`-Zeile ungetestet: per
    Mutationstest verifiziert — sie durch `if False` zu ersetzen liess die
    komplette Datei gruen."""
    base = str(tmp_path)
    g1 = acquire(base, show_requested=True)
    calls = []
    g1.serve(lambda: calls.append(1))
    try:
        wrong = b"x" * _SECRET_LEN
        assert g1.secret is not None and wrong != g1.secret
        port = _derive_port(base)
        with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
            sock.sendall(b"ZEIT-SHOW" + wrong)   # volle Laenge, falsches Secret
            sock.settimeout(5.0)
            try:
                reply = sock.recv(16)
            except socket.timeout:
                reply = b""
        assert reply != b"ZEIT-OK"
        # Barriere wie oben: ein legitimes SHOW feuert danach genau EINMAL.
        assert acquire(base, show_requested=True) is None
        assert _wait_for_calls(calls, 1) is True
        assert len(calls) == 1
    finally:
        g1.release()


def test_secret_write_failure_yields_bound_unauth_guard(tmp_path, monkeypatch):
    """N9-Crash-Sicherheit: scheitert das Schreiben des Secrets hart, darf
    acquire() NICHT werfen — es liefert einen gebundenen Guard mit secret=None
    (unauthentifizierter Fallback), die App startet also weiter."""
    import src.single_instance as si

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(si, "_write_secret_atomic", _boom)
    base = str(tmp_path)
    g = acquire(base, show_requested=True)
    try:
        assert g is not None and g.bound is True
        assert g.secret is None
    finally:
        g.release()


def test_secret_file_acl_hardened_before_replace(tmp_path, monkeypatch):
    """Audit M8: das instance-secret ist unter Windows so schützenswert wie
    token.json — wer es liest, kann den SHOW/PING-Handshake fälschen. Gehärtet
    wird die Temp-Datei, bevor os.replace sie unter dem Zielnamen sichtbar
    macht."""
    import src.single_instance as si

    events = []
    monkeypatch.setattr(si, "harden_windows_acl",
                        lambda p: events.append(("harden", p)))
    real_replace = os.replace

    def tracking_replace(src_path, dst_path):
        events.append(("replace", src_path, dst_path))
        return real_replace(src_path, dst_path)

    monkeypatch.setattr(os, "replace", tracking_replace)
    path = str(tmp_path / "instance-secret")

    si._write_secret_atomic(path, b"s" * 32)

    assert [e[0] for e in events] == ["harden", "replace"]
    assert events[0][1].endswith(".tmp")
    with open(path, "rb") as f:
        assert f.read() == b"s" * 32
