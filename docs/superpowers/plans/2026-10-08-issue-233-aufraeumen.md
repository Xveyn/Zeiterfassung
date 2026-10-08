# Issue #233 aufräumen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die zurückgestellten Minors aus den Reviews zur lokalen API (Issue #233) abarbeiten, soweit sie Robustheit (A) und Texte/Doku (B) betreffen: Auth-Kleinigkeiten, Token-Datei, `ApiService`-Rotation und -Beenden, `Allow`-Header und Backlog des Servers, die Meldung zu `invalid_slot`, falsche Texte und Doku.

**Architecture:** Fünf kleine, voneinander unabhängige Tasks, je mit einem Test, der zuerst rot ist. Keine neue Funktion für Nutzer; die API-Verträge bleiben gleich (außer `Allow`, das jetzt wahr ist).

**Tech Stack:** Python 3.12, stdlib. Keine neue Abhängigkeit.

**Anlass:** Issue #233 (Checklisten und die Review-Kommentare zu #237, #238, #240, #241). Nicht in diesem PR: Bereich C (nur per Pre-Release prüfbar: Windows-Zwischenablage, `SO_EXCLUSIVEADDRUSE`, Tk-Tab), Bereich D (gehört zu #221: `Sec-Fetch-Site` an die Policy koppeln, `allowed_hosts` normalisieren, Plattform-Schwelle in `port_hint`) und Bereich E (Kosmetik, bewusst belassen).

**Branching:** Stack. `feat/issue-233-aufraeumen` ist aus `feat/storage-haerten` (PR #243) abgezweigt und liegt an; der PR zielt auf `feat/storage-haerten` und wird danach mit `POST /repos/Xveyn/Zeiterfassung/stacks/236/add` an den Stack gehängt. PR-Text: `Refs #233`, `Refs #92`, kein `Closes`. **Kein Versionsbump.**

## Entscheidungen (mit dem Nutzer abgestimmt)

- Umfang: Bereiche A (Robustheit) und B (Text und Doku) von #233. C bleibt für den Pre-Release, D wandert nach #221, E bleibt offen.
- Die Kommentare in #233 (nicht der Haupttext) werden erst nach einem Okay abgehakt.

## Rulings aus der Planung

- **`errors="replace"` im Verifier bleibt.** Der Review-Punkt „besser `surrogatepass`" hat keine beobachtbare Wirkung: das Token-Alphabet enthält kein `?`, ein Lone Surrogate wird zu `?` und stimmt nie mit dem Token überein; ein Test dafür war schon vor jeder Änderung grün. Keine Änderung, Punkt in #233 als „kein Handlungsbedarf" geschlossen.
- **Der Token-Dateiinhalt toleriert ein UTF-8-BOM, kein UTF-16.** Windows PowerShell 5.1 schreibt mit `>` UTF-16; das zu erkennen hieße, eine Datei mit NUL-Bytes als Token zu akzeptieren. Stattdessen gilt sie als ungültig (wie bisher) und die Doku sagt es.
- **`Allow` nennt die Methoden der Routen** (`DELETE, GET, PUT`), nicht `ALLOWED_METHODS`. POST bleibt in `ALLOWED_METHODS` (für #221 vorgesehen), damit `authorize` ihn vor dem Routing nicht mit 405 abweist.
- **Der wirkungslose Test `test_too_many_query_fields_are_400` wird ersetzt**, nicht ergänzt: der alte war auch ohne `max_num_fields` grün (die Parameter hießen `a0…a499`, also `unknown_parameter`).
- **„Neu erzeugen“ bleibt bei unbekanntem Token gesperrt.** Die Maske meldet dann nur ehrlich „Kein lesbares Token“; die Knopf-Logik im Tk-Tab zu ändern wäre ein UI-Eingriff, der nur im Pre-Release prüfbar ist (Bereich C).

## Global Constraints

- Tk-frei, stdlib-only, vollständig annotiert; `ruff check .` und `pyright 1.1.411` sauber.
- Jeder `except Exception`/`BaseException` loggt oder begründet im Handler (`tests/test_catch_all_handlers.py`); `rotate()` loggt den Fehler weiterhin mit Traceback.
- Das Token steht nie in einer Datei, die nicht gehärtet ist (gilt auch für die Temp-Datei).
- Keine Änderung am Draht-Format der API außer dem `Allow`-Header.

## Review Focus

1. **Temp-Datei:** die Härtung läuft, bevor das Token geschrieben wird, und es entsteht kein Dateihandle-Leck, wenn `chmod`/`harden_windows_acl` werfen. Task 1.
2. **BOM:** `read_token` und `load_or_create_token` verhalten sich gleich; ein BOM allein oder BOM plus Müll ist ungültig. Task 1.
3. **Rotation:** ein beliebiger Fehler gibt `RotateResult(False, …)`, nie eine Ausnahme; die Verschränkung mit `apply()` und `shutdown()` bleibt serialisiert (derselbe Lock). Task 2.
4. **Aufgegebenes `shutdown()`:** der Server stoppt nach der Rotation, und ein späterer `reopen()` startet wieder. Task 2.
5. **`Allow`:** für jeden unbekannten Methodennamen und jede bekannte Nicht-Route-Methode gleich. Task 3.
6. **Doku-Aussagen** stimmen mit dem Verhalten überein (Port-Squatting, Token-Datei, `weeks[]`-Beispiel). Task 5.

---

### Task 1: Auth und Token-Datei härten

**Files:** Tests `tests/test_api_auth.py`, `tests/test_single_instance.py`; Quelltext `src/api_auth.py`, `src/single_instance.py`.

**Interfaces:** Produces: `AuthResult.ok` verlangt einen Principal; `_valid_token` toleriert ein UTF-8-BOM; `authorize` schneidet den Host-Header nur an HTTP-Whitespace ab; `_write_token_atomic` und `_write_secret_atomic` härten die (noch leere) Temp-Datei vor dem Schreiben.

- [ ] **Step 1: Write the failing tests**

Hänge ans Ende von `tests/test_api_auth.py` an:

```python
# --- Härtung aus dem Review von PR 1 (#233) ------------------------------------------

def test_a_token_file_with_a_utf8_bom_is_still_the_token(tmp_path):
    token = generate_token()
    (tmp_path / TOKEN_FILENAME).write_bytes(b"\xef\xbb\xbf" + token.encode("ascii") + b"\r\n")

    assert load_or_create_token(str(tmp_path)) == token
    assert read_token(str(tmp_path)) == token


@pytest.mark.parametrize("content", [
    "utf16", "nul-in-the-middle", "non-ascii-in-the-middle", "bom-then-junk",
])
def test_a_token_file_that_is_not_ascii_is_not_a_token_and_never_crashes(tmp_path, content):
    token = generate_token()
    data = {
        "utf16": b"\xff\xfe" + token.encode("utf-16-le"),
        "nul-in-the-middle": token[:20].encode() + b"\x00" + token[21:].encode(),
        "non-ascii-in-the-middle": token[:20].encode() + b"\xc3\xa4" + token[22:].encode(),
        "bom-then-junk": b"\xef\xbb\xbf" + b"zu-kurz",
    }[content]
    (tmp_path / TOKEN_FILENAME).write_bytes(data)

    assert read_token(str(tmp_path)) is None
    fresh = load_or_create_token(str(tmp_path))
    assert fresh is not None and fresh != token


def test_an_auth_result_with_status_200_but_no_principal_is_not_ok():
    assert not AuthResult(200, "ok").ok
    assert not AuthResult(200, "ok", None).ok


def test_the_host_header_is_trimmed_of_http_whitespace_only():
    policy = Policy.loopback(17653)
    verify = single_token_verifier("a" * 43)
    ok = authorize("GET", {"Host": " \t127.0.0.1:17653 \t", "Authorization": "Bearer " + "a" * 43},
                   policy, verify)
    assert ok.status == 200
    for junk in ("\u00a0127.0.0.1:17653", "127.0.0.1:17653\u2028", "\x85127.0.0.1:17653"):
        assert authorize("GET", {"Host": junk, "Authorization": "Bearer " + "a" * 43},
                         policy, verify).code == "bad_host"


def test_the_token_is_hardened_before_it_is_written(tmp_path, monkeypatch):
    seen = []
    real = api_auth.harden_windows_acl

    def spy(path):
        seen.append(os.path.getsize(path))                    # Größe zum Zeitpunkt der Härtung
        real(path)
    monkeypatch.setattr(api_auth, "harden_windows_acl", spy)

    token = load_or_create_token(str(tmp_path))

    assert seen == [0]                                        # die Datei war noch leer
    assert (tmp_path / TOKEN_FILENAME).read_text(encoding="ascii") == token
```

Hänge ans Ende von `tests/test_single_instance.py` an:

```python
def test_the_instance_secret_is_hardened_before_it_is_written(tmp_path, monkeypatch):
    import src.single_instance as si
    seen = []
    real = si.harden_windows_acl

    def spy(path):
        seen.append(os.path.getsize(path))
        real(path)
    monkeypatch.setattr(si, "harden_windows_acl", spy)

    si._write_secret_atomic(str(tmp_path / "instance-secret"), b"s" * 32)

    assert seen == [0]
    assert (tmp_path / "instance-secret").read_bytes() == b"s" * 32
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest -q -p no:cacheprovider -x`
Expected: FAIL — BOM-Datei wird verworfen, `AuthResult(200, …)` ist ok, NBSP im Host wird abgeschnitten, die Temp-Datei ist bei der Härtung schon beschrieben (`32 != 0`).

- [ ] **Step 3: Implement**

In `src/api_auth.py` ersetze

```python
    if len(data) > _MAX_FILE_BYTES:
        return None
    candidate = data.strip().decode("ascii", errors="replace")
```

durch

```python
    if len(data) > _MAX_FILE_BYTES:
        return None
    if data.startswith(_UTF8_BOM):          # Windows-Editor, PowerShell 7 `>`
        data = data[len(_UTF8_BOM):]
    candidate = data.strip().decode("ascii", errors="replace")
```

In `src/api_auth.py` ersetze

```python
_MAX_FILE_BYTES = 1024
```

durch

```python
_MAX_FILE_BYTES = 1024
_UTF8_BOM = b"\xef\xbb\xbf"
```

In `src/api_auth.py` ersetze

```python
    """Das Token aus einem Dateiinhalt, oder `None`, wenn es keines ist (zu
    groß, falsches Format). Ein Zeilenumbruch am Ende wird toleriert."""
```

durch

```python
    """Das Token aus einem Dateiinhalt, oder `None`, wenn es keines ist (zu
    groß, falsches Format). Ein Zeilenumbruch am Ende und ein UTF-8-BOM am Anfang
    werden toleriert; UTF-16 (Windows PowerShell 5.1 `>`) nicht — die Datei gilt
    dann als ungültig und wird durch ein frisches Token ersetzt."""
```

In `src/api_auth.py` ersetze

```python
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(token)
        try:
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600; Win: No-op
        except OSError:
            _log.debug("chmod 0600 auf %s fehlgeschlagen", tmp_path, exc_info=True)
        harden_windows_acl(tmp_path)
        attempts = 5
```

durch

```python
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            # Erst härten, dann schreiben: die Temp-Datei ist beim Anlegen leer, das
            # Token steht nie in einer Datei mit geerbten Rechten (unter Windows
            # sonst bis zum `icacls`-Aufruf lesbar).
            try:
                os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600; Win: No-op
            except OSError:
                _log.debug("chmod 0600 auf %s fehlgeschlagen", tmp_path, exc_info=True)
            harden_windows_acl(tmp_path)
            f.write(token)
        attempts = 5
```

In `src/api_auth.py` ersetze

```python
    @property
    def ok(self) -> bool:
        return self.status == 200
```

durch

```python
    @property
    def ok(self) -> bool:
        # Ein 200 ohne Principal ist kein Zugang: `handle` bekäme `None`.
        return self.status == 200 and self.principal is not None
```

In `src/api_auth.py` ersetze

```python
    if h.get("host", "").strip().lower() not in policy.allowed_hosts:
```

durch

```python
    # Nur HTTP-OWS (Leerzeichen, Tab) abschneiden: `str.strip()` nähme auch NBSP,
    # U+2028 und \x85.
    if h.get("host", "").strip(" \t").lower() not in policy.allowed_hosts:
```

In `src/single_instance.py` ersetze

```python
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(secret)
        try:
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600; Win: No-op
        except OSError:
            pass
        harden_windows_acl(tmp_path)
        attempts = 5
```

durch

```python
    try:
        with os.fdopen(fd, "wb") as f:
            # Erst härten, dann schreiben (die Temp-Datei ist beim Anlegen leer).
            try:
                os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600; Win: No-op
            except OSError:
                pass
            harden_windows_acl(tmp_path)
            f.write(secret)
        attempts = 5
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_api_auth.py tests/test_single_instance.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check .`
Expected: PASS, `All checks passed!`.

- [ ] **Step 5: Commit**

~~~bash
git add src/api_auth.py src/single_instance.py tests/test_api_auth.py tests/test_single_instance.py
git commit -m "fix(api): Auth-Kleinigkeiten und Token-Datei (#233)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

### Task 2: `ApiService`: Rotation und Beenden

**Files:** Tests `tests/test_api_service.py`; Quelltext `src/api_service.py`.

**Interfaces:** Produces: `ApiService.rotate()` fängt jede Ausnahme (Ergebnis `REASON_ROTATE_FAILED`), startet nach erfolgreicher Rotation die API, wenn der Fehler `token_unavailable` war, und stoppt den Server, wenn `shutdown()` währenddessen aufgegeben hat; `_reconcile_guarded()` ist `_reconcile_locked` mit Fehler-zu-Status-Umwandlung.

- [ ] **Step 1: Write the failing tests**

Hänge ans Ende von `tests/test_api_service.py` an:

```python
# --- Härtung aus dem Review von PR 3 (#233) -----------------------------------------------

def test_an_unexpected_error_in_rotation_is_a_failed_result_not_a_dead_worker(tmp_path, monkeypatch, caplog):
    service = make_service(tmp_path, {"api_enabled": False, "api_port": free_port()})

    def boom(base_path):
        raise ValueError("kein OSError")

    monkeypatch.setattr(api_service, "rotate_token", boom)

    with caplog.at_level("WARNING"):
        result = service.rotate()

    assert result == RotateResult(False, REASON_ROTATE_FAILED)
    assert "konnte nicht erneuert" in caplog.text


def test_a_successful_rotation_clears_the_token_unavailable_error(tmp_path, monkeypatch):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    monkeypatch.setattr(api_service, "load_or_create_token", lambda base_path: None)
    service.apply()
    assert service.status.reason == "token_unavailable"
    monkeypatch.undo()                                  # das Token ist wieder erzeugbar
    try:
        result = service.rotate()

        assert result == RotateResult(True)
        assert service.status.state == STATE_RUNNING and service.status.port == port
        assert get_status_code(port, token_of(tmp_path)) == 200
    finally:
        service.shutdown()


def test_a_shutdown_that_gave_up_during_a_rotation_still_stops_the_server(tmp_path, monkeypatch):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()
    assert not port_is_closed(port)
    entered, release = threading.Event(), threading.Event()
    real = api_service.rotate_token

    def slow(base_path):
        entered.set()
        release.wait(5)
        return real(base_path)

    monkeypatch.setattr(api_service, "rotate_token", slow)
    worker = threading.Thread(target=service.rotate)
    worker.start()
    assert entered.wait(5)

    service.shutdown(lock_timeout=0.05)                 # wartet nicht auf die Rotation
    assert not port_is_closed(port)                     # der Server läuft noch ...
    release.set()
    worker.join(5)

    assert port_is_closed(port)                         # ... bis die Rotation fertig ist
    assert service.status.state == STATE_OFF
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest -q -p no:cacheprovider -x`
Expected: FAIL — drei Tests: ein `ValueError` in `rotate_token` fliegt durch, der Status bleibt `token_unavailable`, der Port bleibt nach der aufgegebenen `shutdown()` offen.

- [ ] **Step 3: Implement**

In `src/api_service.py` ersetze

```python
    def _reconcile(self) -> ApiStatus:
        with self._lock:
            try:
                return self._reconcile_locked()
            except Exception:
                # Der Runner würde den Fehler nur loggen und `on_done` nie
                # rufen — der Status bliebe stehen. Hier wird er zum Zustand.
                _log.exception("Lokale API: Start/Stopp fehlgeschlagen")
                self._stop_server()
                self._status = ApiStatus(STATE_ERROR, None, REASON_START_FAILED)
                return self._status
```

durch

```python
    def _reconcile(self) -> ApiStatus:
        with self._lock:
            return self._reconcile_guarded()

    def _reconcile_guarded(self) -> ApiStatus:
        """`_reconcile_locked`, aber ein Fehler wird zum Status. Der Aufrufer hält
        `_lock`."""
        try:
            return self._reconcile_locked()
        except Exception:
            # Der Runner würde den Fehler nur loggen und `on_done` nie
            # rufen — der Status bliebe stehen. Hier wird er zum Zustand.
            _log.exception("Lokale API: Start/Stopp fehlgeschlagen")
            self._stop_server()
            self._status = ApiStatus(STATE_ERROR, None, REASON_START_FAILED)
            return self._status
```

In `src/api_service.py` ersetze

```python
            try:
                token = rotate_token(self._base_path)
            except OSError:
                _log.warning("Lokale API: Token konnte nicht erneuert werden",
                             exc_info=True)
                return RotateResult(False, REASON_ROTATE_FAILED)
            if self._server is not None:
                self._server.set_verifier(single_token_verifier(token))
            return RotateResult(True)
```

durch

```python
            try:
                token = rotate_token(self._base_path)
            except Exception:
                # Nicht nur OSError: der Runner ruft bei einer anderen Ausnahme
                # `on_done` nie, der Tab bliebe mit toten Knöpfen und ohne Meldung stehen.
                _log.warning("Lokale API: Token konnte nicht erneuert werden",
                             exc_info=True)
                return RotateResult(False, REASON_ROTATE_FAILED)
            if self._server is not None:
                self._server.set_verifier(single_token_verifier(token))
            elif self._status.reason == REASON_TOKEN_UNAVAILABLE:
                # Das Token war der Grund, warum die API nicht lief: jetzt gibt es
                # eines, also starten (sonst stünde der Fehler bis zum nächsten apply()).
                self._reconcile_guarded()
            if self._closed:
                # `shutdown()` hat auf diesen Lock nur bis zum Timeout gewartet und
                # aufgegeben; den Server stoppt dann der, der den Lock hielt.
                self._stop_server()
                self._status = ApiStatus(STATE_OFF)
            return RotateResult(True)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_api_service.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check .`
Expected: PASS, `All checks passed!`.

- [ ] **Step 5: Commit**

~~~bash
git add src/api_service.py tests/test_api_service.py
git commit -m "fix(api): Rotation fängt alle Fehler, räumt den Token-Fehler ab und stoppt nach aufgegebenem Beenden (#233)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

### Task 3: Server: Allow, Backlog

**Files:** Tests `tests/test_api_server.py`; Quelltext `src/api_server.py`, `src/api_routes.py`.

**Interfaces:** Produces: `api_routes.routed_methods() -> frozenset[str]`; das 405 vor dem Routing sendet `Allow: DELETE, GET, PUT`; `_ApiHTTPServer.request_queue_size = 128`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_api_server.py` ersetze

```python
        assert response.getheader("Allow") == "DELETE, GET, POST, PUT"
```

durch

```python
        assert response.getheader("Allow") == "DELETE, GET, PUT"       # kein POST: keine Route kennt es
```

In `tests/test_api_server.py` ersetze

```python
def test_too_many_query_fields_are_400(server):
    query = "&".join(f"a{i}=1" for i in range(500))
    response, body, _ = http_call(server, "GET", f"/v1/entries?{query}")
    assert response.status == 400
```

durch

```python

```

Hänge ans Ende von `tests/test_api_server.py` an:

```python
# --- Härtung aus dem Review von PR 2 (#233) -----------------------------------------------

@pytest.mark.parametrize("method", ["OPTIONS", "HEAD", "PATCH", "TRACE"])
def test_allow_names_only_methods_that_a_route_can_serve(server, method):
    response, _body, _ = http_call(server, method, "/v1/status")
    assert response.status == 405
    assert response.getheader("Allow") == "DELETE, GET, PUT"       # kein POST


def test_the_listen_backlog_is_larger_than_the_default():
    assert api_server._ApiHTTPServer.request_queue_size >= 64


def test_too_many_query_fields_are_rejected_before_the_parameters_are_checked(server):
    # 30 gleichnamige Felder: ohne die Obergrenze käme "duplicate_parameter",
    # mit ihr scheitert schon das Parsen der Query.
    query = "&".join("from=2026-01-01" for _ in range(30))
    response, body, _ = http_call(server, "GET", f"/v1/entries?{query}")
    assert response.status == 400
    assert body["error"]["code"] == "invalid_query"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest -q -p no:cacheprovider -x`
Expected: FAIL — `Allow` enthält noch `POST`, der Backlog ist 5.

- [ ] **Step 3: Implement**

In `src/api_server.py` ersetze

```python
from src.api_auth import ALLOWED_METHODS, AuthResult, Policy, TokenVerifier, authorize
```

durch

```python
from src.api_auth import AuthResult, Policy, TokenVerifier, authorize
```

In `src/api_routes.py` ersetze

```python
def handle(request: ApiRequest, ctx: ApiContext, principal: Principal) -> ApiResponse:
```

durch

```python
def routed_methods() -> frozenset[str]:
    """Die Methoden, die irgendeine Route kennt (für `Allow` bei einem 405, das
    `authorize` vor dem Routing ausspricht)."""
    return frozenset(route.method for route in ROUTES)


def handle(request: ApiRequest, ctx: ApiContext, principal: Principal) -> ApiResponse:
```

In `src/api_server.py` ersetze

```python
from src.api_routes import ApiContext, ApiRequest, ApiResponse, error_response, handle
```

durch

```python
from src.api_routes import (
    ApiContext, ApiRequest, ApiResponse, error_response, handle, routed_methods,
)
```

In `src/api_server.py` ersetze

```python
        headers["Allow"] = ", ".join(sorted(ALLOWED_METHODS))
```

durch

```python
        # Was die Routen tatsächlich können, nicht `ALLOWED_METHODS`: POST ist für
        # #221 vorgesehen, aber keine Route kennt es.
        headers["Allow"] = ", ".join(sorted(routed_methods()))
```

In `src/api_server.py` ersetze

```python
    max_connections = _MAX_CONNECTIONS
```

durch

```python
    max_connections = _MAX_CONNECTIONS
    # Der Standard (5) lässt bei einem Schwung gleichzeitiger Verbindungen die
    # Warteschlange überlaufen: Latenz bis über eine Sekunde, unter Windows
    # abgewiesene Verbindungen. Angenommen wird ohnehin sofort (Obergrenze oben).
    request_queue_size = 128
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_api_server.py tests/test_api_routes.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check .`
Expected: PASS, `All checks passed!`.

- [ ] **Step 5: Commit**

~~~bash
git add src/api_server.py src/api_routes.py tests/test_api_server.py
git commit -m "fix(api): Allow nennt nur Routenmethoden, größerer Backlog (#233)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

### Task 4: Fehlermeldung zu `invalid_slot` kürzen

**Files:** Tests `tests/test_api_entry_write.py`; Quelltext `src/api_entry_write.py`.

**Interfaces:** Produces: die Meldung nennt Schlüsselnamen mit höchstens 40 Zeichen.

- [ ] **Step 1: Write the failing tests**

Hänge ans Ende von `tests/test_api_entry_write.py` an:

```python
def test_a_huge_key_name_is_cut_in_the_error_message():
    body = json.dumps({"slots": [{"start": "08:00", "end": "09:00", "x" * 200_000: 1}]}).encode()

    with pytest.raises(WriteError) as info:
        w.parse_day_body(body)

    assert info.value.code == "invalid_slot"
    assert len(info.value.message) < 600
    assert "x" * 41 not in info.value.message
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest -q -p no:cacheprovider -x`
Expected: FAIL — die Meldung enthält den 200 000 Zeichen langen Schlüssel.

- [ ] **Step 3: Implement**

In `src/api_entry_write.py` ersetze

```python
            f"gefunden: {sorted(keys)[:10]}.")
```

durch

```python
            f"gefunden: {sorted(str(key)[:_KEY_ECHO_MAX] for key in keys)[:10]}.")
```

In `src/api_entry_write.py` ersetze

```python
_log = logging.getLogger(__name__)
```

durch

```python
_log = logging.getLogger(__name__)

# Schlüsselnamen aus dem Body kommen mit höchstens 1 MiB Länge; in der Fehlermeldung
# stehen sie gekürzt (wie `_NAME_ECHO_MAX` bei den Query-Parametern).
_KEY_ECHO_MAX = 40
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_api_entry_write.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check .`
Expected: PASS, `All checks passed!`.

- [ ] **Step 5: Commit**

~~~bash
git add src/api_entry_write.py tests/test_api_entry_write.py
git commit -m "fix(api): Schlüsselnamen in der Fehlermeldung kürzen (#233)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

### Task 5: Texte, Docstrings und Doku

**Files:** Tests `tests/test_tab_rules.py`; Quelltext `src/dialogs/settings_dialog/tab_rules.py` sowie Doku und Docstrings.

**Interfaces:** Produces: `TOKEN_MISSING` sagt nichts Falsches mehr; Docstrings und Doku stimmen mit dem Verhalten überein.

- [ ] **Step 1: Write the failing tests**

Hänge ans Ende von `tests/test_tab_rules.py` an:

```python
def test_the_missing_token_text_does_not_promise_a_first_time_creation():
    # Die Maske steht auch, wenn die API läuft und die Datei extern gelöscht wurde.
    assert "ersten" not in tr.TOKEN_MISSING
    assert "lesbar" in tr.TOKEN_MISSING and "Einschalten" in tr.TOKEN_MISSING
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest -q -p no:cacheprovider -x`
Expected: FAIL — `TOKEN_MISSING` enthält noch „ersten“.

- [ ] **Step 3: Implement**

In `src/dialogs/settings_dialog/tab_rules.py` ersetze

```python
TOKEN_MISSING = "Wird beim ersten Einschalten erzeugt."
```

durch

```python
TOKEN_MISSING = "Kein lesbares Token — wird beim Einschalten der API erzeugt."
```

In `src/CLAUDE.md` ersetze

```markdown
Wer einen fünften Secret-Schreibpfad baut, ruft diesen Helfer mit auf.
```

durch

```markdown
Wer einen sechsten Secret-Schreibpfad baut, ruft diesen Helfer mit auf.
```

In `src/CLAUDE.md` ersetze

```markdown
Ein Daemon-Thread mit eigener `handle_request()`-Schleife (kein
  `serve_forever()`/`shutdown()`: das blockiert für immer, wenn es vor dem Eintritt
  in die Schleife gerufen wird), pro Verbindung ein Daemon-Thread.
```

durch

```markdown
Ein Daemon-Thread mit eigener `handle_request()`-Schleife (kein
  `serve_forever()`/`shutdown()`: `shutdown()` wartet, bis die Schleife verlassen
  wurde, und blockiert für immer, wenn der Thread nie dorthin kommt — Preis der
  eigenen Schleife sind rund zehn Aufwachvorgänge pro Sekunde), pro Verbindung ein
  Daemon-Thread.
```

In `src/api_server.py` ersetze

```python
Absichtlich NICHT `serve_forever()`/`shutdown()`: `shutdown()` blockiert für
immer, wenn es vor dem Eintritt in `serve_forever()` gerufen wird (Beenden
direkt nach dem Start). Stattdessen pollt eine eigene Schleife mit
`handle_request()` und einem 0,1-s-Timeout gegen ein `Event`.
```

durch

```python
Absichtlich NICHT `serve_forever()`/`shutdown()`: `shutdown()` wartet, bis
`serve_forever()` die Schleife verlassen hat, und blockiert für immer, wenn der
Thread nie dorthin kommt (er startet nicht, oder `start()` scheitert nach dem
Bind). Stattdessen pollt eine eigene Schleife mit `handle_request()` und einem
0,1-s-Timeout gegen ein `Event`; der Preis sind rund zehn Aufwachvorgänge pro
Sekunde.
```

In `src/api_service.py` ersetze

```python
`ApiStatus` samt Grund, den der Settings-Tab (PR 3) anzeigt.
```

durch

```python
`ApiStatus` samt Grund, den der Settings-Tab anzeigt.
```

In `src/api_summary.py` ersetze

```python
Gleichstand nach Name, die leere Kategorie zuletzt (wie im Bericht). `weeks` führt jede ISO-Woche auf, die der Zeitraum
```

durch

```python
Gleichstand nach Name (Groß-/Kleinschreibung beachtend, anders als der Bericht), die
    leere Kategorie zuletzt. `weeks` führt jede ISO-Woche auf, die der Zeitraum
```

In `docs/known-limitations.md` ersetze

```markdown
  die App den Port exklusiv (`SO_EXCLUSIVEADDRUSE`); ein anderer Prozess, der ihn
  vorher belegt, ist von dort aus nicht zu verdrängen.
```

durch

```markdown
  die App den Port exklusiv (`SO_EXCLUSIVEADDRUSE`); ein anderer Prozess, der ihn
  vorher belegt, ist von dort aus nicht zu verdrängen. Unter Linux und macOS bindet die
  App nicht exklusiv: auch dort kann ein anderer Nutzer desselben Rechners den Port vor
  der App belegen (`port_in_use`), oder ein fremder Prozess antwortet unter dem Port.
  Clients verbinden mit `127.0.0.1`, nicht mit `localhost` (gebunden ist nur IPv4).
- **Das Token wird beim Start gelesen.** Ein extern gelöschtes, geändertes oder
  rotiertes `api-token` wirkt erst nach einem Neustart der App; „Neu erzeugen“ im Tab
  schreibt dagegen die Datei und tauscht den Prüfer des laufenden Servers. Der Tab liest
  die Datei und kann deshalb vom laufenden Server abweichen. Die Datei muss ASCII sein
  (ein UTF-8-BOM und ein Zeilenumbruch werden toleriert); UTF-16, wie ihn Windows
  PowerShell 5.1 mit `>` schreibt, gilt als ungültig und wird durch ein neues Token
  ersetzt.
```

In `docs/superpowers/specs/2026-10-06-lokale-api-design.md` ersetze

```markdown
`authorize(request, policy) -> AuthResult` als **eine** Funktion.
```

durch

```markdown
`authorize(method, headers, policy, verifier) -> AuthResult` als **eine** Funktion.
```

In `README.md` ersetze

```markdown
und, bei aktivem Werkstudenten-Limit, `limit_minutes` und `exceeded`)
```

durch

```markdown
und `limit_minutes` (`null` ohne aktives Werkstudenten-Limit) und `exceeded`)
```

In `README.md` ersetze

```markdown
Es gelten die Jahre 2000–2100; ungültige Pfade sind `400`, Jahre außerhalb `422`.
```

durch

```markdown
Es gelten die Jahre 2000–2100: Jahre außerhalb davon sind `422`, ungültige Pfade (auch Jahr `0000` und `9999`) `400`. Bei einem Monat kann `weeks[]` eine Woche des Vorjahres enthalten (KW 52/1999 bei `2000-01`), die `/v1/summary/week/…` selbst ablehnt.
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest -q -p no:cacheprovider && ruff check .` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check .`
Expected: PASS, `All checks passed!`.

- [ ] **Step 5: Commit**

~~~bash
git add README.md CLAUDE.md docs src tests
git commit -m "docs(api): Texte und Doku aus dem Review nachgezogen (#233)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

## Mutationsprüfung (nach Task 5, vor dem Review)

| Datei | Mutation | Erwartet rot |
|---|---|---|
| `api_auth.py` | `return self.status == 200 and self.principal is not None` → `return self.status == 200` | `test_an_auth_result_with_status_200_but_no_principal_is_not_ok` |
| `api_auth.py` | BOM-Zweig in `_valid_token` entfernen | `test_a_token_file_with_a_utf8_bom_is_still_the_token` |
| `api_auth.py` | `.strip(" \t")` → `.strip()` | `test_the_host_header_is_trimmed_of_http_whitespace_only` |
| `api_auth.py` | Härtung nach dem Schreiben | `test_the_token_is_hardened_before_it_is_written` |
| `single_instance.py` | Härtung nach dem Schreiben | `test_the_instance_secret_is_hardened_before_it_is_written` |
| `api_service.py` | `except Exception:` in `rotate` → `except OSError:` | `test_an_unexpected_error_in_rotation_is_a_failed_result_not_a_dead_worker` |
| `api_service.py` | `elif self._status.reason == REASON_TOKEN_UNAVAILABLE:`-Zweig entfernen | `test_a_successful_rotation_clears_the_token_unavailable_error` |
| `api_service.py` | `if self._closed:`-Block am Ende von `rotate` entfernen | `test_a_shutdown_that_gave_up_during_a_rotation_still_stops_the_server` |
| `api_server.py` | `routed_methods()` → `ALLOWED_METHODS` | `test_allow_names_only_methods_that_a_route_can_serve` |
| `api_server.py` | `request_queue_size = 128` entfernen | `test_the_listen_backlog_is_larger_than_the_default` |
| `api_server.py` | `max_num_fields` aus `parse_qs` entfernen | `test_too_many_query_fields_are_rejected_before_the_parameters_are_checked` |
| `api_entry_write.py` | `[:_KEY_ECHO_MAX]` entfernen | `test_a_huge_key_name_is_cut_in_the_error_message` |
| `tab_rules.py` | `TOKEN_MISSING` zurück auf den alten Text | `test_the_missing_token_text_does_not_promise_a_first_time_creation` |

## Finale

Nach Task 5: Review über den ganzen Branch mit einem frischen Reviewer auf dem leistungsfähigsten Modell (Review Focus und Rulings mitgeben; aktiver Angriff auf Rotation/Beenden/Token-Datei), Critical/Important in **einem** Fix-Durchlauf (je Fix ein Test, der zuerst rot war), Minors ins Ledger und in ein Issue. Danach `finishing-a-development-branch`: PR gegen `feat/storage-haerten` (`Refs #233`, `Refs #92`), in den Stack #236 hängen, in #233 die erledigten Punkte abhaken.
