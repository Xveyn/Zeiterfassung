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


# --- Platzhalter auflösen --------------------------------------------------

def resolve(text, version):
    """Ersetzt jeden Platzhalter in `text` durch `version`.

    Liefert `(neuer_text, anzahl)`. Reine Textlogik ohne Dateizugriff, damit
    sie testbar bleibt.
    """
    count = text.count(PLACEHOLDER)
    return text.replace(PLACEHOLDER, version), count


def find_unresolved(text):
    """Liefert die 1-basierten Zeilennummern, in denen noch ein Platzhalter steht."""
    return [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if PLACEHOLDER in line
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

def _read_readme():
    with open(README_PATH, encoding="utf-8") as handle:
        return handle.read()


def _write_readme(text):
    with open(README_PATH, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _released_versions():
    """Alle echten Release-Kennungen aus den git-Tags des Repos."""
    out = subprocess.run(
        ["git", "-C", _ROOT, "tag", "-l", "v*"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [tag.strip().lstrip("vV") for tag in out.splitlines() if tag.strip()]


# --- CLI -------------------------------------------------------------------

def _cmd_check():
    offen = find_unresolved(_read_readme())
    if not offen:
        print(f"README.md: kein {PLACEHOLDER} offen.")
        return 0
    zeilen = ", ".join(str(n) for n in offen)
    print(
        f"::error file=README.md::README.md enthaelt noch {len(offen)}x "
        f"{PLACEHOLDER} (Zeile {zeilen}). Vor dem Merge eines Release-PRs "
        f"aufloesen: python scripts/resolve_readme_version.py",
        file=sys.stderr,
    )
    return 1


def _cmd_resolve():
    neu, count = resolve(_read_readme(), VERSION)
    if count == 0:
        print(f"README.md: kein {PLACEHOLDER} gefunden, nichts zu tun.")
        return 0
    _write_readme(neu)
    print(f"README.md: {count}x {PLACEHOLDER} -> {VERSION}")
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
