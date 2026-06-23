# AP4 — Report + Sende-Dialog (Kategorien) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den Report (`src/report.py`) auf das Multi-Slot-Modell heben — eine Zeile pro Slot mit Kategorie-Spalte, Tages-Subtotal bei mehreren Slots, KW-Summen wie bisher, plus einen „Summe je Kategorie"-Block — und im Sende-Dialog (`src/dialogs/send_dialog.py`) eine Kategorie-Auswahl ergänzen, die in den Versand (Mail/PDF) durchgereicht wird.

**Architecture:** `report.py` rendert aus `{date: {slots: [...]}}` (AP1-Shape). Die HTML-Erzeugung ist pure und voll testbar (Task 1). Der Sende-Dialog ist eine dünne Tkinter-Schicht, die die im Bestand vorhandenen Kategorien als Checkboxen anbietet und die Auswahl an `generate_report`/`generate_pdf` weiterreicht (Task 2).

**Tech Stack:** Python stdlib, xhtml2pdf (lazy import, wie bisher), tkinter, pytest.

## Global Constraints

- **AP1-Shape:** `all_entries` = `{date: {"slots": [{start, end, pause, kategorie}]}}` (Ist-Zeiten). Slots haben `pause` (int) und `kategorie` (str, `""` = keine).
- **Report-Tabelle:** Spalten `Datum | Tag | Kategorie | Start | Ende | Stunden` (6 Spalten). **Eine Zeile je Slot.** Datum+Tag nur in der ERSTEN Slot-Zeile eines Tages, in Folgezeilen leer. Bei >1 Slot am Tag eine **Tages-Subtotal-Zeile** („Summe TT.MM.JJJJ"). KW-Header + KW-Summe wie bisher. Gesamt-Footer wie bisher.
- **„Summe je Kategorie"-Block:** eigene Tabelle nach der Haupttabelle (`Kategorie | Stunden`), Summe je Kategorie über den (gefilterten) Zeitraum. `""` → Label „(ohne Kategorie)", einsortiert ans Ende.
- **Kategorie-Filter:** `generate_report`/`generate_pdf` bekommen Parameter `categories=None`. `None` = alle. Sonst Menge von Kategorie-Strings (`""` = ohne Kategorie); Slots mit nicht-enthaltener Kategorie werden verworfen; Tage ohne verbleibende Slots fallen weg. Werden dadurch (oder durch Datum) keine Slots übrig → `(None, 0)` bzw. `None`.
- **HTML-Escaping:** `kategorie` ist **freier Nutzertext** und MUSS escaped werden (`_esc`). `start`/`end`/Datum/KW bleiben strukturell sicher (wie der bestehende Kommentar in report.py erklärt).
- **Stundenlogik:** Slot-Stunden = `calculate_hours(start, end, pause)`. Tages-/Wochen-/Gesamt-/Kategorie-Summe = Summe über Slots, je `round(…, 2)`.
- **Backwards-Compat der Signaturen:** `categories=None` ist der Default → bestehende Aufrufer ohne Filter verhalten sich unverändert.
- **Datumsformat:** intern ISO; UI/Anzeige deutsch (`%d.%m.%Y`).
- **Harter Schnitt (laufend):** Nur AP4-Dateien. Consumer außerhalb (share, ui, gcal) bleiben rot bis zu ihren Paketen.

## Test-Strategie / Design-Notes (für den Plan-Review)

- **`report.py` ist voll unit-getestet** (Task 1) — `test_report.py` wird auf die Slot-Shape umgestellt (bestehende Assertions bleiben gültig, da ein 1-Slot-Tag weiter Datum/Start/Ende/Stunden rendert) und um Kategorie-/Multi-Slot-/Filter-Tests erweitert.
- **`send_dialog.py` hat KEINE automatisierten Tests** (Tkinter/CI ohne Display, Projekt-Norm). Verifikation Task 2 = Import-Smoke + Diff-Review + manueller lokaler Test. Im Plan-Review zur Abnahme markiert.
- **Filter-Default „alle":** Sind alle Checkboxen gesetzt, übergibt der Dialog `categories=None` (kein Filter) — semantisch identisch zu „alle ausgewählt", aber günstiger und robust.

---

## Dateistruktur

- `src/report.py` — komplette Neufassung der Tabellen-/Render-Logik (Slot-Zeilen, Kategorie-Spalte, Tages-Subtotal, Kategorie-Summen-Block, Filter). Verantwortung unverändert.
- `src/dialogs/send_dialog.py` — Kategorie-Checkbox-Sektion + Durchreichen von `categories`.
- `tests/test_report.py` — auf Slot-Shape umgestellt + Kategorie-/Filter-Tests.

Task 1 (report + Tests) ist unabhängig testbar. Task 2 (send_dialog) konsumiert die neue `categories`-Signatur.

---

## Task 1: `report.py` — Multi-Slot-Tabelle + Kategorie-Summen + Filter

**Files:**
- Modify: `src/report.py` (komplette Neufassung, siehe Step 3)
- Test: `tests/test_report.py` (Neufassung, siehe Step 1)

**Interfaces:**
- Consumes: AP1-Shape `{date: {"slots":[{start,end,pause,kategorie}]}}`.
- Produces:
  - `generate_report(date_from, date_to, all_entries, greeting="", content="", closing="", categories=None) -> (html|None, total)`.
  - `generate_pdf(date_from, date_to, all_entries, name="", categories=None) -> bytes|None`.
  - Interne Helfer: `_slot_hours(slot)`, `_entry_hours(entry)` (Summe über Slots), `_apply_category_filter(entries, categories)`, `_build_category_summary(range_entries, style)`.

- [ ] **Step 1: `tests/test_report.py` neu schreiben**

Ersetze den **kompletten** Inhalt von `tests/test_report.py` durch:

```python
import datetime
from unittest.mock import patch, MagicMock

from src.report import generate_report


def _e(start, end, pause=0, kategorie=""):
    """Eintrag mit genau einem Slot."""
    return {"slots": [{"start": start, "end": end, "pause": pause, "kategorie": kategorie}]}


def _slot(start, end, pause=0, kategorie=""):
    return {"start": start, "end": end, "pause": pause, "kategorie": kategorie}


def test_empty_entries():
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), {})
    assert html is None
    assert total == 0


def test_single_entry():
    entries = {"2026-03-23": _e("08:00", "16:30", 30)}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "23.03.2026" in html
    assert "Mo" in html
    assert "08:00" in html
    assert "16:30" in html
    assert "8.0h" in html
    assert "<table" in html
    assert "#0f172a" in html
    assert "#00D8A7" in html


def test_kategorie_column_present():
    entries = {"2026-03-23": _e("08:00", "16:00", 0, "Büro")}
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "Kategorie" in html   # Spaltenkopf
    assert "Büro" in html        # Wert


def test_multiple_entries_sorted():
    entries = {"2026-03-25": _e("09:00", "17:00", 30), "2026-03-23": _e("08:00", "16:30", 30)}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert html.index("23.03.2026") < html.index("25.03.2026")


def test_total_hours():
    entries = {"2026-03-23": _e("08:00", "16:30", 30), "2026-03-24": _e("09:00", "17:00", 60)}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "15.0h" in html
    assert total == 15.0


def test_multi_slot_day_rows_and_subtotal():
    """Ein Tag mit zwei Slots: beide Slots als Zeilen + Tages-Subtotal."""
    entries = {"2026-03-23": {"slots": [
        _slot("08:00", "12:00", 0, "Büro"),
        _slot("13:00", "17:00", 0, "Homeoffice"),
    ]}}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "08:00" in html and "12:00" in html
    assert "13:00" in html and "17:00" in html
    assert "Büro" in html and "Homeoffice" in html
    assert "Summe 23.03.2026" in html   # Tages-Subtotal bei >1 Slot
    assert total == 8.0


def test_single_slot_day_has_no_subtotal():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "Summe 23.03.2026" not in html


def test_category_summary_block():
    entries = {
        "2026-03-23": {"slots": [_slot("08:00", "12:00", 0, "Büro"),
                                  _slot("13:00", "17:00", 0, "Homeoffice")]},
        "2026-03-24": _e("08:00", "12:00", 0, "Büro"),
    }
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    # Büro: 4h (Di) + 4h (Mo) = 8h; Homeoffice: 4h
    assert "Büro" in html
    assert "Homeoffice" in html
    assert "8.0h" in html
    assert "4.0h" in html


def test_category_summary_uncategorized_label():
    entries = {"2026-03-23": _e("08:00", "16:00")}  # kategorie ""
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "(ohne Kategorie)" in html


def test_category_filter_includes_only_selected():
    entries = {"2026-03-23": {"slots": [_slot("08:00", "12:00", 0, "Büro"),
                                         _slot("13:00", "17:00", 0, "Homeoffice")]}}
    html, total = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, categories={"Büro"})
    assert "Büro" in html
    assert "Homeoffice" not in html
    assert total == 4.0


def test_category_filter_uncategorized_via_empty_string():
    entries = {"2026-03-23": {"slots": [_slot("08:00", "12:00", 0, ""),
                                         _slot("13:00", "17:00", 0, "Büro")]}}
    html, total = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, categories={""})
    assert total == 4.0
    assert "Büro" not in html


def test_category_filter_empty_result_returns_none():
    entries = {"2026-03-23": _e("08:00", "16:00", 0, "Büro")}
    html, total = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, categories={"Nichtvorhanden"})
    assert html is None
    assert total == 0


def test_filters_outside_range():
    entries = {"2026-03-23": _e("08:00", "16:30"), "2026-04-01": _e("09:00", "17:00")}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "23.03.2026" in html
    assert "01.04.2026" not in html


def test_legacy_entry_no_pause():
    # Slot ohne pause-Key (Default 0)
    entries = {"2026-03-23": {"slots": [{"start": "08:00", "end": "16:30", "kategorie": ""}]}}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "8.5h" in html


def test_cross_month_range():
    entries = {
        "2026-02-20": _e("08:00", "16:00"), "2026-03-05": _e("09:00", "17:00"),
        "2026-03-20": _e("08:00", "16:00"),
    }
    html, total = generate_report(datetime.date(2026, 2, 15), datetime.date(2026, 3, 14), entries)
    assert "20.02.2026" in html
    assert "05.03.2026" in html
    assert "20.03.2026" not in html


def test_inclusive_boundaries():
    entries = {
        "2026-03-01": _e("08:00", "16:00"), "2026-03-15": _e("08:00", "16:00"),
        "2026-03-16": _e("08:00", "16:00"),
    }
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 15), entries)
    assert "01.03.2026" in html
    assert "15.03.2026" in html
    assert "16.03.2026" not in html


def test_alternating_row_colors():
    entries = {"2026-03-23": _e("08:00", "16:00"), "2026-03-24": _e("08:00", "16:00")}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "#1e293b" in html
    assert "#243347" in html


def test_greeting_content_closing_in_html():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, total = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries,
        greeting="Hallo Welt,", content="hier die Zeiten für {zeitraum}.", closing="Grüße\nMax")
    assert "Hallo Welt," in html
    assert "hier die Zeiten für 01.03.2026 – 31.03.2026." in html
    assert "Grüße" in html
    assert "Max" in html


def test_placeholders_replaced():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, total = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, content="Gesamt: {gesamt}")
    assert "Gesamt: 8.0h" in html


def test_week_header_and_sum_present():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "KW 13" in html
    assert "Summe KW 13" in html
    assert "8.0h" in html


def test_multiple_weeks_each_have_header_and_sum():
    entries = {
        "2026-03-23": _e("08:00", "16:00"), "2026-03-24": _e("09:00", "17:00"),
        "2026-03-30": _e("08:00", "17:00", 60),
    }
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "KW 13" in html
    assert "KW 14" in html
    assert "Summe KW 13" in html
    assert "Summe KW 14" in html
    assert html.index("KW 13") < html.index("KW 14")


def test_week_sum_equals_sum_of_days():
    entries = {"2026-03-23": _e("08:00", "16:00"), "2026-03-24": _e("09:00", "17:00")}
    html, total = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "16.0h" in html
    assert total == 16.0


def test_iso_week_across_year_boundary():
    entries = {"2025-12-29": _e("08:00", "16:00")}
    html, total = generate_report(datetime.date(2025, 12, 1), datetime.date(2026, 1, 31), entries)
    assert "KW 1" in html


# --- HTML-Escaping ---


def test_greeting_with_ampersand_is_escaped():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, greeting="Mayer & Söhne,")
    assert "Mayer &amp; Söhne," in html
    assert "Mayer & Söhne" not in html


def test_greeting_with_html_tag_is_escaped():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries,
        greeting="<script>alert(1)</script>")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_kategorie_is_escaped():
    """Kategorie ist freier Nutzertext und muss escaped werden."""
    entries = {"2026-03-23": _e("08:00", "16:00", 0, "Mayer & <b>Co</b>")}
    html, _ = generate_report(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries)
    assert "Mayer &amp; &lt;b&gt;Co&lt;/b&gt;" in html
    assert "<b>Co</b>" not in html


def test_content_newline_becomes_br():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, content="Zeile1\nZeile2")
    assert "Zeile1<br>Zeile2" in html


def test_closing_with_lt_and_newline_escaped_with_br():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, closing="A < B\nFreundlich")
    assert "A &lt; B<br>Freundlich" in html
    assert "&lt;br&gt;" not in html


def test_placeholder_zeitraum_replaced_after_escape():
    entries = {"2026-03-23": _e("08:00", "16:00")}
    html, _ = generate_report(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, content="Zeitraum: {zeitraum}")
    assert "Zeitraum: 01.03.2026 – 31.03.2026" in html


def test_pdf_name_is_escaped():
    """generate_pdf escaped name; xhtml2pdf wird gemockt (CI ohne Lib)."""
    from src import report as report_mod
    entries = {"2026-03-23": _e("08:00", "16:00")}
    captured_html = {}

    class FakePisa:
        @staticmethod
        def CreatePDF(html_str, dest):
            captured_html["html"] = html_str
            return MagicMock(err=0)

    fake_xhtml2pdf = MagicMock()
    fake_xhtml2pdf.pisa = FakePisa

    with patch.dict("sys.modules", {"xhtml2pdf": fake_xhtml2pdf}):
        report_mod.generate_pdf(
            datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, name="Müller & Co")

    assert "Müller &amp; Co" in captured_html["html"]
    assert "Müller & Co" not in captured_html["html"]


def test_pdf_category_filter_applied():
    """generate_pdf respektiert den categories-Filter."""
    from src import report as report_mod
    entries = {"2026-03-23": {"slots": [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Büro"},
                                         {"start": "13:00", "end": "17:00", "pause": 0, "kategorie": "HO"}]}}
    captured_html = {}

    class FakePisa:
        @staticmethod
        def CreatePDF(html_str, dest):
            captured_html["html"] = html_str
            return MagicMock(err=0)

    fake_xhtml2pdf = MagicMock()
    fake_xhtml2pdf.pisa = FakePisa

    with patch.dict("sys.modules", {"xhtml2pdf": fake_xhtml2pdf}):
        report_mod.generate_pdf(
            datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), entries, categories={"Büro"})

    assert "Büro" in captured_html["html"]
    assert "HO" not in captured_html["html"]
```

- [ ] **Step 2: Tests laufen lassen — müssen FEHLSCHLAGEN**

Run: `python -m pytest tests/test_report.py -q`
Expected: FAIL — `report.py` liest noch `entry["start"]` (KeyError, da Einträge jetzt `{"slots": [...]}`), und der `categories`-Parameter / Kategorie-Spalte / Summen-Block existieren noch nicht.

- [ ] **Step 3: `src/report.py` neu schreiben**

Ersetze den **kompletten** Inhalt von `src/report.py` durch:

```python
import datetime
import html
import io
from collections import OrderedDict

from src.time_utils import DAYS_DE, calculate_hours, get_week_label


def _esc(text):
    return html.escape(text or "", quote=True)


def _esc_multiline(text):
    return _esc(text).replace("\n", "<br>")


COLUMN_LABELS = ["Datum", "Tag", "Kategorie", "Start", "Ende", "Stunden"]

# Style-Dict pro Render-Ziel. Felder werden direkt als CSS-Strings in die
# Inline-Styles der Zellen geschrieben.
HTML_STYLE = {
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


def _apply_placeholders(text, label, total):
    return text.replace("{zeitraum}", _esc(label)).replace("{gesamt}", _esc(f"{total}h"))


# _week_block / _build_table / _build_category_summary rendern Werte aus dem
# Storage. start/end/Datum/KW sind strukturell auf [0-9:.-] beschränkt (kein
# Escape nötig). `kategorie` ist FREIER Nutzertext → wird mit _esc() escaped.
def _week_block(iso_year, iso_week, week_entries, style):
    """Render einen Wochen-Block: KW-Header, je Slot eine Zeile, Tages-Subtotal
    bei >1 Slot, Wochensumme. Returns (rows_html, week_total)."""
    s = style
    rows = [
        f"<tr style='{s['kw_row']}'>"
        f"<td colspan='6' style='{s['kw_cell']}'>{get_week_label(iso_year, iso_week)}</td>"
        f"</tr>"
    ]

    week_total = 0.0
    for idx, (date_str, entry) in enumerate(week_entries):
        dt = datetime.date.fromisoformat(date_str)
        weekday = DAYS_DE[dt.weekday()]
        day_fmt = dt.strftime("%d.%m.%Y")
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
                f"<td style='{td}{s['c_date']}'>{date_cell}</td>"
                f"<td style='{td}{s['c_day']}'>{day_cell}</td>"
                f"<td style='{td}{s['c_kat']}'>{_esc(slot.get('kategorie') or '')}</td>"
                f"<td style='{td}{s['c_time']}'>{slot['start']}</td>"
                f"<td style='{td}{s['c_time']}'>{slot['end']}</td>"
                f"<td style='{td}{s['c_hours']}'>{hours}h</td>"
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
        f'<th style="{s["th_cell"]}">{label}</th>' for label in COLUMN_LABELS
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
    sortiert. Liefert '' wenn keine Slots vorhanden."""
    s = style
    totals = {}
    for entry in range_entries.values():
        for slot in entry["slots"]:
            kat = slot.get("kategorie") or ""
            totals[kat] = totals.get(kat, 0.0) + _slot_hours(slot)
    if not totals:
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
                    closing="", categories=None):
    """Generate an HTML email report with greeting, content, table, category
    summary, and closing.

    categories: None = alle; sonst Menge von Kategorie-Strings ('' = ohne).
    Returns (html, total) tuple, or (None, 0) if no entries.
    """
    range_entries = _filter_entries(date_from, date_to, all_entries)
    if range_entries:
        range_entries = _apply_category_filter(range_entries, categories)
    if not range_entries:
        return None, 0

    label = f"{date_from.strftime('%d.%m.%Y')} – {date_to.strftime('%d.%m.%Y')}"
    groups = _group_by_week(range_entries)
    table, total = _build_table(groups, HTML_STYLE)
    category_summary = _build_category_summary(range_entries, HTML_STYLE)

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


def generate_pdf(date_from, date_to, all_entries, name="", categories=None):
    """Generate a PDF of the time tracking table. Returns PDF bytes, or None if no entries."""
    from xhtml2pdf import pisa

    range_entries = _filter_entries(date_from, date_to, all_entries)
    if range_entries:
        range_entries = _apply_category_filter(range_entries, categories)
    if not range_entries:
        return None

    label = f"{date_from.strftime('%d.%m.%Y')} – {date_to.strftime('%d.%m.%Y')}"
    groups = _group_by_week(range_entries)
    table, _ = _build_table(groups, PDF_STYLE)
    category_summary = _build_category_summary(range_entries, PDF_STYLE)

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
```

- [ ] **Step 4: Tests laufen lassen — müssen BESTEHEN**

Run: `python -m pytest tests/test_report.py -q`
Expected: PASS (alle Tests grün).

- [ ] **Step 5: Commit**

```bash
git add src/report.py tests/test_report.py
git commit -m "feat(report): Zeile pro Slot + Kategorie-Spalte/-Summen + Filter (#53)

report rendert je Slot eine Zeile (Datum/Tag nur in erster Slot-Zeile),
Tages-Subtotal bei >1 Slot, plus 'Summe je Kategorie'-Block. generate_report/
generate_pdf bekommen categories-Filter (None=alle). Kategorie wird escaped.
Teil von AP4.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `send_dialog` — Kategorie-Auswahl

**Files:**
- Modify: `src/dialogs/send_dialog.py` (Import `CELL_BG`, Kategorie-Checkbox-Sektion, `categories` an `generate_report`/`generate_pdf` durchreichen, Button-Zeile verschieben)

**Interfaces:**
- Consumes: `generate_report(..., categories=...)` / `generate_pdf(..., categories=...)` (Task 1); `storage.get_all() -> {date: {"slots":[{...}]}}`.

> **Keine automatisierten Tests** (Tkinter). Verifikation: Import-Smoke + Diff-Review + manueller lokaler Test.

- [ ] **Step 1: Import `CELL_BG` ergänzen**

In `src/dialogs/send_dialog.py`, im `from src.theme import (...)`-Block, ändere die Zeile

```python
    BG, FONT, TEXT,
```

zu

```python
    BG, CELL_BG, FONT, TEXT,
```

- [ ] **Step 2: Kategorie-Checkbox-Sektion + Button-Zeile verschieben**

In `open_send_dialog`, ersetze den Abschnitt von `from_day, from_month, from_year = ...` bis vor `def do_send():` (aktuell):

```python
    from_day, from_month, from_year = build_date_row(0, "Von:", from_default)
    to_day, to_month, to_year = build_date_row(1, "Bis:", today)

    def do_send():
```

durch:

```python
    from_day, from_month, from_year = build_date_row(0, "Von:", from_default)
    to_day, to_month, to_year = build_date_row(1, "Bis:", today)

    # --- Kategorie-Auswahl ---
    # Kategorien aus dem Bestand UND der Settings-Pickliste sammeln ("" = ohne
    # Kategorie). Alle standardmäßig ausgewählt; sind alle ausgewählt, wird kein
    # Filter gesetzt. Bewusste Vereinfachung: die Liste wird NICHT auf den
    # gewählten Zeitraum eingeschränkt (das bräuchte dynamisches Neu-Aufbauen bei
    # Datumswechsel) — eine im Zeitraum nicht vorkommende Kategorie bleibt
    # wirkungslos, daher unkritisch.
    all_entries = storage.get_all()
    present_categories = sorted(
        {(s.get("kategorie") or "") for e in all_entries.values() for s in e["slots"]}
        | {c for c in (settings.get("categories") or [])},
        key=lambda k: (k == "", k.lower()),
    )
    category_vars = {}  # rohe Kategorie -> BooleanVar
    if present_categories:
        tk.Label(dialog, text="Kategorien:", font=FONT, bg=BG, fg=TEXT).grid(
            row=2, column=0, padx=(10, 5), pady=(4, 8), sticky="nw")
        cat_frame = tk.Frame(dialog, bg=BG)
        cat_frame.grid(row=2, column=1, columnspan=5, padx=(0, 10), pady=(4, 8), sticky="w")
        for kat in present_categories:
            var = tk.BooleanVar(value=True)
            category_vars[kat] = var
            label = kat if kat else "(ohne Kategorie)"
            tk.Checkbutton(
                cat_frame, text=label, variable=var,
                font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT,
                highlightthickness=0, bd=0, anchor="w",
            ).pack(anchor="w")

    def _selected_categories():
        """None, wenn keine Kategorien existieren oder alle ausgewählt sind
        (= kein Filter). Sonst die Menge der ausgewählten rohen Kategorien."""
        if not category_vars:
            return None
        selected = {kat for kat, var in category_vars.items() if var.get()}
        if len(selected) == len(category_vars):
            return None
        return selected

    def do_send():
```

- [ ] **Step 3: `do_send` — `entries` wiederverwenden + `categories` durchreichen**

In `do_send`, ersetze (aktuell):

```python
        entries = storage.get_all()

        html, total = generate_report(
            date_from, date_to, entries,
            greeting=settings.get("mail_greeting"),
            content=settings.get("mail_content"),
            closing=settings.get("mail_closing"),
        )
```

durch:

```python
        entries = all_entries
        categories = _selected_categories()

        html, total = generate_report(
            date_from, date_to, entries,
            greeting=settings.get("mail_greeting"),
            content=settings.get("mail_content"),
            closing=settings.get("mail_closing"),
            categories=categories,
        )
```

Und ersetze die PDF-Zeile (aktuell):

```python
            pdf_bytes = generate_pdf(date_from, date_to, entries, name=settings.get("name"))
```

durch:

```python
            pdf_bytes = generate_pdf(date_from, date_to, entries, name=settings.get("name"),
                                     categories=categories)
```

- [ ] **Step 4: Button-Zeile von row=2 auf row=3 verschieben**

In `open_send_dialog`, ändere (aktuell):

```python
    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=2, column=0, columnspan=6, pady=12)
```

zu:

```python
    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=3, column=0, columnspan=6, pady=12)
```

- [ ] **Step 5: Import-Smoke + Byte-Compile**

Run: `python -c "import src.dialogs.send_dialog; print('ok')"`
Expected: gibt `ok` aus.

Run: `python -m py_compile src/dialogs/send_dialog.py`
Expected: keine Ausgabe, Exit 0.

- [ ] **Step 6: AP1–AP4-Regressionscheck**

Run: `python -m pytest tests/test_storage.py tests/test_storage_migration.py tests/test_reservations.py tests/test_reservations_migration.py tests/test_settings.py tests/test_sync.py tests/test_time_calc.py tests/test_time_utils.py tests/test_report.py -q`
Expected: PASS.

> **Hinweis:** Voller `pytest`-Lauf bleibt erwartbar rot (share/ui/gcal offen). `send_dialog.py` hat keine Auto-Tests — manueller Test durch den Nutzer.

- [ ] **Step 7: Manuelle Verifikations-Checkliste (in den Report, NICHT ausführen)**

- Sende-Dialog zeigt unter Von/Bis eine „Kategorien:"-Sektion mit je einer Checkbox pro vorhandener Kategorie (+ „(ohne Kategorie)"), alle gesetzt.
- Gibt es keine Kategorien im Bestand, fehlt die Sektion (kein leerer Block).
- Eine Kategorie abwählen → PDF/Mail enthält nur die gewählten Kategorien.
- Alle gewählt → unverändertes Verhalten (kein Filter).

- [ ] **Step 8: Commit**

```bash
git add src/dialogs/send_dialog.py
git commit -m "feat(ui): Kategorie-Auswahl im Sende-Dialog (#53)

Checkbox je vorhandener Kategorie (+ '(ohne Kategorie)'), alle vorgewählt;
die Auswahl wird als categories-Filter an generate_report/generate_pdf
durchgereicht (alle gewählt = kein Filter). Teil von AP4.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec-Coverage (Spec-Abschnitt „Report (report.py)" + „send_dialog"):**
- Zeile je Slot mit Spalten Datum/Tag/Kategorie/Start/Ende/Stunden → Task 1, `_week_block` ✓
- Tages-Subtotal bei >1 Slot; KW-Summen + Gesamt wie bisher → Task 1 ✓
- „Summe je Kategorie"-Block über den Zeitraum; „(ohne Kategorie)" → Task 1, `_build_category_summary` ✓
- Kategorie-Filter in `generate_report`/`generate_pdf` (Slot-Ebene, Default alle) → Task 1, `_apply_category_filter` ✓
- Tages-/KW-/Gesamt-Summen über Slots → `_slot_hours`/`_entry_hours`/`_week_block`/`_build_table` ✓
- HTML + PDF konsistent (beide Pfade Kategorie-Spalte + Summen-Block + Filter) → Task 1 ✓
- Kategorie escaped (freier Text) → `_esc(slot.kategorie)` + Test `test_kategorie_is_escaped` ✓
- Sende-Dialog: Mehrfachauswahl der Kategorien, Default alle, Auswahl fließt in den Report → Task 2 ✓
- Bewusst NICHT in AP4: Kategorie-Verwaltung (AP6), Share-Export-Filter (AP5), Kalender-Zellen (AP6).

**2. Placeholder-Scan:** Keine TBD/TODO; vollständiger Code in jedem Step. ✓

**3. Typ-Konsistenz:**
- `generate_report(..., categories=None)` / `generate_pdf(..., categories=None)` — Signaturen in report.py, Tests und send_dialog identisch. ✓
- `categories` = `set[str]|None`, `""` = ohne Kategorie — konsistent in `_apply_category_filter`, `_build_category_summary`, send_dialog `_selected_categories`. ✓
- AP1-Shape `{date:{"slots":[{start,end,pause,kategorie}]}}` — gelesen in `_week_block`/`_build_category_summary`/`_apply_category_filter` und send_dialog `present_categories`. ✓
- `CELL_BG` existiert in theme.py (verwendet in `apply_combobox_style`/`dark_entry`) und wird in send_dialog importiert. ✓
