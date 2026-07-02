# src/reservations_sync.py
"""Reservierungs-Abgleich mit dem Google Kalender (Slot-Modell).

Jeder Reservierungs-Slot ↔ ein Kalender-Event (Matching über gcal_event_id).
`merge_reservations()` ist eine pure LWW-Merge-Funktion (kein I/O): pro Datum
entscheidet `modified_at` (App autoritativ bei Gleichstand), ob die lokalen
Slots oder die Remote-Events gewinnen. `reconcile_reservations()` orchestriert
pull → merge → push und schreibt neue event_ids pro Slot zurück.
"""

import datetime


def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slot_from_event(ev):
    """Reservierungs-Slot aus einem geparsten Kalender-Event."""
    return {
        "start": ev["start"], "end": ev["end"],
        "kategorie": ev.get("kategorie", ""), "gcal_event_id": ev["event_id"],
    }


def _adopt_remote(date, remotes, merged, imported_dates):
    """Remote gewinnt: die Slots des Tages = die Remote-Events."""
    merged[date] = {
        "slots": [_slot_from_event(ev) for ev in remotes],
        "modified_at": max(ev["modified_at"] for ev in remotes),
        "deleted": False,
    }
    imported_dates.add(date)


def _merge_one_date(date, local, remotes, watermark, merged, plan, imported_dates):
    """Mergt einen einzelnen Tag (Slot-Ebene). Mutiert `merged`/`plan`.

    local   — Reservierungs-Record {slots, modified_at, deleted} oder None
    remotes — Liste geparster Kalender-Events dieses Tages (evtl. leer)
    """
    is_tombstone = local is not None and local.get("deleted")
    local_mod = local["modified_at"] if local is not None else None
    remote_mod = max((ev["modified_at"] for ev in remotes), default=None)

    # Fall 1: nichts vorhanden.
    if local is None and not remotes:
        return

    # Fall 2: nur remote → als Slots übernehmen.
    if local is None:
        _adopt_remote(date, remotes, merged, imported_dates)
        return

    # Fall 3: lokaler Tombstone.
    if is_tombstone:
        if not remotes:
            return  # Tombstone fällt weg.
        # Garantiert gesetzt: Tombstone -> local vorhanden -> local_mod; remotes
        # nicht leer -> remote_mod nicht None.
        assert local_mod is not None and remote_mod is not None
        if local_mod >= remote_mod:
            for ev in remotes:
                plan["delete"].append({"event_id": ev["event_id"]})
            return  # Löschung gewinnt.
        _adopt_remote(date, remotes, merged, imported_dates)  # Remote-Update jünger.
        return

    # Fall 4: lokal (echt), keine Remote-Events.
    if not remotes:
        if local_mod > watermark:
            merged[date] = {
                "slots": [dict(s) for s in local["slots"]],
                "modified_at": local_mod, "deleted": False,
            }
            for i, s in enumerate(local["slots"]):
                plan["create"].append({
                    "date": date, "slot_index": i,
                    "start": s["start"], "end": s["end"],
                    "kategorie": s.get("kategorie", ""), "modified_at": local_mod,
                })
        # sonst: war beim letzten Sync da, remote jetzt weg → verwerfen.
        return

    # Fall 5: lokal (echt) + Remote-Events.
    # Garantiert gesetzt: Fall 2 hat local=None abgefangen -> local_mod; Fall 4
    # hat leere remotes abgefangen -> remote_mod nicht None.
    assert local_mod is not None and remote_mod is not None
    if remote_mod > local_mod:
        _adopt_remote(date, remotes, merged, imported_dates)
        return

    # Lokal gewinnt (inkl. Gleichstand — App autoritativ): Slots ↔ Events über
    # gcal_event_id matchen.
    remote_by_id = {ev["event_id"]: ev for ev in remotes}
    matched_ids = set()
    merged_slots = []
    for i, s in enumerate(local["slots"]):
        eid = s.get("gcal_event_id")
        slot_copy = dict(s)
        if eid and eid in remote_by_id:
            matched_ids.add(eid)
            ev = remote_by_id[eid]
            if (s["start"] != ev["start"] or s["end"] != ev["end"]
                    or s.get("kategorie", "") != ev.get("kategorie", "")):
                plan["update"].append({
                    "event_id": eid, "date": date,
                    "start": s["start"], "end": s["end"],
                    "kategorie": s.get("kategorie", ""), "modified_at": local_mod,
                })
        else:
            # Neuer Slot (noch kein Event oder verwaiste id) → create.
            slot_copy["gcal_event_id"] = None
            plan["create"].append({
                "date": date, "slot_index": i,
                "start": s["start"], "end": s["end"],
                "kategorie": s.get("kategorie", ""), "modified_at": local_mod,
            })
        merged_slots.append(slot_copy)

    # Remote-Events ohne lokalen Slot → löschen.
    for ev in remotes:
        if ev["event_id"] not in matched_ids:
            plan["delete"].append({"event_id": ev["event_id"]})

    merged[date] = {"slots": merged_slots, "modified_at": local_mod, "deleted": False}


def merge_reservations(local_raw, remote_events, watermark):
    """Pure Merge zwischen lokalen Reservierungs-Records und Kalender-Events.

    local_raw:     {date: {slots: [{start,end,kategorie,gcal_event_id}],
                           modified_at, deleted}}
    remote_events: Liste von {date, start, end, kategorie, modified_at, event_id}
    watermark:     last_calendar_sync_at (ISO-String, "" beim Erststart)

    Liefert {"merged": {...}, "plan": {"create": [...], "update": [...],
    "delete": [...]}, "imported_dates": [...]}.
    imported_dates: sortierte Liste der Daten, an denen Remote-Events lokal
    übernommen wurden (echter Kalender-Import, siehe _adopt_remote) — für
    den nachgelagerten Wochenlimit-Check (weekly_limit.py, #98). Lokal-
    gewinnt-Fälle (pushen nur zu Google) zählen NICHT als Import.
    """
    plan = {"create": [], "update": [], "delete": []}
    imported_dates = set()

    remote_by_date = {}
    for ev in remote_events:
        remote_by_date.setdefault(ev["date"], []).append(ev)

    merged = {}
    for date in set(local_raw.keys()) | set(remote_by_date.keys()):
        _merge_one_date(
            date, local_raw.get(date), remote_by_date.get(date, []),
            watermark, merged, plan, imported_dates,
        )
    return {"merged": merged, "plan": plan, "imported_dates": sorted(imported_dates)}


def reconcile_reservations(service, calendar_id, store, settings):
    """Voller Kalender-Abgleich: pull → merge → push.

    Mutiert store und settings. Wirft bei Netz-/API-Fehlern weiter — der Caller
    entscheidet, ob still geloggt oder als Messagebox gezeigt wird.

    Liefert {"imported_dates": [...]} — die Daten, an denen in diesem Lauf
    Reservierungs-Slots aus dem Kalender importiert wurden (siehe
    merge_reservations), für den nachgelagerten Wochenlimit-Check (#98).
    """
    from src import gcal

    watermark = settings.get("last_calendar_sync_at") or ""
    local_snapshot = store.get_all_raw()
    remote_events = gcal.list_app_events(service, calendar_id)
    result = merge_reservations(local_snapshot, remote_events, watermark)
    merged, plan, imported_dates = result["merged"], result["plan"], result["imported_dates"]

    for item in plan["delete"]:
        gcal.delete_event(service, calendar_id, item["event_id"])

    for item in plan["update"]:
        gcal.update_event(
            service, calendar_id, item["event_id"],
            item["date"], item["start"], item["end"],
            item["kategorie"], item["modified_at"],
        )

    for item in plan["create"]:
        event_id = gcal.create_event(
            service, calendar_id,
            item["date"], item["start"], item["end"],
            item["kategorie"], item["modified_at"],
        )
        merged[item["date"]]["slots"][item["slot_index"]]["gcal_event_id"] = event_id

    # Rebase: Reservierungen, die seit dem Snapshot lokal gespeichert/geändert
    # wurden (paralleler Reconcile / User-Save während des Netzwerkteils),
    # dürfen nicht durch den apply_reconciled-Replace verloren gehen.
    for date, entry in store.get_all_raw().items():
        snap = local_snapshot.get(date)
        if snap is None or entry.get("modified_at", "") > snap.get("modified_at", ""):
            merged[date] = entry

    store.apply_reconciled(merged)
    settings.set("last_calendar_sync_at", _utc_now_iso())
    return {"imported_dates": imported_dates}
