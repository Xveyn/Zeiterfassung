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
import http.client
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.updater import pick_asset_url
from src.version import VERSION

log = logging.getLogger(__name__)

# Name des Prüfsummen-Assets, das `release.yml` jedem Release beilegt.
SUMS_ASSET_NAME: str = "SHA256SUMS"

_HEX = set("0123456789abcdef")
_CHUNK_BYTES = 1024 * 1024

# Wie lange der Helfer auf das Ende der App wartet, bevor er aufgibt.
# 60 x 1 s: grosszuegig genug fuer einen langsamen Sync-Push beim Beenden,
# kurz genug, dass ein haengender Prozess den Nutzer nicht ewig blockiert.
_WAIT_TRIES = 60


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


def _request(url: str) -> Request:
    return Request(url, headers={"User-Agent": f"Zeiterfassung/{VERSION}"})


def fetch_text(url: str, timeout: float = 15.0) -> str | None:
    """Kleine Textdatei laden (die Prüfsummen). None bei jedem Fehler —
    nie eine Exception nach außen, analog `updater.check_latest_release`.

    `http.client.HTTPException` wird eigens gefangen (z.B. IncompleteRead bei
    abgebrochener Chunked-Response), weil dieser Typ kein OSError-Subtyp ist.
    """
    try:
        with urlopen(_request(url), timeout=timeout) as response:
            return response.read().decode("utf-8")
    except (URLError, OSError, UnicodeDecodeError, http.client.HTTPException):
        return None


def download_to(url: str, dest: str,
                on_progress: Callable[[int, int], None] | None = None,
                timeout: float = 30.0) -> bool:
    """Lädt `url` nach `dest`. True bei Erfolg.

    `on_progress(geladen, gesamt)` wird je Block gerufen; `gesamt` ist 0, wenn
    der Server keine Content-Length schickt. Der Callback läuft im
    Worker-Thread — Aufrufer marshallen selbst auf den UI-Thread.

    Bei JEDEM Fehler wird die angefangene Datei entfernt: eine halbe
    Setup.exe, die liegen bleibt, würde beim nächsten Versuch als fertig
    missverstanden oder vom Nutzer gefunden und ausgeführt.

    `http.client.HTTPException` wird eigens gefangen (z.B. IncompleteRead bei
    abgebrochener Chunked-Response), weil dieser Typ kein OSError-Subtyp ist.
    """
    try:
        with urlopen(_request(url), timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(dest, "wb") as handle:
                while True:
                    chunk = response.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        on_progress(done, total)
        return True
    except (URLError, OSError, http.client.HTTPException) as exc:
        log.warning("Update-Download fehlgeschlagen: %s", exc)
        try:
            os.remove(dest)
        except OSError:
            pass  # nichts angelegt oder schon weg — beides in Ordnung
        return False


def windows_helper_script(pid: int, setup_path: str, exe_path: str,
                          log_path: str) -> str:
    """Das Batch-Skript, das die App nach dem Beenden aktualisiert.

    Drei Schritte, und die Reihenfolge ist der ganze Punkt:
      1. warten, bis die App-PID verschwunden ist (sonst blockt `AppMutex`
         den Installer)
      2. `Setup.exe /SILENT /NORESTART` — bewusst OHNE `/VERYSILENT` (das
         Fortschrittsfenster ist das einzige Signal, dass etwas passiert) und
         OHNE `/SUPPRESSMSGBOXES` (macht „Abort" zur Standardantwort und
         verschluckte echte Fehler)
      3. die App wieder starten — der `[Run]`-Eintrag in `installer.iss`
         trägt `skipifsilent` und feuert im stillen Lauf nicht

    Der Exit-Code des Installers landet im Log neben der App: scheitert der
    Lauf, ist das die einzige Spur. Gestartet wird die App danach in JEDEM
    Fall — auch nach einem Fehlschlag ist eine laufende alte Version besser
    als gar keine.

    Alle Pfade sind gequotet: `D:\\Programme (x86)\\…` ist hier der Normalfall.
    """
    return "\n".join([
        "@echo off",
        "setlocal",
        f"set TRIES={_WAIT_TRIES}",
        ":wait",
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul',
        "if errorlevel 1 goto install",
        "set /a TRIES-=1",
        "if %TRIES% LEQ 0 goto install",
        "timeout /t 1 /nobreak >nul",
        "goto wait",
        ":install",
        f'"{setup_path}" /SILENT /NORESTART',
        f'echo Installer beendet mit %ERRORLEVEL% > "{log_path}"',
        f'start "" "{exe_path}"',
        f'del "{setup_path}" >nul 2>&1',
        "",
    ])


def apply_windows(exe_path: str, setup_path: str, pid: int) -> bool:
    """Schreibt den Helfer nach %TEMP% und startet ihn abgekoppelt.

    Der Aufrufer beendet die App unmittelbar danach — der Helfer wartet auf
    genau dieses Ende. `CREATE_NEW_PROCESS_GROUP` entkoppelt ihn, damit er
    das Ende der App überlebt; `CREATE_NO_WINDOW` hält das Konsolenfenster
    unsichtbar.

    Das Batch-Skript wird in der OEM-Codepage geschrieben (Windows-spezifisch),
    damit Umlaute und andere Nicht-ASCII-Zeichen in Pfaden korrekt erhalten
    bleiben. Linux hat keinen OEM-Codec — dort setzen wir UTF-8 (fallback).
    """
    import subprocess
    import tempfile

    log_path = os.path.join(os.path.dirname(exe_path), "update.log")

    # Encoding-Auswahl: OEM auf Windows (für cmd.exe-Kompatibilität),
    # UTF-8 fallback auf Linux, wo dieser Codec nicht verfügbar ist.
    encoding = "utf-8"
    try:
        # Versuche OEM-Encoding (nur Windows)
        "test".encode("oem")
        encoding = "oem"
    except LookupError:
        # OEM-Codec nicht verfügbar (z.B. Linux)
        pass

    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".cmd", delete=False, encoding=encoding, errors="strict")
    try:
        with handle:
            handle.write(windows_helper_script(
                pid, setup_path, exe_path, log_path))
        # Prozess-Flags: CREATE_NEW_PROCESS_GROUP entkoppelt den Helfer,
        # damit er das Ende der App überlebt. CREATE_NO_WINDOW hält die
        # Konsole unsichtbar.
        # BEWUSST NICHT: DETACHED_PROCESS (0x8). Mit diesem Flag würde dem
        # Prozess die Konsole entzogen → tasklist liefert keine Ausgabe,
        # die Warteschleife (:wait) läuft blind über das Ende der App,
        # springt sofort zu :install, während der AppMutex noch gehalten wird.
        # Das ist exakt das Gegenteil des Zwecks.
        subprocess.Popen(
            ["cmd", "/c", handle.name],
            creationflags=(0x00000200 |   # CREATE_NEW_PROCESS_GROUP
                           0x08000000),   # CREATE_NO_WINDOW
            close_fds=True)
        return True
    except OSError as exc:
        log.warning("Update-Helfer konnte nicht gestartet werden: %s", exc)
        return False
    except UnicodeEncodeError as exc:
        log.warning("Update-Helfer: Zeichen in Pfaden lassen sich nicht kodieren: %s", exc)
        return False
