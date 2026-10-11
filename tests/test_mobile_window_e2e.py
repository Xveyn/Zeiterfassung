"""Ende-zu-Ende (#293 M7): echtes `build_response` des Desktops, echtes `applyResponse` der PWA.

Die Python-Tests prüfen die Antwort, die JS-Tests die Anwendung — aber jeder mit eigenen
Annahmen über die andere Seite. Hier läuft beides hintereinander (Node-Skript
`mobile_apply_probe.mjs`). Ohne Node wird übersprungen; die `pwa`-Job-CI hat es."""
import datetime
import json
import pathlib
import shutil
import subprocess

import pytest

from src import mobile_sync

PROBE = pathlib.Path(__file__).resolve().parent / "mobile_apply_probe.mjs"
TODAY = datetime.date(2026, 10, 8)
NOW = "2026-10-08T12:00:00Z"
DEFAULTS = {"pause": 30, "weekdays": {}, "category_times": {}}
DESKTOP = {"name": "PC", "version": "1.0.0", "platform": "Linux"}

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node fehlt")


def day(offset):
    return (TODAY - datetime.timedelta(days=offset)).isoformat()


def desktop_entries(days):
    return {day(i): {"slots": [{"start": "08:00", "end": "09:00", "pause": 0, "kategorie": "P"}],
                     "modified_at": "2026-10-07T18:30:00Z", "device_id": "DESK", "deleted": False}
            for i in range(days + 1)}


def response(entries, cap):
    out = mobile_sync.build_response(
        {"entries": entries, "conflicts": [], "devices": {}}, sent_dates=(), today=TODAY, now=NOW,
        excluded=False, categories=["P"], defaults=DEFAULTS, desktop=DESKTOP,
        window_days=mobile_sync.grant_window(365, cap), window_max_days=cap)
    return json.loads(json.dumps(out))


def apply_on_phone(responses, dirty_old=()):
    result = subprocess.run(
        ["node", str(PROBE)], input=json.dumps({"today": TODAY.isoformat(), "dirty_old": list(dirty_old),
                                                 "responses": responses}),
        capture_output=True, text=True, check=True, timeout=60)
    return json.loads(result.stdout)


def test_a_sinking_cap_cleans_up_the_old_days_but_keeps_untransferred_ones():
    entries = desktop_entries(365)
    untransferred = day(300)

    first = apply_on_phone([response(entries, 365)], dirty_old=[untransferred])
    assert day(300) in first["days"] and day(364) in first["days"]

    after = apply_on_phone([response(entries, 365), response(entries, 30)], dirty_old=[untransferred])

    assert after["window_days"] == 30
    assert day(30) in after["days"] and day(0) in after["days"]
    assert day(200) not in after["days"]                 # außerhalb der neuen Obergrenze: aufgeräumt
    assert untransferred in after["days"]                # noch nicht übertragen: bleibt


def test_the_phone_window_is_what_the_desktop_reported():
    after = apply_on_phone([response(desktop_entries(365), 90)])

    assert after["window_days"] == 90
