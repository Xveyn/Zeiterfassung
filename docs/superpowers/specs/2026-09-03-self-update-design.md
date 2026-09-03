# In-App-Update für Windows und Linux — Design

**Datum:** 2026-09-03
**Status:** Design abgestimmt, Implementierungsplan folgt
**Branch:** `feat/self-update`

## Problem

Ein Update kostet den Nutzer heute sechs Schritte: Hinweis lesen, Knopf drücken,
Browser wartet auf den Download, Datei im Download-Ordner suchen, SmartScreen-
bzw. Gatekeeper-Warnung wegklicken, Installer durchklicken. Die App ist nach dem
ersten Klick raus — sie öffnet nur eine URL:

```python
# tab_updates.py:214 und update_banner.py:81, identisch
url = pick_asset_url(release.assets, platform.system(), release.version) or release.html_url
webbrowser.open(url)
```

`src/updater.py` enthält **keinerlei** Download-Code; das Modul liest
ausschließlich JSON von der GitHub-API.

## Ziel

Auf **Windows und Linux** wird aus dem Download-Knopf ein „Update installieren":
ein Klick lädt das Plattform-Asset mit Fortschrittsanzeige, prüft es gegen den
`SHA256SUMS` des Releases, installiert und startet die App neu. Optional
(Default aus) läuft derselbe Ablauf ohne Rückfrage.

**macOS bleibt beim heutigen Browser-Weg** — begründet, dokumentiert, kein
Rückstand (s. „macOS bewusst außen vor").

## Status Quo — was schon da ist

Der Sprung ist kleiner als er klingt; die Entscheidungslogik steht vollständig:

| Baustein | Ort | Rolle beim Selbst-Update |
|---|---|---|
| Versionsvergleich inkl. Pre-Release-Ordnung | `version.parse_release_id`, `updater.is_newer` | „ist das neuer als ich" |
| Plattform-Asset-Auswahl | `updater.pick_asset_url` | welche Datei — **muss erweitert werden**, s.u. |
| Check-Throttle, Pre-Release-Opt-in | `updater`, Settings | wann geprüft wird |
| **`SHA256SUMS` als Release-Asset** | `release.yml:238-250` | Integritätsprüfung, **ohne Release-seitige Änderung** |
| Neustart-Kommando | `paths.relaunch_command` | Vorbild für den Neustart |
| `$APPIMAGE` bekannt | `autostart.py:55`, `main.py:172` | Linux kennt seinen eigenen Pfad |
| Single-Instance-Guard, `AppMutex` | `single_instance.py`, `main.py:50` | Alt-Instanz erkennen |

Es fehlen: Download, Hash-Prüfung, Installationsschritt, Neustart.

## Die bindende Vorgabe: M9

In `update_banner._open_download` steht ein Audit-Vermerk, der genau diese
Arbeit vorwegnimmt:

> **M9 (bewusste Design-Grenze):** Die App verifiziert das Update NICHT per
> Hash/Signatur — sie lädt und startet aber auch nichts selbst […]. Ein
> späterer In-App-Auto-Download **OHNE Verifikation wäre eine echte Lücke** —
> dann hier Signatur-/Hash-Prüfung ergänzen.

Die Hash-Prüfung ist damit **Bedingung, nicht Kür**. Der Vermerk wird beim
Umbau durch die tatsächlich eingelöste Zusicherung ersetzt, nicht gelöscht.

**Was die Prüfung leistet und was nicht** — das gehört so in den Code und in
die Doku: `SHA256SUMS` schützt gegen abgebrochene und verfälschte Übertragung.
Es schützt **nicht** gegen ein kompromittiertes Release, denn die Datei ist
selbst unsigniert und liegt neben den Assets, die sie beschreibt. Der
Vertrauensanker bleibt TLS zu GitHub — derselbe wie heute beim Browser-Download.
Das ist für diesen Zweck angemessen, darf aber nicht als „signiert" auftreten.

## Ein Bug, der vorher weg muss: Architektur

`pick_asset_url` verzweigt über `platform.system()`, aber **nie über die
Architektur** — `platform.machine()` kommt im ganzen `src/` nicht vor. Die
erwarteten Namen sind hart `-arm64.dmg` und `-x86_64.AppImage`; weil das
Release genau diese Assets trägt, **matchen sie immer**:

- Intel-Mac bekommt die arm64-DMG angeboten
- arm64-Linux bekommt die x86_64-AppImage angeboten

Heute ist das ein Fehldownload, den der Nutzer bemerkt. **Mit Selbst-Update
wäre es eine automatische Fehlinstallation** — auf dem Mac über eine
funktionierende Installation drüber.

`pick_asset_url` bekommt deshalb einen `machine`-Parameter und liefert `None`,
wenn die Architektur nicht passt. Der bestehende Fallback auf `release.html_url`
greift dann, der Nutzer landet auf der Release-Seite. Das ist eine
eigenständige Korrektur und geht als **erster** Schritt in die Umsetzung —
sie ist auch ohne den Rest richtig.

## Architektur

### `src/self_update.py` (neu, Tk-frei)

Alles Entscheidbare als pure Funktionen, testbar ohne Netzwerk und ohne Tk —
die Zuschnitt-Regel aus CLAUDE.md („Getestet wird Logik, nicht UI"):

- `parse_sha256sums(text) -> dict[str, str]` — Dateiname → Hex-Digest. Format
  ist `<hash>  <name>` (zwei Leerzeichen, coreutils).
- `verify_file(path, expected_hex) -> bool` — streamend, blockweise; eine
  65-MB-AppImage wird nicht in den Speicher gelesen.
- `supports_self_update(system, machine, frozen) -> bool` — Windows und Linux
  im Frozen-Build. Repo-Modus ist ausgeschlossen: dort gibt es keine
  installierte Datei, die man ersetzen könnte.
- `plan_update(...) -> UpdatePlan | UpdateBlocked` — die eine Stelle, die
  entscheidet, ob es losgehen kann, und bei „nein" **einen Grund nennt**
  (falsche Plattform, keine passende Architektur, `$APPIMAGE` fehlt, Ziel
  nicht schreibbar, zu wenig Plattenplatz, kein `SHA256SUMS` im Release).
- `windows_helper_script(pid, setup_path, exe_path) -> str` und
  `linux_apply_paths(appimage_path) -> tuple[str, str, str]` — die
  Kommando-/Pfadkonstruktion je Plattform, als reine Textfunktionen. Sie sind
  der Teil, den man testen kann, ohne etwas zu installieren.

Der **Download** selbst (`urllib`, mit Fortschritts-Callback und Abbruch)
liegt ebenfalls hier, läuft aber über `BackgroundTaskRunner` — nie im
UI-Thread, wie jeder andere Netzwerkpfad der App.

### Windows: Helfer-Skript

Der Zwang ist hart und in **jeder** denkbaren Variante derselbe: `installer.iss`
setzt `AppMutex=ZeiterfassungAppMutex` und schaltet mit `CloseApplications=no`
Innos eigenen Weg ab, die App zu schließen (weil der Restart Manager am
Minimize-to-Tray scheitert). Läuft die App noch, wenn Inno seinen Mutex-Check
macht, bricht der Silent-Installer ab bzw. zeigt einen Retry-Dialog. Ein
„Installer starten und selbst beenden" ist ein Rennen, auf das sich nichts
verlassen darf.

Zweitens startet der Installer die App danach **nicht**: der `[Run]`-Eintrag
trägt `skipifsilent`.

Beides erledigt ein kleines Helfer-Skript, das die App nach `%TEMP%` schreibt
und abgekoppelt startet (`CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`),
bevor sie sich beendet — **nicht** `DETACHED_PROCESS`, s. Nachtrag am Ende
dieses Abschnitts:

1. auf das Verschwinden der übergebenen PID warten (`tasklist /FI "PID eq …"`,
   mit Zeitlimit)
2. `Zeiterfassung_Setup.exe /SILENT /NORESTART`
3. `Zeiterfassung.exe` starten

**`installer.iss` bleibt unangetastet.** Das ist der Hauptgrund für diese
Variante: die Datei ist die am schwersten zu prüfende im Repo (lokal fehlt
Inno, sie ist nur über `build.yml` mit `installer`-Häkchen testbar), und die
Alternative — `skipifsilent` entfernen — löste nur die zweite Hälfte des
Problems und änderte das Verhalten für *jeden* `/SILENT`-Aufruf.

Bewusst **ohne** `/VERYSILENT` und **ohne** `/SUPPRESSMSGBOXES`: das
Fortschrittsfenster ist das einzige Signal, dass gerade etwas passiert, und
echte Fehler sollen sichtbar bleiben. (`/SUPPRESSMSGBOXES` ist auch der
Schalter, der „Abort" zur Standardantwort in Abort/Retry-Situationen macht —
genau das will man hier nicht.) `/SMS` wird **nicht** verwendet: der Schalter
steht nicht mehr in der offiziellen Inno-Dokumentation.

**Nutzerdaten sind unkritisch.** Sie liegen unter Windows neben der Exe
(`get_base_path()` = `dirname(sys.executable)`), aber `[Files]` kopiert mit
`ignoreversion recursesubdirs` darüber und löscht nichts — genau wie bei jedem
heutigen Update.

**Nachtrag (2026-09-04):** Diese ursprüngliche Fassung des Abschnitts nannte
`DETACHED_PROCESS | CREATE_NO_WINDOW` als Prozess-Flags für das Helfer-Skript
(s. History dieser Datei). Das erwies sich bei der Umsetzung als Fehler und
wurde erst über mehrere Runden gefunden und behoben: `DETACHED_PROCESS` entzieht dem Prozess seine
Konsole — ohne Konsole liefert `tasklist /FI "PID eq …"` **keine** Ausgabe
mehr, die Warteschleife auf das Ende der App-PID läuft dadurch blind über
deren Prozessende hinweg und springt sofort zum Installer-Aufruf, während der
`AppMutex` noch gehalten wird. Der Installer bricht dann gegen die
scheinbar noch laufende App ab bzw. zeigt den Retry-Dialog — exakt das
Problem, das der Helfer verhindern sollte. Die tatsächlich verwendeten,
korrekten Flags sind `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`
(`src/self_update.py::apply_windows`, mit demselben `tasklist`-Argument
kommentiert) — sie entkoppeln den Helfer ebenso, ohne ihm die Konsole zu
nehmen. Der Abschnitt oben ist entsprechend korrigiert; dieser Nachtrag bleibt
stehen, damit die Historie nachvollziehbar bleibt.

### Linux: Datei ersetzen

1. Neue AppImage nach `<zielverzeichnis>/.zeiterfassung-update-<pid>.tmp` laden
2. Hash prüfen
3. `chmod +x`
4. laufende Datei nach `<name>.old` umbenennen
5. `os.replace(tmp, $APPIMAGE)`
6. `os.execv` auf den neuen Pfad

Die laufende AppImage im Betrieb zu ersetzen ist **der vorgesehene Weg** — genau
so arbeitet AppImageUpdate; der Inode der gemounteten Datei bleibt bis zum
Prozessende gültig. Die `.old`-Datei ist der Rollback und wird beim nächsten
erfolgreichen Start entfernt (`main.py`, analog zum bestehenden
Tombstone-Sweep). Dieselbe Idee wie AppImages `.zs-old`.

**Zwei Abbruchgründe vor dem ersten Byte**, beide aus `plan_update`:
`$APPIMAGE` ist nicht gesetzt (die nackte PyInstaller-Ausgabe hat es nicht —
steht schon so in `autostart.py:241`), oder das Verzeichnis ist nicht
beschreibbar.

## macOS bewusst außen vor

Kein Selbst-Update, der Knopf bleibt „Download" und öffnet den Browser wie
heute. Gründe, in dieser Reihenfolge:

1. **Das Bundle ist weder signiert noch notarisiert** — `scripts/build.py`
   enthält kein `codesign`. Ein Selbst-Update müsste das DMG mounten, nach
   `/Applications` schreiben und dabei mit Gatekeeper umgehen.
2. **Nicht verifizierbar auf der Entwicklungsmaschine** (Windows). Die
   CLAUDE.md-Regel „Plattformspezifische PRs — Pre-Release vorschlagen" gilt,
   aber ein Selbst-Updater ist die Fehlerklasse, die man **nicht** per Update
   repariert — Pre-Release-Testen allein trägt hier nicht weit genug.
3. Nur arm64: CI baut kein Intel-Artefakt.

**Bemerkenswert und festzuhalten:** ausgerechnet macOS hätte den größten
Gewinn. Heute setzt der Browser beim Download `com.apple.quarantine`, Gatekeeper
blockt die unsignierte App, der Nutzer muss Rechtsklick → Öffnen. Ein Download
per `urllib` setzt dieses Attribut **nicht** — LaunchServices tut das, nicht der
Socket. Ein Selbst-Update auf dem Mac würde die Gatekeeper-Hürde also ganz
umgehen. Das ist der stärkste Grund, es später nachzuziehen, und gehört als
solcher ins Ticket.

Festgehalten wird das in `docs/known-limitations.md` und in der README.

## UI

**Updates-Tab.** Der Knopf heißt „Update installieren", wo `supports_self_update`
wahr ist, sonst unverändert „Download". Der Fortschritt läuft über das
vorhandene Status-Label (`Lade … 58 %` → `Prüfe Prüfsumme …` → `Installiere …`),
keine neue Widget-Zeile. Während des Downloads ist „Jetzt prüfen" deaktiviert,
wie schon während eines Checks.

**Banner.** Derselbe Knopf-Wechsel, gleicher Ablauf.

**Neue Einstellung „Updates automatisch installieren"** (Default **aus**) im
Updates-Tab, unter dem Pre-Release-Häkchen und im selben Stil, mit einer
gedämpften Hinweiszeile darunter. Sie ist **gerätelokal** und kommt
**nicht** in `SYNCED_SETTING_KEYS`: ein Wert, den sich ein Mac und ein
Windows-Rechner teilen, wäre auf dem Mac systematisch falsch — er kann den
Schalter gar nicht einlösen, weil er nicht selbst updaten kann.

Der Schalter wird nur gebaut, wo Selbst-Update möglich ist — ein Schalter für
ein Feature, das die Plattform nicht hat, ist Rauschen (dieselbe Regel wie beim
„Urlaub ausweisen"-Häkchen, das ohne Urlaub nicht erscheint).

### Wann die Automatik auslöst

Der Schalter benutzt **dieselbe Maschine** wie der Knopf und unterscheidet sich
nur im Auslöser. Drei Regeln, damit „automatisch" nicht „überraschend" heißt:

1. **Ausgelöst wird vom vorhandenen Update-Check**, nicht von einem neuen
   Timer. Meldet `check_for_update` eine neuere Version und der Schalter ist an,
   startet der Download im Hintergrund — dieselbe Häufigkeit wie bisher
   (`update_check_frequency`, Default täglich).
2. **Installiert wird nie mitten in der Arbeit.** Nach erfolgreichem Download
   und geprüftem Hash wird **nicht** sofort neu gestartet. Die App merkt sich
   die verifizierte Datei und wendet sie beim **nächsten regulären Beenden** an
   — dort, wo die App ohnehin zumacht. Der Nutzer verliert nie einen
   angefangenen Eintrag, und der Neustart nach dem Update entfällt: die App war
   ja im Begriff zu enden.
3. **Sichtbar bleibt es trotzdem.** Der Banner wechselt von „Update
   installieren" zu „Update bereit — wird beim Beenden installiert", damit
   niemand von einer neuen Version überrascht wird. Wer nicht warten will,
   klickt weiterhin den Knopf und bekommt den Sofort-Ablauf.

Die verifizierte Datei liegt bis dahin im Temp-Verzeichnis. Wird sie zwischen
Download und Beenden gelöscht (Aufräum-Tools), fällt der Vorgang still aus und
der nächste Check beginnt von vorn — geprüft wird deshalb **unmittelbar vor**
dem Anwenden noch einmal, ob die Datei existiert und ihr Hash stimmt.

## Fehlerverhalten

Leitsatz: **jeder Fehlschlag lässt die bestehende Installation unberührt** und
endet mit einer Meldung, die sagt, was man stattdessen tun kann.

| Fehler | Verhalten |
|---|---|
| Kein Netz / Abbruch beim Download | Temp-Datei löschen, Meldung, Knopf wieder aktiv |
| Hash stimmt nicht | Datei **löschen**, deutliche Meldung, Angebot „im Browser öffnen" |
| `SHA256SUMS` fehlt im Release | Gar nicht erst starten — Fallback auf den Browser-Weg |
| Plattform/Architektur passt nicht | Knopf bleibt „Download" (aus `plan_update`) |
| Ziel nicht schreibbar / zu wenig Platz | Vor dem Download erkannt, Meldung mit Grund |
| Installer scheitert (Windows) | Der Helfer startet die App in jedem Fall wieder — auch bei Exit-Code ≠ 0. Was Inno bis dahin kopiert hat, bleibt kopiert (ein Rollback über Dateigrenzen hinweg garantiert es **nicht**); der Helfer schreibt seinen Exit-Code deshalb in eine Log-Datei neben der App, damit ein gescheiterter Lauf nachvollziehbar ist |
| Windows: App startet nach dem Update nicht mehr | **Nicht automatisch heilbar** — die Grenze wird benannt, nicht überspielt. Genau deshalb ist die Automatik Opt-in und der Windows-Weg vor dem Merge lokal durchgestochen |
| Linux: `os.replace` scheitert | `.old` zurückbenennen, Meldung |

Meldungen folgen der bestehenden Zweiteilung: kuratierte Fälle → `themed_*`,
Catch-all mit Traceback → natives `messagebox.showerror`. Und der Catch-all
selbst folgt der Regel aus `tests/test_catch_all_handlers.py`: loggen, melden
oder begründen.

## Tests

Pure Logik in `tests/test_self_update.py`:

- `parse_sha256sums`: normales coreutils-Format, Leerzeilen, fehlende Datei,
  kaputte Zeile, CRLF
- `verify_file`: Treffer, Abweichung, leere Datei
- `supports_self_update`: Windows/Linux frozen → wahr; macOS → falsch;
  Repo-Modus → falsch
- `plan_update`: jeder Blockierungsgrund einzeln, mit Begründungstext
- `windows_helper_script`: enthält PID, Setup-Pfad und Exe-Pfad; keine
  unquotierten Pfade mit Leerzeichen (`D:\Programme (x86)\…` ist der Normalfall
  auf dieser Maschine!)
- `linux_apply_paths`: `.old`-Name, Temp-Name, Kollisionsfreiheit

Erweitert wird `tests/test_updater.py` um die Architektur-Fälle von
`pick_asset_url` (Intel-Mac bekommt `None`, arm64-Linux bekommt `None`,
passende Kombinationen unverändert).

**Nicht** getestet: der tatsächliche Installationsvorgang. Das ist die
dokumentierte M16-Grenze, und die Gegenmaßnahme ist derselbe Zuschnitt —
alles Entscheidbare liegt in den puren Funktionen.

## Verifikation vor dem Merge

1. **Windows-Durchstich lokal.** Setup.exe aus dem Workflow **Build** mit
   gesetztem `installer`-Häkchen ziehen (Inno fehlt auf der Maschine). Die
   echte Installation unter `%LOCALAPPDATA%\Programs\Zeiterfassung\` **vorher
   sichern** — dort liegen `credentials.json`, `conflicts.json`,
   `backup_jsons` und die Zeiteinträge.
2. **Linux** über einen Pre-Release, wie CLAUDE.md es für plattformspezifische
   Änderungen vorschreibt.
3. Beide Wege einmal mit **absichtlich falschem Hash** (Testdatei) — die
   Verifikation muss greifen und darf nichts installieren.

## Dokumentation

- `CLAUDE.md`: neuer Abschnitt zum Update-Weg — die drei Plattformen, warum
  macOS fehlt, warum `installer.iss` unangetastet bleibt, was die
  Hash-Prüfung leistet und was nicht.
- `README.md`, Abschnitt **„Plattform-Kompatibilität"**: eine neue Zeile in der
  vorhandenen Feature-Matrix `| Feature | Windows | macOS | Linux |`. Das ist
  der Ort, an dem ein Leser ohnehin nachsieht, was seine Plattform kann — und
  die Tabelle beantwortet die Frage in einer Zeile statt in einem Absatz:

  | Feature | Windows | macOS | Linux |
  |---|---|---|---|
  | Update aus der App | ✓ (lädt, prüft, installiert, startet neu) | — (Download im Browser) | ✓ (lädt, prüft, ersetzt die AppImage) |

  Das `—` folgt der Konvention der Tabelle: es steht dort nie allein, sondern
  immer mit dem Grund bzw. dem Ersatz in Klammern („— (nicht nötig)"). Hier
  also das, was stattdessen passiert. Kein `○` — das ist in der Legende für
  „implementiert, aber dormant" reserviert, und für macOS ist nichts
  implementiert. Marker `*(ab 1.23.0)*` an der Feature-Zeile in „Features".
- `docs/known-limitations.md`: die **Begründung** für die macOS-Lücke, die in
  eine Tabellenzeile nicht passt — unsigniertes Bundle, nicht auf der
  Dev-Maschine verifizierbar, und der Gatekeeper-Gewinn als Grund, es später
  nachzuziehen. Dieselbe Arbeitsteilung wie beim Tray: knappe Zeile in der
  Matrix, ausführliche Begründung daneben.
- Der M9-Vermerk in `update_banner.py` wird durch die eingelöste Zusicherung
  ersetzt.

## Bewusst nicht dabei (YAGNI)

- **Delta-/zsync-Updates.** Die AppImage ist 65 MB, ein Delta spart Bandbreite,
  kostet aber ein zusätzliches Release-Artefakt und ein Werkzeug auf dem
  Zielsystem.
- **Signierte Releases.** Wäre die ehrliche Lösung für „kompromittiertes
  Release", verlangt aber Schlüsselverwaltung und ändert den Release-Prozess.
  Eigenes Thema; die Grenze wird stattdessen benannt.
- **Rücksprung auf eine ältere Version.** Der Linux-`.old`-Stand ist ein
  Rollback für den Fehlerfall, kein Feature zum Versionswechsel.
- **macOS.** Siehe oben.

## Quellen

- [Inno Setup: Setup-Kommandozeilenparameter](https://jrsoftware.org/ishelp/topic_setupcmdline.htm)
  — `/SILENT`, `/NORESTART`, `/SUPPRESSMSGBOXES`; `/SMS` ist dort **nicht**
  mehr dokumentiert
- [Inno Setup: `AppMutex`](https://jrsoftware.org/ishelp/topic_setup_appmutex.htm)
  — verhindert Installation bei laufender Anwendung
- [AppImage: Making AppImages updateable](https://docs.appimage.org/packaging-guide/optional/updates.html)
  und [Self updating AppImages](https://github.com/AppImageCommunity/AppImageUpdate/wiki/Self-updating-AppImages)
  — `$APPIMAGE` als Pfadquelle, Ersetzen der laufenden Datei, `.zs-old` als
  Sicherung
