import datetime

DAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
WEEKDAYS_DE_FULL = [
    "Montag", "Dienstag", "Mittwoch", "Donnerstag",
    "Freitag", "Samstag", "Sonntag",
]
MONTHS_DE = [
    "", "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def utc_now_iso():
    """Aktueller UTC-Zeitstempel als ISO-String 'YYYY-MM-DDTHH:MM:SSZ'.

    Z-Suffix statt +00:00 (JS/Drive-Konvention), Sekunden-Auflösung, kein
    Millisekunden-Anteil. Single Source of Truth für alle Sync-/Persistenz-
    Timestamps — war früher 6× privat als `_utc_now_iso` in
    storage/reservations/reservations_sync/settings/share/sync dupliziert
    (Audit N17). An dieser Sekunden-Auflösung + Wanduhr-Abhängigkeit hängt das
    LWW-Tie-Break im Sync (vgl. sync.py), daher nicht ohne Bedacht ändern.
    """
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(time_str):
    """Parse HH:MM string. Returns (hours, minutes) or None if invalid."""
    try:
        parts = time_str.split(":")
        if len(parts) != 2:
            return None
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return (h, m)
    except (ValueError, AttributeError):
        return None

def calculate_hours(start_str, end_str, pause_minutes=0):
    """Calculate decimal hours between two HH:MM strings, minus pause."""
    start = parse_time(start_str)
    end = parse_time(end_str)
    if start is None or end is None:
        return 0.0
    start_min = start[0] * 60 + start[1]
    end_min = end[0] * 60 + end[1]
    return max(0.0, round((end_min - start_min - pause_minutes) / 60, 2))

def validate_entry(start_str, end_str, pause_minutes=0):
    """Validate a time entry. Returns (ok, error_message)."""
    start = parse_time(start_str)
    if start is None:
        return False, "Startzeit ungültig (Format: HH:MM)"
    end = parse_time(end_str)
    if end is None:
        return False, "Endzeit ungültig (Format: HH:MM)"
    start_min = start[0] * 60 + start[1]
    end_min = end[0] * 60 + end[1]
    if end_min <= start_min:
        return False, "Endzeit muss nach Startzeit liegen"
    working_min = end_min - start_min
    if pause_minutes < 0:
        return False, "Pause darf nicht negativ sein"
    if pause_minutes >= working_min:
        return False, f"Pause ({pause_minutes} Min) muss kleiner als die Arbeitszeit ({working_min} Min) sein"
    return True, ""


def validate_period(date_from, date_to):
    """Validiert einen Datums-Zeitraum für Bericht/Export. Liefert
    (ok, fehlermeldung). von > bis ist ungültig; von == bis ist erlaubt
    (Ein-Tages-Bericht)."""
    if date_from > date_to:
        return False, "Das Von-Datum muss vor dem Bis-Datum liegen."
    return True, ""

def get_week_dates(iso_year, iso_week):
    """Return list of 7 datetime.date objects (Mon-Sun) for the given ISO week."""
    monday = datetime.date.fromisocalendar(iso_year, iso_week, 1)
    return [monday + datetime.timedelta(days=i) for i in range(7)]


def format_date(d):
    """date/datetime → 'TT.MM.JJJJ' für die Anzeige (deutsches UI-Format).

    Objekt-Pendant zu format_iso_date (das einen ISO-String erwartet):
    zentralisiert das über Dialoge und Report verstreute
    `d.strftime('%d.%m.%Y')` (Audit N20). ISO bleibt die Speicher-/interne
    Quelle — dies ist reine Anzeige-Formatierung.
    """
    return d.strftime("%d.%m.%Y")


def get_week_label(iso_year, iso_week):
    """Return display label like 'KW 14 · 30.03. – 05.04.2026'."""
    dates = get_week_dates(iso_year, iso_week)
    monday = dates[0]
    sunday = dates[6]
    if monday.year != sunday.year:
        return f"KW {iso_week} · {format_date(monday)} – {format_date(sunday)}"
    return f"KW {iso_week} · {monday.strftime('%d.%m.')} – {format_date(sunday)}"


def week_spans_months(iso_year, iso_week):
    """Return True if the week spans two different months."""
    dates = get_week_dates(iso_year, iso_week)
    return dates[0].month != dates[6].month


def format_iso_date(iso, fallback="—"):
    """ISO-Datum oder -Zeitstempel → 'TT.MM.JJJJ' für die Anzeige.

    Akzeptiert sowohl reine Daten ('2026-06-02') als auch Zeitstempel
    ('2026-06-02T14:30:00Z'). Leere oder unparsbare Werte liefern `fallback`.
    """
    if not iso or len(iso) < 10:
        return fallback
    try:
        return format_date(datetime.date.fromisoformat(iso[:10]))
    except ValueError:
        return iso[:10]


def format_iso_weekday_date(iso, fallback="—"):
    """ISO-Datum oder -Zeitstempel → 'Wochentag - TT.MM.JJJJ' für die Anzeige
    (z.B. 'Montag - 13.07.2026'). Leere oder unparsbare Werte liefern denselben
    Fallback-Weg wie format_iso_date (fallback bzw. roher 10-Zeichen-Prefix).
    """
    if not iso or len(iso) < 10:
        return fallback
    try:
        day = datetime.date.fromisoformat(iso[:10])
    except ValueError:
        return iso[:10]
    return f"{WEEKDAYS_DE_FULL[day.weekday()]} - {format_date(day)}"


def format_iso_datetime(iso, fallback="—"):
    """ISO-Zeitstempel → 'TT.MM.JJJJ HH:MM' für die Anzeige.

    Die Uhrzeit wird unverändert aus dem String übernommen (keine
    Zeitzonen-Umrechnung). Fehlt der Zeitanteil, wird nur das Datum gezeigt.
    Leere oder unparsbare Werte liefern `fallback`.
    """
    if not iso or len(iso) < 10:
        return fallback
    date_part = format_iso_date(iso, fallback)
    if len(iso) >= 16 and iso[10] in ("T", " "):
        return f"{date_part} {iso[11:16]}"
    return date_part


def slots_overlap(slots):
    """True, wenn sich zwei Slots zeitlich überlappen.

    `slots`: Liste von Dicts mit 'start'/'end' (HH:MM). Slots mit unparsbarer
    Zeit werden übersprungen (Format-Fehler fängt validate_slots separat ab).
    Angrenzend (Ende == Start des nächsten) gilt NICHT als Überlappung.
    """
    intervals = []
    for s in slots:
        start = parse_time(s.get("start"))
        end = parse_time(s.get("end"))
        if start is None or end is None:
            continue
        intervals.append((start[0] * 60 + start[1], end[0] * 60 + end[1]))
    intervals.sort()
    for (_prev_start, prev_end), (next_start, _next_end) in zip(intervals, intervals[1:], strict=False):
        if next_start < prev_end:
            return True
    return False


def validate_slots(slots, with_pause=True):
    """Validiert eine Slot-Liste: jeden Slot einzeln (validate_entry) und die
    zeitliche Überlappungsfreiheit. Liefert (ok, fehlermeldung).

    with_pause=False (Reservierungen): das Pause-Feld wird ignoriert (als 0
    behandelt). Eine leere Liste ist gültig (ok, "")."""
    for s in slots:
        if with_pause:
            try:
                pause = int(s.get("pause", 0))
            except (TypeError, ValueError):
                return False, "Pause muss eine ganze Zahl (Minuten) sein."
        else:
            pause = 0
        ok, msg = validate_entry(s.get("start"), s.get("end"), pause_minutes=pause)
        if not ok:
            return False, msg
    if slots_overlap(slots):
        return False, "Zeitslots dürfen sich zeitlich nicht überlappen."
    return True, ""
