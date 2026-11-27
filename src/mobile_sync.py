# src/mobile_sync.py
# pyright: reportOptionalMemberAccess=true
"""Fachlicher Kern von `POST /v1/sync` der Handy-Erfassung (#221), Tk-frei, ohne Socket.

Drei Dinge liegen hier:

- `parse_request`: der Body vom Handy ist **Fremddaten**. Er wird mit denselben
  Regeln wie `PUT /v1/entries` geprüft (`api_entry_write`), dazu Datum, Zeitstempel,
  Tag-Obergrenze und die Uhr. Eine Ablehnung ist ein `SyncError`; dann wurde
  nichts angewendet.
- `build_response`: die Antwort aus dem Merge-Ergebnis (Lesefenster, offene
  Konflikte). Rein.
- `perform_sync`: Guard und Lock, `sync.merge` mit dem Handy als `local`, die
  journalisierte Anwendung. Token, Gerätedatensatz und `last_pull_at` des Handys
  gehören der Route: sie kommen als Parameter herein, die Antwort enthält
  `token`/`expires_at` **nicht**.

Es gibt keinen Merge in JavaScript und keinen zweiten hier: Konfliktlogik bleibt
`sync.merge`.
"""
from __future__ import annotations

import contextlib
import datetime
import json
import os
import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src import (
    mobile_pairing, mobile_reminders, mobile_reservations, mobile_settings, mobile_sick, slot_notes,
    sync, sync_history, sync_journal,
)
from src.api_entry_write import WriteError, check_date_range, load_json_body, parse_slots
from src.api_summary import category_names
from src.devices import sanitize_registry, with_own_entry
from src.mobile_settings import clean_category_times, clock, pause
from src.reservations import reservations_active
from src.sick_plan import normalize_basis, prefill
from src.slot_order import DEFAULT_MODE, normalize_mode
from src.settings import WEEKDAY_KEYS
from src.storage import sanitize_slot

if TYPE_CHECKING:
    from src.conflicts_store import ConflictsStore
    from src.reservations import ReservationStore
    from src.settings import Settings
    from src.sick_days import SickDay, SickStore
    from src.storage import Storage
    from src.vacations import VacationStore

PROTOCOL = 2                  # Protokoll v2 (#249): verschlüsselt, s. `mobile_crypto`
WINDOW_DAYS = 90                    # Standardfenster, wenn das Handy keinen Wunsch äußert
WINDOW_AHEAD_DAYS = 14              # Tage nach heute, die das Handy zusätzlich sieht (#265); fest, nicht im Budget
HARD_MAX_WINDOW_DAYS = 365          # weiter geht kein Fenster, auch nicht per Einstellung
WINDOW_CAP_CHOICES = (30, 90, 180, 365)
MAX_RESPONSE_ENTRY_BYTES = 768 * 1024   # Klartext der Einträge im Fenster; s. fit_window
MAX_ENTRIES = 400
# LWW vertraut `modified_at`: eine falsche Uhr würde echte Einträge überschreiben.
CLOCK_SKEW_LIMIT = datetime.timedelta(minutes=15)

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# Nur ASCII-Ziffern: `\d` matcht auch andere Schriften.
_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ECHO_MAX = 40


class SyncError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SyncRequest:
    client_time: str
    # {date: {slots, modified_at, deleted}}, dazu `notes`, wenn das Handy `notiz` an allen Slots des
    # Tages schickte — bewusst ohne `device_id`: die setzt `perform_sync` aus dem Token, nie aus dem Body.
    entries: dict[str, dict[str, Any]]
    window_days: int | None = None      # Wunsch des Handys (#250); `None` = keiner/ungültig
    # {date: {slots, modified_at, deleted}} der Reservierungen; leer, wenn das Handy keine
    # sendet oder der Desktop sie nicht annimmt (`accept_reservations=False`).
    reservations: dict[str, dict[str, Any]] = field(default_factory=dict)
    # {key: {value, modified_at}} der Einstellungen, die das Handy setzen darf (`categories`,
    # `category_times`); leer, wenn es keine sendet. Geprüft von `mobile_settings.parse_settings`.
    settings: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Das Relay-Geheimnis des Handys (Teil `push` der Anfrage, #331); `None`, wenn keins kam oder
    # es unbrauchbar war. Der Handler legt es beim Gerät ab, `perform_sync` fasst es nicht an.
    relay_secret: str | None = None
    # {date: {modified_at, deleted[, minutes]}} der Krankheitstage; leer, wenn das Handy keine
    # sendet. Geprüft von `mobile_sick.parse_sick`; `minutes` fehlt in der Regel (der Desktop rechnet).
    sick: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class SyncReport:
    """Was `perform_sync` außer der Antwort bewirkt hat — für den Aufrufer, der nach der
    Freigabe aller Sperren reagiert. Nicht Teil der Antwort ans Handy."""
    reservations_changed: bool = False


def _parse_utc(text: object) -> datetime.datetime | None:
    if not isinstance(text, str) or not _TIME_RE.fullmatch(text):
        return None
    try:
        return datetime.datetime.strptime(text, _TIME_FORMAT)
    except ValueError:
        return None


def _parse_entry(date: str, raw: object, now_dt: datetime.datetime) -> dict[str, Any]:
    # `ascii()` escaped auch Surrogate: die Meldung bleibt als UTF-8 schreibbar.
    label = ascii(date)[1:-1][:_ECHO_MAX]

    def bad(reason: str) -> SyncError:
        return SyncError(422, "invalid_entry", f"{label}: {reason}")

    if not _DATE_RE.fullmatch(date):
        raise bad("Datum muss YYYY-MM-DD sein.")
    try:
        day = datetime.date.fromisoformat(date)
    except ValueError:
        raise bad("kein gültiges Datum.") from None
    try:
        check_date_range(day)
    except WriteError as error:
        raise bad(error.message) from None
    if not isinstance(raw, dict):
        raise bad("Eintrag muss ein Objekt sein.")
    deleted = raw.get("deleted")
    if not isinstance(deleted, bool):
        raise bad("deleted muss true oder false sein.")
    modified = _parse_utc(raw.get("modified_at"))
    if modified is None:
        raise bad("modified_at muss YYYY-MM-DDTHH:MM:SSZ sein.")
    if modified - now_dt > CLOCK_SKEW_LIMIT:
        raise bad("modified_at liegt in der Zukunft.")
    slots_raw = raw.get("slots")
    if not isinstance(slots_raw, list):
        raise bad("slots muss eine Liste sein.")
    slots: list[dict[str, Any]] = []
    notes: dict[str, str] | None = None
    if deleted:
        if slots_raw:
            raise bad("Ein gelöschter Tag darf keine Slots tragen.")
    else:
        if not slots_raw:
            raise bad("Ein Tag ohne Slots ist gelöscht (deleted: true).")
        try:
            slots = parse_slots(slots_raw, allow_note=True)
        except WriteError as error:
            raise bad(error.message) from None
        # Eine PWA, die Notizen kennt, schickt `notiz` an jedem Slot; ohne `notiz` erbt der Tag im
        # Merge die Notizen des Desktops. Gemischt wäre nicht zu entscheiden, welche gelten.
        noted = [slot_notes.SLOT_KEY in slot for slot in slots]
        if any(noted):
            if not all(noted):
                raise bad("notiz muss an allen Slots eines Tages stehen oder an keinem.")
            notes = slot_notes.notes_from_slots(slots)
            slots = [{key: slot[key] for key in ("start", "end", "pause", "kategorie")} for slot in slots]
    entry: dict[str, Any] = {"slots": slots, "modified_at": str(raw["modified_at"]), "deleted": deleted}
    if notes is not None:
        entry[slot_notes.ENTRY_KEY] = notes
    return entry


def parse_request(body: bytes, *, now: str, today: datetime.date | None = None,
                  accept_reservations: bool = True) -> SyncRequest:
    """Body → geprüfte Einträge. `now` ist die Desktop-Zeit (UTC-Text), `today` sein lokales
    Datum (Standard: das UTC-Datum von `now`). Mit `accept_reservations=False` wird das Feld
    `reservations` gar nicht gelesen — ein Desktop mit ausgeschalteten Reservierungen ignoriert
    es, statt es abzulehnen. `settings` darf nur `categories`/`category_times` enthalten;
    `sick` wird immer geprüft. Wirft `SyncError`."""
    try:
        data = load_json_body(body)
    except WriteError as error:
        raise SyncError(400, "invalid_json", error.message) from None
    if not isinstance(data, dict):
        raise SyncError(400, "invalid_json", "Erwartet wird ein JSON-Objekt.")
    protocol = data.get("protocol")
    if not isinstance(protocol, int) or isinstance(protocol, bool) or protocol != PROTOCOL:
        raise SyncError(400, "invalid_protocol", f"Unterstützt wird protocol {PROTOCOL}.")
    client = _parse_utc(data.get("client_time"))
    if client is None:
        raise SyncError(400, "invalid_json",
                        "client_time fehlt oder ist kein UTC-Zeitstempel (YYYY-MM-DDTHH:MM:SSZ).")
    raw_entries = data.get("entries", {})
    if not isinstance(raw_entries, dict):
        raise SyncError(400, "invalid_json", "entries muss ein Objekt sein.")
    now_dt = datetime.datetime.strptime(now, _TIME_FORMAT)
    # Die Uhr zuerst: ein vorgehendes Handy trägt Zukunftsstempel, und „modified_at
    # liegt in der Zukunft" wäre dann die irreführende der beiden Meldungen.
    if abs(client - now_dt) > CLOCK_SKEW_LIMIT:
        raise SyncError(409, "clock_skew",
                        "Die Uhr des Handys weicht mehr als 15 Minuten von der des Desktops ab. "
                        "Bitte Datum und Uhrzeit am Handy prüfen.")
    if len(raw_entries) > MAX_ENTRIES:
        raise SyncError(422, "invalid_entry", f"Höchstens {MAX_ENTRIES} Tage je Anfrage.")
    entries = {date: _parse_entry(date, raw, now_dt) for date, raw in raw_entries.items()}
    reservations: dict[str, dict[str, Any]] = {}
    if accept_reservations and "reservations" in data:
        try:
            reservations = mobile_reservations.parse_reservations(
                data["reservations"], today=today or now_dt.date(), now_dt=now_dt,
                parse_utc=_parse_utc, skew_limit=CLOCK_SKEW_LIMIT)
        except mobile_reservations.ReservationError as error:
            raise SyncError(422, "invalid_entry", error.message) from None
    settings: dict[str, dict[str, Any]] = {}
    if "settings" in data:
        try:
            settings = mobile_settings.parse_settings(
                data["settings"], now_dt=now_dt, parse_utc=_parse_utc, skew_limit=CLOCK_SKEW_LIMIT)
        except mobile_settings.SettingsError as error:
            raise SyncError(422, "invalid_entry", error.message) from None
    sick: dict[str, dict[str, Any]] = {}
    if "sick" in data:
        try:
            sick = mobile_sick.parse_sick(
                data["sick"], now_dt=now_dt, parse_utc=_parse_utc, skew_limit=CLOCK_SKEW_LIMIT)
        except mobile_sick.SickError as error:
            raise SyncError(422, "invalid_entry", error.message) from None
    wish = data.get("window_days")
    window_days = wish if isinstance(wish, int) and not isinstance(wish, bool) and wish >= 1 else None
    return SyncRequest(str(data["client_time"]), entries, window_days, reservations, settings,
                       mobile_reminders.parse_push(data.get("push")), sick=sick)


def window_cap(raw: object) -> int:
    """Die Obergrenze aus der Einstellung. Nur die angebotenen Werte gelten; alles andere
    (handbearbeitete `settings.json`, Fremdwert) fällt auf das Maximum zurück."""
    if isinstance(raw, int) and not isinstance(raw, bool) and raw in WINDOW_CAP_CHOICES:
        return raw
    return HARD_MAX_WINDOW_DAYS


def grant_window(wish: object, cap: int) -> int:
    """Das gewährte Fenster: der Wunsch (sonst das Standardfenster), auf `1..cap` geklemmt.
    Ein ungültiger Wunsch ist kein Fehler — das Handy bekommt dann das Standardfenster."""
    base = wish if isinstance(wish, int) and not isinstance(wish, bool) and wish >= 1 else WINDOW_DAYS
    return max(1, min(base, cap))


def fit_window(sizes: Mapping[str, int], *, today: datetime.date, window_days: int,
               floor_days: int, budget: int) -> int:
    """Kürzt das Fenster, wenn seine Einträge mehr als `budget` Byte ergäben.

    `sizes` ist die serialisierte Größe je Datum. Gezählt wird von heute rückwärts; das Fenster
    endet vor dem ersten Tag, der das Budget sprengt. Nie unter `floor_days` (das Standardfenster
    bleibt, wie es immer war), nie über `window_days`. Tage außerhalb von `[heute − window_days,
    heute]` zählen nicht."""
    first = (today - datetime.timedelta(days=window_days)).isoformat()
    last = today.isoformat()
    used = 0
    for date in sorted((d for d in sizes if first <= d <= last), reverse=True):
        used += sizes[date]
        if used > budget:
            try:
                cutoff = datetime.date.fromisoformat(date)   # dieser Tag passt nicht mehr hinein
            except ValueError:
                continue        # „2026-09-31“: passt auf das Muster, ist aber kein Kalendertag (Fremddaten)
            return min(window_days, max((today - cutoff).days - 1, floor_days))
    return window_days


def _clean_slots(raw: object, notes: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Gespeicherte Slots sind Fremddaten (Drive-Sync, Handbearbeitung): bereinigen
    und auf die fünf Felder des Protokolls beschränken. `notiz` steht immer da (`""`
    ohne Notiz); `notes` sind die bereinigten Notizen des Tages (`slot_notes.notes_of`)."""
    if not isinstance(raw, list):
        return []
    notes = notes or {}
    slots = []
    for item in raw:
        clean = sanitize_slot(item)
        if clean is not None:
            slot = {key: clean[key] for key in ("start", "end", "pause", "kategorie")}
            start = slot["start"]
            slot[slot_notes.SLOT_KEY] = notes.get(start, "") if isinstance(start, str) else ""
            slots.append(slot)
    return slots


def _clean_entry(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """Ein Desktop-Eintrag in der Form des Protokolls, oder `None`, wenn er sich nicht
    so darstellen lässt. Die Invariante „keine Slots ⇔ gelöscht" erzwingt schon
    `parse_request`; dieselbe gilt hier für Fremddaten vom Desktop. Gelöscht ist nur
    ein echtes `True` (`"false"` ist truthy). Ein Tombstone trägt keine Slots; ein
    lebender Tag ohne brauchbare Slots entfällt — als Tombstone gesendet, würde er
    am Handy einen Tag löschen, nur weil die Desktop-Datei beschädigt ist."""
    deleted = entry.get("deleted") is True
    slots = [] if deleted else _clean_slots(entry.get("slots"), slot_notes.notes_of(entry))
    if not deleted and not slots:
        return None
    return {
        "slots": slots,
        "modified_at": str(entry.get("modified_at") or ""),
        "device_id": str(entry.get("device_id") or ""),
        "deleted": deleted,
    }


def _conflict_views(merged: Mapping[str, Any], visible: Any) -> list[dict[str, Any]]:
    registry = sanitize_registry(merged.get("devices"))
    views = []
    for conflict in merged.get("conflicts") or []:
        if not isinstance(conflict, dict) or conflict.get("kind") != "entry" or conflict.get("resolved"):
            continue
        key = conflict.get("key")
        if not isinstance(key, str) or not _DATE_RE.fullmatch(key) or not visible(key):
            continue
        versions = []
        for candidate in conflict.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            device = candidate.get("device_id")
            device = device if isinstance(device, str) else ""
            versions.append({
                "device": device,
                "name": registry.get(device, {}).get("name", ""),
                "modified_at": str(candidate.get("modified_at") or ""),
                "slots": _clean_slots(candidate.get("slots"), slot_notes.notes_of(candidate)),
            })
        views.append({"id": str(conflict.get("id") or ""), "date": key, "versions": versions})
    return sorted(views, key=lambda view: view["date"])


_PLATFORMS = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}


def build_defaults(settings: Settings, categories: list[str]) -> dict[str, Any]:
    """Standardzeiten für die Vorbelegung in der PWA (#288): Wochentag-Standards, globale
    Pause und die `category_times` der bekannten Kategorien. Die Auflösung selbst
    (`category_defaults.resolve_slot_defaults`) macht die PWA mit derselben Semantik.
    Fremdes im Settings-Dokument (Sync!) wird verworfen, nicht durchgereicht."""
    weekdays = {key: {"start": clock(settings.get(f"default_start_{key}")),
                      "end": clock(settings.get(f"default_end_{key}"))} for key in WEEKDAY_KEYS}
    raw = settings.get("category_times")
    category_times = {name: clean_category_times(raw[name]) for name in categories
                      if isinstance(raw, dict) and isinstance(raw.get(name), dict)}
    return {"pause": pause(settings.get("default_pause")) or 0, "weekdays": weekdays,
            "category_times": category_times}


def desktop_info(name: str, version: str, system: str) -> dict[str, str]:
    """Angaben zum Desktop für den Verbindungsdialog der PWA; `system` ist `platform.system()`.
    Eine unbekannte Plattform bleibt leer, statt einen Rohwert anzuzeigen."""
    return {"name": name, "version": version, "platform": _PLATFORMS.get(system, "")}


def _entry_bytes(date: str, clean: Mapping[str, Any]) -> int:
    """Serialisierte Größe eines Eintrags in der Antwort — mit derselben Serialisierung
    wie `mobile_routes` sie siegelt (`ensure_ascii=False`, kompakte Separatoren): Umlaute
    zählen 2 statt 6 Byte, das Budget kürzt nicht unnötig knapp."""
    return len(json.dumps({date: clean}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def build_response(merged: Mapping[str, Any], *, sent_dates: Iterable[str],
                   today: datetime.date, now: str, excluded: bool,
                   categories: list[str], defaults: Mapping[str, Any],
                   desktop: Mapping[str, str], window_days: int,
                   window_max_days: int,
                   reservations: Mapping[str, Any] | None = None,
                   reminders: Mapping[str, Any] | None = None,
                   slot_order: str = DEFAULT_MODE,
                   sick: Mapping[str, Any] | None = None,
                   sick_sent: Iterable[str] = ()) -> dict[str, Any]:
    """Die Antwort des Abgleichs aus dem Merge-Ergebnis, ohne `token`/`expires_at`
    (die ergänzt die Route). Fenster `[heute − Fenster, heute + WINDOW_AHEAD_DAYS]` (heute ist das lokale
    Datum des Desktops) plus alle gesendeten Tage — beides für Einträge **und**
    Konflikte: ein Konflikt auf einem gesendeten Tag außerhalb des Fensters bliebe
    sonst unsichtbar. Ein gesendeter Tag, den der Merge verworfen hat (Self-Heal bei
    `excluded`), fehlt in `entries`.

    `window_days` ist das **gewährte** Fenster (`grant_window`); `fit_window` kürzt es,
    wenn die Einträge mehr als `MAX_RESPONSE_ENTRY_BYTES` ergäben (#250). Die Antwort
    nennt das Fenster, das tatsächlich gilt.

    `sick` ist der Block der Krankheitstage (`mobile_sick.build_sick`), `None` ohne
    Krankheits-Store. Die Antwort trägt davon die Tage im Fenster, das sie nennt, plus die
    gesendeten (`sick_sent`); er zählt nicht ins Mengenbudget."""
    sent = set(sent_dates)
    last = (today + datetime.timedelta(days=WINDOW_AHEAD_DAYS)).isoformat()

    clean_entries: dict[str, dict[str, Any]] = {}
    for date, entry in (merged.get("entries") or {}).items():
        if isinstance(date, str) and _DATE_RE.fullmatch(date) and isinstance(entry, dict):
            clean = _clean_entry(entry)
            if clean is not None:
                clean_entries[date] = clean
    sizes = {date: _entry_bytes(date, clean) for date, clean in clean_entries.items()
             if date not in sent}
    granted = fit_window(sizes, today=today, window_days=window_days,
                         floor_days=min(WINDOW_DAYS, window_days),
                         budget=MAX_RESPONSE_ENTRY_BYTES)
    first = (today - datetime.timedelta(days=granted)).isoformat()

    def visible(date: str) -> bool:
        return date in sent or first <= date <= last

    entries = {date: clean for date, clean in sorted(clean_entries.items()) if visible(date)}
    response: dict[str, Any] = {
        "protocol": PROTOCOL,
        "server_time": now,
        "last_pull_at": now,
        "excluded": excluded,
        "window_days": granted,
        "window_ahead_days": WINDOW_AHEAD_DAYS,
        "window_max_days": window_max_days,
        "entries": entries,
        "conflicts": _conflict_views(merged, visible),
        "categories": list(categories),
        "defaults": dict(defaults),
        "desktop": dict(desktop),
        # Welche Einstellungen das Handy schreiben darf — daran erkennt die PWA einen Desktop, der
        # `settings` versteht (Feature-Erkennung; `defaults.category_times` gibt es schon länger).
        "writable_settings": list(mobile_settings.SETTING_KEYS),
        # Fähigkeit: der Desktop kennt `POST /v1/unpair` (die PWA warnt sonst vor dem Trennen).
        "unpair": True,
        # Fähigkeit: Slots tragen `notiz`, der Desktop nimmt sie an (die PWA sendet sie nur dann).
        "slot_notes": True,
        # Reihenfolge der Slots eines Tages (#520): die PWA zeigt danach (`chrono`, `category`,
        # `custom`); ein älterer Desktop schickt das Feld nicht, dann gilt `chrono`.
        "slot_order": normalize_mode(slot_order),
    }
    if reservations is not None:       # nur bei eingeschalteten Reservierungen (Feature-Erkennung)
        response["reservations"] = dict(reservations)
        response["reservation_pause"] = True   # Fähigkeit: Slots tragen `pause` (PWA-Erkennung)
    if reminders is not None:          # Feature-Erkennung der PWA; ausgeschaltet ein leerer Block (#331)
        response["reminders"] = dict(reminders)
    if sick is not None:
        # Fähigkeit: der Desktop nimmt `sick` an (Feature-Erkennung der PWA), auch mit leerem Block.
        response["sick_days"] = True
        sent_sick = set(sick_sent)
        response["sick"] = {date: day for date, day in sick.items()
                            if date in sent_sick or first <= date <= last}
    return response


def _stamp_floor(changed_since: str) -> str:
    """`changed_since + 1 s`, leer ohne `changed_since` (Begründung in `_phone_doc`)."""
    return mobile_pairing.shift(changed_since, datetime.timedelta(seconds=1)) if changed_since else ""


def _phone_doc(request: SyncRequest, device_id: str, device_name: str, now: str,
               changed_since: str = "",
               desktop_entries: Mapping[str, Any] | None = None,
               sick: Mapping[str, SickDay] | None = None) -> dict[str, Any]:
    """Das Handy als `local` des Merges: nur die geschickten Tage, die Geräte-ID aus
    dem Token. So wirkt die Self-Heal-Regel (`excluded`) für das Handy richtig.

    `changed_since` (das `last_pull_at` des Desktops, sonst leer): das Handy schickt
    nur Tage, die es seit dem letzten Abgleich geändert hat — jeder gilt per
    Definition als seither geändert. Der Merge entscheidet das aber über
    `modified_at > last_pull_at`, und diese Stempel stammen von zwei Uhren: bei einem
    nachgehenden Handy läge der Stempel vor `last_pull_at`, und die Änderung verlöre
    still gegen die Desktop-Version, ohne Konflikt. Deshalb wird der Stempel auf
    `last_pull_at + 1 s` angehoben (innerhalb der erlaubten 15 Minuten Abweichung).
    Die Einstellungen bekommen denselben angehobenen Stempel.

    Den Schlüssel `notes` richtet `_notes_key_like_desktop` am Desktop-Eintrag aus
    (`desktop_entries`): ein Tag, der nie eine Notiz hatte, bleibt ohne `notes`.

    `sick` sind die fertigen Datensätze aus `mobile_sick.phone_records` (Stempel schon
    angehoben); der Bereich steht nur mit Tagen im Doc."""
    floor = _stamp_floor(changed_since)
    doc: dict[str, Any] = {
        "schema_version": sync.SCHEMA_VERSION,
        "entries": {
            date: {**_notes_key_like_desktop(entry, (desktop_entries or {}).get(date)),
                   "modified_at": max(entry["modified_at"], floor), "device_id": device_id}
            for date, entry in request.entries.items()
        },
        "settings": {
            key: {"value": payload["value"], "modified_at": max(payload["modified_at"], floor),
                  "device_id": device_id}
            for key, payload in request.settings.items()
        },
        "conflicts": [],
        "devices": with_own_entry(None, device_id, device_name, now),
        "meta": {"gc_watermark": ""},
    }
    if sick:
        doc["sick"] = dict(sick)
    return doc


def _phone_sick(request: SyncRequest, *, sick_store: SickStore, storage: Storage,
                settings: Settings, reservation_store: ReservationStore | None,
                vacation_store: VacationStore | None, device_id: str, floor: str,
                today: datetime.date) -> dict[str, SickDay]:
    """Die geänderten Krankheitstage des Handys als Datensätze, unter `data_lock`. Fehlende
    Minuten rechnet `prefill` je lückenloser Folge wie Dialog und API (`mobile_sick.fill_minutes`).
    Ist-Zeiten und Reservierungen derselben Anfrage zählen schon mit, obwohl sie erst danach
    gemergt werden (`mobile_sick.prefill_entries`/`prefill_reservations`). Reservierungen nur,
    solange sie aktiv sind, und im Stand vor `merge_phone`: eine in derselben Anfrage gelöschte
    Desktop-Reservierung bestimmt die Minuten noch."""
    desktop_raw = sick_store.get_all_raw()
    inputs: dict[str, Any] = {}

    def fill(first: str, last: str, sick_days: Mapping[str, int]) -> Mapping[str, int]:
        if not inputs:          # erst gelesen, wenn eine Folge wirklich etwas zu rechnen hat
            inputs.update(
                basis=normalize_basis(settings.get("sick_hours_basis")),
                entries=mobile_sick.prefill_entries(storage.get_all(), request.entries),
                reservations=(mobile_sick.prefill_reservations(reservation_store.get_all(),
                                                               request.reservations)
                              if reservation_store is not None
                              and reservations_active(reservation_store, settings) else None),
                vacation_days=vacation_store.day_minutes() if vacation_store is not None else {})
        return prefill(first, last, sick_days=sick_days, settings=settings, today=today,
                       **inputs).days

    computed = mobile_sick.fill_minutes(request.sick, desktop_raw=desktop_raw, fill=fill)
    return mobile_sick.phone_records(request.sick, desktop_raw=desktop_raw, computed=computed,
                                     device_id=device_id, floor=floor)


def _notes_key_like_desktop(entry: Mapping[str, Any], desktop: object) -> dict[str, Any]:
    """Der Handy-Eintrag mit dem Schlüssel `notes` nach der Schreib-Regel von `Storage`.

    Trägt der Desktop-Eintrag (lebend oder Tombstone) den Schlüssel, behält ein leeres
    `notes` ihn und ein Tombstone des Handys bekommt `notes: {}`; sonst entfällt ein
    leeres `notes`, und der Tag bleibt ohne Schlüssel, den sonst niemand gesetzt hat."""
    result = dict(entry)
    keyed = slot_notes.has_key(desktop)
    if result.get("deleted") is True:
        if keyed:
            result[slot_notes.ENTRY_KEY] = {}
    elif result.get(slot_notes.ENTRY_KEY) == {} and not keyed:
        del result[slot_notes.ENTRY_KEY]
    return result


def perform_sync(request: SyncRequest, *, device_id: str, device_name: str,
                 last_pull_at: str, storage: Storage,
                 settings: Settings, conflicts_store: ConflictsStore, base: str,
                 now: str, today: datetime.date, desktop: Mapping[str, str],
                 data_lock: threading.RLock | None = None,
                 sync_guard: threading.Lock | None = None,
                 reservation_store: ReservationStore | None = None,
                 report: SyncReport | None = None,
                 categories: list[str] | None = None,
                 local_now: datetime.datetime | None = None,
                 sick_store: SickStore | None = None,
                 vacation_store: VacationStore | None = None) -> dict[str, Any]:
    """Wendet den Abgleich an und liefert die Antwort (ohne `token`/`expires_at`).

    `last_pull_at` ist der Stand aus dem Gerätespeicher des Desktops, nie der Wert
    aus dem Body. `sync_guard` (derselbe wie Drive-Sync, Kompaktierung, Quit-Push)
    wird nicht-blockierend genommen und im `finally` dieses Threads freigegeben;
    belegt → `SyncError` 503. `categories` (`None`: aus den Einstellungen **nach** dem
    Anwenden) bestimmt die Namen der Antwort. `data_lock` klammert Snapshot → Merge → Apply. Die
    Route ruft `on_change` erst danach.

    Ohne `sick_store` bleibt `request.sick` unbeachtet und die Antwort ohne Krankheit; mit ihm
    bekommen Snapshot **und** Anwenden den Store (sonst fehlten dem Merge die lokalen Tage).
    `vacation_store` braucht nur die Vorbelegung fehlender Minuten.

    Idempotent: derselbe Request liefert dasselbe Ergebnis (der Merge ist es, und
    `merge` dedupliziert gleichwertige offene Konflikte)."""
    if sync_guard is not None and not sync_guard.acquire(blocking=False):
        raise SyncError(503, "busy", "Ein anderer Abgleich läuft gerade. Bitte später erneut versuchen.")
    active = False
    try:
        with (data_lock if data_lock is not None else contextlib.nullcontext()):
            # Vor dem Snapshot: nichts darf angewendet sein, wenn die Anfrage abgelehnt wird.
            if "category_times" in request.settings and "categories" not in request.settings:
                try:
                    mobile_settings.check_times_names(
                        request.settings["category_times"]["value"], category_names(settings))
                except mobile_settings.SettingsError as error:
                    raise SyncError(422, "invalid_entry", error.message) from None
            desktop_doc = sync.build_local_doc(storage, settings, conflicts_store,
                                               sick_store=sick_store)
            watermark = (desktop_doc.get("meta") or {}).get("gc_watermark") or ""
            excluded = bool(last_pull_at) and last_pull_at < watermark
            # Bei `excluded` bleiben die Stempel unangetastet: die Self-Heal-Regel
            # vergleicht sie mit dem Watermark und soll alte Tage nicht wiederbeleben.
            changed_since = "" if excluded else last_pull_at
            phone_sick = (_phone_sick(request, sick_store=sick_store, storage=storage,
                                      settings=settings, reservation_store=reservation_store,
                                      vacation_store=vacation_store, device_id=device_id,
                                      floor=_stamp_floor(changed_since), today=today)
                          if sick_store is not None and request.sick else None)
            phone_doc = _phone_doc(request, device_id, device_name, now, changed_since,
                                   desktop_entries=desktop_doc.get("entries"), sick=phone_sick)
            merged = sync.merge(phone_doc, desktop_doc, last_pull_at)
            if phone_sick:
                merged["sick"] = mobile_sick.keep_phone_deletions(
                    merged.get("sick") or {}, records=phone_sick,
                    desktop_raw=desktop_doc.get("sick") or {},
                    watermark=merged["meta"]["gc_watermark"])
            sync_journal.apply_merged_doc_journaled(
                merged, storage, settings, conflicts_store,
                os.path.join(base, sync_journal.JOURNAL_FILENAME), sick_store=sick_store)
            sick_raw = sick_store.get_all_raw() if sick_store is not None else None
            # Der Startup-Sweep verwirft Tombstones auf Rechnern, die „nie gesynct"
            # haben: nach einem Abgleich mit dem Handy haben sie einen Abnehmer.
            sync_history.mark_synced(base)
            # Reservierungen gehören nicht in `sync.merge` (eigener Store, kein Drive-Sync),
            # liegen aber im selben Lock: eine Anfrage wird als Ganzes sichtbar.
            if reservation_store is not None and reservations_active(reservation_store, settings):
                active = True
                if request.reservations:
                    floor = (mobile_pairing.shift(last_pull_at, datetime.timedelta(seconds=1))
                             if last_pull_at else "")
                    changed = reservation_store.merge_phone(request.reservations,
                                                            floor=floor, now=now)
                    if report is not None:
                        report.reservations_changed = changed
        reservations = (mobile_reservations.build_reservations(
            reservation_store.get_all_raw(), today=today)
            if active and reservation_store is not None else None)
        names = categories if categories is not None else category_names(settings)
        cap = window_cap(settings.get("mobile_window_max_days"))
        granted = grant_window(request.window_days, cap)
        # Vorauswahl über das gewährte Fenster; auf das Fenster nach `fit_window` kürzt `build_response`.
        sick = (mobile_sick.build_sick(
            sick_raw, first=(today - datetime.timedelta(days=granted)).isoformat(),
            last=(today + datetime.timedelta(days=WINDOW_AHEAD_DAYS)).isoformat(),
            sent=request.sick) if sick_raw is not None else None)
        # `local_now`: die lokale (naive) Desktop-Zeit für die Sende-Zeitpunkte; die Tests setzen sie.
        reminders = mobile_reminders.build_block(
            settings, reservation_store, local_now or datetime.datetime.now())
        return build_response(merged, sent_dates=request.entries, today=today, now=now,
                              excluded=excluded, categories=names,
                              defaults=build_defaults(settings, names), desktop=desktop,
                              window_days=granted,
                              window_max_days=cap, reservations=reservations,
                              reminders=reminders,
                              slot_order=normalize_mode(settings.get("slot_order_mode")),
                              sick=sick, sick_sent=request.sick)
    finally:
        if sync_guard is not None:
            sync_guard.release()
