"""run_calendar_reconcile: orchestriert reservations_sync + Werkstudenten-
Wochenlimit-Check für frisch importierte Reservierungs-Slots (#98).
gcal ist komplett gemockt (kein echtes Netzwerk/OAuth)."""

from src.main import run_calendar_reconcile
from src.reservations import ReservationStore
from src.settings import Settings
from src.storage import Storage


def _settings(tmp_path, **overrides):
    s = Settings(str(tmp_path / "settings.json"))
    s.set_many({"gcal_enabled": True, "gcal_calendar_id": "cal-1", **overrides})
    return s


def test_gcal_disabled_is_noop(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))  # gcal_enabled default False
    store = ReservationStore(str(tmp_path / "res.json"))
    storage = Storage(str(tmp_path / "ze.json"))
    result = run_calendar_reconcile(store, settings, str(tmp_path), storage)
    assert result == {"ok": True, "error": "", "tb": "", "limit_warnings": []}


def test_imported_reservation_over_limit_warns(tmp_path, monkeypatch):
    from src import gcal

    settings = _settings(
        tmp_path,
        werkstudent_limit_enabled=True,
        werkstudent_limit_start="2026-04-01",
        werkstudent_limit_end="2026-07-15",
        werkstudent_limit_max_hours=10.0,
    )
    store = ReservationStore(str(tmp_path / "res.json"))
    storage = Storage(str(tmp_path / "ze.json"))
    # KW19/2026 (2026-05-04..10) hat bereits 11h Ist-Zeit erfasst (> Limit 10h).
    storage.save("2026-05-04",
                 [{"start": "06:00", "end": "17:00", "pause": 0, "kategorie": ""}])

    monkeypatch.setattr(gcal, "get_calendar_service", lambda *a, **k: object())
    monkeypatch.setattr(
        gcal, "list_app_events",
        lambda s, c: [{"date": "2026-05-06", "start": "09:00", "end": "10:00",
                       "kategorie": "", "modified_at": "2026-05-01T00:00:00Z",
                       "event_id": "evt-1"}])
    monkeypatch.setattr(gcal, "update_event", lambda *a: None)
    monkeypatch.setattr(gcal, "delete_event", lambda *a: None)
    monkeypatch.setattr(gcal, "create_event", lambda *a: "new-id")

    result = run_calendar_reconcile(store, settings, str(tmp_path), storage)

    assert result["ok"] is True
    assert len(result["limit_warnings"]) == 1
    assert result["limit_warnings"][0]["iso_week"] == 19


def test_imported_reservation_under_limit_no_warning(tmp_path, monkeypatch):
    from src import gcal

    settings = _settings(
        tmp_path,
        werkstudent_limit_enabled=True,
        werkstudent_limit_start="2026-04-01",
        werkstudent_limit_end="2026-07-15",
        werkstudent_limit_max_hours=20.0,
    )
    store = ReservationStore(str(tmp_path / "res.json"))
    storage = Storage(str(tmp_path / "ze.json"))  # keine Ist-Zeit erfasst

    monkeypatch.setattr(gcal, "get_calendar_service", lambda *a, **k: object())
    monkeypatch.setattr(
        gcal, "list_app_events",
        lambda s, c: [{"date": "2026-05-06", "start": "09:00", "end": "10:00",
                       "kategorie": "", "modified_at": "2026-05-01T00:00:00Z",
                       "event_id": "evt-1"}])
    monkeypatch.setattr(gcal, "update_event", lambda *a: None)
    monkeypatch.setattr(gcal, "delete_event", lambda *a: None)
    monkeypatch.setattr(gcal, "create_event", lambda *a: "new-id")

    result = run_calendar_reconcile(store, settings, str(tmp_path), storage)

    assert result["limit_warnings"] == []
