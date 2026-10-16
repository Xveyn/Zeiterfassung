# tests/test_api_reservations.py
"""/v1/reservations: Lesen, Ersetzen, Löschen (#239, PR 6)."""
import datetime
import json

import pytest

from src.api_auth import SCOPE_LOCAL, Principal
from src.api_routes import ApiContext, ApiRequest, handle
from src.reservations import ReservationStore
from src.storage import Storage
from src.vacations import VacationStore

LOCAL = Principal("local", frozenset({SCOPE_LOCAL}))
TODAY = datetime.date(2026, 10, 14)
DAY = "2026-10-20"
BODY = json.dumps({"slots": [{"start": "08:00", "end": "12:00", "kategorie": "Projekt"}]}).encode()


class Env:
    def __init__(self, tmp_path, enabled=True, with_store=True):
        self.reservations = ReservationStore(str(tmp_path / "reservations.json"))
        self.vacations = VacationStore(str(tmp_path / "vacations.json"))
        self.storage = Storage(str(tmp_path / "zeiterfassung.json"), device_id="dev")
        self.changes = 0
        self.reconciles = 0
        self.events = []
        self.ctx = ApiContext(
            storage=self.storage, settings={"reservations_enabled": enabled},
            app_version=lambda: "t", vacation_store=self.vacations,
            reservation_store=self.reservations if with_store else None,
            today=lambda: TODAY,
            on_change=self._changed, on_reservations_change=self._reconcile)

    def _changed(self):
        self.changes += 1
        self.events.append("change")

    def _reconcile(self):
        self.reconciles += 1
        self.events.append("reconcile")

    def call(self, method, path, body=b"", query=None):
        return handle(ApiRequest(method, path, query or {}, body), self.ctx, LOCAL)

    def put(self, body=BODY, day=DAY):
        return self.call("PUT", f"/v1/reservations/{day}", body)

    def delete(self, day=DAY):
        return self.call("DELETE", f"/v1/reservations/{day}")

    def get(self, day=DAY):
        return self.call("GET", f"/v1/reservations/{day}")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def code(response):
    return response.body["error"]["code"]


def slot(start="08:00", end="12:00", kategorie="Projekt", reminder=None):
    return {"start": start, "end": end, "kategorie": kategorie,
            "send_reminder_minutes": reminder}


# --- Schalter aus: eine ordentliche Meldung -----------------------------------

@pytest.mark.parametrize("method,path", [
    ("PUT", f"/v1/reservations/{DAY}"), ("DELETE", f"/v1/reservations/{DAY}")])
def test_writing_with_reservations_switched_off_is_409_with_a_useful_message(
        tmp_path, method, path):
    env = Env(tmp_path, enabled=False)

    response = env.call(method, path, BODY)

    assert (response.status, code(response)) == (409, "reservations_disabled")
    message = response.body["error"]["message"]
    assert "Einstellungen" in message and "Reservierungen" in message
    assert env.reservations.get(DAY) is None
    assert (env.changes, env.reconciles) == (0, 0)


def test_switched_off_is_reported_before_the_body_is_looked_at(tmp_path):
    env = Env(tmp_path, enabled=False)
    assert code(env.put(b"{kaputt")) == "reservations_disabled"


def test_a_missing_store_is_reported_the_same_way(tmp_path):
    env = Env(tmp_path, with_store=False)
    assert code(env.put()) == "reservations_disabled"
    assert code(env.get()) == "reservations_disabled"


def test_reading_works_with_reservations_switched_off(tmp_path):
    env = Env(tmp_path, enabled=True)
    env.put()
    env.ctx = ApiContext(**{**env.ctx.__dict__, "settings": {"reservations_enabled": False}})

    assert env.get().status == 200
    assert env.call("GET", "/v1/reservations").status == 200


# --- GET ------------------------------------------------------------------------

def test_get_day_returns_the_wire_slots_without_the_calendar_id(env):
    env.reservations.save(DAY, [{"start": "08:00", "end": "12:00", "kategorie": "Projekt",
                                 "gcal_event_id": "evt-1", "send_reminder_minutes": 15}])

    response = env.get()

    assert response.status == 200
    assert response.body == {"date": DAY, "slots": [slot(reminder=15)]}


def test_get_unknown_and_tombstoned_day_is_404(env):
    assert code(env.get()) == "not_found"
    env.put()
    env.delete()
    assert env.get().status == 404


def test_get_range_is_sorted_filtered_and_skips_tombstones(env):
    for day in ("2026-10-22", "2026-10-20", "2026-10-25"):
        env.reservations.save(day, [slot()])
    env.reservations.delete("2026-10-25")

    everything = env.call("GET", "/v1/reservations")
    ranged = env.call("GET", "/v1/reservations", query={"from": ["2026-10-21"]})

    assert list(everything.body["reservations"]) == ["2026-10-20", "2026-10-22"]
    assert everything.body["reservations"]["2026-10-20"] == {"slots": [slot()]}
    assert list(ranged.body["reservations"]) == ["2026-10-22"]


@pytest.mark.parametrize("query,status,error", [
    ({"from": ["x"]}, 400, "invalid_date"),
    ({"from": ["2026-10-22"], "to": ["2026-10-20"]}, 400, "invalid_range"),
    ({"zzz": ["1"]}, 400, "unknown_parameter"),
])
def test_get_range_rejects_bad_queries(env, query, status, error):
    response = env.call("GET", "/v1/reservations", query=query)
    assert (response.status, code(response)) == (status, error)


def test_get_bad_date_is_400(env):
    assert (env.get("20261020").status, code(env.get("20261020"))) == (400, "invalid_date")


def test_stored_junk_never_leaves_the_api(env):
    env.reservations._data[DAY] = {"slots": [
        {"start": None, "end": "12:00"}, {"start": "09:00", "end": "10:00", "kategorie": 5},
    ], "modified_at": "x", "deleted": False}

    assert env.get().body["slots"] == [slot("09:00", "10:00", "")]


# --- PUT ------------------------------------------------------------------------

def test_put_creates_the_day_and_triggers_refresh_then_calendar_reconcile(env):
    response = env.put()

    assert response.status == 200
    assert response.body == {"date": DAY, "slots": [slot()], "changed": True}
    assert env.reservations.get(DAY)["slots"] == [slot()]
    assert env.events == ["change", "reconcile"]


def test_put_replaces_the_whole_day(env):
    env.put()
    two = json.dumps({"slots": [{"start": "09:00", "end": "10:00"},
                                {"start": "13:00", "end": "14:00"}]}).encode()

    response = env.put(two)

    assert [s["start"] for s in response.body["slots"]] == ["09:00", "13:00"]


def test_put_of_an_identical_day_changes_nothing_and_stays_quiet(env):
    env.put()
    stamp = env.reservations.get_all_raw()[DAY]["modified_at"]
    env.events.clear()

    response = env.put()

    assert response.body["changed"] is False
    assert env.events == []
    assert env.reservations.get_all_raw()[DAY]["modified_at"] == stamp


def test_put_revives_a_tombstoned_day(env):
    env.put()
    env.delete()
    assert env.put().body["changed"] is True
    assert env.get().status == 200


def test_put_keeps_calendar_event_ids_by_position(env):
    env.put()
    env.reservations._data[DAY]["slots"][0]["gcal_event_id"] = "evt-1"
    longer = json.dumps({"slots": [{"start": "08:00", "end": "11:00"},
                                   {"start": "13:00", "end": "14:00"}]}).encode()

    env.put(longer)

    stored = env.reservations.get_all_raw()[DAY]["slots"]
    assert [s["gcal_event_id"] for s in stored] == ["evt-1", None]


def test_put_without_reminder_field_keeps_the_existing_marker_by_position(env):
    env.reservations.save(DAY, [slot("08:00", "12:00", "Projekt", reminder=20)])

    response = env.put(json.dumps({"slots": [{"start": "08:00", "end": "13:00"}]}).encode())

    assert response.body["slots"][0]["send_reminder_minutes"] == 20


def test_put_with_an_explicit_null_clears_the_marker(env):
    env.reservations.save(DAY, [slot("08:00", "12:00", "Projekt", reminder=20)])

    response = env.put(json.dumps({"slots": [
        {"start": "08:00", "end": "12:00", "kategorie": "Projekt",
         "send_reminder_minutes": None}]}).encode())

    assert response.body["slots"][0]["send_reminder_minutes"] is None
    assert response.body["changed"] is True


def test_put_can_set_the_reminder(env):
    response = env.put(json.dumps({"slots": [
        {"start": "08:00", "end": "12:00", "send_reminder_minutes": 10}]}).encode())

    assert response.body["slots"][0]["send_reminder_minutes"] == 10


def test_put_on_a_vacation_day_is_409_but_a_zero_minute_day_is_allowed(env):
    env.vacations.save(None, "Sommer", "2026-10-20", "2026-10-22",
                       {"2026-10-20": 480, "2026-10-21": 0, "2026-10-22": 480})

    blocked = env.put(day="2026-10-20")
    allowed = env.put(day="2026-10-21")

    assert (blocked.status, code(blocked)) == (409, "vacation_day")
    assert allowed.status == 200
    assert env.reservations.get("2026-10-20") is None


@pytest.mark.parametrize("day,status,error", [
    ("2026-10-13", 422, "date_in_past"),
    ("2027-10-15", 422, "date_too_far"),
    ("1999-12-31", 422, "date_out_of_range"),
    ("2026-02-30", 400, "invalid_date"),
    ("20261020", 400, "invalid_date"),
])
def test_put_rejects_bad_days(env, day, status, error):
    response = env.put(day=day)
    assert (response.status, code(response)) == (status, error)
    assert env.events == []


def test_put_today_is_allowed(env):
    assert env.put(day=TODAY.isoformat()).status == 200


@pytest.mark.parametrize("raw,status,error", [
    (b"{", 400, "invalid_json"),
    (b'{"slots": []}', 422, "empty_slots"),
    (b'{"slots": [{"start": "08:00", "end": "12:00", "pause": 5}]}', 422, "invalid_slot"),
])
def test_put_maps_body_errors(env, raw, status, error):
    response = env.put(raw)
    assert (response.status, code(response)) == (status, error)
    assert env.reservations.get(DAY) is None


def test_put_takes_no_query(env):
    response = env.call("PUT", f"/v1/reservations/{DAY}", BODY, query={"x": ["1"]})
    assert code(response) == "unknown_parameter"


def test_a_failing_hook_does_not_turn_a_saved_write_into_a_500(tmp_path):
    env = Env(tmp_path)

    def boom():
        raise RuntimeError("kaputt")
    env.ctx = ApiContext(**{**env.ctx.__dict__, "on_reservations_change": boom})

    assert env.put().status == 200
    assert env.reservations.get(DAY) is not None


def test_writes_are_refused_while_the_app_closes(tmp_path):
    env = Env(tmp_path)
    env.ctx = ApiContext(**{**env.ctx.__dict__, "closing": lambda: True})

    assert (env.put().status, code(env.put())) == (503, "shutting_down")
    assert env.reservations.get(DAY) is None


# --- DELETE ---------------------------------------------------------------------

def test_delete_leaves_a_tombstone_and_triggers_refresh_and_reconcile(env):
    env.put()
    env.events.clear()

    response = env.delete()

    assert (response.status, response.body) == (200, {"date": DAY, "deleted": True})
    assert env.reservations.get(DAY) is None
    assert env.reservations.get_all_raw()[DAY]["deleted"] is True
    assert env.events == ["change", "reconcile"]


def test_delete_of_a_missing_day_is_404_and_quiet(env):
    response = env.delete()
    assert (response.status, code(response)) == (404, "not_found")
    assert env.events == []


def test_delete_cleans_up_a_past_reservation(env):
    env.reservations.save("2026-09-01", [slot()])

    assert env.delete("2026-09-01").status == 200


def test_delete_touches_no_actual_hours_and_no_vacation(env):
    env.storage.save(DAY, [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": ""}])
    env.put()

    env.delete()

    assert env.storage.get(DAY) is not None


def test_methods_are_listed_for_405(env):
    response = env.call("POST", f"/v1/reservations/{DAY}")
    assert response.status == 405
    assert response.headers["Allow"] == "DELETE, GET, PUT"


def test_check_and_save_run_under_the_shared_lock_and_the_hooks_after_it(tmp_path):
    import threading

    class Lock:
        def __init__(self):
            self._lock = threading.RLock()
            self.depth = 0

        def __enter__(self):
            self._lock.acquire()
            self.depth += 1

        def __exit__(self, *exc):
            self.depth -= 1
            self._lock.release()

    env = Env(tmp_path)
    lock = Lock()
    seen = []
    real_save = env.reservations.save
    env.reservations.save = lambda *a, **k: (seen.append(("save", lock.depth)), real_save(*a, **k))
    env.ctx = ApiContext(**{**env.ctx.__dict__, "data_lock": lock,
                            "on_reservations_change": lambda: seen.append(("hook", lock.depth))})

    env.put()

    assert seen == [("save", 1), ("hook", 0)]
