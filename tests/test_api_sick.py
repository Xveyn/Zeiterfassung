# tests/test_api_sick.py
"""/v1/sick: Lesen, Anlegen, Löschen und die Sperren drumherum."""
import json

import pytest

from src.api_auth import SCOPE_LOCAL, Principal
from src.api_routes import ApiContext, ApiRequest, handle
from src.reservations import ReservationStore
from src.sick_days import SickStore
from src.storage import Storage
from src.vacations import VacationStore
from tests.conftest import ist_slot

LOCAL = Principal("local", frozenset({SCOPE_LOCAL}))
FIRST, LAST = "2026-07-06", "2026-07-10"          # Mo–Fr


def make_body(**fields):
    base = {"from": FIRST, "to": LAST}
    base.update(fields)
    return json.dumps(base).encode()


class Env:
    def __init__(self, tmp_path, with_sick=True):
        self.sick = SickStore(str(tmp_path / "sick.json"), "dev")
        self.vacations = VacationStore(str(tmp_path / "vacations.json"))
        self.storage = Storage(str(tmp_path / "z.json"), device_id="dev")
        self.reservations = ReservationStore(str(tmp_path / "r.json"))
        self.settings = {"state": "NW", "reservations_enabled": True, "default_pause": 0}
        for key in ("mon", "tue", "wed", "thu", "fri"):
            self.settings[f"default_start_{key}"] = "08:00"
            self.settings[f"default_end_{key}"] = "16:00"
        self.events = []
        self.ctx = ApiContext(
            storage=self.storage, settings=self.settings, app_version=lambda: "t",
            vacation_store=self.vacations, reservation_store=self.reservations,
            sick_store=self.sick if with_sick else None,
            on_change=lambda: self.events.append("change"))

    def call(self, method, path, body=b"", query=None):
        return handle(ApiRequest(method, path, query or {}, body), self.ctx, LOCAL)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def code(response):
    return response.body["error"]["code"]


def test_post_creates_block_from_prefill(env):
    response = env.call("POST", "/v1/sick", make_body())
    assert response.status == 201
    assert (response.body["from"], response.body["to"]) == (FIRST, LAST)
    assert response.body["days"][FIRST] == 480
    assert response.body["total_minutes"] == 5 * 480
    assert env.sick.day_minutes()[LAST] == 480
    assert env.events == ["change"]
    assert response.body["warnings"] == []


def test_post_without_state_warns(env):
    env.settings["state"] = ""
    response = env.call("POST", "/v1/sick", make_body())
    assert [w["code"] for w in response.body["warnings"]] == ["no_state"]


def test_post_day_hours_override(env):
    response = env.call("POST", "/v1/sick", make_body(day_hours={FIRST: 4}))
    assert response.body["days"][FIRST] == 240


def test_post_keeps_existing_minutes_unless_day_hours(env):
    env.sick.save_range({"2026-07-07": 120})
    response = env.call("POST", "/v1/sick", make_body())
    assert response.body["days"]["2026-07-07"] == 120
    assert response.body["days"][FIRST] == 480
    response = env.call("POST", "/v1/sick", make_body(day_hours={"2026-07-07": 3}))
    assert response.body["days"]["2026-07-07"] == 180


def test_post_invalid_plan_is_422(env):
    response = env.call("POST", "/v1/sick", make_body(**{"from": LAST, "to": FIRST}))
    assert (response.status, code(response)) == (422, "invalid_sick")


def test_post_over_work_is_409_and_nothing_written(env):
    env.storage.save("2026-07-08", [ist_slot("08:00", "12:00")])
    response = env.call("POST", "/v1/sick", make_body())
    assert (response.status, code(response)) == (409, "work_on_sick_days")
    assert env.sick.day_minutes() == {}


def test_post_never_deletes_reservations(env):
    env.reservations.save("2026-07-08", [{"start": "08:00", "end": "12:00", "kategorie": ""}])
    env.call("POST", "/v1/sick", make_body())
    assert env.reservations.get("2026-07-08") is not None


def test_get_lists_intersecting_blocks_uncapped(env):
    env.sick.save_range({"2026-07-06": 480, "2026-07-07": 480, "2026-09-01": 60})
    env.storage.save("2026-07-06", [ist_slot("08:00", "12:00")])
    response = env.call("GET", "/v1/sick", query={"from": ["2026-07-07"], "to": ["2026-07-31"]})
    assert response.body == {"sick": [{"from": "2026-07-06", "to": "2026-07-07",
                                       "days": {"2026-07-06": 480, "2026-07-07": 480},
                                       "total_minutes": 960}]}
    assert len(env.call("GET", "/v1/sick").body["sick"]) == 2


def test_delete_removes_whole_block(env):
    env.sick.save_range({"2026-07-06": 480, "2026-07-07": 480})
    response = env.call("DELETE", "/v1/sick/2026-07-07")
    assert response.status == 200
    assert response.body == {"from": "2026-07-06", "to": "2026-07-07", "deleted": True}
    assert env.sick.day_minutes() == {}
    assert env.events == ["change"]


def test_delete_unknown_is_404(env):
    assert code(env.call("DELETE", "/v1/sick/2026-07-07")) == "not_found"


def test_without_store_everything_is_409(tmp_path):
    env = Env(tmp_path, with_sick=False)
    for method, path, body in (("GET", "/v1/sick", b""), ("POST", "/v1/sick", make_body()),
                               ("DELETE", "/v1/sick/2026-07-07", b"")):
        response = env.call(method, path, body)
        assert (response.status, code(response)) == (409, "sick_unavailable")


def test_put_entry_on_sick_day_is_409_but_delete_allowed(env):
    env.sick.save_range({"2026-07-07": 480})
    body = json.dumps({"slots": [ist_slot("08:00", "12:00")]}).encode()
    response = env.call("PUT", "/v1/entries/2026-07-07", body)
    assert (response.status, code(response)) == (409, "sick_day")
    env.storage.save("2026-07-07", [ist_slot("08:00", "12:00")])
    assert env.call("DELETE", "/v1/entries/2026-07-07").status == 200


def test_zero_minute_sick_day_does_not_block_put(env):
    env.sick.save_range({"2026-07-11": 0})
    body = json.dumps({"slots": [ist_slot("08:00", "12:00")]}).encode()
    assert env.call("PUT", "/v1/entries/2026-07-11", body).status == 200


def test_new_vacation_over_sick_day_is_409(env):
    env.sick.save_range({"2026-07-08": 480})
    body = json.dumps({"name": "U", "from": FIRST, "to": LAST, "hours_per_day": 8}).encode()
    response = env.call("POST", "/v1/vacations", body)
    assert (response.status, code(response)) == (409, "sick_on_vacation_days")
    assert "krank gemeldet" in response.body["error"]["message"]
    assert env.vacations.get_all() == {}
