# pyright: reportOptionalMemberAccess=true
from __future__ import annotations

import datetime
import html
import io
from collections import OrderedDict
from typing import Any, Collection, Literal

from src import slot_notes
from src.slot_order import sorted_slots
from src.time_utils import DAYS_DE, calculate_hours, format_date, get_week_label, hours_to_minutes
from src.absence import (
    AbsenceCut,
    CappedDay,
    cap_notice,
    cut_for_output,
    sick_on_vacation_notice,
)


def _esc(text: str | None) -> str:
    return html.escape(text or "", quote=True)


def _esc_multiline(text: str | None) -> str:
    return _esc(text).replace("\n", "<br>")


# Die Wochen-Gruppierung reist durch drei Funktionen (_group_by_week ->
# _build_table -> _week_block); als Alias steht die Form einmal statt dreimal.
WeekEntries = list[tuple[str, dict[str, Any]]]
WeekGroups = OrderedDict[tuple[int, int], WeekEntries]

COLUMN_LABELS = ["Datum", "Tag", "Kategorie", "Start", "Ende", "Stunden"]

# Explizite Spaltenbreiten (Summe 100%) für die 6-spaltige Stundentabelle.
# Browser layouten automatisch (E-Mail-HTML braucht keine Breiten), xhtml2pdf
# dagegen kollabiert mit den colspan-Zeilen (KW-Header/Summen) die linken
# Spalten ineinander. <colgroup>/<col width> ignoriert xhtml2pdf, und eine
# width-Angabe nur am Header reicht nicht — die Breiten müssen an *jeder*
# regulären 6-Spalten-Zelle (Header + Datenzeilen) stehen, damit ReportLab
# trotz der SPAN-Zeilen ein konsistentes Raster bildet. Daher führt nur
# PDF_STYLE Breiten, HTML_STYLE leere.
_PDF_COL_WIDTHS = ["15%", "8%", "25%", "16%", "16%", "20%"]

# Style-Dict pro Render-Ziel. Felder werden direkt als CSS-Strings in die
# Inline-Styles der Zellen geschrieben. `c_sub`/`c_sub_hours` stehen in der Zelle
# nach `td_base`, damit ihr `padding-left` dessen `padding` überschreibt.
HTML_STYLE = {
    "keep_together": False,
    "col_widths":  ["", "", "", "", "", ""],
    "table_extra": "border-radius:8px;overflow:hidden;",
    "th_row":      "background:#1e293b;",
    "th_cell":     "padding:10px 14px;text-align:left;color:#94a3b8;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;",
    "kw_row":      "background:#334155;",
    "kw_cell":     "padding:10px 14px;color:#ffffff;font-weight:600;font-size:13px;letter-spacing:0.03em;",
    "row_a":       "background:#1e293b;",
    "row_b":       "background:#243347;",
    "td_base":     "padding:10px 14px;border-bottom:1px solid rgba(255,255,255,0.08);",
    "c_date":      "color:#cbd5e1;",
    "c_day":       "color:#94a3b8;",
    "c_kat":       "color:#94a3b8;",
    "c_time":      "color:#cbd5e1;",
    "c_hours":     "color:#00D8A7;font-weight:600;",
    "sum_row":     "background:#263244;",
    "sum_lbl":     "padding:10px 14px;color:#cbd5e1;font-weight:600;",
    "sum_hrs":     "padding:10px 14px;color:#00D8A7;font-weight:700;",
    "total_row":   "background:#334155;",
    "total_lbl":   "padding:12px 14px;color:#ffffff;font-weight:700;",
    "total_hrs":   "padding:12px 14px;color:#00D8A7;font-weight:700;font-size:15px;",
    "footnote":    "margin:6px 0 0 0;color:#94a3b8;font-size:12px;line-height:1.4;",
    "c_sub":       "color:#94a3b8;padding-left:32px;",
    "c_sub_hours": "color:#cbd5e1;",
    "wrap_long":   "",
}

PDF_STYLE = {
    "keep_together": True,
    "col_widths":  _PDF_COL_WIDTHS,
    "table_extra": "",
    "th_row":      "background:#1e293b;",
    "th_cell":     "padding:8px 12px;text-align:left;color:#ffffff;font-size:11px;font-weight:600;text-transform:uppercase;",
    "kw_row":      "background:#e2e8f0;",
    "kw_cell":     "padding:8px 12px;color:#111827;font-weight:700;font-size:12px;",
    "row_a":       "background:#ffffff;",
    "row_b":       "background:#f1f5f9;",
    "td_base":     "padding:8px 12px;border-bottom:1px solid #d1d5db;",
    "c_date":      "color:#111827;",
    "c_day":       "color:#4b5563;",
    "c_kat":       "color:#4b5563;",
    "c_time":      "color:#111827;",
    "c_hours":     "color:#111827;font-weight:600;",
    "sum_row":     "background:#cbd5e1;",
    "sum_lbl":     "padding:8px 12px;color:#111827;font-weight:700;",
    "sum_hrs":     "padding:8px 12px;color:#111827;font-weight:700;",
    "total_row":   "background:#1e293b;",
    "total_lbl":   "padding:10px 12px;color:#ffffff;font-weight:700;",
    "total_hrs":   "padding:10px 12px;color:#ffffff;font-weight:700;",
    "footnote":    "margin:6px 0 0 0;color:#475569;font-size:10px;line-height:1.4;",
    "c_sub":       "color:#4b5563;padding-left:28px;",
    "c_sub_hours": "color:#4b5563;",
    "wrap_long":   "-pdf-word-wrap:CJK;",
}


# xhtml2pdf bricht kein Wort um, das breiter als seine Zelle ist: es läuft über die Nachbarspalten,
# 200 Zeichen am Stück aus der Seite. `-pdf-word-wrap:CJK` lässt es zwischen beliebigen Zeichen
# umbrechen. Gesetzt nur, wo ein Wort länger als `LONG_TOKEN` ist — die Kategorie-Spalte (25 %)
# fasst rund 28 Zeichen —, damit Zellen ohne solches Wort wie bisher umbrechen.
LONG_TOKEN = 24


def _has_long_token(text: str) -> bool:
    """Ob `text` ein Wort mit mehr als `LONG_TOKEN` Code Points enthält. Getrennt wird nur am
    Leerzeichen: an U+00A0 bricht xhtml2pdf nicht um, Tabs und Zeilenumbrüche hat `clean_note` entfernt."""
    return any(len(word) > LONG_TOKEN for word in text.split(" "))


def _slot_hours(slot: dict[str, Any]) -> float:
    return round(calculate_hours(slot["start"], slot["end"], pause_minutes=slot.get("pause", 0)), 2)


def _minutes_as_hours(minutes: int) -> float:
    """Minuten → Dezimalstunden für die Anzeige. Gerundet wird ERST hier,
    nachdem in Minuten summiert wurde (CLAUDE.md: Summen über Minuten)."""
    return round(minutes / 60, 2)


def _group_by_week(range_entries: dict[str, Any]) -> WeekGroups:
    """Group entries by ISO week, chronologically.

    Returns OrderedDict keyed by (iso_year, iso_week), value is list of
    (date_str, entry) tuples sorted by date.
    """
    groups = OrderedDict()
    for date_str in sorted(range_entries.keys()):
        entry = range_entries[date_str]
        dt = datetime.date.fromisoformat(date_str)
        iso = dt.isocalendar()
        key = (iso.year, iso.week)
        groups.setdefault(key, []).append((date_str, entry))
    return groups


def filter_period(date_from: datetime.date, date_to: datetime.date,
                  all_entries: dict[str, Any]) -> dict[str, Any] | None:
    """Einträge im Zeitraum [date_from, date_to], oder None wenn keiner drin
    liegt. Öffentlich, weil neben Mail-HTML und PDF auch die Webhook-Payload
    exakt denselben Ausschnitt braucht — zwei Filter-Implementierungen würden
    beim nächsten Detail auseinanderlaufen."""
    from_str = date_from.isoformat()
    to_str = date_to.isoformat()
    range_entries = {
        k: v for k, v in all_entries.items() if from_str <= k <= to_str
    }
    return range_entries if range_entries else None


def filter_categories(entries: dict[str, Any],
                      categories: Collection[str] | None) -> dict[str, Any]:
    """categories=None → unverändert. Sonst werden je Tag nur Slots behalten,
    deren Kategorie (oder "" für ohne) in `categories` liegt; Tage ohne
    verbleibende Slots fallen weg. Liefert ein neues Dict."""
    if categories is None:
        return entries
    cats = set(categories)
    out = {}
    for date_str, entry in entries.items():
        kept = [s for s in entry["slots"] if (s.get("kategorie") or "") in cats]
        if kept:
            out[date_str] = {"slots": kept}
    return out


def total_hours(date_from: datetime.date, date_to: datetime.date,
                all_entries: dict[str, Any],
                categories: Collection[str] | None = None) -> float:
    """Gesamtstunden im Zeitraum, gefiltert auf die gewählten Kategorien
    (None = alle). Summiert über Minuten je Slot — dieselbe Rechnung wie
    _build_table, damit Vorschau und Bericht nie auseinanderlaufen. Leerer
    Bereich → 0.0."""
    range_entries = filter_period(date_from, date_to, all_entries)
    if range_entries:
        range_entries = filter_categories(range_entries, categories)
    if not range_entries:
        return 0.0
    return _minutes_as_hours(sum(
        hours_to_minutes(_slot_hours(s))
        for e in range_entries.values() for s in e["slots"]))


def default_pdf_filename(date_from: datetime.date, date_to: datetime.date) -> str:
    """Default-Dateiname für den PDF-Bericht: Zeiterfassung_<VON>_<BIS>.pdf
    mit Datums-Stempeln im Format YYYYMMDD (z.B.
    Zeiterfassung_20260301_20260331.pdf). Genutzt vom Senden- (Mail-Anhang)
    und vom Export-Pfad."""
    return f"Zeiterfassung_{date_from:%Y%m%d}_{date_to:%Y%m%d}.pdf"


def _apply_placeholders(text: str, label: str, total: float) -> str:
    return text.replace("{zeitraum}", _esc(label)).replace("{gesamt}", _esc(f"{total}h"))


# _week_block / _build_table / _build_category_summary rendern Werte aus dem
# Storage. Datum/KW werden intern erzeugt (strftime / get_week_label) und sind
# vertrauenswürdig. start/end sind zwar über Entry-Dialog/Share/gcal auf
# [0-9:.-] validiert, aber der Drive-Sync (sync.apply_merged_doc) schreibt
# Remote-Slots ungeprüft in den Storage — ein manipuliertes Sync-Doc könnte rohes
# HTML einschleusen (Audit M7). Deshalb werden start/end defensiv _esc()-t,
# genau wie `kategorie` (freier Nutzertext).
def _week_block(iso_year: int, iso_week: int, week_entries: WeekEntries,
                style: dict[str, Any], slot_order: str = "chrono") -> tuple[str, int]:
    """Render einen Wochen-Block: KW-Header, je Slot eine Zeile, Tages-Subtotal
    bei >1 Slot, Wochensumme. Returns (rows_html, week_minutes).

    Summiert wird über MINUTEN (hours_to_minutes je Slot), nicht über
    Dezimalstunden — sonst weicht die ausgewiesene Summe von der Summe der
    angezeigten Einzelwerte ab (CLAUDE.md). Die Slot-Zeile selbst zeigt
    weiterhin ihre eigenen Dezimalstunden, sie ist keine Summe."""
    s = style
    cw = [f"width:{w};" if w else "" for w in s["col_widths"]]
    rows = [
        f"<tr style='{s['kw_row']}'>"
        f"<td colspan='6' style='{s['kw_cell']}'>{get_week_label(iso_year, iso_week)}</td>"
        f"</tr>"
    ]

    week_minutes = 0
    for idx, (date_str, entry) in enumerate(week_entries):
        dt = datetime.date.fromisoformat(date_str)
        weekday = DAYS_DE[dt.weekday()]
        day_fmt = format_date(dt)
        row_bg = s["row_a"] if idx % 2 == 0 else s["row_b"]
        td = s["td_base"]
        slots = sorted_slots(entry["slots"], slot_order)
        day_minutes = 0
        for sidx, slot in enumerate(slots):
            hours = _slot_hours(slot)
            minutes = hours_to_minutes(hours)
            day_minutes += minutes
            week_minutes += minutes
            date_cell = day_fmt if sidx == 0 else ""
            day_cell = weekday if sidx == 0 else ""
            note = slot_notes.clean_note(slot.get("notiz", ""))
            label = slot_notes.label(slot.get("kategorie") or "", note)
            # Nur Zeilen mit Notiz: eine Zeile ohne bleibt bytegleich, auch mit langer Kategorie.
            wrap = s["wrap_long"] if note and _has_long_token(label) else ""
            rows.append(
                f"<tr style='{row_bg}'>"
                f"<td style='{td}{cw[0]}{s['c_date']}'>{date_cell}</td>"
                f"<td style='{td}{cw[1]}{s['c_day']}'>{day_cell}</td>"
                f"<td style='{td}{cw[2]}{s['c_kat']}{wrap}'>{_esc(label)}</td>"
                f"<td style='{td}{cw[3]}{s['c_time']}'>{_esc(slot['start'])}</td>"
                f"<td style='{td}{cw[4]}{s['c_time']}'>{_esc(slot['end'])}</td>"
                f"<td style='{td}{cw[5]}{s['c_hours']}'>{hours}h</td>"
                f"</tr>"
            )
        if len(slots) > 1:
            rows.append(
                f"<tr style='{row_bg}'>"
                f"<td colspan='5' style='{td}{s['c_day']}'>Summe {day_fmt}</td>"
                f"<td style='{td}{s['c_hours']}'>{_minutes_as_hours(day_minutes)}h</td>"
                f"</tr>"
            )

    rows.append(
        f"<tr style='{s['sum_row']}'>"
        f"<td colspan='5' style='{s['sum_lbl']}'>Summe KW {iso_week}</td>"
        f"<td style='{s['sum_hrs']}'>{_minutes_as_hours(week_minutes)}h</td>"
        f"</tr>"
    )
    return "\n".join(rows), week_minutes


def _build_table(groups: WeekGroups, style: dict[str, Any],
                 slot_order: str = "chrono") -> tuple[str, int]:
    """Bauen die komplette Stundentabelle. Returns (table_html, total_minutes)."""
    s = style
    week_blocks = []
    total_minutes = 0
    for (iso_year, iso_week), week_entries in groups.items():
        block_html, week_minutes = _week_block(iso_year, iso_week, week_entries, s, slot_order)
        week_blocks.append(block_html)
        total_minutes += week_minutes

    th_cells = "".join(
        f'<th style="{s["th_cell"]}{f"width:{w};" if w else ""}">{label}</th>'
        for label, w in zip(COLUMN_LABELS, s["col_widths"], strict=False)
    )

    header_row = f'<tr style="{s["th_row"]}">{th_cells}</tr>'
    total_row = (
        f'<tr style="{s["total_row"]}">'
        f'<td colspan="5" style="{s["total_lbl"]}">Gesamt</td>'
        f'<td style="{s["total_hrs"]}">{_minutes_as_hours(total_minutes)}h</td>'
        f'</tr>'
    )
    table_open = f'<table style="border-collapse:collapse;width:100%;{s["table_extra"]}">'
    if not s.get("keep_together"):
        return (f'{table_open}{header_row}{"".join(week_blocks)}{total_row}</table>',
                total_minutes)

    # PDF: je Kalenderwoche eine eigene Tabelle, damit KW-Kopf, Tage und Wochensumme nicht an einer
    # Seitengrenze auseinanderfallen (#370). Eine einzige Tabelle teilt xhtml2pdf an beliebiger Zeile.
    # Den Spaltenkopf trägt nur die erste, die Gesamtzeile nur die letzte; die festen Spaltenbreiten
    # stehen an jeder Zelle, die Tabellen fluchten also. Ein Block, der länger als eine Seite ist,
    # darf sich weiter teilen.
    last = len(week_blocks) - 1
    tables = [
        _keep_together(
            f'{table_open}{header_row if i == 0 else ""}{block}{total_row if i == last else ""}</table>',
            s,
        )
        for i, block in enumerate(week_blocks)
    ]
    return "\n".join(tables), total_minutes


# xhtml2pdf teilt Tabellen zeilenweise und kennt kein `page-break-inside`. Ein Absatz mit
# `-pdf-keep-with-next` wird dagegen mit dem folgenden Element zusammengehalten: passt die ganze
# Tabelle nicht mehr auf die Seite, beginnt sie auf der nächsten — statt mit der Kopfzeile am
# Seitenende und den Zeilen darunter zu zerreißen (#368). Der Absatz ist unsichtbar (1 px).
_KEEP_WITH_NEXT = ('<p style="-pdf-keep-with-next:true;margin:0;padding:0;'
                   'font-size:1px;line-height:1px;">&nbsp;</p>')


def _keep_together(html: str, style: dict[str, Any]) -> str:
    """`html` (eine Tabelle) so voranstellen, dass das PDF sie nicht über eine
    Seitengrenze zerreißt. Nur der PDF-Stil tut das; das Mail-HTML bleibt unverändert
    (ein Mail-Client paginiert nicht). Leeres HTML bleibt leer."""
    if html and style.get("keep_together"):
        return _KEEP_WITH_NEXT + html
    return html


NO_NOTE_LABEL = "(ohne Notiz)"


def _note_rows(range_entries: dict[str, Any]) -> dict[str, list[tuple[str, int]]]:
    """Unterzeilen je Kategorie für die Aufschlüsselung nach Notiz: (Anzeige, Minuten).

    Nur Kategorien, in denen mindestens ein Slot eine Notiz trägt. Gruppiert nach
    `slot_notes.group_key`, angezeigt in der Schreibweise des ersten Vorkommens (Tage
    nach Datum, im Tag gespeicherte Reihenfolge), sortiert nach dem Schlüssel; Slots
    ohne Notiz bilden die letzte Zeile `NO_NOTE_LABEL`. Summiert wird über Minuten,
    damit die Unterzeilen genau die Kategorie-Zeile ergeben (CLAUDE.md).
    """
    groups: dict[str, dict[str, list[Any]]] = {}
    no_note: dict[str, int] = {}
    for date_str in sorted(range_entries):
        for slot in range_entries[date_str]["slots"]:
            kat = slot.get("kategorie") or ""
            minutes = hours_to_minutes(_slot_hours(slot))
            note = slot_notes.clean_note(slot.get("notiz", ""))
            if not note:
                no_note[kat] = no_note.get(kat, 0) + minutes
                continue
            group = groups.setdefault(kat, {}).setdefault(slot_notes.group_key(note), [note, 0])
            group[1] += minutes
    result: dict[str, list[tuple[str, int]]] = {}
    for kat, by_key in groups.items():
        rows = [(by_key[key][0], by_key[key][1]) for key in sorted(by_key)]
        if kat in no_note:
            rows.append((NO_NOTE_LABEL, no_note[kat]))
        result[kat] = rows
    return result


def _build_category_summary(range_entries: dict[str, Any],
                            style: dict[str, Any],
                            note_breakdown: bool = False) -> str:
    """„Summe je Kategorie"-Tabelle über den (gefilterten) Zeitraum. Leerer
    String ('' = keine Kategorie) wird als '(ohne Kategorie)' ans Ende
    sortiert. Liefert '' wenn keine Slots vorhanden — oder wenn alle Slots
    unkategorisiert sind (dann wäre die Tabelle nur die Gesamtsumme), außer
    `note_breakdown` schlüsselt sie nach Notiz auf.

    `note_breakdown`: unter jeder Kategorie mit Notizen deren Unterzeilen
    (`_note_rows`), im Zeilenhintergrund der Kategorie.

    Summiert wird über MINUTEN (hours_to_minutes je Slot), nicht über
    Dezimalstunden — sonst weicht die Kategorien-Summe von der Gesamtsumme
    der Stundentabelle ab, obwohl beide Zahlen im selben Bericht stehen
    (CLAUDE.md)."""
    s = style
    totals: dict[str, int] = {}
    for entry in range_entries.values():
        for slot in entry["slots"]:
            kat = slot.get("kategorie") or ""
            totals[kat] = totals.get(kat, 0) + hours_to_minutes(_slot_hours(slot))
    # Keine Slots, oder ausschließlich unkategorisierte: die Tabelle bestünde
    # dann nur aus der "(ohne Kategorie)"-Zeile = exakt die ohnehin gezeigte
    # Gesamtsumme. Weglassen, statt eine leere Pseudo-Aufschlüsselung zu zeigen.
    note_rows = _note_rows(range_entries) if note_breakdown else {}
    if not totals or (set(totals) == {""} and "" not in note_rows):
        return ""

    td = s["td_base"]
    rows = []
    for idx, kat in enumerate(sorted(totals, key=lambda k: (k == "", k.lower()))):
        label = kat if kat else "(ohne Kategorie)"
        hours = _minutes_as_hours(totals[kat])
        row_bg = s["row_a"] if idx % 2 == 0 else s["row_b"]
        rows.append(
            f"<tr style='{row_bg}'>"
            f"<td style='{td}{s['c_day']}'>{_esc(label)}</td>"
            f"<td style='{td}{s['c_hours']}'>{hours}h</td>"
            f"</tr>"
        )
        for sub_label, sub_minutes in note_rows.get(kat, []):
            wrap = s["wrap_long"] if _has_long_token(sub_label) else ""
            rows.append(
                f"<tr style='{row_bg}'>"
                f"<td style='{td}{s['c_sub']}{wrap}'>{_esc(sub_label)}</td>"
                f"<td style='{td}{s['c_sub_hours']}'>{_minutes_as_hours(sub_minutes)}h</td>"
                f"</tr>"
            )

    return _keep_together(
        f'<table style="border-collapse:collapse;width:100%;margin-top:16px;{s["table_extra"]}">'
        f'<tr style="{s["th_row"]}">'
        f'<th style="{s["th_cell"]}">Kategorie</th>'
        f'<th style="{s["th_cell"]}">Stunden</th>'
        f'</tr>'
        f'{"".join(rows)}'
        f'</table>',
        s,
    )


def _vacation_runs(vacation_days: dict[str, int]) -> list[tuple[str, str, int]]:
    """Zerlegt die Urlaubs- oder Krankheitstage ({ISO: minutes}) in
    zusammenhängende Blöcke.

    Liefert [(von, bis, minuten)] je Block, chronologisch. Ein Block bricht
    nur bei einer echten Kalenderlücke ab — die 0-Minuten-Tage einer Periode
    (Wochenende, Feiertag) halten ihn zusammen, sonst zerfiele jeder
    Zwei-Wochen-Urlaub in drei Zeilen.

    Getrennte Perioden ergeben getrennte Blöcke: eine einzige Zeile über
    min..max behauptete sonst 20 zusammenhängende Urlaubstage, wo zwei mal
    fünf waren — auf einem Dokument an den Arbeitgeber eine Falschaussage.

    Blöcke ohne eine einzige bezahlte Minute (nur Wochenende im Zeitraum)
    fallen weg.
    """
    if not vacation_days:
        return []
    runs: list[tuple[str, str, int]] = []
    days = sorted(vacation_days)
    start = days[0]
    prev = datetime.date.fromisoformat(start)
    minutes = vacation_days[start]
    for day in days[1:]:
        current = datetime.date.fromisoformat(day)
        if (current - prev).days > 1:
            if minutes:
                runs.append((start, prev.isoformat(), minutes))
            start, minutes = day, 0
        minutes += vacation_days[day]
        prev = current
    if minutes:
        runs.append((start, prev.isoformat(), minutes))
    return runs


def _absence_table(runs: list[tuple[str, str, int]], heading: str,
                   total_minutes: int | None, style: dict[str, Any]) -> str:
    """Tabelle „Urlaub“ bzw. „Krankheit“ mit einer Zeile je Block; mit
    `total_minutes` schließt „Zu vergüten gesamt“ sie ab."""
    s = style
    td = s["td_base"]
    rows = []
    for idx, (start, end, minutes) in enumerate(runs):
        label = (f"{format_date(datetime.date.fromisoformat(start))} – "
                 f"{format_date(datetime.date.fromisoformat(end))}")
        row_bg = s["row_a"] if idx % 2 == 0 else s["row_b"]
        rows.append(
            f"<tr style='{row_bg}'>"
            f"<td style='{td}{s['c_day']}'>{_esc(label)}</td>"
            f"<td style='{td}{s['c_hours']}'>{_minutes_as_hours(minutes)}h</td>"
            f"</tr>"
        )
    total_row = (
        f'<tr style="{s["total_row"]}">'
        f'<td style="{s["total_lbl"]}">Zu vergüten gesamt</td>'
        f'<td style="{s["total_hrs"]}">'
        f'{_minutes_as_hours(total_minutes)}h</td>'
        f'</tr>'
    ) if total_minutes is not None else ""
    return _keep_together(
        f'<table style="border-collapse:collapse;width:100%;margin-top:16px;{s["table_extra"]}">'
        f'<tr style="{s["th_row"]}">'
        f'<th style="{s["th_cell"]}">{heading}</th>'
        f'<th style="{s["th_cell"]}">Stunden</th>'
        f'</tr>'
        f'{"".join(rows)}'
        f'{total_row}'
        f'</table>',
        s,
    )


def _build_vacation_summary(vacation_days: dict[str, int],
                            work_minutes: int,
                            style: dict[str, Any],
                            capped_days: list[CappedDay] | None = None,
                            with_total: bool = True
                            ) -> str:
    """„Urlaub"-Block unter der Stundentabelle, plus die Zeile „Zu vergüten
    gesamt" (nur mit `with_total`).

    `vacation_days` ist bereits auf den Berichtszeitraum gefiltert
    ({ISO: minutes}). Je zusammenhängendem Block eine Zeile; liegt im Zeitraum
    keine einzige bezahlte Urlaubsminute, entsteht kein Block.

    Der Periodenname taucht bewusst NICHT auf: er ist gerätelokal, im Bericht
    heißt es schlicht „Urlaub" plus Zeitraum.

    Gerechnet wird durchgehend in Minuten (CLAUDE.md) — `work_minutes` kommt
    aus `_build_table` und damit aus derselben Auflösung, sodass die drei
    Zahlen auf der Seite aufgehen.

    `capped_days` sind die Tage, an denen `cap_by_worktime` den Urlaub um
    erfasste Ist-Zeit gekürzt hat. Sie bekommen eine Fußnote unter der
    Tabelle: ohne sie wiche der Urlaubs-Block still von dem ab, was der
    Verwaltungs-Dialog für dieselbe Periode zeigt.
    """
    runs = _vacation_runs(vacation_days)
    if not runs:
        return ""
    total = work_minutes + sum(m for _, _, m in runs) if with_total else None
    return (_absence_table(runs, "Urlaub", total, style)
            + _cap_footnote(capped_days, style))


def _build_sick_summary(sick_days: dict[str, int], total_minutes: int,
                        style: dict[str, Any],
                        capped_days: list[CappedDay] | None = None) -> str:
    """„Krankheit“-Block mit „Zu vergüten gesamt“ als letzter Zeile.

    `total_minutes` ist Ist-Zeit + Urlaub + Krankheit nach `cut_absences`, alles
    in Minuten. Ohne bezahlte Krankheitsminute entsteht kein Block.
    """
    runs = _vacation_runs(sick_days)
    if not runs:
        return ""
    return (_absence_table(runs, "Krankheit", total_minutes, style)
            + _cap_footnote(capped_days, style, "sick"))


def _absence_section(cut: AbsenceCut, work_minutes: int,
                     style: dict[str, Any]) -> str:
    """Urlaubs- und Krankheits-Block samt Fußnoten für Mail-HTML und PDF.

    Das Total „Zu vergüten gesamt“ steht im Block, der den Abschnitt schließt:
    im Krankheits-Block, wenn es bezahlte Krankheitsminuten gibt, sonst im
    Urlaubs-Block. Ohne Krankheitsdaten bitgleich zum reinen Urlaubs-Block.

    Hat die Kappung die Krankheit ganz aufgezehrt, entfällt ihr Block, ihre
    Fußnote aber nicht: die Vorschau im Zeitraum-Picker nennt die Kürzung
    auch. Ohne Häkchen ist `sick_capped` leer, die Fußnote also nie da.
    """
    has_sick = bool(_vacation_runs(cut.sick))
    vacation_minutes = sum(cut.vacation.values())
    html_out = _build_vacation_summary(
        cut.vacation, work_minutes, style, cut.vacation_capped,
        with_total=not has_sick)
    if has_sick:
        html_out += _build_sick_summary(
            cut.sick, work_minutes + vacation_minutes + sum(cut.sick.values()),
            style, cut.sick_capped)
    else:
        html_out += _cap_footnote(cut.sick_capped, style, "sick")
    notice = sick_on_vacation_notice(cut.sick_on_vacation)
    if notice:
        html_out += f'<p style="{style["footnote"]}">{_esc(notice)}</p>'
    return html_out


def _resolve_absences(date_from: datetime.date, date_to: datetime.date,
                      range_entries: dict[str, Any],
                      vacation_days: dict[str, int] | None,
                      sick_days: dict[str, int] | None) -> AbsenceCut:
    """Schneidet Urlaub und Krankheit auf den Zeitraum und rechnet sie über
    `absence.cut_for_output` gegen die bereits kategoriegefilterte Ist-Zeit.

    `sick_days=None` (Häkchen aus) bleibt `None`: nur so nimmt
    `cut_for_output` den reinen Urlaubs-Weg.
    """
    vacation_in_range = filter_period(date_from, date_to, vacation_days or {}) or {}
    sick_in_range = (None if sick_days is None
                     else filter_period(date_from, date_to, sick_days) or {})
    return cut_for_output(range_entries, vacation_in_range, sick_in_range)


def _cap_footnote(capped_days: list[CappedDay] | None,
                  style: dict[str, Any],
                  kind: Literal["vacation", "sick"] = "vacation") -> str:
    """Fußnote unter dem Urlaubs- bzw. Krankheits-Block, wenn Tage gekappt
    wurden.

    Wortlaut aus `absence.cap_notice` — dieselbe Formulierung wie die
    Hinweiszeile im Zeitraum-Picker, damit Vorschau und Bericht nicht
    verschieden über denselben Sachverhalt reden.
    """
    text = cap_notice(capped_days or [], kind)
    if not text:
        return ""
    return (f'<p style="{style["footnote"]}">{_esc(text)}</p>')


def generate_report(date_from: datetime.date, date_to: datetime.date,
                    all_entries: dict[str, Any], greeting: str = "",
                    content: str = "", closing: str = "",
                    categories: Collection[str] | None = None,
                    category_breakdown: bool = True,
                    vacation_days: dict[str, int] | None = None,
                    slot_order: str = "chrono",
                    note_breakdown: bool = False,
                    sick_days: dict[str, int] | None = None
                    ) -> tuple[str | None, float]:
    """Generate an HTML email report with greeting, content, table, category
    summary, and closing.

    categories: None = alle; sonst Menge von Kategorie-Strings ('' = ohne).
    category_breakdown: True = "Summe je Kategorie"-Tabelle anhängen (Default,
    bisheriges Verhalten); False = weglassen, nur das Gesamt der Tagestabelle.
    note_breakdown: die Kategorien-Tabelle zusätzlich nach Notiz aufschlüsseln;
    wirkt nur mit `category_breakdown`. Ohne Notizen bitgleich zu False.
    vacation_days: {ISO: minutes} der Urlaubstage (bereits Snapshot des
    Stores, ungefiltert) oder None. Liegt im Zeitraum kein Urlaubstag mit
    Minuten, ist die Ausgabe bitgleich zur Variante ohne den Parameter.
    sick_days: {ISO: minutes} der Krankheitstage oder None (Häkchen „Krankheit
    ausweisen“ aus). Mit Dict gewinnt Krankheit über Urlaub, beide werden um
    die Ist-Zeit gekappt, und „Zu vergüten gesamt“ steht am Ende. Ohne
    Krankheitstag im Zeitraum bitgleich zu `None`.
    Der zurückgegebene `total` bleibt in JEDEM Fall die reine Ist-Zeit.
    Returns (html, total) tuple, or (None, 0) if no entries.
    """
    range_entries = filter_period(date_from, date_to, all_entries)
    if range_entries:
        range_entries = filter_categories(range_entries, categories)
    # Urlaub und Krankheit werden um erfasste Ist-Zeit gekappt — sonst käme ein
    # Kalendertag in „Zu vergüten gesamt" auf mehr Stunden, als er hat
    # (Xveyn#97). Gegen den bereits kategoriegefilterten Ausschnitt, damit die
    # Zahlen auf der Seite aufgehen.
    cut = _resolve_absences(date_from, date_to, range_entries or {},
                            vacation_days, sick_days)

    # Leer ist der Bericht nur ohne Ist-Zeit UND ohne bezahlte Urlaubs- oder
    # Krankheitsminute: ein voller Abwesenheitsmonat ohne erfasste Arbeitszeit
    # ist für den Stundenlohn-Fall genau die Abrechnung, um die es geht.
    if (not range_entries and not any(cut.vacation.values())
            and not any(cut.sick.values())):
        return None, 0

    label = f"{format_date(date_from)} – {format_date(date_to)}"
    if range_entries:
        groups = _group_by_week(range_entries)
        table, total_minutes = _build_table(groups, HTML_STYLE, slot_order)
        category_summary = (
            _build_category_summary(range_entries, HTML_STYLE, note_breakdown)
            if category_breakdown else ""
        )
    else:
        # Kein Ist-Zeit-Block: die leere Stundentabelle bestünde nur aus
        # Kopfzeile und „Gesamt 0h" und sagte nichts aus.
        table, total_minutes, category_summary = "", 0, ""
    total = _minutes_as_hours(total_minutes)
    vacation_summary = _absence_section(cut, total_minutes, HTML_STYLE)

    greeting_filled = _apply_placeholders(_esc_multiline(greeting), label, total)
    content_filled = _apply_placeholders(_esc_multiline(content), label, total)
    closing_filled = _apply_placeholders(_esc_multiline(closing), label, total)

    text_style = "color:#cbd5e1;font-size:14px;line-height:1.6;margin:0 0 16px 0;"
    greeting_html = f'<p style="{text_style}">{greeting_filled}</p>' if greeting_filled else ""
    content_html = f'<p style="{text_style}">{content_filled}</p>' if content_filled else ""
    closing_html = f'<p style="{text_style}margin-top:24px;white-space:pre-line;">{closing_filled}</p>' if closing_filled else ""

    html_out = f"""<html><head><meta charset="utf-8"><meta http-equiv="Content-Type" content="text/html; charset=utf-8"></head>
<body style="margin:0;padding:0;background:#0f172a;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:640px;margin:0 auto;padding:32px 24px;">
{greeting_html}
{content_html}
{table}
{category_summary}
{vacation_summary}
{closing_html}
</div>
</body></html>"""

    return html_out, total


def generate_pdf(date_from: datetime.date, date_to: datetime.date,
                 all_entries: dict[str, Any], name: str = "",
                 categories: Collection[str] | None = None,
                 category_breakdown: bool = True,
                 vacation_days: dict[str, int] | None = None,
                 slot_order: str = "chrono",
                 note_breakdown: bool = False,
                 sick_days: dict[str, int] | None = None) -> bytes | None:
    """Generate a PDF of the time tracking table. Returns PDF bytes, or None if no entries.

    category_breakdown: True = "Summe je Kategorie"-Tabelle anhängen (Default);
    False = weglassen, nur das Gesamt der Tagestabelle.
    note_breakdown: wie bei `generate_report`.
    vacation_days: {ISO: minutes} der Urlaubstage (bereits Snapshot des
    Stores, ungefiltert) oder None. Liegt im Zeitraum kein Urlaubstag mit
    Minuten, ist die Ausgabe bitgleich zur Variante ohne den Parameter.
    sick_days: {ISO: minutes} der Krankheitstage oder None (Häkchen „Krankheit
    ausweisen“ aus). Mit Dict gewinnt Krankheit über Urlaub, beide werden um
    die Ist-Zeit gekappt, und „Zu vergüten gesamt“ steht am Ende. Ohne
    Krankheitstag im Zeitraum bitgleich zu `None`.
    """
    from xhtml2pdf import pisa  # pyright: ignore[reportMissingImports]  # lazy, nicht in CI-Test-Deps

    range_entries = filter_period(date_from, date_to, all_entries)
    if range_entries:
        range_entries = filter_categories(range_entries, categories)
    # Urlaub und Krankheit werden um erfasste Ist-Zeit gekappt — sonst käme ein
    # Kalendertag in „Zu vergüten gesamt" auf mehr Stunden, als er hat
    # (Xveyn#97). Gegen den bereits kategoriegefilterten Ausschnitt, damit die
    # Zahlen auf der Seite aufgehen.
    cut = _resolve_absences(date_from, date_to, range_entries or {},
                            vacation_days, sick_days)

    # Leer ist der Bericht nur ohne Ist-Zeit UND ohne bezahlte Urlaubs- oder
    # Krankheitsminute: ein voller Abwesenheitsmonat ohne erfasste Arbeitszeit
    # ist für den Stundenlohn-Fall genau die Abrechnung, um die es geht.
    if (not range_entries and not any(cut.vacation.values())
            and not any(cut.sick.values())):
        return None

    label = f"{format_date(date_from)} – {format_date(date_to)}"
    if range_entries:
        groups = _group_by_week(range_entries)
        table, total_minutes = _build_table(groups, PDF_STYLE, slot_order)
        category_summary = (
            _build_category_summary(range_entries, PDF_STYLE, note_breakdown)
            if category_breakdown else ""
        )
    else:
        # Kein Ist-Zeit-Block: die leere Stundentabelle bestünde nur aus
        # Kopfzeile und „Gesamt 0h" und sagte nichts aus.
        table, total_minutes, category_summary = "", 0, ""
    vacation_summary = _absence_section(cut, total_minutes, PDF_STYLE)

    name_html = (
        f"<p style='color:#111827;font-size:13px;margin:0 0 2px 0;font-weight:600;'>{_esc(name)}</p>"
        if name else ""
    )

    pdf_html = f"""<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:20px;font-family:Arial,sans-serif;font-size:12px;color:#111827;">
<h2 style="font-size:18px;margin:0 0 4px 0;color:#111827;">Zeiterfassung</h2>
{name_html}
<p style="color:#4b5563;font-size:12px;margin:0 0 16px 0;">{_esc(label)}</p>
{table}
{category_summary}
{vacation_summary}
</body></html>"""

    buffer = io.BytesIO()
    pisa.CreatePDF(pdf_html, dest=buffer)
    return buffer.getvalue()
