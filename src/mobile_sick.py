# src/mobile_sick.py
# pyright: reportOptionalMemberAccess=true
"""Krankheitstage im Abgleich mit dem Handy, Tk-frei und ohne I/O.

- `parse_sick`: der Teil `sick` der Anfrage ist **Fremddaten**. Ein Tag ist
  `{modified_at, deleted, minutes?}`; alles andere lehnt die ganze Anfrage ab.
  Die Meldung beginnt mit `Krankheit <Datum>:`, damit die PWA den Tag zuordnet.
- `fill_minutes` und `phone_records`: die Datensätze des Handys für den Merge.
  Die Minuten rechnet der Desktop (`sick_plan.prefill`): das Handy kennt weder
  Feiertage noch die Regel „Stunden je Krankheitstag“. Unveränderte Tage bleiben weg.
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
    mit 0 Minuten. Eine Folge nur aus Desktop-Tagen braucht kein `fill`."""
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
    (`last_pull_at + 1 s`, leer bei `excluded`; Begründung in `mobile_sync._phone_doc`),
    `device_id` kommt aus dem Token."""
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
