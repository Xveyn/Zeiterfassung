# src/relay_adapter.py
"""Beantwortet Anfragen des Handys, die über die Box des Relays kommen (#358), Tk-frei, ohne I/O.

Der Relay ist ein **Tunnel für das bestehende Protokoll**: die Nutzlast `{v, path, token, envelope}`
(`mobile_relay_codec`) trägt denselben verschlüsselten Umschlag wie der LAN-Weg, und beantwortet wird
er von derselben Routenebene (`mobile_routes.dispatch`). Hier liegt nur, was der Transport zusätzlich
verlangt (Regeln der Leitidee in `docs/superpowers/specs/2026-11-02-ios-relay-abgleich-design.md`):

- **Regel 2:** ein Abgleich mit `seq <= last_seq` bekommt **keine** Antwort. Die Box hält je Richtung
  nur einen Platz, ein `409 replay` überschriebe dort die gute Antwort auf dieselbe Anfrage. `last_seq`
  ist das gespeicherte `record["last_seq"]` des Gerätedatensatzes, nie ein Zähler im Adapter — sonst
  beantwortete der Desktop nach einem Neustart ein erneut zugestelltes, schon angewendetes `req`.
  Meldet `dispatch` selbst `409 replay` (der Zähler stieg zwischen der Prüfung hier und der unter der
  Gerätesperre), gilt dasselbe: keine Antwort.
- **Regel 3:** eine Kopplung lässt sich nicht wiederholen (`try_open` verbraucht den Code). Die
  Erfolgsantwort wird deshalb in einem kleinen, befristeten Zwischenspeicher unter dem SHA-256 der
  Nutzlast-Bytes gehalten und bei identischem `req` unverändert erneut ausgeliefert. Fehler werden
  nicht gespeichert; für die Kopplung gilt keine `seq`-Regel (sie trägt immer `seq` 1, ein Neu-Koppeln
  setzt `last_seq` zurück).

Jede Antwort trägt die Nonce `n` der Anfrage, auch unversiegelte Fehler: nur daran erkennt das Handy,
dass eine Antwort zu seiner offenen Anfrage gehört (`seq` reicht nicht, Kopplung und erster Abgleich
tragen beide 1). Ohne gültiges `n` wird nicht geantwortet — eine solche Antwort verwürfe das Handy
ohnehin, und **keine** Antwort ist besser als eine, die den Platz einer guten belegt.

`handle`/`process` werfen nie eine `Exception`: alles nach dem Dekodieren ist abgesichert und wird im
Fehlerfall eine `500 internal` mit `n` (sonst wartete das Handy bis zum Timeout). Geloggt werden nur
Status, Fehlercodes und Ausnahmetypen, nie Token, Umschlag oder Ausnahmetext.

**Verwendung durch die Verbindungsschicht (PR 3b):** sie ruft `process(payload)`, legt
`RelayResult.frame` (falls nicht `None`) in die Box, auf der die Anfrage ankam, und bindet nach einer
gelungenen Kopplung das offene Box-Geheimnis an das Gerät:
`MobileBoxStore.bind(result.paired_device_id, expected=<Geheimnis dieser Box>)`. Die Geräte-ID ermittelt
der Adapter ohne den versiegelten Inhalt zu lesen, aus dem Gerät, dessen `pair_count` beim `dispatch`
gestiegen ist (genau eines, sonst `None`). Eine erneute Zustellung derselben Kopplung liefert aus dem
Zwischenspeicher dieselbe Geräte-ID: wer vor dem Binden abbrach, kann `bind` wiederholen (über `expected`
idempotent). `handle` ist nur `process(payload).frame`.

Grenzen, die der Aufrufer kennen muss:

- **Box und Gerät werden nicht gegeneinander geprüft.** Geantwortet wird auf der Box, auf der der
  Rahmen ankam; eine Anfrage für Gerät X, zugestellt auf der Box von Gerät Y, wird auf Ys Box
  beantwortet. Das liegt im Modell „wer das Box-Geheimnis hat“: lesen kann die Antwort ohnehin nur,
  wer `k_dev` von X hat.

- **Ein Adapter je `MobileContext`, `process`/`handle` aus genau einem Arbeits-Thread.** Gleiche
  Kopplungs-Nutzlasten aus mehreren Threads gleichzeitig werden nicht zusammengelegt (die zweite
  bekäme `403 invalid_code`); die Verbindungsschicht (PR 3b) ruft den Adapter deshalb nacheinander. Die
  Sperre des Zwischenspeichers wird nie über `dispatch` gehalten.
- **Kopplung nach einem Fehlschlag, der den Code schon verbraucht hat** (Gerät nicht speicherbar):
  eine erneute Zustellung bekommt `403 invalid_code` mit demselben `n`. Das Handy zeigt dann „Code
  ungültig“, der Koppel-Dialog am Desktop den Fehlschlag.
- **Zu große Antwort:** das `413`-Ersatzframe geht raus, obwohl die Anfrage schon angewendet ist
  (`last_seq` vorgerückt, Token erneuert). Das Handy arbeitet mit dem alten Token weiter, solange es
  als vorheriges gilt (rund 7 Tage ab der ersten Erneuerung); das `413` wiederholt sich bei jedem
  Abgleich, bis der Nutzer das Fenster verkleinert. Danach muss das Handy neu koppeln.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from dataclasses import dataclass

from src import mobile_pairing, mobile_routes
from src.api_auth import ANONYMOUS, Denied, Principal
from src.api_routes import ApiRequest, ApiResponse, error_response
from src.mobile_relay_codec import (
    FrameError, FrameTooLarge, RelayRequest, decode_request, encode_response,
    encode_too_large_response, should_answer,
)

_log = logging.getLogger(__name__)

# Dieselben Codes und Texte wie die Auth-Antworten des LAN-Wegs (`api_server`); ein Test hält sie gleich.
_AUTH_MESSAGES: dict[str, str] = {
    "unauthorized": "Token fehlt oder ist ungültig.",
    "token_expired": "Das Token ist abgelaufen. Das Gerät muss neu gekoppelt werden.",
    "token_revoked": "Das Token wurde widerrufen. Das Gerät muss neu gekoppelt werden.",
}
_INTERNAL_MESSAGE = "Interner Fehler am Desktop."


@dataclass(frozen=True)
class RelayResult:
    """Ergebnis von `RelayAdapter.process`.

    `frame` ist die Antwort-Nutzlast (`None`: nichts in die Box legen). `paired_device_id` ist nur
    nach einer **gelungenen** Kopplung (`/v1/pair`, Status 200) gesetzt, auch bei der erneuten
    Zustellung derselben Anfrage aus dem Zwischenspeicher — so kann ein Aufrufer, der vor dem Binden
    abgebrochen ist, `bind` wiederholen."""
    frame: bytes | None
    paired_device_id: str | None


_NO_ANSWER = RelayResult(None, None)


def _unauthorized(code: str) -> ApiResponse:
    return error_response(401, code, _AUTH_MESSAGES[code])


def _error_code(body: Any) -> str | None:
    """Der Fehlercode eines unversiegelten Fehler-Bodys `{"error": {"code": …}}`, sonst `None`."""
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


class RelayAdapter:
    """Nutzlast einer Relay-Anfrage → Nutzlast der Antwort, oder `None` für „nicht antworten“."""

    def __init__(self, ctx: mobile_routes.MobileContext, *,
                 clock: Callable[[], float] = time.monotonic,
                 cache_size: int = 8, cache_ttl_seconds: float = 330.0) -> None:
        self._ctx = ctx
        self._clock = clock
        self._cache_size = cache_size
        self._cache_ttl = cache_ttl_seconds
        self._cache: OrderedDict[str, tuple[float, RelayResult]] = OrderedDict()
        self._lock = threading.Lock()

    def handle(self, payload: bytes) -> bytes | None:
        """Beantwortet eine Nutzlast. Wirft nie eine `Exception`; `None` heißt: nichts in die Box legen.
        Nur das Antwort-Frame von `process`."""
        return self.process(payload).frame

    def process(self, payload: bytes) -> RelayResult:
        """Wie `handle`, dazu die Geräte-ID einer gelungenen Kopplung (`RelayResult`). Wirft nie
        eine `Exception`."""
        try:
            request = decode_request(payload)
        except FrameError as exc:
            _log.debug("Relay-Anfrage verworfen: %s", exc.code)
            return _NO_ANSWER
        if request.n is None:
            _log.debug("Relay-Anfrage ohne gültige Nonce verworfen")
            return _NO_ANSWER
        try:
            if request.path == "/v1/pair":
                return self._pair(payload, request)
            return RelayResult(self._sync(request), None)
        except Exception as exc:
            # Wie der LAN-Server: ein Programmfehler (Prüfer, Gerätespeicher, `dispatch`, Kodieren)
            # wird eine 500 ohne Details. Nur der Typ ins Log, der Ausnahmetext kann Inhalte tragen.
            # `BaseException` (Strg+C, SystemExit) läuft bewusst durch.
            _log.warning("Relay-Anfrage %s: %s", request.path, type(exc).__name__)
            body = error_response(500, "internal", _INTERNAL_MESSAGE).body
            return RelayResult(encode_response(500, body, request.seq, request.n), None)

    # --- Kopplung -----------------------------------------------------------------------------------
    def _pair(self, payload: bytes, request: RelayRequest) -> RelayResult:
        key = hashlib.sha256(payload).hexdigest()
        cached = self._cached(key)
        if cached is not None:
            _log.debug("Relay-Kopplung: Antwort aus dem Zwischenspeicher")
            return cached
        before = self._pair_counts()
        response = self._dispatch(request, ANONYMOUS)
        encoded = self._encode(response, request)
        if response.status != 200:
            return RelayResult(encoded, None)
        result = RelayResult(encoded, self._newly_paired(before, self._pair_counts()))
        self._remember(key, result)
        return result

    def _pair_counts(self) -> dict[str, int]:
        return {str(record.get("id")): mobile_pairing.pair_count(record)
                for record in self._ctx.devices.get_all()}

    @staticmethod
    def _newly_paired(before: dict[str, int], after: dict[str, int]) -> str | None:
        """Das Gerät, dessen `pair_count` gestiegen ist (oder das neu ist); bei keinem oder mehreren
        Kandidaten `None` — der verschlüsselte Inhalt der Anfrage wird dafür nicht gelesen."""
        changed = [device_id for device_id, count in after.items() if count > before.get(device_id, 0)]
        return changed[0] if len(changed) == 1 else None

    def _cached(self, key: str) -> RelayResult | None:
        now = self._clock()
        with self._lock:
            self._drop_expired(now)
            entry = self._cache.get(key)
            return entry[1] if entry is not None else None

    def _remember(self, key: str, result: RelayResult) -> None:
        now = self._clock()
        with self._lock:
            self._drop_expired(now)
            self._cache[key] = (now, result)
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)

    def _drop_expired(self, now: float) -> None:
        # Unter `self._lock`. Einträge werden in Ablagereihenfolge geschrieben: der älteste steht vorn.
        while self._cache:
            stored_at, _encoded = next(iter(self._cache.values()))
            if now - stored_at <= self._cache_ttl:
                break
            self._cache.popitem(last=False)

    # --- Abgleich -----------------------------------------------------------------------------------
    def _sync(self, request: RelayRequest) -> bytes | None:
        token = request.token
        assert token is not None                     # `decode_request` verlangt es für `/v1/sync`
        outcome = mobile_routes.make_verifier(self._ctx.devices, self._ctx.now)(token)
        if isinstance(outcome, Denied):
            _log.debug("Relay-Abgleich abgelehnt: %s", outcome.code)
            return self._encode(_unauthorized(outcome.code), request)
        if not isinstance(outcome, mobile_routes.MobilePrincipal):
            _log.debug("Relay-Abgleich abgelehnt: unauthorized")
            return self._encode(_unauthorized("unauthorized"), request)
        record = self._ctx.devices.get(outcome.name)
        if record is None:
            # Zwischen Prüfer und hier verschwunden: wie `_sync` im LAN-Weg ein Widerruf.
            _log.debug("Relay-Abgleich abgelehnt: token_revoked (Datensatz fehlt)")
            return self._encode(_unauthorized("token_revoked"), request)
        if not should_answer(request.seq, int(record.get("last_seq", 0))):
            _log.debug("Relay-Abgleich übersprungen: seq nicht neuer als last_seq")
            return None
        response = self._dispatch(request, outcome)
        if response.status == 409 and _error_code(response.body) == "replay":
            # Der Zähler stieg zwischen der Prüfung oben und der unter der Gerätesperre (gleiche
            # Anfrage parallel beantwortet): Regel 2, das 409 überschriebe die gute Antwort.
            _log.debug("Relay-Abgleich übersprungen: 409 replay aus dispatch")
            return None
        return self._encode(response, request)

    # --- Gemeinsam ----------------------------------------------------------------------------------
    def _dispatch(self, request: RelayRequest, principal: Principal) -> ApiResponse:
        # Kompakt und ohne `\uXXXX`: sonst wüchse ein feindlicher Nicht-ASCII-Umschlag vor `dispatch` bis
        # auf das Dreifache (der LAN-Weg deckelt den rohen Body bei 1 MiB).
        body = json.dumps(request.envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        api_request = ApiRequest("POST", request.path, {}, body)
        return mobile_routes.dispatch(api_request, self._ctx, principal)

    def _encode(self, response: ApiResponse, request: RelayRequest) -> bytes:
        _log.debug("Relay-Antwort %s: %d", request.path, response.status)
        try:
            return encode_response(response.status, response.body, request.seq, request.n)
        except FrameTooLarge:
            _log.warning("Relay-Antwort %s zu groß, sende 413", request.path)
            return encode_too_large_response(request.seq, request.n)
