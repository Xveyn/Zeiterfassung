"""Modal: welche OAuth-Scopes das Google-Konto der App gewährt hat (#120).

Read-only. Die Bewertung macht `mail.scope_overview`, gelesen wird über
`oauth_utils.read_granted_scopes` — hier passiert nur Rendering.

Bewusst ein Modal statt einer Liste im Google-Tab: der Tab ist mit 480 px
bereits der größte im Notebook (das alle Tabs auf diese Höhe zwingt), die
Liste inline kostete +156 px. Nebeneffekt: das Modal liest `token.json` beim
Öffnen und ist damit per Konstruktion immer frisch — kein Poll, keine
Invalidierung nach einem Re-Consent.
"""

import os
import tkinter as tk

from src.mail import scope_overview
from src.oauth_utils import read_granted_scopes
from src.theme import (
    ACCENT, BG, FONT, FONT_BOLD, FONT_SMALL, STATUS_OK, TEXT, TEXT_MUTED,
    center_dialog_on_parent, create_dialog, secondary_button,
)

# Zustand → (Zeichen, Farbe). Zeichen statt Farbe allein, damit die Liste
# auch ohne Farbwahrnehmung lesbar bleibt.
_MARKS = {
    "active": ("✓", STATUS_OK),
    "unused": ("○", TEXT_MUTED),
    "missing": ("✗", ACCENT),
}

_LEGEND = ("✓ gewährt und genutzt    ○ gewährt, zurzeit ungenutzt    "
           "✗ fehlt, wird neu angefragt")


def open_scopes_dialog(parent, settings, base_path):
    """Öffnet das Berechtigungs-Modal und liefert den Toplevel zurück."""
    token_path = os.path.join(base_path, "token.json")
    granted = read_granted_scopes(token_path)

    dialog = create_dialog(parent, "Berechtigungen")
    body = tk.Frame(dialog, bg=BG)
    body.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

    tk.Label(
        body, text="Berechtigungen des Google-Kontos", font=FONT_BOLD,
        bg=BG, fg=TEXT,
    ).pack(anchor="w", pady=(0, 8))

    if granted is None:
        message = (
            "Berechtigungen nicht lesbar."
            if os.path.exists(token_path)
            else "Noch nicht angemeldet — es sind keine Berechtigungen gewährt."
        )
        tk.Label(body, text=message, font=FONT, bg=BG, fg=TEXT_MUTED).pack(anchor="w")
    else:
        entries, extras = scope_overview(
            granted,
            settings.get("sync_enabled"),
            settings.get("gcal_enabled"),
        )
        for entry in entries:
            mark, color = _MARKS[entry.status]
            tk.Label(
                body, text=f"{mark}  {entry.label}", font=FONT, bg=BG, fg=color,
            ).pack(anchor="w", pady=(4, 0))
            tk.Label(
                body, text=f"     {entry.scope}", font=FONT_SMALL,
                bg=BG, fg=TEXT_MUTED,
            ).pack(anchor="w")

        if extras:
            tk.Label(
                body, text="Weitere Berechtigungen", font=FONT_BOLD,
                bg=BG, fg=TEXT,
            ).pack(anchor="w", pady=(12, 4))
            for scope in extras:
                tk.Label(
                    body, text=f"     {scope}", font=FONT_SMALL,
                    bg=BG, fg=TEXT_MUTED,
                ).pack(anchor="w")

        tk.Label(
            body, text=_LEGEND, font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(12, 0))

    secondary_button(body, "Schließen", dialog.destroy).pack(anchor="e", pady=(16, 0))

    center_dialog_on_parent(dialog, parent)
    return dialog
