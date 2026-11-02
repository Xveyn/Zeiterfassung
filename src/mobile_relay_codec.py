# src/mobile_relay_codec.py
"""Codec für den Abgleich Handy <-> Desktop über die Box des Relays (#358), Tk-frei, ohne I/O.

Zwei Schichten:

- **Nachrichtenrahmen** der Box (WebSocket): `put` = Typ-Byte 1 + Nutzbytes (Desktop -> Box),
  `slot` = 2 + `ver` (uint32, big-endian) + Nutzbytes und `ok` = 3 + `ver` (Box -> Desktop).
- **Nutzlast** einer Anfrage/Antwort: UTF-8-JSON `{v:1, path, token, envelope}` bzw.
  `{v:1, status, seq, body}`. Der Umschlag selbst ist der verschlüsselte der lokalen Handy-Instanz
  (`mobile_crypto`); hier wird er nur transportiert.

Gegenstück der PWA: `pwa/relay-frame.js`; den Gleichlauf hält `pwa/test/fixtures/relay-frames.json`.
Größen zählen in **Bytes** der kodierten Nutzlast. Nach außen kommen aus den Dekodierern und
Kodierern nur `FrameError`/`FrameTooLarge`. Nichts hier loggt.
"""
from __future__ import annotations

import json
import re
import secrets
import struct
from dataclasses import dataclass
from typing import Any, Final, NoReturn

from src import mobile_pairing
from src.mobile_routes import PWA_URL

SUBPROTOCOL: Final[str] = "zeit.v1"
MAX_FRAME: Final[int] = 1_048_576          # ganze Nachricht samt Typ-Byte
MAX_PAYLOAD: Final[int] = MAX_FRAME - 1    # Nutzbytes eines `put`
PUTS_PER_MINUTE: Final[int] = 60
TYPE_PUT: Final[int] = 1
TYPE_SLOT: Final[int] = 2
TYPE_OK: Final[int] = 3

MAX_SEQ: Final[int] = 2**53 - 1
BOX_SECRET_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_-]{43}")
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[\x21-\x7e]{1,512}")
_PATHS: Final[frozenset[str]] = frozenset({"/v1/pair", "/v1/sync"})


class FrameError(ValueError):
    """Ungültiger Rahmen oder ungültige Nutzlast."""

    code: str = "invalid_frame"


class FrameTooLarge(FrameError):
    """Nutzlast größer als `MAX_PAYLOAD` Bytes."""

    code = "too_large"


@dataclass(frozen=True)
class RelayMessage:
    kind: str       # "slot" oder "ok"
    ver: int
    data: bytes


@dataclass(frozen=True)
class RelayRequest:
    path: str
    token: str | None
    envelope: dict[str, Any]

    @property
    def seq(self) -> int | None:
        return envelope_seq(self.envelope)


def _is_int(value: object) -> bool:
    # `bool` ist in Python ein `int`: True == 1 darf nie als Zahl durchgehen.
    return type(value) is int


def _valid_seq(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_SEQ


def envelope_seq(envelope: object) -> int | None:
    """Das gültige `seq` eines Umschlags (ganze Zahl 1 … 2^53-1) oder `None`."""
    if not isinstance(envelope, dict):
        return None
    seq = envelope.get("seq")
    if _valid_seq(seq):
        assert isinstance(seq, int)
        return seq
    return None


def should_answer(seq: int | None, last_seq: int) -> bool:
    """Nur eine Anfrage mit gültigem, größerem `seq` als dem zuletzt beantworteten wird beantwortet."""
    return seq is not None and _valid_seq(seq) and seq > last_seq


def encode_put(payload: bytes) -> bytes:
    if not isinstance(payload, (bytes, bytearray)):
        raise FrameError("Nutzlast muss bytes sein")
    if len(payload) > MAX_PAYLOAD:
        raise FrameTooLarge("Nutzlast zu groß")
    return bytes([TYPE_PUT]) + bytes(payload)


def decode_message(data: bytes | str) -> RelayMessage | None:
    """Nachricht der Box; `None` für Text, Unbekanntes, Abgeschnittenes und Leeres. Wirft nie."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 5:
        return None
    kind_byte = data[0]
    if kind_byte not in (TYPE_SLOT, TYPE_OK):
        return None
    (ver,) = struct.unpack(">I", bytes(data[1:5]))
    if kind_byte == TYPE_OK:
        return RelayMessage("ok", ver, b"")
    return RelayMessage("slot", ver, bytes(data[5:]))


def _reject_constant(name: str) -> NoReturn:
    raise FrameError(f"Konstante {name} ist kein JSON")


def _parse_object(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, (bytes, bytearray)):
        raise FrameError("Bytes erwartet")
    if len(payload) > MAX_PAYLOAD:
        raise FrameTooLarge("Nutzlast zu groß")
    try:
        value = json.loads(bytes(payload).decode("utf-8"), parse_constant=_reject_constant)
    except FrameError:
        raise
    except RecursionError:
        raise FrameError("JSON zu tief verschachtelt") from None
    except ValueError:
        # UnicodeDecodeError, JSONDecodeError und das int-Stellenlimit sind alle ValueError.
        raise FrameError("Kein gültiges JSON in UTF-8") from None
    if not isinstance(value, dict):
        raise FrameError("JSON-Objekt erwartet")
    return value


def decode_request(payload: bytes) -> RelayRequest:
    value = _parse_object(payload)
    if not _is_int(value.get("v")) or value["v"] != 1:
        raise FrameError("v muss 1 sein")
    path = value.get("path")
    token = value.get("token")
    envelope = value.get("envelope")
    if not isinstance(path, str) or path not in _PATHS:
        raise FrameError("Pfad nicht erlaubt")
    if token is None:
        if path != "/v1/pair":
            raise FrameError("Token fehlt")
    elif not isinstance(token, str) or _TOKEN_RE.fullmatch(token) is None:
        raise FrameError("Token ungültig")
    if not isinstance(envelope, dict):
        raise FrameError("Umschlag muss ein Objekt sein")
    return RelayRequest(path, token, envelope)


def encode_response(status: int, body: Any, seq: int | None) -> bytes:
    if not _is_int(status) or not 100 <= status <= 599:
        raise FrameError("status ungültig")
    if seq is not None and not (_is_int(seq) and _valid_seq(seq)):
        raise FrameError("seq ungültig")
    try:
        text = json.dumps({"v": 1, "status": status, "seq": seq, "body": body},
                          ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        encoded = text.encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        # Nicht serialisierbarer Body (Typ, NaN, Zyklus, Surrogate): Aufruferfehler, kein Absturz.
        raise FrameError("Antwort nicht serialisierbar") from None
    if len(encoded) > MAX_PAYLOAD:
        raise FrameTooLarge("Nutzlast zu groß")
    return encoded


def generate_box_secret() -> str:
    """Neues Geheimnis der Box: 43 Zeichen Base64url (256 Bit)."""
    return secrets.token_urlsafe(32)


def relay_link(secret: str, code: str) -> str | None:
    """Koppel-Link `<PWA>#relay=<Geheimnis>:<Code>`; `None` bei ungültigem Geheimnis oder Code."""
    if not isinstance(secret, str) or BOX_SECRET_RE.fullmatch(secret) is None:
        return None
    canonical = mobile_pairing.normalize_code(code)
    if canonical is None:
        return None
    return f"{PWA_URL}#relay={secret}:{canonical}"
