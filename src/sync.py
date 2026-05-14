"""Sync-Engine: pure Funktionen ohne I/O. Drive-Calls leben in src/drive.py.

Doc-Struktur (Sync-File und Zwischenformate):
{
  "schema_version": 1,
  "entries":   {date: {start, end, pause, modified_at, device_id, deleted}},
  "settings":  {key:  {value, modified_at, device_id}},
  "conflicts": [{id, kind, key, candidates, detected_at,
                 resolved, resolution, resolved_at, resolved_by}]
}
"""

import datetime
import uuid


SCHEMA_VERSION = 1

SYNCED_SETTING_KEYS = (
    "recipient", "name", "hourly_rate",
    "mail_subject", "mail_greeting", "mail_content", "mail_closing",
)


def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _values_equal_entry(a, b):
    return (a.get("start") == b.get("start")
            and a.get("end") == b.get("end")
            and a.get("pause") == b.get("pause")
            and bool(a.get("deleted")) == bool(b.get("deleted")))


def _values_equal_setting(a, b):
    return a.get("value") == b.get("value")


def _merge_one(local, remote, last_pull_at, equal_fn=_values_equal_entry, kind="entry", key=None):
    """LWW-Merge eines einzelnen Werts.

    Returns: (winner_dict, conflict_or_none)

    - Wenn nur eine Seite vorhanden ist → diese Seite gewinnt, kein Conflict.
    - Werte gleich → eine Seite gewinnt, kein Conflict.
    - Werte unterschiedlich, beide modified_at > last_pull_at → Conflict
      mit beiden Kandidaten, provisorischer Wert ist der jüngere (LWW).
    - Werte unterschiedlich, nur eine Seite seit last_pull_at geändert →
      diese Seite gewinnt (kein Conflict).
    """
    if local is None and remote is None:
        return (None, None)
    if local is None:
        return (remote, None)
    if remote is None:
        return (local, None)
    if equal_fn(local, remote):
        # jüngerer modified_at gewinnt — bei tie egal
        winner = remote if remote["modified_at"] >= local["modified_at"] else local
        return (winner, None)

    local_changed = local["modified_at"] > last_pull_at
    remote_changed = remote["modified_at"] > last_pull_at

    winner = remote if remote["modified_at"] >= local["modified_at"] else local

    if local_changed and remote_changed:
        conflict = {
            "id": str(uuid.uuid4()),
            "kind": kind,
            "key": key,
            "candidates": [_strip_for_candidate(local), _strip_for_candidate(remote)],
            "detected_at": _utc_now_iso(),
            "resolved": False,
            "resolution": None,
            "resolved_at": None,
            "resolved_by": None,
        }
        return (winner, conflict)
    return (winner, None)


def _strip_for_candidate(item):
    """Reduziert ein Entry/Setting auf das, was im conflict.candidates landen soll."""
    return {k: v for k, v in item.items()}


def merge(local, remote, last_pull_at):
    """Hauptfunktion: erwartet zwei Sync-Docs, liefert das gemergte Doc."""
    merged = {
        "schema_version": SCHEMA_VERSION,
        "entries": {},
        "settings": {},
        "conflicts": [],
    }
    new_conflicts = []

    # Entries
    all_keys = set(local.get("entries", {}).keys()) | set(remote.get("entries", {}).keys())
    for key in all_keys:
        l = local.get("entries", {}).get(key)
        r = remote.get("entries", {}).get(key)
        winner, conflict = _merge_one(l, r, last_pull_at,
                                       equal_fn=_values_equal_entry, kind="entry", key=key)
        if winner is not None:
            merged["entries"][key] = winner
        if conflict is not None:
            new_conflicts.append(conflict)

    merged["conflicts"] = new_conflicts
    return merged
