"""Gemeinsamer Aufbau der Listen „SMTP-Konten" und „Webhooks" im Versand-Tab
(R12, Xveyn#123; seit #132 Abschnitte statt eigener Tabs).

Beide Listen sind „konfigurierte Einträge plus Hinzufügen, Bearbeiten,
Entfernen" über einem eigenen, gerätelokalen Store; ihre Unterdialoge
speichern direkt. Bis R12 standen sie als zwei zu 85 % gleiche Dateien da.
Was sich wirklich unterscheidet — Überschrift, Hinweistext, Leertext, Detail
in der Zeile, Unterdialog, Texte beim Entfernen, Schreibschutz-Exception und
was nach dem Löschen noch zu tun ist —, trägt eine `RecordListKind`;
`tab_webhooks.py` und `tab_smtp.py` sind nur noch diese Beschreibung plus
eine Unterklasse. Die Namen tragen noch „Tab" aus R12 — die
Charakterisierungstests hängen daran.

Die Einträge speichern ihre Unterdialoge selbst — für den `SaveCoordinator`
tragen die Listen keine Formularfelder.
"""

import tkinter as tk
from dataclasses import dataclass
from typing import Any, Callable

from src.theme import (
    ACCENT, BG, ENTRY_BG, FONT, TEXT, empty_state, primary_button,
    secondary_button, themed_askyesno, themed_showerror,
)


@dataclass(frozen=True)
class RecordListKind:
    """Was einen Listen-Tab von seinem Zwilling unterscheidet."""

    intro: str                                  # Hinweistext über der Liste
    section: str                                # Abschnitts-Überschrift
    empty: str                                  # Leertext der leeren Liste
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
    """Eine Liste über einem gerätelokalen Store, als Abschnitt in einem
    fremden `Form` (Versand-Tab); Unterklassen setzen `KIND`."""

    KIND: RecordListKind

    def __init__(self, form, dialog, store, runner, parent=None):
        self._dialog = dialog
        # Fallback-Ziel für Fehlermeldungen, falls der Einstellungen-Dialog
        # inzwischen geschlossen wurde (analog send_dialog.on_done). Ohne
        # Injektion (ältere Aufrufer/Tests) fällt das auf `dialog` selbst
        # zurück.
        self._parent = parent if parent is not None else dialog
        self._store = store
        self._runner = runner

        form.section(self.KIND.section, hint=self.KIND.intro)
        box = tk.Frame(form.body, bg=BG)
        box.columnconfigure(0, weight=1)

        # Dieselbe Palette wie die Listbox im ConflictsDialog — zwei
        # Listboxen mit unterschiedlichem Styling wären ein
        # dialogspezifisches Stil-Extra. Drei Zeilen: im Versand-Tab stehen
        # zwei Listen unter der Mail-Vorlage, mehr Konten sind selten, und
        # die Listbox scrollt selbst, sobald es mehr werden.
        self._listbox = tk.Listbox(
            box, height=3, width=30, font=FONT,
            bg=ENTRY_BG, fg=TEXT, selectbackground=ACCENT,
            selectforeground="#ffffff", relief="flat",
            highlightthickness=0, activestyle="none",
        )
        self._listbox.grid(row=0, column=0, sticky="nsew")
        self._listbox.bind("<Double-Button-1>", lambda _e: self._edit())
        # Liegt in derselben Zelle über der Liste; `refresh` blendet ihn
        # aus, sobald es Einträge gibt.
        self._empty = empty_state(box, self.KIND.empty, bg=ENTRY_BG)
        self._empty.grid(row=0, column=0, sticky="nsew")

        btns = tk.Frame(box, bg=BG)
        btns.grid(row=0, column=1, sticky="n", padx=(8, 0))
        primary_button(btns, "Hinzufügen", self._add).pack(fill="x")
        secondary_button(btns, "Bearbeiten", self._edit).pack(fill="x", pady=(4, 0))
        secondary_button(btns, "Entfernen", self._remove).pack(fill="x", pady=(4, 0))
        form.block(box)

        self._records = []
        self.refresh()

    def refresh(self):
        self._records = self._store.get_all() if self._store else []
        self._listbox.delete(0, tk.END)
        for record in self._records:
            self._listbox.insert(
                tk.END, row_text(record, self.KIND.row_detail(record)))
        if self._records:
            self._empty.grid_remove()
        else:
            self._empty.grid()

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
