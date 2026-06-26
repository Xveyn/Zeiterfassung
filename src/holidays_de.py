from datetime import date
from functools import lru_cache

# Code-Label-Paare. Reihenfolge alphabetisch nach Klartext-Label.
STATES: list[tuple[str, str]] = [
    ("", "— kein Bundesland —"),
    ("BW", "Baden-Württemberg"),
    ("BY", "Bayern"),
    ("BE", "Berlin"),
    ("BB", "Brandenburg"),
    ("HB", "Bremen"),
    ("HH", "Hamburg"),
    ("HE", "Hessen"),
    ("MV", "Mecklenburg-Vorpommern"),
    ("NI", "Niedersachsen"),
    ("NW", "Nordrhein-Westfalen"),
    ("RP", "Rheinland-Pfalz"),
    ("SL", "Saarland"),
    ("SN", "Sachsen"),
    ("ST", "Sachsen-Anhalt"),
    ("SH", "Schleswig-Holstein"),
    ("TH", "Thüringen"),
]

_VALID_CODES = {code for code, _ in STATES if code}


def code_for_state_label(label: str) -> str:
    """Mappt ein im Settings-Dialog gewähltes State-Klartext-Label (z.B.
    "Bayern") zurück auf den Bundesland-Code ("BY"). Unbekanntes Label oder die
    "— kein Bundesland —"-Option → "" (kein Bundesland)."""
    return next((code for code, lbl in STATES if lbl == label), "")


@lru_cache(maxsize=64)
def _holidays_cached(state_code: str, year: int) -> dict[date, str]:
    import holidays
    return dict(holidays.Germany(subdiv=state_code, years=year, language="de"))


def get_holidays(state_code: str, year: int) -> dict[date, str]:
    """Liefert {date: name} für gewähltes Bundesland und Jahr.

    Leerer oder ungültiger Code → leeres Dict (silent fallback,
    damit ein versehentlich falsch gespeicherter Code keinen Crash auslöst).

    Rückgabe ist immer ein frisches Dict; Mutationen durch Aufrufer können
    den internen Cache nicht vergiften.
    """
    if state_code not in _VALID_CODES:
        return {}
    return dict(_holidays_cached(state_code, year))
