"""Tab „App": Fenster, Darstellung (Skalierung) und Daten (Datenordner, Import)."""

import logging
import tkinter as tk
import traceback
from tkinter import messagebox, ttk

from src.autostart import (
    disable_autostart, enable_autostart, is_autostart_enabled,
    resolve_autostart_target,
)
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    app_updates, slider_percent,
)
from src.platform_open import open_folder
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, TEXT_MUTED, Form, px, scaled_window_fits,
    themed_askyesno, themed_showerror, workarea_for,
)


class AppTab:
    """Baut den App-Tab; Tab-Schnittstelle für den `SaveCoordinator` (#132)."""

    def __init__(self, frame, settings, dialog, parent, base_path, *,
                 storage=None, reservation_store=None, on_change=None):
        self.frame = frame
        self._storage = storage
        self._reservation_store = reservation_store
        self._on_change = on_change
        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        always_on_top_var = tk.BooleanVar(value=settings.get("always_on_top"))
        minimize_to_tray_var = tk.BooleanVar(value=settings.get("minimize_to_tray"))
        form.section("Fenster")
        form.check("Autostart (minimiert bei Anmeldung)", autostart_var)
        form.check("Immer im Vordergrund", always_on_top_var)
        form.check("Beim Schließen in den Infobereich minimieren", minimize_to_tray_var)

        # --- Darstellung (UI-Skalierung, gerätelokal) ---
        form.section("Darstellung")
        scale_cell = tk.Frame(body, bg=BG)
        # ttk.Scale statt klassischer tk.Scale: das clam-Theme ist via
        # apply_combobox_style aktiv, klassische tk.Scale rendert unter Windows
        # einen hellen System-Trough/-Regler. Wert in eigenem Label (kein
        # showvalue-Kasten); auf 5er-Schritte gerastert (ttk.Scale kennt kein
        # resolution). Akzent analog dark_entry: Ruhe TEXT_MUTED, Press ACCENT.
        scale_style = ttk.Style(frame)
        scale_style.configure(
            "Display.Horizontal.TScale",
            background=TEXT_MUTED, troughcolor=CELL_BG,
            bordercolor=CELL_BG, darkcolor=TEXT_MUTED, lightcolor=TEXT_MUTED,
        )
        scale_style.map(
            "Display.Horizontal.TScale",
            background=[("pressed", ACCENT)],
            darkcolor=[("pressed", ACCENT)],
            lightcolor=[("pressed", ACCENT)],
        )
        scale_var = tk.DoubleVar(value=round(settings.get("ui_scale") * 100))
        scale_value_label = tk.Label(
            scale_cell, text=f"{slider_percent(scale_var.get())} %", font=FONT,
            bg=BG, fg=TEXT_MUTED, width=5, anchor="w",
        )

        # Als Trace statt als `command`: `command` feuert nur bei einer
        # Bewegung des Nutzers, die Beschriftung muss aber auch beim
        # Verwerfen (`load`) mitziehen.
        def _on_scale(*_args):
            scale_value_label.config(text=f"{slider_percent(scale_var.get())} %")

        scale_var.trace_add("write", _on_scale)

        scale_widget = ttk.Scale(
            scale_cell, from_=75, to=200, orient="horizontal",
            variable=scale_var, length=px(200),
            style="Display.Horizontal.TScale",
        )
        scale_widget.bind(
            "<ButtonPress-1>", lambda _e: scale_value_label.config(fg=ACCENT), add="+",
        )
        scale_widget.bind(
            "<ButtonRelease-1>", lambda _e: scale_value_label.config(fg=TEXT_MUTED), add="+",
        )
        scale_widget.pack(side=tk.LEFT)
        scale_value_label.pack(side=tk.LEFT, padx=(8, 0))
        form.row("Skalierung:", scale_cell)
        form.hint("Änderung startet die App neu.")

        # --- Daten ---
        form.section("Daten")
        specs = [("Datenordner öffnen", self._open_data_folder)]
        if storage is not None:
            specs.append(("Daten importieren…", self._open_import_dialog))
        form.buttons(*specs)
        form.hint("Im Datenordner liegen Einträge, Einstellungen und "
                  "credentials.json. Importiert werden geteilte Arbeitszeiten "
                  "(JSON-Datei aus „Teilen“).")

        self.autostart_var = autostart_var
        self.always_on_top_var = always_on_top_var
        self.minimize_to_tray_var = minimize_to_tray_var
        self.scale_var = scale_var

        self.title = "App"
        self._settings = settings
        self._dialog = dialog
        self._parent = parent
        self._base_path = base_path

        fields = FieldSet()
        fields.add("autostart", autostart_var)
        fields.add("always_on_top", always_on_top_var)
        fields.add("minimize_to_tray", minimize_to_tray_var)
        # Gerastert gelesen: ein hin- und zurückgezogener Regler ist keine
        # Änderung.
        fields.add("ui_scale", scale_var, read=slider_percent)
        self.fields = fields

    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return None

    def save(self):
        settings = self._settings
        updates = app_updates(self.values())
        old_scale = settings.get("ui_scale")
        new_scale = updates["ui_scale"]
        # Erst die Frage, dann die Nebenwirkung: wer die Skalierung hier
        # ablehnt, soll keinen bereits umgeschalteten Autostart zurückbehalten.
        # Nur beim Vergrößern gefragt — wer herunterskaliert, kann nichts
        # verlieren.
        if new_scale > old_scale and not self._scale_confirmed(old_scale, new_scale):
            return SaveOutcome(saved=False)
        # Autostart vor dem Schreiben: scheitert er, wird nichts gespeichert.
        new_autostart = updates["autostart"]
        if new_autostart != is_autostart_enabled():
            try:
                if new_autostart:
                    target, arguments = resolve_autostart_target(self._base_path)
                    enable_autostart(target, arguments)
                else:
                    disable_autostart()
            except Exception as e:
                themed_showerror(
                    self._dialog, "Autostart-Fehler",
                    f"Autostart konnte nicht geändert werden:\n{e}",
                )
                return SaveOutcome(saved=False)
        settings.apply_updates(updates)
        return SaveOutcome(saved=True, restart=new_scale != old_scale)

    def _open_data_folder(self):
        try:
            open_folder(self._base_path)
        except Exception as e:
            logging.getLogger(__name__).exception(
                "Datenordner konnte nicht geöffnet werden")
            messagebox.showerror(
                "Ordner konnte nicht geöffnet werden",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=self._dialog,
            )

    def _open_import_dialog(self):
        from src.dialogs.import_dialog import open_import_dialog

        # Der Einstellungen-Dialog bleibt nach dem Import offen (#132): er
        # schloss sich früher, und das nahm ungespeicherte Änderungen eines
        # Tabs ohne Rückfrage mit. on_change aktualisiert den Kalender.
        open_import_dialog(
            self._dialog, self._storage, self._settings,
            self._on_change or (lambda: None),
            reservation_store=self._reservation_store,
        )

    def _scale_confirmed(self, old_scale, new_scale):
        """Passt die größere Skalierung auf den Bildschirm? Sonst fragen.

        Das Hauptfenster ist `resizable(False, False)` und wird auf seine
        angeforderte Größe gepinnt — bei 200 % auf einem 1080p-Schirm ist die
        Fußzeile abgeschnitten. Verhindert wird nichts: die Entscheidung
        gehört dem Nutzer, und sie ist umkehrbar, weil das Zahnrad im Header
        sitzt."""
        _, wa_top, _, wa_bottom = workarea_for(self._parent)
        available = wa_bottom - wa_top
        needed, fits = scaled_window_fits(
            self._parent.winfo_height(), old_scale, new_scale, available)
        if fits:
            return True
        return themed_askyesno(
            self._dialog, "Passt nicht auf den Bildschirm",
            f"Bei {round(new_scale * 100)} % braucht das Fenster etwa "
            f"{needed} Pixel Höhe — dein Bildschirm bietet "
            f"{available}.\n\nDie Fußzeile mit "
            "„Arbeitszeiten senden“, „Export“ und „Teilen“ wäre dann "
            "abgeschnitten. Die Einstellungen bleiben über das Zahnrad "
            "oben erreichbar.\n\nTrotzdem übernehmen?",
        )
