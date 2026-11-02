"""Worker-Kern des Export-Dialogs (Audit M10): Tk-frei, wirft nie.

Nur die (potenziell teure) PDF-Erzeugung — kein Netz. Der anschließende
'Speichern unter'-Dialog und der Datei-Write bleiben im on_done auf dem
UI-Thread (asksaveasfilename ist Tk-gebunden).
"""

import logging
import time
import traceback

from src.report import generate_pdf

log = logging.getLogger(__name__)


def perform_export_pdf(*, date_from, date_to, entries, name, categories,
                       category_breakdown, vacation_days=None):
    started = time.monotonic()
    try:
        pdf_bytes = generate_pdf(
            date_from, date_to, entries, name=name,
            categories=categories, category_breakdown=category_breakdown,
            vacation_days=vacation_days)
    except Exception as e:
        log.exception("PDF-Erzeugung fehlgeschlagen")
        return {"ok": False, "error": e, "tb": traceback.format_exc()}
    # `generate_pdf` liefert `None`, wenn im Zeitraum nichts zu exportieren ist.
    if pdf_bytes is not None:
        log.info("PDF-Export erzeugt (%d KB) in %.1f s",
                 len(pdf_bytes) // 1024, time.monotonic() - started)
    return {"ok": True, "pdf_bytes": pdf_bytes}
