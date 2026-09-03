"""Tests für den gemeinsamen MIME-Bau (Gmail-API und SMTP teilen ihn).

Hier liegen ZWEI der drei UTF-8-Pflichten (MIMEText-Charset und
Betreff-Header) und die Steuerzeichen-Abwehr gegen Header-Injection
(Audit N11). Die dritte Pflicht — <meta charset="utf-8"> im <head> — sitzt
bei den HTML-Erzeugern (report.py, share_dialog.py) und ist hier bewusst
nicht prüfbar.
"""

import pytest

from src.mime_message import build_message


def test_plain_message_is_utf8_html():
    msg = build_message(to="a@example.com", subject="Bericht",
                        html_body="<p>Grüße</p>")
    assert msg["to"] == "a@example.com"
    assert msg.get_content_type() == "text/html"
    assert msg.get_content_charset() == "utf-8"


def test_subject_is_utf8_encoded():
    """Umlaute im Betreff dürfen nicht als Mojibake ankommen."""
    from email.header import decode_header

    msg = build_message(to="a@example.com", subject="Müller & Söhne",
                        html_body="<p>x</p>")
    decoded = decode_header(msg["subject"])[0]
    assert decoded[1] == "utf-8"
    assert decoded[0].decode("utf-8") == "Müller & Söhne"


def test_subject_control_chars_cannot_inject_a_header():
    """Header(subject, "utf-8") kodiert IMMER nach RFC 2047, auch reines
    ASCII — ein eingeschleustes CRLF landet in der kodierten Nutzlast, nicht
    als neuer Header. Deshalb braucht der Betreff keine eigene Abwehr."""
    msg = build_message(to="a@example.com",
                        subject="Bericht\r\nBcc: attacker@evil.com",
                        html_body="<p>x</p>")
    assert msg["bcc"] is None
    assert "attacker@evil.com" not in (msg.get("bcc") or "")


def test_attachment_uses_given_subtype_and_filename():
    msg = build_message(to="a@example.com", subject="S", html_body="<p>x</p>",
                        attachment_bytes=b'{"x":1}',
                        attachment_filename="share.json",
                        attachment_subtype="json")
    raw = msg.as_string()
    assert "application/json" in raw
    assert "share.json" in raw


def test_attachment_without_filename_falls_back_to_subtype():
    msg = build_message(to="a@example.com", subject="S", html_body="<p>x</p>",
                        attachment_bytes=b"%PDF-1.4",
                        attachment_subtype="pdf")
    assert "attachment.pdf" in msg.as_string()


def test_from_addr_is_only_set_when_given():
    """Gmail setzt kein From (der authentifizierte Nutzer ist der Absender),
    SMTP schon."""
    without = build_message(to="a@example.com", subject="S", html_body="<p>x</p>")
    assert without["from"] is None

    with_from = build_message(to="a@example.com", subject="S",
                              html_body="<p>x</p>", from_addr="me@example.com")
    assert with_from["from"] == "me@example.com"


@pytest.mark.parametrize("evil", [
    "victim@example.com\r\nBcc: attacker@evil.com",
    "victim@example.com\nBcc: attacker@evil.com",
    "victim@example.com\x00",
])
def test_control_chars_in_recipient_are_rejected(evil):
    """Audit N11 / #133: abweisen statt still strippen — ein gestripptes
    'a@b\\nBcc: c' ginge sonst an die vermurkste Adresse 'a@bBcc: c'."""
    with pytest.raises(ValueError):
        build_message(to=evil, subject="S", html_body="<p>x</p>")


@pytest.mark.parametrize("evil", [
    "me@example.com\r\nBcc: attacker@evil.com",
    "me@example.com\x00",
])
def test_control_chars_in_from_addr_are_rejected(evil):
    """Beim SMTP-Versand ist der Absender ein zweites nutzergefülltes
    Headerfeld mit demselben Injection-Risiko wie der Empfänger."""
    with pytest.raises(ValueError):
        build_message(to="a@example.com", subject="S", html_body="<p>x</p>",
                      from_addr=evil)
