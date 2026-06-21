# Standardzeiten & Pause pro Kategorie

**Datum:** 2026-06-21
**Branch / PR:** `feat/multi-timeslots-kategorien` (PR #60)

## Ziel

Pro Kategorie konfigurierbare Standard-Start-/Endzeit und Pause. Die globalen
Standardzeiten bleiben bestehen und gelten weiterhin, wenn ein Slot **keine**
Kategorie hat oder die Kategorie für das jeweilige Feld nichts konfiguriert hat.
Manuell geänderte Felder im Tages-Dialog werden nie überschrieben.

Granularität: **ein Satz (Start/Ende/Pause) pro Kategorie**, nicht pro Wochentag.

## Datenmodell

Neuer synchronisierter Settings-Key `category_times` (Dict), parallel zur
bestehenden `categories`-Liste. Die `categories`-Liste bleibt unverändert eine
Liste von Strings — Report, Send-Dialog und die Combos lesen sie weiter direkt.

```json
"category_times": {
  "Office":     {"start": "08:00", "end": "16:30", "pause": 30},
  "Homeoffice": {"start": "09:00", "end": "17:00", "pause": 0}
}
```

- **Per-Feld-Fallback:** Fehlt/leer ein Feld → globaler Standard für genau
  dieses Feld. Kategorie nicht im Dict → komplett global.
- `DEFAULTS["category_times"] = {}`.
- Aufgenommen in `SYNCED_SETTING_KEYS` in **`src/settings.py` und `src/sync.py`**
  (das Duplikat muss konsistent bleiben). LWW-Merge behandelt den Dict-Wert als
  Ganzes, wie bei `categories`.
- `_coerce` lässt Dicts unverändert durch (wie die `categories`-Liste).

## Pure Logik

`src/category_defaults.py` (neu, testbar):

```python
def resolve_slot_defaults(category_times, kategorie, g_start, g_end, g_pause):
    """(start, end, pause) mit Per-Feld-Fallback auf die globalen Werte."""
```

- Leere Strings / fehlende Keys im Eintrag → Fallback pro Feld.
- `pause`: leer/None → globale Pause; sonst int.

`src/dialogs/category_dialog.py::collect_categories(rows)` (pure, testbar):

```python
def collect_categories(rows):
    """rows: [{name, start, end, pause}] (Roh-Strings der Zeilen-Widgets)
    → (categories, category_times).
    Namen getrimmt, ohne Leere, dedupliziert (erstes Vorkommen gewinnt).
    STANDARD/leere Felder entfallen → Per-Feld-Fallback. pause → int."""
```

## UI — Kategorien-Dialog (`src/dialogs/category_dialog.py`)

**Inline-Zeilen-Modell wie der Tages-Dialog** (Entscheidung 2026-06-21): keine
separate Listbox + Detail-Sektion mehr, sondern **eine Zeile pro Kategorie** mit
allen Feldern direkt drin:

```
[Name-Entry] [Start-Combo] – [Ende-Combo] [Pause-Combo] [×]
```

Darunter ein **„+ Kategorie"**-Button (legt leere Zeile an) und Speichern/
Schließen. Umbenennen = Name-Feld editieren, Entfernen = ×-Button. Die früheren
`add/rename/remove_category`-Helfer und die Listbox/`prev_sel`-Logik entfallen.

- Beim Öffnen werden `categories` + `category_times` geladen und je Kategorie
  eine vorbefüllte Zeile erzeugt (Zeit-Felder aus `category_times`, sonst
  „(Standard)"). Ohne Kategorien: eine leere Startzeile.
- Jede Zeit-Combo hat als **ersten** Eintrag **„(Standard)"** — ein literaler
  Wert, der beim Speichern als fehlendes Feld abgelegt wird (Per-Feld-Fallback
  auf global). `TIME_VALUES` / `PAUSE_VALUES` werden NICHT global mutiert —
  „(Standard)" nur lokal vorangestellt (`["(Standard)", *TIME_VALUES]`).
- **Speichern** liest alle Zeilen-Widgets in Roh-Dicts, ruft `collect_categories`
  und persistiert `categories` + `category_times` via `set_synced`.
- Sind alle drei Felder „(Standard)" → Kategorie-Eintrag wird entfernt
  (komplett globaler Fallback).
- **Speichern** persistiert `categories` UND `category_times` via `set_synced`.
- **Umbenennen** zieht den `category_times`-Key per `rename_category_times` nach,
  **Entfernen** per `remove_category_times`.

## UI — Tages-Dialog (`src/dialogs/entry_dialog.py`)

Pro Slot-Zeile wird die zuletzt automatisch gesetzte Default-Basis gemerkt
(`base_start/base_end/base_pause`). **Die Basis sind exakt die Werte, mit denen
die Zeile angelegt wurde** — NICHT pauschal die globalen Standardzeiten:
- Erste/aus Reservierung übernommene Ist-Zeile: globaler Start/Ende +
  `default_pause` (entry_dialog.py:115/117).
- „+ Slot"-Ist-Zeile: globaler Start/Ende, **`pause=0`** (entry_dialog.py:123).
- Geladene bestehende Zeile: die gespeicherten Slot-Werte.

Die Basis wird in `add_ist_row` / `add_res_row` aus den übergebenen
Start/Ende/Pause-Argumenten gesetzt, damit jede Zeile ihre eigene korrekte
Basis hat.

Bei **Kategorie-Wechsel** (Trace auf der `kategorie`-StringVar der Zeile):
1. Zielwerte via `resolve_slot_defaults(...)` bestimmen.
2. Pro Feld (Start/Ende/Pause): **nur überschreiben, wenn aktueller Feldwert ==
   gemerkte Basis** (unverändert). Dann Feldwert setzen UND Basis auf den neuen
   Zielwert nachziehen.
3. Weicht ein Feld ab (manuell) → unangetastet; Basis bleibt, Feld bleibt
   dauerhaft manuell.

Gilt für **Ist-Slots** (Start/Ende/Pause). **Reservierungs-Slots** analog, aber
nur Start/Ende (Reservierungen haben keine Pause).

Der Trace wird erst **nach** dem initialen `kv.set(...)` registriert, damit die
Vorbelegung nicht selbst triggert. Auto-Anwenden nur bei exaktem Treffer einer
bekannten Kategorie.

## Tests

- `tests/test_category_defaults.py`: Per-Feld-Fallback, leere Felder, unbekannte
  Kategorie, pause-Coercion, Nicht-Dict-Eintrag.
- `tests/test_category_dialog.py`: `collect_categories` — Dedup, Reihenfolge,
  leere/getrimmte Namen, partielle Zeilen, pause=0, mehrere Kategorien.
- Settings/Sync: `category_times` ist whitelisted und synct (Smoke).

## Bewusst nicht enthalten (YAGNI)

- Keine Per-Wochentag-Zeiten pro Kategorie.
- Kein Auto-Anwenden beim Tippen abseits exakter Kategorie-Treffer.
