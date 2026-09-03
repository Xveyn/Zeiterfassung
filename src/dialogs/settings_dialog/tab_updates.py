"""Tab „Updates": Update-Status, Changelog und Check-Häufigkeit."""

import os
import platform
import sys
import tempfile
import tkinter as tk
import webbrowser

from src.changelog import (
    fetch_changelog_entry, parse_changelog_markdown, release_notes_for_display,
)
from src.dialogs.settings_dialog._shared import label
from src.self_update import (
    UpdateBlocked, apply_linux, apply_windows, download_to, fetch_text,
    linux_apply_paths, parse_sha256sums, plan_update, supports_self_update,
    verify_file,
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

# Der Knopf heisst nur dort "Update installieren", wo die App das auch kann.
# Sonst bleibt es beim bisherigen Browser-Download.
_LABEL_INSTALL = "Update installieren"
_LABEL_DOWNLOAD = "Download"


class UpdatesTab:
    """Baut den Updates-Tab und exponiert `frequency_var` für save_settings."""

    def __init__(self, frame, settings, runner):
        self.frame = frame
        self._settings = settings
        self._runner = runner
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

        # Label + Text bleiben immer gegridded (nie grid_remove()) — sonst
        # verschwindet ihr Breitenbeitrag zum Notebook-Tab kurzzeitig während
        # eines Checks (Text leer/gecleart ist ok, ungegridded lässt die
        # ansonsten fixe Dialogbreite kurz einbrechen.
        self._changelog_label = tk.Label(
            frame, text=_LABEL_CHANGELOG, font=FONT, bg=BG, fg=TEXT,
        )
        self._changelog_label.grid(row=6, column=0, padx=10, pady=(12, 4), sticky="nw")
        self._changelog_text = dark_text(frame, 58, 12)
        self._changelog_text.grid(
            row=7, column=0, columnspan=2, padx=10, pady=4,
        )
        self._changelog_text.tag_configure("heading", font=FONT_BOLD)
        self._changelog_text.tag_configure("bold", font=FONT_BOLD)
        self._changelog_text.tag_configure("hanging_indent", lmargin1=0, lmargin2=20)
        self._changelog_text.config(state="disabled")

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
        # self._updating: waehrend ein Selbst-Update laeuft (Download/Pruef-
        # /Installier-Phase), darf "Jetzt pruefen" nicht dazwischenfunken —
        # sonst leert es self._latest_release und _finish_checking() aktiviert
        # die Knoepfe wieder, obwohl das Update noch laeuft.
        if self._checking or self._updating:
            return
        self._checking = True
        self._latest_release = None
        set_primary_button_enabled(self._check_btn, False)
        set_button_text(self._check_btn, "Prüfe…")
        self._status_label.config(text="Prüfe…")
        self._download_btn.pack_forget()
        # Zuruecksetzen, sonst bliebe die Pre-Release-Beschriftung stehen,
        # wenn jemand das Haekchen abwaehlt und erneut prueft.
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
            if result["changelog_notes"] is not None:
                # Pre-Release: die Notes liegen dem Payload bereits bei,
                # kein zweiter Netzwerk-Call nötig. Es ist aber der
                # GENERIERTE Body, kein kuratierter Changelog-Eintrag —
                # `release_notes_for_display` laesst die reinen PR-Titel
                # stehen (Links und Autorenangaben nuetzen in einem
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
        # das, was einen zweiten Klick waehrend des Downloads wirklich stoppt.
        if self._latest_release is None or self._updating:
            return
        if self._can_self_update:
            self._start_self_update(self._latest_release)
            return
        self._open_download(self._latest_release)

    def _start_self_update(self, release):
        """Laden, pruefen, installieren — der Ein-Klick-Weg.

        Reihenfolge mit Absicht: `plan_update` stellt ALLE Abbruchgruende
        fest, bevor ein Byte fliesst. Ein halb geladenes Update, das dann an
        einer Kleinigkeit scheitert, waere die schlechtere Erfahrung.
        """
        plan = plan_update(
            release, platform.system(), platform.machine(),
            getattr(sys, "frozen", False),
            os.environ.get("APPIMAGE", ""), sys.executable)
        if isinstance(plan, UpdateBlocked):
            themed_showerror(self.frame, "Update nicht möglich", plan.reason)
            self._open_download(release)
            return

        set_primary_button_enabled(self._check_btn, False)
        # ACHTUNG: `set_secondary_button_enabled` aendert laut seinem Docstring
        # NUR die Optik — die Klick-Bindung bleibt aktiv. Der Callback muss
        # deshalb selbst ein No-op machen, siehe `self._updating`-Guard oben in
        # `_open_latest_download`.
        set_secondary_button_enabled(self._download_btn, False)
        self._updating = True

        if platform.system() == "Windows":
            local = os.path.join(tempfile.gettempdir(), plan.asset_name)
        else:
            # NEBEN die AppImage, nicht nach /tmp: `os.replace` ist nur
            # innerhalb desselben Dateisystems atomar, und /tmp ist auf vielen
            # Systemen ein eigenes (tmpfs).
            local = linux_apply_paths(plan.target)[0]

        def report(text):
            # Aus dem Worker-Thread: nie direkt ans Widget. Analog
            # App._marshal_to_ui (ui.py) werden Einplanen UND Ausfuehren
            # gegen TclError abgesichert: schliesst der Nutzer den
            # Einstellungen-Dialog waehrend des Downloads, existiert
            # self._status_label beim Feuern nicht mehr, und der TclError
            # liefe sonst ungefangen in Tkinters report_callback_exception —
            # das dieses Projekt global auf ein sichtbares Fehler-Popup legt
            # (logging_setup.py). progress() feuert pro 1-MB-Chunk, bei einem
            # ~65-MB-Asset also dutzende Male, waehrend der Download im
            # Hintergrund weiterlaeuft — ohne Guard dutzende Popups.
            def apply_text():
                try:
                    self._status_label.config(text=text)
                except tk.TclError:
                    pass  # Dialog schon zu, die Meldung hat kein Ziel mehr
            try:
                self.frame.after(0, apply_text)
            except tk.TclError:
                pass  # Dialog schon zu, das Einplanen selbst hat kein Ziel mehr

        def work():
            sums_text = fetch_text(plan.sums_url)
            if sums_text is None:
                return "Die Prüfsummen ließen sich nicht laden."
            expected = parse_sha256sums(sums_text).get(plan.asset_name)
            if not expected:
                return "Für diese Datei steht keine Prüfsumme im Release."

            def progress(done, total):
                pct = f"{done * 100 // total} %" if total else f"{done // 1024} KB"
                report(f"Lade {plan.asset_name} … {pct}")

            if not download_to(plan.asset_url, local, on_progress=progress):
                return "Der Download ist fehlgeschlagen."

            report("Prüfe Prüfsumme …")
            if not verify_file(local, expected):
                try:
                    os.remove(local)
                except OSError:
                    pass  # Loeschen ist best-effort; die Datei wird nicht benutzt
                return ("Die Prüfsumme der geladenen Datei stimmt nicht. "
                        "Die Datei wurde verworfen.")
            return None

        def done(error):
            if not self.frame.winfo_exists():
                return
            if error is not None:
                self._fail_update(error)
                return
            self._status_label.config(text="Installiere …")
            self._apply(plan, local)

        self._runner.run(work, done)

    def _fail_update(self, message):
        """Bricht den laufenden Update-Versuch ab: Guard und beide Knoepfe
        wieder hoch, Fehlermeldung zeigen.

        EIN Ausstiegspunkt fuer alle Fehlerpfade nach dem Setzen von
        `self._updating = True` (Download-/Pruef-Fehler in `done()` UND
        Anwenden-Fehler in `_apply`) — sonst bleibt der Guard in
        `_open_latest_download` fuer den Rest der Dialog-Session auf `True`
        haengen und blockt jeden weiteren Klick, waehrend "Jetzt pruefen"
        zusaetzlich optisch tot bliebe."""
        self._updating = False
        set_primary_button_enabled(self._check_btn, True)
        set_secondary_button_enabled(self._download_btn, True)
        self._status_label.config(text="Update fehlgeschlagen")
        themed_showerror(self.frame, "Update fehlgeschlagen", message)

    def _apply(self, plan, local):
        """Anwenden und die App beenden bzw. neu starten."""
        if platform.system() == "Windows":
            if not apply_windows(plan.target, local, os.getpid()):
                self._fail_update("Der Update-Helfer ließ sich nicht starten.")
                return
            self.frame.winfo_toplevel().quit()
            return

        error = apply_linux(plan.target, local)
        if error is not None:
            # Die heruntergeladene Datei blieb sonst neben der AppImage
            # liegen — halbe/nicht-uebernommene Downloads bleiben in diesem
            # Projekt an keiner Stelle bewusst zurueck (s. download_to,
            # verify_file oben).
            try:
                os.remove(local)
            except OSError:
                pass  # nichts angelegt oder schon weg — beides in Ordnung
            self._fail_update(error)
            return
        os.execv(plan.target, [plan.target])

    def _open_download(self, release):
        url = pick_asset_url(
            release.assets, platform.system(), release.version,
            platform.machine(),
        ) or release.html_url
        webbrowser.open(url)
