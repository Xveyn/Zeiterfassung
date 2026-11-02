# Desktop-Kern des Relay-Abgleichs (PR 3a von 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Desktop kann eine Relay-Anfrage (`req`-Nutzlast) **ohne Netzwerk und ohne Oberfläche** vollständig beantworten: ein reiner Adapter `RelayAdapter.handle(payload) -> bytes | None` bildet den Vertrag aus PR 2 auf das bestehende `mobile_routes.dispatch` ab (Kopplung mit Zwischenspeicher der Antwort, Abgleich mit Token-Prüfung und Replay-Regel, Fehlerantworten mit `n`-Echo). Dazu der Speicher für Box-Geheimnisse, das Löschen einer Box (`DELETE /v1/box`) und das Herauslösen von `PWA_URL` aus der Routenebene.

**Architecture:** Drei kleine Tk-freie Module (`pwa_constants`, `mobile_box_store`, `box_relay`) und ein Adapter (`relay_adapter`), der nur bestehende Bausteine aufruft (`mobile_relay_codec`, `mobile_routes.make_verifier`/`dispatch`, `MobileContext`). Kein Socket, kein Thread, kein Tk — die Verbindung (WebSocket, Thread, Dienst, Verdrahtung in `App`, Entfernen/Deinstallation, Abhängigkeit) ist PR 3b, die Oberfläche (Einstellungen, Koppel-Dialog) PR 3c.

**Tech Stack:** Python 3.12 (Tk-frei, vollständig annotiert, stdlib), `pytest`.

**Spec:** `docs/superpowers/specs/2026-11-02-ios-relay-abgleich-design.md` (Abschnitte „Leitidee“ Regeln 1–4, „Vertrag der Nutzlast (PR 2)“, „Desktop“, „Hinweise für PR 3 und PR 4“, „Datenschutz“). Issue #358, alle Commits `Refs #358`.

## Global Constraints

- **Nichts hier öffnet einen Socket, startet einen Thread oder importiert `tkinter`.** `box_relay` ist die einzige Ausnahme mit Netz (`urllib`, injizierbarer `opener` wie `push_relay`), und nur für `DELETE`.
- **Das Box-Geheimnis ist ein Secret:** eigene Datei `mobile_box.json`, geschrieben über `secure_file.write_secret_json` (Härtung 0600/ACL), **nicht** in `mobile_devices.json` (die wird bei jedem Abgleich ohne Härtung geschrieben) und **nicht** in `mobile_relay.json` (das ist der Push-Speicher; Push und Box tragen getrennte, unverknüpfte Geheimnisse, `MobileService._drop_relay_objects` würde ein Box-Geheimnis sonst an `DELETE /v1/device` schicken). Nie in Logs, auch nicht in Ausnahmetexten (nur Ausnahmetyp loggen, Muster `push_relay`).
- Eine neue Credential-Datei trägt sich in **alle** Listen ein: `src/removal.py` `CREDENTIAL_FILES`; `installer.iss` (`[UninstallDelete]` und `DeleteMatching('<datei>.corrupt-*')`); `.gitignore` (Datei und `.corrupt-*`); `tests/test_secret_writers.py`; dazu Doku: `README.md` (Dateiliste), `SECURITY.md`, `CONTRIBUTING.md` (Baum), root `CLAUDE.md` (Modulliste), `src/CLAUDE.md`. Die Tests `tests/test_removal.py`, `tests/test_installer.py`, `tests/test_installer_user_data.py` erzwingen das teils; jede Liste vollständig nachziehen, bis alle grün sind.
- Antworten, die der Adapter erzeugt, tragen **immer** die Nonce `n` der Anfrage (`RelayRequest.n`); ohne gültiges `n` wird **nicht geantwortet** (die Antwort wäre für das Handy wertlos: `isCurrentResponse` verlangt `n`).
- `should_answer(seq, last_seq)` mit dem **gespeicherten** `record["last_seq"]` (nie ein Zähler im Speicher); bei `/v1/pair` **keine** `seq`-Regel (Kopplung ist immer `seq 1`, ein Neu-Koppeln setzt `last_seq` zurück).
- Tk-freie Module: vollständig annotiert (Parameter und Rückgabe) und in `ANNOTATED_MODULES` (`tests/test_type_annotations.py`); `from __future__ import annotations`, deutsche Docstrings; Catch-all-Regel (`tests/test_catch_all_handlers.py`: jeder `except Exception` loggt, meldet oder trägt einen Kommentar **im** Handler); Coverage-Untergrenze `scripts/coverage_gate.py` `FLOOR = 91.0` zählt neue Tk-freie Module mit; `ruff check .` und `pyright` sauber.
- Lock-Reihenfolge `devices_lock` → `sync_guard` → `data_lock` (Docstring `mobile_routes`). Der Adapter hält selbst **keine** Sperre über `dispatch` hinweg; das Lesen von `last_seq` vor `dispatch` ist ohne Sperre erlaubt (`_sync` prüft unter der Sperre noch einmal).
- Shell-Befehle ohne `&&` (PowerShell 5.1): mit `;` trennen. Bekannter, unabhängiger Fehler: `tests/test_report_pdf_layout.py::test_the_reported_report_keeps_its_summary_on_one_page`.

## Review Focus

1. **Kopplung wiederholt:** dasselbe `req`-Byte-Paar zweimal → die **gleiche** versiegelte Antwort (kein `403 invalid_code`, der Code wird nicht ein zweites Mal verbraucht); ein **anderes** `req` (neuer Code/Nonce) wird frisch beantwortet; der Zwischenspeicher ist begrenzt (Einträge und Lebensdauer) und hält nur Erfolgsantworten (Task 3).
2. **Replay und Neustart:** `seq <= last_seq` → **keine** Antwort (`None`), nie ein `409`; `last_seq` kommt aus dem Gerätedatensatz, nicht aus dem Adapter-Zustand; ein frischer Adapter (Neustart) verhält sich wie der alte (Task 3).
3. **Feindliche Nutzlast:** nicht dekodierbare Anfrage, fehlendes/ungültiges `n`, unbekannter Pfad → `None`, nie eine Ausnahme nach außen; **jede** Ausnahme aus `dispatch` → eine `500`-Antwort mit `n` und ohne Details (Task 3).
4. **Fehlerantworten tragen `n` und lassen das Token-Verhalten des LAN-Wegs gleich:** `token_revoked`/`token_expired`/`unauthorized` als unversiegeltes `401` mit `{"error":{"code","message"}}`, `invalid_protocol`/`decrypt_failed` aus `dispatch` unverändert durchgereicht (Task 3).
5. **Zu große Antwort:** liefert `dispatch` eine Antwort, deren Kodierung `MAX_PAYLOAD` überschreitet, geht `encode_too_large_response(seq, n)` raus (die Anfrage ist bereits angewendet) (Task 3).
6. **Geheimnis-Hygiene:** weder `MobileBoxStore` noch `box_relay` noch der Adapter loggen ein Geheimnis; ein Test lenkt `logging` um und sucht nach dem Geheimnis in allen Meldungen und Ausnahmetexten (Task 2, 3, 4).
7. **Verwaiste Boxen:** `pending` wird beim Erzeugen eines neuen Codes ersetzt (das alte Geheimnis wird zurückgegeben, damit der Aufrufer es am Relay löschen kann); `retain(ids)` räumt Geräte-Einträge ohne Gerätedatensatz ab (Task 2).

## File Structure

| Datei | Verantwortung |
|---|---|
| `src/pwa_constants.py` (neu) | `PWA_ORIGIN`, `PWA_URL` — nur stdlib |
| `src/mobile_box_store.py` (neu) | Datei `mobile_box.json`: ein offenes Box-Geheimnis (`pending`) und je gekoppeltem Gerät eines (`devices`) |
| `src/box_relay.py` (neu) | `delete_box(secret, …) -> bool` (`DELETE /v1/box`), best effort, wirft nie |
| `src/relay_adapter.py` (neu) | `RelayAdapter`: `req`-Nutzlast → `res`-Nutzlast, reine Logik über `dispatch` |
| `src/mobile_routes.py`, `src/mobile_relay_codec.py`, `src/mobile_service.py` (ändern) | importieren die Konstanten aus `pwa_constants` |
| `src/removal.py`, `installer.iss`, `.gitignore`, Doku, Tests (ändern) | neue Credential-Datei in allen Listen |
| `tests/test_pwa_constants.py`, `tests/test_mobile_box_store.py`, `tests/test_box_relay.py`, `tests/test_relay_adapter.py` (neu) | Tests |

---

### Task 1: `PWA_URL` und `PWA_ORIGIN` aus der Routenebene lösen

**Files:**
- Create: `src/pwa_constants.py`, `tests/test_pwa_constants.py`
- Modify: `src/mobile_routes.py`, `src/mobile_relay_codec.py`, `src/mobile_service.py`, `tests/test_type_annotations.py`

**Interfaces:**
- Produces: `PWA_ORIGIN: str = "https://xveyn.github.io"`, `PWA_URL: str = "https://xveyn.github.io/Zeiterfassung/"` in `src/pwa_constants.py`. `mobile_routes.PWA_ORIGIN`/`PWA_URL` bleiben als Namen **erhalten** (`from src.pwa_constants import PWA_ORIGIN, PWA_URL`), damit bestehende Aufrufer und Tests (`scripts/pwa_devserver.py`, `tests/…`) unverändert laufen; `mobile_relay_codec` und `mobile_service` importieren künftig aus `pwa_constants`.

- [ ] **Step 1: Branch:** `git checkout master ; git pull ; git checkout -b feat/relay-desktop-kern`; Plan committen: `git add docs/superpowers/plans/2026-11-02-desktop-kern.md ; git commit -m "docs(relay): Plan fuer den Desktop-Kern des Relay-Abgleichs (PR 3a von 5) (Refs #358)"`.
- [ ] **Step 2: Failing tests** (`tests/test_pwa_constants.py`): `test_the_constants_have_the_documented_values` (beide Werte, `PWA_URL` beginnt mit `PWA_ORIGIN` und endet auf `/`), `test_the_module_is_stdlib_only` (Quelltext enthält kein `import` außer `__future__`/`typing`), `test_mobile_routes_and_the_codec_use_the_same_constants` (`mobile_routes.PWA_URL is pwa_constants.PWA_URL`, Codec-Modul ebenso).
- [ ] **Step 3: Run:** `python -m pytest tests/test_pwa_constants.py -q` — FAIL.
- [ ] **Step 4: Implement:** Modul anlegen; in `mobile_routes.py` die zwei Zuweisungen (`mobile_routes.py:56-57`) durch den Import ersetzen; `mobile_relay_codec` und `mobile_service` auf `pwa_constants` umstellen (kein Import von `mobile_routes` mehr im Codec — prüfen, dass `import src.mobile_relay_codec` die Routenebene nicht mehr lädt: Test `test_the_codec_does_not_import_the_route_layer` über `sys.modules` in einem Subprozess).
- [ ] **Step 5: Whitelist:** `"src/pwa_constants.py"` in `ANNOTATED_MODULES`.
- [ ] **Step 6: Run:** `python -m pytest tests/test_pwa_constants.py tests/test_mobile_relay_codec.py tests/test_mobile_service.py tests/test_mobile_routes.py tests/test_mobile_contract.py tests/test_type_annotations.py tests/test_pwa_devserver.py -q` — PASS; `ruff check .`.
- [ ] **Step 7: Commit:** `git add src tests ; git commit -m "refactor(mobile): PWA_URL und PWA_ORIGIN in ein eigenes Konstantenmodul (Refs #358)"`

### Task 2: Speicher für Box-Geheimnisse `mobile_box_store.py`

**Files:**
- Create: `src/mobile_box_store.py`, `tests/test_mobile_box_store.py`
- Modify: `src/removal.py`, `installer.iss`, `.gitignore`, `tests/test_removal.py`, `tests/test_secret_writers.py`, `tests/test_type_annotations.py`; Doku `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CLAUDE.md`, `src/CLAUDE.md`

**Interfaces:**
- Consumes: `secure_file.write_secret_json(path, obj, *, prefix=…)`, `json_store.load_json_or_quarantine`, `mobile_relay_codec.BOX_SECRET_RE`/`generate_box_secret()`; Vorbild `src/mobile_relay_store.py` (Aufbau, Sperre, Schreibweise, Schema-Prüfung — lesen und das Muster übernehmen).
- Produces: Datei `mobile_box.json` = `{"schema_version": 1, "pending": {"secret": str, "created_at": str} | null, "devices": {device_id: {"secret": str}}}`. `class MobileBoxStore(path: str | os.PathLike[str])` mit eigener `RLock`; nur bei **Änderung** schreiben (nie je Abgleich); schreibgeschützt bei neuerem Schema oder unlesbarer Datei (kaputte Datei nach `.corrupt-<stamp>` verschieben, Einträge werden mit `BOX_SECRET_RE` geprüft):
  - `open_pending(now: str) -> tuple[str, str | None]` — erzeugt über `generate_box_secret()` ein neues offenes Geheimnis, speichert es, liefert `(neues, altes_oder_None)` (das alte soll der Aufrufer am Relay löschen);
  - `pending() -> str | None`; `clear_pending() -> str | None` (liefert das entfernte Geheimnis);
  - `bind(device_id: str) -> tuple[str | None, str | None]` — verschiebt das offene Geheimnis zum Gerät; liefert `(gebundenes_geheimnis, ersetztes_altes_des_geraets_oder_None)`; ohne offenes Geheimnis `(None, None)`;
  - `get(device_id: str) -> str | None`; `known_ids() -> list[str]`; `all_secrets() -> list[str]` (offenes + gebundene, ohne Duplikate);
  - `remove(device_id: str) -> str | None`; `retain(ids: Iterable[str]) -> dict[str, str]` (entfernt Geräte-Einträge, die nicht in `ids` stehen; liefert `{device_id: secret}` der entfernten); `read_only: bool`.
  - Schreibfehler (`OSError`) rollen den Speicher zurück und werden dem Aufrufer als Ausnahme gemeldet (wie `MobileRelayStore.set`).

- [ ] **Step 1: Failing tests** (`tests/test_mobile_box_store.py`, Namen): `test_a_new_store_is_empty`, `test_open_pending_creates_a_valid_secret_and_returns_the_old_one` (Review Focus 7), `test_bind_moves_the_pending_secret_to_the_device`, `test_bind_without_pending_does_nothing`, `test_bind_returns_the_replaced_secret_when_the_device_pairs_again`, `test_remove_and_retain_return_the_removed_secrets` (Review Focus 7), `test_clear_pending`, `test_nothing_is_written_when_nothing_changes` (Schreibzähler über `monkeypatch` auf `secure_file.write_secret_json`), `test_the_file_is_written_through_write_secret_json_and_survives_a_reload`, `test_a_broken_file_is_quarantined_and_the_store_starts_empty`, `test_a_newer_schema_makes_the_store_read_only_and_never_overwrites`, `test_invalid_secrets_in_the_file_are_dropped`, `test_a_write_error_rolls_back_and_raises`, `test_no_secret_reaches_the_log` (Review Focus 6: `caplog` über alle Operationen und über einen provozierten Schreibfehler; kein Geheimnis in Meldungen/`exc_text`).
- [ ] **Step 2: Run:** `python -m pytest tests/test_mobile_box_store.py -q` — FAIL.
- [ ] **Step 3: Implement** `mobile_box_store.py` nach dem Muster von `mobile_relay_store.py`.
- [ ] **Step 4: Listen nachziehen** (Global Constraints): `CREDENTIAL_FILES`, `installer.iss` (zwei Stellen, Muster der Zeilen für `mobile_relay.json`), `.gitignore` (zwei Zeilen), `tests/test_secret_writers.py` (Schreiber eintragen), `tests/test_removal.py` (Gegenstück zu `test_the_mobile_devices_file_is_removed_and_ignored`), `ANNOTATED_MODULES`; Doku (`README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CLAUDE.md`, `src/CLAUDE.md`) mit je einem Satz: Datei, Zweck (Box-Geheimnisse der Handy-Erfassung über den Relay), gehärtet geschrieben, reist nicht per Drive-Sync, getrennt vom Push-Speicher.
- [ ] **Step 5: Run:** `python -m pytest tests/test_mobile_box_store.py tests/test_removal.py tests/test_installer.py tests/test_installer_user_data.py tests/test_secret_writers.py tests/test_claude_md_claims.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q` — PASS; `ruff check .`; pyright.
- [ ] **Step 6: Commit:** `git add -A src tests installer.iss .gitignore README.md SECURITY.md CONTRIBUTING.md CLAUDE.md ; git commit -m "feat(mobile): Speicher fuer Box-Geheimnisse der Relay-Kopplung (Refs #358)"`

### Task 3: `DELETE /v1/box` — `box_relay.py`

**Files:**
- Create: `src/box_relay.py`, `tests/test_box_relay.py`
- Modify: `tests/test_type_annotations.py`

**Interfaces:**
- Consumes: Vorbild `src/push_relay.py` (`_NoRedirectHandler`, `TIMEOUT_S`, `USER_AGENT`, `delete_device(secret, *, opener=None, timeout=TIMEOUT_S, base_url=RELAY_URL)`, **nie werfen, nur den Ausnahmetyp loggen**) und `push_relay.RELAY_URL`; Box-Route aus `relay/CLAUDE.md`: `DELETE /v1/box` mit `Authorization: Bearer <43-Zeichen-Geheimnis>`, Antworten `204` gelöscht, `401` Geheimnis ungültig, `429` Rate-Limit.
- Produces: `delete_box(secret: str, *, opener: OpenerDirector | None = None, timeout: float = TIMEOUT_S, base_url: str = RELAY_URL) -> bool` — `True` bei `204` (und bei `401`: die Box gibt es nicht mehr, der Zweck ist erfüllt), `False` bei allem anderen; **wirft nie**; ein Geheimnis, das nicht `BOX_SECRET_RE` entspricht, wird **ohne Netzaufruf** mit `False` abgewiesen. `RELAY_URL` wird aus `push_relay` übernommen (nicht kopieren).

- [ ] **Step 1: Failing tests** (Fake-`opener`, Muster `tests/test_push_relay.py`): `test_a_204_is_success`, `test_a_401_counts_as_gone`, `test_other_statuses_and_429_are_failures`, `test_a_network_error_returns_false_and_never_raises`, `test_a_malformed_secret_makes_no_request`, `test_the_request_is_a_delete_to_v1_box_with_the_bearer_header_and_no_body`, `test_redirects_are_not_followed`, `test_the_secret_never_reaches_the_log` (Review Focus 6; auch bei `URLError` mit Geheimnis im Text), `test_the_url_is_built_from_the_push_relay_url`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4:** `"src/box_relay.py"` in `ANNOTATED_MODULES`; `python -m pytest tests/test_box_relay.py tests/test_push_relay.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q`, `ruff`, pyright — PASS.
- [ ] **Step 5: Commit:** `git add src/box_relay.py tests ; git commit -m "feat(mobile): Box am Relay loeschen (DELETE /v1/box), best effort (Refs #358)"`

### Task 4: Der Adapter `relay_adapter.py`

**Files:**
- Create: `src/relay_adapter.py`, `tests/test_relay_adapter.py`
- Modify: `tests/test_type_annotations.py`

**Interfaces:**
- Consumes: `mobile_relay_codec` (`decode_request`, `encode_response`, `encode_too_large_response`, `should_answer`, `FrameError`, `FrameTooLarge`, `RelayRequest` mit `path`, `token`, `envelope`, `seq`, `n`), `mobile_routes` (`MobileContext`, `MobilePrincipal`, `make_verifier(devices, now) -> verify(token)`, `dispatch(request, ctx, principal) -> ApiResponse`), `api_routes` (`ApiRequest(method, path, query, body)`, `ApiResponse(status, body, headers)`, `error_response(status, code, message)`), `api_auth` (`ANONYMOUS`, `Denied`). Test-Helfer: `tests/mobile_phone.py` (`Phone`: `pair_request(code)`, `open_pair_response`, `sync_request(body, seq=)`, `open_sync_response`, `SYNC_BODY`, `FakeRing`) und der Aufbau von `make_service` in `tests/test_mobile_service.py` (echte `Settings`, `MobileStore`, `MobileKeyStore`, `Storage`, `ConflictsStore` in `tmp_path`) — für `MobileContext` wiederverwenden, nicht neu erfinden.
- Produces: `class RelayAdapter` mit `__init__(self, ctx: MobileContext, *, clock: Callable[[], float] = time.monotonic, cache_size: int = 8, cache_ttl_seconds: float = 330.0)` und `handle(self, payload: bytes) -> bytes | None`. Ablauf von `handle`:
  1. `decode_request(payload)`; `FrameError` → `None` (nur Ausnahmetyp/Code loggen, `log.debug`). Hat die Anfrage kein gültiges `n` → `None`.
  2. `/v1/pair`: Schlüssel = SHA-256 der **Nutzlast-Bytes**; Treffer im begrenzten Zwischenspeicher (`cache_size` Einträge, `cache_ttl_seconds`, ältester fliegt) → dieselben Antwort-Bytes. Sonst `dispatch(ApiRequest("POST", "/v1/pair", {}, json.dumps(envelope).encode()), ctx, ANONYMOUS)`; nur eine Antwort mit Status `200` wird gespeichert.
  3. `/v1/sync`: Token über `make_verifier(ctx.devices, ctx.now)` prüfen: `Denied(code)` → unversiegeltes `401` mit `error_response(401, code, <deutscher Text wie in api_auth>)`; `None` → `401 unauthorized`; `MobilePrincipal` → `last_seq = ctx.devices.get(principal.name)["last_seq"]` (fehlt der Datensatz: wie `unauthorized`), `should_answer(request.seq, last_seq)` falsch → `None`; sonst `dispatch(ApiRequest("POST", "/v1/sync", {}, …), ctx, principal)`.
  4. Jede Ausnahme aus `dispatch` (nur dort breit fangen, mit Kommentar/Log des Ausnahmetyps) → `500`-Antwort `error_response(500, "internal", …)` **mit** `n`, ohne Details.
  5. Antwort kodieren: `encode_response(resp.status, resp.body, request.seq, request.n)`; `FrameTooLarge` → `encode_too_large_response(request.seq, request.n)`.
  Der Adapter hat keine weitere Schnittstelle (kein Start/Stop, keine Verbindung).

- [ ] **Step 1: Failing tests** (`tests/test_relay_adapter.py`, Namen; `Phone` erzeugt echte versiegelte Anfragen, ein Test-Helfer baut daraus die Nutzlast `{"v":1,"path":…,"token":…,"envelope":…}` per `json.dumps`):
  - `test_a_pair_request_is_answered_and_the_phone_can_open_the_answer` (Kopplung über den Adapter; `json.loads(res)["body"]` öffnet `Phone.open_pair_response`; `n` und `seq` der Antwort entsprechen der Anfrage; Gerät steht im `devices`-Speicher)
  - `test_the_same_pair_request_twice_gets_the_identical_answer_and_pairs_once` (Review Focus 1; `pair_count` bleibt 1, zweite Antwort byte-gleich, **kein** `403`)
  - `test_a_different_pair_request_is_answered_fresh_and_a_failed_pair_is_not_cached` (neuer Code → neue Antwort; falscher Code → `403 invalid_code` wird **nicht** gespeichert: derselbe Fehl-Versuch erneut geht wieder durch `dispatch`)
  - `test_the_pair_cache_is_bounded_and_expires` (9 verschiedene Kopplungen, ältester raus; `clock` weiter als `cache_ttl_seconds` → kein Treffer)
  - `test_a_sync_request_is_answered_and_applied` (Review Focus 2 positiv; Antwort öffnet `Phone.open_sync_response`, `last_seq` im Datensatz = `seq`)
  - `test_a_replayed_or_older_seq_gets_no_answer` (Review Focus 2: gleiche Anfrage nach der Antwort, und `seq` kleiner → `None`, **kein** 409)
  - `test_last_seq_comes_from_the_device_record_not_from_the_adapter` (neuer `RelayAdapter` nach „Neustart“ beantwortet eine bereits angewendete Anfrage ebenfalls nicht)
  - `test_a_revoked_or_expired_token_gets_a_plain_401_with_the_nonce` (Review Focus 4: `token_revoked`, `token_expired`; ein unbekanntes Token → `unauthorized`; Antwort trägt `n` und `seq` der Anfrage, Body `{"error":{"code","message"}}`)
  - `test_hostile_payloads_get_no_answer_and_never_raise` (Review Focus 3: leer, kein JSON, falsches `v`, `/v1/ping`, Pfad `../x`, fehlendes/zu langes `n`, Token fehlt bei `/v1/sync`; → `None`)
  - `test_an_exception_in_dispatch_becomes_a_500_with_the_nonce_and_no_details` (Review Focus 3; `monkeypatch` auf `mobile_routes.dispatch` mit `RuntimeError("secret-details")`; Antwort-Bytes enthalten den Text nicht)
  - `test_an_oversized_answer_falls_back_to_the_413_frame` (Review Focus 5; `monkeypatch` von `dispatch` liefert einen Body > `MAX_PAYLOAD`; Antwort entspricht `encode_too_large_response(seq, n)`)
  - `test_shutdown_in_progress_is_answered_with_the_503_of_dispatch` (`ctx.closing` → `True`: die unversiegelte `503 shutting_down` geht mit `n` zurück)
  - `test_the_adapter_logs_no_token_envelope_or_secret` (Review Focus 6: `caplog` über Kopplung, Abgleich, Fehlerfälle; weder Token noch Umschlag-Inhalt noch Code in Meldungen/`exc_text`)
- [ ] **Step 2: Run:** `python -m pytest tests/test_relay_adapter.py -q` — FAIL.
- [ ] **Step 3: Implement** `relay_adapter.py` (Signaturen oben; ein Zwischenspeicher als kleine `OrderedDict` mit Sperre `threading.Lock`, weil `handle` später von einem Arbeits-Thread gerufen wird, die Sperre nie über `dispatch` hinweg halten).
- [ ] **Step 4: Whitelist** `"src/relay_adapter.py"`; **Step 5: Run:** `python -m pytest tests/test_relay_adapter.py tests/test_mobile_routes.py tests/test_mobile_contract.py tests/test_mobile_relay_codec.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q`, `ruff check .`, pyright; `python -m pytest --cov=src.relay_adapter --cov-branch --cov-report=term-missing tests/test_relay_adapter.py -q` — nahezu 100 %.
- [ ] **Step 6: Commit:** `git add src/relay_adapter.py tests ; git commit -m "feat(mobile): RelayAdapter beantwortet Relay-Anfragen ueber mobile_routes.dispatch (Refs #358)"`

### Task 5: Doku und Spec nachziehen

**Files:**
- Modify: `docs/superpowers/specs/2026-11-02-ios-relay-abgleich-design.md`, `src/CLAUDE.md`, `CLAUDE.md`, `docs/datenschutz.md`

- [ ] **Step 1: Spec:** PR-Schnitt neu fassen: **3a** Desktop-Kern (dieser PR: `pwa_constants`, `mobile_box_store`, `box_relay`, `relay_adapter`), **3b** Verbindung (WebSocket-Bibliothek und Auswahl, Thread `relay_link.py`, Dienst, Verdrahtung in `App`/`main` an den drei Stellen `_quit_with_sync_push`, `remove_application`, `restart_for_scaling` samt `reopen`, Entfernen und `--forget-secrets` löschen die Boxen, `have` dauerhaft speichern, Abhängigkeit in `requirements.txt`/`CONTRIBUTING.md`/`scripts/build.py`/`Zeiterfassung.spec`, Pre-Release auf allen drei Plattformen), **3c** Oberfläche (Einstellungen → Mobil, Koppel-Dialog mit `#relay=`-QR und dem Hinweis „ein fotografierter QR erlaubt das Koppeln von überall“, `FIRST_ENABLE_NOTICE`, Statusanzeige), dann 4 (PWA) und 5 (Doku, iPhone-Test). Den Abschnitt „Desktop“ um das Modell **Leser-Thread + Arbeits-Thread** ergänzen (der Leser darf nie in `dispatch`/`perform_sync` hängen, weil er `ping` senden muss; „neuester gewinnt“ in einem einzelnen Slot) und festhalten: der Thread liegt **außerhalb** von `BackgroundTaskRunner` (dritter Thread-Ort neben API-Server und `single_instance`), `shutdown()` schließt den Socket und wartet kurz.
- [ ] **Step 2: `src/CLAUDE.md`:** Einträge für `pwa_constants`, `mobile_box_store`, `box_relay`, `relay_adapter` (Verantwortung, Verträge: Antworten tragen `n`, kein `n` → keine Antwort, `last_seq` aus dem Datensatz, Kopplung zwischengespeichert, Push-Geheimnis und Box-Geheimnis getrennt); Hinweis im Threading-Abschnitt, dass 3b einen dritten Thread-Ort einführt. Root-`CLAUDE.md` (Struktur): je ein Satz zu den vier Modulen, Formulierung robust gegenüber `tests/test_claude_md_claims.py`.
- [ ] **Step 3: `docs/datenschutz.md`:** ein Satz zu Punkt 2/9: Box-Geheimnisse liegen gerätelokal in `mobile_box.json` (gehärtet geschrieben, reisen nicht per Sync); „Kopplung entfernen“ löscht die Box am Relay (ab PR 3b); bis dahin bleibt sie höchstens 90 Tage im Leerlauf. Die beiden geschützten Zeilen unverändert lassen.
- [ ] **Step 4: Run:** `python -m pytest tests/test_claude_md_claims.py tests/test_pwa_claude_md_claims.py tests/test_datenschutz_claims.py -q ; python -m pytest -q ; ruff check .` — nur der bekannte `test_report_pdf_layout`-Fehler darf bleiben.
- [ ] **Step 5: Commit:** `git add -A docs src/CLAUDE.md CLAUDE.md ; git commit -m "docs(relay): Desktop-Kern beschrieben, PR 3 in 3a bis 3c geschnitten (Refs #358)"`. Push und PR bleiben der Entscheidung des Nutzers überlassen.

---

## Self-Review

- **Spec-Abdeckung:** Regeln 2 (kein `req` mit `seq <= last_seq`, persistiertes `last_seq`) und 3 (Kopplungsantwort zwischenspeichern) → Task 4; `n`-Echo und 413-Rückfall → Task 4; `PWA_URL` lösen → Task 1; Box-Speicher und Löschen → Task 2, 3; getrennte Geheimnisse Push/Box → Global Constraints, Task 2. Bewusst **nicht** in 3a: WebSocket, Thread, `have`-Persistenz (hängt an der Verbindung), Verdrahtung, Oberfläche, Entfernen/Deinstallation, Abhängigkeit/Build (3b, 3c).
- **Typkonsistenz:** `RelayRequest.n`/`.seq` (PR 2) werden in Task 4 verwendet; `BOX_SECRET_RE`/`generate_box_secret` aus dem Codec in Task 2 und 3; `ANNOTATED_MODULES` in jedem Task mit neuem Modul.
- **Bekannte Risiken:** (a) der Zwischenspeicher der Kopplungsantwort ist Prozess-Speicher: nach einem Desktop-Neustart zwischen Kopplung und Wiederzustellung antwortet der Adapter mit `403 invalid_code` — das Handy zeigt dann „neuen Code holen“, akzeptiert; (b) `pending`/`bind` setzen voraus, dass die Kopplung (3b/3c) das offene Geheimnis nach erfolgreichem `dispatch` bindet — die Schnittstelle dafür ist hier fertig; (c) die vielen Credential-Listen sind die häufigste Fehlerquelle: Tests und Installer-Tests zuerst laufen lassen; (d) `mobile_box.json` und `mobile_relay.json` ähneln sich im Namen — Docstrings und Doku trennen sie ausdrücklich.
- **Proportion:** Plan ≈ Umfang der Spec-Abschnitte, Funktionskörper nur als Signaturen und Testnamen.
