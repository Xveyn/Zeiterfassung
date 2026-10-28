"""Seitenumbruch im PDF-Bericht (#368): Summentabellen bleiben als Block zusammen.

`xhtml2pdf` teilt Tabellen zeilenweise und kennt kein `page-break-inside`. Eine Summentabelle
(Kategorie, Urlaub) konnte deshalb mit der Kopfzeile am Seitenende und den Zeilen auf der nächsten Seite
landen — der Bericht wirkte abgeschnitten. Ein unsichtbarer Absatz mit `-pdf-keep-with-next` vor der Tabelle
hält beides zusammen.

Zwei Arten von Test:
- **Struktur** (läuft überall): das HTML, das an `xhtml2pdf` geht, über den Fake aus `conftest` — die CI hat
  die Lib nicht.
- **Seitenumbruch** (nur mit echtem `xhtml2pdf` und `pdftotext`, sonst übersprungen): rendert wirklich und
  prüft, was auf der letzten Zeile einer Seite steht. Lokal ausführen, wenn am PDF-Layout gearbeitet wird.
"""

import datetime
import re
import shutil
import subprocess
from unittest.mock import patch

import pytest

from src import report as report_mod
from src.report import HTML_STYLE, PDF_STYLE, _build_category_summary, _build_vacation_summary
from tests.conftest import make_fake_xhtml2pdf

KEEP = "-pdf-keep-with-next:true"


def _entry(day_slots):
    return {"slots": day_slots, "modified_at": "2026-10-28T10:00:00Z", "device_id": "x", "deleted": False}


def _slot(kategorie="Aream", start="09:00", end="17:00", pause=30):
    return {"start": start, "end": end, "pause": pause, "kategorie": kategorie}


def _entries(count, categories=("Aream",)):
    """`count` Werktage ab 01.09.2026, reihum auf die Kategorien verteilt."""
    entries, day, index = {}, datetime.date(2026, 9, 1), 0
    while len(entries) < count:
        if day.weekday() < 5:
            entries[day.isoformat()] = _entry([_slot(categories[index % len(categories)])])
            index += 1
        day += datetime.timedelta(days=1)
    return entries


def _pdf_html(entries, vacation_days=None, **kwargs):
    captured = {}
    with patch.dict("sys.modules", {"xhtml2pdf": make_fake_xhtml2pdf(captured)}):
        report_mod.generate_pdf(datetime.date(2026, 9, 1), datetime.date(2026, 10, 31), entries,
                                vacation_days=vacation_days, **kwargs)
    return captured["html"]


# --- Struktur -------------------------------------------------------------------------------------------


def test_the_pdf_category_summary_is_kept_together_with_its_header():
    html = _build_category_summary(_entries(3, ("Aream", "Intern")), PDF_STYLE)
    assert html.startswith("<p"), "ein Absatz vor der Tabelle"
    assert KEEP in html.split("<table", 1)[0]
    assert html.count("<table") == 1


def test_the_mail_category_summary_stays_unchanged():
    html = _build_category_summary(_entries(3, ("Aream", "Intern")), HTML_STYLE)
    assert KEEP not in html
    assert html.startswith("<table")


def test_an_empty_category_summary_adds_no_keep_paragraph():
    assert _build_category_summary(_entries(3, ("",)), PDF_STYLE) == ""
    assert _build_category_summary({}, PDF_STYLE) == ""


def test_the_pdf_vacation_summary_is_kept_together_with_its_header():
    days = {"2026-10-12": 480, "2026-10-13": 480}
    html = _build_vacation_summary(days, 0, PDF_STYLE)
    assert KEEP in html.split("<table", 1)[0]
    assert KEEP not in _build_vacation_summary(days, 0, HTML_STYLE)


def test_no_vacation_block_means_no_keep_paragraph():
    assert _build_vacation_summary({}, 0, PDF_STYLE) == ""


def test_generate_pdf_keeps_the_summary_table_right_after_a_keep_paragraph():
    html = _pdf_html(_entries(5, ("Aream", "Intern")))      # 01.09.–07.09.: zwei Kalenderwochen (KW 36, 37)
    weeks = len(_day_tables(html))
    assert html.count(KEEP) == weeks + 1, "ein Absatz je Woche und einer vor der Summentabelle"
    # Der Absatz der Summentabelle steht unmittelbar vor ihr, nicht irgendwo davor.
    assert report_mod._KEEP_WITH_NEXT + "<table" in html
    assert html.rindex(KEEP) > html.rindex("Summe KW")


def test_generate_pdf_without_category_breakdown_keeps_only_the_weeks_together():
    html = _pdf_html(_entries(5, ("Aream", "Intern")), category_breakdown=False)
    assert html.count(KEEP) == len(_day_tables(html))


def test_generate_pdf_with_vacation_keeps_both_summary_tables():
    html = _pdf_html(_entries(5, ("Aream", "Intern")),
                     vacation_days={"2026-10-12": 480, "2026-10-13": 480})
    assert html.count(KEEP) == len(_day_tables(html)) + 2
    assert html.index("Urlaub</th>") > html.index("Kategorie</th>")


def test_the_mail_html_carries_no_pdf_only_markup():
    html, _ = report_mod.generate_report(datetime.date(2026, 9, 1), datetime.date(2026, 10, 31),
                                         _entries(5, ("Aream", "Intern")))
    assert "pdf-keep" not in html


# --- Seitenumbruch (echtes xhtml2pdf) -------------------------------------------------------------------

needs_renderer = pytest.mark.skipif(
    shutil.which("pdftotext") is None, reason="pdftotext fehlt")


def _render_pages(entries, tmp_path):
    pytest.importorskip("xhtml2pdf")
    pdf = report_mod.generate_pdf(datetime.date(2026, 9, 1), datetime.date(2026, 10, 31), entries)
    path = tmp_path / "bericht.pdf"
    path.write_bytes(pdf)
    text = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True,
                          check=True).stdout
    return [page for page in text.split("\f") if page.strip()]


def _edge_lines(pages):
    """(letzte Zeile einer Seite, erste Zeile der nächsten) je Seitenübergang."""
    def lines(page):
        return [line.strip() for line in page.splitlines() if line.strip()]
    return [(lines(pages[i])[-1], lines(pages[i + 1])[0]) for i in range(len(pages) - 1)]


def _is_category_header(line):
    return bool(re.match(r"Kategorie\s+Stunden", line))


@needs_renderer
@pytest.mark.parametrize("count", [8, 24, 38])
def test_a_category_summary_never_starts_with_its_header_alone_at_the_page_end(count, tmp_path):
    """8 Einträge: der gemeldete Fall (#368); 24 und 38 treffen die Seitengrenze ebenfalls."""
    pages = _render_pages(_entries(count), tmp_path)
    for last, _first in _edge_lines(pages):
        assert not _is_category_header(last), f"Kopfzeile allein am Seitenende bei {count} Einträgen"


@needs_renderer
def test_the_reported_report_keeps_its_summary_on_one_page(tmp_path):
    """Die Daten aus Zeiterfassung_20261001_20261031.pdf: acht Einträge, eine Kategorie."""
    days = {"2026-10-15": ("09:30", "17:00"), "2026-10-16": ("10:00", "17:30"),
            "2026-10-19": ("09:30", "17:00"), "2026-10-20": ("09:45", "17:15"),
            "2026-10-21": ("09:30", "16:00"), "2026-10-26": ("09:45", "17:15"),
            "2026-10-27": ("09:50", "17:20"), "2026-10-28": ("09:10", "15:40")}
    entries = {day: _entry([_slot(start=s, end=e)]) for day, (s, e) in days.items()}
    pages = _render_pages(entries, tmp_path)
    summary_pages = [i for i, page in enumerate(pages) if "Aream" in page and re.search(r"Kategorie\s+Stunden", page)]
    data_pages = [i for i, page in enumerate(pages) if re.search(r"Aream\s+54\.0h", page)]
    assert summary_pages and summary_pages == data_pages, "Kopfzeile und Datenzeile stehen auf derselben Seite"


# --- Wochenblöcke (#370) --------------------------------------------------------------------------------
# Die Tagestabelle besteht im PDF aus einer Tabelle je Kalenderwoche, damit KW-Kopf, Tage und Wochensumme
# nicht an einer Seitengrenze auseinanderfallen. Das Mail-HTML bleibt eine Tabelle.


def _day_tables(html):
    """Die Tabellen der Tagestabelle: alle `<table>` bis auf die Summentabellen."""
    tables = re.findall(r"<table.*?</table>", html, re.S)
    return [t for t in tables if "Summe KW" in t or "Datum</th>" in t]


def test_the_pdf_has_one_day_table_per_calendar_week():
    html = _pdf_html(_entries(11, ("Aream", "Intern")))     # 01.09.–15.09.: drei Kalenderwochen
    tables = _day_tables(html)
    assert len(tables) == 3
    assert [t.count("Summe KW") for t in tables] == [1, 1, 1], "jede Woche trägt ihre eigene Summe"


def test_the_column_header_stands_only_in_the_first_week_table():
    tables = _day_tables(_pdf_html(_entries(11)))
    assert "Datum</th>" in tables[0]
    assert all("Datum</th>" not in t for t in tables[1:])


def test_the_grand_total_stands_in_the_last_week_table_only():
    tables = _day_tables(_pdf_html(_entries(11)))
    assert "Gesamt" in tables[-1]
    assert all("Gesamt" not in t for t in tables[:-1])


def test_every_week_table_is_kept_together_with_a_keep_paragraph():
    html = _pdf_html(_entries(11))
    for table in _day_tables(html):
        at = html.index(table)
        assert html[:at].endswith(report_mod._KEEP_WITH_NEXT), "der Absatz steht unmittelbar vor der Woche"


def test_the_week_tables_carry_the_same_column_widths_as_the_old_single_table():
    tables = _day_tables(_pdf_html(_entries(11)))
    for table in tables:
        assert "width:15%" in table and "width:25%" in table, "feste Spaltenbreiten an jeder Zelle"


def test_the_mail_html_keeps_a_single_day_table():
    html, _ = report_mod.generate_report(datetime.date(2026, 9, 1), datetime.date(2026, 10, 31),
                                         _entries(11))
    assert len(_day_tables(html)) == 1
    assert html.count("Summe KW") == 3


def test_the_total_does_not_depend_on_how_the_table_is_split():
    entries = _entries(11)
    _html, total = report_mod.generate_report(datetime.date(2026, 9, 1), datetime.date(2026, 10, 31), entries)
    assert f"{total}h" in _pdf_html(entries)


def _is_edge_orphan(last, first):
    """Eine lose Zeile an der Seitengrenze: KW-Kopf/Tabellenkopf unten, Wochen- oder Gesamtsumme oben."""
    if re.match(r"(KW \d+|Datum\s+Tag)", last):
        return "KW-Kopf oder Tabellenkopf allein am Seitenende"
    if re.match(r"(Summe KW|Gesamt)", first):
        return "Summe KW oder Gesamt allein am Seitenanfang"
    return None


@needs_renderer
@pytest.mark.parametrize("count", [10, 11, 25, 40, 41, 45])
@pytest.mark.parametrize("categories", [("Aream",), ("Aream", "Intern", "Support")])
def test_no_loose_row_at_a_page_boundary(count, categories, tmp_path):
    """Die Eintragsmengen, bei denen die Seitengrenze vor #370 eine lose Zeile erzeugte."""
    pages = _render_pages(_entries(count, categories), tmp_path)
    for last, first in _edge_lines(pages):
        assert _is_edge_orphan(last, first) is None, (
            f"{_is_edge_orphan(last, first)} bei {count} Einträgen / {len(categories)} Kategorien: "
            f"{last!r} | {first!r}")


@needs_renderer
def test_a_week_longer_than_one_page_still_renders_and_may_split(tmp_path):
    """Ein Wochenblock, der nicht auf eine Seite passt, darf sich teilen — kein Fehler, keine Endlosschleife."""
    many = {"2026-09-02": _entry([_slot(start=f"{h:02d}:00", end=f"{h:02d}:30", pause=0) for h in range(0, 24)] * 3)}
    pages = _render_pages(many, tmp_path)
    assert len(pages) >= 2
    assert "Summe KW" in "".join(pages)
