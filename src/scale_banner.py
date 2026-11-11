"""Hinweis-Banner „Skalierung passt nicht zum Monitor“ mit Neustart-Knopf
(Xveyn#201). Gleicher Pack-Anker und gleiche Optik wie der Update-Banner;
neu gestartet wird nie von selbst, der Nutzer entscheidet."""

import tkinter as tk

from src.i18n import t
from src.theme import ACCENT, ACCENT_HOVER, FONT_BOLD, label_button


class ScaleBanner:
    def __init__(self, root, get_anchor, on_restart, on_resize=lambda: None):
        self._root = root
        self._get_anchor = get_anchor    # lambda: App.grid_container
        self._on_restart = on_restart
        # Das fixe Fenster braucht beim Ein-/Ausblenden neu gepinnte Höhe
        # (wie beim Update-Banner, #92).
        self._on_resize = on_resize
        self._banner = None

    def set_visible(self, visible):
        if visible:
            self._show()
        else:
            self._hide()

    def _show(self):
        if self._banner is not None:
            return
        self._banner = tk.Frame(self._root, bg=ACCENT)
        self._banner.pack(
            before=self._get_anchor(), fill=tk.X, padx=10, pady=(5, 0))
        tk.Label(
            self._banner,
            text=t("skalierung.banner"),
            bg=ACCENT, fg="#ffffff", font=FONT_BOLD,
        ).pack(side=tk.LEFT, padx=10, pady=6)
        label_button(
            self._banner, t("skalierung.neu_starten"), self._on_restart,
            bg="#ffffff", fg=ACCENT,
            hover_bg="#f0f0f0", hover_fg=ACCENT_HOVER,
            font=FONT_BOLD, label_padx=14, label_pady=2,
        ).pack(side=tk.RIGHT, padx=8, pady=4)
        self._on_resize()

    def _hide(self):
        if self._banner is None:
            return
        self._banner.destroy()
        self._banner = None
        self._on_resize()
