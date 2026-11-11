# src/removal.py
# pyright: reportOptionalMemberAccess=true
"""„Zeiterfassung entfernen" (macOS/Linux, #50): Plan und Ausführung.

Tk-frei. Der Windows-Uninstaller (`installer.iss`) ist die Vorlage:
Zugangsdaten gehen immer, Nutzerdaten nur auf ausdrückliche Nachfrage. Die
Dateilisten hier spiegeln seine.

**Reihenfolge ist der Punkt:** der Schlüsselbund zuerst, denn die Schlüssel
stehen in `token.json`/`webhooks.json`/`smtp.json` (`secret_migration.
forget_all` liest sie von dort). Danach Autostart/Menüeintrag, dann die
Dateien; `settings.json` als letzte Datei — bricht der Lauf ab, sind die
Einstellungen noch da und das Entfernen lässt sich wiederholen.

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
import shlex
import shutil
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from src import desktop_entry, oauth_utils, secret_migration, self_update
from src.autostart import disable_autostart, macos_plist_path
from src.i18n import N_, t

log = logging.getLogger(__name__)

# Spiegel von `installer.iss` ([UninstallDelete] bzw. DeleteUserData).
CREDENTIAL_FILES: tuple[str, ...] = (
    "token.json", "instance-secret", "webhooks.json", "smtp.json",
    "credentials.json", "api-token", "mobile_devices.json", "mobile_keys.json",
    "mobile_relay.json", "mobile_box.json", "mobile_box_cursor.json",
)
USER_DATA_FILES: tuple[str, ...] = (
    "zeiterfassung.json", "reservations.json", "vacations.json",
    "conflicts.json", "sync_history.json", "sync-apply.journal",
)
SETTINGS_FILE = "settings.json"
LOGS_DIR = "logs"

# Schrittkennungen: ein Schritt wird über sie erkannt (`StepResult.name`), nie über
# seinen Anzeigenamen. Den Namen löst `step_label` beim Anzeigen auf.
KEYRING_STEP = "keyring"
BOX_STEP = "boxes"
AUTOSTART_STEP = "autostart"
MENU_STEP = "menu_entry"
PENDING_STEP = "pending_update"
CREDENTIALS_STEP = "credentials"
USER_DATA_STEP = "user_data"
DATA_DIR_STEP = "data_dir"
PLANNING_STEP = "planning"
STEP_LABELS: dict[str, str] = {
    KEYRING_STEP: N_("entfernen.schritt_schluesselbund"),
    BOX_STEP: N_("entfernen.schritt_boxen"),
    AUTOSTART_STEP: N_("entfernen.schritt_autostart"),
    MENU_STEP: N_("entfernen.schritt_menue"),
    PENDING_STEP: N_("entfernen.schritt_update"),
    CREDENTIALS_STEP: N_("entfernen.schritt_zugangsdaten"),
    USER_DATA_STEP: N_("entfernen.schritt_nutzerdaten"),
    DATA_DIR_STEP: N_("entfernen.schritt_datenordner"),
    PLANNING_STEP: N_("entfernen.schritt_planung"),
}
GOOGLE_PERMISSIONS_URL = "https://myaccount.google.com/permissions"
TRANSLOCATION_MARKER = "/AppTranslocation/"
# So lange wartet das Entfernen auf laufende Hintergrundjobs (Token-Refresh,
# Kalender-Abgleich), bevor es Dateien löscht.
IDLE_WAIT_S = 20.0

# Ein Schritt darf einen Hinweis (`str`) zurückgeben: erledigt, aber mit etwas,
# das der Nutzer wissen muss. Jeder andere Rückgabewert zählt als „nichts".
Step = tuple[str, Callable[[], object]]


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    error: str = ""
    note: str = ""


def readme_hint() -> str:
    return t("entfernen.hinweis_readme")


def keyring_hint() -> str:
    return t("entfernen.hinweis_schluesselbund")


def translocation_hint() -> str:
    return t("entfernen.hinweis_translocation")


def step_label(step_id: str) -> str:
    """Anzeigename eines Schritts; eine unbekannte Kennung steht roh da."""
    if step_id in STEP_LABELS:
        return t(STEP_LABELS[step_id])
    return step_id


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


def _forget_boxes(base_path: str) -> str | None:
    """Löscht die Boxen am Relay (Netz — nur über `run_removal` im Worker, nie beim Planen).
    Ein Hinweis, wenn Boxen nicht erreicht wurden: sie verfallen am Relay von selbst."""
    missed = secret_migration.forget_boxes(os.path.join(base_path, "mobile_box.json"))
    if not missed:
        return None
    if missed == 1:
        return t("entfernen.boxen_nicht_erreicht.eins", anzahl=missed)
    return t("entfernen.boxen_nicht_erreicht.viele", anzahl=missed)


def _glob(base_path: str, pattern: str) -> list[str]:
    return glob.glob(os.path.join(glob.escape(base_path), pattern))


def _credential_paths(base_path: str) -> list[str]:
    paths = [os.path.join(base_path, name) for name in CREDENTIAL_FILES]
    # Quarantäne-Kopie (`json_store`, N4) und liegengebliebene Temp-Datei
    # (`oauth_utils.write_token_json`) tragen dieselben Secrets.
    for name in CREDENTIAL_FILES:
        paths.extend(_glob(base_path, f"{glob.escape(name)}.corrupt-*"))
    # mkstemp-Reste der Secret-Schreiber (`secure_file`): `.<stem>-*.tmp` (token, webhooks,
    # smtp, instance-secret, api-token, mobile_keys, mobile_relay, mobile_box) — sie können
    # Secrets im Klartext tragen. Der Präfix des Schreibers muss dazu passen (Test in test_removal).
    for name in CREDENTIAL_FILES:
        stem = name.removesuffix(".json")
        paths.extend(_glob(base_path, f".{glob.escape(stem)}-*.tmp"))
    # Temp-Rest von `json_store.atomic_write_json` (`<datei>.<zufall>.tmp`) des Cursors.
    paths.extend(_glob(base_path, "mobile_box_cursor.json.*.tmp"))
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
        # Reste von `json_store.atomic_write_json` (`<name>.<zufall>.tmp`)
        # und `sync_history.json.tmp`.
        for name in (*USER_DATA_FILES, SETTINGS_FILE):
            _remove_all(_glob(base_path, f"{glob.escape(name)}.*tmp"))
    except OSError as e:
        failures.append(str(e))
    logs = os.path.join(base_path, LOGS_DIR)
    if os.path.isdir(logs):
        try:
            shutil.rmtree(logs)
        except OSError as e:
            failures.append(f"{LOGS_DIR}: {e}")
    try:
        # Als letzte Datei: bricht der Lauf vorher ab, ist sie noch da. (Der
        # Update-Pfad wird nicht hieraus gelesen, sondern vorab im UI-Thread.)
        _remove_all([os.path.join(base_path, SETTINGS_FILE)])
    except OSError as e:
        failures.append(str(e))
    if failures:
        raise OSError("; ".join(failures))


def _remove_dir_if_empty(base_path: str) -> str | None:
    """`None` = Ordner weg. Ein Hinweis, wenn er bleibt (M4): sonst liest der
    Nutzer ✓ und sucht nicht weiter."""
    try:
        os.rmdir(base_path)
    except FileNotFoundError:
        pass
    except OSError:
        # Nicht leer: fremde Dateien bleiben, und mit ihnen der Ordner. Das
        # ist gewollt, kein Fehler. Jeder andere Grund (Rechte) wird gemeldet.
        if os.path.isdir(base_path) and os.listdir(base_path):
            return t("entfernen.ordner_bleibt", pfad=base_path)
        raise
    return None


def _remove_menu_entry(base_path: str) -> None:
    _remove_all([desktop_entry.menu_entry_path(),
                 os.path.join(base_path, desktop_entry.ICON_FILENAME)])


def _remove_macos_autostart() -> None:
    """Nur die plist löschen, **kein** `launchctl unload`: wurde die App über
    den Autostart gestartet, gehört ihr Prozess zu diesem launchd-Job, und das
    Entladen schickt ihr SIGTERM — mitten im Entfernen, vor den Dateischritten
    und ohne Zusammenfassung. Der geladene Job läuft ohnehin nur bis zum
    Beenden der App; ohne plist lädt ihn die nächste Anmeldung nicht mehr."""
    _remove_all([macos_plist_path()])


def _discard_pending(path: str, clear_pending: Callable[[], None] | None) -> None:
    self_update.discard_download(path)
    # Erst nach erfolgreichem Löschen: scheitert es, zeigt der Eintrag weiter
    # auf eine Datei, die noch da ist (M7).
    if clear_pending is not None:
        clear_pending()


def plan_removal(base_path: str, with_data: bool, system: str,
                 pending_update_path: str = "",
                 clear_pending: Callable[[], None] | None = None) -> list[Step]:
    """Die Schritte in der Reihenfolge, in der sie laufen müssen. Leer, wo
    es nichts zu tun gibt (Windows).

    `clear_pending` leert die `pending_update_*`-Schlüssel der Einstellungen.
    Nur ohne Häkchen „Nutzerdaten" gesetzt: dann bleibt `settings.json` stehen
    und würde sonst auf die gelöschte Update-Datei zeigen (M7). Mit Häkchen
    ginge `settings.json` ohnehin weg — ein Schreiben davor wäre überflüssig,
    eines danach legte sie neu an."""
    if system not in ("Darwin", "Linux"):
        return []
    steps: list[Step] = [
        (KEYRING_STEP, lambda: secret_migration.forget_all(base_path, boxes=False)),
        # Vor dem Löschen der Zugangsdaten: `mobile_box.json` trägt die Geheimnisse.
        (BOX_STEP, lambda: _forget_boxes(base_path)),
        (AUTOSTART_STEP,
         _remove_macos_autostart if system == "Darwin"
         else lambda: disable_autostart(system)),
    ]
    if system == "Linux":
        steps.append((MENU_STEP, lambda: _remove_menu_entry(base_path)))
    if pending_update_path:
        steps.append((PENDING_STEP,
                      lambda: _discard_pending(
                          pending_update_path,
                          None if with_data else clear_pending)))
    steps.append((CREDENTIALS_STEP, lambda: _delete_credentials(base_path)))
    if with_data:
        steps.append((USER_DATA_STEP,
                      lambda: _delete_user_data(base_path)))
        steps.append((DATA_DIR_STEP, lambda: _remove_dir_if_empty(base_path)))
    return steps


def run_removal(steps: list[Step]) -> list[StepResult]:
    results: list[StepResult] = []
    for name, fn in steps:
        try:
            note = fn()
        except Exception as e:
            # Bewusst alles: ein Schritt darf scheitern, die übrigen laufen
            # weiter (Modul-Docstring). Der Fehler steht im Ergebnis und im Log.
            log.warning("Entfernen: Schritt %r fehlgeschlagen", name, exc_info=True)
            results.append(StepResult(name, False, f"{type(e).__name__}: {e}"))
        else:
            results.append(StepResult(name, True, note=note if isinstance(note, str) else ""))
    return results


def execute_removal(base_path: str, with_data: bool, system: str,
                    pending_update_path: str = "",
                    clear_pending: Callable[[], None] | None = None,
                    ) -> list[StepResult]:
    """Plan + Ausführung in einem Aufruf — **wirft nie**, auch nicht beim
    Planen (Einstieg für `BackgroundTaskRunner.run`, dessen `on_done` bei
    einer Exception nie feuert)."""
    try:
        steps = plan_removal(base_path, with_data, system, pending_update_path,
                             clear_pending)
    except Exception as e:
        log.exception("Entfernen: Planung fehlgeschlagen")
        return [StepResult(PLANNING_STEP, False, f"{type(e).__name__}: {e}")]
    return run_removal(steps)


def app_file_hint(system: str, environ: Mapping[str, str],
                  executable: str, frozen: bool = False) -> str | None:
    """Die Programmdatei, die der Nutzer selbst löschen muss — oder `None`,
    wenn sie sich nicht bestimmen lässt.

    Linux: `$APPIMAGE`, sonst bei einem gefrorenen Build das Binary selbst
    (#298). Nur gefroren: im Repo-Modus ist `executable` der Interpreter, und
    `app_file_command` machte daraus ein `rm` auf ihn."""
    if system == "Linux":
        return environ.get("APPIMAGE") or (executable if frozen else None)
    if system == "Darwin":
        if is_translocated(system, executable):
            return None
        parts = executable.split("/")
        for i, part in enumerate(parts):
            if part.endswith(".app"):
                return "/".join(parts[:i + 1])
    return None


def is_translocated(system: str, executable: str) -> bool:
    """Läuft die `.app` aus macOS' App Translocation (M6)? Gatekeeper startet
    eine frisch heruntergeladene App mit Quarantäne-Attribut aus einer
    zufälligen, schreibgeschützten Kopie unter `…/T/AppTranslocation/<UUID>/d/`.
    Der Pfad dort ist weder löschbar noch dem Nutzer bekannt. Den echten Ort
    kennt nur die private Security-Schnittstelle `SecTranslocateCreateOriginal-
    PathForURL` — die nutzen wir bewusst nicht, der Hinweis bleibt allgemein."""
    return system == "Darwin" and TRANSLOCATION_MARKER in executable


def app_file_command(system: str, app_file: str | None) -> str | None:
    """Terminal-Befehl, der die Programmdatei löscht — unter Linux (AppImage
    oder Binary).
    Distributionsunabhängig: eine einzelne Datei, kein Paketmanager im Spiel.
    macOS bleibt beim Papierkorb (ein `rm -rf` auf ein Bundle wäre ungeprüft)."""
    if system == "Linux" and app_file:
        return f"rm -- {shlex.quote(app_file)}"
    return None


def format_summary(results: list[StepResult], app_file: str | None,
                   had_token: bool, command: str | None = None,
                   translocated: bool = False) -> str:
    lines = [(f"✓ {step_label(r.name)} — {r.note}" if r.note
              else f"✓ {step_label(r.name)}") if r.ok
             else f"✗ {step_label(r.name)} — {r.error}" for r in results]
    lines.append("")
    if app_file:
        lines.append(t("entfernen.datei_selbst_loeschen"))
        lines.append(app_file)
        if command:
            lines.append("")
            lines.append(t("entfernen.oder_terminal", befehl=command))
    elif translocated:
        lines.append(translocation_hint())
    else:
        lines.append(t("entfernen.datei_bleibt"))
    if had_token:
        lines.append("")
        lines.append(t("entfernen.google_freigabe", url=GOOGLE_PERMISSIONS_URL))
    if any(r.name == KEYRING_STEP and r.ok for r in results):
        lines.append("")
        lines.append(keyring_hint())
    lines.append("")
    lines.append(readme_hint())
    return "\n".join(lines)


class RemovalState:
    """Läuft gerade das Entfernen? Tk-frei, damit die Entscheidungen testbar
    sind, die `ui.App` sonst nur im Widget-Code träfe.

    `begin` nimmt den `sync_guard` und gibt ihn **nie** zurück: jeder
    Sync-Einstieg überspringt danach seinen Lauf. Gelingt das nicht, läuft
    ein Sync — dann bleibt alles unangetastet (`active` bleibt `False`).
    `admits` entscheidet, ob ein auf den UI-Thread marshallter Callback noch
    laufen darf: fremde Worker (Update-Check, Reconcile …) dürfen nach dem
    Löschen nichts mehr schreiben; nur der eigene Abschluss ist `forced`."""

    def __init__(self) -> None:
        self.active = False

    def begin(self, sync_guard: threading.Lock | None) -> bool:
        if sync_guard is not None and not sync_guard.acquire(blocking=False):
            return False
        self.active = True
        return True

    def claim(self, sync_guard: threading.Lock | None) -> str:
        """`begin` mit einer Antwort, die „läuft schon" von „Sync läuft"
        unterscheidet (M11): `"started"` (jetzt ruhiggestellt, Aufrufer
        räumt auf), `"running"` (ein früherer Aufruf ist schon dabei — nichts
        zu tun, und **keine** Sync-Meldung: der Guard ist ja von uns selbst
        belegt) oder `"sync"` (ein Sync läuft, alles bleibt unangetastet)."""
        if self.active:
            return "running"
        return "started" if self.begin(sync_guard) else "sync"

    def admits(self, forced: bool) -> bool:
        return forced or not self.active
