"""SMTP-Versand (Tk-frei).

Der zweite Mailweg neben der Gmail-API. Die Nachricht selbst baut
`mime_message.build_message` — dieselbe wie beim Gmail-Versand, inklusive der
UTF-8-Pflichten und der Steuerzeichen-Abwehr.

Stdlib bis auf einen Import: `mail.is_offline_error` wird wiederverwendet,
statt die Offline-Erkennung zu kopieren. `src/mail.py` ist auf Modulebene
selbst Google-frei (die Google-Importe sind lazy) — es entsteht also kein
CI-Problem und kein Import-Zyklus.

Eigener Fehlerklassifikator statt `mail_task.classify_mail_error`: der kennt
nur `filenotfound`/`offline`/`error`, während hier `auth`/`recipient`/`tls`/
`server` unterschieden werden müssen. Ohne diese Zweige käme jede
SMTP-Fehlerantwort als „unerwarteter Fehler mit Traceback" beim Nutzer an
statt als „Die Zugangsdaten wurden abgelehnt" (Muster wie webhook.py).
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import traceback
from typing import Any

from src.mail import is_offline_error
from src.mime_message import build_message

log = logging.getLogger(__name__)

SECURITY_MODES = ("starttls", "ssl", "none")

# Ohne Timeout hängt der Worker-Thread unbegrenzt an einem Server, der die
# Verbindung annimmt und dann schweigt.
DEFAULT_TIMEOUT = 20


class TlsNotSupported(Exception):
    """Der Server bietet STARTTLS nicht an."""


class AuthNotSupported(Exception):
    """Der Server bietet die AUTH-Extension nicht an.

    Eigene Klasse, weil `smtplib` für beide Fälle dieselbe
    `SMTPNotSupportedError` wirft — auch aus `send_message` bei
    Nicht-ASCII-Adressen ohne SMTPUTF8. Ohne Trennung meldete ein
    Firmen-Relay ohne AUTH „Verschlüsselung fehlgeschlagen", und der Nutzer
    drehte an TLS-Einstellungen, die nichts damit zu tun haben.
    """


def _tls_context() -> ssl.SSLContext:
    """Voller Prüfkontext. Es gibt bewusst keinen Schalter dagegen: eine
    solche Option wird angeklickt, um ein Problem loszuwerden, und bleibt
    dann an."""
    return ssl.create_default_context()


def _close(server: smtplib.SMTP) -> None:
    """Verbindung schließen, ohne den ursprünglichen Fehler zu überdecken.

    `quit()` ruft `close()` erst NACH dem QUIT-Kommando; wirft das auf einer
    toten Verbindung, bliebe der Filedescriptor offen. Deshalb `close()` im
    `finally` — nach erfolgreichem `quit()` ist es idempotent.
    """
    try:
        server.quit()
    except Exception:
        log.debug("SMTP-Verbindung ließ sich nicht sauber beenden",
                  exc_info=True)
    finally:
        try:
            server.close()
        except Exception:
            log.debug("SMTP-Socket ließ sich nicht schließen", exc_info=True)


def _open(record: dict[str, Any], password: str) -> smtplib.SMTP:
    """Baut die Verbindung auf und meldet sich an.

    **Fail-closed:** ein unbekannter `security`-Wert wirft, statt in den
    unverschlüsselten Zweig zu fallen. Sonst gäbe es faktisch doch einen
    Schalter zum Abschalten von TLS — nur unbeabsichtigt, und mit AUTH PLAIN
    im Klartext als Folge.

    Schlägt etwas nach dem Verbindungsaufbau fehl, wird die Verbindung
    geschlossen, bevor die Exception weiterfliegt.
    """
    security = record.get("security")
    if security not in SECURITY_MODES:
        raise ValueError(
            f"Unbekannter Verschlüsselungsmodus: {security!r}. "
            f"Erlaubt sind: {', '.join(SECURITY_MODES)}."
        )

    host = record["host"]
    port = int(record["port"])

    server: smtplib.SMTP
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=DEFAULT_TIMEOUT,
                                  context=_tls_context())
    else:
        server = smtplib.SMTP(host, port, timeout=DEFAULT_TIMEOUT)

    try:
        if security == "starttls":
            try:
                server.starttls(context=_tls_context())
            except smtplib.SMTPNotSupportedError as e:
                raise TlsNotSupported(str(e)) from e
        username = (record.get("username") or "").strip()
        if username:
            try:
                server.login(username, password)
            except smtplib.SMTPNotSupportedError as e:
                raise AuthNotSupported(str(e)) from e
    except BaseException:
        _close(server)
        raise
    return server


def send(record: dict[str, Any], password: str, *, subject: str, html: str,
         to: str | None = None,
         attachment_bytes: bytes | None = None,
         attachment_filename: str | None = None,
         attachment_subtype: str = "pdf") -> None:
    """Verschickt die Nachricht.

    Empfänger ist `to`, sonst `record["recipient"]`. Der Bericht-Versand lässt
    `to` weg (das Konto trägt seinen Empfänger); der Teilen-Pfad setzt es, weil
    dort der Nutzer die Adresse im Dialog eingibt.

    Wirft bei Fehlern — der Aufrufer klassifiziert über `classify_smtp_error`.
    Blockierend: gehört in einen Worker-Thread.
    """
    message = build_message(
        to=to if to is not None else record["recipient"],
        subject=subject, html_body=html,
        attachment_bytes=attachment_bytes,
        attachment_filename=attachment_filename,
        attachment_subtype=attachment_subtype,
        from_addr=record["from_addr"],
    )
    server = _open(record, password)
    try:
        server.send_message(message)
    finally:
        _close(server)


def test_connection(record: dict[str, Any], password: str) -> None:
    """Verbindet, meldet sich an, schickt `NOOP` — und KEINE Mail.

    Für den „Verbindung testen"-Button. Wirft wie `send`.
    """
    server = _open(record, password)
    try:
        server.noop()
    finally:
        _close(server)


def _response_detail(exc: BaseException) -> str:
    """Die Serverantwort als lesbarer Text — der Nutzer soll sehen, was
    gesagt wurde, nicht nur dass etwas schiefging."""
    recipients = getattr(exc, "recipients", None)
    if isinstance(recipients, dict) and recipients:
        # SMTPRecipientsRefused hat KEIN smtp_code/smtp_error, sondern dieses
        # Dict. `str(exc)` waere sonst woertlich "{'a@b': (550, b'...')}".
        parts = []
        for address, response in recipients.items():
            try:
                code, message = response
            except (TypeError, ValueError):
                parts.append(str(address))
                continue
            if isinstance(message, bytes):
                message = message.decode("utf-8", errors="replace")
            parts.append(f"{address}: {code} {message}".strip())
        return ", ".join(parts)

    code = getattr(exc, "smtp_code", None)
    raw = getattr(exc, "smtp_error", None)
    if code is None and raw is None:
        return str(exc)
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw or "")
    return f"{code} {text}".strip()


def classify_smtp_error(exc: BaseException) -> dict[str, Any]:
    """Mappt eine Versand-Exception auf ein Result-Dict.

    Die Reihenfolge ist Absicht:

    - Die eigenen Marker (`TlsNotSupported`/`AuthNotSupported`) zuerst — sie
      tragen die Information, die `SMTPNotSupportedError` allein nicht hat.
    - `SMTPAuthenticationError` und `SMTPSenderRefused` sind Unterklassen von
      `SMTPResponseException`, `SMTPRecipientsRefused` von `SMTPException` —
      das Speziellere muss vor dem Allgemeineren stehen.
    - **`SMTPException` steht VOR der Offline-Prüfung.** `smtplib` wirft
      `SMTPServerDisconnected` aus einem `except OSError`-Block, und
      `is_offline_error` folgt `__context__` bis zum `TimeoutError` des
      Sockets — ein Server, der annimmt und dann schweigt, meldete sonst
      „keine Internetverbindung".
    - Ein nacktes `OSError` am Schluss: CPython mappt `ENETUNREACH`/
      `EHOSTUNREACH` auf keine Subklasse, `is_offline_error` sieht es also
      nicht.

    Muss aus einem aktiven `except`-Block gerufen werden: der `error`-Fall
    liest den aktuellen Traceback über `traceback.format_exc()`.
    """
    def result(kind: str, detail: str, tb: str | None = None) -> dict[str, Any]:
        return {"ok": False, "kind": kind, "detail": detail,
                "error": exc, "tb": tb}

    if isinstance(exc, TlsNotSupported):
        return result("tls", str(exc))
    if isinstance(exc, AuthNotSupported):
        return result("auth", str(exc))
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return result("auth", _response_detail(exc))
    if isinstance(exc, (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused)):
        return result("recipient", _response_detail(exc))
    if isinstance(exc, ssl.SSLError):
        return result("tls", str(exc))
    if isinstance(exc, smtplib.SMTPException):
        return result("server", _response_detail(exc))
    if is_offline_error(exc):
        return result("offline", "")
    if isinstance(exc, OSError):
        return result("offline", str(exc))
    return result("error", str(exc), traceback.format_exc())
