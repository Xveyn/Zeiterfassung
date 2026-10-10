# Handy-Erfassung: Ende-zu-Ende-Verschlüsselung (#249) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Die Nutzdaten zwischen PWA und Desktop (`POST /v1/pair`, `POST /v1/sync`, Antworten und Fehler danach) laufen nicht mehr im Klartext durchs WLAN. Ein Mithörer sieht weder Einträge, Kategorien noch das (erneuerte) Gerätetoken; Wiedereinspielen und Manipulation werden erkannt. Das Klartext-Token im Header bleibt, wird aber ohne den Schlüssel wertlos.

**Architecture:** Ein langer Kopplungscode (28 Zeichen, ≈139 Bit) ersetzt den 8-Zeichen-Einmalcode; er steht im QR-Link und lässt sich notfalls abtippen. Aus ihm werden per HKDF zwei Schlüssel für die **Kopplung** abgeleitet (AES-256-GCM): Anfrage `{protocol, device_id, device_name}` verschlüsselt, Antwort mit Token **und einem frischen zufälligen Geräteschlüssel** `k_dev` verschlüsselt. Der Code taucht nie im Netz auf; ein Mitgeschnittener (oder später abfotografierter) Code öffnet keinen Abgleich, weil der Abgleich mit `k_dev` läuft. `k_dev` liegt am Handy in IndexedDB und am Desktop **im Schlüsselbund des Betriebssystems** (Windows Credential Manager / macOS Keychain / Linux Secret Service); nur wenn keiner verfügbar ist, steht er in `mobile_keys.json` (gehärtet: 0600 unter Linux/macOS, ACL unter Windows). Jede Abgleich-Anfrage ist ein Umschlag `{v:2, seq, n, c}` (Nonce, Chiffretext+Tag); Zusatzdaten (AAD) binden Richtung, Methode, Pfad, Geräte-ID und Zähler. Der Zähler `seq` steigt je Gerät streng monoton (Replay-Schutz ohne Uhr). Fehler **nach** erfolgreichem Entschlüsseln gehen ebenfalls verschlüsselt zurück.

**Tech Stack:** Python (`cryptography`: `AESGCM`, `HKDF`), JavaScript (WebCrypto `subtle`), gemeinsame Testvektoren.

**Spec:** `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md` (wird in Task 6 um „Verschlüsselung" ergänzt); Issue #249 (Überlegungen und offene Punkte); Entscheidungen von Sven am 10.10.2026: kein Release vor diesen Fixes, Variante a (langer Kopplungscode zum Abtippen), HTTPS-Auslieferung durch den Desktop bleibt offen (eigener Plan).

**Branching:** `feat/pwa-verschluesselung` vom aktuellen `master` (nach Merge von #274). PR gegen `master`, `Refs #221` und `Refs #249`; **kein** `Closes` (Fallback A bleibt offen), kein Versionsbump. Der Deploy der PWA (Pages) läuft nach dem Merge automatisch; der Desktop-Server und die PWA ändern sich **gemeinsam** — ein alter, noch gecachter PWA-Stand bekommt `invalid_protocol` und zeigt „App-Versionen passen nicht zusammen" mit „Neu laden".

## Rulings aus der Planung

- **Verpflichtend, kein Klartext-Fallback.** Es gibt noch kein Release; ein Klartext-Weg wäre toter Code mit Downgrade-Risiko. Klartext-Anfragen an `/v1/pair` und `/v1/sync` bekommen `400 invalid_protocol`. Heute gekoppelte (Test-)Handys haben keinen Schlüssel und bekommen `401 encryption_required` → „neu koppeln"; eine Migration entfällt.
- **Ein langer Code statt Code plus Schlüssel (Variante a).** `CODE_LENGTH = 28` aus dem 31-Zeichen-Alphabet (≈139 Bit), angezeigt in Gruppen zu vier (`K7M2-9QXA-…`). Er ist zugleich Gast-Passwort und Schlüsselmaterial der Kopplung. Die Fehlversuch-Sperre (5) und die 5 Minuten bleiben (Schutz gegen Störung, nicht gegen Raten).
- **`k_dev` ist zufällig und kommt in der verschlüsselten Kopplungsantwort**, statt aus dem Code abgeleitet zu werden: Ein abfotografierter oder aus dem Mitschnitt gelesener Code entschlüsselt dann später keinen Abgleich (Schlüsselhygiene). Preis: der Desktop muss `k_dev` speichern (nächster Punkt).
- **`k_dev` liegt im OS-Schlüsselbund, die Datei ist nur Fallback** (Entscheidung von Sven am 10.10.2026; Muster wie `token.json`, `webhooks.json`, SMTP über `keyring_store`). Der Schlüsselbund-Eintrag heißt `mobile:<device_id>` (`keyring_store.put/fetch/remove`, ein Service je Eintrag). `mobile_keys.json` ist die Ablage der **Orte**: je Gerät `{"location": "keyring"}` oder `{"location": "file", "key": "<base64url>"}`. Sie wird gehärtet geschrieben (`secure_file`: `chmod 0600` unter Linux/macOS, `icacls` unter Windows) und nur beim Koppeln, Umziehen, Widerrufen und Aufräumen — nie je Abgleich (die Token-Hashes und `last_seq` liegen in `mobile_devices.json`, die bei jedem Abgleich geschrieben wird).
- **Der heiße Pfad fasst den Schlüsselbund nie an.** `MobileKeyStore.get(device_id)` liest nur einen **Speicher-Cache** (kein Blockieren, kein Prompt, kein Watchdog unter `devices_lock`). Gefüllt wird er (a) beim Laden aus der Datei (Fallback-Schlüssel sofort), (b) durch `load()` im Worker nach dem Serverstart aus dem Schlüsselbund, (c) beim Koppeln. Fehlt ein Schlüsselbund-Schlüssel noch oder war er nicht lesbar (`fetch` → `None`, gesperrter Schlüsselbund, KWallet-Prompt), antwortet der Server `503 key_unavailable` (die PWA versucht es später erneut, Art `transient`) und stößt ein gedrosseltes Nachladen im Hintergrund an (`request_load`, höchstens alle 60 s je Gerät). Ein Schlüsselbund-Aufruf kann so nie eine Anfrage oder die Gerätesperre blockieren.
- **Koppeln schreibt zuerst in die Datei, der Umzug in den Schlüsselbund folgt im Worker** (wie `secret_migration` beim Start): `put` legt den Schlüssel im Cache und mit `location: "file"` in der gehärteten Datei ab (schnell, die Antwort an das Handy wartet nicht auf einen Schlüsselbund-Prompt); danach (`ctx.on_paired`, im Worker) `migrate()`: `keyring_store.put` → `fetch` und vergleichen → erst bei Übereinstimmung Datei auf `location: "keyring"` ohne Schlüssel umschreiben. Jeder Abbruch davor lässt die Datei gültig; der nächste Start holt nach. Preis: der Schlüssel liegt nach dem Koppeln kurz (Sekunden) in der gehärteten Datei; ohne Schlüsselbund dauerhaft (dann sagt der Tab das: „Schlüssel in Datei (kein Schlüsselbund verfügbar)").
- **Widerruf und Aufräumen:** `remove(device_id)` entfernt Cache, Dateieintrag und Schlüsselbund-Eintrag (blockiert → nur im Worker; `MobileService.revoke/revoke_all` laufen schon dort). `apply()` ruft `retain(bekannte Geräte-IDs)`: Schlüssel zu Geräten, die der Store nicht mehr kennt, werden abgeräumt. `MobileStore.prune` hat heute keinen Aufrufer; wer es einführt, ruft danach `retain`. Deinstallation: `secret_migration.forget_all` räumt `mobile:<id>` aller Geräte mit `location: "keyring"` ab (sonst bliebe nach `--forget-secrets` ein Eintrag zurück, Regel aus `src/CLAUDE.md`); ein `grep` auf `forget_all` ist der Beleg.
- **Schlüssel am Handy:** roh (base64url) in `meta.key` in IndexedDB, neben dem Token (gleiche Origin, gleiche Schutzwirkung). Nicht-extrahierbare `CryptoKey`-Objekte wären eine Härtung, aber Token und Code liegen ohnehin im selben Speicher; nicht Teil dieses PRs.
- **Zähler statt Zeitfenster:** `seq` (ganze Zahl ≥ 1), serverseitig `last_seq` im Gerätedatensatz (`mobile_devices.json`, kein Geheimnis). Das Handy legt `seq` **vor** dem Senden durable ab (kein Wiederverwenden nach Absturz). Server: `seq <= last_seq` → `409 replay`. Ging nur die Antwort verloren, sendet das Handy beim nächsten Versuch einfach einen höheren Zähler (der Merge ist idempotent). Ein Wiederherstellen des Speichers (Zähler zurück) heißt neu koppeln. Die Handy-Uhr spielt keine Rolle.
- **`last_seq` wird bei jedem erfolgreich entschlüsselten Umschlag gespeichert**, auch wenn danach ein Fehler (`422`, `409 clock_skew`, `503 busy`) folgt. Ein Mitschnitt eines fehlgeschlagenen, gültig entschlüsselten Pakets lässt sich so nicht noch einmal einspielen. Gespeichert wird zusammen mit der Token-Erneuerung (ein Schreibvorgang je Anfrage, wie bisher).
- **Fehler:** Alles, was **vor** dem Entschlüsseln entschieden wird (Tore, `401 token_*`, `invalid_protocol`, `invalid_envelope`, `403 invalid_code`, `429 pairing_locked`, `401 encryption_required`, `409 replay`, `400 decrypt_failed`), bleibt Klartext-JSON wie bisher: es verrät nichts außer dem Grund. Fehler **nach** erfolgreichem Entschlüsseln (`SyncError` aus `mobile_sync`, `_MobileError` im Handler) gehen als Umschlag `{"error": {code, message}}` mit demselben HTTP-Status zurück, damit `invalid_entry` (nennt den Tag) nicht mitgelesen wird. Die PWA öffnet jede Fehlerantwort, die ein Umschlag ist.
- **`/v1/categories` entfällt.** Die PWA nutzt es nicht (die Kategorien kommen in der Sync-Antwort); mit dem Token allein ließe es sich im Klartext abfragen. `/v1/ping` bleibt (Version, Serverzeit, Fenster: unkritisch).
- **Protokollversion 2:** `PROTOCOL = 2` an beiden Enden; der Pfad bleibt `/v1/…`, der Umschlag trägt `"v": 2`. Der Zusatz kommt ohne neuen Header und ohne neuen Content-Type aus (CORS und Tore unverändert).
- **Abhängigkeit:** `cryptography` ist heute nur transitiv da (Pflicht von `google-auth`); wir nutzen es jetzt direkt und pinnen es in `requirements.txt` und `requirements-test.txt` (3.12-Gegencheck, Wheels für Windows/macOS-arm/Linux). Ob PyInstaller es im gefrorenen Build vollständig bündelt, klärt erst der Pre-Release; Punkt kommt in #267.
- **Nicht in diesem PR:** Forward Secrecy (ECDH je Anfrage), nicht-extrahierbare Schlüssel am Handy, Schlüsselbund-Ablage, HTTPS vom Desktop (#249 „Alternative"), Firefox/iOS (#275).

## Global Constraints

- Ein Klartext darf nach der Kopplung nie mehr durch `/v1/pair` oder `/v1/sync` gehen; ein Test sucht in den Antworten des echten Servers nach Token, Tagen und Kategorien.
- Der heiße Pfad (`POST /v1/sync`) ruft nie `keyring_store`; ein Test ersetzt `keyring_store` durch eine Funktion, die jeden Aufruf als Fehler wertet, und lässt einen Abgleich laufen.
- Kein Schlüssel, Code, Token oder Klartext in Logs (`log.*`, `console.*`); der Test aus PR 7 für `console.*` bleibt, für Python kommt ein Test auf `mobile_routes`/`mobile_crypto` (kein `log`-Aufruf nennt `key`, `code`, `token`).
- AES-256-GCM, 96-Bit-Nonce **zufällig je Nachricht**, 128-Bit-Tag; HKDF-SHA-256 mit leerem Salt; keine eigene Kryptografie jenseits dieser Bausteine.
- `seq` ist eine JSON-Zahl ≤ 2⁵³−1 (JS-sicher).
- Vergleichbare Antwortlaufzeit: jede abgelehnte Kopplung ist dieselbe `403 invalid_code`.
- Python: `ruff check .` und `pyright 1.1.411` sauber; `mobile_crypto`, `mobile_keys` kommen in die Whitelist von `tests/test_type_annotations.py` (vollständig annotiert).
- JS: keine Abhängigkeit, kein Build; `node --test` grün.

## Review Focus

1. **Nonce-/Schlüssel-Wiederverwendung:** je Nachricht frische Zufalls-Nonce; Anfrage- und Antwortschlüssel getrennt (Reflexionsangriff: eine mitgeschnittene Anfrage lässt sich nicht als Antwort einspielen). Task 1 und 4.
2. **AAD-Bindung:** Methode, Pfad, Geräte-ID, Zähler und Richtung sind gebunden; ein auf `/v1/ping` oder an ein anderes Gerät umgeleiteter Umschlag scheitert. Task 1, 3.
3. **Replay:** gleicher `seq` zweimal, kleinerer `seq`, `seq` aus einer fremden Kopplung; Zähler wird auch bei Folgefehlern gespeichert. Task 3.
4. **Downgrade und Altbestand:** Klartext-Body, Umschlag mit `v: 1`, Gerät ohne Schlüssel, widerrufenes Gerät mit altem Schlüssel. Task 3.
5. **Kopplung:** falscher Schlüssel zählt als Fehlversuch und ist von „kein Code aktiv" nicht zu unterscheiden; Code wird nur bei erfolgreichem Entschlüsseln und gültigem Inhalt verbraucht; `k_dev` erreicht das Handy nur verschlüsselt. Task 2, 3.
6. **Schlüssel im Ruhezustand:** im Schlüsselbund, wo es einen gibt; Fallback-Datei gehärtet (0600/ACL) und nach erfolgreichem Umzug **ohne** Schlüssel; Umzug schreibt erst nach erfolgreichem Zurücklesen um; nie im Log; bei Widerruf, Aufräumen und Deinstallation (`forget_all`, Entfernen-Funktion) abgeräumt; ein hängender oder gesperrter Schlüsselbund blockiert weder Anfragen noch die Gerätesperre (nur `503 key_unavailable`). Task 2, 3, 5.
7. **Fehlerpfade in der PWA:** `decrypt`/`replay`/`encryption_required` führen zu „neu koppeln" (kein Dauerfeuer, `needsRepair`), nicht zu „Desktop nicht erreichbar"; lokale Einträge bleiben. Task 4.
8. **Gleichlauf Python/JS:** gemeinsame Vektoren für HKDF, AAD, Verschlüsselung, Umschlag. Task 1, 4.

---

### Task 1: `mobile_crypto.py`, Testvektoren, Abhängigkeit

**Files:**
- Create: `src/mobile_crypto.py`, `tests/test_mobile_crypto.py`, `pwa/test/fixtures/crypto-vectors.json`
- Modify: `requirements.txt`, `requirements-test.txt`, `CONTRIBUTING.md` (Abhängigkeitentabelle), `tests/test_type_annotations.py` (Whitelist)

**Interfaces — Produces:**
`PROTOCOL = 2`; `CryptoError(code: str, message: str)` mit `code ∈ {"invalid_envelope", "decrypt_failed"}`; `b64e(bytes) -> str`, `b64d(str) -> bytes` (wirft `CryptoError("invalid_envelope")`, strikt: nur `A-Za-z0-9_-`, kein Padding, kanonisch); `derive_key(secret: bytes, label: str) -> bytes`; `pair_keys(code: str) -> tuple[bytes, bytes]` (Anfrage, Antwort); `device_keys(key: bytes) -> tuple[bytes, bytes]`; `new_device_key() -> bytes` (32 Zufallsbytes); `is_envelope(obj: object) -> bool`; `envelope_seq(envelope: Mapping) -> int` (wirft `CryptoError`); `seal(key, *, direction, method, path, device_id, seq, plaintext, nonce=None) -> dict`; `open_envelope(key, envelope, *, direction, method, path, device_id, seq=None) -> bytes`; `seal_json(...)`-Hilfe für Dicts.

- [ ] **Step 1: Abhängigkeit prüfen und pinnen**

Run: `pip index versions cryptography 2>/dev/null | head -2; pip show cryptography | grep -E "^Version"`; auf PyPI `requires_python` und cp312-Wheels für Windows, macOS arm64 und Linux x86_64 prüfen (`curl -s https://pypi.org/pypi/cryptography/json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['info']['requires_python'], d['info']['version'])"`). Die neueste Version nehmen, die 3.12 unterstützt **und** zu `google-auth` passt (`pip install --dry-run` im venv gegen `requirements.txt`). Eintragen: `cryptography==<X.Y.Z>` in `requirements.txt` und `requirements-test.txt`; Tabelle in `CONTRIBUTING.md`: `| cryptography | AES-GCM und HKDF für die Verschlüsselung der Handy-Erfassung (vorher nur transitiv über google-auth) |`.
Expected: die Pins sind gesetzt; `python3 -c "import cryptography; print(cryptography.__version__)"` zeigt die gepinnte Version (lokal ggf. `pip install --target` in den Scratchpad wie bei segno, PEP 668).

- [ ] **Step 2: Failing tests**

Create `tests/test_mobile_crypto.py`:

```python
# tests/test_mobile_crypto.py
import json
import pathlib

import pytest

from src import mobile_crypto as mc

VECTORS = json.loads((pathlib.Path(__file__).resolve().parent.parent
                      / "pwa" / "test" / "fixtures" / "crypto-vectors.json").read_text("utf-8"))
KEY = bytes(range(32))
KW = dict(direction="req", method="POST", path="/v1/sync", device_id="phone-0001", seq=7)


def sealed(plaintext=b'{"a":1}', **over):
    return mc.seal(KEY, plaintext=plaintext, **{**KW, **over})


def test_round_trip_and_envelope_shape():
    envelope = sealed()
    assert set(envelope) == {"v", "seq", "n", "c"}
    assert envelope["v"] == 2 and envelope["seq"] == 7
    assert mc.open_envelope(KEY, envelope, **{k: v for k, v in KW.items() if k != "seq"}) == b'{"a":1}'


def test_every_message_gets_a_fresh_nonce():
    assert len({sealed()["n"] for _ in range(200)}) == 200


@pytest.mark.parametrize("field,value", [("direction", "res"), ("method", "GET"),
                                         ("path", "/v1/ping"), ("device_id", "phone-0002")])
def test_aad_binds_direction_method_path_and_device(field, value):
    envelope = sealed()
    args = {k: v for k, v in KW.items() if k != "seq"}
    args[field] = value
    with pytest.raises(mc.CryptoError) as excinfo:
        mc.open_envelope(KEY, envelope, **args)
    assert excinfo.value.code == "decrypt_failed"


def test_aad_binds_the_sequence_number():
    envelope = sealed()
    envelope["seq"] = 8
    with pytest.raises(mc.CryptoError) as excinfo:
        mc.open_envelope(KEY, envelope, **{k: v for k, v in KW.items() if k != "seq"})
    assert excinfo.value.code == "decrypt_failed"


def test_a_flipped_bit_in_the_ciphertext_or_nonce_fails():
    for field in ("c", "n"):
        envelope = sealed()
        raw = bytearray(mc.b64d(envelope[field]))
        raw[0] ^= 1
        envelope[field] = mc.b64e(bytes(raw))
        with pytest.raises(mc.CryptoError):
            mc.open_envelope(KEY, envelope, **{k: v for k, v in KW.items() if k != "seq"})


def test_a_wrong_key_fails():
    with pytest.raises(mc.CryptoError) as excinfo:
        mc.open_envelope(bytes(32), sealed(), **{k: v for k, v in KW.items() if k != "seq"})
    assert excinfo.value.code == "decrypt_failed"


@pytest.mark.parametrize("bad", [
    None, [], "x", {}, {"v": 2}, {"v": 1, "seq": 1, "n": "A" * 16, "c": "A" * 40},
    {"v": 2, "seq": 0, "n": "A" * 16, "c": "A" * 40}, {"v": 2, "seq": True, "n": "A" * 16, "c": "A" * 40},
    {"v": 2, "seq": 2 ** 53, "n": "A" * 16, "c": "A" * 40}, {"v": 2, "seq": 1.5, "n": "A" * 16, "c": "A" * 40},
    {"v": 2, "seq": 1, "n": "AAAA", "c": "A" * 40}, {"v": 2, "seq": 1, "n": "A" * 16, "c": "AAAA"},
    {"v": 2, "seq": 1, "n": "A" * 16, "c": "A" * 40, "x": 1},
    {"v": 2, "seq": 1, "n": "A" * 15 + "=", "c": "A" * 40},
    {"v": 2, "seq": 1, "n": "A" * 16, "c": "A!" * 20},
])
def test_malformed_envelopes_are_refused_before_decrypting(bad):
    assert not mc.is_envelope(bad)
    with pytest.raises(mc.CryptoError) as excinfo:
        mc.open_envelope(KEY, bad, direction="req", method="POST", path="/v1/sync", device_id="d" * 8)
    assert excinfo.value.code == "invalid_envelope"


def test_base64url_is_strict():
    assert mc.b64d(mc.b64e(bytes(range(40)))) == bytes(range(40))
    for text in ("AA==", "A", "AA AA", "AA+/", "é"):
        with pytest.raises(mc.CryptoError):
            mc.b64d(text)


def test_request_and_response_keys_differ_and_depend_on_the_secret():
    request, response = mc.device_keys(KEY)
    assert request != response and len(request) == len(response) == 32
    assert mc.device_keys(bytes(32)) != (request, response)
    pair_request, pair_response = mc.pair_keys("K7M29QXA" * 3 + "K7M2")
    assert pair_request != pair_response and pair_request != request


def test_a_request_cannot_be_replayed_as_a_response():
    request_key, response_key = mc.device_keys(KEY)
    envelope = mc.seal(request_key, plaintext=b"x", **KW)
    with pytest.raises(mc.CryptoError):
        mc.open_envelope(response_key, envelope, **{**{k: v for k, v in KW.items() if k != "seq"}, "direction": "res"})


def test_new_device_keys_are_random_32_bytes():
    keys = {mc.new_device_key() for _ in range(50)}
    assert len(keys) == 50 and all(len(k) == 32 for k in keys)


def test_vectors_match_what_python_computes():
    # Dieselbe Datei prüft pwa/test/crypto.test.js: Gleichlauf der beiden Sprachen.
    code = VECTORS["code"]
    pair_request, pair_response = mc.pair_keys(code)
    assert pair_request.hex() == VECTORS["pair_request_key"]
    assert pair_response.hex() == VECTORS["pair_response_key"]
    request, response = mc.device_keys(bytes.fromhex(VECTORS["device_key"]))
    assert request.hex() == VECTORS["request_key"] and response.hex() == VECTORS["response_key"]
    for case in VECTORS["cases"]:
        key = bytes.fromhex(case["key"])
        envelope = mc.seal(key, direction=case["direction"], method=case["method"], path=case["path"],
                           device_id=case["device_id"], seq=case["seq"],
                           plaintext=case["plaintext"].encode("utf-8"), nonce=bytes.fromhex(case["nonce"]))
        assert envelope == case["envelope"]
        assert mc.open_envelope(key, case["envelope"], direction=case["direction"], method=case["method"],
                                path=case["path"], device_id=case["device_id"]) == case["plaintext"].encode("utf-8")
```

Run: `python3 -m pytest tests/test_mobile_crypto.py -q -p no:cacheprovider -x`
Expected: FAIL (`ModuleNotFoundError: src.mobile_crypto`).

- [ ] **Step 3: Implement**

Create `src/mobile_crypto.py`:

```python
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
```

Run (Vektoren fehlen noch → erst erzeugen):

```
python3 - <<'E'
import json, pathlib
from src import mobile_crypto as mc
code = "K7M29QXA" * 3 + "K7M2"
dev = bytes(range(32))
pr, ps = mc.pair_keys(code); rq, rs = mc.device_keys(dev)
def case(key, direction, method, path, device_id, seq, plaintext, nonce):
    env = mc.seal(key, direction=direction, method=method, path=path, device_id=device_id, seq=seq,
                  plaintext=plaintext.encode(), nonce=nonce)
    return dict(key=key.hex(), direction=direction, method=method, path=path, device_id=device_id, seq=seq,
                plaintext=plaintext, nonce=nonce.hex(), envelope=env)
v = dict(code=code, pair_request_key=pr.hex(), pair_response_key=ps.hex(), device_key=dev.hex(),
         request_key=rq.hex(), response_key=rs.hex(), cases=[
    case(pr, "req", "POST", "/v1/pair", "-", 1, '{"protocol":2,"device_id":"phone-0001","device_name":"Pixel"}', bytes(range(12))),
    case(rq, "req", "POST", "/v1/sync", "phone-0001", 7, '{"entries":{},"last_pull_at":""}', bytes(range(12, 24))),
    case(rs, "res", "POST", "/v1/sync", "phone-0001", 7, '{"token":"x","entries":{"2026-10-07":{"slots":[{"start":"08:00","end":"12:00","pause":0,"kategorie":"Ä ü ß"}]}}}', bytes(range(24, 36))),
])
pathlib.Path("pwa/test/fixtures/crypto-vectors.json").write_text(json.dumps(v, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
E
```

(`seq` im Pair-Fall ist 1: die Kopplung nutzt Zähler 1, Geräte-ID `-`; die Antwort bindet die echte Geräte-ID und Zähler 1.) Dann `python3 -m pytest tests/test_mobile_crypto.py -q -p no:cacheprovider`; Expected: PASS. Whitelist in `tests/test_type_annotations.py` um `src/mobile_crypto.py` ergänzen.

- [ ] **Step 4: Commit** (`feat(mobile): Ende-zu-Ende-Verschlüsselung — Kryptobausteine und Testvektoren (#249)`)

---

### Task 2: Kopplungscode, Gerätedatensatz, Schlüsselspeicher

**Files:**
- Modify: `src/mobile_pairing.py`, `src/mobile_store.py`, `src/secure_file.py`, `src/secret_migration.py`, `src/removal.py`, `installer.iss`, `.gitignore`, `src/main.py` (Store bauen), `tests/test_mobile_pairing.py`, `tests/test_mobile_store.py`, `tests/test_secret_migration.py`, `tests/test_removal.py`, `tests/test_mobile_wiring.py`, `tests/test_type_annotations.py`
- Create: `src/mobile_keys.py`, `tests/test_mobile_keys.py`

**Interfaces — Produces:** `mobile_pairing.CODE_LENGTH = 28`; `format_code` gruppiert zu vier (`K7M2-9QXA-…`, 7 Gruppen); `PairingSession.try_open(attempt: Callable[[str], T | None]) -> tuple[RedeemResult, T | None]`; Datensatzfeld `last_seq: int` (Standard 0; `issue_device` setzt 0; `renew` ändert es nicht; neu: `mobile_pairing.with_seq(record, seq) -> Record`). `secure_file.write_secret_json(path, obj, *, prefix)` (gehärtet atomar, wie `smtp_store._save_to_disk`). `MobileKeyStore(filepath)`:
- `get(device_id) -> bytes | None` — **nur Cache**, nie blockierend.
- `put(device_id, key: bytes)` — Cache + Datei (`location: "file"`), schnell, wirft `OSError`/`MobileKeysReadOnly`.
- `load() -> bool` — **blockiert** (Worker): füllt den Cache für alle Geräte mit `location: "keyring"` über `keyring_store.fetch`; bricht beim ersten Timeout/Fehler (`None`) ab und liefert `False`.
- `request_load(device_id)` — nicht blockierend: stößt (höchstens alle 60 s je Gerät) einen Daemon-Thread an, der den einen Schlüssel nachlädt.
- `migrate() -> int` — **blockiert** (Worker): zieht `location: "file"`-Schlüssel in den Schlüsselbund (`put` → `fetch` vergleichen → Datei umschreiben); Anzahl der umgezogenen.
- `remove(device_id)`, `retain(device_ids)` — **blockieren** (Schlüsselbund), nur im Worker.
- `where() -> dict[str, str]` — `{device_id: "keyring" | "file"}` für den Tab.
- `MobileKeysReadOnly`.

- [ ] **Step 1: Failing tests**

`tests/test_mobile_pairing.py` (bestehende 8-Zeichen-Annahmen anpassen: `len(code) == 8` → `== mp.CODE_LENGTH`; Beispiele mit 8 Zeichen durch `mp.generate_code()` oder 28-Zeichen-Literale ersetzen) und neue Tests:

```python
def test_the_code_has_about_139_bits():
    assert mp.CODE_LENGTH == 28
    assert len(mp.generate_code()) == 28
    assert mp.format_code("K7M29QXA" * 3 + "K7M2") == "K7M2-9QXA-K7M2-9QXA-K7M2-9QXA-K7M2"


def test_try_open_consumes_the_code_only_on_success():
    clock = {"t": 0.0}
    session = PairingSession(lambda: clock["t"])
    code = mp.normalize_code(session.open())
    assert session.try_open(lambda c: None) == (mp.RedeemResult.INVALID, None)
    assert session.is_active()                                    # ein Fehlversuch verbraucht nichts
    result, value = session.try_open(lambda c: {"code": c})
    assert (result, value) == (mp.RedeemResult.OK, {"code": code})
    assert not session.is_active()
    assert session.try_open(lambda c: {"x": 1}) == (mp.RedeemResult.INVALID, None)


def test_try_open_counts_failures_and_locks_like_redeem():
    session = PairingSession(lambda: 0.0, max_failures=3)
    session.open()
    for _ in range(3):
        assert session.try_open(lambda c: None)[0] is mp.RedeemResult.INVALID
    assert session.try_open(lambda c: {"x": 1})[0] is mp.RedeemResult.LOCKED


def test_try_open_without_an_active_code_never_calls_the_attempt():
    called = []
    assert PairingSession().try_open(lambda c: called.append(c))[0] is mp.RedeemResult.INVALID
    assert called == []


def test_try_open_expired_code_is_invalid():
    clock = {"t": 0.0}
    session = PairingSession(lambda: clock["t"], ttl_seconds=10)
    session.open(); clock["t"] = 11.0
    assert session.try_open(lambda c: {"x": 1})[0] is mp.RedeemResult.INVALID


def test_devices_start_with_sequence_zero_and_with_seq_keeps_everything_else():
    record, _ = mp.issue_device("phone-0001", "Pixel", NOW)
    assert record["last_seq"] == 0
    updated = mp.with_seq(record, 5)
    assert updated["last_seq"] == 5 and {**updated, "last_seq": 0} == record
    renewed, _ = mp.renew(updated, NOW)
    assert renewed["last_seq"] == 5                               # Erneuern ändert den Zähler nicht


def test_pairing_again_resets_the_sequence():
    first, _ = mp.issue_device("phone-0001", "Pixel", NOW)
    again, _ = mp.issue_device("phone-0001", "Pixel", NOW, mp.with_seq(first, 9))
    assert again["last_seq"] == 0
```

`tests/test_mobile_store.py`: ein Datensatz mit `last_seq` wird geladen und gespeichert; fehlendes `last_seq` (Altbestand) wird zu 0; ein `last_seq` mit Typ/Wert außerhalb `0…2⁵³−1` macht den Datensatz defekt (übersprungen).

Create `tests/test_mobile_keys.py` (ein Fake-Schlüsselbund ersetzt `src.keyring_store`; die Tests lassen nie das echte System an):

```python
# tests/test_mobile_keys.py
import json
import os
import stat
import time

import pytest

from src import mobile_keys
from src.mobile_keys import MobileKeyStore, MobileKeysReadOnly

KEY = bytes(range(32))
ID = "phone-0001"


class FakeRing:
    """Ersetzt keyring_store: put/fetch/remove wie dort (fetch: None = nicht ermittelbar, "" = kein Eintrag)."""
    def __init__(self):
        self.items, self.available, self.calls = {}, True, []

    def put(self, key, value):
        self.calls.append(("put", key))
        if not self.available:
            return False
        self.items[key] = value
        return True

    def fetch(self, key):
        self.calls.append(("fetch", key))
        if not self.available:
            return None
        return self.items.get(key, "")

    def remove(self, key):
        self.calls.append(("remove", key))
        self.items.pop(key, None)


@pytest.fixture
def ring(monkeypatch):
    fake = FakeRing()
    monkeypatch.setattr(mobile_keys, "keyring_store", fake)
    return fake


def store_at(tmp_path):
    return MobileKeyStore(str(tmp_path / "mobile_keys.json"))


def file_of(tmp_path):
    return json.loads((tmp_path / "mobile_keys.json").read_text("utf-8"))


# --- put/get: Cache und Datei ----------------------------------------------------------------

def test_put_serves_from_the_cache_and_writes_the_file_first(tmp_path, ring):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    assert store.get(ID) == KEY
    assert file_of(tmp_path)["keys"][ID]["location"] == "file"
    assert ring.calls == []                                       # put berührt den Schlüsselbund nie


def test_get_never_calls_the_keyring(tmp_path, ring):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    for _ in range(5):
        store.get(ID); store.get("unknown-device")
    assert ring.calls == []


def test_a_file_key_survives_a_restart(tmp_path, ring):
    store_at(tmp_path).put(ID, KEY)
    assert store_at(tmp_path).get(ID) == KEY


def test_put_replaces_an_existing_key(tmp_path, ring):
    store = store_at(tmp_path)
    store.put(ID, KEY); store.put(ID, bytes(32))
    assert store.get(ID) == bytes(32) and store_at(tmp_path).get(ID) == bytes(32)


# --- migrate: Datei -> Schlüsselbund ----------------------------------------------------------

def test_migrate_moves_the_key_and_empties_the_file_entry(tmp_path, ring):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    assert store.migrate() == 1
    entry = file_of(tmp_path)["keys"][ID]
    assert entry == {"location": "keyring"}                       # kein Schlüssel mehr in der Datei
    assert KEY.hex() not in (tmp_path / "mobile_keys.json").read_text("utf-8")
    assert store.get(ID) == KEY and store.where() == {ID: "keyring"}
    assert ring.items["mobile:" + ID]                              # liegt unter dem erwarteten Namen


def test_migrate_keeps_the_file_when_no_keyring_is_available(tmp_path, ring):
    ring.available = False
    store = store_at(tmp_path)
    store.put(ID, KEY)
    assert store.migrate() == 0
    assert file_of(tmp_path)["keys"][ID]["location"] == "file" and store.get(ID) == KEY
    assert store.where() == {ID: "file"}


def test_migrate_rewrites_the_file_only_after_a_successful_read_back(tmp_path, ring, monkeypatch):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    monkeypatch.setattr(ring, "fetch", lambda key: "etwas-anderes")   # Zurücklesen stimmt nicht
    assert store.migrate() == 0
    assert file_of(tmp_path)["keys"][ID]["location"] == "file"


def test_migrate_is_idempotent_and_retries_later(tmp_path, ring):
    store = store_at(tmp_path)
    store.put(ID, KEY)
    ring.available = False
    assert store.migrate() == 0
    ring.available = True
    assert store.migrate() == 1 and store.migrate() == 0


# --- load: Schlüsselbund -> Cache -------------------------------------------------------------

def test_a_restart_has_no_key_until_load_runs(tmp_path, ring):
    store = store_at(tmp_path); store.put(ID, KEY); store.migrate()
    fresh = store_at(tmp_path)
    assert fresh.get(ID) is None                                  # Cache noch leer, kein Blockieren
    assert fresh.load() is True
    assert fresh.get(ID) == KEY


def test_load_stops_at_the_first_unreadable_key_and_reports_it(tmp_path, ring):
    store = store_at(tmp_path)
    for n in range(3):
        store.put(f"phone-000{n}", KEY)
    store.migrate()
    ring.available = False
    ring.calls.clear()
    fresh = store_at(tmp_path)
    assert fresh.load() is False
    assert len([c for c in ring.calls if c[0] == "fetch"]) == 1   # nicht 3 mal den Watchdog abwarten


def test_request_load_is_throttled_and_fills_the_cache_in_the_background(tmp_path, ring):
    store = store_at(tmp_path); store.put(ID, KEY); store.migrate()
    fresh = store_at(tmp_path)
    fresh.request_load(ID)
    deadline = time.time() + 2
    while fresh.get(ID) is None and time.time() < deadline:
        time.sleep(0.01)
    assert fresh.get(ID) == KEY
    ring.calls.clear()
    fresh.request_load("phone-9999"); fresh.request_load("phone-9999")
    time.sleep(0.2)
    assert len([c for c in ring.calls if c == ("fetch", "mobile:phone-9999")]) <= 1    # gedrosselt


# --- remove / retain --------------------------------------------------------------------------

def test_remove_clears_cache_file_and_keyring(tmp_path, ring):
    store = store_at(tmp_path); store.put(ID, KEY); store.migrate()
    store.remove(ID)
    assert store.get(ID) is None and ID not in file_of(tmp_path)["keys"]
    assert "mobile:" + ID not in ring.items


def test_remove_an_unknown_device_is_not_an_error(tmp_path, ring):
    store_at(tmp_path).remove("phone-9999")


def test_retain_drops_keys_of_unknown_devices_everywhere(tmp_path, ring):
    store = store_at(tmp_path)
    store.put("a" * 8, KEY); store.put("b" * 8, KEY); store.migrate()
    store.retain(["a" * 8])
    assert store.get("a" * 8) == KEY and store.get("b" * 8) is None
    assert "mobile:" + "b" * 8 not in ring.items and "mobile:" + "a" * 8 in ring.items


# --- Datei: Härtung, Fehler, Fremddaten -------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="POSIX-Rechte")
def test_the_file_is_private_and_atomic(tmp_path, ring):
    store_at(tmp_path).put(ID, KEY)
    path = tmp_path / "mobile_keys.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["mobile_keys.json"]     # keine Temp-Reste


def test_the_hardening_helper_runs_for_every_write(tmp_path, ring, monkeypatch):
    calls = []
    monkeypatch.setattr("src.secure_file.harden_windows_acl", lambda p: calls.append(p))
    store = store_at(tmp_path)
    store.put(ID, KEY); store.migrate()
    assert len(calls) == 2                                         # put und Umzug schreiben die Datei


def test_a_corrupt_file_is_quarantined_and_starts_empty(tmp_path, ring):
    (tmp_path / "mobile_keys.json").write_text("{kaputt", encoding="utf-8")
    store = store_at(tmp_path)
    assert store.get(ID) is None
    assert any(p.name.startswith("mobile_keys.json.corrupt-") for p in tmp_path.iterdir())


def test_broken_entries_are_skipped_not_fatal(tmp_path, ring):
    good = "A" * 43
    (tmp_path / "mobile_keys.json").write_text(json.dumps({"schema_version": 1, "keys": {
        "phone-0001": {"location": "file", "key": "!!"}, "phone-0002": 5, "x": {"location": "file", "key": good},
        "phone-0003": {"location": "file", "key": good}, "phone-0004": {"location": "wolke"},
        "phone-0005": {"location": "keyring"}}}), encoding="utf-8")
    store = store_at(tmp_path)
    for broken in ("phone-0001", "phone-0002", "x", "phone-0004"):
        assert store.get(broken) is None and broken not in store.where()
    assert store.get("phone-0003") is not None
    assert store.where()["phone-0005"] == "keyring"


def test_a_newer_schema_makes_the_store_read_only_and_untouched(tmp_path, ring):
    original = json.dumps({"schema_version": 99, "keys": {}})
    (tmp_path / "mobile_keys.json").write_text(original, encoding="utf-8")
    store = store_at(tmp_path)
    with pytest.raises(MobileKeysReadOnly):
        store.put(ID, KEY)
    assert (tmp_path / "mobile_keys.json").read_text("utf-8") == original


def test_a_failed_write_rolls_the_memory_back(tmp_path, ring, monkeypatch):
    store = store_at(tmp_path)
    monkeypatch.setattr("os.replace", lambda a, b: (_ for _ in ()).throw(OSError("voll")))
    with pytest.raises(OSError):
        store.put(ID, KEY)
    assert store.get(ID) is None


def test_no_secret_in_the_log(tmp_path, ring, caplog):
    store = store_at(tmp_path)
    store.put(ID, KEY); store.migrate()
    ring.available = False
    store_at(tmp_path).load()
    (tmp_path / "mobile_keys.json").write_text("{kaputt", encoding="utf-8")
    store_at(tmp_path)
    secret_forms = (KEY.hex(), mobile_keys.mc.b64e(KEY) if hasattr(mobile_keys, "mc") else "AAECAwQF")
    assert not any(form in caplog.text for form in secret_forms)
```

Dazu in `tests/test_secret_migration.py`:

```python
def test_forget_all_removes_the_mobile_keys_of_every_keyring_device(tmp_path, monkeypatch):
    removed = []
    monkeypatch.setattr("src.keyring_store.remove", lambda key: removed.append(key))
    (tmp_path / "mobile_keys.json").write_text(json.dumps({"schema_version": 1, "keys": {
        "phone-0001": {"location": "keyring"},
        "phone-0002": {"location": "file", "key": "A" * 43},
        "phone-0003": {"location": "keyring"}}}), encoding="utf-8")
    secret_migration.forget_all(str(tmp_path))
    assert sorted(k for k in removed if k.startswith("mobile:")) == ["mobile:phone-0001", "mobile:phone-0003"]


def test_forget_all_survives_a_broken_mobile_keys_file(tmp_path, monkeypatch):
    monkeypatch.setattr("src.keyring_store.remove", lambda key: None)
    (tmp_path / "mobile_keys.json").write_text("{kaputt", encoding="utf-8")
    secret_migration.forget_all(str(tmp_path))                     # wirft nicht
```

Run: `python3 -m pytest tests/test_mobile_pairing.py tests/test_mobile_store.py tests/test_mobile_keys.py tests/test_secret_migration.py -q -p no:cacheprovider -x`
Expected: FAIL (`CODE_LENGTH`, `try_open`, `last_seq`, `src.mobile_keys` fehlen).

- [ ] **Step 2: Implement**

`src/mobile_pairing.py`: `CODE_LENGTH = 28`; `_MAX_RAW_CODE_LENGTH = 64`; `format_code` gruppiert zu je vier (`"-".join(code[i:i + 4] for i in range(0, len(code), 4))`); Docstrings (Einmalcode „28 Zeichen aus 31, ≈139 Bit"); `PairingSession.try_open`:

```python
    def try_open(self, attempt: Callable[[str], T | None]) -> tuple[RedeemResult, T | None]:
        """Wie `redeem`, aber der Code wird nicht verglichen, sondern **benutzt**: `attempt`
        bekommt den aktiven Code (zum Ableiten der Kopplungsschlüssel) und liefert das
        Ergebnis, oder `None`, wenn die Nachricht nicht damit zu öffnen war. Nur ein
        Ergebnis verbraucht den Code; `None` zählt als Fehlversuch (nach `max_failures`
        gesperrt). Läuft unter dem Lock: `attempt` muss kurz sein und darf nichts loggen."""
        with self._lock:
            if self._locked:
                return RedeemResult.LOCKED, None
            if not self._active_locked() or self._code is None:
                return RedeemResult.INVALID, None
            value = attempt(self._code)
            if value is not None:
                self._code = None
                self._failures = 0
                return RedeemResult.OK, value
            self._failures += 1
            if self._failures >= self._max_failures:
                self._code = None
                self._locked = True
            return RedeemResult.INVALID, None
```

(`T = TypeVar("T")`; `redeem` bleibt für bestehende Tests, wird aber nicht mehr von der Route benutzt — entfernen, wenn kein Test es mehr braucht.) `issue_device` setzt `"last_seq": 0`; `renew` kopiert und ändert es nicht; neu:

```python
def with_seq(record: Mapping[str, Any], seq: int) -> Record:
    updated: Record = dict(record)
    updated["last_seq"] = seq
    return updated
```

`src/mobile_store.py`: `_is_wellformed` lässt `last_seq` fehlen (→ beim Laden 0) oder prüft `int`, nicht `bool`, `0 ≤ x ≤ 2**53-1`; Docstring unverändert (die Datei trägt weiterhin kein Geheimnis: `last_seq` ist keins).

`src/secure_file.py`: `write_secret_json(path: str, obj: Any, *, prefix: str) -> None` mit dem Ablauf aus `smtp_store._save_to_disk` (`mkstemp` → `json.dump` → `flush`+`fsync` → `chmod 0600` → `harden_windows_acl(tmp)` → `os.replace` mit 5 Versuchen bei `PermissionError`, bei **jedem** Fehler Temp-Datei weg und weiterwerfen). Eigener kleiner Test in `tests/test_secure_file.py` (Datei existiert; sonst anlegen): Rechte 0600, Temp-Aufräumen, Härtung wird gerufen. Die bestehenden Schreiber bleiben **unverändert** (kein Refactor in diesem PR).

Create `src/mobile_keys.py` — Geräteschlüssel der Handy-Erfassung (#249). Aufbau:

```python
"""Geräteschlüssel `k_dev` der Handy-Erfassung (#249): Ablage im OS-Schlüsselbund, Datei als Fallback.

`mobile_keys.json` hält je Gerät nur den **Ort**: `{"location": "keyring"}` (der Schlüssel liegt
im Schlüsselbund unter `mobile:<device_id>`) oder `{"location": "file", "key": <base64url>}`
(Fallback: kein Schlüsselbund verfügbar, oder der Umzug steht noch aus). Gehärtet geschrieben
(`secure_file.write_secret_json`: 0600 unter Linux/macOS, ACL unter Windows) und nur beim
Koppeln, Umziehen, Widerrufen und Aufräumen — nie je Abgleich.

**Der heiße Pfad (`get`) liest nur den Speicher-Cache.** Ein Schlüsselbund-Zugriff kann bis zum
30-s-Watchdog blockieren (gesperrter Schlüsselbund, Prompt); unter der Gerätesperre oder in einem
Server-Thread darf das nie passieren. `load()` und `migrate()`, `remove()` und `retain()` blockieren
deshalb und laufen nur im Worker. Fehlt ein Schlüssel im Cache, liefert `get` `None`; der Server
antwortet dann `503 key_unavailable` und stößt `request_load` an (gedrosselt).
Eigener Lock wie `mobile_store`. Fremde oder kaputte Einträge werden übersprungen, eine kaputte
Datei wird quarantäniert, eine neuere `schema_version` macht den Store read-only. Nichts hier
loggt einen Schlüssel.
"""
```

Umsetzung: Modul-Konstanten `LOAD_RETRY_SECONDS = 60.0`; `keyring_key(device_id) = f"mobile:{device_id}"`; `import keyring_store` als Modul-Attribut `keyring_store` (die Tests ersetzen es); `_entries: dict[str, dict]` (Ort und ggf. Schlüssel), `_cache: dict[str, bytes]`, `_last_try: dict[str, float]`, ein `threading.Lock`. Konstruktor: `load_json_or_quarantine`, `schema_version` prüfen, Einträge validieren (`normalize_device_id`, Ort `keyring`/`file`, bei `file` ein base64url-Schlüssel von 43 Zeichen, der zu 32 Bytes dekodiert), `file`-Schlüssel sofort in den Cache. `put`: Cache + Eintrag `file`, `_save_locked()`; bei `OSError` den Speicher zurückrollen und weiterwerfen; ein vorhandener Schlüsselbund-Eintrag zu dieser ID wird **nicht** hier entfernt (das blockierte), sondern beim nächsten `migrate()`/`retain()` überschrieben bzw. abgeräumt — `migrate` setzt über `keyring_store.put` den neuen Wert (`put` erkennt „anderer Wert" selbst). `load`: unter dem Lock die Liste der `keyring`-Geräte lesen, **außerhalb** des Locks je Gerät `keyring_store.fetch(keyring_key(id))`; `None` → `return False` (abbrechen), `""` → Eintrag fehlt: Gerät in der Datei auf `file`-los ... (ein verlorener Schlüsselbund-Eintrag heißt: Gerät kann nicht mehr entschlüsseln) → Eintrag aus `_entries` entfernen und Datei neu schreiben, **loggen ohne Schlüssel** („Schlüssel eines Geräts fehlt im Schlüsselbund — das Handy muss neu koppeln"); sonst `b64d` → Cache. `request_load`: Drosselung über `_last_try[id]` (`time.monotonic()`), Daemon-Thread führt den einen `fetch` aus. `migrate`: je `file`-Gerät außerhalb des Locks `keyring_store.put(key_name, b64e(key))` und `fetch` vergleichen; nur bei Gleichheit unter dem Lock den Eintrag auf `keyring` setzen (Cache bleibt), Datei schreiben; Zähler zurück. `remove`: Cache/Eintrag unter dem Lock entfernen, Datei schreiben, dann außerhalb `keyring_store.remove`. `retain`: wie `remove` für jede unbekannte ID. `where()`: Kopie `{id: location}`.

`src/secret_migration.py` `forget_all`: nach den SMTP-Konten ein weiterer Block, der `mobile_keys.json` mit demselben Muster liest (`json` direkt, defensiv: kein Objekt/kein `keys` → nichts; jeder Eintrag mit `location == "keyring"` und gültiger ID → `keyring_store.remove(f"mobile:{id}")`), `try/except Exception` mit `log.warning("mobile_keys.json beim Abräumen nicht lesbar", exc_info=True)` wie die Nachbarn. Aufräum- und Installations-Listen (jeweils mit Test): `src/removal.py` `CREDENTIAL_FILES`: `"mobile_keys.json"`; `installer.iss` `[UninstallDelete]`: `Type: files; Name: "{app}\mobile_keys.json"`; `.gitignore`: `mobile_keys.json` und `mobile_keys.json.corrupt-*`; `tests/test_removal.py`: `test_the_mobile_devices_file_is_removed_and_ignored` auf beide Dateien erweitern. `src/main.py`: neben dem `MobileStore` einen `MobileKeyStore(os.path.join(base, "mobile_keys.json"))` bauen und an `App`/`MobileContext` durchreichen (Task 3 verdrahtet ihn); `tests/test_mobile_wiring.py` hält die Zeile am Quelltext fest. Whitelist in `tests/test_type_annotations.py`: `src/mobile_keys.py`.

- [ ] **Step 3: Run**: `python3 -m pytest tests/test_mobile_pairing.py tests/test_mobile_store.py tests/test_mobile_keys.py tests/test_secure_file.py tests/test_secret_migration.py tests/test_removal.py tests/test_mobile_wiring.py -q -p no:cacheprovider` → grün (die Routen-Tests, die den Kontext bauen, folgen in Task 3); `ruff check .`.

- [ ] **Step 4: Commit** (`feat(mobile): langer Kopplungscode, Geräteschlüssel im Schlüsselbund mit Datei-Fallback, Zähler am Gerätedatensatz (#249)`)

---

### Task 3: Routen, Dienst, Dev-Server

**Files:**
- Modify: `src/mobile_routes.py`, `src/mobile_service.py`, `src/mobile_sync.py` (`PROTOCOL` kommt aus `mobile_crypto`), `src/ui.py` (nur Verdrahtung des Schlüsselspeichers, falls `MobileService` ihn dort bekommt), `scripts/pwa_devserver.py`, `tests/test_mobile_routes.py`, `tests/test_mobile_service.py`, `tests/test_api_server_surface.py`, `tests/test_pwa_devserver.py`, `tests/test_mobile_wiring.py`
- Create: `tests/mobile_phone.py` (Test-Hilfe: gekoppeltes Handy als Python-Gegenstück)

**Interfaces — Produces:** `MobileContext.keys: MobileKeyStore` (Pflicht) und `MobileContext.on_paired: Callable[[], None]` (Standard: nichts; wird nach einer erfolgreichen Kopplung **außerhalb** der Locks gerufen, der Dienst startet damit `keys.migrate()` im Worker); Routen `POST /v1/pair`, `GET /v1/ping`, `POST /v1/sync` (**kein** `/v1/categories` mehr); neue Fehlercodes `invalid_envelope` (400), `decrypt_failed` (400), `replay` (409), `encryption_required` (401), `key_unavailable` (503). `MobileService.apply()` ruft nach dem Serverstart im Worker `keys.retain(bekannte IDs)`, `keys.load()` und `keys.migrate()`; `revoke(…)`/`revoke_all()` entfernen die Schlüssel (Worker).

- [ ] **Step 1: Test-Hilfe**

Create `tests/mobile_phone.py` (verwendet von Routen-, Dienst-, Contract- und Dev-Server-Tests; spiegelt das, was `pwa/sync.js` tut):

```python
# tests/mobile_phone.py
"""Ein gekoppeltes Handy auf Python-Seite für die Tests: spricht das Protokoll v2 wie die PWA."""
from __future__ import annotations

import json
from typing import Any

from src import mobile_crypto as mc

SYNC_BODY = {"protocol": mc.PROTOCOL, "client_time": "2026-10-08T12:00:00Z", "last_pull_at": "", "entries": {}}


class Phone:
    def __init__(self, device_id: str = "phone-0001", name: str = "Pixel") -> None:
        self.device_id, self.name = device_id, name
        self.key: bytes | None = None
        self.token = ""
        self.seq = 0

    # --- Kopplung -------------------------------------------------------------------------------
    def pair_request(self, code: str, *, device_id: str | None = None, name: str | None = None) -> dict[str, Any]:
        request_key, _ = mc.pair_keys(code)
        body = {"protocol": mc.PROTOCOL, "device_id": device_id or self.device_id, "device_name": name or self.name}
        return mc.seal(request_key, direction="req", method="POST", path="/v1/pair", device_id="-",
                       seq=1, plaintext=json.dumps(body).encode())

    def open_pair_response(self, code: str, envelope: dict[str, Any]) -> dict[str, Any]:
        _, response_key = mc.pair_keys(code)
        plain = mc.open_envelope(response_key, envelope, direction="res", method="POST", path="/v1/pair",
                                 device_id=self.device_id, seq=1)
        answer = json.loads(plain)
        self.token, self.key, self.seq = answer["token"], mc.b64d(answer["key"]), 0
        return answer

    # --- Abgleich -------------------------------------------------------------------------------
    def sync_request(self, body: dict[str, Any] | None = None, *, seq: int | None = None) -> dict[str, Any]:
        assert self.key is not None
        self.seq = self.seq + 1 if seq is None else seq
        request_key, _ = mc.device_keys(self.key)
        return mc.seal(request_key, direction="req", method="POST", path="/v1/sync", device_id=self.device_id,
                       seq=self.seq, plaintext=json.dumps(SYNC_BODY if body is None else body).encode())

    def open_sync_response(self, envelope: dict[str, Any]) -> dict[str, Any]:
        assert self.key is not None
        _, response_key = mc.device_keys(self.key)
        plain = mc.open_envelope(response_key, envelope, direction="res", method="POST", path="/v1/sync",
                                 device_id=self.device_id, seq=self.seq)
        answer = json.loads(plain)
        if isinstance(answer.get("token"), str):
            self.token = answer["token"]
        return answer
```

- [ ] **Step 2: Failing tests** (Routen). `tests/test_mobile_routes.py` — die Hilfen `make_env`/`add_device` bekommen `keys=MobileKeyStore(...)`; `add_device` legt zusätzlich einen Schlüssel an (`env.ctx.keys.put(...)`) und liefert ein `Phone` mit Schlüssel/Token. Alle bestehenden Pair- und Sync-Tests werden auf Umschläge umgestellt (der Inhalt der Prüfungen bleibt: dieselben Fälle, jetzt durch `Phone`). **Neue** Tests (Auszug, alle vollständig zu schreiben):

```python
# --- Verschlüsselte Kopplung ------------------------------------------------------------------

def test_pairing_is_sealed_and_returns_a_device_key_only_inside_the_envelope(env):
    code = mobile_pairing.normalize_code(env.ctx.pairing.open())
    phone = Phone()
    response = call(env, "POST", "/v1/pair", body=json.dumps(phone.pair_request(code)).encode())
    assert response.status == 200
    assert set(response.body) == {"v", "seq", "n", "c"}                    # nichts im Klartext
    raw = json.dumps(response.body)
    answer = phone.open_pair_response(code, response.body)
    assert answer["token"] not in raw and answer["key"] not in raw
    assert env.ctx.keys.get(phone.device_id) == phone.key
    record = env.ctx.devices.get(phone.device_id)
    assert record["last_seq"] == 0 and record["token_hash"] == mobile_pairing.hash_token(phone.token)

def test_a_plaintext_pair_request_is_refused_and_does_not_burn_the_code(env):
    code = mobile_pairing.normalize_code(env.ctx.pairing.open())
    body = json.dumps({"protocol": 2, "code": code, "device_id": PHONE, "device_name": "x"}).encode()
    response = call(env, "POST", "/v1/pair", body=body)
    assert (response.status, response.body["error"]["code"]) == (400, "invalid_protocol")
    assert env.ctx.pairing.is_active()

def test_a_pair_request_sealed_with_a_wrong_code_counts_as_a_failed_attempt(env):
    env.ctx.pairing.open()
    wrong = mobile_pairing.generate_code()
    response = call(env, "POST", "/v1/pair", body=json.dumps(Phone().pair_request(wrong)).encode())
    assert (response.status, response.body["error"]["code"]) == (403, "invalid_code")
    assert env.ctx.devices.get_all() == [] and env.ctx.keys.get(PHONE) is None

def test_five_wrong_pair_requests_lock_the_session(env):
    env.ctx.pairing.open()
    for _ in range(5):
        call(env, "POST", "/v1/pair", body=json.dumps(Phone().pair_request(mobile_pairing.generate_code())).encode())
    code_of_session = None  # die Sitzung ist gesperrt, auch der richtige Code scheitert
    response = call(env, "POST", "/v1/pair", body=json.dumps(Phone().pair_request(mobile_pairing.generate_code())).encode())
    assert (response.status, response.body["error"]["code"]) == (429, "pairing_locked")

def test_no_active_code_looks_exactly_like_a_wrong_code(env):
    response = call(env, "POST", "/v1/pair", body=json.dumps(Phone().pair_request(mobile_pairing.generate_code())).encode())
    assert (response.status, response.body["error"]["code"]) == (403, "invalid_code")

def test_a_pair_request_with_an_invalid_device_id_inside_does_not_burn_the_code(env):
    code = mobile_pairing.normalize_code(env.ctx.pairing.open())
    response = call(env, "POST", "/v1/pair", body=json.dumps(Phone().pair_request(code, device_id="x")).encode())
    assert response.status == 403 and env.ctx.pairing.is_active()           # zählt als Fehlversuch, Code bleibt

def test_pairing_again_creates_a_new_key_and_resets_the_counter(env):
    phone, token = add_device(env), None
    ...  # zweites Koppeln desselben device_id: neuer Schlüssel, last_seq 0, alter Schlüssel ersetzt

def test_a_malformed_envelope_is_invalid_envelope_not_a_server_error(env):
    env.ctx.pairing.open()
    for body in (b"{}", b'{"v":2}', b"[]", b"null", b"\xff", b'{"v":2,"seq":1,"n":"x","c":"y"}'):
        response = call(env, "POST", "/v1/pair", body=body)
        assert response.status in (400, 403), body

# --- Verschlüsselter Abgleich -----------------------------------------------------------------

def test_sync_round_trip_is_sealed_and_renews_the_token_inside(env):
    phone = add_device(env)
    old = phone.token
    response = call(env, "POST", "/v1/sync", body=json.dumps(phone.sync_request()).encode(), token=phone.token)
    assert response.status == 200 and set(response.body) == {"v", "seq", "n", "c"}
    assert old not in json.dumps(response.body)
    answer = phone.open_sync_response(response.body)
    assert answer["token"] != old and "entries" in answer and "categories" in answer
    assert env.ctx.devices.get(phone.device_id)["last_seq"] == phone.seq

def test_a_plaintext_sync_body_is_refused(env):
    phone = add_device(env)
    response = call(env, "POST", "/v1/sync", body=json.dumps(SYNC_BODY).encode(), token=phone.token)
    assert (response.status, response.body["error"]["code"]) == (400, "invalid_protocol")

def test_replay_of_the_same_envelope_is_refused(env):
    phone = add_device(env)
    body = json.dumps(phone.sync_request()).encode()
    assert call(env, "POST", "/v1/sync", body=body, token=phone.token).status == 200
    # das Token wurde erneuert; mit dem alten (Karenz) und dem alten Umschlag:
    again = call(env, "POST", "/v1/sync", body=body, token=phone.token)
    assert (again.status, again.body["error"]["code"]) == (409, "replay")

def test_a_lower_or_equal_sequence_number_is_refused_a_higher_one_accepted(env):
    phone = add_device(env)
    assert call(env, "POST", "/v1/sync", body=json.dumps(phone.sync_request(seq=5)).encode(), token=phone.token).status == 200
    for seq in (5, 4, 1):
        r = call(env, "POST", "/v1/sync", body=json.dumps(phone.sync_request(seq=seq)).encode(), token=phone.token)
        assert (r.status, r.body["error"]["code"]) == (409, "replay"), seq
    assert call(env, "POST", "/v1/sync", body=json.dumps(phone.sync_request(seq=6)).encode(), token=phone.token).status == 200

def test_an_envelope_for_another_device_or_path_does_not_decrypt(env):
    a, b = add_device(env), add_device(env, "phone-0002", "Zweit")
    stolen = a.sync_request()
    r = call(env, "POST", "/v1/sync", body=json.dumps(stolen).encode(), token=b.token)
    assert (r.status, r.body["error"]["code"]) == (400, "decrypt_failed")

def test_a_tampered_ciphertext_is_decrypt_failed_and_changes_nothing(env):
    phone = add_device(env)
    envelope = phone.sync_request()
    raw = bytearray(mc.b64d(envelope["c"])); raw[0] ^= 1; envelope["c"] = mc.b64e(bytes(raw))
    before = env.ctx.devices.get(phone.device_id)
    r = call(env, "POST", "/v1/sync", body=json.dumps(envelope).encode(), token=phone.token)
    assert (r.status, r.body["error"]["code"]) == (400, "decrypt_failed")
    assert env.ctx.devices.get(phone.device_id) == before                   # Zähler und Token unverändert

def test_a_device_without_a_key_must_pair_again(env):
    record, token = mobile_pairing.issue_device(PHONE, "Alt", NOW)
    env.ctx.devices.save(record)                                            # kein Schlüssel angelegt
    phone = Phone(); phone.key = bytes(32); phone.token = token
    r = call(env, "POST", "/v1/sync", body=json.dumps(phone.sync_request()).encode(), token=token)
    assert (r.status, r.body["error"]["code"]) == (401, "encryption_required")

def test_errors_after_decryption_are_sealed(env):
    phone = add_device(env)
    body = dict(SYNC_BODY, entries={"2026-10-07": {"slots": [{"start": "12:00", "end": "08:00", "pause": 0, "kategorie": ""}],
                                                  "modified_at": "2026-10-08T11:00:00Z", "deleted": False}})
    r = call(env, "POST", "/v1/sync", body=json.dumps(phone.sync_request(body)).encode(), token=phone.token)
    assert r.status == 422 and set(r.body) == {"v", "seq", "n", "c"}
    assert "2026-10-07" not in json.dumps(r.body)
    inner = json.loads(mc.open_envelope(mc.device_keys(phone.key)[1], r.body, direction="res", method="POST",
                                        path="/v1/sync", device_id=phone.device_id, seq=phone.seq))
    assert inner["error"]["code"] == "invalid_entry" and "2026-10-07" in inner["error"]["message"]

def test_the_counter_is_stored_even_when_the_sync_fails_after_decryption(env):
    phone = add_device(env)
    bad = dict(SYNC_BODY, client_time="2026-10-08T13:00:00Z")               # > 15 Minuten Abweichung
    r = call(env, "POST", "/v1/sync", body=json.dumps(phone.sync_request(bad)).encode(), token=phone.token)
    assert r.status == 409
    assert env.ctx.devices.get(phone.device_id)["last_seq"] == phone.seq
    again = call(env, "POST", "/v1/sync", body=json.dumps({"v": 2, "seq": phone.seq, **{k: v for k, v in phone.sync_request(bad, seq=phone.seq).items() if k in ("n", "c")}}).encode(), token=phone.token)
    assert again.body["error"]["code"] == "replay"

def test_the_previous_token_still_works_during_the_grace_period_with_a_valid_envelope(env):
    ...  # Verlorene Antwort: Karenz-Token plus höherer Zähler → 200 (Verhalten wie bisher)

def test_a_revoked_device_keeps_no_key(env):
    phone = add_device(env)
    ...  # service.revoke → keys.get(...) is None; sync → 401 token_revoked

def test_categories_route_is_gone(env):
    phone = add_device(env)
    r = call(env, "GET", "/v1/categories", token=phone.token)
    assert r.status == 404

def test_ping_stays_plaintext_and_reports_protocol_2(env):
    phone = add_device(env)
    r = call(env, "GET", "/v1/ping", token=phone.token)
    assert r.status == 200 and r.body["protocol"] == 2

def test_nothing_in_the_logs_names_secrets(env, caplog):
    ...  # Koppeln + Abgleich + Fehler; kein Log-Eintrag enthält Code, Token, Schlüssel (hex/b64u), Klartext-Kategorie

# --- Schlüsselbund: heißer Pfad und 503 --------------------------------------------------------

def test_the_hot_path_never_touches_the_keyring(env, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("Schlüsselbund im heißen Pfad")
    monkeypatch.setattr("src.mobile_keys.keyring_store", types.SimpleNamespace(put=boom, fetch=boom, remove=boom))
    phone = add_device(env)
    code = mobile_pairing.normalize_code(env.ctx.pairing.open())
    second = Phone("phone-0002", "Zweit")
    assert call(env, "POST", "/v1/pair", body=json.dumps(second.pair_request(code)).encode()).status == 200
    assert call(env, "POST", "/v1/sync", body=json.dumps(phone.sync_request()).encode(), token=phone.token).status == 200

def test_a_keyring_key_that_is_not_loaded_yet_is_503_and_changes_nothing(env):
    phone = add_device(env)
    env.ctx.keys.migrate()                                           # Fake-Schlüsselbund: der Schlüssel zieht um
    fresh = MobileKeyStore(str(env.keys_path))                       # Neustart: Cache leer
    env.ctx.keys = fresh                                             # in den Tests ist der Kontext veränderbar
    before = env.ctx.devices.get(phone.device_id)
    r = call(env, "POST", "/v1/sync", body=json.dumps(phone.sync_request()).encode(), token=phone.token)
    assert (r.status, r.body["error"]["code"]) == (503, "key_unavailable")
    assert env.ctx.devices.get(phone.device_id) == before            # Zähler und Token unverändert
    deadline = time.time() + 2                                       # Nachladen im Hintergrund, danach geht es
    while fresh.get(phone.device_id) is None and time.time() < deadline:
        time.sleep(0.01)
    assert call(env, "POST", "/v1/sync", body=json.dumps(phone.sync_request()).encode(), token=phone.token).status == 200

def test_on_paired_runs_after_the_pairing(env):
    seen = []
    env.ctx.on_paired = lambda: seen.append(env.ctx.keys.get("phone-0001") is not None)
    code = mobile_pairing.normalize_code(env.ctx.pairing.open())
    call(env, "POST", "/v1/pair", body=json.dumps(Phone().pair_request(code)).encode())
    assert seen == [True]                                            # Schlüssel und Datensatz sind schon da

def test_a_failing_on_paired_does_not_fail_the_pairing(env):
    def boom():
        raise RuntimeError("x")
    env.ctx.on_paired = boom
    code = mobile_pairing.normalize_code(env.ctx.pairing.open())
    assert call(env, "POST", "/v1/pair", body=json.dumps(Phone().pair_request(code)).encode()).status == 200
```

Die mit `...` markierten Tests sind vollständig auszuschreiben (Aufbau wie ihre Nachbarn); in den Ledger kommt kein Platzhalter. `tests/test_mobile_service.py` (mit dem Fake-Schlüsselbund aus Task 2): `revoke` und `revoke_all` entfernen Schlüssel aus Cache, Datei **und** Schlüsselbund (sie laufen im Worker: ein Test mit einem `run`, das den Aufruf zählt); `apply()` ruft nach dem Start `retain`, `load` und `migrate` in dieser Reihenfolge, und der Server ist da, bevor sie fertig sind (ein Test mit blockierendem Fake-`fetch`, der den Start **nicht** aufhält); ein Schlüsselbund, der beim Laden `None` liefert, lässt den Dienst trotzdem `running`; `on_paired` stößt `migrate` im Worker an; `shutdown()` wartet nicht auf einen hängenden Schlüsselbund; `pair_link` trägt den 28-Zeichen-Code. `tests/test_api_server_surface.py`: die erwarteten Routen und `Allow`-Header ohne `/v1/categories`. `tests/test_pwa_devserver.py`: der Koppel-Test benutzt `Phone`; `scripts/pwa_devserver.py` baut `MobileKeyStore` im Datenordner und gibt ihn dem Kontext, **ersetzt aber `keyring_store` durch einen Speicher-Fake** (der Dev-Server darf den Schlüsselbund des Entwicklers nie anfassen, Muster wie `demo_data.py`; ein Test legt jeden `keyring_store`-Weg auf einen Fehler und koppelt trotzdem).

Run: `python3 -m pytest tests/test_mobile_routes.py tests/test_mobile_service.py tests/test_api_server_surface.py tests/test_pwa_devserver.py -q -p no:cacheprovider -x` → FAIL.

- [ ] **Step 3: Implement** — `src/mobile_routes.py`:

```python
from src import mobile_crypto as mc
from src.mobile_keys import MobileKeyStore

# MobileContext bekommt `keys: MobileKeyStore` (Pflichtfeld, vor `base`).

def _envelope(body: bytes) -> dict[str, Any]:
    """Der Body als Umschlag. Klartext (oder ein Umschlag der falschen Version) ist
    `invalid_protocol`: die PWA zeigt dann „Versionen passen nicht zusammen"."""
    data = _json_object(body)
    if "c" not in data or data.get("v") != mc.PROTOCOL:
        raise _MobileError(400, "invalid_protocol", f"Unterstützt wird protocol {mc.PROTOCOL} (verschlüsselt).")
    if not mc.is_envelope(data):
        raise _MobileError(400, "invalid_envelope", "Ungültiger Umschlag.")
    return data


def _sealed(key_response: bytes, *, path: str, device_id: str, seq: int, payload: Mapping[str, Any],
            status: int = 200) -> ApiResponse:
    envelope = mc.seal(key_response, direction="res", method="POST", path=path, device_id=device_id, seq=seq,
                       plaintext=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return ApiResponse(status, envelope)
```

`_pair`: Reihenfolge — `_no_query`, `_envelope(body)` (Klartext → `invalid_protocol`, **ohne** den Code anzufassen), `_refuse_while_closing`, dann

```python
    def attempt(code: str):
        request_key, _ = mc.pair_keys(code)
        try:
            plain = mc.open_envelope(request_key, envelope, direction="req", method="POST",
                                     path="/v1/pair", device_id="-", seq=1)
        except mc.CryptoError:
            return None
        try:
            data = load_json_body(plain)
        except WriteError:
            return None
        if not isinstance(data, dict) or data.get("protocol") != mc.PROTOCOL:
            return None
        device_id = mobile_pairing.normalize_device_id(data.get("device_id"))
        if device_id is None:
            return None
        return {"code": code, "device_id": device_id,
                "name": mobile_pairing.clean_device_name(data.get("device_name"))}

    result, opened = ctx.pairing.try_open(attempt)
    # LOCKED → 429 pairing_locked; sonst nicht OK → 403 invalid_code (gleiche Texte wie bisher)
    with ctx.devices_lock:
        key = mc.new_device_key()
        ctx.keys.put(opened["device_id"], key)                       # Cache + gehärtete Datei, schnell; kein Schlüsselbund
        record, token = mobile_pairing.issue_device(opened["device_id"], opened["name"], ctx.now(),
                                                    ctx.devices.get(opened["device_id"]))
        ctx.devices.save(record)
    _, response_key = mc.pair_keys(opened["code"])
    return _sealed(response_key, path="/v1/pair", device_id=opened["device_id"], seq=1, payload={
        "token": token, "expires_at": record["expires_at"], "window_days": WINDOW_DAYS,
        "desktop_name": ctx.desktop_name(), "protocol": mc.PROTOCOL, "key": mc.b64e(key)})
```

(`ctx.keys.put` schlägt es fehl → `OSError` fliegt durch: 500 ohne Details, der Code ist verbraucht, der Nutzer erzeugt einen neuen. Der Code **wird nicht** in einer Variable außerhalb von `attempt` geloggt.) `_sync`: `_no_query`, Scope, `_refuse_while_closing`, `envelope = _envelope(request.body)`; unter `devices_lock`: Datensatz lesen (widerrufen → `401 token_revoked`), **Schlüssel holen** (`ctx.keys.get(record["id"])`; ist er `None`, entscheidet `record["id"] in ctx.keys.where()`: bekannt (Schlüsselbund-Schlüssel noch nicht geladen) → `ctx.keys.request_load(id)` und `503 key_unavailable` (Zähler und Token unverändert, **vor** jeder Änderung), unbekannt (Altbestand ohne Schlüssel) → `401 encryption_required`), `keep_previous = _still_valid(...)`, `mc.envelope_seq(envelope) <= record["last_seq"]` → `409 replay`; `open_envelope(request_key, …, device_id=record["id"])` → `CryptoError` → `400 decrypt_failed` (**ohne** Datensatz zu ändern); ab hier `seq` gültig, `seq_record = mobile_pairing.with_seq(record, seq)`; dann in `try`: `mobile_sync.parse_request(plain, now=now)` und `perform_sync(...)` wie bisher; bei `SyncError`/`_MobileError` → `ctx.devices.save(seq_record)` und `_sealed(response_key, …, payload={"error": {"code": exc.code, "message": exc.message}}, status=exc.status)`; bei Erfolg `renewed, token = renew(seq_record, now, keep_previous=…)`, `renewed["last_pull_at"] = …`, `devices.save(renewed)`, Antwort `_sealed(response_key, …, payload=response)` mit `token`/`expires_at` im Payload; `_notify` nach dem Lock wie bisher. In `_pair` nach dem Lock `_notify_paired(ctx)` (wie `_notify`: ein Fehler in `ctx.on_paired` wird geloggt, nicht weitergegeben). `dispatch`: der `except (_MobileError, SyncError)` bleibt für alles **vor** dem Entschlüsseln. Entfernen: `_categories` samt Route. `mobile_sync.PROTOCOL` → aus `mobile_crypto` (`PROTOCOL = 2`); `ping` meldet es.

`src/mobile_service.py`: Kontext bekommt `keys` und `on_paired` (der Dienst setzt `on_paired` auf einen Aufruf, der `keys.migrate()` über `self._run` im Worker startet). `revoke(device_id)`/`revoke_all()` (laufen im Worker): erst den Widerruf schreiben (unter `devices_lock`), **danach und außerhalb des Locks** `keys.remove(id)` bzw. `keys.retain([])` (blockiert). `apply()`: Server wie bisher starten; danach im selben Worker `keys.retain([r["id"] for r in devices.get_all()])`, `keys.load()`, `keys.migrate()` (jede Stufe in `try/except Exception` mit Log ohne Schlüssel; ein Ausfall hält den Dienst nicht auf). `MobileStore.prune` hat keinen Aufrufer — nichts zu verdrahten. `main.py`/`ui.py`: den `MobileKeyStore` aus Task 2 in den Kontext geben.

`scripts/pwa_devserver.py`: `keys=MobileKeyStore(str(data_dir / "mobile_keys.json"))`; der gedruckte Koppel-Link und „Code:" tragen den langen Code (`format_code`).

- [ ] **Step 4: Run** — die vier Dateien aus Step 2 plus `tests/test_mobile_sync.py`, `tests/test_mobile_wiring.py`, `tests/test_type_annotations.py` und die ganze Suite: `python3 -m pytest -q -p no:cacheprovider`; `ruff check .`. Expected: grün (Test für „kein Log nennt Geheimnisse" eingeschlossen).

- [ ] **Step 5: Commit** (`feat(mobile): verschlüsselte Kopplung und Abgleich im Server, /v1/categories entfällt (#249)`)

---

### Task 4: PWA — `crypto.js`, Kopplung und Abgleich

**Files:**
- Create: `pwa/crypto.js`, `pwa/test/crypto.test.js`
- Modify: `pwa/pairing.js`, `pwa/sync.js`, `pwa/store.js` (Meta-Felder `key`, `seq`), `pwa/messages.js`, `pwa/view-model.js` (nur falls `hintsModel` neue Arten braucht), `pwa/sw-core.js` (`./crypto.js` in `PRECACHE`), `pwa/test/{pairing,sync,store,messages,view-model}.test.js`, `pwa/test/fixtures/{pairing-cases,pair-request,pair-response,sync-request,sync-response,errors}.json`, `tests/test_mobile_contract.py`

**Interfaces — Produces:** `crypto.js`: `deriveKey(secretBytes, label)`, `pairKeys(code)`, `deviceKeys(keyBytes)`, `seal(keyBytes, {direction, method, path, deviceId, seq, plaintext, nonce?}) -> envelope`, `openEnvelope(keyBytes, envelope, {direction, method, path, deviceId, seq?}) -> Uint8Array`, `b64e`, `b64d`, `isEnvelope`, `CryptoFailure(code)`. `pairing.js`: `PROTOCOL = 2`, `CODE_LENGTH = 28`, Code-Regeln wie Python. `Store` Meta: `key` (base64url, `''`), `seq` (0). `SyncClient`: `pair` und `sync` über Umschläge; neue Fehlerarten `crypto` (Aktion „neu koppeln") und `encryption` (`encryption_required`).

- [ ] **Step 1: Failing tests**

`pwa/test/crypto.test.js` (Node 20 hat `globalThis.crypto.subtle`):

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { b64d, b64e, deviceKeys, isEnvelope, openEnvelope, pairKeys, seal } from '../crypto.js';

const V = JSON.parse(readFileSync(new URL('./fixtures/crypto-vectors.json', import.meta.url)));
const hex = (bytes) => Buffer.from(bytes).toString('hex');
const fromHex = (text) => new Uint8Array(Buffer.from(text, 'hex'));

test('key derivation matches the Python vectors', async () => {
  const [pr, ps] = await pairKeys(V.code);
  assert.equal(hex(pr), V.pair_request_key);
  assert.equal(hex(ps), V.pair_response_key);
  const [rq, rs] = await deviceKeys(fromHex(V.device_key));
  assert.equal(hex(rq), V.request_key);
  assert.equal(hex(rs), V.response_key);
});

test('sealing with the vector nonce gives exactly the Python envelope; Python envelopes open', async () => {
  for (const c of V.cases) {
    const key = fromHex(c.key);
    const envelope = await seal(key, { direction: c.direction, method: c.method, path: c.path, deviceId: c.device_id,
      seq: c.seq, plaintext: new TextEncoder().encode(c.plaintext), nonce: fromHex(c.nonce) });
    assert.deepEqual(envelope, c.envelope);
    const plain = await openEnvelope(key, c.envelope, { direction: c.direction, method: c.method, path: c.path, deviceId: c.device_id });
    assert.equal(new TextDecoder().decode(plain), c.plaintext);
  }
});

test('fresh random nonces', async () => { /* 200 Umschläge, alle n verschieden */ });
test('aad binds direction, method, path, device and sequence', async () => { /* je Feld abweichend → CryptoFailure decrypt_failed */ });
test('flipped bits in nonce or ciphertext fail', async () => { /* … */ });
test('a response only opens with the expected request sequence', async () => { /* seq-Argument ≠ Umschlag → decrypt_failed */ });
test('malformed envelopes are refused with invalid_envelope', async () => { /* gleiche Liste wie test_mobile_crypto.py */ });
test('base64url is strict and canonical', () => { /* "AA==", "A", "AA AA", "AA+/", kanonische Form */ });
test('isEnvelope agrees with the Python rules', () => { /* Fixture-Liste gültig/ungültig */ });
```

Die mit Kommentar markierten Tests sind vollständig auszuschreiben (Muster: die Python-Tests aus Task 1). Weitere Tests:
- `pairing.test.js`: `normalizeCode` verlangt 28 Zeichen (`'K7M2-9QXA-K7M2-9QXA-K7M2-9QXA-K7M2'` gültig; 8-Zeichen-Code ungültig; Kleinschreibung/Leerzeichen egal; `0 O 1 I L` ungültig); `parseQrText`/`parsePairFragment` mit langem Code; `PROTOCOL === 2`. `pairing-cases.json` wird mit den 28-Zeichen-Fällen neu erzeugt (beide Seiten lesen sie).
- `store.test.js`: Meta kennt `key: ''`, `seq: 0`; `setMeta({key, seq})` überlebt Neuladen.
- `sync.test.js`: ein Fake-Server (Python-Seite nachgebaut mit `crypto.js`, **nicht** mit Nachbau der Server-Logik, sondern mit den Vektoren) — `pair()` sendet einen Umschlag (kein Code im Body, `JSON.stringify(body)` enthält weder den Code noch die Geräte-ID im Klartext), öffnet die Antwort, speichert `token`, `key`, `seq = 0`; `sync()` erhöht `seq` **vor** dem Senden und legt ihn durable ab (Test: Fetch wirft → `meta.seq` ist trotzdem erhöht), schickt keinen Klartext, öffnet die Antwort mit dem Zähler der Anfrage, wendet sie an; ein Fehler-Umschlag (`{error:{code,message}}`, Status 422) wird geöffnet und als `invalid_entry` mit Tag klassifiziert; Klartext-Fehler (401 `token_expired`, 400 `invalid_protocol`, 409 `replay`, 400 `decrypt_failed`, 401 `encryption_required`) werden wie bisher klassifiziert; eine Antwort mit falschem Zähler/falschem Schlüssel → `SyncError` kind `crypto`; Neukoppeln während des Abgleichs verwirft Antwort **und** Fehler weiter (`discarded`), der Zähler der alten Kopplung wird nicht in die neue übernommen.
- `messages.test.js`: `crypto` und `encryption` haben eigene Texte und Aktion `pair`, `needsRepair` gesetzt (kein Dauerfeuer, `sync-policy` blockiert automatische Auslöser).

Run: `cd pwa && node --test` → FAIL.

- [ ] **Step 2: Implement** — `pwa/crypto.js`:

```js
// pwa/crypto.js
// Gegenstück zu src/mobile_crypto.py (#249): AES-256-GCM, HKDF-SHA-256, Umschlag
// {v:2, seq, n, c}. Gleichlauf mit Python über test/fixtures/crypto-vectors.json.
// WebCrypto gibt es nur in sicheren Kontexten — die Seite kommt über https (Pages) oder von localhost.
export const PROTOCOL = 2;
const NONCE_BYTES = 12;
const TAG_BYTES = 16;
const MAX_SEQ = Number.MAX_SAFE_INTEGER;
const B64URL = /^[A-Za-z0-9_-]*$/;
const ENVELOPE_KEYS = ['c', 'n', 'seq', 'v'];

export class CryptoFailure extends Error {
  constructor(code, message) { super(message); this.name = 'CryptoFailure'; this.code = code; }
}

export function b64e(bytes) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function b64d(text) {
  if (typeof text !== 'string' || !B64URL.test(text) || text.length % 4 === 1) {
    throw new CryptoFailure('invalid_envelope', 'Ungültige Kodierung.');
  }
  const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
  if (b64e(bytes) !== text) throw new CryptoFailure('invalid_envelope', 'Ungültige Kodierung.');
  return bytes;
}

const encoder = new TextEncoder();

export async function deriveKey(secret, label) {
  const base = await crypto.subtle.importKey('raw', secret, 'HKDF', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits(
    { name: 'HKDF', hash: 'SHA-256', salt: new Uint8Array(0), info: encoder.encode(`zeit-mobile/2/${label}`) }, base, 256);
  return new Uint8Array(bits);
}

export async function pairKeys(code) {
  const secret = encoder.encode(`code:${code}`);
  return [await deriveKey(secret, 'pair/request'), await deriveKey(secret, 'pair/response')];
}

export async function deviceKeys(key) {
  return [await deriveKey(key, 'sync/request'), await deriveKey(key, 'sync/response')];
}

const validSeq = (value) => Number.isInteger(value) && value >= 1 && value <= MAX_SEQ;

export function isEnvelope(obj) {
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) return false;
  if (Object.keys(obj).sort().join() !== ENVELOPE_KEYS.join()) return false;
  if (obj.v !== PROTOCOL || !validSeq(obj.seq)) return false;
  try {
    return b64d(obj.n).length === NONCE_BYTES && b64d(obj.c).length >= TAG_BYTES;
  } catch { return false; }
}

function aad({ direction, method, path, deviceId, seq }) {
  return encoder.encode(`zeit-mobile/2|${direction}|${method}|${path}|${deviceId}|${seq}`);
}

const aesKey = (raw, usage) => crypto.subtle.importKey('raw', raw, 'AES-GCM', false, [usage]);

export async function seal(key, { direction, method, path, deviceId, seq, plaintext, nonce }) {
  if (!validSeq(seq)) throw new CryptoFailure('invalid_envelope', 'Ungültiger Zähler.');
  const iv = nonce ?? crypto.getRandomValues(new Uint8Array(NONCE_BYTES));
  const cipher = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: aad({ direction, method, path, deviceId, seq }), tagLength: 128 },
    await aesKey(key, 'encrypt'), plaintext);
  return { v: PROTOCOL, seq, n: b64e(iv), c: b64e(new Uint8Array(cipher)) };
}

export async function openEnvelope(key, envelope, { direction, method, path, deviceId, seq = null }) {
  if (!isEnvelope(envelope)) throw new CryptoFailure('invalid_envelope', 'Ungültiger Umschlag.');
  if (seq !== null && envelope.seq !== seq) throw new CryptoFailure('decrypt_failed', 'Die Nachricht passt nicht zur Anfrage.');
  try {
    const plain = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: b64d(envelope.n), additionalData: aad({ direction, method, path, deviceId, seq: envelope.seq }), tagLength: 128 },
      await aesKey(key, 'decrypt'), b64d(envelope.c));
    return new Uint8Array(plain);
  } catch (error) {
    if (error instanceof CryptoFailure) throw error;
    throw new CryptoFailure('decrypt_failed', 'Die Nachricht konnte nicht entschlüsselt werden.');
  }
}
```

`pwa/pairing.js`: `PROTOCOL = 2`, `CODE_LENGTH = 28`, `MAX_RAW_CODE_LENGTH = 64`, Kommentar zur Rolle des Codes; `pairRequestBody` liefert `{protocol, device_id, device_name}` (kein `code` mehr im Body!). `pwa/store.js`: `DEFAULT_META` um `key: ''`, `seq: 0` erweitern. `pwa/sync.js`:

```js
import { CryptoFailure, b64d, b64e, deviceKeys, isEnvelope, openEnvelope, pairKeys, seal } from './crypto.js';
// ...
const textOf = (value) => new TextEncoder().encode(JSON.stringify(value));
const jsonOf = (bytes) => JSON.parse(new TextDecoder().decode(bytes));
```

`_request` bleibt für Klartext (Ping, Fehler); neu `_sealedRequest(path, address, { token, requestKey, responseKey, deviceId, seq, payload })`:
1. Umschlag mit `seal(requestKey, { direction: 'req', method: 'POST', path, deviceId: aadDevice, seq, plaintext: textOf(payload) })` bauen, `_request('POST', path, address, { token, body: envelope })`;
2. **Erfolg:** Antwort muss ein Umschlag sein (`isEnvelope`), sonst `protocolError`; `openEnvelope(responseKey, answer, { direction: 'res', method: 'POST', path, deviceId, seq })` → `jsonOf`; `CryptoFailure` → `SyncError({ kind: 'crypto' })`;
3. **Fehlerstatus:** `_request` wirft `classifyHttpError(status, json)`; ist `json` ein Umschlag, wird er erst geöffnet und der **innere** `{error:{code,message}}` klassifiziert (`classifyHttpError` bekommt dafür den inneren Body); gelingt das Öffnen nicht → `crypto`. Dazu muss `_request` bei `!response.ok` das geparste JSON an einen Hook geben (`errorOpener`) statt sofort zu werfen.

`pair()`: `const [reqKey, resKey] = await pairKeys(normalized)`; `aadDevice = '-'`, `seq = 1`; Antwort mit `deviceId` der echten ID; Antwort-Payload validieren (wie bisher plus `key` Pflicht, base64url 43 Zeichen); `setMeta({ address, token, token_expires_at, desktop_name, window_days, key: answer.key, seq: 0 })`. `sync()`/`_run()`: Schlüssel aus `meta.key` (fehlt → `SyncError not_paired`/`encryption`); `seq = meta.seq + 1`, `await this._store.setMeta({ seq })` **vor** dem Request; `deviceKeys(b64d(meta.key))`; Payload wie bisher; Antwort wie bisher durch `parseSyncResponse` (das prüft jetzt `protocol === 2`). `ping()` bleibt Klartext (`protocol: 2` erwartet). Fehlerarten in `classifyHttpError`: `409 replay` → `crypto`, `400 decrypt_failed` → `crypto`, `401 encryption_required` → `encryption` (alle drei `needsRepair`), `400 invalid_envelope` → `protocol`, `503 key_unavailable` → `transient` (Text „Der Schlüsselbund am Rechner antwortet gerade nicht. Bitte gleich erneut versuchen.“, Aktion `retry`; kein `needsRepair`, die automatischen Auslöser laufen weiter). `pwa/messages.js`:

```js
    case 'crypto':
      return { text: 'Die Verschlüsselung zwischen Handy und Desktop passt nicht mehr (Handy oder Rechner wurden zurückgesetzt?). Bitte neu koppeln — Ihre nicht übertragenen Einträge bleiben erhalten.', action: 'pair' };
    case 'encryption':
      return { text: 'Diese Kopplung ist noch nicht verschlüsselt. Bitte neu koppeln — Ihre nicht übertragenen Einträge bleiben erhalten.', action: 'pair' };
```

`pwa/sw-core.js`: `'./crypto.js'` in `PRECACHE` (der Test aus PR 7 verlangt es). Fixtures: `pair-request.json`/`pair-response.json`/`sync-request.json`/`sync-response.json` beschreiben jetzt **die inneren Klartext-Payloads** (Form), `errors.json` bekommt die fünf neuen Paare (`400 invalid_envelope`, `400 decrypt_failed`, `409 replay`, `401 encryption_required`, `503 key_unavailable`; `invalid_protocol` bleibt).

`tests/test_mobile_contract.py` (Teile A–C): Request/Response-Form wird gegen den **echten Server** geprüft, indem der Test mit `Phone` koppelt und abgleicht und die **entschlüsselten** Payloads gegen die Fixtures vergleicht; zusätzlich ein Test, dass die Rohantworten (verschlüsselt) keine Schlüsselwörter enthalten (`token`, `entries`, `categories`); der Scanner, der alle `(Status, Code)`-Paare der Server-Quellen findet und gegen `errors.json` hält, bleibt (er findet die neuen Paare in `mobile_routes.py` und verlangt sie).

- [ ] **Step 3: Run** — `cd pwa && node --test` und `python3 -m pytest tests/test_mobile_contract.py tests/test_pwa_pages.py -q -p no:cacheprovider` und die ganze Suite; `ruff check .`. Expected: grün.

- [ ] **Step 4: Commit** (`feat(pwa): verschlüsselte Kopplung und Abgleich (#249)`)

---

### Task 5: Koppel-Dialog und PWA-Formular, Doku

**Files:**
- Modify: `src/dialogs/mobile_pair_dialog.py`, `pwa/views.js`, `pwa/app.js` (nur Textstellen), `src/dialogs/settings_dialog/tab_mobile.py` (Hinweistext), `README.md`, `docs/known-limitations.md`, `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md`, `CLAUDE.md`, `src/CLAUDE.md`, `CONTRIBUTING.md`, `tests/test_mobile_service.py`/`tests/test_tab_rules.py` (nur falls Texte geprüft werden)

- [ ] **Step 1: Koppel-Dialog** (`mobile_pair_dialog.py`): Beschriftung „Kopplungscode:" statt „Code:"; der Code erscheint in Gruppen (`format_code`, 7 Gruppen zu 4, ein Label mit `wraplength=px(…)` — nicht fest verdrahtete Pixelbreite, Regel aus `tests/test_pixel_scaling.py`); Hinweiszeile: „Der Code gilt einmal, fünf Minuten lang, und verschlüsselt die Verbindung — nur dem eigenen Handy zeigen." Der Countdown und „Neuer Code" bleiben. Kein neuer Test für Tk-Layout (Scope-Grenze); die Tk-freien Texte aus `tab_rules.py` (falls dort) bekommen ihre Tests.
- [ ] **Step 1b: Hinweis im Tab „Mobil“** (`tab_mobile.py`, Logik Tk-frei in `tab_rules.py` mit Test): unter der Geräteliste eine Zeile „Schlüsselspeicher: Schlüsselbund“ / „Datei (kein Schlüsselbund verfügbar)“ / „teils Schlüsselbund, teils Datei“, aus `keys.where()` (nur lesen, kein Schlüsselbund-Aufruf im UI-Thread); bei „Datei“ zusätzlich „nur für dein Benutzerkonto lesbar“. `tab_rules.keystore_summary(where: Mapping[str, str]) -> str` mit Tests (leer, nur `keyring`, nur `file`, gemischt).
- [ ] **Step 2: PWA-Formular** (`views.js`): Beschriftung „Kopplungscode" (Pflichtfeld), `placeholder: 'K7M2-9QXA-K7M2-9QXA-K7M2-9QXA-K7M2'`, `maxlength: 40`, Hinweiszeile: „Den Code zeigt der Desktop unter dem QR-Code. Er verschlüsselt die Verbindung." Die Fehlermeldungen (`invalid_code`, `pairing_locked`) bleiben.
- [ ] **Step 3: Doku** — Texte:
  - `README.md` („Handy-Erfassung (optional)"): Schritt 2 „… oder tippe Adresse und **Kopplungscode** (28 Zeichen, in Gruppen zu vier) ein. Der Code gilt einmal, fünf Minuten lang, und verschlüsselt die Verbindung."; „Sicherheit in Kürze" neu: „Die Verbindung im WLAN ist **nicht** per HTTPS gesichert, aber Ende-zu-Ende verschlüsselt (AES-256-GCM): wer im WLAN mitliest, sieht weder Einträge noch Kategorien noch das Gerätetoken im Klartext und kann Anfragen nicht fälschen oder wiedereinspielen. Er sieht, dass ein Handy mit deinem Rechner redet, wann und wie viel. Der Schlüssel entsteht beim Koppeln und liegt nur auf Handy und Rechner — am Rechner im Schlüsselbund des Betriebssystems, ohne Schlüsselbund in einer nur für dein Benutzerkonto lesbaren Datei." Datenspeicherung: Eintrag `mobile_keys.json` *(ab --VERSION--)*: „wo der Schlüssel eines gekoppelten Handys liegt (Schlüsselbund oder, wenn keiner verfügbar ist, die Datei selbst — dann nur für dein Benutzerkonto lesbar). Gerätelokal: reist bewusst **nicht** über den Drive-Sync mit“.
  - `docs/known-limitations.md` „Handy-Erfassung": „Klartext im LAN" ersetzen durch „**Verschlüsselt, aber nicht über HTTPS.** …": was bleibt sichtbar (Metadaten), kein Forward Secrecy (wer später den Schlüssel erbeutet, kann Mitschnitte von früher lesen), der Schlüssel liegt im Schlüsselbund des Betriebssystems; **nur ohne Schlüsselbund** (Linux ohne Secret Service, gesperrt oder nicht antwortend) steht er in `mobile_keys.json` im Klartext, lesbar für Prozesse desselben Nutzers (0600 bzw. ACL, wie `api-token`); gleich nach dem Koppeln liegt er für wenige Sekunden dort, bis der Umzug in den Schlüsselbund fertig ist; ein gesperrter Schlüsselbund lässt Abgleiche mit `503` scheitern, bis er entsperrt ist (macOS fragt nach einem App-Update erneut, vgl. den Abschnitt „Schlüsselbund“), die Origin-Aussage um den Koppel-Code verkürzen (der Code allein genügt einer fremden Pages-Seite nicht mehr: sie bräuchte ihn **und** müsste die Kopplung verschlüsselt führen — sie kann es mit dem Code), Firefox/iOS bleiben ausgesperrt (Mixed Content, #275).
  - Spec: neuer Abschnitt „Verschlüsselung (#249)" mit Kopplung, Umschlag, AAD, Zähler, Fehlerpfaden und den Rulings oben (Kurzfassung, Verweis auf diesen Plan).
  - `CLAUDE.md`: Modulliste um `src/mobile_crypto.py` und `src/mobile_keys.py` ergänzen; `src/mobile_pairing.py`/`mobile_store.py`-Einträge (Code 28 Zeichen, `last_seq`); die Aussage „Von jedem Gerätetoken nur der Hash" bleibt für `mobile_devices.json`, `mobile_keys.json` ist die einzige Klartext-Geheimnisdatei; `pwa/`-Eintrag: `crypto.js`. `src/CLAUDE.md`: `mobile_routes.py` (Umschlag, Reihenfolge, Zähler, `503 key_unavailable`), `mobile_keys.py` (Orte-Datei, Cache-only-`get`, Worker-Methoden, Umzug, `secret_migration.forget_all`, Regel „ein neues Secret braucht seinen Eintrag in `forget_all`“).
  - `CONTRIBUTING.md`: Hinweis „Kryptografie-Änderungen immer mit Testvektoren in beiden Sprachen".
  - Issue #267: Kommentar mit neuem Prüfpunkt „`cryptography` im gefrorenen Build (PyInstaller, alle drei Plattformen): Koppeln und Abgleich funktionieren, `mobile_keys.json` wird mit 0600/ACL angelegt".
- [ ] **Step 4: Run** — ganze Suite, `ruff`, `node --test`; `python scripts/resolve_readme_version.py --check` (nennt die offenen Marker, gewollt); `tests/test_claude_md_claims.py` grün.
- [ ] **Step 5: Commit** (`docs(mobile): Verschlüsselung in README, Grenzen, Spec und CLAUDE.md (#249)`)

---

## Mutationsprüfung (nach Task 5, vor dem Review)

Mutant je Zeile, mindestens ein Test muss rot werden (Skript wie `mut7.py`; nicht parallel zu anderer Arbeit am Arbeitsbaum):

| Datei | Mutation | Erwartet rot |
|---|---|---|
| `mobile_crypto.py` | Nonce konstant (`bytes(12)`) | `every message gets a fresh nonce` |
| `mobile_crypto.py` | `_aad`: `path` weglassen | `aad binds … path` |
| `mobile_crypto.py` | `_aad`: `device_id` weglassen | `aad binds … device` |
| `mobile_crypto.py` | `_aad`: `seq` weglassen | `aad binds the sequence number` |
| `mobile_crypto.py` | `device_keys` liefert zweimal denselben Schlüssel | `request and response keys differ` |
| `mobile_crypto.py` | `b64d`: kanonische Prüfung entfernen | `base64url is strict` |
| `mobile_crypto.py` | `is_envelope`: `v`-Prüfung entfernen | `malformed envelopes …` |
| `mobile_pairing.py` | `try_open`: Code bei `None` verbrauchen | `consumes the code only on success` |
| `mobile_pairing.py` | `try_open`: Fehlversuche nicht zählen | `counts failures and locks` |
| `mobile_pairing.py` | `issue_device`: `last_seq` nicht zurücksetzen | `pairing again resets the sequence` |
| `mobile_keys.py` | `retain`: nichts entfernen | `retain drops keys …` |
| `mobile_keys.py` | `write_secret_json` ohne `harden_windows_acl` | `the hardening helper runs …` |
| `mobile_routes.py` | `seq <= last_seq` → `seq < last_seq` | `replay …`, `lower or equal …` |
| `mobile_routes.py` | `last_seq` bei Folgefehlern nicht speichern | `counter is stored even when …` |
| `mobile_routes.py` | Klartext-Body zulassen | `plaintext … refused` (Pair und Sync) |
| `mobile_routes.py` | Fehler nach Entschlüsselung im Klartext senden | `errors after decryption are sealed` |
| `mobile_routes.py` | Schlüssel-Prüfung entfernen (`encryption_required`) | `device without a key …` |
| `mobile_routes.py` | `keys.get` durch ein `keyring_store.fetch` im Handler ersetzen | `the hot path never touches the keyring` |
| `mobile_routes.py` | `key_unavailable` ohne `request_load` | `… not loaded yet is 503 …` (zweiter Abgleich geht nicht mehr) |
| `mobile_routes.py` | `key_unavailable` erst nach dem Speichern von `last_seq` | `… changes nothing` |
| `mobile_keys.py` | `migrate`: Datei umschreiben **vor** dem Zurücklesen | `rewrites the file only after a successful read back` |
| `mobile_keys.py` | `migrate`: Schlüssel in der Datei lassen | `moves the key and empties the file entry` |
| `mobile_keys.py` | `get` ruft `keyring_store.fetch` bei Cache-Miss | `get never calls the keyring` |
| `mobile_keys.py` | `load`: nicht beim ersten Fehler abbrechen | `load stops at the first unreadable key` |
| `mobile_keys.py` | `remove`: Schlüsselbund-Eintrag stehen lassen | `remove clears cache file and keyring` |
| `secret_migration.py` | `forget_all`: Block für `mobile:` entfernen | `forget_all removes the mobile keys …` |
| `mobile_service.py` | `apply`: `load` vor dem Serverstart | `a blocking fetch does not delay the start` |
| `mobile_service.py` | `revoke` löscht Schlüssel nicht | `a revoked device keeps no key` |
| `crypto.js` | konstante Nonce | `fresh random nonces` |
| `crypto.js` | AAD ohne `direction` | `aad binds …` |
| `sync.js` | `seq` erst nach dem Request ablegen | `sequence is stored before sending` |
| `sync.js` | Fehler-Umschlag nicht öffnen | `sealed error is opened …` |
| `sync.js` | Antwort ohne erwarteten Zähler öffnen (`seq: null`) | `response only opens with the expected sequence` |
| `messages.js` | `crypto` ohne Aktion `pair` | `messages.test.js` |

Überlebt ein Mutant, ist das ein Testfehler: Test schärfen, gegen den Mutanten rot sehen, committen.

## Finale

Nach Task 5: ganze Suite, Mutationsprüfung, dann ein frischer Reviewer auf dem leistungsfähigsten Modell, mit Review Focus, Rulings und den Auftrag, **die Kryptografie auf Fehler zu untersuchen** (Nonce-Handling, AAD-Vollständigkeit, Reihenfolge Entschlüsseln/Zähler, Fehlerpfade, Zeitverhalten bei der Kopplung, Schlüsselablage), ausgeführte Experimente erwünscht (eigener Python-Client gegen den Dev-Server, Replay, Manipulation, Downgrade, Chrome-Browser gegen den Dev-Server mit Playwright: Koppeln über Link und manuell, Abgleich, Neukoppeln, Widerruf). Critical/Important in **einem** Durchlauf (je Fix zuerst ein roter Test), Minors ins Ledger und in ein Issue. Danach Push und PR „Verschlüsselung der Handy-Erfassung (#249)" mit `Refs #221`, `Refs #249`; Beschreibung nennt: nur zusammen deployen (Server und PWA), alte gekoppelte Test-Handys neu koppeln, Pre-Release-Punkt `cryptography` im gefrorenen Build (#267), Fallback A (HTTPS vom Desktop) bleibt offen.
