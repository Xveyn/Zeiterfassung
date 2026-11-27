# tests/test_api_sick.py
"""/v1/sick: Lesen, Anlegen, Löschen und die Sperren drumherum."""
import datetime
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
    message = response.body["error"]["message"]
    assert message.startswith("An diesen Tagen ist bereits Arbeitszeit erfasst: 2026-07-08.")
    assert "Reservierung" not in message
    assert "Krankheit und Arbeitszeit schließen sich am selben Tag aus" in message
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
    assert response.body["error"]["message"] == (
        "Für diesen Tag ist Krankheit eingetragen. An einem Krankheitstag lässt sich keine "
        "Arbeitszeit erfassen; die Krankheit zuerst in der App löschen.")
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


def test_summary_route_uses_the_sick_store(env):
    env.sick.save_range({"2026-07-06": 300})
    response = env.call("GET", "/v1/summary/month/2026-07")
    assert response.status == 200
    assert response.body["sick_minutes"] == 300
    assert response.body["payable_minutes"] == 300


def _average_env(env):
    # Referenzzeitraum davor: 4 Wochen je 4 h an Werktagen -> 4800 min über 24 Arbeitstage = 200 min
    for week in range(4):
        for offset in range(5):
            day = datetime.date(2026, 6, 1) + datetime.timedelta(days=week * 7 + offset)
            env.storage.save(day.isoformat(), [ist_slot("08:00", "12:00")])
    env.ctx = ApiContext(**{**env.ctx.__dict__, "today": lambda: datetime.date(2026, 7, 6)})


def test_basis_in_body_overrides_setting_and_setting_is_default(env):
    _average_env(env)
    env.settings["sick_hours_basis"] = "average_3m"
    default = env.call("POST", "/v1/sick", make_body(**{"to": FIRST}))
    assert default.body["days"][FIRST] == 200
    env.call("DELETE", f"/v1/sick/{FIRST}")
    override = env.call("POST", "/v1/sick", make_body(**{"to": FIRST}, basis="standard"))
    assert override.body["days"][FIRST] == 480                 # Body gewinnt
    env.call("DELETE", f"/v1/sick/{FIRST}")
    env.settings["sick_hours_basis"] = "standard"
    body = env.call("POST", "/v1/sick", make_body(**{"to": FIRST}, basis="average_3m"))
    assert body.body["days"][FIRST] == 200


def test_reservation_minutes_prefill_only_when_reservations_active(env):
    env.reservations.save(FIRST, [{"start": "09:00", "end": "11:00", "kategorie": ""}])
    on = env.call("POST", "/v1/sick", make_body(**{"to": FIRST}))
    assert on.body["days"][FIRST] == 120
    env.call("DELETE", f"/v1/sick/{FIRST}")
    env.settings["reservations_enabled"] = False
    off = env.call("POST", "/v1/sick", make_body(**{"to": FIRST}))
    assert off.body["days"][FIRST] == 480



# --- Review PR 5 -----------------------------------------------------------------

HUGE = 10 ** 400


def test_huge_integer_hours_are_422_not_500(env):
    response = env.call("POST", "/v1/sick", make_body(day_hours={FIRST: HUGE}))
    assert (response.status, code(response)) == (422, "invalid_day_hours")


def test_post_has_its_own_no_state_text(env):
    env.settings["state"] = ""
    warning = env.call("POST", "/v1/sick", make_body()).body["warnings"][0]
    assert warning["code"] == "no_state"
    assert "Urlaub" not in warning["message"]
    assert "Krankheit" in warning["message"]


def test_changed_flag_and_on_change_only_when_something_changed(env):
    first = env.call("POST", "/v1/sick", make_body())
    assert first.body["changed"] is True and env.events == ["change"]
    again = env.call("POST", "/v1/sick", make_body())
    assert again.status == 201 and again.body["changed"] is False
    assert env.events == ["change"]


def test_basis_used_and_average_fallback_warning(env):
    response = env.call("POST", "/v1/sick", make_body(**{"to": FIRST}, basis="average_3m"))
    assert response.body["basis_used"] == "standard"
    assert "average_fallback" in [w["code"] for w in response.body["warnings"]]
    plain = env.call("POST", "/v1/sick", make_body(**{"from": "2026-07-13", "to": "2026-07-13"}))
    assert plain.body["basis_used"] == "standard"
    assert "average_fallback" not in [w["code"] for w in plain.body["warnings"]]


def test_sick_over_vacation_warns(env):
    env.vacations.save(None, "U", FIRST, LAST,
                       {"2026-07-06": 480, "2026-07-07": 480, "2026-07-08": 480,
                        "2026-07-09": 480, "2026-07-10": 480})
    response = env.call("POST", "/v1/sick", make_body(**{"to": FIRST}))
    warning = [w for w in response.body["warnings"] if w["code"] == "sick_on_vacation"]
    assert len(warning) == 1
    from src.sick_plan import HINT_SICK_ON_VACATION
    assert warning[0]["message"] == HINT_SICK_ON_VACATION
    clean = env.call("POST", "/v1/sick", make_body(**{"from": "2026-07-13", "to": "2026-07-13"}))
    assert "sick_on_vacation" not in [w["code"] for w in clean.body["warnings"]]


def test_vacation_over_zero_minute_sick_day_warns(env):
    env.sick.save_range({"2026-07-11": 0})
    body = json.dumps({"name": "U", "from": "2026-07-10", "to": "2026-07-12",
                       "hours_per_day": 8, "day_hours": {"2026-07-11": 8}}).encode()
    response = env.call("POST", "/v1/vacations", body)
    assert response.status == 201
    assert "vacation_on_sick_day" in [w["code"] for w in response.body["warnings"]]
    plain = json.dumps({"name": "V", "from": "2026-08-03", "to": "2026-08-03",
                        "hours_per_day": 8}).encode()
    other = env.call("POST", "/v1/vacations", plain)
    assert "vacation_on_sick_day" not in [w["code"] for w in other.body["warnings"]]


def test_huge_hours_in_vacations_are_422(env):
    for field in ("hours_per_day", "total_hours"):
        body = json.dumps({"name": "U", "from": FIRST, "to": LAST, field: HUGE}).encode()
        response = env.call("POST", "/v1/vacations", body)
        assert (response.status, code(response)) == (422, "invalid_hours")
    body = ('{"name": "U", "from": "%s", "to": "%s", "hours_per_day": 8, '
            '"day_hours": {"%s": %d}}' % (FIRST, LAST, FIRST, HUGE)).encode()
    assert code(env.call("POST", "/v1/vacations", body)) == "invalid_day_hours"


def test_sick_wins_over_vacation_in_put_409(env):
    env.vacations.save(None, "U", FIRST, FIRST, {FIRST: 480})
    env.sick.save_range({FIRST: 480})
    body = json.dumps({"slots": [ist_slot("08:00", "12:00")]}).encode()
    response = env.call("PUT", f"/v1/entries/{FIRST}", body)
    assert (response.status, code(response)) == (409, "sick_day")


def test_shutting_down_refuses_post_and_delete(env):
    env.sick.save_range({FIRST: 480})
    env.ctx = ApiContext(**{**env.ctx.__dict__, "closing": lambda: True})
    for method, path, body in (("POST", "/v1/sick", make_body()),
                               ("DELETE", f"/v1/sick/{FIRST}", b"")):
        response = env.call(method, path, body)
        assert (response.status, code(response)) == (503, "shutting_down")
    assert env.sick.day_minutes() == {FIRST: 480}


def test_delete_from_a_zero_minute_day_removes_the_whole_block(env):
    env.sick.save_range({"2026-07-10": 480, "2026-07-11": 0, "2026-07-12": 0})
    response = env.call("DELETE", "/v1/sick/2026-07-12")
    assert response.status == 200
    assert env.sick.day_minutes() == {}


def test_block_length_366_accepted_367_refused(env):
    ok = env.call("POST", "/v1/sick", json.dumps({"from": "2026-01-01", "to": "2026-12-31"}).encode())
    assert ok.status == 201
    env.call("DELETE", "/v1/sick/2026-01-01")
    over = env.call("POST", "/v1/sick",
                    json.dumps({"from": "2026-01-01", "to": "2027-01-02"}).encode())
    assert over.status == 422
