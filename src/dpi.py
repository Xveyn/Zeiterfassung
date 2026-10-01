# src/dpi.py
"""Systemskalierung: DPI-Awareness unter Windows (#157), `Xft.dpi` unter
Linux (Xveyn#167) und der Systemfaktor daraus.

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

**Linux über `Xft.dpi`.** Tk 8.6 ignoriert unter X11 die Desktop-Skalierung
(`tk scaling`), die App erscheint dort nicht unscharf, sondern winzig.
Sein Schriftbackend rechnet allerdings selbst mit `Xft.dpi` —
`neutralize_xft_dpi` nimmt ihm das (Xveyn#199). `Xft.dpi` steht genau
dann über 96, wenn niemand sonst skaliert: wo der Compositor streckt (GNOME
Wayland, KDE „Skalierung durch das System"), bleibt es bei 96 und der Faktor
bei 1,0 — keine Doppelskalierung. Tk 9 wertet dieselbe Quelle selbst aus
(`tk::scalingPct`), deshalb gilt der Zweig nur unter Tk 8.

Gelesen wird über libX11 (`XResourceManagerString`), nicht über Tks
Ressourcen-Datenbank — die gleicht Einträge gegen den eigenen App-Namen ab,
`Xft.*` passt dort nie — und nicht über `xrdb`, das nicht überall
installiert ist.

**macOS bleibt außen vor:** es löst Retina selbst (Tk rechnet dort in
Punkten); jede Funktion hier ist dort ein No-op mit Faktor 1,0.

Die Plattform-Aufrufe kommen als Default-Argumente herein, damit die
Entscheidung darum herum ohne Windows und ohne X testbar ist
(`tests/test_dpi.py`).
"""

from __future__ import annotations

import atexit
import logging
import os
import platform
import tempfile
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

# Bezugsauflösung von Windows bei 100 % Anzeigeskalierung.
BASE_DPI = 96

# Der Wert, den `init_system_scale` ermittelt hat — für den Hinweis im
# Einstellungen-Dialog. Modul-global wie `theme.fonts._scale`: er wird einmal
# beim Start gesetzt und ändert sich nur über einen Neustart.
_system_scale = 1.0

# Ob `init_system_scale` unter Linux ein `Xft.dpi` gefunden hat — nur dann
# nagelt `pin_tk_scaling` dort `tk scaling` fest (s. dort).
_xft_found = False

# Gerätelokaler Settings-Key: die einmalige Umrechnung von `ui_scale` beim
# ersten Start mit Linux-Erkennung ist gelaufen (s. `migrate_ui_scale`).
MIGRATED_KEY = "linux_system_scale_migrated"


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


def xft_dpi_from_resources(text: Optional[str]) -> Optional[float]:
    """Der Wert von `Xft.dpi` aus dem Text der X-Ressourcen-Datenbank.

    Nur der exakte Eintrag zählt, keine Wildcards wie `*.dpi`. Ohne
    verwertbaren (positiven, numerischen) Wert None."""
    for line in (text or "").splitlines():
        name, sep, value = line.partition(":")
        if not sep or name.strip() != "Xft.dpi":
            continue
        try:
            dpi = float(value.strip())
        except ValueError:
            return None
        return dpi if dpi > 0 else None
    return None


def _xft_dpi() -> Optional[float]:
    """`Xft.dpi` des laufenden X-Servers über libX11 — ohne Tk, damit es vor
    der Root-Erzeugung läuft. Kein Display: None; fehlt libX11, wirft
    `CDLL` einen OSError, den `init_system_scale` loggt."""
    import ctypes
    import ctypes.util
    # find_library braucht ldconfig im PATH, das auf manchen Distributionen
    # nur unter /sbin liegt — der feste SONAME trägt dann trotzdem.
    x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XResourceManagerString.restype = ctypes.c_char_p
    x11.XResourceManagerString.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = x11.XOpenDisplay(None)
    if not display:
        return None
    try:
        raw = x11.XResourceManagerString(display)
        return xft_dpi_from_resources(raw.decode("utf-8", "replace") if raw else None)
    finally:
        x11.XCloseDisplay(display)


def _init_linux_scale(get_xft_dpi: Callable[[], Optional[float]],
                      tk_version: Optional[float]) -> float:
    global _system_scale, _xft_found
    _xft_found = False
    # Tk 9 skaliert selbst über Xft.dpi; ohne bekannte Version lieber gar
    # nicht als womöglich doppelt. Die Version reicht main.py herein — dieses
    # Modul bleibt Tk-frei (tests/test_type_annotations.py).
    if tk_version is None or tk_version >= 9:
        return 1.0
    try:
        xft = get_xft_dpi()
    except Exception:
        log.warning("Xft.dpi nicht lesbar — Faktor 1,0", exc_info=True)
        return 1.0
    if xft is None:
        log.info("Kein Xft.dpi gefunden — Desktop-Skalierung bleibt außen vor")
        return 1.0
    _xft_found = True
    # Nie kleiner als bisher: ein Xft.dpi unter 96 (etwa 90) verkleinerte
    # die App gegenüber dem Stand vor Xveyn#167.
    factor = max(1.0, xft / BASE_DPI)
    _system_scale = factor
    log.info("Xft.dpi %s → Systemskalierung %d %%", xft, round(factor * 100))
    return factor


def init_system_scale(system: Optional[str] = None,
                      set_aware: Callable[[], bool] = _set_system_aware,
                      get_dpi: Callable[[], Optional[int]] = _system_dpi,
                      get_xft_dpi: Callable[[], Optional[float]] = _xft_dpi,
                      tk_version: Optional[float] = None) -> float:
    """Ermittelt den Systemfaktor und merkt ihn für `system_scale()`.

    Windows: schaltet die DPI-Awareness ein. Ohne gesetzte Awareness bleibt
    der Faktor 1,0 — Windows streckt dann weiter selbst, ein zusätzlicher
    Faktor skalierte doppelt. Linux: `Xft.dpi / 96`, nur unter Tk 8.

    Scheitert irgendetwas, startet die App wie bisher — der Status quo ist
    unscharf bzw. klein, ein verhinderter Start wäre eine Regression."""
    global _system_scale
    system = system or platform.system()
    if system == "Linux":
        return _init_linux_scale(get_xft_dpi, tk_version)
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
    """Der Faktor aus `init_system_scale` (1,0 davor und unter macOS)."""
    return _system_scale


def neutralize_xft_dpi(system: Optional[str] = None,
                       directory: Optional[str] = None) -> Optional[str]:
    """Lässt Tk `Xft.dpi` nur in **diesem Prozess** als 96 sehen (Xveyn#199).

    Tks Xft-Schriftbackend rechnet unter X11 selbst mit `Xft.dpi` — auch
    Pixelgrößen, `tk scaling` ändert daran nichts (gemessen: 10 pt = 17 px bei
    96, 39 px bei 240). Geht der Systemfaktor zusätzlich in `init_fonts`, ist
    die Schrift doppelt skaliert (bei 250 %: 2,5 × 2,5), das Layout nur
    einmal, und der Regler kommt nie unter den Systemfaktor × 75 %. So bleibt
    `init_fonts` der eine Hebel.

    Xlib legt die Datei aus `XENVIRONMENT` über die Ressourcen des Servers;
    Xft liest `Xft.dpi` darüber. Muss vor der Root-Erzeugung laufen. Eine
    schon gesetzte `XENVIRONMENT`-Datei bleibt erhalten, unsere Zeile steht
    dahinter. Nur unter Linux und nur, wenn `init_system_scale` ein `Xft.dpi`
    gefunden hat. Liefert den Pfad der Datei, sonst None; scheitert das
    Schreiben, startet die App wie bisher."""
    if (system or platform.system()) != "Linux" or not _xft_found:
        return None
    lines = []
    old = os.environ.get("XENVIRONMENT")
    try:
        if old:
            try:
                with open(old, encoding="utf-8", errors="replace") as f:
                    lines = f.read().splitlines()
            except OSError:
                log.debug("XENVIRONMENT %s nicht lesbar — wird ersetzt", old,
                          exc_info=True)
        lines.append(f"Xft.dpi: {BASE_DPI}")
        fd, path = tempfile.mkstemp(prefix="zeiterfassung-xres-",
                                    dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        log.warning("Xft.dpi lässt sich für Tk nicht neutralisieren — "
                    "Schrift womöglich doppelt skaliert", exc_info=True)
        return None
    os.environ["XENVIRONMENT"] = path
    # Nur die eigene Datei räumen wir weg; ein Neustart-Kind erbt die
    # Variable, Xlib ignoriert eine fehlende Datei und es legt sich eine neue an.
    atexit.register(_remove_quietly, path)
    log.info("Xft.dpi für Tk auf %d gesetzt (Faktor kommt aus init_fonts)",
             BASE_DPI)
    return path


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        log.debug("Ressourcen-Datei %s nicht entfernt", path, exc_info=True)


def pin_tk_scaling(root: Any, system: Optional[str] = None) -> None:
    """Setzt `tk scaling` auf den 96-dpi-Wert zurück — unter Windows immer,
    unter Linux, sobald ein `Xft.dpi` gefunden wurde.

    Windows: in einem DPI-aware Prozess leitet Tk `tk scaling` aus der echten
    Auflösung ab und vergrößert damit jede Punkt-Schrift selbst — zusätzlich
    zu `init_fonts`, die App wäre doppelt skaliert. Linux: Tk leitet den Wert
    aus den Bildschirmmaßen ab, die der X-Server meldet; mit `Xft.dpi` ist die
    Desktop-Angabe maßgeblich, die Maße dürfen die Schrift nicht ein zweites
    Mal verändern. Festgenagelt bleibt `init_fonts` der eine Hebel.

    Nicht auf macOS: dort wirkt `tk scaling` auf Pixel- statt
    Punkt-Schriften, ein Festnageln veränderte die Größen."""
    system = system or platform.system()
    if system == "Windows" or (system == "Linux" and _xft_found):
        root.tk.call("tk", "scaling", BASE_DPI / 72)


def migrated_ui_scale(value: Any, factor: float) -> float:
    """`ui_scale` nach Abzug des Systemfaktors, auf dem Raster des Reglers
    (25 %) und in dessen Grenzen: 150 % bei Faktor 1,5 → 100 %.

    Nur Werte über 100 % werden umgerechnet — nur sie waren ein Ausgleich
    für die winzige App. 100 % heißt „nie eingestellt" und bekommt ab jetzt
    die Systemskalierung; wer verkleinert hat, bleibt dabei."""
    from src.settings import clamp_ui_scale
    f = clamp_ui_scale(value)
    if f <= 1.0:
        return f
    return clamp_ui_scale(round(f / factor * 4) / 4)


def migrate_ui_scale(settings: Any, system: Optional[str] = None) -> None:
    """Rechnet `ui_scale` einmalig um, sobald unter Linux ein `Xft.dpi`
    gefunden wurde (Xveyn#167).

    Wer die winzige App bisher über `ui_scale` ausgeglichen hat, sähe sie mit
    dem Systemfaktor obendrauf doppelt vergrößert. Unter Windows stellt sich
    die Frage nicht: dort hat das System dasselbe Produkt bisher gestreckt.
    Der Marker wird auch ohne Umrechnung gesetzt — ein später bewusst
    gewählter Wert wird nie nachträglich geteilt. Läuft nach
    `init_system_scale`."""
    if (system or platform.system()) != "Linux" or not _xft_found:
        return
    if settings.get(MIGRATED_KEY):
        return
    old = settings.get("ui_scale")
    new = migrated_ui_scale(old, _system_scale)
    settings.set_many({"ui_scale": new, MIGRATED_KEY: True})
    if new != old:
        log.info("ui_scale einmalig umgerechnet: %s → %s (Systemfaktor %s)",
                 old, new, _system_scale)


def scale_hint(factor: float) -> Optional[str]:
    """Hinweiszeile für den Skalierungsregler — None bei 100 %."""
    if round(factor * 100) == 100:
        return None
    return (f"Die Anzeigeskalierung des Systems ({round(factor * 100)} %) wird "
            "automatisch berücksichtigt; der Wert hier gilt zusätzlich.")
