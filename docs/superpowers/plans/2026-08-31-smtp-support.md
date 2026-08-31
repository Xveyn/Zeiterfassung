# SMTP-Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SMTP wird ein vollwertiger, gleichrangiger Mailweg neben der Gmail-API — in beiden Sendepfaden (Bericht senden und Teilen), mit n konfigurierbaren Konten je eigenem Empfänger.

**Architecture:** Der MIME-Bau wandert aus `mail.send_email` in ein reines Modul, das Gmail und SMTP teilen; die UTF-8-Pflichten und die Header-Injection-Abwehr existieren damit genau einmal. `send_task.perform_send` bleibt der Dispatcher, der er seit Audit M10 ist, und bekommt SMTP als dritten Kanaltyp neben Mail und Webhooks. Konten liegen in einem gerätelokalen Store nach dem Vorbild von `webhook_store.py`; Passwörter liegen im OS-Schlüsselbund mit Datei-Fallback.

**Tech Stack:** Python 3.10, stdlib (`smtplib`, `ssl`, `email`), `keyring==25.7.0`, Tkinter, pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-smtp-support-design.md`

## Global Constraints

- **Python 3.10** ist das CI- und Release-Python. Jede neue gepinnte Dependency muss 3.10 unterstützen.
- **Shell unter Windows:** kein `&&` zum Verketten. Sequenziell mit `;`, bedingt mit `if ($?) { ... }`.
- **Tests laufen aus dem Repo-Root:** `pytest`, einzeln `pytest tests/test_x.py::test_name -v`.
- **UI-Strings sind deutsch.** Fehlermeldungen sagen, was zu tun ist.
- **Getestet wird Logik, nicht UI** (entschiedene Scope-Grenze M16). Tk-gebundener Code bekommt keine automatisierten Tests; die Logik gehört Tk-frei in pure Module.
- **Neue Tk-freie Module werden vollständig annotiert** (Rückgabetyp **und** alle Parameter) und in `ANNOTATED_MODULES` in `tests/test_type_annotations.py` eingetragen. Ein Eintrag dort ist eine Zusage — eine falsche Annotation ist schlimmer als keine.
- **`import keyring` immer lazy innerhalb der Funktion**, nie auf Modulebene. Die Importkette `src.ui → … → smtp_store` zöge die Lib sonst in die CI, die bewusst nur `requirements-test.txt` installiert.
- **Secrets nie loggen.** `logs/zeiterfassung.log` ist ungehärtet und genau die Datei, die Nutzer bei Problemen anhängen. Bei Datensatz-Warnungen nur `id` und `name` loggen (Muster `webhook_store._load`).
- **Dialoge über `theme.create_dialog`**, themed Messageboxes für kuratierte Meldungen, rohes `tkinter.messagebox.showerror` nur für Catch-all-Zweige mit Traceback. Keine dialogspezifischen Stil-Extras.
- **Blockierendes gehört in den `BackgroundTaskRunner`**, nie in einen Tk-Callback: `store.save`/`delete` starten einen icacls-Subprozess (timeout 15 s), SMTP-Verbindungen gehen ins Netz, und der Schlüsselbund kann auf Linux ein D-Bus-Roundtrip sein.
- **Commit-Messages** enden mit den beiden Trailern:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01VJux6qnwTncwi1qbmHBHet
  ```
  Mehrzeilige Messages über eine Datei (`git commit -F <datei>`) — Heredoc und PowerShell-Here-String scheitern in dieser Umgebung.

---

### Task 1: MIME-Bau herausziehen (`src/mime_message.py`)

Reiner Refactor ohne Verhaltensänderung. `tests/test_mail.py` bleibt unverändert und muss grün bleiben — das ist die Absicherung, dass am Gmail-Pfad nichts verrutscht.

**Files:**
- Create: `src/mime_message.py`
- Modify: `src/mail.py` (die Funktion `send_email`, aktuell ab Zeile 341)
- Modify: `tests/test_type_annotations.py` (Liste `ANNOTATED_MODULES`)
- Test: `tests/test_mime_message.py`

**Interfaces:**
- Consumes: nichts (erste Task)
- Produces:
  ```python
  build_message(*, to: str, subject: str, html_body: str,
                attachment_bytes: bytes | None = None,
                attachment_filename: str | None = None,
                attachment_subtype: str = "pdf",
                from_addr: str | None = None) -> Message
  ```
  Wirft `ValueError`, wenn `to` oder `from_addr` `\r`, `\n` oder `\x00` enthält.

- [ ] **Step 1: Write the failing test**

Neue Datei `tests/test_mime_message.py`:

```python
"""Tests für den gemeinsamen MIME-Bau (Gmail-API und SMTP teilen ihn).

Hier liegen die drei UTF-8-Pflichten (CLAUDE.md) und die Steuerzeichen-Abwehr
gegen Header-Injection (Audit N11) — beides genau einmal im Repo, deshalb
genau hier getestet.
"""

import pytest

from src.mime_message import build_message


def test_plain_message_is_utf8_html():
    msg = build_message(to="a@example.com", subject="Bericht",
                        html_body="<p>Grüße</p>")
    assert msg["to"] == "a@example.com"
    assert msg.get_content_type() == "text/html"
    assert msg.get_content_charset() == "utf-8"


def test_subject_is_utf8_encoded():
    """Umlaute im Betreff dürfen nicht als Mojibake ankommen."""
    from email.header import decode_header

    msg = build_message(to="a@example.com", subject="Müller & Söhne",
                        html_body="<p>x</p>")
    decoded = decode_header(msg["subject"])[0]
    assert decoded[1] == "utf-8"
    assert decoded[0].decode("utf-8") == "Müller & Söhne"


def test_attachment_uses_given_subtype_and_filename():
    msg = build_message(to="a@example.com", subject="S", html_body="<p>x</p>",
                        attachment_bytes=b'{"x":1}',
                        attachment_filename="share.json",
                        attachment_subtype="json")
    raw = msg.as_string()
    assert "application/json" in raw
    assert "share.json" in raw


def test_attachment_without_filename_falls_back_to_subtype():
    msg = build_message(to="a@example.com", subject="S", html_body="<p>x</p>",
                        attachment_bytes=b"%PDF-1.4",
                        attachment_subtype="pdf")
    assert "attachment.pdf" in msg.as_string()


def test_from_addr_is_only_set_when_given():
    """Gmail setzt kein From (der authentifizierte Nutzer ist der Absender),
    SMTP schon."""
    without = build_message(to="a@example.com", subject="S", html_body="<p>x</p>")
    assert without["from"] is None

    with_from = build_message(to="a@example.com", subject="S",
                              html_body="<p>x</p>", from_addr="me@example.com")
    assert with_from["from"] == "me@example.com"


@pytest.mark.parametrize("evil", [
    "victim@example.com\r\nBcc: attacker@evil.com",
    "victim@example.com\nBcc: attacker@evil.com",
    "victim@example.com\x00",
])
def test_control_chars_in_recipient_are_rejected(evil):
    """Audit N11 / #133: abweisen statt still strippen — ein gestripptes
    'a@b\\nBcc: c' ginge sonst an die vermurkste Adresse 'a@bBcc: c'."""
    with pytest.raises(ValueError):
        build_message(to=evil, subject="S", html_body="<p>x</p>")


@pytest.mark.parametrize("evil", [
    "me@example.com\r\nBcc: attacker@evil.com",
    "me@example.com\x00",
])
def test_control_chars_in_from_addr_are_rejected(evil):
    """Beim SMTP-Versand ist der Absender ein zweites nutzergefülltes
    Headerfeld mit demselben Injection-Risiko wie der Empfänger."""
    with pytest.raises(ValueError):
        build_message(to="a@example.com", subject="S", html_body="<p>x</p>",
                      from_addr=evil)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mime_message.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.mime_message'`

- [ ] **Step 3: Write the implementation**

Neue Datei `src/mime_message.py`:

```python
"""Aufbau der Mail-Nachricht — gemeinsam für Gmail-API und SMTP.

Tk-frei, stdlib-only, ohne Google-Import. Hier liegen die drei UTF-8-Pflichten
(CLAUDE.md, „UTF-8 im Mail-Pipeline") und die Steuerzeichen-Abwehr gegen
Header-Injection (Audit N11) — genau einmal, damit sie für beide Transporte
gilt und nicht in zwei Kopien auseinanderläuft.
"""

from __future__ import annotations

from email.header import Header
from email.message import Message
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_FORBIDDEN_CHARS = ("\r", "\n", "\x00")


def _reject_control_chars(value: str, label: str) -> None:
    """Weist Steuerzeichen ab, statt sie still zu strippen (Audit N11 / #133).

    Ein gestripptes „a@b\\nBcc: c" würde an die vermurkste Adresse
    „a@bBcc: c" gesendet, ohne dass der Nutzer es merkt — stille
    Falschzustellung ist schlimmer als ein sichtbarer Fehler.
    """
    if any(ch in value for ch in _FORBIDDEN_CHARS):
        raise ValueError(
            f"Die {label} enthält unzulässige Steuerzeichen (Zeilenumbruch "
            "oder Nullbyte). Bitte korrigiere die Adresse in den "
            "Einstellungen."
        )


def build_message(*, to: str, subject: str, html_body: str,
                  attachment_bytes: bytes | None = None,
                  attachment_filename: str | None = None,
                  attachment_subtype: str = "pdf",
                  from_addr: str | None = None) -> Message:
    """Baut die fertige Mail-Nachricht.

    `from_addr` wird nur gesetzt, wenn übergeben: die Gmail-API kennt den
    Absender aus dem Token, SMTP braucht ihn im Header.
    """
    _reject_control_chars(to, "Empfängeradresse")
    if from_addr is not None:
        _reject_control_chars(from_addr, "Absenderadresse")

    message: Message
    if attachment_bytes:
        message = MIMEMultipart()
        message.attach(MIMEText(html_body, "html", _charset="utf-8"))
        attachment = MIMEApplication(attachment_bytes, _subtype=attachment_subtype)
        attachment.add_header(
            "Content-Disposition", "attachment",
            filename=attachment_filename or f"attachment.{attachment_subtype}",
        )
        message.attach(attachment)
    else:
        message = MIMEText(html_body, "html", _charset="utf-8")

    message["to"] = to
    message["subject"] = Header(subject, "utf-8")  # pyright: ignore[reportArgumentType]
    if from_addr is not None:
        message["from"] = from_addr
    return message
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mime_message.py -v`
Expected: PASS (7 Tests bzw. 12 mit Parametrisierung)

- [ ] **Step 5: `mail.send_email` auf den gemeinsamen Bau umstellen**

In `src/mail.py`: den Import ergänzen und den Rumpf von `send_email` ab dem Kommentarblock „Header-Injection UND stille Falschzustellung verhindern" bis einschließlich `message.attach(attachment)` / dem `else`-Zweig ersetzen.

Import oben in `src/mail.py` — die vier jetzt ungenutzten `email.*`-Importe (`MIMEText`, `MIMEMultipart`, `MIMEApplication`, `Header`) **entfernen**, sonst schlägt `ruff` zu:

```python
from src.mime_message import build_message
```

Neuer Rumpf von `send_email` (Signatur und Legacy-Alias-Behandlung bleiben unverändert):

```python
    if pdf_bytes is not None and attachment_bytes is None:
        attachment_bytes = pdf_bytes
        attachment_filename = attachment_filename or pdf_filename
        attachment_subtype = "pdf"

    # Der MIME-Bau inklusive UTF-8-Pflichten und Steuerzeichen-Abwehr liegt in
    # src/mime_message.py — dieselbe Nachricht baut der SMTP-Pfad. Kein `from`:
    # die Gmail-API setzt den authentifizierten Nutzer als Absender.
    message = build_message(
        to=to, subject=subject, html_body=html_body,
        attachment_bytes=attachment_bytes,
        attachment_filename=attachment_filename,
        attachment_subtype=attachment_subtype,
    )

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    body = {"raw": raw}

    sent = service.users().messages().send(userId="me", body=body).execute()
    return sent["id"]
```

- [ ] **Step 6: Bestandstests laufen lassen**

Run: `pytest tests/test_mail.py tests/test_send_task.py tests/test_share_task.py -v`
Expected: PASS — insbesondere `test_send_email_json_attachment_uses_subtype` und `test_send_email_rejects_recipient_with_control_chars`. Beide sind unverändert und belegen, dass der Refactor nichts verschoben hat.

- [ ] **Step 7: Modul in die Annotations-Whitelist eintragen**

In `tests/test_type_annotations.py`, in der Liste `ANNOTATED_MODULES` direkt nach `"src/time_utils.py"`:

```python
    "src/mime_message.py",
```

- [ ] **Step 8: Lint, Typecheck und die volle Suite**

Run: `ruff check .`
Run: `npx pyright`
Run: `pytest`
Expected: alles grün.

- [ ] **Step 9: Commit**

```bash
git add src/mime_message.py src/mail.py tests/test_mime_message.py tests/test_type_annotations.py
git commit -F <commit-message-datei>
```

Commit-Message:

```
refactor(mail): MIME-Bau in src/mime_message.py herausziehen

Die drei UTF-8-Pflichten und die Steuerzeichen-Abwehr (Audit N11) lagen
in send_email verwoben mit dem Gmail-Versand. Der SMTP-Pfad braucht
dieselbe Nachricht — als Kopie liefe sie mit der Zeit auseinander.

Die Abwehr prueft jetzt auch from_addr: beim SMTP-Versand ist der
Absender ein zweites nutzergefuelltes Headerfeld.

Kein Verhaltenswechsel; tests/test_mail.py ist unveraendert gruen.
```

---

### Task 2: Schlüsselbund-Zugriff (`src/keyring_store.py`)

**Files:**
- Create: `src/keyring_store.py`
- Modify: `requirements.txt`
- Modify: `requirements-test.txt`
- Modify: `tests/test_type_annotations.py`
- Test: `tests/test_keyring_store.py`

**Interfaces:**
- Consumes: nichts
- Produces:
  ```python
  SERVICE: str  # == "Zeiterfassung"
  set_secret(record_id: str, password: str) -> str      # "keyring" | "file"
  get_secret(record: dict[str, Any]) -> str
  delete_secret(record_id: str) -> None
  ```
  `get_secret` liest bei `record["password_location"] == "file"` aus `record["password"]`, sonst aus dem Schlüsselbund; findet es dort nichts, fällt es auf `record.get("password")` zurück und liefert im Zweifel `""`.

- [ ] **Step 1: Write the failing test**

Neue Datei `tests/test_keyring_store.py`:

```python
"""Tests für den Schlüsselbund-Zugriff inklusive Datei-Fallback.

`keyring` wird im Produktivcode lazy innerhalb der Funktionen importiert
(CI-Pflicht). Die Tests schieben deshalb ein Fake-Modul in sys.modules,
statt das echte Backend des Testrechners anzufassen — ein Test darf keine
Einträge im Windows-Anmeldeinformationsmanager hinterlassen.
"""

import sys
import types

import pytest

from src import keyring_store


class _FakeKeyring:
    """Minimaler Ersatz für das keyring-Modul."""

    def __init__(self, working=True):
        self.working = working
        self.store = {}

    def set_password(self, service, account, password):
        if not self.working:
            raise RuntimeError("No recommended backend was available")
        self.store[(service, account)] = password

    def get_password(self, service, account):
        if not self.working:
            raise RuntimeError("No recommended backend was available")
        return self.store.get((service, account))

    def delete_password(self, service, account):
        if not self.working:
            raise RuntimeError("No recommended backend was available")
        del self.store[(service, account)]


@pytest.fixture
def fake_keyring(monkeypatch):
    def _install(working=True):
        fake = _FakeKeyring(working=working)
        module = types.ModuleType("keyring")
        module.set_password = fake.set_password
        module.get_password = fake.get_password
        module.delete_password = fake.delete_password
        monkeypatch.setitem(sys.modules, "keyring", module)
        return fake
    return _install


def test_set_secret_uses_keyring_when_available(fake_keyring):
    fake = fake_keyring()
    location = keyring_store.set_secret("rec-1", "geheim")
    assert location == "keyring"
    assert fake.store[(keyring_store.SERVICE, "rec-1")] == "geheim"


def test_set_secret_falls_back_to_file_without_backend(fake_keyring):
    """Linux ohne Secret Service: das Feature muss trotzdem funktionieren."""
    fake_keyring(working=False)
    assert keyring_store.set_secret("rec-1", "geheim") == "file"


def test_set_secret_falls_back_when_keyring_is_not_installed(monkeypatch):
    """Kein keyring im Environment (CI-Testlauf ohne die Lib)."""
    monkeypatch.setitem(sys.modules, "keyring", None)
    assert keyring_store.set_secret("rec-1", "geheim") == "file"


def test_get_secret_reads_from_keyring(fake_keyring):
    fake_keyring()
    keyring_store.set_secret("rec-1", "geheim")
    record = {"id": "rec-1", "password_location": "keyring"}
    assert keyring_store.get_secret(record) == "geheim"


def test_get_secret_reads_from_record_when_location_is_file(fake_keyring):
    """Beim Datei-Fallback wird der Schlüsselbund gar nicht erst gefragt."""
    fake_keyring(working=False)
    record = {"id": "rec-1", "password_location": "file", "password": "geheim"}
    assert keyring_store.get_secret(record) == "geheim"


def test_get_secret_returns_empty_string_when_nothing_is_stored(fake_keyring):
    fake_keyring()
    record = {"id": "unbekannt", "password_location": "keyring"}
    assert keyring_store.get_secret(record) == ""


def test_delete_secret_removes_the_entry(fake_keyring):
    """Ohne das bliebe das Secret nach dem Löschen des Kontos verwaist."""
    fake = fake_keyring()
    keyring_store.set_secret("rec-1", "geheim")
    keyring_store.delete_secret("rec-1")
    assert (keyring_store.SERVICE, "rec-1") not in fake.store


def test_delete_secret_is_quiet_when_nothing_is_stored(fake_keyring):
    """Ein fehlendes Secret ist kein Fehler — der Aufrufer löscht ohnehin."""
    fake_keyring()
    keyring_store.delete_secret("gibt-es-nicht")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_keyring_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.keyring_store'`

- [ ] **Step 3: Write the implementation**

Neue Datei `src/keyring_store.py`:

```python
"""Passwörter im OS-Schlüsselbund, mit Datei-Fallback (Tk-frei).

Windows Credential Manager / macOS Keychain / Linux Secret Service. Ist kein
Backend verfügbar — Linux ohne laufenden Secret Service, oder `keyring` gar
nicht installiert —, meldet `set_secret` das ehrlich als `"file"` zurück; der
Aufrufer legt das Passwort dann in seinen eigenen, gehärtet geschriebenen
Store und zeigt es dem Nutzer an.

`import keyring` steht bewusst INNERHALB der Funktionen: die Importkette
`src.ui → … → smtp_store → keyring_store` zöge die Lib sonst in die CI, die
bewusst nur `requirements-test.txt` installiert (gleiches Muster wie die
Google-Wrapper in drive.py/gcal.py).

Blockierend: auf Linux ist jeder Zugriff ein D-Bus-Roundtrip. Gehört in einen
Worker-Thread, nie in einen Tk-Callback.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

SERVICE = "Zeiterfassung"


def set_secret(record_id: str, password: str) -> str:
    """Legt `password` im Schlüsselbund ab.

    Liefert `"keyring"` bei Erfolg, sonst `"file"` — dieser Wert gehört als
    `password_location` in den Datensatz des Aufrufers.
    """
    try:
        import keyring

        keyring.set_password(SERVICE, record_id, password)
    except Exception:
        # Bewusst alles: NoKeyringError, ein fehlgeschlagener D-Bus-Aufruf,
        # eine gar nicht installierte Lib. Für den Aufrufer ist all das
        # dasselbe — es gibt keinen Schlüsselbund.
        log.warning("Schlüsselbund nicht verfügbar — Passwort wird lokal "
                    "in der Konfigurationsdatei abgelegt", exc_info=True)
        return "file"
    return "keyring"


def get_secret(record: dict[str, Any]) -> str:
    """Liest das Passwort zu `record`.

    Steht `password_location` auf `"file"`, wird der Schlüsselbund gar nicht
    erst gefragt — auf Linux spart das einen D-Bus-Roundtrip, der ohnehin
    nichts liefern würde.
    """
    if record.get("password_location") == "file":
        return record.get("password") or ""
    try:
        import keyring

        stored = keyring.get_password(SERVICE, record.get("id", ""))
    except Exception:
        log.warning("Schlüsselbund nicht lesbar — greife auf die lokal "
                    "abgelegte Kopie zurück, falls vorhanden", exc_info=True)
        return record.get("password") or ""
    if stored:
        return stored
    return record.get("password") or ""


def delete_secret(record_id: str) -> None:
    """Räumt das Secret ab. Fehlt es, ist das kein Fehler.

    Muss beim Löschen eines Kontos gerufen werden — sonst bliebe der Eintrag
    für immer im Schlüsselbund stehen.
    """
    try:
        import keyring

        keyring.delete_password(SERVICE, record_id)
    except Exception:
        log.debug("Secret %r nicht gelöscht (kein Schlüsselbund oder kein "
                  "Eintrag)", record_id, exc_info=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_keyring_store.py -v`
Expected: PASS (8 Tests)

- [ ] **Step 5: Dependency pinnen**

In `requirements.txt`, nach der `holidays`-Zeile:

```
keyring==25.7.0
```

In `requirements-test.txt`, nach `google-auth-oauthlib==1.4.0`:

```
# Fuer tests/test_keyring_store.py: die Tests schieben zwar ein Fake-Modul in
# sys.modules, aber der Fallback-Pfad soll auch gegen die echte Lib laufen.
# Rein Python auf Ubuntu (SecretStorage/jeepney), daher kein CI-Risiko.
keyring==25.7.0
```

In der README-Tabelle der Abhängigkeiten (Abschnitt „Abhängigkeiten") eine Zeile ergänzen:

```markdown
| `keyring` | SMTP-Passwörter im Schlüsselbund des Betriebssystems |
```

- [ ] **Step 6: Modul in die Annotations-Whitelist eintragen**

In `tests/test_type_annotations.py`, in `ANNOTATED_MODULES` im Block „Infra-/Plattform-Schicht" nach `"src/secure_file.py"`:

```python
    "src/keyring_store.py",
```

- [ ] **Step 7: Lint, Typecheck, volle Suite**

Run: `ruff check .`
Run: `npx pyright`
Run: `pytest`
Expected: alles grün.

- [ ] **Step 8: Commit**

```bash
git add src/keyring_store.py tests/test_keyring_store.py requirements.txt requirements-test.txt README.md tests/test_type_annotations.py
git commit -F <commit-message-datei>
```

Commit-Message:

```
feat(secrets): Schluesselbund-Zugriff mit Datei-Fallback

set_secret meldet zurueck, wo das Passwort gelandet ist ("keyring" oder
"file") — der Aufrufer haelt das im Datensatz und zeigt es dem Nutzer.
Ohne Fallback fiele das Feature auf Linux ohne Secret Service komplett
aus.

keyring==25.7.0 gepinnt (requires_python >=3.9, unser 3.10 also gruen).
```

---

### Task 3: Kontenspeicher (`src/smtp_store.py`)

**Files:**
- Create: `src/smtp_store.py`
- Modify: `tests/test_type_annotations.py`
- Test: `tests/test_smtp_store.py`

**Interfaces:**
- Consumes: `keyring_store.delete_secret` aus Task 2
- Produces:
  ```python
  SCHEMA_VERSION: int  # == 1
  SECURITY_MODES: tuple[str, ...]  # ("starttls", "ssl", "none")
  class SmtpStoreReadOnly(Exception): ...
  new_id() -> str
  validate_record(record: dict, existing: list[dict]) -> tuple[bool, str]
  class SmtpStore:
      def __init__(self, filepath: str = "smtp.json",
                   lock: threading.RLock | None = None) -> None: ...
      def get_all(self) -> list[dict]: ...
      def enabled(self) -> list[dict]: ...
      def save(self, record: dict) -> None: ...
      def delete(self, account_id: str) -> None: ...
  ```
  Record-Form:
  ```python
  {"id": str, "name": str, "enabled": bool, "host": str, "port": int,
   "security": "starttls" | "ssl" | "none", "username": str,
   "from_addr": str, "recipient": str,
   "password_location": "keyring" | "file",
   "password": str}   # nur bei password_location == "file"
  ```

- [ ] **Step 1: Write the failing test**

Neue Datei `tests/test_smtp_store.py`:

```python
"""Tests für den gerätelokalen SMTP-Kontenspeicher.

Spiegelt tests/test_webhook_store.py: Validierung, Quarantäne bei kaputter
Datei, Read-Only bei neuerer schema_version, Rollback bei Schreibfehlern.
"""

import json
import os

import pytest

from src import smtp_store
from src.smtp_store import SmtpStore, SmtpStoreReadOnly, validate_record


def _record(**overrides):
    base = {
        "id": "rec-1", "name": "Firma", "enabled": True,
        "host": "mail.example.com", "port": 587, "security": "starttls",
        "username": "user@example.com", "from_addr": "user@example.com",
        "recipient": "buchhaltung@example.com",
        "password_location": "keyring",
    }
    base.update(overrides)
    return base


def test_new_id_is_unique():
    assert smtp_store.new_id() != smtp_store.new_id()


def test_valid_record_passes():
    ok, msg = validate_record(_record(), [])
    assert ok, msg


@pytest.mark.parametrize("overrides,fragment", [
    ({"name": "   "}, "Namen"),
    ({"host": ""}, "Server"),
    ({"port": 0}, "Port"),
    ({"port": 70000}, "Port"),
    ({"port": "587"}, "Port"),
    ({"security": "tls"}, "Verschlüsselung"),
    ({"from_addr": ""}, "Absenderadresse"),
    ({"recipient": ""}, "Empfängeradresse"),
])
def test_invalid_records_are_rejected(overrides, fragment):
    ok, msg = validate_record(_record(**overrides), [])
    assert not ok
    assert fragment in msg


def test_empty_username_is_allowed():
    """Interner Relay ohne Auth — Benutzer darf leer bleiben."""
    ok, msg = validate_record(_record(username=""), [])
    assert ok, msg


def test_password_is_not_validated_here():
    """Bei aktivem Schlüsselbund steht das Passwort gar nicht im Datensatz.
    Die Regel „bei gesetztem Benutzer ist ein Passwort Pflicht" gehört in den
    Dialog, der das Eingabefeld besitzt."""
    ok, msg = validate_record(_record(username="u"), [])
    assert ok, msg


def test_duplicate_name_is_rejected():
    existing = [_record(id="rec-0", name="Firma")]
    ok, msg = validate_record(_record(id="rec-1", name="firma"), existing)
    assert not ok
    assert "bereits" in msg


def test_renaming_itself_is_allowed():
    """Derselbe Datensatz kollidiert nicht mit sich selbst."""
    existing = [_record(id="rec-1", name="Firma")]
    ok, msg = validate_record(_record(id="rec-1", name="Firma"), existing)
    assert ok, msg


@pytest.mark.parametrize("field", ["from_addr", "recipient"])
def test_control_chars_in_addresses_are_rejected(field):
    ok, msg = validate_record(_record(**{field: "a@b\r\nBcc: c@d"}), [])
    assert not ok
    assert "Steuerzeichen" in msg


def test_save_and_reload(tmp_path):
    path = str(tmp_path / "smtp.json")
    store = SmtpStore(path)
    store.save(_record())
    assert [r["name"] for r in SmtpStore(path).get_all()] == ["Firma"]


def test_save_replaces_by_id(tmp_path):
    path = str(tmp_path / "smtp.json")
    store = SmtpStore(path)
    store.save(_record())
    store.save(_record(name="Neu"))
    assert [r["name"] for r in store.get_all()] == ["Neu"]


def test_enabled_filters_disabled_accounts(tmp_path):
    store = SmtpStore(str(tmp_path / "smtp.json"))
    store.save(_record(id="a", name="An", enabled=True))
    store.save(_record(id="b", name="Aus", enabled=False))
    assert [r["name"] for r in store.enabled()] == ["An"]


def test_get_all_returns_a_copy(tmp_path):
    """Sonst mutiert der Aufrufer den Store-Inhalt."""
    store = SmtpStore(str(tmp_path / "smtp.json"))
    store.save(_record())
    store.get_all()[0]["name"] = "manipuliert"
    assert store.get_all()[0]["name"] == "Firma"


def test_delete_removes_the_account_and_its_secret(tmp_path, monkeypatch):
    deleted = []
    monkeypatch.setattr(smtp_store.keyring_store, "delete_secret", deleted.append)
    store = SmtpStore(str(tmp_path / "smtp.json"))
    store.save(_record())
    store.delete("rec-1")
    assert store.get_all() == []
    assert deleted == ["rec-1"]


def test_corrupt_file_is_quarantined(tmp_path):
    path = tmp_path / "smtp.json"
    path.write_text("{kein json", encoding="utf-8")
    store = SmtpStore(str(path))
    assert store.get_all() == []
    assert not path.exists()
    assert any(p.name.startswith("smtp.json.corrupt-") for p in tmp_path.iterdir())


def test_newer_schema_version_is_read_only(tmp_path):
    """Ein älterer Build darf eine neuere Datei nicht überschreiben — und ein
    stiller Fehlschlag wäre schlimmer als eine Exception."""
    path = tmp_path / "smtp.json"
    path.write_text(json.dumps(
        {"schema_version": smtp_store.SCHEMA_VERSION + 1, "accounts": []}),
        encoding="utf-8")
    store = SmtpStore(str(path))
    with pytest.raises(SmtpStoreReadOnly):
        store.save(_record())


def test_unreadable_file_is_not_quarantined(tmp_path, monkeypatch):
    """Ein kurzzeitig gesperrtes File (Virenscanner, Backup) ist kein
    defektes File — die Konfiguration samt Secrets darf nicht wegfliegen."""
    path = tmp_path / "smtp.json"
    path.write_text(json.dumps({"schema_version": 1, "accounts": []}),
                    encoding="utf-8")

    real_open = open

    def flaky_open(file, *args, **kwargs):
        if str(file) == str(path):
            raise OSError("gesperrt")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", flaky_open)
    store = SmtpStore(str(path))
    monkeypatch.undo()
    assert path.exists()
    with pytest.raises(SmtpStoreReadOnly):
        store.save(_record())


def test_malformed_record_is_skipped(tmp_path):
    path = tmp_path / "smtp.json"
    path.write_text(json.dumps({"schema_version": 1, "accounts": [
        {"id": "gut", "name": "Gut", "enabled": True, "host": "h", "port": 587,
         "security": "starttls", "username": "", "from_addr": "a@b",
         "recipient": "c@d", "password_location": "keyring"},
        {"id": "kaputt"},
        "kein dict",
    ]}), encoding="utf-8")
    assert [r["id"] for r in SmtpStore(str(path)).get_all()] == ["gut"]


def test_saved_file_is_not_world_readable(tmp_path):
    """Die Datei kann Passwörter enthalten (Datei-Fallback)."""
    if os.name == "nt":
        pytest.skip("POSIX-Modusbits gibt es unter Windows nicht; dort greift "
                    "harden_windows_acl, getestet in tests/test_secure_file.py")
    path = str(tmp_path / "smtp.json")
    SmtpStore(path).save(_record())
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smtp_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.smtp_store'`

- [ ] **Step 3: Write the implementation**

Neue Datei `src/smtp_store.py`. Der Aufbau spiegelt `src/webhook_store.py` — beim Schreiben dort nachsehen und die Struktur übernehmen, statt sie neu zu erfinden:

```python
"""Gerätelokale Persistenz der SMTP-Konten (Tk-frei, stdlib-only).

`smtp.json` liegt neben `token.json` im Datenverzeichnis. Sie enthält
Konfiguration und — wenn kein Schlüsselbund verfügbar ist — auch Passwörter,
und wird deshalb wie `token.json` und `webhooks.json` gehärtet geschrieben
(chmod 0600 + icacls auf der Temp-Datei, dann os.replace).

Nichts hiervon reist per Drive-Sync und nichts steht im Share-Doc: SMTP-Konten
sind bewusst gerätelokal, damit kein Secret im Sync-Doc landet — dieselbe
Begründung wie bei den Webhooks.
"""

from __future__ import annotations

import copy
import datetime
import json
import logging
import os
import stat
import tempfile
import threading
import time
import uuid
from typing import Any

from src import keyring_store
from src.secure_file import harden_windows_acl

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

SECURITY_MODES = ("starttls", "ssl", "none")

Account = dict[str, Any]

_REQUIRED_KEYS = ("id", "name", "enabled", "host", "port", "security",
                  "username", "from_addr", "recipient", "password_location")
_FORBIDDEN_CHARS = ("\r", "\n", "\x00")


class SmtpStoreReadOnly(Exception):
    """Die Datei darf nicht überschrieben werden (neuere schema_version oder
    beim Start nicht lesbar). Der Aufrufer zeigt das als themed Fehlerdialog —
    ein still verworfener Speichervorgang wäre schlimmer als ein Fehler."""


def new_id() -> str:
    """Stabile Kennung eines Kontos. Trägt die Zuordnung — auch zum Secret im
    Schlüsselbund —, wenn der Nutzer den Namen ändert."""
    return uuid.uuid4().hex


def _is_wellformed(record: Any) -> bool:
    """Strukturprüfung fürs Laden — absichtlich schwächer als validate_record."""
    if not isinstance(record, dict):
        return False
    return all(k in record for k in _REQUIRED_KEYS)


def validate_record(record: Account, existing: list[Account]) -> tuple[bool, str]:
    """Prüft einen Datensatz vor dem Speichern. Liefert `(ok, meldung)`.

    Das Passwort wird hier NICHT geprüft: bei aktivem Schlüsselbund steht es
    gar nicht im Datensatz. Die Regel „bei gesetztem Benutzer ist ein Passwort
    Pflicht" gehört in den Dialog, der das Eingabefeld besitzt, und gilt dort
    nur beim Neuanlegen.
    """
    name = (record.get("name") or "").strip()
    if not name:
        return False, "Bitte einen Namen angeben."
    for other in existing:
        if other.get("id") == record.get("id"):
            continue
        if (other.get("name") or "").strip().lower() == name.lower():
            return False, "Es gibt bereits ein Konto mit diesem Namen."

    if not (record.get("host") or "").strip():
        return False, "Bitte einen Server angeben."

    port = record.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        return False, "Der Port muss eine Zahl zwischen 1 und 65535 sein."

    if record.get("security") not in SECURITY_MODES:
        return False, "Unbekannte Verschlüsselung."

    for field, label in (("from_addr", "Absenderadresse"),
                         ("recipient", "Empfängeradresse")):
        value = (record.get(field) or "").strip()
        if not value:
            return False, f"Bitte eine {label} angeben."
        if any(ch in value for ch in _FORBIDDEN_CHARS):
            return False, (f"Die {label} enthält unzulässige Steuerzeichen "
                           "(Zeilenumbruch oder Nullbyte).")

    return True, ""


class SmtpStore:
    def __init__(self, filepath: str = "smtp.json",
                 lock: threading.RLock | None = None) -> None:
        # Wie webhook_store: einheitliche Signatur mit `lock=`, aber main.py
        # injiziert bewusst KEINEN geteilten Daten-Lock — SMTP-Konten nehmen an
        # keinem Sync-Flow teil, und save/delete halten den Lock über den
        # icacls-Subprozess (timeout 15 s) plus Retries.
        self.filepath = filepath
        self._lock = lock if lock is not None else threading.RLock()
        self._accounts: list[Account] = []
        self._readonly = False
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except OSError:
            # KEINE Quarantäne: ein kurzzeitig gesperrtes File (Virenscanner,
            # Backup, Netzlaufwerk) ist kein defektes File. Umbenennen hieße,
            # eine intakte Konfiguration samt Passwörtern wegzuwerfen.
            self._readonly = True
            log.warning("smtp.json nicht lesbar — starte ohne SMTP-Konten, "
                        "die Datei wird nicht überschrieben", exc_info=True)
            return
        except (json.JSONDecodeError, ValueError):
            self._quarantine("JSON nicht parsebar")
            return
        if not isinstance(data, dict):
            self._quarantine(f"unerwartetes Toplevel-Format ({type(data).__name__})")
            return

        version = data.get("schema_version")
        if isinstance(version, int) and not isinstance(version, bool) \
                and version > SCHEMA_VERSION:
            self._readonly = True
            log.warning(
                "smtp.json hat schema_version %s (bekannt: %s) — die Datei "
                "wird nicht gelesen und nicht überschrieben.",
                version, SCHEMA_VERSION)
            return

        raw = data.get("accounts")
        if not isinstance(raw, list):
            return
        for record in raw:
            if _is_wellformed(record):
                self._accounts.append(record)
            else:
                # NIEMALS den Datensatz selbst loggen — er kann im
                # Datei-Fallback das Passwort enthalten, und
                # logs/zeiterfassung.log ist ungehärtet und genau die Datei,
                # die Nutzer bei Problemen anhängen.
                log.warning(
                    "smtp.json: Datensatz übersprungen (id=%r, name=%r)",
                    (record or {}).get("id") if isinstance(record, dict) else None,
                    (record or {}).get("name") if isinstance(record, dict) else None,
                )

    def _quarantine(self, reason: str) -> None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        target = f"{self.filepath}.corrupt-{stamp}"
        try:
            os.replace(self.filepath, target)
        except OSError:
            log.warning("smtp.json korrupt (%s); Quarantäne-Rename "
                        "fehlgeschlagen — starte ohne SMTP-Konten", reason,
                        exc_info=True)
            return
        log.warning("smtp.json korrupt (%s) — nach %s in Quarantäne "
                    "verschoben, starte ohne SMTP-Konten",
                    reason, os.path.basename(target))

    def _save_to_disk(self) -> None:
        """Atomar und gehärtet — derselbe Ablauf wie webhook_store/write_token.

        chmod und icacls laufen auf der TEMP-Datei: sonst gäbe es ein Fenster,
        in dem smtp.json schon am Zielpfad steht, aber noch die geerbten
        Rechte trägt.
        """
        if self._readonly:
            raise SmtpStoreReadOnly(
                "Die SMTP-Datei stammt von einer neueren Version oder ist "
                "nicht lesbar und wird deshalb nicht überschrieben.")
        payload = {"schema_version": SCHEMA_VERSION, "accounts": self._accounts}
        directory = os.path.dirname(os.path.abspath(self.filepath))
        fd, tmp_path = tempfile.mkstemp(
            dir=directory, prefix=".smtp-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
            except OSError:
                pass
            harden_windows_acl(tmp_path)
            # Retry wie in webhook_store/oauth_utils.write_token (#135/#117):
            # ein Virenscanner, der die frische Temp-Datei greift, blockiert
            # den Rename kurzzeitig. Gezielt PermissionError, damit echte
            # Fehler nicht maskiert werden.
            attempts = 5
            for attempt in range(attempts):
                try:
                    os.replace(tmp_path, self.filepath)
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

    def get_all(self) -> list[Account]:
        with self._lock:
            return copy.deepcopy(self._accounts)

    def enabled(self) -> list[Account]:
        with self._lock:
            return copy.deepcopy(
                [a for a in self._accounts if a.get("enabled")])

    def save(self, record: Account) -> None:
        """Legt an oder ersetzt nach `id`.

        Wirft `SmtpStoreReadOnly` oder `OSError` — der Aufrufer MUSS das
        anzeigen. Bei einem Fehler bleibt der Speicherstand unverändert
        (Rollback), damit Liste und Platte nicht auseinanderlaufen.

        Blockierend (icacls-Subprozess, bis zu 15 s) — gehört in einen
        Worker-Thread, nicht in einen Tk-Callback.
        """
        with self._lock:
            previous = copy.deepcopy(self._accounts)
            for i, existing in enumerate(self._accounts):
                if existing.get("id") == record.get("id"):
                    self._accounts[i] = copy.deepcopy(record)
                    break
            else:
                self._accounts.append(copy.deepcopy(record))
            try:
                self._save_to_disk()
            except BaseException:
                self._accounts = previous
                raise

    def delete(self, account_id: str) -> None:
        """Wie `save`: wirft bei Schreibfehlern und rollt dann zurück.

        Räumt zusätzlich das Secret im Schlüsselbund ab — ohne das bliebe es
        dort für immer stehen, ohne dass irgendwas es je wieder fände.
        """
        with self._lock:
            previous = copy.deepcopy(self._accounts)
            self._accounts = [
                a for a in self._accounts if a.get("id") != account_id]
            try:
                self._save_to_disk()
            except BaseException:
                self._accounts = previous
                raise
        keyring_store.delete_secret(account_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_smtp_store.py -v`
Expected: PASS

- [ ] **Step 5: Modul in die Annotations-Whitelist eintragen**

In `tests/test_type_annotations.py`, in `ANNOTATED_MODULES` nach `"src/conflicts_store.py"`:

```python
    "src/smtp_store.py",
```

- [ ] **Step 6: Lint, Typecheck, volle Suite**

Run: `ruff check .`
Run: `npx pyright`
Run: `pytest`
Expected: alles grün.

- [ ] **Step 7: Commit**

```bash
git add src/smtp_store.py tests/test_smtp_store.py tests/test_type_annotations.py
git commit -F <commit-message-datei>
```

Commit-Message:

```
feat(smtp): gerätelokaler Kontenspeicher

smtp.json neben token.json, geschrieben wie webhooks.json: chmod 0600 +
icacls auf der Temp-Datei, dann os.replace. Quarantaene bei kaputter
Datei, Read-Only bei neuerer schema_version, Rollback bei
Schreibfehlern.

delete raeumt zusaetzlich das Secret im Schluesselbund ab — sonst bliebe
es dort fuer immer stehen.
```

---

### Task 4: Versand (`src/smtp.py`)

**Files:**
- Create: `src/smtp.py`
- Modify: `tests/test_type_annotations.py`
- Test: `tests/test_smtp.py`

**Interfaces:**
- Consumes: `mime_message.build_message` (Task 1), `mail.is_offline_error` (Bestand)
- Produces:
  ```python
  DEFAULT_TIMEOUT: int  # == 20
  send(record: dict, password: str, *, subject: str, html: str,
       attachment_bytes: bytes | None = None,
       attachment_filename: str | None = None,
       attachment_subtype: str = "pdf") -> None
  test_connection(record: dict, password: str) -> None
  classify_smtp_error(exc: BaseException) -> dict[str, Any]
  ```
  `classify_smtp_error` liefert `{"ok": False, "kind": ..., "detail": str, "error": exc, "tb": str | None}` mit `kind` aus `auth | recipient | tls | offline | server | error`.

- [ ] **Step 1: Write the failing test**

Neue Datei `tests/test_smtp.py`:

```python
"""Tests für den SMTP-Versand und seine Fehlerklassifikation.

Getestet wird gegen einen smtplib-Stub — kein Netz, kein echter Server.
"""

import smtplib
import socket
import ssl

import pytest

from src import smtp


def _record(**overrides):
    base = {
        "id": "rec-1", "name": "Firma", "enabled": True,
        "host": "mail.example.com", "port": 587, "security": "starttls",
        "username": "user@example.com", "from_addr": "user@example.com",
        "recipient": "buchhaltung@example.com",
        "password_location": "keyring",
    }
    base.update(overrides)
    return base


class _FakeServer:
    def __init__(self, host=None, port=None, timeout=None, context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.started_tls = False
        self.logged_in = None
        self.sent = []
        self.noops = 0
        self.quit_called = False

    def starttls(self, context=None):
        self.started_tls = True
        self.tls_context = context

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, message):
        self.sent.append(message)

    def noop(self):
        self.noops += 1

    def quit(self):
        self.quit_called = True


@pytest.fixture
def fake_smtp(monkeypatch):
    """Fängt sowohl SMTP als auch SMTP_SSL ab und merkt sich die Instanz."""
    created = {}

    def make(kind):
        def factory(*args, **kwargs):
            server = _FakeServer(*args, **kwargs)
            created[kind] = server
            return server
        return factory

    monkeypatch.setattr(smtp.smtplib, "SMTP", make("plain"))
    monkeypatch.setattr(smtp.smtplib, "SMTP_SSL", make("ssl"))
    return created


def test_starttls_connection_upgrades_and_logs_in(fake_smtp):
    smtp.send(_record(), "geheim", subject="S", html="<p>x</p>")
    server = fake_smtp["plain"]
    assert server.started_tls is True
    assert server.logged_in == ("user@example.com", "geheim")
    assert server.quit_called is True


def test_ssl_connection_uses_smtp_ssl_without_starttls(fake_smtp):
    smtp.send(_record(security="ssl", port=465), "geheim",
              subject="S", html="<p>x</p>")
    server = fake_smtp["ssl"]
    assert server.port == 465
    assert server.context is not None
    assert "plain" not in fake_smtp


def test_plain_connection_does_not_start_tls(fake_smtp):
    smtp.send(_record(security="none", port=25), "", subject="S", html="<p>x</p>")
    assert fake_smtp["plain"].started_tls is False


def test_no_login_without_username(fake_smtp):
    """Interner Relay ohne Auth."""
    smtp.send(_record(username=""), "", subject="S", html="<p>x</p>")
    assert fake_smtp["plain"].logged_in is None


def test_timeout_is_set(fake_smtp):
    """Ohne Timeout hängt der Worker unbegrenzt an einem stummen Server."""
    smtp.send(_record(), "geheim", subject="S", html="<p>x</p>")
    assert fake_smtp["plain"].timeout == smtp.DEFAULT_TIMEOUT


def test_message_carries_from_to_and_attachment(fake_smtp):
    smtp.send(_record(), "geheim", subject="Bericht", html="<p>Grüße</p>",
              attachment_bytes=b"%PDF-1.4", attachment_filename="b.pdf",
              attachment_subtype="pdf")
    message = fake_smtp["plain"].sent[0]
    assert message["from"] == "user@example.com"
    assert message["to"] == "buchhaltung@example.com"
    assert "b.pdf" in message.as_string()


def test_connection_is_closed_when_sending_fails(fake_smtp, monkeypatch):
    """Sonst bleibt die Verbindung offen, wenn der Server die Mail ablehnt."""
    smtp.send(_record(), "geheim", subject="S", html="<p>x</p>")
    server = fake_smtp["plain"]

    def boom(_message):
        raise smtplib.SMTPRecipientsRefused({"a@b": (550, b"nope")})

    server.send_message = boom
    monkeypatch.setattr(smtp.smtplib, "SMTP", lambda *a, **k: server)
    server.quit_called = False
    with pytest.raises(smtplib.SMTPRecipientsRefused):
        smtp.send(_record(), "geheim", subject="S", html="<p>x</p>")
    assert server.quit_called is True


def test_test_connection_sends_noop_but_no_mail(fake_smtp):
    smtp.test_connection(_record(), "geheim")
    server = fake_smtp["plain"]
    assert server.noops == 1
    assert server.sent == []
    assert server.quit_called is True


@pytest.mark.parametrize("exc,expected", [
    (smtplib.SMTPAuthenticationError(535, b"Authentication unsuccessful"), "auth"),
    (smtplib.SMTPRecipientsRefused({"a@b": (550, b"no such user")}), "recipient"),
    (smtplib.SMTPSenderRefused(553, b"bad sender", "a@b"), "recipient"),
    (smtplib.SMTPNotSupportedError("STARTTLS extension not supported"), "tls"),
    (ssl.SSLError("certificate verify failed"), "tls"),
    (socket.gaierror("Name or service not known"), "offline"),
    (ConnectionRefusedError("refused"), "offline"),
    (TimeoutError("timed out"), "offline"),
    (smtplib.SMTPServerDisconnected("connection closed"), "server"),
    (smtplib.SMTPConnectError(421, b"service unavailable"), "server"),
    (ValueError("irgendwas ganz anderes"), "error"),
])
def test_error_classification(exc, expected):
    """Ohne eigenen Klassifikator kaeme jede SMTP-Fehlerantwort als
    „unerwarteter Fehler mit Traceback" beim Nutzer an."""
    result = smtp.classify_smtp_error(exc)
    assert result["ok"] is False
    assert result["kind"] == expected


def test_only_the_unexpected_kind_carries_a_traceback():
    """Erwartete Fehler bekommen eine kurze Meldung, keinen Traceback."""
    try:
        raise smtplib.SMTPAuthenticationError(535, b"nope")
    except smtplib.SMTPAuthenticationError as e:
        assert smtp.classify_smtp_error(e)["tb"] is None
    try:
        raise ValueError("unerwartet")
    except ValueError as e:
        assert smtp.classify_smtp_error(e)["tb"] is not None


def test_detail_contains_the_server_response():
    """Der Nutzer soll sehen, was der Server gesagt hat."""
    exc = smtplib.SMTPAuthenticationError(535, b"5.7.3 Authentication unsuccessful")
    detail = smtp.classify_smtp_error(exc)["detail"]
    assert "535" in detail
    assert "Authentication unsuccessful" in detail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smtp.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.smtp'`

- [ ] **Step 3: Write the implementation**

Neue Datei `src/smtp.py`:

```python
"""SMTP-Versand (Tk-frei, stdlib-only).

Der zweite Mailweg neben der Gmail-API. Die Nachricht selbst baut
`mime_message.build_message` — dieselbe wie beim Gmail-Versand, inklusive der
UTF-8-Pflichten und der Steuerzeichen-Abwehr.

Eigener Fehlerklassifikator statt `mail_task.classify_mail_error`: der kennt
nur `filenotfound`/`offline`/`error`, während hier `auth`/`recipient`/`tls`/
`server` unterschieden werden müssen. Ohne diese Zweige käme jede
SMTP-Fehlerantwort als „unerwarteter Fehler mit Traceback" beim Nutzer an
statt als „Die Zugangsdaten wurden abgelehnt" (Muster wie webhook.py).
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import traceback
from typing import Any

from src.mail import is_offline_error
from src.mime_message import build_message

log = logging.getLogger(__name__)

# Ohne Timeout hängt der Worker-Thread unbegrenzt an einem Server, der die
# Verbindung annimmt und dann schweigt.
DEFAULT_TIMEOUT = 20


def _open(record: dict[str, Any], password: str) -> smtplib.SMTP:
    """Baut die Verbindung auf und meldet sich an.

    Schlägt etwas nach dem Verbindungsaufbau fehl (STARTTLS, Login), wird die
    Verbindung geschlossen, bevor die Exception weiterfliegt — sonst bliebe
    ein offener Socket zurück.

    TLS läuft immer über `ssl.create_default_context()`, also mit voller
    Zertifikatsprüfung. Es gibt bewusst keinen Schalter dagegen: eine solche
    Option wird angeklickt, um ein Problem loszuwerden, und bleibt dann an.
    """
    host = record["host"]
    port = int(record["port"])
    security = record.get("security", "starttls")

    server: smtplib.SMTP
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=DEFAULT_TIMEOUT,
                                  context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(host, port, timeout=DEFAULT_TIMEOUT)

    try:
        if security == "starttls":
            server.starttls(context=ssl.create_default_context())
        username = (record.get("username") or "").strip()
        if username:
            server.login(username, password)
    except BaseException:
        _close(server)
        raise
    return server


def _close(server: smtplib.SMTP) -> None:
    """Verbindung schließen, ohne den ursprünglichen Fehler zu überdecken."""
    try:
        server.quit()
    except Exception:
        log.debug("SMTP-Verbindung ließ sich nicht sauber schließen",
                  exc_info=True)


def send(record: dict[str, Any], password: str, *, subject: str, html: str,
         attachment_bytes: bytes | None = None,
         attachment_filename: str | None = None,
         attachment_subtype: str = "pdf") -> None:
    """Verschickt die Nachricht an `record["recipient"]`.

    Wirft bei Fehlern — der Aufrufer klassifiziert über `classify_smtp_error`.
    Blockierend: gehört in einen Worker-Thread.
    """
    message = build_message(
        to=record["recipient"], subject=subject, html_body=html,
        attachment_bytes=attachment_bytes,
        attachment_filename=attachment_filename,
        attachment_subtype=attachment_subtype,
        from_addr=record["from_addr"],
    )
    server = _open(record, password)
    try:
        server.send_message(message)
    finally:
        _close(server)


def test_connection(record: dict[str, Any], password: str) -> None:
    """Verbindet, meldet sich an, schickt `NOOP` — und KEINE Mail.

    Für den „Verbindung testen"-Button. Wirft wie `send`.
    """
    server = _open(record, password)
    try:
        server.noop()
    finally:
        _close(server)


def _response_detail(exc: BaseException) -> str:
    """Die Serverantwort als lesbarer Text — der Nutzer soll sehen, was
    gesagt wurde, nicht nur dass etwas schiefging."""
    code = getattr(exc, "smtp_code", None)
    raw = getattr(exc, "smtp_error", None)
    if code is None and raw is None:
        return str(exc)
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw or "")
    return f"{code} {text}".strip()


def classify_smtp_error(exc: BaseException) -> dict[str, Any]:
    """Mappt eine Versand-Exception auf ein Result-Dict.

    Die Reihenfolge ist Absicht: `SMTPAuthenticationError` und
    `SMTPSenderRefused` sind Unterklassen von `SMTPResponseException`, und
    `SMTPRecipientsRefused` von `SMTPException` — das Speziellere muss zuerst
    geprüft werden.

    Muss aus einem aktiven `except`-Block gerufen werden: der `error`-Fall
    liest den aktuellen Traceback über `traceback.format_exc()`.
    """
    def result(kind: str, detail: str, tb: str | None = None) -> dict[str, Any]:
        return {"ok": False, "kind": kind, "detail": detail,
                "error": exc, "tb": tb}

    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return result("auth", _response_detail(exc))
    if isinstance(exc, (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused)):
        return result("recipient", _response_detail(exc))
    if isinstance(exc, (ssl.SSLError, smtplib.SMTPNotSupportedError)):
        return result("tls", str(exc))
    if is_offline_error(exc):
        return result("offline", "")
    if isinstance(exc, smtplib.SMTPException):
        return result("server", _response_detail(exc))
    return result("error", str(exc), traceback.format_exc())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_smtp.py -v`
Expected: PASS

- [ ] **Step 5: Modul in die Annotations-Whitelist eintragen**

In `tests/test_type_annotations.py`, in `ANNOTATED_MODULES` direkt nach `"src/webhook.py"`:

```python
    "src/smtp.py",
```

- [ ] **Step 6: Lint, Typecheck, volle Suite**

Run: `ruff check .`
Run: `npx pyright`
Run: `pytest`
Expected: alles grün.

- [ ] **Step 7: Commit**

```bash
git add src/smtp.py tests/test_smtp.py tests/test_type_annotations.py
git commit -F <commit-message-datei>
```

Commit-Message:

```
feat(smtp): Versand und Verbindungstest

STARTTLS / implizites TLS / unverschluesselt, Login nur bei gesetztem
Benutzer, fester Timeout. Zertifikatspruefung immer an — bewusst ohne
Schalter dagegen.

Eigener Fehlerklassifikator (auth/recipient/tls/offline/server): mit den
drei Kinds aus mail_task kaeme jede Serverantwort als unerwarteter
Fehler mit Traceback beim Nutzer an.
```

---

### Task 5: SMTP als dritter Kanaltyp im Dispatcher

**Files:**
- Modify: `src/dialogs/send_task.py` (`perform_send`, `_KIND_TEXTS`)
- Test: `tests/test_send_task_dispatch.py`

**Interfaces:**
- Consumes: `smtp.send`, `smtp.classify_smtp_error` (Task 4), `keyring_store.get_secret` (Task 2)
- Produces: `perform_send(..., smtp_accounts: list[dict] | None = None, ...)` — liefert je Konto ein Result `{"channel": "smtp", "name": <Kontoname>, "ok": bool, ...}` in `res["results"]`.

- [ ] **Step 1: Write the failing test**

An `tests/test_send_task_dispatch.py` anhängen (die vorhandenen Helfer der Datei zuerst lesen und wiederverwenden; `st` ist dort das importierte Modul `src.dialogs.send_task`):

```python
def _smtp_account(**overrides):
    base = {
        "id": "rec-1", "name": "Firma", "enabled": True,
        "host": "mail.example.com", "port": 587, "security": "starttls",
        "username": "user@example.com", "from_addr": "user@example.com",
        "recipient": "buchhaltung@example.com",
        "password_location": "keyring",
    }
    base.update(overrides)
    return base


def test_smtp_account_is_sent_with_pdf(monkeypatch, settings):
    sent = []
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"%PDF-1.4")
    monkeypatch.setattr(st.keyring_store, "get_secret", lambda record: "geheim")
    monkeypatch.setattr(st.smtp, "send",
                        lambda record, password, **kw: sent.append((record, password, kw)))

    res = perform_send(
        date_from=DATE_FROM, date_to=DATE_TO, entries=ENTRIES, name="N",
        categories=None, category_breakdown=False,
        send_mail=False, mail=None, webhooks=[],
        smtp_accounts=[_smtp_account()],
        pdf_filename="Bericht.pdf", settings=settings)

    assert [r["ok"] for r in res["results"]] == [True]
    assert res["results"][0]["channel"] == "smtp"
    assert res["results"][0]["name"] == "Firma"
    record, password, kw = sent[0]
    assert password == "geheim"
    assert kw["attachment_bytes"] == b"%PDF-1.4"
    assert kw["attachment_filename"] == "Bericht.pdf"


def test_smtp_failure_does_not_stop_the_other_channels(monkeypatch, settings):
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"%PDF-1.4")
    monkeypatch.setattr(st.keyring_store, "get_secret", lambda record: "geheim")

    def boom(record, password, **kw):
        import smtplib
        raise smtplib.SMTPAuthenticationError(535, b"nope")

    monkeypatch.setattr(st.smtp, "send", boom)
    monkeypatch.setattr(st, "get_gmail_service", lambda *a, **k: "svc")
    monkeypatch.setattr(st, "send_email", lambda *a, **k: "mid")
    monkeypatch.setattr(st, "fetch_user_email", lambda *a, **k: "")

    res = perform_send(
        date_from=DATE_FROM, date_to=DATE_TO, entries=ENTRIES, name="N",
        categories=None, category_breakdown=False,
        send_mail=True,
        mail={"credentials_path": "c", "token_path": "t",
              "recipient": "a@b", "subject": "S", "html": "<p>x</p>",
              "sync_enabled": False, "gcal_enabled": False},
        webhooks=[], smtp_accounts=[_smtp_account()],
        pdf_filename="Bericht.pdf", settings=settings)

    by_channel = {r["channel"]: r for r in res["results"]}
    assert by_channel["mail"]["ok"] is True
    assert by_channel["smtp"]["ok"] is False
    assert by_channel["smtp"]["kind"] == "auth"


def test_pdf_failure_takes_smtp_down_but_json_webhooks_survive(
        monkeypatch, settings):
    """SMTP haengt die PDF an wie der Mail-Kanal — ohne sie kann es nicht
    senden. JSON-Webhooks brauchen sie nicht und laufen weiter."""
    def boom(*a, **k):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(st, "generate_pdf", boom)
    monkeypatch.setattr(st.webhook, "build_json_payload", lambda **k: {"x": 1})
    monkeypatch.setattr(st.webhook, "deliver",
                        lambda *a, **k: {"ok": True, "status": 200})

    res = perform_send(
        date_from=DATE_FROM, date_to=DATE_TO, entries=ENTRIES, name="N",
        categories=None, category_breakdown=False,
        send_mail=False, mail=None,
        webhooks=[{"record": {"name": "Hook"}, "json": True, "pdf": False}],
        smtp_accounts=[_smtp_account()],
        pdf_filename="Bericht.pdf", settings=settings)

    by_channel = {r["channel"]: r for r in res["results"]}
    assert by_channel["smtp"]["ok"] is False
    assert by_channel["webhook"]["ok"] is True


def test_smtp_accounts_default_to_empty(monkeypatch, settings):
    """Bestandsaufrufer ohne den neuen Parameter laufen unveraendert."""
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"%PDF-1.4")
    monkeypatch.setattr(st.webhook, "build_json_payload", lambda **k: {"x": 1})
    monkeypatch.setattr(st.webhook, "deliver",
                        lambda *a, **k: {"ok": True, "status": 200})

    res = perform_send(
        date_from=DATE_FROM, date_to=DATE_TO, entries=ENTRIES, name="N",
        categories=None, category_breakdown=False,
        send_mail=False, mail=None,
        webhooks=[{"record": {"name": "Hook"}, "json": True, "pdf": False}],
        pdf_filename="Bericht.pdf", settings=settings)

    assert [r["channel"] for r in res["results"]] == ["webhook"]


def test_kind_texts_cover_the_new_smtp_kinds():
    """Sonst stuende im Ergebnis-Dialog nur „Fehler"."""
    from src.dialogs.send_task import _KIND_TEXTS
    assert "recipient" in _KIND_TEXTS
    assert "tls" in _KIND_TEXTS
```

**Hinweis für den Implementierenden:** Die Namen `DATE_FROM`, `DATE_TO`, `ENTRIES`, `settings` und `perform_send` stammen aus dem bestehenden Kopf von `tests/test_send_task_dispatch.py`. Vor dem Schreiben die Datei lesen und die dortigen Namen verwenden; weichen sie ab, die Tests entsprechend anpassen statt neue Fixtures anzulegen.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_send_task_dispatch.py -v`
Expected: FAIL — `TypeError: perform_send() got an unexpected keyword argument 'smtp_accounts'`

- [ ] **Step 3: Implementierung in `src/dialogs/send_task.py`**

Importe oben ergänzen:

```python
from src import keyring_store, smtp, webhook
```

(die bestehende Zeile `from src import webhook` ersetzen)

`needs_pdf` erweitern:

```python
def needs_pdf(send_mail, webhooks, smtp_accounts=()):
    """True, wenn irgendein Kanal die PDF braucht.

    Mail und SMTP hängen sie immer an; bei Webhooks entscheidet die
    Format-Wahl.
    """
    return (bool(send_mail) or bool(smtp_accounts)
            or any(w.get("pdf") for w in webhooks))
```

Neue Kanalfunktion, direkt hinter `_send_mail`:

```python
def _send_smtp(*, record, subject, html, pdf_bytes, pdf_filename):
    """Ein SMTP-Konto. Wirft nie — wie jeder Kanal des Dispatchers.

    Das Passwort wird HIER geholt, nicht im Dialog: auf Linux ist der
    Schlüsselbund ein D-Bus-Roundtrip, der im Tk-Callback die Oberfläche
    einfrieren könnte.
    """
    try:
        password = keyring_store.get_secret(record)
        smtp.send(record, password, subject=subject, html=html,
                  attachment_bytes=pdf_bytes,
                  attachment_filename=pdf_filename,
                  attachment_subtype="pdf")
    except Exception as e:
        log.exception("SMTP-Versand über %r fehlgeschlagen", record.get("name"))
        return smtp.classify_smtp_error(e)
    return {"ok": True}
```

In `perform_send` die Signatur um den Parameter erweitern (nach `webhooks`):

```python
def perform_send(*, date_from, date_to, entries, name, categories,
                 category_breakdown, send_mail, mail, webhooks,
                 pdf_filename, settings, vacation_days=None,
                 smtp_accounts=None):
```

Direkt nach der `send_mail`/`mail`-Normalisierung:

```python
    smtp_accounts = list(smtp_accounts or [])
```

Den `needs_pdf`-Aufruf und den PDF-Fehlerzweig anpassen:

```python
    pdf_bytes = None
    if needs_pdf(send_mail, webhooks, smtp_accounts):
        try:
            pdf_bytes = generate_pdf(...)   # unverändert
        except Exception as e:
            ...                             # unveränderter failure-Aufbau
            if send_mail:
                assert mail is not None
                results.append({"channel": "mail",
                                "name": mail["recipient"], **failure})
                send_mail = False
            # SMTP hängt die PDF an wie der Mail-Kanal — ohne sie kann kein
            # Konto senden.
            for record in smtp_accounts:
                results.append({"channel": "smtp",
                                "name": record.get("name", ""), **failure})
            smtp_accounts = []
            for entry in [w for w in webhooks if w.get("pdf")]:
                results.append({"channel": "webhook",
                                "name": entry["record"].get("name", ""),
                                **failure})
            webhooks = [w for w in webhooks if not w.get("pdf")]
```

Nach dem `if send_mail:`-Block den SMTP-Block einfügen:

```python
    for record in smtp_accounts:
        res = _send_smtp(record=record,
                         subject=mail["subject"] if mail else "",
                         html=mail["html"] if mail else "",
                         pdf_bytes=pdf_bytes, pdf_filename=pdf_filename)
        results.append({"channel": "smtp",
                        "name": record.get("name", ""), **res})
```

**Achtung:** Betreff und HTML werden heute nur im Mail-Fall gebaut
(`send_dialog`, Kommentar „(d)"). SMTP braucht beide ebenfalls. Der
Sende-Dialog baut sie deshalb in Task 8 auch dann, wenn nur SMTP angehakt ist,
und reicht sie über `mail=` durch — auch bei `send_mail=False`. Der Parameter
`mail` ist bereits als `dict | None` unabhängig von `send_mail` deklariert;
die vorhandene Normalisierung oben schaltet nur `send_mail` ab, sie leert
`mail` nicht.

`_KIND_TEXTS` erweitern:

```python
_KIND_TEXTS = {
    "filenotfound": "Zugangsdaten fehlen",
    "offline": "keine Internetverbindung",
    "auth": "Zugangsdaten wurden abgelehnt",
    "recipient": "Empfänger oder Absender wurde abgelehnt",
    "tls": "Verschlüsselung fehlgeschlagen",
    "notfound": "Adresse nicht gefunden",
    "redirect": "Weiterleitung — bitte die endgültige Adresse eintragen",
    "client": "Anfrage abgelehnt",
    "server": "Server-Fehler",
    "config": "Konfiguration ungültig",
    "error": "unerwarteter Fehler",
}
```

Den Modul-Docstring anpassen — er sagt heute „Dispatcher über zwei Kanaltypen":

```
Dispatcher über drei Kanaltypen: Gmail, beliebig viele SMTP-Konten und
beliebig viele Webhooks.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_send_task_dispatch.py tests/test_send_task.py -v`
Expected: PASS

- [ ] **Step 5: Lint, Typecheck, volle Suite**

Run: `ruff check .`
Run: `npx pyright`
Run: `pytest`
Expected: alles grün.

- [ ] **Step 6: Commit**

```bash
git add src/dialogs/send_task.py tests/test_send_task_dispatch.py
git commit -F <commit-message-datei>
```

Commit-Message:

```
feat(send): SMTP als dritter Kanaltyp im Dispatcher

perform_send feuert jetzt Gmail, n SMTP-Konten und n Webhooks
unabhaengig voneinander. Die PDF entsteht weiterhin genau einmal;
faellt sie aus, faellt SMTP mit dem Mail-Kanal aus, die JSON-Webhooks
laufen weiter.

Das Passwort holt der Worker, nicht der Dialog: auf Linux ist der
Schluesselbund ein D-Bus-Roundtrip.
```

---

### Task 6: Teilen über SMTP (`share_task`)

**Files:**
- Modify: `src/dialogs/share_task.py`
- Test: `tests/test_share_task.py`

**Interfaces:**
- Consumes: `smtp.send`, `smtp.classify_smtp_error` (Task 4), `keyring_store.get_secret` (Task 2)
- Produces: `perform_share(..., transport: dict | None = None)` — `None` heißt Gmail wie bisher, sonst ein SMTP-Record.

- [ ] **Step 1: Write the failing test**

An `tests/test_share_task.py` anhängen (`st` ist dort `src.dialogs.share_task`):

```python
def _smtp_account(**overrides):
    base = {
        "id": "rec-1", "name": "Firma", "enabled": True,
        "host": "mail.example.com", "port": 587, "security": "starttls",
        "username": "user@example.com", "from_addr": "user@example.com",
        "recipient": "kollege@example.com",
        "password_location": "keyring",
    }
    base.update(overrides)
    return base


def test_share_over_smtp_uses_the_account(monkeypatch, settings):
    sent = []
    monkeypatch.setattr(st.keyring_store, "get_secret", lambda record: "geheim")
    monkeypatch.setattr(st.smtp, "send",
                        lambda record, password, **kw: sent.append((record, kw)))
    monkeypatch.setattr(st, "get_gmail_service", _must_not_be_called)

    res = perform_share(
        payload=b'{"x":1}', filename="share.json",
        credentials_path="c", token_path="t",
        recipient="kollege@example.com", subject="S", html="<p>x</p>",
        sync_enabled=False, gcal_enabled=False, save_default=False,
        settings=settings, transport=_smtp_account())

    assert res["ok"] is True
    record, kw = sent[0]
    assert record["name"] == "Firma"
    assert kw["attachment_subtype"] == "json"
    assert kw["attachment_filename"] == "share.json"


def test_share_over_smtp_classifies_errors(monkeypatch, settings):
    import smtplib

    monkeypatch.setattr(st.keyring_store, "get_secret", lambda record: "geheim")

    def boom(record, password, **kw):
        raise smtplib.SMTPAuthenticationError(535, b"nope")

    monkeypatch.setattr(st.smtp, "send", boom)

    res = perform_share(
        payload=b'{"x":1}', filename="share.json",
        credentials_path="c", token_path="t",
        recipient="kollege@example.com", subject="S", html="<p>x</p>",
        sync_enabled=False, gcal_enabled=False, save_default=False,
        settings=settings, transport=_smtp_account())

    assert res["ok"] is False
    assert res["kind"] == "auth"


def test_share_without_transport_still_uses_gmail(monkeypatch, settings):
    """Bestandsverhalten: transport=None ist der Gmail-Weg."""
    monkeypatch.setattr(st, "get_gmail_service", lambda *a, **k: "svc")
    calls = []
    monkeypatch.setattr(st, "send_email", lambda *a, **k: calls.append(a))

    res = perform_share(
        payload=b'{"x":1}', filename="share.json",
        credentials_path="c", token_path="t",
        recipient="kollege@example.com", subject="S", html="<p>x</p>",
        sync_enabled=False, gcal_enabled=False, save_default=False,
        settings=settings)

    assert res["ok"] is True
    assert calls
```

Dazu oben in der Datei den kleinen Helfer ergänzen:

```python
def _must_not_be_called(*args, **kwargs):
    raise AssertionError("Der Gmail-Pfad darf beim SMTP-Versand nicht laufen.")
```

**Hinweis:** `settings` und `perform_share` stammen aus dem bestehenden Kopf von `tests/test_share_task.py`; vor dem Schreiben die Datei lesen und die dortigen Namen verwenden.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_share_task.py -v`
Expected: FAIL — `TypeError: perform_share() got an unexpected keyword argument 'transport'`

- [ ] **Step 3: Implementierung in `src/dialogs/share_task.py`**

Vollständige neue Fassung:

```python
"""Worker-Kern des Teilen-Dialogs (Audit M10): Tk-frei, wirft nie.

Der Share-Doc-Bau + die Serialisierung laufen auf dem UI-Thread (schnell,
Klick-Zeit-Snapshot); dieser Worker bekommt den fertigen `payload` und
erledigt nur den blockierenden Teil: Transport aufbauen (evtl. OAuth oder
Schlüsselbund-Zugriff) + senden + optional Standard-Empfänger persistieren.

`transport=None` ist der Gmail-Weg; ein SMTP-Record schickt stattdessen über
dieses Konto.
"""

import logging

from src import keyring_store, smtp
from src.dialogs.mail_task import classify_mail_error
from src.mail import get_gmail_service, send_email

log = logging.getLogger(__name__)


def perform_share(*, payload, filename, credentials_path, token_path,
                  recipient, subject, html, sync_enabled, gcal_enabled,
                  save_default, settings, transport=None):
    if transport is None:
        result = _share_via_gmail(
            payload=payload, filename=filename,
            credentials_path=credentials_path, token_path=token_path,
            recipient=recipient, subject=subject, html=html,
            sync_enabled=sync_enabled, gcal_enabled=gcal_enabled)
    else:
        result = _share_via_smtp(
            record=transport, payload=payload, filename=filename,
            subject=subject, html=html)

    if not result["ok"]:
        return result
    if save_default:
        settings.set("share_recipient", recipient)
    return result


def _share_via_gmail(*, payload, filename, credentials_path, token_path,
                     recipient, subject, html, sync_enabled, gcal_enabled):
    try:
        service = get_gmail_service(
            credentials_path, token_path,
            sync_enabled=sync_enabled, gcal_enabled=gcal_enabled)
        send_email(service, recipient, subject, html,
                   attachment_bytes=payload,
                   attachment_filename=filename,
                   attachment_subtype="json")
    except FileNotFoundError as e:
        return classify_mail_error(e)
    except Exception as e:
        log.exception("Teilen fehlgeschlagen")
        return classify_mail_error(e)
    return {"ok": True}


def _share_via_smtp(*, record, payload, filename, subject, html):
    """Der Empfänger steht im Konto — deshalb zeigt der Teilen-Dialog ihn an,
    sobald ein SMTP-Konto gewählt ist, statt das Empfängerfeld zu benutzen."""
    try:
        password = keyring_store.get_secret(record)
        smtp.send(record, password, subject=subject, html=html,
                  attachment_bytes=payload,
                  attachment_filename=filename,
                  attachment_subtype="json")
    except Exception as e:
        log.exception("Teilen über SMTP-Konto %r fehlgeschlagen",
                      record.get("name"))
        return smtp.classify_smtp_error(e)
    return {"ok": True}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_share_task.py -v`
Expected: PASS

- [ ] **Step 5: Lint, Typecheck, volle Suite**

Run: `ruff check .`
Run: `npx pyright`
Run: `pytest`
Expected: alles grün.

- [ ] **Step 6: Commit**

```bash
git add src/dialogs/share_task.py tests/test_share_task.py
git commit -F <commit-message-datei>
```

Commit-Message:

```
feat(share): Teilen ueber ein SMTP-Konto

perform_share bekommt einen transport-Parameter: None ist der Gmail-Weg
wie bisher, ein SMTP-Record schickt ueber dieses Konto. Der
Share-Doc-Bau bleibt unangetastet.
```

---

### Task 7: Einstellungen — Tab „SMTP" und Konto-Dialog

Reine Tk-Schicht, daher ohne automatisierte Tests (Scope-Grenze M16). Verifiziert wird von Hand, s. Step 6.

**Files:**
- Create: `src/dialogs/smtp_dialog.py`
- Create: `src/dialogs/settings_dialog/tab_smtp.py`
- Modify: `src/dialogs/settings_dialog/dialog.py`

**Interfaces:**
- Consumes: `smtp_store.SmtpStore` / `validate_record` / `new_id` / `SmtpStoreReadOnly` / `SECURITY_MODES` (Task 3), `smtp.test_connection` / `classify_smtp_error` (Task 4), `keyring_store.set_secret` / `get_secret` (Task 2), `send_task.format_result_summary` (Bestand)
- Produces:
  ```python
  open_smtp_dialog(parent, store, runner, record: dict | None = None,
                   on_saved=None) -> None
  class SmtpTab:
      def __init__(self, frame, dialog, store, runner, parent=None) -> None: ...
      def refresh(self) -> None: ...
  ```

- [ ] **Step 1: Konto-Dialog anlegen**

Neue Datei `src/dialogs/smtp_dialog.py`. Vorbild ist `src/dialogs/webhook_dialog.py` — vor dem Schreiben lesen und dessen Struktur (busy-Flags, Runner-Nutzung, `on_done`-Behandlung bei geschlossenem Dialog) übernehmen:

```python
"""Anlegen und Bearbeiten eines SMTP-Kontos, inklusive Verbindungstest.

Reine Tk-Schicht: Validierung (smtp_store.validate_record), Versand und
Verbindungstest (smtp.test_connection) liegen Tk-frei in den pure Modulen und
sind dort getestet.
"""

import tkinter as tk
from typing import Any

from src import keyring_store, smtp, smtp_store
from src.theme import (
    BG, CELL_BG, FONT, FONT_SMALL, TEXT, TEXT_MUTED,
    apply_combobox_style, attach_unfocus_on_click, center_dialog_on_parent,
    create_dialog, dark_combo, dark_entry, primary_button, secondary_button,
    set_primary_button_enabled, set_secondary_button_enabled,
    themed_showerror, themed_showinfo,
)

SECURITY_LABELS = [
    ("starttls", "STARTTLS (üblich, Port 587)"),
    ("ssl", "SSL/TLS (Port 465)"),
    ("none", "Keine Verschlüsselung"),
]

# Warum das hier steht und nicht in der Doku versteckt: ohne diesen Hinweis
# liest sich das „535 Authentication unsuccessful" von Microsoft wie ein
# Tippfehler, und der Nutzer sucht stundenlang am falschen Ende.
PROVIDER_HINT = (
    "Microsoft-Konten (Outlook.com, Microsoft 365) lassen sich hier nicht "
    "einrichten — Microsoft hat SMTP mit Passwort 2026 abgeschaltet.\n"
    "Für Gmail wird ein App-Passwort benötigt (nicht das Kontopasswort); "
    "es setzt eine aktive Zwei-Faktor-Anmeldung voraus."
)

STORAGE_HINT = (
    "Das Passwort wird im Schlüsselbund des Betriebssystems abgelegt. Steht "
    "keiner zur Verfügung, wird es lokal in smtp.json gespeichert."
)


def _mode_for_label(label):
    return next((m for m, lbl in SECURITY_LABELS if lbl == label), "starttls")


def _label_for_mode(mode):
    return next((lbl for m, lbl in SECURITY_LABELS if m == mode),
                SECURITY_LABELS[0][1])


def open_smtp_dialog(parent, store, runner, record: dict | None = None,
                     on_saved=None):
    is_new = record is None
    record = dict(record or {
        "id": smtp_store.new_id(), "name": "", "enabled": True,
        "host": "", "port": 587, "security": "starttls", "username": "",
        "from_addr": "", "recipient": "", "password_location": "keyring",
    })

    dialog = create_dialog(
        parent, "SMTP-Konto hinzufügen" if is_new else "SMTP-Konto bearbeiten")
    apply_combobox_style(dialog)
    attach_unfocus_on_click(dialog)

    name_var = tk.StringVar(value=record.get("name", ""))
    host_var = tk.StringVar(value=record.get("host", ""))
    port_var = tk.StringVar(value=str(record.get("port", 587)))
    security_var = tk.StringVar(
        value=_label_for_mode(record.get("security", "starttls")))
    username_var = tk.StringVar(value=record.get("username", ""))
    # Bewusst LEER, auch beim Bearbeiten: ein gespeichertes Secret wird nie
    # zurück in ein Widget geholt. Leer heißt „unverändert".
    password_var = tk.StringVar(value="")
    from_var = tk.StringVar(value=record.get("from_addr", ""))
    recipient_var = tk.StringVar(value=record.get("recipient", ""))
    enabled_var = tk.BooleanVar(value=bool(record.get("enabled", True)))
    busy = {"testing": False, "saving": False}

    def _label(text, row, **kw):
        opts: dict[str, Any] = dict(padx=10, pady=6, sticky="w")
        opts.update(kw)
        tk.Label(dialog, text=text, font=FONT, bg=BG, fg=TEXT).grid(
            row=row, column=0, **opts)

    rows = [
        ("Name:", name_var, False),
        ("Server:", host_var, False),
        ("Port:", port_var, False),
    ]
    for i, (text, var, masked) in enumerate(rows):
        _label(text, i, pady=(14, 6) if i == 0 else 6)
        entry = dark_entry(dialog, var, width=32)
        if masked:
            entry.config(show="•")
        entry.grid(row=i, column=1, padx=10,
                   pady=(14, 6) if i == 0 else 6, sticky="w")

    _label("Verschlüsselung:", 3)
    dark_combo(dialog, security_var,
               [lbl for _, lbl in SECURITY_LABELS], width=32).grid(
        row=3, column=1, padx=10, pady=6, sticky="w")

    more = [
        ("Benutzer:", username_var, False),
        ("Passwort:", password_var, True),
        ("Absender:", from_var, False),
        ("Empfänger:", recipient_var, False),
    ]
    for offset, (text, var, masked) in enumerate(more):
        row = 4 + offset
        _label(text, row)
        entry = dark_entry(dialog, var, width=32)
        if masked:
            entry.config(show="•")
        entry.grid(row=row, column=1, padx=10, pady=6, sticky="w")

    if not is_new:
        location = record.get("password_location")
        stored_text = ("Passwort liegt im Schlüsselbund des Betriebssystems."
                       if location == "keyring" else
                       "Kein Schlüsselbund verfügbar — das Passwort liegt "
                       "lokal in smtp.json.")
        tk.Label(dialog, text=f"{stored_text}  Leer lassen = unverändert.",
                 font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, justify="left",
                 wraplength=380).grid(row=8, column=0, columnspan=2,
                                      padx=10, pady=(0, 4), sticky="w")

    tk.Checkbutton(
        dialog, text="Aktiv", variable=enabled_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG, activebackground=BG,
        activeforeground=TEXT, cursor="hand2",
    ).grid(row=9, column=0, columnspan=2, padx=10, pady=(4, 2), sticky="w")

    # wraplength ist Pflicht, nicht Kosmetik: ohne sie wird das Label so breit
    # wie seine längste Zeile und zieht den ganzen Dialog mit. 380 ist der im
    # Projekt übliche Wert.
    tk.Label(dialog, text=STORAGE_HINT, font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
             justify="left", wraplength=380).grid(
        row=10, column=0, columnspan=2, padx=10, pady=(6, 2), sticky="w")
    tk.Label(dialog, text=PROVIDER_HINT, font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
             justify="left", wraplength=380).grid(
        row=11, column=0, columnspan=2, padx=10, pady=(0, 6), sticky="w")

    def _collect():
        try:
            port = int(port_var.get().strip())
        except ValueError:
            # validate_record weist das mit einer Meldung ab; -1 ist nur der
            # Transportwert dorthin.
            port = -1
        return {
            "id": record["id"],
            "name": name_var.get().strip(),
            "enabled": bool(enabled_var.get()),
            "host": host_var.get().strip(),
            "port": port,
            "security": _mode_for_label(security_var.get()),
            "username": username_var.get().strip(),
            "from_addr": from_var.get().strip(),
            "recipient": recipient_var.get().strip(),
            "password_location": record.get("password_location", "keyring"),
        }

    def _validated():
        candidate = _collect()
        ok, msg = smtp_store.validate_record(candidate, store.get_all())
        if not ok:
            themed_showerror(dialog, "Eingabe unvollständig", msg)
            return None
        # Beim Neuanlegen ist ein Passwort Pflicht, sobald ein Benutzer
        # gesetzt ist — validate_record kann das nicht prüfen, dort steht das
        # Passwort gar nicht drin.
        if is_new and candidate["username"] and not password_var.get():
            themed_showerror(dialog, "Eingabe unvollständig",
                             "Bitte ein Passwort angeben.")
            return None
        return candidate

    def do_save():
        if busy["saving"]:
            return
        candidate = _validated()
        if candidate is None:
            return
        password = password_var.get()
        busy["saving"] = True
        set_primary_button_enabled(save_btn, False)

        # Über den Runner, NICHT direkt: store.save startet einen
        # icacls-Subprozess (timeout=15), und der Schlüsselbund ist auf Linux
        # ein D-Bus-Roundtrip. Im Tk-Callback fröre beides die Oberfläche ein.
        def fn():
            to_save = dict(candidate)
            if password:
                location = keyring_store.set_secret(to_save["id"], password)
                to_save["password_location"] = location
                if location == "file":
                    to_save["password"] = password
                else:
                    to_save.pop("password", None)
            elif to_save.get("password_location") == "file":
                # Unverändert im Datei-Fallback: das bereits gespeicherte
                # Passwort muss erhalten bleiben, sonst löscht ein Speichern
                # ohne Passworteingabe es weg.
                to_save["password"] = keyring_store.get_secret(record)
            try:
                store.save(to_save)
            except (smtp_store.SmtpStoreReadOnly, OSError) as e:
                return {"ok": False, "error": e}
            return {"ok": True, "location": to_save.get("password_location")}

        def on_done(res):
            alive = dialog.winfo_exists()
            if res["ok"]:
                if alive:
                    dialog.destroy()
                if on_saved:
                    on_saved()
                if res.get("location") == "file":
                    themed_showinfo(
                        parent, "Passwort lokal gespeichert",
                        "Auf diesem System steht kein Schlüsselbund zur "
                        "Verfügung. Das Passwort wurde deshalb lokal in "
                        "smtp.json gespeichert.")
                return
            if alive:
                busy["saving"] = False
                set_primary_button_enabled(save_btn, True)
            target = dialog if alive else parent
            themed_showerror(
                target, "Nicht gespeichert",
                f"Das SMTP-Konto konnte nicht gespeichert werden:\n\n{res['error']}")

        runner.run(fn, on_done)

    def do_test():
        # Eigenes Flag nötig: set_secondary_button_enabled ändert laut seinem
        # Docstring NUR die Optik, die command-Bindung bleibt aktiv.
        if busy["testing"]:
            return
        candidate = _validated()
        if candidate is None:
            return
        typed_password = password_var.get()
        busy["testing"] = True
        set_secondary_button_enabled(test_btn, False)

        # Getestet werden die AKTUELLEN Feldwerte, nicht der gespeicherte
        # Datensatz — sonst ließe sich eine Korrektur nicht prüfen, ohne sie
        # vorher zu speichern.
        def fn():
            password = typed_password or keyring_store.get_secret(record)
            try:
                smtp.test_connection(candidate, password)
            except Exception as e:
                return smtp.classify_smtp_error(e)
            return {"ok": True}

        def on_done(res):
            busy["testing"] = False
            if not dialog.winfo_exists():
                return
            set_secondary_button_enabled(test_btn, True)
            if res.get("ok"):
                themed_showinfo(
                    dialog, "Verbindung erfolgreich",
                    "Der Server hat die Zugangsdaten akzeptiert. Es wurde "
                    "keine E-Mail verschickt.")
                return
            from src.dialogs.send_task import format_result_summary
            themed_showerror(
                dialog, "Verbindung fehlgeschlagen",
                format_result_summary(
                    [{"name": candidate["name"], "ok": False,
                      "kind": res.get("kind"), "detail": res.get("detail")}]))

        runner.run(fn, on_done)

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=12, column=0, columnspan=2, pady=14)
    save_btn = primary_button(btn_frame, "Speichern", do_save)
    save_btn.pack(side=tk.LEFT, padx=5)
    test_btn = secondary_button(btn_frame, "Verbindung testen", do_test)
    test_btn.pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(
        side=tk.LEFT, padx=5)

    # Kein eigener <Escape>-Bind: create_dialog setzt ihn bereits.
    center_dialog_on_parent(dialog, parent)
```

- [ ] **Step 2: Tab anlegen**

Neue Datei `src/dialogs/settings_dialog/tab_smtp.py` — Vorbild `tab_webhooks.py`:

```python
"""Tab „SMTP": Liste der konfigurierten Mail-Konten.

Wie der Webhooks-Tab exponiert dieser KEINE Variablen für save_settings —
SMTP-Konten liegen in ihrem eigenen, gerätelokalen Store und werden vom
Unterdialog direkt gespeichert.
"""

import tkinter as tk

from src import smtp_store
from src.dialogs.smtp_dialog import open_smtp_dialog
from src.theme import (
    ACCENT, BG, ENTRY_BG, FONT, FONT_SMALL, TEXT, TEXT_MUTED,
    primary_button, secondary_button, themed_askyesno, themed_showerror,
)


class SmtpTab:
    def __init__(self, frame, dialog, store, runner, parent=None):
        self.frame = frame
        self._dialog = dialog
        self._parent = parent if parent is not None else dialog
        self._store = store
        self._runner = runner

        frame.columnconfigure(0, weight=1)

        # wraplength=380 wie im Webhooks-Tab: ohne sie wird das Label so breit
        # wie seine längste Zeile und zieht den ganzen Einstellungen-Dialog mit.
        tk.Label(
            frame,
            text=("Berichte können statt über die Gmail-API auch über einen "
                  "eigenen Mail-Server verschickt werden. Jedes Konto hat "
                  "seinen eigenen Empfänger und lässt sich beim Senden "
                  "einzeln auswählen. Konten gelten nur auf diesem Gerät und "
                  "werden sofort gespeichert — unabhängig vom „Abbrechen“ "
                  "dieses Einstellungen-Dialogs."),
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, justify="left",
            wraplength=380,
        ).grid(row=0, column=0, padx=10, pady=(10, 6), sticky="w")

        self._listbox = tk.Listbox(
            frame, height=8, width=30, font=FONT,
            bg=ENTRY_BG, fg=TEXT, selectbackground=ACCENT,
            selectforeground="#ffffff", relief="flat",
            highlightthickness=0, activestyle="none",
        )
        self._listbox.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="we")
        self._listbox.bind("<Double-Button-1>", lambda _e: self._edit())

        btns = tk.Frame(frame, bg=BG)
        btns.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="w")
        primary_button(btns, "Hinzufügen", self._add).pack(side=tk.LEFT, padx=(0, 6))
        secondary_button(btns, "Bearbeiten", self._edit).pack(side=tk.LEFT, padx=6)
        secondary_button(btns, "Entfernen", self._remove).pack(side=tk.LEFT, padx=6)

        self._records = []
        self.refresh()

    def refresh(self):
        self._records = self._store.get_all() if self._store else []
        self._listbox.delete(0, tk.END)
        for record in self._records:
            mark = "✓" if record.get("enabled") else "○"
            host = record.get("host", "?")
            self._listbox.insert(
                tk.END, f"  {mark}  {record.get('name', '')}  —  {host}")

    def _selected(self):
        selection = self._listbox.curselection()
        return self._records[selection[0]] if selection else None

    def _add(self):
        if not self._store:
            return
        open_smtp_dialog(self._dialog, self._store, self._runner,
                         on_saved=self.refresh)

    def _edit(self):
        record = self._selected()
        if record is None:
            return
        open_smtp_dialog(self._dialog, self._store, self._runner,
                         record=record, on_saved=self.refresh)

    def _remove(self):
        record = self._selected()
        if record is None:
            return
        if not themed_askyesno(
                self._dialog, "SMTP-Konto entfernen",
                f"„{record.get('name', '')}“ wirklich entfernen?"):
            return

        # Über den Runner: delete schreibt die Datei neu (icacls-Subprozess,
        # bis zu 15 s) und räumt das Secret im Schlüsselbund ab.
        def fn():
            try:
                self._store.delete(record["id"])
            except (smtp_store.SmtpStoreReadOnly, OSError) as e:
                return {"ok": False, "error": e}
            return {"ok": True}

        def on_done(res):
            alive = self._dialog.winfo_exists()
            if not res["ok"]:
                target = self._dialog if alive else self._parent
                themed_showerror(
                    target, "Nicht entfernt",
                    "Das SMTP-Konto konnte nicht entfernt werden:\n\n"
                    f"{res['error']}")
            if alive:
                self.refresh()

        self._runner.run(fn, on_done)
```

- [ ] **Step 3: Tab in den Einstellungen-Dialog einhängen**

In `src/dialogs/settings_dialog/dialog.py`:

Import nach `from src.dialogs.settings_dialog.tab_mail import MailTab`:

```python
from src.dialogs.settings_dialog.tab_smtp import SmtpTab
```

`open_settings_dialog` bekommt einen neuen Keyword-Parameter `smtp_store=None` (neben `webhook_store`).

Nach `tab_mail = tk.Frame(notebook, bg=BG)`:

```python
    tab_smtp = tk.Frame(notebook, bg=BG)
```

Nach `notebook.add(tab_mail, text="Bericht & Mail")`:

```python
    notebook.add(tab_smtp, text="SMTP")
```

Nach `hooks = WebhooksTab(...)`:

```python
    smtp_tab = SmtpTab(tab_smtp, dialog, smtp_store, runner, parent)
```

`smtp_tab` wird nicht weiter gebraucht (der Tab speichert selbst) — die Zuweisung dient nur der Lesbarkeit und der Symmetrie zu `hooks`. Ist `ruff` mit der ungenutzten Variablen unzufrieden, den Aufruf ohne Zuweisung schreiben.

- [ ] **Step 4: Lint, Typecheck, volle Suite**

Run: `ruff check .`
Run: `npx pyright`
Run: `pytest`
Expected: alles grün. Die Tests importieren `src.ui`; ein Importfehler in den neuen Modulen fiele hier auf.

- [ ] **Step 5: App starten und den Tab von Hand prüfen**

Run: `python -m src.main`

Prüfen: ⚙ → Tab „SMTP" ist da → „Hinzufügen" öffnet den Dialog → Speichern ohne Namen zeigt „Bitte einen Namen angeben." → ein vollständiges Konto lässt sich speichern und erscheint in der Liste → „Bearbeiten" zeigt das Passwortfeld leer mit dem Hinweis, wo das Passwort liegt → „Entfernen" fragt nach.

- [ ] **Step 6: Verbindungstest gegen einen echten Server**

Ein echtes Konto eintragen (GMX, Web.de, IONOS oder Gmail mit App-Passwort) und „Verbindung testen" drücken. Erwartet: „Der Server hat die Zugangsdaten akzeptiert. Es wurde keine E-Mail verschickt."

Gegenprobe mit falschem Passwort: „Zugangsdaten wurden abgelehnt" plus die Serverantwort — **kein** Traceback-Dialog.

- [ ] **Step 7: Commit**

```bash
git add src/dialogs/smtp_dialog.py src/dialogs/settings_dialog/tab_smtp.py src/dialogs/settings_dialog/dialog.py
git commit -F <commit-message-datei>
```

Commit-Message:

```
feat(settings): Tab „SMTP" mit Konto-Dialog und Verbindungstest

Liste plus Bearbeiten-Dialog nach dem Vorbild der Webhooks. Passwortfeld
bleibt beim Bearbeiten leer (leer = unveraendert), ein gespeichertes
Secret wird nie in ein Widget zurueckgeholt.

Der Dialog sagt offen, dass Microsoft-Konten nicht gehen und Gmail ein
App-Passwort braucht — sonst liest sich das 535 wie ein Tippfehler.
```

---

### Task 8: Sende-Dialog, Teilen-Dialog und Verdrahtung

Reine Tk-Schicht; verifiziert wird von Hand (Step 6–8).

**Files:**
- Modify: `src/main.py`
- Modify: `src/ui.py`
- Modify: `src/dialogs/send_dialog.py`
- Modify: `src/dialogs/share_dialog.py`

**Interfaces:**
- Consumes: `SmtpStore` (Task 3), `perform_send(..., smtp_accounts=...)` (Task 5), `perform_share(..., transport=...)` (Task 6), `open_settings_dialog(..., smtp_store=...)` (Task 7)
- Produces: nichts für Folgetasks.

- [ ] **Step 1: Store in `main.py` anlegen und durchreichen**

Import nach `from src.webhook_store import WebhookStore`:

```python
from src.smtp_store import SmtpStore
```

Direkt nach der Zeile `webhook_store = WebhookStore(os.path.join(base, "webhooks.json"))`:

```python
    # Kein geteilter Daten-Lock, aus denselben Gründen wie beim webhook_store:
    # SMTP-Konten nehmen an keinem Sync-Flow teil, und save/delete halten den
    # Lock über den icacls-Subprozess.
    smtp_store = SmtpStore(os.path.join(base, "smtp.json"))
```

Im `App(...)`-Aufruf ergänzen:

```python
              webhook_store=webhook_store, smtp_store=smtp_store,
```

- [ ] **Step 2: `ui.py` durchreichen**

In `App.__init__` den Parameter neben `webhook_store=None` ergänzen:

```python
                 webhook_store=None, smtp_store=None,
```

und im Rumpf:

```python
        self._smtp_store = smtp_store
```

Im `open_settings_dialog(...)`-Aufruf (bei `webhook_store=self._webhook_store,`) ergänzen:

```python
            smtp_store=self._smtp_store,
```

In `App._send` ergänzen:

```python
                         smtp_store=self._smtp_store,
```

In `App._share` ergänzen:

```python
            smtp_store=self._smtp_store,
```

- [ ] **Step 3: Sende-Dialog — Ziele und Gating**

In `src/dialogs/send_dialog.py`, `open_send_dialog`: Signatur um `smtp_store=None` erweitern.

Den Gating-Block ersetzen (aktuell Zeilen 147–158):

```python
    hooks = webhook_store.enabled() if webhook_store else []
    accounts = smtp_store.enabled() if smtp_store else []
    recipient = settings.get("recipient")
    have_credentials = os.path.exists(credentials_path)
    mail_possible = bool(recipient) and have_credentials

    # Ohne jedes mögliche Ziel: erklären und abbrechen. Der Text muss BEIDE
    # Mailwege nennen — sonst schickt er jemanden ins Google-Cloud-Setup, der
    # es gar nicht braucht.
    if not mail_possible and not accounts and not hooks:
        if not recipient:
            themed_showinfo(
                parent, "Kein Empfänger",
                "Bitte zuerst einen Empfänger in den Einstellungen angeben "
                "oder unter „SMTP“ ein Mail-Konto einrichten.")
        else:
            show_missing_credentials_dialog(parent, base_path)
        return
```

Die Zielliste: die Bedingung `if hooks:` wird zu `if hooks or accounts:`, und zwischen Mail-Zeile und Webhook-Zeilen kommen die Konten. `_update_send_button` muss sie mitzählen. Konkret:

```python
    mail_var = tk.BooleanVar(value=mail_possible)
    smtp_vars = []
    hook_vars = []

    def _update_send_button():
        """Kein Ziel angehakt → Senden ist nicht anwählbar."""
        any_target = (bool(mail_var.get())
                      or any(v.get() for _r, v in smtp_vars)
                      or any(v.get() for _r, v, _f in hook_vars))
        set_primary_button_enabled(send_btn, any_target)

    if hooks or accounts:
        targets = tk.LabelFrame(dialog, text="Ziele", font=FONT, bg=BG, fg=TEXT_MUTED)
        targets.grid(row=1, column=0, padx=10, pady=(4, 0), sticky="we")

        mail_cb = tk.Checkbutton(
            targets, text=mail_label,
            variable=mail_var, font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
            command=_update_send_button)
        mail_cb.grid(row=0, column=0, sticky="w", padx=6, pady=2)
        if not mail_possible:
            mail_var.set(False)
            mail_cb.config(state="disabled")

        row = 1
        for record in accounts:
            # Vorbelegt: angehakt, wenn es KEINEN Gmail-Weg gibt — dann ist
            # SMTP der Standardweg und nicht die Ausnahme.
            var = tk.BooleanVar(value=not mail_possible)
            tk.Checkbutton(
                targets,
                text=f"{record.get('name', '')} → {record.get('recipient', '')}",
                variable=var, font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT, cursor="hand2",
                command=_update_send_button,
            ).grid(row=row, column=0, sticky="w", padx=6, pady=2)
            smtp_vars.append((record, var))
            row += 1

        for record in hooks:
            ...  # unveränderter Webhook-Block, aber mit `row` statt dem
                 # bisherigen enumerate-Index; am Ende jeweils `row += 1`
```

In `do_send`, im Block „(a) Ziele einsammeln":

```python
        selected_accounts = [r for r, v in smtp_vars if v.get()]
        send_mail = bool(mail_var.get())
        if not send_mail and not selected_accounts and not selected_hooks:
            return  # Button ist in diesem Zustand deaktiviert; defensiv.
```

Block „(d)": Mail-HTML und Betreff werden gebraucht, sobald **Mail oder SMTP** beteiligt ist:

```python
        # Mail-HTML und Betreff für die Mail-Kanäle — Gmail wie SMTP. Beim
        # reinen Webhook-Versand bleiben sie None: `total` kommt nur aus
        # generate_report, unbedingt zu berechnen ergäbe dort einen NameError.
        html = subject = None
        if send_mail or selected_accounts:
            html, total = generate_report(...)   # unverändert
            ...
            subject = (...)                      # unverändert
```

Im `fn()`-Aufruf von `perform_send`: das `mail`-Dict wird gebaut, sobald Betreff und HTML existieren — der Dispatcher liest daraus auch für den SMTP-Kanal:

```python
                send_mail=send_mail,
                mail={
                    "credentials_path": credentials_path,
                    "token_path": token_path,
                    "recipient": recipient, "subject": subject, "html": html,
                    "sync_enabled": settings.get("sync_enabled"),
                    "gcal_enabled": settings.get("gcal_enabled"),
                } if (send_mail or selected_accounts) else None,
                smtp_accounts=selected_accounts,
                webhooks=selected_hooks,
```

Zuletzt die Zeile `btn_frame.grid(row=2 if hooks else 1, column=0, pady=12)` zu `row=2 if (hooks or accounts) else 1` und `if hooks: _update_send_button()` zu `if hooks or accounts: _update_send_button()`.

- [ ] **Step 4: Teilen-Dialog — Versandweg wählen**

In `src/dialogs/share_dialog.py`, `open_share_dialog`: Signatur um `smtp_store=None` erweitern.

Über dem Empfängerfeld (Zeile ~204) eine Auswahl einfügen, aber **nur wenn es Konten gibt** — sonst bleibt der Dialog exakt wie bisher:

```python
    accounts = smtp_store.enabled() if smtp_store else []
    transport_labels = ["Gmail"] + [a.get("name", "") for a in accounts]
    transport_var = tk.StringVar(value=transport_labels[0])
    if accounts:
        tk.Label(dialog, text="Versand über:", font=FONT, bg=BG, fg=TEXT).grid(
            row=row, column=0, padx=(20, 8), pady=(0, 4), sticky="w")
        dark_combo(dialog, transport_var, transport_labels, width=24).grid(
            row=row, column=1, padx=(0, 20), pady=(0, 4), sticky="w")
        row += 1
```

Vor dem `perform_share`-Aufruf den gewählten Transport auflösen. **Wichtig:** ein SMTP-Konto bringt seinen eigenen Empfänger mit — das Empfängerfeld gilt dann nicht:

```python
        chosen = next(
            (a for a in accounts if a.get("name") == transport_var.get()), None)
        # Das Konto trägt seinen Empfänger selbst; das Eingabefeld gilt nur
        # für den Gmail-Weg.
        effective_recipient = (chosen["recipient"] if chosen
                               else share_recipient)
```

`effective_recipient` ersetzt `share_recipient` im `perform_share`-Aufruf und in der Erfolgsmeldung. `save_default` wird beim SMTP-Weg auf `False` gesetzt — der gespeicherte Standard-Empfänger gehört zum Eingabefeld, nicht zum Konto:

```python
            return perform_share(
                ...,
                recipient=effective_recipient, subject=subject, html=html,
                save_default=save_default and chosen is None,
                settings=settings, transport=chosen)
```

Ebenso die Leer-Prüfung des Empfängerfelds (Zeile ~232) überspringen, wenn ein SMTP-Konto gewählt ist. `dark_combo`, `FONT` und `TEXT` ggf. dem Theme-Import der Datei hinzufügen.

- [ ] **Step 5: Lint, Typecheck, volle Suite**

Run: `ruff check .`
Run: `npx pyright`
Run: `pytest`
Expected: alles grün.

- [ ] **Step 6: Sende-Dialog von Hand prüfen**

Run: `python -m src.main`

- Mit `credentials.json` **und** einem SMTP-Konto: „Arbeitszeiten senden" zeigt beide Zeilen, Mail vorbelegt, SMTP nicht.
- `credentials.json` wegbenennen und die App neu starten: der Dialog öffnet trotzdem, die Mail-Zeile ist grau („Zugangsdaten fehlen"), das SMTP-Konto ist **vorbelegt angehakt**, Senden ist anwählbar.
- Ohne Empfänger, ohne Konto, ohne Webhook: der bisherige Erklärdialog, jetzt mit dem Hinweis auf „SMTP".

- [ ] **Step 7: Echten Versand prüfen**

Einen Bericht über das SMTP-Konto senden. Prüfen: Mail kommt an, PDF hängt dran, Umlaute in Betreff und Body sind korrekt, Absender ist der eingetragene.

Dann mit falschem Passwort: die Fehlermeldung nennt „Zugangsdaten wurden abgelehnt" samt Serverantwort — **kein** roher Traceback-Dialog.

- [ ] **Step 8: Teilen prüfen**

Ohne SMTP-Konto: der Teilen-Dialog sieht aus wie vorher (keine Auswahlzeile). Mit Konto: Auswahl „Gmail | ⟨Name⟩", und bei gewähltem Konto geht das Share-JSON an den Empfänger des Kontos.

- [ ] **Step 9: Commit**

```bash
git add src/main.py src/ui.py src/dialogs/send_dialog.py src/dialogs/share_dialog.py
git commit -F <commit-message-datei>
```

Commit-Message:

```
feat(send): SMTP-Konten als Ziele, Gmail wird optional

Der Sende-Dialog verlangt nicht mehr credentials.json, sondern
mindestens ein Ziel. Wer nur SMTP eingerichtet hat, kommt ohne
Google-Cloud-Projekt durch; die Mail-Zeile bleibt sichtbar und
deaktiviert, damit erkennbar ist, warum sie nicht waehlbar ist.

Der Teilen-Dialog bekommt eine Auswahl des Versandwegs — aber nur, wenn
ueberhaupt ein Konto existiert.
```

---

### Task 9: Build, Dokumentation und Projekthinweise

**Files:**
- Modify: `scripts/build.py`
- Modify: `README.md`
- Modify: `docs/known-limitations.md`
- Modify: `CLAUDE.md`
- Modify: `src/CLAUDE.md`

**Interfaces:**
- Consumes: alles Vorherige
- Produces: nichts

- [ ] **Step 1: `keyring` in den Frozen-Build aufnehmen**

In `scripts/build.py`, in der gemeinsamen Argumentliste nach `"--collect-all", "pystray",`:

```python
        # keyring bringt zwar einen eigenen PyInstaller-Hook mit, hat aber
        # historisch Backends im Frozen-Build verloren („No recommended
        # backend was available", jaraco/keyring#399) — die Backends werden
        # über Entry-Points geladen, die ein reiner Import-Scan nicht sieht.
        "--collect-all", "keyring",
```

- [ ] **Step 2: Den vorhandenen Build-Test erweitern**

`tests/test_build.py` hat bereits `test_all_platforms_keep_mandatory_collect_all` mit vier Paketen. `keyring` gehört in dieselbe Liste, nicht in einen zweiten Test — die Datei lädt `scripts/build.py` über seinen Pfad, nicht per Import. Docstring und Tupel ersetzen:

```python
def test_all_platforms_keep_mandatory_collect_all(monkeypatch):
    """Fünf --collect-all müssen auf jeder Plattform gebündelt sein. Drei macht
    CLAUDE.md für PDF/Feiertage zur Pflicht (xhtml2pdf, reportlab, holidays) —
    ohne sie schlagen PDF-Erzeugung bzw. Feiertags-Lookup im Artefakt stumm
    fehl; pystray kommt fürs Tray/Minimize-to-Tray dazu (eigener Fehlermodus),
    keyring für die SMTP-Passwörter: dessen Backends hängen an Entry-Points,
    die ein reiner Import-Scan nicht sieht (jaraco/keyring#399) — ohne das
    fiele der gebaute Build still auf den Datei-Fallback zurück.
    `--collect-all` und der Paketname sind separate Listenelemente, daher
    Element-Test."""
    for build_fn in (build.build_windows, build.build_linux):
        cmd = _capture_pyinstaller_cmd(monkeypatch, build_fn)
        for pkg in ("xhtml2pdf", "reportlab", "holidays", "pystray", "keyring"):
            assert pkg in cmd, f"{pkg} fehlt im {build_fn.__name__}-Kommando"
```

Run: `pytest tests/test_build.py -v`
Expected: PASS

- [ ] **Step 3: README ergänzen**

Im Features-Abschnitt eine Zeile mit Versionsmarker (die Zielversion aus dem Release-PR einsetzen):

```markdown
- **SMTP-Versand** *(ab X.Y.Z)* — Berichte über einen eigenen Mail-Server statt über die Gmail-API verschicken; mehrere Konten mit je eigenem Empfänger möglich.
```

Neuer Abschnitt „E-Mail-Versand ohne Google (SMTP)" nach dem Gmail-Setup-Abschnitt:

```markdown
## E-Mail-Versand ohne Google (SMTP)

Statt der Gmail-API kann die App Berichte über einen ganz normalen
Mail-Server verschicken — dann wird kein Google-Cloud-Projekt und keine
`credentials.json` gebraucht.

Einstellungen → **SMTP** → **Hinzufügen**:

| Feld | Bedeutung |
|------|-----------|
| Name | Frei wählbar, erscheint so im Sende-Dialog |
| Server / Port | z. B. `mail.gmx.net` / `587` |
| Verschlüsselung | STARTTLS (Port 587) oder SSL/TLS (Port 465) |
| Benutzer / Passwort | Zugangsdaten des Postfachs; darf bei internen Relays ohne Anmeldung leer bleiben |
| Absender | Die Adresse, die als Absender erscheint |
| Empfänger | Wohin dieses Konto den Bericht schickt |

**Verbindung testen** prüft Server und Zugangsdaten, ohne eine Mail zu
verschicken.

Das Passwort landet im Schlüsselbund des Betriebssystems (Windows
Credential Manager, macOS Keychain, Linux Secret Service). Steht keiner zur
Verfügung, wird es lokal in `smtp.json` gespeichert — die App sagt das dann
beim Speichern.

**Was nicht geht:** Microsoft-Konten (Outlook.com, Microsoft 365). Microsoft
hat SMTP mit Passwort 2026 abgeschaltet; auch App-Passwörter funktionieren
dort nicht mehr. Für **Gmail** wird ein
[App-Passwort](https://support.google.com/accounts/answer/185833) benötigt —
nicht das Kontopasswort —, das eine aktive Zwei-Faktor-Anmeldung voraussetzt.

SMTP-Konten gelten **nur auf diesem Gerät** und reisen nicht per
Multi-Device-Sync.
```

Im Gmail-Abschnitt einen Verweis ergänzen, dass das nicht mehr der einzige Weg ist.

- [ ] **Step 4: `docs/known-limitations.md` ergänzen**

Zwei Einträge im Stil der vorhandenen (Datei zuerst lesen und die dortige Struktur übernehmen):

```markdown
## SMTP: keine Microsoft-Konten

Der SMTP-Versand meldet sich mit Benutzer und Passwort an. Microsoft hat das
für Outlook.com und Microsoft 365 2026 abgeschaltet (Ablehnung ab März,
endgültig zum 30.04.2026) — auch App-Passwörter greifen dort nicht mehr, SMTP
läuft nur noch über OAuth2. Ein Microsoft-Postfach lässt sich deshalb nicht
als SMTP-Konto einrichten; wer eines nutzen will, geht über die Gmail-API
oder einen anderen Anbieter.

Ein eigener OAuth2-Flow für SMTP (XOAUTH2) würde das lösen, wäre aber ein
zweiter vollständiger Auth-Flow neben dem bestehenden — bewusst nicht gebaut.

## SMTP-Konten sind gerätelokal

Wie Webhooks und Urlaub reisen SMTP-Konten nicht per Drive-Sync: sie enthalten
Zugangsdaten, und die haben im Sync-Doc nichts verloren. Auf einem zweiten
Gerät müssen die Konten deshalb neu eingerichtet werden.
```

- [ ] **Step 5: Projekthinweise nachziehen**

In `CLAUDE.md`, Abschnitt „Struktur", nach dem `src/webhook_store.py`-Eintrag:

```markdown
- `src/mime_message.py` — Aufbau der Mail-Nachricht, gemeinsam für Gmail-API
  und SMTP. Hier liegen die drei UTF-8-Pflichten und die
  Steuerzeichen-Abwehr gegen Header-Injection (Audit N11) — genau einmal;
  `mail.send_email` und `smtp.send` bauen ihre Nachricht beide hierüber
- `src/smtp.py` — SMTP-Versand (stdlib `smtplib`/`ssl`), Verbindungstest ohne
  Mail und **eigene** Fehlerklassifikation (`auth`/`recipient`/`tls`/
  `offline`/`server`). Eigener Klassifikator wie bei `webhook.py`: die drei
  Kinds aus `mail_task` würden jede Serverantwort zu „unerwarteter Fehler mit
  Traceback" verschmelzen. TLS immer mit Zertifikatsprüfung, bewusst ohne
  Schalter dagegen
- `src/smtp_store.py` — gerätelokaler Store der SMTP-Konten (`smtp.json`),
  Mechanik wie `webhook_store.py`. Reist **nicht** per Drive-Sync
- `src/keyring_store.py` — Passwörter im OS-Schlüsselbund, mit Datei-Fallback
  wenn keiner verfügbar ist (Linux ohne Secret Service). `import keyring`
  lazy in den Funktionen (CI)
```

Im Abschnitt „UTF-8 im Mail-Pipeline" den Satz ergänzen, dass die drei Pflichten jetzt in `src/mime_message.py` liegen und für beide Mailwege gelten.

In `src/CLAUDE.md` den Abschnitt „Threading-Modell" um den Satz ergänzen, dass `perform_send` drei Kanaltypen feuert (Gmail, n SMTP-Konten, n Webhooks) und der Schlüsselbund-Zugriff im Worker passiert, nie im Tk-Callback.

- [ ] **Step 6: Volle Suite und Lint**

Run: `ruff check .`
Run: `npx pyright`
Run: `pytest`
Expected: alles grün.

- [ ] **Step 7: Frozen-Build lokal prüfen**

Run: `python scripts/build.py`

Danach `dist\Zeiterfassung\Zeiterfassung.exe` starten, ein SMTP-Konto anlegen, speichern und prüfen: kommt die Meldung „Passwort lokal gespeichert"? Dann hat der Frozen-Build kein Backend gefunden und `--collect-all keyring` greift nicht — das ist genau der Fall aus jaraco/keyring#399 und muss vor dem Merge geklärt sein.

- [ ] **Step 8: Commit**

```bash
git add scripts/build.py tests/test_build.py README.md docs/known-limitations.md CLAUDE.md src/CLAUDE.md
git commit -F <commit-message-datei>
```

Commit-Message:

```
docs+build: SMTP dokumentieren, keyring in den Frozen-Build

--collect-all keyring: die Backends haengen an Entry-Points, die ein
reiner Import-Scan nicht sieht (jaraco/keyring#399). Ohne das faende der
gebaute Build seinen Schluesselbund nicht und fiele still auf die Datei
zurueck.

README bekommt die SMTP-Anleitung, known-limitations die beiden Grenzen
(keine Microsoft-Konten, Konten sind geraetelokal).
```

---

## Vor dem Merge

Kein Task, aber Pflicht — beides steht so in `CLAUDE.md`:

1. **Pre-Release über alle drei Plattformen.** `keyring` ist eine neue Dependency mit plattformabhängigen Backends; auf der Windows-Dev-Maschine ist macOS und Linux nicht verifizierbar. Actions → Workflow **Release** → „Run workflow" mit gesetztem Häkchen **prerelease**. Je Plattform prüfen: Konto anlegen, Passwort speichern (Schlüsselbund oder Datei-Fallback?), Verbindungstest, echter Versand. Auf Linux zusätzlich: verhält sich die App ohne laufenden Secret Service sauber (Meldung, kein Absturz)?
2. **Versionsbump und CHANGELOG** im Release-PR, plus `release:minor`-Label. Die Zielversion ist auch der Wert für den README-Marker `*(ab X.Y.Z)*` aus Task 9.
