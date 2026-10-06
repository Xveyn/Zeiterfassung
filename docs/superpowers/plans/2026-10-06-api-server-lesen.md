# Lokale API, PR 2: Server und lesende Routen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die lokale HTTP-API läuft: ein Server im App-Prozess (nur `127.0.0.1`, Default aus) mit `GET /v1/status`, `GET /v1/entries` und `GET /v1/entries/{date}`, gesteuert über zwei gerätelokale Settings, verdrahtet in `App` samt sauberem Stopp beim Beenden, Entfernen und Skalierungs-Neustart.

**Architecture:** Drei Tk-freie Module: `api_routes` (Routing und Antworten, ohne Socket), `api_server` (dünner `ThreadingHTTPServer` im Daemon-Thread, ruft `api_auth.authorize` vor dem Routing), `api_service` (Lebenszyklus: Settings → Token laden → Server starten/stoppen, immer im Worker, Status für den späteren Settings-Tab). `App` bekommt nur Verdrahtung (`_apply_api_setting`, drei Stopp-Stellen).

**Tech Stack:** Python 3.12, stdlib (`http.server`, `socketserver`, `threading`, `json`), pytest. Keine neue Abhängigkeit.

**Spec:** `docs/superpowers/specs/2026-10-06-lokale-api-design.md` (Abschnitte „Module", „Verdrahtung", „Endpunkte", „Threading"). Checkliste und Minors: Issue #233.

**Branching:** Stack. `git switch feat/api-auth && git switch -c feat/api-server-read`. PR 2 zielt auf `feat/api-auth` (PR 1, #235) und wird danach mit `POST /repos/Xveyn/Zeiterfassung/stacks/236/add` an den Stack gehängt. PR-Text enthält `Refs #92`, **kein** `Closes`.

## Zuschnitt (Rulings gegenüber der Spec)

Die Spec fasst unter Stack-Punkt 2 „Server und lesende Routen, `/status`, Settings-Tab, Verdrahtung" zusammen. Dieser PR nimmt das Tk-freie Rückgrat und lässt zwei Dinge für eigene PRs:

- **Settings-Tab** (Schalter, Port, Token anzeigen/kopieren/neu erzeugen, Statusgrund) → **PR 3**. Er ist UI ohne Tests und verdient eine eigene Prüfung; bis dahin lässt sich die API nur über `settings.json` einschalten und ist unveröffentlicht. `ApiService` liefert den Status samt Grund schon hier, damit PR 3 nur noch zeichnet.
- **Lesende Routen** sind hier `status` und `entries`. Reservierungen, Summen, Wochenlimit/Pausenpflicht, Kategorien und Feiertage bleiben im PR „Reservierungen und Auswertungen" (Spec-Stack Punkt 4). Das ist der kleinste senkrechte Schnitt, der Server, Auth, Routing und Datenzugriff Ende zu Ende beweist.

Die Spec-Stack-Liste wird in Task 5 entsprechend umnummeriert.

## Global Constraints

- Tk-frei, stdlib-only, vollständig annotiert (Rückgabetyp und alle Parameter); Einträge in `ANNOTATED_MODULES` (`tests/test_type_annotations.py`).
- Server bindet **nur** `127.0.0.1` (Bind-Adresse kommt aus `Policy.bind_host`); Default `api_enabled = False`; Port Default `17653`, gültig 1024–65535.
- Reihenfolge je Anfrage: doppelte Header (`host`, `authorization`, `origin`, `content-type`, `content-length`) → 400 → `api_auth.authorize` → `Transfer-Encoding` → 400 → Body lesen (Limit 1 MiB, sonst 413) → Routing → Scope → Handler.
- Kein einziger `Access-Control-*`-Header, nie. Jede Antwort trägt `Content-Type: application/json; charset=utf-8`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Connection: close`; `Server: Zeiterfassung-API` (ohne Python-Version). 401 trägt `WWW-Authenticate: Bearer`, 405 trägt `Allow`.
- Fehlerform: `{"error": {"code": "...", "message": "..."}}`. HTML-Fehlerseiten von `http.server` gibt es nicht (`send_error` ist überschrieben). Ein unerwarteter Fehler im Handler ergibt 500 `internal_error` **ohne** Details im Body, mit `_log.exception` im Log.
- Slot-Format `{start, end, pause, kategorie}`; Summen nie als Dezimalstunden (in diesem PR gibt es keine).
- Die Routen halten keinen Lock und ändern nichts; Daten kommen über `Storage.get_all()`/`get()`, die den geteilten `data_lock` selbst nehmen und Kopien liefern.
- `load_or_create_token` blockiert (Windows: `icacls` bis 15 s): **nur im Worker** (`BackgroundTaskRunner.run`), nie im UI-Thread. Beenden, Entfernen und Skalierungs-Neustart dürfen **nie** auf einen laufenden Start warten (Lock-Timeout statt Blockade).
- Der Server-Thread berührt nie ein Tk-Widget (in diesem PR gibt es keinen UI-Rückruf).
- Unter Windows bindet der Server mit `SO_EXCLUSIVEADDRUSE` (ohne `SO_REUSEADDR`), sonst könnte ein anderer lokaler Prozess den Port kapern und Bearer-Token mitlesen.
- Jeder `except Exception`/`BaseException` loggt, meldet oder trägt eine Begründung im Handler (`tests/test_catch_all_handlers.py`); `except BaseException` re-raist.
- `ruff check .` sauber; kein neues `print`.

## Review Focus

Eingaben und Zustände, die die Spec nahelegt, aber keine Task-Beschreibung erzwingt. Jede Zeile ist in der genannten Task durch einen Test gepinnt.

1. **Mehrdeutige Query und kaputte Datumsformen** (doppelte Parameter, unbekannte Parameter, `20260105`, `2026-W01-1`, `2026-02-30`, arabisch-indische Ziffern, `//v1/status`, `/v1/status#x`): immer 400 bzw. 404, nie ein Treffer über einen Parser-Quirk. Task 1 und 2.
2. **Böse Header und Bodies** (doppelte `Host`/`Authorization`/`Content-Length`, `Transfer-Encoding: chunked`, `Content-Length` nicht numerisch/negativ/5000 Ziffern/2 MB, abgebrochener Body, Protokollfehler wie 150 Header): definierte 4xx als JSON, nie eine Exception, nie ein Hänger, nie eine HTML-Seite. Task 2.
3. **Port belegt, Neustart auf demselben Port, Hostname-Auflösung:** zweiter Server auf demselben Port → `OSError`; Stopp gibt den Port frei (Verbindung abgelehnt) und ein neuer Start gelingt; `start()` ruft nie `socket.getfqdn` (kann bei kaputtem DNS hängen). Task 2.
4. **Beenden/Entfernen während eines Starts:** `shutdown()` kehrt binnen Sekundenbruchteilen zurück, auch wenn der Worker gerade das Token lädt; danach startet kein Server mehr und es wird kein Token mehr geschrieben. Task 3.
5. **Ungültige Settings** (`api_port` = `"abc"`, `0`, `80`, `70000`, `None`, `True`, `""`, `"17653.5"`, `-5`): Status `invalid_port`, kein Server, **kein** `api-token` angelegt, kein Crash; Ausschalten stoppt wirklich; Portwechsel bindet neu. Task 3.

---

### Task 1: `api_routes` — Routing und lesende Routen

**Files:**
- Create: `src/api_routes.py`
- Create: `tests/test_api_routes.py`
- Modify: `tests/test_type_annotations.py` (`"src/api_routes.py"` in `ANNOTATED_MODULES`)

**Interfaces:**
- Consumes: `src.api_auth.SCOPE_LOCAL`, `Principal`, `require_scope(principal, scope) -> AuthResult`; `src.time_utils.utc_now_iso() -> str`; `Storage.get_all() -> dict[str, {"slots": [...]}]` (Tombstones fehlen), `Storage.get(date) -> {"slots": [...]} | None`.
- Produces (Task 2 und 3 verlassen sich darauf):
  - `API_VERSION: int = 1`
  - `ApiRequest(method: str, path: str, query: Mapping[str, list[str]], body: bytes = b"")` (frozen)
  - `ApiResponse(status: int, body: Any, headers: Mapping[str, str] = {})` (frozen)
  - `ApiContext(storage: EntryStore, settings: SettingsLike, app_version: Callable[[], str], now: Callable[[], str] = utc_now_iso)` (frozen)
  - `error_response(status: int, code: str, message: str, headers: Mapping[str, str] | None = None) -> ApiResponse`
  - `handle(request: ApiRequest, ctx: ApiContext, principal: Principal) -> ApiResponse` — wirft nur bei einem echten Programmfehler.

- [ ] **Step 1: Failing tests schreiben**

`tests/test_api_routes.py`:

```python
# tests/test_api_routes.py
import pytest

from src.api_auth import SCOPE_LOCAL, Principal
from src.api_routes import API_VERSION, ApiContext, ApiRequest, handle
from src.storage import Storage
from tests.conftest import ist_slot

LOCAL = Principal("local", frozenset({SCOPE_LOCAL}))


@pytest.fixture
def storage(tmp_path):
    return Storage(str(tmp_path / "zeiterfassung.json"), device_id="dev")


def make_ctx(storage, settings=None, version="1.2.3-test", now="2026-10-06T12:00:00Z"):
    return ApiContext(
        storage=storage,
        settings={"device_name": "Laptop"} if settings is None else settings,
        app_version=lambda: version,
        now=lambda: now,
    )


def call(path, ctx, query=None, method="GET", principal=LOCAL):
    return handle(ApiRequest(method, path, query or {}), ctx, principal)


def seed(storage):
    storage.save("2026-01-05", [ist_slot("08:00", "12:00", 0, "Projekt")])
    storage.save("2026-01-20", [ist_slot("09:00", "17:00", 30)])
    storage.save("2026-02-03", [ist_slot("10:00", "11:00")])


# --- /v1/status ----------------------------------------------------------

def test_status_reports_versions_device_and_time(storage):
    response = call("/v1/status", make_ctx(storage))

    assert response.status == 200
    assert response.body == {
        "api_version": API_VERSION,
        "app_version": "1.2.3-test",
        "device_name": "Laptop",
        "time": "2026-10-06T12:00:00Z",
    }


def test_status_device_name_defaults_to_empty(storage):
    response = call("/v1/status", make_ctx(storage, settings={}))
    assert response.body["device_name"] == ""


def test_status_takes_no_query(storage):
    response = call("/v1/status", make_ctx(storage), {"x": ["1"]})
    assert (response.status, response.body["error"]["code"]) == (400, "unknown_parameter")


# --- /v1/entries ------------------------------------------------------------

def test_entries_without_range_returns_everything_sorted(storage):
    seed(storage)

    response = call("/v1/entries", make_ctx(storage))

    assert response.status == 200
    entries = response.body["entries"]
    assert list(entries) == ["2026-01-05", "2026-01-20", "2026-02-03"]
    assert entries["2026-01-05"] == {
        "slots": [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}]}


def test_entries_empty_store_gives_empty_object(storage):
    assert call("/v1/entries", make_ctx(storage)).body == {"entries": {}}


@pytest.mark.parametrize("query,expected", [
    ({"from": ["2026-01-20"]}, ["2026-01-20", "2026-02-03"]),
    ({"to": ["2026-01-20"]}, ["2026-01-05", "2026-01-20"]),
    ({"from": ["2026-01-06"], "to": ["2026-02-02"]}, ["2026-01-20"]),
    ({"from": ["2026-01-05"], "to": ["2026-01-05"]}, ["2026-01-05"]),
    ({"from": ["2027-01-01"]}, []),
])
def test_entries_range_is_inclusive(storage, query, expected):
    seed(storage)
    response = call("/v1/entries", make_ctx(storage), query)
    assert list(response.body["entries"]) == expected


def test_entries_leave_out_tombstones(storage):
    seed(storage)
    storage.delete("2026-01-20")

    response = call("/v1/entries", make_ctx(storage))

    assert list(response.body["entries"]) == ["2026-01-05", "2026-02-03"]


def test_entries_are_copies_of_the_store(storage):
    seed(storage)
    first = call("/v1/entries", make_ctx(storage))
    first.body["entries"]["2026-01-05"]["slots"][0]["start"] = "00:00"

    second = call("/v1/entries", make_ctx(storage))

    assert second.body["entries"]["2026-01-05"]["slots"][0]["start"] == "08:00"


# --- Review Focus 1: Datumsformen und Query ----------------------------------

BAD_DATES = ["2026-1-5", "20260105", "2026-W01-1", "2026-02-30", "2026-13-01", "",
             "heute", "2026-01-05T10:00", "٢٠٢٦-٠١-٠١", " 2026-01-05"]


@pytest.mark.parametrize("value", BAD_DATES)
@pytest.mark.parametrize("name", ["from", "to"])
def test_entries_reject_anything_but_iso_dates(storage, name, value):
    response = call("/v1/entries", make_ctx(storage), {name: [value]})
    assert (response.status, response.body["error"]["code"]) == (400, "invalid_date")


def test_entries_reject_a_reversed_range(storage):
    response = call("/v1/entries", make_ctx(storage),
                    {"from": ["2026-02-01"], "to": ["2026-01-01"]})
    assert (response.status, response.body["error"]["code"]) == (400, "invalid_range")


def test_entries_reject_unknown_parameters(storage):
    response = call("/v1/entries", make_ctx(storage), {"form": ["2026-01-01"]})
    assert (response.status, response.body["error"]["code"]) == (400, "unknown_parameter")


def test_entries_reject_repeated_parameters(storage):
    response = call("/v1/entries", make_ctx(storage),
                    {"from": ["2026-01-01", "2026-01-02"]})
    assert (response.status, response.body["error"]["code"]) == (400, "duplicate_parameter")


def test_error_message_does_not_echo_unbounded_input(storage):
    response = call("/v1/entries", make_ctx(storage), {"x" * 5000: ["1"]})
    assert len(response.body["error"]["message"]) < 200


# --- /v1/entries/{date} --------------------------------------------------------

def test_single_entry_returns_the_day(storage):
    seed(storage)

    response = call("/v1/entries/2026-01-20", make_ctx(storage))

    assert response.status == 200
    assert response.body == {
        "date": "2026-01-20",
        "slots": [{"start": "09:00", "end": "17:00", "pause": 30, "kategorie": ""}],
    }


def test_single_entry_missing_day_is_404(storage):
    response = call("/v1/entries/2026-03-01", make_ctx(storage))
    assert (response.status, response.body["error"]["code"]) == (404, "not_found")


def test_single_entry_tombstone_is_404(storage):
    seed(storage)
    storage.delete("2026-01-20")
    assert call("/v1/entries/2026-01-20", make_ctx(storage)).status == 404


@pytest.mark.parametrize("value", ["2026-02-30", "20260105", "2026-W01-1", "heute",
                                   "٢٠٢٦-٠١-٠١", "2026-1-5"])
def test_single_entry_rejects_bad_dates_with_400(storage, value):
    response = call(f"/v1/entries/{value}", make_ctx(storage))
    assert (response.status, response.body["error"]["code"]) == (400, "invalid_date")


def test_single_entry_takes_no_query(storage):
    seed(storage)
    response = call("/v1/entries/2026-01-20", make_ctx(storage), {"from": ["2026-01-01"]})
    assert (response.status, response.body["error"]["code"]) == (400, "unknown_parameter")


# --- Routing, Methoden, Scope -----------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/v1", "/v1/", "/v1/status/", "//v1/status",
                                  "/v1/statu", "/v1/entries/", "/v1/entries/2026-01-05/x",
                                  "/V1/status", "/v1/status#x", "/v2/status",
                                  "/v1/%73tatus"])
def test_unknown_paths_are_404(storage, path):
    response = call(path, make_ctx(storage))
    assert (response.status, response.body["error"]["code"]) == (404, "not_found")


@pytest.mark.parametrize("path,allow", [("/v1/status", "GET"), ("/v1/entries", "GET"),
                                        ("/v1/entries/2026-01-05", "GET")])
@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_wrong_method_on_a_known_path_is_405_with_allow(storage, path, allow, method):
    response = call(path, make_ctx(storage), method=method)
    assert (response.status, response.body["error"]["code"]) == (405, "method_not_allowed")
    assert response.headers["Allow"] == allow


def test_a_principal_without_the_scope_is_403(storage):
    stranger = Principal("pixel", frozenset({"mobile-sync"}))

    response = call("/v1/status", make_ctx(storage), principal=stranger)

    assert (response.status, response.body["error"]["code"]) == (403, "insufficient_scope")


def test_unexpected_store_errors_propagate_to_the_server(storage):
    class Broken:
        def get_all(self):
            raise RuntimeError("kaputt")

        def get(self, date_str):
            raise RuntimeError("kaputt")

    ctx = ApiContext(storage=Broken(), settings={}, app_version=lambda: "x")

    with pytest.raises(RuntimeError):
        call("/v1/entries", ctx)
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `python3 -m pytest tests/test_api_routes.py -q -p no:cacheprovider`
Expected: FAIL beim Import (`ModuleNotFoundError: No module named 'src.api_routes'`).

- [ ] **Step 3: Minimal implementieren**

`src/api_routes.py`:

```python
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
```

In `tests/test_type_annotations.py` die Liste `ANNOTATED_MODULES` um `"src/api_routes.py",` ergänzen (direkt hinter `"src/api_auth.py",`).

- [ ] **Step 4: Tests laufen lassen**

Run: `python3 -m pytest tests/test_api_routes.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:cacheprovider`
Expected: alle PASS.

- [ ] **Step 5: Commit**

```bash
git add src/api_routes.py tests/test_api_routes.py tests/test_type_annotations.py
git commit -m "$(cat <<'EOF'
feat(api): Routing und lesende Routen der lokalen API (#92)

GET /v1/status, /v1/entries und /v1/entries/{date}, ohne Socket testbar.
Strenge Datums- und Query-Prüfung, Scope pro Route, 405 mit Allow.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `api_server` — HTTP-Server im Daemon-Thread

**Files:**
- Create: `src/api_server.py`
- Create: `tests/test_api_server.py`
- Modify: `tests/test_type_annotations.py` (`"src/api_server.py"`)

**Interfaces:**
- Consumes (Task 1 und PR 1): `api_auth.authorize(method, headers, policy, verifier) -> AuthResult`, `AuthResult(status, code, principal)`, `ALLOWED_METHODS`, `Policy` (`Policy.loopback(port)`, `bind_host`), `TokenVerifier`, `single_token_verifier`; `api_routes.ApiContext`, `ApiRequest`, `ApiResponse`, `error_response`, `handle`.
- Produces (Task 3 verlässt sich darauf):
  - `MAX_BODY_BYTES: int = 1048576`
  - `ApiServer(context: ApiContext, verifier: TokenVerifier, *, port: int = 0, policy_for_port: Callable[[int], Policy] = Policy.loopback)`
  - `ApiServer.start() -> None` (wirft `OSError`, wenn der Bind scheitert; `RuntimeError`, wenn schon gestartet)
  - `ApiServer.port -> int` (tatsächlicher Port; `RuntimeError`, wenn nicht gestartet)
  - `ApiServer.set_verifier(verifier: TokenVerifier) -> None`
  - `ApiServer.stop(timeout: float = 2.0) -> None` (idempotent, gibt den Port frei)

- [ ] **Step 1: Failing tests schreiben**

`tests/test_api_server.py`:

```python
# tests/test_api_server.py
import http.client
import json
import logging
import socket
import threading
import time

import pytest

from src import api_server
from src.api_auth import single_token_verifier
from src.api_routes import ApiContext
from src.api_server import MAX_BODY_BYTES, ApiServer
from src.storage import Storage
from tests.conftest import ist_slot

TOKEN = "T" * 43


def make_context(tmp_path, storage=None):
    if storage is None:
        storage = Storage(str(tmp_path / "zeiterfassung.json"), device_id="dev")
        storage.save("2026-01-05", [ist_slot("08:00", "12:00", 0, "Projekt")])
    return ApiContext(storage=storage, settings={"device_name": "Test"},
                      app_version=lambda: "9.9.9")


@pytest.fixture
def server(tmp_path):
    srv = ApiServer(make_context(tmp_path), single_token_verifier(TOKEN), port=0)
    srv.start()
    yield srv
    srv.stop()


def http_call(server, method, path, headers=None, body=None, drop=(), token=TOKEN):
    """Eine Anfrage; Header-Werte dürfen Listen sein (doppelte Header)."""
    merged = {} if token is None else {"Authorization": f"Bearer {token}"}
    merged.update(headers or {})
    for name in drop:
        merged.pop(name, None)
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    try:
        conn.putrequest(method, path, skip_host="Host" in merged,
                        skip_accept_encoding=True)
        for name, value in merged.items():
            for single in (value if isinstance(value, list) else [value]):
                conn.putheader(name, single)
        if body is not None and "Content-Length" not in merged:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body)
        response = conn.getresponse()
        raw = response.read()
        return response, (json.loads(raw) if raw else None), raw
    finally:
        conn.close()


def error_code(parsed):
    return parsed["error"]["code"]


# --- Grundverhalten und Antwort-Header --------------------------------------

def test_status_with_valid_token(server):
    response, body, _ = http_call(server, "GET", "/v1/status")

    assert response.status == 200
    assert body["app_version"] == "9.9.9" and body["device_name"] == "Test"
    assert response.getheader("Content-Type") == "application/json; charset=utf-8"
    assert response.getheader("Cache-Control") == "no-store"
    assert response.getheader("X-Content-Type-Options") == "nosniff"


def test_entries_are_served_end_to_end(server):
    response, body, _ = http_call(server, "GET", "/v1/entries?from=2026-01-01&to=2026-01-31")

    assert response.status == 200
    assert body["entries"]["2026-01-05"]["slots"][0]["kategorie"] == "Projekt"


def test_server_header_hides_the_python_version(server):
    response, _, _ = http_call(server, "GET", "/v1/status")
    assert response.getheader("Server") == "Zeiterfassung-API"


def test_no_response_ever_carries_cors_headers(server):
    for method, path, token in [("GET", "/v1/status", TOKEN), ("GET", "/v1/status", None),
                                ("OPTIONS", "/v1/status", TOKEN), ("GET", "/nope", TOKEN)]:
        response, _, _ = http_call(server, method, path, token=token)
        cors = [n for n, _ in response.getheaders() if n.lower().startswith("access-control")]
        assert cors == [], (method, path, cors)


# --- Auth am Draht -----------------------------------------------------------

def test_missing_and_wrong_token_are_401_with_challenge(server):
    for token in (None, "falsch"):
        response, body, raw = http_call(server, "GET", "/v1/status", token=token)
        assert response.status == 401 and error_code(body) == "unauthorized"
        assert response.getheader("WWW-Authenticate") == "Bearer"
        assert TOKEN.encode() not in raw


def test_unknown_path_without_token_does_not_leak_existence(server):
    response, body, _ = http_call(server, "GET", "/v1/gibt-es-nicht", token=None)
    assert response.status == 401


def test_unknown_path_with_token_is_404_json(server):
    response, body, _ = http_call(server, "GET", "/v1/gibt-es-nicht")
    assert (response.status, error_code(body)) == (404, "not_found")


def test_options_head_patch_trace_and_unknown_methods_are_405_with_allow(server):
    for method in ("OPTIONS", "HEAD", "PATCH", "TRACE", "FOO"):
        response, _, _ = http_call(server, method, "/v1/status")
        assert response.status == 405, method
        assert response.getheader("Allow") == "DELETE, GET, POST, PUT"


def test_wrong_host_origin_and_sec_fetch_are_403(server):
    cases = [({"Host": "evil.example"}, "bad_host"),
             ({"Origin": "https://evil.example"}, "bad_origin"),
             ({"Sec-Fetch-Site": "cross-site"}, "browser_request")]
    for headers, code in cases:
        response, body, _ = http_call(server, "GET", "/v1/status", headers)
        assert (response.status, error_code(body)) == (403, code), headers


def test_a_write_without_json_content_type_is_415(server):
    response, body, _ = http_call(server, "PUT", "/v1/entries/2026-01-05", body=b"{}",
                                  headers={"Content-Type": "text/plain"})
    assert (response.status, error_code(body)) == (415, "unsupported_media_type")


# --- Review Focus 2: böse Header und Bodies ----------------------------------

@pytest.mark.parametrize("name", ["Host", "Authorization", "Origin", "Content-Type",
                                  "Content-Length"])
def test_duplicate_single_value_headers_are_400(server, name):
    values = {"Host": ["127.0.0.1", "evil.example"],
              "Authorization": [f"Bearer {TOKEN}", "Bearer x"],
              "Origin": ["a", "b"], "Content-Type": ["application/json"] * 2,
              "Content-Length": ["0", "0"]}[name]
    response, body, _ = http_call(server, "GET", "/v1/status", {name: values})
    assert (response.status, error_code(body)) == (400, "duplicate_header")


def test_chunked_transfer_encoding_is_400(server):
    response, body, _ = http_call(server, "GET", "/v1/status",
                                  {"Transfer-Encoding": "chunked"})
    assert (response.status, error_code(body)) == (400, "unsupported_encoding")


# Nicht dabei: Werte, die der Client selbst nicht senden kann (Nicht-Latin-1)
# oder die der Header-Parser vor dem Server zu einer gültigen Zahl trimmt (" 5").
@pytest.mark.parametrize("value", ["abc", "-1", "1.5", "²", "0x10", ""])
def test_invalid_content_length_is_400(server, value):
    response, body, _ = http_call(server, "GET", "/v1/status", {"Content-Length": value})
    assert (response.status, error_code(body)) == (400, "invalid_content_length")


@pytest.mark.parametrize("value", [str(MAX_BODY_BYTES + 1), "9" * 5000])
def test_oversized_body_is_413_without_reading_it(server, value):
    response, body, _ = http_call(server, "GET", "/v1/status", {"Content-Length": value})
    assert (response.status, error_code(body)) == (413, "payload_too_large")


def test_truncated_body_is_400(server):
    sock = socket.create_connection(("127.0.0.1", server.port), timeout=5)
    try:
        sock.sendall((f"GET /v1/status HTTP/1.0\r\nHost: 127.0.0.1:{server.port}\r\n"
                      f"Authorization: Bearer {TOKEN}\r\nContent-Length: 50\r\n\r\nkurz").encode())
        sock.shutdown(socket.SHUT_WR)
        raw = b""
        while chunk := sock.recv(4096):
            raw += chunk
    finally:
        sock.close()
    head, _, payload = raw.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.0 400")
    assert json.loads(payload)["error"]["code"] == "incomplete_body"


def test_protocol_errors_get_a_json_error_not_html(server):
    # 150 Header: `http.server` lehnt mit 431 ab, und zwar über `send_error` —
    # das ist überschrieben und muss JSON liefern statt der HTML-Seite.
    sock = socket.create_connection(("127.0.0.1", server.port), timeout=5)
    try:
        sock.sendall(b"GET /v1/status HTTP/1.0\r\n" + b"X: 1\r\n" * 150 + b"\r\n")
        raw = b""
        while chunk := sock.recv(4096):
            raw += chunk
    finally:
        sock.close()
    head, _, payload = raw.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.0 431")
    assert json.loads(payload)["error"]["code"] == "http_error"
    assert b"<html" not in raw.lower()


def test_path_forms_are_not_reinterpreted(server):
    for path in ("//v1/status", "/v1/status#x", "http://evil.example/v1/status"):
        response, _, _ = http_call(server, "GET", path)
        assert response.status == 404, path


def test_too_many_query_fields_are_400(server):
    query = "&".join(f"a{i}=1" for i in range(500))
    response, body, _ = http_call(server, "GET", f"/v1/entries?{query}")
    assert response.status == 400


def test_slow_client_is_dropped_and_the_server_keeps_serving(server, monkeypatch):
    monkeypatch.setattr(api_server._Handler, "timeout", 0.3)
    sock = socket.create_connection(("127.0.0.1", server.port), timeout=5)
    try:
        time.sleep(0.8)
        assert sock.recv(100) == b""          # Server hat die Verbindung geschlossen
    finally:
        sock.close()

    assert http_call(server, "GET", "/v1/status")[0].status == 200


def test_unexpected_handler_error_is_500_without_details(tmp_path, caplog):
    class Broken:
        def get_all(self):
            raise RuntimeError("geheime Details")

        def get(self, date_str):
            raise RuntimeError("geheime Details")

    srv = ApiServer(make_context(tmp_path, storage=Broken()), single_token_verifier(TOKEN))
    srv.start()
    try:
        with caplog.at_level(logging.ERROR):
            response, body, raw = http_call(srv, "GET", "/v1/entries")
    finally:
        srv.stop()

    assert (response.status, error_code(body)) == (500, "internal_error")
    assert b"geheime" not in raw
    assert "API-Anfrage fehlgeschlagen" in caplog.text


def test_concurrent_requests_are_all_served(server):
    results = []

    def worker():
        results.append(http_call(server, "GET", "/v1/status")[0].status)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [200] * 20


# --- Verifier-Tausch (Token-Rotation) ------------------------------------------

def test_set_verifier_switches_the_accepted_token_atomically(server):
    server.set_verifier(single_token_verifier("N" * 43))

    assert http_call(server, "GET", "/v1/status", token=TOKEN)[0].status == 401
    assert http_call(server, "GET", "/v1/status", token="N" * 43)[0].status == 200


# --- Review Focus 3: Bind, Port, Stopp -------------------------------------------

def test_server_binds_loopback_only(server):
    assert server._httpd.server_address[0] == "127.0.0.1"
    assert server.port > 0


def test_second_server_on_the_same_port_fails(server, tmp_path):
    other = ApiServer(make_context(tmp_path), single_token_verifier(TOKEN), port=server.port)
    with pytest.raises(OSError):
        other.start()


def test_stop_releases_the_port_and_a_new_start_succeeds(tmp_path):
    first = ApiServer(make_context(tmp_path), single_token_verifier(TOKEN), port=0)
    first.start()
    port = first.port
    first.stop()

    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)

    again = ApiServer(make_context(tmp_path), single_token_verifier(TOKEN), port=port)
    again.start()
    try:
        assert http_call(again, "GET", "/v1/status")[0].status == 200
    finally:
        again.stop()


def test_stop_is_idempotent_and_port_needs_a_running_server(tmp_path):
    srv = ApiServer(make_context(tmp_path), single_token_verifier(TOKEN))
    srv.stop()                                  # nie gestartet: kein Fehler
    srv.start()
    srv.stop()
    srv.stop()
    with pytest.raises(RuntimeError):
        _ = srv.port


def test_start_twice_is_a_programming_error(server):
    with pytest.raises(RuntimeError):
        server.start()


def test_start_does_not_resolve_the_host_name(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("socket.getfqdn kann bei kaputtem DNS hängen")

    monkeypatch.setattr(socket, "getfqdn", boom)
    srv = ApiServer(make_context(tmp_path), single_token_verifier(TOKEN))
    srv.start()
    srv.stop()
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `python3 -m pytest tests/test_api_server.py -q -p no:cacheprovider`
Expected: FAIL beim Import (`ModuleNotFoundError: No module named 'src.api_server'`).

- [ ] **Step 3: Minimal implementieren**

`src/api_server.py`:

```python
# src/api_server.py
"""HTTP-Server der lokalen API (#92), Tk-frei. Kein Fachwissen: er nimmt eine
Anfrage entgegen, lässt `api_auth.authorize` entscheiden, übergibt an
`api_routes.handle` und schreibt die Antwort.

Eigener Daemon-Thread (Muster: der Accept-Loop in `single_instance`), pro
Verbindung ein weiterer Daemon-Thread (`ThreadingMixIn`). Der Server berührt nie
ein Widget und hält keinen Store-Lock; die Routen holen ihre Daten über die
Store-Methoden.

Absichtlich NICHT `serve_forever()`/`shutdown()`: `shutdown()` blockiert für
immer, wenn es vor dem Eintritt in `serve_forever()` gerufen wird (Beenden
direkt nach dem Start). Stattdessen pollt eine eigene Schleife mit
`handle_request()` und einem 0,1-s-Timeout gegen ein `Event`.

Unter Windows bindet der Server mit `SO_EXCLUSIVEADDRUSE` und ohne
`SO_REUSEADDR`: sonst dürfte ein anderer lokaler Prozess denselben Port
zusätzlich binden und Bearer-Token mitlesen. Wie in `single_instance`.
"""
from __future__ import annotations

import http
import http.server
import json
import logging
import socket
import socketserver
import sys
import threading
from collections.abc import Callable
from typing import Any, cast
from urllib.parse import parse_qs

from src.api_auth import ALLOWED_METHODS, AuthResult, Policy, TokenVerifier, authorize
from src.api_routes import ApiContext, ApiRequest, ApiResponse, error_response, handle

_log = logging.getLogger(__name__)

MAX_BODY_BYTES = 1024 * 1024
_SOCKET_TIMEOUT_S = 10.0
_POLL_INTERVAL_S = 0.1
_MAX_QUERY_FIELDS = 20
_MAX_CONTENT_LENGTH_DIGITS = 12
# Diese Header dürfen genau einmal vorkommen. Ein `dict` kann Duplikate nicht
# darstellen — `authorize` sähe nur den letzten und könnte getäuscht werden.
_SINGLE_VALUE_HEADERS = ("host", "authorization", "origin", "content-type",
                         "content-length")

_AUTH_MESSAGES = {
    "method_not_allowed": "Methode nicht erlaubt.",
    "bad_host": "Ungültiger Host-Header.",
    "bad_origin": "Anfragen mit Origin-Header sind nicht erlaubt.",
    "browser_request": "Browser-Anfragen sind nicht erlaubt.",
    "unauthorized": "Token fehlt oder ist ungültig.",
    "unsupported_media_type": "Content-Type muss application/json sein.",
}


def _auth_error(auth: AuthResult) -> ApiResponse:
    headers: dict[str, str] = {}
    if auth.status == 405:
        headers["Allow"] = ", ".join(sorted(ALLOWED_METHODS))
    if auth.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return error_response(auth.status, auth.code,
                          _AUTH_MESSAGES.get(auth.code, "Abgelehnt."), headers)


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "Zeiterfassung-API"
    sys_version = ""
    protocol_version = "HTTP/1.0"            # eine Anfrage je Verbindung
    timeout = _SOCKET_TIMEOUT_S

    def version_string(self) -> str:
        return self.server_version

    def __getattr__(self, name: str) -> Any:
        # Jede Methode läuft durch denselben Weg — auch unbekannte, damit sie
        # von `authorize` mit 405 abgelehnt werden statt als HTML-501 von
        # `http.server`.
        if name.startswith("do_"):
            return self._serve
        raise AttributeError(name)

    def log_message(self, format: str, *args: Any) -> None:
        _log.debug("API %s", format % args)

    def send_error(self, code: int, message: str | None = None,
                   explain: str | None = None) -> None:
        try:
            phrase = http.HTTPStatus(code).phrase
        except ValueError:
            phrase = "Fehler"
        self._send(error_response(code, "http_error", phrase))

    def _send(self, response: ApiResponse) -> None:
        payload = json.dumps(response.body, ensure_ascii=False).encode("utf-8")
        self.close_connection = True
        try:
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(payload)
        except OSError:
            _log.debug("Client hat die Verbindung vor der Antwort geschlossen",
                       exc_info=True)

    def _serve(self) -> None:
        try:
            response = self._respond()
        except Exception:
            # Programmfehler: Details nur ins Log, nie in die Antwort.
            _log.exception("API-Anfrage fehlgeschlagen")
            response = error_response(500, "internal_error", "Interner Fehler.")
        self._send(response)

    def _read_body(self) -> bytes | ApiResponse:
        raw = self.headers.get("Content-Length")
        if raw is None:
            return b""
        if not (raw.isascii() and raw.isdigit()):
            return error_response(400, "invalid_content_length",
                                  "Content-Length ist keine Zahl.")
        if len(raw) > _MAX_CONTENT_LENGTH_DIGITS or int(raw) > MAX_BODY_BYTES:
            return error_response(413, "payload_too_large", "Body ist zu groß.")
        length = int(raw)
        if length == 0:
            return b""
        data = self.rfile.read(length)
        if len(data) != length:
            return error_response(400, "incomplete_body", "Body ist unvollständig.")
        return data

    def _respond(self) -> ApiResponse:
        server = cast("_ApiHTTPServer", self.server)
        for name in _SINGLE_VALUE_HEADERS:
            if len(self.headers.get_all(name) or []) > 1:
                return error_response(400, "duplicate_header",
                                      f"Header {name} darf nur einmal vorkommen.")
        headers = dict(self.headers.items())
        auth = authorize(self.command, headers, server.policy, server.verifier)
        if not auth.ok or auth.principal is None:
            return _auth_error(auth)
        if any(name.lower() == "transfer-encoding" for name in headers):
            return error_response(400, "unsupported_encoding",
                                  "Transfer-Encoding wird nicht unterstützt.")
        body = self._read_body()
        if isinstance(body, ApiResponse):
            return body
        path, _, raw_query = self.path.partition("?")
        try:
            query = parse_qs(raw_query, keep_blank_values=True,
                             max_num_fields=_MAX_QUERY_FIELDS)
        except ValueError:
            return error_response(400, "invalid_query", "Ungültige Query.")
        request = ApiRequest(self.command, path, query, body)
        return handle(request, server.context, auth.principal)


class _ApiHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    timeout = _POLL_INTERVAL_S
    # Unter Windows würde SO_REUSEADDR das gleichzeitige Binden desselben
    # Ports erlauben; dort schützt SO_EXCLUSIVEADDRUSE (server_bind).
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, address: tuple[str, int],
                 policy_for_port: Callable[[int], Policy],
                 verifier: TokenVerifier, context: ApiContext) -> None:
        self.verifier = verifier
        self.context = context
        self.policy: Policy
        super().__init__(address, _Handler)
        self.policy = policy_for_port(self.server_address[1])

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # Nicht `HTTPServer.server_bind`: das ruft `socket.getfqdn` auf, und das
        # kann bei kaputtem DNS lange hängen.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port

    def handle_error(self, request: Any, client_address: Any) -> None:
        # Standard wäre ein Traceback auf stderr — unter --noconsole spurlos.
        _log.exception("API-Verbindung fehlgeschlagen")


class ApiServer:
    def __init__(self, context: ApiContext, verifier: TokenVerifier, *, port: int = 0,
                 policy_for_port: Callable[[int], Policy] = Policy.loopback) -> None:
        self._context = context
        self._verifier = verifier
        self._requested_port = port
        self._policy_for_port = policy_for_port
        self._httpd: _ApiHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise RuntimeError("Server läuft nicht")
        return int(self._httpd.server_address[1])

    def start(self) -> None:
        """Bindet und startet den Server-Thread. Wirft `OSError`, wenn der
        Bind scheitert (Port belegt)."""
        if self._httpd is not None:
            raise RuntimeError("Server läuft bereits")
        bind_host = self._policy_for_port(self._requested_port).bind_host
        httpd = _ApiHTTPServer((bind_host, self._requested_port), self._policy_for_port,
                               self._verifier, self._context)
        self._httpd = httpd
        self._stop_event.clear()
        thread = threading.Thread(target=self._serve_loop, args=(httpd,),
                                  name="api-server", daemon=True)
        self._thread = thread
        thread.start()

    def _serve_loop(self, httpd: _ApiHTTPServer) -> None:
        while not self._stop_event.is_set():
            httpd.handle_request()

    def set_verifier(self, verifier: TokenVerifier) -> None:
        """Tauscht den Prüfer (Token-Rotation) ohne Neustart."""
        self._verifier = verifier
        if self._httpd is not None:
            self._httpd.verifier = verifier

    def stop(self, timeout: float = 2.0) -> None:
        """Beendet den Server und gibt den Port frei. Idempotent."""
        self._stop_event.set()
        thread, httpd = self._thread, self._httpd
        self._thread = None
        self._httpd = None
        if thread is not None:
            thread.join(timeout)
        if httpd is not None:
            httpd.server_close()
```

In `tests/test_type_annotations.py` die Liste `ANNOTATED_MODULES` um `"src/api_server.py",` ergänzen (hinter `"src/api_routes.py",`).

- [ ] **Step 4: Tests laufen lassen**

Run: `python3 -m pytest tests/test_api_server.py tests/test_api_routes.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:cacheprovider`
Expected: alle PASS. Falls ein Test hängt, ist die Ursache eine Schleife oder ein fehlendes `close_connection` — nicht den Test verlängern, sondern den Server korrigieren.

- [ ] **Step 5: Commit**

```bash
git add src/api_server.py tests/test_api_server.py tests/test_type_annotations.py
git commit -m "$(cat <<'EOF'
feat(api): HTTP-Server der lokalen API (#92)

ThreadingHTTPServer im Daemon-Thread, nur Loopback, authorize vor dem
Routing. Doppelte Header, Body-Limit, Socket-Timeout, JSON-Fehler statt
HTML, 405 mit Allow, 401 mit WWW-Authenticate, nie ein CORS-Header.
Unter Windows SO_EXCLUSIVEADDRUSE.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `api_service` und Settings-Schlüssel — Lebenszyklus

**Files:**
- Create: `src/api_service.py`
- Create: `tests/test_api_service.py`
- Modify: `src/settings.py` (`DEFAULTS`: `api_enabled`, `api_port`)
- Modify: `tests/test_settings.py` (Test für die beiden Schlüssel)
- Modify: `tests/test_type_annotations.py` (`"src/api_service.py"`)

**Interfaces:**
- Consumes: `api_auth.load_or_create_token(base_path) -> str | None`, `single_token_verifier`; `api_server.ApiServer`; `api_routes.ApiContext`; `BackgroundTaskRunner.run(fn, on_done=None)` (der Aufrufer reicht die Methode als `run` herein).
- Produces (Task 4 und PR 3 verlassen sich darauf):
  - Konstanten `DEFAULT_PORT = 17653`, `MIN_PORT = 1024`, `MAX_PORT = 65535`; Zustände `STATE_OFF = "off"`, `STATE_RUNNING = "running"`, `STATE_ERROR = "error"`; Gründe `REASON_INVALID_PORT = "invalid_port"`, `REASON_PORT_IN_USE = "port_in_use"`, `REASON_TOKEN_UNAVAILABLE = "token_unavailable"`, `REASON_START_FAILED = "start_failed"`
  - `parse_port(value: Any) -> int | None`
  - `ApiStatus(state: str, port: int | None = None, reason: str = "")` (frozen)
  - `ApiService(settings: SettingsLike, base_path: str, context: ApiContext, *, run: Callable[..., None], on_status: Callable[[ApiStatus], None] | None = None)`
  - `ApiService.apply() -> None` (UI-Thread; stößt `_reconcile` im Worker an, meldet das Ergebnis an `on_status`)
  - `ApiService.status -> ApiStatus`
  - `ApiService.shutdown(lock_timeout: float = 1.0) -> None` (blockiert nie länger als `lock_timeout`; danach ist `apply` ein No-op)
  - `ApiService.reopen() -> None` (macht `shutdown` rückgängig, z. B. nach fehlgeschlagenem Neustart)

- [ ] **Step 1: Failing tests schreiben**

An `tests/test_settings.py` anfügen:

```python
def test_api_defaults_present_and_device_local():
    from src.settings import DEFAULTS, SYNCED_SETTING_KEYS
    assert DEFAULTS["api_enabled"] is False
    assert DEFAULTS["api_port"] == 17653
    # Gerätelokal: ein zweiter Rechner mit anderem Port/Zustand darf nicht von
    # einem synchronisierten Wert überstimmt werden.
    assert "api_enabled" not in SYNCED_SETTING_KEYS
    assert "api_port" not in SYNCED_SETTING_KEYS
```

`tests/test_api_service.py`:

```python
# tests/test_api_service.py
import http.client
import socket
import threading
import time

import pytest

from src import api_service
from src.api_routes import ApiContext
from src.api_service import (
    DEFAULT_PORT, REASON_INVALID_PORT, REASON_PORT_IN_USE, REASON_TOKEN_UNAVAILABLE,
    STATE_ERROR, STATE_OFF, STATE_RUNNING, ApiService, ApiStatus, parse_port,
)
from src.settings import DEFAULTS
from src.storage import Storage


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def sync_run(fn, on_done=None):
    result = fn()
    if on_done is not None:
        on_done(result)


def make_service(tmp_path, settings, run=sync_run, statuses=None):
    storage = Storage(str(tmp_path / "zeiterfassung.json"), device_id="dev")
    context = ApiContext(storage=storage, settings=settings, app_version=lambda: "t")
    on_status = statuses.append if statuses is not None else None
    return ApiService(settings, str(tmp_path), context, run=run, on_status=on_status)


def token_of(tmp_path):
    return (tmp_path / "api-token").read_text(encoding="ascii")


def get_status_code(port, token):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", "/v1/status", headers={"Authorization": f"Bearer {token}"})
        response = conn.getresponse()
        response.read()
        return response.status
    finally:
        conn.close()


def port_is_closed(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return True
    return False


# --- parse_port -----------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (17653, 17653), ("17653", 17653), (" 8080 ", 8080), (1024, 1024), (65535, 65535),
    (1023, None), (0, None), (80, None), (65536, None), (70000, None), (-5, None),
    ("abc", None), ("", None), ("17653.5", None), (17653.0, None), (None, None),
    (True, None), ("٨٠٨٠", None), ("9" * 5000, None), ([8080], None),
])
def test_parse_port(value, expected):
    assert parse_port(value) == expected


def test_default_port_matches_the_settings_default():
    assert DEFAULT_PORT == DEFAULTS["api_port"]


# --- Aus, Ein, Aus --------------------------------------------------------------------

def test_disabled_by_default_starts_nothing_and_creates_no_token(tmp_path):
    service = make_service(tmp_path, {"api_enabled": False, "api_port": free_port()})

    service.apply()

    assert service.status == ApiStatus(STATE_OFF)
    assert not (tmp_path / "api-token").exists()


def test_enabling_starts_the_server_with_the_stored_token(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})

    service.apply()
    try:
        assert service.status == ApiStatus(STATE_RUNNING, port)
        assert get_status_code(port, token_of(tmp_path)) == 200
        assert get_status_code(port, "falsch") == 401
    finally:
        service.shutdown()


def test_disabling_stops_the_server_and_frees_the_port(tmp_path):
    port = free_port()
    settings = {"api_enabled": True, "api_port": port}
    service = make_service(tmp_path, settings)
    service.apply()

    settings["api_enabled"] = False
    service.apply()

    assert service.status == ApiStatus(STATE_OFF)
    assert port_is_closed(port)


def test_changing_the_port_rebinds(tmp_path):
    first, second = free_port(), free_port()
    settings = {"api_enabled": True, "api_port": first}
    service = make_service(tmp_path, settings)
    service.apply()
    try:
        settings["api_port"] = second
        service.apply()

        assert service.status == ApiStatus(STATE_RUNNING, second)
        assert port_is_closed(first)
        assert get_status_code(second, token_of(tmp_path)) == 200
    finally:
        service.shutdown()


def test_applying_the_same_settings_twice_keeps_the_running_server(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()
    try:
        server = service._server
        token = token_of(tmp_path)

        service.apply()

        assert service._server is server
        assert token_of(tmp_path) == token
    finally:
        service.shutdown()


# --- Review Focus 5: ungültige Settings ---------------------------------------------------

@pytest.mark.parametrize("bad", ["abc", 0, 80, 70000, None, True, "", "17653.5", -5])
def test_invalid_port_is_an_error_status_without_server_or_token(tmp_path, bad):
    service = make_service(tmp_path, {"api_enabled": True, "api_port": bad})

    service.apply()

    assert service.status == ApiStatus(STATE_ERROR, None, REASON_INVALID_PORT)
    assert service._server is None
    assert not (tmp_path / "api-token").exists()


def test_port_in_use_is_reported_and_recovers_when_freed(tmp_path):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    try:
        service.apply()
        assert service.status == ApiStatus(STATE_ERROR, port, REASON_PORT_IN_USE)

        blocker.close()
        service.apply()
        assert service.status == ApiStatus(STATE_RUNNING, port)
    finally:
        blocker.close()
        service.shutdown()


def test_unusable_token_location_is_an_error_status(tmp_path):
    missing = tmp_path / "gibt-es-nicht"
    storage = Storage(str(tmp_path / "z.json"), device_id="dev")
    settings = {"api_enabled": True, "api_port": free_port()}
    context = ApiContext(storage=storage, settings=settings, app_version=lambda: "t")
    service = ApiService(settings, str(missing), context, run=sync_run)

    service.apply()

    assert service.status == ApiStatus(STATE_ERROR, None, REASON_TOKEN_UNAVAILABLE)
    assert service._server is None


def test_status_changes_are_reported_to_the_callback(tmp_path):
    port = free_port()
    statuses = []
    settings = {"api_enabled": True, "api_port": port}
    service = make_service(tmp_path, settings, statuses=statuses)

    service.apply()
    settings["api_enabled"] = False
    service.apply()

    assert statuses == [ApiStatus(STATE_RUNNING, port), ApiStatus(STATE_OFF)]


# --- Review Focus 4: Beenden und Entfernen -----------------------------------------------------

def test_shutdown_stops_the_server_and_blocks_further_applies(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()

    service.shutdown()
    assert port_is_closed(port)

    service.apply()                              # darf nichts mehr starten
    assert port_is_closed(port)


def test_reopen_allows_starting_again(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()
    service.shutdown()

    service.reopen()
    service.apply()
    try:
        assert service.status == ApiStatus(STATE_RUNNING, port)
    finally:
        service.shutdown()


def test_shutdown_before_the_worker_runs_prevents_any_start(tmp_path):
    jobs = []
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port},
                           run=lambda fn, on_done=None: jobs.append(fn))
    service.apply()

    service.shutdown()
    jobs[0]()                                    # der Worker läuft erst jetzt

    assert port_is_closed(port)
    assert not (tmp_path / "api-token").exists()


def test_shutdown_during_the_token_load_neither_blocks_nor_starts(tmp_path, monkeypatch):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    real_loader = api_service.load_or_create_token
    elapsed = []

    def loader(base_path):
        token = real_loader(base_path)
        began = time.monotonic()
        service.shutdown(lock_timeout=0.05)      # Worker hält den Lock
        elapsed.append(time.monotonic() - began)
        return token

    monkeypatch.setattr(api_service, "load_or_create_token", loader)

    service.apply()

    assert elapsed and elapsed[0] < 1.0
    assert service.status.state != STATE_RUNNING
    assert port_is_closed(port)


def test_unexpected_errors_in_the_worker_become_an_error_status(tmp_path, monkeypatch, caplog):
    service = make_service(tmp_path, {"api_enabled": True, "api_port": free_port()})

    def boom(base_path):
        raise RuntimeError("unerwartet")

    monkeypatch.setattr(api_service, "load_or_create_token", boom)

    service.apply()

    assert service.status.state == STATE_ERROR
    assert "Lokale API" in caplog.text


def test_concurrent_applies_end_in_one_running_server(tmp_path):
    port = free_port()
    threads = []
    statuses = []

    def thread_run(fn, on_done=None):
        def body():
            result = fn()
            if on_done is not None:
                on_done(result)
        thread = threading.Thread(target=body)
        threads.append(thread)
        thread.start()

    service = make_service(tmp_path, {"api_enabled": True, "api_port": port},
                           run=thread_run, statuses=statuses)
    try:
        for _ in range(10):
            service.apply()
        for thread in threads:
            thread.join()

        assert service.status == ApiStatus(STATE_RUNNING, port)
        assert all(s == ApiStatus(STATE_RUNNING, port) for s in statuses)
        assert get_status_code(port, token_of(tmp_path)) == 200
    finally:
        service.shutdown()
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `python3 -m pytest tests/test_api_service.py tests/test_settings.py::test_api_defaults_present_and_device_local -q -p no:cacheprovider`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.api_service'` bzw. `KeyError: 'api_enabled'`).

- [ ] **Step 3: Minimal implementieren**

`src/settings.py` — in `DEFAULTS` direkt hinter `"auto_update_enabled": False,` einfügen (der Kommentar steht vor den Schlüsseln):

```python
    # Lokale HTTP-API (#92). Beide gerätelokal, NICHT in SYNCED_SETTING_KEYS:
    # ein Rechner mit belegtem Port oder ohne Bedarf darf nicht von einem
    # synchronisierten Wert eines anderen überstimmt werden.
    "api_enabled": False,
    "api_port": 17653,
```

`src/api_service.py`:

```python
# src/api_service.py
"""Lebenszyklus der lokalen HTTP-API (#92), Tk-frei.

`ApiService.apply()` liest `api_enabled`/`api_port` aus den Settings und bringt
den Server in den passenden Zustand — im Worker, nie im UI-Thread: das
Token-Laden blockiert (Windows: `icacls` bis 15 s). Das Ergebnis ist ein
`ApiStatus` samt Grund, den der Settings-Tab (PR 3) anzeigt.

Beenden, Entfernen und Skalierungs-Neustart rufen `shutdown()`; das wartet nie
länger als `lock_timeout` auf einen laufenden Start (nichts darf das Beenden
aufhalten) und sperrt danach jeden weiteren Start — wichtig beim Entfernen, wo
ein spät fertiges Token-Laden die Datei neu anlegen würde.
"""
from __future__ import annotations

import errno
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.api_auth import load_or_create_token, single_token_verifier
from src.api_routes import ApiContext
from src.api_server import ApiServer

if TYPE_CHECKING:  # nur für die Signaturen
    from src.settings import SettingsLike

_log = logging.getLogger(__name__)

DEFAULT_PORT = 17653
MIN_PORT = 1024
MAX_PORT = 65535

STATE_OFF = "off"
STATE_RUNNING = "running"
STATE_ERROR = "error"

REASON_INVALID_PORT = "invalid_port"
REASON_PORT_IN_USE = "port_in_use"
REASON_TOKEN_UNAVAILABLE = "token_unavailable"
REASON_START_FAILED = "start_failed"

_MAX_PORT_DIGITS = 5
# Windows meldet einen belegten Port mit WSAEADDRINUSE (10048), einen mit
# SO_EXCLUSIVEADDRUSE fremd gebundenen mit WSAEACCES (10013).
_WINERRORS_IN_USE = (10048, 10013)


@dataclass(frozen=True)
class ApiStatus:
    state: str
    port: int | None = None
    reason: str = ""


def parse_port(value: Any) -> int | None:
    """Gültiger Port (1024–65535) oder `None`. Bools, Floats, Text mit Nicht-
    ASCII-Ziffern und absurd lange Zahlen sind ungültig."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        port = value
    elif isinstance(value, str):
        text = value.strip()
        if not (text.isascii() and text.isdigit()) or len(text) > _MAX_PORT_DIGITS:
            return None
        port = int(text)
    else:
        return None
    return port if MIN_PORT <= port <= MAX_PORT else None


def _port_in_use(exc: OSError) -> bool:
    return (exc.errno in (errno.EADDRINUSE, errno.EACCES)
            or getattr(exc, "winerror", None) in _WINERRORS_IN_USE)


class ApiService:
    def __init__(self, settings: SettingsLike, base_path: str, context: ApiContext, *,
                 run: Callable[..., None],
                 on_status: Callable[[ApiStatus], None] | None = None) -> None:
        self._settings = settings
        self._base_path = base_path
        self._context = context
        self._run = run
        self._on_status = on_status
        self._lock = threading.Lock()
        self._server: ApiServer | None = None
        self._status = ApiStatus(STATE_OFF)
        self._closed = False

    @property
    def status(self) -> ApiStatus:
        return self._status

    def apply(self) -> None:
        """Bringt den Server in den Zustand der Settings. Im UI-Thread
        aufrufen; die Arbeit läuft im Worker, `on_status` kommt zurück."""
        if self._closed:
            return
        self._run(self._reconcile, self._publish)

    def _publish(self, status: ApiStatus) -> None:
        if self._on_status is not None:
            self._on_status(status)

    def _reconcile(self) -> ApiStatus:
        with self._lock:
            try:
                return self._reconcile_locked()
            except Exception:
                # Der Runner würde den Fehler nur loggen und `on_done` nie
                # rufen — der Status bliebe stehen. Hier wird er zum Zustand.
                _log.exception("Lokale API: Start/Stopp fehlgeschlagen")
                self._stop_server()
                self._status = ApiStatus(STATE_ERROR, None, REASON_START_FAILED)
                return self._status

    def _reconcile_locked(self) -> ApiStatus:
        if self._closed:
            return self._status
        if not self._settings.get("api_enabled"):
            self._stop_server()
            self._status = ApiStatus(STATE_OFF)
            return self._status
        port = parse_port(self._settings.get("api_port"))
        if port is None:
            self._stop_server()
            self._status = ApiStatus(STATE_ERROR, None, REASON_INVALID_PORT)
            return self._status
        if self._server is not None and self._server.port == port:
            return self._status                  # läuft schon, nichts zu tun
        self._stop_server()
        token = load_or_create_token(self._base_path)    # blockiert: nur im Worker
        if token is None:
            self._status = ApiStatus(STATE_ERROR, None, REASON_TOKEN_UNAVAILABLE)
            return self._status
        if self._closed:                         # Beenden/Entfernen kam dazwischen
            return self._status
        server = ApiServer(self._context, single_token_verifier(token), port=port)
        try:
            server.start()
        except OSError as exc:
            reason = REASON_PORT_IN_USE if _port_in_use(exc) else REASON_START_FAILED
            _log.warning("Lokale API: Start auf Port %s scheitert (%s)", port, reason,
                         exc_info=True)
            self._status = ApiStatus(STATE_ERROR, port, reason)
            return self._status
        self._server = server
        self._status = ApiStatus(STATE_RUNNING, server.port)
        return self._status

    def _stop_server(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.stop()

    def shutdown(self, lock_timeout: float = 1.0) -> None:
        """Stoppt den Server und sperrt weitere Starts. Blockiert höchstens
        `lock_timeout`: läuft gerade ein Start (der Worker hält den Lock),
        wird nicht gewartet — der Start prüft `_closed` und bricht selbst ab,
        und ein Daemon-Thread stirbt mit dem Prozess."""
        self._closed = True
        if not self._lock.acquire(timeout=lock_timeout):
            _log.warning("Lokale API: Beenden wartet nicht auf einen laufenden Start")
            return
        try:
            self._stop_server()
            self._status = ApiStatus(STATE_OFF)
        finally:
            self._lock.release()

    def reopen(self) -> None:
        """Macht `shutdown` rückgängig (Skalierungs-Neustart ist gescheitert,
        die App läuft weiter). Der nächste `apply()` startet wieder."""
        self._closed = False
```

In `tests/test_type_annotations.py` die Liste `ANNOTATED_MODULES` um `"src/api_service.py",` ergänzen (hinter `"src/api_server.py",`).

- [ ] **Step 4: Tests laufen lassen**

Run: `python3 -m pytest tests/test_api_service.py tests/test_settings.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:cacheprovider`
Expected: alle PASS.

- [ ] **Step 5: Commit**

```bash
git add src/api_service.py src/settings.py tests/test_api_service.py tests/test_settings.py tests/test_type_annotations.py
git commit -m "$(cat <<'EOF'
feat(api): Lebenszyklus der lokalen API und Settings-Schlüssel (#92)

api_enabled/api_port (gerätelokal, Default aus), Start und Stopp im Worker,
Status mit Grund für den späteren Settings-Tab. shutdown() wartet nie auf
einen laufenden Start und sperrt weitere Starts.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `App`-Verdrahtung und Stopp-Stellen

**Files:**
- Modify: `src/ui.py` (Importe, `__init__`, `_apply_api_setting`, `_open_settings._on_change`, `_quit_with_sync_push`, `remove_application`, `restart_for_scaling`)
- Create: `tests/test_api_wiring.py`

**Interfaces:**
- Consumes: `ApiService(settings, base_path, context, *, run)`, `.apply()`, `.shutdown()`, `.reopen()` (Task 3); `ApiContext` (Task 1); `installed_release_id() -> str` aus `src.version`.
- Produces: `App._api` (der `ApiService`), `App._apply_api_setting()`; PR 3 hängt den Settings-Tab daran.

Tk-Code wird hier nicht ausgeführt getestet (entschiedene Scope-Grenze); der Test prüft die Verdrahtung am Quelltext (AST), Muster `tests/test_dialog_reveal.py`.

- [ ] **Step 1: Failing test schreiben**

`tests/test_api_wiring.py`:

```python
# tests/test_api_wiring.py
"""Die API muss an allen Stellen stehen, an denen die App Ressourcen freigibt
oder neu startet. Tk-Code läuft hier nicht (entschiedene Scope-Grenze), deshalb
prüft der Test die Verdrahtung am Quelltext."""
import ast
import pathlib

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "ui.py"
TREE = ast.parse(UI.read_text(encoding="utf-8"))


def _function(name):
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} fehlt in src/ui.py")


def _self_calls(func, owner, method):
    """Aufrufe `self.<owner>.<method>(...)` innerhalb von `func`."""
    found = []
    for node in ast.walk(func):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        target = node.func
        if (target.attr == method and isinstance(target.value, ast.Attribute)
                and target.value.attr == owner
                and isinstance(target.value.value, ast.Name)
                and target.value.value.id == "self"):
            found.append(node)
    return found


def _self_method_calls(func, method):
    return [n for n in ast.walk(func)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == method and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "self"]


def test_the_api_service_is_built_in_init():
    init = _function("__init__")
    assigned = [t for node in ast.walk(init) if isinstance(node, ast.Assign)
                for t in node.targets if isinstance(t, ast.Attribute) and t.attr == "_api"]
    assert assigned, "App.__init__ muss self._api anlegen"


def test_the_setting_is_applied_at_start_and_after_every_settings_save():
    assert _self_method_calls(_function("__init__"), "_apply_api_setting")
    assert _self_method_calls(_function("_open_settings"), "_apply_api_setting")


def test_apply_api_setting_delegates_to_the_service():
    assert _self_calls(_function("_apply_api_setting"), "_api", "apply")


def test_every_exit_path_shuts_the_api_down():
    for name in ("_quit_with_sync_push", "remove_application", "restart_for_scaling"):
        assert _self_calls(_function(name), "_api", "shutdown"), (
            f"{name} muss self._api.shutdown() rufen")


def test_the_restart_frees_the_port_before_spawning_and_recovers_on_failure():
    restart = _function("restart_for_scaling")
    shutdown = _self_calls(restart, "_api", "shutdown")[0]
    spawn = [n for n in ast.walk(restart)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "Popen"][0]
    # Port VOR dem Spawn freigeben, sonst findet die neue Instanz ihn belegt.
    assert shutdown.lineno < spawn.lineno
    # Scheitert Popen, läuft die App weiter — die API muss zurückkommen.
    assert _self_calls(restart, "_api", "reopen")
    assert _self_calls(restart, "_api", "apply")


def test_removal_stops_the_api_before_any_background_job_is_queued():
    removal = _function("remove_application")
    shutdown = _self_calls(removal, "_api", "shutdown")[0]
    queued = _self_calls(removal, "_bg", "run")[0]
    assert shutdown.lineno < queued.lineno
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `python3 -m pytest tests/test_api_wiring.py -q -p no:cacheprovider`
Expected: FAIL (u. a. `App.__init__ muss self._api anlegen`, `_apply_api_setting fehlt`).

- [ ] **Step 3: Verdrahten**

Alle Änderungen an `src/ui.py`, jeweils mit eindeutigem Anker (jede Ersetzung muss genau einmal treffen):

1. **Importe.** `from src.version import VERSION, version_label` → `from src.version import VERSION, installed_release_id, version_label`, und direkt hinter `from src.background_tasks import BackgroundTaskRunner` einfügen:
   ```python
   from src.api_routes import ApiContext
   from src.api_service import ApiService
   ```

2. **`__init__`, Service anlegen** — direkt vor `        self._renderer = GridRenderer(` einfügen:
   ```python
        # Lokale HTTP-API (#92): Lebenszyklus samt Token-Laden im Worker. Der
        # Dienst startet nur bei `api_enabled`; die Routen lesen über die
        # Store-Methoden und halten keinen Lock.
        self._api = ApiService(
            self.settings, self.base_path,
            ApiContext(storage=self.storage, settings=self.settings,
                       app_version=installed_release_id),
            run=self._bg.run)
   ```

3. **`__init__`, Einstellung anwenden** — Anker (eindeutig durch die folgende Zeile):
   ```python
        self._apply_send_reminder_setting()
        self.root.bind("<Left>", lambda e: self._navigate(-1))
   ```
   wird zu
   ```python
        self._apply_send_reminder_setting()
        self._apply_api_setting()
        self.root.bind("<Left>", lambda e: self._navigate(-1))
   ```

4. **`_open_settings._on_change`** — Anker:
   ```python
            self._apply_send_reminder_setting()
            # Nach jeder Settings-Speicherung den sender_email-Fetch nochmal
   ```
   wird zu
   ```python
            self._apply_send_reminder_setting()
            self._apply_api_setting()
            # Nach jeder Settings-Speicherung den sender_email-Fetch nochmal
   ```

5. **Neue Methode** — direkt vor `    def _apply_send_reminder_setting(self):` einfügen:
   ```python
    def _apply_api_setting(self):
        """Bringt die lokale API in den Zustand der Settings (#92). Die Arbeit
        läuft im Worker (Token-Laden blockiert); hier wird nur angestoßen."""
        self._api.apply()

   ```

6. **`_quit_with_sync_push`** — Anker:
   ```python
        self._reminders.stop()
        self._send_reminders.stop()
        self._sync.stop_day_watch()
        if self._single_instance is not None:
            self._single_instance.release()
        # Ein vorbereitetes Update erst hier anwenden
   ```
   wird zu
   ```python
        self._api.shutdown()
        self._reminders.stop()
        self._send_reminders.stop()
        self._sync.stop_day_watch()
        if self._single_instance is not None:
            self._single_instance.release()
        # Ein vorbereitetes Update erst hier anwenden
   ```

7. **`remove_application`** — Anker:
   ```python
        if self._tray is not None:
            self._tray.stop()
        self._reminders.stop()
        self._send_reminders.stop()
        self._sync.stop_day_watch()

        base = self.base_path
   ```
   wird zu
   ```python
        # Vor allem anderen: ein spät fertiges Token-Laden würde `api-token`
        # nach dem Aufräumen neu anlegen. `shutdown` sperrt weitere Starts;
        # ein laufender Worker wird unten von `wait_idle` abgewartet.
        self._api.shutdown()
        if self._tray is not None:
            self._tray.stop()
        self._reminders.stop()
        self._send_reminders.stop()
        self._sync.stop_day_watch()

        base = self.base_path
   ```

8. **`restart_for_scaling`, Port freigeben** — Anker:
   ```python
        if self._single_instance is not None:
            self._single_instance.release()
        # Port VOR dem Spawn freigeben, sonst fände die neue Instanz ihn noch
   ```
   wird zu
   ```python
        # Auch der API-Port muss VOR dem Spawn frei sein, sonst findet die neue
        # Instanz ihn belegt und die API bleibt dort aus.
        self._api.shutdown()
        if self._single_instance is not None:
            self._single_instance.release()
        # Port VOR dem Spawn freigeben, sonst fände die neue Instanz ihn noch
   ```

9. **`restart_for_scaling`, Fehlerpfad** — Anker:
   ```python
            themed_showinfo(
                self.root,
                "Neustart nötig",
   ```
   wird zu
   ```python
            # Popen ist gescheitert, die App läuft weiter: die API zurückholen.
            self._api.reopen()
            self._api.apply()
            themed_showinfo(
                self.root,
                "Neustart nötig",
   ```

- [ ] **Step 4: Tests laufen lassen**

Run: `python3 -m pytest tests/test_api_wiring.py tests/test_ui_delete.py tests/test_dialog_reveal.py -q -p no:cacheprovider` und danach die ganze Suite `python3 -m pytest -q`.
Expected: alle PASS (`test_ui_delete` importiert `src.ui` — fängt Tippfehler in den Importen).

- [ ] **Step 5: Commit**

```bash
git add src/ui.py tests/test_api_wiring.py
git commit -m "$(cat <<'EOF'
feat(api): lokale API in die App verdrahten (#92)

Start bei App-Start und nach jedem Speichern der Einstellungen; Stopp beim
Beenden, beim Entfernen (vor jedem Worker) und beim Skalierungs-Neustart
(Port vor dem Spawn frei, bei Fehlschlag zurück). Verdrahtung per
AST-Test abgesichert.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Doku, Spec-Stack und Gesamtprüfung

**Files:**
- Modify: `docs/superpowers/specs/2026-10-06-lokale-api-design.md` (Stack-Abschnitt umnummerieren)
- Modify: `src/CLAUDE.md` (Modulbeschreibungen, Threading)
- Modify: `CLAUDE.md` (Strukturliste)
- Modify: `docs/known-limitations.md` (neuer Abschnitt)
- Modify: `README.md` (`api-token` in der Datenliste, mit Platzhalter)

- [ ] **Step 1: Spec-Stack anpassen**

In `docs/superpowers/specs/2026-10-06-lokale-api-design.md` den Abschnitt „## Stack innerhalb von #92" ersetzen durch:

```markdown
## Stack innerhalb von #92

1. `api_auth` samt Tokendatei, Policy und Principal (rein, getestet).
2. Server (`api_server`), Routing (`api_routes`) mit `/status` und den lesenden
   Ist-Zeit-Routen, Lebenszyklus (`api_service`), Settings-Schlüssel,
   Verdrahtung in `App`.
3. Settings-Tab (Schalter, Port, Token anzeigen/kopieren/neu erzeugen,
   Statusgrund).
4. Schreibende Ist-Zeit-Endpunkte samt den Regeln aus „Regeln, die die API
   nachbilden muss".
5. Reservierungen und Auswertungen (Summen, Wochenlimit, Pausenpflicht,
   Kategorien, Feiertage).
```

- [ ] **Step 2: `src/CLAUDE.md`**

Im `api_auth.py`-Bullet den letzten Satz „Der Server selbst (Routen, Thread, Settings-Tab) folgt in den nächsten PRs." ersetzen durch „Server, Routen und Lebenszyklus: `api_server.py`, `api_routes.py`, `api_service.py` (unten)." und direkt hinter dem `api_auth.py`-Bullet (inklusive seines Absatzes zu `load_or_create_token`/`rotate_token`) drei Bullets einfügen:

```
- `api_routes.py` — Routing und Antworten der lokalen API (#92), Tk-frei und
  ohne Socket: `handle(request, ctx, principal)` über eine Routentabelle
  (Methode, Muster, Handler, **Scope**). Lesend: `GET /v1/status`,
  `/v1/entries`, `/v1/entries/{date}`. Die Daten kommen über `Storage.get_all()`/
  `get()` (nehmen den `data_lock` selbst, liefern Kopien) — die Routen halten
  keinen Lock und ändern nichts. Strikte Datumsform (`[0-9]{4}-[0-9]{2}-[0-9]{2}`,
  nicht `\d`, nicht `fromisoformat` allein: das nähme `20260105` und `2026-W01-1`),
  unbekannte und doppelte Query-Parameter sind 400. Ein Programmfehler wirft
  durch; der Server macht daraus eine 500 ohne Details.
- `api_server.py` — HTTP-Server der lokalen API: `ApiServer(context, verifier,
  port=…)`. Ein Daemon-Thread mit eigener `handle_request()`-Schleife (kein
  `serve_forever()`/`shutdown()`: das blockiert für immer, wenn es vor dem Eintritt
  in die Schleife gerufen wird), pro Verbindung ein Daemon-Thread. Reihenfolge je
  Anfrage: doppelte Header → 400, `api_auth.authorize`, `Transfer-Encoding` → 400,
  Body lesen (Limit 1 MiB), `api_routes.handle`. Nur Loopback (Bind-Adresse aus
  `Policy.bind_host`); `server_bind` umgeht `socket.getfqdn` (hängt bei kaputtem
  DNS) und setzt unter Windows `SO_EXCLUSIVEADDRUSE` statt `SO_REUSEADDR` — sonst
  könnte ein anderer lokaler Prozess den Port zusätzlich binden und Token
  mitlesen. `send_error` ist überschrieben: JSON statt HTML-Seite. Nie ein
  CORS-Header. `set_verifier` tauscht den Prüfer ohne Neustart (Token-Rotation).
- `api_service.py` — Lebenszyklus der lokalen API: `ApiService(settings, base_path,
  context, run=…)`. `apply()` liest `api_enabled`/`api_port` (beide gerätelokal) und
  bringt den Server im **Worker** in den passenden Zustand (Token laden blockiert);
  Ergebnis ist ein `ApiStatus(state, port, reason)` mit Grund
  (`invalid_port`/`port_in_use`/`token_unavailable`/`start_failed`) für den
  Settings-Tab. Bei ungültigem Port wird **kein** Token angelegt. `shutdown()` wartet
  höchstens `lock_timeout` auf einen laufenden Start und sperrt weitere Starts —
  Beenden darf nie hängen, und beim Entfernen würde ein spät fertiges Token-Laden die
  Datei neu anlegen. `reopen()` nimmt das zurück (fehlgeschlagener Skalierungs-Neustart).
  `App` ruft `shutdown()` in `_quit_with_sync_push`, `remove_application` (vor jedem
  Worker) und `restart_for_scaling` (**vor** dem Spawn, der Port muss frei sein);
  `tests/test_api_wiring.py` hält das am Quelltext fest.
```

Im Abschnitt „Threading-Modell" einen Absatz anfügen (hinter dem Absatz zum `data_lock`):

```
**Der API-Server ist ein zweiter erlaubter Thread-Ort** (`api_server.py`), wie der
Accept-Loop in `single_instance`: ein eigener Daemon-Thread, der nie ein Widget
berührt. Seine Routen holen Daten ausschließlich über die Store-Methoden (die den
`data_lock` selbst nehmen). Schreibende Routen (spätere PRs) führen Prüfen →
Konfliktcheck → Speichern unter demselben `data_lock` aus und rufen die UI nur über
`App._marshal_to_ui`.
```

- [ ] **Step 3: `CLAUDE.md` (Wurzel)**

Den Eintrag zu `src/api_auth.py` in der Strukturliste: den Schluss „Tk-frei; der Server folgt in den nächsten PRs des Stacks" ersetzen durch „Tk-frei." und dahinter einfügen:

```
- `src/api_routes.py`, `src/api_server.py`, `src/api_service.py` — lokale HTTP-API
  (#92), Tk-frei: Routing mit Scope pro Route (`GET /v1/status`, `/v1/entries`),
  Server im Daemon-Thread (nur Loopback, `authorize` vor dem Routing, nie ein
  CORS-Header) und Lebenszyklus über `api_enabled`/`api_port` (gerätelokal,
  Default aus) mit Statusgrund. Beschreibung und Verträge: `src/CLAUDE.md`.
```

- [ ] **Step 4: `docs/known-limitations.md`**

Am Dateiende anfügen:

```markdown
## Lokale API (#92): bekannte Grenzen

- **Das Token liegt in einer Datei.** `api-token` (wie `instance-secret`) ist für
  jeden Prozess lesbar, der **als derselbe Nutzer** läuft. Auf einem Desktop-
  Betriebssystem nicht zu ändern — direkt daneben liegt `token.json`, das mehr
  wert ist. Bewusst kein Schlüsselbund: Skripte müssen das Token lesen können.
  Die API verschiebt diese Grenze nicht.
- **Kein TLS.** Auf Loopback bedeutungslos. Mit der LAN-Freigabe (#221) wird das
  eine Entscheidung.
- **Nur solange die App läuft.** Der Server lebt im App-Prozess (Single-Writer,
  siehe #92); ohne laufende App ist die API nicht erreichbar. Wer sie praktisch
  braucht, schaltet Autostart ein.
- **Port belegt oder gesperrt.** Ein belegter Port lässt die API aus; der Grund
  steht im Status (`port_in_use`), die App läuft normal weiter. Unter Windows bindet
  die App den Port exklusiv (`SO_EXCLUSIVEADDRUSE`); ein anderer Prozess, der ihn
  vorher belegt, ist von dort aus nicht zu verdrängen.
- **Gerätelokal.** `api_enabled` und `api_port` reisen nicht per Drive-Sync.
- **Kein Brute-Force-Schutz.** 256 Bit sind nicht zu erraten, und gegen lokale
  Codeausführung wäre eine Sperre wirkungslos.
```

- [ ] **Step 5: `README.md`**

Zwei Stellen. Den Satz „Das meiste sind JSON-Dateien — `instance-secret` und das Protokoll sind es nicht." ersetzen durch „Das meiste sind JSON-Dateien — `instance-secret`, `api-token` und das Protokoll sind es nicht." und unter den **Zugangsdaten** hinter dem `instance-secret`-Bullet einfügen:

```markdown
- **api-token** *(ab --VERSION--)* — Zugriffstoken der lokalen HTTP-API; nur vorhanden, wenn die API einmal eingeschaltet war. Gerätelokal: reist bewusst **nicht** über den Drive-Sync mit
```

(Der Platzhalter `--VERSION--` bleibt stehen; `scripts/resolve_readme_version.py` löst ihn im Release-PR auf.)

- [ ] **Step 6: Gesamtprüfung**

Run:
```bash
python3 -m pytest -q
ruff check .
```
Expected: alle Tests grün, `ruff` sauber. Dazu die Abdeckung der drei neuen Module in einem Wegwerf-venv messen (`pytest-cov` ist lokal nicht installiert):

```bash
V=/tmp/claude-1000/-home-sven-projects-Zeiterfassung/560a12d5-c553-4c73-8987-d78214ab3424/scratchpad/covenv
$V/bin/python -m pytest tests/test_api_routes.py tests/test_api_server.py tests/test_api_service.py \
  --cov=src.api_routes --cov=src.api_server --cov=src.api_service --cov-branch \
  --cov-report=term-missing -q -p no:cacheprovider
rm -f .coverage
```
Expected: jedes der drei Module ≥ 95 % (`FLOOR` der Tk-freien Module ist 91). Fehlende Zweige, die ein echtes Verhalten betreffen, bekommen einen Test; unerreichbare (Windows-`sys.platform`-Zweig in `server_bind`) bleiben offen und werden im Ledger vermerkt. Falls das venv nicht mehr existiert: `python3 -m venv $V && $V/bin/pip install -q pytest==9.0.3 pytest-cov`.

Hinweis: Fällt `test_stop_releases_the_port_and_a_new_start_succeeds` in der CI unter **Windows** durch, ist das ein Befund (Neubinden desselben Ports unter `SO_EXCLUSIVEADDRUSE` nach `TIME_WAIT`), kein Anlass, den Test zu überspringen: dann wäre auch das Aus- und Wiedereinschalten in der App betroffen.

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/specs/2026-10-06-lokale-api-design.md src/CLAUDE.md CLAUDE.md docs/known-limitations.md README.md
git commit -m "$(cat <<'EOF'
docs(api): Server, Routen und Dienst dokumentiert (#92)

Modulbeschreibungen, Threading-Absatz, bekannte Grenzen und api-token in der
README-Datenliste. Spec-Stack umnummeriert: Settings-Tab ist jetzt PR 3.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: PR vorbereiten (nicht ohne Freigabe pushen)**

PR 2 gegen `feat/api-auth`, Titel `feat(api): Server und lesende Routen der lokalen API (#92)`, Beschreibung mit `Refs #92`, Verweis auf #233 (welche Checklistenpunkte erledigt sind: doppelte Header, `Allow`/`WWW-Authenticate`, Worker-Aufruf, Verifier-Tausch per `set_verifier`, Statusgrund, `known-limitations.md`/README, Body-Limit/Timeouts/`Cache-Control`/`nosniff`; offen bleiben: Settings-Tab und Token-Rotation → PR 3). Kein `release:*`-Label. Danach in den Stack hängen: `echo '{"pull_requests":[<PR2>]}' | gh api -X POST repos/Xveyn/Zeiterfassung/stacks/236/add --input -`. Push und PR erst nach Rückfrage.

---

## Self-Review

**Spec-Abdeckung:** Server (Daemon-Thread, nur Loopback, `authorize` vor Routing, nie CORS, Header, 405/401-Header, Body-Limit, Timeouts): Task 2. Routing mit Scope, `/status`, lesende Ist-Zeit-Routen, Minuten-Regel (keine Summen in diesem PR): Task 1. `api_enabled`/`api_port` gerätelokal, Start im Worker, Statusgrund, Bindfehler beendet die App nie: Task 3. Verdrahtung (`_apply_api_setting`, Beenden/Entfernen/Neustart): Task 4. Doku, `known-limitations.md`, README (Checkliste #233): Task 5. **Bewusst nicht in PR 2:** Settings-Tab und Token-Rotation (PR 3), schreibende Routen (PR 4), Reservierungen und Auswertungen (PR 5), CORS/LAN (#221).

**Platzhalter:** keine.

**Typkonsistenz:** `ApiContext(storage, settings, app_version, now)` (Task 1) wird in Task 2, 3 und 4 mit denselben Feldnamen gebaut; `ApiServer(context, verifier, *, port, policy_for_port)`, `.start()`, `.port`, `.set_verifier()`, `.stop()` (Task 2) stimmen mit den Aufrufen in `ApiService` (Task 3) überein; `ApiService.apply/shutdown/reopen/status` (Task 3) stimmen mit den AST-Prüfungen in Task 4 überein (`self._api.apply|shutdown|reopen`); `error_response`, `ApiResponse`, `ApiRequest` (Task 1) sind die Typen, die `api_server` importiert.
