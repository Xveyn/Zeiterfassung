import datetime
import html
import io
from collections import OrderedDict

from src.time_utils import DAYS_DE, calculate_hours, format_date, get_week_label


def _esc(text):
    return html.escape(text or "", quote=True)


def _esc_multiline(text):
    return _esc(text).replace("\n", "<br>")


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
# Inline-Styles der Zellen geschrieben.
HTML_STYLE = {
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
}

PDF_STYLE = {
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
}


def _slot_hours(slot):
    return round(calculate_hours(slot["start"], slot["end"], pause_minutes=slot.get("pause", 0)), 2)


def _entry_hours(entry):
    """Summe der Stunden über alle Slots eines Tages."""
    return round(sum(_slot_hours(s) for s in entry.get("slots", [])), 2)


def _group_by_week(range_entries):
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


def _filter_entries(date_from, date_to, all_entries):
    from_str = date_from.isoformat()
    to_str = date_to.isoformat()
    range_entries = {
        k: v for k, v in all_entries.items() if from_str <= k <= to_str
    }
    return range_entries if range_entries else None


def _apply_category_filter(entries, categories):
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


def total_hours(date_from, date_to, all_entries, categories=None):
    """Gesamtstunden im Zeitraum, gefiltert auf die gewählten Kategorien
    (None = alle). Pure Funktion für die Live-Vorschau im Sende-Dialog —
    summiert dieselben Slot-Stunden wie der Report. Leerer Bereich → 0.0."""
    range_entries = _filter_entries(date_from, date_to, all_entries)
    if range_entries:
        range_entries = _apply_category_filter(range_entries, categories)
    if not range_entries:
        return 0.0
    return round(sum(_entry_hours(e) for e in range_entries.values()), 2)


def default_pdf_filename(date_from, date_to):
    """Default-Dateiname für den PDF-Bericht: Zeiterfassung_<VON>_<BIS>.pdf
    mit Datums-Stempeln im Format YYYYMMDD (z.B.
    Zeiterfassung_20260301_20260331.pdf). Genutzt vom Senden- (Mail-Anhang)
    und vom Export-Pfad."""
    return f"Zeiterfassung_{date_from:%Y%m%d}_{date_to:%Y%m%d}.pdf"


def _apply_placeholders(text, label, total):
    return text.replace("{zeitraum}", _esc(label)).replace("{gesamt}", _esc(f"{total}h"))


# _week_block / _build_table / _build_category_summary rendern Werte aus dem
# Storage. Datum/KW werden intern erzeugt (strftime / get_week_label) und sind
# vertrauenswürdig. start/end sind zwar über Entry-Dialog/Share/gcal auf
# [0-9:.-] validiert, aber der Drive-Sync (sync.apply_merged_doc) schreibt
# Remote-Slots ungeprüft in den Storage — ein manipuliertes Sync-Doc könnte rohes
# HTML einschleusen (Audit M7). Deshalb werden start/end defensiv _esc()-t,
# genau wie `kategorie` (freier Nutzertext).
def _week_block(iso_year, iso_week, week_entries, style):
    """Render einen Wochen-Block: KW-Header, je Slot eine Zeile, Tages-Subtotal
    bei >1 Slot, Wochensumme. Returns (rows_html, week_total)."""
    s = style
    cw = [f"width:{w};" if w else "" for w in s["col_widths"]]
    rows = [
        f"<tr style='{s['kw_row']}'>"
        f"<td colspan='6' style='{s['kw_cell']}'>{get_week_label(iso_year, iso_week)}</td>"
        f"</tr>"
    ]

    week_total = 0.0
    for idx, (date_str, entry) in enumerate(week_entries):
        dt = datetime.date.fromisoformat(date_str)
        weekday = DAYS_DE[dt.weekday()]
        day_fmt = format_date(dt)
        row_bg = s["row_a"] if idx % 2 == 0 else s["row_b"]
        td = s["td_base"]
        slots = entry["slots"]
        day_total = 0.0
        for sidx, slot in enumerate(slots):
            hours = _slot_hours(slot)
            day_total += hours
            week_total += hours
            date_cell = day_fmt if sidx == 0 else ""
            day_cell = weekday if sidx == 0 else ""
            rows.append(
                f"<tr style='{row_bg}'>"
                f"<td style='{td}{cw[0]}{s['c_date']}'>{date_cell}</td>"
                f"<td style='{td}{cw[1]}{s['c_day']}'>{day_cell}</td>"
                f"<td style='{td}{cw[2]}{s['c_kat']}'>{_esc(slot.get('kategorie') or '')}</td>"
                f"<td style='{td}{cw[3]}{s['c_time']}'>{_esc(slot['start'])}</td>"
                f"<td style='{td}{cw[4]}{s['c_time']}'>{_esc(slot['end'])}</td>"
                f"<td style='{td}{cw[5]}{s['c_hours']}'>{hours}h</td>"
                f"</tr>"
            )
        if len(slots) > 1:
            day_total = round(day_total, 2)
            rows.append(
                f"<tr style='{row_bg}'>"
                f"<td colspan='5' style='{td}{s['c_day']}'>Summe {day_fmt}</td>"
                f"<td style='{td}{s['c_hours']}'>{day_total}h</td>"
                f"</tr>"
            )

    week_total = round(week_total, 2)
    rows.append(
        f"<tr style='{s['sum_row']}'>"
        f"<td colspan='5' style='{s['sum_lbl']}'>Summe KW {iso_week}</td>"
        f"<td style='{s['sum_hrs']}'>{week_total}h</td>"
        f"</tr>"
    )
    return "\n".join(rows), week_total


def _build_table(groups, style):
    """Bauen die komplette Stundentabelle. Returns (table_html, total)."""
    s = style
    week_blocks = []
    total = 0.0
    for (iso_year, iso_week), week_entries in groups.items():
        block_html, week_total = _week_block(iso_year, iso_week, week_entries, s)
        week_blocks.append(block_html)
        total += week_total
    total = round(total, 2)

    th_cells = "".join(
        f'<th style="{s["th_cell"]}{f"width:{w};" if w else ""}">{label}</th>'
        for label, w in zip(COLUMN_LABELS, s["col_widths"], strict=False)
    )

    table = (
        f'<table style="border-collapse:collapse;width:100%;{s["table_extra"]}">'
        f'<tr style="{s["th_row"]}">{th_cells}</tr>'
        f'{"".join(week_blocks)}'
        f'<tr style="{s["total_row"]}">'
        f'<td colspan="5" style="{s["total_lbl"]}">Gesamt</td>'
        f'<td style="{s["total_hrs"]}">{total}h</td>'
        f'</tr>'
        f'</table>'
    )
    return table, total


def _build_category_summary(range_entries, style):
    """„Summe je Kategorie"-Tabelle über den (gefilterten) Zeitraum. Leerer
    String ('' = keine Kategorie) wird als '(ohne Kategorie)' ans Ende
    sortiert. Liefert '' wenn keine Slots vorhanden — oder wenn alle Slots
    unkategorisiert sind (dann wäre die Tabelle nur die Gesamtsumme)."""
    s = style
    totals = {}
    for entry in range_entries.values():
        for slot in entry["slots"]:
            kat = slot.get("kategorie") or ""
            totals[kat] = totals.get(kat, 0.0) + _slot_hours(slot)
    # Keine Slots, oder ausschließlich unkategorisierte: die Tabelle bestünde
    # dann nur aus der "(ohne Kategorie)"-Zeile = exakt die ohnehin gezeigte
    # Gesamtsumme. Weglassen, statt eine leere Pseudo-Aufschlüsselung zu zeigen.
    if not totals or set(totals) == {""}:
        return ""

    td = s["td_base"]
    rows = []
    for idx, kat in enumerate(sorted(totals, key=lambda k: (k == "", k.lower()))):
        label = kat if kat else "(ohne Kategorie)"
        hours = round(totals[kat], 2)
        row_bg = s["row_a"] if idx % 2 == 0 else s["row_b"]
        rows.append(
            f"<tr style='{row_bg}'>"
            f"<td style='{td}{s['c_day']}'>{_esc(label)}</td>"
            f"<td style='{td}{s['c_hours']}'>{hours}h</td>"
            f"</tr>"
        )

    return (
        f'<table style="border-collapse:collapse;width:100%;margin-top:16px;{s["table_extra"]}">'
        f'<tr style="{s["th_row"]}">'
        f'<th style="{s["th_cell"]}">Kategorie</th>'
        f'<th style="{s["th_cell"]}">Stunden</th>'
        f'</tr>'
        f'{"".join(rows)}'
        f'</table>'
    )


def generate_report(date_from, date_to, all_entries, greeting="", content="",
                    closing="", categories=None, category_breakdown=True):
    """Generate an HTML email report with greeting, content, table, category
    summary, and closing.

    categories: None = alle; sonst Menge von Kategorie-Strings ('' = ohne).
    category_breakdown: True = "Summe je Kategorie"-Tabelle anhängen (Default,
    bisheriges Verhalten); False = weglassen, nur das Gesamt der Tagestabelle.
    Returns (html, total) tuple, or (None, 0) if no entries.
    """
    range_entries = _filter_entries(date_from, date_to, all_entries)
    if range_entries:
        range_entries = _apply_category_filter(range_entries, categories)
    if not range_entries:
        return None, 0

    label = f"{format_date(date_from)} – {format_date(date_to)}"
    groups = _group_by_week(range_entries)
    table, total = _build_table(groups, HTML_STYLE)
    category_summary = (
        _build_category_summary(range_entries, HTML_STYLE)
        if category_breakdown else ""
    )

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
{closing_html}
</div>
</body></html>"""

    return html_out, total


def generate_pdf(date_from, date_to, all_entries, name="", categories=None,
                 category_breakdown=True):
    """Generate a PDF of the time tracking table. Returns PDF bytes, or None if no entries.

    category_breakdown: True = "Summe je Kategorie"-Tabelle anhängen (Default);
    False = weglassen, nur das Gesamt der Tagestabelle.
    """
    from xhtml2pdf import pisa  # pyright: ignore[reportMissingImports]  # lazy, nicht in CI-Test-Deps

    range_entries = _filter_entries(date_from, date_to, all_entries)
    if range_entries:
        range_entries = _apply_category_filter(range_entries, categories)
    if not range_entries:
        return None

    label = f"{format_date(date_from)} – {format_date(date_to)}"
    groups = _group_by_week(range_entries)
    table, _ = _build_table(groups, PDF_STYLE)
    category_summary = (
        _build_category_summary(range_entries, PDF_STYLE)
        if category_breakdown else ""
    )

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
</body></html>"""

    buffer = io.BytesIO()
    pisa.CreatePDF(pdf_html, dest=buffer)
    return buffer.getvalue()
