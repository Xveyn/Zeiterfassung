"""Tab „Arbeitszeit": Standardzeiten, Pause, Werkstudenten-Limit, Kategorien."""

import datetime
import tkinter as tk

from src.dialogs.category_dialog import open_category_dialog
from src.dialogs.date_row import build_date_row
from src.dialogs.settings_dialog._shared import label, subheader
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    WSL_KEYS, validate_work, work_updates, wsl_snapshot,
)
from src.dialogs.vacation_dialog import open_vacation_dialog
from src.settings import WEEKDAY_KEYS
from src.theme import (
    BG, CELL_BG, FONT, FONT_SMALL, PAUSE_VALUES, TEXT, TEXT_MUTED,
    TIME_VALUES, dark_combo, dark_entry, secondary_button, themed_showwarning,
)
from src.time_utils import DAYS_DE
from src.weekly_limit import (
    format_limit_warnings, period_scan_needed, scan_period_for_warnings,
)


class WorkTab:
    """Baut den Arbeitszeit-Tab; Tab-Schnittstelle für den `SaveCoordinator`
    (#132)."""

    def __init__(self, frame, dialog, settings, vacation_store=None,
                 on_vacation_change=None, storage=None,
                 reservation_store=None, runner=None,
                 on_vacation_display_change=None):
        workweek_only_var = tk.BooleanVar(value=settings.get("workweek_only"))
        tk.Checkbutton(
            frame, text="Nur Werktage — Wochenende (Sa/So) komplett deaktivieren",
            variable=workweek_only_var, font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 0), sticky="w")

        label(frame, "Standardzeiten:", row=1, pady=(10, 4), sticky="nw")
        times_frame = tk.Frame(frame, bg=BG)
        times_frame.grid(row=1, column=1, padx=10, pady=(10, 4), sticky="w")

        tk.Label(times_frame, text="Start", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
            row=0, column=1, padx=2)
        tk.Label(times_frame, text="Ende", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
            row=0, column=2, padx=2)

        start_vars = {}
        end_vars = {}
        # Die StringVars entstehen für ALLE sieben Tage, auch für die
        # ausgeblendeten: `save` schreibt unverändert alle Wochentage
        # zurück, damit die Werte für Sa/So erhalten bleiben und sofort wieder
        # da sind, wenn "Nur Werktage" zurückgenommen wird.
        workweek_only = bool(settings.get("workweek_only"))
        row = 0
        for key, lbl in zip(WEEKDAY_KEYS, DAYS_DE, strict=False):
            start_vars[key] = tk.StringVar(value=settings.get(f"default_start_{key}"))
            end_vars[key] = tk.StringVar(value=settings.get(f"default_end_{key}"))
            if workweek_only and key in ("sat", "sun"):
                continue
            row += 1
            tk.Label(times_frame, text=lbl, font=FONT, bg=BG, fg=TEXT, width=3, anchor="w").grid(
                row=row, column=0, padx=(0, 8), pady=2)
            dark_combo(times_frame, start_vars[key], TIME_VALUES).grid(
                row=row, column=1, padx=2, pady=2)
            dark_combo(times_frame, end_vars[key], TIME_VALUES).grid(
                row=row, column=2, padx=2, pady=2)

        label(frame, "Standard-Pause (Min):", row=2)
        pause_var = tk.StringVar(value=str(settings.get("default_pause")))
        dark_combo(frame, pause_var, PAUSE_VALUES).grid(
            row=2, column=1, padx=10, pady=8, sticky="w")

        pause_warning_var = tk.BooleanVar(value=settings.get("pause_warning_enabled"))
        tk.Checkbutton(
            frame, text="Warnen, wenn die Pausenpflicht (§4 ArbZG) unterschritten wird",
            variable=pause_warning_var, font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).grid(row=3, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")

        # Der Stundenlohn stand früher im Bericht-&-Mail-Tab. Er beschreibt
        # aber die Arbeit, nicht den Bericht: gelesen wird er ausschließlich
        # vom Kalender-Footer (`grid_renderer`), der daraus den Geldbetrag zur
        # Stundensumme ableitet — im Mailtext taucht er nirgends auf.
        label(frame, "Stundenlohn (€):", row=4)
        rate_var = tk.StringVar(value=str(settings.get("hourly_rate") or ""))
        # Feld und Hinweis in EIN Frame, nebeneinander gepackt: der Abstand
        # ergibt sich so aus der tatsächlichen Feldbreite. Vorher lagen beide
        # in derselben Grid-Zelle, der Hinweis mit festem padx=120 — das Feld
        # (width=10 in Zeichen) wächst aber mit ui_scale mit, die 120 px
        # nicht; ab 1.5 lag der Hinweis auf dem Feld (#133).
        rate_row = tk.Frame(frame, bg=BG)
        rate_row.grid(row=4, column=1, padx=10, pady=8, sticky="w")
        dark_entry(rate_row, rate_var, width=10).pack(side=tk.LEFT)
        tk.Label(
            rate_row, text="(optional – nur für dich sichtbar)", font=FONT_SMALL,
            bg=BG, fg=TEXT_MUTED,
        ).pack(side=tk.LEFT, padx=(8, 0))

        subheader(frame, "Werkstudenten-Limit", row=5)
        wsl_frame = tk.Frame(frame, bg=BG)
        wsl_frame.grid(row=6, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="we")

        wsl_enabled_var = tk.BooleanVar(value=settings.get("werkstudent_limit_enabled"))
        tk.Checkbutton(
            wsl_frame, text="Wochenstunden-Limit aktivieren", variable=wsl_enabled_var,
            font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).pack(anchor="w")

        wsl_start_default = (
            datetime.date.fromisoformat(settings.get("werkstudent_limit_start"))
            if settings.get("werkstudent_limit_start") else datetime.date.today())
        wsl_end_default = (
            datetime.date.fromisoformat(settings.get("werkstudent_limit_end"))
            if settings.get("werkstudent_limit_end") else datetime.date.today())
        # Gemeinsames Datums-Zeilen-Widget (Audit M14); Werkstudenten-Limit
        # erlaubt Zeiträume etwas weiter in die Zukunft (year_to_offset=3).
        wsl_start_row = build_date_row(wsl_frame, "Zeitraum von:", wsl_start_default,
                                       year_to_offset=3)
        wsl_start_row.frame.pack(anchor="w", pady=(4, 0))
        wsl_start_vars = wsl_start_row.vars
        wsl_end_row = build_date_row(wsl_frame, "bis:", wsl_end_default, year_to_offset=3)
        wsl_end_row.frame.pack(anchor="w", pady=(4, 0))
        wsl_end_vars = wsl_end_row.vars

        wsl_hours_row = tk.Frame(wsl_frame, bg=BG)
        wsl_hours_row.pack(anchor="w", pady=(4, 0))
        tk.Label(wsl_hours_row, text="Limit (Stunden/Woche):", font=FONT, bg=BG, fg=TEXT).pack(
            side=tk.LEFT, padx=(0, 5))
        wsl_hours_var = tk.StringVar(value=str(settings.get("werkstudent_limit_max_hours")))
        dark_entry(wsl_hours_row, wsl_hours_var, width=6).pack(side=tk.LEFT)

        secondary_button(
            frame, "Kategorien verwalten",
            lambda: open_category_dialog(dialog, settings),
        ).grid(row=7, column=0, columnspan=2, padx=10, pady=(12, 8), sticky="w")

        if vacation_store is not None:
            secondary_button(
                frame, "Urlaub verwalten",
                # storage/reservation_store nur für die Kollisionsprüfung
                # beim Speichern: Urlaub und Arbeitszeit schließen sich am
                # selben Tag aus.
                # runner: der Kalender-Schalter im Dialog räumt beim
                # Abschalten über runner.purge_vacations auf (Audit H5).
                lambda: open_vacation_dialog(
                    dialog, vacation_store, settings, on_vacation_change,
                    storage, reservation_store, runner,
                    on_display_change=on_vacation_display_change),
            ).grid(row=8, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")

        self.frame = frame
        self.start_vars = start_vars
        self.end_vars = end_vars
        self.pause_var = pause_var
        self.pause_warning_var = pause_warning_var
        self.rate_var = rate_var
        self.wsl_enabled_var = wsl_enabled_var
        self.wsl_start_vars = wsl_start_vars
        self.wsl_end_vars = wsl_end_vars
        self.wsl_hours_var = wsl_hours_var
        self.workweek_only_var = workweek_only_var

        self.title = "Arbeitszeit"
        self._dialog = dialog
        self._settings = settings
        self._storage = storage

        fields = FieldSet()
        fields.add("workweek_only", workweek_only_var)
        for key in WEEKDAY_KEYS:
            fields.add(f"default_start_{key}", start_vars[key])
            fields.add(f"default_end_{key}", end_vars[key])
        fields.add("default_pause", pause_var)
        fields.add("pause_warning_enabled", pause_warning_var)
        fields.add("hourly_rate", rate_var)
        fields.add("werkstudent_limit_enabled", wsl_enabled_var)
        # Jahr → Monat → Tag ist Absicht: die Datumszeile klemmt den Tag bei
        # jedem Schreibzugriff auf die Monatslänge, und `FieldSet.load`
        # schreibt in dieser Reihenfolge zurück (Verwerfen nach 31.01. →
        # Februar ergäbe sonst den 28.01.).
        for which, (day, month, year) in (("start", wsl_start_vars),
                                          ("end", wsl_end_vars)):
            fields.add(f"werkstudent_limit_{which}.year", year)
            fields.add(f"werkstudent_limit_{which}.month", month)
            fields.add(f"werkstudent_limit_{which}.day", day)
        fields.add("werkstudent_limit_max_hours", wsl_hours_var)
        self.fields = fields

    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return validate_work(self.values())

    def save(self):
        settings = self._settings
        old = {key: settings.get(key) for key in WSL_KEYS}
        updates = work_updates(self.values(), old)
        settings.apply_updates(updates)
        # Geänderter Limit-Zeitraum: bereits erfasste Wochen darin prüfen —
        # sonst fiele eine Überschreitung erst beim nächsten Eintrag auf.
        if self._storage is not None and period_scan_needed(
                wsl_snapshot(old), wsl_snapshot(updates)):
            warnings = scan_period_for_warnings(settings, self._storage.get_all())
            if warnings:
                themed_showwarning(
                    self._dialog, "Wochenlimit überschritten",
                    "Im konfigurierten Zeitraum liegen bereits erfasste Wochen "
                    f"über dem Limit:\n\n{format_limit_warnings(warnings)}\n\n"
                    "Grobe Näherung, keine rechtliche Bewertung.",
                )
        return SaveOutcome(saved=True)
