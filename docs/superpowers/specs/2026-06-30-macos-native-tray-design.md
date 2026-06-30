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

Das Minimize-to-Tray soll auf macOS **erhalten** werden (volle Plattform-
Parität), ohne den Crash. Dazu wird auf macOS kein pystray-Daemon-Thread mehr
gestartet, sondern ein natives `NSStatusItem` **synchron auf dem Main-Thread** an
die von Tk getriebene `NSApplication` gehängt (keine zweite NSApp, kein zweiter
Thread, kein zweiter Runloop). Damit ist die Zwei-Threads-eine-NSApp-Kollision
per Konstruktion ausgeschlossen.

**Gestaged, weil ohne Mac nicht verifizierbar:** Das native Backend landet
vollständig, wird aber in ausgelieferten Builds **dormant** gehalten (macOS-Tray
default **aus** = interim Issue-Option 1, Crash sofort weg) und erst nach
bestandenem manuellem Mac-Gate per Flip default-an. Siehe „Auslieferungs-Default
& Rollout". So sagt der Merge ehrlich „Crash behoben", ohne einen unverifizierten
nativen Pfad an alle Mac-Nutzer auszuliefern.

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

### Fallback & Crash-Garantie (präzise gefasst)

Der Python-Fallback deckt **nur synchron** geworfene Exceptions: wirft das native
Setup (`statusItemWithLength_`, `setMenu_`, Image-Load …) synchron an der
PyObjC-Bridge, propagiert das wie heute aus `start()` → `_apply_tray_setting`
fängt es, zeigt `themed_showerror` und schaltet `minimize_to_tray` ab. Kein
Crash, schlimmstenfalls kein Tray.

**Was der Fallback NICHT deckt:** Eine Exception, die *innerhalb* von AppKits
Event-Processing entsteht (Menü-Tracking, Lazy-Draw, Target/Action-Dispatch,
Notify), läuft nicht durch einen Python-Frame → `-[NSApplication
_crashOnException:]` → SIGTRAP, am `try/except` vorbei. Diese async-Crash-Fläche
zerfällt in zwei Klassen:

- **(i) Python-Exceptions in unseren Callbacks** (Action-Methoden,
  `menuNeedsUpdate_`, Notify): **konstruktiv ausgeschlossen** — verbindliche
  Implementierungsregel: *jeder* von AppKit aufgerufene Python-Callback umschließt
  seinen gesamten Body mit einem restlosen `try/except` (swallow + log). Kein
  Python-Throw darf je in einen ObjC-Frame zurück.
- **(ii) AppKit-interne Exceptions** (Threading-/Runloop-Missbrauch): aus Python
  **nicht** abfangbar (AppKit ist nicht exception-safe; einmal entrollt =
  undefinierter Zustand). Nur auf einem Mac verifizierbar.

**Garantie also präzise:** Klasse (i) ist by construction crash-frei; Klasse (ii)
bleibt **unbewiesen bis zum Mac-Gate** — deshalb der dormant-Default (s.
„Auslieferungs-Default & Rollout"). Kein unconditional „nie Crash".

## Betroffene Stellen

1. **`src/tray.py` — Fassade + Backend-Dispatch.**
   - `is_supported()`: **Windows → True**, **Linux → False** (unverändert),
     **macOS → False, solange der Opt-in-Schalter nicht gesetzt ist** (interim
     dormant-Default, s. Rollout). Opt-in z. B. über Env-Var `ZEIT_MACOS_TRAY=1`
     (oder verstecktes Setting), damit der Mac-Tester das native Backend
     aktivieren kann, ohne es default an alle auszuliefern. Der spätere Flip nach
     bestandenem Mac-Gate macht macOS unconditional True.
   - Reine Selektor-Funktion (z. B. `_select_backend(system)`), die das
     Backend nach `platform.system()` wählt — als pure Funktion testbar. Wird
     **unabhängig** von `is_supported()` getestet, damit der native Dispatch auch
     bei dormantem Default in der CI exerciert wird.
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
   - **Callback-Hülle:** jeder von AppKit aufgerufene Python-Callback (Action,
     `menuNeedsUpdate_`, Notify) umschließt seinen Body restlos mit `try/except`
     (swallow + log) — Klasse-(i)-Schutz, siehe „Fallback & Crash-Garantie".

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
   + die Google-Libs (Tests importieren `src.ui`), läuft `pytest tests/`. Geht
   über Import/Dispatch hinaus: ein **In-Process-Smoke** (s. Tests) konstruiert
   das native Backend unter einer laufenden Tk-Root, ruft jeden Action-Callback
   direkt auf, toggelt die Sichtbarkeit und baut wieder ab — fängt
   Verdrahtungs-/Lifecycle-/Target-Action-Fehler und Klasse-(i)-Exceptions.
   **Nicht** beweisbar: user-sichtbares Icon, echtes Menü-Öffnen per Klick und
   Klasse-(ii)-Absenz (→ Mac-Gate). Separater Job, damit der Linux-Pfad nicht an
   der macOS-Queue hängt.

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

1. **`is_supported()`** (`platform.system()` + Opt-in-Schalter gemockt):
   Windows → True; Linux → False; macOS **ohne** Opt-in → False (dormant-Default),
   macOS **mit** Opt-in → True. Schreibt den Staging-Default fest.
2. **Backend-Dispatch:** `_select_backend("Darwin")` → natives Backend,
   `_select_backend("Windows")` → pystray-Backend. Unabhängig von `is_supported()`.
3. **Bug-Guard:** auf macOS startet der Pfad **keinen** `threading.Thread` —
   das native Backend ist thread-los. Encodiert den Fix; muss gegen den alten
   Code (Daemon-Thread) **rot** sein, gegen den neuen grün.
4. **Menü-Modell:** aus Beispiel-`actions` ergibt sich die erwartete Struktur
   (Einträge, Reihenfolge, Separatoren, Sync-Eintrag als „dynamisch" markiert).
5. **In-Process-Smoke (nur macOS, im `test-macos`-Job):** unter einer Tk-Root das
   native Backend konstruieren, jeden Action-Callback direkt aufrufen,
   Sichtbarkeit togglen, `stop()` — assertet **keine** Exception. Exerciert
   Target/Action-Verdrahtung, Retain/Lifecycle und Klasse-(i)-Schutz. Skippt
   sauber, falls der Runner keinen Status-Bar-Zugriff hat (statt falsch rot).

Nicht (auch nicht im macOS-Job) automatisiert testbar — nur **manuelles Mac-Gate**:
- User-sichtbares Icon, Menü-Öffnen per echtem Klick, live-Sichtbarkeit visuell,
  notify-Toast, und vor allem **Klasse-(ii)-Crash-Absenz** beim Google-Reconnect /
  Sync-Aktivieren mit aktivem Tray.

## Auslieferungs-Default & Rollout (Staging)

Weil das Mac-Gate jetzt nicht fahrbar ist und Klasse-(ii)-Crashes nicht aus
Python abfangbar sind, wird das native Backend **dormant** ausgeliefert:

1. **Merge-Zustand (jetzt):** macOS-Tray **aus** by default (`is_supported()` →
   False auf macOS ohne Opt-in). Effektiv interim Issue-Option 1 → der Crash ist
   ab Merge weg. Bestehende Mac-Nutzer mit `minimize_to_tray=True` bekommen beim
   nächsten Start die vorhandene „auf dieser Plattform nicht nutzbar"-Meldung und
   das Feature wird abgeschaltet (kein Crash).
2. **Verifikations-Zustand:** Der Mac-Tester setzt den Opt-in-Schalter
   (`ZEIT_MACOS_TRAY=1`), baut/startet die Branch und fährt das Mac-Gate (s.
   Verifikation). Das native Backend wird so exerciert, ohne es an Endnutzer
   auszuliefern.
3. **Flip (nach bestandenem Gate):** Ein separater, kleiner PR macht macOS in
   `is_supported()` unconditional True (Default an). **Required Release-Gate:**
   dieser Flip darf erst mergen, wenn das manuelle Mac-Gate dokumentiert grün ist.

Damit liefert dieser Branch **Issue-Option 1 als sofortigen, sicheren Default**
**und** das native Backend (Option 3) **fertig, aber gestaged** — die Crash-
Behebung hängt nicht an einer unverifizierten Annahme.

## Verifikation / Übergabe

- **CI (jetzt):** `test-macos`-Job — Import, Dispatch und In-Process-Smoke (s.
  Tests). Bestätigt Verdrahtung/Lifecycle/Klasse-(i), **nicht** Sichtbarkeit oder
  Klasse-(ii)-Crash-Absenz.
- **Manuelles Mac-Gate (REQUIRED, blockiert den Default-an-Flip):** Mit Opt-in
  (`ZEIT_MACOS_TRAY=1`) auf einem Mac: Tray-Icon sichtbar; Menü öffnet per Klick;
  „Anzeigen"/„Beenden"/Quick-Actions funktionieren; Sync-Eintrag erscheint/
  verschwindet live mit `sync_enabled`; notify-Toast (falls Backend ihn zeigt);
  und **kein Crash** beim „Google neu verbinden" sowie beim Sync-/Kalender-
  Aktivieren mit aktivem Tray. Der `is_supported()`-Flip auf macOS-default-an darf
  **erst mergen**, wenn dieses Gate dokumentiert grün ist. Bis dahin gilt
  „funktioniert auf macOS" als **unverifiziert** — und wird default nicht
  ausgeliefert.

Übergabe (schwerer Loop):
- **VERHALTEN:** Merge liefert macOS-Tray **default aus** (Crash weg, interim
  Issue-Option 1) + das native NSStatusItem-Backend **dormant/opt-in**.
  Windows/Linux unverändert. Default-an erst per separatem Flip nach Mac-Gate.
- **RISIKO:** Der Default-Pfad (Tray aus) trägt **kein** Crash-Risiko. Im Opt-in/
  Flip-Pfad bricht es am ehesten bei (ii) — Tk-Runloop serviced das Menü nicht /
  AppKit-interne Exception — oder PyInstaller bündelt pyobjc unvollständig. (i)
  ist konstruktiv abgefangen; (ii) ist genau das, was das Mac-Gate prüft. Windows
  trägt null Risiko.
- **TEST:** In-Process-Smoke (CI) + manuelles Mac-Gate (oben) vor dem Flip.

## Offene Annahme (irreduzibles Risiko)

Keine Primärquelle belegt, dass Tks `mainloop` ein an die geteilte NSApp
gehängtes `NSStatusItem`-Menü ausreichend serviced (das Standalone-PyObjC-Muster
treibt seinen eigenen `AppHelper.runEventLoop()`, den wir bewusst **nicht**
nutzen). Die PyObjC-API selbst (systemStatusBar, statusItemWithLength_, setMenu_,
Main-Thread-/Retain-Pflicht, Target/Action) ist primärbelegt. Die Integration
ist nur auf einem Mac final verifizierbar.

**Wichtig:** Schlägt diese Annahme fehl, ist das **kein** ausgelieferter Crash —
der dormant-Default (Tray aus) hält den unverifizierten Pfad von Endnutzern fern,
bis das Mac-Gate ihn freigibt. Bestätigt sich die Annahme nicht, bleibt der
dokumentierte Endzustand Issue-Option 1 (macOS-Tray aus), und der Flip entfällt.

## Bewusst nicht enthalten (YAGNI)

- Kein Ersatz von pystray auf Windows (Ansatz B) — nur macOS bekommt das native
  Backend.
- Kein `run_detached`-Weg (Ansatz C / Issue-Option 2) — der NSApp-Konflikt bleibt.
- Kein voller `UNUserNotificationCenter`-Notify mit Authorization/Entitlements —
  notify bleibt best-effort.
- Keine Änderung am Klick-/Lösch-Modell oder an Win/Linux-Verhalten.
- Kein natives Windows-Tray, kein Linux-Tray.
