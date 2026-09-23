# Screenshots

Die Bilder in diesem Ordner werden vom [README](../../README.md) eingebunden.

**Namensschema: `<motiv>-v<version>.png`** — die Versionsnummer im Dateinamen
sagt, aus welchem Stand der App das Bild stammt (`src/version.py` zum Zeitpunkt
der Aufnahme). Ohne sie ließe sich später nicht mehr sagen, ob ein Bild die
aktuelle Oberfläche zeigt oder eine drei Releases alte.

| Datei | Motiv |
|-------|-------|
| `kalender-v1.21.0.png` | Monatsansicht (Hero-Bild) |
| `tagesdialog-v1.21.0.png` | Tages-Dialog: Ist-Zeit, Reservierung, Erinnerung |
| `senden-v1.21.0.png` | Sende-Dialog mit Zeitraum- und Kategoriewahl |
| `bericht-v--VERSION--.png` | Erzeugter PDF-Bericht, Seite 1 |
| `einstellungen-v1.21.0.png` | Einstellungen, Tab „Arbeitszeit" |

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
