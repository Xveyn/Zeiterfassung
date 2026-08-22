# Sende-Erinnerung an Reservierungen koppeln — Design

Datum: 2026-08-22

## Ziel

Die bestehende Erinnerung „Arbeitszeiten verschicken" kennt heute nur einen
monatlichen Termin (Tag im Monat + Uhrzeit). Sie bekommt drei Erweiterungen:

1. **Tagesbezogene Erinnerungen.** Ein Tag mit Reservierung lässt sich im
   Tages-Dialog als Erinnerungs-Tag markieren; die Erinnerung feuert N Minuten
   vor dem Ende eines gewählten Reservierungs-Slots.
2. **Wochenend-/Feiertags-Verschiebung des Monatstermins.** Fällt der Termin
   auf einen arbeitsfreien Tag, wird er vor- oder nachgezogen (konfigurierbar).
3. **Zeitraum-Vorbelegung im Sende-Dialog.** Optional startet der Sende-Dialog
   mit „Tag nach der vorherigen Erinnerung … heute" statt mit dem
   Vormonats-Pendant.

Monatlicher Termin und tagesbezogene Erinnerungen laufen **parallel**; keiner
unterdrückt den anderen.

## Status quo

- `src/send_reminder.py` — pure Fälligkeit: `scheduled_datetime(year, month,
  day, time_str)` (Tag auf Monatslänge geclamped) und `is_due(now_dt, day,
  time_str, last_fired_month)`.
- `src/send_reminder_scheduler.py` — minütlicher `root.after`-Poll, Toast über
  das Tray, `send_reminder_last_fired_month` (`"YYYY-MM"`) in den Settings
  verhindert Mehrfach-Feuern pro Monat.
- `src/reminders.py` / `src/reminder_scheduler.py` — dasselbe Muster für
  Reservierungs-Erinnerungen; Dedup dort über ein **In-Memory-Set**, das pro
  Tag zurückgesetzt wird.
- `src/dialogs/settings_dialog/tab_app.py` — Abschnitt „— Benachrichtigungen —"
  mit Checkbox + Tag/Uhrzeit-Combos.
- `src/dialogs/entry_dialog.py` — Blöcke „Arbeitszeit" und „— Reservierung —",
  ein gemeinsamer Speichern-Button, alles-oder-nichts (`plan_entry_save`).
- `src/dialogs/period_picker.py` — `_default_from_date` liefert hart das
  Vormonats-Pendant zu heute.

Zwei Befunde aus der Bestandsaufnahme, die das Design bestimmen:

- **`reservations_sync._merge_one_date` baut jeden Tages-Record neu.** In
  `_adopt_remote` (Fälle „nur remote" und „remote gewinnt") entsteht der Record
  ausschließlich aus den Kalender-Events. Ein neues Feld überlebt dort nur,
  wenn es explizit übertragen wird.
- **`share._check_keys` ist strikt** (`keys != expected_keys` → Fehler bei
  unbekannten Feldern), und `share.build_share_doc` baut die Reservierungen
  direkt aus `reservation_store.get_all()`. Ohne Gegenmaßnahme erzeugt die App
  Share-Dateien, die ihr eigener Validator ablehnt.

## Datenmodell

Die Markierung hängt am **Reservierungs-Slot**, nicht am Tages-Record:

```json
{"2026-08-31": {
  "slots": [
    {"start": "08:00", "end": "12:00", "kategorie": "Office",
     "gcal_event_id": "abc", "send_reminder_minutes": null},
    {"start": "13:00", "end": "17:00", "kategorie": "Kunde",
     "gcal_event_id": "def", "send_reminder_minutes": 15}
  ],
  "modified_at": "2026-08-22T10:00:00Z",
  "deleted": false
}}
```

Damit beantwortet die Position des Werts die Frage „welcher Slot ist der
Anker", und die Markierung überlebt jede Slot-Listen-Operation (Teil-Löschen
per Rechtsklick, Umsortieren) automatisch — dasselbe Prinzip wie
`gcal_event_id`.

**Invariante:** Höchstens ein Slot pro Tag trägt einen Wert. Der Tages-Dialog
erzwingt sie beim Speichern; Leser nehmen den ersten Slot mit gesetztem Wert.

**Wertebereich:** `int` in `[0, 120]` oder `None` (keine Erinnerung) — dieselbe
Spanne wie `reminder_minutes_before`.

### Berührte Stellen

| Datei | Änderung |
|---|---|
| `reservations._normalize_slot` | Feld ergänzen; fehlend → `None` |
| `reservations._user_shape` | Feld durchreichen (UI und Teil-Lösch-Pfad brauchen es) |
| `reservations_sync._slot_from_event` | Feld auf `None` setzen |
| `reservations_sync._adopt_remote` | vorhandene Marker positionsweise vom lokalen Record übernehmen |
| `share.build_share_doc` | Reservierungs-Slots auf `{start, end, kategorie}` projizieren |

Nicht zu ändern: die Fälle „lokal gewinnt" (`slot_copy = dict(s)`) und „lokal
ohne Remote-Events" (`[dict(s) for s in local["slots"]]`) tragen das Feld schon
heute mit; `_REQUIRED_RESERVATION_KEYS` prüft nur Pflicht-, nicht Fremdfelder.

### Kompatibilität

Alte `reservations.json`-Dateien und Share-Importe kennen das Feld nicht.
Gelesen wird durchgehend per `.get()`, ein Migrationsschritt entfällt. Ein
Share-Import überschreibt den Tag vollständig und löscht damit eine dortige
Markierung — akzeptiert und dokumentiert.

Weil das Feld nicht in Kalender-Events landet, ist die Markierung faktisch
gerätelokal: ein zweites Gerät, das den Tag über den Kalender importiert,
bekommt keine Erinnerung.

## Neue Settings

Alle gerätelokal — **nicht** in `SYNCED_SETTING_KEYS`, konsistent mit den
bestehenden Reminder-Keys.

| Key | Typ | Default | Wirkung |
|---|---|---|---|
| `send_reminder_reservations_enabled` | bool | `False` | Schaltet den Erinnerungs-Block im Tages-Dialog frei |
| `send_reminder_default_minutes` | int | `15` | Vorbelegung der Minuten für eine neu markierte Reservierung |
| `send_reminder_weekend_shift` | str | `"none"` | `"none"` / `"backward"` (vorziehen) / `"forward"` (nachziehen) |
| `send_reminder_shift_holidays` | bool | `False` | Feiertage des eingestellten Bundeslands zählen wie Wochenende |
| `send_period_from_last_reminder` | bool | `False` | Sende-Dialog startet mit „Tag nach der vorherigen Erinnerung … heute" |
| `send_period_anchor_monthly` | bool | `False` | Monatstermine zählen als Ankerpunkte, nicht nur markierte Tage |

`send_reminder_weekend_shift` ist ein String-Enum; `settings._coerce` prüft nur
den Typ. Unbekannte Werte behandelt die Verschiebungs-Logik wie `"none"`.

### Settings/App, Abschnitt „— Benachrichtigungen —"

```
[x] Erinnerung zum Verschicken der Arbeitszeiten
    Tag im Monat: [23 ▾]  um [16:30 ▾]
    Bei kürzeren Monaten wird auf den letzten Tag verschoben.
    Fällt der Tag aufs Wochenende: [nicht verschieben ▾]  [ ] Feiertage mitzählen
    [x] Reservierungen        Standard: [15 ▾] Minuten vor Ende
    [ ] Zeitraum ab der letzten Erinnerung vorbelegen
        [ ] Monatstermine als Anker mitzählen
```

Die Combo „Fällt der Tag aufs Wochenende" zeigt die Klartexte „nicht
verschieben" / „vorziehen (davor)" / „nachziehen (danach)" und mappt auf die
drei Enum-Werte.

## Monatstermin: Verschiebung auf arbeitsfreie Tage

Neu in `src/send_reminder.py`, pure und stdlib-only:

```python
def shift_off_free_days(date, mode, free_dates):
    """Verschiebt `date` weg von arbeitsfreien Tagen.

    mode "backward": rückwärts zum ersten nicht-freien Tag.
    mode "forward":  vorwärts zum ersten nicht-freien Tag; verlässt das den
                     Monat, wird stattdessen rückwärts gesucht.
    mode "none"/unbekannt: unverändert.
    """
```

- `free_dates` ist ein `set[datetime.date]`. `holidays_de` bleibt aus dem
  Modul draußen — der Scheduler baut die Menge (Wochenende immer, Feiertage nur
  bei gesetzter Option, Bundesland aus `state`).
- Die Verschiebung läuft **nach** dem bestehenden Monatslängen-Clamp in
  `scheduled_datetime`, das dafür `shift_mode` und `free_dates` als optionale
  Parameter bekommt (Defaults = heutiges Verhalten).
- Weil `"forward"` an der Monatsgrenze auf Rückwärtssuche umschlägt, bleibt der
  Termin immer im Zielmonat. Die „1×/Monat"-Buchhaltung über
  `send_reminder_last_fired_month` bleibt damit unverändert gültig.
- Findet die Suche in keiner Richtung einen freien Tag (theoretisch: ganzer
  Monat arbeitsfrei), bleibt das geclampte Datum stehen.

Beispiele bei Tag 31, `shift_holidays = False`:

| Monat | geclampt | `backward` | `forward` |
|---|---|---|---|
| Okt 2026 | Sa 31.10. | Fr 30.10. | Fr 30.10. (Monatsgrenze) |
| Mai 2026 | So 31.05. | Fr 29.05. | Fr 29.05. (Monatsgrenze) |
| Aug 2026 | Mo 31.08. | Mo 31.08. | Mo 31.08. |

## Tagesbezogene Erinnerung

### Pure Logik

Neu in `src/send_reminder.py`:

```python
def due_day_reminder(reserved_slots, now_dt):
    """Der fällige tagesbezogene Sende-Reminder für die heutigen
    Reservierungs-Slots, oder None.

    Sucht den ersten Slot mit gesetztem send_reminder_minutes und liefert ihn
    ab now_dt >= end - minutes. Kein oberes Fenster: startet die App erst nach
    dem Zeitpunkt, wird der Toast am selben Tag nachgeholt.
    """
```

Ungültige Slots (kein parsebares `end`, Minuten außerhalb `[0, 120]`) werden
übersprungen — dieselbe Toleranz wie in `reminders.due_reminders`.

### Scheduler

`SendReminderScheduler` bekommt zusätzlich den `reservation_store` und pollt in
demselben Minuten-Tick beide Kanäle:

1. **monatlich** — wie bisher, jetzt mit Verschiebung; Dedup weiter über
   `send_reminder_last_fired_month`.
2. **tagesbezogen** — heutige Reservierung lesen, `due_day_reminder` fragen,
   Toast senden.

Dedup tagesbezogen über ein **In-Memory-Set von Datums-Keys**, das pro Tag
zurückgesetzt wird (Muster von `ReminderScheduler`). Bewusst nicht persistiert:
ein Marker in `reservations.json` würde `modified_at` anfassen und damit einen
gcal-Push auslösen. Folge: ein Neustart am selben Tag nach dem Zeitpunkt kann
den Toast erneut zeigen — dasselbe Verhalten wie beim Reservierungs-Reminder.

Toast-Text: `"Reservierung endet um 17:00 — Zeit, deine Arbeitszeiten zu
verschicken."`

Der Toast bleibt **reiner Text ohne Button**, analog zum bestehenden
Reservierungs-Reminder. Der ungemergte Branch `feat/toast-button-arbeitszeit`
(`tray.notify_action`) könnte später einen „Jetzt senden"-Button nachrüsten —
nicht Teil dieses Features.

Der Poll läuft weiter nur, wenn `send_reminder_enabled` gesetzt und ein Tray
vorhanden ist (`App._apply_send_reminder_setting`, unverändert). Der
tagesbezogene Zweig verlangt zusätzlich `send_reminder_reservations_enabled`.

### Tages-Dialog

Neuer Block unter der Reservierung, sichtbar nur wenn `send_reminder_enabled`
**und** `send_reminder_reservations_enabled` gesetzt sind **und** der
Reservierungs-Block selbst sichtbar ist (`reservation_block_visible`):

```
— Erinnerung —
[x] Ans Verschicken der Arbeitszeiten erinnern
    Slot:  [13:00–17:00  Kunde ▾]
    [15 ▾] Minuten vor Ende
```

- Die Slot-Combo speist sich **live** aus den Reservierungs-Zeilen des Dialogs,
  also auch aus gerade über „+ Slot" hinzugefügten. Vorauswahl ist der letzte
  Slot, bzw. der bereits markierte Slot beim Öffnen.
- Ohne Reservierungs-Zeile ist die Checkbox deaktiviert, mit Hinweiszeile
  „Erst eine Reservierung anlegen."
- Gespeichert wird über denselben Speichern-Button, alles-oder-nichts wie
  gehabt. Kein eigener Lösch-Weg — die Markierung verschwindet mit dem Slot.

Die Zuordnung wandert als Tk-freier Helfer aus dem Dialog heraus:

```python
def apply_reminder_to_slots(res_slots, slot_index, minutes, enabled):
    """Setzt send_reminder_minutes am gewählten Slot und None an allen anderen
    (Invariante: höchstens ein markierter Slot pro Tag). enabled=False oder ein
    ungültiger Index → alle Slots None."""
```

Der Dialog ruft ihn im Speichern-Pfad auf, bevor `reservation_store.save`
läuft. Damit bleibt die Regel testbar, ohne Tk zu instanziieren.

## Zeitraum-Vorbelegung im Sende-Dialog

Neu in `src/send_reminder.py`:

```python
def previous_anchor_date(today, marked_dates, monthly_dates):
    """Das größte Datum aus marked_dates | monthly_dates, das echt vor `today`
    liegt — oder None."""
```

- `marked_dates`: alle Daten aus `reservation_store.get_all_raw()`, deren Slots
  einen Marker tragen (Tombstones ausgenommen).
- `monthly_dates`: die berechneten Monatstermine des aktuellen und der beiden
  vorangehenden Monate (inklusive Clamp und Verschiebung) — nur wenn
  `send_period_anchor_monthly` gesetzt ist, sonst leer. Zwei Vormonate reichen,
  weil ein näherer Anker jeden älteren verdrängt.
- Von-Datum = Anker **+ 1 Tag**, Bis-Datum = heute (einschließlich).
- Kein Anker gefunden → bisheriger Default (`_default_from_date`).

`build_period_picker` bekommt einen optionalen Parameter `from_default=None`;
ohne ihn bleibt das Verhalten exakt wie heute. Nur der **Sende**-Dialog setzt
ihn — der Export-Dialog behält bewusst das Vormonats-Pendant, weil die Option
vom Verschicken handelt.

Dafür muss `open_send_dialog` den `reservation_store` durchgereicht bekommen;
`ui.py` übergibt ihn heute nur an Share- und Import-Dialog.

Die Vorbelegung greift **immer**, solange `send_period_from_last_reminder`
gesetzt ist — unabhängig davon, ob gerade eine Erinnerung gefeuert hat. Es gibt
keinen „Erinnerung offen"-Zustand, der persistiert werden müsste.

Beispiel: markierte Tage 02.08. und 05.09., Monatstermin am 23. Am 05.09. mit
`send_period_anchor_monthly = False` → Von 03.08., Bis 05.09.; mit `True` →
Von 24.08., Bis 05.09.

## Tests

Alles Neue ist Tk-frei und wird getestet (Projektkonvention: Logik, nicht UI):

- `tests/test_send_reminder.py` — `shift_off_free_days` in allen drei Modi,
  Monatsgrenze bei `"forward"`, Feiertage in `free_dates`, Zusammenspiel mit
  dem Monatslängen-Clamp; `due_day_reminder` (fällig, noch nicht fällig,
  nachgeholt, ungültige Werte, kein markierter Slot); `previous_anchor_date`
  (nur markierte Tage, mit Monatsterminen, kein Anker, Anker heute).
- `tests/test_send_reminder_scheduler.py` — tagesbezogener Toast feuert,
  Dedup verhindert den zweiten im selben Tick-Lauf, Tageswechsel setzt zurück,
  ohne `send_reminder_reservations_enabled` passiert nichts, beide Kanäle
  können am selben Tag feuern.
- `tests/test_reservations.py` — `send_reminder_minutes` überlebt
  `save`/`get`/`_user_shape`; fehlendes Feld in Altdaten wird zu `None`.
- `tests/test_reservations_sync.py` — Marker überlebt „lokal gewinnt" und wird
  in `_adopt_remote` positionsweise übernommen.
- `tests/test_share.py` — Regressionstest: ein Share-Doc mit markierter
  Reservierung enthält das Feld **nicht** und besteht `parse_share_doc`.
- `tests/test_entry_dialog.py` — `apply_reminder_to_slots` (Invariante, Index
  außerhalb, deaktiviert).
- `tests/test_settings.py` — Defaults und Coercion der sechs neuen Keys.

## Dokumentation

- `CLAUDE.md` — Reservierungs-Schema um das Feld ergänzen, den Abschnitt zu
  `send_reminder.py`/`send_reminder_scheduler.py` um den zweiten Kanal und die
  Verschiebung erweitern.
- `src/CLAUDE.md` — Verantwortlichkeiten von `SendReminderScheduler`
  (neue Abhängigkeit `reservation_store`) nachziehen.
- `CHANGELOG.md` — Feature-Eintrag beim Release-PR.

## Bewusst nicht enthalten

- Kein interaktiver Toast-Button („Jetzt senden") — hängt am ungemergten
  Branch `feat/toast-button-arbeitszeit`.
- Keine Markierung an Arbeitszeit-Slots; Anker sind ausschließlich
  Reservierungen.
- Kein Persistieren des tatsächlichen Versand-Zeitpunkts; das Von-Datum leitet
  sich allein aus den Erinnerungs-Ankern ab.
- Keine Synchronisierung der Markierung über Geräte hinweg.
