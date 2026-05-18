import calendar
import datetime
import logging
import os
import tkinter as tk
import traceback
from tkinter import messagebox

from src.mail import get_gmail_service, send_email
from src.platform_open import open_folder
from src.report import generate_pdf, generate_report
from src.theme import (
    BG, FONT, TEXT,
    apply_combobox_style, apply_dark_titlebar, center_dialog_on_parent,
    dark_combo, primary_button, secondary_button, themed_showinfo,
)


def show_missing_credentials_dialog(parent, base_path):
    dialog = tk.Toplevel(parent)
    dialog.title("Keine Zugangsdaten")
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)

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

    center_dialog_on_parent(dialog, parent)


def _default_from_date(today):
    if today.month == 1:
        return today.replace(year=today.year - 1, month=12)
    from_month = today.month - 1
    max_day = calendar.monthrange(today.year, from_month)[1]
    return today.replace(month=from_month, day=min(today.day, max_day))


def open_send_dialog(parent, storage, settings, base_path):
    recipient = settings.get("recipient")
    if not recipient:
        messagebox.showwarning(
            "Kein Empfänger",
            "Bitte zuerst einen Empfänger in den Einstellungen angeben.",
            parent=parent,
        )
        return

    credentials_path = os.path.join(base_path, "credentials.json")
    token_path = os.path.join(base_path, "token.json")

    if not os.path.exists(credentials_path):
        show_missing_credentials_dialog(parent, base_path)
        return

    dialog = tk.Toplevel(parent)
    dialog.title("Zeitraum wählen")
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)

    apply_combobox_style(dialog)

    today = datetime.date.today()
    from_default = _default_from_date(today)
    month_values = [str(m) for m in range(1, 13)]
    year_values = [str(y) for y in range(2020, today.year + 2)]

    def update_day_values(day_cb, day_var, month_var, year_var):
        try:
            m = int(month_var.get())
            y = int(year_var.get())
            max_day = calendar.monthrange(y, m)[1]
        except (ValueError, KeyError):
            max_day = 31
        day_cb["values"] = [str(d) for d in range(1, max_day + 1)]
        if int(day_var.get()) > max_day:
            day_var.set(str(max_day))

    def build_date_row(row, label_text, default_date):
        tk.Label(dialog, text=label_text, font=FONT, bg=BG, fg=TEXT).grid(
            row=row, column=0, padx=(10, 5), pady=8, sticky="w")

        day_var = tk.StringVar(value=str(default_date.day))
        max_day = calendar.monthrange(default_date.year, default_date.month)[1]
        day_cb = dark_combo(dialog, day_var, [str(d) for d in range(1, max_day + 1)], width=3)
        day_cb.grid(row=row, column=1, padx=2, pady=8)

        tk.Label(dialog, text=".", font=FONT, bg=BG, fg=TEXT).grid(row=row, column=2)

        month_var = tk.StringVar(value=str(default_date.month))
        dark_combo(dialog, month_var, month_values, width=3).grid(row=row, column=3, padx=2, pady=8)

        tk.Label(dialog, text=".", font=FONT, bg=BG, fg=TEXT).grid(row=row, column=4)

        year_var = tk.StringVar(value=str(default_date.year))
        dark_combo(dialog, year_var, year_values, width=5).grid(row=row, column=5, padx=(2, 10), pady=8)

        month_var.trace_add("write", lambda *_: update_day_values(day_cb, day_var, month_var, year_var))
        year_var.trace_add("write", lambda *_: update_day_values(day_cb, day_var, month_var, year_var))

        return day_var, month_var, year_var

    from_day, from_month, from_year = build_date_row(0, "Von:", from_default)
    to_day, to_month, to_year = build_date_row(1, "Bis:", today)

    def do_send():
        try:
            date_from = datetime.date(int(from_year.get()), int(from_month.get()), int(from_day.get()))
            date_to = datetime.date(int(to_year.get()), int(to_month.get()), int(to_day.get()))
        except ValueError:
            messagebox.showerror("Ungültiges Datum", "Bitte ein gültiges Datum eingeben.", parent=dialog)
            return

        if date_from > date_to:
            messagebox.showerror(
                "Ungültiger Zeitraum",
                "Das Von-Datum muss vor dem Bis-Datum liegen.",
                parent=dialog,
            )
            return

        entries = storage.get_all()

        html, total = generate_report(
            date_from, date_to, entries,
            greeting=settings.get("mail_greeting"),
            content=settings.get("mail_content"),
            closing=settings.get("mail_closing"),
        )

        if html is None:
            messagebox.showinfo(
                "Keine Einträge",
                f"Keine Einträge für {date_from.strftime('%d.%m.%Y')} – {date_to.strftime('%d.%m.%Y')} vorhanden.",
                parent=dialog,
            )
            return

        label = f"{date_from.strftime('%d.%m.%Y')} – {date_to.strftime('%d.%m.%Y')}"

        try:
            pdf_bytes = generate_pdf(date_from, date_to, entries, name=settings.get("name"))
            service = get_gmail_service(
                credentials_path, token_path,
                sync_enabled=settings.get("sync_enabled"),
            )
            subject = (
                settings.get("mail_subject")
                .replace("{zeitraum}", label)
                .replace("{gesamt}", f"{total}h")
            )
            pdf_filename = f"Zeiterfassung_{date_from.strftime('%Y%m%d')}_{date_to.strftime('%Y%m%d')}.pdf"
            send_email(service, recipient, subject, html,
                       attachment_bytes=pdf_bytes,
                       attachment_filename=pdf_filename,
                       attachment_subtype="pdf")
            # Nach erfolgreichem Send ist der Token frisch — gute Gelegenheit,
            # die Absender-Adresse zu cachen.
            try:
                from src.mail import fetch_user_email
                email = fetch_user_email(token_path, sync_enabled=settings.get("sync_enabled"))
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
            messagebox.showerror("Fehler", str(e), parent=dialog)
        except Exception as e:
            logging.getLogger(__name__).exception("Senden fehlgeschlagen")
            messagebox.showerror(
                "Senden fehlgeschlagen",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=dialog,
            )

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=2, column=0, columnspan=6, pady=12)

    primary_button(btn_frame, "Senden", do_send).pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    center_dialog_on_parent(dialog, parent)
