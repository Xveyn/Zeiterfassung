"""Tab „Updates": Update-Status, Changelog und Check-Häufigkeit."""

import platform
import tkinter as tk
import webbrowser

from src.changelog import fetch_changelog_entry
from src.dialogs.settings_dialog._shared import label
from src.theme import (
    BG, FONT, TEXT, TEXT_MUTED,
    dark_combo, dark_text, primary_button, secondary_button,
    set_button_text, set_primary_button_enabled,
)
from src.updater import (
    FREQUENCY_OPTIONS, REPO, check_latest_release, is_newer, pick_asset_url,
)
from src.version import VERSION


class UpdatesTab:
    """Baut den Updates-Tab und exponiert `frequency_var` für save_settings."""

    def __init__(self, frame, settings, runner):
        self.frame = frame
        self._settings = settings
        self._runner = runner
        self._latest_release = None
        self._checked = False
        self._checking = False

        label(frame, f"Installierte Version: {VERSION}", row=0)

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

        self._changelog_label = tk.Label(
            frame, text="Changelog:", font=FONT, bg=BG, fg=TEXT,
        )
        self._changelog_label.grid(row=4, column=0, padx=10, pady=(12, 4), sticky="nw")
        self._changelog_text = dark_text(frame, 50, 12)
        self._changelog_text.grid(
            row=5, column=0, columnspan=2, padx=10, pady=4, sticky="we",
        )
        self._changelog_text.config(state="disabled")
        self._set_changelog_visible(False)

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
        self._changelog_text.insert("1.0", text)
        self._changelog_text.config(state="disabled")

    def _set_changelog_visible(self, visible):
        if visible:
            self._changelog_label.grid()
            self._changelog_text.grid()
            return
        self._changelog_label.grid_remove()
        self._changelog_text.grid_remove()

    def _check_now(self):
        if self._checking:
            return
        self._checking = True
        self._latest_release = None
        set_primary_button_enabled(self._check_btn, False)
        set_button_text(self._check_btn, "Prüfe…")
        self._status_label.config(text="Prüfe…")
        self._download_btn.pack_forget()
        self._set_changelog_visible(False)
        self._set_changelog("")

        def fn():
            return check_latest_release(REPO)

        def on_done(release):
            if not self.frame.winfo_exists():
                return
            if release is None:
                self._finish_checking()
                self._status_label.config(text="Prüfung fehlgeschlagen — keine Verbindung?")
                return
            if not is_newer(VERSION, release.version):
                self._finish_checking()
                self._status_label.config(text=f"Du hast die aktuelle Version ({VERSION}).")
                return
            self._latest_release = release
            self._status_label.config(text=f"Version {release.version} verfügbar")
            self._download_btn.pack(side=tk.LEFT, padx=(8, 0))
            self._set_changelog_visible(True)
            self._settings.set_many({
                "dismissed_version": release.version,
                "update_toast_shown_version": release.version,
            })
            self._fetch_changelog(release.version)

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
        ) or release.html_url
        webbrowser.open(url)
