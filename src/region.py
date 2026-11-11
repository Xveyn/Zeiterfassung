# pyright: reportOptionalMemberAccess=true
"""Land und Region aus den Einstellungen; einmalige Übernahme von `state`."""
from typing import Any, Protocol

from src.holidays_region import COUNTRIES, normalize_region

MIGRATED_KEY = "region_migrated"
DEFAULT_COUNTRY = "DE"
DEFAULT_LANGUAGE = "de"
LANGUAGES = ("de",)


class _Readable(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...


class _Writable(_Readable, Protocol):
    def set_many(self, updates: dict[str, Any]) -> None: ...


def normalize_country(value: object) -> str:
    """Gültiger Ländercode, sonst "DE" (Fremddaten, wirft nie)."""
    if isinstance(value, str) and value in {c for c, _ in COUNTRIES}:
        return value
    return DEFAULT_COUNTRY


def normalize_language(value: object) -> str:
    """Unterstützte Sprache, sonst "de" (Fremddaten, wirft nie)."""
    if isinstance(value, str) and value in LANGUAGES:
        return value
    return DEFAULT_LANGUAGE


def country_region(settings: _Readable) -> tuple[str, str]:
    country = normalize_country(settings.get("country"))
    return country, normalize_region(country, settings.get("region"))


def migrate_state(settings: _Writable) -> bool:
    """Übernimmt `state` als `region` (Land DE); `state` bleibt unberührt.

    Mit gesetztem Marker nur noch bei Abweichung: die App spiegelt `state`
    für Deutschland selbst aus `region`, ein Unterschied stammt also von einer
    älteren Version, die nur `state` ändert — dann gilt `state`. Ein
    unlesbarer `state` lässt eine gute `region` stehen. True bei Änderung."""
    if settings.get(MIGRATED_KEY) is True:
        if normalize_country(settings.get("country")) != DEFAULT_COUNTRY:
            return False
        state = normalize_region(DEFAULT_COUNTRY, settings.get("state"))
        if not state or state == settings.get("region"):
            return False
        settings.set_many({"region": state})
        return True
    settings.set_many({
        "country": DEFAULT_COUNTRY,
        "region": normalize_region(DEFAULT_COUNTRY, settings.get("state")),
        MIGRATED_KEY: True,
    })
    return True
