# tests/test_tray_mac.py
import platform
import threading

import pytest


def test_safe_swallows_callback_exceptions():
    """Klasse-(i)-Schutz: _safe lässt keine Python-Exception durch (läuft auf
    jeder Plattform — reines Python)."""
    from src.tray.mac import _safe
    calls = []
    _safe(lambda: calls.append("ok"))
    _safe(lambda: (_ for _ in ()).throw(ValueError("boom")))  # raises
    assert calls == ["ok"]  # zweiter Aufruf wirft NICHT durch


def test_backend_keeps_the_facade_constructor_signature():
    """Läuft auf JEDER Plattform: `__init__` ist reines Python, die AppKit-
    Importe liegen lazy in `_load_image`/`start`.

    Gegenstück zu `test_tray_linux.py::
    test_backend_keeps_the_facade_constructor_signature` — die Fassade
    instanziiert alle drei Backends gleich (`tray.TrayIcon.start`). Ohne diesen
    Test schlug die Umbenennung `base_path` → `resource_path` erst im
    macOS-CI-Job auf, weil der Smoke-Test darunter Darwin-gated ist und auf der
    Windows-Dev-Maschine übersprungen wird — obwohl der Konstruktor dort
    laufen KANN."""
    from src.tray.mac import MacTrayBackend
    # Bewusst als KEYWORD — genau so brach der Smoke-Test darunter. Positional
    # gebaut würde dieser Test eine Umbenennung des Parameters durchlassen
    # (nachgewiesen per Mutationsprobe), und damit den Fehler wieder erst im
    # macOS-Job sichtbar machen.
    backend = MacTrayBackend(resource_path="res", on_show=lambda: None,
                             on_quit=lambda: None, actions=[])
    assert backend.resource_path == "res"


@pytest.mark.skipif(
    platform.system() != "Darwin",
    reason="natives NSStatusItem nur auf macOS (im test-macos-Job)",
)
def test_native_backend_constructs_no_thread_and_tears_down():
    """In-Process-Smoke (nur macOS): Backend unter Tk-Root konstruieren, KEIN
    Thread, Menü gerendert, sauber abbauen. Skippt, wenn der Runner keinen
    Status-Bar-/Display-Zugriff hat (statt falsch rot)."""
    import tkinter
    from src.tray.mac import MacTrayBackend

    try:
        root = tkinter.Tk()
    except Exception:
        pytest.skip("kein Tk/Display auf dem Runner")
    root.withdraw()

    before = threading.active_count()
    backend = MacTrayBackend(
        resource_path=".",
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
