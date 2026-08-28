"""Pausenpflicht nach § 4 ArbZG: Warnung, wenn die für einen Tag eingetragene
Pause die gesetzliche Mindestpause für die geleistete Netto-Arbeitszeit
unterschreitet.

Pure Logik (kein Tk, kein I/O), analog weekly_limit.py. Bewusste
Vereinfachung, kein Rechtsgutachten: gezählt werden ausschließlich die
`pause`-Felder der Slots eines Tages — eine Lücke ZWISCHEN zwei Slots
desselben Tages (z.B. eine Mittagspause per Kommen/Gehen zwischen zwei
Einträgen) zählt hier nicht als Pause, weil dieses Datenmodell solche Lücken
nirgends als Pause erfasst (vgl. grid_renderer.py::_fmt_cell_hours). Damit
das nicht stillschweigend zu falschen Warnungen führt, macht der
aufrufende Dialog diese Einschränkung im Warntext transparent, statt sie zu
verstecken.

Geprüft wird ausschließlich § 4 Satz 1 (Gesamtdauer der Pause). Die Schwellen
sind gesetzlich vorgegeben, also anders als weekly_limit's Werkstudenten-Limit
bewusst NICHT konfigurierbar:
- Arbeitszeit > 6h bis 9h: mindestens 30 Minuten Pause
- Arbeitszeit > 9h: mindestens 45 Minuten Pause insgesamt
- Arbeitszeit <= 6h: keine Pflichtpause

NICHT geprüft, weil dieses Datenmodell weder Lage noch Stückelung der Pause
speichert (ein Slot trägt nur eine Minutenzahl):
- Satz 2 (Pause aufteilbar in Abschnitte von je mindestens 15 Minuten): eine
  eingetragene `pause: 30`, real genommen als 3x10 Minuten, gilt hier als
  konform, wäre es aber nicht.
- Satz 3 (nie länger als 6 Stunden am Stück ohne Pause): ein 10h-Slot mit
  `pause: 45` besteht diesen Check auch dann, wenn die Pause am Ende lag.
Ein grünes Ergebnis heißt also „Pausendauer reicht", nicht „gesetzeskonform".

Quelle: https://www.gesetze-im-internet.de/arbzg/__4.html
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.time_utils import calculate_hours

if TYPE_CHECKING:  # nur fuer die Signaturen
    from src.settings import SettingsLike

REQUIRED_PAUSE_OVER_6H = 30
REQUIRED_PAUSE_OVER_9H = 45


def required_pause_minutes(worked_hours: float) -> int:
    """Gesetzliche Mindestpause (Minuten) für `worked_hours` Netto-Arbeitszeit.
    0, wenn keine Pflichtpause greift (<=6h)."""
    if worked_hours > 9:
        return REQUIRED_PAUSE_OVER_9H
    if worked_hours > 6:
        return REQUIRED_PAUSE_OVER_6H
    return 0


def check_day_pause(settings: SettingsLike,
                    ist_slots: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Prüft, ob die in `ist_slots` eingetragene Pause (Summe der
    `pause`-Felder) die gesetzliche Mindestpause für die Netto-Arbeitszeit
    des Tages unterschreitet.

    settings: Settings-artiges Dict/Objekt mit `pause_warning_enabled`.
    ist_slots: Liste von Slot-Dicts wie im Storage (start/end/pause) —
    ungespeichert oder simulierter Post-Save-Stand, Aufrufer entscheidet.

    Liefert None (Warnung deaktiviert, keine Slots, oder Pause ausreichend)
    oder {worked_hours, actual_pause_minutes, required_pause_minutes} bei
    Unterschreitung."""
    if not settings.get("pause_warning_enabled"):
        return None
    if not ist_slots:
        return None
    worked_hours = round(sum(
        calculate_hours(s["start"], s["end"], pause_minutes=s.get("pause", 0))
        for s in ist_slots
    ), 2)
    required = required_pause_minutes(worked_hours)
    if required == 0:
        return None
    actual_pause = sum(int(s.get("pause", 0)) for s in ist_slots)
    if actual_pause >= required:
        return None
    return {
        "worked_hours": worked_hours,
        "actual_pause_minutes": actual_pause,
        "required_pause_minutes": required,
    }
