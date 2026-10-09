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
