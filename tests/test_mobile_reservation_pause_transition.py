"""Übergang (#455): eine alte Handy-Version gegen den neuen Desktop, über mehrere Abgleiche.

Die alte PWA kennt `pause` an Reservierungen nicht: ihr `parseReservations` projiziert jede
Antwort-Reservierung auf `{start, end, kategorie}`, und genau diese drei Felder schickt sie zurück.
Der Desktop darf seine Pause dabei nicht verlieren, solange der Slot derselbe bleibt."""
import datetime
import json
import types

import pytest

from src import mobile_sync
from src.conflicts_store import ConflictsStore
from src.reservations import ReservationStore
from src.settings import Settings
from src.storage import Storage

NOW = "2026-10-08T12:00:00Z"
TODAY = datetime.date(2026, 10, 8)
DAY = "2026-10-20"
DESKTOP = {"name": "PC", "version": "1.0.0", "platform": "Linux"}
STAMP = "2026-10-08T11:00:00Z"


class OldPhone:
    """Arbeitet wie die alte PWA: behält je Tag nur `{start, end, kategorie}` und schickt alle Tage zurück."""

    def __init__(self) -> None:
        self.days: dict[str, dict] = {}
        self.pull = ""

    def learn(self, response: dict) -> None:
        for date, entry in response["reservations"].items():
            self.days[date] = {
                "slots": [{k: s[k] for k in ("start", "end", "kategorie")} for s in entry["slots"]],
                "modified_at": entry["modified_at"], "deleted": entry["deleted"]}

    def edit(self, date: str, stamp: str, **fields) -> None:
        day = json.loads(json.dumps(self.days.get(date, {"slots": [{"start": "09:00", "end": "10:00",
                                                                     "kategorie": "P"}],
                                                          "deleted": False})))
        day["slots"][0].update(fields)
        day["modified_at"] = stamp
        self.days[date] = day


@pytest.fixture
def env(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    settings.device_id_for_sync = "DESK"
    settings.set("reservations_enabled", True)
    store = ReservationStore(str(tmp_path / "reservations.json"))
    store.apply_reconciled({DAY: {"slots": [{"start": "09:00", "end": "10:00", "kategorie": "P",
                                             "gcal_event_id": None, "send_reminder_minutes": None,
                                             "pause": 30}],
                                  "modified_at": STAMP, "deleted": False}})
    return types.SimpleNamespace(
        store=store, settings=settings, calendar_calls=[],
        storage=Storage(str(tmp_path / "zeiterfassung.json"), device_id="DESK"),
        conflicts=ConflictsStore(str(tmp_path / "conflicts.json")), base=str(tmp_path))


def sync(env, phone: OldPhone, now: str = NOW, last_pull_at: str = "") -> tuple[dict, mobile_sync.SyncReport]:
    body = json.dumps({"protocol": 2, "client_time": now, "last_pull_at": last_pull_at, "entries": {},
                       "reservations": phone.days}).encode()
    request = mobile_sync.parse_request(body, now=now, today=TODAY)
    report = mobile_sync.SyncReport()
    response = mobile_sync.perform_sync(
        request, device_id="phone-0001", device_name="Pixel", last_pull_at=last_pull_at, categories=["P"],
        storage=env.storage, settings=env.settings, conflicts_store=env.conflicts, base=env.base,
        now=now, today=TODAY, desktop=DESKTOP, reservation_store=env.store, report=report)
    if report.reservations_changed:   # so stößt die Route den Kalender-Abgleich an
        env.calendar_calls.append(now)
    response = json.loads(json.dumps(response))
    phone.learn(response)
    return response, report


def store_pauses(env) -> list[int]:
    return [s["pause"] for s in env.store.get_all_raw()[DAY]["slots"]]


def response_pauses(response) -> list[int]:
    return [s["pause"] for s in response["reservations"][DAY]["slots"]]


def test_old_phone_three_syncs_keep_desktop_pause(env):
    phone = OldPhone()
    changed = []
    for _ in range(3):
        response, report = sync(env, phone)
        changed.append(report.reservations_changed)
        assert store_pauses(env) == [30]
        assert response_pauses(response) == [30]
    assert changed[1:] == [False, False]
    assert env.calendar_calls == []   # keine Änderung, kein Kalender-Abgleich
    assert phone.days[DAY]["slots"] == [{"start": "09:00", "end": "10:00", "kategorie": "P"}]


def test_old_phone_resend_with_newer_stamp_keeps_desktop_pause(env):
    """Stempel höher (Berührung, oder `floor` = last_pull_at + 1 s): ohne `inherit_pause` gewänne der Slot
    mit Pause 0 und löschte die Pause."""
    phone = OldPhone()
    pull = ""
    for step, now in enumerate(["2026-10-08T12:00:00Z", "2026-10-08T12:10:00Z", "2026-10-08T12:20:00Z"]):
        if step:   # unverändert, aber neuer Stempel
            phone.days[DAY]["modified_at"] = now
        response, report = sync(env, phone, now, last_pull_at=pull)
        pull = response["server_time"]
        assert store_pauses(env) == [30]
        assert response_pauses(response) == [30]
        if step == 2:
            assert report.reservations_changed is True   # Stempel wandert, Inhalt bleibt
    # identischer Folge-Abgleich: No-op
    _, report = sync(env, phone, "2026-10-08T12:30:00Z", last_pull_at=pull)
    assert store_pauses(env) == [30]


def test_old_phone_edit_category_keeps_pause_edit_time_loses_it(env):
    phone = OldPhone()
    sync(env, phone)

    phone.edit(DAY, "2026-10-08T12:05:00Z", kategorie="Q")
    response, _ = sync(env, phone, "2026-10-08T12:10:00Z")
    assert env.store.get_all_raw()[DAY]["slots"][0]["kategorie"] == "Q"
    assert store_pauses(env) == [30] and response_pauses(response) == [30]

    phone.edit(DAY, "2026-10-08T12:20:00Z", end="11:00")
    response, _ = sync(env, phone, "2026-10-08T12:25:00Z")
    assert env.store.get_all_raw()[DAY]["slots"][0]["end"] == "11:00"
    assert store_pauses(env) == [0] and response_pauses(response) == [0]
    sync(env, phone, "2026-10-08T12:30:00Z")
    assert store_pauses(env) == [0]


def test_old_phone_new_day_gets_zero_pause(env):
    phone = OldPhone()
    sync(env, phone)
    phone.edit("2026-10-21", "2026-10-08T12:05:00Z")

    first, _ = sync(env, phone, "2026-10-08T12:10:00Z")
    second, _ = sync(env, phone, "2026-10-08T12:15:00Z")

    assert [s["pause"] for s in env.store.get_all_raw()["2026-10-21"]["slots"]] == [0]
    assert first["reservations"]["2026-10-21"]["slots"][0]["pause"] == 0
    assert second["reservations"]["2026-10-21"]["slots"][0]["pause"] == 0
    assert store_pauses(env) == [30]


def test_new_desktop_response_carries_flag_and_pause(env):
    phone = OldPhone()

    response, _ = sync(env, phone)

    assert response["reservation_pause"] is True
    assert response_pauses(response) == [30]
    # die alte Projektion ignoriert beides ohne Fehler
    assert phone.days[DAY]["slots"] == [{"start": "09:00", "end": "10:00", "kategorie": "P"}]
