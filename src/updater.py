# pyright: reportOptionalMemberAccess=true
"""Update-Check gegen GitHub-Releases (stdlib-only).

Single Purpose: Netzwerk-Call, Versions-Vergleich, Asset-Match, Throttle.
Keine Tk-Imports; UI-Layer ruft die Funktionen aus einem Worker-Thread.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.version import VERSION, base_version, parse_release_id, strip_tag_prefix

log = logging.getLogger(__name__)


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


REPO = "Xveyn/Zeiterfassung"

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
    -> 'daily' (sicherer Default, analog Label→Code-Mappings)."""
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

    def __post_init__(self) -> None:
        # Ohne explizite Kennung IST die Version die Kennung (echtes Release,
        # Alt-Konstruktionen). frozen=True erlaubt kein normales Setzen.
        if not self.release_id:
            object.__setattr__(self, "release_id", self.version)


# Art eines gescheiterten Release-Abrufs. Für die Oberfläche gedacht: das Log
# behält die technische Zeile (`_log_fetch_failure`), der Nutzer bekommt den
# Satz aus FAILURE_TEXTS — ohne Statuscodes, Ausnahmenamen oder URLs.
FAILURE_OFFLINE = "offline"
FAILURE_RATE_LIMITED = "rate_limited"
FAILURE_SERVER = "server"
FAILURE_OTHER = "other"

FAILURE_TEXTS: dict[str, str] = {
    FAILURE_OFFLINE: (
        "Keine Verbindung zu GitHub. Prüfe deine Internetverbindung "
        "(auch Proxy oder Firewall) und versuche es erneut."),
    FAILURE_RATE_LIMITED: (
        "GitHub hat die Anfrage abgelehnt, meist weil aus deinem Netzwerk "
        "gerade zu viele Anfragen kamen. Versuche es später erneut."),
    FAILURE_SERVER: (
        "GitHub antwortet gerade nicht richtig. Versuche es später erneut."),
    FAILURE_OTHER: (
        "Die Prüfung auf Updates ist fehlgeschlagen. "
        "Versuche es später erneut."),
}


def failure_text(failure: str | None) -> str:
    """Nutzertext zu einer Fehlerart; unbekannt oder `None` -> der allgemeine."""
    return FAILURE_TEXTS.get(failure or "", FAILURE_TEXTS[FAILURE_OTHER])


def classify_fetch_error(exc: BaseException) -> str:
    """Fehlerart eines gescheiterten Abrufs. GitHub meldet ein Rate-Limit je
    nach Art als 403 oder 429; ein 403 kann auch andere Gründe haben, der Text
    sagt deshalb „meist". `HTTPError` ist selbst ein `URLError` und `OSError` —
    die Prüfung muss vor „offline" stehen, sonst wird aus „GitHub antwortet
    500" ein falsches „keine Verbindung"."""
    if isinstance(exc, HTTPError):
        if exc.code in (403, 429):
            return FAILURE_RATE_LIMITED
        if exc.code >= 500:
            return FAILURE_SERVER
        return FAILURE_OTHER
    if isinstance(exc, OSError):  # URLError ist ein OSError, ebenso Timeouts
        return FAILURE_OFFLINE
    return FAILURE_OTHER


@dataclass(frozen=True)
class CheckOutcome:
    """Ergebnis eines Release-Abrufs: entweder ein Release oder die Art des
    Fehlers (`failure`, einer der FAILURE_*-Werte). Nie beides, nie keines."""
    release: "Release | None"
    failure: str | None = None


def update_toast_text(release: "Release") -> str:
    """Deutscher Toast-Text für ein gefundenes Update (kein Klick-Handler —
    der Toast verweist auf den Updates-Tab)."""
    kind = "Vorabversion" if release.is_prerelease else "Version"
    return (
        f"{kind} {release.release_id} verfügbar — "
        "Details unter Einstellungen → Updates."
    )


def manual_check_toast_text(installed_id: str, release: "Release | None",
                            failure: str | None = None) -> str:
    """Toast-Text für den manuell aus dem Tray angestoßenen Update-Check.

    Anders als der Hintergrund-Check meldet sich der manuelle in **jedem** Fall:
    der Nutzer hat aktiv gefragt, und bei versteckt laufender App ist der Toast
    die einzige Antwortmöglichkeit — ohne Rückmeldung wirkte der Menüpunkt
    kaputt.

    Fallunterscheidung und Wortlaut kommen aus `resolve_check_result` (Single
    Source of Truth, dieselben Texte wie im Updates-Tab); nur der Fund einer
    neueren Version bekommt den toast-spezifischen Verweis auf den Tab.
    """
    result = resolve_check_result(installed_id, release, failure)
    found = result["latest_release"]
    if found is not None:
        return update_toast_text(found)
    return result["status_text"]


def resolve_check_result(installed_id: str, release: "Release | None",
                         failure: str | None = None) -> dict:
    """Reine Entscheidungslogik für das Ergebnis eines Update-Checks.

    `installed_id` ist die Kennung des laufenden Builds
    (`version.installed_release_id()`), nicht bloß die Version.

    Der Changelog kommt aus zwei Quellen: für echte Releases aus CHANGELOG.md
    am Tag (`changelog_version` -> changelog.fetch_changelog_entry), für
    Pre-Releases aus den Release-Notes der API (`changelog_notes`, liegt dem
    Payload bereits bei). CHANGELOG.md kennt am Pre-Tag nur die zuletzt
    veröffentlichte Version — also genau das, was der Nutzer schon hat.

    `failure` ist die Fehlerart eines gescheiterten Abrufs (nur bei `release
    is None` ausgewertet); der Status nennt sie in Nutzerworten.

    Tk-frei, daher ohne Widgets testbar."""
    if release is None:
        return {
            "status_text": failure_text(failure),
            "show_download": False,
            "changelog_version": None,
            "changelog_notes": None,
            "persist": None,
            "latest_release": None,
        }
    if not is_newer(installed_id, release.release_id):
        # Läuft der Nutzer auf genau dem angebotenen Pre-Build, zeigen dessen
        # Notes, was sein Testbuild enthält.
        own_build = release.is_prerelease and release.release_id == installed_id
        return {
            "status_text": f"Du hast die aktuelle Version ({installed_id}).",
            "show_download": False,
            "changelog_version": None if own_build else base_version(installed_id),
            "changelog_notes": release.notes if own_build else None,
            "persist": None,
            "latest_release": None,
        }
    kind = "Vorabversion" if release.is_prerelease else "Version"
    return {
        "status_text": f"{kind} {release.release_id} verfügbar",
        "show_download": True,
        "changelog_version": None if release.is_prerelease else release.version,
        "changelog_notes": release.notes if release.is_prerelease else None,
        "persist": {
            "dismissed_version": release.release_id,
            "update_toast_shown_version": release.release_id,
        },
        "latest_release": release,
    }


# platform.machine() liefert je nach OS verschiedene Schreibweisen für
# dieselbe Architektur. Nur diese Werte gelten als Treffer.
_ARM64 = {"arm64", "aarch64"}
_X86_64 = {"x86_64", "amd64"}


def pick_asset_url(assets: Any, system: str, latest_version: str,
                   machine: str) -> str | None:
    """Liefert die Download-URL für das Plattform-Asset oder None.

    `machine` ist `platform.machine()`. Die Prüfung ist nicht kosmetisch: die
    Asset-Namen tragen die Architektur fest verdrahtet (`-arm64.dmg`,
    `-x86_64.AppImage`), ein Intel-Mac bekäme sonst die arm64-DMG angeboten,
    ein arm64-Linux die x86_64-AppImage — beide laufen dort nicht, und mit dem
    In-App-Update wäre es eine automatische Fehlinstallation. Lieber `None`;
    der Aufrufer fällt auf die Release-Seite zurück.

    Windows ist ausgenommen: `Zeiterfassung_Setup.exe` trägt keine
    Architektur im Namen, und es gibt nur den x64-Build.
    """
    m = (machine or "").lower()
    if system == "Darwin" and m not in _ARM64:
        return None
    if system == "Linux" and m not in _X86_64:
        return None

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


def _fetch_json(url: str, timeout: float) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Zeiterfassung/{VERSION}",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _log_fetch_failure(url: str, exc: BaseException) -> None:
    """Spur für einen gescheiterten Release-Abruf: Art und (bei HTTP) Status,
    nie Header oder Antwortinhalt. Ohne sie bleibt ein 403 (Rate-Limit) oder
    ein Proxy-Problem im --noconsole-Build unsichtbar."""
    code = getattr(exc, "code", None)
    detail = f"HTTP {code}" if code is not None else type(exc).__name__
    log.warning("Update-Check: Abruf von %s fehlgeschlagen (%s)", url, detail)


def release_from_payload(payload: Any) -> Release | None:
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


def select_newest_payload(payloads: Any) -> dict | None:
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


def _latest_outcome(repo: str, timeout: float) -> CheckOutcome:
    url = f"{_API_ROOT}/{repo}/releases/latest"
    try:
        release = release_from_payload(_fetch_json(url, timeout))
    except _FETCH_ERRORS as exc:
        _log_fetch_failure(url, exc)
        return CheckOutcome(None, classify_fetch_error(exc))
    if release is None:
        log.warning("Update-Check: Antwort von %s enthält kein auswertbares Release", url)
        return CheckOutcome(None, FAILURE_OTHER)
    return CheckOutcome(release)


def _any_outcome(repo: str, timeout: float) -> CheckOutcome:
    url = f"{_API_ROOT}/{repo}/releases?per_page=10"
    try:
        payloads = _fetch_json(url, timeout)
        newest = select_newest_payload(payloads) if isinstance(payloads, list) else None
        release = release_from_payload(newest) if newest is not None else None
    except _FETCH_ERRORS as exc:
        _log_fetch_failure(url, exc)
        return CheckOutcome(None, classify_fetch_error(exc))
    if release is None:
        log.warning("Update-Check: Antwort von %s enthält kein auswertbares Release", url)
        return CheckOutcome(None, FAILURE_OTHER)
    return CheckOutcome(release)


def check_latest_release(repo: str, timeout: float = 5.0) -> Release | None:
    """Fragt die GitHub-API nach dem neuesten ECHTEN Release (Pre-Releases
    liefert /releases/latest nie mit).

    Liefert `None` bei jedem Fehler (Netzwerk, Timeout, kaputtes JSON,
    fehlendes `tag_name`) und loggt dann Art bzw. HTTP-Status als WARNING.
    Caller darf sich darauf verlassen, dass keine Exception bubbled —
    Update-Hinweis ist nice-to-have.
    """
    return _latest_outcome(repo, timeout).release


def check_latest_release_any(repo: str, timeout: float = 5.0) -> Release | None:
    """Wie check_latest_release, aber inklusive Pre-Releases: die Liste
    /releases enthält beide Sorten, das Maximum wählen wir selbst.

    per_page=10 deckt bei der Release-Kadenz dieses Repos mehrere Wochen bis
    Monate ab — dass das neueste Release außerhalb der ersten Seite liegt, ist
    praktisch ausgeschlossen."""
    return _any_outcome(repo, timeout).release


def check_for_update_outcome(repo: str, include_prereleases: bool,
                             timeout: float = 5.0) -> CheckOutcome:
    """Der Einstieg für Aufrufer, die einem Nutzer sagen müssen, WARUM ein
    Abruf scheiterte (Updates-Tab, Tray-Check). Wirft nie. Ohne Opt-in bleibt
    es bei /releases/latest."""
    if include_prereleases:
        return _any_outcome(repo, timeout)
    return _latest_outcome(repo, timeout)


def check_for_update(repo: str, include_prereleases: bool,
                     timeout: float = 5.0) -> Release | None:
    """Wie `check_for_update_outcome`, aber nur das Release (`None` bei jedem
    Fehler) — für den stillen Hintergrund-Check, der keinem Nutzer etwas
    erklären muss."""
    return check_for_update_outcome(repo, include_prereleases, timeout).release
