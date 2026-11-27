# pyright: reportOptionalMemberAccess=true
"""Anzeigetexte der Krankheitstage (Kalender, Löschauswahl, Verwaltung).

Tk-frei; Datum und Stunden kommen über die zentralen Formatierer.
"""

from __future__ import annotations

from src.sick_days import SickBlock
from src.time_utils import format_iso_date, format_minutes_hm


def _span(block: SickBlock) -> str:
    start = format_iso_date(block.date_from)
    if block.date_from == block.date_to:
        return start
    return f"{start} – {format_iso_date(block.date_to)}"


def block_label(block: SickBlock) -> str:
    """„Krankheit 02.03.2026 – 06.03.2026“, ein einzelner Tag ohne Spanne."""
    return f"Krankheit {_span(block)}"


def delete_key(block: SickBlock) -> str:
    """Schlüssel der Löschauswahl; der Block wird über seinen Anfang gefunden."""
    return "sick:" + block.date_from


def cell_tooltip(date_str: str, block: SickBlock, *,
                 vacation_name: str | None = None,
                 holiday: str | None = None) -> str:
    """Tooltip einer Kalenderzelle: Zeitraum, Tagesstunden (nur > 0), dazu
    ein überlagerter Urlaub und Feiertag."""
    lines = [f"Krank ({_span(block)})"]
    minutes = block.days.get(date_str, 0)
    if minutes > 0:
        lines.append(format_minutes_hm(minutes))
    if vacation_name is not None:
        lines.append(f"Urlaub: {vacation_name}")
    if holiday is not None:
        lines.append(f"Feiertag: {holiday}")
    return "\n".join(lines)


def manager_rows(blocks: list[SickBlock]) -> list[tuple[str, str]]:
    """Zeilen des Verwaltungs-Dialogs, neueste zuerst: (Zeitraum, Summe)."""
    ordered = sorted(blocks, key=lambda b: b.date_from, reverse=True)
    return [(_span(b), format_minutes_hm(b.total_minutes)) for b in ordered]
