# pyright: reportOptionalMemberAccess=true
import logging
import time
from datetime import date
from functools import lru_cache

COUNTRIES: list[tuple[str, str]] = [("DE", "Deutschland")]

# Pro Land (Code, Anzeigename). Der Eintrag mit leerem Code markiert „keine
# Region gewählt": für dieses Land gilt dann „keine Feiertage". Ein Land ohne
# solchen Eintrag hat keine Unterteilung.
REGIONS: dict[str, list[tuple[str, str]]] = {
    "DE": [
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
    ],
}


def _valid_codes(country: str) -> set[str]:
    return {code for code, _ in REGIONS.get(country, []) if code}


def region_label(country: str, region: str) -> str:
    """Anzeigename der Region; "" bei unbekanntem Land oder Code."""
    return next((lbl for code, lbl in REGIONS.get(country, [])
                 if code == region), "")


def normalize_region(country: str, region: object) -> str:
    """Gültiger Regionscode des Landes, sonst "" (Fremddaten, wirft nie)."""
    if isinstance(region, str) and region in _valid_codes(country):
        return region
    return ""


@lru_cache(maxsize=64)
def _holidays_cached(country: str, region: str, year: int,
                     language: str) -> dict[date, str]:
    """Lädt die Feiertage über `holidays.country_holidays`. Im Onefile-Build
    kann die Übersetzungsdatei bei schnell aufeinanderfolgenden Prozessstarts
    (z.B. Neustart nach UI-Skalierung) transient noch nicht sichtbar sein —
    gettext wirft dann OSError statt still auf Englisch zurückzufallen
    (#116). Kurzer Retry deckt das ab; bleibt es dabei, greift derselbe
    Silent-Empty-Fallback wie bei ungültiger Region."""
    import holidays
    attempts = 3
    for attempt in range(attempts):
        try:
            return dict(holidays.country_holidays(
                country, subdiv=region, years=year, language=language))
        except OSError:
            if attempt == attempts - 1:
                logging.getLogger(__name__).warning(
                    "Feiertage für %s/%s/%s nicht ladbar (Übersetzungsdatei "
                    "transient nicht gefunden)", country, region, year,
                    exc_info=True)
                return {}
            time.sleep(0.2)
    return {}


def get_holidays(country: str, region: str, year: int,
                 language: str = "de") -> dict[date, str]:
    """Liefert {date: name} für Land, Region und Jahr.

    Leere oder ungültige Region (je Land) → leeres Dict, damit ein
    versehentlich falsch gespeicherter Code keinen Crash auslöst.

    Rückgabe ist immer ein frisches Dict; Mutationen durch Aufrufer können
    den internen Cache nicht vergiften.
    """
    if region not in _valid_codes(country):
        return {}
    return dict(_holidays_cached(country, region, year, language))
