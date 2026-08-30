"""Modal-Dialog „Daten importieren": Datei-Pick, je Datentyp
(Arbeitszeiten/Reservierungen) ein Abschnitt mit Master-Schalter, Zeitraum-
Filter und Konflikt-Modi, optional Pro-Tag-Modal, atomarer Apply."""

import datetime
import logging
import tkinter as tk
from tkinter import ttk
import traceback
from tkinter import filedialog, messagebox

from src.dialogs.date_row import build_date_row
from src.share import (
    ShareValidationError,
    apply_import,
    apply_reservation_import,
    diff_reservations_against_local,
    diff_share_against_local,
    parse_share_doc,
)
from src.time_utils import format_date, format_iso_date
from src.theme import (
    BG, CELL_BG, FONT, FONT_SMALL, TEXT, TEXT_MUTED,
    apply_combobox_style, attach_unfocus_on_click, center_dialog_on_parent,
    create_dialog, primary_button, secondary_button,
    themed_showerror, themed_showinfo,
)


def open_import_dialog(parent, storage, settings, on_change, reservation_store=None):
    """Startet den Import-Flow. on_change wird bei erfolgreichem Apply
    aufgerufen. reservation_store=None → Reservierungen werden ignoriert."""
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
        themed_showerror(
            parent, "Datei nicht lesbar", f"{type(e).__name__}: {e}")
        return

    try:
        doc = parse_share_doc(raw)
    except ShareValidationError as e:
        themed_showerror(
            parent,
            "Datei ungültig",
            f"Die Datei kann nicht importiert werden:\n\n{e.reason}",
        )
        return

    entries = doc.get("entries") or {}
    reservations = doc.get("reservations") or {}
    if reservation_store is None:
        reservations = {}

    if not entries and not reservations:
        themed_showinfo(
            parent,
            "Leere Datei",
            "Die Datei enthält keine importierbaren Daten.",
        )
        return

    all_dates = sorted(
        datetime.date.fromisoformat(d)
        for d in (set(entries.keys()) | set(reservations.keys()))
    )
    file_min, file_max = all_dates[0], all_dates[-1]

    _ImportSummaryDialog(
        parent, storage, reservation_store, settings, doc,
        entries, reservations, file_min, file_max, on_change,
    ).show()


class _ImportSummaryDialog:
    def __init__(self, parent, storage, reservation_store, settings, doc,
                 entries, reservations, file_min, file_max, on_change):
        self.parent = parent
        self.storage = storage
        self.reservation_store = reservation_store
        self.settings = settings
        self.doc = doc
        self.file_min = file_min
        self.file_max = file_max
        self.on_change = on_change

        self.sections = []
        if entries:
            self.sections.append(self._make_section("entries", "Arbeitszeiten", entries, True))
        if reservations:
            self.sections.append(self._make_section("reservations", "Reservierungen", reservations, False))

        self.top = create_dialog(parent, "Daten importieren")
        apply_combobox_style(self.top)
        attach_unfocus_on_click(self.top)

        self._build()
        center_dialog_on_parent(self.top, parent)

    @staticmethod
    def _make_section(key, label, records, has_pause):
        return {
            "key": key,
            "label": label,
            "records": records,
            "has_pause": has_pause,
            "enabled": tk.BooleanVar(value=True),
            "mode": tk.StringVar(value="import"),
            "counts_label": None,
            "radios": [],
        }

    def show(self):
        self.top.wait_window()

    def _diff_for(self, section, d_from, d_to):
        if section["key"] == "entries":
            return diff_share_against_local(section["records"], self.storage, d_from, d_to)
        return diff_reservations_against_local(
            section["records"], self.reservation_store, d_from, d_to)

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
            text=f"Exportiert: {format_iso_date(self.doc.get('exported_at', ''))}",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, justify="left",
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(0, 10), sticky="w")
        row += 1

        tk.Label(
            self.top, text="Zeitraum filtern:", font=FONT, bg=BG, fg=TEXT,
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(4, 0), sticky="w")
        row += 1

        # Von/Bis über das gemeinsame Datums-Zeilen-Widget (Audit M14).
        from_row = build_date_row(self.top, "Von:", self.file_min,
                                  on_change=self._recompute_counts, label_width=4)
        from_row.frame.grid(row=row, column=0, columnspan=6, sticky="w", padx=10, pady=4)
        self.from_day, self.from_month, self.from_year = from_row.vars
        row += 1
        to_row = build_date_row(self.top, "Bis:", self.file_max,
                                on_change=self._recompute_counts, label_width=4)
        to_row.frame.grid(row=row, column=0, columnspan=6, sticky="w", padx=10, pady=4)
        self.to_day, self.to_month, self.to_year = to_row.vars
        row += 1

        tk.Label(
            self.top,
            text=f"Voller Bereich der Datei: "
                 f"{format_date(self.file_min)} bis "
                 f"{format_date(self.file_max)}",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(0, 8), sticky="w")
        row += 1

        for section in self.sections:
            tk.Checkbutton(
                self.top, text=f"{section['label']} importieren",
                variable=section["enabled"], command=self._on_toggle_section,
                font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT,
            ).grid(row=row, column=0, columnspan=6, padx=10, pady=(10, 0), sticky="w")
            row += 1

            counts = tk.Label(self.top, text="", font=FONT, bg=BG, fg=TEXT, justify="left")
            counts.grid(row=row, column=0, columnspan=6, padx=24, pady=(2, 2), sticky="w")
            section["counts_label"] = counts
            row += 1

            tk.Label(
                self.top, text="Konflikt-Behandlung:", font=FONT_SMALL,
                bg=BG, fg=TEXT_MUTED,
            ).grid(row=row, column=0, columnspan=6, padx=24, pady=(2, 0), sticky="w")
            row += 1

            section["radios"] = []
            for mode_value, mode_label in [
                ("import", "Alles vom Import übernehmen"),
                ("local", "Alles lokal behalten"),
                ("per_day", "Pro Tag entscheiden"),
            ]:
                rb = tk.Radiobutton(
                    self.top, text=mode_label, variable=section["mode"],
                    value=mode_value, font=FONT_SMALL, bg=BG, fg=TEXT,
                    selectcolor=CELL_BG, activebackground=BG, activeforeground=TEXT,
                )
                rb.grid(row=row, column=0, columnspan=6, padx=40, pady=0, sticky="w")
                section["radios"].append(rb)
                row += 1

        if (any(s["key"] == "reservations" for s in self.sections)
                and not self.settings.get("gcal_enabled")):
            tk.Label(
                self.top,
                text="Hinweis: Reservierungen werden sichtbar und mit dem "
                     "Kalender\nabgeglichen, sobald der Google-Kalender-Sync "
                     "in den Einstellungen aktiviert ist.",
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, justify="left",
            ).grid(row=row, column=0, columnspan=6, padx=10, pady=(8, 4), sticky="w")
            row += 1

        btn_frame = tk.Frame(self.top, bg=BG)
        btn_frame.grid(row=row, column=0, columnspan=6, pady=12)
        primary_button(btn_frame, "Weiter", self._on_next).pack(side=tk.LEFT, padx=5)
        secondary_button(btn_frame, "Abbrechen", self.top.destroy).pack(side=tk.LEFT, padx=5)

        self._on_toggle_section()  # ruft intern bereits _recompute_counts()

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

    def _on_toggle_section(self):
        for section in self.sections:
            state = "normal" if section["enabled"].get() else "disabled"
            for rb in section["radios"]:
                rb.config(state=state)
        self._recompute_counts()

    def _recompute_counts(self):
        d_from, d_to = self._get_range()
        for section in self.sections:
            label = section["counts_label"]
            if label is None:
                continue
            if not section["enabled"].get():
                label.config(text="(übersprungen)", fg=TEXT_MUTED)
                continue
            if d_from is None:
                label.config(text="(Von-Datum muss vor Bis-Datum liegen)", fg=TEXT_MUTED)
                continue
            diff = self._diff_for(section, d_from, d_to)
            label.config(
                text=(
                    f"• {len(diff['additions'])} neu  "
                    f"• {len(diff['conflicts'])} Konflikte  "
                    f"• {len(diff['untouched'])} identisch  "
                    f"• {diff['out_of_range']} außerhalb"
                ),
                fg=TEXT,
            )

    def _on_next(self):
        d_from, d_to = self._get_range()
        if d_from is None:
            themed_showerror(
                self.top,
                "Ungültiger Zeitraum",
                "Das Von-Datum muss vor dem Bis-Datum liegen.",
            )
            return

        planned = []  # list of (apply_fn, decisions)
        for section in self.sections:
            if not section["enabled"].get():
                continue
            diff = self._diff_for(section, d_from, d_to)
            if not diff["additions"] and not diff["conflicts"]:
                continue
            mode = section["mode"].get()
            if mode == "import":
                decisions = self._decisions_from(diff, take_import_for_conflicts=True)
            elif mode == "local":
                decisions = self._decisions_from(diff, take_import_for_conflicts=False)
            else:  # per_day
                if not diff["conflicts"]:
                    decisions = self._decisions_from(diff, take_import_for_conflicts=True)
                else:
                    decisions = _PerDayDialog(
                        self.top, diff, section["label"], section["has_pause"]).show()
                    if decisions is None:
                        return  # Abbruch → atomar nichts tun
            if not decisions:
                continue
            if section["key"] == "entries":
                planned.append((lambda dec: apply_import(self.storage, dec), decisions))
            else:
                planned.append((lambda dec: apply_reservation_import(self.reservation_store, dec), decisions))

        if not planned:
            themed_showinfo(
                self.top,
                "Nichts zu importieren",
                "Im gewählten Zeitraum gibt es nichts zu übernehmen.",
            )
            return

        self._apply(planned)

    @staticmethod
    def _decisions_from(diff, *, take_import_for_conflicts):
        decisions = [{"date": d, "entry": e} for d, e in diff["additions"]]
        if take_import_for_conflicts:
            decisions += [
                {"date": d, "entry": s} for d, _local, s in diff["conflicts"]
            ]
        return decisions

    def _apply(self, planned):
        total = 0
        try:
            for apply_fn, decisions in planned:
                apply_fn(decisions)
                total += len(decisions)
        except Exception as e:
            logging.getLogger(__name__).exception("Import fehlgeschlagen")
            messagebox.showerror(
                "Import fehlgeschlagen",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=self.top,
            )
            return
        # themed_showinfo läuft VOR on_change: on_change kann self.parent
        # zerstören (settings_dialog._after_import ruft dialog.destroy()), und
        # der Info-Dialog braucht den Parent noch lebendig — sonst TclError:
        # bad window path name.
        self.top.destroy()
        themed_showinfo(
            self.parent,
            "Importiert",
            f"{total} Datensätze wurden importiert.",
        )
        self.on_change()


class _PerDayDialog:
    """Modal mit Pro-Tag-Wahl (lokal vs. import). Liefert decisions oder None
    bei Abbruch. has_pause steuert die Anzeige der Pause (Reservierungen ohne)."""

    def __init__(self, parent, diff, type_label="Arbeitszeiten", has_pause=True):
        self.diff = diff
        self.has_pause = has_pause
        self._result = None

        self.top = create_dialog(parent, f"Pro Tag entscheiden — {type_label}",
                                 resizable=True)
        # Ungegatetes transient wie bisher (Verhaltensgleichheit; das
        # gegatete transient kommt zusätzlich über center_dialog_on_parent).
        self.top.transient(parent)

        self._build()
        center_dialog_on_parent(self.top, parent)

    def show(self):
        self.top.wait_window()
        return self._result

    def _fmt(self, rec):
        parts = []
        for s in rec.get("slots", []):
            kat = f" {s['kategorie']}" if s.get("kategorie") else ""
            if self.has_pause:
                parts.append(f"{s['start']}—{s['end']} (P{s.get('pause', 0)}){kat}")
            else:
                parts.append(f"{s['start']}—{s['end']}{kat}")
        return ", ".join(parts) if parts else "—"

    def _build(self):
        tk.Label(
            self.top, text="Wähle pro Tag, was übernommen werden soll:",
            font=FONT, bg=BG, fg=TEXT,
        ).pack(padx=10, pady=(10, 4), anchor="w")

        canvas = tk.Canvas(self.top, bg=BG, highlightthickness=0, height=320)
        # ttk.Scrollbar, NICHT tk.Scrollbar: die Legacy-Scrollbar kennt keine
        # ttk-Styles und bliebe im hellen Systemlook stehen. Der Dialog ruft
        # oben bereits apply_combobox_style, das Vertical.TScrollbar dunkel
        # konfiguriert.
        scrollbar = ttk.Scrollbar(self.top, orient="vertical",
                                  command=canvas.yview,
                                  style="Vertical.TScrollbar")
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
                list_frame, text=format_iso_date(date), font=FONT, bg=BG, fg=TEXT, width=12, anchor="w",
            ).grid(row=i, column=0, padx=4, pady=2, sticky="w")

            tk.Label(
                list_frame, text=f"Lokal: {self._fmt(local)}",
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, anchor="w",
            ).grid(row=i, column=1, padx=4, pady=2, sticky="w")

            tk.Label(
                list_frame, text=f"Import: {self._fmt(shared)}",
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
