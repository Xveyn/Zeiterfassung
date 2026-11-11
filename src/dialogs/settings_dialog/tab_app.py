"""Tab „App": Fenster, Darstellung (Skalierung) und Daten (Datenordner, Import)."""

import logging
import os
import platform
import sys
import tkinter as tk
import traceback
from tkinter import messagebox, ttk

from src import dpi, removal
from src.autostart import (
    disable_autostart, enable_autostart, is_autostart_enabled, linux_desktop_path,
    resolve_autostart_target,
)
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    app_updates, autostart_path_hint, slider_percent,
)
from src.i18n import t
from src.logging_setup import get_log_dir
from src.platform_open import open_folder
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, TEXT_MUTED, Form, px, scaled_window_fits,
    themed_askyesno, themed_showerror, themed_showinfo, workarea_for,
)


class AppTab:
    """Baut den App-Tab; Tab-Schnittstelle für den `SaveCoordinator` (#132)."""

    def __init__(self, frame, settings, dialog, parent, base_path, *,
                 storage=None, reservation_store=None, on_change=None,
                 on_request_removal=None):
        self.frame = frame
        self._on_request_removal = on_request_removal
        self._storage = storage
        self._reservation_store = reservation_store
        self._on_change = on_change
        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        always_on_top_var = tk.BooleanVar(value=settings.get("always_on_top"))
        minimize_to_tray_var = tk.BooleanVar(value=settings.get("minimize_to_tray"))
        form.section(t("tab_app.abschnitt_fenster"))
        form.check(t("tab_app.autostart"), autostart_var)
        path_hint = autostart_path_hint(platform.system(), linux_desktop_path())
        if path_hint is not None:
            form.hint(path_hint)
        form.check(t("tab_app.vordergrund"), always_on_top_var)
        form.check(t("tab_app.infobereich"), minimize_to_tray_var)

        # --- Darstellung (UI-Skalierung, gerätelokal) ---
        form.section(t("tab_app.abschnitt_darstellung"))
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
        form.row(t("tab_app.skalierung"), scale_cell)
        form.hint(t("tab_app.skalierung_hinweis"))
        auto_scale_var = tk.BooleanVar(
            value=bool(settings.get("auto_scale_restart")))
        # Nur unter Linux: nur dort erkennt die App den Monitorwechsel
        # (Xveyn#201; Windows Xveyn#493).
        if platform.system() == "Linux":
            form.check(t("tab_app.skalierung_auto"), auto_scale_var)
            form.hint(t("tab_app.skalierung_auto_hinweis"))
        system_hint = dpi.scale_hint(dpi.system_scale())
        if system_hint:
            form.hint(system_hint)

        # --- Daten ---
        form.section(t("tab_app.abschnitt_daten"))
        # Zwei Reihen statt einer: drei Knöpfe nebeneinander würden bei großer
        # Skalierung den Dialog verbreitern.
        form.buttons((t("tab_app.datenordner_oeffnen"), self._open_data_folder),
                     (t("tab_app.log_oeffnen"), self._open_log_folder))
        if storage is not None:
            form.buttons((t("tab_app.daten_importieren"), self._open_import_dialog))
        form.hint(t("tab_app.daten_hinweis"))
        if on_request_removal is not None and removal.is_available(
                platform.system(), getattr(sys, "frozen", False)):
            form.buttons((t("tab_app.entfernen"), self._request_removal))
            form.hint(t("tab_app.entfernen_hinweis"))

        # --- Datenschutz ---
        form.section(t("tab_app.datenschutz"))
        form.buttons((t("tab_app.datenschutz_knopf"), self._open_privacy))
        form.hint(t("tab_app.datenschutz_hinweis"))

        self.autostart_var = autostart_var
        self.always_on_top_var = always_on_top_var
        self.minimize_to_tray_var = minimize_to_tray_var
        self.scale_var = scale_var
        self.auto_scale_var = auto_scale_var

        self.title = t("tab_app.titel")
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
        fields.add("auto_scale_restart", auto_scale_var)
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
                    self._dialog, t("tab_app.autostart_fehler_titel"),
                    t("tab_app.autostart_fehler", fehler=e),
                )
                return SaveOutcome(saved=False)
        settings.apply_updates(updates)
        return SaveOutcome(saved=True, restart=new_scale != old_scale)

    def _open_data_folder(self):
        self._open_folder(self._base_path, "Datenordner")

    def _open_log_folder(self):
        folder = get_log_dir(self._base_path)
        if not os.path.isdir(folder):
            # Bekannter Fall (das Logging-Setup ist nicht-fatal, s. `main()`):
            # kurze, kuratierte Meldung statt Traceback.
            themed_showinfo(
                self._dialog, t("tab_app.kein_log_titel"), t("tab_app.kein_log"))
            return
        self._open_folder(folder, "Log-Ordner")

    def _open_folder(self, path, what):
        try:
            open_folder(path)
        except Exception as e:
            logging.getLogger(__name__).exception(
                "%s konnte nicht geöffnet werden", what)
            messagebox.showerror(
                t("tab_app.ordner_fehler_titel"),
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=self._dialog,
            )

    def _request_removal(self):
        from src.dialogs.removal_dialog import ask_removal

        # Lokale Bindung: Pyright trägt das None-Narrowing sonst nicht in die
        # Closure (reportOptionalCall-FP, Muster wie in background_tasks.run).
        callback = self._on_request_removal
        if callback is None:
            return
        with_data = ask_removal(self._dialog)
        if with_data is None:
            return
        # Schließt den Einstellungen-Dialog ohne Rückfrage nach ungespeicherten
        # Änderungen (dialog.py::_remove) — ein Speichern danach legte
        # settings.json neu an.
        callback(with_data)

    def _open_privacy(self):
        from src.dialogs.privacy_dialog import open_privacy_dialog

        open_privacy_dialog(self._dialog)

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
            self._dialog, t("tab_app.passt_nicht_titel"),
            t("tab_app.passt_nicht", prozent=round(new_scale * 100),
              hoehe=needed, verfuegbar=available),
        )
