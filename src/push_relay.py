# pyright: reportOptionalMemberAccess=true
"""Das Relay-Objekt eines Handys abräumen (#331), Tk-frei, stdlib-only.

Der Push-Relay (`relay/`, ein Cloudflare Worker) hält je Handy ein Objekt mit Abo und Zeitplan. Es
räumt sich nach 90 Tagen selbst auf; beim **Widerruf** eines Geräts löscht der Desktop es sofort
(`DELETE /v1/device`, das Geheimnis des Handys als Bearer). Best effort: ist der Relay nicht
erreichbar, bleibt der Widerruf gültig und das Objekt verfällt von selbst. `delete_device` wirft
deshalb nie und loggt weder das Geheimnis noch den Text einer Ausnahme (er könnte es enthalten).
Blockiert (Netz): nur im Worker aufrufen.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from http.client import HTTPMessage
from typing import IO, Any, NoReturn

log = logging.getLogger(__name__)

# Muss mit `RELAY_URL` in `pwa/relay-client.js` übereinstimmen (ein Test hält beide zusammen).
RELAY_URL = "https://zeiterfassung-push.svenbirkendahl.workers.dev"
TIMEOUT_S = 10.0
USER_AGENT = "Zeiterfassung (Push-Relay)"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Folgt keinem Redirect: ein Bearer-Token reiste sonst zu einer fremden Adresse mit."""

    def redirect_request(self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str,
                         headers: HTTPMessage, newurl: str) -> NoReturn:
        raise urllib.error.HTTPError(req.full_url, code, "Weiterleitung nicht erlaubt", headers, fp)


def _build_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirectHandler())


def _request(secret: str, base_url: str) -> urllib.request.Request:
    request = urllib.request.Request(f"{base_url}/v1/device", method="DELETE")
    request.add_header("Authorization", f"Bearer {secret}")
    request.add_header("User-Agent", USER_AGENT)
    return request


def delete_device(secret: str, *, opener: Any = None, timeout: float = TIMEOUT_S,
                  base_url: str = RELAY_URL) -> bool:
    """Löscht das Objekt dieses Geheimnisses am Relay. `True` nur bei einer 2xx-Antwort."""
    try:
        with (opener or _build_opener()).open(_request(secret, base_url), timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            return 200 <= status < 300
    except urllib.error.HTTPError as error:
        log.warning("Relay: Objekt eines Handys nicht gelöscht (HTTP %s)", error.code)
    except Exception as error:
        # Offline, Zeitüberschreitung, TLS …: der Text der Ausnahme bleibt draußen (kann das
        # Geheimnis enthalten), die Art genügt.
        log.warning("Relay: Objekt eines Handys nicht gelöscht (%s)", type(error).__name__)
    return False


# --- Testbenachrichtigung (#340) -----------------------------------------------------------------

def _error_body(error: urllib.error.HTTPError) -> dict[str, Any]:
    """Der Body des Relays als Objekt (`{"error": "too_soon"}`), sonst `{}`. Liest höchstens 1 KiB;
    was kein JSON-Objekt ist (eine Fehlerseite von Cloudflare), gilt als leer."""
    try:
        body = json.loads(error.read(1024))
    except Exception:
        # Kein lesbarer Body (leer, kein JSON, Verbindung weg): der Status allein entscheidet.
        return {}
    return body if isinstance(body, dict) else {}


def _cause_of(body: dict[str, Any]) -> str | None:
    """Warum der Push-Dienst ablehnte: sein HTTP-Status (100–599), `network` oder `build`. Alles
    andere (ein künftiger Relay, Fremdtext) entfällt, damit kein Text des Relays in der Oberfläche landet."""
    cause = body.get("cause")
    if isinstance(cause, int) and not isinstance(cause, bool) and 100 <= cause <= 599:
        return str(cause)
    return cause if cause in ("network", "build") else None


def _kind_of(status: int, body: dict[str, Any]) -> str:
    """Status und Body des Relays → die Art, die der Reiter in einen Text übersetzt. `push_failed`
    trägt die Ursache hinter einem Doppelpunkt (`push_failed:403`), wenn der Relay sie nennt."""
    code = body.get("error")
    if status == 401:
        return "unauthorized"
    if status == 404:
        return "unknown_route"        # ein Relay vor #340 kennt `/v1/test` nicht
    if status == 409:
        return "no_subscription"
    if status == 410:
        return "gone"
    if status == 429:
        return "too_soon" if code == "too_soon" else "rate_limited"
    if status == 502 and code == "push_failed":
        cause = _cause_of(body)
        return "push_failed" if cause is None else f"push_failed:{cause}"
    return "server"


def send_test(secret: str, *, opener: Any = None, timeout: float = TIMEOUT_S,
              base_url: str = RELAY_URL) -> str:
    """Lässt den Relay sofort eine Testbenachrichtigung an das Handy dieses Geheimnisses senden
    (`POST /v1/test`, ohne Body; die Nutzlast kennt nur der Relay). Liefert genau eine Art:
    `ok`, `no_subscription`, `gone`, `too_soon`, `rate_limited`, `unknown_route`, `offline`,
    `push_failed` (ggf. `push_failed:<Status|network|build>`), `unauthorized` oder `server`. Wirft nie, loggt weder Geheimnis noch Ausnahmetext."""
    request = urllib.request.Request(f"{base_url}/v1/test", method="POST")
    request.add_header("Authorization", f"Bearer {secret}")
    request.add_header("User-Agent", USER_AGENT)
    try:
        with (opener or _build_opener()).open(request, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            return "ok" if 200 <= status < 300 else "server"
    except urllib.error.HTTPError as error:
        kind = _kind_of(error.code, _error_body(error))
        log.warning("Relay: Testbenachrichtigung abgelehnt (HTTP %s, %s)", error.code, kind)
        return kind
    except OSError as error:
        # Offline, Zeitüberschreitung, TLS, Verbindung zurückgesetzt: nur die Art, nie der Text.
        log.warning("Relay: Testbenachrichtigung nicht gesendet (%s)", type(error).__name__)
        return "offline"
    except Exception as error:
        log.warning("Relay: Testbenachrichtigung nicht gesendet (%s)", type(error).__name__)
        return "server"
