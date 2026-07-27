# Nur Werktage: Wochenende komplett deaktivieren

**Datum:** 2026-07-28
**Status:** entworfen, freigegeben

## Problem

`show_weekend` (Default an, gerätelokal, App-Tab) blendet Sa/So heute **nur im
Kalender** aus: `grid_renderer._visible_day_count()` liefert dann 5 statt 7
Spalten. Alles andere kennt den Schalter nicht:

- Die **Standardzeiten** im Arbeitszeit-Tab zeigen weiter alle sieben Tage.
- **Mailversand, PDF-Export und die Stunden-Vorschau** nehmen Wochenend-Einträge
  unverändert mit.

Wer nicht am Wochenende arbeitet, hat also einen halb ausgeblendeten Zustand: im
Kalender weg, im Bericht drin. Alt-Einträge aus der Zeit vor der Umstellung
tauchen still im Bericht auf.

## Lösung

Eine Einstellung **`workweek_only`** (bool, Default `false`), die das Wochenende
überall deaktiviert. Die Daten für Sa/So bleiben unangetastet — sie werden nur
nirgends mehr gezeigt oder mitgerechnet.

### Entscheidungen

| Frage | Entscheidung | Grund |
|---|---|---|
| Name | `workweek_only`, positiv formuliert | Eine negative Flag (`weekend_disabled`) müsste im Code ständig negiert werden, im Zusammenspiel mit dem ebenfalls negativ wirkenden `show_weekend` doppelt. |
| Synchronisiert? | **Ja**, in `SYNCED_SETTING_KEYS` | Wie `werkstudent_limit_*` und `pause_warning_enabled` eine Aussage über das Arbeitsmodell, nicht über das Gerät — und sie bestimmt den Berichtsinhalt. Gerätelokal hieße: zwei Geräte, zwei verschiedene Berichte aus denselben Daten. |
| Werkstudenten-Limit | **unberührt**, zählt Wochenenden weiter | Das Limit bildet real geleistete Stunden gegen eine gesetzliche Grenze ab. Wer samstags arbeitet, hat die Stunden geleistet — unabhängig davon, ob sie im Bericht stehen. |
| Teilen (Share-JSON) und Kalender-Abgleich | **unberührt** | Teilen überträgt Rohdaten zum Import beim Empfänger; dort zu filtern hieße Datenverlust auf der Gegenseite. Der Kalender-Abgleich betrifft Reservierungen, nicht den Bericht. |
| Ausgeblendete Einträge im Zeitraum | **Hinweiszeile** im Sende-/Export-Dialog | Sonst verlöre jemand mit Alt-Daten stillschweigend Stunden aus dem Bericht. |

### UI

Checkbox **„Nur Werktage — Wochenende (Sa/So) komplett deaktivieren"** im
**Arbeitszeit**-Tab, über den Standardzeiten: sie beschreibt, was die Arbeitswoche
*ist*, und steht damit bei den anderen Arbeitszeit-Regeln (Standardpause,
Pausenpflicht, Werkstudenten-Limit).

Im **App**-Tab wird die vorhandene Checkbox „Wochenende (Sa/So) im Kalender
anzeigen" bei aktivem `workweek_only` **deaktiviert** (`state="disabled"`) und
bekommt darunter den gedämpften Hinweis „Durch „Nur Werktage" (Arbeitszeit)
überstimmt." — sonst steht dort ein Schalter, der sichtbar nichts tut.

## Wirkorte

### 1. Kalender

`grid_renderer._visible_day_count()` liefert 5, sobald `workweek_only` **oder**
`show_weekend=False`:

```python
if self._settings.get("workweek_only"):
    return 5
return 7 if self._settings.get("show_weekend") else 5
```

Die Footer-Summe stimmt dadurch automatisch: sie zählt seit jeher nur die
tatsächlich gerenderten Zellen (`total_minutes` wächst in den Zell-Schleifen).

`measure_max_width` probt beide `show_weekend`-Varianten über
`settings.override_in_memory` — bei aktivem `workweek_only` sind beide Proben
5-spaltig, das Fenster wird also passend schmaler gepinnt. Kein Sonderfall nötig.

### 2. Bericht, PDF, Mail und Vorschau

Alle drei Pfade holen ihre Daten über `storage.get_all()`:

| Datei | Zeile | wohin |
|---|---|---|
| `dialogs/send_dialog.py` | 100 | `generate_report` (Mail-HTML) + `perform_send` → `generate_pdf` |
| `dialogs/export_dialog.py` | 47 | `perform_export_pdf` → `generate_pdf` |
| `dialogs/period_picker.py` | 93 | `total_hours` (Live-Vorschau) |

Gefiltert wird deshalb **am Snapshot**, nicht in `report.py`:

```python
entries = workweek.filter_for_report(storage.get_all(), settings)
```

`report.py` bleibt damit vollständig unangetastet — es ist heute settings-frei
und bleibt es. Kein neuer Parameter durch `generate_report`/`generate_pdf`/
`total_hours` und die beiden Worker-Module (`send_task`, `export_task`), die den
Wert sonst nur durchreichen würden.

### 3. Standardzeiten

`tab_work` iteriert `WEEKDAY_KEYS` und baut je Tag eine Zeile. Bei aktivem
`workweek_only` werden die Zeilen für `sat`/`sun` **nicht gerendert** — die
`StringVar`s entstehen aber weiterhin, damit der Speicherpfad in
`dialog.py::save_settings` (der über dieselbe `WEEKDAY_KEYS`-Liste läuft)
unverändert alle sieben Tage schreibt.

Das ist der Kern der Zusage „die Daten bleiben": die Werte für Sa/So werden nicht
angefasst und sind sofort wieder da, wenn die Einstellung zurückgenommen wird.

### 4. Hinweiszeile

Im geteilten `period_picker` (Sende- **und** Export-Dialog nutzen ihn) unter der
Stunden-Vorschau eine gedämpfte Zeile, sobald `workweek_only` aktiv ist **und**
im gewählten Zeitraum Wochenend-Einträge liegen:

```
Gesamtstunden: 41.5h
3 Wochenend-Einträge werden nicht mitgesendet.
```

Gezählt wird auf dem **ungefilterten** Snapshot, im selben `_update_total`-Lauf,
der schon bei jeder Datums-/Kategorieänderung feuert. Ohne Treffer bleibt die
Zeile leer (kein Platzhalter-Text).

## Neues Modul `src/workweek.py`

Pur und Tk-frei, wie `weekly_limit.py`/`pause_requirement.py`:

- `is_weekend(date_str) -> bool` — ISO-Datum, Sa/So.
- `filter_for_report(entries, settings) -> dict` — bei inaktiver Einstellung das
  Eingabe-Dict unverändert (identisch, keine Kopie), sonst ein neues Dict ohne
  Sa/So.
- `count_weekend_entries(entries, date_from, date_to) -> int` — Anzahl der
  Wochenend-Tage mit Eintrag im Zeitraum, für die Hinweiszeile.

Ungültige Datumsschlüssel (die es im Storage nicht geben sollte) gelten als
*nicht* Wochenende und bleiben drin — Filtern darf niemals Daten verschlucken,
die es nicht sicher zuordnen kann.

## Bewusst nicht enthalten

- **Kein Löschen** und kein Migrieren vorhandener Wochenend-Einträge.
- **Werkstudenten-Limit, Teilen, Kalender-Abgleich** bleiben, wie sie sind (s.
  Entscheidungen).
- **Kein Feiertags-Bezug** — Feiertage sind ein eigenes Konzept und unberührt.
- **Keine Kalender-Interaktion für Wochenendtage**: sie werden nicht gerendert,
  also auch nicht anklickbar. Ein eigener Weg, sie doch zu erreichen, entsteht
  nicht.

## Tests

**`tests/test_workweek.py`** (neu, pur):
- `is_weekend` für Sa/So/Wochentag, ungültiger Schlüssel → `False`
- `filter_for_report` inaktiv → unverändert; aktiv → Sa/So raus, Wochentage
  unangetastet; leeres Dict; Dict ohne Wochenendtage
- `count_weekend_entries` mit/ohne Treffer, Zeitraumgrenzen inklusive

**`tests/test_grid_geometry.py`** (vorhanden): `workweek_only` erzwingt 5 Spalten,
auch wenn `show_weekend=True`.

**`tests/test_settings.py`** (vorhanden): `workweek_only` ist in
`SYNCED_SETTING_KEYS` und hat den Default `False`.

Die Tk-Verdrahtung (Checkbox, ausgeblendete Zeilen, Hinweiszeile) bleibt
ungetestet — konsistent mit der übrigen UI-Schicht (Audit M16 offen).

## Plattform

Kein plattformspezifischer Code. Kein Pre-Release nötig.
