"""Erfolgs-/Ergebniszeilen der Worker-Kerne für Versand, Teilen, Export (Xveyn#401).

Nur Kanal, Zählwerte, Dauer — nie Empfänger oder Kontonamen."""
import logging

import src.dialogs.export_task as et
import src.dialogs.send_task as st
import src.dialogs.share_task as sh
from src.dialogs.send_task import perform_send, summarize_results
from tests.test_send_task import _FakeSettings, _kwargs, _patch_happy


def _lines(caplog, name):
    return [r for r in caplog.records if r.name == name]


def test_summarize_results_counts_per_channel_and_kinds():
    results = [
        {"channel": "mail", "ok": True, "name": "me@example.com"},
        {"channel": "smtp", "ok": True, "name": "Privat (a@example.com)"},
        {"channel": "smtp", "ok": False, "kind": "tls", "name": "Arbeit (b@example.com)"},
        {"channel": "webhook", "ok": False, "kind": "auth", "name": "Hook"},
        {"channel": "webhook", "ok": False, "kind": "auth", "name": "Hook2"},
    ]
    text = summarize_results(results)
    assert text == ("mail 1/1 ok; smtp 1/2 ok (Fehler: tls); "
                    "webhook 0/2 ok (Fehler: auth)")
    for secret in ("example.com", "Privat", "Arbeit", "Hook"):
        assert secret not in text


def test_summarize_results_without_channels():
    assert summarize_results([]) == "kein Kanal gewählt"


def test_perform_send_success_logs_one_info_summary(monkeypatch, caplog):
    _patch_happy(monkeypatch)
    with caplog.at_level(logging.DEBUG, logger="src.dialogs.send_task"):
        res = perform_send(**_kwargs(settings=_FakeSettings()))
    assert res["results"][0]["ok"] is True
    recs = _lines(caplog, "src.dialogs.send_task")
    assert len(recs) == 1
    assert recs[0].levelno == logging.INFO
    assert recs[0].getMessage().startswith("Versand: mail 1/1 ok in ")
    assert "to@example.com" not in recs[0].getMessage()


def test_perform_send_failure_logs_warning_summary(monkeypatch, caplog):
    _patch_happy(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("kaputt")
    monkeypatch.setattr(st, "send_email", boom)
    with caplog.at_level(logging.INFO, logger="src.dialogs.send_task"):
        res = perform_send(**_kwargs(settings=_FakeSettings()))
    assert res["results"][0]["ok"] is False
    summary = [r for r in _lines(caplog, "src.dialogs.send_task")
               if r.getMessage().startswith("Versand:")]
    assert len(summary) == 1
    assert summary[0].levelno == logging.WARNING
    assert "mail 0/1 ok (Fehler: " in summary[0].getMessage()


def test_share_success_logs_way_but_not_recipient(monkeypatch, caplog):
    monkeypatch.setattr(sh, "get_gmail_service", lambda *a, **k: "svc")
    monkeypatch.setattr(sh, "send_email", lambda *a, **k: "mid")

    class S:
        def set(self, *a):
            pass
    with caplog.at_level(logging.INFO, logger="src.dialogs.share_task"):
        res = sh.perform_share(
            payload=b"{}", filename="s.json", credentials_path="c", token_path="t",
            recipient="to@example.com", subject="S", html="<p/>",
            sync_enabled=False, gcal_enabled=False, save_default=False, settings=S())
    assert res["ok"] is True
    msgs = [r.getMessage() for r in _lines(caplog, "src.dialogs.share_task")]
    assert msgs == ["Teilen ok (über Gmail)"]


def test_export_logs_size_and_duration(monkeypatch, caplog):
    monkeypatch.setattr(et, "generate_pdf", lambda *a, **k: b"x" * 4096)
    with caplog.at_level(logging.INFO, logger="src.dialogs.export_task"):
        res = et.perform_export_pdf(
            date_from=None, date_to=None, entries={}, name="N",
            categories=None, category_breakdown=False)
    assert res["ok"] is True
    msgs = [r.getMessage() for r in _lines(caplog, "src.dialogs.export_task")]
    assert len(msgs) == 1 and msgs[0].startswith("PDF-Export erzeugt (4 KB) in ")


def test_export_without_entries_logs_nothing(monkeypatch, caplog):
    monkeypatch.setattr(et, "generate_pdf", lambda *a, **k: None)
    with caplog.at_level(logging.INFO, logger="src.dialogs.export_task"):
        res = et.perform_export_pdf(
            date_from=None, date_to=None, entries={}, name="N",
            categories=None, category_breakdown=False)
    assert res["ok"] is True and res["pdf_bytes"] is None
    assert _lines(caplog, "src.dialogs.export_task") == []
