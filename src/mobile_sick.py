# src/mobile_sick.py
# pyright: reportOptionalMemberAccess=true
"""Krankheitstage im Abgleich mit dem Handy, Tk-frei und ohne I/O.

- `parse_sick`: der Teil `sick` der Anfrage ist **Fremddaten**. Ein Tag ist
  `{modified_at, deleted, minutes?}`; alles andere lehnt die ganze Anfrage ab.
  Die Meldung beginnt mit `Krankheit <Datum>:`, damit die PWA den Tag zuordnet.
- `fill_minutes` und `phone_records`: die Datensätze des Handys für den Merge.
  Die Minuten rechnet der Desktop (`sick_plan.prefill`): das Handy kennt weder
  Feiertage noch die Regel „Stunden je Krankheitstag“. Unveränderte Tage bleiben weg.
  `prefill_entries`/`prefill_reservations` legen die Ist-Zeiten und Reservierungen
  derselben Anfrage über den Stand des Desktops.
- `keep_phone_deletions`: hält eine Löschung des Handys, die der Merge unter dem
  Watermark als erledigt entfernt hat.
- `build_sick`: der Block `sick` der Antwort.

Den Fehler hier übersetzt `mobile_sync` in `SyncError(422, "invalid_entry", …)`.
Gesundheitsdaten: hier wird nichts geloggt.
"""
from __future__ import annotations

import datetime
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from src.absence import date_range
from src.api_entry_write import WriteError, check_date_range
from src.sick_days import MAX_MINUTES, SickDay, clean_record, runs

MAX_SICK_DAYS = 400

_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_KEYS = frozenset({"modified_at", "deleted", "minutes"})
_ECHO_MAX = 40


class SickError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _label(value: object) -> str:
    # `ascii()` escaped auch Surrogate: die Meldung bleibt als UTF-8 schreibbar.
    return ascii(value)[1:-1][:_ECHO_MAX]


def _parse_day(date: object, raw: object, *, now_dt: datetime.datetime,
               parse_utc: Callable[[object], datetime.datetime | None],
               skew_limit: datetime.timedelta) -> dict[str, Any]:
    label = _label(date)

    def bad(reason: str) -> SickError:
        return SickError(f"Krankheit {label}: {reason}")

    if not isinstance(date, str) or not _DATE_RE.fullmatch(date):
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
    unknown = sorted(_label(key) for key in raw if key not in _KEYS)
    if unknown:
        raise bad(f"unbekannte Felder {unknown[:3]}.")
    deleted = raw.get("deleted")
    if not isinstance(deleted, bool):
        raise bad("deleted muss true oder false sein.")
    modified = parse_utc(raw.get("modified_at"))
    if modified is None:
        raise bad("modified_at muss YYYY-MM-DDTHH:MM:SSZ sein.")
    if modified - now_dt > skew_limit:
        raise bad("modified_at liegt in der Zukunft.")
    parsed: dict[str, Any] = {"modified_at": str(raw["modified_at"]), "deleted": deleted}
    if "minutes" in raw:
        minutes = raw["minutes"]
        if (not isinstance(minutes, int) or isinstance(minutes, bool)
                or not 0 <= minutes <= MAX_MINUTES):
            raise bad(f"minutes muss eine ganze Zahl von 0 bis {MAX_MINUTES} sein.")
        parsed["minutes"] = minutes
    return parsed


def parse_sick(raw: object, *, now_dt: datetime.datetime,
               parse_utc: Callable[[object], datetime.datetime | None],
               skew_limit: datetime.timedelta) -> dict[str, dict[str, Any]]:
    """`sick` der Anfrage → geprüfte Tage `{ISO: {modified_at, deleted[, minutes]}}`.
    `minutes` steht nur drin, wenn das Handy sie schickte. Wirft `SickError`; dann wurde
    nichts angewendet. `now_dt` ist die UTC-Zeit des Desktops."""
    if not isinstance(raw, dict):
        raise SickError("sick muss ein Objekt sein.")
    if len(raw) > MAX_SICK_DAYS:
        raise SickError(f"Höchstens {MAX_SICK_DAYS} Krankheitstage je Anfrage.")
    return {date: _parse_day(date, day, now_dt=now_dt, parse_utc=parse_utc,
                             skew_limit=skew_limit)
            for date, day in raw.items()}


def _live_record(raw: object) -> SickDay | None:
    record = clean_record(raw)
    return record if record is not None and not record["deleted"] else None


def days_to_compute(parsed: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Die lebenden Handy-Tage ohne `minutes`, sortiert. Auch Tage, die der Desktop schon
    lebend hat: die Folgen bilden sich wie im Dialog über den ganzen gemeldeten Zeitraum,
    der erste Tag einer Folge ist der Anker des Durchschnitts."""
    return sorted(date for date, day in parsed.items()
                  if not day["deleted"] and "minutes" not in day)


def fill_minutes(parsed: Mapping[str, Mapping[str, Any]], *,
                 desktop_raw: Mapping[str, SickDay],
                 fill: Callable[[str, str, Mapping[str, int]], Mapping[str, int]],
                 ) -> dict[str, int]:
    """Die Minuten der lebenden Handy-Tage ohne `minutes` (`days_to_compute`).

    Je lückenloser Folge, in Datumsreihenfolge, liefert `fill(first, last, sick_days)` die
    Vorbelegung (`sick_plan.prefill`); ein lebender Desktop-Tag behält seine Minuten. Als
    Krankheit zählen dabei die lebenden Desktop-Tage, die Handy-Tage mit eigenen Minuten und
    die Ergebnisse der früheren Folgen: als hätte jemand die Zeiträume nacheinander im Dialog
    gemeldet. Sonst zählten die übrigen neuen Krankheitstage im Durchschnitt als Arbeitstage
    mit 0 Minuten. Ein lebender Desktop-Tag, den das Handy in derselben Anfrage löscht, zählt
    weiter als Krankheit: ob die Löschung gewinnt, entscheidet erst der Merge, und so fällt der
    Tag aus dem Durchschnitt, statt ihn als Arbeitstag ohne Ist-Zeit zu senken. Eine Folge nur
    aus Desktop-Tagen braucht kein `fill`."""
    desktop = {date: record["minutes"] for date, raw in desktop_raw.items()
               if (record := _live_record(raw)) is not None}
    sick_days = dict(desktop)
    sick_days.update({date: int(day["minutes"]) for date, day in parsed.items()
                      if not day["deleted"] and "minutes" in day})
    filled: dict[str, int] = {}
    for first, last in runs(days_to_compute(parsed)):
        dates = [day.isoformat() for day in date_range(first, last)]
        computed = (fill(first, last, dict(sick_days))
                    if any(date not in desktop for date in dates) else {})
        for date in dates:
            filled[date] = desktop[date] if date in desktop else computed[date]
        sick_days.update({date: filled[date] for date in dates})
    return filled


def phone_records(parsed: Mapping[str, Mapping[str, Any]], *,
                  desktop_raw: Mapping[str, SickDay], computed: Mapping[str, int],
                  device_id: str, floor: str) -> dict[str, SickDay]:
    """Die Datensätze des Handys für `sync.merge`, nur für echte Änderungen.

    Ein lebender Tag ohne `minutes` behält die eines lebenden Desktop-Tags (dieselbe Regel
    wie Dialog und API), sonst gilt `computed[date]` (`fill_minutes`). Ein Tombstone trägt
    0 Minuten. Keine Änderung und deshalb nicht dabei: ein lebender Tag, den der Desktop mit
    denselben Minuten lebend hat (auch ohne `minutes`), und ein Tombstone über einem
    Desktop-Tombstone. Der Desktop-Datensatz behält so Stempel und Gerät; ein neuer Stempel
    ohne Änderung schlüge im LWW eine gleichzeitige Änderung auf einem anderen Gerät
    (`SickStore._put_days`/`delete_days`). Der Stempel wird auf `floor` angehoben
    (`last_pull_at + 1 s`, zwei Uhren: Begründung in `mobile_sync._phone_doc`), `device_id`
    kommt aus dem Token. Bei `excluded` ist `floor` leer, weil `perform_sync` der ganzen Anfrage
    eine Untergrenze gibt und die Einträge den Stempel dort für den Self-Heal brauchen;
    Krankheitstage haben keinen. Einen Tombstone, den der Merge unter dem Watermark als erledigt
    entfernt, setzt `keep_phone_deletions` wieder ein."""
    records: dict[str, SickDay] = {}
    for date, day in parsed.items():
        deleted = bool(day["deleted"])
        current = clean_record(desktop_raw.get(date))
        if deleted:
            if current is not None and current["deleted"]:
                continue
            minutes = 0
        else:
            live = current if current is not None and not current["deleted"] else None
            if "minutes" in day:
                minutes = int(day["minutes"])
            elif live is not None:
                minutes = live["minutes"]
            else:
                minutes = computed[date]
            if live is not None and live["minutes"] == minutes:
                continue
        records[date] = {"minutes": minutes, "modified_at": max(str(day["modified_at"]), floor),
                         "device_id": device_id, "deleted": deleted}
    return records


def prefill_entries(stored: Mapping[str, Any],
                    sent: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Die Ist-Zeiten für `sick_plan.prefill`: `stored` (`Storage.get_all()`) mit den Tagen der
    Anfrage (`SyncRequest.entries`) darüber. Ein lebender Handy-Tag ersetzt die Slots, ein
    Tombstone nimmt den Tag heraus. Der Handy-Stand gilt ohne LWW-Vergleich: er ist der neueste,
    den der Desktop kennt, und ein Konflikt auf Eintragsebene ändert am Durchschnitt nichts.
    Sonst zählten die Werktage, die erst mit dieser Anfrage ankommen, als Tage ohne Arbeit."""
    entries = dict(stored)
    for date, entry in sent.items():
        if entry.get("deleted"):
            entries.pop(date, None)
        else:
            entries[date] = {"slots": list(entry.get("slots") or [])}
    return entries


def prefill_reservations(stored: Mapping[str, Any],
                         sent: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Die Reservierungen für `sick_plan.prefill`: `stored` (`ReservationStore.get_all()`, nur
    lebende) plus die lebenden Handy-Tage der Anfrage an Tagen ohne lebende Desktop-Reservierung.
    Es gilt der Stand vor `merge_phone`: eine Desktop-Reservierung, die das Handy in derselben
    Anfrage ändert oder löscht, bestimmt die Minuten noch. Ein Tag, den nur das Handy hat, hat
    keinen anderen Stand; ohne ihn bekäme er die Standardzeit oder den Durchschnitt."""
    reservations = dict(stored)
    for date, day in sent.items():
        if not day.get("deleted") and day.get("slots") and date not in reservations:
            reservations[date] = {"slots": list(day["slots"])}
    return reservations


def keep_phone_deletions(merged: Mapping[str, SickDay], *, records: Mapping[str, SickDay],
                         desktop_raw: Mapping[str, SickDay], watermark: str) -> dict[str, SickDay]:
    """Der gemergte Bereich `sick` plus jeder Tombstone aus `records` (`phone_records`), der darin
    fehlt, obwohl der Desktop den Tag lebend hatte.

    Dann hat der Tombstone im LWW gewonnen (`merge` entfernt nie einen lebenden Tag), lag aber
    unter dem Watermark (Stempel bei `excluded` oder im ersten Abgleich nicht angehoben) und
    wurde als erledigt entfernt; `apply_merged_doc` stellte sonst den lebenden Tag wieder her.
    Er bekommt `max(Handy-Stempel, watermark)`: `_is_settled_entry` vergleicht mit `<`, er
    bleibt bis zur nächsten Kompaktierung und erreicht so auch die anderen Geräte."""
    result = dict(merged)
    for date, record in records.items():
        if not record["deleted"] or date in result:
            continue
        if _live_record(desktop_raw.get(date)) is None:
            continue
        result[date] = {**record, "modified_at": max(record["modified_at"], watermark)}
    return result


def build_sick(raw: Mapping[str, SickDay], *, first: str, last: str,
               sent: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Der Block `sick` der Antwort: lebende Tage und Tombstones von `first` bis `last`
    (ISO, einschließlich) plus die gesendeten Tage, sortiert, ohne `device_id`.
    Unlesbare Datensätze entfallen."""
    wanted = set(sent)
    block: dict[str, dict[str, Any]] = {}
    for date in sorted(key for key in raw if isinstance(key, str) and _DATE_RE.fullmatch(key)):
        if not (first <= date <= last or date in wanted):
            continue
        record = clean_record(raw[date])
        if record is None:
            continue
        block[date] = {"minutes": record["minutes"], "modified_at": record["modified_at"],
                       "deleted": record["deleted"]}
    return block
