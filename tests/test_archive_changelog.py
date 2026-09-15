"""Tests für scripts/archive_changelog.py.

Nach jedem echten Release wandern alle bis auf die neuesten `KEEP_RELEASES`
Abschnitte aus CHANGELOG.md nach CHANGELOG-archive.md (s. CLAUDE.md,
„CHANGELOG-Archiv"). Getestet wird die reine Textlogik, ein Lauf gegen die
Dateien und ein Gegencheck mit der echten CHANGELOG.md — dort vor allem, dass
kein Abschnitt verloren geht und die App wie der Release-Workflow weiter
finden, was sie brauchen.

Das Skript liegt in `scripts/` und ist kein importierbares Modul, wird also
über seinen Pfad geladen — Muster wie tests/test_release_notes.py.
"""

import importlib.util
import pathlib

from src.changelog import extract_version_section, split_version_sections

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


arch = _load("_archive_changelog", "archive_changelog.py")
notes = _load("_release_notes_for_archive", "release_notes.py")


def _changelog(*versions):
    parts = ["# Changelog\n"]
    for v in versions:
        parts.append(f"## {v} — 2026-01-01\n\n### Behoben\n- **Fix {v}**: repariert.\n")
    return "\n".join(parts)


def _versions(text):
    return [v for v, _ in split_version_sections(text)[1]]


# --- archive (reine Textlogik) ----------------------------------------------

def test_bis_keep_abschnitte_bleibt_alles_unveraendert():
    text = _changelog("1.3.0", "1.2.0", "1.1.0")
    new_changelog, new_archive, moved = arch.archive(text, None, keep=3)
    assert new_changelog == text
    assert new_archive is None
    assert moved == []


def test_ueberhang_wandert_ins_neue_archiv_neueste_zuerst():
    text = _changelog("1.5.0", "1.4.0", "1.3.0", "1.2.0", "1.1.0")
    new_changelog, new_archive, moved = arch.archive(text, None, keep=3)
    assert _versions(new_changelog) == ["1.5.0", "1.4.0", "1.3.0"]
    assert _versions(new_archive) == ["1.2.0", "1.1.0"]
    assert moved == ["1.2.0", "1.1.0"]
    assert new_archive.startswith("# ")


def test_abschnittsinhalt_bleibt_wortgleich():
    text = _changelog("1.5.0", "1.4.0", "1.3.0", "1.2.0")
    new_changelog, new_archive, _ = arch.archive(text, None, keep=3)
    for v in ("1.5.0", "1.4.0", "1.3.0"):
        assert extract_version_section(new_changelog, v) == extract_version_section(text, v)
    assert extract_version_section(new_archive, "1.2.0") == extract_version_section(text, "1.2.0")


def test_bestehendes_archiv_wird_oben_ergaenzt_nicht_ueberschrieben():
    _, archive_1, _ = arch.archive(
        _changelog("1.4.0", "1.3.0", "1.2.0", "1.1.0"), None, keep=3)
    changelog_2 = _changelog("1.5.0", "1.4.0", "1.3.0", "1.2.0")
    _, archive_2, moved = arch.archive(changelog_2, archive_1, keep=3)
    assert moved == ["1.2.0"]
    assert _versions(archive_2) == ["1.2.0", "1.1.0"]


def test_zweiter_lauf_aendert_nichts():
    text = _changelog("1.5.0", "1.4.0", "1.3.0", "1.2.0", "1.1.0")
    changelog_1, archive_1, _ = arch.archive(text, None, keep=3)
    changelog_2, archive_2, moved = arch.archive(changelog_1, archive_1, keep=3)
    assert (changelog_2, archive_2, moved) == (changelog_1, archive_1, [])


def test_version_schon_im_archiv_wird_nicht_doppelt_eingefuegt():
    # Z.B. ein abgebrochener Lauf, der das Archiv schon geschrieben hatte, die
    # gekürzte CHANGELOG.md aber nicht mehr.
    text = _changelog("1.4.0", "1.3.0", "1.2.0", "1.1.0")
    _, archive_1, _ = arch.archive(text, None, keep=3)
    new_changelog, archive_2, moved = arch.archive(text, archive_1, keep=3)
    assert _versions(new_changelog) == ["1.4.0", "1.3.0", "1.2.0"]
    assert archive_2 == archive_1
    assert moved == []


def test_changelog_verlinkt_das_archiv_genau_einmal():
    text = _changelog("1.5.0", "1.4.0", "1.3.0", "1.2.0", "1.1.0")
    changelog_1, archive_1, _ = arch.archive(text, None, keep=3)
    assert changelog_1.count(arch.ARCHIVE_FILENAME) == 1
    # Nächstes Release: neuer Abschnitt oben, der Hinweis steht schon da.
    preamble, _ = split_version_sections(changelog_1)
    new_section = _changelog("1.6.0").split("\n", 2)[2]
    next_release = preamble + new_section + "\n" + changelog_1[len(preamble):]
    changelog_2, _, moved = arch.archive(next_release, archive_1, keep=3)
    assert moved == ["1.3.0"]
    assert changelog_2.count(arch.ARCHIVE_FILENAME) == 1


def test_archiv_link_ist_keine_versionsueberschrift():
    # Stuende der Hinweis als `## `-Zeile da, hielte extract_version_section
    # ihn für eine Version — und der Updates-Tab zeigte ihn als Changelog.
    text = _changelog("1.4.0", "1.3.0", "1.2.0", "1.1.0")
    new_changelog, _, _ = arch.archive(text, None, keep=3)
    preamble, sections = split_version_sections(new_changelog)
    assert arch.ARCHIVE_FILENAME in preamble
    assert all(arch.ARCHIVE_FILENAME not in s for _, s in sections)


# --- Lauf gegen Dateien -----------------------------------------------------

def test_main_schreibt_beide_dateien_und_ist_idempotent(tmp_path, monkeypatch):
    changelog = tmp_path / "CHANGELOG.md"
    archive = tmp_path / arch.ARCHIVE_FILENAME
    changelog.write_text(_changelog("1.5.0", "1.4.0", "1.3.0", "1.2.0"), encoding="utf-8")
    monkeypatch.setattr(arch, "CHANGELOG_PATH", str(changelog))
    monkeypatch.setattr(arch, "ARCHIVE_PATH", str(archive))

    assert arch.main(["archive_changelog.py"]) == 0
    first = (changelog.read_bytes(), archive.read_bytes())
    assert _versions(changelog.read_text(encoding="utf-8")) == ["1.5.0", "1.4.0", "1.3.0"]
    assert _versions(archive.read_text(encoding="utf-8")) == ["1.2.0"]
    # LF, nicht CRLF: auf der Windows-Dev-Maschine schriebe `open(..., "w")`
    # sonst CRLF, und der erste CI-Lauf danach sähe jede Zeile als geändert.
    assert b"\r\n" not in first[0] and b"\r\n" not in first[1]

    assert arch.main(["archive_changelog.py"]) == 0
    assert (changelog.read_bytes(), archive.read_bytes()) == first


def test_check_modus_schreibt_nichts(tmp_path, monkeypatch):
    changelog = tmp_path / "CHANGELOG.md"
    archive = tmp_path / arch.ARCHIVE_FILENAME
    original = _changelog("1.5.0", "1.4.0", "1.3.0", "1.2.0")
    changelog.write_text(original, encoding="utf-8")
    monkeypatch.setattr(arch, "CHANGELOG_PATH", str(changelog))
    monkeypatch.setattr(arch, "ARCHIVE_PATH", str(archive))

    assert arch.main(["archive_changelog.py", "--check"]) == 0
    assert changelog.read_text(encoding="utf-8") == original
    assert not archive.exists()


# --- Gegencheck gegen die echte Datei --------------------------------------

def _real_changelog():
    return (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def _real_archive():
    path = _ROOT / arch.ARCHIVE_FILENAME
    return path.read_text(encoding="utf-8") if path.exists() else None


def test_echte_changelog_verliert_beim_archivieren_keinen_abschnitt():
    changelog, archive = _real_changelog(), _real_archive()
    before = split_version_sections(changelog)[1] + (
        split_version_sections(archive)[1] if archive else [])
    new_changelog, new_archive, _ = arch.archive(changelog, archive, arch.KEEP_RELEASES)
    after = split_version_sections(new_changelog)[1] + (
        split_version_sections(new_archive)[1] if new_archive else [])
    assert after == before
    assert len(split_version_sections(new_changelog)[1]) <= arch.KEEP_RELEASES


def test_echte_changelog_liefert_nach_dem_archivieren_denselben_release_body():
    """Der Release-Workflow und der Updates-Tab lesen beide nur den Abschnitt
    der aktuellen Version aus CHANGELOG.md — der muss das Archivieren
    unverändert überstehen."""
    from src.version import VERSION

    changelog = _real_changelog()
    new_changelog, _, _ = arch.archive(changelog, _real_archive(), arch.KEEP_RELEASES)
    assert notes.body_for(new_changelog, VERSION) == notes.body_for(changelog, VERSION)
    assert extract_version_section(new_changelog, VERSION) is not None
