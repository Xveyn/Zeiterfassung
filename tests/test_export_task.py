"""perform_export_pdf: Tk-freier Worker-Kern des Export-Dialogs (Audit M10)."""

import src.dialogs.export_task as st
from src.dialogs.export_task import perform_export_pdf


def _kwargs(**over):
    base = dict(
        date_from=None, date_to=None, entries={}, name="N",
        categories=None, category_breakdown=False,
    )
    base.update(over)
    return base


def test_perform_export_success_returns_pdf_bytes(monkeypatch):
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")
    res = perform_export_pdf(**_kwargs())
    assert res == {"ok": True, "pdf_bytes": b"PDF"}


def test_perform_export_no_entries_returns_none(monkeypatch):
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: None)
    res = perform_export_pdf(**_kwargs())
    assert res == {"ok": True, "pdf_bytes": None}


def test_perform_export_error_sets_traceback(monkeypatch):
    def boom(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(st, "generate_pdf", boom)
    res = perform_export_pdf(**_kwargs())
    assert res["ok"] is False
    assert "boom" in res["tb"]
