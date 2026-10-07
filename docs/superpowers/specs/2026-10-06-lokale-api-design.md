# Lokale HTTP-API (Stufe 1) — Design

Issue: #92. Bildet die Basis für #221 (mobile Erfassung per PWA); dessen
Spike-Ergebnis (Kommentar vom 2026-10-06) ist hier eingearbeitet.

## Ziel und Abgrenzung

Die App von außen ansprechbar machen, **lesend und schreibend**, zunächst nur
vom selben Rechner (`127.0.0.1`). Use Cases: Zeiten per Skript eintragen,
erfasste Daten in andere Tools ziehen.

Die API lebt **im App-Prozess**. `Storage` hält alles im Speicher und schreibt
bei jedem Save die ganze Datei; ein zweiter Schreiber würde überschrieben
(#92, Einschränkung 2). Ein Sidecar oder ein Zugriff auf die JSON-Dateien ist
deshalb keine Option.

**Nicht Teil von Stufe 1:** Pairing, LAN-Bind, CORS, `/v1/sync` (alles #221),
Berichtversand (PDF/Mail/Webhook), Schreibzugriff auf Settings, Secrets,
Webhooks oder Sync-Konfiguration, ein laufender Timer (das Datenmodell kennt
keine offenen Slots).

## Nahtstellen für #221

Zwei Dinge werden jetzt schon als Parameter gebaut, weil sie nachträglich der
riskanteste Umbau wären:

1. **Auth-Policy als Wert:** `Policy(allowed_hosts, allowed_origins,
   bind_host)`. Stufe 1 setzt `allowed_origins = ∅`; #221 füllt sie (gehostete
   PWA-Origin und eigene Desktop-Adresse) und ergänzt die CORS-Konfiguration,
   sobald es CORS gibt.
2. **Token mit Scope:** der Token-Prüfer liefert ein `Principal` mit
   `scopes`; jede Route deklariert den Scope, den sie braucht. Stufe 1 kennt
   nur `local`; #221 ergänzt `mobile-sync` mit eingeschränkten Routen.

## Module (alle Tk-frei, ohne Socket testbar)

| Modul | Aufgabe |
|---|---|
| `src/api_auth.py` | Token erzeugen/laden (Datei `api-token` im Datenordner, Muster `single_instance._write_secret_atomic`: Temp → `chmod 0600` → `harden_windows_acl` → `os.replace` mit `PermissionError`-Retry). `authorize(request, policy) -> AuthResult` als **eine** Funktion. Vergleich mit `hmac.compare_digest`. |
| `src/api_routes.py` | `handle(ApiRequest, ctx) -> ApiResponse`: Routing, Validierung, Serialisierung. `ctx` hält Stores, `data_lock` und den `on_change`-Callback. |
| `src/api_server.py` | Dünner `ThreadingHTTPServer` im eigenen Daemon-Thread (Muster: Accept-Loop in `single_instance`). Body-Limit, Socket-Timeouts, Start/Stopp. Kein Fachwissen. |

Der Token liegt **nicht** in `settings.json` (nicht ACL-gehärtet, wandert
teilweise nach Drive), sondern in eigener Datei wie `instance-secret`.
Dazu gehört ein Eintrag in `removal.py` und `installer.iss` (Aufräumen
beim Entfernen/Deinstallieren), die beiden Test-Assertions halten die Listen
zusammen.

### Verdrahtung

- `App._apply_api_setting()` startet/stoppt den Server je nach Settings
  (Muster `_apply_tray_setting`). Der Server wird beim Beenden, beim
  Skalierungs-Neustart und bei „Zeiterfassung entfernen" gestoppt.
- UI-Refresh nach einem Schreibzugriff: `on_change` ruft über
  `App._marshal_to_ui` das `_refresh`. Der Server-Thread berührt nie ein Widget.
- Neue Settings, beide **gerätelokal** (nicht in `SYNCED_SETTING_KEYS`):
  `api_enabled` (Default `False`), `api_port` (Default `17653`; außerhalb des
  `single_instance`-Bereichs 20000–31999 und der Ephemeral-Ranges).
- Ein Bindfehler (Port belegt) wird im Settings-Tab angezeigt, loggt und
  beendet die App nie (wie `single_instance`: der Start scheitert nie daran).
- Neuer Settings-Tab: Schalter „Lokale API aktivieren", Port, Token maskiert
  mit Kopieren-Button, „Token neu erzeugen" mit Bestätigung (Rotation sperrt
  alle Clients aus).

## Authentifizierung

**Bedrohungsmodell:** jede Webseite im offenen Browser kann
`fetch("http://127.0.0.1:<port>/…")` absetzen. Der Token ist die Verteidigung,
die Header-Prüfungen sind die zweite Reihe.

### Token

`secrets.token_urlsafe(32)`, beim ersten Aktivieren erzeugt. Übergabe als
`Authorization: Bearer <token>`, **nie** als Query-Parameter. Der Token
erscheint in keinem Log; Fehlermeldungen nennen ihn nicht.

### Die Tore in `authorize`

| Tor | Stufe 1 | Hinweis |
|---|---|---|
| Host-Header | muss `127.0.0.1:<port>` oder `localhost:<port>` sein | DNS-Rebinding |
| Origin | vorhanden und nicht in `policy.allowed_origins` → ablehnen | Stufe 1: Allowlist leer. Ein same-origin-POST aus Safari trägt ein `Origin` mit der eigenen Adresse (Spike), die Allowlist muss das in #221 abbilden können. |
| `Sec-Fetch-Site` | vorhanden → ablehnen | Hilft nur auf Loopback. Über `http://<LAN-IP>` sendet Chrome es nicht (Spike), deshalb nie tragender Schutz. |
| Bearer | Pflicht auf **allen** Endpunkten, auch GET | geprüft am eigentlichen Request, nie nur am Preflight (Preflights werden gecacht, Spike) |

Zusätzlich: Schreibzugriffe verlangen `Content-Type: application/json`;
**niemals** ein `Access-Control-Allow-*`-Header in Stufe 1; `OPTIONS` → 405;
Antworten mit `Cache-Control: no-store` und `X-Content-Type-Options: nosniff`.

### Warum das den Browser-Angriff schließt

`Authorization` und `application/json` sind nicht CORS-safelisted. Jede
Anfrage aus einer fremden Seite braucht deshalb einen Preflight, den wir nie
positiv beantworten; der Browser bricht ab, bevor die eigentliche Anfrage
rausgeht. Bei DNS-Rebinding entfällt CORS, der Angreifer kennt aber den Token.

### Grenzen (nach `docs/known-limitations.md`)

- Ein Prozess, der **als derselbe Nutzer** läuft, kann `api-token` lesen. Auf
  einem Desktop-OS nicht änderbar; direkt daneben liegt `token.json`, das mehr
  wert ist. Die API verschiebt diese Grenze nicht.
- Kein TLS: auf Loopback bedeutungslos, im LAN (#221) relevant.
- Keine Brute-Force-Sperre in Stufe 1 (256 Bit, gegen lokale Codeausführung
  wirkungslos). Die Prüfung liegt in **einer** Funktion, damit später genau
  eine Stelle aufgeht.

## Endpunkte (`/v1`)

Slot-Format `{start, end, pause, kategorie}` aus Share v3. Fehler als
`{"error": {"code": "...", "message": "..."}}`. **Summen sind ganze Minuten**
(`hours_to_minutes`), nie Dezimalstunden (Regel „Summen nur über Minuten").

| Methode und Pfad | Zweck | Scope |
|---|---|---|
| `GET /v1/status` | Version, Gerätename, API-Version | `local` |
| `GET /v1/entries?from&to` | Ist-Zeiten im Zeitraum | `local` |
| `GET /v1/entries/{date}` | ein Tag | `local` |
| `PUT /v1/entries/{date}` | Tag **komplett ersetzen**, idempotent | `local` |
| `DELETE /v1/entries/{date}` | Tombstone | `local` |
| `GET/PUT/DELETE /v1/reservations/{date}` | Reservierungen, gleiche Form | `local` |
| `GET /v1/summary/month/{YYYY-MM}`, `/week/{YYYY-Www}` | Minutensummen, Wochenlimit, Pausenpflicht | `local` |
| `GET /v1/categories`, `GET /v1/holidays/{year}` | Kategorien, Feiertage (Bundesland aus Settings) | `local` |

Keine Pfade zu Berichtversand, Settings, Secrets, Webhooks, Sync.

## Regeln, die die API nachbilden muss

Der Store kennt sie nicht, sie sitzen heute an den UI-Eingängen. Die API ist
ein neuer Eingang:

- **Tag mit Urlaubsminuten > 0:** `PUT` → `409` (wie `vacations.conflicting_days`,
  geprüft auf `minutes > 0`; 0-Minuten-Tage der Periode bleiben beschreibbar).
- **Ungelöster Sync-Konflikt am Tag:** `PUT`/`DELETE` → `409`
  (`conflicts_store.unresolved_entry_keys`); die UI öffnet dort den
  Konfliktdialog statt des Tages-Dialogs.
- **Validierung** über `time_utils.validate_slots` (der Store validiert bewusst
  nicht). Wochenlimit und Pausenpflicht kommen als `warnings` in der Antwort,
  nicht blockierend, wie in der UI.
- **Reservierung schreiben** stößt denselben Kalender-Abgleich an wie die UI.
  Kein Sonderweg.
- **Statuscodes:** `400` ungültiges Format, `401` Token fehlt/falsch, `403`
  Host/Origin/Sec-Fetch, `404` unbekannter Pfad, `405` falsche Methode, `409`
  Regelverstoß, `413` Body zu groß, `415` falscher Content-Type, `422`
  Slot-Validierung.

## Threading

Jeder Request führt Prüfen → Konfliktcheck → Speichern unter dem geteilten
`data_lock` (`RLock`) aus, **nie über Netzwerkaufrufe**. Der Server-Thread ist
ein eigener Daemon-Thread im Modul `api_server`, kein Thread in `ui.py`/den
Dialogen; Präzedenz ist der Accept-Loop in `single_instance`. Der Abschnitt
„Threading-Modell" in `src/CLAUDE.md` wird entsprechend ergänzt.

## Tests

- Tabellentest für `authorize` (jedes Tor einzeln, Kombinationen, Timing-sichere
  Vergleiche).
- Routentests mit echtem `Storage`/`ReservationStore` im `tmp_path`:
  Schreiben, Ersetzen, Tombstone, Konflikt- und Urlaubssperre, `warnings`.
- Ein Integrationstest mit `ThreadingHTTPServer` auf Port 0 (stdlib, ohne Tk).
- Neue Module in die Whitelist von `tests/test_type_annotations.py`; sie fallen
  automatisch unter das Coverage-Gate (`FLOOR` der Tk-freien Module).
- `tests/test_catch_all_handlers.py` gilt: jeder Catch-all loggt, meldet oder
  begründet.

## Doku und Release

- `src/CLAUDE.md`: Modulbeschreibung, Threading-Absatz.
- `docs/known-limitations.md`: Token-Lesbarkeit durch Prozesse desselben Nutzers.
- Root-`CLAUDE.md`: Modulliste ergänzen.
- README-Zeile mit `*(ab --VERSION--)*`.
- Versionsstufe **Minor** (neue Funktion).
- Das Binden auf Loopback löst unter Windows keinen Firewall-Dialog aus; die
  Plattformfrage stellt sich erst mit dem LAN-Bind in #221.

## Stack innerhalb von #92

1. `api_auth` samt Tokendatei, Policy und Principal (rein, getestet).
2. Server (`api_server`), Routing (`api_routes`) mit `/status` und den lesenden
   Ist-Zeit-Routen, Lebenszyklus (`api_service`), Settings-Schlüssel,
   Verdrahtung in `App`.
3. Settings-Tab (Schalter, Port, Token anzeigen/kopieren/neu erzeugen,
   Statusgrund).
4. Schreibende Ist-Zeit-Endpunkte (`PUT`/`DELETE /v1/entries/{date}`) samt den Regeln aus
   „Regeln, die die API nachbilden muss“.
5. Auswertungen (Summen, Wochenlimit, Pausenpflicht, Kategorien, Feiertage), dann
   Reservierungen und Urlaub — Zuschnitt und offene Fragen in Issue #239.

## Offene Punkte (bewusst nicht in Stufe 1)

- LAN-Freigabe, Pairing, CORS-Allowlist, `/v1/sync`: #221.
- Sliding Expiration des Tokens: #221 (Stufe 1 rotiert nur manuell).
- Autostart-Empfehlung, damit die API praktisch verfügbar ist.
