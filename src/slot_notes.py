# pyright: reportOptionalMemberAccess=true
"""Regeln der optionalen Notiz an Ist-Zeit-Slots.

Tk-frei und ohne Importe aus `src`. Am Slot heißt das Feld `notiz` (App-intern und
auf dem Draht, nur vorhanden, wenn nicht leer); auf der Platte und im Sync-Doc
stehen die Notizen am Eintrag unter `notes`, Schlüssel ist die Startzeit. Gespeicherte
Einträge, Notizen und Auflösungen können Fremddaten sein: was sie liest, wirft nie;
`check_note` wirft `NoteError`, und `with_notes`/`effective_slots`/`notes_from_slots`
erwarten Slot-Listen aus der App.
"""

import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

MAX_NOTE_LEN = 200
SLOT_KEY = "notiz"
ENTRY_KEY = "notes"

_STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class NoteError(ValueError):
    """Eine abgelehnte Eingabe; `message` ist ein deutscher Satz ohne Slot-Präfix."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# Zeilentrenner (`Zl`/`Zp`) zählen wie Steuerzeichen: die Notiz ist einzeilig.
_REJECTED_CATEGORIES = ("Cc", "Cs", "Zl", "Zp")


def _strip_control(text: str) -> str:
    return "".join(c for c in text if unicodedata.category(c) not in _REJECTED_CATEGORIES)


# Genau die Zeichen, die JavaScripts `trim()` entfernt (WhiteSpace und LineTerminator).
# `str.strip()` ohne Argument weicht ab (U+FEFF bleibt, U+001C–U+001F und U+0085 gehen);
# Python und die PWA müssen dieselbe Notiz und denselben Gruppierschlüssel rechnen.
_TRIM_CHARS = ("\t\n\v\f\r \u00a0\u1680" + "".join(chr(c) for c in range(0x2000, 0x200B))
               + "\u2028\u2029\u202f\u205f\u3000\ufeff")


def _trim(text: str) -> str:
    return text.strip(_TRIM_CHARS)


def clean_note(value: object) -> str:
    """Bereinigt gespeicherte Daten: Steuerzeichen raus, trimmen, auf 200 kürzen."""
    if not isinstance(value, str):
        return ""
    return _trim(_trim(_strip_control(value))[:MAX_NOTE_LEN])


def check_note(value: object) -> str:
    """Prüft eine Eingabe und liefert die getrimmte Notiz; sonst `NoteError`."""
    if not isinstance(value, str):
        raise NoteError("notiz muss Text sein.")
    text = _trim(value)
    if any(unicodedata.category(c) in _REJECTED_CATEGORIES for c in text):
        raise NoteError("notiz darf keine Steuerzeichen enthalten.")
    if len(text) > MAX_NOTE_LEN:
        raise NoteError(f"notiz darf höchstens {MAX_NOTE_LEN} Zeichen haben.")
    return text


def group_key(note: str) -> str:
    """Gruppierungsschlüssel für gleiche Notizen (bewusst `lower`, nicht `casefold`)."""
    return _trim(note).lower()


def has_key(entry: object) -> bool:
    return isinstance(entry, Mapping) and ENTRY_KEY in entry


def _starts(slots: object) -> set[str]:
    if not isinstance(slots, list):
        return set()
    return {s["start"] for s in slots if isinstance(s, Mapping) and isinstance(s.get("start"), str)}


def _restrict(notes: Mapping[str, str], starts: set[str]) -> dict[str, str]:
    return {k: v for k, v in notes.items() if k in starts}


def notes_of(entry: Mapping[str, Any]) -> dict[str, str]:
    """Bereinigte, nicht leere Notizen, deren Schlüssel ein `start` des Eintrags ist."""
    if not isinstance(entry, Mapping):
        return {}
    raw = entry.get(ENTRY_KEY)
    if not isinstance(raw, Mapping):
        return {}
    starts = _starts(entry.get("slots"))
    out: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and key in starts:
            text = clean_note(value)
            if text:
                out[key] = text
    return out


def with_notes(slots: list[dict[str, Any]], notes: Mapping[str, str]) -> list[dict[str, Any]]:
    """Kopien der Slots, `notiz` gesetzt, wo `notes` für den `start` einen Wert hat."""
    out: list[dict[str, Any]] = []
    for slot in slots:
        copy = dict(slot)
        copy.pop(SLOT_KEY, None)
        start = copy.get("start")
        if isinstance(start, str) and notes.get(start):
            copy[SLOT_KEY] = notes[start]
        out.append(copy)
    return out


def effective_slots(
    new_slots: list[dict[str, Any]], old_slots: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Slots in App-Form: eigene Notiz, sonst die des alten Slots mit gleichem `start`."""
    inherited: dict[str, str] = {}
    for old in old_slots:
        if isinstance(old, Mapping) and isinstance(old.get("start"), str):
            text = clean_note(old.get(SLOT_KEY))
            if text:
                inherited.setdefault(old["start"], text)
    out: list[dict[str, Any]] = []
    for slot in new_slots:
        copy = dict(slot)
        start = copy.get("start")
        if SLOT_KEY in copy:
            text = clean_note(copy[SLOT_KEY])
        elif isinstance(start, str):
            text = inherited.get(start, "")
        else:
            text = ""
        copy.pop(SLOT_KEY, None)
        if text and isinstance(start, str):
            copy[SLOT_KEY] = text
        out.append(copy)
    return out


def notes_from_slots(slots: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for slot in slots:
        if isinstance(slot, Mapping) and isinstance(slot.get("start"), str):
            text = clean_note(slot.get(SLOT_KEY))
            if text:
                out[slot["start"]] = text
    return out


def bump_stamp(stamp: object) -> str | None:
    """Stempel plus eine Sekunde, `None` bei unlesbarem oder nicht anhebbarem Stempel."""
    if not isinstance(stamp, str):
        return None
    try:
        bumped = datetime.strptime(stamp, _STAMP_FORMAT) + timedelta(seconds=1)
    except (ValueError, OverflowError):
        return None
    if bumped.year < 1000:
        # strftime schreibt solche Jahre plattformabhängig ohne führende Nullen.
        return None
    return bumped.strftime(_STAMP_FORMAT)


def supplement(entry: Mapping[str, Any], other: Mapping[str, Any]) -> dict[str, Any] | None:
    """Ergänzt einen lebenden Eintrag ohne Notizen-Schlüssel um die Notizen von `other`.

    Ist `other` ein Tombstone mit Schlüssel, bekommt der Eintrag `{}`: ein Tombstone
    vererbt keine Notizen, nur die Markierung, dass der Tag Notizen hatte. `None` heißt:
    nichts zu ergänzen (Eintrag gelöscht oder mit Schlüssel, `other` ohne Schlüssel,
    Stempel nicht anhebbar)."""
    if not isinstance(entry, Mapping) or not isinstance(other, Mapping):
        return None
    if has_key(entry) or not has_key(other) or entry.get("deleted") is True:
        return None
    if bump_stamp(entry.get("modified_at")) is None:
        return None
    result = dict(entry)
    if other.get("deleted") is True:
        result[ENTRY_KEY] = {}
    else:
        result[ENTRY_KEY] = _restrict(notes_of(other), _starts(entry.get("slots")))
    return result


def slot_fields(slot: Mapping[str, Any]) -> tuple[Any, Any, Any, Any]:
    """Die vier Felder eines Slots mit den Vorgaben der Merge-Signatur (`pause` 0,
    `kategorie` ""): `sync._slots_signature` und `resolution_notes` vergleichen gleich."""
    return (slot.get("start"), slot.get("end"), slot.get("pause", 0), slot.get("kategorie", ""))


def _slot_signature(slots: object) -> list[Any] | None:
    if not isinstance(slots, list):
        return None
    rows = [slot_fields(s) if isinstance(s, Mapping) else None for s in slots]
    try:
        return sorted(rows)
    except TypeError:
        # Gemischte Typen (Fremddaten) lassen sich nicht ordnen; die Textform ordnet immer.
        return sorted(rows, key=repr)


def _order_key(entry: Mapping[str, Any]) -> tuple[str, str]:
    stamp, device = entry.get("modified_at"), entry.get("device_id")
    return (stamp if isinstance(stamp, str) else "", device if isinstance(device, str) else "")


def resolution_notes(
    resolution: Mapping[str, Any],
    candidates: Sequence[Any],
    replaced: Mapping[str, Any] | None,
) -> dict[str, str] | None:
    """Notizen für einen gelösten Konflikt; `None` heißt: keinen Schlüssel schreiben."""
    if not isinstance(resolution, Mapping) or resolution.get("deleted"):
        return None
    if has_key(resolution):
        return notes_of({"slots": resolution.get("slots"), ENTRY_KEY: resolution[ENTRY_KEY]})
    starts = _starts(resolution.get("slots"))
    wanted = _slot_signature(resolution.get("slots"))
    objects = [c for c in candidates if isinstance(c, Mapping)]
    matching = [
        c for c in objects if wanted is not None and _slot_signature(c.get("slots")) == wanted
    ]
    if matching:
        best = max(matching, key=_order_key)
        if has_key(best):
            return notes_of(best)
        keyed = [c for c in objects if has_key(c)]
        if keyed:
            return _restrict(notes_of(max(keyed, key=_order_key)), starts)
        return _from_replaced(replaced, starts)
    return _from_replaced(replaced, starts)


def _from_replaced(replaced: Mapping[str, Any] | None, starts: set[str]) -> dict[str, str] | None:
    if isinstance(replaced, Mapping) and has_key(replaced):
        return _restrict(notes_of(replaced), starts)
    return None
