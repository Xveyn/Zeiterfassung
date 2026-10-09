# src/qr.py
"""QR-Code für den Koppel-Dialog (#221), Tk-frei.

`segno` (reines Python, BSD) liefert die Matrix; gezeichnet wird sie vom Dialog auf
einem Tk-`Canvas`. Hier liegt alles, was sich ohne Fenster prüfen lässt: die Matrix
selbst, die Maße samt Ruhezone und die Rechtecke, aus denen der Dialog sie malt.

`segno` wird **lazy** importiert (wie die Google-Wrapper): das Modul bleibt ohne die
Bibliothek importierbar, und die CI installiert sie nur dort, wo ein Test sie braucht.
"""
from __future__ import annotations

# Die Ruhezone des QR-Standards: vier Module weiße Fläche rundherum, unabhängig vom
# Dark-Theme des Dialogs — ohne sie scannt kein Handy.
QUIET_MODULES = 4


class QrTooLong(ValueError):
    """Der Text passt nicht in einen QR-Code (der Dialog zeigt dann nur Text)."""


def qr_matrix(text: str) -> list[list[bool]]:
    """Die Module des QR-Codes (`True` = dunkel), ohne Ruhezone. Fehlerkorrektur `M`,
    kein Micro-QR (Handy-Kameras lesen ihn schlecht)."""
    import segno
    try:
        code = segno.make(text, error="m", micro=False, boost_error=False)
    except segno.DataOverflowError as exc:
        raise QrTooLong(str(exc)) from None
    return [[bool(cell) for cell in row] for row in code.matrix]


def canvas_size(modules: int, module_px: int) -> int:
    """Kantenlänge der quadratischen Zeichenfläche in Pixeln, mit Ruhezone."""
    return (modules + 2 * QUIET_MODULES) * module_px


def dark_rects(matrix: list[list[bool]], module_px: int) -> list[tuple[int, int, int, int]]:
    """Die dunklen Module als Rechtecke `(x0, y0, x1, y1)` in Pixeln, Ruhezone
    eingerechnet. Benachbarte dunkle Module einer Zeile sind **ein** Rechteck: das hält
    die Zahl der Canvas-Items klein (eine Version-5-Matrix hat über 600 dunkle Module)."""
    offset = QUIET_MODULES * module_px
    rects: list[tuple[int, int, int, int]] = []
    for row_index, row in enumerate(matrix):
        y0 = offset + row_index * module_px
        col = 0
        while col < len(row):
            if not row[col]:
                col += 1
                continue
            start = col
            while col < len(row) and row[col]:
                col += 1
            rects.append((offset + start * module_px, y0,
                          offset + col * module_px, y0 + module_px))
    return rects
