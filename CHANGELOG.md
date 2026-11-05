# Changelog

Ältere Versionen stehen im [Archiv](CHANGELOG-archive.md).

## 1.27.0 — 2026-11-05

Reservierungen tragen jetzt eine Pause. Sie steht im Tages-Dialog, im Tooltip,
im Handy-Abgleich und in der lokalen API; der Google-Kalender-Termin bleibt
dabei brutto.

### Hinzugefügt
- **Pause an Reservierungen**: Jeder Reservierungs-Slot hat eine optionale Pause
  (ganze Minuten, Standard 0, kürzer als die Zeitspanne). Der Tages-Dialog zeigt
  im Reservierungs-Block eine Pausenspalte, der Kalender-Tooltip nennt die Pause
  ab 1 Minute. Neue Zeilen bekommen die Standardpause der Kategorie bzw. die
  allgemeine; der Vorschlag für eine Ist-Zeit aus einer Reservierung übernimmt
  deren Pause.
- **Google-Kalender-Termin bleibt brutto**: Der Termin deckt weiter Start bis
  Ende ab, die Pause wird nicht abgezogen. Die Beschreibung nennt sie
  („Zeitspanne brutto, Pause N min nicht abgezogen“), die Pause selbst liegt in
  einer privaten Eigenschaft des Termins. Gewinnt beim Abgleich der Termin, gilt
  seine Pause; fehlt die Eigenschaft (bestehende Termine), ist sie 0. Beim ersten
  Abgleich nach dem Update wird kein Termin umgeschrieben.
- **Handy-Abgleich und lokale API**: Beide nehmen `pause` je Reservierungs-Slot
  an und liefern sie immer mit. Die Sync-Antwort trägt die neue Fähigkeit
  `reservation_pause`, an der ein Handy erkennt, dass der Desktop Pausen kennt
  (das Protokoll bleibt bei Version 2). Fehlt `pause` an einem Slot, erbt er die
  bisherige Pause nur, wenn am selben Platz ein Slot mit gleichem Start und Ende
  steht, sonst 0; eine ungültige Pause ist `422 invalid_pause`.

### Bekannte Grenzen
- Eine ältere Handy-Version kennt die Pause nicht: ändert sie Start oder Ende
  einer Reservierung, wird deren Pause auf 0 gesetzt. Bleibt die Zeit gleich,
  bleibt die Pause erhalten.
- Teilen überträgt keine Pause, ein Import setzt die Pause des importierten
  Tages auf 0.
- Ein älterer Desktop gibt die Pause beim Umschreiben von Kalenderterminen nicht
  weiter; wer zwei Desktops in unterschiedlichen Versionen nutzt, sollte beide
  aktualisieren.

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
