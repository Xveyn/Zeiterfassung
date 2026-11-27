# pyright: reportOptionalMemberAccess=true
"""Sync-Engine: pure Funktionen ohne I/O. Drive-Calls leben in src/drive.py.

Doc-Struktur (Sync-File und Zwischenformate), Stand SCHEMA_VERSION = 4:
{
  "schema_version": 4,
  "entries":   {date: {slots: [{start, end, pause, kategorie}],
                       modified_at, device_id, deleted, notes?}},
  "settings":  {key:  {value, modified_at, device_id}},
  "conflicts": [{id, kind, key, candidates, detected_at,
                 resolved, resolution, resolved_at, resolved_by}],
  "devices":   {device_id: {name, updated_at}},   # optional, s.u.
  "sick":      {date: {minutes, modified_at, device_id, deleted}},   # optional, s.u.
  "meta":      {gc_watermark}
}

`notes` ({start: Notiz}, Xveyn#519) ist wie `devices` additiv: ein Eintrag trägt den
Schlüssel, wenn der Tag Notizen hat oder hatte, ein Tombstone als `{}`, wenn der
gelöschte Stand ihn trug. Die `resolution` eines Eintrags-Konflikts trägt ihn auf
oberster Ebene neben `slots`/`deleted`, wenn ein neues Gerät aufgelöst hat und der
Tag Notizen hat oder hatte. Ältere Clients behalten ihn am Eintrag als unbekannten
Schlüssel; Regeln in `slot_notes.py` und `_merge_entry`.

`devices` ist die Geräte-Registry (s. `devices.py`): sie übersetzt die
`device_id` in einen lesbaren Namen für die Anzeige (Konfliktdialog). Sie ist
bewusst **additiv ohne Schema-Bump** — SCHEMA_VERSION bleibt 4. Eine 5 würde
über `remote_is_newer` den Sync jedes älteren Geräts dauerhaft pausieren, und
das wäre für ein reines Anzeigefeld völlig unverhältnismäßig. Konsequenzen:

* Ältere Clients ignorieren das Feld (ihr `validate_remote_doc` prüft nur
  entries/settings/conflicts) und lassen es beim eigenen Push fallen, weil ihr
  `merge` feste Keys baut. Jedes neuere Gerät trägt sich beim nächsten Push
  wieder ein — der Verlust heilt sich selbst.
* Fehlt oder bricht das Feld, fällt die Anzeige auf die gekürzte `device_id`
  zurück: exakt das Verhalten von vor diesem Feature. Ein kaputtes `devices`
  ist deshalb **kein** Validierungsfehler — es wird verworfen, nicht das Doc.

`sick` (Krankheitstage, s. `sick_days.py`) ist ebenso additiv ohne Schema-Bump und
steht nur im Doc, wenn ein Gerät Krankheitstage (auch Tombstones) hat. Ältere
Clients lassen den Bereich beim Push fallen, deshalb heißt **Fehlen nie
„gelöscht“**: ein neueres Gerät lädt seinen Stand beim nächsten Push wieder hoch,
Self-Heal greift nur gegen einen vorhandenen Bereich. Je Tag gewinnt der neuere
Datensatz (`_lww_key`), Konflikte gibt es keine. Ein kaputter Bereich oder
Datensatz wird verworfen, nicht das Doc.
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Callable

# SYNCED_SETTING_KEYS lebt als Single Source of Truth in settings.py — hier nur
# importieren, NICHT erneut definieren. Eine zweite (divergierende) Definition
# würde dazu führen, dass sync.py einen synchronisierten Key nicht mergt →
# stiller Datenverlust im Multi-Device-Sync (Issue #48). settings.py ist
# stdlib-only und importiert sync.py nicht (kein Zyklus, CI-import-sicher).
from src.settings import SYNCED_SETTING_KEYS
from src.time_utils import utc_now_iso
# Registry-Logik (Sanitizing, LWW, eigener Eintrag) liegt Tk- und I/O-frei in
# devices.py — hier nur angewandt.
from src.devices import merge_registries, sanitize_registry, with_own_entry
# REQUIRED_ENTRY_KEYS ist der Pflichtfeld-Vertrag, den storage.apply_merge
# erzwingt — hier als Single Source of Truth importieren (nicht duplizieren),
# damit validate_remote_doc nie gegen einen anderen Feldsatz prüft als der
# Store später schreibt. storage.py importiert sync.py nicht (kein Zyklus).
from src.storage import REQUIRED_ENTRY_KEYS
from src import slot_notes
# sick_days importiert sync.py nicht (kein Zyklus).
from src.sick_days import clean_section

if TYPE_CHECKING:
    import threading

    from src.conflicts_store import ConflictsStore
    from src.settings import Settings
    from src.sick_days import SickDay, SickStore
    from src.storage import Storage

_log = logging.getLogger(__name__)

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


def sorted_signature(items: Iterable[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """Sortiert Slot-Tupel für den Reihenfolge-unabhängigen Vergleich. Gemischte Typen
    (`None` neben Text, Text neben Zahl) lassen `sorted` mit `TypeError` scheitern:
    `validate_remote_doc` lässt Wertfehler in Slots durch, und der Vergleich läuft bei
    jedem Merge, ein Fehler hier sperrte den Sync dauerhaft. Dann gilt ersatzweise die
    Textform als Schlüssel — für saubere Daten bleibt die Ordnung unverändert."""
    rows = list(items)
    try:
        return sorted(rows)
    except TypeError:
        return sorted(rows, key=repr)


def _slots_signature(entry: Entry) -> list[tuple[Any, ...]]:
    """Reihenfolge-normalisierte Signatur der Slot-Liste eines Eintrags,
    für den Gleichheitsvergleich im Merge. Sortiert nach den Slot-Feldern,
    damit eine reine Umordnung der Slots NICHT als Änderung zählt. Die Notiz
    zur Startzeit gehört dazu: eine reine Notiz-Änderung ist eine Änderung."""
    notes = slot_notes.notes_of(entry)
    return sorted_signature(
        (*slot_notes.slot_fields(s),
         notes.get(s["start"], "") if isinstance(s.get("start"), str) else "")
        for s in (entry.get("slots") or [])
    )


def _values_equal_entry(a: Entry, b: Entry) -> bool:
    return (_slots_signature(a) == _slots_signature(b)
            and bool(a.get("deleted")) == bool(b.get("deleted")))


def _values_equal_setting(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a.get("value") == b.get("value")


def _canonical(value: Any) -> str:
    """Stabile Textform eines Werts — letzter Tiebreaker, damit auch zwei
    sekundengleiche Stände desselben Geräts eine feste Ordnung haben."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _lww_key(item: dict[str, Any]) -> tuple[str, str, str]:
    """Ordnung für Last-Write-Wins: Zeitstempel, dann Gerät, dann der Wert.

    Ohne die beiden Tiebreaker gewann bei gleichem `modified_at` einfach die
    Remote-Seite — `merge(A, B)` und `merge(B, A)` behielten dann verschiedene
    Werte, und zwei Geräte, die denselben Tag in derselben Sekunde änderten,
    liefen auseinander (#142)."""
    return (item.get("modified_at") or "", item.get("device_id") or "",
            _canonical(item))


def _lww_winner(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Der Gewinner zweier Stände — unabhängig von ihrer Reihenfolge."""
    return b if _lww_key(b) >= _lww_key(a) else a


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
        # Wert gleich — die Metadaten (Stempel, Gerät) trotzdem symmetrisch wählen.
        return (_lww_winner(local, remote), None)

    local_changed = local["modified_at"] > last_pull_at
    remote_changed = remote["modified_at"] > last_pull_at

    # N2 (LWW-Wanduhr-Abhängigkeit — bewusst festgehalten): `modified_at` ist eine
    # Wanduhr-Zeit (utc_now_iso, Sekunden-Auflösung, KEINE Millisekunden). Der
    # Vergleich ist ein String-Vergleich der ISO-Timestamps. Das LWW-Ergebnis
    # hängt damit an halbwegs synchronen Geräte-Uhren; eine stark falsch gehende
    # Uhr kann Änderungen dauerhaft gewinnen/verlieren lassen. Bei exakt gleicher
    # Sekunde entscheiden Gerät und Wert (`_lww_key`) — unabhängig davon, welche
    # Seite lokal ist (#142; vorher gewann dann immer die Remote-Seite).
    winner = _lww_winner(local, remote)

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


def _merge_entry(loc: Entry | None, rem: Entry | None, last_pull_at: str,
                 key: str) -> tuple[Entry | None, Conflict | None]:
    """`_merge_one` für einen Tag, mit der Erb-Regel der Slot-Notizen.

    Fehlt einer Seite der Schlüssel `notes` (eine ältere Version hat den Tag
    geschrieben), erbt sie die Notizen der anderen (`slot_notes.supplement`).
    Trägt der Gewinner Stempel und Gerät der ergänzten Seite, bekommt er
    `modified_at + 1 s`: sonst hielte das alte Gerät beide Stände für gleich
    und lüde seinen eigenen (ohne `notes`) bei jedem Sync wieder hoch. Die
    Konflikt-Kandidaten behalten ihre Stempel (Dedupe über sie)."""
    supplemented: tuple[Any, Any] | None = None
    if loc is not None and rem is not None:
        loc_s = slot_notes.supplement(loc, rem)
        rem_s = slot_notes.supplement(rem, loc)
        if loc_s is not None:
            supplemented = (loc.get("modified_at"), loc.get("device_id"))
            loc = loc_s
        elif rem_s is not None:
            supplemented = (rem.get("modified_at"), rem.get("device_id"))
            rem = rem_s
    winner, conflict = _merge_one(loc, rem, last_pull_at,
                                  equal_fn=_values_equal_entry, kind="entry", key=key)
    if (winner is not None and supplemented is not None
            and (winner.get("modified_at"), winner.get("device_id")) == supplemented):
        bumped = slot_notes.bump_stamp(winner.get("modified_at"))
        if bumped is not None:
            winner = {**winner, "modified_at": bumped}
    return winner, conflict


def _strip_for_candidate(item: dict[str, Any]) -> dict[str, Any]:
    """Reduziert ein Entry/Setting auf das, was im conflict.candidates landen soll."""
    return {k: v for k, v in item.items()}


def _merge_conflict_pair(a: Conflict, b: Conflict) -> Conflict:
    """LWW auf resolved_at, resolved beats unresolved — unabhängig davon,
    welche Seite `a` ist (#142): bei gleichem `resolved_at` entscheiden das
    auflösende Gerät und die Auflösung selbst."""
    if a.get("resolved") and not b.get("resolved"):
        return a
    if b.get("resolved") and not a.get("resolved"):
        return b
    if a.get("resolved") and b.get("resolved"):
        return b if _resolution_key(b) >= _resolution_key(a) else a
    # Beide unresolved: ID-Match heißt dasselbe Detection-Event, die Inhalte
    # sind gleich — trotzdem symmetrisch wählen, falls doch nicht.
    return b if _canonical(b) >= _canonical(a) else a


def _resolution_key(conflict: Conflict) -> tuple[str, str, str, str]:
    """Ordnung gelöster Konflikte: Zeitpunkt, Gerät, Auflösung (s. `_lww_key`),
    zuletzt der ganze Datensatz — damit ist die Ordnung auch dann total, wenn
    zwei Seiten unter derselben ID Unterschiedliches tragen (sollte bei
    uuid4-IDs nie vorkommen, darf den Merge aber nicht reihenfolgeabhängig
    machen)."""
    return (conflict.get("resolved_at") or "", conflict.get("resolved_by") or "",
            _canonical(conflict.get("resolution")), _canonical(conflict))


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


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _resolution_candidate(conflict: Conflict, replaced: Entry | None,
                          derive: bool = True) -> dict[str, Any] | None:
    """Der Stand, den ein gelöster Konflikt schreibt; `None` bei unbekannter Art.

    Eine Auflösung eines Eintrags bekommt `notes` nach `slot_notes.resolution_notes`;
    gelöscht trägt sie `notes: {}`, wenn sie selbst, `replaced` oder ein Kandidat den
    Schlüssel trägt (wie `Storage.delete`). `replaced` ist der Stand vor allen Auflösungen, nie
    ein Zwischenstand der Schleife, sonst hinge das Ergebnis an der Reihenfolge der
    Konfliktliste. Mit `derive=False` nur, was die Auflösung selbst trägt (ohne Kandidaten
    und `replaced`): danach werden die Auflösungen eines Tages geordnet."""
    resolution = conflict.get("resolution")
    if not isinstance(resolution, dict):
        resolution = {}
    resolved_at = _text(conflict.get("resolved_at"))
    resolved_by = _text(conflict.get("resolved_by"))
    kind = conflict.get("kind")
    if kind == "setting":
        return {"value": resolution.get("value"), "modified_at": resolved_at,
                "device_id": resolved_by}
    if kind != "entry":
        return None
    candidate: Entry = {
        "slots": resolution.get("slots", []),
        "modified_at": resolved_at,
        "device_id": resolved_by,
        "deleted": bool(resolution.get("deleted", False)),
    }
    candidates = conflict.get("candidates")
    candidates = candidates if isinstance(candidates, list) and derive else []
    if not derive:
        replaced = None
    if candidate["deleted"]:
        if (slot_notes.has_key(resolution) or slot_notes.has_key(replaced)
                or any(slot_notes.has_key(c) for c in candidates)):
            candidate["notes"] = {}
        return candidate
    notes = slot_notes.resolution_notes(resolution, candidates, replaced)
    if notes is not None:
        candidate["notes"] = notes
    return candidate


def _resolve_entry(current: Entry | None, candidate: Entry) -> Entry:
    """Auflösung gegen den gemergten Eintrag, mit der Erb-Regel aus `_merge_entry`.

    Fehlt dem Eintrag `notes` und trägt er Stempel und Gerät der Auflösung (die Form,
    die die Schleife eines alten Geräts aus vier Schlüsseln baut), erbt er ihre
    Notizen und wird eine Sekunde jünger; sonst ersetzte das alte Gerät ihn beim
    nächsten Sync wieder. Ein anders gestempelter Eintrag ohne `notes` erbt nicht:
    er ist ein späterer Schreibvorgang, etwa ein gelöschter und neu angelegter Tag."""
    if current is None:
        return candidate
    supplemented = None
    if ((current.get("modified_at"), current.get("device_id"))
            == (candidate.get("modified_at"), candidate.get("device_id"))):
        supplemented = slot_notes.supplement(current, candidate)
    if supplemented is not None:
        current = supplemented
    winner = candidate if _lww_key(candidate) > _lww_key(current) else current
    if (supplemented is not None
            and (winner.get("modified_at"), winner.get("device_id"))
            == (current.get("modified_at"), current.get("device_id"))):
        bumped = slot_notes.bump_stamp(winner.get("modified_at"))
        if bumped is not None:
            winner = {**winner, "modified_at": bumped}
    return winner


def _apply_resolutions(merged: Doc) -> None:
    """Jeder gelöste Konflikt überschreibt seinen Eintrag bzw. seine Einstellung,
    wenn die Auflösung nach `_lww_key` jünger ist als der gemergte Wert. Je
    Schlüssel zählt nur die jüngste Auflösung, damit die Reihenfolge der Liste
    nichts entscheidet (#142).

    Geordnet wird nach dem, was die Auflösung selbst trägt, nicht nach abgeleiteten
    Notizen: die hängen am gemergten Eintrag, der sich durch das Anwenden ändert, und
    ein zweiter Merge wählte sonst eine andere Auflösung. Bei gleichem eigenem Stand
    entscheidet die Konflikt-ID."""
    base = dict(merged["entries"])
    best: dict[tuple[str, str], tuple[tuple[tuple[str, str, str], str], Conflict]] = {}
    for c in merged["conflicts"]:
        key = c.get("key")
        if not c.get("resolved") or not isinstance(key, str):
            continue
        own = _resolution_candidate(c, None, derive=False)
        if own is None:
            continue
        target = (c["kind"], key)
        # Die IDs der gemergten Liste sind eindeutig. Die Textform des ganzen Datensatzes
        # ließe sich bei Fremddaten nicht bilden (Schlüssel verschiedener Typen sortieren nicht).
        rank = (_lww_key(own), _canonical(c.get("id")))
        if target not in best or rank > best[target][0]:
            best[target] = (rank, c)
    for (kind, key), (_rank, conflict) in best.items():
        candidate = _resolution_candidate(conflict, base.get(key))
        if candidate is None:
            continue
        if kind == "entry":
            merged["entries"][key] = _resolve_entry(merged["entries"].get(key), candidate)
        else:
            current = merged["settings"].get(key)
            if current is None or _lww_key(candidate) > _lww_key(current):
                merged["settings"][key] = candidate


def _sick_section(doc: Doc) -> dict[str, SickDay]:
    """Der bereinigte Bereich `sick` eines Docs; fehlt er, ist er leer."""
    raw = doc.get("sick")
    if "sick" in doc and not isinstance(raw, dict):
        _log.warning("Bereich sick im Sync-Doc ist kein Objekt, ignoriert")
    return clean_section(raw)


def _merge_sick(local: Doc, remote: Doc, excluded: bool,
                remote_wm: str) -> dict[str, SickDay]:
    """Krankheitstage beider Seiten, je Tag der neuere Stand; nie ein Konflikt.

    Self-Heal (Regel 2) nur gegen einen Bereich, der remote als Objekt vorliegt
    und den Tag gar nicht nennt: fehlt der Bereich, hat ein älterer Client ihn
    beim Push weggelassen, und ein unbrauchbarer Datensatz ist kein
    wegkompaktierter Tag."""
    loc_days = _sick_section(local)
    rem_days = _sick_section(remote)
    rem_raw = remote.get("sick")
    named = rem_raw.keys() if excluded and isinstance(rem_raw, dict) else None
    merged: dict[str, SickDay] = {}
    for day in sorted(loc_days.keys() | rem_days.keys()):
        loc, rem = loc_days.get(day), rem_days.get(day)
        if loc is not None and rem is not None:
            merged[day] = _lww_winner(loc, rem)
        elif rem is not None:
            merged[day] = rem
        elif loc is not None and not (named is not None and day not in named
                                      and loc["modified_at"] < remote_wm):
            merged[day] = loc
    return merged


def merge(local: Doc, remote: Doc, last_pull_at: str) -> Doc:
    merged = {
        "schema_version": SCHEMA_VERSION,
        "entries": {},
        "settings": {},
        "conflicts": [],
        # Reine Anzeige-Daten, unabhängig von Entries/Settings: Union beider
        # Seiten, je Gerät gewinnt der neuere Stempel.
        "devices": merge_registries(local.get("devices"), remote.get("devices")),
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
        winner, conflict = _merge_entry(loc, rem, last_pull_at, key)
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

    if "sick" in local or "sick" in remote:
        merged["sick"] = _merge_sick(local, remote, excluded, remote_wm)

    _apply_resolutions(merged)

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
        if "sick" in merged:
            merged["sick"] = {
                k: v for k, v in merged["sick"].items()
                if not _is_settled_entry(v, watermark)
            }

    return merged


def build_local_doc(storage: Storage, settings: Settings,
                    conflicts_store: ConflictsStore,
                    sick_store: SickStore | None = None) -> Doc:
    """Erzeugt das Sync-Doc-Format aus den lokalen Stores. `sick` steht nur
    darin, wenn der Store einen Datensatz hat: ohne Krankheitstage bleibt das
    Doc wie bisher."""
    doc: Doc = {
        "schema_version": SCHEMA_VERSION,
        "entries": storage.get_all_raw(),
        "settings": settings.get_synced_doc(),
        "conflicts": conflicts_store.get_all(),
        # Der lokale Spiegel reist wieder mit hoch (sonst verlöre jeder Push die
        # Namen der anderen Geräte); der eigene Eintrag wird darin gesetzt.
        "devices": with_own_entry(
            settings.get("known_devices"),
            settings.device_id_for_sync or (settings.get("device_id") or ""),
            settings.get("device_name") or "",
            utc_now_iso(),
        ),
        "meta": {"gc_watermark": settings.get("gc_watermark") or ""},
    }
    if sick_store is not None:
        sick = sick_store.get_all_raw()
        if sick:
            doc["sick"] = sick
    return doc


def apply_merged_doc(merged_doc: Doc, storage: Storage, settings: Settings,
                     conflicts_store: ConflictsStore,
                     sick_store: SickStore | None = None) -> None:
    """Schreibt das Merge-Ergebnis zurück in die lokalen Stores. Den
    Krankheits-Store nur, wenn das Doc den Bereich führt (wie die Registry
    unten): Fehlen heißt nie „gelöscht“."""
    storage.apply_merge(merged_doc.get("entries", {}))
    settings.apply_synced(merged_doc.get("settings", {}))
    conflicts_store.save_all(merged_doc.get("conflicts", []))
    if sick_store is not None and "sick" in merged_doc:
        sick_store.apply_merge(clean_section(merged_doc["sick"]))
    # Ein set_many statt zweier set-Aufrufe: jedes set schreibt settings.json
    # komplett neu (atomic write + fsync), und diese Funktion läuft bei jedem
    # Pull, Push und jeder Kompaktierung.
    updates = {"gc_watermark": (merged_doc.get("meta") or {}).get("gc_watermark") or ""}
    # Die Registry nur schreiben, wenn das Doc sie überhaupt führt, sonst
    # räumte sie ein Doc ohne den Key leer. Aus `merge` kommt er immer mit —
    # der Fall greift für ein Journal, das ein älterer Stand hinterlassen hat
    # (`sync_journal.recover_pending_apply`), und für direkte Aufrufer.
    if "devices" in merged_doc:
        updates["known_devices"] = sanitize_registry(merged_doc.get("devices"))
    settings.set_many(updates)


def compact_local(storage: Storage, settings: Settings,
                  conflicts_store: ConflictsStore, now: str,
                  sick_store: SickStore | None = None) -> None:
    """Schreibt das gc_watermark lokal und strippt settled Tombstones aus
    Storage, ConflictsStore und dem Krankheits-Store. Ein lokaler
    Schreibvorgang pro Store (Wiederverwendung von storage.apply_merge —
    Required-Key-Validator + Atomic-Write bleiben auf einem Pfad); den
    Krankheits-Store nur, wenn ein Tombstone fällt."""
    settings.set("gc_watermark", now)
    storage.apply_merge({
        k: v for k, v in storage.get_all_raw().items()
        if not _is_settled_entry(v, now)
    })
    conflicts_store.save_all([
        c for c in conflicts_store.get_all()
        if not _is_settled_conflict(c, now)
    ])
    if sick_store is not None:
        sick = sick_store.get_all_raw()
        kept = {k: v for k, v in sick.items() if not _is_settled_entry(v, now)}
        if len(kept) != len(sick):
            sick_store.apply_merge(kept)


def never_synced(settings: Settings) -> bool:
    """True, wenn dieser Rechner nachweislich nie an einem Drive-Sync
    teilgenommen hat: Sync ist aus UND es gab nie einen Pull."""
    return not settings.get("sync_enabled") and not (settings.get("last_pull_at") or "")


def drop_orphan_tombstones(storage: Storage, settings: Settings,
                           sick_store: SickStore | None = None) -> int:
    """Verwirft Tombstones ohne Sync-Partner (Ist-Zeiten und Krankheitstage).
    Liefert die Anzahl (0 = No-op).

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
    if sick_store is not None:
        sick = sick_store.get_all_raw()
        sick_kept = {k: v for k, v in sick.items() if not v.get("deleted")}
        if len(sick_kept) != len(sick):
            sick_store.apply_merge(sick_kept)
            dropped += len(sick) - len(sick_kept)
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
        if not all(isinstance(slot, dict) for slot in entry["slots"]):
            return False, f"entry {date!r}: slots enthält ein Nicht-Objekt"

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


_SLOT_FIELDS = ("start", "end", "pause", "kategorie")


def _slot_level_notes(resolution: dict[str, Any]) -> dict[str, str] | None:
    """Projiziert die Slots einer Auflösung (in place) auf die vier Felder.

    Liefert die am Slot angegebenen Notizen (`{start: bereinigte Notiz}`, auch `""`),
    `None`, wenn kein Slot ein `notiz` trägt. Ein `notiz` in der gespeicherten
    Auflösung gelangte über die Schleife in `merge` in den Bestand alter Geräte und
    von dort in deren Teilen-Datei, die jeder Empfänger ablehnte."""
    slots = resolution.get("slots")
    if not isinstance(slots, list):
        return None
    given: dict[str, str] = {}
    noted = False
    projected: list[Any] = []
    for slot in slots:
        if not isinstance(slot, dict):
            projected.append(slot)
            continue
        if slot_notes.SLOT_KEY in slot:
            noted = True
            start = slot.get("start")
            if isinstance(start, str):
                given[start] = slot_notes.clean_note(slot[slot_notes.SLOT_KEY])
        projected.append({k: v for k, v in slot.items() if k in _SLOT_FIELDS})
    resolution["slots"] = projected
    return given if noted else None


def resolve_conflict(conflict_id: str, chosen_value: dict[str, Any],
                     conflicts_store: ConflictsStore, storage: Storage, settings: Settings,
                     device_id: str, data_lock: threading.RLock | None = None) -> None:
    """User hat einen Konflikt aufgelöst. chosen_value enthält den gewählten
    (oder manuell editierten) Wert. Für entries: {slots: [...]} (und
    optional deleted, notes); ein `notiz` am Slot gilt als gegeben (auch `""`).
    Für settings: {value}.
    Schreibt den Wert in den entsprechenden Store und markiert den Konflikt
    als resolved im ConflictsStore. Die Auflösung eines Eintrags speichert Slots
    mit genau vier Feldern: ihre Slots landen über die Schleife in `merge` auch im
    Bestand alter Geräte (s. `_slot_level_notes`). Den Schlüssel `notes` schreibt der
    Tag (`notes_known`), wenn der gespeicherte Stand oder ein Kandidat ihn trägt oder
    die Wahl eine nicht leere Notiz hat; die Auflösung trägt ihn genau dann, wenn der
    geschriebene Tag ihn trägt, mit dessen Notizen (`{}` beim Tombstone).

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
            key = target["key"]
            resolution = target["resolution"]
            given = _slot_level_notes(resolution)
            candidates = target.get("candidates")
            candidates = candidates if isinstance(candidates, list) else []
            stored = storage.get_all_raw().get(key)
            known = (slot_notes.has_key(stored)
                     or any(slot_notes.has_key(c) for c in candidates)
                     or any(given.values() if given else ())
                     or bool(slot_notes.notes_of({"slots": resolution.get("slots"),
                                                   "notes": resolution.get("notes")})))
            if chosen_value.get("deleted"):
                storage.delete(key, notes_known=known)
            else:
                slots = resolution.get("slots", [])
                notes = slot_notes.resolution_notes(resolution, candidates, stored)
                if given is not None:
                    notes = {**{k: v for k, v in (notes or {}).items() if k not in given},
                             **{k: v for k, v in given.items() if v}}
                if notes is not None:
                    # Ausdrücklich je Slot, damit `Storage.save` nicht vom Bestand erbt.
                    slots = [{**s, slot_notes.SLOT_KEY: notes.get(s.get("start"), "")}
                             if isinstance(s, dict) and isinstance(s.get("start"), str) else s
                             for s in slots]
                storage.save(key, slots, notes_known=known)
            # Die Notizen stehen in der Auflösung, nicht im Slot (sonst gelangten sie über
            # die Schleife in `merge` in den Bestand alter Geräte), und genau dann, wenn
            # der eben geschriebene Stand den Schlüssel trägt: sonst ergänzte der nächste
            # Merge den Tag aus der Auflösung und höbe ihn auf jedem Gerät an.
            resolution.pop(slot_notes.ENTRY_KEY, None)
            written = storage.get_all_raw().get(key)
            if written is not None and slot_notes.has_key(written):
                resolution[slot_notes.ENTRY_KEY] = (
                    {} if written.get("deleted") else slot_notes.notes_of(written))
        elif target["kind"] == "setting":
            settings.set_synced(target["key"], chosen_value.get("value"))

        conflicts_store.save_all(all_conflicts)
