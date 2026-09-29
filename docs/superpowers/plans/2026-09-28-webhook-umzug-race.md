# Webhook-Umzug race-frei Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Start-Umzug der Webhook-Secrets in den Schlüsselbund und das Speichern im Webhook-Dialog hinterlassen bei gleichzeitigem Bearbeiten/Löschen weder verwaiste noch veraltete Schlüsselbund-Einträge und beleben keine gelöschten Webhooks wieder (Issue #173).

**Architecture:** Eine Modul-Sperre `webhook_secrets.SECRETS_LOCK` serialisiert Umzug und Dialog-Speichern. `WebhookStore.save_if_unchanged` schreibt atomar nur, wenn der Datensatz unverändert ist — das fängt das (ungesperrte) Löschen ab. `_move_webhook` prüft den Datensatz vor dem `put` und räumt nur dort ab, wo der Eintrag sicher ihm gehört. Der Dialog-Kern wandert Tk-frei nach `webhook_secrets.save_with_secret` und rechnet mit dem aktuellen statt dem Schnappschuss-Datensatz.

**Tech Stack:** Python 3.12, `threading`, pytest mit `fake_keyring`-Fixture (`tests/conftest.py`).

**Spec:** `docs/superpowers/specs/2026-09-28-webhook-umzug-race-design.md` (inkl. „Nachträge aus dem Review")

## Global Constraints

- Die Store-Sperre (`WebhookStore._lock`) wird nie über einen Schlüsselbund-Aufruf gehalten — `webhook_dialog.py:188` liest `store.get_all()` im UI-Thread.
- `webhook_store.py` importiert weder `keyring_store` noch `webhook_secrets` (Trennung aus #101).
- `SECRETS_LOCK` ist ein `threading.Lock` (kein `RLock`) auf Modulebene in `src/webhook_secrets.py`. Lock-Reihenfolge immer `SECRETS_LOCK` → (`keyring_store._write_lock` | `store._lock`), nie umgekehrt.
- Das Löschen (`_record_list_tab.remove_record`) nimmt `SECRETS_LOCK` nicht.
- Token-Weg (`_move_token`, `TOKEN_LOCK`) und `forget_all` bleiben unverändert.
- `src/webhook_store.py`, `src/webhook_secrets.py`, `src/secret_migration.py` stehen in der Annotations-Whitelist (`tests/test_type_annotations.py`): neue Funktionen vollständig annotieren (Parameter **und** Rückgabe).
- **Jeder Race-Test muss gegen den alten Code rot sein** (Spec, Abschnitt „Tests"): Auslöser nur an Stellen, die alter und neuer Ablauf gleich durchlaufen — vor `_move_webhook`, am Anfang von `keyring_store.put`, in `webhook_secrets.stored_in_keyring`. Nie im Zurücklesen (`fetch`) oder im erneuten `get_all`.
- Deutsch in Kommentaren/Docstrings, Stil wie im umgebenden Code; kein neuer Catch-all (`except Exception`). Commit-Messages enden mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Vor jedem Commit: `python -m pytest -q` (voll), `ruff check .`, `npx -y pyright@1.1.411 | tail -1` (erwartet: `0 errors, 32 warnings` wie auf `master`).

## Review Focus

- **Mehrere Webhooks, einer wird mittendrin gelöscht:** die übrigen ziehen trotzdem um, der gelöschte hinterlässt keinen Eintrag — Task 2 `test_deleted_webhook_does_not_block_the_others`.
- **Dialog nach dem Umzug auf „Keine Authentifizierung" umgestellt:** der Schlüsselbund-Eintrag wird abgeräumt, obwohl der Dialog vor dem Umzug geöffnet wurde — Task 3 `test_switch_to_none_after_migration_removes_the_entry`.
- **`put` im Dialog scheitert nach dem Umzug:** Rückfall auf Klartext, der alte Eintrag verschwindet — Task 3 `test_failed_put_after_migration_removes_the_old_entry`.
- **`save_if_unchanged` bei Schreibschutz:** wirft, Liste unverändert — Task 1 `test_save_if_unchanged_read_only_raises_and_keeps_list`.
- **Schlüsselbund nicht verfügbar beim Umzug:** nichts gespeichert, nichts abgeräumt, Klartext bleibt — bestehender Test `test_without_keyring_everything_stays` muss grün bleiben.

---

### Task 1: `WebhookStore.save_if_unchanged`

**Files:**
- Modify: `src/webhook_store.py` (neue Methode direkt nach `save`, ca. Zeile 280)
- Test: `tests/test_webhook_store.py`

**Interfaces:**
- Consumes: —
- Produces: `WebhookStore.save_if_unchanged(self, expected: Webhook, record: Webhook) -> bool` — `True` = geschrieben; `False` = unter `expected["id"]` steht nichts oder etwas anderes als `expected`, nichts geschrieben (auch nicht auf Platte). `ValueError`, wenn `record["id"] != expected["id"]`. Wirft sonst wie `save` (`WebhookStoreReadOnly`/`OSError`) mit Rollback.

- [ ] **Step 1: Write the failing tests** (ans Ende von `tests/test_webhook_store.py`; `_record`, `_store`, `whs`, `pytest` sind dort schon importiert/definiert)

```python
# --- save_if_unchanged (Xveyn#173) -------------------------------------------
# Der Umzug in den Schlüsselbund speichert nur, wenn niemand den Datensatz
# zwischendurch gelöscht oder geändert hat — sonst belebte ein `save` einen
# gerade gelöschten Webhook wieder (save legt an ODER ersetzt).

def test_save_if_unchanged_writes_when_equal(tmp_path):
    store = _store(tmp_path)
    store.save(_record())
    assert store.save_if_unchanged(_record(), _record(name="Neu")) is True
    assert [w["name"] for w in store.get_all()] == ["Neu"]


def test_save_if_unchanged_refuses_a_deleted_record(tmp_path):
    store = _store(tmp_path)
    store.save(_record())
    store.delete("id-1")
    assert store.save_if_unchanged(_record(), _record(name="Neu")) is False
    assert store.get_all() == []


def test_save_if_unchanged_refuses_a_changed_record(tmp_path):
    store = _store(tmp_path)
    store.save(_record(name="Anders"))
    assert store.save_if_unchanged(_record(), _record(name="Neu")) is False
    assert [w["name"] for w in store.get_all()] == ["Anders"]


def test_save_if_unchanged_refusal_leaves_the_file_alone(tmp_path):
    path = str(tmp_path / "webhooks.json")
    store = WebhookStore(path)
    store.save(_record(name="Anders"))
    store.save_if_unchanged(_record(), _record(name="Neu"))
    assert [w["name"] for w in WebhookStore(path).get_all()] == ["Anders"]


def test_save_if_unchanged_rejects_mismatched_ids(tmp_path):
    store = _store(tmp_path)
    store.save(_record())
    with pytest.raises(ValueError):
        store.save_if_unchanged(_record(), _record(id="id-2"))


def test_save_if_unchanged_rolls_back_a_failed_write(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.save(_record())
    monkeypatch.setattr(whs.WebhookStore, "_save_to_disk",
                        lambda self: (_ for _ in ()).throw(OSError("voll")))
    with pytest.raises(OSError):
        store.save_if_unchanged(_record(), _record(name="Neu"))
    assert [w["name"] for w in store.get_all()] == ["Server"]


def test_save_if_unchanged_read_only_raises_and_keeps_list(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.save(_record())
    monkeypatch.setattr(whs.WebhookStore, "_save_to_disk",
                        lambda self: (_ for _ in ()).throw(whs.WebhookStoreReadOnly("ro")))
    with pytest.raises(whs.WebhookStoreReadOnly):
        store.save_if_unchanged(_record(), _record(name="Neu"))
    assert [w["name"] for w in store.get_all()] == ["Server"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_webhook_store.py -k save_if_unchanged -q`
Expected: 7 failed, `AttributeError: 'WebhookStore' object has no attribute 'save_if_unchanged'`

- [ ] **Step 3: Implement** (in `src/webhook_store.py`, direkt nach `save`)

```python
    def save_if_unchanged(self, expected: Webhook, record: Webhook) -> bool:
        """Wie `save`, aber nur, wenn unter `expected["id"]` noch genau
        `expected` steht. `False`, wenn der Datensatz inzwischen gelöscht oder
        geändert wurde — dann wird nichts geschrieben.

        Für den Umzug in den Schlüsselbund (Xveyn#173): ein bedingungsloses
        `save` legte einen gerade gelöschten Webhook wieder an. Prüfen und
        Schreiben liegen unter derselben Sperre; ein Schlüsselbund-Aufruf
        gehört nicht hinein (`get_all` läuft auch im UI-Thread).

        Ruft `save` unter der eigenen Sperre — das setzt das reentrante
        `RLock` voraus, das der Store ohne `lock=` selbst anlegt.

        Wirft wie `save` und rollt dann zurück; `ValueError` bei
        verschiedenen `id`s (Programmierfehler)."""
        if record.get("id") != expected.get("id"):
            raise ValueError("save_if_unchanged: expected und record tragen "
                             "verschiedene ids")
        with self._lock:
            current = next((w for w in self._webhooks
                            if w.get("id") == expected.get("id")), None)
            if current != expected:
                return False
            self.save(record)
            return True
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_webhook_store.py tests/test_type_annotations.py -q`
Expected: alle grün

- [ ] **Step 5: Voll prüfen und committen**

Run: `python -m pytest -q && ruff check . && npx -y pyright@1.1.411 | tail -1`

```bash
git add src/webhook_store.py tests/test_webhook_store.py
git commit -m "feat(webhooks): save_if_unchanged für bedingtes Speichern (#173)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `SECRETS_LOCK` und race-freies `_move_webhook`

**Files:**
- Modify: `src/webhook_secrets.py` (Import `threading`, Konstante `SECRETS_LOCK` nach `_FIELDS`)
- Modify: `src/secret_migration.py:101-116` (`_move_webhook` neu)
- Test: `tests/test_secret_migration.py`

**Interfaces:**
- Consumes: `WebhookStore.save_if_unchanged(expected, record) -> bool` (Task 1)
- Produces: `webhook_secrets.SECRETS_LOCK: threading.Lock` — Task 3 nimmt ihn in `save_with_secret`.

- [ ] **Step 1: Write the failing tests** (ans Ende von `tests/test_secret_migration.py`; `_hook`, `_store`, `sm`, `ws`, `keyring_store` existieren dort bereits)

```python
# --- Race mit Bearbeiten/Löschen (Xveyn#173) --------------------------------
# Jeder Auslöser hängt an einer Stelle, die alter und neuer Ablauf gleich
# durchlaufen — sonst wäre der Test schon gegen den alten Code grün.

def _token_path(tmp_path):
    return str(tmp_path / "token.json")   # existiert nicht: nur Webhooks


def _before_move(monkeypatch, action):
    """`action` läuft, bevor _move_webhook den Webhook anfasst (nach dem
    Snapshot in migrate) — z. B. der Dialog speichert vorher."""
    orig = sm._move_webhook

    def wrapped(store, record):
        action()
        return orig(store, record)
    monkeypatch.setattr(sm, "_move_webhook", wrapped)


def _at_first_put(monkeypatch, action):
    """`action` läuft am Anfang des ersten keyring_store.put — also mitten
    im Umzug, bevor das Secret im Schlüsselbund liegt."""
    orig = keyring_store.put
    fired = {"done": False}

    def put(key, value):
        if not fired["done"]:
            fired["done"] = True
            action()
        return orig(key, value)
    monkeypatch.setattr(keyring_store, "put", put)


def _before_save(monkeypatch, action):
    """`action` läuft unmittelbar bevor der Umzug den Datensatz speichert
    (stored_in_keyring baut ihn, direkt vor save/save_if_unchanged)."""
    orig = ws.stored_in_keyring

    def stored_in_keyring(record):
        action()
        return orig(record)
    monkeypatch.setattr(ws, "stored_in_keyring", stored_in_keyring)


def test_new_secret_saved_by_dialog_is_not_overwritten(tmp_path, fake_keyring, monkeypatch):
    """Fall 2: der Dialog hat nach dem Start-Snapshot, aber vor dem Umzug
    dieses Webhooks ein neues Secret abgelegt. Alt: put(alt) überschrieb es."""
    fake_keyring()
    store = _store(tmp_path, _hook(value="Bearer alt"))

    def dialog_save():
        keyring_store.put(ws.keyring_key("w1"), "Bearer neu")
        store.save(ws.stored_in_keyring(_hook(value="Bearer neu")))
    _before_move(monkeypatch, dialog_save)

    report = sm.migrate(_token_path(tmp_path), store)

    assert report.webhooks_moved == ()
    assert keyring_store.fetch("webhook:w1") == "Bearer neu"
    assert ws.in_keyring(store.get_all()[0])


def test_webhook_deleted_during_move_leaves_no_entry(tmp_path, fake_keyring, monkeypatch):
    """Fall 1 (das Issue): gelöscht, während der Umzug läuft. Alt: der
    Eintrag blieb verwaist, kein Codepfad erreicht ihn mehr."""
    fake = fake_keyring()
    store = _store(tmp_path, _hook())

    def delete():
        store.delete("w1")
        ws.forget_by_id("w1")
    _at_first_put(monkeypatch, delete)

    report = sm.migrate(_token_path(tmp_path), store)

    assert report.webhooks_moved == ()
    assert store.get_all() == []
    assert fake.store == {}


def test_webhook_deleted_right_before_save_stays_deleted(tmp_path, fake_keyring, monkeypatch):
    """Fall 3: gelöscht unmittelbar vor dem Speichern. Alt: save legte den
    Webhook wieder an."""
    fake = fake_keyring()
    store = _store(tmp_path, _hook())
    _before_save(monkeypatch, lambda: store.delete("w1"))

    report = sm.migrate(_token_path(tmp_path), store)

    assert report.webhooks_moved == ()
    assert store.get_all() == []
    assert fake.store == {}


def test_webhook_deleted_before_move_touches_no_keyring(tmp_path, fake_keyring, monkeypatch):
    fake = fake_keyring()
    store = _store(tmp_path, _hook())
    _before_move(monkeypatch, lambda: store.delete("w1"))

    report = sm.migrate(_token_path(tmp_path), store)

    assert report.webhooks_moved == ()
    assert fake.store == {}


def test_failed_save_removes_the_entry_and_keeps_plaintext(tmp_path, fake_keyring, monkeypatch):
    fake = fake_keyring()
    store = _store(tmp_path, _hook())
    monkeypatch.setattr(store, "save_if_unchanged",
                        lambda *a: (_ for _ in ()).throw(OSError("voll")))

    report = sm.migrate(_token_path(tmp_path), store)

    assert report.webhooks_moved == () and report.failures
    assert fake.store == {}
    assert store.get_all()[0]["auth"]["value"] == "Bearer abc"
    assert not ws.SECRETS_LOCK.locked()


def test_lock_is_held_during_put(tmp_path, fake_keyring, monkeypatch):
    fake_keyring()
    store = _store(tmp_path, _hook())
    seen = []
    orig = keyring_store.put

    def put(key, value):
        seen.append(ws.SECRETS_LOCK.locked())
        return orig(key, value)
    monkeypatch.setattr(keyring_store, "put", put)

    sm.migrate(_token_path(tmp_path), store)

    assert seen == [True]
    assert not ws.SECRETS_LOCK.locked()


def test_deleted_webhook_does_not_block_the_others(tmp_path, fake_keyring, monkeypatch):
    fake = fake_keyring()
    store = _store(tmp_path, _hook(), _hook(hid="w3", name="Zweites", value="Bearer z"))
    orig = sm._move_webhook

    def wrapped(s, record):
        if record["id"] == "w1":
            store.delete("w1")
        return orig(s, record)
    monkeypatch.setattr(sm, "_move_webhook", wrapped)

    report = sm.migrate(_token_path(tmp_path), store)

    assert report.webhooks_moved == ("Zweites",)
    assert list(fake.store.values()) == ["Bearer z"]
```

- [ ] **Step 2: Run to verify they fail — aus dem richtigen Grund**

Run: `python -m pytest tests/test_secret_migration.py -q`
Expected (gegen den alten `_move_webhook`, nach Task 1):
- `test_new_secret_saved_by_dialog_is_not_overwritten`: FAIL — `fetch("webhook:w1") == "Bearer alt"` (alter Code überschreibt)
- `test_webhook_deleted_during_move_leaves_no_entry`: FAIL — `fake.store` enthält den verwaisten Eintrag
- `test_webhook_deleted_right_before_save_stays_deleted`: FAIL — `store.get_all()` enthält den wiederbelebten Webhook
- `test_webhook_deleted_before_move_touches_no_keyring`: FAIL — `fake.store` enthält einen Eintrag (alter Code macht `put` vor der Prüfung)
- `test_failed_save_removes_the_entry_and_keeps_plaintext`: FAIL — alter Code ruft `save`, nicht `save_if_unchanged`; der Webhook zieht um, `report.webhooks_moved == ("Ziel",)`
- `test_lock_is_held_during_put`: FAIL — `AttributeError: SECRETS_LOCK`
- `test_deleted_webhook_does_not_block_the_others`: FAIL — `fake.store` enthält zusätzlich den Eintrag von `w1`

Ist einer davon grün, ist der Auslöser falsch gesetzt — nicht weitermachen, sondern den Test korrigieren.

- [ ] **Step 3: Implement**

In `src/webhook_secrets.py` — `import threading` zu den Imports (nach `import copy`) und nach `_FIELDS = {...}`:

```python
# Serialisiert alles, was ein Webhook-Secret im Schlüsselbund ablegt UND den
# Datensatz dazu speichert: den Start-Umzug (`secret_migration._move_webhook`)
# und das Dialog-Speichern (`save_with_secret`). Ohne sie überschrieb der
# Umzug ein gerade neu eingegebenes Secret mit dem alten (Xveyn#173). Das
# Löschen nimmt sie nicht — `WebhookStore.save_if_unchanged` fängt es ab.
# Beide Halter laufen im Worker; darunter wird die Store-Sperre nie über
# einen Schlüsselbund-Aufruf gehalten.
SECRETS_LOCK = threading.Lock()
```

In `src/secret_migration.py` `_move_webhook` ersetzen:

```python
def _move_webhook(store: Any, record: dict[str, Any]) -> bool:
    """Zieht das Secret eines Webhooks um — race-frei gegen Bearbeiten und
    Löschen (Xveyn#173).

    Unter `SECRETS_LOCK` wird der Datensatz VOR dem `put` neu gelesen: hat der
    Dialog ihn geändert, bleibt der Schlüsselbund unberührt (sonst
    überschriebe der Umzug das neue Secret mit dem alten). Gespeichert wird
    nur über `save_if_unchanged` — ein zwischendurch gelöschter Webhook
    lebt nicht wieder auf. Abgeräumt wird nur, wo der Eintrag sicher dem
    Umzug gehört: der Dialog-Weg ist durch die Sperre ausgeschlossen."""
    secret = webhook_secrets.plaintext_secret(record)
    key = webhook_secrets.keyring_key(record["id"])
    with webhook_secrets.SECRETS_LOCK:
        current = next((r for r in store.get_all() if r.get("id") == record["id"]), None)
        if current is None or webhook_secrets.plaintext_secret(current) != secret:
            log.info("Ein Webhook hat sich vor dem Umzug geändert")
            return False
        if not _stored_and_verified(key, secret):
            return False
        try:
            saved = store.save_if_unchanged(
                current, webhook_secrets.stored_in_keyring(current))
        except (WebhookStoreReadOnly, OSError):
            log.warning("webhooks.json ließ sich nach dem Umzug nicht schreiben",
                        exc_info=True)
            keyring_store.remove(key)
            return False
        if not saved:
            log.info("Ein Webhook wurde während des Umzugs gelöscht")
            keyring_store.remove(key)
            return False
        return True
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_secret_migration.py tests/test_webhook_secrets.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q`
Expected: alle grün, inkl. der bestehenden `test_moves_token_and_webhooks`, `test_without_keyring_everything_stays`, `test_readback_mismatch_removes_the_unverified_entry`, `test_second_run_does_nothing`.

- [ ] **Step 5: Voll prüfen und committen**

Run: `python -m pytest -q && ruff check . && npx -y pyright@1.1.411 | tail -1`

```bash
git add src/webhook_secrets.py src/secret_migration.py tests/test_secret_migration.py
git commit -m "fix(secrets): Webhook-Umzug race-frei gegen Bearbeiten und Löschen (#173)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `save_with_secret` — Dialog-Kern Tk-frei, unter der Sperre, mit aktuellem Datensatz

**Files:**
- Modify: `src/webhook_secrets.py` (neue Funktion `save_with_secret` nach `persist`)
- Modify: `src/dialogs/webhook_dialog.py:208-216` (`do_save.fn` ruft nur noch `save_with_secret`)
- Modify: `src/CLAUDE.md` (Abschnitt „Wo gehört neuer Code hin?", Punkt „**Ein neues Secret** (#101)")
- Modify: `CLAUDE.md` (Modulliste, Eintrag `src/webhook_secrets.py`, ca. Zeile 1294)
- Test: `tests/test_webhook_secrets.py`

**Interfaces:**
- Consumes: `webhook_secrets.SECRETS_LOCK` (Task 2), `webhook_secrets.persist(candidate, typed, stored) -> (record, stale)` (bestehend)
- Produces: `webhook_secrets.save_with_secret(store: Any, candidate: dict[str, Any], typed: str, stored: dict[str, Any] | None) -> None` — wirft `WebhookStoreReadOnly`/`OSError` von `store.save` und `ValueError` von `persist` unverändert durch.

- [ ] **Step 1: Write the failing tests** (ans Ende von `tests/test_webhook_secrets.py`; `_hook`, `ws`, `keyring_store`, `webhook_store`, `pytest` sind dort schon importiert/definiert. `_hook(mode)` liefert `id="w1"`.)

```python
# --- save_with_secret: der Dialog-Kern (Xveyn#173) --------------------------
# Der Dialog hält einen Schnappschuss `stored` vom Öffnen. War er über den
# Start-Umzug hinweg offen, ist der längst veraltet — gerechnet wird deshalb
# mit dem aktuellen Datensatz.

def _migrated_store(tmp_path):
    """Store und Schlüsselbund nach einem Umzug: Datensatz in
    Schlüsselbund-Form, Secret unter webhook:w1."""
    store = webhook_store.WebhookStore(str(tmp_path / "webhooks.json"))
    keyring_store.put(ws.keyring_key("w1"), "Bearer abc")
    store.save(ws.stored_in_keyring(_hook("header")))
    return store


def test_switch_to_none_after_migration_removes_the_entry(tmp_path, fake_keyring):
    """Dialog vor dem Umzug geöffnet (`stored` = Klartext), nach dem Umzug auf
    „Keine" gestellt: aus `stored` berechnet bliebe das Secret für immer
    stehen — nicht einmal forget_all fände es."""
    fake = fake_keyring()
    store = _migrated_store(tmp_path)

    ws.save_with_secret(store, _hook("none"), "", stored=_hook("header"))

    assert store.get_all()[0]["auth"] == {"mode": "none"}
    assert fake.store == {}


def test_failed_put_after_migration_removes_the_old_entry(tmp_path, fake_keyring, monkeypatch):
    """Scheitert das put im Dialog, landet das neue Secret im Klartext — der
    alte Schlüsselbund-Eintrag ist dann eine zweite, veraltete Quelle."""
    fake = fake_keyring()
    store = _migrated_store(tmp_path)
    monkeypatch.setattr(keyring_store, "put", lambda key, value: False)

    ws.save_with_secret(store, _hook("header"), "Bearer neu", stored=_hook("header"))

    assert store.get_all()[0]["auth"]["value"] == "Bearer neu"
    assert fake.store == {}


def test_failed_write_keeps_the_entry(tmp_path, fake_keyring, monkeypatch):
    """Erst NACH dem Schreiben abräumen — sonst zeigte der unveränderte
    Datensatz auf einen gelöschten Eintrag."""
    fake = fake_keyring()
    store = _migrated_store(tmp_path)
    monkeypatch.setattr(store, "save", lambda record: (_ for _ in ()).throw(OSError("voll")))

    with pytest.raises(OSError):
        ws.save_with_secret(store, _hook("none"), "", stored=_hook("header"))

    assert list(fake.store.values()) == ["Bearer abc"]
    assert not ws.SECRETS_LOCK.locked()


def test_new_webhook_falls_back_to_the_snapshot(tmp_path, fake_keyring):
    fake = fake_keyring()
    store = webhook_store.WebhookStore(str(tmp_path / "webhooks.json"))

    ws.save_with_secret(store, _hook("header"), "Bearer neu", stored=None)

    assert ws.in_keyring(store.get_all()[0])
    assert list(fake.store.values()) == ["Bearer neu"]


def test_save_with_secret_holds_the_lock_during_put(tmp_path, fake_keyring, monkeypatch):
    fake_keyring()
    store = webhook_store.WebhookStore(str(tmp_path / "webhooks.json"))
    seen = []
    orig = keyring_store.put

    def put(key, value):
        seen.append(ws.SECRETS_LOCK.locked())
        return orig(key, value)
    monkeypatch.setattr(keyring_store, "put", put)

    ws.save_with_secret(store, _hook("header"), "Bearer neu", stored=None)

    assert seen == [True]
    assert not ws.SECRETS_LOCK.locked()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_webhook_secrets.py -k "save_with_secret or after_migration or failed_write_keeps or falls_back" -q`
Expected: 5 failed, `AttributeError: module 'src.webhook_secrets' has no attribute 'save_with_secret'`

- [ ] **Step 3: Implement** — in `src/webhook_secrets.py` nach `persist`:

```python
def save_with_secret(store: Any, candidate: dict[str, Any], typed: str,
                     stored: dict[str, Any] | None) -> None:
    """Der Kern von „Speichern" im Webhook-Dialog: Secret ablegen, Datensatz
    schreiben, danach einen veralteten Eintrag abräumen.

    Unter `SECRETS_LOCK`, serialisiert mit dem Start-Umzug (Xveyn#173).
    Gerechnet wird mit dem AKTUELLEN Datensatz, nicht mit dem Schnappschuss
    `stored` vom Öffnen des Dialogs: war der über den Umzug hinweg offen,
    zeigte `stored` noch Klartext, und ein Umstellen auf „Keine" oder ein
    gescheitertes `put` ließe das umgezogene Secret für immer im
    Schlüsselbund stehen. Fehlt der Datensatz (neu oder inzwischen
    gelöscht), gilt `stored`.

    Wirft Schreibfehler von `store.save` und `ValueError` von `persist`
    durch; abgeräumt wird dann nichts. Blockierend (Schlüsselbund, icacls) —
    gehört in einen Worker."""
    with SECRETS_LOCK:
        current = next((r for r in store.get_all()
                        if r.get("id") == candidate.get("id")), None)
        to_save, stale = persist(
            candidate, typed, current if current is not None else stored)
        store.save(to_save)
    if stale is not None:
        keyring_store.remove(stale)   # erst NACH dem Schreiben
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_webhook_secrets.py tests/test_type_annotations.py -q`
Expected: alle grün

- [ ] **Step 5: Dialog umstellen** — in `src/dialogs/webhook_dialog.py`, `do_save`, den Körper von `fn` ersetzen:

```python
        def fn():
            try:
                # Tk-frei in webhook_secrets: unter der Sperre mit dem
                # Start-Umzug, gerechnet mit dem aktuellen Datensatz statt
                # `stored` (Xveyn#173). Räumt einen veralteten Eintrag erst
                # nach dem Schreiben ab.
                webhook_secrets.save_with_secret(store, candidate, typed, stored)
            except (webhook_store.WebhookStoreReadOnly, OSError) as e:
                return {"ok": False, "error": e}
            return {"ok": True}
```

Danach prüfen, ob `keyring_store` in `webhook_dialog.py` noch benutzt wird (`grep -n "keyring_store" src/dialogs/webhook_dialog.py`); wenn nicht, aus der Importzeile `from src import keyring_store, webhook, webhook_secrets, webhook_store` entfernen (ruff meldet es sonst als F401).

- [ ] **Step 6: `src/CLAUDE.md` ergänzen** — im Punkt „- **Ein neues Secret** (#101) …" unter „## Wo gehört neuer Code hin?" als eigenen Absatz am Ende des Punktes anhängen:

```markdown
  Webhook-Secrets haben zusätzlich eine Sperre (`webhook_secrets.SECRETS_LOCK`,
  Xveyn#173): Start-Umzug (`secret_migration._move_webhook`) und
  Dialog-Speichern (`webhook_secrets.save_with_secret`) legen das Secret ab und
  speichern den Datensatz nur unter ihr. Der Umzug speichert über
  `WebhookStore.save_if_unchanged`, damit ein gleichzeitig gelöschter Webhook
  nicht wieder auflebt; das Dialog-Speichern rechnet mit dem aktuellen
  Datensatz statt dem Schnappschuss vom Öffnen. Die Store-Sperre wird dabei nie
  über einen Schlüsselbund-Aufruf gehalten (`get_all` läuft auch im
  UI-Thread). Wer einen weiteren Schreiber für Webhook-Secrets baut, nimmt die
  Sperre mit. Grenze: ein Schlüsselbund-Aufruf, der in den 30-s-Watchdog
  läuft, kann danach noch landen (Spec 2026-09-28-webhook-umzug-race).
```

- [ ] **Step 7: Root-`CLAUDE.md` ergänzen** — der Eintrag `src/webhook_secrets.py` der Modulliste (ca. Zeile 1294) endet mit

```markdown
  Aufrufer **nach** `store.save`, sonst zeigte der Datensatz bei einem
  gescheiterten Schreibvorgang auf einen bereits gelöschten Eintrag
```

Die letzte Zeile ersetzen durch:

```markdown
  gescheiterten Schreibvorgang auf einen bereits gelöschten Eintrag. Ablegen
  und Speichern laufen unter `SECRETS_LOCK`, den auch der Start-Umzug nimmt;
  der Dialog-Kern ist `save_with_secret` (Xveyn#173)
```

- [ ] **Step 8: Voll prüfen**

Run: `python -m pytest -q && ruff check . && npx -y pyright@1.1.411 | tail -1`
Expected: alle Tests grün (inkl. `tests/test_claude_md_claims.py`), `All checks passed!`, `0 errors, 32 warnings`

- [ ] **Step 9: Commit**

```bash
git add src/webhook_secrets.py src/dialogs/webhook_dialog.py tests/test_webhook_secrets.py src/CLAUDE.md CLAUDE.md
git commit -m "fix(webhooks): Dialog-Speichern mit dem Umzug serialisiert, aktueller Datensatz (#173)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
