# Reservierungs-Erinnerungen mit Toast-Notification (Design)

**Datum:** 2026-07-02
**Branch:** `feat/reservation-reminders` (gestackt auf `feat/settings-tabs-ui`, PR #112)
**Scope:** Neue optionale Toast-Erinnerung, wenn ein reservierter Zeitslot mit
Kategorie endet, ohne dass für diese Kategorie am selben Tag Ist-Zeit erfasst
wurde. Dazu eine dedizierte Checkbox, um Toasts überhaupt zu aktivieren, plus
ein einstellbares „N Minuten vor Ende".

## Ausgangslage (Status quo)

- Toasts laufen ausschließlich über `TrayIcon.notify()` (`src/tray.py`):
  Windows via pystray (Balloon mit App-Icon, `_notify_with_icon`), macOS via
  `NSUserNotification` (`src/tray_mac.py`, deprecated, best-effort), **Linux hat
  kein Tray → keine Toasts**.
- Der Tray existiert heute **nur, wenn `minimize_to_tray` aktiv ist**
  (`ui.py::_apply_tray_setting`). Ohne Tray gibt es keinen Notification-Kanal.
  Der bisherige einzige Toast (Sync-Push beim Beenden) prüft `get_tray()` und
  macht nichts, wenn kein Tray da ist.
- macOS-Tray ist **dormant** (Opt-in `ZEIT_MACOS_TRAY=1`, `is_supported()`) bis
  zum manuellen Mac-Gate.
- Reservierungen (`reservations.py`): pro ISO-Datum
  `slots:[{start, end, kategorie, gcal_event_id}]`, `start`/`end` als `"HH:MM"`.
- Ist-Zeiten (`storage.py`): pro ISO-Datum
  `slots:[{start, end, pause, kategorie}]`.
- Es gibt **keinen periodischen Timer**; alle Hintergrund-Tasks
  (`background_tasks.py`) sind One-Shot beim Start.

## Getroffene Entscheidungen (aus dem Brainstorming)

1. **Match-Regel:** „Arbeitszeit noch nicht eingetragen" = es existiert an dem
   Tag **kein Ist-Zeit-Slot mit derselben Kategorie**. Kategorie-Ebene, keine
   Zeitfenster-Überlappung.
2. **Nur kategorisierte Reservierungen** lösen Reminder aus. Reservierungen mit
   leerer Kategorie werden ignoriert. **Das wird dem User in der UI mitgeteilt.**
3. **Kanal entkoppelt:** Der Tray läuft künftig, wenn `minimize_to_tray`
   **oder** `reminders_enabled`. Notifications aktivieren erzeugt bei Bedarf ein
   Tray-Icon als Toast-Kanal, auch ohne Minimize-to-Tray.
4. **Plattform-Gate:** Notifications folgen exakt dem bestehenden
   `is_supported()`-Gate — voll unter Windows, unter macOS nur mit dem
   vorhandenen Opt-in (dormant), unter Linux nicht angeboten. Kein macOS-Ausbau
   in diesem PR.
5. **Zwei sich gegenseitig ausschließende Toast-Typen pro Slot:**
   - `upcoming` (normal): feuert, während man im Slot ist, N Minuten vor `end` —
     Fenster `[max(start, end − N), end)`.
   - `missed` (verpasst): feuert, wenn die App den Slot erst sieht, wenn `end`
     schon vorbei ist (App zu spät gestartet / war im Fenster geschlossen).
   Pro Slot feuert **genau einer** von beiden.
6. **Einmal pro Slot**, `already_fired` **nur im Speicher** — ein Neustart darf
   denselben Slot erneut auslösen (bewusst akzeptiert).
7. **N (Minuten vor Ende):** Ganzzahl **0–120**, Default **15**, Schritt 5,
   **validiert**. `N ≥ Slot-Länge` → `upcoming` feuert beim Slot-Start (untere
   Fenstergrenze auf `start` geklammert).
8. Reminder gelten nur für **heutige** Reservierungen.

## Komponenten

### Neue Settings (gerätelokal, NICHT synced)
In `settings.py::DEFAULTS`:
- `reminders_enabled`: `bool`, Default `False`
- `reminder_minutes_before`: `int`, Default `15`

**Nicht** in `SYNCED_SETTING_KEYS` (Toast-Verhalten ist pro Gerät, konsistent zu
`minimize_to_tray`/`autostart`/`ui_scale`).

Reiner Validator in `settings.py` (analog `parse_hourly_rate`, testbar):
```
parse_reminder_minutes(value) -> int | None
```
Liefert eine Ganzzahl in `[0, 120]` oder `None` (nicht-numerisch / negativ /
> 120). Der Dialog nutzt `None` als Fehlersignal.

### Settings-UI (App-Tab, neuer Block „— Benachrichtigungen —")
Im getabbten Dialog (`settings_dialog.py`, App-Tab, nach dem Darstellung-Block):
- Checkbox **„Erinnerungen als Toast anzeigen"** → `reminders_enabled`.
- Zeile **„Erinnerung … Minuten vor Ende der Reservierung:"** + `dark_combo`
  mit Werten `0,5,10,…,120` → `reminder_minutes_before`.
- Hinweis-Label (klein, `TEXT_MUTED`): **„Nur für Reservierungen mit
  Kategorie."**
- `save_settings`: liest Checkbox + Minuten; Minuten über
  `parse_reminder_minutes` validieren — bei `None` → `notebook.select(App-Tab)`
  + `themed_showerror` + `return` (vor dem Settings-Write, wie die anderen
  Abbruch-Pfade). Beide Keys in das `updates`-Dict.
- Support-Gate: Aktivieren von `reminders_enabled` ohne Tray-Support verhält sich
  wie `minimize_to_tray` — `_apply_tray_setting` fällt zurück und setzt
  `reminders_enabled` mit Hinweis wieder auf `False` (Windows: ok; macOS ohne
  Opt-in / Linux: Fallback).

### Tray-Lifecycle entkoppeln (`ui.py::_apply_tray_setting`)
Bedingung für ein laufendes Tray-Icon wird verallgemeinert:
`want_tray = minimize_to_tray OR reminders_enabled`.
- Tray erzeugen, wenn `want_tray` und noch keins existiert.
- Tray stoppen, wenn **weder** `minimize_to_tray` **noch** `reminders_enabled`.
- Das Schließen-→-Tray-Verhalten (`_on_close`/`_restore_from_tray`) bleibt an
  `minimize_to_tray` gebunden; bei nur `reminders_enabled` dient das Icon
  ausschließlich als Toast-Kanal.
- Fällt die Tray-Erzeugung (unsupported/Fehler) zurück, werden **beide** ihre
  jeweils auslösenden Settings zurückgesetzt bzw. der Nutzer informiert — der
  bestehende `minimize_to_tray`-Fallback wird um `reminders_enabled` ergänzt.

### Reminder-Logik — pur & Tk-frei (`src/reminders.py`)
`now` und `minutes_before` sind Parameter (keine `datetime.now()`-Bindung →
testbar). Signatur:
```
Reminder = namedtuple("Reminder", ["key", "kind", "kategorie", "end"])
# kind ∈ {"upcoming", "missed"}; key = (date_iso, start, end, kategorie)

def due_reminders(reserved_slots, logged_categories, now_dt,
                  minutes_before, already_fired) -> list[Reminder]
```
- `reserved_slots`: heutige Reservierungs-Slots (`[{start, end, kategorie}]`).
- `logged_categories`: `set` der **nicht-leeren** Kategorien, die heute als
  Ist-Zeit vorkommen.
- Pro Slot mit **gesetzter** Kategorie, deren Kategorie **nicht** in
  `logged_categories` ist und dessen `key` **nicht** in `already_fired`:
  - `start`/`end` zu `datetime` am heutigen Datum parsen; ungültig/fehlend →
    Slot überspringen.
  - `now ≥ end` → `missed`.
  - sonst `now ≥ max(start, end − minutes_before)` → `upcoming`.
  - sonst → nicht fällig (kein Eintrag).
- Reihenfolge (`missed` vor `upcoming`-Fenster) sichert die gegenseitige
  Ausschließung über die Zeit: läuft die App durchs Fenster, greift `upcoming`
  und markiert den Slot; wird der Slot erst nach `end` gesehen, greift `missed`.

### Scheduler (`src/reminder_scheduler.py`)
`ReminderScheduler` — dünne Tk-Naht, hält die Entscheidungslogik draußen:
- Konstruktor injiziert: `root` (für `after`), `settings`, `storage`,
  `reservation_store`, `get_tray` (→ `App._tray`), und optional einen
  `now_provider`/`today_provider` (Default `datetime.now`) für Testbarkeit.
- `start()`: plant den ersten Tick zeitnah (z. B. `after(2000, …)`, fängt „App
  startet nach `end`"); danach `after(60_000, …)`-Schleife. Idempotent.
- `stop()`: bricht den geplanten `after` ab. Idempotent.
- `_tick()`:
  1. Heutiges ISO-Datum bestimmen; heutige Reservierungs-Slots
     (`reservation_store.get(today)`) und heutige Ist-Zeit-Kategorien
     (`storage.get(today)` → Set nicht-leerer Kategorien) sammeln.
  2. `reminders.due_reminders(...)` mit `reminder_minutes_before` und dem
     in-memory `already_fired`-Set.
  3. Für jeden Treffer: `tray.notify(text)` mit dem typ-abhängigen deutschen
     Text, dann `key` in `already_fired` aufnehmen. Der Scheduler läuft nur,
     solange ein Tray existiert (siehe App-Verdrahtung), daher ist in `_tick`
     stets ein Tray vorhanden; ein Defensive-Guard (`if tray is None: return`)
     bricht den Tick sauber ab, falls das Icon zwischenzeitlich wegfiel.
  4. Nächsten Tick planen.
- `already_fired`: `set` im Speicher; bei Datumswechsel geleert (nur „heute"
  relevant, verhindert unbegrenztes Wachstum).

Toast-Texte (Titel „Zeiterfassung"):
- `upcoming`: `Reservierung '{kategorie}' endet um {end} — Arbeitszeit noch nicht eingetragen.`
- `missed`: `'{kategorie}' (bis {end}) heute ohne erfasste Arbeitszeit.`

### App-Verdrahtung (`ui.py`)
- `App` erzeugt einen `ReminderScheduler` (wie die anderen Komponenten) und
  ruft `start()`/`stop()` abhängig von `reminders_enabled` — angestoßen in
  `_apply_tray_setting` (Tray muss existieren) und nach `_on_change`
  (Settings-Speicherung). Beim Beenden (`stop`-Pfad) `scheduler.stop()`.
- Der Scheduler wird nur gestartet, wenn `reminders_enabled` **und** ein Tray
  vorhanden ist.

## Fehler-/Edge-Handling
- Tray-`notify` ist bereits fehlertolerant (best-effort, geschluckte Fehler) —
  eine fehlgeschlagene Notification darf den Loop nicht abbrechen; `_tick`
  fängt/loggt und plant den nächsten Tick trotzdem.
- Ungültige/fehlende Slot-Zeiten werden in der puren Logik übersprungen.
- Datumswechsel um Mitternacht: nächster Tick betrachtet automatisch das neue
  „heute"; `already_fired` wird geleert.
- Reservierung ohne Kategorie: übersprungen (Entscheidung 2), UI-Hinweis klärt
  den Nutzer auf.

## Tests
- `tests/test_reminders.py` (pur, ohne Tk/echte Zeit): vor Fenster → keiner; im
  Fenster → `upcoming`; nach `end` → `missed`; Kategorie bereits erfasst →
  keiner; leere Kategorie → keiner; `key` in `already_fired` → keiner;
  `N ≥ Slotlänge` → `upcoming` bei `start`; ungültige Zeit → übersprungen.
- `tests/test_settings.py`: `parse_reminder_minutes` — gültige Werte, `0`, `120`,
  negativ → `None`, `> 120` → `None`, nicht-numerisch → `None`.
- Scheduler/Tray/Dialog: Tk-/Display-abhängig → **kein** CI-Test; lokale
  Verifikation manuell (App starten, Reservierung mit Kategorie ohne Ist-Zeit
  anlegen, Toast beobachten) + Screenshot des neuen Settings-Blocks.
- `pytest` + `ruff check .` bleiben grün.

## Nicht-Ziele
- Kein macOS-Ausbau (bleibt dormant/Opt-in), keine neue Windows-/Linux-
  Notification-API, keine OS-Level-Scheduler (Reminder nur, während die App
  läuft).
- Keine Persistenz von `already_fired` über Neustarts (bewusst).
- Keine Zeitfenster-genaue Überlappungsprüfung (Kategorie-Ebene genügt).
- Keine Reminder für vergangene/zukünftige Tage.

## Plattform-Hinweis (Pre-Release)
Tray/Notification-Verhalten ist auf der Windows-Dev-Maschine nicht für
macOS/Linux verifizierbar. Gemäß Root-`CLAUDE.md` beim PR einen Pre-Release
vorschlagen; macOS bleibt hinter dem `ZEIT_MACOS_TRAY`-Opt-in dormant.
