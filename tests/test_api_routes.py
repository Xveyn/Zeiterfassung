# tests/test_api_routes.py
import json
import logging
import threading

import pytest

from src.api_auth import SCOPE_LOCAL, Principal
from src.api_routes import API_VERSION, ApiContext, ApiRequest, handle
from src.conflicts_store import ConflictsStore
from src.storage import Storage
from src.vacations import VacationStore
from tests.conftest import ist_slot

LOCAL = Principal("local", frozenset({SCOPE_LOCAL}))


@pytest.fixture
def storage(tmp_path):
    return Storage(str(tmp_path / "zeiterfassung.json"), device_id="dev")


def make_ctx(storage, settings=None, version="1.2.3-test", now="2026-10-06T12:00:00Z"):
    return ApiContext(
        storage=storage,
        settings={"device_name": "Laptop"} if settings is None else settings,
        app_version=lambda: version,
        now=lambda: now,
    )


def call(path, ctx, query=None, method="GET", principal=LOCAL):
    return handle(ApiRequest(method, path, query or {}), ctx, principal)


def seed(storage):
    storage.save("2026-01-05", [ist_slot("08:00", "12:00", 0, "Projekt")])
    storage.save("2026-01-20", [ist_slot("09:00", "17:00", 30)])
    storage.save("2026-02-03", [ist_slot("10:00", "11:00")])


# --- /v1/status ----------------------------------------------------------

def test_status_reports_versions_device_and_time(storage):
    response = call("/v1/status", make_ctx(storage))

    assert response.status == 200
    assert response.body == {
        "api_version": API_VERSION,
        "app_version": "1.2.3-test",
        "device_name": "Laptop",
        "time": "2026-10-06T12:00:00Z",
    }


def test_status_device_name_defaults_to_empty(storage):
    response = call("/v1/status", make_ctx(storage, settings={}))
    assert response.body["device_name"] == ""


def test_status_takes_no_query(storage):
    response = call("/v1/status", make_ctx(storage), {"x": ["1"]})
    assert (response.status, response.body["error"]["code"]) == (400, "unknown_parameter")


# --- /v1/entries ------------------------------------------------------------

def test_entries_without_range_returns_everything_sorted(storage):
    seed(storage)

    response = call("/v1/entries", make_ctx(storage))

    assert response.status == 200
    entries = response.body["entries"]
    assert list(entries) == ["2026-01-05", "2026-01-20", "2026-02-03"]
    assert entries["2026-01-05"] == {
        "slots": [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}]}


def test_entries_empty_store_gives_empty_object(storage):
    assert call("/v1/entries", make_ctx(storage)).body == {"entries": {}}


@pytest.mark.parametrize("query,expected", [
    ({"from": ["2026-01-20"]}, ["2026-01-20", "2026-02-03"]),
    ({"to": ["2026-01-20"]}, ["2026-01-05", "2026-01-20"]),
    ({"from": ["2026-01-06"], "to": ["2026-02-02"]}, ["2026-01-20"]),
    ({"from": ["2026-01-05"], "to": ["2026-01-05"]}, ["2026-01-05"]),
    ({"from": ["2027-01-01"]}, []),
])
def test_entries_range_is_inclusive(storage, query, expected):
    seed(storage)
    response = call("/v1/entries", make_ctx(storage), query)
    assert list(response.body["entries"]) == expected


def test_entries_leave_out_tombstones(storage):
    seed(storage)
    storage.delete("2026-01-20")

    response = call("/v1/entries", make_ctx(storage))

    assert list(response.body["entries"]) == ["2026-01-05", "2026-02-03"]


def test_entries_are_copies_of_the_store(storage):
    seed(storage)
    first = call("/v1/entries", make_ctx(storage))
    first.body["entries"]["2026-01-05"]["slots"][0]["start"] = "00:00"

    second = call("/v1/entries", make_ctx(storage))

    assert second.body["entries"]["2026-01-05"]["slots"][0]["start"] == "08:00"


# --- Review Focus 1: Datumsformen und Query ----------------------------------

BAD_DATES = ["2026-1-5", "20260105", "2026-W01-1", "2026-02-30", "2026-13-01", "",
             "heute", "2026-01-05T10:00", "٢٠٢٦-٠١-٠١", " 2026-01-05"]


@pytest.mark.parametrize("value", BAD_DATES)
@pytest.mark.parametrize("name", ["from", "to"])
def test_entries_reject_anything_but_iso_dates(storage, name, value):
    response = call("/v1/entries", make_ctx(storage), {name: [value]})
    assert (response.status, response.body["error"]["code"]) == (400, "invalid_date")


def test_entries_reject_a_reversed_range(storage):
    response = call("/v1/entries", make_ctx(storage),
                    {"from": ["2026-02-01"], "to": ["2026-01-01"]})
    assert (response.status, response.body["error"]["code"]) == (400, "invalid_range")


def test_entries_reject_unknown_parameters(storage):
    response = call("/v1/entries", make_ctx(storage), {"form": ["2026-01-01"]})
    assert (response.status, response.body["error"]["code"]) == (400, "unknown_parameter")


def test_entries_reject_repeated_parameters(storage):
    response = call("/v1/entries", make_ctx(storage),
                    {"from": ["2026-01-01", "2026-01-02"]})
    assert (response.status, response.body["error"]["code"]) == (400, "duplicate_parameter")


def test_error_message_does_not_echo_unbounded_input(storage):
    response = call("/v1/entries", make_ctx(storage), {"x" * 5000: ["1"]})
    assert len(response.body["error"]["message"]) < 200


# --- /v1/entries/{date} --------------------------------------------------------

def test_single_entry_returns_the_day(storage):
    seed(storage)

    response = call("/v1/entries/2026-01-20", make_ctx(storage))

    assert response.status == 200
    assert response.body == {
        "date": "2026-01-20",
        "slots": [{"start": "09:00", "end": "17:00", "pause": 30, "kategorie": ""}],
    }


def test_single_entry_missing_day_is_404(storage):
    response = call("/v1/entries/2026-03-01", make_ctx(storage))
    assert (response.status, response.body["error"]["code"]) == (404, "not_found")


def test_single_entry_tombstone_is_404(storage):
    seed(storage)
    storage.delete("2026-01-20")
    assert call("/v1/entries/2026-01-20", make_ctx(storage)).status == 404


@pytest.mark.parametrize("value", ["2026-02-30", "20260105", "2026-W01-1", "heute",
                                   "٢٠٢٦-٠١-٠١", "2026-1-5"])
def test_single_entry_rejects_bad_dates_with_400(storage, value):
    response = call(f"/v1/entries/{value}", make_ctx(storage))
    assert (response.status, response.body["error"]["code"]) == (400, "invalid_date")


def test_single_entry_takes_no_query(storage):
    seed(storage)
    response = call("/v1/entries/2026-01-20", make_ctx(storage), {"from": ["2026-01-01"]})
    assert (response.status, response.body["error"]["code"]) == (400, "unknown_parameter")


# --- Routing, Methoden, Scope -----------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/v1", "/v1/", "/v1/status/", "//v1/status",
                                  "/v1/statu", "/v1/entries/", "/v1/entries/2026-01-05/x",
                                  "/V1/status", "/v1/status#x", "/v2/status",
                                  "/v1/%73tatus"])
def test_unknown_paths_are_404(storage, path):
    response = call(path, make_ctx(storage))
    assert (response.status, response.body["error"]["code"]) == (404, "not_found")


@pytest.mark.parametrize("path,allow,methods", [
    ("/v1/status", "GET", ["POST", "PUT", "DELETE"]),
    ("/v1/entries", "GET", ["POST", "PUT", "DELETE"]),
    ("/v1/entries/2026-01-05", "DELETE, GET, PUT", ["POST", "PATCH"]),
])
def test_wrong_method_on_a_known_path_is_405_with_allow(storage, path, allow, methods):
    for method in methods:
        response = call(path, make_ctx(storage), method=method)
        assert (response.status, response.body["error"]["code"]) == (405, "method_not_allowed")
        assert response.headers["Allow"] == allow


@pytest.mark.parametrize("method", ["put", "Put", "delete", "get"])
def test_method_names_are_matched_exactly(storage, method):
    response = call("/v1/entries/2026-01-05", make_ctx(storage), method=method)
    assert response.status == 405


def test_a_principal_without_the_scope_is_403(storage):
    stranger = Principal("pixel", frozenset({"mobile-sync"}))

    response = call("/v1/status", make_ctx(storage), principal=stranger)

    assert (response.status, response.body["error"]["code"]) == (403, "insufficient_scope")


def test_unexpected_store_errors_propagate_to_the_server(storage):
    class Broken:
        def get_all(self):
            raise RuntimeError("kaputt")

        def get(self, date_str):
            raise RuntimeError("kaputt")

    ctx = ApiContext(storage=Broken(), settings={}, app_version=lambda: "x")

    with pytest.raises(RuntimeError):
        call("/v1/entries", ctx)


# --- PUT/DELETE /v1/entries/{date} (PR 4) -----------------------------------------------------

DAY = "2026-10-07"
SLOTS_BODY = json.dumps({"slots": [
    {"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}]}).encode()
OTHER_BODY = json.dumps({"slots": [{"start": "09:00", "end": "10:00"}]}).encode()


class TrackingLock:
    """Ein RLock, der mitzählt, ob er gerade gehalten wird."""

    def __init__(self):
        self._lock = threading.RLock()
        self.depth = 0
        self.enters = 0

    def __enter__(self):
        self._lock.acquire()
        self.depth += 1
        self.enters += 1
        return self

    def __exit__(self, *exc):
        self.depth -= 1
        self._lock.release()


class Env:
    """Echter Storage plus Konflikt- und Urlaubsstore, ein Zähler für on_change."""

    def __init__(self, tmp_path, settings=None):
        self.storage = Storage(str(tmp_path / "zeiterfassung.json"), device_id="dev")
        self.conflicts = ConflictsStore(str(tmp_path / "conflicts.json"))
        self.vacations = VacationStore(str(tmp_path / "vacations.json"))
        self.lock = TrackingLock()
        self.changes = 0
        self.ctx = ApiContext(
            storage=self.storage, settings={} if settings is None else settings,
            app_version=lambda: "t", data_lock=self.lock,
            conflicts_store=self.conflicts, vacation_store=self.vacations,
            on_change=self._on_change)

    def _on_change(self):
        self.changes += 1

    def put(self, body, day=DAY, query=None):
        return handle(ApiRequest("PUT", f"/v1/entries/{day}", query or {}, body), self.ctx, LOCAL)

    def delete(self, day=DAY):
        return handle(ApiRequest("DELETE", f"/v1/entries/{day}", {}), self.ctx, LOCAL)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def code(response):
    return response.body["error"]["code"]


def test_put_creates_the_day_and_reports_it(env):
    response = env.put(SLOTS_BODY)

    assert response.status == 200
    assert response.body == {
        "date": DAY,
        "slots": [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}],
        "changed": True, "warnings": []}
    assert env.storage.get(DAY)["slots"] == response.body["slots"]
    assert env.changes == 1


def test_put_replaces_the_whole_day(env):
    env.put(SLOTS_BODY)

    response = env.put(OTHER_BODY)

    assert response.body["changed"] is True
    assert env.storage.get(DAY)["slots"] == [
        {"start": "09:00", "end": "10:00", "pause": 0, "kategorie": ""}]


def test_an_identical_put_neither_saves_nor_notifies(env, monkeypatch):
    env.put(SLOTS_BODY)
    saves = []
    real_save = env.storage.save
    monkeypatch.setattr(env.storage, "save", lambda *a, **k: (saves.append(a), real_save(*a, **k)))
    changes_before = env.changes

    response = env.put(SLOTS_BODY)

    assert response.status == 200 and response.body["changed"] is False
    assert saves == [] and env.changes == changes_before


def test_a_changed_put_saves_exactly_once_and_notifies_once(env, monkeypatch):
    env.put(SLOTS_BODY)
    saves = []
    real_save = env.storage.save
    monkeypatch.setattr(env.storage, "save", lambda *a, **k: (saves.append(a), real_save(*a, **k)))
    changes_before = env.changes

    env.put(OTHER_BODY)

    assert len(saves) == 1 and env.changes == changes_before + 1


def test_the_get_after_a_put_returns_the_same_slots(env):
    env.put(SLOTS_BODY)
    got = handle(ApiRequest("GET", f"/v1/entries/{DAY}", {}), env.ctx, LOCAL)
    assert got.body["slots"] == env.put(SLOTS_BODY).body["slots"]


def test_put_revives_a_tombstoned_day(env):
    env.put(SLOTS_BODY)
    env.storage.delete(DAY)
    assert env.storage.get(DAY) is None

    response = env.put(OTHER_BODY)

    assert response.body["changed"] is True and env.storage.get(DAY) is not None


# --- Warnungen blockieren nie ----------------------------------------------------------------------

def test_warnings_are_reported_and_the_day_is_saved_anyway(tmp_path):
    env = Env(tmp_path, settings={"pause_warning_enabled": True})
    body = json.dumps({"slots": [{"start": "08:00", "end": "16:00"}]}).encode()   # 8 h, keine Pause

    response = env.put(body)

    assert response.status == 200
    assert [x["code"] for x in response.body["warnings"]] == ["pause_requirement"]
    assert env.storage.get(DAY) is not None and env.changes == 1


# --- Sperren ------------------------------------------------------------------------------------------

def test_put_on_a_conflict_day_is_409_and_changes_nothing(env):
    env.conflicts.save_all([{"id": "c", "kind": "entry", "key": DAY, "resolved": False}])

    response = env.put(SLOTS_BODY)

    assert (response.status, code(response)) == (409, "sync_conflict")
    assert env.storage.get(DAY) is None and env.changes == 0


def test_delete_on_a_conflict_day_is_409(env):
    env.storage.save(DAY, [{"start": "08:00", "end": "09:00"}])
    env.conflicts.save_all([{"id": "c", "kind": "entry", "key": DAY, "resolved": False}])

    response = env.delete()

    assert (response.status, code(response)) == (409, "sync_conflict")
    assert env.storage.get(DAY) is not None


def test_put_on_a_vacation_day_is_409_but_a_zero_minute_day_is_allowed(env):
    env.vacations.save(None, "Sommer", "2026-10-07", "2026-10-09",
                       {"2026-10-07": 480, "2026-10-08": 0, "2026-10-09": 480})

    blocked = env.put(SLOTS_BODY, day="2026-10-07")
    allowed = env.put(SLOTS_BODY, day="2026-10-08")

    assert (blocked.status, code(blocked)) == (409, "vacation_day")
    assert allowed.status == 200 and env.storage.get("2026-10-08") is not None
    assert env.storage.get("2026-10-07") is None


def test_checks_and_save_run_under_the_shared_lock(env, monkeypatch):
    held = []
    real_unresolved = env.conflicts.unresolved_entry_keys
    real_save = env.storage.save
    monkeypatch.setattr(env.conflicts, "unresolved_entry_keys",
                        lambda: (held.append(("check", env.lock.depth)), real_unresolved())[1])
    monkeypatch.setattr(env.storage, "save",
                        lambda *a, **k: (held.append(("save", env.lock.depth)), real_save(*a, **k)))

    env.put(SLOTS_BODY)

    assert held == [("check", 1), ("save", 1)]


def test_on_change_runs_after_the_lock_is_released(env):
    depths = []
    env.ctx = ApiContext(storage=env.storage, settings={}, app_version=lambda: "t",
                         data_lock=env.lock, conflicts_store=env.conflicts,
                         vacation_store=env.vacations,
                         on_change=lambda: depths.append(env.lock.depth))

    env.put(SLOTS_BODY)

    assert depths == [0]


def test_an_error_in_on_change_does_not_turn_a_saved_write_into_a_500(tmp_path, caplog):
    env = Env(tmp_path)

    def boom():
        raise RuntimeError("UI weg")

    env.ctx = ApiContext(storage=env.storage, settings={}, app_version=lambda: "t",
                         data_lock=env.lock, on_change=boom)

    with caplog.at_level(logging.ERROR):
        response = env.put(SLOTS_BODY)

    assert response.status == 200 and env.storage.get(DAY) is not None
    assert "on_change" in caplog.text


def test_put_works_without_lock_and_stores(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="dev")
    ctx = ApiContext(storage=storage, settings={}, app_version=lambda: "t")

    response = handle(ApiRequest("PUT", f"/v1/entries/{DAY}", {}, SLOTS_BODY), ctx, LOCAL)

    assert response.status == 200 and storage.get(DAY) is not None


# --- Datum und Body ------------------------------------------------------------------------------------

@pytest.mark.parametrize("day,status,error", [
    ("2026-02-30", 400, "invalid_date"), ("20261007", 400, "invalid_date"), ("heute", 400, "invalid_date"),
    ("1999-12-31", 422, "date_out_of_range"), ("2101-01-01", 422, "date_out_of_range"),
    ("1970-01-01", 422, "date_out_of_range"),
])
def test_put_rejects_bad_dates(env, day, status, error):
    response = env.put(SLOTS_BODY, day=day)
    assert (response.status, code(response)) == (status, error)
    assert env.changes == 0


@pytest.mark.parametrize("body,status", [
    (b"{", 400), (b'{"slots": []}', 422),
    (json.dumps({"slots": [{"start": "8:00", "end": "12:00"}]}).encode(), 422),
])
def test_put_maps_body_errors_to_the_right_status(env, body, status):
    response = env.put(body)
    assert response.status == status
    assert env.storage.get(DAY) is None and env.changes == 0


def test_put_takes_no_query(env):
    response = env.put(SLOTS_BODY, query={"x": ["1"]})
    assert (response.status, code(response)) == (400, "unknown_parameter")


# --- DELETE ----------------------------------------------------------------------------------------------------

def test_delete_removes_the_day_and_leaves_a_tombstone(env):
    env.put(SLOTS_BODY)
    changes_before = env.changes

    response = env.delete()

    assert response.status == 200 and response.body == {"date": DAY, "deleted": True}
    assert env.storage.get(DAY) is None
    assert env.storage.get_all_raw()[DAY]["deleted"] is True
    assert env.changes == changes_before + 1


def test_delete_of_a_missing_or_tombstoned_day_is_404(env):
    assert env.delete().status == 404
    env.put(SLOTS_BODY)
    env.delete()
    changes = env.changes

    again = env.delete()

    assert (again.status, code(again)) == (404, "not_found") and env.changes == changes


def test_delete_with_a_bad_date_is_400(env):
    assert (env.delete("2026-02-30").status, code(env.delete("2026-02-30"))) == (400, "invalid_date")


def test_delete_runs_under_the_lock(env, monkeypatch):
    env.put(SLOTS_BODY)
    seen = []
    real_delete = env.storage.delete
    monkeypatch.setattr(env.storage, "delete",
                        lambda *a, **k: (seen.append(env.lock.depth), real_delete(*a, **k)))

    env.delete()

    assert seen == [1]



# --- Review PR 4 -----------------------------------------------------------------------------------

def test_put_takes_the_lock_exactly_once_so_check_and_save_are_one_critical_section(env):
    # Zwei getrennte `with`-Blöcke (Prüfen / Speichern) wären ein echtes TOCTOU —
    # die Tiefe am Check und am Save wäre in beiden Fällen 1.
    env.put(SLOTS_BODY)
    assert env.lock.enters == 1


def test_delete_takes_the_lock_exactly_once(env):
    env.put(SLOTS_BODY)
    before = env.lock.enters
    env.delete()
    assert env.lock.enters - before == 1


def test_delete_on_a_vacation_day_is_allowed(env):
    # Löschen ist der Weg aus der Sackgasse: nur PUT wird am Urlaubstag gesperrt.
    env.vacations.save(None, "Sommer", "2026-10-07", "2026-10-09", {
        "2026-10-07": 480, "2026-10-08": 480, "2026-10-09": 480})
    env.storage.save("2026-10-07", [{"start": "08:00", "end": "09:00"}])   # Altlast

    response = env.delete("2026-10-07")

    assert response.status == 200 and env.storage.get("2026-10-07") is None


def test_a_lone_surrogate_is_422_and_leaves_the_store_usable(env):
    bad = b'{"slots": [{"start": "08:00", "end": "09:00", "kategorie": "A\\ud83d"}]}'

    response = env.put(bad)

    assert (response.status, code(response)) == (422, "invalid_category")
    env.storage.save("2026-10-09", [{"start": "08:00", "end": "09:00"}])   # darf nicht werfen
    assert env.storage.get(DAY) is None and env.changes == 0


def test_a_failed_disk_write_is_not_remembered_as_saved(env, monkeypatch):
    real = env.storage._save_to_disk
    monkeypatch.setattr(env.storage, "_save_to_disk",
                        lambda: (_ for _ in ()).throw(OSError(28, "voll")))
    with pytest.raises(OSError):
        env.put(SLOTS_BODY)
    assert env.changes == 0 and env.storage.get(DAY) is None
    monkeypatch.setattr(env.storage, "_save_to_disk", real)

    retry = env.put(SLOTS_BODY)

    # Ohne Rollback stünde der Tag im Speicher: der Retry wäre „unverändert“ und
    # würde nie auf die Platte geschrieben.
    assert retry.status == 200 and retry.body["changed"] is True and env.changes == 1


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_writes_are_refused_while_the_service_shuts_down(tmp_path, method):
    env = Env(tmp_path)
    env.put(SLOTS_BODY)
    changes = env.changes
    env.ctx = ApiContext(storage=env.storage, settings={}, app_version=lambda: "t",
                         data_lock=env.lock, closing=lambda: True,
                         on_change=env._on_change)
    request = ApiRequest(method, f"/v1/entries/{DAY}", {}, OTHER_BODY)

    response = handle(request, env.ctx, LOCAL)

    assert (response.status, code(response)) == (503, "shutting_down")
    assert env.storage.get(DAY)["slots"][0]["end"] == "12:00" and env.changes == changes
    assert handle(ApiRequest("GET", f"/v1/entries/{DAY}", {}), env.ctx, LOCAL).status == 200


def test_odd_stored_data_cannot_block_a_put_through_the_warnings(tmp_path):
    settings = {"werkstudent_limit_enabled": True, "werkstudent_limit_start": "2026-01-01",
                "werkstudent_limit_end": "2026-12-31", "werkstudent_limit_max_hours": 20}
    env = Env(tmp_path, settings=settings)
    env.storage.save("2026-10-08", [{"start": "08:00", "end": "17:00", "pause": None}])

    response = env.put(SLOTS_BODY, day="2026-10-09")

    assert response.status == 200 and env.storage.get("2026-10-09") is not None


# --- Auswertungen: /v1/summary, /v1/categories, /v1/holidays ---------------------------

def get(env, path, query=None, principal=LOCAL):
    return handle(ApiRequest("GET", path, query or {}), env.ctx, principal)


def seed_week(env):
    env.storage.save("2026-01-05", [ist_slot("08:00", "12:00", 0, "Projekt")])
    env.storage.save("2026-01-06", [ist_slot("09:00", "17:00", 30, "Büro")])


def test_week_summary_has_the_range_the_totals_and_the_label(env):
    seed_week(env)

    response = get(env, "/v1/summary/week/2026-W02")

    assert response.status == 200
    body = response.body
    assert body["week"] == "2026-W02"
    assert (body["from"], body["to"]) == ("2026-01-05", "2026-01-11")
    assert body["total_minutes"] == 240 + 450
    assert [d["date"] for d in body["days"]] == ["2026-01-05", "2026-01-06"]
    assert [(w["iso_year"], w["iso_week"]) for w in body["weeks"]] == [(2026, 2)]


def test_month_summary_covers_the_whole_month(env):
    seed_week(env)
    env.storage.save("2026-02-02", [ist_slot("08:00", "09:00")])

    response = get(env, "/v1/summary/month/2026-01")

    assert response.status == 200
    assert response.body["month"] == "2026-01"
    assert (response.body["from"], response.body["to"]) == ("2026-01-01", "2026-01-31")
    assert response.body["total_minutes"] == 690          # Februar zählt nicht
    assert len(response.body["weeks"]) == 5


def test_summary_total_matches_the_entries_route(env):
    seed_week(env)
    entries = get(env, "/v1/entries", {"from": ["2026-01-01"], "to": ["2026-01-31"]}).body["entries"]
    by_hand = sum(
        (int(s["end"][:2]) * 60 + int(s["end"][3:])) - (int(s["start"][:2]) * 60 + int(s["start"][3:])) - s["pause"]
        for e in entries.values() for s in e["slots"])
    assert get(env, "/v1/summary/month/2026-01").body["total_minutes"] == by_hand


def test_summary_includes_the_vacation_of_the_store(env):
    env.vacations.save(None, "Sommer", "2026-01-12", "2026-01-13",
                       {"2026-01-12": 480, "2026-01-13": 480})
    env.storage.save("2026-01-12", [ist_slot("08:00", "10:00")])

    body = get(env, "/v1/summary/month/2026-01").body

    assert body["total_minutes"] == 120
    assert body["vacation_minutes"] == 480 - 120 + 480          # 12.01. um die Arbeitszeit gekappt
    assert body["payable_minutes"] == 120 + body["vacation_minutes"]
    assert [d["date"] for d in body["vacation_capped_days"]] == ["2026-01-12"]


def test_summary_without_a_vacation_store_has_no_vacation(tmp_path):
    ctx = make_ctx(Storage(str(tmp_path / "z.json"), device_id="d"))
    body = handle(ApiRequest("GET", "/v1/summary/month/2026-01", {}), ctx, LOCAL).body
    assert (body["vacation_minutes"], body["payable_minutes"]) == (0, 0)


def test_summary_reports_the_weekly_limit_and_pause_warnings(tmp_path):
    env = Env(tmp_path, {
        "werkstudent_limit_enabled": True, "werkstudent_limit_start": "2026-01-01",
        "werkstudent_limit_end": "2026-12-31", "werkstudent_limit_max_hours": 5.0,
        "pause_warning_enabled": True})
    env.storage.save("2026-01-05", [ist_slot("08:00", "15:00", 0)])

    body = get(env, "/v1/summary/week/2026-W02").body

    assert body["weeks"] == [{"iso_year": 2026, "iso_week": 2, "total_minutes": 420,
                              "limit_minutes": 300, "exceeded": True}]
    assert body["pause_warnings"] == [{"date": "2026-01-05", "worked_minutes": 420,
                                       "actual_pause_minutes": 0, "required_pause_minutes": 30}]


@pytest.mark.parametrize("path,error", [
    ("/v1/summary/week/2026-W1", "invalid_week"), ("/v1/summary/week/2025-W53", "invalid_week"),
    ("/v1/summary/week/2026-01", "invalid_week"), ("/v1/summary/week/abc", "invalid_week"),
    ("/v1/summary/month/2026-13", "invalid_month"), ("/v1/summary/month/2026-W02", "invalid_month"),
    ("/v1/summary/month/2026-1", "invalid_month"), ("/v1/summary/month/9999-01", "invalid_month"),
    ("/v1/holidays/26", "invalid_year"), ("/v1/holidays/2026-01", "invalid_year"),
    ("/v1/holidays/abcd", "invalid_year"),
])
def test_malformed_summary_paths_are_400(env, path, error):
    response = get(env, path)
    assert (response.status, code(response)) == (400, error)


@pytest.mark.parametrize("path", [
    "/v1/summary/month/1999-12", "/v1/summary/month/2101-01", "/v1/summary/week/1999-W52",
    "/v1/summary/week/2101-W01", "/v1/holidays/1999", "/v1/holidays/2101",
])
def test_years_outside_2000_to_2100_are_422(env, path):
    response = get(env, path)
    assert (response.status, code(response)) == (422, "date_out_of_range")


@pytest.mark.parametrize("path", [
    "/v1/summary/month/2000-01", "/v1/summary/month/2100-12", "/v1/summary/week/2000-W01",
    "/v1/summary/week/2100-W01", "/v1/holidays/2000", "/v1/holidays/2100",
])
def test_the_edges_of_the_year_range_are_accepted(env, path):
    assert get(env, path).status == 200


@pytest.mark.parametrize("path", [
    "/v1/summary/week/2026-W02", "/v1/summary/month/2026-01", "/v1/categories",
    "/v1/holidays/2026",
])
def test_summary_routes_take_no_query(env, path):
    response = get(env, path, {"x": ["1"]})
    assert (response.status, code(response)) == (400, "unknown_parameter")


@pytest.mark.parametrize("path", [
    "/v1/summary/week/2026-W02", "/v1/summary/month/2026-01", "/v1/categories",
    "/v1/holidays/2026",
])
def test_summary_routes_are_read_only(env, path):
    response = handle(ApiRequest("PUT", path, {}, b"{}"), env.ctx, LOCAL)
    assert response.status == 405 and response.headers["Allow"] == "GET"


@pytest.mark.parametrize("path", [
    "/v1/summary/week/2026-W02", "/v1/summary/month/2026-01", "/v1/categories",
    "/v1/holidays/2026",
])
def test_summary_routes_need_the_local_scope(env, path):
    nobody = Principal("x", frozenset())
    assert get(env, path, principal=nobody).status == 403


def test_reading_a_summary_takes_no_data_lock_and_changes_nothing(env):
    seed_week(env)
    before = env.storage.get_all()

    get(env, "/v1/summary/month/2026-01")
    get(env, "/v1/summary/week/2026-W02")

    assert (env.lock.enters, env.changes) == (0, 0)
    assert env.storage.get_all() == before


def test_categories_come_from_the_settings(tmp_path):
    env = Env(tmp_path, {"categories": ["Projekt", "", "Büro", "Projekt"]})
    assert get(env, "/v1/categories").body == {"categories": ["Projekt", "Büro"]}


def test_categories_default_to_an_empty_list(env):
    assert get(env, "/v1/categories").body == {"categories": []}


def test_holidays_use_the_state_of_the_settings(tmp_path):
    env = Env(tmp_path, {"state": "BY"})
    body = get(env, "/v1/holidays/2026").body
    assert (body["year"], body["state"]) == (2026, "BY")
    assert {"date": "2026-01-01", "name": "Neujahr"} in body["holidays"]


def test_holidays_without_a_state_are_empty_and_say_so(env):
    assert get(env, "/v1/holidays/2026").body == {"year": 2026, "state": "", "holidays": []}
