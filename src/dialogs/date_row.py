"""Gemeinsames Tag/Monat/Jahr-Datums-Zeilen-Widget (Audit M14).

Früher dreifach implementiert (period_picker, import_dialog, tab_work) mit
divergierender Robustheit: nur `import_dialog` fing den `ValueError` beim
Tag-Clamp ab — `period_picker` und `tab_work` crashten, sobald ein Feld einen
nicht-numerischen Wert trug. Diese eine Implementierung ist durchgängig robust.

`build_date_row` liefert ein selbst-enthaltenes Frame (Label + drei
`dark_combo`-Felder für Tag/Monat/Jahr), das der Aufrufer via grid/pack
platziert. Die reine Kernlogik `max_day_for` ist Tk-frei und getestet.
"""
from __future__ import annotations

import calendar
import datetime
import tkinter as tk
from typing import Callable

from src.theme import BG, FONT, TEXT, dark_combo


def max_day_for(month_value: str, year_value: str) -> int:
    """Monatslänge (28–31) für die (String-)Combobox-Werte von Monat und Jahr.

    Bei nicht-numerischem oder ungültigem Monat/Jahr ist der Fallback 31 — der
    Tag-Combobox wird dann nicht künstlich beschnitten. Kapselt genau den
    Robustheits-Kern, den vorher nur `import_dialog` hatte (Audit M14)."""
    try:
        return calendar.monthrange(int(year_value), int(month_value))[1]
    except (ValueError, KeyError):
        return 31


class DateRow:
    """Handle auf eine gebaute Datumszeile: das Frame plus die drei Tk-Vars.

    Der Aufrufer platziert `frame` (grid/pack) und liest Tag/Monat/Jahr über
    `vars` bzw. die Einzel-Attribute."""

    def __init__(self, frame: tk.Frame, day_var: tk.StringVar,
                 month_var: tk.StringVar, year_var: tk.StringVar) -> None:
        self.frame = frame
        self.day_var = day_var
        self.month_var = month_var
        self.year_var = year_var

    @property
    def vars(self) -> tuple[tk.StringVar, tk.StringVar, tk.StringVar]:
        return self.day_var, self.month_var, self.year_var


def build_date_row(parent: tk.Misc, label_text: str, default_date: datetime.date, *,
                   on_change: Callable[[], None] | None = None,
                   year_from: int = 2020, year_to_offset: int = 2,
                   label_width: int = 0) -> DateRow:
    """Baut eine Tag/Monat/Jahr-Zeile in ein eigenes Frame und liefert das Handle.

    - on_change: optionaler Callback bei jeder Benutzer-Änderung an Tag, Monat
      oder Jahr (Vorschau aktualisieren / Zähler neu berechnen). Wird beim
      initialen Aufbau NICHT gefeuert.
    - year_from / year_to_offset: Jahresbereich `range(year_from,
      heute.Jahr + year_to_offset)`.
    - label_width: feste Label-Breite in Zeichen (0 = natürlich) — für
      Spaltenausrichtung mehrerer Zeilen untereinander.
    """
    frame = tk.Frame(parent, bg=BG)
    tk.Label(frame, text=label_text, font=FONT, bg=BG, fg=TEXT,
             width=label_width, anchor="w").pack(side=tk.LEFT, padx=(0, 5))

    today = datetime.date.today()
    month_values = [str(m) for m in range(1, 13)]
    year_values = [str(y) for y in range(year_from, today.year + year_to_offset)]

    day_var = tk.StringVar(value=str(default_date.day))
    start_max_day = calendar.monthrange(default_date.year, default_date.month)[1]
    day_cb = dark_combo(frame, day_var, [str(d) for d in range(1, start_max_day + 1)], width=3)
    day_cb.pack(side=tk.LEFT, padx=2)
    tk.Label(frame, text=".", font=FONT, bg=BG, fg=TEXT).pack(side=tk.LEFT)
    month_var = tk.StringVar(value=str(default_date.month))
    dark_combo(frame, month_var, month_values, width=3).pack(side=tk.LEFT, padx=2)
    tk.Label(frame, text=".", font=FONT, bg=BG, fg=TEXT).pack(side=tk.LEFT)
    year_var = tk.StringVar(value=str(default_date.year))
    dark_combo(frame, year_var, year_values, width=5).pack(side=tk.LEFT, padx=(2, 10))

    def _on_write(*_a) -> None:
        md = max_day_for(month_var.get(), year_var.get())
        day_cb["values"] = [str(d) for d in range(1, md + 1)]
        # Tag-Clamp defensiv: der Tag-Combobox kann während der Eingabe einen
        # nicht-numerischen Zwischenwert tragen (Audit M14 — vorher crashten
        # period_picker/tab_work hier).
        try:
            if int(day_var.get()) > md:
                day_var.set(str(md))
        except ValueError:
            pass
        if on_change is not None:
            on_change()

    day_var.trace_add("write", _on_write)
    month_var.trace_add("write", _on_write)
    year_var.trace_add("write", _on_write)
    return DateRow(frame, day_var, month_var, year_var)
