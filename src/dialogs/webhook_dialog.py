"""Anlegen und Bearbeiten eines Webhooks, inklusive Testversand.

Reine Tk-Schicht: Validierung (webhook_store.validate_record) und Versand
(webhook.deliver) liegen Tk-frei in den pure Modulen und sind dort
getestet.
"""

import json
import tkinter as tk
from typing import Any

from src import webhook, webhook_store
from src.theme import (
    BG, CELL_BG, FONT, FONT_SMALL, TEXT, TEXT_MUTED,
    apply_combobox_style, attach_unfocus_on_click, center_dialog_on_parent,
    create_dialog, dark_combo, dark_entry, primary_button, secondary_button,
    set_primary_button_enabled, set_secondary_button_enabled,
    themed_showerror, themed_showinfo,
)

AUTH_LABELS = [
    ("none", "Keine"),
    ("header", "Token im Header (Bearer / API-Key)"),
    ("hmac", "HMAC-Signatur (SHA-256)"),
]

# Je Verfahren ein eigener Default. Ein gemeinsames, modusunabhängiges Feld
# schickte eine HMAC-Signatur sonst als „Authorization: sha256=…" raus — der
# Fallback in auth_headers greift nur bei LEEREM Feld, und der Nutzer hat es
# ja nicht geleert.
DEFAULT_HEADERS = {"header": "Authorization", "hmac": "X-Hub-Signature-256"}


def _mode_for_label(label):
    return next((m for m, lbl in AUTH_LABELS if lbl == label), "none")


def _label_for_mode(mode):
    return next((lbl for m, lbl in AUTH_LABELS if m == mode), AUTH_LABELS[0][1])


def open_webhook_dialog(parent, store, runner, record: dict | None = None, on_saved=None):
    is_new = record is None
    record = dict(record or {
        "id": webhook_store.new_id(), "name": "", "url": "", "enabled": True,
        "payload": {"json": True, "pdf": False}, "auth": {"mode": "none"},
    })
    auth = dict(record.get("auth") or {"mode": "none"})

    dialog = create_dialog(
        parent, "Webhook hinzufügen" if is_new else "Webhook bearbeiten")
    apply_combobox_style(dialog)
    attach_unfocus_on_click(dialog)

    name_var = tk.StringVar(value=record.get("name", ""))
    url_var = tk.StringVar(value=record.get("url", ""))
    enabled_var = tk.BooleanVar(value=bool(record.get("enabled", True)))
    json_var = tk.BooleanVar(value=bool(record.get("payload", {}).get("json")))
    pdf_var = tk.BooleanVar(value=bool(record.get("payload", {}).get("pdf")))
    mode_var = tk.StringVar(value=_label_for_mode(auth.get("mode", "none")))
    header_var = tk.StringVar(
        value=auth.get("header") or DEFAULT_HEADERS.get(auth.get("mode") or "", ""))
    # Bewusst LEER statt "Bearer ": ein vorbelegter Präfix bestünde die
    # Validierung ("Bearer ".strip() ist nicht leer) und ginge mit leerem
    # Token raus — der Endpunkt antwortet 401 und der Nutzer sucht woanders.
    value_var = tk.StringVar(value=auth.get("value", ""))
    prefix_var = tk.StringVar(value=auth.get("prefix", "sha256="))
    secret_var = tk.StringVar(value=auth.get("secret", ""))
    busy = {"testing": False, "saving": False}

    def _label(text, row, **kw):
        opts: dict[str, Any] = dict(padx=10, pady=6, sticky="w")
        opts.update(kw)
        tk.Label(dialog, text=text, font=FONT, bg=BG, fg=TEXT).grid(
            row=row, column=0, **opts)

    _label("Name:", 0, pady=(14, 6))
    dark_entry(dialog, name_var, width=32).grid(
        row=0, column=1, padx=10, pady=(14, 6), sticky="w")

    _label("URL:", 1)
    dark_entry(dialog, url_var, width=32).grid(
        row=1, column=1, padx=10, pady=6, sticky="w")

    opts_frame = tk.Frame(dialog, bg=BG)
    opts_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=(2, 4), sticky="w")

    def _check(parent_frame, text, var):
        cb = tk.Checkbutton(
            parent_frame, text=text, variable=var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2")
        cb.pack(anchor="w")
        return cb

    _check(opts_frame, "Aktiv", enabled_var)
    _check(opts_frame, "Arbeitszeiten als JSON senden", json_var)
    _check(opts_frame, "Bericht als PDF senden", pdf_var)

    _label("Authentifizierung:", 3)
    dark_combo(dialog, mode_var, [lbl for _, lbl in AUTH_LABELS], width=32).grid(
        row=3, column=1, padx=10, pady=6, sticky="w")

    auth_frame = tk.Frame(dialog, bg=BG)
    auth_frame.grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="we")

    def _rebuild_auth_fields(*_a):
        for child in auth_frame.winfo_children():
            child.destroy()
        mode = _mode_for_label(mode_var.get())
        # Header-Default beim Moduswechsel nachziehen — aber nur, solange dort
        # nichts Eigenes steht (leer oder der Default des anderen Verfahrens).
        if mode in DEFAULT_HEADERS and \
                header_var.get().strip() in ("", *DEFAULT_HEADERS.values()):
            header_var.set(DEFAULT_HEADERS[mode])
        if mode == "none":
            tk.Label(auth_frame,
                     text="Der Endpunkt wird ohne zusätzlichen Header aufgerufen.",
                     font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
            return
        rows = [("Header:", header_var, False)]
        if mode == "header":
            rows.append(("Wert:", value_var, True))
        else:
            rows.append(("Präfix:", prefix_var, False))
            rows.append(("Secret:", secret_var, True))
        for i, (text, var, masked) in enumerate(rows):
            tk.Label(auth_frame, text=text, font=FONT, bg=BG, fg=TEXT).grid(
                row=i, column=0, sticky="w", pady=4)
            entry = dark_entry(auth_frame, var, width=30)
            if masked:
                entry.config(show="•")
            entry.grid(row=i, column=1, padx=(8, 0), pady=4, sticky="w")
        if mode == "header":
            tk.Label(auth_frame,
                     text="z. B.  Bearer dein-token  —  Präfix mit eintragen",
                     font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
                row=len(rows), column=1, sticky="w", padx=(8, 0))

    mode_var.trace_add("write", _rebuild_auth_fields)
    _rebuild_auth_fields()

    def _collect():
        mode = _mode_for_label(mode_var.get())
        new_auth = {"mode": mode}
        if mode == "header":
            new_auth.update(header=header_var.get().strip(), value=value_var.get())
        elif mode == "hmac":
            new_auth.update(header=header_var.get().strip(),
                            prefix=prefix_var.get(), secret=secret_var.get())
        return {
            "id": record["id"],
            "name": name_var.get().strip(),
            "url": url_var.get().strip(),
            "enabled": bool(enabled_var.get()),
            "payload": {"json": bool(json_var.get()), "pdf": bool(pdf_var.get())},
            "auth": new_auth,
        }

    def _validated():
        candidate = _collect()
        ok, msg = webhook_store.validate_record(candidate, store.get_all())
        if not ok:
            themed_showerror(dialog, "Eingabe unvollständig", msg)
            return None
        return candidate

    def do_save():
        if busy["saving"]:
            return
        candidate = _validated()
        if candidate is None:
            return
        busy["saving"] = True
        set_primary_button_enabled(save_btn, False)

        # Über den Runner, NICHT direkt: store.save startet einen
        # icacls-Subprozess (timeout=15). Im Tk-Callback blockierte ein
        # hängendes Netzlaufwerk damit bis zu 15 s lang die Oberfläche
        # (src/CLAUDE.md, secure_file-Absatz).
        def fn():
            try:
                store.save(candidate)
            except (webhook_store.WebhookStoreReadOnly, OSError) as e:
                return {"ok": False, "error": e}
            return {"ok": True}

        def on_done(res):
            if not dialog.winfo_exists():
                return
            if res["ok"]:
                dialog.destroy()
                if on_saved:
                    on_saved()
                return
            busy["saving"] = False
            set_primary_button_enabled(save_btn, True)
            themed_showerror(
                dialog, "Nicht gespeichert",
                f"Der Webhook konnte nicht gespeichert werden:\n\n{res['error']}")

        runner.run(fn, on_done)

    def do_test():
        # Eigenes Flag nötig: set_secondary_button_enabled ändert laut seinem
        # Docstring NUR die Optik, die command-Bindung bleibt aktiv. Ohne das
        # löst ein Doppelklick zwei echte POSTs beim Empfänger aus.
        if busy["testing"]:
            return
        candidate = _validated()
        if candidate is None:
            return
        busy["testing"] = True
        set_secondary_button_enabled(test_btn, False)

        sample = {
            "schema_version": webhook.PAYLOAD_SCHEMA_VERSION,
            "kind": "zeiterfassung-report-test",
            "period": {"from": "2026-07-01", "to": "2026-07-01"},
            "total_minutes": 450,
            "entries": {"2026-07-01": {"slots": [
                {"start": "08:00", "end": "16:00", "pause": 30, "kategorie": ""}]}},
        }
        body = json.dumps(sample, ensure_ascii=False).encode("utf-8")

        def fn():
            return webhook.deliver(
                candidate,
                json_bytes=body if candidate["payload"]["json"] else None,
                pdf_bytes=b"%PDF-1.4\n% Testversand\n"
                if candidate["payload"]["pdf"] else None,
                pdf_filename="Zeiterfassung_Test.pdf")

        def on_done(res):
            busy["testing"] = False
            if not dialog.winfo_exists():
                return
            set_secondary_button_enabled(test_btn, True)
            if res.get("ok"):
                themed_showinfo(
                    dialog, "Test erfolgreich",
                    f"Der Endpunkt hat mit HTTP {res['status']} geantwortet.")
                return
            from src.dialogs.send_task import format_result_summary
            themed_showerror(
                dialog, "Test fehlgeschlagen",
                format_result_summary(
                    [{"name": candidate["name"], "ok": False,
                      "kind": res.get("kind"), "detail": res.get("detail")}]))

        runner.run(fn, on_done)

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=5, column=0, columnspan=2, pady=14)
    save_btn = primary_button(btn_frame, "Speichern", do_save)
    save_btn.pack(side=tk.LEFT, padx=5)
    test_btn = secondary_button(btn_frame, "Testen", do_test)
    test_btn.pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    # Kein eigener <Escape>-Bind: create_dialog setzt ihn bereits
    # (escape_closes=True ist der Default) — die Fenster-Chrome gehört dorthin.
    center_dialog_on_parent(dialog, parent)
