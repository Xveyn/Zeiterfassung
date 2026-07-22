"""Update-Check gegen GitHub-Releases (stdlib-only).

Single Purpose: Netzwerk-Call, Versions-Vergleich, Asset-Match, Throttle.
Keine Tk-Imports; UI-Layer ruft die Funktionen aus einem Worker-Thread.
"""

import json
from dataclasses import dataclass
from datetime import date
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.version import VERSION, base_version, parse_release_id, strip_tag_prefix


def is_newer(current: str, latest: str) -> bool:
    """True, wenn `latest` strikt neuer ist als `current`. Beide sind
    Release-Kennungen ohne v-Prefix ('1.19.0' oder '1.19.0-pre.2').

    Ist eine Seite nicht parsebar, gilt "nicht neuer" — ein kaputter oder
    fremder Tag im Release-Feed darf weder crashen noch ein Update auslösen.
    """
    current_key = parse_release_id(current)
    latest_key = parse_release_id(latest)
    if current_key is None or latest_key is None:
        return False
    return latest_key > current_key


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
    version: str            # Basisversion ohne v/-pre, z.B. "1.19.0" (Asset-Namen)
    html_url: str           # Release-Page auf GitHub
    assets: tuple[Asset, ...]
    release_id: str = ""    # volle Kennung ohne v: "1.19.0" | "1.19.0-pre.2"
    is_prerelease: bool = False
    notes: str = ""         # API-`body`; bei Pre-Releases die einzige Inhaltsquelle

    def __post_init__(self):
        # Ohne explizite Kennung IST die Version die Kennung (echtes Release,
        # Alt-Konstruktionen). frozen=True erlaubt kein normales Setzen.
        if not self.release_id:
            object.__setattr__(self, "release_id", self.version)


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


_API_ROOT = "https://api.github.com/repos"

# URLError fängt auch HTTPError (4xx/5xx); OSError fängt socket.timeout etc.
# TypeError/KeyError/AttributeError fangen kaputte Payload-Strukturen ab.
_FETCH_ERRORS = (URLError, OSError, json.JSONDecodeError, TypeError, KeyError, AttributeError)


def _fetch_json(url: str, timeout: float):
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Zeiterfassung/{VERSION}",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def release_from_payload(payload) -> Release | None:
    """Ein Release-Objekt der GitHub-API -> Release. None, wenn Tag oder
    html_url fehlen. Tk-frei und ohne Netzwerk testbar."""
    if not isinstance(payload, dict):
        return None
    tag = payload.get("tag_name")
    html_url = payload.get("html_url")
    if not tag or not html_url:
        return None
    tag = strip_tag_prefix(tag)
    raw_assets = payload.get("assets") or []
    assets = tuple(
        Asset(name=a["name"], url=a["browser_download_url"])
        for a in raw_assets
        if isinstance(a, dict) and "name" in a and "browser_download_url" in a
    )
    return Release(
        version=base_version(tag),
        html_url=html_url,
        assets=assets,
        release_id=tag,
        is_prerelease=bool(payload.get("prerelease")),
        notes=payload.get("body") or "",
    )


def select_newest_payload(payloads) -> dict | None:
    """Wählt aus einer /releases-Liste den Eintrag mit der höchsten Kennung.
    Drafts und Einträge mit unparsebarem Tag werden übersprungen. Wir
    maximieren selbst statt uns auf die API-Sortierung zu verlassen (die nach
    created_at sortiert, nicht nach Publish-Datum)."""
    best, best_key = None, None
    for payload in payloads or []:
        if not isinstance(payload, dict) or payload.get("draft"):
            continue
        key = parse_release_id(strip_tag_prefix(payload.get("tag_name")))
        if key is None:
            continue
        if best_key is None or key > best_key:
            best, best_key = payload, key
    return best


def check_latest_release(repo: str, timeout: float = 5.0) -> Release | None:
    """Fragt die GitHub-API nach dem neuesten ECHTEN Release (Pre-Releases
    liefert /releases/latest nie mit).

    Liefert `None` bei jedem Fehler (Netzwerk, Timeout, kaputtes JSON,
    fehlendes `tag_name`). Caller darf sich darauf verlassen, dass keine
    Exception bubbled — Update-Hinweis ist nice-to-have.
    """
    try:
        return release_from_payload(_fetch_json(f"{_API_ROOT}/{repo}/releases/latest", timeout))
    except _FETCH_ERRORS:
        return None


def check_latest_release_any(repo: str, timeout: float = 5.0) -> Release | None:
    """Wie check_latest_release, aber inklusive Pre-Releases: die Liste
    /releases enthält beide Sorten, das Maximum wählen wir selbst.

    per_page=10 deckt bei der Release-Kadenz dieses Repos mehrere Wochen bis
    Monate ab — dass das neueste Release außerhalb der ersten Seite liegt, ist
    praktisch ausgeschlossen."""
    try:
        payloads = _fetch_json(f"{_API_ROOT}/{repo}/releases?per_page=10", timeout)
        if not isinstance(payloads, list):
            return None
        newest = select_newest_payload(payloads)
        return release_from_payload(newest) if newest is not None else None
    except _FETCH_ERRORS:
        return None


def check_for_update(repo: str, include_prereleases: bool,
                     timeout: float = 5.0) -> Release | None:
    """Der eine Einstieg für beide Aufrufer (Updates-Tab + Hintergrund-Check).
    Ohne Opt-in bleibt es exakt beim bisherigen /releases/latest."""
    if include_prereleases:
        return check_latest_release_any(repo, timeout)
    return check_latest_release(repo, timeout)
