"""Multi-Kanal-Dispatch: Mail und Webhooks feuern unabhängig voneinander."""

import datetime

import src.dialogs.send_task as st
from src.dialogs.send_task import (
    format_result_summary, needs_json, needs_pdf, perform_send,
)
from tests.conftest import ist_slot as _slot


class _FakeSettings:
    def __init__(self):
        self._d = {"sender_email": ""}
        self.sets = []

    def get(self, k):
        return self._d.get(k)

    def set(self, k, v):
        self.sets.append((k, v))
        self._d[k] = v


def _hook(name="Server", json_=True, pdf=False):
    return {
        "record": {"id": name, "name": name, "url": "https://x.example/h",
                   "enabled": True, "payload": {"json": json_, "pdf": pdf},
                   "auth": {"mode": "none"}},
        "json": json_, "pdf": pdf,
    }


def _mail():
    return {
        "credentials_path": "c.json", "token_path": "t.json",
        "recipient": "to@example.com", "subject": "Subj", "html": "<p>x</p>",
        "sync_enabled": False, "gcal_enabled": False,
    }


def _kwargs(**over):
    base = dict(
        date_from=datetime.date(2026, 7, 1), date_to=datetime.date(2026, 7, 31),
        entries={"2026-07-01": {"slots": [_slot("08:00", "16:00")]}},
        name="Sven", categories=None, category_breakdown=False,
        send_mail=True, mail=_mail(), webhooks=[],
        pdf_filename="r.pdf", settings=_FakeSettings(),
    )
    base.update(over)
    return base


def _patch_mail_ok(monkeypatch, calls=None):
    monkeypatch.setattr(st, "generate_pdf",
                        lambda *a, **k: (calls.append("pdf") if calls is not None else None) or b"PDF")
    monkeypatch.setattr(st, "get_gmail_service", lambda *a, **k: "svc")
    monkeypatch.setattr(st, "send_email", lambda *a, **k: "mid")
    monkeypatch.setattr(st, "fetch_user_email", lambda *a, **k: "me@example.com")


def test_mail_only_matches_previous_behaviour(monkeypatch):
    _patch_mail_ok(monkeypatch)
    res = perform_send(**_kwargs())
    assert res["results"] == [
        {"channel": "mail", "name": "to@example.com", "ok": True}]


def test_webhook_result_is_reported_per_channel(monkeypatch):
    _patch_mail_ok(monkeypatch)
    monkeypatch.setattr(st.webhook, "deliver",
                        lambda *a, **k: {"ok": True, "status": 200})
    res = perform_send(**_kwargs(webhooks=[_hook("Buchhaltung")]))
    assert [r["name"] for r in res["results"]] == ["to@example.com", "Buchhaltung"]
    assert all(r["ok"] for r in res["results"])


def test_failing_webhook_does_not_stop_mail(monkeypatch):
    _patch_mail_ok(monkeypatch)
    monkeypatch.setattr(
        st.webhook, "deliver",
        lambda *a, **k: {"ok": False, "kind": "server", "detail": "HTTP 500",
                         "error": None, "tb": None})
    res = perform_send(**_kwargs(webhooks=[_hook("Buchhaltung")]))
    mail_res, hook_res = res["results"]
    assert mail_res["ok"] is True
    assert hook_res["ok"] is False
    assert hook_res["kind"] == "server"


def test_failing_mail_does_not_stop_webhooks(monkeypatch):
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")

    def boom(*a, **k):
        raise RuntimeError("gmail kaputt")

    monkeypatch.setattr(st, "get_gmail_service", boom)
    monkeypatch.setattr(st.webhook, "deliver",
                        lambda *a, **k: {"ok": True, "status": 200})
    res = perform_send(**_kwargs(webhooks=[_hook("Buchhaltung")]))
    assert res["results"][0]["ok"] is False
    assert res["results"][1]["ok"] is True


def test_pdf_is_generated_once_for_all_channels(monkeypatch):
    calls = []
    _patch_mail_ok(monkeypatch, calls)
    monkeypatch.setattr(st.webhook, "deliver",
                        lambda *a, **k: {"ok": True, "status": 200})
    perform_send(**_kwargs(send_mail=False, mail=None,
                           webhooks=[_hook("A", json_=False, pdf=True),
                                     _hook("B", json_=False, pdf=True)]))
    assert calls.count("pdf") == 1


def test_broken_payload_build_never_escapes(monkeypatch):
    """Entkäme die Exception, riefe BackgroundTaskRunner.run `on_done` nie und
    der Sende-Dialog bliebe dauerhaft auf „Sende…" stehen — während die Mail
    längst raus ist."""
    _patch_mail_ok(monkeypatch)

    def boom(*a, **k):
        raise KeyError("slots")

    monkeypatch.setattr(st.webhook, "build_json_payload", boom)
    monkeypatch.setattr(st.webhook, "deliver",
                        lambda *a, **k: {"ok": True, "status": 200})
    res = perform_send(**_kwargs(webhooks=[_hook("A", json_=True, pdf=False)]))
    mail_res, hook_res = res["results"]
    assert mail_res["ok"] is True
    assert hook_res["ok"] is False
    assert hook_res["kind"] == "error"


def test_broken_payload_build_leaves_pdf_only_webhooks_alone(monkeypatch):
    def boom(*a, **k):
        raise KeyError("slots")

    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")
    monkeypatch.setattr(st.webhook, "build_json_payload", boom)
    monkeypatch.setattr(st.webhook, "deliver",
                        lambda *a, **k: {"ok": True, "status": 200})
    res = perform_send(**_kwargs(
        send_mail=False, mail=None,
        webhooks=[_hook("Json", json_=True, pdf=False),
                  _hook("Pdf", json_=False, pdf=True)]))
    by_name = {r["name"]: r for r in res["results"]}
    assert by_name["Json"]["ok"] is False
    assert by_name["Pdf"]["ok"] is True


def test_pdf_is_not_generated_when_nobody_wants_it(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("generate_pdf darf nicht laufen")

    monkeypatch.setattr(st, "generate_pdf", boom)
    monkeypatch.setattr(st.webhook, "deliver",
                        lambda *a, **k: {"ok": True, "status": 200})
    res = perform_send(**_kwargs(send_mail=False, mail=None,
                                 webhooks=[_hook("A", json_=True, pdf=False)]))
    assert res["results"][0]["ok"] is True


def test_unexpected_webhook_error_never_escapes(monkeypatch):
    _patch_mail_ok(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(st.webhook, "deliver", boom)
    res = perform_send(**_kwargs(webhooks=[_hook("A")]))
    assert res["results"][1]["ok"] is False
    assert res["results"][1]["kind"] == "error"


def test_needs_pdf_and_needs_json():
    assert needs_pdf(True, []) is True
    assert needs_pdf(False, [_hook("A", json_=True, pdf=False)]) is False
    assert needs_pdf(False, [_hook("A", json_=False, pdf=True)]) is True
    assert needs_json([_hook("A", json_=True, pdf=False)]) is True
    assert needs_json([_hook("A", json_=False, pdf=True)]) is False


def test_summary_lists_every_channel():
    text = format_result_summary([
        {"channel": "mail", "name": "to@example.com", "ok": True},
        {"channel": "webhook", "name": "Buchhaltung", "ok": False,
         "kind": "server", "detail": "HTTP 500"},
    ])
    assert "to@example.com" in text
    assert "Buchhaltung" in text
    assert "HTTP 500" in text
    assert "✓" in text and "✗" in text


def test_perform_send_survives_send_mail_without_mail_data(monkeypatch):
    """Der „wirft nie"-Vertrag gilt auch für diese Fehlbedienung: `mail` ist
    als `dict | None` deklariert, also unabhängig von `send_mail` setzbar.
    Entkäme hier ein TypeError, riefe BackgroundTaskRunner.run `on_done` nie
    und der Sende-Dialog bliebe auf „Sende…" stehen."""
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")
    monkeypatch.setattr(st.webhook, "deliver",
                        lambda *a, **k: {"ok": True, "status": 200})
    res = perform_send(**_kwargs(send_mail=True, mail=None,
                                 webhooks=[_hook("A")]))
    assert [r["name"] for r in res["results"]] == ["A"]
