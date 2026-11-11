# pyright: reportOptionalMemberAccess=true
import logging
import time
from datetime import date
from functools import lru_cache

from src.i18n import N_, t

# Pro Land (Code, Schlüssel des Anzeigenamens); der Name wird beim Anzeigen
# aufgelöst (`country_choices`), nie beim Import.
COUNTRIES: list[tuple[str, str]] = [("DE", N_("land.de"))]

# Pro Land (Code, Schlüssel des Anzeigenamens; `region_choices` löst auf). Der
# Eintrag mit leerem Code markiert „keine Region gewählt": für dieses Land
# gilt dann „keine Feiertage". Ein Land ohne solchen Eintrag hat keine
# Unterteilung.
REGIONS: dict[str, list[tuple[str, str]]] = {
    "DE": [
        ("", N_("region.de_keine")),
        ("BW", N_("region.de_bw")),
        ("BY", N_("region.de_by")),
        ("BE", N_("region.de_be")),
        ("BB", N_("region.de_bb")),
        ("HB", N_("region.de_hb")),
        ("HH", N_("region.de_hh")),
        ("HE", N_("region.de_he")),
        ("MV", N_("region.de_mv")),
        ("NI", N_("region.de_ni")),
        ("NW", N_("region.de_nw")),
        ("RP", N_("region.de_rp")),
        ("SL", N_("region.de_sl")),
        ("SN", N_("region.de_sn")),
        ("ST", N_("region.de_st")),
        ("SH", N_("region.de_sh")),
        ("TH", N_("region.de_th")),
    ],
}


# Tabellen für die Auflösung (Schlüssel bleiben Literale an den `N_`-Stellen oben).
_COUNTRY_KEYS = dict(COUNTRIES)
_REGION_KEYS = {(country, code): key
                for country, entries in REGIONS.items() for code, key in entries}


def country_choices() -> list[tuple[str, str]]:
    """(Code, Anzeigename) der Länder in der aktuellen Sprache."""
    return [(code, t(_COUNTRY_KEYS[code])) for code in _COUNTRY_KEYS]


def country_label(country: str) -> str:
    """Anzeigename des Landes; "" bei unbekanntem Code."""
    return next((lbl for code, lbl in country_choices() if code == country), "")


def region_choices(country: str) -> list[tuple[str, str]]:
    """(Code, Anzeigename) der Regionen des Landes in der aktuellen Sprache;
    leer bei einem Land ohne Unterteilung."""
    return [(code, t(_REGION_KEYS[(country, code)]))
            for code, _ in REGIONS.get(country, [])]


def _valid_codes(country: str) -> set[str]:
    return {code for code, _ in REGIONS.get(country, []) if code}


def region_label(country: str, region: str) -> str:
    """Anzeigename der Region; "" bei unbekanntem Land oder Code."""
    return next((lbl for code, lbl in region_choices(country)
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
