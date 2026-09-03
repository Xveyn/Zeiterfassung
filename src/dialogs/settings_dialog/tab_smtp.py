"""Tab „SMTP": Liste der konfigurierten Mail-Konten.

Anders als die übrigen Tabs exponiert dieser KEINE Variablen für
save_settings — SMTP-Konten liegen in ihrem eigenen, gerätelokalen Store und
werden vom Unterdialog direkt gespeichert.
"""

import tkinter as tk

from src import keyring_store, smtp_store
from src.dialogs.smtp_dialog import open_smtp_dialog
from src.theme import (
    ACCENT, BG, ENTRY_BG, FONT, FONT_SMALL, TEXT, TEXT_MUTED,
    primary_button, secondary_button, themed_askyesno, themed_showerror,
)


class SmtpTab:
    def __init__(self, frame, dialog, store, runner, parent=None):
        self.frame = frame
        self._dialog = dialog
        # Fallback-Ziel für Fehlermeldungen, falls der Einstellungen-Dialog
        # inzwischen geschlossen wurde (analog send_dialog.on_done). Ohne
        # Injektion (ältere Aufrufer/Tests) fällt das auf `dialog` selbst
        # zurück — dann bleibt das Verhalten wie zuvor.
        self._parent = parent if parent is not None else dialog
        self._store = store
        self._runner = runner

        # Verteilt überschüssige Breite an die Spalte, statt sie rechts liegen
        # zu lassen: das Notebook ist so breit wie sein breitester Tab (App),
        # dieser hier braucht weniger. Ohne das endete die Liste mitten im Tab
        # und der Rest bliebe totes Feld. Auf die angeforderte Breite hat
        # `weight` keinen Einfluss — nur auf den Überschuss.
        frame.columnconfigure(0, weight=1)

        # wraplength ist Pflicht, nicht Kosmetik: ohne sie wird das Label so
        # breit wie seine längste Zeile und zieht den GANZEN Einstellungen-
        # Dialog mit — das Notebook ist so breit wie sein breitester Tab.
        # 380 ist der im Projekt übliche Wert (send_dialog, conflicts_dialog,
        # die themed Message-Dialoge) und hält diesen Tab auf allen
        # ui_scale-Stufen unter dem App-Tab, der die Dialogbreite bestimmt.
        tk.Label(
            frame,
            text=("Berichte können statt über die Gmail-API auch über einen "
                  "eigenen Mail-Server verschickt werden. Jedes Konto hat "
                  "seinen eigenen Empfänger und lässt sich beim Senden "
                  "einzeln auswählen. Konten gelten nur auf diesem Gerät und "
                  "werden sofort gespeichert — unabhängig vom „Abbrechen“ "
                  "dieses Einstellungen-Dialogs."),
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, justify="left",
            wraplength=380,
        ).grid(row=0, column=0, padx=10, pady=(10, 6), sticky="w")

        # Dieselbe Palette wie die Listbox im ConflictsDialog (ENTRY_BG wie
        # Eingabefelder, ACCENT-Selektion, `selectforeground`/`relief`
        # ebenfalls identisch). Zwei Listboxen mit unterschiedlichem Styling
        # wären ein dialogspezifisches Stil-Extra — CLAUDE.md verbietet das
        # ohne Rücksprache.
        # width in Zeichen: bestimmt die MINDEST-Breite der Spalte. 48 zog den
        # Dialog deutlich über die übrigen Tabs hinaus; 30 bleibt darunter,
        # und `sticky="we"` lässt die Liste trotzdem die volle Tab-Breite
        # einnehmen, die der Hinweistext vorgibt.
        self._listbox = tk.Listbox(
            frame, height=8, width=30, font=FONT,
            bg=ENTRY_BG, fg=TEXT, selectbackground=ACCENT,
            selectforeground="#ffffff", relief="flat",
            highlightthickness=0, activestyle="none",
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
            mark = "✓" if record.get("enabled") else "○"
            self._listbox.insert(
                tk.END,
                f"  {mark}  {record.get('name', '')}  —  {record.get('host', '?')}")

    def _selected(self):
        selection = self._listbox.curselection()
        return self._records[selection[0]] if selection else None

    def _add(self):
        if not self._store:
            return
        open_smtp_dialog(self._dialog, self._store, self._runner,
                         on_saved=self.refresh)

    def _edit(self):
        record = self._selected()
        if record is None:
            return
        open_smtp_dialog(self._dialog, self._store, self._runner,
                         record=record, on_saved=self.refresh)

    def _remove(self):
        record = self._selected()
        if record is None:
            return
        if not themed_askyesno(
                self._dialog, "SMTP-Konto entfernen",
                f"„{record.get('name', '')}“ wirklich entfernen?"):
            return

        # Über den Runner: delete schreibt die Datei neu (icacls-Subprozess,
        # bis zu 15 s), und delete_secret kann auf Linux blockieren.
        def fn():
            try:
                self._store.delete(record["id"])
            except (smtp_store.SmtpStoreReadOnly, OSError) as e:
                return {"ok": False, "error": e}
            # Erst NACH dem erfolgreichen Schreiben: sonst stünde ein Konto
            # ohne Passwort in der Datei. Der Store selbst fasst den
            # Schlüsselbund nicht an, damit er reine Dateipersistenz bleibt.
            keyring_store.delete_secret(record["id"])
            return {"ok": True}

        def on_done(res):
            alive = self._dialog.winfo_exists()
            if not res["ok"]:
                target = self._dialog if alive else self._parent
                themed_showerror(
                    target, "Nicht entfernt",
                    "Das SMTP-Konto konnte nicht entfernt werden:\n\n"
                    f"{res['error']}")
            if alive:
                self.refresh()

        self._runner.run(fn, on_done)
