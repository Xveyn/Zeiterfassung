# Sende-Erinnerung an Reservierungen koppeln — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Erinnerung „Arbeitszeiten verschicken" bekommt tagesbezogene
Auslöser an Reservierungs-Slots, eine konfigurierbare Wochenend-/Feiertags-
Verschiebung des Monatstermins und eine optionale Zeitraum-Vorbelegung im
Sende-Dialog.

**Architecture:** Die Markierung ist ein neues Feld `send_reminder_minutes` am
Reservierungs-Slot in `reservations.json`. Alle Entscheidungen (Verschiebung,
Fälligkeit, Anker-Suche, Slot-Zuordnung) liegen Tk-frei in `src/send_reminder.py`
bzw. als Helfer in `src/dialogs/entry_dialog.py`; die Scheduler- und Dialog-
Schichten sind dünne Nähte darüber.

**Tech Stack:** Python 3.10, Tkinter, pytest, ruff, pyright. Keine neuen
Abhängigkeiten.

**Spec:** `docs/superpowers/specs/2026-08-22-sende-erinnerung-reservierungen-design.md`

## Global Constraints

- **Python 3.10** ist die Untergrenze (CI- und Release-Python). Keine
  `match`-Statements mit Struktur-Patterns aus 3.11+, kein `datetime.UTC`.
- **Keine neuen Abhängigkeiten.** `src/send_reminder.py` und
  `src/reminders.py` bleiben ohne Tk-Import; `holidays_de` wird nur **lazy**
  innerhalb einer Funktion importiert.
- **Shell unter Windows 11 / PowerShell 5.1:** niemals `&&` zum Verketten.
  Sequenziell mit `;`, bedingt mit `if ($?) { ... }`.
- **Sprache:** UI-Texte, Docstrings und Kommentare auf Deutsch, wie im
  restlichen Repo. Code-Bezeichner englisch.
- **Datumsformat:** intern ISO (`YYYY-MM-DD`), in der UI deutsch über
  `src/time_utils.py::format_iso_date` / `format_iso_datetime`.
- **Wertebereich Erinnerungs-Minuten:** `int` in `[0, 120]` oder `None` —
  dieselbe Spanne wie `reminder_minutes_before`.
- **Tests:** `pytest` aus dem Repo-Root muss nach jeder Task grün sein.
  Getestet wird Logik, nicht Tk (siehe `CLAUDE.md`, Abschnitt „Getestet wird
  Logik, nicht UI").
- **Lint/Typecheck:** `ruff check .` und `npx pyright` müssen sauber bleiben.
- **Commits:** nach jeder Task, Conventional-Commit-Präfix, Body via
  `git commit -F <tempfile>` (Heredocs und PowerShell-Here-Strings scheitern
  auf dieser Maschine).

---

## Dateiübersicht

| Datei | Verantwortung | Task |
|---|---|---|
| `src/reservations.py` | Slot-Feld `send_reminder_minutes` normalisieren und in der User-Shape ausliefern | 1 |
| `src/reservations_sync.py` | Marker über `gcal_event_id` durch den Kalender-Merge tragen | 2 |
| `src/share.py` | Feld aus dem Share-Doc projizieren | 3 |
| `src/settings.py` | sechs neue gerätelokale Keys | 4 |
| `src/send_reminder.py` | pure Logik: Verschiebung, Tagesfälligkeit, Anker-Suche, Label-Mapping | 5, 6, 7 |
| `src/send_reminder_scheduler.py` | zweiter Toast-Kanal + Verschiebungs-Parameter | 8 |
| `src/dialogs/settings_dialog/tab_app.py`, `dialog.py` | Bedienung der neuen Settings | 9 |
| `src/dialogs/entry_dialog.py` | Erinnerungs-Block im Tages-Dialog + Tk-freier Zuordnungs-Helfer | 10 |
| `src/dialogs/period_picker.py`, `send_dialog.py`, `src/ui.py` | Zeitraum-Vorbelegung | 11 |
| `CLAUDE.md`, `src/CLAUDE.md` | Doku nachziehen | 12 |

---

### Task 1: Slot-Feld `send_reminder_minutes` im ReservationStore

**Files:**
- Modify: `src/reservations.py` (Modul-Docstring, `_normalize_slot`, `_user_shape`)
- Test: `tests/test_reservations.py`

**Interfaces:**
- Consumes: nichts
- Produces: Reservierungs-Slots tragen `send_reminder_minutes: int | None`,
  sowohl in `get_all_raw()` als auch in `get()` / `get_all()`.
  `_normalize_reminder_minutes(value) -> int | None` normalisiert den Wert.

- [ ] **Step 1: Bestehenden Test-Helfer erweitern**

`tests/test_reservations.py::_ushape` beschreibt die erwartete User-Shape und
bricht sonst in mehreren bestehenden Tests. Beide Helfer anpassen:

```python
def _slot(start, end, kategorie="", gcal_event_id=None, send_reminder_minutes=None):
    """Roh-Slot (inkl. gcal_event_id), wie er in get_all_raw erscheint."""
    return {"start": start, "end": end, "kategorie": kategorie,
            "gcal_event_id": gcal_event_id,
            "send_reminder_minutes": send_reminder_minutes}


def _ushape(*slots):
    """Erwartete User-Shape: slots ohne gcal_event_id."""
    return {"slots": [{"start": s["start"], "end": s["end"],
                       "kategorie": s["kategorie"],
                       "send_reminder_minutes": s.get("send_reminder_minutes")}
                      for s in slots]}
```

- [ ] **Step 2: Failing tests schreiben**

Ans Ende von `tests/test_reservations.py`:

```python
def test_send_reminder_minutes_survives_save_and_get(store):
    store.save("2026-08-31", [
        {"start": "08:00", "end": "12:00", "kategorie": "Office"},
        {"start": "13:00", "end": "17:00", "kategorie": "Kunde",
         "send_reminder_minutes": 15},
    ])
    slots = store.get("2026-08-31")["slots"]
    assert slots[0]["send_reminder_minutes"] is None
    assert slots[1]["send_reminder_minutes"] == 15
    raw = store.get_all_raw()["2026-08-31"]["slots"]
    assert raw[1]["send_reminder_minutes"] == 15


def test_send_reminder_minutes_missing_key_becomes_none(store):
    store.save("2026-08-31", [{"start": "08:00", "end": "12:00"}])
    assert store.get("2026-08-31")["slots"][0]["send_reminder_minutes"] is None


def test_send_reminder_minutes_out_of_range_or_wrong_type_becomes_none(store):
    store.save("2026-08-31", [
        {"start": "08:00", "end": "09:00", "send_reminder_minutes": 121},
        {"start": "09:00", "end": "10:00", "send_reminder_minutes": -1},
        {"start": "10:00", "end": "11:00", "send_reminder_minutes": "15"},
        {"start": "11:00", "end": "12:00", "send_reminder_minutes": True},
    ])
    assert [s["send_reminder_minutes"] for s in store.get("2026-08-31")["slots"]] \
        == [None, None, None, None]


def test_send_reminder_minutes_not_carried_over_positionally(store):
    """Anders als gcal_event_id wird der Marker NICHT vom Vorstand geerbt —
    sonst könnte der Dialog ihn nie löschen."""
    store.save("2026-08-31", [{"start": "08:00", "end": "12:00",
                               "send_reminder_minutes": 15}])
    store.save("2026-08-31", [{"start": "08:00", "end": "12:00"}])
    assert store.get("2026-08-31")["slots"][0]["send_reminder_minutes"] is None
```

- [ ] **Step 3: Tests laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_reservations.py -v`
Expected: die vier neuen Tests FAIL mit `KeyError: 'send_reminder_minutes'`.

- [ ] **Step 4: Implementieren**

In `src/reservations.py` vor `_normalize_slot` einfügen:

```python
def _normalize_reminder_minutes(value: Any) -> int | None:
    """Erinnerungs-Minuten am Reservierungs-Slot: int in [0, 120] oder None.

    Alles andere (bool, String, Ausreißer) wird zu None — dieselbe Toleranz,
    mit der der Store auch sonst korrupte Werte wegnormalisiert, statt beim
    Laden zu werfen.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 120 else None
```

`_normalize_slot` erweitern:

```python
def _normalize_slot(slot: Slot) -> Slot:
    """Vervollständigt einen Reservierungs-Slot auf
    {start, end, kategorie, gcal_event_id, send_reminder_minutes}. Fehlende
    `kategorie` → "", fehlende `gcal_event_id` → None, fehlende/ungültige
    `send_reminder_minutes` → None."""
    return {
        "start": slot.get("start"),
        "end": slot.get("end"),
        "kategorie": slot.get("kategorie", ""),
        "gcal_event_id": slot.get("gcal_event_id"),
        "send_reminder_minutes": _normalize_reminder_minutes(
            slot.get("send_reminder_minutes")),
    }
```

`_user_shape` erweitern:

```python
    @staticmethod
    def _user_shape(entry: Reservation) -> dict[str, Any]:
        """User-Shape: Slots ohne das interne Feld gcal_event_id.

        `send_reminder_minutes` ist dagegen Teil der User-Shape: der
        Tages-Dialog zeigt es an, und der Teil-Lösch-Pfad in ui.py speichert
        die verbleibenden Slots aus genau dieser Shape zurück — fehlte das
        Feld hier, ginge die Markierung beim Löschen eines anderen Slots
        verloren.
        """
        return {"slots": [
            {"start": s.get("start"), "end": s.get("end"),
             "kategorie": s.get("kategorie", ""),
             "send_reminder_minutes": s.get("send_reminder_minutes")}
            for s in entry.get("slots", [])
        ]}
```

Im Modul-Docstring das Schema nachziehen:

```
Schema pro Tag (ISO-Datum als Schlüssel):
    {slots: [{start, end, kategorie, gcal_event_id, send_reminder_minutes}],
     modified_at, deleted}
`gcal_event_id` ist None, bis der Slot erstmals in den Kalender gepusht wurde.
`send_reminder_minutes` ist None oder die Minuten vor Slot-Ende, zu denen an
das Verschicken der Arbeitszeiten erinnert wird — höchstens ein Slot pro Tag
trägt einen Wert.
```

- [ ] **Step 5: Tests laufen lassen**

Run: `pytest tests/test_reservations.py tests/test_reservations_migration.py -v`
Expected: alle PASS.

- [ ] **Step 6: Commit**

```bash
git add src/reservations.py tests/test_reservations.py
git commit -m "feat(reservations): send_reminder_minutes am Slot"
```

---

### Task 2: Marker durch den Kalender-Merge tragen

**Files:**
- Modify: `src/reservations_sync.py:16-31` (`_slot_from_event`, `_adopt_remote`) und die drei Aufrufstellen in `_merge_one_date`
- Test: `tests/test_reservations_sync.py`

**Interfaces:**
- Consumes: Slot-Feld `send_reminder_minutes` aus Task 1
- Produces: `_slot_from_event(ev, reminder_minutes=None)` und
  `_adopt_remote(date, remotes, merged, imported_dates, local=None)`

- [ ] **Step 1: Failing tests schreiben**

Zuerst den Test-Helfer in `tests/test_reservations_sync.py` erweitern:

```python
def _lslot(start="09:00", end="17:00", kategorie="", event_id=None,
           send_reminder_minutes=None):
    return {"start": start, "end": end, "kategorie": kategorie,
            "gcal_event_id": event_id,
            "send_reminder_minutes": send_reminder_minutes}
```

Dann ans Dateiende:

```python
def test_marker_survives_local_wins():
    res = merge_reservations(
        {"2026-06-01": _local(
            slots=[_lslot(event_id="ev1", send_reminder_minutes=15)],
            modified_at="2026-05-21T10:00:00Z")},
        [_remote(event_id="ev1", modified_at="2026-05-20T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["slots"][0]["send_reminder_minutes"] == 15


def test_marker_follows_event_id_when_remote_wins():
    """Google liefert die Events in beliebiger Reihenfolge — der Marker muss
    dem richtigen Slot folgen, nicht der Position."""
    res = merge_reservations(
        {"2026-06-01": _local(
            slots=[_lslot(start="08:00", end="12:00", event_id="ev1"),
                   _lslot(start="13:00", end="17:00", event_id="ev2",
                          send_reminder_minutes=15)],
            modified_at="2026-05-20T10:00:00Z")},
        [_remote(start="13:00", end="17:00", event_id="ev2",
                 modified_at="2026-05-21T10:00:00Z"),
         _remote(start="08:00", end="12:00", event_id="ev1",
                 modified_at="2026-05-21T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    slots = res["merged"]["2026-06-01"]["slots"]
    assert slots[0]["start"] == "13:00" and slots[0]["send_reminder_minutes"] == 15
    assert slots[1]["start"] == "08:00" and slots[1]["send_reminder_minutes"] is None


def test_marker_dropped_when_event_id_has_no_local_partner():
    res = merge_reservations(
        {"2026-06-01": _local(
            slots=[_lslot(event_id="ev1", send_reminder_minutes=15)],
            modified_at="2026-05-20T10:00:00Z")},
        [_remote(event_id="ev-neu", modified_at="2026-05-21T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    slots = res["merged"]["2026-06-01"]["slots"]
    assert slots[0]["send_reminder_minutes"] is None


def test_remote_only_date_has_no_marker():
    res = merge_reservations({}, [_remote(event_id="ev1")], "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["slots"][0]["send_reminder_minutes"] is None
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_reservations_sync.py -v`
Expected: die vier neuen Tests FAIL mit `KeyError: 'send_reminder_minutes'`.

- [ ] **Step 3: Implementieren**

```python
def _slot_from_event(ev, reminder_minutes=None):
    """Reservierungs-Slot aus einem geparsten Kalender-Event.

    `reminder_minutes` kommt aus dem lokalen Slot mit derselben event_id — der
    Kalender kennt das Feld nicht, es würde beim Remote-gewinnt-Merge sonst
    verloren gehen.
    """
    return {
        "start": ev["start"], "end": ev["end"],
        "kategorie": ev.get("kategorie", ""), "gcal_event_id": ev["event_id"],
        "send_reminder_minutes": reminder_minutes,
    }


def _reminders_by_event_id(local):
    """{event_id: send_reminder_minutes} aus den lokalen Slots.

    Zuordnung über die Event-ID und NICHT über die Position: in _adopt_remote
    entsteht die neue Slot-Liste in der Reihenfolge, in der Google die Events
    liefert — die hat mit der lokalen Slot-Reihenfolge nichts zu tun.
    """
    if local is None:
        return {}
    out = {}
    for slot in local.get("slots", []):
        event_id = slot.get("gcal_event_id")
        minutes = slot.get("send_reminder_minutes")
        if event_id and minutes is not None:
            out[event_id] = minutes
    return out


def _adopt_remote(date, remotes, merged, imported_dates, local=None):
    """Remote gewinnt: die Slots des Tages = die Remote-Events. Ein lokal
    gesetzter Erinnerungs-Marker wandert über die event_id mit."""
    reminders = _reminders_by_event_id(local)
    merged[date] = {
        "slots": [_slot_from_event(ev, reminders.get(ev["event_id"]))
                  for ev in remotes],
        "modified_at": max(ev["modified_at"] for ev in remotes),
        "deleted": False,
    }
    imported_dates.add(date)
```

Die drei Aufrufstellen in `_merge_one_date` mit `local` versorgen: Fall 2
bleibt `_adopt_remote(date, remotes, merged, imported_dates)` (dort ist
`local` per Definition None), Fall 3 und Fall 5 bekommen
`_adopt_remote(date, remotes, merged, imported_dates, local)`.

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/test_reservations_sync.py -v`
Expected: alle PASS.

- [ ] **Step 5: Commit**

```bash
git add src/reservations_sync.py tests/test_reservations_sync.py
git commit -m "feat(gcal): Erinnerungs-Marker ueber event_id durch den Merge tragen"
```

---

### Task 3: Feld aus dem Share-Doc projizieren

**Files:**
- Modify: `src/share.py:237-254` (`build_share_doc`)
- Test: `tests/test_share.py`

**Interfaces:**
- Consumes: User-Shape mit `send_reminder_minutes` aus Task 1
- Produces: `_share_reservation_shape(records) -> dict`

**Warum:** `share._check_keys` vergleicht `keys != expected_keys` und wirft bei
unbekannten Feldern. Ohne Projektion erzeugt die App ein Share-Doc, das ihr
eigener Validator ablehnt.

- [ ] **Step 1: Failing test schreiben**

Ans Ende von `tests/test_share.py`:

```python
def test_share_doc_omits_send_reminder_minutes(tmp_path):
    from src.reservations import ReservationStore
    from src.share import build_share_doc, parse_share_doc, serialize_share_doc

    store = ReservationStore(str(tmp_path / "res.json"))
    store.save("2026-08-31", [{"start": "08:00", "end": "12:00",
                               "kategorie": "Office",
                               "send_reminder_minutes": 15}])
    doc = build_share_doc(_FakeStorage({}), "a@b.de", reservation_store=store,
                          include_entries=False, include_reservations=True)
    slot = doc["reservations"]["2026-08-31"]["slots"][0]
    assert set(slot.keys()) == {"start", "end", "kategorie"}
    # Das eigene Doc muss den eigenen, strikten Validator bestehen.
    parse_share_doc(serialize_share_doc(doc))
```

`_FakeStorage` gibt es in dieser Datei ggf. schon; falls nicht, davor
einfügen:

```python
class _FakeStorage:
    def __init__(self, data):
        self._data = data

    def get_all(self):
        return dict(self._data)
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_share.py::test_share_doc_omits_send_reminder_minutes -v`
Expected: FAIL — `slot.keys()` enthält `send_reminder_minutes`.

- [ ] **Step 3: Implementieren**

In `src/share.py` neben `_filter_records_by_category`:

```python
def _share_reservation_shape(records):
    """Projiziert Reservierungs-Records auf die Share-Felder.

    Der ReservationStore liefert in seiner User-Shape auch interne Felder wie
    `send_reminder_minutes` (Erinnerungs-Marker, gerätelokal). Die gehören
    nicht ins Share-Doc: _check_keys ist strikt, ein Empfänger würde die Datei
    mit „unbekannte Felder" ablehnen.
    """
    return {
        date_str: {"slots": [
            {"start": s.get("start"), "end": s.get("end"),
             "kategorie": s.get("kategorie", "")}
            for s in record["slots"]
        ]}
        for date_str, record in records.items()
    }
```

In `build_share_doc` die Reservierungs-Zeile umbauen:

```python
    if include_reservations and reservation_store is not None:
        doc["reservations"] = _share_reservation_shape(
            _filter_records_by_category(
                dict(reservation_store.get_all()), categories))
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/test_share.py tests/test_share_task.py -v`
Expected: alle PASS.

- [ ] **Step 5: Commit**

```bash
git add src/share.py tests/test_share.py
git commit -m "fix(share): internes Erinnerungs-Feld nicht ins Share-Doc schreiben"
```

---

### Task 4: Sechs neue Settings-Keys

**Files:**
- Modify: `src/settings.py:33-79` (`DEFAULTS`)
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: die Keys `send_reminder_reservations_enabled`,
  `send_reminder_default_minutes`, `send_reminder_weekend_shift`,
  `send_reminder_shift_holidays`, `send_period_from_last_reminder`,
  `send_period_anchor_monthly`

- [ ] **Step 1: Failing test schreiben**

Ans Ende von `tests/test_settings.py`:

```python
def test_new_send_reminder_defaults(tmp_path):
    s = Settings(str(tmp_path / "settings.json"))
    assert s.get("send_reminder_reservations_enabled") is False
    assert s.get("send_reminder_default_minutes") == 15
    assert s.get("send_reminder_weekend_shift") == "none"
    assert s.get("send_reminder_shift_holidays") is False
    assert s.get("send_period_from_last_reminder") is False
    assert s.get("send_period_anchor_monthly") is False


def test_new_send_reminder_keys_are_device_local():
    from src.settings import SYNCED_SETTING_KEYS
    for key in ("send_reminder_reservations_enabled",
                "send_reminder_default_minutes",
                "send_reminder_weekend_shift",
                "send_reminder_shift_holidays",
                "send_period_from_last_reminder",
                "send_period_anchor_monthly"):
        assert key not in SYNCED_SETTING_KEYS
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_settings.py::test_new_send_reminder_defaults -v`
Expected: FAIL — `assert None is False`.

- [ ] **Step 3: Implementieren**

In `src/settings.py` direkt nach `"send_reminder_last_fired_month": "",`:

```python
    # Tagesbezogene Sende-Erinnerung (an Reservierungs-Slots gekoppelt) und
    # Verschiebung des Monatstermins. Alle gerätelokal — bewusst NICHT in
    # SYNCED_SETTING_KEYS, wie die übrigen Benachrichtigungs-Keys.
    "send_reminder_reservations_enabled": False,
    "send_reminder_default_minutes": 15,
    # "none" | "backward" (vorziehen) | "forward" (nachziehen).
    "send_reminder_weekend_shift": "none",
    "send_reminder_shift_holidays": False,
    "send_period_from_last_reminder": False,
    "send_period_anchor_monthly": False,
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/test_settings.py -v`
Expected: alle PASS.

- [ ] **Step 5: Commit**

```bash
git add src/settings.py tests/test_settings.py
git commit -m "feat(settings): Keys fuer tagesbezogene Sende-Erinnerung"
```

---

### Task 5: Verschiebung auf arbeitsfreie Tage

**Files:**
- Modify: `src/send_reminder.py` (Docstring, `scheduled_datetime`, `is_due`)
- Test: `tests/test_send_reminder.py`

**Interfaces:**
- Produces:
  - `shift_off_free_days(date, mode, free_dates) -> datetime.date`
  - `free_dates_for_month(year, month, state="", include_holidays=False) -> set[datetime.date]`
  - `scheduled_datetime(year, month, day, time_str, shift_mode="none", free_dates=None) -> datetime.datetime | None`
  - `is_due(now_dt, day, time_str, last_fired_month, shift_mode="none", free_dates=None) -> bool`
  - `SHIFT_LABELS`, `shift_for_label(label) -> str`, `label_for_shift(mode) -> str`

- [ ] **Step 1: Failing tests schreiben**

Ans Ende von `tests/test_send_reminder.py`; oben den Import erweitern auf
`from src.send_reminder import (free_dates_for_month, is_due, label_for_shift,
scheduled_datetime, shift_for_label, shift_off_free_days)`:

```python
def _weekend(year, month):
    """Alle Sa/So des Monats als free_dates-Menge."""
    import calendar
    last = calendar.monthrange(year, month)[1]
    return {datetime.date(year, month, d) for d in range(1, last + 1)
            if datetime.date(year, month, d).weekday() >= 5}


def test_shift_none_leaves_date_untouched():
    d = datetime.date(2026, 10, 31)  # Samstag
    assert shift_off_free_days(d, "none", _weekend(2026, 10)) == d
    assert shift_off_free_days(d, "kaputt", _weekend(2026, 10)) == d


def test_shift_backward_to_previous_workday():
    # Sa 15.08.2026 -> Fr 14.08.
    assert shift_off_free_days(
        datetime.date(2026, 8, 15), "backward", _weekend(2026, 8)
    ) == datetime.date(2026, 8, 14)


def test_shift_forward_to_next_workday():
    # Sa 15.08.2026 -> Mo 17.08.
    assert shift_off_free_days(
        datetime.date(2026, 8, 15), "forward", _weekend(2026, 8)
    ) == datetime.date(2026, 8, 17)


def test_shift_forward_stays_in_month():
    # Sa 31.10.2026 -> vorwaerts waere Mo 02.11. -> stattdessen Fr 30.10.
    assert shift_off_free_days(
        datetime.date(2026, 10, 31), "forward", _weekend(2026, 10)
    ) == datetime.date(2026, 10, 30)


def test_shift_backward_stays_in_month():
    # So 01.02.2026 -> rueckwaerts waere Fr 30.01. -> stattdessen Mo 02.02.
    assert shift_off_free_days(
        datetime.date(2026, 2, 1), "backward", _weekend(2026, 2)
    ) == datetime.date(2026, 2, 2)


def test_shift_all_days_free_returns_input():
    import calendar
    last = calendar.monthrange(2026, 2)[1]
    every_day = {datetime.date(2026, 2, d) for d in range(1, last + 1)}
    assert shift_off_free_days(
        datetime.date(2026, 2, 10), "backward", every_day
    ) == datetime.date(2026, 2, 10)


def test_shift_backward_from_first_workday_of_month_falls_forward():
    # Fr 01.05.2026 ist "Erster Mai": rueckwaerts landet man auf Do 30.04. und
    # damit im Vormonat -> stattdessen vorwaerts auf Mo 04.05.
    free = _weekend(2026, 5) | {datetime.date(2026, 5, 1)}
    assert shift_off_free_days(
        datetime.date(2026, 5, 1), "backward", free
    ) == datetime.date(2026, 5, 4)


def test_scheduled_datetime_applies_shift_after_clamp():
    # Tag 31 im Oktober -> Sa 31.10. -> backward -> Fr 30.10. um 18:00
    assert scheduled_datetime(
        2026, 10, 31, "18:00", "backward", _weekend(2026, 10)
    ) == datetime.datetime(2026, 10, 30, 18, 0)


def test_is_due_uses_shifted_date():
    free = _weekend(2026, 10)
    # Am Fr 30.10. 18:00 ist der auf diesen Tag vorgezogene Termin faellig.
    assert is_due(datetime.datetime(2026, 10, 30, 18, 0), 31, "18:00", "",
                  "backward", free) is True
    # Ohne Verschiebung noch nicht.
    assert is_due(datetime.datetime(2026, 10, 30, 18, 0), 31, "18:00", "") is False


def test_free_dates_for_month_weekend_only():
    free = free_dates_for_month(2026, 8)
    assert datetime.date(2026, 8, 15) in free   # Samstag
    assert datetime.date(2026, 8, 16) in free   # Sonntag
    assert datetime.date(2026, 8, 17) not in free


def test_free_dates_for_month_with_holidays():
    # Fr 01.05.2026 "Erster Mai" — ein Werktag, also nur ueber die Feiertage frei.
    assert datetime.date(2026, 5, 1) not in free_dates_for_month(2026, 5)
    assert datetime.date(2026, 5, 1) in free_dates_for_month(
        2026, 5, "BY", include_holidays=True)


def test_free_dates_for_month_without_state_is_weekend_only():
    free = free_dates_for_month(2026, 5, "", include_holidays=True)
    assert datetime.date(2026, 5, 1) not in free
    assert datetime.date(2026, 5, 2) in free    # Samstag


def test_shift_label_roundtrip():
    for mode in ("none", "backward", "forward"):
        assert shift_for_label(label_for_shift(mode)) == mode
    assert shift_for_label("Unsinn") == "none"
    assert label_for_shift("Unsinn") == label_for_shift("none")
```

Den Platzhalter-Test `test_shift_respects_holidays_in_free_dates` **nicht**
übernehmen — er ist durch
`test_shift_backward_from_first_workday_of_month_falls_forward` abgedeckt und
enthält ein irreführendes `or True`. Beim Schreiben der Datei weglassen.

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_send_reminder.py -v`
Expected: FAIL beim Import — `cannot import name 'shift_off_free_days'`.

- [ ] **Step 3: Implementieren**

In `src/send_reminder.py`, nach `_parse_hhmm`:

```python
SHIFT_LABELS = {
    "none": "nicht verschieben",
    "backward": "vorziehen (davor)",
    "forward": "nachziehen (danach)",
}


def label_for_shift(mode):
    """Enum-Wert → Klartext fürs Dropdown. Unbekannt → Label von 'none'."""
    return SHIFT_LABELS.get(mode, SHIFT_LABELS["none"])


def shift_for_label(label):
    """Klartext aus dem Dropdown → Enum-Wert. Unbekannt → 'none'."""
    for mode, text in SHIFT_LABELS.items():
        if text == label:
            return mode
    return "none"


def shift_off_free_days(date, mode, free_dates):
    """Verschiebt `date` weg von arbeitsfreien Tagen, ohne den Monat zu
    verlassen.

    mode "backward": rückwärts zum ersten nicht-freien Tag.
    mode "forward":  vorwärts zum ersten nicht-freien Tag.
    Verlässt die Suche den Monat, wird in der Gegenrichtung gesucht. Das gilt
    bewusst für BEIDE Richtungen: is_due berechnet den Fälligkeitszeitpunkt
    immer für den laufenden Monat, ein in den Nachbarmonat gerutschter Termin
    wäre dort nie erreichbar und würde erst am Monatsersten nachfeuern.
    Anderer/unbekannter Modus oder kein Arbeitstag im ganzen Monat: unverändert.
    """
    if mode not in ("backward", "forward"):
        return date
    first = date.replace(day=1)
    last = date.replace(day=calendar.monthrange(date.year, date.month)[1])
    primary = -1 if mode == "backward" else 1
    for step in (primary, -primary):
        current = date
        while first <= current <= last:
            if current not in free_dates:
                return current
            current += datetime.timedelta(days=step)
    return date


def free_dates_for_month(year, month, state="", include_holidays=False):
    """Arbeitsfreie Tage des Monats: immer Sa/So, optional die Feiertage des
    Bundeslands.

    holidays_de wird lazy importiert, damit dieses Modul ohne die
    holidays-Lib importierbar bleibt. get_holidays ist intern gecached und
    liefert bei leerem/ungültigem Bundesland {} — der Minuten-Poll darf es
    also direkt aufrufen.
    """
    last_day = calendar.monthrange(year, month)[1]
    days = [datetime.date(year, month, d) for d in range(1, last_day + 1)]
    free = {d for d in days if d.weekday() >= 5}
    if include_holidays and state:
        from src.holidays_de import get_holidays
        feiertage = get_holidays(state, year)
        free |= {d for d in days if d in feiertage}
    return free
```

`scheduled_datetime` und `is_due` bekommen die Parameter:

```python
def scheduled_datetime(year, month, day, time_str,
                       shift_mode="none", free_dates=None):
    """Fällig-Zeitpunkt für (year, month); `day` wird auf die tatsächliche
    Monatslänge geclamped (Tag 31 im Februar -> 28./29., im April -> 30.).
    Danach wird optional von arbeitsfreien Tagen weg verschoben
    (shift_off_free_days). `time_str` ungültig/kein 'HH:MM' -> None."""
    hh_mm = _parse_hhmm(time_str)
    if hh_mm is None:
        return None
    last_day = calendar.monthrange(year, month)[1]
    actual_day = min(max(day, 1), last_day)
    target = shift_off_free_days(
        datetime.date(year, month, actual_day), shift_mode,
        free_dates if free_dates is not None else frozenset())
    hh, mm = hh_mm
    return datetime.datetime(target.year, target.month, target.day, hh, mm)


def is_due(now_dt, day, time_str, last_fired_month,
           shift_mode="none", free_dates=None):
    """True, wenn `now_dt` den Fällig-Zeitpunkt des aktuellen Monats erreicht
    hat und dieser Monat (`'YYYY-MM'`) noch nicht in `last_fired_month`
    steht. shift_mode/free_dates werden an scheduled_datetime durchgereicht."""
    current_month = f"{now_dt.year:04d}-{now_dt.month:02d}"
    if last_fired_month == current_month:
        return False
    due_at = scheduled_datetime(
        now_dt.year, now_dt.month, day, time_str, shift_mode, free_dates)
    if due_at is None:
        return False
    return now_dt >= due_at
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/test_send_reminder.py -v`
Expected: alle PASS.

- [ ] **Step 5: Commit**

```bash
git add src/send_reminder.py tests/test_send_reminder.py
git commit -m "feat(send-reminder): Monatstermin von arbeitsfreien Tagen wegschieben"
```

---

### Task 6: Fälligkeit der tagesbezogenen Erinnerung

**Files:**
- Modify: `src/send_reminder.py`
- Test: `tests/test_send_reminder.py`

**Interfaces:**
- Consumes: Slot-Feld aus Task 1
- Produces: `DayReminder = namedtuple("DayReminder", ["end", "minutes"])` und
  `due_day_reminder(reserved_slots, now_dt) -> DayReminder | None`

- [ ] **Step 1: Failing tests schreiben**

Import in `tests/test_send_reminder.py` um `due_day_reminder` erweitern, dann:

```python
def _res(end, minutes, start="08:00"):
    return {"start": start, "end": end, "kategorie": "",
            "send_reminder_minutes": minutes}


def test_due_day_reminder_fires_n_minutes_before_end():
    slots = [_res("17:00", 15)]
    assert due_day_reminder(slots, datetime.datetime(2026, 8, 31, 16, 44)) is None
    rem = due_day_reminder(slots, datetime.datetime(2026, 8, 31, 16, 45))
    assert rem is not None and rem.end == "17:00" and rem.minutes == 15


def test_due_day_reminder_is_caught_up_after_end():
    """App startet erst um 18:00 — der Toast von 16:45 wird nachgeholt."""
    rem = due_day_reminder([_res("17:00", 15)],
                           datetime.datetime(2026, 8, 31, 18, 0))
    assert rem is not None


def test_due_day_reminder_zero_minutes_fires_at_end():
    slots = [_res("17:00", 0)]
    assert due_day_reminder(slots, datetime.datetime(2026, 8, 31, 16, 59)) is None
    assert due_day_reminder(slots, datetime.datetime(2026, 8, 31, 17, 0)) is not None


def test_due_day_reminder_without_marker_returns_none():
    assert due_day_reminder([_res("17:00", None)],
                            datetime.datetime(2026, 8, 31, 18, 0)) is None
    assert due_day_reminder([], datetime.datetime(2026, 8, 31, 18, 0)) is None


def test_due_day_reminder_picks_the_marked_slot():
    slots = [_res("12:00", None, start="08:00"), _res("17:00", 30, start="13:00")]
    rem = due_day_reminder(slots, datetime.datetime(2026, 8, 31, 16, 30))
    assert rem is not None and rem.end == "17:00" and rem.minutes == 30


def test_due_day_reminder_ignores_broken_values():
    assert due_day_reminder([{"start": "08:00", "end": "kaputt",
                              "send_reminder_minutes": 15}],
                            datetime.datetime(2026, 8, 31, 23, 0)) is None
    assert due_day_reminder([{"start": "08:00", "end": "17:00",
                              "send_reminder_minutes": 999}],
                            datetime.datetime(2026, 8, 31, 23, 0)) is None
    assert due_day_reminder([{"start": "08:00", "end": "17:00",
                              "send_reminder_minutes": True}],
                            datetime.datetime(2026, 8, 31, 23, 0)) is None
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_send_reminder.py -v`
Expected: FAIL beim Import — `cannot import name 'due_day_reminder'`.

- [ ] **Step 3: Implementieren**

In `src/send_reminder.py` oben `from collections import namedtuple` ergänzen
und ans Modulende:

```python
DayReminder = namedtuple("DayReminder", ["end", "minutes"])


def _parse_hhmm_on(date, value):
    """'HH:MM' + date -> datetime; None/ungültig -> None."""
    hh_mm = _parse_hhmm(value)
    if hh_mm is None:
        return None
    hh, mm = hh_mm
    return datetime.datetime(date.year, date.month, date.day, hh, mm)


def due_day_reminder(reserved_slots, now_dt):
    """Der fällige tagesbezogene Sende-Reminder für die heutigen
    Reservierungs-Slots, oder None.

    Sucht den ersten Slot mit gültigem `send_reminder_minutes` (Invariante:
    höchstens einer pro Tag) und liefert ihn ab `now_dt >= end - minutes`.
    Kein oberes Fenster: startet die App erst nach dem Zeitpunkt, wird der
    Toast am selben Tag nachgeholt — ab dem Folgetag nicht mehr, weil der
    Aufrufer nur die Slots von heute übergibt.

    Ungültige Werte (kein parsebares Ende, Minuten außerhalb [0, 120] oder
    kein echtes int) werden übersprungen, wie in reminders.due_reminders.
    """
    date = now_dt.date()
    for slot in reserved_slots:
        minutes = slot.get("send_reminder_minutes")
        if isinstance(minutes, bool) or not isinstance(minutes, int):
            continue
        if not 0 <= minutes <= 120:
            continue
        end = _parse_hhmm_on(date, slot.get("end"))
        if end is None:
            continue
        if now_dt >= end - datetime.timedelta(minutes=minutes):
            return DayReminder(slot.get("end"), minutes)
        return None
    return None
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/test_send_reminder.py -v`
Expected: alle PASS.

- [ ] **Step 5: Commit**

```bash
git add src/send_reminder.py tests/test_send_reminder.py
git commit -m "feat(send-reminder): Faelligkeit der tagesbezogenen Erinnerung"
```

---

### Task 7: Anker-Suche für die Zeitraum-Vorbelegung

**Files:**
- Modify: `src/send_reminder.py`
- Test: `tests/test_send_reminder.py`

**Interfaces:**
- Consumes: `scheduled_datetime`, `free_dates_for_month` aus Task 5
- Produces:
  - `marked_reminder_dates(raw_reservations) -> list[datetime.date]`
  - `monthly_anchor_dates(today, day, time_str, shift_mode="none", state="", include_holidays=False, months_back=2) -> list[datetime.date]`
  - `previous_anchor_date(today, marked_dates, monthly_dates) -> datetime.date | None`
  - `default_send_period(today, marked_dates, monthly_dates) -> tuple[datetime.date, datetime.date] | None`

- [ ] **Step 1: Failing tests schreiben**

Import erweitern, dann ans Dateiende:

```python
def test_marked_reminder_dates_collects_days_with_marker():
    from src.send_reminder import marked_reminder_dates
    raw = {
        "2026-08-02": {"slots": [{"send_reminder_minutes": 15}],
                       "modified_at": "x", "deleted": False},
        "2026-08-10": {"slots": [{"send_reminder_minutes": None}],
                       "modified_at": "x", "deleted": False},
        "2026-09-05": {"slots": [{"send_reminder_minutes": None},
                                 {"send_reminder_minutes": 30}],
                       "modified_at": "x", "deleted": False},
        "2026-09-20": {"slots": [{"send_reminder_minutes": 15}],
                       "modified_at": "x", "deleted": True},
    }
    assert sorted(marked_reminder_dates(raw)) == [
        datetime.date(2026, 8, 2), datetime.date(2026, 9, 5)]


def test_marked_reminder_dates_ignores_broken_date_keys():
    from src.send_reminder import marked_reminder_dates
    raw = {"kein-datum": {"slots": [{"send_reminder_minutes": 15}],
                          "modified_at": "x", "deleted": False}}
    assert marked_reminder_dates(raw) == []


def test_monthly_anchor_dates_covers_three_months():
    from src.send_reminder import monthly_anchor_dates
    dates = monthly_anchor_dates(datetime.date(2026, 9, 5), 23, "16:30")
    assert dates == [datetime.date(2026, 9, 23), datetime.date(2026, 8, 23),
                     datetime.date(2026, 7, 23)]


def test_monthly_anchor_dates_crosses_year_boundary():
    from src.send_reminder import monthly_anchor_dates
    dates = monthly_anchor_dates(datetime.date(2026, 1, 10), 15, "16:30")
    assert dates == [datetime.date(2026, 1, 15), datetime.date(2025, 12, 15),
                     datetime.date(2025, 11, 15)]


def test_previous_anchor_date_marked_only():
    from src.send_reminder import previous_anchor_date
    assert previous_anchor_date(
        datetime.date(2026, 9, 5),
        [datetime.date(2026, 8, 2), datetime.date(2026, 9, 5)],
        [],
    ) == datetime.date(2026, 8, 2)


def test_previous_anchor_date_prefers_the_nearest():
    from src.send_reminder import previous_anchor_date
    assert previous_anchor_date(
        datetime.date(2026, 9, 5),
        [datetime.date(2026, 8, 2)],
        [datetime.date(2026, 8, 23), datetime.date(2026, 9, 23)],
    ) == datetime.date(2026, 8, 23)


def test_previous_anchor_date_none_when_no_past_anchor():
    from src.send_reminder import previous_anchor_date
    assert previous_anchor_date(datetime.date(2026, 9, 5),
                                [datetime.date(2026, 9, 5)], []) is None
    assert previous_anchor_date(datetime.date(2026, 9, 5), [], []) is None


def test_default_send_period_starts_day_after_anchor():
    from src.send_reminder import default_send_period
    assert default_send_period(
        datetime.date(2026, 9, 5), [datetime.date(2026, 8, 2)], []
    ) == (datetime.date(2026, 8, 3), datetime.date(2026, 9, 5))


def test_default_send_period_none_without_anchor():
    from src.send_reminder import default_send_period
    assert default_send_period(datetime.date(2026, 9, 5), [], []) is None
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_send_reminder.py -v`
Expected: FAIL — `ImportError: cannot import name 'marked_reminder_dates'`.

- [ ] **Step 3: Implementieren**

Ans Ende von `src/send_reminder.py`:

```python
def marked_reminder_dates(raw_reservations):
    """Die Tage mit gesetztem Erinnerungs-Marker, aus get_all_raw().

    Tombstones (`deleted`) zählen nicht, kaputte Datums-Keys werden
    übersprungen (der Store normalisiert Keys nicht).
    """
    out = []
    for date_str, entry in raw_reservations.items():
        if entry.get("deleted"):
            continue
        if not any(s.get("send_reminder_minutes") is not None
                   for s in entry.get("slots", [])):
            continue
        try:
            out.append(datetime.date.fromisoformat(date_str))
        except (ValueError, TypeError):
            continue
    return out


def monthly_anchor_dates(today, day, time_str, shift_mode="none", state="",
                         include_holidays=False, months_back=2):
    """Die Monatstermine des laufenden und der `months_back` vorangehenden
    Monate — inklusive Monatslängen-Clamp und Verschiebung.

    Zwei Vormonate reichen für die Anker-Suche, weil ein näherer Anker jeden
    älteren verdrängt.
    """
    out = []
    year, month = today.year, today.month
    for _ in range(months_back + 1):
        free = free_dates_for_month(year, month, state, include_holidays)
        due_at = scheduled_datetime(year, month, day, time_str, shift_mode, free)
        if due_at is not None:
            out.append(due_at.date())
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return out


def previous_anchor_date(today, marked_dates, monthly_dates):
    """Der jüngste Erinnerungs-Ankerpunkt echt VOR `today`, oder None.

    `today` selbst zählt nicht: der Zeitraum soll bis heute reichen, nicht
    bei heute beginnen.
    """
    candidates = [d for d in (*marked_dates, *monthly_dates) if d < today]
    return max(candidates) if candidates else None


def default_send_period(today, marked_dates, monthly_dates):
    """(von, bis) für den Sende-Dialog: Tag NACH dem vorherigen Anker bis
    heute (einschließlich). Kein Anker → None, der Aufrufer bleibt dann beim
    bisherigen Default."""
    anchor = previous_anchor_date(today, marked_dates, monthly_dates)
    if anchor is None:
        return None
    return anchor + datetime.timedelta(days=1), today
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/test_send_reminder.py -v`
Expected: alle PASS.

- [ ] **Step 5: Commit**

```bash
git add src/send_reminder.py tests/test_send_reminder.py
git commit -m "feat(send-reminder): Anker-Suche fuer die Zeitraum-Vorbelegung"
```

---

### Task 8: Scheduler — zweiter Kanal und Verschiebung

**Files:**
- Modify: `src/send_reminder_scheduler.py` (komplett), `src/ui.py:124-127`
- Test: `tests/test_send_reminder_scheduler.py`

**Interfaces:**
- Consumes: `is_due`, `free_dates_for_month`, `due_day_reminder` aus Task 5/6
- Produces: `SendReminderScheduler(root, settings, get_tray,
  reservation_store=None, now_provider=datetime.datetime.now)`;
  `poll(now_dt) -> bool`

- [ ] **Step 1: Test-Fake reparieren und failing tests schreiben**

`_FakeSettings.get` wirft heute `KeyError` bei unbekannten Keys — der neue
Poll fragt mehr Keys ab. Fake und Factory in
`tests/test_send_reminder_scheduler.py` umbauen:

```python
_DEFAULTS = {
    "send_reminder_day": 15, "send_reminder_time": "18:00",
    "send_reminder_last_fired_month": "",
    "send_reminder_weekend_shift": "none",
    "send_reminder_shift_holidays": False,
    "send_reminder_reservations_enabled": False,
    "gcal_enabled": False,
    "state": "",
}


class _FakeSettings:
    def __init__(self, data):
        # Fehlende Keys in das ÜBERGEBENE Dict fuellen, nicht in eine Kopie:
        # die bestehenden Tests pruefen send_reminder_last_fired_month direkt
        # an ihrem settings_data.
        for key, value in _DEFAULTS.items():
            data.setdefault(key, value)
        self._data = data

    def get(self, key):
        return self._data[key]

    def set(self, key, value):
        self._data[key] = value


class _FakeReservationStore:
    def __init__(self, data=None):
        self._data = data or {}

    def get(self, date_str):
        return self._data.get(date_str)


def _make(settings_data, tray, reservation_store=None):
    return SendReminderScheduler(
        root=None,
        settings=_FakeSettings(settings_data),
        get_tray=lambda: tray,
        reservation_store=reservation_store,
    )
```

Weil `_FakeSettings` die Defaults in das **übergebene** Dict schreibt statt in
eine Kopie, bleiben alle bestehenden Assertions der Form
`settings_data["send_reminder_last_fired_month"] == "2026-07"` gültig — an den
bestehenden Tests ist nichts zu ändern.

Neue Tests ans Dateiende:

```python
def _res_store(date_str, end, minutes):
    return _FakeReservationStore({
        date_str: {"slots": [{"start": "08:00", "end": end, "kategorie": "",
                              "send_reminder_minutes": minutes}]}})


def test_day_reminder_fires_before_reservation_end():
    tray = _FakeTray()
    sched = _make(
        {"send_reminder_reservations_enabled": True, "gcal_enabled": True,
         "send_reminder_last_fired_month": "2026-07"},
        tray, _res_store("2026-07-15", "17:00", 15))
    assert sched.poll(_now(15, 16, 44)) is False
    assert sched.poll(_now(15, 16, 45)) is True
    assert "17:00" in tray.messages[0] and "verschicken" in tray.messages[0]


def test_day_reminder_fires_only_once_per_day():
    tray = _FakeTray()
    sched = _make(
        {"send_reminder_reservations_enabled": True, "gcal_enabled": True,
         "send_reminder_last_fired_month": "2026-07"},
        tray, _res_store("2026-07-15", "17:00", 15))
    sched.poll(_now(15, 16, 45))
    assert sched.poll(_now(15, 16, 46)) is False
    assert len(tray.messages) == 1


def test_day_reminder_resets_on_new_day():
    tray = _FakeTray()
    store = _FakeReservationStore({
        "2026-07-15": {"slots": [{"start": "08:00", "end": "17:00",
                                  "kategorie": "", "send_reminder_minutes": 15}]},
        "2026-07-16": {"slots": [{"start": "08:00", "end": "17:00",
                                  "kategorie": "", "send_reminder_minutes": 15}]},
    })
    sched = _make(
        {"send_reminder_reservations_enabled": True, "gcal_enabled": True,
         "send_reminder_last_fired_month": "2026-07"}, tray, store)
    sched.poll(_now(15, 16, 45))
    assert sched.poll(_now(16, 16, 45)) is True
    assert len(tray.messages) == 2


def test_day_reminder_needs_both_switches():
    tray = _FakeTray()
    store = _res_store("2026-07-15", "17:00", 15)
    off = _make({"send_reminder_reservations_enabled": False,
                 "gcal_enabled": True,
                 "send_reminder_last_fired_month": "2026-07"}, tray, store)
    assert off.poll(_now(15, 16, 45)) is False
    no_gcal = _make({"send_reminder_reservations_enabled": True,
                     "gcal_enabled": False,
                     "send_reminder_last_fired_month": "2026-07"}, tray, store)
    assert no_gcal.poll(_now(15, 16, 45)) is False
    assert tray.messages == []


def test_day_reminder_without_store_is_noop():
    tray = _FakeTray()
    sched = _make({"send_reminder_reservations_enabled": True,
                   "gcal_enabled": True,
                   "send_reminder_last_fired_month": "2026-07"}, tray)
    assert sched.poll(_now(15, 16, 45)) is False


def test_both_channels_can_fire_on_the_same_day():
    tray = _FakeTray()
    sched = _make(
        {"send_reminder_day": 15, "send_reminder_time": "16:00",
         "send_reminder_reservations_enabled": True, "gcal_enabled": True},
        tray, _res_store("2026-07-15", "17:00", 15))
    assert sched.poll(_now(15, 16, 45)) is True
    assert len(tray.messages) == 2


def test_monthly_channel_uses_weekend_shift():
    # 15.08.2026 ist ein Samstag; vorziehen -> Fr 14.08.
    tray = _FakeTray()
    sched = _make({"send_reminder_day": 15, "send_reminder_time": "18:00",
                   "send_reminder_weekend_shift": "backward"}, tray)
    assert sched.poll(datetime.datetime(2026, 8, 14, 18, 0)) is True
    assert "August" in tray.messages[0]
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_send_reminder_scheduler.py -v`
Expected: die neuen Tests FAIL (`TypeError: unexpected keyword argument
'reservation_store'`).

- [ ] **Step 3: Implementieren**

`src/send_reminder_scheduler.py` — Konstruktor, `poll` und die Toast-Texte:

```python
class SendReminderScheduler:
    def __init__(self, root, settings, get_tray, reservation_store=None,
                 now_provider=datetime.datetime.now):
        self._root = root
        self._settings = settings
        self._get_tray = get_tray
        self._reservation_store = reservation_store
        self._now = now_provider
        self._after_id = None
        # Tagesbezogener Kanal: Dedup nur im Speicher, tageweise
        # zurückgesetzt (Muster von ReminderScheduler). Ein persistierter
        # Marker müsste in reservations.json landen und würde dort
        # modified_at anfassen — das löst einen gcal-Push aus.
        self._day_fired = False
        self._day_fired_date = None
```

`poll` in zwei Zweige teilen:

```python
    def poll(self, now_dt):
        """Ein Durchlauf über beide Kanäle: monatlicher Termin und
        tagesbezogene Erinnerung. Gibt True zurück, wenn mindestens einer
        benachrichtigt hat (für Tests). Ohne Tray: no-op."""
        tray = self._get_tray()
        if tray is None:
            return False
        fired_monthly = self._poll_monthly(now_dt, tray)
        fired_day = self._poll_day(now_dt, tray)
        return fired_monthly or fired_day

    def _poll_monthly(self, now_dt, tray):
        day = self._settings.get("send_reminder_day")
        time_str = self._settings.get("send_reminder_time")
        last_fired = self._settings.get("send_reminder_last_fired_month")
        shift_mode = self._settings.get("send_reminder_weekend_shift")
        free_dates = (
            send_reminder.free_dates_for_month(
                now_dt.year, now_dt.month, self._settings.get("state"),
                bool(self._settings.get("send_reminder_shift_holidays")))
            if shift_mode in ("backward", "forward") else frozenset()
        )
        if not send_reminder.is_due(now_dt, day, time_str, last_fired,
                                    shift_mode, free_dates):
            return False
        tray.notify(_toast_text(now_dt))
        self._settings.set(
            "send_reminder_last_fired_month",
            f"{now_dt.year:04d}-{now_dt.month:02d}",
        )
        return True

    def _poll_day(self, now_dt, tray):
        """Tagesbezogener Kanal. Verlangt zusätzlich zum Haupt-Schalter die
        Option „Reservierungen" UND einen aktiven Kalender-Abgleich: ohne
        gcal_enabled zeigt die App gar keine Reservierungen an
        (App._reservations_active), ein Toast dafür wäre nicht nachvollziehbar."""
        if self._reservation_store is None:
            return False
        if not (self._settings.get("send_reminder_reservations_enabled")
                and self._settings.get("gcal_enabled")):
            return False
        today = now_dt.date().isoformat()
        if self._day_fired_date != today:
            self._day_fired = False
            self._day_fired_date = today
        if self._day_fired:
            return False
        reservation = self._reservation_store.get(today)
        slots = reservation.get("slots", []) if reservation else []
        rem = send_reminder.due_day_reminder(slots, now_dt)
        if rem is None:
            return False
        tray.notify(_day_toast_text(rem))
        self._day_fired = True
        return True
```

Toast-Text ergänzen:

```python
def _day_toast_text(rem):
    """Deutscher Toast-Text für die tagesbezogene Erinnerung."""
    return (f"Reservierung endet um {rem.end} — Zeit, deine Arbeitszeiten "
            "zu verschicken.")
```

Modul-Docstring auf beide Kanäle erweitern.

In `src/ui.py` den Store durchreichen:

```python
        self._send_reminders = SendReminderScheduler(
            self.root, self.settings, lambda: self._tray,
            reservation_store=self.reservation_store,
        )
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/test_send_reminder_scheduler.py -v`
Expected: alle PASS.

- [ ] **Step 5: Commit**

```bash
git add src/send_reminder_scheduler.py src/ui.py tests/test_send_reminder_scheduler.py
git commit -m "feat(send-reminder): tagesbezogener Toast-Kanal im Scheduler"
```

---

### Task 9: Einstellungen im App-Tab

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_app.py:165-210`, `src/dialogs/settings_dialog/dialog.py:180-186`
- Test: `tests/test_settings_dialog.py`

**Interfaces:**
- Consumes: Settings-Keys aus Task 4, `SHIFT_LABELS`/`shift_for_label`/
  `label_for_shift` aus Task 5
- Produces: `AppTab` exponiert `send_reminder_shift_var`,
  `send_reminder_shift_holidays_var`, `send_reminder_reservations_var`,
  `send_reminder_default_minutes_var`, `send_period_from_last_var`,
  `send_period_anchor_monthly_var`

- [ ] **Step 1: Failing test schreiben**

Der Tab-Aufbau selbst ist Tk und wird nicht getestet; getestet wird die
Label-Zuordnung, die der Tab benutzt. Ans Ende von
`tests/test_settings_dialog.py`:

```python
def test_shift_labels_are_distinct_and_mapped():
    from src.send_reminder import SHIFT_LABELS, label_for_shift, shift_for_label

    assert set(SHIFT_LABELS) == {"none", "backward", "forward"}
    assert len(set(SHIFT_LABELS.values())) == 3
    for mode in SHIFT_LABELS:
        assert shift_for_label(label_for_shift(mode)) == mode
```

- [ ] **Step 2: Test laufen lassen**

Run: `pytest tests/test_settings_dialog.py -v`
Expected: PASS (die Mapping-Funktionen kamen in Task 5) — der Test sichert die
Kopplung zwischen Tab und Enum gegen späteres Umbenennen ab.

- [ ] **Step 3: Widgets ergänzen**

In `src/dialogs/settings_dialog/tab_app.py` den Import erweitern:

```python
from src.send_reminder import SHIFT_LABELS, label_for_shift
```

Nach der bestehenden Hinweiszeile „Bei kürzeren Monaten wird auf den letzten
Tag verschoben." einfügen:

```python
        shift_row = tk.Frame(app_frame, bg=BG)
        shift_row.pack(anchor="w", pady=(4, 0))
        tk.Label(
            shift_row, text="Fällt der Tag aufs Wochenende:",
            font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT, padx=(0, 8))
        send_reminder_shift_var = tk.StringVar(
            value=label_for_shift(settings.get("send_reminder_weekend_shift")))
        dark_combo(
            shift_row, send_reminder_shift_var,
            [SHIFT_LABELS[m] for m in ("none", "backward", "forward")],
            width=20,
        ).pack(side=tk.LEFT, padx=(0, 8))
        send_reminder_shift_holidays_var = tk.BooleanVar(
            value=settings.get("send_reminder_shift_holidays"))
        tk.Checkbutton(
            shift_row, text="Feiertage mitzählen",
            variable=send_reminder_shift_holidays_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).pack(side=tk.LEFT)

        # --- Tagesbezogene Erinnerung an Reservierungen ---
        res_row = tk.Frame(app_frame, bg=BG)
        res_row.pack(anchor="w", pady=(6, 0))
        send_reminder_reservations_var = tk.BooleanVar(
            value=settings.get("send_reminder_reservations_enabled"))
        tk.Checkbutton(
            res_row, text="Reservierungen",
            variable=send_reminder_reservations_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(
            res_row, text="Standard:", font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT, padx=(0, 8))
        send_reminder_default_minutes_var = tk.StringVar(
            value=str(settings.get("send_reminder_default_minutes")))
        dark_combo(
            res_row, send_reminder_default_minutes_var,
            [str(m) for m in range(0, 121, 5)], width=4,
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(
            res_row, text="Minuten vor Ende", font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT)
        tk.Label(
            app_frame,
            text="Erinnerungs-Tage werden im Tages-Dialog gesetzt.",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", padx=(24, 0), pady=(2, 0))
        if not settings.get("gcal_enabled"):
            # Ohne Kalender-Abgleich zeigt die App gar keine Reservierungen
            # (App._reservations_active) — der Schalter bliebe sonst wirkungslos,
            # ohne dass man sieht warum.
            tk.Label(
                app_frame,
                text="Erfordert den aktiven Google-Kalender-Abgleich (Tab Google).",
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
            ).pack(anchor="w", padx=(24, 0))

        send_period_from_last_var = tk.BooleanVar(
            value=settings.get("send_period_from_last_reminder"))
        tk.Checkbutton(
            app_frame, text="Zeitraum ab der letzten Erinnerung vorbelegen",
            variable=send_period_from_last_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).pack(anchor="w", pady=(6, 0))
        send_period_anchor_monthly_var = tk.BooleanVar(
            value=settings.get("send_period_anchor_monthly"))
        tk.Checkbutton(
            app_frame, text="Monatstermine als Anker mitzählen",
            variable=send_period_anchor_monthly_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).pack(anchor="w", padx=(24, 0))
```

Am Ende von `__init__` die sechs Variablen exponieren:

```python
        self.send_reminder_shift_var = send_reminder_shift_var
        self.send_reminder_shift_holidays_var = send_reminder_shift_holidays_var
        self.send_reminder_reservations_var = send_reminder_reservations_var
        self.send_reminder_default_minutes_var = send_reminder_default_minutes_var
        self.send_period_from_last_var = send_period_from_last_var
        self.send_period_anchor_monthly_var = send_period_anchor_monthly_var
```

- [ ] **Step 4: Save-Pfad ergänzen**

In `src/dialogs/settings_dialog/dialog.py` oben
`from src.send_reminder import shift_for_label` importieren und im
`updates`-Dict nach `"send_reminder_time"` einfügen:

```python
            "send_reminder_weekend_shift": shift_for_label(
                app.send_reminder_shift_var.get()),
            "send_reminder_shift_holidays": app.send_reminder_shift_holidays_var.get(),
            "send_reminder_reservations_enabled": app.send_reminder_reservations_var.get(),
            "send_reminder_default_minutes": int(
                app.send_reminder_default_minutes_var.get()),
            "send_period_from_last_reminder": app.send_period_from_last_var.get(),
            "send_period_anchor_monthly": app.send_period_anchor_monthly_var.get(),
```

- [ ] **Step 5: App manuell starten und den Tab ansehen**

Run: `python -m src.main`
Expected: Einstellungen → Tab „App" → Abschnitt „Benachrichtigungen" zeigt die
neuen Zeilen; Speichern und erneutes Öffnen behält die Werte.

- [ ] **Step 6: Tests, Lint, Typecheck**

Run: `pytest ; if ($?) { ruff check . }`
Expected: alle PASS, keine Lint-Fehler.

- [ ] **Step 7: Commit**

```bash
git add src/dialogs/settings_dialog/tab_app.py src/dialogs/settings_dialog/dialog.py tests/test_settings_dialog.py
git commit -m "feat(settings-ui): Optionen fuer Verschiebung und Reservierungs-Erinnerung"
```

---

### Task 10: Erinnerungs-Block im Tages-Dialog

**Files:**
- Modify: `src/dialogs/entry_dialog.py`
- Test: `tests/test_entry_dialog.py`

**Interfaces:**
- Consumes: Settings aus Task 4, Slot-Feld aus Task 1
- Produces:
  - `apply_reminder_to_slots(res_slots, slot_index, minutes, enabled) -> None` (mutiert in-place)
  - `reminder_block_visible(settings, show_reservation) -> bool`
  - `reminder_slot_labels(rows) -> list[str]`

- [ ] **Step 1: Failing tests schreiben**

Ans Ende von `tests/test_entry_dialog.py`:

```python
def _rslot(start, end, minutes=None):
    return {"start": start, "end": end, "kategorie": "",
            "send_reminder_minutes": minutes}


def test_apply_reminder_marks_only_the_chosen_slot():
    from src.dialogs.entry_dialog import apply_reminder_to_slots

    slots = [_rslot("08:00", "12:00", 30), _rslot("13:00", "17:00")]
    apply_reminder_to_slots(slots, 1, 15, True)
    assert [s["send_reminder_minutes"] for s in slots] == [None, 15]


def test_apply_reminder_disabled_clears_all():
    from src.dialogs.entry_dialog import apply_reminder_to_slots

    slots = [_rslot("08:00", "12:00", 30), _rslot("13:00", "17:00")]
    apply_reminder_to_slots(slots, 0, 15, False)
    assert [s["send_reminder_minutes"] for s in slots] == [None, None]


def test_apply_reminder_invalid_index_clears_all():
    from src.dialogs.entry_dialog import apply_reminder_to_slots

    slots = [_rslot("08:00", "12:00", 30)]
    apply_reminder_to_slots(slots, 5, 15, True)
    assert slots[0]["send_reminder_minutes"] is None
    apply_reminder_to_slots(slots, None, 15, True)
    assert slots[0]["send_reminder_minutes"] is None


def test_apply_reminder_invalid_minutes_clears_all():
    from src.dialogs.entry_dialog import apply_reminder_to_slots

    slots = [_rslot("08:00", "12:00")]
    apply_reminder_to_slots(slots, 0, None, True)
    assert slots[0]["send_reminder_minutes"] is None


def test_reminder_block_visible_needs_both_settings_and_reservation_block():
    from src.dialogs.entry_dialog import reminder_block_visible

    class _S:
        def __init__(self, **kw):
            self._d = kw

        def get(self, key):
            return self._d.get(key)

    on = _S(send_reminder_enabled=True, send_reminder_reservations_enabled=True)
    assert reminder_block_visible(on, True) is True
    assert reminder_block_visible(on, False) is False
    assert reminder_block_visible(
        _S(send_reminder_enabled=False,
           send_reminder_reservations_enabled=True), True) is False
    assert reminder_block_visible(
        _S(send_reminder_enabled=True,
           send_reminder_reservations_enabled=False), True) is False


def test_reminder_slot_labels_are_unique_and_ordered():
    from src.dialogs.entry_dialog import reminder_slot_labels

    rows = [{"start": "08:00", "end": "12:00", "kategorie": "Office"},
            {"start": "08:00", "end": "12:00", "kategorie": "Office"},
            {"start": "13:00", "end": "17:00", "kategorie": ""}]
    labels = reminder_slot_labels(rows)
    assert labels == ["1. 08:00–12:00  Office", "2. 08:00–12:00  Office",
                      "3. 13:00–17:00"]
    assert len(set(labels)) == 3
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_entry_dialog.py -v`
Expected: FAIL — `cannot import name 'apply_reminder_to_slots'`.

- [ ] **Step 3: Tk-freie Helfer implementieren**

In `src/dialogs/entry_dialog.py` neben `reservation_block_visible`:

```python
def reminder_block_visible(settings, show_reservation):
    """Ob der Erinnerungs-Block im Tages-Dialog erscheint: nur wenn die
    Sende-Erinnerung überhaupt an ist, die Kopplung an Reservierungen aktiviert
    wurde und der Reservierungs-Block selbst sichtbar ist (der liefert die
    Slots, an denen die Erinnerung hängt)."""
    return bool(
        show_reservation
        and settings.get("send_reminder_enabled")
        and settings.get("send_reminder_reservations_enabled")
    )


def reminder_slot_labels(rows):
    """Anzeige-Labels der Reservierungs-Zeilen fürs Slot-Dropdown.

    `rows`: Liste von {start, end, kategorie}. Die führende Nummer hält die
    Labels eindeutig — zwei Zeilen dürfen dieselbe Zeit und Kategorie haben,
    und der Dialog liest die Auswahl über den Listen-Index zurück.
    """
    out = []
    for i, row in enumerate(rows):
        kategorie = (row.get("kategorie") or "").strip()
        label = f"{i + 1}. {row.get('start')}–{row.get('end')}"
        out.append(f"{label}  {kategorie}" if kategorie else label)
    return out


def apply_reminder_to_slots(res_slots, slot_index, minutes, enabled):
    """Setzt `send_reminder_minutes` am gewählten Slot und None an allen
    anderen — die Invariante „höchstens ein markierter Slot pro Tag".

    Mutiert `res_slots` in-place. enabled=False, ein Index außerhalb der Liste
    oder ungültige Minuten → alle Slots None.
    """
    valid = (
        enabled
        and isinstance(slot_index, int)
        and not isinstance(slot_index, bool)
        and 0 <= slot_index < len(res_slots)
        and isinstance(minutes, int)
        and not isinstance(minutes, bool)
        and 0 <= minutes <= 120
    )
    for i, slot in enumerate(res_slots):
        slot["send_reminder_minutes"] = minutes if valid and i == slot_index else None
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/test_entry_dialog.py -v`
Expected: alle PASS.

- [ ] **Step 5: Commit der reinen Logik**

```bash
git add src/dialogs/entry_dialog.py tests/test_entry_dialog.py
git commit -m "feat(entry-dialog): Tk-freie Helfer fuer den Erinnerungs-Block"
```

- [ ] **Step 6: Reservierungs-Zeilen den Marker mitführen lassen**

`add_res_row` bekommt einen weiteren Parameter und legt den Wert im Record ab
(er wird nicht bearbeitet, nur durchgereicht):

```python
        def add_res_row(start, end, kategorie, removable=True,
                        send_reminder_minutes=None):
```

und im Record:

```python
            record = {"frame": row, "start": sv, "end": ev, "kategorie": kv,
                      # Nicht editierbar in der Zeile — nur mitgeführt, damit
                      # ein bestehender Marker das Speichern überlebt, auch
                      # wenn der Erinnerungs-Block gar nicht sichtbar ist.
                      "send_reminder_minutes": send_reminder_minutes}
```

Die Vorbelegung aus dem Store mitgeben:

```python
        if existing_reservation and existing_reservation["slots"]:
            for s in existing_reservation["slots"]:
                add_res_row(s["start"], s["end"], s.get("kategorie", ""),
                            removable=False,
                            send_reminder_minutes=s.get("send_reminder_minutes"))
```

In `save_all` die res_slots um das Feld erweitern:

```python
        res_slots = [{
            "start": r["start"].get(),
            "end": r["end"].get(),
            "kategorie": category_from_display(r["kategorie"].get()),
            "send_reminder_minutes": r["send_reminder_minutes"],
        } for r in res_rows]
```

- [ ] **Step 7: Den Block bauen**

**Platzierung:** nach dem kompletten `if show_reservation:`-Block und **vor**
dem Abschnitt „Mindestbreite ohne Slot-Zeilen", auf Funktionsebene — nicht
innerhalb des `if`. Sonst wäre `reminder_ui` nicht definiert, wenn kein
Reservierungs-Block gezeigt wird, und `save_all` liefe in einen `NameError`.
`reminder_block_visible` verlangt `show_reservation` ohnehin, und `res_rows`
ist auf Funktionsebene definiert.

```python
    reminder_ui = None
    if reminder_block_visible(settings, show_reservation):
        tk.Label(
            outer, text="— Erinnerung —", font=FONT_BOLD, bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(12, 2))
        rem_frame = tk.Frame(outer, bg=BG)
        rem_frame.pack(fill="x")

        marked = next(
            (i for i, r in enumerate(res_rows)
             if r["send_reminder_minutes"] is not None), None)
        rem_enabled = tk.BooleanVar(value=marked is not None)
        rem_slot = tk.StringVar()
        rem_minutes = tk.StringVar(value=str(
            res_rows[marked]["send_reminder_minutes"] if marked is not None
            else settings.get("send_reminder_default_minutes")))
        # Ausgewählter Slot als Index — die Labels ändern sich mit den Zeiten,
        # der Index ist die stabile Auswahl.
        rem_index = {"value": marked if marked is not None else None}

        rem_cb = tk.Checkbutton(
            rem_frame, text="Ans Verschicken der Arbeitszeiten erinnern",
            variable=rem_enabled, font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        )
        rem_cb.pack(anchor="w")

        rem_row = tk.Frame(rem_frame, bg=BG)
        rem_row.pack(anchor="w", pady=(2, 0))
        tk.Label(rem_row, text="Slot:", font=FONT, bg=BG, fg=TEXT).pack(
            side=tk.LEFT, padx=(24, 8))
        slot_combo = dark_combo(rem_row, rem_slot, [], width=26)
        slot_combo.pack(side=tk.LEFT, padx=(0, 8))
        dark_combo(rem_row, rem_minutes,
                   [str(m) for m in range(0, 121, 5)], width=4).pack(side=tk.LEFT)
        tk.Label(rem_row, text="Minuten vor Ende", font=FONT, bg=BG, fg=TEXT).pack(
            side=tk.LEFT, padx=(8, 0))
        rem_hint = tk.Label(
            rem_frame, text="Erst eine Reservierung anlegen.",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED)

        def on_slot_selected(*_a):
            values = list(slot_combo.cget("values"))
            if rem_slot.get() in values:
                rem_index["value"] = values.index(rem_slot.get())

        slot_combo.bind("<<ComboboxSelected>>", on_slot_selected, add="+")

        def refresh_reminder_block(*_a):
            """Hält Slot-Liste und Bedienbarkeit an den Reservierungs-Zeilen.

            Wird bei jedem Hinzufügen/Entfernen einer Zeile und bei jeder
            Zeit-/Kategorie-Änderung aufgerufen; die Auswahl bleibt über den
            Index erhalten und wird auf die Listenlänge geklemmt.
            """
            rows = [{"start": r["start"].get(), "end": r["end"].get(),
                     "kategorie": category_from_display(r["kategorie"].get())}
                    for r in res_rows]
            labels = reminder_slot_labels(rows)
            slot_combo.config(values=labels)
            if not labels:
                rem_enabled.set(False)
                rem_index["value"] = None
                rem_slot.set("")
                rem_cb.config(state="disabled")
                slot_combo.config(state="disabled")
                rem_hint.pack(anchor="w", padx=(24, 0))
                return
            rem_cb.config(state="normal")
            slot_combo.config(state="readonly")
            rem_hint.pack_forget()
            index = rem_index["value"]
            if index is None or index >= len(labels):
                index = len(labels) - 1
                rem_index["value"] = index
            rem_slot.set(labels[index])

        reminder_ui = {
            "enabled": rem_enabled, "minutes": rem_minutes, "index": rem_index,
            "refresh": refresh_reminder_block,
        }
        refresh_reminder_block()
```

Damit der Block auf Änderungen reagiert, `refresh_reminder_block` an drei
Stellen anstoßen. Weil er erst nach `add_res_row` definiert ist, geht das über
eine Late-Bound-Indirektion — direkt nach `res_rows = []` oben im Dialog
ergänzen:

```python
    # Late-bound: der Erinnerungs-Block wird erst nach den Reservierungs-Zeilen
    # gebaut, muss aber von deren Änderungen erfahren.
    notify_reminder_block = {"fn": None}

    def _reminder_changed(*_a):
        if notify_reminder_block["fn"] is not None:
            notify_reminder_block["fn"]()
```

In `add_res_row` nach `refresh_save_state()` am Ende sowie in dessen
`remove()` nach `refresh_save_state()` jeweils `_reminder_changed()` aufrufen,
und in `add_res_row` die Traces erweitern:

```python
            sv.trace_add("write", _reminder_changed)
            ev.trace_add("write", _reminder_changed)
            cat_combo.bind("<<ComboboxSelected>>", _reminder_changed, add="+")
```

Nach dem Bau des Blocks die Indirektion schließen:

```python
        notify_reminder_block["fn"] = refresh_reminder_block
```

- [ ] **Step 8: Im Speichern-Pfad anwenden**

In `save_all`, direkt vor `plan = plan_entry_save(...)`:

```python
        if reminder_ui is not None:
            # Nur bei sichtbarem Block anfassen: sonst blieben die aus dem
            # Store mitgeführten Marker unangetastet, statt still gelöscht zu
            # werden, wenn die Option abgeschaltet wurde.
            apply_reminder_to_slots(
                res_slots, reminder_ui["index"]["value"],
                parse_reminder_minutes(reminder_ui["minutes"].get()),
                bool(reminder_ui["enabled"].get()),
            )
```

Import ergänzen: `from src.settings import WEEKDAY_KEYS, parse_reminder_minutes`.

- [ ] **Step 9: Manuell verifizieren**

Run: `python -m src.main`
Expected (Kalender-Abgleich aktiv, beide Settings an):
1. Linksklick auf einen heutigen/zukünftigen Tag ohne Reservierung → Block da,
   Checkbox deaktiviert, Hinweis „Erst eine Reservierung anlegen."
2. „+ Slot" bei der Reservierung → Checkbox wird bedienbar, Slot-Dropdown zeigt
   „1. 08:00–16:00".
3. Zweiten Slot anlegen, zweiten wählen, 30 Minuten, speichern, Dialog erneut
   öffnen → Haken steht, zweiter Slot und 30 sind vorbelegt.
4. Option „Reservierungen" abschalten, Tag erneut speichern, wieder
   einschalten → die Markierung steht noch.
5. Rechtsklick → nur den markierten Slot löschen → Markierung ist weg, der
   andere Slot bleibt.

- [ ] **Step 10: Tests, Lint, Typecheck**

Run: `pytest ; if ($?) { ruff check . }`
Expected: alle PASS.

- [ ] **Step 11: Commit**

```bash
git add src/dialogs/entry_dialog.py
git commit -m "feat(entry-dialog): Erinnerungs-Block an Reservierungs-Slots"
```

---

### Task 11: Zeitraum-Vorbelegung im Sende-Dialog

**Files:**
- Modify: `src/dialogs/period_picker.py:88-105`, `src/dialogs/send_dialog.py:63-90`, `src/ui.py:736-737`
- Test: `tests/test_period_picker.py`

**Interfaces:**
- Consumes: `default_send_period`, `marked_reminder_dates`,
  `monthly_anchor_dates` aus Task 7
- Produces:
  - `build_period_picker(parent, storage, settings, on_change=None, from_default=None, to_default=None)`
  - `resolve_send_period(settings, reservation_store, today) -> tuple[date, date] | None` in `send_dialog.py`

- [ ] **Step 1: Failing test schreiben**

Ans Ende von `tests/test_period_picker.py`:

```python
def test_resolve_send_period_off_by_default():
    from src.dialogs.send_dialog import resolve_send_period

    class _S:
        def __init__(self, **kw):
            self._d = kw

        def get(self, key):
            return self._d.get(key)

    assert resolve_send_period(
        _S(send_period_from_last_reminder=False), None,
        datetime.date(2026, 9, 5)) is None


def test_resolve_send_period_uses_marked_days():
    from src.dialogs.send_dialog import resolve_send_period

    class _S:
        def __init__(self, **kw):
            self._d = kw

        def get(self, key):
            return self._d.get(key)

    class _Store:
        def get_all_raw(self):
            return {"2026-08-02": {"slots": [{"send_reminder_minutes": 15}],
                                   "modified_at": "x", "deleted": False}}

    assert resolve_send_period(
        _S(send_period_from_last_reminder=True, send_period_anchor_monthly=False),
        _Store(), datetime.date(2026, 9, 5),
    ) == (datetime.date(2026, 8, 3), datetime.date(2026, 9, 5))


def test_resolve_send_period_with_monthly_anchor():
    from src.dialogs.send_dialog import resolve_send_period

    class _S:
        def __init__(self, **kw):
            self._d = kw

        def get(self, key):
            return self._d.get(key)

    class _Store:
        def get_all_raw(self):
            return {"2026-08-02": {"slots": [{"send_reminder_minutes": 15}],
                                   "modified_at": "x", "deleted": False}}

    settings = _S(send_period_from_last_reminder=True,
                  send_period_anchor_monthly=True,
                  send_reminder_enabled=True,
                  send_reminder_day=23, send_reminder_time="16:30",
                  send_reminder_weekend_shift="none",
                  send_reminder_shift_holidays=False, state="")
    assert resolve_send_period(settings, _Store(), datetime.date(2026, 9, 5)) \
        == (datetime.date(2026, 8, 24), datetime.date(2026, 9, 5))


def test_resolve_send_period_ignores_monthly_when_reminder_off():
    from src.dialogs.send_dialog import resolve_send_period

    class _S:
        def __init__(self, **kw):
            self._d = kw

        def get(self, key):
            return self._d.get(key)

    class _Store:
        def get_all_raw(self):
            return {"2026-08-02": {"slots": [{"send_reminder_minutes": 15}],
                                   "modified_at": "x", "deleted": False}}

    settings = _S(send_period_from_last_reminder=True,
                  send_period_anchor_monthly=True,
                  send_reminder_enabled=False,
                  send_reminder_day=23, send_reminder_time="16:30",
                  send_reminder_weekend_shift="none",
                  send_reminder_shift_holidays=False, state="")
    assert resolve_send_period(settings, _Store(), datetime.date(2026, 9, 5)) \
        == (datetime.date(2026, 8, 3), datetime.date(2026, 9, 5))
```

Oben in der Datei `import datetime` sicherstellen.

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_period_picker.py -v`
Expected: FAIL — `cannot import name 'resolve_send_period'`.

- [ ] **Step 3: `resolve_send_period` implementieren**

In `src/dialogs/send_dialog.py`, oberhalb von `open_send_dialog`:

```python
def resolve_send_period(settings, reservation_store, today):
    """Von/Bis-Vorbelegung für den Sende-Dialog, oder None.

    None heißt „bisheriger Default" (Vormonats-Pendant im period_picker).
    Ist die Option aus, gibt es keinen Store oder keinen zurückliegenden
    Anker, bleibt es dabei. Monatstermine zählen nur mit, wenn sie
    eingeschaltet sind — ein abgeschalteter Termin hat nie erinnert und darf
    den Zeitraum nicht verkürzen.
    """
    from src import send_reminder

    if not settings.get("send_period_from_last_reminder"):
        return None
    if reservation_store is None:
        return None
    marked = send_reminder.marked_reminder_dates(reservation_store.get_all_raw())
    monthly = []
    if settings.get("send_period_anchor_monthly") and settings.get("send_reminder_enabled"):
        monthly = send_reminder.monthly_anchor_dates(
            today,
            settings.get("send_reminder_day"),
            settings.get("send_reminder_time"),
            settings.get("send_reminder_weekend_shift"),
            settings.get("state"),
            bool(settings.get("send_reminder_shift_holidays")),
        )
    return send_reminder.default_send_period(today, marked, monthly)
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/test_period_picker.py -v`
Expected: alle PASS.

- [ ] **Step 5: Picker parametrisieren und verdrahten**

In `src/dialogs/period_picker.py` die Signatur erweitern und die zwei
Default-Zeilen ersetzen:

```python
def build_period_picker(parent, storage, settings, on_change=None,
                        from_default=None, to_default=None):
```

Im Docstring ergänzen:

```
    from_default / to_default: optionale Vorbelegung der Datumszeilen. Ohne
    sie gilt wie bisher „Vormonats-Pendant bis heute" (_default_from_date).
```

und:

```python
    today = datetime.date.today()
    from_value = from_default if from_default is not None else _default_from_date(today)
    to_value = to_default if to_default is not None else today
```

Die beiden `build_date_row`-Aufrufe auf `from_value` / `to_value` umstellen.

In `src/dialogs/send_dialog.py` die Signatur um den Store erweitern und den
Picker versorgen:

```python
def open_send_dialog(parent, storage, settings, base_path, runner,
                     reservation_store=None):
```

```python
    period = resolve_send_period(settings, reservation_store, datetime.date.today())
    picker_frame, picker = build_period_picker(
        dialog, storage, settings,
        from_default=period[0] if period else None,
        to_default=period[1] if period else None,
    )
```

`import datetime` oben in `send_dialog.py` ergänzen.

In `src/ui.py::_send`:

```python
    def _send(self):
        open_send_dialog(self.root, self.storage, self.settings, self.base_path,
                         self._bg, reservation_store=self.reservation_store)
```

- [ ] **Step 6: Manuell verifizieren**

Run: `python -m src.main`
Expected: Mit aktivierter Option „Zeitraum ab der letzten Erinnerung
vorbelegen" und einem markierten Tag in der Vergangenheit zeigt „Senden" das
Von-Datum als Tag nach diesem Tag; ohne Markierung bleibt es beim
Vormonats-Pendant. Der Export-Dialog ist unverändert.

- [ ] **Step 7: Tests, Lint, Typecheck**

Run: `pytest ; if ($?) { ruff check . }`
Expected: alle PASS.

- [ ] **Step 8: Commit**

```bash
git add src/dialogs/period_picker.py src/dialogs/send_dialog.py src/ui.py tests/test_period_picker.py
git commit -m "feat(send-dialog): Zeitraum ab der letzten Erinnerung vorbelegen"
```

---

### Task 12: Dokumentation und Gesamtlauf

**Files:**
- Modify: `CLAUDE.md`, `src/CLAUDE.md`

- [ ] **Step 1: `CLAUDE.md` nachziehen**

Im Abschnitt „Struktur" den Eintrag zu `send_reminder.py` ersetzen:

```markdown
- `src/send_reminder.py` — pure Logik des Sende-Reminders (Tk-frei): monatlicher
  Termin (Tag im Monat auf die Monatslänge geclamped, optional von Wochenenden/
  Feiertagen weg verschoben — die Verschiebung bleibt immer im Zielmonat),
  tagesbezogene Fälligkeit an einem markierten Reservierungs-Slot
  (`due_day_reminder`) und die Anker-Suche für die Zeitraum-Vorbelegung
  (`previous_anchor_date`/`default_send_period`); `src/send_reminder_scheduler.py`
  — periodischer Poll (root.after) über beide Kanäle → Toast über Tray. Der
  Monats-Kanal persistiert seinen Fired-Zustand in den Settings (einmal pro
  Monat, auch über Neustarts), der tagesbezogene dedupliziert nur im Speicher
  (ein persistierter Marker würde `modified_at` der Reservierung anfassen und
  einen gcal-Push auslösen).
```

Im Eintrag zu `src/reservations.py` das Schema ergänzen:

```markdown
- `src/reservations.py` — Reservierungen (zukünftige Soll-Zeiten, eigenes Konzept
  neben Ist-Zeiten). Slot-Schema `{start, end, kategorie, gcal_event_id,
  send_reminder_minutes}`; `send_reminder_minutes` markiert den Slot, an dem die
  Sende-Erinnerung hängt (höchstens einer pro Tag, gerätelokal — der Kalender
  kennt das Feld nicht) und wird in `share.py` bewusst aus dem Share-Doc
  projiziert, weil dessen Validator unbekannte Felder ablehnt.
```

- [ ] **Step 2: `src/CLAUDE.md` nachziehen**

Die Verantwortlichkeit von `SendReminderScheduler` um die neue Abhängigkeit
`reservation_store` und den zweiten Kanal erweitern (Formulierung an den
vorhandenen Stil des Dokuments anpassen).

- [ ] **Step 3: Gesamtlauf**

Run: `pytest ; if ($?) { ruff check . }`
Expected: alle Tests PASS, keine Lint-Fehler.

Run: `npx pyright`
Expected: keine neuen Fehler gegenüber dem Stand vor dem Branch.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md src/CLAUDE.md
git commit -m "docs: Sende-Erinnerung an Reservierungen dokumentieren"
```

---

## Verifikation vor dem PR

- [ ] `pytest` grün (alle Dateien, nicht nur die geänderten)
- [ ] `ruff check .` sauber
- [ ] `npx pyright` ohne neue Fehler
- [ ] Manueller Durchlauf aus Task 10 Step 9 und Task 11 Step 6 gemacht
- [ ] `src/version.py` und `CHANGELOG.md` im Release-PR gesetzt (siehe
      „Release-Prozess" in `CLAUDE.md`)

Das Feature ist reine Anwendungslogik ohne plattformspezifische Zweige — ein
Pre-Release vor dem Merge ist nach der Regel in `CLAUDE.md` („Plattform-
spezifische PRs") **nicht** erforderlich.
