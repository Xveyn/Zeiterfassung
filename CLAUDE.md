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

### Pre-Releases (plattformübergreifende Test-Builds)

Für plattformübergreifendes Testen des Stands **nach** dem letzten echten Release gibt es Pre-Releases:
Actions → Workflow **Release** → „Run workflow" mit gesetztem Häkchen
**prerelease** (Branch egal, gebaut wird der gewählte Ref). Ablauf:

- Baut dieselben drei Artefakte (Windows/macOS-arm/Linux) wie ein echtes Release,
  aber gestempelt mit `CHANNEL=prerelease` → In-App-Titel zeigt `X.Y.Z-pre.N`
  (Nummer aus dem Build-Stempel, s.u.).
- Tag ist **fortlaufend** `vX.Y.Z-pre.N` (N automatisch hochgezählt je Zielversion,
  aus `src/version.py`). Das echte `vX.Y.Z` existiert zu diesem Zeitpunkt bereits:
  der Pre-Release trägt die Version des **letzten** Releases und enthält den Stand
  danach (siehe Reihenfolge-Regel unten). Kollidieren kann er mit ihr nicht.
- GitHub-Release wird als **Pre-Release** markiert (`--prerelease`): der Auto-Updater
  liest `/releases/latest` und **ignoriert** Pre-Releases → normale Nutzer bekommen
  sie nicht als Update angeboten.
- **Opt-in im Updates-Tab:** Wer die Einstellung „Auch Vorabversionen
  (Pre-Releases) anbieten" aktiviert, bekommt Pre-Releases im Updates-Tab
  angezeigt und als Toast/Banner gemeldet (`updater.check_for_update` fragt
  dann `/releases` statt `/releases/latest`). Die Einstellung ist gerätelokal
  (nicht in `SYNCED_SETTING_KEYS`).
- **Reihenfolge-Regel (wichtig, vom Workflow erzwungen):** Ein Pre-Release wird
  **immer nach** dem gleichnamigen echten Release gebaut, aus neuerem Code. Die
  App ordnet entsprechend `X.Y.Z < X.Y.Z-pre.1 < X.Y.Z-pre.2 < X.Y.Z+1`
  (`version.parse_release_id`) — die Umkehrung der Semver-Regel, aber die Praxis
  hier. Der `pre-check`-Job bricht deshalb ab, wenn `v<VERSION>` aus
  `src/version.py` **noch nicht** existiert: erst `version.py` bumpen und dann
  einen Pre-Release bauen würde die Annahme umdrehen — die App böte
  Opt-in-Nutzern nach dem echten Release dauerhaft den älteren Pre an, ohne
  Selbstheilung. Wer die Reihenfolge künftig bewusst ändert, muss beides
  mitziehen: die Ordnung in `version.parse_release_id` **und** dieses Gate.
- **Build-Stempel:** `release.yml` reicht den berechneten Tag als
  `ZEIT_RELEASE_TAG` an die Build-Jobs; `build.py` schreibt ihn als
  `RELEASE_TAG` nach `src/build_info.py`. Daraus kennt die App ihre exakte
  Identität (`version.installed_release_id()`) und zeigt im Titel
  `X.Y.Z-pre.N` statt nur `X.Y.Z-pre`. Fehlt der Stempel (Alt-Build, Dev-Modus),
  gilt die reine `VERSION`.
- **Kein Versionsbump, kein CHANGELOG, kein Label** nötig. Die Release-Notes werden
  wie beim echten Release automatisch aus den PRs generiert (`--generate-notes`),
  kumulativ seit dem letzten **echten** Release.

Manuelles „Run workflow" **ohne** das prerelease-Häkchen baut wie bisher ein echtes
Voll-Release (Tag `vX.Y.Z`).

## Recovery bei teilweise fehlgeschlagenem Release

Scheitert `gh release create` selbst (Netzwerkproblem, Rate-Limit), räumt der
`publish`-Job seit Audit N26 **automatisch auf**: ein eventuell halb angelegtes
Release wird entfernt, dann der bereits gepushte Tag gelöscht, dann bricht der
Job ab. Ein „Re-run all jobs" läuft danach sauber durch — der Pre-Check findet
keinen Tag mehr vor.

Von Hand nachräumen muss man nur, wenn der Job **zwischen** Tag-Push und
Rollback stirbt (Runner-Abbruch, Cancel, Timeout) — dann blockiert der
Pre-Check den Re-Run wegen „tag already exists":

1. Tag lokal und remote löschen:
   ```
   git tag -d v<ver>
   git push origin :refs/tags/v<ver>
   ```
2. Workflow im PR unter Actions → „Re-run all jobs" erneut starten.

Alternative: `src/version.py` auf die nächste Patch-Version bumpen und einen neuen Release-PR mergen.

## Branch Protection

`master` ist protected: direkte Pushes erfordern Admin-Bypass. Im Normalfall über PR arbeiten. Für Notfall-Fixes am CI kann der Repo-Owner direkt pushen.

## Plattformspezifische PRs — Pre-Release vorschlagen

Entwickelt wird primär unter Windows; macOS und Linux (inkl. Desktop-Umgebungs-
Spezialfälle wie KDE, siehe #42) sind vollwertige Zielplattformen, aber auf der
Windows-Dev-Maschine nicht direkt verifizierbar. Betrifft ein PR Code, der sich
nur auf macOS, Linux oder eine bestimmte Linux-Desktop-Umgebung auswirkt (z. B.
`src/tray_mac.py`, plattformspezifische Zweige in `theme.py`/`grid_renderer.py`/
`autostart.py`), soll vorgeschlagen werden, vor dem Merge einen Pre-Release zu
triggern, damit die Änderung dort getestet werden kann — statt das erst beim
nächsten regulären, für diese Plattform dann faktisch ungetesteten Release zu
bemerken. Vorbild: das manuelle macOS-Gate in #96. PR-Plattform-Labels und der
Pre-Release-Workflow selbst sind als #100 bzw. #99 vorgeschlagen, aber noch
nicht umgesetzt — bis dahin gilt der Hinweis als Review-Empfehlung, nicht als
automatisierter Check.

## Build

```
python build.py
```

`build.py` ist ein Plattform-Dispatcher und ruft PyInstaller je nach `platform.system()` unterschiedlich auf. Auf allen drei Plattformen sind `--collect-all xhtml2pdf --collect-all reportlab --collect-all holidays` zwingend — ohne sie schlagen PDF-Erzeugung bzw. Feiertags-Lookup im gebauten Artefakt stumm fehl.

**Windows und macOS bauen `--onedir`, Linux `--onefile`.** Onefile entpackt bei
jedem Start alle DLLs frisch in einen `_MEIxxxxxx`-Tempordner; dieses Zeitfenster
war die Wurzel einer intermittierenden Fehlerklasse (Bootloader lädt
`python310.dll` transient nicht → #118; `holidays` fand `de.mo` transient nicht →
#116; der Skalierungs-Neustart musste den `_MEIPASS`-Erbgang per
`PYINSTALLER_RESET_ENVIRONMENT` umgehen, siehe `ui.py`). Onedir legt Exe +
`_internal\` einmalig entpackt ab — kein Extraktions-Race pro Start. `installer.iss`
shippt entsprechend den ganzen `dist\Zeiterfassung\`-Ordner (nicht nur die Exe);
die Exe bleibt `{app}\Zeiterfassung.exe`, `get_base_path()=dirname(exe)` und alle
Autostart-/Single-Instance-Pfade bleiben damit unverändert. Linux bleibt onefile,
weil die AppImage ohnehin selbst mountet (onefile darin wäre Doppelpackung) und
`#118` Windows-spezifisch ist.

## Cross-Platform Builds

`build.py` ist plattformabhängig:

| Plattform | Voraussetzung | Ausgabe |
|-----------|---------------|---------|
| Windows | Inno Setup 6 unter `%LOCALAPPDATA%\Programs\Inno Setup 6\` | `dist/Zeiterfassung_Setup.exe` |
| macOS | `brew install create-dmg` | `dist/Zeiterfassung-<ver>-arm64.dmg` (CI baut nur Apple Silicon; Intel-Runner `macos-13` hat de-facto unbrauchbare Queue-Zeiten) |
| Linux | `apt install libfuse2` + `appimagetool` auf `$PATH` | `dist/Zeiterfassung-<ver>-<arch>.AppImage` |

Fehlt das Pack-Tool lokal, überspringt `build.py` den Pack-Schritt mit Warnung — der PyInstaller-Build läuft trotzdem durch. Das ist für Local-Dev gewollt.

## Manueller CI-Build ohne Release (`build.yml`)

Für einen reinen Test-Build eines Branches — **ohne** Tag, Release oder
Auto-Update-Effekt — gibt es den Workflow **Build** (`.github/workflows/build.yml`):
Actions → **Build** → „Run workflow". Er baut in **CI-identischer Umgebung**
(Python 3.10 + gepinnte `requirements.txt`), sodass man einen Stand verifizieren
kann, ohne eine lokale venv zu pflegen, die zur CI divergiert (Vorbild für das
Divergenz-Problem: der lokale Frozen-Build scheiterte auf Python 3.13/3.14 an
fehlenden gebündelten Datendateien — die CI auf 3.10 spiegelt die echte
Release-Umgebung).

- **Inputs:** `windows`/`macos`/`linux` als Häkchen (mindestens eins, maximal
  alle; Default nur Windows) + optionaler `ref` (Branch/Tag/SHA; leer = der
  Branch, aus dem der Lauf startet).
- **Ausgabe = reine App** (kein Installer): `build.py` läuft ohne Inno Setup /
  create-dmg / appimagetool, überspringt also den Pack-Schritt und lädt die
  nackte PyInstaller-Ausgabe als **Workflow-Artefakt** hoch — Windows den
  `dist\Zeiterfassung\`-Ordner (onedir: Exe + `_internal\`, von `upload-artifact`
  gezippt), macOS `Zeiterfassung.app` und Linux-Binary als `.tar.gz`
  (tar bewahrt Symlinks/Exec-Bits, die ein Zip zerstören würde). `retention-days: 14`.
- **Kanal-Stempel:** kein `ZEIT_RELEASE`/`ZEIT_PRERELEASE` → `build.py` stempelt
  `CHANNEL=dev` + Commit-SHA; der In-App-Titel zeigt damit den exakt gebauten Commit.
- **Abgrenzung zum (Pre-)Release:** `build.yml` erzeugt **keinen** Tag und
  **kein** GitHub-Release. Wer testbare, installierbare Artefakte (Setup.exe/DMG/
  AppImage) oder einen plattformübergreifenden Vorab-Stand für andere Nutzer will,
  nimmt weiter den **Pre-Release** aus `release.yml` (s. „Release-Prozess").

**Default-Branch-Eigenheit:** `workflow_dispatch` ist erst dispatchbar, wenn
`build.yml` auf dem **Default-Branch** (`master`) liegt — vorher liefert
`gh workflow run build.yml …` ein `HTTP 404: workflow not found on the default
branch`, und der „Run workflow"-Knopf fehlt. Solange der Workflow nur auf einem
Feature-Branch existiert, lässt er sich ausschließlich aus diesem Branch heraus
starten (in der Actions-UI den Branch im „Run workflow"-Dropdown wählen). Der
`ref`-Input entfaltet seinen Nutzen — einen *beliebigen* Branch bauen, der
`build.yml` selbst nicht trägt — daher erst nach dem Merge nach `master`.

## Abhängigkeiten & Pinning

Die **direkten** Abhängigkeiten in `requirements.txt` sind exakt (`==`) auf
known-good Versionen gepinnt — für reproduzierbare Release-Builds (Audit M17).
Jede gepinnte Version muss **Python 3.10** unterstützen (CI- und Release-Python;
per PyPI `requires_python` prüfen). Beim Bump also die neue Version gegen 3.10
gegenchecken, nicht blind auf „latest" gehen.

**Transitive** Deps (u. a. `reportlab` via `xhtml2pdf`) sind bewusst **nicht**
gepinnt — kein Lockfile, keine Hashes. Wer eine direkte Dep hinzufügt, pinnt sie
`==` und ergänzt sie in der README-Abhängigkeiten-Tabelle.

`release.yml` installiert `-r requirements.txt` plus das reine Build-Tooling
`pip-licenses==5.5.5` (erzeugt `THIRD-PARTY-NOTICES.txt`). PyInstaller kommt
gepinnt aus `requirements.txt` — **nicht** zusätzlich auf die Install-Zeile
setzen (sonst floatet es wieder).

**Änderungen an der Dependency-Auflösung des Release-Builds** (Pins, Install-
Zeilen) sind auf der Windows-Dev-Maschine nur für Windows verifizierbar → vor
dem nächsten echten Release einen **Pre-Release** über alle drei Plattformen
bauen (siehe „Plattformspezifische PRs — Pre-Release vorschlagen").

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

### Bekannt-themed / unerwartet-nativ (bewusste Zweiteilung, Audit N14)

Für Fehlerdialoge gilt eine bewusste Aufteilung:

- **Bekannte, erwartete Fehler** (Validierung, „Keine Einträge", „Ungültiger
  Zeitraum", ein gehandhabter Speicher-`OSError`) → die **themed** Drop-ins
  aus `theme.py` (`themed_showerror`/`themed_showinfo`/…). Kurze, kuratierte
  Meldung, konsistentes Dark-Theme.
- **Unerwartete Fehler** (die generischen `except`-Zweige, die
  `traceback.format_exc()` bzw. ein `result["tb"]` mitzeigen) →
  **rohes `tkinter.messagebox.showerror`**. Bewusst nativ und nicht themed:
  ein themed Dialog baut selbst Tk-Toplevels/Widgets auf und könnte im bereits
  gestörten Zustand seinerseits scheitern und damit genau die Fehlermeldung
  verschlucken, die er zeigen soll. Der native Dialog ist die robuste
  Fallback-Schicht (siehe auch die `messagebox.showerror`-Pflicht oben).

Neue Fehlerpfade dieser Konvention folgen: kuratierte Meldung → themed;
Traceback-/Catch-all-Ausgabe → nativ.

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

## Stunden: intern dezimal, angezeigt in Minuten — Summen NUR über Minuten

`calculate_hours` liefert **Dezimalstunden** und rundet dabei **pro Slot** auf
2 Nachkommastellen. Das ist gröber als eine Minute (0,01 h = 0,6 min) — solche
Werte sind als Zwischenergebnis brauchbar, als Grundlage einer *angezeigten
Summe* aber nicht.

Angezeigt wird **immer** über die Minuten-Auflösung: `hours_to_minutes` ist die
einzige Stelle, an der Dezimalstunden auf Minuten gerundet werden;
`format_minutes_hm` (`7 h 30 min`) und `format_hours_colon` (`7:30`) bauen
darauf auf.

**Die Regel:** Wer mehrere angezeigte Werte aufsummiert, summiert deren
**Minuten** — niemals die Dezimalstunden, um erst am Ende zu runden. Sonst
rundet man an zwei Stellen unabhängig voneinander, und die Summe weicht von
dem ab, was der Nutzer in den Einzelposten sieht (bei einem typischen Monat in
~83 % der Fälle um mindestens eine Minute; genau dieser Bug steckte im Footer,
s. `GridRenderer._display_minutes`). Geldbeträge aus derselben Minuten-Summe
ableiten, nicht aus den Dezimalstunden — sonst widersprechen sich Stunden- und
Euro-Anzeige.

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

## Dialog-Styling: ein gemeinsames Theme

Alle Dialoge (modal wie nicht-modal) teilen sich dasselbe Dark-Theme aus
`src/theme.py` — Drop-ins für die `tkinter.messagebox`-Familie
(`themed_showinfo`/`themed_showwarning`/`themed_showerror`,
`themed_askyesno`, `themed_ask_delete_choice`) sowie die Fenster-Chrome-
Helfer (`apply_dark_titlebar`, `disable_min_max`, `apply_app_icon`,
`center_dialog_on_parent`). Neue Dialoge nutzen diese Helfer statt
`tkinter.messagebox`/eigenem Ad-hoc-Styling, und bekommen **keine**
dialogspezifischen Stil-Extras (Farbakzente, abweichende Fonts o.ä.) ohne
Rücksprache — das Theme bleibt bewusst einheitlich über alle Dialoge hinweg,
nicht pro Dialog individualisiert.

Neue Dialoge entstehen über `theme.create_dialog(parent, title, …)` —
nicht über handgebaute `Toplevel`-Boilerplate; der Helfer setzt die
komplette Fenster-Chrome (BG, dunkle Titelleiste, disable_min_max,
App-Icon, modal/Escape) konventionskonform. `center_dialog_on_parent`
nach dem Widget-Aufbau bleibt Aufgabe des Dialogs.

**Bekannte, akzeptierte Einschränkung — kurzes Aufblitzen der hellen
Windows-Titelleiste:** `apply_dark_titlebar`/`disable_min_max` sind bewusst
per `window.after(100, …)` verzögert (s. Kommentar dort — frühere Tk-eigene
Fenster-Property-Calls würden das DWM-Farb-Attribut sonst clobbern). In
diesem ~100ms-Fenster rendert Windows die Titelleiste kurz im hellen
Standard-Stil, bevor sie umgefärbt wird. Versuch, das Fenster bis dahin per
`-alpha 0.0` unsichtbar zu halten (reine Compositing-Deckkraft statt
`withdraw`/`deiconify`, um `grab_set()` nicht zu gefährden): macht auf
diesem Windows/Tk-Gespann `center_dialog_on_parent` dauerhaft kaputt — ein
frisch erzeugtes Toplevel, das direkt `-alpha 0.0` bekommt, ignoriert
spätere `geometry()`-Aufrufe komplett (auch ein zweiter Zentrier-Aufruf
nach dem Sichtbarmachen bringt die Position nicht zurück, Dialog landet bei
`+0+0` bzw. einem falschen Offset). Tieferer Windows/DWM-Layered-Window-
Effekt, kein einfacher Timing-Bug — daher bewusst nicht gefixt; das
Flackern ist als Kompromiss akzeptiert. Vor einem neuen Versuch: das oben
beschriebene Verhalten reproduzieren und gegenchecken, ob es (in einer
neueren Tk/Python-Version) noch auftritt.

## Tests / CI

`.github/workflows/test.yml` installiert gezielt nur die Pakete, die die Tests brauchen — gepinnt in **`requirements-test.txt`** (`pytest`, `holidays`, `google-api-python-client`, `google-auth`, `google-auth-oauthlib`), **nicht** `requirements.txt`. Grund: `pycairo` (transitive Dep von `xhtml2pdf`) braucht Cairo-Systemheader auf Ubuntu und bricht sonst den CI-Build. Der Import von `xhtml2pdf` in `src/report.py::generate_pdf` ist lazy, daher laufen die Report-Tests ohne die Lib. `holidays` und die Google-Libs sind pure Python ohne C-Deps und problemlos installierbar — letztere sind nötig, weil Tests `src.ui` importieren (z.B. `tests/test_ui_delete.py`), dessen Importkette die Google-Wrapper zieht.

Die Test-Deps sind **exakt gepinnt** (Audit N25) — beim Bump gegen Python 3.10 gegenchecken (alle rein-Python, daher auf jedem Matrix-Python installierbar). Jobs (alle mit `cache: pip` auf `requirements-test.txt`):

- **test-matrix** — Matrix über **Python 3.10–3.13** (README: „3.10+"), `fail-fast: false`.
- **test** — schlankes Sammel-Gate über `test-matrix`, das **nur** der Branch
  Protection dient: ein Matrix-Job meldet seine Check-Contexts ausschließlich
  mit Suffix (`test-matrix (3.10)` …), ein Context namens `test` entstünde nie mehr —
  der Required Check bliebe ewig „pending" und jeder PR dauerhaft blockiert.
  Nicht entfernen oder umbenennen, ohne die Required Checks mitzuziehen. Prüft
  `needs.test-matrix.result` explizit unter `if: always()`, weil ein
  übersprungener Required Check GitHub sonst als erfüllt gilt.
- **coverage** — `pytest --cov=src` (ubuntu/3.10); Reporting, **kein** `fail_under`-Gate (Config: `pyproject.toml [tool.coverage]`, Audit N24).
- **test-macos** / **test-windows** — Plattform-Verifikation (je 3.10; macOS zieht zusätzlich `pyobjc-framework-Cocoa`).
- **lint** — `ruff check .`. **typecheck** — `pyright` (gepinnt `1.1.411`).

Lokal: `pytest` aus dem Repo-Root (Coverage: `pytest --cov=src --cov-report=term-missing`). Alle Tests müssen vor dem PR-Merge grün sein.

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
- `src/sync.py` — Sync-Engine (pure Logik: LWW-Merge der Entries/Settings, Konflikterkennung); importiert `SYNCED_SETTING_KEYS` aus `settings.py` (Single Source of Truth, nicht hier neu definieren); `validate_remote_doc` prüft ein Remote-Doc auf die Merge-Invarianten vor dem Merge (Audit M5)
- `src/sync_journal.py` — Crash-Recovery für `sync.apply_merged_doc` via Write-Ahead-Journal (`sync-apply.journal`); beim Start holt `recover_pending_apply` einen unvollständigen Apply idempotent nach (Audit M6)
- `src/sync_history.py` — persistenter „hat je gesynct/abgeglichen"-Marker (`sync_history.json`, write-once, stdlib-only); vetoed den N6-Startup-Sweep gegen einen settings.json-Reset (M4), damit ein gesyncter Rechner nicht fälschlich seine Tombstones verliert (Resurrection)
- `src/conflicts_store.py` — lokale JSON-Persistenz der Sync-Konfliktliste
- `src/share.py` — Export/Import von Arbeitszeiten als Share-JSON (Teilen per Mail-Anhang)
- `src/reservations.py` — Reservierungen (zukünftige Soll-Zeiten, eigenes Konzept neben Ist-Zeiten)
- `src/reservations_sync.py` — Abgleich der Reservierungen mit einem Google Kalender
- `src/reminders.py` — pure Fälligkeits-Logik für Reservierungs-Erinnerungen (Tk-frei); `src/reminder_scheduler.py` — periodischer Reminder-Poll (root.after) → Toast über Tray
- `src/send_reminder.py` — pure Fälligkeits-Logik für den monatlichen Sende-Reminder (Tk-frei), Tag im Monat auf die tatsächliche Monatslänge geclamped; `src/send_reminder_scheduler.py` — periodischer Poll (root.after) → Toast über Tray, Fired-Zustand persistiert in Settings (einmal pro Monat, auch über Neustarts hinweg)
- `src/weekly_limit.py` — Wochenstunden-Limit für einen konfigurierbaren Zeitraum (Werkstudenten-Privileg, #98); pure Logik, zählt nur Ist-Zeiten (nicht Reservierungen)
- `src/pause_requirement.py` — Pausenpflicht-Warnung nach §4 ArbZG (30 Min ab >6h, 45 Min ab >9h Netto-Arbeitszeit); pure Logik, zählt nur die `pause`-Felder der Slots eines Tages (keine Lücken zwischen mehreren Slots); Default aktiv (`pause_warning_enabled`, im Gegensatz zum Werkstudenten-Limit kein Sonderfall-Opt-in, da die Pflicht für praktisch alle Angestellten in DE gilt)
- `src/gcal.py` — Google-Calendar-API-Wrapper (lazy Imports wie `drive.py`, wegen CI ohne `requirements.txt`)
- `src/tray.py` — Infobereich-Icon (Minimize-to-Tray); Plattform-Fassade über pystray (Windows) und `tray_mac.py` (macOS)
- `src/tray_mac.py` — natives macOS-Tray (NSStatusItem, Main-Thread) als Backend von `tray.py`; macOS-Tray ist bis zum Mac-Gate dormant (Opt-in `ZEIT_MACOS_TRAY=1`, #88)
- `src/time_utils.py` — Stundenberechnung, KW-Labels
- `src/holidays_de.py` — Feiertags-Lookup (über `holidays`-Lib)
- `src/paths.py` — `get_base_path()` dispatched über `platform.system()` und Frozen- vs. Repo-Modus
- `src/autostart.py` — plattformabhängiger Autostart (Windows-**Registry** HKCU Run, gleicher Wertname `Zeiterfassung` wie `installer.iss` → strukturell ein Eintrag; macOS-LaunchAgent / Linux `.desktop`). `is_autostart_enabled()` liest den echten Zustand, `migrate_legacy_autostart()` überführt Alt-Startup-Shortcuts frozen-gated in die Registry
- `src/single_instance.py` — Tk-freier Single-Instance-Guard (pro-Nutzer-Localhost-Port, `acquire`/`serve`/`release`); verhindert parallele Instanzen und holt bei manuellem Zweitstart das vorhandene Fenster nach vorn (SHOW), beim Autostart-Doppelfeuer ohne Fenster-Pop (PING)
- `src/device_id.py` — stabile, hardware-abgeleitete Geräte-ID für den Sync (Windows `MachineGuid` / macOS `IOPlatformUUID` / Linux `/etc/machine-id`, SHA-256-gehasht); nur für installierte Builds (`main.py::_ensure_device_id`, gated auf `sys.frozen`) — Repo-/Skript-Modus bleibt bei der alten, in `settings.json` persistierten Zufalls-UUID, damit eine parallel laufende Dev-Instanz nie dieselbe device_id wie eine echte Installation auf demselben Rechner bekommt
- `src/updater.py` — GitHub-Releases-Check (stdlib-only, Check-Häufigkeit über `update_check_frequency` konfigurierbar, Default 1×/Tag; Pre-Releases optional über `prerelease_updates_enabled`, s. Release-Prozess); `src/changelog.py` — lädt und parst den Changelog-Abschnitt einer Release-Version vom GitHub-Tag (stdlib-only)
- `src/platform_open.py` — `os.startfile`/`open`/`xdg-open`-Wrapper
- `src/logging_setup.py` — File-Logging + globaler Excepthook (Setup-Fehler sind **nicht-fatal**, siehe `main.py`)
- `src/theme.py`, `src/tooltip.py` — UI-Hilfen
- `src/version.py` — Einzige Quelle für die App-Version (von Workflow & `installer.iss` gelesen); ordnet Release-Kennungen (`parse_release_id`, `X.Y.Z[-pre.N]`) und kennt die Build-Identität (`installed_release_id` aus dem `RELEASE_TAG`-Stempel)
- `installer.iss` — Inno Setup Script, Version wird per `/DAppVer=...` vom Workflow übergeben.
  `AppMutex=ZeiterfassungAppMutex` (muss exakt zu `main.py::_APP_MUTEX_NAME` passen) lässt Setup
  eine laufende Instanz erkennen und den User per Retry-Dialog zum manuellen Schließen auffordern;
  `CloseApplications=no` schaltet bewusst den Default-Weg (Restart Manager) ab, der bei aktivem
  Minimize-to-Tray scheitert (`App._on_close` behandelt das dabei gesendete `WM_CLOSE` nur als
  Fenster-Verstecken, der Prozess läuft weiter und blockiert die .exe-Datei)

Hinweis: Es gibt **keine** `Zeiterfassung.spec`-Datei — Build läuft komplett über `build.py` mit expliziten PyInstaller-Args.
