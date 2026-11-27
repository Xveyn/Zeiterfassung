#!/usr/bin/env python3
"""Erzeugt alle Icon-Dateien aus `assets/app-icon.svg`.

    uv run --no-project --with resvg-py==0.5.0 --with Pillow==13.0.0 python scripts/app_icons.py

Schreibt `assets/app-icon.png` (512), `.ico`, `.icns`, `pwa/icons/` (192, 512, maskierbar 512)
und zuletzt den Stempel `assets/app-icon.svg.sha256`. Nach jeder Änderung an der SVG ausführen,
die Tests prüfen den Stempel gegen die SVG. Der Renderer wird nur hier gebraucht, nicht im Build.
"""
from __future__ import annotations

import hashlib
import io
import pathlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "app-icon.svg"
STAMP = ROOT / "assets" / "app-icon.svg.sha256"
ASSETS = ROOT / "assets"
PWA = ROOT / "pwa" / "icons"

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
ICNS_SIZES = (16, 32, 64, 128, 256, 512, 1024)
APP_PNG_SIZE = 512
PWA_SIZES = (192, 512)
MASKABLE_SIZE = 512
# Android legt maskierbare Icons unter eine Maske, sicher sichtbar ist nur ein Kreis mit 80 %
# Durchmesser. Die Kachel auf 80 % hält den Kalender darin, die Fläche dahinter trägt die
# Randfarbe der Kachel, damit kein Rand sichtbar wird.
MASKABLE_SCALE = 0.8
MASKABLE_BACKGROUND = "#0e172b"

INSTALL_HINT = (
    "resvg-py fehlt. Aufruf: uv run --no-project --with resvg-py==0.5.0 "
    "--with Pillow==13.0.0 python scripts/app_icons.py"
)


def source_digest(svg_text: str) -> str:
    """SHA-256 der SVG; Zeilenenden zählen nicht, ein CRLF-Checkout ergibt denselben Wert."""
    return hashlib.sha256(svg_text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def render(svg_text: str, size: int) -> Image.Image:
    """Die SVG als RGBA-Bild in `size` × `size`, direkt in dieser Größe gerendert."""
    try:
        import resvg_py  # pyright: ignore[reportMissingImports]  # nur für dieses Skript installiert
    except ImportError:
        raise SystemExit(INSTALL_HINT) from None
    from PIL import Image

    png = resvg_py.svg_to_bytes(svg_string=svg_text, width=size, height=size)
    return Image.open(io.BytesIO(bytes(png))).convert("RGBA")


def _maskable(svg_text: str) -> Image.Image:
    from PIL import Image

    canvas = Image.new("RGBA", (MASKABLE_SIZE, MASKABLE_SIZE), MASKABLE_BACKGROUND)
    tile = render(svg_text, round(MASKABLE_SIZE * MASKABLE_SCALE))
    offset = (MASKABLE_SIZE - tile.width) // 2
    canvas.alpha_composite(tile, (offset, offset))
    return canvas


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
    _maskable(svg).save(PWA / "icon-maskable-512.png", optimize=True)

    # Zuletzt: ein abgebrochener Lauf hinterlässt keinen Stempel, der zu halben Dateien passt.
    STAMP.write_text(source_digest(svg) + "\n", encoding="utf-8")
    print(f"Icons aus {SOURCE.relative_to(ROOT)} erzeugt.", file=sys.stderr)


if __name__ == "__main__":
    main()
