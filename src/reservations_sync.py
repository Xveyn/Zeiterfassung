# src/reservations_sync.py
"""Reservierungs-Abgleich mit dem Google Kalender.

`merge_reservations()` ist eine pure LWW-Merge-Funktion (kein I/O), die
`reconcile_reservations()` (weiter unten, Task 9) orchestriert pull → merge →
push. Der Merge spiegelt `sync.py::_merge_one` OHNE den Konflikt-Zweig: bei
beidseitiger Änderung gewinnt still der jüngere `modified_at`-Stand.
"""

import datetime


def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _from_remote(remote):
    """Reservierungs-Record aus einem geparsten Kalender-Event."""
    return {
        "start": remote["start"],
        "end": remote["end"],
        "modified_at": remote["modified_at"],
        "deleted": False,
        "gcal_event_id": remote["event_id"],
    }


def _merge_one_date(date, local, remote, watermark, merged, plan):
    """Mergt einen einzelnen Tag. Mutiert `merged` und `plan` in-place.

    `local`  — Reservierungs-Record (echt oder Tombstone) oder None
    `remote` — geparstes Kalender-Event oder None
    `watermark` — last_calendar_sync_at
    """
    is_tombstone = local is not None and local.get("deleted")

    # Fall 1: nichts vorhanden.
    if local is None and remote is None:
        return

    # Fälle 2 & 3: lokaler Tombstone.
    if is_tombstone:
        if remote is None:
            return  # Tombstone fällt weg, nichts zu tun.
        if local["modified_at"] >= remote["modified_at"]:
            plan["delete"].append({"event_id": remote["event_id"]})
            return  # Löschung gewinnt, Tombstone fällt weg.
        merged[date] = _from_remote(remote)  # Remote-Update ist jünger.
        return

    # Fall 6: nur remote → übernehmen.
    if local is None:
        merged[date] = _from_remote(remote)
        return

    # Fall 5: nur lokal (echt).
    if remote is None:
        if local["modified_at"] > watermark:
            merged[date] = dict(local)  # lokale Neuanlage.
            plan["create"].append({
                "date": date, "start": local["start"], "end": local["end"],
                "modified_at": local["modified_at"],
            })
        # sonst: war beim letzten Sync da, remote jetzt weg → verwerfen.
        return

    # Fall 4: beide vorhanden (echt) → LWW.
    if remote["modified_at"] > local["modified_at"]:
        merged[date] = _from_remote(remote)
        return
    # Lokal gewinnt (inkl. Gleichstand — App ist autoritativ).
    record = dict(local)
    record["gcal_event_id"] = remote["event_id"]
    merged[date] = record
    if local["start"] != remote["start"] or local["end"] != remote["end"]:
        plan["update"].append({
            "date": date, "event_id": remote["event_id"],
            "start": local["start"], "end": local["end"],
            "modified_at": local["modified_at"],
        })


def merge_reservations(local_raw, remote_events, watermark):
    """Pure Merge zwischen lokalen Reservierungen und Kalender-Events.

    local_raw:     {date: {start, end, modified_at, deleted, gcal_event_id}}
    remote_events: Liste von {date, start, end, modified_at, event_id}
    watermark:     last_calendar_sync_at (ISO-String, "" beim Erststart)

    Liefert {"merged": {...}, "plan": {"create": [...], "update": [...],
    "delete": [...]}}.
    """
    plan = {"create": [], "update": [], "delete": []}

    # Remote-Events nach Datum gruppieren. Bei mehreren Events pro Tag (seltenes
    # Race) gewinnt das jüngste, die übrigen landen im delete-Plan — Selbstheilung.
    remote_by_date = {}
    for ev in remote_events:
        d = ev["date"]
        if d not in remote_by_date:
            remote_by_date[d] = ev
            continue
        keep, drop = remote_by_date[d], ev
        if ev["modified_at"] > keep["modified_at"]:
            keep, drop = ev, keep
        remote_by_date[d] = keep
        plan["delete"].append({"event_id": drop["event_id"]})

    merged = {}
    for date in set(local_raw.keys()) | set(remote_by_date.keys()):
        _merge_one_date(
            date, local_raw.get(date), remote_by_date.get(date),
            watermark, merged, plan,
        )
    return {"merged": merged, "plan": plan}
