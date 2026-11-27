#!/usr/bin/env python3
"""Erzeugt alle Icon-Dateien aus `assets/app-icon.svg`.

    uv run --no-project --with resvg-py==0.5.0 --with Pillow==13.0.0 python scripts/app_icons.py

Schreibt `assets/app-icon.png` (512), `.ico`, `.icns`, `pwa/icons/` (192, 512, maskierbar 512)
und zuletzt die Prüfsummenliste `assets/app-icon.sha256sums` über SVG, Skript und Ausgaben. Nach
jeder Änderung an SVG oder Skript ausführen, die Tests rechnen die Liste nach. Der Renderer wird
nur hier gebraucht, nicht im Build.
"""
from __future__ import annotations

import hashlib
import io
import pathlib
import sys
import xml.etree.ElementTree as ET  # liest nur die eigene SVG aus dem Repo
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "app-icon.svg"
MANIFEST = ROOT / "assets" / "app-icon.sha256sums"
ASSETS = ROOT / "assets"
PWA = ROOT / "pwa" / "icons"
# Pfade relativ zu ROOT, wie sie in der Prüfsummenliste stehen.
TEXT_INPUTS = ("assets/app-icon.svg", "scripts/app_icons.py")
OUTPUTS = ("assets/app-icon.png", "assets/app-icon.ico", "assets/app-icon.icns",
           "pwa/icons/icon-192.png", "pwa/icons/icon-512.png", "pwa/icons/icon-maskable-512.png")
_TEXT_SUFFIXES = (".svg", ".py")

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
ICNS_SIZES = (32, 64, 128, 256, 512, 1024)   # Pillow schreibt nur Retina-Typen, kleinster 16@2x
APP_PNG_SIZE = 512
PWA_SIZES = (192, 512)
MASKABLE_SIZE = 512
# Android legt maskierbare Icons unter eine Maske, sicher sichtbar ist nur ein Kreis mit 80 %
# Durchmesser: das Motiv schrumpft auf 80 %, die Kachel wird zur randlosen Fläche (maskable_svg).
MASKABLE_SCALE = 0.8
SVG_NS = "http://www.w3.org/2000/svg"

INSTALL_HINT = (
    "resvg-py fehlt. Aufruf: uv run --no-project --with resvg-py==0.5.0 "
    "--with Pillow==13.0.0 python scripts/app_icons.py"
)


def file_digest(path: pathlib.Path) -> str:
    """SHA-256 einer Datei. Bei Text (SVG, Skript) zählen die Zeilenenden nicht, ein
    CRLF-Checkout ergibt denselben Wert; Bilder zählen Byte für Byte."""
    data = path.read_bytes()
    if path.suffix in _TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def render(svg_text: str, size: int) -> Image.Image:
    """Die SVG als RGBA-Bild in `size` × `size`, direkt in dieser Größe gerendert."""
    try:
        import resvg_py  # pyright: ignore[reportMissingImports]  # nur für dieses Skript installiert
    except ImportError:
        raise SystemExit(INSTALL_HINT) from None
    from PIL import Image

    png = resvg_py.svg_to_bytes(svg_string=svg_text, width=size, height=size)
    return Image.open(io.BytesIO(bytes(png))).convert("RGBA")


def maskable_svg(svg_text: str) -> str:
    """Die SVG des maskierbaren Icons: der Bildausschnitt wächst um den Kehrwert von
    `MASKABLE_SCALE` (das Motiv bleibt mittig), und das Rechteck `id="tile"` füllt ihn
    randlos. Eine Kachel vor einer Fläche zeigte sonst ihre Kante: ihr Verlauf ist oben
    heller als ihr Rand. Wirft `ValueError`, wenn das Rechteck fehlt."""
    ET.register_namespace("", SVG_NS)
    root = ET.fromstring(svg_text)
    tile = next((el for el in root.iter() if el.get("id") == "tile"), None)
    if tile is None:
        raise ValueError('app-icon.svg: Rechteck mit id="tile" fehlt')
    width = float(root.get("viewBox", "0 0 256 256").split()[2])
    size = width / MASKABLE_SCALE
    offset = -(size - width) / 2
    root.set("viewBox", f"{offset!r} {offset!r} {size!r} {size!r}")
    for key, value in (("x", offset), ("y", offset), ("width", size), ("height", size)):
        tile.set(key, repr(value))
    tile.attrib.pop("rx", None)
    return ET.tostring(root, encoding="unicode")


def main() -> None:
    svg = SOURCE.read_text(encoding="utf-8")

    render(svg, APP_PNG_SIZE).save(ASSETS / "app-icon.png", optimize=True)

    ico = [render(svg, n) for n in ICO_SIZES]
    ico[-1].save(ASSETS / "app-icon.ico", format="ICO",
                 sizes=[(n, n) for n in ICO_SIZES], append_images=ico[:-1])

    render(svg, ICNS_SIZES[-1]).save(ASSETS / "app-icon.icns", format="ICNS",
                                     append_images=[render(svg, n) for n in ICNS_SIZES[:-1]])

    PWA.mkdir(parents=True, exist_ok=True)
    for size in PWA_SIZES:
        render(svg, size).save(PWA / f"icon-{size}.png", optimize=True)
    render(maskable_svg(svg), MASKABLE_SIZE).save(PWA / "icon-maskable-512.png", optimize=True)

    # Zuletzt: ein abgebrochener Lauf hinterlässt keine Liste, die zu halben Dateien passt.
    lines = [f"{file_digest(ROOT / path)}  {path}\n" for path in (*TEXT_INPUTS, *OUTPUTS)]
    MANIFEST.write_text("".join(lines), encoding="utf-8", newline="\n")
    print(f"Icons aus {SOURCE.relative_to(ROOT)} erzeugt.", file=sys.stderr)


if __name__ == "__main__":
    main()
