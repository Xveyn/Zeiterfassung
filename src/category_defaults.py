"""Pure Logik für Per-Kategorie-Standardzeiten (Start/Ende/Pause).

`category_times` ist ein Dict `{kategorie: <Wert>}`, parallel zur `categories`-Liste.
`<Wert>` hat zwei Formen:

- **Allgemein** (kein ``mode`` oder ``mode != "per_day"``):
  ``{"start"?: str, "end"?: str, "pause"?: int}`` — ein Satz für alle Wochentage.

- **Per-Wochentag** (``mode == "per_day"``):
  ``{"mode": "per_day", "pause"?: int, "days": {<weekday>: {"start"?: str, "end"?: str}}}``

In beiden Formen gilt: Fehlt die Kategorie, ein `days`-Eintrag oder ein einzelnes
Feld (leer/None), greift der globale Standardwert für genau dieses Feld (Per-Feld-
Fallback). Rein, ohne Tkinter/IO, daher direkt testbar.
"""


def resolve_slot_defaults(category_times, kategorie, weekday_key,
                          g_start, g_end, g_pause):
    """(start, end, pause) für einen Slot der Kategorie am gegebenen Wochentag.

    - mode == "per_day": Start/Ende aus days[weekday_key] (Per-Feld-Fallback auf
      g_start/g_end), Pause aus top-level "pause".
    - sonst (mode fehlt / != "per_day"): heutiger Ein-Satz-Pfad.
    Per-Feld-Fallback auf die globalen Werte überall, wo ein Feld leer/None/
    ungültig oder Kategorie/Tag unbekannt ist. pause=0 bleibt gültig.
    """
    entry = category_times.get(kategorie) if isinstance(category_times, dict) else None
    if not isinstance(entry, dict):
        return g_start, g_end, g_pause

    if entry.get("mode") == "per_day":
        days = entry.get("days")
        day = days.get(weekday_key) if isinstance(days, dict) else None
        if not isinstance(day, dict):
            day = {}
        start = day.get("start") or g_start
        end = day.get("end") or g_end
    else:
        start = entry.get("start") or g_start
        end = entry.get("end") or g_end

    pause = entry.get("pause")
    if pause is None or pause == "":
        pause = g_pause
    else:
        try:
            pause = int(pause)
        except (TypeError, ValueError):
            pause = g_pause

    return start, end, pause
