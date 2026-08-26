"""Tab „Webhooks": Liste der konfigurierten HTTP-Ziele.

Anders als die übrigen Tabs exponiert dieser KEINE Variablen für
save_settings — Webhooks liegen in ihrem eigenen, gerätelokalen Store und
werden vom Unterdialog direkt gespeichert.
"""

import tkinter as tk
from urllib.parse import urlsplit

from src import webhook_store
from src.dialogs.webhook_dialog import open_webhook_dialog
from src.theme import (
    ACCENT, BG, ENTRY_BG, FONT, FONT_SMALL, TEXT, TEXT_MUTED,
    primary_button, secondary_button, themed_askyesno, themed_showerror,
)


class WebhooksTab:
    def __init__(self, frame, dialog, store, runner):
        self.frame = frame
        self._dialog = dialog
        self._store = store
        self._runner = runner

        tk.Label(
            frame,
            text=("Der Bericht kann zusätzlich zur E-Mail an HTTP-Endpunkte "
                  "gesendet werden.\nWebhooks gelten nur auf diesem Gerät."),
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, justify="left",
        ).grid(row=0, column=0, padx=10, pady=(10, 6), sticky="w")

        # Dieselbe Palette wie die Listbox im ConflictsDialog (ENTRY_BG wie
        # Eingabefelder, ACCENT-Selektion). Zwei Listboxen mit
        # unterschiedlichem Styling wären ein dialogspezifisches Stil-Extra —
        # CLAUDE.md verbietet das ohne Rücksprache. Der Kommentar „Einzige
        # Listbox der App" in conflicts_dialog.py wird in Task 13 nachgezogen.
        self._listbox = tk.Listbox(
            frame, height=8, width=48, font=FONT,
            bg=ENTRY_BG, fg=TEXT, selectbackground=ACCENT,
            highlightthickness=0, borderwidth=0, activestyle="none",
        )
        self._listbox.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="we")
        self._listbox.bind("<Double-Button-1>", lambda _e: self._edit())

        btns = tk.Frame(frame, bg=BG)
        btns.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="w")
        primary_button(btns, "Hinzufügen", self._add).pack(side=tk.LEFT, padx=(0, 6))
        secondary_button(btns, "Bearbeiten", self._edit).pack(side=tk.LEFT, padx=6)
        secondary_button(btns, "Entfernen", self._remove).pack(side=tk.LEFT, padx=6)

        self._records = []
        self.refresh()

    def refresh(self):
        self._records = self._store.get_all() if self._store else []
        self._listbox.delete(0, tk.END)
        for record in self._records:
            host = urlsplit(record.get("url", "")).hostname or "?"
            mark = "✓" if record.get("enabled") else "○"
            self._listbox.insert(tk.END, f"  {mark}  {record.get('name', '')}  —  {host}")

    def _selected(self):
        selection = self._listbox.curselection()
        return self._records[selection[0]] if selection else None

    def _add(self):
        if not self._store:
            return
        open_webhook_dialog(self._dialog, self._store, self._runner,
                            on_saved=self.refresh)

    def _edit(self):
        record = self._selected()
        if record is None:
            return
        open_webhook_dialog(self._dialog, self._store, self._runner,
                            record=record, on_saved=self.refresh)

    def _remove(self):
        record = self._selected()
        if record is None:
            return
        if not themed_askyesno(
                self._dialog, "Webhook entfernen",
                f"„{record.get('name', '')}“ wirklich entfernen?"):
            return

        # Wie beim Speichern über den Runner: delete schreibt die Datei neu
        # (icacls-Subprozess unter dem geteilten Daten-Lock).
        def fn():
            try:
                self._store.delete(record["id"])
            except (webhook_store.WebhookStoreReadOnly, OSError) as e:
                return {"ok": False, "error": e}
            return {"ok": True}

        def on_done(res):
            if not self._dialog.winfo_exists():
                return
            if not res["ok"]:
                themed_showerror(
                    self._dialog, "Nicht entfernt",
                    f"Der Webhook konnte nicht entfernt werden:\n\n{res['error']}")
            self.refresh()

        self._runner.run(fn, on_done)
