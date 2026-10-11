# src/mobile_sync.py
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
import os
import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src import mobile_pairing, sync, sync_history, sync_journal
from src.api_entry_write import WriteError, check_date_range, load_json_body, parse_slots
from src.devices import sanitize_registry, with_own_entry
from src.settings import WEEKDAY_KEYS
from src.storage import sanitize_slot

if TYPE_CHECKING:
    from src.conflicts_store import ConflictsStore
    from src.settings import Settings
    from src.storage import Storage

PROTOCOL = 2                  # Protokoll v2 (#249): verschlüsselt, s. `mobile_crypto`
WINDOW_DAYS = 90                    # Standardfenster, wenn das Handy keinen Wunsch äußert
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
    # {date: {slots, modified_at, deleted}} — bewusst ohne `device_id`: die setzt
    # `perform_sync` aus dem Token, nie aus dem Body.
    entries: dict[str, dict[str, Any]]
    window_days: int | None = None      # Wunsch des Handys (#250); `None` = keiner/ungültig


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
    if deleted:
        if slots_raw:
            raise bad("Ein gelöschter Tag darf keine Slots tragen.")
    else:
        if not slots_raw:
            raise bad("Ein Tag ohne Slots ist gelöscht (deleted: true).")
        try:
            slots = parse_slots(slots_raw)
        except WriteError as error:
            raise bad(error.message) from None
    return {"slots": slots, "modified_at": str(raw["modified_at"]), "deleted": deleted}


def parse_request(body: bytes, *, now: str) -> SyncRequest:
    """Body → geprüfte Einträge. `now` ist die Desktop-Zeit (UTC-Text). Wirft `SyncError`."""
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
    wish = data.get("window_days")
    window_days = wish if isinstance(wish, int) and not isinstance(wish, bool) and wish >= 1 else None
    return SyncRequest(str(data["client_time"]), entries, window_days)


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
            cutoff = datetime.date.fromisoformat(date)       # dieser Tag passt nicht mehr hinein
            return min(window_days, max((today - cutoff).days - 1, floor_days))
    return window_days


def _clean_slots(raw: object) -> list[dict[str, Any]]:
    """Gespeicherte Slots sind Fremddaten (Drive-Sync, Handbearbeitung): bereinigen
    und auf die vier Felder des Protokolls beschränken."""
    if not isinstance(raw, list):
        return []
    slots = []
    for item in raw:
        clean = sanitize_slot(item)
        if clean is not None:
            slots.append({key: clean[key] for key in ("start", "end", "pause", "kategorie")})
    return slots


def _clean_entry(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """Ein Desktop-Eintrag in der Form des Protokolls, oder `None`, wenn er sich nicht
    so darstellen lässt. Die Invariante „keine Slots ⇔ gelöscht" erzwingt schon
    `parse_request`; dieselbe gilt hier für Fremddaten vom Desktop. Gelöscht ist nur
    ein echtes `True` (`"false"` ist truthy). Ein Tombstone trägt keine Slots; ein
    lebender Tag ohne brauchbare Slots entfällt — als Tombstone gesendet, würde er
    am Handy einen Tag löschen, nur weil die Desktop-Datei beschädigt ist."""
    deleted = entry.get("deleted") is True
    slots = [] if deleted else _clean_slots(entry.get("slots"))
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
                "slots": _clean_slots(candidate.get("slots")),
            })
        views.append({"id": str(conflict.get("id") or ""), "date": key, "versions": versions})
    return sorted(views, key=lambda view: view["date"])


_CLOCK_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
MAX_DEFAULT_PAUSE = 24 * 60
_PLATFORMS = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}


def _clock(value: Any) -> str:
    return value if isinstance(value, str) and _CLOCK_RE.fullmatch(value) else ""


def _pause(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        minutes = int(value)
    except ValueError:
        return None
    return minutes if 0 <= minutes <= MAX_DEFAULT_PAUSE else None


def _clean_category_times(entry: Any) -> dict[str, Any]:
    """Eine Kategorie aus `category_times` (Form: `category_defaults`), auf gültige Felder
    reduziert. Ein fehlendes oder ungültiges Feld fehlt in der Antwort — die PWA greift dann
    wie der Desktop auf den globalen Standard zurück."""
    if not isinstance(entry, dict):
        return {}
    out: dict[str, Any] = {}
    if entry.get("mode") == "per_day":
        out["mode"] = "per_day"
        days = entry.get("days")
        clean_days: dict[str, dict[str, str]] = {}
        for key in WEEKDAY_KEYS:
            day = days.get(key) if isinstance(days, dict) else None
            if isinstance(day, dict):
                clean_days[key] = {f: t for f in ("start", "end") if (t := _clock(day.get(f)))}
        out["days"] = clean_days
    else:
        out.update({f: t for f in ("start", "end") if (t := _clock(entry.get(f)))})
    pause = _pause(entry.get("pause"))
    if pause is not None:
        out["pause"] = pause
    return out


def build_defaults(settings: Settings, categories: list[str]) -> dict[str, Any]:
    """Standardzeiten für die Vorbelegung in der PWA (#288): Wochentag-Standards, globale
    Pause und die `category_times` der bekannten Kategorien. Die Auflösung selbst
    (`category_defaults.resolve_slot_defaults`) macht die PWA mit derselben Semantik.
    Fremdes im Settings-Dokument (Sync!) wird verworfen, nicht durchgereicht."""
    weekdays = {key: {"start": _clock(settings.get(f"default_start_{key}")),
                      "end": _clock(settings.get(f"default_end_{key}"))} for key in WEEKDAY_KEYS}
    raw = settings.get("category_times")
    category_times = {name: _clean_category_times(raw[name]) for name in categories
                      if isinstance(raw, dict) and isinstance(raw.get(name), dict)}
    return {"pause": _pause(settings.get("default_pause")) or 0, "weekdays": weekdays,
            "category_times": category_times}


def desktop_info(name: str, version: str, system: str) -> dict[str, str]:
    """Angaben zum Desktop für den Verbindungsdialog der PWA; `system` ist `platform.system()`.
    Eine unbekannte Plattform bleibt leer, statt einen Rohwert anzuzeigen."""
    return {"name": name, "version": version, "platform": _PLATFORMS.get(system, "")}


def build_response(merged: Mapping[str, Any], *, sent_dates: Iterable[str],
                   today: datetime.date, now: str, excluded: bool,
                   categories: list[str], defaults: Mapping[str, Any],
                   desktop: Mapping[str, str]) -> dict[str, Any]:
    """Die Antwort des Abgleichs aus dem Merge-Ergebnis, ohne `token`/`expires_at`
    (die ergänzt die Route). Fenster `[heute − 90, heute]` (heute ist das lokale
    Datum des Desktops) plus alle gesendeten Tage — beides für Einträge **und**
    Konflikte: ein Konflikt auf einem gesendeten Tag außerhalb des Fensters bliebe
    sonst unsichtbar. Ein gesendeter Tag, den der Merge verworfen hat (Self-Heal bei
    `excluded`), fehlt in `entries`."""
    sent = set(sent_dates)
    first = (today - datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    last = today.isoformat()

    def visible(date: str) -> bool:
        return date in sent or first <= date <= last

    entries = {}
    for date, entry in sorted((merged.get("entries") or {}).items(), key=lambda item: str(item[0])):
        if (isinstance(date, str) and _DATE_RE.fullmatch(date) and isinstance(entry, dict)
                and visible(date)):
            clean = _clean_entry(entry)
            if clean is not None:
                entries[date] = clean
    return {
        "protocol": PROTOCOL,
        "server_time": now,
        "last_pull_at": now,
        "excluded": excluded,
        "window_days": WINDOW_DAYS,
        "entries": entries,
        "conflicts": _conflict_views(merged, visible),
        "categories": list(categories),
        "defaults": dict(defaults),
        "desktop": dict(desktop),
    }


def _phone_doc(request: SyncRequest, device_id: str, device_name: str, now: str,
               changed_since: str = "") -> dict[str, Any]:
    """Das Handy als `local` des Merges: nur die geschickten Tage, die Geräte-ID aus
    dem Token. So wirkt die Self-Heal-Regel (`excluded`) für das Handy richtig.

    `changed_since` (das `last_pull_at` des Desktops, sonst leer): das Handy schickt
    nur Tage, die es seit dem letzten Abgleich geändert hat — jeder gilt per
    Definition als seither geändert. Der Merge entscheidet das aber über
    `modified_at > last_pull_at`, und diese Stempel stammen von zwei Uhren: bei einem
    nachgehenden Handy läge der Stempel vor `last_pull_at`, und die Änderung verlöre
    still gegen die Desktop-Version, ohne Konflikt. Deshalb wird der Stempel auf
    `last_pull_at + 1 s` angehoben (innerhalb der erlaubten 15 Minuten Abweichung)."""
    floor = mobile_pairing.shift(changed_since, datetime.timedelta(seconds=1)) if changed_since else ""
    return {
        "schema_version": sync.SCHEMA_VERSION,
        "entries": {
            date: {**entry, "modified_at": max(entry["modified_at"], floor),
                   "device_id": device_id}
            for date, entry in request.entries.items()
        },
        "settings": {},
        "conflicts": [],
        "devices": with_own_entry(None, device_id, device_name, now),
        "meta": {"gc_watermark": ""},
    }


def perform_sync(request: SyncRequest, *, device_id: str, device_name: str,
                 last_pull_at: str, categories: list[str], storage: Storage,
                 settings: Settings, conflicts_store: ConflictsStore, base: str,
                 now: str, today: datetime.date, desktop: Mapping[str, str],
                 data_lock: threading.RLock | None = None,
                 sync_guard: threading.Lock | None = None) -> dict[str, Any]:
    """Wendet den Abgleich an und liefert die Antwort (ohne `token`/`expires_at`).

    `last_pull_at` ist der Stand aus dem Gerätespeicher des Desktops, nie der Wert
    aus dem Body. `sync_guard` (derselbe wie Drive-Sync, Kompaktierung, Quit-Push)
    wird nicht-blockierend genommen und im `finally` dieses Threads freigegeben;
    belegt → `SyncError` 503. `data_lock` klammert Snapshot → Merge → Apply. Die
    Route ruft `on_change` erst danach.

    Idempotent: derselbe Request liefert dasselbe Ergebnis (der Merge ist es, und
    `merge` dedupliziert gleichwertige offene Konflikte)."""
    if sync_guard is not None and not sync_guard.acquire(blocking=False):
        raise SyncError(503, "busy", "Ein anderer Abgleich läuft gerade. Bitte später erneut versuchen.")
    try:
        with (data_lock if data_lock is not None else contextlib.nullcontext()):
            desktop_doc = sync.build_local_doc(storage, settings, conflicts_store)
            watermark = (desktop_doc.get("meta") or {}).get("gc_watermark") or ""
            excluded = bool(last_pull_at) and last_pull_at < watermark
            # Bei `excluded` bleiben die Stempel unangetastet: die Self-Heal-Regel
            # vergleicht sie mit dem Watermark und soll alte Tage nicht wiederbeleben.
            phone_doc = _phone_doc(request, device_id, device_name, now,
                                   "" if excluded else last_pull_at)
            merged = sync.merge(phone_doc, desktop_doc, last_pull_at)
            sync_journal.apply_merged_doc_journaled(
                merged, storage, settings, conflicts_store,
                os.path.join(base, sync_journal.JOURNAL_FILENAME))
            # Der Startup-Sweep verwirft Tombstones auf Rechnern, die „nie gesynct"
            # haben: nach einem Abgleich mit dem Handy haben sie einen Abnehmer.
            sync_history.mark_synced(base)
        return build_response(merged, sent_dates=request.entries, today=today, now=now,
                              excluded=excluded, categories=categories,
                              defaults=build_defaults(settings, categories), desktop=desktop)
    finally:
        if sync_guard is not None:
            sync_guard.release()
