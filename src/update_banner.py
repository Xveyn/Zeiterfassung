"""GitHub-Release-Hinweis als Banner über dem Kalender (anzeigen, Download
öffnen, ausblenden). Eigenständig herausgelöst aus der App (#49).

Tk-nutzend, aber ohne src.ui-Import (kein Circular-Import). Der Pack-Anker
(App.grid_container) wird lazy über get_anchor gelesen, weil er erst nach dem
Grid-Build existiert."""

import platform
import sys
import tkinter as tk
import webbrowser

from src.self_update import supports_self_update
from src.theme import ACCENT, ACCENT_HOVER, FONT_BOLD, label_button
from src.tooltip import attach_tooltip
from src.updater import pick_asset_url

# Beschriftung wie im Updates-Tab (tab_updates.py, Task 7): "Update
# installieren" nur dort, wo die App das Update auch selbst laden kann.
_LABEL_INSTALL = "Update installieren"
_LABEL_DOWNLOAD = "Download"


class UpdateBanner:
    def __init__(self, root, settings, get_anchor, on_resize=lambda: None,
                on_open_updates_tab=lambda: None):
        self._root = root
        self._settings = settings
        self._get_anchor = get_anchor    # lambda: App.grid_container
        # Wird beim Ein-/Ausblenden aufgerufen, damit das fixe Fenster seine
        # Höhe an die geänderte Banner-Präsenz anpasst (sonst schneidet das
        # nicht-resizable Fenster den Footer ab, #92). Default no-op hält den
        # Banner unabhängig vom Renderer testbar.
        self._on_resize = on_resize
        # Oeffnet den Einstellungen-Dialog auf dem Updates-Tab (aus ui.py
        # injiziert, wie die uebrigen Banner-Callbacks — der Banner
        # importiert src.ui bewusst nicht, s. src/CLAUDE.md). Default
        # no-op haelt den Banner unabhaengig von App testbar.
        self._open_updates_tab = on_open_updates_tab
        self._banner = None              # Frame oder None (None = nicht sichtbar)
        # True, waehrend der aktuell sichtbare Banner der "wird beim Beenden
        # installiert"-Zustand ist (statt der normalen "Version X
        # verfuegbar"-Meldung) — s. show_ready_to_install.
        self._ready_to_install = False
        # Einmalig ermittelt wie im Updates-Tab: aendert sich waehrend der
        # Laufzeit nicht (Plattform/Frozen-Status stehen beim Start fest).
        self._can_self_update = supports_self_update(
            platform.system(), getattr(sys, "frozen", False))

    def show_if_newer(self, release):
        """Zeigt den Banner, wenn `release` nicht bereits ausgeblendet wurde.

        Der Aufrufer hat bereits geprüft, dass `release` neuer als die
        installierte Version ist, und routet nur dann hierher, wenn kein
        aktiver Toast-Kanal verfügbar ist.
        """
        if release.release_id == self._settings.get("dismissed_version"):
            return
        self._show(release, ready_to_install=False)

    def show_ready_to_install(self, release):
        """Zeigt (oder aktualisiert) den Banner mit dem Hinweis, dass ein
        bereits geladenes und geprüftes Update beim nächsten Beenden
        installiert wird (Automatik-Schalter, injiziert aus `ui.py` — der
        Banner importiert `src.ui` weiterhin nicht).

        Ignoriert bewusst `dismissed_version`: ein Update, das gleich
        automatisch installiert wird, ist wichtiger als eine zuvor
        weggeklickte Verfügbarkeits-Meldung — niemand soll davon überrascht
        werden (Design-Regel 3, „sichtbar bleibt es trotzdem"). Ein bereits
        sichtbarer "normaler" Banner für dieselbe Version wird durch den
        Ready-Zustand ersetzt statt liegenzubleiben.
        """
        if self._banner is not None and self._ready_to_install:
            return  # schon im richtigen Zustand sichtbar
        if self._banner is not None:
            self._banner.destroy()
            self._banner = None
        self._show(release, ready_to_install=True)

    def _show(self, release, ready_to_install):
        if self._banner is not None:
            return
        self._ready_to_install = ready_to_install
        self._banner = tk.Frame(self._root, bg=ACCENT)
        self._banner.pack(
            before=self._get_anchor(), fill=tk.X, padx=10, pady=(5, 0),
        )

        if ready_to_install:
            text = "Update bereit — wird beim Beenden installiert"
        else:
            kind = "Vorabversion" if release.is_prerelease else "Version"
            text = f"{kind} {release.release_id} verfügbar"
        tk.Label(
            self._banner, text=text,
            bg=ACCENT, fg="#ffffff", font=FONT_BOLD,
        ).pack(side=tk.LEFT, padx=10, pady=6)

        dismiss_btn = label_button(
            self._banner, "✕",
            lambda: self._dismiss(release.release_id),
            bg=ACCENT, fg="#ffffff",
            hover_bg=ACCENT_HOVER, hover_fg="#ffffff",
            font=FONT_BOLD,
            label_padx=8,
        )
        dismiss_btn.pack(side=tk.RIGHT, padx=(0, 4), pady=6)
        attach_tooltip(dismiss_btn, "Diese Version ausblenden")

        if not ready_to_install:
            # Im Ready-Zustand gibt es nichts mehr zu klicken — das Update
            # laedt/installiert bereits automatisch, ein zweiter Ablaufpfad
            # waere hier fehl am Platz (dieselbe Regel wie in
            # _install_or_download unten).
            label_button(
                self._banner, _LABEL_INSTALL if self._can_self_update else _LABEL_DOWNLOAD,
                lambda: self._install_or_download(release),
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

    def _install_or_download(self, release):
        # Bewusst KEIN zweiter Ablaufpfad: der Banner hat weder Statuszeile
        # noch Fortschrittsanzeige. Er schickt den Nutzer dorthin, wo beides
        # steht — ein Klick mehr, aber nur EINE Stelle, die das Update fährt.
        if self._can_self_update:
            self._open_updates_tab()
            return
        self._open_download(release)

    def _open_download(self, release):
        # Fallback-Weg (macOS, unpassende Architektur, Repo-Modus): die App
        # oeffnet nur die URL, sie laedt und startet nichts selbst.
        #
        # M9 ist damit eingeloest, aber nur zur Haelfte weg: der In-App-Weg
        # (self_update.py) prueft JEDE geladene Datei gegen den SHA256SUMS des
        # Releases und installiert nichts Ungeprueftes. Was das leistet, steht
        # im Modul-Docstring dort — Schutz gegen kaputte Uebertragung, NICHT
        # gegen ein kompromittiertes Release; die Summen-Datei ist selbst
        # unsigniert. Vertrauensanker bleibt TLS zu GitHub.
        url = pick_asset_url(
            release.assets, platform.system(), release.version,
            platform.machine(),
        ) or release.html_url
        webbrowser.open(url)

    def _dismiss(self, release_id):
        self._settings.set("dismissed_version", release_id)
        if self._banner is not None:
            self._banner.destroy()
            self._banner = None
        # Höhe zurückpinnen (Gegenstück zu _show): das fixe Fenster soll wieder
        # auf die Höhe ohne Banner schrumpfen.
        self._on_resize()
