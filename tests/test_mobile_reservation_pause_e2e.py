"""Ende-zu-Ende (#455): die Pause an Reservierungen über mehrere Abgleiche, neue PWA gegen neuen Desktop.

Beide Seiten sind echt: der Desktop mit `mobile_sync.perform_sync` und einem `ReservationStore`
auf der Platte, das Handy mit der echten PWA-Logik (`Store`, `parseSyncResponse`,
`snapshotReservations`) in einem Node-Prozess (`mobile_session_probe.mjs`). Die Unit-Tests je Seite
prüfen jede mit eigenen Annahmen über die andere; hier läuft die Schleife Handy → Desktop → Handy.
Ohne Node wird übersprungen; die `pwa`-Job-CI hat es."""
import datetime
import json
import pathlib
import shutil
import subprocess
import types

import pytest

from src import mobile_sync, reservations
from src.conflicts_store import ConflictsStore
from src.reservations import ReservationStore
from src.settings import Settings
from src.storage import Storage

PROBE = pathlib.Path(__file__).resolve().parent / "mobile_session_probe.mjs"
TODAY = datetime.date(2026, 10, 8)
DAY = "2026-10-20"
DESKTOP = {"name": "PC", "version": "1.0.0", "platform": "Linux"}
SLOT_STAMP = "2026-10-08T11:00:00Z"
T1, T2, T3 = "2026-10-08T12:00:00Z", "2026-10-08T12:20:00Z", "2026-10-08T12:40:00Z"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node fehlt")


def slot(pause, **extra):
    return {"start": "09:00", "end": "17:00", "kategorie": "P", "gcal_event_id": None,
            "send_reminder_minutes": None, "pause": pause, **extra}


class Phone:
    """Das Handy: ein Node-Prozess mit der echten PWA, gesteuert per Zeilenprotokoll."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(["node", str(PROBE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, bufsize=1)

    def call(self, cmd, **args):
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps({"cmd": cmd, **args}) + "\n")
        self.proc.stdin.flush()
        out = json.loads(self.proc.stdout.readline())
        if "error" in out:
            raise AssertionError(out["error"])
        return out["ok"]

    def close(self) -> None:
        assert self.proc.stdin
        self.proc.stdin.close()
        self.proc.wait(timeout=30)

    def pause(self, date=DAY):
        return [s["pause"] for s in self.call("state")["reservations"][date]["slots"]]


@pytest.fixture
def world(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    settings.device_id_for_sync = "DESK"
    settings.set("reservations_enabled", True)
    store = ReservationStore(str(tmp_path / "reservations.json"))
    store.apply_reconciled({DAY: {"slots": [slot(30)], "modified_at": SLOT_STAMP, "deleted": False}})
    phone = Phone()
    yield types.SimpleNamespace(
        store=store, settings=settings, phone=phone,
        storage=Storage(str(tmp_path / "zeiterfassung.json"), device_id="DESK"),
        conflicts=ConflictsStore(str(tmp_path / "conflicts.json")), base=str(tmp_path))
    phone.close()


def sync(world, now, *, strip=False):
    """Ein Abgleich: Anfrage der PWA → echter Desktop → Antwort in die PWA. `strip` macht den Desktop
    zu einem ohne die Fähigkeit (Antwort ohne `reservation_pause`, Slots ohne `pause`)."""
    world.phone.call("clock", now=now)
    sent = world.phone.call("request")
    body = json.dumps({"protocol": 2, "client_time": now, "last_pull_at": sent["last_pull_at"], "entries": {},
                       **({"reservations": sent["reservations"]} if sent["reservations"] else {})}).encode()
    request = mobile_sync.parse_request(body, now=now, today=TODAY)
    report = mobile_sync.SyncReport()
    response = json.loads(json.dumps(mobile_sync.perform_sync(
        request, device_id="phone-0001", device_name="Pixel", last_pull_at=sent["last_pull_at"],
        categories=["P"], storage=world.storage, settings=world.settings, conflicts_store=world.conflicts,
        base=world.base, now=now, today=TODAY, desktop=DESKTOP, reservation_store=world.store, report=report)))
    if strip:
        response.pop("reservation_pause")
        for entry in response["reservations"].values():
            for s in entry["slots"]:
                s.pop("pause")
    state = world.phone.call("apply", response=response)
    return types.SimpleNamespace(sent=sent, response=response, report=report, state=state)


def store_pause(world, date=DAY):
    return [s["pause"] for s in world.store.get_all_raw()[date]["slots"]]


def response_pause(result, date=DAY):
    return [s["pause"] for s in result.response["reservations"][date]["slots"]]


def test_a_stable_pause_survives_three_syncs_without_churn(world):
    nows = [T1, "2026-10-08T12:10:00Z", T2]
    results = [sync(world, now) for now in nows]

    assert results[0].state["flag"] is True
    for result in results:
        assert store_pause(world) == [30]
        assert response_pause(result) == [30]
        assert result.state["reservations"][DAY]["slots"][0]["pause"] == 30
        assert result.state["dirty_count"] == 0
    assert [r.report.reservations_changed for r in results[1:]] == [False, False]
    assert results[0].sent["reservations"] == {} and results[2].sent["reservations"] == {}
    assert world.phone.call("request")["reservations"] == {}      # und es bleibt dabei


def test_b_pause_changed_on_the_phone_reaches_the_desktop(world):
    sync(world, T1)
    world.phone.call("clock", now="2026-10-08T12:10:00Z")
    changed = world.phone.call("save", date=DAY, slots=[{"start": "09:00", "end": "17:00", "kategorie": "P",
                                                         "pause": 45}])
    assert changed["dirty_count"] == 1

    result = sync(world, T2)

    assert result.sent["reservations"][DAY]["slots"][0]["pause"] == 45       # ging auf den Draht
    assert result.report.reservations_changed is True
    assert store_pause(world) == [45]
    assert response_pause(result) == [45]
    assert result.state["reservations"][DAY]["slots"][0]["pause"] == 45
    assert result.state["dirty_count"] == 0
    assert sync(world, T3).report.reservations_changed is False               # und danach ruhig


def test_c_pause_changed_on_the_desktop_reaches_the_phone(world):
    sync(world, T1)

    world.store.save(DAY, [slot(20)])
    result = sync(world, T2)

    assert result.sent["reservations"] == {}
    assert store_pause(world) == [20]
    assert response_pause(result) == [20]
    assert result.state["reservations"][DAY]["slots"][0]["pause"] == 20
    assert result.state["dirty_count"] == 0


@pytest.mark.parametrize("winner, desktop_stamp, phone_clock, expected", [
    ("phone", "2026-10-08T12:12:00Z", "2026-10-08T12:15:00Z", 45),
    ("desktop", "2026-10-08T12:18:00Z", "2026-10-08T12:15:00Z", 20),
])
def test_d_conflict_the_newer_stamp_wins_and_both_converge(world, monkeypatch, winner, desktop_stamp,
                                                           phone_clock, expected):
    sync(world, T1)
    world.phone.call("clock", now=phone_clock)
    world.phone.call("save", date=DAY, slots=[{"start": "09:00", "end": "17:00", "kategorie": "P", "pause": 45}])
    monkeypatch.setattr(reservations, "utc_now_iso", lambda: desktop_stamp)
    world.store.save(DAY, [slot(20)])

    result = sync(world, T2)

    assert store_pause(world) == [expected]
    assert response_pause(result) == [expected]
    assert result.state["reservations"][DAY]["slots"][0]["pause"] == expected
    assert result.state["dirty_count"] == 0
    # Der unterlegene Wert ist weg; es gibt keinen Konflikteintrag, der ihn aufbewahrt (so festgehalten).
    losing = {45, 20} - {expected}
    assert not losing & set(store_pause(world)) and not losing & set(world.phone.pause())
    assert sync(world, T3).report.reservations_changed is False


def test_e_without_the_capability_the_pause_stays_local_and_off_the_wire(world):
    sync(world, T1)
    result = sync(world, "2026-10-08T12:10:00Z", strip=True)
    assert result.state["flag"] is False

    world.phone.call("clock", now="2026-10-08T12:15:00Z")
    state = world.phone.call("save", date=DAY, slots=[{"start": "09:00", "end": "17:00", "kategorie": "P",
                                                       "pause": 45}])
    request = world.phone.call("request")

    assert state["reservations"][DAY]["slots"][0]["pause"] == 45              # lokal gespeichert
    assert state["dirty_count"] == 1
    assert list(request["reservations"][DAY]["slots"][0]) == ["start", "end", "kategorie"]   # nicht gesendet
    assert store_pause(world) == [30]                                         # der Desktop sah sie nie
