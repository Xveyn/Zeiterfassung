"""Aufbau der Mail-Nachricht — gemeinsam für Gmail-API und SMTP.

Tk-frei, stdlib-only, ohne Google-Import. Hier liegen ZWEI der drei
UTF-8-Pflichten aus CLAUDE.md („UTF-8 im Mail-Pipeline") — der
MIMEText-Charset und der Betreff-Header — sowie die Steuerzeichen-Abwehr
gegen Header-Injection (Audit N11), damit sie für beide Transporte gilt und
nicht in zwei Kopien auseinanderläuft.

Die dritte Pflicht, `<meta charset="utf-8">` im `<head>`, liegt NICHT hier:
sie gehört zu den HTML-Erzeugern (`report.generate_report`, `share_dialog`),
weil dieses Modul das HTML nur entgegennimmt.
"""

from __future__ import annotations

from email.header import Header
from email.message import Message
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_FORBIDDEN_CHARS = ("\r", "\n", "\x00")


def _reject_control_chars(value: str, label: str) -> None:
    """Weist Steuerzeichen ab, statt sie still zu strippen (Audit N11 / #133).

    Ein gestripptes „a@b\\nBcc: c" würde an die vermurkste Adresse
    „a@bBcc: c" gesendet, ohne dass der Nutzer es merkt — stille
    Falschzustellung ist schlimmer als ein sichtbarer Fehler.

    Der Betreff braucht das nicht: `Header(subject, "utf-8")` kodiert immer
    nach RFC 2047, ein CRLF landet dort in der Nutzlast.
    """
    if any(ch in value for ch in _FORBIDDEN_CHARS):
        raise ValueError(
            f"Die {label} enthält unzulässige Steuerzeichen (Zeilenumbruch "
            "oder Nullbyte). Bitte korrigiere die Adresse in den "
            "Einstellungen."
        )


def build_message(*, to: str, subject: str, html_body: str,
                  attachment_bytes: bytes | None = None,
                  attachment_filename: str | None = None,
                  attachment_subtype: str = "pdf",
                  from_addr: str | None = None) -> Message:
    """Baut die fertige Mail-Nachricht.

    `from_addr` wird nur gesetzt, wenn übergeben: die Gmail-API kennt den
    Absender aus dem Token, SMTP braucht ihn im Header.
    """
    _reject_control_chars(to, "Empfängeradresse")
    if from_addr is not None:
        _reject_control_chars(from_addr, "Absenderadresse")

    message: Message
    if attachment_bytes:
        message = MIMEMultipart()
        message.attach(MIMEText(html_body, "html", _charset="utf-8"))
        attachment = MIMEApplication(attachment_bytes, _subtype=attachment_subtype)
        attachment.add_header(
            "Content-Disposition", "attachment",
            filename=attachment_filename or f"attachment.{attachment_subtype}",
        )
        message.attach(attachment)
    else:
        message = MIMEText(html_body, "html", _charset="utf-8")

    message["to"] = to
    message["subject"] = Header(subject, "utf-8")  # pyright: ignore[reportArgumentType]
    if from_addr is not None:
        message["from"] = from_addr
    return message
