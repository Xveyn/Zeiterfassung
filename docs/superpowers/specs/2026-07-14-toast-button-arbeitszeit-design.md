# Arbeitszeit per Toast-Button eintragen (Design)

**Datum:** 2026-07-14
**Branch:** `feat/toast-button-arbeitszeit`
**Scope:** Reservierungs-Erinnerungen bekommen auf **Windows** einen echten Button
**„Arbeitszeit eintragen"** direkt auf dem Toast. Ein Klick schreibt den
Reservierungs-Slot (Soll) als Ist-Zeit. macOS/Linux behalten den einfachen Toast
ohne Button (unveränderter Fallback).

## Ausgangslage (Status quo)

- Reservierungs-Erinnerungen bestehen bereits (Design
  `2026-07-02-reservation-reminders-design.md`): `reminders.py` (pur) entscheidet
  pro heutigem Reservierungs-Slot **mit Kategorie** ohne erfasste Ist-Zeit, ob
  `upcoming` (N Min vor Ende) oder `missed` (nach Ende) fällig ist.
  `reminder_scheduler.py` pollt minütlich (`root.after`) und schickt reinen
  **Text** über `tray.notify(...)`. Jeder Slot feuert genau einmal
  (`already_fired`-Set, nur im Speicher).
- Toast-Kanal = `tray.py::notify()`: Windows via **pystray-Balloon** (mit
  App-Icon, `_notify_with_icon`), macOS via `NSUserNotification`
  (`tray_mac.py`, deprecated, best-effort), **Linux: kein Tray → keine Toasts**.
- **pystray-Balloons können keine Buttons und keinen Klick-Callback** (bestätigt:
  pystray #92 / Feature-Request). Ein Button *auf* dem Toast geht nur über eine
  echte WinRT-Toast-Lib.
- Der Tray läuft, sobald `minimize_to_tray` **oder** `reminders_enabled` aktiv ist
  (`ui.py::_apply_tray_setting`). Bei nur `reminders_enabled` dient das Icon
  ausschließlich als Toast-Kanal.
- Reservierung (`reservations.py`): pro ISO-Datum
  `slots:[{start, end, kategorie, gcal_event_id}]`, Zeiten `"HH:MM"`.
- Ist-Zeit (`storage.py`): pro ISO-Datum `slots:[{start, end, pause, kategorie}]`.
  `storage.save(date, slots)` normalisiert jeden Slot (fehlende `pause` → 0,
  fehlende `kategorie` → "").
- Pro-Kategorie-Defaults existieren: `category_defaults.resolve_slot_defaults(
  category_times, kategorie, weekday_key, g_start, g_end, g_pause)` liefert
  `(start, end, pause)`; der Tages-Dialog nutzt es mit `default_pause` (Default 30)
  und `weekday_key = WEEKDAY_KEYS[day.weekday()]`.

## Getroffene Entscheidungen (aus dem Brainstorming)

1. **Windows-First.** Kernstück ist der echte Button auf dem Windows-Toast via
   `windows-toasts` (WinRT). macOS/Linux bekommen **keinen** Button — dort bleibt
   der einfache Toast (bestehendes `notify()`).
2. **Gestaffelt.** Dieser PR = Stufe 1 (Windows-Toast-Button). Eine plattform-
   konsistente Tray-Quick-Action als Cross-Platform-Ersatz ist **Nicht-Ziel** und
   bleibt ein möglicher Folge-PR.
3. **Button auf beiden Typen** (`upcoming` **und** `missed`). Bei `upcoming` trägt
   der Klick den vollen geplanten Slot (`start`–`end`) ein, auch wenn das Ende noch
   nicht erreicht ist — die Reservierung ist die Planung, die der Nutzer bestätigt.
4. **Was der Klick schreibt:** ein Ist-Zeit-Slot `{start, end, pause, kategorie}`,
   wobei `start`/`end`/`kategorie` **aus der Reservierung** kommen und `pause` über
   `resolve_slot_defaults` aus dem Per-Kategorie-Default (Fallback `default_pause`)
   abgeleitet wird — genau wie beim manuellen Anlegen im Tages-Dialog. Angehängt an
   die heutigen Ist-Slots. **Die Reservierung bleibt bestehen** (separates Konzept).
5. **Nur kategorisierte Reservierungen** — bereits Vorbedingung der Reminder-Logik,
   keine Änderung nötig.
6. **Callback nur bei laufender App.** Der `on_activated`-Callback feuert
   in-process, solange die App läuft und den WinRT-Loop pumpt — deckt sich mit dem
   Reminder-Design („nur während die App läuft"). **Keine** COM-Aktivierung bei
   geschlossener App (Nicht-Ziel).

## Komponenten

### Neue Dependency (`requirements.txt`)
- `Windows-Toasts==<pin>; sys_platform == "win32"` — analog zum bestehenden
  `pyobjc-framework-Cocoa==…; sys_platform == "darwin"`. Beim Pinnen gegen
  **Python 3.10** gegenchecken (windows-toasts deklariert 3.9–3.12; CI-/Release-
  Python ist 3.10 ✓).
- In die README-Abhängigkeiten-Tabelle aufnehmen (Pinning-Regel).

### Notify-Layer (`src/tray.py`)
Neue Fassaden-Methode `notify_action(message, title, action_label, on_action)`:
- **`_PystrayBackend` (Windows):** Wenn `windows-toasts` **lazy** importierbar →
  `InteractableWindowsToaster(...)` + `Toast(...)` mit
  `AddAction(ToastButton(action_label, arguments="log"))` und
  `toast.on_activated = lambda args: on_action()` → `show_toast(toast)`. Das
  Toast-/Toaster-Objekt als **starke Referenz** halten (sonst GC → Callback tot).
  Bei **jedem** Fehler oder fehlender Lib → Fallback auf das bestehende
  `self.notify(message, title)` (Plain-Balloon ohne Button). Der Import trägt
  `# pyright: ignore[reportMissingImports]` (nicht in CI-Deps, wie pystray/pyobjc).
- **`MacTrayBackend`:** ignoriert Button/Callback, ruft `self.notify(message,
  title)` (bestehendes Verhalten, macOS bleibt dormant/opt-in).
- **`TrayIcon`-Fassade:** delegiert `notify_action` an das Backend (wie `notify`);
  ohne Backend no-op.
- `on_action` ist 0-arg und **marshallt selbst** auf den Tk-Thread
  (`root.after(0, …)`), wie die bestehenden Tray-Actions und `on_show`/`on_quit`.

### AUMID (Windows-Aktivierung)
Damit `on_activated` zuverlässig feuert (v.a. nachdem der Toast ins Action Center
wandert), braucht der Prozess einen **eigenen AUMID**:
- **Laufzeit:** früh in `main.py` (Windows-Zweig) den Prozess-AUMID via
  `ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("…")` setzen; den
  gleichen String an den `InteractableWindowsToaster` übergeben.
- **Installer:** denselben AUMID am Start-Menü-Shortcut in `installer.iss` setzen
  (`AppUserModelID`).
- **Abgrenzbar:** Der AUMID-/Installer-Teil ist ein diskretes, nur-Windows-
  verifizierbares Stück. Er kann zeitlich vom App-Logik-Kern getrennt umgesetzt
  werden, gehört aber in denselben PR, weil der Callback ohne ihn unzuverlässig ist.

### Slot-Bauen — pur & Tk-frei
Neue Funktion (in `reminders.py`, neben der Fälligkeitslogik):
```
ist_slot_from_reservation(res_slot, category_times, weekday_key,
                          g_start, g_end, g_pause) -> dict
```
- `start`/`end`/`kategorie` aus `res_slot`; `pause` = dritter Rückgabewert von
  `resolve_slot_defaults(category_times, kategorie, weekday_key, g_start, g_end,
  g_pause)` (nur die Pause wird übernommen, Start/Ende bleiben die der
  Reservierung). Rückgabe `{start, end, pause, kategorie}`. Rein → Unit-Test.

### Scheduler-Verdrahtung (`src/reminder_scheduler.py`)
- Konstruktor bekommt zusätzlich `data_lock` und einen `on_logged`-Callback
  (= `App._refresh`) injiziert.
- In `poll(...)` statt `tray.notify(_toast_text(rem))`:
  `tray.notify_action(_toast_text(rem), "Zeiterfassung", "Arbeitszeit eintragen",
  on_action)`, wobei `on_action` eine Closure pro Reminder ist, die die Slot-Daten
  (`start`/`end`/`kategorie`) und das heutige Datum captured.
- `on_action` (läuft nach dem Marshalling auf dem Tk-Thread):
  1. `with data_lock:` heutige Storage-Slots lesen, den via
     `ist_slot_from_reservation(...)` gebauten Slot **anhängen**,
     `storage.save(today, slots)`.
  2. `on_logged()` aufrufen (Kalender-Refresh).
- Idempotenz: Nach dem Eintragen ist die Kategorie erfasst → `due_reminders`
  liefert den Slot nicht mehr; ein erneuter Klick auf einen alten, noch sichtbaren
  Toast würde den Slot ein zweites Mal anhängen. Das ist ein bewusst akzeptierter
  Rand-Fall (der Toast verschwindet nach Klick; Doppel-Eintrag ist über Rechtsklick
  im Kalender löschbar). Kein Dedup in Stufe 1.

### App-Verdrahtung (`src/ui.py`)
- `ReminderScheduler(...)` bekommt `data_lock` (der geteilte RLock aus `main()`,
  bereits an die Stores gereicht) und `on_logged=self._refresh` injiziert. Sonst
  unverändert — Start/Stop weiter über `_apply_reminder_setting` an
  `reminders_enabled` + laufendes Tray gekoppelt.

### Build (`build.py`, Windows-Branch)
- PyInstaller muss das WinRT-Binärpaket bündeln, das `windows-toasts` zieht
  (`--collect-all <winrt/winsdk-Paket>`). **Exakter Paketname bei der Umsetzung
  gegen die gepinnte `windows-toasts`-Version verifizieren** (neuere Versionen
  nutzen die `winrt-Windows.*`-Pakete statt des monolithischen `winsdk`).

## CI-Auswirkungen (`.github/workflows/test.yml`)
Alle Test-Jobs (Matrix 3.10–3.13, `test-macos`, `test-windows`, `coverage`,
`lint`, `typecheck`) installieren **`requirements-test.txt`**, nicht
`requirements.txt`. `windows-toasts` ist damit in **keinem** CI-Job vorhanden —
auch nicht auf `test-windows` (windows-latest, 3.10). Daraus folgen drei Auflagen:

1. **Import zwingend lazy** (nur im interaktiven Windows-Notify-Pfad), mit
   `# pyright: ignore[reportMissingImports]`. `import src.tray`/`import src.ui`
   müssen ohne die Lib durchlaufen — sonst brechen `test-windows` **und** die
   Ubuntu-Matrix beim Import. (Exakt das bestehende Muster für
   pystray/pyobjc/Pillow/xhtml2pdf.)
2. **`windows-toasts` kommt NICHT in `requirements-test.txt`** — konsistent zur
   Regel „Toast/Tray-Code wird nicht in CI getestet, sondern manuell verifiziert".
   Der echte WinRT-Toast braucht Display + WinRT-Loop → headless-CI-untauglich.
3. **Testbare Nähte laufen ohne die Lib auf jeder Plattform:** der reine
   Slot-Builder, der Scheduler-Poll mit **Fake-Tray** (prüft den
   `notify_action`-Payload), und der `notify_action` → Plain-`notify`-Fallback
   (Lib fehlt → Mock). Damit bleibt `test-windows` grün, ohne den Toast real zu
   feuern.

## Tests
- `tests/test_reminders.py` (erweitern): `ist_slot_from_reservation` — Pause aus
  Per-Kategorie-Default, Fallback auf `default_pause`, `per_day`-Mode, unbekannte
  Kategorie; Start/Ende immer aus der Reservierung übernommen.
- `tests/test_reminder_scheduler.py` (erweitern): `poll` ruft `notify_action` mit
  korrektem `(text, title, action_label, callback)`; der Callback trägt unter Fake-
  Store den erwarteten Slot ein und ruft `on_logged`; nach dem Eintragen ist die
  Kategorie „erfasst" und der Slot nicht mehr fällig.
- `tests/test_tray.py` (falls vorhanden / sonst neu, pur): `notify_action` fällt
  ohne verfügbare WinRT-Lib auf `notify` zurück (Monkeypatch/Mock).
- WinRT-Toast + Button-Aktivierung + Tk = **manuelle Lokal-Verifikation** (kein
  CI): App starten, Reservierung mit Kategorie ohne Ist-Zeit für heute anlegen,
  Toast abwarten, „Arbeitszeit eintragen" klicken, Ist-Zeit im Kalender prüfen.
- `pytest` + `ruff check .` + `pyright` bleiben grün.

## Fehler-/Edge-Handling
- `notify_action` ist best-effort: jeder Fehler im WinRT-Pfad → Fallback auf Plain-
  `notify`, nie eine Exception in den Poll-Loop (der fängt/loggt ohnehin).
- Fehlender AUMID / Aktivierung im Action Center: der Callback kann dann
  unzuverlässig sein — daher AUMID (s.o.); der Toast selbst erscheint trotzdem.
- Datumswechsel/`already_fired`: unverändert aus dem bestehenden Reminder-Design.

## Nicht-Ziele
- Kein Button auf macOS/Linux; kein Ausbau des macOS-Toasts.
- Keine Tray-Quick-Action als Cross-Platform-Ersatz (möglicher Folge-PR).
- Keine COM-Aktivierung / kein Eintragen bei geschlossener App.
- Kein Dedup gegen Doppelklick auf einen alten Toast (akzeptierter Rand-Fall).
- Keine Wochenlimit-Warnung im Klick-Pfad (stiller Eintrag; Warnungen bleiben den
  bestehenden Pfaden vorbehalten).

## Plattform-Hinweis (Pre-Release)
Reine Windows-Änderung mit neuer Windows-only-Dependency + Installer-Anpassung →
gemäß Root-`CLAUDE.md` vor dem nächsten echten Release einen **Pre-Release** über
alle drei Plattformen bauen (verifiziert, dass der Nicht-Windows-Fallback und der
Frozen-Build mit dem gebündelten WinRT-Paket sauber durchlaufen).
