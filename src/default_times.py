# pyright: reportOptionalMemberAccess=true
"""Pure Logik der globalen Standardzeiten: Allgemein oder Tageweise.

Gespeichert werden immer die 14 Schlüssel `default_start_<tag>`/
`default_end_<tag>`; alle Leser (Tages-Dialog, Handy-Abgleich, Kategorien)
bleiben davon unberührt. „Allgemein" schreibt denselben Wert in alle sieben
Tage, `default_times_mode` merkt sich nur, welche Darstellung der Nutzer
gewählt hat. Rein, ohne Tkinter/IO.
"""

from collections.abc import Mapping

from src.i18n import N_, t
from src.settings import WEEKDAY_KEYS

MODE_GENERAL = "general"
MODE_PER_DAY = "per_day"

MODE_LABEL_KEYS = {MODE_GENERAL: N_("standardzeiten.modus_allgemein"),
                   MODE_PER_DAY: N_("standardzeiten.modus_tageweise")}


def mode_labels() -> dict[str, str]:
    """Moduscode → Anzeigetext in der aktuellen Sprache (beim Aufruf aufgelöst)."""
    return {code: t(MODE_LABEL_KEYS[code]) for code in MODE_LABEL_KEYS}


def mode_label(code: str) -> str:
    labels = mode_labels()
    return labels.get(code, labels[MODE_GENERAL])


def mode_code(label: str) -> str:
    """Anzeigetext der Combobox → Moduswert; Unbekanntes gilt als Tageweise,
    damit nie Tageswerte durch einen unlesbaren Wert verworfen werden."""
    return {text: code for code, text in mode_labels().items()}.get(label, MODE_PER_DAY)


def days_differ(starts: Mapping[str, str], ends: Mapping[str, str]) -> bool:
    """True, wenn nicht alle sieben Tage dieselbe Start- und Endzeit tragen."""
    return (len({starts[k] for k in WEEKDAY_KEYS}) > 1
            or len({ends[k] for k in WEEKDAY_KEYS}) > 1)


def resolve_mode(stored: object, starts: Mapping[str, str],
                 ends: Mapping[str, str]) -> str:
    """Gespeicherter Modus, sonst aus den Zeiten abgeleitet.

    Ohne gültigen Wert (frische Installation, Update von einer Version ohne
    Modus) startet der Tab „Allgemein", wenn alle Tage gleich sind, sonst
    „Tageweise" — niemand sieht seine Wochenplanung plötzlich eingeebnet."""
    if stored in (MODE_GENERAL, MODE_PER_DAY):
        return str(stored)
    return MODE_PER_DAY if days_differ(starts, ends) else MODE_GENERAL


def general_from_days(starts: Mapping[str, str],
                      ends: Mapping[str, str]) -> tuple[str, str]:
    """Vorbelegung des Allgemein-Paars beim Wechsel von Tageweise: Montag."""
    return starts["mon"], ends["mon"]


def days_for_per_day(starts: Mapping[str, str], ends: Mapping[str, str],
                     general_start: str,
                     general_end: str) -> tuple[dict[str, str], dict[str, str]]:
    """Tageswerte nach dem Wechsel auf Tageweise.

    Sind alle Tage gleich, trägt das Raster die (evtl. gerade geänderten)
    Allgemein-Werte; weichen sie ab, bleiben sie unangetastet — ein Hin- und
    Herschalten vor dem Speichern darf keine Tageswerte kosten."""
    if days_differ(starts, ends):
        return dict(starts), dict(ends)
    return ({k: general_start for k in WEEKDAY_KEYS},
            {k: general_end for k in WEEKDAY_KEYS})


def spread(start: str, end: str) -> dict[str, str]:
    """Settings-Werte für „Allgemein": dasselbe Paar in alle sieben Tage."""
    updates: dict[str, str] = {}
    for key in WEEKDAY_KEYS:
        updates[f"default_start_{key}"] = start
        updates[f"default_end_{key}"] = end
    return updates

