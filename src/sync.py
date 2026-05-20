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
    "gcal_calendar_id",
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


def _merge_conflict_pair(a, b):
    """LWW auf resolved_at, resolved beats unresolved."""
    if a.get("resolved") and not b.get("resolved"):
        return a
    if b.get("resolved") and not a.get("resolved"):
        return b
    if a.get("resolved") and b.get("resolved"):
        return a if (a.get("resolved_at") or "") >= (b.get("resolved_at") or "") else b
    return a  # beide unresolved — ID-Match heißt dasselbe Detection-Event


def _equivalent_unresolved_exists(existing, new_conflict):
    """Dedupe: existiert bereits ein unresolved Konflikt mit gleichem
    (kind, key, Kandidaten-Set)?"""
    if new_conflict.get("resolved"):
        return False
    new_keys = _candidate_signatures(new_conflict["candidates"])
    for c in existing:
        if c.get("resolved"):
            continue
        if c["kind"] != new_conflict["kind"] or c["key"] != new_conflict["key"]:
            continue
        if _candidate_signatures(c["candidates"]) == new_keys:
            return True
    return False


def _candidate_signatures(candidates):
    """Sortiertes Tuple aus (modified_at, device_id) — als Set-Vergleichsbasis."""
    return tuple(sorted((c.get("modified_at"), c.get("device_id")) for c in candidates))


def merge(local, remote, last_pull_at):
    merged = {
        "schema_version": SCHEMA_VERSION,
        "entries": {},
        "settings": {},
        "conflicts": [],
    }
    new_conflicts = []

    # Entries
    all_entry_keys = set(local.get("entries", {}).keys()) | set(remote.get("entries", {}).keys())
    for key in all_entry_keys:
        l = local.get("entries", {}).get(key)
        r = remote.get("entries", {}).get(key)
        winner, conflict = _merge_one(l, r, last_pull_at,
                                       equal_fn=_values_equal_entry, kind="entry", key=key)
        if winner is not None:
            merged["entries"][key] = winner
        if conflict is not None:
            new_conflicts.append(conflict)

    # Settings (Whitelist)
    for key in SYNCED_SETTING_KEYS:
        l = local.get("settings", {}).get(key)
        r = remote.get("settings", {}).get(key)
        winner, conflict = _merge_one(l, r, last_pull_at,
                                       equal_fn=_values_equal_setting, kind="setting", key=key)
        if winner is not None:
            merged["settings"][key] = winner
        if conflict is not None:
            new_conflicts.append(conflict)

    # Conflicts-Liste: Union by ID
    by_id = {}
    for c in local.get("conflicts", []) + remote.get("conflicts", []):
        cid = c["id"]
        if cid in by_id:
            by_id[cid] = _merge_conflict_pair(by_id[cid], c)
        else:
            by_id[cid] = c

    # Neu erkannte Konflikte dazu, mit Dedup
    existing = list(by_id.values())
    for c in new_conflicts:
        if not _equivalent_unresolved_exists(existing, c):
            by_id[c["id"]] = c
            existing.append(c)

    merged["conflicts"] = list(by_id.values())

    # Resolutions anwenden: jeder resolved Konflikt überschreibt entries/settings,
    # falls die Resolution jünger ist als der aktuelle merged-Wert.
    for c in merged["conflicts"]:
        if not c.get("resolved"):
            continue
        resolution = c.get("resolution") or {}
        resolved_at = c.get("resolved_at") or ""
        resolved_by = c.get("resolved_by") or ""
        if c["kind"] == "entry":
            current = merged["entries"].get(c["key"])
            if current is None or current["modified_at"] < resolved_at:
                merged["entries"][c["key"]] = {
                    "start": resolution.get("start"),
                    "end": resolution.get("end"),
                    "pause": resolution.get("pause", 0),
                    "modified_at": resolved_at,
                    "device_id": resolved_by,
                    "deleted": bool(resolution.get("deleted", False)),
                }
        elif c["kind"] == "setting":
            current = merged["settings"].get(c["key"])
            if current is None or current["modified_at"] < resolved_at:
                merged["settings"][c["key"]] = {
                    "value": resolution.get("value"),
                    "modified_at": resolved_at,
                    "device_id": resolved_by,
                }

    return merged


def build_local_doc(storage, settings, conflicts_store):
    """Erzeugt das Sync-Doc-Format aus den lokalen Stores."""
    return {
        "schema_version": SCHEMA_VERSION,
        "entries": storage.get_all_raw(),
        "settings": settings.get_synced_doc(),
        "conflicts": conflicts_store.get_all(),
    }


def apply_merged_doc(merged_doc, storage, settings, conflicts_store):
    """Schreibt das Merge-Ergebnis zurück in die lokalen Stores."""
    storage.apply_merge(merged_doc.get("entries", {}))
    settings.apply_synced(merged_doc.get("settings", {}))
    conflicts_store.save_all(merged_doc.get("conflicts", []))


def resolve_conflict(conflict_id, chosen_value, conflicts_store, storage, settings, device_id):
    """User hat einen Konflikt aufgelöst. chosen_value enthält den gewählten
    (oder manuell editierten) Wert. Für entries: {start, end, pause} (und
    optional deleted). Für settings: {value}.
    Schreibt den Wert in den entsprechenden Store und markiert den Konflikt
    als resolved im ConflictsStore."""
    all_conflicts = conflicts_store.get_all()
    target = next((c for c in all_conflicts if c["id"] == conflict_id), None)
    if target is None:
        raise KeyError(f"Konflikt {conflict_id!r} nicht gefunden")

    now = _utc_now_iso()
    target["resolved"] = True
    target["resolution"] = dict(chosen_value)
    target["resolved_at"] = now
    target["resolved_by"] = device_id

    if target["kind"] == "entry":
        if chosen_value.get("deleted"):
            storage.delete(target["key"])
        else:
            storage.save(
                target["key"],
                chosen_value.get("start"),
                chosen_value.get("end"),
                chosen_value.get("pause", 0),
            )
    elif target["kind"] == "setting":
        settings.set_synced(target["key"], chosen_value.get("value"))

    conflicts_store.save_all(all_conflicts)
