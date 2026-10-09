# Mobile Erfassung, PR 4b von 9: Routen und Dienst — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Handy-Instanz (#221) läuft: die vier Routen (`POST /v1/pair`, `GET /v1/ping`, `GET /v1/categories`, `POST /v1/sync`), ein Prüfer über die gekoppelten Geräte, die Tokenerneuerung samt `last_pull_at`, und der `MobileService` mit Lebenszyklus, Statusgründen und Geräteverwaltung. Dazu die drei Settings-Keys. **Noch nicht verdrahtet:** `ui.py`/`main.py` erzeugen den Dienst erst in PR 5 (Tab „Mobil").

**Architecture:** `mobile_routes.py` ist Tk-frei und ohne Socket: Routentabelle, `MobileContext`, `make_verifier` (über `mobile_pairing.authenticate`), Handler und `surface(ctx)` für den `ApiServer` aus PR 4a. `mobile_service.py` baut darauf den Lebenszyklus (Muster `ApiService`): Einstellungen lesen, LAN-Adresse wählen (`netinfo`), `ApiServer` mit LAN-`Policy` starten. Ein gemeinsamer `devices_lock` schützt jede Folge „Datensatz lesen → ändern → speichern" (Koppeln, Abgleich samt Tokenerneuerung, Widerruf).

**Tech Stack:** Python 3.12, stdlib. Keine neue Abhängigkeit.

**Spec:** `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md` (Abschnitte „Server", „Protokoll", „Pairing und Token", „Einschalten und Binden"). Vertrag aus Issue #254: `last_pull_at` des Handys wird im selben Schritt wie das Apply gespeichert.

**Voraussetzung:** PR 2 bis 4a (#252, #255, #257) sind gemergt.

**Branching:** `feat/mobile-routen-dienst` vom aktuellen `master`; der PR zielt auf `master`, trägt `Refs #221`, kein `Closes`. Kein Versionsbump.

## Rulings aus der Planung

- **Karenz des vorherigen Tokens bleibt wie in der Spec** (10 Minuten ab Erneuerung, `keep_previous` bei einer Anfrage mit dem vorherigen Token), weil #253 noch offen ist. Entscheidet der Nutzer anders, ändert das nur `mobile_pairing.renew`/`authenticate` (PR 2) und deren Tests, nicht diesen PR.
- **Ein `devices_lock` (RLock) in `MobileContext`** schützt Koppeln, Abgleich samt Tokenerneuerung und Widerruf. Sperrreihenfolge: `devices_lock` → `sync_guard` → `data_lock`; niemand nimmt sie in anderer Reihenfolge. Der Prüfer (`make_verifier`) läuft **vor** dem Handler ohne Lock und liest nur; der Abgleich liest den Datensatz deshalb unter dem Lock **neu** und lehnt einen inzwischen widerrufenen mit `401 token_revoked` ab.
- **Fehler im Body von `/v1/pair` und `/v1/sync` melden `400 invalid_json`** (auch ein ungültiges `device_id`), wie in PR 3: die Statuscode-Liste der Spec kennt keinen eigenen Code dafür.
- **`/v1/pair` prüft `device_id` und `protocol` vor dem Code und zählt dabei keinen Fehlversuch.** Ein ungültiges `device_id` antwortet immer `400`, ohne den Code anzusehen: das ist kein Orakel (der Code wird gar nicht geprüft) und verbrennt keinen gültigen Code. `protocol` ist im Pair-Request optional (die Spec zeigt es im Beispiel nicht), aber wenn vorhanden, muss es `1` sein.
- **Ein Fehler beim Speichern des Geräts nach erfolgreichem Einlösen ist eine `500`** (der Code ist dann verbraucht, der Nutzer öffnet einen neuen). Das gilt auch für `MobileStoreReadOnly`; die Anzeige übernimmt PR 5.
- **Die Tokenerneuerung und `last_pull_at = server_time` werden erst nach erfolgreichem `perform_sync` gespeichert,** im selben `devices_lock`-Abschnitt. Scheitert `perform_sync` (400/409/422/503), bleiben Token und `last_pull_at` unverändert. Scheitert nur das Speichern des Datensatzes (Platte), ist es eine `500` und das Handy wiederholt mit demselben Token; der Abgleich ist idempotent.
- **Der Prüfer liefert ein `MobilePrincipal`** (Unterklasse von `Principal` mit `record` und `via_previous`), damit der Handler nicht erneut authentifiziert. Scope ist `SCOPE_MOBILE`.
- **Routen sind exakte Pfade** (keine Muster, keine Pfadparameter) und kennen keine Query-Parameter (`400 unknown_parameter`).
- **Der Dienst bindet nur auf `pick_address(...)`** (gewählt oder Vorschlag); fehlt die gewählte Adresse, ist der Zustand `error` mit Grund `address_gone` und es läuft **nichts** (nie ein stiller Wechsel auf eine andere Adresse). Beim Stoppen wird die offene Kopplungssitzung geschlossen.
- **`allowed_hosts` ist genau `<ip>:<port>`**, `allowed_origins` genau `https://xveyn.github.io` (Konstante `PWA_ORIGIN`, zieht das Repo um, wird sie nachgezogen).
- **Geräteverwaltung (`list_devices`, `revoke`, `revoke_all`) und `pair_link` liegen im Dienst,** weil sie sich den `devices_lock` mit den Routen teilen müssen. Sie schreiben (Datei): im Worker aufrufen.

## Global Constraints

- Tk-frei, stdlib-only, vollständig annotiert (`mobile_routes.py`, `mobile_service.py` kommen in `ANNOTATED_MODULES`); `ruff check .` und `pyright 1.1.411` sauber.
- Weder Code noch Token noch Token-Hash im Log und in keiner Antwort außer dem frisch ausgegebenen Token an sein Gerät; Antworten und Logs nennen höchstens Geräte-ID und Name.
- Jeder `except` ist eng und begründet; ein Catch-all loggt (`tests/test_catch_all_handlers.py`).
- Die lokale API und ihre Tests bleiben unberührt.
- Settings-Keys `mobile_enabled`, `mobile_port`, `mobile_address` sind gerätelokal (nicht in `SYNCED_SETTING_KEYS`).
- Ablehnungen haben die Form `{"error": {"code", "message"}}` mit Codes aus der Statuscode-Liste der Spec.

## Review Focus

1. **Pairing von außen:** 5 Fehlversuche sperren die Sitzung (`429 pairing_locked`, auch ein richtiger Code danach); falscher, abgelaufener, verbrauchter Code und „kein Code aktiv" geben **dieselbe** Antwort `403 invalid_code`; ein ungültiges `device_id` ist `400` ohne Code-Prüfung; Müll im Body (Array, Zahl, NaN, tiefe Verschachtelung, riesige Strings, Surrogate) ist 4xx, nie 500. Tasks 3 und 5.
2. **Token-Lebenszyklus:** erneuert wird nur nach erfolgreichem Abgleich; das alte Token gilt 10 Minuten, bei einer Anfrage mit dem alten Token bleibt es erhalten (zwei verlorene Antworten sperren nicht aus); widerrufen und abgelaufen sind getrennte Codes; ein zwischen Prüfer und Handler widerrufenes Gerät kommt nicht durch. Task 4.
3. **`last_pull_at` (Vertrag #254):** wird mit dem Apply gespeichert, ein wiederholter Erstabgleich erzeugt keinen zweiten Konflikt. Task 4.
4. **Nebenläufigkeit:** zwei Abgleiche desselben Geräts gleichzeitig verlieren keine Tokenerneuerung (ein Datensatz-Stand wird nie mit einem veralteten überschrieben); Sperrreihenfolge ohne Deadlock gegen Drive-Sync (`sync_guard`) und UI-Saves (`data_lock`). Task 4.
5. **Bindung:** nur die gewählte LAN-Adresse, nie `0.0.0.0`; verschwundene Adresse = Fehler, kein Ersatz; falscher `Host`-Header = `403`; jeder Statuswechsel schließt die Kopplungssitzung. Task 5.
6. **Keine Geheimnisse:** kein Token, Code oder Hash in Logs und Antworten (außer dem eigenen neuen Token); Fehlertexte leaken keine Pfade. Tasks 3 bis 5.

---

### Task 1: Settings-Keys

**Files:**
- Modify: `src/settings.py`
- Modify: `tests/test_settings.py`

**Interfaces:** Produces: `DEFAULTS["mobile_enabled"] = False`, `DEFAULTS["mobile_port"] = 17654`, `DEFAULTS["mobile_address"] = ""`; keiner davon in `SYNCED_SETTING_KEYS`.

- [ ] **Step 1: Write the failing test**

Hänge an `tests/test_settings.py` an:

```python
def test_the_mobile_keys_are_device_local_with_safe_defaults():
    from src.settings import DEFAULTS, SYNCED_SETTING_KEYS
    assert DEFAULTS["mobile_enabled"] is False          # aus, bis es der Nutzer einschaltet
    assert DEFAULTS["mobile_port"] == 17654
    assert DEFAULTS["mobile_address"] == ""             # leer = Vorschlag der aktiven Route
    for key in ("mobile_enabled", "mobile_port", "mobile_address"):
        assert key not in SYNCED_SETTING_KEYS           # ein Wert, den sich zwei Rechner teilen, wäre falsch
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_settings.py -q -p no:cacheprovider -k mobile_keys`
Expected: FAIL: `KeyError: 'mobile_enabled'`.

- [ ] **Step 3: Implement**

In `src/settings.py` ersetze

```python
    "api_enabled": False,
    "api_port": 17653,
```

durch

```python
    "api_enabled": False,
    "api_port": 17653,
    # Handy-Erfassung per PWA (#221). Alle drei gerätelokal: eine Adresse oder ein
    # belegter Port eines anderen Rechners wäre hier falsch, und ein synchronisierter
    # Schalter würde das Handy-Netz auf einem Rechner einschalten, der es nie wollte.
    # `mobile_address` leer = der Vorschlag der aktiven Route (`netinfo`).
    "mobile_enabled": False,
    "mobile_port": 17654,
    "mobile_address": "",
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_settings.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check .`
Expected: PASS, `All checks passed!`.

- [ ] **Step 5: Commit**

~~~bash
git add src/settings.py tests/test_settings.py
git commit -m "feat(mobile): Settings-Keys für die Handy-Instanz (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 2: `mobile_routes` — Prüfer, Routing, `ping`, `categories`

**Files:**
- Create: `src/mobile_routes.py`
- Create: `tests/test_mobile_routes.py`

**Interfaces:** Consumes: `mobile_pairing.authenticate`, `api_auth` (PR 4a), `api_routes.ApiRequest/ApiResponse/error_response`, `api_server.Surface`, `mobile_sync`. Produces: `PWA_ORIGIN`, `PWA_URL`; `MobilePrincipal(name, scopes, record, via_previous)`; `MobileContext(pairing, devices, devices_lock, storage, settings, conflicts_store, base, desktop_name, now=utc_now_iso, today=date.today, data_lock=None, sync_guard=None, on_change=<no-op>, closing=<never>)`; `make_verifier(devices, now) -> TokenVerifier`; `dispatch(request, ctx, principal) -> ApiResponse`; `methods_for_path(path) -> frozenset[str]`; `routed_methods() -> frozenset[str]`; `surface(ctx) -> Surface`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mobile_routes.py`:

```python
# tests/test_mobile_routes.py
import datetime
import json
import threading
import types

import pytest

from src import mobile_pairing, mobile_routes
from src.api_auth import ANONYMOUS, SCOPE_LOCAL, SCOPE_MOBILE, Denied, Principal
from src.api_routes import ApiRequest
from src.conflicts_store import ConflictsStore
from src.mobile_pairing import PairingSession
from src.mobile_routes import MobilePrincipal
from src.mobile_store import MobileStore
from src.settings import Settings
from src.storage import Storage

NOW = "2026-10-08T12:00:00Z"
TODAY = datetime.date(2026, 10, 8)
PHONE = "phone-0001"


def make_env(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    settings.device_id_for_sync = "DESK"
    clock = {"now": NOW, "pairing": 1000.0}
    changes = []
    ctx = mobile_routes.MobileContext(
        pairing=PairingSession(lambda: clock["pairing"]),
        devices=MobileStore(str(tmp_path / "mobile_devices.json")),
        devices_lock=threading.RLock(),
        storage=Storage(str(tmp_path / "zeiterfassung.json"), device_id="DESK"),
        settings=settings,
        conflicts_store=ConflictsStore(str(tmp_path / "conflicts.json")),
        base=str(tmp_path),
        desktop_name=lambda: "Desktop",
        now=lambda: clock["now"],
        today=lambda: TODAY,
        on_change=lambda: changes.append(1))
    return types.SimpleNamespace(ctx=ctx, clock=clock, changes=changes)


@pytest.fixture
def env(tmp_path):
    return make_env(tmp_path)


def add_device(env, device_id=PHONE, name="Pixel", now=NOW):
    record, token = mobile_pairing.issue_device(device_id, name, now)
    env.ctx.devices.save(record)
    return record, token


def principal_for(env, token):
    return mobile_routes.make_verifier(env.ctx.devices, env.ctx.now)(token)


def call(env, method, path, *, body=b"", query=None, token=None, principal=None):
    if principal is None:
        principal = ANONYMOUS if token is None else principal_for(env, token)
    request = ApiRequest(method, path, query or {}, body)
    return mobile_routes.dispatch(request, env.ctx, principal)


def error_code(response):
    return response.body["error"]["code"]


# --- Prüfer ---------------------------------------------------------------------------------------

def test_a_valid_token_yields_a_mobile_principal_with_the_record(env):
    record, token = add_device(env)

    principal = principal_for(env, token)

    assert isinstance(principal, MobilePrincipal)
    assert principal.name == PHONE and principal.scopes == frozenset({SCOPE_MOBILE})
    assert principal.record["id"] == PHONE and principal.via_previous is False


def test_the_previous_token_is_flagged_as_such(env):
    record, token = add_device(env)
    renewed, _new = mobile_pairing.renew(record, NOW)
    env.ctx.devices.save(renewed)

    principal = principal_for(env, token)

    assert isinstance(principal, MobilePrincipal) and principal.via_previous is True


def test_an_expired_token_is_denied_as_expired(env):
    _record, token = add_device(env)
    env.clock["now"] = "2026-11-07T12:00:00Z"                 # genau expires_at

    assert principal_for(env, token) == Denied("token_expired")


def test_a_revoked_token_is_denied_as_revoked(env):
    record, token = add_device(env)
    env.ctx.devices.save(mobile_pairing.revoke(record))

    assert principal_for(env, token) == Denied("token_revoked")


@pytest.mark.parametrize("junk", ["", "x" * 43, "x" * 5000, "\ud800", "a b"])
def test_an_unknown_token_is_not_recognised(env, junk):
    add_device(env)
    assert principal_for(env, junk) is None


# --- Routing ----------------------------------------------------------------------------------------

def test_the_route_table_knows_only_its_own_routes():
    assert mobile_routes.methods_for_path("/v1/ping") == frozenset({"GET"})
    assert mobile_routes.methods_for_path("/v1/categories") == frozenset({"GET"})
    assert mobile_routes.methods_for_path("/v1/entries") == frozenset()      # nichts von der lokalen API
    assert mobile_routes.methods_for_path("/v1/status") == frozenset()
    assert mobile_routes.routed_methods() == frozenset({"GET"})


def test_the_surface_enables_cors_and_has_no_public_route_yet(env):
    surface = mobile_routes.surface(env.ctx)

    assert surface.public == frozenset()
    assert surface.cors is True and surface.methods == frozenset({"GET"})
    assert surface.route_methods("/v1/ping") == frozenset({"GET"})


def test_an_unknown_path_is_404(env):
    _record, token = add_device(env)
    for path in ("/v1/entries", "/v1/status", "/v1/ping/", "/v1/PING", "/"):
        assert call(env, "GET", path, token=token).status == 404


def test_a_wrong_method_is_405_with_allow(env):
    _record, token = add_device(env)

    response = call(env, "POST", "/v1/ping", token=token)

    assert response.status == 405 and response.headers["Allow"] == "GET"
    assert call(env, "POST", "/v1/categories", token=token).headers["Allow"] == "GET"


def test_query_parameters_are_rejected(env):
    _record, token = add_device(env)
    for path in ("/v1/ping", "/v1/categories"):
        response = call(env, "GET", path, token=token, query={"x": ["1"]})
        assert response.status == 400 and error_code(response) == "unknown_parameter"


def test_a_principal_without_the_mobile_scope_is_refused(env):
    local = Principal("local", frozenset({SCOPE_LOCAL}))

    assert call(env, "GET", "/v1/ping", principal=local).status == 403
    anonymous = call(env, "GET", "/v1/ping")
    assert anonymous.status == 403 and error_code(anonymous) == "insufficient_scope"


# --- ping und categories -------------------------------------------------------------------------

def test_ping_reports_protocol_time_and_window(env):
    _record, token = add_device(env)

    response = call(env, "GET", "/v1/ping", token=token)

    assert response.status == 200
    assert response.body == {"protocol": 1, "server_time": NOW, "window_days": 90}


def test_categories_are_the_configured_names_without_blanks_and_duplicates(env):
    _record, token = add_device(env)
    env.ctx.settings.set("categories", ["Projekt", "", "Projekt", "Intern"])

    response = call(env, "GET", "/v1/categories", token=token)

    assert response.status == 200 and response.body == {"categories": ["Projekt", "Intern"]}
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_mobile_routes.py -q -p no:cacheprovider -x`
Expected: ERROR beim Sammeln: `ImportError: cannot import name 'mobile_routes' from 'src'`.

- [ ] **Step 3: Implement**

Create `src/mobile_routes.py`:

```python
# src/mobile_routes.py
"""Routen der Handy-Instanz (#221), Tk-frei und ohne Socket.

Die zweite `ApiServer`-Instanz (LAN, Gerätetoken) liefert nur diese vier Routen:
`POST /v1/pair` (öffentlich, solange ein Code aktiv ist), `GET /v1/ping`,
`GET /v1/categories` und `POST /v1/sync`. Auth, Host- und Origin-Tore und CORS
macht der Server (`api_server`, `api_auth`); hier liegen Prüfer, Routing und
Handler. Alle Pfade sind exakte Zeichenketten, keine kennt Query-Parameter.

Der Prüfer (`make_verifier`) läuft **vor** dem Handler und liest nur. Jede Folge
„Datensatz lesen → ändern → speichern" (Koppeln, Abgleich samt Tokenerneuerung)
läuft im Handler unter `ctx.devices_lock`, und der Abgleich liest den Datensatz
dort neu: zwischen Prüfer und Handler kann ein Widerruf liegen.
Sperrreihenfolge: `devices_lock` → `sync_guard` → `data_lock`.
"""
from __future__ import annotations

import datetime
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src import mobile_pairing
from src.api_auth import SCOPE_MOBILE, Denied, Principal, TokenVerifier, require_scope
from src.api_routes import ApiRequest, ApiResponse, error_response
from src.api_server import Surface
from src.api_summary import category_names
from src.mobile_sync import PROTOCOL, WINDOW_DAYS, SyncError
from src.time_utils import utc_now_iso

if TYPE_CHECKING:
    from src.mobile_pairing import PairingSession
    from src.mobile_store import MobileStore

_log = logging.getLogger(__name__)

# Die gehostete PWA. Zieht das Repo um, müssen beide Konstanten (und die Doku) mit.
PWA_ORIGIN = "https://xveyn.github.io"
PWA_URL = "https://xveyn.github.io/Zeiterfassung/"


def _no_change() -> None:
    return None


def _never_closing() -> bool:
    return False


@dataclass(frozen=True)
class MobilePrincipal(Principal):
    """Ein authentifiziertes Handy: der Datensatz, mit dem der Prüfer das Token
    zugeordnet hat, und ob es das *vorherige* Token war (Karenzfenster)."""
    record: dict[str, Any]
    via_previous: bool = False


@dataclass(frozen=True)
class MobileContext:
    pairing: PairingSession
    devices: MobileStore
    devices_lock: threading.RLock
    storage: Any
    settings: Any
    conflicts_store: Any
    base: str
    desktop_name: Callable[[], str]
    now: Callable[[], str] = utc_now_iso
    today: Callable[[], datetime.date] = datetime.date.today
    data_lock: Any = None
    sync_guard: Any = None
    # `on_change` meldet der UI einen angewendeten Abgleich und läuft nach der Freigabe
    # aller Sperren. `closing` ist wahr, sobald die App beendet oder entfernt wird.
    on_change: Callable[[], None] = _no_change
    closing: Callable[[], bool] = _never_closing


class _MobileError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def make_verifier(devices: MobileStore, now: Callable[[], str]) -> TokenVerifier:
    """Prüfer für den Server: ordnet ein Token einem Gerät zu. `Denied` für
    abgelaufen und widerrufen (die PWA zeigt dann „Neu koppeln"), `None` für alles
    Unbekannte."""
    def verify(token: str) -> Principal | Denied | None:
        outcome = mobile_pairing.authenticate(devices.get_all(), token, now())
        if outcome.status == "ok" and outcome.record is not None:
            return MobilePrincipal(outcome.record["id"], frozenset({SCOPE_MOBILE}),
                                   outcome.record, outcome.via_previous)
        if outcome.status == "expired":
            return Denied("token_expired")
        if outcome.status == "revoked":
            return Denied("token_revoked")
        return None
    return verify


def _no_query(request: ApiRequest) -> None:
    if request.query:
        raise _MobileError(400, "unknown_parameter", "Diese Route kennt keine Query-Parameter.")


def _ping(request: ApiRequest, ctx: MobileContext, principal: Principal) -> ApiResponse:
    _no_query(request)
    return ApiResponse(200, {"protocol": PROTOCOL, "server_time": ctx.now(),
                             "window_days": WINDOW_DAYS})


def _categories(request: ApiRequest, ctx: MobileContext, principal: Principal) -> ApiResponse:
    _no_query(request)
    return ApiResponse(200, {"categories": category_names(ctx.settings)})


@dataclass(frozen=True)
class _Route:
    method: str
    path: str
    handler: Callable[[ApiRequest, MobileContext, Principal], ApiResponse]
    public: bool = False


ROUTES: tuple[_Route, ...] = (
    _Route("GET", "/v1/ping", _ping),
    _Route("GET", "/v1/categories", _categories),
)


def methods_for_path(path: str) -> frozenset[str]:
    return frozenset(route.method for route in ROUTES if route.path == path)


def routed_methods() -> frozenset[str]:
    return frozenset(route.method for route in ROUTES)


def dispatch(request: ApiRequest, ctx: MobileContext, principal: Principal) -> ApiResponse:
    """Eine bereits authentifizierte Anfrage (an einer öffentlichen Route mit dem
    anonymen Principal) → Antwort. Ein Programmfehler wirft durch; der Server macht
    daraus eine `500` ohne Details."""
    same_path = [route for route in ROUTES if route.path == request.path]
    if not same_path:
        return error_response(404, "not_found", "Unbekannter Pfad.")
    route = next((r for r in same_path if r.method == request.method), None)
    if route is None:
        return error_response(405, "method_not_allowed", "Methode nicht erlaubt.",
                              {"Allow": ", ".join(sorted(r.method for r in same_path))})
    if not route.public:
        denied = require_scope(principal, SCOPE_MOBILE)
        if not denied.ok:
            return error_response(denied.status, denied.code, "Dem Token fehlt die Berechtigung.")
    try:
        return route.handler(request, ctx, principal)
    except (_MobileError, SyncError) as exc:
        return error_response(exc.status, exc.code, exc.message)


def surface(ctx: MobileContext) -> Surface:
    return Surface(
        dispatch=lambda request, principal: dispatch(request, ctx, principal),
        methods=routed_methods(), route_methods=methods_for_path,
        public=frozenset((route.method, route.path) for route in ROUTES if route.public),
        cors=True)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_mobile_routes.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/mobile_routes.py`
Expected: PASS, `All checks passed!`, `0 errors`.

- [ ] **Step 5: Commit**

~~~bash
git add src/mobile_routes.py tests/test_mobile_routes.py
git commit -m "feat(mobile): Prüfer, Routing, ping und categories der Handy-Instanz (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 3: `POST /v1/pair`

**Files:**
- Modify: `src/mobile_routes.py`
- Modify: `tests/test_mobile_routes.py`

**Interfaces:** Consumes: `PairingSession.redeem`, `mobile_pairing.issue_device/normalize_device_id/clean_device_name`, `api_entry_write.load_json_body`, `MobileStore.get/save`. Produces: Route `POST /v1/pair` (öffentlich): `200 {"token", "expires_at", "window_days": 90, "desktop_name", "protocol": 1}`; `403 invalid_code`, `429 pairing_locked`, `400 invalid_json|invalid_protocol`, `503 shutting_down`.

- [ ] **Step 1: Write the failing tests**

Hänge an `tests/test_mobile_routes.py` an:

```python
# --- pair ---------------------------------------------------------------------------------------------

def pair_body(code, device_id=PHONE, name="Pixel von Sven", **extra):
    doc = {"code": code, "device_name": name, "device_id": device_id}
    doc.update(extra)
    return json.dumps(doc).encode()


def pair(env, code, **kwargs):
    return call(env, "POST", "/v1/pair", body=pair_body(code, **kwargs))


def test_the_pair_route_is_the_only_public_one(env):
    surface = mobile_routes.surface(env.ctx)

    assert surface.public == frozenset({("POST", "/v1/pair")})
    assert surface.methods == frozenset({"GET", "POST"})
    assert surface.route_methods("/v1/pair") == frozenset({"POST"})


def test_a_correct_code_pairs_the_device_and_returns_its_token(env):
    code = env.ctx.pairing.open()

    response = pair(env, code)

    assert response.status == 200
    body = response.body
    assert set(body) == {"token", "expires_at", "window_days", "desktop_name", "protocol"}
    assert (body["window_days"], body["desktop_name"], body["protocol"]) == (90, "Desktop", 1)
    assert body["expires_at"] == "2026-11-07T12:00:00Z"
    stored = env.ctx.devices.get(PHONE)
    assert stored["name"] == "Pixel von Sven" and stored["token_hash"] == mobile_pairing.hash_token(body["token"])
    assert isinstance(principal_for(env, body["token"]), MobilePrincipal)
    with open(env.ctx.devices.filepath, encoding="utf-8") as handle:
        assert body["token"] not in handle.read()                  # nur der Hash steht in der Datei


def test_the_code_is_single_use(env):
    code = env.ctx.pairing.open()
    assert pair(env, code).status == 200

    again = pair(env, code, device_id="phone-0002")

    assert again.status == 403 and error_code(again) == "invalid_code"
    assert env.ctx.devices.get("phone-0002") is None


def test_a_wrong_code_and_no_active_code_give_one_shared_answer(env):
    env.ctx.pairing.open()
    wrong = pair(env, "AAAA-AAAA")
    env.ctx.pairing.close()
    nothing_active = pair(env, "AAAA-AAAA")

    assert wrong.status == nothing_active.status == 403
    assert wrong.body == nothing_active.body and error_code(wrong) == "invalid_code"


def test_an_expired_code_gives_the_same_answer(env):
    code = env.ctx.pairing.open()
    env.clock["pairing"] += 300                                  # genau die Gültigkeit

    expired = pair(env, code)

    assert expired.status == 403 and expired.body == pair(env, "AAAA-AAAA").body


def test_five_wrong_codes_lock_the_session_even_for_the_right_one(env):
    code = env.ctx.pairing.open()

    results = [pair(env, "AAAA-AAAA").status for _ in range(5)]
    locked = pair(env, "AAAA-AAAA")
    right_but_locked = pair(env, code)

    assert results == [403] * 5
    assert locked.status == 429 and error_code(locked) == "pairing_locked"
    assert right_but_locked.status == 429
    assert env.ctx.devices.get(PHONE) is None


@pytest.mark.parametrize("device_id", [None, "", "kurz", "a" * 65, "mit leerzeichen!", 5, ["x"], "٢" * 10])
def test_an_invalid_device_id_is_400_without_looking_at_the_code(env, device_id):
    code = env.ctx.pairing.open()
    body = json.dumps({"code": code, "device_name": "P", "device_id": device_id}).encode()

    response = call(env, "POST", "/v1/pair", body=body)
    wrong_code = call(env, "POST", "/v1/pair", body=json.dumps(
        {"code": "AAAA-AAAA", "device_name": "P", "device_id": device_id}).encode())

    assert response.status == 400 and error_code(response) == "invalid_json"
    assert wrong_code.status == 400 and wrong_code.body == response.body      # kein Orakel
    assert pair(env, code).status == 200                                       # Code nicht verbrannt


def test_a_request_with_a_bad_device_id_never_counts_as_a_failed_attempt(env):
    code = env.ctx.pairing.open()
    for _ in range(10):
        call(env, "POST", "/v1/pair", body=json.dumps(
            {"code": "AAAA-AAAA", "device_id": "x"}).encode())

    assert pair(env, code).status == 200


@pytest.mark.parametrize("raw", [
    b"", b"{kaputt", b"[]", b'"x"', b"5", b'{"code": NaN}', b'{"a":1,"a":2}',
    pytest.param(b"[" * 100000, id="deep-nesting"), b"\xff",
])
def test_a_malformed_pair_body_is_400_invalid_json(env, raw):
    env.ctx.pairing.open()

    response = call(env, "POST", "/v1/pair", body=raw)

    assert response.status == 400 and error_code(response) == "invalid_json"


@pytest.mark.parametrize("protocol", [0, 2, "1", 1.0, True, None, [1]])
def test_a_present_but_wrong_protocol_is_400_invalid_protocol(env, protocol):
    code = env.ctx.pairing.open()

    response = pair(env, code, protocol=protocol)

    assert response.status == 400 and error_code(response) == "invalid_protocol"
    assert pair(env, code).status == 200                                       # Code nicht verbrannt


def test_protocol_one_is_accepted(env):
    assert pair(env, env.ctx.pairing.open(), protocol=1).status == 200


@pytest.mark.parametrize("code", [None, 5, "", ["x"], {"a": 1}, "٢" * 8, "A" * 5000])
def test_a_junk_code_is_a_failed_attempt_not_an_error(env, code):
    env.ctx.pairing.open()

    response = call(env, "POST", "/v1/pair", body=json.dumps(
        {"code": code, "device_name": "P", "device_id": PHONE}).encode())

    assert response.status == 403 and error_code(response) == "invalid_code"


def test_a_junk_name_becomes_the_default_name(env):
    code = env.ctx.pairing.open()
    body = json.dumps({"code": code, "device_id": PHONE, "device_name": "Pi\nxel\x00"}).encode()

    assert call(env, "POST", "/v1/pair", body=body).status == 200
    assert env.ctx.devices.get(PHONE)["name"] == "Pixel"


def test_pairing_again_keeps_the_sync_identity_and_lifts_a_revocation(env):
    old, _token = add_device(env, now="2026-10-01T08:00:00Z")
    old["last_pull_at"] = "2026-10-07T09:00:00Z"
    env.ctx.devices.save(mobile_pairing.revoke(old))
    code = env.ctx.pairing.open()

    response = pair(env, code, name="Pixel neu")

    assert response.status == 200
    stored = env.ctx.devices.get(PHONE)
    assert stored["created_at"] == "2026-10-01T08:00:00Z" and stored["last_pull_at"] == "2026-10-07T09:00:00Z"
    assert stored["revoked"] is False and stored["name"] == "Pixel neu"
    assert isinstance(principal_for(env, response.body["token"]), MobilePrincipal)


def test_pairing_is_refused_while_the_app_closes_and_keeps_the_code(env):
    code = env.ctx.pairing.open()
    closing = mobile_routes.MobileContext(**{**env.ctx.__dict__, "closing": lambda: True})

    response = mobile_routes.dispatch(
        ApiRequest("POST", "/v1/pair", {}, pair_body(code)), closing, ANONYMOUS)

    assert response.status == 503 and error_code(response) == "shutting_down"
    assert pair(env, code).status == 200


def test_a_query_string_on_pair_is_rejected(env):
    response = call(env, "POST", "/v1/pair", body=pair_body("AAAA-AAAA"), query={"x": ["1"]})
    assert response.status == 400 and error_code(response) == "unknown_parameter"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_mobile_routes.py -q -p no:cacheprovider -x`
Expected: FAIL: `test_the_pair_route_is_public` (`assert ('POST', '/v1/pair') in frozenset()`).

- [ ] **Step 3: Implement**

In `src/mobile_routes.py` ergänze die Importe

```python
from src.api_entry_write import WriteError, load_json_body
```

(einsortiert nach `from src.api_auth …`) und füge **vor** `@dataclass(frozen=True)\nclass _Route:` ein:

```python
def _json_object(body: bytes) -> dict[str, Any]:
    try:
        data = load_json_body(body)
    except WriteError as exc:
        raise _MobileError(400, "invalid_json", exc.message) from None
    if not isinstance(data, dict):
        raise _MobileError(400, "invalid_json", "Erwartet wird ein JSON-Objekt.")
    return data


def _refuse_while_closing(ctx: MobileContext) -> None:
    if ctx.closing():
        raise _MobileError(503, "shutting_down", "Die App wird gerade beendet.")


def _pair(request: ApiRequest, ctx: MobileContext, principal: Principal) -> ApiResponse:
    """Koppelt ein Handy. Erst Form und Gerät, dann der Code: ein ungültiges
    `device_id` antwortet `400`, ohne den Code zu prüfen — kein Orakel, und ein
    gültiger Code verbrennt dabei nicht."""
    _no_query(request)
    data = _json_object(request.body)
    if "protocol" in data:
        protocol = data["protocol"]
        if not isinstance(protocol, int) or isinstance(protocol, bool) or protocol != PROTOCOL:
            raise _MobileError(400, "invalid_protocol", f"Unterstützt wird protocol {PROTOCOL}.")
    device_id = mobile_pairing.normalize_device_id(data.get("device_id"))
    if device_id is None:
        raise _MobileError(400, "invalid_json", "device_id fehlt oder ist ungültig.")
    _refuse_while_closing(ctx)
    result = ctx.pairing.redeem(data.get("code"))
    if result is mobile_pairing.RedeemResult.LOCKED:
        raise _MobileError(429, "pairing_locked",
                           "Zu viele Fehlversuche. Am Desktop einen neuen Code erzeugen.")
    if result is not mobile_pairing.RedeemResult.OK:
        # Falsch, abgelaufen, verbraucht und „kein Code aktiv" sind dieselbe Antwort.
        raise _MobileError(403, "invalid_code", "Der Code ist ungültig oder abgelaufen.")
    with ctx.devices_lock:
        record, token = mobile_pairing.issue_device(
            device_id, mobile_pairing.clean_device_name(data.get("device_name")), ctx.now(),
            ctx.devices.get(device_id))
        ctx.devices.save(record)
    _log.info("Handy gekoppelt: %s (%s)", record["id"], record["name"])
    return ApiResponse(200, {"token": token, "expires_at": record["expires_at"],
                             "window_days": WINDOW_DAYS, "desktop_name": ctx.desktop_name(),
                             "protocol": PROTOCOL})


```

und ergänze in `ROUTES` als erste Zeile

```python
    _Route("POST", "/v1/pair", _pair, public=True),
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_mobile_routes.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/mobile_routes.py`
Expected: PASS, `All checks passed!`, `0 errors`. Die Tests `test_the_route_table_knows_only_its_own_routes` und `test_the_surface_enables_cors_and_has_no_public_route_yet` aus Task 2 beschreiben den Stand ohne `pair`: lösche sie in diesem Task (sie sind durch `test_the_pair_route_is_the_only_public_one` und die Routing-Tests abgelöst) und ersetze sie in Task 4 durch den Test für alle vier Routen (dort angegeben).

- [ ] **Step 5: Commit**

~~~bash
git add src/mobile_routes.py tests/test_mobile_routes.py
git commit -m "feat(mobile): Koppeln per Einmalcode (POST /v1/pair) (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 4: `POST /v1/sync` — Abgleich, Tokenerneuerung, `last_pull_at`

**Files:**
- Modify: `src/mobile_routes.py`
- Modify: `tests/test_mobile_routes.py`

**Interfaces:** Consumes: `mobile_sync.parse_request/perform_sync`, `mobile_pairing.renew`. Produces: Route `POST /v1/sync`: `200` = Antwort von `perform_sync` plus `"token"` (erneuert) und `"expires_at"`; Fehler aus `SyncError`; `401 token_revoked` bei inzwischen widerrufenem Gerät; `503 shutting_down`.

- [ ] **Step 1: Write the failing tests**

Hänge an `tests/test_mobile_routes.py` an:

```python
# --- sync ----------------------------------------------------------------------------------------------

SLOT = {"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}


def sync_body(env, entries=None, **over):
    doc = {"protocol": 1, "client_time": env.clock["now"], "last_pull_at": "",
           "entries": entries or {}}
    doc.update(over)
    return json.dumps(doc).encode()


def day(modified_at="2026-10-07T18:30:00Z", slots=(SLOT,), deleted=False):
    return {"slots": list(slots), "modified_at": modified_at, "deleted": deleted}


def sync(env, token, entries=None, **over):
    return call(env, "POST", "/v1/sync", body=sync_body(env, entries, **over), token=token)


def test_a_sync_applies_the_days_and_renews_the_token(env):
    record, token = add_device(env)

    response = sync(env, token, {"2026-10-07": day()})

    assert response.status == 200
    body = response.body
    assert body["protocol"] == 1 and body["server_time"] == NOW and body["last_pull_at"] == NOW
    assert body["entries"]["2026-10-07"]["device_id"] == PHONE
    assert env.ctx.storage.get_all_raw()["2026-10-07"]["device_id"] == PHONE
    assert body["token"] != token and body["expires_at"] == "2026-11-07T12:00:00Z"
    stored = env.ctx.devices.get(PHONE)
    assert stored["token_hash"] == mobile_pairing.hash_token(body["token"])
    assert stored["last_pull_at"] == NOW and stored["last_seen"] == NOW
    assert env.changes == [1]


def test_the_old_token_works_for_ten_minutes_after_the_renewal_and_the_new_one_always(env):
    _record, old = add_device(env)
    new = sync(env, old).body["token"]

    env.clock["now"] = "2026-10-08T12:10:00Z"
    inside = principal_for(env, old)
    env.clock["now"] = "2026-10-08T12:10:01Z"

    assert isinstance(inside, MobilePrincipal) and inside.via_previous is True
    assert principal_for(env, old) is None
    assert isinstance(principal_for(env, new), MobilePrincipal)


def test_a_lost_answer_twice_does_not_lock_the_phone_out(env):
    _record, t1 = add_device(env)
    sync(env, t1)                                            # Antwort mit t2 geht verloren
    env.clock["now"] = "2026-10-08T12:05:00Z"

    second = sync(env, t1)                                   # Handy sendet weiter mit t1
    t3 = second.body["token"]                                # auch diese Antwort geht verloren
    env.clock["now"] = "2026-10-08T12:06:00Z"

    assert second.status == 200
    assert isinstance(principal_for(env, t1), MobilePrincipal)      # t1 gilt noch
    assert isinstance(principal_for(env, t3), MobilePrincipal)


def test_a_rejected_sync_neither_renews_the_token_nor_moves_last_pull_at(env):
    record, token = add_device(env)
    before = env.ctx.devices.get(PHONE)

    bad_json = call(env, "POST", "/v1/sync", body=b"{kaputt", token=token)
    skew = sync(env, token, client_time="2026-10-08T13:00:00Z")
    invalid = sync(env, token, {"2026-10-07": day(slots=())})

    assert (bad_json.status, skew.status, invalid.status) == (400, 409, 422)
    assert error_code(skew) == "clock_skew" and error_code(invalid) == "invalid_entry"
    assert env.ctx.devices.get(PHONE) == before
    assert env.ctx.storage.get_all_raw() == {} and env.changes == []


def test_a_busy_sync_guard_is_503_and_keeps_the_token(env):
    _record, token = add_device(env)
    before = env.ctx.devices.get(PHONE)
    guard = threading.Lock()
    guard.acquire()
    busy = mobile_routes.MobileContext(**{**env.ctx.__dict__, "sync_guard": guard})

    response = mobile_routes.dispatch(
        ApiRequest("POST", "/v1/sync", {}, sync_body(env)), busy, principal_for(env, token))

    assert response.status == 503 and error_code(response) == "busy"
    assert env.ctx.devices.get(PHONE) == before


def test_a_device_revoked_between_the_check_and_the_handler_is_refused(env):
    record, token = add_device(env)
    principal = principal_for(env, token)                      # der Prüfer war schon durch
    env.ctx.devices.save(mobile_pairing.revoke(record))

    response = call(env, "POST", "/v1/sync", body=sync_body(env, {"2026-10-07": day()}),
                    principal=principal)

    assert response.status == 401 and error_code(response) == "token_revoked"
    assert env.ctx.storage.get_all_raw() == {}


def test_a_sync_is_refused_while_the_app_closes(env):
    _record, token = add_device(env)
    closing = mobile_routes.MobileContext(**{**env.ctx.__dict__, "closing": lambda: True})

    response = mobile_routes.dispatch(
        ApiRequest("POST", "/v1/sync", {}, sync_body(env)), closing, principal_for(env, token))

    assert response.status == 503 and error_code(response) == "shutting_down"
    assert env.ctx.storage.get_all_raw() == {}


def test_last_pull_at_is_saved_with_the_apply_so_a_repeated_first_sync_adds_no_conflict(env):
    # Vertrag aus #254. Erstabgleich: der Desktop kennt den Tag anders.
    env.ctx.storage.apply_merge({"2026-10-07": {
        "slots": [{"start": "09:00", "end": "13:00", "pause": 0, "kategorie": ""}],
        "modified_at": "2026-10-07T20:00:00Z", "device_id": "DESK", "deleted": False}})
    _record, token = add_device(env)
    entries = {"2026-10-07": day(modified_at="2026-10-07T18:30:00Z")}

    first = sync(env, token, entries)
    assert env.ctx.devices.get(PHONE)["last_pull_at"] == NOW
    again = sync(env, token, entries)                          # Antwort ging verloren, gleicher Request

    assert first.status == again.status == 200
    assert len(env.ctx.conflicts_store.get_all()) == 1


def test_a_failing_on_change_does_not_turn_a_saved_sync_into_a_500(env, caplog):
    _record, token = add_device(env)

    def boom():
        raise RuntimeError("UI weg")
    failing = mobile_routes.MobileContext(**{**env.ctx.__dict__, "on_change": boom})

    response = mobile_routes.dispatch(
        ApiRequest("POST", "/v1/sync", {}, sync_body(env, {"2026-10-07": day()})), failing,
        principal_for(env, token))

    assert response.status == 200 and "2026-10-07" in env.ctx.storage.get_all_raw()


def test_syncing_does_not_touch_other_devices(env):
    _a, token_a = add_device(env, "phone-aaaa", "A")
    b, _token_b = add_device(env, "phone-bbbb", "B")

    sync(env, token_a, {"2026-10-07": day()})

    assert env.ctx.devices.get("phone-bbbb") == b


def test_the_response_contains_the_new_token_but_neither_the_old_one_nor_any_hash(env):
    record, token = add_device(env)

    body = sync(env, token, {"2026-10-07": day()}).body
    text = json.dumps(body)

    assert body["token"] in text and token not in text
    assert record["token_hash"] not in text and mobile_pairing.hash_token(body["token"]) not in text


def test_two_concurrent_syncs_of_one_device_never_lose_a_renewal(env):
    _record, token = add_device(env)
    principal = principal_for(env, token)
    results = []

    def run():
        results.append(call(env, "POST", "/v1/sync", body=sync_body(env), principal=principal))

    threads = [threading.Thread(target=run) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    tokens = [r.body["token"] for r in results]
    hashes = {mobile_pairing.hash_token(t) for t in tokens}
    stored = env.ctx.devices.get(PHONE)
    assert all(r.status == 200 for r in results) and len(set(tokens)) == 8
    # Die Abgleiche laufen nacheinander durch den Lock: gespeichert ist das Token des
    # zuletzt fertigen, und das vorherige ist das des davor — nie ein veralteter Stand.
    assert stored["token_hash"] in hashes and stored["previous_token_hash"] in hashes
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_mobile_routes.py -q -p no:cacheprovider -x`
Expected: FAIL: `test_a_sync_applies_the_days_and_renews_the_token` (404: die Route fehlt).

- [ ] **Step 3: Implement**

In `src/mobile_routes.py` ergänze die Importe `from src import mobile_pairing, mobile_sync` (statt nur `mobile_pairing`) und füge **vor** `@dataclass(frozen=True)\nclass _Route:` ein:

```python
def _notify(ctx: MobileContext) -> None:
    try:
        ctx.on_change()
    except Exception:
        # Der Abgleich ist angewendet und gespeichert; ein Fehler beim Neuzeichnen
        # darf daraus keine 500 machen (das Handy wiederholte den Abgleich).
        _log.exception("Handy-Abgleich: on_change fehlgeschlagen")


def _sync(request: ApiRequest, ctx: MobileContext, principal: Principal) -> ApiResponse:
    """Der Abgleich. Unter `devices_lock`: den Datensatz neu lesen (ein Widerruf kann
    zwischen Prüfer und Handler liegen), `perform_sync`, danach Token erneuern und
    `last_pull_at` speichern. Erneuert wird nur nach einem erfolgreichen Abgleich;
    scheitert er, bleiben Token und `last_pull_at` unverändert."""
    _no_query(request)
    if not isinstance(principal, MobilePrincipal):
        raise _MobileError(403, "insufficient_scope", "Dem Token fehlt die Berechtigung.")
    _refuse_while_closing(ctx)
    now = ctx.now()
    parsed = mobile_sync.parse_request(request.body, now=now)
    with ctx.devices_lock:
        record = ctx.devices.get(principal.name)
        if record is None or record.get("revoked"):
            raise _MobileError(401, "token_revoked",
                               "Das Token wurde widerrufen. Das Gerät muss neu gekoppelt werden.")
        response = mobile_sync.perform_sync(
            parsed, device_id=record["id"], device_name=record["name"],
            last_pull_at=record["last_pull_at"], categories=category_names(ctx.settings),
            storage=ctx.storage, settings=ctx.settings, conflicts_store=ctx.conflicts_store,
            base=ctx.base, now=now, today=ctx.today(), data_lock=ctx.data_lock,
            sync_guard=ctx.sync_guard)
        renewed, token = mobile_pairing.renew(record, now, keep_previous=principal.via_previous)
        renewed["last_pull_at"] = response["last_pull_at"]
        ctx.devices.save(renewed)
    response["token"] = token
    response["expires_at"] = renewed["expires_at"]
    _notify(ctx)
    return ApiResponse(200, response)


```

und ergänze in `ROUTES` als letzte Zeile

```python
    _Route("POST", "/v1/sync", _sync),
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_mobile_routes.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/mobile_routes.py`
Expected: PASS, `All checks passed!`, `0 errors`. Füge außerdem den Test für die vollständige Tabelle hinzu:

```python
def test_the_route_table_has_exactly_the_four_routes(env):
    assert mobile_routes.methods_for_path("/v1/pair") == frozenset({"POST"})
    assert mobile_routes.methods_for_path("/v1/ping") == frozenset({"GET"})
    assert mobile_routes.methods_for_path("/v1/categories") == frozenset({"GET"})
    assert mobile_routes.methods_for_path("/v1/sync") == frozenset({"POST"})
    assert mobile_routes.methods_for_path("/v1/entries") == frozenset()
    assert mobile_routes.routed_methods() == frozenset({"GET", "POST"})
    assert mobile_routes.surface(env.ctx).public == frozenset({("POST", "/v1/pair")})
```

- [ ] **Step 5: Commit**

~~~bash
git add src/mobile_routes.py tests/test_mobile_routes.py
git commit -m "feat(mobile): Abgleich mit Tokenerneuerung und last_pull_at (POST /v1/sync) (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 5: `MobileService` — Lebenszyklus, Statusgründe, Geräte, Koppel-Link

**Files:**
- Create: `src/mobile_service.py`
- Create: `tests/test_mobile_service.py`

**Interfaces:** Consumes: `mobile_routes` (Task 2 bis 4), `netinfo.lan_candidates/pick_address` (PR 4a), `api_server.ApiServer`, `api_auth.Policy`, `api_service.parse_port`. Produces: `DEFAULT_PORT = 17654`; Zustände `STATE_OFF/STARTING/RUNNING/ERROR`; Gründe `REASON_INVALID_PORT/NO_ADDRESS/ADDRESS_GONE/PORT_IN_USE/START_FAILED/CLOSED`; `MobileStatus(state, address=None, port=None, reason="")`; `MobileService(settings, context, *, run, on_status=None, lan_candidates=netinfo.lan_candidates)` mit `status`, `pairing`, `apply()`, `shutdown(lock_timeout=1.0)`, `reopen()`, `list_devices()`, `revoke(device_id) -> bool`, `revoke_all() -> int`, `pair_link(code) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mobile_service.py`:

```python
# tests/test_mobile_service.py
import http.client
import json
import socket
import threading

import pytest

from src import mobile_pairing, mobile_routes
from src.api_auth import ANONYMOUS
from src.api_routes import ApiRequest
from src.conflicts_store import ConflictsStore
from src.mobile_pairing import PairingSession
from src.mobile_service import (
    DEFAULT_PORT, REASON_ADDRESS_GONE, REASON_INVALID_PORT, REASON_NO_ADDRESS,
    REASON_PORT_IN_USE, STATE_ERROR, STATE_OFF, STATE_RUNNING, STATE_STARTING, MobileService,
    MobileStatus,
)
from src.mobile_store import MobileStore
from src.settings import DEFAULTS, Settings
from src.storage import Storage
from src.time_utils import utc_now_iso

ORIGIN = "https://xveyn.github.io"
LOOPBACK = "127.0.0.1"


def free_port():
    with socket.socket() as sock:
        sock.bind((LOOPBACK, 0))
        return sock.getsockname()[1]


def sync_run(fn, on_done=None):
    result = fn()
    if on_done is not None:
        on_done(result)


def make_service(tmp_path, *, enabled=True, port=None, address="", candidates=(LOOPBACK,),
                 run=sync_run, statuses=None):
    settings = Settings(str(tmp_path / "settings.json"))
    settings.device_id_for_sync = "DESK"
    settings.set_many({"mobile_enabled": enabled, "mobile_port": port or free_port(),
                       "mobile_address": address})
    ctx = mobile_routes.MobileContext(
        pairing=PairingSession(),
        devices=MobileStore(str(tmp_path / "mobile_devices.json")),
        devices_lock=threading.RLock(),
        storage=Storage(str(tmp_path / "zeiterfassung.json"), device_id="DESK"),
        settings=settings,
        conflicts_store=ConflictsStore(str(tmp_path / "conflicts.json")),
        base=str(tmp_path), desktop_name=lambda: "Desktop")
    on_status = statuses.append if statuses is not None else None
    service = MobileService(settings, ctx, run=run, on_status=on_status,
                            lan_candidates=lambda: list(candidates))
    return service, settings, ctx


def http_call(port, method, path, *, token=None, body=None, origin=ORIGIN, host=None):
    conn = http.client.HTTPConnection(LOOPBACK, port, timeout=5)
    try:
        headers = {}
        if origin:
            headers["Origin"] = origin
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if host:
            headers["Host"] = host
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.putrequest(method, path, skip_host=host is not None, skip_accept_encoding=True)
        for name, value in headers.items():
            conn.putheader(name, value)
        if payload is not None:
            conn.putheader("Content-Length", str(len(payload)))
        conn.endheaders(payload)
        response = conn.getresponse()
        raw = response.read()
        return response, (json.loads(raw) if raw else None)
    finally:
        conn.close()


def port_is_closed(port):
    try:
        socket.create_connection((LOOPBACK, port), timeout=1).close()
    except OSError:
        return True
    return False


@pytest.fixture
def started(tmp_path):
    service, settings, ctx = make_service(tmp_path)
    service.apply()
    yield service, settings, ctx
    service.shutdown()


# --- Defaults -----------------------------------------------------------------------------------------

def test_the_default_port_matches_the_settings_default():
    assert DEFAULT_PORT == DEFAULTS["mobile_port"] == 17654


# --- Zustände -------------------------------------------------------------------------------------------

def test_a_disabled_service_runs_nothing(tmp_path):
    service, _settings, _ctx = make_service(tmp_path, enabled=False)
    service.apply()
    assert service.status == MobileStatus(STATE_OFF)


def test_an_enabled_service_binds_the_chosen_address_and_answers(started):
    service, _settings, ctx = started

    assert service.status.state == STATE_RUNNING and service.status.address == LOOPBACK
    port = service.status.port
    record, token = mobile_pairing.issue_device("phone-0001", "Pixel", utc_now_iso())
    ctx.devices.save(record)
    response, body = http_call(port, "GET", "/v1/ping", token=token)

    assert response.status == 200 and body["protocol"] == 1
    assert response.getheader("Access-Control-Allow-Origin") == ORIGIN


def test_the_server_only_accepts_the_exact_host_and_origin(started):
    service, _settings, _ctx = started
    port = service.status.port

    wrong_host, _b = http_call(port, "GET", "/v1/ping", host="evil.example:80")
    wrong_origin, _b2 = http_call(port, "GET", "/v1/ping", origin="https://evil.example")
    no_token, body = http_call(port, "GET", "/v1/ping")

    assert wrong_host.status == 403 and wrong_origin.status == 403
    assert no_token.status == 401 and body["error"]["code"] == "unauthorized"


def test_the_local_api_surface_is_not_reachable_through_the_phone_server(started):
    service, _settings, ctx = started
    record, token = mobile_pairing.issue_device("phone-0001", "Pixel", utc_now_iso())
    ctx.devices.save(record)

    for path in ("/v1/status", "/v1/entries", "/v1/entries/2026-10-07"):
        response, _body = http_call(service.status.port, "GET", path, token=token)
        assert response.status == 404


def test_pairing_and_syncing_work_end_to_end_over_a_real_socket(started):
    service, _settings, ctx = started
    port = service.status.port
    code = service.pairing.open()

    paired, body = http_call(port, "POST", "/v1/pair", body={
        "code": code, "device_name": "Pixel", "device_id": "phone-0001"})
    token = body["token"]
    entries = {"2026-10-07": {"slots": [{"start": "08:00", "end": "12:00", "pause": 0,
                                         "kategorie": "Projekt"}],
                              "modified_at": "2026-10-07T18:30:00Z", "deleted": False}}
    synced, answer = http_call(port, "POST", "/v1/sync", token=token, body={
        "protocol": 1, "client_time": utc_now_iso(), "entries": entries})
    renewed = answer["token"]
    still_old, _b = http_call(port, "GET", "/v1/ping", token=token)       # Karenz
    new_ok, _b2 = http_call(port, "GET", "/v1/ping", token=renewed)

    assert paired.status == 200 and synced.status == 200
    assert ctx.storage.get_all_raw()["2026-10-07"]["device_id"] == "phone-0001"
    assert still_old.status == 200 and new_ok.status == 200
    assert paired.getheader("Access-Control-Allow-Origin") == ORIGIN


def test_a_refused_pairing_has_no_token_in_the_answer(started):
    service, _settings, _ctx = started
    service.pairing.open()

    response, body = http_call(service.status.port, "POST", "/v1/pair", body={
        "code": "AAAA-AAAA", "device_name": "P", "device_id": "phone-0001"})

    assert response.status == 403 and "token" not in json.dumps(body)


def test_switching_off_stops_the_server_and_closes_the_pairing_session(tmp_path):
    service, settings, _ctx = make_service(tmp_path)
    service.apply()
    port = service.status.port
    service.pairing.open()

    settings.set("mobile_enabled", False)
    service.apply()

    assert service.status == MobileStatus(STATE_OFF)
    assert port_is_closed(port) and not service.pairing.is_active()


def test_changing_the_port_restarts_on_the_new_one(tmp_path):
    service, settings, _ctx = make_service(tmp_path)
    service.apply()
    first = service.status.port
    second = free_port()

    settings.set("mobile_port", second)
    service.apply()

    assert service.status.state == STATE_RUNNING and service.status.port == second
    assert port_is_closed(first)
    service.shutdown()


def test_applying_again_without_a_change_keeps_the_server_and_the_code(started):
    service, _settings, _ctx = started
    service.pairing.open()

    service.apply()

    assert service.status.state == STATE_RUNNING and service.pairing.is_active()


@pytest.mark.parametrize("bad", [0, 80, 70000, "abc", None, True, 17654.5])
def test_an_invalid_port_is_an_error(tmp_path, bad):
    service, settings, _ctx = make_service(tmp_path)
    settings.set("mobile_port", bad)

    service.apply()

    assert service.status == MobileStatus(STATE_ERROR, None, None, REASON_INVALID_PORT)


def test_no_lan_address_is_an_error_and_starts_nothing(tmp_path):
    service, _settings, _ctx = make_service(tmp_path, candidates=())

    service.apply()

    assert service.status.state == STATE_ERROR and service.status.reason == REASON_NO_ADDRESS


def test_a_vanished_address_is_an_error_and_never_replaced_silently(tmp_path):
    service, _settings, _ctx = make_service(tmp_path, address="192.168.77.5",
                                            candidates=(LOOPBACK, "10.0.0.5"))

    service.apply()

    assert service.status.state == STATE_ERROR and service.status.reason == REASON_ADDRESS_GONE
    assert service.status.address == "192.168.77.5"


def test_a_running_server_stops_when_its_address_vanishes(tmp_path):
    candidates = [LOOPBACK]
    service, _settings, _ctx = make_service(tmp_path, address=LOOPBACK, candidates=candidates)
    service.apply()
    port = service.status.port
    assert service.status.state == STATE_RUNNING

    candidates[:] = ["10.0.0.5"]                  # die Adresse ist weg (anderes WLAN)
    service.apply()

    assert service.status.reason == REASON_ADDRESS_GONE and port_is_closed(port)


def test_a_busy_port_is_reported(tmp_path):
    port = free_port()
    with socket.socket() as blocker:
        blocker.bind((LOOPBACK, port))
        blocker.listen(1)
        service, _settings, _ctx = make_service(tmp_path, port=port)

        service.apply()

    assert service.status.state == STATE_ERROR and service.status.reason == REASON_PORT_IN_USE


def test_apply_shows_starting_before_the_worker_ran(tmp_path):
    queued = []
    service, _settings, _ctx = make_service(tmp_path, run=lambda fn, done=None: queued.append((fn, done)))

    service.apply()

    assert service.status.state == STATE_STARTING and len(queued) == 1


def test_the_status_callback_gets_the_current_status(tmp_path):
    statuses = []
    service, _settings, _ctx = make_service(tmp_path, statuses=statuses)

    service.apply()

    assert statuses and statuses[-1].state == STATE_RUNNING
    service.shutdown()


def test_shutdown_stops_the_server_and_blocks_new_starts_until_reopened(tmp_path):
    service, _settings, _ctx = make_service(tmp_path)
    service.apply()
    port = service.status.port

    service.shutdown()
    service.apply()

    assert port_is_closed(port) and service.status.state == STATE_OFF
    service.reopen()
    service.apply()
    assert service.status.state == STATE_RUNNING
    service.shutdown()


def test_routes_refuse_work_after_shutdown(tmp_path):
    service, _settings, ctx = make_service(tmp_path)
    service.apply()
    code = service.pairing.open()
    service.shutdown()
    request = ApiRequest("POST", "/v1/pair", {}, json.dumps(
        {"code": code, "device_id": "phone-0001"}).encode())

    response = mobile_routes.dispatch(request, service._context, ANONYMOUS)

    assert response.status == 503 and response.body["error"]["code"] == "shutting_down"


# --- Geräte und Koppel-Link ------------------------------------------------------------------------------

def test_devices_can_be_listed_and_revoked(started):
    service, _settings, ctx = started
    a, token_a = mobile_pairing.issue_device("phone-aaaa", "Zeta", utc_now_iso())
    b, token_b = mobile_pairing.issue_device("phone-bbbb", "Alpha", utc_now_iso())
    ctx.devices.save(a)
    ctx.devices.save(b)

    assert [d["name"] for d in service.list_devices()] == ["Alpha", "Zeta"]
    assert service.revoke("phone-aaaa") is True and service.revoke("unbekannt") is False
    port = service.status.port
    revoked, body = http_call(port, "GET", "/v1/ping", token=token_a)
    other, _b = http_call(port, "GET", "/v1/ping", token=token_b)

    assert revoked.status == 401 and body["error"]["code"] == "token_revoked"
    assert other.status == 200


def test_revoke_all_revokes_every_device_and_counts_them(started):
    service, _settings, ctx = started
    tokens = []
    for index in range(3):
        record, token = mobile_pairing.issue_device(f"phone-000{index}", f"P{index}", utc_now_iso())
        ctx.devices.save(record)
        tokens.append(token)

    assert service.revoke_all() == 3
    for token in tokens:
        response, body = http_call(service.status.port, "GET", "/v1/ping", token=token)
        assert response.status == 401 and body["error"]["code"] == "token_revoked"
    assert service.revoke_all() == 3                          # idempotent, zählt die vorhandenen


def test_the_pair_link_carries_address_port_and_the_canonical_code(started):
    service, _settings, _ctx = started
    port = service.status.port

    assert service.pair_link("K7M2-9QXA") == (
        f"https://xveyn.github.io/Zeiterfassung/#pair=127.0.0.1:{port}:K7M29QXA")
    assert service.pair_link("k7m2 9qxa") == service.pair_link("K7M2-9QXA")
    assert service.pair_link("kein code") is None


def test_there_is_no_pair_link_while_the_server_is_not_running(tmp_path):
    service, _settings, _ctx = make_service(tmp_path, enabled=False)
    service.apply()
    assert service.pair_link("K7M2-9QXA") is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_mobile_service.py -q -p no:cacheprovider -x`
Expected: ERROR beim Sammeln: `ImportError: cannot import name 'mobile_service' from 'src'`.

- [ ] **Step 3: Implement**

Create `src/mobile_service.py`:

```python
# src/mobile_service.py
"""Lebenszyklus der Handy-Instanz (#221), Tk-frei.

`MobileService.apply()` liest `mobile_enabled`/`mobile_port`/`mobile_address` aus den
Settings und bringt den Server in den passenden Zustand — im Worker, nie im
UI-Thread (`netinfo` löst einen Hostnamen auf und kann blockieren). Das Ergebnis ist
ein `MobileStatus` samt Grund, den der Tab „Mobil" (PR 5) anzeigt.

Gebunden wird nur auf die gewählte LAN-Adresse (`netinfo.pick_address`), nie auf
`0.0.0.0`. Fehlt die gewählte Adresse (DHCP, anderes WLAN), ist der Zustand `error`
mit dem Grund `address_gone` und es läuft nichts: die Adresse wird nie still durch
eine andere ersetzt. Bei jedem Statuswechsel weg von „läuft" wird die offene
Kopplungssitzung geschlossen — ein Code ohne Server ist nutzlos.

Die Geräteverwaltung (`list_devices`, `revoke`, `revoke_all`) und `pair_link` liegen
hier, weil sie sich den `devices_lock` mit den Routen teilen müssen. Sie schreiben
(Datei): im Worker aufrufen.
"""
from __future__ import annotations

import dataclasses
import errno
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src import mobile_pairing, mobile_routes, netinfo
from src.api_auth import Policy
from src.api_server import ApiServer
from src.api_service import parse_port

if TYPE_CHECKING:
    from src.mobile_store import Record

_log = logging.getLogger(__name__)

DEFAULT_PORT = 17654

STATE_OFF = "off"
STATE_RUNNING = "running"
STATE_STARTING = "starting"
STATE_ERROR = "error"

REASON_INVALID_PORT = "invalid_port"
REASON_NO_ADDRESS = "no_address"
REASON_ADDRESS_GONE = "address_gone"
REASON_PORT_IN_USE = "port_in_use"
REASON_START_FAILED = "start_failed"
REASON_CLOSED = "closed"

# Windows meldet einen belegten Port mit WSAEADDRINUSE (10048), einen mit
# SO_EXCLUSIVEADDRUSE fremd gebundenen mit WSAEACCES (10013).
_WINERRORS_IN_USE = (10048, 10013)


@dataclass(frozen=True)
class MobileStatus:
    state: str
    address: str | None = None
    port: int | None = None
    reason: str = ""


def _port_in_use(exc: OSError) -> bool:
    return (exc.errno in (errno.EADDRINUSE, errno.EACCES)
            or getattr(exc, "winerror", None) in _WINERRORS_IN_USE)


class MobileService:
    def __init__(self, settings: Any, context: mobile_routes.MobileContext, *,
                 run: Callable[..., None],
                 on_status: Callable[[MobileStatus], None] | None = None,
                 lan_candidates: Callable[[], list[str]] = netinfo.lan_candidates) -> None:
        self._settings = settings
        # Die Routen fragen `closing` unter dem Lock: nach `shutdown()` (Beenden,
        # Entfernen, Neustart) koppelt und gleicht keine Route mehr ab.
        self._context = dataclasses.replace(context, closing=lambda: self._closed)
        self._run = run
        self._on_status = on_status
        self._lan_candidates = lan_candidates
        self._lock = threading.Lock()
        self._server: ApiServer | None = None
        self._running: tuple[str, int] | None = None
        self._status = MobileStatus(STATE_OFF)
        self._closed = False

    @property
    def status(self) -> MobileStatus:
        return self._status

    @property
    def pairing(self) -> mobile_pairing.PairingSession:
        return self._context.pairing

    def apply(self) -> None:
        """Bringt den Server in den Zustand der Settings. Im UI-Thread aufrufen; die
        Arbeit läuft im Worker, `on_status` kommt zurück. Sofort sichtbar wird
        „startet": die Adressauflösung kann dauern."""
        if self._closed:
            return
        port = parse_port(self._settings.get("mobile_port"))
        if (self._settings.get("mobile_enabled") and port is not None
                and (self._running is None or self._running[1] != port)):
            self._status = MobileStatus(STATE_STARTING, None, port)
        self._run(self._reconcile, self._publish)

    def _publish(self, _result: MobileStatus) -> None:
        # Der aktuelle Stand, nicht das Ergebnis dieses Workers: kommen zwei Worker
        # vertauscht zurück, würde die UI sonst einen veralteten Status zeigen.
        if self._on_status is not None:
            self._on_status(self._status)

    def _reconcile(self) -> MobileStatus:
        with self._lock:
            try:
                return self._reconcile_locked()
            except Exception:
                # Der Runner würde den Fehler nur loggen und `on_done` nie rufen — der
                # Status bliebe stehen. Hier wird er zum Zustand.
                _log.exception("Handy-Instanz: Start/Stopp fehlgeschlagen")
                self._stop_server()
                self._status = MobileStatus(STATE_ERROR, None, None, REASON_START_FAILED)
                return self._status

    def _reconcile_locked(self) -> MobileStatus:
        if self._closed:
            return self._status
        if not self._settings.get("mobile_enabled"):
            self._stop_server()
            self._status = MobileStatus(STATE_OFF)
            return self._status
        port = parse_port(self._settings.get("mobile_port"))
        if port is None:
            self._stop_server()
            self._status = MobileStatus(STATE_ERROR, None, None, REASON_INVALID_PORT)
            return self._status
        configured = self._settings.get("mobile_address")
        configured = configured if isinstance(configured, str) else ""
        address = netinfo.pick_address(configured, self._lan_candidates())
        if address is None:
            self._stop_server()
            reason = REASON_ADDRESS_GONE if configured else REASON_NO_ADDRESS
            self._status = MobileStatus(STATE_ERROR, configured or None, port, reason)
            return self._status
        if self._running == (address, port) and self._server is not None:
            # Läuft schon. RUNNING setzen statt `_status` durchzureichen: `apply` kann
            # dazwischen „startet" geschrieben haben.
            self._status = MobileStatus(STATE_RUNNING, address, port)
            return self._status
        self._stop_server()
        if self._closed:                          # Beenden/Entfernen kam dazwischen
            return self._status
        context = self._context

        def policy_for_port(bound: int) -> Policy:
            return Policy(allowed_hosts=frozenset({f"{address}:{bound}"}),
                          allowed_origins=frozenset({mobile_routes.PWA_ORIGIN}),
                          bind_host=address)

        server = ApiServer(None, mobile_routes.make_verifier(context.devices, context.now),
                           port=port, policy_for_port=policy_for_port,
                           surface=mobile_routes.surface(context))
        try:
            server.start()
        except OSError as exc:
            reason = REASON_PORT_IN_USE if _port_in_use(exc) else REASON_START_FAILED
            _log.warning("Handy-Instanz: Start auf %s:%s scheitert (%s)", address, port,
                         reason, exc_info=True)
            self._status = MobileStatus(STATE_ERROR, address, port, reason)
            return self._status
        self._server = server
        self._running = (address, server.port)
        self._status = MobileStatus(STATE_RUNNING, address, server.port)
        return self._status

    def _stop_server(self) -> None:
        server, self._server = self._server, None
        self._running = None
        if server is not None:
            server.stop()
        # Ein Code ohne Server ist nutzlos, und beim Neustart auf anderer Adresse oder
        # anderem Port stimmte der QR-Code nicht mehr.
        self._context.pairing.close()

    def shutdown(self, lock_timeout: float = 1.0) -> None:
        """Stoppt den Server und sperrt weitere Starts. Blockiert höchstens
        `lock_timeout`: läuft gerade ein Start (der Worker hält den Lock), wird nicht
        gewartet — der Start prüft `_closed` und bricht selbst ab."""
        self._closed = True
        if not self._lock.acquire(timeout=lock_timeout):
            _log.warning("Handy-Instanz: Beenden wartet nicht auf einen laufenden Start")
            return
        try:
            self._stop_server()
            self._status = MobileStatus(STATE_OFF)
        finally:
            self._lock.release()

    def reopen(self) -> None:
        """Macht `shutdown` rückgängig (Skalierungs-Neustart ist gescheitert, die App
        läuft weiter). Der nächste `apply()` startet wieder."""
        self._closed = False

    # --- Geräte ---------------------------------------------------------------------------------

    def list_devices(self) -> list[Record]:
        """Die gekoppelten Geräte nach Name (Datei lesen: im Worker)."""
        return sorted(self._context.devices.get_all(),
                      key=lambda record: (record["name"].lower(), record["id"]))

    def revoke(self, device_id: str) -> bool:
        """Widerruft ein Gerät (der Datensatz bleibt, die Antwort wird `token_revoked`).
        `False`, wenn es das Gerät nicht gibt."""
        with self._context.devices_lock:
            record = self._context.devices.get(device_id)
            if record is None:
                return False
            self._context.devices.save(mobile_pairing.revoke(record))
            return True

    def revoke_all(self) -> int:
        """Widerruft alle Geräte in **einem** Schreibvorgang; liefert die Zahl der
        vorhandenen Geräte (auch bereits widerrufene)."""
        with self._context.devices_lock:
            records = self._context.devices.get_all()
            self._context.devices.replace_all([mobile_pairing.revoke(r) for r in records])
            return len(records)

    def pair_link(self, code: str) -> str | None:
        """Der Link im QR-Code: `<PWA>#pair=<ip>:<port>:<code>`. Das Fragment geht nie
        an einen Server und trägt nur Adresse und Einmalcode, kein Token. `None`,
        solange der Server nicht läuft oder der Code keine Form eines Codes hat."""
        status = self._status
        canonical = mobile_pairing.normalize_code(code)
        if status.state != STATE_RUNNING or status.address is None or canonical is None:
            return None
        return f"{mobile_routes.PWA_URL}#pair={status.address}:{status.port}:{canonical}"
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_mobile_service.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/mobile_service.py`
Expected: PASS, `All checks passed!`, `0 errors`.

Hinweis: `Settings.set` nimmt die ungültigen Ports aus `test_an_invalid_port_is_an_error` (`None`, `True`, `17654.5`) womöglich nicht roh an; dann schreibe den Wert direkt in `settings._data` oder nutze ein schlichtes `dict` als `settings` für den Dienst (er braucht davon nur `get`).

- [ ] **Step 5: Commit**

~~~bash
git add src/mobile_service.py tests/test_mobile_service.py
git commit -m "feat(mobile): MobileService mit Lebenszyklus, Statusgründen und Geräteverwaltung (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 6: Annotationen, Doku, Spec

**Files:**
- Modify: `tests/test_type_annotations.py`
- Modify: `CLAUDE.md`, `src/CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md`

- [ ] **Step 1: Whitelist**

In `tests/test_type_annotations.py` ersetze

```python
    "src/api_summary.py",
```

durch

```python
    "src/api_summary.py",
    "src/mobile_routes.py",
    "src/mobile_service.py",
```

Run: `python3 -m pytest tests/test_type_annotations.py -q -p no:cacheprovider`
Expected: PASS; fehlen Annotationen (z. B. an den inneren Funktionen `verify`, `policy_for_port`), ergänze sie.

- [ ] **Step 2: Docs**

In `CLAUDE.md` ersetze

```markdown
- `src/netinfo.py` — LAN-Adressen
```

durch (zwei neue Zeilen davor, die vorhandene bleibt)

```markdown
- `src/mobile_routes.py` — die vier Routen der Handy-Instanz (#221, `POST /v1/pair` öffentlich, `GET /v1/ping`, `GET /v1/categories`, `POST /v1/sync`), der Prüfer über die gekoppelten Geräte (`make_verifier` → `MobilePrincipal`/`Denied`) und `surface(ctx)` für den `ApiServer`. Tk-frei; Koppeln und Abgleich samt Tokenerneuerung laufen unter `devices_lock` (s. `src/CLAUDE.md`)
- `src/mobile_service.py` — Lebenszyklus der Handy-Instanz (Muster `ApiService`): bindet nur die gewählte LAN-Adresse, Statusgründe (`address_gone`, `no_address`, `port_in_use` …), Geräteverwaltung und Koppel-Link. Noch nicht in `ui.py` verdrahtet (PR 5)
- `src/netinfo.py` — LAN-Adressen
```

In `src/CLAUDE.md` ersetze

```markdown
- `api_service.py` — Lebenszyklus der lokalen API:
```

durch

```markdown
- `mobile_routes.py` / `mobile_service.py` — die Handy-Instanz (#221) auf demselben `ApiServer`. `mobile_routes`: exakte Pfade, keine Query-Parameter. `POST /v1/pair` ist die einzige öffentliche Route und prüft Form und `device_id` **vor** dem Code (ungültiges `device_id` = `400`, ohne den Code anzusehen: kein Orakel, kein Fehlversuch, kein verbrannter Code); falscher, abgelaufener, verbrauchter Code und „kein Code aktiv" sind dieselbe `403 invalid_code`, nach 5 Fehlversuchen `429 pairing_locked`. `POST /v1/sync` liest den Datensatz unter `devices_lock` neu (ein Widerruf kann zwischen Prüfer und Handler liegen), ruft `mobile_sync.perform_sync` und erneuert **erst danach** das Token (`renew(…, keep_previous=principal.via_previous)`) und speichert `last_pull_at` im selben Abschnitt (Vertrag #254: ein wiederholter Erstabgleich erzeugt keinen zweiten Konflikt); bei jeder Ablehnung bleiben Token und `last_pull_at` unverändert. Sperrreihenfolge `devices_lock` → `sync_guard` → `data_lock`. `mobile_service`: wie `ApiService` (`apply()` im Worker, `shutdown()`/`reopen()`), aber ohne Token-Datei; bindet `pick_address(mobile_address, lan_candidates())`, nie `0.0.0.0`, `allowed_hosts` genau `<ip>:<port>`, `allowed_origins` genau `PWA_ORIGIN`. Eine verschwundene Adresse ist `error`/`address_gone` und startet **nichts** (kein stiller Wechsel); jeder Statuswechsel weg von „läuft" schließt die Kopplungssitzung. Geräteverwaltung (`list_devices`, `revoke`, `revoke_all`) und `pair_link` liegen im Dienst, weil sie den `devices_lock` teilen; sie schreiben, also im Worker. Settings `mobile_enabled`/`mobile_port`/`mobile_address` sind gerätelokal.
- `api_service.py` — Lebenszyklus der lokalen API:
```

(Anker: der Text hinter „Lebenszyklus der lokalen API:" bleibt unverändert.)

In `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md` ergänze am Ende des Absatzes „**Umsetzung (PR 4a):**" einen Absatz:

```markdown

**Umsetzung (PR 4b):** Körperfehler an `/v1/pair` und `/v1/sync` (auch ein ungültiges `device_id`) sind `400 invalid_json`; `protocol` ist im Pair-Request optional, aber wenn vorhanden `1`. Die Tokenerneuerung und `last_pull_at` werden erst nach einem erfolgreichen Abgleich gespeichert. Ein Fehler beim Speichern des Geräts nach erfolgreichem Einlösen ist eine `500` (der Code ist verbraucht).
```

- [ ] **Step 3: Run to verify**

Run: `python3 -m pytest tests/test_claude_md_claims.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/mobile_routes.py src/mobile_service.py`
Expected: PASS, `All checks passed!`, `0 errors`.

- [ ] **Step 4: Commit**

~~~bash
git add tests/test_type_annotations.py CLAUDE.md src/CLAUDE.md docs/superpowers/specs/2026-10-08-mobile-pwa-design.md
git commit -m "docs(mobile): Routen und Dienst in CLAUDE.md, Whitelist und Spec (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

## Mutationsprüfung (nach Task 6, vor dem Review)

Jeden Mutanten einzeln anwenden (`PYTHONDONTWRITEBYTECODE=1`, Datei sichern, genau eine Ersetzung, die Tests der beiden Dateien laufen lassen, zurückkopieren; **nicht parallel zu anderen Arbeiten am Arbeitsbaum**). Jeder muss mindestens einen Test rot färben:

| Datei | Mutation | Erwartet rot |
|---|---|---|
| `mobile_routes.py` | `Denied("token_expired")` ↔ `Denied("token_revoked")` vertauschen | `test_an_expired_token_is_denied_as_expired` |
| `mobile_routes.py` | `outcome.via_previous` im Prinzipal auf `False` | `test_the_previous_token_is_flagged_as_such` |
| `mobile_routes.py` | `require_scope` entfernen | `test_a_principal_without_the_mobile_scope_is_refused` |
| `mobile_routes.py` | `public=True` auch für `sync` | `test_the_surface_publishes_only_pair_and_enables_cors` |
| `mobile_routes.py` | `_no_query` in `_ping` entfernen | `test_query_parameters_are_rejected` |
| `mobile_routes.py` | `device_id`-Prüfung hinter `redeem` | `test_an_invalid_device_id_is_400_without_looking_at_the_code` |
| `mobile_routes.py` | `LOCKED` wie `INVALID` behandeln | `test_five_wrong_codes_lock_the_session_even_for_the_right_one` |
| `mobile_routes.py` | `protocol`-Prüfung im Pair entfernen | `test_a_present_but_wrong_protocol_is_400_invalid_protocol` |
| `mobile_routes.py` | `ctx.devices.get(device_id)` (Wiederkoppeln) durch `None` ersetzen | `test_pairing_again_keeps_the_sync_identity_and_lifts_a_revocation` |
| `mobile_routes.py` | `_refuse_while_closing` in `_pair` entfernen | `test_pairing_is_refused_while_the_app_closes_and_keeps_the_code` |
| `mobile_routes.py` | Datensatz nicht neu lesen (`principal.record` verwenden) | `test_a_device_revoked_between_the_check_and_the_handler_is_refused` |
| `mobile_routes.py` | `keep_previous=principal.via_previous` → `False` | `test_a_lost_answer_twice_does_not_lock_the_phone_out` |
| `mobile_routes.py` | `renewed["last_pull_at"]` nicht setzen | `test_a_sync_applies_the_days_and_renews_the_token` |
| `mobile_routes.py` | Token **vor** `perform_sync` erneuern/speichern | `test_a_rejected_sync_neither_renews_the_token_nor_moves_last_pull_at` |
| `mobile_routes.py` | `devices_lock` weglassen | `test_two_concurrent_syncs_of_one_device_never_lose_a_renewal` (ggf. nur flackernd: dann Test schärfen) |
| `mobile_routes.py` | `_notify` ohne `try` | `test_a_failing_on_change_does_not_turn_a_saved_sync_into_a_500` |
| `mobile_routes.py` | `response["token"]` mit dem **alten** Token | `test_a_sync_applies_the_days_and_renews_the_token` |
| `mobile_service.py` | `pick_address` durch `candidates[0]` ersetzen | `test_a_vanished_address_is_an_error_and_never_replaced_silently` |
| `mobile_service.py` | `allowed_hosts` ohne Port | `test_the_server_only_accepts_the_exact_host_and_origin` |
| `mobile_service.py` | `allowed_origins` leer lassen | `test_pairing_and_syncing_work_end_to_end_over_a_real_socket` |
| `mobile_service.py` | `self._context.pairing.close()` im Stoppen entfernen | `test_switching_off_stops_the_server_and_closes_the_pairing_session` |
| `mobile_service.py` | `self._running == (address, port)`-Zweig entfernen | `test_applying_again_without_a_change_keeps_the_server_and_the_code` |
| `mobile_service.py` | `REASON_ADDRESS_GONE`/`REASON_NO_ADDRESS` vertauschen | `test_a_vanished_address_…`, `test_no_lan_address_…` |
| `mobile_service.py` | `closing=lambda: self._closed` entfernen | `test_routes_refuse_work_after_shutdown` |
| `mobile_service.py` | `pair_link` ohne `normalize_code` | `test_the_pair_link_carries_address_port_and_the_canonical_code` |
| `mobile_service.py` | `pair_link` auch bei nicht laufendem Server | `test_there_is_no_pair_link_while_the_server_is_not_running` |

Überlebt ein Mutant, ist das ein Testfehler: Test schärfen, gegen den Mutanten rot sehen, committen.

## Finale

Nach Task 6: Review über den ganzen Branch mit einem frischen Reviewer auf dem leistungsfähigsten Modell (Review Focus und Rulings mitgeben; aktiver Angriff über echte Sockets: Pair-Brute-Force, Token-Zustände, gleichzeitige Abgleiche, Lock-Reihenfolge), Critical/Important in **einem** Fix-Durchlauf (je Fix ein Test, der zuerst rot war), Minors ins Ledger und in ein Issue. Danach `finishing-a-development-branch`: PR gegen `master` (`Refs #221`, „PR 4b von 9" im Titel).

**Danach PR 5:** Tab „Mobil" mit QR (`segno`) und Verdrahtung in `ui.py`/`main.py` (`MobileService` bauen, `shutdown` in den Beenden-Pfaden, `closing`/`on_change` verbinden, Einschalten-Hinweis zur unverschlüsselten Verbindung).
