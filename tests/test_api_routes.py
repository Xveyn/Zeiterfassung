# tests/test_api_routes.py
import pytest

from src.api_auth import SCOPE_LOCAL, Principal
from src.api_routes import API_VERSION, ApiContext, ApiRequest, handle
from src.storage import Storage
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


@pytest.mark.parametrize("path,allow", [("/v1/status", "GET"), ("/v1/entries", "GET"),
                                        ("/v1/entries/2026-01-05", "GET")])
@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_wrong_method_on_a_known_path_is_405_with_allow(storage, path, allow, method):
    response = call(path, make_ctx(storage), method=method)
    assert (response.status, response.body["error"]["code"]) == (405, "method_not_allowed")
    assert response.headers["Allow"] == allow


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
