"""Arbeitszeiten teilen + importieren — pure functions, kein UI-Import.

Wire-Format (eigenständig, kein Sync-Doc-Re-Use):
{
  "schema_version": 1,
  "kind": "zeiterfassung-share",
  "exported_at": "<UTC-ISO>",
  "exported_by": "<email or empty>",
  "entries": {"YYYY-MM-DD": {"start": "HH:MM", "end": "HH:MM", "pause": int>=0}}
}
"""

import datetime
import json
import re


SCHEMA_VERSION = 1
KIND = "zeiterfassung-share"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_ENTRY_KEYS = frozenset({"start", "end", "pause"})


class ShareValidationError(Exception):
    """Datei kann nicht importiert werden. `.reason` enthält den deutschen Grund."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


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
    if schema_version < SCHEMA_VERSION:
        raise ShareValidationError(f"Unbekannte schema_version: {schema_version}")

    entries = doc.get("entries")
    if not isinstance(entries, dict):
        raise ShareValidationError("Feld 'entries' fehlt oder ist kein Objekt.")

    for date_str, entry in entries.items():
        if not isinstance(date_str, str) or not _DATE_RE.match(date_str):
            raise ShareValidationError(f"Ungültiger Datums-Key: {date_str!r}")
        try:
            datetime.date.fromisoformat(date_str)
        except ValueError:
            raise ShareValidationError(f"Ungültiges Datum: {date_str!r}")

        if not isinstance(entry, dict):
            raise ShareValidationError(f"Eintrag {date_str} ist kein Objekt.")

        keys = set(entry.keys())
        if keys != _ENTRY_KEYS:
            extras = sorted(keys - _ENTRY_KEYS)
            missing = sorted(_ENTRY_KEYS - keys)
            parts = []
            if extras:
                parts.append(f"unbekannte Felder: {extras}")
            if missing:
                parts.append(f"fehlende Felder: {missing}")
            raise ShareValidationError(f"Eintrag {date_str}: {'; '.join(parts)}")

        start = entry["start"]
        end = entry["end"]
        pause = entry["pause"]
        if not isinstance(start, str) or not _TIME_RE.match(start):
            raise ShareValidationError(
                f"Eintrag {date_str}: ungültige Startzeit {start!r}"
            )
        if not isinstance(end, str) or not _TIME_RE.match(end):
            raise ShareValidationError(
                f"Eintrag {date_str}: ungültige Endzeit {end!r}"
            )
        if not isinstance(pause, int) or isinstance(pause, bool) or pause < 0:
            raise ShareValidationError(
                f"Eintrag {date_str}: ungültige Pause {pause!r}"
            )

    return doc
