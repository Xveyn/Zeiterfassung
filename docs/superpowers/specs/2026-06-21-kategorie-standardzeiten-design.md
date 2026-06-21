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

## Pure Logik — `src/category_defaults.py` (neu, testbar)

```python
def resolve_slot_defaults(category_times, kategorie, g_start, g_end, g_pause):
    """(start, end, pause) mit Per-Feld-Fallback auf die globalen Werte."""

def rename_category_times(times, old, new):
    """Verschiebt den Time-Eintrag old→new. Liefert neues Dict."""

def remove_category_times(times, name):
    """Entfernt den Time-Eintrag. Liefert neues Dict."""
```

- Leere Strings / fehlende Keys im Eintrag → Fallback pro Feld.
- `pause`: leer/None → globale Pause; sonst int.
- `rename`: No-op wenn `old` keinen Eintrag hat; überschreibt vorhandenen
  `new`-Eintrag nicht (konsistent zur `rename_category`-Semantik).

## UI — Kategorien-Dialog (`src/dialogs/category_dialog.py`)

Unter der Kategorie-Liste erscheinen drei Combos **Start / Ende / Pause** für die
aktuell selektierte Kategorie. Jede Combo hat als **ersten** Eintrag die Option **„(Standard)"** — ein
literaler Combo-Wert, der beim Speichern als **leerer String** im Eintrag
landet (bzw. das Feld weglässt) und so den Per-Feld-Fallback auf global
auslöst. Beim Laden eines leeren/fehlenden Feldes wird „(Standard)" angezeigt.
`TIME_VALUES` / `PAUSE_VALUES` (theme.py, reine String-Listen) werden NICHT
global mutiert — „(Standard)" wird nur lokal in diesen Dialog-Combos
vorangestellt (`["(Standard)", *TIME_VALUES]`).

- Eine `category_times`-Kopie wird beim Öffnen geladen:
  `category_times = dict(settings.get("category_times") or {})` — parallel zur
  bestehenden lokalen `categories`-Liste, im selben `nonlocal`-Scope mutiert.
- Listbox-Auswahl wechselt (`<<ListboxSelect>>`-Binding, existiert noch nicht)
  → Felder aus dem In-Memory-`category_times` laden.
- **Vorherige Auswahl** wird in einem Holder (`prev_sel = [None]`) gemerkt, weil
  Tk im Select-Event nur die NEUE Auswahl liefert. Der Handler schreibt zuerst
  die aktuellen Feldwerte in den Eintrag der `prev_sel`-Kategorie zurück, lädt
  dann die neue und setzt `prev_sel[0]` auf die neue Kategorie. Auch `on_save`
  schreibt die Felder der aktuell selektierten Kategorie final zurück.
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
  Kategorie, rename/remove der Time-Keys, pause-Coercion.
- Settings/Sync: `category_times` ist whitelisted und synct (Smoke).

## Bewusst nicht enthalten (YAGNI)

- Keine Per-Wochentag-Zeiten pro Kategorie.
- Kein Auto-Anwenden beim Tippen abseits exakter Kategorie-Treffer.
