# OAuth-Token und Webhook-Secrets im Schlüsselbund — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Refresh-Token aus `token.json` und die Webhook-Secrets aus `webhooks.json` liegen im OS-Schlüsselbund, sobald einer verfügbar ist. Bestehende Installationen ziehen beim Start automatisch und verlustfrei um, ohne Schlüsselbund bleibt alles wie heute.

**Architecture:**
- Neue Tk-freie Module:
  - `token_store` lädt und speichert OAuth-Credentials und setzt Datei plus Schlüsselbund zusammen.
  - `webhook_secrets` enthält die Secret-Regeln der Webhooks nach dem SMTP-Muster.
  - `secret_migration` zieht beim Start um.
- `keyring_store` bekommt die schlüsselbasierten Funktionen `put`/`fetch`/`remove`.
- `oauth_utils` bekommt den Schlüsselnamen, den Datei-Schreibweg für fertiges JSON und `forget_token`.
- Der Umzug läuft als Hintergrund-Task nach dem Token-Refresh beim Start. Hat er etwas verschoben, erscheint einmal ein Hinweis.

**Tech Stack:** Python 3.10, Tkinter (nur Dialog-Wiring), `keyring==25.7.0` (lazy importiert), google-auth, pytest, ruff, pyright 1.1.411.

**Spec:** `docs/superpowers/specs/2026-09-18-secrets-keyring-design.md`

## Global Constraints

- **Kompatibilität mit bestehenden Installationen hat Vorrang:**
  - Eine `token.json` ohne `refresh_token_location` bzw. ein Webhook ohne `auth.secret_location` gilt als `"file"`. Beide werden **exakt wie heute** gelesen und geschrieben.
  - Ohne Schlüsselbund ist das Verhalten byte-gleich zu heute.
- **Kein Test darf den echten OS-Schlüsselbund anfassen.** Ein autouse-Fixture in `tests/conftest.py` installiert standardmäßig ein **nicht verfügbares** Fake-`keyring` in `sys.modules`. Tests, die einen funktionierenden brauchen, nehmen das Fixture `fake_keyring`.
- `import keyring` bleibt **lazy innerhalb** der Funktionen von `keyring_store`, weil die CI `keyring` nicht installiert.
- **Jeder Schlüsselbund-Zugriff läuft über `keyring_store`** (Watchdog `WATCHDOG_TIMEOUT` = 30 s) und nie im Tk-Callback, immer im Worker.
- **Logs enthalten nie ein Secret und nie einen Schlüsselbund-Schlüssel oder eine Webhook-ID** (CodeQL `py/clear-text-logging`, s. `keyring_store.delete_secret`).
- **Kein Consent-Flow ohne Klick** (Xveyn#129): Ein nicht erreichbarer Schlüsselbund führt in nicht-interaktiven Pfaden zu einem Fehler, nie zu `run_local_server`.
- **Neue Tk-freie Module sind vollständig annotiert** und stehen in `tests/test_type_annotations.py::ANNOTATED_MODULES`: `src/token_store.py`, `src/webhook_secrets.py`, `src/secret_migration.py`. `keyring_store`/`oauth_utils` stehen dort schon, neue Funktionen darin sind also ebenfalls voll zu annotieren.
- **Catch-alls** folgen `tests/test_catch_all_handlers.py`: Sie loggen, melden oder tragen eine Begründung im Handler, und der `try` bleibt eng.
- **Keine neuen Abhängigkeiten.**
- **Befehle:** Aus dem Repo-Root laufen `python -m pytest -q -p no:warnings`, `python -m ruff check .` und `npx --yes pyright@1.1.411`. pyright lokal: `0 errors, 0 warnings`; in frischem Checkout ist eine bestehende Warnung zu `src/build_info.py` normal, **jede andere** Warnung ist ein Befund.
- **Shell:** In PowerShell nie `&&` verwenden. Mehrzeilige Commit-Messages nur über eine Temp-Datei (`git commit -F`) im Scratchpad `C:\Users\SvenB\AppData\Local\Temp\claude\D--Programme--x86--Zeiterfassung-Repo-Zeiterfassung\0ce62229-4862-454a-b6a3-a2cf81fea1b3\scratchpad`. Jeder Commit endet mit `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Namen der Einträge im Schlüsselbund:**
  - Service `"Zeiterfassung"` (`keyring_store.SERVICE`).
  - Token: `"google-oauth:" + sha256(normcase(abspath(Datenverzeichnis)))[:12]` (hex).
  - Webhook: `"webhook:" + id`.

## Bewusste Abweichungen von der Spec (Plan-Entscheidungen)

1. **`load_credentials(token_path, scopes, credentials_cls)`** bekommt die `Credentials`-Klasse des Aufrufers. Nur so greifen die bestehenden Test-Patches unverändert: `src.drive.Credentials`, `google.oauth2.credentials.Credentials.from_authorized_user_file` und der globale Patch in `tests/conftest.py::install_existing_token`.
2. **`token_keyring_key` und `forget_token` liegen in `oauth_utils`**, nicht in `token_store`. `discard_token_for_scope_upgrade` (in `oauth_utils`) ruft `forget_token`, und `token_store` importiert `oauth_utils`, das wäre ein Zyklus.
3. **Die SMTP-Funktionen in `keyring_store` bleiben unverändert.** `put`/`fetch`/`remove` kommen daneben, über denselben `_call_guarded`. Die SMTP-Tests prüfen Log-Inhalte, ein Umbau brächte Risiko ohne Nutzen.
4. **Der Webhook-Lösch-Hook bekommt nur die ID** (Signatur `after_delete(record_id)` aus R12). Er ruft `keyring_store.remove` also auch für Webhooks ohne Schlüsselbund-Secret. Das SMTP-Konto verhält sich heute genauso (`tab_smtp._delete_secret`).

## File Structure

| Datei | Aktion | Verantwortung |
|---|---|---|
| `tests/conftest.py` | Modify | autouse „kein OS-Schlüsselbund", Fixture `fake_keyring` (aus `test_keyring_store.py` hierher) |
| `tests/test_keyring_store.py` | Modify | lokalen Fake entfernen, conftest-Fixture nutzen; Tests für `put`/`fetch`/`remove` |
| `src/keyring_store.py` | Modify | `put`, `fetch`, `remove` |
| `src/oauth_utils.py` | Modify | `KEYRING_UNAVAILABLE_MSG`, `TokenKeyringUnavailable`, `REFRESH_TOKEN_LOCATION`, `token_keyring_key`, `token_location`, `write_token_json`, `forget_token`; `discard_token_for_scope_upgrade` nutzt `forget_token` |
| `src/token_store.py` | Create | `load_credentials`, `save_credentials` |
| `src/mail.py`, `src/drive.py`, `src/gcal.py` | Modify | laden/schreiben über `token_store`; `drive.reconnect` nutzt `forget_token` |
| `src/background_tasks.py` | Modify | `refresh_token`: `TokenKeyringUnavailable` still, neuer `on_finished`; neuer Task `migrate_secrets` |
| `src/dialogs/mail_task.py` | Modify | `TokenKeyringUnavailable` → `kind: "keyring"` |
| `src/sync_orchestrator.py`, `src/ui.py` | Modify | Fehlerart `"keyring"` in Meldungen; Umzug anstoßen und Hinweis zeigen |
| `src/webhook_secrets.py` | Create | Secret-Regeln der Webhooks (Feld, Schlüssel, Auflösen, Persistieren, Vergessen) |
| `src/webhook_store.py` | Modify | `validate_record` akzeptiert ein Secret im Schlüsselbund |
| `src/dialogs/send_task.py` | Modify | Webhook-Secret im Worker auflösen |
| `src/dialogs/webhook_dialog.py` | Modify | kein Vorbefüllen, Hinweis, `persist` beim Speichern, `resolve` beim Test |
| `src/dialogs/settings_dialog/tab_webhooks.py` | Modify | `after_delete` räumt den Eintrag ab |
| `src/secret_migration.py` | Create | `migrate`, `MigrationReport`, Hinweistexte |
| `tests/test_type_annotations.py` | Modify | drei neue Module |
| `tests/test_token_store.py`, `tests/test_webhook_secrets.py`, `tests/test_secret_migration.py` | Create | Tests |
| `CLAUDE.md`, `src/CLAUDE.md`, `docs/known-limitations.md` | Modify | Doku |

---

### Task 1: Test-Fundament — kein Test berührt den echten Schlüsselbund

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_keyring_store.py` (Z. 10–56: Imports `sys`/`types`, Klasse `_FakeKeyring`, Fixture `fake_keyring`)

**Interfaces:**
- Produces: Fixture `fake_keyring(working=True, block=None, lie=False)` → Fake mit `.store: dict[(service, account), str]`. Mit `lie=True` liefert `get_password` einen anderen Wert als geschrieben, für den Fall „Zurücklesen stimmt nicht". Außerdem ein autouse-Fixture `_no_os_keyring`.

- [ ] **Step 1: Fake und Fixtures nach `tests/conftest.py`**

Am Ende von `tests/conftest.py` anfügen (Imports `sys`, `types`, `pytest` oben ergänzen, falls nicht vorhanden):

```python
class FakeKeyring:
    """Stand-in für das `keyring`-Paket. `keyring_store` importiert `keyring`
    lazy in den Funktionen — ein Modul in sys.modules ersetzt also das echte
    Backend vollständig. Kein Test darf Einträge im Anmeldeinformations-
    manager / in der Keychain des Entwicklerrechners hinterlassen."""

    def __init__(self, working=True, block=None, lie=False):
        self.working = working
        self.block = block          # threading.Event: blockiert bis gesetzt
        self.lie = lie              # get_password liefert einen falschen Wert
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
        value = self.store.get((service, account))
        if self.lie and value is not None:
            return value + "-verfälscht"
        return value

    def delete_password(self, service, account):
        self._guard()
        del self.store[(service, account)]


def _install_fake_keyring(monkeypatch, fake):
    module = types.ModuleType("keyring")
    module.set_password = fake.set_password
    module.get_password = fake.get_password
    module.delete_password = fake.delete_password
    monkeypatch.setitem(sys.modules, "keyring", module)
    return fake


@pytest.fixture(autouse=True)
def _no_os_keyring(monkeypatch):
    """Standard für JEDEN Test: kein Schlüsselbund verfügbar. Damit verhalten
    sich alle Pfade wie heute ohne Schlüsselbund (Datei), und ein Entwickler
    mit installiertem `keyring` schreibt beim Testlauf nichts in seinen
    echten Schlüsselbund. Tests mit Schlüsselbund nehmen `fake_keyring`."""
    _install_fake_keyring(monkeypatch, FakeKeyring(working=False))


@pytest.fixture
def fake_keyring(monkeypatch):
    def _install(working=True, block=None, lie=False):
        return _install_fake_keyring(
            monkeypatch, FakeKeyring(working=working, block=block, lie=lie))
    return _install
```

- [ ] **Step 2: Lokalen Fake aus `tests/test_keyring_store.py` entfernen**

Die Klasse `_FakeKeyring` und das Fixture `fake_keyring` (Z. 20–55) löschen. Imports `sys` und `types` nur dann entfernen, wenn `ruff` sie danach als unbenutzt meldet. `test_set_secret_falls_back_when_keyring_is_not_installed` setzt `sys.modules["keyring"]` selbst und bleibt, wie er ist. Den Modul-Docstring lassen, er beschreibt das Prinzip weiter richtig.

- [ ] **Step 3: Volle Suite**

Run: `python -m pytest -q -p no:warnings`
Expected: dieselbe Anzahl bestandener Tests wie vorher (2237 passed, 10 skipped). Mit dem autouse-Fixture ändert sich für bestehende Tests nichts, weil heute kein Produktivpfad außer SMTP den Schlüsselbund anfasst und die SMTP-Tests `fake_keyring` nutzen.

- [ ] **Step 4: Commit** — Message: `test: Fake-Schlüsselbund zentral in conftest, autouse ohne OS-Schlüsselbund (#101)` + Leerzeile + `Refs Xveyn/Zeiterfassung#101` + Co-Authored-By.

---

### Task 2: `keyring_store` — schlüsselbasierte Grundfunktionen

**Files:**
- Modify: `src/keyring_store.py` (hinter `delete_secret`, vor `persist_password`)
- Test: `tests/test_keyring_store.py` (anhängen)

**Interfaces:**
- Consumes: `_call_guarded`, `SERVICE`, `WATCHDOG_TIMEOUT` (bestehend)
- Produces:
  - `put(key: str, value: str) -> bool`
  - `fetch(key: str) -> str | None`. `None` heißt „nicht ermittelbar", `""` heißt „kein Eintrag".
  - `remove(key: str) -> None`

- [ ] **Step 1: Tests schreiben** (an `tests/test_keyring_store.py` anhängen)

```python
# --- schlüsselbasiert: put / fetch / remove (#101) -------------------------


def test_put_and_fetch_roundtrip(fake_keyring):
    fake = fake_keyring()
    assert keyring_store.put("google-oauth:abc", "1//refresh") is True
    assert fake.store[(keyring_store.SERVICE, "google-oauth:abc")] == "1//refresh"
    assert keyring_store.fetch("google-oauth:abc") == "1//refresh"


def test_fetch_returns_empty_string_for_a_missing_entry(fake_keyring):
    fake_keyring()
    assert keyring_store.fetch("google-oauth:abc") == ""


def test_put_and_fetch_without_backend(fake_keyring):
    fake_keyring(working=False)
    assert keyring_store.put("k", "v") is False
    assert keyring_store.fetch("k") is None


def test_put_and_fetch_give_up_when_the_keyring_blocks(fake_keyring, monkeypatch):
    import threading
    monkeypatch.setattr(keyring_store, "WATCHDOG_TIMEOUT", 0.05)
    release = threading.Event()
    fake_keyring(block=release)
    try:
        assert keyring_store.put("k", "v") is False
        assert keyring_store.fetch("k") is None
    finally:
        release.set()


def test_remove_deletes_and_is_quiet_when_missing(fake_keyring):
    fake = fake_keyring()
    keyring_store.put("k", "v")
    keyring_store.remove("k")
    assert (keyring_store.SERVICE, "k") not in fake.store
    keyring_store.remove("k")            # fehlt: kein Fehler


def test_put_fetch_remove_never_log_key_or_value(fake_keyring, caplog):
    import logging
    fake_keyring(working=False)
    with caplog.at_level(logging.DEBUG, logger="src.keyring_store"):
        keyring_store.put("google-oauth:geheimer-schluessel", "1//geheim")
        keyring_store.fetch("google-oauth:geheimer-schluessel")
        keyring_store.remove("google-oauth:geheimer-schluessel")
    assert "geheimer-schluessel" not in caplog.text
    assert "1//geheim" not in caplog.text
```

- [ ] **Step 2: RED** — Run: `python -m pytest tests/test_keyring_store.py -q -p no:warnings` · Expected: FAIL mit `AttributeError: module 'src.keyring_store' has no attribute 'put'`.

- [ ] **Step 3: Implementieren** (in `src/keyring_store.py` vor `def persist_password` einfügen)

```python
def put(key: str, value: str) -> bool:
    """Legt `value` unter `key` ab (schlüsselbasiert, #101). `True` bei Erfolg.

    Anders als `set_secret` kennt diese Funktion keinen Datensatz und keinen
    Datei-Fallback — den entscheidet der Aufrufer (`token_store`,
    `webhook_secrets`, `secret_migration`). Geloggt wird weder Schlüssel noch
    Wert: der Schlüssel enthält eine Webhook-ID bzw. den Hash des
    Datenverzeichnisses, und das Log ist ungehärtet.
    """
    def work() -> None:
        import keyring  # pyright: ignore[reportMissingImports]

        keyring.set_password(SERVICE, key, value)

    try:
        ok, _ = _call_guarded(work)
    except Exception:
        # Bewusst alles: kein Backend, D-Bus-Fehler, Lib fehlt — für den
        # Aufrufer dasselbe (s. set_secret).
        log.info("Schlüsselbund nicht verfügbar — Eintrag nicht abgelegt",
                 exc_info=True)
        return False
    if not ok:
        log.warning("Schlüsselbund antwortet nicht (Timeout nach %.1fs) — "
                    "Eintrag nicht abgelegt", WATCHDOG_TIMEOUT)
        return False
    return True


def fetch(key: str) -> str | None:
    """Liest den Eintrag `key`.

    `None`: NICHT ermittelbar (kein Backend, Timeout, Fehler). `""`: der
    Schlüsselbund hat geantwortet, es gibt keinen Eintrag. Aufrufer MÜSSEN
    beides unterscheiden — dieselbe Regel wie bei `get_secret`.
    """
    def work() -> Any:
        import keyring  # pyright: ignore[reportMissingImports]

        return keyring.get_password(SERVICE, key)

    try:
        ok, stored = _call_guarded(work)
    except Exception:
        # Bewusst alles, s. put.
        log.warning("Schlüsselbund nicht lesbar", exc_info=True)
        return None
    if not ok:
        log.warning("Schlüsselbund antwortet nicht (Timeout nach %.1fs)",
                    WATCHDOG_TIMEOUT)
        return None
    return str(stored) if stored else ""


def remove(key: str) -> None:
    """Räumt `key` ab. Ein fehlender Eintrag ist kein Fehler."""
    def work() -> None:
        import keyring  # pyright: ignore[reportMissingImports]

        keyring.delete_password(SERVICE, key)

    try:
        ok, _ = _call_guarded(work)
    except Exception:
        # Bewusst alles: kein Backend oder kein Eintrag (PasswordDeleteError)
        # — beides heißt „nichts zu tun". Ohne Schlüssel im Log, s. put.
        log.debug("Ein Eintrag ließ sich nicht entfernen (kein Schlüsselbund "
                  "oder kein Eintrag)", exc_info=True)
        return
    if not ok:
        log.warning("Schlüsselbund antwortet nicht — ein Eintrag blieb stehen")
```

- [ ] **Step 4: GREEN** — Run: `python -m pytest tests/test_keyring_store.py tests/test_catch_all_handlers.py tests/test_type_annotations.py -q -p no:warnings` · Expected: PASS.

- [ ] **Step 5: Commit** — `feat(keyring): schlüsselbasiertes put/fetch/remove hinter dem Watchdog (#101)`.

---

### Task 3: `oauth_utils` — Schlüsselname, JSON-Schreibweg, `forget_token`

**Files:**
- Modify: `src/oauth_utils.py`, `src/drive.py` (`reconnect`)
- Test: `tests/test_oauth_utils.py` (anhängen)

**Interfaces:**
- Consumes: `keyring_store.remove` (Task 2)
- Produces:
  - `KEYRING_UNAVAILABLE_MSG: str`
  - `class TokenKeyringUnavailable(Exception)`, Meldung = `KEYRING_UNAVAILABLE_MSG`
  - `REFRESH_TOKEN_LOCATION = "refresh_token_location"`
  - `token_keyring_key(token_path: str) -> str`
  - `token_location(token_path: str) -> str`, liefert `"keyring"` oder `"file"`
  - `write_token_json(json_text: str, token_path: str) -> None`
  - `write_token(creds, token_path)` mit unveränderter Signatur und unverändertem Verhalten
  - `forget_token(token_path: str) -> None`

- [ ] **Step 1: Tests schreiben** (an `tests/test_oauth_utils.py` anhängen)

```python
# --- Schlüsselbund-Anbindung (#101) ----------------------------------------

import json as _json

from src import keyring_store as _ks
from src import oauth_utils as _ou


def test_token_keyring_key_depends_on_the_data_directory(tmp_path):
    a = _ou.token_keyring_key(str(tmp_path / "a" / "token.json"))
    b = _ou.token_keyring_key(str(tmp_path / "b" / "token.json"))
    assert a.startswith("google-oauth:") and len(a) == len("google-oauth:") + 12
    assert a != b
    assert a == _ou.token_keyring_key(str(tmp_path / "a" / "token.json"))


def test_token_location_defaults_to_file(tmp_path):
    path = tmp_path / "token.json"
    assert _ou.token_location(str(path)) == "file"                 # fehlt
    path.write_text('{"token": "t"}', encoding="utf-8")
    assert _ou.token_location(str(path)) == "file"                 # Alt-Format
    path.write_text("kein json", encoding="utf-8")
    assert _ou.token_location(str(path)) == "file"                 # kaputt
    path.write_text('{"refresh_token_location": "keyring"}', encoding="utf-8")
    assert _ou.token_location(str(path)) == "keyring"


def test_write_token_json_writes_exactly_the_text(tmp_path):
    path = tmp_path / "token.json"
    _ou.write_token_json('{"a": 1}', str(path))
    assert path.read_text(encoding="utf-8") == '{"a": 1}'


def test_forget_token_removes_file_and_keyring_entry(tmp_path, fake_keyring):
    fake = fake_keyring()
    path = tmp_path / "token.json"
    path.write_text(_json.dumps({"refresh_token_location": "keyring"}),
                    encoding="utf-8")
    key = _ou.token_keyring_key(str(path))
    _ks.put(key, "1//refresh")

    _ou.forget_token(str(path))

    assert not path.exists()
    assert (_ks.SERVICE, key) not in fake.store


def test_forget_token_leaves_the_keyring_alone_for_a_file_token(tmp_path, fake_keyring):
    fake = fake_keyring()
    path = tmp_path / "token.json"
    path.write_text('{"refresh_token": "1//x"}', encoding="utf-8")
    key = _ou.token_keyring_key(str(path))
    fake.store[(_ks.SERVICE, key)] = "fremder Eintrag"

    _ou.forget_token(str(path))

    assert not path.exists()
    assert fake.store[(_ks.SERVICE, key)] == "fremder Eintrag"


def test_forget_token_is_quiet_without_a_file(tmp_path):
    _ou.forget_token(str(tmp_path / "token.json"))
```

- [ ] **Step 2: RED** — Run: `python -m pytest tests/test_oauth_utils.py -q -p no:warnings` · Expected: FAIL (`AttributeError: … has no attribute 'token_keyring_key'`).

- [ ] **Step 3: Implementieren** in `src/oauth_utils.py`

(a) Imports ergänzen: `import hashlib`, `import json` (falls nicht vorhanden) und `from src import keyring_store`.

(b) `write_token` aufteilen. Den bisherigen Körper nach `write_token_json(json_text, token_path)` verschieben; darin `f.write(creds.to_json())` durch `f.write(json_text)` ersetzen. Den Docstring übernehmen und oben einen Satz ergänzen: „Schreibt fertigen JSON-Text; `write_token` und `token_store.save_credentials` liefern ihn." Danach:

```python
def write_token(creds: Any, token_path: str) -> None:
    """Persistiere Credentials vollständig (inkl. Refresh-Token) als Datei —
    der Weg ohne Schlüsselbund, byte-gleich zum Verhalten vor #101."""
    write_token_json(creds.to_json(), token_path)
```

(c) Nach `REAUTH_REQUIRED_MSG` einfügen:

```python
KEYRING_UNAVAILABLE_MSG = (
    "Der Schlüsselbund des Betriebssystems ist nicht erreichbar — dort liegt "
    "die Google-Anmeldung.")
"""Fehlertext, wenn der Refresh-Token im Schlüsselbund liegt, dieser aber
nicht antwortet (gesperrt, Timeout). Wie `REAUTH_REQUIRED_MSG` als Text
erkennbar, weil Sync-Flows Fehler teils nur als `str(e)` weiterreichen."""

REFRESH_TOKEN_LOCATION = "refresh_token_location"
"""Feld in token.json: `"keyring"`, wenn der Refresh-Token im Schlüsselbund
liegt. Fehlt es (Alt-Format), liegt er in der Datei (#101)."""


class TokenKeyringUnavailable(Exception):
    """Der Refresh-Token liegt im Schlüsselbund, der aber nicht antwortet.

    Kein Auth-Fehler: der Token ist nicht ungültig, nur gerade nicht lesbar.
    Aufrufer starten deshalb KEINEN Consent-Flow (Xveyn#129) und fassen
    token.json nicht an."""

    def __init__(self) -> None:
        super().__init__(KEYRING_UNAVAILABLE_MSG)


def token_keyring_key(token_path: str) -> str:
    """Schlüssel des Refresh-Tokens im Schlüsselbund — pro Datenverzeichnis.

    Der Schlüsselbund gehört dem OS-Nutzer, nicht der Installation: ohne den
    Verzeichnis-Hash läse und überschriebe eine Dev-Instanz (eigenes
    Datenverzeichnis) den Token der installierten App. Gleiche Idee wie der
    Port-Hash in `single_instance`."""
    directory = os.path.normcase(
        os.path.dirname(os.path.abspath(os.fspath(token_path))))
    digest = hashlib.sha256(directory.encode("utf-8")).hexdigest()[:12]
    return f"google-oauth:{digest}"


def token_location(token_path: str) -> str:
    """`"keyring"` oder `"file"` — wo der Refresh-Token von `token_path` liegt.
    Fehlende, unlesbare oder Alt-Dateien gelten als `"file"`."""
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return "file"
    if isinstance(data, dict) and data.get(REFRESH_TOKEN_LOCATION) == "keyring":
        return "keyring"
    return "file"


def forget_token(token_path: str) -> None:
    """Löscht token.json und — nur wenn der Refresh-Token dort liegt — den
    Eintrag im Schlüsselbund. Ohne das zweite blieben nach „Google neu
    verbinden" oder einem Scope-Upgrade verwaiste Einträge stehen."""
    in_keyring = token_location(token_path) == "keyring"
    try:
        os.remove(token_path)
    except FileNotFoundError:
        pass
    if in_keyring:
        keyring_store.remove(token_keyring_key(token_path))
```

(d) In `discard_token_for_scope_upgrade` den Block

```python
    try:
        os.remove(token_path)
    except OSError:
        pass
    return True
```

ersetzen durch

```python
    try:
        forget_token(token_path)
    except OSError:
        # Wie zuvor: ein Löschfehler (gesperrte Datei) darf den Consent, der
        # unmittelbar folgt, nicht verhindern — der schreibt token.json neu.
        log.debug("token.json ließ sich nicht löschen", exc_info=True)
    return True
```

Falls `oauth_utils` noch kein `log` hat: `import logging` und `log = logging.getLogger(__name__)` ergänzen.

(e) In `src/drive.py::reconnect` den Block `try: os.remove(token_path) except FileNotFoundError: pass` durch `forget_token(token_path)` ersetzen und `forget_token` zum Import `from src.oauth_utils import …` hinzufügen.

- [ ] **Step 4: GREEN** — Run: `python -m pytest tests/test_oauth_utils.py tests/test_drive.py tests/test_gcal.py tests/test_mail.py tests/test_catch_all_handlers.py tests/test_type_annotations.py -q -p no:warnings` · Expected: PASS (bestehende `write_token`-/`discard`-Tests unverändert grün).

- [ ] **Step 5: Commit** — `feat(oauth): Schlüsselname je Datenverzeichnis, forget_token, write_token_json (#101)`.

---

### Task 4: `token_store` — Laden und Speichern mit Schlüsselbund

**Files:**
- Create: `src/token_store.py`, `tests/test_token_store.py`
- Modify: `tests/test_type_annotations.py` (`"src/token_store.py",` nach `"src/oauth_utils.py",`)

**Interfaces:**
- Consumes: `keyring_store.put/fetch` (Task 2); `oauth_utils.REFRESH_TOKEN_LOCATION`, `TokenKeyringUnavailable`, `token_keyring_key`, `write_token`, `write_token_json` (Task 3)
- Produces:
  - `load_credentials(token_path: str, scopes: list[str], credentials_cls: Any) -> Any | None`. Liefert `None` genau dann, wenn der Refresh-Token im Schlüsselbund liegen soll, dort aber fehlt. Wirft `TokenKeyringUnavailable`, wenn der Schlüsselbund nicht antwortet.
  - `save_credentials(creds: Any, token_path: str) -> None`

- [ ] **Step 1: Tests schreiben** — `tests/test_token_store.py`:

```python
"""token_store (#101): Refresh-Token im Schlüsselbund, Rest in token.json.
Die Kompatibilitätstests laufen mit ECHTEN google-auth-Credentials."""

import json

import pytest
from google.oauth2.credentials import Credentials

from src import keyring_store, oauth_utils
from src.token_store import load_credentials, save_credentials

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _real_creds(refresh="1//refresh-token"):
    return Credentials(
        token="ya29.access", refresh_token=refresh,
        token_uri="https://oauth2.googleapis.com/token",
        client_id="cid.apps.googleusercontent.com", client_secret="csecret",
        scopes=SCOPES)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_legacy_file_loads_exactly_as_before(tmp_path):
    """Kompatibilität: eine token.json, wie sie write_token heute schreibt,
    lädt zu denselben Credentials wie from_authorized_user_file."""
    path = tmp_path / "token.json"
    oauth_utils.write_token(_real_creds(), str(path))

    loaded = load_credentials(str(path), SCOPES, Credentials)
    reference = Credentials.from_authorized_user_file(str(path), SCOPES)

    assert loaded.to_json() == reference.to_json()


def test_without_keyring_save_writes_the_full_file_as_before(tmp_path):
    """Kein Schlüsselbund (autouse-Standard): byte-gleich zu write_token."""
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    creds = _real_creds()

    save_credentials(creds, str(a))
    oauth_utils.write_token(creds, str(b))

    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")
    assert oauth_utils.REFRESH_TOKEN_LOCATION not in _read(a)


def test_with_keyring_the_refresh_token_leaves_the_file(tmp_path, fake_keyring):
    fake = fake_keyring()
    path = tmp_path / "token.json"

    save_credentials(_real_creds(), str(path))

    data = _read(path)
    assert "refresh_token" not in data
    assert data["token"] == "ya29.access"          # Access-Token bleibt
    assert data[oauth_utils.REFRESH_TOKEN_LOCATION] == "keyring"
    key = oauth_utils.token_keyring_key(str(path))
    assert fake.store[(keyring_store.SERVICE, key)] == "1//refresh-token"


def test_keyring_roundtrip_loads_the_same_credentials(tmp_path, fake_keyring):
    fake_keyring()
    path = tmp_path / "token.json"
    creds = _real_creds()
    save_credentials(creds, str(path))

    loaded = load_credentials(str(path), SCOPES, Credentials)

    assert loaded.refresh_token == "1//refresh-token"
    assert loaded.token == "ya29.access"
    assert loaded.client_id == creds.client_id


def test_unreachable_keyring_raises_and_leaves_the_file(tmp_path, fake_keyring):
    fake_keyring()
    path = tmp_path / "token.json"
    save_credentials(_real_creds(), str(path))
    before = path.read_bytes()
    fake_keyring(working=False)

    with pytest.raises(oauth_utils.TokenKeyringUnavailable):
        load_credentials(str(path), SCOPES, Credentials)

    assert path.read_bytes() == before


def test_missing_keyring_entry_means_no_credentials(tmp_path, fake_keyring):
    fake = fake_keyring()
    path = tmp_path / "token.json"
    save_credentials(_real_creds(), str(path))
    fake.store.clear()                              # im Credential Manager gelöscht

    assert load_credentials(str(path), SCOPES, Credentials) is None


def test_save_falls_back_to_the_file_when_the_keyring_fails(tmp_path, fake_keyring):
    fake_keyring(working=False)
    path = tmp_path / "token.json"

    save_credentials(_real_creds(refresh="1//rotiert"), str(path))

    data = _read(path)
    assert data["refresh_token"] == "1//rotiert"   # der neue Token geht nie verloren
    assert oauth_utils.REFRESH_TOKEN_LOCATION not in data


def test_unreadable_file_takes_the_legacy_path(tmp_path):
    """Nicht-JSON: dasselbe Verhalten wie heute (die Klasse entscheidet)."""
    path = tmp_path / "token.json"
    path.write_text("kaputt", encoding="utf-8")
    calls = []

    class _Cls:
        @staticmethod
        def from_authorized_user_file(p, scopes):
            calls.append(p)
            return "LEGACY"

    assert load_credentials(str(path), SCOPES, _Cls) == "LEGACY"
    assert calls == [str(path)]
```

- [ ] **Step 2: RED** — Run: `python -m pytest tests/test_token_store.py -q -p no:warnings` · Expected: ERROR `ModuleNotFoundError: No module named 'src.token_store'`.

- [ ] **Step 3: Implementieren** — `src/token_store.py`:

```python
"""OAuth-Credentials laden und speichern — Refresh-Token im Schlüsselbund (#101).

Einzige Stelle, die entscheidet, wo der Refresh-Token liegt. token.json
bleibt bestehen und behält alles außer ihm (Access-Token, Scopes, Client,
Ablauf): die rund zehn Datei-Prüfungen der App (existiert? welche Scopes?
mtime-Poll im Google-Tab) laufen damit unverändert weiter.

Nur der Refresh-Token, weil der Windows Credential Manager höchstens 1280
Zeichen (UTF-16) fasst, Google Access-Tokens aber bis 2048 Byte reserviert —
das ganze JSON risse das Limit (Spec, R1). Der Access-Token muss in der Datei
bleiben: ohne ihn meldet google-auth `valid=False` UND `expired=False`, und
die Ladepfade liefen in den Consent statt in den Refresh.

Tk-frei; google-auth wird nicht importiert — die Credentials-Klasse kommt
vom Aufrufer (`load_credentials(..., credentials_cls)`), damit dessen
lazy/optional gebundene Klasse und die Test-Patches daran greifen.
"""

from __future__ import annotations

import json
from typing import Any

from src import keyring_store
from src.oauth_utils import (
    REFRESH_TOKEN_LOCATION, TokenKeyringUnavailable, token_keyring_key,
    write_token, write_token_json,
)


def load_credentials(token_path: str, scopes: list[str],
                     credentials_cls: Any) -> Any | None:
    """Lädt die Credentials aus token.json (+ Schlüsselbund).

    - Alt-Format oder `"file"`: exakt wie bisher
      `credentials_cls.from_authorized_user_file`.
    - `"keyring"`: Refresh-Token aus dem Schlüsselbund einsetzen, dann
      `from_authorized_user_info`.
      - Schlüsselbund antwortet nicht → `TokenKeyringUnavailable` (die Datei
        bleibt unangetastet, kein Consent — Xveyn#129).
      - Eintrag fehlt → `None`, der Aufrufer behandelt das wie „kein Token"
        (vorab geprüft: google-auth würfe sonst `ValueError` „missing fields
        refresh_token", Spec R3).
    """
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        # Unlesbar: dieselbe Reaktion wie vor #101 — die Klasse entscheidet
        # (und wirft ggf. selbst).
        return credentials_cls.from_authorized_user_file(token_path, scopes)
    if not isinstance(info, dict) or info.get(REFRESH_TOKEN_LOCATION) != "keyring":
        return credentials_cls.from_authorized_user_file(token_path, scopes)

    refresh = keyring_store.fetch(token_keyring_key(token_path))
    if refresh is None:
        raise TokenKeyringUnavailable()
    if not refresh:
        return None
    merged = dict(info)
    merged.pop(REFRESH_TOKEN_LOCATION, None)
    merged["refresh_token"] = refresh
    return credentials_cls.from_authorized_user_info(merged, scopes)


def save_credentials(creds: Any, token_path: str) -> None:
    """Speichert die Credentials: Refresh-Token in den Schlüsselbund, der Rest
    gehärtet in token.json. Klappt der Schlüsselbund nicht, wird wie vor #101
    das vollständige JSON geschrieben — ein (rotierter) Refresh-Token geht so
    nie verloren; der nächste Start zieht ihn wieder um."""
    refresh = getattr(creds, "refresh_token", None)
    if (isinstance(refresh, str) and refresh
            and keyring_store.put(token_keyring_key(token_path), refresh)):
        data = json.loads(creds.to_json(strip=["refresh_token"]))
        data[REFRESH_TOKEN_LOCATION] = "keyring"
        write_token_json(json.dumps(data), token_path)
        return
    write_token(creds, token_path)
```

Hinweis zu `isinstance(refresh, str)`: In bestehenden Tests sind die Credentials oft `MagicMock`s. Dort wäre `refresh_token` ein truthy Mock-Objekt. Die Prüfung schickt diese Fälle auf den bisherigen Weg `write_token`, mit unverändertem Verhalten.

- [ ] **Step 4:** In `tests/test_type_annotations.py` `"src/token_store.py",` direkt nach `"src/oauth_utils.py",` einfügen.

- [ ] **Step 5: GREEN** — Run: `python -m pytest tests/test_token_store.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:warnings` · Expected: PASS.

- [ ] **Step 6: Commit** — `feat(oauth): token_store — Refresh-Token im Schlüsselbund, Datei behält den Rest (#101)`.

---

### Task 5: Token-Pfade verdrahten und Fehlerart „Schlüsselbund nicht erreichbar"

**Files:**
- Modify:
  - `src/mail.py` (3 Lade-, 3 Schreibstellen)
  - `src/drive.py` (1 Lade-, 2 Schreibstellen)
  - `src/gcal.py` (1 Lade-, 2 Schreibstellen)
  - `src/background_tasks.py::refresh_token`
  - `src/dialogs/mail_task.py`
  - `src/sync_orchestrator.py`
  - `src/ui.py::_on_reconcile_done`
- Modify (Tests): `tests/test_gcal.py` (3 Patch-Ziele), neue Tests in `tests/test_token_store.py`, `tests/test_mail_task.py`, `tests/test_sync_orchestrator.py`

**Interfaces:**
- Consumes: `load_credentials`, `save_credentials` (Task 4); `TokenKeyringUnavailable`, `KEYRING_UNAVAILABLE_MSG` (Task 3)
- Produces: `classify_sync_error(...)` kennt zusätzlich `"keyring"`; `classify_mail_error` liefert für `TokenKeyringUnavailable` `kind: "keyring"`.

- [ ] **Step 1: Tests schreiben (RED)**

(a) an `tests/test_token_store.py` anhängen:

```python
# --- Verdrahtung: nicht-interaktive Pfade starten keinen Flow (#129) -------


def _keyring_token_that_is_unreachable(tmp_path, fake_keyring):
    fake_keyring()
    path = tmp_path / "token.json"
    save_credentials(_real_creds(), str(path))
    fake_keyring(working=False)
    return path


def test_drive_without_click_raises_unavailable_not_flow(tmp_path, fake_keyring, monkeypatch):
    from tests.conftest import forbid_consent_flow
    from src import drive
    path = _keyring_token_that_is_unreachable(tmp_path, fake_keyring)
    forbid_consent_flow(monkeypatch)

    with pytest.raises(oauth_utils.TokenKeyringUnavailable):
        drive.get_drive_service("credentials.json", str(path))


def test_calendar_without_click_raises_unavailable_not_flow(tmp_path, fake_keyring, monkeypatch):
    from tests.conftest import forbid_consent_flow
    from src import gcal
    path = _keyring_token_that_is_unreachable(tmp_path, fake_keyring)
    forbid_consent_flow(monkeypatch)

    with pytest.raises(oauth_utils.TokenKeyringUnavailable):
        gcal.get_calendar_service("credentials.json", str(path))


def test_start_refresh_is_quiet_when_the_keyring_is_unreachable(tmp_path, fake_keyring):
    from src.mail import refresh_token_if_needed
    path = _keyring_token_that_is_unreachable(tmp_path, fake_keyring)

    with pytest.raises(oauth_utils.TokenKeyringUnavailable):
        refresh_token_if_needed(str(path))


def test_missing_keyring_entry_is_an_auth_error_at_start(tmp_path, fake_keyring):
    from src.mail import TokenAuthError, refresh_token_if_needed
    fake = fake_keyring()
    path = tmp_path / "token.json"
    save_credentials(_real_creds(), str(path))
    fake.store.clear()

    with pytest.raises(TokenAuthError):
        refresh_token_if_needed(str(path))
```

`forbid_consent_flow` ist eine Hilfsfunktion in `tests/conftest.py` (kein Fixture), importiert wie in den bestehenden Tests über `from tests.conftest import …`.

(b) an `tests/test_mail_task.py` anhängen:

```python
def test_classify_keyring_unavailable_has_no_traceback():
    from src.dialogs.mail_task import classify_mail_error
    from src.oauth_utils import TokenKeyringUnavailable
    try:
        raise TokenKeyringUnavailable()
    except TokenKeyringUnavailable as e:
        res = classify_mail_error(e)
    assert res["kind"] == "keyring"
    assert res["tb"] is None
```

(c) an `tests/test_sync_orchestrator.py` anhängen:

```python
def test_keyring_unavailable_is_its_own_kind_as_exception_and_as_text():
    from src.oauth_utils import TokenKeyringUnavailable
    from src.sync_orchestrator import (
        _friendly_sync_message, _short_sync_error, classify_sync_error,
    )
    error = TokenKeyringUnavailable()
    assert classify_sync_error(error) == "keyring"
    assert classify_sync_error(f"{type(error).__name__}: {error}") == "keyring"
    title, _msg, known = _friendly_sync_message(error)
    assert title == "Schlüsselbund nicht erreichbar" and known is True
    assert _short_sync_error(error) == "Der Schlüsselbund ist nicht erreichbar."
```

Run: `python -m pytest tests/test_token_store.py tests/test_mail_task.py tests/test_sync_orchestrator.py -q -p no:warnings` · Expected: die neuen Tests FAIL. Der Grund: Die Builder und `refresh_token_if_needed` laden noch direkt aus der Datei, bekommen den Refresh-Token nicht und laufen in `ValueError` bzw. einen anderen Fehler statt in `TokenKeyringUnavailable`/`TokenAuthError`. `classify_*` kennen `"keyring"` noch nicht.

- [ ] **Step 2: `src/mail.py` verdrahten**

- Import: `from src.oauth_utils import TokenKeyringUnavailable, discard_token_for_scope_upgrade` und `from src.token_store import load_credentials, save_credentials`. `write_token` fällt aus dem Import.
- `fetch_user_email`: `creds = Credentials.from_authorized_user_file(token_path, get_scopes(sync_enabled, gcal_enabled))` → `creds = load_credentials(token_path, get_scopes(sync_enabled, gcal_enabled), Credentials)`. Direkt danach `if creds is None: return ""`. `write_token(creds, token_path)` → `save_credentials(creds, token_path)`. Vor dem bestehenden äußeren `except Exception:` einfügen:
  ```python
      except TokenKeyringUnavailable:
          log.warning("fetch_user_email: Schlüsselbund nicht erreichbar")
          return ""
  ```
- `_refresh_and_persist`: `write_token(creds, token_path)` → `save_credentials(creds, token_path)`.
- `refresh_token_if_needed`: `creds = Credentials.from_authorized_user_file(token_path, scopes)` → `creds = load_credentials(token_path, scopes, Credentials)` und direkt danach:
  ```python
      if creds is None:
          raise TokenAuthError(
              "Der Refresh-Token fehlt im Schlüsselbund des Betriebssystems.")
  ```
  `TokenKeyringUnavailable` wird hier **nicht** gefangen, das tut der Aufrufer (Step 5).
- `get_gmail_service`: `creds = Credentials.from_authorized_user_file(token_path, scopes)` → `creds = load_credentials(token_path, scopes, Credentials)`. `None` läuft in den bestehenden Flow, denn der Aufrufer ist ein Klick. `write_token(creds, token_path)` nach dem Flow → `save_credentials(creds, token_path)`.

- [ ] **Step 3: `src/drive.py` verdrahten**

- Import `write_token` → `forget_token` bleibt aus Task 3; neu: `from src.token_store import load_credentials, save_credentials`.
- `creds = Credentials.from_authorized_user_file(token_path, scopes)` → `creds = load_credentials(token_path, scopes, Credentials)`.
- Beide `write_token(creds, token_path)` → `save_credentials(creds, token_path)`.
- `TokenKeyringUnavailable` propagiert unverändert. Sie ist weder `DriveAuthError` noch ein Flow-Auslöser.

- [ ] **Step 4: `src/gcal.py` verdrahten**

- Import: `write_token` aus dem `oauth_utils`-Import entfernen; `from src.token_store import load_credentials, save_credentials`.
- `creds = Credentials.from_authorized_user_file(token_path, scopes)` → `creds = load_credentials(token_path, scopes, Credentials)`.
- Beide `write_token(creds, token_path)` → `save_credentials(creds, token_path)`.
- In `tests/test_gcal.py` die Patch-Ziele `monkeypatch.setattr(gcal, "write_token", …)` (3×, Z. ~258, ~319, ~361) auf `monkeypatch.setattr(gcal, "save_credentials", …)` umstellen. Die Lambdas und Assertions bleiben unverändert. Das `oauth_utils`-Patch in Z. ~257 bleibt.

- [ ] **Step 5: `src/background_tasks.py::refresh_token`**

- Signatur: `def refresh_token(self, on_auth_error, on_error, on_finished=None):`, Docstring ergänzt um: „`on_finished()` wird nach JEDEM Ausgang gerufen (UI-Thread) — der Umzug der Zugangsdaten hängt daran (#101), damit er nicht parallel zum Start-Refresh token.json schreibt."
- Im Worker `fn` vor `except Exception:`:
  ```python
              except TokenKeyringUnavailable:
                  # Nicht ungültig, nur gerade nicht lesbar — still wie ein
                  # Netzfehler beim Offline-Start; der nächste Zugriff versucht
                  # es erneut.
                  log.warning("Token-Refresh: Schlüsselbund nicht erreichbar")
                  return None
  ```
  Import `from src.oauth_utils import TokenKeyringUnavailable`.
- `on_done` umbauen: Nach der bestehenden Behandlung (auch nach dem frühen `return` bei `outcome is None`) wird `on_finished()` gerufen, falls gesetzt. Also:
  ```python
          def on_done(outcome):
              if outcome is not None:
                  kind, payload = outcome
                  if kind == "auth":
                      on_auth_error(payload)
                  else:
                      on_error(payload)
              if on_finished is not None:
                  on_finished()
  ```

- [ ] **Step 6: Fehlerart „keyring" in Mail und Sync**

- `src/dialogs/mail_task.py::classify_mail_error`: als ersten Zweig
  ```python
      if isinstance(e, TokenKeyringUnavailable):
          return {"ok": False, "kind": "keyring", "error": e, "tb": None,
                  "detail": KEYRING_UNAVAILABLE_MSG}
  ```
  Import `from src.oauth_utils import KEYRING_UNAVAILABLE_MSG, TokenKeyringUnavailable`. Docstring um die Zeile „TokenKeyringUnavailable -> kind "keyring" (Schlüsselbund antwortet nicht; kein Traceback)." ergänzen.
- `src/sync_orchestrator.py`:
  - `classify_sync_error` bekommt als **ersten** Zweig `if KEYRING_UNAVAILABLE_MSG in text: return "keyring"`, dazu den Import aus `oauth_utils` und im Docstring „oder 'keyring'".
  - `_friendly_sync_message`: vor `if kind == "network":`
    ```python
        if kind == "keyring":
            return (
                "Schlüsselbund nicht erreichbar",
                "Die Google-Anmeldung liegt im Schlüsselbund des Betriebssystems, "
                "und der antwortet gerade nicht (gesperrt oder nicht gestartet)."
                "\n\nBitte entsperre ihn und versuche es erneut.",
                True,
            )
    ```
  - `_short_sync_error`: vor `if kind == "network":` die Zeile `if kind == "keyring": return "Der Schlüsselbund ist nicht erreichbar."`
- `src/ui.py::_on_reconcile_done`: zwischen dem `if classify_sync_error(error) == "auth":`-Zweig und `else:` einfügen:
  ```python
              elif classify_sync_error(error) == "keyring":
                  themed_showinfo(
                      self.root,
                      "Schlüsselbund nicht erreichbar",
                      "Die Änderung wurde lokal gespeichert. Der Kalender-Abgleich "
                      "ist fehlgeschlagen, weil der Schlüsselbund des "
                      "Betriebssystems gerade nicht antwortet.\n\nEr wird beim "
                      "nächsten Abgleich automatisch nachgeholt.",
                  )
  ```

- [ ] **Step 7: GREEN + Rest-Check**

Run: `python -m pytest -q -p no:warnings`, `python -m ruff check .`, `npx --yes pyright@1.1.411`
Expected: alles grün.
Git-Bash-Check: `grep -rn "from_authorized_user_file\|write_token(" src --include=*.py` darf nur noch Treffer in `src/token_store.py` und `src/oauth_utils.py` zeigen.

- [ ] **Step 8: Commit** — `feat(oauth): Google-Pfade laden/speichern über token_store; Fehlerart Schlüsselbund (#101)`.

---

### Task 6: `webhook_secrets` — Secret-Regeln, Store-Validierung, Versand

**Files:**
- Create: `src/webhook_secrets.py`, `tests/test_webhook_secrets.py`
- Modify: `src/webhook_store.py::validate_record`, `src/dialogs/send_task.py` (Webhook-Schleife), `tests/test_type_annotations.py` (`"src/webhook_secrets.py",` nach `"src/webhook_store.py",`)

**Interfaces:**
- Consumes: `keyring_store.put/fetch/remove` (Task 2)
- Produces (alle Tk-frei):
  - `SECRET_LOCATION = "secret_location"`
  - `secret_field(record: dict) -> str | None`: `"value"` bei `header`, `"secret"` bei `hmac`, sonst `None`
  - `keyring_key(webhook_id: str) -> str`: `"webhook:" + id`
  - `in_keyring(record: dict) -> bool`
  - `plaintext_secret(record: dict) -> str`: das Klartext-Secret, falls vorhanden und nicht im Schlüsselbund, sonst `""`
  - `stored_in_keyring(record: dict) -> dict`: Kopie ohne Secret-Feld, mit `secret_location = "keyring"`
  - `resolve(record: dict) -> tuple[dict | None, str | None]`: `(record_mit_secret, None)` oder `(None, "unavailable" | "missing")`
  - `persist(candidate: dict, typed: str, stored: dict | None) -> dict`
  - `forget_by_id(webhook_id: str) -> None`
  - `keyring_failure(problem: str) -> dict`: das Ergebnis-Dict eines gescheiterten Kanals

- [ ] **Step 1: Tests schreiben** — `tests/test_webhook_secrets.py`:

```python
"""Webhook-Secrets im Schlüsselbund (#101): das SMTP-Muster für webhooks.json."""

import pytest

from src import keyring_store, webhook_secrets as ws, webhook_store


def _hook(mode="header", **auth):
    base = {"mode": mode}
    if mode == "header":
        base.update(header="Authorization", value="Bearer abc")
    elif mode == "hmac":
        base.update(header="X-Hub-Signature-256", prefix="sha256=", secret="s3cr3t")
    base.update(auth)
    return {"id": "w1", "name": "Ziel", "url": "https://example.org/h",
            "enabled": True, "payload": {"json": True, "pdf": False}, "auth": base}


@pytest.mark.parametrize("mode, field", [("header", "value"), ("hmac", "secret"), ("none", None)])
def test_secret_field(mode, field):
    assert ws.secret_field(_hook(mode)) == field


def test_legacy_record_is_plaintext_and_resolves_to_itself():
    """Kompatibilität: ein Datensatz von heute bleibt unverändert nutzbar."""
    rec = _hook("header")
    assert ws.plaintext_secret(rec) == "Bearer abc"
    assert ws.resolve(rec) == (rec, None)


def test_stored_in_keyring_drops_the_field():
    moved = ws.stored_in_keyring(_hook("hmac"))
    assert "secret" not in moved["auth"]
    assert moved["auth"][ws.SECRET_LOCATION] == "keyring"
    assert moved["auth"]["prefix"] == "sha256="          # Rest bleibt
    assert ws.plaintext_secret(moved) == ""


def test_resolve_fills_the_secret_from_the_keyring(fake_keyring):
    fake_keyring()
    keyring_store.put(ws.keyring_key("w1"), "Bearer xyz")
    rec, problem = ws.resolve(ws.stored_in_keyring(_hook("header")))
    assert problem is None
    assert rec["auth"]["value"] == "Bearer xyz"
    assert ws.SECRET_LOCATION not in rec["auth"]


def test_resolve_reports_unavailable_and_missing(fake_keyring):
    moved = ws.stored_in_keyring(_hook("header"))
    fake_keyring(working=False)
    assert ws.resolve(moved) == (None, "unavailable")
    fake_keyring()
    assert ws.resolve(moved) == (None, "missing")


def test_persist_typed_goes_to_the_keyring(fake_keyring):
    fake = fake_keyring()
    saved = ws.persist(_hook("header", value="Bearer neu"), "Bearer neu", stored=None)
    assert "value" not in saved["auth"]
    assert saved["auth"][ws.SECRET_LOCATION] == "keyring"
    assert fake.store[(keyring_store.SERVICE, "webhook:w1")] == "Bearer neu"


def test_persist_typed_falls_back_to_the_file_without_keyring(fake_keyring):
    fake_keyring(working=False)
    saved = ws.persist(_hook("header", value="Bearer neu"), "Bearer neu", stored=None)
    assert saved["auth"]["value"] == "Bearer neu"
    assert ws.SECRET_LOCATION not in saved["auth"]


def test_persist_empty_keeps_the_keyring_secret(fake_keyring):
    fake = fake_keyring()
    stored = ws.stored_in_keyring(_hook("header"))
    fake.store[(keyring_store.SERVICE, "webhook:w1")] = "Bearer alt"
    candidate = _hook("header")
    del candidate["auth"]["value"]
    candidate["auth"][ws.SECRET_LOCATION] = "keyring"

    saved = ws.persist(candidate, "", stored=stored)

    assert saved["auth"][ws.SECRET_LOCATION] == "keyring"
    assert fake.store[(keyring_store.SERVICE, "webhook:w1")] == "Bearer alt"


def test_persist_switch_to_none_forgets_the_old_entry(fake_keyring):
    fake = fake_keyring()
    stored = ws.stored_in_keyring(_hook("header"))
    fake.store[(keyring_store.SERVICE, "webhook:w1")] = "Bearer alt"

    saved = ws.persist(_hook("none"), "", stored=stored)

    assert saved["auth"] == {"mode": "none"}
    assert (keyring_store.SERVICE, "webhook:w1") not in fake.store


def test_validate_accepts_a_keyring_secret_without_value():
    rec = ws.stored_in_keyring(_hook("header"))
    assert webhook_store.validate_record(rec, []) == (True, "")


def test_validate_still_demands_a_value_in_file_mode():
    rec = _hook("header", value="")
    ok, _msg = webhook_store.validate_record(rec, [])
    assert ok is False


def test_keyring_failure_texts():
    assert ws.keyring_failure("unavailable")["kind"] == "keyring"
    assert "neu eingeben" in ws.keyring_failure("missing")["detail"]
```

Zusätzlich an `tests/test_send_task_dispatch.py` anhängen (nutzt dessen `_kwargs`/`_patch_mail_ok`):

```python
def _keyring_hook(name="Tresor"):
    entry = _hook(name)
    entry["record"]["auth"] = {"mode": "header", "header": "Authorization",
                               "secret_location": "keyring"}
    return entry


def test_webhook_with_unreachable_keyring_is_not_sent_without_auth(monkeypatch):
    _patch_mail_ok(monkeypatch)
    monkeypatch.setattr(st.webhook, "deliver", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("ohne Secret darf nicht gesendet werden")))
    res = perform_send(**_kwargs(webhooks=[_keyring_hook()]))
    hook = next(r for r in res["results"] if r["name"] == "Tresor")
    assert hook["ok"] is False and hook["kind"] == "keyring"


def test_webhook_secret_is_resolved_before_delivery(monkeypatch, fake_keyring):
    from src import keyring_store
    _patch_mail_ok(monkeypatch)
    fake_keyring()
    keyring_store.put("webhook:Tresor", "Bearer aus-dem-schluesselbund")
    seen = []
    monkeypatch.setattr(st.webhook, "deliver",
                        lambda record, **k: seen.append(record) or {"ok": True, "status": 200})
    perform_send(**_kwargs(webhooks=[_keyring_hook()]))
    assert seen[0]["auth"]["value"] == "Bearer aus-dem-schluesselbund"
    assert "secret_location" not in seen[0]["auth"]
```

- [ ] **Step 2: RED** — Run: `python -m pytest tests/test_webhook_secrets.py -q -p no:warnings` · Expected: ERROR `ModuleNotFoundError: No module named 'src.webhook_secrets'`.

- [ ] **Step 3: Implementieren** — `src/webhook_secrets.py`:

```python
"""Webhook-Secrets im Schlüsselbund (#101) — das SMTP-Muster für webhooks.json.

`auth.value` (Token im Header) bzw. `auth.secret` (HMAC) wandern in den
Schlüsselbund; im Datensatz bleibt `auth.secret_location = "keyring"`. Fehlt
das Feld (Alt-Format), steht das Secret wie bisher im Klartext im Datensatz.

`webhook_store` bleibt reine Dateipersistenz und fasst den Schlüsselbund
nicht an — dieselbe Trennung wie `smtp_store`/`keyring_store`. Alles hier
kann blockieren (Schlüsselbund-Watchdog) und läuft deshalb im Worker.
"""

from __future__ import annotations

import copy
from typing import Any

from src import keyring_store

SECRET_LOCATION = "secret_location"

_FIELDS = {"header": "value", "hmac": "secret"}


def secret_field(record: dict[str, Any]) -> str | None:
    """Das Secret-Feld des Auth-Verfahrens, oder None (`none`)."""
    return _FIELDS.get((record.get("auth") or {}).get("mode", "none"))


def keyring_key(webhook_id: str) -> str:
    """Schlüssel im Schlüsselbund; das Präfix trennt ihn von SMTP-Konten."""
    return f"webhook:{webhook_id}"


def in_keyring(record: dict[str, Any]) -> bool:
    return (record.get("auth") or {}).get(SECRET_LOCATION) == "keyring"


def plaintext_secret(record: dict[str, Any]) -> str:
    """Das im Datensatz stehende Secret, oder "" (keins/im Schlüsselbund)."""
    field = secret_field(record)
    if field is None or in_keyring(record):
        return ""
    return str((record.get("auth") or {}).get(field) or "")


def stored_in_keyring(record: dict[str, Any]) -> dict[str, Any]:
    """Kopie in Schlüsselbund-Form: ohne Secret-Feld, mit Ort-Markierung."""
    out = copy.deepcopy(record)
    auth = out.setdefault("auth", {})
    field = secret_field(out)
    if field is not None:
        auth.pop(field, None)
    auth[SECRET_LOCATION] = "keyring"
    return out


def resolve(record: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Datensatz fürs Senden: das Secret eingesetzt.

    `(record, None)` — sendefertig (Alt-Format unverändert).
    `(None, "unavailable")` — Schlüsselbund antwortet nicht.
    `(None, "missing")` — Eintrag fehlt (z. B. im Credential Manager gelöscht).
    Nie ohne Secret senden: der Endpunkt antwortete 401, und der Nutzer
    suchte beim Token, obwohl der Schlüsselbund das Problem war.
    """
    field = secret_field(record)
    if field is None or not in_keyring(record):
        return record, None
    value = keyring_store.fetch(keyring_key(record["id"]))
    if value is None:
        return None, "unavailable"
    if not value:
        return None, "missing"
    out = copy.deepcopy(record)
    out["auth"].pop(SECRET_LOCATION, None)
    out["auth"][field] = value
    return out, None


def persist(candidate: dict[str, Any], typed: str,
            stored: dict[str, Any] | None) -> dict[str, Any]:
    """Entscheidet, wo das Secret landet, und legt es ab (wie
    `keyring_store.persist_password`). Verändert `candidate` nicht.

    - Verfahren ohne Secret (`none`): Datensatz ohne Secret; ein altes
      Schlüsselbund-Secret wird abgeräumt.
    - `typed` gefüllt: in den Schlüsselbund; klappt das nicht, in den
      Datensatz (Alt-Format). Ein älterer Schlüsselbund-Eintrag wird dann
      abgeräumt, sonst gälte er als veraltete zweite Quelle.
    - `typed` leer und `candidate` trägt die Schlüsselbund-Markierung
      (Dialog: „leer lassen = unverändert"): unverändert im Schlüsselbund.
    """
    field = secret_field(candidate)
    if field is None:
        out = copy.deepcopy(candidate)
        out.get("auth", {}).pop(SECRET_LOCATION, None)
        if stored is not None and in_keyring(stored):
            keyring_store.remove(keyring_key(candidate["id"]))
        return out
    if typed:
        with_secret = copy.deepcopy(candidate)
        with_secret["auth"][field] = typed
        with_secret["auth"].pop(SECRET_LOCATION, None)
        if keyring_store.put(keyring_key(candidate["id"]), typed):
            return stored_in_keyring(with_secret)
        if stored is not None and in_keyring(stored):
            keyring_store.remove(keyring_key(candidate["id"]))
        return with_secret
    return copy.deepcopy(candidate)


def forget_by_id(webhook_id: str) -> None:
    """Nach dem Löschen eines Webhooks: den Eintrag abräumen (wie
    `tab_smtp._delete_secret` — ein fehlender Eintrag ist kein Fehler)."""
    keyring_store.remove(keyring_key(webhook_id))


def keyring_failure(problem: str) -> dict[str, Any]:
    """Ergebnis-Dict eines Webhook-Kanals, dessen Secret nicht lesbar war."""
    detail = ("Die Zugangsdaten konnten nicht aus dem Schlüsselbund gelesen "
              "werden." if problem == "unavailable" else
              "Die Zugangsdaten fehlen im Schlüsselbund — Webhook bearbeiten "
              "und neu eingeben.")
    return {"ok": False, "kind": "keyring", "error": None, "tb": None,
            "detail": detail}
```

- [ ] **Step 4: `webhook_store.validate_record`**

In den Zweigen `header`/`hmac` die Prüfung des Werts bzw. des Secrets überspringen, wenn es im Schlüsselbund liegt:

```python
    keyring_held = auth.get("secret_location") == "keyring"
    if mode == "header":
        if not (auth.get("header") or "").strip():
            return False, "Bitte einen Header-Namen angeben."
        if not keyring_held and not (auth.get("value") or "").strip():
            return False, "Bitte einen Header-Wert (Token) angeben."
    elif mode == "hmac":
        if not (auth.get("header") or "").strip():
            return False, "Bitte einen Header-Namen angeben."
        if not keyring_held and not (auth.get("secret") or "").strip():
            return False, "Bitte ein Secret für die Signatur angeben."
```

Den String `"secret_location"` hier als Literal lassen, statt `webhook_secrets` zu importieren. `webhook_store` bleibt so frei von Schlüsselbund-Code, und `webhook_secrets` importiert `webhook_store` nicht. Kommentar: `# „secret_location" wie webhook_secrets.SECRET_LOCATION — hier als Literal, damit der Store frei von Schlüsselbund-Code bleibt.`

- [ ] **Step 5: `send_task` — Secret im Worker auflösen**

In der Schleife `for entry in webhooks:` vor dem `try:` einfügen:

```python
        record, problem = webhook_secrets.resolve(entry["record"])
        if problem is not None:
            results.append({"channel": "webhook",
                            "name": entry["record"].get("name", ""),
                            **webhook_secrets.keyring_failure(problem)})
            continue
```

Die bestehende Zeile `record = entry["record"]` entfällt dadurch. Das Log danach verwendet weiter `record.get("name")`. Import: `from src import keyring_store, smtp, webhook, webhook_secrets`.

- [ ] **Step 6:** Whitelist-Eintrag `"src/webhook_secrets.py",` in `tests/test_type_annotations.py`.

- [ ] **Step 7: GREEN** — Run: `python -m pytest -q -p no:warnings`, `python -m ruff check .`, `npx --yes pyright@1.1.411` · Expected: grün.

- [ ] **Step 8: Commit** — `feat(webhooks): Secrets im Schlüsselbund — Regeln, Validierung, Versand (#101)`.

---

### Task 7: Webhook-Dialog und Lösch-Hook

**Files:**
- Modify: `src/dialogs/webhook_dialog.py`, `src/dialogs/settings_dialog/tab_webhooks.py`

**Interfaces:**
- Consumes: `webhook_secrets.in_keyring/persist/resolve/keyring_failure/forget_by_id/SECRET_LOCATION` (Task 6)

Dieser Task ist Tk-Code und hat keine eigenen Unit-Tests (CLAUDE.md, „Getestet wird Logik, nicht UI"). Die Logik steckt in Task 6, geprüft wird sie in Task 10 im echten Dialog.

- [ ] **Step 1: Vorbefüllen abschalten, Hinweis zeigen** (`open_webhook_dialog`)

- Nach `auth = dict(record.get("auth") or {"mode": "none"})`:
  ```python
      stored = None if is_new else dict(record)
      # Liegt das Secret im Schlüsselbund, steht es nicht im Datensatz — das
      # Feld bleibt leer, „leer lassen = unverändert" (wie im SMTP-Dialog).
      stored_in_keyring = stored is not None and webhook_secrets.in_keyring(stored)
      stored_mode = auth.get("mode", "none")
  ```
- `value_var` und `secret_var` werden weiter aus `auth.get(...)` vorbelegt. Liegt das Secret im Schlüsselbund, fehlen diese Felder im Datensatz, also ergibt sich `""` von selbst. Keine Änderung nötig, nur einen Kommentar ergänzen.
- In `_rebuild_auth_fields`, nachdem die Felder für `header`/`hmac` gebaut sind: Wenn `stored_in_keyring` gilt **und** der aktuell gewählte Modus gleich `stored_mode` ist, kommt unter das Secret-Feld ein Label (`font=FONT_SMALL`, `fg=TEXT_MUTED`, `justify="left"`, `wraplength=380`) mit dem Text „Liegt im Schlüsselbund des Betriebssystems. Leer lassen = unverändert." Es wird in dasselbe `auth_frame` gegriddet, in die nächste freie Zeile.

- [ ] **Step 2: `_collect` kennzeichnet „unverändert"**

Die Zweige `header`/`hmac` so ändern, dass bei leerem Eingabefeld mit gespeichertem Schlüsselbund-Secret desselben Modus die Markierung gesetzt wird statt eines leeren Werts:

```python
        mode = _mode_for_label(mode_var.get())
        new_auth = {"mode": mode}
        typed = ""
        if mode == "header":
            typed = value_var.get()
            new_auth.update(header=header_var.get().strip(), value=typed)
        elif mode == "hmac":
            typed = secret_var.get()
            new_auth.update(header=header_var.get().strip(),
                            prefix=prefix_var.get(), secret=typed)
        if mode in ("header", "hmac") and not typed.strip() \
                and stored_in_keyring and mode == stored_mode:
            new_auth.pop("value", None)
            new_auth.pop("secret", None)
            new_auth[webhook_secrets.SECRET_LOCATION] = "keyring"
```

`_collect` liefert zusätzlich `typed`, also `return {...}, typed` statt `return {...}`. `_validated` und ihre beiden Aufrufer passen sich an:

```python
    def _validated():
        candidate, typed = _collect()
        ok, msg = webhook_store.validate_record(candidate, store.get_all())
        if not ok:
            themed_showerror(dialog, "Eingabe unvollständig", msg)
            return None
        return candidate, typed
```

In `do_save` und `do_test` wird aus `candidate = _validated()` / `if candidate is None: return` jeweils:

```python
        validated = _validated()
        if validated is None:
            return
        candidate, typed = validated
```

(`do_test` braucht `typed` nicht: `resolve` entscheidet anhand der Markierung im `candidate`.)

- [ ] **Step 3: Speichern über `persist`** (`do_save` → `fn`)

```python
        def fn():
            try:
                to_save = webhook_secrets.persist(candidate, typed, stored)
                store.save(to_save)
            except (webhook_store.WebhookStoreReadOnly, OSError) as e:
                return {"ok": False, "error": e}
            return {"ok": True}
```

- [ ] **Step 4: Test-Versand über `resolve`** (`do_test` → `fn`)

```python
        def fn():
            record_for_send, problem = webhook_secrets.resolve(candidate)
            if problem is not None:
                return webhook_secrets.keyring_failure(problem)
            return webhook.deliver(
                record_for_send,
                json_bytes=body if candidate["payload"]["json"] else None,
                pdf_bytes=b"%PDF-1.4\n% Testversand\n"
                if candidate["payload"]["pdf"] else None,
                pdf_filename="Zeiterfassung_Test.pdf")
```

Import im Dialog: `from src import webhook, webhook_secrets, webhook_store`.

- [ ] **Step 5: Lösch-Hook** — `src/dialogs/settings_dialog/tab_webhooks.py`:

```python
def _forget_secret(webhook_id):
    # Wie tab_smtp._delete_secret: erst NACH dem erfolgreichen Schreiben
    # (remove_record ruft den Hook nur dann), und ein fehlender Eintrag ist
    # kein Fehler. Für Webhooks ohne Schlüsselbund-Secret ein No-op.
    webhook_secrets.forget_by_id(webhook_id)
```

Das kommt in `WEBHOOKS_KIND` als `after_delete=_forget_secret`, Import `from src import webhook_secrets, webhook_store`. Die Charakterisierungstests aus R12 (`tests/test_record_list_tabs.py::test_webhook_remove_never_touches_the_keyring`) patchen `keyring_store.delete_secret`. Der Hook ruft aber `keyring_store.remove`, der Test bleibt also grün. **Den Test nicht anpassen.** Seine Aussage „Webhooks fassen `delete_secret` nicht an" stimmt weiter, und das Abräumen prüft Task 6.

- [ ] **Step 6: GREEN** — volle Suite, ruff, pyright · Expected: grün.

- [ ] **Step 7: Commit** — `feat(webhooks): Dialog füllt Secrets nicht mehr vor, Löschen räumt den Schlüsselbund ab (#101)`.

---

### Task 8: `secret_migration` — Umzug beim Start

**Files:**
- Create: `src/secret_migration.py`, `tests/test_secret_migration.py`
- Modify: `tests/test_type_annotations.py` (`"src/secret_migration.py",`)

**Interfaces:**
- Consumes:
  - `keyring_store.put/fetch` (Task 2)
  - `oauth_utils.REFRESH_TOKEN_LOCATION/token_keyring_key/write_token_json` (Task 3)
  - `webhook_secrets.plaintext_secret/secret_field/keyring_key/stored_in_keyring` (Task 6)
  - `webhook_store.WebhookStore.get_all/save`, `WebhookStoreReadOnly`
- Produces:
  - `@dataclass(frozen=True) class MigrationReport` mit den Feldern `token_moved: bool = False`, `webhooks_moved: tuple[str, ...] = ()`, `failures: tuple[str, ...] = ()` und der Property `moved_anything -> bool`
  - `migrate(token_path: str, webhook_store: Any | None) -> MigrationReport`
  - `notice(report: MigrationReport, system: str) -> tuple[str, str]` liefert Titel und Text
  - `toast_text(report: MigrationReport) -> str`

- [ ] **Step 1: Tests schreiben** — `tests/test_secret_migration.py`:

```python
"""Umzug der Zugangsdaten in den Schlüsselbund beim Start (#101)."""

import json

from src import keyring_store, oauth_utils, secret_migration as sm, webhook_secrets as ws
from src.webhook_store import WebhookStore


def _token(tmp_path, **extra):
    path = tmp_path / "token.json"
    data = {"token": "ya29.a", "refresh_token": "1//r", "client_id": "c",
            "client_secret": "s", "token_uri": "https://oauth2.googleapis.com/token"}
    data.update(extra)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _store(tmp_path, *records):
    store = WebhookStore(str(tmp_path / "webhooks.json"))
    for r in records:
        store.save(r)
    return store


def _hook(hid="w1", name="Ziel", value="Bearer abc"):
    return {"id": hid, "name": name, "url": "https://example.org/h", "enabled": True,
            "payload": {"json": True, "pdf": False},
            "auth": {"mode": "header", "header": "Authorization", "value": value}}


def test_moves_token_and_webhooks(tmp_path, fake_keyring):
    fake = fake_keyring()
    token = _token(tmp_path)
    store = _store(tmp_path, _hook())

    report = sm.migrate(str(token), store)

    assert report.token_moved and report.webhooks_moved == ("Ziel",)
    data = json.loads(token.read_text(encoding="utf-8"))
    assert "refresh_token" not in data and data["token"] == "ya29.a"
    assert data[oauth_utils.REFRESH_TOKEN_LOCATION] == "keyring"
    assert fake.store[(keyring_store.SERVICE, oauth_utils.token_keyring_key(str(token)))] == "1//r"
    saved = store.get_all()[0]
    assert "value" not in saved["auth"] and ws.in_keyring(saved)
    assert fake.store[(keyring_store.SERVICE, "webhook:w1")] == "Bearer abc"


def test_nothing_to_move_never_touches_the_keyring(tmp_path, monkeypatch):
    """Ohne Klartext-Funde wird der Schlüsselbund gar nicht gefragt — sonst
    löste jeder normale Start auf macOS einen Keychain-Dialog aus."""
    calls = []
    monkeypatch.setattr(keyring_store, "put", lambda *a: calls.append(("put", a)))
    monkeypatch.setattr(keyring_store, "fetch", lambda *a: calls.append(("fetch", a)))
    report = sm.migrate(str(tmp_path / "token.json"), _store(tmp_path))
    assert not report.moved_anything and calls == []


def test_without_keyring_everything_stays(tmp_path, fake_keyring):
    fake_keyring(working=False)
    token = _token(tmp_path)
    before = token.read_bytes()
    store = _store(tmp_path, _hook())

    report = sm.migrate(str(token), store)

    assert not report.moved_anything
    assert token.read_bytes() == before
    assert store.get_all()[0]["auth"]["value"] == "Bearer abc"


def test_readback_mismatch_leaves_the_files(tmp_path, fake_keyring):
    fake_keyring(lie=True)
    token = _token(tmp_path)
    before = token.read_bytes()

    report = sm.migrate(str(token), _store(tmp_path))

    assert not report.token_moved and report.failures
    assert token.read_bytes() == before


def test_changed_token_between_check_and_write_is_not_moved(tmp_path, fake_keyring, monkeypatch):
    """Ein Refresh hat token.json zwischendurch neu geschrieben (rotiert)."""
    fake_keyring()
    token = _token(tmp_path)
    orig_fetch = keyring_store.fetch

    def fetch_and_rotate(key):
        value = orig_fetch(key)
        _token(tmp_path, refresh_token="1//rotiert")
        return value

    monkeypatch.setattr(keyring_store, "fetch", fetch_and_rotate)
    report = sm.migrate(str(token), _store(tmp_path))

    assert not report.token_moved
    assert json.loads(token.read_text(encoding="utf-8"))["refresh_token"] == "1//rotiert"


def test_partial_failure_still_moves_the_rest(tmp_path, fake_keyring, monkeypatch):
    fake_keyring()
    token = _token(tmp_path)
    store = _store(tmp_path, _hook())

    def broken_write(*a, **k):
        raise OSError("Platte voll")

    monkeypatch.setattr(sm, "write_token_json", broken_write)
    report = sm.migrate(str(token), store)

    assert not report.token_moved and report.webhooks_moved == ("Ziel",)
    assert "Google-Anmeldung" in report.failures
    assert json.loads(token.read_text(encoding="utf-8"))["refresh_token"] == "1//r"


def test_second_run_does_nothing(tmp_path, fake_keyring):
    fake_keyring()
    token = _token(tmp_path)
    store = _store(tmp_path, _hook())
    sm.migrate(str(token), store)

    assert sm.migrate(str(token), store) == sm.MigrationReport()


def test_crash_after_put_leaves_a_valid_file_and_is_retried(tmp_path, fake_keyring, monkeypatch):
    fake_keyring()
    token = _token(tmp_path)

    def crash(*a, **k):
        raise KeyboardInterrupt  # Abbruch zwischen put/fetch und Datei-Schreiben

    monkeypatch.setattr(sm, "write_token_json", crash)
    try:
        sm.migrate(str(token), None)
    except KeyboardInterrupt:
        pass
    assert json.loads(token.read_text(encoding="utf-8"))["refresh_token"] == "1//r"

    monkeypatch.undo()
    fake_keyring()
    assert sm.migrate(str(token), None).token_moved


def test_notice_texts():
    report = sm.MigrationReport(token_moved=True, webhooks_moved=("A", "B"))
    title, text = sm.notice(report, "Windows")
    assert title == "Zugangsdaten im Schlüsselbund"
    assert "Google-Anmeldung" in text and "2 Webhooks" in text
    assert "macOS" not in text
    _t, mac = sm.notice(report, "Darwin")
    assert "nach App-Updates" in mac
    assert sm.toast_text(report) == "Zugangsdaten liegen jetzt im Schlüsselbund."
```

Hinweis zu `test_crash_after_put…`: `monkeypatch.undo()` stellt auch das Fake-Keyring-Modul zurück, also auf das autouse-„nicht verfügbar". Deshalb wird danach `fake_keyring()` erneut installiert. Das zweite `fake_keyring()` startet mit leerem Store, das ist egal, weil der Umzug neu schreibt.

- [ ] **Step 2: RED** — Run: `python -m pytest tests/test_secret_migration.py -q -p no:warnings` · Expected: ERROR `ModuleNotFoundError: No module named 'src.secret_migration'`.

- [ ] **Step 3: Implementieren** — `src/secret_migration.py`:

```python
"""Umzug der Zugangsdaten in den Schlüsselbund beim Start (#101).

Idempotent und bei jedem Start geprüft — kein Versionsvergleich nötig: der
erste Start nach dem Update zieht um, und ebenso ein Linux-System, das erst
später einen Secret Service bekommt. Pro Secret: in den Schlüsselbund
schreiben, zurücklesen, NUR bei Übereinstimmung die Datei neu schreiben.
Jeder Abbruch davor lässt die Datei gültig; der nächste Start holt nach.

Der Schlüsselbund wird nur gefragt, wenn es etwas umzuziehen gibt — sonst
löste jeder normale Start auf macOS einen Keychain-Dialog aus (Spec, R4).
Tk-frei; läuft im BackgroundTaskRunner, nie vor dem Tk-Aufbau.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from src import keyring_store, webhook_secrets
from src.oauth_utils import REFRESH_TOKEN_LOCATION, token_keyring_key, write_token_json
from src.webhook_store import WebhookStoreReadOnly

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MigrationReport:
    token_moved: bool = False
    webhooks_moved: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()

    @property
    def moved_anything(self) -> bool:
        return self.token_moved or bool(self.webhooks_moved)


def _read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _plaintext_refresh_token(token_path: str) -> str:
    data = _read_json(token_path)
    if not isinstance(data, dict) or data.get(REFRESH_TOKEN_LOCATION) == "keyring":
        return ""
    token = data.get("refresh_token")
    return token if isinstance(token, str) else ""


def _stored_and_verified(key: str, secret: str) -> bool:
    if not keyring_store.put(key, secret):
        return False
    if keyring_store.fetch(key) != secret:
        log.warning("Schlüsselbund liefert nach dem Schreiben einen anderen "
                    "Wert — Umzug unterbleibt")
        return False
    return True


def _move_token(token_path: str, secret: str) -> bool:
    if not _stored_and_verified(token_keyring_key(token_path), secret):
        return False
    data = _read_json(token_path)
    if not isinstance(data, dict) or data.get("refresh_token") != secret:
        # Zwischendurch neu geschrieben (Refresh, Rotation): der nächste
        # Start zieht den dann gültigen Token um.
        log.info("token.json hat sich während des Umzugs geändert")
        return False
    data.pop("refresh_token")
    data[REFRESH_TOKEN_LOCATION] = "keyring"
    try:
        write_token_json(json.dumps(data), token_path)
    except OSError:
        log.warning("token.json ließ sich nach dem Umzug nicht schreiben",
                    exc_info=True)
        return False
    return True


def _move_webhook(store: Any, record: dict[str, Any]) -> bool:
    secret = webhook_secrets.plaintext_secret(record)
    if not _stored_and_verified(webhook_secrets.keyring_key(record["id"]), secret):
        return False
    current = next((r for r in store.get_all() if r.get("id") == record["id"]), None)
    if current is None or webhook_secrets.plaintext_secret(current) != secret:
        log.info("Ein Webhook hat sich während des Umzugs geändert")
        return False
    try:
        store.save(webhook_secrets.stored_in_keyring(current))
    except (WebhookStoreReadOnly, OSError):
        log.warning("webhooks.json ließ sich nach dem Umzug nicht schreiben",
                    exc_info=True)
        return False
    return True


def migrate(token_path: str, webhook_store: Any | None) -> MigrationReport:
    """Zieht Klartext-Secrets um. Ohne Funde bleibt der Schlüsselbund
    unberührt und der Bericht leer."""
    token_secret = _plaintext_refresh_token(token_path)
    records = webhook_store.get_all() if webhook_store is not None else []
    pending = [r for r in records if webhook_secrets.plaintext_secret(r)]
    if not token_secret and not pending:
        return MigrationReport()

    failures: list[str] = []
    token_moved = False
    if token_secret:
        token_moved = _move_token(token_path, token_secret)
        if not token_moved:
            failures.append("Google-Anmeldung")
    moved: list[str] = []
    for record in pending:
        if _move_webhook(webhook_store, record):
            moved.append(str(record.get("name", "")))
        else:
            failures.append(f"Webhook „{record.get('name', '')}“")
    return MigrationReport(token_moved, tuple(moved), tuple(failures))


def notice(report: MigrationReport, system: str) -> tuple[str, str]:
    """Titel und Text des einmaligen Hinweises nach einem Umzug."""
    parts = []
    if report.token_moved:
        parts.append("deine Google-Anmeldung")
    n = len(report.webhooks_moved)
    if n:
        parts.append(f"die Zugangsdaten von {n} Webhook" + ("s" if n > 1 else ""))
    what = " und ".join(parts)
    text = (f"{what[:1].upper()}{what[1:]} "
            f"{'liegen' if len(parts) > 1 or n > 1 else 'liegt'} jetzt im "
            "Schlüsselbund des Betriebssystems statt im Klartext im Datenordner.")
    if system == "Darwin":
        text += ("\n\nmacOS kann nach App-Updates erneut fragen, ob Zeiterfassung "
                 "auf den Schlüsselbund zugreifen darf.")
    return "Zugangsdaten im Schlüsselbund", text


def toast_text(report: MigrationReport) -> str:
    """Kurzform für den Tray-Toast (Autostart mit --minimized)."""
    return "Zugangsdaten liegen jetzt im Schlüsselbund."
```

Hinweis zu `notice`: Der Test erwartet „2 Webhooks" im Text. Für n > 1 ergibt „von 2 Webhooks" diesen Teilstring. Das Verb lautet bei mehreren Teilen oder mehreren Webhooks „liegen", sonst „liegt".

- [ ] **Step 4:** Whitelist-Eintrag `"src/secret_migration.py",`.

- [ ] **Step 5: GREEN** — Run: `python -m pytest tests/test_secret_migration.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:warnings` · Expected: PASS.

- [ ] **Step 6: Commit** — `feat: Zugangsdaten beim Start in den Schlüsselbund umziehen (#101)`.

---

### Task 9: Umzug beim Start anstoßen, Hinweis zeigen

**Files:**
- Modify: `src/background_tasks.py` (neuer Task `migrate_secrets`), `src/ui.py` (`refresh_token`-Aufruf, neue Methode `_on_secrets_migrated`)
- Test: `tests/test_background_tasks.py` (anhängen; existiert sie nicht, anlegen mit dem `_FakeRunner`-Muster aus `tests/test_update_coordinator.py`), `tests/test_ui_update_wiring.py` oder neue `tests/test_ui_secret_notice.py`

**Interfaces:**
- Consumes: `secret_migration.migrate/notice/toast_text/MigrationReport` (Task 8); `refresh_token(..., on_finished=)` (Task 5)
- Produces: `BackgroundTaskRunner.migrate_secrets(webhook_store, on_done) -> None`; `App._on_secrets_migrated(report) -> None`

- [ ] **Step 1: Tests schreiben**

```python
# tests/test_background_tasks.py — anhängen
def test_migrate_secrets_reports_only_real_moves(tmp_path, monkeypatch):
    from src import background_tasks, secret_migration

    reports = []
    runner = background_tasks.BackgroundTaskRunner.__new__(background_tasks.BackgroundTaskRunner)
    runner._base_path = str(tmp_path)
    runner.run = lambda fn, on_done=None: on_done(fn())
    monkeypatch.setattr(secret_migration, "migrate",
                        lambda path, store: secret_migration.MigrationReport(token_moved=True))

    runner.migrate_secrets(object(), reports.append)

    assert reports == [secret_migration.MigrationReport(token_moved=True)]


def test_migrate_secrets_swallows_and_logs_unexpected_errors(tmp_path, monkeypatch, caplog):
    from src import background_tasks, secret_migration

    reports = []
    runner = background_tasks.BackgroundTaskRunner.__new__(background_tasks.BackgroundTaskRunner)
    runner._base_path = str(tmp_path)
    runner.run = lambda fn, on_done=None: on_done(fn())

    def boom(*a):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(secret_migration, "migrate", boom)
    runner.migrate_secrets(object(), reports.append)

    assert reports == []
    assert "Umzug der Zugangsdaten" in caplog.text
```

```python
# tests/test_ui_secret_notice.py — neu
from unittest.mock import MagicMock

from src.secret_migration import MigrationReport
from src.ui import App


def _app(state="normal", tray=None):
    fake = MagicMock()
    fake.root.state.return_value = state
    fake._tray = tray
    return fake


def test_notice_is_a_dialog_when_the_window_is_visible(monkeypatch):
    shown = []
    monkeypatch.setattr("src.ui.themed_showinfo", lambda *a: shown.append(a))
    fake = _app("normal")
    App._on_secrets_migrated(fake, MigrationReport(token_moved=True))
    assert len(shown) == 1 and shown[0][1] == "Zugangsdaten im Schlüsselbund"


def test_notice_is_a_toast_when_started_minimized(monkeypatch):
    shown = []
    monkeypatch.setattr("src.ui.themed_showinfo", lambda *a: shown.append(a))
    tray = MagicMock()
    App._on_secrets_migrated(_app("withdrawn", tray), MigrationReport(token_moved=True))
    assert shown == []
    tray.notify.assert_called_once_with("Zugangsdaten liegen jetzt im Schlüsselbund.")


def test_notice_is_a_dialog_for_a_maximized_window(monkeypatch):
    shown = []
    monkeypatch.setattr("src.ui.themed_showinfo", lambda *a: shown.append(a))
    App._on_secrets_migrated(_app("zoomed"), MigrationReport(token_moved=True))
    assert len(shown) == 1


def test_no_notice_when_nothing_moved(monkeypatch):
    shown = []
    monkeypatch.setattr("src.ui.themed_showinfo", lambda *a: shown.append(a))
    tray = MagicMock()
    App._on_secrets_migrated(_app("normal", tray), MigrationReport())
    assert shown == [] and not tray.notify.called
```

- [ ] **Step 2: RED** — Run: `python -m pytest tests/test_background_tasks.py tests/test_ui_secret_notice.py -q -p no:warnings` · Expected: FAIL (`AttributeError: … migrate_secrets` / `_on_secrets_migrated`).

- [ ] **Step 3: `BackgroundTaskRunner.migrate_secrets`** (nach `refresh_token`)

```python
    def migrate_secrets(self, webhook_store, on_done):
        """Zieht Klartext-Zugangsdaten in den Schlüsselbund (#101). Im Worker
        (der Schlüsselbund kann bis zum Watchdog blockieren); `on_done(report)`
        im UI-Thread. Ein unerwarteter Fehler wird geloggt und verschluckt —
        der Umzug ist ein Zusatz, nichts hängt von ihm ab, und der nächste
        Start versucht es erneut."""
        token_path = os.path.join(self._base_path, "token.json")

        def fn():
            try:
                return secret_migration.migrate(token_path, webhook_store)
            except Exception:
                log.exception("Umzug der Zugangsdaten fehlgeschlagen")
                return None

        def done(report):
            if report is not None:
                on_done(report)

        self.run(fn, done)
```

Import `from src import secret_migration`.

- [ ] **Step 4: `App` verdrahten** (`src/ui.py`)

- Im Aufruf `self._bg.refresh_token(...)` in `__init__` als dritten Parameter ergänzen:
  ```python
              # Erst NACH dem Start-Refresh: beide schreiben token.json (#101).
              on_finished=lambda: self._bg.migrate_secrets(
                  self._webhook_store, self._on_secrets_migrated),
  ```
- Neue Methode (neben `_on_reconcile_start_done`):
  ```python
      def _on_secrets_migrated(self, report):
          """Einmaliger Hinweis, wenn Zugangsdaten in den Schlüsselbund
          umgezogen sind (#101). Sichtbares Fenster → Dialog; beim Start in den
          Tray (--minimized) → Toast statt Pop-up; sonst nur das Log."""
          if not report.moved_anything:
              return
          # "zoomed": maximiertes Fenster unter Windows — ebenfalls sichtbar.
          if self.root.state() in ("normal", "zoomed"):
              title, text = secret_migration.notice(report, platform.system())
              themed_showinfo(self.root, title, text)
          elif self._tray is not None:
              self._tray.notify(secret_migration.toast_text(report))
          else:
              logging.getLogger(__name__).info(
                  "Zugangsdaten in den Schlüsselbund umgezogen")
  ```
  Import `from src import secret_migration`.

- [ ] **Step 5: GREEN** — volle Suite, ruff, pyright · Expected: grün.

- [ ] **Step 6: Commit** — `feat: Umzug nach dem Start-Refresh anstoßen, Hinweis als Dialog oder Toast (#101)`.

---

### Task 10: Doku und Verifikation in der echten App

**Files:**
- Modify: `CLAUDE.md`, `src/CLAUDE.md`, `docs/known-limitations.md`

- [ ] **Step 1: `CLAUDE.md`**
- **Strukturliste:**
  - neue Einträge für `src/token_store.py` (Refresh-Token im Schlüsselbund, Rest in der Datei, warum nur der Refresh-Token), `src/webhook_secrets.py` (SMTP-Muster für Webhooks) und `src/secret_migration.py` (idempotenter Umzug beim Start, Hinweis);
  - den Eintrag `keyring_store` um `put`/`fetch`/`remove` ergänzen;
  - den Eintrag `secure_file` anpassen: Welche der vier Secret-Dateien tragen noch Klartext? Nur ohne Schlüsselbund.
- **Abschnitt „Installation & Daten":** ein Satz dazu, dass `token.json`/`webhooks.json` bei verfügbarem Schlüsselbund keine Refresh-Token bzw. Webhook-Secrets mehr enthalten.
- **Abschnitt „UTF-8 …":** keine Änderung.

- [ ] **Step 2: `src/CLAUDE.md`**
- **Abschnitt „Google-Integration":** Token nur über `token_store` laden und speichern, `forget_token` statt `os.remove(token_path)`, `TokenKeyringUnavailable` gilt nicht als Auth-Fehler und löst keinen Flow aus.
- **Abschnitt `secure_file`:** entsprechend anpassen.
- **Abschnitt „Wo gehört neuer Code hin?":** Ein neues Secret kommt über `keyring_store` plus Datei-Fallback, nie direkt über `keyring`.

- [ ] **Step 3: `docs/known-limitations.md`** — neuer Abschnitt mit drei Einschränkungen:
  - **Downgrade:** Eine ältere Version liest den Refresh-Token nicht mehr. google-auth wirft `ValueError` „missing fields refresh_token". Abhilfe ist einmal „Google neu verbinden". Webhooks mit Auth senden dort ohne Wert.
  - **macOS:** Nach App-Updates kann der Keychain-Dialog erneut erscheinen (ad-hoc-Signatur).
  - **Größenlimit unter Windows:** Deshalb liegt nur der Refresh-Token im Schlüsselbund.

- [ ] **Step 4: Prüfen** — `python -m pytest -q -p no:warnings` (inkl. `test_claude_md_claims.py`), `python -m ruff check .`. Scheitert `test_claude_md_claims.py`, das Muster im Test nachziehen, nicht die Behauptung.

- [ ] **Step 5: Commit** — `docs: Schlüsselbund für Token und Webhooks in CLAUDE.md und known-limitations (#101)`.

- [ ] **Step 6: Verifikation mit echtem Windows-Schlüsselbund (kein Commit)**

Mit dem echten `keyring` in einer Scratch-venv, **nie** gegen das echte Datenverzeichnis:

1. `python -m venv "$SP/kvenv"` und `"$SP/kvenv/Scripts/python" -m pip install -q -r requirements.txt`.
2. Ein Scratch-Datenverzeichnis mit einer **Fake**-`token.json` anlegen (ausgedachter Refresh-Token `1//fake-refresh`, beliebige `client_id`/`client_secret`), dazu eine `webhooks.json` mit einem Header-Webhook (Fake-Token).
3. Die App aus der venv starten, mit `ZEITERFASSUNG_DATA_DIR` auf das Scratch-Verzeichnis. Harness wie bei R11 mit `src.main.main()`, das nach ~8 s beendet.
4. Erwartet:
   - Hinweis-Dialog (Fenster sichtbar), Screenshot.
   - `token.json` ohne `refresh_token`, mit `refresh_token_location: "keyring"`; `webhooks.json` ohne `value`, mit `secret_location`.
   - `cmdkey /list | grep -i Zeiterfassung` zeigt den Eintrag. Alternativ liefert `"$SP/kvenv/Scripts/python" -c "import keyring; print(keyring.get_password('Zeiterfassung', '<schlüssel>'))"` den Fake-Wert.
5. Zweiter Start: kein Hinweis.
6. **Aufräumen:**
   - Einträge entfernen mit `"$SP/kvenv/Scripts/python" -c "import keyring; keyring.delete_password('Zeiterfassung', '<token-schlüssel>'); keyring.delete_password('Zeiterfassung', 'webhook:<id>')"`.
   - Scratch-Verzeichnis und venv löschen.
   - `cmdkey /list` zeigt danach keinen Zeiterfassung-Eintrag mehr aus diesem Lauf.

Pre-Release auf allen drei Plattformen: **vor dem nächsten echten Release**, zusammen mit dem offenen Pre-Release aus #123/R9 (s. Spec, „Verifikation vor dem Merge").

---

## Abschluss

Nach Task 10: `superpowers:finishing-a-development-branch`. In die PR-Beschreibung gehören `Closes #101` (Stufe 1; `credentials.json` bleibt als Idee im Issue-Kommentar festgehalten), die Downgrade-Einschränkung, der Pre-Release-Hinweis und das Ergebnis der Windows-Verifikation.
