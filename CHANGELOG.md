# Changelog

Ältere Versionen stehen im [Archiv](CHANGELOG-archive.md).

## 1.28.0 — 2026-11-09

Die Handy-Web-App kann sich jetzt selbst vom Rechner trennen, bekommt eine
App-Sperre, einen Einrichtungs-Screen und ein Debug-Protokoll und ist
überarbeitet. Unter Linux weist die App auf eine geänderte Skalierung hin, wenn
du den Monitor wechselst.

### Hinzugefügt
- **Handy trennen**: Die Web-App hat unter Einstellungen → Verbindung „Trennen
  und lokale Daten löschen“. Nach einer Rückfrage (die zuerst abgleicht und sagt,
  wie viele Änderungen noch nicht am Rechner sind) meldet sich das Handy am
  Rechner ab und löscht alle Daten auf dem Handy; danach steht wieder der
  Einrichtungs-Screen da. Der Rechner widerruft das Gerät, räumt Schlüssel,
  Relay-Box und Push-Objekt ab und meldet es: als Dialog bei sichtbarem Fenster,
  als Toast im Infobereich bei verstecktem, sonst im Log. Einstellungen → Mobil
  führt das Gerät als „vom Handy getrennt“, bis du es mit „Entfernen“ aus der
  Liste nimmst. Über den Relay liegt die Abmeldung in der Box, bis sich der
  Rechner verbindet. Dafür gibt es die neue Route `POST /v1/unpair`; die
  Sync-Antwort nennt die Fähigkeit `unpair`, an der die Web-App einen älteren
  Rechner erkennt (das Protokoll bleibt bei Version 2).
- **Linux: Hinweis bei Monitorwechsel mit anderer Skalierung**: Wechselst du
  zwischen Monitoren mit verschiedener Skalierung (etwa WQHD und 4K), blieb die
  App bisher zu groß oder zu klein, bis zum nächsten Start. Jetzt prüft sie alle
  fünf Sekunden `Xft.dpi` und zeigt bei Abweichung ein Banner „Skalierung passt
  nicht zum Monitor“ mit „Neu starten“. Einstellungen → App → „Skalierung bei
  Monitorwechsel automatisch anpassen“ (Standard: aus) lässt die App stattdessen
  selbst neu starten, sobald kein Dialog offen ist und nichts im Hintergrund
  läuft; ein verstecktes Fenster bleibt dabei versteckt. Windows (#493) und
  macOS folgen nicht.
- **Web-App: App-Sperre**: Optional (Einstellungen → Verbindung) verlangt die
  Web-App nach einer wählbaren Frist die Entsperrung mit der Bildschirmsperre des
  Handys. Ein Neuladen innerhalb der Frist fragt nicht erneut. Eine
  Komfort-Sperre für die Oberfläche: die gespeicherten Daten werden dadurch nicht
  verschlüsselt.
- **Web-App: Einrichtungs-Screen**: Statt eines Formulars zeigt die Web-App vor
  dem Koppeln die Schritte für das jeweilige Gerät (Chrome, Firefox, Safari, auf
  dem iPhone zuerst die Installation).
- **Web-App: Debug-Protokoll**: Einstellungen → Debug zeigt den technischen
  Zustand und ein lokales Protokoll der letzten Fehler und Abgleiche, bereinigt
  um Adressen, Namen und Zeiten aus Einträgen. Kopieren, als Datei teilen,
  löschen, Haltezeit einstellbar; es verlässt das Handy nie von selbst.
- **Web-App: überarbeitete Oberfläche**: Wochenansicht mit schließbarem
  Speicher-Hinweis und Einladung auf leeren Tagen, Tages-Editor mit Netto-Zeit,
  Feldfehlern und Schnellwahl und dem Wochentag im Titel, Einstellungen als
  Vollbild mit Zurück-Geste, Zustandskarte im Reiter Verbindung, kurze
  Übergänge, bessere Kontraste und kein hängendes Hover auf Touch-Geräten. Die
  Pause an Reservierungen (seit 1.27.0 am Rechner) gibt es jetzt auch in der
  Web-App; „Noch ausstehend“ rechnet netto.

### Behoben
- **Autostart unter Linux**: Der Eintrag lag fest unter `~/.config/autostart`.
  Die Desktop-Umgebung liest aber `$XDG_CONFIG_HOME/autostart`; bei abweichendem
  Wert startete die App nie. Der Eintrag liegt jetzt dort (nur absolute Werte,
  sonst `~/.config`), Einstellungen → App zeigt seinen Pfad.
- **Über Relay koppeln**: Der Koppel-Dialog schließt nur noch die eigene
  Sitzung und bleibt bei Ablehnung oder Fehler bedienbar; der Zustand
  „verdrängt“ nennt Ursache und Ausweg.
- **Push über den Relay**: Die Nachricht wird nicht mehr auf 4096 Byte
  aufgefüllt (Mozilla antwortete mit 413); die Testbenachrichtigung nennt bei
  einem Fehler die Ursache. Firefox auf Android ist damit geprüft.
- **Web-App, Neuladen mit App-Sperre**: Wischen zum Aktualisieren verlangte jedes
  Mal die Entsperrung; innerhalb der Frist nicht mehr.

### Bekannte Grenzen
- Trennen im WLAN: Ist der Rechner dabei nicht erreichbar, erfährt er nichts
  davon; das Gerät bleibt in der Liste, bis du es dort widerrufst oder entfernst.
  Die Rückfrage sagt das vorher. Näheres unter
  [Handy trennen](docs/known-limitations.md#handy-trennen-499-bekannte-grenzen).
- Der Toast beim Trennen braucht den Infobereich (Windows, Linux mit
  StatusNotifier); unter macOS ist er bis zum Opt-in `ZEIT_MACOS_TRAY=1` aus,
  dort bleiben Dialog bei sichtbarem Fenster und die Geräteliste.
- Firefox zeigt in der Push-Benachrichtigung kein Logo.

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
  seine Pause; fehlt die Eigenschaft (bestehende Termine) oder ist sie nicht kleiner
  als die Zeitspanne (Termin in Google gekürzt), ist sie 0. Beim ersten
  Abgleich nach dem Update wird kein Termin umgeschrieben.
- **Handy-Abgleich und lokale API**: Beide nehmen `pause` je Reservierungs-Slot
  an und liefern sie immer mit. Die Sync-Antwort trägt die neue Fähigkeit
  `reservation_pause`, an der ein Handy erkennt, dass der Desktop Pausen kennt
  (das Protokoll bleibt bei Version 2). Fehlt `pause` an einem Slot, erbt er die
  bisherige Pause nur, wenn am selben Platz ein Slot mit gleichem Start und Ende
  steht, sonst 0; in der lokalen API ist eine ungültige Pause `422 invalid_pause`
  (im Handy-Abgleich `422 invalid_entry`).

### Bekannte Grenzen
- Eine ältere Handy-Version kennt die Pause nicht: ändert sie Start oder Ende
  einer Reservierung, wird deren Pause auf 0 gesetzt. Bleibt die Zeit gleich,
  bleibt die Pause erhalten. Ebenso verliert die Pause der Slots, die nachrücken,
  wenn eine ältere Handy-Version einen Slot löscht, einfügt oder umsortiert (geerbt
  wird nur am selben Platz bei gleichem Start und Ende).
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
