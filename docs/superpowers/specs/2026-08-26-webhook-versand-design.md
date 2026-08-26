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
        └─ webhook.deliver         pro Webhook, Tk-frei, wirft nie
             └─ webhook.post       urllib, folgt keinen Redirects

webhook.py        (pure)   URL-Regel, Auth-Header, HMAC, Payload, POST, Fehler-Mapping
webhook_store.py  (Store)  webhooks.json, gehärtet wie token.json, gerätelokal
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

Damit ist `webhook_store.py` der dritte Secret-Schreibpfad, den `src/CLAUDE.md`
einfordert. `harden_windows_acl` bleibt best-effort und nie fatal — eine
ungehärtete Datei ist der Status quo, ein gescheiterter Schreibvorgang wäre
eine Regression.

Der `os.replace` am Ende trägt dieselbe **Retry-Schleife wie
`oauth_utils.write_token`** (fünf Versuche, 200 ms Abstand, nur bei
`PermissionError`). Auf Windows ist genau das die dokumentierte Flake-Quelle
(#135/#117): ein Virenscanner, der die frische Temp-Datei greift, blockiert
den Rename kurz — und hier trifft er eine Datei, deren ACL gerade eben per
`icacls` neu gesetzt wurde.

**Drei Wege, auf denen ein Secret sonst nach draußen sickert**, und wie sie
geschlossen werden:

- **Git.** `.gitignore` bekommt `webhooks.json`, `webhooks.json.corrupt-*` und
  `.webhooks-*.tmp`. Im Repo-Modus liegt die Datei neben dem Quellcode; ohne
  Eintrag wandert sie beim nächsten `git add -A` ins Repository. Das gehört in
  denselben Schritt wie der Store, nicht in die Doku-Aufräumaufgabe am Ende.
- **Logfile.** Beim Überspringen eines defekten Datensatzes wird **niemals der
  Datensatz selbst** geloggt, nur `id`/`name` und die fehlenden Schlüssel.
  `logs/zeiterfassung.log` ist ungehärtet und genau die Datei, die Nutzer bei
  Problemen anhängen.
- **Fehlerdialog.** Der Traceback-Pfad zeigt keine Locals
  (`logging_setup` nutzt `exc_info`), und die kuratierten Meldungen führen
  Secrets nicht mit. Neue Fehlertexte dürfen das nicht ändern.

**Schreibfehler dürfen nicht still bleiben.** `save`/`delete` melden einen
gescheiterten Schreibvorgang an den Aufrufer, der ihn als themed Fehlerdialog
zeigt (`CLAUDE.md` nennt den gehandhabten Speicher-`OSError` ausdrücklich als
themed-Fall). Ein Dialog, der sich schließt und den Eintrag in der Liste zeigt,
während auf Platte nichts steht, wäre die schlimmste Variante — der Nutzer
merkt es erst nach dem Neustart.

**Ein Lesefehler ist keine Korruption.** Quarantäne (Umbenennen nach
`.corrupt-<stamp>`) gibt es **nur** bei kaputtem JSON oder falschem
Toplevel-Format, nicht bei `OSError`. Ein kurzzeitig gesperrtes File
(Virenscanner, Backup, Netzlaufwerk) würde sonst umbenannt, die App startete
ohne Webhooks, der nächste Speichervorgang legte eine frische Datei an — und
die Konfiguration samt Secrets wäre weg. `settings.py` macht diese
Unterscheidung schon richtig (fängt dort nur `JSONDecodeError`/`ValueError`);
`conflicts_store.py` nicht — das ist kein Vorbild.

**Der Schreibvorgang gehört nicht in den UI-Thread.** `harden_windows_acl`
startet einen `icacls`-Subprozess mit `timeout=15`. Ein hängendes Netzlaufwerk
blockierte damit bis zu 15 Sekunden lang die Oberfläche. `src/CLAUDE.md` benennt
genau diesen Fall („Wer den Helfer in einen UI-Thread-Pfad hängt, muss das
prüfen"). Speichern und Löschen laufen deshalb über den `BackgroundTaskRunner`,
wie jede andere blockierende Operation in den Dialogen.

Der `WebhookStore` bekommt dabei bewusst **nicht** den geteilten `data_lock`
der übrigen Stores (`storage`/`settings`/`conflicts_store`/`reservations`),
sondern legt sich einen eigenen an: Webhooks nehmen an keinem Sync-Flow teil
(kein Snapshot→Merge→Apply, kein Sync-Doc, kein Journal) — es gibt also keine
übergreifende Invariante mitzuziehen. Den Lock trotzdem zu teilen hätte nur
einen Preis ohne Gegenwert gehabt: `save`/`delete` hielten ihn über den ganzen
`icacls`-Aufruf (bis 15 s plus Retries), was jeden anderen Store und einen
laufenden Drive-Sync blockiert hätte, ohne dass Webhooks von der Klammerung
je profitieren.

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

Die IP-Prüfung läuft über eine **explizit ausgeschriebene Netzliste**
(`ipaddress.ip_network` je Eintrag der Tabelle oben), nicht über
`ip_address(host).is_private`. Grund: `is_private` ist über die CI-Matrix
hinweg nicht stabil — CPython hat die Einordnung des CGNAT-Bereichs
`100.64.0.0/10` zwischen 3.10 und 3.13 geändert (RFC 6598 „Shared Address
Space" gilt dem IANA-Registry nach nicht als privat). Ein Test darauf wäre
auf 3.10 grün und auf 3.13 rot. Die eigene Liste macht die Regel
versionsunabhängig und zugleich lesbar — sie ist genau die Tabelle oben.

Der Rest ist die Suffix-Liste plus die Single-Label-Regel. Ein `ValueError`
aus `ip_address` heißt schlicht „ist ein Name, keine IP" und führt in den
Namens-Zweig.

**Zwei Bypässe, die die Single-Label-Regel sonst öffnet** — beide nachgemessen:

- **Prozent-kodierter Host.** `urlsplit("http://8%2e8%2e8%2e8/hook").hostname`
  liefert `8%2e8%2e8%2e8`: kein gültiges IP-Literal, kein Punkt darin, also
  „Single-Label" und damit privat. `urllib` dekodiert beim Request aber wieder
  (`Request(...).host` → `8.8.8.8`) und schickt den Klartext-POST samt Token an
  eine öffentliche Adresse.
- **Dezimale IP-Notation.** `http://2130706433/` ist ebenfalls ein
  punktloses Single-Label und wird vom Betriebssystem als `127.0.0.1`
  aufgelöst. Hier zufällig harmlos, aber dieselbe Lücke.

Der Host wird deshalb vor der Prüfung `unquote`d, und ein Host, der danach ein
`%` enthält **oder** ein rein numerisches Single-Label ist, wird abgewiesen —
nicht als „privat" durchgewinkt.

Gegengeprüft und unproblematisch: `user@host` (`hostname` liefert nur den
Host-Teil), abschließender Punkt, Groß-/Kleinschreibung, Punycode/Umlaut-Domains
und IPv4-in-IPv6-Mapping (`::ffff:8.8.8.8` → öffentlich, also die sichere
Richtung).

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

**Die Slots werden explizit auf diese vier Felder projiziert**, statt den
Storage-Snapshot durchzureichen. Das ist nicht überflüssig, auch wenn es beim
ersten Hinsehen so aussieht: `storage._normalize_slot` läuft nur im
**Schreibpfad** (`Storage.save`/`save_many`). `Storage._load` normalisiert
Slots **nicht** — `_migrate_legacy_entries` rüstet nur Sync-Metadaten nach und
wrappt Ein-Eintrag-Tage in eine Slot-Liste; ein bereits vorhandener
`slots`-Eintrag bleibt unangetastet. Ein Slot, der aus einer von Hand
bearbeiteten oder von einer neueren App-Version geschriebenen
`zeiterfassung.json` stammt, trägt seine Zusatzfelder also bis in
`Storage.get_all()` — und ohne Projektion bis ins Webhook-Dokument.

Die Projektion ist damit die Stelle, an der das Wire-Format tatsächlich
festgelegt wird. `share.py` wird dafür trotzdem nicht angefasst: dessen
`_share_reservation_shape` projiziert Reservierungen, nicht Ist-Zeiten, und
`build_share_doc` braucht einen Store, wo hier ein gefiltertes Dict vorliegt.

Die Kopplung an das Share-Format bleibt real und gehört benannt: beide
beschreiben dieselben vier Slot-Felder. Wer sie ändert, ändert beide
Wire-Formate — die deshalb je eine eigene `schema_version` tragen.

## HTTP-Transport

- **Timeout:** 30 s, fest. Das ist urllibs Socket-Timeout je Operation, **kein**
  Gesamt-Timeout: ein Server, der die Antwort langsam tröpfeln lässt, hält den
  Worker beliebig lange. Hinnehmbar, weil der Aufruf im Worker-Thread liegt und
  die UI nicht blockiert; ein echter Gesamt-Timeout bräuchte einen zweiten
  Thread und ist die Komplexität hier nicht wert.
- **Redirects werden NICHT gefolgt.** Ein 3xx gilt als Fehler mit eigenem
  `kind` und der Meldung „Der Endpunkt hat weitergeleitet — bitte die
  endgültige Adresse eintragen."

  Das ist die wichtigste Transport-Entscheidung, und sie geht gegen den ersten
  Reflex. `urllib` zu erlauben, Redirects zu folgen, hat drei Konsequenzen, die
  alle schlecht sind:

  1. **Der Body geht verloren.** `HTTPRedirectHandler.redirect_request` baut
     bei 301/302/303 auf einen POST eine **GET**-Anfrage ohne `data` und ohne
     `Content-Type`. Der Bericht käme nie an, der Endpunkt antwortete 200, und
     die App meldete „✓ gesendet". Ein stiller Datenverlust ist das schlechteste
     mögliche Ergebnis — schlimmer als jeder sichtbare Fehler. Und der Auslöser
     ist alltäglich: jede trailing-slash- oder http→https-Kanonisierung.
  2. **Der Auth-Header reist mit, auch zu einem fremden Host.** urllib kopiert
     alle Header außer `Content-Length`/`Content-Type` ins Redirect-Ziel und
     entfernt `Authorization` bei Host-Wechsel **nicht** (anders als
     `requests`). Ein `Location: https://fremder.host/x` lieferte Bearer-Token
     bzw. HMAC-Signatur dorthin aus.
  3. **Die URL-Regel wäre umgangen.** Ein erlaubtes lokales `http://`-Ziel
     dürfte per `302` auf eine öffentliche `http://`-Adresse weiterleiten — der
     Verkehr ginge im Klartext ins Internet, obwohl die Prüfung beim Speichern
     grün war.

  Alle drei ließen sich mit einem eigenen Handler abfangen (Body mitnehmen,
  Header bei Host-Wechsel strippen, jeden Hop erneut durch `validate_url`
  schicken). Das wäre aber sicherheitskritischer Eigenbau an einer Stelle, an
  der es eine triviale Alternative gibt: der Nutzer trägt die endgültige
  Adresse ein. Ein Webhook-Ziel ist eine feste Konfiguration, kein Browsing.

  307/308 sind hiervon nicht ausgenommen: `urllib` wirft dort ohnehin einen
  `HTTPError`, weil es sie bei POST nicht automatisch auflöst.
- **Antwort:** Body wird auf 8 KB begrenzt gelesen und für die Anzeige auf die
  ersten 500 Zeichen gekürzt. Ein Endpunkt, der bei einem Fehler eine
  HTML-Seite zurückgibt, soll den Fehlerdialog nicht sprengen.
- **Header-Namen schreibt `urllib` um.** `Request.add_header` macht
  `key.capitalize()`, `AbstractHTTPHandler.do_open` danach `name.title()`. Aus
  `X-API-Key` wird auf der Leitung `X-Api-Key`. HTTP-Header sind
  case-insensitiv, das ist also regelkonform — Empfänger mit exaktem
  String-Vergleich (handgeschriebener n8n-Code o.ä.) scheitern trotzdem daran.
  Bewusst nicht umgangen: das hieße, an urllibs Header-Pfad vorbeizuschreiben.
  Gehört nach `docs/known-limitations.md`, damit der Fall bei einer
  Support-Frage nicht neu erforscht werden muss.
- **Keine neue Dependency:** `urllib`, `hmac`, `hashlib`, `ipaddress`, `uuid`,
  `json` — alles stdlib, alles in der Test-CI ohne `requirements.txt` verfügbar.

## Fehlerklassifikation

Eigener Klassifikator in `webhook.py`, **nicht** `mail_task.classify_mail_error`.
`HTTPError` wird dabei explizit **vor** der Offline-Prüfung abgefangen.

| Ergebnis | `kind` | Meldung |
|---|---|---|
| 2xx | — (`ok: True`) | — |
| 3xx | `redirect` | „Der Endpunkt hat weitergeleitet — bitte die endgültige Adresse eintragen." |
| 401, 403 | `auth` | „Die Zugangsdaten wurden abgelehnt." |
| 404 | `notfound` | „Die URL wurde nicht gefunden." |
| übrige 4xx | `client` | Status + gekürzte Antwort |
| 5xx | `server` | Status + gekürzte Antwort |
| Timeout, DNS, kein Netz | `offline` | die bestehende Offline-Formulierung |
| alles andere | `error` | Traceback |

**Warum ein eigener Klassifikator — und warum nicht aus dem naheliegenden
Grund.** `urllib.error.HTTPError` ist zwar eine Unterklasse von `URLError`, und
`URLError` steht in `mail._OFFLINE_EXC_NAMES` — aber `mail.is_offline_error`
vergleicht über `type(exc).__name__`, nicht über `isinstance`. Ein `HTTPError`
heißt `"HTTPError"` und würde dort also **nicht** als offline gelten
(nachgemessen: `is_offline_error(HTTPError(500))` → `False`). Der eigentliche
Grund ist ein anderer: ohne die HTTPError-Behandlung fiele jede
HTTP-Fehlerantwort in den generischen Zweig und käme als *unerwarteter Fehler
mit Traceback* beim Nutzer an, statt als „Der Server hat mit 500 geantwortet".

Die Reihenfolge (HTTPError zuerst) bleibt trotzdem Pflicht — verlässt man sich
auf `isinstance`-Semantik, die `mail.py` heute zufällig nicht hat, kippt das
Verhalten beim nächsten Umbau dort.

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
- **Webhooks sind vorbelegt abgehakt, nicht angehakt.** Mail bleibt der
  Standardweg; ein Versand an einen externen Endpunkt soll eine bewusste
  Entscheidung sein und nicht passieren, weil jemand den Zeitraum bestätigt hat.
- Kein Ziel angehakt → der Senden-Button ist deaktiviert (nicht: Fehlermeldung
  nach dem Klick). Die Ziel-Häkchen tragen dafür einen gemeinsamen
  `trace_add`-Handler.
- Der Empfänger-Check am Dialog-Anfang (`recipient` leer → Hinweis und
  Abbruch) greift nur noch, wenn Mail überhaupt ein mögliches Ziel ist. Ohne
  gesetzten Empfänger, aber mit konfiguriertem Webhook, öffnet der Dialog sich
  künftig mit abgehakter, deaktivierter Mail-Zeile statt gar nicht.
- **Die deaktivierte Mail-Zeile sagt, warum sie deaktiviert ist** — „(kein
  Empfänger)" bzw. „(Zugangsdaten fehlen)". Heute bekommt der Nutzer bei
  fehlender `credentials.json` einen erklärenden Dialog mit „Datenordner
  öffnen"; künftig genügte ein einziger konfigurierter Webhook, damit dieser
  Dialog ausbleibt. Ohne Beschriftung stünde dort dann eine tote Zeile mit der
  Empfängeradresse und ohne jeden Hinweis auf die Ursache.

**Ergebnis-Anzeige:** alle Kanäle ok → eine themed Bestätigung, die sie
auflistet. Mindestens ein Fehler → themed Zusammenfassung mit ✓/✗ und
kuratierter Begründung je Kanal; ist ein `kind == "error"` darunter, folgt
zusätzlich der native `messagebox`-Dialog mit Traceback. Das hält die
Zweiteilung aus `CLAUDE.md` ein (Kuratiertes themed, Traceback nativ).

**Die Zusammenfassung darf die bestehenden Meldungen nicht verwässern.**
Scheitert genau ein Kanal, bleibt es bei der heutigen ausführlichen Meldung —
der Offline-Fall führt weiterhin seine vier Zeilen mit Handlungsanweisung, der
`filenotfound`-Fall weiterhin den vollständigen Pfad zur fehlenden
`credentials.json`. Erst wenn mehrere Kanäle beteiligt sind, tritt die
Listen-Darstellung an ihre Stelle. Andernfalls wäre der häufigste Fehlerfall
überhaupt — kein Internet beim Mailversand — nach diesem Feature schlechter
erklärt als vorher.

Der Dialog schließt sich wie heute bei vollem Erfolg und bleibt bei jedem
Fehler offen, damit der Nutzer denselben Zeitraum erneut senden kann.

## UI: Einstellungen-Tab „Webhooks"

Neuer Tab im Notebook, **direkt nach „Bericht & Mail"** — also an dritter von
dann sechs Positionen, nicht am Ende. Er gehört thematisch neben den
Versandweg, nicht hinter die Update-Einstellungen:

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
  bzw. Fehler im selben Klassifikationsschema an. Das Ergebnis kommt
  `winfo_exists`-gegatet zurück.

  Der Button braucht ein eigenes Laufflag, nicht nur `set_secondary_button_enabled`:
  dessen Docstring sagt ausdrücklich, dass er **nur die Optik** ändert und die
  `command`-Bindung aktiv bleibt. Ohne Flag löst ein Doppelklick zwei echte
  POSTs beim Empfänger aus. `send_dialog.do_send` macht es mit seinem
  `busy`-Dict richtig — dasselbe Muster hier.

**Zwei Vorbelegungs-Fallen im Auth-Block**, beide unscheinbar und beide mit
echtem Folgeschaden:

- Der Header-Name wird **je Verfahren** vorbelegt: `Authorization` für
  Token, `X-Hub-Signature-256` für HMAC. Ein gemeinsames, modusunabhängiges
  Feld führt sonst dazu, dass eine HMAC-Signatur als
  `Authorization: sha256=…` rausgeht — der Fallback im Code greift nur bei
  *leerem* Feld, und der Nutzer hat es ja nicht geleert.
- Das Token-Feld startet **leer**, mit „Bearer …" als Hinweistext daneben —
  nicht mit `"Bearer "` als Inhalt. Sonst besteht ein Webhook ohne Token die
  Validierung (`"Bearer ".strip()` ist nicht leer), geht mit leerem Token raus
  und wird vom Endpunkt mit 401 abgewiesen, während der Nutzer den Fehler
  woanders sucht.

**Webhooks laufen nicht über `save_settings`.** Sie haben ihren eigenen Store
und werden vom Unterdialog direkt gespeichert. Der zentrale Settings-Save-Pfad
ist auf skalare Tk-Variablen ausgelegt; eine Liste von Dicts hindurchzufädeln
würde ihn ohne Gegenwert verkomplizieren. Der Tab braucht dadurch auch keine
Variablen an `save_settings` zu exponieren — er ist der erste Tab ohne diesen
Vertrag, was in `src/CLAUDE.md` festzuhalten ist.

## Neue und geänderte Module

| Datei | Art | Inhalt |
|---|---|---|
| `src/webhook_store.py` | neu | `WebhookStore`: Laden/Speichern/Quarantäne, gehärteter Schreibpfad, `lock=`-Parameter wie die übrigen Stores |
| `src/webhook.py` | neu | pure Logik: `is_private_host`, `validate_url`, `validate_record`, `build_json_payload`, `build_body`, `auth_headers`, `sign_hmac`, `post`, `classify_error`, `perform_send` |
| `src/dialogs/webhook_dialog.py` | neu | Anlegen/Bearbeiten eines Webhooks inkl. Test-Button |
| `src/dialogs/settings_dialog/tab_webhooks.py` | neu | Listen-Tab |
| `src/dialogs/send_task.py` | geändert | Dispatcher; heutiger Gmail-Block wandert nach `_send_mail` |
| `src/dialogs/send_dialog.py` | geändert | Ziel-Abschnitt, Empfänger-Check, Ergebnis-Anzeige, kanalunabhängige Leer-Prüfung |
| `src/dialogs/settings_dialog/dialog.py` | geändert | sechster Tab |
| `src/main.py` / `src/ui.py` | geändert | `WebhookStore` erzeugen und durchreichen (bewusst ohne den geteilten `data_lock` — eigener Lock, siehe Absatz oben) |
| `src/report.py` | geändert | `_filter_entries` / `_apply_category_filter` werden öffentlich (`filter_period` / `filter_categories`) |

**Warum `report.py` doch angefasst wird.** Die JSON-Payload muss auf exakt
denselben Zeitraum und dieselben Kategorien gefiltert sein wie PDF und
Mail-HTML — sonst behaupten zwei Anhänge derselben Sendung unterschiedliche
Zeiträume. Diese Filter liegen heute privat in `report.py` (je drei Call-Sites,
ausschließlich dort). Sie in `webhook.py` nachzubauen wäre eine Dublette, die
beim nächsten Filter-Detail auseinanderläuft; ein modulübergreifender Zugriff
auf den privaten Namen ist im Projekt ausdrücklich unerwünscht (Audit N17).
Also werden sie umbenannt und öffentlich, Verhalten unverändert.

`src/share.py`, `src/mail.py` und `src/storage.py` bleiben unangetastet.

## Tests

Alles Tk-frei, nach der Projektgrenze „Getestet wird Logik, nicht UI":

- **`tests/test_webhook.py`** — die Netzwerk-Tabelle Zeile für Zeile (jede
  Adressklasse einzeln, inkl. IPv6 und Single-Label); Auth-Header für alle drei
  Modi; Steuerzeichen-Abweisung; HMAC gegen feste Vektoren; Content-Type-Wahl
  je Payload-Kombination; Multipart-Aufbau mit injizierter Boundary;
  Fehlerklassifikation inklusive der **HTTPError-vor-URLError-Falle** und des
  Schema-Downgrade-Abbruchs bei Redirects.
- **`tests/test_webhook_store.py`** — Laden, Speichern, Round-Trip; Quarantäne
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

- **`CLAUDE.md`** — `src/webhook.py`, `src/webhook_store.py` in die Modul-Liste;
  ein Absatz zum Webhook-Versand neben der Mail-Pipeline.
- **`src/CLAUDE.md`** — `webhook_store.py` in die Persistenz-Schicht; `secure_file`
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
