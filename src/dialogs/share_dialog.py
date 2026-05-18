"""Modal-Dialog „Arbeitszeiten teilen“: baut Share-Doc, sendet per Gmail."""

import logging
import os
import tkinter as tk
import traceback
from tkinter import messagebox

from src.dialogs.send_dialog import show_missing_credentials_dialog
from src.mail import get_gmail_service, send_email
from src.share import build_share_doc, serialize_share_doc
from src.theme import (
    BG, FONT, TEXT,
    apply_dark_titlebar, center_dialog_on_parent,
    primary_button, secondary_button, themed_showinfo,
)


def open_share_dialog(parent, storage, settings, base_path):
    share_recipient = settings.get("share_recipient")
    if not share_recipient:
        messagebox.showwarning(
            "Kein Empfänger zum Teilen",
            "Bitte zuerst eine Empfänger-Adresse unter „Teilen mit:“ in den "
            "Einstellungen angeben.",
            parent=parent,
        )
        return

    credentials_path = os.path.join(base_path, "credentials.json")
    token_path = os.path.join(base_path, "token.json")

    if not os.path.exists(credentials_path):
        show_missing_credentials_dialog(parent, base_path)
        return

    entries = storage.get_all()
    if not entries:
        messagebox.showinfo(
            "Keine Einträge",
            "Es sind keine Einträge zum Teilen vorhanden.",
            parent=parent,
        )
        return

    dialog = tk.Toplevel(parent)
    dialog.title("Arbeitszeiten teilen")
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)

    tk.Label(
        dialog,
        text=(
            f"Alle {len(entries)} Einträge werden als JSON-Anhang an\n"
            f"{share_recipient}\n"
            "gesendet."
        ),
        font=FONT, bg=BG, fg=TEXT,
        wraplength=380, justify="left",
    ).grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 12))

    def do_send():
        sender_email = settings.get("sender_email") or ""
        display_name = settings.get("name") or sender_email or "anonym"
        try:
            doc = build_share_doc(storage, sender_email)
            payload = serialize_share_doc(doc)
            service = get_gmail_service(
                credentials_path, token_path,
                sync_enabled=settings.get("sync_enabled"),
            )
            subject = f"Arbeitszeiten geteilt von {display_name}"
            html = (
                "<html><head><meta charset=\"utf-8\"></head><body>"
                f"<p>Hallo,</p>"
                f"<p>im Anhang findest Du meine Arbeitszeiten "
                f"({len(entries)} Tage) als JSON-Datei.</p>"
                "<p>Du kannst sie in der Zeiterfassung-App über "
                "<em>Einstellungen → Arbeitszeiten importieren…</em> einlesen. "
                "Vor dem Import kannst Du einen Zeitraum auswählen und "
                "festlegen, was bei Konflikten passieren soll.</p>"
                f"<p>Viele Grüße<br/>{display_name}</p>"
                "</body></html>"
            )
            filename = f"zeiterfassung-share-{doc['exported_at'][:10].replace('-', '')}.json"
            send_email(
                service, share_recipient, subject, html,
                attachment_bytes=payload,
                attachment_filename=filename,
                attachment_subtype="json",
            )
            dialog.destroy()
            themed_showinfo(
                parent,
                "Geteilt",
                f"Arbeitszeiten wurden an {share_recipient} gesendet.",
            )
        except FileNotFoundError as e:
            messagebox.showerror("Fehler", str(e), parent=dialog)
        except Exception as e:
            logging.getLogger(__name__).exception("Teilen fehlgeschlagen")
            messagebox.showerror(
                "Teilen fehlgeschlagen",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=dialog,
            )

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=1, column=0, columnspan=2, pady=(0, 16))

    primary_button(btn_frame, "Senden", do_send).pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    center_dialog_on_parent(dialog, parent)
