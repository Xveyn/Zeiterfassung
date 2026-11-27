# Screenshots

Die Bilder in diesem Ordner werden vom [README](../../README.md) eingebunden.

**Namensschema: `<motiv>-v<version>.png`** — die Versionsnummer im Dateinamen
sagt, aus welchem Stand der App das Bild stammt (`src/version.py` zum Zeitpunkt
der Aufnahme). Ohne sie ließe sich später nicht mehr sagen, ob ein Bild die
aktuelle Oberfläche zeigt oder eine drei Releases alte.

| Datei | Motiv |
|-------|-------|
| `kalender-v--VERSION--.png` | Monatsansicht (Hero-Bild) mit Urlaub, violettem Punkt (Reservierung) und bernsteinfarbenem Punkt (Sende-Erinnerung) |
| `tagesdialog-v--VERSION--.png` | Tages-Dialog: Ist-Zeit mit Notiz, Reservierung, Erinnerung |
| `senden-v--VERSION--.png` | Sende-Dialog mit Zeitraum- und Kategoriewahl, „Nach Kategorie“ und „Nach Notiz aufschlüsseln“ angehakt |
| `bericht-v--VERSION--.png` | Erzeugter PDF-Bericht, Seite 1 (Notizen in der Kategorie-Spalte) |
| `bericht-summe-v--VERSION--.png` | Ausschnitt der letzten Berichtsseite: „Summe je Kategorie“, aufgeschlüsselt nach Notiz (die Tabelle steht nie auf Seite 1, xhtml2pdf hält jede Woche zusammen) |
| `einstellungen-v--VERSION--.png` | Einstellungen, Tab „Arbeitszeit" mit „Slots eines Tages" und der Moduswahl der Standardzeiten |
| `konflikte-v--VERSION--.png` | Konfliktdialog: zwei Karten, die sich nur in der Notiz unterscheiden, links die gruppierte Liste |
| `einstellungen-erinnerungen-v--VERSION--.png` | Einstellungen, Tab „Erinnerungen" mit dem Abschnitt „Handy" |
| `einstellungen-mobil-v--VERSION--.png` | Einstellungen, Tab „Mobil" mit einem gekoppelten Demo-Handy |
| `handy-woche-v--VERSION--.png` | Handy-Web-App: Woche mit Notizen als eigene Zeile, heutigem Tag, Reservierung und „Noch ausstehend" |
| `handy-editor-v--VERSION--.png` | Handy-Web-App: Tages-Editor, Reiter „Arbeitszeit" mit Notizfeld und aufgeklappter Liste; 390 × 1580 Pixel, damit der ganze Dialog im Bild steht |
| `handy-verbindung-v--VERSION--.png` | Handy-Web-App: Einstellungen → Verbindung (Zustandskarte, Benachrichtigungen, App-Sperre, Zeiten verschieben, Notizen, Trennen); 390 × 1330 Pixel, damit der ganze Reiter im Bild steht |
| `handy-kategorien-v--VERSION--.png` | Handy-Web-App: Einstellungen → Kategorien |
| `handy-einrichtung-v--VERSION--.png` | Handy-Web-App: Einrichtungs-Screen vor dem Koppeln (Chrome auf Android, User-Agent per CDP gesetzt) |

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
`python scripts/pwa_devserver.py --reservations --api-port <frei>` startet die echte Handy-Instanz und die
Web-App, der ausgegebene Koppel-Link koppelt einen Chrome mit **390×844 Pixeln** Fenstergröße. Alle Bilder
sind 390 Pixel breit und zeigen den Zustand ohne Dialog-Animation (Playwright: `animations: 'disabled'`).

Die Demo-Woche stammt nicht von `--seed-days` (das legt gleichförmige Ein-Stunden-Tage an), sondern von einem kleinen
Skript, das `pwa_devserver.running(...)` startet und mit `dev.storage.apply_merge(...)` Einträge für Montag bis
heute schreibt (Mo `08:00–16:30`, 30 min Pause; Di zwei Slots Projekt/Intern; Mi Support und Projekt; Do `08:00–16:00`;
heute `08:00–12:00`); die Reservierung für heute (`13:00–17:00`, Support) kommt über den Editor der Web-App, weil der
Reservierungs-Speicher der Handy-Instanz im Server liegt. Heute sollte ein Werktag mit Ist-Zeit am Vormittag sein,
damit „heute“ und „Noch ausstehend“ im Bild stehen.

Was sich beim Aufnehmen ändert, ohne dass es im Bild stehen soll:

- **Speicher-Hinweis:** der Test-Browser bekommt keinen dauerhaften Speicher, die Web-App zeigt dann ihre Warnung.
  Vor dem Laden `navigator.storage.persist` auf „gewährt“ setzen (`page.addInitScript`), dann erscheint sie nicht.
- **Fokusrahmen:** ein Dialog setzt beim Öffnen den Fokus auf den ersten Knopf, im Bild steht dann ein gelber
  Rahmen. Per eingeschleustem CSS ausblenden (`:focus, :focus-visible { outline: none !important }`); `blur()` am
  fokussierten Knopf lässt den Screenshot in Playwright hängen.
- **Desktop-Name:** der Dev-Server nennt den Desktop „Desktop (Dev)“; im Reiter „Verbindung“ vor der Aufnahme durch
  „Arbeitsrechner“ ersetzen. Die LAN-Adresse steht nur unter „Technische Details“ (eingeklappt, also nicht im Bild);
  wer sie aufklappt, ersetzt sie durch eine Beispiel-Adresse.
- **Service Worker:** Worker und Caches vor dem Koppeln abmelden/leeren, sonst zeigt der Browser eine ältere Fassung der Seite.

Den Kopplungscode zeigt kein Bild.
