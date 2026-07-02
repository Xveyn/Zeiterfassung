# src/main.py
import logging
import os
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
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from src.conflicts_store import ConflictsStore
from src.logging_setup import setup_logging
from src.paths import get_base_path
from src.reservations import ReservationStore
from src.settings import Settings, clamp_ui_scale
from src.storage import Storage
from src.theme import init_fonts
from src.ui import App
from src.version import VERSION


def _ensure_device_id(settings) -> str:
    """Bei Erststart oder fehlendem device_id: UUID generieren und persistieren.

    Liefert die garantiert vorhandene Device-ID — spart dem Caller einen
    zweiten settings.get()-Call (der Pylance-seitig wieder Optional wäre)."""
    device_id = settings.get("device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
        settings.set("device_id", device_id)
    return device_id


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


def _run_pull_in_background(storage, settings, conflicts_store, base, ui_callback):
    """Pull läuft in einem Thread; UI-Update über ui_callback (root.after)."""
    from src import drive, sync
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
        if sync._remote_is_newer(remote_doc):
            # Neueres (zukünftiges) Schema: NICHT mergen/pushen — Pull sauber
            # abbrechen, last_pull_at/etag unverändert lassen.
            ui_callback(ok=False, error=sync.NEWER_REMOTE_VERSION_MSG, tb="")
            return
        # Älteres Remote (v1/v2) wird aufs aktuelle Schema migriert und normal
        # gemergt (absorb-and-upgrade). Dass ältere Geräte ein hochgezogenes
        # v4-Doc nicht überschreiben, sichert deren Push-Guard (ab v1.15.2).
        remote_doc = sync.migrate_doc_to_current(remote_doc)
        local_doc = sync.build_local_doc(storage, settings, conflicts_store)
        merged = sync.merge(local_doc, remote_doc, settings.get("last_pull_at") or "")
        sync.apply_merged_doc(merged, storage, settings, conflicts_store)
        settings.set_many({
            "last_pull_at": sync._utc_now_iso(),
            "drive_etag": etag,
        })
        ui_callback(ok=True, error=None, tb="")
    except Exception as e:
        tb = traceback.format_exc()
        logging.getLogger(__name__).exception("Sync pull failed")
        ui_callback(ok=False, error=e, tb=tb)


def _run_push_blocking(storage, settings, conflicts_store, base, timeout_seconds=5):
    """Synchroner Push mit Timeout. Fehler werden geloggt, nicht angezeigt
    (App schließt gerade)."""
    import json
    from src import drive, sync

    result = {}

    def _do():
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
                if sync._remote_is_newer(remote_doc):
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
            local_doc = sync.build_local_doc(storage, settings, conflicts_store)
            merged = sync.merge(local_doc, remote_doc, settings.get("last_pull_at") or "")
            sync.apply_merged_doc(merged, storage, settings, conflicts_store)
            doc = sync.build_local_doc(storage, settings, conflicts_store)
            content = json.dumps(doc, ensure_ascii=False).encode("utf-8")
            new_id, new_etag = drive.upload(service, content, file_id, expected_etag="")
            settings.set_many({
                "last_pull_at": sync._utc_now_iso(),
                "drive_etag": new_etag,
            })
            result["ok"] = True
        except Exception as e:
            logging.getLogger(__name__).exception("Sync push failed: %s", e)
            result["ok"] = False
            result["error"] = str(e)
            result["tb"] = traceback.format_exc()

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    if not result:
        result = {"ok": False, "error": "Timeout", "tb": ""}
    return result


def _run_compaction_blocking(storage, settings, conflicts_store, base, timeout_seconds=20):
    """User-ausgelöste Kompaktierung: frischer Pull → Alt-Client-Guard → Merge →
    Watermark setzen + lokal strippen → Push. Liefert
    {"ok": bool, "reason": str, "error": ..., "tb": ...}.

    reason == "newer_version": ein neueres Gerät hat ein Schema geschrieben, das
    diese Version nicht versteht — Kompaktierung abgebrochen, kein Merge/Upload
    (sonst würde das neuere Doc überschrieben). Ältere Remote-Docs (v1/v2) werden
    wie bei Pull/Push aufs aktuelle Schema migriert."""
    import json
    from src import drive, sync

    result = {}

    def _do():
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
                if sync._remote_is_newer(remote_doc):
                    result.update({"ok": False, "reason": "newer_version"})
                    return
            else:
                remote_doc = {"schema_version": 2, "entries": {}, "settings": {},
                              "conflicts": [], "meta": {"gc_watermark": ""}}

            # Älteres Remote (v1/v2) absorbieren: aufs aktuelle Schema migrieren.
            remote_doc = sync.migrate_doc_to_current(remote_doc)
            # 1) normaler Merge des frischen Remote-Stands
            now = sync._utc_now_iso()
            local_doc = sync.build_local_doc(storage, settings, conflicts_store)
            merged = sync.merge(local_doc, remote_doc, settings.get("last_pull_at") or "")
            sync.apply_merged_doc(merged, storage, settings, conflicts_store)
            settings.set("last_pull_at", now)
            # 2) Watermark setzen + lokal strippen
            sync.compact_local(storage, settings, conflicts_store, now)
            # 3) kompaktiertes Doc hochladen
            doc = sync.build_local_doc(storage, settings, conflicts_store)
            payload = json.dumps(doc, ensure_ascii=False).encode("utf-8")
            new_id, new_etag = drive.upload(service, payload, file_id, expected_etag="")
            settings.set("drive_etag", new_etag)
            result.update({"ok": True})
        except Exception as e:
            logging.getLogger(__name__).exception("Kompaktierung fehlgeschlagen")
            result.update({"ok": False, "error": str(e), "tb": traceback.format_exc()})

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    if not result:
        result = {"ok": False, "error": "Timeout", "tb": ""}
    return result


def run_calendar_reconcile(reservation_store, settings, base, storage):
    """Baut den Calendar-Service und fährt einen Reservierungs-Reconcile.

    Liefert {"ok": bool, "error": str, "tb": str, "limit_warnings": [...]}.
    Wirft NICHT — der Caller (UI-Thread) wertet das Dict aus. No-op, wenn
    gcal deaktiviert oder kein Kalender gewählt ist.

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
        result = reconcile_reservations(service, calendar_id, reservation_store, settings)
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


def main():
    base = get_base_path()
    try:
        setup_logging(base)
        logging.getLogger(__name__).info("Zeiterfassung v%s gestartet", VERSION)
    except Exception:
        pass

    settings = Settings(os.path.join(base, "settings.json"))
    device_id = _ensure_device_id(settings)
    settings.device_id_for_sync = device_id

    storage = Storage(os.path.join(base, "zeiterfassung.json"), device_id=device_id)

    conflicts_store = ConflictsStore(os.path.join(base, "conflicts.json"))

    reservation_store = ReservationStore(os.path.join(base, "reservations.json"))

    root = tk.Tk()
    _apply_ui_scaling(root, settings.get("ui_scale"))
    app = App(root, storage, settings, base_path=base, conflicts_store=conflicts_store,
              reservation_store=reservation_store)

    if "--minimized" in sys.argv:
        root.iconify()

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
            target=_run_pull_in_background,
            args=(storage, settings, conflicts_store, base, _on_sync_done),
            daemon=True,
        ).start()

    root.mainloop()


if __name__ == "__main__":
    main()
