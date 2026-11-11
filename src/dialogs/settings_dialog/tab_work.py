"""Tab „Arbeitszeit": Arbeitswoche, Standardzeiten, Vergütung,
Werkstudenten-Limit, Kategorien und Urlaub."""

import datetime
import tkinter as tk

from src import default_times as dt
from src.dialogs.category_dialog import open_category_dialog
from src.dialogs.date_row import build_date_row
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    WSL_KEYS, country_code_for_label, validate_work, work_updates,
    wsl_snapshot,
)
from src.dialogs.vacation_dialog import open_vacation_dialog
from src.holidays_region import (
    COUNTRIES, country_choices, country_label, region_choices, region_label,
)
from src.i18n import t
from src.region import country_region
from src.settings import WEEKDAY_KEYS
from src.theme import (
    BG, FONT, PAUSE_VALUES, TEXT_MUTED, TIME_VALUES, Form, dark_combo,
    dark_entry, themed_askyesno, themed_showwarning,
)
from src.time_utils import short_day_names
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
        country, region = country_region(settings)
        country_var = tk.StringVar(value=country_label(country))
        region_var = tk.StringVar(value=region_label(country, region)
                                  or region_choices(country)[0][1])
        form.section(t("tab_arbeit.abschnitt_arbeitswoche"))
        form.check(t("tab_arbeit.nur_werktage"), workweek_only_var)
        # Stand bis PR 3 im App-Tab, mit einem Hinweis, der hierher verwies.
        # Neben „Nur Werktage" braucht es keinen: grau, solange der an ist.
        with form.depends_on(workweek_only_var, invert=True, indent=False):
            form.check(t("tab_arbeit.wochenende_anzeigen"), show_weekend_var)
        region_combo = dark_combo(
            body, region_var, [lbl for _, lbl in region_choices(country)], width=22)

        def _country_changed(_event=None):
            code = country_code_for_label(country_var.get())
            labels = [lbl for _, lbl in region_choices(code)]
            region_combo.configure(values=labels)
            region_var.set(labels[0] if labels else "")

        # Ein Land-Dropdown gibt es erst, wenn es mehr als ein Land gibt.
        if len(COUNTRIES) > 1:
            country_combo = dark_combo(
                body, country_var, [lbl for _, lbl in country_choices()], width=22)
            country_combo.bind("<<ComboboxSelected>>", _country_changed)
            form.row(t("tab_arbeit.land"), country_combo)
        form.row(t("tab_arbeit.bundesland"), region_combo)
        form.hint(t("tab_arbeit.region_hinweis"))

        # --- Standardzeiten ---
        form.section(t("tab_arbeit.abschnitt_standardzeiten"))
        start_vars = {}
        end_vars = {}
        day_rows = {}
        # Die StringVars entstehen für ALLE sieben Tage, auch für die
        # ausgeblendeten: `save` schreibt unverändert alle Wochentage zurück,
        # damit die Werte für Sa/So erhalten bleiben und sofort wieder da
        # sind, wenn "Nur Werktage" zurückgenommen wird.
        for key in WEEKDAY_KEYS:
            start_vars[key] = tk.StringVar(value=settings.get(f"default_start_{key}"))
            end_vars[key] = tk.StringVar(value=settings.get(f"default_end_{key}"))

        # Allgemein = ein Paar für alle Tage, Tageweise = das 7-Tage-Raster
        # (wie bei den Kategorien). Gespeichert werden in beiden Fällen die
        # 14 Tages-Keys, siehe src/default_times.py.
        mode = dt.resolve_mode(
            settings.get("default_times_mode"),
            {k: v.get() for k, v in start_vars.items()},
            {k: v.get() for k, v in end_vars.items()})
        mode_var = tk.StringVar(value=dt.mode_label(mode))
        all_start_var = tk.StringVar(value=start_vars["mon"].get())
        all_end_var = tk.StringVar(value=end_vars["mon"].get())

        form.row(t("tab_arbeit.modus"), dark_combo(
            body, mode_var, list(dt.mode_labels().values()), width=12))
        general_cell = tk.Frame(body, bg=BG)
        dark_combo(general_cell, all_start_var, TIME_VALUES).pack(side=tk.LEFT)
        tk.Label(general_cell, text="–", font=FONT, bg=BG, fg=TEXT_MUTED).pack(
            side=tk.LEFT, padx=6)
        dark_combo(general_cell, all_end_var, TIME_VALUES).pack(side=tk.LEFT)
        general_row = form.row(t("tab_arbeit.alle_tage"), general_cell)

        for key, lbl in zip(WEEKDAY_KEYS, short_day_names(), strict=True):
            cell = tk.Frame(body, bg=BG)
            dark_combo(cell, start_vars[key], TIME_VALUES).pack(side=tk.LEFT)
            tk.Label(cell, text="–", font=FONT, bg=BG, fg=TEXT_MUTED).pack(
                side=tk.LEFT, padx=6)
            dark_combo(cell, end_vars[key], TIME_VALUES).pack(side=tk.LEFT)
            day_rows[key] = form.row(f"{lbl}:", cell)

        def _apply_visibility(*_args):
            # Sofort statt erst beim nächsten Öffnen (#132) — auch beim
            # Verwerfen, das die Variablen über FieldSet.load zurücksetzt.
            per_day = dt.mode_code(mode_var.get()) == dt.MODE_PER_DAY
            general_row.show(not per_day)
            weekend = not workweek_only_var.get()
            for key, row in day_rows.items():
                row.show(per_day and (weekend or key not in ("sat", "sun")))

        def _on_mode_change(*_args):
            # Werte mitnehmen, damit ein Wechsel nichts Eingegebenes kostet.
            if dt.mode_code(mode_var.get()) == dt.MODE_PER_DAY:
                starts, ends = dt.days_for_per_day(
                    {k: v.get() for k, v in start_vars.items()},
                    {k: v.get() for k, v in end_vars.items()},
                    all_start_var.get(), all_end_var.get())
                for key in WEEKDAY_KEYS:
                    start_vars[key].set(starts[key])
                    end_vars[key].set(ends[key])
            else:
                start, end = dt.general_from_days(
                    {k: v.get() for k, v in start_vars.items()},
                    {k: v.get() for k, v in end_vars.items()})
                all_start_var.set(start)
                all_end_var.set(end)
            _apply_visibility()

        workweek_only_var.trace_add("write", _apply_visibility)
        mode_var.trace_add("write", _on_mode_change)
        _apply_visibility()

        pause_var = tk.StringVar(value=str(settings.get("default_pause")))
        form.row(t("tab_arbeit.standard_pause"), dark_combo(body, pause_var, PAUSE_VALUES))
        pause_warning_var = tk.BooleanVar(value=settings.get("pause_warning_enabled"))
        form.check(t("tab_arbeit.pausenwarnung"), pause_warning_var)

        # --- Vergütung ---
        # Der Stundenlohn stand früher im Bericht-&-Mail-Tab. Er beschreibt
        # aber die Arbeit, nicht den Bericht: gelesen wird er ausschließlich
        # vom Kalender-Footer (`grid_renderer`).
        rate_var = tk.StringVar(value=str(settings.get("hourly_rate") or ""))
        form.section(t("tab_arbeit.abschnitt_verguetung"))
        form.row(t("tab_arbeit.stundenlohn"), dark_entry(body, rate_var, width=10))
        form.hint(t("tab_arbeit.stundenlohn_hinweis"))

        # --- Werkstudenten-Limit ---
        wsl_enabled_var = tk.BooleanVar(value=settings.get("werkstudent_limit_enabled"))
        wsl_hours_var = tk.StringVar(value=str(settings.get("werkstudent_limit_max_hours")))
        wsl_start_default = (
            datetime.date.fromisoformat(settings.get("werkstudent_limit_start"))
            if settings.get("werkstudent_limit_start") else datetime.date.today())
        wsl_end_default = (
            datetime.date.fromisoformat(settings.get("werkstudent_limit_end"))
            if settings.get("werkstudent_limit_end") else datetime.date.today())
        form.section(t("tab_arbeit.abschnitt_limit"))
        form.check(t("tab_arbeit.limit_aktivieren"), wsl_enabled_var)
        with form.depends_on(wsl_enabled_var):
            # Gemeinsames Datums-Zeilen-Widget (Audit M14), ohne eigene
            # Beschriftung — die trägt die Formularspalte. Werkstudenten-
            # Limit erlaubt Zeiträume etwas weiter in die Zukunft.
            wsl_start_row = build_date_row(body, None, wsl_start_default,
                                           year_to_offset=3)
            form.row(t("tab_arbeit.zeitraum_von"), wsl_start_row.frame)
            wsl_end_row = build_date_row(body, None, wsl_end_default,
                                         year_to_offset=3)
            form.row(t("tab_arbeit.zeitraum_bis"), wsl_end_row.frame)
            form.row(t("tab_arbeit.limit_stunden"), dark_entry(body, wsl_hours_var, width=6))
        wsl_start_vars = wsl_start_row.vars
        wsl_end_vars = wsl_end_row.vars

        # --- Reservierungen ---
        reservations_var = tk.BooleanVar(value=settings.get("reservations_enabled"))
        form.section(t("tab_arbeit.abschnitt_reservierungen"))
        form.check(t("tab_arbeit.reservierungen_verwenden"), reservations_var)
        form.hint(t("tab_arbeit.reservierungen_hinweis"))

        # --- Verwalten ---
        form.section(t("tab_arbeit.abschnitt_verwalten"))
        specs = [(t("tab_arbeit.kategorien_verwalten"),
                  lambda: open_category_dialog(dialog, settings))]
        if vacation_store is not None:
            # storage/reservation_store nur für die Kollisionsprüfung beim
            # Speichern: Urlaub und Arbeitszeit schließen sich am selben Tag
            # aus. runner: der Kalender-Schalter im Dialog räumt beim
            # Abschalten über runner.purge_vacations auf (Audit H5).
            specs.append((t("tab_arbeit.urlaub_verwalten"), lambda: open_vacation_dialog(
                dialog, vacation_store, settings, on_vacation_change,
                storage, reservation_store, runner,
                on_display_change=on_vacation_display_change)))
        form.buttons(*specs)

        self.start_vars = start_vars
        self.end_vars = end_vars
        self.mode_var = mode_var
        self.all_start_var = all_start_var
        self.all_end_var = all_end_var
        self.pause_var = pause_var
        self.pause_warning_var = pause_warning_var
        self.reservations_var = reservations_var
        self.rate_var = rate_var
        self.wsl_enabled_var = wsl_enabled_var
        self.wsl_start_vars = wsl_start_vars
        self.wsl_end_vars = wsl_end_vars
        self.wsl_hours_var = wsl_hours_var
        self.workweek_only_var = workweek_only_var
        self.show_weekend_var = show_weekend_var
        self.country_var = country_var
        self.region_var = region_var

        self.title = t("tab_arbeit.titel")
        self._dialog = dialog
        self._settings = settings
        self._storage = storage

        fields = FieldSet()
        fields.add("workweek_only", workweek_only_var)
        fields.add("show_weekend", show_weekend_var)
        fields.add("country", country_var)
        fields.add("region", region_var)
        fields.add("default_times_mode", mode_var)
        fields.add("default_start_all", all_start_var)
        fields.add("default_end_all", all_end_var)
        for key in WEEKDAY_KEYS:
            fields.add(f"default_start_{key}", start_vars[key])
            fields.add(f"default_end_{key}", end_vars[key])
        fields.add("default_pause", pause_var)
        fields.add("pause_warning_enabled", pause_warning_var)
        fields.add("reservations_enabled", reservations_var)
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
        raw = self.values()
        if dt.mode_code(raw["default_times_mode"]) == dt.MODE_GENERAL and (
                dt.days_differ(
                    {k: raw[f"default_start_{k}"] for k in WEEKDAY_KEYS},
                    {k: raw[f"default_end_{k}"] for k in WEEKDAY_KEYS})):
            # Wie im Kategorien-Dialog: Tageswerte gehen nur nach Rückfrage.
            if not themed_askyesno(
                    self._dialog, t("tab_arbeit.tageszeiten_frage_titel"),
                    t("tab_arbeit.tageszeiten_frage")):
                return SaveOutcome(saved=False)
        old = {key: settings.get(key) for key in WSL_KEYS}
        updates = work_updates(self.values(), old)
        settings.apply_updates(updates)
        # Das Raster zeigt nach „Allgemein" den gespeicherten Stand; so
        # stimmt die Baseline des Coordinators mit den Settings überein.
        for key in WEEKDAY_KEYS:
            self.start_vars[key].set(updates[f"default_start_{key}"])
            self.end_vars[key].set(updates[f"default_end_{key}"])
        # Geänderter Limit-Zeitraum: bereits erfasste Wochen darin prüfen —
        # sonst fiele eine Überschreitung erst beim nächsten Eintrag auf.
        if self._storage is not None and period_scan_needed(
                wsl_snapshot(old), wsl_snapshot(updates)):
            warnings = scan_period_for_warnings(settings, self._storage.get_all())
            if warnings:
                themed_showwarning(
                    self._dialog, t("tab_arbeit.wochenlimit_titel"),
                    t("tab_arbeit.wochenlimit_text",
                      liste=format_limit_warnings(warnings)),
                )
        return SaveOutcome(saved=True)
