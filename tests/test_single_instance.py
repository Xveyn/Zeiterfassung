# tests/test_single_instance.py
import socket
import sys
import threading

import pytest

from src.single_instance import _derive_port, acquire


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
    base = str(tmp_path)
    g1 = acquire(base, show_requested=True)
    fired = threading.Event()
    g1.serve(lambda: fired.set())
    try:
        # SHOW → Callback feuert
        assert acquire(base, show_requested=True) is None
        assert fired.wait(timeout=3.0) is True

        # PING → Callback feuert NICHT
        fired.clear()
        assert acquire(base, show_requested=False) is None
        assert fired.wait(timeout=1.0) is False
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


def test_foreign_occupant_yields_degraded_primary(tmp_path):
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
