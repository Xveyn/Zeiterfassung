"""Worker-Kerne des Google-Tabs (R4, Stufe 2), headless.

Der Tab selbst ist Tk-gebunden und bleibt per M16 untestbar — diese drei
Kerne sind es seit der Extraktion nicht mehr. Geprüft wird der Vertrag, auf
den sich `runner.run(fn, on_done)` verlässt: **wirft nie**, liefert immer ein
Result-Dict, persistiert im Worker (überlebt einen Dialog-Close) und reicht
die richtigen Pfade/Flags an die Google-Wrapper durch.
"""

import os

import pytest

import src.dialogs.settings_dialog.google_tab_task as gtt
from src.dialogs.settings_dialog.google_tab_task import (
    fetch_sender_email, load_calendars, open_calendar_service,
    open_drive_service, reconnect_drive,
)


class _FakeSettings:
    def __init__(self, **values):
        self._data = {"sync_enabled": False, "gcal_enabled": False}
        self._data.update(values)
        self.sets = []

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self.sets.append((key, value))
        self._data[key] = value


class _Boom(Exception):
    """Eigener Typ, damit die Tests die Identität der Exception prüfen können."""


# --- fetch_sender_email ---------------------------------------------------

def test_fetch_sender_email_persists_and_returns(monkeypatch, tmp_path):
    settings = _FakeSettings(sync_enabled=True, gcal_enabled=True)
    monkeypatch.setattr(gtt, "get_gmail_service", lambda *a, **k: object())
    monkeypatch.setattr(gtt, "fetch_user_email", lambda *a, **k: "a@b.de")

    res = fetch_sender_email(settings, str(tmp_path))

    assert res == {"ok": True, "email": "a@b.de"}
    assert settings.sets == [("sender_email", "a@b.de")], \
        "die Adresse muss im Worker persistiert werden (überlebt Dialog-Close)"


def test_fetch_sender_email_without_address_does_not_persist(monkeypatch, tmp_path):
    """Fehlender userinfo-Scope liefert None — kein Fehler, aber auch kein Cache."""
    settings = _FakeSettings()
    monkeypatch.setattr(gtt, "get_gmail_service", lambda *a, **k: object())
    monkeypatch.setattr(gtt, "fetch_user_email", lambda *a, **k: None)

    res = fetch_sender_email(settings, str(tmp_path))

    assert res == {"ok": True, "email": None}
    assert settings.sets == []


def test_fetch_sender_email_passes_paths_and_flags(monkeypatch, tmp_path):
    settings = _FakeSettings(sync_enabled=True, gcal_enabled=False)
    seen = {}

    def fake_service(creds, token, *, sync_enabled, gcal_enabled):
        seen["service"] = (creds, token, sync_enabled, gcal_enabled)
        return object()

    def fake_email(token, *, sync_enabled, gcal_enabled):
        seen["email"] = (token, sync_enabled, gcal_enabled)
        return "x@y.z"

    monkeypatch.setattr(gtt, "get_gmail_service", fake_service)
    monkeypatch.setattr(gtt, "fetch_user_email", fake_email)

    fetch_sender_email(settings, str(tmp_path))

    creds, token, sync, gcal_flag = seen["service"]
    assert creds == os.path.join(str(tmp_path), "credentials.json")
    assert token == os.path.join(str(tmp_path), "token.json")
    assert (sync, gcal_flag) == (True, False)
    assert seen["email"] == (token, True, False)


@pytest.mark.parametrize("failing", ["get_gmail_service", "fetch_user_email"])
def test_fetch_sender_email_never_raises(monkeypatch, tmp_path, failing):
    """Egal welcher der beiden Schritte kippt: Dict statt Exception."""
    settings = _FakeSettings()
    boom = _Boom("kaputt")

    def raiser(*a, **k):
        raise boom

    monkeypatch.setattr(gtt, "get_gmail_service", lambda *a, **k: object())
    monkeypatch.setattr(gtt, "fetch_user_email", lambda *a, **k: "a@b.de")
    monkeypatch.setattr(gtt, failing, raiser)

    res = fetch_sender_email(settings, str(tmp_path))

    assert res["ok"] is False
    assert res["error"] is boom, "das Exception-OBJEKT wird durchgereicht, nicht str(e)"
    assert "_Boom" in res["tb"]
    assert settings.sets == [], "bei Fehler darf nichts persistiert werden"


# --- load_calendars -------------------------------------------------------

def test_load_calendars_returns_items(monkeypatch, tmp_path):
    settings = _FakeSettings(sync_enabled=True)
    items = [{"summary": "Privat", "id": "cal-1"}]
    seen = {}

    def fake_service(creds, token, *, sync_enabled):
        seen["args"] = (creds, token, sync_enabled)
        return "SERVICE"

    monkeypatch.setattr(gtt.gcal, "get_calendar_service", fake_service)
    monkeypatch.setattr(gtt.gcal, "list_calendars", lambda service: items)

    res = load_calendars(settings, str(tmp_path))

    assert res == {"ok": True, "items": items}
    assert seen["args"] == (os.path.join(str(tmp_path), "credentials.json"),
                            os.path.join(str(tmp_path), "token.json"), True)


def test_load_calendars_never_raises(monkeypatch, tmp_path):
    boom = _Boom("kein Netz")
    monkeypatch.setattr(gtt.gcal, "get_calendar_service",
                        lambda *a, **k: (_ for _ in ()).throw(boom))

    res = load_calendars(_FakeSettings(), str(tmp_path))

    assert res["ok"] is False and res["error"] is boom and res["tb"]


def test_load_calendars_survives_failing_list_call(monkeypatch, tmp_path):
    """Auch der zweite Schritt (list_calendars) ist ein Netzaufruf."""
    boom = _Boom("API 500")
    monkeypatch.setattr(gtt.gcal, "get_calendar_service", lambda *a, **k: "SERVICE")
    monkeypatch.setattr(gtt.gcal, "list_calendars",
                        lambda service: (_ for _ in ()).throw(boom))

    res = load_calendars(_FakeSettings(), str(tmp_path))

    assert res["ok"] is False and res["error"] is boom


# --- reconnect_drive ------------------------------------------------------

def test_reconnect_drive_ok(monkeypatch, tmp_path):
    settings = _FakeSettings(gcal_enabled=True)
    seen = {}

    def fake_reconnect(creds, token, *, gcal_enabled):
        seen["args"] = (creds, token, gcal_enabled)

    monkeypatch.setattr(gtt.drive, "reconnect", fake_reconnect)

    assert reconnect_drive(settings, str(tmp_path)) == {"ok": True}
    assert seen["args"] == (os.path.join(str(tmp_path), "credentials.json"),
                            os.path.join(str(tmp_path), "token.json"), True)


def test_reconnect_drive_never_raises(monkeypatch, tmp_path):
    boom = _Boom("Consent abgebrochen")
    monkeypatch.setattr(gtt.drive, "reconnect",
                        lambda *a, **k: (_ for _ in ()).throw(boom))

    res = reconnect_drive(_FakeSettings(), str(tmp_path))

    assert res["ok"] is False and res["error"] is boom and res["tb"]


# --- service_fn-Einstiege für build_oauth_enable_task ---------------------

def test_open_drive_service_passes_args(monkeypatch, tmp_path):
    settings = _FakeSettings(gcal_enabled=True)
    seen = {}
    monkeypatch.setattr(gtt.drive, "get_drive_service",
                        lambda creds, token, *, gcal_enabled:
                        seen.update(args=(creds, token, gcal_enabled)))

    open_drive_service(settings, str(tmp_path))

    assert seen["args"] == (os.path.join(str(tmp_path), "credentials.json"),
                            os.path.join(str(tmp_path), "token.json"), True)


def test_open_calendar_service_passes_args(monkeypatch, tmp_path):
    settings = _FakeSettings(sync_enabled=True)
    seen = {}
    monkeypatch.setattr(gtt.gcal, "get_calendar_service",
                        lambda creds, token, *, sync_enabled:
                        seen.update(args=(creds, token, sync_enabled)))

    open_calendar_service(settings, str(tmp_path))

    assert seen["args"] == (os.path.join(str(tmp_path), "credentials.json"),
                            os.path.join(str(tmp_path), "token.json"), True)


@pytest.mark.parametrize("fn,module,attr", [
    (open_drive_service, "drive", "get_drive_service"),
    (open_calendar_service, "gcal", "get_calendar_service"),
])
def test_service_fns_propagate_errors(monkeypatch, tmp_path, fn, module, attr):
    """Anders als die drei Kerne WERFEN diese beiden — build_oauth_enable_task
    fängt selbst und braucht die Exception, um den Toggle zurückzudrehen."""
    boom = _Boom("Consent verweigert")
    monkeypatch.setattr(getattr(gtt, module), attr,
                        lambda *a, **k: (_ for _ in ()).throw(boom))

    with pytest.raises(_Boom):
        fn(_FakeSettings(), str(tmp_path))
