"""Tab „Bericht & Mail": Empfänger, Name, Stundenlohn, Mail-Vorlage."""

import tkinter as tk

from src.dialogs.settings_dialog._shared import label, subheader
from src.theme import BG, FONT_SMALL, TEXT_MUTED, dark_entry, dark_text


class MailTab:
    """Baut den Bericht-&-Mail-Tab; exponiert die Variablen für save_settings."""

    def __init__(self, frame, settings):
        label(frame, "Empfänger:", row=0, pady=(10, 8))
        recipient_var = tk.StringVar(value=settings.get("recipient"))
        dark_entry(frame, recipient_var, width=25).grid(row=0, column=1, padx=10, pady=(10, 8))

        label(frame, "Dein Name:", row=1)
        name_var = tk.StringVar(value=settings.get("name"))
        dark_entry(frame, name_var, width=25).grid(row=1, column=1, padx=10, pady=8)

        label(frame, "Stundenlohn (€):", row=2)
        rate_var = tk.StringVar(value=str(settings.get("hourly_rate") or ""))
        dark_entry(frame, rate_var, width=10).grid(row=2, column=1, padx=10, pady=8, sticky="w")
        tk.Label(
            frame, text="(optional – nur für dich sichtbar)", font=FONT_SMALL,
            bg=BG, fg=TEXT_MUTED,
        ).grid(row=2, column=1, padx=(120, 10), pady=8, sticky="w")

        subheader(frame, "Mail-Vorlage", row=3)

        label(frame, "Betreff:", row=4, pady=4)
        subject_var = tk.StringVar(value=settings.get("mail_subject"))
        dark_entry(frame, subject_var, width=35).grid(row=4, column=1, padx=10, pady=4)

        label(frame, "Anrede:", row=5, pady=4)
        greeting_var = tk.StringVar(value=settings.get("mail_greeting"))
        dark_entry(frame, greeting_var, width=35).grid(row=5, column=1, padx=10, pady=4)

        label(frame, "Inhalt:", row=6, pady=4, sticky="nw")
        content_text = dark_text(frame, 35, 3)
        content_text.grid(row=6, column=1, padx=10, pady=4)
        content_text.insert("1.0", settings.get("mail_content"))

        label(frame, "Gruß:", row=7, pady=4, sticky="nw")
        closing_text = dark_text(frame, 35, 2)
        closing_text.grid(row=7, column=1, padx=10, pady=4)
        closing_text.insert("1.0", settings.get("mail_closing"))

        tk.Label(
            frame, text="Platzhalter: {zeitraum}, {gesamt}", font=("Segoe UI", 8),
            bg=BG, fg=TEXT_MUTED,
        ).grid(row=8, column=0, columnspan=2, padx=10, pady=(0, 8))

        self.frame = frame
        self.recipient_var = recipient_var
        self.name_var = name_var
        self.rate_var = rate_var
        self.subject_var = subject_var
        self.greeting_var = greeting_var
        self.content_text = content_text
        self.closing_text = closing_text
