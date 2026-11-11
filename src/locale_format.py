# pyright: reportOptionalMemberAccess=true
"""Datumsdarstellung je Locale (Sprache und Land zusammen).

Das Muster hängt an beidem: dieselbe Sprache schreibt in anderen Ländern
andere Reihenfolgen. Das Locale wird nie eingestellt, sondern aus
`language` und `country` abgeleitet (`locale_for`). ISO bleibt intern.
"""
from src.region import normalize_country, normalize_language

DEFAULT_LOCALE = "de-DE"

# Je Locale: Datum mit Jahr, Kurzform ohne Jahr und das Muster
# "Wochentag - Datum"; die Wochentagsnamen stehen daneben (Montag zuerst).
_PATTERNS: dict[str, dict[str, str]] = {
    "de-DE": {"date": "%d.%m.%Y", "short": "%d.%m.", "day_month": "{day}.{month}.",
              "weekday_date": "{weekday} - {date}"},
}
_WEEKDAYS: dict[str, list[str]] = {
    "de-DE": ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
              "Freitag", "Samstag", "Sonntag"],
}

_active = DEFAULT_LOCALE


def locale_for(language: object, country: object) -> str:
    """Locale-Tag wie "de-DE" aus Sprache und Land; Ungültiges ergibt
    `DEFAULT_LOCALE`, wirft nie."""
    return f"{normalize_language(language)}-{normalize_country(country)}"


def _entry(locale: str) -> dict[str, str]:
    return _PATTERNS.get(locale, _PATTERNS[DEFAULT_LOCALE])


def date_pattern(locale: str) -> str:
    """strftime-Muster für das Datum mit Jahr; unbekanntes Locale → Standard."""
    return _entry(locale)["date"]


def short_date_pattern(locale: str) -> str:
    """strftime-Muster für Tag und Monat ohne Jahr."""
    return _entry(locale)["short"]


def day_month_pattern(locale: str) -> str:
    """Muster mit den Platzhaltern {day} und {month}, ohne führende Nullen
    (`%-d` ginge unter Windows nicht)."""
    return _entry(locale)["day_month"]


def weekday_date_pattern(locale: str) -> str:
    """Muster mit den Platzhaltern {weekday} und {date}."""
    return _entry(locale)["weekday_date"]


def weekday_names(locale: str) -> list[str]:
    """Ausgeschriebene Wochentage, Montag zuerst."""
    return _WEEKDAYS.get(locale, _WEEKDAYS[DEFAULT_LOCALE])


def set_active(locale: str) -> None:
    global _active
    _active = locale


def active() -> str:
    return _active
