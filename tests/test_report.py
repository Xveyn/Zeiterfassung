import datetime
from src.report import generate_report

def test_empty_entries():
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), {})
    assert html is None
    assert total == 0

def test_single_entry():
    entries = {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30}
    }
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "23.03.2026" in html
    assert "Mo" in html
    assert "08:00" in html
    assert "16:30" in html
    assert "8.0h" in html
    assert "<table" in html
    # Dark mode styling
    assert "#0f172a" in html
    assert "#00D8A7" in html

def test_multiple_entries_sorted():
    entries = {
        "2026-03-25": {"start": "09:00", "end": "17:00", "pause": 30},
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    }
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    pos_23 = html.index("23.03.2026")
    pos_25 = html.index("25.03.2026")
    assert pos_23 < pos_25

def test_total_hours():
    entries = {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
        "2026-03-24": {"start": "09:00", "end": "17:00", "pause": 60},
    }
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "15.0h" in html
    assert total == 15.0

def test_filters_outside_range():
    entries = {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 0},
        "2026-04-01": {"start": "09:00", "end": "17:00", "pause": 0},
    }
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "23.03.2026" in html
    assert "01.04.2026" not in html

def test_legacy_entry_no_pause():
    entries = {
        "2026-03-23": {"start": "08:00", "end": "16:30"}
    }
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "8.5h" in html

def test_cross_month_range():
    entries = {
        "2026-02-20": {"start": "08:00", "end": "16:00", "pause": 0},
        "2026-03-05": {"start": "09:00", "end": "17:00", "pause": 0},
        "2026-03-20": {"start": "08:00", "end": "16:00", "pause": 0},
    }
    html, total = generate_report(datetime.date(2026, 2, 15), datetime.date(2026, 3, 14), entries)
    assert "20.02.2026" in html
    assert "05.03.2026" in html
    assert "20.03.2026" not in html

def test_inclusive_boundaries():
    entries = {
        "2026-03-01": {"start": "08:00", "end": "16:00", "pause": 0},
        "2026-03-15": {"start": "08:00", "end": "16:00", "pause": 0},
        "2026-03-16": {"start": "08:00", "end": "16:00", "pause": 0},
    }
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 15), entries)
    assert "01.03.2026" in html
    assert "15.03.2026" in html
    assert "16.03.2026" not in html

def test_alternating_row_colors():
    entries = {
        "2026-03-23": {"start": "08:00", "end": "16:00", "pause": 0},
        "2026-03-24": {"start": "08:00", "end": "16:00", "pause": 0},
    }
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "#1e293b" in html
    assert "#243347" in html

def test_greeting_content_closing_in_html():
    entries = {
        "2026-03-23": {"start": "08:00", "end": "16:00", "pause": 0}
    }
    html, total = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries,
        greeting="Hallo Welt,",
        content="hier die Zeiten für {zeitraum}.",
        closing="Grüße\nMax"
    )
    assert "Hallo Welt," in html
    assert "hier die Zeiten für 01.03.2026 – 31.03.2026." in html
    assert "Grüße" in html
    assert "Max" in html

def test_placeholders_replaced():
    entries = {
        "2026-03-23": {"start": "08:00", "end": "16:00", "pause": 0}
    }
    html, total = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries,
        content="Gesamt: {gesamt}"
    )
    assert "Gesamt: 8.0h" in html


def test_week_header_and_sum_present():
    entries = {
        "2026-03-23": {"start": "08:00", "end": "16:00", "pause": 0},
    }
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "KW 13" in html
    assert "Summe KW 13" in html
    assert "8.0h" in html


def test_multiple_weeks_each_have_header_and_sum():
    entries = {
        "2026-03-23": {"start": "08:00", "end": "16:00", "pause": 0},
        "2026-03-24": {"start": "09:00", "end": "17:00", "pause": 0},
        "2026-03-30": {"start": "08:00", "end": "17:00", "pause": 60},
    }
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "KW 13" in html
    assert "KW 14" in html
    assert "Summe KW 13" in html
    assert "Summe KW 14" in html
    pos_kw13 = html.index("KW 13")
    pos_kw14 = html.index("KW 14")
    assert pos_kw13 < pos_kw14


def test_week_sum_equals_sum_of_days():
    entries = {
        "2026-03-23": {"start": "08:00", "end": "16:00", "pause": 0},
        "2026-03-24": {"start": "09:00", "end": "17:00", "pause": 0},
    }
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "16.0h" in html
    assert total == 16.0


def test_iso_week_across_year_boundary():
    entries = {
        "2025-12-29": {"start": "08:00", "end": "16:00", "pause": 0},
    }
    html, total = generate_report(datetime.date(2025, 12, 1), datetime.date(2026, 1, 31), entries)
    assert "KW 1" in html


from unittest.mock import patch, MagicMock


# --- HTML-Escaping ---

def test_greeting_with_ampersand_is_escaped():
    entries = {"2026-03-23": {"start": "08:00", "end": "16:00", "pause": 0}}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries,
        greeting="Mayer & Söhne,",
    )
    assert "Mayer &amp; Söhne," in html
    assert "Mayer & Söhne" not in html


def test_greeting_with_html_tag_is_escaped():
    entries = {"2026-03-23": {"start": "08:00", "end": "16:00", "pause": 0}}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries,
        greeting="<script>alert(1)</script>",
    )
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_content_newline_becomes_br():
    entries = {"2026-03-23": {"start": "08:00", "end": "16:00", "pause": 0}}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries,
        content="Zeile1\nZeile2",
    )
    assert "Zeile1<br>Zeile2" in html


def test_closing_with_lt_and_newline_escaped_with_br():
    entries = {"2026-03-23": {"start": "08:00", "end": "16:00", "pause": 0}}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries,
        closing="A < B\nFreundlich",
    )
    # `<` muss escaped sein, `<br>` darf NICHT escaped sein
    assert "A &lt; B<br>Freundlich" in html
    assert "&lt;br&gt;" not in html


def test_placeholder_zeitraum_replaced_after_escape():
    entries = {"2026-03-23": {"start": "08:00", "end": "16:00", "pause": 0}}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries,
        content="Zeitraum: {zeitraum}",
    )
    assert "Zeitraum: 01.03.2026 – 31.03.2026" in html


def test_pdf_name_is_escaped():
    """generate_pdf escaped name vor der HTML-Generierung. xhtml2pdf wird
    gemockt, damit der Test ohne installierte Lib läuft (CI-kompatibel)."""
    from src import report as report_mod
    entries = {"2026-03-23": {"start": "08:00", "end": "16:00", "pause": 0}}

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
            datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries,
            name="Müller & Co",
        )

    assert "Müller &amp; Co" in captured_html["html"]
    assert "Müller & Co" not in captured_html["html"]
