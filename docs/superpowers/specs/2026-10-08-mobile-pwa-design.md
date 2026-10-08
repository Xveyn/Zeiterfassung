# Mobile Erfassung per PWA — Design (Stufe 1: Android, nachträgliches Erfassen, nur LAN)

Ergebnis des Brainstormings zu Issue #221 (Spike-Ergebnis dort als Kommentar). Setzt die lokale HTTP-API (#92, Spec `2026-10-06-lokale-api-design.md`) voraus, nutzt aber einen **eigenen Server** (s. „Server"). Entscheidungen, die bewusst später fallen, stehen in „Nicht in Stufe 1".

## Ziel und Abgrenzung

Zeiten unterwegs auf dem Handy nachtragen — auch ohne Verbindung — und im selben WLAN mit dem Desktop-Client abgleichen. Das Handy ist ein weiteres **Gerät** im Sinne des Sync-Modells; der Desktop ist der Merger. Konfliktlogik bleibt an einer Stelle (Python, `sync.merge`), **es gibt keinen Merge in JavaScript.**

Erfolg: ein am Handy eingetragener Tag steht nach dem nächsten Abgleich im Kalender am Desktop, mit demselben Konfliktverhalten wie beim Drive-Sync.

**In Stufe 1:** Android/Chrome (gehostete PWA), Ist-Zeiten erfassen und ändern (Slots `{start, end, pause, kategorie}`), Tage leeren, Wochenliste mit Minutensummen, Kategorien vom Desktop, Pairing per QR oder Eingabe, Offline-Betrieb, Konflikte **anzeigen**.

**Nicht in Stufe 1:** Stempeluhr (Kommen/Gehen; das Datenmodell kennt keine offenen Slots), Konfliktauflösung am Handy, Reservierungen, Urlaub, Einstellungen, Sync über das Internet (Drive), iOS, Verschlüsselung der Nutzdaten (#249), konfigurierbares Lesefenster (#250), mehrere Adressen im QR.

## Entscheidungen (mit dem Nutzer abgestimmt)

| Thema | Entscheidung |
|---|---|
| Erfassungsart | nachträglich; Stempeluhr „folgt ggf. später" |
| Reichweite | nur LAN; unterwegs offline, Abgleich im Heim-/Büro-WLAN |
| Hosting | GitHub Pages dieses Repos, Ordner `pwa/`, `https://xveyn.github.io/Zeiterfassung/` |
| Transport | Klartext-HTTP im LAN, bewusst akzeptiert (Spike: Chrome erlaubt `https`-Seite → `http://<LAN-IP>`, ein selbstsigniertes Zertifikat nicht). Ausbau: #249 |
| Konflikte | am Handy nur anzeigen, am Desktop im vorhandenen `ConflictsDialog` lösen |
| Lesefenster | 90 Tage, **geschrieben** werden darf jeder Tag. Ausbau: #250 |
| Wiederfinden | gespeicherte `IP:Port`, bei Fehlschlag QR neu scannen |
| QR | `segno` (reines Python, BSD, `py3-none-any`), auf einem Tk-`Canvas` gezeichnet; Text von Adresse und Code immer zusätzlich sichtbar |
| IP-Wahl | Vorschlag aus der aktiven Route, Auswahl bei mehreren Kandidaten |
| Sync-Protokoll | ein `POST /v1/sync` mit Merge im Desktop |
| Server | zweite, getrennte Instanz mit eigener Policy/Scope |
| PWA-Technik | ES-Module, IndexedDB, Service Worker, **kein Build-Schritt**; Tests mit `node --test` |

## Bausteine

Desktop (Tk-frei und einzeln testbar, außer dem Dialog):

- **`mobile_pairing.py`** (rein): Code erzeugen/prüfen, Gültigkeit, Fehlversuch-Sperre, Token ausgeben und erneuern (Sliding Expiration mit Karenzfenster), Widerruf.
- **`mobile_store.py`:** gerätelokale Datei `mobile_devices.json` (nicht im Drive-Sync, nicht im Share-Doc; ohne ACL-Härtung, da nur Token-Hashes darin stehen (siehe Plan Teil 1); Mechanik über `json_store`; eigener Lock wie `smtp_store`). Pro Gerät: `id`, `name`, `token_hash`, `previous_token_hash` mit `previous_valid_until`, `expires_at`, `last_seen`, `last_pull_at`.
- **`mobile_sync.py`:** Handy-Doc prüfen, durch `sync.merge` schicken, über die journalisierte Pipeline anwenden, Antwort bauen.
- **`mobile_routes.py`, `MobileService`:** Routentabelle und Lebenszyklus der zweiten Server-Instanz (Muster `api_routes`/`api_service`).
- **`netinfo.py`:** LAN-Adress-Kandidaten, plattformneutral, ohne Zusatzbibliothek (Adresse der aktiven Route per UDP-Socket ohne Senden, dazu private Adressen der Schnittstellen).
- **Tab „Mobil"** im Einstellungsdialog (`tab_mobile.py`, Regeln Tk-frei in `tab_rules.py`) und der Koppeln-Dialog mit QR-Canvas (`segno`, Modulgröße über `theme.px()`, weiße Fläche mit 4 Modulen Ruhezone unabhängig vom Dark-Theme).

PWA (`pwa/`): `index.html`, `manifest.webmanifest`, `sw.js`, Module `db.js` (IndexedDB), `sync.js` (Client), `pairing.js`, `minutes.js` (Summen, Validierung), `app.js` und Oberfläche. Tests in `pwa/test/`.

Neue gerätelokale Settings (nicht in `SYNCED_SETTING_KEYS`): `mobile_enabled` (Standard `False`), `mobile_port` (Standard `17654`), `mobile_address` (leer = Vorschlag).

## Server

Eine **zweite `ApiServer`-Instanz** mit eigener `Policy` (`allowed_hosts` = genau `<ip>:<port>`, `allowed_origins` = `https://xveyn.github.io`; `bind_host` = die gewählte LAN-Adresse, **nie `0.0.0.0`**), eigenem Prüfer (kennt nur den Scope `mobile-sync`) und einer Routentabelle, die nur die vier Routen unten enthält. Die lokale API (Loopback, Token `local`) bleibt unverändert und von außen unerreichbar; das lokale Token wird auf dem LAN-Server nie akzeptiert und umgekehrt.

Die Auth-Tore bleiben, in dieser Reihenfolge, wie in der lokalen API; `Sec-Fetch-Site` zählt im LAN nicht als Schutz (Chrome sendet es über `http://<LAN-IP>` nicht, Spike), Host, Origin und Token tragen. **CORS** nur auf diesen vier Routen und nur für die erlaubte Origin: `Access-Control-Allow-Origin: <Origin>`, `Vary: Origin`, erlaubte Header `Authorization, Content-Type`, `Max-Age` 600, nie `Allow-Credentials`. Der Preflight trägt keine Daten; die Auth läuft immer auf dem eigentlichen Request. Body-Limit, Socket-Timeouts und die Obergrenze gleichzeitiger Verbindungen wie `api_server`.

## Protokoll (`/v1`, zusätzlich `protocol: 1` im Body)

Fehler wie in der lokalen API: `{"error": {"code": "...", "message": "..."}}`.

### `POST /v1/pair` (ohne Token, nur solange ein Code aktiv ist)

Request `{"code": "K7M2-9QXA", "device_name": "Pixel von Sven", "device_id": "<uuid>"}`. Antwort `200`: `{"token", "expires_at", "window_days": 90, "desktop_name", "protocol": 1}`. Falscher, abgelaufener oder verbrauchter Code und „kein Code aktiv" geben **dieselbe** Antwort `403 invalid_code`; nach 5 Fehlversuchen ist der aktive Code ungültig (`429 pairing_locked`). Der Vergleich läuft konstantzeitig. Das Handy erzeugt die `device_id` einmalig selbst und behält sie dauerhaft (auch über erneutes Koppeln).

### `GET /v1/ping`

Mit Token. Antwort `{"protocol": 1, "server_time": "<UTC, Sekunden>", "window_days": 90}`. Dient der Erreichbarkeits- und Uhrprüfung (die PWA warnt ab 2 Minuten Abweichung).

### `GET /v1/categories`

Mit Token. `{"categories": ["Projekt", ...]}` (die in den Einstellungen konfigurierten Namen).

### `POST /v1/sync`

Request:

```json
{"protocol": 1, "client_time": "2026-10-08T12:00:00Z", "last_pull_at": "2026-10-07T09:00:00Z",
 "entries": {"2026-10-07": {"slots": [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}],
                            "modified_at": "2026-10-07T18:30:00Z", "device_id": "<uuid>", "deleted": false}}}
```

`entries` enthält nur die **geänderten** Tage (Tombstones mit `deleted: true` und `slots: []`). Ablauf im Desktop:

1. **Prüfen:** Datum `YYYY-MM-DD` (ASCII-Ziffern) und Jahr 2000–2100; höchstens 400 Tage je Anfrage; Slots mit denselben Regeln wie `PUT /v1/entries` (`validate_slots`, `HH:MM`, Pause ganze Minuten ≥ 0, höchstens 50 Slots, Kategorie höchstens 100 Zeichen ohne Steuer- und Surrogat-Zeichen); `modified_at` exakt im Format `YYYY-MM-DDTHH:MM:SSZ` und höchstens 15 Minuten in der Zukunft (sonst gewänne ein Zukunftsstempel jeden LWW-Vergleich); ein Tag ohne Slots muss `deleted: true` sein und umgekehrt; die Geräte-ID wird aus dem Token gesetzt, **nicht** aus dem Body übernommen. Fehler → `422 invalid_entry` mit Datum und Grund; es wird nichts angewendet.
2. **Uhr** (geprüft **vor** den Einträgen, damit ein vorgehendes Handy `clock_skew` statt `invalid_entry` bekommt): weicht `client_time` mehr als **15 Minuten** vom Desktop ab → `409 clock_skew`, nichts wird angewendet (LWW vertraut `modified_at`; eine falsche Uhr würde echte Einträge überschreiben).
3. **Guard:** den Sync-Guard (derselbe `sync_guard` wie Drive-Sync, Kompaktierung, Quit-Push) nicht-blockierend nehmen; ist er belegt → `503 busy`, das Handy versucht es später. Das `last_pull_at` kommt aus dem **Gerätespeicher des Desktops**, nicht aus dem Body (der Wert im Body dient nur der Diagnose).
4. **Mergen:** `sync.merge(local=<Handy-Doc>, remote=<Desktop-Stand>, last_pull_at)`. Das Handy ist `local`: so wirkt die Self-Heal-Regel (`excluded`) genau richtig — ein Handy, das länger offline war als die letzte Kompaktierung (`last_pull_at < gc_watermark`), darf einen am Desktop gelöschten, seitdem aufgeräumten Eintrag nicht wiederbeleben. Angewendet wird über dieselbe journalisierte Pipeline wie beim Drive-Sync (`sync_journal`, `apply_merged_doc`); Konflikte landen im `ConflictsStore`; danach `on_change` (UI-Refresh). Das Handy erscheint über `devices.py` mit lesbarem Namen in der Registry. Beim **ersten Abgleich** (`last_pull_at` leer) gilt jeder Tag, den beide Seiten kennen und der sich unterscheidet, als geändert auf beiden Seiten und wird ein Konflikt — das ist gewollt, denn ohne gemeinsamen Stand lässt sich nicht entscheiden.
5. **Antwort:** `200` mit
   `{"protocol": 1, "server_time", "last_pull_at": "<server_time>", "excluded": false, "window_days": 90, "entries": {...}, "conflicts": [...], "categories": [...], "token": "<erneuert>", "expires_at"}`.
   `entries` sind die Tage des Fensters `[heute − 90, heute]` samt Tombstones (heute ist das lokale Datum des Desktops) **und** alle vom Handy geschickten Tage (das Merge-Ergebnis, auch außerhalb des Fensters). `conflicts`: offene Einträge-Konflikte im Fenster als `{"id", "date", "versions": [{"device", "name", "modified_at", "slots"}]}`. `excluded: true` heißt: das Handy war länger offline als die letzte Kompaktierung.

**Wiederholbar:** derselbe Request liefert dasselbe Ergebnis (Merge ist idempotent). Das erneuerte Token ersetzt das alte; das alte gilt noch 10 Minuten (verlorene Antwort).

### Statuscodes

`400 invalid_json|invalid_protocol`, `401 unauthorized|token_expired|token_revoked`, `403 bad_host|bad_origin|invalid_code`, `404`, `405` (mit `Allow`), `409 clock_skew`, `413`, `415`, `422 invalid_entry`, `429 pairing_locked`, `503 busy|shutting_down`. Ein Programmfehler ist eine `500` ohne Details, mit Traceback im Log.

## Pairing und Token

1. Im Tab „Gerät koppeln": Der Desktop erzeugt einen Code aus **31 Zeichen** (Ziffern 2–9 und Buchstaben ohne I, L, O), 8 Stellen als `XXXX-XXXX`, rund 40 Bit, **5 Minuten** gültig, einmal einlösbar. Er zeigt Code, Adresse und einen QR-Code mit `https://xveyn.github.io/Zeiterfassung/#pair=<ip>:<port>:<code>`. Das Fragment geht nie an einen Server; es enthält nur Adresse und Einmalcode, kein Token.
2. Das Handy scannt (Kamera-App, oder in der PWA „QR scannen" per `BarcodeDetector`; Rückfall: Eingabe von Adresse und Code), speichert die Adresse und ruft `POST /v1/pair`.
3. Der Code wird ungültig durch Ablauf, erfolgreiches Koppeln, 5 Fehlversuche oder Schließen des Dialogs. Ohne aktiven Code ist `/v1/pair` wirkungslos.
4. Das Gerätetoken (`secrets.token_urlsafe(32)`) liegt im Desktop nur als SHA-256-Hash, im Handy in IndexedDB. **30 Tage ab der letzten Nutzung**, jeder erfolgreiche Sync erneuert es. Abgelaufen oder widerrufen → `401` mit eigenem Code; die PWA zeigt „Neu koppeln" und **behält alle lokalen, nicht übertragenen Einträge** (die `device_id` bleibt, die LWW-Identität ändert sich nicht).
5. Der Tab listet gekoppelte Geräte (Name, zuletzt gesehen, läuft ab am) mit „Widerrufen" und „Alle widerrufen".
6. Codes, Token und Hashes stehen nie im Log.

## Einschalten und Binden

Standardmäßig **aus.** Beim ersten Einschalten erklärt ein Hinweis, dass die Verbindung unverschlüsselt ist und nur in vertrauenswürdigen Netzen genutzt werden soll; dazu der Hinweis, dass die App laufen muss (Autostart empfehlen, wie bei der lokalen API). Gebunden wird nur auf die gewählte LAN-Adresse. Verschwindet sie (DHCP, anderes WLAN), zeigt der Tab „Adresse nicht mehr vorhanden" und bietet die Auswahl an; ein belegter Port wird wie bei `ApiService` als Statusgrund gemeldet. Unter Windows löst das Binden auf eine Nicht-Loopback-Adresse beim ersten Mal den Firewall-Dialog aus; der Tab sagt das vorher in einem Satz (Prüfung in #248).

## PWA

**Bildschirme:** Koppeln; Woche (Startseite: Mo–So, Wochenpfeile, heute markiert, Tagessummen und Wochensumme); Tag bearbeiten (mehrere Slots, Kategorie-Auswahl aus den Desktop-Kategorien mit freier Eingabe, „+ Slot", „Speichern", „Tag leeren" mit Rückfrage); Konfliktansicht (beide Versionen nur lesend, „Am Desktop lösen"). **Summen nur über ganze Minuten** je Slot (nie Dezimalstunden), Anzeige deutsch (`TT.MM.JJJJ`, `h:mm`), Speicherung ISO. Validierung am Handy mit denselben Regeln wie am Desktop; maßgeblich bleibt der Desktop, bei `422` bleibt der Tag lokal erhalten, rot markiert und mit der Meldung.

**Statuszeile:** online/offline, „n Änderungen nicht übertragen", „zuletzt abgeglichen um …", „Jetzt abgleichen". Hinweise mit Ausweg: Desktop nicht erreichbar (mit „QR neu scannen"), Uhr weicht ab, Handy war länger offline („am Desktop gelöschte Einträge bleiben gelöscht"), Token abgelaufen, Speicher nicht dauerhaft.

**Lokale Daten (IndexedDB):** Store `entries` (`date` → `{entry, dirty_version}`), `meta` (Adresse, Token, `device_id`, `last_pull_at`, Kategorien, `window_days`). Jede Änderung setzt `modified_at` (UTC, Sekunden) und erhöht `dirty_version`. Nach einer Antwort gilt je Tag: war `dirty_version` seit dem Senden unverändert → durch den Stand des Desktops ersetzen und „nicht übertragen" löschen; wurde der Tag inzwischen erneut geändert → lokal behalten (der nächste Abgleich merged erneut). Tage **im Fenster**, die in der Antwort fehlen und nicht „nicht übertragen" sind, werden lokal entfernt; aus „nicht im Fenster" wird **nie** ein Löschen abgeleitet. Außerhalb des Fensters bleiben nur noch nicht übertragene Tage.

**Abgleichzeitpunkte:** beim Start, beim Zurückkehren in die App (`visibilitychange`), beim `online`-Ereignis, 2 Sekunden nach dem Speichern, auf Knopfdruck. Kein Hintergrund-Sync.

**Offline-Hülle:** der Service Worker legt die App-Dateien in einen versionierten Cache und liefert sie offline aus; eine neue Version zeigt „Neue Version, neu laden". **API-Antworten werden nie gecacht.** Die PWA fordert dauerhaften Speicher an (`navigator.storage.persist()`) und zeigt an, wenn er nicht gewährt wird. Fetch an den Desktop mit `targetAddressSpace: "local"` (nicht nötig, aber ausdrücklich).

## Sicherheit und Grenzen

- **Klartext im LAN:** Wer im selben WLAN mitlauscht, kann das Gerätetoken mitlesen und damit Ist-Zeiten lesen und über den Sync-Pfad schreiben — nicht Einstellungen, Secrets, Webhooks oder die Sync-Konfiguration. Maßnahmen: Funktion aus, Bind nur auf die gewählte Adresse, Scope `mobile-sync`, Token pro Gerät nur als Hash und widerrufbar, kurzlebiger Einmalcode mit Sperre, Ablauf nach 30 Tagen. Ausbau: #249.
- **Origin ohne Pfad:** erlaubt ist `https://xveyn.github.io`; damit könnte jede andere GitHub-Pages-Seite unter diesem Nutzernamen die API ansprechen, braucht aber das Gerätetoken.
- **Lokaler Speicher kann verloren gehen:** löscht der Nutzer die Website-Daten oder räumt Android bei Platzmangel auf, sind nicht übertragene Einträge weg. Gegenmaßnahmen: dauerhafter Speicher, sichtbarer Zähler.
- **Uhr:** LWW vertraut der Handy-Uhr; 15-Minuten-Grenze (s. oben).
- **IP-Wechsel:** keine Namensauflösung; bei Fehlschlag QR neu scannen (feste Adresse im Router hilft).
- **Nur solange die Desktop-App läuft.**
- **Kein TLS:** Fallback A aus #221 (Desktop liefert die PWA selbst per HTTPS aus) bleibt der Weg für iOS und für Verschlüsselung (#249).

## Tests

Python (TDD, Mutationsprüfung, finaler Review pro PR): Pairing und Store rein; `mobile_sync` gegen `sync.merge` (Self-Heal/`excluded`, Konflikt, Tombstone, Wiederholung, Uhrabweichung, Validierung, `busy`); Routen mit echten Stores; Server über echte Sockets (Preflight, Origin, Host, Token-Zustände); `netinfo` und die Regeln des Tabs Tk-frei. Der Tab selbst wird von Hand geprüft. **JavaScript** (`node --test`, neuer CI-Job): Warteschlange und `dirty_version`, Sync-Client mit gefälschtem `fetch`, Pairing-Link, Minutensummen, Validierung. **Vertrag gegen Drift:** gemeinsame JSON-Beispiele in `pwa/test/fixtures/` für Request und Response, die Python- und JS-Tests beide lesen.

## Auslieferung und Zuschnitt

GitHub Pages deployt `pwa/` per Workflow (`actions/deploy-pages`) bei Änderungen am Ordner auf `master`. Das braucht eine **Repo-Einstellung** (Settings → Pages → Source: „GitHub Actions"), die nicht im Code steht; sie kommt wie bei `changelog-archive` in die `CLAUDE.md`. Die Origin steht als Konstante im Code (und in der Doku), zieht das Repo um, muss sie nachgezogen werden.

PR-Zuschnitt (jeweils vom aktuellen `master`, nach dem Merge des API-Stacks):

1. Spec (Doku).
2. `mobile_pairing` und `mobile_store`.
3. `mobile_sync`.
4. Server, Routen, `MobileService`, CORS, `netinfo`, Settings-Keys.
5. Tab „Mobil" mit QR (`segno` gepinnt in `requirements.txt`, `requirements-test.txt` und der Tabelle in `CONTRIBUTING.md`; Python-3.12-Gegencheck: reines Python) und Verdrahtung in `ui.py`.
6. PWA-Kern (Module, Tests, Vertragsbeispiele, CI-Job).
7. PWA-Oberfläche, Service Worker, Manifest, Pages-Workflow.
8. Doku: README, `known-limitations`, Erweiterung der Prüfliste #248.

Release: ein Minor. Davor Pre-Release über alle drei Plattformen und ein Test mit einem echten Android-Gerät (Chrome, installierte PWA, Local-Network-Access-Berechtigung, abgelehnte Berechtigung, Offline-Start).

## Nicht in Stufe 1 / offen

- **iOS:** Safari blockiert `https` → `http://<LAN-IP>`. Weg: der Desktop liefert die PWA selbst per HTTP aus (Fallback B, ohne Service Worker und Offline-Start) oder per HTTPS (Fallback A). Eigene Spec.
- **Stempeluhr** (laufender Eintrag auf dem Handy), **Konfliktauflösung am Handy**, **Reservierungen/Urlaub** auf dem Handy.
- **Verschlüsselung der Nutzdaten:** #249. **Lesefenster einstellbar oder volle Historie:** #250. **Mehrere Adressen im QR**, **mDNS-Name**.
- **Offene Tests auf Android:** Verhalten bei abgelehnter Local-Network-Berechtigung (Fehlermeldung für den Nutzer), Offline-Start der installierten PWA.

## Referenzen

#221 (Idee und Spike), #92 und `2026-10-06-lokale-api-design.md` (lokale API), #233/#246/#248 (Review-Reste und Prüfliste), #249, #250.
