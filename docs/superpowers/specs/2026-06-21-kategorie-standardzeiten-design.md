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
aktuell selektierte Kategorie. Jede Combo hat eine Leer-Option **„(Standard)"**
= globaler Fallback (leerer gespeicherter Wert).

- Listbox-Auswahl wechselt → Felder aus dem In-Memory-`category_times` laden.
- Vor dem Wechsel: aktuelle Feldwerte in das In-Memory-Dict der vorher
  selektierten Kategorie zurückschreiben.
- Sind alle drei Felder „(Standard)" → Kategorie-Eintrag wird entfernt
  (komplett globaler Fallback).
- **Speichern** persistiert `categories` UND `category_times` via `set_synced`.
- **Umbenennen** zieht den `category_times`-Key per `rename_category_times` nach,
  **Entfernen** per `remove_category_times`.

## UI — Tages-Dialog (`src/dialogs/entry_dialog.py`)

Pro Slot-Zeile wird die zuletzt automatisch gesetzte Default-Basis gemerkt
(`base_start/base_end/base_pause`), initial die globalen Standardzeiten des
Wochentags (bzw. die Werte, mit denen die Zeile angelegt wurde).

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
