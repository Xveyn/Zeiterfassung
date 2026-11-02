"""Die Zahlen in `docs/datenschutz.md` gegen den Code des Relays (#358).

Das Dokument nennt zwei exakte Werte, die in `relay/src/validate.js` (`LIMITS`) noch einmal stehen:
die Frist im Leerlauf (`idleDays`) und die Größe einer Nachricht (`maxFrame`). Beide werden aus den
Dateien geparst, nicht hier kopiert. Findet ein Muster nichts, ist der Test rot: ein Test, der seine
Erwartung nicht mehr findet und deshalb schweigt, prüft nichts mehr (Muster `test_claude_md_claims.py`).
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
VALIDATE_JS = (ROOT / "relay" / "src" / "validate.js").read_text(encoding="utf-8")
DOC = (ROOT / "docs" / "datenschutz.md").read_text(encoding="utf-8")


def _js_limit(name):
    match = re.search(rf"\b{name}:\s*([0-9_]+)", VALIDATE_JS)
    assert match, f"Parser gescheitert: `{name}` steht nicht mehr als Zahl in relay/src/validate.js."
    return int(match.group(1).replace("_", ""))


def _doc_number(pattern, was):
    match = re.search(pattern, DOC)
    assert match, (
        f"Parser gescheitert: docs/datenschutz.md nennt {was} nicht mehr in der erwarteten Form "
        f"(Muster: {pattern!r})."
    )
    return int(match.group(1))


def test_idle_retention_matches_the_relay():
    in_doc = _doc_number(r"Aufbewahrung im Leerlauf:\s*(\d+)\s*Tage", "die Frist im Leerlauf")
    in_code = _js_limit("idleDays")
    assert in_doc == in_code, f"datenschutz.md sagt {in_doc} Tage, validate.js idleDays ist {in_code}."


def test_message_size_matches_the_relay():
    in_code = _js_limit("maxFrame")
    in_doc = _doc_number(r"höchstens 1 MiB \((\d+) Bytes\)", "die Größe je Nachricht")
    assert in_doc == in_code, f"datenschutz.md sagt {in_doc} Bytes, validate.js maxFrame ist {in_code}."
    assert in_code == 1024 * 1024, "maxFrame ist nicht mehr 1 MiB: der Text `1 MiB` im Dokument stimmt nicht mehr."


def test_the_doc_keeps_its_disclaimer():
    assert "keine Rechtsberatung" in DOC.split("\n\n", 2)[1]
