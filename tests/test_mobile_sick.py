# tests/test_mobile_sick.py
import datetime
import pathlib
import re

import pytest

from src import mobile_sick
from src.mobile_sick import MAX_SICK_DAYS, SickError
from src.mobile_sync import CLOCK_SKEW_LIMIT, _parse_utc

NOW_DT = datetime.datetime(2026, 10, 8, 12, 0, 0)
STAMP = "2026-10-07T18:30:00Z"


def parse(raw):
    return mobile_sick.parse_sick(raw, now_dt=NOW_DT, parse_utc=_parse_utc,
                                  skew_limit=CLOCK_SKEW_LIMIT)


def rejected(raw):
    with pytest.raises(SickError) as excinfo:
        parse(raw)
    return excinfo.value.message


def live(minutes=None, modified_at=STAMP):
    day = {"modified_at": modified_at, "deleted": False}
    if minutes is not None:
        day["minutes"] = minutes
    return day


def tomb(modified_at=STAMP):
    return {"modified_at": modified_at, "deleted": True}


# --- parse_sick ------------------------------------------------------------------------------------

def test_a_live_day_without_minutes_and_a_tombstone_are_parsed():
    parsed = parse({"2026-10-05": live(), "2026-10-04": tomb()})

    assert parsed == {"2026-10-05": {"modified_at": STAMP, "deleted": False},
                      "2026-10-04": {"modified_at": STAMP, "deleted": True}}


def test_minutes_are_kept_when_the_phone_sends_them():
    assert parse({"2026-10-05": live(0)})["2026-10-05"]["minutes"] == 0
    assert parse({"2026-10-05": live(1440)})["2026-10-05"]["minutes"] == 1440


def test_an_empty_section_is_fine():
    assert parse({}) == {}


@pytest.mark.parametrize("raw", [None, [], "x", 5])
def test_a_section_that_is_no_object_is_rejected(raw):
    assert "sick" in rejected(raw)


def test_more_than_the_limit_is_rejected():
    days = {(datetime.date(2026, 1, 1) + datetime.timedelta(days=i)).isoformat(): live()
            for i in range(MAX_SICK_DAYS + 1)}
    assert str(MAX_SICK_DAYS) in rejected(days)
    days.popitem()
    assert len(parse(days)) == MAX_SICK_DAYS


def test_the_phone_sends_exactly_as_many_sick_days_as_the_desktop_accepts():
    # Mehr lehnte der Desktop als ganze Anfrage ab, weniger ließe nicht übertragene Tage länger liegen.
    store = pathlib.Path(__file__).resolve().parent.parent / "pwa" / "store.js"
    match = re.search(r"^const MAX_SICK_PER_REQUEST = (\d+);", store.read_text(encoding="utf-8"), re.MULTILINE)
    assert match is not None, "Parser gescheitert: MAX_SICK_PER_REQUEST fehlt in pwa/store.js"
    assert int(match.group(1)) == MAX_SICK_DAYS


@pytest.mark.parametrize("minutes", [-1, 1441, 480.0, "480", True, None, [480]])
def test_bad_minutes_are_rejected_with_the_day_in_front(minutes):
    message = rejected({"2026-10-05": {"modified_at": STAMP, "deleted": False, "minutes": minutes}})
    assert message.startswith("Krankheit 2026-10-05: ")


@pytest.mark.parametrize("day", [
    {"modified_at": STAMP},                                             # deleted fehlt
    {"modified_at": STAMP, "deleted": "nein"},
    {"modified_at": STAMP, "deleted": 1},
    {"deleted": False},                                                 # modified_at fehlt
    {"modified_at": "2026-10-07 18:30:00", "deleted": False},
    {"modified_at": "٢026-10-07T18:30:00Z", "deleted": False},
    {"modified_at": STAMP, "deleted": False, "device_id": "evil"},     # unbekanntes Feld
    {"modified_at": STAMP, "deleted": False, "slots": []},
    5, None, [], "x",
])
def test_a_malformed_day_is_rejected_with_the_day_in_front(day):
    assert rejected({"2026-10-05": day}).startswith("Krankheit 2026-10-05: ")


@pytest.mark.parametrize("modified_at,ok", [
    ("2026-10-08T12:15:00Z", True), ("2026-10-08T12:15:01Z", False),
])
def test_a_stamp_more_than_fifteen_minutes_ahead_is_rejected(modified_at, ok):
    raw = {"2026-10-05": live(modified_at=modified_at)}
    if ok:
        assert parse(raw)["2026-10-05"]["modified_at"] == modified_at
    else:
        assert rejected(raw).startswith("Krankheit 2026-10-05: ")


@pytest.mark.parametrize("key", [
    "2026-02-30", "20261005", "2026-10-5", "٢٠٢٦-١٠-٠٥", "1999-12-31", "2101-01-01", "", "\ud800",
    "x" * 5000,
])
def test_a_bad_date_is_rejected_and_the_message_stays_short_and_writable(key):
    message = rejected({key: live()})
    assert message.startswith("Krankheit ")
    message.encode("utf-8")                              # nie ein Surrogat in der Antwort
    assert len(message) < 200


def test_an_unknown_field_is_named_without_echoing_long_text():
    message = rejected({"2026-10-05": {**live(), "x" * 500: 1}})
    assert message.startswith("Krankheit 2026-10-05: ") and len(message) < 200


# --- days_to_compute -------------------------------------------------------------------------------

def _rec(minutes, *, deleted=False, modified_at="2026-10-01T10:00:00Z", device="DESK"):
    return {"minutes": minutes, "modified_at": modified_at, "device_id": device, "deleted": deleted}


def test_every_live_day_without_minutes_is_computed_even_where_the_desktop_has_one():
    # Die Folgen bilden sich wie im Dialog über den ganzen gemeldeten Zeitraum; ein lebender
    # Desktop-Tag behält trotzdem seine Minuten (`fill_minutes`, `phone_records`).
    parsed = parse({"2026-10-05": live(), "2026-10-06": live(), "2026-10-07": live(300),
                    "2026-10-02": tomb(), "2026-10-01": live()})

    assert mobile_sick.days_to_compute(parsed) == ["2026-10-01", "2026-10-05", "2026-10-06"]


# --- fill_minutes ----------------------------------------------------------------------------------

class FakeFill:
    """Liefert je Tag `value`, merkt sich die Aufrufe samt den übergebenen Krankheitstagen."""

    def __init__(self, value=450):
        self.value = value
        self.calls = []

    def __call__(self, first, last, sick_days):
        self.calls.append((first, last, dict(sick_days)))
        days = {}
        day = datetime.date.fromisoformat(first)
        while day.isoformat() <= last:
            days[day.isoformat()] = self.value
            day += datetime.timedelta(days=1)
        return days


def test_runs_are_filled_in_date_order_and_later_runs_see_the_earlier_ones():
    parsed = parse({"2026-10-02": live(), "2026-09-28": live(), "2026-09-29": live(),
                    "2026-10-01": live()})
    fill = FakeFill()

    minutes = mobile_sick.fill_minutes(parsed, desktop_raw={"2026-07-01": _rec(300)}, fill=fill)

    assert minutes == {"2026-09-28": 450, "2026-09-29": 450, "2026-10-01": 450, "2026-10-02": 450}
    assert [(first, last) for first, last, _ in fill.calls] == [
        ("2026-09-28", "2026-09-29"), ("2026-10-01", "2026-10-02")]
    assert fill.calls[0][2] == {"2026-07-01": 300}
    assert fill.calls[1][2] == {"2026-07-01": 300, "2026-09-28": 450, "2026-09-29": 450}


def test_a_live_desktop_day_keeps_its_minutes_inside_a_run_and_counts_as_sick():
    parsed = parse({"2026-10-05": live(), "2026-10-06": live(), "2026-10-07": live(),
                    "2026-10-09": live(), "2026-10-12": live(120)})
    desktop = {"2026-10-06": _rec(300), "2026-10-08": _rec(0, deleted=True)}
    fill = FakeFill()

    minutes = mobile_sick.fill_minutes(parsed, desktop_raw=desktop, fill=fill)

    assert minutes == {"2026-10-05": 450, "2026-10-06": 300, "2026-10-07": 450, "2026-10-09": 450}
    assert [(first, last) for first, last, _ in fill.calls] == [
        ("2026-10-05", "2026-10-07"), ("2026-10-09", "2026-10-09")]
    # Minuten vom Handy zählen von Anfang an als Krankheit, der Desktop-Tombstone nicht.
    assert fill.calls[0][2] == {"2026-10-06": 300, "2026-10-12": 120}
    assert fill.calls[1][2] == {"2026-10-05": 450, "2026-10-06": 300, "2026-10-07": 450,
                                "2026-10-12": 120}


def test_a_run_of_desktop_days_only_needs_no_fill():
    parsed = parse({"2026-10-06": live(), "2026-10-07": live(60), "2026-10-02": tomb()})
    fill = FakeFill()

    minutes = mobile_sick.fill_minutes(parsed, desktop_raw={"2026-10-06": _rec(300)}, fill=fill)

    assert minutes == {"2026-10-06": 300} and fill.calls == []


# --- prefill_entries / prefill_reservations --------------------------------------------------------

SLOT_A = {"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}
SLOT_B = {"start": "13:00", "end": "17:00", "pause": 30, "kategorie": ""}


def test_the_entries_of_the_same_request_lie_over_the_stored_ones():
    stored = {"2026-10-01": {"slots": [SLOT_A]}, "2026-10-02": {"slots": [SLOT_A]},
              "2026-10-03": {"slots": [SLOT_A]}}
    sent = {"2026-10-02": {"slots": [SLOT_B], "modified_at": STAMP, "deleted": False,
                           "notes": {"13:00": "x"}},
            "2026-10-03": {"slots": [], "modified_at": STAMP, "deleted": True},
            "2026-10-04": {"slots": [SLOT_B], "modified_at": STAMP, "deleted": False},
            "2026-10-05": {"slots": [], "modified_at": STAMP, "deleted": True}}

    entries = mobile_sick.prefill_entries(stored, sent)

    assert entries == {"2026-10-01": {"slots": [SLOT_A]}, "2026-10-02": {"slots": [SLOT_B]},
                       "2026-10-04": {"slots": [SLOT_B]}}
    assert stored["2026-10-03"] == {"slots": [SLOT_A]}               # Eingabe unverändert


def test_phone_reservations_fill_only_days_without_a_live_desktop_reservation():
    stored = {"2026-10-12": {"slots": [SLOT_A]}, "2026-10-13": {"slots": [SLOT_A]}}
    sent = {"2026-10-12": {"slots": [SLOT_B], "modified_at": STAMP, "deleted": False},
            "2026-10-13": {"slots": [], "modified_at": STAMP, "deleted": True},
            "2026-10-14": {"slots": [SLOT_B], "modified_at": STAMP, "deleted": False},
            "2026-10-15": {"slots": [], "modified_at": STAMP, "deleted": True}}

    reservations = mobile_sick.prefill_reservations(stored, sent)

    # Der Stand vor `merge_phone` gilt; ein Tombstone des Handys nimmt nichts heraus.
    assert reservations == {"2026-10-12": {"slots": [SLOT_A]}, "2026-10-13": {"slots": [SLOT_A]},
                            "2026-10-14": {"slots": [SLOT_B]}}
    assert "2026-10-14" not in stored


# --- keep_phone_deletions --------------------------------------------------------------------------

WATERMARK = "2026-10-08T10:00:00Z"


def test_a_phone_tombstone_stripped_over_a_live_desktop_day_is_put_back_at_the_watermark():
    tombstone = _rec(0, deleted=True, modified_at=STAMP, device="phone-0001")
    merged = {"2026-10-06": _rec(300)}

    kept = mobile_sick.keep_phone_deletions(
        merged, records={"2026-10-05": tombstone, "2026-10-06": _rec(120, device="phone-0001")},
        desktop_raw={"2026-10-05": _rec(300, modified_at="2026-09-01T10:00:00Z"),
                     "2026-10-06": _rec(300)},
        watermark=WATERMARK)

    assert kept == {"2026-10-05": {**tombstone, "modified_at": WATERMARK},
                    "2026-10-06": _rec(300)}
    assert merged == {"2026-10-06": _rec(300)}                        # Eingabe unverändert


def test_a_phone_tombstone_above_the_watermark_keeps_its_stamp():
    tombstone = _rec(0, deleted=True, modified_at="2026-10-08T11:00:00Z", device="phone-0001")

    kept = mobile_sick.keep_phone_deletions(
        {}, records={"2026-10-05": tombstone}, desktop_raw={"2026-10-05": _rec(300)},
        watermark=WATERMARK)

    assert kept == {"2026-10-05": tombstone}


def test_nothing_is_put_back_without_a_live_desktop_day():
    tombstone = _rec(0, deleted=True, modified_at=STAMP, device="phone-0001")
    records = {"2026-10-03": tombstone, "2026-10-04": tombstone, "2026-10-05": tombstone}
    desktop = {"2026-10-04": _rec(0, deleted=True),
               "2026-10-05": {"minutes": "viel", "modified_at": "x", "device_id": "D",
                              "deleted": False}}

    assert mobile_sick.keep_phone_deletions({}, records=records, desktop_raw=desktop,
                                            watermark=WATERMARK) == {}


# --- phone_records ---------------------------------------------------------------------------------

def test_phone_records_follow_the_rules_for_minutes_stamps_and_device():
    parsed = parse({"2026-10-05": live(), "2026-10-06": live(), "2026-10-07": live(300),
                    "2026-10-08": live(480), "2026-10-02": tomb(),
                    "2026-10-01": live(modified_at="2026-10-08T12:10:00Z")})
    desktop = {"2026-10-06": _rec(420), "2026-10-07": _rec(480), "2026-10-08": _rec(480),
               "2026-10-02": _rec(480)}

    records = mobile_sick.phone_records(
        parsed, desktop_raw=desktop, computed={"2026-10-05": 450, "2026-10-06": 999, "2026-10-01": 0},
        device_id="phone-0001", floor="2026-10-08T09:00:01Z")

    # 06. (ohne Minuten, lebender Desktop-Tag) und 08. (dieselben Minuten) sind keine Änderung:
    # sie fehlen, der Desktop-Datensatz behält Stempel und Gerät (wie `SickStore._put_days`).
    assert records == {
        # ohne Minuten, kein Desktop-Tag: die Vorbelegung
        "2026-10-05": _rec(450, modified_at="2026-10-08T09:00:01Z", device="phone-0001"),
        # andere Minuten vom Handy gewinnen
        "2026-10-07": _rec(300, modified_at="2026-10-08T09:00:01Z", device="phone-0001"),
        # Tombstone über einem lebenden Tag: 0 Minuten
        "2026-10-02": _rec(0, deleted=True, modified_at="2026-10-08T09:00:01Z", device="phone-0001"),
        # ein Stempel über dem Boden bleibt
        "2026-10-01": _rec(0, modified_at="2026-10-08T12:10:00Z", device="phone-0001"),
    }


def test_a_phone_tombstone_over_a_desktop_tombstone_is_no_change():
    parsed = parse({"2026-10-02": tomb(), "2026-10-03": tomb()})

    records = mobile_sick.phone_records(
        parsed, desktop_raw={"2026-10-02": _rec(0, deleted=True)}, computed={},
        device_id="phone-0001", floor="2026-10-08T09:00:01Z")

    assert list(records) == ["2026-10-03"]               # unbekannter Tag: geht durch wie bisher


def test_a_tombstone_from_the_phone_carries_zero_minutes_even_if_it_sent_some():
    parsed = parse({"2026-10-02": {"modified_at": STAMP, "deleted": True, "minutes": 300}})

    records = mobile_sick.phone_records(parsed, desktop_raw={}, computed={},
                                        device_id="phone-0001", floor="")

    assert records["2026-10-02"]["minutes"] == 0 and records["2026-10-02"]["deleted"] is True
    assert records["2026-10-02"]["modified_at"] == STAMP


def test_a_desktop_tombstone_does_not_lend_its_minutes():
    parsed = parse({"2026-10-05": live()})
    records = mobile_sick.phone_records(
        parsed, desktop_raw={"2026-10-05": _rec(0, deleted=True)}, computed={"2026-10-05": 450},
        device_id="phone-0001", floor="")
    assert records["2026-10-05"]["minutes"] == 450


# --- build_sick ------------------------------------------------------------------------------------

def test_build_sick_carries_live_days_and_tombstones_in_the_window_plus_sent_days():
    raw = {"2026-07-01": _rec(480),                          # vor dem Fenster
           "2026-07-10": _rec(300),                          # vor dem Fenster, aber gesendet
           "2026-09-01": _rec(480),
           "2026-10-02": _rec(0, deleted=True),
           "2026-10-22": _rec(480),                          # letzter Tag des Fensters
           "2026-10-23": _rec(480)}                          # dahinter

    built = mobile_sick.build_sick(raw, first="2026-07-11",
                                   last="2026-10-22", sent=["2026-07-10", "2026-12-24"])

    assert built == {
        "2026-07-10": {"minutes": 300, "modified_at": "2026-10-01T10:00:00Z", "deleted": False},
        "2026-09-01": {"minutes": 480, "modified_at": "2026-10-01T10:00:00Z", "deleted": False},
        "2026-10-02": {"minutes": 0, "modified_at": "2026-10-01T10:00:00Z", "deleted": True},
        "2026-10-22": {"minutes": 480, "modified_at": "2026-10-01T10:00:00Z", "deleted": False},
    }
    assert list(built) == sorted(built)


def test_build_sick_skips_records_it_cannot_read():
    raw = {"2026-10-01": {"minutes": "viel", "modified_at": "x", "device_id": "D", "deleted": False},
           "kaputt": _rec(480), "2026-10-02": _rec(60)}

    built = mobile_sick.build_sick(raw, first="2026-09-01", last="2026-10-22", sent=())

    assert list(built) == ["2026-10-02"]
