# Notiz am Slot, PR 2: Desktop-Oberfläche und Bericht — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Am Desktop lässt sich die Notiz eines Ist-Zeit-Slots eintragen und überall lesen, wo heute die Kategorie steht (Tages-Dialog, Tooltip, Löschen-Dialog, Konfliktdialog, Bericht), und der Bericht kann die Summe je Kategorie zusätzlich je Notiz aufschlüsseln.

**Architecture:** Der Kern aus PR 1 bleibt unverändert: `Storage.get`/`get_all` liefern `notiz` am Slot, `Storage.save` nimmt sie dort an. Dieser PR ergänzt nur Leser und einen Schreiber (Tages-Dialog). Jede Entscheidung liegt Tk-frei auf Modulebene (`slot_notes`, `conflict_view`, `report`, Modul-Funktionen der Dialoge) und ist getestet; die Widgets verdrahten nur.

**Tech Stack:** Python 3.12, Tkinter/ttk, pytest. Kein neues Paket.

**Spec:** `docs/superpowers/specs/2026-11-23-slot-notizen-design.md` (Xveyn#519), Abschnitte „Desktop-Oberfläche“, „Bericht“ und „Meine Entscheidungen“ 10–13. PR 3 (PWA) bekommt einen eigenen Plan.

**Branch:** `feat/slot-notizen-desktop` von `master`. Plan und Spec-Ergänzung gehen mit dem ersten Commit hinein. PR-Text mit `Refs #519`, kein `release:*`-Label.

## Global Constraints

- Kein Format ändert sich: Datei, Sync-Doc, Handy-Abgleich, lokale API, Webhook und Teilen-Datei bleiben, wie PR 1 sie hinterlassen hat. Dieser PR fasst `storage.py`, `sync.py`, `mobile_sync.py`, `webhook.py`, `share.py` nicht an.
- Ohne Notizen bitgleich: Mail-HTML, PDF-HTML, Tooltip-Text, Löschen-Optionen und Konfliktkarten sind für einen Bestand ohne Notiz Zeichen für Zeichen wie auf `master`. Der Sende-/Export-Dialog sieht ohne Notiz im Bestand unverändert aus.
- Slots in App-Form: `slot.get("notiz", "")`. Der Tages-Dialog übergibt `notiz` an **jedem** Ist-Slot ausdrücklich (auch `""`), sonst erbte `Storage.save` die alte Notiz und Löschen wäre unmöglich.
- Notiz-Regeln nur aus `src/slot_notes.py` (`check_note`, `clean_note`, `group_key`, `MAX_NOTE_LEN` = 200); nichts davon wird nachgebaut.
- Trennzeichen zwischen Kategorie und Notiz ist `" · "` (U+00B7 mit je einem Leerzeichen).
- Summen nur über Minuten (`hours_to_minutes` je Slot, Anzeige über `_minutes_as_hours`).
- Jeder Text aus dem Bestand geht im Bericht durch `_esc`.
- UI-Regeln des Repos: Pixelwerte durch `px()`, Schrift nur aus benannten Fonts, Breiten von Eingabefeldern in Zeichen, ausgrauen über `theme.set_enabled`, keine Lösch-Knöpfe im Tages-Dialog, genau ein `attach_tooltip` je Widget, keine dialogspezifischen Farben.
- Tk-freie, annotierte Module (`slot_notes.py`, `conflict_view.py`, `report.py`) bleiben vollständig annotiert. Kommentare sagen das Warum, keine Historie, Docstrings in der Regel ≤ 8 Zeilen.
- Prüfung je Task: `.venv/bin/python -m pytest -q`, `ruff check .`, `uvx --quiet pyright@1.1.411 --pythonpath .venv/bin/python` (5 bekannte `websockets`-Importfehler der lokalen Umgebung).
- Commits enden mit `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.

## Review Focus

Eingaben, die die Spec nicht einzeln nennt und die am ehesten jemanden treffen. Jede hat ihren Test in der genannten Task.

1. Eine Notiz mit 200 Zeichen: Tooltip und Löschen-Dialog zeigen höchstens 60 Zeichen mit „…“, die Konfliktkarte bricht um, kein Fenster wächst über den Bildschirm. → Task 1, 3, 4
2. HTML in der Notiz (`<b>Kunde</b> & Co`): Berichtszeile und Aufschlüsselung zeigen den Text, kein Markup. → Task 5
3. Dieselbe Notiz in anderer Schreibweise (`Kunde Müller`, `kunde müller `) an mehreren Tagen: eine Unterzeile, Schreibweise des ersten Vorkommens nach Datum; drei Slots zu je 20 Minuten ergeben in Unterzeilen und Kategorie dieselbe Summe. → Task 1, 5
4. Konflikt, dessen Stände dieselben Slots und verschiedene Notizen haben; der Nutzer behält den **älteren**: gespeichert ist danach die Notiz des älteren. → Task 4
5. Im Notizfeld eingefügter Text mit Zeilenumbruch oder 201 Zeichen: Meldung, nichts wird gespeichert. Ein geleertes Feld an einem gespeicherten Slot entfernt die Notiz. → Task 2

## File Structure

| Datei | Aufgabe |
|---|---|
| `src/slot_notes.py` | Anzeige-Helfer: Beschriftung, Kürzen, Vorschläge, „hat der Bestand Notizen“ |
| `src/theme/widgets.py` | `dark_combo(..., editable=False)` |
| `src/dialogs/slot_rows.py`, `src/dialogs/entry_dialog.py` | Notizfeld je Ist-Zeile, Prüfung beim Speichern |
| `src/grid_renderer.py` | Tooltip-Zeile (der Löschen-Dialog benutzt dieselbe Funktion) |
| `src/conflict_view.py`, `src/dialogs/conflicts_dialog.py` | Notiz auf der Karte, Notizen der gewählten Karte beim Auflösen |
| `src/report.py` | Berichtszeile, Aufschlüsselung je Notiz |
| `src/dialogs/period_picker.py`, `send_dialog.py`, `send_task.py`, `export_dialog.py`, `export_task.py` | Option „Nach Notiz aufschlüsseln“ |
| `README.md`, `CLAUDE.md`, `src/CLAUDE.md` | Doku |

---

### Task 1: Anzeige-Helfer in `slot_notes`

**Files:**
- Modify: `src/slot_notes.py`, `tests/test_slot_notes.py`

**Interfaces (Produces):**

```python
SEPARATOR = " · "
DISPLAY_LIMIT = 60

def label(kategorie: object, notiz: object) -> str: ...
def shorten(text: str, limit: int = DISPLAY_LIMIT) -> str: ...
def suggestions(entries: Mapping[str, Any], kategorie: str, limit: int = 20) -> list[str]: ...
def has_notes(entries: Mapping[str, Any]) -> bool: ...
```

- `label`: Kategorie (Text, getrimmt; alles andere `""`) und `clean_note(notiz)`, verbunden mit `SEPARATOR`; fehlt eines, nur das andere; fehlen beide, `""`.
- `shorten`: bis `limit` Code Points unverändert, sonst die ersten `limit - 1` und `…`.
- `suggestions`: Notizen der Slots, deren `kategorie or ""` gleich `kategorie` ist. Tage absteigend nach Datum (Schlüssel der Abbildung), innerhalb eines Tages in gespeicherter Reihenfolge; je `group_key` nur das erste Vorkommen; höchstens `limit`. `entries` hat die Form von `Storage.get_all()`; ein Eintrag ohne Slot-Liste oder ein Slot, der kein Objekt ist, wird übergangen.
- `has_notes`: wahr, sobald ein Slot eine nicht leere `clean_note(notiz)` hat.

- [ ] **Step 1: Tests schreiben** (`tests/test_slot_notes.py`)

```python
def test_label_joins_category_and_note():
    assert slot_notes.label("Montage", "Kunde Mustermann") == "Montage · Kunde Mustermann"
    assert slot_notes.label("Montage", "") == "Montage"
    assert slot_notes.label("", "Kunde Mustermann") == "Kunde Mustermann"
    assert slot_notes.label(None, None) == ""
    assert slot_notes.label("Montage", "a\nb") == "Montage · ab"

def test_shorten_counts_code_points():
    assert slot_notes.shorten("x" * 60) == "x" * 60
    assert slot_notes.shorten("x" * 61) == "x" * 59 + "…"
    assert slot_notes.shorten("😀" * 61) == "😀" * 59 + "…"

def test_suggestions_newest_first_once_per_group_key():
    entries = {
        "2026-11-02": {"slots": [{"start": "08:00", "kategorie": "Montage", "notiz": "Kunde Müller"}]},
        "2026-11-03": {"slots": [{"start": "08:00", "kategorie": "Montage", "notiz": "kunde müller"},
                                 {"start": "13:00", "kategorie": "Büro", "notiz": "Ablage"}]},
        "2026-11-04": {"slots": [{"start": "08:00", "kategorie": "Montage", "notiz": "Kunde Mustermann"},
                                 {"start": "13:00", "kategorie": "Montage"}]},
    }
    assert slot_notes.suggestions(entries, "Montage") == ["Kunde Mustermann", "kunde müller"]
    assert slot_notes.suggestions(entries, "") == []
    assert slot_notes.suggestions(entries, "Montage", limit=1) == ["Kunde Mustermann"]

def test_suggestions_and_has_notes_survive_foreign_shapes():
    entries = {"2026-11-02": {"slots": "kaputt"}, "2026-11-03": {}, "2026-11-04": {"slots": [None, {"notiz": 5}]}}
    assert slot_notes.suggestions(entries, "") == []
    assert slot_notes.has_notes(entries) is False
    assert slot_notes.has_notes({"2026-11-02": {"slots": [{"start": "08:00", "notiz": " x "}]}}) is True
```

- [ ] **Step 2:** `pytest tests/test_slot_notes.py -q` → die neuen Tests scheitern (`AttributeError`).
- [ ] **Step 3:** Die vier Funktionen und zwei Konstanten in `src/slot_notes.py` ergänzen (weiter ohne Importe aus `src`).
- [ ] **Step 4:** `pytest tests/test_slot_notes.py tests/test_type_annotations.py -q` → grün.
- [ ] **Step 5: Commit** `feat(notizen): Anzeige-Helfer für Beschriftung, Kürzen und Vorschläge (Refs #519)` (enthält auch Plan und Spec-Ergänzung).

---

### Task 2: Notizfeld im Tages-Dialog

**Files:**
- Modify: `src/theme/widgets.py`, `src/dialogs/slot_rows.py`, `src/dialogs/entry_dialog.py`, `tests/test_entry_dialog.py`

**Interfaces:**
- Consumes: `slot_notes.suggestions`, `slot_notes.check_note`, `slot_notes.NoteError`.
- Produces:

```python
# theme/widgets.py
def dark_combo(parent, textvariable, values, width=8, editable=False, **kw)  # editable → state="normal"

# slot_rows.py
NOTE_WIDTH = 24
SlotRowList(..., note_suggestions=None)   # Callable[[str], list[str]] | None; None = kein Notizfeld
SlotRowList.add(start, end, kategorie, *, pause=None, notiz="", removable=True, parent=None, extra=None)
# Record trägt mit Notizfeld zusätzlich "notiz": tk.StringVar

# entry_dialog.py
NOTE_ERROR = "Notiz: höchstens 200 Zeichen, ohne Zeilenumbruch oder Steuerzeichen."
def plan_entry_save(ist_slots, res_slots, show_reservation)  # prüft und trimmt `notiz` der Ist-Slots in-place
```

Festlegungen:
- **Zeile:** nach dem Kategorie-Dropdown ein gedämpftes Label `Notiz:` (`FONT`, `TEXT_MUTED`) und das Feld `dark_combo(row, nv, [], width=NOTE_WIDTH, editable=True)`; danach wie bisher × und ▲/▼. Nur wenn `note_suggestions` gesetzt ist (Ist-Block), der Reservierungs-Block bleibt ohne Feld.
- **Vorschläge** werden beim Aufklappen berechnet (`postcommand`): `note_suggestions(category_from_display(kv.get()))`. Die Kategorie-Auswahl schreibt nie in das Notizfeld.
- **Mausrad** auf dem Notizfeld (`<MouseWheel>`, `<Button-4>`, `<Button-5>`) liefert `"break"`: ttk schaltete sonst durch die Vorschläge und überschriebe getippten Text.
- **Cursor sichtbar:** `apply_combobox_style` setzt für `Dark.TCombobox` zusätzlich `insertcolor=ACCENT` (im editierbaren Feld wäre der Cursor sonst dunkel auf dunkel).
- **`entry_dialog`:** `all_entries = storage.get_all()` einmal beim Öffnen; `note_suggestions=lambda kat: slot_notes.suggestions(all_entries, kat)` nur für `ist_list`. `add_ist_row` reicht `notiz` durch; gespeicherte Slots mit `s.get("notiz", "")`, die Vorbelegung aus einer Reservierung und „+ Slot“ mit `""`. `save_all` setzt `"notiz": r["notiz"].get()` in jeden Ist-Slot.
- **`plan_entry_save`:** nach der bestehenden Slot-Prüfung jeden Ist-Slot mit Schlüssel `notiz` durch `check_note`; bei `NoteError` Fehler `NOTE_ERROR` (mit dem Präfix `Arbeitszeit: `, wenn `show_reservation`, wie die übrigen Fehler), sonst wird `slot["notiz"]` durch den getrimmten Wert ersetzt. Slots ohne den Schlüssel bleiben unberührt.

- [ ] **Step 1: Tests schreiben** (`tests/test_entry_dialog.py`)

```python
def _ist(notiz=None):
    slot = {"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Montage"}
    if notiz is not None:
        slot["notiz"] = notiz
    return slot

def test_plan_entry_save_trims_notes_in_place():
    slots = [_ist("  Kunde Mustermann  ")]
    plan = plan_entry_save(slots, [], False)
    assert plan["error"] is None and plan["save_ist"] is True
    assert slots[0]["notiz"] == "Kunde Mustermann"

def test_plan_entry_save_keeps_explicit_empty_note():
    slots = [_ist("")]
    assert plan_entry_save(slots, [], False)["error"] is None
    assert slots[0]["notiz"] == ""            # Schlüssel bleibt: nur so löscht Storage.save die Notiz

@pytest.mark.parametrize("bad", ["x" * 201, "a\nb", "a\tb"])
def test_plan_entry_save_rejects_invalid_note(bad):
    plan = plan_entry_save([_ist(bad)], [], False)
    assert plan == {"error": NOTE_ERROR, "save_ist": False, "save_reservation": False}

def test_plan_entry_save_note_error_carries_block_prefix():
    assert plan_entry_save([_ist("x" * 201)], [], True)["error"] == "Arbeitszeit: " + NOTE_ERROR

def test_plan_entry_save_without_note_key_is_unchanged():
    slots = [_ist()]
    assert plan_entry_save(slots, [], False)["error"] is None
    assert "notiz" not in slots[0]

def test_cleared_note_is_removed_by_storage(tmp_path):
    storage = Storage(str(tmp_path / "z.json"))        # Konstruktion wie in tests/test_storage_notes.py
    storage.save("2026-11-03", [_ist("Kunde Mustermann")])
    slots = [_ist("")]
    assert plan_entry_save(slots, [], False)["error"] is None
    storage.save("2026-11-03", slots)
    assert "notiz" not in storage.get("2026-11-03")["slots"][0]
```

- [ ] **Step 2:** `pytest tests/test_entry_dialog.py -q` → neue Tests scheitern.
- [ ] **Step 3:** `dark_combo` und `apply_combobox_style` erweitern; `plan_entry_save` und `NOTE_ERROR`.
- [ ] **Step 4:** `SlotRowList` und `open_entry_dialog` nach den Festlegungen verdrahten. Die Breiten-Probe (`add_ist_row(..., parent=holder)`) misst die Zeile mit Notizfeld automatisch mit.
- [ ] **Step 5:** ganze Suite, `ruff`, `pyright`; `tests/test_pixel_scaling.py` und `tests/test_dialog_reveal.py` bleiben grün.
- [ ] **Step 6: Commit** `feat(notizen): Notizfeld mit Vorschlägen im Tages-Dialog (Refs #519)`

---

### Task 3: Tooltip und Löschen-Dialog

**Files:**
- Modify: `src/grid_renderer.py`, `tests/test_grid_renderer.py`, `tests/test_ui_delete.py`

`GridRenderer._fmt_slot_line(slot, with_pause=False)`: der Teil hinter der Zeit ist `slot_notes.label(kategorie, shorten(clean_note(notiz)))`, mit zwei Leerzeichen davor, wenn nicht leer. Die Pause-Angabe der Reservierungen bleibt dahinter. `ui._delete_options` und der Tooltip rufen dieselbe Funktion; `ui.py` ändert sich nicht.

- [ ] **Step 1: Tests schreiben**

```python
# tests/test_grid_renderer.py
def test_fmt_slot_line_with_category_and_note():
    slot = {"start": "08:00", "end": "12:00", "kategorie": "Montage", "notiz": "Kunde Mustermann"}
    assert GridRenderer._fmt_slot_line(slot) == "08:00-12:00  Montage · Kunde Mustermann"

def test_fmt_slot_line_note_without_category():
    slot = {"start": "08:00", "end": "12:00", "kategorie": "", "notiz": "Kunde Mustermann"}
    assert GridRenderer._fmt_slot_line(slot) == "08:00-12:00  Kunde Mustermann"

def test_fmt_slot_line_shortens_long_note():
    slot = {"start": "08:00", "end": "12:00", "kategorie": "A", "notiz": "x" * 200}
    assert GridRenderer._fmt_slot_line(slot) == "08:00-12:00  A · " + "x" * 59 + "…"

def test_tooltip_lists_notes():
    entry = {"slots": [{"start": "08:00", "end": "12:00", "kategorie": "Montage", "notiz": "Kunde Mustermann"}]}
    text = GridRenderer._build_tooltip_text(entry, None, None)
    assert text == "Arbeitszeit:\n08:00-12:00  Montage · Kunde Mustermann"

# tests/test_ui_delete.py
def test_delete_options_show_notes_and_keep_them():
    slots = [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Montage", "notiz": "Kunde Mustermann"},
             {"start": "13:00", "end": "17:00", "pause": 0, "kategorie": "Büro"}]
    options = _delete_options(slots, "entry", "Arbeitszeit", GridRenderer._fmt_slot_line)
    assert options[0] == ("entry:0", "Arbeitszeit  08:00-12:00  Montage · Kunde Mustermann")
    assert _delete_action(slots, {"entry:1"}, "entry") == ("save", [slots[0]])   # die Notiz reist im Slot mit
```

- [ ] **Step 2:** Tests scheitern lassen, dann `_fmt_slot_line` anpassen (Docstring auf die neue Form).
- [ ] **Step 3:** Die bestehenden `_fmt_slot_line`-Tests bleiben unverändert grün (ohne Notiz dieselbe Zeile).
- [ ] **Step 4: Commit** `feat(notizen): Notiz in Tooltip und Löschen-Dialog (Refs #519)`

---

### Task 4: Konfliktdialog

**Files:**
- Modify: `src/conflict_view.py`, `src/dialogs/conflicts_dialog.py`, `tests/test_conflict_view.py`, `tests/test_conflicts_dialog.py`, `tests/test_sync_notes.py`

**Interfaces (Produces):**

```python
# conflict_view.py
NO_NOTE = "keine Notiz"

@dataclass(frozen=True)
class SlotView:
    start: Field
    end: Field
    category: Field
    pause: Field
    note: Field | None = None

def entry_choice(cand: dict[str, Any]) -> dict[str, Any]: ...
```

- Kandidaten sind Rohform des Sync-Docs: die Notizen stehen unter `notes` am Kandidaten (`slot_notes.notes_of(cand)`, Schlüssel = `start` des Slots), nie im Slot.
- `note` ist `None`, wenn weder dieser Slot noch der Slot an derselben Position der anderen Karte eine Notiz hat (dann sieht die Karte aus wie heute). Sonst `Field(Notiz oder NO_NOTE, differs)`; `differs` ist wahr, wenn sich die Texte unterscheiden oder die andere Karte an der Position keinen Slot hat.
- `entry_choice`: `{"slots": cand.get("slots", []), "deleted": cand.get("deleted", False)}`, dazu `"notes": notes_of(cand)` genau dann, wenn der Kandidat nicht gelöscht ist und `slot_notes.has_key(cand)`. Ein Kandidat ohne Schlüssel liefert exakt die heutige Form (dann leitet `resolve_conflict` ab).
- `conflicts_dialog._entry_chosen(cand)` gibt `conflict_view.entry_choice(cand)` zurück. `_build_slot` hängt bei `slot.note is not None` eine dritte Zeile an: Label mit `FONT`, Farbe wie `_field`, `wraplength=px(240)`, `justify="left"`.

- [ ] **Step 1: Tests schreiben**

```python
# tests/test_conflict_view.py
def _cand(device, stamp, note=None, key=True):
    cand = {"device_id": device, "modified_at": stamp, "deleted": False,
            "slots": [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Montage"}]}
    if key:
        cand["notes"] = {"08:00": note} if note else {}
    return cand

def _cards(a, b):
    conflict = {"kind": "entry", "key": "2026-11-03", "candidates": [a, b]}
    return build_cards(conflict, {}, "dev-a")

def test_note_differs_is_marked_on_both_cards():
    own, other = _cards(_cand("dev-a", "2026-11-03T10:00:00Z", "Kunde Mustermann"),
                        _cand("dev-b", "2026-11-03T11:00:00Z", "Kunde Müller"))
    assert own.slots[0].note == Field("Kunde Mustermann", True)
    assert other.slots[0].note == Field("Kunde Müller", True)
    assert own.slots[0].category == Field("Montage", False)

def test_missing_note_reads_keine_notiz():
    own, other = _cards(_cand("dev-a", "2026-11-03T10:00:00Z", "Kunde Mustermann"),
                        _cand("dev-b", "2026-11-03T11:00:00Z", None, key=False))
    assert other.slots[0].note == Field(NO_NOTE, True)

def test_same_note_is_shown_unmarked():
    own, other = _cards(_cand("dev-a", "2026-11-03T10:00:00Z", "Kunde Mustermann"),
                        _cand("dev-b", "2026-11-03T11:00:00Z", "Kunde Mustermann"))
    assert own.slots[0].note == Field("Kunde Mustermann", False)

def test_cards_without_notes_have_no_note_field():
    own, other = _cards(_cand("dev-a", "2026-11-03T10:00:00Z", None, key=False),
                        _cand("dev-b", "2026-11-03T11:00:00Z", None, key=False))
    assert own.slots[0].note is None and other.slots[0].note is None

def test_foreign_notes_do_not_raise():
    cand = _cand("dev-a", "2026-11-03T10:00:00Z")
    cand["notes"] = ["kaputt"]
    assert _cards(cand, _cand("dev-b", "2026-11-03T11:00:00Z", "x"))[0].slots[0].note == Field(NO_NOTE, True)

def test_entry_choice_carries_notes_only_with_key():
    keyed = _cand("dev-a", "2026-11-03T10:00:00Z", "Kunde Mustermann")
    assert entry_choice(keyed) == {"slots": keyed["slots"], "deleted": False,
                                   "notes": {"08:00": "Kunde Mustermann"}}
    plain = _cand("dev-a", "2026-11-03T10:00:00Z", None, key=False)
    assert entry_choice(plain) == {"slots": plain["slots"], "deleted": False}
    assert entry_choice({"slots": [], "deleted": True, "notes": {}}) == {"slots": [], "deleted": True}
```

In `tests/test_sync_notes.py` (echte `Storage`, Aufbau wie die bestehenden `resolve_conflict`-Tests dort): ein Konflikt mit zwei Kandidaten gleicher Slots, älterer mit `notes {"08:00": "Alt"}`, jüngerer mit `{"08:00": "Neu"}`; `resolve_conflict(..., conflict_view.entry_choice(älterer), ...)` → `storage.get(tag)["slots"][0]["notiz"] == "Alt"` und `resolution["notes"] == {"08:00": "Alt"}`.

- [ ] **Step 2:** Tests scheitern lassen; `conflict_view` erweitern, dann den Dialog.
- [ ] **Step 3:** Die drei bestehenden `_entry_chosen`-Tests bleiben unverändert grün.
- [ ] **Step 4: Commit** `feat(notizen): Notiz im Konfliktdialog, gewählte Karte bestimmt die Notiz (Refs #519)`

---

### Task 5: Bericht — Zeile und Aufschlüsselung je Notiz

**Files:**
- Modify: `src/report.py`, `tests/test_report.py`, `tests/test_report_pdf_layout.py`

**Interfaces (Produces):**

```python
NO_NOTE_LABEL = "(ohne Notiz)"

def _note_rows(range_entries: dict[str, Any]) -> dict[str, list[tuple[str, int]]]: ...
def _build_category_summary(range_entries: dict[str, Any], style: dict[str, Any],
                            note_breakdown: bool = False) -> str: ...
def generate_report(..., slot_order: str = "chrono", note_breakdown: bool = False) -> tuple[str | None, float]: ...
def generate_pdf(..., slot_order: str = "chrono", note_breakdown: bool = False) -> bytes | None: ...
```

- **Zeile (`_week_block`):** die Kategorie-Zelle zeigt `_esc(slot_notes.label(kategorie, notiz))`. Keine neue Spalte.
- **`_note_rows`:** je Kategorie, in der mindestens ein Slot eine Notiz hat, die Unterzeilen `(Anzeige, Minuten)`: gruppiert nach `group_key`, Anzeige = Schreibweise des ersten Vorkommens (Tage aufsteigend nach Datum, im Tag gespeicherte Reihenfolge), sortiert nach `group_key`; Slots ohne Notiz bilden die letzte Zeile `NO_NOTE_LABEL`, die nur erscheint, wenn es solche Slots gibt. Kategorien ohne jede Notiz fehlen in der Abbildung.
- **`_build_category_summary`:** ohne `note_breakdown` Ausgabe wie heute. Mit: nach der Zeile einer Kategorie ihre Unterzeilen, derselbe Zeilenhintergrund wie die Kategorie, Zellen mit den neuen Stil-Schlüsseln. Die Regel „nur unkategorisierte Slots → keine Tabelle“ gilt weiter, außer `note_breakdown` ist an und `_note_rows` hat einen Eintrag für `""`: dann erscheint die Tabelle mit „(ohne Kategorie)“ und Unterzeilen.
- **Stil-Schlüssel** in beiden Dicts: `c_sub` (HTML `"color:#94a3b8;padding-left:32px;"`, PDF `"color:#4b5563;padding-left:28px;"`) und `c_sub_hours` (HTML `"color:#cbd5e1;"`, PDF `"color:#4b5563;"`); angehängt **nach** `td_base`, damit `padding-left` gewinnt.
- `generate_report`/`generate_pdf` reichen `note_breakdown` an `_build_category_summary` weiter; es wirkt nur zusammen mit `category_breakdown`.

- [ ] **Step 1: Tests schreiben** (`tests/test_report.py`; Helfer für Einträge wie in der Datei üblich)

```python
def _day(*slots):
    return {"slots": [dict(zip(("start", "end", "pause", "kategorie", "notiz"), s)) if len(s) == 5
                      else dict(zip(("start", "end", "pause", "kategorie"), s)) for s in slots]}

ENTRIES = {
    "2026-11-02": _day(("08:00", "12:00", 0, "Montage", "Kunde Müller"), ("13:00", "17:00", 0, "Büro")),
    "2026-11-03": _day(("08:00", "12:00", 0, "Montage", "kunde müller "), ("13:00", "15:00", 0, "Montage")),
    "2026-11-04": _day(("08:00", "10:00", 0, "Montage", "Kunde Adam")),
}

def test_note_rows_group_sort_and_first_spelling():
    assert _note_rows(ENTRIES) == {"Montage": [("Kunde Adam", 120), ("Kunde Müller", 480), ("(ohne Notiz)", 120)]}

def test_note_rows_sum_to_category_minutes():
    entries = {"2026-11-02": _day(("08:00", "08:20", 0, "A", "x"), ("09:00", "09:20", 0, "A", "y"),
                                  ("10:00", "10:20", 0, "A"))}
    assert sum(minutes for _, minutes in _note_rows(entries)["A"]) == 60

def test_row_shows_category_and_note_escaped():
    entries = {"2026-11-02": _day(("08:00", "12:00", 0, "Montage", "<b>Kunde</b> & Co"))}
    html, _ = generate_report(date(2026, 11, 2), date(2026, 11, 2), entries)
    assert "Montage · &lt;b&gt;Kunde&lt;/b&gt; &amp; Co" in html
    assert "<b>Kunde</b>" not in html

def test_summary_with_note_breakdown_lists_sub_rows_in_order():
    html = _build_category_summary(ENTRIES, HTML_STYLE, note_breakdown=True)
    order = [html.index(text) for text in ("Büro", "Montage", "Kunde Adam", "Kunde Müller", "(ohne Notiz)")]
    assert order == sorted(order)
    assert "kunde müller" not in html

def test_summary_without_flag_is_unchanged_by_notes():
    stripped = {day: {"slots": [{k: v for k, v in s.items() if k != "notiz"} for s in e["slots"]]}
                for day, e in ENTRIES.items()}
    assert _build_category_summary(ENTRIES, HTML_STYLE) == _build_category_summary(stripped, HTML_STYLE)

def test_note_breakdown_without_notes_is_bitgleich():
    stripped = {day: {"slots": [{k: v for k, v in s.items() if k != "notiz"} for s in e["slots"]]}
                for day, e in ENTRIES.items()}
    args = (date(2026, 11, 2), date(2026, 11, 4), stripped)
    assert generate_report(*args, note_breakdown=True) == generate_report(*args)

def test_uncategorised_with_notes_gets_a_table_only_with_flag():
    entries = {"2026-11-02": _day(("08:00", "12:00", 0, "", "Kunde Adam"), ("13:00", "14:00", 0, ""))}
    assert _build_category_summary(entries, HTML_STYLE) == ""
    html = _build_category_summary(entries, HTML_STYLE, note_breakdown=True)
    assert "(ohne Kategorie)" in html and "Kunde Adam" in html and "(ohne Notiz)" in html
```

In `tests/test_report_pdf_layout.py`: die Tabelle mit `note_breakdown=True` und `PDF_STYLE` beginnt weiter mit dem Zusammenhalte-Absatz (`_KEEP_WITH_NEXT`), und `c_sub`/`c_sub_hours` stehen in beiden Stil-Dicts.

- [ ] **Step 2:** Tests scheitern lassen.
- [ ] **Step 3:** `_week_block`, `_note_rows`, `_build_category_summary`, die beiden Stil-Dicts, `generate_report`, `generate_pdf`.
- [ ] **Step 4:** `pytest tests/test_report.py tests/test_report_pdf_layout.py tests/test_webhook.py -q`, dann die ganze Suite.
- [ ] **Step 5: Commit** `feat(notizen): Notiz in der Berichtszeile und Aufschlüsselung je Notiz (Refs #519)`

---

### Task 6: Option „Nach Notiz aufschlüsseln“ in Senden und Export

**Files:**
- Modify: `src/dialogs/period_picker.py`, `src/dialogs/send_dialog.py`, `src/dialogs/send_task.py`, `src/dialogs/export_dialog.py`, `src/dialogs/export_task.py`, `tests/test_period_picker.py`, `tests/test_send_task.py`, `tests/test_export_task.py`

**Interfaces:**
- Consumes: `generate_report(..., note_breakdown=...)`, `generate_pdf(..., note_breakdown=...)`, `slot_notes.has_notes`.
- Produces:

```python
# period_picker.py
def note_breakdown_active(category_on: bool, note_on: bool) -> bool: ...   # beide an
_PeriodPickerHandle.get_note_breakdown() -> bool                            # False, wenn der Schalter nicht gebaut wurde

# send_task.py / export_task.py
perform_send(..., vacation_days=None, note_breakdown=False)
perform_export_pdf(..., slot_order="chrono", note_breakdown=False)
```

Festlegungen:
- Der Schalter wird nur gebaut, wenn `slot_notes.has_notes(all_entries)` (der gefilterte Snapshot des Pickers). Er steht direkt unter „Nach Kategorie aufschlüsseln“ (Zeile 4, eingerückt `padx=(30, 10)`); die folgenden Zeilen rücken um eine Nummer.
- Er ist ausgegraut (`theme.set_enabled`), solange „Nach Kategorie aufschlüsseln“ aus ist; dessen Checkbutton bekommt dafür ein `command`. Sein gesetzter Wert bleibt beim Ausgrauen erhalten, `get_note_breakdown()` liefert trotzdem `False`.
- `send_dialog` und `export_dialog` lesen `picker.get_note_breakdown()` neben `get_category_breakdown()` und reichen den Wert an `generate_report` bzw. die Worker weiter.

- [ ] **Step 1: Tests schreiben**

```python
# tests/test_period_picker.py
@pytest.mark.parametrize("category_on,note_on,expected",
                         [(True, True, True), (True, False, False), (False, True, False), (False, False, False)])
def test_note_breakdown_needs_the_category_breakdown(category_on, note_on, expected):
    assert note_breakdown_active(category_on, note_on) is expected
```

In `tests/test_export_task.py` und `tests/test_send_task.py` (Muster der vorhandenen Tests, die `generate_pdf` ersetzen): `note_breakdown=True` kommt bei `generate_pdf` als Schlüsselwort an; ohne das Argument kommt `False` an.

- [ ] **Step 2:** Tests scheitern lassen, dann die fünf Module anpassen.
- [ ] **Step 3:** ganze Suite, `ruff`, `pyright`.
- [ ] **Step 4: Commit** `feat(notizen): Option „Nach Notiz aufschlüsseln“ in Senden und Export (Refs #519)`

---

### Task 7: Doku und Gesamtprüfung

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `src/CLAUDE.md`

- [ ] **Step 1: README**, Abschnitt „Features“ nach „Kategorien“: `- **Notiz am Slot** *(ab --VERSION--)* — …` (eine Zeile: optionale, einzeilige Notiz je Zeitblock, die eine Kategorie verfeinert, z. B. Kategorie „Montage“, Notiz „Kunde Mustermann“; mit Vorschlägen aus bereits benutzten Notizen; erscheint in Tooltip, Bericht und Webhook; der Bericht kann die Summe je Kategorie zusätzlich je Notiz aufschlüsseln). Die Zeile „PDF-Report“ bleibt unverändert.
- [ ] **Step 2: `CLAUDE.md` (Wurzel), „Struktur“:** im Eintrag `src/dialogs/` bei `slot_rows` das Notizfeld nennen; im Eintrag `src/conflict_view.py` die Notiz als Feld und `entry_choice`; im Eintrag `src/report.py` die Notiz in der Kategorie-Zelle und die Aufschlüsselung; im Eintrag `src/slot_notes.py` die Anzeige-Helfer. Gegenwart, keine Historie; `tests/test_claude_md_claims.py` bleibt grün.
- [ ] **Step 3: `src/CLAUDE.md`:** Abschnitt „Dialoge“ (Tages-Dialog: Notizfeld, ausdrückliches `notiz` an jedem Slot und warum; Konfliktdialog: `entry_choice` und warum die Notizen ausdrücklich mitgehen; Zeitraum-Baustein: Schalter nur mit Notizen im Bestand).
- [ ] **Step 4: Gesamtprüfung:** `.venv/bin/python -m pytest -q`, `ruff check .`, `pyright` wie oben, `cd pwa && node --test` (unverändert 1393).
- [ ] **Step 5: Commit** `docs(notizen): Tages-Dialog, Konfliktdialog und Bericht beschreiben (Refs #519)`

**Von Hand zu prüfen** (Tk wird nicht automatisiert getestet; die Liste gehört in den PR-Text):
1. Tages-Dialog: Notiz eintragen, speichern, wieder öffnen; Notiz leeren und speichern; 201 Zeichen einfügen → Meldung.
2. Vorschläge: zweiter Tag, gleiche Kategorie → das Feld bietet die Notiz an; andere Kategorie → nicht. Mausrad über dem Feld ändert nichts. Der Cursor im Feld ist sichtbar.
3. Modus „Eigene Reihenfolge“: ▲/▼ nimmt die Notiz mit.
4. Tooltip der Kalenderzelle und Rechtsklick-Dialog bei zwei Slots zeigen `Kategorie · Notiz`.
5. Senden/Export: Schalter erscheint erst mit einer Notiz im Bestand, ist ohne „Nach Kategorie aufschlüsseln“ ausgegraut; PDF mit Unterzeilen ansehen (Einrückung, Seitenumbruch).
6. Dialogbreite bei 100 % und 150 % Skalierung.
