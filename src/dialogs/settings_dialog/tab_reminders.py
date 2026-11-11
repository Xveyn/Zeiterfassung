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
from src.i18n import t
from src.send_reminder import label_for_shift
from src.theme import TIME_VALUES, Form, dark_combo

_MINUTES = [str(m) for m in range(0, 121, 5)]


class RemindersTab:
    """Baut den Erinnerungen-Tab; Tab-Schnittstelle für den
    `SaveCoordinator`."""

    def __init__(self, frame, settings, mobile_service=None):
        self.frame = frame
        self.title = t("tab_erinnerungen.titel")
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
            form.section(t("tab_erinnerungen.abschnitt_reservierungen"))
            form.check(t("tab_erinnerungen.toast_anzeigen"), reminders_var)
            with form.depends_on(minutes_active):
                form.row(t("tab_erinnerungen.minuten_vor_ende"),
                         dark_combo(body, minutes_var, _MINUTES, width=4))
                form.hint(t("tab_erinnerungen.minuten_hinweis"))

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

        form.section(t("tab_erinnerungen.abschnitt_monatlich"))
        form.check(t("tab_erinnerungen.monatlich_aktiv"), send_var)
        with form.depends_on(send_var):
            form.row(t("tab_erinnerungen.tag_im_monat"), dark_combo(
                body, day_var, [str(d) for d in range(1, 32)], width=4))
            form.hint(t("tab_erinnerungen.tag_hinweis"))
            form.row(t("tab_erinnerungen.uhrzeit"), dark_combo(body, time_var, TIME_VALUES, width=6))
            form.row(t("tab_erinnerungen.wochenende_faellt"), dark_combo(
                body, shift_var,
                [label_for_shift(m) for m in ("none", "backward", "forward")],
                width=18))
            with form.depends_on(shift_active):
                form.check(t("tab_erinnerungen.auch_feiertage"), holidays_var)

        # --- Sende-Erinnerung an Reservierungstagen ---
        res_var = tk.BooleanVar(
            value=settings.get("send_reminder_reservations_enabled"))
        default_minutes_var = tk.StringVar(
            value=str(settings.get("send_reminder_default_minutes")))
        if show_reservations:
            form.section(t("tab_erinnerungen.abschnitt_reservierungstage"))
            form.check(t("tab_erinnerungen.reservierungstage_aktiv"), res_var)
            with form.depends_on(res_var):
                form.row(t("tab_erinnerungen.standard_minuten"), dark_combo(
                    body, default_minutes_var, _MINUTES, width=4))
                form.hint(t("tab_erinnerungen.reservierungstage_hinweis"))

        # --- Handy-Abschnitt (nur mit Handy-Instanz) ---
        if show_phone:
            form.section(t("tab_erinnerungen.abschnitt_handy"))
            form.check(t("tab_erinnerungen.handy_senden"), push_var)
            form.hint(phone_hint(len(visible_devices(mobile_service.list_devices()))))
            with form.depends_on(push_var):
                if show_reservations:
                    form.check(t("tab_erinnerungen.handy_reservierung"), push_res_var)
                form.check(t("tab_erinnerungen.handy_sende"), push_send_var)
                form.check(t("tab_erinnerungen.toast_unterdruecken"),
                           push_suppress_var)
                form.hint(t("tab_erinnerungen.toast_unterdruecken_hinweis"))

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
