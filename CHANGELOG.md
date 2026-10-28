# Changelog

Ältere Versionen stehen im [Archiv](CHANGELOG-archive.md).

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

## 1.24.0 — 2026-10-06

Die App folgt jetzt der Anzeigeskalierung des Systems — unter Windows scharf,
unter Linux nicht mehr winzig —, unter macOS und Linux lässt sie sich aus den
Einstellungen heraus vollständig entfernen, und neue Kategorien lassen sich
direkt im Tages-Dialog anlegen. Dazu kommen Korrekturen bei Rundung, Tooltips
und dem Schlüsselbund.

### Hinzugefügt
- **Windows: Anzeigeskalierung ohne Unschärfe**: Die App übernimmt die
  Skalierung von Windows (125 %, 150 % …) und zeichnet ihre Schrift in der
  echten Auflösung, statt das Fenster als Bild zu strecken. Der Regler
  „UI-Skalierung" gilt jetzt *obendrauf*: 100 % heißt „wie Windows". Wer
  vorher einen eigenen Wert eingestellt hat, sieht die App gleich groß wie
  zuvor, nur schärfer. Bei mehreren Bildschirmen mit unterschiedlicher
  Skalierung streckt Windows auf dem zweiten weiterhin; ein Wechsel der
  Windows-Skalierung wirkt erst nach einem Neustart der App.
- **Linux: Desktop-Skalierung wird übernommen**: Auf skalierten Desktops
  (X11/XWayland) erschien die App bisher winzig. Sie folgt jetzt der
  Einstellung des Desktops (`Xft.dpi`), ohne doppelt zu skalieren; wo der
  Desktop selbst streckt, bleibt alles wie bisher. Ein zuvor hochgedrehter
  „UI-Skalierung"-Wert wird beim ersten Start einmalig umgerechnet, damit die
  App nicht doppelt so groß wird.
- **Zeiterfassung entfernen (macOS und Linux)**: Einstellungen → App →
  „Zeiterfassung entfernen" räumt Schlüsselbund, Zugangsdaten, Autostart und
  Menüeintrag ab, auf Wunsch auch Zeiten, Einstellungen und Protokoll, und
  beendet die App. Die Programmdatei löschst du danach selbst — die App nennt
  den Pfad (unter Linux samt Terminal-Befehl) und lässt ihn kopieren. Bleibt
  der Datenordner wegen fremder Dateien stehen, steht das in der
  Zusammenfassung. Unter Windows übernimmt das wie bisher die Deinstallation.
  Eine Schritt-für-Schritt-Anleitung steht im README.
- **Neue Kategorie direkt im Tages-Dialog**: Das Kategorie-Dropdown hat als
  letzten Eintrag „＋ Neue Kategorie". Er öffnet den Kategorien-Dialog; die
  neu angelegte Kategorie ist danach in der Zeile ausgewählt. Das Mausrad
  überspringt den Eintrag, er lässt sich nur anklicken.

### Behoben
- **Wochenlimit und Pausenpflicht: Rundungsfehler**: Beide rechneten mit auf
  0,01 h gerundeten Werten und lösten bei exakt 6:00 h falsch aus — eine
  Wochensumme von genau 6 h über einem Limit von 6 h warnte, und exakt 6 h
  Arbeitszeit verlangten 30 Minuten Pause, obwohl § 4 ArbZG erst *über* 6 h
  greift. Gerechnet wird jetzt in Minuten.
- **Tooltips**: Beim schnellen Überfahren des Kalenders flackerten sie und
  zeigten unter Linux (KDE) weiße Rechtecke; sie erscheinen jetzt nach einer
  kurzen Verzögerung. Am Bildschirmrand werden sie nicht mehr abgeschnitten,
  und ein Feiertag mit Sync-Konflikt zeigt nur noch einen Tooltip statt zwei.
- **Schlüsselbund bei „Immer im Vordergrund"**: Der Passwort-Dialog des
  Systems (KWallet, GNOME Keyring) lag unter dem Hauptfenster und blieb
  unsichtbar, bis die Abfrage ablief. Das Fenster gibt den Vordergrund jetzt
  frei, solange der Schlüsselbund fragt.
- **Webhook-Zugangsdaten beim Start**: Der Umzug in den Schlüsselbund konnte
  mit dem Speichern oder Löschen eines Webhooks zusammenstoßen — ein gelöschter
  Webhook tauchte wieder auf, ein frisch eingegebenes Geheimnis wurde
  überschrieben.
- **Speichern von Webhook und SMTP-Konto**: Ein unerwarteter Fehler ließ den
  Speichern-Knopf dauerhaft gesperrt, ohne Meldung. Jetzt erscheint der Fehler.
- **Sync-Zeitüberschreitung**: Dauerte der Abgleich zu lange, erschien ein
  heller Fehlerdialog mit dem Text „Timeout". Jetzt gibt es eine verständliche
  Meldung im Dunkel-Design.
- **Einstellungen nach Skalierungswechsel**: Nach dem Speichern einer anderen
  Skalierung erschien „Unerwarteter Fehler: TclError", obwohl die App sauber
  neu startete.
- **Einstellungen sprangen auf**: Der Dialog wurde nach dem Öffnen plötzlich
  breiter, sobald die Prüfung der Google-Anmeldung antwortete.
- **Vergrößerte Darstellung**: Reservierungs-Markierung und Lösch-Knopf (✕) in
  den Kalenderzellen wuchsen nicht mit.
- **Urlaub: Kalender-Aufräumen**: Scheiterte das Entfernen der Urlaubstermine
  im Google Kalender, während der Dialog schon zu war, erfuhr man nichts davon.
- **Auto-Update**: Ein vorgemerktes Update gehörte womöglich zu einer älteren
  Version als der, die der Hinweis nannte; beim Beenden wurde dann die ältere
  installiert.

### Intern
- **Logs im Terminal**: Wer die App aus dem Quellcode startet
  (`python -m src.main`), sieht die Log-Zeilen jetzt auch im Terminal;
  `ZEITERFASSUNG_LOG_LEVEL=DEBUG` macht sie ausführlicher.
- **Installer und Test-Builds**: Das Setup zeigt Kanal und Commit des Builds
  (z. B. `1.24.0-pre.2`) im Assistenten und unter „Apps & Features".
- **Coverage**: Für die Tk-freien Module gilt in der CI jetzt eine
  Untergrenze.
- **Plattform-Labels** für Pull Requests (macOS, Linux, KDE, GNOME, Windows)
  und ein Abschnitt zu KI-generiertem Code in `CONTRIBUTING.md`.
