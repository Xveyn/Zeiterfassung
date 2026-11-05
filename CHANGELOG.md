# Changelog

Ältere Versionen stehen im [Archiv](CHANGELOG-archive.md).

## 1.26.0 — 2026-11-05

Die Handy-Web-App läuft jetzt auch auf dem iPhone und iPad: Dort gleicht sie
über einen Relay im Internet mit der App ab, Ende-zu-Ende verschlüsselt, weil
Safari den Zugriff auf eine Adresse im WLAN sperrt. Dazu kommen
Datenschutzhinweise in der App und in der Web-App, Standardzeiten wahlweise
allgemein oder je Wochentag, ein neu gestalteter Konfliktdialog und ein
aufgeräumteres Protokoll.

### Hinzugefügt
- **Handy-Abgleich über einen Relay (iPhone und iPad)**: Die Web-App gleicht
  Ist-Zeiten, Reservierungen und Kategorien über einen Relay im Internet mit der
  App ab. Der Relay reicht nur verschlüsselte Nachrichten weiter (AES-256-GCM,
  Ende-zu-Ende) und sieht keine Inhalte; die App muss dafür laufen. Auf iPhone
  und iPad ist das der einzige Weg, im WLAN bleibt der bisherige Abgleich
  unverändert. Geprüft mit Safari auf iPhone und iPad, als Web-App installiert,
  auch über Mobilfunk, einschließlich Benachrichtigungen auf dem iPhone. Nicht
  geprüft: Ruhezustand des Rechners, Android und Firefox über den Relay.
- **Einstellungen → Mobil: „Über Relay koppeln“**: Der Dialog zeigt einen
  QR-Code, den die installierte Web-App scannt (die Kamera-App geht oft, aber
  nicht immer). Die Geräteliste zeigt bei Geräten am Relay den
  Verbindungszustand. „Widerrufen“ löscht auch die Box am Relay; ohne Netz
  verfällt sie nach 90 Tagen ohne Nutzung.
- **Datenschutzhinweise**: Einstellungen → App → „Datenschutzhinweise“ zeigt,
  welche Daten der Relay verarbeitet und welche nicht. Die Web-App hat dazu eine
  eigene Seite, verlinkt im Koppel-Bildschirm und unter Einstellungen →
  Verbindung. Kontakt läuft über GitHub.
- **Standardzeiten allgemein oder je Wochentag**: Unter Einstellungen →
  Arbeitszeit lässt sich wie bei den Kategorien zwischen „Allgemein“ (ein
  Start–Ende-Paar für alle Tage) und „Tageweise“ wählen. Bestehende
  Wochenpläne bleiben sichtbar; wer von Tageweise auf Allgemein speichert,
  obwohl Tage abweichen, wird vorher gefragt.
- **Einstellungen → App: „Log-Ordner öffnen“**: Der Knopf öffnet den Ordner mit
  `zeiterfassung.log`, etwa für die Fehlersuche in einem Issue.
- **Einstellungen → API: Routenübersicht**: Der Tab erklärt unter „So sprichst
  du sie an“ die Anmeldung per Token und listet die Routen.

### Geändert
- **Konfliktdialog**: Beide Stände stehen als zwei Karten nebeneinander:
  „Dieses Gerät“ links, das andere Gerät rechts mit seinem Namen. Unterschiede
  sind gelb markiert, der jüngere Stand trägt „● neuer“. Die Liste ist in Zeiten
  und Einstellungen gruppiert, Tage mit Wochentag, Einstellungen im Klartext;
  nach dem Auflösen springt die Auswahl zum nächsten Konflikt.
- **Handy-Web-App: Zeiten in 5-Minuten-Schritten**: Start, Ende und Pause rasten
  wie am Desktop auf 5 Minuten. Bereits gespeicherte Werte bleiben, bis das Feld
  geändert wird.
- **Handy-Web-App: Reservierung gilt heute als erledigt**, sobald eine Ist-Zeit
  derselben Kategorie existiert, auch zu anderer Uhrzeit. Wer eine Reservierung
  nur verschiebt, sieht sie nicht mehr als „geplant“ und „noch ausstehend“.
- **Einstellungen**: Dropdowns haben mehr Innenabstand und einen größeren
  Pfeil-Knopf, der Kategorien-Dialog und die Zeilen im Tages-Dialog mehr Luft.
  Der Knopf im API-Tab heißt „Neu erzeugen“.
- **Protokoll**: Fremd-Rauschen und Debug-Reste fehlen, erwartete
  Anmeldefehler im Sync stehen als eine Zeile statt als Traceback. Neu sind
  Erfolg und Dauer von Sync, Kalender-Abgleich, Versand, Teilen, PDF-Export,
  Handy-Abgleich, Update-Check und Update-Download. Die Startzeilen nennen
  Version, Kanal, Plattform, Python und Tk sowie die eingeschalteten
  Funktionen, ohne Namen, Pfade oder Adressen; jede Zeile trägt den
  Thread-Namen.

### Behoben
- **Einstellungen**: Das Formular sprang beim Fokussieren eines Felds ohne
  Übergang nach oben, und die Liste eines Dropdowns löste sich teils vom Feld.
- **Handy-Web-App, Gerätename beim Koppeln**: Vorgeschlagen wurde auf jedem
  Gerät „Android-Handy“. Jetzt erkennt sie iPhone, iPad und das Android-Modell;
  ohne Treffer steht „Handy“ im Feld.
- **Handy-Web-App, Seite hinter einem Dialog**: Bei offenen Einstellungen oder
  dem Zeiteditor ließ sich die Seite dahinter weiter scrollen.
- **Handy-Web-App, schmale Bildschirme**: Im Tages-Editor quetschte der
  ×-Knopf ab zwei Slots die Zeitfelder, in Einstellungen → Verbindung brachen
  Werte Zeichen für Zeichen um, und lange Adressen liefen aus der Karte.
  „Abbrechen“ und „Speichern“ bleiben jetzt auch im Querformat sichtbar.

## 1.25.2 — 2026-10-30

Ein Wartungs-Release: Die Handy-Kopplung ist gegen gleichzeitige Zugriffe
abgesichert, die Handy-Web-App bekommt Wischgeste, ein größeres Lesefenster und
klarere Fehlermeldungen, und der Uninstaller räumt Sicherungskopien der
Zugangsdaten ab.

### Hinzugefügt
- **Handy-Web-App: Woche per Wischgeste wechseln**: In der Wochenansicht blättert
  ein Wisch nach links oder rechts zur nächsten bzw. vorigen Woche.
- **Handy-Web-App: Ist-Zeiten bis 14 Tage nach heute**: Das Handy sieht und
  behält Ist-Zeiten auch für die nächsten 14 Tage, nicht nur bis heute.
- **Handy-Web-App: Netzfehler nennen die Ursache**: Erreicht das Handy den
  Rechner nicht, nennt die Meldung die wahrscheinliche Ursache und wie man sie
  prüft.
- **Handy-Web-App: Service Worker reparieren**: Meldet Chrome bei der
  Update-Suche „ServiceWorker cannot be started“, richtet der Knopf „Reparieren“
  im Reiter „Updates“ nur den Service Worker neu ein. Einträge und Kopplung
  bleiben unberührt.

### Geändert
- **Handy-Web-App: Arbeitszeit außerhalb des Lesefensters gesperrt**: Ein Tag,
  den das Handy vom Rechner nicht kennt, sah leer aus, obwohl dort Einträge
  liegen konnten, und Speichern ersetzte sie ohne Konflikt. Jetzt ist die
  Arbeitszeit dort gesperrt; die Web-App bietet „Ältere Zeiten laden“ an oder
  nennt den Grund.

### Behoben
- **Handy-Kopplung bei gleichzeitigen Zugriffen**: Das Aufräumen von Schlüsseln
  und „Alle widerrufen“ lief nicht abgesichert neben dem Koppeln eines Geräts; ein
  Handy, das in diesem Fenster koppelte, verlor seinen frischen Schlüssel und
  musste neu koppeln. Beides läuft jetzt unter der Gerätesperre.
- **Koppel-Dialog**: Scheitert das Speichern des Geräts, sagt der Dialog es, statt
  ein Handy als gekoppelt zu zeigen, das die App nicht kennt.
- **Handy-Web-App, Abgleich über mehrere Tabs**: Ein zweiter Tab sendete
  denselben Zähler („neu koppeln“) und schrieb Zähler und Token des anderen
  zurück. Der Abgleich läuft jetzt unter einer Sperre und liest den Stand frisch.
- **Handy-Web-App, Fehlerdiagnose**: Bei abgefangenen Fehlern erscheint die
  Ursache und steht im Log; Chromes Update-Fehler wird nicht mehr vor dem Grund
  abgeschnitten.
- **Einstellungen**: Das Mausrad schaltet den Wert einer Combobox, sobald sie
  den Fokus hat; vorher scrollte es stets das Formular. Ohne Fokus scrollt weiter
  das Formular.
- **Deinstallation**: Der Uninstaller entfernt auch die `.corrupt-*`-Kopien der
  Zugangsdaten.

## 1.25.1 — 2026-10-29

Ein Wartungs-Release: Der PDF-Bericht bricht an Seitengrenzen nicht mehr mitten
in Tabellen um, und die Handy-Web-App schlägt die Ist-Zeit aus einer
Reservierung vor, wie es die App am Rechner tut.

### Behoben
- **PDF-Bericht: Summentabellen bleiben zusammen**: Die „Summe je Kategorie“ und
  der Urlaubs-Block konnten am Seitenende zerrissen werden, die Kopfzeile stand
  dann auf der einen, die Zeilen auf der nächsten Seite. Eine solche Tabelle
  beginnt jetzt als Ganzes auf der nächsten Seite, wenn sie nicht mehr passt.
  Die Mail ist unverändert.
- **PDF-Bericht: Wochen bleiben zusammen**: Die Kopfzeile „KW …“, die Tage, die
  „Summe KW“ und die Gesamtzeile konnten an Seitengrenzen von ihren Tagen
  getrennt werden. Jede Kalenderwoche steht jetzt zusammen auf einer Seite, die
  Gesamtzeile in der letzten Woche.
- **Handy-Web-App: Ist-Zeit aus der Reservierung vorschlagen**: Hat ein Tag eine
  Reservierung, aber noch keine Ist-Zeit, ist der Reiter „Arbeitszeit“ daraus
  vorbelegt: Start und Ende vom ersten Slot, die Kategorie bei genau einem Slot.
  Vorher war er leer und ohne Kategorie. Außerdem zeigt die Kategorie wie am
  Rechner ein `*` (`Projekt*`), wenn die Zeiten von den Standardzeiten der
  Kategorie abweichen. Das Sternchen ist nur Anzeige, gespeichert wird der
  Name ohne.

## 1.25.0 — 2026-10-26

Zwei neue Schnittstellen, beide standardmäßig aus: eine lokale HTTP-API für
Skripte und eine Handy-Erfassung per Web-App, die im WLAN mit der App abgleicht
und auf Wunsch Erinnerungen als Push aufs Handy schickt. Reservierungen gehen
jetzt auch ohne Google-Kalender, und beschädigte Zeitdaten bringen die App nicht
mehr zum Absturz. Dazu kommen Korrekturen an „Zeiterfassung entfernen“, am
Einstellungen-Dialog und für Linux ohne AppImage.

### Hinzugefügt
- **Handy-Erfassung per Web-App**: Zeiten unterwegs auf dem Handy nachtragen,
  auch ohne Verbindung, und im selben WLAN mit der App abgleichen. Die Web-App
  läuft im Browser (`https://xveyn.github.io/Zeiterfassung/`, groß geschrieben),
  gekoppelt wird per QR-Code (Einstellungen → Mobil). Abgeglichen werden
  Ist-Zeiten, Reservierungen und die Kategorien samt Standardzeiten, jeweils in
  beide Richtungen; das Handy sieht standardmäßig die letzten 90 Tage und lädt
  ältere bis zu einer Obergrenze nach, die du am Rechner einstellst (höchstens
  365 Tage). Die Wochenansicht zeigt unter „Woche gesamt“ die noch ausstehende
  reservierte Zeit. Die Verbindung ist Ende-zu-Ende verschlüsselt; Geräte sind
  einzeln widerrufbar. **Chrome auf Android ist der unterstützte Weg**: Safari
  und Firefox öffnen die Seite und scannen den Code (auch ohne Barcode-Leser des
  Browsers), erreichen den Rechner danach aber nicht, iOS ist für die Web-App
  noch nicht vollständig funktionsfähig. Das Feature ist standardmäßig aus.
- **Erinnerungen als Push aufs Handy**: Reservierungs- und Sende-Erinnerungen
  kommen auf Wunsch als Benachrichtigung aufs Handy, auch wenn der Rechner aus
  ist (Einstellungen → Erinnerungen → „Handy“). Dafür läuft ein kleiner
  Weiterleitungsdienst im Internet, ein Cloudflare Worker (`relay/`); er kennt
  nur Zeitpunkte und einen Text, den nur das Handy entschlüsselt, keine
  Arbeitszeiten. Nur Chrome auf Android. Eine Testbenachrichtigung (Einstellungen
  → Mobil am Rechner oder in der Web-App) prüft den Weg.
- **Sende-Erinnerung im Kalender sichtbar**: Hängt an einer Reservierung die
  Erinnerung ans Verschicken, trägt die Tageszelle neben dem violetten einen
  bernsteinfarbenen Punkt; der Tooltip nennt Minuten und Uhrzeit.
- **Reservierungen ohne Google-Kalender**: „Reservierungen verwenden“ (Einstellungen
  → Arbeitszeit) schaltet die zukünftigen Soll-Zeiten ein, auch ohne Google.
  Ohne den Schalter sind sie in der App, der API und am Handy unsichtbar.
- **Lokale HTTP-API** (Einstellungen → API): Ein Server nur auf `127.0.0.1`, über
  den Skripte oder Taskplaner Zeiten lesen und eintragen, dazu Reservierungen,
  Urlaub und Auswertungen (Woche, Monat, Kategorien, Feiertage). Zugriff nur mit
  Token, nie aus dem Browser; standardmäßig aus. Beschreibung im README.
- **Hinweis nach Reparatur beschädigter Zeitdaten**: Repariert die App beim Start
  eine beschädigte Zeitdatei, sagt sie es einmal (Dialog, bei minimiertem Start
  ein Tray-Hinweis) und nennt, wo die Sicherungskopie liegt.

### Geändert
- **Tages-Dialog**: Neben „Speichern“ steht „Abbrechen“. Im Kategorien-Dialog
  heißt „Schließen“ jetzt „Abbrechen“, weil es ungespeicherte Änderungen
  verwirft.

### Behoben
- **Beschädigte oder fremde Zeitdaten**: Eine Zeitdatei, die kein JSON-Objekt war
  (Handbearbeitung, fremder Sync), verhinderte den Start; einzelne kaputte
  Einträge ließen Kalender, Berichte und Auswertungen abstürzen. Die App repariert
  beim Laden und legt vorher eine Sicherung ab (`zeiterfassung.json.corrupt-…`,
  die letzten fünf bleiben). Eine Datei aus dem Windows-Editor mit BOM gilt nicht
  mehr als beschädigt, eine kaputte Uhrzeit erscheint als `?-12:00`.
- **Zeiterfassung entfernen**: Unter macOS App Translocation nennt der Hinweis
  keinen unbrauchbaren Pfad mehr; ein vorgemerktes Update bleibt nicht in den
  Einstellungen zurück; der Bestätigungsdialog ist kurz gesperrt wie die
  Lösch-Rückfragen; ein zweiter Aufruf meldet keinen Sync mehr, den es nicht gibt.
- **App-Start**: Hintergrundaufgaben, die vor dem Fenster fertig wurden, gingen
  mit einem `RuntimeError` verloren, etwa der Umzug von Zugangsdaten in den
  Schlüsselbund.
- **Hauptfenster**: Es war rund 60 px zu breit. Die Kopfzeile zentriert sich jetzt
  im freien Platz zwischen den Knopfgruppen; der Titel versetzt sich leicht,
  sobald die Sync-Gruppe erscheint.
- **Einstellungen**: Der Dialog behält seine Breite, wenn sich ein Reiter nach dem
  Öffnen ändert; eine lange Absender-Adresse im Google-Reiter bricht um; das
  Mausrad scrollt das Formular nicht mehr unter einer offenen Auswahlliste.
- **„Update installieren“**: Der Fehlerdialog stürzte beim Anzeigen ab, sodass
  Grund und Browser-Download verloren gingen.
- **Linux ohne AppImage**: Menüeintrag, Hinweis beim Entfernen und Autostart-Pfad
  funktionieren auch mit einer gewöhnlichen Binärdatei.

### Intern
- **Dev-Builds prüfen nie auf Updates**: Ein Start aus dem Quellcode oder ein Build
  aus `build.yml` trägt die Version des letzten Releases, aber neueren Code, und
  bot sonst ein Pre-Release derselben Version als „Update“ an.
- **Zugangsdaten**: Alle Secret-Dateien laufen über einen Schreibpfad, der die
  Datei härtet, bevor das Geheimnis hineinkommt (unter Windows vorher geerbte
  Rechte). Die JSON-Stores schreiben unter Windows LF statt CRLF.
- **Relay**: Wird nach einem Merge auf `master` automatisch ausgerollt
  (`relay-deploy.yml`, Environment `relay-production`).
- **Web-App**: Build-Kennung `N/X.Y.Z (sha)` (Commits unter `pwa/` seit dem letzten
  Release, dessen Version, Commit); Veröffentlichung über GitHub Pages; der
  Dev-Server stempelt die Kennung selbst.
- **Abhängigkeiten und CI**: Pillow 13.0.0, Node 22 im PWA-Job.
- **Doku**: README, `SECURITY.md`, `CONTRIBUTING.md`, `docs/known-limitations.md`
  und die `CLAUDE.md`-Dateien zu Handy-Erfassung, Relay und API; neue Screenshots
  von Desktop und Web-App.
