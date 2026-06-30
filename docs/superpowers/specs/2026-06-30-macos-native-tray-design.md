# Design: Natives macOS-Tray (NSStatusItem) statt pystray-Daemon-Thread

Datum: 2026-06-30
Branch: `fix/macos-tray-mainthread-crash`
Issue: #88

## Problem

`src/tray.py::TrayIcon.start()` startet pystray auf **allen** Plattformen in
einem Daemon-Thread (`threading.Thread(target=icon.run, daemon=True)`). Auf
macOS ist das laut pystray-Doku unzulässig: `Icon.run()` muss auf dem
Main-Thread laufen und treibt eine eigene `NSApplication`. Tkinter treibt auf
macOS **dieselbe** geteilte `NSApplication` bereits exklusiv vom Main-Thread.
Es treiben also zwei Threads dieselbe NSApp — sobald das nächste Tk-Fenster
gemappt wird (der `themed_showinfo`-Bestätigungsdialog nach „Google neu
verbinden" bzw. `on_change → _apply_tray_setting` beim Sync-/Kalender-Aktivieren,
das das Tray neu startet), kollidiert der AppKit-Zustand → ObjC-Exception →
`-[NSApplication _crashOnException:]` → Crash. Der Google-Schritt ist nur der
**Auslöser**, die Ursache ist der Daemon-Thread.

Voraussetzung für den Crash: „Beim Schließen in den Infobereich minimieren"
(Tray) ist aktiv. Diagnose abgeleitet aus dem macOS-Crash-Report + Code +
pystray-Primärdoku (Issue #88), nicht lokal reproduziert.

## Ziel

Das Minimize-to-Tray bleibt auf macOS **erhalten** (volle Plattform-Parität),
ohne den Crash. Dazu wird auf macOS kein pystray-Daemon-Thread mehr gestartet,
sondern ein natives `NSStatusItem` **synchron auf dem Main-Thread** an die von
Tk getriebene `NSApplication` gehängt (keine zweite NSApp, kein zweiter Thread,
kein zweiter Runloop). Damit ist die Zwei-Threads-eine-NSApp-Kollision per
Konstruktion ausgeschlossen.

**Windows bleibt unangetastet** — dort läuft weiter der bestehende
pystray-Daemon-Thread-Pfad (verifiziert funktionierend, null Regressionsrisiko).
Linux hat wie bisher kein Tray (`is_supported()` → False).

Projekt-Designregel: „bestmöglich gleich auf allen drei Plattformen; wenn nicht
möglich, exklusive Anpassung." Hier ist die Anpassung der macOS-exklusive
Backend-Wechsel hinter einer gemeinsamen Fassade.

## Architektur (Ansatz A: Plattform-Dispatch hinter `TrayIcon`-Fassade)

`tray.py::TrayIcon` bleibt die **öffentliche Fassade** mit unveränderter API
(`is_supported`, `start`, `stop`, `notify`). Intern wählt sie das Backend nach
`platform.system()`:

- **Windows** → bestehender pystray-Pfad (Daemon-Thread, Icon-Toast). Code
  unverändert, nur in eine interne Backend-Einheit gefasst.
- **macOS** → neues natives Backend in **`src/tray_mac.py`** (eigenes Modul,
  PyObjC **lazy** importiert).

Begründung eigenes Modul: hält die PyObjC-Imports **vollständig** aus dem
Linux/Windows-Importpfad heraus (die Test-CI importiert `src.ui → src.tray`).
Spiegelt das vorhandene Lazy-Import-Muster der Google-Wrapper (`gcal.py`,
`drive.py`).

### Testbarkeits-Schnitt (pures Modell vs. nativer Renderer)

Das macOS-Backend wird in zwei Teile getrennt:

1. **Reines Menü-Modell** (pure Python, kein AppKit) — leitet aus den `actions`
   die Menüstruktur ab: Einträge, Reihenfolge, Separatoren, welcher Eintrag eine
   dynamische `visible`-Callable trägt. **Auf jeder Plattform unit-testbar**
   (Linux-CI, Windows).
2. **Dünner nativer Renderer** (`src/tray_mac.py`) — macht aus dem Modell
   NSMenu/NSMenuItem/NSStatusItem, hält die starken Referenzen, wired Target/
   Action. Nur dieser Teil ist macOS-only und erst auf einem Mac visuell
   verifizierbar.

So liegen Backend-Auswahl und Menü-Logik in der CI-testbaren Naht; nur das nackte
AppKit-Rendering bleibt „blind".

## Verhalten

### Menü

Identisch zum heutigen: **Anzeigen** | — | **Senden / Teilen / Export / Sync** |
— | **Beenden**. Auf macOS öffnet ein Klick auf das Status-Item das Menü;
„Anzeigen" ist schlicht der erste Eintrag (keine Linksklick-vs-Rechtsklick-
Konvention für Status-Items — wie pystray-darwin es auch handhabt). Die
Callbacks sind dieselben wie heute und marshallen bereits selbst per
`root.after(0, …)` auf den Tk-Thread; die nativen Action-Methoden feuern ohnehin
auf dem Main-Thread, das Marshalling bleibt korrekt.

### Dynamische Sichtbarkeit (Sync-Eintrag)

Der Sync-Eintrag ist nur sichtbar, wenn `sync_enabled`. Umsetzung **live** über
einen `NSMenu`-Delegate (`menuNeedsUpdate_`), der vor jedem Öffnen die
`visible`-Callable neu auswertet und `item.setHidden_(…)` setzt — **echte
Windows-Parität** (Eintrag erscheint/verschwindet sofort beim Umschalten),
besser als pystray-darwins Einmal-Snapshot. Fallback bei Komplikationen:
Snapshot beim Aufbau (= heutiges, im Docstring als akzeptabel dokumentiertes
Verhalten).

### Threading

Kein Daemon-Thread auf macOS. `_apply_tray_setting` (ui.py) läuft bereits immer
auf dem UI-/Main-Thread (aus `__init__` und dem Settings-`on_change`) und ist
die einzige Stelle, die `tray.start()` ruft — das Status-Item wird dort synchron
auf dem Main-Thread erzeugt. An `ui.py` ändert sich dadurch (fast) nichts; die
Fassade kapselt den Dispatch.

### `notify()` (Sync-Toasts)

`notify()` ist vertraglich schon **fehlertolerant**. Auf macOS: **best-effort,
nie fatal** — minimaler nativer Versuch (`NSUserNotification`, leichtgewichtig,
kein Entitlement), **alle** Fehler geschluckt, defensiv auf den Main-Thread
dispatcht. Bleibt es auf neueren macOS still, funktioniert der Sync trotzdem —
nur ohne Toast. Die einzige „blinde" Funktionalität ist damit kosmetisch.

### Graceful Fallback

Wirft das native Setup **irgendeine** Exception, propagiert sie wie heute aus
`start()`. `_apply_tray_setting` fängt das bereits, zeigt `themed_showerror` und
schaltet `minimize_to_tray` ab. Kein Crash, schlimmstenfalls kein Tray.

## Betroffene Stellen

1. **`src/tray.py` — Fassade + Backend-Dispatch.**
   - `is_supported()` bleibt `Windows`/`Darwin` → True (Verhalten unverändert,
     aber Darwin ist jetzt echt unterstützt).
   - Reine Selektor-Funktion (z. B. `_select_backend(system)`), die das
     Backend nach `platform.system()` wählt — als pure Funktion testbar.
   - `start()/stop()/notify()` delegieren an das aktive Backend. Windows-Pfad
     (pystray, Daemon-Thread, `_notify_with_icon`) wandert unverändert in die
     interne Windows-Backend-Einheit.
   - Pures Menü-Modell aus `actions` ableiten — speist den macOS-Renderer und
     die Tests. Der Windows-Pfad baut sein pystray-Menü weiter inline wie heute
     (kein Verhaltens-/Code-Wechsel dort).

2. **`src/tray_mac.py` — neues Modul, natives Backend.**
   - Lazy: `import objc`, `from AppKit import NSStatusBar, NSImage, NSMenu,
     NSMenuItem, NSVariableStatusItemLength`, `from Foundation import NSObject`.
   - `NSObject`-Delegate-Subklasse hält die Python-Callbacks; Menüeinträge
     targeten sie per Selektor. Implementiert `menuNeedsUpdate_` für live-
     Sichtbarkeit.
   - Status-Item: `NSStatusBar.systemStatusBar().statusItemWithLength_(…)`,
     Button-Image aus `assets/margenheld-icon.png` (→ NSImage, ~18 px),
     `setMenu_(menu)`.
   - Hält starke Referenzen (Item, Menu, Delegate) auf `self` (sonst GC →
     Icon verschwindet/Crash).
   - `stop()`: `removeStatusItem_` + Referenzen lösen. Idempotent.
   - `notify()`: best-effort `NSUserNotification`, alle Fehler geschluckt.

3. **`requirements.txt` — Dependency mit Plattform-Marker.**
   `pyobjc-framework-Cocoa>=10.0; sys_platform == "darwin"` (Meta-Paket: zieht
   `objc` + `Foundation` + `AppKit`). Marker hält `pip install` auf
   Linux/Windows sauber — Test-CI und Windows-Build sehen pyobjc nie.

4. **`build.py::build_macos` — PyInstaller-Collecting.**
   Da `src/tray_mac.py` AppKit/Foundation **lazy** importiert, übersieht die
   statische Analyse die Module gern. Im macOS-Build explizit collecten (analog
   `--collect-all pystray`), z. B. `--collect-all objc --collect-all AppKit
   --collect-all Foundation` bzw. nötige `--hidden-import`. Exakter Satz beim
   Plan/Umsetzung gegen die aktuelle pyobjc-Version fixieren. Windows/Linux-Build
   unverändert. (`THIRD-PARTY-NOTICES` nehmen pyobjc auf dem Mac-Build über
   pip-licenses automatisch mit.)

5. **`.github/workflows/test.yml` — neuer Job `test-macos`.**
   `macos-latest`, Python 3.10, installiert `pytest` + `pyobjc-framework-Cocoa`
   + die Google-Libs (Tests importieren `src.ui`), läuft `pytest tests/`.
   Bestätigt pyobjc-Import, `src.tray_mac`-Import und Backend-Auswahl auf echtem
   macOS — **nicht** die visuelle Sichtbarkeit/Interaktion des Icons. Separater
   Job, damit der Linux-Pfad nicht an der macOS-Queue hängt.

6. **`tray.py`-Docstrings + ggf. `CLAUDE.md`/`src/CLAUDE.md`.**
   Der Klassen-Docstring beschreibt aktuell das pystray-darwin-Snapshot-Verhalten
   und „Linux hat kein Tray". Anpassen: macOS nutzt jetzt das native Backend mit
   live-Sichtbarkeit. `tray.py` in der Modul-Liste um `tray_mac.py` ergänzen.

## Fehlerbehandlung / Edge Cases

- **Setup-Fehler nativ:** Exception aus `start()` → bestehender
  `_apply_tray_setting`-Fang (Toast + Feature aus). Kein neuer Pfad nötig.
- **Referenz-GC:** Item/Menu/Delegate werden auf dem Backend-Objekt gehalten;
  das Backend hängt an `App._tray`. Solange `App._tray` lebt, leben die Refs.
- **`stop()` Idempotenz:** wie heute mehrfach aufrufbar; `removeStatusItem_` nur
  wenn Item vorhanden.
- **`notify()` vom Worker-Thread:** AppKit-Notify muss auf den Main-Thread —
  das Backend dispatcht defensiv (bzw. no-op bei Fehler). Sync bleibt unberührt.
- **Quit-Pfad:** `App._quit_with_sync_push` ruft `tray.stop()` vor
  `root.destroy()` — Reihenfolge bleibt; nativ entfernt `stop()` nur das
  Status-Item, kein Thread-Join nötig (es gibt keinen Thread mehr).

## Tests

Rot→grün-Naht (auf jeder Plattform lauffähig, sofern nicht anders vermerkt):

1. `is_supported()` → True auf Darwin & Windows, False auf Linux
   (`platform.system()` gemockt). Verhalten festgeschrieben.
2. **Backend-Dispatch:** `_select_backend("Darwin")` → natives Backend,
   `_select_backend("Windows")` → pystray-Backend.
3. **Bug-Guard:** auf macOS startet der Pfad **keinen** `threading.Thread` —
   das native Backend ist thread-los. Encodiert den Fix, Regression-Guard gegen
   Wieder-Einführung des Crashes.
4. **Menü-Modell:** aus Beispiel-`actions` ergibt sich die erwartete Struktur
   (Einträge, Reihenfolge, Separatoren, Sync-Eintrag als „dynamisch" markiert).

Nicht unit-testbar (→ CI-Import + manueller Mac-Test):
- Die nativen AppKit-Aufrufe (NSStatusItem erscheint, Menü öffnet, Klicks lösen
  Callbacks, live-Sichtbarkeit, notify-Toast) und die Crash-Abwesenheit selbst.

## Verifikation / Übergabe

- **CI (jetzt):** `test-macos`-Job bestätigt Build-/Import-/Dispatch-Korrektheit
  auf macOS.
- **Manueller Mac-Test (später, offen):** Tray-Icon sichtbar; Menü öffnet;
  „Anzeigen"/„Beenden"/Quick-Actions funktionieren; **kein Crash** beim „Google
  neu verbinden" und beim Sync-/Kalender-Aktivieren mit aktivem Minimize-to-Tray;
  Sync-Eintrag erscheint/verschwindet mit `sync_enabled`. Bis dieser Test
  gelaufen ist, gilt „funktioniert auf macOS" als **unverifiziert**.

Übergabe (schwerer Loop):
- **VERHALTEN:** macOS-Tray läuft nativ (NSStatusItem, Main-Thread) statt
  pystray-Daemon-Thread; Windows/Linux unverändert.
- **RISIKO:** Bricht es, dann am ehesten beim Mac-Test — entweder Tk-Runloop
  serviced das Status-Item-Menü nicht (unbelegte Annahme, s. u.) oder PyInstaller
  bündelt pyobjc nicht vollständig. Beides degradiert dank Fallback zu „kein
  Tray", nicht zu Crash. Windows trägt null Risiko.
- **TEST:** manuelle Mac-Checkliste oben.

## Offene Annahme (irreduzibles Risiko)

Keine Primärquelle belegt, dass Tks `mainloop` ein an die geteilte NSApp
gehängtes `NSStatusItem`-Menü ausreichend serviced (das Standalone-PyObjC-Muster
treibt seinen eigenen `AppHelper.runEventLoop()`, den wir bewusst **nicht**
nutzen). Die PyObjC-API selbst (systemStatusBar, statusItemWithLength_, setMenu_,
Main-Thread-/Retain-Pflicht, Target/Action) ist primärbelegt. Die Integration
ist nur auf einem Mac final verifizierbar — bei Fehlschlag greift der Fallback,
und der dokumentierte Rückfallweg ist Issue-Option 1 (Tray auf macOS deaktivieren).

## Bewusst nicht enthalten (YAGNI)

- Kein Ersatz von pystray auf Windows (Ansatz B) — nur macOS bekommt das native
  Backend.
- Kein `run_detached`-Weg (Ansatz C / Issue-Option 2) — der NSApp-Konflikt bleibt.
- Kein voller `UNUserNotificationCenter`-Notify mit Authorization/Entitlements —
  notify bleibt best-effort.
- Keine Änderung am Klick-/Lösch-Modell oder an Win/Linux-Verhalten.
- Kein natives Windows-Tray, kein Linux-Tray.
