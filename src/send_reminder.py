"""Pure Fälligkeits-Logik für den monatlichen Sende-Reminder (Tk-frei).

Ermittelt, ob am `now_dt` der konfigurierte Tag/Uhrzeit für die Erinnerung
"Arbeitszeiten verschicken" erreicht oder überschritten ist und für den
aktuellen Monat noch nicht gefeuert wurde. Tage jenseits der Monatslänge
(z.B. 31 im Februar) clampen auf den letzten Tag des Monats. Optional wird
der Termin zusätzlich von arbeitsfreien Tagen (Wochenende/Feiertage) weg
verschoben (shift_off_free_days).
"""
import calendar
import datetime
from collections import namedtuple


def scheduled_datetime(year, month, day, time_str,
                       shift_mode="none", free_dates=None):
    """Fällig-Zeitpunkt für (year, month); `day` wird auf die tatsächliche
    Monatslänge geclamped (Tag 31 im Februar -> 28./29., im April -> 30.).
    Danach wird optional von arbeitsfreien Tagen weg verschoben
    (shift_off_free_days). `time_str` ungültig/kein 'HH:MM' -> None."""
    hh_mm = _parse_hhmm(time_str)
    if hh_mm is None:
        return None
    last_day = calendar.monthrange(year, month)[1]
    actual_day = min(max(day, 1), last_day)
    target = shift_off_free_days(
        datetime.date(year, month, actual_day), shift_mode,
        free_dates if free_dates is not None else frozenset())
    hh, mm = hh_mm
    return datetime.datetime(target.year, target.month, target.day, hh, mm)


def _parse_hhmm(value):
    if not isinstance(value, str):
        return None
    try:
        hh, mm = value.split(":")
        hh, mm = int(hh), int(mm)
    except (ValueError, TypeError):
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh, mm


SHIFT_LABELS = {
    "none": "nicht verschieben",
    "backward": "vorziehen (davor)",
    "forward": "nachziehen (danach)",
}


def label_for_shift(mode):
    """Enum-Wert → Klartext fürs Dropdown. Unbekannt → Label von 'none'."""
    return SHIFT_LABELS.get(mode, SHIFT_LABELS["none"])


def shift_for_label(label):
    """Klartext aus dem Dropdown → Enum-Wert. Unbekannt → 'none'."""
    for mode, text in SHIFT_LABELS.items():
        if text == label:
            return mode
    return "none"


def shift_off_free_days(date, mode, free_dates):
    """Verschiebt `date` weg von arbeitsfreien Tagen, ohne den Monat zu
    verlassen.

    mode "backward": rückwärts zum ersten nicht-freien Tag.
    mode "forward":  vorwärts zum ersten nicht-freien Tag.
    Verlässt die Suche den Monat, wird in der Gegenrichtung gesucht. Das gilt
    bewusst für BEIDE Richtungen: is_due berechnet den Fälligkeitszeitpunkt
    immer für den laufenden Monat, ein in den Nachbarmonat gerutschter Termin
    wäre dort nie erreichbar und würde erst am Monatsersten nachfeuern.
    Anderer/unbekannter Modus oder kein Arbeitstag im ganzen Monat: unverändert.
    """
    if mode not in ("backward", "forward"):
        return date
    first = date.replace(day=1)
    last = date.replace(day=calendar.monthrange(date.year, date.month)[1])
    primary = -1 if mode == "backward" else 1
    for step in (primary, -primary):
        current = date
        while first <= current <= last:
            if current not in free_dates:
                return current
            current += datetime.timedelta(days=step)
    return date


def free_dates_for_month(year, month, state="", include_holidays=False):
    """Arbeitsfreie Tage des Monats: immer Sa/So, optional die Feiertage des
    Bundeslands.

    holidays_de wird lazy importiert, damit dieses Modul ohne die
    holidays-Lib importierbar bleibt. get_holidays ist intern gecached und
    liefert bei leerem/ungültigem Bundesland {} — der Minuten-Poll darf es
    also direkt aufrufen.
    """
    last_day = calendar.monthrange(year, month)[1]
    days = [datetime.date(year, month, d) for d in range(1, last_day + 1)]
    free = {d for d in days if d.weekday() >= 5}
    if include_holidays and state:
        from src.holidays_de import get_holidays
        feiertage = get_holidays(state, year)
        free |= {d for d in days if d in feiertage}
    return free


def is_due(now_dt, day, time_str, last_fired_month,
           shift_mode="none", free_dates=None):
    """True, wenn `now_dt` den Fällig-Zeitpunkt des aktuellen Monats erreicht
    hat und dieser Monat (`'YYYY-MM'`) noch nicht in `last_fired_month`
    steht. shift_mode/free_dates werden an scheduled_datetime durchgereicht."""
    current_month = f"{now_dt.year:04d}-{now_dt.month:02d}"
    if last_fired_month == current_month:
        return False
    due_at = scheduled_datetime(
        now_dt.year, now_dt.month, day, time_str, shift_mode, free_dates)
    if due_at is None:
        return False
    return now_dt >= due_at


DayReminder = namedtuple("DayReminder", ["end", "minutes"])


def _parse_hhmm_on(date, value):
    """'HH:MM' + date -> datetime; None/ungültig -> None."""
    hh_mm = _parse_hhmm(value)
    if hh_mm is None:
        return None
    hh, mm = hh_mm
    return datetime.datetime(date.year, date.month, date.day, hh, mm)


def due_day_reminder(reserved_slots, now_dt):
    """Der fällige tagesbezogene Sende-Reminder für die heutigen
    Reservierungs-Slots, oder None.

    Sucht den ersten Slot mit gültigem `send_reminder_minutes` (Invariante:
    höchstens einer pro Tag) und liefert ihn ab `now_dt >= end - minutes`.
    Kein oberes Fenster: startet die App erst nach dem Zeitpunkt, wird der
    Toast am selben Tag nachgeholt — ab dem Folgetag nicht mehr, weil der
    Aufrufer nur die Slots von heute übergibt.

    Ungültige Werte (kein parsebares Ende, Minuten außerhalb [0, 120] oder
    kein echtes int) werden übersprungen, wie in reminders.due_reminders.
    """
    date = now_dt.date()
    for slot in reserved_slots:
        minutes = slot.get("send_reminder_minutes")
        if isinstance(minutes, bool) or not isinstance(minutes, int):
            continue
        if not 0 <= minutes <= 120:
            continue
        end = _parse_hhmm_on(date, slot.get("end"))
        if end is None:
            continue
        if now_dt >= end - datetime.timedelta(minutes=minutes):
            return DayReminder(slot.get("end"), minutes)
        return None
    return None


def marked_reminder_dates(raw_reservations):
    """Die Tage mit gesetztem Erinnerungs-Marker, aus get_all_raw().

    Tombstones (`deleted`) zählen nicht, kaputte Datums-Keys werden
    übersprungen (der Store normalisiert Keys nicht).
    """
    out = []
    for date_str, entry in raw_reservations.items():
        if entry.get("deleted"):
            continue
        if not any(s.get("send_reminder_minutes") is not None
                   for s in entry.get("slots", [])):
            continue
        try:
            out.append(datetime.date.fromisoformat(date_str))
        except (ValueError, TypeError):
            continue
    return out


def monthly_anchor_dates(today, day, time_str, shift_mode="none", state="",
                         include_holidays=False, months_back=2):
    """Die Monatstermine des laufenden und der `months_back` vorangehenden
    Monate — inklusive Monatslängen-Clamp und Verschiebung.

    Zwei Vormonate reichen für die Anker-Suche, weil ein näherer Anker jeden
    älteren verdrängt.
    """
    out = []
    year, month = today.year, today.month
    for _ in range(months_back + 1):
        free = free_dates_for_month(year, month, state, include_holidays)
        due_at = scheduled_datetime(year, month, day, time_str, shift_mode, free)
        if due_at is not None:
            out.append(due_at.date())
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return out


def previous_anchor_date(today, marked_dates, monthly_dates):
    """Der jüngste Erinnerungs-Ankerpunkt echt VOR `today`, oder None.

    `today` selbst zählt nicht: der Zeitraum soll bis heute reichen, nicht
    bei heute beginnen.
    """
    candidates = [d for d in (*marked_dates, *monthly_dates) if d < today]
    return max(candidates) if candidates else None


def default_send_period(today, marked_dates, monthly_dates):
    """(von, bis) für den Sende-Dialog: Tag NACH dem vorherigen Anker bis
    heute (einschließlich). Kein Anker → None, der Aufrufer bleibt dann beim
    bisherigen Default."""
    anchor = previous_anchor_date(today, marked_dates, monthly_dates)
    if anchor is None:
        return None
    return anchor + datetime.timedelta(days=1), today
