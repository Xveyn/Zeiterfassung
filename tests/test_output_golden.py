"""Goldene Ausgaben ohne Häkchen „Krankheit ausweisen“ (`sick_days=None`).

Mail-HTML, PDF-HTML und Webhook-JSON eines Urlaubsberichts liegen byte-genau
unter `tests/fixtures/`. Ohne Häkchen müssen alle drei bitgleich zum Stand vor
der Krankheit bleiben; die Dateien halten diesen Stand fest. Weicht eine Ausgabe
ab, ist der Code falsch, nicht die Datei: nie neu erzeugen, um einen Test grün
zu bekommen.

Der Fall deckt ab, was die Urlaubs-Rechnung trägt: Zeitraum- und
Kategoriefilter (auch gegen die Kappung), zwei Urlaubsblöcke über ein
Wochenende hinweg, eine Kappungs-Fußnote über zwei Tage, einen 0-Minuten-Tag
mit Arbeitszeit, Notizen samt Aufschlüsselung und HTML-Escaping.
"""

import datetime
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src import report, webhook
from tests.conftest import ist_slot, make_fake_xhtml2pdf

FIXTURES = Path(__file__).parent / "fixtures"

DATE_FROM = datetime.date(2026, 9, 1)
DATE_TO = datetime.date(2026, 9, 30)


def _day(*slots):
    return {"slots": list(slots)}


def _noted(slot, note):
    return {**slot, "notiz": note}


ENTRIES = {
    "2026-08-31": _day(ist_slot("08:00", "16:00", 0, "A")),
    "2026-09-01": _day(ist_slot("08:00", "16:30", 30, "A")),
    "2026-09-02": _day(_noted(ist_slot("08:00", "12:00", 0, "A"), "Kunde Müller"),
                       ist_slot("13:00", "15:15", 0, "")),
    "2026-09-03": _day(ist_slot("09:00", "17:00", 30, "B")),
    "2026-09-08": _day(ist_slot("08:00", "12:00", 0, "A")),
    # Arbeitszeit nur in der abgewählten Kategorie: kappt den Urlaub nicht.
    "2026-09-09": _day(ist_slot("08:00", "16:00", 0, "B")),
    "2026-09-10": _day(ist_slot("14:00", "15:00", 0, "A"),
                       ist_slot("08:00", "09:30", 0, "A")),
    # Samstag im Urlaub (0 Minuten): Arbeitszeit bleibt, keine Kappung.
    "2026-09-12": _day(ist_slot("10:00", "12:00", 0, "A")),
    "2026-09-15": _day(ist_slot("07:45", "16:10", 45, "A")),
    "2026-09-28": _day(_noted(ist_slot("08:00", "12:00", 0, "A"), "Büro <Nord> & Süd")),
    "2026-10-01": _day(ist_slot("08:00", "16:00", 0, "A")),
}

VACATION = {
    "2026-08-31": 480,
    "2026-09-07": 480, "2026-09-08": 480, "2026-09-09": 480,
    "2026-09-10": 480, "2026-09-11": 480, "2026-09-12": 0, "2026-09-13": 0,
    "2026-09-14": 480,
    "2026-09-22": 450, "2026-09-23": 450,
    "2026-10-01": 480,
}

REPORT_KW = dict(categories={"A", ""}, category_breakdown=True,
                 vacation_days=VACATION, slot_order="chrono",
                 note_breakdown=True)

MAIL_KW = dict(greeting="Hallo,\nanbei {zeitraum}.",
               content="Gesamt: {gesamt} <b>fett</b>",
               closing="Viele Grüße\nMax Müller")


def mail_html(**extra):
    html, _ = report.generate_report(DATE_FROM, DATE_TO, ENTRIES,
                                     **MAIL_KW, **REPORT_KW, **extra)
    return html


def pdf_html(**extra):
    captured = {}
    with patch.dict("sys.modules", {"xhtml2pdf": make_fake_xhtml2pdf(captured)}):
        report.generate_pdf(DATE_FROM, DATE_TO, ENTRIES, name="Max Müller & Co",
                            **REPORT_KW, **extra)
    return captured["html"]


def webhook_json(**extra):
    payload = webhook.build_json_payload(
        date_from=DATE_FROM, date_to=DATE_TO, entries=ENTRIES,
        name="Max Müller", sender="max@example.com", categories=["A", ""],
        generated_at="2026-10-01T08:00:00Z", vacation_days=VACATION,
        slot_order="chrono", **extra)
    # Wie `send_task.perform_send` den Body baut: das sind die Bytes auf dem Draht.
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


GOLDEN = {
    "golden-report-mail.html": mail_html,
    "golden-report-pdf.html": pdf_html,
    "golden-webhook.json": webhook_json,
}


def _golden(name):
    # Text-Modus: ein Checkout mit CRLF (Windows) liest sich wie LF.
    text = (FIXTURES / name).read_text(encoding="utf-8")
    assert text.endswith("\n")
    return text[:-1]


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_output_without_sick_flag_matches_golden(name):
    assert GOLDEN[name]() == _golden(name)


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_explicit_none_matches_golden(name):
    assert GOLDEN[name](sick_days=None) == _golden(name)


@pytest.mark.parametrize("sick", [{}, {"2026-10-05": 480, "2026-08-03": 0}])
@pytest.mark.parametrize("name", ["golden-report-mail.html", "golden-report-pdf.html"])
def test_report_without_sick_day_in_range_matches_golden(name, sick):
    """Mit Häkchen, aber ohne Krankheitstag im Zeitraum: bitgleich zu ohne."""
    assert GOLDEN[name](sick_days=sick) == _golden(name)


def test_golden_covers_the_vacation_cases():
    """Hält fest, dass die Datei die Fälle trägt, für die sie da ist."""
    mail = _golden("golden-report-mail.html")
    assert mail.count(">Urlaub</th>") == 1
    assert "07.09.2026 – 14.09.2026" in mail
    assert "22.09.2026 – 23.09.2026" in mail
    assert "An 2 Tagen (08.09.2026, 10.09.2026) liegt Urlaub" in mail
    assert ">Kategorie</th>" in mail and "(ohne Notiz)" in mail
    assert "Zu vergüten gesamt" in mail
    assert "Krankheit" not in mail
    assert '"vacation": {' in _golden("golden-webhook.json")
