"""Tab „Arbeitszeit": Arbeitswoche, Standardzeiten, Vergütung,
Werkstudenten-Limit, Kategorien und Urlaub."""

import datetime
import tkinter as tk

from src.dialogs.category_dialog import open_category_dialog
from src.dialogs.date_row import build_date_row
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    WSL_KEYS, validate_work, work_updates, wsl_snapshot,
)
from src.dialogs.vacation_dialog import open_vacation_dialog
from src.holidays_de import STATES
from src.settings import WEEKDAY_KEYS
from src.theme import (
    BG, FONT, PAUSE_VALUES, TEXT_MUTED, TIME_VALUES, Form, dark_combo,
    dark_entry, themed_showwarning,
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
        self.frame = frame
        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        # --- Arbeitswoche ---
        workweek_only_var = tk.BooleanVar(value=settings.get("workweek_only"))
        show_weekend_var = tk.BooleanVar(value=settings.get("show_weekend"))
        state_labels = [lbl for _, lbl in STATES]
        current_state = settings.get("state")
        state_var = tk.StringVar(value=next(
            (lbl for code, lbl in STATES if code == current_state), STATES[0][1]))
        form.section("Arbeitswoche")
        form.check("Nur Werktage — Wochenende (Sa/So) komplett ausblenden",
                   workweek_only_var)
        # Stand bis PR 3 im App-Tab, mit einem Hinweis, der hierher verwies.
        # Neben „Nur Werktage" braucht es keinen: grau, solange der an ist.
        with form.depends_on(workweek_only_var, invert=True, indent=False):
            form.check("Wochenende (Sa/So) im Kalender anzeigen", show_weekend_var)
        form.row("Bundesland:", dark_combo(body, state_var, state_labels, width=22))
        form.hint("Für Feiertage und Urlaub.")

        # --- Standardzeiten ---
        form.section("Standardzeiten")
        start_vars = {}
        end_vars = {}
        day_rows = {}
        # Die StringVars entstehen für ALLE sieben Tage, auch für die
        # ausgeblendeten: `save` schreibt unverändert alle Wochentage zurück,
        # damit die Werte für Sa/So erhalten bleiben und sofort wieder da
        # sind, wenn "Nur Werktage" zurückgenommen wird.
        for key, lbl in zip(WEEKDAY_KEYS, DAYS_DE, strict=True):
            start_vars[key] = tk.StringVar(value=settings.get(f"default_start_{key}"))
            end_vars[key] = tk.StringVar(value=settings.get(f"default_end_{key}"))
            cell = tk.Frame(body, bg=BG)
            dark_combo(cell, start_vars[key], TIME_VALUES).pack(side=tk.LEFT)
            tk.Label(cell, text="–", font=FONT, bg=BG, fg=TEXT_MUTED).pack(
                side=tk.LEFT, padx=6)
            dark_combo(cell, end_vars[key], TIME_VALUES).pack(side=tk.LEFT)
            day_rows[key] = form.row(f"{lbl}:", cell)

        def _apply_workweek(*_args):
            # Sofort statt erst beim nächsten Öffnen (#132) — auch beim
            # Verwerfen, das die Variable über FieldSet.load zurücksetzt.
            visible = not workweek_only_var.get()
            for key in ("sat", "sun"):
                day_rows[key].show(visible)

        workweek_only_var.trace_add("write", _apply_workweek)
        _apply_workweek()

        pause_var = tk.StringVar(value=str(settings.get("default_pause")))
        form.row("Standard-Pause (Min):", dark_combo(body, pause_var, PAUSE_VALUES))
        pause_warning_var = tk.BooleanVar(value=settings.get("pause_warning_enabled"))
        form.check("Warnen, wenn die Pausenpflicht (§4 ArbZG) unterschritten wird",
                   pause_warning_var)

        # --- Vergütung ---
        # Der Stundenlohn stand früher im Bericht-&-Mail-Tab. Er beschreibt
        # aber die Arbeit, nicht den Bericht: gelesen wird er ausschließlich
        # vom Kalender-Footer (`grid_renderer`).
        rate_var = tk.StringVar(value=str(settings.get("hourly_rate") or ""))
        form.section("Vergütung")
        form.row("Stundenlohn (€):", dark_entry(body, rate_var, width=10))
        form.hint("Optional – nur für dich sichtbar, als Betrag neben der "
                  "Stundensumme im Kalender.")

        # --- Werkstudenten-Limit ---
        wsl_enabled_var = tk.BooleanVar(value=settings.get("werkstudent_limit_enabled"))
        wsl_hours_var = tk.StringVar(value=str(settings.get("werkstudent_limit_max_hours")))
        wsl_start_default = (
            datetime.date.fromisoformat(settings.get("werkstudent_limit_start"))
            if settings.get("werkstudent_limit_start") else datetime.date.today())
        wsl_end_default = (
            datetime.date.fromisoformat(settings.get("werkstudent_limit_end"))
            if settings.get("werkstudent_limit_end") else datetime.date.today())
        form.section("Werkstudenten-Limit")
        form.check("Wochenstunden-Limit aktivieren", wsl_enabled_var)
        with form.depends_on(wsl_enabled_var):
            # Gemeinsames Datums-Zeilen-Widget (Audit M14), ohne eigene
            # Beschriftung — die trägt die Formularspalte. Werkstudenten-
            # Limit erlaubt Zeiträume etwas weiter in die Zukunft.
            wsl_start_row = build_date_row(body, None, wsl_start_default,
                                           year_to_offset=3)
            form.row("Zeitraum von:", wsl_start_row.frame)
            wsl_end_row = build_date_row(body, None, wsl_end_default,
                                         year_to_offset=3)
            form.row("bis:", wsl_end_row.frame)
            form.row("Limit (Stunden/Woche):", dark_entry(body, wsl_hours_var, width=6))
        wsl_start_vars = wsl_start_row.vars
        wsl_end_vars = wsl_end_row.vars

        # --- Verwalten ---
        form.section("Verwalten")
        specs = [("Kategorien…", lambda: open_category_dialog(dialog, settings))]
        if vacation_store is not None:
            # storage/reservation_store nur für die Kollisionsprüfung beim
            # Speichern: Urlaub und Arbeitszeit schließen sich am selben Tag
            # aus. runner: der Kalender-Schalter im Dialog räumt beim
            # Abschalten über runner.purge_vacations auf (Audit H5).
            specs.append(("Urlaub…", lambda: open_vacation_dialog(
                dialog, vacation_store, settings, on_vacation_change,
                storage, reservation_store, runner,
                on_display_change=on_vacation_display_change)))
        form.buttons(*specs)

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
        self.show_weekend_var = show_weekend_var
        self.state_var = state_var

        self.title = "Arbeitszeit"
        self._dialog = dialog
        self._settings = settings
        self._storage = storage

        fields = FieldSet()
        fields.add("workweek_only", workweek_only_var)
        fields.add("show_weekend", show_weekend_var)
        fields.add("state", state_var)
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
