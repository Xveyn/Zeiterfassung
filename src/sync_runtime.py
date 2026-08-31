# src/sync_runtime.py
"""Sync-, Kompaktierungs- und Reconcile-Runtime.

Bis Issue #49/#51 (R1) wohnten diese Flows in `main.py`. Damit war der
Einstiegspunkt zugleich Bibliothek: vier Module importierten lazy zurück nach
`src.main`, jedes mit einem „Circular-Import-Schutz"-Kommentar. Die Flows
stehen jetzt hier, `main.py` bleibt Bootstrap.

Aufrufer: `main.py` (Startup-Pull), `sync_orchestrator.py` (Push),
`background_tasks.py` (Reconcile), `dialogs/settings_dialog/tab_google.py`
(Kompaktierung).

Die Google-Wrapper (`drive`, `gcal`, `reservations_sync`) werden bewusst
**lazy in den Funktionen** importiert — wie in `drive.py`/`gcal.py` selbst,
damit die CI ohne `requirements.txt` durchläuft (siehe `src/CLAUDE.md`).

Die beiden Lock-Invarianten (Audit H1/H2) leben in diesen Funktionen und sind
je Funktion im Docstring beschrieben: `data_lock` klammert
Snapshot→Merge→Apply, `sync_guard` verhindert parallele Sync-Läufe. Nie einen
Lock über einen Netzaufruf halten.
"""

import contextlib
import logging
import os
import threading
import traceback

from src import sync_history
from src.time_utils import utc_now_iso


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


def run_compaction_blocking(storage, settings, conflicts_store, base, timeout_seconds=20,
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


def run_vacation_purge(settings, base, vacation_store, data_lock=None):
    """Räumt die Urlaubs-Events der App aus dem Kalender — der Weg zurück,
    wenn `vacation_gcal_enabled` abgeschaltet wird.

    Liefert {"ok": bool, "error": str, "tb": str} und wirft nie; der Aufrufer
    (`vacation_dialog`) entscheidet, ob er den Fehler zeigt. Ohne aktiven
    Kalender gibt es nichts aufzuräumen — dann ist der Lauf ein stiller
    Erfolg, nicht etwa ein Fehler: es kann in dem Fall auch nie etwas
    gepusht worden sein.

    Läuft über `runner.run` in einem Hintergrund-Thread (Audit H5) — der
    Aufräum-Lauf listet und löscht über das Netz und darf die UI nicht
    blockieren.
    """
    from src import gcal
    from src.vacations_sync import purge_vacation_events

    calendar_id = settings.get("gcal_calendar_id")
    if (vacation_store is None or not settings.get("gcal_enabled")
            or not calendar_id):
        return {"ok": True, "error": "", "tb": ""}

    try:
        service = gcal.get_calendar_service(
            os.path.join(base, "credentials.json"),
            os.path.join(base, "token.json"),
            sync_enabled=settings.get("sync_enabled"),
        )
        purge_vacation_events(service, calendar_id, vacation_store,
                              data_lock=data_lock)
        return {"ok": True, "error": "", "tb": ""}
    except Exception as e:
        logging.getLogger(__name__).exception("Urlaubs-Aufräumen fehlgeschlagen")
        return {"ok": False, "error": str(e), "tb": traceback.format_exc()}


def run_calendar_reconcile(reservation_store, settings, base, storage,
                           data_lock=None, vacation_store=None):
    """Baut den Calendar-Service und fährt einen Reservierungs-Reconcile.

    Liefert {"ok": bool, "error": str, "tb": str, "limit_warnings": [...]}.
    Wirft NICHT — der Caller (UI-Thread) wertet das Dict aus. No-op, wenn
    gcal deaktiviert oder kein Kalender gewählt ist.

    data_lock wird an reconcile_reservations durchgereicht (Rebase+Apply atomar, Audit H1).

    limit_warnings (#98): Werkstudenten-Wochenlimit-Ergebnis (siehe
    weekly_limit.py) für die ISO-Wochen frisch importierter Reservierungs-
    Slots — geprüft werden dabei ausschließlich bereits erfasste Ist-Zeiten
    (storage), nicht die importierten Reservierungen selbst.

    vacation_store (optional, Default None → kein Push): pusht im Anschluss
    die Urlaubsperioden als Ganztags-Events, sofern
    `settings["vacation_gcal_enabled"]` gesetzt ist. Läuft NACH
    `mark_reconciled` und in einem eigenen try/except — additiv, darf einen
    bereits gelungenen Reservierungs-Abgleich nicht mitreißen (s.
    reconcile_vacations-Aufruf unten). Das Gegenstück zum Abschalten des
    Schalters ist `run_vacation_purge`.
    """
    from src import gcal
    from src.reservations_sync import reconcile_reservations
    from src.vacations_sync import reconcile_vacations
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
        # Urlaubs-Push zuletzt und bewusst NICHT-FATAL: derselbe Service,
        # dasselbe gcal_enabled-Gate, derselbe data_lock — aber ein eigener
        # Fehlerraum. Läge er im gemeinsamen try, risse ein scheiternder Push
        # (API-Problem) einen erfolgreichen Reservierungs-Abgleich mit: der
        # sync_history-Marker bliebe ungesetzt, und genau der vetot den
        # N6-Startup-Sweep gegen einen settings.json-Reset (M4) — Folge wäre
        # die Tombstone-Resurrection, gegen die sync_history.py existiert.
        # Zusätzlich gingen die Werkstudenten-Warnungen (#98) verloren.
        if (vacation_store is not None
                and settings.get("vacation_gcal_enabled")):
            try:
                reconcile_vacations(service, calendar_id, vacation_store,
                                    data_lock=data_lock)
            except Exception:
                logging.getLogger(__name__).exception(
                    "Urlaubs-Push fehlgeschlagen (nicht-fatal)")
        return {"ok": True, "error": "", "tb": "", "limit_warnings": limit_warnings}
    except Exception as e:
        logging.getLogger(__name__).exception("Kalender-Reconcile fehlgeschlagen")
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "tb": traceback.format_exc(), "limit_warnings": []}
