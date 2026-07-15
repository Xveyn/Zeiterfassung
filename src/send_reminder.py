"""Pure Fälligkeits-Logik für den monatlichen Sende-Reminder (Tk-frei).

Ermittelt, ob am `now_dt` der konfigurierte Tag/Uhrzeit für die Erinnerung
"Arbeitszeiten verschicken" erreicht oder überschritten ist und für den
aktuellen Monat noch nicht gefeuert wurde. Tage jenseits der Monatslänge
(z.B. 31 im Februar) clampen auf den letzten Tag des Monats.
"""
import calendar
import datetime


def scheduled_datetime(year, month, day, time_str):
    """Fällig-Zeitpunkt für (year, month); `day` wird auf die tatsächliche
    Monatslänge geclamped (Tag 31 im Februar -> 28./29., im April -> 30.).
    `time_str` ungültig/kein 'HH:MM' -> None."""
    hh_mm = _parse_hhmm(time_str)
    if hh_mm is None:
        return None
    last_day = calendar.monthrange(year, month)[1]
    actual_day = min(max(day, 1), last_day)
    hh, mm = hh_mm
    return datetime.datetime(year, month, actual_day, hh, mm)


def _parse_hhmm(value):
    if not isinstance(value, str):
        return None
    try:
        hh, mm = value.split(":")
        return int(hh), int(mm)
    except (ValueError, TypeError):
        return None


def is_due(now_dt, day, time_str, last_fired_month):
    """True, wenn `now_dt` den Fällig-Zeitpunkt des aktuellen Monats erreicht
    hat und dieser Monat (`'YYYY-MM'`) noch nicht in `last_fired_month`
    steht."""
    current_month = f"{now_dt.year:04d}-{now_dt.month:02d}"
    if last_fired_month == current_month:
        return False
    due_at = scheduled_datetime(now_dt.year, now_dt.month, day, time_str)
    if due_at is None:
        return False
    return now_dt >= due_at
