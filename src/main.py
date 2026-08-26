# src/main.py
import contextlib
import logging
import os
import platform
import sys
import threading
import tkinter as tk
import traceback
import uuid

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
from src.logging_setup import setup_logging
from src.paths import get_base_path, get_resource_path
from src.reservations import ReservationStore
from src.settings import Settings, clamp_ui_scale
from src.storage import Storage
from src.theme import init_fonts
from src.time_utils import utc_now_iso
from src.ui import App
from src.version import VERSION

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


def relaunch_command(argv, executable, frozen):
    """Baut das Kommando, um die App neu zu starten (nach UI-Skalierungs-
    Änderung). Im Frozen-Build ist `executable` die App-Exe selbst; im
    Repo-Modus wird `python -m src.main` aufgerufen. `--minimized` wird
    entfernt, weil der Nutzer nach einer interaktiven Skalierungsänderung das
    Fenster sehen will, nicht ein erneut minimiertes."""
    rest = [a for a in argv[1:] if a != "--minimized"]
    if frozen:
        return [executable] + rest
    return [executable, "-m", "src.main"] + rest


def _parse_remote_or_quarantine(content_bytes, file_id, on_corrupt):
    """Parsed Remote-Bytes als JSON. Bei Fehler ruft on_corrupt(file_id) auf
    und liefert ein leeres Doc."""
    import json
    try:
        return json.loads(content_bytes)
    except (json.JSONDecodeError, ValueError):
        on_corrupt(file_id)
        return {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}


def _lock_ctx(lock):
    """Context-Manager-Shim für den optionalen Daten-Lock: `with _lock_ctx(l)`
    lockt, wenn ein Lock übergeben wurde, und ist sonst ein No-op (Tests,
    Alt-Aufrufer). Hält den Sync-Apply-Block atomar gegen UI-Saves (Audit H1)."""
    return lock if lock is not None else contextlib.nullcontext()


def run_pull_in_background(storage, settings, conflicts_store, base, ui_callback,
                            data_lock=None, sync_guard=None):
    """Pull läuft in einem Thread; UI-Update über ui_callback (root.after).

    sync_guard (plain Lock, Re-Entrancy-Guard, Audit H2): läuft bereits ein
    anderer Sync, wird der Pull still übersprungen — ohne ui_callback; der
    laufende Sync meldet sein Ergebnis selbst. Release im finally DIESES
    Threads (nach der letzten Store-Mutation), nie in UI-Callbacks.
    data_lock (geteilter Store-RLock, Audit H1): klammert
    Snapshot→Merge→Apply atomar gegen parallele UI-Saves. Wird NICHT über
    den Download gehalten."""
    from src import drive, sync, sync_journal
    if sync_guard is not None and not sync_guard.acquire(blocking=False):
        return
    try:
        try:
            service = drive.get_drive_service(
                os.path.join(base, "credentials.json"),
                os.path.join(base, "token.json"),
                gcal_enabled=settings.get("gcal_enabled"),
            )
            file_id = drive.find_sync_file(service)
            if file_id is None:
                remote_doc = {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
                etag = ""
            else:
                content, etag = drive.download(service, file_id)
                def _quarantine(fid):
                    import datetime
                    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                    try:
                        service.files().update(
                            fileId=fid,
                            body={"name": f"zeiterfassung-sync.corrupt-{stamp}.json"},
                        ).execute()
                    except Exception:
                        logging.getLogger(__name__).warning(
                            "Quarantine rename failed for %s", fid, exc_info=True)
                remote_doc = _parse_remote_or_quarantine(content, file_id, _quarantine)
            if sync.remote_is_newer(remote_doc):
                # Neueres (zukünftiges) Schema: NICHT mergen/pushen — Pull sauber
                # abbrechen, last_pull_at/etag unverändert lassen.
                ui_callback(ok=False, error=sync.NEWER_REMOTE_VERSION_MSG, tb="")
                return
            # Älteres Remote (v1/v2) wird aufs aktuelle Schema migriert und normal
            # gemergt (absorb-and-upgrade). Dass ältere Geräte ein hochgezogenes
            # v4-Doc nicht überschreiben, sichert deren Push-Guard (ab v1.15.2).
            remote_doc = sync.migrate_doc_to_current(remote_doc)
            ok, reason = sync.validate_remote_doc(remote_doc)
            if not ok:
                # Strukturell defektes Remote-Doc (fehlende Pflichtfelder etc.)
                # wie korruptes JSON behandeln (Audit M5): quarantänen und leer
                # weitermergen, damit der lokale Stand zur neuen Remote-Wahrheit
                # wird — statt mitten im Merge mit KeyError/ValueError im
                # generischen except zu landen.
                logging.getLogger(__name__).warning(
                    "Remote-Sync-Doc ungültig (%s) — quarantäniert, starte leer", reason)
                if file_id is not None:
                    _quarantine(file_id)
                remote_doc = {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
            # Snapshot→Merge→Apply atomar: kein UI-Save kann zwischen
            # build_local_doc und apply_merged_doc interleaven (Audit H1).
            with _lock_ctx(data_lock):
                local_doc = sync.build_local_doc(storage, settings, conflicts_store)
                merged = sync.merge(local_doc, remote_doc, settings.get("last_pull_at") or "")
                sync_journal.apply_merged_doc_journaled(
                    merged, storage, settings, conflicts_store,
                    os.path.join(base, sync_journal.JOURNAL_FILENAME))
                settings.set_many({
                    "last_pull_at": utc_now_iso(),
                    "drive_etag": etag,
                })
                sync_history.mark_synced(base)
            ui_callback(ok=True, error=None, tb="")
        except Exception as e:
            tb = traceback.format_exc()
            logging.getLogger(__name__).exception("Sync pull failed")
            ui_callback(ok=False, error=e, tb=tb)
    finally:
        if sync_guard is not None:
            sync_guard.release()


def run_push_blocking(storage, settings, conflicts_store, base, timeout_seconds=5,
                       data_lock=None, sync_guard=None, guard_timeout=0):
    """Synchroner Push mit Timeout. Fehler werden geloggt, nicht angezeigt
    (App schließt gerade).

    sync_guard/guard_timeout (Audit H2/M1): Re-Entrancy-Guard. guard_timeout=0
    → non-blocking (zweiter Klick/Tray-Sync liefert {"skipped": True});
    guard_timeout>0 → blockierend warten (Quit-Push wartet auf einen laufenden
    Sync). Der Guard wird im INNEREN _do-Thread acquired UND im finally
    released — erst nach der letzten Store-Mutation. Ein per Join-Timeout
    „verwaister" Worker hält ihn dadurch bis zum echten Ende: er IST dann der
    laufende Sync, statt parallel zu einem neuen zu schreiben.
    data_lock (Audit H1): klammert Snapshot→Merge→Apply→Upload-Snapshot
    atomar; der Upload selbst läuft OHNE Daten-Lock (nie Lock über Netz)."""
    import json
    from src import drive, sync, sync_journal

    result = {}

    def _do():
        if sync_guard is not None:
            got = (sync_guard.acquire(timeout=guard_timeout) if guard_timeout > 0
                   else sync_guard.acquire(blocking=False))
            if not got:
                result["ok"] = False
                result["skipped"] = True
                return
        try:
            try:
                service = drive.get_drive_service(
                    os.path.join(base, "credentials.json"),
                    os.path.join(base, "token.json"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
                file_id = drive.find_sync_file(service)
                # Push = download -> Guard -> Merge -> upload. drive.upload kennt
                # kein File-level If-Match (ignoriert expected_etag), daher MUSS hier
                # das frische Remote-Doc gelesen und gemergt werden — sonst
                # überschreibt der Push fremde oder neuere Stände blind (Datenverlust
                # bzw. Clobber eines neueren Schemas während eines Rollouts).
                if file_id is not None:
                    remote_bytes, _etag = drive.download(service, file_id)
                    try:
                        remote_doc = json.loads(remote_bytes)
                    except (json.JSONDecodeError, ValueError):
                        remote_doc = {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
                    if sync.remote_is_newer(remote_doc):
                        # Neueres Gerät hat das Remote-Doc fortgeschrieben: nicht
                        # mergen/überschreiben — Push abbrechen, neuere Daten bleiben.
                        result["ok"] = False
                        result["error"] = sync.NEWER_REMOTE_VERSION_MSG
                        result["tb"] = ""
                        return
                else:
                    remote_doc = {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
                # Älteres Remote (v1/v2) absorbieren: aufs aktuelle Schema migrieren,
                # dann mergen — sonst gingen v2-only-Stände beim Upload verloren.
                remote_doc = sync.migrate_doc_to_current(remote_doc)
                ok, reason = sync.validate_remote_doc(remote_doc)
                if not ok:
                    # Defektes Remote wie korruptes JSON behandeln (Audit M5):
                    # leer weitermergen, der lokale Stand wird beim Upload zur
                    # neuen Remote-Wahrheit. (Der Push quarantänt nicht separat —
                    # der Upload überschreibt das defekte Remote ohnehin.)
                    logging.getLogger(__name__).warning(
                        "Remote-Sync-Doc ungültig (%s) — ignoriert, lokaler Stand gewinnt", reason)
                    remote_doc = {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
                # Snapshot→Merge→Apply→Upload-Snapshot atomar (Audit H1);
                # der Upload danach läuft bewusst ungelockt.
                with _lock_ctx(data_lock):
                    local_doc = sync.build_local_doc(storage, settings, conflicts_store)
                    merged = sync.merge(local_doc, remote_doc, settings.get("last_pull_at") or "")
                    sync_journal.apply_merged_doc_journaled(
                        merged, storage, settings, conflicts_store,
                        os.path.join(base, sync_journal.JOURNAL_FILENAME))
                    doc = sync.build_local_doc(storage, settings, conflicts_store)
                    content = json.dumps(doc, ensure_ascii=False).encode("utf-8")
                new_id, new_etag = drive.upload(service, content, file_id)
                settings.set_many({
                    "last_pull_at": utc_now_iso(),
                    "drive_etag": new_etag,
                })
                sync_history.mark_synced(base)
                result["ok"] = True
            except Exception as e:
                logging.getLogger(__name__).exception("Sync push failed: %s", e)
                result["ok"] = False
                result["error"] = str(e)
                result["tb"] = traceback.format_exc()
        finally:
            if sync_guard is not None:
                sync_guard.release()

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    if not result:
        result = {"ok": False, "error": "Timeout", "tb": ""}
    return result


def _run_compaction_blocking(storage, settings, conflicts_store, base, timeout_seconds=20,
                             data_lock=None, sync_guard=None):
    """User-ausgelöste Kompaktierung: frischer Pull → Alt-Client-Guard → Merge →
    Watermark setzen + lokal strippen → Push. Liefert
    {"ok": bool, "reason": str, "error": ..., "tb": ...}.

    reason == "newer_version": ein neueres Gerät hat ein Schema geschrieben, das
    diese Version nicht versteht — Kompaktierung abgebrochen, kein Merge/Upload
    (sonst würde das neuere Doc überschrieben). Ältere Remote-Docs (v1/v2) werden
    wie bei Pull/Push aufs aktuelle Schema migriert.

    sync_guard: non-blocking — läuft ein Sync, kommt {"skipped": True} zurück
    (der Settings-Dialog zeigt dann einen Hinweis). Release im finally des
    inneren _do-Threads. data_lock: klammert Merge/Apply/Kompaktierung atomar;
    der Upload läuft ungelockt (Invarianten wie run_push_blocking)."""
    import json
    from src import drive, sync, sync_journal

    result = {}

    def _do():
        if sync_guard is not None and not sync_guard.acquire(blocking=False):
            result["ok"] = False
            result["skipped"] = True
            return
        try:
            try:
                service = drive.get_drive_service(
                    os.path.join(base, "credentials.json"),
                    os.path.join(base, "token.json"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
                file_id = drive.find_sync_file(service)
                if file_id is not None:
                    content, _etag = drive.download(service, file_id)
                    try:
                        remote_doc = json.loads(content)
                    except (json.JSONDecodeError, ValueError):
                        remote_doc = {"schema_version": 1}
                    # Neueres Schema (>v3) auf dem FRISCH gepullten Doc: nicht
                    # mergen/überschreiben — Kompaktierung abbrechen.
                    if sync.remote_is_newer(remote_doc):
                        result.update({"ok": False, "reason": "newer_version"})
                        return
                else:
                    remote_doc = {"schema_version": 2, "entries": {}, "settings": {},
                                  "conflicts": [], "meta": {"gc_watermark": ""}}

                # Älteres Remote (v1/v2) absorbieren: aufs aktuelle Schema migrieren.
                remote_doc = sync.migrate_doc_to_current(remote_doc)
                ok, reason = sync.validate_remote_doc(remote_doc)
                if not ok:
                    # Defektes Remote wie korruptes JSON behandeln (Audit M5):
                    # leer weitermergen; die Kompaktierung schreibt danach den
                    # lokalen Stand als neue Remote-Wahrheit hoch.
                    logging.getLogger(__name__).warning(
                        "Remote-Sync-Doc ungültig (%s) — ignoriert, lokaler Stand gewinnt", reason)
                    remote_doc = {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
                now = utc_now_iso()
                # Merge + Apply + Watermark/Strippung + Upload-Snapshot atomar
                # (Audit H1); der Upload danach läuft bewusst ungelockt.
                with _lock_ctx(data_lock):
                    # 1) normaler Merge des frischen Remote-Stands
                    local_doc = sync.build_local_doc(storage, settings, conflicts_store)
                    merged = sync.merge(local_doc, remote_doc, settings.get("last_pull_at") or "")
                    sync_journal.apply_merged_doc_journaled(
                        merged, storage, settings, conflicts_store,
                        os.path.join(base, sync_journal.JOURNAL_FILENAME))
                    settings.set("last_pull_at", now)
                    # 2) Watermark setzen + lokal strippen
                    sync.compact_local(storage, settings, conflicts_store, now)
                    # 3) kompaktiertes Doc für den Upload snapshotten
                    doc = sync.build_local_doc(storage, settings, conflicts_store)
                    payload = json.dumps(doc, ensure_ascii=False).encode("utf-8")
                new_id, new_etag = drive.upload(service, payload, file_id)
                settings.set("drive_etag", new_etag)
                sync_history.mark_synced(base)
                result.update({"ok": True})
            except Exception as e:
                logging.getLogger(__name__).exception("Kompaktierung fehlgeschlagen")
                result.update({"ok": False, "error": str(e), "tb": traceback.format_exc()})
        finally:
            if sync_guard is not None:
                sync_guard.release()

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    if not result:
        result = {"ok": False, "error": "Timeout", "tb": ""}
    return result


def run_calendar_reconcile(reservation_store, settings, base, storage, data_lock=None):
    """Baut den Calendar-Service und fährt einen Reservierungs-Reconcile.

    Liefert {"ok": bool, "error": str, "tb": str, "limit_warnings": [...]}.
    Wirft NICHT — der Caller (UI-Thread) wertet das Dict aus. No-op, wenn
    gcal deaktiviert oder kein Kalender gewählt ist.

    data_lock wird an reconcile_reservations durchgereicht (Rebase+Apply atomar, Audit H1).

    limit_warnings (#98): Werkstudenten-Wochenlimit-Ergebnis (siehe
    weekly_limit.py) für die ISO-Wochen frisch importierter Reservierungs-
    Slots — geprüft werden dabei ausschließlich bereits erfasste Ist-Zeiten
    (storage), nicht die importierten Reservierungen selbst.
    """
    from src import gcal
    from src.reservations_sync import reconcile_reservations
    from src.weekly_limit import check_dates_for_warnings

    if not settings.get("gcal_enabled"):
        return {"ok": True, "error": "", "tb": "", "limit_warnings": []}
    calendar_id = settings.get("gcal_calendar_id")
    if not calendar_id:
        return {"ok": True, "error": "", "tb": "", "limit_warnings": []}

    try:
        service = gcal.get_calendar_service(
            os.path.join(base, "credentials.json"),
            os.path.join(base, "token.json"),
            sync_enabled=settings.get("sync_enabled"),
        )
        result = reconcile_reservations(service, calendar_id, reservation_store,
                                        settings, data_lock=data_lock)
        sync_history.mark_reconciled(base)
        limit_warnings = check_dates_for_warnings(
            settings, storage.get_all(), result["imported_dates"])
        return {"ok": True, "error": "", "tb": "", "limit_warnings": limit_warnings}
    except Exception as e:
        logging.getLogger(__name__).exception("Kalender-Reconcile fehlgeschlagen")
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "tb": traceback.format_exc(), "limit_warnings": []}


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

    storage = Storage(os.path.join(base, "zeiterfassung.json"),
                      device_id=device_id, lock=data_lock)

    conflicts_store = ConflictsStore(os.path.join(base, "conflicts.json"),
                                     lock=data_lock)

    reservation_store = ReservationStore(os.path.join(base, "reservations.json"),
                                         lock=data_lock)

    # M6: Ein unvollständig gebliebener Sync-Apply eines vorherigen Laufs
    # (Crash zwischen den vier Store-Writes) wird jetzt idempotent nachgeholt —
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
              data_lock=data_lock, sync_guard=sync_guard)

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
