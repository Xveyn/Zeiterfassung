# tests/test_api_vacations.py
"""/v1/vacations: Lesen, Anlegen, Löschen (#239, PR 7)."""
import json

import pytest

from src.api_auth import SCOPE_LOCAL, Principal
from src.api_routes import ApiContext, ApiRequest, handle
from src.reservations import ReservationStore
from src.storage import Storage
from src.vacations import VacationStore
from tests.conftest import ist_slot

LOCAL = Principal("local", frozenset({SCOPE_LOCAL}))
# Mo 2026-07-06 … Fr 2026-07-10 (5 Arbeitstage), Wochenende 11./12., dann 13.–17.
FIRST, LAST = "2026-07-06", "2026-07-17"


def make_body(**fields):
    base = {"name": "Sommer", "from": FIRST, "to": LAST, "hours_per_day": 8}
    base.update(fields)
    return json.dumps({k: v for k, v in base.items() if v is not None}).encode()


class Env:
    def __init__(self, tmp_path, settings=None):
        self.vacations = VacationStore(str(tmp_path / "vacations.json"))
        self.storage = Storage(str(tmp_path / "zeiterfassung.json"), device_id="dev")
        self.reservations = ReservationStore(str(tmp_path / "reservations.json"))
        self.settings = {"state": "NW", "reservations_enabled": True}
        if settings:
            self.settings.update(settings)
        self.events = []
        self.ctx = ApiContext(
            storage=self.storage, settings=self.settings, app_version=lambda: "t",
            vacation_store=self.vacations, reservation_store=self.reservations,
            on_change=lambda: self.events.append("change"),
            on_vacations_change=lambda: self.events.append("reconcile"))

    def call(self, method, path, body=b"", query=None):
        return handle(ApiRequest(method, path, query or {}, body), self.ctx, LOCAL)

    def post(self, body=None):
        return self.call("POST", "/v1/vacations", make_body() if body is None else body)

    def get(self, vacation_id):
        return self.call("GET", f"/v1/vacations/{vacation_id}")

    def delete(self, vacation_id):
        return self.call("DELETE", f"/v1/vacations/{vacation_id}")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def code(response):
    return response.body["error"]["code"]


# --- POST -------------------------------------------------------------------------

def test_post_creates_the_period_with_the_minutes_the_app_would_compute(env):
    response = env.post()

    assert response.status == 201
    body = response.body
    assert (body["name"], body["from"], body["to"]) == ("Sommer", FIRST, LAST)
    # Arbeitstage 8 h, Wochenende 0
    assert body["days"]["2026-07-06"] == 480
    assert body["days"]["2026-07-11"] == 0 and body["days"]["2026-07-12"] == 0
    assert len(body["days"]) == 12                       # lückenlos von … bis
    assert body["total_minutes"] == 10 * 480 == sum(body["days"].values())
    assert env.vacations.get(body["id"])["days"] == body["days"]
    assert "gcal_event_id" not in body
    assert env.events == ["change", "reconcile"]


def test_post_total_hours_apportions_exactly(env):
    response = env.post(make_body(hours_per_day=None, total_hours=40))
    assert response.body["total_minutes"] == 2400
    # 40 h auf 10 Arbeitstage: je 240 Minuten
    assert {m for m in response.body["days"].values() if m} == {240}


def test_post_total_hours_that_do_not_divide_evenly_still_sum_exactly(env):
    # 1,5 h = 90 Minuten auf 4 Arbeitstage: 23, 23, 22, 22 — die ersten bekommen den Rest
    response = env.post(make_body(hours_per_day=None, total_hours=1.5,
                                  **{"from": "2026-07-06", "to": "2026-07-09"}))

    minutes = [response.body["days"][d] for d in sorted(response.body["days"])]
    assert minutes == [23, 23, 22, 22]
    assert response.body["total_minutes"] == 90


def test_post_day_hours_override_single_days(env):
    response = env.post(make_body(day_hours={"2026-07-10": 4}))
    assert response.body["days"]["2026-07-10"] == 240
    assert response.body["total_minutes"] == 9 * 480 + 240


def test_post_holidays_follow_the_state_setting(env):
    response = env.post(make_body(name="Weihnachten", **{"from": "2026-12-23", "to": "2026-12-28"}))
    days = response.body["days"]
    assert days["2026-12-25"] == 0 and days["2026-12-26"] == 0     # Feiertage
    assert days["2026-12-24"] == 480


def test_post_without_a_state_warns_that_holidays_are_not_known(tmp_path):
    env = Env(tmp_path, settings={"state": ""})

    response = env.post(make_body(name="Weihnachten", **{"from": "2026-12-23", "to": "2026-12-28"}))

    assert response.status == 201
    assert response.body["days"]["2026-12-25"] == 480            # volle Stunden
    assert [w["code"] for w in response.body["warnings"]] == ["no_state"]
    assert "Bundesland" in response.body["warnings"][0]["message"]


def test_post_with_a_state_has_no_warnings(env):
    assert env.post().body["warnings"] == []


@pytest.mark.parametrize("fields,error", [
    ({"hours_per_day": 25}, "invalid_vacation"),
    ({"hours_per_day": -1}, "invalid_vacation"),
    ({"hours_per_day": None, "total_hours": 400}, "invalid_vacation"),   # > 24 h/Tag
    ({"from": LAST, "to": FIRST}, "invalid_vacation"),
    ({"from": "2026-07-11", "to": "2026-07-12", "hours_per_day": None, "total_hours": 8},
     "invalid_vacation"),                                                # kein Arbeitstag
])
def test_post_maps_planner_errors_to_422_with_the_apps_message(env, fields, error):
    response = env.post(make_body(**fields))

    assert (response.status, code(response)) == (422, error)
    assert response.body["error"]["message"]
    assert env.vacations.get_all() == {}
    assert env.events == []


def test_post_overlapping_a_period_is_409_and_names_it(env):
    env.post()

    response = env.post(make_body(name="Zweiter", **{"from": "2026-07-15", "to": "2026-07-20"}))

    assert (response.status, code(response)) == (409, "vacation_overlap")
    assert "Sommer" in response.body["error"]["message"]
    assert len(env.vacations.get_all()) == 1


def test_post_over_actual_hours_is_409_and_lists_the_days(env):
    env.storage.save("2026-07-08", [ist_slot("08:00", "12:00")])

    response = env.post()

    assert (response.status, code(response)) == (409, "work_on_vacation_days")
    assert "2026-07-08" in response.body["error"]["message"]
    assert env.vacations.get_all() == {}


def test_post_over_a_reservation_blocks_only_when_reservations_are_on(tmp_path):
    (tmp_path / "a").mkdir()
    on = Env(tmp_path / "a")
    on.reservations.save("2026-07-08", [{"start": "08:00", "end": "12:00", "kategorie": ""}])
    assert code(on.post()) == "work_on_vacation_days"

    (tmp_path / "b").mkdir()
    off = Env(tmp_path / "b", settings={"reservations_enabled": False})
    off.reservations.save("2026-07-08", [{"start": "08:00", "end": "12:00", "kategorie": ""}])
    assert off.post().status == 201


def test_post_over_actual_hours_on_a_zero_minute_day_is_allowed(env):
    env.storage.save("2026-07-11", [ist_slot("08:00", "12:00")])   # Samstag
    assert env.post().status == 201


@pytest.mark.parametrize("raw,status,error", [
    (b"{", 400, "invalid_json"),
    (b'{"name": "x"}', 400, "invalid_body"),
    (make_body(name=""), 422, "invalid_name"),
    (make_body(**{"from": "2026-02-30"}), 422, "invalid_date"),
])
def test_post_maps_body_errors(env, raw, status, error):
    response = env.post(raw)
    assert (response.status, code(response)) == (status, error)
    assert env.events == []


def test_post_takes_no_query(env):
    assert code(env.call("POST", "/v1/vacations", make_body(), query={"x": ["1"]})) == "unknown_parameter"


def test_post_refused_while_closing(tmp_path):
    env = Env(tmp_path)
    env.ctx = ApiContext(**{**env.ctx.__dict__, "closing": lambda: True})
    response = env.post()
    assert (response.status, code(response)) == (503, "shutting_down")
    assert env.vacations.get_all() == {}


def test_a_failing_hook_does_not_turn_a_saved_vacation_into_a_500(tmp_path):
    env = Env(tmp_path)

    def boom():
        raise RuntimeError("kaputt")
    env.ctx = ApiContext(**{**env.ctx.__dict__, "on_vacations_change": boom})

    assert env.post().status == 201
    assert len(env.vacations.get_all()) == 1


def test_missing_store_is_reported(tmp_path):
    env = Env(tmp_path)
    env.ctx = ApiContext(**{**env.ctx.__dict__, "vacation_store": None})
    for response in (env.post(), env.call("GET", "/v1/vacations")):
        assert (response.status, code(response)) == (409, "vacations_unavailable")


# --- GET ----------------------------------------------------------------------------

def test_get_one_returns_the_period_uncapped(env):
    created = env.post().body

    response = env.get(created["id"])

    assert response.status == 200
    assert response.body == {k: v for k, v in created.items() if k != "warnings"}


def test_get_unknown_is_404(env):
    assert (env.get("deadbeef").status, code(env.get("deadbeef"))) == (404, "not_found")


def test_get_list_is_sorted_by_start_and_filtered_by_overlap(env):
    env.post(make_body(name="B", **{"from": "2026-09-07", "to": "2026-09-11"}))
    env.post(make_body(name="A", **{"from": "2026-07-06", "to": "2026-07-10"}))

    everything = env.call("GET", "/v1/vacations").body["vacations"]
    ranged = env.call("GET", "/v1/vacations", query={"from": ["2026-08-01"]}).body["vacations"]
    inside = env.call("GET", "/v1/vacations",
                      query={"from": ["2026-07-10"], "to": ["2026-07-10"]}).body["vacations"]

    assert [v["name"] for v in everything] == ["A", "B"]
    assert [v["name"] for v in ranged] == ["B"]
    assert [v["name"] for v in inside] == ["A"]          # Überlappung, nicht „liegt ganz drin“


@pytest.mark.parametrize("query,error", [
    ({"from": ["x"]}, "invalid_date"),
    ({"from": ["2026-07-10"], "to": ["2026-07-01"]}, "invalid_range"),
    ({"q": ["1"]}, "unknown_parameter"),
])
def test_get_list_rejects_bad_queries(env, query, error):
    assert code(env.call("GET", "/v1/vacations", query=query)) == error


def test_a_stored_period_without_range_or_days_is_left_out_of_the_list(env):
    env.vacations._data["zz"] = {"name": "kaputt", "gcal_event_id": None,
                                 "modified_at": "", "deleted": False, "days": {}}
    env.post()

    names = [v["name"] for v in env.call("GET", "/v1/vacations").body["vacations"]]

    assert names == ["Sommer"]


# --- DELETE -------------------------------------------------------------------------

def test_delete_removes_the_whole_period(env):
    created = env.post().body["id"]
    env.events.clear()

    response = env.delete(created)

    assert (response.status, response.body) == (200, {"id": created, "deleted": True})
    assert env.vacations.get(created) is None
    assert env.events[0] == "change"


def test_delete_asks_the_calendar_only_when_an_event_hung_there(env):
    plain = env.post().body["id"]
    env.events.clear()
    env.delete(plain)
    assert env.events == ["change"]

    pushed = env.post(make_body(name="Gepusht", **{"from": "2026-09-07", "to": "2026-09-11"})).body["id"]
    env.vacations._data[pushed]["gcal_event_id"] = "evt"
    env.events.clear()
    env.delete(pushed)
    assert env.events == ["change", "reconcile"]


def test_delete_unknown_is_404_and_quiet(env):
    response = env.delete("deadbeef")
    assert (response.status, code(response)) == (404, "not_found")
    assert env.events == []


def test_delete_refused_while_closing(tmp_path):
    env = Env(tmp_path)
    created = env.post().body["id"]
    env.ctx = ApiContext(**{**env.ctx.__dict__, "closing": lambda: True})
    assert env.delete(created).status == 503
    assert env.vacations.get(created) is not None


def test_there_is_no_put(env):
    created = env.post().body["id"]
    response = env.call("PUT", f"/v1/vacations/{created}", make_body())
    assert response.status == 405 and response.headers["Allow"] == "DELETE, GET"


def test_the_collection_allows_get_and_post_only(env):
    assert env.call("DELETE", "/v1/vacations").headers["Allow"] == "GET, POST"


def test_lock_covers_conflict_check_and_save(tmp_path):
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
    real_save = env.vacations.save
    real_all = env.storage.get_all
    env.vacations.save = lambda *a, **k: (seen.append(("save", lock.depth)), real_save(*a, **k))[1]
    env.storage.get_all = lambda: (seen.append(("check", lock.depth)), real_all())[1]
    env.ctx = ApiContext(**{**env.ctx.__dict__, "data_lock": lock,
                            "on_vacations_change": lambda: seen.append(("hook", lock.depth))})

    env.post()

    assert seen == [("check", 1), ("save", 1), ("hook", 0)]
