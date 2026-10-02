# src/removal.py
"""„Zeiterfassung entfernen" (macOS/Linux, #50): Plan und Ausführung.

Tk-frei. Der Windows-Uninstaller (`installer.iss`) ist die Vorlage:
Zugangsdaten gehen immer, Nutzerdaten nur auf ausdrückliche Nachfrage. Die
Dateilisten hier spiegeln seine — `tests/test_removal.py` hält beide
zusammen.

**Reihenfolge ist der Punkt:** der Schlüsselbund zuerst, denn die Schlüssel
stehen in `token.json`/`webhooks.json`/`smtp.json` (`secret_migration.
forget_all` liest sie von dort). Danach Autostart/Menüeintrag, dann die
Dateien; `settings.json` als letzte Datei.

Jeder Schritt läuft für sich: ein Fehler (gesperrte Datei, hängender
Schlüsselbund) hält die übrigen nicht auf und steht im Ergebnis. Nach außen
wirft nichts — der Aufrufer wartet auf `on_done`, und ein Worker, der
stirbt, ließe die App ruhiggestellt und unsichtbar zurück.

Die App löscht ihre eigene Programmdatei **nicht**; `app_file_hint` nennt
sie nur.
"""
from __future__ import annotations

import glob
import logging
import os
import shutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from src import desktop_entry, oauth_utils, secret_migration, self_update
from src.autostart import disable_autostart

log = logging.getLogger(__name__)

# Spiegel von `installer.iss` ([UninstallDelete] bzw. DeleteUserData).
CREDENTIAL_FILES: tuple[str, ...] = (
    "token.json", "instance-secret", "webhooks.json", "smtp.json",
    "credentials.json",
)
USER_DATA_FILES: tuple[str, ...] = (
    "zeiterfassung.json", "reservations.json", "vacations.json",
    "conflicts.json", "sync_history.json", "sync-apply.journal",
)
SETTINGS_FILE = "settings.json"
LOGS_DIR = "logs"

README_HINT = (
    "Bleibt etwas stehen, steht in der README unter „Vollständig entfernen“, "
    "wie du es von Hand abräumst.")
GOOGLE_PERMISSIONS_URL = "https://myaccount.google.com/permissions"

Step = tuple[str, Callable[[], None]]


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    error: str = ""


def is_available(system: str, frozen: bool) -> bool:
    """Nur macOS/Linux und nur im installierten Build — aus dem Repo heraus
    würde der Button Dev-Daten löschen, unter Windows ist der Uninstaller
    zuständig."""
    return frozen and system in ("Darwin", "Linux")


def _remove_all(paths: Iterable[str]) -> None:
    """Löscht jede Datei einzeln; ein Fehler stoppt die übrigen nicht und
    wird am Ende gesammelt geworfen. Fehlende Dateien sind kein Fehler."""
    failures: list[str] = []
    for path in paths:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            failures.append(f"{os.path.basename(path)}: {e}")
    if failures:
        raise OSError("; ".join(failures))


def _glob(base_path: str, pattern: str) -> list[str]:
    return glob.glob(os.path.join(glob.escape(base_path), pattern))


def _credential_paths(base_path: str) -> list[str]:
    paths = [os.path.join(base_path, name) for name in CREDENTIAL_FILES]
    # Quarantäne-Kopie (`json_store`, N4) und liegengebliebene Temp-Datei
    # (`oauth_utils.write_token_json`) tragen dieselben Secrets.
    for name in CREDENTIAL_FILES:
        paths.extend(_glob(base_path, f"{glob.escape(name)}.corrupt-*"))
    paths.extend(_glob(base_path, ".token-*.tmp"))
    return paths


def _delete_credentials(base_path: str) -> None:
    # Unter TOKEN_LOCK: ein gleichzeitiger Token-Refresh darf die Datei nicht
    # zwischen Löschen und Beenden neu schreiben.
    with oauth_utils.TOKEN_LOCK:
        _remove_all(_credential_paths(base_path))


def _delete_user_data(base_path: str) -> None:
    failures: list[str] = []
    try:
        _remove_all(os.path.join(base_path, name) for name in USER_DATA_FILES)
        _remove_all(_glob(base_path, "*.corrupt-*"))
    except OSError as e:
        failures.append(str(e))
    logs = os.path.join(base_path, LOGS_DIR)
    if os.path.isdir(logs):
        try:
            shutil.rmtree(logs)
        except OSError as e:
            failures.append(f"{LOGS_DIR}: {e}")
    try:
        # Als letzte Datei: andere Schritte lesen sie nicht mehr.
        _remove_all([os.path.join(base_path, SETTINGS_FILE)])
    except OSError as e:
        failures.append(str(e))
    if failures:
        raise OSError("; ".join(failures))


def _remove_dir_if_empty(base_path: str) -> None:
    try:
        os.rmdir(base_path)
    except FileNotFoundError:
        pass
    except OSError:
        # Nicht leer: fremde Dateien bleiben, und mit ihnen der Ordner. Das
        # ist gewollt, kein Fehler. Jeder andere Grund (Rechte) wird gemeldet.
        if os.path.isdir(base_path) and os.listdir(base_path):
            return
        raise


def _remove_menu_entry(base_path: str) -> None:
    _remove_all([desktop_entry.menu_entry_path(),
                 os.path.join(base_path, desktop_entry.ICON_FILENAME)])


def plan_removal(base_path: str, with_data: bool, system: str,
                 pending_update_path: str = "") -> list[Step]:
    """Die Schritte in der Reihenfolge, in der sie laufen müssen. Leer, wo
    es nichts zu tun gibt (Windows)."""
    if system not in ("Darwin", "Linux"):
        return []
    steps: list[Step] = [
        ("Schlüsselbund-Einträge",
         lambda: secret_migration.forget_all(base_path)),
        ("Autostart", disable_autostart),
    ]
    if system == "Linux":
        steps.append(("Menüeintrag", lambda: _remove_menu_entry(base_path)))
    if pending_update_path:
        steps.append(("Vorbereitetes Update",
                      lambda: self_update.discard_download(pending_update_path)))
    steps.append(("Zugangsdaten", lambda: _delete_credentials(base_path)))
    if with_data:
        steps.append(("Zeiten, Einstellungen und Protokoll",
                      lambda: _delete_user_data(base_path)))
        steps.append(("Datenordner", lambda: _remove_dir_if_empty(base_path)))
    return steps


def run_removal(steps: list[Step]) -> list[StepResult]:
    results: list[StepResult] = []
    for name, fn in steps:
        try:
            fn()
        except Exception as e:
            # Bewusst alles: ein Schritt darf scheitern, die übrigen laufen
            # weiter (Modul-Docstring). Der Fehler steht im Ergebnis und im Log.
            log.warning("Entfernen: Schritt %r fehlgeschlagen", name, exc_info=True)
            results.append(StepResult(name, False, f"{type(e).__name__}: {e}"))
        else:
            results.append(StepResult(name, True))
    return results


def execute_removal(base_path: str, with_data: bool, system: str,
                    pending_update_path: str = "") -> list[StepResult]:
    """Plan + Ausführung in einem Aufruf — **wirft nie**, auch nicht beim
    Planen (Einstieg für `BackgroundTaskRunner.run`, dessen `on_done` bei
    einer Exception nie feuert)."""
    try:
        steps = plan_removal(base_path, with_data, system, pending_update_path)
    except Exception as e:
        log.exception("Entfernen: Planung fehlgeschlagen")
        return [StepResult("Planung", False, f"{type(e).__name__}: {e}")]
    return run_removal(steps)


def app_file_hint(system: str, environ: Mapping[str, str],
                  executable: str) -> str | None:
    """Die Programmdatei, die der Nutzer selbst löschen muss — oder `None`,
    wenn sie sich nicht bestimmen lässt."""
    if system == "Linux":
        return environ.get("APPIMAGE") or None
    if system == "Darwin":
        parts = executable.split("/")
        for i, part in enumerate(parts):
            if part.endswith(".app"):
                return "/".join(parts[:i + 1])
    return None


def format_summary(results: list[StepResult], app_file: str | None,
                   had_token: bool) -> str:
    lines = [f"✓ {r.name}" if r.ok else f"✗ {r.name} — {r.error}" for r in results]
    lines.append("")
    if app_file:
        lines.append("Die Programmdatei bleibt liegen. Lösche sie jetzt selbst:")
        lines.append(app_file)
    else:
        lines.append("Die Programmdatei bleibt liegen — lösche sie selbst.")
    if had_token:
        lines.append("")
        lines.append("Die Freigabe im Google-Konto bleibt bestehen. Zurückziehen "
                     f"lässt sie sich unter:\n{GOOGLE_PERMISSIONS_URL}")
    lines.append("")
    lines.append(README_HINT)
    return "\n".join(lines)
