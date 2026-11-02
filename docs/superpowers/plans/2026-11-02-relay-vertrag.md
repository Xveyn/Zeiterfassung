# Relay-Vertrag (PR 2 von 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Nachtrag nach der Ausführung (2026-11-02):** Das kritische Abschluss-Review änderte den Vertrag. Maßgeblich ist die Spec (Abschnitt „Vertrag der Nutzlast (PR 2)“) und der Code; wo dieser Plan davon abweicht, steht „Nachtrag“ an der Stelle. Die Änderungen im Überblick: (1) die **Antwort** lautet `{"v":1,"status":…,"seq":…,"n":…,"body":…}`, `n` = Nonce des Anfrage-Umschlags (16 Zeichen Base64url) wird in **jeder** Antwort zurückgegeben; (2) `isCurrentResponse(frame, pendingN)` vergleicht nur `n` — die Ausnahme „`null`-`seq` ab Status 400“ entfällt, weil sie eine gefälschte 401-Antwort durchließ und `seq 1` bei Kopplung und erstem Abgleich nicht unterscheidet; (3) `encode_response(status, body, seq, n)` hat vier Parameter, dazu `encode_too_large_response(seq, n)` (413 `response_too_large`); (4) fehlt der Schlüssel `token`, lehnt der Python-Decoder ab (wie JS); (5) Fixture-Zeilen mit `canonical: true` binden die Kodierer byte-genau; (6) `./relay-frame.js` steht im `PRECACHE` von `pwa/sw-core.js`; (7) beide Seiten müssen `have` dauerhaft speichern, der Desktop nutzt das gespeicherte `last_seq`.

**Goal:** Der Vertrag zwischen Handy (PWA) und Desktop für den Abgleich über die Relay-Box steht als reine, getestete Codecs auf beiden Seiten: Nachrichtenrahmen der Box, Nutzlast `{path, token, envelope}` / `{status, seq, n, body}`, Kopplungs-Link `#relay=…` und die Regeln „veraltetes `res` verwerfen“ und „`req` mit `seq <= last_seq` nicht beantworten“. Kein Netzwerk, keine UI.

**Architecture:** Eine geteilte, handgeschriebene Fixture-Datei (`pwa/test/fixtures/relay-frames.json`) legt das Format fest; drei Implementierungen lesen sie: `relay/src/frames.js` (Referenz, nur Test), das neue `pwa/relay-frame.js` und das neue `src/mobile_relay_codec.py`. Nur das **Dekodieren** ist byte-genau gebunden (JSON-Schlüsselreihenfolge und Unicode-Escapes sind zwischen Python und JS nicht deckungsgleich), das Kodieren wird per Rundlauf mit dem eigenen Dekoder geprüft. **Nachtrag (finale Fix-Welle):** Fixture-Zeilen mit `"canonical": true` binden zusätzlich die Kodierer byte-genau (JS `encodeRequest`, Python `encode_response`); die Antwort trägt `n` (Nonce der Anfrage), `isCurrentResponse` vergleicht nur noch `n`, und `encode_too_large_response` liefert `413 response_too_large`. Maßgeblich ist die Spec, Abschnitt „Vertrag der Nutzlast (PR 2)“.

**Tech Stack:** Python 3.12 (Tk-frei, vollständig annotiert, stdlib), reines JavaScript ohne Build (`node --test`), Relay `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-02-ios-relay-abgleich-design.md` (Abschnitte „Leitidee“ Regeln 1–4, „Relay-Schnittstelle“, „PWA“, „Desktop“). Issue #358, alle Commits mit `Refs #358`.

## Global Constraints

- **Kein Gzip.** Spec und Plan 1 nannten es; die Prüfung des Codes zeigt: eine Anfrage trägt höchstens `MAX_DAYS_PER_REQUEST = 400` Tage (`pwa/sync.js:19`), das sind größenordnungsmäßig 100 KB, der Rahmen erlaubt 1 MiB. Stattdessen **Größenwächter**: Kodieren wirft `FrameTooLarge`, wenn die Nutzlast `MAX_PAYLOAD` überschreitet. Gzip kommt nur, wenn eine Messung es verlangt.
- Konstanten (auf beiden Seiten gleich, ein Test hält sie gegen `relay/src/validate.js`/`relay/CLAUDE.md`): Subprotocol `zeit.v1`; Typ-Bytes `put 0x01`, `slot 0x02`, `ok 0x03`; `ver` = 4 Byte big-endian (ohne Vorzeichen); `MAX_FRAME = 1_048_576` gilt für die **ganze** Nachricht samt Typ-Byte, also `MAX_PAYLOAD = MAX_FRAME - 1 = 1_048_575`; `PUTS_PER_MINUTE = 60`.
- Unbekannte Relay→Client-Typen und abgeschnittene `slot`/`ok` (weniger als 5 Byte) werden **ignoriert** (Dekoder liefert `None`/`null`), nie ein Fehler.
- Erlaubte Pfade der Nutzlast: genau `/v1/pair` und `/v1/sync` (Methode POST, nicht im Rahmen). `/v1/ping` gibt es im Relay-Weg nicht.
- Token im Rahmen: `null` (nur bei `/v1/pair`) oder Text aus 1–512 druckbaren ASCII-Zeichen (`[\x21-\x7e]`); ob er gültig ist, entscheidet später der Prüfer des Desktops.
- Python: Tk-freie Module vollständig annotiert (Parameter und Rückgabe) und in `ANNOTATED_MODULES` (`tests/test_type_annotations.py`); `from __future__ import annotations`, deutsche Docstrings; Catch-all-Regel (`tests/test_catch_all_handlers.py`): nur spezifische Ausnahmen fangen; Coverage-Untergrenze (`scripts/coverage_gate.py`, `FLOOR = 91.0`) zählt neue Tk-freie Module mit — also fast vollständig testen; `ruff check .` und `pyright` müssen sauber sein.
- JavaScript: reine ES-Module ohne Abhängigkeiten, Dateinamen kebab-case in `pwa/`, Tests `pwa/test/<name>.test.js` mit `node:test` + `node:assert/strict`, deutsche Kommentare; `pwa/CLAUDE.md`-Aussagen werden von `tests/test_pwa_claude_md_claims.py` geprüft (Doku mitziehen, wenn dort Dateien aufgezählt sind).
- Kein bestehender Aufrufer ändert sein Verhalten: `parseQrText`/`parsePairFragment` (LAN-Link) bleiben unverändert und lehnen `#relay=…` weiter mit `null` ab.
- Shell-Befehle ohne `&&` (PowerShell 5.1): mit `;` trennen.

## Review Focus

1. **Feindliche Nutzlasten:** kein JSON, kein Objekt, falsches `v`, Pfad außerhalb von `/v1/pair`/`/v1/sync` (`/v1/ping`, `/v1/sync?x=1`, `../x`, `https://evil`, leer), `envelope` kein Objekt, Token > 512 Zeichen oder mit Leerzeichen/Steuerzeichen, `status` außerhalb 100–599 → immer der **eigene** Fehlertyp (`FrameError`/`RelayFrameError`), nie `TypeError`/`KeyError` (Task 2, 3).
2. **Größe:** Nutzlast genau `MAX_PAYLOAD` wird kodiert, `+1` wirft `FrameTooLarge`; gezählt werden **Bytes (UTF-8)**, nicht Zeichen (Task 2, 3).
3. **`seq`-Echo:** `0`, `-1`, `"1"`, `1.5`, `true`/`True` (in Python ist `bool` ein `int`!), größer als `2^53−1` → `None`/`null`, nie eine Zahl (Task 2, 3).
4. **Veraltetes `res`:** `isCurrentResponse` ist nur `true`, wenn `frame.n` gleich der Nonce der offenen Anfrage ist (Nachtrag: ursprünglich `seq`-Vergleich mit Ausnahme für `null`-`seq` bei `status >= 400`, beides entfallen); `should_answer` ist `false` bei `seq <= last_seq` und bei ungültigem `seq` (Task 2, 3).
5. **Kopplungs-Link:** Geheimnis mit 42/44 Zeichen, Code mit verbotenen Buchstaben (`0 O 1 I L`) oder Kleinbuchstaben, zusätzliche Doppelpunkte, Leerzeichen, > 512 Zeichen → `null`; der LAN-Link `#pair=…` bleibt unverändert LAN; der Relay-Link passt in QR-Version ≤ 10 (Decoder der PWA unterstützt 1–10) (Task 4).

## File Structure

| Datei | Verantwortung |
|---|---|
| `pwa/test/fixtures/relay-frames.json` (neu) | der Vertrag: Konstanten, Nachrichten-Vektoren, Nutzlast-Fälle, Link-Fälle |
| `relay/test/frames-contract.test.js` (neu) | prüft `relay/src/frames.js` gegen die Fixture (Kreuzprobe der Referenz) |
| `pwa/relay-frame.js` (neu), `pwa/test/relay-frame.test.js` (neu) | JS-Codec: Nachrichten, Nutzlasten, Regeln |
| `pwa/pairing.js` (ändern), `pwa/test/pairing.test.js` (ändern) | `parsePairLink` (LAN oder Relay) |
| `src/mobile_relay_codec.py` (neu), `tests/test_mobile_relay_codec.py` (neu) | Python-Codec, Link-Bau, Box-Geheimnis, Regeln |
| `tests/test_mobile_contract.py`, `tests/test_type_annotations.py` (ändern) | Vertragstest bzw. Whitelist |
| `relay/CLAUDE.md`, `pwa/CLAUDE.md`, `CLAUDE.md`, Spec, `docs/datenschutz.md` (ändern) | Doku |

---

### Task 1: Der Vertrag als Fixture, Kreuzprobe mit dem Relay

**Files:**
- Create: `pwa/test/fixtures/relay-frames.json`, `relay/test/frames-contract.test.js`

**Interfaces:**
- Produces (Fixture-Form, von Tasks 2–4 gelesen):
  - `constants`: `{subprotocol: "zeit.v1", max_frame: 1048576, max_payload: 1048575, puts_per_minute: 60, types: {put: 1, slot: 2, ok: 3}}`
  - `messages`: Liste `{name, hex, decoded}` für Relay→Client-Nachrichten; `decoded` = `{kind: "slot"|"ok", ver: <int>, data_hex: <hex>|null}` oder `null` (zu ignorieren). Pflichtfälle: `ok` mit `ver 258`; `slot` mit `ver 0xFFFFFFFF` und Nutzbytes `0102`; `slot` ohne Nutzbytes; unbekannter Typ `0x09…`; leere Nachricht; `slot` mit 4 Byte (abgeschnitten); `ok` mit 3 Byte; ein Text wird in den Sprachtests getrennt geprüft.
  - `puts`: Liste `{name, payload_hex, hex}` mit `hex = "01" + payload_hex` (Pflichtfälle: leere Nutzlast, `abcdef`).
  - `requests`: Liste `{name, json, ok, path?, token?, seq?}`; `json` ist der UTF-8-Text der Nutzlast `{"v":1,"path":…,"token":…,"envelope":{…}}`; `ok: true` mit erwarteten `path`, `token`, `seq` (Echo, `null` wenn ungültig) oder `ok: false`. Pflichtfälle `ok: true`: `/v1/sync` mit Token (43 Zeichen) und Envelope `{"v":2,"seq":7,"n":"…","c":"…"}`; `/v1/pair` mit `token: null` und `seq 1`; Envelope mit `seq` `0` → `seq: null`; Envelope mit `seq: true` → `null`; Umlaute im Envelope. Pflichtfälle `ok: false`: kein JSON; JSON-Liste; `v: 2`; fehlendes `path`; Pfade `/v1/ping`, `/v1/sync?x=1`, `../v1/sync`, `https://evil/v1/sync`, `""`; `envelope` als Liste/Text/`null`; Token mit Leerzeichen, leer, 513 Zeichen; `token` fehlt.
  - `responses`: Liste `{name, json, ok, status?, seq?, body?}`; Nutzlast `{"v":1,"status":200,"seq":7,"body":{…}}`. `ok: true`: Status 200 mit Envelope-Body und `seq 7`; Status 401 mit `seq: null` und Fehlerkörper; Status 409 mit `seq 7`. `ok: false`: `status` 99/600/"200"/fehlt; `seq` 0/"7"/1.5; `body` Liste/fehlt/`null`; `v: 2`; kein JSON.
  - `links`: Liste `{url, kind, host?, port?, secret?, code?}` mit `kind` `"lan"`, `"relay"` oder `null` (ungültig). Pflichtfälle `relay`: `https://xveyn.github.io/Zeiterfassung/#relay=<43 Zeichen>:<28 Zeichen>`; nur Fragment `#relay=…`. Pflichtfälle `lan` (unverändert aus `pairing-cases.json`): `#pair=192.168.178.20:17654:<28 Zeichen>`. `null`: Geheimnis 42 bzw. 44 Zeichen; Code mit `0`, `O`, `1`, `I`, `L`; Code in Kleinbuchstaben (der Link-Parser verlangt kanonisch Großbuchstaben); drei Doppelpunkte; Leerzeichen; `#relay=` ohne Inhalt; Länge > 512; `#pair=relay:…`.
  - Das Geheimnis in allen Fällen ist ein **festes Testgeheimnis** (z. B. `Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYmE` mit exakt 43 Zeichen), keine echte Kopplung.

- [ ] **Step 1: Branch anlegen:** `git checkout master ; git pull ; git checkout -b feat/relay-vertrag`; `npm ci` in `relay/` ist erledigt, falls `node_modules` fehlt nachholen. Spec und Plan (`docs/superpowers/specs/…`, dieser Plan) in den ersten Commit dieses Branches mit aufnehmen: `git add docs/superpowers/plans/2026-11-02-relay-vertrag.md ; git commit -m "docs(relay): Plan fuer den Relay-Vertrag (PR 2 von 5) (Refs #358)"`.
- [ ] **Step 2: Failing Test** `relay/test/frames-contract.test.js`: lädt die Fixture (`../../pwa/test/fixtures/relay-frames.json` über `import.meta.url`), prüft `constants` gegen `LIMITS.maxFrame` aus `validate.js` und `FRAME` aus `frames.js` (Typ-Bytes), und für jedes `messages`/`puts`-Beispiel: `encodeSlot(ver, data)`/`encodeOk(ver)` erzeugen genau `hex` für alle Fälle mit `decoded !== null`; `decodePut(hex)` liefert `payload_hex` für `puts`. Namen: `the fixture constants match the relay`, `encodeSlot and encodeOk produce the fixture bytes`, `decodePut returns the fixture payload`.
- [ ] **Step 3: Run** `cd relay ; npm test` — Expected: FAIL (Fixture fehlt).
- [ ] **Step 4: Fixture schreiben** (Werte exakt wie oben; `hex` klein, ohne Trennzeichen; `ver` big-endian). Die Hex-Werte sind von Hand nachzurechnen, nicht aus einer der Implementierungen zu erzeugen.
- [ ] **Step 5: Run** `cd relay ; npm test` — Expected: alles PASS (die Referenz erfüllt den Vertrag).
- [ ] **Step 6: Commit:** `git add pwa/test/fixtures/relay-frames.json relay/test/frames-contract.test.js ; git commit -m "test(relay): Vertrags-Fixture fuer den Relay-Abgleich, Kreuzprobe mit dem Relay (Refs #358)"`

### Task 2: JavaScript-Codec `pwa/relay-frame.js`

**Files:**
- Create: `pwa/relay-frame.js`
- Test: `pwa/test/relay-frame.test.js`

**Interfaces:**
- Consumes: Fixture aus Task 1.
- Produces (alle Namen `export`):
  - `SUBPROTOCOL = 'zeit.v1'`, `MAX_FRAME = 1_048_576`, `MAX_PAYLOAD = MAX_FRAME - 1`, `PUTS_PER_MINUTE = 60`, `TYPE = { put: 1, slot: 2, ok: 3 }`.
  - `class RelayFrameError extends Error` mit `code` (`'invalid_frame'`, `'too_large'`).
  - `encodePut(payload: Uint8Array): Uint8Array` — Typ-Byte + Nutzlast; wirft `RelayFrameError('too_large')` bei `payload.length > MAX_PAYLOAD`.
  - `decodeMessage(data: ArrayBuffer | Uint8Array | string): {kind: 'slot', ver: number, data: Uint8Array} | {kind: 'ok', ver: number} | null` — `null` für Text, unbekannte Typen, abgeschnitten, leer; `ver` als `DataView.getUint32(1, false)`; der Rückgabewert `data` ist eine Kopie.
  - `encodeRequest({path, token, envelope}): Uint8Array` — UTF-8 von `{"v":1,"path":…,"token":…,"envelope":…}` (Reihenfolge der Schlüssel fest); prüft dieselben Regeln wie `decodeRequest`; wirft `RelayFrameError('invalid_frame')`/`('too_large')` (Größe in **Bytes**).
  - `decodeRequest(bytes: Uint8Array): {path: string, token: string | null, envelope: object, seq: number | null}` (nur für Tests und Rundlauf; der Desktop dekodiert in Python) — wirft `RelayFrameError('invalid_frame')` bei allem, was in der Fixture `ok: false` ist.
  - `decodeResponse(bytes: Uint8Array): {status: number, seq: number | null, n: string | null, body: object}` (Nachtrag: ursprünglich ohne `n`) — wirft `RelayFrameError('invalid_frame')`; `seq` gültig nur als ganze Zahl `1…Number.MAX_SAFE_INTEGER` (kein `true`, kein Text, keine Bruchzahl), sonst im **Request** `null`, im **Response** ungültig = Fehler (ein `seq` im Response ist entweder `null` oder gültig).
  - `envelopeSeq(envelope: unknown): number | null` — das gültige `seq` eines Umschlags oder `null`.
  - `isCurrentResponse(frame: {status: number, seq: number | null, n: string | null}, pendingN: string): boolean` — `pendingN` gültige Nonce und `frame.n === pendingN` (Nachtrag; ursprünglich `pendingSeq`).
  - Alle Pfade außer `/v1/pair`, `/v1/sync` sind ungültig (`PATHS = new Set([...])`); Token-Regel `/^[\x21-\x7e]{1,512}$/` oder `null`; `token` darf nur bei `/v1/pair` `null` sein.

- [ ] **Step 1: Failing tests** in `relay-frame.test.js` (Namen):
  - `constants match the fixture and the relay` (liest Fixture und `relay/src/validate.js` per Regex auf `maxFrame`/`putsPerMinute`)
  - `encodePut prefixes the type byte; empty payload is allowed; MAX_PAYLOAD is accepted and +1 throws too_large` (Review Focus 2)
  - `decodeMessage matches every fixture message (slot, ok, ignored cases)` und `decodeMessage ignores strings and never throws`
  - `decodeRequest accepts every ok:true fixture request and returns path, token, seq` / `rejects every ok:false fixture request with RelayFrameError invalid_frame` (Review Focus 1, 3)
  - `decodeResponse accepts every ok:true fixture response and rejects every ok:false one`
  - `encodeRequest then decodeRequest round-trips, counts UTF-8 bytes against MAX_PAYLOAD` (Umlaute, ein Envelope, das in Zeichen knapp, in Bytes über der Grenze liegt → `too_large`) (Review Focus 2)
  - `envelopeSeq rejects 0, -1, "1", 1.5, true, 2**53, NaN` (Review Focus 3)
  - ~~`isCurrentResponse: equal seq true, different seq false, null seq only with status >= 400`~~ (Nachtrag: ersetzt durch Tests auf `n`: gleiche `n` wahr, andere `n` falsch, `n: null` nie aktuell, zwei Antworten mit `seq 1` und verschiedener `n`) (Review Focus 4)
- [ ] **Step 2: Run** `cd pwa ; node --test test/relay-frame.test.js` — Expected: FAIL (Modul fehlt).
- [ ] **Step 3: Implement** `pwa/relay-frame.js` (reine Funktionen, `TextEncoder`/`TextDecoder`, `DataView`; keine Abhängigkeiten, kein `Buffer`).
- [ ] **Step 4: Run** `cd pwa ; node --test` — Expected: alles PASS.
- [ ] **Step 5: Commit:** `git add pwa/relay-frame.js pwa/test/relay-frame.test.js ; git commit -m "feat(pwa): Codec fuer den Relay-Abgleich (Rahmen, Nutzlast, Regeln) (Refs #358)"`

### Task 3: Python-Codec `src/mobile_relay_codec.py`

**Files:**
- Create: `src/mobile_relay_codec.py`, `tests/test_mobile_relay_codec.py`
- Modify: `tests/test_type_annotations.py` (Eintrag `"src/mobile_relay_codec.py"` in `ANNOTATED_MODULES`), `tests/test_mobile_contract.py` (ein Vertragstest, s. u.)

**Interfaces:**
- Consumes: Fixture aus Task 1.
- Produces (alle mit Annotationen, Konstanten `Final`):
  - `SUBPROTOCOL: str = "zeit.v1"`, `MAX_FRAME: int = 1_048_576`, `MAX_PAYLOAD: int = MAX_FRAME - 1`, `PUTS_PER_MINUTE: int = 60`, `TYPE_PUT = 1`, `TYPE_SLOT = 2`, `TYPE_OK = 3`.
  - `class FrameError(ValueError)` mit `code: str` (`"invalid_frame"`); `class FrameTooLarge(FrameError)` (`code == "too_large"`).
  - `@dataclass(frozen=True) class RelayMessage`: `kind: str` (`"slot"`/`"ok"`), `ver: int`, `data: bytes`.
  - `@dataclass(frozen=True) class RelayRequest`: `path: str`, `token: str | None`, `envelope: dict[str, Any]`; Eigenschaft `seq -> int | None` (über `envelope_seq`).
  - `encode_put(payload: bytes) -> bytes` (wirft `FrameTooLarge`); `decode_message(data: bytes | str) -> RelayMessage | None` (Text/unbekannt/abgeschnitten → `None`).
  - `decode_request(payload: bytes) -> RelayRequest` (wirft `FrameError` für alles `ok: false` der Fixture, **nur** `FrameError`, nie `TypeError`/`KeyError`/`UnicodeDecodeError`/`json.JSONDecodeError` nach außen); `encode_response(status: int, body: Any, seq: int | None, n: str | None) -> bytes` (UTF-8 mit `ensure_ascii=False`, `separators=(",", ":")`, Schlüsselreihenfolge `v, status, seq, n, body` — `n` ist Nachtrag; prüft `status` 100–599 und `seq` gültig/`None`; wirft `FrameTooLarge`/`FrameError`).
  - `envelope_seq(envelope: object) -> int | None` — gültig nur `int`, **nicht** `bool`, `1 <= seq <= 2**53 - 1`.
  - `should_answer(seq: int | None, last_seq: int) -> bool` — `True` nur bei gültigem `seq > last_seq`.
  - `generate_box_secret() -> str` — 43 Zeichen Base64url (`secrets.token_urlsafe(32)`), `BOX_SECRET_RE` (`^[A-Za-z0-9_-]{43}$`).
  - `relay_link(secret: str, code: str) -> str | None` — `f"{PWA_URL}#relay={secret}:{canonical_code}"`; `None`, wenn das Geheimnis nicht `BOX_SECRET_RE` entspricht oder `mobile_pairing.normalize_code(code)` `None` liefert; `PWA_URL` aus `mobile_routes.PWA_URL` importieren (`from src import mobile_routes`/dort definierte Konstante; wenn das einen Importzyklus ergäbe, die Konstante an einer gemeinsamen Stelle lesen — nicht kopieren).

- [ ] **Step 1: Failing tests** in `tests/test_mobile_relay_codec.py` (Namen), jeder liest die Fixture über den Helfer aus `tests/test_mobile_contract.py` (`load("relay-frames.json")`) bzw. denselben Pfad:
  - `test_constants_match_the_fixture_and_the_relay` (Fixture + Regex auf `relay/src/validate.js` für `maxFrame`/`putsPerMinute`, Unterstriche entfernen; rot, wenn der Regex nichts findet)
  - `test_encode_put_limits` (Review Focus 2; `MAX_PAYLOAD` ok, `+1` → `FrameTooLarge`; Bytes statt Zeichen bei Umlauten in `encode_response`)
  - `test_decode_message_matches_every_fixture_vector`, `test_decode_message_ignores_text_and_unknown_types`
  - `test_decode_request_accepts_every_ok_fixture_case` / `test_decode_request_rejects_every_bad_fixture_case_with_frame_error_only` (Review Focus 1: `pytest.raises(FrameError)` und zusätzlich: die Ausnahme ist **genau** `FrameError`/Unterklasse)
  - `test_envelope_seq_rejects_bool_zero_negative_text_float_and_huge` (Review Focus 3, inkl. `True`)
  - `test_encode_response_round_trips_with_the_fixture_response_shape` (decodiert mit `json.loads` und prüft Form; kein Byte-Vergleich mit JS)
  - `test_encode_response_rejects_bad_status_and_seq` (Nachtrag: auch `n`; `encode_response` hat vier Parameter)
  - `test_should_answer` (Review Focus 4: `seq <= last_seq` → `False`; `None` → `False`; `last_seq + 1` → `True`)
  - `test_generate_box_secret_has_43_base64url_chars_and_differs_each_time`
  - `test_relay_link_matches_every_fixture_relay_link_and_rejects_bad_ones` (Review Focus 5: für jeden `relay`-Fall aus der Fixture `relay_link(secret, code) == url`; für ungültige Geheimnisse/Codes `None`)
  - `test_relay_link_fits_qr_version_10` (`pytest.importorskip("segno")`; `len(qr.qr_matrix(link)) <= 57`)
  - In `tests/test_mobile_contract.py`: `test_the_relay_request_decoder_yields_what_dispatch_expects` — baut aus einem `ok: true`-Fall `ApiRequest("POST", request.path, {}, json.dumps(request.envelope).encode())` und prüft, dass `mobile_routes._envelope(body)` den Umschlag akzeptiert (die Naht zum bestehenden `dispatch`; kein Netzwerk).
- [ ] **Step 2: Run** `python -m pytest tests/test_mobile_relay_codec.py -q` — Expected: FAIL (Modul fehlt).
- [ ] **Step 3: Implement** `src/mobile_relay_codec.py`: stdlib (`json`, `secrets`, `re`, `struct`, `dataclasses`); `json.loads` mit Bytes → UTF-8 → `FrameError`; nur spezifische Ausnahmen fangen (`UnicodeDecodeError`, `json.JSONDecodeError`, `RecursionError` nicht fangen — Tiefe wird durch die Rahmengröße und `json`-Standardgrenze behandelt; ein tief verschachtelter Fall gehört in die Fixture, wenn er `RecursionError` auslöst: dann dort eine bewusste Entscheidung treffen und im Bericht melden). `from __future__ import annotations`.
- [ ] **Step 4: Whitelist:** `"src/mobile_relay_codec.py"` in `ANNOTATED_MODULES` eintragen.
- [ ] **Step 5: Run:** `python -m pytest tests/test_mobile_relay_codec.py tests/test_mobile_contract.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q`, danach `ruff check .` und `pyright` (oder `npx pyright`) — Expected: alles sauber.
- [ ] **Step 6: Gesamtlauf:** `python -m pytest -q` — Expected: PASS (Coverage-Untergrenze prüft die CI; lokal `python -m pytest --cov=src --cov-report=term-missing tests/test_mobile_relay_codec.py` zeigt, dass das neue Modul nahezu vollständig abgedeckt ist).
- [ ] **Step 7: Commit:** `git add src/mobile_relay_codec.py tests/test_mobile_relay_codec.py tests/test_mobile_contract.py tests/test_type_annotations.py ; git commit -m "feat(mobile): Codec fuer den Relay-Abgleich auf dem Desktop (Refs #358)"`

### Task 4: Kopplungs-Link in der PWA

**Files:**
- Modify: `pwa/pairing.js`, `pwa/test/pairing.test.js`

**Interfaces:**
- Consumes: Fixture `links` (Task 1), `normalizeCode`, `parsePairFragment`/`parseQrText` (unverändert).
- Produces: `export function parsePairLink(text: string): {kind: 'lan', host: string, port: number, code: string} | {kind: 'relay', secret: string, code: string} | null` — Länge ≤ 512; nimmt alles nach dem ersten `#`; `#relay=<43 Base64url>:<28 Zeichen Code>` → `relay` (Code **kanonisch** gemäß `normalizeCode`, aber die Eingabe muss bereits Großbuchstaben tragen, wie beim LAN-Link: Kleinbuchstaben → `null`); sonst delegiert an `parseQrText` und gibt dessen Ergebnis mit `kind: 'lan'` zurück. `parseQrText` und `parsePairFragment` bleiben unverändert.
- [ ] **Step 1: Failing tests** (`pairing.test.js`): `parsePairLink matches every fixture link (lan, relay, null)` (liest die Fixture), `parsePairLink leaves parseQrText untouched: a relay link still yields null from parseQrText`, `parsePairLink rejects longer than 512 characters`, `an LAN link keeps parsing as lan with the same host, port and code as before`.
- [ ] **Step 2: Run** `cd pwa ; node --test test/pairing.test.js` — FAIL.
- [ ] **Step 3: Implement** `parsePairLink` in `pairing.js`; Secret-Regex `/^[A-Za-z0-9_-]{43}$/` (wie `KEY_RE` in `sync.js`, nicht importieren, um keinen Zyklus zu schaffen).
- [ ] **Step 4: Run** `cd pwa ; node --test` und `python -m pytest tests/test_pwa_claude_md_claims.py -q` — PASS (falls `pwa/CLAUDE.md` Dateien aufzählt: `relay-frame.js` und `parsePairLink` dort eintragen, bis der Test grün ist).
- [ ] **Step 5: Commit:** `git add pwa/pairing.js pwa/test/pairing.test.js pwa/CLAUDE.md ; git commit -m "feat(pwa): parsePairLink erkennt LAN- und Relay-Kopplungslinks (Refs #358)"`

### Task 5: Doku und Aufräumen der Spec

**Files:**
- Modify: `docs/superpowers/specs/2026-11-02-ios-relay-abgleich-design.md`, `relay/CLAUDE.md`, `CLAUDE.md` (Struktur-Abschnitt), `pwa/CLAUDE.md`, `docs/datenschutz.md`

- [ ] **Step 1: Spec:** „Gzip“ aus Leitidee Regel 4, Budget Punkt 4 und PR-Schnitt streichen und durch den **Größenwächter** (`FrameTooLarge`, Begründung 400 Tage ≈ 100 KB) ersetzen; die Nutzlast-Formate (`{v:1, path, token, envelope}` / `{v:1, status, seq, n, body}` (Nachtrag: `n` kam nach dem Abschluss-Review dazu)), den Link `#relay=<Geheimnis>:<Code>` und `isCurrentResponse`/`should_answer` knapp beschreiben; PR 3 nennt `relay_link.py` als Netzwerk-Modul, PR 2 `mobile_relay_codec.py`/`relay-frame.js` als Vertrag.
- [ ] **Step 2: `relay/CLAUDE.md`** („Für die Clients“): ein Verweis auf `pwa/relay-frame.js`, `src/mobile_relay_codec.py` und die Fixture `pwa/test/fixtures/relay-frames.json` als Gegenstücke, plus der Satz „Konstante ändern heißt beide Codecs und die Fixture mitziehen“.
- [ ] **Step 3: `CLAUDE.md`** (Struktur): je ein Eintrag `src/mobile_relay_codec.py` und `pwa/relay-frame.js` mit einem Satz zur Rolle; Wortlaut so, dass `tests/test_claude_md_claims.py` grün bleibt.
- [ ] **Step 4: `docs/datenschutz.md`:** Abschnitt „Was der Relay sieht“ um das Gerätetoken im Rahmen ergänzen (Token liegt im Klartext der Nutzlast neben dem verschlüsselten Umschlag; der Relay kann damit nichts entschlüsseln; Token wird bei jedem Abgleich erneuert), Aussage „Gzip“ falls vorhanden entfernen.
- [ ] **Step 5: Run:** `python -m pytest tests/test_claude_md_claims.py tests/test_pwa_claude_md_claims.py tests/test_datenschutz_claims.py -q ; python -m pytest -q ; cd pwa ; node --test ; cd ../relay ; npm test` — Expected: alles PASS.
- [ ] **Step 6: Commit:** `git add -A docs relay/CLAUDE.md CLAUDE.md pwa/CLAUDE.md ; git commit -m "docs(relay): Relay-Vertrag beschrieben, Gzip gestrichen, Datenschutz ergaenzt (Refs #358)"`. Push und PR bleiben der Entscheidung des Nutzers überlassen.

---

## Self-Review

- **Spec-Abdeckung:** Rahmen und Nachrichten (Task 1–3), Nutzlast `{path, token, envelope}` inkl. Regel 4 (Task 2, 3), Regel 1 `isCurrentResponse` (Task 2), Regel 2 `should_answer` (Task 3), Regel 3 (Pair-Cache) und alles mit Netzwerk gehört bewusst in PR 3/4, Kopplungs-Link (Task 3, 4), Gzip entfällt begründet (Global Constraints, Task 5). Pflicht der Spec „Fixtures für beide Seiten“: Task 1.
- **Typkonsistenz:** `MAX_PAYLOAD = MAX_FRAME − 1` auf allen drei Seiten; `envelopeSeq`/`envelope_seq` gleiche Regeln (bool-Falle nur in Python); Fehlertypen `RelayFrameError`/`FrameError` mit `code`; Link-Form `#relay=<43>:<28>` identisch in Fixture, `relay_link` und `parsePairLink`.
- **Bekannte Risiken:** (a) JSON-Bytegleichheit zwischen Sprachen ist bewusst nicht gefordert; (b) `RecursionError` bei tief verschachteltem JSON — Task 3 nennt die Entscheidung; (c) `relay_link` braucht `PWA_URL` aus `mobile_routes` (Importzyklus prüfen); (d) QR-Version ≤ 10 gilt für den Decoder der PWA, Prüfung nur mit installiertem `segno`.
- **Proportion:** Plan ≈ Spec-Länge, Funktionskörper nur als Signaturen und Testnamen.
