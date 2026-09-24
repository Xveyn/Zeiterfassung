# src/dpi.py
"""Systemskalierung unter Windows (#157): DPI-Awareness und Systemfaktor.

Ohne Awareness meldet Windows einem Prozess auf einem skalierten Display eine
verkleinerte Auflösung und streckt das fertige Fenster als Bitmap hoch — die
Größe stimmt, die Schrift ist unscharf. Mit Awareness zeichnet die App in der
echten Auflösung und muss selbst größer werden. Dafür gibt es schon einen
Hebel (`theme.fonts.init_fonts`, s. „UI-Skalierung" in CLAUDE.md); dieses
Modul liefert nur den Faktor, der zusätzlich hineingeht:

    init_fonts(root, systemfaktor × ui_scale)

`ui_scale` bleibt damit ein Faktor **obendrauf**. Bei 100 % folgt die App der
Windows-Einstellung, und wer heute einen eigenen Wert gesetzt hat, sieht die
App gleich groß wie vorher — Windows hat bisher dasselbe Produkt gestreckt.

**system-aware, nicht per-monitor.** Tk 8.6 reagiert nicht auf DPI-Wechsel
zwischen Bildschirmen; per-monitor-aware hätte das Fenster auf einem zweiten
Monitor mit anderer Skalierung die falsche Größe. System-aware streckt Windows
dort weiter, wie bisher.

**Nur Windows.** macOS löst Retina selbst (Tk rechnet dort in Punkten), und
auf Linux ist das Signal ein anderes (`Xft.dpi`, Xveyn#167). Außerhalb von
Windows ist jede Funktion hier ein No-op mit Faktor 1,0.

Die Win32-Aufrufe kommen als Default-Argumente herein, damit die Entscheidung
darum herum ohne Windows testbar ist (`tests/test_dpi.py`).
"""

from __future__ import annotations

import logging
import platform
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

# Bezugsauflösung von Windows bei 100 % Anzeigeskalierung.
BASE_DPI = 96

# Der Wert, den `init_system_scale` ermittelt hat — für den Hinweis im
# Einstellungen-Dialog. Modul-global wie `theme.fonts._scale`: er wird einmal
# beim Start gesetzt und ändert sich nur über einen Neustart.
_system_scale = 1.0


def scale_from_dpi(dpi: Optional[int]) -> float:
    """Systemfaktor aus der gemeldeten Auflösung: 144 dpi → 1,5.

    Ohne verwertbaren Wert 1,0 — keine Aussage heißt: nicht skalieren."""
    if not dpi or dpi <= 0:
        return 1.0
    return dpi / BASE_DPI


def _set_system_aware() -> bool:
    """Meldet den Prozess als system-aware an. True, wenn er es danach ist.

    Muss vor dem ersten Fenster laufen — danach lässt Windows die Awareness
    nicht mehr ändern."""
    import ctypes
    try:
        # PROCESS_SYSTEM_DPI_AWARE = 1 (shcore, ab Windows 8.1). Scheitert der
        # Aufruf, weil die Awareness schon gesetzt ist (E_ACCESSDENIED), sagt
        # die Abfrage darunter, ob sie reicht.
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        awareness = ctypes.c_int()
        ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(awareness))
        return awareness.value != 0
    except (AttributeError, OSError):
        # Kein shcore (vor Windows 8.1): der ältere Aufruf kennt nur
        # system-aware, genau das Gewünschte.
        return bool(ctypes.windll.user32.SetProcessDPIAware())


def _system_dpi() -> Optional[int]:
    """Die Systemauflösung (ab Windows 10 1607). Für einen nicht DPI-aware
    Prozess liefert Windows hier immer 96."""
    import ctypes
    return int(ctypes.windll.user32.GetDpiForSystem())


def init_system_scale(system: Optional[str] = None,
                      set_aware: Callable[[], bool] = _set_system_aware,
                      get_dpi: Callable[[], Optional[int]] = _system_dpi) -> float:
    """Schaltet unter Windows die DPI-Awareness ein und liefert den
    Systemfaktor; merkt ihn für `system_scale()`.

    Ohne gesetzte Awareness bleibt der Faktor 1,0: Windows streckt dann
    weiter selbst, ein zusätzlicher Faktor skalierte doppelt. Scheitert
    irgendetwas, startet die App wie bisher — unscharf ist der Status quo,
    ein verhinderter Start wäre eine Regression."""
    global _system_scale
    system = system or platform.system()
    if system != "Windows":
        return 1.0
    try:
        if not set_aware():
            log.info("DPI-Awareness nicht gesetzt — Windows skaliert selbst")
            return 1.0
        factor = scale_from_dpi(get_dpi())
    except Exception:
        log.warning("Systemskalierung nicht ermittelbar — Faktor 1,0",
                    exc_info=True)
        return 1.0
    _system_scale = factor
    log.info("Windows-Anzeigeskalierung: %d %%", round(factor * 100))
    return factor


def system_scale() -> float:
    """Der Faktor aus `init_system_scale` (1,0 davor und außerhalb Windows)."""
    return _system_scale


def pin_tk_scaling(root: Any, system: Optional[str] = None) -> None:
    """Setzt `tk scaling` unter Windows auf den 96-dpi-Wert zurück.

    In einem DPI-aware Prozess leitet Tk `tk scaling` aus der echten Auflösung
    ab und vergrößert damit jede Punkt-Schrift selbst — zusätzlich zu
    `init_fonts`, die App wäre doppelt skaliert. Festgenagelt bleibt
    `init_fonts` der eine Hebel. Nicht auf macOS: dort wirkt `tk scaling` auf
    Pixel- statt Punkt-Schriften, ein Festnageln veränderte die Größen."""
    if (system or platform.system()) != "Windows":
        return
    root.tk.call("tk", "scaling", BASE_DPI / 72)


def scale_hint(factor: float) -> Optional[str]:
    """Hinweiszeile für den Skalierungsregler — None bei 100 %."""
    if round(factor * 100) == 100:
        return None
    return (f"Die Windows-Anzeigeskalierung ({round(factor * 100)} %) wird "
            "automatisch berücksichtigt; der Wert hier gilt zusätzlich.")
