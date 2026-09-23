"""Tab „Updates": Update-Status, Changelog und Check-Häufigkeit."""

import logging
import os
import platform
import sys
import tempfile
import tkinter as tk
import webbrowser

from src.auto_update import manual_outcome
from src.changelog import (
    fetch_changelog_entry, parse_changelog_markdown, release_notes_for_display,
)
from src.dialogs.settings_dialog._shared import label
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import update_tab_updates
from src.self_update import (
    UpdateBlocked, apply_linux, apply_windows, discard_download,
    download_and_verify_update, download_dest, plan_update,
    supports_self_update, verify_file,
)
from src.theme import (
    BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL, TEXT, TEXT_MUTED,
    dark_combo, dark_text, primary_button, secondary_button,
    set_button_text, set_primary_button_enabled, set_secondary_button_enabled,
    themed_showerror,
)
from src.updater import (
    FREQUENCY_OPTIONS, REPO, check_for_update, pick_asset_url,
    resolve_check_result,
)
from src.version import installed_release_id


# Beschriftung der Changelog-Box. Ein Pre-Release hat bewusst KEINEN
# kuratierten Changelog-Eintrag — dort stehen die generierten Release-Notes,
# und die Box sagt das auch, statt "Changelog" zu behaupten.
_LABEL_CHANGELOG = "Changelog:"
_LABEL_PRERELEASE = "Enthaltene Änderungen:"

# Der Knopf heißt nur dort "Update installieren", wo die App das auch kann.
# Sonst bleibt es beim bisherigen Browser-Download.
_LABEL_INSTALL = "Update installieren"
_LABEL_DOWNLOAD = "Download"

_STATUS_READY = "Update bereit — wird beim Beenden installiert"


class UpdatesTab:
    """Baut den Updates-Tab; Tab-Schnittstelle für den `SaveCoordinator`
    (#132)."""

    def __init__(self, frame, settings, runner, auto_updater):
        self.frame = frame
        self._settings = settings
        self._runner = runner
        # Die Auto-Update-Policy der App, samt dem EINEN Guard für jeden
        # Update-Download (R9) — der Tab fährt keinen eigenen stillen Lauf.
        self._auto_updater = auto_updater
        self._latest_release = None
        self._checked = False
        self._checking = False
        self._updating = False

        # Damit die Changelog-Box (unten) breiter als ihr Zeichen-`width` sein
        # und sich mit gleichem Abstand links/rechts zentrieren kann, statt
        # links angepinnt zu bleiben und den Rest der Notebook-Tab-Breite
        # ungenutzt rechts stehen zu lassen.
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        label(frame, f"Installierte Version: {installed_release_id()}", row=0)

        self._status_label = tk.Label(
            frame, text="", font=FONT, bg=BG, fg=TEXT_MUTED,
        )
        self._status_label.grid(
            row=1, column=0, columnspan=2, padx=10, pady=4, sticky="w",
        )

        btn_row = tk.Frame(frame, bg=BG)
        btn_row.grid(row=2, column=0, columnspan=2, padx=10, pady=4, sticky="w")
        self._check_btn = primary_button(btn_row, "Jetzt prüfen", self._check_now)
        self._check_btn.pack(side=tk.LEFT)
        self._can_self_update = supports_self_update(
            platform.system(), getattr(sys, "frozen", False))
        self._download_btn = secondary_button(
            btn_row,
            _LABEL_INSTALL if self._can_self_update else _LABEL_DOWNLOAD,
            self._open_latest_download,
        )

        freq_row = tk.Frame(frame, bg=BG)
        freq_row.grid(row=3, column=0, columnspan=2, padx=10, pady=(12, 4), sticky="w")
        tk.Label(
            freq_row, text="Automatisch prüfen:", font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT, padx=(0, 8))
        current_frequency = settings.get("update_check_frequency")
        current_label = next(
            (lbl for value, lbl in FREQUENCY_OPTIONS if value == current_frequency),
            FREQUENCY_OPTIONS[0][1],
        )
        self.frequency_var = tk.StringVar(value=current_label)
        dark_combo(
            freq_row, self.frequency_var,
            [lbl for _, lbl in FREQUENCY_OPTIONS], width=14,
        ).pack(side=tk.LEFT)

        # Opt-in für Pre-Releases: ohne Häkchen verhält sich der Tab exakt wie
        # bisher (nur echte Releases über /releases/latest).
        self.prerelease_var = tk.BooleanVar(
            value=settings.get("prerelease_updates_enabled"),
        )
        tk.Checkbutton(
            frame, text="Auch Vorabversionen (Pre-Releases) anbieten",
            variable=self.prerelease_var, font=FONT, bg=BG, fg=TEXT,
            selectcolor=CELL_BG, activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
        ).grid(row=4, column=0, columnspan=2, padx=10, pady=(8, 0), sticky="w")
        tk.Label(
            frame, text="Testbuilds vor dem echten Release — können Fehler enthalten.",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).grid(row=5, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="w")

        # Nur bauen, wo Selbst-Update überhaupt möglich ist — ein Schalter
        # für ein Feature, das die Plattform nicht hat, ist Rauschen
        # (dieselbe Regel wie beim "Urlaub ausweisen"-Häkchen).
        self.auto_update_var = None
        if self._can_self_update:
            self.auto_update_var = tk.BooleanVar(
                value=bool(settings.get("auto_update_enabled")))
            tk.Checkbutton(
                frame, text="Updates automatisch installieren",
                variable=self.auto_update_var, font=FONT, bg=BG, fg=TEXT,
                selectcolor=CELL_BG, activebackground=BG, activeforeground=TEXT,
                cursor="hand2",
            ).grid(row=6, column=0, columnspan=2, padx=10, pady=(8, 0),
                   sticky="w")
            tk.Label(
                frame,
                text=("Lädt im Hintergrund und installiert beim nächsten "
                      "Beenden — nie mitten in der Arbeit."),
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
            ).grid(row=7, column=0, columnspan=2, padx=10, pady=(0, 4),
                   sticky="w")

        self.title = "Updates"
        fields = FieldSet()
        fields.add("update_check_frequency", self.frequency_var)
        fields.add("prerelease_updates_enabled", self.prerelease_var)
        if self.auto_update_var is not None:
            fields.add("auto_update_enabled", self.auto_update_var)
        self.fields = fields

        # Label + Text bleiben immer gegridded (nie grid_remove()) — sonst
        # verschwindet ihr Breitenbeitrag zum Notebook-Tab kurzzeitig während
        # eines Checks (Text leer/gecleart ist ok, ungegridded lässt die
        # ansonsten fixe Dialogbreite kurz einbrechen.
        self._changelog_label = tk.Label(
            frame, text=_LABEL_CHANGELOG, font=FONT, bg=BG, fg=TEXT,
        )
        self._changelog_label.grid(row=8, column=0, padx=10, pady=(12, 4), sticky="nw")
        self._changelog_text = dark_text(frame, 58, 12)
        self._changelog_text.grid(
            row=9, column=0, columnspan=2, padx=10, pady=4,
        )
        self._changelog_text.tag_configure("heading", font=FONT_BOLD)
        self._changelog_text.tag_configure("bold", font=FONT_BOLD)
        self._changelog_text.tag_configure("hanging_indent", lmargin1=0, lmargin2=20)
        self._changelog_text.config(state="disabled")

    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return None

    def save(self):
        self._settings.apply_updates(update_tab_updates(self.values()))
        return SaveOutcome(saved=True)

    def on_tab_selected(self):
        """Löst den Live-Check nur beim ersten Sichtbarwerden des Tabs aus."""
        if self._checked:
            return
        self._checked = True
        self._check_now()

    def _finish_checking(self):
        self._checking = False
        set_primary_button_enabled(self._check_btn, True)
        set_button_text(self._check_btn, "Jetzt prüfen")

    def _set_changelog(self, text):
        self._changelog_text.config(state="normal")
        self._changelog_text.delete("1.0", "end")
        for line in parse_changelog_markdown(text):
            if line is None:
                self._changelog_text.insert("end", "\n")
                continue
            line_start = self._changelog_text.index("end-1c")
            for segment_text, tags in line["segments"]:
                if tags:
                    self._changelog_text.insert("end", segment_text, tags)
                else:
                    self._changelog_text.insert("end", segment_text)
            if line["hanging_indent"]:
                self._changelog_text.tag_add("hanging_indent", line_start, "end-1c")
            self._changelog_text.insert("end", "\n")
        self._changelog_text.config(state="disabled")

    def _check_now(self):
        # self._updating: während ein Selbst-Update läuft (Download/Prüf-
        # /Installier-Phase), darf "Jetzt prüfen" nicht dazwischenfunken —
        # sonst leert es self._latest_release und _finish_checking() aktiviert
        # die Knöpfe wieder, obwohl das Update noch läuft.
        if self._checking or self._updating:
            return
        self._checking = True
        self._latest_release = None
        set_primary_button_enabled(self._check_btn, False)
        set_button_text(self._check_btn, "Prüfe…")
        self._status_label.config(text="Prüfe…")
        self._download_btn.pack_forget()
        # Zurücksetzen, sonst bliebe die Pre-Release-Beschriftung stehen,
        # wenn jemand das Häkchen abwählt und erneut prüft.
        self._changelog_label.config(text=_LABEL_CHANGELOG)
        self._set_changelog("")

        # Tk-Variable im UI-Thread lesen und als Wert in die Closure geben —
        # nie aus dem Daemon-Thread. Bewusst der AKTUELLE Checkbox-Zustand,
        # nicht der gespeicherte: sonst wirkt das Häkchen erst nach Speichern
        # und erneutem Öffnen des Dialogs.
        include_prereleases = bool(self.prerelease_var.get())

        def fn():
            return check_for_update(REPO, include_prereleases)

        def on_done(release):
            if not self.frame.winfo_exists():
                return
            result = resolve_check_result(installed_release_id(), release)
            self._latest_release = result["latest_release"]
            self._status_label.config(text=result["status_text"])
            if result["show_download"]:
                self._download_btn.pack(side=tk.LEFT, padx=(8, 0))
            if result["persist"]:
                self._settings.set_many(result["persist"])
            if self._latest_release is not None:
                # Derselbe Check, der den Nutzer über den Knopf informiert,
                # löst bei aktivem Häkchen zusätzlich den stillen
                # Hintergrund-Download aus — kein eigener Timer (Regel 1 aus
                # dem Design: "vorhandener Update-Check").
                self._maybe_start_auto_update(self._latest_release)
            if result["changelog_notes"] is not None:
                # Pre-Release: die Notes liegen dem Payload bereits bei,
                # kein zweiter Netzwerk-Call nötig. Es ist aber der
                # GENERIERTE Body, kein kuratierter Changelog-Eintrag —
                # `release_notes_for_display` lässt die reinen PR-Titel
                # stehen (Links und Autorenangaben nützen in einem
                # Text-Widget ohne Klick-Ziele nichts), und das Label
                # behauptet kein "Changelog".
                self._finish_checking()
                self._changelog_label.config(text=_LABEL_PRERELEASE)
                self._set_changelog(
                    release_notes_for_display(result["changelog_notes"]))
                return
            if result["changelog_version"] is None:
                self._finish_checking()
                return
            self._fetch_changelog(result["changelog_version"])

        self._runner.run(fn, on_done)

    def _fetch_changelog(self, version):
        def fn():
            return fetch_changelog_entry(REPO, version)

        def on_done(text):
            if not self.frame.winfo_exists():
                return
            self._finish_checking()
            self._set_changelog(text or "Changelog konnte nicht geladen werden.")

        self._runner.run(fn, on_done)

    def _open_latest_download(self):
        # `set_secondary_button_enabled` graut den Knopf nur optisch aus, die
        # Bindung feuert weiter (s. dessen Docstring) — der Guard hier ist
        # das, was einen zweiten Klick während des Downloads wirklich stoppt.
        if self._latest_release is None or self._updating:
            return
        if self._can_self_update:
            self._start_self_update(self._latest_release)
            return
        self._open_download(self._latest_release)

    def _maybe_start_auto_update(self, release):
        """Reicht den Check an die gemeinsame Auto-Update-Policy weiter
        (`auto_update.AutoUpdater`, R9) und zeigt deren Ausgang an.

        Geladen und geprüft wird dort — auch wenn der Start-Check der App
        schon lädt: dann hängt sich der Tab nur an dessen Fortschritt und
        Ausgang, statt selbst ein zweites Mal zu laden. Angewendet wird erst
        beim nächsten Beenden (`UpdateCoordinator._apply_pending_update`)."""
        outcome = self._auto_updater.maybe_start(
            release, on_progress=self._report_status,
            on_finished=self._on_auto_update_finished)
        if outcome == "pending":
            self._status_label.config(text=_STATUS_READY)
        elif outcome in ("started", "busy"):
            # Nur optisch (s. `set_secondary_button_enabled`) — ein Klick
            # landet trotzdem in `_start_self_update`, und dort stoppt ihn
            # der gemeinsame Guard.
            set_secondary_button_enabled(self._download_btn, False)

    def _on_auto_update_finished(self, ok):
        # Der Runner ist `App._bg` und überlebt den Dialog: persistiert hat
        # der AutoUpdater bereits, hier bleibt nur die Anzeige.
        if not self.frame.winfo_exists():
            return
        set_secondary_button_enabled(self._download_btn, True)
        self._status_label.config(
            text=_STATUS_READY if ok else
            "Automatischer Download fehlgeschlagen — neuer Versuch beim "
            "nächsten Check")

    def _report_status(self, text):
        """Fortschrittstext aus dem Worker-Thread in die Statuszeile."""
        # Nie direkt ans Widget. Analog App._marshal_to_ui (ui.py) werden
        # Einplanen UND Ausführen gegen TclError abgesichert: schließt der
        # Nutzer den Einstellungen-Dialog während des Downloads, existiert
        # self._status_label beim Feuern nicht mehr, und der TclError liefe
        # sonst ungefangen in Tkinters report_callback_exception — das dieses
        # Projekt global auf ein sichtbares Fehler-Popup legt
        # (logging_setup.py). Der Fortschritt feuert pro 1-MB-Chunk, bei
        # einem ~65-MB-Asset also dutzende Male, während der Download im
        # Hintergrund weiterläuft — ohne Guard dutzende Popups.
        def apply_text():
            try:
                self._status_label.config(text=text)
            except tk.TclError:
                pass  # Dialog schon zu, die Meldung hat kein Ziel mehr
        try:
            self.frame.after(0, apply_text)
        except tk.TclError:
            pass  # Dialog schon zu, das Einplanen selbst hat kein Ziel mehr

    def _start_self_update(self, release):
        """Laden, prüfen, installieren — der Ein-Klick-Weg.

        Reihenfolge mit Absicht: `plan_update` stellt ALLE Abbruchgründe
        fest, bevor ein Byte fliesst. Ein halb geladenes Update, das dann an
        einer Kleinigkeit scheitert, wäre die schlechtere Erfahrung.
        """
        plan = plan_update(
            release, platform.system(), platform.machine(),
            getattr(sys, "frozen", False),
            os.environ.get("APPIMAGE", ""), sys.executable)
        if isinstance(plan, UpdateBlocked):
            themed_showerror(self.frame, "Update nicht möglich", plan.reason)
            self._open_download(release)
            return

        if not self._auto_updater.acquire_manual():
            # Der stille Download (Start-Check der App oder dieser Tab) läuft
            # schon. Ein zweiter daneben liesse beim sofortigen Installieren
            # den halben stillen Download in %TEMP% zurück (R9).
            self._status_label.config(
                text="Update wird bereits im Hintergrund geladen …")
            return

        set_primary_button_enabled(self._check_btn, False)
        # ACHTUNG: `set_secondary_button_enabled` ändert laut seinem Docstring
        # NUR die Optik — die Klick-Bindung bleibt aktiv. Der Callback muss
        # deshalb selbst ein No-op machen, siehe `self._updating`-Guard oben in
        # `_open_latest_download`.
        set_secondary_button_enabled(self._download_btn, False)
        self._updating = True

        # Pro Lauf ein eigener Zielname (s. `download_dest`).
        local = download_dest(platform.system(), plan.asset_name, plan.target,
                              tempfile.gettempdir())

        # Laden+Prüfen ist gemeinsamer Kern mit dem stillen Automatik-Pfad
        # (`auto_update.AutoUpdater`) — beide rufen dieselbe Funktion in
        # self_update.py, damit die beiden Abläufe nicht auseinanderlaufen.
        def work():
            return download_and_verify_update(
                plan, local, on_progress=self._report_status)

        def done(result):
            self._auto_updater.release_manual()
            # `alive` statt eines frühen `return`: der Runner ist `App._bg`
            # und überlebt den Dialog — ein ~65-MB-Download läuft nach dem
            # Schliessen des Einstellungen-Dialogs fertig. Was dann mit der
            # Datei geschieht, entscheidet `manual_outcome`.
            ok = not isinstance(result, str)
            outcome = manual_outcome(ok, bool(self.frame.winfo_exists()))
            if outcome == "log":
                # `download_and_verify_update` hat seine Datei bereits selbst
                # weggeräumt, und für eine Meldung ist niemand mehr da.
                logging.getLogger(__name__).info(
                    "Update abgebrochen (Dialog bereits zu): %s", result)
                return
            if outcome == "show_error":
                self._fail_update(result)
                return
            if outcome == "discard":
                logging.getLogger(__name__).info(
                    "Update verworfen: der Dialog wurde während des "
                    "Downloads geschlossen")
                discard_download(result.path)
                return
            self._status_label.config(text="Installiere …")
            self._apply(plan, result.path, result.sha256)

        self._runner.run(work, done)

    def _fail_update(self, message):
        """Bricht den laufenden Update-Versuch ab: Guard und beide Knöpfe
        wieder hoch, Fehlermeldung zeigen.

        EIN Ausstiegspunkt für alle Fehlerpfade nach dem Setzen von
        `self._updating = True` (Download-/Prüf-Fehler in `done()` UND
        Anwenden-Fehler in `_apply`) — sonst bleibt der Guard in
        `_open_latest_download` für den Rest der Dialog-Session auf `True`
        hängen und blockt jeden weiteren Klick, während "Jetzt prüfen"
        zusätzlich optisch tot bliebe."""
        self._updating = False
        set_primary_button_enabled(self._check_btn, True)
        set_secondary_button_enabled(self._download_btn, True)
        self._status_label.config(text="Update fehlgeschlagen")
        themed_showerror(self.frame, "Update fehlgeschlagen", message)

    def _apply(self, plan, local, expected_sha256):
        """Anwenden und die App beenden bzw. neu starten.

        Erneut geprüft wird hier bewusst, UNMITTELBAR bevor installiert
        wird — dieselbe Prüfung wie in `UpdateCoordinator._apply_pending_update`, aus
        demselben Grund: unter Windows startet `apply_windows` den Helfer nur
        ab und beendet diesen Prozess sofort danach, installiert wird also
        asynchron, NACHDEM die App schon weg ist. Was zwischen Download-Ende
        und diesem Aufruf mit der Datei passiert ist (Aufräum-Tool,
        Virenscanner, jemand mit einem Editor), sieht sonst niemand mehr —
        und M9 verlangt, dass nur installiert wird, was geprüft ist.

        Was diese Prüfung ausdrücklich NICHT mehr abzuwehren hat, ist ein
        zeitgleicher stiller Automatik-Download: seit `download_dest` jedem
        Lauf einen eigenen Zielnamen gibt, können sich die beiden Wege gar
        nicht mehr in derselben Datei begegnen. Eine Prüfung hätte dieses
        Rennen ohnehin nie schließen können — sie liegt VOR dem
        Zeitfenster, nicht darin.
        """
        if not os.path.exists(local) or not verify_file(local, expected_sha256):
            discard_download(local)
            self._fail_update(
                "Die geladene Datei ist nicht mehr vorhanden oder wurde "
                "zwischenzeitlich verändert. Bitte erneut versuchen.")
            return

        # Ein vom Automatik-Lauf vorbereitetes Update wird HIER sofort
        # angewendet (Sofort-Ablauf gewinnt gegen "beim Beenden") — ohne
        # Aufräumen würde UpdateCoordinator._apply_pending_update beim nächsten
        # regulären Beenden dieselbe, längst installierte Datei erneut
        # anzuwenden versuchen.
        pending = self._settings.get("pending_update_path")
        if pending and pending != local:
            # Seit `download_dest` trägt jeder Lauf einen eigenen Namen: die
            # still vorbereitete Datei ist eine ANDERE als die eben geladene
            # und würde sonst als ~65-MB-Leiche liegen bleiben, weil sie
            # kein späterer Lauf mehr überschreibt.
            discard_download(pending)
        self._settings.set_many({"pending_update_path": "",
                                 "pending_update_sha256": ""})
        if platform.system() == "Windows":
            # restart=True: der Nutzer hat eben geklickt und will
            # weiterarbeiten (Gegenstück: der Beenden-Weg in ui.py).
            if not apply_windows(plan.target, local, os.getpid(), True):
                # Wie im apply_linux-Zweig unten: pending_update_* ist zwei
                # Zeilen weiter oben geleert, es gibt danach KEINE Referenz
                # mehr auf diese Datei — ohne Aufräumen bleiben ~65 MB
                # dauerhaft im %TEMP% (die Zusage steht im Docstring von
                # `download_dest`).
                discard_download(local)
                self._fail_update("Der Update-Helfer ließ sich nicht starten.")
                return
            self.frame.winfo_toplevel().quit()
            return

        error = apply_linux(plan.target, local)
        if error is not None:
            # Die heruntergeladene Datei blieb sonst neben der AppImage
            # liegen — halbe/nicht-übernommene Downloads bleiben in diesem
            # Projekt an keiner Stelle bewusst zurück (s. download_to,
            # verify_file oben).
            discard_download(local)
            self._fail_update(error)
            return
        os.execv(plan.target, [plan.target])

    def _open_download(self, release):
        url = pick_asset_url(
            release.assets, platform.system(), release.version,
            platform.machine(),
        ) or release.html_url
        webbrowser.open(url)
