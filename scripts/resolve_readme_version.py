"""Pflegt die Versionsmarker der README.

Hintergrund steht in CLAUDE.md, „README-Zeilen für Unveröffentlichtes
markieren": `master` ist der Default-Branch, die README also die Startseite
des Repos — und sie beschreibt den Stand von `master`, nicht den des letzten
Releases. Wer ein noch nicht veröffentlichtes Feature dokumentiert, schreibt
deshalb `*(ab --VERSION--)*` statt die kommende Version zu raten. Geraten wird
sie sonst falsch, sobald ein Patch dazwischenkommt — und dann steht die
falsche Zahl dauerhaft auf der Startseite.

Drei Modi:

    python scripts/resolve_readme_version.py           # --VERSION-- -> VERSION
    python scripts/resolve_readme_version.py --check    # nur pruefen (CI)
    python scripts/resolve_readme_version.py --prune    # alte Marker entfernen

`--check` ist der Modus für den `readme-version.yml`-Workflow: Exit 1, solange
noch ein Platzhalter in der README steht. Bewusst NICHT im Release-Workflow
selbst — der pusht nichts nach `master` (s. CLAUDE.md, „Branch Protection"),
und beim Release ist der Tag längst gesetzt: eine Korrektur danach läge nur
auf `master`, während `v<VERSION>` für immer auf einen Baum mit `--VERSION--`
zeigte.

`--prune` räumt Marker weg, die `KEEP_RELEASES` echte Releases alt sind. Er
läuft nach dem Release und öffnet einen PR (kein Push nach `master`) — siehe
`release.yml`, Job `readme-marker-cleanup`.

**Screenshots** (`docs/screenshots/`) tragen die Version im Dateinamen
(`kalender-v1.24.0.png`). Wer sie vor dem Release aufnimmt, kennt die Version
so wenig wie beim Marker — also `kalender-v--VERSION--.png`. Auflösen benennt
diese Dateien um und zieht die Verweise in `README.md` und
`docs/screenshots/README.md` nach; `--check` meldet einen offenen Platzhalter
auch dort. Getroffen wird nur das Token zwischen `-v` und `.png`, nie
Fließtext.
"""

import os
import re
import subprocess
import sys

# Dieses Skript liegt in scripts/, gehört aber zum Repo-Root: es importiert aus
# `src/` und liest `README.md` aus der Wurzel. Ohne den sys.path-Eintrag
# scheitert schon der Import unten mit `ModuleNotFoundError: No module named
# 'src'` (vgl. scripts/build.py).
#
# Anders als build.py **kein** `os.chdir(_ROOT)`: alle Pfade hier werden von
# `_ROOT` abgeleitet, ein Verzeichniswechsel bräuchte es dafür nicht — und er
# wäre ein Seiteneffekt beim Laden, den tests/test_readme_version.py mitträge.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.version import VERSION, parse_release_id  # noqa: E402  (erst nach dem Bootstrap)

README_PATH = os.path.join(_ROOT, "README.md")
SCREENSHOTS_DIR = os.path.join(_ROOT, "docs", "screenshots")
SCREENSHOTS_README = os.path.join(SCREENSHOTS_DIR, "README.md")

#: Der Platzhalter. Bewusst laut und in Großbuchstaben — er soll auf der
#: gerenderten Startseite auffallen, solange er unaufgelöst dort steht.
PLACEHOLDER = "--VERSION--"

#: Ab wie vielen NEUEREN echten Releases ein Marker als überholt gilt und von
#: `--prune` entfernt wird. Gemessen in Releases, nicht in Versionssprüngen:
#: zwischen 1.22.0 und 1.23.0 können mehrere Patches liegen, „drei Minor
#: weiter" wäre also kein verlässliches Alter.
KEEP_RELEASES = 5

#: Ein aufgelöster Marker: `*(ab 1.22.0)*`, mitsamt einem führenden
#: Leerzeichen, damit `- **A** *(ab 1.22.0)* — x` zu `- **A** — x` wird und
#: keine doppelten Leerzeichen zurückbleiben. Trifft bewusst NUR
#: Versionsnummern — `*(ab --VERSION--)*` ist ein offener Platzhalter und wird
#: aufgelöst, nicht entfernt.
_MARKER = re.compile(r" ?\*\(ab (\d+\.\d+\.\d+)\)\*")

#: Der noch offene Marker `*(ab --VERSION--)*`. Bewusst dieselbe Form wie
#: `_MARKER` und NICHT das blanke Token: die README erklaert den Platzhalter
#: unter „Features" selbst im Fliesstext („Steht dort statt einer Zahl
#: `--VERSION--`, ist das Feature fertig …"). Ein Ersetzen ueber das blanke
#: Token traefe diese Legende mit und machte aus ihr „Steht dort statt einer
#: Zahl `1.23.0`" — und zwar dauerhaft, denn danach steht dort kein
#: Platzhalter mehr, den ein spaeterer Lauf zurueckdrehen koennte.
_PLACEHOLDER_MARKER = re.compile(r"\*\(ab " + re.escape(PLACEHOLDER) + r"\)\*")


# --- Platzhalter auflösen --------------------------------------------------

def resolve(text, version):
    """Ersetzt jeden offenen Marker in `text` durch einen mit `version`.

    Liefert `(neuer_text, anzahl)`. Reine Textlogik ohne Dateizugriff, damit
    sie testbar bleibt. Getroffen wird nur die Marker-Form, nicht das blanke
    Token — s. `_PLACEHOLDER_MARKER`.
    """
    return _PLACEHOLDER_MARKER.subn(lambda _: f"*(ab {version})*", text)


def find_unresolved(text):
    """Liefert die 1-basierten Zeilennummern mit einem noch offenen Marker."""
    return [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if _PLACEHOLDER_MARKER.search(line)
    ]


# --- Screenshots -----------------------------------------------------------

#: Der Platzhalter in einem Screenshot-Namen: nur zwischen `-v` und `.png`,
#: damit Fließtext und die Marker-Form unberührt bleiben.
_SCREENSHOT_TOKEN = re.compile(r"(?<=-v)" + re.escape(PLACEHOLDER) + r"(?=\.png)")
#: Eine Screenshot-Datei mit Platzhalter im Namen.
_SCREENSHOT_FILE = re.compile(r"^[\w.-]+-v" + re.escape(PLACEHOLDER) + r"\.png$")


def resolve_screenshots(text, version):
    """Ersetzt den Platzhalter in Screenshot-Pfaden. `(neuer_text, anzahl)`."""
    return _SCREENSHOT_TOKEN.subn(version, text)


def find_unresolved_screenshots(text):
    """Zeilennummern (1-basiert) mit einem Screenshot-Pfad voller Platzhalter."""
    return [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if _SCREENSHOT_TOKEN.search(line)
    ]


def screenshot_renames(names, version):
    """`(alt, neu)` für jede Datei in `names` mit Platzhalter, sortiert."""
    return [
        (name, name.replace(PLACEHOLDER, version))
        for name in sorted(names)
        if _SCREENSHOT_FILE.match(name)
    ]


# --- alte Marker aufräumen -------------------------------------------------

def find_markers(text):
    """Liefert die Versionen aller aufgelösten Marker, in Reihenfolge."""
    return _MARKER.findall(text)


def stale_versions(markers, releases, keep):
    """Welche Marker-Versionen haben mindestens `keep` neuere echte Releases?

    `releases` sind Release-Kennungen ohne v-Prefix. Pre-Releases zählen
    **nicht** mit: sie tragen die Version des vorangegangenen echten Releases
    (s. `version.parse_release_id`), und mehrere Pres zu einem Release würden
    das Alter sonst künstlich hochtreiben und Marker viel zu früh wegräumen.
    """
    echte = [
        key
        for key in (parse_release_id(r) for r in releases)
        if key is not None and key[3] == 0
    ]
    reif = set()
    for marker in markers:
        key = parse_release_id(marker)
        if key is None:
            continue
        if sum(1 for r in echte if r > key) >= keep:
            reif.add(marker)
    return reif


def prune(text, versions):
    """Entfernt die Marker, deren Version in `versions` steht.

    Liefert `(neuer_text, anzahl)`. Marker, die nicht in `versions` stehen,
    bleiben unangetastet — ebenso der offene Platzhalter.
    """
    count = 0

    def _ersetzen(match):
        nonlocal count
        if match.group(1) in versions:
            count += 1
            return ""
        return match.group(0)

    return _MARKER.sub(_ersetzen, text), count


# --- I/O -------------------------------------------------------------------

def _read_readme(path=README_PATH):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _write_readme(text, path=README_PATH):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _screenshot_files():
    return os.listdir(SCREENSHOTS_DIR) if os.path.isdir(SCREENSHOTS_DIR) else []


def _released_versions():
    """Alle echten Release-Kennungen aus den git-Tags des Repos."""
    out = subprocess.run(
        ["git", "-C", _ROOT, "tag", "-l", "v*"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [tag.strip().lstrip("vV") for tag in out.splitlines() if tag.strip()]


# --- CLI -------------------------------------------------------------------

def _cmd_check():
    text = _read_readme()
    offen = find_unresolved(text)
    probleme = []
    if offen:
        probleme.append(("README.md", offen))
    for path, name in ((README_PATH, "README.md"),
                       (SCREENSHOTS_README, "docs/screenshots/README.md")):
        if os.path.exists(path):
            zeilen = find_unresolved_screenshots(_read_readme(path))
            if zeilen:
                probleme.append((name, zeilen))
    dateien = [alt for alt, _neu in screenshot_renames(_screenshot_files(), VERSION)]
    if not probleme and not dateien:
        print(f"README.md: kein {PLACEHOLDER} offen.")
        return 0
    for name, zeilen in probleme:
        liste = ", ".join(str(n) for n in zeilen)
        print(
            f"::error file={name}::{name} enthaelt noch {len(zeilen)}x "
            f"{PLACEHOLDER} (Zeile {liste}). Vor dem Merge eines Release-PRs "
            f"aufloesen: python scripts/resolve_readme_version.py",
            file=sys.stderr,
        )
    if dateien:
        print(
            f"::error::docs/screenshots/ hat noch {len(dateien)} Datei(en) mit "
            f"{PLACEHOLDER} im Namen ({', '.join(dateien)}). Aufloesen: "
            f"python scripts/resolve_readme_version.py",
            file=sys.stderr,
        )
    return 1


def _cmd_resolve():
    text = _read_readme()
    neu, count = resolve(text, VERSION)
    neu, shots = resolve_screenshots(neu, VERSION)
    if count or shots:
        _write_readme(neu)
    if os.path.exists(SCREENSHOTS_README):
        doc = _read_readme(SCREENSHOTS_README)
        doc_neu, doc_count = resolve_screenshots(doc, VERSION)
        if doc_count:
            _write_readme(doc_neu, SCREENSHOTS_README)
        shots += doc_count
    renames = screenshot_renames(_screenshot_files(), VERSION)
    for alt, neu_name in renames:
        os.replace(os.path.join(SCREENSHOTS_DIR, alt),
                   os.path.join(SCREENSHOTS_DIR, neu_name))
    if not (count or shots or renames):
        print(f"README.md: kein {PLACEHOLDER} gefunden, nichts zu tun.")
        return 0
    print(f"README.md: {count}x {PLACEHOLDER} -> {VERSION}")
    if shots or renames:
        print(f"Screenshots: {shots} Verweis(e) und {len(renames)} Datei(en) "
              f"-> v{VERSION}")
    return 0


def _cmd_prune():
    text = _read_readme()
    reif = stale_versions(find_markers(text), _released_versions(), KEEP_RELEASES)
    if not reif:
        print(f"README.md: kein Marker ist {KEEP_RELEASES} Releases alt.")
        return 0
    neu, count = prune(text, reif)
    _write_readme(neu)
    print(f"README.md: {count} Marker entfernt ({', '.join(sorted(reif))}).")
    return 0


def main(argv):
    args = argv[1:]
    if "--check" in args:
        return _cmd_check()
    if "--prune" in args:
        return _cmd_prune()
    return _cmd_resolve()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
