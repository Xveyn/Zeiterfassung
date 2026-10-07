"""Tab „API" (#92): lokale HTTP-API ein-/ausschalten, Port, Status und Token.

Schalter und Port sind Formularfelder (Speichern je Tab, `SaveCoordinator`);
„Token kopieren" und „Neu erzeugen" sind Aktionen, die sofort wirken. Beide
blockieren (Dateizugriff, unter Windows `icacls`) und laufen deshalb über den
`BackgroundTaskRunner`. Der Status kommt per Poll aus `ApiService.status`: das
`on_status`-Callback kann nach dem Schließen des Dialogs zurückkommen, ein
`after`-Poll, der mit dem Tab stirbt, nicht.

Das Token wird nie angezeigt, nur in die Zwischenablage kopiert.

Die Knöpfe stehen bewusst **außerhalb** der `depends_on`-Gruppe: für
Label-Buttons verbietet `Form` beide Wege zugleich (Gruppe und eigenes
`set_secondary_button_enabled`). Ihren Zustand berechnet `_sync_buttons` an einer
Stelle aus `tab_rules.token_buttons_enabled`; die Token-Zeile rendert
`tab_rules.token_label_view` — beide Tk-frei und getestet.
"""

import tkinter as tk

from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    api_updates, curl_example, port_hint, status_view, token_buttons_enabled,
    token_label_view, validate_api,
)
from src.theme import (
    BG, FONT, STATUS_OK, STATUS_WARN, TEXT_MUTED, Form, dark_entry, px,
    set_secondary_button_enabled, themed_askyesno, themed_showerror,
    themed_showinfo,
)

_POLL_MS = 500
_FLASH_MS = 2500
# Umbruchbreite für Status und Token-Zeile. Der Dialog nagelt die Reiterbreite
# beim Öffnen fest (`pin_notebook_width`), gemessen mit dem kurzen Status „Aus.“:
# ein längerer Text ohne Umbruch ragt sonst über den Rand (Fehlertext „Port … ist
# belegt“ um rund 60 px bei 100 %).
_WRAP_PX = 380
_STATUS_COLORS = {"ok": STATUS_OK, "muted": TEXT_MUTED, "error": STATUS_WARN}
_TOKEN_COLORS = {"ok": STATUS_OK, "muted": TEXT_MUTED}
_ROTATE_ERRORS = {
    "closed": "Die App wird gerade beendet.",
    "rotate_failed": ("Das neue Token konnte nicht geschrieben werden "
                      "(Zugriffsrechte des Datenordners?). Das bisherige Token "
                      "gilt weiter."),
}


class ApiTab:
    """Baut den API-Tab; Tab-Schnittstelle für den `SaveCoordinator`."""

    def __init__(self, frame, dialog, settings, api_service, runner):
        self.frame = frame
        self.title = "API"
        self._dialog = dialog
        self._settings = settings
        self._service = api_service
        self._runner = runner
        self._alive = True
        self._token_known = False
        self._busy = False                  # Rotation läuft
        self._notice = None                 # kurze Rückmeldung in der Token-Zeile
        self._last_state = None
        self._poll_id = None
        self._flash_id = None

        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        enabled_var = tk.BooleanVar(value=bool(settings.get("api_enabled")))
        port_var = tk.StringVar(value=str(settings.get("api_port")))
        self._enabled_var = enabled_var

        form.section("Lokale HTTP-API")
        form.hint("Andere Programme auf diesem Rechner (Skripte, Taskplaner, "
                  "Dashboards) können Zeiten lesen. Erreichbar nur von diesem "
                  "Rechner und nur mit Token.")
        form.check("Lokale API aktivieren", enabled_var)
        with form.depends_on(enabled_var):
            form.row("Port:", dark_entry(body, port_var, width=7))
            port_hint_label = form.hint(port_hint(port_var.get()))
        self._status_label = tk.Label(
            body, text="", font=FONT, bg=BG, fg=TEXT_MUTED, anchor="w",
            justify="left", wraplength=px(_WRAP_PX))
        form.row("Status:", self._status_label)
        with form.depends_on(enabled_var):
            self._token_label = tk.Label(
                body, text="", font=FONT, bg=BG, fg=TEXT_MUTED, anchor="w",
                justify="left", wraplength=px(_WRAP_PX))
            form.row("Token:", self._token_label)
        # Außerhalb der Gruppe (siehe Moduldocstring); Zustand: `_sync_buttons`.
        self._copy_btn, self._rotate_btn = form.buttons(
            ("Token kopieren", self._copy_token),
            ("Neu erzeugen …", self._rotate))
        with form.depends_on(enabled_var):
            example_label = form.hint(curl_example(port_var.get()))
        form.hint("Die API läuft nur, solange die App läuft — Autostart gibt es "
                  "im Tab „App“. Das Token verlässt diese Maske nur über die "
                  "Zwischenablage.")

        def _on_port(*_args):
            port_hint_label.config(text=port_hint(port_var.get()))
            example_label.config(text=curl_example(port_var.get()))

        port_var.trace_add("write", _on_port)
        enabled_var.trace_add("write", lambda *_args: self._sync_buttons())

        fields = FieldSet()
        fields.add("api_enabled", enabled_var)
        fields.add("api_port", port_var)
        self.fields = fields

        self._render_token_label()
        self._sync_buttons()
        frame.bind("<Destroy>", self._on_destroy, add="+")
        self._poll()                        # der erste Poll liest auch das Token

    # --- Tab-Schnittstelle --------------------------------------------------

    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return validate_api(self.values())

    def save(self):
        self._settings.apply_updates(api_updates(self.values()))
        return SaveOutcome(saved=True)

    # --- Anzeige ------------------------------------------------------------------

    def _on_destroy(self, event):
        if event.widget is not self.frame:
            return
        self._alive = False
        for after_id in (self._poll_id, self._flash_id):
            if after_id is not None:
                try:
                    self.frame.after_cancel(after_id)
                except tk.TclError:
                    pass                    # Fenster schon weg: nichts mehr zu stornieren

    def _poll(self):
        if not self._alive:
            return
        try:
            status = self._service.status
            text, kind = status_view(status)
            self._status_label.config(text=text, fg=_STATUS_COLORS[kind])
            if status.state != self._last_state:
                self._last_state = status.state
                self._refresh_token()       # das Token entsteht beim ersten Einschalten
            self._poll_id = self.frame.after(_POLL_MS, self._poll)
        except tk.TclError:
            self._alive = False             # Fenster zwischenzeitlich zu

    def _render_token_label(self):
        text, kind = token_label_view(token_known=self._token_known,
                                      notice=self._notice)
        self._token_label.config(text=text, fg=_TOKEN_COLORS[kind])

    def _sync_buttons(self):
        on = token_buttons_enabled(api_on=bool(self._enabled_var.get()),
                                   token_known=self._token_known, busy=self._busy)
        set_secondary_button_enabled(self._copy_btn, on)
        set_secondary_button_enabled(self._rotate_btn, on)

    def _refresh_token(self):
        self._runner.run(self._service.read_token, self._show_token)

    def _show_token(self, token):
        if not self._alive:
            return
        self._token_known = token is not None
        try:
            self._render_token_label()
            self._sync_buttons()
        except tk.TclError:
            self._alive = False

    def _flash(self, text):
        """Kurze Rückmeldung in der Token-Zeile; ein zweiter Aufruf ersetzt den
        ersten samt Timer."""
        if self._flash_id is not None:
            self.frame.after_cancel(self._flash_id)
        self._notice = text
        self._render_token_label()
        self._flash_id = self.frame.after(_FLASH_MS, self._clear_notice)

    def _clear_notice(self):
        self._flash_id = None
        if not self._alive:
            return
        self._notice = None
        try:
            self._render_token_label()
        except tk.TclError:
            self._alive = False

    # --- Aktionen -------------------------------------------------------------

    def _actions_allowed(self):
        return token_buttons_enabled(api_on=bool(self._enabled_var.get()),
                                     token_known=self._token_known, busy=self._busy)

    def _copy_token(self):
        if not self._actions_allowed():
            return
        self._runner.run(self._service.read_token, self._copy_to_clipboard)

    def _copy_to_clipboard(self, token):
        if not self._alive:
            return
        try:
            if token is None:               # Datei zwischenzeitlich weg
                themed_showinfo(self._dialog, "Kein Token",
                                "Es gibt gerade kein lesbares Token. „Neu erzeugen“ "
                                "legt ein neues an.")
                return
            self._dialog.clipboard_clear()
            self._dialog.clipboard_append(token)
            self._flash("In die Zwischenablage kopiert.")
        except tk.TclError:
            self._alive = False

    def _rotate(self):
        if not self._actions_allowed():
            return
        if not themed_askyesno(
                self._dialog, "Token neu erzeugen",
                "Alle Programme, die das bisherige Token benutzen, werden "
                "ausgesperrt und brauchen das neue.\n\nFortfahren?",
                lock_ms=600):
            return
        self._busy = True
        self._sync_buttons()
        self._runner.run(self._service.rotate, self._rotated)

    def _rotated(self, result):
        self._busy = False
        if not self._alive:
            return
        try:
            self._sync_buttons()
            if result.ok:
                self._refresh_token()
                self._flash("Token erneuert — alte Clients sind ausgesperrt.")
                return
            themed_showerror(
                self._dialog, "Token konnte nicht erneuert werden",
                _ROTATE_ERRORS.get(result.reason, "Unbekannter Fehler."))
        except tk.TclError:
            self._alive = False
