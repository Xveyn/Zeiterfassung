"""Das Relay-Objekt eines Handys abräumen (#331), Tk-frei, stdlib-only.

Der Push-Relay (`relay/`, ein Cloudflare Worker) hält je Handy ein Objekt mit Abo und Zeitplan. Es
räumt sich nach 90 Tagen selbst auf; beim **Widerruf** eines Geräts löscht der Desktop es sofort
(`DELETE /v1/device`, das Geheimnis des Handys als Bearer). Best effort: ist der Relay nicht
erreichbar, bleibt der Widerruf gültig und das Objekt verfällt von selbst. `delete_device` wirft
deshalb nie und loggt weder das Geheimnis noch den Text einer Ausnahme (er könnte es enthalten).
Blockiert (Netz): nur im Worker aufrufen.
"""
from __future__ import annotations

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
