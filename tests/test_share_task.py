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
