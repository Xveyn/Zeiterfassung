# Monatlicher Sende-Reminder mit Toast-Notification (Design)

**Datum:** 2026-07-15
**Branch:** TBD (Feature-Branch beim Implementierungsstart)
**Scope:** Neue optionale Toast-Erinnerung „Arbeitszeiten verschicken", die
einmal pro Monat an einem konfigurierbaren Tag + Uhrzeit feuert. Analog zum
bestehenden Reservierungs-Reminder (`src/reminders.py` /
`src/reminder_scheduler.py`), aber eigenständiger Toggle und eigene
Fälligkeitslogik (kein Bezug zu Reservierungen/Ist-Zeiten).

## Ausgangslage (Status quo)

- Toast-Kanal ist `TrayIcon.notify()` (`src/tray.py`), Plattform-Gate über
  `tray.is_supported()`: Windows voll, macOS dormant hinter
  `ZEIT_MACOS_TRAY=1`, Linux kein Tray → keine Toasts.
- Der Tray läuft, sobald `minimize_to_tray` **oder** `reminders_enabled`
  aktiv ist (`ui.py::_apply_tray_setting`).
- `ReminderScheduler` (`src/reminder_scheduler.py`) pollt minütlich über
  `root.after`, mit einem zeitnahen ersten Tick (`_INITIAL_DELAY_MS = 2000`)
  — das fängt den Fall „App startet, nachdem der Fällig-Zeitpunkt schon
  vorbei ist" (`missed`-Kind in `src/reminders.py::due_reminders`).
  `already_fired` lebt dort nur im Speicher (Neustart darf denselben Slot
  erneut auslösen — bewusst akzeptiert für den Tages-Anwendungsfall).
- Settings-Konvention: gerätelokale UI-Optionen (`minimize_to_tray`,
  `reminders_enabled`, `reminder_minutes_before`, …) leben in
  `settings.py::DEFAULTS`, sind **nicht** in `SYNCED_SETTING_KEYS`.
- Datumskonvention (Projekt-`CLAUDE.md`): intern **immer ISO**
  (`YYYY-MM-DD`), in der UI **immer deutsch** (`TT.MM.JJJJ`) über
  `time_utils.py::format_iso_date`/`format_iso_datetime`.
- Tray-Quick-Action „Arbeitszeiten senden" existiert bereits
  (`ui.py::_apply_tray_setting`, ruft `App._send`) — der Nutzer kann nach
  dem Toast direkt darüber reagieren, ohne das Fenster erst zu öffnen.

## Getroffene Entscheidungen (aus dem Brainstorming)

1. **Eigenständiger Toggle**, nicht an `reminders_enabled` gekoppelt — beide
   Reminder-Arten sind unabhängig voneinander nutzbar.
2. **Tag im Monat clamped auf die tatsächliche Monatslänge:** Tag 31 im
   Februar → 28./29., im April → 30. Kein separater „letzter Tag"-Spezialwert
   nötig, Clamping deckt die Absicht ab (`calendar.monthrange`).
3. **Fired-Tracking persistiert** (User-Entscheid, abweichend vom
   Reservierungs-Reminder): neues Settings-Feld
   `send_reminder_last_fired_month` (ISO `"YYYY-MM"`, gerätelokal) merkt sich
   den zuletzt benachrichtigten Monat dauerhaft. Verhindert, dass der Toast
   bei jedem App-Neustart im selben Monat erneut erscheint.
4. **Catch-up nach App-Start, wenn der Zeitpunkt verpasst wurde** (User-
   Bestätigung, analog Reservierungen): die Fälligkeitsprüfung ist rein
   zustandsbasiert (`now ≥ Fällig-Zeitpunkt UND aktueller Monat ≠
   last_fired_month`), unabhängig davon, ob die App durchgehend lief. Der
   neue Scheduler nutzt denselben zeitnahen ersten Tick
   (`_INITIAL_DELAY_MS = 2000`) wie `ReminderScheduler` — startet die App
   nach dem konfigurierten Zeitpunkt, feuert der Toast beim ersten Tick,
   exakt wie das `missed`-Verhalten bei Reservierungen.
5. **Datumsformat:** `send_reminder_day` ist eine Tageszahl (1–31), keine
   Datums-String — Format-Frage stellt sich dort nicht. Das einzige
   persistierte Datum-artige Feld ist `send_reminder_last_fired_month`
   (ISO `"YYYY-MM"`, reiner interner Zustand, nie in der UI angezeigt). Der
   Toast-Text zeigt den Monat als deutschen Namen (`MONTHS_DE`), kein
   `isoformat()`/`str()`-Datum in der UI.
6. **Plattform-Gate:** exakt das bestehende `is_supported()`-Gate, keine
   Erweiterung. Damit funktioniert der Toast heute nur unter Windows
   (macOS nur mit vorhandenem Opt-in) — bekannte, bereits akzeptierte
   Einschränkung, keine neue Lücke.
7. **Toast rein informativ**, kein Klick-Handler (pystray-`notify()`
   unterstützt hier keinen Callback) — Reaktion läuft manuell über
   Tray-Menü/App, wie beim Reservierungs-Reminder.

## Komponenten

### Neue Settings (gerätelokal, NICHT synced)
In `settings.py::DEFAULTS`:
- `send_reminder_enabled`: `bool`, Default `False`
- `send_reminder_day`: `int`, Default `1` (1–31, Tag im Monat)
- `send_reminder_time`: `str`, Default `"18:00"` (`"HH:MM"`)
- `send_reminder_last_fired_month`: `str`, Default `""` (ISO `"YYYY-MM"` oder leer)

Keine dieser vier Keys in `SYNCED_SETTING_KEYS` (Toast-Verhalten ist pro
Gerät, konsistent zu `reminders_enabled`).

### Settings-UI (App-Tab, bestehender „— Benachrichtigungen —"-Block)
In `tab_app.py`, nach dem bestehenden Reservierungs-Reminder-Block:
- Checkbox **„Erinnerung zum Verschicken der Arbeitszeiten"** →
  `send_reminder_enabled`.
- Zeile **„Tag im Monat:"** + `dark_combo` (readonly) mit Werten `"1"`…`"31"`
  → `send_reminder_day`, danach **„um"** + `dark_combo` (readonly) mit
  `TIME_VALUES` (5-Minuten-Raster, wie überall sonst) → `send_reminder_time`.
- Hinweis-Label (klein, `TEXT_MUTED`): **„Bei kürzeren Monaten wird auf den
  letzten Tag verschoben."**
- `save_settings` (`dialog.py`): beide Comboboxes sind `state="readonly"` →
  Werte immer aus der vorgegebenen Liste, keine Fehler-Validierung nötig
  (Muster wie `default_pause`: direktes `int(...)`/`str(...)`-Casting ins
  `updates`-Dict, kein eigener Parser).
- Support-Gate: identisch zum bestehenden Fallback — schlägt Tray-Start
  fehl / ist die Plattform nicht unterstützt, wird `send_reminder_enabled`
  zusätzlich zu `minimize_to_tray`/`reminders_enabled` auf `False`
  zurückgesetzt (beide bestehenden Fallback-Stellen in
  `ui.py::_apply_tray_setting` erweitert).

### Tray-Lifecycle (`ui.py::_apply_tray_setting`)
`want_tray` bekommt ein drittes ODER-Kriterium:
`minimize_to_tray OR reminders_enabled OR send_reminder_enabled`.

### Reminder-Logik — pur & Tk-frei (`src/send_reminder.py`)
```
def scheduled_datetime(year, month, day, time_str) -> datetime | None
# Tag auf calendar.monthrange(year, month)[1] geclamped; time_str ungültig -> None.

def is_due(now_dt, day, time_str, last_fired_month) -> bool
# current_month = f"{now_dt.year:04d}-{now_dt.month:02d}"
# False, wenn last_fired_month == current_month (schon gefeuert)
# sonst: now_dt >= scheduled_datetime(now_dt.year, now_dt.month, day, time_str)
```
Keine Slot-/Kategorie-Logik nötig — ein einzelner Fällig-Zeitpunkt pro
Monat, kein Fenster (kein „upcoming", nur „fällig ja/nein").

### Scheduler (`src/send_reminder_scheduler.py`)
`SendReminderScheduler` — dünne Tk-Naht, gleiche Form wie
`ReminderScheduler`:
- Konstruktor injiziert `root`, `settings`, `get_tray`, optional
  `now_provider` (Default `datetime.now`).
- `start()`/`stop()`: identisches `after`-Muster (`_INITIAL_DELAY_MS = 2000`,
  `_INTERVAL_MS = 60_000`), idempotent.
- `poll(now_dt)`:
  1. `tray = get_tray()`; `None` → no-op (return `False`).
  2. `day`/`time_str`/`last_fired` aus `settings` lesen.
  3. `send_reminder.is_due(...)` prüfen.
  4. Bei Fälligkeit: `tray.notify(text)`, danach
     `settings.set("send_reminder_last_fired_month", f"{now_dt.year:04d}-{now_dt.month:02d}")`
     (Persistenz **nach** dem erfolgreichen `notify`-Aufruf).
  5. Gibt zurück, ob benachrichtigt wurde (für Tests).
- `_tick()` fängt/loggt Exceptions wie `ReminderScheduler`, plant den
  nächsten Tick in jedem Fall weiter.

Toast-Text (Titel „Zeiterfassung"):
`f"Zeit, deine Arbeitszeiten für {MONTHS_DE[now_dt.month - 1]} zu verschicken."`

### App-Verdrahtung (`ui.py`)
- Neue Instanz `self._send_reminders = SendReminderScheduler(self.root,
  self.settings, lambda: self._tray)` neben `self._reminders`.
- Neue `_apply_send_reminder_setting()`, analog `_apply_reminder_setting()`:
  `want = bool(settings.get("send_reminder_enabled")) and self._tray is not None`.
  **Muss** nach `_apply_tray_setting()` laufen (wie beim bestehenden
  Reminder) — beide Call-Sites (`__init__`, Settings-`_on_change`) rufen
  beide `_apply_*_setting`-Methoden in derselben Reihenfolge.
- `.stop()` an beiden bestehenden Shutdown-Stellen ergänzt (dort, wo aktuell
  `self._reminders.stop()` steht).

## Fehler-/Edge-Handling
- Ungültiger `send_reminder_time`-Wert (sollte durch readonly-Combobox nicht
  vorkommen) → `scheduled_datetime` liefert `None` → `is_due` → `False`,
  kein Crash.
- Persistenter Schreibfehler bei `settings.set(...)` nach dem Notify würde
  wie jeder andere Settings-Write behandelt (bestehendes Verhalten von
  `Settings._save_to_disk`, nicht neu zu bauen).
- Monatswechsel während die App durchgehend läuft: nächster Poll sieht
  automatisch den neuen `current_month` und damit erneut „nicht gefeuert".
- Mehrere übersprungene Monate (App war lange nicht offen): es wird **nur**
  für den aktuellen Monat nachgeholt, kein Backfill vergangener Monate
  (konsistent zu „keine Reminder für vergangene Tage" bei Reservierungen).

## Tests
- `tests/test_send_reminder.py` (pur): Clamping Tag 31 im Februar/April auf
  Monatsende; Fälligkeit vor/nach Zeitpunkt; `last_fired_month == aktueller
  Monat` → nicht fällig; `last_fired_month` aus Vormonat + Zeitpunkt bereits
  vorbei → fällig (Catch-up-Fall); ungültiger `time_str` → nicht fällig.
- `tests/test_send_reminder_scheduler.py` (analog `tests/test_reminder_scheduler.py`):
  `poll()` ohne Tray → no-op; fälliger Poll → `tray.notify` aufgerufen +
  `settings` aktualisiert; zweiter Poll im selben Monat → kein erneutes Notify.
- Settings-UI/Tray/Scheduler-Wiring: Tk-/Display-abhängig → kein CI-Test,
  lokale Verifikation manuell (Tag/Uhrzeit auf „in 2 Minuten" stellen, Toast
  beobachten; App nach verpasstem Zeitpunkt neu starten, Catch-up-Toast
  beobachten).
- `pytest` + `ruff check .` bleiben grün.

## Nicht-Ziele
- Kein automatisches Versenden — der Toast erinnert nur, der Versand bleibt
  manuell (Tray-Aktion „Arbeitszeiten senden" oder App).
- Kein Sync des Fälligkeits-Zustands über Geräte hinweg (gerätelokal, wie
  alle Toast-Settings).
- Kein Ausbau der Plattform-Unterstützung (Linux weiterhin ohne Tray, macOS
  weiterhin hinter Opt-in).
- Kein separater „letzter Tag des Monats"-Spezialwert — Clamping auf 1–31
  deckt den Anwendungsfall ab.

## Plattform-Hinweis (Pre-Release)
Tray/Notification-Verhalten ist auf der Windows-Dev-Maschine nicht für
macOS/Linux verifizierbar. Gemäß Root-`CLAUDE.md` beim PR einen Pre-Release
vorschlagen; macOS bleibt hinter dem `ZEIT_MACOS_TRAY`-Opt-in dormant.
