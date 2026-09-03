"""Tab „Updates": Update-Status, Changelog und Check-Häufigkeit."""

import platform
import tkinter as tk
import webbrowser

from src.changelog import (
    fetch_changelog_entry, parse_changelog_markdown, release_notes_for_display,
)
from src.dialogs.settings_dialog._shared import label
from src.theme import (
    BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL, TEXT, TEXT_MUTED,
    dark_combo, dark_text, primary_button, secondary_button,
    set_button_text, set_primary_button_enabled,
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


class UpdatesTab:
    """Baut den Updates-Tab und exponiert `frequency_var` für save_settings."""

    def __init__(self, frame, settings, runner):
        self.frame = frame
        self._settings = settings
        self._runner = runner
        self._latest_release = None
        self._checked = False
        self._checking = False

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
        self._download_btn = secondary_button(
            btn_row, "Download", self._open_latest_download,
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
        if self._checking:
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
        if self._latest_release is None:
            return
        self._open_download(self._latest_release)

    def _open_download(self, release):
        url = pick_asset_url(
            release.assets, platform.system(), release.version,
            platform.machine(),
        ) or release.html_url
        webbrowser.open(url)
