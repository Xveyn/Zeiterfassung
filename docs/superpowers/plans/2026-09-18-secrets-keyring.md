# OAuth-Token und Webhook-Secrets im Schlüsselbund — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Refresh-Token aus `token.json` und die Webhook-Secrets aus `webhooks.json` liegen im OS-Schlüsselbund, sobald einer verfügbar ist. Bestehende Installationen ziehen beim Start geprüft und verlustfrei um, und die Deinstallation räumt den Schlüsselbund ab. Ohne Schlüsselbund bleibt alles wie heute.

**Architecture:**
- Neue Tk-freie Module:
  - `token_store` lädt und speichert OAuth-Credentials und behält den Ort bei.
  - `webhook_secrets` bündelt die Secret-Regeln der Webhooks nach dem SMTP-Muster.
  - `secret_migration` enthält den Umzug beim Start, die Hinweistexte und das Abräumen bei der Deinstallation.
- Erweiterte Module:
  - `keyring_store` bekommt schlüsselbasierte Funktionen mit einem Service-Namen pro Eintrag und einem Prozess-Cache.
  - `oauth_utils` bekommt Feldnamen, den Schlüssel in der Datei, einen JSON-Schreibweg und `forget_token`.
- Ablauf: Der Umzug läuft als Hintergrund-Task nach dem Token-Refresh beim Start. Die Exe kennt den Modus `--forget-secrets`, den der Uninstaller aufruft.

**Tech Stack:** Python 3.10, Tkinter (nur Dialog-Wiring), `keyring==25.7.0` (lazy), google-auth, Inno Setup, pytest, ruff, pyright 1.1.411.

**Spec:** `docs/superpowers/specs/2026-09-18-secrets-keyring-design.md`. Der Abschnitt „Nachträge aus dem Plan-Review" geht den übrigen Abschnitten vor.

## Global Constraints

- **Kompatibilität mit bestehenden Installationen hat Vorrang.**
  - Eine `token.json` ohne `refresh_token_location` bzw. ein Webhook ohne `auth.secret_location` gilt als `"file"` und wird **exakt wie heute** gelesen und geschrieben.
  - **`save_credentials` behält den Ort bei.** Eine bestehende Datei im Datei-Modus bleibt eine Datei. Umziehen darf **ausschließlich** `secret_migration`.
  - Ohne Schlüsselbund ist das Verhalten byte-gleich zu heute.
- **Kein Test darf den echten OS-Schlüsselbund anfassen.** Ein autouse-Fixture in `tests/conftest.py` installiert standardmäßig ein **nicht verfügbares** Fake-`keyring` und leert den Prozess-Cache von `keyring_store`. Tests mit funktionierendem Schlüsselbund nehmen `fake_keyring`.
- **`import keyring` bleibt lazy** in den Funktionen von `keyring_store`, weil die CI `keyring` nicht installiert.
- **Jeder Schlüsselbund-Zugriff läuft über `keyring_store`** (Watchdog 30 s), nie im Tk-Callback, immer im Worker.
- **Schlüssel und Service-Namen:**
  - Neue Einträge liegen unter Service `keyring_store.service_for(key)` = `"Zeiterfassung:" + key`, als Nutzername dient `key`.
  - SMTP-Einträge bleiben unverändert unter Service `"Zeiterfassung"`.
  - Token-Schlüssel: `"google-oauth:" + uuid4().hex`. Er wird einmal erzeugt und steht in `token.json` als `refresh_token_key`.
  - Webhook-Schlüssel: `"webhook:" + id`.
- **Logs enthalten nie ein Secret, einen Schlüssel oder eine Webhook-ID** (CodeQL `py/clear-text-logging`).
- **Kein Consent-Flow ohne Klick** (Xveyn#129): Ist der Schlüsselbund nicht erreichbar, führt das in nicht-interaktiven Pfaden zu einem Fehler, nie zu `run_local_server`.
- **Annotationen:** `src/token_store.py`, `src/webhook_secrets.py` und `src/secret_migration.py` sind vollständig annotiert und stehen in `tests/test_type_annotations.py::ANNOTATED_MODULES`. `keyring_store` und `oauth_utils` stehen dort schon.
- **Catch-alls** folgen `tests/test_catch_all_handlers.py`: loggen, melden oder eine Begründung im Handler, dazu ein enger `try`.
- **Keine neuen Abhängigkeiten.**
- **Befehle** aus dem Repo-Root: `python -m pytest -q -p no:warnings`, `python -m ruff check .`, `npx --yes pyright@1.1.411`.
  - pyright lokal: `0 errors, 0 warnings`.
  - In einem frischen Checkout ist eine bestehende Warnung in `src/version.py` (Import von `build_info`) normal. **Jede andere** ist ein Befund.
- **Shell:**
  - In PowerShell nie `&&`.
  - Mehrzeilige Commit-Messages nur per Temp-Datei (`git commit -F`) im Scratchpad `C:\Users\SvenB\AppData\Local\Temp\claude\D--Programme--x86--Zeiterfassung-Repo-Zeiterfassung\0ce62229-4862-454a-b6a3-a2cf81fea1b3\scratchpad`.
  - Jeder Commit endet mit `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Nie gegen echte Nutzerdaten.** Kein Subagent startet die App gegen das echte Datenverzeichnis oder macht echte Google-Aufrufe mit echten Tokens. Solche Läufe sind Stopp-Punkte für den Menschen (Task 11 Step 8).

## Bewusste Abweichungen von der Spec (Plan-Entscheidungen)

1. **`load_credentials(token_path, scopes, credentials_cls)`** bekommt die `Credentials`-Klasse des Aufrufers. So greifen die bestehenden Test-Patches unverändert: `src.drive.Credentials`, `google.oauth2.credentials.Credentials.from_authorized_user_file` und `tests/conftest.py::install_existing_token`.
2. **`forget_token` und die Token-Feldnamen liegen in `oauth_utils`.** `discard_token_for_scope_upgrade` liegt dort, und `token_store` importiert `oauth_utils`. Andersherum wäre es ein Zyklus.
3. **Die SMTP-Funktionen in `keyring_store` bleiben unverändert.** `put`/`fetch`/`remove` kommen daneben. Die SMTP-Tests prüfen Log-Inhalte, ein Umbau brächte Risiko ohne Nutzen.
4. **Der Webhook-Lösch-Hook bekommt nur die ID** (`after_delete(record_id)` aus R12). Er ruft `keyring_store.remove` also auch für Webhooks ohne Schlüsselbund-Secret, wie heute `tab_smtp._delete_secret`.
5. **Der Webhook-Dialog füllt Datensätze im Datei-Modus weiter vor.** Das ist Kompatibilität: ohne Schlüsselbund ändert sich nichts. „Nicht vorbefüllen" gilt nur für Secrets im Schlüsselbund.
6. **Die Charakterisierung** der Token-Datei entsteht in Task 4. Task 3 trennt `write_token` nur in `write_token_json` auf und ändert das Verhalten nicht. Die bestehenden Tests in `tests/test_oauth_utils.py` sichern das ab.
7. **Nicht in diesem Vorhaben** (Folge-Issue): themed Meldungen für `TokenKeyringUnavailable` in den Einstellungs-Pfaden (`oauth_task`, `reconnect_drive`, `load_calendars(interactive=True)`, Kompaktierung). Dort erscheint der native Fehler-Dialog mit der Meldung „Der Schlüsselbund … ist nicht erreichbar".

---

### Task 1: Test-Fundament: kein Test berührt den echten Schlüsselbund

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_keyring_store.py` (Z. 10–56: Imports, `_FakeKeyring`, Fixture `fake_keyring`)

**Interfaces:**
- Produces: Fixture `fake_keyring(working=True, block=None, lie=False)` → Fake mit `.store: dict[(service, account), str]`. Außerdem das autouse-Fixture `_no_os_keyring`.

- [ ] **Step 1: ans Ende von `tests/conftest.py`**. Imports `sys`, `types` und `pytest` oben ergänzen, falls sie fehlen.

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


def _clear_keyring_cache():
    from src import keyring_store
    if hasattr(keyring_store, "_known"):
        keyring_store._known.clear()


@pytest.fixture(autouse=True)
def _no_os_keyring(monkeypatch):
    """Standard für JEDEN Test: kein Schlüsselbund verfügbar — alle Pfade
    verhalten sich wie heute ohne Schlüsselbund (Datei), und ein Entwickler
    mit installiertem `keyring` schreibt beim Testlauf nichts in seinen
    echten Schlüsselbund. Der Prozess-Cache von `keyring_store` wird
    geleert, damit kein Test Werte eines anderen sieht."""
    _clear_keyring_cache()
    _install_fake_keyring(monkeypatch, FakeKeyring(working=False))


@pytest.fixture
def fake_keyring(monkeypatch):
    def _install(working=True, block=None, lie=False):
        _clear_keyring_cache()
        return _install_fake_keyring(
            monkeypatch, FakeKeyring(working=working, block=block, lie=lie))
    return _install
```

`_known` gibt es erst ab Task 2. Dank der `hasattr`-Prüfung läuft Task 1 trotzdem schon grün.

- [ ] **Step 2: `tests/test_keyring_store.py`**: `_FakeKeyring` und das Fixture `fake_keyring` löschen (Z. 20–55). Danach `python -m ruff check tests/test_keyring_store.py` laufen lassen und genau die Imports entfernen, die ruff als unbenutzt meldet. Laut Review sind das wahrscheinlich `sys`, `types` und `pytest`.

- [ ] **Step 3: Volle Suite**, `python -m pytest -q -p no:warnings`. Erwartet: 2237 passed, 10 skipped, also unverändert.

- [ ] **Step 4: Commit.** Titel: `test: Fake-Schlüsselbund zentral in conftest, autouse ohne OS-Schlüsselbund (#101)`, dazu `Refs Xveyn/Zeiterfassung#101`.

---

### Task 2: `keyring_store`: Service-Name pro Eintrag, nur bei Änderung schreiben

**Files:**
- Modify: `src/keyring_store.py` (vor `def persist_password`; `threading` ist bereits importiert)
- Test: `tests/test_keyring_store.py` (anhängen)

**Interfaces:**
- Consumes: `_call_guarded`, `SERVICE`, `WATCHDOG_TIMEOUT`
- Produces:
  - `service_for(key: str) -> str`
  - `put(key: str, value: str) -> bool`
  - `fetch(key: str) -> str | None`: `None` heißt „nicht ermittelbar", `""` heißt „kein Eintrag"
  - `remove(key: str) -> None`
  - Cache `_known: dict[str, str]`

- [ ] **Step 1: Tests anhängen**

```python
# --- schlüsselbasiert: put / fetch / remove (#101) -------------------------


def _entry(key):
    return (keyring_store.service_for(key), key)


def test_service_is_per_entry():
    """Ein Service je Eintrag: WinVaultKeyring schichtet mehrere Nutzernamen
    unter EINEM Service per ungeschütztem Lesen-Ändern-Schreiben um."""
    assert keyring_store.service_for("webhook:w1") == "Zeiterfassung:webhook:w1"


def test_put_and_fetch_roundtrip(fake_keyring):
    fake = fake_keyring()
    assert keyring_store.put("google-oauth:abc", "1//refresh") is True
    assert fake.store[_entry("google-oauth:abc")] == "1//refresh"
    assert keyring_store.fetch("google-oauth:abc") == "1//refresh"


def test_smtp_entries_stay_under_the_plain_service(fake_keyring):
    fake = fake_keyring()
    keyring_store.set_secret("rec-1", "pw")
    keyring_store.put("webhook:w1", "tok")
    assert (keyring_store.SERVICE, "rec-1") in fake.store
    assert _entry("webhook:w1") in fake.store


def test_fetch_returns_empty_string_for_a_missing_entry(fake_keyring):
    fake_keyring()
    assert keyring_store.fetch("google-oauth:abc") == ""


def test_put_and_fetch_without_backend(fake_keyring):
    fake_keyring(working=False)
    assert keyring_store.put("k", "v") is False
    assert keyring_store.fetch("k") is None


def test_put_skips_an_unchanged_value(fake_keyring):
    """Nur bei Änderung schreiben: jeder Token-Refresh schriebe sonst neu
    (macOS: SecItemDelete+SecItemAdd, nicht atomar)."""
    fake = fake_keyring()
    keyring_store.put("k", "v")
    del fake.store[_entry("k")]           # „hinter dem Rücken" entfernt
    assert keyring_store.put("k", "v") is True
    assert _entry("k") not in fake.store  # gleicher Wert: nicht erneut geschrieben
    assert keyring_store.put("k", "w") is True
    assert fake.store[_entry("k")] == "w"


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
    assert _entry("k") not in fake.store
    keyring_store.remove("k")             # fehlt: kein Fehler
    assert keyring_store.put("k", "v") is True
    assert fake.store[_entry("k")] == "v"  # Cache nach remove geleert


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

- [ ] **Step 2: RED.** `python -m pytest tests/test_keyring_store.py -q -p no:warnings`. Erwartet: FAIL mit `AttributeError … 'service_for'`/`'put'`.

- [ ] **Step 3: Implementieren** (vor `def persist_password`):

```python
# Zuletzt geschriebener bzw. gelesener Wert je Schlüssel, nur in diesem
# Prozess. `put` schreibt nur bei Änderung: sonst schriebe jeder stündliche
# Token-Refresh denselben Wert neu — unter macOS über SecItemDelete +
# SecItemAdd (nicht atomar, womöglich mit Keychain-Rückfrage), unter Linux
# bei hängendem Secret Service mit 30 s Watchdog. Preis: wird ein Eintrag
# außerhalb der App entfernt, merkt das erst der nächste Start.
_known: dict[str, str] = {}
_known_lock = threading.Lock()


def service_for(key: str) -> str:
    """Service-Name eines schlüsselbasierten Eintrags (#101): einer je
    Eintrag. Unter EINEM gemeinsamen Service schichtet WinVaultKeyring
    mehrere Nutzernamen per ungeschütztem Lesen-Ändern-Schreiben um — nicht
    thread-sicher, und die SMTP-Passwörter unter `SERVICE` wären betroffen."""
    return f"{SERVICE}:{key}"


def put(key: str, value: str) -> bool:
    """Legt `value` unter `key` ab. `True` bei Erfolg (oder unverändert).

    Anders als `set_secret` ohne Datensatz und ohne Datei-Fallback — den
    entscheidet der Aufrufer. Geloggt wird weder Schlüssel noch Wert.
    """
    with _known_lock:
        if _known.get(key) == value:
            return True

    def work() -> None:
        import keyring  # pyright: ignore[reportMissingImports]

        keyring.set_password(service_for(key), key, value)

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
    with _known_lock:
        _known[key] = value
    return True


def fetch(key: str) -> str | None:
    """Liest `key` — immer aus dem Schlüsselbund, nie aus dem Cache.

    `None`: NICHT ermittelbar (kein Backend, Timeout, Fehler). `""`: der
    Schlüsselbund hat geantwortet, es gibt keinen Eintrag. Aufrufer MÜSSEN
    beides unterscheiden — dieselbe Regel wie bei `get_secret`.
    """
    def work() -> Any:
        import keyring  # pyright: ignore[reportMissingImports]

        return keyring.get_password(service_for(key), key)

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
    value = str(stored) if stored else ""
    with _known_lock:
        if value:
            _known[key] = value
        else:
            _known.pop(key, None)
    return value


def remove(key: str) -> None:
    """Räumt `key` ab. Ein fehlender Eintrag ist kein Fehler."""
    with _known_lock:
        _known.pop(key, None)

    def work() -> None:
        import keyring  # pyright: ignore[reportMissingImports]

        keyring.delete_password(service_for(key), key)

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

- [ ] **Step 4: GREEN.** `python -m pytest tests/test_keyring_store.py tests/test_catch_all_handlers.py tests/test_type_annotations.py -q -p no:warnings`.

- [ ] **Step 5: Commit.** `feat(keyring): Einträge mit eigenem Service-Namen, nur bei Änderung schreiben (#101)`.

---

### Task 3: `oauth_utils`: Feldnamen, Schlüssel in der Datei, `forget_token`

**Files:**
- Modify: `src/oauth_utils.py`, `src/drive.py` (`reconnect`)
- Test: `tests/test_oauth_utils.py` (anhängen)

**Interfaces:**
- Consumes: `keyring_store.remove`
- Produces:
  - `KEYRING_UNAVAILABLE_MSG`, `class TokenKeyringUnavailable(Exception)`
  - `REFRESH_TOKEN_LOCATION = "refresh_token_location"`, `REFRESH_TOKEN_KEY = "refresh_token_key"`
  - `new_token_keyring_key() -> str`
  - `read_token_meta(token_path) -> dict | None`
  - `token_in_keyring(meta) -> bool`
  - `write_token_json(json_text, token_path) -> None`
  - `write_token(creds, token_path)` (unverändert)
  - `forget_token(token_path) -> None`

- [ ] **Step 1: Tests anhängen**

```python
# --- Schlüsselbund-Anbindung (#101) ----------------------------------------

import json as _json

from src import keyring_store as _ks
from src import oauth_utils as _ou


def test_new_token_keyring_keys_are_unique():
    a, b = _ou.new_token_keyring_key(), _ou.new_token_keyring_key()
    assert a.startswith("google-oauth:") and a != b


def test_read_token_meta_and_location(tmp_path):
    path = tmp_path / "token.json"
    assert _ou.read_token_meta(str(path)) is None                # fehlt
    path.write_text("kein json", encoding="utf-8")
    assert _ou.read_token_meta(str(path)) is None                # kaputt
    path.write_text('{"token": "t"}', encoding="utf-8")
    meta = _ou.read_token_meta(str(path))
    assert meta == {"token": "t"} and not _ou.token_in_keyring(meta)   # Alt-Format
    path.write_text('{"refresh_token_location": "keyring"}', encoding="utf-8")
    assert _ou.token_in_keyring(_ou.read_token_meta(str(path)))


def test_write_token_json_writes_exactly_the_text(tmp_path):
    path = tmp_path / "token.json"
    _ou.write_token_json('{"a": 1}', str(path))
    assert path.read_text(encoding="utf-8") == '{"a": 1}'


def test_forget_token_removes_file_and_keyring_entry(tmp_path, fake_keyring):
    fake = fake_keyring()
    path = tmp_path / "token.json"
    path.write_text(_json.dumps({"refresh_token_location": "keyring",
                                 "refresh_token_key": "google-oauth:k1"}),
                    encoding="utf-8")
    _ks.put("google-oauth:k1", "1//refresh")

    _ou.forget_token(str(path))

    assert not path.exists()
    assert (_ks.service_for("google-oauth:k1"), "google-oauth:k1") not in fake.store


def test_forget_token_leaves_the_keyring_alone_for_a_file_token(tmp_path, fake_keyring):
    fake = fake_keyring()
    path = tmp_path / "token.json"
    path.write_text('{"refresh_token": "1//x", "refresh_token_key": "google-oauth:k1"}',
                    encoding="utf-8")
    fake.store[(_ks.service_for("google-oauth:k1"), "google-oauth:k1")] = "fremd"

    _ou.forget_token(str(path))

    assert not path.exists()
    assert fake.store[(_ks.service_for("google-oauth:k1"), "google-oauth:k1")] == "fremd"


def test_forget_token_is_quiet_without_a_file(tmp_path):
    _ou.forget_token(str(tmp_path / "token.json"))
```

- [ ] **Step 2: RED.** `python -m pytest tests/test_oauth_utils.py -q -p no:warnings`. Erwartet: FAIL.

- [ ] **Step 3: Implementieren** in `src/oauth_utils.py`

(a) Imports ergänzen: `json`, `logging`, `uuid` (soweit sie fehlen) und `from src import keyring_store`. Falls noch kein Logger existiert, `log = logging.getLogger(__name__)` anlegen.

(b) Den bisherigen Körper von `write_token` nach `write_token_json(json_text: str, token_path: str) -> None` verschieben. Darin `f.write(creds.to_json())` durch `f.write(json_text)` ersetzen. Den Docstring übernehmen und um diesen Satz ergänzen: „Schreibt fertigen JSON-Text; `write_token` und `token_store.save_credentials` liefern ihn." Danach:

```python
def write_token(creds: Any, token_path: str) -> None:
    """Persistiere Credentials vollständig (inkl. Refresh-Token) als Datei —
    der Datei-Modus, byte-gleich zum Verhalten vor #101."""
    write_token_json(creds.to_json(), token_path)
```

(c) Nach `REAUTH_REQUIRED_MSG` einfügen:

```python
KEYRING_UNAVAILABLE_MSG = (
    "Der Schlüsselbund des Betriebssystems ist nicht erreichbar — dort liegt "
    "die Google-Anmeldung.")
"""Fehlertext, wenn der Refresh-Token im Schlüsselbund liegt, dieser aber
nicht antwortet. Wie `REAUTH_REQUIRED_MSG` als Text erkennbar, weil
Sync-Flows Fehler teils nur als `str(e)` weiterreichen."""

REFRESH_TOKEN_LOCATION = "refresh_token_location"
"""Feld in token.json: `"keyring"`, wenn der Refresh-Token im Schlüsselbund
liegt. Fehlt es (Alt-Format), liegt er in der Datei (#101)."""

REFRESH_TOKEN_KEY = "refresh_token_key"
"""Feld in token.json: Schlüssel des Eintrags im Schlüsselbund. In der Datei
statt aus dem Pfad abgeleitet — ein verschobener Datenordner (Junction,
8.3-Name, Backup) behält so seinen Token."""


class TokenKeyringUnavailable(Exception):
    """Der Refresh-Token liegt im Schlüsselbund, der aber nicht antwortet.

    Kein Auth-Fehler: der Token ist nicht ungültig, nur gerade nicht lesbar.
    Aufrufer starten deshalb KEINEN Consent-Flow (Xveyn#129) und fassen
    token.json nicht an."""

    def __init__(self) -> None:
        super().__init__(KEYRING_UNAVAILABLE_MSG)


def new_token_keyring_key() -> str:
    """Neuer, eindeutiger Schlüssel für den Refresh-Token. Eindeutig statt
    fest: zwei Datenverzeichnisse desselben OS-Nutzers (Dev-Instanz neben
    der Installation) dürfen sich keinen Eintrag teilen."""
    return f"google-oauth:{uuid.uuid4().hex}"


def read_token_meta(token_path: str) -> dict[str, Any] | None:
    """Inhalt von token.json als Dict, oder None (fehlt/unlesbar/kein Dict)."""
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def token_in_keyring(meta: dict[str, Any] | None) -> bool:
    """Liegt der Refresh-Token laut `meta` im Schlüsselbund?"""
    return isinstance(meta, dict) and meta.get(REFRESH_TOKEN_LOCATION) == "keyring"


def forget_token(token_path: str) -> None:
    """Löscht token.json und — nur wenn der Refresh-Token dort liegt — den
    Eintrag im Schlüsselbund. Ohne das zweite blieben nach „Google neu
    verbinden" oder einem Scope-Upgrade verwaiste Einträge stehen."""
    meta = read_token_meta(token_path)
    key = meta.get(REFRESH_TOKEN_KEY) if meta is not None and token_in_keyring(meta) else None
    try:
        os.remove(token_path)
    except FileNotFoundError:
        pass
    if isinstance(key, str) and key:
        keyring_store.remove(key)
```

(d) In `discard_token_for_scope_upgrade` wird der Block `try: os.remove(token_path) except OSError: pass` / `return True` zu:

```python
    try:
        forget_token(token_path)
    except OSError:
        # Wie zuvor: ein Löschfehler (gesperrte Datei) darf den Consent, der
        # unmittelbar folgt, nicht verhindern — der schreibt token.json neu.
        log.debug("token.json ließ sich nicht löschen", exc_info=True)
    return True
```

(e) In `src/drive.py::reconnect` wird der Block `try: os.remove(token_path) except FileNotFoundError: pass` zu `forget_token(token_path)`. `forget_token` kommt in den Import `from src.oauth_utils import …`.

- [ ] **Step 4: GREEN.** `python -m pytest tests/test_oauth_utils.py tests/test_drive.py tests/test_gcal.py tests/test_mail.py tests/test_catch_all_handlers.py tests/test_type_annotations.py -q -p no:warnings`.

- [ ] **Step 5: Commit.** `feat(oauth): Token-Feldnamen, Schlüssel in der Datei, forget_token (#101)`.

---

### Task 4: `token_store`: Laden und Speichern, Ort beibehalten

**Files:**
- Create: `src/token_store.py`, `tests/test_token_store.py`
- Modify: `tests/test_type_annotations.py` (`"src/token_store.py",` nach `"src/oauth_utils.py",`)

**Interfaces:**
- Consumes: Task 2 und 3
- Produces:
  - `TOKEN_LOCK: threading.RLock`
  - `load_credentials(token_path: str, scopes: list[str], credentials_cls: Any) -> Any | None`. Liefert `None`, wenn der Token im Schlüsselbund liegen soll, dort aber fehlt, oder wenn in der Datei kein Schlüssel steht. Wirft `TokenKeyringUnavailable`, wenn der Schlüsselbund nicht antwortet.
  - `save_credentials(creds: Any, token_path: str) -> None`

- [ ] **Step 1: Tests**: `tests/test_token_store.py`:

```python
"""token_store (#101): Refresh-Token im Schlüsselbund, Rest in token.json —
und Speichern behält den Ort bei. Kompatibilität mit ECHTEN
google-auth-Credentials."""

import datetime
import json

import pytest
from google.oauth2.credentials import Credentials

from src import keyring_store, oauth_utils
from src.token_store import load_credentials, save_credentials

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
# Festes expiry: google-auth setzt ein fehlendes expiry beim Laden auf
# utcnow() - REFRESH_THRESHOLD — zwei Ladevorgänge unterschieden sich sonst
# in den Mikrosekunden.
EXPIRY = datetime.datetime(2030, 1, 1, 12, 0, 0)


def _real_creds(refresh="1//refresh-token"):
    return Credentials(
        token="ya29.access", refresh_token=refresh,
        token_uri="https://oauth2.googleapis.com/token",
        client_id="cid.apps.googleusercontent.com", client_secret="csecret",
        scopes=SCOPES, expiry=EXPIRY)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _keyring_token(tmp_path, fake_keyring, refresh="1//refresh-token"):
    """token.json im Schlüsselbund-Modus, wie nach dem Umzug bzw. einer
    frischen Anmeldung (vorher gab es keine Datei)."""
    fake_keyring()
    path = tmp_path / "token.json"
    save_credentials(_real_creds(refresh), str(path))
    return path


def test_legacy_file_loads_exactly_as_before(tmp_path):
    """Kompatibilität: token.json, wie write_token sie heute schreibt."""
    path = tmp_path / "token.json"
    oauth_utils.write_token(_real_creds(), str(path))

    loaded = load_credentials(str(path), SCOPES, Credentials)
    reference = Credentials.from_authorized_user_file(str(path), SCOPES)

    assert loaded.to_json() == reference.to_json()


def test_legacy_file_stays_a_file_even_with_a_keyring(tmp_path, fake_keyring):
    """B1: Speichern behält den Ort bei. Umziehen darf nur secret_migration —
    sonst zöge der Start-Refresh still und ohne Zurücklesen um, und der
    Hinweis bliebe aus."""
    fake = fake_keyring()
    a, b = tmp_path / "a" / "token.json", tmp_path / "b" / "token.json"
    a.parent.mkdir()
    b.parent.mkdir()
    oauth_utils.write_token(_real_creds(), str(a))
    oauth_utils.write_token(_real_creds(), str(b))

    save_credentials(_real_creds("1//rotiert"), str(a))
    oauth_utils.write_token(_real_creds("1//rotiert"), str(b))

    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")
    assert fake.store == {}


def test_without_keyring_save_writes_the_full_file_as_before(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    save_credentials(_real_creds(), str(a))          # keine Datei, kein Schlüsselbund
    oauth_utils.write_token(_real_creds(), str(b))
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


def test_fresh_login_goes_straight_to_the_keyring(tmp_path, fake_keyring):
    path = _keyring_token(tmp_path, fake_keyring)
    data = _read(path)
    assert "refresh_token" not in data
    assert data["token"] == "ya29.access"                  # Access-Token bleibt
    assert data[oauth_utils.REFRESH_TOKEN_LOCATION] == "keyring"
    assert keyring_store.fetch(data[oauth_utils.REFRESH_TOKEN_KEY]) == "1//refresh-token"


def test_keyring_roundtrip_loads_the_same_credentials(tmp_path, fake_keyring):
    path = _keyring_token(tmp_path, fake_keyring)
    loaded = load_credentials(str(path), SCOPES, Credentials)
    assert loaded.refresh_token == "1//refresh-token"
    assert loaded.token == "ya29.access"
    assert loaded.client_id == "cid.apps.googleusercontent.com"


def test_keyring_token_keeps_its_key_across_saves(tmp_path, fake_keyring):
    path = _keyring_token(tmp_path, fake_keyring)
    key = _read(path)[oauth_utils.REFRESH_TOKEN_KEY]
    save_credentials(_real_creds("1//rotiert"), str(path))
    assert _read(path)[oauth_utils.REFRESH_TOKEN_KEY] == key
    assert keyring_store.fetch(key) == "1//rotiert"


def test_unreachable_keyring_raises_and_leaves_the_file(tmp_path, fake_keyring):
    path = _keyring_token(tmp_path, fake_keyring)
    before = path.read_bytes()
    fake_keyring(working=False)
    with pytest.raises(oauth_utils.TokenKeyringUnavailable):
        load_credentials(str(path), SCOPES, Credentials)
    assert path.read_bytes() == before


def test_missing_keyring_entry_means_no_credentials(tmp_path, fake_keyring):
    path = _keyring_token(tmp_path, fake_keyring)
    fake_keyring()                                 # frischer, leerer Schlüsselbund
    assert load_credentials(str(path), SCOPES, Credentials) is None


def test_save_falls_back_to_the_file_when_the_keyring_fails(tmp_path, fake_keyring):
    path = _keyring_token(tmp_path, fake_keyring)
    fake_keyring(working=False)
    save_credentials(_real_creds("1//rotiert"), str(path))
    data = _read(path)
    assert data["refresh_token"] == "1//rotiert"   # der neue Token geht nie verloren
    assert oauth_utils.REFRESH_TOKEN_LOCATION not in data


def test_unreadable_file_takes_the_legacy_path(tmp_path):
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

- [ ] **Step 2: RED.** Erwartet: ERROR `ModuleNotFoundError: No module named 'src.token_store'`.

- [ ] **Step 3: Implementieren**: `src/token_store.py`:

```python
"""OAuth-Credentials laden und speichern — Refresh-Token im Schlüsselbund (#101).

Einzige Stelle, die OAuth-Credentials lädt und speichert. token.json bleibt
bestehen und behält alles außer dem Refresh-Token (Access-Token, Scopes,
Client, Ablauf): die rund zehn Datei-Prüfungen der App (existiert? welche
Scopes? mtime-Poll im Google-Tab) laufen unverändert weiter.

**Speichern behält den Ort bei.** Eine token.json im Datei-Modus bleibt eine
Datei; in den Schlüsselbund kommt der Token nur, wenn er schon dort liegt
oder es noch keine Datei gibt (frische Anmeldung). Umziehen darf allein
`secret_migration` — mit Zurücklesen und Hinweis.

Nur der Refresh-Token, weil der Windows Credential Manager höchstens 1280
Zeichen (UTF-16) fasst, Google Access-Tokens aber bis 2048 Byte reserviert
(Spec, R1). Tk-frei; die Credentials-Klasse kommt vom Aufrufer, damit dessen
lazy/optional gebundene Klasse und die Test-Patches daran greifen.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from src import keyring_store
from src.oauth_utils import (
    REFRESH_TOKEN_KEY, REFRESH_TOKEN_LOCATION, TokenKeyringUnavailable,
    new_token_keyring_key, read_token_meta, token_in_keyring, write_token,
    write_token_json,
)

# Speichern und Umzug sind Lesen-Prüfen-Schreiben an token.json; beim Start
# erneuern Refresh, Absender-Abruf, Sync-Pull und Kalender-Abgleich parallel.
TOKEN_LOCK = threading.RLock()


def load_credentials(token_path: str, scopes: list[str],
                     credentials_cls: Any) -> Any | None:
    """Lädt die Credentials aus token.json (+ Schlüsselbund).

    - Alt-Format / Datei-Modus / unlesbar: exakt wie bisher
      `credentials_cls.from_authorized_user_file`.
    - Schlüsselbund-Modus: Refresh-Token einsetzen, dann
      `from_authorized_user_info`.
      - Schlüsselbund antwortet nicht → `TokenKeyringUnavailable` (Datei
        unangetastet, kein Consent — Xveyn#129).
      - Eintrag oder Schlüssel fehlt → `None`; der Aufrufer behandelt das wie
        „kein Token" (vorab geprüft: google-auth würfe sonst `ValueError`
        „missing fields refresh_token", Spec R3).
    """
    meta = read_token_meta(token_path)
    if meta is None or not token_in_keyring(meta):
        return credentials_cls.from_authorized_user_file(token_path, scopes)
    key = meta.get(REFRESH_TOKEN_KEY)
    if not isinstance(key, str) or not key:
        return None
    refresh = keyring_store.fetch(key)
    if refresh is None:
        raise TokenKeyringUnavailable()
    if not refresh:
        return None
    info = dict(meta)
    info.pop(REFRESH_TOKEN_LOCATION, None)
    info.pop(REFRESH_TOKEN_KEY, None)
    info["refresh_token"] = refresh
    return credentials_cls.from_authorized_user_info(info, scopes)


def save_credentials(creds: Any, token_path: str) -> None:
    """Speichert die Credentials am bisherigen Ort (s. Modul-Docstring)."""
    with TOKEN_LOCK:
        exists = os.path.exists(token_path)
        meta = read_token_meta(token_path) if exists else None
        refresh = getattr(creds, "refresh_token", None)
        if ((exists and not token_in_keyring(meta))
                or not (isinstance(refresh, str) and refresh)):
            # Datei-Modus (Ort beibehalten) oder nichts für den Schlüsselbund
            # (MagicMock-/Fake-Creds in Tests, Flow ohne Refresh-Token).
            write_token(creds, token_path)
            return
        key = meta.get(REFRESH_TOKEN_KEY) if meta is not None else None
        if not isinstance(key, str) or not key:
            key = new_token_keyring_key()
        if keyring_store.put(key, refresh):
            data = json.loads(creds.to_json(strip=["refresh_token"]))
            data[REFRESH_TOKEN_LOCATION] = "keyring"
            data[REFRESH_TOKEN_KEY] = key
            write_token_json(json.dumps(data), token_path)
            return
        # Schlüsselbund fällt aus: vollständig in die Datei — ein (rotierter)
        # Refresh-Token geht nie verloren; der nächste Start zieht ihn um.
        write_token(creds, token_path)
```

- [ ] **Step 4:** In die Whitelist `"src/token_store.py",` eintragen.

- [ ] **Step 5: GREEN.** `python -m pytest tests/test_token_store.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:warnings`.

- [ ] **Step 6: Commit.** `feat(oauth): token_store — Refresh-Token im Schlüsselbund, Ort beibehalten (#101)`.

---

### Task 5: Token-Pfade verdrahten, Fehlerart „Schlüsselbund nicht erreichbar"

**Files:**
- Modify: `src/mail.py`, `src/drive.py`, `src/gcal.py`, `src/background_tasks.py::refresh_token`, `src/dialogs/mail_task.py`, `src/sync_orchestrator.py`, `src/ui.py::_on_reconcile_done`
- Tests: `tests/test_gcal.py` (Patch-Ziele) sowie neue Tests in `tests/test_token_store.py`, `tests/test_mail_task.py`, `tests/test_sync_orchestrator.py` und `tests/test_background_tasks.py` (anlegen, falls die Datei fehlt)

**Interfaces:**
- Consumes: Task 3 und 4
- Produces:
  - `classify_sync_error` liefert `"keyring"`.
  - `classify_mail_error` liefert `kind: "keyring"`.
  - `BackgroundTaskRunner.refresh_token(on_auth_error, on_error, on_finished=None)`

- [ ] **Step 1: Tests (RED)**

(a) an `tests/test_token_store.py`:

```python
# --- Verdrahtung: nicht-interaktive Pfade starten keinen Flow (#129) -------


def _unreachable(tmp_path, fake_keyring):
    path = _keyring_token(tmp_path, fake_keyring)
    fake_keyring(working=False)
    return path


def test_drive_without_click_raises_unavailable_not_flow(tmp_path, fake_keyring, monkeypatch):
    from src import drive
    from tests.conftest import forbid_consent_flow
    path = _unreachable(tmp_path, fake_keyring)
    forbid_consent_flow(monkeypatch)
    with pytest.raises(oauth_utils.TokenKeyringUnavailable):
        drive.get_drive_service("credentials.json", str(path))


def test_calendar_without_click_raises_unavailable_not_flow(tmp_path, fake_keyring, monkeypatch):
    from src import gcal
    from tests.conftest import forbid_consent_flow
    path = _unreachable(tmp_path, fake_keyring)
    forbid_consent_flow(monkeypatch)
    with pytest.raises(oauth_utils.TokenKeyringUnavailable):
        gcal.get_calendar_service("credentials.json", str(path))


def test_start_refresh_raises_unavailable_for_the_runner(tmp_path, fake_keyring):
    from src.mail import refresh_token_if_needed
    path = _unreachable(tmp_path, fake_keyring)
    with pytest.raises(oauth_utils.TokenKeyringUnavailable):
        refresh_token_if_needed(str(path))


def test_missing_keyring_entry_is_an_auth_error_at_start(tmp_path, fake_keyring):
    from src.mail import TokenAuthError, refresh_token_if_needed
    path = _keyring_token(tmp_path, fake_keyring)
    fake_keyring()                                 # Eintrag weg
    with pytest.raises(TokenAuthError):
        refresh_token_if_needed(str(path))


def test_sender_lookup_is_empty_when_the_keyring_is_unreachable(tmp_path, fake_keyring):
    from src.mail import fetch_user_email
    path = _unreachable(tmp_path, fake_keyring)
    assert fetch_user_email(str(path)) == ""
```

(b) an `tests/test_mail_task.py`:

```python
def test_classify_keyring_unavailable_has_no_traceback():
    from src.dialogs.mail_task import classify_mail_error
    from src.oauth_utils import TokenKeyringUnavailable
    try:
        raise TokenKeyringUnavailable()
    except TokenKeyringUnavailable as e:
        res = classify_mail_error(e)
    assert res["kind"] == "keyring" and res["tb"] is None
```

(c) an `tests/test_sync_orchestrator.py`:

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

(d) an `tests/test_background_tasks.py`:

```python
import pytest


@pytest.mark.parametrize("outcome", ["ok", "auth", "error", "keyring"])
def test_start_refresh_calls_on_finished_after_every_outcome(outcome, monkeypatch):
    """Der Umzug der Zugangsdaten hängt an on_finished (#101) — er muss nach
    JEDEM Ausgang kommen, sonst zöge eine Installation nie um."""
    from src import background_tasks
    from src.mail import TokenAuthError
    from src.oauth_utils import TokenKeyringUnavailable

    def fake_refresh(*a, **k):
        if outcome == "auth":
            raise TokenAuthError("invalid_grant")
        if outcome == "error":
            raise RuntimeError("kaputt")
        if outcome == "keyring":
            raise TokenKeyringUnavailable()
        return "valid"

    monkeypatch.setattr(background_tasks, "refresh_token_if_needed", fake_refresh)
    runner = background_tasks.BackgroundTaskRunner.__new__(background_tasks.BackgroundTaskRunner)
    runner._base_path = "."
    runner._settings = {"sync_enabled": False, "gcal_enabled": False}
    runner.run = lambda fn, on_done: on_done(fn())
    events = []

    runner.refresh_token(on_auth_error=lambda m: events.append("auth"),
                         on_error=lambda tb: events.append("error"),
                         on_finished=lambda: events.append("finished"))

    assert events[-1] == "finished" and events.count("finished") == 1
    assert ("auth" in events) == (outcome == "auth")
    assert ("error" in events) == (outcome == "error")
```

Beim Implementieren prüfen, unter welchem Namen `background_tasks` `refresh_token_if_needed` importiert. Der Patch-Name muss dazu passen. `_settings` ist ein Dict, weil nur `.get` genutzt wird.

Run: `python -m pytest tests/test_token_store.py tests/test_mail_task.py tests/test_sync_orchestrator.py tests/test_background_tasks.py -q -p no:warnings`. Erwartet: die neuen Tests schlagen fehl.

- [ ] **Step 2: `src/mail.py`**
- Imports: `from src.oauth_utils import TokenKeyringUnavailable, discard_token_for_scope_upgrade` und `from src.token_store import load_credentials, save_credentials`. `write_token` fällt weg.
- `fetch_user_email`:
  - `Credentials.from_authorized_user_file(token_path, get_scopes(...))` wird zu `load_credentials(token_path, get_scopes(sync_enabled, gcal_enabled), Credentials)`.
  - Direkt danach `if creds is None: return ""`.
  - `write_token` wird zu `save_credentials`.
  - Vor das äußere `except Exception:` kommt:
    ```python
        except TokenKeyringUnavailable:
            log.warning("fetch_user_email: Schlüsselbund nicht erreichbar")
            return ""
    ```
- `_refresh_and_persist`: `save_credentials(creds, token_path)`.
- `refresh_token_if_needed`: `creds = load_credentials(token_path, scopes, Credentials)`, danach:
  ```python
      if creds is None:
          raise TokenAuthError(
              "Der Refresh-Token fehlt im Schlüsselbund des Betriebssystems.")
  ```
  `TokenKeyringUnavailable` wird hier **nicht** gefangen.
- `get_gmail_service`: `load_credentials(token_path, scopes, Credentials)`. Ist das Ergebnis `None`, läuft der bestehende Flow (der Aufrufer ist ein Klick). Nach dem Flow folgt `save_credentials(creds, token_path)`.

- [ ] **Step 3: `src/drive.py`**: `from src.token_store import load_credentials, save_credentials`, `write_token` aus dem Import entfernen. `creds = load_credentials(token_path, scopes, Credentials)` und beide Schreibstellen auf `save_credentials(creds, token_path)` umstellen.

- [ ] **Step 4: `src/gcal.py`**: dasselbe (`write_token` aus dem Import, `load_credentials(...)`, 2× `save_credentials`). In `tests/test_gcal.py` wird `monkeypatch.setattr(gcal, "write_token", …)` an drei Stellen (Z. ~258, ~319, ~361) zu `monkeypatch.setattr(gcal, "save_credentials", …)`. Lambdas und Assertions bleiben. Das `oauth_utils`-Patch in Z. ~257 bleibt ebenfalls stehen; es ist wirkungslos, aber harmlos.

- [ ] **Step 5: `src/background_tasks.py::refresh_token`**
- Signatur: `def refresh_token(self, on_auth_error, on_error, on_finished=None):`.
- Docstring ergänzen: „`on_finished()` kommt nach JEDEM Ausgang (UI-Thread), und zwar erst NACHDEM `on_auth_error`/`on_error` zurückgekehrt sind. Diese zeigen modale Dialoge, der Umzug der Zugangsdaten (#101) startet also erst nach dem Wegklicken. So schreibt er token.json nicht parallel zum Start-Refresh."
- Im Worker vor `except Exception:` einfügen:
  ```python
              except TokenKeyringUnavailable:
                  # Nicht ungültig, nur gerade nicht lesbar — still wie ein
                  # Netzfehler beim Offline-Start.
                  log.warning("Token-Refresh: Schlüsselbund nicht erreichbar")
                  return None
  ```
  Dazu den Import `from src.oauth_utils import TokenKeyringUnavailable`.
- `on_done`:
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

- [ ] **Step 6: Fehlerart „keyring"**
- `src/dialogs/mail_task.py::classify_mail_error`, als ersten Zweig:
  ```python
      if isinstance(e, TokenKeyringUnavailable):
          return {"ok": False, "kind": "keyring", "error": e, "tb": None,
                  "detail": KEYRING_UNAVAILABLE_MSG}
  ```
  Dazu den Import und eine Docstring-Zeile.
- `src/sync_orchestrator.py`:
  - `classify_sync_error`: als **ersten** Zweig `if KEYRING_UNAVAILABLE_MSG in text: return "keyring"` (Import aus `oauth_utils`; Docstring: „oder 'keyring'").
  - `_friendly_sync_message`, vor `network`:
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
  - `_short_sync_error`, vor `network`: `if kind == "keyring": return "Der Schlüsselbund ist nicht erreichbar."`
- `src/ui.py::_on_reconcile_done`, zwischen dem `auth`-Zweig und `else:`:
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

- [ ] **Step 7: GREEN und Rest-Check.** Volle Suite, ruff, pyright. `grep -rn "from_authorized_user_file\|write_token(" src --include=*.py` darf nur noch in `src/token_store.py` und `src/oauth_utils.py` treffen.

- [ ] **Step 8: Commit.** `feat(oauth): Google-Pfade über token_store; Fehlerart Schlüsselbund (#101)`.

---

### Task 6: `webhook_secrets`: Regeln, Store-Validierung, Versand

**Files:**
- Create: `src/webhook_secrets.py`, `tests/test_webhook_secrets.py`
- Modify:
  - `src/webhook_store.py::validate_record`
  - `src/dialogs/send_task.py` (Webhook-Schleife, `_KIND_TEXTS`)
  - `tests/test_send_task_dispatch.py`
  - `tests/test_type_annotations.py` (`"src/webhook_secrets.py",` nach `"src/webhook_store.py",`)

**Interfaces:**
- Consumes: `keyring_store.put/fetch/remove`
- Produces:
  - `SECRET_LOCATION`
  - `secret_field(record) -> str | None`
  - `keyring_key(webhook_id) -> str`
  - `in_keyring(record) -> bool`
  - `plaintext_secret(record) -> str`
  - `stored_in_keyring(record) -> dict`
  - `resolve(record) -> tuple[dict | None, str | None]` mit dem Problem `"unavailable"` bzw. `"missing"`
  - `persist(candidate, typed, stored) -> tuple[dict, str | None]`; das zweite Element ist der Schlüssel, der **nach** `store.save` abzuräumen ist
  - `forget_by_id(webhook_id) -> None`
  - `keyring_failure(problem) -> dict`

- [ ] **Step 1: Tests**: `tests/test_webhook_secrets.py`:

```python
"""Webhook-Secrets im Schlüsselbund (#101): das SMTP-Muster für webhooks.json."""

import pytest

from src import keyring_store, webhook_secrets as ws, webhook_store


def _entry(key):
    return (keyring_store.service_for(key), key)


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
    rec = _hook("header")
    assert ws.plaintext_secret(rec) == "Bearer abc"
    assert ws.resolve(rec) == (rec, None)


def test_stored_in_keyring_drops_the_field():
    moved = ws.stored_in_keyring(_hook("hmac"))
    assert "secret" not in moved["auth"]
    assert moved["auth"][ws.SECRET_LOCATION] == "keyring"
    assert moved["auth"]["prefix"] == "sha256="
    assert ws.plaintext_secret(moved) == ""


def test_resolve_fills_the_secret_from_the_keyring(fake_keyring):
    fake_keyring()
    keyring_store.put(ws.keyring_key("w1"), "Bearer xyz")
    rec, problem = ws.resolve(ws.stored_in_keyring(_hook("header")))
    assert problem is None
    assert rec["auth"]["value"] == "Bearer xyz" and ws.SECRET_LOCATION not in rec["auth"]


def test_resolve_reports_unavailable_and_missing(fake_keyring):
    moved = ws.stored_in_keyring(_hook("header"))
    fake_keyring(working=False)
    assert ws.resolve(moved) == (None, "unavailable")
    fake_keyring()
    assert ws.resolve(moved) == (None, "missing")


def test_persist_typed_goes_to_the_keyring(fake_keyring):
    fake = fake_keyring()
    saved, stale = ws.persist(_hook("header", value="Bearer neu"), "Bearer neu", stored=None)
    assert "value" not in saved["auth"] and saved["auth"][ws.SECRET_LOCATION] == "keyring"
    assert fake.store[_entry("webhook:w1")] == "Bearer neu" and stale is None


def test_persist_typed_falls_back_to_the_file_and_names_the_stale_entry(fake_keyring):
    fake_keyring(working=False)
    stored = ws.stored_in_keyring(_hook("header"))
    saved, stale = ws.persist(_hook("header", value="Bearer neu"), "Bearer neu", stored=stored)
    assert saved["auth"]["value"] == "Bearer neu" and ws.SECRET_LOCATION not in saved["auth"]
    assert stale == "webhook:w1"      # abräumen erst NACH store.save


@pytest.mark.parametrize("typed", ["", "   "])
def test_persist_blank_keeps_the_keyring_secret(fake_keyring, typed):
    """Leer ODER nur Leerzeichen = unverändert — Leerzeichen dürfen das
    gespeicherte Secret nicht überschreiben."""
    fake = fake_keyring()
    fake.store[_entry("webhook:w1")] = "Bearer alt"
    stored = ws.stored_in_keyring(_hook("header"))
    candidate = ws.stored_in_keyring(_hook("header"))

    saved, stale = ws.persist(candidate, typed, stored=stored)

    assert saved["auth"][ws.SECRET_LOCATION] == "keyring" and stale is None
    assert fake.store[_entry("webhook:w1")] == "Bearer alt"


def test_persist_switch_to_none_names_the_stale_entry(fake_keyring):
    fake = fake_keyring()
    fake.store[_entry("webhook:w1")] = "Bearer alt"
    saved, stale = ws.persist(_hook("none"), "", stored=ws.stored_in_keyring(_hook("header")))
    assert saved["auth"] == {"mode": "none"}
    assert stale == "webhook:w1"
    assert fake.store[_entry("webhook:w1")] == "Bearer alt"   # noch nicht abgeräumt


def test_validate_accepts_a_keyring_secret_without_value():
    assert webhook_store.validate_record(ws.stored_in_keyring(_hook("header")), []) == (True, "")


def test_validate_still_demands_a_value_in_file_mode():
    ok, _msg = webhook_store.validate_record(_hook("header", value=""), [])
    assert ok is False


def test_keyring_failure_kinds():
    assert ws.keyring_failure("unavailable")["kind"] == "keyring"
    missing = ws.keyring_failure("missing")
    assert missing["kind"] == "keyring_missing" and "neu eingeben" in missing["detail"]


def test_forget_by_id_removes_the_entry(fake_keyring):
    fake = fake_keyring()
    keyring_store.put("webhook:w1", "x")
    ws.forget_by_id("w1")
    assert _entry("webhook:w1") not in fake.store
```

An `tests/test_send_task_dispatch.py`:

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


def test_missing_keyring_entry_has_its_own_text():
    assert "fehlen" in st._KIND_TEXTS["keyring_missing"]
```

- [ ] **Step 2: RED.** Erwartet: ERROR `ModuleNotFoundError … src.webhook_secrets` bzw. FAIL.

- [ ] **Step 3: Implementieren**: `src/webhook_secrets.py`:

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
    """Schlüssel im Schlüsselbund (Service über keyring_store.service_for)."""
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
    """Datensatz fürs Senden, Secret eingesetzt.

    `(record, None)` sendefertig (Alt-Format unverändert); `(None,
    "unavailable")` Schlüsselbund antwortet nicht; `(None, "missing")`
    Eintrag fehlt. Nie ohne Secret senden: der Endpunkt antwortete 401, und
    der Nutzer suchte beim Token, obwohl der Schlüsselbund das Problem war.
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
            stored: dict[str, Any] | None) -> tuple[dict[str, Any], str | None]:
    """Entscheidet, wo das Secret landet, legt es ab und liefert
    `(zu_speichernder_datensatz, abzuräumender_schlüssel)`.

    Abgeräumt wird NICHT hier, sondern vom Aufrufer NACH `store.save` —
    scheiterte das Schreiben, zeigte der Datensatz sonst auf einen gelöschten
    Eintrag (dieselbe Regel wie `remove_record`).

    - Verfahren ohne Secret (`none`): Datensatz ohne Secret; ein altes
      Schlüsselbund-Secret ist abzuräumen.
    - `typed` mit Inhalt: in den Schlüsselbund; klappt das nicht, in den
      Datensatz (Alt-Format), und ein älterer Schlüsselbund-Eintrag ist
      abzuräumen (sonst zweite, veraltete Quelle).
    - `typed` leer oder nur Leerzeichen: unverändert (Dialog: „leer lassen =
      unverändert"). Verändert `candidate` nicht.
    """
    stale = keyring_key(candidate["id"]) if stored is not None and in_keyring(stored) else None
    field = secret_field(candidate)
    if field is None:
        out = copy.deepcopy(candidate)
        out.get("auth", {}).pop(SECRET_LOCATION, None)
        return out, stale
    if typed.strip():
        with_secret = copy.deepcopy(candidate)
        with_secret["auth"][field] = typed
        with_secret["auth"].pop(SECRET_LOCATION, None)
        if keyring_store.put(keyring_key(candidate["id"]), typed):
            return stored_in_keyring(with_secret), None
        return with_secret, stale
    return copy.deepcopy(candidate), None


def forget_by_id(webhook_id: str) -> None:
    """Nach dem Löschen eines Webhooks den Eintrag abräumen (wie
    `tab_smtp._delete_secret` — ein fehlender Eintrag ist kein Fehler)."""
    keyring_store.remove(keyring_key(webhook_id))


def keyring_failure(problem: str) -> dict[str, Any]:
    """Ergebnis-Dict eines Webhook-Kanals, dessen Secret nicht lesbar war."""
    if problem == "unavailable":
        return {"ok": False, "kind": "keyring", "error": None, "tb": None,
                "detail": "Die Zugangsdaten konnten nicht aus dem "
                          "Schlüsselbund gelesen werden."}
    return {"ok": False, "kind": "keyring_missing", "error": None, "tb": None,
            "detail": "Webhook bearbeiten und die Zugangsdaten neu eingeben."}
```

- [ ] **Step 4: `webhook_store.validate_record`**, in den Zweigen `header`/`hmac`:

```python
    # „secret_location" wie webhook_secrets.SECRET_LOCATION — hier als
    # Literal, damit der Store frei von Schlüsselbund-Code bleibt.
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

- [ ] **Step 5: `send_task`**
- In `for entry in webhooks:` vor dem `try:` einfügen:
  ```python
          record, problem = webhook_secrets.resolve(entry["record"])
          if problem is not None:
              results.append({"channel": "webhook",
                              "name": entry["record"].get("name", ""),
                              **webhook_secrets.keyring_failure(problem)})
              continue
  ```
  Die Zeile `record = entry["record"]` entfällt.
- Import um `webhook_secrets` erweitern.
- In `_KIND_TEXTS` nach `"keyring"` einfügen: `"keyring_missing": "Zugangsdaten fehlen im Schlüsselbund",`.

- [ ] **Step 6:** In die Whitelist `"src/webhook_secrets.py",` eintragen.

- [ ] **Step 7: GREEN.** Volle Suite, ruff, pyright.

- [ ] **Step 8: Commit.** `feat(webhooks): Secrets im Schlüsselbund — Regeln, Validierung, Versand (#101)`.

---

### Task 7: Webhook-Dialog und Lösch-Hook

**Files:**
- Modify: `src/dialogs/webhook_dialog.py`, `src/dialogs/settings_dialog/tab_webhooks.py`
- Test: `tests/test_record_list_tabs.py`

**Interfaces:**
- Consumes: Task 6 sowie `keyring_store.remove`

Der Dialog ist Tk-Code ohne Unit-Tests; seine Logik steckt in Task 6. Der Lösch-Hook bekommt Tests.

- [ ] **Step 1: Hook-Tests (RED).** In `tests/test_record_list_tabs.py`:
- `test_webhook_remove_never_touches_the_keyring` umbenennen zu `test_webhook_remove_never_touches_the_smtp_keyring`. Der Inhalt bleibt.
- Anhängen:

```python
def test_webhook_remove_forgets_its_keyring_entry_after_the_record(monkeypatch):
    _answer(monkeypatch, WebhooksTab, yes=True)
    order = []
    monkeypatch.setattr(keyring_store, "remove", lambda key: order.append(("remove", key)))
    tab = _tab(WebhooksTab, _HOOKS)
    tab._store.delete.side_effect = lambda rid: order.append(("delete", rid))
    _select(tab, 0)

    tab._remove()

    assert order == [("delete", "w0"), ("remove", "webhook:w0")]


def test_webhook_remove_keeps_the_keyring_entry_when_the_write_fails(monkeypatch):
    _answer(monkeypatch, WebhooksTab, yes=True)
    removed = []
    monkeypatch.setattr(keyring_store, "remove", removed.append)
    tab = _tab(WebhooksTab, _HOOKS)
    tab._store.delete.side_effect = OSError("Platte voll")
    _select(tab, 0)

    tab._remove()

    assert removed == []
```

- [ ] **Step 2: Lösch-Hook** in `tab_webhooks.py`:

```python
def _forget_secret(webhook_id):
    # Wie tab_smtp._delete_secret: erst NACH dem erfolgreichen Schreiben
    # (remove_record ruft den Hook nur dann), und ein fehlender Eintrag ist
    # kein Fehler. Für Webhooks ohne Schlüsselbund-Secret ein No-op.
    webhook_secrets.forget_by_id(webhook_id)
```

In `WEBHOOKS_KIND` als `after_delete=_forget_secret` eintragen; Import `from src import webhook_secrets, webhook_store`.

- [ ] **Step 3: Dialog: Vorbefüllen und Hinweis**
- Nach `auth = dict(record.get("auth") or {"mode": "none"})` einfügen:
  ```python
      stored = None if is_new else dict(record)
      # Liegt das Secret im Schlüsselbund, steht es nicht im Datensatz — das
      # Feld bleibt leer, „leer lassen = unverändert" (wie im SMTP-Dialog).
      # Im Datei-Modus bleibt der Klartext wie bisher vorbefüllt.
      stored_in_keyring = stored is not None and webhook_secrets.in_keyring(stored)
      stored_mode = auth.get("mode", "none")
  ```
- `value_var`/`secret_var` werden weiter aus `auth.get(...)` vorbelegt. Im Schlüsselbund-Fall ergibt das `""`.
- In `_rebuild_auth_fields`: Ist `stored_in_keyring` gesetzt **und** der gewählte Modus gleich `stored_mode`, kommt unter das Secret-Feld ein Label mit dem Text „Liegt im Schlüsselbund des Betriebssystems. Leer lassen = unverändert." (`font=FONT_SMALL`, `fg=TEXT_MUTED`, `bg=BG`, `justify="left"`, `wraplength=380`). Es wird in die nächste freie Zeile des `auth_frame` gegriddet.

- [ ] **Step 4: `_collect` / `_validated`**

```python
    def _collect():
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
        if (mode in ("header", "hmac") and not typed.strip()
                and stored_in_keyring and mode == stored_mode):
            # „leer lassen = unverändert": nur die Markierung, kein Wert.
            new_auth.pop("value", None)
            new_auth.pop("secret", None)
            new_auth[webhook_secrets.SECRET_LOCATION] = "keyring"
            typed = ""
        return {
            "id": record["id"],
            "name": name_var.get().strip(),
            "url": url_var.get().strip(),
            "enabled": bool(enabled_var.get()),
            "payload": {"json": bool(json_var.get()), "pdf": bool(pdf_var.get())},
            "auth": new_auth,
        }, typed

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

- [ ] **Step 5: Speichern und Test-Versand**
- `do_save`, `fn`:
  ```python
          def fn():
              try:
                  to_save, stale = webhook_secrets.persist(candidate, typed, stored)
                  store.save(to_save)
              except (webhook_store.WebhookStoreReadOnly, OSError) as e:
                  return {"ok": False, "error": e}
              if stale is not None:
                  keyring_store.remove(stale)   # erst NACH dem Schreiben
              return {"ok": True}
  ```
- `do_test`, `fn`:
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
- Imports: `from src import keyring_store, webhook, webhook_secrets, webhook_store`.

- [ ] **Step 6: GREEN.** Volle Suite, ruff, pyright.

- [ ] **Step 7: Commit.** `feat(webhooks): Dialog und Löschen mit Schlüsselbund (#101)`.

---

### Task 8: `secret_migration`: Umzug beim Start

**Files:**
- Create: `src/secret_migration.py`, `tests/test_secret_migration.py`
- Modify: `tests/test_type_annotations.py` (`"src/secret_migration.py",`)

**Interfaces:**
- Consumes: Task 2, 3, 4 (`TOKEN_LOCK`), 6; `webhook_store.WebhookStoreReadOnly`
- Produces:
  - `MigrationReport(token_moved, webhooks_moved, failures)` mit der Property `moved_anything`
  - `migrate(token_path, webhook_store) -> MigrationReport`
  - `notice(report, system) -> tuple[str, str]`
  - `toast_text(report) -> str`

- [ ] **Step 1: Tests**: `tests/test_secret_migration.py`:

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
    fake_keyring()
    token = _token(tmp_path)
    store = _store(tmp_path, _hook())

    report = sm.migrate(str(token), store)

    assert report.token_moved and report.webhooks_moved == ("Ziel",)
    data = json.loads(token.read_text(encoding="utf-8"))
    assert "refresh_token" not in data and data["token"] == "ya29.a"
    assert data[oauth_utils.REFRESH_TOKEN_LOCATION] == "keyring"
    assert keyring_store.fetch(data[oauth_utils.REFRESH_TOKEN_KEY]) == "1//r"
    saved = store.get_all()[0]
    assert "value" not in saved["auth"] and ws.in_keyring(saved)
    assert keyring_store.fetch("webhook:w1") == "Bearer abc"


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
        raise KeyboardInterrupt  # Abbruch zwischen Zurücklesen und Datei-Schreiben

    monkeypatch.setattr(sm, "write_token_json", crash)
    try:
        sm.migrate(str(token), None)
    except KeyboardInterrupt:
        pass
    assert json.loads(token.read_text(encoding="utf-8"))["refresh_token"] == "1//r"

    monkeypatch.setattr(sm, "write_token_json", oauth_utils.write_token_json)
    assert sm.migrate(str(token), None).token_moved


def test_notice_texts():
    title, text = sm.notice(sm.MigrationReport(token_moved=True, webhooks_moved=("A", "B")), "Windows")
    assert title == "Zugangsdaten im Schlüsselbund"
    assert text.startswith("Deine Google-Anmeldung und die Zugangsdaten von 2 Webhooks liegen jetzt")
    assert "macOS" not in text
    _t, only_token = sm.notice(sm.MigrationReport(token_moved=True), "Windows")
    assert only_token.startswith("Deine Google-Anmeldung liegt jetzt")
    _t, one_hook = sm.notice(sm.MigrationReport(webhooks_moved=("A",)), "Windows")
    assert one_hook.startswith("Die Zugangsdaten von 1 Webhook liegen jetzt")
    _t, mac = sm.notice(sm.MigrationReport(token_moved=True), "Darwin")
    assert "nach App-Updates" in mac
    assert sm.toast_text(sm.MigrationReport(token_moved=True)) == \
        "Zugangsdaten liegen jetzt im Schlüsselbund."
```

- [ ] **Step 2: RED.** Erwartet: ERROR `ModuleNotFoundError … src.secret_migration`.

- [ ] **Step 3: Implementieren**: `src/secret_migration.py`:

```python
"""Umzug der Zugangsdaten in den Schlüsselbund beim Start (#101) — und das
Abräumen bei der Deinstallation (`forget_all`).

Idempotent und bei jedem Start geprüft — kein Versionsvergleich nötig: der
erste Start nach dem Update zieht um, ebenso ein Linux-System, das erst
später einen Secret Service bekommt. Pro Secret: in den Schlüsselbund
schreiben, zurücklesen, NUR bei Übereinstimmung die Datei neu schreiben.
Jeder Abbruch davor lässt die Datei gültig; der nächste Start holt nach.

Einzige Stelle, die umzieht — `token_store.save_credentials` behält den Ort
bei. Der Schlüsselbund wird nur gefragt, wenn es etwas umzuziehen gibt
(sonst löste jeder Start auf macOS einen Keychain-Dialog aus, Spec R4).
Tk-frei; läuft im BackgroundTaskRunner, nie vor dem Tk-Aufbau.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from src import keyring_store, webhook_secrets
from src.oauth_utils import (
    REFRESH_TOKEN_KEY, REFRESH_TOKEN_LOCATION, new_token_keyring_key,
    read_token_meta, token_in_keyring, write_token_json,
)
from src.token_store import TOKEN_LOCK
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


def _plaintext_refresh_token(token_path: str) -> str:
    meta = read_token_meta(token_path)
    if meta is None or token_in_keyring(meta):
        return ""
    token = meta.get("refresh_token")
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
    with TOKEN_LOCK:
        key = new_token_keyring_key()
        if not _stored_and_verified(key, secret):
            return False
        meta = read_token_meta(token_path)
        if meta is None or meta.get("refresh_token") != secret:
            # Zwischendurch neu geschrieben (Refresh, Rotation): der nächste
            # Start zieht den dann gültigen Token um.
            log.info("token.json hat sich während des Umzugs geändert")
            keyring_store.remove(key)
            return False
        meta.pop("refresh_token")
        meta[REFRESH_TOKEN_LOCATION] = "keyring"
        meta[REFRESH_TOKEN_KEY] = key
        try:
            write_token_json(json.dumps(meta), token_path)
        except OSError:
            log.warning("token.json ließ sich nach dem Umzug nicht schreiben",
                        exc_info=True)
            keyring_store.remove(key)
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
    # „liegt" nur, wenn allein die Google-Anmeldung umgezogen ist —
    # „Zugangsdaten" ist Plural.
    verb = "liegt" if parts == ["deine Google-Anmeldung"] else "liegen"
    text = (f"{what[:1].upper()}{what[1:]} {verb} jetzt im Schlüsselbund des "
            "Betriebssystems statt im Klartext im Datenordner.")
    if system == "Darwin":
        text += ("\n\nmacOS kann nach App-Updates erneut fragen, ob Zeiterfassung "
                 "auf den Schlüsselbund zugreifen darf.")
    return "Zugangsdaten im Schlüsselbund", text


def toast_text(report: MigrationReport) -> str:
    """Kurzform für den Tray-Toast (Autostart mit --minimized)."""
    return "Zugangsdaten liegen jetzt im Schlüsselbund."
```

- [ ] **Step 4:** In die Whitelist `"src/secret_migration.py",` eintragen.

- [ ] **Step 5: GREEN.** `python -m pytest tests/test_secret_migration.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:warnings`.

- [ ] **Step 6: Commit.** `feat: Zugangsdaten beim Start geprüft in den Schlüsselbund umziehen (#101)`.

---

### Task 9: Umzug beim Start anstoßen, Hinweis zeigen

**Files:**
- Modify: `src/background_tasks.py` (`migrate_secrets`), `src/ui.py`
- Test: `tests/test_background_tasks.py` (anhängen), `tests/test_ui_secret_notice.py` (neu)

**Interfaces:**
- Consumes: Task 5 und 8
- Produces: `BackgroundTaskRunner.migrate_secrets(webhook_store, on_done)`, `App._on_secrets_migrated(report)`

- [ ] **Step 1: Tests**

```python
# tests/test_background_tasks.py — anhängen
def test_migrate_secrets_reports_the_result(tmp_path, monkeypatch):
    from src import background_tasks, secret_migration
    reports = []
    runner = background_tasks.BackgroundTaskRunner.__new__(background_tasks.BackgroundTaskRunner)
    runner._base_path = str(tmp_path)
    runner.run = lambda fn, on_done: on_done(fn())
    monkeypatch.setattr(secret_migration, "migrate",
                        lambda path, store: secret_migration.MigrationReport(token_moved=True))
    runner.migrate_secrets(object(), reports.append)
    assert reports == [secret_migration.MigrationReport(token_moved=True)]


def test_migrate_secrets_swallows_and_logs_unexpected_errors(tmp_path, monkeypatch, caplog):
    from src import background_tasks, secret_migration
    reports = []
    runner = background_tasks.BackgroundTaskRunner.__new__(background_tasks.BackgroundTaskRunner)
    runner._base_path = str(tmp_path)
    runner.run = lambda fn, on_done: on_done(fn())

    def boom(*a):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(secret_migration, "migrate", boom)
    runner.migrate_secrets(object(), reports.append)
    assert reports == [] and "Umzug der Zugangsdaten" in caplog.text
```

```python
# tests/test_ui_secret_notice.py — neu
from unittest.mock import MagicMock

import pytest

from src.secret_migration import MigrationReport
from src.ui import App


def _app(state="normal", tray=None):
    fake = MagicMock()
    fake.root.state.return_value = state
    fake._tray = tray
    return fake


@pytest.mark.parametrize("state", ["normal", "zoomed"])
def test_notice_is_a_dialog_when_the_window_is_visible(monkeypatch, state):
    shown = []
    monkeypatch.setattr("src.ui.themed_showinfo", lambda *a: shown.append(a))
    App._on_secrets_migrated(_app(state), MigrationReport(token_moved=True))
    assert len(shown) == 1 and shown[0][1] == "Zugangsdaten im Schlüsselbund"


def test_notice_is_a_toast_when_started_minimized(monkeypatch):
    shown = []
    monkeypatch.setattr("src.ui.themed_showinfo", lambda *a: shown.append(a))
    tray = MagicMock()
    App._on_secrets_migrated(_app("withdrawn", tray), MigrationReport(token_moved=True))
    assert shown == []
    tray.notify.assert_called_once_with("Zugangsdaten liegen jetzt im Schlüsselbund.")


def test_no_notice_when_nothing_moved(monkeypatch):
    shown = []
    monkeypatch.setattr("src.ui.themed_showinfo", lambda *a: shown.append(a))
    tray = MagicMock()
    App._on_secrets_migrated(_app("normal", tray), MigrationReport())
    assert shown == [] and not tray.notify.called
```

- [ ] **Step 2: RED.** Erwartet: FAIL.

- [ ] **Step 3: `migrate_secrets`** (nach `refresh_token`; Import `from src import secret_migration`):

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

- [ ] **Step 4: `App`** (Import `from src import secret_migration`)
- Im Aufruf `self._bg.refresh_token(...)` einfügen:
  ```python
              # Erst NACH dem Start-Refresh: beide schreiben token.json (#101).
              on_finished=lambda: self._bg.migrate_secrets(
                  self._webhook_store, self._on_secrets_migrated),
  ```
- Neue Methode neben `_on_reconcile_start_done`:
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

- [ ] **Step 5: GREEN.** Volle Suite, ruff, pyright.

- [ ] **Step 6: Commit.** `feat: Umzug nach dem Start-Refresh anstoßen, Hinweis als Dialog oder Toast (#101)`.

---

### Task 10: Deinstallation räumt den Schlüsselbund ab

**Files:**
- Modify: `src/secret_migration.py` (`forget_all`), `src/main.py` (Modus `--forget-secrets`), `installer.iss`
- Test: `tests/test_secret_migration.py` (anhängen), `tests/test_main_forget_secrets.py` (neu)

**Interfaces:**
- Consumes: `oauth_utils.read_token_meta/token_in_keyring/REFRESH_TOKEN_KEY`; `keyring_store.remove/delete_secret`; `webhook_secrets.in_keyring/keyring_key`; `webhook_store.WebhookStore`; `smtp_store.SmtpStore`
- Produces: `secret_migration.forget_all(base_path: str) -> None`; Aufruf `Zeiterfassung.exe --forget-secrets` bzw. `python -m src.main --forget-secrets`

- [ ] **Step 1: Tests**

```python
# tests/test_secret_migration.py — anhängen
def test_forget_all_removes_token_webhook_and_smtp_entries(tmp_path, fake_keyring):
    from src.smtp_store import SmtpStore
    fake = fake_keyring()
    token = _token(tmp_path)
    store = _store(tmp_path, _hook())
    sm.migrate(str(token), store)                         # Token + Webhook im Schlüsselbund
    smtp = SmtpStore(str(tmp_path / "smtp.json"))
    smtp.save({"id": "s1", "name": "Firma", "enabled": True, "host": "smtp.example.org",
               "port": 587, "security": "starttls", "username": "u",
               "from_addr": "a@example.org", "recipient": "b@example.org",
               "password_location": "keyring"})
    keyring_store.set_secret("s1", "pw")

    sm.forget_all(str(tmp_path))

    assert fake.store == {}


def test_forget_all_without_files_is_quiet(tmp_path):
    sm.forget_all(str(tmp_path))
```

```python
# tests/test_main_forget_secrets.py — neu
"""`--forget-secrets` (Deinstallation): räumt ab und beendet sich, ohne Tk,
ohne Single-Instance-Guard und ohne Autostart-Migration."""

import sys


def test_forget_secrets_mode_returns_before_anything_else(tmp_path, monkeypatch):
    from src import main as main_mod, secret_migration
    calls = []
    monkeypatch.setattr(sys, "argv", ["Zeiterfassung.exe", "--forget-secrets"])
    monkeypatch.setattr(main_mod, "get_base_path", lambda: str(tmp_path))
    monkeypatch.setattr(main_mod, "setup_logging", lambda base: None)
    monkeypatch.setattr(secret_migration, "forget_all", lambda base: calls.append(base))

    def forbidden(*a, **k):
        raise AssertionError("darf im --forget-secrets-Modus nicht laufen")

    monkeypatch.setattr(main_mod, "migrate_legacy_autostart", forbidden)
    monkeypatch.setattr("src.single_instance.acquire", forbidden)
    monkeypatch.setattr(main_mod.tk, "Tk", forbidden)

    main_mod.main()

    assert calls == [str(tmp_path)]
```

Die Namen `get_base_path`, `setup_logging`, `migrate_legacy_autostart` und `tk` als Modul-Attribute von `src/main.py` prüfen. Weichen sie ab, werden die Patch-Ziele angepasst, nicht der Produktivcode.

- [ ] **Step 2: RED.** Erwartet: FAIL.

- [ ] **Step 3: `forget_all`**. Anhängen an `secret_migration`; Imports `import os`, `from src.smtp_store import SmtpStore` und `from src.webhook_store import WebhookStore` ergänzen (`WebhookStoreReadOnly` steht schon im Import aus `webhook_store`).

```python
def forget_all(base_path: str) -> None:
    """Deinstallation (#101): alle Schlüsselbund-Einträge dieses
    Datenverzeichnisses abräumen — Refresh-Token, Webhook- und SMTP-Secrets.

    Gerufen vom Uninstaller (`Zeiterfassung.exe --forget-secrets`) BEVOR er
    die Dateien löscht: aus ihnen stammen die Schlüssel. Wirft nie — jede
    Quelle einzeln, ein Fehler in einer hält die übrigen nicht auf.
    """
    meta = read_token_meta(os.path.join(base_path, "token.json"))
    key = meta.get(REFRESH_TOKEN_KEY) if meta is not None and token_in_keyring(meta) else None
    if isinstance(key, str) and key:
        keyring_store.remove(key)
    try:
        hooks = WebhookStore(os.path.join(base_path, "webhooks.json")).get_all()
    except Exception:
        # Bewusst alles: kaputte/fremde Datei — die übrigen Quellen trotzdem.
        log.warning("webhooks.json beim Abräumen nicht lesbar", exc_info=True)
        hooks = []
    for record in hooks:
        if webhook_secrets.in_keyring(record):
            keyring_store.remove(webhook_secrets.keyring_key(record["id"]))
    try:
        accounts = SmtpStore(os.path.join(base_path, "smtp.json")).get_all()
    except Exception:
        # Bewusst alles, s. o.
        log.warning("smtp.json beim Abräumen nicht lesbar", exc_info=True)
        accounts = []
    for account in accounts:
        if account.get("password_location") == "keyring":
            keyring_store.delete_secret(account["id"])
```

- [ ] **Step 4: `src/main.py`**. In `main()` direkt nach dem Logging-`try`/`except` und **vor** `from src import single_instance` einfügen:

```python
    # Deinstallation (installer.iss): Schlüsselbund-Einträge abräumen und
    # sofort beenden — ohne Tk, ohne Single-Instance-Guard, ohne
    # Autostart-Migration (die schriebe sonst den Run-Wert, den der
    # Uninstaller gerade entfernt).
    if "--forget-secrets" in sys.argv:
        try:
            from src import secret_migration
            secret_migration.forget_all(base)
        except Exception:
            logging.getLogger(__name__).exception(
                "Abräumen des Schlüsselbunds fehlgeschlagen")
        return
```

- [ ] **Step 5: `installer.iss`**
- **`[UninstallDelete]`:** `Type: files; Name: "{app}\smtp.json"` ergänzen. Im Kommentar „Diese vier Dateien" zu „Diese fünf Dateien" ändern und anfügen: „`smtp.json` trägt ohne Schlüsselbund das Mail-Passwort im Klartext — sie gehört seit dem SMTP-Feature hierher und fehlte (#101)."
- **`CurUninstallStepChanged`:** Die Deklaration `var ResultCode: Integer;` kommt zwischen `procedure …;` und `begin`. Im Zweig `usUninstall` als **ersten** Schritt, vor `HadToken := …`:
  ```pascal
      // Schlüsselbund abräumen (#101), BEVOR [UninstallDelete] token.json,
      // webhooks.json und smtp.json löscht — die Exe liest aus ihnen, welche
      // Einträge dazugehören. Ohne das bliebe der Refresh-Token in der
      // Windows-Anmeldeinformationsverwaltung stehen, und der Hinweis unten
      // („Google-Anmeldung entfernt") wäre falsch. Scheitert der Aufruf,
      // läuft die Deinstallation trotzdem weiter.
      Exec(ExpandConstant('{app}\Zeiterfassung.exe'), '--forget-secrets', '',
           SW_HIDE, ewWaitUntilTerminated, ResultCode);
  ```

- [ ] **Step 6: GREEN.** Volle Suite, ruff, pyright. `installer.iss` lässt sich lokal nicht kompilieren (Inno fehlt, s. CLAUDE.md); geprüft wird es in Task 11 Step 8.

- [ ] **Step 7: Commit.** `feat: Deinstallation räumt den Schlüsselbund ab, smtp.json wird mit entfernt (#101)`.

---

### Task 11: Doku und Verifikation

**Files:**
- Modify: `CLAUDE.md`, `src/CLAUDE.md`, `docs/known-limitations.md`, `README.md`, `CONTRIBUTING.md`

- [ ] **Step 1: `CLAUDE.md`**
- **Strukturliste:** Einträge für `src/token_store.py` (Ort beibehalten; Umziehen nur `secret_migration`; nur der Refresh-Token; Schlüssel in der Datei), `src/webhook_secrets.py` (SMTP-Muster; `persist` räumt nach dem Speichern ab) und `src/secret_migration.py` (idempotenter Umzug, Hinweis, `forget_all` für den Uninstaller).
- **`keyring_store`:** um `put`/`fetch`/`remove` ergänzen, mit Service-Name pro Eintrag und Prozess-Cache „nur bei Änderung".
- **`secure_file`:** Klartext bleibt nur ohne Schlüsselbund.
- **`installer.iss`:** `--forget-secrets` und `smtp.json` in `[UninstallDelete]`.
- **„Installation & Daten":** ein Satz: Mit Schlüsselbund enthalten `token.json`/`webhooks.json` keinen Refresh-Token bzw. keine Webhook-Secrets.

- [ ] **Step 2: `src/CLAUDE.md`**
- **„Google-Integration":** Token nur über `token_store`; `forget_token` statt `os.remove`; `TokenKeyringUnavailable` ist kein Auth-Fehler und startet keinen Flow.
- **`secure_file`** anpassen.
- **„Wo gehört neuer Code hin?":** Ein neues Secret kommt über `keyring_store` plus Datei-Fallback plus Eintrag in `secret_migration.forget_all`.

- [ ] **Step 3: `docs/known-limitations.md`.** Den bestehenden macOS-Keychain-Absatz **erweitern**, nicht verdoppeln. Neu hinzu kommen:
- **Downgrade:** Eine ältere Version liest den Refresh-Token nicht (google-auth `ValueError` „missing fields refresh_token"). Abhilfe: einmal „Google neu verbinden". Webhooks mit Auth senden dort ohne Wert bzw. signieren mit leerem Secret.
- **Datenordner auf einen anderen Rechner kopiert:** Google neu verbinden, Webhook-Secrets neu eingeben.
- **Windows-Größenlimit:** Deshalb liegt nur der Refresh-Token im Schlüsselbund.
- **Extern gelöschter Eintrag:** fällt erst beim nächsten Start auf (Prozess-Cache).
- **Klartext-Reste außerhalb des Umzugs:** Quarantäne-Dateien `webhooks.json.corrupt-*` und `.token-*.tmp` nach einem Prozessabbruch.
- **macOS/Linux** haben keinen Uninstaller. Die Einträge (Service beginnt mit `Zeiterfassung:`) lassen sich in „Schlüsselbundverwaltung" bzw. „Passwörter und Schlüssel" von Hand entfernen.

- [ ] **Step 4: `README.md`.** Beide Abschnitte bekommen den Marker `*(ab --VERSION--)*` am fetten Stichwort (Regel „README-Zeilen für Unveröffentlichtes"):
- **Sicherheitshinweis (Z. ~394–418):** Mit verfügbarem Schlüsselbund liegen Refresh-Token, Webhook-Secrets und SMTP-Passwort dort, nicht im Klartext; ohne bleibt es wie beschrieben. Die Windows-Deinstallation entfernt auch die Schlüsselbund-Einträge.
- **„Bestehendes Token verwerfen" (Z. ~241–248):** Der empfohlene Weg ist Einstellungen → Google → „Google neu verbinden", das den Schlüsselbund-Eintrag mit abräumt. Die Datei zu löschen bleibt als Alternative; der Eintrag im Schlüsselbund bleibt dann bis zur nächsten Anmeldung stehen.

- [ ] **Step 5: `CONTRIBUTING.md`:** In der Abhängigkeiten-Tabelle bei `keyring` „SMTP-Passwörter" ersetzen durch „SMTP-Passwörter, OAuth-Refresh-Token, Webhook-Secrets".

- [ ] **Step 6: Prüfen und committen.** Volle Suite inklusive `test_claude_md_claims.py`. Wird er rot, das Muster nachziehen, nicht die Behauptung. Dazu ruff. Commit: `docs: Schlüsselbund für Token und Webhooks (#101)`.

- [ ] **Step 7: Verifikation mit echtem Windows-Schlüsselbund, nur Fake-Daten, kein Commit**

Ausführbar durch einen Subagenten, unter drei Bedingungen: **eigener Service-Name, Scratch-Daten, Fake-Tokens**.
1. `python -m venv --system-site-packages "$SP/kvenv"` und `"$SP/kvenv/Scripts/python" -m pip install -q keyring==25.7.0`.
2. Scratch-Datenverzeichnis `"$SP/k101data"` anlegen mit:
   - `settings.json` mit `sync_enabled: false` und `gcal_enabled: false`;
   - einer Fake-`token.json` mit `"refresh_token": "1//fake-refresh"`, `"token": "ya29.fake"` und `"expiry": "2030-01-01T00:00:00Z"`, damit kein Refresh gegen Google läuft, dazu Fake-`client_id`/`client_secret`;
   - einer `webhooks.json` mit einem Header-Webhook und Fake-Token.
3. Harness im Scratchpad:
   - `ZEITERFASSUNG_DATA_DIR` setzen;
   - **vor allem anderen `keyring_store.SERVICE = "Zeiterfassung-Verify101"`**, damit echte `Zeiterfassung`-Einträge nie berührt werden;
   - `themed_showinfo` in `src.ui` so umhüllen, dass Titel und Text auf stdout landen;
   - `src.main.main()` starten und nach ~10 s über `_quit_with_sync_push` beenden.
4. Erwartet nach dem 1. Start:
   - `HINWEIS: Zugangsdaten im Schlüsselbund …`;
   - `token.json` ohne `refresh_token`, mit `refresh_token_location`/`refresh_token_key`;
   - `webhooks.json` ohne `value`, mit `secret_location`;
   - `"$SP/kvenv/Scripts/python" -c "import keyring; print(keyring.get_password('Zeiterfassung-Verify101:<key>', '<key>'))"` liefert den Fake-Wert.
5. Beim 2. Start erscheint kein Hinweis.
6. `--forget-secrets` gegen dasselbe Verzeichnis, mit gesetztem Service-Namen im Harness. Danach liefern beide `get_password` `None`.
7. Aufräumen: `cmdkey /list | grep -i Verify101` ist leer; Scratch-Verzeichnis und venv löschen.

- [ ] **Step 8: STOPP. Verifikation mit echten Daten und Uninstaller, nur mit dem Menschen**

**Kein Subagent** führt diese Schritte aus. Der Controller beschreibt sie dem Nutzer und wartet:
- **Frozen-Build:** Workflow **Build** mit `installer`-Häkchen auf `feat/secrets-keyring` starten. Ergebnis: Onedir-Artefakt und Setup.
- **Kopie eines echten Datenordners** gegen das Onedir-Artefakt, mit `ZEITERFASSUNG_DATA_DIR` auf die Kopie. Zu prüfen: Umzug und Hinweis, Senden, Drive-Sync, Kalender, Webhook. Dabei laufen echte Google-Aufrufe mit dem echten Token, und der Drive-Sync spricht mit dem echten Sync-Dokument. Ob, wie und mit welchen Einstellungen (z. B. Sync aus) das läuft, entscheidet der Nutzer.
- **Uninstaller:** Das Setup in einer Windows-Sandbox oder VM installieren, mit Token und Webhook wieder deinstallieren. Danach darf `cmdkey /list` keine `Zeiterfassung:`-Einträge mehr zeigen, und `smtp.json` muss weg sein.
- **Pre-Release auf allen drei Plattformen** vor dem nächsten echten Release, zusammen mit dem offenen Pre-Release aus #123/R9.

---

## Abschluss

Nach Task 11 Step 7 folgt `superpowers:finishing-a-development-branch`. Der Merge setzt Step 8 voraus, das entscheidet der Nutzer. In die PR-Beschreibung gehören:
- `Closes #101` (Stufe 1; `credentials.json` bleibt als Idee im Issue-Kommentar);
- die Downgrade-Einschränkung;
- der Pre-Release-Hinweis;
- das Verifikationsergebnis;
- die Nebenbefunde: `smtp.json` fehlte im Uninstaller (behoben), `vacations.json` fehlt in `DeleteUserData` (eigenes Issue).
