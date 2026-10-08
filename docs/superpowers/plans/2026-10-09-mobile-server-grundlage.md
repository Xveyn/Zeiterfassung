# Mobile Erfassung, PR 4a von 9: Server-Grundlage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der `ApiServer` der lokalen API (#92) wird für eine zweite Instanz im LAN tauglich (#221): ein Prüfer kann „abgelaufen" und „widerrufen" melden, einzelne Routen sind ohne Token erreichbar (`/v1/pair`), und der Server beantwortet CORS samt Preflight für genau eine Origin. Dazu `netinfo` (LAN-Adressen). Noch keine Mobil-Routen, kein `MobileService`, keine Settings-Keys, keine UI: das ist PR 4b.

**Architecture:** `api_auth` bekommt `Denied` (der Prüfer unterscheidet „unbekannt" von „bekannt, aber abgelehnt"), `authorize_public` (dieselben Tore ohne Token) und `SCOPE_MOBILE`. `api_server` nimmt statt des festen `ApiContext` eine `Surface` (Dispatch-Funktion, Methodentabelle, öffentliche Routen, CORS an/aus); ohne Angabe baut er die bisherige lokale Surface, das Verhalten der lokalen API bleibt Bit für Bit gleich. `netinfo` ist rein (die Socket-Aufrufe kommen als Parameter herein).

**Tech Stack:** Python 3.12, stdlib. Keine neue Abhängigkeit.

**Spec:** `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md` (Abschnitte „Bausteine" → `netinfo.py`, „Server", „Protokoll" → Statuscodes). PR-Zuschnitt dort: Punkt 4, hier in 4a/4b geteilt (Server-Grundlage / Routen und Dienst).

**Voraussetzung:** PR 2 (#252) und PR 3 (#255) sind gemergt.

**Branching:** `feat/mobile-server-grundlage` vom aktuellen `master`; der PR zielt auf `master`, trägt `Refs #221`, kein `Closes`. Kein Versionsbump.

## Rulings aus der Planung

- **`Denied` statt eines zweiten Prüfer-Typs.** Der Prüfer liefert `Principal | Denied | None`; `Denied(code)` wird zu `401 <code>`. Die Spec verlangt `401 unauthorized|token_expired|token_revoked`, und `Principal | None` kann „abgelaufen" nicht von „unbekannt" unterscheiden. Bestehende Prüfer (`single_token_verifier`) bleiben unverändert.
- **`authorize_public` teilt die Tore** (Methode → Host → Origin → `Sec-Fetch-Site` → Content-Type) mit `authorize` über einen gemeinsamen Helfer, sonst driften zwei Kopien. Die Reihenfolge von `authorize` bleibt exakt.
- **Öffentlich ist nur ein exaktes (Methode, Pfad)-Paar** (`Surface.public`), kein Muster. Ein `Authorization`-Header an einer öffentlichen Route wird ignoriert.
- **`ApiServer(context, …)` bleibt aufrufkompatibel;** neu ist das Schlüsselwort `surface`. Mindestens eines von beiden muss gegeben sein. `api_service` und alle bestehenden Tests ändern sich nicht.
- **`OPTIONS` wird nur bei `surface.cors` vor `authorize` behandelt.** Für die lokale API bleibt es bei `405` aus `authorize` (Origin-Header → `403`, nie ein CORS-Header).
- **Der Preflight prüft Host, Origin und Methode, nicht das Token** (Browser senden im Preflight keinen `Authorization`-Header) und berührt keinen Store: er trägt keine Daten.
- **CORS-Header an jeder Antwort für die erlaubte Origin,** auch an `401`/`403`/`500`: die PWA muss `token_expired` lesen können, sonst sieht sie nur einen Netzwerkfehler. Für eine nicht erlaubte Origin gibt es nie einen CORS-Header, auch nicht am `403 bad_origin`. Nie `Allow-Credentials`.
- **`Access-Control-Allow-Private-Network: true` nur, wenn der Preflight es anfragt** (`Access-Control-Request-Private-Network: true`). Die Spec nennt es nicht; Chromes frühere Private-Network-Access-Regel verlangt es, es kostet nichts und der Android-Test (#248) kann es dann nicht übersehen.
- **`Sec-Fetch-Site` bleibt ein Tor** (Spec: „die Auth-Tore bleiben"). Risiko, das nur der Android-Test klärt: sendet Chrome den Header doch an `http://<LAN-IP>`, scheitert jede Anfrage mit `403 browser_request`. Eine Policy-Option dafür gibt es bewusst noch nicht (YAGNI); der Vermerk gehört in die Prüfliste #248.
- **`netinfo` zählt nur private IPv4-Adressen** (RFC 1918), nie Loopback, Link-Local, `0.0.0.0` oder Carrier-Grade-NAT (Tailscale). Aufzählung der Schnittstellen ohne Zusatzbibliothek: Adresse der aktiven Route (UDP-Socket ohne Senden) plus `getaddrinfo(gethostname())`. **Bekannte Grenze:** unter Linux liefert der Hostname oft nur `127.0.1.1`; dann bleibt der Routen-Vorschlag der einzige Kandidat. Eine vollständige Aufzählung (`ioctl`) ist ein Folge-Issue, wenn der Android-Test mehrere Adapter zeigt.

## Global Constraints

- Tk-frei, stdlib-only, vollständig annotiert (`netinfo.py` kommt in `ANNOTATED_MODULES`, `api_auth.py`/`api_server.py` sind es ggf. schon); `ruff check .` und `pyright 1.1.411` sauber.
- Die lokale API verhält sich unverändert: **alle bestehenden Tests** (`tests/test_api_*.py`) bleiben ohne Änderung grün.
- Fail-closed: wirft ein Prüfer, ist das eine `500` ohne Details, nie ein Zugang.
- Kein Token, kein Code, kein Hash im Log.
- Server-Obergrenzen (32 Verbindungen, Body-Limit, Socket-Timeouts, Gesamtfrist) gelten auch an öffentlichen Routen.

## Review Focus

1. **Preflight ohne Daten:** `OPTIONS` ruft `dispatch` nie auf, braucht kein Token, antwortet `204` ohne Body; falscher Host, fehlende oder fremde Origin, unbekannter Pfad, nicht geroutete Methode → `403`/`404`/`405` ohne CORS-Header. Task 4.
2. **CORS-Grenzen:** `Access-Control-Allow-Origin` echot nur die erlaubte Origin, `Vary: Origin` dabei, nie `Allow-Credentials`; `401`/`403 bad_host`/`500` tragen die Header für die erlaubte Origin, `403 bad_origin` nicht. Task 4.
3. **Öffentliche Route:** nur exakt (Methode, Pfad); `GET` auf denselben Pfad, ein Pfad mit Schrägstrich dahinter und ein Nachbarpfad verlangen ein Token; Host/Origin/`Sec-Fetch-Site`/Content-Type gelten auch dort. Task 3.
4. **Denied-Codes:** `token_expired`/`token_revoked` kommen als `401` mit `WWW-Authenticate: Bearer` an; ein Prüfer, der wirft, gibt `500` ohne Details; `None` bleibt `401 unauthorized`. Task 3.
5. **Lokale API unverändert:** `OPTIONS` → `405`, ein Origin-Header → `403` ohne CORS-Header, `Allow` bei `405` aus der Methodentabelle der Surface. Tasks 3 und 4.
6. **netinfo gegen Müll:** `"0.0.0.0"`, `"127.0.0.1"`, `"169.254.1.1"`, `"100.64.0.1"`, `"8.8.8.8"`, `"192.168.1.256"`, `"192.168.001.001"`, Unicode-Ziffern, `None`, Zahlen → keine LAN-Adresse; eine verschwundene Adresse wird nie stillschweigend durch eine andere ersetzt. Task 2.

---

### Task 1: `api_auth` — `Denied`, `authorize_public`, `SCOPE_MOBILE`

**Files:**
- Modify: `src/api_auth.py`
- Modify: `tests/test_api_auth.py`

**Interfaces:** Produces: `SCOPE_MOBILE = "mobile-sync"`; `Denied(code: str)` (frozen dataclass); `TokenVerifier = Callable[[str], Principal | Denied | None]`; `ANONYMOUS = Principal("anonymous", frozenset())`; `authorize_public(method, headers, policy) -> AuthResult` (bei Erfolg `status 200`, `principal = ANONYMOUS`). `authorize` übersetzt `Denied(code)` in `AuthResult(401, code)`.

- [ ] **Step 1: Write the failing tests**

Hänge an `tests/test_api_auth.py` an (die Importzeile oben um `ANONYMOUS, SCOPE_MOBILE, Denied, authorize_public` ergänzen):

```python
# --- Denied und öffentliche Routen (#221) ------------------------------------------------------

LAN_POLICY = Policy(allowed_hosts=frozenset({"192.168.1.20:17654"}),
                    allowed_origins=frozenset({"https://xveyn.github.io"}),
                    bind_host="192.168.1.20")
LAN_HEADERS = {"Host": "192.168.1.20:17654", "Origin": "https://xveyn.github.io",
               "Authorization": "Bearer abc", "Content-Type": "application/json"}


@pytest.mark.parametrize("code", ["token_expired", "token_revoked"])
def test_a_denied_verdict_becomes_a_401_with_its_own_code(code):
    result = authorize("POST", LAN_HEADERS, LAN_POLICY, lambda token: Denied(code))
    assert (result.status, result.code, result.principal) == (401, code, None)


def test_an_unknown_token_is_still_plain_unauthorized():
    result = authorize("POST", LAN_HEADERS, LAN_POLICY, lambda token: None)
    assert (result.status, result.code) == (401, "unauthorized")


def test_a_principal_with_the_mobile_scope_passes():
    principal = Principal("device-0001", frozenset({SCOPE_MOBILE}))
    result = authorize("POST", LAN_HEADERS, LAN_POLICY, lambda token: principal)
    assert result.ok and result.principal is principal
    assert require_scope(principal, SCOPE_MOBILE).ok
    assert require_scope(principal, SCOPE_LOCAL).status == 403


def test_the_gates_still_run_before_the_verifier():
    called = []

    def verifier(token):
        called.append(token)
        return Denied("token_expired")

    wrong_host = dict(LAN_HEADERS, Host="evil.example:17654")
    assert authorize("POST", wrong_host, LAN_POLICY, verifier).code == "bad_host"
    assert authorize("POST", dict(LAN_HEADERS, Origin="https://evil.example"),
                     LAN_POLICY, verifier).code == "bad_origin"
    assert called == []


def test_public_authorize_needs_no_token_and_yields_the_anonymous_principal():
    headers = {k: v for k, v in LAN_HEADERS.items() if k != "Authorization"}

    result = authorize_public("POST", headers, LAN_POLICY)

    assert result.ok and result.principal is ANONYMOUS
    assert ANONYMOUS.scopes == frozenset()
    assert require_scope(ANONYMOUS, SCOPE_MOBILE).status == 403


def test_public_authorize_ignores_an_authorization_header():
    assert authorize_public("POST", LAN_HEADERS, LAN_POLICY).ok


@pytest.mark.parametrize("override,expected", [
    ({"Host": "evil.example:17654"}, (403, "bad_host")),
    ({"Origin": "https://evil.example"}, (403, "bad_origin")),
    ({"Sec-Fetch-Site": "cross-site"}, (403, "browser_request")),
    ({"Content-Type": "text/plain"}, (415, "unsupported_media_type")),
])
def test_public_authorize_keeps_the_other_gates(override, expected):
    headers = dict(LAN_HEADERS, **override)
    result = authorize_public("POST", headers, LAN_POLICY)
    assert (result.status, result.code) == expected and result.principal is None


def test_public_authorize_rejects_unknown_methods():
    assert authorize_public("PATCH", LAN_HEADERS, LAN_POLICY).status == 405
    assert authorize_public("OPTIONS", LAN_HEADERS, LAN_POLICY).status == 405
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_api_auth.py -q -p no:cacheprovider -x`
Expected: ERROR beim Sammeln: `ImportError: cannot import name 'ANONYMOUS' from 'src.api_auth'`.

- [ ] **Step 3: Implement**

In `src/api_auth.py` ersetze

```python
SCOPE_LOCAL = "local"
```

durch

```python
SCOPE_LOCAL = "local"
SCOPE_MOBILE = "mobile-sync"
```

Ersetze

```python
TokenVerifier = Callable[[str], "Principal | None"]
```

durch

```python
@dataclass(frozen=True)
class Denied:
    """Der Prüfer kennt das Token, lässt es aber nicht zu (`token_expired`,
    `token_revoked`). `None` heißt dagegen „unbekannt" (`unauthorized`); ohne
    diese Unterscheidung könnte die PWA nicht zwischen „neu koppeln" und
    „Token falsch" unterscheiden."""
    code: str


TokenVerifier = Callable[[str], "Principal | Denied | None"]

# Wer an einer öffentlichen Route (ohne Token) anfragt: keine Rechte.
ANONYMOUS = Principal("anonymous", frozenset())
```

Ersetze

```python
def _bearer_principal(value: str | None, verifier: TokenVerifier) -> Principal | None:
```

durch

```python
def _bearer_principal(value: str | None,
                      verifier: TokenVerifier) -> Principal | Denied | None:
```

Ersetze den Körper von `authorize` ab `# Methoden sind case-sensitive` bis zum `return AuthResult(200, "ok", principal)` durch:

```python
    h = {name.lower(): value for name, value in headers.items()}
    refused = _gate(method, h, policy)
    if refused is not None:
        return refused
    found = _bearer_principal(h.get("authorization"), verifier)
    if isinstance(found, Denied):
        return AuthResult(401, found.code)
    if found is None:
        return AuthResult(401, "unauthorized")
    if method in _BODY_METHODS and not _is_json(h.get("content-type")):
        return AuthResult(415, "unsupported_media_type")
    return AuthResult(200, "ok", found)
```

und füge **vor** `def authorize(` ein:

```python
def _gate(method: str, h: Mapping[str, str], policy: Policy) -> AuthResult | None:
    """Die Tore vor dem Token, gemeinsam für `authorize` und `authorize_public`;
    `h` hat kleingeschriebene Namen. `None` heißt: durch."""
    # Methoden sind case-sensitive (RFC 9110): kein `.upper()`. Das Routing
    # vergleicht exakt; eine großgeschriebene Sicht hier und eine rohe dort wären
    # zwei Wahrheiten über dieselbe Anfrage.
    if method not in ALLOWED_METHODS:
        return AuthResult(405, "method_not_allowed")
    # Nur HTTP-OWS (Leerzeichen, Tab) abschneiden: `str.strip()` nähme auch NBSP,
    # U+2028 und \x85.
    if h.get("host", "").strip(" \t").lower() not in policy.allowed_hosts:
        return AuthResult(403, "bad_host")
    origin = h.get("origin")
    if origin is not None and origin not in policy.allowed_origins:
        return AuthResult(403, "bad_origin")
    if "sec-fetch-site" in h:
        return AuthResult(403, "browser_request")
    return None


def authorize_public(method: str, headers: Mapping[str, str],
                     policy: Policy) -> AuthResult:
    """Dieselben Tore wie `authorize`, aber ohne Token: für Routen, die ein Gerät
    erst koppeln (`/v1/pair`). Ein `Authorization`-Header wird ignoriert."""
    h = {name.lower(): value for name, value in headers.items()}
    refused = _gate(method, h, policy)
    if refused is not None:
        return refused
    if method in _BODY_METHODS and not _is_json(h.get("content-type")):
        return AuthResult(415, "unsupported_media_type")
    return AuthResult(200, "ok", ANONYMOUS)


```

(Die Kommentare, die vorher im Körper von `authorize` standen, ziehen mit in `_gate`; in `authorize` bleibt der Docstring.)

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_api_auth.py tests/test_api_server.py tests/test_api_routes.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/api_auth.py`
Expected: PASS (die bestehenden Tests unverändert grün), `All checks passed!`, `0 errors`.

- [ ] **Step 5: Commit**

~~~bash
git add src/api_auth.py tests/test_api_auth.py
git commit -m "feat(api): Denied-Urteile und Prüfung ohne Token für die LAN-Instanz (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 2: `netinfo` — LAN-Adressen

**Files:**
- Create: `src/netinfo.py`
- Create: `tests/test_netinfo.py`
- Modify: `tests/test_type_annotations.py` (Whitelist)

**Interfaces:** Produces: `is_lan_address(text: object) -> bool`; `route_address(probe=("192.0.2.1", 9)) -> str | None`; `interface_addresses() -> list[str]`; `lan_candidates(*, route=route_address, interfaces=interface_addresses) -> list[str]` (Routen-Adresse zuerst, dedupliziert, nur LAN-Adressen); `pick_address(configured: str, candidates: list[str]) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_netinfo.py`:

```python
# tests/test_netinfo.py
import pytest

from src import netinfo


@pytest.mark.parametrize("text", ["192.168.1.20", "10.0.0.5", "172.16.0.1", "172.31.255.254"])
def test_private_ipv4_addresses_are_lan_addresses(text):
    assert netinfo.is_lan_address(text)


@pytest.mark.parametrize("text", [
    "0.0.0.0", "127.0.0.1", "127.0.1.1", "169.254.1.1", "100.64.0.1", "8.8.8.8",
    "172.32.0.1", "224.0.0.1", "255.255.255.255", "192.168.1.256", "192.168.001.001",
    "192.168.1", "192.168.1.20 ", " 192.168.1.20", "192.168.1.20:17654", "::1",
    "fe80::1", "fd00::1", "", "localhost", "１９２.１６８.１.２０", "192.168.1.20\n",
    None, 5, 192168120, b"192.168.1.20", ["192.168.1.20"],
])
def test_everything_else_is_not_a_lan_address(text):
    assert not netinfo.is_lan_address(text)


def test_route_address_uses_a_udp_socket_without_sending(monkeypatch):
    events = []

    class FakeSocket:
        def __init__(self, family, kind):
            events.append(("socket", family, kind))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def connect(self, address):
            events.append(("connect", address))

        def getsockname(self):
            return ("192.168.1.20", 54321)

        def sendto(self, *args):                  # darf nie gerufen werden
            events.append(("send",))

        send = sendall = sendto

    monkeypatch.setattr(netinfo.socket, "socket", FakeSocket)

    assert netinfo.route_address(("192.0.2.1", 9)) == "192.168.1.20"
    assert events[0][2] == netinfo.socket.SOCK_DGRAM
    assert ("connect", ("192.0.2.1", 9)) in events and ("send",) not in events


def test_route_address_is_none_without_a_route(monkeypatch):
    class Broken:
        def __init__(self, *args):
            raise OSError(101, "Network is unreachable")

    monkeypatch.setattr(netinfo.socket, "socket", Broken)
    assert netinfo.route_address() is None


def test_interface_addresses_come_from_the_host_name(monkeypatch):
    monkeypatch.setattr(netinfo.socket, "gethostname", lambda: "rechner")
    monkeypatch.setattr(netinfo.socket, "getaddrinfo", lambda host, port, **kw: [
        (2, 1, 6, "", ("192.168.1.20", 0)), (2, 1, 6, "", ("10.0.0.5", 0))])

    assert netinfo.interface_addresses() == ["192.168.1.20", "10.0.0.5"]


def test_interface_addresses_survive_a_failing_lookup(monkeypatch):
    def boom(*args, **kwargs):
        raise netinfo.socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(netinfo.socket, "getaddrinfo", boom)
    assert netinfo.interface_addresses() == []


def test_candidates_put_the_route_address_first_and_drop_duplicates_and_non_lan():
    result = netinfo.lan_candidates(
        route=lambda: "192.168.1.20",
        interfaces=lambda: ["127.0.1.1", "10.0.0.5", "192.168.1.20", "169.254.3.4", "8.8.8.8"])

    assert result == ["192.168.1.20", "10.0.0.5"]


def test_candidates_without_a_route_use_the_interfaces():
    assert netinfo.lan_candidates(route=lambda: None,
                                  interfaces=lambda: ["10.0.0.5"]) == ["10.0.0.5"]


def test_candidates_are_empty_when_nothing_is_a_lan_address():
    assert netinfo.lan_candidates(route=lambda: "127.0.0.1", interfaces=lambda: []) == []


def test_the_real_candidates_are_all_lan_addresses():
    # Läuft auf jedem Rechner, auch ohne Netz (dann leer).
    assert all(netinfo.is_lan_address(a) for a in netinfo.lan_candidates())


@pytest.mark.parametrize("configured,candidates,expected", [
    ("", ["192.168.1.20", "10.0.0.5"], "192.168.1.20"),          # leer = Vorschlag
    ("", [], None),
    ("10.0.0.5", ["192.168.1.20", "10.0.0.5"], "10.0.0.5"),        # gewählte Adresse gibt es noch
    ("10.0.0.9", ["192.168.1.20", "10.0.0.5"], None),            # verschwunden: nie still ersetzt
    ("garbage", ["192.168.1.20"], None),
])
def test_pick_address(configured, candidates, expected):
    assert netinfo.pick_address(configured, candidates) == expected
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_netinfo.py -q -p no:cacheprovider -x`
Expected: ERROR beim Sammeln: `ImportError: cannot import name 'netinfo' from 'src'`.

- [ ] **Step 3: Implement**

Create `src/netinfo.py`:

```python
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
```

In `tests/test_type_annotations.py` ersetze

```python
    "src/api_summary.py",
```

durch

```python
    "src/api_summary.py",
    "src/netinfo.py",
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_netinfo.py tests/test_type_annotations.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/netinfo.py`
Expected: PASS, `All checks passed!`, `0 errors`. (Schlägt `"192.168.1.20 "` im Test fehl, weil `IPv4Address` Leerraum selbst ablehnt, ist das richtig: dann ist die `str(address) != text`-Zeile nur ein zweiter Riegel.)

- [ ] **Step 5: Commit**

~~~bash
git add src/netinfo.py tests/test_netinfo.py tests/test_type_annotations.py
git commit -m "feat(mobile): LAN-Adress-Kandidaten für den Handy-Server (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 3: `Surface` — Dispatch, öffentliche Routen, Denied im Server

**Files:**
- Modify: `src/api_routes.py` (`methods_for_path`)
- Modify: `src/api_server.py`
- Create: `tests/test_api_server_surface.py`

**Interfaces:** Consumes: `authorize`, `authorize_public`, `Denied`, `ANONYMOUS` (Task 1). Produces: `api_routes.methods_for_path(path: str) -> frozenset[str]`; `api_server.Surface(dispatch, methods, route_methods, public=frozenset(), cors=False)`; `api_server.local_surface(context) -> Surface`; `ApiServer(context | None, verifier, *, port, policy_for_port, surface=None)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_server_surface.py`:

```python
# tests/test_api_server_surface.py
import http.client
import json

import pytest

from src.api_auth import SCOPE_MOBILE, Denied, Policy, Principal
from src.api_routes import ApiRequest, ApiResponse
from src.api_server import ApiServer, Surface

ORIGIN = "https://xveyn.github.io"
GOOD, EXPIRED, REVOKED = "G" * 43, "E" * 43, "R" * 43
ROUTES = {"/v1/ping": frozenset({"GET"}), "/v1/pair": frozenset({"POST"}),
          "/v1/sync": frozenset({"POST"})}


def verify(token):
    if token == GOOD:
        return Principal("device-0001", frozenset({SCOPE_MOBILE}))
    if token == EXPIRED:
        return Denied("token_expired")
    if token == REVOKED:
        return Denied("token_revoked")
    return None


def make_surface(calls, *, cors=False):
    def dispatch(request: ApiRequest, principal: Principal) -> ApiResponse:
        if request.path not in ROUTES:
            return ApiResponse(404, {"error": {"code": "not_found", "message": "Unbekannt."}})
        calls.append((request.method, request.path, principal.name))
        return ApiResponse(200, {"who": principal.name, "path": request.path,
                                 "body": request.body.decode("utf-8")})

    return Surface(dispatch=dispatch, methods=frozenset({"GET", "POST"}),
                   route_methods=lambda path: ROUTES.get(path, frozenset()),
                   public=frozenset({("POST", "/v1/pair")}), cors=cors)


@pytest.fixture
def make_server():
    servers = []

    def build(*, cors=False, verifier=verify):
        calls = []

        def policy_for(port):
            return Policy(allowed_hosts=frozenset({f"127.0.0.1:{port}"}),
                          allowed_origins=frozenset({ORIGIN}), bind_host="127.0.0.1")

        server = ApiServer(None, verifier, port=0, policy_for_port=policy_for,
                           surface=make_surface(calls, cors=cors))
        server.start()
        server.calls = calls
        servers.append(server)
        return server

    yield build
    for server in servers:
        server.stop()


def call(server, method, path, headers=None, body=None, token=GOOD):
    merged = {} if token is None else {"Authorization": f"Bearer {token}"}
    merged.update(headers or {})
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    try:
        conn.putrequest(method, path, skip_host="Host" in merged, skip_accept_encoding=True)
        for name, value in merged.items():
            conn.putheader(name, value)
        if body is not None:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body)
        response = conn.getresponse()
        raw = response.read()
        return response, (json.loads(raw) if raw else None), raw
    finally:
        conn.close()


JSON = {"Content-Type": "application/json"}


def code(parsed):
    return parsed["error"]["code"]


# --- Surface statt ApiContext -------------------------------------------------------------------

def test_the_dispatch_of_the_surface_serves_authenticated_routes(make_server):
    server = make_server()

    response, body, _ = call(server, "GET", "/v1/ping")

    assert response.status == 200 and body["who"] == "device-0001"
    assert server.calls == [("GET", "/v1/ping", "device-0001")]


def test_a_server_needs_a_context_or_a_surface():
    with pytest.raises(ValueError):
        ApiServer(None, verify)


@pytest.mark.parametrize("token,expected", [
    (EXPIRED, "token_expired"), (REVOKED, "token_revoked"), ("X" * 43, "unauthorized"),
    (None, "unauthorized"),
])
def test_denied_verdicts_reach_the_client_as_401(make_server, token, expected):
    server = make_server()

    response, body, _ = call(server, "GET", "/v1/ping", token=token)

    assert response.status == 401 and code(body) == expected
    assert response.getheader("WWW-Authenticate") == "Bearer"
    assert server.calls == []


def test_a_verifier_that_raises_is_a_500_without_details(make_server):
    def broken(token):
        raise RuntimeError("geheimer Zustand")

    server = make_server(verifier=broken)

    response, body, raw = call(server, "GET", "/v1/ping")

    assert response.status == 500 and code(body) == "internal_error"
    assert b"geheimer" not in raw and server.calls == []


def test_the_allow_header_of_a_405_comes_from_the_surface(make_server):
    server = make_server()

    response, body, _ = call(server, "PATCH", "/v1/ping")

    assert response.status == 405 and response.getheader("Allow") == "GET, POST"


# --- öffentliche Routen -----------------------------------------------------------------------------

def test_a_public_route_needs_no_token(make_server):
    server = make_server()

    response, body, _ = call(server, "POST", "/v1/pair", JSON, b'{"code": "x"}', token=None)

    assert response.status == 200 and body["who"] == "anonymous"
    assert server.calls == [("POST", "/v1/pair", "anonymous")]


def test_a_public_route_ignores_an_authorization_header(make_server):
    server = make_server()

    _, body, _ = call(server, "POST", "/v1/pair", JSON, b"{}", token=EXPIRED)

    assert body["who"] == "anonymous"


@pytest.mark.parametrize("method,path", [
    ("GET", "/v1/pair"), ("POST", "/v1/pair/"), ("POST", "/v1/pair/x"), ("POST", "/v1/pairs"),
    ("POST", "/v1/sync"), ("PUT", "/v1/pair"),
])
def test_only_the_exact_method_and_path_are_public(make_server, method, path):
    server = make_server()

    response, body, _ = call(server, method, path, JSON, b"{}", token=None)

    assert response.status == 401 and code(body) == "unauthorized"
    assert server.calls == []


@pytest.mark.parametrize("headers,status,expected", [
    ({"Content-Type": "text/plain"}, 415, "unsupported_media_type"),
    ({"Origin": "https://evil.example", **JSON}, 403, "bad_origin"),
    ({"Sec-Fetch-Site": "cross-site", **JSON}, 403, "browser_request"),
    ({"Host": "evil.example", **JSON}, 403, "bad_host"),
])
def test_a_public_route_keeps_the_other_gates(make_server, headers, status, expected):
    server = make_server()

    response, body, _ = call(server, "POST", "/v1/pair", headers, b"{}", token=None)

    assert response.status == status and code(body) == expected
    assert server.calls == []


def test_the_query_string_does_not_turn_a_protected_path_public(make_server):
    server = make_server()

    response, body, _ = call(server, "POST", "/v1/sync?x=/v1/pair", JSON, b"{}", token=None)

    assert response.status == 401 and server.calls == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_api_server_surface.py -q -p no:cacheprovider -x`
Expected: ERROR beim Sammeln: `ImportError: cannot import name 'Surface' from 'src.api_server'`.

- [ ] **Step 3: Implement**

In `src/api_routes.py` ersetze

```python
def routed_methods() -> frozenset[str]:
```

durch (neue Funktion davor, `routed_methods` bleibt unverändert darunter)

```python
def methods_for_path(path: str) -> frozenset[str]:
    """Die Methoden, die ROUTES für genau diesen Pfad kennen (leer = unbekannter Pfad)."""
    return frozenset(route.method for route in ROUTES if route.pattern.fullmatch(path))


def routed_methods() -> frozenset[str]:
```

In `src/api_server.py`:

1. Ersetze

```python
from collections.abc import Callable
from typing import Any, cast
from urllib.parse import parse_qs

from src.api_auth import AuthResult, Policy, TokenVerifier, authorize
from src.api_routes import (
    ApiContext, ApiRequest, ApiResponse, error_response, handle, routed_methods,
)
```

durch

```python
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import parse_qs

from src.api_auth import (
    AuthResult, Policy, Principal, TokenVerifier, authorize, authorize_public,
)
from src.api_routes import (
    ApiContext, ApiRequest, ApiResponse, error_response, handle, methods_for_path,
    routed_methods,
)
```

2. Ergänze in `_AUTH_MESSAGES` nach der Zeile `"unauthorized": …`:

```python
    "token_expired": "Das Token ist abgelaufen. Das Gerät muss neu gekoppelt werden.",
    "token_revoked": "Das Token wurde widerrufen. Das Gerät muss neu gekoppelt werden.",
```

3. Ersetze

```python
def _auth_error(auth: AuthResult) -> ApiResponse:
    headers: dict[str, str] = {}
    if auth.status == 405:
        # Was die Routen tatsächlich können, nicht `ALLOWED_METHODS`: POST ist für
        # #221 vorgesehen, aber keine Route kennt es.
        headers["Allow"] = ", ".join(sorted(routed_methods()))
```

durch

```python
@dataclass(frozen=True)
class Surface:
    """Was eine Server-Instanz ausliefert: die lokale API (Loopback, ein Token) und
    die Handy-Instanz (LAN, Gerätetoken, CORS) teilen sich diesen Server und
    unterscheiden sich nur hierin.

    `dispatch` bekommt eine bereits authentifizierte Anfrage. `methods` ist, was
    irgendeine Route kann (`Allow` bei einem 405 aus `authorize`, nicht
    `ALLOWED_METHODS`), `route_methods(path)` was genau dieser Pfad kann (leer =
    unbekannt; der Preflight fragt es). `public` sind (Methode, Pfad)-Paare, die
    ohne Token erreichbar sind — exakt, kein Muster. `cors` schaltet Preflight und
    CORS-Header für die erlaubten Origins der Policy ein."""
    dispatch: Callable[[ApiRequest, Principal], ApiResponse]
    methods: frozenset[str]
    route_methods: Callable[[str], frozenset[str]]
    public: frozenset[tuple[str, str]] = frozenset()
    cors: bool = False


def local_surface(context: ApiContext) -> Surface:
    return Surface(dispatch=lambda request, principal: handle(request, context, principal),
                   methods=routed_methods(), route_methods=methods_for_path)


def _auth_error(auth: AuthResult, allowed_methods: frozenset[str]) -> ApiResponse:
    headers: dict[str, str] = {}
    if auth.status == 405:
        headers["Allow"] = ", ".join(sorted(allowed_methods))
```

4. In `_Handler._respond` ersetze

```python
        headers = dict(self.headers.items())
        auth = authorize(self.command, headers, server.policy, server.verifier)
        if not auth.ok or auth.principal is None:
            return _auth_error(auth)
```

durch

```python
        headers = dict(self.headers.items())
        path = self.path.partition("?")[0]
        surface = server.surface
        if (self.command, path) in surface.public:
            auth = authorize_public(self.command, headers, server.policy)
        else:
            auth = authorize(self.command, headers, server.policy, server.verifier)
        if not auth.ok or auth.principal is None:
            return _auth_error(auth, surface.methods)
```

ersetze `path, _, raw_query = self.path.partition("?")` durch `raw_query = self.path.partition("?")[2]` und `return handle(request, server.context, auth.principal)` durch `return surface.dispatch(request, auth.principal)`.

5. In `_ApiHTTPServer.__init__` ersetze

```python
                 verifier: TokenVerifier, context: ApiContext) -> None:
        self.verifier = verifier
        self.context = context
```

durch

```python
                 verifier: TokenVerifier, surface: Surface) -> None:
        self.verifier = verifier
        self.surface = surface
```

6. In `ApiServer.__init__` ersetze

```python
    def __init__(self, context: ApiContext, verifier: TokenVerifier, *, port: int = 0,
                 policy_for_port: Callable[[int], Policy] = Policy.loopback) -> None:
        self._context = context
        self._verifier = verifier
```

durch

```python
    def __init__(self, context: ApiContext | None, verifier: TokenVerifier, *, port: int = 0,
                 policy_for_port: Callable[[int], Policy] = Policy.loopback,
                 surface: Surface | None = None) -> None:
        if surface is None:
            if context is None:
                raise ValueError("ApiServer braucht einen Kontext oder eine Surface")
            surface = local_surface(context)
        self._surface = surface
        self._verifier = verifier
```

und in `start()` `self._verifier, self._context)` durch `self._verifier, self._surface)`.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_api_server_surface.py tests/test_api_server.py tests/test_api_service.py tests/test_api_routes.py tests/test_api_wiring.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/api_server.py src/api_routes.py`
Expected: PASS (alle bestehenden API-Tests unverändert), `All checks passed!`, `0 errors`. Greift ein bestehender Test auf `server.context` zu, ist das ein Plan-Fehler: Ruling und `_ApiHTTPServer.context` nicht wieder einführen, sondern den Test auf die Surface umstellen.

- [ ] **Step 5: Commit**

~~~bash
git add src/api_routes.py src/api_server.py tests/test_api_server_surface.py
git commit -m "feat(api): Surface mit öffentlichen Routen und Denied-Codes im Server (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 4: CORS und Preflight

**Files:**
- Modify: `src/api_server.py`
- Modify: `tests/test_api_server_surface.py`
- Modify: `tests/test_api_server.py` (ein Test für die lokale API)

**Interfaces:** Consumes: `Surface.cors`, `Surface.route_methods`, `Policy.allowed_origins`. Produces: bei `cors=True`: `OPTIONS` wird vor `authorize` beantwortet (`204` ohne Body oder `403`/`404`/`405` ohne CORS-Header); jede Antwort auf eine Anfrage mit erlaubter Origin trägt `Access-Control-Allow-Origin: <Origin>` und `Vary: Origin`; nie `Access-Control-Allow-Credentials`.

- [ ] **Step 1: Write the failing tests**

Hänge an `tests/test_api_server_surface.py` an:

```python
# --- CORS ---------------------------------------------------------------------------------------------

def preflight(server, path="/v1/sync", method="POST", headers=None, drop=()):
    merged = {"Origin": ORIGIN, "Access-Control-Request-Method": method,
              "Access-Control-Request-Headers": "authorization, content-type"}
    merged.update(headers or {})
    for name in drop:
        merged.pop(name, None)
    return call(server, "OPTIONS", path, merged, token=None)


def test_a_preflight_is_a_204_without_body_and_needs_no_token(make_server):
    server = make_server(cors=True)

    response, body, raw = preflight(server)

    assert response.status == 204 and raw == b"" and body is None
    assert response.getheader("Content-Type") is None
    assert response.getheader("Access-Control-Allow-Origin") == ORIGIN
    assert response.getheader("Vary") == "Origin"
    assert response.getheader("Access-Control-Allow-Methods") == "POST"
    assert response.getheader("Access-Control-Allow-Headers") == "Authorization, Content-Type"
    assert response.getheader("Access-Control-Max-Age") == "600"
    assert response.getheader("Access-Control-Allow-Credentials") is None
    assert response.getheader("Access-Control-Allow-Private-Network") is None
    assert server.calls == []                          # der Preflight trägt keine Daten


def test_the_preflight_answers_the_private_network_request(make_server):
    server = make_server(cors=True)

    response, _, _ = preflight(server, headers={"Access-Control-Request-Private-Network": "true"})

    assert response.getheader("Access-Control-Allow-Private-Network") == "true"


@pytest.mark.parametrize("kwargs,status", [
    ({"headers": {"Origin": "https://evil.example"}}, 403),
    ({"drop": ("Origin",)}, 403),
    ({"headers": {"Host": "evil.example"}}, 403),
    ({"path": "/v1/unbekannt"}, 404),
    ({"path": "/v1/ping", "method": "POST"}, 405),                  # /v1/ping kennt nur GET
    ({"method": "DELETE"}, 405),
    ({"drop": ("Access-Control-Request-Method",)}, 405),
])
def test_a_refused_preflight_has_no_cors_headers(make_server, kwargs, status):
    server = make_server(cors=True)

    response, body, _ = preflight(server, **kwargs)

    assert response.status == status and "error" in body
    assert response.getheader("Access-Control-Allow-Origin") is None
    assert response.getheader("Access-Control-Allow-Methods") is None
    assert server.calls == []


def test_responses_for_the_allowed_origin_carry_cors_headers_even_when_they_are_errors(make_server):
    server = make_server(cors=True)

    ok, _, _ = call(server, "GET", "/v1/ping", {"Origin": ORIGIN})
    expired, body, _ = call(server, "GET", "/v1/ping", {"Origin": ORIGIN}, token=EXPIRED)
    missing, _, _ = call(server, "GET", "/v1/unbekannt", {"Origin": ORIGIN})

    for response in (ok, expired, missing):
        assert response.getheader("Access-Control-Allow-Origin") == ORIGIN
        assert response.getheader("Vary") == "Origin"
        assert response.getheader("Access-Control-Allow-Credentials") is None
    assert (ok.status, expired.status, missing.status) == (200, 401, 404)
    assert code(body) == "token_expired"


def test_a_public_route_answers_the_allowed_origin_too(make_server):
    server = make_server(cors=True)

    response, _, _ = call(server, "POST", "/v1/pair", {"Origin": ORIGIN, **JSON}, b"{}", token=None)

    assert response.status == 200
    assert response.getheader("Access-Control-Allow-Origin") == ORIGIN


def test_a_server_error_carries_cors_headers_for_the_allowed_origin(make_server):
    def broken(token):
        raise RuntimeError("x")

    server = make_server(cors=True, verifier=broken)

    response, body, _ = call(server, "GET", "/v1/ping", {"Origin": ORIGIN})

    assert response.status == 500
    assert response.getheader("Access-Control-Allow-Origin") == ORIGIN


def test_a_foreign_origin_gets_a_403_without_cors_headers(make_server):
    server = make_server(cors=True)

    response, body, _ = call(server, "GET", "/v1/ping", {"Origin": "https://evil.example"})

    assert response.status == 403 and code(body) == "bad_origin"
    assert response.getheader("Access-Control-Allow-Origin") is None


def test_requests_without_origin_get_no_cors_headers(make_server):
    server = make_server(cors=True)

    response, _, _ = call(server, "GET", "/v1/ping")

    assert response.status == 200
    assert response.getheader("Access-Control-Allow-Origin") is None
    assert response.getheader("Vary") is None


def test_without_the_cors_switch_options_stays_a_405(make_server):
    server = make_server(cors=False)

    response, body, _ = preflight(server)

    assert response.status == 405
    assert response.getheader("Access-Control-Allow-Origin") is None
    ok, _, _ = call(server, "GET", "/v1/ping", {"Origin": ORIGIN})
    assert ok.getheader("Access-Control-Allow-Origin") is None
```

Hänge an `tests/test_api_server.py` an:

```python
def test_the_local_api_still_answers_neither_options_nor_cors(server):
    origin = {"Origin": "https://xveyn.github.io"}
    options, _, _ = http_call(server, "OPTIONS", "/v1/status",
                              headers={**origin, "Access-Control-Request-Method": "GET"})
    get, body, _ = http_call(server, "GET", "/v1/status", headers=origin)

    assert options.status == 405 and options.getheader("Access-Control-Allow-Origin") is None
    assert get.status == 403 and error_code(body) == "bad_origin"
    assert get.getheader("Access-Control-Allow-Origin") is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_api_server_surface.py -q -p no:cacheprovider -x`
Expected: FAIL: `test_a_preflight_is_a_204_without_body_and_needs_no_token` (`assert 405 == 204` oder `403`).

- [ ] **Step 3: Implement**

In `src/api_server.py`, `class _Handler`:

1. Ersetze in `_send`

```python
        payload = json.dumps(response.body).encode("utf-8")
        self.close_connection = True
        try:
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
```

durch

```python
        # 204 (Preflight) trägt nie einen Body und keinen Content-Type.
        payload = b"" if response.status == 204 else json.dumps(response.body).encode("utf-8")
        self.close_connection = True
        try:
            self.send_response(response.status)
            if response.status != 204:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
```

2. Ersetze in `_serve` `self._send(response)` (die letzte Zeile der Methode) durch `self._send(self._with_cors(response))` und füge **nach** `_serve` ein:

```python
    def _with_cors(self, response: ApiResponse) -> ApiResponse:
        """CORS-Header für die erlaubte Origin, an jeder Antwort — auch an Fehlern: die
        PWA muss `token_expired` lesen können, sonst sieht sie nur einen Netzwerkfehler.
        Eine fremde Origin bekommt nie einen, auch nicht am `403 bad_origin`. Nie
        `Allow-Credentials`: die Anmeldung läuft über den Authorization-Header."""
        server = cast("_ApiHTTPServer", self.server)
        if not server.surface.cors:
            return response
        origin = self.headers.get("Origin")
        if origin is None or origin not in server.policy.allowed_origins:
            return response
        return ApiResponse(response.status, response.body,
                           {**response.headers, "Access-Control-Allow-Origin": origin,
                            "Vary": "Origin"})

    def _preflight(self, headers: dict[str, str], path: str) -> ApiResponse:
        """`OPTIONS` einer CORS-Surface. Prüft Host, Origin und Methode, nicht das
        Token (Browser senden im Preflight keinen Authorization-Header), und berührt
        keinen Store."""
        server = cast("_ApiHTTPServer", self.server)
        h = {name.lower(): value for name, value in headers.items()}
        if h.get("host", "").strip(" \t").lower() not in server.policy.allowed_hosts:
            return _auth_error(AuthResult(403, "bad_host"), server.surface.methods)
        origin = h.get("origin")
        if origin is None or origin not in server.policy.allowed_origins:
            return _auth_error(AuthResult(403, "bad_origin"), server.surface.methods)
        methods = server.surface.route_methods(path)
        if not methods:
            return error_response(404, "not_found", "Unbekannter Pfad.")
        if h.get("access-control-request-method") not in methods:
            return error_response(405, "method_not_allowed", "Methode nicht erlaubt.",
                                  {"Allow": ", ".join(sorted(methods))})
        reply = {
            "Access-Control-Allow-Methods": ", ".join(sorted(methods)),
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Max-Age": "600",
        }
        if h.get("access-control-request-private-network", "").lower() == "true":
            reply["Access-Control-Allow-Private-Network"] = "true"
        return ApiResponse(204, None, reply)
```

3. In `_respond` füge **vor** `if (self.command, path) in surface.public:` ein:

```python
        if surface.cors and self.command == "OPTIONS":
            return self._preflight(headers, path)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_api_server_surface.py tests/test_api_server.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/api_server.py`
Expected: PASS, `All checks passed!`, `0 errors`. (`authorize` prüft die Methode vor Host und Origin: `OPTIONS` ohne CORS-Surface ist deshalb immer `405`.)

- [ ] **Step 5: Commit**

~~~bash
git add src/api_server.py tests/test_api_server_surface.py tests/test_api_server.py
git commit -m "feat(api): CORS und Preflight für die Handy-Instanz (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 5: Doku

**Files:**
- Modify: `CLAUDE.md`, `src/CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md`

- [ ] **Step 1: Edit the docs**

In `CLAUDE.md` ersetze

```markdown
- `src/api_routes.py`, `src/api_server.py`, `src/api_service.py` — lokale HTTP-API
```

durch (neue Zeile davor, die vorhandene bleibt unverändert)

```markdown
- `src/netinfo.py` — LAN-Adressen für die Handy-Erfassung (#221): nur private IPv4-Adressen, Aufzählung ohne Zusatzbibliothek (Routen-Adresse per UDP-Socket ohne Senden, Hostname-Auflösung), `pick_address` ersetzt eine verschwundene Adresse nie still. Tk-frei, die Socket-Aufrufe kommen als Parameter herein
- `src/api_routes.py`, `src/api_server.py`, `src/api_service.py` — lokale HTTP-API
```

In `src/CLAUDE.md` ersetze (Anker: Zeile 698)

```markdown
- `api_server.py` — HTTP-Server der lokalen API: `ApiServer(context, verifier,
```

durch

```markdown
- `api_server.py` — HTTP-Server, seit #221 für zwei Instanzen gebaut: die lokale API (Loopback, ein Token) und die Handy-Instanz (LAN, Gerätetoken) teilen sich ihn und unterscheiden sich in der **`Surface`** (`dispatch`, `methods` für `Allow`, `route_methods(path)` für den Preflight, `public` = exakte (Methode, Pfad)-Paare ohne Token, `cors`); `ApiServer(context, …)` baut ohne Angabe die lokale (`local_surface`). Bei `cors=True` wird `OPTIONS` **vor** `authorize` beantwortet (Host, Origin, Methode; kein Token, kein Store, `204` ohne Body), und jede Antwort auf die erlaubte Origin trägt `Access-Control-Allow-Origin` + `Vary: Origin`, auch Fehler (die PWA muss `token_expired` lesen können); eine fremde Origin nie, `Allow-Credentials` nie. Ein Prüfer liefert `Principal | Denied | None` (`Denied(code)` → `401 <code>`). Für die lokale API ändert sich nichts. Zur lokalen API: `ApiServer(context, verifier,
```

In `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md` ergänze am Ende des Abschnitts „Server" (nach dem Satz „Body-Limit, Socket-Timeouts und die Obergrenze gleichzeitiger Verbindungen wie `api_server`.") einen Absatz:

```markdown

**Umsetzung (PR 4a):** Der Prüfer liefert `Principal | Denied | None`; `Denied("token_expired"|"token_revoked")` wird zu `401` mit diesem Code. `POST /v1/pair` ist als einziges (Methode, Pfad)-Paar öffentlich, mit denselben Toren Host/Origin/`Sec-Fetch-Site`/Content-Type. CORS-Header tragen alle Antworten auf die erlaubte Origin, auch Fehler; der Preflight antwortet auf `Access-Control-Request-Private-Network: true` mit `Access-Control-Allow-Private-Network: true`. Risiko für den Android-Test (#248): sendet Chrome `Sec-Fetch-Site` doch an `http://<LAN-IP>`, scheitert jede Anfrage mit `403 browser_request`.
```

- [ ] **Step 2: Run to verify**

Run: `python3 -m pytest tests/test_claude_md_claims.py tests/test_type_annotations.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check .`
Expected: PASS, `All checks passed!`.

- [ ] **Step 3: Commit**

~~~bash
git add CLAUDE.md src/CLAUDE.md docs/superpowers/specs/2026-10-08-mobile-pwa-design.md
git commit -m "docs(mobile): Server-Grundlage in CLAUDE.md und Spec (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

## Mutationsprüfung (nach Task 5, vor dem Review)

Jeden Mutanten einzeln anwenden (`PYTHONDONTWRITEBYTECODE=1`, Datei sichern, genau eine Ersetzung, Tests laufen lassen, zurückkopieren). Jeder muss mindestens einen Test rot färben:

| Datei | Mutation | Erwartet rot |
|---|---|---|
| `api_auth.py` | `Denied` wie `None` behandeln (`isinstance(found, Denied)`-Zweig entfernen) | `test_a_denied_verdict_becomes_a_401_with_its_own_code` |
| `api_auth.py` | `_gate` in `authorize_public` überspringen | `test_public_authorize_keeps_the_other_gates` |
| `api_auth.py` | Content-Type-Prüfung in `authorize_public` entfernen | `test_public_authorize_keeps_the_other_gates` |
| `api_auth.py` | Verifier vor `_gate` aufrufen | `test_the_gates_still_run_before_the_verifier` |
| `netinfo.py` | `is_loopback`-Ausschluss entfernen | `test_everything_else_is_not_a_lan_address` |
| `netinfo.py` | `is_link_local`-Ausschluss entfernen | `test_everything_else_is_not_a_lan_address` |
| `netinfo.py` | `text.isascii()` entfernen | `test_everything_else_is_not_a_lan_address` |
| `netinfo.py` | `pick_address`: verschwundene Adresse durch `candidates[0]` ersetzen | `test_pick_address` |
| `netinfo.py` | Duplikatprüfung `address not in found` entfernen | `test_candidates_put_the_route_address_first_and_drop_duplicates_and_non_lan` |
| `netinfo.py` | `sock.connect(probe)` → `sock.sendto(b"", probe)` | `test_route_address_uses_a_udp_socket_without_sending` |
| `api_server.py` | `public` mit `startswith` statt exaktem Paar | `test_only_the_exact_method_and_path_are_public` |
| `api_server.py` | Pfad für `public` mit Query statt `partition` | `test_the_query_string_does_not_turn_a_protected_path_public` |
| `api_server.py` | `authorize_public` auch für nicht öffentliche Routen | `test_denied_verdicts_reach_the_client_as_401` |
| `api_server.py` | `_preflight` ruft `dispatch` | `test_a_preflight_is_a_204_without_body_and_needs_no_token` |
| `api_server.py` | Preflight ohne Host-Prüfung | `test_a_refused_preflight_has_no_cors_headers` |
| `api_server.py` | Preflight ohne Origin-Prüfung | `test_a_refused_preflight_has_no_cors_headers` |
| `api_server.py` | `Access-Control-Allow-Origin: *` statt Echo | `test_responses_for_the_allowed_origin_carry_cors_headers_even_when_they_are_errors` |
| `api_server.py` | CORS-Header auch für fremde Origin | `test_a_foreign_origin_gets_a_403_without_cors_headers` |
| `api_server.py` | `Vary: Origin` entfernen | `test_a_preflight_is_a_204_without_body_and_needs_no_token` |
| `api_server.py` | `Allow-Credentials: true` ergänzen | `test_a_preflight_is_a_204_without_body_and_needs_no_token` |
| `api_server.py` | 204 mit `Content-Type` und Body `null` senden | `test_a_preflight_is_a_204_without_body_and_needs_no_token` |
| `api_server.py` | `_with_cors` nur für `status < 400` | `test_responses_for_the_allowed_origin_carry_cors_headers_even_when_they_are_errors` |
| `api_server.py` | `surface.cors`-Prüfung in `_respond` entfernen | `test_without_the_cors_switch_options_stays_a_405`, `test_the_local_api_still_answers_neither_options_nor_cors` |
| `api_server.py` | `Allow` wieder aus `routed_methods()` statt `surface.methods` | `test_the_allow_header_of_a_405_comes_from_the_surface` |

Überlebt ein Mutant, ist das ein Testfehler: Test schärfen, gegen den Mutanten rot sehen, committen.

## Finale

Nach Task 5: Review über den ganzen Branch mit einem frischen Reviewer auf dem leistungsfähigsten Modell (Review Focus und Rulings mitgeben; aktiver Angriff mit hostilen Headern, Pfaden und Origins über echte Sockets), Critical/Important in **einem** Fix-Durchlauf (je Fix ein Test, der zuerst rot war), Minors ins Ledger und in ein Issue. Danach `finishing-a-development-branch`: PR gegen `master` (`Refs #221`, „PR 4a von 9" im Titel).

**Danach PR 4b:** `mobile_routes` (die vier Routen: `pair`, `ping`, `categories`, `sync`), Gerätetoken-Erneuerung und `last_pull_at` im selben Schritt wie das Apply (Vertrag aus #254), `MobileService` (Lebenszyklus, Statusgründe, verschwundene Adresse), Settings-Keys `mobile_enabled`/`mobile_port`/`mobile_address`. Offen davor: die Entscheidung zur Karenz des vorherigen Tokens (#253).
