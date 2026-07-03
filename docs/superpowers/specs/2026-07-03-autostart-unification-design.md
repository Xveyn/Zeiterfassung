# Autostart-Vereinheitlichung + Single-Instance-Guard

**Datum:** 2026-07-03
**Status:** Design freigegeben, bereit für Implementierungsplan
**Plattformen:** Windows / macOS / Linux

## Problem

Bei einem Nutzer starten beim Hochfahren des Rechners **zwei Instanzen** der App
parallel (Autostart + Tray aktiv, Windows). Ursache ist ein Logikfehler: es gibt
zwei voneinander unabhängige Autostart-Mechanismen, die sich gegenseitig nicht
kennen.

1. **Installer** (`installer.iss`): der Setup-Task „Mit Windows starten (minimiert)"
   schreibt einen Registry-Wert
   `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Zeiterfassung` =
   `"<app>\Zeiterfassung.exe" --minimized`.
2. **App-Setting** (`settings_dialog.py` → `autostart.py`): die Checkbox „Autostart
   (minimiert bei Anmeldung)" legt einen Shortcut `Zeiterfassung.lnk` im
   Startup-Ordner an.

Die Checkbox liest `settings.get("autostart")` (Default `False`) und weiß nichts
vom Installer-Registry-Key. Sie zeigt also **aus**, obwohl Autostart längst läuft.
Hakt der Nutzer sie an, entsteht ein **zweiter** Autostart-Eintrag (Shortcut
zusätzlich zur Registry) → beim nächsten Boot feuern beide → zwei Instanzen.

Verschärfend:
- `disable_autostart()` löscht nur den Shortcut, nie den Registry-Key — der
  Installer-Autostart ist aus der App heraus gar nicht abschaltbar.
- Es gibt **keinen Single-Instance-Guard**: beide Instanzen laufen voll durch und
  schreiben auf dieselben JSON-Dateien (Last-write-wins, potenzieller Datenverlust;
  mit aktivem Sync zusätzlich Push-Races). Das Tray macht es unsichtbar-persistent
  (beide hängen minimiert im Infobereich statt als zwei offensichtliche Fenster).

## Ziel

- Auf Windows kann strukturell nur **ein** Autostart-Eintrag existieren.
- Die Autostart-Checkbox zeigt den **echten** Zustand, plattformübergreifend.
- Bestandsnutzer werden beim Update automatisch und **absichtserhaltend** migriert.
- Ein Single-Instance-Guard fängt jeden verbleibenden Doppelstart ab (auch
  manuellen Doppelklick), plattformübergreifend, ohne den Nutzer je am Start zu
  hindern.

Nicht im Scope: Umbau des `settings.json`-Schemas, Änderungen an den
macOS-/Linux-Autostart-Backends (nur die neue Statusabfrage kommt dort dazu).

## Ansatz

Gewählt: **Ansatz A** — der Registry-Run-Key wird die einzige Windows-Quelle; App
und Installer beschreiben denselben Wertnamen. Verworfen: Ansatz B (Shortcut als
einzige Quelle — VBS-Hack bliebe, Migration schiefer) und Ansatz C (App verwaltet
defensiv beide Orte, Installer unangetastet — heilt Bestandsnutzer nur bei
Toggle, Checkbox lügt weiter).

---

## Abschnitt 1 — Autostart-Vereinheitlichung (Windows)

Die App schreibt statt eines Startup-Shortcuts denselben Registry-Wert, den der
Installer nutzt.

- `_enable_windows` / `_disable_windows` in `autostart.py` arbeiten über `winreg`
  (stdlib) auf `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, Wertname
  `Zeiterfassung`, Datenformat **exakt** wie der Installer: `"<target>" --minimized`
  (Exe-Pfad in Anführungszeichen, Space, Argumente).
- Weil App und Installer denselben **Wertnamen** beschreiben, ist es strukturell
  **ein** Eintrag — egal in welcher Reihenfolge Installer-Häkchen und
  App-Checkbox gesetzt werden. Zwei Autostart-Trigger sind unmöglich.
- Der VBS/cscript-Hack (Temp-Skript zum Shortcut-Anlegen) entfällt ersatzlos.
- **macOS/Linux bleiben unverändert** (Plist bzw. `.desktop`).

Der öffentliche Vertrag `enable_autostart(target, arguments)` /
`disable_autostart()` bleibt gleich — nur das Windows-Backend wechselt von
Shortcut zu Registry.

### Registry-Wertformat (Vertrag mit dem Installer)

Der Installer schreibt (`installer.iss`):
```
ValueName: "Zeiterfassung"
ValueData: """{app}\Zeiterfassung.exe"" --minimized"
```
→ tatsächliche Daten: `"C:\...\Zeiterfassung.exe" --minimized`.

Die App baut denselben String: `f'"{target}" {arguments}'` (bzw. nur `f'"{target}"'`
wenn `arguments` leer). In Frozen-Windows ist `target = sys.executable =
{app}\Zeiterfassung.exe` → exakter Match, ein Eintrag.

---

## Abschnitt 2 — Migration der Bestandsnutzer (Windows)

Vier mögliche Zustände beim Update. Blindes Löschen des Shortcuts würde Zustand 2
kaputtmachen, daher **absichtserhaltende** Migration statt bloßem Aufräumen.

| Zustand vor Update      | Registry-Key | Shortcut | gewünscht nach Migration          |
|-------------------------|--------------|----------|-----------------------------------|
| 1 — nur Installer-Häkchen | ✓          | —        | Registry bleibt (autostart an)    |
| 2 — nur App-Checkbox    | —            | ✓        | Registry **schreiben**, Shortcut weg (autostart bleibt an) |
| 3 — beides (der Bug)    | ✓            | ✓        | Shortcut weg, Registry bleibt (single) |
| 4 — nichts              | —            | —        | nichts                            |

Neue Funktion `migrate_legacy_autostart(base_path)` in `autostart.py`, aufgerufen
beim App-Start in `main.py` (Windows-only, in `try/except` — nicht-fatal wie das
übrige Startup-Setup):

```
wenn Legacy-Shortcut existiert:
    wenn Registry-Key fehlt:
        Registry-Key schreiben  (Absicht aus Zustand 2 retten)
    Legacy-Shortcut löschen
```

- **Idempotent über Shortcut-Präsenz**: nach dem ersten Lauf ist der Shortcut weg
  → jeder weitere Start ist ein No-op. Kein „migrated"-Flag nötig.
- **Selbstheilend**: der Registry-Wert wird aus `resolve_autostart_target(base)`
  (= aktuelle Exe) gebaut, nicht aus dem alten Shortcut-Ziel → zeigt garantiert auf
  den aktuellen Installationspfad.
- Der Installer braucht **kein** `[InstallDelete]` — die App räumt beim ersten
  Start selbst auf und erhält dabei die Absicht (was der Installer nicht könnte).

---

## Abschnitt 3 — Checkbox zeigt die Wahrheit

Neue Funktion `is_autostart_enabled()` in `autostart.py`, plattform-dispatched,
liest den **echten** Zustand:
- Windows: Registry-Wert `Zeiterfassung` unter dem Run-Key vorhanden?
- macOS: Plist-Datei vorhanden?
- Linux: `.desktop`-Datei vorhanden?

Im Settings-Dialog (`settings_dialog.py`):
- Die Checkbox wird aus `is_autostart_enabled()` initialisiert statt aus dem
  Setting.
- `old_autostart` in der Save-Logik liest ebenfalls den echten Zustand → „unverändert
  gelassen" ist ein echtes No-op, togglen ruft sauber `enable`/`disable`.
- Weil die Migration (Abschnitt 2) beim Start läuft, ist zum Zeitpunkt des
  Dialog-Öffnens der Shortcut bereits in die Registry überführt → kohärenter
  Zustand.

Das Setting `autostart` bleibt in den DEFAULTS (kein `settings.json`-Umbau) und
wird beim Speichern weiter mitgeschrieben, ist aber **nicht mehr die
Anzeigequelle**. `autostart` ist device-lokal und **nicht** in
`SYNCED_SETTING_KEYS` — bleibt so (Autostart darf nicht zwischen Geräten
synchronisiert werden).

---

## Abschnitt 4 — Single-Instance-Guard

Defense-in-depth: fängt jeden verbleibenden Doppelstart ab (manueller Doppelklick;
Boot-Doppelfeuer bei noch nicht migrierten Bestandsnutzern). Neues **Tk-freies**
Modul `src/single_instance.py`, testbar wie `reminders.py`.

### Primitiv: TCP-Socket auf 127.0.0.1, pro Nutzer fester Port

- Port `P = 20000 + (crc32(base_path) % 20000)`, abgeleitet aus dem
  per-Nutzer-Datenverzeichnis (`get_base_path()`). Zwei Instanzen desselben
  Nutzers → selber Port; verschiedene Windows-Nutzer → verschiedene `LOCALAPPDATA`
  → verschiedene Ports (keine Kollision bei Fast User Switching). Reines
  `socket`/`zlib`-stdlib, **auf allen drei Plattformen identisch** — kein
  `fcntl`/`msvcrt`-Plattformzweig.
- **Atomare Primar-Entscheidung durch den OS-Bind**: nur einer kann `P` binden.
  Das löst genau die Race, die den Bug ausmacht (zwei Autostart-Trigger feuern beim
  Boot quasi gleichzeitig).

### Ablauf in `main.py`, *vor* dem Tk-Aufbau

1. `bind()` auf `P` (mit `SO_REUSEADDR`):
   - **Erfolg → Primärinstanz.** `listen()` + Accept-Thread sofort starten (daemon).
     Normal weiterstarten.
   - **Fehlschlag (Port belegt) → Zweitinstanz.** Verbinden, Nachricht senden, dann
     `sys.exit(0)`:
     - Start **ohne** `--minimized` (manueller Doppelklick) → `SHOW` →
       Primärinstanz holt ihr Fenster nach vorn.
     - Start **mit** `--minimized` (Autostart-Doppelfeuer) → `PING` →
       Primärinstanz tut nichts (keine Fenster-Überraschung beim Boot).
   - **Belegt, aber Gegenstelle antwortet nicht wie erwartet** (fremde Software auf
     dem Port) → warnen, loggen, **normal weiterstarten**. Der Guard blockiert den
     Nutzer nie.

### Fenster-Holen

- Der Accept-Thread ackt **sofort** — auch während die Primärinstanz noch die UI
  baut (gepufferter Callback), damit die Zweitinstanz nicht in einen Timeout läuft
  und fälschlich selbst startet.
- `SHOW` ruft `App._restore_from_tray()` (`ui.py`: deiconify + lift + focus) via
  `_marshal_to_ui` auf den Tk-Thread. Kein neuer Fenster-Code — der vorhandene
  Tray-Restore-Pfad wird wiederverwendet.

### Verdrahtung

- `acquire_single_instance(base)` früh in `main()`: die Zweitinstanz beendet sich,
  bevor Tk gebaut wird (schneller, sauberer Exit).
- Nach dem App-Bau `guard.serve(show_fn)`: ersetzt den Puffer-Callback; ein während
  des Baus eingetroffenes `SHOW` feuert dann nach.
- Der gebundene Socket wird beim App-Quit geschlossen (Port freigeben);
  `SO_REUSEADDR` vermeidet TIME_WAIT-Probleme beim Rebind.

### Protokoll

- Magic-Nachrichten (ASCII, feste Präfixe), z. B. `ZEIT-SHOW`, `ZEIT-PING`;
  Primärinstanz ackt mit `ZEIT-OK`.
- Zweitinstanz sendet best-effort und beendet sich in **jedem** Fall, sobald der
  Bind fehlschlug (der belegte Port ist der Beweis, dass eine Instanz läuft) — außer
  der Occupant identifiziert sich nicht als unsere App (kein `ZEIT-OK`), dann
  degradierter Weiterstart.

---

## Abschnitt 5 — Fehlerbehandlung & Tests

### Fehlerbehandlung (Prinzip: der Nutzer wird nie am Start gehindert)

- Migration (`migrate_legacy_autostart`) und Guard-`acquire` laufen in `main.py` in
  `try/except`, nicht-fatal — wie `setup_logging`. Wirft `winreg` oder der Socket,
  wird geloggt und normal weitergestartet.
- `winreg`-Delete auf fehlenden Wert wird toleriert (analog „disable ohne Shortcut
  ist kein Fehler").
- Guard: belegter Port ohne erwartete Antwort → degradierter Start (unguarded),
  geloggt.

### Tests (Test-zuerst, rot→grün)

**`test_autostart.py`** (Windows-Klasse umbauen, macOS/Linux-Klassen unberührt):
- Registry statt Shortcut: `enable` schreibt Wertname `Zeiterfassung` mit Daten
  `"<target>" --minimized`; `disable` entfernt ihn; `disable` ohne Wert wirft
  nicht. Über gepatchte `winreg`-Fake bzw. Temp-Key.
- Wertformat matcht exakt den Installer-String.
- `is_autostart_enabled()`: True wenn Wert/Datei existiert, sonst False — je
  Plattform (Win Registry / macOS Plist / Linux `.desktop`).
- `migrate_legacy_autostart`: die vier Zustände aus Abschnitt 2 (v. a. Zustand 2 →
  Registry geschrieben; Zustand 3 → Shortcut weg, Registry bleibt; idempotent bei
  erneutem Lauf).

**`test_single_instance.py`** (neu, reine Socket-Logik):
- Port-Ableitung deterministisch je `base_path`; verschiedene Pfade → verschiedene
  Ports.
- Erster `acquire` = primär; zweiter `acquire` mit gleichem `base` = erkennt Primär,
  liefert „secondary".
- `SHOW` triggert den Callback; `PING` triggert ihn **nicht**.
- Belegter Port durch Fremd-Socket (kein gültiges Ack) → `acquire` degradiert,
  blockiert nicht.

### Verifikation vor Abschluss

Voller `pytest`-Lauf grün + `ruff check .` (Evidenz zeigen, nicht „fertig"
behaupten). Windows-Registry- und Guard-Pfade sind auf der Windows-Dev-Maschine
real ausführbar; macOS/Linux-Zweige bleiben unangetastet → hier kein
Pre-Release-Gate nötig (anders als bei plattformspezifischen Änderungen).

---

## Betroffene Dateien

| Datei | Änderung |
|-------|----------|
| `src/autostart.py` | Windows-Backend Shortcut→Registry (`winreg`); neu `is_autostart_enabled()`, `migrate_legacy_autostart()` |
| `src/single_instance.py` | **neu** — Tk-freier Guard (Socket, Port-Ableitung, Protokoll) |
| `src/main.py` | Guard-`acquire` vor Tk-Bau; `migrate_legacy_autostart` beim Start; `guard.serve(show_fn)` nach App-Bau; Socket-Close bei Quit |
| `src/dialogs/settings_dialog.py` | Checkbox init + `old_autostart` aus `is_autostart_enabled()` |
| `tests/test_autostart.py` | Windows-Klasse auf Registry umbauen; Tests für `is_autostart_enabled`, `migrate_legacy_autostart` |
| `tests/test_single_instance.py` | **neu** |
| `src/CLAUDE.md` | Guard-Modul + Autostart-Registry-Vertrag dokumentieren |

`installer.iss` bleibt **unverändert** (Registry-Task schreibt schon den richtigen
Wertnamen; App gleicht sich an, nicht umgekehrt).
