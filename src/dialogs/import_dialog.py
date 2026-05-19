"""Modal-Dialog „Arbeitszeiten importieren": Datei-Pick, Summary mit
Zeitraum-Filter + Konflikt-Modi, optional Pro-Tag-Modal, atomarer Apply."""

import calendar
import datetime
import logging
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox

from src.share import (
    ShareValidationError,
    apply_import,
    diff_share_against_local,
    parse_share_doc,
)
from src.theme import (
    BG, CELL_BG, FONT, FONT_SMALL, TEXT, TEXT_MUTED,
    apply_combobox_style, apply_dark_titlebar, center_dialog_on_parent,
    dark_combo, primary_button, secondary_button, themed_showinfo,
)


def open_import_dialog(parent, storage, settings, on_change):
    """Startet den Import-Flow. on_change wird bei erfolgreichem Apply aufgerufen
    (damit der Kalender re-rendert)."""
    path = filedialog.askopenfilename(
        parent=parent,
        title="Share-Datei auswählen",
        filetypes=[("Zeiterfassung Share", "*.json"), ("Alle Dateien", "*.*")],
    )
    if not path:
        return

    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        messagebox.showerror(
            "Datei nicht lesbar",
            f"{type(e).__name__}: {e}",
            parent=parent,
        )
        return

    try:
        doc = parse_share_doc(raw)
    except ShareValidationError as e:
        messagebox.showerror(
            "Datei ungültig",
            f"Die Datei kann nicht importiert werden:\n\n{e.reason}",
            parent=parent,
        )
        return

    share_entries = doc["entries"]
    if not share_entries:
        messagebox.showinfo(
            "Leere Datei",
            "Die Datei enthält keine Einträge.",
            parent=parent,
        )
        return

    dates = sorted(datetime.date.fromisoformat(d) for d in share_entries.keys())
    file_min, file_max = dates[0], dates[-1]

    _ImportSummaryDialog(parent, storage, doc, file_min, file_max, on_change).show()


class _ImportSummaryDialog:
    def __init__(self, parent, storage, doc, file_min, file_max, on_change):
        self.parent = parent
        self.storage = storage
        self.doc = doc
        self.share_entries = doc["entries"]
        self.file_min = file_min
        self.file_max = file_max
        self.on_change = on_change

        self.top = tk.Toplevel(parent)
        self.top.title("Arbeitszeiten importieren")
        self.top.resizable(False, False)
        self.top.grab_set()
        self.top.configure(bg=BG)
        apply_dark_titlebar(self.top)
        apply_combobox_style(self.top)

        self._build()
        center_dialog_on_parent(self.top, parent)

    def show(self):
        self.top.wait_window()

    def _build(self):
        row = 0
        tk.Label(
            self.top,
            text=f"Datei: zeiterfassung-share (geteilt von "
                 f"{self.doc.get('exported_by') or 'unbekannt'})",
            font=FONT, bg=BG, fg=TEXT, justify="left",
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(10, 4), sticky="w")
        row += 1

        tk.Label(
            self.top,
            text=f"Exportiert: {self.doc.get('exported_at', '')}",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, justify="left",
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(0, 10), sticky="w")
        row += 1

        tk.Label(
            self.top, text="Zeitraum filtern:", font=FONT, bg=BG, fg=TEXT,
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(4, 0), sticky="w")
        row += 1

        self.from_day, self.from_month, self.from_year = self._build_date_row(
            row, "Von:", self.file_min)
        row += 1
        self.to_day, self.to_month, self.to_year = self._build_date_row(
            row, "Bis:", self.file_max)
        row += 1

        tk.Label(
            self.top,
            text=f"Voller Bereich der Datei: "
                 f"{self.file_min.isoformat()} bis {self.file_max.isoformat()}",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(0, 8), sticky="w")
        row += 1

        self.counts_label = tk.Label(
            self.top, text="", font=FONT, bg=BG, fg=TEXT, justify="left",
        )
        self.counts_label.grid(row=row, column=0, columnspan=6, padx=10, pady=(4, 4), sticky="w")
        row += 1

        tk.Label(
            self.top, text="Konflikt-Behandlung:", font=FONT, bg=BG, fg=TEXT,
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(8, 0), sticky="w")
        row += 1

        self.mode_var = tk.StringVar(value="import")
        for mode_value, mode_label in [
            ("import", "Alles vom Import übernehmen"),
            ("local", "Alles lokal behalten"),
            ("per_day", "Pro Tag entscheiden"),
        ]:
            tk.Radiobutton(
                self.top, text=mode_label, variable=self.mode_var, value=mode_value,
                font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT,
            ).grid(row=row, column=0, columnspan=6, padx=20, pady=0, sticky="w")
            row += 1

        btn_frame = tk.Frame(self.top, bg=BG)
        btn_frame.grid(row=row, column=0, columnspan=6, pady=12)
        primary_button(btn_frame, "Weiter", self._on_next).pack(side=tk.LEFT, padx=5)
        secondary_button(btn_frame, "Abbrechen", self.top.destroy).pack(side=tk.LEFT, padx=5)

        self._recompute_counts()

    def _build_date_row(self, row, label_text, default_date):
        tk.Label(self.top, text=label_text, font=FONT, bg=BG, fg=TEXT).grid(
            row=row, column=0, padx=(10, 5), pady=4, sticky="w")

        day_var = tk.StringVar(value=str(default_date.day))
        max_day = calendar.monthrange(default_date.year, default_date.month)[1]
        day_cb = dark_combo(self.top, day_var,
                             [str(d) for d in range(1, max_day + 1)], width=3)
        day_cb.grid(row=row, column=1, padx=2, pady=4)

        tk.Label(self.top, text=".", font=FONT, bg=BG, fg=TEXT).grid(row=row, column=2)

        month_var = tk.StringVar(value=str(default_date.month))
        dark_combo(self.top, month_var,
                    [str(m) for m in range(1, 13)], width=3).grid(
            row=row, column=3, padx=2, pady=4)

        tk.Label(self.top, text=".", font=FONT, bg=BG, fg=TEXT).grid(row=row, column=4)

        year_var = tk.StringVar(value=str(default_date.year))
        years = [str(y) for y in range(2020, datetime.date.today().year + 2)]
        dark_combo(self.top, year_var, years, width=5).grid(
            row=row, column=5, padx=(2, 10), pady=4)

        def _on_change(*_):
            try:
                m = int(month_var.get())
                y = int(year_var.get())
                max_day = calendar.monthrange(y, m)[1]
            except (ValueError, KeyError):
                max_day = 31
            day_cb["values"] = [str(d) for d in range(1, max_day + 1)]
            try:
                if int(day_var.get()) > max_day:
                    day_var.set(str(max_day))
            except ValueError:
                pass
            self._recompute_counts()

        day_var.trace_add("write", _on_change)
        month_var.trace_add("write", _on_change)
        year_var.trace_add("write", _on_change)

        return day_var, month_var, year_var

    def _get_range(self):
        try:
            d_from = datetime.date(
                int(self.from_year.get()), int(self.from_month.get()),
                int(self.from_day.get()))
            d_to = datetime.date(
                int(self.to_year.get()), int(self.to_month.get()),
                int(self.to_day.get()))
        except ValueError:
            return None, None
        if d_from > d_to:
            return None, None
        return d_from, d_to

    def _compute_diff(self):
        d_from, d_to = self._get_range()
        if d_from is None:
            return None
        return diff_share_against_local(
            self.share_entries, self.storage,
            date_from=d_from, date_to=d_to,
        )

    def _recompute_counts(self):
        diff = self._compute_diff()
        if diff is None:
            self.counts_label.config(
                text="(Von-Datum muss vor Bis-Datum liegen)",
                fg=TEXT_MUTED,
            )
            return
        text = (
            f"• {len(diff['additions'])} neue Tage werden importiert\n"
            f"• {len(diff['conflicts'])} Tage haben Konflikte\n"
            f"• {len(diff['untouched'])} Tage sind identisch (übersprungen)\n"
            f"• {diff['out_of_range']} Tage außerhalb des Zeitraums (ignoriert)"
        )
        self.counts_label.config(text=text, fg=TEXT)

    def _on_next(self):
        diff = self._compute_diff()
        if diff is None:
            messagebox.showerror(
                "Ungültiger Zeitraum",
                "Das Von-Datum muss vor dem Bis-Datum liegen.",
                parent=self.top,
            )
            return
        if not diff["additions"] and not diff["conflicts"]:
            messagebox.showinfo(
                "Nichts zu importieren",
                "Im gewählten Zeitraum sind alle Einträge bereits identisch.",
                parent=self.top,
            )
            return

        mode = self.mode_var.get()
        if mode == "import":
            decisions = self._decisions_from(diff, take_import_for_conflicts=True)
        elif mode == "local":
            decisions = self._decisions_from(diff, take_import_for_conflicts=False)
        else:  # per_day
            if not diff["conflicts"]:
                decisions = self._decisions_from(diff, take_import_for_conflicts=True)
            else:
                decisions = _PerDayDialog(self.top, diff).show()
                if decisions is None:
                    return  # User abgebrochen → atomar nichts tun
        self._apply(decisions)

    @staticmethod
    def _decisions_from(diff, *, take_import_for_conflicts):
        decisions = [{"date": d, "entry": e} for d, e in diff["additions"]]
        if take_import_for_conflicts:
            decisions += [
                {"date": d, "entry": s} for d, _local, s in diff["conflicts"]
            ]
        return decisions

    def _apply(self, decisions):
        try:
            apply_import(self.storage, decisions)
        except Exception as e:
            logging.getLogger(__name__).exception("Import fehlgeschlagen")
            messagebox.showerror(
                "Import fehlgeschlagen",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=self.top,
            )
            return
        self.on_change()
        self.top.destroy()
        themed_showinfo(
            self.parent,
            "Importiert",
            f"{len(decisions)} Einträge wurden importiert.",
        )


class _PerDayDialog:
    """Modal mit Pro-Tag-Wahl (lokal vs. import). Liefert decisions oder None
    bei Abbruch."""

    def __init__(self, parent, diff):
        self.diff = diff
        self._result = None

        self.top = tk.Toplevel(parent)
        self.top.title("Pro Tag entscheiden")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.configure(bg=BG)
        apply_dark_titlebar(self.top)

        self._build()
        center_dialog_on_parent(self.top, parent)

    def show(self):
        self.top.wait_window()
        return self._result

    def _build(self):
        tk.Label(
            self.top, text="Wähle pro Tag, was übernommen werden soll:",
            font=FONT, bg=BG, fg=TEXT,
        ).pack(padx=10, pady=(10, 4), anchor="w")

        canvas = tk.Canvas(self.top, bg=BG, highlightthickness=0, height=320)
        scrollbar = tk.Scrollbar(self.top, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0))
        scrollbar.pack(side="right", fill="y")

        list_frame = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=list_frame, anchor="nw")

        self.choices = {}
        for i, (date, local, shared) in enumerate(self.diff["conflicts"]):
            var = tk.StringVar(value="L")
            self.choices[date] = var

            tk.Label(
                list_frame, text=date, font=FONT, bg=BG, fg=TEXT, width=12, anchor="w",
            ).grid(row=i, column=0, padx=4, pady=2, sticky="w")

            tk.Label(
                list_frame,
                text=f"Lokal: {local['start']}—{local['end']} (P{local.get('pause', 0)})",
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, anchor="w",
            ).grid(row=i, column=1, padx=4, pady=2, sticky="w")

            tk.Label(
                list_frame,
                text=f"Import: {shared['start']}—{shared['end']} (P{shared.get('pause', 0)})",
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, anchor="w",
            ).grid(row=i, column=2, padx=4, pady=2, sticky="w")

            tk.Radiobutton(
                list_frame, text="lokal", variable=var, value="L",
                font=FONT_SMALL, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT,
            ).grid(row=i, column=3, padx=2, pady=0)
            tk.Radiobutton(
                list_frame, text="import", variable=var, value="I",
                font=FONT_SMALL, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT,
            ).grid(row=i, column=4, padx=2, pady=0)

        list_frame.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

        btn_frame = tk.Frame(self.top, bg=BG)
        btn_frame.pack(pady=10)

        secondary_button(
            btn_frame, "Alle auf Import",
            lambda: [v.set("I") for v in self.choices.values()],
        ).pack(side=tk.LEFT, padx=4)
        secondary_button(
            btn_frame, "Alle auf Lokal",
            lambda: [v.set("L") for v in self.choices.values()],
        ).pack(side=tk.LEFT, padx=4)
        primary_button(btn_frame, "Anwenden", self._on_apply).pack(side=tk.LEFT, padx=4)
        secondary_button(btn_frame, "Abbrechen", self.top.destroy).pack(side=tk.LEFT, padx=4)

    def _on_apply(self):
        decisions = [{"date": d, "entry": e} for d, e in self.diff["additions"]]
        for date, _local, shared in self.diff["conflicts"]:
            if self.choices[date].get() == "I":
                decisions.append({"date": date, "entry": shared})
        self._result = decisions
        self.top.destroy()
