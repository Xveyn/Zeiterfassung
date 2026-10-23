# tests/test_qr_fixtures.py
"""Drift-Wächter für die QR-Fixtures des PWA-Decoders (#326).

`pwa/test/fixtures/qr-matrices.json` stammt aus `scripts/qr_fixtures.py`. Der Node-Test
dekodiert diese Matrizen; stimmen sie nicht mehr mit dem überein, was der Desktop zeichnet
oder was `segno` heute erzeugt, prüft er den Decoder gegen etwas, das es nicht gibt."""
import importlib.util
import json
import pathlib

import pytest

from src import qr

pytest.importorskip("segno")

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "pwa" / "test" / "fixtures" / "qr-matrices.json"


def _load_script():
    spec = importlib.util.spec_from_file_location("qr_fixtures", ROOT / "scripts" / "qr_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_link_fixture_is_the_matrix_the_desktop_draws():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    link = data["link"]

    drawn = ["".join("1" if cell else "0" for cell in row) for row in qr.qr_matrix(link["text"])]

    assert link["rows"] == drawn
    assert link["version"] == 6
    assert len(link["text"]) == 93


def test_the_fixture_is_what_the_script_produces_today():
    # Ändert sich `segno` (oder das Skript), muss die Datei neu erzeugt werden:
    # `python scripts/qr_fixtures.py`.
    script = _load_script()
    expected = json.loads(json.dumps(script.build()))

    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == expected
