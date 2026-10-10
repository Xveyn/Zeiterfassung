# tests/mobile_phone.py
"""Test-Hilfen der Handy-Erfassung (#249): ein gekoppeltes Handy auf Python-Seite, das das
Protokoll v2 spricht wie die PWA, und ein Schlüsselbund-Fake (kein Test fasst je den echten an)."""
from __future__ import annotations

import json
from typing import Any

from src import mobile_crypto as mc

SYNC_BODY: dict[str, Any] = {"protocol": mc.PROTOCOL, "client_time": "2026-10-08T12:00:00Z",
                              "last_pull_at": "", "entries": {}}


class FakeRing:
    """Ersetzt `keyring_store`: put/fetch/remove wie dort (`fetch`: `None` = nicht ermittelbar,
    `""` = kein Eintrag)."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}
        self.available = True
        self.calls: list[tuple[str, str]] = []

    def put(self, key: str, value: str) -> bool:
        self.calls.append(("put", key))
        if not self.available:
            return False
        self.items[key] = value
        return True

    def fetch(self, key: str) -> str | None:
        self.calls.append(("fetch", key))
        if not self.available:
            return None
        return self.items.get(key, "")

    def remove(self, key: str) -> None:
        self.calls.append(("remove", key))
        self.items.pop(key, None)


class Phone:
    def __init__(self, device_id: str = "phone-0001", name: str = "Pixel") -> None:
        self.device_id, self.name = device_id, name
        self.key: bytes | None = None
        self.token = ""
        self.seq = 0

    # --- Kopplung -------------------------------------------------------------------------------
    def pair_request(self, code: str, *, device_id: str | None = None, name: str | None = None,
                     protocol: Any = mc.PROTOCOL) -> dict[str, Any]:
        request_key, _ = mc.pair_keys(code)
        body = {"protocol": protocol, "device_id": device_id or self.device_id,
                "device_name": name if name is not None else self.name}
        return mc.seal(request_key, direction="req", method="POST", path="/v1/pair", device_id="-",
                       seq=1, plaintext=json.dumps(body).encode())

    def open_pair_response(self, code: str, envelope: dict[str, Any]) -> dict[str, Any]:
        _, response_key = mc.pair_keys(code)
        plain = mc.open_envelope(response_key, envelope, direction="res", method="POST",
                                 path="/v1/pair", device_id=self.device_id, seq=1)
        answer = json.loads(plain)
        self.token, self.key, self.seq = answer["token"], mc.b64d(answer["key"]), 0
        return answer

    # --- Abgleich -------------------------------------------------------------------------------
    def sync_request(self, body: dict[str, Any] | None = None, *, seq: int | None = None) -> dict[str, Any]:
        assert self.key is not None
        self.seq = self.seq + 1 if seq is None else seq
        request_key, _ = mc.device_keys(self.key)
        return mc.seal(request_key, direction="req", method="POST", path="/v1/sync",
                       device_id=self.device_id, seq=self.seq,
                       plaintext=json.dumps(SYNC_BODY if body is None else body).encode())

    def open_sync_response(self, envelope: dict[str, Any]) -> dict[str, Any]:
        """Öffnet eine Antwort (Erfolg oder verschlüsselter Fehler) zur **letzten** Anfrage."""
        assert self.key is not None
        _, response_key = mc.device_keys(self.key)
        plain = mc.open_envelope(response_key, envelope, direction="res", method="POST",
                                 path="/v1/sync", device_id=self.device_id, seq=self.seq)
        answer = json.loads(plain)
        if isinstance(answer.get("token"), str):
            self.token = answer["token"]
        return answer
