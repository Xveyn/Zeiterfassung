# src/json_store.py
"""Gemeinsame Persistenz-Mechanik der lokalen JSON-Stores.

Bis Issue #51 (R2) stand dieselbe Mechanik mehrfach wortgleich im Repo:
`_save_to_disk` viermal (`storage.py`, `reservations.py`, `conflicts_store.py`,
`settings.py`), der Quarantäne-Block beim Laden dreimal. Damit musste man die
N1-Durability-Regel an vier und die N4-Quarantäne-Regel an drei Stellen
mitpflegen — die Sorte Duplikat, bei der die nächste Kopie irgendwann das
`fsync` vergisst.

Die beiden Regeln stehen deshalb hier, und zwar nur hier:

- **N1 (Durability):** `fsync` VOR `os.replace`. Ohne den fsync kann das
  Rename durabel sein, während die Datenblöcke noch im OS-Cache stehen — nach
  einem Stromausfall läge dann eine leere oder halbe Datei am Zielnamen.
- **N4 (Quarantäne):** eine unparsebare Datei wird nicht kommentarlos
  verworfen, sondern nach `<name>.corrupt-<stamp>` verschoben und geloggt.
  Der Nutzer verliert seine Daten damit nicht unwiederbringlich.

**Bewusst NICHT hier:**

- `settings.py::_quarantine_corrupt` bleibt eigen. Es quarantäniert auch bei
  einem nicht-Dict-Toplevel (nicht nur bei Parse-Fehlern) und **schluckt** einen
  fehlgeschlagenen Rename, damit der Start mit Defaults weiterläuft statt zu
  crashen. Die Stores hier lassen den `OSError` bewusst hochlaufen.
- `sync_journal.py::_atomic_write_json` schreibt über `tempfile.mkstemp` statt
  über einen festen `.tmp`-Namen und räumt bei `BaseException` auf. Das ist die
  Crash-Recovery-Schicht; sie in einem Refactoring-PR mit umzustellen hieße,
  ausgerechnet den Pfad anzufassen, der die Wiederherstellung trägt.
- `webhook_store.py`/`oauth_utils.py`/`single_instance.py` schreiben Secrets und
  brauchen zusätzlich ACL-Härtung plus Rename-Retry (siehe `secure_file.py`).
"""

import datetime
import json
import logging
import os
from typing import Any


def atomic_write_json(path: str, obj: Any) -> None:
    """Schreibt `obj` als JSON atomar und durable nach `path`.

    Temp-Datei neben dem Ziel → `flush` + `fsync` (N1) → `os.replace`.
    Scheitert das Rename, wird die Temp-Datei entfernt und der `OSError`
    weitergereicht: der Aufrufer soll den fehlgeschlagenen Save sehen, und die
    bestehende Zieldatei bleibt unangetastet.

    `indent=2` ist bewusst fest verdrahtet: alle vier Stores schreiben
    menschenlesbar (die Dateien liegen im Datenverzeichnis des Nutzers und
    werden im Support-Fall gelesen). Wer eine kompakte Variante braucht,
    ergänzt sie mit dem ersten echten Aufrufer.
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        # N1: fsync vor os.replace — sonst kann das Rename durabel sein, die
        # Datenblöcke aber noch im OS-Cache (Stromausfall → leere/halbe Datei).
        f.flush()
        os.fsync(f.fileno())
    try:
        os.replace(tmp, path)
    except OSError:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def quarantine_corrupt(path: str) -> str:
    """Verschiebt eine unparsebare Datei nach `<name>.corrupt-<stamp>` (N4)
    und loggt das. Liefert den Zielpfad. Ein fehlschlagender Rename läuft als
    `OSError` hoch — hier ist er nicht harmlos: die Datei bliebe unlesbar
    liegen und der nächste Start liefe erneut hinein.
    """
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = f"{path}.corrupt-{stamp}"
    os.replace(path, target)
    logging.getLogger(__name__).warning(
        "%s korrupt (JSON nicht parsebar) — nach %s in Quarantäne "
        "verschoben, starte leer",
        os.path.basename(path), os.path.basename(target),
    )
    return target


def load_json_or_quarantine(path: str) -> Any:
    """Lädt `path` als JSON.

    Liefert `None`, wenn die Datei fehlt oder unparsebar war (dann wurde sie
    über `quarantine_corrupt` weggeräumt). Der Aufrufer setzt daraufhin seinen
    leeren Startzustand — welcher das ist, weiß nur er (`{}`, `[]`, Defaults).

    `None` deckt damit auch den entarteten Fall ab, dass die Datei zwar
    gültiges JSON, aber `null` enthält: vorher landete dieses `None` ungeprüft
    im `_data` des Stores und ließ die anschließende Migration mit einem
    `AttributeError` auflaufen.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        quarantine_corrupt(path)
        return None
