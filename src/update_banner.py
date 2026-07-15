"""GitHub-Release-Hinweis als Banner über dem Kalender (anzeigen, Download
öffnen, ausblenden). Eigenständig herausgelöst aus der App (#49).

Tk-nutzend, aber ohne src.ui-Import (kein Circular-Import). Der Pack-Anker
(App.grid_container) wird lazy über get_anchor gelesen, weil er erst nach dem
Grid-Build existiert."""

import platform
import tkinter as tk
import webbrowser

from src.theme import ACCENT, ACCENT_HOVER, FONT_BOLD, label_button
from src.tooltip import attach_tooltip
from src.updater import pick_asset_url


class UpdateBanner:
    def __init__(self, root, settings, get_anchor, on_resize=lambda: None):
        self._root = root
        self._settings = settings
        self._get_anchor = get_anchor    # lambda: App.grid_container
        # Wird beim Ein-/Ausblenden aufgerufen, damit das fixe Fenster seine
        # Höhe an die geänderte Banner-Präsenz anpasst (sonst schneidet das
        # nicht-resizable Fenster den Footer ab, #92). Default no-op hält den
        # Banner unabhängig vom Renderer testbar.
        self._on_resize = on_resize
        self._banner = None              # Frame oder None (None = nicht sichtbar)

    def show_if_newer(self, release):
        """Zeigt den Banner, wenn `release` nicht bereits ausgeblendet wurde.

        Der Aufrufer hat bereits geprüft, dass `release` neuer als die
        installierte Version ist, und routet nur dann hierher, wenn kein
        aktiver Toast-Kanal verfügbar ist.
        """
        if release.version == self._settings.get("dismissed_version"):
            return
        self._show(release)

    def _show(self, release):
        if self._banner is not None:
            return
        self._banner = tk.Frame(self._root, bg=ACCENT)
        self._banner.pack(
            before=self._get_anchor(), fill=tk.X, padx=10, pady=(5, 0),
        )

        tk.Label(
            self._banner,
            text=f"Version {release.version} verfügbar",
            bg=ACCENT, fg="#ffffff", font=FONT_BOLD,
        ).pack(side=tk.LEFT, padx=10, pady=6)

        dismiss_btn = label_button(
            self._banner, "✕",
            lambda: self._dismiss(release.version),
            bg=ACCENT, fg="#ffffff",
            hover_bg=ACCENT_HOVER, hover_fg="#ffffff",
            font=FONT_BOLD,
            label_padx=8,
        )
        dismiss_btn.pack(side=tk.RIGHT, padx=(0, 4), pady=6)
        attach_tooltip(dismiss_btn, "Diese Version ausblenden")

        label_button(
            self._banner, "Download",
            lambda: self._open_download(release),
            bg="#ffffff", fg=ACCENT,
            hover_bg="#f0f0f0", hover_fg=ACCENT_HOVER,
            font=FONT_BOLD,
            label_padx=14, label_pady=2,
        ).pack(side=tk.RIGHT, padx=8, pady=4)

        # Der Banner sitzt zwischen Header und Grid und braucht zusätzliche
        # Höhe. Das Fenster ist fix (resizable(False, False)) und wächst nur
        # über einen kontrollierten Geometry-Pin — den hier anstoßen, sonst
        # läuft der Inhalt unten über und der Footer wird abgeschnitten (#92).
        self._on_resize()

    def _open_download(self, release):
        # M9 (bewusste Design-Grenze): Die App verifiziert das Update NICHT per
        # Hash/Signatur — sie lädt und startet aber auch nichts selbst, sondern
        # öffnet nur die Release-URL im Browser. Vertrauensanker ist damit TLS +
        # GitHub (der Nutzer lädt/installiert manuell). Ein späterer In-App-
        # Auto-Download OHNE Verifikation wäre eine echte Lücke — dann hier
        # Signatur-/Hash-Prüfung ergänzen.
        url = pick_asset_url(
            release.assets, platform.system(), release.version,
        ) or release.html_url
        webbrowser.open(url)

    def _dismiss(self, version):
        self._settings.set("dismissed_version", version)
        if self._banner is not None:
            self._banner.destroy()
            self._banner = None
        # Höhe zurückpinnen (Gegenstück zu _show): das fixe Fenster soll wieder
        # auf die Höhe ohne Banner schrumpfen.
        self._on_resize()
