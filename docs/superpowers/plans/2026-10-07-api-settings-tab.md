# Lokale API, PR 3: Settings-Tab und Token-Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die lokale API ist in der App bedienbar: ein neuer Tab „API" (Schalter, Port, Status, Token kopieren, Token neu erzeugen) und die dafür nötigen Erweiterungen von `ApiService` (Zustand „startet", aktueller Status statt veraltetem Ergebnis, `rotate()` unter demselben Lock wie der Start, `read_token()`).

**Architecture:** Alles, was entscheidet, ist Tk-frei und getestet: `api_auth.read_token`, `ApiService` (`rotate`, `read_token`, `STATE_STARTING`) und `tab_rules` (`validate_api`, `api_updates`, `port_hint`, `status_view`, `curl_example`). Der Tab selbst (`tab_api.py`) ist reine Verdrahtung auf `theme.Form`; seine blockierenden Aufrufe laufen über den `BackgroundTaskRunner`, der Status kommt per `after`-Poll aus `ApiService.status`. `open_settings_dialog` bekommt `api_service=…` und hängt den Tab zwischen „Google" und „App" ein.

**Tech Stack:** Python 3.12, Tkinter (nur `tab_api.py`), pytest. Keine neue Abhängigkeit.

**Spec:** `docs/superpowers/specs/2026-10-06-lokale-api-design.md` (Abschnitt „Bedienung"). Offene Punkte aus Issue #233 (Checkliste Server-PR und Kommentar zu #237).

**Branching:** Stack. `git switch feat/api-server-read && git switch -c feat/api-settings-tab`. PR 3 zielt auf `feat/api-server-read` (PR #237) und wird danach mit `POST /repos/Xveyn/Zeiterfassung/stacks/236/add` an den Stack gehängt. PR-Text enthält `Refs #92`, **kein** `Closes`.

## Global Constraints

- Tk-frei bleiben `api_auth`, `api_service`, `tab_rules`; nur `tab_api.py` und `dialog.py` importieren Tk. Neue/erweiterte Tk-freie Module bleiben vollständig annotiert (`ANNOTATED_MODULES`).
- Das Token wird **nie angezeigt**, nur in die Zwischenablage kopiert. In keiner Meldung, keinem Log und keinem Widget-Text steht der Token-Wert.
- `rotate()` und `read_token()` blockieren (Dateizugriff, unter Windows `icacls`): in der UI **nur über `BackgroundTaskRunner.run`**, nie im UI-Thread.
- Rotation und Server-Start laufen unter **demselben** `ApiService._lock`; nach jeder Verschränkung stimmt die Token-Datei mit dem vom Server akzeptierten Token überein.
- Scheitert die Rotation, bleibt das alte Token gültig (Datei und Verifier unverändert). Nach `shutdown()` tut `rotate()` nichts.
- `read_token()` legt nichts an, ändert keine Rechte und ruft kein `icacls`.
- `ApiService._publish` meldet den **aktuellen** `.status`, nie das (evtl. veraltete) Ergebnis eines Workers. „Läuft schon" meldet `RUNNING`, nie `STARTING`; unveränderte Einstellungen lösen kein `STARTING`-Flackern aus.
- Port-Hinweise: 20000–31999 (Bereich des Mehrfachstart-Schutzes, aus `single_instance` abgeleitet, per Test gegen Drift gesichert) und ab 32768 (Ephemeral). Gültig bleibt 1024–65535.
- Der Tab ist ein normaler `SettingsTab` (`title`, `fields`, `values()`, `validate()`, `save()`, `load()`); nur `api_enabled` und `api_port` sind Formularfelder. Kopieren und Neuerzeugen sind Aktionen, die sofort wirken.
- Jeder `except Exception`/`BaseException` loggt, meldet oder begründet im Handler; `ruff check .` sauber.
- UI-Texte deutsch; Pixelangaben (falls nötig) über `theme.px()`.

## Review Focus

Eingaben und Zustände, die die Spec nahelegt, aber keine Task erzwingt. Jede Zeile ist in der genannten Task gepinnt.

1. **Rotation gegen einen laufenden Start:** egal wie sich beide verschränken, am Ende akzeptiert der Server genau das Token, das in der Datei steht. Task 2.
2. **Rotationsfehler und -Randfälle:** Schreibfehler lässt das alte Token gültig; Rotation nach `shutdown()` ändert nichts; Rotation ohne laufenden Server schreibt nur die Datei und startet nichts. Task 2.
3. **Statusanzeige unter Last:** kein `STARTING`-Flackern bei unveränderten Einstellungen, kein veralteter Status durch einen zu spät fertigen Worker, „läuft schon" meldet `RUNNING`. Task 2.
4. **Token lesen ist rein lesend:** keine Datei angelegt, Modus (z. B. 0644) unverändert, kein `harden_windows_acl`; fehlend, unlesbar oder ungültig → `None`. Task 1.
5. **Port-Eingaben im Feld:** Leerzeichen, Nicht-ASCII-Ziffern, `08080`, extrem lange Ziffernfolgen, `0`, `80`, `70000`, `17653.5` blockieren das Speichern mit klarer Meldung; die Hinweisgrenzen stimmen mit `single_instance` überein. Task 3.
6. **Dialog ohne `api_service`:** kein Tab, kein Crash; `initial_tab="api"` springt auf den Tab; Reihenfolge Google → API → App. Task 4.

---

### Task 1: `api_auth.read_token` — Token rein lesend

**Files:**
- Modify: `src/api_auth.py`
- Modify: `tests/test_api_auth.py`

**Interfaces:**
- Consumes: `api_auth._TOKEN_RE`, `_MAX_FILE_BYTES`, `TOKEN_FILENAME`.
- Produces (Task 2 verlässt sich darauf):
  - `read_token(base_path: str) -> str | None` — liest `<base_path>/api-token`; `None` bei fehlender, unlesbarer oder ungültiger Datei; legt nichts an, ändert nichts, härtet nichts.
  - `_valid_token(data: bytes) -> str | None` (intern, von `load_or_create_token` und `read_token` geteilt).

- [ ] **Step 1: Failing tests schreiben**

An `tests/test_api_auth.py` anfügen (die Datei importiert `os`, `stat`, `sys`, `pytest`, `api_auth`, `TOKEN_FILENAME`, `generate_token`; `read_token` dazu importieren: in der Importzeile `from src.api_auth import (…)` den Namen `read_token` ergänzen):

```python
# --- read_token: rein lesend (PR 3, Settings-Tab „Token kopieren") --------------

def test_read_token_returns_the_stored_token(tmp_path):
    token = generate_token()
    (tmp_path / TOKEN_FILENAME).write_text(token, encoding="ascii")

    assert read_token(str(tmp_path)) == token


def test_read_token_tolerates_a_trailing_newline(tmp_path):
    token = generate_token()
    (tmp_path / TOKEN_FILENAME).write_bytes(token.encode("ascii") + b"\r\n")

    assert read_token(str(tmp_path)) == token


def test_read_token_without_a_file_is_none_and_creates_nothing(tmp_path):
    assert read_token(str(tmp_path)) is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("content", [b"", b"zu-kurz", b"x" * 5000, b"\xff\xfe" * 30,
                                     b"a" * 42, b"a" * 44])
def test_read_token_with_invalid_content_is_none_and_leaves_the_file_alone(tmp_path, content):
    path = tmp_path / TOKEN_FILENAME
    path.write_bytes(content)

    assert read_token(str(tmp_path)) is None
    assert path.read_bytes() == content


def test_read_token_unreadable_is_none(tmp_path, monkeypatch):
    (tmp_path / TOKEN_FILENAME).write_text(generate_token(), encoding="ascii")
    real_open = open

    def fake_open(file, *args, **kwargs):
        if os.fspath(file).endswith(TOKEN_FILENAME):
            raise PermissionError("denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(api_auth, "open", fake_open, raising=False)

    assert read_token(str(tmp_path)) is None


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Dateimodi sind unter Windows kein Maßstab")
def test_read_token_does_not_touch_the_file_mode(tmp_path):
    path = tmp_path / TOKEN_FILENAME
    path.write_text(generate_token(), encoding="ascii")
    os.chmod(path, 0o644)

    read_token(str(tmp_path))

    assert stat.S_IMODE(os.stat(path).st_mode) == 0o644


def test_read_token_never_hardens_the_file(tmp_path, monkeypatch):
    (tmp_path / TOKEN_FILENAME).write_text(generate_token(), encoding="ascii")
    calls = []
    monkeypatch.setattr(api_auth, "harden_windows_acl", calls.append)

    read_token(str(tmp_path))

    assert calls == []                  # `icacls` bis 15 s: nichts für „nur kopieren"
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `python3 -m pytest tests/test_api_auth.py -q -p no:cacheprovider`
Expected: FAIL beim Import (`cannot import name 'read_token'`).

- [ ] **Step 3: Implementieren**

In `src/api_auth.py` die Erkennung eines gültigen Tokens in eine geteilte Funktion ziehen und `read_token` ergänzen. Zuerst vor `def _write_token_atomic` einfügen:

```python
def _valid_token(data: bytes) -> str | None:
    """Das Token aus einem Dateiinhalt, oder `None`, wenn es keines ist (zu
    groß, falsches Format). Ein Zeilenumbruch am Ende wird toleriert."""
    if len(data) > _MAX_FILE_BYTES:
        return None
    candidate = data.strip().decode("ascii", errors="replace")
    return candidate if _TOKEN_RE.fullmatch(candidate) else None
```

In `load_or_create_token` den Block

```python
    if data is not None:
        candidate = data.strip().decode("ascii", errors="replace")
        if len(data) <= _MAX_FILE_BYTES and _TOKEN_RE.fullmatch(candidate):
            _harden_existing(path)
            return candidate
        _log.warning("API-Token-Datei ungültig — wird neu erzeugt")
```

ersetzen durch

```python
    if data is not None:
        candidate = _valid_token(data)
        if candidate is not None:
            _harden_existing(path)
            return candidate
        _log.warning("API-Token-Datei ungültig — wird neu erzeugt")
```

und hinter `load_or_create_token` (vor `rotate_token`) einfügen:

```python
def read_token(base_path: str) -> str | None:
    """Liest das Token, **ohne etwas anzulegen, zu ändern oder zu härten** —
    für „Token kopieren" im Settings-Tab. `None`, wenn die Datei fehlt, nicht
    lesbar oder ungültig ist."""
    try:
        with open(os.path.join(base_path, TOKEN_FILENAME), "rb") as f:
            data = f.read(_MAX_FILE_BYTES + 1)
    except OSError:
        _log.debug("API-Token nicht lesbar", exc_info=True)
        return None
    return _valid_token(data)
```

- [ ] **Step 4: Tests laufen lassen**

Run: `python3 -m pytest tests/test_api_auth.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:cacheprovider`
Expected: alle PASS (die bestehenden `load_or_create_token`-Tests belegen, dass die Auslagerung nichts verändert).

- [ ] **Step 5: Commit**

```bash
git add src/api_auth.py tests/test_api_auth.py
git commit -m "$(cat <<'EOF'
feat(api): Token rein lesend lesen (#92)

read_token legt nichts an, ändert keine Rechte und ruft kein icacls: für
„Token kopieren" im Settings-Tab. Die Erkennung eines gültigen Tokens ist
mit load_or_create_token geteilt.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `ApiService` — Zustand „startet", aktueller Status, Rotation, Token lesen

**Files:**
- Modify: `src/api_service.py`
- Modify: `tests/test_api_service.py`

**Interfaces:**
- Consumes: `api_auth.read_token`, `rotate_token(base_path) -> str` (wirft `OSError`), `single_token_verifier`; `ApiServer.set_verifier(verifier)`.
- Produces (Task 3 und 4 verlassen sich darauf):
  - `STATE_STARTING = "starting"`, `REASON_CLOSED = "closed"`, `REASON_ROTATE_FAILED = "rotate_failed"`
  - `RotateResult(ok: bool, reason: str = "")` (frozen)
  - `ApiService.rotate() -> RotateResult` (blockiert; nur im Worker)
  - `ApiService.read_token() -> str | None`
  - Verhalten: `apply()` setzt `ApiStatus(STATE_STARTING, port)` sofort, wenn die API eingeschaltet, der Port gültig und nicht schon dort ein Server läuft; `_publish` meldet `self.status`; der „läuft schon"-Zweig setzt `RUNNING`.

- [ ] **Step 1: Failing tests schreiben**

In `tests/test_api_service.py` die Importzeile

```python
from src.api_service import (
    DEFAULT_PORT, REASON_INVALID_PORT, REASON_PORT_IN_USE, REASON_TOKEN_UNAVAILABLE,
    STATE_ERROR, STATE_OFF, STATE_RUNNING, ApiService, ApiStatus, parse_port,
)
```

ersetzen durch

```python
from src.api_service import (
    DEFAULT_PORT, REASON_CLOSED, REASON_INVALID_PORT, REASON_PORT_IN_USE,
    REASON_ROTATE_FAILED, REASON_TOKEN_UNAVAILABLE, STATE_ERROR, STATE_OFF,
    STATE_RUNNING, STATE_STARTING, ApiService, ApiStatus, RotateResult, parse_port,
)
```

und am Dateiende anfügen:

```python
# --- PR 3: Zustand „startet", aktueller Status, Rotation, Token lesen -------------

def deferred_run(jobs):
    def run(fn, on_done=None):
        jobs.append((fn, on_done))
    return run


def test_apply_shows_starting_before_the_worker_has_run(tmp_path):
    jobs = []
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port},
                           run=deferred_run(jobs))

    service.apply()
    assert service.status == ApiStatus(STATE_STARTING, port)

    fn, on_done = jobs[0]
    on_done(fn())
    try:
        assert service.status == ApiStatus(STATE_RUNNING, port)
    finally:
        service.shutdown()


def test_apply_does_not_flash_starting_while_the_server_already_runs(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()                                     # läuft
    jobs = []
    service._run = deferred_run(jobs)                   # ab hier verzögert
    try:
        service.apply()

        assert service.status == ApiStatus(STATE_RUNNING, port)
        fn, _ = jobs[0]
        assert fn() == ApiStatus(STATE_RUNNING, port)   # „läuft schon" meldet RUNNING
    finally:
        service.shutdown()


@pytest.mark.parametrize("settings", [
    {"api_enabled": False, "api_port": 17653},
    {"api_enabled": True, "api_port": "abc"},
])
def test_apply_shows_no_starting_when_nothing_will_start(tmp_path, settings):
    jobs = []
    service = make_service(tmp_path, dict(settings), run=deferred_run(jobs))

    service.apply()

    assert service.status.state == STATE_OFF


def test_status_callback_reports_the_current_status_not_a_late_workers_result(tmp_path):
    port = free_port()
    jobs, statuses = [], []
    settings = {"api_enabled": True, "api_port": port}
    service = make_service(tmp_path, settings, run=deferred_run(jobs), statuses=statuses)
    service.apply()
    first_fn, first_done = jobs[0]
    first_result = first_fn()                           # RUNNING
    settings["api_enabled"] = False
    service.apply()
    second_fn, second_done = jobs[1]
    second_done(second_fn())                            # OFF

    first_done(first_result)                            # kommt zu spät an

    assert statuses == [ApiStatus(STATE_OFF), ApiStatus(STATE_OFF)]


def test_rotate_switches_the_token_of_the_running_server_without_a_restart(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()
    try:
        old, server = token_of(tmp_path), service._server

        result = service.rotate()

        new = token_of(tmp_path)
        assert result == RotateResult(True) and new != old
        assert service._server is server
        assert get_status_code(port, old) == 401
        assert get_status_code(port, new) == 200
    finally:
        service.shutdown()


def test_rotate_without_a_server_writes_the_token_and_starts_nothing(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": False, "api_port": port})

    result = service.rotate()

    assert result == RotateResult(True)
    assert (tmp_path / "api-token").exists() and port_is_closed(port)


def test_failed_rotation_keeps_the_old_token_valid(tmp_path, monkeypatch):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()
    try:
        old = token_of(tmp_path)

        def boom(base_path):
            raise OSError("nicht schreibbar")

        monkeypatch.setattr(api_service, "rotate_token", boom)

        result = service.rotate()

        assert result == RotateResult(False, REASON_ROTATE_FAILED)
        assert token_of(tmp_path) == old
        assert get_status_code(port, old) == 200
    finally:
        service.shutdown()


def test_rotate_after_shutdown_is_refused_and_changes_nothing(tmp_path):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    service.apply()
    old = token_of(tmp_path)
    service.shutdown()

    result = service.rotate()

    assert result == RotateResult(False, REASON_CLOSED)
    assert token_of(tmp_path) == old


def test_rotation_is_serialized_against_a_start_in_progress(tmp_path, monkeypatch):
    port = free_port()
    service = make_service(tmp_path, {"api_enabled": True, "api_port": port})
    entered, release = threading.Event(), threading.Event()
    real_loader = api_service.load_or_create_token

    def slow_loader(base_path):
        token = real_loader(base_path)
        entered.set()
        assert release.wait(5)
        return token

    monkeypatch.setattr(api_service, "load_or_create_token", slow_loader)
    starter = threading.Thread(target=service._reconcile)
    starter.start()
    assert entered.wait(5)
    rotated = []
    rotator = threading.Thread(target=lambda: rotated.append(service.rotate()))
    rotator.start()

    rotator.join(0.3)
    assert rotator.is_alive(), "rotate() hätte auf den laufenden Start warten müssen"
    release.set()
    starter.join(5)
    rotator.join(5)

    try:
        assert rotated == [RotateResult(True)]
        # Die Datei trägt das neue Token — und genau das akzeptiert der Server.
        assert get_status_code(port, token_of(tmp_path)) == 200
    finally:
        service.shutdown()


def test_read_token_returns_the_file_token_and_creates_nothing(tmp_path):
    service = make_service(tmp_path, {"api_enabled": False, "api_port": 17653})

    assert service.read_token() is None
    assert list(tmp_path.glob("api-token*")) == []

    (tmp_path / "api-token").write_text("a" * 43, encoding="ascii")
    assert service.read_token() == "a" * 43
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `python3 -m pytest tests/test_api_service.py -q -p no:cacheprovider`
Expected: FAIL beim Import (`cannot import name 'REASON_CLOSED'` o. ä.).

- [ ] **Step 3: Implementieren**

Alle Änderungen an `src/api_service.py` als eindeutige Ersetzungen (jede muss genau einmal treffen):

1. Import: `from src.api_auth import load_or_create_token, single_token_verifier` →
   ```python
   from src.api_auth import (
       load_or_create_token, rotate_token, single_token_verifier,
   )
   from src.api_auth import read_token as read_token_file
   ```
2. Konstanten: hinter `STATE_RUNNING = "running"` die Zeile `STATE_STARTING = "starting"`; hinter `REASON_START_FAILED = "start_failed"` die Zeilen
   ```python
   REASON_CLOSED = "closed"
   REASON_ROTATE_FAILED = "rotate_failed"
   ```
3. Hinter der Klasse `ApiStatus` (vor `def parse_port`) einfügen:
   ```python
   @dataclass(frozen=True)
   class RotateResult:
       ok: bool
       reason: str = ""
   ```
4. `apply()` ersetzen:
   ```python
       def apply(self) -> None:
           """Bringt den Server in den Zustand der Settings. Im UI-Thread
           aufrufen; die Arbeit läuft im Worker, `on_status` kommt zurück.

           Sofort sichtbar wird „startet": das Token-Laden blockiert unter
           Windows bis 15 s, bis dahin stünde sonst „aus" da."""
           if self._closed:
               return
           port = parse_port(self._settings.get("api_port"))
           if (self._settings.get("api_enabled") and port is not None
                   and self._running_port() != port):
               self._status = ApiStatus(STATE_STARTING, port)
           self._run(self._reconcile, self._publish)

       def _running_port(self) -> int | None:
           server = self._server
           if server is None:
               return None
           try:
               return server.port
           except RuntimeError:                 # gerade gestoppt
               return None
   ```
   (den bisherigen Körper von `apply()` samt Docstring dafür entfernen)
5. `_publish` ersetzen:
   ```python
       def _publish(self, _result: ApiStatus) -> None:
           # Der aktuelle Stand, nicht das Ergebnis dieses Workers: kommen zwei
           # Worker vertauscht zurück, würde die UI sonst einen veralteten
           # Status zeigen.
           if self._on_status is not None:
               self._on_status(self._status)
   ```
6. „Läuft schon"-Zweig in `_reconcile_locked`: die Zeilen
   ```python
           if self._server is not None and self._server.port == port:
               return self._status                  # läuft schon, nichts zu tun
   ```
   ersetzen durch
   ```python
           if self._server is not None and self._server.port == port:
               # Läuft schon. RUNNING setzen statt `_status` durchzureichen: `apply`
               # kann dazwischen „startet" geschrieben haben.
               self._status = ApiStatus(STATE_RUNNING, port)
               return self._status
   ```
7. Zwei Methoden vor `def reopen` einfügen:
   ```python
       def rotate(self) -> RotateResult:
           """Erneuert das Token und tauscht den Prüfer des laufenden Servers aus.

           **Blockiert** (Dateizugriff, unter Windows `icacls`): nur im Worker.
           Läuft unter demselben Lock wie der Start — nach jeder Verschränkung
           akzeptiert der Server genau das Token, das in der Datei steht.
           Scheitert das Schreiben, bleibt das alte Token gültig."""
           with self._lock:
               if self._closed:
                   return RotateResult(False, REASON_CLOSED)
               try:
                   token = rotate_token(self._base_path)
               except OSError:
                   _log.warning("Lokale API: Token konnte nicht erneuert werden",
                                exc_info=True)
                   return RotateResult(False, REASON_ROTATE_FAILED)
               if self._server is not None:
                   self._server.set_verifier(single_token_verifier(token))
               return RotateResult(True)

       def read_token(self) -> str | None:
           """Token zum Kopieren (Settings-Tab). Rein lesend: legt nichts an.
           Dateizugriff — über den Worker aufrufen."""
           return read_token_file(self._base_path)
   ```

- [ ] **Step 4: Tests laufen lassen**

Run: `python3 -m pytest tests/test_api_service.py tests/test_api_auth.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:cacheprovider`
Expected: alle PASS.

- [ ] **Step 5: Commit**

```bash
git add src/api_service.py tests/test_api_service.py
git commit -m "$(cat <<'EOF'
feat(api): Rotation, Zustand „startet" und Token lesen im Dienst (#92)

rotate() läuft unter demselben Lock wie der Start und tauscht den Prüfer
des laufenden Servers aus; apply() zeigt sofort „startet"; _publish meldet
den aktuellen Status statt des Ergebnisses eines zu spät fertigen Workers.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `tab_rules` — Prüfung, Umrechnung und Texte des API-Tabs

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_rules.py`
- Modify: `tests/test_tab_rules.py`

**Interfaces:**
- Consumes: `api_service.parse_port`, `DEFAULT_PORT`, `MIN_PORT`, `MAX_PORT`, `ApiStatus`, `STATE_*`, `REASON_*`; `single_instance._PORT_BASE`/`_PORT_SPAN` (nur im Test).
- Produces (Task 4 verlässt sich darauf):
  - `validate_api(raw: Mapping[str, Any]) -> tuple[str, str] | None` (Schlüssel `api_port`)
  - `api_updates(raw: Mapping[str, Any]) -> dict[str, Any]` → `{"api_enabled": bool, "api_port": int}`
  - `port_hint(raw_port: Any) -> str` (leer, wenn nichts zu sagen ist)
  - `status_view(status: ApiStatus) -> tuple[str, str]` → `(Text, Art)` mit Art `"ok"` | `"muted"` | `"error"`
  - `curl_example(raw_port: Any) -> str`

- [ ] **Step 1: Failing tests schreiben**

An `tests/test_tab_rules.py` anfügen:

```python
# --- API-Tab (#92, PR 3) ----------------------------------------------------------

from src import single_instance  # noqa: E402
from src.api_service import (  # noqa: E402
    DEFAULT_PORT, REASON_INVALID_PORT, REASON_PORT_IN_USE, REASON_START_FAILED,
    REASON_TOKEN_UNAVAILABLE, STATE_ERROR, STATE_OFF, STATE_RUNNING, STATE_STARTING,
    ApiStatus,
)


def api_raw(**overrides):
    raw = {"api_enabled": True, "api_port": "17653"}
    raw.update(overrides)
    return raw


@pytest.mark.parametrize("port", ["17653", " 8080 ", "1024", "65535"])
def test_validate_api_accepts_valid_ports(port):
    assert tr.validate_api(api_raw(api_port=port)) is None


@pytest.mark.parametrize("port", ["", "abc", "0", "80", "1023", "65536", "70000",
                                  "17653.5", "-5", "٨٠٨٠", "9" * 5000, "0x50", " "])
def test_validate_api_rejects_everything_else(port):
    result = tr.validate_api(api_raw(api_port=port))

    assert result is not None
    title, message = result
    assert title and "1024" in message and "65535" in message


def test_validate_api_checks_the_port_even_when_the_api_is_off():
    # Ein kaputter Port im Feld soll nicht erst beim späteren Einschalten auffallen.
    assert tr.validate_api(api_raw(api_enabled=False, api_port="abc")) is not None


def test_api_updates_converts_the_form_state():
    assert tr.api_updates(api_raw(api_port=" 8080 ")) == {
        "api_enabled": True, "api_port": 8080}
    assert tr.api_updates(api_raw(api_enabled=False)) == {
        "api_enabled": False, "api_port": 17653}


def test_api_updates_falls_back_to_the_default_port_like_the_other_tabs():
    assert tr.api_updates(api_raw(api_port="abc"))["api_port"] == DEFAULT_PORT


def test_api_tab_keys_do_not_collide_with_the_other_tabs():
    assert set(tr.api_updates(api_raw())) & LEGACY_KEYS == set()


@pytest.mark.parametrize("port,expected_fragment", [
    ("20000", "Mehrfachstart"), ("31999", "Mehrfachstart"), ("25000", "Mehrfachstart"),
    ("32768", "32768"), ("60000", "32768"), ("65535", "32768"),
])
def test_port_hint_warns_for_the_busy_ranges(port, expected_fragment):
    assert expected_fragment in tr.port_hint(port)


@pytest.mark.parametrize("port", ["17653", "1024", "19999", "32000", "32767", "abc", "", "0"])
def test_port_hint_is_empty_everywhere_else(port):
    assert tr.port_hint(port) == ""


def test_port_hint_range_matches_the_single_instance_range():
    # Der Hinweis nennt den Bereich des Mehrfachstart-Schutzes; ändert sich der,
    # muss der Hinweis mit.
    assert tr._SINGLE_INSTANCE_FROM == single_instance._PORT_BASE
    assert tr._SINGLE_INSTANCE_TO == single_instance._PORT_BASE + single_instance._PORT_SPAN - 1


def test_status_view_for_every_state():
    assert tr.status_view(ApiStatus(STATE_OFF)) == ("Aus.", "muted")
    assert tr.status_view(ApiStatus(STATE_STARTING, 17653)) == ("Startet …", "muted")
    assert tr.status_view(ApiStatus(STATE_RUNNING, 17653)) == (
        "Läuft auf 127.0.0.1:17653", "ok")


@pytest.mark.parametrize("reason", [REASON_INVALID_PORT, REASON_PORT_IN_USE,
                                    REASON_TOKEN_UNAVAILABLE, REASON_START_FAILED,
                                    "etwas-neues"])
def test_status_view_error_reasons_are_distinct_and_never_empty(reason):
    text, kind = tr.status_view(ApiStatus(STATE_ERROR, 17653, reason))
    assert kind == "error" and text.strip()


def test_status_view_port_in_use_names_the_port():
    text, _ = tr.status_view(ApiStatus(STATE_ERROR, 8080, REASON_PORT_IN_USE))
    assert "8080" in text


def test_status_view_reasons_have_different_texts():
    texts = {tr.status_view(ApiStatus(STATE_ERROR, 8080, r))[0]
             for r in (REASON_INVALID_PORT, REASON_PORT_IN_USE,
                       REASON_TOKEN_UNAVAILABLE, REASON_START_FAILED)}
    assert len(texts) == 4


def test_curl_example_uses_the_port_and_never_a_real_token():
    assert tr.curl_example("8080") == (
        'curl -H "Authorization: Bearer <Token>" http://127.0.0.1:8080/v1/status')
    assert "17653" in tr.curl_example("abc")          # Fallback auf den Standard
```

Hinweis: `tests/test_tab_rules.py` importiert `pytest` bisher nicht; die Importzeilen oben an die Datei setzen: `import pytest`.

- [ ] **Step 2: Fehlschlag prüfen**

Run: `python3 -m pytest tests/test_tab_rules.py -q -p no:cacheprovider`
Expected: FAIL (`AttributeError: module … has no attribute 'validate_api'`).

- [ ] **Step 3: Implementieren**

In `src/dialogs/settings_dialog/tab_rules.py` die Importe erweitern (hinter `from src.devices import sanitize_device_name`):

```python
from src.api_service import (
    DEFAULT_PORT, MAX_PORT, MIN_PORT, REASON_INVALID_PORT, REASON_PORT_IN_USE,
    REASON_TOKEN_UNAVAILABLE, STATE_ERROR, STATE_RUNNING, STATE_STARTING,
    ApiStatus, parse_port,
)
```

und am Dateiende anfügen:

```python
# ---- API (#92) --------------------------------------------------------------

# Bereich, aus dem `single_instance` den Port je Installationsordner ableitet
# (20000–31999); `tests/test_tab_rules.py` hält ihn gegen Drift fest.
_SINGLE_INSTANCE_FROM = 20000
_SINGLE_INSTANCE_TO = 31999
# Ab hier vergeben Betriebssysteme kurzlebig Ports an andere Programme (Linux
# 32768+, Windows 49152+).
_EPHEMERAL_FROM = 32768

_API_ERRORS = {
    REASON_INVALID_PORT: "Ungültiger Port — die API ist aus.",
    REASON_PORT_IN_USE: ("Port {port} ist belegt. Einen anderen Port wählen oder das "
                         "andere Programm beenden."),
    REASON_TOKEN_UNAVAILABLE: ("Das Token ist nicht les- oder schreibbar "
                               "(Zugriffsrechte des Datenordners?)."),
}


def validate_api(raw: Mapping[str, Any]) -> tuple[str, str] | None:
    """Der Port muss gültig sein — auch bei ausgeschalteter API, damit ein
    kaputter Wert nicht erst beim späteren Einschalten auffällt."""
    if parse_port(raw["api_port"]) is None:
        return ("Ungültiger Port",
                f"Der Port muss eine Zahl zwischen {MIN_PORT} und {MAX_PORT} sein.")
    return None


def api_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des API-Tabs. Tolerant wie die anderen Tabs: ein
    ungültiger Port fällt auf den Standard (`validate_api` fängt ihn vorher)."""
    return {
        "api_enabled": bool(raw["api_enabled"]),
        "api_port": parse_port(raw["api_port"]) or DEFAULT_PORT,
    }


def port_hint(raw_port: Any) -> str:
    """Hinweis zum eingegebenen Port, leer wenn es nichts zu sagen gibt."""
    port = parse_port(raw_port)
    if port is None:
        return ""
    if _SINGLE_INSTANCE_FROM <= port <= _SINGLE_INSTANCE_TO:
        return ("Dieser Bereich wird auch vom Mehrfachstart-Schutz der App genutzt "
                "(je Installationsordner ein Port). Bei einem Konflikt einen anderen "
                "Port wählen.")
    if port >= _EPHEMERAL_FROM:
        return (f"Ab {_EPHEMERAL_FROM} vergibt das Betriebssystem kurzlebig Ports an "
                "andere Programme; ist der Port beim Start belegt, bleibt die API aus.")
    return ""


def status_view(status: ApiStatus) -> tuple[str, str]:
    """(Text, Art) für die Statuszeile; Art ist `ok`, `muted` oder `error`."""
    if status.state == STATE_RUNNING:
        return f"Läuft auf 127.0.0.1:{status.port}", "ok"
    if status.state == STATE_STARTING:
        return "Startet …", "muted"
    if status.state == STATE_ERROR:
        text = _API_ERRORS.get(status.reason,
                               "Start fehlgeschlagen. Details im Protokoll.")
        return text.format(port=status.port), "error"
    return "Aus.", "muted"


def curl_example(raw_port: Any) -> str:
    """Beispielaufruf für die Hinweiszeile; mit Platzhalter statt echtem Token."""
    port = parse_port(raw_port) or DEFAULT_PORT
    return f'curl -H "Authorization: Bearer <Token>" http://127.0.0.1:{port}/v1/status'
```

- [ ] **Step 4: Tests laufen lassen**

Run: `python3 -m pytest tests/test_tab_rules.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:cacheprovider`
Expected: alle PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/settings_dialog/tab_rules.py tests/test_tab_rules.py
git commit -m "$(cat <<'EOF'
feat(api): Prüfung und Texte des API-Tabs, Tk-frei (#92)

validate_api, api_updates, port_hint, status_view und curl_example. Die
Hinweisgrenze des Mehrfachstart-Schutzes ist per Test an single_instance
gebunden.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Tab „API" und Dialog-Verdrahtung

**Files:**
- Create: `src/dialogs/settings_dialog/tab_api.py`
- Modify: `src/dialogs/settings_dialog/dialog.py`
- Modify: `src/ui.py` (`_open_settings`)
- Modify: `tests/test_api_wiring.py`

**Interfaces:**
- Consumes: `ApiService.status`, `.read_token()`, `.rotate() -> RotateResult`; `tab_rules.api_updates`/`curl_example`/`port_hint`/`status_view`/`validate_api`; `theme.Form`, `dark_entry`, `set_secondary_button_enabled`, `themed_askyesno(parent, title, message, lock_ms=0)`, `themed_showerror`, `themed_showinfo`; `BackgroundTaskRunner.run(fn, on_done)`.
- Produces: `ApiTab(frame, dialog, settings, api_service, runner)` mit der Tab-Schnittstelle (`title = "API"`, `fields`, `values`, `load`, `validate`, `save`); `open_settings_dialog(..., api_service=None)`.

Tk-Code läuft hier nicht automatisiert (entschiedene Scope-Grenze); abgesichert wird die Verdrahtung am Quelltext (AST), Muster `tests/test_api_wiring.py`.

- [ ] **Step 1: Failing tests schreiben**

An `tests/test_api_wiring.py` anfügen:

```python
# --- Settings-Tab (PR 3) -------------------------------------------------------

DIALOG = (pathlib.Path(__file__).resolve().parent.parent / "src" / "dialogs"
          / "settings_dialog" / "dialog.py")
DIALOG_TREE = ast.parse(DIALOG.read_text(encoding="utf-8"))


def _dialog_function():
    for node in ast.walk(DIALOG_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == "open_settings_dialog":
            return node
    raise AssertionError("open_settings_dialog fehlt")


def test_the_app_hands_its_api_service_to_the_settings_dialog():
    call = [n for n in ast.walk(_function("_open_settings"))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "open_settings_dialog"][0]
    keywords = {kw.arg: kw.value for kw in call.keywords}
    assert "api_service" in keywords
    value = keywords["api_service"]
    assert (isinstance(value, ast.Attribute) and value.attr == "_api"
            and isinstance(value.value, ast.Name) and value.value.id == "self")


def test_the_dialog_accepts_api_service_as_an_optional_keyword():
    args = _dialog_function().args
    names = [a.arg for a in args.kwonlyargs] + [a.arg for a in args.args]
    assert "api_service" in names
    defaults = dict(zip([a.arg for a in args.kwonlyargs], args.kw_defaults, strict=True))
    assert isinstance(defaults["api_service"], ast.Constant) and defaults["api_service"].value is None


def test_the_api_tab_sits_between_google_and_app_and_only_with_a_service():
    func = _dialog_function()
    order = []          # (Zeile, Schlüssel) aller `tabs[...] = …` und des Literals
    for node in ast.walk(func):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Subscript)
                and isinstance(node.targets[0].value, ast.Name)
                and node.targets[0].value.id == "tabs"
                and isinstance(node.targets[0].slice, ast.Constant)):
            order.append((node.lineno, node.targets[0].slice.value))
    assert [key for _, key in sorted(order)] == ["api", "app", "updates"]
    # Der Eintrag „api" steht unter einer Bedingung (kein Dienst, kein Tab).
    api_assign = [n for n in ast.walk(func) if isinstance(n, ast.If)
                  and any(isinstance(s, ast.Assign) and isinstance(s.targets[0], ast.Subscript)
                          and isinstance(s.targets[0].slice, ast.Constant)
                          and s.targets[0].slice.value == "api" for s in n.body)]
    assert api_assign


def test_the_api_tab_is_built_from_the_service_and_the_runner():
    calls = [n for n in ast.walk(_dialog_function())
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "ApiTab"]
    assert calls and len(calls[0].args) == 5
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `python3 -m pytest tests/test_api_wiring.py -q -p no:cacheprovider`
Expected: FAIL (u. a. `assert "api_service" in keywords`).

- [ ] **Step 3: Tab und Verdrahtung bauen**

`src/dialogs/settings_dialog/tab_api.py`:

```python
"""Tab „API" (#92): lokale HTTP-API ein-/ausschalten, Port, Status und Token.

Schalter und Port sind Formularfelder (Speichern je Tab, `SaveCoordinator`);
„Token kopieren" und „Neu erzeugen" sind Aktionen, die sofort wirken. Beide
blockieren (Dateizugriff, unter Windows `icacls`) und laufen deshalb über den
`BackgroundTaskRunner`. Der Status kommt per Poll aus `ApiService.status`: das
`on_status`-Callback kann nach dem Schließen des Dialogs zurückkommen, ein
`after`-Poll, der mit dem Tab stirbt, nicht.

Das Token wird nie angezeigt, nur in die Zwischenablage kopiert.
"""

import tkinter as tk

from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    api_updates, curl_example, port_hint, status_view, validate_api,
)
from src.theme import (
    BG, FONT, STATUS_OK, STATUS_WARN, TEXT_MUTED, Form, dark_entry,
    set_secondary_button_enabled, themed_askyesno, themed_showerror,
    themed_showinfo,
)

_POLL_MS = 500
_FLASH_MS = 2500
_MASK = "•" * 24
_NO_TOKEN = "Wird beim ersten Einschalten erzeugt."
_STATUS_COLORS = {"ok": STATUS_OK, "muted": TEXT_MUTED, "error": STATUS_WARN}
_ROTATE_ERRORS = {
    "closed": "Die App wird gerade beendet.",
    "rotate_failed": ("Das neue Token konnte nicht geschrieben werden "
                      "(Zugriffsrechte des Datenordners?). Das bisherige Token "
                      "gilt weiter."),
}


class ApiTab:
    """Baut den API-Tab; Tab-Schnittstelle für den `SaveCoordinator`."""

    def __init__(self, frame, dialog, settings, api_service, runner):
        self.frame = frame
        self.title = "API"
        self._dialog = dialog
        self._settings = settings
        self._service = api_service
        self._runner = runner
        self._alive = True
        self._token_known = False
        self._last_state = None

        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        enabled_var = tk.BooleanVar(value=bool(settings.get("api_enabled")))
        port_var = tk.StringVar(value=str(settings.get("api_port")))

        form.section("Lokale HTTP-API")
        form.hint("Andere Programme auf diesem Rechner (Skripte, Taskplaner, "
                  "Dashboards) können Zeiten lesen. Erreichbar nur von diesem "
                  "Rechner und nur mit Token.")
        form.check("Lokale API aktivieren", enabled_var)
        with form.depends_on(enabled_var):
            form.row("Port:", dark_entry(body, port_var, width=7))
            port_hint_label = form.hint(port_hint(port_var.get()))
        self._status_label = tk.Label(body, text="", font=FONT, bg=BG,
                                      fg=TEXT_MUTED, anchor="w", justify="left")
        form.row("Status:", self._status_label)
        with form.depends_on(enabled_var):
            self._token_label = tk.Label(body, text=_MASK, font=FONT, bg=BG,
                                         fg=TEXT_MUTED, anchor="w")
            form.row("Token:", self._token_label)
            self._copy_btn, self._rotate_btn = form.buttons(
                ("Token kopieren", self._copy_token),
                ("Neu erzeugen …", self._rotate))
            example_label = form.hint(curl_example(port_var.get()))
        form.hint("Die API läuft nur, solange die App läuft — Autostart gibt es "
                  "im Tab „App“. Das Token verlässt diese Maske nur über die "
                  "Zwischenablage.")

        def _on_port(*_args):
            port_hint_label.config(text=port_hint(port_var.get()))
            example_label.config(text=curl_example(port_var.get()))

        port_var.trace_add("write", _on_port)

        fields = FieldSet()
        fields.add("api_enabled", enabled_var)
        fields.add("api_port", port_var)
        self.fields = fields

        frame.bind("<Destroy>", self._on_destroy, add="+")
        self._poll()
        self._refresh_token()

    # --- Tab-Schnittstelle --------------------------------------------------

    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return validate_api(self.values())

    def save(self):
        self._settings.apply_updates(api_updates(self.values()))
        return SaveOutcome(saved=True)

    # --- Status und Token ---------------------------------------------------

    def _on_destroy(self, event):
        if event.widget is self.frame:
            self._alive = False

    def _poll(self):
        if not self._alive:
            return
        try:
            status = self._service.status
            text, kind = status_view(status)
            self._status_label.config(text=text, fg=_STATUS_COLORS[kind])
            if status.state != self._last_state:
                self._last_state = status.state
                self._refresh_token()       # das Token entsteht beim ersten Einschalten
            self.frame.after(_POLL_MS, self._poll)
        except tk.TclError:
            self._alive = False             # Fenster zwischenzeitlich zu

    def _refresh_token(self):
        self._runner.run(self._service.read_token, self._show_token)

    def _show_token(self, token):
        if not self._alive:
            return
        self._token_known = token is not None
        try:
            self._token_label.config(text=_MASK if self._token_known else _NO_TOKEN)
            set_secondary_button_enabled(self._copy_btn, self._token_known)
        except tk.TclError:
            self._alive = False

    def _flash(self, text):
        """Kurze Rückmeldung in der Token-Zeile, danach wieder die Maske."""
        self._token_label.config(text=text, fg=STATUS_OK)
        self.frame.after(_FLASH_MS, self._restore_token_label)

    def _restore_token_label(self):
        if not self._alive:
            return
        try:
            self._token_label.config(
                text=_MASK if self._token_known else _NO_TOKEN, fg=TEXT_MUTED)
        except tk.TclError:
            self._alive = False

    # --- Aktionen -------------------------------------------------------------

    def _copy_token(self):
        self._runner.run(self._service.read_token, self._copy_to_clipboard)

    def _copy_to_clipboard(self, token):
        if not self._alive:
            return
        try:
            if token is None:
                themed_showinfo(self._dialog, "Noch kein Token",
                                "Das Token entsteht beim ersten Einschalten der API.")
                return
            self._dialog.clipboard_clear()
            self._dialog.clipboard_append(token)
            self._flash("In die Zwischenablage kopiert.")
        except tk.TclError:
            self._alive = False

    def _rotate(self):
        if not themed_askyesno(
                self._dialog, "Token neu erzeugen",
                "Alle Programme, die das bisherige Token benutzen, werden "
                "ausgesperrt und brauchen das neue.\n\nFortfahren?",
                lock_ms=600):
            return
        set_secondary_button_enabled(self._rotate_btn, False)
        set_secondary_button_enabled(self._copy_btn, False)
        self._runner.run(self._service.rotate, self._rotated)

    def _rotated(self, result):
        if not self._alive:
            return
        try:
            set_secondary_button_enabled(self._rotate_btn, True)
            if result.ok:
                self._refresh_token()           # stellt „Kopieren" wieder her
                self._flash("Token erneuert — alte Clients sind ausgesperrt.")
                return
            set_secondary_button_enabled(self._copy_btn, self._token_known)
            themed_showerror(
                self._dialog, "Token konnte nicht erneuert werden",
                _ROTATE_ERRORS.get(result.reason, "Unbekannter Fehler."))
        except tk.TclError:
            self._alive = False
```

`src/dialogs/settings_dialog/dialog.py` — Ersetzungen (jede genau einmal):

1. Import: `from src.dialogs.settings_dialog.tab_app import AppTab` →
   ```python
   from src.dialogs.settings_dialog.tab_api import ApiTab
   from src.dialogs.settings_dialog.tab_app import AppTab
   ```
2. Signatur: `                         on_request_removal=None):` → `                         on_request_removal=None, api_service=None):`
3. Docstring: `aufgeteilt auf sechs\n    Tabs (Arbeitszeit / Erinnerungen / Versand / Google / App / Updates).` → `aufgeteilt auf sieben\n    Tabs (Arbeitszeit / Erinnerungen / Versand / Google / API / App / Updates).`; `` `sending`/`google`/`app`/`updates`), auf den `` → `` `sending`/`google`/`api`/`app`/`updates`), auf den ``; und hinter dem Absatz zu `on_request_removal` (`der Dialog schließt dafür ohne Speichern.`) einfügen:
   ```
       api_service: der `api_service.ApiService` der App (#92); ohne ihn gibt es
       keinen Tab „API".
   ```
4. Frames: die Zeilen
   ```python
       frames = {key: tk.Frame(notebook, bg=BG) for key in
                 ("work", "reminders", "sending", "google", "app", "updates")}
   ```
   ersetzen durch
   ```python
       frame_keys = ["work", "reminders", "sending", "google"]
       if api_service is not None:
           frame_keys.append("api")
       frame_keys += ["app", "updates"]
       frames = {key: tk.Frame(notebook, bg=BG) for key in frame_keys}
   ```
5. Tab bauen: direkt vor `    def _remove(with_data):` einfügen:
   ```python
       api = None
       if api_service is not None:
           api = ApiTab(frames["api"], dialog, settings, api_service, runner)
   ```
   — der Aufruf hat genau fünf Positionsargumente.
6. `tabs`: das Literal
   ```python
       tabs = {
           "work": work,
           "reminders": reminders,
           "sending": sending,
           "google": google,
           "app": app,
           "updates": updates_tab,
       }
   ```
   ersetzen durch
   ```python
       tabs = {
           "work": work,
           "reminders": reminders,
           "sending": sending,
           "google": google,
       }
       if api is not None:
           tabs["api"] = api
       tabs["app"] = app
       tabs["updates"] = updates_tab
   ```

`src/ui.py`, in `_open_settings`: `            on_vacation_display_change=self._refresh,` →
```python
            on_vacation_display_change=self._refresh,
            api_service=self._api,
```
(die Zeile muss im Aufruf von `open_settings_dialog` stehen und eindeutig sein; steht sie dort nicht allein, den Anker um die Nachbarzeile erweitern.)

- [ ] **Step 4: Tests laufen lassen**

Run: `python3 -m pytest tests/test_api_wiring.py tests/test_settings_dialog.py tests/test_dialog_reveal.py tests/test_ui_delete.py tests/test_pixel_scaling.py -q -p no:cacheprovider` und danach die ganze Suite `python3 -m pytest -q`.
Expected: alle PASS. `test_pixel_scaling` und `test_dialog_reveal` fangen Verstöße im neuen Tab (Pixel-Literale, Dialogpaare); `test_ui_delete` importiert `src.ui` und fängt Tippfehler in den Importen.

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/settings_dialog/tab_api.py src/dialogs/settings_dialog/dialog.py src/ui.py tests/test_api_wiring.py
git commit -m "$(cat <<'EOF'
feat(api): Settings-Tab „API" (#92)

Schalter, Port, Statuszeile, Token kopieren und neu erzeugen. Blockierende
Aufrufe über den BackgroundTaskRunner, Status per after-Poll aus
ApiService.status, das Token wird nie angezeigt. Der Tab hängt nur im Dialog,
wenn ein api_service übergeben wird; Verdrahtung per AST-Test gesichert.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Doku und Gesamtprüfung

**Files:**
- Modify: `README.md`
- Modify: `src/CLAUDE.md`

**Interfaces:** Consumes alles aus Task 1–4. Produces konsistente Doku; grüne Gesamtprüfung.

- [ ] **Step 1: README und `src/CLAUDE.md` anpassen**

Als Wegwerf-Skript im Scratchpad ausführen (jede Ersetzung muss genau einmal treffen; trifft ein Anker nicht, den Wortlaut in der Datei prüfen und den Anker anpassen, nie die Assertion entfernen):

```python
def rw(path):
    return open(path, encoding="utf-8", newline="").read()


def wr(path, text):
    open(path, "w", encoding="utf-8", newline="").write(text)


def sub(text, old, new, label):
    assert text.count(old) == 1, (label, text.count(old))
    return text.replace(old, new)


# --- README ---------------------------------------------------------------------
s = rw("README.md")
s = sub(s,
    "[Google-Kalender](#google-kalender-für-reservierungen-einrichten-optional) ·\n",
    "[Google-Kalender](#google-kalender-für-reservierungen-einrichten-optional) ·\n"
    "[Lokale API](#lokale-http-api-optional) ·\n", "toc")
s = sub(s, "(Arbeitszeit / Erinnerungen / Versand / Google / App / Updates)",
        "(Arbeitszeit / Erinnerungen / Versand / Google / API / App / Updates)", "tabs")
s = sub(s, "- **Autostart & Einzelinstanz**",
    "- **Lokale HTTP-API** *(ab --VERSION--)* — Optional (Standard: aus): ein Server nur "
    "auf `127.0.0.1`, über den Skripte, Taskplaner oder andere Programme auf diesem "
    "Rechner deine Zeiten lesen können — nur mit Token (Einstellungen → API), nie aus dem "
    "Browser; siehe [Lokale HTTP-API](#lokale-http-api-optional)\n"
    "- **Autostart & Einzelinstanz**", "feature")
s = sub(s,
    "| **Autostart** | App minimiert bei Systemanmeldung starten (Windows/macOS/Linux) |\n",
    "| **Autostart** | App minimiert bei Systemanmeldung starten (Windows/macOS/Linux) |\n"
    "| **Lokale API** *(ab --VERSION--)* | Tab „API“: lokale HTTP-API ein-/ausschalten, Port, "
    "Status, Token kopieren oder neu erzeugen (Standard: aus, gerätelokal) |\n", "row")
section = '''## Lokale HTTP-API (optional)

**Lokale HTTP-API** *(ab --VERSION--)* — Eine kleine Schnittstelle nur auf deinem Rechner (`127.0.0.1`), über die Skripte, Taskplaner oder andere Programme deine Zeiten lesen können. Standardmäßig **aus**.

1. Einstellungen → **API** → „Lokale API aktivieren“, speichern. Der Standard-Port ist 17653; die Statuszeile zeigt, ob die API läuft.
2. **Token kopieren** — jeder Zugriff braucht es als `Authorization: Bearer <Token>`. „Neu erzeugen …“ sperrt alle Programme aus, die das alte Token benutzen.
3. Abfragen, zum Beispiel:

~~~
curl -H "Authorization: Bearer <Token>" http://127.0.0.1:17653/v1/status
curl -H "Authorization: Bearer <Token>" "http://127.0.0.1:17653/v1/entries?from=2026-10-01&to=2026-10-31"
curl -H "Authorization: Bearer <Token>" http://127.0.0.1:17653/v1/entries/2026-10-06
~~~

| Pfad | Antwort |
|------|---------|
| `GET /v1/status` | App-Version, Gerätename, API-Version, Zeit |
| `GET /v1/entries?from=…&to=…` | Ist-Zeiten im Zeitraum (ohne Angabe: alle), je Tag die Slots `{start, end, pause, kategorie}` |
| `GET /v1/entries/{YYYY-MM-DD}` | ein Tag (404, wenn es keinen Eintrag gibt) |

Die API läuft nur, solange die App läuft (Autostart hilft), nimmt nur Anfragen von diesem Rechner mit Token an und keine Browser-Anfragen. Grenzen: [`docs/known-limitations.md`](docs/known-limitations.md#lokale-api-92-bekannte-grenzen).

'''
s = sub(s, "## Einstellungen\n\nÜber das Zahnrad-Symbol", section + "## Einstellungen\n\nÜber das Zahnrad-Symbol",
        "section")
wr("README.md", s)

# --- src/CLAUDE.md ------------------------------------------------------------------
c = rw("src/CLAUDE.md")
c = sub(c, "`tab_sending`/`tab_google`/`tab_app`/`tab_updates`.py, alle gebaut mit",
        "`tab_sending`/`tab_google`/`tab_api`/`tab_app`/`tab_updates`.py, alle gebaut mit",
        "claude tab list")
c = sub(c, "`initial_tab`-Schlüssel: `work`, `reminders`, `sending`, `google`, `app`, `updates` — die",
        "`initial_tab`-Schlüssel: `work`, `reminders`, `sending`, `google`, `api` (nur mit\n"
        "`api_service`), `app`, `updates` — die", "claude tab keys")
c = sub(c, "Reitertexte kommen aus `tab.title`. SMTP-Konten und Webhooks sind Abschnitte im\n"
        "Versand-Tab (`tab_smtp.SmtpTab`/`tab_webhooks.WebhooksTab` über",
        "Reitertexte kommen aus `tab.title`. **`tab_api.ApiTab` (#92)** ist der Tab „API“\n"
        "(Schalter, Port, Statuszeile, Token kopieren/neu erzeugen): nur `api_enabled`/`api_port`\n"
        "sind Formularfelder, Kopieren und Erneuern sind Aktionen, die sofort wirken und — weil\n"
        "sie Dateizugriff machen (unter Windows `icacls`) — über den `BackgroundTaskRunner`\n"
        "laufen. Der Status kommt per `after`-Poll aus `ApiService.status`, nicht aus\n"
        "`on_status` (das Callback kann nach dem Schließen des Dialogs zurückkommen). Das Token\n"
        "wird nie angezeigt. Prüfung und Texte (`validate_api`, `api_updates`, `port_hint`,\n"
        "`status_view`, `curl_example`) liegen Tk-frei in `tab_rules.py`; den Tab hängt\n"
        "`open_settings_dialog` nur ein, wenn ihm ein `api_service` übergeben wird. SMTP-Konten\n"
        "und Webhooks sind Abschnitte im\n"
        "Versand-Tab (`tab_smtp.SmtpTab`/`tab_webhooks.WebhooksTab` über", "claude tab api")
c = sub(c, "`Policy` und\n  `Principal.scopes` sind die Nahtstellen für die LAN-Freigabe (#221).",
        "`Policy` und\n  `Principal.scopes` sind die Nahtstellen für die LAN-Freigabe (#221). "
        "`read_token` liest das Token\n  rein lesend (kein Anlegen, kein Härten) — für „Token kopieren“.",
        "claude api_auth read_token")
c = sub(c, "Datei neu anlegen. `reopen()` nimmt das zurück (fehlgeschlagener Skalierungs-Neustart).",
        "Datei neu anlegen. `reopen()` nimmt das zurück (fehlgeschlagener Skalierungs-Neustart).\n"
        "  `apply()` setzt sofort `starting` (Token-Laden blockiert unter Windows bis 15 s), und\n"
        "  `_publish` meldet immer den **aktuellen** `.status`, nie das Ergebnis eines zu spät\n"
        "  fertigen Workers. `rotate()` (Worker!) erneuert das Token und tauscht den Prüfer des\n"
        "  laufenden Servers aus — unter demselben `_lock` wie der Start, sodass der Server nach\n"
        "  jeder Verschränkung genau das Token akzeptiert, das in der Datei steht; scheitert das\n"
        "  Schreiben, bleibt das alte gültig. `read_token()` liest rein lesend.",
        "claude service")
wr("src/CLAUDE.md", c)
print("Doku angepasst")
```

- [ ] **Step 2: Gesamtprüfung**

Run:
```bash
python3 -m pytest -q
ruff check .
V=/tmp/claude-1000/-home-sven-projects-Zeiterfassung/560a12d5-c553-4c73-8987-d78214ab3424/scratchpad/covenv
$V/bin/python -m pytest tests/test_api_auth.py tests/test_api_service.py tests/test_tab_rules.py \
  --cov=src.api_auth --cov=src.api_service --cov=src.dialogs.settings_dialog.tab_rules --cov-branch \
  --cov-report=term-missing -q -p no:cacheprovider
rm -f .coverage
```
Expected: alle Tests grün, `ruff` sauber; `api_auth` und `api_service` bleiben ≥ 95 %, die neuen `tab_rules`-Funktionen sind vollständig abgedeckt (der Rest von `tab_rules` ist vorbestehend). Falls das venv fehlt: `python3 -m venv $V && $V/bin/pip install -q pytest==9.0.3 pytest-cov`. Hinweis: `tab_rules` importiert jetzt `src.api_service` — `$V/bin/python` braucht dafür nichts Zusätzliches (stdlib).

Zusätzlich die README-Prüfungen: `python3 -m pytest tests/test_readme_version.py tests/test_claude_md_claims.py -q`.

- [ ] **Step 3: Commit**

```bash
git add README.md src/CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(api): Settings-Tab, Rotation und Bedienung dokumentiert (#92)

README: Abschnitt „Lokale HTTP-API“ mit Beispielen, Feature-Zeile, Tab-Liste
und Einstellungs-Tabelle (alle mit *(ab --VERSION--)*). src/CLAUDE.md: Tab,
Rotation unter dem Start-Lock, aktueller Status statt Worker-Ergebnis.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: PR vorbereiten (nicht ohne Freigabe pushen)**

PR 3 gegen `feat/api-server-read`, Titel `feat(api): Settings-Tab „API“ und Token-Rotation (#92)`, Beschreibung mit `Refs #92`, Verweis auf #233 (erledigt: Rotationspfad unter `_lock`, Zustand „startet", aktueller Status statt Worker-Ergebnis, Statusgrund im Tab, Port-Hinweise). Kein `release:*`-Label. Danach in den Stack hängen: `echo '{"pull_requests":[<PR3>]}' | gh api -X POST repos/Xveyn/Zeiterfassung/stacks/236/add --input -`. Vor dem Release einen Pre-Release über alle drei Plattformen bauen (UI + Windows-Port-Verhalten). Push und PR erst nach Rückfrage.

---

## Self-Review

**Spec-Abdeckung:** Schalter „Lokale API aktivieren" (Default aus), Port, Token maskiert mit Kopieren-Knopf, „Token neu erzeugen" mit Bestätigung (Rotation sperrt Clients aus): Task 4 (UI), Task 2 (Rotation), Task 3 (Prüfung/Texte). Ausstehende Punkte aus #233: Rotationspfad unter `_lock` und Start gegen Rotation serialisiert (Task 2), Zustand „startet" und aktueller Status statt Worker-Ergebnis (Task 2), Statusgrund im Tab (Task 3/4), Port-Hinweis für 20000–31999 und Ephemeral (Task 3). **Bewusst nicht in PR 3:** schreibende Routen (PR 4), Reservierungen/Auswertungen (PR 5), `shutdown` vor `push_on_quit` (PR 4), die übrigen zurückgestellten Minors aus #233.

**Platzhalter:** keine.

**Typkonsistenz:** `read_token(base_path)` (Task 1) → `ApiService.read_token()` ruft `read_token_file(self._base_path)` (Task 2) → vom Tab über den Runner aufgerufen (Task 4). `RotateResult(ok, reason)` und die Konstanten `REASON_CLOSED`/`REASON_ROTATE_FAILED` (Task 2) stimmen mit den Schlüsseln in `_ROTATE_ERRORS` (`"closed"`, `"rotate_failed"`, Task 4) überein. `status_view(ApiStatus) -> (Text, Art)` (Task 3) wird in `_STATUS_COLORS` (Art `ok`/`muted`/`error`, Task 4) konsumiert. `open_settings_dialog(api_service=…)` (Task 4) und der AST-Test prüfen dieselben Namen wie `App._open_settings`.
