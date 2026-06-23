# AP6 — UI Multi-Slot + Kategorie-Verwaltung + Pull-Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Kalender-Zellen (`src/ui.py`) auf das Multi-Slot-Modell heben (Tagessumme über Slots, kompakte Zellen-Darstellung, Slot-Tooltips), eine Kategorie-Verwaltung als eigenen Modal-Dialog (`src/dialogs/category_dialog.py`) bereitstellen (Button im Settings-Dialog), und den aus AP2 verschobenen Regulär-Sync-Pre-v3-Guard in `src/main.py` verdrahten.

**Architecture:** ui.py ist eine dünne Tkinter-Schicht (Task 1, manuell verifiziert). Die Kategorie-Listen-Logik (anlegen/umbenennen/entfernen) wird als **pure, getestete Funktionen** in `category_dialog.py` ausgelagert; der Modal nutzt sie (Task 2). Der Pull-Guard nutzt die in AP2 bereits getestete `sync._remote_is_pre_v3` und überspringt den Merge bei einem pre-v3-Remote (Task 3).

**Tech Stack:** Python stdlib, tkinter, pytest.

## Global Constraints

- **AP1-Shape:** Ist-Zeit-Eintrag = `{"slots":[{start,end,pause,kategorie}]}`; Reservierung (user-shape) = `{"slots":[{start,end,kategorie}]}`. `storage.get(date)`/`reservation_store.get(date)` liefern das oder `None`.
- **Tagessumme** = Summe `calculate_hours(start,end,pause)` über alle Slots, `round(…,2)`.
- **Zellen-Darstellung:** kompakt — erste Slot-Zeit `HH:MM-HH:MM`, bei >1 Slot `+N` (N = weitere Slots). Tooltip listet bei >1 Slot alle Arbeitszeit-Slots (inkl. Kategorie); Reservierungs-/Feiertags-Infos im selben (einzigen) Tooltip kombiniert.
- **Genau ein `attach_tooltip` pro Zelle** (Mehrfach = überlappende Tooltips, s. bestehender Docstring).
- **Rechtsklick-Löschen (`_delete_day`) bleibt unverändert** — es arbeitet bereits typweise (Arbeitszeit/Reservierung, nur was existiert) und liest die Slot-Shape nicht.
- **Kategorie-Verwaltung** als eigener Modal `open_category_dialog(parent, settings, on_change=None)`; speichert via `settings.set_synced("categories", liste)`. Reine Listen-Logik (`add_category`/`remove_category`/`rename_category`) ist pure + getestet.
- **Pull-Guard:** `sync._remote_is_pre_v3(remote_doc)` in `_run_pull_in_background` (nur im real-heruntergeladenen Zweig, NICHT im synthetischen No-File-Fall) und im `_run_push_blocking`-Retry; bei pre-v3-Remote Merge überspringen + `sync.OLD_REMOTE_VERSION_MSG` melden (freundlicher Info-Dialog via `_friendly_sync_message`).
- **Datumsformat:** intern ISO; UI deutsch.
- **Harter Schnitt — Ziel: nach AP6 ist die App lauffähig.** Nach AP6 sind alle bisher umgestellten Pfade konsistent; nur `gcal`/`reservations_sync` (AP7) bleiben offen, betreffen aber nur den (optionalen) Google-Kalender-Abgleich.

## Test-Strategie / Design-Notes (für den Plan-Review)

- **`category_dialog.py` Pure-Helfer sind voll unit-getestet** (Task 2). Der Tkinter-Modal selbst: Import-Smoke + manuell.
- **`ui.py` und `settings_dialog.py` und `main.py`-Wiring: keine Auto-Tests** (Tkinter/Threads). Verifikation: Import-Smoke + Diff-Review + manueller Test + bestehende `test_ui_*`-Tests bleiben grün (sie berühren die Zellen-Logik nicht).
- **`sync._remote_is_pre_v3` ist seit AP2 getestet**; AP6 fügt nur die Wiring + eine String-Konstante hinzu.

---

## Dateistruktur

- `src/ui.py` — `_entry_hours` (Slot-Summe), `_build_entry_cell` (kompakte Multi-Slot-Zeit), `_build_day_cell` (kombinierter Slot-Tooltip), neuer Helfer `_fmt_slot_line`; plus `_friendly_sync_message`-Branch (Task 3).
- `src/dialogs/category_dialog.py` — **neu**: pure Listen-Helfer + Modal.
- `tests/test_category_dialog.py` — **neu**: Tests der Pure-Helfer.
- `src/dialogs/settings_dialog.py` — Button „Kategorien verwalten…".
- `src/main.py` — Pull-Guard (2 Stellen).
- `src/sync.py` — Konstante `OLD_REMOTE_VERSION_MSG`.

Task 1 (ui-Zellen) und Task 2 (Kategorie-Dialog) sind unabhängig. Task 3 (Guard) ist unabhängig von 1/2.

---

## Task 1: `ui.py` — Multi-Slot-Zellen

**Files:**
- Modify: `src/ui.py` (`_entry_hours`, `_build_entry_cell`, `_build_day_cell`, neuer Helfer `_fmt_slot_line`)

**Interfaces:**
- Consumes: AP1-Shape (`entry["slots"]`, `reservation["slots"]`).

> Keine Auto-Tests (Tkinter). Verifikation: Import-Smoke + `test_ui_*` grün + manuell.

- [ ] **Step 1: `_entry_hours` auf Slot-Summe umstellen**

In `src/ui.py`, ersetze (aktuell):

```python
    def _entry_hours(self, entry):
        return calculate_hours(
            entry["start"], entry["end"], pause_minutes=entry.get("pause", 0),
        )
```

durch:

```python
    def _entry_hours(self, entry):
        return round(sum(
            calculate_hours(s["start"], s["end"], pause_minutes=s.get("pause", 0))
            for s in entry.get("slots", [])
        ), 2)
```

- [ ] **Step 2: `_fmt_slot_line`-Helfer ergänzen**

In `src/ui.py`, direkt **vor** `def _add_reservation_marker(self, cell):`, füge ein:

```python
    @staticmethod
    def _fmt_slot_line(slot):
        """Eine Tooltip-Zeile für einen Slot: 'HH:MM-HH:MM  Kategorie'
        (Kategorie weggelassen, wenn leer)."""
        kat = f"  {slot['kategorie']}" if slot.get("kategorie") else ""
        return f"{slot['start']}-{slot['end']}{kat}"

```

- [ ] **Step 3: `_build_entry_cell` — kompakte Multi-Slot-Zeit**

In `src/ui.py`, in `_build_entry_cell`, ersetze (aktuell):

```python
        time_lbl = tk.Label(
            cell, text=f"{entry['start']}-{entry['end']}",
            font=time_font, bg=bg, fg=TEXT_MUTED, cursor="hand2",
        )
```

durch:

```python
        slots = entry.get("slots", [])
        if slots:
            first = slots[0]
            time_text = f"{first['start']}-{first['end']}"
            if len(slots) > 1:
                time_text += f"  +{len(slots) - 1}"
        else:
            time_text = ""
        time_lbl = tk.Label(
            cell, text=time_text,
            font=time_font, bg=bg, fg=TEXT_MUTED, cursor="hand2",
        )
```

- [ ] **Step 4: `_build_day_cell` — kombinierter Slot-Tooltip**

In `src/ui.py`, in `_build_day_cell`, ersetze den Tooltip-Block (aktuell):

```python
        # Reservierung ist ein reiner Overlay-Marker (Eck-Punkt) — sie ändert
        # den Zelltyp nicht. Genau ein attach_tooltip pro Zelle: Mehrfachaufruf
        # erzeugt überlappende Tooltips (s. attach_tooltip-Docstring).
        if reservation is not None:
            self._add_reservation_marker(cell)
            tip = f"Reservierung: {reservation['start']}-{reservation['end']}"
            if is_holiday:
                tip += f"\nFeiertag: {holidays_map[day_date]}"
            attach_tooltip(cell, tip)
        elif entry and is_holiday:
            attach_tooltip(cell, f"Feiertag: {holidays_map[day_date]}")
```

durch:

```python
        # Reservierung ist ein reiner Overlay-Marker (Eck-Punkt) — sie ändert
        # den Zelltyp nicht. Genau EIN attach_tooltip pro Zelle (Mehrfachaufruf
        # erzeugt überlappende Tooltips); deshalb alle relevanten Infos
        # (mehrere Arbeitszeit-Slots, Reservierung, Feiertag) in einen
        # kombinierten Tooltip. Ein Feiertag-OHNE-Eintrag/-Reservierung zeigt
        # seinen Namen weiterhin als Zelltext (Holiday-Zelle) bzw. eigenen
        # Tooltip (name_tooltip) und kommt hier NICHT rein.
        tip_parts = []
        if entry and len(entry.get("slots", [])) > 1:
            tip_parts.append(
                "Arbeitszeit:\n"
                + "\n".join(self._fmt_slot_line(s) for s in entry["slots"]))
        if reservation is not None:
            self._add_reservation_marker(cell)
            tip_parts.append(
                "Reservierung:\n"
                + "\n".join(self._fmt_slot_line(s) for s in reservation.get("slots", [])))
        if is_holiday and (reservation is not None or entry):
            tip_parts.append(f"Feiertag: {holidays_map[day_date]}")
        if tip_parts:
            attach_tooltip(cell, "\n".join(tip_parts))
```

- [ ] **Step 5: Import-Smoke + Byte-Compile + `test_ui_*`**

Run: `python -c "import src.ui; print('ok')"`
Expected: `ok`.

Run: `python -m py_compile src/ui.py`
Expected: keine Ausgabe, Exit 0.

Run: `python -m pytest tests/test_ui_sync_errors.py tests/test_ui_autostart_target.py tests/test_click_guard.py -q`
Expected: PASS (unverändert grün — die Zellen-Logik wird dort nicht berührt).

- [ ] **Step 6: Manuelle Verifikations-Checkliste (in den Report, NICHT ausführen)**

- Tag mit einem Slot: Zelle zeigt „HH:MM-HH:MM" wie bisher, Tagessumme korrekt.
- Tag mit zwei Slots: Zelle zeigt „erste Zeit  +1"; Tooltip listet beide Slots inkl. Kategorie; Footer-Summe = Summe beider Slots.
- Tag mit Reservierung: violetter Punkt + Tooltip listet Reservierungs-Slots.
- Feiertag ohne Eintrag: Name als Text/Tooltip wie bisher (kein Doppel-Tooltip).

- [ ] **Step 7: Commit**

```bash
git add src/ui.py
git commit -m "feat(ui): Kalenderzellen mit mehreren Slots + Slot-Tooltips (#53)

_entry_hours summiert über Slots; _build_entry_cell zeigt erste Slot-Zeit
+N; _build_day_cell baut einen kombinierten Tooltip (Arbeitszeit-Slots,
Reservierung, Feiertag). Rechtsklick-Löschen unverändert. Teil von AP6.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Kategorie-Verwaltung (`category_dialog.py` + Settings-Button)

**Files:**
- Create: `src/dialogs/category_dialog.py`
- Create: `tests/test_category_dialog.py`
- Modify: `src/dialogs/settings_dialog.py` (Import + Button im btn_frame)

**Interfaces:**
- Produces:
  - `add_category(categories, name) -> list` / `remove_category(categories, name) -> list` / `rename_category(categories, old, new) -> list` (pure; trimmen, dedupen, neue Liste).
  - `open_category_dialog(parent, settings, on_change=None) -> None` (Modal; speichert via `settings.set_synced("categories", ...)`).

- [ ] **Step 1: `tests/test_category_dialog.py` anlegen (Failing)**

Lege `tests/test_category_dialog.py` mit folgendem Inhalt an:

```python
from src.dialogs.category_dialog import add_category, remove_category, rename_category


def test_add_category():
    assert add_category([], "Büro") == ["Büro"]


def test_add_strips_whitespace():
    assert add_category([], "  Büro  ") == ["Büro"]


def test_add_empty_is_ignored():
    assert add_category(["A"], "   ") == ["A"]


def test_add_duplicate_is_ignored():
    assert add_category(["Büro"], "Büro") == ["Büro"]


def test_add_returns_new_list():
    orig = ["A"]
    result = add_category(orig, "B")
    assert orig == ["A"]            # Original unverändert
    assert result == ["A", "B"]


def test_remove_category():
    assert remove_category(["A", "B"], "A") == ["B"]


def test_remove_absent_is_noop():
    assert remove_category(["A"], "X") == ["A"]


def test_rename_category():
    assert rename_category(["A", "B"], "A", "C") == ["C", "B"]


def test_rename_strips_whitespace():
    assert rename_category(["A"], "A", "  C  ") == ["C"]


def test_rename_empty_new_is_ignored():
    assert rename_category(["A"], "A", "   ") == ["A"]


def test_rename_absent_old_is_noop():
    assert rename_category(["A"], "X", "C") == ["A"]


def test_rename_to_existing_other_is_ignored():
    assert rename_category(["A", "B"], "A", "B") == ["A", "B"]


def test_rename_to_same_name_keeps_list():
    assert rename_category(["A", "B"], "A", "A") == ["A", "B"]
```

- [ ] **Step 2: Tests laufen lassen — müssen FEHLSCHLAGEN**

Run: `python -m pytest tests/test_category_dialog.py -q`
Expected: FAIL — `src/dialogs/category_dialog.py` existiert noch nicht (ImportError).

- [ ] **Step 3: `src/dialogs/category_dialog.py` anlegen**

Lege `src/dialogs/category_dialog.py` mit folgendem Inhalt an:

```python
"""Modal zum Verwalten der Kategorie-Pickliste. Die Listen-Logik
(add/remove/rename) ist pure und getestet; der Tkinter-Teil ist nur Wiring.
Speichert via settings.set_synced('categories', ...)."""

import tkinter as tk

from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, TEXT,
    apply_app_icon, apply_dark_titlebar, attach_unfocus_on_click,
    center_dialog_on_parent, dark_entry, disable_min_max,
    primary_button, secondary_button,
)


def add_category(categories, name):
    """Fügt `name` (getrimmt) hinzu, falls nicht leer und nicht vorhanden.
    Liefert IMMER eine neue Liste (Original bleibt unangetastet)."""
    name = name.strip()
    if not name or name in categories:
        return list(categories)
    return list(categories) + [name]


def remove_category(categories, name):
    """Entfernt `name`. Liefert eine neue Liste."""
    return [c for c in categories if c != name]


def rename_category(categories, old, new):
    """Benennt `old` in `new` (getrimmt) um. No-op, wenn `new` leer ist, `old`
    nicht existiert, oder `new` bereits eine ANDERE Kategorie ist."""
    new = new.strip()
    if not new or old not in categories:
        return list(categories)
    if new in categories and new != old:
        return list(categories)
    return [new if c == old else c for c in categories]


def open_category_dialog(parent, settings, on_change=None):
    categories = list(settings.get("categories") or [])

    dialog = tk.Toplevel(parent)
    dialog.title("Kategorien verwalten")
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.focus_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)
    disable_min_max(dialog)
    apply_app_icon(dialog)
    attach_unfocus_on_click(dialog)
    dialog.bind("<Escape>", lambda _e: dialog.destroy())

    outer = tk.Frame(dialog, bg=BG)
    outer.pack(padx=12, pady=12)

    tk.Label(outer, text="Kategorien", font=FONT_BOLD, bg=BG, fg=TEXT).pack(anchor="w")

    listbox = tk.Listbox(
        outer, height=8, width=30, font=FONT, bg=CELL_BG, fg=TEXT,
        selectbackground=ACCENT, selectforeground="#ffffff",
        highlightthickness=0, bd=0, activestyle="none",
    )
    listbox.pack(fill="x", pady=(4, 8))

    def refresh():
        listbox.delete(0, tk.END)
        for c in categories:
            listbox.insert(tk.END, c)

    refresh()

    def _selected():
        sel = listbox.curselection()
        return categories[sel[0]] if sel else None

    name_var = tk.StringVar()

    def on_add():
        nonlocal categories
        categories = add_category(categories, name_var.get())
        name_var.set("")
        refresh()

    def on_rename():
        nonlocal categories
        current = _selected()
        if current is None:
            return
        categories = rename_category(categories, current, name_var.get())
        name_var.set("")
        refresh()

    def on_remove():
        nonlocal categories
        current = _selected()
        if current is None:
            return
        categories = remove_category(categories, current)
        refresh()

    edit_row = tk.Frame(outer, bg=BG)
    edit_row.pack(fill="x", pady=(0, 8))
    dark_entry(edit_row, name_var, width=18).pack(side=tk.LEFT, padx=(0, 4))
    secondary_button(edit_row, "Hinzufügen", on_add).pack(side=tk.LEFT, padx=2)
    secondary_button(edit_row, "Umbenennen", on_rename).pack(side=tk.LEFT, padx=2)
    secondary_button(edit_row, "Entfernen", on_remove).pack(side=tk.LEFT, padx=2)

    def on_save():
        settings.set_synced("categories", categories)
        if on_change is not None:
            on_change()
        dialog.destroy()

    save_row = tk.Frame(outer, bg=BG)
    save_row.pack(fill="x")
    primary_button(save_row, "Speichern", on_save).pack(side=tk.LEFT, padx=2)
    secondary_button(save_row, "Schließen", dialog.destroy).pack(side=tk.LEFT, padx=2)

    center_dialog_on_parent(dialog, parent)
```

- [ ] **Step 4: Tests laufen lassen — müssen BESTEHEN**

Run: `python -m pytest tests/test_category_dialog.py -q`
Expected: PASS.

Run: `python -c "import src.dialogs.category_dialog; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: `settings_dialog.py` — Button „Kategorien verwalten…"**

In `src/dialogs/settings_dialog.py`, ergänze den Import (z.B. direkt nach den bestehenden `from src.dialogs...`-Imports am Dateianfang — oder, falls keine vorhanden, nach den `from src.theme import (...)`-Imports):

```python
from src.dialogs.category_dialog import open_category_dialog
```

Und ersetze den Button-Block (aktuell):

```python
    primary_button(btn_frame, "Speichern", save_settings).pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)
```

durch:

```python
    secondary_button(
        btn_frame, "Kategorien verwalten…",
        lambda: open_category_dialog(dialog, settings),
    ).pack(side=tk.LEFT, padx=5)
    primary_button(btn_frame, "Speichern", save_settings).pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)
```

> Hinweis: Der Kategorie-Dialog speichert eigenständig via `set_synced` — unabhängig vom „Speichern"/„Abbrechen" des Settings-Dialogs. Das ist gewollt.

- [ ] **Step 6: Import-Smoke + Byte-Compile**

Run: `python -c "import src.dialogs.settings_dialog, src.dialogs.category_dialog; print('ok')"`
Expected: `ok`.

Run: `python -m py_compile src/dialogs/settings_dialog.py src/dialogs/category_dialog.py`
Expected: keine Ausgabe, Exit 0.

- [ ] **Step 7: Manuelle Verifikations-Checkliste (in den Report, NICHT ausführen)**

- Settings-Dialog: Button „Kategorien verwalten…" öffnet den Modal.
- Hinzufügen/Umbenennen/Entfernen ändern die Liste; Speichern persistiert sie; im Tages-Dialog erscheinen die Kategorien als Vorschläge.

- [ ] **Step 8: Commit**

```bash
git add src/dialogs/category_dialog.py tests/test_category_dialog.py src/dialogs/settings_dialog.py
git commit -m "feat(ui): Kategorie-Verwaltung als Modal-Dialog (#53)

Neuer category_dialog mit pure, getesteten Listen-Helfern (add/remove/
rename) + Tkinter-Modal; speichert via set_synced('categories'). Button
'Kategorien verwalten…' im Settings-Dialog. Teil von AP6.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Regulär-Sync Pre-v3-Guard (aus AP2 verschoben)

**Files:**
- Modify: `src/sync.py` (Konstante `OLD_REMOTE_VERSION_MSG`)
- Modify: `src/main.py` (Guard in `_run_pull_in_background` + `_run_push_blocking`-Retry)
- Modify: `src/ui.py` (`_friendly_sync_message`-Branch)

**Interfaces:**
- Consumes: `sync._remote_is_pre_v3` (seit AP2 getestet).
- Produces: `sync.OLD_REMOTE_VERSION_MSG` (str).

> Wiring ohne Unit-Test (Drive-I/O/Threads). `_remote_is_pre_v3` ist getestet. Verifikation: Import-Smoke + Regression + manuell.

- [ ] **Step 1: `sync.py` — Konstante ergänzen**

In `src/sync.py`, direkt **nach** `SCHEMA_VERSION = 3`, füge ein:

```python


OLD_REMOTE_VERSION_MSG = (
    "Ein anderes Gerät nutzt eine ältere App-Version, die das neue Format "
    "(Mehrfach-Slots/Kategorien) noch nicht versteht.\n\n"
    "Bitte aktualisiere die App auf dem anderen Gerät, bevor du dort "
    "synchronisierst. Bis dahin pausiert die Synchronisation, damit keine "
    "Daten verloren gehen."
)
```

- [ ] **Step 2: `main.py` — Guard im Startup-Pull**

In `src/main.py`, in `_run_pull_in_background`, ersetze (aktuell):

```python
            remote_doc = _parse_remote_or_quarantine(content, file_id, _quarantine)
        local_doc = sync.build_local_doc(storage, settings, conflicts_store)
```

durch:

```python
            remote_doc = _parse_remote_or_quarantine(content, file_id, _quarantine)
            if sync._remote_is_pre_v3(remote_doc):
                # Älteres Gerät aktiv: nicht mergen (ein v2-Eintrag hat kein
                # 'slots' → würde apply_merge verletzen / Daten plätten).
                ui_callback(ok=False, error=sync.OLD_REMOTE_VERSION_MSG, tb="")
                return
        local_doc = sync.build_local_doc(storage, settings, conflicts_store)
```

> Der synthetische No-File-Fall (`file_id is None` → `{"schema_version": 1, "entries": {}}`) liegt im `if`-Zweig DAVOR und wird vom Guard NICHT erfasst — ein Erstsync ohne Drive-Datei merged korrekt (leeres Remote).

- [ ] **Step 3: `main.py` — Guard im Push-Retry**

In `src/main.py`, in `_run_push_blocking`, im `except drive.DriveConflictError:`-Block, ersetze (aktuell):

```python
                    remote_bytes, _ = drive.download(service, file_id)
                    remote_doc = json.loads(remote_bytes)
```

durch:

```python
                    remote_bytes, _ = drive.download(service, file_id)
                    remote_doc = json.loads(remote_bytes)
                    if sync._remote_is_pre_v3(remote_doc):
                        result["ok"] = False
                        result["error"] = sync.OLD_REMOTE_VERSION_MSG
                        result["tb"] = ""
                        return
```

- [ ] **Step 4: `ui.py` — freundliche Meldung in `_friendly_sync_message`**

In `src/ui.py`, in `_friendly_sync_message`, ersetze den Anfang (aktuell):

```python
    kind = _classify_sync_error(error)

    if kind == "auth":
```

durch:

```python
    from src.sync import OLD_REMOTE_VERSION_MSG
    if str(error) == OLD_REMOTE_VERSION_MSG:
        return ("Anderes Gerät veraltet", OLD_REMOTE_VERSION_MSG, True)

    kind = _classify_sync_error(error)

    if kind == "auth":
```

- [ ] **Step 5: Import-Smoke + Byte-Compile + Regression**

Run: `python -c "import src.main, src.ui, src.sync; print(src.sync.OLD_REMOTE_VERSION_MSG[:10])"`
Expected: gibt `Ein andere` aus (kein ImportError).

Run: `python -m py_compile src/main.py src/ui.py src/sync.py`
Expected: keine Ausgabe, Exit 0.

Run: `python -m pytest tests/test_sync.py -q`
Expected: PASS (Konstante bricht nichts).

- [ ] **Step 6: AP1–AP6-Gesamtregression**

Run: `python -m pytest tests/ -q --ignore=tests/test_gcal.py --ignore=tests/test_reservations_sync.py`
Expected: PASS.

> **Hinweis:** `test_gcal.py` und `test_reservations_sync.py` bleiben rot bis AP7 (gcal/reservations_sync noch nicht slot-fähig). Alle übrigen Tests müssen grün sein.

- [ ] **Step 7: Manuelle Verifikations-Checkliste (in den Report, NICHT ausführen)**

- Bei aktivem Sync gegen ein altes (pre-v3) Remote-Doc: Startup-Pull und manueller Sync zeigen den freundlichen „Anderes Gerät veraltet"-Hinweis und ändern lokale Daten NICHT.

- [ ] **Step 8: Commit**

```bash
git add src/sync.py src/main.py src/ui.py
git commit -m "feat(sync): Regulär-Pull/Push-Guard gegen pre-v3-Remote (#53)

_remote_is_pre_v3 in _run_pull_in_background + _run_push_blocking-Retry:
bei älterem Remote Merge überspringen (kein apply_merge-Crash/Datenverlust)
und freundlichen Hinweis zeigen (sync.OLD_REMOTE_VERSION_MSG +
_friendly_sync_message-Branch). Schließt die aus AP2 verschobene Lücke.
Teil von AP6.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec-Coverage (Spec „UI (ui.py)" + „settings_dialog" + AP2-Guard-Verschiebung):**
- Kalenderzelle mehrere Slots kompakt + Tooltip + Tagessumme über Slots → Task 1 ✓
- Rechtsklick-Löschen zeigt nur vorhandene Arten (unverändert korrekt) → keine Änderung nötig ✓
- settings_dialog Kategorie-Verwaltung (anlegen/umbenennen/entfernen) → Task 2 (eigener Modal) ✓
- Regulär-Pull-Pre-v3-Guard + Hinweis (aus AP2) → Task 3 ✓
- Bewusst NICHT in AP6: gcal Multi-Event / reservations_sync (AP7).

**2. Placeholder-Scan:** Keine TBD/TODO; vollständiger Code/Tests in jedem Step. ✓

**3. Typ-Konsistenz:**
- `_fmt_slot_line(slot)` liest `{start,end,kategorie}` — passt für Ist-Zeit- UND Reservierungs-Slots (pause ignoriert). ✓
- `_entry_hours` summiert `entry["slots"]`; `_build_entry_cell`/`_build_day_cell` lesen `entry["slots"]`/`reservation["slots"]` — konsistent zu AP1. ✓
- `add/remove/rename_category` Signaturen identisch in category_dialog, Tests und Modal-Aufrufen. ✓
- `open_category_dialog(parent, settings, on_change=None)` — Aufruf in settings_dialog passt. ✓
- `sync.OLD_REMOTE_VERSION_MSG` — definiert in sync.py, referenziert in main.py (2×) und ui.py. ✓
- `sync._remote_is_pre_v3` — seit AP2 vorhanden/getestet. ✓
