"""Urlaubsperioden: reine Regeln und JSON-Persistenz.

Urlaub ist ein eigenständiges Konzept neben Ist-Zeiten (`storage.py`) und
Reservierungen (`reservations.py`). Gespeichert wird die **Periode** als
Record mit Identität — sie trägt einen (nur lokal sichtbaren) Namen, ein
Kalender-Event und wird als Einheit gelöscht. Die Tagesminuten liegen in ihr:

    {period_id: {name, from, to, days: {ISO: minutes},
                 gcal_event_id, modified_at, deleted}}

`days` deckt JEDEN Kalendertag von `from` bis `to` ab, lückenlos — daraus
folgt „Urlaub gewinnt" im Kalender ohne weitere Rangfolge-Regel. Wochenenden
und Feiertage stehen mit 0 Minuten darin: sichtbar als Urlaub, aber ohne
Stunden.

Werte sind **Minuten** (CLAUDE.md: Summen nie über Dezimalstunden). Der Store
reist NICHT per Drive-Sync und trägt daher — wie `reservations.py` — kein
`device_id`-Feld.
"""

from __future__ import annotations

import datetime
import secrets
import threading
from typing import Any

from src.holidays_de import get_holidays
from src.json_store import atomic_write_json, load_json_or_quarantine
from src.time_utils import utc_now_iso

# JSON-getragener Record (Audit N8): Werte sind heterogen → Any.
Vacation = dict[str, Any]


def _date_range(date_from: str, date_to: str) -> list[datetime.date]:
    """Alle Kalendertage von `date_from` bis `date_to` (inklusive). Leere
    Liste, wenn `date_to` vor `date_from` liegt."""
    start = datetime.date.fromisoformat(date_from)
    end = datetime.date.fromisoformat(date_to)
    if end < start:
        return []
    return [start + datetime.timedelta(days=i)
            for i in range((end - start).days + 1)]


def _holiday_dates(days: list[datetime.date], state: str) -> set[datetime.date]:
    """Feiertage über den (ggf. jahresübergreifenden) Zeitraum. Ohne
    Bundesland liefert get_holidays ein leeres Dict — dann gilt kein Tag als
    Feiertag."""
    out: set[datetime.date] = set()
    for year in {d.year for d in days}:
        out |= set(get_holidays(state, year))
    return out


def expand_days(date_from: str, date_to: str, minutes_per_day: int,
                state: str) -> dict[str, int]:
    """Baut {ISO: minutes} über ALLE Kalendertage von `date_from` bis
    `date_to`.

    Wochenenden (Sa/So) und Feiertage des Bundeslands `state` bekommen 0 —
    sie sind ohnehin frei und sollen keine Urlaubsstunden tragen. Sie bleiben
    aber im Dict, damit der Kalender den Zeitraum durchgehend einfärben kann.
    """
    days = _date_range(date_from, date_to)
    holidays = _holiday_dates(days, state)
    return {
        d.isoformat(): (
            0 if (d.weekday() >= 5 or d in holidays) else minutes_per_day
        )
        for d in days
    }


def apportion_minutes(total: int, n: int) -> list[int]:
    """Verteilt `total` Minuten auf `n` Tage so, dass die Summe EXAKT `total`
    ergibt.

    `total // n` für alle, die ersten `total % n` bekommen eine Minute mehr.
    Die Alternative — je Tag Dezimalstunden runden — ergäbe bei 40 h auf 6
    Tage 40,02 h und bei 40 h auf 7 Tage 39,97 h; genau der Fehler, den
    CLAUDE.md für den Footer beschreibt. So summiert sich stattdessen jeder
    Teilbericht exakt zum Ganzen.
    """
    if n <= 0:
        return []
    base, rest = divmod(total, n)
    return [base + 1 if i < rest else base for i in range(n)]


def periods_overlap(periods: dict[str, Vacation], period_id: str | None,
                    date_from: str, date_to: str) -> str | None:
    """Prüft, ob [date_from, date_to] eine bestehende Periode schneidet.

    Datums-Pendant zu `time_utils.slots_overlap`. Liefert den Namen der
    kollidierenden Periode oder None. `period_id` ist die gerade bearbeitete
    Periode — sie darf sich nicht mit sich selbst überschneiden. Tombstones
    zählen nicht mit.
    """
    for pid, period in periods.items():
        if pid == period_id or period.get("deleted"):
            continue
        if period.get("from", "") <= date_to and date_from <= period.get("to", ""):
            return period.get("name", "")
    return None


def total_minutes(day_minutes: dict[str, int]) -> int:
    """Summe über Minuten — die einzige erlaubte Summenbildung (CLAUDE.md)."""
    return sum(day_minutes.values())


def period_for_day(periods: dict[str, Vacation], date_str: str) -> Vacation | None:
    """Die Periode, die diesen Tag abdeckt, um ihre `id` ergänzt — oder None.

    Perioden überschneiden sich nicht (siehe VacationStore.save), es kann also
    höchstens eine sein. Tombstones tragen ein leeres `days` und matchen daher
    nie.
    """
    for pid, period in periods.items():
        if date_str in period.get("days", {}):
            return {**period, "id": pid, "days": dict(period["days"])}
    return None


_REQUIRED_VACATION_KEYS = frozenset(
    {"name", "from", "to", "days", "gcal_event_id", "modified_at", "deleted"})


class VacationStore:
    def __init__(self, filepath: str = "vacations.json",
                 lock: threading.RLock | None = None) -> None:
        self.filepath = filepath
        # Geteilter Daten-Lock (Audit H1/H2) — siehe storage.py.
        self._lock = lock if lock is not None else threading.RLock()
        self._data: dict[str, Vacation] = {}
        self._load()

    def _load(self) -> None:
        data = load_json_or_quarantine(self.filepath)
        # None = nicht vorhanden oder korrupt (dann quarantäniert).
        self._data = data if isinstance(data, dict) else {}

    def _save_to_disk(self) -> None:
        atomic_write_json(self.filepath, self._data)

    @staticmethod
    def _copy(period: Vacation) -> Vacation:
        """Kopie mit eigenem `days`-Dict.

        Eine flache `dict(period)`-Kopie teilte das verschachtelte `days` mit
        dem Store — der Urlaubs-Dialog bearbeitet genau dieses Dict, und eine
        Mutation am zurückgegebenen Record landete damit direkt im Speicher
        des Stores, ohne `_save_to_disk`: Speicher und Platte liefen
        auseinander.
        """
        return {**period, "days": dict(period.get("days", {}))}

    def get_all(self) -> dict[str, Vacation]:
        """Lebende Perioden — für die UI."""
        with self._lock:
            return {pid: self._copy(p) for pid, p in self._data.items()
                    if not p.get("deleted")}

    def get_all_raw(self) -> dict[str, Vacation]:
        """Komplette Objekte inkl. gcal_event_id und Tombstones — für den
        Reconcile."""
        with self._lock:
            return {pid: self._copy(p) for pid, p in self._data.items()}

    def get(self, period_id: str) -> Vacation | None:
        with self._lock:
            period = self._data.get(period_id)
            if period is None or period.get("deleted"):
                return None
            return self._copy(period)

    def save(self, period_id: str | None, name: str, date_from: str,
             date_to: str, days: dict[str, int]) -> str:
        """Legt eine Periode an oder überschreibt sie. Liefert die period_id.

        Wirft ValueError, wenn der Zeitraum eine andere lebende Periode
        schneidet — zwei überlappende Urlaube wären im Kalender nicht mehr
        eindeutig einer Periode zuzuordnen (`period_for_date`).

        Wirft ValueError bei `date_to < date_from`. Der Store schützt sich
        hier selbst, statt sich auf die Dialog-Validierung zu verlassen: ein
        Record mit vertauschtem Bereich hätte ein leeres `days` (siehe
        `expand_days`), wäre im Kalender unsichtbar (`period_for_date` matcht
        nie) und ließe sich nur noch über die Verwaltungsliste finden — ein
        stiller Zombie.

        Eine bereits vergebene `gcal_event_id` wird übernommen: das Bearbeiten
        soll das vorhandene Kalender-Event verschieben, nicht ein zweites
        anlegen.
        """
        with self._lock:
            if date_to < date_from:
                raise ValueError("Das Bis-Datum liegt vor dem Von-Datum.")
            collision = periods_overlap(self._data, period_id, date_from, date_to)
            if collision is not None:
                raise ValueError(
                    f"Der Zeitraum überschneidet sich mit dem Urlaub "
                    f"„{collision}“. Bearbeite stattdessen diesen Urlaub, "
                    f"wenn du ihn verlängern willst.")
            pid = period_id
            if pid is None:
                # Nur für NEUE Perioden würfeln. Auch gegen Tombstones
                # prüfen — deren ID ist noch vergeben, bis der Reconcile sie
                # einlöst.
                pid = secrets.token_hex(4)
                while pid in self._data:
                    pid = secrets.token_hex(4)
            existing = self._data.get(pid) or {}
            self._data[pid] = {
                "name": name,
                "from": date_from,
                "to": date_to,
                "days": {d: int(m) for d, m in days.items()},
                "gcal_event_id": existing.get("gcal_event_id"),
                "modified_at": utc_now_iso(),
                "deleted": False,
            }
            self._save_to_disk()
            return pid

    def delete(self, period_id: str) -> None:
        """Löscht eine Periode.

        Ein Tombstone entsteht NUR, wenn die Periode ein Kalender-Event trägt
        — nur dann gibt es draußen etwas aufzuräumen, und nur dann kann ihn
        jemand einlösen (`reconcile_vacations`). Ohne `gcal_event_id` wird der
        Record direkt entfernt.

        Das ist der Unterschied zu `reservations.py`, das immer einen
        Tombstone schreibt: Reservierungen SIND an den Kalender-Sync
        gekoppelt, Urlaub ist es bewusst nicht. Ein bedingungsloser Tombstone
        wäre auf jedem Rechner ohne Google unsterblich — `vacations.json`
        wüchse mit jedem gelöschten Urlaub monoton weiter, ohne dass je ein
        Pfad ihn einlöst. `src/CLAUDE.md` verlangt für jeden neuen
        Tombstone-Erzeuger genau diese Unterscheidung.

        Rest-Risiko, bewusst akzeptiert und in `src/CLAUDE.md` dokumentiert:
        wurde eine Periode gepusht und der Kalender-Sync danach abgeschaltet,
        bleibt ihr Tombstone liegen, bis der Sync wieder läuft.
        """
        with self._lock:
            existing = self._data.get(period_id)
            if existing is None:
                return
            if not existing.get("gcal_event_id"):
                del self._data[period_id]
            else:
                self._data[period_id] = {
                    **existing,
                    "days": {},
                    "modified_at": utc_now_iso(),
                    "deleted": True,
                }
            self._save_to_disk()

    def apply_reconciled(self, reconciled: dict[str, Vacation]) -> None:
        """Ersetzt den kompletten Stand durch das Reconcile-Ergebnis. Wirft
        ValueError, wenn ein Eintrag Pflichtfelder vermissen lässt — analog
        Storage.apply_merge."""
        with self._lock:
            for pid, period in reconciled.items():
                missing = _REQUIRED_VACATION_KEYS - period.keys()
                if missing:
                    raise ValueError(
                        f"apply_reconciled: entry {pid!r} missing keys "
                        f"{sorted(missing)}")
            self._data = {pid: dict(p) for pid, p in reconciled.items()}
            self._save_to_disk()

    def day_minutes(self) -> dict[str, int]:
        """Flache Sicht {ISO: minutes} über alle lebenden Perioden.

        DIE Schnittstelle zum Bericht: darauf läuft `report.filter_period`
        unverändert, weil sie dieselbe Form hat wie der Entries-Snapshot.
        Wird bei jedem Aufruf neu gebaut — bei realistischen Datenmengen
        billiger als ein zu pflegender Cache, und der Store bleibt gegenüber
        der UI zustandsfrei.
        """
        with self._lock:
            out: dict[str, int] = {}
            for period in self._data.values():
                if period.get("deleted"):
                    continue
                for day, minutes in period.get("days", {}).items():
                    out[day] = minutes
            return out

    def period_for_date(self, date_str: str) -> Vacation | None:
        """Die Periode, die diesen Tag abdeckt, um ihre `id` ergänzt — oder
        None. Perioden überschneiden sich nicht (siehe `save`), es kann also
        höchstens eine sein."""
        with self._lock:
            return period_for_day(
                {pid: p for pid, p in self._data.items() if not p.get("deleted")},
                date_str)
