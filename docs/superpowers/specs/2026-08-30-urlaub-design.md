# Urlaub — Design

Datum: 2026-08-30
Issue: Xveyn/Zeiterfassung#88

## Ziel

Der Nutzer kann einen Zeitraum A–B als Urlaub eintragen. Der Urlaub ist im
Kalender ohne Hover erkennbar, lässt sich per Rechtsklick löschen und kann im
Bericht ausgewiesen werden. Jedem Urlaubstag können Stunden zugeordnet werden —
für alle, die nicht festangestellt sind, sondern pro Stunde abrechnen.

Ohne eingetragenen Urlaub verhält sich die App **exakt** wie heute: gleicher
Kalender, bitgleicher Bericht, unveränderter Footer.

## Entschiedene Eckpunkte

Aus dem Brainstorming, als Kurzreferenz für alles Folgende:

| Frage | Entscheidung |
|---|---|
| Visueller Kanal | eigener Zelltyp mit Hintergrundfarbe |
| Rangfolge | **Urlaub gewinnt** — auch über Feiertag und Wochenende |
| Feiertag trotzdem sichtbar | ja, im kombinierten Tooltip |
| Expansion | jeder Kalendertag von A bis B, Wochenende/Feiertag mit 0 Minuten |
| Stunden | pro Tag gespeichert; ein Sammelfeld füllt alle, Einzeltage überschreibbar |
| Gesamtstunden-Eingabe | optional, wird beim Anlegen einmalig auf die Tage verteilt |
| Rundung | Minuten mit Restverteilung — Tagesanteile summieren exakt |
| „Gesamt" im Bericht | bleibt reine Ist-Zeit; „Zu vergüten gesamt" kommt als **neue** Zeile dazu |
| Einstieg | Button „Urlaub verwalten" neben „Kategorien verwalten" |
| Überschneidung | zwei Urlaube dürfen sich nicht überlappen |
| Name der Periode | nur lokal sichtbar (Kalender-Tooltip, Verwaltungs-Dialog) — im Bericht steht „Urlaub" |
| Sync | gerätelokal, **kein** Drive-Sync, **kein** Share-Doc |
| Google Kalender | ja, Einwegs-Push, nur bei aktiviertem `gcal_enabled` |
| Kalender-Footer | unverändert |

## Status quo

Sieben Befunde aus der Bestandsaufnahme, die das Design bestimmen:

1. **`reservations.py` ist als Store-Vorlage tragfähig, aber nicht als
   Konzept-Vorlage.** Das Muster `{ISO: Record}` + `modified_at` + Tombstone +
   `_user_shape` + Persistenz über `json_store` (N1/N4) lässt sich übernehmen.
   Reservierungen sind aber tagesbezogen und an `gcal_enabled` gekoppelt
   (`ui.App._reservations_active`, `ui.py:246`) — beides trifft auf Urlaub
   nicht zu.

2. **Der Kalender hat genau einen freien visuellen Kanal: den Zellhintergrund
   in Kombination mit dem Zelltyp-Dispatch.** `grid_renderer._build_day_cell`
   (`grid_renderer.py:403`) dispatcht `entry → holiday → empty`; darüber liegen
   Reservierungspunkt (Ecke oben rechts), macOS-✕ (Ecke oben links) und die
   Rahmenfarben (heute blau, Konflikt orange — Konflikt gewinnt).

3. **Es gibt genau EINEN Tooltip pro Zelle.** `_build_tooltip_text`
   (`grid_renderer.py:291`) ist eine statische, Tk-freie Funktion und faltet
   Arbeitszeit, Reservierung, Feiertag und Konflikt-Hinweis in einen Text —
   ein zweiter `attach_tooltip` am selben Widget war Audit-Finding M11. Der
   Feiertagsname kommt heute nur in den Tooltip, wenn ohnehin ein Eintrag oder
   eine Reservierung vorliegt; sonst zeigt ihn die Holiday-Zelle als Zelltext.

4. **Geld gibt es in dieser App an genau einer Stelle.** `hourly_rate` wird
   ausschließlich im Kalender-Footer verrechnet (`grid_renderer.py:507`).
   Bericht, PDF und Webhook-Payload tragen **keine** Beträge, sondern Stunden —
   die Zahl, auf der eine Abrechnung faktisch beruht, ist das „Gesamt" der
   Stundentabelle.

5. **`filter_period` / `filter_categories` sind bewusst öffentlich**
   (`report.py:111`), damit Mail-HTML, PDF und `webhook.build_json_payload`
   (`webhook.py:231`) exakt denselben Ausschnitt behaupten. `filter_period`
   arbeitet auf flachen ISO-Keys.

6. **`gcal.py` trennt seine Events serverseitig über einen Marker.**
   `APP_MARKER_KEY = "zeiterfassung"`, `APP_MARKER_VALUE = "reservation"`
   (`gcal.py:16`); `list_app_events` filtert per
   `privateExtendedProperty` genau darauf. Zusätzlich gibt `parse_event`
   für Ganztags-Events (`date` statt `dateTime`) `None` zurück — ein
   Urlaubs-Ganztagsevent unter demselben Marker-Wert wäre stillschweigend
   rausgefallen.

7. **Die Werte-Konventionen sind festgeschrieben.** Summen laufen über Minuten
   (`hours_to_minutes`, nie über Dezimalstunden — siehe `_display_minutes`);
   gespeichert und verglichen wird ISO, angezeigt deutsch
   (`format_iso_date`). `weekly_limit` zählt bewusst nur Ist-Zeiten,
   `pause_requirement` nur die `pause`-Felder vorhandener Slots.

## Architektur

```
Settings → Tab „Arbeitszeit" → [Urlaub verwalten]
                                     │
                                     ▼
                         vacation_dialog.py  (Liste + Anlegen/Bearbeiten)
                                     │  schreibt Perioden
                                     ▼
                              vacations.py
                    ┌────────────────┴────────────────┐
                    │  VacationStore  (vacations.json)│
                    │  + pure Regeln (Tk-frei)        │
                    └────────────────┬────────────────┘
                                     │  day_minutes() → {ISO: minutes}
             ┌───────────────┬───────┴───────┬──────────────────┐
             ▼               ▼               ▼                  ▼
      grid_renderer      ui._delete_day   report.py      vacations_sync.py
      (Zelltyp+Tooltip)  (Rechtsklick)    (+ webhook)    (gcal, Einweg-Push)
```

Die Trennung ist bewusst: `vacations.py` ist Tk-frei und Google-frei,
`vacations_sync.py` kapselt die einzige Google-Abhängigkeit,
`vacation_dialog.py` ist reines Tk-Wiring über getesteten reinen Funktionen.

---

## 1. Datenmodell — `src/vacations.py` (neu)

Die **Periode** ist der Record mit Identität. Sie trägt einen Namen, ein
Kalender-Event und wird als Einheit gelöscht — drei Dinge, die auf 14 lose
Tage nicht abbildbar wären. Die Tagesminuten liegen in ihr:

```json
{
  "a1b2c3d4": {
    "name": "Weihnachtsurlaub",
    "from": "2026-12-28",
    "to": "2027-01-04",
    "days": {
      "2026-12-28": 480, "2026-12-29": 480, "2026-12-30": 480,
      "2026-12-31": 240, "2027-01-01": 0,   "2027-01-02": 0,
      "2027-01-03": 0,   "2027-01-04": 480
    },
    "gcal_event_id": null,
    "modified_at": "2026-08-30T10:12:00Z",
    "deleted": false
  }
}
```

**Invarianten** (in `apply_reconciled`/`save` geprüft, analog
`_REQUIRED_RESERVATION_KEYS`):

- `days` deckt **jeden** Kalendertag von `from` bis `to` ab, lückenlos —
  daraus folgt „Urlaub gewinnt" ohne weitere Rangfolge-Regel.
- Werte sind **Minuten** (int ≥ 0), nie Dezimalstunden.
- Die Perioden-ID ist ein zufälliger Hex-String (`secrets.token_hex(4)`),
  nicht die Von-Bis-Kombination — sonst änderte sich beim Verschieben des
  Zeitraums die Identität und der gcal-Bezug risse ab.
- Perioden überschneiden sich nicht (siehe `periods_overlap`).
- Eine gelöschte Periode bleibt als Tombstone (`deleted: true`, `days: {}`)
  erhalten, bis der gcal-Reconcile ihr Event entfernt hat — exakt die
  Begründung aus `reservations.py`.

**Warum abweichend vom Issue:** #88 empfiehlt „auf Tage expandiert speichern"
(`{ISO: Record}`). Das trug, solange der Urlaub keine Identität hatte. Mit
Name, gcal-Event und Löschen-als-Einheit hätte jeder Tag diese Felder
redundant tragen müssen. Der Tages-Zugriff, den das Issue dafür wollte,
entsteht stattdessen als **abgeleitete Sicht** (`day_minutes()`), sodass
`filter_period` unverändert bleibt — der Nutzen der Empfehlung ist erhalten,
ihre Kosten nicht.

### Persistenz

`vacations.json` neben den übrigen Stores, geschrieben über
`json_store.atomic_write_json`, geladen über `load_json_or_quarantine` — die
beiden Regeln N1/N4 werden nicht nachgebaut. Kein `device_id`-Feld (wie
`reservations.py`: der Store reist nicht per Drive-Sync). Kein
Legacy-Migrationspfad — der Store ist neu.

Instanziiert in `main.py` am geteilten `data_lock`, in der Reihe der übrigen
Stores (`main.py:212`).

### Öffentliche Oberfläche

```python
class VacationStore:
    def __init__(self, filepath="vacations.json", lock=None) -> None
    def get_all(self) -> dict[str, Vacation]          # ohne Tombstones, für UI
    def get_all_raw(self) -> dict[str, Vacation]      # inkl. Tombstones, für Reconcile
    def get(self, period_id: str) -> Vacation | None
    def save(self, period_id: str | None, name: str, date_from: str,
             date_to: str, days: dict[str, int]) -> str   # liefert period_id
    def delete(self, period_id: str) -> None          # Tombstone
    def apply_reconciled(self, reconciled: dict[str, Vacation]) -> None
    def day_minutes(self) -> dict[str, int]           # {ISO: minutes}, ohne Tombstones
    def period_for_date(self, date_str: str) -> Vacation | None
```

`day_minutes()` und `period_for_date()` sind die beiden Sichten, die der
Kalender und der Bericht brauchen. Beide bauen ihren Index bei jedem Aufruf
neu — bei realistischen Datenmengen (einige Dutzend Perioden) ist das
billiger als ein zu pflegender Cache, und der Store bleibt zustandsfrei
gegenüber der UI.

### Reine Regeln (Tk-frei, Google-frei, im selben Modul)

```python
def expand_days(date_from: str, date_to: str, minutes_per_day: int,
                state: str) -> dict[str, int]
```
Baut `{ISO: minutes}` über alle Kalendertage. Wochenenden (Sa/So) und
Feiertage (`holidays_de.get_holidays`, Bundesland aus `settings["state"]`)
bekommen 0 — sie sind ohnehin frei. Alle übrigen Tage bekommen
`minutes_per_day`.

```python
def apportion_minutes(total: int, n: int) -> list[int]
```
Verteilt `total` Minuten auf `n` Tage so, dass die Summe **exakt** `total`
ergibt: `total // n` für alle, die ersten `total % n` bekommen eine Minute
mehr. `n == 0` → leere Liste. Damit summiert sich jeder Teilbericht exakt zum
Ganzen; die Alternative (Dezimalstunden je Tag runden) ergäbe bei 40 h auf 6
Tage 40,02 h — genau der Fehler, den CLAUDE.md für den Footer beschreibt.

```python
def periods_overlap(periods: dict[str, Vacation], period_id: str | None,
                    date_from: str, date_to: str) -> str | None
```
Datums-Pendant zu `time_utils.slots_overlap`. Liefert den Namen der
kollidierenden Periode oder `None`. `period_id` ist die gerade bearbeitete
Periode, die sich nicht mit sich selbst überschneiden darf. Tombstones zählen
nicht.

```python
def total_minutes(day_minutes: dict[str, int]) -> int
```
Summe über Minuten — die einzige erlaubte Summenbildung (CLAUDE.md).

---

## 2. Kalender — `grid_renderer.py`, `theme/palette.py`

### Neue Farben (`palette.py`)

```python
# Urlaubszelle — türkis, abgesetzt von rotem Eintrag, grünem Feiertag,
# violetter Reservierung, blauem Heute-Rahmen und orangem Konflikt-Rand.
VACATION_BG = "#134e4a"
VACATION_BG_HOVER = "#176b64"
VACATION_ACCENT = "#2dd4bf"
```

Re-Export über `theme/__init__.py` wie die übrigen Konstanten.

### Dispatch — „Urlaub färbt, der Rest entscheidet den Inhalt"

`_build_day_cell` bekommt einen Parameter `vacation` (die Periode oder
`None`) und `vacation_minutes` (int). Die Regel:

```
Urlaub, keine Ist-Zeit    Halber Urlaubstag         Urlaub am Feiertag
┌───────────┐             ┌───────────┐             ┌───────────┐
│▓▓▓▓▓▓▓▓▓▓▓│             │▓▓▓▓▓▓▓▓▓▓▓│             │▓▓▓▓▓▓▓▓▓▓▓│
│▓▓▓ 29 ▓▓▓▓│             │▓▓▓ 31 ▓▓▓▓│             │▓▓▓ 01 ▓▓▓▓│
│▓ Urlaub ▓▓│             │▓08:00-12:00             │▓ Urlaub ▓▓│
│▓ 8:00 h ▓▓│             │▓ 4:00 h·P0│             │▓▓▓▓▓▓▓▓▓▓▓│
└───────────┘             └───────────┘             └───────────┘
```

- **Urlaub ohne Ist-Zeit** → neuer `_build_vacation_cell`: Tagnummer,
  „Urlaub", und die Stundenzeile nur, wenn der Tag Minuten trägt (0-Minuten-
  Tage — Wochenende, Feiertag — zeigen nur „Urlaub").
- **Urlaub mit Ist-Zeit** → die Eintragszelle wird wie heute gebaut, aber mit
  `VACATION_BG`/`VACATION_BG_HOVER` statt `ENTRY_BG`. Zeit- und Stundenzeile
  bleiben sichtbar. Der halbe Urlaubstag ist damit ohne Sonderfall im
  Dispatch abgedeckt: `_build_entry_cell` bekommt die Hintergrundfarben als
  Parameter, statt sie selbst aus `is_weekend` abzuleiten.
- **Urlaub am Feiertag / am Wochenende** → Urlaubszelle. Der Feiertagsname
  wandert in den Tooltip (siehe unten), die Wochenend-Einfärbung entfällt.

Alle Overlays bleiben unangetastet: Reservierungspunkt oben rechts,
macOS-✕ oben links, Heute-/Konflikt-Rahmen mit unveränderter Rangfolge.

### Tooltip

`_build_tooltip_text` bekommt zwei zusätzliche Parameter und bleibt statisch
und Tk-frei:

```python
def _build_tooltip_text(entry, reservation, holiday_name, has_conflict=False,
                        vacation=None, vacation_minutes=0)
```

Block-Reihenfolge: Arbeitszeit → Reservierung → **Urlaub** → Feiertag →
Konflikt. Der Urlaubs-Block nennt den **lokalen Namen** und den Zeitraum:

```
Urlaub: Weihnachtsurlaub
28.12.2026 – 04.01.2027  ·  8:00 h
Feiertag: Neujahr
```

Die Feiertags-Bedingung wird von
`if holiday_name and (reservation is not None or entry)` auf
`if holiday_name and (reservation is not None or entry or vacation is not None)`
erweitert — denn bei Urlaub baut der Dispatch keine Holiday-Zelle mehr, die
den Namen selbst zeigen könnte. Datumsanzeige über `format_iso_date`
(CLAUDE.md: UI immer deutsch).

Weiterhin **genau ein** `attach_tooltip` pro Zelle.

### Renderer-Verdrahtung

`GridRenderer.__init__` bekommt `vacation_store` als weiteren Parameter
(nach `reservation_store`). `_refresh_month`/`_refresh_week` holen einmal pro
Refresh `vacation_store.day_minutes()` und `get_all()` und reichen die
Treffer je Tag durch — kein Store-Zugriff pro Zelle.

**Der Footer bleibt unverändert.** `_update_footer` und `_display_minutes`
zählen weiterhin ausschließlich Ist-Zeit; die fixierten Breiten
(`width=42`/`20`, `repin_geometry`) werden nicht angefasst.

---

## 3. Verwaltung — `src/dialogs/vacation_dialog.py` (neu)

### Einstieg

Ein `secondary_button` **„Urlaub verwalten"** direkt unter „Kategorien
verwalten" im Tab „Arbeitszeit" (`tab_work.py:118`, neue Grid-Zeile 8).
`WorkTab.__init__` bekommt dafür `vacation_store` und `on_vacation_change`;
`open_settings_dialog` reicht beide durch (neue Keyword-Argumente, Default
`None` — fehlen sie, wird der Button nicht gebaut), `ui.App._open_settings`
übergibt `self.vacation_store` und einen Callback, der `self._refresh()` und
den gcal-Abgleich anstößt.

### Übersicht

Aufbau nach `category_dialog.py`: `create_dialog`, Liste der Perioden
(chronologisch, Name + Zeitraum + Gesamtstunden), Buttons *Neu*,
*Bearbeiten*, *Löschen*. Löschen fragt per `themed_askyesno` nach.

### Anlege-/Bearbeiten-Dialog

```
┌─ Urlaub eintragen ────────────────────────┐
│ Name:  [Weihnachtsurlaub_______________]  │
│ Von: [28][12][2026]   Bis: [04][01][2027] │
│                                           │
│ ( • ) Stunden pro Tag   [ 8,0 ]           │
│ (   ) Gesamtstunden     [     ]           │
│                                           │
│ ▾ Einzelne Tage anpassen                  │
│    Mo 28.12.  [ 8,0 ]                     │
│    Di 29.12.  [ 8,0 ]                     │
│    Mi 30.12.  [ 8,0 ]                     │
│    Do 31.12.  [ 4,0 ]  ← halber Tag       │
│    Fr 01.01.  [ 0,0 ]  Neujahr            │
│    Sa 02.01.  [ 0,0 ]                     │
│    So 03.01.  [ 0,0 ]                     │
│    Mo 04.01.  [ 8,0 ]                     │
│                                           │
│ Urlaub gesamt: 36,00 h                    │
│                     [Abbrechen] [Speichern]│
└───────────────────────────────────────────┘
```

- **Von/Bis** über `dialogs/date_row.py::build_date_row` (Audit M14), wie im
  Werkstudenten-Block.
- **Radiobutton-Paar**: „Stunden pro Tag" füllt alle Arbeitstage über
  `expand_days`; „Gesamtstunden" verteilt über `apportion_minutes` auf die
  Arbeitstage der Periode (Wochenende/Feiertag bleiben 0). Beide schreiben in
  **dieselbe** Tagesliste — der Store sieht nie eine Gesamtzahl.
- **Tagesliste** ist eingeklappt (die aufgeklappte Variante scrollt), zeigt
  jeden Tag mit deutschem Datum, Wochentag und ggf. Feiertagsnamen. Eine
  Änderung im Sammelfeld überschreibt die Liste; eine Änderung in der Liste
  lässt das Sammelfeld unangetastet und aktualisiert nur die Summe.
- **Live-Summe** unten, über `format_minutes_hm`.
- **Speichern** prüft in dieser Reihenfolge: Von ≤ Bis → Name nicht leer →
  `periods_overlap` → Minuten ≥ 0. Jeder Fehler ist ein **bekannter,
  erwarteter** Fehler und damit ein **themed** `themed_showerror` (CLAUDE.md,
  Audit N14).

Der Dialog entsteht über `theme.create_dialog(...)`, `center_dialog_on_parent`
nach dem Widget-Aufbau — keine handgebaute Toplevel-Boilerplate.

**Keine flächendeckenden Tooltips** (CLAUDE.md: Dialoge bekommen keine); der
Radiobutton „Gesamtstunden" bekommt einen, weil ohne ihn unklar bleibt, dass
der Wert auf die Arbeitstage verteilt wird.

### Neue Einstellung

`vacation_hours_per_day` (float, Default `8.0`) in `settings.DEFAULTS` als
Vorbelegung des Sammelfelds. **Nicht** in `SYNCED_SETTING_KEYS` — genau wie
`default_pause` und die Wochenplan-Zeiten, die dort ebenfalls nicht stehen;
den Store synchronisiert diese Ausbaustufe ohnehin nicht.

---

## 4. Löschen — `ui.py::_delete_day`, `theme/geometry.py`

Der Rechtsklick-Pfad bleibt das einzige Lösch-Modell im Kalender. `_delete_day`
holt zusätzlich `vacation_store.period_for_date(date_str)` und reiht die
Periode als weitere Option ein:

```python
if vacation is not None:
    options.append((
        f"vacation:{vacation_id}",
        f"Urlaub „{vacation['name']}\" ({von}–{bis})",
    ))
```

Gelöscht wird **immer die ganze Periode**. Einzelne Tage aus der Mitte
herauszubrechen würde den Zeitraum zerreißen und die `days`-Invariante
(lückenlos von `from` bis `to`) verletzen; wer das will, bearbeitet die
Periode im Verwaltungs-Dialog. Das ist auch die konsistente Lesart des
bestehenden Modells: die Reservierung wird ebenfalls als Einheit angeboten,
solange sie nur einen Slot hat.

Ein einzelner Urlaubstag ohne weitere Einheiten läuft damit in den
Ja/Nein-Zweig, mehrere Einheiten in den Checkbox-Dialog — beides unverändert
inklusive `lock_ms=600`.

`_should_show_delete_button(is_macos, has_entry, has_reservation)` bekommt ein
drittes Merkmal `has_vacation`; `_build_day_cell` übergibt
`vacation is not None`. Danach ist der macOS-✕ auf jedem löschbaren Tag
verfügbar.

Nach dem Löschen: `self._refresh()` und — falls die Periode ein
`gcal_event_id` trug — der Kalender-Abgleich, analog `res_touched`.

---

## 5. Bericht und Versand

### Häkchen

`period_picker.build_period_picker` bekommt eine zweite Checkbox **„Urlaub
ausweisen"** unter „Nach Kategorie aufschlüsseln" (neue Grid-Zeile), plus
`_PeriodPickerHandle.get_show_vacation()`. Der Picker bekommt dafür den
`vacation_store` als optionalen Parameter; ohne ihn (oder ohne jede Periode)
wird die Checkbox **nicht gebaut** — ein Schalter für ein Feature, das der
Nutzer nicht benutzt, ist Rauschen.

Die Live-Vorschau nennt den Urlaub getrennt, sobald er im Zeitraum liegt:
`Gesamtstunden: 15h  (+ 28h Urlaub)`.

### Weg durch die Schichten

Der Flag folgt exakt dem Pfad von `category_breakdown`:

```
send_dialog.py:232   ─┐
export_dialog.py:53  ─┴→ picker.get_show_vacation()
                          │
                          ├→ send_task.perform_send(..., show_vacation, vacation_days)
                          │     ├→ report.generate_report(...)
                          │     ├→ report.generate_pdf(...)
                          │     └→ webhook.build_json_payload(...)
                          └→ export_task.export_pdf(..., show_vacation, vacation_days)
                                └→ report.generate_pdf(...)
```

`send_task` und `export_task` sind Tk-freie Worker — sie bekommen
`vacation_days: dict[str, int]` als **fertigen Snapshot** (im Dialog-Thread
über `vacation_store.day_minutes()` gezogen), nicht den Store. Damit bleibt
das Threading-Modell unverändert: kein Store-Zugriff im Worker.

### Ausgabe

`report.py` bekommt `_build_vacation_summary(vacation_days, date_from,
date_to, style)` — denselben Zuschnitt wie `_build_category_summary`, damit
Mail-HTML und PDF sich denselben Baustein teilen und nicht auseinanderlaufen
können. Gefiltert wird mit `filter_period` über die flachen ISO-Keys:

```
  Gesamt (Arbeitszeit)         15,00 h    ← unverändert

  Urlaub
  28.12. – 31.12.2026          28,00 h    ← nur die Tage IM Zeitraum
  ─────────────────────────────────────
  Zu vergüten gesamt           43,00 h    ← neu
```

(Beispiel-Periode aus Abschnitt 1: 28.12.–04.01., der 31.12. ein halber Tag.
Ein Dezember-Bericht sieht davon 480+480+480+240 = 1680 min = 28,00 h; der
Januar-Bericht die restlichen 480 min = 8,00 h.)

Drei Festlegungen dazu:

- **„Gesamt" ändert nie seine Bedeutung.** Es bleibt geleistete Ist-Zeit.
  Die abrechnungsrelevante Zahl kommt als **zusätzliche** Zeile dazu, statt
  eine bestehende je nach Häkchen umzudeuten. Für den Stundenlohn-Fall ist
  das die Zahl, um die es geht (Befund 4); für alle anderen ändert sich
  nichts.
- **Kein Periodenname im Bericht.** Der Name ist lokal — im Bericht steht
  „Urlaub" und der Zeitraum. Angezeigt werden nur die Tage im
  Berichtszeitraum: eine Periode, die über die Grenze ragt, erscheint mit
  ihrem anteiligen Zeitraum und dessen Minuten.
- **Ohne Urlaub im Zeitraum ist die Ausgabe bitgleich zu heute** — keine
  Zeile, keine Trennlinie, kein geänderter Wert. Das gilt auch bei gesetztem
  Häkchen.

`generate_report` / `generate_pdf` bekommen dafür
`vacation_days: dict[str, int] | None = None`. Der Rückgabewert von
`generate_report` bleibt `(html, total)` mit `total` = Ist-Zeit — Aufrufer,
die ihn für Platzhalter (`{gesamt}`) nutzen, ändern sich nicht.

### Webhook

`build_json_payload` bekommt `vacation_days` und ergänzt die Payload um
zwei Felder, gefiltert über denselben `filter_period`-Aufruf:

```json
"vacation": {"2026-12-28": 480, "2026-12-29": 480,
             "2026-12-30": 480, "2026-12-31": 240},
"vacation_minutes": 1680
```

Minuten statt Stunden, konsistent zum vorhandenen `total_minutes`.
`PAYLOAD_SCHEMA_VERSION` steigt um eins; die Felder erscheinen nur bei
gesetztem Häkchen (sonst `null`/`0`), damit ein bestehender Empfänger
unverändert weiterläuft.

### Was sich ausdrücklich NICHT ändert

- **`weekly_limit`** liest ausschließlich `storage`-Einträge. Urlaub liegt in
  einem eigenen Store — das Werkstudenten-Limit sieht ihn per Konstruktion
  nicht. Kein Code-Change, kein Test-Change.
- **`pause_requirement`** prüft die `pause`-Felder vorhandener Slots. Ein
  Urlaubstag hat keine Slots. Ebenfalls unberührt.
- **`workweek.filter_for_report`** filtert Wochenend-Einträge. Urlaubstage am
  Wochenende tragen 0 Minuten und fallen damit ohnehin nicht ins Gewicht.
- **Kalender-Footer**, `share.py`, `sync.py`.

---

## 6. Google Kalender — `src/vacations_sync.py` (neu)

### Marker

`gcal.py` bekommt einen zweiten Marker-Wert:

```python
APP_MARKER_VALUE_VACATION = "vacation"
VACATION_SUMMARY = "Urlaub"
VACATION_DESCRIPTION = "Von der Zeiterfassung verwalteter Urlaub."
```

Das ist die **sicherheitsrelevante** Stelle des Entwurfs (Befund 6): der
serverseitige Filter von `list_app_events` lautet
`zeiterfassung=reservation`. Urlaubs-Events unter `zeiterfassung=vacation`
werden davon gar nicht erst zurückgeliefert — der Reservierungs-Reconcile
kann sie weder adoptieren noch als verwaiste App-Events löschen. Mit
demselben Marker-Wert wäre das Verhalten dagegen von `parse_event`s
Ganztags-`None` abhängig gewesen, also von einem Detail, das jederzeit hätte
kippen können.

### Event-Form

Ein **Ganztags-Event pro Periode**: `start.date = from`,
`end.date = to + 1 Tag` (die Calendar-API behandelt `end.date` exklusiv).
Titel „Urlaub", der lokale Name geht **nicht** mit — er ist lokal.
`extendedProperties.private` trägt Marker, `period_id` und `modified_at`.

Neue Funktionen in `gcal.py` (die reinen Helfer bleiben Google-frei, die I/O-
Funktionen behalten ihre lazy Imports):
`vacation_event_payload`, `list_app_vacations`, `create_vacation_event`,
`update_vacation_event` — Löschen deckt das vorhandene `delete_event` ab.

### Abgleich

`reconcile_vacations(service, calendar_id, store, settings, data_lock=None)`
— **Einwegs-Push**, die App ist die Quelle:

1. App-Urlaubsevents listen.
2. Events ohne lebende lokale Periode löschen (inkl. der Events zu
   Tombstones — danach darf der Tombstone weg).
3. Perioden ohne Event anlegen, `gcal_event_id` zurückschreiben.
4. Perioden, deren `modified_at` neuer ist als das Event, aktualisieren.

Der Merge-Teil (`plan_vacation_sync(local_raw, remote_events)` → `{create,
update, delete}`) ist **Tk- und Google-frei** und wird direkt getestet — wie
`merge_reservations`. Rebase + `apply_reconciled` laufen unter dem
`data_lock`, die Netzwerk-Calls davor bewusst ungelockt (Audit H1/H2, Muster
aus `reconcile_reservations`).

**Bewusst kein Import aus dem Kalender.** Nur App-Events tragen den Marker,
ein manuell angelegter Urlaubstermin würde also ohnehin nie erkannt. Der
einzige Verlust ist: wer das Event in Google verschiebt, bekommt es beim
nächsten Abgleich zurückgesetzt. Das ist als möglicher späterer Schritt im
Issue zu vermerken, nicht in dieser Stufe zu bauen.

### Gate

Der Push läuft nur bei `gcal_enabled` **und** gewähltem Kalender — dasselbe
Gate wie der Reservierungs-Abgleich, angestoßen über denselben
`BackgroundTaskRunner`-Pfad (`_bg.trigger_reconcile`).

**Der Urlaub selbst ist nicht an dieses Gate gekoppelt.** Anders als
Reservierungen (`ui.App._reservations_active`, `ui.py:246`) werden
Urlaubsperioden ohne jede Google-Anbindung angelegt, gerendert, gelöscht und
berichtet. Google ist ein Zusatz, keine Voraussetzung — Akzeptanzkriterium 2
des Issues.

---

## Fehlerbehandlung

Nach der Zweiteilung aus CLAUDE.md (Audit N14):

- **Bekannt/erwartet → themed:** Von > Bis, leerer Name, überschneidender
  Zeitraum, ungültige Stundenzahl, „keine Urlaubsperiode ausgewählt". Alle
  über `themed_showerror`/`themed_showinfo`.
- **Unerwartet → nativ:** die generischen `except`-Zweige im Speicherpfad und
  im gcal-Abgleich zeigen `traceback.format_exc()` per rohem
  `tkinter.messagebox.showerror`.
- **Store-Fehler:** ein `OSError` beim Schreiben ist ein gehandhabter,
  bekannter Fehler → themed, mit dem Hinweis, dass der Urlaub nicht
  gespeichert wurde.
- Ein fehlgeschlagener gcal-Abgleich lässt den lokalen Urlaub **unangetastet**
  und wird still geloggt bzw. wie der Reservierungs-Abgleich gemeldet — der
  lokale Store ist die Quelle, Google die Kopie.

## Tests

Getestet wird Logik, nicht UI (entschiedene Scope-Grenze, M16). Der
Tk-gebundene Teil beschränkt sich bewusst auf Wiring.

**`tests/test_vacations.py`** (Store)
- Anlegen, Lesen, Überschreiben, Tombstone beim Löschen
- `get_all` blendet Tombstones aus, `get_all_raw` nicht
- `day_minutes` / `period_for_date` über mehrere Perioden
- `apply_reconciled` wirft bei fehlenden Pflichtfeldern
- Runde durch `json_store`: atomarer Write, korrupte Datei → Quarantäne

**`tests/test_vacation_rules.py`** (reine Regeln)
- `expand_days`: lückenlos von `from` bis `to`; Sa/So und Feiertage 0;
  Bundesland aus `state` wirkt; Ein-Tages-Periode
- `apportion_minutes`: Summe **exakt** gleich `total` für n = 1…31 und
  diverse Totals; `n == 0`; Rest landet vorn
- `periods_overlap`: Berührung am Rand, echte Überlappung, Umschließung,
  Selbst-Ausschluss beim Bearbeiten, Tombstones zählen nicht
- **Monatswechsel-Schnitt**: 28.12.–04.01. mit 8 h/Tag ergibt im
  Dezember-Bericht 32 h, im Januar-Bericht 8 h, zusammen exakt 40 h

**`tests/test_report.py`** (Erweiterung)
- Urlaubs-Block erscheint nur bei gesetztem Häkchen **und** Urlaub im Zeitraum
- ohne Urlaub im Zeitraum: Ausgabe **identisch** zum Stand ohne das Feature
- „Zu vergüten gesamt" = Ist-Zeit + Urlaub, gerechnet über Minuten
- Mail-HTML und PDF zeigen denselben Block (gemeinsamer Baustein)
- `filter_period` schneidet eine überstehende Periode korrekt an

**`tests/test_webhook.py`** (Erweiterung)
- `vacation` / `vacation_minutes` in der Payload, gleicher Ausschnitt wie
  Mail und PDF

**`tests/test_vacations_sync.py`**
- `plan_vacation_sync`: create/update/delete, Tombstone-Aufräumung,
  Idempotenz bei unverändertem Stand
- Ganztags-Payload: `end.date` ist exklusiv (to + 1 Tag)

**`tests/test_grid_renderer.py`** bzw. der Tooltip-Pfad
- `_build_tooltip_text` mit Urlaub, mit Urlaub + Feiertag, mit Urlaub +
  Reservierung + Ist-Zeit + Konflikt (Reihenfolge und Vollständigkeit)
- Feiertagsname erscheint auch ohne Eintrag/Reservierung, sobald Urlaub vorliegt

**`tests/test_delete_button.py`** (Erweiterung)
- `_should_show_delete_button` mit dem dritten Merkmal

**`tests/test_type_annotations.py`**
- `src/vacations.py` und `src/vacations_sync.py` in die Whitelist — beide
  sind Tk-frei und damit **vollständig** zu annotieren (Rückgabetyp *und*
  alle Parameter). `vacation_dialog.py` gehört zur UI-Schicht und bleibt
  außen vor.

**Manuell zu prüfen** (nicht automatisierbar, siehe M16): Zellfarben im
Kalender, aufklappbare Tagesliste, Rechtsklick-Auswahl mit Urlaub, und der
gcal-Push gegen einen echten Kalender.

## Doku

- **Root-`CLAUDE.md`**: `src/vacations.py`, `src/vacations_sync.py`,
  `src/dialogs/vacation_dialog.py` in die Struktur-Liste; ein Absatz zum
  Urlaubs-Konzept neben dem Klick-Modell (Rechtsklick löscht die ganze
  Periode) und die Festlegung, dass „Gesamt" im Bericht reine Ist-Zeit bleibt.
- **`src/CLAUDE.md`**: Schichten, der neue Store am `data_lock`, der
  Snapshot-Vertrag zu den Tk-freien Workern, der zweite gcal-Marker.

## Abgrenzung

Nicht in dieser Ausbaustufe — im Issue als eigene, spätere Schritte zu
vermerken:

- **Drive-Sync** (`sync.SCHEMA_VERSION` 4 → 5, LWW-Zweig,
  Tombstone-Kompaktierung, Forward-Compat-Rollout wie bei v3)
- **Share-Doc** (`share.SCHEMA_VERSION` 3 → 4, Validator-Zweig)
- **Urlaub im Kalender-Footer** (fixierte Breiten wären neu zu vermessen)
- **Import aus dem Google Kalender** (Verschieben des Events dort übernehmen)
- **Urlaubskonto / Resttage** — eigenes Thema
- Urlaub bleibt **keine Kategorie**; die Kategorie-Mechanik ist unberührt.

## Offene Punkte

Keine. Alle im Issue als offen geführten Entscheidungen (1–6) sind oben
festgelegt.
