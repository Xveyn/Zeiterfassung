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
| `bericht-v1.21.0.png` | Erzeugter PDF-Bericht, Seite 1 |
| `einstellungen-v1.21.0.png` | Einstellungen, Tab „Arbeitszeit" |

## Neue Screenshots aufnehmen

Veraltet ein Bild, wird es **nicht überschrieben**, sondern unter neuem Namen
(`…-v<neue-version>.png`) hinzugefügt und die Referenz im README umgehängt; das
alte Bild kann im selben Zug gelöscht werden — die Historie steckt in git.

Aufgenommen wird mit **Demo-Daten** (Max Mustermann, `…@example.com` /
`…@musterfirma.de`), nie mit echten Nutzerdaten. Die Daten der App liegen im
Repo-Modus im Projekt-Root (`zeiterfassung.json`, `reservations.json`,
`settings.json`) und sind alle gitignored.
