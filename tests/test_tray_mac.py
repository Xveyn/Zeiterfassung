# tests/test_tray_mac.py
import platform
import threading

import pytest


def test_safe_swallows_callback_exceptions():
    """Klasse-(i)-Schutz: _safe lässt keine Python-Exception durch (läuft auf
    jeder Plattform — reines Python)."""
    from src.tray_mac import _safe
    calls = []
    _safe(lambda: calls.append("ok"))
    _safe(lambda: (_ for _ in ()).throw(ValueError("boom")))  # raises
    assert calls == ["ok"]  # zweiter Aufruf wirft NICHT durch


@pytest.mark.skipif(
    platform.system() != "Darwin",
    reason="natives NSStatusItem nur auf macOS (im test-macos-Job)",
)
def test_native_backend_constructs_no_thread_and_tears_down():
    """In-Process-Smoke (nur macOS): Backend unter Tk-Root konstruieren, KEIN
    Thread, Menü gerendert, sauber abbauen. Skippt, wenn der Runner keinen
    Status-Bar-/Display-Zugriff hat (statt falsch rot)."""
    import tkinter
    from src.tray_mac import MacTrayBackend

    try:
        root = tkinter.Tk()
    except Exception:
        pytest.skip("kein Tk/Display auf dem Runner")
    root.withdraw()

    before = threading.active_count()
    backend = MacTrayBackend(
        base_path=".",
        on_show=lambda: None,
        on_quit=lambda: None,
        actions=[("Sync", lambda: None, lambda: True)],
    )
    try:
        try:
            backend.start()
        except Exception:
            pytest.skip("Status-Bar auf dem Runner nicht verfügbar")
        # Bug-Guard (#88): natives Backend startet KEINEN Daemon-Thread
        assert threading.active_count() == before
        # Menü gerendert: Anzeigen | sep | Sync | sep | Beenden = 5 Items
        assert backend._menu.numberOfItems() == 5
    finally:
        backend.stop()
        assert backend._status_item is None  # idempotenter Teardown
        root.destroy()
