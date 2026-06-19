import datetime
from unittest.mock import patch, MagicMock

from src.report import generate_report


def _e(start, end, pause=0, kategorie=""):
    """Eintrag mit genau einem Slot."""
    return {"slots": [{"start": start, "end": end, "pause": pause, "kategorie": kategorie}]}


def _slot(start, end, pause=0, kategorie=""):
    return {"start": start, "end": end, "pause": pause, "kategorie": kategorie}


def test_empty_entries():
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), {})
    assert html is None
    assert total == 0


def test_single_entry():
    entries = {"2026-03-23": _e("08:00", "16:30", 30)}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "23.03.2026" in html
    assert "Mo" in html
    assert "08:00" in html
    assert "16:30" in html
    assert "8.0h" in html
    assert "<table" in html
    assert "#0f172a" in html
    assert "#00D8A7" in html


def test_kategorie_column_present():
    entries = {"2026-03-23": _e("08:00", "16:00", 0, "Büro")}
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "Kategorie" in html   # Spaltenkopf
    assert "Büro" in html        # Wert


def test_multiple_entries_sorted():
    entries = {"2026-03-25": _e("09:00", "17:00", 30), "2026-03-23": _e("08:00", "16:30", 30)}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert html.index("23.03.2026") < html.index("25.03.2026")


def test_total_hours():
    entries = {"2026-03-23": _e("08:00", "16:30", 30), "2026-03-24": _e("09:00", "17:00", 60)}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "15.0h" in html
    assert total == 15.0


def test_multi_slot_day_rows_and_subtotal():
    """Ein Tag mit zwei Slots: beide Slots als Zeilen + Tages-Subtotal."""
    entries = {"2026-03-23": {"slots": [
        _slot("08:00", "12:00", 0, "Büro"),
        _slot("13:00", "17:00", 0, "Homeoffice"),
    ]}}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "08:00" in html and "12:00" in html
    assert "13:00" in html and "17:00" in html
    assert "Büro" in html and "Homeoffice" in html
    assert "Summe 23.03.2026" in html   # Tages-Subtotal bei >1 Slot
    assert total == 8.0


def test_single_slot_day_has_no_subtotal():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "Summe 23.03.2026" not in html


def test_category_summary_block():
    entries = {
        "2026-03-23": {"slots": [_slot("08:00", "12:00", 0, "Büro"),
                                  _slot("13:00", "17:00", 0, "Homeoffice")]},
        "2026-03-24": _e("08:00", "12:00", 0, "Büro"),
    }
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    # Büro: 4h (Di) + 4h (Mo) = 8h; Homeoffice: 4h
    assert "Büro" in html
    assert "Homeoffice" in html
    assert "8.0h" in html
    assert "4.0h" in html


def test_category_summary_uncategorized_label():
    entries = {"2026-03-23": _e("08:00", "16:00")}  # kategorie ""
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "(ohne Kategorie)" in html


def test_category_filter_includes_only_selected():
    entries = {"2026-03-23": {"slots": [_slot("08:00", "12:00", 0, "Büro"),
                                         _slot("13:00", "17:00", 0, "Homeoffice")]}}
    html, total = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, categories={"Büro"})
    assert "Büro" in html
    assert "Homeoffice" not in html
    assert total == 4.0


def test_category_filter_uncategorized_via_empty_string():
    entries = {"2026-03-23": {"slots": [_slot("08:00", "12:00", 0, ""),
                                         _slot("13:00", "17:00", 0, "Büro")]}}
    html, total = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, categories={""})
    assert total == 4.0
    assert "Büro" not in html


def test_category_filter_empty_result_returns_none():
    entries = {"2026-03-23": _e("08:00", "16:00", 0, "Büro")}
    html, total = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, categories={"Nichtvorhanden"})
    assert html is None
    assert total == 0


def test_filters_outside_range():
    entries = {"2026-03-23": _e("08:00", "16:30"), "2026-04-01": _e("09:00", "17:00")}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "23.03.2026" in html
    assert "01.04.2026" not in html


def test_legacy_entry_no_pause():
    # Slot ohne pause-Key (Default 0)
    entries = {"2026-03-23": {"slots": [{"start": "08:00", "end": "16:30", "kategorie": ""}]}}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "8.5h" in html


def test_cross_month_range():
    entries = {
        "2026-02-20": _e("08:00", "16:00"), "2026-03-05": _e("09:00", "17:00"),
        "2026-03-20": _e("08:00", "16:00"),
    }
    html, total = generate_report(datetime.date(2026, 2, 15), datetime.date(2026, 3, 14), entries)
    assert "20.02.2026" in html
    assert "05.03.2026" in html
    assert "20.03.2026" not in html


def test_inclusive_boundaries():
    entries = {
        "2026-03-01": _e("08:00", "16:00"), "2026-03-15": _e("08:00", "16:00"),
        "2026-03-16": _e("08:00", "16:00"),
    }
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 15), entries)
    assert "01.03.2026" in html
    assert "15.03.2026" in html
    assert "16.03.2026" not in html


def test_alternating_row_colors():
    entries = {"2026-03-23": _e("08:00", "16:00"), "2026-03-24": _e("08:00", "16:00")}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "#1e293b" in html
    assert "#243347" in html


def test_greeting_content_closing_in_html():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, total = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries,
        greeting="Hallo Welt,", content="hier die Zeiten für {zeitraum}.", closing="Grüße\nMax")
    assert "Hallo Welt," in html
    assert "hier die Zeiten für 01.03.2026 – 31.03.2026." in html
    assert "Grüße" in html
    assert "Max" in html


def test_placeholders_replaced():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, total = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, content="Gesamt: {gesamt}")
    assert "Gesamt: 8.0h" in html


def test_week_header_and_sum_present():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "KW 13" in html
    assert "Summe KW 13" in html
    assert "8.0h" in html


def test_multiple_weeks_each_have_header_and_sum():
    entries = {
        "2026-03-23": _e("08:00", "16:00"), "2026-03-24": _e("09:00", "17:00"),
        "2026-03-30": _e("08:00", "17:00", 60),
    }
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "KW 13" in html
    assert "KW 14" in html
    assert "Summe KW 13" in html
    assert "Summe KW 14" in html
    assert html.index("KW 13") < html.index("KW 14")


def test_week_sum_equals_sum_of_days():
    entries = {"2026-03-23": _e("08:00", "16:00"), "2026-03-24": _e("09:00", "17:00")}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "16.0h" in html
    assert total == 16.0


def test_iso_week_across_year_boundary():
    entries = {"2025-12-29": _e("08:00", "16:00")}
    html, total = generate_report(datetime.date(2025, 12, 1), datetime.date(2026, 1, 31), entries)
    assert "KW 1" in html


# --- HTML-Escaping ---


def test_greeting_with_ampersand_is_escaped():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, greeting="Mayer & Söhne,")
    assert "Mayer &amp; Söhne," in html
    assert "Mayer & Söhne" not in html


def test_greeting_with_html_tag_is_escaped():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries,
        greeting="<script>alert(1)</script>")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_kategorie_is_escaped():
    """Kategorie ist freier Nutzertext und muss escaped werden."""
    entries = {"2026-03-23": _e("08:00", "16:00", 0, "Mayer & <b>Co</b>")}
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "Mayer &amp; &lt;b&gt;Co&lt;/b&gt;" in html
    assert "<b>Co</b>" not in html


def test_content_newline_becomes_br():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, content="Zeile1\nZeile2")
    assert "Zeile1<br>Zeile2" in html


def test_closing_with_lt_and_newline_escaped_with_br():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, closing="A < B\nFreundlich")
    assert "A &lt; B<br>Freundlich" in html
    assert "&lt;br&gt;" not in html


def test_placeholder_zeitraum_replaced_after_escape():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, content="Zeitraum: {zeitraum}")
    assert "Zeitraum: 01.03.2026 – 31.03.2026" in html


def test_pdf_name_is_escaped():
    """generate_pdf escaped name; xhtml2pdf wird gemockt (CI ohne Lib)."""
    from src import report as report_mod
    entries = {"2026-03-23": _e("08:00", "16:00")}
    captured_html = {}

    class FakePisa:
        @staticmethod
        def CreatePDF(html_str, dest):
            captured_html["html"] = html_str
            return MagicMock(err=0)

    fake_xhtml2pdf = MagicMock()
    fake_xhtml2pdf.pisa = FakePisa

    with patch.dict("sys.modules", {"xhtml2pdf": fake_xhtml2pdf}):
        report_mod.generate_pdf(
            datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, name="Müller & Co")

    assert "Müller &amp; Co" in captured_html["html"]
    assert "Müller & Co" not in captured_html["html"]


def test_pdf_category_filter_applied():
    """generate_pdf respektiert den categories-Filter."""
    from src import report as report_mod
    entries = {"2026-03-23": {"slots": [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Büro"},
                                         {"start": "13:00", "end": "17:00", "pause": 0, "kategorie": "HO"}]}}
    captured_html = {}

    class FakePisa:
        @staticmethod
        def CreatePDF(html_str, dest):
            captured_html["html"] = html_str
            return MagicMock(err=0)

    fake_xhtml2pdf = MagicMock()
    fake_xhtml2pdf.pisa = FakePisa

    with patch.dict("sys.modules", {"xhtml2pdf": fake_xhtml2pdf}):
        report_mod.generate_pdf(
            datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, categories={"Büro"})

    assert "Büro" in captured_html["html"]
    assert "HO" not in captured_html["html"]
