# AP3 — entry_dialog Multi-Slot + Non-Overlap-Validierung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den Tages-Dialog (`src/dialogs/entry_dialog.py`) auf mehrere Timeslots pro Tag (Ist-Zeit und Reservierung) mit Kategorie je Slot umstellen, und die Slot-Validierung (Per-Slot + zeitliche Überlappungsfreiheit) als pure, getestete Funktion in `src/time_utils.py` bereitstellen.

**Architecture:** Die testbare Logik (`validate_slots`) lebt in `time_utils`. Der Dialog ist eine dünne Tkinter-Schicht: dynamische Slot-Zeilen (hinzufügen/entfernen), Kategorie je Zeile, sammelt beim Speichern eine Slot-Liste, ruft `validate_slots` und schreibt via die AP1-Slot-API (`storage.save(date, slots)` / `reservation_store.save(date, slots)`).

**Tech Stack:** Python stdlib, tkinter, pytest. Keine neuen Dependencies.

## Global Constraints

- **Non-Overlap:** Slots eines Blocks dürfen sich **zeitlich nicht überlappen** — getrennt geprüft für Ist-Zeit-Slots bzw. Reservierungs-Slots (die beiden Blöcke dürfen sich gegenseitig überlagern). Angrenzend (Ende == Start des nächsten) ist **erlaubt**.
- **Slot-Schemata:** Ist-Zeit-Slot `{start, end, pause, kategorie}`; Reservierungs-Slot `{start, end, kategorie}` (kein `pause`).
- **Kategorie** ist Freitext (String), `""` = keine. Auswahlvorschläge kommen aus `settings.get("categories")`.
- **Lösch-Modell (CLAUDE.md):** Der Dialog ist auf Win/Linux rein zum Speichern — **kein** Lösch-Button. Entfernen aller Zeilen eines Blocks + Speichern = dieser Block wird gelöscht (`storage.delete` / `reservation_store.delete`) — das ist Editieren, kein zweiter Lösch-Pfad. **macOS-Ausnahme:** behält die expliziten „Löschen"/„Reservierung löschen"-Buttons (`_SHOW_DELETE_IN_DIALOG = platform.system() == "Darwin"`).
- **AP1-Slot-API:** `storage.save(date, slots)`, `storage.get(date) -> {"slots":[...]}|None`, `storage.delete(date)`; `reservation_store.save(date, slots)`, `reservation_store.get(date) -> {"slots":[{start,end,kategorie}]}|None`, `reservation_store.delete(date)`.
- **Reservierungs-Slot ohne gcal_event_id im Dialog:** Der Dialog liefert nur `{start,end,kategorie}`. Das Event-Mapping (gcal_event_id) macht der Reconcile (AP7) — der Dialog setzt es nicht.
- **Datumsformat:** intern ISO; UI deutsch (Dialog-Titel bleibt `%d.%m.%Y`).
- **Harter Schnitt (laufend):** Nur AP3-Dateien werden angepasst. Consumer außerhalb (report, share, ui, gcal) bleiben rot bis zu ihren Paketen.

## Test-Strategie / Design-Notes (für den Plan-Review)

- **`time_utils.validate_slots` ist voll unit-getestet** (Task 1).
- **`entry_dialog.py` hat KEINE automatisierten Tests** — bewusst, konsistent mit dem Projekt: Tkinter-Widgets brauchen ein Display und laufen in der CI (ubuntu, `test.yml` ohne xvfb) nicht; es gibt im Repo keine Widget-Tests für Dialoge. Verifikation von Task 2 = (a) Import-Smoke (`python -c "import src.dialogs.entry_dialog"`), (b) Diff-Review, (c) **manueller lokaler Test** durch den Nutzer vor dem PR. Das ist im Plan-Review zur Abnahme markiert.
- **„Alle Zeilen entfernt + Speichern = Block löschen":** bewusste Save-Semantik (kein zusätzlicher Lösch-Button auf Win/Linux). Im Plan-Review zur Abnahme markiert.
- **`dark_combo_editable`** ist ein neuer, kleiner Theme-Helfer (editierbare Combobox), nötig weil die Kategorie-Verwaltung erst in AP6 kommt — bis dahin muss man Kategorien im Dialog per Freitext anlegen können.

---

## Dateistruktur

- `src/time_utils.py` — neue pure Helfer `slots_overlap`, `validate_slots`. Verantwortung (Zeit-Mathematik/Validierung) unverändert.
- `src/theme.py` — neuer Helfer `dark_combo_editable` (editierbare Combobox).
- `src/dialogs/entry_dialog.py` — komplette Neufassung: dynamische Slot-Zeilen + Kategorie.
- `tests/test_time_calc.py` — Tests für `validate_slots`/`slots_overlap` (gleiche Datei wie die bestehenden `validate_entry`-Tests).

Task 1 (`time_utils` + Tests) ist unabhängig von Task 2 (Dialog + Theme-Helfer). Task 2 konsumiert `validate_slots` aus Task 1.

---

## Task 1: `time_utils` — `slots_overlap` + `validate_slots`

**Files:**
- Modify: `src/time_utils.py` (zwei neue Funktionen am Ende)
- Test: `tests/test_time_calc.py` (neue Tests anhängen)

**Interfaces:**
- Produces:
  - `slots_overlap(slots: list[dict]) -> bool` — True, wenn sich zwei Slots zeitlich überlappen. Slots mit unparsbarer Zeit werden übersprungen (separat per `validate_slots` abgefangen). Angrenzend (Ende==Start) ist KEINE Überlappung.
  - `validate_slots(slots: list[dict], with_pause: bool = True) -> tuple[bool, str]` — validiert jeden Slot (`validate_entry` auf `start`/`end`/`pause`; bei `with_pause=False` wird `pause=0` erzwungen) und die Überlappungsfreiheit. Leere Liste → `(True, "")`. Erste Fehlermeldung gewinnt.

- [ ] **Step 1: Failing-Tests an `tests/test_time_calc.py` anhängen**

Hänge ans Ende von `tests/test_time_calc.py` an:

```python


from src.time_utils import slots_overlap, validate_slots


def _s(start, end, pause=0, kategorie=""):
    return {"start": start, "end": end, "pause": pause, "kategorie": kategorie}


def test_slots_overlap_false_for_disjoint():
    assert slots_overlap([_s("08:00", "12:00"), _s("13:00", "17:00")]) is False


def test_slots_overlap_false_for_adjacent():
    # Ende == Start des nächsten ist erlaubt (angrenzend, nicht überlappend)
    assert slots_overlap([_s("08:00", "12:00"), _s("12:00", "17:00")]) is False


def test_slots_overlap_true_for_overlap():
    assert slots_overlap([_s("08:00", "13:00"), _s("12:00", "17:00")]) is True


def test_slots_overlap_detects_unsorted_input():
    # Reihenfolge egal: zweite Liste ist nicht nach start sortiert
    assert slots_overlap([_s("13:00", "17:00"), _s("08:00", "13:30")]) is True


def test_slots_overlap_ignores_unparsable_times():
    # Ein Slot mit kaputter Zeit wird übersprungen (validate_slots fängt ihn ab)
    assert slots_overlap([_s("abc", "xyz"), _s("08:00", "12:00")]) is False


def test_slots_overlap_empty_and_single():
    assert slots_overlap([]) is False
    assert slots_overlap([_s("08:00", "16:00")]) is False


def test_validate_slots_ok_single():
    ok, msg = validate_slots([_s("08:00", "16:30", 30)])
    assert ok is True
    assert msg == ""


def test_validate_slots_ok_multiple_disjoint():
    ok, _ = validate_slots([_s("08:00", "12:00", 0, "Büro"), _s("13:00", "17:00", 30, "HO")])
    assert ok is True


def test_validate_slots_empty_is_ok():
    assert validate_slots([]) == (True, "")


def test_validate_slots_rejects_overlap():
    ok, msg = validate_slots([_s("08:00", "13:00"), _s("12:00", "17:00")])
    assert ok is False
    assert "überlapp" in msg.lower()


def test_validate_slots_rejects_bad_slot():
    ok, msg = validate_slots([_s("17:00", "08:00")])  # Ende vor Start
    assert ok is False


def test_validate_slots_rejects_pause_too_big():
    ok, msg = validate_slots([_s("08:00", "09:00", 90)])  # Pause > Arbeitszeit
    assert ok is False


def test_validate_slots_without_pause_ignores_pause():
    # Reservierungs-Slots: pause wird ignoriert (with_pause=False), kein Pausenfehler
    ok, msg = validate_slots([_s("08:00", "09:00", 999)], with_pause=False)
    assert ok is True
```

- [ ] **Step 2: Tests laufen lassen — müssen FEHLSCHLAGEN**

Run: `python -m pytest tests/test_time_calc.py -q`
Expected: FAIL — `slots_overlap`/`validate_slots` existieren noch nicht (ImportError beim neuen `from src.time_utils import ...`).

- [ ] **Step 3: `src/time_utils.py` — Funktionen ergänzen**

Hänge ans Ende von `src/time_utils.py` an:

```python


def slots_overlap(slots):
    """True, wenn sich zwei Slots zeitlich überlappen.

    `slots`: Liste von Dicts mit 'start'/'end' (HH:MM). Slots mit unparsbarer
    Zeit werden übersprungen (Format-Fehler fängt validate_slots separat ab).
    Angrenzend (Ende == Start des nächsten) gilt NICHT als Überlappung.
    """
    intervals = []
    for s in slots:
        start = parse_time(s.get("start"))
        end = parse_time(s.get("end"))
        if start is None or end is None:
            continue
        intervals.append((start[0] * 60 + start[1], end[0] * 60 + end[1]))
    intervals.sort()
    for (_prev_start, prev_end), (next_start, _next_end) in zip(intervals, intervals[1:]):
        if next_start < prev_end:
            return True
    return False


def validate_slots(slots, with_pause=True):
    """Validiert eine Slot-Liste: jeden Slot einzeln (validate_entry) und die
    zeitliche Überlappungsfreiheit. Liefert (ok, fehlermeldung).

    with_pause=False (Reservierungen): das Pause-Feld wird ignoriert (als 0
    behandelt). Eine leere Liste ist gültig (ok, "")."""
    for s in slots:
        pause = int(s.get("pause", 0)) if with_pause else 0
        ok, msg = validate_entry(s.get("start"), s.get("end"), pause_minutes=pause)
        if not ok:
            return False, msg
    if slots_overlap(slots):
        return False, "Zeitslots dürfen sich zeitlich nicht überlappen."
    return True, ""
```

- [ ] **Step 4: Tests laufen lassen — müssen BESTEHEN**

Run: `python -m pytest tests/test_time_calc.py tests/test_time_utils.py -q`
Expected: PASS (alle Tests grün).

- [ ] **Step 5: Commit**

```bash
git add src/time_utils.py tests/test_time_calc.py
git commit -m "feat(time_utils): Slot-Validierung mit Non-Overlap (#53)

slots_overlap + validate_slots: prüfen jeden Slot (validate_entry) und die
zeitliche Überlappungsfreiheit (angrenzend erlaubt). with_pause=False für
Reservierungs-Slots. Teil von AP3.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `entry_dialog` Multi-Slot-Umschreibung (+ Theme-Helfer)

**Files:**
- Modify: `src/theme.py` (neuer Helfer `dark_combo_editable`, direkt nach `dark_combo`)
- Modify: `src/dialogs/entry_dialog.py` (komplette Neufassung, siehe Step 3)

**Interfaces:**
- Consumes: `time_utils.validate_slots` (Task 1); AP1-Slot-API (Storage/ReservationStore); `settings.get("categories")` (AP2).
- Produces: `dark_combo_editable(parent, textvariable, values, width=14, **kw) -> ttk.Combobox` (editierbar, Freitext + Vorschläge).
- Signatur von `open_entry_dialog` bleibt unverändert: `open_entry_dialog(parent, date_str, storage, settings, on_change, reservation_store=None, trigger_reconcile=None)`.

> **Keine automatisierten Tests** (Tkinter, kein Display in der CI; Projekt-Norm). Verifikation: Import-Smoke + Diff-Review + manueller lokaler Test.

- [ ] **Step 1: `src/theme.py` — `dark_combo_editable` ergänzen**

Füge in `src/theme.py` direkt **nach** der Funktion `dark_combo` (endet mit der schließenden `)` der `return ttk.Combobox(...)`) ein:

```python


def dark_combo_editable(parent, textvariable, values, width=14, **kw):
    """Wie dark_combo, aber editierbar (state="normal") — Freitext plus
    Vorschlagsliste. Für die Kategorie-Auswahl je Slot, deren Werte aus
    settings['categories'] kommen, aber auch frei eingetippt werden dürfen."""
    return ttk.Combobox(
        parent, textvariable=textvariable, values=values,
        width=width, font=FONT, style="Dark.TCombobox", state="normal", **kw,
    )
```

- [ ] **Step 2: Import-Smoke nach dem Theme-Helfer**

Run: `python -c "from src.theme import dark_combo_editable; print('ok')"`
Expected: gibt `ok` aus (kein ImportError).

- [ ] **Step 3: `src/dialogs/entry_dialog.py` neu schreiben**

Ersetze den **kompletten** Inhalt von `src/dialogs/entry_dialog.py` durch:

```python
import datetime
import platform
import tkinter as tk
from tkinter import messagebox

from src.holidays_de import get_holidays
from src.settings import WEEKDAY_KEYS
from src.theme import (
    BG, FONT, FONT_BOLD, PAUSE_VALUES, TEXT, TEXT_MUTED, TIME_VALUES,
    apply_app_icon, apply_combobox_style, apply_dark_titlebar,
    attach_unfocus_on_click, center_dialog_on_parent, dark_combo,
    dark_combo_editable, disable_min_max, primary_button, secondary_button,
    themed_askyesno,
)
from src.time_utils import validate_slots


# Löschen folgt im Kalender dem Muster „Linksklick = speichern, Rechtsklick =
# löschen". Der Dialog (Linksklick) ist daher rein zum Anlegen/Bearbeiten — die
# Lösch-Buttons sind dort raus. AUSNAHME macOS: Tkinters Maustasten-Nummerierung
# macht den Rechtsklick (`<Button-3>`) dort unzuverlässig; damit Löschen auf dem
# Mac überhaupt erreichbar bleibt, behält der Dialog dort seine Lösch-Buttons.
_SHOW_DELETE_IN_DIALOG = platform.system() == "Darwin"


def open_entry_dialog(parent, date_str, storage, settings, on_change,
                      reservation_store=None, trigger_reconcile=None):
    """Modaler Dialog zum Bearbeiten von Ist-Zeit und Reservierung eines Tages.

    Beide Blöcke führen eine Liste von Slot-Zeilen (Start/Ende/Pause/Kategorie
    bzw. Start/Ende/Kategorie). Speichern sammelt die Zeilen, validiert sie
    (validate_slots: pro Slot + Überlappungsfreiheit) und schreibt die Slot-
    Liste. Entfernt man alle Zeilen eines Blocks und speichert, wird der Block
    gelöscht — kein separater Lösch-Button (außer macOS).

    on_change wird nach erfolgreichem Speichern/Löschen aufgerufen.
    reservation_store / trigger_reconcile sind optional; ist der Tag
    heute/zukünftig (oder existiert bereits eine Reservierung), erscheint der
    Reservierungs-Block. trigger_reconcile() stößt den Kalender-Abgleich an.
    """
    entry = storage.get(date_str)
    day = datetime.date.fromisoformat(date_str)
    weekday_key = WEEKDAY_KEYS[day.weekday()]

    # Feiertags-Warnung beim Anlegen einer Ist-Zeit (nicht beim Edit).
    if entry is None:
        state = settings.get("state")
        if state:
            feiertage = get_holidays(state, day.year)
            if day in feiertage:
                date_de = day.strftime("%d.%m.%Y")
                confirm = themed_askyesno(
                    parent, "Feiertag",
                    f"Der {date_de} ist {feiertage[day]} (Feiertag).\n\n"
                    "Trotzdem Eintrag anlegen?",
                )
                if not confirm:
                    return

    existing_reservation = (
        reservation_store.get(date_str) if reservation_store is not None else None
    )
    show_reservation = reservation_store is not None and (
        day >= datetime.date.today() or existing_reservation is not None
    )

    categories = settings.get("categories") or []
    default_start = settings.get(f"default_start_{weekday_key}")
    default_end = settings.get(f"default_end_{weekday_key}")
    default_pause = settings.get("default_pause")

    dialog = tk.Toplevel(parent)
    dialog.title(day.strftime("%d.%m.%Y"))
    dialog.resizable(False, False)
    dialog.grab_set()
    # focus_set() ist nach grab_set() Pflicht, sonst feuern Tastatur-Bindungen
    # (z.B. Escape) am Dialog nie.
    dialog.focus_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)
    disable_min_max(dialog)
    apply_app_icon(dialog)
    apply_combobox_style(dialog)
    attach_unfocus_on_click(dialog)
    dialog.bind("<Escape>", lambda _e: dialog.destroy())

    outer = tk.Frame(dialog, bg=BG)
    outer.pack(padx=12, pady=12)

    # ---------- Ist-Zeit ----------
    tk.Label(outer, text="Arbeitszeit", font=FONT_BOLD, bg=BG, fg=TEXT).pack(anchor="w")
    ist_rows_frame = tk.Frame(outer, bg=BG)
    ist_rows_frame.pack(fill="x")
    ist_rows = []  # Liste von {frame, start, end, pause, kategorie}

    def add_ist_row(start, end, pause, kategorie):
        row = tk.Frame(ist_rows_frame, bg=BG)
        row.pack(fill="x", pady=2)
        sv = tk.StringVar(value=start)
        ev = tk.StringVar(value=end)
        pv = tk.StringVar(value=str(pause))
        kv = tk.StringVar(value=kategorie)
        dark_combo(row, sv, TIME_VALUES, width=6).pack(side=tk.LEFT, padx=2)
        tk.Label(row, text="–", font=FONT, bg=BG, fg=TEXT_MUTED).pack(side=tk.LEFT)
        dark_combo(row, ev, TIME_VALUES, width=6).pack(side=tk.LEFT, padx=2)
        dark_combo(row, pv, PAUSE_VALUES, width=4).pack(side=tk.LEFT, padx=2)
        dark_combo_editable(row, kv, categories, width=14).pack(side=tk.LEFT, padx=2)
        record = {"frame": row, "start": sv, "end": ev, "pause": pv, "kategorie": kv}

        def remove():
            row.destroy()
            ist_rows.remove(record)

        secondary_button(row, "×", remove, padx=8, pady=0).pack(side=tk.LEFT, padx=2)
        ist_rows.append(record)

    # Vorbelegung: vorhandene Ist-Slots → bestehende Reservierung (erste Slot-
    # Zeit) → Standardzeit des Wochentags.
    if entry and entry["slots"]:
        for s in entry["slots"]:
            add_ist_row(s["start"], s["end"], s.get("pause", 0), s.get("kategorie", ""))
    elif existing_reservation and existing_reservation["slots"]:
        first = existing_reservation["slots"][0]
        add_ist_row(first["start"], first["end"], default_pause, "")
    else:
        add_ist_row(default_start, default_end, default_pause, "")

    ist_btns = tk.Frame(outer, bg=BG)
    ist_btns.pack(fill="x", pady=(2, 8))
    secondary_button(
        ist_btns, "+ Slot",
        lambda: add_ist_row(default_start, default_end, 0, ""),
    ).pack(side=tk.LEFT, padx=2)

    def save_ist():
        slots = [{
            "start": r["start"].get(),
            "end": r["end"].get(),
            "pause": int(r["pause"].get() or 0),
            "kategorie": r["kategorie"].get().strip(),
        } for r in ist_rows]
        if not slots:
            storage.delete(date_str)
            dialog.destroy()
            on_change()
            return
        ok, msg = validate_slots(slots, with_pause=True)
        if not ok:
            messagebox.showerror("Fehler", msg, parent=dialog)
            return
        storage.save(date_str, slots)
        dialog.destroy()
        on_change()

    def delete_ist():
        storage.delete(date_str)
        dialog.destroy()
        on_change()

    ist_save = tk.Frame(outer, bg=BG)
    ist_save.pack(fill="x")
    primary_button(ist_save, "Speichern", save_ist).pack(side=tk.LEFT, padx=2)
    if entry is not None and _SHOW_DELETE_IN_DIALOG:
        secondary_button(ist_save, "Löschen", delete_ist).pack(side=tk.LEFT, padx=2)

    # ---------- Reservierung ----------
    if show_reservation:
        tk.Label(
            outer, text="— Reservierung —", font=FONT_BOLD, bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(12, 2))
        res_rows_frame = tk.Frame(outer, bg=BG)
        res_rows_frame.pack(fill="x")
        res_rows = []  # Liste von {frame, start, end, kategorie}

        def add_res_row(start, end, kategorie):
            row = tk.Frame(res_rows_frame, bg=BG)
            row.pack(fill="x", pady=2)
            sv = tk.StringVar(value=start)
            ev = tk.StringVar(value=end)
            kv = tk.StringVar(value=kategorie)
            dark_combo(row, sv, TIME_VALUES, width=6).pack(side=tk.LEFT, padx=2)
            tk.Label(row, text="–", font=FONT, bg=BG, fg=TEXT_MUTED).pack(side=tk.LEFT)
            dark_combo(row, ev, TIME_VALUES, width=6).pack(side=tk.LEFT, padx=2)
            dark_combo_editable(row, kv, categories, width=14).pack(side=tk.LEFT, padx=2)
            record = {"frame": row, "start": sv, "end": ev, "kategorie": kv}

            def remove():
                row.destroy()
                res_rows.remove(record)

            secondary_button(row, "×", remove, padx=8, pady=0).pack(side=tk.LEFT, padx=2)
            res_rows.append(record)

        if existing_reservation and existing_reservation["slots"]:
            for s in existing_reservation["slots"]:
                add_res_row(s["start"], s["end"], s.get("kategorie", ""))
        else:
            add_res_row(default_start, default_end, "")

        res_btns = tk.Frame(outer, bg=BG)
        res_btns.pack(fill="x", pady=(2, 8))
        secondary_button(
            res_btns, "+ Slot",
            lambda: add_res_row(default_start, default_end, ""),
        ).pack(side=tk.LEFT, padx=2)

        def save_reservation():
            slots = [{
                "start": r["start"].get(),
                "end": r["end"].get(),
                "kategorie": r["kategorie"].get().strip(),
            } for r in res_rows]
            if not slots:
                reservation_store.delete(date_str)
                dialog.destroy()
                on_change()
                if trigger_reconcile is not None:
                    trigger_reconcile()
                return
            ok, msg = validate_slots(slots, with_pause=False)
            if not ok:
                messagebox.showerror("Fehler", msg, parent=dialog)
                return
            reservation_store.save(date_str, slots)
            dialog.destroy()
            on_change()
            if trigger_reconcile is not None:
                trigger_reconcile()

        def delete_reservation():
            reservation_store.delete(date_str)
            dialog.destroy()
            on_change()
            if trigger_reconcile is not None:
                trigger_reconcile()

        res_save = tk.Frame(outer, bg=BG)
        res_save.pack(fill="x")
        primary_button(res_save, "Reservierung speichern",
                       save_reservation).pack(side=tk.LEFT, padx=2)
        if existing_reservation is not None and _SHOW_DELETE_IN_DIALOG:
            secondary_button(res_save, "Reservierung löschen",
                             delete_reservation).pack(side=tk.LEFT, padx=2)

    center_dialog_on_parent(dialog, parent)
```

- [ ] **Step 4: Import-Smoke + Byte-Compile**

Run: `python -c "import src.dialogs.entry_dialog; print('ok')"`
Expected: gibt `ok` aus (kein ImportError, keine SyntaxError).

Run: `python -m py_compile src/dialogs/entry_dialog.py src/theme.py src/time_utils.py`
Expected: keine Ausgabe, Exit 0.

- [ ] **Step 5: AP1–AP3-Regressionscheck (kein Rückschritt)**

Run: `python -m pytest tests/test_storage.py tests/test_storage_migration.py tests/test_reservations.py tests/test_reservations_migration.py tests/test_settings.py tests/test_sync.py tests/test_time_calc.py tests/test_time_utils.py -q`
Expected: PASS.

> **Hinweis:** Ein voller `pytest`-Lauf bleibt erwartbar rot (report/share/ui/gcal noch nicht angepasst). `entry_dialog.py` selbst hat keine automatisierten Tests — manueller Test durch den Nutzer vor dem PR.

- [ ] **Step 6: Manuelle Verifikations-Checkliste (für den lokalen Test des Nutzers, NICHT vom Implementer auszuführen)**

In den Report schreiben (als Hinweis an den Nutzer), nicht ausführen:
- Linksklick auf einen Tag öffnet den Dialog; Ist-Zeit zeigt eine Zeile (Vorbelegung).
- „+ Slot" fügt eine Zeile hinzu; „×" entfernt sie.
- Zwei sich überlappende Slots → „Speichern" zeigt Überlappungs-Fehler.
- Zwei angrenzende Slots (z.B. 08:00–12:00 und 12:00–17:00) speichern ok.
- Kategorie ist frei eintippbar und bietet `settings['categories']` als Vorschläge.
- Alle Ist-Zeit-Zeilen entfernen + Speichern löscht die Ist-Zeit des Tages.
- Reservierungs-Block analog (ohne Pause), nur bei heute/zukünftig bzw. bestehender Reservierung.

- [ ] **Step 7: Commit**

```bash
git add src/dialogs/entry_dialog.py src/theme.py
git commit -m "feat(ui): Tages-Dialog mit mehreren Slots + Kategorie je Slot (#53)

entry_dialog führt für Ist-Zeit und Reservierung je eine Liste von Slot-
Zeilen (hinzufügen/entfernen), Kategorie je Zeile (Freitext + Vorschläge aus
settings.categories). Speichern validiert via validate_slots (pro Slot +
Non-Overlap) und schreibt Slot-Listen über die AP1-API; alle Zeilen entfernt
+ Speichern löscht den Block. Neuer Theme-Helfer dark_combo_editable.
macOS behält seine Lösch-Buttons. Teil von AP3.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec-Coverage (Spec-Abschnitt „entry_dialog.py — dynamische Slot-Zeilen" + Validierung):**
- Ist-Zeit & Reservierung je Liste von Slot-Zeilen, Start/Ende/Pause/Kategorie bzw. Start/Ende/Kategorie → Task 2, Step 3 ✓
- „+ Slot hinzufügen" + „×" entfernen je Block → Task 2, Step 3 ✓
- Kategorie editierbar (Freitext + Vorschläge aus settings.categories) → `dark_combo_editable` + `categories` ✓
- Speichern validiert (pro Slot + Non-Overlap je Block) und schreibt Slot-Listen via AP1-API → `validate_slots` (Task 1) + `save_ist`/`save_reservation` ✓
- Non-Overlap getrennt je Block; angrenzend erlaubt → `slots_overlap` (Task 1) + getrennte `validate_slots`-Aufrufe ✓
- Erster Slot eines neuen Tages aus Per-Wochentag-Defaults; Vorbelegungs-Priorität (Ist → Reservierung → Default) → Task 2, Step 3 ✓
- Zeile entfernen + Speichern = Editieren (kein zweiter Lösch-Pfad Win/Linux); macOS behält Lösch-Buttons → Save-Semantik + `_SHOW_DELETE_IN_DIALOG` ✓
- Reservierungs-Slot ohne pause; trigger_reconcile nach Reservierungs-Save → Task 2 ✓
- Bewusst NICHT in AP3: Kategorie-Verwaltung (AP6), Kalender-Zellen-Mehrslot-Anzeige + Rechtsklick (AP6), report/share/gcal (eigene Pakete).

**2. Placeholder-Scan:** Keine TBD/TODO; vollständiger Code in jedem Code-Step, vollständige Tests in Task 1. ✓

**3. Typ-Konsistenz:**
- `validate_slots(slots, with_pause)` Signatur identisch in time_utils, Tests und beiden Dialog-Aufrufen. ✓
- Ist-Zeit-Slot `{start,end,pause,kategorie}` (int pause) vs. Reservierungs-Slot `{start,end,kategorie}` — konsistent zu AP1 und den `storage.save`/`reservation_store.save`-Signaturen. ✓
- `dark_combo_editable(parent, textvariable, values, width)` — Signatur in theme.py-Definition und Dialog-Aufrufen identisch. ✓
- `storage.get`/`reservation_store.get` liefern `{"slots":[...]}|None` — der Dialog liest `entry["slots"]` / `existing_reservation["slots"]` entsprechend. ✓
