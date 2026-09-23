# Changelog

Ältere Versionen stehen im [Archiv](CHANGELOG-archive.md).

## 1.23.3 — 2026-09-23

Ein Wartungs-Release rund um die Einstellungen: der Dialog ist neu
geordnet und speichert tabweise, und bei vergrößerter Darstellung wachsen
Dialoge jetzt auch in die Breite. Dazu kommen einige Korrekturen unter Linux.

### Geändert
- **Einstellungen neu geordnet**: sechs statt sieben Tabs — Arbeitszeit,
  Erinnerungen, Versand, Google, App, Updates —, jeder nach demselben Aufbau
  mit Abschnitten. Optionen, die von einem Schalter abhängen, sind
  eingerückt und grau, solange der Schalter aus ist. Wird der Inhalt zu
  lang, scrollt er, statt dass der Dialog über den Bildschirm hinauswächst.
  Der Gmail-Empfänger steht jetzt unter „Gmail“, denn für SMTP-Konten und
  Webhooks galt er nie. „Sync-Daten kompaktieren“ steht abgesetzt unter
  „Erweitert“, weil es Einträge endgültig entfernt.
- **Speichern je Tab**: „Speichern“ übernimmt nur den gerade offenen Tab,
  und der Dialog bleibt offen. Ohne Änderungen ist der Knopf grau. Wer einen
  geänderten Tab verlässt oder den Dialog schließt, wird gefragt:
  Speichern, Verwerfen oder Zurück. „Abbrechen“ heißt jetzt „Schließen“.
- **„Nur Werktage“ wirkt sofort**: Die Zeilen für Samstag und Sonntag
  verschwinden gleich, nicht erst beim nächsten Öffnen.
- **Teilen**: Der Tooltip sagt jetzt, wofür der Knopf da ist — eine Datei
  zum Import in eine andere Zeiterfassung, egal ob auf dem eigenen zweiten
  Gerät oder bei einer anderen Person.

### Behoben
- **Vergrößerte Darstellung: Dialoge wurden nur höher, nicht breiter.**
  Meldungen brachen bei 200 % in doppelt so viele Zeilen um, statt breiter
  zu werden, und die Abstände in den Knöpfen blieben klein. Jetzt wächst
  beides mit.
- **„Daten importieren“ verwarf ungespeicherte Einstellungen**: Der Dialog
  schloss sich dabei und nahm Änderungen ohne Rückfrage mit. Jetzt bleibt er
  offen.
- **Google-Fehler als Traceback**: Fehlte `credentials.json` oder das Netz,
  zeigten Sync, Kalender und Anmeldung einen technischen Fehlerbericht. Jetzt
  steht dort, was fehlt — mit „Datenordner öffnen“ bei fehlenden
  Zugangsdaten.
- **Senden ohne Ziel**: Die Meldung nennt jetzt auch den Webhook als
  mögliches Ziel.
- **Teilen: falscher Weg in der Mail**: Die Mail zum Teilen verwies auf
  „Einstellungen → Daten importieren“. Der Knopf liegt seit dem Neuschnitt
  unter „Einstellungen → App → Daten importieren“.
- **Linux: Wochentage sprangen beim Blättern**: Die Kopfzeile Mo–So zuckte
  in der Monatsansicht bei jedem Monatswechsel kurz zur Seite.
- **Linux: Start ohne grafische Sitzung** (etwa per SSH) brach mit einer
  nichtssagenden Meldung ab. Jetzt steht im Terminal, dass ein Display fehlt.
- **Sync: gleichzeitige Änderung auf zwei Geräten**: Änderten zwei Geräte
  denselben Tag in derselben Sekunde, behielt jedes vorläufig einen anderen
  Wert. Jetzt ist das Ergebnis auf beiden gleich; der Konflikt wird wie
  bisher gemeldet.

### Intern
- **Gebaut mit Python 3.12** statt 3.10, das im Oktober 2026 ausläuft.
- **Neue Screenshots** im README, aufgenommen mit Demo-Daten
  (`scripts/demo_data.py`).

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
