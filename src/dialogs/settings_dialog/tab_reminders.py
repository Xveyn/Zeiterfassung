"""Tab „Erinnerungen" (#132): Reservierungs-Erinnerung, monatliche
Sende-Erinnerung und die Sende-Erinnerung an Reservierungstagen.

Stand bis PR 3 im App-Tab, dort ohne Überschriften — zwei fast gleich
benannte Minuten-Einstellungen nebeneinander. Jede hat jetzt ihren Abschnitt.
"""

import tkinter as tk

from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    reminders_updates, shift_moves, validate_reminders,
)
from src.send_reminder import SHIFT_LABELS, label_for_shift
from src.theme import TIME_VALUES, Form, dark_combo

_MINUTES = [str(m) for m in range(0, 121, 5)]


class RemindersTab:
    """Baut den Erinnerungen-Tab; Tab-Schnittstelle für den
    `SaveCoordinator`."""

    def __init__(self, frame, settings):
        self.frame = frame
        self.title = "Erinnerungen"
        self._settings = settings

        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        # --- Reservierungs-Erinnerung (Toast, gerätelokal) ---
        reminders_var = tk.BooleanVar(value=settings.get("reminders_enabled"))
        minutes_var = tk.StringVar(value=str(settings.get("reminder_minutes_before")))
        form.section("Reservierungen")
        form.check("Erinnerungen als Toast anzeigen", reminders_var)
        with form.depends_on(reminders_var):
            form.row("Minuten vor Ende:",
                     dark_combo(body, minutes_var, _MINUTES, width=4))
            form.hint("Nur für Reservierungen mit Kategorie — und nur, solange "
                      "für diese Kategorie an dem Tag keine Ist-Zeit erfasst ist.")

        # --- Monatliche Sende-Erinnerung ---
        send_var = tk.BooleanVar(value=settings.get("send_reminder_enabled"))
        day_var = tk.StringVar(value=str(settings.get("send_reminder_day")))
        time_var = tk.StringVar(value=settings.get("send_reminder_time"))
        shift_var = tk.StringVar(
            value=label_for_shift(settings.get("send_reminder_weekend_shift")))
        holidays_var = tk.BooleanVar(
            value=settings.get("send_reminder_shift_holidays"))
        # Abgeleitet, kein Formularfeld: „auch Feiertage" hat nur Wirkung,
        # wenn überhaupt verschoben wird. Form hält die Variable fest.
        shift_active = tk.BooleanVar(value=shift_moves(shift_var.get()))
        shift_var.trace_add(
            "write", lambda *_: shift_active.set(shift_moves(shift_var.get())))

        form.section("Monatliche Sende-Erinnerung")
        form.check("Erinnerung zum Verschicken der Arbeitszeiten", send_var)
        with form.depends_on(send_var):
            form.row("Tag im Monat:", dark_combo(
                body, day_var, [str(d) for d in range(1, 32)], width=4))
            form.hint("Bei kürzeren Monaten wird auf den letzten Tag verschoben.")
            form.row("Uhrzeit:", dark_combo(body, time_var, TIME_VALUES, width=6))
            form.row("Fällt er aufs Wochenende:", dark_combo(
                body, shift_var,
                [SHIFT_LABELS[m] for m in ("none", "backward", "forward")],
                width=18))
            with form.depends_on(shift_active):
                form.check("auch Feiertage", holidays_var)

        # --- Sende-Erinnerung an Reservierungstagen ---
        res_var = tk.BooleanVar(
            value=settings.get("send_reminder_reservations_enabled"))
        default_minutes_var = tk.StringVar(
            value=str(settings.get("send_reminder_default_minutes")))
        form.section("An Reservierungstagen")
        form.check("Sende-Erinnerung am Ende einer markierten Reservierung",
                   res_var)
        with form.depends_on(res_var):
            form.row("Standard (Minuten vor Ende):", dark_combo(
                body, default_minutes_var, _MINUTES, width=4))
            # Ohne Kalender-Abgleich zeigt die App gar keine Reservierungen
            # (App._reservations_active) — der Schalter bliebe sonst
            # wirkungslos, ohne dass man sieht warum.
            hint = "Welche Tage erinnern, legst du im Tages-Dialog fest."
            if not settings.get("gcal_enabled"):
                hint += " Braucht den Kalender-Abgleich (Tab Google)."
            form.hint(hint)

        fields = FieldSet()
        fields.add("reminders_enabled", reminders_var)
        fields.add("reminder_minutes_before", minutes_var)
        fields.add("send_reminder_enabled", send_var)
        fields.add("send_reminder_day", day_var)
        fields.add("send_reminder_time", time_var)
        fields.add("send_reminder_weekend_shift", shift_var)
        fields.add("send_reminder_shift_holidays", holidays_var)
        fields.add("send_reminder_reservations_enabled", res_var)
        fields.add("send_reminder_default_minutes", default_minutes_var)
        self.fields = fields

    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return validate_reminders(self.values())

    def save(self):
        self._settings.apply_updates(reminders_updates(self.values()))
        return SaveOutcome(saved=True)
