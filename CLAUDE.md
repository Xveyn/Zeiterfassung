# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Zeiterfassung – Projekthinweise

Kleines Desktop-Tool zur Zeiterfassung (Tkinter + Python) für Windows, macOS und Linux, das PDF-Berichte erzeugt und per Gmail verschickt.

## Entwicklung

```
pip install -r requirements.txt
python -m src.main          # App aus dem Repo starten
pytest                      # alle Tests
pytest tests/test_storage.py             # eine Datei
pytest tests/test_storage.py::test_name  # einzelner Test
```

Die App muss als Modul gestartet werden (`python -m src.main`), nicht als Script — die Imports innerhalb von `src/` sind absolut (`from src...`).

## Release-Prozess

Releases werden automatisch von `.github/workflows/release.yml` erzeugt, sobald ein PR nach `master` gemerged wird, der ein `release:major`, `release:minor` oder `release:patch` Label trägt.

Ablauf vor dem Merge:
1. `src/version.py` im PR auf die neue Version setzen (z.B. `VERSION = "1.5.0"`).
2. `CHANGELOG.md` im PR aktualisieren.
3. Passendes `release:*` Label am PR setzen (Label steuert nur den Trigger, nicht die Versionsnummer).
4. PR mergen — Workflow liest die Version aus `src/version.py`, bricht ab falls der Tag `vX.Y.Z` bereits existiert, baut das Installer-Exe und veröffentlicht das Release.

Der Workflow pusht **nichts** nach `master`. Versionsbump gehört in den PR.

## Recovery bei teilweise fehlgeschlagenem Release

Wenn der `publish`-Job nach dem Tag-Push fehlschlägt (z.B. `gh release create` Netzwerkproblem), blockiert der Pre-Check beim Re-Run die erneute Ausführung wegen "tag already exists". Ablauf:

1. Tag lokal und remote löschen:
   ```
   git tag -d v<ver>
   git push origin :refs/tags/v<ver>
   ```
2. Workflow im PR unter Actions → „Re-run all jobs" erneut starten.

Alternative: `src/version.py` auf die nächste Patch-Version bumpen und einen neuen Release-PR mergen.

## Branch Protection

`master` ist protected: direkte Pushes erfordern Admin-Bypass. Im Normalfall über PR arbeiten. Für Notfall-Fixes am CI kann der Repo-Owner direkt pushen.

## Build

```
python build.py
```

`build.py` ist ein Plattform-Dispatcher und ruft PyInstaller je nach `platform.system()` unterschiedlich auf. Auf allen drei Plattformen sind `--collect-all xhtml2pdf --collect-all reportlab --collect-all holidays` zwingend — ohne sie schlagen PDF-Erzeugung bzw. Feiertags-Lookup im gebauten Artefakt stumm fehl.

## Cross-Platform Builds

`build.py` ist plattformabhängig:

| Plattform | Voraussetzung | Ausgabe |
|-----------|---------------|---------|
| Windows | Inno Setup 6 unter `%LOCALAPPDATA%\Programs\Inno Setup 6\` | `dist/Zeiterfassung_Setup.exe` |
| macOS | `brew install create-dmg` | `dist/Zeiterfassung-<ver>-arm64.dmg` (CI baut nur Apple Silicon; Intel-Runner `macos-13` hat de-facto unbrauchbare Queue-Zeiten) |
| Linux | `apt install libfuse2` + `appimagetool` auf `$PATH` | `dist/Zeiterfassung-<ver>-<arch>.AppImage` |

Fehlt das Pack-Tool lokal, überspringt `build.py` den Pack-Schritt mit Warnung — der PyInstaller-Build läuft trotzdem durch. Das ist für Local-Dev gewollt.

## Installation & Daten

Installierte App und Benutzerdaten liegen je nach Plattform:

| Plattform | Installation | Benutzerdaten (Entries, Settings, `token.json`, `credentials.json`) |
|-----------|--------------|--------------------------------------------------------------------|
| Windows | `%LOCALAPPDATA%\Programs\Zeiterfassung\` | Gleiches Verzeichnis wie die Exe |
| macOS | `/Applications/Zeiterfassung.app` | `~/Library/Application Support/Zeiterfassung/` |
| Linux | Beliebige AppImage-Datei | `$XDG_DATA_HOME/Zeiterfassung/` (Fallback `~/.local/share/Zeiterfassung/`) |

`src/paths.py::get_base_path` dispatched über `platform.system()` und unterscheidet zwischen Frozen- und Repo-Modus.

## UI-Fehler sichtbar machen

`--noconsole` unterdrückt stderr. Fehler aus dem Sendepfad (Gmail, PDF-Erzeugung) **müssen** per `messagebox.showerror` mit `traceback.format_exc()` angezeigt werden — sonst klickt der Nutzer auf „Senden", nichts passiert, und es gibt keine Spur.

## UTF-8 im Mail-Pipeline

Damit Umlaute/ß nicht als Mojibake ankommen, gelten drei Pflichten:
- HTML-Body: `<meta charset="utf-8">` im `<head>`
- `MIMEText(html, "html", _charset="utf-8")`
- Betreff: `Header(subject, "utf-8")`

## Datumsformat: intern ISO, in der UI deutsch

Gespeichert und intern verarbeitet wird **immer ISO** (`YYYY-MM-DD`,
Timestamps `…THH:MM…`): Storage-Keys, Filter, Sync-Doc, gcal-Payloads,
Update-Throttle. Nicht anfassen — daran hängen Vergleiche und Persistenz.

In der **UI** wird **immer deutsch** angezeigt: Datum `TT.MM.JJJJ`,
Zeitstempel `TT.MM.JJJJ HH:MM`. Dafür gibt es die zentralen Helfer
`src/time_utils.py::format_iso_date` / `format_iso_datetime` (reine
Anzeige-Formatierung, ISO bleibt die Quelle). Neue datumsanzeigende
UI-Stellen über diese Helfer formatieren, nicht roh `isoformat()`/`str()`
ausgeben.

## Kalender-Interaktion: Linksklick speichert, Rechtsklick löscht

Im Kalender gilt ein striktes Modell: **Linksklick** öffnet den Tages-Dialog
zum Anlegen/Bearbeiten (Ist-Zeit *und* Reservierung), **Rechtsklick** löscht.
Rechtsklick löscht nie ohne Bestätigung; liegen an einem Tag Ist-Zeit **und**
Reservierung, fragt ein Checkbox-Dialog (`themed_ask_delete_choice`), was
gelöscht wird. Gebunden an `<Button-3>` auf allen Zelltypen
(`src/ui.py::_delete_day`, für Eintrags-, Leer- und Feiertagszellen).

Der Tages-Dialog (`src/dialogs/entry_dialog.py`) ist deshalb bewusst **rein
zum Speichern** — er hat **keine** Lösch-Buttons.

Das gilt auch für die Multi-Slot-Zeilen: das per-Zeile-**×** erscheint **nur an
neu hinzugefügten, noch nicht gespeicherten** Slots (über „+ Slot"). Bereits
gespeicherte Ist-/Reservierungs-Slots tragen **kein ×** — sie lassen sich im
Dialog editieren/überschreiben, aber **nicht löschen**. Löschen gespeicherter
Slots läuft ausschließlich über den Rechtsklick im Kalender (mit Slot-Auswahl).
Gesteuert über den `removable`-Parameter von `add_ist_row`/`add_res_row`.

**Plattform-Ausnahme macOS:** Tkinters Maustasten-Nummerierung macht den
Rechtsklick (`<Button-3>`) auf macOS unzuverlässig (Sekundärklick ist je nach
Tk-Version `<Button-2>` bzw. Control-Klick). Damit Löschen auf dem Mac
erreichbar bleibt, zeigt die Tageszelle **dort** ein kleines ✕ oben links,
sobald der Tag löschbare Einheiten hat (Ist-Zeit oder aktive Reservierung).
Der ✕-Button löst denselben Lösch-Pfad wie der Rechtsklick aus
(`App._delete_day` inkl. Bestätigung/Slot-Auswahl). Gesteuert über
`_should_show_delete_button` (`theme.py`) + `App._add_delete_button` (`ui.py`).
Der Tages-Dialog hat auf **allen** Plattformen keine Lösch-Buttons. Auf
Windows/Linux ist Löschen ausschließlich der Rechtsklick.

Neue Lösch-/Rechtsklick-Stellen müssen dieses Modell einhalten (kein zweiter
Lösch-Pfad im Linksklick-Dialog auf Win/Linux).

## Tests / CI

`.github/workflows/test.yml` installiert gezielt nur die Pakete, die die Tests brauchen (`pytest`, `holidays==0.99`, `google-api-python-client`, `google-auth`, `google-auth-oauthlib`), **nicht** `requirements.txt`. Grund: `pycairo` (transitive Dep von `xhtml2pdf`) braucht Cairo-Systemheader auf Ubuntu und bricht sonst den CI-Build. Der Import von `xhtml2pdf` in `src/report.py::generate_pdf` ist lazy, daher laufen die Report-Tests ohne die Lib. `holidays` und die Google-Libs sind pure Python ohne C-Deps und problemlos installierbar — letztere sind nötig, weil Tests `src.ui` importieren (z.B. `tests/test_ui_delete.py`), dessen Importkette die Google-Wrapper zieht. Ein zweiter Job läuft `ruff check .` (Lint).

Lokal: `pytest` aus dem Repo-Root. Alle Tests müssen vor dem PR-Merge grün sein.

## Struktur

> Detaillierte Architektur-Referenz (Schichten, App-Komponenten, Verträge,
> Threading-Modell): **`src/CLAUDE.md`** — bei Verantwortlichkeits-Änderungen
> mitpflegen.

- `src/main.py` — Einstiegspunkt; baut `Tk`-Root, instanziert `Storage`/`Settings`/`App`, behandelt `--minimized`
- `src/ui.py` — Tkinter-GUI; `App` ist schlanker Koordinator über `GridRenderer`/`BackgroundTaskRunner`/`SyncOrchestrator`/`UpdateBanner` (siehe `src/CLAUDE.md`)
- `src/dialogs/` — Modal-Dialoge (`entry_dialog`, `send_dialog`, `settings_dialog`)
- `src/storage.py` — JSON-Persistenz der Zeiteinträge (Schlüssel: ISO-Datum)
- `src/settings.py` — Benutzereinstellungen mit Defaults
- `src/report.py` — HTML-Mail und PDF (dark/light Theme), gruppiert pro ISO-Kalenderwoche; `xhtml2pdf`-Import ist **lazy** in `generate_pdf` (siehe Tests/CI)
- `src/mail.py` — Gmail-API-Wrapper (OAuth2, `token.json` / `credentials.json`)
- `src/drive.py` — Google-Drive-API-Wrapper für den Multi-Device-Sync (`appDataFolder`, Scope `drive.appdata`)
- `src/sync.py` — Sync-Engine (pure Logik: LWW-Merge der Entries/Settings, Konflikterkennung); importiert `SYNCED_SETTING_KEYS` aus `settings.py` (Single Source of Truth, nicht hier neu definieren)
- `src/conflicts_store.py` — lokale JSON-Persistenz der Sync-Konfliktliste
- `src/share.py` — Export/Import von Arbeitszeiten als Share-JSON (Teilen per Mail-Anhang)
- `src/reservations.py` — Reservierungen (zukünftige Soll-Zeiten, eigenes Konzept neben Ist-Zeiten)
- `src/reservations_sync.py` — Abgleich der Reservierungen mit einem Google Kalender
- `src/gcal.py` — Google-Calendar-API-Wrapper (lazy Imports wie `drive.py`, wegen CI ohne `requirements.txt`)
- `src/tray.py` — Infobereich-Icon (Minimize-to-Tray); Plattform-Fassade über pystray (Windows) und `tray_mac.py` (macOS)
- `src/tray_mac.py` — natives macOS-Tray (NSStatusItem, Main-Thread) als Backend von `tray.py`; macOS-Tray ist bis zum Mac-Gate dormant (Opt-in `ZEIT_MACOS_TRAY=1`, #88)
- `src/time_utils.py` — Stundenberechnung, KW-Labels
- `src/holidays_de.py` — Feiertags-Lookup (über `holidays`-Lib)
- `src/paths.py` — `get_base_path()` dispatched über `platform.system()` und Frozen- vs. Repo-Modus
- `src/autostart.py` — plattformabhängiger Autostart (Windows-Shortcut / macOS-LaunchAgent / Linux `.desktop`)
- `src/updater.py` — GitHub-Releases-Check (stdlib-only, gedrosselt 1×/Tag)
- `src/platform_open.py` — `os.startfile`/`open`/`xdg-open`-Wrapper
- `src/logging_setup.py` — File-Logging + globaler Excepthook (Setup-Fehler sind **nicht-fatal**, siehe `main.py`)
- `src/theme.py`, `src/tooltip.py` — UI-Hilfen
- `src/version.py` — Einzige Quelle für die App-Version (von Workflow & `installer.iss` gelesen)
- `installer.iss` — Inno Setup Script, Version wird per `/DAppVer=...` vom Workflow übergeben

Hinweis: Es gibt **keine** `Zeiterfassung.spec`-Datei (entgegen der README-Erwähnung) — Build läuft komplett über `build.py` mit expliziten PyInstaller-Args.
