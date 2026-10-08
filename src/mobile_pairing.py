# src/mobile_pairing.py
"""Pairing-Code und Gerätetoken der Handy-Erfassung (#221), Tk-frei und stdlib-only.

Rein: kein Dateizugriff, kein Socket. Die Uhr kommt als Parameter herein
(`clock` für die Laufzeit des Codes, `now` als UTC-Text `YYYY-MM-DDTHH:MM:SSZ`
für die Gerätedatensätze), damit alles ohne `sleep` testbar ist. Persistiert
werden die Datensätze von `mobile_store`; der Server (`mobile_routes`) ruft hier
nur auf.

Zwei Dinge liegen hier:

- **Der Einmalcode** (`PairingSession`): 8 Zeichen aus 31, 5 Minuten gültig, einmal
  einlösbar, nach 5 Fehlversuchen gesperrt. Er steht nur im Hauptspeicher.
- **Das Gerätetoken** (`issue_device`, `renew`, `authenticate`): 256 Bit Zufall,
  im Datensatz nur als SHA-256-Hash. 30 Tage ab der letzten Nutzung (Sliding
  Expiration); jede Erneuerung lässt das alte Token noch 10 Minuten gelten, damit
  eine verlorene Antwort das Handy nicht aussperrt.

Geräte-ID, Name und Token kommen vom Handy — Fremddaten.
"""
from __future__ import annotations

import enum
import hmac
import secrets
import threading
import time
from collections.abc import Callable

# Ziffern 2–9 und Buchstaben ohne I, L, O: 31 Zeichen, keine Verwechslung 0/O, 1/I/L.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 8
CODE_TTL_SECONDS = 300
MAX_CODE_FAILURES = 5
_MAX_RAW_CODE_LENGTH = 32



def generate_code() -> str:
    """Ein frischer Code in kanonischer Form (8 Zeichen, ohne Bindestrich)."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def format_code(code: str) -> str:
    """`K7M29QXA` → `K7M2-9QXA` (Anzeige und QR-Code)."""
    half = CODE_LENGTH // 2
    return f"{code[:half]}-{code[half:]}"


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


class RedeemResult(enum.Enum):
    OK = "ok"
    INVALID = "invalid"      # falsch, abgelaufen, verbraucht oder gar kein Code aktiv
    LOCKED = "locked"        # zu viele Fehlversuche, bis zum nächsten `open()`


class PairingSession:
    """Der eine aktive Einmalcode. Thread-sicher: `redeem` kommt aus
    Server-Threads, `open`/`close` aus dem UI-Thread."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, *,
                 ttl_seconds: float = CODE_TTL_SECONDS,
                 max_failures: int = MAX_CODE_FAILURES) -> None:
        self._clock = clock
        self._ttl = ttl_seconds
        self._max_failures = max_failures
        self._lock = threading.Lock()
        self._code: str | None = None
        self._expires = 0.0
        self._failures = 0
        self._locked = False

    def open(self) -> str:
        """Erzeugt einen neuen Code (der alte verfällt, Sperre und Zähler werden
        zurückgesetzt) und liefert ihn formatiert."""
        with self._lock:
            self._code = generate_code()
            self._expires = self._clock() + self._ttl
            self._failures = 0
            self._locked = False
            return format_code(self._code)

    def close(self) -> None:
        """Macht den Code ungültig (Dialog geschlossen)."""
        with self._lock:
            self._code = None
            self._failures = 0
            self._locked = False

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

    def redeem(self, raw: object) -> RedeemResult:
        """Löst den Code ein. Bei Erfolg ist er verbraucht. Der Fehlversuch, der den
        Zähler erschöpft, ist selbst noch `INVALID`; danach antwortet die Sitzung
        `LOCKED`, bis ein neuer Code geöffnet wird."""
        with self._lock:
            if self._locked:
                return RedeemResult.LOCKED
            if not self._active_locked() or self._code is None:
                return RedeemResult.INVALID
            candidate = normalize_code(raw) or "-" * CODE_LENGTH
            # Immer vergleichen, auch bei einer Form, die nie passen kann: gleiche Laufzeit.
            if hmac.compare_digest(candidate.encode("ascii"), self._code.encode("ascii")):
                self._code = None
                self._failures = 0
                return RedeemResult.OK
            self._failures += 1
            if self._failures >= self._max_failures:
                self._code = None
                self._locked = True
            return RedeemResult.INVALID
