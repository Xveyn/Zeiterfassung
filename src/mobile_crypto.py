# src/mobile_crypto.py
"""Ende-zu-Ende-Verschlüsselung der Handy-Erfassung (#249), Tk-frei, ohne I/O.

AES-256-GCM (`cryptography`) mit HKDF-SHA-256-Schlüsseln. Zwei Schlüsselpaare:

- **Kopplung:** aus dem langen Kopplungscode (`pair_keys`) — Anfrage und Antwort von
  `POST /v1/pair`. Der Code steht nie im Netz.
- **Abgleich:** aus dem zufälligen Geräteschlüssel `k_dev` (`device_keys`), der mit der
  Kopplungsantwort verschlüsselt zum Handy kommt — `POST /v1/sync`.

Jede Richtung hat einen eigenen Schlüssel (Anfrage ≠ Antwort): eine mitgeschnittene
Anfrage lässt sich nicht als Antwort einspielen. Der Umschlag
`{"v": 2, "seq": N, "n": <Nonce>, "c": <Chiffretext+Tag>}` trägt eine **zufällige**
96-Bit-Nonce je Nachricht. Zusatzdaten (AAD) binden Richtung, Methode, Pfad, Geräte-ID
und Zähler: ein Umschlag taugt nur für genau diese Anfrage dieses Geräts. Den Zähler
(`seq`, Replay-Schutz) verwaltet der Aufrufer; hier wird er nur gebunden und geprüft.

Gleichlauf mit `pwa/crypto.js` hält `pwa/test/fixtures/crypto-vectors.json`.
Nichts hier loggt.
"""
from __future__ import annotations

import base64
import binascii
import os
import re
from collections.abc import Mapping
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PROTOCOL = 2
KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16
MAX_SEQ = 2 ** 53 - 1                       # größte in JavaScript exakte ganze Zahl
_B64URL = re.compile(r"[A-Za-z0-9_-]*")
_ENVELOPE_KEYS = frozenset({"v", "seq", "n", "c"})
_DIRECTIONS = frozenset({"req", "res"})


class CryptoError(Exception):
    """`invalid_envelope`: die Form stimmt nicht (vor dem Entschlüsseln erkannt).
    `decrypt_failed`: Schlüssel, Zusatzdaten oder Inhalt passen nicht (Fälschung,
    falscher Schlüssel, umgeleiteter Umschlag) — mehr verrät es bewusst nicht."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64d(text: object) -> bytes:
    """Strenges base64url ohne Padding; auch die kanonische Form wird verlangt (die
    letzten Bits dürfen nicht gesetzt sein), damit es genau eine Schreibweise gibt."""
    if not isinstance(text, str) or not _B64URL.fullmatch(text) or len(text) % 4 == 1:
        raise CryptoError("invalid_envelope", "Ungültige Kodierung.")
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise CryptoError("invalid_envelope", "Ungültige Kodierung.") from None
    if b64e(raw) != text:
        raise CryptoError("invalid_envelope", "Ungültige Kodierung.")
    return raw


def derive_key(secret: bytes, label: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None,
                info=f"zeit-mobile/2/{label}".encode("ascii")).derive(secret)


def pair_keys(code: str) -> tuple[bytes, bytes]:
    """(Anfrage-, Antwortschlüssel) der Kopplung aus dem kanonischen Kopplungscode."""
    secret = b"code:" + code.encode("ascii")
    return derive_key(secret, "pair/request"), derive_key(secret, "pair/response")


def device_keys(key: bytes) -> tuple[bytes, bytes]:
    """(Anfrage-, Antwortschlüssel) des Abgleichs aus `k_dev`."""
    return derive_key(key, "sync/request"), derive_key(key, "sync/response")


def new_device_key() -> bytes:
    return os.urandom(KEY_BYTES)


def _valid_seq(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_SEQ


def is_envelope(obj: object) -> bool:
    """Form eines Umschlags, ohne zu entschlüsseln (auch für die Entscheidung
    „Klartext oder Umschlag"). Nonce genau 12, Chiffretext mindestens ein Tag."""
    if not isinstance(obj, dict) or set(obj) != _ENVELOPE_KEYS:
        return False
    if obj["v"] != PROTOCOL or isinstance(obj["v"], bool) or not _valid_seq(obj["seq"]):
        return False
    try:
        return len(b64d(obj["n"])) == NONCE_BYTES and len(b64d(obj["c"])) >= TAG_BYTES
    except CryptoError:
        return False


def envelope_seq(envelope: Mapping[str, Any]) -> int:
    if not is_envelope(envelope):
        raise CryptoError("invalid_envelope", "Ungültiger Umschlag.")
    return int(envelope["seq"])


def _aad(direction: str, method: str, path: str, device_id: str, seq: int) -> bytes:
    if direction not in _DIRECTIONS:
        raise ValueError(direction)
    return f"zeit-mobile/2|{direction}|{method}|{path}|{device_id}|{seq}".encode("utf-8")


def seal(key: bytes, *, direction: str, method: str, path: str, device_id: str, seq: int,
         plaintext: bytes, nonce: bytes | None = None) -> dict[str, Any]:
    """Verschlüsselt `plaintext`. `nonce` nur für die Testvektoren; sonst zufällig."""
    if not _valid_seq(seq):
        raise ValueError(seq)
    nonce = os.urandom(NONCE_BYTES) if nonce is None else nonce
    cipher = AESGCM(key).encrypt(nonce, plaintext, _aad(direction, method, path, device_id, seq))
    return {"v": PROTOCOL, "seq": seq, "n": b64e(nonce), "c": b64e(cipher)}


def open_envelope(key: bytes, envelope: object, *, direction: str, method: str, path: str,
                  device_id: str, seq: int | None = None) -> bytes:
    """Entschlüsselt. `seq=None`: der Zähler aus dem Umschlag (Server, Anfrage); sonst
    muss er dem erwarteten entsprechen (Handy, Antwort: der Zähler der Anfrage)."""
    if not is_envelope(envelope):
        raise CryptoError("invalid_envelope", "Ungültiger Umschlag.")
    assert isinstance(envelope, dict)
    actual = int(envelope["seq"])
    if seq is not None and actual != seq:
        raise CryptoError("decrypt_failed", "Die Nachricht konnte nicht entschlüsselt werden.")
    try:
        return AESGCM(key).decrypt(b64d(envelope["n"]), b64d(envelope["c"]),
                                   _aad(direction, method, path, device_id, actual))
    except InvalidTag:
        raise CryptoError("decrypt_failed", "Die Nachricht konnte nicht entschlüsselt werden.") from None
