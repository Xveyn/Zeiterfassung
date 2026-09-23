"""Die Mail zum Teilen von Arbeitszeiten/Reservierungen (R10, Xveyn#123):
Betreff, HTML-Body und Dateiname des Anhangs, Tk-frei aus dem Teilen-Dialog
gezogen.
"""

import datetime

import pytest

from src.share_message import build_share_message


def _message(**overrides):
    kwargs = dict(
        include_entries=True, include_reservations=False,
        name="Sven", sender_email="sven@example.org",
        date_from=datetime.date(2026, 9, 1), date_to=datetime.date(2026, 9, 30),
        exported_at="2026-09-18T10:15:00Z",
    )
    kwargs.update(overrides)
    return build_share_message(**kwargs)


def test_html_is_the_complete_share_mail():
    """Der ganze Body als Literal: der Text, den der Empfänger liest, darf
    sich durch den Umzug aus dem Dialog nicht verändern."""
    assert _message().html == (
        '<html><head><meta charset="utf-8"></head><body>'
        "<p>Hallo,</p>"
        "<p>im Anhang findest Du meine Arbeitszeiten vom 01.09.2026 bis "
        "30.09.2026 als JSON-Datei.</p>"
        "<p>Du kannst die Datei in der Zeiterfassung-App über "
        "<em>Einstellungen → App → Daten importieren</em> einlesen. "
        "Vor dem Import kannst Du einen Zeitraum auswählen und je "
        "Datentyp festlegen, was bei Konflikten passieren soll.</p>"
        "<p>Viele Grüße<br/>Sven</p>"
        "</body></html>"
    )


def test_html_declares_utf8_in_the_head():
    """Die dritte UTF-8-Pflicht aus CLAUDE.md („UTF-8 im Mail-Pipeline"):
    `mime_message` bündelt die anderen beiden, diese liegt beim HTML-Erzeuger.
    Ohne sie kommen Umlaute beim Empfänger als Mojibake an."""
    html = _message().html

    head = html[html.index("<head>"):html.index("</head>")]
    assert '<meta charset="utf-8">' in head


@pytest.mark.parametrize("entries, reservations, what", [
    (True, False, "Arbeitszeiten"),
    (False, True, "Reservierungen"),
    (True, True, "Arbeitszeiten und Reservierungen"),
])
def test_subject_names_what_is_shared_and_by_whom(entries, reservations, what):
    msg = _message(include_entries=entries, include_reservations=reservations)

    assert msg.what == what
    assert msg.subject == f"{what} geteilt von Sven"
    assert f"meine {what} vom" in msg.html


@pytest.mark.parametrize("name, sender_email, shown", [
    ("Sven", "sven@example.org", "Sven"),
    ("", "sven@example.org", "sven@example.org"),
    ("", "", "anonym"),
    (None, None, "anonym"),
])
def test_sender_falls_back_from_name_to_address_to_anonym(name, sender_email, shown):
    msg = _message(name=name, sender_email=sender_email)

    assert msg.subject == f"Arbeitszeiten geteilt von {shown}"
    assert msg.html.endswith(f"<p>Viele Grüße<br/>{shown}</p></body></html>")


def test_name_is_escaped_in_html_but_raw_in_the_subject():
    """Der Name stand bis R10 roh im HTML — „Müller & Söhne" oder ein „<"
    ergaben beim Empfänger kaputtes Markup. `report.py` escapete schon immer;
    der Betreff ist kein HTML und bleibt, wie er ist."""
    msg = _message(name="Müller & Söhne <GmbH>")

    assert "Müller &amp; Söhne &lt;GmbH&gt;" in msg.html
    assert "<GmbH>" not in msg.html
    assert msg.subject == "Arbeitszeiten geteilt von Müller & Söhne <GmbH>"


def test_filename_carries_the_export_date():
    assert _message(exported_at="2026-09-18T23:59:59Z").filename == \
        "zeiterfassung-share-20260918.json"
