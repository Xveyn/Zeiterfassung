"""Verschiebt ältere Versionen aus CHANGELOG.md nach CHANGELOG-archive.md.

CHANGELOG.md wächst mit jedem Release um einen ausführlichen Abschnitt und
war nach 46 Versionen bei rund 800 Zeilen. Wer dort nachsieht, will fast immer
wissen, was die letzten Releases gebracht haben. Deshalb behält die Datei nur
die neuesten `KEEP_RELEASES` Abschnitte, alles Ältere steht — wortgleich,
neueste zuerst — im Archiv, auf das CHANGELOG.md oben verlinkt.

Zwei Modi:

    python scripts/archive_changelog.py            # Dateien umschreiben
    python scripts/archive_changelog.py --check    # nur anzeigen, nichts schreiben

Läuft nach jedem echten Release im Job `changelog-archive` von `release.yml`
und öffnet einen PR (kein Push nach `master`, s. CLAUDE.md, „CHANGELOG-Archiv").

Warum das niemandem etwas wegnimmt: Der Updates-Tab lädt CHANGELOG.md vom Tag
`v<version>` und sucht dort nur den Abschnitt genau dieser Version — an ihrem
eigenen Tag steht sie immer ganz oben. Ebenso liest `release_notes.py` nur den
Abschnitt der aktuellen Version, und zwar vor dem Archivieren.
"""

import os
import sys

# Dieses Skript liegt in scripts/, gehoert aber zum Repo-Root: es importiert
# aus `src/` und liest `CHANGELOG.md` aus der Wurzel. Ohne den sys.path-Eintrag
# scheitert schon der Import unten (vgl. scripts/build.py). Kein `os.chdir` —
# alle Pfade werden von `_ROOT` abgeleitet, und ein Verzeichniswechsel beim
# Laden traege tests/test_archive_changelog.py mit (vgl.
# scripts/release_notes.py).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.changelog import split_version_sections  # noqa: E402  (nach Bootstrap)

ARCHIVE_FILENAME = "CHANGELOG-archive.md"
CHANGELOG_PATH = os.path.join(_ROOT, "CHANGELOG.md")
ARCHIVE_PATH = os.path.join(_ROOT, ARCHIVE_FILENAME)

#: Wie viele der neuesten Versionen in CHANGELOG.md stehen bleiben.
KEEP_RELEASES = 3

#: Hinweis im Vorspann von CHANGELOG.md. Bewusst KEINE `## `-Überschrift: die
#: hielte `split_version_sections` für eine Version.
ARCHIVE_NOTE = f"Ältere Versionen stehen im [Archiv]({ARCHIVE_FILENAME})."

ARCHIVE_PREAMBLE = (
    "# Changelog — Archiv\n\n"
    "Ältere Versionen, neueste zuerst. Die aktuellen stehen in "
    "[CHANGELOG.md](CHANGELOG.md).\n"
)


def _join(preamble, sections):
    body = "\n\n".join(section for _, section in sections)
    return preamble.rstrip("\n") + "\n\n" + body + "\n"


def _with_note(preamble):
    if ARCHIVE_FILENAME in preamble:
        return preamble
    return preamble.rstrip("\n") + "\n\n" + ARCHIVE_NOTE + "\n"


def archive(changelog_text, archive_text, keep):
    """Liefert (neue CHANGELOG.md, neues Archiv, verschobene Versionen).

    `archive_text` ist None, wenn es noch kein Archiv gibt; es bleibt None,
    solange nichts zu verschieben ist. Ohne Überhang kommen beide Texte
    unverändert zurück — ein zweiter Lauf ändert also nichts.

    Eine Version, die schon im Archiv steht, wird nicht noch einmal eingefügt
    (etwa nach einem Lauf, der das Archiv schrieb, CHANGELOG.md aber nicht
    mehr): sie fällt dann nur aus CHANGELOG.md heraus und taucht nicht in der
    Liste der verschobenen Versionen auf.
    """
    preamble, sections = split_version_sections(changelog_text)
    overflow = sections[keep:]
    if not overflow:
        return changelog_text, archive_text, []

    if archive_text is None:
        archive_preamble, archived = ARCHIVE_PREAMBLE, []
    else:
        archive_preamble, archived = split_version_sections(archive_text)
    known = {version for version, _ in archived}
    moved = [(version, section) for version, section in overflow if version not in known]

    new_changelog = _join(_with_note(preamble), sections[:keep])
    new_archive = _join(archive_preamble, moved + archived)
    return new_changelog, new_archive, [version for version, _ in moved]


def _read(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _write(path, text):
    # newline="\n": auf der Windows-Dev-Maschine schriebe der Default CRLF.
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main(argv):
    check = "--check" in argv[1:]
    changelog_text = _read(CHANGELOG_PATH)
    if changelog_text is None:
        print(f"::error::{CHANGELOG_PATH} nicht gefunden.")
        return 1
    archive_text = _read(ARCHIVE_PATH)

    new_changelog, new_archive, moved = archive(changelog_text, archive_text, KEEP_RELEASES)
    if new_changelog == changelog_text and new_archive == archive_text:
        print(f"CHANGELOG.md: höchstens {KEEP_RELEASES} Versionen, nichts zu archivieren.")
        return 0

    listed = ", ".join(moved) if moved else "(nur Duplikate entfernt)"
    if check:
        print(f"Würde nach {ARCHIVE_FILENAME} verschieben: {listed}")
        return 0

    _write(CHANGELOG_PATH, new_changelog)
    _write(ARCHIVE_PATH, new_archive)
    print(f"Nach {ARCHIVE_FILENAME} verschoben: {listed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
