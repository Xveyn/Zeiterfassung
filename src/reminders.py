"""Pure Reminder-Entscheidungslogik (Tk-frei, keine datetime.now()-Bindung).

Ermittelt, für welche heutigen reservierten Slots eine Toast-Erinnerung fällig
ist: 'upcoming' (N Minuten vor Ende, während man im Slot ist) oder 'missed'
(Slot-Ende bereits vorbei). Beides nur für Slots mit gesetzter Kategorie, deren
Kategorie am Tag noch nicht als Ist-Zeit erfasst wurde. Pro Slot feuert genau
einer der beiden Typen — garantiert durch die Zeit-Reihenfolge (missed vor dem
upcoming-Fenster) plus das already_fired-Set beim Aufrufer.
"""
import datetime
from collections import namedtuple

from src.category_defaults import resolve_slot_defaults

Reminder = namedtuple("Reminder", ["key", "kind", "kategorie", "end"])


def _parse_hhmm(date, value):
    """'HH:MM' + date -> datetime; None/ungültig -> None."""
    if not isinstance(value, str):
        return None
    try:
        hh, mm = value.split(":")
        return datetime.datetime(date.year, date.month, date.day, int(hh), int(mm))
    except (ValueError, TypeError):
        return None


def due_reminders(reserved_slots, logged_categories, now_dt,
                  minutes_before, already_fired):
    """Liefert die fälligen Reminder für die heutigen reservierten Slots.

    reserved_slots: Iterable von {start, end, kategorie}.
    logged_categories: set der heute als Ist-Zeit erfassten nicht-leeren Kategorien.
    now_dt: datetime 'jetzt' (naiv, lokal — das Datum von now_dt ist 'heute').
    minutes_before: int N (>= 0).
    already_fired: set von keys, die bereits benachrichtigt wurden.

    key = (now_dt.date().isoformat(), start_str, end_str, kategorie).
    Fällig, wenn Kategorie gesetzt UND nicht in logged_categories UND key nicht
    in already_fired:
      now >= end                         -> 'missed'
      now >= max(start, end - N Minuten) -> 'upcoming'
      sonst                              -> nicht fällig.
    """
    date = now_dt.date()
    delta = datetime.timedelta(minutes=minutes_before)
    out = []
    for slot in reserved_slots:
        kategorie = (slot.get("kategorie") or "").strip()
        if not kategorie or kategorie in logged_categories:
            continue
        start = _parse_hhmm(date, slot.get("start"))
        end = _parse_hhmm(date, slot.get("end"))
        if start is None or end is None:
            continue
        key = (date.isoformat(), slot.get("start"), slot.get("end"), kategorie)
        if key in already_fired:
            continue
        if now_dt >= end:
            out.append(Reminder(key, "missed", kategorie, slot.get("end")))
        elif now_dt >= max(start, end - delta):
            out.append(Reminder(key, "upcoming", kategorie, slot.get("end")))
    return out


def ist_slot_from_reservation(res_slot, category_times, weekday_key, default_pause):
    """Baut aus einem Reservierungs-Slot (Soll) den Ist-Zeit-Slot fürs Eintragen.

    start/end/kategorie stammen aus der Reservierung; die Pause wird aus dem
    Per-Kategorie-Default abgeleitet (resolve_slot_defaults, Fallback
    default_pause) — genau wie beim manuellen Anlegen im Tages-Dialog. Start/Ende
    aus resolve_slot_defaults werden bewusst verworfen (die Reservierung ist die
    Quelle der Zeiten).
    """
    kategorie = (res_slot.get("kategorie") or "").strip()
    _, _, pause = resolve_slot_defaults(
        category_times, kategorie, weekday_key, None, None, default_pause)
    return {
        "start": res_slot.get("start"),
        "end": res_slot.get("end"),
        "pause": pause,
        "kategorie": kategorie,
    }
