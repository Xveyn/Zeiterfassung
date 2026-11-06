# Handy-Web-App: Debug-Reiter mit lokalem, bereinigtem Protokoll

Stand: 2026-11-06 · Status: Entwurf, geprüft von einem unabhängigen Leser, noch nicht freigegeben

## Anlass und Ziel

Die Update-Suche der Web-App scheitert auf Android/Chrome oft, auf Firefox nicht. Die Ursache ist
unbelegt (#390). Heute steht der Fehlertext nur in der Konsole (`logFailure`, über `chrome://inspect`
lesbar) und kurz im Reiter „Updates“; ein späterer Blick auf einen früheren Fehler ist nicht möglich,
und ohne Rechner am Handy gar nicht.

Ziel: Ein neuer Reiter **„Debug“** in den Einstellungen zeigt den technischen Zustand der Web-App
und ein Protokoll der letzten Fehler und Abgleiche. Der Nutzer kann es kopieren, als Datei teilen und
löschen. Es enthält **nichts Personenbezogenes** und verlässt das Gerät nie von selbst.

Die Frage, die es beantworten soll, wenn wieder etwas schiefgeht: *Welcher Fehler trat wann auf, in
welcher Umgebung, und wie oft?*

## Entscheidungen des Nutzers

- Ein Debug-Bereich in den Einstellungen, **eigener vierter Reiter** (Skizze A gewählt).
- Technisch alles Relevante, aber datenschutzkonform.
- **Nicht ins Protokoll:** Adressen (IP-Adressen, Hostnamen, Web-Adressen, auch Relay und Push-Dienst),
  Namen (Gerätename, Kategorien, Personen) und Zeiten aus echten Einträgen (Tage, Start/Ende, Stunden);
  allgemein nichts Persönliches.
- **Haltezeit einstellbar**, mit Standardwert.
- **Protokolliert werden nur Fehler und eine Zusammenfassung jedes Abgleichs.** Kein Start-, Klick-
  oder sonstiger Ablauf.

## Ziele, Nicht-Ziele, Anti-Ziele

Ziele
- Die Ursache eines Fehlers lässt sich später aus dem Protokoll ablesen (Art, Meldung bereinigt, Umgebung).
- Alles, was die Web-App heute über `logFailure` meldet, landet ohne Änderung an den Aufrufern im Protokoll.
- Auch der Service Worker schreibt hinein (dort entstehen die Update- und Push-Fehler).

Nicht-Ziele
- Kein Hochladen, keine Telemetrie, keine automatische Weitergabe. Nur Kopieren/Teilen auf Knopfdruck.
- Keine Protokollstufen zum Einstellen, kein Mitschneiden des normalen Ablaufs.
- Kein Eingriff in Protokoll, Desktop oder Relay. Reine Änderung der Web-App.
- Keine Anzeige über den Reiter hinaus (kein Banner, keine Zahl am Zahnrad).

Anti-Ziele (wäre ein Misserfolg, auch wenn es technisch läuft)
- Eine einzige Adresse, ein Name oder eine Uhrzeit eines Eintrags im Protokoll oder im Export.
- Ein Protokoll, das den Speicher füllt oder den Start der App verlangsamt.
- Ein Fehler im Protokollieren selbst, der den Pfad stört, den er beschreibt (wie bei `logFailure`).

## Aufbau (Vorschlag, Aufteilung ist Sache des Bauenden)

Neue DOM-freie Module unter `pwa/`, nach dem Muster von `diagnose.js` (Umgebung als Parameter, in Node
getestet), jeweils in der Modulliste von `pwa/CLAUDE.md` nachzutragen:

- **Bereinigung** (`log-scrub.js`): wandelt freien Text in bereinigten Text. Ersetzt Web-Adressen
  (`http(s)://…`, auch ohne Schema `host:port`), IPv4/IPv6, E-Mail-Adressen, Hostnamen, lange Zeichenketten
  (Base64/Hex, Schlüssel, Tokens ab etwa 20 Zeichen), Datums- und Uhrzeitangaben (`2026-11-06`, `14:30`,
  `06.11.2026`) und Pfade durch feste Platzhalter (`<url>`, `<ip>`, `<mail>`, `<schlüssel>`, `<datum>`,
  `<zeit>`, `<pfad>`). Länge begrenzt (auf 240 Zeichen, wie `errorDetail`).
- **Ereignisse** (`debug-log.js`): feste Arten mit festen Feldern, als **Positivliste**:
  - `error`: `context` (fester Text aus dem Code, Ausnahme: ein dynamischer Wert wird bereinigt),
    `name` (Fehlername), `detail` (bereinigte Meldung).
  - `sync`: `result` (`ok` oder die Art des Fehlers), `ms` (Dauer), `sent`/`received` (Zahl der Tage,
    nur Zahlen), `conflicts` (Zahl), `window` (Zahl der Tage, nur Zahl).
  Unbekannte Felder werden verworfen, nicht bereinigt: freier Text kommt nur über die Stelle, an der
  die Bereinigung läuft.
- **Speicher:** eigene IndexedDB-Datenbank `zeiterfassung-log` (Muster: `zeiterfassung-push` in
  `push-blob.js`), damit die Datenbank der Einträge (`zeiterfassung`, Version 2) unverändert bleibt und
  Seite **und** Service Worker beide schreiben können. Je Eintrag: Zeitstempel (UTC, ISO), Art, Felder.
- **Anbindung:** `logFailure` in `diagnose.js` bekommt eine austauschbare Senke. Die Seite und der Service
  Worker setzen sie beim Start; damit wird jeder bestehende Aufruf (App, Service Worker, Sync, Relay-Transport)
  ohne weitere Änderung protokolliert. Der Abgleich ruft `sync` an der Stelle, an der er sein Ergebnis kennt.
- **Technischer Zustand** (`debug-info.js`): aus Parametern (wie `browser-policy.js`), nie aus
  `navigator` direkt. Felder: Browser und Hauptversion, Betriebssystem und Hauptversion, installiert
  (`display-mode: standalone`), online, Sprache, Bildschirmgröße, Build-Kennung, Zustand des Service
  Workers (aktiv/wartend), Benachrichtigungen (Erlaubnis, Abo ja/nein), Speicher (dauerhaft ja/nein, belegt),
  Kopplungsweg (LAN/Relay) und Protokollversion. **Nicht:** Gerätemodell und Gerätename (identifizieren das
  Gerät), Adressen, Geräte-ID.
- **Reiter „Debug“:** vierter Reiter in `settingsDialog`; oben der technische Zustand, darunter die
  Einträge (neueste zuerst), unten „Kopieren“, „Als Datei teilen“, „Löschen“ und die Haltezeit.

## Verhalten

- **Haltezeit:** Einstellung `log_retention_days` (gerätelokale Meta, wie `auto_update`), Auswahl
  1 / 7 / 30 Tage, **Standard 7**. Ältere Einträge werden beim Start und beim Schreiben entfernt.
  Zusätzlich eine harte Obergrenze von 500 Einträgen (älteste fallen zuerst), damit ein Fehler in einer
  Schleife den Speicher nicht füllt. Das sind meine Werte, nicht die des Nutzers.
- **Export:** reiner Text, zuerst der technische Zustand, dann die Einträge, eine Zeile je Eintrag
  (`2026-11-06T14:02Z WARN Update-Suche: ServiceWorker cannot be started`). Der Export läuft **erneut**
  durch die Bereinigung (Gürtel und Hosenträger). „Teilen“ nutzt die Web-Share-API mit einer Datei, wo
  vorhanden, sonst ein Download. „Kopieren“ geht über die Zwischenablage-API mit Fallback.
- **Löschen** leert das Protokoll sofort, ohne Rückfrage-Dialog mit Text, aber mit der Bestätigung, die die
  Web-App für Löschen schon kennt.
- **Ausfallsicherheit:** Schreiben ins Protokoll wirft nie. Ohne IndexedDB (privates Fenster) bleibt ein
  Protokoll im Speicher der Seite, der Reiter sagt das.
- **Neue Fehlerstellen:** wer in `app.js`, `sw.js`, `sync.js` oder `relay-transport.js` einen Catch-all
  baut, ruft weiter `logFailure`; ein Quelltext-Test kann das wie bei den übrigen Konventionen festhalten
  (Sache des Bauenden).

## Datenschutz

- Das Protokoll liegt nur auf dem Gerät und verlässt es nur, wenn der Nutzer kopiert oder teilt.
- Die Datenschutzhinweise (`docs/datenschutz.md`, in der App und als `pwa/datenschutz.html`) nennen es im
  Abschnitt zur Web-App: was es enthält, was nicht, Haltezeit, Löschen. `tests/test_privacy_doc.py` bleibt
  grün; die Aussage „schreibt es in kein Log und keinen Fehlertext“ zu den Geheimnissen bleibt wahr und
  wird nicht aufgeweicht.
- Prüfung der Bereinigung als Test mit gezielt bösartigen Eingaben (IPs, URLs, E-Mails, Tokens, Daten,
  Uhrzeiten, Namen). Der Test prüft das Ergebnis des Exports vollständig, nicht nur einzelne Muster.

## Kompatibilität

Keine Änderung am Protokoll, an der Datenbank der Einträge oder am Relay. Eine ältere Web-App kennt den
Reiter nicht; ein Desktop-Release ist nicht nötig. Die Datenbank `zeiterfassung-log` ist neu und wird bei
Bedarf angelegt.

## Dem Bauenden überlassen

Aufteilung in Module und Dateinamen, die genaue Gestalt der Bereinigungsmuster (Hauptsache die Tests oben
sind grün), Text und Optik des Reiters (Theme der Web-App), die Wahl der Zwischenablage-Technik und des
Download-Fallbacks, Namen der Meta-Schlüssel.

## Festlegungen aus der Prüfung des Entwurfs

Aus dem Code (Stand dieser Woche):

- **Senke von `logFailure`:** `logFailure(context, error)` bekommt immer einen **festen Text** als `context`
  (alle zehn Aufrufstellen in `app.js`, `sw.js`, `sync.js`; `relay-transport.js` reicht seinen Kontext
  durch) und einen `Error` oder Text als `error` (einmal `error.cause ?? error`). Die Senke bekommt
  dieselben zwei Argumente und leitet `name` und `detail` daraus ab (`errorDetail`). Kein Aufrufer ändert sich.
  Ein Quelltext-Test hält fest, dass `context` ein Textliteral bleibt; damit kann kein Name oder Wert aus
  Nutzerdaten über den Kontext ins Protokoll gelangen.
- **Namen:** Sie lassen sich nicht per Muster entfernen. Der Schutz ist deshalb die Bauform: `context` ist
  fest, Ereignisse haben eine Positivliste von Feldern, `detail` stammt nur aus Browser- und Laufzeitfehlern
  (`errorDetail` von Fehlern der Browser-Schnittstellen). Meldungen aus eigenem Code, die Eingaben
  enthalten (etwa Kategorienamen in Prüftexten), gehen nie an `logFailure` und werden es nie.
- **Abgleich:** `sync.js` liefert heute `{sent, conflicts, excluded}`; `received` und `window` kommen aus der
  Antwort und werden dort ergänzt (nur Zahlen). `result` ist `ok` oder `SyncError.kind` (die Arten aus
  `sync-errors.js` samt `timeout` und `offline`), bei einem fremden Fehler dessen `name`.
- **Löschen** nutzt `confirmDialog` aus `views.js`, wie die übrigen Rückfragen.
- **Reiter:** `SETTINGS_TABS` hat heute genau drei Einträge (Verbindung, Kategorien, Updates); „Debug“
  kommt als vierter dazu.

Meine Entscheidungen (bitte beim Lesen prüfen):

- Haltezeit 1/7/30 Tage, **Standard 7**, harte Obergrenze 500 Einträge. Ein Rennen zwischen Seite und Service
  Worker darf die Zahl kurz überschreiten; das nächste Schreiben räumt auf.
- **Die Haltezeit liegt in der Log-Datenbank**, nicht in der Meta der Einträge, damit der Service Worker sie
  beim Aufräumen kennt. Eine Änderung im Reiter gilt sofort und räumt sofort auf.
- **Service Worker:** öffnet die Log-Datenbank erst beim ersten Schreiben (kein Kosten beim Kaltstart) und
  schreibt nur Fehler. Abgleich-Zusammenfassungen kommen nur aus der Seite.
- **Bereinigung:** ersetzt Zeitangaben nur in den Formen `HH:MM`, `TT.MM.JJJJ` und `JJJJ-MM-TT`. Portnummern,
  Statuscodes und Versionen bleiben stehen. Bleibt dadurch ein Teil technisch unlesbar, ist das hinnehmbar.
- **Teilen:** `navigator.canShare({files})`, sonst Download; fester Dateiname `zeiterfassung-debug.txt`
  (ohne Datum oder Gerät).
- **Stufen im Export:** `WARN` für Fehler, `INFO` für Abgleiche; fest je Art, nicht einstellbar.
- **Werte, die nicht ermittelt werden können** (Speicherbelegung, Abo-Zustand ohne Seite), zeigt der Reiter als
  „unbekannt“.
- Gerätemodell und -name bleiben aus dem technischen Zustand heraus.
- Der Zeitstempel einer Zeile bleibt, denn er ist kein Eintrag der Arbeitszeit.
- Protokolliert wird über die vorhandene Senke von `logFailure`, nicht über neue Aufrufe an jeder Stelle.
