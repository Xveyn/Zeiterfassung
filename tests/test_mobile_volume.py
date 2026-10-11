"""Datenmenge der Sync-Antwort (#250): das Budget schützt vor der Zeitüberschreitung der PWA."""
import datetime
import json

import pytest

from src import mobile_crypto as mc
from src import mobile_sync

TODAY = datetime.date(2026, 10, 8)
NOW = "2026-10-08T12:00:00Z"
DEFAULTS = {"pause": 30, "weekdays": {}, "category_times": {}}
DESKTOP = {"name": "PC", "version": "1.0.0", "platform": "Linux"}
PWA_TIMEOUT_S = 15                      # AbortSignal.timeout in pwa/sync.js
WEAK_WLAN_BYTES_PER_S = 0.6e6 / 8       # 0,6 Mbit/s
MAX_WIRE_BYTES = PWA_TIMEOUT_S * WEAK_WLAN_BYTES_PER_S    # ≈ 1,1 MB


def entries(days, slots, *, every_day=True, category="Projekt"):
    out = {}
    for i in range(days + 1):
        if not every_day and i % 7 >= 5:
            continue
        date = (TODAY - datetime.timedelta(days=i)).isoformat()
        out[date] = {"slots": [{"start": f"{8 + k % 10:02d}:00", "end": f"{9 + k % 10:02d}:00",
                                "pause": 0, "kategorie": category} for k in range(slots)],
                     "modified_at": "2026-10-07T18:30:00Z", "device_id": "DESK", "deleted": False}
    return out


def wire_size(response):
    key = mc.new_device_key()
    _, response_key = mc.device_keys(key)
    envelope = mc.seal(response_key, direction="res", method="POST", path="/v1/sync",
                       device_id="d", seq=1, plaintext=json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return len(json.dumps(envelope).encode())


def build(merged_entries, window_days=365, sent=()):
    return mobile_sync.build_response(
        {"entries": merged_entries, "conflicts": [], "devices": {}}, sent_dates=sent, today=TODAY,
        now=NOW, excluded=False, categories=["Projekt"], defaults=DEFAULTS, desktop=DESKTOP,
        window_days=window_days, window_max_days=365)


def test_a_realistic_year_is_granted_in_full_and_small():
    response = build(entries(365, 2, every_day=False))

    assert response["window_days"] == 365
    assert wire_size(response) < 150 * 1024          # gemessen: ≈ 96 KB


@pytest.mark.parametrize("slots,category", [(6, "Projekt"), (20, "Projekt"), (50, "Projekt"),
                                            (50, "Kategorie-" + "x" * 90)])
def test_heavy_data_never_exceeds_what_the_phone_can_fetch_in_time(slots, category):
    response = build(entries(365, slots, category=category))

    assert wire_size(response) <= MAX_WIRE_BYTES
    assert 90 <= response["window_days"] <= 365


def test_the_trimmed_window_is_what_the_entries_show():
    response = build(entries(365, 50, category="Kategorie-" + "x" * 90))
    first = (TODAY - datetime.timedelta(days=response["window_days"])).isoformat()
    last_inside = (TODAY - datetime.timedelta(days=response["window_days"] - 1)).isoformat()

    assert response["window_days"] < 365
    assert min(response["entries"]) >= first                  # nichts jenseits des gemeldeten Fensters
    assert last_inside in response["entries"]


def test_the_default_window_stays_even_if_it_alone_is_too_big(monkeypatch):
    monkeypatch.setattr(mobile_sync, "MAX_RESPONSE_ENTRY_BYTES", 1000)

    assert build(entries(365, 50))["window_days"] == 90


def test_days_the_phone_sent_come_back_even_outside_the_trimmed_window(monkeypatch):
    monkeypatch.setattr(mobile_sync, "MAX_RESPONSE_ENTRY_BYTES", 1000)
    old = (TODAY - datetime.timedelta(days=300)).isoformat()

    response = build(entries(365, 50), sent=[old])

    assert old in response["entries"] and response["window_days"] == 90


def test_the_budget_counts_bytes_the_way_the_response_is_sealed():
    """`_entry_bytes` misst mit der Serialisierung der Route (`mobile_routes`): Umlaute
    zählen 2 Byte (nicht 6 als `\\u00fc`), Separatoren sind kompakt."""
    clean = {"slots": [{"start": "08:00", "end": "09:00", "pause": 0, "kategorie": "Übung für Ärzte"}],
             "modified_at": "2026-10-07T18:30:00Z", "device_id": "DESK", "deleted": False}
    expected = len(json.dumps({"2026-10-07": clean}, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8"))

    assert mobile_sync._entry_bytes("2026-10-07", clean) == expected

