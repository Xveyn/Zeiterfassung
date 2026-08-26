"""Pure Logik des Webhook-Versands (Tk-frei, stdlib-only).

Kein tkinter, keine Google-Imports, keine dritte Dependency — dieses Modul
ist die getestete Schicht des Features (siehe docs/known-limitations.md:
getestet wird Logik, nicht UI).
"""

import ipaddress
from urllib.parse import unquote, urlsplit

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


def is_private_host(host):
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
        # Rein numerisch ist es aber kein Name, sondern eine Dezimal-IP
        # (http://2130706433/ -> 127.0.0.1) — die gehört nicht hierher.
        return not host.isdigit()
    return any(ip in net for net in _PRIVATE_NETWORKS)


def validate_url(url):
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
