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


def test_generate_pdf_keeps_the_summary_but_not_the_day_table_together():
    html = _pdf_html(_entries(5, ("Aream", "Intern")))
    assert html.count(KEEP) == 1, "genau ein Absatz: vor der Summentabelle"
    # Der Absatz steht unmittelbar vor der Tabelle, nicht irgendwo davor.
    assert report_mod._KEEP_WITH_NEXT + "<table" in html
    # Die Tagestabelle beginnt nach der Überschrift und darf teilen (Wochen können lang sein).
    day_table = html.index("<table")
    assert html.index(KEEP) > day_table


def test_generate_pdf_without_category_breakdown_has_no_keep_paragraph():
    html = _pdf_html(_entries(5, ("Aream", "Intern")), category_breakdown=False)
    assert KEEP not in html


def test_generate_pdf_with_vacation_keeps_both_summary_tables():
    html = _pdf_html(_entries(5, ("Aream", "Intern")),
                     vacation_days={"2026-10-12": 480, "2026-10-13": 480})
    assert html.count(KEEP) == 2
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
