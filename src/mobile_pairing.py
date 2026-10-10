# src/mobile_pairing.py
"""Pairing-Code und Gerätetoken der Handy-Erfassung (#221), Tk-frei und stdlib-only.

Rein: kein Dateizugriff, kein Socket. Die Uhr kommt als Parameter herein
(`clock` für die Laufzeit des Codes, `now` als UTC-Text `YYYY-MM-DDTHH:MM:SSZ`
für die Gerätedatensätze), damit alles ohne `sleep` testbar ist. Persistiert
werden die Datensätze von `mobile_store`; der Server (`mobile_routes`) ruft hier
nur auf.

Zwei Dinge liegen hier:

- **Der Kopplungscode** (`PairingSession`): 28 Zeichen aus 31 (≈139 Bit), 5 Minuten
  gültig, einmal einlösbar, **ohne Sperre** (s. dort). Er steht nur im Hauptspeicher
  und geht nie über das Netz: er verschlüsselt die Kopplung (`mobile_crypto`).
- **Das Gerätetoken** (`issue_device`, `renew`, `authenticate`): 256 Bit Zufall,
  im Datensatz nur als SHA-256-Hash. 30 Tage ab der letzten Nutzung (Sliding
  Expiration); jede Erneuerung lässt das alte Token noch 10 Minuten gelten, damit
  eine verlorene Antwort das Handy nicht aussperrt.

Geräte-ID, Name und Token kommen vom Handy — Fremddaten.
"""
from __future__ import annotations

import datetime
import enum
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

# Ziffern 2–9 und Buchstaben ohne I, L, O: 31 Zeichen, keine Verwechslung 0/O, 1/I/L.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
# 28 Zeichen aus 31: ≈139 Bit. Der Code ist seit #249 zugleich Schlüsselmaterial der Kopplung
# (aus ihm leitet `mobile_crypto.pair_keys` die Schlüssel ab) und lässt sich abtippen.
CODE_LENGTH = 28
CODE_TTL_SECONDS = 300
_MAX_RAW_CODE_LENGTH = 64



def generate_code() -> str:
    """Ein frischer Code in kanonischer Form (8 Zeichen, ohne Bindestrich)."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def format_code(code: str) -> str:
    """`K7M29QXA…` → `K7M2-9QXA-…` (Anzeige): Gruppen zu vier."""
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def normalize_code(raw: object) -> str | None:
    """Die kanonische Form einer Eingabe, oder `None`, wenn sie kein möglicher
    Code ist. Groß-/Kleinschreibung, Bindestriche und Leerzeichen sind egal; ein
    Zeichen außerhalb des Alphabets (auch `0`, `O`, `1`, `I`, `L`) ist ungültig."""
    if not isinstance(raw, str) or len(raw) > _MAX_RAW_CODE_LENGTH:
        return None
    code = raw.strip().upper().replace("-", "").replace(" ", "")
    if len(code) != CODE_LENGTH or any(ch not in CODE_ALPHABET for ch in code):
        return None
    return code


T = TypeVar("T")


class RedeemResult(enum.Enum):
    OK = "ok"
    INVALID = "invalid"      # nicht zu öffnen, abgelaufen, verbraucht oder gar kein Code aktiv


class PairingSession:
    """Der eine aktive Kopplungscode. Thread-sicher: `try_open` kommt aus Server-Threads,
    `open`/`close` aus dem UI-Thread.

    **Keine Sperre nach Fehlversuchen.** Mit ≈139 Bit ist der Code nicht zu erraten; eine
    Sperre schützte also vor nichts und wäre nur ein Hebel, mit dem ein Fremder im WLAN die
    Kopplung dauerhaft verhindert (ein paar Zufalls-Umschläge an `/v1/pair` genügten). Der
    Schutz sind die Länge des Codes, die fünf Minuten Gültigkeit und dass er nur einmal gilt;
    ein Fehlversuch kostet den Angreifer eine AES-GCM-Prüfung und den Server dasselbe."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, *,
                 ttl_seconds: float = CODE_TTL_SECONDS) -> None:
        self._clock = clock
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._code: str | None = None
        self._expires = 0.0

    def open(self) -> str:
        """Erzeugt einen neuen Code (der alte verfällt) und liefert ihn formatiert."""
        with self._lock:
            self._code = generate_code()
            self._expires = self._clock() + self._ttl
            return format_code(self._code)

    def close(self) -> None:
        """Macht den Code ungültig (Dialog geschlossen)."""
        with self._lock:
            self._code = None

    def is_active(self) -> bool:
        with self._lock:
            return self._active_locked()

    def seconds_left(self) -> int:
        with self._lock:
            if not self._active_locked():
                return 0
            return max(0, int(self._expires - self._clock()))

    def _active_locked(self) -> bool:
        if self._code is None:
            return False
        if self._clock() >= self._expires:
            self._code = None
            return False
        return True

    def try_open(self, attempt: Callable[[str], T | None]) -> tuple[RedeemResult, T | None]:
        """Benutzt den aktiven Code: `attempt` bekommt ihn (zum Ableiten der Kopplungsschlüssel)
        und liefert ein Ergebnis oder `None`, wenn die Nachricht nicht damit zu öffnen war. Nur
        ein Ergebnis verbraucht den Code; `None` ändert nichts. Läuft unter dem Lock: `attempt`
        muss kurz sein und darf nichts loggen."""
        with self._lock:
            if not self._active_locked() or self._code is None:
                return RedeemResult.INVALID, None
            value = attempt(self._code)
            if value is None:
                return RedeemResult.INVALID, None
            self._code = None
            return RedeemResult.OK, value


# --- Gerätetoken und -datensätze ---------------------------------------------------------------------

TOKEN_LIFETIME = datetime.timedelta(days=30)
PREVIOUS_TOKEN_GRACE = datetime.timedelta(minutes=10)
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_MAX_TOKEN_LENGTH = 512
MAX_NAME_LENGTH = 60
DEFAULT_DEVICE_NAME = "Handy"
_DEVICE_ID_RE = re.compile(r"[A-Za-z0-9-]{8,64}")


Record = dict[str, Any]


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 (hex) des Tokens. Das Token hat 256 Bit Zufall, ein schneller Hash
    genügt: ein Wörterbuchangriff auf den Hash ist aussichtslos. `surrogatepass`,
    damit auch ein kaputtes Zeichen im Header zu einem (nie passenden) Hash wird."""
    return hashlib.sha256(token.encode("utf-8", errors="surrogatepass")).hexdigest()


def normalize_device_id(raw: object) -> str | None:
    """Die Geräte-ID des Handys (eine UUID, 8–64 Zeichen aus `A-Za-z0-9-`), sonst `None`."""
    if isinstance(raw, str) and _DEVICE_ID_RE.fullmatch(raw):
        return raw
    return None


def clean_device_name(raw: object) -> str:
    """Ein anzeigbarer Gerätename: ohne Steuerzeichen, getrimmt, höchstens
    `MAX_NAME_LENGTH` Zeichen; leer oder kein Text wird `Handy`."""
    if not isinstance(raw, str):
        return DEFAULT_DEVICE_NAME
    name = "".join(ch for ch in raw if ch.isprintable()).strip()[:MAX_NAME_LENGTH].strip()
    return name or DEFAULT_DEVICE_NAME


def shift(now: str, delta: datetime.timedelta) -> str:
    """`now` (UTC-Text) plus `delta`, im selben Format. Das feste Format macht den
    String-Vergleich der Zeitstempel korrekt."""
    moment = datetime.datetime.strptime(now, _TIME_FORMAT)
    return (moment + delta).strftime(_TIME_FORMAT)


def pair_count(record: Mapping[str, Any] | None) -> int:
    """Wie oft dieses Gerät gekoppelt wurde (`issue_device`); Datensätze von vorher und
    Fremdwerte zählen als 0. Ein Abgleich (`renew`) ändert den Zähler nicht."""
    value = record.get("pair_count") if record else 0
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def issue_device(device_id: str, name: str, now: str,
                 existing: Mapping[str, Any] | None = None) -> tuple[Record, str]:
    """Ein neues Gerät (oder ein erneutes Koppeln desselben): liefert den Datensatz
    **ohne Klartext-Token** und das Token zur einmaligen Übergabe an das Handy. Beim
    erneuten Koppeln bleiben `created_at` und `last_pull_at` erhalten (die Identität
    im Sync ändert sich nicht), ein Widerruf wird aufgehoben. `pair_count` zählt jedes
    Koppeln hoch: so erkennt der Koppel-Dialog ein Ersetzen ausdrücklich, statt es aus
    Token-Hashes zu raten (ein Handy synct gleich nach dem Koppeln)."""
    token = new_token()
    record: Record = {
        "id": device_id,
        "name": name,
        "token_hash": hash_token(token),
        "previous_token_hash": "",
        "previous_valid_until": "",
        "created_at": str(existing["created_at"]) if existing else now,
        "expires_at": shift(now, TOKEN_LIFETIME),
        "last_seen": now,
        "last_pull_at": str(existing["last_pull_at"]) if existing else "",
        "revoked": False,
        "pair_count": pair_count(existing) + 1,
        "last_seq": 0,                      # Replay-Schutz (#249): höchster gesehener Zähler
    }
    return record, token


def with_seq(record: Mapping[str, Any], seq: int) -> Record:
    """Kopie des Datensatzes mit höchstem gesehenen Zähler `seq` (Replay-Schutz, #249)."""
    updated: Record = dict(record)
    updated["last_seq"] = seq
    return updated


def renew(record: Mapping[str, Any], now: str, *,
          keep_previous: bool = False) -> tuple[Record, str]:
    """Erneuert das Token (Sliding Expiration): neues Token, Ablauf 30 Tage ab `now`.
    Das bisherige gilt noch 10 Minuten. Kam die Anfrage selbst mit dem **alten**
    Token (`keep_previous`: die Antwort mit dem neuen ging verloren), bleibt dieses
    alte als „vorheriges" erhalten, statt vom noch nie übergebenen aktuellen
    verdrängt zu werden — sonst sperrte ein zweiter Verlust das Handy aus."""
    token = new_token()
    updated: Record = dict(record)
    if not keep_previous:
        updated["previous_token_hash"] = str(record["token_hash"])
    updated["previous_valid_until"] = shift(now, PREVIOUS_TOKEN_GRACE)
    updated["token_hash"] = hash_token(token)
    updated["expires_at"] = shift(now, TOKEN_LIFETIME)
    updated["last_seen"] = now
    return updated, token


def revoke(record: Mapping[str, Any]) -> Record:
    """Der Datensatz bleibt (damit die Antwort `token_revoked` lauten kann), das Token
    ist nicht mehr brauchbar."""
    updated: Record = dict(record)
    updated["revoked"] = True
    updated["previous_token_hash"] = ""
    updated["previous_valid_until"] = ""
    return updated


@dataclass(frozen=True)
class AuthOutcome:
    status: str                      # "ok" | "unauthorized" | "expired" | "revoked"
    record: Record | None = None
    via_previous: bool = False       # das Token war das vorherige (Karenzfenster)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def authenticate(records: Iterable[Mapping[str, Any]], token: object, now: str) -> AuthOutcome:
    """Ordnet ein Token einem Gerät zu. Verglichen wird gegen alle Datensätze (kein
    früher Abbruch), konstantzeitig je Hash."""
    unknown = AuthOutcome("unauthorized")
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        return unknown
    candidate = hash_token(token).encode("ascii")
    current: Mapping[str, Any] | None = None
    previous: Mapping[str, Any] | None = None
    for record in records:
        if hmac.compare_digest(candidate, str(record.get("token_hash", "")).encode("ascii", "replace")):
            current = record
        prev_hash = str(record.get("previous_token_hash", ""))
        if prev_hash and hmac.compare_digest(candidate, prev_hash.encode("ascii", "replace")):
            previous = record
    if current is not None:
        return _state_of(current, now, via_previous=False)
    if previous is not None and str(previous.get("previous_valid_until", "")) >= now:
        return _state_of(previous, now, via_previous=True)
    return unknown


def _state_of(record: Mapping[str, Any], now: str, *, via_previous: bool) -> AuthOutcome:
    if record.get("revoked"):
        return AuthOutcome("revoked", dict(record), via_previous)
    if str(record.get("expires_at", "")) <= now:
        return AuthOutcome("expired", dict(record), via_previous)
    return AuthOutcome("ok", dict(record), via_previous)
