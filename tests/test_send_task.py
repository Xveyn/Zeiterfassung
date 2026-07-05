"""perform_send: Tk-freier Worker-Kern des Sende-Dialogs (Audit M10)."""

import src.dialogs.send_task as st
from src.dialogs.send_task import perform_send


class _FakeSettings:
    def __init__(self, sender_email=""):
        self._d = {"sender_email": sender_email}
        self.sets = []

    def get(self, k):
        return self._d.get(k)

    def set(self, k, v):
        self.sets.append((k, v))
        self._d[k] = v


def _kwargs(**over):
    base = dict(
        date_from=None, date_to=None, entries={}, name="N",
        categories=None, category_breakdown=False,
        credentials_path="c.json", token_path="t.json",
        recipient="to@example.com", subject="Subj", html="<p>x</p>",
        pdf_filename="r.pdf",
        sync_enabled=False, gcal_enabled=False, settings=_FakeSettings(),
    )
    base.update(over)
    return base


def _patch_happy(monkeypatch, sent=None):
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")
    monkeypatch.setattr(st, "get_gmail_service", lambda *a, **k: "svc")

    def fake_send(service, to, subject, html, **k):
        if sent is not None:
            sent["to"] = to
            sent["bytes"] = k.get("attachment_bytes")
            sent["subtype"] = k.get("attachment_subtype")
        return "mid"

    monkeypatch.setattr(st, "send_email", fake_send)
    monkeypatch.setattr(st, "fetch_user_email", lambda *a, **k: "me@example.com")


def test_perform_send_success_sends_and_caches_sender(monkeypatch):
    sent = {}
    _patch_happy(monkeypatch, sent)
    s = _FakeSettings(sender_email="")
    res = perform_send(**_kwargs(settings=s))
    assert res == {"ok": True}
    assert sent["to"] == "to@example.com"
    assert sent["bytes"] == b"PDF"
    assert sent["subtype"] == "pdf"
    assert ("sender_email", "me@example.com") in s.sets


def test_perform_send_sender_cache_failure_is_swallowed(monkeypatch):
    _patch_happy(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("no net")

    monkeypatch.setattr(st, "fetch_user_email", boom)
    res = perform_send(**_kwargs())
    assert res == {"ok": True}


def test_perform_send_error_delegates_to_classifier(monkeypatch):
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")
    monkeypatch.setattr(st, "get_gmail_service", lambda *a, **k: "svc")

    def boom(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(st, "send_email", boom)
    sentinel = {"ok": False, "kind": "error", "error": None, "tb": "TB"}
    monkeypatch.setattr(st, "classify_mail_error", lambda e: sentinel)
    res = perform_send(**_kwargs())
    assert res is sentinel


def test_perform_send_missing_credentials_delegates_to_classifier(monkeypatch):
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")

    def missing(*a, **k):
        raise FileNotFoundError("credentials.json")

    monkeypatch.setattr(st, "get_gmail_service", missing)
    sentinel = {"ok": False, "kind": "filenotfound", "error": None, "tb": None}
    monkeypatch.setattr(st, "classify_mail_error", lambda e: sentinel)
    res = perform_send(**_kwargs())
    assert res is sentinel
