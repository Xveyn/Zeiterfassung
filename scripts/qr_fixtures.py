#!/usr/bin/env python3
"""Erzeugt die Referenz-Matrizen für den QR-Decoder der Handy-PWA (#326).

    python scripts/qr_fixtures.py

Schreibt `pwa/test/fixtures/qr-matrices.json`. Die Matrizen stammen aus `segno`, dem
Encoder des Desktops — die Ground Truth ist also nicht von Hand gerechnet. Der Node-Test
`pwa/test/qr-decode.test.js` liest die Datei, `tests/test_qr_fixtures.py` hält sie gegen
`src.qr.qr_matrix` und gegen die installierte `segno`-Version zusammen.

Nicht Teil der App, nicht gebündelt. Die Ausgabe ist deterministisch (fester Zufallsstart):
ein erneuter Lauf ändert die Datei nur, wenn sich `segno` ändert.
"""
from __future__ import annotations

import json
import pathlib
import random

import segno
import segno.consts as consts

ROOT = pathlib.Path(__file__).resolve().parent.parent

TARGET = ROOT / "pwa" / "test" / "fixtures" / "qr-matrices.json"

# Die Pairing-Link-Form (`mobile_service.pair_link`) mit einem Dummy-Code: 28 Zeichen
# aus dem Alphabet des Kopplungscodes, keine echte Adresse und kein echter Code.
PWA_URL = "https://xveyn.github.io/Zeiterfassung/"
LINK = PWA_URL + "#pair=192.168.178.20:17654:" + "K7M29QXAK7M29QXAK7M29QXAK7M2"

EC_NAMES = {"L": consts.ERROR_LEVEL_L, "M": consts.ERROR_LEVEL_M,
            "Q": consts.ERROR_LEVEL_Q, "H": consts.ERROR_LEVEL_H}
PRINTABLE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,:;#/?=&-_~!"


def _byte_capacity(version: int, ec: str) -> int:
    """Zeichen, die im Byte-Modus gerade noch passen: Datenbits ohne Modus (4) und Zähler."""
    count_bits = 8 if version < 10 else 16
    return (consts.SYMBOL_CAPACITY[version][EC_NAMES[ec]] - 4 - count_bits) // 8


def _rows(code: segno.QRCode) -> list[str]:
    return ["".join("1" if cell else "0" for cell in row) for row in code.matrix]


def _make(text: str, version: int, ec: str, mask: int | None) -> segno.QRCode:
    return segno.make(text, version=version, error=ec, mask=mask, mode="byte",
                      micro=False, boost_error=False)


def _text(rng: random.Random, length: int) -> str:
    return "".join(rng.choice(PRINTABLE) for _ in range(length))


def _case(name: str, text: str, version: int, ec: str, mask: int | None) -> dict:
    code = _make(text, version, ec, mask)
    return {"name": name, "text": text, "version": version, "ec": ec,
            "mask": code.mask, "rows": _rows(code)}


def build() -> dict:
    rng = random.Random(326)
    cases = []
    for version in range(1, 11):
        for index, ec in enumerate(EC_NAMES):
            capacity = _byte_capacity(version, ec)
            text = _text(rng, max(1, capacity * 7 // 10))
            # Die Maske wandert mit Version und Stufe, damit alle acht vorkommen.
            cases.append(_case(f"v{version}-{ec}", text, version, ec, (version + index) % 8))
    for mask in range(8):
        cases.append(_case(f"v6-M-mask{mask}", LINK, 6, "M", mask))
    for version in range(1, 11):
        capacity = _byte_capacity(version, "L")
        cases.append(_case(f"v{version}-L-full", _text(rng, capacity), version, "L", None))

    # Wie `src.qr.qr_matrix`: dieselben Argumente, damit es die Matrix ist, die der Dialog zeichnet
    # (`tests/test_qr_fixtures.py` hält beides zusammen).
    link_code = segno.make(LINK, error="m", micro=False, boost_error=False)
    unsupported = []
    for name, text, mode, eci in (
        ("numeric", "0123456789012345", "numeric", False),
        ("alphanumeric", "HELLO WORLD", "alphanumeric", False),
        ("eci", "Grüße", "byte", True),
    ):
        code = segno.make(text, error="m", micro=False, boost_error=False, mode=mode,
                          encoding="utf-8" if eci else None, eci=eci)
        unsupported.append({"name": name, "version": code.version, "rows": _rows(code)})

    return {
        "segno": segno.__version__,
        "cases": cases,
        "unsupported": unsupported,
        "link": {"text": LINK, "version": link_code.version, "ec": "M",
                 "mask": link_code.mask, "rows": _rows(link_code)},
    }


def main() -> None:
    data = build()
    TARGET.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(data['cases'])} Matrizen -> {TARGET.relative_to(ROOT)} "
          f"({TARGET.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
