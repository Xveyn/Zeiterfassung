"""Die Auto-Update-Policy — genau einmal (R9, Xveyn#123).

Zwei Stellen lösen den stillen Hintergrund-Download aus: der Update-Check der
App beim Start (`UpdateCoordinator.on_check_result`) und der Check des
Updates-Tabs beim Öffnen oder bei „Jetzt prüfen". Bis R9 entschied jede
Stelle selbst — mit eigenem Laufguard, der den anderen nicht kannte. Klickte
der Nutzer während des Start-Downloads auf „Update installieren" im Banner,
öffnete das den Tab, und dessen Check lud dieselben ~65 MB ein zweites Mal
(`pending_update_path` war ja noch leer). Die Datei des Verlierers blieb in
%TEMP% liegen; seit `self_update.download_dest` jedem Lauf einen eigenen
Namen gibt, räumt sie auch kein späterer Lauf mehr weg.

Deshalb hier: die Entscheidung (Häkchen, Plattform, vorbereitete Datei,
Guard, `plan_update`), der Lauf und sein Abschluss (persistieren, Banner) —
und **ein** Guard für **jeden** Update-Download, auch den manuellen
Ein-Klick-Weg im Tab (`acquire_manual`/`release_manual`).

Die Mechanik (Laden, Prüfen, Anwenden) liegt weiter in `self_update.py`.
Tk-frei: der Runner (`App._bg`) und der Banner kommen als Callables herein.
"""

import logging
import os
import platform
import sys
import tempfile
from typing import Any, Callable, Protocol

from src.self_update import (
    DownloadedUpdate, UpdateBlocked, download_and_verify_update, download_dest,
    plan_update, supports_self_update,
)

log = logging.getLogger(__name__)


class _Settings(Protocol):
    def get(self, key: str) -> Any: ...

    def set_many(self, updates: dict[str, Any]) -> None: ...


class _Runner(Protocol):
    def run(self, fn: Callable[[], Any],
            on_done: Callable[[Any], None] | None = None) -> None: ...


class AutoUpdater:
    """Entscheidet und fährt den stillen Hintergrund-Download.

    Gehört dem `UpdateCoordinator` der App (ein Exemplar pro Prozess) und wird
    an den Updates-Tab durchgereicht — nur so kennen beide Auslöser denselben
    Guard. Alle Methoden laufen im UI-Thread; `on_done` des Runners ebenfalls,
    der Guard braucht deshalb kein Lock.
    """

    def __init__(self, settings: _Settings, runner: _Runner,
                 on_ready: Callable[[Any], None]) -> None:
        self._settings = settings
        self._runner = runner
        # Macht ein vorbereitetes Update sichtbar (in der App: der Banner).
        self._on_ready = on_ready
        self._busy = False
        # Wer während eines laufenden Auto-Downloads nachfragt, hängt sich
        # hier an und erfährt dessen Ausgang, statt selbst zu laden.
        self._finish_listeners: list[Callable[[bool], None]] = []
        self._progress_listeners: list[Callable[[str], None]] = []
        self._auto_running = False

    @property
    def busy(self) -> bool:
        """Läuft gerade ein Update-Download, still oder manuell?"""
        return self._busy

    def acquire_manual(self) -> bool:
        """Belegt den Guard für den Ein-Klick-Weg. `False`: es lädt schon
        einer — der Aufrufer startet dann keinen zweiten Download."""
        if self._busy:
            return False
        self._busy = True
        return True

    def release_manual(self) -> None:
        self._busy = False

    def maybe_start(self, release: Any,
                    on_progress: Callable[[str], None] | None = None,
                    on_finished: Callable[[bool], None] | None = None) -> str:
        """Lädt und prüft `release` still, wenn die Policy es erlaubt.

        Liefert den Ausgang der Entscheidung: `"disabled"`, `"unsupported"`,
        `"pending"` (eine geprüfte Datei liegt schon bereit), `"busy"`,
        `"blocked"` oder `"started"`. `on_finished(ok)` meldet das Ende des
        Downloads — bei `"busy"` das des bereits laufenden Auto-Downloads.

        Angewendet wird NICHT hier, sondern beim nächsten Beenden
        (`UpdateCoordinator._apply_pending_update`). Der Ablauf ist unbeobachtet: kein
        Dialog, ein Fehlschlag geht nur ins Log, der nächste Check versucht
        es erneut.
        """
        if not bool(self._settings.get("auto_update_enabled")):
            return "disabled"
        if not supports_self_update(platform.system(),
                                    getattr(sys, "frozen", False)):
            return "unsupported"
        if self._settings.get("pending_update_path"):
            # Nicht erneut laden (sonst lädt jeder Check dieselben ~65 MB,
            # solange der Nutzer nicht beendet) — nur wieder sichtbar machen,
            # z.B. nach einem Neustart der App.
            self._on_ready(release)
            return "pending"
        if self._busy:
            if self._auto_running:
                if on_finished is not None:
                    self._finish_listeners.append(on_finished)
                if on_progress is not None:
                    self._progress_listeners.append(on_progress)
            return "busy"

        plan = plan_update(
            release, platform.system(), platform.machine(),
            getattr(sys, "frozen", False),
            os.environ.get("APPIMAGE", ""), sys.executable)
        if isinstance(plan, UpdateBlocked):
            log.info("Automatisches Update nicht möglich: %s", plan.reason)
            return "blocked"

        # Pro Lauf ein eigener Zielname (s. `self_update.download_dest`).
        local = download_dest(platform.system(), plan.asset_name, plan.target,
                              tempfile.gettempdir())
        self._busy = True
        self._auto_running = True
        self._finish_listeners = [on_finished] if on_finished else []
        self._progress_listeners = [on_progress] if on_progress else []

        def progress(text: str) -> None:
            # Aus dem Worker-Thread; die Liste wird nur im UI-Thread
            # verlängert, die Kopie macht das Iterieren davon unabhängig.
            for listener in list(self._progress_listeners):
                listener(text)

        def work() -> DownloadedUpdate | str:
            return download_and_verify_update(plan, local, on_progress=progress)

        def done(result: DownloadedUpdate | str) -> None:
            self._busy = False
            self._auto_running = False
            listeners, self._finish_listeners = self._finish_listeners, []
            self._progress_listeners = []
            ok = not isinstance(result, str)
            if isinstance(result, str):
                log.info("Automatisches Update abgebrochen: %s", result)
            else:
                self._settings.set_many({
                    "pending_update_path": result.path,
                    "pending_update_sha256": result.sha256,
                })
                self._on_ready(release)
            for listener in listeners:
                listener(ok)

        self._runner.run(work, done)
        return "started"


def manual_outcome(ok: bool, dialog_alive: bool) -> str:
    """Was nach dem Download des Ein-Klick-Wegs geschieht.

    - `"apply"` — geladen, der Dialog ist offen: sofort installieren, die
      App beendet sich dabei.
    - `"discard"` — geladen, der Dialog ist zu: NICHT hinter dem Rücken
      eines Nutzers installieren, der ihn gerade geschlossen hat („nie
      mitten in der Arbeit") — aber auch nicht liegen lassen, seit
      `download_dest` räumt kein späterer Lauf die Datei mehr weg.
    - `"show_error"` — gescheitert, der Dialog ist offen: der Nutzer hat
      geklickt und wartet auf eine Antwort.
    - `"log"` — gescheitert, der Dialog ist zu: niemand mehr da, der eine
      Meldung läse.

    Der stille Weg braucht diese Tabelle nicht: er persistiert unabhängig
    davon, ob ein Dialog offen ist (`AutoUpdater.maybe_start`).
    """
    if ok:
        return "apply" if dialog_alive else "discard"
    return "show_error" if dialog_alive else "log"
