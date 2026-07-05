"""Gemeinsamer Fehler-Klassifikator für die Mail-Versand-Kerne (Audit M10).

send_task/share_task teilen sich diese Zuordnung einer Versand-Exception auf
ein Result-Dict. Export nutzt sie NICHT (kein Netz-Pfad).
"""

import traceback

from src.mail import is_offline_error


def classify_mail_error(e):
    """Mappt eine beim Mailversand aufgetretene Exception auf ein
    Fehler-Result-Dict:

    - FileNotFoundError -> kind "filenotfound" (fehlende credentials.json,
      erwartet; kein Traceback).
    - is_offline_error  -> kind "offline" (kein Netz; kein Traceback).
    - sonst             -> kind "error" mit Traceback.

    Muss aus einem aktiven `except`-Block gerufen werden — der error-Fall
    liest den aktuellen Traceback über traceback.format_exc()."""
    if isinstance(e, FileNotFoundError):
        return {"ok": False, "kind": "filenotfound", "error": e, "tb": None}
    if is_offline_error(e):
        return {"ok": False, "kind": "offline", "error": e, "tb": None}
    return {"ok": False, "kind": "error", "error": e, "tb": traceback.format_exc()}
