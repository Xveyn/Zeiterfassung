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
MANIFEST = ASSETS / "app-icon.sha256sums"

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


def _manifest():
    """`{Pfad: SHA-256}` aus der Prüfsummenliste (Format von `sha256sum`)."""
    rows = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        digest, path = line.split("  ", 1)
        rows[path] = digest
    return rows


def test_manifest_lists_source_script_and_every_output():
    assert set(_manifest()) == {*app_icons.TEXT_INPUTS, *app_icons.OUTPUTS}


def test_generated_files_match_the_manifest():
    """Nach jeder Änderung an SVG oder Skript `scripts/app_icons.py` ausführen und alle
    erzeugten Dateien mit committen, auch die unter `pwa/icons/`."""
    stale = [path for path, digest in _manifest().items()
             if app_icons.file_digest(ROOT / path) != digest]
    assert stale == []


def test_file_digest_ignores_line_endings_of_text_inputs(tmp_path):
    """Ein Windows-Checkout mit CRLF darf die Liste nicht ungültig machen."""
    (tmp_path / "crlf.svg").write_bytes(b"a\r\nb\r\n")
    (tmp_path / "lf.svg").write_bytes(b"a\nb\n")
    assert app_icons.file_digest(tmp_path / "crlf.svg") == app_icons.file_digest(tmp_path / "lf.svg")


def test_file_digest_reads_images_as_bytes(tmp_path):
    (tmp_path / "crlf.png").write_bytes(b"a\r\n")
    (tmp_path / "lf.png").write_bytes(b"a\n")
    assert app_icons.file_digest(tmp_path / "crlf.png") != app_icons.file_digest(tmp_path / "lf.png")


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


def test_maskable_variant_fills_the_canvas_without_a_tile_edge():
    """Die Kachel ist oben heller als ihr Rand: auf einer Fläche dahinter bliebe ihre
    Kante sichtbar. Das maskierbare Icon tauscht sie gegen eine randlose Fläche."""
    root = ET.fromstring(app_icons.maskable_svg(SVG.read_text(encoding="utf-8")))
    x, y, w, h = (float(v) for v in root.get("viewBox").split())
    assert w == h == 256 / app_icons.MASKABLE_SCALE
    assert x == y == -(w - 256) / 2          # Motif mittig
    tile = next(el for el in root.iter() if el.get("id") == "tile")
    geometry = tuple(float(tile.get(k)) for k in ("x", "y", "width", "height"))
    assert geometry == (x, y, w, h)
    assert tile.get("rx") is None


def test_maskable_variant_needs_the_tile():
    with pytest.raises(ValueError):
        app_icons.maskable_svg('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"/>')


@pytest.mark.parametrize("name", ["icon-192.png", "icon-512.png"])
def test_pwa_icons_keep_transparent_corners(name):
    assert _png_top_left_rgba(PWA / name)[3] == 0
