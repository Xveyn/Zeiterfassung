"""Pure Logik des Webhook-Versands (Tk-frei, stdlib-only).

Kein tkinter, keine Google-Imports, keine dritte Dependency — dieses Modul
ist die getestete Schicht des Features (siehe docs/known-limitations.md:
getestet wird Logik, nicht UI).
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import ipaddress
import logging
import re
import traceback
import urllib.error
import urllib.request
import uuid
from http.client import HTTPMessage
from typing import IO, Any, NoReturn
from urllib.parse import unquote, urlsplit

from src.mail import is_offline_error
from src.report import filter_categories, filter_period
from src.time_utils import calculate_hours, hours_to_minutes, utc_now_iso
from src.vacations import cap_by_worktime
from src.version import VERSION

log = logging.getLogger(__name__)

# Explizit ausgeschriebene Netzliste statt ip_address(...).is_private:
# CPython hat die Einordnung von 100.64.0.0/10 (RFC 6598, CGNAT) zwischen
# 3.10 und 3.13 geändert. Die CI-Matrix deckt beide ab — mit is_private wäre
# derselbe Test auf einer Python-Version grün und auf der anderen rot.
_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "127.0.0.0/8",      # Loopback
        "10.0.0.0/8",       # RFC 1918
        "172.16.0.0/12",    # RFC 1918
        "192.168.0.0/16",   # RFC 1918
        "100.64.0.0/10",    # RFC 6598 CGNAT (Tailscale u.ä.)
        "169.254.0.0/16",   # Link-Local
        "::1/128",          # Loopback v6
        "fc00::/7",         # ULA
        "fe80::/10",        # Link-Local v6
    )
)

_PRIVATE_SUFFIXES = (".local", ".lan", ".home.arpa", ".internal", ".localhost")


def is_private_host(host: str | None) -> bool:
    """True, wenn `host` im lokalen Netz liegt und http damit erlaubt ist.

    Rein syntaktisch, ohne DNS-Auflösung. Ein öffentlicher Name, der per
    Split-Horizon-DNS intern auf eine private Adresse zeigt, gilt deshalb als
    öffentlich — bewusst, siehe docs/known-limitations.md.
    """
    if not host:
        return False
    # Vor der Prüfung dekodieren: urlsplit lässt Prozent-Kodierung im Host
    # stehen ('8%2e8%2e8%2e8'), urllib löst sie beim Request aber auf
    # (Request(...).host -> '8.8.8.8'). Ungeprüft sähe eine öffentliche IP
    # damit wie ein punktloses Single-Label und also wie ein lokaler Name aus.
    host = unquote(host.strip()).lower().rstrip(".")
    if not host or "%" in host:
        return False
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Kein IP-Literal, also ein Name.
        if host.endswith(_PRIVATE_SUFFIXES):
            return True
        if "." in host:
            return False
        # Single-Label-Name (»nas«, »fritzbox«): nur im lokalen Netz auflösbar.
        # Rein numerisch (dezimal ODER hex mit 0x/0X-Präfix) ist es aber kein
        # Name, sondern eine numerische IP, die glibcs inet_aton-Semantik
        # auflöst (http://2130706433/ -> 127.0.0.1, http://0x08080808/ ->
        # 8.8.8.8) — die gehört nicht hierher. Oktale Schreibweisen
        # (»017700000001«) sind bereits über isdigit() erfasst (nur Ziffern),
        # gepunktete oktale/hex-Formen (»0177.0.0.1«) scheitern schon oben an
        # der Punkt-Prüfung.
        return not re.fullmatch(r"[0-9]+|0[xX][0-9a-fA-F]+", host)
    return any(ip in net for net in _PRIVATE_NETWORKS)


def validate_url(url: str | None) -> tuple[bool, str]:
    """Prüft Schema und Host. Liefert (ok, deutsche Begründung)."""
    try:
        # urlsplit selbst wirft bei kaputten IPv6-Klammern ('http://[::1/x')
        # — nicht erst .hostname. Der try muss deshalb hier stehen, sonst
        # entkommt die Exception bis in den Tk-Excepthook.
        parts = urlsplit((url or "").strip())
        host = parts.hostname
    except ValueError:
        return False, "Die Adresse ist nicht lesbar."
    if parts.scheme not in ("http", "https"):
        return False, "Die Adresse muss mit http:// oder https:// beginnen."
    if not host:
        return False, "Die Adresse enthält keinen Server-Namen."
    if parts.scheme == "http" and not is_private_host(host):
        return False, (
            "Für Adressen außerhalb des lokalen Netzes ist https erforderlich."
        )
    return True, ""


_CONTROL_CHARS = ("\r", "\n", "\x00")


def _check_header_part(kind: str, value: str) -> None:
    """Wirft ValueError, wenn `value` Steuerzeichen enthält.

    `kind` trägt den Artikel schon mit (»Der Header-Name«, »Das
    Signatur-Präfix«) — die Genera sind unterschiedlich, ein fest
    vorangestelltes »Der« wäre für »Präfix« falsch.

    Abweisen statt strippen: ein still bereinigtes "Bearer a\\nX-Foo: b"
    ergäbe einen Request, den der Nutzer nie so gemeint hat, und der Fehler
    fiele erst beim Empfänger auf (Muster wie mail.send_email, Audit N11).
    """
    if any(c in value for c in _CONTROL_CHARS):
        raise ValueError(
            f"{kind} enthält unzulässige Steuerzeichen "
            "(Zeilenumbruch oder Nullbyte)."
        )


def sign_hmac(secret: str, body: bytes) -> str:
    """HMAC-SHA256 über die rohen Body-Bytes, Hex, kleingeschrieben."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def auth_headers(auth: dict[str, Any] | None, body: bytes) -> dict[str, str]:
    """Baut die Auth-Header für einen Webhook-Request.

    `auth` ist das `auth`-Objekt aus webhooks.json. Signiert wird bei `hmac`
    über die rohen Body-Bytes — exakt die Bytes, die über die Leitung gehen,
    sonst kann der Empfänger nicht verifizieren.
    """
    mode = (auth or {}).get("mode", "none")
    if mode == "none":
        return {}
    if mode == "header":
        name = auth.get("header") or "Authorization"
        value = auth.get("value") or ""
        _check_header_part("Der Header-Name", name)
        _check_header_part("Der Header-Wert", value)
        return {name: value}
    if mode == "hmac":
        name = auth.get("header") or "X-Hub-Signature-256"
        # Fehlender Schlüssel → der dokumentierte Default sha256=; ein
        # ausdrücklich leeres Präfix bleibt leer. Deshalb None-Prüfung statt
        # `or ""` (schluckte den Default) und statt .get(key, default)
        # (liefe bei einem None-Wert in die Konkatenation).
        prefix = auth.get("prefix")
        if prefix is None:
            prefix = "sha256="
        _check_header_part("Der Header-Name", name)
        _check_header_part("Das Signatur-Präfix", prefix)
        return {name: prefix + sign_hmac(auth.get("secret") or "", body)}
    raise ValueError(f"Unbekanntes Auth-Verfahren: {mode!r}")


PAYLOAD_SCHEMA_VERSION = 2
PAYLOAD_KIND = "zeiterfassung-report"


def _project_slots(entries: dict[str, Any]) -> dict[str, Any]:
    """Reduziert jeden Slot auf die vier Felder des Wire-Formats.

    Sieht überflüssig aus, ist es aber nicht: `Storage._load` normalisiert
    Slots NICHT — das tut nur der Schreibpfad (`Storage.save` über
    `_normalize_slot`). Ein Slot aus einer von Hand bearbeiteten oder von
    einer neueren App-Version geschriebenen zeiterfassung.json trägt seine
    Zusatzfelder sonst bis ins Webhook-Dokument. Diese Projektion ist die
    Stelle, an der das Wire-Format tatsächlich festgelegt wird.

    Die Defaults sind dieselben wie in `storage._normalize_slot` (`pause` → 0,
    `kategorie` → ""). Das ist keine Kosmetik: `total_minutes` rechnet auf
    diesen Slots weiter, und ein `None` in `pause` liefe in
    `calculate_hours` in einen TypeError.
    """
    return {
        date_str: {"slots": [
            {"start": slot.get("start"), "end": slot.get("end"),
             "pause": slot.get("pause", 0) or 0,
             "kategorie": slot.get("kategorie") or ""}
            for slot in record.get("slots", [])
        ]}
        for date_str, record in entries.items()
    }


def total_minutes(entries: dict[str, Any]) -> int:
    """Summe der Arbeitsminuten über alle Slots.

    Summiert wird über hours_to_minutes je Slot, NICHT über die
    Dezimalstunden — calculate_hours rundet pro Slot auf 2 Nachkommastellen
    (gröber als eine Minute), zweimal unabhängig zu runden ließe die Summe
    von den Einzelposten abweichen (CLAUDE.md, Abschnitt „Stunden").
    """
    return sum(
        hours_to_minutes(
            calculate_hours(slot.get("start"), slot.get("end"), slot.get("pause", 0)))
        for record in entries.values()
        for slot in record.get("slots", [])
    )


def build_json_payload(*, date_from: datetime.date, date_to: datetime.date,
                       entries: dict[str, Any], name: str | None,
                       sender: str | None, categories: list[str] | None,
                       generated_at: str | None = None,
                       vacation_days: dict[str, int] | None = None
                       ) -> dict[str, Any]:
    """Das JSON-Dokument für den Webhook.

    `entries` ist der Snapshot aus `Storage.get_all()` (bereits durch
    `workweek.filter_for_report` gelaufen); Zeitraum und Kategorien filtert
    diese Funktion über dieselben Helfer wie Mail-HTML und PDF, damit alle
    drei denselben Ausschnitt behaupten.

    `vacation_days` ist der {ISO: minutes}-Snapshot des Urlaubs-Stores oder
    None (Häkchen nicht gesetzt). Er läuft durch DENSELBEN `filter_period`
    wie die Entries — die drei Ausgabewege (Mail-HTML, PDF, Webhook) sollen
    denselben Ausschnitt behaupten. Ohne Urlaub bleiben die Felder
    null/0, damit ein bestehender Empfänger unverändert weiterläuft.

    Eigenes `kind` statt `zeiterfassung-share`: das Dokument trägt
    Report-Metadaten, die der Share-Validator als unbekannte Felder ablehnt.
    Die Slot-Shape ist trotzdem identisch zu Share v3, damit ein Empfänger
    seinen Parser wiederverwenden kann.
    """
    ranged = filter_period(date_from, date_to, entries) or {}
    if ranged:
        ranged = filter_categories(ranged, categories)
    ranged = _project_slots(ranged)
    vacation_ranged = (
        filter_period(date_from, date_to, vacation_days) or {}
        if vacation_days is not None else None
    )
    # Trifft Urlaub auf erfasste Ist-Zeit, wird der Urlaub des Tages um sie
    # gekappt — dieselbe Rechnung wie in Mail-HTML und PDF, sonst summierte
    # ein Empfänger für einen Kalendertag mehr Stunden, als er hat
    # (Xveyn#97). Gegen `ranged`, also den bereits zeitraum- und
    # kategoriegefilterten, projizierten Ausschnitt, auf dem auch
    # `total_minutes` rechnet.
    if vacation_ranged:
        vacation_ranged, _ = cap_by_worktime(vacation_ranged, ranged)
    return {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "kind": PAYLOAD_KIND,
        "generated_at": generated_at or utc_now_iso(),
        "sender": sender or "",
        "name": name or "",
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "categories": list(categories) if categories is not None else None,
        "total_minutes": total_minutes(ranged),
        "entries": ranged,
        "vacation": vacation_ranged,
        "vacation_minutes": sum(vacation_ranged.values()) if vacation_ranged else 0,
    }


def build_body(*, json_bytes: bytes | None, pdf_bytes: bytes | None,
               pdf_filename: str, boundary: str) -> tuple[str, bytes]:
    """Wählt Content-Type und baut den Request-Body.

    JSON allein → application/json, PDF allein → application/pdf,
    beides → multipart/form-data mit den Teilen `data` und `report`.
    Multipart statt base64-im-JSON: Empfänger wie n8n/Make erwarten es so,
    und base64 bläht die Payload um ein Drittel auf.

    `boundary` wird hereingereicht (statt hier gewürfelt), damit Tests
    deterministisch bleiben.
    """
    if json_bytes is not None and pdf_bytes is None:
        return "application/json; charset=utf-8", json_bytes
    if pdf_bytes is not None and json_bytes is None:
        return "application/pdf", pdf_bytes
    if json_bytes is None and pdf_bytes is None:
        raise ValueError("Weder JSON noch PDF zum Senden vorhanden.")

    sep = f"--{boundary}\r\n".encode("latin-1")
    parts = [
        sep,
        b'Content-Disposition: form-data; name="data"; filename="report.json"\r\n',
        b"Content-Type: application/json; charset=utf-8\r\n\r\n",
        json_bytes, b"\r\n",
        sep,
        f'Content-Disposition: form-data; name="report"; '
        f'filename="{pdf_filename}"\r\n'.encode("utf-8"),
        b"Content-Type: application/pdf\r\n\r\n",
        pdf_bytes, b"\r\n",
        f"--{boundary}--\r\n".encode("latin-1"),
    ]
    return f'multipart/form-data; boundary="{boundary}"', b"".join(parts)


REQUEST_TIMEOUT_S = 30
_MAX_RESPONSE_BYTES = 8192
_MAX_DETAIL_CHARS = 500

USER_AGENT = f"Zeiterfassung/{VERSION}"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Folgt keinem Redirect — jedes 3xx wird zum HTTPError.

    urllib würde bei 301/302/303 auf einen POST eine GET-Anfrage OHNE Body
    bauen (`redirect_request` erzeugt `Request(newurl, method="GET", …)` ohne
    `data`, Content-Type/-Length sind herausgefiltert). Der Bericht käme nie
    an, der Endpunkt antwortete 200 — die App meldete Erfolg. Dazu reisen alle
    übrigen Header hostunabhängig mit, `Authorization` inklusive.

    Ein Webhook-Ziel ist feste Konfiguration: die endgültige Adresse gehört in
    die Einstellungen, nicht in eine Weiterleitungskette.

    Da diese Klasse von HTTPRedirectHandler erbt, ersetzt `build_opener` den
    Default-Handler durch sie (statt beide einzuhängen).
    """

    def redirect_request(self, req: urllib.request.Request, fp: IO[bytes],
                         code: int, msg: str, headers: HTTPMessage,
                         newurl: str) -> NoReturn:
        raise urllib.error.HTTPError(
            req.full_url, code,
            "Der Endpunkt hat weitergeleitet — bitte die endgültige Adresse "
            "eintragen.",
            headers, fp)


def _build_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirectHandler())


def post(url: str, headers: dict[str, str], body: bytes,
         timeout: float = REQUEST_TIMEOUT_S) -> int:
    """POST an `url`. Liefert den HTTP-Status; wirft bei Fehlern.

    `timeout` ist urllibs Socket-Timeout je Operation, kein Gesamt-Timeout:
    ein tröpfelnder Server hält den Worker beliebig lange. Hinnehmbar, weil
    der Aufruf im Worker-Thread liegt.
    """
    req = urllib.request.Request(url, data=body, method="POST")
    for name, value in headers.items():
        req.add_header(name, value)
    req.add_header("User-Agent", USER_AGENT)
    with _build_opener().open(req, timeout=timeout) as resp:
        resp.read(_MAX_RESPONSE_BYTES)
        return getattr(resp, "status", None) or resp.getcode()


def _response_snippet(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read(_MAX_RESPONSE_BYTES)
    except Exception:
        # Der Body ist reine Detailanzeige unter der Fehlermeldung. Laesst er
        # sich nicht lesen, faellt nur dieses Detail weg — die Klassifikation
        # des Fehlers steht bereits fest und bleibt unberuehrt.
        return ""
    finally:
        # `exc` (der HTTPError) ist ein offener Dateizeiger auf die
        # Fehlerantwort — anders als post()s Erfolgspfad läuft er nicht durch
        # ein `with`. Ohne close() bliebe die Verbindung/der Socket hängen.
        # Defensiv: ein scheiterndes close() darf den Klassifikator nicht
        # kippen, der Body wurde oben ja schon gelesen (oder der Lesefehler
        # bereits behandelt).
        try:
            exc.close()
        except Exception:
            pass  # Begruendung im Block-Kommentar direkt darueber
    text = raw.decode("utf-8", "replace").strip()
    return text[:_MAX_DETAIL_CHARS]


def classify_error(exc: Exception) -> dict[str, Any]:
    """Mappt eine Versand-Exception auf ein Fehler-Result-Dict.

    HTTPError wird ZUERST geprüft — sonst fiele jede HTTP-Fehlerantwort in den
    generischen Zweig und käme als unerwarteter Fehler MIT Traceback beim
    Nutzer an, statt als „Der Server hat mit 500 geantwortet". (Nicht, weil
    is_offline_error sie schlucken würde: das vergleicht Typnamen, und
    "HTTPError" steht nicht in _OFFLINE_EXC_NAMES — nachgemessen.)
    """
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        if 300 <= code < 400:
            # Kann nur von _NoRedirectHandler kommen; 307/308 wirft urllib bei
            # POST ohnehin selbst. Der Body wäre bei einem gefolgten Redirect
            # verloren gegangen — deshalb eigener kind statt "server".
            return {"ok": False, "kind": "redirect",
                    "detail": f"HTTP {code}", "error": exc, "tb": None}
        snippet = _response_snippet(exc)
        detail = f"HTTP {code}" + (f": {snippet}" if snippet else "")
        if code in (401, 403):
            kind = "auth"
        elif code == 404:
            kind = "notfound"
        elif 400 <= code < 500:
            kind = "client"
        else:
            kind = "server"
        return {"ok": False, "kind": kind, "detail": detail,
                "error": exc, "tb": None}
    if is_offline_error(exc):
        return {"ok": False, "kind": "offline", "detail": "",
                "error": exc, "tb": None}
    return {"ok": False, "kind": "error", "detail": str(exc),
            "error": exc, "tb": traceback.format_exc()}


def deliver(record: Any, *, json_bytes: bytes | None, pdf_bytes: bytes | None,
            pdf_filename: str, boundary: str | None = None) -> dict[str, Any]:
    """Sendet eine Payload an einen konfigurierten Webhook.

    Wirft nie — Fehler kommen als Result-Dict zurück (Vertrag wie
    send_task.perform_send, Audit M10). `kind == "config"` heißt: die
    Konfiguration ist unbrauchbar, es wurde gar nicht erst gesendet.

    Die URL wird hier erneut geprüft, obwohl der Dialog das beim Speichern
    schon tut: eine von Hand editierte webhooks.json soll die https-Pflicht
    nicht umgehen können.
    """
    # Dieselbe Bedrohung wie bei der URL-Nachprüfung: eine von Hand editierte
    # Datei kann jeden Typ enthalten. Ein Nicht-Dict würde unten schon am
    # ersten .get() scheitern.
    if not isinstance(record, dict):
        return {"ok": False, "kind": "config",
                "detail": "Der Webhook-Datensatz ist kein Objekt.",
                "error": None, "tb": None}

    try:
        ok, msg = validate_url(record.get("url", ""))
        if not ok:
            return {"ok": False, "kind": "config", "detail": msg,
                    "error": None, "tb": None}

        content_type, body = build_body(
            json_bytes=json_bytes, pdf_bytes=pdf_bytes,
            pdf_filename=pdf_filename,
            boundary=boundary or uuid.uuid4().hex)

        headers = {"Content-Type": content_type}
        headers.update(auth_headers(record.get("auth"), body))
    except (ValueError, TypeError, AttributeError, KeyError) as e:
        # Nicht nur ValueError: die Felder des Datensatzes können jeden Typ
        # tragen, wenn jemand webhooks.json von Hand editiert hat. Eine Zahl
        # in `url` wirft AttributeError in validate_url (`.strip()`), ein
        # String in `auth` ebenso in auth_headers (`.get()`), eine Zahl im
        # Header-Namen einen TypeError in der Steuerzeichen-Prüfung. Alle drei
        # sind derselbe Fall — unbrauchbare Konfiguration — und keiner davon
        # darf den „wirft nie"-Vertrag brechen.
        return {"ok": False, "kind": "config", "detail": str(e),
                "error": e, "tb": None}

    try:
        status = post(record["url"], headers, body)
    except Exception as e:  # bewusst alles: der Vertrag lautet „wirft nie"
        log.exception("Webhook-Versand an %r fehlgeschlagen", record.get("name"))
        return classify_error(e)
    return {"ok": True, "status": status}
