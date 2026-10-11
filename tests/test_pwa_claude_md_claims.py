"""Schutztest für die harten Behauptungen der `pwa/CLAUDE.md` (#290).

Gleiche Bauart wie `test_claude_md_claims.py`, nur gegen die PWA-Doku: Wo
`pwa/CLAUDE.md` einen **exakten** Wert nennt, der im Repo noch einmal steht
(Protokollnummer, Prüfintervall, Node-Version, Port, Pages-Adresse, Dateien),
wird er aus der Markdown-Datei geparst und gegen den Code gehalten.

* **Quelle ist die Doku, nicht eine Kopie.** Kein Erwartungswert steht hier als
  Literal.
* **Ein gescheiterter Parser ist rot** (`_claim`), nicht grün: ein Test, der
  seine Erwartung nicht mehr findet und deshalb schweigt, prüft nichts mehr.
* **Fehlermeldungen nennen beide Seiten**, damit klar ist, was nachzuziehen ist.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PWA = ROOT / "pwa"
PWA_MD = PWA / "CLAUDE.md"

TEXT = PWA_MD.read_text(encoding="utf-8")
FLAT = re.sub(r"\s+", " ", TEXT)


def _claim(pattern, was):
    match = re.search(pattern, FLAT)
    assert match, (
        f"Parser gescheitert: die Behauptung der pwa/CLAUDE.md über {was} steht nicht mehr "
        f"in der erwarteten Form (Muster: {pattern!r}).\n"
        "Wurde der Abschnitt nur umformuliert, gehört das Muster nachgezogen; "
        "wurde die Behauptung entfernt, gehört auch diese Assertion weg.")
    return match


def _read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_the_documented_protocol_matches_every_place_that_defines_it():
    documented = int(_claim(r"Aktuell steht es auf `PROTOCOL` (\d+)", "die Protokollnummer").group(1))
    places = {
        "pwa/pairing.js": r"export const PROTOCOL = (\d+)",
        "src/mobile_sync.py": r"^PROTOCOL = (\d+)",
        "src/mobile_crypto.py": r"^PROTOCOL = (\d+)",
    }
    for path, pattern in places.items():
        found = re.search(pattern, _read(path), re.M)
        assert found, f"Parser gescheitert: keine PROTOCOL-Zeile in {path}"
        assert int(found.group(1)) == documented, (
            f"pwa/CLAUDE.md sagt PROTOCOL {documented}, {path} sagt {found.group(1)}")


def test_the_documented_update_interval_matches_the_policy():
    documented = int(_claim(r"höchstens alle (\d+) Minuten \(`UPDATE_CHECK_INTERVAL_MS`\)",
                            "das Prüfintervall").group(1))
    found = re.search(r"UPDATE_CHECK_INTERVAL_MS = (\d+) \* 60 \* 1000", _read("pwa/update-policy.js"))
    assert found, "Parser gescheitert: UPDATE_CHECK_INTERVAL_MS in pwa/update-policy.js"
    assert int(found.group(1)) == documented, (
        f"pwa/CLAUDE.md sagt {documented} Minuten, update-policy.js sagt {found.group(1)}")


def test_the_documented_node_version_matches_the_ci_job():
    documented = _claim(r"läuft mit Node (\d+)", "die Node-Version").group(1)
    workflow = _read(".github/workflows/test.yml")
    job = workflow[workflow.index("\n  pwa:"):]
    found = re.search(r"node-version: '(\d+)'", job)
    assert found, "Parser gescheitert: keine node-version im Job `pwa` von test.yml"
    assert found.group(1) == documented, (
        f"pwa/CLAUDE.md sagt Node {documented}, test.yml sagt Node {found.group(1)}")


def test_the_documented_dev_port_is_the_devserver_default():
    documented = _claim(r"`http://localhost:(\d+)/` \(sichere Origin", "den Dev-Server-Port").group(1)
    found = re.search(r'"--port", type=int, default=(\d+)', _read("scripts/pwa_devserver.py"))
    assert found, "Parser gescheitert: kein --port-Default in scripts/pwa_devserver.py"
    assert found.group(1) == documented, (
        f"pwa/CLAUDE.md sagt Port {documented}, pwa_devserver.py sagt {found.group(1)}")


def test_the_documented_pages_address_is_the_one_in_mobile_routes():
    documented = _claim(r"Die Adresse `(https://[^`]+)` steht als `PWA_ORIGIN`/ ?`PWA_URL`",
                        "die Pages-Adresse").group(1)
    source = _read("src/mobile_routes.py")
    url = re.search(r'^PWA_URL = "([^"]+)"', source, re.M)
    origin = re.search(r'^PWA_ORIGIN = "([^"]+)"', source, re.M)
    assert url and origin, "Parser gescheitert: PWA_URL/PWA_ORIGIN in src/mobile_routes.py"
    assert url.group(1) == documented, f"pwa/CLAUDE.md: {documented}, PWA_URL: {url.group(1)}"
    assert documented.startswith(origin.group(1) + "/"), (
        f"PWA_ORIGIN {origin.group(1)} passt nicht zur dokumentierten Adresse {documented}")


def test_every_module_the_doc_names_exists():
    names = set(re.findall(r"`((?:[\w-]+/)*[\w-]+\.(?:js|json|css|html|webmanifest))`", TEXT))
    assert len(names) > 15, "Parser gescheitert: kaum Dateinamen in pwa/CLAUDE.md gefunden"
    missing = []
    for name in sorted(names):
        candidates = [PWA / name, PWA / "test" / name, PWA / "test" / "fixtures" / name]
        if name.startswith("pwa/"):
            candidates = [ROOT / name]
        if not any(path.is_file() for path in candidates):
            missing.append(name)
    assert not missing, (
        f"pwa/CLAUDE.md nennt Dateien, die es nicht (mehr) gibt: {missing}")


def test_every_python_path_the_doc_names_exists():
    paths = set(re.findall(r"`((?:src|scripts|tests|\.github)/[\w./-]+)`", TEXT))
    assert paths, "Parser gescheitert: keine Repo-Pfade in pwa/CLAUDE.md gefunden"
    missing = [path for path in sorted(paths) if not (ROOT / path.rstrip("/")).exists()]
    assert not missing, f"pwa/CLAUDE.md nennt Pfade, die es nicht (mehr) gibt: {missing}"


def test_the_frozen_predecessor_really_lacks_the_fields_added_since():
    _claim(r"ersten eingefrorenen Stand|erste eingefrorene Stand", "den ersten eingefrorenen Stand")
    import json
    frozen = json.loads((PWA / "test" / "fixtures" / "compat" / "sync-response-pre-288.json").read_text("utf-8"))
    assert "defaults" not in frozen and "desktop" not in frozen, (
        "pwa/CLAUDE.md nennt den Vor-#288-Stand als eingefroren, aber compat/sync-response-pre-288.json "
        "trägt `defaults`/`desktop`: eingefrorene Fixtures werden nicht mitgezogen")


def test_automatic_updates_are_documented_off_by_default_and_are_in_the_store():
    _claim(r"Standard \*\*aus\*\*", "den Standard des Auto-Update-Schalters")
    found = re.search(r"auto_update:\s*(\w+)", _read("pwa/store.js"))
    assert found and found.group(1) == "false", (
        "pwa/CLAUDE.md sagt: Auto-Update ist standardmäßig aus, pwa/store.js setzt "
        f"auto_update auf {found.group(1) if found else 'nichts'}")


def test_the_pages_workflow_does_not_publish_the_markdown_the_doc_lives_in():
    _claim(r"ohne `test/`, `package.json` und Markdown", "die Pages-Ausschlüsse")
    assert "--exclude '*.md'" in _read(".github/workflows/pages.yml"), (
        "pwa/CLAUDE.md sagt, Markdown werde nicht veröffentlicht, pages.yml schließt '*.md' nicht aus")


def test_the_root_claude_md_points_to_the_pwa_doc():
    assert "pwa/CLAUDE.md" in _read("CLAUDE.md"), (
        "Die Root-CLAUDE.md muss auf pwa/CLAUDE.md verweisen (die PWA-Doku liegt dort, #290)")


def test_the_documented_window_steps_match_the_policy():
    documented = [int(n) for n in _claim(r"Stufen \*\*(\d+) / (\d+) / (\d+)\*\* Tage",
                                         "die Fensterstufen").groups()]
    found = re.search(r"WINDOW_STEPS = \[([\d, ]+)\]", _read("pwa/window-policy.js"))
    assert found, "Parser gescheitert: WINDOW_STEPS in pwa/window-policy.js"
    assert [int(n) for n in found.group(1).split(",")] == documented, (
        f"pwa/CLAUDE.md sagt {documented}, window-policy.js sagt {found.group(1)}")


def test_the_documented_window_budget_matches_the_desktop():
    documented = int(_claim(r"Budget von (\d+) KiB", "das Mengenlimit").group(1))
    found = re.search(r"^MAX_RESPONSE_ENTRY_BYTES = (\d+) \* 1024", _read("src/mobile_sync.py"), re.M)
    assert found, "Parser gescheitert: MAX_RESPONSE_ENTRY_BYTES in src/mobile_sync.py"
    assert int(found.group(1)) == documented, (
        f"pwa/CLAUDE.md sagt {documented} KiB, mobile_sync.py sagt {found.group(1)}")


def test_the_documented_window_cap_choices_match_the_desktop():
    documented = [int(n) for n in _claim(r"Obergrenze \*\*(\d+) / (\d+) / (\d+) / (\d+)\*\* Tage",
                                         "die Obergrenzen").groups()]
    found = re.search(r"^WINDOW_CAP_CHOICES = \(([\d, ]+)\)", _read("src/mobile_sync.py"), re.M)
    assert found, "Parser gescheitert: WINDOW_CAP_CHOICES in src/mobile_sync.py"
    assert [int(n) for n in found.group(1).split(",")] == documented, (
        f"pwa/CLAUDE.md sagt {documented}, mobile_sync.py sagt {found.group(1)}")


def test_the_documented_default_window_matches_the_desktop_and_the_phone():
    documented = int(_claim(r"Standardfenster \*\*(\d+) Tage\*\*", "das Standardfenster").group(1))
    desktop = re.search(r"^WINDOW_DAYS = (\d+)", _read("src/mobile_sync.py"), re.M)
    phone = re.search(r"DEFAULT_WISH = (\d+)", _read("pwa/window-policy.js"))
    assert desktop and phone, "Parser gescheitert: WINDOW_DAYS / DEFAULT_WISH"
    assert int(desktop.group(1)) == documented == int(phone.group(1)), (
        f"pwa/CLAUDE.md sagt {documented}, Desktop {desktop.group(1)}, Handy {phone.group(1)}")
