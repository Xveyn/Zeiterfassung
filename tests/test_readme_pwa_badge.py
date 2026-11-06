"""Das Badge der README liest die Kennung der Web-App live aus dem Manifest der veröffentlichten Seite.

Es hängt an drei Dingen, die woanders im Repo stehen: der Adresse der Seite (``pwa_constants``), dem Feld
``version`` im Manifest (``pwa_stamp`` ersetzt dort ``__BUILD__``) und der Form der Kennung ``N/X.Y.Z (sha)``.
Zieht eines davon um, würde das Badge still „invalid“ zeigen — dieser Test hält die Verbindung fest.
"""
from __future__ import annotations

import json
import pathlib
import re
import urllib.parse

from src.pwa_constants import PWA_URL

ROOT = pathlib.Path(__file__).resolve().parent.parent
BADGE = re.compile(r"!\[[^\]]*\]\((https://img\.shields\.io/badge/dynamic/json\?[^)\s]+)\)")


def _badge_params() -> dict[str, list[str]]:
    matches = BADGE.findall((ROOT / "README.md").read_text(encoding="utf-8"))
    assert len(matches) == 1, "die README braucht genau ein Badge für die Web-App-Kennung"
    return urllib.parse.parse_qs(urllib.parse.urlsplit(matches[0]).query)


def test_badge_reads_the_manifest_of_the_published_page() -> None:
    params = _badge_params()
    assert params["url"] == [PWA_URL + "manifest.webmanifest"]
    assert params["query"] == ["$.version"]


def test_manifest_carries_the_stamped_version_field() -> None:
    manifest = json.loads((ROOT / "pwa" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["version"] == "__BUILD__"          # scripts/pwa_stamp.py ersetzt genau diesen Platzhalter


def test_readme_explains_the_label_where_the_badge_stands() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    after = text[text.index("img.shields.io/badge/dynamic/json"):][:1500]
    assert "N/X.Y.Z" in after
    assert "Einstellungen → Updates" in after
