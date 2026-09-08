"""Baut den Release-Body eines echten Releases aus CHANGELOG.md.

Bis 1.23.0 bestand der Body aus der von GitHub generierten PR-Liste
(`gh release create --generate-notes`). Die beschreibt aber die Arbeit, nicht
die Aenderung: „fix(urlaub): Urlaub und Ist-Zeit am selben Tag nicht doppelt
verguetet" sagt einem Nutzer weniger als der kuratierte CHANGELOG-Eintrag, der
danebensteht und ohnehin fuer jedes Release geschrieben wird. Also steht er
jetzt direkt auf der Release-Seite, statt dass der Leser ihn sich im Repo
sucht.

Zwei Modi:

    python scripts/release_notes.py --check          # nur pruefen (CI)
    python scripts/release_notes.py --out notes.md   # Body schreiben

`--check` laeuft im `pre-check`-Job von `release.yml` und bricht ab, wenn
CHANGELOG.md keinen Abschnitt zur Version aus `src/version.py` hat — also
bevor die drei Plattform-Builds laufen und lange bevor ein Tag gepusht ist.

Betrifft **nur echte Releases**. Ein Pre-Release hat bewusst keinen
kuratierten CHANGELOG-Eintrag (s. CLAUDE.md, „Pre-Releases"): dort ist der
generierte Body die Changelog-Quelle der App, und `release.yml` bleibt fuer
diesen Zweig bei `--generate-notes`.
"""

import os
import re
import sys

# Dieses Skript liegt in scripts/, gehoert aber zum Repo-Root: es importiert
# aus `src/` und liest `CHANGELOG.md` aus der Wurzel. Ohne den sys.path-Eintrag
# scheitert schon der Import unten mit `ModuleNotFoundError: No module named
# 'src'` (vgl. scripts/build.py). Kein `os.chdir` — alle Pfade hier werden von
# `_ROOT` abgeleitet, und ein Verzeichniswechsel beim Laden traege
# tests/test_release_notes.py mit (vgl. scripts/resolve_readme_version.py).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.changelog import extract_version_section  # noqa: E402  (nach Bootstrap)
from src.version import VERSION  # noqa: E402  (nach Bootstrap)

CHANGELOG_PATH = os.path.join(_ROOT, "CHANGELOG.md")


def body_for(changelog_text, version):
    """Liefert den Release-Body zu `version` — den CHANGELOG-Abschnitt ohne
    seine Versionsueberschrift. None, wenn es den Abschnitt nicht gibt oder
    unter der Ueberschrift nichts steht.

    Der Ausschnitt kommt aus `src.changelog.extract_version_section`, also aus
    derselben Funktion, mit der die App den Eintrag im Updates-Tab anzeigt —
    ein zweiter Parser fuer dieselbe Datei wuerde lautlos auseinanderlaufen.

    Die Ueberschrift faellt weg, weil der Release-Titel die Version schon
    nennt („Zeiterfassung v1.24.0") und GitHub das Datum selbst anzeigt; sie
    stuende sonst ein drittes Mal auf derselben Seite.

    Ein leerer Rest ist derselbe Fehlerfall wie ein fehlender Abschnitt: ein
    Release mit leerem Body ist fuer den Leser von einem Fehler nicht zu
    unterscheiden.
    """
    section = extract_version_section(changelog_text, version)
    if section is None:
        return None
    heading = re.compile(r"^##\s+" + re.escape(version) + r"\b.*$")
    lines = section.splitlines()
    if lines and heading.match(lines[0]):
        lines = lines[1:]
    body = "\n".join(lines).strip()
    return body or None


def _read_changelog():
    with open(CHANGELOG_PATH, encoding="utf-8") as fh:
        return fh.read()


def _fail(version):
    # ::error:: macht die Zeile in der Actions-UI zur Fehlermeldung am Job,
    # statt sie im Log zu vergraben.
    print(f"::error::CHANGELOG.md hat keinen (oder einen leeren) Abschnitt "
          f"'## {version}'. Der Release-Body wird daraus gebaut — Eintrag im "
          f"Release-PR nachtragen (s. CLAUDE.md, Release-Prozess).")
    return 1


def main(argv):
    args = argv[1:]
    body = body_for(_read_changelog(), VERSION)
    if body is None:
        return _fail(VERSION)

    if "--check" in args:
        print(f"CHANGELOG.md: Abschnitt zu {VERSION} gefunden "
              f"({len(body.splitlines())} Zeilen).")
        return 0

    if "--out" in args:
        pos = args.index("--out") + 1
        if pos >= len(args):
            print("::error::--out braucht einen Dateinamen.")
            return 2
        target = args[pos]
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(body + "\n")
        print(f"{target}: Release-Body zu {VERSION} geschrieben "
              f"({len(body.splitlines())} Zeilen).")
        return 0

    sys.stdout.write(body + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
