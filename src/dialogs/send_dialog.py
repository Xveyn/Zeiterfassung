import logging
import os
import tkinter as tk
import traceback
from tkinter import messagebox

from src import workweek
from src.dialogs.period_picker import build_period_picker
from src.dialogs.send_task import perform_send
from src.platform_open import open_folder
from src.report import default_pdf_filename, generate_report
from src.theme import (
    BG, FONT, TEXT,
    apply_combobox_style, attach_unfocus_on_click, center_dialog_on_parent,
    create_dialog, primary_button, secondary_button,
    set_button_text, set_primary_button_enabled,
    themed_showerror, themed_showinfo,
)
from src.time_utils import format_date, validate_period


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


def open_send_dialog(parent, storage, settings, base_path, runner):
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

    busy = {"running": False}

    def do_send():
        if busy["running"]:
            return
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
        # Nur-Werktage-Modus: Sa/So fliegen einmal am Snapshot raus — damit
        # sehen Mail-HTML (generate_report) und PDF (generate_pdf im Worker)
        # automatisch dieselben Daten, ohne dass report.py die Einstellung
        # kennen muss.
        entries = workweek.filter_for_report(storage.get_all(), settings)
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
                dialog, "Keine Einträge",
                f"Keine Einträge für {format_date(date_from)} – {format_date(date_to)} vorhanden.",
            )
            return

        label = f"{format_date(date_from)} – {format_date(date_to)}"
        subject = (
            settings.get("mail_subject")
            .replace("{zeitraum}", label)
            .replace("{gesamt}", f"{total}h")
        )
        pdf_filename = default_pdf_filename(date_from, date_to)

        busy["running"] = True
        set_primary_button_enabled(send_btn, False)
        set_button_text(send_btn, "Sende…")

        def fn():
            return perform_send(
                date_from=date_from, date_to=date_to, entries=entries,
                name=settings.get("name"), categories=categories,
                category_breakdown=category_breakdown,
                credentials_path=credentials_path, token_path=token_path,
                recipient=recipient, subject=subject, html=html,
                pdf_filename=pdf_filename,
                sync_enabled=settings.get("sync_enabled"),
                gcal_enabled=settings.get("gcal_enabled"),
                settings=settings,
            )

        def on_done(res):
            if res["ok"]:
                if dialog.winfo_exists():
                    dialog.destroy()
                themed_showinfo(
                    parent, "Gesendet",
                    f"Bericht für {label} wurde an {recipient} gesendet.",
                )
                return
            busy["running"] = False
            alive = dialog.winfo_exists()
            target = dialog if alive else parent
            if alive:
                set_primary_button_enabled(send_btn, True)
                set_button_text(send_btn, "Senden")
            kind = res["kind"]
            if kind == "filenotfound":
                themed_showerror(target, "Fehler", str(res["error"]))
            elif kind == "offline":
                themed_showerror(
                    target, "Keine Internetverbindung",
                    "Der Bericht konnte nicht gesendet werden, weil keine "
                    "Verbindung zum Internet besteht.\n\n"
                    "Bitte prüfe deine Internetverbindung und versuche es "
                    "dann erneut.",
                )
            else:
                messagebox.showerror(
                    "Senden fehlgeschlagen",
                    f"{type(res['error']).__name__}: {res['error']}\n\n{res['tb']}",
                    parent=target,
                )

        runner.run(fn, on_done)

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=1, column=0, pady=12)

    send_btn = primary_button(btn_frame, "Senden", do_send)
    send_btn.pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    center_dialog_on_parent(dialog, parent)
