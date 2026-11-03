# tests/test_relay_service.py
"""Der Dienst über der Relay-Verbindung (#358, PR 3b): offenes Geheimnis, Binden, Aufräumen,
Lebenszyklus. Gefälschter Link und Relay-Aufrufer, echte `MobileBoxStore`/`MobileBoxCursor`,
echter `RelayAdapter` mit den Umschlägen des Test-Handys."""
from __future__ import annotations

import json
import struct
import threading

import pytest

from src import mobile_keys, mobile_pairing, relay_service
from src.mobile_box_cursor import MobileBoxCursor
from src.mobile_box_store import MobileBoxReadOnly, MobileBoxStore
from src.mobile_relay_codec import TYPE_PUT, TYPE_SLOT, relay_link
from src.pwa_constants import PWA_URL
from src.relay_link import DEFAULT_TIMING, LinkTiming
from src.relay_service import RelayService
from src.time_utils import utc_now_iso
from tests.fakes_relay import FakeConnect, wait_until
from tests.mobile_phone import FakeRing, Phone
from tests.test_mobile_service import make_service, sync_run

NOW = "2026-11-03T10:00:00Z"


@pytest.fixture(autouse=True)
def ring(monkeypatch):
    """Kein Test fasst den echten Schlüsselbund an."""
    fake = FakeRing()
    monkeypatch.setattr(mobile_keys, "keyring_store", fake)
    return fake


class FakeLink:
    """Steht für `RelayLink`: merkt sich `set_boxes`/`put`/`shutdown`; Handler und `on_idle` ruft
    der Test selbst (deterministisch, im Test-Thread)."""

    def __init__(self, connect, handler, cursor, *, on_idle=None, timing=DEFAULT_TIMING):
        self.handler = handler
        self.on_idle = on_idle
        self.cursor = cursor
        self.boxes: set[str] | None = None
        self.history: list[set[str]] = []
        self.puts: list[tuple[str, bytes]] = []
        self.closed = False

    def set_boxes(self, secrets):
        self.boxes = set(secrets)
        self.history.append(set(secrets))

    def put(self, secret, frame):
        self.puts.append((secret, frame))
        return True

    def states(self):
        return {secret: "connected" for secret in (self.boxes or ())}

    def shutdown(self):
        self.closed = True


class Env:
    def __init__(self, tmp_path, monkeypatch, *, run=sync_run):
        self.links: list[FakeLink] = []

        def factory(*args, **kwargs):
            link = FakeLink(*args, **kwargs)
            self.links.append(link)
            return link
        monkeypatch.setattr(relay_service, "RelayLink", factory)
        self.mobile, self.settings, _ctx = make_service(tmp_path)
        self.ctx = self.mobile.context
        self.box_path = str(tmp_path / "mobile_box.json")
        self.boxes = MobileBoxStore(self.box_path)
        self.cursor_path = str(tmp_path / "mobile_box_cursor.json")
        self.cursor = MobileBoxCursor(self.cursor_path)
        self.deleted: list[str] = []
        self.relay = RelayService(self.settings, self.ctx, self.boxes, self.cursor, run=run,
                                  delete_box=self._delete, now=lambda: NOW)

    def _delete(self, secret):
        self.deleted.append(secret)
        return True

    @property
    def link(self) -> FakeLink:
        return self.links[-1]

    def open(self):
        """`open_pairing` und die Teile des Koppel-Links: (Link, Geheimnis, Code)."""
        link = self.relay.open_pairing()
        assert link is not None
        secret, code = link.split("#relay=", 1)[1].split(":", 1)
        return link, secret, code

    def pair_payload(self, code, phone=None):
        phone = phone or Phone()
        envelope = phone.pair_request(mobile_pairing.normalize_code(code))
        payload = json.dumps({"v": 1, "path": "/v1/pair", "token": None,
                              "envelope": envelope}).encode()
        return phone, payload


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def slot(ver, data):
    return bytes([TYPE_SLOT]) + struct.pack(">I", ver) + data


def bind_device(boxes, device_id):
    secret, _old = boxes.open_pending(NOW)
    boxes.bind(device_id)
    return secret


# --- Start und Einstellung --------------------------------------------------------------------------

def test_apply_clears_orphan_pending_on_start(tmp_path, monkeypatch):
    earlier = MobileBoxStore(str(tmp_path / "mobile_box.json"))
    bound = bind_device(earlier, "phone-aaaa")
    orphan, _old = earlier.open_pending(NOW)

    env = Env(tmp_path, monkeypatch)
    env.relay.apply()

    assert env.boxes.pending() is None
    assert env.deleted == [orphan]
    assert env.link.boxes == {bound}


def test_apply_does_its_work_in_the_worker(tmp_path, monkeypatch):
    queued = []
    env = Env(tmp_path, monkeypatch, run=lambda fn, on_done=None: queued.append(fn))
    orphan, _old = env.boxes.open_pending(NOW)

    env.relay.apply()                          # UI-Thread: nichts blockiert, nichts passiert sofort
    assert env.link.history == [] and env.deleted == [] and env.boxes.pending() == orphan
    for fn in queued:
        fn()
    assert env.deleted == [orphan]


def test_offline_relay_holds_neither_start_nor_shutdown(tmp_path, monkeypatch):
    """Review Focus 5: ein hängendes `delete_box` (offline) läuft im Worker; weder `apply` noch
    `shutdown` warten darauf."""
    workers: list[threading.Thread] = []

    def thread_run(fn, on_done=None):
        thread = threading.Thread(target=fn, daemon=True)
        workers.append(thread)
        thread.start()
    env = Env(tmp_path, monkeypatch, run=thread_run)
    env.boxes.open_pending(NOW)
    entered, release = threading.Event(), threading.Event()

    def hanging_delete(secret):
        entered.set()
        release.wait(5)
        return False
    env.relay._delete_box = hanging_delete

    env.relay.apply()
    assert entered.wait(5)                     # der Worker hängt im Netz
    env.relay.shutdown()                       # kehrt trotzdem zurück
    assert env.link.closed and workers[0].is_alive()
    before = len(env.link.history)             # getrennt wird vor dem Löschen am Relay
    release.set()
    workers[0].join(5)
    assert not workers[0].is_alive()
    assert len(env.link.history) == before     # nach `shutdown` keine Boxen mehr gesetzt


def test_disabled_setting_disconnects_all(env):
    bound = bind_device(env.boxes, "phone-aaaa")
    env.relay.apply()
    assert env.link.boxes == {bound}

    env.settings.set_many({"mobile_enabled": False})
    env.relay.apply()
    assert env.link.boxes == set()


def test_a_closing_app_disconnects_all(env):
    bind_device(env.boxes, "phone-aaaa")
    env.mobile.shutdown()                       # `closing()` des Kontexts wird wahr
    env.relay.apply()
    assert env.link.boxes == set()


# --- Kopplung -------------------------------------------------------------------------------------

def test_open_pairing_returns_relay_link_and_connects_pending(env):
    link, secret, code = env.open()

    assert env.boxes.pending() == secret
    assert link == relay_link(secret, code) and link.startswith(f"{PWA_URL}#relay=")
    assert env.ctx.pairing.is_active()
    assert secret in env.link.boxes


def test_pending_only_connected_while_pairing_active(env):
    _link, secret, _code = env.open()
    assert secret in env.link.boxes

    env.ctx.pairing.close()                    # Code abgelaufen oder Dialog zu
    env.relay.apply()
    assert secret not in env.link.boxes

    env.link.on_idle()                         # das Aufräumen räumt das verwaiste Geheimnis ab
    assert env.boxes.pending() is None and env.deleted == [secret]


def test_close_pairing_clears_pending_and_deletes_the_box(env):
    _link, secret, _code = env.open()
    env.relay.close_pairing()

    assert not env.ctx.pairing.is_active()
    assert env.boxes.pending() is None and env.deleted == [secret]
    assert secret not in env.link.boxes


def test_open_pairing_deletes_previous_pending_but_not_unbound_leftover(env, monkeypatch):
    _l, first, _c = env.open()
    _l, second, code = env.open()
    assert env.deleted == [first] and first not in env.link.boxes

    # Kopplung auf `second` gelingt, das Binden scheitert: `second` ist ein ungebundener Rest.
    def failing_bind(device_id, expected=None):
        raise OSError("Platte voll")
    monkeypatch.setattr(env.boxes, "bind", failing_bind)
    _phone, payload = env.pair_payload(code)
    env.link.handler(second, payload)
    assert env.boxes.pending() == second

    # Ein neues Koppeln würde den Rest aus dem Store verdrängen: abgelehnt, ohne Sitzung.
    assert env.relay.open_pairing() is None
    assert not env.ctx.pairing.is_active()
    assert second not in env.deleted and env.boxes.pending() == second
    assert second in env.link.boxes


def test_a_refused_open_pairing_leaves_a_foreign_lan_session_open(env, monkeypatch):
    """Die Ablehnung schließt keine Sitzung, die dieser Aufruf nicht geöffnet hat (LAN-Dialog)."""
    _l, second, code = env.open()

    def failing_bind(device_id, expected=None):
        raise OSError("Platte voll")
    monkeypatch.setattr(env.boxes, "bind", failing_bind)
    _phone, payload = env.pair_payload(code)
    env.link.handler(second, payload)          # ungebundener Rest entsteht
    lan_code = env.ctx.pairing.open()          # der LAN-Koppeldialog öffnet seine Sitzung

    assert env.relay.open_pairing() is None
    assert env.ctx.pairing.is_active() and lan_code


def test_open_pairing_is_refused_while_mobile_is_off(env):
    env.settings.set_many({"mobile_enabled": False})
    assert env.relay.open_pairing() is None
    assert not env.ctx.pairing.is_active() and env.boxes.pending() is None


def test_repairing_a_device_deletes_its_old_box_and_cursor(env):
    phone = Phone()
    _l, old, code = env.open()
    _phone, payload = env.pair_payload(code, phone)
    env.link.handler(old, payload)
    assert env.boxes.get(phone.device_id) == old
    env.cursor.advance(old, 7)

    _l, new, code = env.open()                 # dasselbe Handy koppelt erneut
    _phone, payload = env.pair_payload(code, phone)
    env.link.handler(new, payload)

    assert env.boxes.get(phone.device_id) == new
    assert env.deleted == [old] and env.cursor.get(old) == 0
    assert new in env.link.boxes and old not in env.link.boxes


def test_a_concurrent_snapshot_never_drops_the_box_being_bound(env, monkeypatch):
    """Fix-Runde 1: ein `set_boxes` aus einem anderen Thread (hier `apply` im Worker) darf zwischen
    Verarbeiten und Binden der Kopplung keinen Schnappschuss nehmen, der P weder offen-aktiv noch
    gebunden sieht — P fiele sonst aus den Boxen und die Antwort der Kopplung ginge verloren."""
    _l, secret, code = env.open()
    phone, payload = env.pair_payload(code)
    original = env.relay._adapter.process
    other: list[threading.Thread] = []
    env.relay.apply()                          # Start-Aufräumen erledigt: nur noch Schnappschuss
    seen_at = len(env.link.history)

    def process_then_race(data):
        result = original(data)                # Code verbraucht, P noch `pending`
        thread = threading.Thread(target=env.relay._reconcile, daemon=True)
        thread.start()
        other.append(thread)
        thread.join(0.2)                       # mit dem Fix wartet er auf das Binden
        return result
    monkeypatch.setattr(env.relay._adapter, "process", process_then_race)

    env.link.handler(secret, payload)
    other[0].join(5)
    assert not other[0].is_alive()

    assert env.boxes.get(phone.device_id) == secret
    assert len(env.link.history) > seen_at
    assert all(secret in boxes for boxes in env.link.history[seen_at:])
    assert env.link.puts and env.link.puts[-1][0] == secret


@pytest.mark.parametrize("error", [MobileBoxReadOnly("x"), OSError("x")])
def test_open_pairing_readonly_store_closes_session_and_returns_none(env, monkeypatch, error):
    def failing_open(now):
        raise error
    monkeypatch.setattr(env.boxes, "open_pending", failing_open)

    assert env.relay.open_pairing() is None
    assert not env.ctx.pairing.is_active()


def test_pair_request_binds_pending_with_expected_secret(env, monkeypatch):
    calls = []
    original = env.boxes.bind

    def spy(device_id, expected=None):
        calls.append((device_id, expected))
        return original(device_id, expected=expected)
    monkeypatch.setattr(env.boxes, "bind", spy)
    _l, secret, code = env.open()
    phone, payload = env.pair_payload(code)

    env.link.handler(secret, payload)

    assert calls == [(phone.device_id, secret)]
    assert env.boxes.get(phone.device_id) == secret and env.boxes.pending() is None
    assert [s for s, _f in env.link.puts] == [secret]
    assert secret in env.link.boxes and env.deleted == []


def test_bind_failure_is_retried_on_idle_and_never_deleted(env, monkeypatch):
    original = env.boxes.bind
    failing = [True]

    def flaky(device_id, expected=None):
        if failing[0]:
            raise OSError("gesperrt")
        return original(device_id, expected=expected)
    monkeypatch.setattr(env.boxes, "bind", flaky)
    _l, secret, code = env.open()
    phone, payload = env.pair_payload(code)

    env.link.handler(secret, payload)
    assert env.link.puts                       # das Handy bekommt seine Antwort trotzdem
    env.ctx.pairing.close()                    # Code abgelaufen
    env.relay.close_pairing()
    env.link.on_idle()
    assert env.boxes.pending() == secret and env.deleted == []
    assert secret in env.link.boxes            # das Handy benutzt die Box schon

    failing[0] = False
    env.link.on_idle()
    assert env.boxes.get(phone.device_id) == secret and env.boxes.pending() is None
    assert env.deleted == [] and secret in env.link.boxes


def test_pair_when_new_pairing_opened_meanwhile_does_not_bind(env, monkeypatch):
    _l, secret, code = env.open()
    phone, payload = env.pair_payload(code)
    original = env.relay._adapter.process
    newer = []

    def process_then_new_pairing(data):
        result = original(data)
        newer.append(env.boxes.open_pending(NOW)[0])   # ein neues Koppeln dazwischen
        return result
    monkeypatch.setattr(env.relay._adapter, "process", process_then_new_pairing)

    env.link.handler(secret, payload)

    assert env.boxes.get(phone.device_id) is None
    assert env.boxes.pending() == newer[0]


def test_handler_puts_frame_and_skips_none(env):
    _l, secret, code = env.open()
    env.link.handler(secret, b"kein json")
    assert env.link.puts == []

    _phone, payload = env.pair_payload(code)
    env.link.handler(secret, payload)
    assert len(env.link.puts) == 1 and env.link.puts[0][0] == secret
    assert json.loads(env.link.puts[0][1])["status"] == 200


def test_expired_code_cleans_pending_after_handler(env, monkeypatch):
    """Review Focus 7: der Code läuft ab, während die Kopplungs-Anfrage läuft, und der Dialog
    schließt gleichzeitig im Worker. Binden kommt vor jedem Aufräumen, das Geheimnis bleibt."""
    _l, secret, code = env.open()
    phone, payload = env.pair_payload(code)
    original = env.relay._adapter.process
    closer: list[threading.Thread] = []

    def process_and_expire(data):
        result = original(data)
        env.ctx.pairing.close()                # Code läuft ab
        thread = threading.Thread(target=env.relay.close_pairing, daemon=True)
        thread.start()                         # Dialog schließt im Worker
        closer.append(thread)
        thread.join(0.2)
        assert thread.is_alive()               # wartet, bis gebunden ist
        return result
    monkeypatch.setattr(env.relay._adapter, "process", process_and_expire)

    env.link.handler(secret, payload)
    closer[0].join(5)
    assert not closer[0].is_alive()
    env.link.on_idle()

    assert env.boxes.get(phone.device_id) == secret and env.boxes.pending() is None
    assert env.deleted == [] and secret in env.link.boxes


def test_on_idle_does_nothing_while_mobile_is_off(env):
    """Ausgeschaltet spricht die App den Relay nicht an, auch nicht aus dem Leerlauf-Takt."""
    orphan, _old = env.boxes.open_pending(NOW)
    env.settings.set_many({"mobile_enabled": False})

    env.link.on_idle()

    assert env.deleted == [] and env.boxes.pending() == orphan and env.link.history == []


def test_boxes_are_disconnected_before_they_are_deleted_at_the_relay(env):
    """Erst `set_boxes`, dann `delete_box`: sonst bekäme der noch verbundene Leser `wiped` und
    verbände sich neu mit der gerade gelöschten Box."""
    connected_at_delete = []

    def delete(secret):
        connected_at_delete.append(secret in (env.link.boxes or set()))
        return True
    env.relay._delete_box = delete
    _l, _secret, _code = env.open()
    env.ctx.pairing.close()                    # Code abgelaufen
    env.link.on_idle()                         # räumt das offene Geheimnis ab
    bind_device(env.boxes, "phone-aaaa")
    env.relay.apply()
    env.relay.forget_devices(["phone-aaaa"])

    assert connected_at_delete == [False, False]


def test_discarding_the_pending_box_drops_its_cursor(env):
    _l, secret, _code = env.open()
    env.cursor.advance(secret, 2)              # eine gescheiterte Kopplungsanfrage kam an

    env.relay.close_pairing()

    assert env.deleted == [secret] and env.cursor.get(secret) == 0
    assert MobileBoxCursor(env.cursor_path).get(secret) == 0      # auch in der Datei verworfen


def test_a_pair_request_in_flight_during_shutdown_neither_binds_nor_answers(env, monkeypatch):
    """Eine Kopplung, die beim Entfernen schon verarbeitet wird, schreibt `mobile_box.json` danach
    nicht neu."""
    _l, secret, code = env.open()
    phone, payload = env.pair_payload(code)
    original = env.relay._adapter.process

    def process_then_shutdown(data):
        result = original(data)
        env.relay.shutdown()                   # Entfernen kommt dazwischen
        return result
    monkeypatch.setattr(env.relay._adapter, "process", process_then_shutdown)
    writes = []
    monkeypatch.setattr(env.boxes, "bind", lambda *a, **k: writes.append(a))

    env.link.handler(secret, payload)

    assert writes == [] and env.link.puts == []
    assert env.boxes.get(phone.device_id) is None


# --- Widerruf -------------------------------------------------------------------------------------

def test_forget_devices_removes_boxes_cursor_and_deletes_remote(env):
    a = bind_device(env.boxes, "phone-aaaa")
    b = bind_device(env.boxes, "phone-bbbb")
    env.cursor.advance(a, 3)
    env.cursor.advance(b, 4)
    env.relay.apply()

    env.relay.forget_devices(["phone-aaaa"])
    assert env.boxes.known_ids() == ["phone-bbbb"]
    assert env.cursor.get(a) == 0 and env.cursor.get(b) == 4
    assert env.deleted == [a] and env.link.boxes == {b}

    env.relay.forget_devices(None)
    assert env.boxes.known_ids() == [] and env.cursor.get(b) == 0
    assert env.deleted == [a, b] and env.link.boxes == set()


def test_forget_all_keeps_a_device_that_paired_meanwhile(env):
    gone = bind_device(env.boxes, "phone-aaaa")
    fresh = bind_device(env.boxes, "phone-bbbb")
    record, _token = mobile_pairing.issue_device("phone-bbbb", "Neu", utc_now_iso())
    env.ctx.devices.save(record)               # nach dem Widerruf gekoppelt, nicht widerrufen

    env.relay.forget_devices(None)

    assert env.boxes.known_ids() == ["phone-bbbb"] and env.deleted == [gone]
    assert env.boxes.get("phone-bbbb") == fresh


def test_forget_devices_drops_an_unbound_leftover(env, monkeypatch):
    def failing_bind(device_id, expected=None):
        raise OSError("Platte voll")
    monkeypatch.setattr(env.boxes, "bind", failing_bind)
    _l, secret, code = env.open()
    phone, payload = env.pair_payload(code)
    env.link.handler(secret, payload)
    assert env.mobile.revoke(phone.device_id)

    env.relay.forget_devices([phone.device_id])

    assert env.boxes.pending() is None and env.deleted == [secret]
    assert secret not in env.link.boxes


def test_states_by_device_maps_ids_without_secrets(env):
    bind_device(env.boxes, "phone-aaaa")
    env.relay.apply()
    states = env.relay.states_by_device()
    assert states == {"phone-aaaa": "connected"}

    env.settings.set_many({"mobile_enabled": False})
    env.relay.apply()
    assert env.relay.states_by_device() == {"phone-aaaa": relay_service.STATE_OFF}


# --- Mit echtem RelayLink -------------------------------------------------------------------------

def test_a_pair_over_the_real_link_binds_and_answers(tmp_path):
    """Durchstich mit dem echten `RelayLink` und gefälschter WebSocket: Kopplung über die offene
    Box, Antwort als `put`, Geheimnis gebunden und am Gerät weiter verbunden."""
    mobile, settings, _ctx = make_service(tmp_path)
    ctx = mobile.context
    boxes = MobileBoxStore(str(tmp_path / "mobile_box.json"))
    cursor = MobileBoxCursor(str(tmp_path / "mobile_box_cursor.json"))
    connect = FakeConnect()
    relay = RelayService(settings, ctx, boxes, cursor, run=sync_run, connect=connect,
                         delete_box=lambda s: True, now=lambda: NOW,
                         timing=LinkTiming(idle_tick_s=0.05, join_s=1.0))
    try:
        link = relay.open_pairing()
        assert link is not None
        secret, code = link.split("#relay=", 1)[1].split(":", 1)
        sock = connect.socket(0)
        assert connect.calls[0].secret == secret
        phone = Phone()
        envelope = phone.pair_request(mobile_pairing.normalize_code(code))
        sock.feed(slot(1, json.dumps({"v": 1, "path": "/v1/pair", "token": None,
                                      "envelope": envelope}).encode()))

        assert wait_until(lambda: any(isinstance(m, bytes) and m[:1] == bytes([TYPE_PUT])
                                      for m in sock.sent))
        assert wait_until(lambda: boxes.get(phone.device_id) == secret)
        assert cursor.get(secret) == 1
        relay.close_pairing()                  # Dialog zu: die gebundene Box bleibt verbunden
        assert relay.states_by_device() == {phone.device_id: "connected"}
        assert sock in connect.open_sockets()
    finally:
        relay.shutdown()


# --- Lebenszyklus ---------------------------------------------------------------------------------

def test_shutdown_stops_link_and_apply_after_shutdown_is_noop(env):
    bind_device(env.boxes, "phone-aaaa")
    env.relay.shutdown()
    assert env.link.closed

    env.relay.apply()
    assert env.relay.open_pairing() is None
    assert env.link.history == [] and not env.ctx.pairing.is_active()


def test_reopen_allows_apply_again(env):
    bound = bind_device(env.boxes, "phone-aaaa")
    env.relay.shutdown()
    first = env.link
    env.relay.reopen()

    assert env.link is not first and not env.link.closed
    env.relay.apply()
    assert env.link.boxes == {bound}
