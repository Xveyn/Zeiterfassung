"""Sample-Daten für das Dev-Daten-Verzeichnis.

Schreibt Einträge, Settings und ein Dummy-credentials.json — aber bewusst
KEIN token.json (siehe Plan-Header: hält den Dev-Start frei von Token-Popups).
"""

import datetime
import json
import os

_DATA_FILES = ("zeiterfassung.json", "settings.json", "credentials.json")


def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sample_entries():
    today = datetime.date.today()
    now = _utc_now_iso()
    entries = {}
    for delta in (0, 1, 2, 7):
        day = today - datetime.timedelta(days=delta)
        entries[day.isoformat()] = {
            "start": "08:00",
            "end": "16:30",
            "pause": 30,
            "modified_at": now,
            "device_id": "dev",
            "deleted": False,
        }
    return entries


def _write_all(base_path):
    os.makedirs(base_path, exist_ok=True)
    with open(os.path.join(base_path, "zeiterfassung.json"), "w", encoding="utf-8") as f:
        json.dump(_sample_entries(), f, indent=2, ensure_ascii=False)

    settings = {
        "name": "Dev User",
        "recipient": "dev@example.com",
        "sync_enabled": False,
        "gcal_enabled": False,
    }
    with open(os.path.join(base_path, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)

    creds = {"installed": {"client_id": "dev", "client_secret": "dev",
                           "auth_uri": "", "token_uri": ""}}
    with open(os.path.join(base_path, "credentials.json"), "w", encoding="utf-8") as f:
        json.dump(creds, f)


def seed_if_empty(base_path):
    """Schreibt Sample-Daten nur, wenn noch keine zeiterfassung.json existiert."""
    os.makedirs(base_path, exist_ok=True)
    if os.path.exists(os.path.join(base_path, "zeiterfassung.json")):
        return
    _write_all(base_path)


def reseed(base_path):
    """Löscht die Daten-Dateien und schreibt frische Sample-Daten."""
    for name in _DATA_FILES:
        path = os.path.join(base_path, name)
        if os.path.exists(path):
            os.remove(path)
    _write_all(base_path)
