# SMTP-Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SMTP wird ein vollwertiger, gleichrangiger Mailweg neben der Gmail-API — in beiden Sendepfaden (Bericht senden und Teilen), mit n konfigurierbaren Konten je eigenem Empfänger.

**Architecture:** Der MIME-Bau wandert aus `mail.send_email` in ein reines Modul, das Gmail und SMTP teilen. `send_task.perform_send` bleibt der Dispatcher, der er seit Audit M10 ist, und bekommt SMTP als dritten Kanaltyp. Konten liegen in einem gerätelokalen Store nach dem Vorbild von `webhook_store.py`; Passwörter liegen im OS-Schlüsselbund mit Datei-Fallback, jeder Zugriff hinter einem Watchdog.

**Tech Stack:** Python 3.10, stdlib (`smtplib`, `ssl`, `email`, `threading`), `keyring==25.7.0`, Tkinter, pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-smtp-support-design.md` (Revision 2, nach Review)

## Global Constraints

- **Python 3.10** ist das CI- und Release-Python. Jede neue gepinnte Dependency muss 3.10 unterstützen.
- **Shell unter Windows:** kein `&&` zum Verketten. Sequenziell mit `;`, bedingt mit `if ($?) { ... }`.
- **Tests laufen aus dem Repo-Root:** `pytest`, einzeln `pytest tests/test_x.py::test_name -v`.
- **UI-Strings sind deutsch.** Fehlermeldungen sagen, was zu tun ist.
- **Getestet wird Logik, nicht UI** (entschiedene Scope-Grenze M16). Tk-gebundener Code bekommt keine automatisierten Tests; die Logik gehört Tk-frei in pure Module. Wer merkt, dass eine Fallunterscheidung nur in einer Dialog-Closure lebt, hat sie am falschen Ort.
- **Neue Tk-freie Module werden vollständig annotiert** (Rückgabetyp **und** alle Parameter — der Test prüft auch verschachtelte Funktionen) und in `ANNOTATED_MODULES` in `tests/test_type_annotations.py` eingetragen. Ein Eintrag dort ist eine Zusage; eine falsche Annotation ist schlimmer als keine.
- **`import keyring` immer lazy innerhalb der Funktion**, nie auf Modulebene, und immer mit `# pyright: ignore[reportMissingImports]` — die Lib ist im CI nicht installiert.
- **Secrets nie loggen.** `logs/zeiterfassung.log` ist ungehärtet und genau die Datei, die Nutzer bei Problemen anhängen. Bei Datensatz-Warnungen nur `id` und `name` loggen (Muster `webhook_store._load`).
- **Fehlerdialoge folgen der N14-Zweiteilung:** kuratierte, erwartete Fehler → themed Drop-ins aus `src/theme`; nur die Catch-all-Zweige mit echtem Traceback → rohes `tkinter.messagebox.showerror`. Ein themed Dialog mit dem Text „None" ist beides falsch.
- **Dialoge über `theme.create_dialog`**, keine dialogspezifischen Stil-Extras, `center_dialog_on_parent` nach dem Aufbau.
- **Blockierendes gehört in den `BackgroundTaskRunner`**, nie in einen Tk-Callback: `store.save`/`delete` starten einen icacls-Subprozess (timeout 15 s), SMTP-Verbindungen gehen ins Netz, und der Schlüsselbund kann auf Linux blockieren. **Und der Worker muss garantiert zurückkehren** — kehrt `fn()` nie zurück, ruft der Runner `on_done` nie, und der Dialog steht dauerhaft auf „Sende…".
- **Commit-Messages** enden mit den beiden Trailern:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01VJux6qnwTncwi1qbmHBHet
  ```
  Mehrzeilige Messages über eine Datei (`git commit -F <datei>`) — Heredoc und PowerShell-Here-String scheitern in dieser Umgebung.
- **Nach jeder Task:** `ruff check .`, `npx pyright`, `pytest` — alle drei grün, bevor committet wird.

---

### Task 1: MIME-Bau herausziehen (`src/mime_message.py`)

Reiner Refactor ohne Verhaltensänderung. `tests/test_mail.py` bleibt unverändert und muss grün bleiben — das ist die Absicherung, dass am Gmail-Pfad nichts verrutscht.

**Files:**
- Create: `src/mime_message.py`
- Modify: `src/mail.py` (`send_email`, ab Zeile 341; die vier `email.*`-Importe oben)
- Modify: `tests/test_type_annotations.py`
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

Hier liegen ZWEI der drei UTF-8-Pflichten (MIMEText-Charset und
Betreff-Header) und die Steuerzeichen-Abwehr gegen Header-Injection
(Audit N11). Die dritte Pflicht — <meta charset="utf-8"> im <head> — sitzt
bei den HTML-Erzeugern (report.py, share_dialog.py) und ist hier bewusst
nicht prüfbar.
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


def test_subject_control_chars_cannot_inject_a_header():
    """Header(subject, "utf-8") kodiert IMMER nach RFC 2047, auch reines
    ASCII — ein eingeschleustes CRLF landet in der kodierten Nutzlast, nicht
    als neuer Header. Deshalb braucht der Betreff keine eigene Abwehr."""
    msg = build_message(to="a@example.com",
                        subject="Bericht\r\nBcc: attacker@evil.com",
                        html_body="<p>x</p>")
    assert msg["bcc"] is None
    assert "attacker@evil.com" not in (msg.get("bcc") or "")


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

Tk-frei, stdlib-only, ohne Google-Import. Hier liegen ZWEI der drei
UTF-8-Pflichten aus CLAUDE.md („UTF-8 im Mail-Pipeline") — der
MIMEText-Charset und der Betreff-Header — sowie die Steuerzeichen-Abwehr
gegen Header-Injection (Audit N11), damit sie für beide Transporte gilt und
nicht in zwei Kopien auseinanderläuft.

Die dritte Pflicht, `<meta charset="utf-8">` im `<head>`, liegt NICHT hier:
sie gehört zu den HTML-Erzeugern (`report.generate_report`, `share_dialog`),
weil dieses Modul das HTML nur entgegennimmt.
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

    Der Betreff braucht das nicht: `Header(subject, "utf-8")` kodiert immer
    nach RFC 2047, ein CRLF landet dort in der Nutzlast.
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
Expected: PASS

- [ ] **Step 5: `mail.send_email` auf den gemeinsamen Bau umstellen**

In `src/mail.py` die vier jetzt ungenutzten Importe entfernen (`MIMEText`, `MIMEMultipart`, `MIMEApplication`, `Header` — sie werden ausschließlich in `send_email` verwendet, sonst schlägt `ruff` mit F401 zu) und stattdessen ergänzen:

```python
from src.mime_message import build_message
```

Rumpf von `send_email` ab der Legacy-Alias-Behandlung ersetzen (Signatur und Docstring bleiben):

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
Expected: PASS — insbesondere `test_send_email_json_attachment_uses_subtype` und `test_send_email_rejects_recipient_with_control_chars`. Beide sind unverändert und belegen, dass der Refactor nichts verschoben hat. (Die Header-Reihenfolge im Rohtext ändert sich minimal, weil `build_message` `to`/`subject` nach dem `attach()` setzt — beide Tests prüfen nur Substrings, das ist folgenlos.)

- [ ] **Step 7: Modul in die Annotations-Whitelist eintragen**

In `tests/test_type_annotations.py`, in `ANNOTATED_MODULES` nach `"src/time_utils.py"`:

```python
    "src/mime_message.py",
```

- [ ] **Step 8: Lint, Typecheck, volle Suite**

Run: `ruff check .`
Run: `npx pyright`
Run: `pytest`

- [ ] **Step 9: Commit**

```bash
git add src/mime_message.py src/mail.py tests/test_mime_message.py tests/test_type_annotations.py
git commit -F <commit-message-datei>
```

```
refactor(mail): MIME-Bau in src/mime_message.py herausziehen

Zwei der drei UTF-8-Pflichten und die Steuerzeichen-Abwehr (Audit N11)
lagen in send_email verwoben mit dem Gmail-Versand. Der SMTP-Pfad braucht
dieselbe Nachricht — als Kopie liefe sie mit der Zeit auseinander.

Die Abwehr prueft jetzt auch from_addr: beim SMTP-Versand ist der
Absender ein zweites nutzergefuelltes Headerfeld.

Kein Verhaltenswechsel; tests/test_mail.py ist unveraendert gruen.
```

---

### Task 2: Schlüsselbund mit Watchdog (`src/keyring_store.py`)

**Files:**
- Create: `src/keyring_store.py`
- Modify: `requirements.txt`
- Modify: `README.md` (Abhängigkeitstabelle)
- Modify: `tests/test_type_annotations.py`
- Test: `tests/test_keyring_store.py`

**Nicht** anfassen: `requirements-test.txt`. Kein Test benutzt die echte Lib, und `SecretStorage` zöge `cryptography` (Rust-Extension) in die CI — genau die Klasse, wegen der diese Datei existiert.

**Interfaces:**
- Consumes: nichts
- Produces:
  ```python
  SERVICE: str            # == "Zeiterfassung"
  WATCHDOG_TIMEOUT: float # == 5.0
  set_secret(record_id: str, password: str) -> str      # "keyring" | "file"
  get_secret(record: dict[str, Any]) -> str
  delete_secret(record_id: str) -> None
  persist_password(candidate: dict[str, Any], typed: str,
                   stored: dict[str, Any] | None = None) -> dict[str, Any]
  ```

- [ ] **Step 1: Write the failing test**

Neue Datei `tests/test_keyring_store.py`:

```python
"""Tests für den Schlüsselbund-Zugriff: Keyring-Pfad, Datei-Fallback,
Watchdog und die reine Zustandslogik persist_password.

`keyring` wird im Produktivcode lazy innerhalb der Funktionen importiert
(CI-Pflicht). Die Tests schieben deshalb ein Fake-Modul in sys.modules,
statt das echte Backend des Testrechners anzufassen — ein Test darf keine
Einträge im Windows-Anmeldeinformationsmanager hinterlassen.
"""

import sys
import threading
import types

import pytest

from src import keyring_store


class _FakeKeyring:
    def __init__(self, working=True, block=None):
        self.working = working
        self.block = block          # threading.Event: blockiert bis gesetzt
        self.store = {}

    def _guard(self):
        if self.block is not None:
            self.block.wait()
        if not self.working:
            raise RuntimeError("No recommended backend was available")

    def set_password(self, service, account, password):
        self._guard()
        self.store[(service, account)] = password

    def get_password(self, service, account):
        self._guard()
        return self.store.get((service, account))

    def delete_password(self, service, account):
        self._guard()
        del self.store[(service, account)]


@pytest.fixture
def fake_keyring(monkeypatch):
    def _install(working=True, block=None):
        fake = _FakeKeyring(working=working, block=block)
        module = types.ModuleType("keyring")
        module.set_password = fake.set_password
        module.get_password = fake.get_password
        module.delete_password = fake.delete_password
        monkeypatch.setitem(sys.modules, "keyring", module)
        return fake
    return _install


def _record(**over):
    base = {"id": "rec-1", "name": "Firma", "password_location": "keyring"}
    base.update(over)
    return base


# --- set_secret / get_secret / delete_secret -------------------------------

def test_set_secret_uses_keyring_when_available(fake_keyring):
    fake = fake_keyring()
    assert keyring_store.set_secret("rec-1", "geheim") == "keyring"
    assert fake.store[(keyring_store.SERVICE, "rec-1")] == "geheim"


def test_set_secret_falls_back_to_file_without_backend(fake_keyring):
    """Linux ohne Secret Service: das Feature muss trotzdem funktionieren."""
    fake_keyring(working=False)
    assert keyring_store.set_secret("rec-1", "geheim") == "file"


def test_set_secret_falls_back_when_keyring_is_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    assert keyring_store.set_secret("rec-1", "geheim") == "file"


def test_get_secret_reads_from_keyring(fake_keyring):
    fake_keyring()
    keyring_store.set_secret("rec-1", "geheim")
    assert keyring_store.get_secret(_record()) == "geheim"


def test_get_secret_reads_from_record_when_location_is_file(fake_keyring):
    """Beim Datei-Fallback wird der Schlüsselbund gar nicht erst gefragt."""
    fake_keyring(working=False)
    record = _record(password_location="file", password="geheim")
    assert keyring_store.get_secret(record) == "geheim"


def test_get_secret_returns_empty_string_when_nothing_is_stored(fake_keyring):
    fake_keyring()
    assert keyring_store.get_secret(_record(id="unbekannt")) == ""


def test_delete_secret_removes_the_entry(fake_keyring):
    """Ohne das bliebe das Secret nach dem Löschen des Kontos verwaist."""
    fake = fake_keyring()
    keyring_store.set_secret("rec-1", "geheim")
    keyring_store.delete_secret("rec-1")
    assert (keyring_store.SERVICE, "rec-1") not in fake.store


def test_delete_secret_is_quiet_when_nothing_is_stored(fake_keyring):
    fake_keyring()
    keyring_store.delete_secret("gibt-es-nicht")


# --- Watchdog --------------------------------------------------------------

def test_set_secret_gives_up_when_the_keyring_blocks(fake_keyring, monkeypatch):
    """Der eigentliche Grund für den Watchdog: auf Linux ruft
    keyring.get_preferred_collection() ein collection.unlock() OHNE Timeout.
    Blockiert das, kehrt der Worker nie zurück, BackgroundTaskRunner ruft
    on_done nie, und der Sende-Dialog steht dauerhaft auf „Sende…"."""
    gate = threading.Event()
    fake_keyring(block=gate)
    monkeypatch.setattr(keyring_store, "WATCHDOG_TIMEOUT", 0.05)
    try:
        assert keyring_store.set_secret("rec-1", "geheim") == "file"
    finally:
        gate.set()


def test_get_secret_gives_up_when_the_keyring_blocks(fake_keyring, monkeypatch):
    gate = threading.Event()
    fake_keyring(block=gate)
    monkeypatch.setattr(keyring_store, "WATCHDOG_TIMEOUT", 0.05)
    try:
        record = _record(password="notfall")
        assert keyring_store.get_secret(record) == "notfall"
    finally:
        gate.set()


def test_delete_secret_gives_up_when_the_keyring_blocks(fake_keyring, monkeypatch):
    gate = threading.Event()
    fake_keyring(block=gate)
    monkeypatch.setattr(keyring_store, "WATCHDOG_TIMEOUT", 0.05)
    try:
        keyring_store.delete_secret("rec-1")   # kehrt zurück, statt zu hängen
    finally:
        gate.set()


# --- persist_password ------------------------------------------------------

def test_persist_password_new_password_goes_to_the_keyring(fake_keyring):
    fake = fake_keyring()
    result = keyring_store.persist_password(_record(), "neu")
    assert result["password_location"] == "keyring"
    assert "password" not in result
    assert fake.store[(keyring_store.SERVICE, "rec-1")] == "neu"


def test_persist_password_new_password_falls_back_into_the_record(fake_keyring):
    fake_keyring(working=False)
    result = keyring_store.persist_password(_record(), "neu")
    assert result["password_location"] == "file"
    assert result["password"] == "neu"


def test_persist_password_empty_keeps_the_stored_file_password(fake_keyring):
    """Nur den Port geändert und gespeichert: das Passwort darf nicht
    verschwinden. Genau dieser Fall lebte vorher nur in einer Dialog-Closure
    und war durch nichts gedeckt."""
    fake_keyring(working=False)
    stored = _record(password_location="file", password="alt")
    result = keyring_store.persist_password(_record(), "", stored=stored)
    assert result["password_location"] == "file"
    assert result["password"] == "alt"


def test_persist_password_empty_keeps_the_keyring_location(fake_keyring):
    fake_keyring()
    stored = _record(password_location="keyring")
    result = keyring_store.persist_password(_record(), "", stored=stored)
    assert result["password_location"] == "keyring"
    assert "password" not in result


def test_persist_password_does_not_mutate_its_input(fake_keyring):
    fake_keyring()
    candidate = _record()
    keyring_store.persist_password(candidate, "neu")
    assert candidate == _record()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_keyring_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.keyring_store'`

- [ ] **Step 3: Write the implementation**

Neue Datei `src/keyring_store.py`:

```python
"""Passwörter im OS-Schlüsselbund, mit Datei-Fallback (Tk-frei).

Windows Credential Manager / macOS Keychain / Linux Secret Service. Ist kein
Backend verfügbar — Linux ohne laufenden Secret Service, `keyring` gar nicht
installiert, oder der Schlüsselbund antwortet nicht —, meldet `set_secret` das
ehrlich als `"file"` zurück; der Aufrufer legt das Passwort dann in seinen
eigenen, gehärtet geschriebenen Store und zeigt es dem Nutzer an.

`import keyring` steht bewusst INNERHALB der Funktionen: die Importkette
`src.ui → … → smtp_store → keyring_store` zöge die Lib sonst in die CI, die
bewusst nur `requirements-test.txt` installiert (gleiches Muster wie die
Google-Wrapper in drive.py/gcal.py).

**Warum jeder Zugriff hinter einem Watchdog läuft:** Auf Linux meldet sich das
SecretService-Backend schon dann als nutzbar, wenn der D-Bus-Name lediglich
*aktivierbar* ist — im AppImage-Fall also praktisch immer. `keyring` ruft dann
`collection.unlock()` OHNE Timeout, obwohl SecretStorage einen anbietet;
blockiert das (gesperrter Schlüsselbund, kein Prompt), kehrt der Aufruf nie
zurück. Da diese Funktionen aus `BackgroundTaskRunner`-Workern gerufen werden
und der Runner `on_done` erst nach der Rückkehr von `fn()` ruft, stünde der
Sende-Dialog dauerhaft auf „Sende…" — bis zum App-Neustart. Genau dieser
Ausfall ist in pip (#7883) und poetry (#8623) dokumentiert.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)

SERVICE = "Zeiterfassung"

# Großzügig genug für einen echten Keychain-Prompt auf einem trägen System,
# kurz genug, dass ein hängender Schlüsselbund den Versand nicht auffrisst.
WATCHDOG_TIMEOUT = 5.0


def _call_guarded(work: Callable[[], Any]) -> tuple[bool, Any]:
    """Ruft `work` in einem Sekundär-Thread und gibt nach `WATCHDOG_TIMEOUT`
    auf.

    Liefert `(True, ergebnis)` bei rechtzeitiger Rückkehr, sonst
    `(False, None)`. Eine Exception aus `work` wird im Aufrufer-Thread erneut
    geworfen. Der Thread ist ein Daemon: bleibt er hängen, blockiert er das
    Beenden der App nicht.
    """
    box: dict[str, Any] = {}

    def runner() -> None:
        try:
            box["value"] = work()
        except BaseException as exc:  # bewusst alles — wird unten weitergereicht
            box["error"] = exc

    thread = threading.Thread(target=runner, daemon=True,
                              name="keyring-watchdog")
    thread.start()
    thread.join(WATCHDOG_TIMEOUT)
    if thread.is_alive():
        return False, None
    if "error" in box:
        raise box["error"]
    return True, box.get("value")


def set_secret(record_id: str, password: str) -> str:
    """Legt `password` im Schlüsselbund ab.

    Liefert `"keyring"` bei Erfolg, sonst `"file"` — dieser Wert gehört als
    `password_location` in den Datensatz des Aufrufers.
    """
    def work() -> None:
        import keyring  # pyright: ignore[reportMissingImports]

        keyring.set_password(SERVICE, record_id, password)

    try:
        ok, _ = _call_guarded(work)
    except Exception:
        # Bewusst alles: NoKeyringError, ein fehlgeschlagener D-Bus-Aufruf,
        # eine gar nicht installierte Lib. Für den Aufrufer ist all das
        # dasselbe — es gibt keinen Schlüsselbund.
        log.warning("Schlüsselbund nicht verfügbar — Passwort wird lokal "
                    "in der Konfigurationsdatei abgelegt", exc_info=True)
        return "file"
    if not ok:
        log.warning("Schlüsselbund antwortet nicht (Timeout nach %.1fs) — "
                    "Passwort wird lokal abgelegt", WATCHDOG_TIMEOUT)
        return "file"
    return "keyring"


def get_secret(record: dict[str, Any]) -> str:
    """Liest das Passwort zu `record`.

    Steht `password_location` auf `"file"`, wird der Schlüsselbund gar nicht
    erst gefragt — das spart auf Linux einen D-Bus-Roundtrip, der ohnehin
    nichts liefern würde.
    """
    if record.get("password_location") == "file":
        return record.get("password") or ""

    def work() -> Any:
        import keyring  # pyright: ignore[reportMissingImports]

        return keyring.get_password(SERVICE, record.get("id", ""))

    try:
        ok, stored = _call_guarded(work)
    except Exception:
        log.warning("Schlüsselbund nicht lesbar — greife auf die lokal "
                    "abgelegte Kopie zurück, falls vorhanden", exc_info=True)
        return record.get("password") or ""
    if not ok:
        log.warning("Schlüsselbund antwortet nicht (Timeout nach %.1fs)",
                    WATCHDOG_TIMEOUT)
        return record.get("password") or ""
    if stored:
        return str(stored)
    return record.get("password") or ""


def delete_secret(record_id: str) -> None:
    """Räumt das Secret ab. Fehlt es, ist das kein Fehler.

    Muss beim Löschen eines Kontos gerufen werden — sonst bliebe der Eintrag
    für immer im Schlüsselbund stehen, unter einer id, die in keiner Datei
    mehr steht.
    """
    def work() -> None:
        import keyring  # pyright: ignore[reportMissingImports]

        keyring.delete_password(SERVICE, record_id)

    try:
        ok, _ = _call_guarded(work)
    except Exception:
        log.debug("Secret %r nicht gelöscht (kein Schlüsselbund oder kein "
                  "Eintrag)", record_id, exc_info=True)
        return
    if not ok:
        log.warning("Schlüsselbund antwortet nicht — Secret %r blieb stehen",
                    record_id)


def persist_password(candidate: dict[str, Any], typed: str,
                     stored: dict[str, Any] | None = None) -> dict[str, Any]:
    """Entscheidet, wo das Passwort landet, und legt es ab.

    Vier Fälle, und alle vier gehören hierher statt in eine Dialog-Closure —
    sonst lebte die Regel nur im Widget und wäre durch nichts gedeckt
    (CLAUDE.md, „Getestet wird Logik, nicht UI").

    - `typed` gefüllt → in den Schlüsselbund; klappt das nicht, in den
      Datensatz (`password_location="file"`).
    - `typed` leer → unverändert: `stored` bestimmt Ort und Wert. Bei einem
      bestehenden Datei-Fallback wird das dort abgelegte Passwort übernommen,
      sonst bliebe es beim nächsten Speichern weg.
    - Kein `stored` (neues Konto ohne Passwort) → `keyring`, kein `password`.

    Verändert `candidate` nicht.
    """
    result = dict(candidate)
    if typed:
        location = set_secret(result["id"], typed)
        result["password_location"] = location
        if location == "file":
            result["password"] = typed
        else:
            result.pop("password", None)
        return result

    location = (stored or {}).get("password_location", "keyring")
    result["password_location"] = location
    if location == "file":
        result["password"] = (stored or {}).get("password", "")
    else:
        result.pop("password", None)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_keyring_store.py -v`
Expected: PASS

- [ ] **Step 5: Dependency pinnen — direkt UND drei transitive**

In `requirements.txt` nach der `holidays`-Zeile:

```
keyring==25.7.0
# Bewusste Ausnahme von der Transitiv-Regel (sonst pinnen wir nur direkte
# Deps): jaraco.functools/context und importlib_metadata sind Transitive von
# keyring und fordern in ihren aktuellen Versionen bereits Python >=3.10 —
# also GENAU unser CI-/Release-Python, ohne Puffer. Zieht jaraco seine
# Skeleton-Pakete auf >=3.11, braeche der 3.10-Build still ueber eine Dep,
# die niemand angefasst hat, und der in CLAUDE.md vorgeschriebene
# 3.10-Gegencheck schlaege nicht an, weil er nur die direkte Dep betrachtet.
jaraco.functools==4.6.0
jaraco.context==6.1.2
importlib_metadata==9.0.1
```

**Vor dem Commit gegenprüfen** (CLAUDE.md verlangt den 3.10-Check per PyPI `requires_python`), dass alle vier Versionen existieren und `>=3.10` oder niedriger fordern; weicht eine ab, die nächstniedrigere passende Version nehmen und den Kommentar entsprechend anpassen.

In der README-Tabelle der Abhängigkeiten eine Zeile ergänzen:

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

Der typecheck-Job hat `keyring` nicht installiert — deshalb trägt jeder der drei `import keyring` ein `# pyright: ignore[reportMissingImports]`. Meldet pyright trotzdem etwas, ist der Kommentar an der falschen Zeile.

- [ ] **Step 8: Commit**

```bash
git add src/keyring_store.py tests/test_keyring_store.py requirements.txt README.md tests/test_type_annotations.py
git commit -F <commit-message-datei>
```

```
feat(secrets): Schluesselbund-Zugriff mit Watchdog und Datei-Fallback

set_secret meldet zurueck, wo das Passwort gelandet ist ("keyring" oder
"file"); persist_password haelt die vier Uebergaenge als reine Funktion,
statt sie in einer Dialog-Closure zu verstecken.

Jeder OS-Zugriff laeuft hinter einem 5-s-Watchdog: keyring ruft auf Linux
collection.unlock() ohne Timeout, und ein haengender Worker bedeutet, dass
BackgroundTaskRunner on_done nie ruft — der Dialog stuende dauerhaft auf
"Sende...".

keyring==25.7.0 gepinnt, dazu drei Transitive als begruendete Ausnahme:
sie fordern bereits Python >=3.10, unser Release-Python hat also keinen
Puffer mehr.
```

---

### Task 3: Versand (`src/smtp.py`)

Kommt **vor** dem Store, weil `SECURITY_MODES` hier definiert wird: der Transport bestimmt, welche Modi es gibt, der Store validiert dagegen.

**Files:**
- Create: `src/smtp.py`
- Modify: `tests/test_type_annotations.py`
- Test: `tests/test_smtp.py`

**Interfaces:**
- Consumes: `mime_message.build_message` (Task 1), `mail.is_offline_error` (Bestand)
- Produces:
  ```python
  SECURITY_MODES: tuple[str, ...]   # ("starttls", "ssl", "none")
  DEFAULT_TIMEOUT: int              # == 20
  class TlsNotSupported(Exception): ...
  class AuthNotSupported(Exception): ...
  send(record: dict, password: str, *, subject: str, html: str,
       to: str | None = None,
       attachment_bytes: bytes | None = None,
       attachment_filename: str | None = None,
       attachment_subtype: str = "pdf") -> None
  test_connection(record: dict, password: str) -> None
  classify_smtp_error(exc: BaseException) -> dict[str, Any]
  ```
  `classify_smtp_error` liefert `{"ok": False, "kind": ..., "detail": str, "error": exc, "tb": str | None}` mit `kind` aus `auth | recipient | tls | server | offline | error`.

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
        self.tls_context = None
        self.logged_in = None
        self.sent = []
        self.noops = 0
        self.quit_called = False
        self.closed = False
        self.fail_starttls = None
        self.fail_login = None
        self.fail_send = None

    def starttls(self, context=None):
        self.started_tls = True
        self.tls_context = context
        if self.fail_starttls:
            raise self.fail_starttls

    def login(self, user, password):
        if self.fail_login:
            raise self.fail_login
        self.logged_in = (user, password)

    def send_message(self, message):
        if self.fail_send:
            raise self.fail_send
        self.sent.append(message)

    def noop(self):
        self.noops += 1

    def quit(self):
        self.quit_called = True

    def close(self):
        self.closed = True


@pytest.fixture
def fake_smtp(monkeypatch):
    """Fängt SMTP und SMTP_SSL ab und merkt sich die erzeugte Instanz."""
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


# --- Verbindungsaufbau -----------------------------------------------------

def test_starttls_connection_upgrades_and_logs_in(fake_smtp):
    smtp.send(_record(), "geheim", subject="S", html="<p>x</p>")
    server = fake_smtp["plain"]
    assert server.started_tls is True
    assert server.logged_in == ("user@example.com", "geheim")
    assert server.quit_called is True


def test_starttls_gets_a_verifying_context(fake_smtp):
    """Ohne expliziten Kontext faellt smtplib auf _create_stdlib_context()
    zurueck — OHNE Hostname- und Zertifikatspruefung. Eine Regression dort
    kaeme sonst durch alle Tests."""
    smtp.send(_record(), "geheim", subject="S", html="<p>x</p>")
    context = fake_smtp["plain"].tls_context
    assert context is not None
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


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


def test_unknown_security_mode_is_rejected(fake_smtp):
    """Fail-CLOSED. Ein durchgerutschter Wert (Handedit in smtp.json,
    Gross-/Kleinschreibung, spaetere Migration) darf NICHT still
    unverschluesselt verbinden und AUTH PLAIN im Klartext schicken."""
    with pytest.raises(ValueError):
        smtp.send(_record(security="TLS"), "geheim", subject="S", html="<p>x</p>")
    assert fake_smtp == {}


def test_no_login_without_username(fake_smtp):
    """Interner Relay ohne Auth."""
    smtp.send(_record(username=""), "", subject="S", html="<p>x</p>")
    assert fake_smtp["plain"].logged_in is None


def test_timeout_is_set(fake_smtp):
    """Ohne Timeout hängt der Worker unbegrenzt an einem stummen Server."""
    smtp.send(_record(), "geheim", subject="S", html="<p>x</p>")
    assert fake_smtp["plain"].timeout == smtp.DEFAULT_TIMEOUT


# --- Nachricht -------------------------------------------------------------

def test_message_carries_from_to_and_attachment(fake_smtp):
    smtp.send(_record(), "geheim", subject="Bericht", html="<p>Grüße</p>",
              attachment_bytes=b"%PDF-1.4", attachment_filename="b.pdf",
              attachment_subtype="pdf")
    message = fake_smtp["plain"].sent[0]
    assert message["from"] == "user@example.com"
    assert message["to"] == "buchhaltung@example.com"
    assert "b.pdf" in message.as_string()


def test_to_overrides_the_account_recipient(fake_smtp):
    """Der Teilen-Pfad fragt den Empfaenger im Dialog ab; das
    recipient-Feld des Kontos ist semantisch etwas anderes."""
    smtp.send(_record(), "geheim", subject="S", html="<p>x</p>",
              to="kollege@example.com")
    assert fake_smtp["plain"].sent[0]["to"] == "kollege@example.com"


# --- Verbindung schließen --------------------------------------------------

def test_connection_is_closed_when_sending_fails(fake_smtp):
    """Sonst bleibt die Verbindung offen, wenn der Server die Mail ablehnt."""
    record = _record()

    def factory(*args, **kwargs):
        server = _FakeServer(*args, **kwargs)
        server.fail_send = smtplib.SMTPRecipientsRefused({"a@b": (550, b"nope")})
        fake_smtp["plain"] = server
        return server

    smtp.smtplib.SMTP = factory  # type: ignore[assignment]
    with pytest.raises(smtplib.SMTPRecipientsRefused):
        smtp.send(record, "geheim", subject="S", html="<p>x</p>")
    assert fake_smtp["plain"].closed is True


def test_close_still_closes_when_quit_raises(fake_smtp):
    """smtplib.quit() ruft close() erst NACH dem QUIT-Kommando; wirft das auf
    einer toten Verbindung, bliebe der Filedescriptor offen."""
    smtp.send(_record(), "geheim", subject="S", html="<p>x</p>")
    server = fake_smtp["plain"]

    def boom():
        raise smtplib.SMTPServerDisconnected("weg")

    server.quit = boom
    smtp._close(server)
    assert server.closed is True


def test_test_connection_sends_noop_but_no_mail(fake_smtp):
    smtp.test_connection(_record(), "geheim")
    server = fake_smtp["plain"]
    assert server.noops == 1
    assert server.sent == []


# --- Fehlerklassifikation --------------------------------------------------

@pytest.mark.parametrize("exc,expected", [
    (smtplib.SMTPAuthenticationError(535, b"Authentication unsuccessful"), "auth"),
    (smtp.AuthNotSupported("SMTP AUTH extension not supported by server."), "auth"),
    (smtplib.SMTPRecipientsRefused({"a@b": (550, b"no such user")}), "recipient"),
    (smtplib.SMTPSenderRefused(553, b"bad sender", "a@b"), "recipient"),
    (smtp.TlsNotSupported("STARTTLS extension not supported by server."), "tls"),
    (ssl.SSLError("certificate verify failed"), "tls"),
    (smtplib.SMTPServerDisconnected("connection closed"), "server"),
    (smtplib.SMTPConnectError(421, b"service unavailable"), "server"),
    (smtplib.SMTPNotSupportedError("SMTPUTF8 not supported"), "server"),
    (socket.gaierror("Name or service not known"), "offline"),
    (ConnectionRefusedError("refused"), "offline"),
    (TimeoutError("timed out"), "offline"),
    (OSError(101, "Network is unreachable"), "offline"),
    (ValueError("irgendwas ganz anderes"), "error"),
])
def test_error_classification(exc, expected):
    """Ohne eigenen Klassifikator kaeme jede SMTP-Fehlerantwort als
    „unerwarteter Fehler mit Traceback" beim Nutzer an."""
    result = smtp.classify_smtp_error(exc)
    assert result["ok"] is False
    assert result["kind"] == expected


def test_disconnect_after_timeout_is_not_reported_as_offline():
    """smtplib wirft SMTPServerDisconnected aus einem except-OSError-Block;
    is_offline_error folgt __context__ bis zum TimeoutError des Sockets. Ein
    Server, der annimmt und dann schweigt — der Fall, fuer den der Timeout
    existiert —, darf nicht „keine Internetverbindung" melden."""
    try:
        try:
            raise TimeoutError("timed out")
        except TimeoutError:
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
    except smtplib.SMTPServerDisconnected as e:
        assert smtp.classify_smtp_error(e)["kind"] == "server"


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
    exc = smtplib.SMTPAuthenticationError(535, b"5.7.3 Authentication unsuccessful")
    detail = smtp.classify_smtp_error(exc)["detail"]
    assert "535" in detail
    assert "Authentication unsuccessful" in detail


def test_recipient_detail_is_readable():
    """SMTPRecipientsRefused hat KEIN smtp_code/smtp_error, sondern ein Dict.
    Ohne eigenen Zweig staende in der Meldung woertlich
    {'a@b': (550, b'...')} — geschweifte Klammern und Bytes-Literal, und das
    beim haeufigsten Empfaengerfehler ueberhaupt."""
    exc = smtplib.SMTPRecipientsRefused(
        {"tippfehler@example.com": (550, b"5.1.1 User unknown")})
    detail = smtp.classify_smtp_error(exc)["detail"]
    assert "tippfehler@example.com" in detail
    assert "550" in detail
    assert "User unknown" in detail
    assert "{" not in detail
    assert "b'" not in detail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smtp.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.smtp'`

- [ ] **Step 3: Write the implementation**

Neue Datei `src/smtp.py`:

```python
"""SMTP-Versand (Tk-frei).

Der zweite Mailweg neben der Gmail-API. Die Nachricht selbst baut
`mime_message.build_message` — dieselbe wie beim Gmail-Versand, inklusive der
UTF-8-Pflichten und der Steuerzeichen-Abwehr.

Stdlib bis auf einen Import: `mail.is_offline_error` wird wiederverwendet,
statt die Offline-Erkennung zu kopieren. `src/mail.py` ist auf Modulebene
selbst Google-frei (die Google-Importe sind lazy) — es entsteht also kein
CI-Problem und kein Import-Zyklus.

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

SECURITY_MODES = ("starttls", "ssl", "none")

# Ohne Timeout hängt der Worker-Thread unbegrenzt an einem Server, der die
# Verbindung annimmt und dann schweigt.
DEFAULT_TIMEOUT = 20


class TlsNotSupported(Exception):
    """Der Server bietet STARTTLS nicht an."""


class AuthNotSupported(Exception):
    """Der Server bietet die AUTH-Extension nicht an.

    Eigene Klasse, weil `smtplib` für beide Fälle dieselbe
    `SMTPNotSupportedError` wirft — auch aus `send_message` bei
    Nicht-ASCII-Adressen ohne SMTPUTF8. Ohne Trennung meldete ein
    Firmen-Relay ohne AUTH „Verschlüsselung fehlgeschlagen", und der Nutzer
    drehte an TLS-Einstellungen, die nichts damit zu tun haben.
    """


def _tls_context() -> ssl.SSLContext:
    """Voller Prüfkontext. Es gibt bewusst keinen Schalter dagegen: eine
    solche Option wird angeklickt, um ein Problem loszuwerden, und bleibt
    dann an."""
    return ssl.create_default_context()


def _close(server: smtplib.SMTP) -> None:
    """Verbindung schließen, ohne den ursprünglichen Fehler zu überdecken.

    `quit()` ruft `close()` erst NACH dem QUIT-Kommando; wirft das auf einer
    toten Verbindung, bliebe der Filedescriptor offen. Deshalb `close()` im
    `finally` — nach erfolgreichem `quit()` ist es idempotent.
    """
    try:
        server.quit()
    except Exception:
        log.debug("SMTP-Verbindung ließ sich nicht sauber beenden",
                  exc_info=True)
    finally:
        try:
            server.close()
        except Exception:
            log.debug("SMTP-Socket ließ sich nicht schließen", exc_info=True)


def _open(record: dict[str, Any], password: str) -> smtplib.SMTP:
    """Baut die Verbindung auf und meldet sich an.

    **Fail-closed:** ein unbekannter `security`-Wert wirft, statt in den
    unverschlüsselten Zweig zu fallen. Sonst gäbe es faktisch doch einen
    Schalter zum Abschalten von TLS — nur unbeabsichtigt, und mit AUTH PLAIN
    im Klartext als Folge.

    Schlägt etwas nach dem Verbindungsaufbau fehl, wird die Verbindung
    geschlossen, bevor die Exception weiterfliegt.
    """
    security = record.get("security")
    if security not in SECURITY_MODES:
        raise ValueError(
            f"Unbekannter Verschlüsselungsmodus: {security!r}. "
            f"Erlaubt sind: {', '.join(SECURITY_MODES)}."
        )

    host = record["host"]
    port = int(record["port"])

    server: smtplib.SMTP
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=DEFAULT_TIMEOUT,
                                  context=_tls_context())
    else:
        server = smtplib.SMTP(host, port, timeout=DEFAULT_TIMEOUT)

    try:
        if security == "starttls":
            try:
                server.starttls(context=_tls_context())
            except smtplib.SMTPNotSupportedError as e:
                raise TlsNotSupported(str(e)) from e
        username = (record.get("username") or "").strip()
        if username:
            try:
                server.login(username, password)
            except smtplib.SMTPNotSupportedError as e:
                raise AuthNotSupported(str(e)) from e
    except BaseException:
        _close(server)
        raise
    return server


def send(record: dict[str, Any], password: str, *, subject: str, html: str,
         to: str | None = None,
         attachment_bytes: bytes | None = None,
         attachment_filename: str | None = None,
         attachment_subtype: str = "pdf") -> None:
    """Verschickt die Nachricht.

    Empfänger ist `to`, sonst `record["recipient"]`. Der Bericht-Versand lässt
    `to` weg (das Konto trägt seinen Empfänger); der Teilen-Pfad setzt es, weil
    dort der Nutzer die Adresse im Dialog eingibt.

    Wirft bei Fehlern — der Aufrufer klassifiziert über `classify_smtp_error`.
    Blockierend: gehört in einen Worker-Thread.
    """
    message = build_message(
        to=to if to is not None else record["recipient"],
        subject=subject, html_body=html,
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
    recipients = getattr(exc, "recipients", None)
    if isinstance(recipients, dict) and recipients:
        # SMTPRecipientsRefused hat KEIN smtp_code/smtp_error, sondern dieses
        # Dict. `str(exc)` waere sonst woertlich "{'a@b': (550, b'...')}".
        parts = []
        for address, response in recipients.items():
            try:
                code, message = response
            except (TypeError, ValueError):
                parts.append(str(address))
                continue
            if isinstance(message, bytes):
                message = message.decode("utf-8", errors="replace")
            parts.append(f"{address}: {code} {message}".strip())
        return ", ".join(parts)

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

    Die Reihenfolge ist Absicht:

    - Die eigenen Marker (`TlsNotSupported`/`AuthNotSupported`) zuerst — sie
      tragen die Information, die `SMTPNotSupportedError` allein nicht hat.
    - `SMTPAuthenticationError` und `SMTPSenderRefused` sind Unterklassen von
      `SMTPResponseException`, `SMTPRecipientsRefused` von `SMTPException` —
      das Speziellere muss vor dem Allgemeineren stehen.
    - **`SMTPException` steht VOR der Offline-Prüfung.** `smtplib` wirft
      `SMTPServerDisconnected` aus einem `except OSError`-Block, und
      `is_offline_error` folgt `__context__` bis zum `TimeoutError` des
      Sockets — ein Server, der annimmt und dann schweigt, meldete sonst
      „keine Internetverbindung".
    - Ein nacktes `OSError` am Schluss: CPython mappt `ENETUNREACH`/
      `EHOSTUNREACH` auf keine Subklasse, `is_offline_error` sieht es also
      nicht.

    Muss aus einem aktiven `except`-Block gerufen werden: der `error`-Fall
    liest den aktuellen Traceback über `traceback.format_exc()`.
    """
    def result(kind: str, detail: str, tb: str | None = None) -> dict[str, Any]:
        return {"ok": False, "kind": kind, "detail": detail,
                "error": exc, "tb": tb}

    if isinstance(exc, TlsNotSupported):
        return result("tls", str(exc))
    if isinstance(exc, AuthNotSupported):
        return result("auth", str(exc))
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return result("auth", _response_detail(exc))
    if isinstance(exc, (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused)):
        return result("recipient", _response_detail(exc))
    if isinstance(exc, ssl.SSLError):
        return result("tls", str(exc))
    if isinstance(exc, smtplib.SMTPException):
        return result("server", _response_detail(exc))
    if is_offline_error(exc):
        return result("offline", "")
    if isinstance(exc, OSError):
        return result("offline", str(exc))
    return result("error", str(exc), traceback.format_exc())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_smtp.py -v`
Expected: PASS

- [ ] **Step 5: Modul in die Annotations-Whitelist eintragen**

In `tests/test_type_annotations.py`, in `ANNOTATED_MODULES` nach `"src/webhook.py"`:

```python
    "src/smtp.py",
```

- [ ] **Step 6: Lint, Typecheck, volle Suite**

Run: `ruff check .`
Run: `npx pyright`
Run: `pytest`

- [ ] **Step 7: Commit**

```bash
git add src/smtp.py tests/test_smtp.py tests/test_type_annotations.py
git commit -F <commit-message-datei>
```

```
feat(smtp): Versand und Verbindungstest

STARTTLS / implizites TLS / unverschluesselt — fail-closed: ein
unbekannter security-Wert wirft, statt still im Klartext zu verbinden.
Zertifikatspruefung immer an, auch beim starttls-Kontext.

Eigener Fehlerklassifikator (auth/recipient/tls/server/offline). Drei
Details, die sonst falsch beim Nutzer ankommen: SMTPNotSupportedError ist
nicht immer TLS, SMTPRecipientsRefused hat kein smtp_code sondern ein
Dict, und SMTPServerDisconnected nach Timeout ist kein "offline".
```

---

### Task 4: Kontenspeicher (`src/smtp_store.py`)

**Files:**
- Create: `src/smtp_store.py`
- Modify: `.gitignore`
- Modify: `tests/test_type_annotations.py`
- Test: `tests/test_smtp_store.py`

**Interfaces:**
- Consumes: `smtp.SECURITY_MODES` (Task 3), `secure_file.harden_windows_acl` (Bestand)
- Produces:
  ```python
  SCHEMA_VERSION: int   # == 1
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
  **`delete` fasst den Schlüsselbund NICHT an** — das macht der Aufrufer (Task 7). Der Store bleibt reine Dateipersistenz und lässt sich ohne Zugriff auf den echten Credential Manager testen.

- [ ] **Step 1: `.gitignore` ergänzen — zuerst, nicht zuletzt**

Im Repo-Modus liegt `smtp.json` im Repo-Root, und die manuellen Prüfschritte späterer Tasks legen dort ein echtes Konto an. Im Datei-Fallback steht das Passwort im Klartext darin. Neben den `webhooks.json`-Zeilen ergänzen:

```
smtp.json
smtp.json.corrupt-*
.smtp-*.tmp
```

Run: `git check-ignore -v smtp.json`
Expected: eine Trefferzeile mit der neuen Regel.

- [ ] **Step 2: Write the failing test**

Neue Datei `tests/test_smtp_store.py`:

```python
"""Tests für den gerätelokalen SMTP-Kontenspeicher.

Spiegelt tests/test_webhook_store.py: Validierung, Quarantäne bei kaputter
Datei, Read-Only bei neuerer schema_version, Rollback bei Schreibfehlern,
Härtung auf der Temp-Datei.
"""

import json
import os
import threading

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


# --- validate_record -------------------------------------------------------

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
    ({"port": True}, "Port"),
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


def test_record_without_password_key_passes_and_is_not_mentioned():
    """Bei aktivem Schlüsselbund steht das Passwort gar nicht im Datensatz.
    validate_record darf es deshalb weder fordern noch erwähnen — die Regel
    „bei gesetztem Benutzer ist ein Passwort Pflicht" gehört in den Dialog."""
    candidate = _record(username="user@example.com")
    assert "password" not in candidate
    ok, msg = validate_record(candidate, [])
    assert ok
    assert "asswort" not in msg


def test_duplicate_name_is_rejected():
    existing = [_record(id="rec-0", name="Firma")]
    ok, msg = validate_record(_record(id="rec-1", name="firma"), existing)
    assert not ok
    assert "bereits" in msg


def test_renaming_itself_is_allowed():
    existing = [_record(id="rec-1", name="Firma")]
    ok, msg = validate_record(_record(id="rec-1", name="Firma"), existing)
    assert ok, msg


@pytest.mark.parametrize("field", ["from_addr", "recipient"])
def test_control_chars_in_addresses_are_rejected(field):
    ok, msg = validate_record(_record(**{field: "a@b\r\nBcc: c@d"}), [])
    assert not ok
    assert "Steuerzeichen" in msg


# --- Persistenz ------------------------------------------------------------

def test_save_and_reload(tmp_path):
    path = str(tmp_path / "smtp.json")
    SmtpStore(path).save(_record())
    assert [r["name"] for r in SmtpStore(path).get_all()] == ["Firma"]


def test_save_replaces_by_id(tmp_path):
    store = SmtpStore(str(tmp_path / "smtp.json"))
    store.save(_record())
    store.save(_record(name="Neu"))
    assert [r["name"] for r in store.get_all()] == ["Neu"]


def test_enabled_filters_disabled_accounts(tmp_path):
    store = SmtpStore(str(tmp_path / "smtp.json"))
    store.save(_record(id="a", name="An", enabled=True))
    store.save(_record(id="b", name="Aus", enabled=False))
    assert [r["name"] for r in store.enabled()] == ["An"]


def test_get_all_returns_a_copy(tmp_path):
    store = SmtpStore(str(tmp_path / "smtp.json"))
    store.save(_record())
    store.get_all()[0]["name"] = "manipuliert"
    assert store.get_all()[0]["name"] == "Firma"


def test_delete_removes_the_account(tmp_path):
    store = SmtpStore(str(tmp_path / "smtp.json"))
    store.save(_record())
    store.delete("rec-1")
    assert store.get_all() == []


def test_store_does_not_know_the_keyring_at_all():
    """Der Store bleibt reine Dateipersistenz; das Secret raeumt der Aufrufer
    ab (tab_smtp._remove). Sonst faesst jeder Test, der delete ruft, den
    echten Credential Manager der Entwicklermaschine an — und blockiert auf
    Linux womoeglich."""
    assert not hasattr(smtp_store, "keyring_store")


def test_lock_can_be_injected(tmp_path):
    lock = threading.RLock()
    store = SmtpStore(str(tmp_path / "smtp.json"), lock=lock)
    store.save(_record())
    assert store.get_all()[0]["id"] == "rec-1"


def test_failed_write_rolls_back_the_in_memory_list(tmp_path, monkeypatch):
    """Sonst zeigt die Liste den Eintrag, auf Platte steht nichts, und
    auffallen wuerde es erst nach dem Neustart."""
    store = SmtpStore(str(tmp_path / "smtp.json"))
    store.save(_record())

    def boom():
        raise OSError("Platte voll")

    monkeypatch.setattr(store, "_save_to_disk", boom)
    with pytest.raises(OSError):
        store.save(_record(id="rec-2", name="Zweite"))
    assert [r["id"] for r in store.get_all()] == ["rec-1"]


def test_hardening_runs_on_the_temp_file(tmp_path, monkeypatch):
    """chmod und icacls muessen auf der TEMP-Datei laufen: sonst gaebe es ein
    Fenster, in dem smtp.json schon am Zielpfad steht, aber noch die
    geerbten Rechte traegt."""
    seen = []
    monkeypatch.setattr(smtp_store, "harden_windows_acl", seen.append)
    path = str(tmp_path / "smtp.json")
    SmtpStore(path).save(_record())
    assert seen
    assert seen[0] != path
    assert os.path.basename(seen[0]).startswith(".smtp-")


# --- Laden, Quarantäne, Read-Only ------------------------------------------

def test_corrupt_file_is_quarantined(tmp_path):
    path = tmp_path / "smtp.json"
    path.write_text("{kein json", encoding="utf-8")
    store = SmtpStore(str(path))
    assert store.get_all() == []
    assert not path.exists()
    assert any(p.name.startswith("smtp.json.corrupt-") for p in tmp_path.iterdir())


def test_newer_schema_version_is_read_only(tmp_path):
    path = tmp_path / "smtp.json"
    path.write_text(json.dumps(
        {"schema_version": smtp_store.SCHEMA_VERSION + 1, "accounts": []}),
        encoding="utf-8")
    store = SmtpStore(str(path))
    with pytest.raises(SmtpStoreReadOnly):
        store.save(_record())


def test_unreadable_file_is_not_quarantined(tmp_path, monkeypatch):
    """Ein kurzzeitig gesperrtes File (Virenscanner, Backup) ist kein
    defektes File — die Konfiguration samt Passwoertern darf nicht wegfliegen."""
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
        _record(id="gut", name="Gut"),
        {"id": "kaputt"},
        "kein dict",
    ]}), encoding="utf-8")
    assert [r["id"] for r in SmtpStore(str(path)).get_all()] == ["gut"]


def test_record_with_unknown_security_is_skipped_on_load(tmp_path):
    """Der wichtigste Ladetest: validate_record laeuft beim Laden NIE, und
    smtp._open verbindet bei einem unbekannten Wert gar nicht erst. Ein
    solcher Datensatz darf deshalb erst gar nicht in der Ziel-Auswahl
    erscheinen — dasselbe Muster, das webhook_store fuer die URL faehrt."""
    path = tmp_path / "smtp.json"
    path.write_text(json.dumps({"schema_version": 1, "accounts": [
        _record(id="gut", name="Gut"),
        _record(id="boese", name="Boese", security="TLS"),
    ]}), encoding="utf-8")
    assert [r["id"] for r in SmtpStore(str(path)).get_all()] == ["gut"]


def test_saved_file_is_not_world_readable(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX-Modusbits gibt es unter Windows nicht; dort greift "
                    "harden_windows_acl (s. test_hardening_runs_on_the_temp_file)")
    path = str(tmp_path / "smtp.json")
    SmtpStore(path).save(_record())
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_smtp_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.smtp_store'`

- [ ] **Step 4: Write the implementation**

Neue Datei `src/smtp_store.py`. Der Aufbau spiegelt `src/webhook_store.py` — beim Schreiben dort nachsehen und die Struktur (Laden, `_quarantine`, `_save_to_disk` mit chmod/icacls/Retry, Rollback in `save`/`delete`) **übernehmen**, statt sie neu zu erfinden. Was hier abweicht, steht unten explizit.

```python
"""Gerätelokale Persistenz der SMTP-Konten (Tk-frei, stdlib-only).

`smtp.json` liegt neben `token.json` im Datenverzeichnis. Sie enthält
Konfiguration und — wenn kein Schlüsselbund verfügbar ist — auch Passwörter,
und wird deshalb wie `token.json` und `webhooks.json` gehärtet geschrieben
(chmod 0600 + icacls auf der Temp-Datei, dann os.replace). Der vierte
Secret-Schreibpfad der App, siehe src/CLAUDE.md.

Nichts hiervon reist per Drive-Sync und nichts steht im Share-Doc: SMTP-Konten
sind bewusst gerätelokal, damit kein Secret im Sync-Doc landet — dieselbe
Begründung wie bei den Webhooks.

Der Store fasst den Schlüsselbund NICHT an. Das Secret zu einem gelöschten
Konto räumt der Aufrufer ab (`tab_smtp._remove`), damit dieses Modul reine
Dateipersistenz bleibt und ohne Zugriff auf den echten Credential Manager
testbar ist.
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

from src.secure_file import harden_windows_acl
from src.smtp import SECURITY_MODES

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

Account = dict[str, Any]

_REQUIRED_KEYS = ("id", "name", "enabled", "host", "port", "security",
                  "username", "from_addr", "recipient", "password_location")
_FORBIDDEN_CHARS = ("\r", "\n", "\x00")


class SmtpStoreReadOnly(Exception):
    """Die Datei darf nicht überschrieben werden (neuere schema_version oder
    beim Start nicht lesbar). Der Aufrufer zeigt das als themed Fehlerdialog —
    ein still verworfener Speichervorgang wäre schlimmer als ein Fehler."""


def new_id() -> str:
    """Stabile Kennung eines Kontos. Trägt die Zuordnung — im Store UND als
    Keyring-Account —, wenn der Nutzer den Namen ändert."""
    return uuid.uuid4().hex


def _is_wellformed(record: Any) -> bool:
    """Strukturprüfung fürs Laden — schwächer als validate_record, aber NICHT
    wertfrei.

    `security` wird mitgeprüft, und das ist keine Kosmetik: `validate_record`
    läuft beim Laden nie, und `smtp._open` weist einen unbekannten Wert zwar
    ab, aber erst beim Senden. Ein solcher Datensatz soll gar nicht erst in
    der Ziel-Auswahl erscheinen — dasselbe Muster, das `webhook_store` für die
    URL fährt („sonst erschiene ein Eintrag mit kaputter oder unsicherer
    Adresse in der Ziel-Auswahl und scheiterte erst beim Senden").
    """
    if not isinstance(record, dict):
        return False
    if any(k not in record for k in _REQUIRED_KEYS):
        return False
    return record.get("security") in SECURITY_MODES


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
    """Analog `WebhookStore`; Details dort nachlesen.

    Wie dieser bekommt der Store **keinen** geteilten Daten-Lock injiziert
    (`main.py`): SMTP-Konten nehmen an keinem Sync-Flow teil, es gibt also
    keine übergreifende Invariante zu wahren — und `save`/`delete` halten den
    Lock über den icacls-Subprozess (timeout 15 s) plus bis zu vier Retries.
    """

    def __init__(self, filepath: str = "smtp.json",
                 lock: threading.RLock | None = None) -> None:
        ...   # wie WebhookStore.__init__, Feld heißt self._accounts

    def _load(self) -> None:
        ...   # wie WebhookStore._load; Datenschlüssel "accounts" statt
              # "webhooks", Dateiname in allen Meldungen "smtp.json".
              # OSError -> self._readonly = True, KEINE Quarantäne.
              # NIEMALS den Datensatz loggen (Datei-Fallback = Passwort!),
              # nur id und name.

    def _quarantine(self, reason: str) -> None:
        ...   # wie WebhookStore._quarantine

    def _save_to_disk(self) -> None:
        ...   # wie WebhookStore._save_to_disk; payload
              # {"schema_version": SCHEMA_VERSION, "accounts": self._accounts},
              # tempfile-Prefix ".smtp-", SmtpStoreReadOnly statt
              # WebhookStoreReadOnly

    def get_all(self) -> list[Account]:
        ...   # deepcopy unter Lock

    def enabled(self) -> list[Account]:
        ...   # deepcopy der aktivierten

    def save(self, record: Account) -> None:
        ...   # wie WebhookStore.save inkl. Rollback

    def delete(self, account_id: str) -> None:
        ...   # wie WebhookStore.delete inkl. Rollback — und OHNE
              # Keyring-Zugriff (s. Modul-Docstring)
```

**Der Implementierende schreibt die mit `...` markierten Rümpfe aus, indem er `src/webhook_store.py` daneben legt.** Das ist bewusst kein Copy-Paste-Block im Plan: die Vorlage ist 150 Zeilen mit Kommentaren, die zu Wort und Zeichen übernommen gehören (Retry-Begründung, Quarantäne-Regel, `deepcopy`-Begründung). Abweichungen sind ausschließlich die oben genannten.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_smtp_store.py -v`
Expected: PASS

- [ ] **Step 6: Modul in die Annotations-Whitelist eintragen**

In `tests/test_type_annotations.py`, in `ANNOTATED_MODULES` nach `"src/conflicts_store.py"`:

```python
    "src/smtp_store.py",
```

- [ ] **Step 7: Lint, Typecheck, volle Suite**

Run: `ruff check .`
Run: `npx pyright`
Run: `pytest`

- [ ] **Step 8: Commit**

```bash
git add src/smtp_store.py tests/test_smtp_store.py tests/test_type_annotations.py .gitignore
git commit -F <commit-message-datei>
```

```
feat(smtp): geraetelokaler Kontenspeicher

smtp.json neben token.json, geschrieben wie webhooks.json: chmod 0600 +
icacls auf der Temp-Datei, dann os.replace. Quarantaene bei kaputter
Datei, Read-Only bei neuerer schema_version, Rollback bei
Schreibfehlern.

_is_wellformed prueft security mit — validate_record laeuft beim Laden
nie, und ein Datensatz mit unbekanntem Modus soll gar nicht erst in der
Ziel-Auswahl erscheinen (Muster wie die URL-Pruefung im webhook_store).

.gitignore deckt smtp.json, Quarantaene-Kopien und Temp-Dateien ab: im
Datei-Fallback steht dort ein Klartext-Passwort.
```

---

### Task 5: SMTP als dritter Kanaltyp im Dispatcher

**Files:**
- Modify: `src/dialogs/send_task.py` (Modul-Docstring, Importe, `needs_pdf`, `perform_send`, `_KIND_TEXTS`, neue Funktion `_send_smtp`)
- Test: `tests/test_send_task_dispatch.py`

**Interfaces:**
- Consumes: `smtp.send` / `classify_smtp_error` (Task 3), `keyring_store.get_secret` (Task 2)
- Produces: `perform_send(..., smtp_accounts: list[dict] | None = None, ...)` — liefert je Konto ein Result `{"channel": "smtp", "name": "<Konto> (<Empfänger>)", "ok": bool, ...}` in `res["results"]`.

- [ ] **Step 1: Write the failing test**

An `tests/test_send_task_dispatch.py` anhängen. **Die Datei hat kein `settings`-Fixture und keine Modulkonstanten** — sie arbeitet mit dem Builder `_kwargs(**over)` und `_FakeSettings`; die neuen Tests benutzen genau das:

```python
def _account(**over):
    base = {
        "id": "rec-1", "name": "Firma", "enabled": True,
        "host": "mail.example.com", "port": 587, "security": "starttls",
        "username": "user@example.com", "from_addr": "user@example.com",
        "recipient": "buchhaltung@example.com",
        "password_location": "keyring",
    }
    base.update(over)
    return base


def test_smtp_account_is_sent_with_pdf(monkeypatch):
    sent = []
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")
    monkeypatch.setattr(st.keyring_store, "get_secret", lambda record: "geheim")
    monkeypatch.setattr(st.smtp, "send",
                        lambda record, password, **kw: sent.append((record, password, kw)))

    res = perform_send(**_kwargs(send_mail=False, smtp_accounts=[_account()]))

    assert [r["ok"] for r in res["results"]] == [True]
    assert res["results"][0]["channel"] == "smtp"
    record, password, kw = sent[0]
    assert password == "geheim"
    assert kw["attachment_bytes"] == b"PDF"
    assert kw["attachment_filename"] == "r.pdf"
    assert kw["subject"] == "Subj"


def test_smtp_result_name_shows_the_recipient(monkeypatch):
    """Bei genau einem Ergebnis meldet der Dialog „wurde an {name} gesendet" —
    dort stand bisher immer eine Adresse, nie ein Kontoname."""
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")
    monkeypatch.setattr(st.keyring_store, "get_secret", lambda record: "geheim")
    monkeypatch.setattr(st.smtp, "send", lambda *a, **k: None)

    res = perform_send(**_kwargs(send_mail=False, smtp_accounts=[_account()]))
    assert res["results"][0]["name"] == "Firma (buchhaltung@example.com)"


def test_smtp_failure_does_not_stop_the_other_channels(monkeypatch):
    import smtplib

    _patch_mail_ok(monkeypatch)
    monkeypatch.setattr(st.keyring_store, "get_secret", lambda record: "geheim")

    def boom(record, password, **kw):
        raise smtplib.SMTPAuthenticationError(535, b"nope")

    monkeypatch.setattr(st.smtp, "send", boom)

    res = perform_send(**_kwargs(smtp_accounts=[_account()]))

    by_channel = {r["channel"]: r for r in res["results"]}
    assert by_channel["mail"]["ok"] is True
    assert by_channel["smtp"]["ok"] is False
    assert by_channel["smtp"]["kind"] == "auth"


def test_pdf_failure_takes_smtp_down_but_json_webhooks_survive(monkeypatch):
    """SMTP haengt die PDF an wie der Mail-Kanal — ohne sie kann es nicht
    senden. JSON-Webhooks brauchen sie nicht und laufen weiter."""
    def boom(*a, **k):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(st, "generate_pdf", boom)
    monkeypatch.setattr(st.webhook, "build_json_payload", lambda **k: {"x": 1})
    monkeypatch.setattr(st.webhook, "deliver",
                        lambda *a, **k: {"ok": True, "status": 200})

    res = perform_send(**_kwargs(
        send_mail=False, webhooks=[_hook()], smtp_accounts=[_account()]))

    by_channel = {r["channel"]: r for r in res["results"]}
    assert by_channel["smtp"]["ok"] is False
    assert by_channel["webhook"]["ok"] is True


def test_smtp_without_mail_data_fails_instead_of_sending_an_empty_mail(monkeypatch):
    """Der Dialog liefert Betreff und HTML, sobald Konten gewaehlt sind. Faellt
    das je aus (direkter Aufruf, uebersehener Zweig beim Refactor), darf der
    Dispatcher NICHT still eine Mail mit leerem Betreff und leerem Body
    verschicken — und ein mail["subject"] waere ein KeyError ausserhalb jedes
    try: der Runner schluckt ihn, on_done feuert nie, der Dialog steht
    dauerhaft auf „Sende…"."""
    sent = []
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")
    monkeypatch.setattr(st.keyring_store, "get_secret", lambda record: "geheim")
    monkeypatch.setattr(st.smtp, "send", lambda *a, **k: sent.append(1))

    res = perform_send(**_kwargs(
        send_mail=False, mail=None, smtp_accounts=[_account()]))

    assert sent == []
    assert [r["ok"] for r in res["results"]] == [False]
    assert res["results"][0]["channel"] == "smtp"


def test_smtp_accounts_default_to_empty(monkeypatch):
    """Bestandsaufrufer ohne den neuen Parameter laufen unveraendert."""
    _patch_mail_ok(monkeypatch)
    res = perform_send(**_kwargs())
    assert [r["channel"] for r in res["results"]] == ["mail"]


def test_kind_texts_cover_the_new_smtp_kinds():
    """Sonst stuende im Ergebnis-Dialog nur „Fehler"."""
    from src.dialogs.send_task import _KIND_TEXTS
    assert "recipient" in _KIND_TEXTS
    assert "tls" in _KIND_TEXTS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_send_task_dispatch.py -v`
Expected: FAIL — `TypeError: perform_send() got an unexpected keyword argument 'smtp_accounts'`

- [ ] **Step 3: Implementierung in `src/dialogs/send_task.py`**

Modul-Docstring: „Dispatcher über zwei Kanaltypen: Gmail und beliebig viele Webhooks." → „Dispatcher über drei Kanaltypen: Gmail, beliebig viele SMTP-Konten und beliebig viele Webhooks."

Import ersetzen:

```python
from src import keyring_store, smtp, webhook
```

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

Neue Kanalfunktion hinter `_send_mail`:

```python
def _account_label(record):
    """Kontoname plus Empfänger. Bei genau einem Ergebnis meldet der Dialog
    „Bericht wurde an {name} gesendet" — dort stand bisher immer eine
    Adresse, und ein nackter Kontoname wäre ein Rückschritt."""
    recipient = record.get("recipient") or ""
    name = record.get("name") or ""
    return f"{name} ({recipient})" if recipient else name


def _send_smtp(*, record, subject, html, pdf_bytes, pdf_filename):
    """Ein SMTP-Konto. Wirft nie — wie jeder Kanal des Dispatchers.

    Das Passwort wird HIER geholt, nicht im Dialog: der Schlüsselbund kann auf
    Linux blockieren, und `keyring_store` bringt dafür seinen eigenen Watchdog
    mit. Im Tk-Callback fröre das die Oberfläche ein.
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

`perform_send`: Signatur um `smtp_accounts=None` erweitern (hinter `webhooks`, vor `pdf_filename`). Direkt hinter der bestehenden `send_mail`/`mail`-Normalisierung die symmetrische Prüfung ergänzen:

```python
    smtp_accounts = list(smtp_accounts or [])

    # Dieselbe Begründung wie bei der send_mail-Normalisierung darüber: der
    # Vertrag lautet „wirft nie". Ein Zugriff mail["subject"] ohne mail-Dict
    # wäre ein KeyError AUSSERHALB jedes try — BackgroundTaskRunner.run fängt
    # ihn, ruft `on_done` nie, und der Sende-Dialog bleibt dauerhaft auf
    # „Sende…" stehen. Und still eine Mail mit leerem Betreff und leerem Body
    # zu verschicken wäre die schlechtere Alternative.
    if smtp_accounts and not (mail and mail.get("subject") and mail.get("html")):
        log.error("perform_send: SMTP-Konten ohne Betreff/HTML — "
                  "Kanal wird übersprungen")
        for record in smtp_accounts:
            results.append({
                "channel": "smtp", "name": _account_label(record),
                "ok": False, "kind": "config",
                "detail": "Betreff und Inhalt fehlen.", "error": None,
                "tb": None})
        smtp_accounts = []
```

PDF-Block: `needs_pdf(send_mail, webhooks, smtp_accounts)`, und im Fehlerzweig zwischen Mail- und Webhook-Behandlung ergänzen:

```python
            # SMTP hängt die PDF an wie der Mail-Kanal — ohne sie kann kein
            # Konto senden.
            for record in smtp_accounts:
                results.append({"channel": "smtp",
                                "name": _account_label(record), **failure})
            smtp_accounts = []
```

Nach dem `if send_mail:`-Block:

```python
    for record in smtp_accounts:
        # mail ist hier garantiert vollständig — die Normalisierung oben hat
        # smtp_accounts sonst geleert.
        assert mail is not None
        res = _send_smtp(record=record, subject=mail["subject"],
                         html=mail["html"], pdf_bytes=pdf_bytes,
                         pdf_filename=pdf_filename)
        results.append({"channel": "smtp",
                        "name": _account_label(record), **res})
```

`_KIND_TEXTS` erweitern:

```python
    "recipient": "Empfänger oder Absender wurde abgelehnt",
    "tls": "Verschlüsselung fehlgeschlagen",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_send_task_dispatch.py tests/test_send_task.py -v`
Expected: PASS

- [ ] **Step 5: Lint, Typecheck, volle Suite** — `ruff check .`, `npx pyright`, `pytest`

- [ ] **Step 6: Commit**

```bash
git add src/dialogs/send_task.py tests/test_send_task_dispatch.py
git commit -F <commit-message-datei>
```

```
feat(send): SMTP als dritter Kanaltyp im Dispatcher

perform_send feuert jetzt Gmail, n SMTP-Konten und n Webhooks
unabhaengig voneinander. Die PDF entsteht weiterhin genau einmal;
faellt sie aus, faellt SMTP mit dem Mail-Kanal aus, die JSON-Webhooks
laufen weiter.

Symmetrisch zur send_mail-Normalisierung: SMTP-Konten ohne Betreff/HTML
liefern ein Failure-Result, statt still eine leere Mail zu verschicken —
ein mail["subject"] waere ein KeyError ausserhalb jedes try, und der
Dialog bliebe auf "Sende..." stehen.

Das Passwort holt der Worker, nicht der Dialog.
```

---

### Task 6: Teilen über SMTP (`share_task`)

**Files:**
- Modify: `src/dialogs/share_task.py`
- Test: `tests/test_share_task.py`

**Interfaces:**
- Consumes: `smtp.send` / `classify_smtp_error` (Task 3), `keyring_store.get_secret` (Task 2)
- Produces: `perform_share(..., transport: dict | None = None)` — `None` heißt Gmail wie bisher, sonst ein SMTP-Record. Der Empfänger kommt in **beiden** Fällen aus dem `recipient`-Parameter.

- [ ] **Step 1: Write the failing test**

An `tests/test_share_task.py` anhängen. Auch diese Datei arbeitet mit `_kwargs(**over)` und `_FakeSettings`:

```python
def _account(**over):
    base = {
        "id": "rec-1", "name": "Firma", "enabled": True,
        "host": "mail.example.com", "port": 587, "security": "starttls",
        "username": "user@example.com", "from_addr": "user@example.com",
        "recipient": "buchhaltung@example.com",
        "password_location": "keyring",
    }
    base.update(over)
    return base


def _must_not_run(*args, **kwargs):
    raise AssertionError("Der Gmail-Pfad darf beim SMTP-Versand nicht laufen.")


def test_share_over_smtp_uses_the_account(monkeypatch):
    sent = []
    monkeypatch.setattr(st, "get_gmail_service", _must_not_run)
    monkeypatch.setattr(st.keyring_store, "get_secret", lambda record: "geheim")
    monkeypatch.setattr(st.smtp, "send",
                        lambda record, password, **kw: sent.append((record, kw)))

    res = perform_share(**_kwargs(transport=_account()))

    assert res == {"ok": True}
    record, kw = sent[0]
    assert record["name"] == "Firma"
    assert kw["attachment_subtype"] == "json"
    assert kw["attachment_filename"] == "share.json"


def test_share_over_smtp_sends_to_the_dialog_recipient(monkeypatch):
    """Der Teilen-Dialog fragt nach einer Adresse; das recipient-Feld des
    Kontos ist semantisch etwas anderes (wohin dieses Konto den BERICHT
    schickt). Ein sichtbares, ausgefuelltes Feld, das ignoriert wird, waere
    eine Falle: das Share-JSON ginge an jemand anderen als angezeigt."""
    sent = {}
    monkeypatch.setattr(st.keyring_store, "get_secret", lambda record: "geheim")
    monkeypatch.setattr(st.smtp, "send",
                        lambda record, password, **kw: sent.update(kw))

    perform_share(**_kwargs(recipient="kollege@example.com",
                            transport=_account()))

    assert sent["to"] == "kollege@example.com"


def test_share_over_smtp_classifies_errors(monkeypatch):
    import smtplib

    monkeypatch.setattr(st.keyring_store, "get_secret", lambda record: "geheim")

    def boom(record, password, **kw):
        raise smtplib.SMTPAuthenticationError(535, b"nope")

    monkeypatch.setattr(st.smtp, "send", boom)

    res = perform_share(**_kwargs(transport=_account()))
    assert res["ok"] is False
    assert res["kind"] == "auth"
    assert res["tb"] is None


def test_share_over_smtp_saves_the_default_recipient(monkeypatch):
    """save_default gehoert zum Eingabefeld, nicht zum Transport — es muss
    auch ueber SMTP greifen."""
    monkeypatch.setattr(st.keyring_store, "get_secret", lambda record: "geheim")
    monkeypatch.setattr(st.smtp, "send", lambda *a, **k: None)
    settings = _FakeSettings()

    perform_share(**_kwargs(transport=_account(), save_default=True,
                            settings=settings))

    assert settings.sets == [("share_recipient", "to@example.com")]


def test_share_without_transport_still_uses_gmail(monkeypatch):
    """Bestandsverhalten: transport=None ist der Gmail-Weg."""
    sent = {}
    _patch_happy(monkeypatch, sent)
    res = perform_share(**_kwargs())
    assert res == {"ok": True}
    assert sent["to"] == "to@example.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_share_task.py -v`
Expected: FAIL — `TypeError: perform_share() got an unexpected keyword argument 'transport'`

- [ ] **Step 3: Implementierung — vollständige neue Fassung von `src/dialogs/share_task.py`**

```python
"""Worker-Kern des Teilen-Dialogs (Audit M10): Tk-frei, wirft nie.

Der Share-Doc-Bau + die Serialisierung laufen auf dem UI-Thread (schnell,
Klick-Zeit-Snapshot); dieser Worker bekommt den fertigen `payload` und
erledigt nur den blockierenden Teil: Transport aufbauen (evtl. OAuth oder
Schlüsselbund-Zugriff) + senden + optional Standard-Empfänger persistieren.

`transport=None` ist der Gmail-Weg; ein SMTP-Record schickt stattdessen über
dieses Konto. Der Empfänger kommt in **beiden** Fällen aus `recipient`, also
aus dem Eingabefeld des Dialogs — das `recipient`-Feld eines SMTP-Kontos
bezeichnet etwas anderes (wohin dieses Konto den Bericht schickt).
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
            recipient=recipient, subject=subject, html=html)

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


def _share_via_smtp(*, record, payload, filename, recipient, subject, html):
    try:
        password = keyring_store.get_secret(record)
        smtp.send(record, password, subject=subject, html=html, to=recipient,
                  attachment_bytes=payload,
                  attachment_filename=filename,
                  attachment_subtype="json")
    except Exception as e:
        log.exception("Teilen über SMTP-Konto %r fehlgeschlagen",
                      record.get("name"))
        return smtp.classify_smtp_error(e)
    return {"ok": True}
```

**Achtung:** die bestehenden Tests der Datei patchen `st.classify_mail_error` als Modul-Global — der Import oben bleibt deshalb genau so stehen.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_share_task.py -v`
Expected: PASS

- [ ] **Step 5: Lint, Typecheck, volle Suite** — `ruff check .`, `npx pyright`, `pytest`

- [ ] **Step 6: Commit**

```bash
git add src/dialogs/share_task.py tests/test_share_task.py
git commit -F <commit-message-datei>
```

```
feat(share): Teilen ueber ein SMTP-Konto

perform_share bekommt einen transport-Parameter: None ist der Gmail-Weg
wie bisher, ein SMTP-Record schickt ueber dieses Konto. Der Empfaenger
bleibt in beiden Faellen das Eingabefeld des Dialogs — das
recipient-Feld eines Kontos bezeichnet etwas anderes.
```

---

### Task 7: Einstellungen — Tab „SMTP" und Konto-Dialog

Reine Tk-Schicht, daher ohne automatisierte Tests (Scope-Grenze M16). Die gesamte Fallunterscheidung ums Passwort liegt bereits in `keyring_store.persist_password` (Task 2) und ist dort getestet — hier wird sie nur aufgerufen.

**Files:**
- Create: `src/dialogs/smtp_dialog.py`
- Create: `src/dialogs/settings_dialog/tab_smtp.py`
- Modify: `src/dialogs/settings_dialog/dialog.py`

**Interfaces:**
- Consumes: `smtp_store` (Task 4), `smtp.test_connection`/`classify_smtp_error` (Task 3), `keyring_store.persist_password`/`get_secret`/`delete_secret` (Task 2), `send_task.format_result_summary` (Task 5)
- Produces:
  ```python
  open_smtp_dialog(parent, store, runner, record: dict | None = None,
                   on_saved=None) -> None
  class SmtpTab:
      def __init__(self, frame, dialog, store, runner, parent=None) -> None: ...
      def refresh(self) -> None: ...
  ```

- [ ] **Step 1: Konto-Dialog anlegen**

Neue Datei `src/dialogs/smtp_dialog.py`. Vorbild ist `src/dialogs/webhook_dialog.py` — vor dem Schreiben lesen und dessen Struktur (busy-Flags, Runner-Nutzung, `on_done` bei inzwischen geschlossenem Dialog) übernehmen:

```python
"""Anlegen und Bearbeiten eines SMTP-Kontos, inklusive Verbindungstest.

Reine Tk-Schicht: Validierung (`smtp_store.validate_record`), Verbindungstest
(`smtp.test_connection`) und die Passwort-Zustandslogik
(`keyring_store.persist_password`) liegen Tk-frei in den pure Modulen und sind
dort getestet.
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

# Warum das hier steht und nicht in der Doku: ohne diesen Hinweis liest sich
# das „535 Authentication unsuccessful" von Microsoft wie ein Tippfehler, und
# der Nutzer sucht stundenlang am falschen Ende.
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
    stored = record                      # der gespeicherte Stand, oder None
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

    row = 0
    for text, var, masked in (
        ("Name:", name_var, False),
        ("Server:", host_var, False),
        ("Port:", port_var, False),
    ):
        _label(text, row, pady=(14, 6) if row == 0 else 6)
        dark_entry(dialog, var, width=32).grid(
            row=row, column=1, padx=10,
            pady=(14, 6) if row == 0 else 6, sticky="w")
        row += 1

    _label("Verschlüsselung:", row)
    dark_combo(dialog, security_var,
               [lbl for _, lbl in SECURITY_LABELS], width=32).grid(
        row=row, column=1, padx=10, pady=6, sticky="w")
    row += 1

    for text, var, masked in (
        ("Benutzer:", username_var, False),
        ("Passwort:", password_var, True),
        ("Absender:", from_var, False),
        ("Empfänger:", recipient_var, False),
    ):
        _label(text, row)
        entry = dark_entry(dialog, var, width=32)
        if masked:
            entry.config(show="•")
        entry.grid(row=row, column=1, padx=10, pady=6, sticky="w")
        row += 1

    if not is_new:
        location = record.get("password_location")
        stored_text = ("Passwort liegt im Schlüsselbund des Betriebssystems."
                       if location == "keyring" else
                       "Kein Schlüsselbund verfügbar — das Passwort liegt "
                       "lokal in smtp.json.")
        tk.Label(dialog, text=f"{stored_text}  Leer lassen = unverändert.",
                 font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, justify="left",
                 wraplength=380).grid(row=row, column=0, columnspan=2,
                                      padx=10, pady=(0, 4), sticky="w")
        row += 1

    tk.Checkbutton(
        dialog, text="Aktiv", variable=enabled_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG, activebackground=BG,
        activeforeground=TEXT, cursor="hand2",
    ).grid(row=row, column=0, columnspan=2, padx=10, pady=(4, 2), sticky="w")
    row += 1

    # wraplength ist Pflicht, nicht Kosmetik: ohne sie wird das Label so breit
    # wie seine längste Zeile und zieht den ganzen Dialog mit. 380 ist der im
    # Projekt übliche Wert.
    for hint in (STORAGE_HINT, PROVIDER_HINT):
        tk.Label(dialog, text=hint, font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
                 justify="left", wraplength=380).grid(
            row=row, column=0, columnspan=2, padx=10, pady=(6, 2), sticky="w")
        row += 1

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
        # icacls-Subprozess (timeout=15), und der Schlüsselbund kann auf Linux
        # blockieren. Im Tk-Callback fröre beides die Oberfläche ein.
        def fn():
            to_save = keyring_store.persist_password(candidate, password,
                                                     stored=stored)
            try:
                store.save(to_save)
            except (smtp_store.SmtpStoreReadOnly, OSError) as e:
                # Kompensation: das Secret steht schon im Schlüsselbund, der
                # Datensatz aber nirgends. Bei einem NEUEN Konto bliebe es
                # dort für immer unter einer id, die in keiner Datei mehr
                # steht — unauffindbar und unlöschbar. Beim Bearbeiten NICHT
                # kompensieren: dort existiert der Datensatz weiter, und das
                # frisch geschriebene Passwort ist das, was der Nutzer wollte.
                if is_new and password and \
                        to_save.get("password_location") == "keyring":
                    keyring_store.delete_secret(to_save["id"])
                return {"ok": False, "error": e}
            return {"ok": True,
                    "fell_back": bool(password)
                    and to_save.get("password_location") == "file"}

        def on_done(res):
            alive = dialog.winfo_exists()
            if res["ok"]:
                if alive:
                    dialog.destroy()
                if on_saved:
                    on_saved()
                # Nur wenn tatsächlich ein Passwort geschrieben wurde — sonst
                # feuerte der Hinweis bei jedem Speichern einer Namensänderung.
                if res["fell_back"]:
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
            password = typed_password
            if not password and stored is not None:
                password = keyring_store.get_secret(stored)
            try:
                smtp.test_connection(candidate, password)
            except Exception as e:
                return smtp.classify_smtp_error(e)
            return {"ok": True, "checked_login": bool(candidate["username"])}

        def on_done(res):
            busy["testing"] = False
            if not dialog.winfo_exists():
                return
            set_secondary_button_enabled(test_btn, True)
            if res.get("ok"):
                # Ohne Benutzer wurde keine einzige Zugangsdatei geprüft —
                # nur, dass der Server erreichbar ist und NOOP beantwortet.
                message = ("Der Server hat die Zugangsdaten akzeptiert."
                           if res["checked_login"] else
                           "Der Server ist erreichbar. Zugangsdaten wurden "
                           "nicht geprüft, weil kein Benutzer eingetragen ist.")
                themed_showinfo(dialog, "Verbindung erfolgreich",
                                f"{message} Es wurde keine E-Mail verschickt.")
                return
            from src.dialogs.send_task import format_result_summary
            themed_showerror(
                dialog, "Verbindung fehlgeschlagen",
                format_result_summary(
                    [{"name": candidate["name"], "ok": False,
                      "kind": res.get("kind"), "detail": res.get("detail")}]))

        runner.run(fn, on_done)

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=row, column=0, columnspan=2, pady=14)
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

Neue Datei `src/dialogs/settings_dialog/tab_smtp.py`, Vorbild `tab_webhooks.py`. Der Aufbau (Hinweistext mit `wraplength=380`, Listbox mit derselben Palette wie im ConflictsDialog, drei Buttons, `refresh`/`_selected`/`_add`/`_edit`/`_remove`) wird von dort übernommen. Abweichungen:

- Hinweistext:
  ```python
  ("Berichte können statt über die Gmail-API auch über einen eigenen "
   "Mail-Server verschickt werden. Jedes Konto hat seinen eigenen Empfänger "
   "und lässt sich beim Senden einzeln auswählen. Konten gelten nur auf "
   "diesem Gerät und werden sofort gespeichert — unabhängig vom „Abbrechen“ "
   "dieses Einstellungen-Dialogs.")
  ```
- Listenzeile: `f"  {mark}  {record.get('name', '')}  —  {record.get('host', '?')}"`
- `_remove` räumt **zusätzlich zum Store das Keyring-Secret ab** — der Store tut das bewusst nicht:

  ```python
      def _remove(self):
          record = self._selected()
          if record is None:
              return
          if not themed_askyesno(
                  self._dialog, "SMTP-Konto entfernen",
                  f"„{record.get('name', '')}“ wirklich entfernen?"):
              return

          # Über den Runner: delete schreibt die Datei neu (icacls-Subprozess,
          # bis zu 15 s), und delete_secret kann auf Linux blockieren.
          def fn():
              try:
                  self._store.delete(record["id"])
              except (smtp_store.SmtpStoreReadOnly, OSError) as e:
                  return {"ok": False, "error": e}
              # Erst NACH dem erfolgreichen Schreiben: sonst stünde ein Konto
              # ohne Passwort in der Datei. Der Store selbst fasst den
              # Schlüsselbund nicht an, damit er reine Dateipersistenz bleibt.
              keyring_store.delete_secret(record["id"])
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

Importe entsprechend: `from src import keyring_store, smtp_store` und `from src.dialogs.smtp_dialog import open_smtp_dialog`.

- [ ] **Step 3: Tab in den Einstellungen-Dialog einhängen — hinter „Webhooks"**

In `src/dialogs/settings_dialog/dialog.py`:

- Import nach `from src.dialogs.settings_dialog.tab_mail import MailTab`:
  ```python
  from src.dialogs.settings_dialog.tab_smtp import SmtpTab
  ```
- `open_settings_dialog` bekommt den Keyword-Parameter `smtp_store=None` (neben `webhook_store`).
- Frame **nach** `tab_webhooks = tk.Frame(notebook, bg=BG)`:
  ```python
      tab_smtp = tk.Frame(notebook, bg=BG)
  ```
- `notebook.add` **nach** `notebook.add(tab_webhooks, text="Webhooks")`:
  ```python
      notebook.add(tab_smtp, text="SMTP")
  ```
- Instanziierung nach `hooks = WebhooksTab(...)`, **ohne Zuweisung** — der Tab speichert selbst, und eine ungenutzte lokale Variable ist `ruff` F841 (in `pyproject.toml` über `"F"` aktiv):
  ```python
      SmtpTab(tab_smtp, dialog, smtp_store, runner, parent)
  ```
- Modul-Docstring korrigieren: „aufgeteilt auf **sechs** Tabs (Arbeitszeit / Bericht & Mail / Webhooks / Google / App / Updates)" → sieben, mit SMTP hinter Webhooks.

- [ ] **Step 4: Lint, Typecheck, volle Suite** — `ruff check .`, `npx pyright`, `pytest`

Die Tests importieren `src.ui`; ein Importfehler in den neuen Modulen fiele hier auf.

- [ ] **Step 5: App starten und den Tab von Hand prüfen**

Run: `python -m src.main`

- ⚙ → der Tab „SMTP" steht **hinter** „Webhooks".
- „Hinzufügen" → Speichern ohne Namen zeigt „Bitte einen Namen angeben."
- Benutzer ohne Passwort beim Neuanlegen → „Bitte ein Passwort angeben."
- Vollständiges Konto speichern → erscheint in der Liste.
- „Bearbeiten" → Passwortfeld leer, darunter die Zeile, wo das Passwort liegt.
- Nur den Namen ändern und speichern → **kein** Hinweis „Passwort lokal gespeichert", und der Versand funktioniert danach weiter (das Passwort darf nicht verschwinden).
- „Entfernen" fragt nach.

- [ ] **Step 6: Verbindungstest gegen einen echten Server**

Ein echtes Konto eintragen (GMX, Web.de, IONOS oder Gmail mit App-Passwort) und „Verbindung testen" drücken. Erwartet: „Der Server hat die Zugangsdaten akzeptiert. Es wurde keine E-Mail verschickt."

Gegenprobe mit falschem Passwort: „Zugangsdaten wurden abgelehnt" plus die Serverantwort — **kein** Traceback-Dialog.

- [ ] **Step 7: Commit**

```bash
git add src/dialogs/smtp_dialog.py src/dialogs/settings_dialog/tab_smtp.py src/dialogs/settings_dialog/dialog.py
git commit -F <commit-message-datei>
```

```
feat(settings): Tab „SMTP" mit Konto-Dialog und Verbindungstest

Liste plus Bearbeiten-Dialog nach dem Vorbild der Webhooks, hinter dem
Webhooks-Tab. Passwortfeld bleibt beim Bearbeiten leer (leer =
unveraendert); die Zustandslogik dahinter liegt in
keyring_store.persist_password und ist dort getestet.

Scheitert store.save nach dem Schreiben ins Keyring, wird bei einem NEUEN
Konto kompensiert — sonst bliebe das Secret unter einer id stehen, die in
keiner Datei mehr steht.

Der Dialog sagt offen, dass Microsoft-Konten nicht gehen und Gmail ein
App-Passwort braucht.
```

---

### Task 8: Sende-Dialog, Erklärtexte und Verdrahtung

Reine Tk-Schicht; verifiziert wird von Hand (Steps 6–8).

**Files:**
- Modify: `src/main.py`
- Modify: `src/ui.py`
- Modify: `src/dialogs/send_dialog.py`

**Interfaces:**
- Consumes: `SmtpStore` (Task 4), `perform_send(..., smtp_accounts=…)` (Task 5), `open_settings_dialog(..., smtp_store=…)` (Task 7)
- Produces: `open_send_dialog(..., smtp_store=None)`, `open_share_dialog(..., smtp_store=None)` (Signatur hier, Inhalt in Task 9), `show_missing_credentials_dialog` mit erweitertem Text

- [ ] **Step 1: Store in `main.py` anlegen und durchreichen**

Import nach `from src.webhook_store import WebhookStore`:

```python
from src.smtp_store import SmtpStore
```

Direkt nach `webhook_store = WebhookStore(os.path.join(base, "webhooks.json"))`:

```python
    # Kein geteilter Daten-Lock, aus denselben Gründen wie beim webhook_store:
    # SMTP-Konten nehmen an keinem Sync-Flow teil, und save/delete halten den
    # Lock über den icacls-Subprozess.
    smtp_store = SmtpStore(os.path.join(base, "smtp.json"))
```

Im `App(...)`-Aufruf ergänzen: `smtp_store=smtp_store,`

- [ ] **Step 2: `ui.py` durchreichen**

- `App.__init__`: Parameter `smtp_store=None` neben `webhook_store=None`, im Rumpf `self._smtp_store = smtp_store`.
- Im `open_settings_dialog(...)`-Aufruf: `smtp_store=self._smtp_store,`
- In `App._send`: `smtp_store=self._smtp_store,`
- In `App._share`: `smtp_store=self._smtp_store,`

- [ ] **Step 3: Erklärtext ohne Google-Sackgasse**

`show_missing_credentials_dialog` (`src/dialogs/send_dialog.py:25-60`) wird von **beiden** Dialogen benutzt und ist genau der Text, den ein Nutzer mit eingetragenem Empfänger und ohne `credentials.json` sieht. Der Absatz im Meldungstext (Zeilen 30–35) bekommt einen zweiten Weg:

```python
        "credentials.json nicht gefunden unter:\n"
        f"{base_path}\n\n"
        "Für den Versand über Gmail wird ein Google Cloud Projekt mit "
        "aktivierter Gmail API benötigt; lade die OAuth2 Client-ID als "
        "credentials.json in den Datenordner.\n\n"
        "Alternativ kannst Du unter Einstellungen → SMTP ein eigenes "
        "Mail-Konto einrichten — dann wird kein Google-Konto benötigt."
```

Den genauen Wortlaut der bestehenden Zeilen beim Umbau erhalten; nur der letzte Absatz kommt hinzu.

- [ ] **Step 4: Gating und Zielliste im Sende-Dialog**

Signatur um `smtp_store=None` erweitern. Den Block ab `hooks = webhook_store.enabled() …` bis zum `return` (aktuell `src/dialogs/send_dialog.py:148-161`) ersetzen:

```python
    hooks = webhook_store.enabled() if webhook_store else []
    accounts = smtp_store.enabled() if smtp_store else []
    recipient = settings.get("recipient")
    have_credentials = os.path.exists(credentials_path)
    mail_possible = bool(recipient) and have_credentials

    # Ohne jedes mögliche Ziel: erklären und abbrechen. Beide Texte nennen
    # beide Mailwege — sonst schicken sie jemanden ins Google-Cloud-Setup, der
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

Zielliste: `if hooks:` wird zu `if hooks or accounts:`, die SMTP-Zeilen kommen zwischen Mail und Webhooks, und `_update_send_button` zählt sie mit:

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

        target_row = 1
        for record in accounts:
            # Vorbelegt angehakt, wenn es KEINEN Gmail-Weg gibt: dann ist SMTP
            # der Standardweg und nicht die Ausnahme.
            var = tk.BooleanVar(value=not mail_possible)
            tk.Checkbutton(
                targets,
                text=f"{record.get('name', '')} → {record.get('recipient', '')}",
                variable=var, font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT, cursor="hand2",
                command=_update_send_button,
            ).grid(row=target_row, column=0, sticky="w", padx=6, pady=2)
            smtp_vars.append((record, var))
            target_row += 1

        for record in hooks:
            ...   # unveränderter Webhook-Block aus dem Bestand, aber mit
                  # `target_row` statt dem bisherigen enumerate-Index; am Ende
                  # jeder Iteration target_row += 1
```

- [ ] **Step 5: `do_send` anpassen**

Block „(a) Ziele einsammeln":

```python
        selected_accounts = [r for r, v in smtp_vars if v.get()]
        send_mail = bool(mail_var.get())
        if not send_mail and not selected_accounts and not selected_hooks:
            return  # Button ist in diesem Zustand deaktiviert; defensiv.
```

Block „(d)": Betreff und HTML werden gebraucht, sobald **Mail oder SMTP** beteiligt ist — der Kommentar dort gehört mitgezogen:

```python
        # Mail-HTML und Betreff für die Mail-Kanäle — Gmail wie SMTP. Beim
        # reinen Webhook-Versand bleiben sie None: `total` kommt nur aus
        # generate_report, unbedingt zu berechnen ergäbe dort einen NameError.
        html = subject = None
        if send_mail or selected_accounts:
            ...   # unveränderter generate_report-/subject-Block
```

`perform_send`-Aufruf:

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

Zuletzt: `btn_frame.grid(row=2 if (hooks or accounts) else 1, …)` und `if hooks or accounts: _update_send_button()`.

- [ ] **Step 6: Lint, Typecheck, volle Suite** — `ruff check .`, `npx pyright`, `pytest`

- [ ] **Step 7: Sende-Dialog von Hand prüfen**

Run: `python -m src.main`

- Mit `credentials.json` **und** einem SMTP-Konto: beide Zeilen sichtbar, Mail vorbelegt, SMTP nicht.
- `credentials.json` wegbenennen, App neu starten: der Dialog **öffnet**, die Mail-Zeile ist grau („Zugangsdaten fehlen"), das SMTP-Konto ist vorbelegt angehakt, Senden ist anwählbar.
- Empfänger eingetragen, keine `credentials.json`, kein Konto, kein Webhook: der Erklärdialog nennt jetzt **beide** Wege.

- [ ] **Step 8: Echten Versand prüfen**

Bericht über das SMTP-Konto senden: Mail kommt an, PDF hängt dran, Umlaute in Betreff und Body korrekt, Absender ist der eingetragene. Die Erfolgsmeldung nennt `Konto (empfaenger@…)`, nicht nur den Kontonamen.

Dann mit falschem Passwort: „Zugangsdaten wurden abgelehnt" samt Serverantwort — **kein** roher Traceback-Dialog.

- [ ] **Step 9: Commit**

```bash
git add src/main.py src/ui.py src/dialogs/send_dialog.py
git commit -F <commit-message-datei>
```

```
feat(send): SMTP-Konten als Ziele, Gmail wird optional

Der Sende-Dialog verlangt nicht mehr credentials.json, sondern
mindestens ein Ziel. Die Mail-Zeile bleibt sichtbar und deaktiviert,
damit erkennbar ist, warum sie nicht waehlbar ist.

show_missing_credentials_dialog nennt jetzt beide Wege — es war genau
die Google-Sackgasse, gegen die dieses Feature gebaut wird, und beide
Dialoge benutzen denselben Text.
```

---

### Task 9: Teilen-Dialog

Ohne diese Task ist der gesamte SMTP-Teilen-Pfad aus Task 6 unerreichbar: `open_share_dialog` bricht heute als **erste** Anweisung ab, wenn `credentials.json` fehlt — also genau für die Zielgruppe des Features.

**Files:**
- Modify: `src/dialogs/share_dialog.py`

**Interfaces:**
- Consumes: `perform_share(..., transport=…)` (Task 6), `send_task.format_result_summary` und `_KIND_TEXTS` (Task 5), `smtp_store.enabled()` (Task 4)
- Produces: nichts für Folgetasks.

- [ ] **Step 1: Gate kippen**

Signatur um `smtp_store=None` erweitern (die Verdrahtung in `ui.py` steht bereits aus Task 8). Den Block `src/dialogs/share_dialog.py:28-33` ersetzen:

```python
    credentials_path = os.path.join(base_path, "credentials.json")
    token_path = os.path.join(base_path, "token.json")

    accounts = smtp_store.enabled() if smtp_store else []
    gmail_possible = os.path.exists(credentials_path)

    # Nicht mehr „credentials.json muss da sein", sondern „irgendein Mailweg
    # muss da sein". Sonst bleibt Teilen für alle unerreichbar, die genau
    # deshalb SMTP eingerichtet haben.
    if not gmail_possible and not accounts:
        show_missing_credentials_dialog(parent, base_path)
        return
```

- [ ] **Step 2: Transport-Auswahl über dem Empfängerfeld**

Nur bauen, wenn es überhaupt eine Wahl gibt — sonst bleibt der Dialog exakt wie bisher. Vor dem „Empfänger:"-Label (`share_dialog.py:200`):

```python
    transport_labels = (["Gmail"] if gmail_possible else []) + \
        [a.get("name", "") for a in accounts]
    transport_var = tk.StringVar(value=transport_labels[0])
    if len(transport_labels) > 1:
        tk.Label(dialog, text="Versand über:", font=FONT, bg=BG, fg=TEXT).grid(
            row=row, column=0, padx=(20, 6), pady=(0, 4), sticky="w")
        dark_combo(dialog, transport_var, transport_labels, width=24).grid(
            row=row, column=1, padx=(0, 20), pady=(0, 4), sticky="w")
        row += 1

    def _chosen_transport():
        """Das gewählte SMTP-Konto, oder None für den Gmail-Weg."""
        return next(
            (a for a in accounts if a.get("name") == transport_var.get()), None)
```

`dark_combo` dem Theme-Import der Datei hinzufügen (`FONT` und `TEXT` sind bereits importiert).

- [ ] **Step 3: `do_send` anpassen**

Der Empfänger bleibt das Eingabefeld — auch beim SMTP-Weg (s. Task 6). Es ändert sich deshalb nur der Transport:

```python
        def fn():
            return perform_share(
                payload=payload, filename=filename,
                credentials_path=credentials_path, token_path=token_path,
                recipient=share_recipient, subject=subject, html=html,
                sync_enabled=settings.get("sync_enabled"),
                gcal_enabled=settings.get("gcal_enabled"),
                save_default=save_default_var.get(), settings=settings,
                transport=_chosen_transport(),
            )
```

Die Leerprüfung des Empfängerfelds (`share_dialog.py:232-239`) und die Erfolgsmeldung bleiben **unverändert** — beide beziehen sich weiterhin auf `share_recipient`, und das ist jetzt in beiden Wegen die tatsächlich verwendete Adresse.

- [ ] **Step 4: Fehlerzweig auf die neuen Kinds umstellen**

`on_done` verzweigt heute nur auf `filenotfound` und `offline` themed; **alles andere** geht in den rohen `messagebox.showerror` mit `res["tb"]`. Da `classify_smtp_error` für erwartete Fehler bewusst `tb=None` liefert, sähe der Nutzer bei falschem Passwort einen nativen Dialog mit der Zeile „None" — das verletzt die N14-Zweiteilung und verschluckt das kuratierte `detail`. Den Block ersetzen (`share_dialog.py:314-330`):

```python
            kind = res["kind"]
            if kind == "filenotfound":
                themed_showerror(target, "Fehler", str(res["error"]))
            elif kind == "offline":
                themed_showerror(
                    target, "Keine Internetverbindung",
                    "Die Daten konnten nicht gesendet werden, weil keine "
                    "Verbindung zum Internet besteht.\n\n"
                    "Bitte prüfe deine Internetverbindung und versuche es "
                    "dann erneut.",
                )
            elif res.get("tb"):
                # Nur der Catch-all-Zweig ist nativ: ein themed Dialog baut
                # selbst Tk-Widgets auf und ist im gestörten Zustand die
                # unzuverlässigere Schicht (CLAUDE.md, Audit N14).
                messagebox.showerror(
                    "Teilen fehlgeschlagen",
                    f"{type(res['error']).__name__}: {res['error']}\n\n{res['tb']}",
                    parent=target,
                )
            else:
                # Erwartete SMTP-Fehler (auth/recipient/tls/server): kuratierte
                # Meldung samt Serverantwort, themed.
                from src.dialogs.send_task import format_result_summary
                themed_showerror(
                    target, "Teilen fehlgeschlagen",
                    format_result_summary([{
                        "name": share_recipient, "ok": False,
                        "kind": kind, "detail": res.get("detail")}]))
```

- [ ] **Step 5: Lint, Typecheck, volle Suite** — `ruff check .`, `npx pyright`, `pytest`

- [ ] **Step 6: Von Hand prüfen — beide Varianten**

Run: `python -m src.main`

- **Mit** `credentials.json` und **ohne** SMTP-Konto: der Teilen-Dialog sieht aus wie vorher, keine Auswahlzeile.
- Mit beidem: Auswahl „Gmail | ⟨Kontoname⟩"; bei gewähltem Konto geht das Share-JSON an die im Feld eingetragene Adresse (nicht an den Konto-Empfänger).
- **`credentials.json` wegbenennen**, App neu starten, Teilen öffnen: der Dialog **öffnet** und zeigt nur das SMTP-Konto. Genau dieser Schritt fehlte in der ersten Planfassung und hätte den toten Pfad nicht aufgedeckt.
- Falsches Passwort: themed Meldung mit Serverantwort, **kein** Dialog mit dem Text „None".

- [ ] **Step 7: Commit**

```bash
git add src/dialogs/share_dialog.py
git commit -F <commit-message-datei>
```

```
feat(share): Versandweg waehlbar, Gate und Fehlerzweig nachgezogen

open_share_dialog brach als erste Anweisung ab, wenn credentials.json
fehlte — der SMTP-Teilen-Pfad waere fuer die Zielgruppe unerreichbar
gewesen. Jetzt: abbrechen nur, wenn weder Gmail noch ein Konto da ist.

Der Fehlerzweig kannte nur filenotfound und offline; jeder SMTP-Fehler
waere im rohen Traceback-Dialog gelandet und haette dort woertlich
"None" angezeigt, weil erwartete Kinds bewusst kein tb tragen.
```

---

### Task 10: Build, Dokumentation und Projekthinweise

**Files:**
- Modify: `scripts/build.py`, `tests/test_build.py`
- Modify: `README.md`
- Modify: `docs/known-limitations.md`
- Modify: `CLAUDE.md`, `src/CLAUDE.md`
- Modify: `src/secure_file.py` (nur der Modul-Docstring)

- [ ] **Step 1: `keyring` in den Frozen-Build aufnehmen — mit ehrlicher Begründung**

In `scripts/build.py`, in `_pyinstaller_common` nach `"--collect-all", "pystray",`:

```python
        # Redundant zum PyInstaller-Core-Hook (hook-keyring.py bündelt
        # keyring.backends samt Metadata; das keyring-Wheel selbst bringt
        # KEINEN Hook mit). Steht hier als Absicherung, falls dieser Hook
        # wegfällt — ohne die Backends findet der gebaute Build seinen
        # Schlüsselbund nicht und fiele still auf den Datei-Fallback zurück.
        "--collect-all", "keyring",
```

- [ ] **Step 2: Eigener Test — NICHT in die Pflichtliste**

`tests/test_build.py` hat `test_all_platforms_keep_mandatory_collect_all` mit vier Paketen und dem Docstring „Vier --collect-all…". Diese Liste bleibt **unverändert**: `keyring` ist dort keine Pflicht, und ein Required-Test mit falscher Begründung ist schlechter als keiner. Stattdessen ein eigener Test daneben:

```python
def test_all_platforms_bundle_keyring(monkeypatch):
    """Redundant zum PyInstaller-Core-Hook, aber bewusst gesetzt: faellt der
    Hook je weg, findet der gebaute Build seine Backends nicht und legt
    Passwoerter still im Datei-Fallback ab, statt im Schluesselbund. Kein
    Absturz, keine Meldung — nur schwaecherer Schutz. Deshalb hier
    festgehalten, aber getrennt von den vier zwingenden --collect-all."""
    for build_fn in (build.build_windows, build.build_linux):
        cmd = _capture_pyinstaller_cmd(monkeypatch, build_fn)
        assert "keyring" in cmd, f"keyring fehlt im {build_fn.__name__}-Kommando"
```

Run: `pytest tests/test_build.py -v`
Expected: PASS

- [ ] **Step 3: README — neuer Abschnitt und Features-Zeile**

Features-Abschnitt (Zielversion aus dem Release-PR einsetzen):

```markdown
- **SMTP-Versand** *(ab X.Y.Z)* — Berichte über einen eigenen Mail-Server statt über die Gmail-API verschicken; mehrere Konten mit je eigenem Empfänger möglich.
```

Neuer Abschnitt nach dem Gmail-Setup:

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

Das Passwort wird im Schlüsselbund des Betriebssystems abgelegt (Windows
Credential Manager, macOS Keychain, Linux Secret Service). Steht keiner zur
Verfügung, wird es lokal in `smtp.json` gespeichert — die App sagt das dann
beim Speichern. Der Schlüsselbund bindet den Zugriff an die installierte
App; wird die App aus dem Repo heraus gestartet (`python -m src.main`), hängt
er dagegen am Python-Interpreter und schützt entsprechend weniger.

**Was nicht geht:** Microsoft-Konten (Outlook.com, Microsoft 365). Microsoft
hat SMTP mit Passwort 2026 abgeschaltet; auch App-Passwörter funktionieren
dort nicht mehr. Für **Gmail** wird ein
[App-Passwort](https://support.google.com/accounts/answer/185833) benötigt —
nicht das Kontopasswort —, das eine aktive Zwei-Faktor-Anmeldung voraussetzt.

SMTP-Konten gelten **nur auf diesem Gerät** und reisen nicht per
Multi-Device-Sync.
```

Im Gmail-Abschnitt einen Verweis ergänzen, dass das nicht mehr der einzige Weg ist.

- [ ] **Step 4: README — die drei Stellen, die sonst falsch werden**

1. Block **Zugangsdaten** im Abschnitt Datenspeicherung (~Zeile 503): `smtp.json` in derselben Form ergänzen wie `webhooks.json` („inklusive Zugangsdaten … gerätelokal") — im Datei-Fallback steht dort ein Klartextpasswort.
2. Sicherheitshinweis (~Zeilen 518–522): „**Drei** Dateien im Datenordner sind Geheimnisse … Alle drei werden gleich behandelt" → **vier**, mit `smtp.json` in der Aufzählung. Das ist genau die Stelle, die sagt „Wer den Daten-/Installationsordner kopiert, sichert oder in die Cloud synchronisiert, nimmt sie mit".
3. Projektstruktur-Baum (~Zeilen 176–245): die fünf neuen Dateien ergänzen (`src/mime_message.py`, `src/smtp.py`, `src/smtp_store.py`, `src/keyring_store.py`, `src/dialogs/smtp_dialog.py`, `src/dialogs/settings_dialog/tab_smtp.py`).
4. Der Tab-Aufzählung im Einstellungen-Abschnitt (~Zeile 74) den SMTP-Tab hinzufügen.

- [ ] **Step 5: `docs/known-limitations.md` — drei Einträge**

Im Stil der vorhandenen (Datei zuerst lesen):

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

## macOS fragt nach jedem App-Update erneut nach dem Schlüsselbund

Auf macOS hängt die Zugriffsberechtigung eines Keychain-Eintrags am
*Designated Requirement* des zugreifenden Programms. PyInstaller signiert die
`.app` per Default ad-hoc, und dabei ist dieses Requirement der `cdhash` —
der sich mit **jedem** Build ändert. „Immer erlauben" gilt deshalb nur für
genau den Build, für den es geklickt wurde; nach einem Update fragt macOS
erneut. Das ließe sich nur mit einer echten Developer-ID-Signatur beheben.

Zusätzlich schreibt `keyring` ein geändertes Passwort als Löschen-und-neu-
Anlegen statt als Update und verwirft dabei die Berechtigung — auch ohne
Update erscheint der Dialog also nach jeder Passwortänderung einmal wieder.

Der Versand selbst ist davon nicht betroffen: wer den Dialog bestätigt, sendet
normal weiter; wer ihn abbricht, bekommt eine Fehlermeldung statt eines
stillen Fehlschlags.
```

- [ ] **Step 6: `CLAUDE.md` — Struktur und UTF-8-Abschnitt**

Im Abschnitt „Struktur" nach dem `src/webhook_store.py`-Eintrag:

```markdown
- `src/mime_message.py` — Aufbau der Mail-Nachricht, gemeinsam für Gmail-API
  und SMTP. Hier liegen **zwei der drei** UTF-8-Pflichten (MIMEText-Charset,
  Betreff-Header) und die Steuerzeichen-Abwehr gegen Header-Injection
  (Audit N11) — jeweils genau einmal; `mail.send_email` und `smtp.send` bauen
  ihre Nachricht beide hierüber
- `src/smtp.py` — SMTP-Versand (`smtplib`/`ssl`), Verbindungstest ohne Mail
  und **eigene** Fehlerklassifikation (`auth`/`recipient`/`tls`/`server`/
  `offline`). Eigener Klassifikator wie bei `webhook.py`: die drei Kinds aus
  `mail_task` würden jede Serverantwort zu „unerwarteter Fehler mit
  Traceback" verschmelzen. TLS immer mit Zertifikatsprüfung, und
  **fail-closed**: ein unbekannter `security`-Wert wirft, statt still
  unverschlüsselt zu verbinden
- `src/smtp_store.py` — gerätelokaler Store der SMTP-Konten (`smtp.json`),
  Mechanik wie `webhook_store.py`; prüft `security` schon beim Laden. Reist
  **nicht** per Drive-Sync. Fasst den Schlüsselbund nicht an — das Secret
  eines gelöschten Kontos räumt der Aufrufer ab
- `src/keyring_store.py` — Passwörter im OS-Schlüsselbund, mit Datei-Fallback
  wenn keiner verfügbar ist. `import keyring` lazy in den Funktionen (CI),
  und **jeder Zugriff hinter einem 5-s-Watchdog**: `keyring` ruft auf Linux
  `collection.unlock()` ohne Timeout, und ein hängender Worker bedeutet, dass
  `BackgroundTaskRunner` `on_done` nie ruft
- `src/dialogs/smtp_dialog.py` — Anlegen/Bearbeiten eines SMTP-Kontos inkl.
  Verbindungstest
```

Im Abschnitt „UTF-8 im Mail-Pipeline": klarstellen, dass die ersten beiden Pflichten in `src/mime_message.py` liegen und für **beide** Mailwege gelten, die dritte (`<meta charset>`) dagegen weiterhin bei den HTML-Erzeugern (`report.py`, `share_dialog.py`) — ein künftiger Mail-Kanal, der sein HTML selbst baut, kann sie also weiterhin verletzen. Den Satz „Diese drei Pflichten gelten nur für den Mail-Kanal" um den Hinweis ergänzen, dass „Mail-Kanal" jetzt Gmail **und** SMTP heißt.

In der Tabelle „Installation & Daten" `smtp.json` bei den Benutzerdaten mitnennen.

- [ ] **Step 7: `src/CLAUDE.md` — sechs Stellen, die sonst falsch stehen**

Die Datei sagt selbst: „veraltet ist sie schlimmer als gar nicht vorhanden." Nachzuziehen:

1. **`secure_file.py`-Absatz:** „Zugriffsschutz für die **drei** lokal abgelegten Secrets … `webhooks.json` (… **dritter** Schreibpfad)" → vier, mit `smtp.json`. Der Satz „Wer einen **vierten** Secret-Schreibpfad baut, ruft diesen Helfer mit auf" wird zu „einen fünften".
2. **`src/secure_file.py`, Modul-Docstring** („Die App schreibt **drei** sensible Dateien … `oauth_utils`, `single_instance` und `webhook_store` sollen nichts voneinander importieren") — dieselbe Korrektur, plus `smtp_store` in der Aufzählung.
3. **`json_store`-Absatz, „Bewusst eigen geblieben":** `smtp_store` in die Liste der Secret-Schreiber aufnehmen. Wichtig, weil `CLAUDE.md` sonst verlangt, neue Stores nutzten `atomic_write_json` — die Abweichung (ACL-Härtung + Rename-Retry) ist richtig, muss aber begründet dort stehen.
4. **`webhook_store`-Absatz über den eigenen Lock:** einen entsprechenden Eintrag für `SmtpStore` ergänzen (gleiche Begründung: kein Sync-Flow, Lock über den icacls-Subprozess).
5. **Dialoge-Abschnitt:** „je Tab eine Klasse in `tab_work`/`tab_mail`/… — außer `tab_webhooks`: **als einziger** Tab exponiert er keine Variablen" → `tab_smtp` ergänzen und „als einziger" streichen. `smtp_dialog` in die Dialog-Aufzählung neben `webhook_dialog`.
6. **Threading-Modell:** „die **zwei** Netz-Kerne teilen sich `mail_task.classify_mail_error`" → `share_task` nutzt zusätzlich `smtp.classify_smtp_error`. Und ergänzen, dass `perform_send` drei Kanaltypen feuert (Gmail, n SMTP-Konten, n Webhooks) und der Schlüsselbund-Zugriff im Worker passiert, hinter einem Watchdog, nie im Tk-Callback.

- [ ] **Step 8: Volle Suite und Lint** — `ruff check .`, `npx pyright`, `pytest`

- [ ] **Step 9: Frozen-Build lokal prüfen**

Run: `python scripts/build.py`

Danach `dist\Zeiterfassung\Zeiterfassung.exe` starten, ein SMTP-Konto anlegen und speichern. **Kommt die Meldung „Passwort lokal gespeichert"?** Dann hat der Frozen-Build kein Backend gefunden — das muss vor dem Merge geklärt sein, nicht vom ersten Nutzer entdeckt werden.

- [ ] **Step 10: Commit**

```bash
git add scripts/build.py tests/test_build.py README.md docs/known-limitations.md CLAUDE.md src/CLAUDE.md src/secure_file.py
git commit -F <commit-message-datei>
```

```
docs+build: SMTP dokumentieren, keyring in den Frozen-Build

--collect-all keyring ist redundant zum PyInstaller-Core-Hook und steht
als Absicherung, falls der wegfaellt — bewusst NICHT in der Liste der
zwingenden --collect-all, sondern in einem eigenen Test mit ehrlicher
Begruendung.

README bekommt die SMTP-Anleitung und drei nachgezogene Stellen (die
Secret-Dateien sind jetzt vier), known-limitations drei Eintraege
(Microsoft, geraetelokal, macOS-Keychain-Prompt nach jedem Update).

src/CLAUDE.md an sechs Stellen: secure_file zaehlt Secrets, die
json_store-Ausnahmeliste, der Lock-Absatz, die Tab-Aufzaehlung und das
Threading-Modell.
```

---

## Vor dem Merge

Kein Task, aber Pflicht — beides steht so in `CLAUDE.md`:

1. **Pre-Release über alle drei Plattformen.** `keyring` ist eine neue Dependency mit plattformabhängigen Backends; auf der Windows-Dev-Maschine sind macOS und Linux nicht verifizierbar. Actions → Workflow **Release** → „Run workflow" mit Häkchen **prerelease**. Je Plattform:
   - Konto anlegen, Passwort speichern — Schlüsselbund oder Datei-Fallback? Im Zweifel `keyring.core.get_keyring()` im gebauten Artefakt ausgeben lassen, statt am Symptom zu raten.
   - Verbindungstest und echter Versand.
   - **Linux:** Verhalten ohne laufenden Secret Service — saubere Meldung statt Absturz, und der Watchdog greift (der Dialog darf nicht auf „Sende…" stehenbleiben).
   - **macOS: zweimal bauen**, Bundle austauschen, erneut senden. Kommt der Keychain-Dialog wieder? Wenn ja, ist der known-limitations-Eintrag aus Task 10 die richtige Beschreibung; wenn nein, gehört er entschärft.
2. **Versionsbump und CHANGELOG** im Release-PR, plus `release:minor`-Label. Die Zielversion ist auch der Wert für den README-Marker `*(ab X.Y.Z)*` aus Task 10.
