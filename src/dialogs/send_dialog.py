import logging
import os
import tkinter as tk
import traceback
from tkinter import messagebox

from src.dialogs.period_picker import build_period_picker
from src.mail import get_gmail_service, is_offline_error, send_email
from src.platform_open import open_folder
from src.report import default_pdf_filename, generate_pdf, generate_report
from src.theme import (
    BG, FONT, TEXT,
    apply_combobox_style, attach_unfocus_on_click, center_dialog_on_parent,
    create_dialog, primary_button, secondary_button,
    themed_showerror, themed_showinfo,
)
from src.time_utils import validate_period


def show_missing_credentials_dialog(parent, base_path):
    dialog = create_dialog(parent, "Keine Zugangsdaten", escape_closes=False)

    tk.Label(
        dialog,
        text=(
            "credentials.json nicht gefunden.\n\n"
            "Bitte erstelle ein Google Cloud Projekt mit Gmail API "
            "und lade die OAuth2 Client-ID als credentials.json in "
            "den Datenordner."
        ),
        font=FONT, bg=BG, fg=TEXT,
        wraplength=380, justify="left",
    ).grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 12))

    def open_and_close():
        try:
            open_folder(base_path)
        except Exception as e:
            logging.getLogger(__name__).exception("Datenordner konnte nicht geöffnet werden")
            messagebox.showerror(
                "Ordner konnte nicht geöffnet werden",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=dialog,
            )
            return
        dialog.destroy()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=1, column=0, columnspan=2, pady=(0, 16))

    primary_button(btn_frame, "Datenordner öffnen", open_and_close).pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "OK", dialog.destroy).pack(side=tk.LEFT, padx=5)

    dialog.bind("<Escape>", lambda _e: dialog.destroy())
    center_dialog_on_parent(dialog, parent)


def open_send_dialog(parent, storage, settings, base_path):
    recipient = settings.get("recipient")
    if not recipient:
        themed_showinfo(
            parent,
            "Kein Empfänger",
            "Bitte zuerst einen Empfänger in den Einstellungen angeben.",
        )
        return

    credentials_path = os.path.join(base_path, "credentials.json")
    token_path = os.path.join(base_path, "token.json")

    if not os.path.exists(credentials_path):
        show_missing_credentials_dialog(parent, base_path)
        return

    dialog = create_dialog(parent, "Zeitraum wählen")

    apply_combobox_style(dialog)
    attach_unfocus_on_click(dialog)

    picker_frame, picker = build_period_picker(dialog, storage, settings)
    picker_frame.grid(row=0, column=0, sticky="w")

    def do_send():
        date_from, date_to = picker.get_range()
        if date_from is None:
            themed_showerror(dialog, "Ungültiges Datum", "Bitte ein gültiges Datum eingeben.")
            return
        ok, msg = validate_period(date_from, date_to)
        if not ok:
            themed_showerror(dialog, "Ungültiger Zeitraum", msg)
            return

        # Frisch lesen statt den Dialog-Snapshot zu senden — der Storage kann
        # sich bei offenem Dialog geändert haben (Hintergrund-Drive-Sync).
        entries = storage.get_all()
        categories = picker.get_categories()
        category_breakdown = picker.get_category_breakdown()

        html, total = generate_report(
            date_from, date_to, entries,
            greeting=settings.get("mail_greeting"),
            content=settings.get("mail_content"),
            closing=settings.get("mail_closing"),
            categories=categories,
            category_breakdown=category_breakdown,
        )

        if html is None:
            themed_showinfo(
                dialog,
                "Keine Einträge",
                f"Keine Einträge für {date_from.strftime('%d.%m.%Y')} – {date_to.strftime('%d.%m.%Y')} vorhanden.",
            )
            return

        label = f"{date_from.strftime('%d.%m.%Y')} – {date_to.strftime('%d.%m.%Y')}"

        try:
            pdf_bytes = generate_pdf(date_from, date_to, entries, name=settings.get("name"),
                                     categories=categories,
                                     category_breakdown=category_breakdown)
            service = get_gmail_service(
                credentials_path, token_path,
                sync_enabled=settings.get("sync_enabled"),
                gcal_enabled=settings.get("gcal_enabled"),
            )
            subject = (
                settings.get("mail_subject")
                .replace("{zeitraum}", label)
                .replace("{gesamt}", f"{total}h")
            )
            pdf_filename = default_pdf_filename(date_from, date_to)
            send_email(service, recipient, subject, html,
                       attachment_bytes=pdf_bytes,
                       attachment_filename=pdf_filename,
                       attachment_subtype="pdf")
            # Nach erfolgreichem Send ist der Token frisch — gute Gelegenheit,
            # die Absender-Adresse zu cachen.
            try:
                from src.mail import fetch_user_email
                email = fetch_user_email(
                    token_path,
                    sync_enabled=settings.get("sync_enabled"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
                if email and email != settings.get("sender_email"):
                    settings.set("sender_email", email)
            except Exception:
                logging.getLogger(__name__).exception("sender_email fetch after send failed")
            dialog.destroy()
            themed_showinfo(
                parent,
                "Gesendet",
                f"Bericht für {label} wurde an {recipient} gesendet.",
            )
        except FileNotFoundError as e:
            themed_showerror(dialog, "Fehler", str(e))
        except Exception as e:
            # Trace landet immer im Logfile. Bei einem reinen Offline-Fehler
            # zeigen wir dem Nutzer aber eine verständliche Meldung statt des
            # kryptischen Tracebacks — das ist kein Bug, sondern fehlendes Netz.
            logging.getLogger(__name__).exception("Senden fehlgeschlagen")
            if is_offline_error(e):
                themed_showerror(
                    dialog,
                    "Keine Internetverbindung",
                    "Der Bericht konnte nicht gesendet werden, weil keine "
                    "Verbindung zum Internet besteht.\n\n"
                    "Bitte prüfe deine Internetverbindung und versuche es "
                    "dann erneut.",
                )
            else:
                messagebox.showerror(
                    "Senden fehlgeschlagen",
                    f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                    parent=dialog,
                )

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=1, column=0, pady=12)

    primary_button(btn_frame, "Senden", do_send).pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    center_dialog_on_parent(dialog, parent)
