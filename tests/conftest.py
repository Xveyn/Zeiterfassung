"""Gemeinsame Test-Helfer (Audit N22).

Vorher war die Ist-Zeit-Slot-Factory (`_slot`) 4× dupliziert (test_report/
test_storage/test_sync/test_weekly_limit) und der xhtml2pdf-Fake (`FakePisa`)
4× in test_report. Beide leben jetzt zentral hier.

Die Slot-Factory wird von den Aufrufern weiterhin auf ihren lokalen Namen
`_slot` aliast (`from tests.conftest import ist_slot as _slot`), damit die
vielen bestehenden Call-Sites unverändert bleiben. Reservierungs-Slots
(kategorie/gcal_event_id) und Sync-Einträge (modified_at/device_id) sind je
nur in einer Datei und bleiben dort lokal.
"""
from unittest.mock import MagicMock


def ist_slot(start, end, pause=0, kategorie=""):
    """Ein Ist-Zeit-Slot {start, end, pause, kategorie} für Storage-/Sync-/
    Report-/Weekly-Limit-Tests."""
    return {"start": start, "end": end, "pause": pause, "kategorie": kategorie}


def make_fake_xhtml2pdf(captured):
    """Fake für den lazy `xhtml2pdf`-Import in `report.generate_pdf` (die CI hat
    die Lib nicht). Liefert ein Mock-Modul, dessen `pisa.CreatePDF` das
    gerenderte HTML unter `captured['html']` ablegt und Erfolg (err=0) meldet.

    Nutzung:
        captured = {}
        with patch.dict("sys.modules", {"xhtml2pdf": make_fake_xhtml2pdf(captured)}):
            report.generate_pdf(...)
        assert "…" in captured["html"]
    """
    class _FakePisa:
        @staticmethod
        def CreatePDF(html_str, dest):
            captured["html"] = html_str
            return MagicMock(err=0)

    fake_mod = MagicMock()
    fake_mod.pisa = _FakePisa
    return fake_mod
