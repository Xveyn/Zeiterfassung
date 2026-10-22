"""Tab „Erinnerungen" (#132): Reservierungs-Erinnerung, monatliche
Sende-Erinnerung und die Sende-Erinnerung an Reservierungstagen.

Stand bis PR 3 im App-Tab, dort ohne Überschriften — zwei fast gleich
benannte Minuten-Einstellungen nebeneinander. Jede hat jetzt ihren Abschnitt.
Die Reservierungs-Abschnitte erscheinen nur, wenn Reservierungen eingeschaltet
sind (Tab Arbeitszeit); die Werte bleiben erhalten.
"""

import tkinter as tk

from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    phone_hint, reminders_updates, shift_moves, validate_reminders, visible_devices,
)
from src.send_reminder import SHIFT_LABELS, label_for_shift
from src.theme import TIME_VALUES, Form, dark_combo

_MINUTES = [str(m) for m in range(0, 121, 5)]


class RemindersTab:
    """Baut den Erinnerungen-Tab; Tab-Schnittstelle für den
    `SaveCoordinator`."""

    def __init__(self, frame, settings, mobile_service=None):
        self.frame = frame
        self.title = "Erinnerungen"
        self._settings = settings

        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        show_reservations = bool(settings.get("reservations_enabled"))

        # --- Handy (Push über den Relay, #331): die Variablen vorab, weil die Minuten-Zeile der
        # Reservierungs-Erinnerung von Toast **oder** Handy abhängt ---
        push_var = tk.BooleanVar(value=settings.get("mobile_push_enabled"))
        push_res_var = tk.BooleanVar(value=settings.get("mobile_push_reservation"))
        push_send_var = tk.BooleanVar(value=settings.get("mobile_push_send"))
        push_suppress_var = tk.BooleanVar(value=settings.get("mobile_push_suppress_toast"))
        show_phone = mobile_service is not None

        # --- Reservierungs-Erinnerung (Toast, gerätelokal) ---
        reminders_var = tk.BooleanVar(value=settings.get("reminders_enabled"))
        minutes_var = tk.StringVar(value=str(settings.get("reminder_minutes_before")))
        # Abgeleitet, kein Formularfeld: die Minuten gelten für Toast und Handy.
        minutes_active = tk.BooleanVar(value=False)

        def refresh_minutes(*_):
            minutes_active.set(bool(reminders_var.get()
                                    or (show_phone and push_var.get() and push_res_var.get())))

        for var in (reminders_var, push_var, push_res_var):
            var.trace_add("write", refresh_minutes)
        refresh_minutes()
        if show_reservations:
            form.section("Reservierungen")
            form.check("Erinnerungen als Toast anzeigen", reminders_var)
            with form.depends_on(minutes_active):
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
        if show_reservations:
            form.section("An Reservierungstagen")
            form.check("Sende-Erinnerung am Ende einer markierten Reservierung",
                       res_var)
            with form.depends_on(res_var):
                form.row("Standard (Minuten vor Ende):", dark_combo(
                    body, default_minutes_var, _MINUTES, width=4))
                form.hint("Welche Tage erinnern, legst du im Tages-Dialog fest.")

        # --- Handy-Abschnitt (nur mit Handy-Instanz) ---
        if show_phone:
            form.section("Handy")
            form.check("Auch aufs Handy senden", push_var)
            form.hint(phone_hint(len(visible_devices(mobile_service.list_devices()))))
            with form.depends_on(push_var):
                if show_reservations:
                    form.check("Reservierungs-Erinnerung", push_res_var)
                form.check("Sende-Erinnerung", push_send_var)
                form.check("Toast am Desktop unterdrücken, wenn aufs Handy gesendet wird",
                           push_suppress_var)
                form.hint("Der Toast entfällt nur, wenn das Handy die Erinnerung bekommt; "
                          "sonst bleibt er.")

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
        fields.add("mobile_push_enabled", push_var)
        fields.add("mobile_push_reservation", push_res_var)
        fields.add("mobile_push_send", push_send_var)
        fields.add("mobile_push_suppress_toast", push_suppress_var)
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
