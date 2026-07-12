"""Arbeitszeiten teilen + importieren — pure functions, kein UI-Import.

Wire-Format v3 (Slot-Listen):
{
  "schema_version": 3,
  "kind": "zeiterfassung-share",
  "exported_at": "<UTC-ISO>",
  "exported_by": "<email or empty>",
  "entries":      {"YYYY-MM-DD": {"slots": [{"start","end","pause":int>=0,"kategorie":str}]}},
  "reservations": {"YYYY-MM-DD": {"slots": [{"start","end","kategorie":str}]}}
}

Beide Felder sind optional, aber mind. eines muss nicht-leer sein.
v1-Dateien ({start,end,pause}/Tag, Pflichtfeld) und v2-Dateien (entries +
reservations, alte Shape) werden beim Lesen weiterhin akzeptiert und in
1-Slot-Listen (kategorie="") gewrappt (Abwärtskompatibilität).
"""

import datetime
import json
import re


SCHEMA_VERSION = 3
KIND = "zeiterfassung-share"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")

# Alte (v1/v2) Record-Keys:
_LEGACY_ENTRY_KEYS = frozenset({"start", "end", "pause"})
_LEGACY_RESERVATION_KEYS = frozenset({"start", "end"})
# v3-Slot-Keys:
_ENTRY_SLOT_KEYS = frozenset({"start", "end", "pause", "kategorie"})
_RESERVATION_SLOT_KEYS = frozenset({"start", "end", "kategorie"})


def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ShareValidationError(Exception):
    """Datei kann nicht importiert werden. `.reason` enthält den deutschen Grund."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _validate_time(date_str, label, value):
    if not isinstance(value, str) or not _TIME_RE.match(value):
        raise ShareValidationError(f"Eintrag {date_str}: ungültige {label} {value!r}")
    try:
        datetime.time.fromisoformat(value)
    except ValueError:
        raise ShareValidationError(
            f"Eintrag {date_str}: ungültige {label} {value!r}") from None


def _validate_date_key(date_str):
    if not isinstance(date_str, str) or not _DATE_RE.match(date_str):
        raise ShareValidationError(f"Ungültiger Datums-Key: {date_str!r}")
    try:
        datetime.date.fromisoformat(date_str)
    except ValueError:
        raise ShareValidationError(f"Ungültiges Datum: {date_str!r}") from None


def _check_keys(date_str, entry, expected_keys, label="Eintrag"):
    if not isinstance(entry, dict):
        raise ShareValidationError(f"{label} {date_str} ist kein Objekt.")
    keys = set(entry.keys())
    if keys != expected_keys:
        extras = sorted(keys - expected_keys)
        missing = sorted(expected_keys - keys)
        parts = []
        if extras:
            parts.append(f"unbekannte Felder: {extras}")
        if missing:
            parts.append(f"fehlende Felder: {missing}")
        raise ShareValidationError(f"{label} {date_str}: {'; '.join(parts)}")


def _validate_pause(date_str, pause):
    if not isinstance(pause, int) or isinstance(pause, bool) or pause < 0:
        raise ShareValidationError(f"Eintrag {date_str}: ungültige Pause {pause!r}")


def _validate_kategorie(date_str, kategorie):
    if not isinstance(kategorie, str):
        raise ShareValidationError(f"Eintrag {date_str}: ungültige Kategorie {kategorie!r}")


# --- v1/v2 (alte Shape) ---

def _validate_legacy_entries(entries):
    for date_str, entry in entries.items():
        _validate_date_key(date_str)
        _check_keys(date_str, entry, _LEGACY_ENTRY_KEYS)
        _validate_time(date_str, "Startzeit", entry["start"])
        _validate_time(date_str, "Endzeit", entry["end"])
        _validate_pause(date_str, entry["pause"])


def _validate_legacy_reservations(reservations):
    for date_str, entry in reservations.items():
        _validate_date_key(date_str)
        _check_keys(date_str, entry, _LEGACY_RESERVATION_KEYS, label="Reservierung")
        _validate_time(date_str, "Startzeit", entry["start"])
        _validate_time(date_str, "Endzeit", entry["end"])


def _wrap_legacy_entries(entries):
    return {
        d: {"slots": [{"start": e["start"], "end": e["end"],
                       "pause": e["pause"], "kategorie": ""}]}
        for d, e in entries.items()
    }


def _wrap_legacy_reservations(reservations):
    return {
        d: {"slots": [{"start": r["start"], "end": r["end"], "kategorie": ""}]}
        for d, r in reservations.items()
    }


# --- v3 (Slot-Shape) ---

def _validate_slot_record(date_str, record, slot_keys, has_pause):
    if not isinstance(record, dict) or set(record.keys()) != {"slots"}:
        raise ShareValidationError(f"Eintrag {date_str}: erwartet {{\"slots\": [...]}}.")
    if not isinstance(record["slots"], list):
        raise ShareValidationError(f"Eintrag {date_str}: 'slots' ist keine Liste.")
    for slot in record["slots"]:
        _check_keys(date_str, slot, slot_keys, label="Slot")
        _validate_time(date_str, "Startzeit", slot["start"])
        _validate_time(date_str, "Endzeit", slot["end"])
        if has_pause:
            _validate_pause(date_str, slot["pause"])
        _validate_kategorie(date_str, slot["kategorie"])


def _validate_v3_entries(entries):
    for date_str, record in entries.items():
        _validate_date_key(date_str)
        _validate_slot_record(date_str, record, _ENTRY_SLOT_KEYS, has_pause=True)


def _validate_v3_reservations(reservations):
    for date_str, record in reservations.items():
        _validate_date_key(date_str)
        _validate_slot_record(date_str, record, _RESERVATION_SLOT_KEYS, has_pause=False)


def parse_share_doc(raw_bytes):
    """Parst und validiert Share-File-Inhalt. Wirft ShareValidationError bei
    jeder Schema-Verletzung. Der zurückgegebene doc hat entries/reservations
    immer als Slot-Records (v1/v2 werden gewrappt)."""
    try:
        doc = json.loads(raw_bytes)
    except (ValueError, TypeError) as e:
        raise ShareValidationError(f"Datei ist kein gültiges JSON: {e}") from e

    if not isinstance(doc, dict):
        raise ShareValidationError("Datei-Inhalt ist kein JSON-Objekt.")

    if doc.get("kind") != KIND:
        raise ShareValidationError("Diese Datei ist keine geteilte Zeiterfassung.")

    schema_version = doc.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ShareValidationError("Fehlende oder ungültige schema_version.")
    if schema_version > SCHEMA_VERSION:
        raise ShareValidationError(
            "Diese Datei wurde mit einer neueren Version erstellt. "
            "Bitte App aktualisieren."
        )
    if schema_version < 1:
        raise ShareValidationError(f"Unbekannte schema_version: {schema_version}")

    entries = doc.get("entries")
    reservations = doc.get("reservations")

    if schema_version == 1:
        # v1: nur entries, Pflichtfeld, alte Shape → wrappen.
        if not isinstance(entries, dict):
            raise ShareValidationError("Feld 'entries' fehlt oder ist kein Objekt.")
        _validate_legacy_entries(entries)
        doc["entries"] = _wrap_legacy_entries(entries)
        return doc

    if schema_version == 2:
        # v2: entries + reservations optional, alte Shape → wrappen.
        if entries is not None:
            if not isinstance(entries, dict):
                raise ShareValidationError("Feld 'entries' ist kein Objekt.")
            _validate_legacy_entries(entries)
        if reservations is not None:
            if not isinstance(reservations, dict):
                raise ShareValidationError("Feld 'reservations' ist kein Objekt.")
            _validate_legacy_reservations(reservations)
        if not entries and not reservations:
            raise ShareValidationError("Datei enthält weder Arbeitszeiten noch Reservierungen.")
        if entries is not None:
            doc["entries"] = _wrap_legacy_entries(entries)
        if reservations is not None:
            doc["reservations"] = _wrap_legacy_reservations(reservations)
        return doc

    # v3: Slot-Shape.
    if entries is not None:
        if not isinstance(entries, dict):
            raise ShareValidationError("Feld 'entries' ist kein Objekt.")
        _validate_v3_entries(entries)
    if reservations is not None:
        if not isinstance(reservations, dict):
            raise ShareValidationError("Feld 'reservations' ist kein Objekt.")
        _validate_v3_reservations(reservations)
    if not entries and not reservations:
        raise ShareValidationError("Datei enthält weder Arbeitszeiten noch Reservierungen.")
    return doc


def _filter_records_by_category(records, categories):
    """categories=None → unverändert. Sonst je Tag nur Slots behalten, deren
    Kategorie (oder "") in `categories` liegt; leere Tage fallen weg."""
    if categories is None:
        return records
    cats = set(categories)
    out = {}
    for date_str, record in records.items():
        kept = [s for s in record["slots"] if (s.get("kategorie") or "") in cats]
        if kept:
            out[date_str] = {"slots": kept}
    return out


def build_share_doc(storage, sender_email, *, reservation_store=None,
                    include_entries=True, include_reservations=False, categories=None):
    """Baut das v3-Share-Doc aus den Slot-Records von Storage/ReservationStore.

    include_entries / include_reservations steuern die Typen. categories=None →
    alle; sonst werden Slots auf die Kategorie-Menge gefiltert ('' = ohne)."""
    doc = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "exported_at": _utc_now_iso(),
        "exported_by": sender_email or "",
    }
    if include_entries:
        doc["entries"] = _filter_records_by_category(dict(storage.get_all()), categories)
    if include_reservations and reservation_store is not None:
        doc["reservations"] = _filter_records_by_category(
            dict(reservation_store.get_all()), categories)
    return doc


def serialize_share_doc(doc):
    """Stabiles UTF-8-JSON, sortierte Keys (deterministisch für Tests)."""
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _slot_signature(slots, keys):
    """Reihenfolge-normalisierte Signatur einer Slot-Liste über `keys`."""
    return sorted(tuple(s.get(k) for k in keys) for s in (slots or []))


def _entries_equal(a, b):
    return (_slot_signature(a.get("slots"), ("start", "end", "pause", "kategorie"))
            == _slot_signature(b.get("slots"), ("start", "end", "pause", "kategorie")))


def _reservations_equal(a, b):
    return (_slot_signature(a.get("slots"), ("start", "end", "kategorie"))
            == _slot_signature(b.get("slots"), ("start", "end", "kategorie")))


def _diff_records(share_records, local_snapshot, equal_fn, date_from=None, date_to=None):
    """Typ-neutraler Diff zwischen Share-Records und lokalem Snapshot.

    share_records / local_snapshot: {date: record}.
    equal_fn(local_record, share_record) -> bool.
    Rückgabe: additions / conflicts / untouched / out_of_range.
    """
    additions = []
    conflicts = []
    untouched = []
    out_of_range = 0

    for date_str in sorted(share_records.keys()):
        try:
            d = datetime.date.fromisoformat(date_str)
        except ValueError:
            continue
        if date_from is not None and d < date_from:
            out_of_range += 1
            continue
        if date_to is not None and d > date_to:
            out_of_range += 1
            continue

        share_rec = share_records[date_str]
        local_rec = local_snapshot.get(date_str)
        if local_rec is None:
            additions.append((date_str, share_rec))
        elif equal_fn(local_rec, share_rec):
            untouched.append(date_str)
        else:
            conflicts.append((date_str, local_rec, share_rec))

    return {
        "additions": additions,
        "conflicts": conflicts,
        "untouched": untouched,
        "out_of_range": out_of_range,
    }


def diff_share_against_local(share_entries, storage, date_from=None, date_to=None):
    """Arbeitszeiten-Diff (Wrapper, unverändertes Verhalten)."""
    return _diff_records(
        share_entries, storage.get_all(), _entries_equal, date_from, date_to)


def diff_reservations_against_local(share_reservations, reservation_store,
                                    date_from=None, date_to=None):
    """Reservierungs-Diff gegen den ReservationStore-Snapshot ({date:{start,end}})."""
    return _diff_records(
        share_reservations, reservation_store.get_all(),
        _reservations_equal, date_from, date_to)


def apply_reservation_import(reservation_store, decisions):
    """Schreibt importierte Reservierungen (Slot-Records) in den Store.

    decisions: list of {"date": "YYYY-MM-DD", "entry": {"slots": [...]}}.
    Der gcal_event_id-Erhalt / Reconcile-Abgleich passiert separat im
    Kalender-Reconcile (nicht hier)."""
    for d in decisions:
        reservation_store.save(d["date"], d["entry"]["slots"])


def apply_import(storage, decisions):
    """Wendet Import-Decisions atomar an (ein save_many-Aufruf).

    decisions: list of {"date": "YYYY-MM-DD", "entry": {"slots": [...]}}.
    """
    updates = {d["date"]: d["entry"] for d in decisions}
    storage.save_many(updates)
