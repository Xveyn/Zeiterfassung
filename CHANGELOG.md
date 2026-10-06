# Changelog

Ältere Versionen stehen im [Archiv](CHANGELOG-archive.md).

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
