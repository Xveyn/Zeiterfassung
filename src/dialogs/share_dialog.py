"""Modal-Dialog „Teilen": baut Share-Doc für Arbeitszeiten und/oder
Reservierungen, sendet per Gmail."""

import os
import tkinter as tk
from tkinter import messagebox

from src.dialogs.send_dialog import show_missing_credentials_dialog
from src.dialogs.share_task import perform_share
from src.share import build_share_doc, serialize_share_doc
from src.theme import (
    BG, CELL_BG, FONT, TEXT,
    attach_unfocus_on_click, center_dialog_on_parent, create_dialog,
    dark_entry, primary_button, secondary_button,
    set_button_text, set_primary_button_enabled,
    themed_showerror, themed_showinfo,
)


def open_share_dialog(parent, storage, settings, base_path, runner, reservation_store=None):
    credentials_path = os.path.join(base_path, "credentials.json")
    token_path = os.path.join(base_path, "token.json")

    if not os.path.exists(credentials_path):
        show_missing_credentials_dialog(parent, base_path)
        return

    entries = storage.get_all()
    reservations = (
        reservation_store.get_all() if reservation_store is not None else {})

    if not entries and not reservations:
        themed_showinfo(
            parent,
            "Nichts zum Teilen",
            "Es sind weder Arbeitszeiten noch Reservierungen zum Teilen "
            "vorhanden.",
        )
        return

    dialog = create_dialog(parent, "Teilen")
    attach_unfocus_on_click(dialog)

    row = 0
    tk.Label(
        dialog, text="Was möchtest Du teilen?", font=FONT, bg=BG, fg=TEXT,
    ).grid(row=row, column=0, columnspan=2, padx=20, pady=(20, 6), sticky="w")
    row += 1

    include_entries_var = tk.BooleanVar(value=bool(entries))
    cb_entries = tk.Checkbutton(
        dialog, text=f"Arbeitszeiten ({len(entries)} Tage)",
        variable=include_entries_var,
        font=FONT, bg=BG, fg=TEXT, selectcolor=BG,
        activebackground=BG, activeforeground=TEXT,
    )
    if not entries:
        include_entries_var.set(False)
        cb_entries.config(state="disabled")
    cb_entries.grid(row=row, column=0, columnspan=2, padx=20, pady=0, sticky="w")
    row += 1

    include_res_var = tk.BooleanVar(value=bool(reservations))
    cb_res = tk.Checkbutton(
        dialog, text=f"Reservierungen ({len(reservations)} Tage)",
        variable=include_res_var,
        font=FONT, bg=BG, fg=TEXT, selectcolor=BG,
        activebackground=BG, activeforeground=TEXT,
    )
    if not reservations:
        include_res_var.set(False)
        cb_res.config(state="disabled")
    cb_res.grid(row=row, column=0, columnspan=2, padx=20, pady=(0, 12), sticky="w")
    row += 1

    # --- Kategorie-Auswahl (optional) ---
    # Kategorien aus Arbeitszeiten + Reservierungen + settings.categories.
    present_categories = sorted(
        {(s.get("kategorie") or "")
         for rec in list(entries.values()) + list(reservations.values())
         for s in rec["slots"]}
        | set(settings.get("categories") or []),
        key=lambda k: (k == "", k.lower()),
    )
    category_vars = {}
    if present_categories:
        tk.Label(
            dialog, text="Kategorien:", font=FONT, bg=BG, fg=TEXT,
        ).grid(row=row, column=0, padx=(20, 6), pady=(0, 4), sticky="nw")
        cat_frame = tk.Frame(dialog, bg=BG)
        cat_frame.grid(row=row, column=1, padx=(0, 20), pady=(0, 4), sticky="w")
        for kat in present_categories:
            var = tk.BooleanVar(value=True)
            category_vars[kat] = var
            tk.Checkbutton(
                cat_frame, text=(kat if kat else "(ohne Kategorie)"), variable=var,
                command=lambda: _refresh_send_btn(),
                font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT,
                highlightthickness=0, bd=0, anchor="w",
            ).pack(anchor="w")
        row += 1

    def _selected_categories():
        if not category_vars:
            return None
        selected = {kat for kat, var in category_vars.items() if var.get()}
        if len(selected) == len(category_vars):
            return None
        return selected

    tk.Label(
        dialog, text="Empfänger:", font=FONT, bg=BG, fg=TEXT,
    ).grid(row=row, column=0, padx=(20, 6), pady=(0, 4), sticky="w")

    recipient_var = tk.StringVar(value=settings.get("share_recipient") or "")
    recipient_entry = dark_entry(dialog, recipient_var, width=35)
    recipient_entry.grid(row=row, column=1, padx=(0, 20), pady=(0, 4), sticky="w")
    row += 1

    save_default_var = tk.BooleanVar(value=False)
    tk.Checkbutton(
        dialog,
        text="Als Standard-Empfänger speichern",
        variable=save_default_var,
        font=FONT, bg=BG, fg=TEXT, selectcolor=BG,
        activebackground=BG, activeforeground=TEXT,
    ).grid(row=row, column=0, columnspan=2, padx=20, pady=(0, 12), sticky="w")
    row += 1

    busy = {"running": False}

    def do_send():
        if busy["running"]:
            return
        want_entries = include_entries_var.get()
        want_res = include_res_var.get()
        if not want_entries and not want_res:
            # „Senden" ist in diesem Zustand deaktiviert (s.u.) — No-op.
            return
        if _selected_categories() == set():
            # leere Kategorie-Auswahl → „Senden" optisch deaktiviert — No-op.
            return
        share_recipient = recipient_var.get().strip()
        if not share_recipient:
            themed_showerror(
                dialog,
                "Empfänger fehlt",
                "Bitte eine E-Mail-Adresse angeben.",
            )
            return
        sender_email = settings.get("sender_email") or ""
        display_name = settings.get("name") or sender_email or "anonym"

        doc = build_share_doc(
            storage, sender_email,
            reservation_store=reservation_store,
            include_entries=want_entries,
            include_reservations=want_res,
            categories=_selected_categories(),
        )
        payload = serialize_share_doc(doc)
        parts = []
        if want_entries:
            parts.append("Arbeitszeiten")
        if want_res:
            parts.append("Reservierungen")
        what = " und ".join(parts)
        subject = f"{what} geteilt von {display_name}"
        html = (
            "<html><head><meta charset=\"utf-8\"></head><body>"
            "<p>Hallo,</p>"
            f"<p>im Anhang findest Du meine {what} als JSON-Datei.</p>"
            "<p>Du kannst die Datei in der Zeiterfassung-App über "
            "<em>Einstellungen → Daten importieren</em> einlesen. "
            "Vor dem Import kannst Du einen Zeitraum auswählen und je "
            "Datentyp festlegen, was bei Konflikten passieren soll.</p>"
            f"<p>Viele Grüße<br/>{display_name}</p>"
            "</body></html>"
        )
        filename = (
            "zeiterfassung-share-"
            f"{doc['exported_at'][:10].replace('-', '')}.json"
        )

        busy["running"] = True
        set_primary_button_enabled(send_btn, False)
        set_button_text(send_btn, "Teile…")

        def fn():
            return perform_share(
                payload=payload, filename=filename,
                credentials_path=credentials_path, token_path=token_path,
                recipient=share_recipient, subject=subject, html=html,
                sync_enabled=settings.get("sync_enabled"),
                gcal_enabled=settings.get("gcal_enabled"),
                save_default=save_default_var.get(), settings=settings,
            )

        def on_done(res):
            if res["ok"]:
                if dialog.winfo_exists():
                    dialog.destroy()
                themed_showinfo(
                    parent, "Geteilt",
                    f"{what} wurden an {share_recipient} gesendet.",
                )
                return
            busy["running"] = False
            alive = dialog.winfo_exists()
            target = dialog if alive else parent
            if alive:
                set_button_text(send_btn, "Senden")
                _refresh_send_btn()
            kind = res["kind"]
            if kind == "filenotfound":
                themed_showerror(target, "Fehler", str(res["error"]))
            elif kind == "offline":
                themed_showerror(
                    target, "Keine Internetverbindung",
                    "Die Daten konnten nicht gesendet werden, weil keine "
                    "Verbindung zum Internet besteht.\n\n"
                    "Bitte prüfe deine Internetverbindung und versuche es "
                    "dann erneut.",
                )
            else:
                messagebox.showerror(
                    "Teilen fehlgeschlagen",
                    f"{type(res['error']).__name__}: {res['error']}\n\n{res['tb']}",
                    parent=target,
                )

        runner.run(fn, on_done)

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=row, column=0, columnspan=2, pady=(0, 16))

    send_btn = primary_button(btn_frame, "Senden", do_send)
    send_btn.pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    def _refresh_send_btn(*_):
        # „Senden" nur klickbar, wenn mind. ein Datentyp UND (falls Kategorien
        # existieren) mind. eine Kategorie gewählt ist.
        has_datatype = include_entries_var.get() or include_res_var.get()
        has_category = _selected_categories() != set()
        set_primary_button_enabled(send_btn, has_datatype and has_category)

    cb_entries.config(command=_refresh_send_btn)
    cb_res.config(command=_refresh_send_btn)
    _refresh_send_btn()

    center_dialog_on_parent(dialog, parent)
