# Storage-Härtung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein beschädigter oder fremder Stand (Sync-Doc, Handbearbeitung) bringt `Storage` nie mehr zum Absturz: kein Start-Absturz bei falschem Top-Level, kein `AttributeError`/`ValueError` in `get`/`get_all`, und UI, Berichte und API sehen immer wohlgeformte Slots.

**Architecture:** Zwei Linien. (1) **Lese-Grenze:** `sanitize_slot` bereinigt jeden Slot in `Storage._user_shape` (Nicht-Objekte entfallen, `start`/`end` Text oder `None`, `kategorie` Text, `pause` ganze Zahl 0–1440 sonst 0), nicht-objektförmige Einträge gelten als nicht vorhanden; das Original bleibt unangetastet, `get_all_raw()` und der Sync sehen es weiter. (2) **Laden:** ein Top-Level, das kein Objekt ist, wird wie unparsebar quarantäniert; Einträge ohne Objektform und Slot-Listen ohne Objekte werden mit Sicherungskopie (`.corrupt-<stamp>`) repariert und zurückgeschrieben. Dazu lehnt `validate_remote_doc` Slot-Listen mit Nicht-Objekten ab.

**Tech Stack:** Python 3.12, stdlib. Keine neue Abhängigkeit.

**Spec/Anlass:** Befund M4 des Reviews zu PR 5 (Issue #233, Kommentar vom 2026-10-08): `Storage.get_all()` stürzt bei `null`-Einträgen, Text-Einträgen und `"slots": ["x"]` ab; ein Top-Level `[]` verhindert den App-Start. Kein eigenes Spec-Dokument: die Entscheidungen stehen unten.

**Branching:** Stack. `feat/storage-haerten` ist aus `feat/api-analytics` (PR #241) abgezweigt und liegt an. Der PR zielt auf `feat/api-analytics` und wird danach mit `POST /repos/Xveyn/Zeiterfassung/stacks/236/add` an den Stack gehängt. PR-Text: `Refs #233` (und `Refs #92`), kein `Closes`. **Kein Versionsbump** (gehört in den Release-PR).

## Entscheidungen (mit dem Nutzer abgestimmt)

- **Pause:** ungültig oder über 1440 Minuten wird `0` (nicht abgeschnitten). `30.0` zählt als `30`.
- **Nicht-Objekt-Einträge beim Laden:** verworfen, nach Sicherungskopie und mit Rückschreiben des reparierten Stands; **kein** Startabbruch.
- **Strukturell kaputtes Remote-Doc** (`slots` enthält ein Nicht-Objekt): ungültig wie bisher die anderen Strukturfehler (Remote quarantänen, lokaler Stand wird neue Wahrheit). Wertfehler in Slots lehnt `validate_remote_doc` nicht ab; die Lese-Grenze fängt sie ab.
- Nicht enthalten: `ReservationStore`/`VacationStore` (gleiches Muster, Follow-up über #239).

## Rulings aus der Planung

- `sanitize_slot` **behält weitere Schlüssel** eines Slots (Überlagerung der vier Felder auf einer Kopie), damit sich für saubere Daten nichts ändert. Ein Slot ohne `pause`/`kategorie` bekommt an der Lese-Grenze `0`/`""` (vorher fehlten die Schlüssel); Verbraucher nutzen ohnehin `.get(..., 0)`.
- Die **Reparatur beim Laden betrifft nur Struktur** (kein Objekt, `slots` keine Liste, Slot kein Objekt). Wertfehler wie `pause: null` bleiben roh in der Datei: sie zu ändern verfälschte, was der Sync als „lokal geändert“ sieht, und erzeugte Schein-Konflikte.
- Lässt sich die **Sicherung nicht anlegen**, wird nicht zurückgeschrieben (nichts geht still verloren); der reparierte Stand gilt dann nur im Speicher und der Start gelingt trotzdem. Ein Fehler beim Zurückschreiben selbst stoppt den Start ebenfalls nicht.
- `json_store.quarantine_corrupt` bekommt einen optionalen `reason` (Standard unverändert „JSON nicht parsebar“), damit die Logzeile bei „Top-Level ist list“ nicht lügt.

## Global Constraints

- Tk-frei, stdlib-only, vollständig annotiert (`src/storage.py`, `src/json_store.py`, `src/sync.py` stehen in `ANNOTATED_MODULES`); `pyright 1.1.411` und `ruff check .` sauber.
- **Die Rohdaten bleiben unangetastet** außer in der Lade-Reparatur (Struktur, mit Sicherung): `get_all_raw()` liefert weiter das Original; Lesen verändert nie.
- Jeder `except Exception`/`BaseException` loggt, meldet oder begründet im Handler; hier nur `except OSError` mit Log (`tests/test_catch_all_handlers.py`).
- Keine Datenverluste ohne Spur: was beim Laden verworfen wird, steht vorher in `<datei>.corrupt-<stamp>`.
- `Storage.save`/`delete`/`save_many`/`apply_merge` und ihr Rollback bleiben unverändert.

## Review Focus

1. **Start-Absturz:** Top-Level `[]`, `"text"`, `42`, `true` (nicht nur `null`): die App startet leer, die Datei liegt in Quarantäne, der Inhalt ist gerettet. Task 3.
2. **Keine Sicherungs-Flut:** ein geheilter Stand legt beim nächsten Start keine zweite Sicherung an; eine saubere Datei wird weder gesichert noch neu geschrieben (mtime bleibt). Task 3.
3. **Sync bleibt unberührt:** `get_all_raw()` zeigt nach dem Lesen unverändert das Original; `pause: null` bleibt roh, ist aber gelesen `0`. Task 2 und 3.
4. **Pause-Grenzen:** `None`, Bool, Text, `30.5`, negativ, 1441, `inf`/`nan`, `10**400`, Liste: alles `0`; `0`, `30`, `30.0`, 1440 bleiben. Task 2.
5. **Remote-Doc:** `slots: [null]`, `["x"]`, `[5]`, `[["a"]]` werden abgelehnt, ungewöhnliche Werte nicht. Task 4.
6. **Die API:** `/v1/entries` und `/v1/summary/…` über eine echte beschädigte Datei liefern 200 und strenges JSON (kein `-Infinity`/`NaN`). Task 5.
7. **Fehler beim Heilen:** Sicherung scheitert oder Zurückschreiben scheitert: der Start gelingt, nichts wird überschrieben. Task 3.

---

### Task 1: `json_store` — Grund in der Quarantäne-Meldung, Sicherungskopie

**Files:**
- Modify: `src/json_store.py`
- Modify: `tests/test_json_store.py`

**Interfaces:**
- Produces: `quarantine_corrupt(path: str, reason: str = "JSON nicht parsebar") -> str` (Verhalten für den Standard unverändert) und `backup_corrupt(path: str, reason: str) -> str` (kopiert nach `<name>.corrupt-<stamp>`, das Original bleibt, `OSError` läuft hoch).

- [ ] **Step 1: Write the failing tests**

In `tests/test_json_store.py` ersetze

```python
from src.json_store import atomic_write_json, load_json_or_quarantine, quarantine_corrupt
```

durch

```python
from src.json_store import (
    atomic_write_json, backup_corrupt, load_json_or_quarantine, quarantine_corrupt,
)
```

und füge direkt vor dem Abschnitt `# --- load_json_or_quarantine` (zwei Leerzeilen Abstand) ein:

```python
def test_quarantine_names_the_reason_in_the_log(tmp_path, caplog):
    path = tmp_path / "liste.json"
    path.write_text("[]", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        quarantine_corrupt(str(path), "Top-Level ist list, erwartet ein Objekt")

    assert "Top-Level ist list" in caplog.text
    assert "JSON nicht parsebar" not in caplog.text


def test_quarantine_default_reason_is_unchanged(tmp_path, caplog):
    path = tmp_path / "kaputt.json"
    path.write_text("{", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        quarantine_corrupt(str(path))
    assert "JSON nicht parsebar" in caplog.text


# --- backup_corrupt ---------------------------------------------------------

def test_backup_copies_and_keeps_the_original(tmp_path, caplog):
    path = tmp_path / "store.json"
    path.write_text('{"a": null}', encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        target = backup_corrupt(str(path), "1 Eintrag ohne Objektform")

    assert path.read_text(encoding="utf-8") == '{"a": null}'
    assert open(target, encoding="utf-8").read() == '{"a": null}'
    assert os.path.basename(target).startswith("store.json.corrupt-")
    assert "Sicherung" in caplog.text and "1 Eintrag ohne Objektform" in caplog.text


def test_backup_of_a_missing_file_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        backup_corrupt(str(tmp_path / "gibt-es-nicht.json"), "egal")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_json_store.py -q -p no:cacheprovider`
Expected: ERROR at collection, `ImportError: cannot import name 'backup_corrupt' from 'src.json_store'`.

- [ ] **Step 3: Implement**

In `src/json_store.py` ersetze

```python
import os
import tempfile
```

durch

```python
import os
import shutil
import tempfile
```

In `src/json_store.py` ersetze

```python
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
```

durch

```python
def quarantine_corrupt(path: str, reason: str = "JSON nicht parsebar") -> str:
    """Verschiebt eine unbrauchbare Datei nach `<name>.corrupt-<stamp>` (N4)
    und loggt das. Liefert den Zielpfad. `reason` steht in der Logzeile (Standard:
    unparsebar; „Top-Level ist eine Liste“ ist ebenso gültiges JSON, aber kein
    Store). Ein fehlschlagender Rename läuft als `OSError` hoch — hier ist er
    nicht harmlos: die Datei bliebe unlesbar liegen und der nächste Start liefe
    erneut hinein.
    """
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = f"{path}.corrupt-{stamp}"
    os.replace(path, target)
    logging.getLogger(__name__).warning(
        "%s korrupt (%s) — nach %s in Quarantäne verschoben, starte leer",
        os.path.basename(path), reason, os.path.basename(target),
    )
    return target


def backup_corrupt(path: str, reason: str) -> str:
    """Kopiert eine Datei, die gleich repariert wird, nach `<name>.corrupt-<stamp>`
    (anders als `quarantine_corrupt` bleibt das Original liegen) und loggt das.
    Liefert den Zielpfad. `OSError` läuft hoch: ohne Sicherung repariert der
    Aufrufer nicht, damit nichts still verloren geht."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = f"{path}.corrupt-{stamp}"
    shutil.copy2(path, target)
    logging.getLogger(__name__).warning(
        "%s enthält Unbrauchbares (%s) — Sicherung nach %s, der Rest wird repariert",
        os.path.basename(path), reason, os.path.basename(target),
    )
    return target
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_json_store.py -q -p no:cacheprovider && ruff check src tests`
Expected: PASS (17 Tests), `All checks passed!`.

- [ ] **Step 5: Commit**

~~~bash
git add src/json_store.py tests/test_json_store.py
git commit -m "feat(storage): Grund in der Quarantäne-Meldung und Sicherungskopie (#233)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 2: Lese-Grenze — `sanitize_slot`, `_user_shape`, `get`, `get_all`

**Files:**
- Modify: `src/storage.py`
- Create: `tests/test_storage_hardening.py`

**Interfaces:**
- Consumes: nichts aus Task 1.
- Produces: `MAX_PAUSE_MINUTES = 1440`, `sanitize_slot(slot: Any) -> Slot | None`; `Storage.get`/`get_all` überspringen Nicht-Objekt-Einträge und liefern bereinigte Slots.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_storage_hardening.py`:

```python
# tests/test_storage_hardening.py
"""Ein beschädigter oder fremder Stand darf `Storage` nie zum Absturz bringen.

Zwei Linien: beim Laden wird die STRUKTUR repariert (mit Sicherung), und an der
Lese-Grenze (`get`/`get_all`) werden die WERTE bereinigt (`sanitize_slot`). Das
Original bleibt dort unangetastet, damit der Sync keine spontanen Änderungen sieht.
"""
import pytest

from src.storage import MAX_PAUSE_MINUTES, Storage, sanitize_slot
from tests.conftest import ist_slot

DAY = "2026-01-05"


def entry(slots, deleted=False):
    return {"slots": slots, "modified_at": "2026-01-05T08:00:00Z", "device_id": "x",
            "deleted": deleted}


# --- sanitize_slot ------------------------------------------------------------------------------

@pytest.mark.parametrize("junk", [None, "x", 5, 5.5, True, ["a"], ()])
def test_a_non_object_slot_is_dropped(junk):
    assert sanitize_slot(junk) is None


@pytest.mark.parametrize("pause", [None, True, False, "30", "", 30.5, -1, -0.5,
                                   MAX_PAUSE_MINUTES + 1, float("inf"), float("-inf"),
                                   float("nan"), 10 ** 400, [30], {"a": 1}])
def test_an_unusable_pause_becomes_zero(pause):
    assert sanitize_slot(ist_slot("08:00", "12:00", pause))["pause"] == 0


@pytest.mark.parametrize("pause,expected", [(0, 0), (30, 30), (30.0, 30),
                                            (MAX_PAUSE_MINUTES, MAX_PAUSE_MINUTES)])
def test_a_usable_pause_is_kept_as_an_int(pause, expected):
    clean = sanitize_slot(ist_slot("08:00", "12:00", pause))
    assert clean["pause"] == expected and type(clean["pause"]) is int


@pytest.mark.parametrize("junk", [None, 5, True, ["08:00"], {"a": 1}])
def test_start_and_end_must_be_text(junk):
    clean = sanitize_slot({"start": junk, "end": junk, "pause": 0, "kategorie": ""})
    assert (clean["start"], clean["end"]) == (None, None)


@pytest.mark.parametrize("junk", [None, 5, True, ["x"]])
def test_a_non_text_category_becomes_empty(junk):
    assert sanitize_slot(ist_slot("08:00", "12:00", 0, junk))["kategorie"] == ""


def test_missing_fields_get_their_defaults():
    assert sanitize_slot({"start": "08:00", "end": "12:00"}) == ist_slot("08:00", "12:00", 0, "")
    assert sanitize_slot({}) == ist_slot(None, None, 0, "")


def test_a_clean_slot_is_unchanged_and_other_keys_survive():
    slot = dict(ist_slot("08:00", "12:00", 30, "Büro"), extra=1)
    assert sanitize_slot(slot) == slot


def test_sanitize_returns_a_copy():
    slot = ist_slot("08:00", "12:00", None)
    clean = sanitize_slot(slot)
    clean["start"] = "99:99"
    assert slot == ist_slot("08:00", "12:00", None)


# --- Lese-Grenze: get / get_all ---------------------------------------------------------------------

@pytest.fixture
def storage(tmp_path):
    return Storage(str(tmp_path / "z.json"), device_id="dev")


def test_get_all_skips_non_object_entries_and_drops_non_object_slots(storage):
    storage._data.update({
        "2026-01-05": None, "2026-01-06": "x", "2026-01-07": ["a"], "2026-01-08": 5,
        "2026-01-09": entry(["x", None, ist_slot("08:00", "09:00")]),
        "2026-01-10": entry("kaputt"), "2026-01-11": {"modified_at": "a"},
    })

    assert storage.get_all() == {
        "2026-01-09": {"slots": [ist_slot("08:00", "09:00")]},
        "2026-01-10": {"slots": []},
        "2026-01-11": {"slots": []},
    }


def test_get_treats_a_non_object_entry_as_absent(storage):
    storage._data[DAY] = "x"
    assert storage.get(DAY) is None


def test_get_cleans_the_values_of_a_slot(storage):
    storage._data[DAY] = entry([{"start": "08:00", "end": "12:00", "pause": None,
                                 "kategorie": 7}])
    assert storage.get(DAY) == {"slots": [ist_slot("08:00", "12:00", 0, "")]}


def test_reading_never_changes_the_raw_data(storage):
    raw = entry([{"start": "08:00", "end": "12:00", "pause": float("inf")}, "x"])
    storage._data[DAY] = raw
    snapshot = repr(raw)

    storage.get_all()
    storage.get(DAY)

    assert repr(storage.get_all_raw()[DAY]) == snapshot


def test_a_returned_slot_is_a_copy(storage):
    storage.save(DAY, [ist_slot("08:00", "12:00")])
    storage.get(DAY)["slots"][0]["start"] = "x"
    assert storage.get(DAY)["slots"][0]["start"] == "08:00"


def test_hours_can_be_computed_for_every_cleaned_slot(storage):
    from src.time_utils import calculate_hours
    storage._data[DAY] = entry([ist_slot("08:00", "12:00", pause)
                                for pause in (None, "x", float("nan"), 10 ** 400, True)])
    for slot in storage.get(DAY)["slots"]:
        assert calculate_hours(slot["start"], slot["end"], slot["pause"]) == 4.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_storage_hardening.py -q -p no:cacheprovider`
Expected: ERROR at collection, `ImportError: cannot import name 'MAX_PAUSE_MINUTES' from 'src.storage'`.

- [ ] **Step 3: Implement**

In `src/storage.py` ersetze

```python
REQUIRED_ENTRY_KEYS = frozenset({"slots", "modified_at", "device_id", "deleted"})
```

durch

```python
REQUIRED_ENTRY_KEYS = frozenset({"slots", "modified_at", "device_id", "deleted"})

# Eine Pause über einen ganzen Tag hinaus ist kein Wert, sondern Müll.
MAX_PAUSE_MINUTES = 24 * 60
```

In `src/storage.py` ersetze

```python
class Storage:
    def __init__
```

durch

```python
def sanitize_slot(slot: Any) -> Slot | None:
    """Ein wohlgeformter Ist-Zeit-Slot aus einem gespeicherten, oder `None`.

    Gespeicherte Slots sind Fremddaten: der Sync prüft nur, dass `slots` eine
    Liste ist, und eine Datei lässt sich von Hand ändern. Alles, was die Datei
    hergibt, läuft hier durch, bevor UI, Berichte und API es sehen:
    - Kein Objekt → `None` (der Slot entfällt).
    - `start`/`end` nur als Text, sonst `None` (`calculate_hours` zählt das 0).
    - `kategorie` nur als Text, sonst `""`.
    - `pause` eine ganze Zahl von 0 bis `MAX_PAUSE_MINUTES` (`30.0` zählt als 30),
      sonst `0`: `None`, Bool, Text, negativ, `inf`/`nan` und Riesen-Ints
      brächten sonst jede Rechnung damit zum Absturz.
    Weitere Schlüssel bleiben erhalten; das Original wird nie verändert."""
    if not isinstance(slot, dict):
        return None
    pause = slot.get("pause", 0)
    if isinstance(pause, float) and pause.is_integer():
        pause = int(pause)
    if isinstance(pause, bool) or not isinstance(pause, int) or not 0 <= pause <= MAX_PAUSE_MINUTES:
        pause = 0
    start, end, kategorie = slot.get("start"), slot.get("end"), slot.get("kategorie", "")
    clean = dict(slot)
    clean.update({
        "start": start if isinstance(start, str) else None,
        "end": end if isinstance(end, str) else None,
        "pause": pause,
        "kategorie": kategorie if isinstance(kategorie, str) else "",
    })
    return clean


class Storage:
    def __init__
```

In `src/storage.py` ersetze

```python
    @staticmethod
    def _user_shape(entry: Entry) -> dict[str, Any]:
        """Reduziert ein Roh-Entry auf {slots: [...]} für UI-Caller.
        Liefert frische Kopien, damit Caller den internen Stand nicht mutieren."""
        return {"slots": [dict(s) for s in entry.get("slots", [])]}
```

durch

```python
    @staticmethod
    def _user_shape(entry: Any) -> dict[str, Any]:
        """Reduziert ein Roh-Entry auf {slots: [...]} für UI-Caller.
        Liefert frische, bereinigte Kopien (`sanitize_slot`), damit Caller den
        internen Stand nicht mutieren und nie auf Fremddaten treffen, die ihre
        Rechnung zum Absturz bringen."""
        slots = entry.get("slots") if isinstance(entry, dict) else None
        if not isinstance(slots, list):
            return {"slots": []}
        return {"slots": [clean for clean in map(sanitize_slot, slots) if clean is not None]}
```

In `src/storage.py` ersetze

```python
                for date, entry in self._data.items()
                if not entry.get("deleted")
```

durch

```python
                for date, entry in self._data.items()
                if isinstance(entry, dict) and not entry.get("deleted")
```

In `src/storage.py` ersetze

```python
            if entry is None or entry.get("deleted"):
                return None
```

durch

```python
            if not isinstance(entry, dict) or entry.get("deleted"):
                return None
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_storage_hardening.py tests/test_storage.py tests/test_type_annotations.py -q -p no:cacheprovider && ruff check src tests`
Expected: PASS (189 Tests), `All checks passed!`.

- [ ] **Step 5: Commit**

~~~bash
git add src/storage.py tests/test_storage_hardening.py
git commit -m "feat(storage): Slots werden an der Lese-Grenze bereinigt (#233)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 3: Laden — Top-Level, Einträge und Slot-Listen reparieren

**Files:**
- Modify: `src/storage.py`
- Modify: `tests/test_storage_hardening.py`

**Interfaces:**
- Consumes: Task 1 (`quarantine_corrupt(path, reason)`, `backup_corrupt`), Task 2 (`sanitize_slot` bleibt unverändert).
- Produces: `Storage._load` startet auch bei einem Nicht-Objekt-Top-Level; `_drop_non_object_entries() -> int`, `_repair_slot_structure() -> int`, `_heal(problems: str) -> None`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_storage_hardening.py`:

In `tests/test_storage_hardening.py` ersetze

```python
import pytest

from src.storage import
```

durch

```python
import json
import logging
import math
import os

import pytest

from src.storage import
```

Füge direkt hinter der Funktion `entry(...)` (vor `# --- sanitize_slot`) ein:

```python
def write(tmp_path, content, name="z.json"):
    path = tmp_path / name
    path.write_text(content if isinstance(content, str) else json.dumps(content),
                    encoding="utf-8")
    return str(path)


def backups(tmp_path):
    return sorted(p.name for p in tmp_path.iterdir() if ".corrupt-" in p.name)
```

Hänge ans Dateiende an:

```python
# --- Laden: Struktur --------------------------------------------------------------------------------------

@pytest.mark.parametrize("content", ["[]", "[1, 2]", '"text"', "42", "true", "3.5"])
def test_a_non_object_top_level_is_quarantined_and_the_app_starts_empty(tmp_path, content, caplog):
    path = write(tmp_path, content)

    with caplog.at_level(logging.WARNING):
        storage = Storage(path, device_id="dev")

    assert storage.get_all() == {}
    assert not os.path.exists(path)
    (name,) = backups(tmp_path)
    assert (tmp_path / name).read_text(encoding="utf-8") == content          # Inhalt gerettet
    assert "Top-Level" in caplog.text and "Quarantäne" in caplog.text
    storage.save(DAY, [ist_slot("08:00", "09:00")])                          # und benutzbar
    assert Storage(path, device_id="dev").get(DAY) == {"slots": [ist_slot("08:00", "09:00")]}


def test_non_object_entries_are_dropped_with_a_backup_and_the_file_is_healed(tmp_path, caplog):
    original = {"2026-01-05": entry([ist_slot("08:00", "09:00")]), "2026-01-06": None,
                "2026-01-07": "x", "2026-01-08": [1]}
    path = write(tmp_path, original)

    with caplog.at_level(logging.WARNING):
        storage = Storage(path, device_id="dev")

    assert list(storage.get_all()) == ["2026-01-05"]
    (name,) = backups(tmp_path)
    assert json.loads((tmp_path / name).read_text(encoding="utf-8")) == original
    assert "Sicherung" in caplog.text
    assert sorted(json.loads(open(path, encoding="utf-8").read())) == ["2026-01-05"]   # geheilt


def test_a_healed_file_makes_no_second_backup_on_the_next_start(tmp_path):
    path = write(tmp_path, {"2026-01-05": None, "2026-01-06": entry(["x"])})
    Storage(path, device_id="dev")
    assert len(backups(tmp_path)) == 1

    Storage(path, device_id="dev")
    Storage(path, device_id="dev")

    assert len(backups(tmp_path)) == 1


def test_broken_slot_lists_are_repaired(tmp_path):
    path = write(tmp_path, {
        "2026-01-05": entry(["x", None, ist_slot("08:00", "09:00"), 5]),
        "2026-01-06": entry("kaputt"), "2026-01-07": entry(None), "2026-01-08": entry({"a": 1}),
    })

    storage = Storage(path, device_id="dev")

    raw = storage.get_all_raw()
    assert raw["2026-01-05"]["slots"] == [ist_slot("08:00", "09:00")]
    assert [raw[d]["slots"] for d in ("2026-01-06", "2026-01-07", "2026-01-08")] == [[], [], []]
    assert len(backups(tmp_path)) == 1


def test_repair_keeps_metadata_and_tombstones(tmp_path):
    tomb = entry([], deleted=True)
    path = write(tmp_path, {"2026-01-05": entry(["x", ist_slot("08:00", "09:00")]),
                            "2026-01-06": tomb})

    raw = Storage(path, device_id="dev").get_all_raw()

    assert raw["2026-01-05"]["modified_at"] == "2026-01-05T08:00:00Z"
    assert raw["2026-01-05"]["device_id"] == "x"
    assert raw["2026-01-06"] == tomb


def test_unusual_values_stay_raw_on_disk_but_are_clean_when_read(tmp_path):
    odd = {"start": "08:00", "end": "12:00", "pause": None, "kategorie": ""}
    path = write(tmp_path, {DAY: entry([odd])})

    storage = Storage(path, device_id="dev")

    assert storage.get_all_raw()[DAY]["slots"] == [odd]                      # Sync sieht das Original
    assert storage.get(DAY) == {"slots": [ist_slot("08:00", "12:00", 0, "")]}
    assert backups(tmp_path) == []                                           # kein Anlass zur Reparatur


def test_a_clean_file_is_neither_backed_up_nor_rewritten(tmp_path):
    path = write(tmp_path, {DAY: entry([ist_slot("08:00", "09:00")])})
    os.utime(path, (1_000_000_000, 1_000_000_000))

    Storage(path, device_id="dev")

    assert backups(tmp_path) == []
    assert os.path.getmtime(path) == 1_000_000_000


def test_legacy_entries_are_still_migrated_next_to_broken_ones(tmp_path):
    path = write(tmp_path, {"2026-01-05": {"start": "08:00", "end": "09:00", "pause": 15},
                            "2026-01-06": None})

    storage = Storage(path, device_id="dev")

    assert storage.get(DAY) == {"slots": [ist_slot("08:00", "09:00", 15)]}


def test_without_a_backup_nothing_is_written_back(tmp_path, monkeypatch, caplog):
    original = {DAY: entry([ist_slot("08:00", "09:00")]), "2026-01-06": None}
    path = write(tmp_path, original)

    def refuse(*_args):
        raise OSError("Platte voll")
    monkeypatch.setattr("src.storage.backup_corrupt", refuse)

    with caplog.at_level(logging.WARNING):
        storage = Storage(path, device_id="dev")

    assert list(storage.get_all()) == [DAY]                                  # der Start gelingt
    assert json.loads(open(path, encoding="utf-8").read()) == original       # Datei unberührt
    assert "nicht auf die Platte" in caplog.text


def test_a_failing_heal_write_does_not_stop_the_start(tmp_path, monkeypatch):
    path = write(tmp_path, {DAY: entry([ist_slot("08:00", "09:00")]), "2026-01-06": None})

    def refuse(self):
        raise OSError("schreibgeschützt")
    monkeypatch.setattr(Storage, "_save_to_disk", refuse)

    assert list(Storage(path, device_id="dev").get_all()) == [DAY]


def test_nan_never_reaches_a_reader(tmp_path):
    path = write(tmp_path, '{"2026-01-05": {"slots": [{"start": "08:00", "end": "12:00", '
                           '"pause": NaN, "kategorie": ""}], "modified_at": "a", '
                           '"device_id": "x", "deleted": false}}')
    pause = Storage(path, device_id="dev").get(DAY)["slots"][0]["pause"]
    assert pause == 0 and not math.isnan(pause)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_storage_hardening.py -q -p no:cacheprovider`
Expected: FAIL — u. a. `AttributeError: 'list' object has no attribute 'items'` (Top-Level `[]`), `AttributeError`/`ValueError` in `_migrate_legacy_entries`/`get_all`, fehlende `.corrupt-`-Dateien.

- [ ] **Step 3: Implement**

In `src/storage.py` ersetze

```python
import datetime
import os
import threading
from typing import Any

from src.json_store import atomic_write_json, load_json_or_quarantine
```

durch

```python
import datetime
import logging
import os
import threading
from typing import Any

from src.json_store import (
    atomic_write_json, backup_corrupt, load_json_or_quarantine, quarantine_corrupt,
)
```

In `src/storage.py` ersetze

```python
# Eine Pause über
```

durch

```python
log = logging.getLogger(__name__)

# Eine Pause über
```

In `src/storage.py` ersetze

```python
        data = load_json_or_quarantine(self.filepath)
        if data is None:  # nicht vorhanden oder korrupt (dann quarantäniert)
            self._data = {}
            return
        self._data = data
        self._migrate_legacy_entries()
```

durch

```python
        data = load_json_or_quarantine(self.filepath)
        if data is None:  # nicht vorhanden oder korrupt (dann quarantäniert)
            self._data = {}
            return
        if not isinstance(data, dict):
            # Gültiges JSON, aber kein Store (Liste, Text, Zahl): sonst stürbe schon
            # der Start in der Migration. Wie unparsebar behandeln.
            quarantine_corrupt(
                self.filepath, f"Top-Level ist {type(data).__name__}, erwartet ein Objekt")
            self._data = {}
            return
        self._data = data
        dropped = self._drop_non_object_entries()
        self._migrate_legacy_entries()
        repaired = self._repair_slot_structure()
        if dropped or repaired:
            self._heal(f"{dropped} Eintrag/Einträge ohne Objektform, "
                       f"{repaired} Eintrag/Einträge mit kaputter Slot-Liste")

    def _drop_non_object_entries(self) -> int:
        """Entfernt Tage, deren Wert kein Objekt ist (`null`, Text, Liste)."""
        bad = [day for day, entry in self._data.items() if not isinstance(entry, dict)]
        for day in bad:
            del self._data[day]
        return len(bad)

    def _repair_slot_structure(self) -> int:
        """Macht aus einer Nicht-Liste als `slots` eine leere Liste und wirft
        Nicht-Objekte aus der Liste. Nur die STRUKTUR: ungewöhnliche Werte in einem
        Slot (`pause: null`) bleiben roh liegen und werden an der Lese-Grenze
        (`sanitize_slot`) bereinigt, damit der Sync keine spontanen Änderungen sieht."""
        fixed = 0
        for entry in self._data.values():
            slots = entry.get("slots")
            if not isinstance(slots, list):
                entry["slots"] = []
                fixed += 1
                continue
            objects = [slot for slot in slots if isinstance(slot, dict)]
            if len(objects) != len(slots):
                entry["slots"] = objects
                fixed += 1
        return fixed

    def _heal(self, problems: str) -> None:
        """Sichert die Datei, dann schreibt sie den reparierten Stand zurück —
        sonst fände jeder Start dasselbe vor und legte jedes Mal eine Sicherung an.
        Ohne Sicherung wird nicht geschrieben (nichts geht still verloren); der
        reparierte Stand gilt dann nur im Speicher."""
        try:
            backup_corrupt(self.filepath, problems)
            self._save_to_disk()
        except OSError:
            log.warning("%s: Reparatur nicht auf die Platte geschrieben, der Stand "
                        "gilt nur im Speicher", os.path.basename(self.filepath),
                        exc_info=True)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_storage_hardening.py tests/test_storage.py -q -p no:cacheprovider && ruff check src tests && npx --yes pyright@1.1.411 src/storage.py src/json_store.py`
Expected: PASS (90 Tests), `All checks passed!`, `0 errors`.

- [ ] **Step 5: Commit**

~~~bash
git add src/storage.py tests/test_storage_hardening.py
git commit -m "feat(storage): beschädigte Dateien beim Laden reparieren, mit Sicherung (#233)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 4: `validate_remote_doc` prüft die Slot-Elemente

**Files:**
- Modify: `src/sync.py`
- Modify: `tests/test_sync.py`

**Interfaces:**
- Consumes: nichts.
- Produces: `validate_remote_doc` lehnt Einträge ab, deren `slots` ein Nicht-Objekt enthalten (Grund nennt Datum und „slots“).

- [ ] **Step 1: Write the failing tests**

In `tests/test_sync.py` füge direkt hinter `test_validate_rejects_entry_modified_at_not_string` ein:

```python
@pytest.mark.parametrize("junk", [None, "x", 5, ["a"], [None]], ids=repr)
def test_validate_rejects_a_slot_that_is_not_an_object(junk):
    # slots war nur als Liste geprüft: [null] lief durch und ließ später get_all() abstürzen
    doc = _valid_remote_doc()
    doc["entries"]["2026-05-14"]["slots"] = [junk]
    ok, reason = validate_remote_doc(doc)
    assert ok is False
    assert "slots" in reason and "2026-05-14" in reason


def test_validate_still_accepts_slots_with_unusual_values():
    # Wertfehler fängt die Lese-Grenze von Storage ab; abgelehnt wird nur die Struktur
    doc = _valid_remote_doc()
    doc["entries"]["2026-05-14"]["slots"] = [
        {"start": "08:00", "end": "12:00", "pause": None, "kategorie": 5}, {}]
    ok, reason = validate_remote_doc(doc)
    assert ok is True, reason
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_sync.py -q -p no:cacheprovider -k "slot_that_is_not_an_object or unusual_values"`
Expected: FAIL — der Reject-Test bekommt `ok is True` (das Doc läuft durch), der Accept-Test ist grün (Gegenprobe, soll es bleiben).

- [ ] **Step 3: Implement**

In `src/sync.py` ersetze

```python
        if not isinstance(entry.get("slots"), list):
            return False, f"entry {date!r}: slots ist keine Liste"
```

durch

```python
        if not isinstance(entry.get("slots"), list):
            return False, f"entry {date!r}: slots ist keine Liste"
        if not all(isinstance(slot, dict) for slot in entry["slots"]):
            return False, f"entry {date!r}: slots enthält ein Nicht-Objekt"
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_sync.py -q -p no:cacheprovider && ruff check src tests`
Expected: PASS (94 Tests), `All checks passed!`.

- [ ] **Step 5: Commit**

~~~bash
git add src/sync.py tests/test_sync.py
git commit -m "fix(sync): Remote-Doc mit Nicht-Objekt in slots ist ungültig (#233)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 5: Die API über eine beschädigte Datei, Doku und Gesamtlauf

**Files:**
- Modify: `tests/test_api_routes.py`, `src/api_summary.py` (nur Docstring), `src/CLAUDE.md`, `CLAUDE.md`, `docs/known-limitations.md`

**Interfaces:** keine; hält Doku und Verhalten zusammen.

- [ ] **Step 1: Tests über einen echten Storage**

Hänge ans Ende von `tests/test_api_routes.py` an:

```python
# --- Fremddaten in der Datei: dieselbe Antwort wie für saubere Daten, nie 500 ------------------

def test_the_api_reads_a_store_file_with_broken_entries(tmp_path):
    path = tmp_path / "z.json"
    good = {"slots": [ist_slot("08:00", "12:00", 0, "Projekt")], "modified_at": "2026-01-05T08:00:00Z",
            "device_id": "x", "deleted": False}
    path.write_text(json.dumps({
        "2026-01-05": good, "2026-01-06": None, "2026-01-07": "x",
        "2026-01-08": dict(good, slots=["x", None, {"start": "09:00", "end": "10:00",
                                                    "pause": None, "kategorie": 5}]),
    }), encoding="utf-8")
    env = Env(tmp_path)
    env.storage = Storage(str(path), device_id="dev")
    env.ctx = ApiContext(storage=env.storage, settings={}, app_version=lambda: "t",
                         vacation_store=env.vacations)

    entries = get(env, "/v1/entries")
    month = get(env, "/v1/summary/month/2026-01")

    assert entries.status == 200 and month.status == 200
    assert list(entries.body["entries"]) == ["2026-01-05", "2026-01-08"]
    assert entries.body["entries"]["2026-01-08"]["slots"] == [ist_slot("09:00", "10:00", 0, "")]
    assert month.body["total_minutes"] == 240 + 60
    assert get(env, "/v1/entries/2026-01-06").status == 404


def test_an_absurd_stored_pause_gives_strict_json_over_entries(tmp_path):
    path = tmp_path / "z.json"
    path.write_text('{"2026-01-05": {"slots": [{"start": "08:00", "end": "12:00", "pause": '
                    '-Infinity, "kategorie": ""}], "modified_at": "a", "device_id": "x", '
                    '"deleted": false}}', encoding="utf-8")
    env = Env(tmp_path)
    env.storage = Storage(str(path), device_id="dev")
    env.ctx = ApiContext(storage=env.storage, settings={}, app_version=lambda: "t")

    body = get(env, "/v1/entries").body

    assert body["entries"]["2026-01-05"]["slots"][0]["pause"] == 0
    json.dumps(body, allow_nan=False)                       # strikt: kein -Infinity/NaN mehr
```

Run: `python3 -m pytest tests/test_api_routes.py -q -p no:cacheprovider`
Expected: PASS (153 Tests). Beide Tests wären **vor** Task 2 und 3 rot gewesen (`get_all()` wirft bzw. `-Infinity` im JSON); sie sind hier die Regression für die Befunde M4 und den `-Infinity`-Hinweis des PR-5-Reviews.

- [ ] **Step 2: Docstring von `api_summary` ehrlich machen**

In `src/api_summary.py` ersetze im Modul-Docstring den Absatz

```python
Gespeicherte Slots sind Fremddaten (der Sync validiert ihren Inhalt nicht): ein
Slot mit ungewöhnlichem Inhalt zählt 0 Minuten und wird geloggt, er macht aus
einer lesenden Route keine 500.
```

durch

```python
Gespeicherte Slots sind Fremddaten. `Storage` bereinigt sie an der Lese-Grenze
(`storage.sanitize_slot`); was `summarize` trotzdem von einem Aufrufer mit eigenem
Snapshot bekommt, zählt als ungewöhnlicher Slot 0 Minuten und wird geloggt. Das ist
die zweite Linie, kein Ersatz für die erste.
```

- [ ] **Step 3: Doku**

In `src/CLAUDE.md` ersetze im `storage.py`-Bullet

```python
unbemerkt mit. `reservations.py` — Reservierungen
  (zukünftige Soll-Zeiten, eigenes Konzept). `settings.py`
```

durch

```python
unbemerkt mit.
  **Beschädigte Dateien** (Handbearbeitung, ein fremdes Sync-Doc): `_load` quarantäniert ein
  Top-Level, das kein Objekt ist, wie unparsebar und startet leer; Einträge ohne Objektform und
  Slot-Listen mit Nicht-Objekten werden nach einer Sicherung (`json_store.backup_corrupt`,
  `<datei>.corrupt-<stamp>`) repariert und zurückgeschrieben — scheitert die Sicherung, wird
  nicht geschrieben. Wertfehler bleiben roh (der Sync soll keine spontane Änderung sehen) und
  werden an der Lese-Grenze bereinigt: `sanitize_slot` in `_user_shape` macht aus jedem Slot
  `start`/`end` Text-oder-`None`, `kategorie` Text, `pause` eine ganze Zahl 0–1440 (sonst 0).
  Alle Leser (UI, Berichte, API) gehen über `get`/`get_all` und sehen nie Fremddaten;
  `get_all_raw` bleibt das Original für den Sync. `sync.validate_remote_doc` lehnt Slot-Listen
  mit Nicht-Objekten ab.
  `reservations.py` — Reservierungen
  (zukünftige Soll-Zeiten, eigenes Konzept). `settings.py`
```

In `src/CLAUDE.md` ersetze im `json_store.py`-Bullet

```python
`<name>.corrupt-<stamp>` verschoben und geloggt wird (**N4**). Genutzt von `storage`,
```

durch

```python
`<name>.corrupt-<stamp>` verschoben und geloggt wird (**N4**); `quarantine_corrupt(path, reason)`
  nimmt einen Grund für die Logzeile, `backup_corrupt(path, reason)` kopiert statt zu verschieben (für
  Dateien, die gleich repariert werden). Genutzt von `storage`,
```

In `CLAUDE.md` (Wurzel) ersetze die Zeile

```python
- `src/storage.py` — JSON-Persistenz der Zeiteinträge (Schlüssel: ISO-Datum)
```

durch

```python
- `src/storage.py` — JSON-Persistenz der Zeiteinträge (Schlüssel: ISO-Datum). Gelesen wird nur bereinigt (`sanitize_slot`), eine beschädigte Datei wird beim Laden mit Sicherung repariert (s. `src/CLAUDE.md`)
```

Hänge an `docs/known-limitations.md` (Dateiende, mit einer Leerzeile Abstand) an:

```markdown
## Beschädigte oder fremde Daten (Storage)

- **Ungültige Slot-Werte werden beim Lesen ersetzt, nicht repariert.** Eine gespeicherte Pause, die keine ganze Zahl von 0 bis 1440 ist (`null`, Text, `30.5`, negativ, `inf`), zählt `0`; `start`/`end` ohne Text zählen als leer, eine Kategorie ohne Text als „ohne Kategorie“. Die Datei behält den Originalwert, bis der Tag neu gespeichert wird.
- **Was beim Laden nicht Objekt-förmig ist, wird verworfen.** Das betrifft nur Einträge und Slots, die kein JSON-Objekt sind (Handbearbeitung, Fremd-Sync). Vorher liegt eine Kopie als `zeiterfassung.json.corrupt-<Zeitstempel>` neben der Datei; scheitert die Kopie, bleibt die Datei unverändert und der reparierte Stand gilt nur bis zum nächsten Speichern.
- **Ein Remote-Doc mit einem Nicht-Objekt in `slots` ist ungültig** und wird wie andere Strukturfehler behandelt (Remote quarantänen, lokaler Stand wird neue Wahrheit).
- **Reservierungen und Urlaub** haben diese Härtung noch nicht (Follow-up über #239).
```

- [ ] **Step 4: Gesamtlauf**

Run: `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/storage.py src/json_store.py src/sync.py src/api_summary.py`
Expected: alle Tests grün (3599), `All checks passed!`, `0 errors`. Fällt `tests/test_claude_md_claims.py`, die Zahl „rund 125“ Catch-all-Handler in `CLAUDE.md` nachziehen (Ruling ins Ledger).

- [ ] **Step 5: Commit**

~~~bash
git add tests/test_api_routes.py src/api_summary.py src/CLAUDE.md CLAUDE.md docs/known-limitations.md
git commit -m "docs(storage): Härtung dokumentiert, API-Regressionstests über echte Dateien (#233)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

## Mutationsprüfung (nach Task 5, vor dem Review)

Jeden Mutanten einzeln anwenden (Datei kopieren, genau eine Ersetzung, Tests laufen lassen, zurückkopieren). Jeder muss mindestens einen Test rot färben:

| Datei | Mutation | Erwartet rot |
|---|---|---|
| `storage.py` | `isinstance(pause, bool) or` entfernen | `test_an_unusable_pause_becomes_zero[True]` |
| `storage.py` | `0 <= pause <= MAX_PAUSE_MINUTES` → `0 <= pause` | `…[10**400]`, `…[MAX_PAUSE_MINUTES + 1]` |
| `storage.py` | `pause.is_integer()`-Zweig entfernen | `test_a_usable_pause_is_kept_as_an_int[30.0]` |
| `storage.py` | `clean = dict(slot)` → `clean = {}` | `test_a_clean_slot_is_unchanged_and_other_keys_survive` |
| `storage.py` | `if not isinstance(slot, dict): return None` → `return {}` | `test_a_non_object_slot_is_dropped` |
| `storage.py` | `isinstance(entry, dict) and` in `get_all` entfernen | `test_get_all_skips_non_object_entries…` |
| `storage.py` | `_user_shape` liefert `entry.get("slots")` ungeprüft | `…skips_non_object_entries_and_drops…` |
| `storage.py` | `if not isinstance(data, dict):`-Block entfernen | `test_a_non_object_top_level_is_quarantined…` |
| `storage.py` | `_heal` ohne `backup_corrupt` | `test_non_object_entries_are_dropped_with_a_backup…` |
| `storage.py` | `_heal` ohne `_save_to_disk()` | `test_a_healed_file_makes_no_second_backup_on_the_next_start` |
| `storage.py` | `except OSError` in `_heal` → `except KeyError` | `test_without_a_backup_nothing_is_written_back`, `test_a_failing_heal_write_does_not_stop_the_start` |
| `storage.py` | `if dropped or repaired:` → `if True:` | `test_a_clean_file_is_neither_backed_up_nor_rewritten` |
| `storage.py` | `_repair_slot_structure` ohne Listenprüfung | `test_broken_slot_lists_are_repaired` |
| `sync.py` | Slot-Elemente-Prüfung entfernen | `test_validate_rejects_a_slot_that_is_not_an_object` |
| `sync.py` | Prüfung auf Werte verschärfen (`pause` muss int sein) | `test_validate_still_accepts_slots_with_unusual_values` |
| `json_store.py` | `shutil.copy2` → `os.replace` | `test_backup_copies_and_keeps_the_original` |

## Finale

Nach Task 5: Review über den ganzen Branch mit einem frischen Reviewer auf dem leistungsfähigsten Modell (Review Focus und Rulings mitgeben, aktiver Angriff mit echten beschädigten Dateien, Sync-Docs und Nebenläufigkeit), Critical/Important in **einem** Fix-Durchlauf (je Fix ein Test, der zuerst rot war), Minors ins Ledger und in Issue #233. Danach `finishing-a-development-branch`: PR gegen `feat/api-analytics` (`Refs #233`, `Refs #92`), in den Stack #236 hängen, in #233 den Punkt „Storage._user_shape robust“ abhaken.
