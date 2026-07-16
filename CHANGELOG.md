# Changelog

## 1.18.1 — 2026-07-16

### Hinzugefügt
- **Sync-Konflikte**: Linksklick auf einen Kalendertag mit ungelöstem Konflikt
  öffnet jetzt direkt den Konflikt-Dialog, gefiltert auf genau diesen Tag —
  vorher nur über Einstellungen → Google erreichbar.

### Geändert
- **Updates-Tab**: Der Changelog wird jetzt auch ohne verfügbares Update
  angezeigt (für die installierte Version); Markdown wird lesbar formatiert
  (fette Überschriften/Bullet-Titel) statt roh angezeigt.
- **Tages-Dialog**: Arbeitszeit und Reservierung teilen sich jetzt einen
  einzelnen „Speichern"-Button statt je einem eigenen. Das Kategorie-Dropdown
  zeigt ein Sternchen, wenn die Slot-Zeiten manuell vom Kategorie-Standard
  abweichen.

### Behoben
- **Header**: Die Monat/Jahr-Anzeige rutscht nicht mehr, wenn beim
  Synchronisieren der Status-Text rechts wechselt.
- **Drive-Sync**: Verbindungsabbrüche/Timeouts werden jetzt korrekt als
  Netzwerkfehler erkannt und zeigen die passende „Keine Internetverbindung"-
  Meldung statt eines rohen Fehlerdialogs.
- **Sync-Konflikte**: Der Kalender aktualisiert sich jetzt sofort, nachdem ein
  Konflikt aufgelöst wurde (vorher blieb die Zelle auf altem Stand).

## 1.18.0 — 2026-07-15

### Hinzugefügt
- **Updates-Tab**: Der Einstellungen-Dialog hat jetzt einen fünften Tab
  „Updates". Dort lässt sich der Update-Status manuell prüfen, die
  Hintergrund-Häufigkeit auf täglich / wöchentlich / monatlich / nie stellen
  und bei einer neueren Version direkt der passende Changelog-Abschnitt lesen.
- **Monatliche Erinnerung „Arbeitszeiten verschicken"**: Optionaler Toast an
  einem frei wählbaren Tag im Monat plus Uhrzeit. Kürzere Monate werden sauber
  auf den letzten Tag geklemmt.

### Geändert
- **Update-Hinweise**: Läuft ein aktives Infobereich-Icon als Toast-Kanal,
  erscheint ein einmaliger Toast statt eines dauerhaften Banners; ohne aktives
  Tray bleibt das Banner der Fallback. Versionen, die bereits im Updates-Tab
  gesehen wurden, nerven danach nicht noch einmal per Banner oder Toast.
- **Einstellungen**: Der Tab-Satz ist um „Updates" erweitert; dort liegt jetzt
  auch die konfigurierbare Update-Check-Häufigkeit.
- **Senden / Teilen / Export**: Die längeren Mail-/PDF-Aktionen laufen jetzt
  im Hintergrund, statt die Oberfläche währenddessen zu blockieren.

### Behoben
- **Updates-Tab**: Ohne verfügbares Update bleibt kein leeres Changelog-Feld
  mehr sichtbar.
- **Monatlicher Sende-Reminder**: Ungültige `HH:MM`-Werte im Setting werden
  defensiv abgefangen, statt den Scheduler aus dem Tritt zu bringen.
- **Bericht / Sicherheit**: Start- und Endwerte im Bericht werden korrekt
  escaped, statt eingebettetes HTML ungefiltert zu übernehmen.
- **Gmail-Start**: Der initiale Absender-/Profil-Check löst keinen
  `403 insufficientPermissions` mehr aus, wenn nur die tatsächlich benötigten
  Scopes vorliegen.
- **Mail-Empfänger**: Adressen mit CR/LF-Steuerzeichen werden jetzt
  zurückgewiesen, statt still bereinigt weiterzulaufen.
- **Windows-Token-Persistenz**: Transiente `PermissionError` beim Schreiben von
  `token.json` werden abgefangen und erneut versucht, statt den OAuth-Pfad
  unnötig scheitern zu lassen.
- **Fensterbreite**: Der Footer mit Stundenlohn lässt die Fensterbreite nicht
  mehr sichtbar springen; die Breite wächst jetzt stabil auf den Maximalbedarf.
- **Feiertags-Lookup**: Eine transiente `FileNotFoundError` im
  Übersetzungs-Ladepfad wird defensiv abgefangen, statt den Feiertagsabruf zu
  stören.
- **Settings-/Sync-Robustheit**: Korruptes `settings.json` wird in Quarantäne
  verschoben, und die Sync-Apply-Sequenz ist crash-sicherer bzw.
  threadsicherer gegen gleichzeitige Datenzugriffe.
- **Einzelinstanz / Sicherheit**: Der lokale SHOW/PING-Handshake der
  Einzelinstanz ist jetzt per Shared Secret abgesichert.
- **Google-Auth**: Der Token-Info-Check übermittelt das Access-Token jetzt per
  POST-Body statt als URL-Query.
- **Linux-Autostart**: Die `Exec=`-Zeile der `.desktop`-Datei wird
  shell-korrekt gequotet.

### Intern
- `CHANGELOG.md` kann für eine neue Version jetzt zur Laufzeit direkt vom
  GitHub-Tag geladen und abschnittsweise geparst werden.
- Release-nahe Checks sind enger abgesichert: `ruff`/`pyright` decken den
  neuen Updates-Tab samt UI-Routing mit ab.

## 1.17.0 — 2026-07-03

### Hinzugefügt
- **PDF-Export**: Der Bericht für einen frei gewählten Zeitraum lässt sich jetzt
  direkt als PDF lokal speichern — über den neuen „Export"-Eintrag im Footer und
  im Tray-Menü, ohne Mail-Versand.
- **Reservierungs-Erinnerungen**: Optionale Benachrichtigung (Toast), wenn ein für
  heute reservierter Slot fällig wird und dafür noch keine Ist-Zeit erfasst ist —
  mit einstellbarer Vorlaufzeit in Minuten. Das Infobereich-Icon läuft dafür auch
  dann, wenn nur die Erinnerungen aktiv sind (nicht „in den Infobereich
  minimieren").
- **Wochenstunden-Limit** (Werkstudenten): In den Einstellungen lässt sich ein
  maximales Wochenstunden-Kontingent für einen konfigurierbaren Zeitraum
  hinterlegen. Beim Speichern einer Ist-Zeit und nach einem Google-Kalender-Abgleich
  warnt die App, wenn eine Woche das Limit überschreitet (gezählt werden nur
  Ist-Zeiten, keine Reservierungen).
- **UI-Skalierung**: Ein Schieberegler in den Einstellungen skaliert die gesamte
  Oberfläche stufenweise; die Änderung greift nach einem kurzen Neustart und wirkt
  auf allen Plattformen (inklusive macOS). Der Faktor ist gerätelokal und wird
  nicht synchronisiert.
- **Kategorie-Standardzeiten pro Wochentag**: Die Standard-Start/-Endzeit einer
  Kategorie lässt sich jetzt optional pro Wochentag (Mo–So) hinterlegen, umschaltbar
  über einen Modus-Toggle im Kategorien-Dialog. Der Eintrags-Dialog zieht beim
  Anlegen automatisch die passende Zeit für den jeweiligen Wochentag.
- **Kategorie-Aufschlüsselung im Bericht optional**: Die „Summe je Kategorie" im
  Bericht lässt sich beim Senden und Exportieren an- und abschalten; liegen nur
  unkategorisierte Slots vor, entfällt die Tabelle automatisch.

### Geändert
- **Einstellungen in Reitern**: Der Einstellungen-Dialog ist in vier Tabs gegliedert
  (Arbeitszeit / Bericht & Mail / Google / App) — statt einer einzigen langen Liste.
- **Autostart & Einzelinstanz** (Windows): Der Autostart läuft jetzt über einen
  Registry-Eintrag, den App und Installer gemeinsam nutzen — dadurch kann kein
  doppelter Autostart-Eintrag mehr entstehen, der beim Hochfahren zwei Instanzen
  parallel startete. Die Autostart-Checkbox in den Einstellungen zeigt jetzt den
  tatsächlichen Zustand an, auch wenn er über den Installer gesetzt wurde. Eine
  bestehende Alt-Verknüpfung im Autostart-Ordner wird beim ersten Start automatisch
  übernommen. Zusätzlich läuft die App jetzt immer nur einmal: Ein zweiter Start
  holt das vorhandene Fenster nach vorn, statt eine zweite Instanz zu öffnen.
- **Arbeitszeit-Tooltip**: Der Hover-Tooltip im Kalender zeigt die erfasste
  Arbeitszeit schon ab einem einzelnen Slot (vorher erst bei mehreren).

### Behoben
- Reservierungen lassen sich per Linksklick nicht mehr für bereits vergangene Tage
  anlegen.
- Bericht-PDF: Die Stundentabelle kollabiert die linken Spalten nicht mehr.
- Update-Banner: Das Fenster wächst jetzt um die Banner-Höhe, sodass der Footer
  sichtbar bleibt (vorher konnte er abgeschnitten werden).
- Kleinere Dialog-Interaktionen: Die Löschen-Rückfrage ist auch bei nur einer
  betroffenen Einheit einen kurzen Moment gesperrt (gegen versehentliches
  Sofort-Bestätigen), und ein Zellen-Tooltip schließt jetzt zuverlässig, sobald
  sich ein modaler Dialog darüber öffnet.

### Intern
- Natives macOS-Infobereich-Icon (NSStatusItem) als Backend vorbereitet — vorerst
  ruhend und nur per Opt-in (`ZEIT_MACOS_TRAY=1`) aktivierbar, bis das macOS-Gate
  durchlaufen ist; ein Main-Thread-Absturz des macOS-Trays wurde behoben.
- Pre-Release-Builds: Der Release-Workflow kann jetzt plattformübergreifende
  Test-Builds erzeugen (fortlaufender `-pre.N`-Tag, als Pre-Release markiert und vom
  Auto-Updater ignoriert), um Änderungen vor einem echten Release auf allen
  Plattformen zu testen.
- `SYNCED_SETTING_KEYS` als Single Source of Truth in `settings.py`; die
  Save-Pfad-Logik des Einstellungen-Dialogs ist headless testbar extrahiert.

## 1.16.1 — 2026-06-25

### Behoben
- Es wird jetzt zu jedem Zeitpunkt nur **ein Tooltip gleichzeitig** angezeigt —
  beim schnellen Überfahren mehrerer Elemente bleibt kein zweiter mehr stehen.
- Import: Die Erfolgsmeldung erscheint wieder zuverlässig, statt gelegentlich
  mit einem Fehler abzubrechen (der Dialog wurde zu früh geschlossen).
- Info- und Fehler-Dialoge (Senden, Teilen, Einstellungen, Import, Tray-Einrichtung)
  erscheinen jetzt einheitlich im App-Design statt als native System-Dialoge.

### Intern
- Die UI-Schicht (`ui.py`) wurde in eigenständige Komponenten entflochten
  (Kalender-Rendering, Hintergrund-Tasks, Drive-Sync, Update-Banner) — ohne
  funktionale Änderung, für bessere Wartbarkeit. Details: [`src/CLAUDE.md`](src/CLAUDE.md).
- Das OAuth-Token-Handling für Gmail/Drive/Kalender liegt jetzt in einem
  gemeinsamen Helfer (`src/oauth_utils.py`); Token werden atomar geschrieben.

## 1.16.0 — 2026-06-23

### Hinzugefügt
- Mehrere Zeitblöcke pro Tag mit eigenen Kategorien — für Arbeitszeiten und
  Reservierungen. Pro Kategorie lassen sich Standard-Start/-Ende und -Pause
  hinterlegen („Kategorien verwalten"), die beim Anlegen neuer Slots automatisch
  greifen.
- Im Bericht: Kategorie-Spalte, Tages-Summen und eine „Summe je Kategorie".
  Beim Senden und Teilen lässt sich nach Kategorie filtern.
- Reservierungen erzeugen je Slot ein eigenes Google-Kalender-Event (Kategorie
  im Titel).

### Geändert
- Der Footer- und Tray-Eintrag „Monat senden" heißt jetzt „Arbeitszeiten
  senden".
- Bestehende Einträge und Reservierungen werden beim ersten Start automatisch
  ins neue Format übernommen — wer keine Kategorien oder mehrere Slots nutzt,
  merkt nichts.

### Behoben
- Das Setzen einer Kategorie überschreibt gespeicherte Slot-Zeiten nicht mehr.
- Bearbeiten einer Reservierung aktualisiert das bestehende Kalender-Event,
  statt es zu löschen und neu anzulegen.
- Fehlt `credentials.json`, erscheint auch beim Absender-„Anmelden/
  Aktualisieren" der freundliche Hinweis mit „Datenordner öffnen".
- Multi-Geräte-Sync zwischen unterschiedlichen App-Versionen überschreibt keine
  Daten mehr: ein neueres Datenformat wird auf älteren Geräten pausiert
  („Update erforderlich"), ein neueres Gerät übernimmt ein älteres Drive-
  Dokument verlustfrei und zieht es aufs neue Format hoch.

## 1.15.2 — 2026-06-23

### Behoben
- Multi-Geräte-Sync: Beim Hochladen wird der aktuelle Stand aus Google Drive
  jetzt zuerst gelesen und zusammengeführt, statt ihn blind zu überschreiben.
  Dadurch kann ein älteres Gerät die Daten eines Geräts mit neuerem Datenformat
  nicht mehr versehentlich überschreiben, und gleichzeitige Änderungen auf
  mehreren Geräten gehen beim Speichern nicht mehr verloren.

## 1.15.1 — 2026-06-23

### Behoben
- Multi-Geräte-Sync: Nutzt ein Gerät bereits eine neuere App-Version mit einem
  neueren Datenformat, pausiert die Synchronisation auf älteren Geräten jetzt
  mit einem klaren Hinweis („Update erforderlich"), statt mit einem Fehler
  abzubrechen oder Daten zu überschreiben. Das gilt für den Abgleich ebenso wie
  für das Kompaktieren der Sync-Daten. Die vollständige Synchronisation läuft
  wieder, sobald alle Geräte aktualisiert sind.

## 1.15.0 — 2026-06-19

### Hinzugefügt
- Schnellaktionen im Infobereich-Menü (Tray): „Monat senden", „Teilen…" und
  „Mit Google Drive synchronisieren" lassen sich direkt über das Tray-Icon
  auslösen, ohne das Hauptfenster zu öffnen. Das Sync-Ergebnis erscheint als
  Windows-Benachrichtigung (Toast) mit App-Logo. (Der Sync-Eintrag ist nur bei
  aktivierter Synchronisation sichtbar.)
- Veröffentlichte Releases enthalten jetzt eine `SHA256SUMS`-Datei zur
  Integritätsprüfung der heruntergeladenen Dateien.

### Geändert
- Einheitliches Löschen im Kalender: Rechtsklick auf einen Tag löscht – immer
  mit Rückfrage. Liegen Arbeitszeit und Reservierung am selben Tag, fragt ein
  Auswahldialog, was gelöscht werden soll. Der Tages-Dialog (Linksklick) dient
  auf Windows/Linux nur noch dem Anlegen/Bearbeiten; seine Lösch-Schaltflächen
  sind entfallen. Auf macOS bleiben sie erhalten (Rechtsklick ist dort
  systembedingt unzuverlässig).
- Die Dialoge des „Sync-Daten kompaktieren"-Vorgangs erscheinen jetzt im dunklen
  App-Design statt als helle System-Meldungen.
- Selbst gebaute bzw. aus dem Quellcode gestartete Versionen weisen sich im
  Fenstertitel mit „-dev" (samt Commit-Kürzel) aus; offizielle Releases zeigen
  unverändert nur die Versionsnummer.

### Behoben
- Versehentliche Klicks direkt nach dem Schließen eines Dialogs lösen keine
  ungewollte Aktion mehr aus: Der Kalender ignoriert für einen kurzen Moment
  Klicks, sodass der Schließen-Klick nicht auf einer dahinterliegenden Zelle
  „durchschlägt".

## 1.14.1 — 2026-06-15

### Hinzugefügt
- Der heutige Tag wird im Kalender hervorgehoben: Die heutige Zelle erhält in
  Monats- und Wochenansicht einen blauen Rahmen — klar abgesetzt von
  Eintrags- (rot), Feiertags- (grün), Reservierungs- (violett) und
  Konflikt-Markierung (orange).

## 1.14.0 — 2026-06-02

### Hinzugefügt
- Teilen umfasst jetzt auch Reservierungen: Über „Teilen" lassen sich
  Arbeitszeiten, Reservierungen oder beide als JSON-Datei verschicken. Beim
  Import kann der Empfänger jeden Datentyp einzeln an- oder abwählen und für
  jeden die gewohnte Konflikt-Behandlung (alles übernehmen / alles lokal / pro
  Tag) wählen. Bereits verschickte Alt-Dateien (nur Arbeitszeiten) bleiben
  importierbar.
- Schaltfläche „Google neu verbinden" in den Einstellungen: erneuert die
  Google-Berechtigungen (Drive/Gmail/Kalender) per frischer Anmeldung. Nötig,
  wenn der gespeicherte Zugriff eine inzwischen benötigte Berechtigung nicht
  abdeckt — ein bloßes Aus-/Einschalten der Synchronisation hat das vorher
  nicht behoben.

### Behoben
- Synchronisations-Fehlermeldungen: Bei abgelaufenem oder widerrufenem
  Google-Token (oder fehlender Internetverbindung) erscheint jetzt eine
  verständliche, ins App-Theme integrierte Meldung mit Hinweis zum Neuverbinden
  — statt eines rohen Python-Tracebacks im weißen Systemdialog. Greift sowohl
  beim Drive-Sync (Pull, Push, Push beim Schließen) als auch beim
  Google-Kalender-Abgleich. Unerwartete Fehler zeigen weiterhin den Traceback.
- Fehlende Google-Berechtigung (HTTP 403): Eine nicht abgedeckte
  Drive-Berechtigung wurde fälschlich als Netzwerkfehler bzw. als roher
  Traceback angezeigt. Sie erscheint jetzt als verständliche Meldung mit
  Verweis auf „Google neu verbinden".

### Geändert
- Datumsanzeigen durchgehend im deutschen Format: Sync-Status, „Letzte
  Synchronisation", das Export-Datum sowie die Tagesdaten im Pro-Tag-Schritt
  des Import-Dialogs erscheinen als `TT.MM.JJJJ`, Konflikt-Zeitstempel als
  `TT.MM.JJJJ HH:MM` — statt im ISO-Format.

### Intern
- `reservations.json` wird nun von Git ignoriert (persönliche Nutzerdaten).

## 1.13.2 — 2026-06-02

### Behoben
- Wochenansicht: Die Tageszellen sprangen beim Wechsel zwischen Monats- und
  Wochenansicht leicht in der Breite — die Spalten richten sich jetzt in beiden
  Ansichten identisch aus.

### Geändert
- Wochenansicht: Die Zeitzeile der Einträge nutzt dieselbe Schriftgröße wie die
  Monatsansicht, und Tagesziffer/Zeitzeile sitzen vertikal an derselben Position.

## 1.13.1 — 2026-06-02

### Behoben
- Wochenansicht: Die Tageszellen waren höher als in der Monatsansicht. Beide
  Ansichten rendern jetzt gleich hohe Zellen.

### Geändert
- Copyright-Halter in der MIT-Lizenz auf „MargenHeld GmbH" präzisiert.

### Intern
- GitHub-Actions-Workflows auf Node-24-Runtime angehoben (`checkout@v6`,
  `setup-python@v6`, `upload-artifact@v7`, `download-artifact@v8`), bevor
  GitHub Node 20 zum 16.09.2026 von den Runnern entfernt.

## 1.13.0 — 2026-06-01

### Hinzugefügt
- MIT-Lizenz: Das Repository steht jetzt explizit unter der MIT-Lizenz
  (`LICENSE`), README mit Badge und Lizenzabschnitt. Der Build erzeugt zudem
  automatisch eine `THIRD-PARTY-NOTICES.txt` (via `pip-licenses`) und liefert
  sie in jedem Installer mit (Windows-Setup, macOS-App-Bundle, AppImage).

### Geändert
- Beim Anlegen einer Arbeitszeit an einem bereits reservierten Tag werden
  Start/Ende mit den Reservierungszeiten vorbelegt statt mit den Standardzeiten
  des Wochentags — eine Reservierung überschreibt also die Standardzeiten.

### Behoben
- Hover-Tooltip im Kalender blieb sichtbar über allen Fenstern hängen, wenn das
  Hauptfenster ohne Mausbewegung minimiert (bzw. in den Infobereich geklappt)
  oder der Kalender neu gerendert wurde. Das Tooltip schließt jetzt zusätzlich
  bei minimiertem/weggeklapptem Fenster und beim Zerstören der Kalenderzelle.

## 1.12.2 — 2026-06-01

### Dokumentation
- Sicherheitshinweis in der README zu `token.json` (enthält im Klartext einen
  langlebigen OAuth-Refresh-Token; wer den Daten-/Installationsordner kopiert,
  sichert oder cloud-synct, nimmt diesen Token mit — inkl. Widerruf-Anleitung).
- README und `CLAUDE.md` auf den aktuellen Feature-Stand gebracht: Teilen/Import
  und Reservierungen/Google-Kalender in der Feature-Liste, Projektstruktur auf
  den realen `src/`-Stand (kein nicht-existentes `Zeiterfassung.spec` mehr).
- `planned-features.md`: „Teilen + Import" als umgesetzt (v1.12.0) markiert.
- `docs/gmail-setup.md`: `userinfo.email`-Scope ergänzt.
- Spec und Implementierungsplan für das geplante Auto-Update-Feature ergänzt
  (noch keine Implementierung — reine Planung).

_Keine Verhaltensänderung an der App — reiner Doku-Release._

## 1.12.1 — 2026-05-28

### Behoben
- Combobox-Dropdowns: Scrollbar, Popdown-Border und Pfeil-Button im Dark-Theme statt heller System-Standard
- Roter Fokusrand in Eingabefeldern verschwindet beim Klick auf Dialog-Hintergrund — gilt jetzt überall, nicht mehr nur in Settings
- App-Icon (margenheld) in allen Modal-Dialogen — statt Tk-Standard-Feder
- Token-Fehlermeldungen beim App-Start im App-Theme statt heller System-Messagebox

### Geändert
- Escape-Taste schließt alle Modal-Dialoge (Eintrag, Settings, Senden, Teilen, Import, Konflikte)
- Modal-Dialoge zeigen in der Titelleiste nur noch den Close-Button — keine ausgegrauten Min/Max-Schaltflächen mehr (Windows)

## 1.12.0 — 2026-05-14

### Hinzugefügt
- Multi-Device-Sync via Google Drive (opt-in). Zeiteinträge und Mail-Settings
  synchronisieren über einen versteckten Ordner in deinem Drive (`appDataFolder`).
  Pull beim App-Start, Push manuell oder beim Schließen.
- Konflikt-Behandlung: Wenn derselbe Tag auf zwei Geräten offline bearbeitet wird,
  erscheinen beide Versionen in einem Konflikt-Dialog zur manuellen Auswahl.
- Sync-Button und Status-Anzeige im Header (nur sichtbar bei aktivem Sync).
- Geräte-ID wird einmal pro Installation generiert (siehe Einstellungen).
- Absender-E-Mail wird automatisch aus dem authentifizierten Google-Konto übernommen — kein manuelles Eintragen mehr. „Aktualisieren"-Button in den Einstellungen, falls der Scope noch fehlt oder das Konto gewechselt wurde
- Neue Einstellung „Immer im Vordergrund" — App-Fenster bleibt über anderen Anwendungen
- Neue Einstellung „Beim Schließen in den Infobereich minimieren" (Windows + macOS) — Tray-Icon mit Anzeigen-/Beenden-Menü ersetzt das tatsächliche Beenden, bis du es willst
- Themed Success-Popup nach erfolgreichem Mail-Versand (statt System-Messagebox)
- Themed Bestätigungs-Dialog (Ja/Nein) beim Löschen eines Eintrags (statt System-Messagebox)
- Dunkle Titelleiste auf Windows 11 22H2+ (über DWM)
- Tooltip auf truncated Feiertagsnamen — Hover zeigt den vollen Namen
- Arbeitszeiten an eine zweite Person teilen: neuer Footer-Button „Teilen…". Versendet eine JSON-Datei mit den eigenen Einträgen per Mail; der Empfänger wird direkt im Teilen-Dialog eingegeben.
- Arbeitszeiten aus einer Share-Datei importieren: Einstellungen → „Arbeitszeiten importieren…", mit Zeitraum-Filter und drei Konflikt-Modi (alles importieren / alles lokal / pro Tag entscheiden). Anwenden ist atomar — Abbruch im Pro-Tag-Modal hinterlässt keinen Teilzustand.
- Reservierungen: zukünftige Arbeitszeiten lassen sich pro Tag im Tages-Dialog
  reservieren — ein eigenständiges Konzept neben den erfassten Ist-Zeiten.
  Reservierungen werden im Kalender als violetter Eck-Punkt am Tag markiert und
  sind über das Tages-Modal einsehbar.
- Google-Kalender-Anbindung: in den Einstellungen aktivierbar; Reservierungen
  werden mit einem wählbaren Google Kalender abgeglichen. Push überschreibt die
  Remote-Kalender-Einträge — Synchronisierung funktioniert geräteübergreifend
  über den Kalender.

### Geändert
- Kalender-Spaltenbreiten sind jetzt strikt unabhängig vom Zellen-Inhalt — Einträge, Feiertage und leere Tage haben identische Pixel-Breite, kein visueller Versatz mehr je nach Text
- Monatsansicht mit eingeblendeten Wochenenden: Zeit-Schrift in Eintragszellen größer (8pt statt 7pt) für bessere Lesbarkeit; Feiertagsnamen mit kleinerem Font (im 7-Spalten-Modus)
- Wochenansicht: Feiertagsnamen werden enger truncated, sodass „Christi Himmelfahrt" nicht mehr über den Zellrand läuft
- Settings-Dialog: Klick auf nicht-interaktive Bereiche (Labels, Frame-Bg) entfernt den roten Fokusrand vom zuletzt aktiven Eingabefeld
- Dialog-Position wird an die Bildschirmgrenzen geklammert — das Settings-Modal wird nicht mehr unten/oben abgeschnitten, wenn das Hauptfenster nah am Bildschirmrand sitzt (auf Windows respektiert die Klammerung die Taskleiste)
- Fehler beim Sync-Push beim Schließen werden jetzt als Messagebox sichtbar (vorher still verschluckt)
- Tages-Dialog zeigt einen neuen „Reservierung"-Sektor mit Start/Ende-Feldern, unabhängig von den Ist-Arbeitszeiten. Reservierungen können auch gelöscht werden.
- Schlägt „Monat senden" oder „Teilen…" mangels Internetverbindung fehl, erscheint jetzt eine verständliche „Keine Internetverbindung"-Meldung statt eines technischen Tracebacks. Andere Fehler zeigen weiterhin die Detail-Ausgabe.

### Hinweise
- Aktivierung erfordert einen erneuten Google-OAuth-Consent mit erweiterten Scopes
  (`drive.appdata` für Sync, `userinfo.email` für Absender-Auto-Fetch — beide non-sensitive).
- Beim Aufräumen alter Einträge wachsen Tombstone-Marker derzeit unbeschränkt —
  siehe `docs/known-limitations.md`.

## v1.11.1
- Neue Option in den Einstellungen: „Wochenende (Sa/So) im Kalender anzeigen". Wenn deaktiviert, fallen Sa und So aus der Monats- und Wochenansicht weg, das Fenster wird entsprechend schmaler. Bestehende Wochenend-Einträge bleiben gespeichert und werden weiterhin in Mail/PDF exportiert — nur die Kalender-Anzeige ändert sich. Default: angezeigt (kein Verhaltenssprung für Bestandsnutzer)
- Das „Absender"-Feld in den Einstellungen wurde entfernt. Es hatte keine Wirkung — die Absender-Adresse wird zwingend vom Gmail-OAuth-Token bestimmt (`userId=me`), das eingetragene Feld wurde nie als `From:`-Header gesetzt. Ein evtl. vorhandener Wert in `settings.json` wird beim nächsten Settings-Speichern still entfernt

## v1.11.0
- macOS: alle Buttons rendern jetzt im Dark-Theme statt als native Aqua-Buttons (Header `‹ › ⚙`, Monat/Woche-Toggle, Footer „Monat senden", Dialog-Buttons, Update-Banner). Bisher war der Text auf primären und aktiven Buttons unter macOS weiß auf weiß und damit unlesbar — der Grund: das Aqua-Backend ignoriert `bg`/`fg` für `tk.Button` und zeichnet sie nativ. Die App benutzt jetzt Label-basierte Custom-Buttons, die auf allen Plattformen das Theme respektieren
- Font-Familie wird plattformabhängig gewählt: Windows „Segoe UI", macOS „Helvetica Neue", Linux „DejaVu Sans". Verhindert stille Fallback-Drift der Pixel-Metriken in den Kalenderzellen, wenn die Default-Familie nicht installiert ist

## v1.10.3
- Beim Umschalten zwischen Monats- und Wochenansicht schrumpft das Fenster jetzt sofort auf die richtige Höhe (vorher blieb beim ersten Monat→Woche-Wechsel die Monatshöhe stehen, bis ein weiterer Refresh innerhalb der Wochenansicht erfolgte). Hintergrund: der inaktive Double-Buffer-Frame wird beim View-Wechsel komplett ersetzt statt nur ausgeräumt — Tk's reqheight-Cache hielt sonst die alte Höhe trotz Cleanup

## v1.10.2
- Eintrags-Dialog zeigt den „Löschen"-Button nur noch, wenn der Tag tatsächlich einen Eintrag hat — bei leeren Tagen war der Button vorher sichtbar, hatte aber keine Funktion

## v1.10.1
- Monats- und Wochenansicht flackern beim Navigieren nicht mehr: Header (Monatsname / KW-Label), Footer-Stunden und Tageszellen behalten ihre Position, wenn sich der Inhalt zwischen Monaten oder Wochen ändert. Hintergrund: Labels und Zellen haben jetzt fixe Pixel-/Zeichenbreiten, sodass der Pack-Manager bei Text-Wechseln keine Layout-Reflows mehr triggert
- Feiertagsanzeige weitet die Kalenderspalten in der Monatsansicht nicht mehr auf — analog zur Wochenansicht sind Feiertagszellen pixel-fixiert mit Wraplength als Sicherheitsnetz für lange Namen
- Wochenansicht-Header: das KW-Label nutzt jetzt eine kleinere Schrift (12pt bold), damit z.B. „KW 19 · 04.05. – 10.05.2026" auch bei Jahreswechseln vollständig ins Fenster passt — vorher wurde der Text rechts und links abgeschnitten

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
