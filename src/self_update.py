"""In-App-Update für Windows und Linux: reine Logik, Tk-frei, stdlib-only.

Die App lädt das Plattform-Asset selbst, prüft es gegen den `SHA256SUMS` des
Releases und installiert es. macOS ist bewusst NICHT dabei — das Bundle ist
weder signiert noch notarisiert, und der Weg über DMG-Mount und
`/Applications` ist auf der Windows-Entwicklungsmaschine nicht verifizierbar
(s. `docs/known-limitations.md`).

**Was die Hash-Prüfung leistet und was nicht.** `SHA256SUMS` schützt gegen
abgebrochene und verfälschte Übertragung. Es schützt NICHT gegen ein
kompromittiertes Release: die Datei ist selbst unsigniert und liegt neben den
Assets, die sie beschreibt. Vertrauensanker bleibt TLS zu GitHub — derselbe
wie beim manuellen Download im Browser. Das löst den Audit-Vermerk M9 ein
(„ein In-App-Auto-Download OHNE Verifikation wäre eine echte Lücke"), ohne
mehr zu behaupten, als es trägt.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from src.updater import pick_asset_url

# Name des Prüfsummen-Assets, das `release.yml` jedem Release beilegt.
SUMS_ASSET_NAME: str = "SHA256SUMS"

_HEX = set("0123456789abcdef")
_CHUNK_BYTES = 1024 * 1024


def parse_sha256sums(text: str) -> dict[str, str]:
    """`SHA256SUMS`-Text → {Dateiname: Hex-Digest}.

    Format ist das von coreutils `sha256sum`: `<digest>  <name>` (zwei
    Leerzeichen) bzw. `<digest> *<name>` im Binärmodus. Unbrauchbare Zeilen
    werden übersprungen statt zu werfen — eine kaputte Zeile darf den Rest
    der Datei nicht entwerten.
    """
    result: dict[str, str] = {}
    for raw in text.splitlines():
        parts = raw.strip().split(None, 1)
        if len(parts) != 2:
            continue
        digest = parts[0].lower()
        if len(digest) != 64 or not set(digest) <= _HEX:
            continue
        result[parts[1].strip().lstrip("*")] = digest
    return result


def verify_file(path: str, expected_hex: str) -> bool:
    """True, wenn die Datei den erwarteten SHA256 hat.

    Blockweise gelesen: die AppImage ist ~65 MB und hat im Speicher nichts zu
    suchen. Ein Lesefehler ist ein Prüf-Fehlschlag, kein Ausnahmefall — der
    Aufrufer behandelt beides gleich (Datei löschen, Update abbrechen).
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == (expected_hex or "").lower()


@dataclass(frozen=True)
class UpdatePlan:
    """Alles, was der Ablauf braucht — ermittelt, bevor ein Byte fließt."""

    asset_url: str
    asset_name: str
    sums_url: str
    target: str     # Linux: $APPIMAGE; Windows: Pfad der laufenden Exe


@dataclass(frozen=True)
class UpdateBlocked:
    """Warum es NICHT losgehen kann — `reason` ist anzeigbarer Text."""

    reason: str


def supports_self_update(system: str, frozen: bool) -> bool:
    """Kann sich die App auf dieser Plattform selbst aktualisieren?

    Nur Windows und Linux, und nur im Frozen-Build: im Repo-Modus gibt es
    keine installierte Datei, die man ersetzen könnte, und `python -m
    src.main` aktualisiert man über git.
    """
    return bool(frozen) and system in ("Windows", "Linux")


def plan_update(release: Any, system: str, machine: str, frozen: bool,
                appimage: str, executable: str) -> "UpdatePlan | UpdateBlocked":
    """Prüft alle Voraussetzungen und liefert entweder den Plan oder den Grund.

    Bewusst EINE Stelle: jeder Abbruchgrund wird hier festgestellt, bevor
    heruntergeladen wird — ein halb geladenes Update, das dann an einer
    Kleinigkeit scheitert, wäre die schlechtere Erfahrung.

    `appimage` ist `$APPIMAGE` (nur Linux relevant), `executable` ist
    `sys.executable`.
    """
    if not supports_self_update(system, frozen):
        if system == "Darwin":
            return UpdateBlocked(
                "Unter macOS lädt die App das Update nicht selbst — "
                "der Download öffnet sich im Browser.")
        return UpdateBlocked(
            "Das Update aus der App heraus gibt es nur in der installierten "
            "Version.")

    asset_url = pick_asset_url(release.assets, system, release.version, machine)
    if asset_url is None:
        return UpdateBlocked(
            "Für die Architektur dieses Rechners gibt es in diesem Release "
            "keine passende Datei.")

    sums_url = next(
        (a.url for a in release.assets if a.name == SUMS_ASSET_NAME), None)
    if sums_url is None:
        return UpdateBlocked(
            "Dieses Release enthält keine Prüfsummen-Datei — die App "
            "installiert nur, was sie prüfen kann.")

    if system == "Linux":
        if not appimage:
            return UpdateBlocked(
                "Der Pfad der laufenden AppImage ist unbekannt "
                "($APPIMAGE nicht gesetzt).")
        target = appimage
    else:
        target = executable

    asset_name = {
        "Windows": "Zeiterfassung_Setup.exe",
        "Linux": f"Zeiterfassung-{release.version}-x86_64.AppImage",
    }[system]
    return UpdatePlan(asset_url=asset_url, asset_name=asset_name,
                      sums_url=sums_url, target=target)
