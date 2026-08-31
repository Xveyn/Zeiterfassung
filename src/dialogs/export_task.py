"""Worker-Kern des Export-Dialogs (Audit M10): Tk-frei, wirft nie.

Nur die (potenziell teure) PDF-Erzeugung — kein Netz. Der anschließende
'Speichern unter'-Dialog und der Datei-Write bleiben im on_done auf dem
UI-Thread (asksaveasfilename ist Tk-gebunden).
"""

import logging
import traceback

from src.report import generate_pdf

log = logging.getLogger(__name__)


def perform_export_pdf(*, date_from, date_to, entries, name, categories,
                       category_breakdown, vacation_days=None):
    try:
        pdf_bytes = generate_pdf(
            date_from, date_to, entries, name=name,
            categories=categories, category_breakdown=category_breakdown,
            vacation_days=vacation_days)
    except Exception as e:
        log.exception("PDF-Erzeugung fehlgeschlagen")
        return {"ok": False, "error": e, "tb": traceback.format_exc()}
    return {"ok": True, "pdf_bytes": pdf_bytes}
