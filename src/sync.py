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


SCHEMA_VERSION = 3


NEWER_REMOTE_VERSION_MSG = (
    "Ein anderes Gerät nutzt eine neuere App-Version mit einem Datenformat, "
    "das diese (ältere) Version noch nicht versteht.\n\n"
    "Bitte aktualisiere die App auf diesem Gerät. Bis dahin pausiert die "
    "Synchronisation, damit keine Daten verloren gehen oder überschrieben werden."
)


def _watermark_of(doc):
    return ((doc.get("meta") or {}).get("gc_watermark") or "")


def _is_settled_entry(entry, watermark):
    return bool(entry.get("deleted")) and (entry.get("modified_at") or "") < watermark


def _is_settled_conflict(conflict, watermark):
    resolved_at = conflict.get("resolved_at") or ""
    return bool(conflict.get("resolved")) and resolved_at != "" and resolved_at < watermark

SYNCED_SETTING_KEYS = (
    "recipient", "name", "hourly_rate",
    "mail_subject", "mail_greeting", "mail_content", "mail_closing",
    "gcal_calendar_id", "categories", "category_times",
)


def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slots_signature(entry):
    """Reihenfolge-normalisierte Signatur der Slot-Liste eines Eintrags,
    für den Gleichheitsvergleich im Merge. Sortiert nach den Slot-Feldern,
    damit eine reine Umordnung der Slots NICHT als Änderung zählt."""
    return sorted(
        (s.get("start"), s.get("end"), s.get("pause", 0), s.get("kategorie", ""))
        for s in (entry.get("slots") or [])
    )


def _values_equal_entry(a, b):
    return (_slots_signature(a) == _slots_signature(b)
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
        "meta": {"gc_watermark": ""},
    }
    watermark = max(_watermark_of(local), _watermark_of(remote))
    merged["meta"]["gc_watermark"] = watermark
    remote_wm = _watermark_of(remote)
    excluded = bool(last_pull_at) and last_pull_at < remote_wm
    new_conflicts = []

    # Entries
    all_entry_keys = set(local.get("entries", {}).keys()) | set(remote.get("entries", {}).keys())
    for key in all_entry_keys:
        loc = local.get("entries", {}).get(key)
        rem = remote.get("entries", {}).get(key)
        winner, conflict = _merge_one(loc, rem, last_pull_at,
                                       equal_fn=_values_equal_entry, kind="entry", key=key)
        # Regel 2: Self-Heal — ein zurückgekehrtes (excluded) Gerät darf einen
        # alten, remote-fehlenden lebenden Eintrag nicht auferstehen lassen.
        if (excluded and rem is None and loc is not None
                and (loc.get("modified_at") or "") < remote_wm):
            winner = None
        if winner is not None:
            merged["entries"][key] = winner
        if conflict is not None:
            new_conflicts.append(conflict)

    # Settings (Whitelist)
    for key in SYNCED_SETTING_KEYS:
        loc = local.get("settings", {}).get(key)
        rem = remote.get("settings", {}).get(key)
        winner, conflict = _merge_one(loc, rem, last_pull_at,
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
                    "slots": resolution.get("slots", []),
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

    # Regel 1: settled Tombstones entfernen (Kompaktierung propagieren).
    # Läuft NACH der Resolution-Application, damit kein resolved-Wert verloren geht.
    if watermark:
        merged["entries"] = {
            k: v for k, v in merged["entries"].items()
            if not _is_settled_entry(v, watermark)
        }
        merged["conflicts"] = [
            c for c in merged["conflicts"]
            if not _is_settled_conflict(c, watermark)
        ]

    return merged


def build_local_doc(storage, settings, conflicts_store):
    """Erzeugt das Sync-Doc-Format aus den lokalen Stores."""
    return {
        "schema_version": SCHEMA_VERSION,
        "entries": storage.get_all_raw(),
        "settings": settings.get_synced_doc(),
        "conflicts": conflicts_store.get_all(),
        "meta": {"gc_watermark": settings.get("gc_watermark") or ""},
    }


def apply_merged_doc(merged_doc, storage, settings, conflicts_store):
    """Schreibt das Merge-Ergebnis zurück in die lokalen Stores."""
    storage.apply_merge(merged_doc.get("entries", {}))
    settings.apply_synced(merged_doc.get("settings", {}))
    conflicts_store.save_all(merged_doc.get("conflicts", []))
    settings.set("gc_watermark", (merged_doc.get("meta") or {}).get("gc_watermark") or "")


def compact_local(storage, settings, conflicts_store, now):
    """Schreibt das gc_watermark lokal und strippt settled Tombstones aus
    Storage und ConflictsStore. Ein lokaler Schreibvorgang pro Store
    (Wiederverwendung von storage.apply_merge — Required-Key-Validator +
    Atomic-Write bleiben auf einem Pfad)."""
    settings.set("gc_watermark", now)
    storage.apply_merge({
        k: v for k, v in storage.get_all_raw().items()
        if not _is_settled_entry(v, now)
    })
    conflicts_store.save_all([
        c for c in conflicts_store.get_all()
        if not _is_settled_conflict(c, now)
    ])


def migrate_doc_to_v3(remote_doc):
    """Migriert ein Sync-Doc auf das aktuelle Schema (v3): flache Einträge
    (start/end/pause) werden in eine Slot-Liste gewrappt. Idempotent — Einträge,
    die bereits `slots` tragen, bleiben unangetastet; Tombstones (deleted=True)
    bekommen eine leere Slot-Liste. settings/conflicts/meta bleiben unberührt.

    Damit kann ein v3-Client ein älteres (v1/v2) Remote-Doc absorbieren und
    hochziehen, statt es abzuweisen oder beim Push zu plätten."""
    entries = remote_doc.get("entries") or {}
    migrated = {}
    for date, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        if "slots" in entry:
            migrated[date] = entry
            continue
        if entry.get("deleted"):
            slots = []
        else:
            slots = [{
                "start": entry.get("start"),
                "end": entry.get("end"),
                "pause": entry.get("pause", 0),
                "kategorie": "",
            }]
        migrated[date] = {
            "slots": slots,
            "modified_at": entry.get("modified_at"),
            "device_id": entry.get("device_id"),
            "deleted": bool(entry.get("deleted", False)),
        }
    return {**remote_doc, "schema_version": SCHEMA_VERSION, "entries": migrated}


def _remote_is_newer(remote_doc):
    """True, wenn das Remote-Doc von einer NEUEREN App-Version stammt
    (schema_version > der hier verstandenen SCHEMA_VERSION).

    Forward-Compat-Guard: Ab Schema 3 enthalten Einträge `slots` statt der
    flachen `start/end/pause`-Keys. Würde diese ältere Version so ein Doc
    mergen und via `storage.apply_merge` schreiben, bräche der Required-Key-
    Validator hart ab ("missing keys ['start','end','pause']"). Stattdessen
    muss der Pull/Push abbrechen, ohne das neuere Remote-Doc zu überschreiben."""
    return (remote_doc.get("schema_version") or 1) > SCHEMA_VERSION


def resolve_conflict(conflict_id, chosen_value, conflicts_store, storage, settings, device_id):
    """User hat einen Konflikt aufgelöst. chosen_value enthält den gewählten
    (oder manuell editierten) Wert. Für entries: {slots: [...]} (und
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
            storage.save(target["key"], chosen_value.get("slots", []))
    elif target["kind"] == "setting":
        settings.set_synced(target["key"], chosen_value.get("value"))

    conflicts_store.save_all(all_conflicts)
