"""Tk-freie Logik des Einstellungs-Dialogs (#132).

Hier entscheidet sich, ob ein Tab ungespeicherte Änderungen hat. PR 2 ergänzt
den `SaveCoordinator` (Speichern je Tab, Rückfrage beim Verlassen).
"""

import re
from collections.abc import Mapping
from typing import Any

# Nur schlichte Dezimalzahlen gelten als Zahl — "08:00", "nan" oder "1e3"
# bleiben Text. So wird aus einer Uhrzeit nie versehentlich eine Zahl.
_NUMBER = re.compile(r"-?\d+(\.\d+)?")


def normalize(value: Any) -> Any:
    """Vergleichsform eines Formularwerts.

    Ein Tk-Entry liefert Text, `settings.json` hält Zahlen: `"20"`, `20` und
    `20.0` sind derselbe gespeicherte Wert und dürfen nicht als Änderung
    zählen. Bools bleiben eigen (`True` ist hier nicht `1`), Zeilenenden
    werden vereinheitlicht (Tk-Text liefert `\\n`, eine alte Datei evtl.
    `\\r\\n`). Leerzeichen in Text bleiben signifikant — wer sie tippt,
    ändert etwas."""
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.replace("\r\n", "\n")
        stripped = text.strip()
        if _NUMBER.fullmatch(stripped):
            return float(stripped)
        return text
    if isinstance(value, Mapping):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    return value


def is_dirty(baseline: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    """True, wenn sich der Formularstand `current` vom gespeicherten Stand
    `baseline` unterscheidet (Vergleich über `normalize`). Ein fehlender oder
    zusätzlicher Schlüssel zählt als Änderung."""
    return normalize(baseline) != normalize(current)
