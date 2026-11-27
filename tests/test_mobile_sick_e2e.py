"""Ende-zu-Ende: Krankheitstage über mehrere Abgleiche, echte PWA gegen echten Desktop.

Beide Seiten sind echt: der Desktop mit `mobile_sync.perform_sync`, `SickStore` und `ReservationStore` auf der
Platte, das Handy mit der echten PWA-Logik (`Store`, `parseSyncResponse`, `sickDialogModel`, `blockOf`) in einem
Node-Prozess (`mobile_sick_probe.mjs`). Die Unit-Tests je Seite prüfen jede mit eigenen Annahmen über die andere
(etwa: das Handy sendet nie `minutes`, der Desktop rechnet sie aus der Reservierung); hier läuft die Schleife
Handy → Desktop → Handy. Ein Desktop ohne die Fähigkeit ist der echte Weg ohne `sick_store`.
Ohne Node wird übersprungen; die CI hat es."""
import datetime
import json
import pathlib
import shutil
import subprocess
import types

import pytest

from src import mobile_sync, reservations, sick_days, sick_plan, storage
from src.conflicts_store import ConflictsStore
from src.reservations import ReservationStore
from src.settings import Settings
from src.sick_days import SickStore
from src.storage import Storage
from src.vacations import VacationStore

PROBE = pathlib.Path(__file__).resolve().parent / "mobile_sick_probe.mjs"
TODAY = datetime.date(2026, 10, 8)                   # Donnerstag
THU, FRI, SAT, SUN, MON, TUE = (str(TODAY + datetime.timedelta(days=i)) for i in range(6))
DESKTOP = {"name": "PC", "version": "1.0.0", "platform": "Linux"}
T1, T2, T3, T4, T5 = (f"2026-10-08T12:{minute:02d}:00Z" for minute in (0, 10, 20, 30, 40))

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node fehlt")


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


@pytest.fixture
def world(tmp_path, monkeypatch):
    clock = {"now": "2026-10-08T11:00:00Z"}          # Uhr des Desktops: folgt dem jeweiligen Abgleich
    for module in (sick_days, reservations, storage):
        monkeypatch.setattr(module, "utc_now_iso", lambda: clock["now"])
    settings = Settings(str(tmp_path / "settings.json"))
    settings.device_id_for_sync = "DESK"
    settings.set("reservations_enabled", True)
    phone = Phone()
    yield types.SimpleNamespace(
        clock=clock, settings=settings, phone=phone, base=str(tmp_path),
        storage=Storage(str(tmp_path / "zeiterfassung.json"), device_id="DESK"),
        reservations=ReservationStore(str(tmp_path / "reservations.json")),
        sick=SickStore(str(tmp_path / "sick.json"), device_id="DESK"),
        vacations=VacationStore(str(tmp_path / "vacations.json")),
        conflicts=ConflictsStore(str(tmp_path / "conflicts.json")))
    phone.close()


def sync(world, now, *, capable=True):
    """Ein Abgleich: Anfrage der PWA → echter Desktop → Antwort in die PWA. Ohne `capable` läuft der Desktop
    ohne Krankheits-Store: er beachtet `sick` nicht und antwortet ohne `sick_days` und `sick`."""
    world.clock["now"] = now
    world.phone.call("clock", now=now)
    sent = world.phone.call("request")
    body = json.dumps({"protocol": 2, "client_time": now, "last_pull_at": sent["last_pull_at"],
                       "entries": sent["entries"],
                       **({"reservations": sent["reservations"]} if sent["reservations"] else {}),
                       **({"sick": sent["sick"]} if sent["sick"] else {})}).encode()
    request = mobile_sync.parse_request(body, now=now, today=TODAY)
    response = json.loads(json.dumps(mobile_sync.perform_sync(
        request, device_id="phone-0001", device_name="Pixel", last_pull_at=sent["last_pull_at"],
        categories=["P"], storage=world.storage, settings=world.settings, conflicts_store=world.conflicts,
        base=world.base, now=now, today=TODAY, desktop=DESKTOP, reservation_store=world.reservations,
        sick_store=world.sick if capable else None, vacation_store=world.vacations)))
    state = world.phone.call("apply", response=response)
    return types.SimpleNamespace(sent=sent, response=response, state=state)


def report(world, now, start, end, *, delete_reservations=False):
    world.phone.call("clock", now=now)
    return world.phone.call("report", **{"from": start, "to": end, "deleteReservations": delete_reservations})


def desktop_live(world):
    return {date: record["minutes"] for date, record in world.sick.get_all_raw().items() if not record["deleted"]}


def standard(world, date):
    return sick_plan.standard_minutes(datetime.date.fromisoformat(date), world.settings)


def test_a_report_with_a_desktop_reservation_takes_its_minutes_and_deletes_it(world):
    world.reservations.save(FRI, [{"start": "09:00", "end": "13:00", "kategorie": "P"}])
    first = sync(world, T1)
    assert first.state["capable"] is True
    assert FRI in first.state["reservations"]

    reported = report(world, "2026-10-08T12:05:00Z", THU, MON, delete_reservations=True)

    assert reported["offered"]["dates"] == [FRI]                       # das Häkchen bot genau sie an
    assert reported["state"]["reservations"][FRI]["deleted"] is True   # vom Desktop: Tombstone, nicht verworfen
    # Ein künftiger Krankheitstag öffnet bei der Arbeitszeit, wo „Krankheit entfernen“ steht.
    lock = world.phone.call("lock", date=FRI)
    assert (lock["lock"]["kind"], lock["canReport"], lock["startTab"]) == ("sick", False, "work")

    result = sync(world, T2)

    assert sorted(result.sent["sick"]) == [THU, FRI, SAT, SUN, MON]
    assert all("minutes" not in day for day in result.sent["sick"].values())    # die Minuten rechnet der Desktop
    assert result.sent["reservations"][FRI]["deleted"] is True                  # im selben Paket
    assert desktop_live(world) == {THU: standard(world, THU), FRI: 240, SAT: 0, SUN: 0, MON: standard(world, MON)}
    assert FRI not in world.reservations.get_all()
    assert result.state["pending"] == 0
    assert {date: record["minutes"] for date, record in result.state["sick"].items()} == desktop_live(world)
    assert FRI not in result.state["reservations"]


def test_b_a_second_sync_sends_nothing_and_keeps_the_desktop_stamps(world):
    sync(world, T1)
    report(world, "2026-10-08T12:05:00Z", THU, FRI)
    sync(world, T2)
    before = world.sick.get_all_raw()

    again = sync(world, T3)

    assert again.sent["sick"] == {} and again.sent["reservations"] == {}
    assert world.sick.get_all_raw() == before
    assert again.state["pending"] == 0

    # Erneut melden über bekannte Tage: die gehen wieder hinaus, der Desktop behält ihre Datensätze samt Stempel.
    report(world, "2026-10-08T12:25:00Z", THU, SAT)
    overlap = sync(world, T4)

    assert sorted(overlap.sent["sick"]) == [THU, FRI, SAT]
    after = world.sick.get_all_raw()
    assert {date: after[date] for date in before} == before
    assert desktop_live(world)[SAT] == 0
    assert overlap.state["pending"] == 0


def test_c_removing_the_block_sends_tombstones_and_clears_the_desktop(world):
    sync(world, T1)
    report(world, "2026-10-08T12:05:00Z", THU, MON)
    sync(world, T2)

    world.phone.call("clock", now="2026-10-08T12:15:00Z")
    removed = world.phone.call("remove", date=SAT)                    # mitten im Block: der ganze Block
    assert removed["block"]["dates"] == [THU, FRI, SAT, SUN, MON]
    result = sync(world, T3)

    assert sorted(result.sent["sick"]) == [THU, FRI, SAT, SUN, MON]
    assert all(day == {"modified_at": "2026-10-08T12:15:00Z", "deleted": True} for day in result.sent["sick"].values())
    assert desktop_live(world) == {}
    assert result.state["pending"] == 0
    assert all(record["deleted"] for record in result.state["sick"].values())
    lock = world.phone.call("lock", date=THU)
    assert (lock["lock"], lock["canReport"]) == (None, True)


def test_c_a_sick_day_from_the_desktop_removed_on_the_phone_goes_out_as_tombstone(world):
    world.sick.save_range({TUE: 300})
    first = sync(world, T1)
    assert first.state["sick"][TUE]["minutes"] == 300
    assert first.state["sick"][TUE]["synced_version"] >= 1           # sonst verwürfe das Entfernen nur lokal

    world.phone.call("clock", now="2026-10-08T12:15:00Z")
    world.phone.call("remove", date=TUE)
    result = sync(world, T2)

    assert result.sent["sick"] == {TUE: {"modified_at": "2026-10-08T12:15:00Z", "deleted": True}}
    assert desktop_live(world) == {}
    assert result.state["pending"] == 0


def test_d_without_the_capability_local_sick_days_stay_and_nothing_is_sent(world):
    sync(world, T1)
    report(world, "2026-10-08T12:05:00Z", THU, THU)

    old = sync(world, T2, capable=False)                              # das Handy hielt den Desktop noch für fähig

    assert old.state["capable"] is False
    assert world.sick.get_all_raw() == {}                             # der Desktop hat es nicht übernommen
    kept = old.state["sick"][THU]
    assert (kept["deleted"], kept["synced_version"], kept["dirty_version"]) == (False, 0, 1)   # lokal, nicht übertragen
    assert old.state["pending"] == 0                                  # verborgen: zählt nicht als offen
    quiet = sync(world, T3, capable=False)
    assert quiet.sent["sick"] == {}
    assert quiet.state["sick"] == old.state["sick"]
    lock = world.phone.call("lock", date=THU)
    assert (lock["lock"], lock["canReport"]) == (None, False)

    # Mit der Fähigkeit zurück geht der Tag beim nächsten Abgleich hinaus.
    assert sync(world, T4).sent["sick"] == {}                         # die Fähigkeit kennt das Handy erst danach
    back = sync(world, T5)
    assert list(back.sent["sick"]) == [THU]
    assert desktop_live(world) == {THU: standard(world, THU)}
    assert back.state["pending"] == 0
