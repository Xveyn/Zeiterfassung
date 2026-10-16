# src/api_routes.py
"""Routing und Antworten der lokalen HTTP-API (#92), Tk-frei und ohne Socket.

`handle(request, ctx, principal)` bekommt eine bereits authentifizierte Anfrage
(`api_auth.authorize` läuft davor, im Server) und liefert eine `ApiResponse`.
Jede Route deklariert den Scope, den sie braucht (`api_auth.require_scope`);
Stufe 1 kennt nur `local`.

Lesend: `GET /v1/status`, `GET /v1/entries`, `GET /v1/entries/{date}` (über
`Storage.get_all()`/`get()`, die den geteilten `data_lock` selbst nehmen und
Kopien liefern, ohne eigenen Lock). Schreibend: `PUT`/`DELETE
/v1/entries/{date}`: Prüfen, Konfliktcheck und Speichern laufen unter
`ctx.data_lock`, die Regeln der UI stehen in `api_entry_write`; `ctx.on_change`
kommt danach, und nur bei einer Änderung.
Auswertungen: `GET /v1/summary/week/{YYYY-Www}`, `/v1/summary/month/{YYYY-MM}`,
`/v1/categories`, `/v1/holidays/{YYYY}` (Rechnung in `api_summary`).
Reservierungen (#239): `GET /v1/reservations[/{date}]`, `PUT`/`DELETE
/v1/reservations/{date}` (Regeln in `api_reservation_write`; Schreiben nur mit
eingeschalteten Reservierungen, danach der Kalender-Abgleich der UI).
Wire-Format der Ist-Zeit-Slots: `{start, end, pause, kategorie}` (Share v3), der
Reservierungs-Slots: `{start, end, kategorie, send_reminder_minutes}`.

Ein Programmfehler in einem Handler wirft hier durch; den macht der Server zu
einer 500-Antwort ohne Details.
"""
from __future__ import annotations

import contextlib
import datetime
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from src.api_auth import SCOPE_LOCAL, Principal, require_scope
from src.api_entry_write import (
    MAX_YEAR, MIN_YEAR, WriteError, check_date_range, check_day_writable, parse_day_body,
    warnings_for,
)
from src.api_reservation_write import check_reservation_day, parse_reservation_body
from src.api_summary import (
    category_names, holidays_for, parse_month, parse_week, parse_year, summarize,
)
from src.time_utils import utc_now_iso

if TYPE_CHECKING:  # nur für die Signaturen
    from src.settings import SettingsLike

_log = logging.getLogger(__name__)

API_VERSION = 1

# Nur YYYY-MM-DD in ASCII-Ziffern: `date.fromisoformat` nimmt seit 3.11 auch
# "20260105" und "2026-W01-1", und `\d` matcht Ziffern anderer Schriften.
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_NAME_ECHO_MAX = 40


class EntryStore(Protocol):
    def get_all(self) -> dict[str, dict[str, Any]]: ...

    def get(self, date_str: str) -> dict[str, Any] | None: ...

    def save(self, date_str: str, slots: list[dict[str, Any]]) -> None: ...

    def delete(self, date_str: str) -> None: ...


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


def _no_change() -> None:
    return None


def _not_closing() -> bool:
    return False


@dataclass(frozen=True)
class ApiContext:
    storage: EntryStore
    settings: SettingsLike
    app_version: Callable[[], str]
    now: Callable[[], str] = utc_now_iso
    # Nur für schreibende Routen. `data_lock` ist der geteilte Store-`RLock`
    # der App (Prüfen, Konfliktcheck und Speichern laufen darunter);
    # `on_change` meldet der UI eine Änderung (App: `_marshal_to_ui(_refresh)`)
    # und läuft NACH dem Lock.
    data_lock: Any = None
    conflicts_store: Any = None
    vacation_store: Any = None
    # Reservierungen (#239): der Store, und der Kalender-Abgleich, den die UI nach
    # jedem Speichern oder Löschen anstößt (App: `_marshal_to_ui` →
    # `trigger_reconcile`; das gatet selbst auf `gcal_enabled`). `today` ist das
    # lokale Datum, injizierbar für die Tests.
    reservation_store: Any = None
    on_reservations_change: Callable[[], None] = _no_change
    today: Callable[[], datetime.date] = datetime.date.today
    on_change: Callable[[], None] = _no_change
    # Wahr, sobald die App beendet oder entfernt wird: schreibende Routen
    # lehnen dann (unter dem Lock) mit 503 ab. Der Sync-Push nimmt denselben
    # Lock — so landet nach `shutdown()` nichts mehr hinter dem Push-Snapshot.
    closing: Callable[[], bool] = _not_closing


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


def _wire_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Nur die vier Felder des Protokolls. `sanitize_slot` behält Zusatzschlüssel
    (Plan-Ruling), und ein gespeichertes `NaN`/`-Infinity` darin verließe die API als
    nicht-striktes JSON. Die Werte der vier Felder hat die Lese-Grenze schon bereinigt."""
    return [{key: slot[key] for key in ("start", "end", "pause", "kategorie")} for slot in slots]


def _query_range(query: Mapping[str, list[str]]) -> tuple[datetime.date | None, datetime.date | None]:
    _only_params(query, frozenset({"from", "to"}))
    start = _query_date(query, "from")
    end = _query_date(query, "to")
    if start is not None and end is not None and start > end:
        raise _ApiError(400, "invalid_range", "from liegt nach to.")
    return start, end


def _in_range(day: datetime.date, start: datetime.date | None, end: datetime.date | None) -> bool:
    return not ((start is not None and day < start) or (end is not None and day > end))


def _entries(request: ApiRequest, ctx: ApiContext, _match: re.Match[str]) -> ApiResponse:
    start, end = _query_range(request.query)
    entries: dict[str, Any] = {}
    for day_key, entry in ctx.storage.get_all().items():
        day = parse_date(day_key)
        if day is None:                          # kaputter Schlüssel: nie ausliefern
            continue
        if not _in_range(day, start, end):
            continue
        entries[day_key] = {**entry, "slots": _wire_slots(entry["slots"])}
    return ApiResponse(200, {"entries": dict(sorted(entries.items()))})


def _entry(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    day_key = match.group(1)
    if parse_date(day_key) is None:
        raise _ApiError(400, "invalid_date", "Erwartet YYYY-MM-DD.")
    entry = ctx.storage.get(day_key)
    if entry is None:
        raise _ApiError(404, "not_found", "Für diesen Tag gibt es keinen Eintrag.")
    return ApiResponse(200, {"date": day_key, "slots": _wire_slots(entry["slots"])})


def _check_year(year: int) -> None:
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise _ApiError(422, "date_out_of_range",
                        f"Nur die Jahre {MIN_YEAR} bis {MAX_YEAR} werden unterstützt.")


def _summary(ctx: ApiContext, span: tuple[datetime.date, datetime.date]) -> dict[str, Any]:
    vacation = ctx.vacation_store.day_minutes() if ctx.vacation_store is not None else {}
    return summarize(span[0], span[1], ctx.storage.get_all(), ctx.settings, vacation)


def _summary_week(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    raw = match.group(1)
    span = parse_week(raw)
    if span is None:
        raise _ApiError(400, "invalid_week", "Erwartet YYYY-Www, zum Beispiel 2026-W01.")
    _check_year(int(raw[:4]))
    return ApiResponse(200, {"week": raw, **_summary(ctx, span)})


def _summary_month(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    raw = match.group(1)
    span = parse_month(raw)
    if span is None:
        raise _ApiError(400, "invalid_month", "Erwartet YYYY-MM, zum Beispiel 2026-01.")
    _check_year(span[0].year)
    return ApiResponse(200, {"month": raw, **_summary(ctx, span)})


def _categories(request: ApiRequest, ctx: ApiContext, _match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    return ApiResponse(200, {"categories": category_names(ctx.settings)})


def _holidays(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    year = parse_year(match.group(1))
    if year is None:
        raise _ApiError(400, "invalid_year", "Erwartet YYYY, zum Beispiel 2026.")
    _check_year(year)
    return ApiResponse(200, holidays_for(ctx.settings, year))


def _locked(ctx: ApiContext) -> Any:
    return ctx.data_lock if ctx.data_lock is not None else contextlib.nullcontext()


def _refuse_while_closing(ctx: ApiContext) -> None:
    if ctx.closing():
        raise _ApiError(503, "shutting_down", "Die App wird gerade beendet.")


def _notify(ctx: ApiContext) -> None:
    try:
        ctx.on_change()
    except Exception:
        # Die Daten sind gespeichert; ein Fehler beim Neuzeichnen darf daraus
        # keine 500 machen (der Client würde den Schreibzugriff wiederholen).
        _log.exception("Lokale API: on_change nach dem Schreiben fehlgeschlagen")


def _write_day(match: re.Match[str]) -> str:
    day_key = match.group(1)
    day = parse_date(day_key)
    if day is None:
        raise _ApiError(400, "invalid_date", "Erwartet YYYY-MM-DD.")
    check_date_range(day)
    return day_key


def _put_entry(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    day_key = _write_day(match)
    slots = parse_day_body(request.body)
    with _locked(ctx):
        _refuse_while_closing(ctx)
        check_day_writable(day_key, conflicts_store=ctx.conflicts_store,
                           vacation_store=ctx.vacation_store, for_save=True)
        existing = ctx.storage.get(day_key)
        changed = existing is None or existing["slots"] != slots
        warnings = warnings_for(ctx.settings, ctx.storage.get_all(), day_key, slots)
        if changed:
            ctx.storage.save(day_key, slots)
        stored = ctx.storage.get(day_key)
    if changed:
        _notify(ctx)
    return ApiResponse(200, {"date": day_key,
                             "slots": stored["slots"] if stored else slots,
                             "changed": changed, "warnings": warnings})


def _delete_entry(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    day_key = _write_day(match)
    with _locked(ctx):
        _refuse_while_closing(ctx)
        check_day_writable(day_key, conflicts_store=ctx.conflicts_store,
                           vacation_store=ctx.vacation_store, for_save=False)
        if ctx.storage.get(day_key) is None:
            raise _ApiError(404, "not_found", "Für diesen Tag gibt es keinen Eintrag.")
        ctx.storage.delete(day_key)
    _notify(ctx)
    return ApiResponse(200, {"date": day_key, "deleted": True})


# --- Reservierungen (#239) ------------------------------------------------------

_RESERVATIONS_OFF = (
    "Reservierungen sind in der App ausgeschaltet. Einstellungen → Arbeitszeit → "
    "„Reservierungen verwenden“ einschalten und speichern, dann erneut versuchen.")


def _reservation_store(ctx: ApiContext, *, writing: bool) -> Any:
    """Lesen geht, sobald es den Store gibt; Schreiben nur mit eingeschalteten
    Reservierungen — sonst legte ein Skript Tage an, die in der App unsichtbar und
    nicht löschbar wären (`App._reservations_active`)."""
    store = ctx.reservation_store
    if store is None or (writing and not ctx.settings.get("reservations_enabled")):
        raise _ApiError(409, "reservations_disabled", _RESERVATIONS_OFF)
    return store


def _wire_reservation_slots(slots: Any) -> list[dict[str, Any]]:
    """Nur die vier Felder der API, nie `gcal_event_id`. Gespeicherte Slots sind
    Fremddaten (Kalender-Abgleich, Handbearbeitung): ohne Textzeiten entfällt der
    Slot, ein falscher Typ wird zum Leerwert."""
    out: list[dict[str, Any]] = []
    for slot in slots if isinstance(slots, list) else []:
        if not (isinstance(slot, dict) and isinstance(slot.get("start"), str)
                and isinstance(slot.get("end"), str)):
            continue
        category = slot.get("kategorie")
        reminder = slot.get("send_reminder_minutes")
        out.append({
            "start": slot["start"], "end": slot["end"],
            "kategorie": category if isinstance(category, str) else "",
            "send_reminder_minutes": (reminder if isinstance(reminder, int)
                                      and not isinstance(reminder, bool) else None),
        })
    return out


def _reservations(request: ApiRequest, ctx: ApiContext, _match: re.Match[str]) -> ApiResponse:
    start, end = _query_range(request.query)
    store = _reservation_store(ctx, writing=False)
    found: dict[str, Any] = {}
    for day_key, entry in store.get_all().items():
        day = parse_date(day_key)
        if day is None or not _in_range(day, start, end):
            continue
        slots = _wire_reservation_slots(entry.get("slots"))
        if slots:
            found[day_key] = {"slots": slots}
    return ApiResponse(200, {"reservations": dict(sorted(found.items()))})


def _reservation(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    day_key = match.group(1)
    if parse_date(day_key) is None:
        raise _ApiError(400, "invalid_date", "Erwartet YYYY-MM-DD.")
    entry = _reservation_store(ctx, writing=False).get(day_key)
    slots = _wire_reservation_slots(entry["slots"]) if entry else []
    if not slots:
        raise _ApiError(404, "not_found", "Für diesen Tag gibt es keine Reservierung.")
    return ApiResponse(200, {"date": day_key, "slots": slots})


def _notify_reservations(ctx: ApiContext) -> None:
    """Neuzeichnen und Kalender-Abgleich, beide nach dem Lock. Die UI stößt nach
    jedem Speichern oder Löschen denselben Abgleich an — die API ist kein Sonderweg."""
    _notify(ctx)
    try:
        ctx.on_reservations_change()
    except Exception:
        # Wie bei `_notify`: gespeichert ist gespeichert, der Client soll nicht
        # wiederholen, nur weil der Abgleich nicht angestoßen werden konnte.
        _log.exception("Lokale API: Kalender-Abgleich nach dem Schreiben nicht angestoßen")


def _carry_reminder(slots: list[dict[str, Any]], existing: dict[str, Any] | None) -> None:
    """Nennt der Body `send_reminder_minutes` nirgends, bleibt die Markierung des
    Nutzers: positionsweise vom bisherigen Stand, wie der Store es mit `gcal_event_id`
    hält."""
    old = _wire_reservation_slots(existing["slots"]) if existing else []
    for index, slot in enumerate(slots):
        if index < len(old):
            slot["send_reminder_minutes"] = old[index]["send_reminder_minutes"]


def _put_reservation(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    store = _reservation_store(ctx, writing=True)
    day_key = _write_day(match)
    check_reservation_day(datetime.date.fromisoformat(day_key), ctx.today())
    slots, reminder_given = parse_reservation_body(request.body)
    with _locked(ctx):
        _refuse_while_closing(ctx)
        _check_no_vacation(ctx, day_key)
        existing = store.get(day_key)
        if not reminder_given:
            _carry_reminder(slots, existing)
        existing_slots = _wire_reservation_slots(existing["slots"]) if existing else None
        changed = existing_slots != slots
        if changed:
            store.save(day_key, slots)
        stored = store.get(day_key)
    if changed:
        _notify_reservations(ctx)
    return ApiResponse(200, {"date": day_key,
                             "slots": _wire_reservation_slots(stored["slots"]) if stored else slots,
                             "changed": changed})


def _check_no_vacation(ctx: ApiContext, day_key: str) -> None:
    """Urlaub und Arbeitszeit schließen sich aus; der Tages-Dialog öffnet an einem
    Urlaubstag gar nicht, also auch keine Reservierung. 0-Minuten-Tage einer Periode
    sind kein Urlaubstag."""
    if ctx.vacation_store is None:
        return
    period = ctx.vacation_store.period_for_date(day_key)
    if period is not None and period.get("days", {}).get(day_key, 0):
        raise _ApiError(409, "vacation_day",
                        f"Für diesen Tag ist Urlaub eingetragen („{period.get('name', '')}“). "
                        "An einem Urlaubstag lässt sich nichts reservieren; den Urlaub "
                        "zuerst in der App löschen.")


def _delete_reservation(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    store = _reservation_store(ctx, writing=True)
    day_key = _write_day(match)
    with _locked(ctx):
        _refuse_while_closing(ctx)
        if store.get(day_key) is None:
            raise _ApiError(404, "not_found", "Für diesen Tag gibt es keine Reservierung.")
        store.delete(day_key)
    _notify_reservations(ctx)
    return ApiResponse(200, {"date": day_key, "deleted": True})


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
    Route("PUT", re.compile(r"/v1/entries/([^/]+)"), _put_entry, SCOPE_LOCAL),
    Route("DELETE", re.compile(r"/v1/entries/([^/]+)"), _delete_entry, SCOPE_LOCAL),
    Route("GET", re.compile(r"/v1/reservations"), _reservations, SCOPE_LOCAL),
    Route("GET", re.compile(r"/v1/reservations/([^/]+)"), _reservation, SCOPE_LOCAL),
    Route("PUT", re.compile(r"/v1/reservations/([^/]+)"), _put_reservation, SCOPE_LOCAL),
    Route("DELETE", re.compile(r"/v1/reservations/([^/]+)"), _delete_reservation, SCOPE_LOCAL),
    Route("GET", re.compile(r"/v1/summary/week/([^/]+)"), _summary_week, SCOPE_LOCAL),
    Route("GET", re.compile(r"/v1/summary/month/([^/]+)"), _summary_month, SCOPE_LOCAL),
    Route("GET", re.compile(r"/v1/categories"), _categories, SCOPE_LOCAL),
    Route("GET", re.compile(r"/v1/holidays/([^/]+)"), _holidays, SCOPE_LOCAL),
)


def methods_for_path(path: str) -> frozenset[str]:
    """Die Methoden, die ROUTES für genau diesen Pfad kennen (leer = unbekannter Pfad)."""
    return frozenset(route.method for route in ROUTES if route.pattern.fullmatch(path))


def routed_methods() -> frozenset[str]:
    """Die Methoden, die irgendeine Route kennt (für `Allow` bei einem 405, das
    `authorize` vor dem Routing ausspricht)."""
    return frozenset(route.method for route in ROUTES)


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
    except (_ApiError, WriteError) as exc:
        return error_response(exc.status, exc.code, exc.message)
