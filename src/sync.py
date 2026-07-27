"""Sync-Engine: pure Funktionen ohne I/O. Drive-Calls leben in src/drive.py.

Doc-Struktur (Sync-File und Zwischenformate), Stand SCHEMA_VERSION = 4:
{
  "schema_version": 4,
  "entries":   {date: {slots: [{start, end, pause, kategorie}],
                       modified_at, device_id, deleted}},
  "settings":  {key:  {value, modified_at, device_id}},
  "conflicts": [{id, kind, key, candidates, detected_at,
                 resolved, resolution, resolved_at, resolved_by}],
  "meta":      {gc_watermark}
}
"""

from __future__ import annotations

import contextlib
import uuid
from typing import TYPE_CHECKING, Any, Callable

# SYNCED_SETTING_KEYS lebt als Single Source of Truth in settings.py — hier nur
# importieren, NICHT erneut definieren. Eine zweite (divergierende) Definition
# würde dazu führen, dass sync.py einen synchronisierten Key nicht mergt →
# stiller Datenverlust im Multi-Device-Sync (Issue #48). settings.py ist
# stdlib-only und importiert sync.py nicht (kein Zyklus, CI-import-sicher).
from src.settings import SYNCED_SETTING_KEYS
from src.time_utils import utc_now_iso
# REQUIRED_ENTRY_KEYS ist der Pflichtfeld-Vertrag, den storage.apply_merge
# erzwingt — hier als Single Source of Truth importieren (nicht duplizieren),
# damit validate_remote_doc nie gegen einen anderen Feldsatz prüft als der
# Store später schreibt. storage.py importiert sync.py nicht (kein Zyklus).
from src.storage import REQUIRED_ENTRY_KEYS

if TYPE_CHECKING:
    import threading

    from src.conflicts_store import ConflictsStore
    from src.settings import Settings
    from src.storage import Storage

# JSON-getragene Sync-Strukturen (Audit N8). Doc = ein komplettes Sync-Doc
# ({schema_version, entries, settings, conflicts, meta}); Entry = ein
# Eintrag-Record; Conflict = ein Konflikt-Record. Werte heterogen → Any.
Doc = dict[str, Any]
Entry = dict[str, Any]
Conflict = dict[str, Any]


SCHEMA_VERSION = 4


NEWER_REMOTE_VERSION_MSG = (
    "Ein anderes Gerät nutzt eine neuere App-Version mit einem Datenformat, "
    "das diese (ältere) Version noch nicht versteht.\n\n"
    "Bitte aktualisiere die App auf diesem Gerät. Bis dahin pausiert die "
    "Synchronisation, damit keine Daten verloren gehen oder überschrieben werden."
)


def _watermark_of(doc: Doc) -> str:
    return ((doc.get("meta") or {}).get("gc_watermark") or "")


def _is_settled_entry(entry: Entry, watermark: str) -> bool:
    return bool(entry.get("deleted")) and (entry.get("modified_at") or "") < watermark


def _is_settled_conflict(conflict: Conflict, watermark: str) -> bool:
    resolved_at = conflict.get("resolved_at") or ""
    return bool(conflict.get("resolved")) and resolved_at != "" and resolved_at < watermark


def _slots_signature(entry: Entry) -> list[tuple[Any, ...]]:
    """Reihenfolge-normalisierte Signatur der Slot-Liste eines Eintrags,
    für den Gleichheitsvergleich im Merge. Sortiert nach den Slot-Feldern,
    damit eine reine Umordnung der Slots NICHT als Änderung zählt."""
    return sorted(
        (s.get("start"), s.get("end"), s.get("pause", 0), s.get("kategorie", ""))
        for s in (entry.get("slots") or [])
    )


def _values_equal_entry(a: Entry, b: Entry) -> bool:
    return (_slots_signature(a) == _slots_signature(b)
            and bool(a.get("deleted")) == bool(b.get("deleted")))


def _values_equal_setting(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a.get("value") == b.get("value")


def _merge_one(local: dict[str, Any] | None, remote: dict[str, Any] | None,
               last_pull_at: str, equal_fn: Callable[[Any, Any], bool] = _values_equal_entry,
               kind: str = "entry", key: str | None = None
               ) -> tuple[dict[str, Any] | None, Conflict | None]:
    """LWW-Merge eines einzelnen Werts.

    Returns: (winner_dict, conflict_or_none)

    - Wenn nur eine Seite vorhanden ist → diese Seite gewinnt, kein Conflict.
    - Werte gleich → eine Seite gewinnt, kein Conflict.
    - Werte unterschiedlich, beide modified_at > last_pull_at → Conflict
      mit beiden Kandidaten, provisorischer Wert ist der jüngere (LWW).
    - Werte unterschiedlich, nur eine Seite seit last_pull_at geändert →
      diese Seite gewinnt (kein Conflict).
    """
    if local is None and remote is None:
        return (None, None)
    if local is None:
        return (remote, None)
    if remote is None:
        return (local, None)
    if equal_fn(local, remote):
        # jüngerer modified_at gewinnt — bei tie egal
        winner = remote if remote["modified_at"] >= local["modified_at"] else local
        return (winner, None)

    local_changed = local["modified_at"] > last_pull_at
    remote_changed = remote["modified_at"] > last_pull_at

    # N2 (LWW-Wanduhr-Abhängigkeit — bewusst festgehalten): `modified_at` ist eine
    # Wanduhr-Zeit (utc_now_iso, Sekunden-Auflösung, KEINE Millisekunden). Der
    # Vergleich ist ein String-Vergleich der ISO-Timestamps. Das LWW-Ergebnis
    # hängt damit an halbwegs synchronen Geräte-Uhren; eine stark falsch gehende
    # Uhr kann Änderungen dauerhaft gewinnen/verlieren lassen. Bei exakt gleicher
    # Sekunde bevorzugt `>=` deterministisch die REMOTE-Seite (arbiträr, aber
    # stabil) — akzeptierter Trade-off für ein Ein-Nutzer-Multi-Device-Tool.
    winner = remote if remote["modified_at"] >= local["modified_at"] else local

    if local_changed and remote_changed:
        conflict = {
            "id": str(uuid.uuid4()),
            "kind": kind,
            "key": key,
            "candidates": [_strip_for_candidate(local), _strip_for_candidate(remote)],
            "detected_at": utc_now_iso(),
            "resolved": False,
            "resolution": None,
            "resolved_at": None,
            "resolved_by": None,
        }
        return (winner, conflict)
    return (winner, None)


def _strip_for_candidate(item: dict[str, Any]) -> dict[str, Any]:
    """Reduziert ein Entry/Setting auf das, was im conflict.candidates landen soll."""
    return {k: v for k, v in item.items()}


def _merge_conflict_pair(a: Conflict, b: Conflict) -> Conflict:
    """LWW auf resolved_at, resolved beats unresolved."""
    if a.get("resolved") and not b.get("resolved"):
        return a
    if b.get("resolved") and not a.get("resolved"):
        return b
    if a.get("resolved") and b.get("resolved"):
        return a if (a.get("resolved_at") or "") >= (b.get("resolved_at") or "") else b
    return a  # beide unresolved — ID-Match heißt dasselbe Detection-Event


def _equivalent_unresolved_exists(existing: list[Conflict], new_conflict: Conflict) -> bool:
    """Dedupe: existiert bereits ein unresolved Konflikt mit gleichem
    (kind, key, Kandidaten-Set)?"""
    if new_conflict.get("resolved"):
        return False
    new_keys = _candidate_signatures(new_conflict["candidates"])
    for c in existing:
        if c.get("resolved"):
            continue
        if c["kind"] != new_conflict["kind"] or c["key"] != new_conflict["key"]:
            continue
        if _candidate_signatures(c["candidates"]) == new_keys:
            return True
    return False


def _candidate_signatures(candidates: list[dict[str, Any]]) -> tuple[tuple[Any, Any], ...]:
    """Sortiertes Tuple aus (modified_at, device_id) — als Set-Vergleichsbasis."""
    return tuple(sorted((c.get("modified_at"), c.get("device_id")) for c in candidates))


def merge(local: Doc, remote: Doc, last_pull_at: str) -> Doc:
    merged = {
        "schema_version": SCHEMA_VERSION,
        "entries": {},
        "settings": {},
        "conflicts": [],
        "meta": {"gc_watermark": ""},
    }
    watermark = max(_watermark_of(local), _watermark_of(remote))
    merged["meta"]["gc_watermark"] = watermark
    remote_wm = _watermark_of(remote)
    excluded = bool(last_pull_at) and last_pull_at < remote_wm
    new_conflicts = []

    # Entries
    all_entry_keys = set(local.get("entries", {}).keys()) | set(remote.get("entries", {}).keys())
    for key in all_entry_keys:
        loc = local.get("entries", {}).get(key)
        rem = remote.get("entries", {}).get(key)
        winner, conflict = _merge_one(loc, rem, last_pull_at,
                                       equal_fn=_values_equal_entry, kind="entry", key=key)
        # Regel 2: Self-Heal — ein zurückgekehrtes (excluded) Gerät darf einen
        # alten, remote-fehlenden lebenden Eintrag nicht auferstehen lassen.
        if (excluded and rem is None and loc is not None
                and (loc.get("modified_at") or "") < remote_wm):
            winner = None
        if winner is not None:
            merged["entries"][key] = winner
        if conflict is not None:
            new_conflicts.append(conflict)

    # Settings (Whitelist)
    for key in SYNCED_SETTING_KEYS:
        loc = local.get("settings", {}).get(key)
        rem = remote.get("settings", {}).get(key)
        winner, conflict = _merge_one(loc, rem, last_pull_at,
                                       equal_fn=_values_equal_setting, kind="setting", key=key)
        if winner is not None:
            merged["settings"][key] = winner
        if conflict is not None:
            new_conflicts.append(conflict)

    # Conflicts-Liste: Union by ID
    by_id = {}
    for c in local.get("conflicts", []) + remote.get("conflicts", []):
        cid = c["id"]
        if cid in by_id:
            by_id[cid] = _merge_conflict_pair(by_id[cid], c)
        else:
            by_id[cid] = c

    # Neu erkannte Konflikte dazu, mit Dedup
    existing = list(by_id.values())
    for c in new_conflicts:
        if not _equivalent_unresolved_exists(existing, c):
            by_id[c["id"]] = c
            existing.append(c)

    merged["conflicts"] = list(by_id.values())

    # Resolutions anwenden: jeder resolved Konflikt überschreibt entries/settings,
    # falls die Resolution jünger ist als der aktuelle merged-Wert.
    for c in merged["conflicts"]:
        if not c.get("resolved"):
            continue
        resolution = c.get("resolution") or {}
        resolved_at = c.get("resolved_at") or ""
        resolved_by = c.get("resolved_by") or ""
        if c["kind"] == "entry":
            current = merged["entries"].get(c["key"])
            if current is None or current["modified_at"] < resolved_at:
                merged["entries"][c["key"]] = {
                    "slots": resolution.get("slots", []),
                    "modified_at": resolved_at,
                    "device_id": resolved_by,
                    "deleted": bool(resolution.get("deleted", False)),
                }
        elif c["kind"] == "setting":
            current = merged["settings"].get(c["key"])
            if current is None or current["modified_at"] < resolved_at:
                merged["settings"][c["key"]] = {
                    "value": resolution.get("value"),
                    "modified_at": resolved_at,
                    "device_id": resolved_by,
                }

    # Regel 1: settled Tombstones entfernen (Kompaktierung propagieren).
    # Läuft NACH der Resolution-Application, damit kein resolved-Wert verloren geht.
    if watermark:
        merged["entries"] = {
            k: v for k, v in merged["entries"].items()
            if not _is_settled_entry(v, watermark)
        }
        merged["conflicts"] = [
            c for c in merged["conflicts"]
            if not _is_settled_conflict(c, watermark)
        ]

    return merged


def build_local_doc(storage: Storage, settings: Settings,
                    conflicts_store: ConflictsStore) -> Doc:
    """Erzeugt das Sync-Doc-Format aus den lokalen Stores."""
    return {
        "schema_version": SCHEMA_VERSION,
        "entries": storage.get_all_raw(),
        "settings": settings.get_synced_doc(),
        "conflicts": conflicts_store.get_all(),
        "meta": {"gc_watermark": settings.get("gc_watermark") or ""},
    }


def apply_merged_doc(merged_doc: Doc, storage: Storage, settings: Settings,
                     conflicts_store: ConflictsStore) -> None:
    """Schreibt das Merge-Ergebnis zurück in die lokalen Stores."""
    storage.apply_merge(merged_doc.get("entries", {}))
    settings.apply_synced(merged_doc.get("settings", {}))
    conflicts_store.save_all(merged_doc.get("conflicts", []))
    settings.set("gc_watermark", (merged_doc.get("meta") or {}).get("gc_watermark") or "")


def compact_local(storage: Storage, settings: Settings,
                  conflicts_store: ConflictsStore, now: str) -> None:
    """Schreibt das gc_watermark lokal und strippt settled Tombstones aus
    Storage und ConflictsStore. Ein lokaler Schreibvorgang pro Store
    (Wiederverwendung von storage.apply_merge — Required-Key-Validator +
    Atomic-Write bleiben auf einem Pfad)."""
    settings.set("gc_watermark", now)
    storage.apply_merge({
        k: v for k, v in storage.get_all_raw().items()
        if not _is_settled_entry(v, now)
    })
    conflicts_store.save_all([
        c for c in conflicts_store.get_all()
        if not _is_settled_conflict(c, now)
    ])


def never_synced(settings: Settings) -> bool:
    """True, wenn dieser Rechner nachweislich nie an einem Drive-Sync
    teilgenommen hat: Sync ist aus UND es gab nie einen Pull."""
    return not settings.get("sync_enabled") and not (settings.get("last_pull_at") or "")


def drop_orphan_tombstones(storage: Storage, settings: Settings) -> int:
    """Verwirft Tombstones ohne Sync-Partner. Liefert die Anzahl (0 = No-op).

    Ein Tombstone hat genau einen Zweck: beim Merge ein veraltetes Save eines
    anderen Geräts zu schlagen. Ohne Sync erfüllt er ihn nie und bleibt
    trotzdem für immer liegen — jeder gelöschte Tag wächst die Datei um eine
    Zeile, ohne dass es je einen GC-Pfad gäbe (Audit N6): die Kompaktierung
    hängt am Google-Tab und ist ohne Sync gar nicht erreichbar.

    Die Bedingung ist bewusst eng (`never_synced`): Sync AUS reicht nicht.
    Wer den Sync abschaltet, dessen Remote kennt die gelöschten Tage weiter —
    fiele der Tombstone hier, kämen sie beim Wiedereinschalten zurück. Für
    diese Gruppe bleibt die Kompaktierung der richtige Weg, weil sie über das
    gc_watermark alle Geräte einbezieht.

    Kein Watermark, keine Alters-Schwelle: ohne Sync gibt es niemanden, mit
    dem etwas abzustimmen wäre.
    """
    if not never_synced(settings):
        return 0
    raw = storage.get_all_raw()
    kept = {k: v for k, v in raw.items() if not v.get("deleted")}
    dropped = len(raw) - len(kept)
    if dropped:
        # apply_merge statt eigenem Write: Required-Key-Validator und
        # Atomic-Write bleiben auf einem Pfad (wie in compact_local).
        storage.apply_merge(kept)
    return dropped


def migrate_doc_to_current(remote_doc: Doc) -> Doc:
    """Migriert ein älteres Sync-Doc auf das aktuelle Schema (v4): flache Einträge
    (start/end/pause) werden in eine Slot-Liste gewrappt. Idempotent — Einträge mit
    `slots` bleiben unangetastet; Tombstones bekommen eine leere Slot-Liste.
    settings/conflicts/meta bleiben unberührt (per_day-category_times ist additiv in
    den Settings und braucht keine Doc-Migration).

    Damit absorbiert ein aktueller Client ein älteres (v1–v3) Remote-Doc und zieht es
    hoch, statt es abzuweisen oder beim Push zu plätten."""
    entries = remote_doc.get("entries") or {}
    migrated = {}
    for date, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        if "slots" in entry:
            migrated[date] = entry
            continue
        if entry.get("deleted"):
            slots = []
        else:
            slots = [{
                "start": entry.get("start"),
                "end": entry.get("end"),
                "pause": entry.get("pause", 0),
                "kategorie": "",
            }]
        migrated[date] = {
            "slots": slots,
            "modified_at": entry.get("modified_at"),
            "device_id": entry.get("device_id"),
            "deleted": bool(entry.get("deleted", False)),
        }
    return {**remote_doc, "schema_version": SCHEMA_VERSION, "entries": migrated}


def validate_remote_doc(doc: Any) -> tuple[bool, str]:
    """Prüft ein (bereits auf SCHEMA_VERSION migriertes) Remote-Doc auf die
    strukturellen Invarianten, die `merge`/`apply_merged_doc` voraussetzen —
    BEVOR ein `KeyError`/`ValueError` mitten im Merge landet (Audit M5).

    Der Merge greift an mehreren Stellen ungeprüft zu: `entry["modified_at"]`
    beim LWW-Vergleich (`_merge_one`), `conflict["id"]` bei der Union-by-ID,
    und `storage.apply_merge` wirft `ValueError`, wenn einem Eintrag eines der
    Pflichtfelder (`slots`/`modified_at`/`device_id`/`deleted`) fehlt. Ein
    defektes/manipuliertes Remote-Doc landet sonst im generischen
    `except Exception` als „unerwarteter Fehler".

    Liefert `(True, "")` oder `(False, grund)`. Ein invalides Doc behandelt der
    Aufrufer wie korruptes JSON: Remote-File quarantänen und leer weitermergen
    (lokaler Stand wird zur neuen Remote-Wahrheit)."""
    if not isinstance(doc, dict):
        return False, "Doc ist kein Objekt"

    entries = doc.get("entries", {})
    if not isinstance(entries, dict):
        return False, "entries ist kein Objekt"
    for date, entry in entries.items():
        if not isinstance(entry, dict):
            return False, f"entry {date!r} ist kein Objekt"
        missing = REQUIRED_ENTRY_KEYS - entry.keys()
        if missing:
            return False, f"entry {date!r} fehlen Felder {sorted(missing)}"
        if not isinstance(entry.get("modified_at"), str):
            return False, f"entry {date!r}: modified_at ist kein String"
        if not isinstance(entry.get("slots"), list):
            return False, f"entry {date!r}: slots ist keine Liste"

    settings = doc.get("settings", {})
    if not isinstance(settings, dict):
        return False, "settings ist kein Objekt"
    for skey, payload in settings.items():
        if not isinstance(payload, dict):
            return False, f"setting {skey!r} ist kein Objekt"
        if "value" not in payload:
            return False, f"setting {skey!r} ohne value"
        if not isinstance(payload.get("modified_at"), str):
            return False, f"setting {skey!r}: modified_at ist kein String"

    conflicts = doc.get("conflicts", [])
    if not isinstance(conflicts, list):
        return False, "conflicts ist keine Liste"
    for c in conflicts:
        if not isinstance(c, dict):
            return False, "conflict ist kein Objekt"
        if not isinstance(c.get("id"), str) or not c.get("id"):
            return False, "conflict ohne gültige id"
        if c.get("kind") not in ("entry", "setting"):
            return False, "conflict mit ungültigem kind"
        if "key" not in c:
            return False, "conflict ohne key"
        if not isinstance(c.get("candidates"), list):
            return False, "conflict ohne candidates-Liste"

    return True, ""


def remote_is_newer(remote_doc: Doc) -> bool:
    """True, wenn das Remote-Doc von einer NEUEREN App-Version stammt
    (schema_version > der hier verstandenen SCHEMA_VERSION).

    Forward-Compat-Guard: Ab Schema 3 enthalten Einträge `slots` statt der
    flachen `start/end/pause`-Keys. Würde diese ältere Version so ein Doc
    mergen und via `storage.apply_merge` schreiben, bräche der Required-Key-
    Validator hart ab ("missing keys ['start','end','pause']"). Stattdessen
    muss der Pull/Push abbrechen, ohne das neuere Remote-Doc zu überschreiben."""
    return (remote_doc.get("schema_version") or 1) > SCHEMA_VERSION


def resolve_conflict(conflict_id: str, chosen_value: dict[str, Any],
                     conflicts_store: ConflictsStore, storage: Storage, settings: Settings,
                     device_id: str, data_lock: threading.RLock | None = None) -> None:
    """User hat einen Konflikt aufgelöst. chosen_value enthält den gewählten
    (oder manuell editierten) Wert. Für entries: {slots: [...]} (und
    optional deleted). Für settings: {value}.
    Schreibt den Wert in den entsprechenden Store und markiert den Konflikt
    als resolved im ConflictsStore.

    data_lock: geteilter Store-RLock (Whole-Branch-Review-Finding). Die
    Read-Modify-Write-Spanne (get_all → mutieren → storage/settings-Write →
    save_all) muss atomar gegen einen parallel laufenden Hintergrund-Sync
    sein — dessen apply_merged_doc kann sonst zwischen dem Lesen und dem
    Zurückschreiben in conflicts_store schreiben, wodurch der stale Snapshot
    hier die frisch gemergte Änderung überschreibt/verliert. sync.py ist ein
    pure Modul und darf nicht aus src.main importieren (Circular-Import) —
    daher optionaler Parameter mit Default None + contextlib.nullcontext,
    genau wie in reservations_sync.py."""
    with (data_lock if data_lock is not None else contextlib.nullcontext()):
        all_conflicts = conflicts_store.get_all()
        target = next((c for c in all_conflicts if c["id"] == conflict_id), None)
        if target is None:
            raise KeyError(f"Konflikt {conflict_id!r} nicht gefunden")

        now = utc_now_iso()
        target["resolved"] = True
        target["resolution"] = dict(chosen_value)
        target["resolved_at"] = now
        target["resolved_by"] = device_id

        if target["kind"] == "entry":
            if chosen_value.get("deleted"):
                storage.delete(target["key"])
            else:
                storage.save(target["key"], chosen_value.get("slots", []))
        elif target["kind"] == "setting":
            settings.set_synced(target["key"], chosen_value.get("value"))

        conflicts_store.save_all(all_conflicts)
