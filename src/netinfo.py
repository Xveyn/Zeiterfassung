# src/netinfo.py
"""LAN-Adressen des Rechners für die Handy-Erfassung (#221), Tk-frei, stdlib-only.

Die App bindet den Handy-Server nie auf `0.0.0.0`, sondern auf **eine** gewählte
private Adresse. Dieses Modul liefert die Kandidaten: nur private IPv4-Adressen
(RFC 1918), nie Loopback, Link-Local, `0.0.0.0`, Multicast oder Carrier-Grade-NAT
(Tailscale u. ä.).

Aufgezählt wird ohne Zusatzbibliothek: die Adresse der aktiven Route (UDP-Socket,
der nur `connect`et und nie sendet — das wählt die Route) und die Adressen, die
der Hostname auflöst. **Grenze:** unter Linux löst der Hostname oft nur
`127.0.1.1` auf; dann bleibt der Routen-Vorschlag der einzige Kandidat.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Callable

_log = logging.getLogger(__name__)

# TEST-NET-1 (RFC 5737): nie geroutet, aber `connect` auf UDP wählt trotzdem die
# Schnittstelle der Standardroute.
_PROBE = ("192.0.2.1", 9)


def is_lan_address(text: object) -> bool:
    """True für eine private IPv4-Adresse in kanonischer Schreibweise. Alles
    andere — auch Leerraum, führende Nullen, Unicode-Ziffern, Ports, IPv6 und
    Nicht-Text — ist keine."""
    if not isinstance(text, str) or not text.isascii():
        return False
    try:
        address = ipaddress.IPv4Address(text)
    except ValueError:
        return False
    if str(address) != text:                      # „192.168.1.20 " o. ä. kommt nie bis hier
        return False
    return (address.is_private and not address.is_loopback
            and not address.is_link_local and not address.is_unspecified
            and not address.is_multicast and not address.is_reserved)


def route_address(probe: tuple[str, int] = _PROBE) -> str | None:
    """Die Adresse, mit der dieser Rechner Pakete Richtung `probe` senden würde.
    `None` ohne Route (offline, Flugmodus)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(probe)                   # UDP: sendet nichts, wählt nur die Route
            return str(sock.getsockname()[0])
    except OSError:
        _log.debug("Keine Route für die LAN-Adresse", exc_info=True)
        return None


def interface_addresses() -> list[str]:
    """Die IPv4-Adressen, die der Hostname auflöst (leer, wenn die Auflösung scheitert)."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET,
                                   type=socket.SOCK_STREAM)
    except OSError:                               # auch `gaierror`
        _log.debug("Hostname nicht auflösbar", exc_info=True)
        return []
    return [str(info[4][0]) for info in infos]


def lan_candidates(*, route: Callable[[], str | None] = route_address,
                   interfaces: Callable[[], list[str]] = interface_addresses) -> list[str]:
    """Die LAN-Adressen dieses Rechners, die der Routen-Adresse zuerst (sie ist der
    Vorschlag), ohne Duplikate."""
    found: list[str] = []
    for address in [route(), *interfaces()]:
        if address is not None and is_lan_address(address) and address not in found:
            found.append(address)
    return found


def pick_address(configured: str, candidates: list[str]) -> str | None:
    """Die Adresse, auf die gebunden wird. `configured` leer → der Vorschlag (erster
    Kandidat). Gesetzt → genau diese, aber nur wenn es sie noch gibt: eine
    verschwundene Adresse (DHCP, anderes WLAN) wird **nicht** still durch eine andere
    ersetzt, der Nutzer soll wählen."""
    if not configured:
        return candidates[0] if candidates else None
    return configured if configured in candidates else None
