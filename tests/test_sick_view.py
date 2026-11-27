from src.sick_days import SickBlock
from src.sick_view import block_label, cell_tooltip, delete_key, manager_rows
from src.theme import palette


def _block(frm, to, days):
    return SickBlock(date_from=frm, date_to=to, days=days)


def test_block_label_single_and_range():
    assert block_label(_block("2026-03-02", "2026-03-02", {"2026-03-02": 480})) \
        == "Krankheit 02.03.2026"
    assert block_label(_block("2026-03-02", "2026-03-06", {})) \
        == "Krankheit 02.03.2026 – 06.03.2026"
    assert delete_key(_block("2026-03-02", "2026-03-06", {})) == "sick:2026-03-02"


def test_cell_tooltip_without_hours_on_zero_day():
    b = _block("2026-03-02", "2026-03-08",
               {"2026-03-02": 480, "2026-03-07": 0})
    assert cell_tooltip("2026-03-07", b) == "Krank (02.03.2026 – 08.03.2026)"
    assert cell_tooltip("2026-03-02", b) == \
        "Krank (02.03.2026 – 08.03.2026)\n8 h"
    one = _block("2026-03-02", "2026-03-02", {"2026-03-02": 450})
    assert cell_tooltip("2026-03-02", one) == "Krank (02.03.2026)\n7 h 30 min"


def test_cell_tooltip_names_vacation_and_holiday():
    b = _block("2026-03-02", "2026-03-03", {"2026-03-02": 480, "2026-03-03": 0})
    assert cell_tooltip("2026-03-03", b, vacation_name="Ostern",
                        holiday="Feiertag X") == (
        "Krank (02.03.2026 – 03.03.2026)\nUrlaub: Ostern\nFeiertag: Feiertag X")


def test_manager_rows_newest_first():
    a = _block("2026-01-05", "2026-01-06", {"2026-01-05": 480, "2026-01-06": 480})
    b = _block("2026-03-02", "2026-03-02", {"2026-03-02": 450})
    assert manager_rows([a, b]) == [("02.03.2026", "7 h 30 min"),
                                    ("05.01.2026 – 06.01.2026", "16 h")]


def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(fg, bg):
    hi, lo = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_sick_bg_contrast_at_least_vacation():
    assert (_contrast(palette.TEXT, palette.SICK_BG)
            >= _contrast(palette.TEXT, palette.VACATION_BG))
