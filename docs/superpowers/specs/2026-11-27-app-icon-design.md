# Rebranding: neues App-Icon und neue Screenshots

## Warum

Die App bekommt ein neues Erscheinungsbild: ein Icon, das zeigt, was
sie tut, und Screenshots, die es zeigen. Das bisherige Icon
(`assets/margenheld-icon.*`, ein Roboter) liegt zudem nur als 300 × 297 px
großes Rasterbild vor; die 512er-Icons der PWA sind daraus hochskaliert und
weich (Xveyn#271).

## Ziele

- Ein neues Motiv: **Kalenderblatt mit Uhr auf einer dunklen, abgerundeten
  Kachel** (Entwurf „B3“ aus der Abstimmung).
- Farblich wie bisher: dunkelblauer Grund (`#0e172b` → `#1b2a4a`, radialer
  Verlauf), Mint (`#04cd9f`, Kalenderkopf), Cyan (`#19ebec`, markierter Tag und
  Uhrrahmen), helles Blatt (`#e6ecef`), Raster `#b6c2cc`.
- **Eine Quelle: `assets/app-icon.svg`.** Alle Formate werden daraus erzeugt
  und sind in jeder Größe scharf.
- Neutrale Dateinamen (`app-icon.*`), im Installer `AppPublisher=Xveyn`.
- **Alle Screenshots im README neu**, mit dem neuen Icon und auf einem Stand.

## Nicht-Ziele

- `com.margenheld.zeiterfassung` (macOS-Bundle-ID, LaunchAgent) und die
  Copyright-Zeile in `LICENSE` bleiben, Begründung in
  `docs/project-handover.md`, Abschnitte 1 und 6.
- Das Icon der Push-Benachrichtigung (Xveyn#357) ist eine eigene Frage.
- Eine vereinfachte Variante für 16 px oder ein monochromes Tray-Icon für die
  macOS-Menüleiste: erst, wenn das echte Tray es zeigt.

## Anti-Ziele

- Ein Aussehen, das vom Renderer abhängt: die SVG nutzt **keine Filter** (der
  Glanz ist eine halbtransparente breitere Linie hinter der Kontur), keine
  Schrift, nur Pfade, Formen und einen Verlauf.
- Eine neue Abhängigkeit für Build, CI oder die App.

## Ansätze

1. **SVG als Quelle, ein Skript erzeugt die Formate** *(gewählt)*. Die
   Ergebnisse werden eingecheckt; nur wer das Icon ändert, braucht den
   Renderer.
2. Icon direkt in Pillow zeichnen: kein Werkzeug nötig, aber das Motiv wäre
   Code und mit keinem Grafikprogramm zu öffnen.
3. SVG einmal von Hand umwandeln: am wenigsten Code, aber jede Änderung sind
   viele Handgriffe, und die Formate laufen auseinander.

Gewählt wurde 1: eine Quelle, ein Skript, keine Kopien. So hält es das Repo
auch sonst.

## Umsetzung

**Skript `scripts/app_icons.py`** (löst `scripts/pwa_icons.py` ab). Es rendert
die SVG mit **`resvg-py`** (fertige Wheels für Windows, macOS und Linux,
keine Systembibliotheken; nur ein Entwicklerwerkzeug, nicht in
`requirements*.txt`, Installationshinweis im Docstring) und schreibt mit
Pillow:

| Datei | Inhalt | Nutzer |
|---|---|---|
| `assets/app-icon.png` | 512 × 512 | Fenster-`iconphoto`, Tray (alle drei), Linux-Menüeintrag |
| `assets/app-icon.ico` | 16, 20, 24, 32, 40, 48, 64, 128, 256 | PyInstaller (Windows), Installer, Verknüpfungen |
| `assets/app-icon.icns` | 32 bis 1024 (Retina-Typen ic07–ic14, kleinster 16@2x) | PyInstaller (macOS) |
| `pwa/icons/icon-192.png`, `icon-512.png` | Kachel auf transparentem Grund | Manifest, Einrichtungs-Screen |
| `pwa/icons/icon-maskable-512.png` | Kachel auf voller Fläche `#0e172b`, Motiv innerhalb der Sicherheitszone (Kreis mit 80 % Durchmesser) | Android |

Jede Größe wird **direkt aus der SVG** gerendert, nicht aus der 512er
herunterskaliert. Die Dateinamen der PWA bleiben, damit Manifest, `sw-core.js`
und `views.js` unverändert bleiben.

**Umbenennen `margenheld-icon.*` → `app-icon.*`** in `src/ui.py`,
`src/theme/chrome.py`, `src/desktop_entry.py`, `src/tray/windows.py`,
`src/tray/mac.py`, `src/tray/linux.py`, `scripts/build.py`, `installer.iss`
und den Tests. Die alten Dateien werden aus dem Repo gelöscht.

**Drei Stellen mit eigener Regel:**

- **AppImage:** Datei und Eintrag heißen `zeiterfassung.png` /
  `Icon=zeiterfassung`, nicht `app-icon`. Werkzeuge wie `appimaged`
  installieren das Icon unter diesem Namen ins Icon-Theme, ein generischer
  Name könnte dort mit anderen Programmen kollidieren.
- **Windows-Installer:** `[InstallDelete]` mit den beiden alten Dateien
  (`{app}\assets\margenheld-icon.ico`/`.png`, ausdrücklich benannt, kein `*`),
  sonst blieben sie nach einem Upgrade liegen. Die Verknüpfungen legt Inno
  beim Upgrade neu an, sie zeigen danach auf `app-icon.ico`.
  `AppPublisher=Margenheld` → `AppPublisher=Xveyn` (passt zu
  `AppPublisherURL`; reine Anzeige in „Apps & Features“, `AppId` hängt am
  `AppName` und bleibt).
- **Linux-Menüeintrag:** nichts zu tun. `desktop_entry.ensure_icon` kopiert
  das gebündelte PNG bei geänderter Dateigröße nach `icon.png` im Datenordner,
  bestehende Installationen bekommen das neue Icon beim nächsten Start.

**Doku:** README (Titelbild in Zeile 2), `CONTRIBUTING.md` (Verzeichnisbaum,
Skript), `CLAUDE.md` (Eintrag zu `scripts/pwa_icons.py`), `pwa/CLAUDE.md`,
Kommentare an den umbenannten Stellen. In `docs/project-handover.md` werden
Abschnitt 6 (Assets) und die `AppPublisher`-Zeile als erledigt vermerkt.
Historische Specs, Pläne und CHANGELOG bleiben, wie sie sind.

**Screenshots: alle 14 neu**, nach dem Icon-Tausch (die App und der
Dev-Server der PWA zeigen dann schon das neue Icon). Ablauf nach
`docs/screenshots/README.md`:

- Neue Namen mit `--VERSION--`-Platzhalter statt der Versionsnummer, die
  alten Bilder werden gelöscht, die Verweise in `README.md` und die Tabelle in
  `docs/screenshots/README.md` umgehängt. `resolve_readme_version.py` löst die
  Namen im Release-PR auf.
- Desktop (Kalender, Tages-Dialog, Senden, drei Einstellungs-Tabs,
  Konflikte) mit `scripts/demo_data.py` in einem eigenen Datenordner
  (`ZEITERFASSUNG_DATA_DIR`), nie mit echten Daten; der PDF-Bericht (zwei
  Bilder) aus denselben Demo-Daten.
- Handy-Ansichten (Woche, Editor, Verbindung, Kategorien, Einrichtung) über
  `scripts/pwa_devserver.py` im Browser mit 390 Pixeln Breite, mit den dort
  beschriebenen Handgriffen (Speicher-Hinweis, Fokusrahmen, Desktop-Name,
  Service Worker).
- Motive und Bildausschnitte bleiben wie bisher; die Alt-Texte werden
  geprüft (beim Einrichtungs-Screen entfällt das „Robotergesicht“).

Der PDF-Bericht und die meisten Handy-Ansichten zeigen kein Icon. Sie werden
trotzdem neu aufgenommen, damit alle Bilder denselben Stand zeigen.

## Tests

- Ein neuer Test prüft die erzeugten Dateien strukturell: Größen im ICO,
  lesbares ICNS mit 1024er, PNG 512 × 512 RGBA, PWA-Größen, maskierbares Icon
  ohne Transparenz in den Ecken.
- Die bestehenden Tests (`test_desktop_entry`, `test_ui_window_icon`,
  `test_tray_linux`) ziehen den neuen Namen nach.

## Prüfen vor dem Merge

Wirkt auf alle drei Plattformen: Labels `platform:windows`, `platform:macos`,
`platform:linux`. Vor dem Merge ein **Pre-Release** über alle drei bauen und
ansehen: Fenster, Taskleiste/Dock, Tray, Installer, Verknüpfungen, AppImage im
Menü. Den Installer allein prüft auch der Workflow **Build** mit gesetztem
`installer`-Häkchen. Die PWA nach dem Pages-Deploy auf dem iPhone
(Homescreen-Icon, Einrichtungs-Screen) ansehen.

Der PR schließt Xveyn#271 und ein eigenes Issue zum Rebranding, das vor dem
PR angelegt wird.

## Dem Umsetzer überlassen

- Die genauen Koordinaten des Motivs in der SVG (Vorlage: Entwurf B3), die
  Größe des Motivs auf der Kachel und der Ersatz für den Glanz ohne Filter.
- Ob der Strukturtest Pillow braucht (dann in `requirements-test.txt`
  ergänzen und in `CLAUDE.md` nachziehen) oder die Köpfe von ICO/PNG mit der
  stdlib liest.
