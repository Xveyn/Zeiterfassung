"""Tab „API" (#92): lokale HTTP-API ein-/ausschalten, Port, Status und Token.

Schalter und Port sind Formularfelder (Speichern je Tab, `SaveCoordinator`);
„Token kopieren" und „Neu erzeugen" sind Aktionen, die sofort wirken. Beide
blockieren (Dateizugriff, unter Windows `icacls`) und laufen deshalb über den
`BackgroundTaskRunner`. Der Status kommt per Poll aus `ApiService.status`: das
`on_status`-Callback kann nach dem Schließen des Dialogs zurückkommen, ein
`after`-Poll, der mit dem Tab stirbt, nicht.

Das Token wird nie angezeigt, nur in die Zwischenablage kopiert.
"""

import tkinter as tk

from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    api_updates, curl_example, port_hint, status_view, validate_api,
)
from src.theme import (
    BG, FONT, STATUS_OK, STATUS_WARN, TEXT_MUTED, Form, dark_entry,
    set_secondary_button_enabled, themed_askyesno, themed_showerror,
    themed_showinfo,
)

_POLL_MS = 500
_FLASH_MS = 2500
_MASK = "•" * 24
_NO_TOKEN = "Wird beim ersten Einschalten erzeugt."
_STATUS_COLORS = {"ok": STATUS_OK, "muted": TEXT_MUTED, "error": STATUS_WARN}
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
        # `set_secondary_button_enabled` dämpft nur die Optik, der Callback bleibt
        # gebunden: Doppelklicks fängt der Tab selbst ab.
        self._busy = False
        self._last_state = None

        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        enabled_var = tk.BooleanVar(value=bool(settings.get("api_enabled")))
        port_var = tk.StringVar(value=str(settings.get("api_port")))

        form.section("Lokale HTTP-API")
        form.hint("Andere Programme auf diesem Rechner (Skripte, Taskplaner, "
                  "Dashboards) können Zeiten lesen. Erreichbar nur von diesem "
                  "Rechner und nur mit Token.")
        form.check("Lokale API aktivieren", enabled_var)
        with form.depends_on(enabled_var):
            form.row("Port:", dark_entry(body, port_var, width=7))
            port_hint_label = form.hint(port_hint(port_var.get()))
        self._status_label = tk.Label(body, text="", font=FONT, bg=BG,
                                      fg=TEXT_MUTED, anchor="w", justify="left")
        form.row("Status:", self._status_label)
        with form.depends_on(enabled_var):
            self._token_label = tk.Label(body, text=_MASK, font=FONT, bg=BG,
                                         fg=TEXT_MUTED, anchor="w")
            form.row("Token:", self._token_label)
            self._copy_btn, self._rotate_btn = form.buttons(
                ("Token kopieren", self._copy_token),
                ("Neu erzeugen …", self._rotate))
            example_label = form.hint(curl_example(port_var.get()))
        form.hint("Die API läuft nur, solange die App läuft — Autostart gibt es "
                  "im Tab „App“. Das Token verlässt diese Maske nur über die "
                  "Zwischenablage.")

        def _on_port(*_args):
            port_hint_label.config(text=port_hint(port_var.get()))
            example_label.config(text=curl_example(port_var.get()))

        port_var.trace_add("write", _on_port)

        fields = FieldSet()
        fields.add("api_enabled", enabled_var)
        fields.add("api_port", port_var)
        self.fields = fields

        frame.bind("<Destroy>", self._on_destroy, add="+")
        self._poll()
        self._refresh_token()

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

    # --- Status und Token ---------------------------------------------------

    def _on_destroy(self, event):
        if event.widget is self.frame:
            self._alive = False

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
            self.frame.after(_POLL_MS, self._poll)
        except tk.TclError:
            self._alive = False             # Fenster zwischenzeitlich zu

    def _refresh_token(self):
        self._runner.run(self._service.read_token, self._show_token)

    def _show_token(self, token):
        if not self._alive:
            return
        self._token_known = token is not None
        try:
            self._token_label.config(text=_MASK if self._token_known else _NO_TOKEN)
            set_secondary_button_enabled(self._copy_btn, self._token_known)
        except tk.TclError:
            self._alive = False

    def _flash(self, text):
        """Kurze Rückmeldung in der Token-Zeile, danach wieder die Maske."""
        self._token_label.config(text=text, fg=STATUS_OK)
        self.frame.after(_FLASH_MS, self._restore_token_label)

    def _restore_token_label(self):
        if not self._alive:
            return
        try:
            self._token_label.config(
                text=_MASK if self._token_known else _NO_TOKEN, fg=TEXT_MUTED)
        except tk.TclError:
            self._alive = False

    # --- Aktionen -------------------------------------------------------------

    def _copy_token(self):
        if self._busy or not self._token_known:
            return
        self._runner.run(self._service.read_token, self._copy_to_clipboard)

    def _copy_to_clipboard(self, token):
        if not self._alive:
            return
        try:
            if token is None:
                themed_showinfo(self._dialog, "Noch kein Token",
                                "Das Token entsteht beim ersten Einschalten der API.")
                return
            self._dialog.clipboard_clear()
            self._dialog.clipboard_append(token)
            self._flash("In die Zwischenablage kopiert.")
        except tk.TclError:
            self._alive = False

    def _rotate(self):
        if self._busy:
            return
        if not themed_askyesno(
                self._dialog, "Token neu erzeugen",
                "Alle Programme, die das bisherige Token benutzen, werden "
                "ausgesperrt und brauchen das neue.\n\nFortfahren?",
                lock_ms=600):
            return
        self._busy = True
        set_secondary_button_enabled(self._rotate_btn, False)
        set_secondary_button_enabled(self._copy_btn, False)
        self._runner.run(self._service.rotate, self._rotated)

    def _rotated(self, result):
        self._busy = False
        if not self._alive:
            return
        try:
            set_secondary_button_enabled(self._rotate_btn, True)
            if result.ok:
                self._refresh_token()           # stellt „Kopieren" wieder her
                self._flash("Token erneuert — alte Clients sind ausgesperrt.")
                return
            set_secondary_button_enabled(self._copy_btn, self._token_known)
            themed_showerror(
                self._dialog, "Token konnte nicht erneuert werden",
                _ROTATE_ERRORS.get(result.reason, "Unbekannter Fehler."))
        except tk.TclError:
            self._alive = False
