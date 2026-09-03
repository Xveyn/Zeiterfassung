"""Löst den README-Platzhalter `--VERSION--` gegen `src/version.py` auf.

Hintergrund steht in CLAUDE.md, „README-Zeilen für Unveröffentlichtes
markieren": `master` ist der Default-Branch, die README also die Startseite
des Repos — und sie beschreibt den Stand von `master`, nicht den des letzten
Releases. Wer ein noch nicht veröffentlichtes Feature dokumentiert, schreibt
deshalb `*(ab --VERSION--)*` statt die kommende Version zu raten. Geraten wird
sie sonst falsch, sobald ein Patch dazwischenkommt — und dann steht die
falsche Zahl dauerhaft auf der Startseite.

Aufgelöst wird im **Release-PR**, wo `src/version.py` ohnehin auf die
Zielversion gesetzt wird:

    python scripts/resolve_readme_version.py           # ersetzen und schreiben
    python scripts/resolve_readme_version.py --check   # nur prüfen (CI)

`--check` ist der Modus für den `readme-version`-Job: Exit 1, solange noch ein
Platzhalter in der README steht. Bewusst NICHT im Release-Workflow selbst —
der pusht nichts nach `master` (s. CLAUDE.md, „Branch Protection"), und beim
Release ist der Tag längst gesetzt: eine Korrektur danach läge nur auf
`master`, während `v<VERSION>` für immer auf einen Baum mit `--VERSION--`
zeigte.
"""

import os
import sys

# Dieses Skript liegt in scripts/, gehört aber zum Repo-Root: es importiert aus
# `src/` und liest `README.md` aus der Wurzel. Ohne den sys.path-Eintrag
# scheitert schon der VERSION-Import mit `ModuleNotFoundError: No module named
# 'src'` (vgl. scripts/build.py).
#
# Anders als build.py **kein** `os.chdir(_ROOT)`: alle Pfade hier werden von
# `_ROOT` abgeleitet, ein Verzeichniswechsel bräuchte es dafür nicht — und er
# wäre ein Seiteneffekt beim Laden, den tests/test_readme_version.py mitträge.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

README_PATH = os.path.join(_ROOT, "README.md")

#: Der Platzhalter. Bewusst laut und in Großbuchstaben — er soll auf der
#: gerenderten Startseite auffallen, solange er unaufgelöst dort steht.
PLACEHOLDER = "--VERSION--"


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


def _read_readme():
    with open(README_PATH, encoding="utf-8") as handle:
        return handle.read()


def main(argv):
    check_only = "--check" in argv[1:]
    text = _read_readme()

    if check_only:
        offen = find_unresolved(text)
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

    from src.version import VERSION  # erst nach dem sys.path-Bootstrap möglich

    neu, count = resolve(text, VERSION)
    if count == 0:
        print(f"README.md: kein {PLACEHOLDER} gefunden, nichts zu tun.")
        return 0

    with open(README_PATH, "w", encoding="utf-8", newline="") as handle:
        handle.write(neu)
    print(f"README.md: {count}x {PLACEHOLDER} -> {VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
