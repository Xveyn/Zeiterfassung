"""Crash-Recovery für `sync.apply_merged_doc` (Audit M6).

`apply_merged_doc` schreibt das Merge-Ergebnis in **vier** separate Stores
nacheinander (storage, settings-synced, conflicts, gc_watermark). Jeder einzelne
Write ist atomar (`.tmp` + `os.replace`), die **Sequenz** ist es nicht: stürzt der
Prozess zwischen zwei Writes ab (Stromausfall, Kill), bleiben die Stores
inkonsistent — z. B. Storage-Tombstones gestrippt, aber das gc_watermark noch alt.

Dieses Modul klammert die vier Writes in ein **Write-Ahead-Journal**:

1. Der komplette `merged_doc` wird zuerst atomar + `fsync` in eine Journal-Datei
   geschrieben (durable, bevor irgendein Store angefasst wird).
2. `sync.apply_merged_doc` schreibt die vier Stores.
3. Das Journal wird gelöscht.

Existiert beim App-Start noch ein Journal, war der letzte Apply unvollständig →
er wird **idempotent** wiederholt. Das ist gefahrlos, weil alle vier Store-Ops
Full-Replace sind (`storage.apply_merge`/`conflicts_store.save_all` ersetzen den
kompletten Stand, `settings.apply_synced`/`set` sind für gleiche Eingabe
idempotent) — die Wiederholung reproduziert exakt denselben Endzustand.

Damit ist der Apply effektiv atomar: entweder das Journal ist weg (vollständig
angewandt) oder es existiert (wird beim nächsten Start vollständig nachgeholt).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
import logging
import os
import tempfile

from src import sync

if TYPE_CHECKING:  # nur fuer die Signaturen
    from src.conflicts_store import ConflictsStore
    from src.settings import Settings
    from src.storage import Storage

JOURNAL_FILENAME = "sync-apply.journal"


def _atomic_write_json(path: str, obj: Any) -> None:
    """Schreibt `obj` als JSON atomar + durable (fsync vor replace). Ohne den
    fsync könnte das Rename durabel sein, der Inhalt aber noch im OS-Cache —
    dann wäre das Journal beim Recovery leer/kurz (der Fall, gegen den es
    schützt)."""
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def apply_merged_doc_journaled(merged_doc: dict[str, Any], storage: Storage,
                               settings: Settings,
                               conflicts_store: ConflictsStore,
                               journal_path: str) -> None:
    """Wie `sync.apply_merged_doc`, aber crash-sicher über ein Journal (M6):
    merged_doc erst durable auf Platte, dann die vier Store-Writes, dann Journal
    löschen. Stürzt der Prozess dazwischen ab, holt `recover_pending_apply` den
    Apply beim nächsten Start nach."""
    _atomic_write_json(journal_path, merged_doc)
    sync.apply_merged_doc(merged_doc, storage, settings, conflicts_store)
    try:
        os.remove(journal_path)
    except FileNotFoundError:
        pass


def recover_pending_apply(journal_path: str, storage: Storage, settings: Settings,
                          conflicts_store: ConflictsStore) -> bool:
    """Beim App-Start (vor dem Start der Sync-Threads, single-threaded → kein
    Lock nötig) aufrufen: existiert ein Journal, war der letzte Apply
    unvollständig → idempotent wiederholen.

    Liefert True, wenn ein Journal nachgeholt wurde, sonst False."""
    log = logging.getLogger(__name__)
    if not os.path.exists(journal_path):
        return False
    try:
        with open(journal_path, "r", encoding="utf-8") as f:
            merged_doc = json.load(f)
    except (json.JSONDecodeError, ValueError, OSError):
        # Unlesbares Journal: dank atomic-write sollte das nicht vorkommen (ein
        # halb geschriebenes .tmp wird nie zu journal_path). Falls doch, ist der
        # sichere Zustand der Vor-Apply-Stand (Stores unverändert) — verwerfen.
        log.warning("Sync-Apply-Journal unlesbar — verworfen (Stores im "
                    "Vor-Apply-Zustand)", exc_info=True)
        _remove_quietly(journal_path)
        return False

    log.warning("Unvollständiger Sync-Apply gefunden — hole ihn nach (M6-Recovery)")
    sync.apply_merged_doc(merged_doc, storage, settings, conflicts_store)
    _remove_quietly(journal_path)
    return True


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
