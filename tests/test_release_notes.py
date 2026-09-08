"""Tests für scripts/release_notes.py.

Der Body eines echten Releases ist der kuratierte CHANGELOG.md-Abschnitt
(s. CLAUDE.md, „Release-Prozess"). Das Skript schneidet ihn heraus; der
Release-Workflow reicht ihn per `--notes-file` an `gh release create`.

Getestet wird die reine Textlogik plus ein Gegencheck gegen die echte
CHANGELOG.md. Das Skript liegt in `scripts/` und ist damit kein importierbares
Modul (`scripts` ist bewusst kein Package), wird also über seinen Pfad geladen
— Muster wie tests/test_readme_version.py.
"""

import importlib.util
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "release_notes.py"
_spec = importlib.util.spec_from_file_location("_release_notes", _SCRIPT)
notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(notes)


_CHANGELOG = """# Changelog

## 1.24.0 — 2026-09-20

### Hinzugefügt
- **Etwas Neues**: ausführlich beschrieben.

### Behoben
- **Etwas Altes**: repariert.

## 1.23.0 — 2026-09-08

### Hinzugefügt
- **Noch was**: von vorgestern.
"""


# --- body_for --------------------------------------------------------------

def test_body_enthaelt_den_abschnitt_der_version():
    body = notes.body_for(_CHANGELOG, "1.24.0")
    assert "### Hinzugefügt" in body
    assert "**Etwas Neues**: ausführlich beschrieben." in body


def test_body_laesst_die_versionsueberschrift_weg():
    # Der Release-Titel nennt die Version bereits („Zeiterfassung v1.24.0"),
    # das Datum zeigt GitHub selbst — die Überschrift stünde ein drittes Mal
    # auf derselben Seite.
    body = notes.body_for(_CHANGELOG, "1.24.0")
    assert "1.24.0" not in body
    assert "2026-09-20" not in body
    # Die Unterueberschriften des Abschnitts bleiben unangetastet — weg faellt
    # nur die eine `## <version>`-Zeile.
    assert body.startswith("### Hinzugefügt")
    assert "### Behoben" in body


def test_body_schneidet_vor_der_naechsten_version_ab():
    body = notes.body_for(_CHANGELOG, "1.24.0")
    assert "von vorgestern" not in body


def test_body_der_letzten_version_reicht_bis_zum_dateiende():
    body = notes.body_for(_CHANGELOG, "1.23.0")
    assert "von vorgestern" in body


def test_body_ist_none_wenn_die_version_fehlt():
    assert notes.body_for(_CHANGELOG, "9.9.9") is None


def test_body_ist_none_wenn_unter_der_ueberschrift_nichts_steht():
    # Eine Überschrift ohne Inhalt ergäbe ein Release mit leerem Body — für
    # den Leser nicht von einem Fehler zu unterscheiden. Also derselbe
    # Fehlerfall wie ein ganz fehlender Abschnitt.
    leer = "# Changelog\n\n## 1.24.0 — 2026-09-20\n\n## 1.23.0 — 2026-09-08\n\n- was\n"
    assert notes.body_for(leer, "1.24.0") is None


# --- Gegencheck gegen die echte Datei --------------------------------------

def test_die_echte_changelog_traegt_einen_abschnitt_zur_aktuellen_version():
    """Dieselbe Prüfung, die `--check` im Release-Workflow macht — nur schon
    hier, statt erst nach dem Merge nach master."""
    from src.version import VERSION

    text = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    body = notes.body_for(text, VERSION)
    assert body, (
        f"CHANGELOG.md hat keinen (oder einen leeren) Abschnitt '## {VERSION}'. "
        "Der Release-Workflow baut den Release-Body daraus und bricht sonst ab "
        "(s. CLAUDE.md, Abschnitt Release-Prozess)."
    )
