import datetime
from unittest.mock import patch, MagicMock

from src.report import generate_report


def _e(start, end, pause=0, kategorie=""):
    """Eintrag mit genau einem Slot."""
    return {"slots": [{"start": start, "end": end, "pause": pause, "kategorie": kategorie}]}


# geteilte Ist-Zeit-Factory + xhtml2pdf-Fake (Audit N22)
from tests.conftest import ist_slot as _slot, make_fake_xhtml2pdf


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


def test_category_summary_suppressed_when_only_uncategorized():
    """Sind alle Slots ohne Kategorie, ist die Kategorie-Summentabelle
    bedeutungslos (nur eine Zeile = Gesamtsumme) und wird weggelassen."""
    entries = {"2026-03-23": _e("08:00", "16:00")}  # kategorie ""
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "(ohne Kategorie)" not in html


def test_category_summary_shown_when_mixed():
    """Sobald mindestens eine echte Kategorie existiert, erscheint die Tabelle
    inklusive der (ohne Kategorie)-Zeile für die unkategorisierten Slots."""
    entries = {"2026-03-23": {"slots": [_slot("08:00", "12:00", 0, "Büro"),
                                         _slot("13:00", "17:00", 0, "")]}}
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "(ohne Kategorie)" in html
    assert "Büro" in html


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


def test_slot_start_end_are_escaped():
    """start/end sind normalerweise auf [0-9:.-] validiert, aber der Drive-Sync
    schreibt Remote-Slots ungeprüft in den Storage (Audit M7). Ein
    manipuliertes Sync-Doc darf kein rohes HTML in Mail/PDF einschleusen."""
    entries = {"2026-03-23": _e("<script>alert(1)</script>", "16<b>:00</b>")}
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "16&lt;b&gt;:00&lt;/b&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "<b>:00</b>" not in html


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

    with patch.dict("sys.modules", {"xhtml2pdf": make_fake_xhtml2pdf(captured_html)}):
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

    with patch.dict("sys.modules", {"xhtml2pdf": make_fake_xhtml2pdf(captured_html)}):
        report_mod.generate_pdf(
            datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, categories={"Büro"})

    assert "Büro" in captured_html["html"]
    assert "HO" not in captured_html["html"]


def test_category_breakdown_default_includes_summary():
    """Default (category_breakdown nicht gesetzt) = aufgeschlüsselt: 'Büro'
    erscheint zweimal — in der Tageszeile UND in der Kategorie-Summentabelle."""
    entries = {"2026-03-23": _e("08:00", "16:00", 0, "Büro")}
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert html.count("Büro") == 2


def test_category_breakdown_false_hides_summary_keeps_total():
    """category_breakdown=False lässt die 'Summe je Kategorie'-Tabelle weg;
    die Tagestabelle inkl. Gesamt bleibt unverändert."""
    entries = {"2026-03-23": _e("08:00", "16:00", 0, "Büro")}
    html, total = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries,
        category_breakdown=False)
    # Tagestabelle + Gesamt bleiben
    assert "23.03.2026" in html
    assert "Gesamt" in html
    assert "8.0h" in html
    assert total == 8.0
    # 'Büro' nur noch in der Tageszeile, nicht mehr in einer Summentabelle
    assert html.count("Büro") == 1


def test_pdf_category_breakdown_false_hides_summary():
    """generate_pdf respektiert category_breakdown=False."""
    from src import report as report_mod
    entries = {"2026-03-23": _e("08:00", "16:00", 0, "Büro")}
    captured_html = {}

    with patch.dict("sys.modules", {"xhtml2pdf": make_fake_xhtml2pdf(captured_html)}):
        report_mod.generate_pdf(
            datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries,
            category_breakdown=False)

    html = captured_html["html"]
    assert html.count("Büro") == 1
    assert "Gesamt" in html


def test_pdf_table_defines_explicit_column_widths():
    """xhtml2pdf berechnet Spaltenbreiten nicht wie ein Browser und kollabiert
    bei width:100%-Tabellen mit colspan-Zeilen die linken Spalten ineinander.
    Die Breiten (Summe 100%) müssen daher an *jeder* regulären 6-Spalten-Zelle
    stehen — am Header UND an den Datenzeilen, sonst greift der Workaround
    wegen der SPAN-Zeilen nicht."""
    from src import report as report_mod
    entries = {"2026-03-23": _e("08:00", "16:00")}
    captured_html = {}

    with patch.dict("sys.modules", {"xhtml2pdf": make_fake_xhtml2pdf(captured_html)}):
        report_mod.generate_pdf(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)

    html = captured_html["html"]
    widths = ["15%", "8%", "25%", "16%", "16%", "20%"]
    assert sum(int(w.rstrip("%")) for w in widths) == 100
    for w in set(widths):
        assert f"width:{w};" in html
    # nicht nur am Header: die Datumsspalte (15%) taucht auch in der Datenzeile auf
    assert html.count("width:15%;") >= 2


def test_email_html_has_no_column_widths():
    """Die E-Mail-HTML-Tabelle bleibt ohne feste Spaltenbreiten (Browser
    layouten selbst) — der xhtml2pdf-Workaround darf nur das PDF betreffen.
    (width:100% am <table> ist erlaubt, nur die Spaltenbreiten dürfen fehlen.)"""
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    for w in ["15%", "8%", "25%", "16%", "20%"]:
        assert f"width:{w};" not in html


from src.report import total_hours


def test_total_hours_basic():
    entries = {"2026-03-23": _e("08:00", "16:00", 0)}
    assert total_hours(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries) == 8.0


def test_total_hours_sums_slots_and_days():
    entries = {
        "2026-03-23": {"slots": [_slot("08:00", "12:00", 0, "Büro"), _slot("13:00", "17:00", 30, "HO")]},
        "2026-03-24": _e("09:00", "17:00", 60),
    }
    # 4 + 3.5 + 7 = 14.5
    assert total_hours(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries) == 14.5


def test_total_hours_category_filter():
    entries = {"2026-03-23": {"slots": [_slot("08:00", "12:00", 0, "Büro"), _slot("13:00", "17:00", 0, "HO")]}}
    assert total_hours(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, categories={"Büro"}) == 4.0


def test_total_hours_none_categories_is_all():
    entries = {"2026-03-23": {"slots": [_slot("08:00", "12:00", 0, "A"), _slot("13:00", "17:00", 0, "B")]}}
    assert total_hours(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries) == 8.0


def test_total_hours_empty_range_is_zero():
    entries = {"2026-03-23": _e("08:00", "16:00", 0)}
    assert total_hours(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31), entries) == 0.0


def test_total_hours_filtered_to_nothing_is_zero():
    entries = {"2026-03-23": _e("08:00", "16:00", 0, "Büro")}
    assert total_hours(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, categories={"X"}) == 0.0


def test_default_pdf_filename_format():
    from src.report import default_pdf_filename
    assert default_pdf_filename(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31)
    ) == "Zeiterfassung_20260301_20260331.pdf"


def test_generate_pdf_returns_none_for_empty_range():
    from src import report as report_mod
    fake_xhtml2pdf = MagicMock()
    with patch.dict("sys.modules", {"xhtml2pdf": fake_xhtml2pdf}):
        result = report_mod.generate_pdf(
            datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), {})
    assert result is None


# --- Tests für die öffentlichen Filter-Funktionen (Task 3) ---

from src.report import filter_categories, filter_period


def test_filter_period_public_name_keeps_range_only():
    entries = {
        "2026-06-30": {"slots": [_slot("08:00", "16:00")]},
        "2026-07-01": {"slots": [_slot("08:00", "16:00")]},
        "2026-08-01": {"slots": [_slot("08:00", "16:00")]},
    }
    got = filter_period(datetime.date(2026, 7, 1), datetime.date(2026, 7, 31), entries)
    assert list(got) == ["2026-07-01"]


def test_filter_period_returns_none_when_empty():
    assert filter_period(
        datetime.date(2026, 7, 1), datetime.date(2026, 7, 31), {}) is None


def test_filter_categories_none_returns_same_object():
    entries = {"2026-07-01": {"slots": [_slot("08:00", "16:00")]}}
    assert filter_categories(entries, None) is entries


def test_filter_categories_drops_days_without_matching_slots():
    entries = {
        "2026-07-01": {"slots": [_slot("08:00", "16:00", kategorie="A")]},
        "2026-07-02": {"slots": [_slot("08:00", "16:00", kategorie="B")]},
    }
    got = filter_categories(entries, ["A"])
    assert list(got) == ["2026-07-01"]


# --- Task 7: Summen über Minuten, nicht Dezimalstunden ---


def test_total_sums_minutes_not_decimal_hours():
    """Drei 5-Minuten-Slots: je 0,08 h gerundet. Über Dezimalstunden ergibt
    das 0,24 h, über Minuten 3 × 5 min = 15 min = 0,25 h. CLAUDE.md schreibt
    den Minuten-Weg vor — er ist auch der ehrliche: der Nutzer hat 15 Minuten
    gearbeitet."""
    entries = {"2026-07-01": {"slots": [
        _slot("08:00", "08:05"), _slot("09:00", "09:05"),
        _slot("10:00", "10:05"),
    ]}}
    _, total = generate_report(
        datetime.date(2026, 7, 1), datetime.date(2026, 7, 31), entries)
    assert total == 0.25


def test_week_and_grand_total_agree_over_minutes():
    """Wochensumme und Gesamt entstehen aus derselben Minutenrechnung."""
    entries = {
        "2026-07-01": {"slots": [_slot("08:00", "08:05")]},
        "2026-07-02": {"slots": [_slot("08:00", "08:05")]},
    }
    html, total = generate_report(
        datetime.date(2026, 7, 1), datetime.date(2026, 7, 31), entries)
    assert total == 0.17          # 10 min
    assert "0.17h" in html


def test_total_hours_preview_matches_the_report():
    """Die Live-Vorschau im period_picker muss dieselbe Zahl nennen wie der
    Bericht — sonst widersprechen sich Dialog und Ausgabe."""
    entries = {"2026-07-01": {"slots": [
        _slot("08:00", "08:05"), _slot("09:00", "09:05"),
        _slot("10:00", "10:05"),
    ]}}
    _, report_total = generate_report(
        datetime.date(2026, 7, 1), datetime.date(2026, 7, 31), entries)
    assert total_hours(
        datetime.date(2026, 7, 1), datetime.date(2026, 7, 31),
        entries) == report_total
