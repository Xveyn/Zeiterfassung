# pyright: reportOptionalMemberAccess=true
"""Planung der Krankheitstage — rein, ohne Tk und ohne I/O.

Grundlage der vorbelegten Stunden (`sick_hours_basis`, synchronisiert):
die Standardzeit des Wochentags oder der Durchschnitt der letzten 3 Monate.
"""

from __future__ import annotations

BASES = ("standard", "average_3m")
DEFAULT_BASIS = "standard"

BASIS_LABELS = {
    "standard": "Standardzeit des Wochentags",
    "average_3m": "Durchschnitt der letzten 3 Monate",
}


def normalize_basis(value: object) -> str:
    """Unbrauchbare Werte (auch aus dem Sync) gelten als `standard`."""
    if isinstance(value, str) and value in BASES:
        return value
    return DEFAULT_BASIS
