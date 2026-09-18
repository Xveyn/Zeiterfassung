"""classify_mail_error: gemeinsame Fehler-Zuordnung der Mail-Kerne (Audit M10)."""

import src.dialogs.mail_task as mt
from src.dialogs.mail_task import classify_mail_error


def test_classify_filenotfound():
    res = classify_mail_error(FileNotFoundError("credentials.json"))
    assert res["ok"] is False
    assert res["kind"] == "filenotfound"
    assert res["tb"] is None


def test_classify_offline(monkeypatch):
    monkeypatch.setattr(mt, "is_offline_error", lambda e: True)
    try:
        raise OSError("net")
    except Exception as e:
        res = classify_mail_error(e)
    assert res["kind"] == "offline"
    assert res["tb"] is None


def test_classify_generic_error_has_traceback(monkeypatch):
    monkeypatch.setattr(mt, "is_offline_error", lambda e: False)
    try:
        raise ValueError("boom")
    except Exception as e:
        res = classify_mail_error(e)
    assert res["kind"] == "error"
    assert "boom" in res["tb"]


def test_classify_keyring_unavailable_has_no_traceback():
    from src.dialogs.mail_task import classify_mail_error
    from src.oauth_utils import TokenKeyringUnavailable
    try:
        raise TokenKeyringUnavailable()
    except TokenKeyringUnavailable as e:
        res = classify_mail_error(e)
    assert res["kind"] == "keyring" and res["tb"] is None
