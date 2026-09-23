"""Tab „Bericht & Mail": Empfänger, Name, Mail-Vorlage.

Der Stundenlohn lag hier früher mit, gehört aber fachlich in den
Arbeitszeit-Tab: er beschreibt die Arbeit, nicht den Bericht, und speist
die Geldanzeige im Kalender-Footer (`grid_renderer`), nicht den Mailtext.
"""

import tkinter as tk

from src.dialogs.settings_dialog._shared import label, subheader
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import mail_updates
from src.theme import BG, TEXT_MUTED, dark_entry, dark_text


class MailTab:
    """Baut den Bericht-&-Mail-Tab; Tab-Schnittstelle für den
    `SaveCoordinator` (#132)."""

    def __init__(self, frame, settings):
        label(frame, "Empfänger:", row=0, pady=(10, 8))
        recipient_var = tk.StringVar(value=settings.get("recipient"))
        dark_entry(frame, recipient_var, width=25).grid(row=0, column=1, padx=10, pady=(10, 8))

        label(frame, "Dein Name:", row=1)
        name_var = tk.StringVar(value=settings.get("name"))
        dark_entry(frame, name_var, width=25).grid(row=1, column=1, padx=10, pady=8)

        subheader(frame, "Mail-Vorlage", row=2)

        label(frame, "Betreff:", row=3, pady=4)
        subject_var = tk.StringVar(value=settings.get("mail_subject"))
        dark_entry(frame, subject_var, width=35).grid(row=3, column=1, padx=10, pady=4)

        label(frame, "Anrede:", row=4, pady=4)
        greeting_var = tk.StringVar(value=settings.get("mail_greeting"))
        dark_entry(frame, greeting_var, width=35).grid(row=4, column=1, padx=10, pady=4)

        label(frame, "Inhalt:", row=5, pady=4, sticky="nw")
        content_text = dark_text(frame, 35, 3)
        content_text.grid(row=5, column=1, padx=10, pady=4)
        content_text.insert("1.0", settings.get("mail_content"))

        label(frame, "Gruß:", row=6, pady=4, sticky="nw")
        closing_text = dark_text(frame, 35, 2)
        closing_text.grid(row=6, column=1, padx=10, pady=4)
        closing_text.insert("1.0", settings.get("mail_closing"))

        tk.Label(
            frame, text="Platzhalter: {zeitraum}, {gesamt}", font=("Segoe UI", 8),
            bg=BG, fg=TEXT_MUTED,
        ).grid(row=7, column=0, columnspan=2, padx=10, pady=(0, 8))

        self.frame = frame
        self.recipient_var = recipient_var
        self.name_var = name_var
        self.subject_var = subject_var
        self.greeting_var = greeting_var
        self.content_text = content_text
        self.closing_text = closing_text

        self.title = "Bericht & Mail"
        self._settings = settings
        fields = FieldSet()
        fields.add("recipient", recipient_var)
        fields.add("name", name_var)
        fields.add("mail_subject", subject_var)
        fields.add("mail_greeting", greeting_var)
        # Nach dem Einfügen des Anfangstexts (oben) — add_text setzt das
        # Modified-Flag zurück, das das Einfügen gesetzt hat.
        fields.add_text("mail_content", content_text)
        fields.add_text("mail_closing", closing_text)
        self.fields = fields

    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return None

    def save(self):
        self._settings.apply_updates(mail_updates(self.values()))
        return SaveOutcome(saved=True)
