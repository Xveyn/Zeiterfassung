"""Nur-Werktage-Modus: Wochenende (Sa/So) überall deaktivieren.

Pure Logik, Tk-frei — wie `weekly_limit.py`/`pause_requirement.py`. Die
Einstellung `workweek_only` blendet Sa/So aus Kalender, Standardzeiten und
Bericht aus, **ohne Daten zu löschen**: Die Einträge bleiben im Storage und
tauchen wieder auf, sobald die Einstellung zurückgenommen wird.

Bewusst nicht hier: das Werkstudenten-Limit (zählt real geleistete Stunden,
auch am Wochenende), das Teilen von Rohdaten und der Kalender-Abgleich.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # nur fuer die Signaturen
    from src.settings import SettingsLike


def is_weekend(date_str: str) -> bool:
    """Ist der ISO-Datumsschlüssel ein Samstag oder Sonntag?

    Ein unlesbarer Schlüssel gilt als **nicht** Wochenende: Filtern darf nie
    Daten verschlucken, die es nicht sicher zuordnen kann.
    """
    try:
        return datetime.date.fromisoformat(date_str).weekday() >= 5
    except (TypeError, ValueError):
        return False


def filter_for_report(entries: dict[str, Any],
                      settings: SettingsLike) -> dict[str, Any]:
    """Ein ISO-Datum-keyed Dict ohne Wochenendtage — wenn `workweek_only`
    aktiv ist. Gefiltert wird rein über den Schlüssel (`is_weekend`); die
    Werte bleiben unangesehen, deshalb bedient dieselbe Funktion sowohl den
    Entries-Snapshot (`storage.get_all()`) als auch, seit dem Urlaubs-Feature,
    den `{ISO: minutes}`-Snapshot von `VacationStore.day_minutes()`.

    Bei inaktiver Einstellung wird das Eingabe-Dict unverändert
    zurückgegeben (nicht kopiert); sonst entsteht ein neues Dict, das Original
    bleibt unangetastet.

    Angewendet wird das am Snapshot der Dialoge, nicht in `report.py` — so
    bleibt der Report settings-frei, und Mail-HTML, PDF und Stunden-Vorschau
    sehen automatisch dieselben Daten.
    """
    if not settings.get("workweek_only"):
        return entries
    return {k: v for k, v in entries.items() if not is_weekend(k)}


def count_weekend_entries(entries: dict[str, Any], date_from: datetime.date,
                          date_to: datetime.date) -> int:
    """Anzahl der Wochenend-Tage mit Eintrag im Zeitraum (Grenzen inklusive).

    Für die Hinweiszeile im Sende-/Export-Dialog — gezählt wird deshalb auf dem
    **ungefilterten** Snapshot. `date_from`/`date_to` sind `datetime.date`.
    """
    from_str = date_from.isoformat()
    to_str = date_to.isoformat()
    return sum(1 for k in entries if from_str <= k <= to_str and is_weekend(k))
