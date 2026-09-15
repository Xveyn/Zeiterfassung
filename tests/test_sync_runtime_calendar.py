"""Kalender-Flows in `sync_runtime`: der Urlaubs-Push als Anhang von
`run_calendar_reconcile` und sein Gegenstück `run_vacation_purge`.

Die Reservierungs-Seite von `run_calendar_reconcile` (Werkstudenten-Limit)
testet `test_main.py`. Google ist über `fake_calendar` ersetzt, alles
darüber — `reservations_sync`, `vacations_sync`, Stores, `sync_history` —
läuft echt.
"""

import logging

import pytest

from src import gcal, sync_history
from src.reservations import ReservationStore
from src.settings import Settings
from src.storage import Storage
from src.sync_runtime import run_calendar_reconcile, run_vacation_purge
from src.vacations import VacationStore

_JULY_DAYS = {"2026-07-01": 480, "2026-07-02": 480, "2026-07-03": 480}


def _settings(tmp_path, **overrides):
    settings = Settings(str(tmp_path / "settings.json"))
    settings.set_many({"gcal_enabled": True, "gcal_calendar_id": "cal-1",
                       "vacation_gcal_enabled": True, **overrides})
    return settings


def _vacation_store(tmp_path, event_id=None):
    """Ein Store mit einer Periode 01.–03.07.2026. Liefert (store, period_id)."""
    store = VacationStore(str(tmp_path / "vacations.json"))
    pid = store.save(None, "Sommer", "2026-07-01", "2026-07-03", dict(_JULY_DAYS))
    if event_id is not None:
        raw = store.get_all_raw()
        raw[pid]["gcal_event_id"] = event_id
        store.apply_reconciled(raw)
    return store, pid


def _reconcile(tmp_path, settings, vacation_store):
    return run_calendar_reconcile(
        ReservationStore(str(tmp_path / "reservations.json")), settings,
        str(tmp_path), Storage(str(tmp_path / "entries.json")),
        vacation_store=vacation_store)


# ------------------------------------------- run_calendar_reconcile: Urlaub

def test_vacation_push_creates_events_when_enabled(fake_calendar, tmp_path):
    store, pid = _vacation_store(tmp_path)
    modified_at = store.get_all_raw()[pid]["modified_at"]

    result = _reconcile(tmp_path, _settings(tmp_path), store)

    assert result["ok"] is True
    assert fake_calendar.created_vacations == [
        (pid, "2026-07-01", "2026-07-03", modified_at)]
    assert store.get_all_raw()[pid]["gcal_event_id"] == "evt-new-1"


@pytest.mark.parametrize("switch_on, with_store", [
    pytest.param(False, True, id="schalter-aus"),
    pytest.param(True, False, id="kein-store"),
])
def test_vacation_push_is_skipped(fake_calendar, tmp_path, switch_on, with_store):
    """Der Push ist ein Zusatz mit eigenem Schalter: ohne ihn (oder ohne
    Store) fragt der Abgleich den Kalender nicht einmal nach Urlaubs-Events."""
    store = _vacation_store(tmp_path)[0] if with_store else None
    settings = _settings(tmp_path, vacation_gcal_enabled=switch_on)

    result = _reconcile(tmp_path, settings, store)

    assert result["ok"] is True
    assert "list_app_vacations" not in fake_calendar.calls
    assert fake_calendar.created_vacations == []


def test_vacation_push_failure_does_not_fail_the_reservation_reconcile(
        fake_calendar, tmp_path, caplog):
    """Der Urlaubs-Push hat einen eigenen Fehlerraum. Risse er den
    gelungenen Reservierungs-Abgleich mit, gingen zwei Dinge verloren:

    - der `sync_history`-Marker — er vetot den Startup-Sweep gegen einen
      settings.json-Reset (M4), ohne ihn drohen wiederauferstehende
      Reservierungs-Tombstones;
    - die Werkstudenten-Warnungen (#98) für frisch importierte Slots.
    """
    settings = _settings(
        tmp_path,
        werkstudent_limit_enabled=True,
        werkstudent_limit_start="2026-04-01",
        werkstudent_limit_end="2026-07-15",
        werkstudent_limit_max_hours=10.0,
    )
    storage = Storage(str(tmp_path / "entries.json"))
    # KW19/2026 hat bereits 11 h Ist-Zeit (> Limit 10 h); der importierte
    # Reservierungs-Slot am 06.05. liegt in derselben Woche.
    storage.save("2026-05-04",
                 [{"start": "06:00", "end": "17:00", "pause": 0, "kategorie": ""}])
    fake_calendar.reservation_events = [
        {"date": "2026-05-06", "start": "09:00", "end": "10:00", "kategorie": "",
         "modified_at": "2026-05-01T00:00:00Z", "event_id": "evt-1"}]
    fake_calendar.raise_on("list_app_vacations", RuntimeError("Calendar API 503"))
    store = _vacation_store(tmp_path)[0]
    assert not sync_history.ever_reconciled(str(tmp_path))

    with caplog.at_level(logging.ERROR, logger="src.sync_runtime"):
        result = run_calendar_reconcile(
            ReservationStore(str(tmp_path / "reservations.json")), settings,
            str(tmp_path), storage, vacation_store=store)

    assert result["ok"] is True
    assert [w["iso_week"] for w in result["limit_warnings"]] == [19]
    assert sync_history.ever_reconciled(str(tmp_path)) is True
    # Nicht-fatal heißt nicht spurlos (--noconsole schluckt stderr).
    assert any(r.exc_info and "Calendar API 503" in str(r.exc_info[1])
               for r in caplog.records)


def test_startup_reconcile_with_revoked_token_reports_auth_instead_of_opening_the_browser(
        tmp_path, monkeypatch):
    """Xveyn#129, im Log belegt: seit dem Widerruf öffnete JEDER App-Start
    ~100 ms nach dem gescheiterten Pull den Google-Consent im Browser. Der
    Kalender-Abgleich rief den Builder ohne `interactive` und erbte den Flow;
    `run_local_server` wartete dann unbegrenzt, der Abgleich kam nie zurück.

    Hier läuft der echte Builder — ersetzt sind nur Token, Flow und build."""
    from src.mail import get_scopes
    from src.sync_orchestrator import classify_sync_error
    from tests.conftest import (
        fake_google_build, forbid_consent_flow, install_existing_token,
        revoked_google_creds,
    )

    install_existing_token(monkeypatch, tmp_path, revoked_google_creds(),
                           get_scopes(True, gcal_enabled=True))
    forbid_consent_flow(monkeypatch)
    fake_google_build(monkeypatch)

    result = _reconcile(tmp_path, _settings(tmp_path, sync_enabled=True), None)

    assert result["ok"] is False
    assert classify_sync_error(result["error"]) == "auth"


# ----------------------------------------------------------- run_vacation_purge

@pytest.mark.parametrize("overrides, with_store", [
    pytest.param({"gcal_enabled": False}, True, id="kalender-aus"),
    pytest.param({"gcal_calendar_id": ""}, True, id="kein-kalender"),
    pytest.param({}, False, id="kein-store"),
])
def test_purge_without_usable_calendar_is_a_silent_success(
        fake_calendar, tmp_path, overrides, with_store):
    """Ohne nutzbaren Kalender kann nie etwas gepusht worden sein — also kein
    Fehler, und vor allem kein Service-Aufbau, der einen Consent auslösen
    könnte."""
    store = _vacation_store(tmp_path, event_id="evt-1")[0] if with_store else None
    fake_calendar.raise_on("get_calendar_service",
                           AssertionError("Service ohne nutzbaren Kalender gebaut"))

    result = run_vacation_purge(_settings(tmp_path, **overrides), str(tmp_path), store)

    assert result == {"ok": True, "error": "", "tb": ""}
    assert fake_calendar.calls == []


def test_purge_deletes_events_and_clears_the_local_ids(fake_calendar, tmp_path):
    store, pid = _vacation_store(tmp_path, event_id="evt-1")
    fake_calendar.vacation_events = [
        {"period_id": pid, "event_id": "evt-1", "modified_at": "",
         "from": "2026-07-01", "to": "2026-07-03"}]

    result = run_vacation_purge(_settings(tmp_path), str(tmp_path), store)

    assert result == {"ok": True, "error": "", "tb": ""}
    assert fake_calendar.deleted == ["evt-1"]
    assert store.get_all_raw()[pid]["gcal_event_id"] is None


def test_purge_failure_is_reported_not_raised(fake_calendar, tmp_path):
    """Der Aufrufer (Urlaubs-Dialog) wertet ein Result-Dict aus. Die lokalen
    Event-IDs bleiben dabei stehen: sie sind der einzige Hinweis darauf, was
    im Kalender noch liegt, und ein erneuter Versuch braucht sie."""
    store, pid = _vacation_store(tmp_path, event_id="evt-1")
    fake_calendar.raise_on("get_calendar_service",
                           gcal.CalendarAuthError("Kein gültiger Google-Token"))

    result = run_vacation_purge(_settings(tmp_path), str(tmp_path), store)

    assert result["ok"] is False
    assert "Kein gültiger Google-Token" in result["error"]
    assert "CalendarAuthError" in result["tb"]
    assert store.get_all_raw()[pid]["gcal_event_id"] == "evt-1"
