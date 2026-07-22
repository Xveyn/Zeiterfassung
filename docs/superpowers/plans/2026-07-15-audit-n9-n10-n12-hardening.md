# Audit-Härtung N9/N10/N12 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drei unabhängige NIEDRIG-Audit-Findings aus Issue #131 in einem Sammel-PR beheben — Shared-Secret-Auth für den Single-Instance-Handshake (N9), Access-Token per POST-Body statt URL-Query (N10), shell-korrektes Quoting der Linux-Autostart-`Exec=`-Zeile (N12).

**Architecture:** Je Finding ein eigener, in sich testbarer Commit auf dem bestehenden Branch `fix/audit-n9-n10-n12-hardening`. Alle Änderungen sind lokalisiert (ein Modul + sein Test je Finding), stdlib-only, headless über `pytest`/`ruff` verifizierbar. N9 folgt bewusst dem atomaren-Schreib-Muster aus `oauth_utils.write_token`.

**Tech Stack:** Python 3.10 (stdlib: `hmac`, `os`, `socket`, `stat`, `tempfile`, `time`, `shlex`, `urllib`), pytest, ruff.

## Global Constraints

- **Python-Floor 3.10** — alle genutzten stdlib-APIs (`hmac.compare_digest`, `os.urandom`, `shlex.quote`, `urllib.request.Request(method=...)`) sind ≥3.3 verfügbar; keine neue Dependency.
- **`single_instance.py` bleibt stdlib-only und Tk-frei** — keine Google-/Third-Party-Imports.
- **Keine neue Runtime-Dependency** — nichts in `requirements.txt`.
- **Commit-Typ englisch** (`fix:`), Body/Kommentare Deutsch erlaubt; Commit-Footer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Kein `git push` / kein `gh pr create` ohne wörtlichen Trigger** des Nutzers (CLAUDE.md: schreibende Remote-Ops nur auf Trigger). Der Plan endet mit lokal committeten, grün verifizierten Änderungen.
- **Zeilenenden:** Working Tree ist CRLF (`core.autocrlf=true`); reine EOL-Diffs sind kein Lint-Fehler, nicht per Massen-Reformat „beheben".
- **Verhaltensgleichheit im Normalfall:** kein fremder Prozess / keine Sonderzeichen → Ausgabe identisch zu vorher (bestehende Tests bleiben unverändert grün).

**Referenz-Spec:** `docs/superpowers/specs/2026-07-15-audit-n9-n10-n12-hardening-design.md`

---

### Task 1: N9 — Shared-Secret-Auth für den Single-Instance-Handshake

**Files:**
- Modify: `src/single_instance.py`
- Test: `tests/test_single_instance.py`

**Interfaces:**
- Consumes: bestehende öffentliche API `acquire(base_path, show_requested)`, `_derive_port(base_path)`, `_Guard.serve(show_fn)`, `_Guard.release()` (Signaturen unverändert nach außen).
- Produces (neu, modul-intern): `_load_or_create_secret(base_path) -> bytes | None`, `_write_secret_atomic(path, secret) -> None`, `_recv_exactly(conn, n) -> bytes`, `_Guard.__init__(self, port, secret)`, öffentliches Attribut `_Guard.secret: bytes | None` (analog zu den bestehenden `port`/`bound` ohne Unterstrich). Konstanten `_MAGIC_LEN = 9`, `_SECRET_LEN = 32`, `_SECRET_FILENAME = "instance-secret"`.

- [ ] **Step 1: Failing-Test schreiben — Handshake ohne Secret wird abgewiesen**

In `tests/test_single_instance.py` ans Dateiende anfügen:

```python
def test_handshake_without_secret_is_rejected(tmp_path):
    """N9: Ein Client, der das instance-secret NICHT kennt (nur das Magic
    schickt), darf KEIN ZEIT-OK bekommen und den SHOW-Callback nicht auslösen."""
    base = str(tmp_path)
    g1 = acquire(base, show_requested=True)
    fired = threading.Event()
    g1.serve(lambda: fired.set())
    try:
        port = _derive_port(base)
        with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
            sock.sendall(b"ZEIT-SHOW")          # Magic ohne Secret
            sock.settimeout(5.0)
            try:
                reply = sock.recv(16)
            except socket.timeout:
                reply = b""
        assert reply != b"ZEIT-OK"
        assert fired.wait(timeout=1.0) is False
    finally:
        g1.release()
```

- [ ] **Step 2: Test laufen lassen, roten Fehler bestätigen**

Run: `pytest tests/test_single_instance.py::test_handshake_without_secret_is_rejected -v`
Expected: FAIL — heute antwortet der Primary auf reines `ZEIT-SHOW` mit `ZEIT-OK` und feuert den Callback (`reply == b"ZEIT-OK"`, `fired` gesetzt).

- [ ] **Step 3: Imports und Konstanten in `src/single_instance.py` ergänzen**

Die bestehende Import-Zeile (`import logging` … `import zlib`) um `hmac`, `stat`, `tempfile`, `time` erweitern. Der Kopf lautet danach:

```python
# src/single_instance.py
"""Single-Instance-Guard (Tk-frei). Erstinstanz bindet einen pro-Nutzer
abgeleiteten Localhost-Port; Folgeinstanzen melden sich per Socket und beenden
sich. Blockiert den Start nie — jeder Fehlerpfad endet im (ggf. ungeschützten)
Weiterlauf."""
import hmac
import logging
import os
import socket
import stat
import sys
import tempfile
import threading
import time
import zlib

_MAGIC_SHOW = b"ZEIT-SHOW"
_MAGIC_PING = b"ZEIT-PING"
_MAGIC_OK = b"ZEIT-OK"
_MAGIC_LEN = len(_MAGIC_SHOW)   # 9; SHOW und PING sind gleich lang
_SECRET_LEN = 32
_SECRET_FILENAME = "instance-secret"
_ACK_TIMEOUT = 2.0          # großzügig gegen Boot-Last
_PORT_BASE = 20000
_PORT_SPAN = 12000          # Range 20000–31999, unter allen Ephemeral-Ranges

_log = logging.getLogger(__name__)
```

- [ ] **Step 4: Secret-Laden/-Schreiben + `_recv_exactly` als Modul-Helfer einfügen**

Direkt nach `_derive_port(...)` (vor `class _Guard`) einfügen:

```python
def _write_secret_atomic(path, secret):
    """Schreibt das Instanz-Secret atomar (Temp + os.replace) mit 0600 und
    PermissionError-Retry — Muster aus oauth_utils.write_token (Issue #135)."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=".instance-secret-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(secret)
        try:
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600; Win: No-op
        except OSError:
            pass
        attempts = 5
        for attempt in range(attempts):
            try:
                os.replace(tmp_path, path)
                break
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.2)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _load_or_create_secret(base_path):
    """Lädt das 32-Byte-Instanz-Secret aus <base_path>/instance-secret oder
    erzeugt es beim ersten Start. Liefert 32 Bytes — oder None, wenn Lesen ODER
    Schreiben an einem OSError scheitert. None heißt: Handshake läuft
    unauthentifiziert weiter (der Start darf NIE an dieser Datei scheitern,
    Modul-Invariante). Eine vorhandene, aber unlesbare Datei wird NICHT
    überschrieben (könnte das Secret einer laufenden Instanz sein)."""
    path = os.path.join(base_path, _SECRET_FILENAME)
    try:
        with open(path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        data = None
    except OSError:
        _log.warning("Instanz-Secret nicht lesbar — Handshake unauthentifiziert",
                     exc_info=True)
        return None
    if data is not None and len(data) == _SECRET_LEN:
        return data
    # fehlt oder falsche Größe → neu erzeugen
    secret = os.urandom(_SECRET_LEN)
    try:
        _write_secret_atomic(path, secret)
        return secret
    except OSError:
        _log.warning("Instanz-Secret nicht schreibbar — Handshake unauthentifiziert",
                     exc_info=True)
        return None


def _recv_exactly(conn, n):
    """Liest genau n Bytes. Bei Timeout, geschlossener Verbindung oder
    Short-Read → b'' (Aufrufer verwirft die Verbindung). TCP ist ein Stream:
    ein einzelnes recv darf legal weniger als n Bytes liefern."""
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = conn.recv(n - len(buf))
        except OSError:
            return b""
        if not chunk:
            return b""
        buf.extend(chunk)
    return bytes(buf)
```

- [ ] **Step 5: `_Guard.__init__` um `secret` erweitern**

```python
class _Guard:
    def __init__(self, port, secret):
        self.port = port
        self.secret = secret        # bytes(32) oder None (unauth. Fallback)
        self.bound = False
        self._sock = None
        self._lock = threading.Lock()
        self._show_fn = None
        self._pending_show = False
        self._stop = False
```

- [ ] **Step 6: `_accept_loop` auf feste Länge + HMAC-Vergleich umstellen**

Die bestehende `_accept_loop`-Methode ersetzen durch die folgenden zwei Methoden (Accept-Schleife bleibt, Verbindungs-Handling wird ausgelagert):

```python
    def _accept_loop(self):
        while not self._stop:
            sock = self._sock
            if sock is None:            # release() lief parallel → sauber raus
                break
            try:
                conn, _addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._handle_conn(conn)

    def _handle_conn(self, conn):
        conn.settimeout(_ACK_TIMEOUT)
        with conn:
            try:
                if self.secret is None:
                    # Fallback (Secret nicht verfügbar): altes,
                    # unauthentifiziertes Protokoll — nur Magic prüfen.
                    magic = conn.recv(64)[:_MAGIC_LEN]
                else:
                    data = _recv_exactly(conn, _MAGIC_LEN + _SECRET_LEN)
                    if len(data) != _MAGIC_LEN + _SECRET_LEN:
                        return
                    magic, secret = data[:_MAGIC_LEN], data[_MAGIC_LEN:]
                    if not hmac.compare_digest(secret, self.secret):
                        return
                if magic == _MAGIC_SHOW:
                    conn.sendall(_MAGIC_OK)
                    self._fire_show()
                elif magic == _MAGIC_PING:
                    conn.sendall(_MAGIC_OK)
            except OSError:
                pass
```

- [ ] **Step 7: `_notify_primary` und `acquire` das Secret durchreichen**

Beide Funktionen am Dateiende ersetzen:

```python
def _notify_primary(port, show_requested, secret):
    """Meldet sich bei der laufenden Instanz. True nur, wenn sie sich per
    ZEIT-OK als unsere App bestätigt. Das Secret authentifiziert uns gegenüber
    dem Primary; None → altes Protokoll (nur Magic)."""
    magic = _MAGIC_SHOW if show_requested else _MAGIC_PING
    payload = magic if secret is None else magic + secret
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=_ACK_TIMEOUT) as sock:
            sock.sendall(payload)
            sock.settimeout(_ACK_TIMEOUT)
            return sock.recv(len(_MAGIC_OK)) == _MAGIC_OK
    except OSError:
        return False


def acquire(base_path, show_requested):
    """Erstinstanz → gebundener _Guard. Läuft schon eine (bestätigt per ZEIT-OK)
    → None (Aufrufer beendet sich). Port von Fremd-Software belegt → degradierter
    (ungebundener) _Guard, damit der Start nie blockiert."""
    port = _derive_port(base_path)
    secret = _load_or_create_secret(base_path)
    guard = _Guard(port, secret)
    if guard._try_bind():
        return guard
    if _notify_primary(port, show_requested, secret):
        return None
    _log.warning("Single-Instance-Port %d belegt, kein ZEIT-OK — Start ohne Guard", port)
    return guard
```

- [ ] **Step 8: Reject-Test laufen lassen, grün bestätigen**

Run: `pytest tests/test_single_instance.py::test_handshake_without_secret_is_rejected -v`
Expected: PASS — der Primary erwartet jetzt 41 Byte (Magic+Secret); das reine `ZEIT-SHOW` läuft in den Short-Read/Mismatch-Pfad, keine Antwort, kein Callback.

- [ ] **Step 9: Crash-Sicherheits-Test schreiben (Fallback statt Startup-Crash)**

Ans Ende von `tests/test_single_instance.py` anfügen:

```python
def test_secret_write_failure_yields_bound_unauth_guard(tmp_path, monkeypatch):
    """N9-Crash-Sicherheit: scheitert das Schreiben des Secrets hart, darf
    acquire() NICHT werfen — es liefert einen gebundenen Guard mit secret=None
    (unauthentifizierter Fallback), die App startet also weiter."""
    import src.single_instance as si

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(si, "_write_secret_atomic", _boom)
    base = str(tmp_path)
    g = acquire(base, show_requested=True)
    try:
        assert g is not None and g.bound is True
        assert g.secret is None
    finally:
        g.release()
```

- [ ] **Step 10: Crash-Test + volle Modul-Suite laufen lassen**

Run: `pytest tests/test_single_instance.py -v`
Expected: PASS — alle bestehenden Tests (`test_first_acquire_is_primary_second_exits`, `test_show_fires_callback_ping_does_not`, `test_pending_show_before_serve_fires_on_serve`, `test_silent_connection_does_not_wedge_listener`, `test_foreign_occupant_yields_degraded_primary`) plus die zwei neuen sind grün.

- [ ] **Step 11: Lint auf die geänderte Datei**

Run: `ruff check src/single_instance.py tests/test_single_instance.py`
Expected: `All checks passed!`

- [ ] **Step 12: Commit**

```bash
git add src/single_instance.py tests/test_single_instance.py
git commit -m "$(cat <<'EOF'
fix(single-instance): Shared-Secret-Auth für den SHOW/PING-Handshake (N9)

Der Single-Instance-Handshake band bisher nur einen deterministischen
127.0.0.1-Port und bediente jeden lokalen Prozess ohne Auth. Neu: ein
32-Byte-Secret in <base_path>/instance-secret (atomar geschrieben, 0600,
Muster wie oauth_utils.write_token) wird an den Handshake angehängt und
zeitkonstant (hmac.compare_digest) geprüft; ohne korrektes Secret kein
ZEIT-OK. Schließt den Cross-User-Nuisance-Vektor (anderer lokaler Nutzer
erreicht den Loopback-Port, kann aber die 0600-Datei nicht lesen);
Same-User-Prozesse sind bewusst nicht im Scope (Windows-ACL wäre M8).

Wire-Format jetzt feste 41 Byte (9 Magic + 32 Secret) → _accept_loop liest
exakt (Short-Read-sicher). Scheitert Lesen/Schreiben des Secrets, fällt
acquire() auf secret=None (altes, unauthentifiziertes Protokoll) zurück
statt zu crashen — die Modul-Invariante "blockiert den Start nie" bleibt.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: N10 — Access-Token per POST-Body statt URL-Query

**Files:**
- Modify: `src/mail.py` (Funktion `fetch_user_email`, tokeninfo-Block ~Z. 93–111)
- Test: `tests/test_mail.py`

**Interfaces:**
- Consumes: `fetch_user_email(token_path) -> str` (Signatur unverändert).
- Produces: keine neuen öffentlichen Symbole — reine Transport-Änderung (GET-Query → POST-Body).

- [ ] **Step 1: Failing-Test schreiben — Token geht in den POST-Body, nicht in die URL**

Ans Ende von `tests/test_mail.py` anfügen:

```python
def test_fetch_user_email_sends_token_in_post_body_not_url(tmp_path):
    """N10: Der Access-Token darf nicht als URL-Query-Parameter gehen
    (Leak-Risiko über URL-Logs), sondern im POST-Body."""
    from src.mail import fetch_user_email

    path = str(tmp_path / "token.json")
    open(path, "w").close()

    fake_creds = MagicMock()
    fake_creds.valid = True
    fake_creds.expired = False
    fake_creds.token = "access-token-xyz"

    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"email": "me@example.com"}'

    def _fake_urlopen(req, timeout=None):
        captured["req"] = req
        return _Resp()

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file",
               return_value=fake_creds), \
         patch("urllib.request.urlopen", _fake_urlopen):
        result = fetch_user_email(path)

    assert result == "me@example.com"
    req = captured["req"]
    assert req.get_method() == "POST"
    assert "access-token-xyz" not in req.full_url     # nicht in der URL
    assert b"access-token-xyz" in req.data            # sondern im Body
```

- [ ] **Step 2: Test laufen lassen, roten Fehler bestätigen**

Run: `pytest tests/test_mail.py::test_fetch_user_email_sends_token_in_post_body_not_url -v`
Expected: FAIL — heute ruft `fetch_user_email` `urlopen(url_string)` (kein `Request`-Objekt); `captured["req"]` ist ein `str`, `req.get_method()` wirft `AttributeError`.

- [ ] **Step 3: tokeninfo-Block in `src/mail.py` auf POST umstellen**

Den Block ab dem Kommentar `# Tokeninfo — …` bis zum `return ""` ersetzen durch:

```python
    # Tokeninfo — liest die E-Mail direkt aus dem Access-Token, sofern
    # userinfo.email-Scope autorisiert ist. Token geht als POST-Body (nicht als
    # URL-Query) → kein Token-Leak über URL-/Proxy-Logs (Audit N10). urllib
    # setzt bei gesetztem data automatisch Content-Type:
    # application/x-www-form-urlencoded.
    try:
        import json
        import urllib.parse
        import urllib.request

        body = urllib.parse.urlencode({"access_token": creds.token}).encode("ascii")
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/tokeninfo", data=body, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        log.info("fetch_user_email: tokeninfo response keys = %r", list(data.keys()))
        return (data.get("email") or "")
    except Exception:
        log.exception("fetch_user_email: tokeninfo lookup failed")
        return ""
```

- [ ] **Step 4: Neuen Test + Regressions-Test laufen lassen, grün bestätigen**

Run: `pytest tests/test_mail.py::test_fetch_user_email_sends_token_in_post_body_not_url tests/test_mail.py::test_fetch_user_email_uses_tokeninfo_not_gmail_getprofile -v`
Expected: PASS — der bestehende `…uses_tokeninfo_not_gmail_getprofile` bleibt grün (sein `urlopen`-Mock ignoriert die Args), der neue prüft POST + Body.

- [ ] **Step 5: Lint auf die geänderten Dateien**

Run: `ruff check src/mail.py tests/test_mail.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/mail.py tests/test_mail.py
git commit -m "$(cat <<'EOF'
fix(mail): tokeninfo-Access-Token per POST-Body statt URL-Query (N10)

fetch_user_email hängte den OAuth-Access-Token als Query-Parameter an die
tokeninfo-URL — Leak-Risiko über URL-/Proxy-Logs. Jetzt als POST-Body
(application/x-www-form-urlencoded, Content-Type setzt urllib automatisch).
Der tokeninfo-Endpoint unterstützt POST (gegen Google-Doku verifiziert).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: N12 — shell-korrektes Quoting der Linux-Autostart-`Exec=`-Zeile

**Files:**
- Modify: `src/autostart.py` (Import + Funktion `_enable_linux`)
- Test: `tests/test_autostart.py` (Klasse `TestLinuxAutostart`)

**Interfaces:**
- Consumes: `enable_autostart(target, arguments)` → `_enable_linux(target, arguments)` (Signaturen unverändert).
- Produces (neu, modul-intern): `_exec_line(target, arguments) -> str`.

- [ ] **Step 1: Failing-Test schreiben — Pfad mit Leerzeichen wird gequotet**

In `tests/test_autostart.py`, innerhalb der Klasse `TestLinuxAutostart` (nach `test_enable_without_arguments_has_no_trailing_space`), einfügen:

```python
    def test_enable_quotes_path_with_spaces(self, fake_home):
        enable_autostart("/opt/My Apps/Zeiterfassung.AppImage", "--minimized")
        content = open(_linux_desktop_path(), encoding="utf-8").read()
        # Pfad mit Leerzeichen MUSS gequotet sein, sonst zerbricht Exec nach
        # der Desktop-Entry-/GLib-Tokenisierung. shlex.quote nutzt Single-Quotes.
        assert "Exec='/opt/My Apps/Zeiterfassung.AppImage' --minimized" in content
```

- [ ] **Step 2: Test laufen lassen, roten Fehler bestätigen**

Run: `pytest "tests/test_autostart.py::TestLinuxAutostart::test_enable_quotes_path_with_spaces" -v`
Expected: FAIL — heute wird `Exec=/opt/My Apps/Zeiterfassung.AppImage --minimized` (ungequotet) geschrieben.

- [ ] **Step 3: `import shlex` und `_exec_line`-Helfer in `src/autostart.py` ergänzen**

Die Import-Zeilen am Dateianfang um `import shlex` erweitern (alphabetisch nach `import plistlib`, vor `import subprocess`):

```python
# src/autostart.py
import os
import platform
import plistlib
import shlex
import subprocess
import sys
```

Direkt vor `def _enable_linux(...)` einfügen:

```python
def _exec_line(target, arguments):
    """Baut die Exec=-Zeile mit shell-korrektem Quoting (Audit N12): ein Pfad
    mit Leerzeichen o.ä. zerbricht die .desktop-Datei sonst. shlex.quote deckt
    sich mit GLibs Exec-Parsing (g_shell_parse_argv). `arguments` ist ein
    Whitespace-getrennter String einfacher Flags (heute "" oder "--minimized").
    Werte ohne Sonderzeichen bleiben unverändert (shlex.quote quotet nur bei
    Bedarf)."""
    parts = [shlex.quote(target)]
    if arguments:
        parts.extend(shlex.quote(a) for a in arguments.split())
    return " ".join(parts)
```

- [ ] **Step 4: `_enable_linux` die `exec_line` über den Helfer bauen lassen**

In `_enable_linux` die Zeile
`exec_line = target if not arguments else f"{target} {arguments}"`
ersetzen durch:
`exec_line = _exec_line(target, arguments)`

Die Funktion lautet danach:

```python
def _enable_linux(target, arguments):
    desktop_path = _linux_desktop_path()
    os.makedirs(os.path.dirname(desktop_path), exist_ok=True)

    exec_line = _exec_line(target, arguments)
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Zeiterfassung\n"
        f"Exec={exec_line}\n"
        "Hidden=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    with open(desktop_path, "w", encoding="utf-8") as f:
        f.write(content)
```

- [ ] **Step 5: Neuen Test + bestehende Linux-Tests laufen lassen, grün bestätigen**

Run: `pytest tests/test_autostart.py -k Linux -v`
Expected: PASS — `test_enable_writes_desktop_file` und `test_enable_without_arguments_has_no_trailing_space` bleiben grün (Werte ohne Sonderzeichen → unverändert), `test_enable_quotes_path_with_spaces` ist neu grün.

- [ ] **Step 6: Lint auf die geänderten Dateien**

Run: `ruff check src/autostart.py tests/test_autostart.py`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add src/autostart.py tests/test_autostart.py
git commit -m "$(cat <<'EOF'
fix(autostart): Linux-.desktop Exec-Zeile shell-korrekt quoten (N12)

_enable_linux schrieb target/arguments ungequotet in die Exec=-Zeile — ein
Installationspfad mit Leerzeichen zerbrach den Autostart-Eintrag. Jetzt via
shlex.quote (deckt sich mit GLibs g_shell_parse_argv). Werte ohne
Sonderzeichen bleiben unverändert.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Gesamt-Verifikation & PR-Vorbereitung

**Files:** keine Änderung — reiner Verifikations-Gate.

- [ ] **Step 1: Gesamte Test-Suite laufen lassen**

Run: `pytest`
Expected: PASS — alle bisherigen Tests plus die neuen (N9: 2, N10: 1, N12: 1); keine Regression.

- [ ] **Step 2: Vollständiger Lint**

Run: `ruff check .`
Expected: `All checks passed!`

- [ ] **Step 3: Diff gegen `master` sichten (Verhaltensgleichheit im Normalfall)**

Run: `git log --oneline master..HEAD` und `git diff master --stat`
Expected: genau die drei fix-Commits (plus die Spec/Plan-Doc-Commits); geänderte Dateien nur `src/single_instance.py`, `src/mail.py`, `src/autostart.py` + die drei Testdateien + `docs/superpowers/...`.

- [ ] **Step 4: PR — nur auf wörtlichen Trigger**

`git push` und `gh pr create` **nicht** automatisch ausführen (CLAUDE.md). Dem Nutzer den fertigen, lokal grünen Stand melden und auf Trigger warten. Vorbereiteter PR-Text (Findings N9/N10/N12, Verweis auf Issue #131, N9-Bedrohungsmodell ehrlich gescopet). **Hinweis für den PR:** N12 ist Linux-spezifisch und auf der Windows-Dev-Maschine nicht gegen eine echte Desktop-Umgebung verifizierbar → vor dem nächsten echten Release einen Pre-Release vorschlagen (CLAUDE.md: „Plattformspezifische PRs — Pre-Release vorschlagen").

---

## Verifikations-Zusammenfassung

| Finding | Datei | Neuer Test | Bestehende Tests |
|---|---|---|---|
| N9 | `src/single_instance.py` | `test_handshake_without_secret_is_rejected`, `test_secret_write_failure_yields_bound_unauth_guard` | `test_single_instance.py` (5 Stück) unverändert grün |
| N10 | `src/mail.py` | `test_fetch_user_email_sends_token_in_post_body_not_url` | `test_fetch_user_email_uses_tokeninfo_not_gmail_getprofile` unverändert grün |
| N12 | `src/autostart.py` | `test_enable_quotes_path_with_spaces` | `test_enable_writes_desktop_file`, `test_enable_without_arguments_has_no_trailing_space` unverändert grün |

Gesamt-Gate: `pytest` + `ruff check .` grün. N12 zusätzlich Pre-Release-Realtest auf Linux empfohlen (nicht headless verifizierbar).
