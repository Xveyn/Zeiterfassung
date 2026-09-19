"""Schutztest für Pixelkonstanten im Layout.

Die UI-Skalierung läuft über **einen** Hebel: `theme.fonts.init_fonts` setzt
die Punktgrößen aller benannten Fonts auf `basis × faktor`. Daraus folgt eine
Regel, an der jede Layout-Angabe hängt:

    Was in Zeichen oder Zeilen angegeben ist, skaliert mit.
    Was in Pixeln angegeben ist, steht still.

`Entry(width=35)` zählt Zeichen und wächst mit der Schrift; `wraplength=380`
zählt Pixel und bleibt, was es ist. Ein Hinweistext mit fester Umbruchbreite
bricht bei doppelter Schrift in doppelt so viele Zeilen um — der Dialog wird
höher, aber keinen Pixel breiter. Bei den themed Meldungsdialogen bestimmt
dieser Text die ganze Dialogbreite, die damit komplett einfriert.

Die Fehlerklasse ist wiederkehrend, nicht einmalig: Xveyn#133 war derselbe
Fehler mit einem festen `padx=120` neben einem in Zeichen bemessenen Feld.
Deshalb ein Test und kein Kommentar.

Geprüft werden die Tk-Optionen, die **eindeutig** Pixel zählen — bei `width`/
`height` entscheidet die Widget-Klasse (Entry: Zeichen, Canvas: Pixel), das
wäre aus dem AST heraus geraten. Sie müssen über `theme.fonts.px()` laufen,
das den beim Start gemerkten Faktor anwendet.

Muster wie `tests/test_catch_all_handlers.py` und
`tests/test_type_annotations.py`: dokumentierte Konvention als Assertion, läuft
in der bestehenden Matrix mit, reine stdlib.
"""

import ast
import pathlib

import pytest

from src.theme.fonts import px, scaled_px

REPO = pathlib.Path(__file__).resolve().parent.parent

# Tk-Optionen, die IMMER Pixel zählen — unabhängig von der Widget-Klasse.
# `wraplength`: Umbruchbreite eines Labels. `length`: Länge einer ttk.Scale
# bzw. ttk.Progressbar.
PIXEL_OPTIONS = ("wraplength", "length")


def _source_files():
    return sorted(p for p in (REPO / "src").rglob("*.py"))


def _literal_pixel_args(tree):
    """(zeile, option, wert) für jedes `option=<Zahl>` aus PIXEL_OPTIONS."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg not in PIXEL_OPTIONS:
                continue
            if isinstance(kw.value, ast.Constant) and isinstance(
                    kw.value.value, (int, float)):
                found.append((kw.value.lineno, kw.arg, kw.value.value))
    return found


def test_pixel_options_go_through_px():
    """Keine literale Pixelangabe im Layout — sie überlebt die Skalierung nicht.

    Statt `wraplength=380` gehört dort `wraplength=px(380)` hin: derselbe Wert
    bei 100 %, mitwachsend darüber."""
    offenders = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, option, value in _literal_pixel_args(tree):
            rel = path.relative_to(REPO).as_posix()
            offenders.append(f"{rel}:{lineno}: {option}={value!r}")
    assert not offenders, (
        "Pixelangaben ohne px() — sie frieren die Breite bei geänderter "
        "UI-Skalierung ein:\n  " + "\n  ".join(offenders))


@pytest.mark.parametrize("value,scale,expected", [
    (380, 1.0, 380),
    (380, 2.0, 760),
    (380, 0.75, 285),
    (16, 1.5, 24),
    # Halbe Pixel gibt es nicht: kaufmännisch runden, nicht abschneiden.
    (15, 1.5, 22),
    (0, 2.0, 0),
])
def test_scaled_px(value, scale, expected):
    assert scaled_px(value, scale) == expected


def test_scaled_px_keeps_hairlines_visible():
    """Eine 1-px-Trennlinie darf beim Herunterskalieren nicht verschwinden —
    `round(1 * 0.75)` wäre 1, `round(1 * 0.4)` aber 0 und damit unsichtbar."""
    assert scaled_px(1, 0.75) == 1
    assert scaled_px(1, 0.4) == 1


def test_px_uses_the_factor_from_init_fonts(monkeypatch):
    """`px` ist die Kurzform von `scaled_px` mit dem beim Start gemerkten
    Faktor — ohne `init_fonts` (Tests, Tk-freie Aufrufer) gilt 1.0."""
    from src.theme import fonts

    assert px(380) == 380
    monkeypatch.setattr(fonts, "_scale", 2.0)
    assert px(380) == 760
