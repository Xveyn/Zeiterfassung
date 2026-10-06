# src/api_routes.py
"""Routing und Antworten der lokalen HTTP-API (#92), Tk-frei und ohne Socket.

`handle(request, ctx, principal)` bekommt eine bereits authentifizierte Anfrage
(`api_auth.authorize` läuft davor, im Server) und liefert eine `ApiResponse`.
Jede Route deklariert den Scope, den sie braucht (`api_auth.require_scope`);
Stufe 1 kennt nur `local`.

Lesend: `GET /v1/status`, `GET /v1/entries`, `GET /v1/entries/{date}`. Die Daten
kommen über `Storage.get_all()`/`get()`, die den geteilten `data_lock` selbst
nehmen und Kopien liefern — die Routen halten keinen Lock und ändern nichts.
Wire-Format der Slots: `{start, end, pause, kategorie}` (Share v3).

Ein Programmfehler in einem Handler wirft hier durch; den macht der Server zu
einer 500-Antwort ohne Details.
"""
from __future__ import annotations

import datetime
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from src.api_auth import SCOPE_LOCAL, Principal, require_scope
from src.time_utils import utc_now_iso

if TYPE_CHECKING:  # nur für die Signaturen
    from src.settings import SettingsLike

API_VERSION = 1

# Nur YYYY-MM-DD in ASCII-Ziffern: `date.fromisoformat` nimmt seit 3.11 auch
# "20260105" und "2026-W01-1", und `\d` matcht Ziffern anderer Schriften.
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_NAME_ECHO_MAX = 40


class EntryStore(Protocol):
    def get_all(self) -> dict[str, dict[str, Any]]: ...

    def get(self, date_str: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class ApiRequest:
    method: str
    path: str                                   # ohne Query, nicht prozentdekodiert
    query: Mapping[str, list[str]]
    body: bytes = b""


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: Any                                   # JSON-serialisierbar
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ApiContext:
    storage: EntryStore
    settings: SettingsLike
    app_version: Callable[[], str]
    now: Callable[[], str] = utc_now_iso


def error_response(status: int, code: str, message: str,
                   headers: Mapping[str, str] | None = None) -> ApiResponse:
    return ApiResponse(status, {"error": {"code": code, "message": message}},
                       dict(headers or {}))


class _ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def parse_date(raw: str) -> datetime.date | None:
    if not _DATE_RE.fullmatch(raw):
        return None
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        return None


def _only_params(query: Mapping[str, list[str]], allowed: frozenset[str]) -> None:
    for name, values in query.items():
        if name not in allowed:
            raise _ApiError(400, "unknown_parameter",
                            f"Unbekannter Parameter: {name[:_NAME_ECHO_MAX]}")
        if len(values) != 1:
            raise _ApiError(400, "duplicate_parameter",
                            f"Parameter {name} nur einmal angeben.")


def _query_date(query: Mapping[str, list[str]], name: str) -> datetime.date | None:
    values = query.get(name)
    if values is None:
        return None
    day = parse_date(values[0])
    if day is None:
        raise _ApiError(400, "invalid_date", f"Parameter {name}: erwartet YYYY-MM-DD.")
    return day


def _status(request: ApiRequest, ctx: ApiContext, _match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    return ApiResponse(200, {
        "api_version": API_VERSION,
        "app_version": ctx.app_version(),
        "device_name": ctx.settings.get("device_name") or "",
        "time": ctx.now(),
    })


def _entries(request: ApiRequest, ctx: ApiContext, _match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset({"from", "to"}))
    start = _query_date(request.query, "from")
    end = _query_date(request.query, "to")
    if start is not None and end is not None and start > end:
        raise _ApiError(400, "invalid_range", "from liegt nach to.")
    entries: dict[str, Any] = {}
    for day_key, entry in ctx.storage.get_all().items():
        day = parse_date(day_key)
        if day is None:                          # kaputter Schlüssel: nie ausliefern
            continue
        if (start is not None and day < start) or (end is not None and day > end):
            continue
        entries[day_key] = entry
    return ApiResponse(200, {"entries": dict(sorted(entries.items()))})


def _entry(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    day_key = match.group(1)
    if parse_date(day_key) is None:
        raise _ApiError(400, "invalid_date", "Erwartet YYYY-MM-DD.")
    entry = ctx.storage.get(day_key)
    if entry is None:
        raise _ApiError(404, "not_found", "Für diesen Tag gibt es keinen Eintrag.")
    return ApiResponse(200, {"date": day_key, "slots": entry["slots"]})


@dataclass(frozen=True)
class Route:
    method: str
    pattern: re.Pattern[str]
    handler: Callable[[ApiRequest, ApiContext, re.Match[str]], ApiResponse]
    scope: str


ROUTES: tuple[Route, ...] = (
    Route("GET", re.compile(r"/v1/status"), _status, SCOPE_LOCAL),
    Route("GET", re.compile(r"/v1/entries"), _entries, SCOPE_LOCAL),
    Route("GET", re.compile(r"/v1/entries/([^/]+)"), _entry, SCOPE_LOCAL),
)


def handle(request: ApiRequest, ctx: ApiContext, principal: Principal) -> ApiResponse:
    allowed: set[str] = set()
    chosen: tuple[Route, re.Match[str]] | None = None
    for route in ROUTES:
        match = route.pattern.fullmatch(request.path)
        if match is None:
            continue
        allowed.add(route.method)
        if route.method == request.method and chosen is None:
            chosen = (route, match)
    if chosen is None:
        if allowed:
            return error_response(405, "method_not_allowed", "Methode nicht erlaubt.",
                                  {"Allow": ", ".join(sorted(allowed))})
        return error_response(404, "not_found", "Unbekannter Pfad.")
    route, match = chosen
    denied = require_scope(principal, route.scope)
    if not denied.ok:
        return error_response(denied.status, denied.code, "Dem Token fehlt die Berechtigung.")
    try:
        return route.handler(request, ctx, match)
    except _ApiError as exc:
        return error_response(exc.status, exc.code, exc.message)
