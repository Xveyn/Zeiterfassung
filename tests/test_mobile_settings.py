import datetime

import pytest

from src import mobile_settings as ms

NOW_DT = datetime.datetime(2026, 10, 13, 12, 0, 0)
STAMP = "2026-10-13T11:00:00Z"


def parse_utc(text):
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def parse(raw):
    return ms.parse_settings(raw, now_dt=NOW_DT, parse_utc=parse_utc,
                             skew_limit=datetime.timedelta(minutes=15))


def block(value, modified_at=STAMP, **extra):
    return {"value": value, "modified_at": modified_at, **extra}


def bad(raw):
    with pytest.raises(ms.SettingsError) as excinfo:
        parse(raw)
    return excinfo.value.message


def test_both_keys_are_parsed_and_the_stamp_is_kept():
    out = parse({"categories": block(["Projekt", "Intern"]),
                 "category_times": block({"Projekt": {"start": "09:00", "end": "17:00", "pause": 30}})})

    assert out == {"categories": {"value": ["Projekt", "Intern"], "modified_at": STAMP},
                   "category_times": {"value": {"Projekt": {"start": "09:00", "end": "17:00", "pause": 30}},
                                      "modified_at": STAMP}}


def test_extra_payload_fields_are_dropped_silently():
    out = parse({"categories": block(["A"], device_id="evil", foo=1)})
    assert out == {"categories": {"value": ["A"], "modified_at": STAMP}}


def test_a_single_key_is_fine_and_an_empty_settings_object_too():
    assert list(parse({"categories": block([])})) == ["categories"]
    assert parse({}) == {}


@pytest.mark.parametrize("key", ["hourly_rate", "gcal_enabled", "device_name", "__proto__", ""])
def test_any_other_key_is_rejected_and_named(key):
    assert f"Einstellung {key}" in bad({key: block("x")})


def test_the_name_in_the_message_is_cut_and_safe():
    message = bad({"x" * 500 + "\ud800": block(1)})
    assert len(message) < 200
    message.encode("utf-8")                                    # kein Surrogat in der Meldung


@pytest.mark.parametrize("raw", [[], "x", 1, None])
def test_settings_must_be_an_object(raw):
    assert "Objekt" in bad(raw)


@pytest.mark.parametrize("payload", [None, [], "x", {"value": ["A"]}, {"modified_at": STAMP}])
def test_a_payload_needs_value_and_modified_at(payload):
    bad({"categories": payload})


@pytest.mark.parametrize("stamp,ok", [
    ("2026-10-13T12:15:00Z", True),        # genau 15 Minuten voraus
    ("2026-10-13T12:15:01Z", False),
    ("gestern", False),
    ("2026-10-13 11:00:00", False),
    (None, False),
])
def test_the_stamp_may_be_at_most_fifteen_minutes_ahead(stamp, ok):
    raw = {"categories": block(["A"], modified_at=stamp)}
    if ok:
        parse(raw)
    else:
        bad(raw)


@pytest.mark.parametrize("value", [
    "x", {"a": 1}, [1], [None], [""], ["  "], ["A", "A"], ["A", " A "],
    ["x" * 101], ["tab\there"], ["lone\ud800"],
    [f"K{i}" for i in range(101)],
])
def test_bad_category_lists_are_rejected(value):
    bad({"categories": block(value)})


def test_names_are_trimmed_and_the_limits_are_inclusive():
    out = parse({"categories": block(["  Projekt  ", "x" * 100, *[f"K{i}" for i in range(98)]])})
    assert out["categories"]["value"][0] == "Projekt"
    assert len(out["categories"]["value"]) == 100


@pytest.mark.parametrize("value", [
    [], "x", {"A": "x"}, {"A": []}, {"": {}}, {"A": {"start": "25:00"}}, {"A": {"start": "9:00"}},
    {"A": {"end": 900}}, {"A": {"pause": -1}}, {"A": {"pause": 1441}}, {"A": {"pause": True}},
    {"A": {"pause": "30"}}, {"A": {"pause": 1.5}}, {"A": {"foo": 1}}, {"A": {"mode": "general"}},
    {"A": {"mode": "per_day", "days": []}}, {"A": {"mode": "per_day", "days": {"xxx": {}}}},
    {"A": {"mode": "per_day", "days": {"mon": {"start": "99:00"}}}},
    {"A": {"mode": "per_day", "days": {"mon": {"foo": 1}}}},
    {"A": {"mode": "per_day", "start": "09:00"}},
])
def test_bad_category_times_are_rejected(value):
    bad({"category_times": block(value)})


def test_general_and_per_day_entries_survive_unchanged():
    times = {
        "Projekt": {"start": "09:00", "end": "17:00", "pause": 45},
        "Nur Pause": {"pause": 0},
        "Support": {"mode": "per_day", "pause": 15,
                    "days": {"fri": {"start": "07:00", "end": "11:00"}, "mon": {"start": "08:00"}}},
        "Tage ohne Zeit": {"mode": "per_day", "days": {}},
    }
    assert parse({"category_times": block(times)})["category_times"]["value"] == times


def test_an_empty_entry_is_dropped_like_the_desktop_dialog_does():
    out = parse({"category_times": block({"A": {}, "B": {"pause": 5}})})
    assert out["category_times"]["value"] == {"B": {"pause": 5}}


def test_times_names_must_be_in_the_same_requests_categories():
    bad({"categories": block(["A"]), "category_times": block({"B": {"pause": 5}})})


def test_check_times_names_against_the_current_desktop_categories():
    ms.check_times_names({"A": {"pause": 5}}, ["A", "B"])
    with pytest.raises(ms.SettingsError) as excinfo:
        ms.check_times_names({"C": {"pause": 5}}, ["A", "B"])
    assert "category_times" in excinfo.value.message and "C" in excinfo.value.message


def test_the_moved_helpers_behave_as_before():
    assert ms.clock("09:30") == "09:30" and ms.clock("9:30") == "" and ms.clock(None) == ""
    assert ms.pause(30) == 30 and ms.pause("45") == 45 and ms.pause(True) is None
    assert ms.pause(1441) is None and ms.pause(-1) is None
    assert ms.clean_category_times({"start": "09:00", "pause": "x", "foo": 1}) == {"start": "09:00"}


def test_category_times_keys_that_collide_after_trimming_are_rejected():
    message = bad({"category_times": block({"A": {"pause": 5}, "  A ": {"pause": 10}})})
    assert "doppelt" in message


def test_a_whitespace_only_category_times_key_is_rejected():
    bad({"category_times": block({"   ": {"pause": 5}})})
