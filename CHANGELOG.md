# Changelog

Ältere Versionen stehen im [Archiv](CHANGELOG-archive.md).

## 1.23.2 — 2026-09-18

Ein Wartungs-Release: Zugangsdaten liegen nicht mehr im Klartext im
Datenordner, das Infobereich-Icon ist nach dem Test auf KDE Plasma unter Linux
freigeschaltet, und eine Reihe von Fehlern ist behoben — die meisten davon
unter Linux gefunden.

### Geändert
- **Zugangsdaten im Schlüsselbund des Betriebssystems**: Die Google-Anmeldung
  und die Zugangsdaten von Webhooks liegen jetzt in der
  Anmeldeinformationsverwaltung (Windows), im Schlüsselbund (macOS) bzw. im
  Secret Service (Linux: KWallet, GNOME Keyring) — nicht mehr im Klartext in
  `token.json` und `webhooks.json`. Bestehende Zugangsdaten zieht die App beim
  ersten Start nach dem Update selbst um und sagt einmal Bescheid. Ohne
  Schlüsselbund bleibt alles wie bisher.

  Zwei Dinge, die man wissen sollte: Wer danach **auf eine ältere Version
  zurückgeht**, muss Google einmal neu verbinden und Webhook-Zugangsdaten neu
  eingeben — die alte Version findet sie im Schlüsselbund nicht. Und **macOS**
  fragt nach App-Updates womöglich erneut, ob die App auf den Schlüsselbund
  zugreifen darf.
- **Infobereich-Icon unter Linux**: Das Tray-Icon (Minimieren in den
  Infobereich, Menü, Erinnerungen als Benachrichtigung) ist unter Linux nicht
  mehr hinter einer Test-Einstellung versteckt. Es schaltet sich ein, sobald
  der Desktop einen Infobereich für App-Icons hat — KDE Plasma und XFCE von
  Haus aus, GNOME mit der Erweiterung „AppIndicator and KStatusNotifierItem
  Support". Fehlt er, sagt die App beim Einschalten, woran es liegt.
- **Deinstallation (Windows)**: Sie entfernt jetzt auch die Einträge im
  Schlüsselbund und die SMTP-Konten (`smtp.json`), und „Daten löschen" nimmt
  die Urlaubszeiträume mit.

### Behoben
- **Jeder Start öffnete die Google-Anmeldung im Browser**: War die
  Google-Anmeldung abgelaufen, riss der Kalender-Abgleich beim Start jedes Mal
  ein Freigabe-Fenster auf. Ein Freigabe-Fenster erscheint jetzt nur noch als
  Folge eines Klicks.
- **Update wurde doppelt geladen**: Ein Klick auf den Update-Hinweis, während
  die App das Update beim Start schon still herunterlud, startete denselben
  Download ein zweites Mal.
- **Stundenlohn-Hinweis überlappte das Eingabefeld** bei vergrößerter
  Darstellung (Einstellungen → Arbeitszeit).
- **Linux: Neustart nach geänderter Skalierung stürzte ab** — die App kam
  nach dem Ändern der Skalierung nicht wieder hoch.
- **Linux: weißer Rand um Häkchen-Felder** in allen Dialogen.

## 1.23.1 — 2026-09-12

Ein Wartungs-Release: lauter Stellen, an denen die App entweder etwas
Falsches behauptet oder unaufgefordert etwas getan hat.

### Hinzugefügt
- **Zeile „Anmeldung" im Google-Tab**: Die Einstellungen sagen jetzt, ob die
  Google-Anmeldung überhaupt noch trägt — „gültig", „nicht angemeldet",
  „abgelaufen" oder „nicht prüfbar (offline)". Sie ergänzt die Zeile
  „Berechtigungen" darüber, ersetzt sie nicht: die sagt, *welche* Freigaben
  erteilt sind, diese, *ob* die Anmeldung noch funktioniert. Genau diese
  Unterscheidung fehlte — Freigaben vollständig, Anmeldung tot. Geprüft wird
  beim Öffnen, ohne Browser; lässt sich die Anmeldung still erneuern, tut die
  App das dabei und meldet „gültig".

### Behoben
- **Der Haken neben dem Sync-Datum behauptete zu viel**: Im Kopf des Fensters
  stand ein ✓ vor dem Datum der letzten Synchronisation — auch wenn diese
  „noch nie" stattfand oder Wochen zurücklag. Gerade im wichtigen Fall war
  das falsch: Ist die Google-Anmeldung abgelaufen, scheitert der Abgleich
  beim Start stillschweigend, das Datum bleibt stehen, und der Haken
  versicherte weiter, alles sei aktuell. Jetzt steht das ✓ nur noch für
  „heute abgeglichen"; alles andere bekommt ein ⚠ in Bernstein, und ein
  Tooltip sagt, was los ist. Bleibt die App über Mitternacht offen, wechselt
  die Anzeige von selbst.
- **Die Einstellungen rissen ungefragt den Browser auf**: War die
  Google-Anmeldung abgelaufen und der Kalender-Abgleich aktiv, öffnete allein
  das Öffnen der Einstellungen ein Google-Freigabefenster im Browser. Jetzt
  fragt die App dort nicht mehr nach — sie vermerkt in der Kalender-Zeile,
  dass eine Anmeldung nötig ist. Ein Freigabe-Fenster erscheint nur noch als
  Folge eines Klicks.
- **Google-Fehlermeldungen waren roher Maschinentext**: Beim Start konnte ein
  Dialog erscheinen, in dem dreimal „invalid_grant" stand und aus dem nicht
  hervorging, was zu tun ist (nämlich nichts — die App holt die Freigabe beim
  nächsten Senden selbst). Derselbe Text landete im Tray-Hinweis. Beide sagen
  jetzt in einem Satz, was passiert ist.
- **Titelleiste blitzte beim Öffnen von Dialogen hell auf** (Windows): Für
  einen Sekundenbruchteil erschien die helle Standard-Titelleiste, bevor sie
  dunkel wurde. Dialoge werden jetzt unsichtbar aufgebaut und erst gezeigt,
  wenn sie fertig eingefärbt sind. Beim Hauptfenster kann das Aufblitzen
  weiterhin auftreten.

### Intern
- **Release-Notizen kommen aus dem CHANGELOG**: Der Text eines Releases ist
  jetzt dieser Abschnitt statt einer generierten Liste von Pull-Requests. Die
  beschreibt die Arbeit, der CHANGELOG beschreibt die Änderung — und
  geschrieben wird er ohnehin.
- **README auf Nutzer zugeschnitten**, alles Entwicklerische nach
  `CONTRIBUTING.md`.
- **Veraltete Stellen in der Projektdokumentation nachgezogen**, dazu ein
  Test, der die exakten Werte darin gegen den Code hält.

## 1.23.0 — 2026-09-08

### Hinzugefügt
- **SMTP-Versand**: Berichte lassen sich jetzt zusätzlich zur Gmail-API über
  einen eigenen Mail-Server verschicken (Einstellungen → „SMTP“). Mehrere
  Konten mit je eigenem Empfänger sind möglich, jedes einzeln aktivierbar und
  im Sende-Dialog einzeln anwählbar; ein „Verbindung testen“-Button prüft
  Server und Zugangsdaten direkt im Dialog, ohne eine Mail zu verschicken.
  Passwörter liegen im Schlüsselbund des Betriebssystems; steht keiner zur
  Verfügung, fällt die App auf eine lokal gehärtet geschriebene Datei zurück
  und sagt das beim Speichern. Auch der Teilen-Dialog kann wahlweise über ein
  SMTP-Konto statt über Gmail versenden — der im Konto hinterlegte Empfänger
  ist dort vorbelegt und überschreibbar. Gmail muss dadurch nicht mehr
  zwingend eingerichtet sein: wer ausschließlich SMTP nutzt, kommt ohne
  `credentials.json` aus. Nicht möglich sind Microsoft-Konten (Outlook.com,
  Microsoft 365) — Microsoft hat SMTP mit Passwort abgeschaltet; für Gmail
  wird ein App-Passwort gebraucht. SMTP-Konten gelten nur auf diesem Gerät
  und reisen **nicht** über den Drive-Sync mit.
- **Update aus der App** (Windows und Linux): Der Download-Knopf — im
  Updates-Tab, im Banner und im Tray-Toast — installiert das Update jetzt
  selbst, statt nur den Browser zu öffnen. Die App lädt das passende
  Release-Asset, prüft es gegen die `SHA256SUMS`-Datei des Releases und
  installiert es: unter Windows über den stillen Installer, unter Linux durch
  Ersetzen der laufenden AppImage (mit Rollback, falls etwas schiefgeht).
  Danach startet sie neu. Optional erledigt sie das von selbst: ist „Updates
  automatisch installieren“ eingeschaltet, lädt sie ein geprüftes Update im
  Hintergrund und wendet es erst beim nächsten Beenden an — nie mitten in der
  Arbeit, und ohne die App danach unaufgefordert wieder zu öffnen. Unter
  macOS bleibt es beim Download im Browser. Die Prüfsumme schützt gegen
  abgebrochene und verfälschte Übertragung, **nicht** gegen ein
  kompromittiertes Release: die Updates sind an keiner Stelle signiert, der
  Vertrauensanker bleibt die verschlüsselte Verbindung zu GitHub — derselbe
  wie beim Download im Browser.
- **Stundenzeile an Urlaubstagen abschaltbar**: Neuer Schalter „Stunden an
  Urlaubstagen im Kalender anzeigen“ im Dialog „Urlaub verwalten“.
  Abgeschaltet bleibt der Zeitraum als durchgehender Block mit „Urlaub“
  stehen, die Stunden stehen weiterhin im Tooltip. Gerätelokal wie die
  übrigen Urlaubs-Einstellungen.

### Geändert
- **Sendeziele nach Kanal gruppiert**: Der Sende-Dialog listete Gmail,
  SMTP-Konten und Webhooks flach untereinander — ein SMTP-Konto namens „Büro“
  war dort von einem Webhook gleichen Namens nicht zu unterscheiden. Die
  Ziele stehen jetzt unter den Überschriften „Gmail“, „SMTP“ und „Webhooks“.
- **Pre-Releases im Updates-Tab**: Ein Pre-Release hat keinen kuratierten
  Changelog-Eintrag. Statt eines „Changelog:“-Kastens mit dem rohen
  GitHub-Text — samt Autorenangaben und URLs, die im schmalen Feld nur
  umbrachen — stehen dort jetzt unter „Enthaltene Änderungen:“ die reinen
  Titel der enthaltenen Änderungen.

### Behoben
- **Urlaub und Arbeitszeit am selben Tag wurden doppelt vergütet**: Liegt an
  einem Tag beides, zählten Urlaubs- und Ist-Stunden in „Zu vergüten gesamt“
  nebeneinander — der Kalendertag kam damit auf mehr Stunden, als er hat. Die
  App verhindert diese Kombination an den Eingabewegen, über einen Import
  oder einen Sync vom Zweitgerät konnte sie aber trotzdem entstehen (der
  Urlaub ist gerätelokal, der Absender kennt ihn nicht). An solchen Tagen
  wird der Urlaub jetzt um die erfasste Arbeitszeit gekürzt — und beide
  Stellen sagen es: eine Hinweiszeile im Sende- und Export-Dialog und eine
  Fußnote unter dem Urlaubs-Block im Bericht.
- **Falsches Update-Asset auf Intel-Macs und ARM-Linux**: Der Download-Knopf
  bot die Datei der jeweils anderen Architektur an (arm64-DMG auf einem
  Intel-Mac, x86_64-AppImage auf ARM-Linux) — beide laufen dort nicht.
  Passt keine Datei zur Architektur, führt der Knopf jetzt auf die
  Release-Seite.
- **KW-Header verdeckte den „Woche“-Umschalter**: In der Wochenansicht legte
  sich das zentrierte Kalenderwochen-Label über den Umschalter daneben,
  sobald es breit genug wurde.

### Intern
- **Konvention für Catch-all-Handler**: Jeder `except Exception`-Zweig
  loggt, meldet oder trägt eine Begründung im Handler selbst — durchgesetzt
  von einem Test, nicht vom Linter.
- **Harte Angaben in `CLAUDE.md` sind jetzt Assertions**: Exakte Werte, die
  auch im Code stehen (Required Checks, Mutex-Name, Matrix-Spanne,
  Tool-Pins), prüft ein Test gegen den Code, damit sie nicht lautlos
  auseinanderlaufen.
- **Dependabot für GitHub Actions**: Actions-Updates laufen automatisch,
  Python-Abhängigkeiten bleiben bewusst Handarbeit (jede Version muss
  Python 3.10 unterstützen).
- **Versionsmarker der README**: Noch nicht veröffentlichte Features tragen
  auf der Startseite den Platzhalter `--VERSION--` statt einer geratenen
  Versionsnummer; ein Workflow hält den Release-PR an, solange einer offen
  ist, und ein zweiter räumt überholte Marker später wieder weg.
