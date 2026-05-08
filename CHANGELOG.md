# Changelog

## v1.10.0
- Standard-Arbeitszeiten lassen sich jetzt **pro Wochentag** konfigurieren — der Settings-Dialog zeigt eine Tabelle Mo–So mit je einem Start- und Endefeld, die der Eintrags-Dialog beim Anlegen eines neuen Tages automatisch zieht. Bestehende globale Werte (`Standard-Start` / `Standard-Ende`) werden beim ersten App-Start auf alle sieben Wochentage übernommen, sodass sich für Bestandsnutzer nichts ändert, bis sie einzelne Tage abweichend einstellen. Pause bleibt eine globale Einstellung

## v1.9.2
- Mail-Templates (Anrede, Inhalt, Gruß, Name) und der Bericht escapen Sonderzeichen jetzt korrekt — `&`, `<`, `>` werden im Mail-HTML und PDF nicht mehr roh ausgegeben. **Behavior-Change:** wer bisher bewusst HTML-Tags wie `<b>` oder `<br>` in den Mail-Templates verwendet hat, sieht diese jetzt als Klartext. Zeilenumbrüche im Inhalt/Gruß werden weiterhin korrekt umgebrochen
- `token.json` wird auf macOS/Linux mit `0600`-Permissions geschrieben — der Refresh-Token mit Gmail-Send-Scope ist auf Multi-User-Systemen nicht mehr für andere User lesbar (Windows ignoriert Unix-Permissions)
- Settings-Speichern macht statt 12 separater Disk-Roundtrips nur noch einen einzigen — minimiert das Risiko verlorener Updates, wenn der Update-Banner-Worker parallel zum Settings-Dialog schreibt
- Neues Logfile unter `<Datenordner>/logs/zeiterfassung.log` (rotierend, max. 4 MB Gesamtvolumen). App-Start, uncaught Exceptions im Tk-Mainloop und alle Sendepfad-Fehler landen dort — bei `--noconsole`-Builds (Windows-Release) gab es bisher keine Spur von Crashes
- `settings.json` wird beim Laden gegen die erwarteten Typen validiert. Ein manuell verändertes Feld mit falschem Typ (z.B. String statt Int) lässt die App nicht mehr abstürzen, sondern fällt auf den Default zurück und schreibt eine Warnung ins Logfile

## v1.9.1
- Multi-Monitor-Fix: Settings-, Eintrags-, Sende- und Credentials-Dialoge öffnen sich jetzt zuverlässig auf demselben Monitor wie das Hauptfenster (vorher landeten sie immer auf dem Primärmonitor). Wenn der Dialog grösser ist als das App-Fenster, wird er an Parent-Top-Left ausgerichtet, damit die Titlebar nicht über den Bildschirmrand rutscht
- `settings.json` wird jetzt atomar geschrieben (temp + replace), damit ein Crash mid-write keine korrupte Datei hinterlassen kann — relevant, weil Settings-Dialog und Update-Banner-Worker parallel schreiben können
- Internes Refactoring: Monats-/Wochenansicht in `ui.py` und HTML-/PDF-Render in `report.py` deduplizieren gemeinsame Render-Helfer

## v1.9.0
- Update-Check beim App-Start: einmal pro Kalendertag wird die GitHub-Releases-API abgefragt. Liegt eine neuere Version vor, erscheint zwischen Header und Kalender ein Banner mit dem Versions-Hinweis und einem **Download**-Button, der direkt das passende Plattform-Asset (`.exe` / `.dmg` / `.AppImage`) im Browser öffnet
- Fallback auf die Release-Page, falls kein Plattform-Asset gefunden wird (z.B. Intel-Mac oder ARM-Linux)
- ✕-Symbol blendet die jeweilige Version dauerhaft aus — Banner kommt erst wieder, wenn eine noch neuere Version released wird (Tooltip: „Diese Version ausblenden")
- Netzwerk-/API-Fehler werden still verschluckt — der Hinweis ist nice-to-have und stört einen Offline-Start nicht. Drosselung und Dismiss werden in `settings.json` persistiert (`last_update_check_at`, `dismissed_version`)

## v1.8.3
- Pfeiltasten `<Left>` / `<Right>` navigieren im Hauptfenster durch Monate bzw. Wochen — analog zu den `‹`/`›` Buttons im Header. Modal-Dialoge fangen die Tasten automatisch ab, sodass `<Left>`/`<Right>` in Eingabefeldern weiterhin den Cursor bewegen

## v1.8.2
- Doppelter Tooltip an Feiertags-/Eintragszellen behoben: `attach_tooltip` wird jetzt nur am äußersten Frame gebunden und erkennt beim Pointer-Übergang in Child-Widgets, dass die Maus weiterhin im Cluster ist (keine Re-Open-Stacking)

## v1.8.1
- Feiertagsnamen erscheinen jetzt korrekt auf Deutsch (z.B. „Tag der Deutschen Einheit" statt „German Unity Day"). `python-holidays` wird mit `language="de"` aufgerufen — vorher griff der englische Default

## v1.8.0
- Gesetzliche Feiertage werden im Monats- und Wochenkalender grün markiert, sobald in den Einstellungen ein Bundesland gewählt ist — Default „— kein Bundesland —" lässt das Verhalten für Bestandsnutzer unverändert
- Tooltip beim Hover zeigt den vollen Feiertagsnamen, sobald der Name in der Zelle truncated ist
- Beim Anlegen eines neuen Eintrags an einem Feiertag erscheint eine Bestätigungs-Warnung mit Datum und Feiertagsname (kein Hinweis beim Bearbeiten bestehender Einträge)
- Tag mit Eintrag und Feiertag: rote Eintragszelle bleibt visuell dominant, Tooltip zeigt zusätzlich den Feiertagsnamen
- Datenquelle: `python-holidays` (offline gebündelt, alle 16 Bundesländer)

## v1.7.0
- Einstellungen: neue Sektion „Gmail-Zugangsdaten" am Anfang des Dialogs mit „Ordner öffnen"-Button und Live-Status (✓/✗) für `credentials.json` — kein Suchen mehr nach `~/Library/Application Support/Zeiterfassung` oder `%LOCALAPPDATA%\Programs\Zeiterfassung`
- Sende-Fehler bei fehlender `credentials.json`: statt der Standard-Messagebox erscheint ein Dialog im Dark-Theme mit zwei Buttons („Datenordner öffnen" / „OK") — ein Klick öffnet das richtige Verzeichnis
- Status-Label aktualisiert sich live alle 500 ms, solange der Settings-Dialog offen ist (kein Neuöffnen mehr nötig nach dem Reinkopieren)
- Monat/Woche-Toggle springt jetzt immer auf den aktuellen Monat / die aktuelle KW (vorher: behielt die zuletzt angezeigte Scroll-Position)

## v1.6.0
- Installer für macOS (DMG, Apple Silicon und Intel) und Linux (AppImage) zusätzlich zum bestehenden Windows-Installer
- Autostart jetzt auch unter macOS (LaunchAgent) und Linux (`.desktop`-Datei unter `~/.config/autostart/`)
- Datenverzeichnisse plattformkonform: macOS unter `~/Library/Application Support/Zeiterfassung`, Linux unter `$XDG_DATA_HOME/Zeiterfassung`, Windows unverändert
- Release-Workflow baut alle vier Artefakte parallel und taggt erst nach erfolgreichem Build aller Plattformen

## v1.5.0
- Gmail-Token wird beim App-Start proaktiv im Hintergrund erneuert, damit beim Senden kein Login-Browser mehr aufpoppt
- Differenzierte Fehlerbehandlung beim Token-Refresh: abgelaufene Anmeldung wird als Messagebox angezeigt, Netzwerkfehler beim Start werden still übergangen

## v1.4.0
- Wochen-Gruppierung im E-Mail- und PDF-Bericht mit Wochenüberschrift und Wochensumme je KW
- UTF-8-Fix: Umlaute und ß im E-Mail-Body und Betreff werden korrekt dargestellt
- Sichtbare Fehlermeldungen beim Mail-Versand (inkl. Traceback), wenn der PDF-/Sende-Schritt fehlschlägt
- PyInstaller-Build bündelt jetzt xhtml2pdf- und reportlab-Submodule, damit die PDF-Erzeugung in der installierten Version funktioniert
- Einstellungen: Feld "E-Mail" heißt jetzt "Absender" (analog zu "Empfänger")

## v1.3.0
- Stundenlohn-Einstellung mit Bruttolohn-Anzeige im Footer (nur lokal sichtbar)
- Rechtsklick auf Tageseintrag zum Löschen
- Versionsnummer im Fenstertitel
- GitHub Actions Workflow für automatische Tests

## v1.2.0
- App-Icon und Taskbar-Integration (Windows & Linux)
- Feste Fenstergröße
- PyInstaller-Build mit gebündelten Assets

## v1.1.0
- PDF-Report-Generierung
- HTML E-Mail-Vorlagen mit Dark-Mode-Styling
- Mail-Einstellungen (Betreff, Anrede, Inhalt, Gruß)
- Datumsbereich-Auswahl für Reports
- Standard-Arbeitszeiten konfigurierbar (Start, Ende, Pause)

## v1.0.0
- Kalenderansicht mit Monatsübersicht
- Zeiterfassung (Start, Ende, Pause)
- Gmail OAuth2 E-Mail-Versand
- Empfänger-Einstellung
- Windows-Autostart
- Dark-Mode UI
