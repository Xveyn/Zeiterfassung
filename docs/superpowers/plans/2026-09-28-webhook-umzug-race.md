# Webhook-Umzug race-frei Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Start-Umzug der Webhook-Secrets in den Schlüsselbund hinterlässt bei gleichzeitigem Bearbeiten/Löschen weder verwaiste noch veraltete Einträge und belebt keine gelöschten Webhooks wieder (Issue #173).

**Architecture:** Eine Modul-Sperre `webhook_secrets.SECRETS_LOCK` serialisiert Umzug und Dialog-Speichern. `WebhookStore.save_if_unchanged` schreibt atomar nur, wenn der Datensatz unverändert ist — das fängt das (ungesperrte) Löschen ab. `_move_webhook` prüft den Datensatz vor dem `put` und räumt nur dort ab, wo der Eintrag sicher ihm gehört.

**Tech Stack:** Python 3.12, `threading`, pytest mit `fake_keyring`-Fixture (`tests/conftest.py`).

**Spec:** `docs/superpowers/specs/2026-09-28-webhook-umzug-race-design.md`

## Global Constraints

- Die Store-Sperre (`WebhookStore._lock`) wird nie über einen Schlüsselbund-Aufruf gehalten — `webhook_dialog.py:188` liest `store.get_all()` im UI-Thread.
- `webhook_store.py` importiert weder `keyring_store` noch `webhook_secrets` (Trennung aus #101).
- `SECRETS_LOCK` ist ein `threading.Lock` (kein `RLock`) auf Modulebene in `src/webhook_secrets.py`.
- Das Löschen (`_record_list_tab.remove_record`) nimmt `SECRETS_LOCK` nicht.
- Token-Weg (`_move_token`, `TOKEN_LOCK`) und `forget_all` bleiben unverändert.
- `src/webhook_store.py`, `src/webhook_secrets.py`, `src/secret_migration.py` stehen in der Annotations-Whitelist (`tests/test_type_annotations.py`): neue Funktionen vollständig annotieren.
- Deutsch in Kommentaren/Docstrings, Stil wie im umgebenden Code; Commit-Messages enden mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Vor jedem Commit: `pytest` (voll), `ruff check .`, `npx -y pyright@1.1.411` (erwartet: 0 errors, 32 warnings wie auf `master`).

## Review Focus

- **Mehrere Webhooks, einer wird mittendrin gelöscht:** die übrigen ziehen trotzdem um, der gelöschte hinterlässt keinen Eintrag — Test in Task 2 (`test_deleted_webhook_does_not_block_the_others`).
- **HMAC-Webhook statt Header:** dasselbe Race-Verhalten für `auth.secret` — Test in Task 2 (`test_hmac_webhook_deleted_during_move_leaves_no_entry`).
- **Schlüsselbund nicht verfügbar:** `put` scheitert → nichts gespeichert, nichts abgeräumt, Klartext bleibt (bestehender Test `test_without_keyring_everything_stays`, muss grün bleiben).
- **`save_if_unchanged` bei Schreibschutz (`WebhookStoreReadOnly`):** wirft, Liste unverändert — Test in Task 1 (`test_save_if_unchanged_read_only_raises_and_keeps_list`).
- **Sperre wird nach einem Fehler wieder freigegeben:** ein zweiter Umzugslauf nach einem gescheiterten Speichern hängt nicht — Test in Task 2 (`test_lock_is_released_after_failed_save`).

---

### Task 1: `WebhookStore.save_if_unchanged`

**Files:**
- Modify: `src/webhook_store.py` (neue Methode direkt nach `save`, ca. Zeile 280)
- Test: `tests/test_webhook_store.py`

**Interfaces:**
- Consumes: —
- Produces: `WebhookStore.save_if_unchanged(self, expected: Webhook, record: Webhook) -> bool` — `True` = geschrieben; `False` = unter `expected["id"]` steht nichts oder etwas anderes als `expected`, nichts geschrieben. Wirft wie `save` (`WebhookStoreReadOnly`/`OSError`) mit Rollback.

- [ ] **Step 1: Write the failing tests** (ans Ende von `tests/test_webhook_store.py`)

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
Expected: 5 failed, `AttributeError: 'WebhookStore' object has no attribute 'save_if_unchanged'`

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

        Wirft wie `save` und rollt dann zurück."""
        with self._lock:
            current = next((w for w in self._webhooks
                            if w.get("id") == expected.get("id")), None)
            if current != expected:
                return False
            self.save(record)
            return True
```

(`self._lock` ist ein `RLock` — der Aufruf von `save` unter derselben Sperre ist reentrant.)

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_webhook_store.py -q`
Expected: alle grün

- [ ] **Step 5: Commit**

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
- Produces: `webhook_secrets.SECRETS_LOCK: threading.Lock` — Task 3 nimmt ihn im Dialog.

- [ ] **Step 1: Write the failing tests** (ans Ende von `tests/test_secret_migration.py`; `_hook`/`_store`/`_token` existieren dort bereits)

```python
# --- Race mit Bearbeiten/Löschen (Xveyn#173) --------------------------------
# migrate() snapshotet die Webhooks einmal; _move_webhook liest den Datensatz
# unter SECRETS_LOCK erneut. Die konkurrierende Aktion wird deterministisch in
# den zweiten get_all-Aufruf (Neu-Lesen) bzw. ins Zurücklesen (fetch) gelegt.

def _hmac_hook(hid="w2", name="Signiert", secret="geheim"):
    return {"id": hid, "name": name, "url": "https://example.org/s", "enabled": True,
            "payload": {"json": True, "pdf": False},
            "auth": {"mode": "hmac", "secret": secret}}


def _act_on_reread(monkeypatch, store, action):
    """Führt `action` aus, sobald _move_webhook den Datensatz neu liest
    (zweiter get_all-Aufruf; der erste ist der Snapshot in migrate)."""
    orig = store.get_all
    calls = {"n": 0}

    def get_all():
        calls["n"] += 1
        if calls["n"] == 2:
            action()
        return orig()

    monkeypatch.setattr(store, "get_all", get_all)


def _act_on_readback(monkeypatch, action):
    """Führt `action` nach dem Zurücklesen des Secrets aus — also zwischen
    put und Speichern."""
    orig = keyring_store.fetch

    def fetch(key):
        value = orig(key)
        action()
        return value

    monkeypatch.setattr(keyring_store, "fetch", fetch)


def test_webhook_deleted_before_move_touches_no_keyring(tmp_path, fake_keyring, monkeypatch):
    fake = fake_keyring()
    store = _store(tmp_path, _hook())
    _act_on_reread(monkeypatch, store, lambda: store.delete("w1"))

    report = sm.migrate(str(tmp_path / "token.json"), store)

    assert report.webhooks_moved == ()
    assert fake.store == {}


def test_webhook_deleted_between_put_and_save_leaves_no_entry(tmp_path, fake_keyring, monkeypatch):
    """Fall 1 + 3: kein verwaister Eintrag, und der gelöschte Webhook wird
    nicht wieder angelegt."""
    fake = fake_keyring()
    store = _store(tmp_path, _hook())

    def delete():
        store.delete("w1")
        ws.forget_by_id("w1")
    _act_on_readback(monkeypatch, delete)

    report = sm.migrate(str(tmp_path / "token.json"), store)

    assert report.webhooks_moved == ()
    assert store.get_all() == []
    assert fake.store == {}


def test_new_secret_saved_by_dialog_is_not_overwritten(tmp_path, fake_keyring, monkeypatch):
    """Fall 2: der Dialog hat vor dem Umzug ein neues Secret abgelegt — der
    Umzug fasst den Schlüsselbund nicht an, das neue bleibt."""
    fake_keyring()
    store = _store(tmp_path, _hook(value="Bearer alt"))

    def dialog_save():
        keyring_store.put(ws.keyring_key("w1"), "Bearer neu")
        store.save(ws.stored_in_keyring(_hook(value="Bearer neu")))
    _act_on_reread(monkeypatch, store, dialog_save)

    report = sm.migrate(str(tmp_path / "token.json"), store)

    assert report.webhooks_moved == ()
    assert keyring_store.fetch("webhook:w1") == "Bearer neu"
    assert ws.in_keyring(store.get_all()[0])


def test_failed_save_removes_the_entry_and_keeps_plaintext(tmp_path, fake_keyring, monkeypatch):
    fake = fake_keyring()
    store = _store(tmp_path, _hook())
    monkeypatch.setattr(store, "save_if_unchanged",
                        lambda *a: (_ for _ in ()).throw(OSError("voll")))

    report = sm.migrate(str(tmp_path / "token.json"), store)

    assert report.webhooks_moved == () and report.failures
    assert fake.store == {}
    assert store.get_all()[0]["auth"]["value"] == "Bearer abc"


def test_lock_is_held_during_put(tmp_path, fake_keyring, monkeypatch):
    fake_keyring()
    store = _store(tmp_path, _hook())
    seen = []
    orig = keyring_store.put

    def put(key, value):
        seen.append(ws.SECRETS_LOCK.locked())
        return orig(key, value)
    monkeypatch.setattr(keyring_store, "put", put)

    sm.migrate(str(tmp_path / "token.json"), store)

    assert seen == [True]
    assert not ws.SECRETS_LOCK.locked()


def test_lock_is_released_after_failed_save(tmp_path, fake_keyring, monkeypatch):
    fake_keyring()
    store = _store(tmp_path, _hook())
    monkeypatch.setattr(store, "save_if_unchanged",
                        lambda *a: (_ for _ in ()).throw(OSError("voll")))
    sm.migrate(str(tmp_path / "token.json"), store)
    assert not ws.SECRETS_LOCK.locked()


def test_deleted_webhook_does_not_block_the_others(tmp_path, fake_keyring, monkeypatch):
    fake = fake_keyring()
    store = _store(tmp_path, _hook(), _hook(hid="w3", name="Zweites", value="Bearer z"))
    _act_on_reread(monkeypatch, store, lambda: store.delete("w1"))

    report = sm.migrate(str(tmp_path / "token.json"), store)

    assert report.webhooks_moved == ("Zweites",)
    assert list(fake.store.values()) == ["Bearer z"]


def test_hmac_webhook_deleted_during_move_leaves_no_entry(tmp_path, fake_keyring, monkeypatch):
    fake = fake_keyring()
    store = _store(tmp_path, _hmac_hook())

    def delete():
        store.delete("w2")
        ws.forget_by_id("w2")
    _act_on_readback(monkeypatch, delete)

    report = sm.migrate(str(tmp_path / "token.json"), store)

    assert report.webhooks_moved == ()
    assert store.get_all() == [] and fake.store == {}
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_secret_migration.py -q`
Expected: u. a. `test_webhook_deleted_before_move_touches_no_keyring` (Eintrag bleibt stehen), `test_webhook_deleted_between_put_and_save_leaves_no_entry` (Webhook wiederbelebt), `test_new_secret_saved_by_dialog_is_not_overwritten` (altes Secret im Schlüsselbund), `test_lock_is_held_during_put` (`AttributeError: SECRETS_LOCK`) rot.

- [ ] **Step 3: Implement**

In `src/webhook_secrets.py` — Import ergänzen (`import threading` zu `import copy`) und nach `_FIELDS = {...}`:

```python
# Serialisiert alles, was ein Webhook-Secret im Schlüsselbund ablegt UND den
# Datensatz dazu speichert: den Start-Umzug (`secret_migration._move_webhook`)
# und das Speichern im Dialog (`webhook_dialog.do_save`). Ohne sie überschrieb
# der Umzug ein gerade neu eingegebenes Secret mit dem alten (Xveyn#173).
# Das Löschen nimmt sie nicht — `WebhookStore.save_if_unchanged` fängt es ab.
# Beide Halter laufen im Worker; die Store-Sperre wird darunter nie über einen
# Schlüsselbund-Aufruf gehalten.
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

Run: `python -m pytest tests/test_secret_migration.py tests/test_webhook_store.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q`
Expected: alle grün (inkl. der bestehenden `test_moves_token_and_webhooks`, `test_without_keyring_everything_stays`, `test_readback_mismatch_removes_the_unverified_entry`)

- [ ] **Step 5: Commit**

```bash
git add src/webhook_secrets.py src/secret_migration.py tests/test_secret_migration.py
git commit -m "fix(secrets): Webhook-Umzug race-frei gegen Bearbeiten und Löschen (#173)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Dialog nimmt die Sperre, Doku

**Files:**
- Modify: `src/dialogs/webhook_dialog.py:208-216` (`do_save.fn`)
- Modify: `src/CLAUDE.md` (Abschnitt „Wo gehört neuer Code hin?", Punkt „Ein neues Secret")
- Modify: `CLAUDE.md` (Modulliste, Eintrag `src/webhook_secrets.py`)

**Interfaces:**
- Consumes: `webhook_secrets.SECRETS_LOCK` (Task 2)
- Produces: —

Tk-Code, nach Projektregel ohne automatisierten Test (s. CLAUDE.md „Getestet wird Logik, nicht UI"); geprüft per Review und über die volle Suite.

- [ ] **Step 1: Dialog-Worker unter die Sperre stellen** — in `do_save` den Körper von `fn` ersetzen:

```python
        def fn():
            try:
                # Mit dem Start-Umzug serialisiert (Xveyn#173): sonst
                # überschriebe der Umzug das hier abgelegte neue Secret mit
                # dem alten. Läuft im Worker — die Sperre blockiert nie die
                # Oberfläche.
                with webhook_secrets.SECRETS_LOCK:
                    to_save, stale = webhook_secrets.persist(candidate, typed, stored)
                    store.save(to_save)
            except (webhook_store.WebhookStoreReadOnly, OSError) as e:
                return {"ok": False, "error": e}
            if stale is not None:
                keyring_store.remove(stale)   # erst NACH dem Schreiben
            return {"ok": True}
```

- [ ] **Step 2: `src/CLAUDE.md` ergänzen** — im Punkt „**Ein neues Secret** (#101) …" unter „Wo gehört neuer Code hin?" anhängen:

```markdown
  Webhook-Secrets haben zusätzlich eine Sperre (`webhook_secrets.SECRETS_LOCK`,
  Xveyn#173): Start-Umzug und Dialog-Speichern legen das Secret ab und
  speichern den Datensatz nur unter ihr; der Umzug speichert über
  `WebhookStore.save_if_unchanged`, damit ein gleichzeitig gelöschter Webhook
  nicht wieder auflebt. Die Store-Sperre wird dabei nie über einen
  Schlüsselbund-Aufruf gehalten (`get_all` läuft auch im UI-Thread). Wer einen
  weiteren Schreiber für Webhook-Secrets baut, nimmt die Sperre mit.
```

- [ ] **Step 3: Root-`CLAUDE.md` ergänzen** — der Eintrag `src/webhook_secrets.py` der Modulliste (ca. Zeile 1294) endet mit den Zeilen

```markdown
  Aufrufer **nach** `store.save`, sonst zeigte der Datensatz bei einem
  gescheiterten Schreibvorgang auf einen bereits gelöschten Eintrag
```

Die letzte Zeile ersetzen durch:

```markdown
  gescheiterten Schreibvorgang auf einen bereits gelöschten Eintrag. Ablegen
  und Speichern laufen unter `SECRETS_LOCK`, den auch der Start-Umzug nimmt
  (Xveyn#173)
```

- [ ] **Step 4: Volle Prüfung**

Run: `python -m pytest -q && ruff check . && npx -y pyright@1.1.411 | tail -1`
Expected: alle Tests grün (inkl. `tests/test_claude_md_claims.py`), `All checks passed!`, `0 errors, 32 warnings`

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/webhook_dialog.py src/CLAUDE.md CLAUDE.md
git commit -m "fix(webhooks): Dialog-Speichern mit dem Umzug serialisiert (#173)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
