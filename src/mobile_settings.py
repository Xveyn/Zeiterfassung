"""Einstellungen im Abgleich mit dem Handy (PWA-Einstellungen), Tk-frei und ohne I/O.

Das Handy darf genau zwei Einstellungen setzen: `categories` und `category_times`. Der Teil
`settings` der Anfrage ist **Fremddaten** und wird strikt geprüft (`parse_settings`); den Merge
macht `sync.merge` wie zwischen zwei Desktops. Hier liegen außerdem die Helfer, mit denen die
Antwort die Standardzeiten bereinigt (`clean_category_times`).

Der Fehler ist ein `SettingsError`, den `mobile_sync` in `SyncError(422, "invalid_entry", …)`
übersetzt (ein eigener Code brauchte einen Eintrag in `pwa/test/fixtures/errors.json`)."""
from __future__ import annotations

import datetime
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from src.settings import WEEKDAY_KEYS

SETTING_KEYS = ("categories", "category_times")
MAX_CATEGORIES = 100
MAX_CATEGORY_NAME = 100
MAX_DEFAULT_PAUSE = 24 * 60

_CLOCK_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
_ECHO_MAX = 40


class SettingsError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def clock(value: Any) -> str:
    return value if isinstance(value, str) and _CLOCK_RE.fullmatch(value) else ""


def pause(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        minutes = int(value)
    except ValueError:
        return None
    return minutes if 0 <= minutes <= MAX_DEFAULT_PAUSE else None


def clean_category_times(entry: Any) -> dict[str, Any]:
    """Eine Kategorie aus `category_times` (Form: `category_defaults`), auf gültige Felder
    reduziert. Ein fehlendes oder ungültiges Feld fehlt in der Antwort — die PWA greift dann
    wie der Desktop auf den globalen Standard zurück."""
    if not isinstance(entry, dict):
        return {}
    out: dict[str, Any] = {}
    if entry.get("mode") == "per_day":
        out["mode"] = "per_day"
        days = entry.get("days")
        clean_days: dict[str, dict[str, str]] = {}
        for key in WEEKDAY_KEYS:
            day = days.get(key) if isinstance(days, dict) else None
            if isinstance(day, dict):
                clean_days[key] = {f: t for f in ("start", "end") if (t := clock(day.get(f)))}
        out["days"] = clean_days
    else:
        out.update({f: t for f in ("start", "end") if (t := clock(entry.get(f)))})
    minutes = pause(entry.get("pause"))
    if minutes is not None:
        out["pause"] = minutes
    return out


def _label(text: object) -> str:
    # `ascii()` escaped auch Surrogate: die Meldung bleibt als UTF-8 schreibbar.
    return ascii(text)[1:-1][:_ECHO_MAX]


def _name(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise SettingsError(f"{where}: Namen müssen Text sein.")
    name = value.strip()
    if not name:
        raise SettingsError(f"{where}: Namen dürfen nicht leer sein.")
    if len(name) > MAX_CATEGORY_NAME:
        raise SettingsError(f"{where}: Namen dürfen höchstens {MAX_CATEGORY_NAME} Zeichen haben.")
    # Cc: Steuerzeichen; Cs: Surrogate. Ein einzelnes Surrogat ließe sich nicht als UTF-8
    # schreiben und machte jedes spätere Speichern der Einstellungen unmöglich.
    if any(unicodedata.category(ch) in ("Cc", "Cs") for ch in name):
        raise SettingsError(f"{where}: Namen dürfen keine Steuerzeichen oder ungültigen Unicode-Zeichen enthalten.")
    return name


def _parse_categories(value: object) -> list[str]:
    where = "Einstellung categories"
    if not isinstance(value, list):
        raise SettingsError(f"{where}: muss eine Liste sein.")
    if len(value) > MAX_CATEGORIES:
        raise SettingsError(f"{where}: höchstens {MAX_CATEGORIES} Kategorien.")
    names: list[str] = []
    for item in value:
        name = _name(item, where)
        if name in names:
            raise SettingsError(f"{where}: {_label(name)} kommt doppelt vor.")
        names.append(name)
    return names


def _time_field(value: object, where: str, label: str) -> str:
    if not isinstance(value, str) or not _CLOCK_RE.fullmatch(value):
        raise SettingsError(f"{where}: {label} muss genau HH:MM sein.")
    return value


def _clocks(raw: object, where: str, allowed: tuple[str, ...] = ("start", "end")) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise SettingsError(f"{where}: muss ein Objekt sein.")
    unknown = sorted(str(key)[:_ECHO_MAX] for key in raw if key not in allowed)
    if unknown:
        raise SettingsError(f"{where}: unbekannte Felder {unknown[:5]}.")
    return {field: _time_field(raw[field], where, field) for field in allowed if field in raw}


def _parse_category_times(value: object) -> dict[str, dict[str, Any]]:
    where = "Einstellung category_times"
    if not isinstance(value, dict):
        raise SettingsError(f"{where}: muss ein Objekt sein.")
    if len(value) > MAX_CATEGORIES:
        raise SettingsError(f"{where}: höchstens {MAX_CATEGORIES} Kategorien.")
    out: dict[str, dict[str, Any]] = {}
    for raw_name, raw in value.items():
        name = _name(raw_name, where)
        if name in out:      # zwei Schlüssel, die nach dem Trimmen gleich sind (wie bei `categories`)
            raise SettingsError(f"{where}: {_label(name)} kommt doppelt vor.")
        entry_where = f"{where} {_label(name)}"
        if not isinstance(raw, dict):
            raise SettingsError(f"{entry_where}: Eintrag muss ein Objekt sein.")
        entry: dict[str, Any]
        if raw.get("mode") == "per_day":
            unknown = sorted(str(key)[:_ECHO_MAX] for key in raw if key not in ("mode", "days", "pause"))
            if unknown:
                raise SettingsError(f"{entry_where}: unbekannte Felder {unknown[:5]}.")
            days_raw = raw.get("days", {})
            if not isinstance(days_raw, dict):
                raise SettingsError(f"{entry_where}: days muss ein Objekt sein.")
            days: dict[str, dict[str, str]] = {}
            for key, day in days_raw.items():
                if key not in WEEKDAY_KEYS:
                    raise SettingsError(f"{entry_where}: unbekannter Wochentag {_label(key)}.")
                days[key] = _clocks(day, f"{entry_where} {key}")
            entry = {"mode": "per_day", "days": days}
        elif "mode" in raw:
            raise SettingsError(f"{entry_where}: mode darf nur per_day sein.")
        else:
            entry = _clocks({key: val for key, val in raw.items() if key != "pause"}, entry_where)
        if "pause" in raw:
            minutes = raw["pause"]
            if isinstance(minutes, bool) or not isinstance(minutes, int) or not 0 <= minutes <= MAX_DEFAULT_PAUSE:
                raise SettingsError(f"{entry_where}: pause muss eine ganze Zahl von 0 bis {MAX_DEFAULT_PAUSE} sein.")
            entry["pause"] = minutes
        # Ein leerer allgemeiner Eintrag entfällt (wie `collect_categories` am Desktop); ein
        # `per_day`-Eintrag bleibt auch ohne Tage erhalten.
        if entry or raw.get("mode") == "per_day":
            out[name] = entry
    return out


def check_times_names(times: Mapping[str, Any], categories: Iterable[str]) -> None:
    """Jeder Name in `category_times` muss eine bekannte Kategorie sein (sonst `SettingsError`)."""
    known = set(categories)
    for name in times:
        if name not in known:
            raise SettingsError(f"Einstellung category_times: {_label(name)} steht nicht in categories.")


def parse_settings(raw: object, *, now_dt: datetime.datetime,
                   parse_utc: Callable[[object], datetime.datetime | None],
                   skew_limit: datetime.timedelta) -> dict[str, dict[str, Any]]:
    """`settings` der Anfrage → `{key: {"value", "modified_at"}}`. Wirft `SettingsError`; dann wurde
    nichts angewendet. Nur `SETTING_KEYS` sind erlaubt."""
    if not isinstance(raw, dict):
        raise SettingsError("settings muss ein Objekt sein.")
    for key in raw:
        if key not in SETTING_KEYS:
            raise SettingsError(f"Einstellung {_label(key)}: nicht erlaubt (erlaubt: "
                                f"{', '.join(SETTING_KEYS)}).")
    out: dict[str, dict[str, Any]] = {}
    for key in SETTING_KEYS:
        if key not in raw:
            continue
        payload = raw[key]
        if not isinstance(payload, dict) or "value" not in payload or "modified_at" not in payload:
            raise SettingsError(f"Einstellung {key}: erwartet wird {{value, modified_at}}.")
        modified = parse_utc(payload["modified_at"])
        if modified is None:
            raise SettingsError(f"Einstellung {key}: modified_at muss YYYY-MM-DDTHH:MM:SSZ sein.")
        if modified - now_dt > skew_limit:
            raise SettingsError(f"Einstellung {key}: modified_at liegt in der Zukunft.")
        value = _parse_categories(payload["value"]) if key == "categories" else _parse_category_times(payload["value"])
        out[key] = {"value": value, "modified_at": str(payload["modified_at"])}
    if "categories" in out and "category_times" in out:
        check_times_names(out["category_times"]["value"], out["categories"]["value"])
    return out
