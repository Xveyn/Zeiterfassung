"""Gemeinsamer Aufbau der Listen-Tabs „Webhooks" und „SMTP" (R12, Xveyn#123).

Beide Tabs sind „Liste konfigurierter Einträge plus Hinzufügen, Bearbeiten,
Entfernen" über einem eigenen, gerätelokalen Store; ihre Unterdialoge
speichern direkt. Bis R12 standen sie als zwei zu 85 % gleiche Dateien da.
Was sich wirklich unterscheidet — Hinweistext, Detail in der Zeile,
Unterdialog, Texte beim Entfernen, Schreibschutz-Exception und was nach dem
Löschen noch zu tun ist —, trägt eine `RecordListKind`; `tab_webhooks.py` und
`tab_smtp.py` sind nur noch diese Beschreibung plus eine Unterklasse.

Anders als die übrigen Tabs exponieren diese beiden KEINE Variablen für
save_settings.
"""

import tkinter as tk
from dataclasses import dataclass
from typing import Any, Callable

from src.theme import (
    ACCENT, BG, ENTRY_BG, FONT, FONT_SMALL, TEXT, TEXT_MUTED,
    primary_button, secondary_button, themed_askyesno, themed_showerror,
)


@dataclass(frozen=True)
class RecordListKind:
    """Was einen Listen-Tab von seinem Zwilling unterscheidet."""

    intro: str                                  # Hinweistext über der Liste
    row_detail: Callable[[dict], str]           # rechts vom Namen, z.B. der Host
    open_dialog: Callable[..., None]            # (parent, store, runner, record=, on_saved=)
    remove_title: str                           # Titel der Rückfrage beim Entfernen
    remove_error: str                           # Satz vor der Fehlermeldung
    read_only_error: type[Exception]            # Schreibschutz-Exception des Stores
    after_delete: Callable[[str], None] | None = None   # nach erfolgreichem Löschen


def row_text(record: dict, detail: str) -> str:
    """Eine Zeile der Liste: Aktiv-Marke, Name, Detail."""
    mark = "✓" if record.get("enabled") else "○"
    return f"  {mark}  {record.get('name', '')}  —  {detail}"


def remove_record(store: Any, record_id: str, read_only_error: type[Exception],
                  after_delete: Callable[[str], None] | None = None) -> dict:
    """Löscht einen Eintrag — der Worker hinter „Entfernen" (Tk-frei).

    Liefert `{"ok": True}` oder `{"ok": False, "error": e}` für die erwarteten
    Schreibfehler (Schreibschutz, `OSError`); alles andere ist ein Bug und
    fliegt durch. `after_delete` läuft erst NACH dem erfolgreichen Schreiben:
    beim SMTP-Konto räumt es das Passwort aus dem Schlüsselbund, und davor
    stünde bei einem Fehlschlag ein Konto ohne Passwort in der Datei.
    """
    try:
        store.delete(record_id)
    except (read_only_error, OSError) as e:
        return {"ok": False, "error": e}
    if after_delete is not None:
        after_delete(record_id)
    return {"ok": True}


class RecordListTab:
    """Listen-Tab über einem gerätelokalen Store; Unterklassen setzen `KIND`."""

    KIND: RecordListKind

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
        # Nachgemessen bei 0.75/1.0/1.25/1.5/2.0.
        tk.Label(
            frame, text=self.KIND.intro,
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
            self._listbox.insert(
                tk.END, row_text(record, self.KIND.row_detail(record)))

    def _selected(self):
        selection = self._listbox.curselection()
        return self._records[selection[0]] if selection else None

    def _add(self):
        if not self._store:
            return
        self.KIND.open_dialog(self._dialog, self._store, self._runner,
                              on_saved=self.refresh)

    def _edit(self):
        record = self._selected()
        if record is None:
            return
        self.KIND.open_dialog(self._dialog, self._store, self._runner,
                              record=record, on_saved=self.refresh)

    def _remove(self):
        record = self._selected()
        if record is None:
            return
        if not themed_askyesno(
                self._dialog, self.KIND.remove_title,
                f"„{record.get('name', '')}“ wirklich entfernen?"):
            return

        # Wie beim Speichern über den Runner: delete schreibt die Datei neu
        # (icacls-Subprozess, bis zu 15 s), und `after_delete` kann blockieren
        # (SMTP: der Schlüsselbund auf Linux) — beides gehört nicht in den
        # Tk-Callback.
        def fn():
            return remove_record(self._store, record["id"],
                                 self.KIND.read_only_error,
                                 self.KIND.after_delete)

        def on_done(res):
            alive = self._dialog.winfo_exists()
            if not res["ok"]:
                # Ein Schreibfehler darf nie stillbleiben — auch wenn der
                # Einstellungen-Dialog inzwischen geschlossen wurde. Dann auf
                # `parent` zeigen statt den Fehler zu verschlucken (analog
                # send_dialog.on_done).
                target = self._dialog if alive else self._parent
                themed_showerror(
                    target, "Nicht entfernt",
                    f"{self.KIND.remove_error}\n\n{res['error']}")
            if alive:
                self.refresh()

        self._runner.run(fn, on_done)
