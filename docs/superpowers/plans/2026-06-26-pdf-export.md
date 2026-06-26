# PDF-Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine dritte Footer-Aktion „Export" erzeugt aus einem Zeitraum+Kategorie-Modal die PDF und speichert sie lokal über einen „Speichern unter"-Dialog.

**Architecture:** Der geteilte Zeitraum+Kategorie+Vorschau-Picker wird aus `send_dialog` in ein neues Modul `period_picker.py` extrahiert (Ansatz B). Senden **und** der neue Export-Dialog nutzen ihn. Zwei kleine pure Helfer (`default_pdf_filename`, `validate_period`) werden ebenfalls geteilt und headless getestet. Der Export-Dialog hat keine Gmail-Abhängigkeit.

**Tech Stack:** Python 3.11, Tkinter, pytest. PDF via `report.generate_pdf` (xhtml2pdf, lazy import). Datei-Dialog via `tkinter.filedialog`.

## Global Constraints

- **CI ohne `requirements.txt`:** Tests laufen mit pytest + holidays + google-libs, **nicht** mit `xhtml2pdf`. Jeder Test, der `generate_pdf` aufruft, muss `xhtml2pdf` mocken (`patch.dict("sys.modules", {"xhtml2pdf": fake})`).
- **Keine Tk-Display-Abhängigkeit in Tests:** Neue Unit-Tests dürfen kein `tk.Tk()` erzeugen. `import tkinter` auf Modulebene ist erlaubt (läuft headless im CI, vgl. bestehende `test_ui_*`).
- **App-Start als Modul:** `python -m src.main` (absolute `from src...`-Imports).
- **`generate_pdf` bleibt unverändert** (I/O-frei, liefert Bytes oder `None`). Das Schreiben auf Platte passiert im Dialog.
- **UI-Fehler sichtbar machen:** `--noconsole` verschluckt stderr. Fehler im Erzeugen/Speichern **müssen** per `messagebox`/`themed_showerror` (mit `traceback.format_exc()` bei unerwarteten Exceptions) gezeigt werden.
- **Lint:** `ruff check .` muss grün sein (fängt ungenutzte Imports F401 / undefinierte Namen F821).
- **Commits:** Author ist via repo-lokaler `git config` bereits `Sven-MH`. Keine `--no-verify`/`--force`.
- **Branch:** `feat/pdf-export` (existiert, von `origin/master`).

---

### Task 1: `default_pdf_filename` + generate_pdf-None-Contract (report.py)

**Files:**
- Modify: `src/report.py` (neue pure Funktion ans Modul-Ende oder nach `total_hours` bei Zeile ~115)
- Test: `tests/test_report.py`

**Interfaces:**
- Produces: `default_pdf_filename(date_from: datetime.date, date_to: datetime.date) -> str`

- [ ] **Step 1: Failing test für `default_pdf_filename` schreiben** (an `tests/test_report.py` anhängen)

```python
def test_default_pdf_filename_format():
    import datetime
    from src.report import default_pdf_filename
    assert default_pdf_filename(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31)
    ) == "Zeiterfassung_20260301_20260331.pdf"
```

- [ ] **Step 2: Test ausführen, Fehlschlag prüfen**

Run: `python -m pytest tests/test_report.py::test_default_pdf_filename_format -v`
Expected: FAIL (`ImportError: cannot import name 'default_pdf_filename'`)

- [ ] **Step 3: Implementieren** (in `src/report.py`, z.B. direkt nach `total_hours`)

```python
def default_pdf_filename(date_from, date_to):
    """Default-Dateiname für den PDF-Bericht: Zeiterfassung_<VON>_<BIS>.pdf
    mit Datums-Stempeln im Format YYYYMMDD (z.B.
    Zeiterfassung_20260301_20260331.pdf). Genutzt vom Senden- (Mail-Anhang)
    und vom Export-Pfad."""
    return f"Zeiterfassung_{date_from:%Y%m%d}_{date_to:%Y%m%d}.pdf"
```

- [ ] **Step 4: Test ausführen, grün prüfen**

Run: `python -m pytest tests/test_report.py::test_default_pdf_filename_format -v`
Expected: PASS

- [ ] **Step 5: None-Contract-Test für `generate_pdf` schreiben** (dokumentiert das Verhalten, auf das Export sich verlässt; `xhtml2pdf` gemockt)

```python
def test_generate_pdf_returns_none_for_empty_range():
    import datetime
    from unittest.mock import MagicMock
    from unittest.mock import patch
    from src import report as report_mod
    fake_xhtml2pdf = MagicMock()
    with patch.dict("sys.modules", {"xhtml2pdf": fake_xhtml2pdf}):
        result = report_mod.generate_pdf(
            datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), {})
    assert result is None
```

(Hinweis: `from unittest.mock import MagicMock, patch` steht oben in `tests/test_report.py` evtl. schon — dann die lokalen Imports weglassen.)

- [ ] **Step 6: Test ausführen, grün prüfen**

Run: `python -m pytest tests/test_report.py::test_generate_pdf_returns_none_for_empty_range -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/report.py tests/test_report.py
git commit -m "feat(report): default_pdf_filename + generate_pdf None-Contract-Test"
```

---

### Task 2: `validate_period` (time_utils.py)

**Files:**
- Modify: `src/time_utils.py` (neue Funktion direkt nach `validate_entry`, ~Zeile 50)
- Test: `tests/test_time_calc.py`

**Interfaces:**
- Produces: `validate_period(date_from: datetime.date, date_to: datetime.date) -> tuple[bool, str]`

- [ ] **Step 1: Failing tests schreiben** (an `tests/test_time_calc.py` anhängen)

```python
def test_validate_period_from_after_to_is_invalid():
    import datetime
    from src.time_utils import validate_period
    ok, msg = validate_period(datetime.date(2026, 3, 31), datetime.date(2026, 3, 1))
    assert ok is False
    assert "Von-Datum" in msg


def test_validate_period_equal_dates_ok():
    import datetime
    from src.time_utils import validate_period
    ok, msg = validate_period(datetime.date(2026, 3, 1), datetime.date(2026, 3, 1))
    assert ok is True
    assert msg == ""


def test_validate_period_from_before_to_ok():
    import datetime
    from src.time_utils import validate_period
    ok, _ = validate_period(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))
    assert ok is True
```

- [ ] **Step 2: Tests ausführen, Fehlschlag prüfen**

Run: `python -m pytest tests/test_time_calc.py -k validate_period -v`
Expected: FAIL (`ImportError: cannot import name 'validate_period'`)

- [ ] **Step 3: Implementieren** (in `src/time_utils.py`, nach `validate_entry`)

```python
def validate_period(date_from, date_to):
    """Validiert einen Datums-Zeitraum für Bericht/Export. Liefert
    (ok, fehlermeldung). von > bis ist ungültig; von == bis ist erlaubt
    (Ein-Tages-Bericht)."""
    if date_from > date_to:
        return False, "Das Von-Datum muss vor dem Bis-Datum liegen."
    return True, ""
```

- [ ] **Step 4: Tests ausführen, grün prüfen**

Run: `python -m pytest tests/test_time_calc.py -k validate_period -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/time_utils.py tests/test_time_calc.py
git commit -m "feat(time_utils): validate_period für Bericht/Export-Zeitraum"
```

---

### Task 3: `period_picker.py` — pure Kategorie-Logik + geteilter Tk-Picker

**Files:**
- Create: `src/dialogs/period_picker.py`
- Test: `tests/test_period_picker.py`

**Interfaces:**
- Consumes: `report.total_hours`, `theme.{BG, CELL_BG, FONT, TEXT, dark_combo}`
- Produces:
  - `selected_category_filter(selected_map: dict[str, bool]) -> set[str] | None`
  - `build_period_picker(parent, storage, settings) -> tuple[tk.Frame, handle]`
    wobei `handle.get_range() -> tuple[date, date] | tuple[None, None]` und
    `handle.get_categories() -> set[str] | None`

- [ ] **Step 1: Failing tests für `selected_category_filter` schreiben** (`tests/test_period_picker.py`)

```python
def test_selected_category_filter_empty_map_is_none():
    from src.dialogs.period_picker import selected_category_filter
    assert selected_category_filter({}) is None


def test_selected_category_filter_all_selected_is_none():
    from src.dialogs.period_picker import selected_category_filter
    assert selected_category_filter({"Büro": True, "HO": True}) is None


def test_selected_category_filter_partial_returns_selected_set():
    from src.dialogs.period_picker import selected_category_filter
    assert selected_category_filter({"Büro": True, "HO": False}) == {"Büro"}


def test_selected_category_filter_none_selected_returns_empty_set():
    # keiner ausgewählt ist NICHT "alle" -> leere Menge (Filter ohne Treffer),
    # exakt die bisherige send_dialog-Semantik.
    from src.dialogs.period_picker import selected_category_filter
    assert selected_category_filter({"Büro": False, "HO": False}) == set()
```

- [ ] **Step 2: Tests ausführen, Fehlschlag prüfen**

Run: `python -m pytest tests/test_period_picker.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.dialogs.period_picker'`)

- [ ] **Step 3: Modul anlegen mit pure Helfer + Tk-Picker** (`src/dialogs/period_picker.py`)

```python
import calendar
import datetime
import tkinter as tk

from src.report import total_hours
from src.theme import BG, CELL_BG, FONT, TEXT, dark_combo


def selected_category_filter(selected_map):
    """selected_map: {kategorie: bool}. Liefert None, wenn keine Kategorien
    existieren ODER alle ausgewählt sind (= kein Filter), sonst die Menge der
    ausgewählten Kategorien. Identisch zur bisherigen send_dialog-Semantik
    (`_selected_categories`)."""
    if not selected_map:
        return None
    selected = {kat for kat, on in selected_map.items() if on}
    if len(selected) == len(selected_map):
        return None
    return selected


def _default_from_date(today):
    """Vormonats-Pendant zu heute (Tag auf Monatslänge gekappt). Default für
    das Von-Datum."""
    if today.month == 1:
        return today.replace(year=today.year - 1, month=12)
    from_month = today.month - 1
    max_day = calendar.monthrange(today.year, from_month)[1]
    return today.replace(month=from_month, day=min(today.day, max_day))


class _PeriodPickerHandle:
    """Lese-Schnittstelle auf die Picker-Widgets, ohne dass der Aufrufer die
    Tk-Vars kennt."""

    def __init__(self, from_vars, to_vars, category_vars):
        self._from = from_vars        # (day_var, month_var, year_var)
        self._to = to_vars            # (day_var, month_var, year_var)
        self._cats = category_vars    # {kategorie: BooleanVar}

    def get_range(self):
        try:
            df = datetime.date(
                int(self._from[2].get()), int(self._from[1].get()), int(self._from[0].get()))
            dt = datetime.date(
                int(self._to[2].get()), int(self._to[1].get()), int(self._to[0].get()))
        except ValueError:
            return None, None
        return df, dt

    def get_categories(self):
        return selected_category_filter({k: v.get() for k, v in self._cats.items()})


def build_period_picker(parent, storage, settings):
    """Baut Von/Bis-Datumszeilen + Kategorie-Checkboxen + Live-Stundenvorschau
    in einen eigenen Frame. Liefert (frame, handle). Der Frame wird vom
    Aufrufer ins Dialog-Layout gegridded; die Aktions-Buttons bleiben Sache
    des Aufrufers (Senden bzw. Export)."""
    frame = tk.Frame(parent, bg=BG)

    today = datetime.date.today()
    from_default = _default_from_date(today)
    month_values = [str(m) for m in range(1, 13)]
    year_values = [str(y) for y in range(2020, today.year + 2)]

    def update_day_values(day_cb, day_var, month_var, year_var):
        try:
            m = int(month_var.get())
            y = int(year_var.get())
            max_day = calendar.monthrange(y, m)[1]
        except (ValueError, KeyError):
            max_day = 31
        day_cb["values"] = [str(d) for d in range(1, max_day + 1)]
        if int(day_var.get()) > max_day:
            day_var.set(str(max_day))

    def build_date_row(row, label_text, default_date):
        tk.Label(frame, text=label_text, font=FONT, bg=BG, fg=TEXT).grid(
            row=row, column=0, padx=(10, 5), pady=8, sticky="w")
        day_var = tk.StringVar(value=str(default_date.day))
        max_day = calendar.monthrange(default_date.year, default_date.month)[1]
        day_cb = dark_combo(frame, day_var, [str(d) for d in range(1, max_day + 1)], width=3)
        day_cb.grid(row=row, column=1, padx=2, pady=8)
        tk.Label(frame, text=".", font=FONT, bg=BG, fg=TEXT).grid(row=row, column=2)
        month_var = tk.StringVar(value=str(default_date.month))
        dark_combo(frame, month_var, month_values, width=3).grid(row=row, column=3, padx=2, pady=8)
        tk.Label(frame, text=".", font=FONT, bg=BG, fg=TEXT).grid(row=row, column=4)
        year_var = tk.StringVar(value=str(default_date.year))
        dark_combo(frame, year_var, year_values, width=5).grid(row=row, column=5, padx=(2, 10), pady=8)
        month_var.trace_add("write", lambda *_: update_day_values(day_cb, day_var, month_var, year_var))
        year_var.trace_add("write", lambda *_: update_day_values(day_cb, day_var, month_var, year_var))
        return day_var, month_var, year_var

    from_vars = build_date_row(0, "Von:", from_default)
    to_vars = build_date_row(1, "Bis:", today)

    # Kategorien aus Bestand UND Settings-Pickliste ("" = ohne Kategorie). Alle
    # default ausgewählt. Bewusst NICHT auf den Zeitraum eingeschränkt (vgl.
    # bisheriger send_dialog-Kommentar).
    all_entries = storage.get_all()
    present_categories = sorted(
        {(s.get("kategorie") or "") for e in all_entries.values() for s in e["slots"]}
        | {c for c in (settings.get("categories") or [])},
        key=lambda k: (k == "", k.lower()),
    )
    category_vars = {}
    if present_categories:
        tk.Label(frame, text="Kategorien:", font=FONT, bg=BG, fg=TEXT).grid(
            row=2, column=0, padx=(10, 5), pady=(4, 8), sticky="nw")
        cat_frame = tk.Frame(frame, bg=BG)
        cat_frame.grid(row=2, column=1, columnspan=5, padx=(0, 10), pady=(4, 8), sticky="w")
        for kat in present_categories:
            var = tk.BooleanVar(value=True)
            category_vars[kat] = var
            label = kat if kat else "(ohne Kategorie)"
            tk.Checkbutton(
                cat_frame, text=label, variable=var,
                command=lambda: _update_total(),
                font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT,
                highlightthickness=0, bd=0, anchor="w",
            ).pack(anchor="w")

    handle = _PeriodPickerHandle(from_vars, to_vars, category_vars)

    # Live-Vorschau (Gesamtstunden über den Build-Zeit-Snapshot all_entries).
    total_label = tk.Label(frame, text="", font=FONT, bg=BG, fg=TEXT)
    total_label.grid(row=3, column=0, columnspan=6, padx=10, pady=(0, 8), sticky="w")

    def _update_total(*_):
        df, dt = handle.get_range()
        if df is None or dt is None or df > dt:
            total_label.config(text="Gesamtstunden: —")
            return
        hours = total_hours(df, dt, all_entries, handle.get_categories())
        total_label.config(text=f"Gesamtstunden: {hours}h")

    for _v in (*from_vars, *to_vars):
        _v.trace_add("write", _update_total)
    _update_total()

    return frame, handle
```

- [ ] **Step 4: Tests ausführen, grün prüfen**

Run: `python -m pytest tests/test_period_picker.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Import-/Lint-Check** (Modul lädt headless, keine ungenutzten Namen)

Run: `python -c "import src.dialogs.period_picker"` (Expected: kein Output, Exit 0)
Run: `ruff check src/dialogs/period_picker.py tests/test_period_picker.py` (Expected: `All checks passed!`)

- [ ] **Step 6: Commit**

```bash
git add src/dialogs/period_picker.py tests/test_period_picker.py
git commit -m "feat(dialogs): geteilten period_picker extrahieren (Zeitraum+Kategorie+Vorschau)"
```

---

### Task 4: `send_dialog` auf den Picker umstellen

**Files:**
- Modify: `src/dialogs/send_dialog.py`

**Interfaces:**
- Consumes: `period_picker.build_period_picker`, `time_utils.validate_period`, `report.default_pdf_filename`

**Hintergrund:** Verhalten des Senden-Pfads bleibt identisch — nur die Maske kommt jetzt aus dem geteilten Picker. Kein Unit-Test (Tk-Dialog); Absicherung über volle Suite (keine Regression in Report-/Settings-Tests), `ruff` und manuelles QA.

- [ ] **Step 1: Imports anpassen** (`src/dialogs/send_dialog.py`, oben)

`from src.report import generate_pdf, generate_report, total_hours` →
```python
from src.report import default_pdf_filename, generate_pdf, generate_report
```
Ergänzen:
```python
from src.time_utils import validate_period
from src.dialogs.period_picker import build_period_picker
```

- [ ] **Step 2: Inline-Maske + Helfer entfernen**

Löschen:
- die Funktion `_default_from_date` (Zeilen ~67–72, jetzt im Picker),
- in `open_send_dialog` den gesamten Block von `today = datetime.date.today()` bis einschließlich `_update_total()` (Zeilen ~106–212): `update_day_values`, `build_date_row`, die beiden `build_date_row`-Aufrufe, den Kategorie-Block, `_selected_categories`, `total_label`, `_current_range`, `_update_total` und die Trace-Schleife.

Direkt nach `dialog.bind("<Escape>", ...)` einsetzen:
```python
    picker_frame, picker = build_period_picker(dialog, storage, settings)
    picker_frame.grid(row=0, column=0, sticky="w")
```

- [ ] **Step 3: `do_send` auf den Picker umstellen**

Den Kopf von `do_send` (Datumsparsing + von>bis-Check, Zeilen ~215–228) ersetzen durch:
```python
    def do_send():
        date_from, date_to = picker.get_range()
        if date_from is None:
            themed_showerror(dialog, "Ungültiges Datum", "Bitte ein gültiges Datum eingeben.")
            return
        ok, msg = validate_period(date_from, date_to)
        if not ok:
            themed_showerror(dialog, "Ungültiger Zeitraum", msg)
            return

        entries = storage.get_all()
        categories = picker.get_categories()
```
(Die alten Zeilen `entries = storage.get_all()` und `categories = _selected_categories()` damit ersetzen — nicht doppeln.)

In `do_send` weiter unten den Inline-Dateinamen
`pdf_filename = f"Zeiterfassung_{date_from.strftime('%Y%m%d')}_{date_to.strftime('%Y%m%d')}.pdf"`
ersetzen durch:
```python
            pdf_filename = default_pdf_filename(date_from, date_to)
```

Den Button-Frame `btn_frame` von `row=4` auf `row=1` setzen (der Picker belegt jetzt nur noch Dialog-Row 0):
```python
    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=1, column=0, columnspan=6, pady=12)
```

- [ ] **Step 4: Ungenutzte Imports/Namen entfernen via ruff**

Run: `ruff check src/dialogs/send_dialog.py`
Erwartet werden F401-Hinweise auf jetzt ungenutzte Namen — entfernen, was gemeldet wird (voraussichtlich: `calendar`, `total_hours`, sowie aus dem `theme`-Import `CELL_BG`, `dark_combo`, evtl. `FONT`/`TEXT`, falls im Rest der Datei nicht mehr genutzt). **Nur** entfernen, was ruff als ungenutzt meldet.
Danach erneut: `ruff check src/dialogs/send_dialog.py` → `All checks passed!`

- [ ] **Step 5: Volle Suite + Import-Check** (keine Regression)

Run: `python -c "import src.dialogs.send_dialog"` (Expected: Exit 0)
Run: `python -m pytest -q` (Expected: alle grün, gleiche Anzahl wie vor Task 4 + die neuen Tests)

- [ ] **Step 6: Manuelles QA Senden** (Display nötig)

`python -m src.main` → „Arbeitszeiten senden" → Maske rendert (Von/Bis, Kategorien, Vorschau), Vorschau aktualisiert bei Datums-/Kategorie-Änderung. (Tatsächlicher Versand nur, falls Gmail eingerichtet — sonst reicht die Maske + Vorschau als Regressions-Check.)

- [ ] **Step 7: Commit**

```bash
git add src/dialogs/send_dialog.py
git commit -m "refactor(send_dialog): geteilten period_picker + validate_period/default_pdf_filename nutzen"
```

---

### Task 5: `export_dialog.py`

**Files:**
- Create: `src/dialogs/export_dialog.py`

**Interfaces:**
- Consumes: `period_picker.build_period_picker`, `time_utils.validate_period`, `report.{default_pdf_filename, generate_pdf}`
- Produces: `open_export_dialog(parent, storage, settings)`

**Hinweis:** Kein `base_path`-Parameter — Export braucht keine Credentials. (Bewusste Vereinfachung gegenüber der defensiv im Spec gelisteten Signatur.) Kein Unit-Test (Tk-Dialog); Absicherung über Import-Check, `ruff` und manuelles QA.

- [ ] **Step 1: Modul anlegen** (`src/dialogs/export_dialog.py`)

```python
import logging
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox

from src.report import default_pdf_filename, generate_pdf
from src.time_utils import validate_period
from src.dialogs.period_picker import build_period_picker
from src.theme import (
    BG,
    apply_app_icon, apply_combobox_style, apply_dark_titlebar,
    attach_unfocus_on_click, center_dialog_on_parent,
    disable_min_max, primary_button, secondary_button,
    themed_showerror, themed_showinfo,
)


def open_export_dialog(parent, storage, settings):
    """Modal: Zeitraum + Kategorien wählen, daraus die PDF erzeugen und lokal
    über einen 'Speichern unter'-Dialog speichern. Kein Gmail nötig."""
    dialog = tk.Toplevel(parent)
    dialog.title("Als PDF exportieren")
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.focus_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)
    disable_min_max(dialog)
    apply_app_icon(dialog)
    apply_combobox_style(dialog)
    attach_unfocus_on_click(dialog)
    dialog.bind("<Escape>", lambda _e: dialog.destroy())

    picker_frame, picker = build_period_picker(dialog, storage, settings)
    picker_frame.grid(row=0, column=0, sticky="w")

    def do_export():
        date_from, date_to = picker.get_range()
        if date_from is None:
            themed_showerror(dialog, "Ungültiges Datum", "Bitte ein gültiges Datum eingeben.")
            return
        ok, msg = validate_period(date_from, date_to)
        if not ok:
            themed_showerror(dialog, "Ungültiger Zeitraum", msg)
            return

        # Frisch lesen (Hintergrund-Drive-Sync könnte den Storage geändert haben).
        entries = storage.get_all()
        categories = picker.get_categories()

        # Erst erzeugen, dann nach dem Pfad fragen — so erscheint der Speichern-
        # Dialog bei leerem Zeitraum gar nicht erst.
        try:
            pdf_bytes = generate_pdf(
                date_from, date_to, entries,
                name=settings.get("name"), categories=categories)
        except Exception as e:
            logging.getLogger(__name__).exception("PDF-Erzeugung fehlgeschlagen")
            messagebox.showerror(
                "Export fehlgeschlagen",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=dialog,
            )
            return

        if pdf_bytes is None:
            themed_showinfo(
                dialog, "Keine Einträge",
                f"Keine Einträge für {date_from.strftime('%d.%m.%Y')} – "
                f"{date_to.strftime('%d.%m.%Y')} vorhanden.",
            )
            return

        path = filedialog.asksaveasfilename(
            parent=dialog,
            title="PDF speichern unter",
            initialfile=default_pdf_filename(date_from, date_to),
            defaultextension=".pdf",
            filetypes=[("PDF-Datei", "*.pdf")],
        )
        if not path:
            return

        try:
            with open(path, "wb") as f:
                f.write(pdf_bytes)
        except OSError as e:
            themed_showerror(
                dialog, "Export fehlgeschlagen",
                f"Die Datei konnte nicht gespeichert werden:\n{e}")
            return

        dialog.destroy()
        themed_showinfo(parent, "Exportiert", f"PDF gespeichert unter\n{path}")

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=1, column=0, pady=12)
    primary_button(btn_frame, "Exportieren", do_export).pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    center_dialog_on_parent(dialog, parent)
```

- [ ] **Step 2: Import-/Lint-Check**

Run: `python -c "import src.dialogs.export_dialog"` (Expected: Exit 0)
Run: `ruff check src/dialogs/export_dialog.py` (Expected: `All checks passed!`)

- [ ] **Step 3: Commit**

```bash
git add src/dialogs/export_dialog.py
git commit -m "feat(dialogs): export_dialog (Zeitraum-Modal -> PDF lokal speichern)"
```

---

### Task 6: Footer-Button + Tray-Eintrag (ui.py)

**Files:**
- Modify: `src/ui.py` (Footer ~Zeilen 262–267, `_export`-Methode bei den anderen Handlern ~515–523, Tray-Actions ~366–373)

**Interfaces:**
- Consumes: `export_dialog.open_export_dialog`

- [ ] **Step 1: Footer-Button „Export" ergänzen**

Den Footer-Block ersetzen durch (Reihenfolge links→rechts: Senden, Export, Teilen):
```python
        secondary_button(
            footer_frame, "Teilen", self._share, padx=12,
        ).pack(side=tk.RIGHT, padx=(0, 4))
        secondary_button(
            footer_frame, "Export", self._export, padx=12,
        ).pack(side=tk.RIGHT, padx=(0, 4))
        secondary_button(
            footer_frame, "Arbeitszeiten senden", self._send, padx=12,
        ).pack(side=tk.RIGHT)
```

- [ ] **Step 2: `_export`-Handler ergänzen** (direkt nach `_share`, ~Zeile 523)

```python
    def _export(self):
        from src.dialogs.export_dialog import open_export_dialog
        open_export_dialog(self.root, self.storage, self.settings)
```

- [ ] **Step 3: Tray-Eintrag „Export" ergänzen** (in der `actions=[...]`-Liste, nach „Teilen")

```python
                    ("Export",
                     lambda: self.root.after(0, self._export), None),
```

- [ ] **Step 4: Suite + Import-/Lint-Check**

Run: `python -c "import src.ui"` (Expected: Exit 0)
Run: `python -m pytest -q` (Expected: alle grün)
Run: `ruff check src/ui.py` (Expected: `All checks passed!`)

- [ ] **Step 5: Manuelles QA Export** (Display nötig)

`python -m src.main`:
1. Footer zeigt drei Buttons in Reihenfolge „Arbeitszeiten senden", „Export", „Teilen".
2. „Export" → Modal „Als PDF exportieren" mit Zeitraum + Kategorien + Vorschau.
3. Gültiger Zeitraum mit Einträgen → „Exportieren" → „Speichern unter" mit vorbefülltem Namen `Zeiterfassung_<VON>_<BIS>.pdf` → speichern → Bestätigung „PDF gespeichert unter …", PDF liegt auf Platte und ist gültig.
4. Zeitraum ohne Einträge → „Exportieren" → „Keine Einträge", **kein** Speichern-Dialog.
5. „Speichern unter" abbrechen → kein Fehler, Dialog bleibt offen.
6. Tray-Menü (falls Tray aktiv, Win/macOS) zeigt „Export".

- [ ] **Step 6: Commit**

```bash
git add src/ui.py
git commit -m "feat(ui): Footer- und Tray-Aktion 'Export' verdrahten"
```

---

## Manuelles QA (Gesamt, vor PR)

Da Picker/Senden/Export Tk-Dialoge sind und im CI nicht ausgeführt werden, vor dem PR einmal komplett durchklicken (`python -m src.main`):

1. **Senden (Regression):** Maske rendert wie vorher, Live-Vorschau aktualisiert, Kategorie-Filter wirkt auf die Vorschau.
2. **Export Happy-Path:** Zeitraum mit Daten → PDF speichern → öffnen → Inhalt stimmt (Zeitraum, Kategorien, Stunden).
3. **Export Kategorie-Filter:** Nur eine Kategorie anhaken → exportierte PDF enthält nur diese.
4. **Export leer:** Zeitraum ohne Einträge → „Keine Einträge", kein Speichern-Dialog.
5. **Export abbrechen:** „Speichern unter" schließen → No-op.
6. **Schreibfehler (optional):** Pfad ohne Schreibrecht wählen → themed Fehlermeldung.

## Self-Review

**Spec-Coverage:**
- Footer-Aktion „Export" + `_export` → Task 6. ✓
- „Speichern unter" mit vorbefülltem Namen → Task 5 (`asksaveasfilename` + `default_pdf_filename`). ✓
- Nur Bestätigung, kein Auto-Öffnen → Task 5 (`themed_showinfo`, kein open). ✓
- Volle Maske (Zeitraum+Kategorie+Vorschau) → Task 3 (`build_period_picker`). ✓
- Ansatz B (Picker geteilt) → Task 3 + Task 4 (Senden nutzt ihn). ✓
- `default_pdf_filename` / `validate_period` geteilt → Task 1/2, genutzt in Task 4/5. ✓
- Tray-Eintrag → Task 6. ✓
- „Erst generieren, dann Pfad fragen" + leer-Abfang → Task 5. ✓
- Fehlerbehandlung (ungültiges Datum, von>bis, None, OSError, Abbruch) → Task 5. ✓
- Tests headless, xhtml2pdf gemockt → Task 1/2/3 (kein realer `generate_pdf`-Aufruf ohne Mock). ✓

**Placeholder-Scan:** Kein TBD/TODO; jeder Code-Step enthält vollständigen Code. ✓

**Typ-Konsistenz:** `build_period_picker → (frame, handle)`; `handle.get_range() → (date,date)|(None,None)`; `handle.get_categories() → set|None`; `selected_category_filter(dict[str,bool]) → set|None`; `default_pdf_filename(date,date) → str`; `validate_period(date,date) → (bool,str)`. In Task 4/5 konsistent verwendet. ✓
