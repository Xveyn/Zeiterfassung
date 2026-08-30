"""Worker-Kern des Sende-Dialogs (Audit M10): Tk-frei, wirft nie.

Dispatcher über zwei Kanaltypen: Gmail und beliebig viele Webhooks. Die
Payloads (PDF, JSON) entstehen genau einmal und nur, wenn sie ein Kanal
braucht — generate_pdf ist der teuerste Schritt im Pfad. Jeder Kanal läuft
unabhängig; ein Fehler bricht die übrigen nicht ab. Persistenz
(settings.set) passiert hier im Worker und überlebt damit einen
Dialog-Close.
"""

import json as _json
import logging
import traceback

from src import webhook
from src.dialogs.mail_task import classify_mail_error
from src.mail import fetch_user_email, get_gmail_service, send_email
from src.report import generate_pdf

log = logging.getLogger(__name__)


def needs_pdf(send_mail, webhooks):
    """True, wenn irgendein Kanal die PDF braucht (Mail hängt sie immer an)."""
    return bool(send_mail) or any(w.get("pdf") for w in webhooks)


def needs_json(webhooks):
    return any(w.get("json") for w in webhooks)


def _send_mail(*, mail, pdf_bytes, pdf_filename, settings):
    """Der bisherige Gmail-Pfad, unverändert im Verhalten."""
    try:
        service = get_gmail_service(
            mail["credentials_path"], mail["token_path"],
            sync_enabled=mail["sync_enabled"], gcal_enabled=mail["gcal_enabled"])
        send_email(service, mail["recipient"], mail["subject"], mail["html"],
                   attachment_bytes=pdf_bytes,
                   attachment_filename=pdf_filename,
                   attachment_subtype="pdf")
    except FileNotFoundError as e:
        return classify_mail_error(e)
    except Exception as e:
        log.exception("Mailversand fehlgeschlagen")
        return classify_mail_error(e)

    # Nach erfolgreichem Send ist der Token frisch — Absender-Adresse cachen.
    try:
        email = fetch_user_email(
            mail["token_path"], sync_enabled=mail["sync_enabled"],
            gcal_enabled=mail["gcal_enabled"])
        if email and email != settings.get("sender_email"):
            settings.set("sender_email", email)
    except Exception:
        log.exception("sender_email fetch after send failed")

    return {"ok": True}


def perform_send(*, date_from, date_to, entries, name, categories,
                 category_breakdown, send_mail, mail, webhooks,
                 pdf_filename, settings, vacation_days=None):
    """Feuert alle gewählten Kanäle und sammelt ein Ergebnis je Kanal.

    Wirft nie. `webhooks` ist eine Liste von
    {"record": <webhook>, "json": bool, "pdf": bool} — die im Sende-Dialog
    ggf. übersteuerte Format-Wahl.
    """
    results = []

    # `mail` ist als `dict | None` deklariert und damit unabhängig von
    # `send_mail` setzbar. Ohne diese Normalisierung dereferenziert der
    # Mail-Zweig unten `mail["recipient"]` außerhalb jedes try-Blocks und
    # wirft — der Vertrag lautet aber „wirft nie", und ein Bruch heißt hier:
    # BackgroundTaskRunner.run ruft `on_done` nie, der Sende-Dialog bleibt
    # dauerhaft auf „Sende…" stehen, während die übrigen Kanäle schon
    # gefeuert haben.
    if send_mail and mail is None:
        log.error("perform_send: send_mail=True ohne mail-Daten — "
                  "Mail-Kanal wird übersprungen")
        send_mail = False

    pdf_bytes = None
    if needs_pdf(send_mail, webhooks):
        try:
            pdf_bytes = generate_pdf(
                date_from, date_to, entries, name=name,
                categories=categories, category_breakdown=category_breakdown,
                vacation_days=vacation_days)
        except Exception as e:
            log.exception("PDF-Erzeugung fehlgeschlagen")
            failure = {"ok": False, "kind": "error", "detail": str(e),
                       "error": e, "tb": traceback.format_exc()}
            # Ohne PDF kann weder die Mail noch ein PDF-Webhook raus. Die
            # JSON-Webhooks laufen trotzdem weiter — sie brauchen sie nicht.
            if send_mail:
                # Garantiert gesetzt: die Normalisierung oben hat send_mail
                # auf False gezogen, wenn mail None war.
                assert mail is not None
                results.append({"channel": "mail",
                                "name": mail["recipient"], **failure})
                send_mail = False
            for entry in [w for w in webhooks if w.get("pdf")]:
                results.append({"channel": "webhook",
                                "name": entry["record"].get("name", ""),
                                **failure})
            webhooks = [w for w in webhooks if not w.get("pdf")]

    if send_mail:
        # Garantiert gesetzt: dieselbe Normalisierung wie oben.
        assert mail is not None
        res = _send_mail(mail=mail, pdf_bytes=pdf_bytes,
                         pdf_filename=pdf_filename, settings=settings)
        results.append({"channel": "mail", "name": mail["recipient"], **res})

    json_bytes = None
    if needs_json(webhooks):
        # MUSS abgesichert sein: entkommt hier eine Exception, fängt
        # BackgroundTaskRunner.run sie ab und ruft `on_done` NIE — der
        # Sende-Dialog bliebe mit „Sende…" dauerhaft stehen, während die Mail
        # längst raus ist. Der Vertrag lautet „wirft nie", und der gilt für
        # den ganzen Dispatcher, nicht nur für die Kanäle.
        try:
            payload = webhook.build_json_payload(
                date_from=date_from, date_to=date_to, entries=entries,
                name=name, sender=settings.get("sender_email"),
                categories=categories)
            json_bytes = _json.dumps(
                payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        except Exception as e:  # bewusst alles, s.o.
            log.exception("JSON-Payload konnte nicht gebaut werden")
            failure = {"ok": False, "kind": "error", "detail": str(e),
                       "error": e, "tb": traceback.format_exc()}
            for entry in [w for w in webhooks if w.get("json")]:
                results.append({"channel": "webhook",
                                "name": entry["record"].get("name", ""),
                                **failure})
            # Nur-PDF-Webhooks brauchen das Dokument nicht und laufen weiter.
            webhooks = [w for w in webhooks if not w.get("json")]

    for entry in webhooks:
        record = entry["record"]
        try:
            res = webhook.deliver(
                record,
                json_bytes=json_bytes if entry.get("json") else None,
                pdf_bytes=pdf_bytes if entry.get("pdf") else None,
                pdf_filename=pdf_filename)
        except Exception as e:  # bewusst alles: der Dispatcher wirft nie
            log.exception("Webhook %r: unerwarteter Fehler",
                          record.get("name"))
            res = {"ok": False, "kind": "error", "detail": str(e),
                   "error": e, "tb": traceback.format_exc()}
        results.append({"channel": "webhook",
                        "name": record.get("name", ""), **res})

    return {"results": results}


_KIND_TEXTS = {
    "filenotfound": "Zugangsdaten fehlen",
    "offline": "keine Internetverbindung",
    "auth": "Zugangsdaten wurden abgelehnt",
    "notfound": "Adresse nicht gefunden",
    "redirect": "Weiterleitung — bitte die endgültige Adresse eintragen",
    "client": "Anfrage abgelehnt",
    "server": "Server-Fehler",
    "config": "Konfiguration ungültig",
    "error": "unerwarteter Fehler",
}


def format_result_summary(results):
    """Mehrzeilige Zusammenfassung für den Ergebnis-Dialog."""
    lines = []
    for res in results:
        if res.get("ok"):
            lines.append(f"✓  {res['name']}")
            continue
        reason = _KIND_TEXTS.get(res.get("kind"), "Fehler")
        detail = (res.get("detail") or "").strip()
        lines.append(f"✗  {res['name']} — {reason}"
                     + (f" ({detail})" if detail else ""))
    return "\n".join(lines)
