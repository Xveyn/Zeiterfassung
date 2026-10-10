"""Tab „Mobil" (#221): Handy-Erfassung per PWA ein-/ausschalten, Port, Adresse, Status,
gekoppelte Geräte und Koppeln.

Schalter, Port und Adresse sind Formularfelder (Speichern je Tab, `SaveCoordinator`);
„Gerät koppeln …", „Widerrufen" und „Alle widerrufen …" sind Aktionen, die sofort wirken.
Schreiben (Widerruf) läuft über den `BackgroundTaskRunner`; die Geräteliste zu lesen ist
günstig (der Store hält sie im Speicher) und geschieht im Poll. Den Status liefert ein
`after`-Poll aus `MobileService.status` — wie im API-Tab ein Poll, der mit dem Tab
stirbt, statt eines Callbacks, der nach dem Schließen zurückkommen könnte.

Das erste Einschalten fragt nach (unverschlüsselte Verbindung, vertrauenswürdiges Netz,
App muss laufen); erst die Zustimmung wird gemerkt (`mobile_notice_accepted`).
"""

import tkinter as tk

from src import netinfo
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    FIRST_ENABLE_NOTICE, REVOKE_ERROR_TEXT, address_options, address_to_choice,
    device_row_text, keystore_summary, mobile_status_view, mobile_updates, revoke_outcome,
    validate_mobile,
)
from src.theme import (
    ACCENT, BG, ENTRY_BG, FONT, STATUS_OK, STATUS_WARN, TEXT, TEXT_MUTED, Form, dark_combo,
    dark_entry, empty_state, px, set_secondary_button_enabled, themed_askyesno,
    themed_showerror,
)
from src.time_utils import utc_now_iso

_POLL_MS = 500
_WRAP_PX = 380       # wie im API-Tab: die Reiterbreite ist beim Öffnen festgenagelt
_STATUS_COLORS = {"ok": STATUS_OK, "muted": TEXT_MUTED, "error": STATUS_WARN}


class MobileTab:
    """Baut den Mobil-Tab; Tab-Schnittstelle für den `SaveCoordinator`."""

    def __init__(self, frame, dialog, settings, mobile_service, runner):
        self.frame = frame
        self.title = "Mobil"
        self._dialog = dialog
        self._settings = settings
        self._service = mobile_service
        self._runner = runner
        self._alive = True
        self._busy = False                  # Widerruf läuft
        self._poll_id = None
        self._rows = []                     # Datensätze, parallel zur Listbox
        self._row_texts = []

        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        enabled_var = tk.BooleanVar(value=bool(settings.get("mobile_enabled")))
        port_var = tk.StringVar(value=str(settings.get("mobile_port")))
        address_var = tk.StringVar(
            value=address_to_choice(str(settings.get("mobile_address") or "")))
        self._enabled_var = enabled_var
        self._last_enabled = enabled_var.get()

        form.section("Handy-Erfassung")
        form.hint("Zeiten unterwegs auf dem Handy nachtragen — auch ohne Verbindung — und im "
                  "selben WLAN mit dieser App abgleichen. Die Verbindung ist unverschlüsselt "
                  "(nur in vertrauenswürdigen Netzen nutzen), die App muss laufen. Unter "
                  "Windows fragt die Firewall beim ersten Einschalten nach.")
        form.check("Handy-Erfassung aktivieren", enabled_var)
        with form.depends_on(enabled_var):
            form.row("Port:", dark_entry(body, port_var, width=7))
            self._combo = dark_combo(body, address_var, address_options([]), width=20)
            form.row("Adresse:", self._combo)
        self._status_label = tk.Label(
            body, text="", font=FONT, bg=BG, fg=TEXT_MUTED, anchor="w",
            justify="left", wraplength=px(_WRAP_PX))
        form.row("Status:", self._status_label)

        form.section("Gekoppelte Geräte")
        box = tk.Frame(body, bg=BG)
        box.columnconfigure(0, weight=1)
        self._listbox = tk.Listbox(
            box, height=4, width=30, font=FONT, bg=ENTRY_BG, fg=TEXT, selectbackground=ACCENT,
            selectforeground="#ffffff", relief="flat", highlightthickness=0,
            activestyle="none", exportselection=False)
        self._listbox.grid(row=0, column=0, sticky="nsew")
        self._empty = empty_state(box, "Noch kein Handy gekoppelt.", bg=ENTRY_BG)
        self._empty.grid(row=0, column=0, sticky="nsew")
        form.block(box)
        self._pair_btn, self._revoke_btn, self._revoke_all_btn = form.buttons(
            ("Gerät koppeln …", self._pair),
            ("Widerrufen", self._revoke),
            ("Alle widerrufen …", self._revoke_all))
        self._keystore_label = form.hint("")
        self._listbox.bind("<<ListboxSelect>>", lambda _e: self._sync_buttons())

        port_var.trace_add("write", lambda *_args: self._sync_buttons())
        enabled_var.trace_add("write", self._on_enabled_changed)

        fields = FieldSet()
        fields.add("mobile_enabled", enabled_var)
        fields.add("mobile_port", port_var)
        fields.add("mobile_address", address_var)
        self.fields = fields

        self._runner.run(netinfo.lan_candidates, self._candidates_loaded)
        self._sync_buttons()
        frame.bind("<Destroy>", self._on_destroy, add="+")
        self._poll()

    # --- Tab-Schnittstelle --------------------------------------------------

    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return validate_mobile(self.values())

    def save(self):
        self._settings.apply_updates(mobile_updates(self.values()))
        return SaveOutcome(saved=True)

    # --- Schalter und Adressen ------------------------------------------------------

    def _on_enabled_changed(self, *_args):
        enabled = bool(self._enabled_var.get())
        if enabled and not self._last_enabled and not self._settings.get("mobile_notice_accepted"):
            if not themed_askyesno(self._dialog, "Handy-Erfassung einschalten",
                                   FIRST_ENABLE_NOTICE, lock_ms=600):
                self._enabled_var.set(False)            # zurück, nichts eingeschaltet
                return
            self._settings.set("mobile_notice_accepted", True)
        self._last_enabled = bool(self._enabled_var.get())
        self._sync_buttons()

    def _candidates_loaded(self, candidates):
        if not self._alive:
            return
        try:
            # Nur die Auswahl, nie der Wert: eine später eintreffende Liste macht den
            # Reiter nicht „geändert".
            self._combo.configure(values=address_options(candidates or []))
        except tk.TclError:
            self._alive = False

    # --- Anzeige --------------------------------------------------------------------

    def _on_destroy(self, event):
        if event.widget is not self.frame:
            return
        self._alive = False
        if self._poll_id is not None:
            try:
                self.frame.after_cancel(self._poll_id)
            except tk.TclError:
                pass                    # Fenster schon weg: nichts mehr zu stornieren

    def _poll(self):
        if not self._alive:
            return
        try:
            text, kind = mobile_status_view(self._service.status)
            self._status_label.config(text=text, fg=_STATUS_COLORS[kind])
            self._refresh_devices()
            # Bei jedem Poll, nicht nur bei einer geänderten Geräteliste: der Zustand von
            # „Gerät koppeln …" hängt am Status, und der ändert sich unabhängig davon.
            self._sync_buttons()
            self._poll_id = self.frame.after(_POLL_MS, self._poll)
        except tk.TclError:
            self._alive = False             # Fenster zwischenzeitlich zu

    def _refresh_devices(self):
        self._keystore_label.config(text=keystore_summary(self._service.key_locations()))
        records = self._service.list_devices()
        now = utc_now_iso()
        texts = [device_row_text(record, now) for record in records]
        if texts == self._row_texts:
            return                          # nichts geändert: die Auswahl bleibt
        selected = self._selected_id()
        self._rows, self._row_texts = records, texts
        self._listbox.delete(0, tk.END)
        for text in texts:
            self._listbox.insert(tk.END, text)
        for index, record in enumerate(records):
            if record["id"] == selected:
                self._listbox.selection_set(index)
        if texts:
            self._empty.grid_remove()
        else:
            self._empty.grid()
        self._sync_buttons()

    def _selected_id(self):
        selection = self._listbox.curselection()
        if not selection or selection[0] >= len(self._rows):
            return None
        return self._rows[selection[0]]["id"]

    def _sync_buttons(self):
        running = self._service.status.state == "running"
        has_devices = bool(self._rows)
        has_selection = self._selected_id() is not None
        set_secondary_button_enabled(self._pair_btn, running and not self._busy)
        set_secondary_button_enabled(self._revoke_btn, has_selection and not self._busy)
        set_secondary_button_enabled(self._revoke_all_btn, has_devices and not self._busy)

    # --- Aktionen ---------------------------------------------------------------------

    def _pair(self):
        if self._service.status.state != "running" or self._busy:
            return
        # Lazy: der Dialog importiert `tab_rules` und damit dieses Paket; oben stünde
        # ein Importzyklus (Dialog → Paket → tab_mobile → Dialog).
        from src.dialogs.mobile_pair_dialog import open_pair_dialog
        open_pair_dialog(self._dialog, self._service)
        if self._alive:
            self._refresh_devices()

    def _revoke(self):
        device_id = self._selected_id()
        if device_id is None or self._busy:
            return
        name = next((r["name"] for r in self._rows if r["id"] == device_id), device_id)
        if not themed_askyesno(
                self._dialog, "Gerät widerrufen",
                f"„{name}“ wird ausgesperrt und muss neu gekoppelt werden.\n\nFortfahren?",
                lock_ms=600):
            return
        self._busy = True
        self._sync_buttons()
        self._runner.run(
            lambda: revoke_outcome(lambda: self._service.revoke(device_id)), self._revoked)

    def _revoke_all(self):
        if not self._rows or self._busy:
            return
        if not themed_askyesno(
                self._dialog, "Alle Geräte widerrufen",
                "Alle gekoppelten Handys werden ausgesperrt und müssen neu gekoppelt "
                "werden.\n\nFortfahren?", lock_ms=600):
            return
        self._busy = True
        self._sync_buttons()
        self._runner.run(
            lambda: revoke_outcome(self._service.revoke_all), self._revoked)

    def _revoked(self, outcome):
        self._busy = False
        if not self._alive:
            return
        try:
            self._refresh_devices()
            self._sync_buttons()
            if not outcome["ok"]:
                themed_showerror(self._dialog, "Widerruf fehlgeschlagen", REVOKE_ERROR_TEXT)
        except tk.TclError:
            self._alive = False
