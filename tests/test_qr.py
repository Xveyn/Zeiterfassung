# tests/test_qr.py
import pytest

from src import qr

LINK = "https://xveyn.github.io/Zeiterfassung/#pair=192.168.178.20:17654:K7M29QXA"


def test_the_matrix_is_square_and_boolean():
    matrix = qr.qr_matrix(LINK)

    size = len(matrix)
    assert size >= 21 and all(len(row) == size for row in matrix)
    assert all(isinstance(cell, bool) for row in matrix for cell in row)
    assert (size - 17) % 4 == 0                         # Version n hat 4n + 17 Module


def test_the_link_fits_into_a_small_version():
    # Version 4 bis 6 (33 bis 41 Module): größer wäre mit dem Handy schwer zu scannen.
    assert 33 <= len(qr.qr_matrix(LINK)) <= 41


def test_the_three_finder_patterns_are_there():
    matrix = qr.qr_matrix(LINK)
    size = len(matrix)

    def finder(top, left):
        return [row[left:left + 7] for row in matrix[top:top + 7]]

    expected = [
        [True] * 7,
        [True] + [False] * 5 + [True],
        [True, False, True, True, True, False, True],
        [True, False, True, True, True, False, True],
        [True, False, True, True, True, False, True],
        [True] + [False] * 5 + [True],
        [True] * 7,
    ]
    assert finder(0, 0) == expected
    assert finder(0, size - 7) == expected
    assert finder(size - 7, 0) == expected


def test_the_matrix_is_deterministic_and_depends_on_the_text():
    assert qr.qr_matrix(LINK) == qr.qr_matrix(LINK)
    assert qr.qr_matrix(LINK) != qr.qr_matrix(LINK.replace("K7M29QXA", "K7M29QXB"))


def test_too_long_a_text_raises_qr_too_long():
    with pytest.raises(qr.QrTooLong):
        qr.qr_matrix("x" * 5000)


def test_the_canvas_size_includes_the_quiet_zone():
    assert qr.canvas_size(33, 6) == (33 + 2 * qr.QUIET_MODULES) * 6
    assert qr.canvas_size(33, 1) == 41 and qr.QUIET_MODULES == 4


def test_dark_rects_cover_exactly_the_dark_modules():
    matrix = qr.qr_matrix(LINK)
    scale = 3

    painted = set()
    for x0, y0, x1, y1 in qr.dark_rects(matrix, scale):
        assert (y1 - y0) == scale and (x1 - x0) % scale == 0
        for x in range(x0, x1, scale):
            assert (x, y0) not in painted                 # kein Modul doppelt
            painted.add((x, y0))

    offset = qr.QUIET_MODULES * scale
    expected = {(offset + col * scale, offset + row * scale)
                for row, cells in enumerate(matrix) for col, dark in enumerate(cells) if dark}
    assert painted == expected


def test_dark_rects_merge_horizontal_runs():
    matrix = [[True, True, False, True], [False, False, False, False],
              [True, False, True, True], [False, True, True, False]]

    rects = qr.dark_rects(matrix, 2)

    offset = qr.QUIET_MODULES * 2
    assert rects[0] == (offset, offset, offset + 4, offset + 2)         # zwei Module in einem Lauf
    assert (offset + 6, offset, offset + 8, offset + 2) in rects           # das einzelne letzte
    assert len(rects) == 5


def test_an_empty_matrix_has_no_rects():
    assert qr.dark_rects([], 4) == []
    assert qr.dark_rects([[False, False]], 4) == []
