# Zeiterfassung

Desktop-App zur Erfassung von Arbeitszeiten mit Kalenderansicht, PDF-Report und automatischem Gmail-Versand.

[![Release](https://img.shields.io/github/v/release/margenheld/Zeiterfassung?label=Release&color=success&logo=github)](https://github.com/margenheld/Zeiterfassung/releases/latest) ![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

## Features

- **Kalenderansicht** — Monatsübersicht mit Tageseinträgen (Start, Ende, Pause)
- **PDF-Report** — Automatische Generierung als druckfreundliches PDF
- **E-Mail-Versand** — HTML-E-Mail mit PDF-Anhang über Gmail API (OAuth2)
- **Multi-Device-Sync** — Optionale Synchronisation von Zeiteinträgen und Mail-Vorlagen über Google Drive (`appDataFolder`), inklusive manueller Konflikt-Auflösung wenn dasselbe Datum offline auf mehreren Geräten bearbeitet wurde
- **Teilen & Importieren** — Eigene Arbeitszeiten als JSON-Anhang per Mail an eine zweite Person teilen; der Empfänger importiert sie mit Zeitraum-Filter und drei Konflikt-Modi (alles importieren / alles lokal / pro Tag entscheiden)
- **Reservierungen & Google-Kalender** — Zukünftige Arbeitszeiten pro Tag reservieren (eigenes Konzept neben den Ist-Zeiten, im Kalender als violetter Eck-Punkt markiert); optionaler Abgleich mit einem wählbaren Google Kalender
- **Zeitraumwahl** — Flexibler Datumsbereich für Reports
- **Einstellungen** — E-Mail-Vorlagen mit Platzhaltern, Standardpause, Empfänger
- **Autostart** — Optionaler minimierter Start bei Anmeldung (Windows, macOS, Linux)
- **Update-Check** — Prüft beim Start einmal pro Tag auf neuere Releases und zeigt einen unaufdringlichen Banner mit Direkt-Download
- **Dark Mode UI** — Modernes dunkles Design
- **Cross-Platform-Installer** — Per PyInstaller gebaut, als Setup-Exe (Windows), DMG (macOS) und AppImage (Linux) paketierbar

## Projektstruktur

```
Zeiterfassung/
├── src/
│   ├── main.py            # Einstiegspunkt
│   ├── ui.py              # Tkinter-GUI (Kalender, Header, Banner-Updater)
│   ├── dialogs/           # Modal-Dialoge (entry, send, settings, share, import, conflicts)
│   ├── storage.py         # JSON-Persistenz der Zeiteinträge
│   ├── settings.py        # Einstellungen mit Standardwerten
│   ├── report.py          # HTML- & PDF-Reportgenerierung
│   ├── mail.py            # Gmail OAuth2-Authentifizierung & Versand
│   ├── drive.py           # Google Drive API-Wrapper (Multi-Device-Sync)
│   ├── sync.py            # Sync-Engine (pure Logik, LWW-Merge, Konflikterkennung)
│   ├── conflicts_store.py # Lokale Persistenz der Konfliktliste
│   ├── share.py           # Export/Import von Arbeitszeiten als Share-JSON
│   ├── reservations.py    # Reservierungen (zukünftige Soll-Zeiten)
│   ├── reservations_sync.py # Abgleich der Reservierungen mit Google Kalender
│   ├── gcal.py            # Google-Calendar-API-Wrapper
│   ├── tray.py            # Infobereich-Icon (Minimize-to-Tray)
│   ├── autostart.py       # Plattformabhängiger Autostart (Windows/macOS/Linux)
│   ├── updater.py         # GitHub-Releases-Check (stdlib-only, gedrosselt 1×/Tag)
│   ├── holidays_de.py     # Feiertags-Lookup (python-holidays)
│   ├── time_utils.py      # Zeitberechnung und Validierung
│   ├── logging_setup.py   # File-Logging + globaler Excepthook
│   ├── platform_open.py   # os.startfile/open/xdg-open-Wrapper
│   ├── theme.py           # Theme-/Font-Konstanten
│   ├── tooltip.py         # Tooltip-Helfer
│   ├── version.py         # Einzige Quelle der App-Version
│   └── paths.py           # Pfadauflösung (Script- vs. Frozen-Modus)
├── tests/                 # pytest-Testdateien
├── assets/
│   └── margenheld-icon    # App-Icon (.png + .ico + .icns)
├── docs/                  # Setup-Anleitung, Specs/Plans, Known Limitations
├── build.py               # Plattform-Dispatcher für den PyInstaller-Build
├── installer.iss          # Inno Setup Script (Windows-Installer)
├── requirements.txt       # Python-Abhängigkeiten
├── settings.json          # Benutzereinstellungen (wird automatisch erstellt)
└── zeiterfassung.json     # Gespeicherte Zeiteinträge (wird automatisch erstellt)
```

## Installation

### Fertige Releases

Vorgefertigte Installer für alle drei Plattformen gibt es unter [Releases](../../releases):

**Windows**
Lade `Zeiterfassung_Setup.exe` und führe den Installer aus. App installiert nach `%LOCALAPPDATA%\Programs\Zeiterfassung\`.

**macOS** (Apple Silicon)
Lade `Zeiterfassung-<ver>-arm64.dmg` herunter. Öffne das DMG und ziehe die App in den Applications-Ordner. Beim ersten Start: Rechtsklick auf die App → „Öffnen" (Gatekeeper-Warnung bestätigen), oder im Terminal:

```bash
xattr -dr com.apple.quarantine /Applications/Zeiterfassung.app
```

Der Build ist nicht signiert — dieser Schritt ist einmalig nötig.

**Linux**
Lade `Zeiterfassung-<ver>-x86_64.AppImage` herunter:

```bash
chmod +x Zeiterfassung-<ver>-x86_64.AppImage
./Zeiterfassung-<ver>-x86_64.AppImage
```

Voraussetzung: `libfuse2` installiert (`sudo apt install libfuse2` unter Debian/Ubuntu).

### Aus dem Source-Code

#### Voraussetzungen

- Python 3.10+
- Windows 10/11, macOS 12+ oder Linux (mit Tkinter)

#### Linux: Tkinter installieren

Tkinter ist unter Linux nicht immer vorinstalliert:

```bash
# Debian / Ubuntu
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter

# Arch
sudo pacman -S tk
```

#### Setup

```bash
# Repository klonen
git clone <repo-url>
cd Zeiterfassung

# Abhängigkeiten installieren
pip install -r requirements.txt

# App starten
python -m src.main
```

#### Abhängigkeiten

| Paket | Zweck |
|-------|-------|
| `google-auth-oauthlib` | OAuth2-Authentifizierung für Gmail |
| `google-api-python-client` | Gmail API Client |
| `xhtml2pdf` | PDF-Generierung aus HTML |
| `pyinstaller` | Paketierung als Standalone-Binary |

## Gmail API einrichten

Damit die App E-Mails versenden kann, muss einmalig ein Google Cloud Projekt mit Gmail API eingerichtet werden.

### 1. Google Cloud Projekt erstellen

1. [Google Cloud Console](https://console.cloud.google.com/) öffnen
2. Projekt-Dropdown → **Neues Projekt** → Name: "Zeiterfassung" → **Erstellen**

### 2. Gmail API aktivieren

1. **APIs & Dienste** → **Bibliothek**
2. Nach "Gmail API" suchen → **Aktivieren**

### 3. OAuth-Zustimmungsbildschirm

1. **APIs & Dienste** → **OAuth-Zustimmungsbildschirm**
2. **Extern** → **Erstellen**
3. Ausfüllen:
   - App-Name: "Zeiterfassung"
   - Support-E-Mail: deine Gmail-Adresse
   - Entwickler-E-Mail: deine Gmail-Adresse
4. **Speichern und fortfahren**
5. Bei **Bereiche**: `gmail.send` und `userinfo.email` hinzufügen → **Aktualisieren** → **Speichern**
   - `userinfo.email` wird benötigt, damit die App die Absender-E-Mail-Adresse automatisch aus dem Google-Konto übernehmen kann (non-sensitive, keine Verifizierung nötig)
6. Bei **Testnutzer**: deine Gmail-Adresse hinzufügen → **Speichern**

### 4. OAuth2 Client-ID erstellen

1. **APIs & Dienste** → **Anmeldedaten**
2. **Anmeldedaten erstellen** → **OAuth-Client-ID**
3. Anwendungstyp: **Desktopanwendung** → Name: "Zeiterfassung" → **Erstellen**
4. **JSON herunterladen** → als `credentials.json` speichern:
   - **Entwicklung (aus dem Source):** im Projekt-Root
   - **Windows (installiert):** `%LOCALAPPDATA%\Programs\Zeiterfassung\`
   - **macOS (installiert):** `~/Library/Application Support/Zeiterfassung/`
   - **Linux (AppImage):** `~/.local/share/Zeiterfassung/` (oder `$XDG_DATA_HOME/Zeiterfassung/`)

### 5. Erster Versand

1. App starten
2. Unter **Einstellungen** (⚙) E-Mail und Empfänger eintragen
3. **Monat senden** klicken
4. Browser öffnet sich → mit Google anmelden → Zugriff erlauben
5. `token.json` wird automatisch erstellt — ab jetzt kein erneutes Anmelden nötig

### Hinweise

- Die App läuft im **Test-Modus** — nur eingetragene Testnutzer können sich authentifizieren
- Das Token wird automatisch erneuert; bei Ablauf öffnet sich der Browser erneut
- `credentials.json` und `token.json` gehören **nicht** ins Repository

## Multi-Device-Sync einrichten (optional)

Wer die App auf mehreren Geräten (z. B. Büro-PC und Privat-Laptop) mit demselben Google-Konto nutzt, kann Zeiteinträge und Mail-Vorlagen automatisch synchronisieren. Die Sync-Datei liegt in einem **versteckten App-Ordner** in deinem Google Drive (`appDataFolder`) — sie taucht nicht in der normalen Drive-Ansicht auf und ist nur für diese App lesbar.

**Voraussetzung:** Gmail API ist bereits eingerichtet (siehe Abschnitt oben). Die Sync-Funktion erweitert das bestehende OAuth-Setup nur um einen zusätzlichen Scope.

### 1. Google Drive API aktivieren

1. [Google Cloud Console](https://console.cloud.google.com/) öffnen, dein bestehendes Zeiterfassungs-Projekt wählen
2. **APIs & Dienste** → **Bibliothek**
3. Nach "Google Drive API" suchen → **Aktivieren**

### 2. drive.appdata-Scope hinzufügen

Google hat die OAuth-Konfiguration 2025 unter **Google Auth Platform** zusammengezogen. Direkt-Link zur Scope-Seite:

```
https://console.cloud.google.com/auth/scopes
```

Oder manuell: **Menü ☰ → Google Auth Platform → Data Access**.

1. **Bereiche hinzufügen oder entfernen** klicken
2. Im Filter `drive.appdata` eintippen
3. Häkchen bei `.../auth/drive.appdata` (Google Drive API) setzen — Beschreibung: „Eigene Konfigurationsdaten in Google Drive abrufen, erstellen und löschen"
4. **Aktualisieren** klicken → der Scope landet unter „Nicht vertrauliche Bereiche" (keine Verifizierung nötig — `drive.appdata` ist Non-Sensitive)

### 3. Bestehendes Token verwerfen

Solange die alte `token.json` (nur mit `gmail.send`-Scope) existiert, läuft kein neuer Consent-Flow. Datei löschen:

- **Windows (installiert):** `%LOCALAPPDATA%\Programs\Zeiterfassung\token.json`
- **macOS (installiert):** `~/Library/Application Support/Zeiterfassung/token.json`
- **Linux (AppImage):** `~/.local/share/Zeiterfassung/token.json`
- **Entwicklung (Source):** `token.json` im Projekt-Root

### 4. Sync in der App aktivieren

1. App starten → Einstellungen (⚙) öffnen
2. Sektion **Synchronisation** ganz unten → Checkbox **„Mit Google Drive synchronisieren"** anhaken
3. Browser öffnet sich → mit Google anmelden → der Consent-Screen zeigt jetzt **zwei** Berechtigungen:
   - „E-Mails über dein Konto senden" (Gmail, bestehend)
   - „Eigene Konfigurationsdaten in deinem Google Drive einsehen und verwalten" (Drive appdata, neu)
4. Beiden zustimmen → im Header erscheint rechts ein `⟳`-Button und ein Status-Label

Wiederhole Schritte 3-4 auf jedem weiteren Gerät mit demselben Google-Konto.

### Wie der Sync funktioniert

- **Pull beim App-Start** — sobald Sync aktiv und Netz da ist, werden Drive-Änderungen anderer Geräte im Hintergrund eingespielt
- **Push beim App-Schließen** — lokale Änderungen werden vor dem Beenden hochgeladen (5s Timeout)
- **Manueller Sync** — der `⟳`-Button im Header triggert sofortigen Push
- **Konflikte** — wird ein Tag offline auf zwei Geräten unterschiedlich bearbeitet, erscheint nach dem Sync ein Warn-Icon auf dem Tag und ein „⚠ N Konflikte"-Status. Klick auf **Konflikte ansehen** in den Einstellungen öffnet einen Dialog, in dem du Version A, B oder einen eigenen Wert übernehmen kannst

### Hinweise zum Sync

- **Geräte-ID** — jede Installation generiert beim ersten Start eine eindeutige UUID. Im Konflikt-Dialog siehst du, von welchem Gerät die jeweilige Version kommt.
- **Was synchronisiert wird:** Zeiteinträge + Mail-Vorlagen-Settings (Empfänger, Name, Stundensatz, Betreff, Begrüßung, Inhalt, Grußformel). Gerätespezifisches (Autostart, Standardzeiten pro Wochentag, Update-Check-Status) bleibt lokal.
- **Wo die Sync-Datei liegt:** Im versteckten `appDataFolder` deines Google Drives — nicht über `drive.google.com` einsehbar, nur diese App kommt dran.
- **Test-Modus:** Solange dein Cloud-Projekt im Test-Modus bleibt, müssen alle Nutzer (deine eigenen Geräte zählen mit deiner E-Mail) als Testnutzer eingetragen sein. Verifizierung durch Google ist für rein private Nutzung nicht nötig.
- **Tombstones wachsen unbeschränkt** — gelöschte Einträge bleiben als Marker im Sync-File, damit Löschungen sich gegen veraltete Speicherungen anderer Geräte durchsetzen. Bei normalem Gebrauch unproblematisch über Jahre; siehe [`docs/known-limitations.md`](docs/known-limitations.md).

## Einstellungen

Über das Zahnrad-Symbol (⚙) im Header konfigurierbar:

| Einstellung | Beschreibung |
|-------------|-------------|
| **E-Mail** | Eigene Gmail-Adresse (Absender) |
| **Empfänger** | E-Mail-Adresse für den Report |
| **Name** | Vollständiger Name (erscheint im PDF) |
| **Standard-Pause** | Standardmäßige Pausendauer in Minuten |
| **Betreff** | E-Mail-Betreff mit Platzhaltern |
| **Begrüßung** | Anrede im E-Mail-Text |
| **Inhalt** | E-Mail-Body mit Platzhaltern |
| **Grußformel** | Abschluss der E-Mail (Zeilenumbrüche mit `\n`) |
| **Autostart** | App minimiert bei Systemanmeldung starten (Windows/macOS/Linux) |
| **Synchronisation** | Multi-Device-Sync via Google Drive aktivieren (siehe Abschnitt oben) |

### Platzhalter in E-Mail-Vorlagen

| Platzhalter | Wird ersetzt durch |
|-------------|-------------------|
| `{zeitraum}` | Datumsbereich, z.B. "01.03.2026 – 31.03.2026" |
| `{gesamt}` | Gesamtstunden, z.B. "168.5h" |

## Build

```bash
python build.py
```

`build.py` erkennt die Plattform via `platform.system()` und baut das passende Artefakt:

| Plattform | Voraussetzung | Ausgabe |
|-----------|---------------|---------|
| Windows | [Inno Setup 6](https://jrsoftware.org/isdl.php) unter `%LOCALAPPDATA%\Programs\Inno Setup 6\` | `dist/Zeiterfassung_Setup.exe` |
| macOS | `brew install create-dmg` | `dist/Zeiterfassung-<ver>-<arch>.dmg` |
| Linux | `apt install libfuse2` + `appimagetool` auf `$PATH` | `dist/Zeiterfassung-<ver>-<arch>.AppImage` |

Fehlt das Pack-Tool, überspringt `build.py` den Pack-Schritt mit Warnung — der PyInstaller-Build läuft trotzdem durch.

## Plattform-Kompatibilität

Die App läuft auf **Windows, macOS und Linux**. Plattformspezifische Features werden automatisch erkannt:

| Feature | Windows | macOS | Linux |
|---------|---------|-------|-------|
| Kalender & Zeiterfassung | ✓ | ✓ | ✓ |
| PDF-Report & E-Mail-Versand | ✓ | ✓ | ✓ |
| Einstellungen & Vorlagen | ✓ | ✓ | ✓ |
| Taskbar-Icon (AppUserModelID) | ✓ | — (nicht nötig) | — (nicht nötig) |
| Window-Icon | ✓ (`.ico`) | ✓ (`.png` Fallback) | ✓ (`.png` Fallback) |
| Autostart bei Anmeldung | ✓ (VBScript-Shortcut) | ✓ (LaunchAgent plist) | ✓ (`.desktop`-Datei) |
| Standalone-Binary (PyInstaller) | ✓ (`.exe`) | ✓ (`.app` Bundle) | ✓ (AppImage) |

## Tests

```bash
pytest tests/
```

## Datenspeicherung

Alle Daten werden lokal als JSON gespeichert:

- **zeiterfassung.json** — Zeiteinträge (Schlüssel: ISO-Datum `YYYY-MM-DD`)
- **settings.json** — Benutzereinstellungen
- **token.json** — Gmail/Drive OAuth-Token (wird automatisch erneuert)
- **conflicts.json** — Lokaler Spiegel der Sync-Konflikte (nur vorhanden bei aktivem Sync und mindestens einem registrierten Konflikt)

Bei aktivem Sync liegt zusätzlich in deinem Google Drive eine versteckte Datei `zeiterfassung-sync.json` im `appDataFolder` — nicht über die Drive-Web-Oberfläche sichtbar, nur die App kommt dran.

Speicherort je nach Plattform (siehe `src/paths.py`):

| Plattform | Pfad |
|-----------|------|
| Windows (installiert) | `%LOCALAPPDATA%\Programs\Zeiterfassung\` |
| macOS (installiert) | `~/Library/Application Support/Zeiterfassung/` |
| Linux (AppImage) | `$XDG_DATA_HOME/Zeiterfassung/` (Fallback `~/.local/share/Zeiterfassung/`) |
| Entwicklung (Source) | Projekt-Root |

> **Sicherheitshinweis:** `token.json` enthält im Klartext einen langlebigen
> OAuth-Refresh-Token, der laufenden Zugriff auf dein Google-Konto (Gmail-Versand,
> Drive-Sync, ggf. Kalender) gewährt. Unter macOS/Linux wird die Datei mit
> `chmod 0600` nur für deinen Benutzer lesbar gemacht; unter Windows schützt sie
> die ACL deines Benutzerprofils. **Wer den Daten-/Installationsordner kopiert,
> sichert oder in die Cloud synchronisiert, nimmt diesen Token mit** — behandle
> den Ordner entsprechend vertraulich und gib ihn nicht weiter. Bei Verdacht auf
> Kompromittierung den Zugriff in den [Google-Kontoeinstellungen](https://myaccount.google.com/permissions)
> entziehen und `token.json` löschen (die App startet beim nächsten Versand einen
> neuen Anmelde-Flow).
