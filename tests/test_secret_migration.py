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


def test_readback_mismatch_removes_the_unverified_entry(tmp_path, fake_keyring):
    fake = fake_keyring(lie=True)
    sm.migrate(str(_token(tmp_path)), _store(tmp_path, _hook()))
    assert fake.store == {}


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


def test_migration_reuses_a_key_the_file_already_carries(tmp_path, fake_keyring):
    """Nach einem Datei-Fallback trägt token.json ihren Schlüssel weiter —
    der Umzug überschreibt denselben Eintrag, statt einen neuen anzulegen."""
    fake = fake_keyring()
    fake.store[(keyring_store.service_for("google-oauth:k1"), "google-oauth:k1")] = "1//alt"
    token = _token(tmp_path, refresh_token_key="google-oauth:k1")

    assert sm.migrate(str(token), None).token_moved

    data = json.loads(token.read_text(encoding="utf-8"))
    assert data[oauth_utils.REFRESH_TOKEN_KEY] == "google-oauth:k1"
    assert fake.store == {(keyring_store.service_for("google-oauth:k1"), "google-oauth:k1"): "1//r"}


def test_forget_all_removes_the_entry_of_a_file_mode_token_with_key(tmp_path, fake_keyring):
    fake = fake_keyring()
    fake.store[(keyring_store.service_for("google-oauth:k1"), "google-oauth:k1")] = "1//r"
    _token(tmp_path, refresh_token_key="google-oauth:k1")

    sm.forget_all(str(tmp_path))

    assert fake.store == {}


def test_forget_all_without_files_is_quiet(tmp_path):
    sm.forget_all(str(tmp_path))


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


def test_forget_all_goes_on_when_webhooks_json_is_broken(tmp_path, fake_keyring):
    fake = fake_keyring()
    token = _token(tmp_path)
    sm.migrate(str(token), None)                          # Token im Schlüsselbund
    (tmp_path / "webhooks.json").write_text("kaputt", encoding="utf-8")

    sm.forget_all(str(tmp_path))

    assert fake.store == {}
