"""Push der Urlaubsperioden in einen Google Kalender.

EINWEGS-PUSH: die App ist die Quelle, der Kalender die Kopie. Nur von der App
angelegte Events tragen den Urlaubs-Marker, ein manuell angelegter
Urlaubstermin würde also ohnehin nie erkannt. Wer das Event in Google
verschiebt, bekommt es beim nächsten Abgleich zurückgesetzt — dafür vergleicht
plan_vacation_sync den Zeitraum und nicht nur den Zeitstempel (Google fasst
die private modified_at beim Verschieben nicht an). Ein Import der
Google-Änderung ist als eigener, späterer Schritt vorgesehen.

Google-Imports liegen lazy in `reconcile_vacations` — die CI installiert kein
requirements.txt, `import src.vacations_sync` muss aber funktionieren (wie
`reservations_sync.py`). `plan_vacation_sync` ist rein und direkt testbar.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Any

from src.vacations import Vacation, VacationStore


def plan_vacation_sync(local_raw: dict[str, Vacation],
                       remote_events: list[dict[str, Any]]
                       ) -> dict[str, list[Any]]:
    """Plant den Abgleich, ohne ihn auszuführen.

    Liefert {create: [(period_id, from, to, modified_at)],
             update: [(event_id, period_id, from, to, modified_at)],
             delete: [event_id]}.

    Regeln:
    - Lebende Periode ohne Event → create.
    - Lebende Periode, deren Zeitraum oder modified_at vom Event abweicht →
      update.
    - Tombstone mit Event → delete (danach darf der Tombstone weg).
    - Remote-Event ohne lebende lokale Periode → delete (Verwaiste).
    - Mehrere Events zu derselben period_id → alle bis auf eines löschen.
    """
    # Nach period_id GRUPPIEREN, nicht auf eines abbilden: ein Dict-Comprehension
    # (`{ev["period_id"]: ev for ...}`) kollabierte Duplikate auf den letzten
    # Eintrag — die überschriebenen Events landeten weder im pop-Zweig noch im
    # Rest-delete und wären für JEDEN künftigen Lauf unsichtbar. Der Fall ist
    # real: `insert` ist nicht idempotent, und die gcal_event_id wird erst nach
    # allen Netz-Calls zurückgeschrieben — ein Abbruch zwischen zwei creates
    # hinterlässt genau das. Dasselbe gilt für mehrere Events ohne period_id
    # (parse_vacation_event liefert dafür "").
    by_period: dict[str, list[dict[str, Any]]] = {}
    for ev in remote_events:
        by_period.setdefault(ev["period_id"], []).append(ev)

    create: list[Any] = []
    update: list[Any] = []
    delete: list[Any] = []

    # Duplikate abräumen; deterministisch das kleinste event_id behalten.
    for events in by_period.values():
        events.sort(key=lambda e: e["event_id"])
        delete.extend(e["event_id"] for e in events[1:])
        del events[1:]

    for pid, period in local_raw.items():
        events = by_period.pop(pid, None)
        remote = events[0] if events else None
        if period.get("deleted"):
            if remote is not None:
                delete.append(remote["event_id"])
            continue
        if remote is None:
            create.append((pid, period["from"], period["to"],
                           period["modified_at"]))
        elif (period["modified_at"] > remote.get("modified_at", "")
              or period["from"] != remote.get("from")
              or period["to"] != remote.get("to")):
            # Zeitraum-Vergleich zusätzlich zu modified_at — dasselbe Muster
            # wie reservations_sync._merge_one_date, und aus zwei Gründen
            # nötig: (1) verschiebt jemand das Event in Google, ändert sich
            # dessen private modified_at NICHT, ein reiner Zeitstempel-
            # Vergleich sähe also nie einen Unterschied; (2) utc_now_iso hat
            # Sekundenauflösung — zwei Bearbeitungen in derselben Sekunde
            # ergäben `T > T` und fielen unter den Tisch.
            update.append((remote["event_id"], pid, period["from"],
                           period["to"], period["modified_at"]))

    # Was übrig bleibt, hat keine lokale Entsprechung mehr.
    delete.extend(ev["event_id"] for evs in by_period.values() for ev in evs)
    return {"create": create, "update": update, "delete": delete}


def purge_vacation_events(service: Any, calendar_id: str,
                          store: VacationStore,
                          data_lock: threading.RLock | None = None) -> None:
    """Entfernt ALLE von der App angelegten Urlaubs-Events aus dem Kalender
    und vergisst ihre IDs lokal.

    Der Gegenweg zu `reconcile_vacations`, gefahren beim Abschalten von
    `vacation_gcal_enabled`: ohne ihn bliebe jeder bereits gepushte Zeitraum
    für immer im Kalender stehen — die App fasst ihn danach nie wieder an,
    weil der Push abgeschaltet ist. Der Schalter wäre damit eine Einbahn-
    straße.

    Das Leeren der `gcal_event_id` ist der zweite, weniger offensichtliche
    Teil: bliebe sie stehen, hielte `plan_vacation_sync` die Periode beim
    späteren Wiedereinschalten für bereits gepusht, fände remote aber nichts
    und legte kein Event mehr an. Tombstones, deren Event weg ist, haben
    nichts mehr einzulösen und verschwinden endgültig — dieselbe Regel wie
    am Ende von `reconcile_vacations`.

    Der lokale Urlaub selbst bleibt unangetastet; entfernt wird nur, was
    draußen im Kalender liegt.
    """
    from src import gcal

    for event in gcal.list_app_vacations(service, calendar_id):
        gcal.delete_event(service, calendar_id, event["event_id"])

    with (data_lock if data_lock is not None else contextlib.nullcontext()):
        merged = store.get_all_raw()
        for pid, period in list(merged.items()):
            if period.get("deleted"):
                merged.pop(pid)
            else:
                period["gcal_event_id"] = None
        store.apply_reconciled(merged)


def reconcile_vacations(service: Any, calendar_id: str, store: VacationStore,
                        data_lock: threading.RLock | None = None) -> None:
    """Voller Push: listen → planen → ausführen → Ergebnis zurückschreiben.

    Ohne `settings`-Parameter: es gibt kein Watermark zu führen — der Push
    liest den vollen Stand und vergleicht gegen die Events.

    Wirft bei Netz-/API-Fehlern weiter — der Caller entscheidet, ob still
    geloggt oder gezeigt wird. Der lokale Store bleibt bei einem Fehler
    unangetastet: er ist die Quelle, Google die Kopie.

    data_lock klammert das Zurückschreiben gegen parallele UI-Saves (Audit
    H1/H2); die Netzwerk-Calls davor laufen bewusst ungelockt.
    """
    from src import gcal

    snapshot = store.get_all_raw()
    remote_events = gcal.list_app_vacations(service, calendar_id)
    plan = plan_vacation_sync(snapshot, remote_events)

    for event_id in plan["delete"]:
        gcal.delete_event(service, calendar_id, event_id)

    for event_id, pid, date_from, date_to, modified_at in plan["update"]:
        gcal.update_vacation_event(service, calendar_id, event_id, pid,
                                   date_from, date_to, modified_at)

    new_event_ids = {}
    for pid, date_from, date_to, modified_at in plan["create"]:
        new_event_ids[pid] = gcal.create_vacation_event(
            service, calendar_id, pid, date_from, date_to, modified_at)

    removed = {pid for pid, p in snapshot.items() if p.get("deleted")}
    if not new_event_ids and not removed:
        # Nichts zurückzuschreiben. Ohne diesen Guard liefe bei JEDEM App-Start
        # und jeder Reservierungsänderung ein atomic_write_json samt fsync,
        # obwohl sich nichts geändert hat.
        return

    with (data_lock if data_lock is not None else contextlib.nullcontext()):
        merged = store.get_all_raw()
        for pid, event_id in new_event_ids.items():
            if pid in merged:
                merged[pid]["gcal_event_id"] = event_id
        # Tombstones, deren Event abgeräumt ist, verschwinden endgültig.
        for pid in removed:
            entry = merged.get(pid)
            if entry is not None and entry.get("deleted"):
                merged.pop(pid)
        store.apply_reconciled(merged)
