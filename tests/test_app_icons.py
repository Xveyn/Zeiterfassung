"""Die Icon-Dateien der App, erzeugt von `scripts/app_icons.py` aus `assets/app-icon.svg`.

Gelesen wird nur mit der stdlib: Pillow und der SVG-Renderer stehen nicht in den
Test-Abhängigkeiten. Das Skript liegt in `scripts/` (kein Package) und wird über
seinen Pfad geladen, wie in `test_build.py`.
"""

import importlib.util
import pathlib
import struct
import xml.etree.ElementTree as ET  # liest nur die eigene SVG aus dem Repo, keine Fremddaten
import zlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
PWA = ROOT / "pwa" / "icons"
SVG = ASSETS / "app-icon.svg"
STAMP = ASSETS / "app-icon.svg.sha256"

_spec = importlib.util.spec_from_file_location("_app_icons_script", ROOT / "scripts" / "app_icons.py")
app_icons = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app_icons)


def _png_chunks(data):
    """`(typ, inhalt)` je Chunk; PNG-Signatur sind die ersten acht Bytes."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        yield kind, data[pos + 8:pos + 8 + length]
        pos += 12 + length


def _png_info(path):
    """`(breite, höhe, bittiefe, farbtyp)` aus dem IHDR."""
    kind, ihdr = next(_png_chunks(path.read_bytes()))
    assert kind == b"IHDR"
    width, height, depth, color = struct.unpack(">IIBB", ihdr[:10])
    return width, height, depth, color


def _png_top_left_rgba(path):
    """Das Pixel (0, 0) eines 8-Bit-RGBA-PNG.

    Das erste Pixel der ersten Zeile steht bei jedem PNG-Filter unverändert in
    den Daten: links, oben und oben links gelten dort als 0. Byte 0 ist der
    Filtertyp der Zeile, die Bytes 1 bis 4 sind das Pixel.
    """
    data = path.read_bytes()
    assert _png_info(path)[2:] == (8, 6)
    raw = zlib.decompress(b"".join(body for kind, body in _png_chunks(data) if kind == b"IDAT"))
    return tuple(raw[1:5])


def _icns_types(data):
    """Die Chunk-Typen einer ICNS-Datei; jeder Chunk: 4 Byte Typ, 4 Byte Länge samt Kopf."""
    types, pos = set(), 8
    while pos < len(data):
        kind, length = struct.unpack(">4sI", data[pos:pos + 8])
        types.add(kind.decode("ascii"))
        pos += length
    return types


def test_svg_is_renderer_neutral():
    """Filter, Schrift und eingebettete Bilder rendert nicht jedes Programm gleich."""
    root = ET.parse(SVG).getroot()
    assert root.get("viewBox") == "0 0 256 256"
    tags = {el.tag.rsplit("}", 1)[-1] for el in root.iter()}
    assert not tags & {"filter", "text", "image", "foreignObject", "style"}


def test_source_digest_ignores_line_endings():
    """Ein Windows-Checkout mit CRLF darf den Stempel nicht ungültig machen."""
    assert app_icons.source_digest("a\r\nb\r\n") == app_icons.source_digest("a\nb\n")


def test_generated_files_match_svg():
    """Nach jeder Änderung an der SVG `scripts/app_icons.py` ausführen."""
    stamp = STAMP.read_text(encoding="utf-8").strip()
    assert stamp == app_icons.source_digest(SVG.read_text(encoding="utf-8"))


def test_app_png_is_512_rgba():
    assert _png_info(ASSETS / "app-icon.png") == (512, 512, 8, 6)


def test_ico_carries_every_size():
    data = (ASSETS / "app-icon.ico").read_bytes()
    _, kind, count = struct.unpack("<HHH", data[:6])
    sizes = sorted((data[6 + 16 * i] or 256) for i in range(count))
    assert kind == 1
    assert sizes == [16, 20, 24, 32, 40, 48, 64, 128, 256]


def test_icns_carries_retina_sizes():
    data = (ASSETS / "app-icon.icns").read_bytes()
    assert data[:4] == b"icns"
    assert struct.unpack(">I", data[4:8])[0] == len(data)
    assert {"ic07", "ic08", "ic09", "ic10", "ic11", "ic12", "ic13", "ic14"} <= _icns_types(data)


def test_maskable_icon_is_full_bleed():
    """Android schneidet maskierbare Icons beliebig zu: keine durchsichtige Ecke."""
    assert _png_top_left_rgba(PWA / "icon-maskable-512.png")[3] == 255


@pytest.mark.parametrize("name", ["icon-192.png", "icon-512.png"])
def test_pwa_icons_keep_transparent_corners(name):
    assert _png_top_left_rgba(PWA / name)[3] == 0
