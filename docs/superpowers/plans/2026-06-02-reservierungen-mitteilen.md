# Reservierungen beim Teilen mitschicken — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das bestehende „Arbeitszeiten teilen"-Feature (Gmail-Anhang) so erweitern, dass der Nutzer Arbeitszeiten, Reservierungen oder beides verschicken kann und der Empfänger beide Typen optional importiert.

**Architecture:** Reine Logik in `src/share.py` (Wire-Format v2 mit optionalen `entries`/`reservations`, generalisierter Diff, neuer Reservierungs-Apply) wird TDD-getrieben erweitert. Die zwei Tkinter-Dialoge (`share_dialog.py` Senden, `import_dialog.py` Importieren) bekommen Typ-Auswahl bzw. einen Abschnitt pro Datentyp. Plumbing reicht den vorhandenen `reservation_store` durch.

**Tech Stack:** Python 3, Tkinter, pytest. Keine neuen Dependencies.

**Referenz-Spec:** `docs/superpowers/specs/2026-06-02-reservierungen-mitteilen-design.md`

---

## File Structure

- **Modify** `src/share.py` — Wire-Format v2, Reservierungs-Validierung, generalisierter Diff, `build_share_doc`-Typauswahl, `apply_reservation_import`.
- **Modify** `tests/test_share.py` — neue Tests + Anpassung des Version-Tests.
- **Modify** `src/dialogs/share_dialog.py` — zwei Typ-Checkboxen, `reservation_store`-Parameter, Doc-Bau je Auswahl, angepasster Betreff/Body.
- **Modify** `src/dialogs/import_dialog.py` — ein Abschnitt pro Datentyp mit Master-Schalter + Konflikt-Modi, gemeinsamer Zeitraum-Filter, gcal-aus-Hinweis, `reservation_store`-Parameter.
- **Modify** `src/dialogs/settings_dialog.py` — `reservation_store` an `open_import_dialog` durchreichen.
- **Modify** `src/ui.py` — `reservation_store` an Share- und Settings-Dialog übergeben.

---

## Task 1: Wire-Format v2 + Reservierungs-Validierung (`share.py`)

**Files:**
- Modify: `src/share.py` (`SCHEMA_VERSION`, `parse_share_doc`)
- Test: `tests/test_share.py`

- [ ] **Step 1: Vorhandenen Versions-Test anpassen, neue Tests schreiben (failing)**

In `tests/test_share.py` den bestehenden Test `test_parse_rejects_future_schema_version` von Version `2` auf `3` umstellen (2 ist künftig gültig):

```python
def test_parse_rejects_future_schema_version():
    with pytest.raises(ShareValidationError, match="neueren Version"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 3,
            "entries": {},
        }))
```

Am Ende von `tests/test_share.py` anhängen:

```python
# --- v2: Reservierungen + abwärtskompatibles Lesen ---

def _v2(**fields):
    base = {"kind": "zeiterfassung-share", "schema_version": 2}
    base.update(fields)
    return _bytes(base)


def test_parse_v1_entries_only_still_accepted():
    doc = parse_share_doc(_bytes({
        "kind": "zeiterfassung-share",
        "schema_version": 1,
        "entries": {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0}},
    }))
    assert doc["schema_version"] == 1
    assert "2026-05-14" in doc["entries"]


def test_parse_v2_entries_only():
    doc = parse_share_doc(_v2(entries={"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0}}))
    assert doc["entries"] != {}


def test_parse_v2_reservations_only():
    doc = parse_share_doc(_v2(reservations={"2026-05-14": {"start": "08:00", "end": "12:00"}}))
    assert doc["reservations"] == {"2026-05-14": {"start": "08:00", "end": "12:00"}}


def test_parse_v2_both():
    doc = parse_share_doc(_v2(
        entries={"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0}},
        reservations={"2026-05-15": {"start": "09:00", "end": "12:00"}},
    ))
    assert doc["entries"] and doc["reservations"]


def test_parse_v2_rejects_both_missing():
    with pytest.raises(ShareValidationError, match="weder"):
        parse_share_doc(_v2())


def test_parse_v2_rejects_both_empty():
    with pytest.raises(ShareValidationError, match="weder"):
        parse_share_doc(_v2(entries={}, reservations={}))


def test_parse_v2_reservation_rejects_pause_field():
    with pytest.raises(ShareValidationError, match="unbekannt"):
        parse_share_doc(_v2(reservations={"2026-05-14": {"start": "08:00", "end": "12:00", "pause": 0}}))


def test_parse_v2_reservation_rejects_missing_field():
    with pytest.raises(ShareValidationError, match="fehlend"):
        parse_share_doc(_v2(reservations={"2026-05-14": {"start": "08:00"}}))


def test_parse_v2_reservation_rejects_bad_time():
    with pytest.raises(ShareValidationError, match="Startzeit"):
        parse_share_doc(_v2(reservations={"2026-05-14": {"start": "25:00", "end": "12:00"}}))


def test_parse_v2_reservation_rejects_bad_date_key():
    with pytest.raises(ShareValidationError, match="Datum"):
        parse_share_doc(_v2(reservations={"not-a-date": {"start": "08:00", "end": "12:00"}}))
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_share.py -q`
Expected: FAIL (neue Tests scheitern; `test_parse_rejects_future_schema_version` mit v3 schlägt fehl, weil v3 aktuell wie „unbekannt" statt „neuer" behandelt wird bzw. v2 abgelehnt wird).

- [ ] **Step 3: `share.py` implementieren**

In `src/share.py` `SCHEMA_VERSION` anheben:

```python
SCHEMA_VERSION = 2
KIND = "zeiterfassung-share"
```

Neue Konstante neben `_ENTRY_KEYS` ergänzen:

```python
_ENTRY_KEYS = frozenset({"start", "end", "pause"})
_RESERVATION_KEYS = frozenset({"start", "end"})
```

Die Validierungs-Schleife aus `parse_share_doc` in zwei Helfer auslagern und `parse_share_doc` ersetzen. Die alte Schleife (ab `entries = doc.get("entries")` bis `return doc`) durch Folgendes ersetzen:

```python
def _validate_time(date_str, label, value):
    if not isinstance(value, str) or not _TIME_RE.match(value):
        raise ShareValidationError(f"Eintrag {date_str}: ungültige {label} {value!r}")
    try:
        datetime.time.fromisoformat(value)
    except ValueError:
        raise ShareValidationError(f"Eintrag {date_str}: ungültige {label} {value!r}")


def _validate_date_key(date_str):
    if not isinstance(date_str, str) or not _DATE_RE.match(date_str):
        raise ShareValidationError(f"Ungültiger Datums-Key: {date_str!r}")
    try:
        datetime.date.fromisoformat(date_str)
    except ValueError:
        raise ShareValidationError(f"Ungültiges Datum: {date_str!r}")


def _check_keys(date_str, entry, expected_keys):
    if not isinstance(entry, dict):
        raise ShareValidationError(f"Eintrag {date_str} ist kein Objekt.")
    keys = set(entry.keys())
    if keys != expected_keys:
        extras = sorted(keys - expected_keys)
        missing = sorted(expected_keys - keys)
        parts = []
        if extras:
            parts.append(f"unbekannte Felder: {extras}")
        if missing:
            parts.append(f"fehlende Felder: {missing}")
        raise ShareValidationError(f"Eintrag {date_str}: {'; '.join(parts)}")


def _validate_entries(entries):
    for date_str, entry in entries.items():
        _validate_date_key(date_str)
        _check_keys(date_str, entry, _ENTRY_KEYS)
        _validate_time(date_str, "Startzeit", entry["start"])
        _validate_time(date_str, "Endzeit", entry["end"])
        pause = entry["pause"]
        if not isinstance(pause, int) or isinstance(pause, bool) or pause < 0:
            raise ShareValidationError(f"Eintrag {date_str}: ungültige Pause {pause!r}")


def _validate_reservations(reservations):
    for date_str, entry in reservations.items():
        _validate_date_key(date_str)
        _check_keys(date_str, entry, _RESERVATION_KEYS)
        _validate_time(date_str, "Startzeit", entry["start"])
        _validate_time(date_str, "Endzeit", entry["end"])
```

`parse_share_doc` so umbauen, dass nach der `kind`-Prüfung folgender Block steht (die bisherige `schema_version`- und `entries`-Logik ersetzen):

```python
    schema_version = doc.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ShareValidationError("Fehlende oder ungültige schema_version.")
    if schema_version > SCHEMA_VERSION:
        raise ShareValidationError(
            "Diese Datei wurde mit einer neueren Version erstellt. "
            "Bitte App aktualisieren."
        )
    if schema_version < 1:
        raise ShareValidationError(f"Unbekannte schema_version: {schema_version}")

    entries = doc.get("entries")
    reservations = doc.get("reservations")

    if schema_version == 1:
        # v1: nur entries, Pflichtfeld (Abwärtskompatibilität für Alt-Dateien).
        if not isinstance(entries, dict):
            raise ShareValidationError("Feld 'entries' fehlt oder ist kein Objekt.")
        _validate_entries(entries)
        return doc

    # v2: entries und reservations beide optional, mind. eines nicht-leer.
    if entries is not None:
        if not isinstance(entries, dict):
            raise ShareValidationError("Feld 'entries' ist kein Objekt.")
        _validate_entries(entries)
    if reservations is not None:
        if not isinstance(reservations, dict):
            raise ShareValidationError("Feld 'reservations' ist kein Objekt.")
        _validate_reservations(reservations)
    if not entries and not reservations:
        raise ShareValidationError(
            "Datei enthält weder Arbeitszeiten noch Reservierungen."
        )
    return doc
```

- [ ] **Step 4: Tests laufen lassen — müssen grün sein**

Run: `pytest tests/test_share.py -q`
Expected: PASS (alle, inkl. der bestehenden v1-Tests).

- [ ] **Step 5: Commit**

```bash
git add src/share.py tests/test_share.py
git commit -m "feat(share): wire-format v2 mit optionalen reservations + v1 lesend kompatibel"
```

---

## Task 2: `build_share_doc` mit Typ-Auswahl (`share.py`)

**Files:**
- Modify: `src/share.py` (`build_share_doc`)
- Test: `tests/test_share.py`

- [ ] **Step 1: Tests schreiben (failing)**

Am Ende von `tests/test_share.py` anhängen:

```python
class _FakeResStore:
    def __init__(self, data):
        self._d = data

    def get_all(self):
        return dict(self._d)


def test_build_doc_entries_only_omits_reservations():
    storage = _FakeStorage({"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0}})
    doc = build_share_doc(storage, "a@b.de")
    assert "entries" in doc
    assert "reservations" not in doc
    assert doc["schema_version"] == 2


def test_build_doc_reservations_only():
    storage = _FakeStorage({"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0}})
    res = _FakeResStore({"2026-05-15": {"start": "09:00", "end": "12:00"}})
    doc = build_share_doc(
        storage, "a@b.de", reservation_store=res,
        include_entries=False, include_reservations=True,
    )
    assert "entries" not in doc
    assert doc["reservations"] == {"2026-05-15": {"start": "09:00", "end": "12:00"}}


def test_build_doc_both():
    storage = _FakeStorage({"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0}})
    res = _FakeResStore({"2026-05-15": {"start": "09:00", "end": "12:00"}})
    doc = build_share_doc(
        storage, "a@b.de", reservation_store=res,
        include_entries=True, include_reservations=True,
    )
    assert doc["entries"] and doc["reservations"]
    parsed = parse_share_doc(serialize_share_doc(doc))
    assert parsed["entries"] and parsed["reservations"]
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_share.py -k build_doc -q`
Expected: FAIL (`build_share_doc` kennt die neuen kwargs noch nicht).

- [ ] **Step 3: `build_share_doc` ersetzen**

In `src/share.py` die Funktion ersetzen:

```python
def build_share_doc(storage, sender_email, *, reservation_store=None,
                    include_entries=True, include_reservations=False):
    """Baut das Share-Doc. Tombstones sind via get_all() bereits gefiltert.

    include_entries / include_reservations steuern, welche Typen mitgehen.
    reservations werden nur aufgenommen, wenn ein reservation_store übergeben
    wurde."""
    doc = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "exported_at": _utc_now_iso(),
        "exported_by": sender_email or "",
    }
    if include_entries:
        doc["entries"] = dict(storage.get_all())
    if include_reservations and reservation_store is not None:
        doc["reservations"] = dict(reservation_store.get_all())
    return doc
```

- [ ] **Step 4: Tests laufen lassen — müssen grün sein**

Run: `pytest tests/test_share.py -q`
Expected: PASS (auch die bestehenden `test_build_share_doc_*`, da `include_entries` per Default `True`).

- [ ] **Step 5: Commit**

```bash
git add src/share.py tests/test_share.py
git commit -m "feat(share): build_share_doc mit wählbaren typen (entries/reservations)"
```

---

## Task 3: Generalisierter Diff + Reservierungs-Apply (`share.py`)

**Files:**
- Modify: `src/share.py` (`diff_share_against_local`, neue `_diff_records`, `diff_reservations_against_local`, `apply_reservation_import`)
- Test: `tests/test_share.py`

- [ ] **Step 1: Tests schreiben (failing)**

Am Ende von `tests/test_share.py` anhängen:

```python
from src.share import (
    apply_reservation_import,
    diff_reservations_against_local,
)


def test_diff_reservations_additions_and_conflicts():
    store = _FakeResStore({"2026-05-14": {"start": "08:00", "end": "12:00"}})
    share = {
        "2026-05-14": {"start": "09:00", "end": "12:00"},  # conflict
        "2026-05-16": {"start": "10:00", "end": "14:00"},  # addition
    }
    diff = diff_reservations_against_local(share, store)
    assert [d for d, _ in diff["additions"]] == ["2026-05-16"]
    assert [d for d, _l, _s in diff["conflicts"]] == ["2026-05-14"]


def test_diff_reservations_untouched():
    store = _FakeResStore({"2026-05-14": {"start": "08:00", "end": "12:00"}})
    share = {"2026-05-14": {"start": "08:00", "end": "12:00"}}
    diff = diff_reservations_against_local(share, store)
    assert diff["untouched"] == ["2026-05-14"]
    assert diff["conflicts"] == []


def test_diff_reservations_range_filter():
    store = _FakeResStore({})
    share = {
        "2026-05-10": {"start": "08:00", "end": "12:00"},
        "2026-05-20": {"start": "08:00", "end": "12:00"},
    }
    diff = diff_reservations_against_local(share, store, date_from=_dt.date(2026, 5, 15))
    assert [d for d, _ in diff["additions"]] == ["2026-05-20"]
    assert diff["out_of_range"] == 1


class _RecordingResStore:
    def __init__(self):
        self.saved = []

    def save(self, date_str, start, end):
        self.saved.append((date_str, start, end))


def test_apply_reservation_import_calls_save_per_decision():
    store = _RecordingResStore()
    apply_reservation_import(store, [
        {"date": "2026-05-14", "entry": {"start": "08:00", "end": "12:00"}},
        {"date": "2026-05-15", "entry": {"start": "09:00", "end": "13:00"}},
    ])
    assert store.saved == [
        ("2026-05-14", "08:00", "12:00"),
        ("2026-05-15", "09:00", "13:00"),
    ]


def test_apply_reservation_import_integration_keeps_event_id(tmp_path):
    from src.reservations import ReservationStore
    store = ReservationStore(str(tmp_path / "r.json"))
    store.save("2026-05-14", "08:00", "12:00")
    # gcal_event_id simulieren
    raw = store.get_all_raw()
    raw["2026-05-14"]["gcal_event_id"] = "evt-1"
    store.apply_reconciled(raw)
    apply_reservation_import(store, [
        {"date": "2026-05-14", "entry": {"start": "10:00", "end": "14:00"}},
    ])
    assert store.get("2026-05-14") == {"start": "10:00", "end": "14:00"}
    assert store.get_all_raw()["2026-05-14"]["gcal_event_id"] == "evt-1"
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_share.py -k "reservation" -q`
Expected: FAIL (`diff_reservations_against_local` / `apply_reservation_import` existieren nicht).

- [ ] **Step 3: `share.py` implementieren**

In `src/share.py` die bestehende `diff_share_against_local` durch einen generischen Kern plus zwei Wrapper ersetzen, und `_reservations_equal` sowie `apply_reservation_import` ergänzen:

```python
def _reservations_equal(a, b):
    return a.get("start") == b.get("start") and a.get("end") == b.get("end")


def _diff_records(share_records, local_snapshot, equal_fn, date_from=None, date_to=None):
    """Typ-neutraler Diff zwischen Share-Records und lokalem Snapshot.

    share_records / local_snapshot: {date: record}.
    equal_fn(local_record, share_record) -> bool.
    Rückgabe: additions / conflicts / untouched / out_of_range (wie gehabt).
    """
    additions = []
    conflicts = []
    untouched = []
    out_of_range = 0

    for date_str in sorted(share_records.keys()):
        try:
            d = datetime.date.fromisoformat(date_str)
        except ValueError:
            continue
        if date_from is not None and d < date_from:
            out_of_range += 1
            continue
        if date_to is not None and d > date_to:
            out_of_range += 1
            continue

        share_rec = share_records[date_str]
        local_rec = local_snapshot.get(date_str)
        if local_rec is None:
            additions.append((date_str, share_rec))
        elif equal_fn(local_rec, share_rec):
            untouched.append(date_str)
        else:
            conflicts.append((date_str, local_rec, share_rec))

    return {
        "additions": additions,
        "conflicts": conflicts,
        "untouched": untouched,
        "out_of_range": out_of_range,
    }


def diff_share_against_local(share_entries, storage, date_from=None, date_to=None):
    """Arbeitszeiten-Diff (Wrapper, unverändertes Verhalten)."""
    return _diff_records(
        share_entries, storage.get_all(), _entries_equal, date_from, date_to)


def diff_reservations_against_local(share_reservations, reservation_store,
                                    date_from=None, date_to=None):
    """Reservierungs-Diff gegen den ReservationStore-Snapshot ({date:{start,end}})."""
    return _diff_records(
        share_reservations, reservation_store.get_all(),
        _reservations_equal, date_from, date_to)


def apply_reservation_import(reservation_store, decisions):
    """Schreibt importierte Reservierungen in den Store. save() setzt
    modified_at neu und behält eine vorhandene gcal_event_id, sodass der
    nächste Kalender-Reconcile das Event aktualisiert statt zu duplizieren."""
    for d in decisions:
        entry = d["entry"]
        reservation_store.save(d["date"], entry["start"], entry["end"])
```

Hinweis: Die alte Implementierung von `diff_share_against_local` (mit eigener Schleife) komplett entfernen — sie wird durch den Wrapper oben ersetzt. `_entries_equal` bleibt unverändert bestehen.

- [ ] **Step 4: Tests laufen lassen — müssen grün sein**

Run: `pytest tests/test_share.py -q`
Expected: PASS (inkl. aller bestehenden Diff-Tests, die weiter über den Wrapper laufen).

- [ ] **Step 5: Commit**

```bash
git add src/share.py tests/test_share.py
git commit -m "feat(share): generalisierter diff + apply_reservation_import"
```

---

## Task 4: Send-Dialog mit Typ-Checkboxen (`share_dialog.py`)

**Files:**
- Modify: `src/dialogs/share_dialog.py`

Kein automatisierter Test (Tkinter-Dialog, wie im Repo üblich ungetestet). Verifikation manuell.

- [ ] **Step 1: `open_share_dialog` ersetzen**

Den gesamten Body von `open_share_dialog` in `src/dialogs/share_dialog.py` ersetzen. Neue Signatur mit `reservation_store=None`:

```python
def open_share_dialog(parent, storage, settings, base_path, reservation_store=None):
    credentials_path = os.path.join(base_path, "credentials.json")
    token_path = os.path.join(base_path, "token.json")

    if not os.path.exists(credentials_path):
        show_missing_credentials_dialog(parent, base_path)
        return

    entries = storage.get_all()
    reservations = (
        reservation_store.get_all() if reservation_store is not None else {})

    if not entries and not reservations:
        messagebox.showinfo(
            "Nichts zum Teilen",
            "Es sind weder Arbeitszeiten noch Reservierungen zum Teilen "
            "vorhanden.",
            parent=parent,
        )
        return

    dialog = tk.Toplevel(parent)
    dialog.title("Teilen")
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.focus_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)
    disable_min_max(dialog)
    apply_app_icon(dialog)
    attach_unfocus_on_click(dialog)
    dialog.bind("<Escape>", lambda _e: dialog.destroy())

    row = 0
    tk.Label(
        dialog, text="Was möchtest Du teilen?", font=FONT, bg=BG, fg=TEXT,
    ).grid(row=row, column=0, columnspan=2, padx=20, pady=(20, 6), sticky="w")
    row += 1

    include_entries_var = tk.BooleanVar(value=bool(entries))
    cb_entries = tk.Checkbutton(
        dialog, text=f"Arbeitszeiten ({len(entries)} Tage)",
        variable=include_entries_var,
        font=FONT, bg=BG, fg=TEXT, selectcolor=BG,
        activebackground=BG, activeforeground=TEXT,
    )
    if not entries:
        include_entries_var.set(False)
        cb_entries.config(state="disabled")
    cb_entries.grid(row=row, column=0, columnspan=2, padx=20, pady=0, sticky="w")
    row += 1

    include_res_var = tk.BooleanVar(value=bool(reservations))
    cb_res = tk.Checkbutton(
        dialog, text=f"Reservierungen ({len(reservations)} Tage)",
        variable=include_res_var,
        font=FONT, bg=BG, fg=TEXT, selectcolor=BG,
        activebackground=BG, activeforeground=TEXT,
    )
    if not reservations:
        include_res_var.set(False)
        cb_res.config(state="disabled")
    cb_res.grid(row=row, column=0, columnspan=2, padx=20, pady=(0, 12), sticky="w")
    row += 1

    tk.Label(
        dialog, text="Empfänger:", font=FONT, bg=BG, fg=TEXT,
    ).grid(row=row, column=0, padx=(20, 6), pady=(0, 4), sticky="w")

    recipient_var = tk.StringVar(value=settings.get("share_recipient") or "")
    recipient_entry = dark_entry(dialog, recipient_var, width=35)
    recipient_entry.grid(row=row, column=1, padx=(0, 20), pady=(0, 4), sticky="w")
    row += 1

    save_default_var = tk.BooleanVar(value=False)
    tk.Checkbutton(
        dialog,
        text="Als Standard-Empfänger speichern",
        variable=save_default_var,
        font=FONT, bg=BG, fg=TEXT, selectcolor=BG,
        activebackground=BG, activeforeground=TEXT,
    ).grid(row=row, column=0, columnspan=2, padx=20, pady=(0, 12), sticky="w")
    row += 1

    def do_send():
        want_entries = include_entries_var.get()
        want_res = include_res_var.get()
        if not want_entries and not want_res:
            messagebox.showerror(
                "Nichts ausgewählt",
                "Bitte mindestens einen Datentyp zum Teilen auswählen.",
                parent=dialog,
            )
            return
        share_recipient = recipient_var.get().strip()
        if not share_recipient:
            messagebox.showerror(
                "Empfänger fehlt",
                "Bitte eine E-Mail-Adresse angeben.",
                parent=dialog,
            )
            return
        sender_email = settings.get("sender_email") or ""
        display_name = settings.get("name") or sender_email or "anonym"
        try:
            doc = build_share_doc(
                storage, sender_email,
                reservation_store=reservation_store,
                include_entries=want_entries,
                include_reservations=want_res,
            )
            payload = serialize_share_doc(doc)
            service = mail.get_gmail_service(
                credentials_path, token_path,
                sync_enabled=settings.get("sync_enabled"),
                gcal_enabled=settings.get("gcal_enabled"),
            )
            parts = []
            if want_entries:
                parts.append("Arbeitszeiten")
            if want_res:
                parts.append("Reservierungen")
            what = " und ".join(parts)
            subject = f"{what} geteilt von {display_name}"
            html = (
                "<html><head><meta charset=\"utf-8\"></head><body>"
                "<p>Hallo,</p>"
                f"<p>im Anhang findest Du meine {what} als JSON-Datei.</p>"
                "<p>Du kannst die Datei in der Zeiterfassung-App über "
                "<em>Einstellungen → Daten importieren…</em> einlesen. "
                "Vor dem Import kannst Du einen Zeitraum auswählen und je "
                "Datentyp festlegen, was bei Konflikten passieren soll.</p>"
                f"<p>Viele Grüße<br/>{display_name}</p>"
                "</body></html>"
            )
            filename = (
                "zeiterfassung-share-"
                f"{doc['exported_at'][:10].replace('-', '')}.json"
            )
            mail.send_email(
                service, share_recipient, subject, html,
                attachment_bytes=payload,
                attachment_filename=filename,
                attachment_subtype="json",
            )
            if save_default_var.get():
                settings.set("share_recipient", share_recipient)
            dialog.destroy()
            themed_showinfo(
                parent,
                "Geteilt",
                f"{what} wurden an {share_recipient} gesendet.",
            )
        except FileNotFoundError as e:
            messagebox.showerror("Fehler", str(e), parent=dialog)
        except Exception as e:
            logging.getLogger(__name__).exception("Teilen fehlgeschlagen")
            if mail.is_offline_error(e):
                messagebox.showerror(
                    "Keine Internetverbindung",
                    "Die Daten konnten nicht gesendet werden, weil keine "
                    "Verbindung zum Internet besteht.\n\n"
                    "Bitte prüfe deine Internetverbindung und versuche es "
                    "dann erneut.",
                    parent=dialog,
                )
            else:
                messagebox.showerror(
                    "Teilen fehlgeschlagen",
                    f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                    parent=dialog,
                )

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=row, column=0, columnspan=2, pady=(0, 16))

    primary_button(btn_frame, "Senden", do_send).pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    center_dialog_on_parent(dialog, parent)
```

- [ ] **Step 2: Import-Check**

Run: `python -c "import src.dialogs.share_dialog"`
Expected: kein Fehler (Syntax/Imports ok).

- [ ] **Step 3: Commit**

```bash
git add src/dialogs/share_dialog.py
git commit -m "feat(share-dialog): typ-auswahl arbeitszeiten/reservierungen beim teilen"
```

---

## Task 5: Import-Dialog mit Abschnitt pro Typ (`import_dialog.py`)

**Files:**
- Modify: `src/dialogs/import_dialog.py` (kompletter Ersatz)

Kein automatisierter Test (Tkinter). Verifikation manuell.

- [ ] **Step 1: `import_dialog.py` komplett ersetzen**

Den gesamten Inhalt von `src/dialogs/import_dialog.py` durch folgendes ersetzen:

```python
"""Modal-Dialog „Daten importieren": Datei-Pick, je Datentyp
(Arbeitszeiten/Reservierungen) ein Abschnitt mit Master-Schalter, Zeitraum-
Filter und Konflikt-Modi, optional Pro-Tag-Modal, atomarer Apply."""

import calendar
import datetime
import logging
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox

from src.share import (
    ShareValidationError,
    apply_import,
    apply_reservation_import,
    diff_reservations_against_local,
    diff_share_against_local,
    parse_share_doc,
)
from src.theme import (
    BG, CELL_BG, FONT, FONT_SMALL, TEXT, TEXT_MUTED,
    apply_app_icon, apply_combobox_style, apply_dark_titlebar,
    attach_unfocus_on_click, center_dialog_on_parent, disable_min_max,
    dark_combo, primary_button, secondary_button, themed_showinfo,
)


def open_import_dialog(parent, storage, settings, on_change, reservation_store=None):
    """Startet den Import-Flow. on_change wird bei erfolgreichem Apply
    aufgerufen. reservation_store=None → Reservierungen werden ignoriert."""
    path = filedialog.askopenfilename(
        parent=parent,
        title="Share-Datei auswählen",
        filetypes=[("Zeiterfassung Share", "*.json"), ("Alle Dateien", "*.*")],
    )
    if not path:
        return

    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        messagebox.showerror(
            "Datei nicht lesbar", f"{type(e).__name__}: {e}", parent=parent)
        return

    try:
        doc = parse_share_doc(raw)
    except ShareValidationError as e:
        messagebox.showerror(
            "Datei ungültig",
            f"Die Datei kann nicht importiert werden:\n\n{e.reason}",
            parent=parent,
        )
        return

    entries = doc.get("entries") or {}
    reservations = doc.get("reservations") or {}
    if reservation_store is None:
        reservations = {}

    if not entries and not reservations:
        messagebox.showinfo(
            "Leere Datei",
            "Die Datei enthält keine importierbaren Daten.",
            parent=parent,
        )
        return

    all_dates = sorted(
        datetime.date.fromisoformat(d)
        for d in (set(entries.keys()) | set(reservations.keys()))
    )
    file_min, file_max = all_dates[0], all_dates[-1]

    _ImportSummaryDialog(
        parent, storage, reservation_store, settings, doc,
        entries, reservations, file_min, file_max, on_change,
    ).show()


class _ImportSummaryDialog:
    def __init__(self, parent, storage, reservation_store, settings, doc,
                 entries, reservations, file_min, file_max, on_change):
        self.parent = parent
        self.storage = storage
        self.reservation_store = reservation_store
        self.settings = settings
        self.doc = doc
        self.file_min = file_min
        self.file_max = file_max
        self.on_change = on_change

        self.sections = []
        if entries:
            self.sections.append(self._make_section("entries", "Arbeitszeiten", entries, True))
        if reservations:
            self.sections.append(self._make_section("reservations", "Reservierungen", reservations, False))

        self.top = tk.Toplevel(parent)
        self.top.title("Daten importieren")
        self.top.resizable(False, False)
        self.top.grab_set()
        self.top.focus_set()
        self.top.configure(bg=BG)
        apply_dark_titlebar(self.top)
        disable_min_max(self.top)
        apply_app_icon(self.top)
        apply_combobox_style(self.top)
        attach_unfocus_on_click(self.top)
        self.top.bind("<Escape>", lambda _e: self.top.destroy())

        self._build()
        center_dialog_on_parent(self.top, parent)

    @staticmethod
    def _make_section(key, label, records, has_pause):
        return {
            "key": key,
            "label": label,
            "records": records,
            "has_pause": has_pause,
            "enabled": tk.BooleanVar(value=True),
            "mode": tk.StringVar(value="import"),
            "counts_label": None,
            "radios": [],
        }

    def show(self):
        self.top.wait_window()

    def _diff_for(self, section, d_from, d_to):
        if section["key"] == "entries":
            return diff_share_against_local(section["records"], self.storage, d_from, d_to)
        return diff_reservations_against_local(
            section["records"], self.reservation_store, d_from, d_to)

    def _build(self):
        row = 0
        tk.Label(
            self.top,
            text=f"Datei: zeiterfassung-share (geteilt von "
                 f"{self.doc.get('exported_by') or 'unbekannt'})",
            font=FONT, bg=BG, fg=TEXT, justify="left",
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(10, 4), sticky="w")
        row += 1

        tk.Label(
            self.top,
            text=f"Exportiert: {self.doc.get('exported_at', '')}",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, justify="left",
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(0, 10), sticky="w")
        row += 1

        tk.Label(
            self.top, text="Zeitraum filtern:", font=FONT, bg=BG, fg=TEXT,
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(4, 0), sticky="w")
        row += 1

        self.from_day, self.from_month, self.from_year = self._build_date_row(
            row, "Von:", self.file_min)
        row += 1
        self.to_day, self.to_month, self.to_year = self._build_date_row(
            row, "Bis:", self.file_max)
        row += 1

        tk.Label(
            self.top,
            text=f"Voller Bereich der Datei: "
                 f"{self.file_min.isoformat()} bis {self.file_max.isoformat()}",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(0, 8), sticky="w")
        row += 1

        for section in self.sections:
            tk.Checkbutton(
                self.top, text=f"{section['label']} importieren",
                variable=section["enabled"], command=self._on_toggle_section,
                font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT,
            ).grid(row=row, column=0, columnspan=6, padx=10, pady=(10, 0), sticky="w")
            row += 1

            counts = tk.Label(self.top, text="", font=FONT, bg=BG, fg=TEXT, justify="left")
            counts.grid(row=row, column=0, columnspan=6, padx=24, pady=(2, 2), sticky="w")
            section["counts_label"] = counts
            row += 1

            tk.Label(
                self.top, text="Konflikt-Behandlung:", font=FONT_SMALL,
                bg=BG, fg=TEXT_MUTED,
            ).grid(row=row, column=0, columnspan=6, padx=24, pady=(2, 0), sticky="w")
            row += 1

            section["radios"] = []
            for mode_value, mode_label in [
                ("import", "Alles vom Import übernehmen"),
                ("local", "Alles lokal behalten"),
                ("per_day", "Pro Tag entscheiden"),
            ]:
                rb = tk.Radiobutton(
                    self.top, text=mode_label, variable=section["mode"],
                    value=mode_value, font=FONT_SMALL, bg=BG, fg=TEXT,
                    selectcolor=CELL_BG, activebackground=BG, activeforeground=TEXT,
                )
                rb.grid(row=row, column=0, columnspan=6, padx=40, pady=0, sticky="w")
                section["radios"].append(rb)
                row += 1

        if (any(s["key"] == "reservations" for s in self.sections)
                and not self.settings.get("gcal_enabled")):
            tk.Label(
                self.top,
                text="Hinweis: Reservierungen werden sichtbar und mit dem "
                     "Kalender\nabgeglichen, sobald der Google-Kalender-Sync "
                     "in den Einstellungen aktiviert ist.",
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, justify="left",
            ).grid(row=row, column=0, columnspan=6, padx=10, pady=(8, 4), sticky="w")
            row += 1

        btn_frame = tk.Frame(self.top, bg=BG)
        btn_frame.grid(row=row, column=0, columnspan=6, pady=12)
        primary_button(btn_frame, "Weiter", self._on_next).pack(side=tk.LEFT, padx=5)
        secondary_button(btn_frame, "Abbrechen", self.top.destroy).pack(side=tk.LEFT, padx=5)

        self._on_toggle_section()
        self._recompute_counts()

    def _build_date_row(self, row, label_text, default_date):
        tk.Label(self.top, text=label_text, font=FONT, bg=BG, fg=TEXT).grid(
            row=row, column=0, padx=(10, 5), pady=4, sticky="w")

        day_var = tk.StringVar(value=str(default_date.day))
        max_day = calendar.monthrange(default_date.year, default_date.month)[1]
        day_cb = dark_combo(self.top, day_var,
                            [str(d) for d in range(1, max_day + 1)], width=3)
        day_cb.grid(row=row, column=1, padx=2, pady=4)

        tk.Label(self.top, text=".", font=FONT, bg=BG, fg=TEXT).grid(row=row, column=2)

        month_var = tk.StringVar(value=str(default_date.month))
        dark_combo(self.top, month_var,
                   [str(m) for m in range(1, 13)], width=3).grid(
            row=row, column=3, padx=2, pady=4)

        tk.Label(self.top, text=".", font=FONT, bg=BG, fg=TEXT).grid(row=row, column=4)

        year_var = tk.StringVar(value=str(default_date.year))
        years = [str(y) for y in range(2020, datetime.date.today().year + 2)]
        dark_combo(self.top, year_var, years, width=5).grid(
            row=row, column=5, padx=(2, 10), pady=4)

        def _on_change(*_):
            try:
                m = int(month_var.get())
                y = int(year_var.get())
                max_day = calendar.monthrange(y, m)[1]
            except (ValueError, KeyError):
                max_day = 31
            day_cb["values"] = [str(d) for d in range(1, max_day + 1)]
            try:
                if int(day_var.get()) > max_day:
                    day_var.set(str(max_day))
            except ValueError:
                pass
            self._recompute_counts()

        day_var.trace_add("write", _on_change)
        month_var.trace_add("write", _on_change)
        year_var.trace_add("write", _on_change)

        return day_var, month_var, year_var

    def _get_range(self):
        try:
            d_from = datetime.date(
                int(self.from_year.get()), int(self.from_month.get()),
                int(self.from_day.get()))
            d_to = datetime.date(
                int(self.to_year.get()), int(self.to_month.get()),
                int(self.to_day.get()))
        except ValueError:
            return None, None
        if d_from > d_to:
            return None, None
        return d_from, d_to

    def _on_toggle_section(self):
        for section in self.sections:
            state = "normal" if section["enabled"].get() else "disabled"
            for rb in section["radios"]:
                rb.config(state=state)
        self._recompute_counts()

    def _recompute_counts(self):
        d_from, d_to = self._get_range()
        for section in self.sections:
            label = section["counts_label"]
            if label is None:
                continue
            if not section["enabled"].get():
                label.config(text="(übersprungen)", fg=TEXT_MUTED)
                continue
            if d_from is None:
                label.config(text="(Von-Datum muss vor Bis-Datum liegen)", fg=TEXT_MUTED)
                continue
            diff = self._diff_for(section, d_from, d_to)
            label.config(
                text=(
                    f"• {len(diff['additions'])} neu  "
                    f"• {len(diff['conflicts'])} Konflikte  "
                    f"• {len(diff['untouched'])} identisch  "
                    f"• {diff['out_of_range']} außerhalb"
                ),
                fg=TEXT,
            )

    def _on_next(self):
        d_from, d_to = self._get_range()
        if d_from is None:
            messagebox.showerror(
                "Ungültiger Zeitraum",
                "Das Von-Datum muss vor dem Bis-Datum liegen.",
                parent=self.top,
            )
            return

        planned = []  # list of (apply_fn, decisions)
        for section in self.sections:
            if not section["enabled"].get():
                continue
            diff = self._diff_for(section, d_from, d_to)
            if not diff["additions"] and not diff["conflicts"]:
                continue
            mode = section["mode"].get()
            if mode == "import":
                decisions = self._decisions_from(diff, take_import_for_conflicts=True)
            elif mode == "local":
                decisions = self._decisions_from(diff, take_import_for_conflicts=False)
            else:  # per_day
                if not diff["conflicts"]:
                    decisions = self._decisions_from(diff, take_import_for_conflicts=True)
                else:
                    decisions = _PerDayDialog(
                        self.top, diff, section["label"], section["has_pause"]).show()
                    if decisions is None:
                        return  # Abbruch → atomar nichts tun
            if not decisions:
                continue
            if section["key"] == "entries":
                planned.append((lambda dec: apply_import(self.storage, dec), decisions))
            else:
                planned.append((lambda dec: apply_reservation_import(self.reservation_store, dec), decisions))

        if not planned:
            messagebox.showinfo(
                "Nichts zu importieren",
                "Im gewählten Zeitraum gibt es nichts zu übernehmen.",
                parent=self.top,
            )
            return

        self._apply(planned)

    @staticmethod
    def _decisions_from(diff, *, take_import_for_conflicts):
        decisions = [{"date": d, "entry": e} for d, e in diff["additions"]]
        if take_import_for_conflicts:
            decisions += [
                {"date": d, "entry": s} for d, _local, s in diff["conflicts"]
            ]
        return decisions

    def _apply(self, planned):
        total = 0
        try:
            for apply_fn, decisions in planned:
                apply_fn(decisions)
                total += len(decisions)
        except Exception as e:
            logging.getLogger(__name__).exception("Import fehlgeschlagen")
            messagebox.showerror(
                "Import fehlgeschlagen",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=self.top,
            )
            return
        self.on_change()
        self.top.destroy()
        themed_showinfo(
            self.parent,
            "Importiert",
            f"{total} Einträge wurden importiert.",
        )


class _PerDayDialog:
    """Modal mit Pro-Tag-Wahl (lokal vs. import). Liefert decisions oder None
    bei Abbruch. has_pause steuert die Anzeige der Pause (Reservierungen ohne)."""

    def __init__(self, parent, diff, type_label="Arbeitszeiten", has_pause=True):
        self.diff = diff
        self.has_pause = has_pause
        self._result = None

        self.top = tk.Toplevel(parent)
        self.top.title(f"Pro Tag entscheiden — {type_label}")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.focus_set()
        self.top.configure(bg=BG)
        apply_dark_titlebar(self.top)
        disable_min_max(self.top)
        apply_app_icon(self.top)
        self.top.bind("<Escape>", lambda _e: self.top.destroy())

        self._build()
        center_dialog_on_parent(self.top, parent)

    def show(self):
        self.top.wait_window()
        return self._result

    def _fmt(self, rec):
        if self.has_pause:
            return f"{rec['start']}—{rec['end']} (P{rec.get('pause', 0)})"
        return f"{rec['start']}—{rec['end']}"

    def _build(self):
        tk.Label(
            self.top, text="Wähle pro Tag, was übernommen werden soll:",
            font=FONT, bg=BG, fg=TEXT,
        ).pack(padx=10, pady=(10, 4), anchor="w")

        canvas = tk.Canvas(self.top, bg=BG, highlightthickness=0, height=320)
        scrollbar = tk.Scrollbar(self.top, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0))
        scrollbar.pack(side="right", fill="y")

        list_frame = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=list_frame, anchor="nw")

        self.choices = {}
        for i, (date, local, shared) in enumerate(self.diff["conflicts"]):
            var = tk.StringVar(value="L")
            self.choices[date] = var

            tk.Label(
                list_frame, text=date, font=FONT, bg=BG, fg=TEXT, width=12, anchor="w",
            ).grid(row=i, column=0, padx=4, pady=2, sticky="w")

            tk.Label(
                list_frame, text=f"Lokal: {self._fmt(local)}",
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, anchor="w",
            ).grid(row=i, column=1, padx=4, pady=2, sticky="w")

            tk.Label(
                list_frame, text=f"Import: {self._fmt(shared)}",
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, anchor="w",
            ).grid(row=i, column=2, padx=4, pady=2, sticky="w")

            tk.Radiobutton(
                list_frame, text="lokal", variable=var, value="L",
                font=FONT_SMALL, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT,
            ).grid(row=i, column=3, padx=2, pady=0)
            tk.Radiobutton(
                list_frame, text="import", variable=var, value="I",
                font=FONT_SMALL, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT,
            ).grid(row=i, column=4, padx=2, pady=0)

        list_frame.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

        btn_frame = tk.Frame(self.top, bg=BG)
        btn_frame.pack(pady=10)

        secondary_button(
            btn_frame, "Alle auf Import",
            lambda: [v.set("I") for v in self.choices.values()],
        ).pack(side=tk.LEFT, padx=4)
        secondary_button(
            btn_frame, "Alle auf Lokal",
            lambda: [v.set("L") for v in self.choices.values()],
        ).pack(side=tk.LEFT, padx=4)
        primary_button(btn_frame, "Anwenden", self._on_apply).pack(side=tk.LEFT, padx=4)
        secondary_button(btn_frame, "Abbrechen", self.top.destroy).pack(side=tk.LEFT, padx=4)

    def _on_apply(self):
        decisions = [{"date": d, "entry": e} for d, e in self.diff["additions"]]
        for date, _local, shared in self.diff["conflicts"]:
            if self.choices[date].get() == "I":
                decisions.append({"date": date, "entry": shared})
        self._result = decisions
        self.top.destroy()
```

- [ ] **Step 2: Import-Check**

Run: `python -c "import src.dialogs.import_dialog"`
Expected: kein Fehler.

- [ ] **Step 3: Commit**

```bash
git add src/dialogs/import_dialog.py
git commit -m "feat(import-dialog): abschnitt je datentyp mit master-schalter + konflikt-modi"
```

---

## Task 6: Plumbing — `reservation_store` durchreichen

**Files:**
- Modify: `src/ui.py` (`_share`, Settings-Aufruf ~Z. 515)
- Modify: `src/dialogs/settings_dialog.py` (`open_settings_dialog`, `_open_import_dialog`)

- [ ] **Step 1: `ui.py::_share` anpassen**

In `src/ui.py` die Methode `_share` ersetzen:

```python
    def _share(self):
        from src.dialogs.share_dialog import open_share_dialog
        open_share_dialog(
            self.root, self.storage, self.settings, self.base_path,
            reservation_store=self.reservation_store,
        )
```

- [ ] **Step 2: `ui.py` Settings-Aufruf anpassen**

In `src/ui.py` den `open_settings_dialog(...)`-Aufruf (um Zeile 515) um `reservation_store` ergänzen:

```python
        open_settings_dialog(
            self.root, self.settings, self.base_path,
            on_change=_on_change,
            conflicts_store=self.conflicts_store,
            storage=self.storage,
            reservation_store=self.reservation_store,
        )
```

- [ ] **Step 3: `settings_dialog.py` Signatur + Weitergabe anpassen**

In `src/dialogs/settings_dialog.py` die Signatur erweitern:

```python
def open_settings_dialog(parent, settings, base_path, on_change, *,
                         conflicts_store=None, storage=None,
                         reservation_store=None):
```

Und in `_open_import_dialog` den Store durchreichen:

```python
    def _open_import_dialog():
        from src.dialogs.import_dialog import open_import_dialog

        def _after_import():
            on_change()
            dialog.destroy()

        open_import_dialog(
            dialog, storage, settings, _after_import,
            reservation_store=reservation_store,
        )
```

Außerdem den Button-Text neutralisieren (von „Arbeitszeiten importieren…" auf „Daten importieren…"):

```python
    if storage is not None:
        secondary_button(
            dialog,
            "Daten importieren…",
            _open_import_dialog,
            padx=12, pady=2,
        ).grid(row=26, column=0, columnspan=2, padx=10, pady=(4, 8), sticky="w")
```

- [ ] **Step 4: Import-/Smoke-Check**

Run: `python -c "import src.ui, src.dialogs.settings_dialog, src.dialogs.import_dialog, src.dialogs.share_dialog"`
Expected: kein Fehler.

Run: `pytest -q`
Expected: PASS (alle Tests, inkl. der neuen Share-Tests).

- [ ] **Step 5: Commit**

```bash
git add src/ui.py src/dialogs/settings_dialog.py
git commit -m "feat(plumbing): reservation_store an share- und import-dialog durchreichen"
```

---

## Task 7: Manuelle End-to-End-Verifikation

**Files:** keine Änderung — nur Verifikation.

- [ ] **Step 1: App im Dev-Modus starten**

Run: `python -m src.main --dev`
Expected: App startet ohne Fehler.

- [ ] **Step 2: Senden prüfen**

Im Menü „Teilen" öffnen. Erwartung:
- Zwei Checkboxen „Arbeitszeiten (N Tage)" und „Reservierungen (M Tage)".
- Boxen ohne Daten sind ausgegraut und nicht angehakt.
- Ohne Auswahl → „Senden" zeigt „Nichts ausgewählt".

- [ ] **Step 3: Datei erzeugen und importieren**

Eine Share-Datei mit beiden Typen senden (oder vorab eine v2-JSON von Hand erstellen), dann „Einstellungen → Daten importieren…" öffnen. Erwartung:
- Je vorhandenem Typ ein Abschnitt mit Master-Schalter + Konflikt-Modi.
- Master-Schalter aus → Radios des Abschnitts ausgegraut, Counts zeigen „(übersprungen)".
- Bei deaktiviertem Kalender-Sync erscheint der Reservierungs-Hinweis.
- „Weiter" mit „Pro Tag" bei Konflikten öffnet das Pro-Tag-Modal (Reservierungs-Modal ohne Pause-Anzeige).
- Nach Apply zeigt der Kalender importierte Reservierungen (bei aktivem Sync).

- [ ] **Step 4: Abschluss-Commit (falls Doku-Updates nötig)**

Keine zwingende Änderung. Falls README/CHANGELOG erwähnt werden soll, separat committen.

---

## Self-Review-Ergebnis

- **Spec-Abdeckung:** Wire-Format v2 + v1-Lesen (Task 1), Diff-Generalisierung + Apply (Task 3), Send-Typauswahl (Task 4), symmetrischer Import mit optionalen Master-Schaltern (Task 5), gcal-aus-Hinweis (Task 5), Plumbing (Task 6). Alle Spec-Abschnitte abgedeckt.
- **Platzhalter:** keine.
- **Typ-Konsistenz:** Decisions nutzen durchgehend `{"date", "entry"}`; `apply_import`/`apply_reservation_import` lesen dieselbe Form; Diff-Rückgabe-Schlüssel (`additions`/`conflicts`/`untouched`/`out_of_range`) konsistent zwischen Kern und Wrappern.
