"""Tab „Versand" (#132): alles, was einen Bericht verschickt — Name und
Mail-Vorlage (für jeden Mailweg), die Zeitraum-Vorbelegung des Sende-Dialogs
und je Kanal ein Abschnitt: Gmail (Empfänger), SMTP-Konten, Webhooks.

Bis PR 3 verteilt auf „Bericht & Mail", „SMTP", „Webhooks" und den App-Tab.
Der Gmail-Absender bleibt im Google-Tab: er hängt an der Google-Anmeldung.
"""

import tkinter as tk

from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import sending_updates
from src.dialogs.settings_dialog.tab_smtp import SmtpTab
from src.dialogs.settings_dialog.tab_webhooks import WebhooksTab
from src.theme import Form, dark_entry, dark_text


class SendingTab:
    """Baut den Versand-Tab; Tab-Schnittstelle für den `SaveCoordinator`.
    Die beiden Listen speichern selbst (eigener Klick, eigenes Speichern)
    und tragen nichts zu `values()` bei."""

    def __init__(self, frame, dialog, settings, webhook_store, smtp_store,
                 runner, parent):
        self.frame = frame
        self.title = "Versand"
        self._settings = settings

        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        # Geordnet wie der Sende-Dialog: erst, was für jeden Weg gilt, dann je
        # Kanal ein Abschnitt. Ein „Empfänger" ganz oben sah aus, als gälte
        # er für alle Wege — er gilt nur für Gmail; SMTP-Konten tragen ihren
        # eigenen, Webhooks haben eine URL.
        name_var = tk.StringVar(value=settings.get("name"))
        subject_var = tk.StringVar(value=settings.get("mail_subject"))
        greeting_var = tk.StringVar(value=settings.get("mail_greeting"))
        form.section("Bericht",
                     hint="Name und Vorlage gelten für Gmail und alle SMTP-Konten; "
                          "der Name steht auch im Bericht selbst.")
        form.row("Dein Name:", dark_entry(body, name_var, width=35))
        form.row("Betreff:", dark_entry(body, subject_var, width=35))
        form.row("Anrede:", dark_entry(body, greeting_var, width=35))
        content_text = dark_text(body, 35, 3)
        content_text.insert("1.0", settings.get("mail_content"))
        form.row("Inhalt:", content_text, align_top=True)
        closing_text = dark_text(body, 35, 2)
        closing_text.insert("1.0", settings.get("mail_closing"))
        form.row("Gruß:", closing_text, align_top=True)
        form.hint("Platzhalter in allen Vorlagen-Feldern: {zeitraum}, {gesamt}")

        from_last_var = tk.BooleanVar(
            value=settings.get("send_period_from_last_reminder"))
        anchor_var = tk.BooleanVar(value=settings.get("send_period_anchor_monthly"))
        form.section("Zeitraum im Sende-Dialog")
        form.check("Zeitraum ab der letzten Erinnerung vorbelegen", from_last_var)
        with form.depends_on(from_last_var):
            form.check("inkl. Monatstermine der Sende-Erinnerung", anchor_var)

        recipient_var = tk.StringVar(value=settings.get("recipient"))
        form.section("Gmail",
                     hint="Absender ist dein Google-Konto (Tab Google).")
        form.row("Empfänger:", dark_entry(body, recipient_var, width=35))

        self.smtp = SmtpTab(form, dialog, smtp_store, runner, parent)
        self.webhooks = WebhooksTab(form, dialog, webhook_store, runner, parent)

        # Für das Smoke-Skript (liest Felder direkt).
        self.content_text = content_text
        self.name_var = name_var

        fields = FieldSet()
        fields.add("recipient", recipient_var)
        fields.add("name", name_var)
        fields.add("mail_subject", subject_var)
        fields.add("mail_greeting", greeting_var)
        # Nach dem Einfügen des Anfangstexts — add_text setzt das
        # Modified-Flag zurück, das das Einfügen gesetzt hat.
        fields.add_text("mail_content", content_text)
        fields.add_text("mail_closing", closing_text)
        fields.add("send_period_from_last_reminder", from_last_var)
        fields.add("send_period_anchor_monthly", anchor_var)
        self.fields = fields

    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return None

    def save(self):
        self._settings.apply_updates(sending_updates(self.values()))
        return SaveOutcome(saved=True)
