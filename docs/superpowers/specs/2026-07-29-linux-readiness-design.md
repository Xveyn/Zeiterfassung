# Design: Linux-Readiness (Asset-Pfad, Autostart-Selbstheilung, Menüeintrag)

Ergänzt `2026-07-29-linux-sni-tray-design.md`. Das SNI-Tray ist dort vollständig
beschrieben; hier geht es um die drei Dinge, die eine AppImage-Installation
darüber hinaus braucht, damit sie auf einem Linux-Desktop wie eine installierte
Anwendung funktioniert — inklusive einer Voraussetzung, ohne die das Tray-Gate
gar nicht bestehen kann.

## Problem

Drei getrennte Befunde, alle Linux-spezifisch, alle aus dem Code abgeleitet und
gegen das installierte Windows-Artefakt gegengeprüft.

### 1. Gebündelte Assets sind zur Laufzeit nicht erreichbar (blockiert das Tray-Gate)

Jeder Icon-Zugriff im Repo geht über `os.path.join(base_path, "assets", …)` —
`tray_linux.icon_pixmaps`, `tray_linux._notify`, `tray.py::_load_image`,
`tray_mac`, `theme.apply_app_icon`, `ui.py`. `base_path` ist überall
`paths.get_base_path()`.

Das ist plattformabhängig aber etwas völlig anderes:

| Plattform | `get_base_path()` | enthält `assets/`? |
|-----------|-------------------|--------------------|
| Windows (installiert) | `%LOCALAPPDATA%\Programs\Zeiterfassung\` | **ja** (am Artefakt verifiziert: sowohl im Root als auch unter `_internal\`) |
| macOS (installiert) | `~/Library/Application Support/Zeiterfassung/` | **nein** |
| Linux (AppImage) | `$XDG_DATA_HOME/Zeiterfassung/` | **nein** |

`build.py` legt die Assets per `--add-data` nach `sys._MEIPASS` und das Icon
zusätzlich nach `$APPDIR/margenheld-icon.png` — beides **innerhalb** des
AppImage-Mounts. Kein Modul liest `sys._MEIPASS`, nichts kopiert `assets/` ins
Datenverzeichnis (per Grep über alle `.py` geprüft).

Auf Windows fallen Nutzerdaten- und Bundle-Verzeichnis zufällig zusammen,
deshalb ist es nie aufgefallen. Auf Linux liefert `icon_pixmaps()` damit eine
leere Liste, während `IconName` bewusst `""` zurückgibt: das SNI-Item hätte
weder Pixmap noch Theme-Namen, und Plasma bekäme nichts zu zeichnen. Das erste
Kriterium des manuellen Gates („Icon erscheint im Systemabschnitt") würde
fehlschlagen, mit der Ursache in `paths.py` statt in `tray_linux.py`.

macOS ist von demselben Befund betroffen — aber anders als beim Linux-Tray
nicht hinter einem dormanten Feature verborgen: der Tray dort ist dormant
(#88), aber `theme.apply_app_icon` läuft auf macOS bei **jedem** Dialog und
`ui._setup_window_icon` bei **jedem** Start, beide ohne Opt-in-Flag. Beide
gingen bisher auf macOS ins Leere (leeres `get_base_path()`), weil sie nichts
fanden — mit `get_resource_path()` finden sie ab sofort etwas und laden
tatsächlich ein `PhotoImage`. Dass es bisher niemand gesehen hat, liegt daran,
dass diese Änderung schlicht neu ist, nicht daran, dass der Pfad dormant wäre.

### 2. Autostart überlebt kein Update

`autostart.resolve_autostart_target` pinnt unter Linux `os.environ["APPIMAGE"]`
— den absoluten Pfad zur AppImage-Datei zum Zeitpunkt des Einschaltens.
`updater.pick_asset_url` erwartet als Linux-Asset
`Zeiterfassung-<version>-x86_64.AppImage`, also **einen versionierten
Dateinamen pro Release**. Die App ersetzt sich nie selbst: `update_banner.
_open_download` öffnet nur den Browser (bewusste Grenze M9).

Nach einem Update liegt also eine Datei mit neuem Namen auf der Platte, während
`~/.config/autostart/Zeiterfassung.desktop` weiter auf die alte zeigt. Der
Nutzer startet bei jeder Anmeldung stillschweigend die **Vorgängerversion**.
Löscht er die alte Datei, bricht der Autostart sichtbar.

Geschrieben wird die Datei heute ausschließlich beim Umlegen des Schalters
(`settings_dialog/dialog.py`). Es gibt keinen Startup-Pfad, der sie nachzieht;
`autostart.migrate_legacy_autostart` ist das strukturelle Vorbild, aber auf
Windows und `sys.frozen` gegated.

### 3. Kein Desktop-Menüeintrag

Ohne `appimaged` oder AppImageLauncher integriert niemand die AppImage in das
Anwendungsmenü. Auf dem Zielgerät ist keines von beiden installiert (per
`which` geprüft). Die App ist damit nur über den Dateimanager oder ein Terminal
startbar.

## Ziel

Eine AppImage, die nach dem ersten Start im Anwendungsmenü steht, deren
Autostart ein Update überlebt, und deren Icon überall ankommt — ohne
Installationsskript und ohne dass der Nutzer etwas konfiguriert.

Nicht-Ziel: die AppImage an einen kanonischen Ort verschieben. Eine Anwendung,
die ihre eigene laufende Datei bewegt, kollidiert mit dem Single-Instance-Guard
und mit der Nutzererwartung an das AppImage-Format (verworfen, s.u.).

## Architektur

### `paths.get_resource_path()`

Neue Funktion neben `get_base_path()`:

```python
def get_resource_path():
    """Verzeichnis der GEBÜNDELTEN Programmdaten (assets/) — read-only.

    Frozen: sys._MEIPASS (onefile = Temp-Extraktion, onedir = _internal/).
    Script-Modus: Repo-Root.
    """
```

Fallback auf `os.path.dirname(sys.executable)`, falls `sys.frozen` gesetzt ist,
`_MEIPASS` aber fehlt (kein PyInstaller-Bundle).

Die Abgrenzung ist der eigentliche Inhalt der Änderung und gehört als
Docstring-Satz dorthin: **`get_base_path()` = Nutzerdaten, schreibbar,
persistent. `get_resource_path()` = Programmdaten, read-only, kommt mit dem
Build.** Wer künftig eine gebündelte Datei sucht, nimmt die zweite.

Für Windows ist der Umstieg risikofrei: `_MEIPASS` zeigt bei onedir auf
`_internal`, und dort liegt `assets\` nachweislich.

### Umbenennung `base_path` → `resource_path` in der Tray-Schicht

Die drei Tray-Backends und die `TrayIcon`-Fassade nutzen ihren `base_path`
**ausschließlich** für Asset-Lookups. Der Parameter wird umbenannt statt ihm
still eine neue Bedeutung unterzuschieben; `ui.py` übergibt
`get_resource_path()`. Gleiches gilt für `theme.apply_app_icon` (holt sich den
Pfad selbst) und die beiden Icon-Zeilen in `ui.py`.

### `src/desktop_entry.py` (neu, Tk-frei)

Besitzt das `.desktop`-Dateiformat:

- `exec_line(target, arguments)` — **umgezogen** aus `autostart._exec_line`.
  Das shlex-Quoting (Audit N12) bekommt damit einen Besitzer, statt dass ein
  zweites Modul den privaten Namen des ersten mitbenutzt (Audit N17 hat genau
  das verboten). `autostart.py` importiert es von hier; Richtung stimmt, denn
  Autostart ist ein Sonderfall einer `.desktop`-Datei, nicht umgekehrt.
- `ensure_icon(resource_path, data_path)` — kopiert `assets/margenheld-icon.png`
  einmalig nach `<data>/icon.png`. Nötig, weil `Icon=` den AppImage-Mount
  überleben muss; ein Pfad in `_MEIPASS` ist nach dem Beenden tot. Idempotent —
  kopiert nur, wenn das Ziel fehlt oder seine **Dateigröße** von der Quelle
  abweicht (billiger Versions-Check ohne Hash, reicht für ein Icon, das sich
  praktisch nie ändert). Liefert den Zielpfad oder `None`.
- `write_menu_entry(target, icon_path)` — schreibt
  `~/.local/share/applications/Zeiterfassung.desktop`.

Inhalt des Menüeintrags:

```
[Desktop Entry]
Type=Application
Name=Zeiterfassung
Comment=Arbeitszeiten erfassen, berichten und versenden
Exec=<exec_line(target, "")>
Icon=<absoluter Pfad oder entfällt>
Terminal=false
Categories=Office;
StartupWMClass=Zeiterfassung
```

`Icon=` entfällt komplett, wenn `ensure_icon` `None` liefert — eine Zeile mit
leerem Wert wäre schlechter als keine.

### `autostart.refresh_linux_target(base_path)`

Zieht die Autostart-Datei auf den aktuellen `$APPIMAGE`-Pfad nach. Vier Gates,
alle müssen zutreffen:

1. `sys.frozen` — im Repo-Modus zeigte das Ziel sonst auf python.exe + Repo
   (dieselbe Selbstbeschädigung, gegen die `migrate_legacy_autostart` gegated
   ist).
2. `platform.system() == "Linux"`.
3. `os.environ.get("APPIMAGE")` gesetzt — die nackte PyInstaller-Ausgabe aus
   `build.yml` hat das nicht.
4. `~/.config/autostart/Zeiterfassung.desktop` existiert bereits — wer keinen
   Autostart eingeschaltet hat, bekommt hier auch keinen.

Trifft alles zu, wird die Datei über den bestehenden `_enable_linux`-Pfad neu
geschrieben. Kein neues Format, keine zweite Schreibstelle.

### Startup-Hook in `main.py`

Beide Schritte laufen dort, wo `migrate_legacy_autostart(base)` schon steht —
dasselbe Muster, dieselbe Stelle im Ablauf, jeder Aufruf gated sich selbst.

## Verhalten

**Menüeintrag:** wird bei **jedem** Start idempotent überschrieben, solange
frozen-Linux und `$APPIMAGE` gesetzt sind. Damit hält sich `Exec=` von selbst
aktuell — dieselbe Selbstheilung wie beim Autostart, eine Mechanik statt zwei.
Kein neues Setting: ein Schalter für „möchtest du einen Menüeintrag" wäre genau
die Sorte Option, die niemand findet, und `appimaged` täte im Ökosystem
ohnehin dasselbe automatisch.

**Autostart:** heilt beim ersten Start der neuen AppImage. Bis dahin startet
weiter die alte Version — korrekt, aber nennenswert (s. Grenzen).

## Betroffene Stellen

| Datei | Änderung |
|-------|----------|
| `src/paths.py` | `get_resource_path()` neu, Abgrenzung im Docstring |
| `src/desktop_entry.py` | **neu** — `exec_line`, `ensure_icon`, `write_menu_entry` |
| `src/autostart.py` | `_exec_line` ausgezogen, `refresh_linux_target()` neu |
| `src/main.py` | zwei Aufrufe im bestehenden Startup-Block |
| `src/ui.py` | `TrayIcon(get_resource_path(), …)`, Icon-Zeilen |
| `src/theme.py` | `apply_app_icon` nutzt `get_resource_path()` |
| `src/tray.py`, `tray_mac.py`, `tray_linux.py` | Parameter `base_path` → `resource_path` (auch in `icon_pixmaps`) |
| `tests/test_tray.py`, `test_tray_linux.py`, `test_tray_linux_dbus.py`, `test_autostart.py` | ziehen die Umbenennung mit; `test_tray_linux.py::test_backend_keeps_the_facade_constructor_signature` prüft `backend.base_path` explizit und bricht sonst |
| `README.md`, `src/CLAUDE.md`, `docs/known-limitations.md` | s.u. |

## Fehlerbehandlung / Edge Cases

Alles best-effort, geloggt, **nie** fatal — Vorbild `secure_file`: ungehärtet
bzw. nicht integriert ist der Status quo, eine geworfene Exception im
Startpfad wäre eine Regression. Konkret abgefangen: nicht schreibbares
`~/.local/share/applications`, fehlendes `assets/margenheld-icon.png`,
`OSError` beim Kopieren, fehlendes `$APPIMAGE`.

## Tests

Alle plattformunabhängig über `monkeypatch` (Muster aus `test_tray.py`), keine
echten Schreibzugriffe außerhalb von `tmp_path`:

- `get_resource_path`: frozen mit `_MEIPASS`, frozen ohne `_MEIPASS`
  (Fallback), Script-Modus.
- `desktop_entry`: `.desktop`-Inhalt, Quoting eines Pfads mit Leerzeichen
  (übernommen aus den bestehenden `_exec_line`-Tests), `Icon=` entfällt ohne
  Icon, Idempotenz bei doppeltem Aufruf, `ensure_icon` kopiert nicht erneut.
- `autostart.refresh_linux_target`: alle vier Gate-Zustände einzeln als No-op,
  plus der Positivfall (veralteter Pfad wird ersetzt).
- `icon_pixmaps` gegen einen `resource_path`.

## Verifikation / Übergabe

- **CI:** die neuen Tests laufen auf allen Matrix-Pythons und allen drei
  Plattformen.
- **Windows-Regression (lokal prüfbar, wichtig):** die Umbenennung und
  `get_resource_path` fassen den Windows-Pfad an. Volle Suite plus ein
  In-Place-Build-Test, dass Tray-Icon und Fenster-Icon unverändert erscheinen.
- **Manuelles Gate macOS (zusätzlich, nicht optional):** anders als der
  Linux-Tray ist dieser Pfad auf macOS nicht hinter einem Opt-in-Flag
  dormant — `theme.apply_app_icon` (jeder Dialog) und `ui._setup_window_icon`
  (jeder Start) gehen mit `get_resource_path()` von "fand nichts" auf
  "lädt tatsächlich ein PhotoImage", ohne dass ein Nutzer das aktivieren
  müsste. Vor dem nächsten echten Release denselben Pre-Release bauen (s.
  `CLAUDE.md`, „Plattformspezifische PRs — Pre-Release vorschlagen") und auf
  macOS prüfen: App startet, Fenster-Icon erscheint, mindestens ein Dialog
  (Einstellungen oder Tages-Dialog) öffnet fehlerfrei. Das ist die einzige
  Prüfung, die diese Änderung auf macOS vor einem echten Release bekommt.
- **Manuelles Gate (Debian 13 / Plasma 6), zusätzlich zu den Tray-Punkten:**
  Menüeintrag erscheint nach dem ersten Start; Start daraus funktioniert;
  Icon im Menü und im Tray sichtbar (belegt Befund 1 als behoben); Autostart
  einschalten, AppImage umbenennen, App starten, Datei prüfen — `Exec=` zeigt
  auf den neuen Namen; `StartupWMClass` prüfen, indem das laufende Fenster im
  Task-Manager unter dem Menüeintrag gruppiert erscheint.

## Bekannte Grenzen (gehören nach `docs/known-limitations.md`)

- Löscht der Nutzer die AppImage, bleibt ein toter Menüeintrag zurück. Die App
  kann nicht aufräumen, wenn sie nicht mehr startet. Ein Deinstallations-Hook
  existiert im AppImage-Format nicht.
- Der Autostart heilt erst, **nachdem** die neue AppImage einmal gestartet
  wurde. Wer die neue Version herunterlädt und nie öffnet, startet weiter die
  alte — ohne Hinweis.
- Ohne `$APPIMAGE` (nackte PyInstaller-Ausgabe aus `build.yml`) sind beide
  Schritte No-ops. Gewollt: dort gibt es keinen stabilen Pfad, auf den man
  zeigen könnte.
- `StartupWMClass=Zeiterfassung` ist eine begründete Annahme (Tk leitet die
  WM-Klasse vom Basisnamen der Exe ab), aber nicht verifiziert. Stimmt sie
  nicht, gruppiert KDE das Fenster nur nicht unter dem Menüeintrag — kosmetisch,
  deshalb Prüfpunkt im Gate statt Blocker.

## Bewusst nicht enthalten (YAGNI)

- **AppImage an einen kanonischen Ort verschieben** (`~/.local/bin`). Löste
  Befund 2 an der Wurzel statt nachzuziehen, aber die App bewegte dabei ihre
  eigene laufende Datei — Kollision mit dem Single-Instance-Guard, und ein
  AppImage, das sich selbst verschiebt, verletzt die Erwartung an das Format.
- **Installationsskript.** Ein Shell-Skript neben einer AppImage gibt genau die
  Selbstgenügsamkeit auf, für die man das Format wählt. Alles, was es täte,
  kann die App beim Start selbst.
- **Setting für den Menüeintrag.** S. Verhalten.
- **`.desktop`-Datei beim Beenden aufräumen.** Der Normalfall ist ein Neustart,
  kein Deinstallieren; ein Eintrag, der bei jedem Beenden verschwindet, wäre
  schlechter als ein gelegentlich toter.
