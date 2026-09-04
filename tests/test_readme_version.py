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


def test_resolve_ersetzt_alle_marker():
    text = "a *(ab --VERSION--)* b *(ab --VERSION--)* c\n"
    out, count = resolver.resolve(text, "2.0.0")
    assert out == "a *(ab 2.0.0)* b *(ab 2.0.0)* c\n"
    assert count == 2


def test_resolve_laesst_das_blanke_token_im_fliesstext_stehen():
    # Die README erklärt den Platzhalter unter „Features" selbst — dort steht
    # `--VERSION--` in Prosa, nicht als Marker. Nähme ein Lauf ihn mit, stünde
    # die Legende danach dauerhaft falsch da („statt einer Zahl `1.23.0`"),
    # und keine spätere Auflösung könnte das zurückdrehen: ein Platzhalter,
    # den man auflöst, ist danach keiner mehr.
    text = "Steht dort statt einer Zahl `--VERSION--`, ist es fertig.\n"
    out, count = resolver.resolve(text, "1.24.0")
    assert out == text
    assert count == 0


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
    text = ("erste Zeile\nzweite *(ab --VERSION--)*\ndritte\n"
            "vierte *(ab --VERSION--)*\n")
    assert resolver.find_unresolved(text) == [2, 4]


def test_find_unresolved_ist_leer_wenn_nichts_offen_ist():
    assert resolver.find_unresolved("nichts hier\n") == []


def test_find_unresolved_meldet_das_blanke_token_nicht():
    # Sonst hielte der readme-version-Check jeden Release-PR an der Legende
    # auf — die trägt den Platzhalter per Definition dauerhaft.
    assert resolver.find_unresolved("Zahl `--VERSION--` heißt offen\n") == []


# --- find_markers ----------------------------------------------------------

def test_find_markers_liefert_die_versionen_in_reihenfolge():
    text = ("- **A** *(ab 1.22.0)* — eins\n"
            "- **B** *(ab 1.20.1)* — zwei, mitten im Satz *(ab 1.23.0)* auch\n")
    assert resolver.find_markers(text) == ["1.22.0", "1.20.1", "1.23.0"]


def test_find_markers_ignoriert_den_offenen_platzhalter():
    # `--VERSION--` ist keine Version — er wird aufgeloest, nicht entfernt.
    assert resolver.find_markers("- **A** *(ab --VERSION--)*\n") == []


# --- stale_versions --------------------------------------------------------

def test_stale_versions_meldet_marker_mit_genug_neueren_releases():
    releases = ["1.20.0", "1.21.0", "1.21.1", "1.22.0", "1.23.0", "1.24.0"]
    # 1.20.0 hat 5 neuere -> reif. 1.21.0 hat 4 -> bleibt.
    assert resolver.stale_versions(["1.20.0", "1.21.0"], releases, 5) == {"1.20.0"}


def test_stale_versions_zaehlt_pre_releases_nicht_mit():
    # Pre-Releases sind keine Releases — sonst raeumte ein einziger echter
    # Release mit vier Pres davor die Marker viel zu frueh weg.
    releases = ["1.20.0", "1.21.0", "1.21.0-pre.1", "1.21.0-pre.2",
                "1.21.0-pre.3", "1.21.0-pre.4", "1.21.0-pre.5"]
    assert resolver.stale_versions(["1.20.0"], releases, 5) == set()


def test_stale_versions_ignoriert_unparsbare_eintraege():
    assert resolver.stale_versions(["quatsch"], ["1.20.0", "1.21.0"], 1) == set()


# --- prune -----------------------------------------------------------------

def test_prune_entfernt_marker_am_fetten_namen_samt_leerzeichen():
    text = "- **Urlaub** *(ab 1.22.0)* — Zeiträume eintragen\n"
    out, count = resolver.prune(text, {"1.22.0"})
    assert out == "- **Urlaub** — Zeiträume eintragen\n"
    assert count == 1


def test_prune_entfernt_marker_auch_mitten_im_satz():
    text = "… lässt sich abschalten *(ab 1.23.0)* — der Zeitraum bleibt\n"
    out, count = resolver.prune(text, {"1.23.0"})
    assert out == "… lässt sich abschalten — der Zeitraum bleibt\n"
    assert count == 1


def test_prune_laesst_nicht_reife_marker_stehen():
    text = "- **A** *(ab 1.22.0)* — x\n- **B** *(ab 1.23.0)* — y\n"
    out, count = resolver.prune(text, {"1.22.0"})
    assert out == "- **A** — x\n- **B** *(ab 1.23.0)* — y\n"
    assert count == 1


def test_prune_fasst_den_offenen_platzhalter_nicht_an():
    text = "- **A** *(ab --VERSION--)* — noch offen\n"
    out, count = resolver.prune(text, {"1.22.0", "--VERSION--"})
    assert out == text
    assert count == 0
