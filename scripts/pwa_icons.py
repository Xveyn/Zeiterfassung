#!/usr/bin/env python3
"""Erzeugt die PWA-Icons aus dem Markenbild `assets/margenheld-icon.png`.

    python scripts/pwa_icons.py

Schreibt nach `pwa/icons/`: `icon-192.png`, `icon-512.png` und `icon-maskable-512.png`
(Motiv auf 70 % der Fläche vor dem Theme-Hintergrund, damit die runde Maske nichts abschneidet).
Das Quellbild ist 300 × 297 Pixel groß: die 512er-Icons sind hochskaliert und etwas weich; ein
größeres Original ersetzt sie ohne Codeänderung. Nicht Teil der App, nicht gebündelt.
"""
from __future__ import annotations

import pathlib

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "margenheld-icon.png"
TARGET = ROOT / "pwa" / "icons"
BACKGROUND = (0x1A, 0x1A, 0x2E, 255)          # --bg der PWA und BG des Desktop-Themes


def _square(image: Image.Image, size: int) -> Image.Image:
    """Das Motiv, auf `size` × `size` skaliert (Seitenverhältnis bleibt, transparent aufgefüllt)."""
    ratio = min(size / image.width, size / image.height)
    scaled = image.resize((round(image.width * ratio), round(image.height * ratio)), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2), scaled)
    return canvas


def main() -> None:
    source = Image.open(SOURCE).convert("RGBA")
    TARGET.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        _square(source, size).save(TARGET / f"icon-{size}.png", optimize=True)
    maskable = Image.new("RGBA", (512, 512), BACKGROUND)
    motif = _square(source, round(512 * 0.7))
    maskable.paste(motif, ((512 - motif.width) // 2, (512 - motif.height) // 2), motif)
    maskable.save(TARGET / "icon-maskable-512.png", optimize=True)
    print(f"Icons nach {TARGET} geschrieben.")


if __name__ == "__main__":
    main()
