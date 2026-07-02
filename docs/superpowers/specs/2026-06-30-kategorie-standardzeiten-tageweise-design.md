# Standardzeiten pro Kategorie wahlweise tageweise (pro Wochentag)

**Datum:** 2026-06-30
**Issue:** #84
**Baut auf:** `2026-06-21-kategorie-standardzeiten-design.md` (Ein-Satz-Override pro
Kategorie) und `2026-05-08-per-weekday-default-times-design.md` (globale Defaults
pro Wochentag).

## Ziel

Pro Kategorie soll der Standardzeiten-Override **wahlweise** sein:

- **Allgemein** (Default, heutiges Verhalten): ein Satz `{start, end, pause}` für die
  ganze Kategorie. Unverändert abwärtskompatibel.
- **Tageweise**: Start/Ende **pro Wochentag** Mo–So, analog zu den globalen
  Standardzeiten. Die **Pause bleibt ein Wert** pro Kategorie (nicht pro Tag —
  symmetrisch zur globalen `default_pause`, die bewusst nicht pro Tag ist).

Der Per-Feld-Fallback auf die globalen (bereits pro Wochentag bestimmten) Defaults
bleibt in beiden Modi erhalten. Der Modus wird **pro Kategorie** umgeschaltet.

Begründung: Die globalen Defaults sind schon pro Wochentag (langer Montag, kurzer
Freitag, Sa/So 0 h). Eine Kategorie mit eigenem Override muss diese Tagesstruktur
aktuell auf einen Satz kollabieren — das passt nicht für Kategorien mit eigenem
Wochenrhythmus. Diese Erweiterung zieht die schon global existierende
Per-Wochentag-Granularität auf die Kategorie-Ebene nach. Die Spec von 2026-06-21 hat
das explizit als YAGNI ausgeschlossen; dieses Issue holt es als konkreten Bedarf nach.

## Datenmodell

Der bestehende synchronisierte Settings-Key `category_times` (Dict) bleibt, bekommt
aber **zwei mögliche Eintrags-Formen**, unterschieden am `mode`-Key:

```jsonc
"category_times": {
  // Allgemein (= heute, unverändert): KEIN mode-Key
  "Office_1": { "start": "09:30", "end": "17:00", "pause": 30 },

  // Tageweise: mode-Flag + days-Dict; Pause ist EIN Wert (top-level)
  "Homeoffice": {
    "mode": "per_day",
    "pause": 0,
    "days": {
      "mon": { "start": "09:00", "end": "18:00" },
      "tue": { "start": "09:00", "end": "18:00" },
      "wed": { "start": "09:00", "end": "18:00" },
      "thu": { "start": "09:00", "end": "18:00" },
      "fri": { "start": "09:00", "end": "14:00" }
      // fehlende Tage (sat/sun) → Fallback auf globalen Wochentags-Standard
      // fehlendes Feld innerhalb eines Tages → Per-Feld-Fallback auf global
    }
  }
}
```

**Regeln:**

- **`mode` fehlt ⇒ „allgemein".** Nur der literale String `"per_day"` aktiviert den
  tageweise-Pfad; jeder andere/fehlende Wert ist allgemein. Das ist die **gesamte**
  Abwärtskompatibilität: Bestandseinträge tragen kein `mode` und werden ohne jede
  Transformation weiter als allgemein interpretiert.
- **Per-Feld/-Tag-Fallback:** Fehlt im tageweise-Modus ein Tag in `days` oder ein
  Start/Ende innerhalb eines Tages, gilt der globale Wochentags-Standard für genau
  dieses Feld. `pause` fehlt/leer → globale `default_pause`.
- `days`-Keys sind `WEEKDAY_KEYS` (`mon`…`sun`, Index = `datetime.weekday()`).
- `DEFAULTS["category_times"]` bleibt `{}`.
- `category_times` ist **bereits** in `SYNCED_SETTING_KEYS` (`settings.py:11`) — für
  #84 ist an der Whitelist **nichts** zu tun. Die Liste lebt **nur** in `settings.py`;
  `sync.py` **importiert** sie (Single Source of Truth, Issue #48 — kein Duplikat,
  `sync.py:16–21`). LWW-Merge behandelt den Dict-Wert weiter als Ganzes.

**Kein Lade-Migrationscode nötig.** `Settings._load` → `_coerce` lässt Dict-Werte
unverändert durch (verifiziert in `settings.py:62–83`, der Dict-Default-Pfad castet
nicht). Die innere Struktur von `category_times` wird also unverändert geladen und
gespeichert — Migration ist reine *Interpretations*-Logik in `resolve_slot_defaults`,
keine Daten-*Transformation* beim Laden.

## Pure Logik

### `src/category_defaults.py::resolve_slot_defaults`

Neuer Parameter `weekday_key` (der Aufrufer kennt ihn bereits):

```python
def resolve_slot_defaults(category_times, kategorie, weekday_key,
                          g_start, g_end, g_pause):
    """(start, end, pause) für einen Slot der Kategorie am gegebenen Wochentag.

    - mode == "per_day": Start/Ende aus days[weekday_key] (Per-Feld-Fallback auf
      g_start/g_end), Pause aus top-level "pause" (Fallback g_pause).
    - sonst (mode fehlt / != "per_day"): heutiger Ein-Satz-Pfad, bit-identisch.
    Per-Feld-Fallback auf die globalen Werte überall, wo ein Feld leer/None/ungültig
    oder die Kategorie/der Tag unbekannt ist. pause=0 bleibt gültig.
    """
```

- `g_start/g_end` sind weiterhin die schon **wochentags-aufgelösten** Globalwerte, die
  `entry_dialog` aus `default_start_{weekday_key}` reinreicht. `weekday_key` dient
  hier ausschließlich dazu, den richtigen Tagessatz **innerhalb der Kategorie** zu
  wählen.
- Der allgemein-Zweig bleibt verhaltensgleich zu heute; die 9 Bestandstests prüfen
  weiter dieselben Ergebnisse (nur der zusätzliche Parameter wird in den Aufrufen
  ergänzt).
- Defensiv: ist `days` kein Dict oder `days[weekday_key]` kein Dict → kompletter
  Fallback auf die Globalwerte (kein Crash bei korruptem Eintrag).

### `src/dialogs/category_dialog.py::collect_categories`

Liest pro Zeile zusätzlich den Modus und (bei tageweise) das 7-Tage-Grid:

```python
# rows-Eintrag (Roh-Strings der Widgets):
{
  "name": str,
  "mode": "general" | "per_day",
  "start": str, "end": str,          # allgemein-Felder
  "pause": str,                       # in beiden Modi (eine Pause-Combo)
  "days": {"mon": {"start": str, "end": str}, ...},  # nur tageweise
}
```

- **allgemein:** wie heute — `{start?, end?, pause?}`, STANDARD/leer entfällt.
- **tageweise:** `{mode:"per_day", pause?, days:{tag:{start?,end?}}}`. In `days`
  landen nur Tage mit mindestens einem gesetzten (Nicht-STANDARD-)Feld; leere Felder
  entfallen → Per-Feld-Fallback.
- **Leerer Eintrag entfällt** (komplett globaler Fallback): allgemein mit allen drei
  Feldern STANDARD **oder** tageweise ohne ein einziges gesetztes Tagesfeld und ohne
  Pause → kein `category_times`-Eintrag für diese Kategorie. Hält das Dict schlank,
  konsistent zum heutigen Verhalten.
- Namen weiter getrimmt, ohne Leere, dedupliziert (erstes Vorkommen gewinnt).

### `src/dialogs/category_dialog.py::row_defaults_from_entry` (neu, pure)

Umkehrung von `collect_categories` **pro Zeile**: ein `category_times[name]`-Eintrag →
die Vorbelegungs-Strings einer Dialog-Zeile. Heute liegt diese Hydration inline und
liest nur flache Felder (`category_dialog.py:185–194`); für `per_day` muss sie Modus,
Pause **und** alle `days` korrekt zurück in die Widgets bringen.

```python
def row_defaults_from_entry(entry):
    """category_times[name]-Eintrag → {mode, start, end, pause, days} (Roh-Strings/
    STANDARD) zur Widget-Vorbelegung. Fehlende Felder → STANDARD. Defensiv gegen
    Nicht-Dict / korrupte Struktur (→ allgemein, alles STANDARD)."""
```

Damit wird der **Round-Trip** Tk-frei prüfbar: ein persistierter Eintrag, durch
`row_defaults_from_entry` hydriert und unverändert durch `collect_categories` zurück,
muss **bit-identisch** wieder herauskommen (Schutz gegen die Plättung beim No-op-Save).
Der Tk-Teil im Dialog ist dann nur noch: Helfer aufrufen → Werte in StringVars/Grid
gießen.

### `src/dialogs/category_dialog.py::categories_losing_per_day` (neu, pure)

Entscheidet Tk-frei, welche Kategorien beim Speichern Tagesdaten verlören (Basis für
den Downgrade-Confirm, Finding #84):

```python
def categories_losing_per_day(rows):
    """Namen der Zeilen, die im Modus 'general' stehen, aber noch >=1 gesetztes
    (Nicht-STANDARD-)Tagesfeld in 'days' tragen (= versteckte per_day-Daten, die
    ein Save als allgemein verwerfen würde). Leere Liste → kein Verlust."""
```

Greift, weil der Toggle die `days`-Widgets nur versteckt (StringVars bleiben); eine
frische allgemein-Kategorie hat keine gesetzten `days` → löst nicht aus.

## Entry-Dialog (`src/dialogs/entry_dialog.py`)

`weekday_key` ist bereits vorhanden (`:48`). Beide `resolve_slot_defaults`-Aufrufe
(`:123` Ist-Slot, `:233` Reservierungs-Slot) reichen ihn zusätzlich durch. Sonst
**keine** Änderung — der `<<ComboboxSelected>>`-Trigger und das Basis-/Manuell-Modell
bleiben unverändert. Reservierungen nutzen weiter nur Start/Ende (keine Pause).

## UI — Kategorien-Dialog (`src/dialogs/category_dialog.py`)

Pro Kategorie-Zeile ein Modus-Umschalter. Im tageweise-Modus klappt — analog zum
**bereits existierenden** „Pro Tag ▶"-Toggle der globalen Referenzzeile
(`category_dialog.py:135–162`, dort read-only) — ein **editierbares** 7-Tage-Grid auf.
Das Fenster passt seine Höhe automatisch an (wie der bestehende Toggle).

```
Allgemein (heute):
[Name] [Modus: Allgemein ▾] [Start]–[Ende] [Pause] [×]

Tageweise:
[Name] [Modus: Tageweise ▾] [Pause] [Pro Tag ▼] [×]
        Mo [09:00]–[18:00]
        Di [09:00]–[18:00]
        …                      (leeres Feld = „(Standard)" → globaler Tageswert)
        So [(Standard)]–[(Standard)]
```

- Modus-Umschalter als kleine Combo/Toggle pro Zeile (`Allgemein` / `Tageweise`).
- Pause bleibt **eine** Combo pro Kategorie, auch tageweise (top-level).
- Jede Zeit-Combo hat weiter `"(Standard)"` als ersten Eintrag (Per-Feld-Fallback);
  `TIME_VALUES`/`PAUSE_VALUES` werden nicht global mutiert.
- **Umschalten allgemein → tageweise:** der eine Satz wird auf alle 7 Tage
  **gespiegelt** (vorbefüllt), damit der Nutzer von sinnvollen Werten aus editiert
  statt von leer — analog zur globalen Legacy-Spiegelung
  (`_migrate_legacy_default_times`).
- **Umschalten tageweise → allgemein:** die allgemein-Combo wird mit dem
  **Montags-Satz** vorbefüllt (erster Werktag, vorhersehbar). Die Tages-Widgets werden
  beim Umschalten **versteckt, nicht zerstört** (`pack_forget`, StringVars bleiben) —
  Toggle hin-und-zurück innerhalb derselben Dialog-Session verliert also **nichts**.
  Der Modus bestimmt, was **gespeichert** wird: bei „Allgemein" liest
  `collect_categories` nur die Start/Ende/Pause-Zeile, die (versteckten) `days` werden
  **nicht** persistiert. Der Verlust tritt damit erst beim tatsächlichen Speichern im
  allgemein-Modus ein und wird dort durch den **Downgrade-Confirm** (s.u.,
  `categories_losing_per_day`) abgefangen. Bewusst **kein** persistentes „inaktiv
  mitschleppen" im JSON (kein Datenmodell-Change, YAGNI).
- Speichern liest alle Zeilen-Widgets in Roh-Dicts. **Vor** dem Persistieren prüft
  `categories_losing_per_day(rows)` (pure, s.u.), ob eine Zeile im **allgemein**-Modus
  noch gesetzte (versteckte) Tagesfelder trägt — dann gingen beim Speichern Tagesdaten
  verloren. Ist die Liste nicht leer, fragt ein `themed_askyesno` mit den betroffenen
  Kategorie-Namen nach; bricht der Nutzer ab, wird **nicht** gespeichert. Danach
  `collect_categories` → `categories` + `category_times` via `set_synced`.

## Sync-Schema-Version (v3 → v4) — Schutz vor Datenverlust

**Problem (verifiziert, Codex-Review #84):** `category_times` wird als ganzer Dict per
LWW gemergt. Ohne Gegenmaßnahme würde ein **pre-#84-Client** einen `per_day`-Eintrag
zwar crashfrei laden (top-level `start`/`end` fehlen → graceful Fallback auf global),
ihn aber bei einem Edit der Kategorie über sein altes `collect_categories` zu einem
flachen Eintrag **plätten** und zurücksynchronisieren → **stiller, unwiederbringlicher
Verlust** der Tagesdaten. Ein neuer Parallel-Key hilft nicht: `sync.merge` iteriert
über die *lokale* `SYNCED_SETTING_KEYS`-Whitelist (`sync.py:184`); einen Key, den der
alte Client nicht kennt, lässt er beim Push **ganz weg** (Verlust ohne Edit).

**Lösung:** Den etablierten dokumentweiten Forward-Compat-Guard nutzen.

- **`sync.SCHEMA_VERSION = 3 → 4`** (nur der Sync-Wert; `share.SCHEMA_VERSION` ist ein
  **separates** Schema und bleibt 3).
- Damit greift `_remote_is_newer` (`sync.py:322`) automatisch: sobald ein #84-Client
  ein Doc mit `schema_version 4` gepusht hat, brechen Pull/Push/Compaction auf einem
  pre-#84-Client (v3) sauber ab (`NEWER_REMOTE_VERSION_MSG`) — **kein Merge, kein
  Überschreiben**. Der alte Client kann die `per_day`-Daten nicht mehr plätten.
- **Preis (bewusst akzeptiert):** Bei Versions-Skew pausiert der **gesamte** Sync
  (auch Entries) auf dem Altgerät, bis es aktualisiert ist — exakt das Verhalten, das
  schon bei v2→v3 etabliert wurde und das `NEWER_REMOTE_VERSION_MSG` dem Nutzer
  erklärt. Anders als v2→v3 ist #84 kein *struktureller* Bruch (kein Crash), aber der
  Guard ist der einzige robuste Schutz gegen den Verlustpfad.
- **`migrate_doc_to_v3` → `migrate_doc_to_current`** umbenennen (Name wird sonst
  falsch). Die **entry**-Logik bleibt unverändert (v1/v2 flache Einträge → Slots);
  ein v3-Doc ist vollständig v4-kompatibel (per_day ist additiv/optional in den
  Settings), wird also idempotent durchgereicht und nur die `schema_version` auf
  `SCHEMA_VERSION` (=4) gehoben. **Keine** Settings-Migration im Doc nötig.
- Alle drei Aufrufstellen (`main.py:97/150/214`) rufen die umbenannte Funktion;
  `_remote_is_newer`/`NEWER_REMOTE_VERSION_MSG` bleiben unverändert.

## Tests

- `tests/test_category_defaults.py`: Signatur um `weekday_key` ergänzen; neue Fälle:
  - per_day wählt den richtigen Tagessatz (Mo vs. Fr),
  - fehlender Tag in `days` → globaler Fallback,
  - fehlendes Start/Ende innerhalb eines Tages → Per-Feld-Fallback,
  - `pause` top-level greift / fehlt → globale Pause; `pause=0` bleibt,
  - `mode` fehlt bzw. `mode != "per_day"` → allgemein-Pfad (Bestandsverhalten),
  - korruptes `days` / Nicht-Dict-Tag → kompletter Fallback.
- `tests/test_category_dialog.py`: `collect_categories` baut allgemein **und** per_day:
  - tageweise mit Teil-Tagen, leeren Feldern, pause top-level,
  - leerer per_day-Eintrag (keine Tagesfelder, keine Pause) entfällt,
  - allgemein-Pfad unverändert (Bestandstests bleiben).
- `tests/test_category_dialog.py`: **Round-Trip Hydration↔Serialisierung** (Finding #84):
  - `row_defaults_from_entry`: per_day-Eintrag → Modus/Pause/alle days korrekt; flacher
    Eintrag → allgemein; korrupt/Nicht-Dict → allgemein-STANDARD,
  - **No-op-Erhalt:** `collect_categories([{"name": n, **row_defaults_from_entry(e)}])`
    liefert `([n], {n: e})` **bit-identisch** für einen persistierten per_day- **und**
    einen allgemein-Eintrag — beweist, dass Öffnen+Speichern ohne Änderung nichts plättet.
  - `categories_losing_per_day`: general-Zeile mit gesetzten `days` → Name in Liste;
    general-Zeile ohne `days` → leer; per_day-Zeile (Modus aktiv) → leer (kein Verlust).
- Settings/Sync-Smoke: `category_times` mit `per_day`-Struktur synct/lädt unverändert
  (Dict bleibt als Ganzes).
- `tests/test_sync.py` / `tests/test_storage_migration.py`: Schema-Bump v3→v4:
  - `SCHEMA_VERSION == 4`; auf `3` hartcodierte Asserts auf `4` bzw. besser auf
    `SCHEMA_VERSION` umstellen (`test_sync.py:293,685,808`, `test_storage_migration.py:135–136`),
  - `migrate_doc_to_v3`-Tests auf den neuen Namen `migrate_doc_to_current` ziehen;
    Verhalten unverändert (v1/v2-flach → Slots, v3 idempotent, `schema_version`=4),
  - `test_remote_is_newer` bleibt grün (relativ via `SCHEMA_VERSION ± 1` formuliert).

## Bewusst nicht enthalten (YAGNI)

- **Pause pro Wochentag** — bleibt ein Wert pro Kategorie (symmetrisch zu global).
  Bei späterem Bedarf separat nachrüstbar (Issue-Notiz, nicht hier).
- **Persistentes** Mitschleppen der Tagesdaten im JSON nach Speichern im allgemein-
  Modus (Session-Retention via „verstecken statt zerstören" **plus** Downgrade-Confirm
  reichen).
- Profile (Sommer/Winter, Urlaubsmodus) — wie bei den globalen Defaults.
