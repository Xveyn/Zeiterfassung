# pyright: reportOptionalMemberAccess=true
"""Die Box eines Handys am Relay löschen (#358), Tk-frei, stdlib-only.

Der Relay (`relay/`) hält je Kopplung eine Box (Postfach des Handy-Abgleichs). Sie verfällt nach
90 Tagen ohne Nutzung von selbst; wird die Kopplung gelöst, räumt der Desktop sie sofort ab
(`DELETE /v1/box`, das Box-Geheimnis als Bearer). Best effort: ist der Relay nicht erreichbar,
bleibt das Lösen gültig und die Box verfällt von selbst. `delete_box` wirft deshalb nie und loggt
weder das Geheimnis noch den Text einer Ausnahme (er könnte es enthalten).
Blockiert (Netz): nur im Worker aufrufen.
"""
from __future__ import annotations

import logging
import urllib.error
import urllib.request
from typing import Any

from src.mobile_relay_codec import BOX_SECRET_RE
from src.push_relay import RELAY_URL, TIMEOUT_S
from src.push_relay import _build_opener as _build_opener  # folgt keinem Redirect (Bearer-Token)

log = logging.getLogger(__name__)

USER_AGENT = "Zeiterfassung (Box-Relay)"


def _request(secret: str, base_url: str) -> urllib.request.Request:
    request = urllib.request.Request(f"{base_url}/v1/box", method="DELETE")
    request.add_header("Authorization", f"Bearer {secret}")
    request.add_header("User-Agent", USER_AGENT)
    return request


def delete_box(secret: str, *, opener: Any = None, timeout: float = TIMEOUT_S,
               base_url: str = RELAY_URL) -> bool:
    """Löscht die Box dieses Geheimnisses am Relay. `True` bei einer 2xx-Antwort **und** bei
    `401`: dann kennt der Relay die Box nicht (mehr), der Zweck ist erfüllt. `False` bei allem
    anderen (429, 5xx, offline, Zeitüberschreitung, Redirect). Ein Geheimnis in falscher Form
    wird ohne Netzaufruf mit `False` abgewiesen. Wirft nie; blockiert, nur im Worker aufrufen."""
    if not isinstance(secret, str) or BOX_SECRET_RE.fullmatch(secret) is None:
        return False
    try:
        with (opener or _build_opener()).open(_request(secret, base_url), timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            return 200 <= status < 300
    except urllib.error.HTTPError as error:
        if error.code == 401:
            log.debug("Relay: Box war schon weg (HTTP 401)")
            return True
        log.warning("Relay: Box nicht gelöscht (HTTP %s)", error.code)
    except Exception as error:
        # Offline, Zeitüberschreitung, TLS …: der Text der Ausnahme bleibt draußen (kann das
        # Geheimnis enthalten), die Art genügt.
        log.warning("Relay: Box nicht gelöscht (%s)", type(error).__name__)
    return False
