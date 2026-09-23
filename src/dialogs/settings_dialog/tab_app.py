"""Tab „App": Bundesland, UI-Optionen, Skalierung."""

import tkinter as tk
from tkinter import ttk

from src.autostart import (
    disable_autostart, enable_autostart, is_autostart_enabled,
    resolve_autostart_target,
)
from src.dialogs.settings_dialog._shared import label
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    app_updates, slider_percent,
)
from src.holidays_de import STATES
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL, TEXT, TEXT_MUTED,
    dark_combo, px, scaled_window_fits, themed_askyesno,
    themed_showerror, workarea_for,
)


class AppTab:
    """Baut den App-Tab; Tab-Schnittstelle für den `SaveCoordinator` (#132)."""

    def __init__(self, frame, settings, dialog, parent, base_path):
        label(frame, "Bundesland:", row=0, pady=(10, 8))
        state_labels = [lbl for _, lbl in STATES]
        current_code = settings.get("state")
        current_label = next(
            (lbl for code, lbl in STATES if code == current_code),
            STATES[0][1],
        )
        state_var = tk.StringVar(value=current_label)
        dark_combo(frame, state_var, state_labels, width=22).grid(
            row=0, column=1, padx=10, pady=(10, 8), sticky="w")

        # Gerätelokale UI-Optionen. Alle in app_frame (ein Grid-Member), damit die
        # pack-Interna dieses Frames unberührt bleiben.
        app_frame = tk.Frame(frame, bg=BG)
        app_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=(4, 4), sticky="we")

        show_weekend_var = tk.BooleanVar(value=settings.get("show_weekend"))
        weekend_cb = tk.Checkbutton(
            app_frame, text="Wochenende (Sa/So) im Kalender anzeigen",
            variable=show_weekend_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
        )
        weekend_cb.pack(anchor="w")
        if settings.get("workweek_only"):
            # Sonst stünde hier ein Haken, der sichtbar nichts tut: der
            # Nur-Werktage-Modus blendet Sa/So ohnehin aus.
            weekend_cb.config(state="disabled")
            tk.Label(
                app_frame,
                text="Durch „Nur Werktage\" (Arbeitszeit) überstimmt.",
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
            ).pack(anchor="w", padx=(24, 0))

        autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        tk.Checkbutton(
            app_frame, text="Autostart (minimiert bei Anmeldung)",
            variable=autostart_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
        ).pack(anchor="w")

        always_on_top_var = tk.BooleanVar(value=settings.get("always_on_top"))
        tk.Checkbutton(
            app_frame, text="Immer im Vordergrund",
            variable=always_on_top_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
        ).pack(anchor="w")

        minimize_to_tray_var = tk.BooleanVar(value=settings.get("minimize_to_tray"))
        tk.Checkbutton(
            app_frame, text="Beim Schließen in den Infobereich minimieren",
            variable=minimize_to_tray_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
        ).pack(anchor="w")

        # --- Darstellung (UI-Skalierung, gerätelokal) ---
        tk.Label(
            app_frame, text="— Darstellung —", font=FONT_BOLD,
            bg=BG, fg=TEXT_MUTED,
        ).pack(pady=(12, 4))
        scale_row = tk.Frame(app_frame, bg=BG)
        scale_row.pack(fill="x")
        tk.Label(
            scale_row, text="Skalierung:", font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT, padx=(0, 8))

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
            scale_row, text=f"{slider_percent(scale_var.get())} %", font=FONT,
            bg=BG, fg=TEXT_MUTED, width=5, anchor="w",
        )

        # Als Trace statt als `command`: `command` feuert nur bei einer
        # Bewegung des Nutzers, die Beschriftung muss aber auch beim
        # Verwerfen (`load`) mitziehen.
        def _on_scale(*_args):
            scale_value_label.config(text=f"{slider_percent(scale_var.get())} %")

        scale_var.trace_add("write", _on_scale)

        scale_widget = ttk.Scale(
            scale_row, from_=75, to=200, orient="horizontal",
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
        tk.Label(
            app_frame, text="Änderung startet die App neu.", font=FONT_SMALL,
            bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

        self.frame = frame
        self.state_var = state_var
        self.show_weekend_var = show_weekend_var
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
        fields.add("state", state_var)
        fields.add("show_weekend", show_weekend_var)
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
