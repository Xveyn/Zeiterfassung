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
from src.settings import Settings
from src.storage import Storage
from src.ui import App
from src.version import VERSION


def _ensure_device_id(settings):
    """Bei Erststart oder fehlendem device_id: UUID generieren und persistieren."""
    if not settings.get("device_id"):
        settings.set("device_id", str(uuid.uuid4()))


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
            )
            file_id = drive.find_sync_file(service)
            doc = sync.build_local_doc(storage, settings, conflicts_store)
            content = json.dumps(doc, ensure_ascii=False).encode("utf-8")
            expected_etag = settings.get("drive_etag")
            try:
                new_id, new_etag = drive.upload(service, content, file_id, expected_etag)
            except drive.DriveConflictError:
                # Etag-Mismatch: 1× pull-merge-push retry
                if file_id is not None:
                    remote_bytes, _ = drive.download(service, file_id)
                    remote_doc = json.loads(remote_bytes)
                else:
                    remote_doc = {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
                local_doc = sync.build_local_doc(storage, settings, conflicts_store)
                merged = sync.merge(local_doc, remote_doc, settings.get("last_pull_at") or "")
                sync.apply_merged_doc(merged, storage, settings, conflicts_store)
                doc = sync.build_local_doc(storage, settings, conflicts_store)
                content = json.dumps(doc, ensure_ascii=False).encode("utf-8")
                new_id, new_etag = drive.upload(service, content, file_id, expected_etag="")
            settings.set("drive_etag", new_etag)
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


def main():
    base = get_base_path()
    try:
        setup_logging(base)
        logging.getLogger(__name__).info("Zeiterfassung v%s gestartet", VERSION)
    except Exception:
        pass

    settings = Settings(os.path.join(base, "settings.json"))
    _ensure_device_id(settings)
    device_id = settings.get("device_id")
    settings.device_id_for_sync = device_id

    storage = Storage(os.path.join(base, "zeiterfassung.json"), device_id=device_id)

    conflicts_store = ConflictsStore(os.path.join(base, "conflicts.json"))

    root = tk.Tk()
    app = App(root, storage, settings, base_path=base, conflicts_store=conflicts_store)

    if "--minimized" in sys.argv:
        root.iconify()

    if settings.get("sync_enabled"):
        def _on_sync_done(ok, error, tb=""):
            def apply():
                if ok:
                    app.on_sync_pull_success()
                else:
                    app.on_sync_pull_error(error, tb)
            root.after(0, apply)
        threading.Thread(
            target=_run_pull_in_background,
            args=(storage, settings, conflicts_store, base, _on_sync_done),
            daemon=True,
        ).start()

    root.mainloop()


if __name__ == "__main__":
    main()
