"""Arbeitszeiten teilen + importieren — pure functions, kein UI-Import.

Wire-Format v2 (eigenständig, kein Sync-Doc-Re-Use):
{
  "schema_version": 2,
  "kind": "zeiterfassung-share",
  "exported_at": "<UTC-ISO>",
  "exported_by": "<email or empty>",
  "entries":      {"YYYY-MM-DD": {"start": "HH:MM", "end": "HH:MM", "pause": int>=0}},
  "reservations": {"YYYY-MM-DD": {"start": "HH:MM", "end": "HH:MM"}}
}

Beide Felder ("entries", "reservations") sind optional, aber mind. eines muss
nicht-leer sein. v1-Dateien (nur "entries", Pflichtfeld) werden beim Lesen
weiterhin akzeptiert (Abwärtskompatibilität).
"""

import datetime
import json
import re


SCHEMA_VERSION = 2
KIND = "zeiterfassung-share"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_ENTRY_KEYS = frozenset({"start", "end", "pause"})
_RESERVATION_KEYS = frozenset({"start", "end"})


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
        raise ShareValidationError(f"Eintrag {date_str}: ungültige {label} {value!r}")


def _validate_date_key(date_str):
    if not isinstance(date_str, str) or not _DATE_RE.match(date_str):
        raise ShareValidationError(f"Ungültiger Datums-Key: {date_str!r}")
    try:
        datetime.date.fromisoformat(date_str)
    except ValueError:
        raise ShareValidationError(f"Ungültiges Datum: {date_str!r}")


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


def _validate_entries(entries):
    for date_str, entry in entries.items():
        _validate_date_key(date_str)
        _check_keys(date_str, entry, _ENTRY_KEYS)
        _validate_time(date_str, "Startzeit", entry["start"])
        _validate_time(date_str, "Endzeit", entry["end"])
        pause = entry["pause"]
        if not isinstance(pause, int) or isinstance(pause, bool) or pause < 0:
            raise ShareValidationError(f"Eintrag {date_str}: ungültige Pause {pause!r}")


def _validate_reservations(reservations):
    for date_str, entry in reservations.items():
        _validate_date_key(date_str)
        _check_keys(date_str, entry, _RESERVATION_KEYS, label="Reservierung")
        _validate_time(date_str, "Startzeit", entry["start"])
        _validate_time(date_str, "Endzeit", entry["end"])


def parse_share_doc(raw_bytes):
    """Parst und validiert Share-File-Inhalt. Wirft ShareValidationError bei
    jeder Schema-Verletzung — Aufrufer darf den lokalen Bestand nicht antasten,
    wenn diese Funktion wirft."""
    try:
        doc = json.loads(raw_bytes)
    except (ValueError, TypeError) as e:
        raise ShareValidationError(f"Datei ist kein gültiges JSON: {e}")

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
        # v1: nur entries, Pflichtfeld (Abwärtskompatibilität für Alt-Dateien).
        if not isinstance(entries, dict):
            raise ShareValidationError("Feld 'entries' fehlt oder ist kein Objekt.")
        _validate_entries(entries)
        return doc

    # v2: entries und reservations beide optional, mind. eines nicht-leer.
    if entries is not None:
        if not isinstance(entries, dict):
            raise ShareValidationError("Feld 'entries' ist kein Objekt.")
        _validate_entries(entries)
    if reservations is not None:
        if not isinstance(reservations, dict):
            raise ShareValidationError("Feld 'reservations' ist kein Objekt.")
        _validate_reservations(reservations)
    if not entries and not reservations:
        raise ShareValidationError(
            "Datei enthält weder Arbeitszeiten noch Reservierungen."
        )
    return doc


def build_share_doc(storage, sender_email, *, reservation_store=None,
                    include_entries=True, include_reservations=False):
    """Baut das Share-Doc. Tombstones sind via get_all() bereits gefiltert.

    include_entries / include_reservations steuern, welche Typen mitgehen.
    reservations werden nur aufgenommen, wenn ein reservation_store übergeben
    wurde."""
    doc = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "exported_at": _utc_now_iso(),
        "exported_by": sender_email or "",
    }
    if include_entries:
        doc["entries"] = dict(storage.get_all())
    if include_reservations and reservation_store is not None:
        doc["reservations"] = dict(reservation_store.get_all())
    return doc


def serialize_share_doc(doc):
    """Stabiles UTF-8-JSON, sortierte Keys (deterministisch für Tests)."""
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _entries_equal(a, b):
    return (a.get("start") == b.get("start")
            and a.get("end") == b.get("end")
            and a.get("pause", 0) == b.get("pause", 0))


def diff_share_against_local(share_entries, storage, date_from=None, date_to=None):
    """Vergleicht share_entries mit storage.get_all().

    date_from/date_to: optional datetime.date, inclusive auf beiden Seiten.
    None = unbeschränkt. Einträge außerhalb fallen in 'out_of_range'-Count
    und tauchen sonst nirgends auf.

    Returns dict mit 'additions' (list of (date, entry)), 'conflicts'
    (list of (date, local_entry, share_entry)), 'untouched' (list of date)
    und 'out_of_range' (int).
    """
    additions = []
    conflicts = []
    untouched = []
    out_of_range = 0
    local = storage.get_all()

    for date_str in sorted(share_entries.keys()):
        try:
            d = datetime.date.fromisoformat(date_str)
        except ValueError:
            # parse_share_doc hat das schon abgefangen — defensive Skip.
            continue
        if date_from is not None and d < date_from:
            out_of_range += 1
            continue
        if date_to is not None and d > date_to:
            out_of_range += 1
            continue

        share_entry = share_entries[date_str]
        local_entry = local.get(date_str)
        if local_entry is None:
            additions.append((date_str, share_entry))
        elif _entries_equal(local_entry, share_entry):
            untouched.append(date_str)
        else:
            conflicts.append((date_str, local_entry, share_entry))

    return {
        "additions": additions,
        "conflicts": conflicts,
        "untouched": untouched,
        "out_of_range": out_of_range,
    }


def apply_import(storage, decisions):
    """Wendet Import-Decisions atomar an (eine save_many-Aufruf).

    decisions: list of {"date": "YYYY-MM-DD", "entry": {start, end, pause}}.
    """
    updates = {d["date"]: d["entry"] for d in decisions}
    storage.save_many(updates)
