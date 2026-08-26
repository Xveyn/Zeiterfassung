# Webhook-Versand — Design

Datum: 2026-08-26

## Ziel

Der Bericht kann heute ausschließlich per Gmail verschickt werden. Er soll
zusätzlich an **benannte HTTP-Endpunkte** (Webhooks) gepostet werden können —
mehrere davon, gerätelokal konfiguriert, mit optionaler Authentifizierung.

Der Mailversand bleibt dabei unverändert der Hauptweg. Ist kein Webhook
eingerichtet, sieht der Sende-Dialog exakt aus wie heute.

## Entschiedene Eckpunkte

Aus dem Brainstorming, als Kurzreferenz für alles Folgende:

| Frage | Entscheidung |
|---|---|
| Payload | JSON, PDF oder beides — der Nutzer entscheidet |
| Payload-Wahl wo | pro Webhook konfiguriert, im Sende-Dialog übersteuerbar |
| Auth | ohne Auth, Header-Token (Bearer/API-Key), HMAC-Signatur — **kein** Basic Auth |
| Auslösung | im bestehenden Sende-Dialog; kein Webhook konfiguriert ⇒ keine Ziel-Auswahl sichtbar |
| Sync | gerätelokal, gar kein Drive-Sync |
| Teilfehler | alle Kanäle feuern unabhängig, Ergebnis wird gesammelt angezeigt |
| Transport | https erzwungen außerhalb des lokalen Netzes, http innerhalb — **ohne** Warnung |

## Status quo

```
ui.py "Senden" → send_dialog.open_send_dialog
                   ├─ period_picker (Zeitraum + Kategorien + Vorschau)
                   ├─ workweek.filter_for_report(storage.get_all(), settings)
                   ├─ report.generate_report(...) → (html, total) | (None, …)
                   └─ runner.run(send_task.perform_send) [Worker]
                          ├─ report.generate_pdf(...) → bytes
                          ├─ mail.get_gmail_service(...)  (ggf. OAuth-Flow)
                          ├─ mail.send_email(...)
                          └─ mail.fetch_user_email → settings["sender_email"]
```

Fünf Befunde aus der Bestandsaufnahme, die das Design bestimmen:

1. **`send_task.perform_send` ist Tk-frei und wirft nie** (Audit M10) — es
   liefert ein Result-Dict, das `mail_task.classify_mail_error` in
   `filenotfound` / `offline` / `error` einteilt. Genau diese Naht ist der
   Andockpunkt für einen zweiten Transport. Eine Transport-Abstraktion gibt es
   heute nicht; `perform_send` kennt nur Gmail.
2. **`settings.json` hat keinerlei Zugriffsschutz** — kein `chmod`, kein
   `icacls`. Geschützt sind heute genau `token.json` und `instance-secret`,
   beide über `secure_file` (`src/CLAUDE.md`: *„Wer einen dritten
   Secret-Schreibpfad baut, ruft diesen Helfer mit auf."*).
3. **`SYNCED_SETTING_KEYS` wandert per Drive-Sync auf andere Geräte.** Ein
   Secret darf dort nicht landen; das Projekt hat bisher nie eines in den Sync
   gegeben.
4. **Ausgehende HTTP-Calls laufen über stdlib `urllib`** (`updater.py`,
   `mail.fetch_user_email`). `requests` ist keine direkte Dependency und ist in
   `requirements-test.txt` nicht enthalten.
5. **`share.py` besitzt bereits ein versioniertes Slot-Wire-Format** (v3), das
   sich als JSON-Payload wiederverwenden lässt — aber sein Validator lehnt
   unbekannte Felder ab.

## Architektur

Der Mailpfad wird nicht umgebaut, sondern bekommt einen Dispatcher davor:

```
send_dialog                 (Tk)   Ziel-Auswahl, Ergebnis-Anzeige
   └─ send_task.perform_send       Dispatcher: Payload einmal bauen, Kanäle feuern
        ├─ _send_mail              der heutige Gmail-Block, unverändert
        └─ webhook.perform_send    pro Webhook, Tk-frei, wirft nie
             └─ webhook.post       urllib, kein Schema-Downgrade bei Redirects

webhooks.py   (Store)   webhooks.json, gehärtet wie token.json, gerätelokal
webhook.py    (pure)    URL-Regel, Auth-Header, HMAC, Payload, POST, Fehler-Mapping
```

Bewusst **keine** generische Kanal-Abstraktion, in die auch Mail eingepasst
wird: Gmail bringt OAuth-Flow, Scope-Upgrade, Token-Refresh, `sender_email`-Cache
und den `credentials.json`-Sonderfehler mit. Das alles hinter ein
`send(payload)`-Interface zu quetschen hieße, den einzigen heute
funktionierenden Versandweg für einen hypothetischen dritten umzubauen. Kommt
irgendwann ein dritter Kanal, ist das der Moment für die Abstraktion — nicht
jetzt.

## Datenmodell: `webhooks.json`

Liegt neben `token.json` im Datenverzeichnis (`paths.get_base_path()`),
gerätelokal, nie im Sync-Doc.

```json
{
  "schema_version": 1,
  "webhooks": [
    {
      "id": "3f2a…",
      "name": "Buchhaltungs-Server",
      "url": "https://erp.example.com/hooks/zeiterfassung",
      "enabled": true,
      "payload": { "json": true, "pdf": true },
      "auth": { "mode": "header", "header": "Authorization", "value": "Bearer …" }
    }
  ]
}
```

- `id` — `uuid.uuid4().hex`, beim Anlegen vergeben, danach unveränderlich.
  Trägt die Zuordnung, wenn der Nutzer den Namen ändert.
- `name` — Pflichtfeld, nicht leer, **eindeutig** (case-insensitiv). Der Name
  ist die einzige Kennung, die im Sende-Dialog und in der Ergebnis-Anzeige
  auftaucht; zwei gleich benannte Ziele wären dort nicht unterscheidbar.
- `enabled` — abgeschaltete Webhooks erscheinen nicht in der Ziel-Auswahl,
  bleiben aber konfiguriert.
- `payload` — die Vorbelegung der Format-Wahl im Sende-Dialog. Mindestens
  eines von `json`/`pdf` muss gesetzt sein.
- `auth` — drei Formen, siehe unten.

**Fehlertoleranz beim Laden**, nach dem Muster der übrigen Stores:

- Datei nicht parsebar oder kein Objekt → Quarantäne nach
  `webhooks.json.corrupt-<stamp>` (`os.replace`, gegen `OSError` abgesichert),
  Warnung ins Log, App startet mit leerer Liste. Wie
  `Settings._quarantine_corrupt`.
- Einzelner Datensatz ungültig (fehlende Pflichtfelder, unbekannter
  `auth.mode`, kaputte URL) → dieser eine Datensatz wird übersprungen und
  geloggt, der Rest der Liste bleibt nutzbar. Analog zur `_coerce`-Logik in
  `settings.py`: ein defekter Wert kippt nicht die ganze Konfiguration.
- `schema_version` größer als bekannt → Datei wird **nicht** angefasst und die
  Liste bleibt leer, mit Log-Hinweis. Ein älterer Build darf eine neuere Datei
  nicht überschreiben.

## Secret-Ablage und Härtung

Konfiguration **und** Secret liegen in derselben Datei. Das ist keine
Bequemlichkeit, sondern folgt daraus, dass nichts synct: es gibt keinen Grund,
`url`/`enabled`/`payload` von `auth.value` zu trennen, und eine Trennung
erzwänge das Zusammenführen zweier Quellen bei jedem Lesen, Speichern und
Löschen.

Der Schreibpfad ist derselbe wie bei `token.json` und `instance-secret`:

```
Temp-Datei schreiben → chmod 0600 → secure_file.harden_windows_acl → os.replace
```

Damit ist `webhooks.py` der dritte Secret-Schreibpfad, den `src/CLAUDE.md`
einfordert. `harden_windows_acl` bleibt best-effort und nie fatal — eine
ungehärtete Datei ist der Status quo, ein gescheiterter Schreibvorgang wäre
eine Regression.

**Was das nicht leistet:** die Datei ist nicht verschlüsselt. Wer auf dem Rechner
als derselbe Benutzer Code ausführt, liest die Secrets. Das ist dasselbe
Schutzniveau wie beim OAuth-Refresh-Token, das die App seit jeher so ablegt —
eine Keyring-Anbindung wäre ein eigenes Feature mit drei Plattform-Backends und
ist hier bewusst nicht enthalten.

## URL-Regel: https außerhalb, http innerhalb

Entschieden wird **allein an der Adresse in der URL**, ohne DNS-Auflösung.

| Host | http erlaubt |
|---|---|
| `localhost`, `127.0.0.0/8`, `::1` | ja |
| RFC 1918 (`10/8`, `172.16/12`, `192.168/16`) | ja |
| CGNAT `100.64/10` (Tailscale u.ä.) | ja |
| Link-Local `169.254/16`, `fe80::/10`; ULA `fc00::/7` | ja |
| Suffix `.local`, `.lan`, `.home.arpa`, `.internal`, `.localhost` | ja |
| Einzelnes Label ohne Punkt (`nas`, `fritzbox`) | ja |
| alles andere | **nein — https erzwungen** |

Die IP-Fälle deckt `ipaddress.ip_address(host).is_private` vollständig ab
(Loopback, RFC 1918, CGNAT, Link-Local und ULA sind dort alle als privat
geführt); der Rest ist eine Suffix-Liste plus die Single-Label-Regel. Ein
`ValueError` aus `ip_address` heißt schlicht „ist ein Name, keine IP" und führt
in den Namens-Zweig.

Im erlaubten Fall passiert **nichts** — keine Warnung, kein Hinweistext, wie
gewünscht. Im verbotenen Fall lehnt der Webhook-Dialog das Speichern ab:
*„Für Adressen außerhalb des lokalen Netzes ist https erforderlich."*

Geprüft wird an genau zwei Stellen: beim Speichern im Dialog (damit der Nutzer
es sofort erfährt) und erneut unmittelbar vor dem POST (damit eine von Hand
editierte `webhooks.json` die Regel nicht umgeht).

**Bekannte Lücke — kommt nach `docs/known-limitations.md`:** ein öffentlicher
Name, der per Split-Horizon-DNS intern auf eine private Adresse zeigt
(`erp.firma.de` → `10.0.0.5`), gilt als öffentlich und verlangt https.
Auflösen ließe sich das nur mit einem DNS-Lookup beim Speichern — der wäre
langsam, offline unmöglich und könnte später stillschweigend anders ausgehen,
ohne dass die App es merkt. Wer diesen Fall hat, trägt die interne Adresse
direkt ein.

## Auth-Verfahren

### `none`

```json
{ "mode": "none" }
```

Nackter POST. Für Dienste, bei denen die URL selbst das Geheimnis ist
(Slack/Discord/Teams-Incoming-Webhooks).

### `header` — Bearer-Token / API-Key

```json
{ "mode": "header", "header": "Authorization", "value": "Bearer abc123" }
```

Der Nutzer tippt den **kompletten** Header-Wert; die UI belegt Name mit
`Authorization` und Wert mit `Bearer ` vor. Damit ist derselbe Mechanismus auch
für `X-API-Key: …` nutzbar, ohne ein zweites Verfahren zu bauen.

Header-Name und -Wert werden gegen Steuerzeichen geprüft (`\r`, `\n`, `\x00`) und
bei einem Treffer **abgewiesen, nicht bereinigt** — dieselbe Entscheidung wie bei
der Empfängeradresse in `mail.send_email` (Audit N11 / #133): still gestrippte
Zeichen führen zu einem falschen Request, den niemand bemerkt.

### `hmac` — Signatur über den Body

```json
{ "mode": "hmac", "header": "X-Hub-Signature-256", "prefix": "sha256=", "secret": "…" }
```

`hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()`, kleingeschrieben,
mit `prefix` davor — das GitHub-Format. Algorithmus fest SHA-256; Header-Name
und Präfix sind konfigurierbar (Präfix darf leer sein).

Signiert werden die **rohen Body-Bytes**, in allen drei Content-Type-Fällen
identisch und exakt die Bytes, die auch über die Leitung gehen. Sonst kann der
Empfänger nicht verifizieren.

`hmac` und ein Auth-Header schließen sich nicht aus — HMAC beweist Integrität,
nicht Zugangsberechtigung. Sie sind hier trotzdem alternativ, weil ein
kombiniertes Formular die UI verdoppeln würde, ohne dass ein realer Empfänger
danach verlangt. Kommt der Bedarf, ist `auth` als Objekt erweiterbar, ohne das
Dateiformat zu brechen.

## Payload-Formate

| Auswahl | Content-Type | Body |
|---|---|---|
| nur JSON | `application/json; charset=utf-8` | das Report-Dokument (s.u.) |
| nur PDF | `application/pdf` | die rohen PDF-Bytes |
| beides | `multipart/form-data; boundary=…` | Teil `data` (JSON) + Teil `report` (PDF) |

Multipart statt base64-im-JSON: Empfänger wie n8n oder Make erwarten es so, und
base64 bläht die Payload um ein Drittel auf und zwingt jeden Empfänger zum
Dekodieren. Der Multipart-Body wird von Hand gebaut (stdlib reicht; die
`boundary` ist injizierbar, damit Tests deterministisch bleiben). Der PDF-Teil
trägt `filename` aus `report.default_pdf_filename` — derselbe Name wie im
Mail-Anhang.

Immer mitgesendet: `User-Agent: Zeiterfassung/<VERSION>` und
`Content-Length`. Keine weiteren App-Header, damit die Signatur nicht von
Dingen abhängt, die ein Proxy anfassen könnte.

### Das JSON-Dokument

```json
{
  "schema_version": 1,
  "kind": "zeiterfassung-report",
  "generated_at": "2026-08-26T09:14:00Z",
  "sender": "sven@…",
  "name": "Sven",
  "period": { "from": "2026-07-01", "to": "2026-07-31" },
  "categories": ["Projekt A", ""],
  "total_minutes": 9420,
  "entries": {
    "2026-07-01": { "slots": [
      { "start": "08:00", "end": "16:00", "pause": 30, "kategorie": "Projekt A" }
    ] }
  }
}
```

Die `entries` haben **exakt die Slot-Shape von `share.py` v3** — ein Empfänger,
der schon Share-Dateien liest, kann seinen Parser wiederverwenden. Das `kind`
ist trotzdem ein eigenes (`zeiterfassung-report`, nicht
`zeiterfassung-share`): das Dokument trägt Report-Metadaten, die der
Share-Validator als „unbekannte Felder" ablehnen würde. Ein Empfänger, der die
Payload versehentlich als Share-Datei zurückspielt, soll eine klare Absage
bekommen und keine halb passende Datei.

`categories` ist `null`, wenn nicht gefiltert wurde; `""` steht wie überall im
Projekt für „ohne Kategorie".

**`total_minutes`, nicht Dezimalstunden.** Summiert werden die je Slot über
`time_utils.hours_to_minutes` gerundeten Minuten — die Regel aus `CLAUDE.md`
(„Wer mehrere angezeigte Werte aufsummiert, summiert deren Minuten"). Das weicht
bewusst von `report.total_hours` ab, das Dezimalstunden summiert; jene Funktion
bedient die Live-Vorschau und den `{gesamt}`-Platzhalter und bleibt unangetastet.

**`share.py` wird dafür nicht angefasst.** Die Slot-Shape entsteht bereits in
`storage._normalize_slot` (`{start, end, pause, kategorie}`, fehlende Felder auf
`0`/`""` ergänzt), und `Storage.get_all()` liefert `{date: {slots: [...]}}` in
frischen Kopien, ohne `modified_at`/`device_id`/`deleted`. Der Entries-Teil des
Dokuments ist damit der gefilterte Snapshot, den der Sende-Dialog ohnehin schon
in der Hand hält — es gibt nichts zu projizieren, und `share.build_share_doc`
tut für Ist-Zeiten nichts anderes.

Die Kopplung ist trotzdem real und gehört benannt: `storage._normalize_slot` ist
der Ort, an dem diese Shape festgelegt wird. Wer sie dort ändert, ändert
zugleich das Share-Format **und** die Webhook-Payload. Beide Wire-Formate tragen
deshalb eine eigene `schema_version`, die dann hochzuziehen ist.

## HTTP-Transport

- **Timeout:** 30 s, fest. Der Aufruf läuft im Worker-Thread; die UI blockiert
  nicht.
- **Redirects:** werden gefolgt, aber ein eigener `HTTPRedirectHandler` bricht
  ab, sobald das Ziel-Schema schlechter ist als das Ausgangs-Schema. Ohne das
  könnte ein `301` von https auf http den Bearer-Token im Klartext ausliefern
  und die URL-Regel aushebeln.
- **Antwort:** Body wird auf 8 KB begrenzt gelesen und für die Anzeige auf die
  ersten 500 Zeichen gekürzt. Ein Endpunkt, der bei einem Fehler eine
  HTML-Seite zurückgibt, soll den Fehlerdialog nicht sprengen.
- **Keine neue Dependency:** `urllib`, `hmac`, `hashlib`, `ipaddress`, `uuid`,
  `json` — alles stdlib, alles in der Test-CI ohne `requirements.txt` verfügbar.

## Fehlerklassifikation

Eigener Klassifikator in `webhook.py`, **nicht** `mail_task.classify_mail_error`.
Grund: `urllib.error.HTTPError` ist eine Unterklasse von `URLError`, und
`URLError` steht in `mail._OFFLINE_EXC_NAMES` — ein sauberes HTTP 500 würde dort
als „keine Internetverbindung" durchgereicht. `HTTPError` wird deshalb explizit
**vor** der Offline-Prüfung abgefangen.

| Ergebnis | `kind` | Meldung |
|---|---|---|
| 2xx | — (`ok: True`) | — |
| 401, 403 | `auth` | „Die Zugangsdaten wurden abgelehnt." |
| 404 | `notfound` | „Die URL wurde nicht gefunden." |
| übrige 4xx | `client` | Status + gekürzte Antwort |
| 5xx | `server` | Status + gekürzte Antwort |
| Timeout, DNS, kein Netz | `offline` | die bestehende Offline-Formulierung |
| alles andere | `error` | Traceback |

3xx taucht nicht auf: entweder der Handler folgt dem Redirect, oder er bricht
mit einem Schema-Downgrade-Fehler ab, der als `error` zählt.

## Der Dispatcher

`send_task.perform_send` bekommt statt der festen Gmail-Parameter eine
Ziel-Beschreibung und liefert ein Ergebnis **pro Kanal**:

```python
{"results": [
    {"channel": "mail",    "name": "buchhaltung@example.com", "ok": True},
    {"channel": "webhook", "name": "Buchhaltungs-Server",     "ok": False,
     "kind": "server", "detail": "HTTP 500", "error": <exc>, "tb": None},
]}
```

Er wirft weiterhin nie — die M10-Regel bleibt. Reihenfolge: Mail zuerst, dann
die Webhooks in Listenreihenfolge. Ein Fehler bricht nichts ab.

**Payload-Erzeugung einmal, und nur bei Bedarf.** `generate_pdf` ist der
teuerste Schritt im ganzen Pfad; es läuft genau dann, wenn Mail angehakt ist
oder mindestens ein Webhook PDF will — und dann genau einmal, geteilt über alle
Kanäle. Dasselbe gilt für das JSON-Dokument.

**Die „Keine Einträge"-Prüfung wandert.** Heute fällt sie als Nebenwirkung davon
an, dass `generate_report` bei leerem Zeitraum `None` liefert. Ohne
Mail-Kanal gäbe es dieses Signal nicht mehr, und ein Webhook bekäme ein
Dokument mit leerem `entries`. Die Prüfung läuft deshalb künftig
kanalunabhängig auf den gefilterten Einträgen, **vor** dem Dispatch, mit
unveränderter Meldung und unverändertem Verhalten für den Mail-Fall.

## UI: Sende-Dialog

Unter dem Zeitraum-Block ein Ziel-Abschnitt:

```
Ziele
  [x] E-Mail an buchhaltung@example.com
  [x] Buchhaltungs-Server            [ JSON + PDF  v ]
  [ ] Slack #zeiten                  [ JSON        v ]
```

- Nur aktive (`enabled`) Webhooks erscheinen.
- **Ist keiner konfiguriert, fehlt der gesamte Abschnitt** und der Dialog ist
  Pixel für Pixel der heutige — inklusive der Mail-Checkbox, die dann gar nicht
  gebaut wird.
- Die Combobox ist mit der Payload-Vorgabe des Webhooks vorbelegt und gilt nur
  für diesen einen Versand; sie schreibt nichts zurück in `webhooks.json`.
- Kein Ziel angehakt → der Senden-Button ist deaktiviert.
- Der Empfänger-Check am Dialog-Anfang (`recipient` leer → Hinweis und
  Abbruch) greift nur noch, wenn Mail überhaupt ein mögliches Ziel ist. Ohne
  gesetzten Empfänger, aber mit konfiguriertem Webhook, öffnet der Dialog sich
  künftig mit abgehakter, deaktivierter Mail-Zeile statt gar nicht.

**Ergebnis-Anzeige:** alle Kanäle ok → eine themed Bestätigung, die sie
auflistet. Mindestens ein Fehler → themed Zusammenfassung mit ✓/✗ und
kuratierter Begründung je Kanal; ist ein `kind == "error"` darunter, folgt
zusätzlich der native `messagebox`-Dialog mit Traceback. Das hält die
Zweiteilung aus `CLAUDE.md` ein (Kuratiertes themed, Traceback nativ).

Der Dialog schließt sich wie heute bei vollem Erfolg und bleibt bei jedem
Fehler offen, damit der Nutzer denselben Zeitraum erneut senden kann.

## UI: Einstellungen-Tab „Webhooks"

Sechster Tab im Notebook, nach „Bericht & Mail":

- Liste der konfigurierten Webhooks (Name, Ziel-Host, ✓/✗ für `enabled`).
- Buttons **Hinzufügen / Bearbeiten / Entfernen**; Entfernen fragt über
  `themed_askyesno` nach.
- Bearbeiten öffnet `dialogs/webhook_dialog.py`, gebaut über
  `theme.create_dialog`, mit: Name, URL, Aktiv-Checkbox, Payload-Vorgabe (zwei
  Checkboxen), Auth-Verfahren (Combobox) und den je nach Verfahren
  eingeblendeten Feldern. Secret-Felder mit `show="•"`.
- **Testen**-Button im Unterdialog: schickt über den `runner` einen echten POST
  mit einem kleinen Beispiel-Dokument
  (`"kind": "zeiterfassung-report-test"`, ein Beispieltag) und zeigt Status
  bzw. Fehler im selben Klassifikationsschema an. Während des Laufs ist der
  Button deaktiviert; das Ergebnis kommt `winfo_exists`-gegatet zurück.

**Webhooks laufen nicht über `save_settings`.** Sie haben ihren eigenen Store
und werden vom Unterdialog direkt gespeichert. Der zentrale Settings-Save-Pfad
ist auf skalare Tk-Variablen ausgelegt; eine Liste von Dicts hindurchzufädeln
würde ihn ohne Gegenwert verkomplizieren. Der Tab braucht dadurch auch keine
Variablen an `save_settings` zu exponieren — er ist der erste Tab ohne diesen
Vertrag, was in `src/CLAUDE.md` festzuhalten ist.

## Neue und geänderte Module

| Datei | Art | Inhalt |
|---|---|---|
| `src/webhooks.py` | neu | `WebhookStore`: Laden/Speichern/Quarantäne, gehärteter Schreibpfad, `lock=`-Parameter wie die übrigen Stores |
| `src/webhook.py` | neu | pure Logik: `is_private_host`, `validate_url`, `validate_record`, `build_json_payload`, `build_body`, `auth_headers`, `sign_hmac`, `post`, `classify_error`, `perform_send` |
| `src/dialogs/webhook_dialog.py` | neu | Anlegen/Bearbeiten eines Webhooks inkl. Test-Button |
| `src/dialogs/settings_dialog/tab_webhooks.py` | neu | Listen-Tab |
| `src/dialogs/send_task.py` | geändert | Dispatcher; heutiger Gmail-Block wandert nach `_send_mail` |
| `src/dialogs/send_dialog.py` | geändert | Ziel-Abschnitt, Empfänger-Check, Ergebnis-Anzeige, kanalunabhängige Leer-Prüfung |
| `src/dialogs/settings_dialog/dialog.py` | geändert | sechster Tab |
| `src/main.py` / `src/ui.py` | geändert | `WebhookStore` erzeugen und durchreichen (geteilter `data_lock`) |

`src/share.py`, `src/report.py`, `src/mail.py` und `src/storage.py` bleiben
unangetastet.

## Tests

Alles Tk-frei, nach der Projektgrenze „Getestet wird Logik, nicht UI":

- **`tests/test_webhook.py`** — die Netzwerk-Tabelle Zeile für Zeile (jede
  Adressklasse einzeln, inkl. IPv6 und Single-Label); Auth-Header für alle drei
  Modi; Steuerzeichen-Abweisung; HMAC gegen feste Vektoren; Content-Type-Wahl
  je Payload-Kombination; Multipart-Aufbau mit injizierter Boundary;
  Fehlerklassifikation inklusive der **HTTPError-vor-URLError-Falle** und des
  Schema-Downgrade-Abbruchs bei Redirects.
- **`tests/test_webhooks_store.py`** — Laden, Speichern, Round-Trip; Quarantäne
  bei korrupter Datei; Überspringen einzelner defekter Datensätze; neuere
  `schema_version` wird nicht überschrieben; `harden_windows_acl` wird auf der
  **Temp-Datei** aufgerufen (gepatcht, wie in den bestehenden `secure_file`-Tests).
- **`tests/test_send_task_dispatch.py`** — Teilfehler (Mail ok, Webhook 500 und
  umgekehrt); PDF wird genau einmal erzeugt; PDF wird gar nicht erzeugt, wenn
  kein Kanal sie will; leerer Zeitraum wird vor dem Dispatch abgefangen;
  `perform_send` wirft auch dann nicht, wenn ein Kanal eine unerwartete
  Exception auslöst.
- **`tests/test_webhook.py`** (Payload-Teil) — das JSON-Dokument aus einem
  Beispiel-Snapshot: Slot-Shape identisch zu Share v3, `total_minutes` über
  Minuten summiert (nicht über Dezimalstunden), `categories: null` bei
  ungefiltertem Versand.

Kein Test für Tab, Dialog oder Ziel-Auswahl — deren Logik liegt in den oben
genannten pure Modulen.

## Dokumentation

Im selben PR:

- **`CLAUDE.md`** — `src/webhook.py`, `src/webhooks.py` in die Modul-Liste;
  ein Absatz zum Webhook-Versand neben der Mail-Pipeline.
- **`src/CLAUDE.md`** — `webhooks.py` in die Persistenz-Schicht; `secure_file`
  als **dritter** Schreibpfad; der neue Tab-ohne-`save_settings`-Vertrag; der
  Dispatcher-Vertrag von `send_task`.
- **`docs/known-limitations.md`** — neuer Abschnitt *„Webhooks: Split-Horizon-DNS
  gilt als öffentliche Adresse"* mit der Begründung aus dem
  URL-Regel-Abschnitt.
- **`README.md`** — kurze Erwähnung des Webhook-Ziels bei den Versandwegen.
- **`CHANGELOG.md`** + `src/version.py` — beim Release-PR, nach dem üblichen
  Prozess.

## Bewusst nicht enthalten

- **Basic Auth** — explizit abgewählt. Wer es braucht, kann es über einen frei
  benannten `Authorization`-Header nachbilden, muss den base64-Wert dann aber
  selbst erzeugen.
- **Automatische Wiederholung fehlgeschlagener Webhooks** — kein Retry, keine
  Warteschlange, keine Persistenz über Neustarts. Für einen manuell
  ausgelösten Bericht wäre das viel Maschinerie samt Duplikat-Gefahr beim
  Empfänger.
- **Automatischer Versand** (zeitgesteuert, ohne Dialog) — der Sende-Reminder
  erinnert weiterhin nur; ausgelöst wird von Hand.
- **Verschlüsselte Secret-Ablage / Keyring** — siehe „Secret-Ablage".
- **Sync der Webhook-Konfiguration** — gerätelokal, entschieden.
- **Replay-Schutz für HMAC** (signierter Zeitstempel-Header) — signiert wird nur
  der Body. Kommt der Bedarf, ist `auth` erweiterbar.
- **Reservierungen im Payload** — das Dokument enthält ausschließlich
  Ist-Zeiten, genau wie der Mail-Bericht und die PDF. Reservierungen sind
  zukünftige Soll-Zeiten und gehören nicht in eine Abrechnung; wer sie teilen
  will, nutzt weiterhin den Share-Export. Das Feld ließe sich später additiv
  ergänzen, ohne `schema_version` zu brechen.
- **Frei konfigurierbare JSON-Templates** — das Dokument hat ein festes,
  versioniertes Schema.
- **Kanal-Abstraktion, die Mail mit einschließt** — siehe „Architektur".
