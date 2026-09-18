"""Der Update-Lebenszyklus der App — fünfte App-Komponente (R11, Xveyn#123).

Start-Check, Toast-vs.-Banner-Routing seines Ergebnisses, der manuelle Check
aus dem Tray-Menü und das Anwenden eines still vorbereiteten Updates beim
Beenden. Bis R11 lag das alles in `ui.App`; gebaut ist die Komponente wie
`SyncOrchestrator`: Konstruktor-Injektion, `get_tray` lazy (die einzige Quelle
bleibt `App._tray`), kein Import von `src.ui`.

Einen Schritt weiter als `SyncOrchestrator`: Tk-frei. Den Banner baut `App`
(er braucht `root`, den Renderer und `_open_settings`) und reicht ihn fertig
herein; die Tray-Callbacks marshallt `App` selbst per `root.after`.

Die Auto-Update-Policy (R9) gehört dem `AutoUpdater`, den der Coordinator
baut und als `auto_updater` für den Einstellungsdialog bereithält.

Der Gurt vor `root.destroy()` bleibt bewusst in `App._quit_with_sync_push`:
die Zusage „nichts darf das Beenden aufhalten" gilt dem `destroy()`, und der
gehört der App.
"""

import logging
import os
import platform
import sys
from typing import Any, Callable, Protocol

from src.auto_update import AutoUpdater
from src.self_update import apply_linux, apply_windows, discard_download, verify_file
from src.updater import (
    REPO, check_for_update, is_newer, manual_check_toast_text, today_iso,
    update_toast_text,
)
from src.version import installed_release_id


class _Settings(Protocol):
    def get(self, key: str) -> Any: ...

    def set(self, key: str, value: Any) -> None: ...

    def set_many(self, updates: dict[str, Any]) -> None: ...


class _Runner(Protocol):
    def run(self, fn: Callable[[], Any],
            on_done: Callable[[Any], None] | None = None) -> None: ...

    def check_update(self, on_result: Callable[[Any, bool], None]) -> None: ...


class _Banner(Protocol):
    def show_if_newer(self, release: Any) -> None: ...

    def show_ready_to_install(self, release: Any) -> None: ...


class _Tray(Protocol):
    def notify(self, message: str) -> None: ...


def route_update_notification(release: Any, tray_active: bool,
                              toast_shown_version: str) -> tuple[str, str | None]:
    """Entscheidet zwischen Toast, Banner oder No-op für eine neue Version.

    Verglichen wird die volle Kennung (`release_id`), nicht die Basisversion —
    sonst würde ein zweiter Pre-Release derselben Version (pre.1 -> pre.2)
    als "schon gemeldet" durchfallen."""
    if tray_active:
        if release.release_id == toast_shown_version:
            return "none", None
        return "toast", update_toast_text(release)
    return "banner", None


class UpdateCoordinator:
    """Update-Lebenszyklus der App; alle Methoden laufen im UI-Thread."""

    def __init__(self, settings: _Settings, runner: _Runner, banner: _Banner,
                 get_tray: Callable[[], _Tray | None]) -> None:
        self._settings = settings
        self._runner = runner            # App._bg
        self._banner = banner            # das UpdateBanner-Exemplar der App
        self._get_tray = get_tray        # lambda: App._tray
        # Läuft gerade ein manueller Update-Check aus dem Tray? Blockt den
        # zweiten Klick, damit ein Doppelklick nicht zwei Requests und zwei
        # Toasts auslöst (siehe tray_check).
        self._update_check_running = False
        # Die eine Auto-Update-Policy samt Guard (R9) — der Updates-Tab
        # bekommt dasselbe Exemplar, sonst luden der Start-Check und der
        # Check des Tabs dasselbe Update zweimal.
        self.auto_updater = AutoUpdater(
            settings, runner, on_ready=banner.show_ready_to_install)

    def start(self) -> None:
        """Stößt den Start-Check an (Frequenz-Throttle im Runner)."""
        self._runner.check_update(on_result=self.on_check_result)

    def on_check_result(self, release: Any, newer: bool) -> None:
        """Verarbeitet das Ergebnis des Hintergrund-Update-Checks im UI-Thread."""
        self._settings.set("last_update_check_at", today_iso())
        if not newer:
            return
        tray = self._get_tray()
        action, text = route_update_notification(
            release,
            tray is not None,
            self._settings.get("update_toast_shown_version"),
        )
        # `tray`/`text` sind bei "toast" per Konstruktion gesetzt
        # (route_update_notification liefert "toast" nur mit Tray und Text);
        # die Prüfung macht das für den Typchecker sichtbar.
        if action == "toast" and tray is not None and text is not None:
            tray.notify(text)
            self._settings.set("update_toast_shown_version", release.release_id)
        elif action == "banner":
            self._banner.show_if_newer(release)
        # Derselbe Check, der den Nutzer über Toast/Banner informiert, löst
        # bei aktivem Automatik-Schalter zusätzlich den stillen Hintergrund-
        # Download aus — kein eigener Timer (Design-Regel 1: "vorhandener
        # Update-Check"). Läuft unabhängig von der toast/banner-Routing-
        # Entscheidung oben, deshalb hier und nicht in einem der beiden Zweige.
        # Die Policy selbst liegt in `auto_update.AutoUpdater` (R9).
        self.auto_updater.maybe_start(release)

    def tray_check(self) -> None:
        """Manueller Update-Check aus dem Tray-Menü; Ergebnis kommt als Toast.

        Übergeht bewusst den Frequenz-Throttle (`updater.should_check`) des
        Hintergrund-Checks — manuell heißt manuell —, respektiert aber dessen
        Kanal-Einstellung (`prerelease_updates_enabled`).
        """
        if self._get_tray() is None or self._update_check_running:
            return
        self._update_check_running = True
        include_prereleases = bool(self._settings.get("prerelease_updates_enabled"))

        def fn() -> Any:
            try:
                return check_for_update(REPO, include_prereleases)
            except Exception:
                logging.getLogger(__name__).exception(
                    "Manueller Update-Check fehlgeschlagen")
                return None

        self._runner.run(fn, self._on_tray_check_result)

    def _on_tray_check_result(self, release: Any) -> None:
        """Ergebnis des manuellen Checks im UI-Thread: immer ein Toast.

        Das Lauf-Flag wird als Erstes freigegeben — auch im Fehlerfall, sonst
        wäre der Menüpunkt nach einem Netzausfall dauerhaft tot.
        """
        self._update_check_running = False
        installed = installed_release_id()
        if release is not None:
            # Nur eine erfolgreiche Abfrage zählt als „heute geprüft"; sonst
            # schwiege nach einem Fehlversuch auch der Hintergrund-Check.
            self._settings.set("last_update_check_at", today_iso())
            if is_newer(installed, release.release_id):
                # Der Hintergrund-Check soll dieselbe Version nicht gleich
                # nochmal melden (route_update_notification liest den Wert).
                self._settings.set("update_toast_shown_version", release.release_id)
        tray = self._get_tray()
        if tray is not None:
            tray.notify(manual_check_toast_text(installed, release))

    def apply_pending_on_quit(self) -> None:
        """Wendet ein vorbereitetes Update beim Beenden an, falls eines liegt.

        Ein vorbereitetes Update erst hier anwenden — die App macht ohnehin
        zu, der Nutzer verliert keinen angefangenen Eintrag, und der
        Neustart nach dem Update entfällt. Der Gurt gegen doch noch
        entkommende Exceptions sitzt beim Aufrufer (`App._quit_with_sync_push`,
        direkt vor `root.destroy()`).
        """
        pending = self._settings.get("pending_update_path")
        if pending:
            self._apply_pending_update(pending)

    def _apply_pending_update(self, path: str) -> None:
        """Ein vorbereitetes Update beim Beenden anwenden (best-effort).

        Erneut geprüft wird hier bewusst: zwischen Download und Beenden
        können Stunden liegen, und Aufräum-Tools leeren %TEMP%. Fehlt die
        Datei oder stimmt ihr Hash nicht mehr, fällt der Vorgang still aus —
        der nächste Update-Check beginnt von vorn. Ein Fehlschlag hier darf
        das Beenden NIE aufhalten (der Aufrufer sichert das zusätzlich ab).

        Gemeldet wird hier NICHTS: die App macht gerade zu, ein Dialog hätte
        kein Gegenüber mehr. Jeder Fehlerpfad geht ins Log — und räumt
        seine Datei weg. Seit `download_dest` jedem Download-Lauf einen
        eigenen Namen gibt, überschreibt sie kein späterer Lauf mehr; wer
        sie hier liegen lässt, lässt dauerhaft ~65 MB liegen
        (`sweep_appimage_backup` räumt nur `.old`).
        """
        expected = self._settings.get("pending_update_sha256")
        self._settings.set_many({"pending_update_path": "",
                                 "pending_update_sha256": ""})
        if not os.path.exists(path) or not verify_file(path, expected):
            logging.getLogger(__name__).info(
                "Vorbereitetes Update verworfen (Datei fehlt oder Hash "
                "stimmt nicht)")
            discard_download(path)
            return

        if platform.system() == "Windows":
            # restart=False: wer beendet, will beendet haben — der Helfer
            # installiert, startet die App aber NICHT wieder (Gegenstück:
            # der Sofort-Weg im Updates-Tab). Linux verhält sich unten
            # schon so: `apply_linux` ersetzt nur, ohne `os.execv`.
            if not apply_windows(sys.executable, path, os.getpid(), False):
                # apply_windows hat den Grund bereits geloggt; die Datei
                # bleibt sonst als Leiche im %TEMP%.
                discard_download(path)
            return
        appimage = os.environ.get("APPIMAGE", "")
        if not appimage:
            logging.getLogger(__name__).info(
                "Vorbereitetes Update nicht angewendet: $APPIMAGE ist nicht "
                "gesetzt")
            discard_download(path)
            return
        error = apply_linux(appimage, path)
        if error is not None:
            logging.getLogger(__name__).warning(
                "Vorbereitetes Update nicht angewendet: %s", error)
            discard_download(path)
