# Changelog

Ältere Versionen stehen im [Archiv](CHANGELOG-archive.md).

## 1.30.1 — 2026-11-28

### Behoben
- **Tages-Dialog zu breit**: Seit den Notizen war der Tages-Dialog deutlich
  breiter als nötig, auch ganz ohne Slot. Die Notiz steht jetzt in einer
  eigenen Zeile unter ihrem Slot und zeigt dort mehr Text. Jeder Slot steht in
  einem Rahmen, damit klar ist, welche Notiz zu welchem Slot gehört.
- **Kalender: abgeschnittene Zeiten**: Bei mehreren Slots an einem Tag war die
  Zeitzeile ohne eingetragenen Stundenlohn links und rechts abgeschnitten.
  Passt sie nicht in die Zelle, zeigt die Zelle jetzt den Beginn und die Zahl
  der weiteren Slots („08:00 +2“). Alle Slots stehen weiter im Tooltip.
- **Web-App: Krankheitsstunden in der Woche**: Unter „Woche gesamt“ steht jetzt
  eine eigene Zeile „Krankheit“ mit den Krankheitsstunden der Woche.
  „Woche gesamt“ bleibt die Arbeitszeit.

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
