"""Persistenter 'hat je gesynct/abgeglichen'-Marker (Audit N6 / Folge-Fix F).

Der Startup-Sweep (`main._sweep_orphan_tombstones`) verwirft verwaiste
Tombstones nur auf Geräten, die nie gesynct/abgeglichen haben. Ob das der Fall
ist, leiten `sync.never_synced` / `reservations_sync.never_reconciled` aus
settings.json ab (`sync_enabled`/`last_pull_at` bzw. `gcal_enabled`/
`last_calendar_sync_at`). Wird settings.json korrupt, setzt `Settings` auf
Defaults zurück (Audit M4) — ein Rechner, der sehr wohl gesynct hat, sähe dann
wie 'nie gesynct' aus und verlöre beim nächsten Start irreversibel seine
Tombstones (Resurrection gelöschter Tage über den Sync/Reconcile).

Dieser Marker ist die dauerhafte, von settings.json unabhängige Gegenprobe:
eine eigene write-once-Datei neben den Nutzerdaten, die ein settings.json-Reset
nicht berührt. Ist das jeweilige Flag gesetzt, unterbleibt der zugehörige
Sweep — auch nach einem Settings-Reset.

Fail-safe-Semantik (Richtung immer: im Zweifel Tombstones behalten):
  - Datei fehlt        -> nie markiert (frischer Single-Device-Nutzer) ->
                          Sweep ERLAUBT (genau der N6-Zweck).
  - Datei da, lesbar   -> das jeweilige Flag entscheidet.
  - Datei da, unlesbar -> als gesetzt behandeln (True): lieber Tombstones
                          behalten als fälschlich verwerfen.

Schreiben ist best-effort: scheitert es (Platte voll o.ä.), darf es den Sync
NICHT abbrechen — der Marker ist eine Absicherung des Sweeps, kein Sync-Schritt.
"""

from __future__ import annotations

import json
import logging
import os

_FILENAME = "sync_history.json"


def _path(base: str) -> str:
    return os.path.join(base, _FILENAME)


def _load(base: str) -> dict | None:
    """Liefert das Marker-Dict, {} wenn die Datei fehlt (= nie markiert), oder
    None wenn sie da, aber unlesbar/kein Dict ist (= fail-safe 'gesetzt')."""
    try:
        with open(_path(base), "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _flag(base: str, key: str) -> bool:
    data = _load(base)
    if data is None:
        return True  # unlesbar -> im Zweifel als gesetzt behandeln
    return bool(data.get(key))


def ever_synced(base: str) -> bool:
    """True, wenn dieser Rechner nachweislich (persistenter Marker) schon an
    einem Drive-Sync teilgenommen hat."""
    return _flag(base, "synced")


def ever_reconciled(base: str) -> bool:
    """True, wenn dieser Rechner nachweislich schon mit einem Kalender
    abgeglichen hat."""
    return _flag(base, "reconciled")


def _mark(base: str, key: str) -> None:
    try:
        data = _load(base)
        if not isinstance(data, dict):  # None (unlesbar) -> frisch beginnen
            data = {}
        if data.get(key):
            return  # write-once: schon gesetzt, kein erneuter Write
        data[key] = True
        tmp = _path(base) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _path(base))
    except OSError:
        logging.getLogger(__name__).warning(
            "sync_history: Marker %r konnte nicht geschrieben werden "
            "(nicht-fatal)", key, exc_info=True)


def mark_synced(base: str) -> None:
    """Vermerkt dauerhaft, dass ein Drive-Sync stattgefunden hat. Best-effort,
    idempotent. Aufrufen, wo `last_pull_at` gesetzt wird."""
    _mark(base, "synced")


def mark_reconciled(base: str) -> None:
    """Vermerkt dauerhaft, dass ein Kalender-Reconcile stattgefunden hat.
    Best-effort, idempotent. Aufrufen, wo `last_calendar_sync_at` gesetzt wird."""
    _mark(base, "reconciled")
