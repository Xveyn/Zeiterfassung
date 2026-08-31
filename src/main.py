# src/main.py
import logging
import os
import platform
import sys
import threading
import tkinter as tk
import uuid
from typing import Any

# OAuthlib bricht den Flow ab, wenn die zurückgegebenen Scopes nicht exakt mit
# den angeforderten matchen. Google fügt aber bei Identity-Scopes wie
# userinfo.email automatisch 'openid' hinzu — die Lib wirft dann
# "Scope has changed". Diese Env-Variable lockert den Check; muss VOR dem
# Import von google_auth_oauthlib stehen (frühester Punkt: main.py).
#
# N15 (bewusste, eng begrenzte Sicherheits-Lockerung): entschärft NUR die
# Client-seitige Scope-Gleichheitsprüfung von oauthlib. Welche Scopes tatsächlich
# gewährt wurden, erzwingt weiterhin Google serverseitig; ein echter Scope-Upgrade
# (fehlender Scope im Token) wird separat über discard_token_for_scope_upgrade
# (oauth_utils.py) erkannt und per frischem Consent nachgeholt. Kein Blankoscheck.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from src import sync_history
from src.autostart import migrate_legacy_autostart, refresh_linux_target
from src.conflicts_store import ConflictsStore
from src.desktop_entry import ensure_icon, write_menu_entry
from src.device_id import derive_device_id
from src.devices import default_device_name
from src.logging_setup import setup_logging
from src.paths import get_base_path, get_resource_path
from src.reservations import ReservationStore
from src.settings import Settings, clamp_ui_scale
from src.storage import Storage
from src.vacations import VacationStore
from src.sync_runtime import run_pull_in_background
from src.theme import init_fonts
from src.ui import App
from src.version import VERSION
from src.webhook_store import WebhookStore

# Muss exakt zum AppMutex-Wert in installer.iss passen. Der Installer prüft
# beim Start, ob dieser Mutex existiert, und bittet den User, die App manuell
# zu schließen, statt (wie der standardmäßige Restart-Manager-Weg,
# CloseApplications) automatisch zu versuchen — Letzteres scheitert bei uns,
# weil ein aktives Minimize-to-Tray den dabei gesendeten WM_CLOSE nur als
# Fenster-Verstecken behandelt (App._on_close), der Prozess also weiterläuft
# und die .exe-Datei blockiert bleibt.
_APP_MUTEX_NAME = "ZeiterfassungAppMutex"


def _hold_app_mutex():
    """Hält für die Lebensdauer des Prozesses einen benannten Win32-Mutex
    (nur installierte Windows-Builds) — reiner Existenz-Marker für
    installer.iss (AppMutex, s. dort). Windows gibt den Handle beim
    Prozessende automatisch frei (auch bei Crash), kein explizites Release
    nötig; der Rückgabewert muss aber am Leben gehalten werden (sonst schließt
    Python das Handle beim GC), s. Aufrufer in main()."""
    if platform.system() != "Windows" or not getattr(sys, "frozen", False):
        return None
    try:
        import ctypes
        return ctypes.windll.kernel32.CreateMutexW(None, False, _APP_MUTEX_NAME)
    except OSError:
        return None


def _ensure_device_id(settings) -> str:
    """Liefert die garantiert vorhandene Device-ID für den Sync.

    Installierte Builds (frozen): aus einer stabilen, pro OS-Installation
    eindeutigen Hardware-ID abgeleitet (device_id.py) — übersteht damit eine
    Neuinstallation der App, anders als eine rein in settings.json persistierte
    Zufalls-UUID (die beim Reinstall verloren geht). Wird bei jedem Start neu
    abgeleitet und persistiert (statt nur einmalig), damit die Anzeige in
    Einstellungen → Google konsistent bleibt und ein späterer erfolgreicher
    Resolve einen früheren Fallback-Wert wieder korrigiert.

    Repo-/Skript-Modus (`python -m src.main`) UND der Fallback, falls die
    Hardware-ID nicht lesbar ist (fehlende Berechtigung o.ä.): wie bisher eine
    bei Erststart generierte, in settings.json persistierte Zufalls-UUID —
    bewusst NICHT hardware-abgeleitet, sonst hätte eine parallel zu einer
    echten Installation laufende Dev-Instanz auf demselben Rechner dieselbe
    device_id (device_id.py hat die Begründung)."""
    if getattr(sys, "frozen", False):
        derived = derive_device_id()
        if derived:
            settings.set("device_id", derived)
            return derived
    device_id = settings.get("device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
        settings.set("device_id", device_id)
    return device_id


def _ensure_device_name(settings) -> str:
    """Liefert den Anzeigenamen dieses Geräts und belegt ihn beim allerersten
    Start aus dem Hostnamen vor (s. `devices.default_device_name`).

    Die Vorbelegung läuft **genau einmal**, gemerkt über
    `device_name_initialized`: wer den Namen im Einstellungen-Dialog bewusst
    leert, will die Geräte-ID sehen — ein Neustart darf ihm den Hostnamen
    nicht wieder unterschieben. Ein leerer Name ist ein gültiger Zustand, kein
    fehlender Wert."""
    if not settings.get("device_name_initialized"):
        updates: dict[str, Any] = {"device_name_initialized": True}
        if not (settings.get("device_name") or ""):
            updates["device_name"] = default_device_name()
        settings.set_many(updates)
    return settings.get("device_name") or ""


def _sweep_orphan_tombstones(storage, reservation_store, settings, base) -> int:
    """Verwirft beim Start Tombstones, die nie einen Abnehmer bekommen (N6).

    Storage-Tombstones löst nur ein Drive-Sync ein, Reservierungs-Tombstones
    nur ein Kalender-Reconcile. Ohne das jeweilige Feature bleibt jeder
    gelöschte Tag als Zeile liegen — dauerhaft, weil der einzige GC-Pfad
    (Kompaktierung) am Google-Tab hängt.

    Ob je gesynct/abgeglichen wurde, entscheidet NICHT allein settings.json:
    ein korruptes settings.json setzt `Settings` auf Defaults zurück (M4), ein
    tatsächlich gesyncter Rechner sähe dann per `never_synced`/`never_reconciled`
    wie 'nie gesynct' aus und verlöre hier irreversibel seine Tombstones
    (Resurrection gelöschter Tage). Der persistente `sync_history`-Marker ist
    die dauerhafte Gegenprobe: ist er gesetzt, unterbleibt der jeweilige Sweep
    auch nach einem Settings-Reset (Fail-safe: im Zweifel behalten).

    Liefert die Gesamtzahl verworfener Tombstones (für Tests/Logging)."""
    from src import reservations_sync, sync
    dropped = 0
    if not sync_history.ever_synced(base):
        dropped += sync.drop_orphan_tombstones(storage, settings)
    if not sync_history.ever_reconciled(base):
        dropped += reservations_sync.drop_orphan_reservation_tombstones(
            reservation_store, settings)
    if dropped:
        logging.getLogger(__name__).info(
            "%d verwaiste Tombstone(s) verworfen (nie gesynct/abgeglichen)", dropped)
    return dropped


def _apply_ui_scaling(root, factor):
    """Legt die per UI-Faktor skalierten App-Fonts an (ersetzt das frühere
    `tk scaling`, das auf macOS/Aqua die Punkt-Fonts nicht skalierte → Slider dort
    wirkungslos). MUSS vor dem Aufbau der App-Widgets laufen, damit
    measure_max_width die skalierten Fonts misst und die Fenstergeometrie pinnt."""
    init_fonts(root, clamp_ui_scale(factor))


def _refresh_linux_integration(base):
    """Linux-Desktop-Integration beim Start nachziehen (best-effort).

    Zwei Selbstheilungen mit derselben Ursache: der Updater ersetzt die
    AppImage nicht selbst, und ihr Dateiname trägt die Version. Beide Ziele
    zeigen sonst nach einem Update auf die alte Datei.

    Fehler sind hier NIE fatal — ein nicht geschriebener Menüeintrag ist der
    Status quo, ein verhinderter Start wäre eine Regression (Muster wie beim
    Logging-Setup in main()).
    """
    try:
        refresh_linux_target(base)
    except Exception:
        logging.getLogger(__name__).warning(
            "Autostart-Pfad konnte nicht nachgezogen werden", exc_info=True)

    if platform.system() != "Linux" or not getattr(sys, "frozen", False):
        return
    appimage = os.environ.get("APPIMAGE")
    if not appimage:
        return
    try:
        write_menu_entry(appimage, ensure_icon(get_resource_path(), base))
    except Exception:
        logging.getLogger(__name__).warning(
            "Menüeintrag konnte nicht geschrieben werden", exc_info=True)


def main():
    base = get_base_path()
    try:
        setup_logging(base)
        logging.getLogger(__name__).info("Zeiterfassung v%s gestartet", VERSION)
    except Exception:
        # N13: bewusst still — schlägt das Logging-Setup selbst fehl, gibt es
        # keinen Kanal, in den man den Fehler schreiben könnte (und --noconsole
        # schluckt stderr). Setup-Fehler sind nicht-fatal, die App läuft weiter.
        pass

    from src import single_instance

    try:
        migrate_legacy_autostart(base)
    except Exception:
        logging.getLogger(__name__).warning(
            "Autostart-Migration fehlgeschlagen", exc_info=True)

    _refresh_linux_integration(base)

    guard = None
    try:
        guard = single_instance.acquire(base, show_requested="--minimized" not in sys.argv)
        if guard is None:
            return  # Eine Instanz läuft bereits; sie hat SHOW/PING erhalten.
    except Exception:
        logging.getLogger(__name__).warning(
            "Single-Instance-Guard-Fehler — Start ohne Guard", exc_info=True)
        guard = None

    # Referenz muss für die Prozesslaufzeit gehalten werden (s. _hold_app_mutex).
    _app_mutex = _hold_app_mutex()  # noqa: F841

    # Geteilter Daten-Lock über alle vier Stores (Audit H1/H2) + Sync-Guard.
    # data_lock: RLock (reentrant — der Sync-Apply-Block ruft gelockte
    # Store-Methoden). sync_guard: bewusst plain Lock, NIE RLock — er wird
    # thread-übergreifend acquired/released (Lock erlaubt das, RLock nicht).
    data_lock = threading.RLock()
    sync_guard = threading.Lock()

    settings = Settings(os.path.join(base, "settings.json"), lock=data_lock)
    device_id = _ensure_device_id(settings)
    settings.device_id_for_sync = device_id
    _ensure_device_name(settings)

    storage = Storage(os.path.join(base, "zeiterfassung.json"),
                      device_id=device_id, lock=data_lock)

    conflicts_store = ConflictsStore(os.path.join(base, "conflicts.json"),
                                     lock=data_lock)

    reservation_store = ReservationStore(os.path.join(base, "reservations.json"),
                                         lock=data_lock)

    # Urlaubsperioden. Am geteilten data_lock, weil reconcile_vacations
    # Snapshot → Apply unter demselben Lock klammert (Audit H1/H2) — anders
    # als webhook_store, der keinen Sync-Flow hat und sich deshalb bewusst
    # einen eigenen anlegt. Der Store reist NICHT per Drive-Sync und ist
    # bewusst NICHT an gcal_enabled gekoppelt: Urlaub funktioniert ohne
    # Google, nur der Kalender-Push nicht.
    vacation_store = VacationStore(os.path.join(base, "vacations.json"),
                                   lock=data_lock)

    # BEWUSST OHNE den geteilten data_lock — der Store legt sich seinen eigenen an.
    # Der geteilte Lock (Audit H1/H2) existiert, um Snapshot→Merge→Apply der
    # SYNC-Flows über storage/settings/conflicts/reservations atomar zu klammern.
    # Webhooks nehmen an keinem dieser Flows teil: sie sind gerätelokal, stehen
    # nicht im Sync-Doc, nicht im Merge und nicht im Journal. Es gibt also keine
    # übergreifende Invariante, die sie mitziehen müssten.
    #
    # Ihn trotzdem zu teilen hätte einen realen Preis: `save`/`delete` halten den
    # Lock über den icacls-Subprozess (timeout=15) plus bis zu vier Retries à
    # 200 ms. Auf einem hängenden Netzlaufwerk blockierte das Speichern eines
    # Webhooks damit jeden anderen Store und einen laufenden Drive-Sync — für
    # nichts.
    webhook_store = WebhookStore(os.path.join(base, "webhooks.json"))

    # M6: Ein unvollständig gebliebener Sync-Apply eines vorherigen Laufs
    # (Crash zwischen den Store-Writes) wird jetzt idempotent nachgeholt —
    # bevor irgendein Sync-Thread startet, hier noch single-threaded (kein
    # data_lock nötig). Kein Journal → No-op.
    from src import sync_journal
    sync_journal.recover_pending_apply(
        os.path.join(base, sync_journal.JOURNAL_FILENAME),
        storage, settings, conflicts_store)

    # N6: Tombstones ohne Sync-/Kalender-Partner verwerfen. Hier, weil der
    # Prozess noch single-threaded ist (kein data_lock nötig) und der Sweep
    # vor dem ersten Rendern durch sein soll. Nicht-fatal wie die übrigen
    # Startschritte (setup_logging/migrate_legacy_autostart/single_instance):
    # ein Schreibfehler (Platte voll o.ä.) darf den Start nicht verhindern —
    # --noconsole schluckt stderr, ein Crash hier wäre spurlos.
    try:
        _sweep_orphan_tombstones(storage, reservation_store, settings, base)
    except Exception:
        logging.getLogger(__name__).exception(
            "Tombstone-Sweep fehlgeschlagen (nicht-fatal)")

    root = tk.Tk()
    _apply_ui_scaling(root, settings.get("ui_scale"))
    app = App(root, storage, settings, base_path=base, conflicts_store=conflicts_store,
              reservation_store=reservation_store, single_instance=guard,
              data_lock=data_lock, sync_guard=sync_guard, webhook_store=webhook_store,
              vacation_store=vacation_store)

    if "--minimized" in sys.argv:
        root.iconify()

    if guard is not None:
        guard.serve(lambda: app._marshal_to_ui(app._restore_from_tray))

    if settings.get("sync_enabled"):
        def _on_sync_done(ok, error, tb=""):
            def apply():
                # Der Startup-Sync läuft im Daemon-Thread und marshallt sein
                # Ergebnis via after(0) zurück. Schließt der Nutzer das Fenster,
                # bevor dieser Callback feuert, ist der Tk-Interpreter bereits
                # zerstört — jeder winfo-/config-Aufruf wirft dann
                # "application has been destroyed". Der Callback ist dann
                # gegenstandslos und wird verworfen (vgl. tooltip.py).
                try:
                    if ok:
                        app.on_sync_pull_success()
                    else:
                        app.on_sync_pull_error(error, tb)
                except tk.TclError:
                    pass
            root.after(0, apply)
        threading.Thread(
            target=run_pull_in_background,
            args=(storage, settings, conflicts_store, base, _on_sync_done),
            kwargs={"data_lock": data_lock, "sync_guard": sync_guard},
            daemon=True,
        ).start()

    root.mainloop()


if __name__ == "__main__":
    main()
