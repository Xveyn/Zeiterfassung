"""Tests für scripts/resolve_readme_version.py.

Die README markiert noch nicht veröffentlichte Zeilen mit `*(ab --VERSION--)*`
(s. CLAUDE.md, „README-Zeilen für Unveröffentlichtes markieren"). Der
Platzhalter wird im Release-PR gegen die Version aus `src/version.py`
aufgelöst; ein CI-Job hält PRs mit `release:*`-Label an, solange noch einer
drinsteht.

Getestet wird nur die reine Textlogik — kein Dateizugriff, kein git. Das
Skript liegt in `scripts/` und ist damit kein importierbares Modul (`scripts`
ist bewusst kein Package), wird also über seinen Pfad geladen. Der Pfad wird
vom Ort DIESER Datei abgeleitet, nicht vom Arbeitsverzeichnis, damit der Test
unabhängig davon läuft, von wo pytest gestartet wurde.
"""

import importlib.util
import pathlib

_SCRIPT = (pathlib.Path(__file__).resolve().parent.parent
           / "scripts" / "resolve_readme_version.py")
_spec = importlib.util.spec_from_file_location("_resolve_readme_version", _SCRIPT)
resolver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resolver)


# --- resolve ---------------------------------------------------------------

def test_resolve_ersetzt_den_platzhalter_durch_die_version():
    text = "- **Urlaub** *(ab --VERSION--)* — Zeiträume eintragen\n"
    out, count = resolver.resolve(text, "1.24.0")
    assert out == "- **Urlaub** *(ab 1.24.0)* — Zeiträume eintragen\n"
    assert count == 1


def test_resolve_ersetzt_alle_vorkommen():
    text = "a *(ab --VERSION--)* b *(ab --VERSION--)* c --VERSION--\n"
    out, count = resolver.resolve(text, "2.0.0")
    assert "--VERSION--" not in out
    assert count == 3


def test_resolve_laesst_text_ohne_platzhalter_unveraendert():
    text = "- **Urlaub** *(ab 1.22.0)* — schon veröffentlicht\n"
    out, count = resolver.resolve(text, "1.24.0")
    assert out == text
    assert count == 0


def test_resolve_fasst_aehnlich_aussehende_tokens_nicht_an():
    # Weder Kleinschreibung noch Plural noch einfache Bindestriche sind der
    # Platzhalter — sonst zerschriebe ein Lauf beliebige README-Prosa.
    text = "--version-- --VERSIONS-- -VERSION- VERSION --VERSION\n"
    out, count = resolver.resolve(text, "1.24.0")
    assert out == text
    assert count == 0


# --- find_unresolved -------------------------------------------------------

def test_find_unresolved_meldet_zeilennummern_eins_basiert():
    text = "erste Zeile\nzweite *(ab --VERSION--)*\ndritte\nvierte --VERSION--\n"
    assert resolver.find_unresolved(text) == [2, 4]


def test_find_unresolved_ist_leer_wenn_nichts_offen_ist():
    assert resolver.find_unresolved("nichts hier\n") == []
