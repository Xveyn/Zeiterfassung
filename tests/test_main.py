"""run_calendar_reconcile: orchestriert reservations_sync + Werkstudenten-
Wochenlimit-Check für frisch importierte Reservierungs-Slots (#98).
gcal ist komplett gemockt (kein echtes Netzwerk/OAuth)."""

import sys

from src import main as main_module
from src.main import _ensure_device_id, run_calendar_reconcile
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


# --- _ensure_device_id: hardware-abgeleitet (frozen) vs. Zufalls-UUID -------
# (Repo-/Skript-Modus, Fallback bei nicht lesbarer Hardware-ID)

class TestEnsureDeviceId:
    def test_not_frozen_generates_and_persists_random_uuid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        settings = Settings(str(tmp_path / "settings.json"))

        device_id = _ensure_device_id(settings)

        assert device_id
        assert settings.get("device_id") == device_id

    def test_not_frozen_reuses_persisted_uuid_on_second_call(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        settings = Settings(str(tmp_path / "settings.json"))

        first = _ensure_device_id(settings)
        second = _ensure_device_id(settings)

        assert first == second

    def test_not_frozen_never_calls_derive_device_id(self, tmp_path, monkeypatch):
        # Repo-/Skript-Modus darf NIE die hardware-abgeleitete ID nutzen —
        # sonst hätte eine parallel zu einer echten Installation laufende
        # Dev-Instanz auf demselben Rechner dieselbe device_id.
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        monkeypatch.setattr(main_module, "derive_device_id",
                            lambda: (_ for _ in ()).throw(AssertionError("must not be called")))
        settings = Settings(str(tmp_path / "settings.json"))

        _ensure_device_id(settings)  # darf nicht werfen

    def test_frozen_uses_derived_hardware_id_and_persists_it(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(main_module, "derive_device_id", lambda: "derived-abc123")
        settings = Settings(str(tmp_path / "settings.json"))

        device_id = _ensure_device_id(settings)

        assert device_id == "derived-abc123"
        assert settings.get("device_id") == "derived-abc123"

    def test_frozen_falls_back_to_random_uuid_when_hardware_id_unavailable(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(main_module, "derive_device_id", lambda: None)
        settings = Settings(str(tmp_path / "settings.json"))

        device_id = _ensure_device_id(settings)

        assert device_id
        assert settings.get("device_id") == device_id

    def test_frozen_overwrites_stale_persisted_id_once_derivable_again(
            self, tmp_path, monkeypatch):
        # Simuliert: voriger Start konnte die Hardware-ID nicht lesen (Fallback
        # auf Zufalls-UUID persistiert), dieser Start kann es wieder — die neue,
        # stabile ID muss die veraltete Zufalls-UUID ersetzen, nicht dauerhaft
        # bei ihr bleiben.
        settings = Settings(str(tmp_path / "settings.json"))
        settings.set("device_id", "stale-random-uuid")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(main_module, "derive_device_id", lambda: "derived-abc123")

        device_id = _ensure_device_id(settings)

        assert device_id == "derived-abc123"
        assert settings.get("device_id") == "derived-abc123"
