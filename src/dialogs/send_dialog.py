import datetime
import logging
import os
import tkinter as tk
import traceback
from tkinter import messagebox

from src import workweek
from src.dialogs.period_picker import build_period_picker
from src.dialogs.send_task import format_result_summary, perform_send
from src.platform_open import open_folder
from src.report import (
    default_pdf_filename, filter_categories, filter_period, generate_report,
)
from src.theme import (
    BG, CELL_BG, FONT, TEXT, TEXT_MUTED,
    apply_combobox_style, attach_unfocus_on_click, center_dialog_on_parent,
    create_dialog, dark_combo, primary_button, secondary_button,
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


def resolve_send_period(settings, reservation_store, today):
    """Von/Bis-Vorbelegung für den Sende-Dialog, oder None.

    None heißt „bisheriger Default" (Vormonats-Pendant im period_picker).
    Ist die Option aus, gibt es keinen Store oder keinen zurückliegenden
    Anker, bleibt es dabei. Monatstermine zählen nur mit, wenn sie
    eingeschaltet sind — ein abgeschalteter Termin hat nie erinnert und darf
    den Zeitraum nicht verkürzen.
    """
    from src import send_reminder

    if not settings.get("send_period_from_last_reminder"):
        return None
    if reservation_store is None:
        return None
    marked = send_reminder.marked_reminder_dates(reservation_store.get_all_raw())
    monthly = []
    if settings.get("send_period_anchor_monthly") and settings.get("send_reminder_enabled"):
        monthly = send_reminder.monthly_anchor_dates(
            today,
            settings.get("send_reminder_day"),
            settings.get("send_reminder_time"),
            settings.get("send_reminder_weekend_shift"),
            settings.get("state"),
            bool(settings.get("send_reminder_shift_holidays")),
        )
    return send_reminder.default_send_period(today, marked, monthly)


def _show_single_failure(target, res):
    """Fehlermeldung, wenn genau ein Kanal beteiligt war.

    Behält die ausführlichen Formulierungen von vor dem Multi-Kanal-Umbau.
    `kind == "error"` bleibt außen vor: dafür kommt gleich danach der native
    Traceback-Dialog, ein themed Kasten davor wäre nur ein zweiter Klick.
    """
    kind = res.get("kind")
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
    elif kind != "error":
        themed_showerror(
            target, "Senden fehlgeschlagen", format_result_summary([res]))


FORMAT_LABELS = {(True, False): "JSON", (False, True): "PDF",
                 (True, True): "JSON + PDF"}
_FORMAT_BY_LABEL = {v: k for k, v in FORMAT_LABELS.items()}


def open_send_dialog(parent, storage, settings, base_path, runner,
                     reservation_store=None, webhook_store=None):
    credentials_path = os.path.join(base_path, "credentials.json")
    token_path = os.path.join(base_path, "token.json")

    hooks = webhook_store.enabled() if webhook_store else []
    recipient = settings.get("recipient")
    have_credentials = os.path.exists(credentials_path)
    mail_possible = bool(recipient) and have_credentials

    # Ohne jedes mögliche Ziel: wie bisher erklären und abbrechen.
    if not mail_possible and not hooks:
        if not recipient:
            themed_showinfo(
                parent, "Kein Empfänger",
                "Bitte zuerst einen Empfänger in den Einstellungen angeben.")
        else:
            show_missing_credentials_dialog(parent, base_path)
        return

    # Warum die Mail-Zeile ggf. tot ist — sonst steht dort die
    # Empfängeradresse und nichts erklärt, warum sie nicht anwählbar ist.
    if not recipient:
        mail_label = "E-Mail (kein Empfänger eingetragen)"
    elif not have_credentials:
        mail_label = f"E-Mail an {recipient} (Zugangsdaten fehlen)"
    else:
        mail_label = f"E-Mail an {recipient}"

    dialog = create_dialog(parent, "Zeitraum wählen")

    apply_combobox_style(dialog)
    attach_unfocus_on_click(dialog)

    period = resolve_send_period(settings, reservation_store, datetime.date.today())
    picker_frame, picker = build_period_picker(
        dialog, storage, settings,
        from_default=period[0] if period else None,
        to_default=period[1] if period else None,
    )
    picker_frame.grid(row=0, column=0, sticky="w")

    mail_var = tk.BooleanVar(value=mail_possible)
    hook_vars = []

    def _update_send_button():
        """Kein Ziel angehakt → Senden ist nicht anwählbar.

        Als `command` der Checkbuttons, nicht als trace_add: der Button wird
        erst weiter unten erzeugt, und `command` feuert nur auf echte
        Nutzer-Klicks — genau das, was hier gebraucht wird.
        """
        any_target = bool(mail_var.get()) or any(v.get() for _r, v, _f in hook_vars)
        set_primary_button_enabled(send_btn, any_target)

    if hooks:
        targets = tk.LabelFrame(dialog, text="Ziele", font=FONT, bg=BG, fg=TEXT_MUTED)
        targets.grid(row=1, column=0, padx=10, pady=(4, 0), sticky="we")

        mail_cb = tk.Checkbutton(
            targets, text=mail_label,
            variable=mail_var, font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
            command=_update_send_button)
        mail_cb.grid(row=0, column=0, sticky="w", padx=6, pady=2)
        if not mail_possible:
            mail_var.set(False)
            mail_cb.config(state="disabled")

        for i, record in enumerate(hooks, start=1):
            # Vorbelegt ABGEHAKT: Mail bleibt der Standardweg, ein Versand an
            # einen externen Endpunkt soll eine bewusste Entscheidung sein.
            var = tk.BooleanVar(value=False)
            tk.Checkbutton(
                targets, text=record.get("name", ""), variable=var, font=FONT,
                bg=BG, fg=TEXT, selectcolor=CELL_BG, activebackground=BG,
                activeforeground=TEXT, cursor="hand2",
                command=_update_send_button,
            ).grid(row=i, column=0, sticky="w", padx=6, pady=2)

            payload = record.get("payload") or {}
            current = (bool(payload.get("json")), bool(payload.get("pdf")))
            fmt_var = tk.StringVar(value=FORMAT_LABELS.get(current, "JSON"))
            dark_combo(targets, fmt_var, list(_FORMAT_BY_LABEL), width=12).grid(
                row=i, column=1, sticky="w", padx=(12, 6), pady=2)
            hook_vars.append((record, var, fmt_var))

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

        # (a) Ziele einsammeln — zuerst, alles Weitere hängt davon ab.
        selected_hooks = []
        for record, var, fmt_var in hook_vars:
            if not var.get():
                continue
            want_json, want_pdf = _FORMAT_BY_LABEL[fmt_var.get()]
            selected_hooks.append(
                {"record": record, "json": want_json, "pdf": want_pdf})
        send_mail = bool(mail_var.get())
        if not send_mail and not selected_hooks:
            return  # Button ist in diesem Zustand deaktiviert; defensiv.

        # (b) Leer-Prüfung kanalunabhängig. Bisher fiel sie als Nebenwirkung
        # davon an, dass generate_report None liefert — ohne Mail-Kanal gäbe
        # es dieses Signal nicht und ein Webhook bekäme ein leeres Dokument.
        ranged = filter_period(date_from, date_to, entries)
        if ranged is not None:
            ranged = filter_categories(ranged, categories)
        if not ranged:
            themed_showinfo(
                dialog, "Keine Einträge",
                f"Keine Einträge für {format_date(date_from)} – "
                f"{format_date(date_to)} vorhanden.")
            return

        # (c) label und pdf_filename IMMER — die Erfolgsmeldung braucht label
        # auch beim reinen Webhook-Versand.
        label = f"{format_date(date_from)} – {format_date(date_to)}"
        pdf_filename = default_pdf_filename(date_from, date_to)

        # (d) Mail-HTML, Betreff und `total` NUR im Mail-Fall. `total` kommt
        # ausschließlich aus generate_report; unbedingt zu berechnen ergäbe
        # beim reinen Webhook-Versand einen NameError im Tk-Callback.
        html = subject = None
        if send_mail:
            html, total = generate_report(
                date_from, date_to, entries,
                greeting=settings.get("mail_greeting"),
                content=settings.get("mail_content"),
                closing=settings.get("mail_closing"),
                categories=categories,
                category_breakdown=category_breakdown,
            )
            if html is None:
                # Sicherheitsnetz — (b) sollte das schon abgefangen haben.
                themed_showinfo(
                    dialog, "Keine Einträge",
                    f"Keine Einträge für {label} vorhanden.")
                return
            subject = (
                settings.get("mail_subject")
                .replace("{zeitraum}", label)
                .replace("{gesamt}", f"{total}h")
            )

        busy["running"] = True
        set_primary_button_enabled(send_btn, False)
        set_button_text(send_btn, "Sende…")

        def fn():
            return perform_send(
                date_from=date_from, date_to=date_to, entries=entries,
                name=settings.get("name"), categories=categories,
                category_breakdown=category_breakdown,
                send_mail=send_mail,
                mail={
                    "credentials_path": credentials_path,
                    "token_path": token_path,
                    "recipient": recipient, "subject": subject, "html": html,
                    "sync_enabled": settings.get("sync_enabled"),
                    "gcal_enabled": settings.get("gcal_enabled"),
                } if send_mail else None,
                webhooks=selected_hooks,
                pdf_filename=pdf_filename, settings=settings)

        def on_done(res):
            results = res["results"]
            if all(r["ok"] for r in results):
                if dialog.winfo_exists():
                    dialog.destroy()
                if len(results) == 1:
                    # Der 95-%-Fall (nur Mail): ganzer Satz statt Listen-
                    # Symbolik. Dieselbe Begründung wie bei den Fehlern —
                    # ein Feature darf den häufigsten Pfad nicht schlechter
                    # erklären als vorher.
                    themed_showinfo(
                        parent, "Gesendet",
                        f"Bericht für {label} wurde an "
                        f"{results[0]['name']} gesendet.")
                else:
                    themed_showinfo(
                        parent, "Gesendet",
                        f"Bericht für {label} gesendet:\n\n"
                        + format_result_summary(results))
                return

            busy["running"] = False
            alive = dialog.winfo_exists()
            target = dialog if alive else parent
            if alive:
                set_primary_button_enabled(send_btn, True)
                set_button_text(send_btn, "Senden")

            if len(results) == 1:
                # Einzelkanal: die bestehende, ausführliche Formulierung
                # behalten (Offline-Text mit Handlungsanweisung, bzw. der
                # vollständige Pfad zur fehlenden credentials.json).
                _show_single_failure(target, results[0])
            else:
                themed_showerror(
                    target, "Nicht alles konnte gesendet werden",
                    format_result_summary(results))

            # Unerwartete Fehler zusätzlich roh mit Traceback — themed Dialoge
            # bauen selbst Tk-Widgets auf und sind im gestörten Zustand die
            # unzuverlässigere Schicht (CLAUDE.md).
            for r in results:
                if r.get("kind") == "error" and r.get("tb"):
                    messagebox.showerror(
                        "Senden fehlgeschlagen",
                        f"{r['name']}: {type(r['error']).__name__}: "
                        f"{r['error']}\n\n{r['tb']}",
                        parent=target,
                    )

        runner.run(fn, on_done)

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=2 if hooks else 1, column=0, pady=12)

    send_btn = primary_button(btn_frame, "Senden", do_send)
    send_btn.pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)
    if hooks:
        _update_send_button()

    center_dialog_on_parent(dialog, parent)
