# src/api_entry_write.py
"""Schreibpfad der lokalen API für Ist-Zeiten (#92, PR 4), Tk-frei und ohne Socket.

Dieses Modul **nimmt Fremddaten** (der Body kommt von einem Skript) und bildet
die Regeln nach, die die UI an ihren Eingängen heute durchsetzt, weil `Storage`
sie nicht kennt:

- Validierung der Slots über `time_utils.validate_slots` (pro Slot Zeit/Pause,
  Überlappungsfreiheit) — dazu die Form (strenges JSON, genau `HH:MM`, nur die
  vier bekannten Felder) und Grenzen (Slot-Anzahl, Kategorielänge, Jahr);
- Sperren: ungelöster Sync-Konflikt am Tag (die UI öffnet dort den
  Konfliktdialog statt des Tages-Dialogs) und Urlaubsminuten > 0 (Urlaub und
  Arbeitszeit schließen sich aus; 0-Minuten-Tage einer Periode bleiben
  beschreibbar);
- Warnungen zu Wochenlimit und Pausenpflicht, nie ein Fehler — wie in der UI,
  wo sie nur nachfragen.

Fehler sind `WriteError` mit Status und Code; die Routen machen daraus die
JSON-Antwort. Nichts hier hält einen Lock — den nimmt der Aufrufer um Prüfen
und Speichern gemeinsam.
"""
from __future__ import annotations

import datetime
import json
import logging
import re
import unicodedata
from typing import Any

from src.pause_requirement import check_day_pause
from src.time_utils import parse_time, validate_slots
from src.weekly_limit import check_week_limit

_log = logging.getLogger(__name__)

MIN_YEAR = 2000
MAX_YEAR = 2100
MAX_SLOTS = 50
MAX_CATEGORY_LEN = 100

# Nur ASCII-Ziffern: `\d` matcht auch Ziffern anderer Schriften, und
# `parse_time` akzeptiert "8:00" — gespeichert werden soll genau "08:00".
_TIME_RE = re.compile(r"[0-9]{2}:[0-9]{2}")
_SLOT_KEYS = frozenset({"start", "end", "pause", "kategorie"})
_REQUIRED_KEYS = frozenset({"start", "end"})


class WriteError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} ist kein gültiger JSON-Wert")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"doppelter Schlüssel {key!r}")
        result[key] = value
    return result


def _load_json(body: bytes) -> Any:
    try:
        # utf-8-sig: ein BOM ist erlaubt (Windows PowerShell 5.1 schreibt eines).
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise WriteError(400, "invalid_encoding",
                         "Der Body muss UTF-8 sein (ein BOM ist erlaubt).") from None
    try:
        return json.loads(text, parse_constant=_reject_constant,
                          object_pairs_hook=_reject_duplicates)
    except (ValueError, RecursionError):
        # ValueError deckt kaputtes JSON, NaN/Infinity und doppelte Schlüssel;
        # RecursionError die tiefe Verschachtelung (ein 1-MiB-Body aus lauter "["
        # wäre sonst eine 500).
        raise WriteError(400, "invalid_json", "Der Body ist kein gültiges JSON.") from None


def _parse_time_field(value: Any, label: str, index: int) -> str:
    if not isinstance(value, str) or not _TIME_RE.fullmatch(value) or parse_time(value) is None:
        raise WriteError(422, "invalid_time",
                         f"Slot {index}: {label} muss genau HH:MM sein (00:00 bis 23:59).")
    return value


def _parse_category(value: Any, index: int) -> str:
    if not isinstance(value, str):
        raise WriteError(422, "invalid_category", f"Slot {index}: kategorie muss Text sein.")
    value = value.strip()
    if len(value) > MAX_CATEGORY_LEN:
        raise WriteError(422, "invalid_category",
                         f"Slot {index}: kategorie darf höchstens {MAX_CATEGORY_LEN} Zeichen haben.")
    # Cc: Steuerzeichen (auch C1, DEL); Cs: Surrogate. Ein einzelnes Surrogat (ein
    # mitten im Emoji gekürzter Name) ließe sich nicht als UTF-8 schreiben und
    # machte jedes spätere Speichern des Stores unmöglich.
    if any(unicodedata.category(ch) in ("Cc", "Cs") for ch in value):
        raise WriteError(422, "invalid_category",
                         f"Slot {index}: kategorie darf keine Steuerzeichen oder "
                         "ungültigen Unicode-Zeichen enthalten.")
    return value


def _parse_slot(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise WriteError(422, "invalid_slot", f"Slot {index} muss ein Objekt sein.")
    keys = set(item)
    if not _REQUIRED_KEYS <= keys or not keys <= _SLOT_KEYS:
        raise WriteError(
            422, "invalid_slot",
            f"Slot {index}: erlaubt sind start, end (Pflicht) sowie pause und kategorie; "
            f"gefunden: {sorted(keys)[:10]}.")
    pause = item.get("pause", 0)
    if not isinstance(pause, int) or isinstance(pause, bool) or pause < 0:
        raise WriteError(422, "invalid_pause",
                         f"Slot {index}: pause muss eine ganze Zahl >= 0 (Minuten) sein.")
    return {
        "start": _parse_time_field(item["start"], "start", index),
        "end": _parse_time_field(item["end"], "end", index),
        "pause": pause,
        "kategorie": _parse_category(item.get("kategorie", ""), index),
    }


def parse_day_body(body: bytes) -> list[dict[str, Any]]:
    """Body → geprüfte Slots (`{start, end, pause, kategorie}`, alle vier Felder).
    Wirft `WriteError`: 400 bei kaputtem JSON oder falscher Form, 422 bei
    ungültigem Slot."""
    data = _load_json(body)
    if not isinstance(data, dict) or set(data) != {"slots"} or not isinstance(data["slots"], list):
        raise WriteError(400, "invalid_body", 'Erwartet wird {"slots": [...]}.')
    raw = data["slots"]
    if not raw:
        raise WriteError(422, "empty_slots",
                         "Eine leere Slot-Liste speichert nichts — zum Löschen DELETE benutzen.")
    if len(raw) > MAX_SLOTS:
        raise WriteError(422, "too_many_slots", f"Höchstens {MAX_SLOTS} Slots je Tag.")
    slots = [_parse_slot(item, i + 1) for i, item in enumerate(raw)]
    ok, message = validate_slots(slots, with_pause=True)
    if not ok:
        raise WriteError(422, "invalid_slots", message)
    return slots


def check_date_range(day: datetime.date) -> None:
    """Ein Skript-Fehler mit Jahr 1970 würde sonst Daten und Tombstones dauerhaft
    im Sync hinterlassen."""
    if not MIN_YEAR <= day.year <= MAX_YEAR:
        raise WriteError(422, "date_out_of_range",
                         f"Das Jahr muss zwischen {MIN_YEAR} und {MAX_YEAR} liegen.")


def check_day_writable(date_str: str, *, conflicts_store: Any, vacation_store: Any,
                       for_save: bool) -> None:
    """Die Sperren der UI. Ungelöster Sync-Konflikt: `PUT` und `DELETE` — die
    Ist-Zeit steht zur Debatte, ein Schreiben würde einen Kandidaten
    überschreiben. Urlaubsminuten > 0: nur `PUT` (Löschen ist der Weg aus der
    Sackgasse); 0-Minuten-Tage einer Periode sind kein Urlaubstag."""
    if conflicts_store is not None and date_str in conflicts_store.unresolved_entry_keys():
        raise WriteError(409, "sync_conflict",
                         "Für diesen Tag gibt es einen ungelösten Sync-Konflikt. "
                         "Zuerst in der App auflösen.")
    if for_save and vacation_store is not None:
        period = vacation_store.period_for_date(date_str)
        if period is not None and period.get("days", {}).get(date_str, 0):
            raise WriteError(409, "vacation_day",
                             f"Für diesen Tag ist Urlaub eingetragen "
                             f"(„{period.get('name', '')}“). An einem Urlaubstag lässt sich "
                             "keine Arbeitszeit erfassen; den Urlaub zuerst in der App löschen.")


def warnings_for(settings: Any, all_entries: dict[str, Any], date_str: str,
                 slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wochenlimit und Pausenpflicht gegen den simulierten Stand **nach** dem
    Speichern (der neue Tag ersetzt den alten). Nur Warnungen, nie ein Fehler."""
    simulated = dict(all_entries)
    simulated[date_str] = {"slots": slots}
    found: list[dict[str, Any]] = []
    # Nie ein Fehler: ein gespeicherter Slot mit ungewöhnlichem Inhalt (der Sync
    # validiert Slot-Inhalte nicht, z. B. pause=None) ließe die Summe mit
    # TypeError scheitern und damit das Schreiben. Jede Prüfung für sich.
    try:
        overshoot = check_week_limit(settings, simulated, date_str)
        if overshoot is not None:
            found.append({"code": "weekly_limit", **overshoot})
    except Exception:
        _log.exception("Lokale API: Wochenlimit nicht berechenbar — Warnungen übersprungen")
    try:
        violation = check_day_pause(settings, slots)
        if violation is not None:
            found.append({"code": "pause_requirement", **violation})
    except Exception:
        _log.exception("Lokale API: Pausenpflicht nicht berechenbar — Warnungen übersprungen")
    return found
