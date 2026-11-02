"""Tests fuer src/pwa_constants.py: die Adresse der gehosteten PWA, an einer Stelle."""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from src import mobile_relay_codec, mobile_routes, pwa_constants

ROOT = Path(__file__).resolve().parent.parent


def test_the_constants_have_the_documented_values():
    assert pwa_constants.PWA_ORIGIN == "https://xveyn.github.io"
    assert pwa_constants.PWA_URL == "https://xveyn.github.io/Zeiterfassung/"
    assert pwa_constants.PWA_URL.startswith(pwa_constants.PWA_ORIGIN)
    assert pwa_constants.PWA_URL.endswith("/")


def test_the_module_is_stdlib_only():
    tree = ast.parse((ROOT / "src" / "pwa_constants.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "typing"}, imported


def test_mobile_routes_and_the_codec_use_the_same_constants():
    assert mobile_routes.PWA_URL is pwa_constants.PWA_URL
    assert mobile_routes.PWA_ORIGIN is pwa_constants.PWA_ORIGIN
    assert mobile_relay_codec.PWA_URL is pwa_constants.PWA_URL


def test_the_codec_does_not_import_the_route_layer():
    code = ("import sys, src.mobile_relay_codec; "
            "sys.exit(1 if 'src.mobile_routes' in sys.modules else 0)")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
