"""Wochenstunden-Limit für einen konfigurierbaren Zeitraum (z.B. das
Werkstudenten-Privileg während der Vorlesungszeit, § 6 Abs. 1 Nr. 3 SGB V).

Pure Logik (kein Tk, kein I/O): prüft, ob die Ist-Stunden-Summe (alle
Kategorien; Reservierungen zählen NICHT mit, siehe reservations.py-Docstring)
einer ISO-Woche das konfigurierte Limit überschreitet, wenn ein Datum in den
konfigurierten Zeitraum fällt. Default ist das Limit deaktiviert
(`werkstudent_limit_enabled=False`, siehe settings.py DEFAULTS) — bestehende
Nutzer sehen ohne bewusste Aktivierung keinerlei Änderung im Verhalten.

Bewusste Vereinfachung, kein Rechtsgutachten: Das tatsächliche Werkstudenten-
privileg (Gemeinsames Rundschreiben GKV-Spitzenverband/DRV Bund/BA vom
23.11.2016, Abschnitt 1.2.4) bewertet nicht rückwirkend aufsummierte
Ist-Stunden pro Kalenderwoche, sondern die vereinbarte/regelmäßige
Wochenarbeitszeit des Beschäftigungsverhältnisses — mit einer bis zu
zweiwöchigen Übergangstoleranz am Rand von Vorlesungszeit/Semesterferien und
einer separaten rollierenden 26-Wochen/Jahres-Zählung. Dieses Modul kennt
beides nicht: eine ISO-Woche zählt hier immer vollständig (inkl. Tage
außerhalb des konfigurierten Zeitraums), sobald ein Tag dieser Woche aktiv
ist (siehe check_dates_for_warnings-Docstring); es gibt keine Toleranzzone
und keinen Jahres-Rückblick. Die Warnung ist eine grobe Näherung/Erinnerung,
keine rechtsverbindliche Aussage — für Grenzfälle bleibt eine echte Prüfung
(z.B. durch die Krankenkasse) nötig. Ein Issue, das dieses Modul näher an die
Rundschreiben-Logik heranführen würde, ist als optionale Idee im Repo
vermerkt (#98-Nachfolge, aktuell unentschieden)."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any, Iterable

from src.time_utils import calculate_hours, get_week_dates, get_week_label

if TYPE_CHECKING:  # nur fuer die Signaturen
    from src.settings import SettingsLike


def is_limit_active(settings: SettingsLike, date_str: str) -> bool:
    """True, wenn das Werkstudenten-Limit aktiv ist UND date_str (ISO) im
    konfigurierten Zeitraum liegt. Deaktiviertes Limit oder leerer/fehlender
    Zeitraum -> False."""
    if not settings.get("werkstudent_limit_enabled"):
        return False
    start = settings.get("werkstudent_limit_start")
    end = settings.get("werkstudent_limit_end")
    if not start or not end:
        return False
    return start <= date_str <= end


def week_ist_hours(all_entries: dict[str, Any], iso_year: int, iso_week: int) -> float:
    """Summe der Ist-Stunden (alle Kategorien) einer ISO-Woche.

    all_entries: {date_str: {slots: [...]}} wie von Storage.get_all()."""
    total = 0.0
    for day in get_week_dates(iso_year, iso_week):
        entry = all_entries.get(day.isoformat())
        if not entry:
            continue
        for slot in entry["slots"]:
            total += calculate_hours(
                slot.get("start"), slot.get("end"), slot.get("pause", 0))
    return round(total, 2)


def check_week_limit(settings: SettingsLike, all_entries: dict[str, Any],
                     date_str: str) -> dict[str, Any] | None:
    """Prüft, ob date_str im konfigurierten Werkstudenten-Zeitraum liegt und
    die Ist-Stunden-Summe der zugehörigen ISO-Woche das Limit überschreitet.

    Liefert None (Limit inaktiv, Datum außerhalb, oder Summe <= Limit) oder
    ein Dict {iso_year, iso_week, total_hours, limit_hours} bei
    Überschreitung."""
    if not is_limit_active(settings, date_str):
        return None
    day = datetime.date.fromisoformat(date_str)
    iso = day.isocalendar()
    total = week_ist_hours(all_entries, iso.year, iso.week)
    limit = settings.get("werkstudent_limit_max_hours")
    if total <= limit:
        return None
    return {
        "iso_year": iso.year, "iso_week": iso.week,
        "total_hours": total, "limit_hours": limit,
    }


def check_dates_for_warnings(settings: SettingsLike, all_entries: dict[str, Any],
                             date_strs: Iterable[str]) -> list[dict[str, Any]]:
    """Prüft eine Menge von Daten (z.B. neu importierte Reservierungs-Slots)
    auf Wochenlimit-Überschreitung. Dedupliziert nach ISO-Woche (ein Datum
    pro Woche reicht für den Check). Liefert eine Liste von
    Überschreitungs-Dicts (siehe check_week_limit), höchstens eine pro
    betroffener Woche.

    Inaktive Daten (außerhalb des konfigurierten Zeitraums) werden VOR dem
    Dedupe gefiltert, nicht erst in check_week_limit — sonst markiert ein
    frühes, inaktives Datum die Woche fälschlich als 'geprüft' und ein
    späteres, aktives Datum derselben ISO-Woche würde nie berechnet (Bug:
    ein realer Verstoß nach Kalender-Import bliebe unbemerkt, wenn der
    Zeitraum mitten in einer Woche beginnt/endet)."""
    seen_weeks = set()
    warnings = []
    for date_str in sorted(set(date_strs)):
        if not is_limit_active(settings, date_str):
            continue
        iso = datetime.date.fromisoformat(date_str).isocalendar()
        week_key = (iso.year, iso.week)
        if week_key in seen_weeks:
            continue
        seen_weeks.add(week_key)
        result = check_week_limit(settings, all_entries, date_str)
        if result is not None:
            warnings.append(result)
    return warnings


def scan_period_for_warnings(settings: SettingsLike,
                             all_entries: dict[str, Any]) -> list[dict[str, Any]]:
    """Scannt den kompletten konfigurierten Werkstudenten-Zeitraum (falls
    aktiv) Woche für Woche auf Limit-Überschreitung. Liefert eine Liste von
    Überschreitungs-Dicts (siehe check_week_limit), eine pro überschrittener
    Woche. Leere Liste, wenn das Limit inaktiv ist, kein/ungültiger Zeitraum
    konfiguriert ist, oder keine Woche überschritten wird."""
    if not settings.get("werkstudent_limit_enabled"):
        return []
    start = settings.get("werkstudent_limit_start")
    end = settings.get("werkstudent_limit_end")
    if not start or not end:
        return []
    start_date = datetime.date.fromisoformat(start)
    end_date = datetime.date.fromisoformat(end)
    if start_date > end_date:
        return []
    dates = []
    day = start_date
    while day <= end_date:
        dates.append(day.isoformat())
        day += datetime.timedelta(days=1)
    return check_dates_for_warnings(settings, all_entries, dates)


def format_limit_warnings(warnings: Iterable[dict[str, Any]]) -> str:
    """Formatiert eine Liste von Überschreitungs-Dicts (siehe
    check_week_limit) zu einem mehrzeiligen Anzeige-Text für einen
    Warn-Dialog."""
    return "\n".join(
        f"– {get_week_label(w['iso_year'], w['iso_week'])}: "
        f"{w['total_hours']:.2f}h (Limit {w['limit_hours']:.2f}h)"
        for w in warnings
    )


def period_scan_needed(old: dict[str, Any], new: dict[str, Any]) -> bool:
    """Entscheidet, ob ein voller Zeitraum-Scan (scan_period_for_warnings)
    nötig ist, wenn sich die Werkstudenten-Limit-Settings von old nach new
    ändern. old/new: Dicts {"enabled", "start", "end", "max_hours"}.

    True bei Aktivierung (enabled False -> True) sowie bei jeder Zeitraum-
    oder Stundenlimit-Änderung, SOLANGE das Limit in new aktiv ist — eine
    Verschärfung des Stundenlimits bei unverändertem Zeitraum muss den Scan
    genauso auslösen wie eine Zeitraum-Änderung, weil genau das der
    Kontrollpunkt ist, an dem neue Verstöße gegen bestehende Daten sichtbar
    werden (Adversarial-Review-Fix). False, wenn new deaktiviert ist oder
    sich nichts geändert hat."""
    if not new["enabled"]:
        return False
    if not old["enabled"]:
        return True
    return (new["start"] != old["start"] or new["end"] != old["end"]
            or new["max_hours"] != old["max_hours"])
