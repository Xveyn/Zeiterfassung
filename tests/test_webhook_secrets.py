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


def test_persist_rejects_a_keyring_marker_for_another_mode(fake_keyring):
    """Wechsel header→hmac mit leerem Feld darf die Markierung nicht
    übernehmen: im Eintrag läge noch der Header-Token, und der würde still
    als HMAC-Secret benutzt."""
    fake_keyring()
    stored = ws.stored_in_keyring(_hook("header"))
    candidate = ws.stored_in_keyring(_hook("hmac"))
    with pytest.raises(ValueError):
        ws.persist(candidate, "", stored=stored)


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
    Datensatz auf einen gelöschten Eintrag.

    Der Webhook existiert bereits, save_with_secret schreibt ihn also über
    `save_if_unchanged` — dessen Schreibkern ist `_save_to_disk`, nicht mehr
    `save` (M1, Xveyn#173 Abschluss-Review)."""
    fake = fake_keyring()
    store = _migrated_store(tmp_path)
    monkeypatch.setattr(store, "_save_to_disk", lambda: (_ for _ in ()).throw(OSError("voll")))

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


def test_save_does_not_resurrect_a_webhook_deleted_before(tmp_path, fake_keyring):
    """Xveyn#173 (Abschluss-Review): der Webhook wurde gelöscht, während das
    Dialog-Speichern auf die Sperre wartete — das Löschen gewinnt."""
    fake = fake_keyring()
    store = _migrated_store(tmp_path)
    snapshot = store.get_all()[0]
    store.delete("w1")
    ws.forget_by_id("w1")

    saved = ws.save_with_secret(store, _hook("header"), "Bearer neu", stored=snapshot)

    assert saved is False
    assert store.get_all() == []
    assert fake.store == {}


def test_save_does_not_resurrect_a_webhook_deleted_during_put(tmp_path, fake_keyring, monkeypatch):
    fake = fake_keyring()
    store = _migrated_store(tmp_path)
    snapshot = store.get_all()[0]
    orig = keyring_store.put
    fired = {"done": False}

    def put(key, value):
        if not fired["done"]:
            fired["done"] = True
            store.delete("w1")
            ws.forget_by_id("w1")
        return orig(key, value)
    monkeypatch.setattr(keyring_store, "put", put)

    saved = ws.save_with_secret(store, _hook("header"), "Bearer neu", stored=snapshot)

    assert saved is False
    assert store.get_all() == []
    assert fake.store == {}


def test_save_with_secret_reports_success(tmp_path, fake_keyring):
    fake_keyring()
    store = _migrated_store(tmp_path)
    assert ws.save_with_secret(store, _hook("none"), "", stored=_hook("header")) is True
