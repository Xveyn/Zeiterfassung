"""Die Regeln hinter dem Anlegen einer Urlaubsperiode — Tk-frei.

`plan_vacation_save` (Tagesminuten aus der Eingabe) und `blocking_days` (Sperre
durch Ist-Zeit/Reservierung) lagen im Urlaubs-Dialog. Die lokale API (#239) ruft
dieselben Funktionen, statt neu zu rechnen; ein Import aus dem Dialog zöge
Tkinter und das Theme in einen Serverthread-Pfad, der davon frei bleiben soll.
`dialogs/vacation_dialog.py` importiert sie von hier unter ihren alten Namen.
"""

from src.time_utils import format_iso_date
from src.vacations import apportion_minutes, conflicting_days, expand_days

# Obergrenze je Urlaubstag. 24 h ist die einzige Grenze, die sich nicht
# diskutieren lässt — ein Kalendertag hat nicht mehr. Alles darunter wäre
# erfundene Policy: 10-Stunden-Tage gibt es, und ein Urlaubstag darf so lang
# sein wie der Arbeitstag, den er ersetzt.
MAX_HOURS_PER_DAY = 24
MAX_MINUTES_PER_DAY = MAX_HOURS_PER_DAY * 60


def hours_to_minutes_exact(hours: float) -> int:
    """Eingegebene Stunden → Minuten. Anders als `time_utils.hours_to_minutes`
    (das gerundete Dezimalstunden aus `calculate_hours` entgegennimmt) ist der
    Wert hier eine direkte Nutzereingabe — gerundet wird auf die nächste ganze
    Minute."""
    return int(round(hours * 60))


def plan_vacation_save(name, date_from, date_to, mode, value, overrides, state):
    """Baut die Tagesminuten einer Urlaubsperiode aus der Dialog-Eingabe.

    mode: "per_day" (value = Stunden je Arbeitstag) oder "total" (value =
    Gesamtstunden, die auf die Arbeitstage verteilt werden). `value` ist None,
    wenn im Stundenfeld keine Zahl steht.

    Kein Tag darf über MAX_HOURS_PER_DAY liegen. Geprüft wird das an allen
    drei Eingabewegen — Sammelwert, verteilte Gesamtstunden und den Overrides
    der Tagesliste; jeder für sich kann die Grenze reißen, und ohne die
    Prüfung landeten 48 h/Tag unbeanstandet im Store und im Bericht.
    overrides: {ISO: minutes} aus der aufgeklappten Tagesliste; sie gewinnen
    über den berechneten Wert. Tage außerhalb des Zeitraums werden ignoriert.
    state: Bundesland-Code für die Feiertagsliste.

    Liefert {"error": str|None, "days": {ISO: minutes}}. Alle Fehler sind
    bekannte, erwartete Fehler → der Aufrufer zeigt sie themed (Audit N14).
    """
    if not (name or "").strip():
        return {"error": "Bitte einen Namen für den Urlaub eingeben.", "days": {}}
    if date_to < date_from:
        return {"error": "Das Bis-Datum liegt vor dem Von-Datum.", "days": {}}
    if value is None:
        return {"error": "Bitte eine Zahl in das Stundenfeld eingeben.",
                "days": {}}
    if value < 0:
        return {"error": "Die Stundenzahl darf nicht negativ sein.", "days": {}}

    if mode == "total":
        # Erst die Arbeitstage ermitteln (Expansion mit 1 Minute als Marker),
        # dann die Gesamtminuten exakt auf sie verteilen.
        skeleton = expand_days(date_from, date_to, 1, state)
        workdays = [d for d, m in skeleton.items() if m]
        if not workdays:
            return {
                "error": ("Im Zeitraum liegt kein Arbeitstag, auf den die "
                          "Stunden verteilt werden könnten."),
                "days": {},
            }
        parts = apportion_minutes(hours_to_minutes_exact(value), len(workdays))
        if parts and max(parts) > MAX_MINUTES_PER_DAY:
            return {
                "error": (f"Die Gesamtstunden ergeben mehr als "
                          f"{MAX_HOURS_PER_DAY} Stunden pro Arbeitstag "
                          f"({len(workdays)} Arbeitstage im Zeitraum)."),
                "days": {},
            }
        days = {d: 0 for d in skeleton}
        # strict=True: die Längen sind per Konstruktion gleich, und `ruff` hat
        # B905 scharf (select enthält "B") — ein zip() ohne strict= macht den
        # Linter rot.
        for day, minutes in zip(sorted(workdays), parts, strict=True):
            days[day] = minutes
    else:
        minutes_per_day = hours_to_minutes_exact(value)
        if minutes_per_day > MAX_MINUTES_PER_DAY:
            return {
                "error": (f"Mehr als {MAX_HOURS_PER_DAY} Stunden pro Tag gibt "
                          f"es nicht."),
                "days": {},
            }
        days = expand_days(date_from, date_to, minutes_per_day, state)

    for day, minutes in overrides.items():
        if day in days:
            days[day] = max(0, int(minutes))

    # Nach den Overrides erneut: die Grenze oben deckt nur den Sammelwert ab,
    # ein einzelner Tag aus der Tagesliste kann sie danach immer noch reißen.
    over = sorted(d for d, m in days.items() if m > MAX_MINUTES_PER_DAY)
    if over:
        return {
            "error": (f"Für diese Tage sind mehr als {MAX_HOURS_PER_DAY} "
                      f"Stunden eingetragen:\n\n"
                      + format_day_list(over)),
            "days": {},
        }

    return {"error": None, "days": days}


def format_day_list(days, limit=8):
    """Die kollidierenden Tage als deutsche Datumsliste, ab `limit` gekürzt.

    Ein dreiwöchiger Urlaub über einem vollen Monat Arbeitszeit ergäbe sonst
    eine Fehlermeldung, die aus dem Bildschirm läuft.
    """
    shown = [format_iso_date(d) for d in days[:limit]]
    rest = len(days) - len(shown)
    if rest > 0:
        shown.append(f"… und {rest} weitere")
    return "\n".join(shown)


def blocking_days(days, entries, reservations, settings):
    """Tage der geplanten Periode, an denen schon Ist-Zeit oder eine
    Reservierung liegt (Regel in `vacations.conflicting_days`).

    `entries`/`reservations` sind die `get_all()`-Dicts der Stores (oder None,
    wenn es den Store nicht gibt); gezählt wird ein Tag nur mit Slots.
    Reservierungen zählen NUR, wenn sie eingeschaltet sind
    (`settings["reservations_enabled"]`, vgl. `reservations.reservations_active`)
    — sonst zeigt der Kalender sie nicht an und der Rechtsklick löscht sie
    nicht. Eine Sperre wegen einer unsichtbaren, nicht löschbaren
    Reservierung wäre eine Sackgasse. Unabhängig vom Google-Kalender.
    """
    entry_dates = [d for d, e in (entries or {}).items() if e.get("slots")]
    reservation_dates = (
        [d for d, r in (reservations or {}).items() if r.get("slots")]
        if settings.get("reservations_enabled") else [])
    return conflicting_days(days, entry_dates, reservation_dates)
