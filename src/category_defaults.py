"""Pure Logik für Per-Kategorie-Standardzeiten (Start/Ende/Pause).

`category_times` ist ein Dict `{kategorie: {"start", "end", "pause"}}`, parallel
zur `categories`-Liste in den Settings. Fehlt eine Kategorie oder ein einzelnes
Feld (leer/None), gilt der globale Standardwert für genau dieses Feld — so
bleiben die globalen Standardzeiten wirksam, wenn eine Kategorie nichts
konfiguriert hat. Rein, ohne Tkinter/IO, daher direkt testbar.
"""


def resolve_slot_defaults(category_times, kategorie, g_start, g_end, g_pause):
    """(start, end, pause) für einen Slot der gegebenen Kategorie.

    Per-Feld-Fallback auf die globalen Werte (g_start/g_end/g_pause), wenn die
    Kategorie unbekannt ist, keinen Eintrag hat oder das jeweilige Feld leer
    bzw. ungültig ist. `pause=0` ist ein gültiger Wert und bleibt erhalten.
    """
    entry = category_times.get(kategorie) if isinstance(category_times, dict) else None
    if not isinstance(entry, dict):
        return g_start, g_end, g_pause

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
