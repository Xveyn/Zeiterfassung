# tests/test_mobile_contract.py
"""Vertrag zwischen Desktop (Python) und Handy-PWA (JavaScript).

Die Beispiele unter `pwa/test/fixtures/` lesen **beide** Seiten: die JS-Tests
(`pwa/test/*.test.js`) und dieser Test. Wer eine Regel auf einer Seite ändert, ohne die
andere nachzuziehen, macht eine der beiden Seiten rot — das ist der Zweck.
"""
import datetime
import json
import pathlib

import pytest

from src.api_entry_write import WriteError, parse_slots
from src.time_utils import calculate_hours, hours_to_minutes, validate_slots

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "pwa" / "test" / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- Minuten und Validierung ----------------------------------------------------------------

@pytest.mark.parametrize("row", load("minutes-cases.json")["slot_minutes"],
                         ids=lambda r: f"{r['start']}-{r['end']}-p{r['pause']}")
def test_slot_minutes_match_the_python_calculation(row):
    hours = calculate_hours(row["start"], row["end"], row["pause"])
    assert hours_to_minutes(hours) == row["minutes"]


@pytest.mark.parametrize("row", load("minutes-cases.json")["validation"], ids=lambda r: r["name"])
def test_validation_matches_the_server(row):
    try:
        parse_slots(row["slots"])
        accepted = True
    except WriteError:
        accepted = False
    assert accepted == row["ok"]


@pytest.mark.parametrize(
    "row", [r for r in load("minutes-cases.json")["validation"] if "message" in r],
    ids=lambda r: r["name"])
def test_time_rule_messages_are_word_for_word_those_of_validate_slots(row):
    ok, message = validate_slots(row["slots"])
    assert not ok and message == row["message"]


@pytest.mark.parametrize("row", load("minutes-cases.json")["iso_weeks"], ids=lambda r: r["date"])
def test_iso_weeks_match(row):
    year, week, _weekday = datetime.date.fromisoformat(row["date"]).isocalendar()
    assert (year, week) == (row["year"], row["week"])


# --- Koppeln: Code, Adresse, Link -------------------------------------------------------------

from src import mobile_pairing, netinfo  # noqa: E402
from src.mobile_service import STATE_RUNNING, MobileService, MobileStatus  # noqa: E402


@pytest.mark.parametrize("row", load("pairing-cases.json")["codes"], ids=lambda r: repr(r["raw"]))
def test_code_normalisation_matches(row):
    assert mobile_pairing.normalize_code(row["raw"]) == row["code"]


@pytest.mark.parametrize("row", load("pairing-cases.json")["lan_addresses"],
                         ids=lambda r: repr(r["address"]))
def test_the_lan_address_rule_matches(row):
    assert netinfo.is_lan_address(row["address"]) is row["lan"]


@pytest.mark.parametrize(
    "row", [r for r in load("pairing-cases.json")["fragments"] if r.get("python_link")],
    ids=lambda r: r["hash"])
def test_the_link_the_desktop_builds_is_the_fragment_the_pwa_parses(row):
    service = MobileService.__new__(MobileService)           # nur pair_link, ohne Server
    service._status = MobileStatus(STATE_RUNNING, row["host"], row["port"])

    link = service.pair_link(row["code"])

    assert link is not None and "#" in link
    assert "#" + link.split("#", 1)[1] == row["hash"]


# --- Sync, Koppeln und Fehlercodes ------------------------------------------------------------

import re  # noqa: E402

from src import mobile_crypto as mc  # noqa: E402
from src import mobile_routes, mobile_sync  # noqa: E402
from src.api_auth import ANONYMOUS  # noqa: E402
from src.api_routes import ApiRequest  # noqa: E402
from tests import test_mobile_routes as mr  # noqa: E402

DATE_KEY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def shape(value):
    """Die Form eines JSON-Werts: Schlüssel und Typen, nicht die Werte. Eine Liste hat die Form
    ihres ersten Elements, ein Objekt mit lauter Datumsschlüsseln die seines ersten Werts."""
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    if isinstance(value, dict):
        if value and all(DATE_KEY.match(key) for key in value):
            return {"<date>": shape(next(iter(value.values())))}
        return {key: shape(value[key]) for key in sorted(value)}
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    return "string"


def test_the_request_example_is_accepted_by_the_server_parser():
    example = load("sync-request.json")

    parsed = mobile_sync.parse_request(json.dumps(example).encode(), now=example["client_time"])

    assert sorted(parsed.entries) == sorted(example["entries"])


def test_the_response_example_has_the_shape_the_server_really_sends(tmp_path):
    example = load("sync-response.json")
    env = mr.make_env(tmp_path)
    env.ctx.settings.set("categories", ["Projekt", "Intern"])
    _record, token = mr.add_device(env, mr.PHONE, "Pixel")
    # Der Desktop kennt 2026-10-05 anders: der Erstabgleich macht daraus einen Konflikt.
    env.ctx.storage.apply_merge({"2026-10-05": {
        "slots": [{"start": "09:00", "end": "13:00", "pause": 0, "kategorie": ""}],
        "modified_at": "2026-10-07T20:00:00Z", "device_id": "DESK", "deleted": False}})
    entries = {"2026-10-07": mr.day(), "2026-10-06": mr.day(slots=(), deleted=True),
               "2026-10-05": mr.day(modified_at="2026-10-07T18:30:00Z")}

    raw = mr.call(env, "POST", "/v1/sync", body=mr.sync_body(env, entries), token=token)
    response = mr.opened(env, raw)

    assert raw.status == 200
    assert set(raw.body) == {"v", "seq", "n", "c"}                      # auf dem Draht nur der Umschlag
    assert shape(response.body) == shape(example)
    assert response.body["protocol"] == example["protocol"] == 2


def test_the_sync_request_example_has_the_shape_the_phone_sends(tmp_path):
    example = load("sync-request.json")
    env = mr.make_env(tmp_path)
    mr.add_device(env)
    sent = mr.sync_doc(env, {"2026-10-07": mr.day(), "2026-10-06": mr.day(slots=(), deleted=True)})
    sent["last_pull_at"] = example["last_pull_at"]

    assert set(sent) == set(example) and sent["protocol"] == example["protocol"] == 2


def test_the_pair_examples_have_the_shape_the_server_expects_and_sends(tmp_path):
    request = load("pair-request.json")
    example = load("pair-response.json")
    env = mr.make_env(tmp_path)
    code = mobile_pairing.normalize_code(env.ctx.pairing.open())
    phone = mr.Phone(request["device_id"], request["device_name"])
    envelope = phone.pair_request(code)
    request_key, _ = mc.pair_keys(code)
    plain = json.loads(mc.open_envelope(request_key, envelope, direction="req", method="POST",
                                        path="/v1/pair", device_id="-", seq=1))

    assert shape(plain) == shape(request)                                  # der Klartext der Anfrage
    assert "code" not in plain                                              # der Code ist nur der Schlüssel
    response = mobile_routes.dispatch(
        ApiRequest("POST", "/v1/pair", {}, json.dumps(envelope).encode()), env.ctx, ANONYMOUS)
    answer = phone.open_pair_response(code, response.body)

    assert response.status == 200 and set(response.body) == {"v", "seq", "n", "c"}
    assert shape(answer) == shape(example)
    assert answer["window_days"] == example["window_days"]
    assert answer["protocol"] == example["protocol"] == 2
    assert len(mc.b64d(answer["key"])) == 32 and len(mc.b64d(example["key"])) == 32


def test_the_fixture_errors_include_the_encryption_codes_with_the_expected_repair_flags():
    rows = {(row["status"], row["code"]): row for row in load("errors.json")}
    for status, code, kind, repair in ((400, "decrypt_failed", "crypto", True), (409, "replay", "crypto", True),
                                       (401, "encryption_required", "encryption", True),
                                       (400, "invalid_envelope", "protocol", False),
                                       (503, "key_unavailable", "transient", False)):
        assert rows[(status, code)]["kind"] == kind and rows[(status, code)]["needs_repair"] is repair


_EMITTED = re.compile(
    r'(?:SyncError|_MobileError|AuthResult|error_response)\(\s*(\d{3}),\s*"([a-z_]+)"')
_DENIED = re.compile(r'Denied\("([a-z_]+)"\)')
_SOURCES = ("mobile_routes.py", "mobile_sync.py", "api_server.py", "api_auth.py")


def test_the_pwa_classifies_every_error_the_server_can_send():
    src = pathlib.Path(__file__).resolve().parent.parent / "src"
    emitted = set()
    for name in _SOURCES:
        text = (src / name).read_text(encoding="utf-8")
        emitted |= {(int(status), code) for status, code in _EMITTED.findall(text)}
        if name == "mobile_routes.py":
            emitted |= {(401, code) for code in _DENIED.findall(text)}
    assert emitted, "Parser gescheitert: keine Fehlercodes im Quelltext gefunden"
    emitted = {(status, code) for status, code in emitted if status >= 400}     # (200, "ok") ist kein Fehler
    known = {(row["status"], row["code"]) for row in load("errors.json")}

    missing = sorted(emitted - known)

    assert not missing, (
        f"Der Server kann diese (Status, Code)-Paare senden, die pwa/test/fixtures/errors.json "
        f"nicht kennt — die PWA wüsste nicht, wie sie sie einordnet: {missing}")
