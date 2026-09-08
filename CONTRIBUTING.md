# Mitwirken

Danke für dein Interesse an Zeiterfassung! Beiträge sind willkommen — egal ob
Bugfix, Feature oder Doku-Korrektur.

Für Fehler und Wünsche gibt es [Issue-Formulare](https://github.com/Xveyn/Zeiterfassung/issues/new/choose);
Fragen und unfertige Ideen passen besser in die
[Discussions](https://github.com/Xveyn/Zeiterfassung/discussions). Für den Umgang
miteinander gilt der [Verhaltenskodex](CODE_OF_CONDUCT.md).

## Entwicklungsumgebung

### Voraussetzungen

- Python 3.10+
- Windows 10/11, macOS 12+ oder Linux (mit Tkinter)

### Linux: Tkinter installieren

Tkinter ist unter Linux nicht immer vorinstalliert:

```bash
# Debian / Ubuntu
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter

# Arch
sudo pacman -S tk
```

### Setup

```bash
# Repository klonen
git clone https://github.com/Xveyn/Zeiterfassung.git
cd Zeiterfassung

# Abhängigkeiten installieren
pip install -r requirements.txt

# App starten
python -m src.main
```

Die App **muss** als Modul gestartet werden (`python -m src.main`), nicht als
Script — die Imports innerhalb von `src/` sind absolut (`from src...`).

### Abhängigkeiten

| Paket | Zweck |
|-------|-------|
| `google-auth-oauthlib` | OAuth2-Authentifizierung für Gmail |
| `google-api-python-client` | Gmail API Client |
| `xhtml2pdf` | PDF-Generierung aus HTML |
| `pyinstaller` | Paketierung als Standalone-Binary |
| `holidays` | Feiertags-Lookup (deutsche Feiertage) |
| `keyring` | SMTP-Passwörter im Schlüsselbund des Betriebssystems |
| `pystray` | Infobereich-Icon (Minimize-to-Tray) |
| `Pillow` | Icon-/Bildverarbeitung (Tray-Icon) |
| `dbus-fast` | Linux-Tray über StatusNotifierItem (nur Linux) |
| `pyobjc-framework-Cocoa` | Natives macOS-Tray (nur macOS) |

## Projektstruktur

> Detaillierte Architektur — die `App`-Komponenten (`GridRenderer`, `BackgroundTaskRunner`, `SyncOrchestrator`, `UpdateBanner`), ihre Verträge und das Threading-Modell: [`src/CLAUDE.md`](src/CLAUDE.md).

<details>
<summary>Verzeichnisbaum mit Kurzbeschreibung je Modul</summary>

```
Zeiterfassung/
├── src/
│   ├── main.py            # Einstiegspunkt
│   ├── ui.py              # Tkinter-GUI; App koordiniert die Komponenten (Chrome, Navigation, Dialog-Routing)
│   ├── grid_renderer.py   # Kalender-/Grid-Rendering (Monats-/Wochenansicht, Zelltypen, Double-Buffer)
│   ├── background_tasks.py # Hintergrund-Worker + Thread-Mechanik (Token-Refresh, Update-Check, Reconcile)
│   ├── sync_orchestrator.py # Drive-Sync-Steuerung (manuell/Tray/Pull/Quit, Fehler-Aufbereitung)
│   ├── update_banner.py   # GitHub-Release-Hinweis-Banner
│   ├── dialogs/           # Modal-Dialoge (entry, send, export, settings [inkl. SMTP-Tab], share, import, conflicts, category, scopes, webhook, smtp, vacation) + geteilter period_picker
│   ├── json_store.py      # Gemeinsame Mechanik der lokalen JSON-Stores (atomares Schreiben, Quarantäne)
│   ├── storage.py         # JSON-Persistenz der Zeiteinträge
│   ├── settings.py        # Einstellungen mit Standardwerten
│   ├── category_defaults.py # Default-Kategorien für Zeit-Slots
│   ├── report.py          # HTML- & PDF-Reportgenerierung
│   ├── mime_message.py    # Gemeinsamer MIME-Bau für Gmail-API und SMTP (UTF-8-Charset, Betreff-Header, Header-Injection-Abwehr)
│   ├── mail.py            # Gmail OAuth2-Authentifizierung & Versand
│   ├── smtp.py            # SMTP-Versand (smtplib/ssl), Verbindungstest, eigene Fehlerklassifikation
│   ├── smtp_store.py      # Gerätelokale Persistenz der SMTP-Konten (gehärtet geschrieben, kein Sync)
│   ├── keyring_store.py   # SMTP-Passwörter im OS-Schlüsselbund, mit Datei-Fallback
│   ├── webhook.py         # Webhook-Versand (URL-Prüfung, Auth/HMAC, Payload, POST), pure Logik
│   ├── webhook_store.py   # Gerätelokale Persistenz der Webhooks (gehärtet geschrieben, kein Sync)
│   ├── drive.py           # Google Drive API-Wrapper (Multi-Device-Sync)
│   ├── sync.py            # Sync-Engine (pure Logik, LWW-Merge, Konflikterkennung)
│   ├── sync_runtime.py    # Sync-/Kompaktierungs-/Reconcile-Flows über der Engine
│   ├── sync_journal.py    # Crash-Recovery für den Sync-Apply (Write-Ahead-Journal)
│   ├── sync_history.py    # Persistenter „hat je gesynct/abgeglichen"-Marker (Tombstone-Schutz)
│   ├── conflicts_store.py # Lokale Persistenz der Konfliktliste
│   ├── share.py           # Export/Import von Arbeitszeiten als Share-JSON
│   ├── reservations.py    # Reservierungen (zukünftige Soll-Zeiten)
│   ├── reservations_sync.py # Abgleich der Reservierungen mit Google Kalender
│   ├── vacations.py       # Urlaubsperioden (Regeln + Persistenz, gerätelokal)
│   ├── vacations_sync.py  # Einwegs-Push der Urlaubsperioden in den Google Kalender
│   ├── reminders.py       # Fälligkeits-Logik für Reservierungs-Erinnerungen (Tk-frei)
│   ├── reminder_scheduler.py # Periodischer Reminder-Poll → Toast über Tray
│   ├── send_reminder.py   # Fälligkeits-Logik des Sende-Reminders: monatlich + am markierten Slot (Tk-frei)
│   ├── send_reminder_scheduler.py # Periodischer Poll über beide Kanäle → Sende-Toast
│   ├── weekly_limit.py    # Wochenstunden-Limit (Werkstudenten-Privileg), pure Logik
│   ├── pause_requirement.py # Pausenpflicht-Check nach § 4 ArbZG, pure Logik
│   ├── workweek.py        # Nur-Werktage-Modus (Sa/So ausblenden), pure Logik
│   ├── gcal.py            # Google-Calendar-API-Wrapper
│   ├── oauth_utils.py     # Gemeinsame OAuth-Token-Boilerplate (Persistenz, Scope-Upgrade) für mail/drive/gcal
│   ├── tray/              # Infobereich-Icon (Minimize-to-Tray): Plattform-Fassade,
│   │                      #   Menü-Modell und je ein Backend für Windows (pystray),
│   │                      #   macOS (NSStatusItem) und Linux (StatusNotifierItem) — die
│   │                      #   letzten beiden dormant/opt-in
│   ├── autostart.py       # Plattformabhängiger Autostart (Windows-Registry/macOS/Linux)
│   ├── desktop_entry.py   # Freedesktop-.desktop-Eintrag + Icon-Kopie (Linux-Anwendungsmenü)
│   ├── secure_file.py     # Zugriffsschutz für lokale Secrets (Windows-ACL via icacls)
│   ├── single_instance.py # Single-Instance-Guard (verhindert parallele Instanzen)
│   ├── device_id.py       # Stabile, hardware-abgeleitete Geräte-ID für installierte Builds (Sync)
│   ├── devices.py         # Lesbare Gerätenamen (Registry im Sync-Doc) für den Konflikt-Dialog
│   ├── updater.py         # GitHub-Releases-Check (stdlib-only, Frequenz konfigurierbar)
│   ├── self_update.py     # Update laden, gegen SHA256SUMS prüfen und installieren (Windows/Linux)
│   ├── changelog.py       # Lädt/parst den Changelog-Abschnitt einer Release-Version
│   ├── holidays_de.py     # Feiertags-Lookup (python-holidays)
│   ├── time_utils.py      # Zeitberechnung und Validierung
│   ├── logging_setup.py   # File-Logging + globaler Excepthook
│   ├── platform_open.py   # os.startfile/open/xdg-open-Wrapper
│   ├── theme/             # Dark-Theme: Palette, Fonts, Widget-Fabriken, Fenster-Chrome,
│   │                      #   Geometrie-Helfer und themed messagebox-Drop-ins
│   ├── tooltip.py         # Tooltip-Helfer
│   ├── version.py         # Einzige Quelle der App-Version
│   └── paths.py           # Pfadauflösung (Script- vs. Frozen-Modus)
├── tests/                 # pytest-Testdateien
├── assets/
│   └── margenheld-icon    # App-Icon (.png + .ico + .icns)
├── docs/                  # Specs/Plans, Known Limitations
├── scripts/               # Entwickler-Skripte (nicht Teil der App)
│   ├── build.py           # Plattform-Dispatcher für den PyInstaller-Build
│   ├── resolve_readme_version.py # Pflegt die Versionsmarker dieser README
│   ├── webhook_testserver.py  # lokaler Test-Empfänger für den Webhook-Versand
│   └── smtp_testserver.py     # lokaler Test-Mailserver für den SMTP-Versand
├── installer.iss          # Inno Setup Script (Windows-Installer)
├── requirements.txt       # Python-Abhängigkeiten (App-Laufzeit, exakt gepinnt)
├── requirements-test.txt  # Test-/CI-Abhängigkeiten (pytest & Co., exakt gepinnt)
├── pyproject.toml         # Konfiguration für ruff, pytest, coverage und pyright
└── (Laufzeitdaten)        # settings.json, zeiterfassung.json u.a. entstehen im
                           # Repo-Modus hier — vollständige Liste im Abschnitt
                           # „Datenspeicherung"
```

</details>

## Tests

Die Test-Abhängigkeiten stehen gepinnt in `requirements-test.txt` (nicht in
`requirements.txt` — dort liegen nur die App-Laufzeit-Deps):

```bash
pip install -r requirements-test.txt

pytest                                   # alle Tests
pytest tests/test_storage.py             # eine Datei
pytest tests/test_storage.py::test_name  # einzelner Test
```

Coverage-Report lokal (braucht zusätzlich `pip install pytest-cov`):

```bash
pytest --cov=src --cov-report=term-missing
```

`pytest` ist das Gate: **alle Tests müssen grün sein, bevor ein PR gemerged wird.**
Wer testbares Verhalten ändert (Feature wie Bugfix), schreibt einen passenden Test
mit — bei Bugfixes idealerweise erst einen Test, der den Fehler reproduziert.

In der CI läuft die Test-Suite gegen Python 3.10–3.13 sowie zusätzlich auf Windows
und macOS; dazu kommen `ruff check .` (Lint) und `pyright` (Typen).

## Build

```bash
python scripts/build.py
```

`scripts/build.py` erkennt die Plattform via `platform.system()` und baut das passende Artefakt:

| Plattform | Voraussetzung | Ausgabe |
|-----------|---------------|---------|
| Windows | [Inno Setup 6](https://jrsoftware.org/isdl.php) unter `%LOCALAPPDATA%\Programs\Inno Setup 6\` | `dist/Zeiterfassung_Setup.exe` |
| macOS | `brew install create-dmg` | `dist/Zeiterfassung-<ver>-<arch>.dmg` |
| Linux | `apt install libfuse2` + `appimagetool` auf `$PATH` | `dist/Zeiterfassung-<ver>-<arch>.AppImage` |

Fehlt das Pack-Tool, überspringt `scripts/build.py` den Pack-Schritt mit Warnung — der PyInstaller-Build läuft trotzdem durch. Die unverpackte Ausgabe liegt dann je nach Plattform als **Ordner** oder Einzeldatei in `dist/`:

| Plattform | PyInstaller-Modus | Unverpackte Ausgabe |
|-----------|-------------------|---------------------|
| Windows | `--onedir` | `dist/Zeiterfassung/` (`Zeiterfassung.exe` + `_internal/`) |
| macOS | `--onedir` | `dist/Zeiterfassung.app` |
| Linux | `--onefile` | `dist/Zeiterfassung` (Einzeldatei) |

Windows baut seit 1.19.1 `--onedir` statt `--onefile`: Onefile entpackte bei jedem Start alle DLLs frisch in einen Temp-Ordner, was gelegentlich zu „Failed to load Python DLL 'python310.dll'" führte. Der Installer liefert entsprechend den ganzen Ordner aus — der Installationspfad und die Lage der Benutzerdaten (neben der Exe) ändern sich dadurch nicht.

## Pull Requests

1. Branch von `master` abzweigen.
2. Änderung umsetzen, Tests grün halten.
3. PR gegen `master` öffnen mit einer kurzen Beschreibung, **was** sich verhält und
   **warum**.

Nur anfassen, was die Änderung verlangt, und den vorhandenen Stil matchen. `master`
ist protected — Merge erfolgt über PR.

## Commit-Konventionen

- Commit-**Typ** englisch im Conventional-Commits-Stil: `feat:`, `fix:`, `docs:`,
  `ci:`, `refactor:` … Der Body darf deutsch sein.
- Code und Bezeichner englisch; UI-Texte und Konversation deutsch.

## Wichtige Projekt-Konventionen

- **Datumsformat:** intern **immer ISO** (`YYYY-MM-DD`, Timestamps `…THH:MM…`) für
  Storage, Filter, Sync und Payloads. In der **UI immer deutsch** (`TT.MM.JJJJ`) über
  die Helfer in `src/time_utils.py` (`format_iso_date` / `format_iso_datetime`) — nicht
  roh `isoformat()`/`str()` ausgeben.
- **Sichtbare Fehler:** Fehler im Sendepfad (Gmail, PDF) müssen per
  `messagebox.showerror` mit `traceback.format_exc()` angezeigt werden — `--noconsole`
  im Build unterdrückt sonst jede Spur.
- **README-Zeilen für Unveröffentlichtes markieren:** Die README beschreibt den
  Stand von `master`, nicht den des letzten Releases. Wer ein Feature dort
  einträgt, das noch nicht released ist, hängt `*(ab X.Y.Z)*` an den fetten
  Namen — sonst liest die Startseite des Repositories von etwas, das es im
  Download noch nicht gibt.
- Weitere Details (UTF-8 in der Mail-Pipeline, Build, CI-Eigenheiten) stehen in
  [`CLAUDE.md`](CLAUDE.md).

## Releases

Releases erstellt der Maintainer über ein `release:*`-Label am gemergten PR
(siehe [`CLAUDE.md`](CLAUDE.md#release-prozess)). Als Contributor musst du dich
darum nicht kümmern — Versionsbump und Changelog übernimmt der Maintainer beim
Release-PR.

## Sicherheit

Sicherheitslücken bitte **nicht** über öffentliche Issues melden, sondern wie in
[`SECURITY.md`](SECURITY.md) beschrieben.
