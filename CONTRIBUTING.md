# Mitwirken

Danke für dein Interesse an Zeiterfassung! Beiträge sind willkommen — egal ob
Bugfix, Feature oder Doku-Korrektur.

Für Fehler und Wünsche gibt es [Issue-Formulare](https://github.com/Xveyn/Zeiterfassung/issues/new/choose);
Fragen und unfertige Ideen passen besser in die
[Discussions](https://github.com/Xveyn/Zeiterfassung/discussions). Für den Umgang
miteinander gilt der [Verhaltenskodex](CODE_OF_CONDUCT.md).

## Entwicklungsumgebung

### Voraussetzungen

- Python 3.12+
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

Aus dem Quellcode gestartet, erscheinen die Log-Zeilen zusätzlich im Terminal
(der gebaute Build loggt nur ins Logfile `logs/zeiterfassung.log`). Mehr Details
liefert die Umgebungsvariable `ZEITERFASSUNG_LOG_LEVEL` — sie gilt für Terminal
und Logfile:

```powershell
$env:ZEITERFASSUNG_LOG_LEVEL = "DEBUG" ; python -m src.main
```

```bash
ZEITERFASSUNG_LOG_LEVEL=DEBUG python -m src.main
```

### Abhängigkeiten

| Paket | Zweck |
|-------|-------|
| `google-auth-oauthlib` | OAuth2-Authentifizierung für Gmail |
| `google-api-python-client` | Gmail API Client |
| `xhtml2pdf` | PDF-Generierung aus HTML |
| `pyinstaller` | Paketierung als Standalone-Binary |
| `holidays` | Feiertags-Lookup (deutsche Feiertage) |
| `keyring` | SMTP-Passwörter, OAuth-Refresh-Token, Webhook-Secrets im Schlüsselbund des Betriebssystems |
| `segno` | QR-Code im Koppel-Dialog der Handy-Erfassung (reines Python) |
| `cryptography` | AES-GCM und HKDF für die Verschlüsselung der Handy-Erfassung (vorher nur transitiv über `google-auth`; Wheels `cp311-abi3` für Windows, macOS arm64 und Linux x86_64) |
| `pystray` | Infobereich-Icon (Minimize-to-Tray) |
| `Pillow` | Icon-/Bildverarbeitung (Tray-Icon) |
| `dbus-fast` | Linux-Tray über StatusNotifierItem (nur Linux) |
| `pyobjc-framework-Cocoa` | Natives macOS-Tray (nur macOS) |

## Projektstruktur

> Detaillierte Architektur — die `App`-Komponenten (`GridRenderer`, `BackgroundTaskRunner`, `SyncOrchestrator`, `UpdateBanner`, `UpdateCoordinator`), ihre Verträge und das Threading-Modell: [`src/CLAUDE.md`](src/CLAUDE.md).

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
│   ├── update_coordinator.py # Update-Lebenszyklus: Start-Check, Toast/Banner, Tray-Check, Anwenden beim Beenden
│   ├── dialogs/           # Modal-Dialoge (entry, send, export, settings [Paket, ein Modul je Tab; SMTP und Webhooks im Versand-Tab], share, import, conflicts, category, scopes, webhook, smtp, vacation, mobile_pair, removal) + geteilte Bausteine (period_picker, date_row, slot_rows)
│   ├── json_store.py      # Gemeinsame Mechanik der lokalen JSON-Stores (atomares Schreiben, Quarantäne)
│   ├── storage.py         # JSON-Persistenz der Zeiteinträge
│   ├── settings.py        # Einstellungen mit Standardwerten
│   ├── category_defaults.py # Per-Kategorie-Standardzeiten (allgemein oder je Wochentag), pure Logik
│   ├── report.py          # HTML- & PDF-Reportgenerierung
│   ├── mime_message.py    # Gemeinsamer MIME-Bau für Gmail-API und SMTP (UTF-8-Charset, Betreff-Header, Header-Injection-Abwehr)
│   ├── mail.py            # Gmail OAuth2-Authentifizierung & Versand
│   ├── smtp.py            # SMTP-Versand (smtplib/ssl), Verbindungstest, eigene Fehlerklassifikation
│   ├── smtp_store.py      # Gerätelokale Persistenz der SMTP-Konten (gehärtet geschrieben, kein Sync)
│   ├── keyring_store.py   # Passwörter und Geheimnisse im OS-Schlüsselbund (30-s-Watchdog), mit Datei-Fallback
│   ├── token_store.py     # OAuth-Credentials laden/speichern, Refresh-Token im Schlüsselbund
│   ├── webhook_secrets.py # Webhook-Secrets im Schlüsselbund
│   ├── secret_migration.py # Klartext-Secrets beim Start in den Schlüsselbund umziehen; Aufräumen bei der Deinstallation
│   ├── topmost_relief.py  # „Immer im Vordergrund" kurz aufheben, solange der Schlüsselbund fragt
│   ├── webhook.py         # Webhook-Versand (URL-Prüfung, Auth/HMAC, Payload, POST), pure Logik
│   ├── webhook_store.py   # Gerätelokale Persistenz der Webhooks (gehärtet geschrieben, kein Sync)
│   ├── drive.py           # Google Drive API-Wrapper (Multi-Device-Sync)
│   ├── sync.py            # Sync-Engine (pure Logik, LWW-Merge, Konflikterkennung)
│   ├── sync_runtime.py    # Sync-/Kompaktierungs-/Reconcile-Flows über der Engine
│   ├── sync_journal.py    # Crash-Recovery für den Sync-Apply (Write-Ahead-Journal)
│   ├── sync_history.py    # Persistenter „hat je gesynct/abgeglichen"-Marker (Tombstone-Schutz)
│   ├── conflicts_store.py # Lokale Persistenz der Konfliktliste
│   ├── share.py           # Export/Import von Arbeitszeiten als Share-JSON
│   ├── share_message.py   # Mail zum Teilen: Betreff, HTML-Body, Anhangsname
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
│   ├── api_auth.py        # Lokale HTTP-API (#92): Token und Zugangsprüfung
│   ├── api_server.py      # … Server im Daemon-Thread (Loopback bzw. Handy-Instanz)
│   ├── api_service.py     # … Lebenszyklus (api_enabled/api_port)
│   ├── api_routes.py      # … Routing und Antworten
│   ├── api_summary.py     # … Auswertungen (Summen, Kategorien, Limit, Urlaub)
│   ├── api_entry_write.py # … Schreibpfad der Ist-Zeiten
│   ├── api_reservation_write.py # … Schreibpfad der Reservierungen
│   ├── api_vacation_write.py # … Schreibpfad des Urlaubs
│   ├── vacation_plan.py   # Planung beim Anlegen einer Urlaubsperiode (aus dem Dialog gezogen, auch von der API genutzt)
│   ├── mobile_service.py  # Handy-Erfassung (#221): Lebenszyklus der LAN-Instanz
│   ├── mobile_routes.py   # … Routen (/v1/pair, /v1/ping, /v1/sync) als verschlüsselte Umschläge
│   ├── mobile_sync.py     # … fachlicher Kern des Abgleichs
│   ├── mobile_reservations.py # … Reservierungen im Abgleich
│   ├── mobile_settings.py # … Einstellungen (Kategorien, Standardzeiten) im Abgleich
│   ├── mobile_reminders.py # … Erinnerungen: Block der Antwort, Relay-Geheimnis
│   ├── mobile_pairing.py  # … Kopplungscode und Gerätetoken
│   ├── mobile_store.py    # … gekoppelte Handys (gerätelokal, nur Token-Hashes)
│   ├── mobile_crypto.py   # … Ende-zu-Ende-Verschlüsselung (AES-GCM/HKDF), Gegenstück pwa/crypto.js
│   ├── mobile_keys.py     # … Geräteschlüssel im Schlüsselbund, Datei als Fallback
│   ├── mobile_relay_store.py # … Relay-Geheimnisse der Handys (gehärtet)
│   ├── push_relay.py      # Spricht den Push-Relay an (Abräumen beim Widerruf, Testbenachrichtigung)
│   ├── netinfo.py         # LAN-Adressen (nur RFC 1918) für die Handy-Erfassung
│   ├── qr.py              # QR-Code-Matrix für den Koppel-Dialog (segno)
│   ├── removal.py         # „Zeiterfassung entfernen" (macOS/Linux): Plan und Ausführung
│   ├── dpi.py             # Systemfaktor der UI-Skalierung (Windows-DPI-Awareness, Linux-Xft.dpi)
│   ├── ui_queue.py        # Thread-sichere Übergabe von Worker-Callbacks an den UI-Thread
│   ├── auto_update.py     # Auto-Update-Policy (stiller Download, Vormerken bis zum Beenden)
│   ├── updater.py         # GitHub-Releases-Check (stdlib-only, Frequenz konfigurierbar)
│   ├── self_update.py     # Update laden, gegen SHA256SUMS prüfen und installieren (Windows/Linux)
│   ├── changelog.py       # Lädt/parst den Changelog-Abschnitt einer Release-Version
│   ├── holidays_de.py     # Feiertags-Lookup (python-holidays)
│   ├── time_utils.py      # Zeitberechnung und Validierung
│   ├── logging_setup.py   # File-Logging + globaler Excepthook
│   ├── platform_open.py   # os.startfile/open/xdg-open-Wrapper
│   ├── theme/             # Dark-Theme: Palette, Fonts, Widget-Fabriken, Fenster-Chrome,
│   │                      #   Geometrie-Helfer, themed messagebox-Drop-ins und
│   │                      #   Formular-Bausteine (Form)
│   ├── tooltip.py         # Tooltip-Helfer
│   ├── version.py         # Einzige Quelle der App-Version
│   └── paths.py           # Pfadauflösung (Script- vs. Frozen-Modus)
├── pwa/                   # Handy-Web-App (reines JavaScript, kein Build), s. pwa/CLAUDE.md
├── relay/                 # Push-Relay (Cloudflare Worker + Durable Object), s. relay/CLAUDE.md
├── tests/                 # pytest-Testdateien
├── assets/
│   └── margenheld-icon    # App-Icon (.png + .ico + .icns)
├── docs/                  # Specs/Plans, Known Limitations
├── scripts/               # Entwickler-Skripte (nicht Teil der App), s. scripts/README.md
│   ├── build.py           # Plattform-Dispatcher für den PyInstaller-Build
│   ├── resolve_readme_version.py # Versionsmarker dieser README und Screenshot-Namen
│   ├── release_notes.py   # Release-Body aus dem CHANGELOG-Abschnitt
│   ├── archive_changelog.py   # ältere CHANGELOG-Abschnitte ins Archiv
│   ├── coverage_gate.py   # Coverage-Untergrenze für die Tk-freien Module (CI)
│   ├── pwa_devserver.py   # Dev-Server: echte Handy-Instanz plus pwa/ auf localhost:8099
│   ├── pwa_icons.py       # erzeugt pwa/icons aus dem Markenbild
│   ├── pwa_stamp.py       # stempelt die Build-Kennung der Handy-PWA (pages.yml)
│   ├── qr_fixtures.py     # Referenz-Matrizen für den QR-Decoder der PWA
│   ├── demo_data.py       # Demo-Daten für Screenshots und zum Ausprobieren
│   ├── webhook_testserver.py  # lokaler Test-Empfänger für den Webhook-Versand
│   └── smtp_testserver.py     # lokaler Test-Mailserver für den SMTP-Versand
├── .github/workflows/     # CI: test.yml, build.yml, release.yml, pages.yml (PWA veröffentlichen),
│                          #   readme-version.yml, relay-deploy.yml (Relay ausrollen)
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
pytest --cov=src --cov-report=term-missing --cov-report=json
python scripts/coverage_gate.py          # Untergrenze der Tk-freien Module
```

Die Gesamtzahl liegt bei rund 60 % und ist **kein** Gate — Tk-Code wird bewusst
nicht automatisiert getestet. Für alle Module, die `tkinter` nicht importieren,
gilt dagegen eine Untergrenze (`FLOOR` in `scripts/coverage_gate.py`); die CI
bricht ab, wenn sie unterschritten wird. Neue Logik gehört also in ein
Tk-freies Modul **und** getestet.

`pytest` ist das Gate: **alle Tests müssen grün sein, bevor ein PR gemerged wird.**
Wer testbares Verhalten ändert (Feature wie Bugfix), schreibt einen passenden Test
mit — bei Bugfixes idealerweise erst einen Test, der den Fehler reproduziert.

In der CI läuft die Test-Suite gegen Python 3.12–3.14 sowie zusätzlich auf Windows
und macOS; dazu kommen `ruff check .` (Lint) und `pyright` (Typen).

### PWA (`pwa/`)

Die Handy-Web-App ist reines JavaScript ohne Build und ohne npm-Abhängigkeiten (`pwa/` hat keine; der Relay unten schon). Tests laufen mit dem eingebauten Runner von Node (Node 22 oder neuer):

```
cd pwa && node --test
```

Die JSON-Beispiele in `pwa/test/fixtures/` sind der Vertrag zum Python-Server: Dieselben Dateien lesen die JS-Tests und `tests/test_mobile_contract.py`. Ändert sich Request, Response oder ein Fehlercode des Servers, ändern sich die Beispiele mit — sonst wird einer der beiden Tests rot.

Zum Ausprobieren im Browser startet `python scripts/pwa_devserver.py` die echte Handy-Instanz der App und dazu `pwa/` auf `http://localhost:8099/`; er druckt einen Koppel-Link mit frischem Code. Der Koppel-Link akzeptiert nur private IPv4-Adressen: Standard ist die erste gefundene LAN-Adresse; fällt der Server auf `127.0.0.1` zurück (kein LAN), startest du ihn mit `--address <LAN-IP>`. Der Dev-Server stempelt `__BUILD__` in `sw-core.js` selbst (`dev-<Hash>` über die App-Dateien, #272): eine Änderung unter `pwa/` löst den normalen Update-Weg aus, „Neu laden“ übernimmt den neuen Worker — Worker abmelden oder Caches leeren ist nicht nötig (`pwa/CLAUDE.md`, „Entwickeln und prüfen“).

**Kryptografie ändert man immer auf beiden Seiten:** `src/mobile_crypto.py` und `pwa/crypto.js` müssen byte-genau dasselbe tun (Ableitung, Zusatzdaten, Umschlag). Gemeinsame Testvektoren liegen in `pwa/test/fixtures/crypto-vectors.json`; wer etwas daran ändert, erzeugt sie neu (Skript im Plan `docs/superpowers/plans/2026-10-10-pwa-verschluesselung.md`, Task 1) und lässt beide Testsuiten laufen.

Veröffentlicht wird `pwa/` von `.github/workflows/pages.yml` (Details in der `CLAUDE.md`).

### Relay (`relay/`)

Der Push-Relay ist ein Cloudflare Worker mit einem Durable Object je Handy und sendet die Erinnerungen der Handy-PWA als Web-Push, auch wenn der Desktop aus ist. Wie `pwa/` wird er nicht in die App gebündelt. Modell, Regeln und Grenzen: [`relay/CLAUDE.md`](relay/CLAUDE.md); Einrichtung eines eigenen Relays: [`relay/README.md`](relay/README.md).

```
cd relay && npm ci && node --test
```

Node 22 oder neuer (`engines` in `relay/package.json`). Die Tests brauchen kein `wrangler` und kein Cloudflare-Konto. Die CI führt sie im Job `relay` von `test.yml` aus und prüft dort zusätzlich die Konfiguration mit `wrangler deploy --dry-run` (ohne Token).

**Ausgerollt wird automatisch:** `.github/workflows/relay-deploy.yml` läuft nach einem Merge auf `master`, der etwas unter `relay/` (oder den Workflow) ändert, und führt `npm ci`, `node --test` und `wrangler deploy` aus, danach einen Smoke-Check (`PUT /v1/device` ohne Header muss `401` liefern). Der Job läuft im Environment `relay-production` (nur `master`), das die Secrets `CLOUDFLARE_API_TOKEN` und `CLOUDFLARE_ACCOUNT_ID` trägt. Das ersetzt keinen ersten manuellen Deploy: Worker, workers.dev-Subdomain und die Worker-Secrets (`VAPID_PRIVATE`, `VAPID_SUBJECT`) legt man einmal von Hand an (`relay/README.md`).

**Drei Werte müssen übereinstimmen:** `RELAY_URL` in `pwa/relay-client.js` und `src/push_relay.py` (ein Test in `tests/test_push_relay.py` hält beide zusammen) sowie `VAPID_PUBLIC` in `relay/wrangler.toml` und `pwa/relay-client.js` (kein Test; wechseln darf man ihn nie, alle Abos hängen daran).

Zusätzliche Abhängigkeiten, nur für `relay/` (`relay/package.json`, exakt gepinnt): `@block65/webcrypto-web-push` 2.0.0 (Web-Push mit VAPID) und `wrangler` 4.153.0 (Dev-Dependency, Deploy und `wrangler dev`).

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

Nur anfassen, was die Änderung verlangt, und den vorhandenen Stil matchen — eine
Änderung pro PR, nichts „nebenbei“ mitnehmen. `master` ist protected — Merge
erfolgt über PR.

## Commit-Konventionen

- Commit-**Typ** englisch im Conventional-Commits-Stil: `feat:`, `fix:`, `docs:`,
  `ci:`, `refactor:` … Der Body darf deutsch sein.
- Code und Bezeichner englisch; UI-Texte und Konversation deutsch.

## KI-generierter Code

Code, der mit einem LLM-Werkzeug entstanden ist, ist willkommen und unterliegt
denselben Regeln wie alles andere. Dazu kommt, was sich im Umgang damit
bewährt hat:

- **Verantwortung bleibt bei dir.** Wer einen PR öffnet, hat den Diff selbst
  gelesen und kann ihn erklären. Das Werkzeug steht als `Co-Authored-By` im
  Commit, damit die Herkunft nachvollziehbar bleibt.
- **Erst Befund und Design, dann Code.** Bei Features und nicht trivialen Fixes
  wird das Problem zuerst reproduziert oder belegt und der Ansatz kurz
  abgestimmt; größere Vorhaben bekommen Spec und Plan unter `docs/superpowers/`.
  Gibt es noch kein Issue, wird erst eines angelegt, damit der PR es mit
  `Closes #N` schließt.
- **Der Test war sichtbar rot.** Ein Test, der nie fehlgeschlagen ist, beweist
  nichts — erst den Fehler zeigen, dann beheben (Regeln und Zuschnitt: „Tests“
  oben). Die komplette Suite, `ruff check .` und `pyright` laufen **vor** dem
  PR lokal durch; „sollte funktionieren“ zählt nicht.
- **Nichts behaupten, was nicht geprüft ist.** Was sich nicht verifizieren ließ
  (andere Plattform, UI ohne automatisierten Test), steht im PR unter
  „Hinweise“. Betrifft die Änderung nur macOS oder Linux, wird vor dem Merge
  ein Pre-Release dafür vorgeschlagen (siehe [`CLAUDE.md`](CLAUDE.md#plattformspezifische-prs--pre-release-vorschlagen)).
  Das Gleiche gilt für Zahlen, Pfade und Funktionsnamen in Doku und PR-Text:
  gegen den Code prüfen, nicht aus dem Gedächtnis übernehmen.
- **Unabhängige Durchsicht bei größeren Änderungen.** Jemand, der den
  Entstehungskontext nicht kennt (Mensch oder neue Sitzung), liest den Diff.
  Befunde werden einzeln behoben, jeweils mit rotem Test; offene Kleinigkeiten
  stehen im PR.

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
- **Plattform-Labels:** Betrifft ein PR nur macOS oder Linux, trägt er
  `platform:macos` bzw. `platform:linux` — bei KDE- oder GNOME-spezifischem
  Verhalten zusätzlich `platform:kde` bzw. `platform:gnome`. Vor dem Merge
  wird dann ein Pre-Release zum Testen gebaut (Details in `CLAUDE.md`,
  „Plattform-Labels am PR").
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
