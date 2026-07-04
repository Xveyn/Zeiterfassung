import logging
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox

from src.report import default_pdf_filename, generate_pdf
from src.time_utils import validate_period
from src.dialogs.period_picker import build_period_picker
from src.theme import (
    BG,
    apply_combobox_style, attach_unfocus_on_click, center_dialog_on_parent,
    create_dialog, primary_button, secondary_button,
    set_primary_button_enabled, themed_showerror, themed_showinfo,
)


def open_export_dialog(parent, storage, settings):
    """Modal: Zeitraum + Kategorien wählen, daraus die PDF erzeugen und lokal
    über einen 'Speichern unter'-Dialog speichern. Kein Gmail nötig."""
    dialog = create_dialog(parent, "Als PDF exportieren")
    apply_combobox_style(dialog)
    attach_unfocus_on_click(dialog)

    picker_frame, picker = build_period_picker(
        dialog, storage, settings, on_change=lambda: _refresh_export_btn())
    picker_frame.grid(row=0, column=0, sticky="w")

    def do_export():
        if picker.get_categories() == set():
            # "Exportieren" ist in diesem Zustand optisch deaktiviert — No-op.
            # set_primary_button_enabled blockt den Klick nicht (nur die Optik),
            # daher hier abfangen, statt ein "Keine Einträge"-Modal zu zeigen.
            return
        date_from, date_to = picker.get_range()
        if date_from is None:
            themed_showerror(dialog, "Ungültiges Datum", "Bitte ein gültiges Datum eingeben.")
            return
        ok, msg = validate_period(date_from, date_to)
        if not ok:
            themed_showerror(dialog, "Ungültiger Zeitraum", msg)
            return

        # Frisch lesen (Hintergrund-Drive-Sync könnte den Storage geändert haben).
        entries = storage.get_all()
        categories = picker.get_categories()

        # Erst erzeugen, dann nach dem Pfad fragen — so erscheint der Speichern-
        # Dialog bei leerem Zeitraum gar nicht erst.
        try:
            pdf_bytes = generate_pdf(
                date_from, date_to, entries,
                name=settings.get("name"), categories=categories,
                category_breakdown=picker.get_category_breakdown())
        except Exception as e:
            logging.getLogger(__name__).exception("PDF-Erzeugung fehlgeschlagen")
            messagebox.showerror(
                "Export fehlgeschlagen",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=dialog,
            )
            return

        if pdf_bytes is None:
            themed_showinfo(
                dialog, "Keine Einträge",
                f"Keine Einträge für {date_from.strftime('%d.%m.%Y')} – "
                f"{date_to.strftime('%d.%m.%Y')} vorhanden.",
            )
            return

        path = filedialog.asksaveasfilename(
            parent=dialog,
            title="PDF speichern unter",
            initialfile=default_pdf_filename(date_from, date_to),
            defaultextension=".pdf",
            filetypes=[("PDF-Datei", "*.pdf")],
        )
        if not path:
            return

        try:
            with open(path, "wb") as f:
                f.write(pdf_bytes)
        except OSError as e:
            themed_showerror(
                dialog, "Export fehlgeschlagen",
                f"Die Datei konnte nicht gespeichert werden:\n{e}")
            return

        dialog.destroy()
        themed_showinfo(parent, "Exportiert", f"PDF gespeichert unter\n{path}")

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=1, column=0, pady=12)
    export_btn = primary_button(btn_frame, "Exportieren", do_export)
    export_btn.pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    def _refresh_export_btn(*_):
        # "Exportieren" nur klickbar, wenn die Kategorie-Auswahl nicht leer ist.
        # get_categories(): None = alle gewählt bzw. keine Kategorien vorhanden
        # → klickbar; nicht-leere Menge (auch {""} = nur "(ohne Kategorie)")
        # → klickbar; set() = nichts angehakt → deaktiviert.
        set_primary_button_enabled(export_btn, picker.get_categories() != set())

    _refresh_export_btn()

    center_dialog_on_parent(dialog, parent)
