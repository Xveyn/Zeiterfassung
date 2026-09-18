"""Die Mail zum Teilen von Arbeitszeiten/Reservierungen (R10, Xveyn#123).

Betreff, HTML-Body und Dateiname des Anhangs — bis R10 inline im
Teilen-Dialog (`share_dialog.do_send`) zusammengebaut und damit per
Zuschnitt untestbar. Tk-frei, stdlib-only.

Hier liegt für den Teilen-Weg die dritte UTF-8-Pflicht aus CLAUDE.md („UTF-8
im Mail-Pipeline"): `<meta charset="utf-8">` im `<head>`. Die anderen beiden
bündelt `mime_message.build_message` für alle Mailwege; diese gehört zum
HTML-Erzeuger, weil `mime_message` das HTML nur entgegennimmt.
"""

import datetime
import html
from dataclasses import dataclass

from src.time_utils import format_date


@dataclass(frozen=True)
class ShareMessage:
    """Was der Teilen-Dialog verschickt.

    `what` („Arbeitszeiten", „Reservierungen" oder beides) nennt der Dialog
    nach dem Versand noch einmal in seiner Erfolgsmeldung."""

    subject: str
    html: str
    filename: str
    what: str


def build_share_message(*, include_entries: bool, include_reservations: bool,
                        name: str | None, sender_email: str | None,
                        date_from: datetime.date, date_to: datetime.date,
                        exported_at: str) -> ShareMessage:
    """Baut Betreff, HTML-Body und Dateinamen für ein Share-Doc.

    Der Absender heißt wie in den Einstellungen (`name`), ersatzweise wie
    seine Adresse, sonst „anonym". Im HTML wird er escapet — ein „&" oder
    „<" im Namen ergäbe sonst kaputtes Markup (`report.py` hält es genauso);
    der Betreff ist kein HTML und bleibt roh.

    `exported_at` ist der UTC-Zeitstempel des Share-Docs; sein Datum steht
    im Dateinamen des Anhangs.
    """
    parts = []
    if include_entries:
        parts.append("Arbeitszeiten")
    if include_reservations:
        parts.append("Reservierungen")
    what = " und ".join(parts)
    display_name = name or sender_email or "anonym"
    period = f"{format_date(date_from)} bis {format_date(date_to)}"
    body = (
        '<html><head><meta charset="utf-8"></head><body>'
        "<p>Hallo,</p>"
        f"<p>im Anhang findest Du meine {what} vom {period} "
        "als JSON-Datei.</p>"
        "<p>Du kannst die Datei in der Zeiterfassung-App über "
        "<em>Einstellungen → Daten importieren</em> einlesen. "
        "Vor dem Import kannst Du einen Zeitraum auswählen und je "
        "Datentyp festlegen, was bei Konflikten passieren soll.</p>"
        f"<p>Viele Grüße<br/>{html.escape(display_name)}</p>"
        "</body></html>"
    )
    return ShareMessage(
        subject=f"{what} geteilt von {display_name}",
        html=body,
        filename=f"zeiterfassung-share-{exported_at[:10].replace('-', '')}.json",
        what=what,
    )
