#!/usr/bin/env python3
"""Erzeugt `pwa/test/fixtures/privacy-blocks.json`, den Gleichlauf der beiden Markdown-Parser der
Datenschutzhinweise (Desktop `src/privacy_doc.py`, Web-App `pwa/privacy-doc.js`).

    python scripts/privacy_fixtures.py

Die Datei enthält die Blöcke des echten `docs/datenschutz.md` (ab dem ersten Abschnitt, wie beide
Anzeigen) und einige Grenzfälle. Der Python-Test (`tests/test_privacy_doc.py`) hält sie gegen den Parser,
der Node-Test (`pwa/test/privacy-doc.test.js`) gegen das JavaScript. Nach einer Änderung an
`docs/datenschutz.md` neu erzeugen. Nicht Teil der App, nicht gebündelt.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import privacy_doc as pd  # noqa: E402

DOC = ROOT / "docs" / "datenschutz.md"
TARGET = ROOT / "pwa" / "test" / "fixtures" / "privacy-blocks.json"

CASES = [
    "# Titel\n\n> Zitat\n> zweite Zeile\n\nEinleitung.\n\n## 1. Abschnitt\n\nText mit **fett**, `code` und [Link](https://x.example/a).\n",
    "- eins\n  weiter\n  - unter\n    - ganz unten\n- zwei\n",
    "[x](javascript:alert(1)) [y](docs/a.md) [](https://x.example) **offen `offen [offen](\n",
    "| a | b |\n\n1. eins\n\n```\ncode\n```\n\n<b>x</b>\n",
    "a\n<!-- weg\nauch weg -->\n\nb\n",
    "a<<!-- x -->!-- y -->b\n",
    "kein Abschnitt, nur Text\n",
]


def build() -> dict:
    text = DOC.read_text(encoding="utf-8")
    return {
        "document": pd.sections_only(pd.parse_privacy_markdown(text)),
        "cases": [
            {"markdown": md, "blocks": pd.sections_only(pd.parse_privacy_markdown(md))} for md in CASES
        ],
    }


def main() -> None:
    TARGET.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"geschrieben: {TARGET}")


if __name__ == "__main__":
    main()
