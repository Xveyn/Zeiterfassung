# Screenshots

Die Bilder in diesem Ordner werden vom [README](../../README.md) eingebunden.

**Namensschema: `<motiv>-v<version>.png`** — die Versionsnummer im Dateinamen
sagt, aus welchem Stand der App das Bild stammt (`src/version.py` zum Zeitpunkt
der Aufnahme). Ohne sie ließe sich später nicht mehr sagen, ob ein Bild die
aktuelle Oberfläche zeigt oder eine drei Releases alte.

| Datei | Motiv |
|-------|-------|
| `kalender-v1.25.0.png` | Monatsansicht (Hero-Bild) mit Urlaub, violettem Punkt (Reservierung) und bernsteinfarbenem Punkt (Sende-Erinnerung) |
| `tagesdialog-v1.25.0.png` | Tages-Dialog: Ist-Zeit, Reservierung, Erinnerung |
| `senden-v1.23.3.png` | Sende-Dialog mit Zeitraum- und Kategoriewahl |
| `bericht-v1.23.3.png` | Erzeugter PDF-Bericht, Seite 1 |
| `einstellungen-v1.25.0.png` | Einstellungen, Tab „Arbeitszeit" |
| `einstellungen-erinnerungen-v1.25.0.png` | Einstellungen, Tab „Erinnerungen" mit dem Abschnitt „Handy" |
| `einstellungen-mobil-v1.25.0.png` | Einstellungen, Tab „Mobil" mit einem gekoppelten Demo-Handy |
| `handy-woche-v1.25.0.png` | Handy-Web-App: Woche mit Reservierung und „Noch ausstehend" |
| `handy-editor-v1.25.0.png` | Handy-Web-App: Tages-Editor, Reiter „Reservierung" |
| `handy-verbindung-v1.25.0.png` | Handy-Web-App: Einstellungen → Verbindung (Benachrichtigungen) |
| `handy-kategorien-v1.25.0.png` | Handy-Web-App: Einstellungen → Kategorien |

## Neue Screenshots aufnehmen

Veraltet ein Bild, wird es **nicht überschrieben**, sondern unter neuem Namen
hinzugefügt und die Referenz im README umgehängt; das alte Bild kann im selben
Zug gelöscht werden — die Historie steckt in git.

Aufgenommen wird meist **vor** dem Release, die Version steht dann noch nicht
fest. Der neue Name trägt deshalb an der Stelle der Versionsnummer denselben
Platzhalter wie die README-Marker (`--VERSION--`), ebenso jeder Verweis darauf.
Im Release-PR löst `python scripts/resolve_readme_version.py` beides auf —
benennt die Dateien um und zieht die Pfade in `README.md` und dieser Datei
nach; `--check` hält den Release-PR an, solange ein Platzhalter übrig ist.

Aufgenommen wird mit **Demo-Daten**, nie mit echten Nutzerdaten. Die legt
`scripts/demo_data.py` an — Max Mustermann, zwei Monate Arbeitszeit relativ
zu heute, Reservierungen, ein Urlaub im laufenden Monat, SMTP-Konten und
Webhooks, Adressen nur aus den Beispiel-Domains (`…@example.com`):

```
python scripts/demo_data.py          # in den Datenordner des Repo-Modus
python -m src.main
```

Die Daten liegen im Repo-Modus im Projekt-Root und sind alle gitignored; ein
zweiter Lauf bricht ab, `--force` ersetzt sie. Der Schlüsselbund des
Betriebssystems bleibt dabei unberührt (Details im Docstring des Skripts).

**Eigener Datenordner statt Projekt-Root.** Wer die echte Installation auf demselben
Rechner hat, nimmt besser einen eigenen Ordner: `ZEITERFASSUNG_DATA_DIR=<ordner>
python scripts/demo_data.py` und danach `ZEITERFASSUNG_DATA_DIR=<ordner> python -m src.main`.
Für den Tab „Mobil“ ein Demo-Handy in `mobile_devices.json` des Demo-Ordners anlegen
(`mobile_pairing.issue_device` + `MobileStore.save`, ohne den Server einzuschalten) und für
den Abschnitt „Handy“ in `settings.json` `mobile_push_enabled` setzen — nur im Demo-Ordner.
Dialoge lassen sich ohne Mausklicks über ein kleines Skript öffnen, das `App._open_dialog`
bzw. `App._open_settings(initial_tab=…)` ruft und das Fenster aufnimmt (unter Wayland mit
`spectacle -b -n -a -o <datei>`, danach den transparenten Schattenrand mit
`convert … -channel A -threshold 98% +channel -trim +repage` abschneiden).

**Handy-Ansichten** entstehen im Browser am Rechner, nicht auf einem Handy:
`python scripts/pwa_devserver.py --seed-days 21 --reservations --api-port <frei>` startet die
echte Handy-Instanz und die Web-App, der ausgegebene Koppel-Link koppelt einen Chrome mit
390×844 Pixeln Fenstergröße. Vor der Aufnahme von Hand bereinigt: der Hinweis „Der Browser
sichert die Daten nicht dauerhaft“ (der Test-Browser bekommt keinen dauerhaften Speicher) und
die eigene LAN-Adresse, die der Reiter „Verbindung“ zeigt (durch eine Beispiel-Adresse ersetzt).
Den Kopplungscode zeigt kein Bild.
