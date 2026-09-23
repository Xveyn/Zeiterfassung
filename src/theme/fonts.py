# src/theme/fonts.py
"""Benannte App-Fonts und ihre Skalierung.

`init_fonts(root, scale)` legt die benannten Tk-Fonts an und MUSS vor dem
Aufbau der App-Widgets laufen (siehe `main.py::_apply_ui_scaling`) — die
Namen aus diesem Modul sind bis dahin nur Strings.
"""

import platform
import tkinter as tk
from tkinter import font as tkfont
from typing import Literal


_system = platform.system()
if _system == "Darwin":
    FONT_FAMILY = "Helvetica Neue"
elif _system == "Linux":
    FONT_FAMILY = "DejaVu Sans"
else:
    FONT_FAMILY = "Segoe UI"

# Fonts als Tk *named fonts*: Die FONT*-Konstanten sind die NAMEN der named
# fonts (keine Größen-Tupel). Alle Widgets binden font=FONT usw. als String; die
# tatsächliche, per UI-Faktor skalierte Größe steckt im named font, den init_fonts
# nach der Root-Erzeugung anlegt. So skaliert die UI plattformübergreifend über
# echte Punktgrößen statt über `tk scaling` — das skaliert auf macOS/Aqua die
# Punkt-Fonts NICHT (Ursache des macOS-Skalierungs-Bugs).
FONT = "AppFont"
FONT_SMALL = "AppFontSmall"
FONT_TINY = "AppFontTiny"
FONT_BOLD = "AppFontBold"
FONT_HEADER = "AppFontHeader"
FONT_HEADER_SMALL = "AppFontHeaderSmall"
FONT_FOOTER = "AppFontFooter"

# name → (Basis-Punktgröße, weight); die Größe wird in init_fonts × Faktor gesetzt.
_APP_FONTS: dict[str, tuple[int, Literal["normal", "bold"]]] = {
    FONT: (10, "normal"),
    FONT_SMALL: (8, "normal"),
    FONT_TINY: (7, "normal"),
    FONT_BOLD: (10, "bold"),
    FONT_HEADER: (16, "bold"),
    FONT_HEADER_SMALL: (12, "bold"),
    FONT_FOOTER: (12, "bold"),
}

# Standard-Tk-Fonts werden mitskaliert, damit Widgets ohne explizites font=…
# (Default-Font) ebenfalls mitziehen — Parität zum früheren `tk scaling`.
_STANDARD_FONTS = (
    "TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont",
    "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont",
    "TkIconFont", "TkTooltipFont",
)


def scaled_px(base, scale):
    """Skalierte Pixelangabe: `round(base × scale)`.

    Getrennt von `scaled_size`, obwohl beide runden: Font-Größen tragen auf
    manchen Plattformen ein Vorzeichen (negativ = Pixel statt Punkt), das dort
    erhalten bleiben muss. Eine Pixelangabe im Layout ist nie negativ — dafür
    darf hier eine 1-px-Trennlinie nicht auf 0 fallen und damit unsichtbar
    werden."""
    scaled = round(base * scale)
    if scaled == 0 and base > 0:
        return 1
    return scaled


def px(base):
    """`scaled_px` mit dem Faktor, den `init_fonts` gemerkt hat.

    Der Einstieg für jede Pixelangabe im Layout — Umbruchbreiten, Innenabstände
    von Buttons, feste Ausschnittshöhen. Ohne vorangegangenes `init_fonts`
    (Tk-freie Tests, Import-Zeit) gilt 1.0, die Konstante bleibt dann exakt der
    Wert, der im Quelltext steht.

    **Nicht zur Import-Zeit auswerten:** `init_fonts` läuft erst nach der
    Root-Erzeugung, eine Modul-Konstante `WRAP = px(380)` stünde also für immer
    auf dem unskalierten Wert. Der Aufruf gehört an die Stelle, an der das
    Widget gebaut wird."""
    return scaled_px(base, _scale)


def current_scale():
    """Der Faktor, den `init_fonts` gemerkt hat (1.0 davor).

    Für Tk-freie Logik, die den Faktor als Parameter nimmt, statt selbst aus
    `theme.fonts` zu ziehen (`form_logic.body_height`) — der Aufrufer reicht
    ihn hierüber durch, damit es dafür keinen zweiten Weg neben `px()` gibt."""
    return _scale


def scaled_size(base, scale):
    """Skalierte Font-Größe: round(base × scale). Betrag min. 1 (nie 0 =
    unsichtbar), Vorzeichen erhalten — Standard-Tk-Fonts tragen je nach Plattform
    negative (Pixel-)Größen."""
    scaled = round(base * scale)
    if scaled == 0:
        return -1 if base < 0 else 1
    return scaled


# Hält die erzeugten Font-Objekte prozessweit am Leben. ZWINGEND: ohne Referenz
# löscht der GC via tkinter.font.Font.__del__ den named font sofort wieder
# (`font delete`), und font=FONT wäre in den Widgets ein unbekannter Name.
_APP_FONT_OBJECTS = []

# Der zuletzt an `init_fonts` übergebene UI-Faktor — die Quelle für `px()`.
# Modul-global statt durchgereicht, weil die Skalierung prozessweit gilt: sie
# wird einmal beim Start gesetzt und ändert sich nur über einen Neustart
# (`ui.App.restart_for_scaling`).
_scale = 1.0


def init_fonts(root, scale):
    """Legt die App-named-fonts an (Basisgröße × scale) und skaliert die
    Standard-Tk-Fonts mit. MUSS nach der Root-Erzeugung und VOR dem Aufbau der
    App-Widgets laufen, damit measure_max_width die skalierten Fonts misst und die
    Fenstergeometrie korrekt pinnt. Ersetzt das frühere `tk scaling`, das auf
    macOS/Aqua wirkungslos war (skaliert dort die Punkt-Fonts nicht).

    Merkt den Faktor zusätzlich für `px()` — Schrift und Layout-Pixel hängen am
    selben Hebel, sonst wächst nur die eine Hälfte."""
    global _scale
    _scale = scale
    for name, (size, weight) in _APP_FONTS.items():
        _APP_FONT_OBJECTS.append(
            tkfont.Font(root=root, name=name, family=FONT_FAMILY,
                        size=scaled_size(size, scale), weight=weight))
    for name in _STANDARD_FONTS:
        try:
            f = tkfont.nametofont(name)
        except tk.TclError:
            continue  # nicht jede Plattform/Tk-Build kennt jeden Standard-Font
        f.configure(size=scaled_size(f.cget("size"), scale))
