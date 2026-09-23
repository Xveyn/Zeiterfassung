import tkinter as tk
from tkinter import ttk

from src.dialogs.settings_dialog.form_model import SaveCoordinator
from src.dialogs.settings_dialog.tab_app import AppTab
from src.dialogs.settings_dialog.tab_google import GoogleTab
from src.dialogs.settings_dialog.tab_mail import MailTab
from src.dialogs.settings_dialog.tab_smtp import SmtpTab
from src.dialogs.settings_dialog.tab_updates import UpdatesTab
from src.dialogs.settings_dialog.tab_webhooks import WebhooksTab
from src.dialogs.settings_dialog.tab_work import WorkTab
from src.theme import (
    BG,
    apply_combobox_style, apply_notebook_style, attach_unfocus_on_click,
    center_dialog_on_parent, create_dialog,
    primary_button, secondary_button, set_primary_button_enabled,
    themed_ask_save_changes, themed_showerror,
)


def open_settings_dialog(parent, settings, base_path, on_change, *,
                         runner, auto_updater, conflicts_store=None,
                         storage=None,
                         reservation_store=None, on_request_restart=None,
                         data_lock=None, sync_guard=None, webhook_store=None,
                         smtp_store=None,
                         vacation_store=None, on_vacation_change=None,
                         on_vacation_display_change=None, initial_tab=None):
    """Modaler Dialog zum Bearbeiten der App-Einstellungen, aufgeteilt auf sieben
    Tabs (Arbeitszeit / Bericht & Mail / Webhooks / SMTP / Google / App / Updates).

    Gespeichert wird je Tab (#132): „Speichern" schreibt nur den aktiven Tab;
    wer einen geänderten Tab verlässt oder den Dialog schließt, wird gefragt
    (`form_model.SaveCoordinator`).

    on_change wird nach jedem erfolgreichen Speichern eines Tabs aufgerufen
    (der Dialog bleibt offen), damit der Kalender sich aktualisiert. conflicts_store und storage sind optional; sind sie
    gesetzt, erscheint im Google-Tab der Sync-Block mit Konflikte-Button.
    data_lock/sync_guard: geteilter Store-Lock + Sync-Guard für die Kompaktierung
    (Audit H1/H2) — von App durchgereicht.
    runner: der App-BackgroundTaskRunner (App._bg); alle Hintergrund-Worker des
    Dialogs laufen über runner.run(fn, on_done) (Audit H5).
    auto_updater: der `auto_update.AutoUpdater` der App — derselbe, den ihr
    Start-Check benutzt, damit beide Auslöser einen Guard teilen (R9).
    vacation_store/on_vacation_change: optional; sind sie gesetzt, erscheint
    im Arbeitszeit-Tab der „Urlaub verwalten"-Button.
    on_vacation_display_change: reines Neuzeichnen des Kalenders für die
    Anzeige-Schalter jenes Dialogs — ohne den Kalender-Abgleich, den
    on_vacation_change mitbringt.
    initial_tab: optionaler Schlüssel aus `tabs` (unten), auf den der Dialog
    direkt aufspringt — Default `None` lässt es beim bisherigen Verhalten
    (erster Tab „Arbeitszeit"). Für Aufrufer, die gezielt zu einem Tab wollen
    (das Update-Banner zu „updates"), statt dass der Nutzer ihn selbst sucht.
    """
    dialog = create_dialog(parent, "Einstellungen", escape_closes=False)

    apply_combobox_style(dialog)
    apply_notebook_style(dialog)

    notebook = ttk.Notebook(dialog, style="Dark.TNotebook")
    notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))

    tab_work = tk.Frame(notebook, bg=BG)
    tab_mail = tk.Frame(notebook, bg=BG)
    tab_webhooks = tk.Frame(notebook, bg=BG)
    tab_smtp = tk.Frame(notebook, bg=BG)
    tab_google = tk.Frame(notebook, bg=BG)
    tab_app = tk.Frame(notebook, bg=BG)
    tab_updates = tk.Frame(notebook, bg=BG)
    notebook.add(tab_work, text="Arbeitszeit")
    notebook.add(tab_mail, text="Bericht & Mail")
    notebook.add(tab_webhooks, text="Webhooks")
    notebook.add(tab_smtp, text="SMTP")
    notebook.add(tab_google, text="Google")
    notebook.add(tab_app, text="App")
    notebook.add(tab_updates, text="Updates")

    # ===================== Tab: Arbeitszeit =====================
    work = WorkTab(tab_work, dialog, settings, vacation_store,
                   on_vacation_change, storage, reservation_store, runner,
                   on_vacation_display_change)

    # ===================== Tab: Bericht & Mail =====================
    mail = MailTab(tab_mail, settings)

    # ===================== Tab: Webhooks =====================
    hooks = WebhooksTab(tab_webhooks, dialog, webhook_store, runner, parent)

    # ===================== Tab: SMTP =====================
    smtp = SmtpTab(tab_smtp, dialog, smtp_store, runner, parent)

    # ===================== Tab: Google =====================
    google = GoogleTab(
        tab_google, dialog, settings, base_path, on_change, runner,
        storage, conflicts_store, reservation_store, data_lock, sync_guard)

    # ===================== Tab: App =====================
    app = AppTab(tab_app, settings, dialog, parent, base_path)

    # ===================== Tab: Updates =====================
    updates_tab = UpdatesTab(tab_updates, settings, runner, auto_updater)

    # Vor dem initialen select deklariert und gebunden (wie bisher): der
    # Banner-Weg (initial_tab="updates") startet so seinen Live-Check über
    # <<NotebookTabChanged>>. on_tab_selected ist idempotent (self._checked).
    coordinator = None
    save_btn = None

    def _refresh_save_button():
        if coordinator is None or save_btn is None or not dialog.winfo_exists():
            return
        set_primary_button_enabled(save_btn, coordinator.dirty())

    def _on_tab_changed(_event):
        if notebook.select() == str(updates_tab.frame):
            updates_tab.on_tab_selected()
        _refresh_save_button()

    notebook.bind("<<NotebookTabChanged>>", _on_tab_changed)

    # ===================== Speichern / Buttons =====================
    # Reihenfolge = Reiterreihenfolge im Notebook: der Reiter-Klick unten
    # rechnet über den Index auf den Schlüssel um.
    tabs = {
        "work": work,
        "mail": mail,
        "webhooks": hooks,
        "smtp": smtp,
        "google": google,
        "app": app,
        "updates": updates_tab,
    }
    keys = list(tabs)
    assert len(keys) == notebook.index("end"), "tabs und Notebook laufen auseinander"

    # Springt direkt auf den gewünschten Tab, statt den Nutzer beim Default
    # ("Arbeitszeit") suchen zu lassen. Läuft vor dem ersten Edit — der
    # Coordinator braucht hier nicht zu fragen.
    current = initial_tab if initial_tab in tabs else "work"
    notebook.select(tabs[current].frame)

    def _restart():
        # Der Neustart nimmt den Dialog mit; der Coordinator liefert danach
        # False, damit niemand mehr an diesem Fenster etwas tut.
        dialog.destroy()
        if on_request_restart is not None:
            on_request_restart()

    coordinator = SaveCoordinator(
        tabs, current,
        ask=lambda title: themed_ask_save_changes(dialog, title),
        show_error=lambda title, msg: themed_showerror(dialog, title, msg),
        on_change=on_change,
        on_restart=_restart,
    )

    def _save():
        # Ein grauer Knopf ist nur optisch gesperrt (set_primary_button_enabled)
        # — ohne Änderungen ist save_current ein No-op.
        coordinator.save_current()
        _refresh_save_button()

    def _close():
        if coordinator.request_close() and dialog.winfo_exists():
            dialog.destroy()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(pady=12)
    save_btn = primary_button(btn_frame, "Speichern", _save)
    save_btn.pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Schließen", _close).pack(side=tk.LEFT, padx=5)

    for tab in tabs.values():
        tab.fields.on_edit(_refresh_save_button)

    def _on_calendars_loaded():
        coordinator.rebaseline("google", ["gcal_calendar"])
        _refresh_save_button()

    google.on_calendars_loaded = _on_calendars_loaded

    def _on_tab_click(event):
        """Fängt den Reiter-Klick VOR dem Wechsel ab: ttk.Notebook kennt kein
        Veto, `<<NotebookTabChanged>>` käme erst danach. Die Widget-Bindung
        läuft vor der Klassenbindung des Notebooks; "break" verhindert den
        Wechsel. Tastatur-Traversal (enable_traversal) ist nicht aktiv."""
        try:
            index = notebook.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return None   # Klick neben die Reiter: das Notebook tut nichts
        target = keys[index]
        if target == coordinator.current:
            return None
        if coordinator.request_switch(target) and dialog.winfo_exists():
            notebook.select(tabs[target].frame)
        return "break"

    notebook.bind("<Button-1>", _on_tab_click)
    _refresh_save_button()

    attach_unfocus_on_click(dialog)
    dialog.protocol("WM_DELETE_WINDOW", _close)
    dialog.bind("<Escape>", lambda _e: _close())
    center_dialog_on_parent(dialog, parent)
