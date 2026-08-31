"""Anlegen und Bearbeiten eines SMTP-Kontos, inklusive Verbindungstest.

Reine Tk-Schicht: Validierung (`smtp_store.validate_record`), Verbindungstest
(`smtp.test_connection`) und die Passwort-Zustandslogik
(`keyring_store.persist_password`) liegen Tk-frei in den pure Modulen und sind
dort getestet.
"""

import tkinter as tk
from typing import Any

from src import keyring_store, smtp, smtp_store
from src.theme import (
    BG, CELL_BG, FONT, FONT_SMALL, TEXT, TEXT_MUTED,
    apply_combobox_style, attach_unfocus_on_click, center_dialog_on_parent,
    create_dialog, dark_combo, dark_entry, primary_button, secondary_button,
    set_primary_button_enabled, set_secondary_button_enabled,
    themed_showerror, themed_showinfo,
)

SECURITY_LABELS = [
    ("starttls", "STARTTLS (üblich, Port 587)"),
    ("ssl", "SSL/TLS (Port 465)"),
    ("none", "Keine Verschlüsselung"),
]

# Warum das hier steht und nicht in der Doku: ohne diesen Hinweis liest sich
# das „535 Authentication unsuccessful" von Microsoft wie ein Tippfehler, und
# der Nutzer sucht stundenlang am falschen Ende.
PROVIDER_HINT = (
    "Microsoft-Konten (Outlook.com, Microsoft 365) lassen sich hier nicht "
    "einrichten — Microsoft hat SMTP mit Passwort 2026 abgeschaltet.\n"
    "Für Gmail wird ein App-Passwort benötigt (nicht das Kontopasswort); "
    "es setzt eine aktive Zwei-Faktor-Anmeldung voraus."
)

STORAGE_HINT = (
    "Das Passwort wird im Schlüsselbund des Betriebssystems abgelegt. Steht "
    "keiner zur Verfügung, wird es lokal in smtp.json gespeichert."
)


def _mode_for_label(label):
    return next((m for m, lbl in SECURITY_LABELS if lbl == label), "starttls")


def _label_for_mode(mode):
    return next((lbl for m, lbl in SECURITY_LABELS if m == mode),
                SECURITY_LABELS[0][1])


def open_smtp_dialog(parent, store, runner, record: dict | None = None,
                     on_saved=None):
    is_new = record is None
    stored = record                      # der gespeicherte Stand, oder None
    record = dict(record or {
        "id": smtp_store.new_id(), "name": "", "enabled": True,
        "host": "", "port": 587, "security": "starttls", "username": "",
        "from_addr": "", "recipient": "", "password_location": "keyring",
    })

    dialog = create_dialog(
        parent, "SMTP-Konto hinzufügen" if is_new else "SMTP-Konto bearbeiten")
    apply_combobox_style(dialog)
    attach_unfocus_on_click(dialog)

    name_var = tk.StringVar(value=record.get("name", ""))
    host_var = tk.StringVar(value=record.get("host", ""))
    port_var = tk.StringVar(value=str(record.get("port", 587)))
    security_var = tk.StringVar(
        value=_label_for_mode(record.get("security", "starttls")))
    username_var = tk.StringVar(value=record.get("username", ""))
    # Bewusst LEER, auch beim Bearbeiten: ein gespeichertes Secret wird nie
    # zurück in ein Widget geholt. Leer heißt „unverändert".
    password_var = tk.StringVar(value="")
    from_var = tk.StringVar(value=record.get("from_addr", ""))
    recipient_var = tk.StringVar(value=record.get("recipient", ""))
    enabled_var = tk.BooleanVar(value=bool(record.get("enabled", True)))
    busy = {"testing": False, "saving": False}

    def _label(text, row, **kw):
        opts: dict[str, Any] = dict(padx=10, pady=6, sticky="w")
        opts.update(kw)
        tk.Label(dialog, text=text, font=FONT, bg=BG, fg=TEXT).grid(
            row=row, column=0, **opts)

    row = 0
    for text, var, _masked in (
        ("Name:", name_var, False),
        ("Server:", host_var, False),
        ("Port:", port_var, False),
    ):
        _label(text, row, pady=(14, 6) if row == 0 else 6)
        dark_entry(dialog, var, width=32).grid(
            row=row, column=1, padx=10,
            pady=(14, 6) if row == 0 else 6, sticky="w")
        row += 1

    _label("Verschlüsselung:", row)
    dark_combo(dialog, security_var,
               [lbl for _, lbl in SECURITY_LABELS], width=32).grid(
        row=row, column=1, padx=10, pady=6, sticky="w")
    row += 1

    for text, var, masked in (
        ("Benutzer:", username_var, False),
        ("Passwort:", password_var, True),
        ("Absender:", from_var, False),
        ("Empfänger:", recipient_var, False),
    ):
        _label(text, row)
        entry = dark_entry(dialog, var, width=32)
        if masked:
            entry.config(show="•")
        entry.grid(row=row, column=1, padx=10, pady=6, sticky="w")
        row += 1

    if not is_new:
        location = record.get("password_location")
        stored_text = ("Passwort liegt im Schlüsselbund des Betriebssystems."
                       if location == "keyring" else
                       "Kein Schlüsselbund verfügbar — das Passwort liegt "
                       "lokal in smtp.json.")
        tk.Label(dialog, text=f"{stored_text}  Leer lassen = unverändert.",
                 font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, justify="left",
                 wraplength=380).grid(row=row, column=0, columnspan=2,
                                      padx=10, pady=(0, 4), sticky="w")
        row += 1

    tk.Checkbutton(
        dialog, text="Aktiv", variable=enabled_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG, activebackground=BG,
        activeforeground=TEXT, cursor="hand2",
    ).grid(row=row, column=0, columnspan=2, padx=10, pady=(4, 2), sticky="w")
    row += 1

    # wraplength ist Pflicht, nicht Kosmetik: ohne sie wird das Label so breit
    # wie seine längste Zeile und zieht den ganzen Dialog mit. 380 ist der im
    # Projekt übliche Wert.
    for hint in (STORAGE_HINT, PROVIDER_HINT):
        tk.Label(dialog, text=hint, font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
                 justify="left", wraplength=380).grid(
            row=row, column=0, columnspan=2, padx=10, pady=(6, 2), sticky="w")
        row += 1

    def _collect():
        try:
            port = int(port_var.get().strip())
        except ValueError:
            # validate_record weist das mit einer Meldung ab; -1 ist nur der
            # Transportwert dorthin.
            port = -1
        return {
            "id": record["id"],
            "name": name_var.get().strip(),
            "enabled": bool(enabled_var.get()),
            "host": host_var.get().strip(),
            "port": port,
            "security": _mode_for_label(security_var.get()),
            "username": username_var.get().strip(),
            "from_addr": from_var.get().strip(),
            "recipient": recipient_var.get().strip(),
            "password_location": record.get("password_location", "keyring"),
        }

    def _validated():
        candidate = _collect()
        ok, msg = smtp_store.validate_record(candidate, store.get_all())
        if not ok:
            themed_showerror(dialog, "Eingabe unvollständig", msg)
            return None
        # Beim Neuanlegen ist ein Passwort Pflicht, sobald ein Benutzer
        # gesetzt ist — validate_record kann das nicht prüfen, dort steht das
        # Passwort gar nicht drin.
        if is_new and candidate["username"] and not password_var.get():
            themed_showerror(dialog, "Eingabe unvollständig",
                             "Bitte ein Passwort angeben.")
            return None
        return candidate

    def do_save():
        if busy["saving"]:
            return
        candidate = _validated()
        if candidate is None:
            return
        password = password_var.get()
        busy["saving"] = True
        set_primary_button_enabled(save_btn, False)

        # Über den Runner, NICHT direkt: store.save startet einen
        # icacls-Subprozess (timeout=15), und der Schlüsselbund kann auf Linux
        # blockieren. Im Tk-Callback fröre beides die Oberfläche ein.
        def fn():
            to_save = keyring_store.persist_password(candidate, password,
                                                     stored=stored)
            try:
                store.save(to_save)
            except (smtp_store.SmtpStoreReadOnly, OSError) as e:
                # Kompensation: das Secret steht schon im Schlüsselbund, der
                # Datensatz aber nirgends. Bei einem NEUEN Konto bliebe es
                # dort für immer unter einer id, die in keiner Datei mehr
                # steht — unauffindbar und unlöschbar. Beim Bearbeiten NICHT
                # kompensieren: dort existiert der Datensatz weiter, und das
                # frisch geschriebene Passwort ist das, was der Nutzer wollte.
                if is_new and password and \
                        to_save.get("password_location") == "keyring":
                    keyring_store.delete_secret(to_save["id"])
                return {"ok": False, "error": e}
            return {"ok": True,
                    "fell_back": bool(password)
                    and to_save.get("password_location") == "file"}

        def on_done(res):
            alive = dialog.winfo_exists()
            if res["ok"]:
                if alive:
                    dialog.destroy()
                if on_saved:
                    on_saved()
                # Nur wenn tatsächlich ein Passwort geschrieben wurde — sonst
                # feuerte der Hinweis bei jedem Speichern einer Namensänderung.
                if res["fell_back"]:
                    themed_showinfo(
                        parent, "Passwort lokal gespeichert",
                        "Auf diesem System steht kein Schlüsselbund zur "
                        "Verfügung. Das Passwort wurde deshalb lokal in "
                        "smtp.json gespeichert.")
                return
            if alive:
                busy["saving"] = False
                set_primary_button_enabled(save_btn, True)
            target = dialog if alive else parent
            themed_showerror(
                target, "Nicht gespeichert",
                f"Das SMTP-Konto konnte nicht gespeichert werden:\n\n{res['error']}")

        runner.run(fn, on_done)

    def do_test():
        # Eigenes Flag nötig: set_secondary_button_enabled ändert laut seinem
        # Docstring NUR die Optik, die command-Bindung bleibt aktiv.
        if busy["testing"]:
            return
        candidate = _validated()
        if candidate is None:
            return
        typed_password = password_var.get()
        busy["testing"] = True
        set_secondary_button_enabled(test_btn, False)

        # Getestet werden die AKTUELLEN Feldwerte, nicht der gespeicherte
        # Datensatz — sonst ließe sich eine Korrektur nicht prüfen, ohne sie
        # vorher zu speichern.
        def fn():
            password = typed_password
            if not password and stored is not None:
                password = keyring_store.get_secret(stored)
            try:
                smtp.test_connection(candidate, password)
            except Exception as e:
                return smtp.classify_smtp_error(e)
            return {"ok": True, "checked_login": bool(candidate["username"])}

        def on_done(res):
            busy["testing"] = False
            if not dialog.winfo_exists():
                return
            set_secondary_button_enabled(test_btn, True)
            if res.get("ok"):
                # Ohne Benutzer wurde keine einzige Zugangsdatei geprüft —
                # nur, dass der Server erreichbar ist und NOOP beantwortet.
                message = ("Der Server hat die Zugangsdaten akzeptiert."
                           if res["checked_login"] else
                           "Der Server ist erreichbar. Zugangsdaten wurden "
                           "nicht geprüft, weil kein Benutzer eingetragen ist.")
                themed_showinfo(dialog, "Verbindung erfolgreich",
                                f"{message} Es wurde keine E-Mail verschickt.")
                return
            from src.dialogs.send_task import format_result_summary
            themed_showerror(
                dialog, "Verbindung fehlgeschlagen",
                format_result_summary(
                    [{"name": candidate["name"], "ok": False,
                      "kind": res.get("kind"), "detail": res.get("detail")}]))

        runner.run(fn, on_done)

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=row, column=0, columnspan=2, pady=14)
    save_btn = primary_button(btn_frame, "Speichern", do_save)
    save_btn.pack(side=tk.LEFT, padx=5)
    test_btn = secondary_button(btn_frame, "Verbindung testen", do_test)
    test_btn.pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(
        side=tk.LEFT, padx=5)

    # Kein eigener <Escape>-Bind: create_dialog setzt ihn bereits.
    center_dialog_on_parent(dialog, parent)
