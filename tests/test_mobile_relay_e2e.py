"""Ende-zu-Ende (#444): Relay-Abgleich, echter `RelayAdapter` gegen die echte PWA-Logik.

Beide Seiten sind echt: der Desktop mit `RelayAdapter`, echtem `dispatch`, Stores auf der Platte und
echter Verschlüsselung; das Handy mit `SyncClient` und `RelayTransport` in einem Node-Prozess
(`mobile_relay_probe.mjs`). Die Unit-Tests je Seite prüfen jede mit eigenen Annahmen über die andere
(`test_relay_adapter.py`, `pwa/test/relay-transport.test.js`); hier laufen die drei Regeln des Abgleichs
(2: `seq <= last_seq` ohne Antwort, 3: Zwischenspeicher der Kopplungsantwort, 1: fremdes `res` wird
übergangen) tatsächlich gegeneinander.

Nachgebildet ist nur die **Box**, der Platz dazwischen (`FakeBox`): ein Slot je Richtung, `have`. Die echte
Box ist ein Durable Object und wird in `relay/` getestet. Ohne Node wird übersprungen; die CI hat es."""
from __future__ import annotations

import datetime
import json
import pathlib
import shutil
import subprocess
from typing import Any

import pytest

from src import mobile_keys, mobile_pairing, mobile_routes
from src.mobile_relay_codec import encode_response
from src.relay_adapter import RelayAdapter, RelayResult
from tests.mobile_phone import FakeRing
from tests.test_mobile_service import make_service

PROBE = pathlib.Path(__file__).resolve().parent / "mobile_relay_probe.mjs"
SECRET = "B" * 43
FOREIGN_NONCE = "AAAAAAAAAAAAAAAA"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node fehlt")


@pytest.fixture(autouse=True)
def ring(monkeypatch):
    """Kein Test fasst den echten Schlüsselbund an."""
    monkeypatch.setattr(mobile_keys, "keyring_store", FakeRing())


class FakeBox:
    """Die Box zwischen Handy und Desktop: ein Slot (die letzte Antwort) und je Richtung ein eigener
    Zähler (`req_ver` für `ok`, `res_ver` für `slot`; die echte Box startet sie bei den Sekunden seit
    2026-01-01). `have` des Handys folgt nur dem `slot`.

    `lose_next_response`: die Antwort liegt im Slot, erreicht das Handy aber nicht (die Verbindung reißt
    nach `ok`). Beim nächsten Verbinden stellt die Box den Slot erneut zu, solange `ver > have`.
    `wipe_when_lost`: dazu wird die Box geleert (`1000 wiped`); der Slot ist weg, `have` beim Handy 0.

    Bei einem Verbindungsende bleibt ein bereits gesendetes `put` gültig: die Box verarbeitet es auch dann,
    wenn das Handy die Antwort schon beim Verbinden bekommen hat."""

    EPOCH_SECONDS = 25_000_000

    def __init__(self, adapter: RelayAdapter) -> None:
        self.adapter = adapter
        self.req_ver = self.res_ver = self.EPOCH_SECONDS
        self.slot: tuple[int, bytes] | None = None
        self.puts: list[bytes] = []
        self.results: list[RelayResult] = []
        self.lose_next_response = False
        self.wipe_when_lost = False

    def preload_foreign_response(self) -> None:
        """Im Slot liegt die Antwort auf eine **andere** Anfrage (fremde Nonce)."""
        self.res_ver += 1
        self.slot = (self.res_ver, encode_response(200, {"v": 2, "seq": 1, "n": FOREIGN_NONCE, "c": "AAAA"},
                                                   1, FOREIGN_NONCE))

    def on_connect(self, have: int) -> dict[str, Any]:
        deliver = []
        if self.slot is not None and self.slot[0] > have:
            deliver.append({"type": "slot", "ver": self.slot[0], "hex": self.slot[1].hex()})
        return {"deliver": deliver, "close": None}

    def on_put(self, payload: bytes) -> dict[str, Any]:
        self.puts.append(payload)
        self.req_ver += 1
        deliver: list[dict[str, Any]] = [{"type": "ok", "ver": self.req_ver}]
        result = self.adapter.process(payload)
        self.results.append(result)
        if result.frame is None:
            return {"deliver": deliver, "close": None}
        self.res_ver += 1
        self.slot = (self.res_ver, result.frame)
        if self.lose_next_response:
            self.lose_next_response = False
            if self.wipe_when_lost:
                self.slot = None
                return {"deliver": deliver, "close": {"code": 1000, "reason": "wiped"}}
            return {"deliver": deliver, "close": {"code": 1006, "reason": ""}}
        deliver.append({"type": "slot", "ver": self.res_ver, "hex": result.frame.hex()})
        return {"deliver": deliver, "close": None}


class Phone:
    """Das Handy: ein Node-Prozess mit der echten PWA, gesteuert per Zeilenprotokoll."""

    def __init__(self, box: FakeBox, *, timeout_ms: int = 5000) -> None:
        self.box = box
        self.proc = subprocess.Popen(["node", str(PROBE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, encoding="utf-8", bufsize=1)
        try:
            self.call("setup", timeoutMs=timeout_ms)
        except BaseException:
            self.close()
            raise

    def _send(self, message: dict[str, Any]) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def call(self, cmd: str, **args: Any) -> Any:
        self._send({"cmd": cmd, **args})
        assert self.proc.stdout
        while True:
            line = self.proc.stdout.readline()
            assert line, "Der Node-Prozess ist beendet"
            out = json.loads(line)
            if "event" in out:
                event = out["event"]
                if event["type"] == "connect":
                    self._send(self.box.on_connect(event["have"]))
                else:
                    self._send(self.box.on_put(bytes.fromhex(event["hex"])))
            elif "error" in out:
                raise AssertionError(out["error"])
            else:
                return out["ok"]

    def close(self) -> None:
        """Beendet den Node-Prozess auch dann, wenn ein Test mittendrin gescheitert ist."""
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()
            self.proc.wait()
        finally:
            if self.proc.stdout:
                self.proc.stdout.close()


@pytest.fixture
def world(tmp_path, monkeypatch):
    _service, _settings, ctx = make_service(tmp_path)
    adapter = RelayAdapter(ctx)
    box = FakeBox(adapter)
    calls: list[str] = []
    original = mobile_routes.dispatch

    def spy(request, context, principal):
        calls.append(request.path)
        return original(request, context, principal)
    monkeypatch.setattr(mobile_routes, "dispatch", spy)
    phone = Phone(box, timeout_ms=1500)
    yield type("World", (), {"ctx": ctx, "box": box, "phone": phone, "calls": calls})
    phone.close()


def open_code(world) -> str:
    code = mobile_pairing.normalize_code(world.ctx.pairing.open())
    assert code is not None
    return code


def pair(world) -> dict[str, Any]:
    return world.phone.call("pair", secret=SECRET, code=open_code(world))


def paired(world) -> dict[str, Any]:
    result = pair(world)
    assert result == {"desktopName": "Desktop"}
    world.calls.clear()
    return result


def last_seq(world) -> int:
    (record,) = world.ctx.devices.get_all()
    return int(record.get("last_seq", 0))


def day(offset: int = 1) -> str:
    return (datetime.date.today() - datetime.timedelta(days=offset)).isoformat()


def save_day(world, offset: int = 1, end: str = "12:00") -> None:
    world.phone.call("save", date=day(offset),
                     slots=[{"start": "08:00", "end": end, "pause": 0, "kategorie": ""}])


# --- Grundablauf ----------------------------------------------------------------------------------

def test_pairing_and_two_syncs_run_through_the_box(world):
    paired_result = pair(world)
    save_day(world)
    first = world.phone.call("sync")
    second = world.phone.call("sync")

    assert paired_result == {"desktopName": "Desktop"}
    assert first["sent"] == 1 and first["received"] == 1
    assert second["sent"] == 0 and second["received"] == 1
    assert world.calls == ["/v1/pair", "/v1/sync", "/v1/sync"]
    state = world.phone.call("state")
    assert state["transport"] == "relay" and state["token"] and state["pending"] == 0
    assert state["seq"] == 2 == last_seq(world)
    assert state["box_have"] == world.box.res_ver             # jedes `slot` hat `have` vorgerückt, `ok` nicht
    assert world.ctx.storage.get_all_raw()[day()]["slots"][0]["end"] == "12:00"


# --- Regel 3: Kopplung genau einmal ---------------------------------------------------------------

def test_a_lost_pair_answer_is_redelivered_identically_and_the_pairing_happens_once(world):
    world.box.lose_next_response = True

    result = pair(world)

    assert result == {"desktopName": "Desktop"}
    first, second = world.box.puts
    assert first == second                                      # der zweite Versuch trägt dieselben Bytes
    assert world.calls == ["/v1/pair"]                          # `dispatch` lief nur einmal
    assert world.box.results[0].frame is not None and world.box.results[1].frame == world.box.results[0].frame
    assert world.box.results[1].paired_device_id == world.box.results[0].paired_device_id
    (record,) = world.ctx.devices.get_all()
    assert mobile_pairing.pair_count(record) == 1
    assert world.phone.call("state")["token"]


def test_a_refused_pairing_is_never_cached_and_answers_the_retry_again(world):
    world.ctx.pairing.open()
    world.box.lose_next_response = True

    result = world.phone.call("pair", secret=SECRET, code=mobile_pairing.generate_code())

    assert result == {"failed": {"kind": "invalid_code", "code": "invalid_code"}}
    assert world.box.puts[0] == world.box.puts[1]
    assert world.calls == ["/v1/pair", "/v1/pair"]              # der Fehler wurde nicht zwischengespeichert
    assert world.ctx.devices.get_all() == []
    assert world.phone.call("state")["token"] == ""


# --- Regel 2: kein Replay beantworten ---------------------------------------------------------------

def test_a_lost_sync_answer_is_not_answered_twice_but_the_box_redelivers_it(world):
    paired(world)
    save_day(world)
    world.box.lose_next_response = True

    result = world.phone.call("sync")

    assert result["sent"] == 1 and "failed" not in result
    first, second = world.box.puts[-2:]
    assert first == second
    assert world.box.results[-1].frame is None                  # Regel 2: die Wiederholung bekommt keine Antwort
    assert world.calls == ["/v1/sync"]                          # und läuft nicht erneut durch `dispatch`
    assert last_seq(world) == 1
    state = world.phone.call("state")
    assert state["pending"] == 0                                # die redelivered Antwort wurde angewendet
    assert state["box_have"] == world.box.res_ver


def test_a_replay_after_the_box_was_wiped_leaves_the_phone_waiting_and_the_next_sync_heals(world):
    paired(world)
    save_day(world)
    world.box.lose_next_response = True
    world.box.wipe_when_lost = True          # `1000 wiped`: der Slot ist weg, `have` fällt auf 0

    failed = world.phone.call("sync")

    assert failed == {"failed": {"kind": "desktop_silent", "code": "desktop_silent"}}
    assert world.box.results[-1].frame is None                  # die Wiederholung bekam keine Antwort
    assert world.calls == ["/v1/sync"] and last_seq(world) == 1
    assert world.phone.call("state")["pending"] == 1            # nichts bestätigt, der Tag bleibt offen

    healed = world.phone.call("sync")

    assert "failed" not in healed and healed["sent"] == 1
    assert last_seq(world) == 2 and world.phone.call("state")["pending"] == 0


def test_a_409_replay_from_dispatch_gets_no_answer(world, monkeypatch):
    paired(world)
    save_day(world)
    through_spy = mobile_routes.dispatch
    statuses: list[int] = []

    def applied_in_between(request, context, principal):
        # Dieselbe Anfrage wird nach der Prüfung des Adapters schon angewendet (anderer Weg): das zweite
        # `dispatch` meldet `409 replay`, und das überschriebe im Slot die gute Antwort.
        statuses.append(through_spy(request, context, principal).status)
        second = through_spy(request, context, principal)
        statuses.append(second.status)
        return second
    monkeypatch.setattr(mobile_routes, "dispatch", applied_in_between)

    failed = world.phone.call("sync")

    assert statuses == [200, 409]
    assert world.box.results[-1].frame is None and world.box.slot is not None
    assert failed == {"failed": {"kind": "desktop_silent", "code": "desktop_silent"}}
    assert last_seq(world) == 1


def test_last_seq_is_read_from_the_device_record_not_kept_in_the_adapter(world):
    paired(world)
    save_day(world)
    assert world.phone.call("sync")["sent"] == 1
    request = world.box.puts[-1]
    world.box.adapter = RelayAdapter(world.ctx)                  # „Neustart“: kein Zustand im Speicher
    world.calls.clear()

    again = world.box.on_put(request)                            # dieselbe Anfrage wird erneut zugestellt

    assert [m["type"] for m in again["deliver"]] == ["ok"]       # keine Antwort
    assert world.calls == [] and last_seq(world) == 1
    assert world.phone.call("sync")["sent"] == 0                 # der nächste Abgleich (seq 2) geht durch
    assert last_seq(world) == 2


def test_re_pairing_after_a_replay_resets_the_counter_and_seq_1_is_answered_again(world):
    paired(world)
    assert "failed" not in world.phone.call("sync")
    world.box.adapter.handle(world.box.puts[-1])                 # ein Replay von seq 1: keine Antwort
    assert last_seq(world) == 1

    assert pair(world) == {"desktopName": "Desktop"}             # Neu-Koppeln setzt `last_seq` zurück
    assert last_seq(world) == 0
    resumed = world.phone.call("sync")                           # das Handy zählt wieder bei seq 1

    assert "failed" not in resumed
    assert last_seq(world) == 1


# --- Regel 1: fremdes res übergehen -----------------------------------------------------------------

def test_a_foreign_answer_delivered_on_connect_is_skipped(world):
    paired(world)
    save_day(world)
    world.box.preload_foreign_response()
    foreign_ver = world.box.res_ver

    result = world.phone.call("sync")

    assert result["sent"] == 1 and "failed" not in result
    assert world.calls == ["/v1/sync"] and last_seq(world) == 1
    state = world.phone.call("state")
    assert state["pending"] == 0
    assert state["box_have"] == world.box.res_ver > foreign_ver     # `have` rückte auch über das fremde `slot` vor
