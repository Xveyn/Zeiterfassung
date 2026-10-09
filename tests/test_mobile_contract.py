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
