# src/mobile_routes.py
"""Routen der Handy-Instanz (#221), Tk-frei und ohne Socket.

Die zweite `ApiServer`-Instanz (LAN, Gerätetoken) liefert nur diese drei Routen:
`POST /v1/pair` (öffentlich, solange ein Code aktiv ist), `GET /v1/ping` und
`POST /v1/sync`. Auth, Host- und Origin-Tore und CORS macht der Server (`api_server`,
`api_auth`); hier liegen Prüfer, Routing und Handler. Alle Pfade sind exakte
Zeichenketten, keine kennt Query-Parameter.

**Verschlüsselt (#249):** `/v1/pair` und `/v1/sync` tragen ihre Nutzdaten als Umschlag
(`mobile_crypto`); Klartext ist `400 invalid_protocol`. Was **vor** dem Entschlüsseln
entschieden wird (Tore, Token, Umschlagform, Code, Zähler), antwortet im Klartext und
verrät nur den Grund; Fehler **nach** erfolgreichem Entschlüsseln gehen als Umschlag
zurück (sie nennen den Tag). Der Gerätezähler `seq` ist der Replay-Schutz und wird bei
jedem entschlüsselten Paket gespeichert, auch bei einem Folgefehler. Den Schlüssel liefert
`ctx.keys.get` — nur aus dem Speicher, nie aus dem Schlüsselbund (`503 key_unavailable`,
solange er nicht geladen ist).

Der Prüfer (`make_verifier`) läuft **vor** dem Handler und liest nur. Jede Folge
„Datensatz lesen → ändern → speichern" (Koppeln, Abgleich samt Tokenerneuerung)
läuft im Handler unter `ctx.devices_lock`, und der Abgleich liest den Datensatz
dort neu: zwischen Prüfer und Handler kann ein Widerruf liegen.
Sperrreihenfolge: `devices_lock` → `sync_guard` → `data_lock`.
"""
from __future__ import annotations

import datetime
import json
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src import mobile_crypto as mc
from src import mobile_pairing, mobile_sync
from src.api_auth import SCOPE_MOBILE, Denied, Principal, TokenVerifier, require_scope
from src.api_entry_write import WriteError, load_json_body
from src.api_routes import ApiRequest, ApiResponse, error_response
from src.api_server import Surface
from src.api_summary import category_names
from src.mobile_sync import WINDOW_DAYS, SyncError
from src.time_utils import utc_now_iso

if TYPE_CHECKING:
    from src.mobile_keys import MobileKeyStore
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
    keys: MobileKeyStore
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
    # Nach einer erfolgreichen Kopplung, außerhalb der Sperren: der Dienst zieht den Schlüssel
    # damit im Worker in den Schlüsselbund um (`MobileKeyStore.migrate`).
    on_paired: Callable[[], None] = _no_change


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
    return ApiResponse(200, {"protocol": mc.PROTOCOL, "server_time": ctx.now(),
                             "window_days": WINDOW_DAYS})


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


def _envelope(body: bytes) -> dict[str, Any]:
    """Der Body als Umschlag. Klartext (oder ein Umschlag der falschen Version) ist
    `invalid_protocol`: die PWA zeigt dann „Versionen passen nicht zusammen“."""
    data = _json_object(body)
    if "c" not in data or data.get("v") != mc.PROTOCOL:
        raise _MobileError(400, "invalid_protocol",
                           f"Unterstützt wird protocol {mc.PROTOCOL} (verschlüsselt).")
    if not mc.is_envelope(data):
        raise _MobileError(400, "invalid_envelope", "Ungültiger Umschlag.")
    return data


def _sealed(key: bytes, *, path: str, device_id: str, seq: int, payload: Mapping[str, Any],
            status: int = 200) -> ApiResponse:
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return ApiResponse(status, mc.seal(key, direction="res", method="POST", path=path,
                                       device_id=device_id, seq=seq, plaintext=plaintext))


def _pair(request: ApiRequest, ctx: MobileContext, principal: Principal) -> ApiResponse:
    """Koppelt ein Handy. Der Body ist ein Umschlag, mit dem aus dem Kopplungscode
    abgeleiteten Schlüssel verschlüsselt; der Code selbst steht nie im Netz. Was sich damit
    nicht öffnen lässt — falscher, abgelaufener, verbrauchter Code, „kein Code aktiv“, auch
    ein ungültiger Inhalt —, ist dieselbe `403 invalid_code`; es gibt keine Sperre (der Code hat ≈139 Bit, eine Sperre wäre nur ein DoS-Hebel für Fremde im WLAN).
    Die Antwort trägt Token und den frischen Geräteschlüssel, verschlüsselt."""
    _no_query(request)
    envelope = _envelope(request.body)
    _refuse_while_closing(ctx)

    def attempt(code: str) -> dict[str, str] | None:
        request_key, _ = mc.pair_keys(code)
        try:
            plain = mc.open_envelope(request_key, envelope, direction="req", method="POST",
                                     path="/v1/pair", device_id="-", seq=1)
            data = load_json_body(plain)
        except (mc.CryptoError, WriteError):
            return None
        if not isinstance(data, dict):
            return None
        protocol = data.get("protocol")
        if not isinstance(protocol, int) or isinstance(protocol, bool) or protocol != mc.PROTOCOL:
            return None
        device_id = mobile_pairing.normalize_device_id(data.get("device_id"))
        if device_id is None:
            return None
        return {"code": code, "device_id": device_id,
                "name": mobile_pairing.clean_device_name(data.get("device_name"))}

    result, opened = ctx.pairing.try_open(attempt)
    if result is not mobile_pairing.RedeemResult.OK or opened is None:
        # Falsch, abgelaufen, verbraucht und „kein Code aktiv“ sind dieselbe Antwort.
        raise _MobileError(403, "invalid_code", "Der Code ist ungültig oder abgelaufen.")
    key = mc.new_device_key()
    with ctx.devices_lock:
        # Cache und gehärtete Datei, schnell; der Umzug in den Schlüsselbund folgt im Worker.
        ctx.keys.put(opened["device_id"], key)
        record, token = mobile_pairing.issue_device(
            opened["device_id"], opened["name"], ctx.now(), ctx.devices.get(opened["device_id"]))
        ctx.devices.save(record)
    _log.info("Handy gekoppelt: %s (%s)", record["id"], record["name"])
    _notify_paired(ctx)
    _, response_key = mc.pair_keys(opened["code"])
    return _sealed(response_key, path="/v1/pair", device_id=opened["device_id"], seq=1, payload={
        "token": token, "expires_at": record["expires_at"], "window_days": WINDOW_DAYS,
        "desktop_name": ctx.desktop_name(), "protocol": mc.PROTOCOL, "key": mc.b64e(key)})


def _notify_paired(ctx: MobileContext) -> None:
    try:
        ctx.on_paired()
    except Exception:
        # Die Kopplung ist gespeichert; der Umzug des Schlüssels in den Schlüsselbund holt
        # der nächste Start nach. Ein Fehler hier darf sie nicht zur 500 machen.
        _log.exception("Handy-Kopplung: on_paired fehlgeschlagen")


def _notify(ctx: MobileContext) -> None:
    try:
        ctx.on_change()
    except Exception:
        # Der Abgleich ist angewendet und gespeichert; ein Fehler beim Neuzeichnen
        # darf daraus keine 500 machen (das Handy wiederholte den Abgleich).
        _log.exception("Handy-Abgleich: on_change fehlgeschlagen")


def _still_valid(principal: MobilePrincipal, record: Mapping[str, Any], now: str) -> bool:
    """Das Token, mit dem diese Anfrage kam, gegen den **frisch gelesenen** Datensatz.
    Der Prüfer lief vor dem Handler und ohne Lock: dazwischen kann eine Erneuerung, ein
    erneutes Koppeln oder der Ablauf liegen. Liefert, ob das Token jetzt das *vorherige*
    ist (dann bleibt es beim Erneuern erhalten); wirft, wenn es weder aktuell noch
    vorherig ist oder abgelaufen. Der Hash stammt aus dem Datensatz, den der Prüfer
    seinerzeit zugeordnet hat — das Token selbst kennt der Handler nicht."""
    presented = (principal.record["previous_token_hash"] if principal.via_previous
                 else principal.record["token_hash"])
    if str(record["expires_at"]) <= now:
        raise _MobileError(401, "token_expired",
                           "Das Token ist abgelaufen. Das Gerät muss neu gekoppelt werden.")
    if presented == record["token_hash"]:
        return False
    if (presented and presented == record["previous_token_hash"]
            and str(record["previous_valid_until"]) >= now):
        return True
    raise _MobileError(401, "unauthorized", "Das Token ist nicht mehr gültig.")


def _sync(request: ApiRequest, ctx: MobileContext, principal: Principal) -> ApiResponse:
    """Der Abgleich. Unter `devices_lock`: den Datensatz neu lesen (ein Widerruf kann
    zwischen Prüfer und Handler liegen), den Geräteschlüssel holen, Zähler prüfen, den
    Umschlag öffnen, `perform_sync`, danach Token erneuern und `last_pull_at` speichern.
    Erneuert wird nur nach einem erfolgreichen Abgleich; scheitert er, bleiben Token und
    `last_pull_at` unverändert — der Zähler dagegen wird nach jedem **entschlüsselten**
    Paket gespeichert (ein mitgeschnittenes Paket lässt sich nicht noch einmal einspielen)."""
    _no_query(request)
    if not isinstance(principal, MobilePrincipal):
        raise _MobileError(403, "insufficient_scope", "Dem Token fehlt die Berechtigung.")
    _refuse_while_closing(ctx)
    envelope = _envelope(request.body)
    now = ctx.now()
    notify = False
    with ctx.devices_lock:
        record = ctx.devices.get(principal.name)
        if record is None or record.get("revoked"):
            raise _MobileError(401, "token_revoked",
                               "Das Token wurde widerrufen. Das Gerät muss neu gekoppelt werden.")
        key = ctx.keys.get(record["id"])
        if key is None:
            if record["id"] in ctx.keys.where():
                # Der Schlüssel liegt im Schlüsselbund und ist noch nicht geladen. Nie hier
                # blockieren: Nachladen im Hintergrund anstoßen, das Handy versucht es später.
                ctx.keys.request_load(record["id"])
                raise _MobileError(503, "key_unavailable",
                                   "Der Schlüsselbund am Rechner antwortet gerade nicht.")
            raise _MobileError(401, "encryption_required",
                               "Diese Kopplung ist nicht verschlüsselt. Das Gerät muss neu koppeln.")
        keep_previous = _still_valid(principal, record, now)
        seq = mc.envelope_seq(envelope)
        if seq <= int(record.get("last_seq", 0)):
            raise _MobileError(409, "replay", "Die Anfrage wurde bereits verarbeitet.")
        request_key, response_key = mc.device_keys(key)
        try:
            plain = mc.open_envelope(request_key, envelope, direction="req", method="POST",
                                     path="/v1/sync", device_id=record["id"])
        except mc.CryptoError:
            raise _MobileError(400, "decrypt_failed",
                               "Die Nachricht konnte nicht entschlüsselt werden.") from None
        seen = mobile_pairing.with_seq(record, seq)
        try:
            parsed = mobile_sync.parse_request(plain, now=now)
            response = mobile_sync.perform_sync(
                parsed, device_id=record["id"], device_name=record["name"],
                last_pull_at=record["last_pull_at"], categories=category_names(ctx.settings),
                storage=ctx.storage, settings=ctx.settings, conflicts_store=ctx.conflicts_store,
                base=ctx.base, now=now, today=ctx.today(), data_lock=ctx.data_lock,
                sync_guard=ctx.sync_guard)
        except (_MobileError, SyncError) as exc:
            ctx.devices.save(seen)                       # nur der Zähler: Token bleibt unverändert
            return _sealed(response_key, path="/v1/sync", device_id=record["id"], seq=seq,
                           payload={"error": {"code": exc.code, "message": exc.message}},
                           status=exc.status)
        except Exception:
            # Unerwartet (Platte voll …): der Server antwortet 500, der entschlüsselte Umschlag
            # darf aber nicht noch einmal einspielbar sein — den Zähler trotzdem festhalten.
            ctx.devices.save(seen)
            raise
        renewed, token = mobile_pairing.renew(seen, now, keep_previous=keep_previous)
        renewed["last_pull_at"] = response["last_pull_at"]
        ctx.devices.save(renewed)
        notify = True
    response["token"] = token
    response["expires_at"] = renewed["expires_at"]
    if notify:
        _notify(ctx)
    return _sealed(response_key, path="/v1/sync", device_id=record["id"], seq=seq, payload=response)


@dataclass(frozen=True)
class _Route:
    method: str
    path: str
    handler: Callable[[ApiRequest, MobileContext, Principal], ApiResponse]
    public: bool = False


ROUTES: tuple[_Route, ...] = (
    _Route("POST", "/v1/pair", _pair, public=True),
    _Route("GET", "/v1/ping", _ping),
    _Route("POST", "/v1/sync", _sync),
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
