# Changelog

Ältere Versionen stehen im [Archiv](CHANGELOG-archive.md).

## 1.30.0 — 2026-11-27

Krankheitstage lassen sich jetzt eintragen. Sie gleichen sich zwischen den
Geräten und mit dem Handy ab, und auf Wunsch stehen sie im Bericht. Dazu kommt
ein neues App-Icon.

### Hinzugefügt
- **Krankheitstage**: Krankheit lässt sich als Zeitraum eintragen, über
  „Krank melden“ im Tages-Dialog oder unter Einstellungen → Arbeitszeit →
  „Krankheit verwalten“. Ist ein Tag als Urlaub eingetragen, bietet die Meldung
  dort ebenfalls „Krank melden“ an.
  - **Stunden je Tag**: Die App schlägt sie vor, wahlweise aus der
    Standardzeit des Wochentags oder dem Durchschnitt der letzten drei Monate.
    Liegt am Tag eine Reservierung, zählen deren Stunden. Wochenenden und
    Feiertage zählen 0. Jeder Tag lässt sich anpassen.
  - **Hinweise**: Die App kürzt nichts selbst. Sie weist darauf hin, dass die
    Entgeltfortzahlung in der Regel nach sechs Wochen endet und dass die
    Stunden ein Vorschlag sind.
  - **Kalender**: Krankheit hat dort eine eigene Farbe und gewinnt über Urlaub,
    Feiertag und Wochenende. Ein Linksklick öffnet den Zeitraum, ein Rechtsklick
    löscht ihn.
  - **Sperren**: An einem Krankheitstag lässt sich keine Arbeitszeit erfassen,
    und ein neuer Urlaub lässt sich nicht über Krankheitstage legen.
  - **Reservierungen**: Liegen im Zeitraum Reservierungen, bietet die Meldung
    an, sie zu löschen.
- **Krankheit im Bericht**: Mit dem neuen Häkchen „Krankheit ausweisen“ in
  Senden und Export bekommen Mail, PDF und Webhook einen eigenen
  Krankheits-Block, und „Zu vergüten gesamt“ zählt die Krankheitsstunden mit.
  Liegt Urlaub auf einem Krankheitstag, zählt dort nur die Krankheit. Ohne das
  Häkchen bleiben Bericht, PDF und Webhook genau wie bisher.
- **Krankheitstage auf allen Geräten**: Sie reisen per Drive-Sync zu deinen
  anderen Rechnern und gleichen sich mit dem Handy ab. In der Web-App meldest
  du Krankheit, siehst sie in der Woche und entfernst sie wieder. Die Stunden
  rechnet der Rechner. Ältere Versionen auf anderen Geräten laufen ohne
  Einschränkung weiter, sie sehen die Krankheitstage nur nicht.
- **Lokale API**: Neue Routen `GET`/`POST /v1/sick` und `DELETE /v1/sick/{Datum}`.
  Die Auswertungen enthalten die Krankheitsstunden (`sick_minutes`).

### Geändert
- **Neues App-Icon**: ein Kalenderblatt mit Uhr auf dunkler Kachel, in allen
  Größen scharf, auch in der Web-App. Die Bilder im README sind neu aufgenommen.
- **Datenschutzhinweise**: Ein neuer Abschnitt erklärt, wo Krankheitstage
  gespeichert werden und wann sie das Gerät verlassen.
- **Relay**: Eine Box, die 14 Tage lang nicht benutzt wird, räumt sich selbst
  auf (bisher 90 Tage). Ist der Rechner länger aus, kommen die letzten
  Handy-Änderungen mit dem nächsten Abgleich des Handys an.

### Behoben
- **Zeitpunkte in Ortszeit**: Der Konfliktdialog, Einstellungen → Mobil und der
  Import-Dialog zeigten Zeitpunkte in UTC statt in deiner Ortszeit, im Winter
  eine Stunde und im Sommer zwei Stunden daneben. Das gilt auch für die Web-App.
- **Einstellungen → API**: Die Routenübersicht zeigt die Methoden in einer
  eigenen Spalte. Die Pfade stehen damit sauber untereinander.
- **Web-App: Reservierung vom Rechner löschen**: Eine Reservierung, die vom
  Rechner kam, ließ sich am Handy nicht dauerhaft löschen. Beim nächsten Abgleich
  stand sie wieder da.
- **Protokoll**: Im ausführlichen Protokoll (`ZEITERFASSUNG_LOG_LEVEL=DEBUG`)
  stand beim PDF-Export der Inhalt des Berichts. Er steht dort nicht mehr.

## 1.29.1 — 2026-11-25

### Behoben
- **Linux: 1.29.0 startete nicht**: Die AppImage von 1.29.0 brach unter Linux-Systemen mit
  glibc vor 2.42 (etwa Debian 13 und Ubuntu 24.04) direkt beim Start ab (`GLIBC_2.42 not
  found`), weil der Build-Rechner von GitHub auf Ubuntu 26.04 gewechselt war. 1.29.1 wird wieder
  auf Ubuntu 24.04 gebaut und läuft wie 1.28.0. Wer 1.29.0 unter Linux bereits installiert hat
  und die App nicht mehr starten kann, lädt die AppImage von 1.29.1 von der Release-Seite und
  ersetzt die alte Datei; die Daten bleiben unberührt. Windows und macOS waren nicht betroffen.

## 1.29.0 — 2026-11-25

Ein Zeitblock kann jetzt eine Notiz tragen, am Rechner und auf dem Handy, und
der Bericht schlüsselt auf Wunsch je Notiz auf. Die Slots eines Tages stehen
chronologisch, nach Kategorie oder in einer eigenen Reihenfolge.

### Hinzugefügt
- **Notiz am Slot**: Jeder Zeitblock der Arbeitszeit kann eine einzeilige Notiz
  tragen, die die Kategorie verfeinert (Kategorie „Montage“, Notiz „Kunde
  Mustermann“), höchstens 200 Zeichen. Im Tages-Dialog steht dafür ein Feld mit
  Vorschlägen aus den bisher benutzten Notizen (die der gewählten Kategorie
  zuerst). Die Notiz erscheint im Tooltip der Kalenderzelle, im Löschen-Dialog,
  im Konfliktdialog und im Bericht (in der Kategorie-Spalte, keine neue Spalte);
  der Webhook trägt sie am Slot (`notiz`, nur wenn vorhanden), die lokale API
  liest und schreibt sie. Reservierungen und das Teilen von Arbeitszeiten bleiben
  ohne Notiz.
- **Bericht: „Nach Notiz aufschlüsseln“**: Unter „Nach Kategorie aufschlüsseln“
  im Senden- und Export-Dialog; die „Summe je Kategorie“ bekommt dann Unterzeilen
  je Notiz. Der Schalter erscheint nur, wenn es überhaupt eine Notiz gibt.
- **Notiz auf dem Handy**: Die Web-App zeigt Notizen in der Woche (als eigene
  Zeile oder hinter der Kategorie, Einstellungen → Verbindung → „Notizen“) und in
  den Konflikten, und im Tages-Editor gibt es dasselbe Feld mit aufklappbarer
  Liste der bisherigen Notizen. Die Web-App bietet das nur an, wenn der Rechner
  diese Version hat; Notizen am Rechner, die das Handy noch nicht kennt, bleiben
  beim Abgleich erhalten.
- **Reihenfolge der Slots**: Einstellungen → Arbeitszeit → „Slots eines Tages“:
  chronologisch (Standard), nach Kategorie oder eigene Reihenfolge, die du im
  Tages-Dialog mit ▲/▼ festlegst. Die Einstellung reist per Drive-Sync, und das
  Handy zeigt die Slots in derselben Reihenfolge. Die Liste der Kategorien lässt sich im Kategorien-Dialog
  ebenfalls mit ▲/▼ ordnen; die Reihenfolge gilt in allen Auswahllisten.
- **Web-App: Zeiten per Wisch verschieben**: Ein waagerechter Zug auf den
  Zeitfeldern eines Slots verschiebt Start und Ende gemeinsam; die Schrittweite
  (oder aus) steht unter Einstellungen → Verbindung.

### Behoben
- **Slots eines Tages**: Ein später angelegter früherer Slot stand bisher hinter
  den vorhandenen; die Slots werden jetzt in der gewählten Reihenfolge angezeigt
  und gespeichert.
- **Web-App: Updates kamen nicht an**: Änderte ein Update nur die Build-Kennung,
  startete Chrome den neuen Service Worker nicht und die Web-App blieb auf dem
  alten Stand. Die Kennung steht jetzt auch im Hauptskript, und die Update-Suche
  umgeht den HTTP-Cache.
- **Web-App: Zeitfelder auf dem iPhone** überlappten in der Slot-Zeile nicht mehr.
- **Web-App: Erinnerung trotz eingetragener Zeit**: Eine am Handy eingetragene
  Ist-Zeit nimmt die zugehörige Erinnerung jetzt sofort heraus, auch wenn der
  Rechner aus ist.

### Bekannte Grenzen
- Notizen und ältere Versionen: Ändert eine ältere App-Version die Startzeit
  eines Slots oder löscht ihn, geht dessen Notiz verloren; in seltenen
  Reihenfolgen mit drei Geräten kann eine gelöschte oder geänderte Notiz
  zurückkommen. Einzelheiten unter
  [Slot-Notizen](docs/known-limitations.md#slot-notizen-519-bekannte-grenzen).
- Geteilte Arbeitszeiten kommen ohne Notizen an.

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
