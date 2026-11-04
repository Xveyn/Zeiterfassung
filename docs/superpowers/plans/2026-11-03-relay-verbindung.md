# Relay-Verbindung (PR 3b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Desktop hält je Box eine WebSocket zum Relay, beantwortet Handy-Anfragen über den `RelayAdapter`, bindet beim Koppeln das offene Box-Geheimnis und räumt Boxen bei Widerruf, „Zeiterfassung entfernen“ und `--forget-secrets` ab.

**Architecture:** Ein dünner Adapter (`ws_client.py`) ist die **einzige** Stelle, die die WebSocket-Bibliothek kennt. `relay_link.py` (Sockets und Threads: je Box ein Leser-Thread, ein gemeinsamer Arbeits-Thread mit „neuester gewinnt“) kennt nur dessen Protokoll `Socket`. `relay_service.py` hält die Regeln (offenes Geheimnis, Binden, Aufräumen, Lebenszyklus) und wird in `App` an dieselben Stellen gehängt wie `MobileService`.

**Tech Stack:** Python 3.12, `websockets` (sync-Client, `websockets.sync.client`), `threading`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-11-02-ios-relay-abgleich-design.md` (Abschnitte „Desktop“, „Hinweise für PR 3 (3a–3c) und PR 4“, „PR-Schnitt“ 3b). Erster Schritt ist ein Spike, der die Bibliothekswahl bestätigt oder auf `websocket-client` (`suppress_origin=True`) umlenkt.

## Global Constraints

- Python 3.12 ist CI-/Release-Python; jede gepinnte Version muss 3.12 unterstützen; direkte Abhängigkeiten exakt `==` (`requirements.txt`), Eintrag in der Abhängigkeiten-Tabelle in `CONTRIBUTING.md`; Test-Abhängigkeiten in `requirements-test.txt` ebenfalls exakt gepinnt.
- Subprotocol `zeit.v1, <Geheimnis>` (`mobile_relay_codec.SUBPROTOCOL`); **kein** `Origin`-Header (der Relay antwortet auf eine fremde Origin mit `403 forbidden_origin`); Query `role=desktop&have=<ver>`; TLS-Prüfung an.
- Heartbeat: der Text `ping` alle 60–120 s (Wert hier: 90 s), die Box antwortet `pong`.
- Schließcodes der Box: `1000` mit Grund `replaced` ⇒ **nicht** automatisch neu verbinden; `1008` ⇒ mindestens 60 s warten; `1000` mit Grund `wiped` ⇒ `have` auf 0 zurücksetzen.
- Nachrichten: `put` = `encode_put(frame)`, Eingang `decode_message` (`slot`/`ok`), Größe höchstens `MAX_FRAME` (1 048 576 Byte).
- Thread-Modell: der Leser ruft **nie** `RelayAdapter.process`; ein Arbeits-Thread ruft es **nacheinander**; ein Adapter je `MobileContext`; der Thread liegt **außerhalb** von `BackgroundTaskRunner`, `shutdown()` schließt die Sockets und wartet kurz.
- Das Box-Geheimnis steht nie in einem Log, einer Ausnahme-Meldung, einer URL im Log oder einem Statusfeld (Konvention aus `box_relay`/`mobile_box_store`).
- Neue Tk-freie Module: vollständige Typannotationen (Whitelist `tests/test_type_annotations.py`); jeder Catch-all loggt, meldet oder begründet im Handler (`tests/test_catch_all_handlers.py`); Coverage-Gate der Tk-freien Module (`scripts/coverage_gate.py`) bleibt über `FLOOR`.
- Neue Dateien im Datenordner gehören in `removal.py` **und** `installer.iss` (und `.gitignore`); `forget_all` kennt jeden neuen Schlüsselbund-Eintrag (hier: keiner).
- Texte und Kommentare deutsch; Commit-Nachrichten wie im Branch (`feat(mobile): … (Refs #358)`).

## Review Focus

Vom Spec angedeutet, von keinem Task-Test selbstverständlich abgedeckt — jede Zeile hat einen Test im genannten Task:

1. **Das Geheimnis taucht in keinem Log auf**, auch nicht in der Meldung einer scheiternden Verbindung (`InvalidStatus`, URL) — Task 4 (`caplog`).
2. **Ein langsamer Abgleich blockiert den Heartbeat nicht** (Handler schläft länger als das Heartbeat-Intervall, der Leser sendet trotzdem) — Task 4.
3. **`shutdown()` kehrt in der Frist zurück**, egal ob die Box gerade verbindet, im Backoff wartet oder der Handler läuft — Task 4.
4. **Ein werfender Handler tötet den Arbeits-Thread nicht**; eine zu große Antwort (`FrameTooLarge`) wird verworfen und geloggt — Task 4.
5. **Offline beim Start oder Beenden** hält weder den App-Start noch das Beenden auf, und der Backoff loggt nicht bei jedem Versuch — Task 4 und Task 5.
6. **Ein Neustart zwischen Kopplung und erneuter Zustellung** darf keine gute Antwort mit `403 invalid_code` überschreiben: `have` ist vor dem Verarbeiten gespeichert — Task 2 und Task 4.
7. **Der offene Code läuft ab, während die Kopplungs-Anfrage schon läuft**: die Reihenfolge Verarbeiten → Binden → Aufräumen im selben Thread verliert das Geheimnis nicht — Task 5.

---

### Task 1: Spike — Bibliothek bestätigen (Wegwerfcode)

**Files:**
- Create: `scripts/ws_spike.py` (Wegwerfskript, **nicht** committen, wenn der Spike durch ist; Ergebnis in den Abschnitt „Spike-Ergebnis“ am Ende dieses Plans)
- Modify: `docs/superpowers/plans/2026-11-03-relay-verbindung.md` (Abschnitt „Spike-Ergebnis“)

**Interfaces:**
- Produces: eine Entscheidung `websockets` oder `websocket-client`, plus die Pin-Version, plus ein Satz zu Proxy und Bündelung. Spätere Tasks kennen nur das Protokoll `Socket` (Task 3); wechselt die Bibliothek, ändert sich nur `ws_client.py`.

- [ ] **Step 1: Handshake mitschneiden.** Ein roher TCP-Server (`socketserver`) auf `127.0.0.1` nimmt die Upgrade-Anfrage an und druckt Request-Zeile und Header. Dagegen `websockets.sync.client.connect("ws://127.0.0.1:<port>/v1/box/ws?role=desktop&have=0", subprotocols=["zeit.v1", "x"*43], origin=None, ping_interval=None)`. Erwartung: **kein** `Origin`-Header, `Sec-WebSocket-Protocol: zeit.v1, xxxx…`. Zeigt sich ein `Origin`, wechselt der Spike auf `websocket-client` mit `suppress_origin=True` und wiederholt Step 1.
- [ ] **Step 2: TLS prüfen.** Lokaler TLS-Server mit selbstsigniertem Zertifikat; `connect("wss://127.0.0.1:<port>/…")` muss mit `ssl.SSLCertVerificationError` scheitern (Zertifikatsprüfung ist ohne `ssl=`-Angabe an). Danach gegen den echten Relay (`push_relay.RELAY_URL`, `wss`) mit einer erfundenen Box (43 Zeichen): Verbindung kommt zustande, `recv(timeout=…)` liefert nichts; Text `ping` ⇒ Text `pong`; Aufräumen mit `box_relay.delete_box(secret)`.
- [ ] **Step 3: Close-Codes und Parallelität prüfen.** Lokaler `websockets.sync.server`: schließt mit `1000 "replaced"`; der Client sieht `ConnectionClosed.rcvd.code == 1000` und `.reason == "replaced"`. `send` aus Thread B, während Thread A in `recv(timeout=…)` steht, läuft ohne `ConcurrencyError`; zwei gleichzeitige `send` aus zwei Threads ohne Lock werden **nicht** vorausgesetzt (Task 4 serialisiert).
- [ ] **Step 4: Proxy prüfen.** `HTTPS_PROXY=http://127.0.0.1:9` setzen: der Verbindungsversuch scheitert mit einem Proxy-Fehler (beweist, dass der System-Proxy gelesen wird); `proxy=None` umgeht ihn. Festhalten, welches Verhalten der Plan wählt (Empfehlung: Proxy mitnutzen, Standard der Bibliothek, damit Firmennetze nicht still scheitern).
- [ ] **Step 4b: Python-Gegencheck.** `pip download websockets==<aktuell> --python-version 3.12 --only-binary=:all:` für `win_amd64`, `macosx_11_0_arm64`, `manylinux_x86_64` (und 3.13/3.14); fehlt ein Wheel, gibt es `py3-none-any`? Ergebnis notieren.
- [ ] **Step 5: Bündelung prüfen.** `python scripts/build.py` lokal (Windows) mit einem Import in `ws_client.py` (Task 3 anlegen, falls der Spike vorher abbricht: ein Einzeiler-Import in `src/main.py` reicht) und die gebaute Exe starten (`python -m src.main` aus `dist\`-Exe wie in `build-test-windows-inplace`). Für macOS und Linux entscheidet der Workflow **Build** (Häkchen aller Plattformen) mit demselben Import; fehlt ein Hidden Import, kommt `--collect-submodules websockets` in `scripts/build.py`.
- [ ] **Step 6: Ergebnis eintragen** (Abschnitt „Spike-Ergebnis“): Bibliothek, Pin, Proxy-Entscheidung, Bündelung, Abweichungen vom Plan. `scripts/ws_spike.py` löschen.

---

### Task 2: Cursor der Boxen (`have`, dauerhaft)

**Files:**
- Create: `src/mobile_box_cursor.py`
- Modify: `src/removal.py` (`CREDENTIAL_FILES`, neben `mobile_devices.json`: die Datei gehört zu den Boxen und verschwindet mit ihnen, auch ohne das Häkchen für Nutzerdaten), `installer.iss` (`[UninstallDelete]` und die `DeleteMatching('….corrupt-*')`-Zeilen wie bei `mobile_devices.json`), `.gitignore` (Datei und `.corrupt-*`)
- Test: `tests/test_mobile_box_cursor.py`, `tests/test_removal.py` (Listen bleiben gleich)

**Interfaces:**
- Produces: `class MobileBoxCursor` mit `__init__(self, filepath: str = "mobile_box_cursor.json") -> None`, `get(self, secret: str) -> int` (0 ohne Eintrag), `advance(self, secret: str, ver: int) -> bool` (speichert nur, wenn `ver` größer; `True` bei Änderung; **wirft nie** — ein Schreibfehler wird geloggt und der Wert bleibt im Speicher), `reset(self, secret: str) -> None` (für `wiped`), `retain(self, secrets: Iterable[str]) -> None`.
- Die Datei hält `{"schema_version": 1, "have": {sha256(secret) hex: ver}}` — **kein** Geheimnis, deshalb über `json_store.atomic_write_json` ohne ACL-Härtung (wird bei jedem Abgleich geschrieben, wie `mobile_devices.json`); kaputte Datei ⇒ `load_json_or_quarantine`; `ver` ist `0 ≤ ver < 2**31`, sonst verworfen.

- [ ] **Step 1: Tests schreiben** — `test_get_default_is_zero`, `test_advance_only_forward` (`advance(s, 5)` ⇒ `True`, `advance(s, 5)` und `advance(s, 3)` ⇒ `False`, `get == 5`), `test_persists_across_instances`, `test_file_holds_digest_not_secret` (Dateiinhalt enthält das Geheimnis nicht), `test_reset_and_retain`, `test_write_failure_keeps_memory` (`atomic_write_json` wirft `OSError` ⇒ `get` liefert den neuen Wert, `advance` wirft nicht), `test_corrupt_file_is_quarantined`.
- [ ] **Step 2: Test laufen lassen** (`pytest tests/test_mobile_box_cursor.py -v`) — FAIL: Modul fehlt.
- [ ] **Step 3: `MobileBoxCursor` implementieren** (eigener `threading.Lock`; Digest `hashlib.sha256(secret.encode()).hexdigest()`; Muster `mobile_store`, Typannotationen vollständig).
- [ ] **Step 4: Dateilisten nachziehen**: `removal.py`, `installer.iss`, `.gitignore`; `pytest tests/test_mobile_box_cursor.py tests/test_removal.py tests/test_type_annotations.py -v` — PASS (Whitelist in `test_type_annotations.py` ergänzen).
- [ ] **Step 5: Commit** `feat(mobile): Cursor der Boxen, have dauerhaft (Refs #358)`.

---

### Task 3: WebSocket-Adapter (`ws_client.py`)

**Files:**
- Create: `src/ws_client.py`
- Modify: `requirements.txt`, `requirements-test.txt`, `CONTRIBUTING.md` (Abhängigkeiten-Tabelle), ggf. `scripts/build.py` (je Spike-Ergebnis)
- Test: `tests/test_ws_client.py`

**Interfaces:**
- Consumes: `mobile_relay_codec.SUBPROTOCOL`, `MAX_FRAME`; `push_relay.RELAY_URL`.
- Produces:
  - `class SocketClosed(Exception)` mit `code: int | None`, `reason: str`; `class SocketTimeout(Exception)`.
  - `class Socket(Protocol)`: `recv(self, timeout: float) -> bytes | str` (wirft `SocketTimeout`/`SocketClosed`), `send(self, data: bytes | str) -> None` (wirft `SocketClosed`), `close(self) -> None` (wirft nie, aus jedem Thread aufrufbar, weckt einen wartenden `recv`).
  - `Connect = Callable[[str, int], Socket]` (Argumente: Geheimnis, `have`) und `def connect(secret: str, have: int, *, base_url: str = RELAY_URL, open_timeout: float = 10.0) -> Socket`; `https`→`wss`, Query `role=desktop&have=<have>`, `subprotocols=[SUBPROTOCOL, secret]`, `origin=None`, `ping_interval=None` (der Heartbeat ist der Text `ping`), `max_size=MAX_FRAME + 16`; jede Bibliotheksausnahme wird zu `SocketClosed`/`OSError` **ohne** das Geheimnis im Text.

- [ ] **Step 1: Tests schreiben** gegen einen lokalen `websockets.sync.server` auf `127.0.0.1` (Fixture): `test_handshake_has_no_origin_and_carries_subprotocol` (Handler liest `request.headers`: kein `Origin`; `Sec-WebSocket-Protocol` nennt `zeit.v1` und das Geheimnis; Pfad/Query `role=desktop&have=7`), `test_recv_times_out_with_SocketTimeout`, `test_server_close_surfaces_code_and_reason` (`1000`, `"replaced"`), `test_close_from_other_thread_wakes_recv`, `test_error_text_never_contains_secret` (Verbindung zu einem toten Port: `str(exc)`/`repr(exc)` ohne Geheimnis).
- [ ] **Step 2: Tests laufen lassen** — FAIL.
- [ ] **Step 3: `ws_client.py` implementieren.** Import der Bibliothek **lazy** in `connect` (CI ohne sie installiert die Test-Deps trotzdem, aber `src.ui` darf sie beim Import nicht verlangen). Die `Socket`-Hülle übersetzt `TimeoutError` → `SocketTimeout`, `ConnectionClosed` → `SocketClosed(code=rcvd.code if rcvd else None, reason=rcvd.reason if rcvd else "")`.
- [ ] **Step 4: Pin eintragen** (`requirements.txt` mit Kommentar: „sync-Client des Relay-Abgleichs (#358); gegen Python 3.12 geprüft, Wheels cp312–cp314 für Windows, macOS arm64, Linux x86_64“), `requirements-test.txt`, `CONTRIBUTING.md`.
- [ ] **Step 5: Tests laufen lassen** (`pytest tests/test_ws_client.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -v`) — PASS.
- [ ] **Step 6: Commit** `feat(mobile): WebSocket-Adapter fuer den Relay, websockets sync (Refs #358)`.

---

### Task 4: Verbindungsschicht (`relay_link.py`)

**Files:**
- Create: `src/relay_link.py`, `tests/fakes_relay.py` (gefälschter `Socket` und `Connect`)
- Test: `tests/test_relay_link.py`

**Interfaces:**
- Consumes: `Socket`, `Connect`, `SocketClosed`, `SocketTimeout` (Task 3); `MobileBoxCursor` (Task 2); `mobile_relay_codec.encode_put`, `decode_message`, `FrameTooLarge`.
- Produces:
  - `@dataclass(frozen=True) class LinkTiming`: `heartbeat_s: float = 90.0`, `pong_wait_s: float = 30.0`, `backoff: tuple[float, ...] = (1, 2, 4, 8, 16, 30, 60)`, `throttled_wait_s: float = 60.0`, `idle_tick_s: float = 5.0`, `join_s: float = 2.0` (Tests geben winzige Werte).
  - `class RelayLink`: `__init__(self, connect: Connect, handler: Callable[[str, bytes], None], cursor: MobileBoxCursor, *, on_idle: Callable[[], None] | None = None, timing: LinkTiming = LinkTiming()) -> None`; `set_boxes(self, secrets: Collection[str]) -> None` (nicht blockierend: startet fehlende Leser, schließt entfernte; ein `replaced`-Leser wird erst durch erneutes Nennen in `set_boxes` nach Entfernen wieder gestartet); `put(self, secret: str, frame: bytes) -> bool` (`False`, wenn nicht verbunden oder zu groß; nie ein Wurf); `states(self) -> dict[str, str]` (`connecting`/`connected`/`backoff`/`replaced`/`stopped`, Schlüssel = Geheimnis, **nur intern** — der Dienst übersetzt); `shutdown(self) -> None` (idempotent, wartet höchstens `join_s`, schließt alle Sockets, weckt den Arbeits-Thread).
  - Der Handler läuft auf dem **Arbeits-Thread** und bekommt `(secret, payload)`.

- [ ] **Step 1: Tests schreiben** (alle mit gefälschten Sockets, ohne Netz, `LinkTiming` im Millisekundenbereich):
  - `test_slot_reaches_handler_on_worker_thread` (Handler-Thread ≠ Leser-Thread; Geheimnis und Nutzlast stimmen).
  - `test_have_advanced_before_handler_runs` (zum Handler-Zeitpunkt steht `cursor.get(secret)` schon auf `ver`) und `test_reconnect_sends_have` (zweiter `connect`-Aufruf bekommt den gespeicherten Wert).
  - `test_latest_wins_per_box` (drei `slot` kommen, der Handler ist beim ersten blockiert ⇒ er sieht danach nur den dritten).
  - `test_put_encodes_and_sends` (Socket bekommt `encode_put(frame)`), `test_put_without_connection_returns_false`, `test_put_oversize_returns_false_and_logs`.
  - `test_slow_handler_does_not_block_heartbeat` (Review Focus 2) und `test_missing_pong_reconnects`.
  - `test_replaced_close_does_not_reconnect` (`1000/"replaced"` ⇒ Zustand `replaced`, kein zweiter `connect`), `test_wiped_resets_have_and_reconnects` (`1000/"wiped"`), `test_throttle_close_waits_at_least_throttled_wait` (`1008`), `test_other_close_uses_backoff_and_resets_after_success`.
  - `test_secret_never_logged` (Review Focus 1: `caplog` über alle Ebenen, Verbindung wirft `OSError("… <secret> …")` — das Log enthält das Geheimnis nicht; auch nicht in `states()`-Logzeilen).
  - `test_handler_exception_keeps_worker_alive` (Review Focus 4: zweiter `slot` wird trotzdem behandelt).
  - `test_shutdown_returns_within_join_while_connecting`, `…_in_backoff`, `…_while_handler_runs` (Review Focus 3).
  - `test_offline_logs_once_per_state_change` (Review Focus 5: zehn gescheiterte Versuche ⇒ höchstens eine Warnung je Zustandswechsel).
  - `test_on_idle_called_periodically_from_worker`.
- [ ] **Step 2: Tests laufen lassen** — FAIL.
- [ ] **Step 3: `RelayLink` implementieren.** Pro Box ein Daemon-Thread (`_BoxReader`) mit der Schleife connect → `recv(timeout=heartbeat_s)`; bei `SocketTimeout` den Text `ping` senden (unter einem **Sendesperr-Lock je Box**, weil `put` aus dem Arbeits-Thread und der Heartbeat aus dem Leser schreiben) und `pong_wait_s` auf irgendeine Nachricht warten; `decode_message` ⇒ `slot` in den Slot der Box legen (ein Arbeits-Thread, `threading.Condition`, je Box höchstens ein wartendes `(ver, payload)`), `ok` und Text ignorieren. Der Arbeits-Thread: `cursor.advance(secret, ver)`, dann `handler(secret, payload)` in `try/except Exception` (Typ ins Log, nie der Text), außerdem alle `idle_tick_s` `on_idle`. Wartezeiten über `threading.Event.wait`, damit `shutdown` sie weckt. Das Geheimnis kommt in keine Logzeile; Logs nennen eine Kurzmarke (die ersten 6 Zeichen von `sha256(secret)`).
- [ ] **Step 4: Tests laufen lassen** (`pytest tests/test_relay_link.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -v`) — PASS.
- [ ] **Step 5: Commit** `feat(mobile): relay_link - Leser je Box, ein Arbeits-Thread, Backoff (Refs #358)`.

---

### Task 5: Dienst und Regeln (`relay_service.py`)

**Files:**
- Create: `src/relay_service.py`
- Modify: `src/mobile_service.py` (Eigenschaft `context`, Parameter `box_cleanup`)
- Test: `tests/test_relay_service.py`, `tests/test_mobile_service.py`

**Interfaces:**
- Consumes: `RelayLink` (Task 4), `MobileBoxStore` (3a: `pending`, `open_pending`, `clear_pending`, `bind`, `get`, `all_secrets`, `known_ids`, `remove`, `retain`), `MobileBoxCursor.reset/retain`, `RelayAdapter.process` → `RelayResult`, `box_relay.delete_box`, `PairingSession.open/close/is_active`, `mobile_relay_codec.relay_link`.
- Produces:
  - `MobileService.context` (Eigenschaft, das mit `closing`/`on_paired` ersetzte `MobileContext`) und Konstruktor-Parameter `box_cleanup: Callable[[Iterable[str] | None], None] | None = None`, den `revoke(device_id)` (mit `[device_id]`) und `revoke_all()` (mit `None`) **nach** der Gerätesperre rufen.
  - `class RelayService`: `__init__(self, settings, context: MobileContext, boxes: MobileBoxStore, cursor: MobileBoxCursor, *, run: Callable[..., None], connect: Connect = ws_client.connect, delete_box: Callable[[str], bool] = box_relay.delete_box, now: Callable[[], str] = utc_now_iso, timing: LinkTiming = LinkTiming())`;
    - `apply(self) -> None` (UI-Thread, Arbeit im Worker): bei `mobile_enabled` falsch oder `closing()` wahr: `link.set_boxes([])`; sonst beim **ersten** Lauf ein verwaistes `pending` abräumen (`clear_pending` + `delete_box`), dann `link.set_boxes(gebundene Geheimnisse + pending nur bei aktiver Kopplungssitzung)`.
    - `open_pairing(self) -> str | None` (**Worker**): `pairing.open()`, `boxes.open_pending(now())`, ein früheres `pending` löschen (außer es ist ein nicht gebundener Rest einer gelungenen Kopplung), `link.set_boxes`, Rückgabe `relay_link(secret, code)`; bei `MobileBoxReadOnly`/`OSError`: Sitzung schließen, `None`.
    - `close_pairing(self) -> None` (Worker): Sitzung schließen, `clear_pending`, Box am Relay löschen, `set_boxes` aktualisieren.
    - `forget_devices(self, ids: Iterable[str] | None) -> None` (Worker; `None` = alle): `boxes.remove`/`retain` ⇒ je Geheimnis `delete_box`, `cursor.retain`, `set_boxes`.
    - `shutdown(self) -> None` / `reopen(self) -> None` wie `MobileService` (`shutdown` setzt ein Flag und ruft `link.shutdown()`; `reopen` baut einen neuen `RelayLink`).
    - `states_by_device(self) -> dict[str, str]` (Geräte-ID → Zustand, für 3c).
    - intern `_handle(secret, payload)` (Arbeits-Thread, vom Link gerufen): `RelayAdapter(context).process(payload)`; Frame ⇒ `link.put`; `paired_device_id` ⇒ `boxes.bind(id, expected=secret)`, bei `OSError` loggen und `(id, secret)` als „ungebunden“ merken; `_on_idle` (alle 5 s, Arbeits-Thread): ungebundene erneut binden; `pending` ohne aktive Sitzung ⇒ `clear_pending` + `delete_box`; liefert die Reihenfolge Verarbeiten → Binden → Aufräumen im selben Thread (Review Focus 7).

- [ ] **Step 1: Tests schreiben** (gefälschter Link und Relay-Aufrufer, echte `MobileBoxStore`/`MobileBoxCursor` in `tmp_path`):
  - `test_apply_clears_orphan_pending_on_start` (Datei mit `pending` ⇒ `clear_pending`, `delete_box(secret)`, `set_boxes` ohne es).
  - `test_pending_only_connected_while_pairing_active`.
  - `test_open_pairing_returns_relay_link_and_connects_pending`; `test_open_pairing_deletes_previous_pending_but_not_unbound_leftover`; `test_open_pairing_readonly_store_closes_session_and_returns_none`.
  - `test_pair_request_binds_pending_with_expected_secret`; `test_bind_failure_is_retried_on_idle_and_never_deleted` (erst `OSError`, dann Erfolg; `delete_box` nie gerufen); `test_pair_when_new_pairing_opened_meanwhile_does_not_bind` (`expected` verhindert Binden).
  - `test_handler_puts_frame_and_skips_none` (kein Frame ⇒ kein `put`).
  - `test_expired_code_cleans_pending_after_handler` (Review Focus 7).
  - `test_forget_devices_removes_boxes_cursor_and_deletes_remote` (ein Gerät und `None`).
  - `test_disabled_setting_disconnects_all`.
  - `test_shutdown_stops_link_and_apply_after_shutdown_is_noop`; `test_reopen_allows_apply_again`.
  - `test_mobile_service_revoke_calls_box_cleanup_outside_lock` (in `tests/test_mobile_service.py`: Aufruf erfolgt, wenn `devices_lock` frei ist; `revoke_all` übergibt `None`).
- [ ] **Step 2: Tests laufen lassen** — FAIL.
- [ ] **Step 3: `RelayService` und die zwei Änderungen an `MobileService` implementieren.** Der Adapter wird einmal je Dienst-Instanz gebaut (`RelayAdapter(self._context)`) und nur aus dem Arbeits-Thread gerufen. `bind`-/`delete_box`-Aufrufe laufen nie unter einem Lock des Stores.
- [ ] **Step 4: Tests laufen lassen** (`pytest tests/test_relay_service.py tests/test_mobile_service.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -v`) — PASS.
- [ ] **Step 5: Commit** `feat(mobile): RelayService - Binden, Aufraeumen, Lebenszyklus (Refs #358)`.

---

### Task 6: Verdrahtung in `main.py` und `App`

**Files:**
- Modify: `src/main.py` (Stores bauen, an `App` reichen), `src/ui.py` (Dienst bauen und an **denselben** Stellen führen wie `self._mobile`: Aufbau, `_apply_mobile_setting`, `_quit_with_sync_push`, `remove_application`, `restart_for_scaling` samt `reopen`), `src/mobile_service.py` (Übergabe `box_cleanup=self._relay.forget_devices` beim Bau — der `RelayService` braucht `service.context`, deshalb erst `MobileService` bauen, dann `RelayService(…, service.context, …)` und `service._box_cleanup` über einen Setter `set_box_cleanup` nachreichen, falls die Zirkularität das verlangt)
- Test: `tests/test_mobile_wiring.py`, `tests/test_relay_wiring.py`

**Interfaces:**
- Consumes: `RelayService` (Task 5), `MobileBoxStore`, `MobileBoxCursor`.
- Produces: `App(..., mobile_box_store=None, mobile_box_cursor=None)`; ohne beide (und ohne `_mobile`) ist `self._relay = None`, alle Aufrufstellen prüfen darauf (Muster `self._mobile`).

- [ ] **Step 1: Tests schreiben** (Quelltext-Tests wie `tests/test_mobile_wiring.py`): `test_relay_shutdown_in_all_three_exit_paths` (`_quit_with_sync_push`, `remove_application` **vor** jedem Worker, `restart_for_scaling` **vor** dem Spawn), `test_relay_reopen_after_failed_restart`, `test_relay_apply_follows_mobile_apply`, `test_main_builds_box_store_and_cursor_in_base_dir`.
- [ ] **Step 2: Tests laufen lassen** — FAIL.
- [ ] **Step 3: Verdrahtung umsetzen.** `shutdown()` blockiert höchstens die Frist des Links (2 s) und läuft **vor** dem finalen Sync-Push, damit nach dem Snapshot keine Handy-Anfrage mehr schreibt; beim Beenden nie auf den Relay warten.
- [ ] **Step 4: Tests laufen lassen** (`pytest tests/test_mobile_wiring.py tests/test_relay_wiring.py tests/test_api_wiring.py -v`, danach `pytest -q`) — PASS.
- [ ] **Step 5: Commit** `feat(mobile): Relay-Dienst in main und App verdrahtet (Refs #358)`.

---

### Task 7: Boxen beim Entfernen und Deinstallieren abräumen

**Files:**
- Modify: `src/removal.py` (neuer Schritt nach dem Schlüsselbund, **vor** dem Löschen der Zugangsdaten-Dateien), `src/secret_migration.py` (`forget_all`: `_forget_boxes(path)` neben `_forget_mobile_keys`)
- Test: `tests/test_removal.py`, `tests/test_secret_migration.py`

**Interfaces:**
- Consumes: `MobileBoxStore(os.path.join(base, "mobile_box.json")).all_secrets()` (nur lesen, kein Schreiben), `box_relay.delete_box`.
- Produces: `removal` ruft je Geheimnis `delete_box`, **wirft nie** (best effort, ein Netzfehler hält die übrigen Schritte nicht auf), meldet die Zahl der nicht erreichbaren Boxen im Abschlusstext („verfallen nach 90 Tagen von selbst“); `forget_all` tut dasselbe ohne UI (Deinstaller, begrenzt durch `TIMEOUT_S` je Box).

- [ ] **Step 1: Tests schreiben:** `test_removal_deletes_all_boxes_before_credentials` (Reihenfolge: `delete_box` vor dem Löschen von `mobile_box.json`), `test_removal_continues_when_relay_unreachable` (alle `delete_box` ⇒ `False`, übrige Schritte laufen, Hinweis im Abschlusstext), `test_removal_with_unreadable_box_file_does_not_overwrite_it`, `test_forget_all_deletes_boxes` und `test_forget_all_survives_corrupt_box_file`.
- [ ] **Step 2: Tests laufen lassen** — FAIL.
- [ ] **Step 3: Umsetzen.** Eine nicht lesbare/schreibgeschützte Datei ist kein Grund, den Rest des Entfernens abzubrechen (loggen, Typ).
- [ ] **Step 4: Tests laufen lassen** (`pytest tests/test_removal.py tests/test_secret_migration.py tests/test_catch_all_handlers.py -v`) — PASS.
- [ ] **Step 5: Commit** `feat(mobile): Boxen beim Entfernen und Deinstallieren abraeumen (Refs #358)`.

---

### Task 8: Doku, Build-Gegencheck, Pre-Release

**Files:**
- Modify: `src/CLAUDE.md` (Abschnitt „Threading-Modell“: dritter Thread-Ort ist jetzt vorhanden; Einträge `relay_link`, `relay_service`, `ws_client`, `mobile_box_cursor`; Streichen von „noch nicht verdrahtet (ab PR 3b)“ in den Einträgen zu `mobile_box_store`, `box_relay`, `relay_adapter`), `CLAUDE.md` (Struktur-Liste), `docs/superpowers/specs/2026-11-02-ios-relay-abgleich-design.md` (3b als umgesetzt, Offener Punkt 5 mit der Entscheidung schließen), `CONTRIBUTING.md`, ggf. `scripts/build.py`
- Test: `tests/test_claude_md_claims.py` (läuft mit), volle Suite

- [ ] **Step 1: Doku nachziehen** (nur Beschreibung des Umgesetzten, kein neuer Vertrag).
- [ ] **Step 2: Volle Suite und Linter:** `pytest -q`, `ruff check .`, `npx pyright` (wie in der CI) — alles grün; `python scripts/coverage_gate.py` nach `pytest --cov=src --cov-report=json`.
- [ ] **Step 3: Build-Gegencheck:** Workflow **Build** mit allen drei Plattformen und gesetztem `installer`-Häkchen auf dem Branch; die gebauten Artefakte starten (Import von `ws_client` und `connect` gegen den echten Relay mit einer erfundenen Box, dann `delete_box`).
- [ ] **Step 4: Pre-Release auf allen drei Plattformen vorschlagen** (Änderung der Dependency-Auflösung, s. Wurzel-`CLAUDE.md`, „Abhängigkeiten & Pinning“); macOS ist laut Memo nicht Pflicht-Gate, aber der Build läuft mit.
- [ ] **Step 5: Commit** `docs(relay): Verbindungsschicht beschrieben (Refs #358)`.

---

## Spike-Ergebnis

Gemessen am 2026-11-03 unter Windows 11, Python 3.13.2, `websockets` 17.4 (Wegwerfskript, nicht committet).

**Entscheidung: `websockets==17.4`** (`websockets.sync.client`), nicht `websocket-client`.

- **Handshake:** kein `Origin`-Header (mit `origin=None`), `Sec-WebSocket-Protocol: zeit.v1, <43 Zeichen>`; es geht zusätzlich `Sec-WebSocket-Extensions: permessage-deflate` und `User-Agent: Python/3.13 websockets/17.4` mit. Keine `suppress_origin`-Variante nötig, kein Wechsel der Bibliothek.
- **Abweichung für `ws_client.py` (Task 3): `connect(..., legacy=True)` übergeben** (und im `finally` `close()`). Ohne `legacy=True` warnt 17.x bei jedem direkten `connect()` mit einer `DeprecationWarning` („must be used as a context manager“); `legacy=True` ist die dokumentierte Form für die Nutzung ohne `with` und warnungsfrei (im PyInstaller-Test mit `warnings.simplefilter("error")` gelaufen). Alternativ `with connect(...) as ws:` über die ganze Lebensdauer der Verbindung. `compression=None` ist optional (Frames sind verschlüsselt, Kompression bringt nichts), im Spike nicht nötig.
- **TLS:** selbstsigniertes Zertifikat ⇒ `ssl.SSLCertVerificationError` (Prüfung ist ohne `ssl=` an). Echter Relay (`wss`, erfundene 43-Zeichen-Box): Verbindung steht, `subprotocol == "zeit.v1"`, `recv(timeout=2)` liefert nichts (`TimeoutError`), Text `ping` ⇒ Text `pong`; danach `box_relay.delete_box` ⇒ `True`.
- **Close-Codes:** der Client sieht `ConnectionClosed.rcvd.code == 1000`, `.reason == "replaced"`.
- **Parallelität:** `send` aus Thread B, während Thread A in `recv(timeout=3)` steht, läuft ohne `ConcurrencyError` (die Pong-Antwort kam in Thread A an). Zwei gleichzeitige `send` ohne Lock wurden nicht geprüft; Task 4 serialisiert weiter.
- **Proxy:** Standard der Bibliothek (`proxy=True`) liest `HTTPS_PROXY`: mit `HTTPS_PROXY=http://127.0.0.1:9` scheitert der Verbindungsversuch (`ConnectionRefusedError`, WinError 10061), mit `proxy=None` kommt die Verbindung zustande. **Plan: Standard beibehalten (Proxy mitnutzen)**, damit Firmennetze nicht still scheitern; kein `proxy=`-Argument setzen. (Ausnahme-Meldungen der Proxy-Stufe können Hostnamen enthalten, nie das Geheimnis; trotzdem nur die Art loggen.)
- **Python-Gegencheck:** `websockets==17.4`, `Requires-Python >=3.11`. Binäre Wheels (`pip download --only-binary=:all: --no-deps`) vorhanden für cp312/cp313(win)/cp314 auf `win_amd64`, `macosx_11_0_arm64` und `manylinux x86_64` (cp312: Windows, macOS arm64, Linux x86_64 alle bestätigt; zusätzlich cp314 alle drei, cp313 nur Windows geprüft). Die Bibliothek hat zudem einen reinen Python-Rückfall (die C-Beschleunigung ist optional), fehlt ein Wheel, läuft sie trotzdem. Keine Transitiven: `websockets` hat keine Abhängigkeiten.
- **Bündelung (Windows):** Mini-Exe mit `pyinstaller --onedir` (PyInstaller 6.20.0, nur `from websockets.sync.client import connect`, **ohne** `--collect-*`/Hidden Imports) startet, verbindet gegen den echten Relay, `ping` ⇒ `pong`. Kein `--collect-submodules websockets` in `scripts/build.py` nötig. **Offen:** macOS und Linux (Workflow **Build**, Task 8) sind von hier nicht auslösbar; dort mit dem Import in `ws_client.py` prüfen.
- Die Pin-Zeile gehört in `requirements.txt` und `requirements-test.txt` (Task 3/8), `CONTRIBUTING.md`-Tabelle ergänzen.

## Offene Fragen, die das Bauen klärt

- Ob `websockets` im PyInstaller-Build ohne zusätzlichen Hidden Import läuft (Task 1/8).
- Ob Auto-Response-Nachrichten gegen das 20:1-Kontingent des Relays zählen (Spec, Offener Punkt 2; Messung im Dashboard, kein Code).
