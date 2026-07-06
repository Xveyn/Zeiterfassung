"""Gemeinsame Grid-Helfer der Settings-Tabs (label/subheader)."""

import tkinter as tk
from typing import Any

from src.theme import BG, FONT, FONT_BOLD, TEXT, TEXT_MUTED


def label(parent_frame, text, row, col=0, **grid_kw):
    kw: dict[str, Any] = dict(padx=10, pady=8, sticky="w")
    kw.update(grid_kw)
    lbl = tk.Label(parent_frame, text=text, font=FONT, bg=BG, fg=TEXT)
    lbl.grid(row=row, column=col, **kw)
    return lbl


def subheader(parent_frame, text, row, top_pad=16):
    tk.Label(
        parent_frame, text=f"— {text} —", font=FONT_BOLD,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=row, column=0, columnspan=2, padx=10, pady=(top_pad, 4))
