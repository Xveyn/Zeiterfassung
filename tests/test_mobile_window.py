"""Fensterrechnung der Handy-Erfassung (#250): Obergrenze, Wunsch, Mengenlimit."""
import datetime
import json

import pytest

from src import mobile_sync
from src.mobile_sync import fit_window, grant_window, window_cap
from src.settings import DEFAULTS, SYNCED_SETTING_KEYS

TODAY = datetime.date(2026, 10, 8)


def test_the_cap_setting_defaults_to_365_and_stays_device_local():
    assert DEFAULTS["mobile_window_max_days"] == 365
    assert "mobile_window_max_days" not in SYNCED_SETTING_KEYS


@pytest.mark.parametrize("raw,expected", [
    (30, 30), (90, 90), (180, 180), (365, 365),
    (7, 365), (0, 365), (-1, 365), (366, 365), (10_000, 365),   # nicht in der Auswahl
    (True, 365), ("180", 365), ("abc", 365), (None, 365), (3.5, 365),
])
def test_the_cap_comes_only_from_the_offered_values(raw, expected):
    assert window_cap(raw) == expected


@pytest.mark.parametrize("wish,cap,expected", [
    (None, 365, 90),                 # kein Wunsch: Standardfenster
    (None, 30, 30),                  # ... gedeckelt auf die Obergrenze
    (180, 365, 180),
    (365, 365, 365),
    (400, 365, 365),                 # über der Obergrenze: Obergrenze
    (10**9, 365, 365),
    (1, 365, 1),
    (0, 365, 90), (-5, 365, 90),     # ungültig: Standardfenster
    (True, 365, 90), ("365", 365, 90), (3.5, 365, 90), ([], 365, 90),
    (180, 90, 90),                   # Obergrenze 90: nie mehr
])
def test_grant_window_clamps_the_wish_and_never_raises(wish, cap, expected):
    assert grant_window(wish, cap) == expected


def sizes_for(days, size):
    return {(TODAY - datetime.timedelta(days=i)).isoformat(): size for i in range(days + 1)}


def test_fit_window_keeps_the_whole_window_when_it_fits():
    assert fit_window(sizes_for(365, 100), today=TODAY, window_days=365, floor_days=90,
                      budget=100 * 400) == 365


def test_fit_window_ends_before_the_first_day_that_breaks_the_budget():
    # Budget für 10 Tage (heute zählt mit): der 11. Tag zurück passt nicht mehr hinein.
    granted = fit_window(sizes_for(365, 100), today=TODAY, window_days=365, floor_days=1,
                         budget=100 * 10)
    assert granted == 9
    first = (TODAY - datetime.timedelta(days=granted)).isoformat()
    kept = [d for d in sizes_for(365, 100) if first <= d <= TODAY.isoformat()]
    assert sum(100 for _ in kept) <= 100 * 10


def test_fit_window_never_goes_below_the_floor():
    assert fit_window(sizes_for(365, 10_000), today=TODAY, window_days=365, floor_days=90,
                      budget=1) == 90


def test_fit_window_floor_is_capped_by_the_requested_window():
    # Obergrenze 30: das Standardfenster von 90 darf das gewährte Fenster nicht über 30 heben.
    assert fit_window(sizes_for(30, 10_000), today=TODAY, window_days=30, floor_days=min(90, 30),
                      budget=1) == 30


def test_fit_window_ignores_days_outside_the_window_and_in_the_future():
    sizes = {**sizes_for(30, 100), (TODAY + datetime.timedelta(days=3)).isoformat(): 10**9,
             (TODAY - datetime.timedelta(days=200)).isoformat(): 10**9}
    assert fit_window(sizes, today=TODAY, window_days=30, floor_days=1, budget=100 * 40) == 30


def test_fit_window_with_nothing_to_send_keeps_the_window():
    assert fit_window({}, today=TODAY, window_days=180, floor_days=90, budget=1) == 180


def test_the_constants_match_the_spec():
    assert mobile_sync.WINDOW_DAYS == 90
    assert mobile_sync.HARD_MAX_WINDOW_DAYS == 365
    assert mobile_sync.WINDOW_CAP_CHOICES == (30, 90, 180, 365)
    assert mobile_sync.MAX_RESPONSE_ENTRY_BYTES == 768 * 1024


def _body(**over):
    doc = {"protocol": 2, "client_time": "2026-10-08T12:00:00Z", "last_pull_at": "", "entries": {}}
    doc.update(over)
    return json.dumps(doc).encode()


@pytest.mark.parametrize("sent,expected", [
    (180, 180), (365, 365), (1, 1),
    (None, None), (0, None), (-3, None), (True, None), ("365", None), (2.5, None), ([], None),
])
def test_parse_request_reads_the_window_wish_tolerantly(sent, expected):
    over = {} if sent is None else {"window_days": sent}
    parsed = mobile_sync.parse_request(_body(**over), now="2026-10-08T12:00:00Z")
    assert parsed.window_days == expected


def test_a_request_without_the_wish_is_still_valid():
    parsed = mobile_sync.parse_request(_body(), now="2026-10-08T12:00:00Z")
    assert parsed.window_days is None


def test_fit_window_survives_a_date_key_that_is_not_a_calendar_day():
    # Schlüssel wie „2026-09-31“ passen auf das Datumsmuster, sind aber kein Kalendertag (Fremddaten,
    # Handbearbeitung). Der alte Antwortbau war rein textuell und vertrug sie: ein Fehler wäre ein 500
    # bei jedem Abgleich.
    sizes = {"2026-09-31": 800 * 1024, "2026-10-07": 10}

    granted = fit_window(sizes, today=TODAY, window_days=365, floor_days=90, budget=768 * 1024)

    assert 90 <= granted <= 365
