"""Update-Check gegen GitHub-Releases (stdlib-only).

Single Purpose: Netzwerk-Call, Versions-Vergleich, Asset-Match, Throttle.
Keine Tk-Imports; UI-Layer ruft die Funktionen aus einem Worker-Thread.
"""

import json
from dataclasses import dataclass
from datetime import date
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.version import VERSION


def _to_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def is_newer(current: str, latest: str) -> bool:
    """True, wenn `latest` strikt neuer ist als `current`. Beide ohne v-Prefix."""
    return _to_tuple(latest) > _to_tuple(current)


def today_iso() -> str:
    """Heutiges Datum als ISO-Format `YYYY-MM-DD` (lokale Zeitzone)."""
    return date.today().isoformat()


REPO = "MargenHeld/Zeiterfassung"

FREQUENCY_OPTIONS: list[tuple[str, str]] = [
    ("daily", "Täglich"),
    ("weekly", "Wöchentlich"),
    ("monthly", "Monatlich"),
    ("never", "Nie"),
]

_FREQUENCY_INTERVAL_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}


def frequency_for_label(label: str) -> str:
    """Mappt ein im Updates-Tab gewähltes Klartext-Label (z.B. 'Wöchentlich')
    zurück auf den internen Frequency-Value ('weekly'). Unbekanntes Label
    -> 'daily' (sicherer Default, analog holidays_de.code_for_state_label)."""
    return next((value for value, lbl in FREQUENCY_OPTIONS if lbl == label), "daily")


def should_check(last_check: str | None, frequency: str, today: date | None = None) -> bool:
    """True, wenn laut `frequency` ein Update-Check fällig ist.

    `frequency` in {"daily","weekly","monthly","never"} (siehe
    FREQUENCY_OPTIONS). "never" -> immer False. Sonst True, wenn
    `last_check` leer/ungültig ist ODER seit `last_check` mindestens das
    Intervall in Tagen vergangen ist (lokale Kalendertage).
    """
    if frequency == "never":
        return False
    interval_days = _FREQUENCY_INTERVAL_DAYS.get(frequency, 1)
    if not last_check:
        return True
    today = today or date.today()
    try:
        last = date.fromisoformat(last_check)
    except ValueError:
        return True
    return (today - last).days >= interval_days


@dataclass(frozen=True)
class Asset:
    name: str
    url: str


@dataclass(frozen=True)
class Release:
    version: str        # ohne v-Prefix, z.B. "1.9.0"
    html_url: str       # Release-Page auf GitHub
    assets: tuple[Asset, ...]


def update_toast_text(release: "Release") -> str:
    """Deutscher Toast-Text für ein gefundenes Update (kein Klick-Handler —
    der Toast verweist auf den Updates-Tab)."""
    return (
        f"Version {release.version} verfügbar — "
        "Details unter Einstellungen → Updates."
    )


def resolve_check_result(version: str, release: "Release | None") -> dict:
    """Reine Entscheidungslogik für das Ergebnis eines Update-Checks:
    ohne verfügbares Update wird trotzdem der Changelog der installierten
    Version gezeigt, statt das Feld leer/versteckt zu lassen. Liefert alles,
    was der Tk-Glue-Code (`tab_updates.py::_check_now`) an der UI anwenden
    muss — Tk-frei, daher ohne Widgets testbar."""
    if release is None:
        return {
            "status_text": "Prüfung fehlgeschlagen — keine Verbindung?",
            "show_download": False,
            "changelog_version": None,
            "persist": None,
            "latest_release": None,
        }
    if not is_newer(version, release.version):
        return {
            "status_text": f"Du hast die aktuelle Version ({version}).",
            "show_download": False,
            "changelog_version": version,
            "persist": None,
            "latest_release": None,
        }
    return {
        "status_text": f"Version {release.version} verfügbar",
        "show_download": True,
        "changelog_version": release.version,
        "persist": {
            "dismissed_version": release.version,
            "update_toast_shown_version": release.version,
        },
        "latest_release": release,
    }


def pick_asset_url(assets, system: str, latest_version: str) -> str | None:
    """Liefert die Download-URL für das Plattform-Asset oder None."""
    expected_name = {
        "Windows": "Zeiterfassung_Setup.exe",
        "Darwin": f"Zeiterfassung-{latest_version}-arm64.dmg",
        "Linux": f"Zeiterfassung-{latest_version}-x86_64.AppImage",
    }.get(system)
    if expected_name is None:
        return None
    for asset in assets:
        if asset.name == expected_name:
            return asset.url
    return None


def check_latest_release(repo: str, timeout: float = 5.0) -> Release | None:
    """Fragt die GitHub-API nach dem neuesten Release.

    Liefert `None` bei jedem Fehler (Netzwerk, Timeout, kaputtes JSON,
    fehlendes `tag_name`). Caller darf sich darauf verlassen, dass keine
    Exception bubbled — Update-Hinweis ist nice-to-have.
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Zeiterfassung/{VERSION}",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        tag = payload.get("tag_name")
        html_url = payload.get("html_url")
        if not tag or not html_url:
            return None
        # Sowohl 'v' als auch 'V' strippen; Tags sind normiert, defensiv ist billig.
        if tag[:1] in ("v", "V"):
            tag = tag[1:]
        raw_assets = payload.get("assets") or []
        assets = tuple(
            Asset(name=a["name"], url=a["browser_download_url"])
            for a in raw_assets
            if isinstance(a, dict) and "name" in a and "browser_download_url" in a
        )
        return Release(version=tag, html_url=html_url, assets=assets)
    except (URLError, OSError, json.JSONDecodeError, TypeError, KeyError, AttributeError):
        # URLError fängt auch HTTPError (4xx/5xx); OSError fängt socket.timeout etc.
        # TypeError/KeyError/AttributeError fangen kaputte Payload-Strukturen ab.
        return None
