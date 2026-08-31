"""perform_share: Tk-freier Worker-Kern des Teilen-Dialogs (Audit M10)."""

import src.dialogs.share_task as st
from src.dialogs.share_task import perform_share


class _FakeSettings:
    def __init__(self):
        self.sets = []

    def set(self, k, v):
        self.sets.append((k, v))


def _kwargs(**over):
    base = dict(
        payload=b'{"x":1}', filename="share.json",
        credentials_path="c.json", token_path="t.json",
        recipient="to@example.com", subject="Subj", html="<p>x</p>",
        sync_enabled=False, gcal_enabled=False,
        save_default=False, settings=_FakeSettings(),
    )
    base.update(over)
    return base


def _patch_happy(monkeypatch, sent=None):
    monkeypatch.setattr(st, "get_gmail_service", lambda *a, **k: "svc")

    def fake_send(service, to, subject, html, **k):
        if sent is not None:
            sent["to"] = to
            sent["bytes"] = k.get("attachment_bytes")
            sent["subtype"] = k.get("attachment_subtype")
        return "mid"

    monkeypatch.setattr(st, "send_email", fake_send)


def test_perform_share_success_sends_json(monkeypatch):
    sent = {}
    _patch_happy(monkeypatch, sent)
    res = perform_share(**_kwargs())
    assert res == {"ok": True}
    assert sent["to"] == "to@example.com"
    assert sent["bytes"] == b'{"x":1}'
    assert sent["subtype"] == "json"


def test_perform_share_saves_default_recipient_when_requested(monkeypatch):
    _patch_happy(monkeypatch)
    s = _FakeSettings()
    res = perform_share(**_kwargs(save_default=True, recipient="x@y.z", settings=s))
    assert res["ok"] is True
    assert ("share_recipient", "x@y.z") in s.sets


def test_perform_share_does_not_save_when_not_requested(monkeypatch):
    _patch_happy(monkeypatch)
    s = _FakeSettings()
    perform_share(**_kwargs(save_default=False, settings=s))
    assert s.sets == []


def test_perform_share_error_delegates_to_classifier(monkeypatch):
    monkeypatch.setattr(st, "get_gmail_service", lambda *a, **k: "svc")

    def boom(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(st, "send_email", boom)
    sentinel = {"ok": False, "kind": "error", "error": None, "tb": "TB"}
    monkeypatch.setattr(st, "classify_mail_error", lambda e: sentinel)
    res = perform_share(**_kwargs())
    assert res is sentinel


def test_perform_share_missing_credentials_delegates_to_classifier(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError("credentials.json")

    monkeypatch.setattr(st, "get_gmail_service", missing)
    sentinel = {"ok": False, "kind": "filenotfound", "error": None, "tb": None}
    monkeypatch.setattr(st, "classify_mail_error", lambda e: sentinel)
    res = perform_share(**_kwargs())
    assert res is sentinel


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


def test_share_over_smtp_fails_instead_of_logging_in_with_an_empty_password(
        monkeypatch):
    """F1: `get_secret` signalisiert ein nicht lesbares Passwort über `None`.
    perform_share darf smtp.send dann NICHT mit einem leeren Passwort
    aufrufen, sondern muss ein Failure-Result liefern."""
    sent = []
    monkeypatch.setattr(st.keyring_store, "get_secret", lambda record: None)
    monkeypatch.setattr(st.smtp, "send", lambda *a, **k: sent.append(1))

    res = perform_share(**_kwargs(transport=_account()))

    assert sent == []
    assert res["ok"] is False
    assert res["kind"] == "keyring"


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
