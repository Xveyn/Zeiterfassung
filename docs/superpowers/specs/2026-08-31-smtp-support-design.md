# SMTP-Support — Design

**Datum:** 2026-08-31
**Status:** Design abgestimmt und nach Review überarbeitet; Implementierungsplan in
`docs/superpowers/plans/2026-08-31-smtp-support.md`
**Branch:** `worktree-feat+smtp-support`

> **Revision 2 (2026-08-31)** — nach einem dreiteiligen Review (Status-Quo-Treue,
> CLAUDE.md-Regelkonformität, technische Kritik). Was sich gegenüber Revision 1
> geändert hat, steht in „Was das Review korrigiert hat" am Ende.

## Problem

Berichte verlassen die App heute ausschließlich über die Gmail-API. Wer sie
per Mail verschicken will, braucht ein eigenes Google-Cloud-Projekt mit
aktivierter Gmail-API, einen OAuth-Zustimmungsbildschirm und eine
`credentials.json` — beschrieben im README-Abschnitt „Gmail API einrichten".
Das ist für ein kleines Desktop-Tool eine hohe Einstiegshürde, und für alle,
die gar kein Google-Konto benutzen wollen, eine geschlossene Tür: sowohl der
Sende- als auch der Teilen-Dialog brechen ohne `credentials.json` mit einem
Hinweis auf das Cloud-Setup ab.

Ein klassischer SMTP-Zugang (Server, Port, Benutzer, Passwort) ist der Weg,
den jeder Mail-Anbieter und jeder Firmen-Mailserver anbietet und den jeder
Mail-Client seit dreißig Jahren spricht.

## Ziel

SMTP wird ein **vollwertiger, gleichrangiger Mailweg neben der Gmail-API** —
in beiden Sendepfaden (Bericht senden und Teilen). Die App verlangt künftig,
dass **einer von beiden** Wegen eingerichtet ist, nicht mehr zwingend die
Gmail-API. Das gilt für **jeden** Abbruch- und Erklärtext: wo heute „Bitte
erstelle ein Google Cloud Projekt" steht, muss der zweite Weg mitgenannt
werden, sonst bleibt die Sackgasse bestehen, gegen die das Feature gebaut wird.

Struktur: **n SMTP-Konten**, jedes mit eigenem Empfänger, jedes im
Sende-Dialog einzeln ankreuzbar — exakt das Muster der Webhooks.

## Status Quo

- `src/mail.py` — `get_gmail_service()` (OAuth-Flow, `credentials.json` +
  `token.json`, Scope-Upgrade-Erkennung) und `send_email(service, to, subject,
  html, attachment…)`. In `send_email` stecken der MIME-Bau, **zwei der drei
  UTF-8-Pflichten** (`MIMEText(…, _charset="utf-8")` und `Header(subject,
  "utf-8")`) und die Steuerzeichen-Abwehr gegen Header-Injection (Audit N11) —
  verwoben mit dem Gmail-Versand. Die dritte Pflicht, `<meta charset="utf-8">`
  im `<head>`, sitzt bei den HTML-Erzeugern: `src/report.py` und
  `src/dialogs/share_dialog.py`. Dazu Scope-Verwaltung und `is_offline_error`.
- Zwei Aufrufer senden tatsächlich: `dialogs/send_task.py::_send_mail`
  (Bericht) und `dialogs/share_task.py::perform_share` (Teilen). Beide holen
  sich selbst einen Gmail-Service — der Transport ist hart verdrahtet.
- `send_task.perform_send` ist seit Audit M10 bereits ein **Dispatcher** über
  Kanäle (Mail + n Webhooks), sammelt je Kanal ein Result-Dict und wirft nie.
- `webhook_store.py` ist das Vorbild für einen gerätelokalen Store mit
  Secrets: gehärtet geschrieben, reist nicht per Drive-Sync. Sein
  `_is_wellformed` prüft beim Laden bewusst **auch Werte** (u. a. die URL) —
  „sonst erschiene ein Eintrag mit kaputter oder unsicherer Adresse in der
  Ziel-Auswahl und scheiterte erst beim Senden".
- Gating im Sende-Dialog: `mail_possible = recipient and
  os.path.exists(credentials_path)`; ohne Ziel bricht der Dialog ab. Der
  Teilen-Dialog bricht sogar **vor** dem Dialogaufbau ab, wenn
  `credentials.json` fehlt (`share_dialog.py:31-33`).
- SMTP kommt im Repo bisher nirgends vor.

## Architektur-Entscheidung: gemeinsamer MIME-Bau, getrennte Transporte

Verworfen wurden zwei Alternativen:

- **SMTP baut seine Nachricht selbst** (`mail.py` bleibt unberührt): Die
  UTF-8-Pflichten und die Injection-Abwehr stünden zweimal im Repo — genau
  die Stelle, an der eine Kopie mit der Zeit auseinanderläuft.
- **Volle Transport-Abstraktion** (`Transport`-Interface, zwei
  Implementierungen, beide Aufrufer kennen nur noch Transporte): saubere
  Struktur, aber ein Umbau am funktionierenden Gmail-Pfad in beiden Aufrufern
  für einen Nutzen, den zwei Implementierungen noch nicht einfordern.

Gewählt: **das Gemeinsame herausziehen, den Rest getrennt lassen.** Der
MIME-Bau wandert in ein eigenes reines Modul, das beide Transporte nutzen;
`send_task.perform_send` bleibt der Dispatcher, der er ist, und bekommt SMTP
als dritten Kanaltyp. Kein Interface auf Vorrat — aber die eine Regel, die
nicht doppelt existieren darf, existiert nicht doppelt und wird dabei zum
ersten Mal isoliert testbar.

## Datenmodell & Secrets

### `src/smtp_store.py` (neu)

Spiegelt `webhook_store.py`: `smtp.json` neben `token.json`, gehärtet
geschrieben (chmod 0600 + `secure_file.harden_windows_acl` auf der
Temp-Datei, dann `os.replace`), `SCHEMA_VERSION`, Quarantäne statt stillem
Verwerfen bei kaputter Datei, `SmtpStoreReadOnly` bei neuerer
Schema-Version, dazu `get_all` / `enabled` / `save` / `delete` und
`validate_record`.

Reist **nicht** per Drive-Sync und steht **nicht** im Share-Doc — dieselbe
Begründung wie bei den Webhooks: kein Secret im Sync-Doc. `smtp.json`, ihre
Quarantäne-Kopien und die Temp-Dateien gehören in `.gitignore`, wie
`webhooks.json` — im Repo-Modus liegt die Datei im Repo-Root, und im
Datei-Fallback steht das Passwort im Klartext darin.

Record:

```
{id, name, enabled, host, port,
 security: "starttls" | "ssl" | "none",
 username, from_addr, recipient,
 password_location: "keyring" | "file",
 password?}          # nur bei password_location == "file"
```

Die `id` trägt die Zuordnung — im Store **und** als Keyring-Account —, nicht
der Name; der ist umbenennbar (Webhook-Muster).

`validate_record` prüft vor dem Speichern:

- `name` nicht leer und im Store eindeutig
- `host` nicht leer
- `port` ganzzahlig, 1–65535
- `security` einer der drei erlaubten Werte
- `from_addr` und `recipient` nicht leer und ohne Steuerzeichen
- `username` **darf leer sein** (interner Relay ohne Auth)

Das Passwort prüft `validate_record` **nicht** — es steht bei aktivem
Schlüsselbund gar nicht im Record. Die Regel „bei gesetztem Benutzer ist ein
Passwort Pflicht" gehört in den Dialog, der das Eingabefeld besitzt, und gilt
dort nur beim **Neuanlegen**; beim Bearbeiten heißt ein leeres Feld
„unverändert" (s. UI).

`_is_wellformed` (die Ladeprüfung) prüft **nicht nur die Existenz der Keys,
sondern auch `security in SECURITY_MODES`.** Das ist keine Kosmetik: `_open`
verbindet bei jedem unbekannten Wert unverschlüsselt (s. u.), und
`validate_record` läuft beim Laden nie. `webhook_store` prüft aus demselben
Grund die URL mit.

Das Keyring-Secret räumt **der Aufrufer** ab (`tab_smtp._remove`, nach
erfolgreichem `store.delete`), nicht der Store: `SmtpStore` bleibt damit reine
Dateipersistenz und lässt sich ohne Zugriff auf den echten Credential Manager
des Entwicklerrechners testen.

### `src/keyring_store.py` (neu)

Kapselt den OS-Schlüsselbund (Windows Credential Manager / macOS Keychain /
Linux Secret Service) hinter vier Funktionen:

```
set_secret(record_id, password) -> "keyring" | "file"
get_secret(record) -> str
delete_secret(record_id) -> None
persist_password(record, typed) -> dict     # rein, ohne OS-Zugriff testbar
```

`import keyring` erfolgt **lazy innerhalb der Funktionen** — Pflicht, weil
die Importkette `src.ui → … → smtp_store` sonst die Lib in die CI zieht, die
bewusst nur `requirements-test.txt` installiert (gleiches Muster wie die
Google-Wrapper in `drive.py`/`gcal.py`). Der Import trägt ein
`# pyright: ignore[reportMissingImports]`, weil `keyring` im typecheck-Job
nicht installiert ist — das etablierte Muster für genau diesen Fall.

Service-Name `Zeiterfassung`, Account ist die Record-`id`.

`set_secret` liefert zurück, wo das Secret gelandet ist; genau dieser Wert
steht als `password_location` im Record. Ist kein Backend verfügbar
(`keyring.errors.NoKeyringError`, oder `keyring.backends.fail.Keyring` als
aktives Backend), fällt es auf `"file"` zurück: das Passwort steht dann als
`password` im Record in der ohnehin gehärteten `smtp.json`. Der
Bearbeiten-Dialog zeigt den Zustand als eigene Zeile, nicht als Fußnote:

> „Passwort liegt im Windows-Schlüsselbund."
> „Kein Schlüsselbund verfügbar — das Passwort wird lokal in `smtp.json` gespeichert."

**`persist_password` ist die Zustandslogik als reine Funktion.** Sie
entscheidet aus `(record, typed)`, was gespeichert wird — leeres Feld heißt
„unverändert", ein neues Passwort geht in den Schlüsselbund oder in die
Datei, ein bestehender Datei-Fallback bleibt erhalten, ein Wechsel
keyring→file setzt `password`, der umgekehrte Wechsel entfernt es. Vier Fälle
mit vier Tests. Sie darf **nicht** als Closure im Dialog leben: CLAUDE.md sagt
dazu wörtlich „Wer ein Feature baut, dessen Logik nur im Widget lebt, hat sie
am falschen Ort — nicht einen fehlenden UI-Test."

**Der Watchdog ist Pflicht, nicht Kür.** Jeder der drei OS-Zugriffe läuft
hinter einem Sekundär-Thread mit `join(timeout=5)`; läuft er ab, gilt der
Schlüsselbund als nicht verfügbar und die Funktion kehrt zurück. Grund: auf
Linux meldet das `SecretService`-Backend sich schon dann als nutzbar, wenn der
D-Bus-Name lediglich *aktivierbar* ist — im AppImage-Fall also praktisch
immer —, und `get_preferred_collection()` ruft `collection.unlock()` **ohne
Timeout**. Blockiert das (kein Prompt, gesperrter Schlüsselbund), kehrt der
Worker nie zurück, `BackgroundTaskRunner` ruft `on_done` nie, und der
Sende-Dialog steht **dauerhaft** auf „Sende…" — bis zum App-Neustart. Genau
dieser Ausfall ist in pip (#7883) und poetry (#8623) dokumentiert. Für
`smtp.send` wurde gegen dieselbe Fehlerklasse ein Timeout eingebaut; der
Schlüsselbund braucht ihn genauso.

Zwei weitere Regeln, die sonst später weh tun:

- **Ein Konto zu löschen löscht auch sein Keyring-Secret** — sonst bleibt es
  dauerhaft verwaist. Zuständig ist der Aufrufer (s. o.).
- **Beim Speichern wird das Secret erst nach dem Datensatz geschrieben** —
  oder bei einem Fehlschlag kompensiert. Andernfalls hinterlässt jedes
  gescheiterte `store.save` (Read-Only-Datei, volle Platte) ein Secret unter
  einer `id`, die in keiner Datei mehr steht und die niemand je wieder
  findet oder löscht.

## Versandpfad

### `src/mime_message.py` (neu, rein, stdlib-only)

```
build_message(*, to, subject, html_body,
              attachment_bytes=None, attachment_filename=None,
              attachment_subtype="pdf", from_addr=None)
```

Enthält den kompletten MIME-Bau: `MIMEText(html_body, "html",
_charset="utf-8")`, `Header(subject, "utf-8")`, optionaler
`MIMEApplication`-Anhang mit `Content-Disposition`, und die
Steuerzeichen-Abwehr (`\r`, `\n`, `\x00`) — die jetzt **auch `from_addr`**
prüft: beim SMTP-Versand ist der Absender ein zweites nutzergefülltes
Headerfeld mit demselben Injection-Risiko. `from_addr` wird nur gesetzt, wenn
übergeben (Gmail braucht es nicht, dort ist der authentifizierte Nutzer der
Absender).

Der Betreff braucht **keine** eigene Abwehr: `Header(subject, "utf-8")`
kodiert immer nach RFC 2047, auch reines ASCII — ein eingeschleustes `\r\n`
landet in der kodierten Nutzlast, nicht als neuer Header.

**Zwei der drei UTF-8-Pflichten liegen damit an genau einer Stelle**
(`MIMEText`-Charset und Betreff-Header). Die dritte, `<meta charset="utf-8">`
im `<head>`, bleibt bei den HTML-Erzeugern (`report.generate_report`,
`share_dialog`) — ein künftiger Mail-Kanal, der sein HTML selbst baut, kann
sie also weiterhin verletzen. Das gehört so in `CLAUDE.md`, statt dort
„alle drei liegen jetzt in `mime_message`" zu behaupten.

`mail.send_email` behält Signatur samt Legacy-Aliasen (`pdf_bytes`/
`pdf_filename`) und schrumpft auf `build_message(...)` → base64url →
API-Call. Kein Aufrufer ändert sich; `tests/test_mail.py` bleibt unverändert
grün und ist damit die Absicherung, dass der Umbau am Bestand nichts
verschiebt.

### `src/smtp.py` (neu, Tk-frei)

Stdlib bis auf einen Import: `mail.is_offline_error` wird wiederverwendet,
statt die Offline-Erkennung zu kopieren. `src/mail.py` ist auf Modulebene
selbst Google-frei (die Google-Importe sind lazy), es entsteht also kein
CI-Problem und kein Zyklus.

```
send(record, password, *, subject, html, to=None,
     attachment_bytes=None, attachment_filename=None,
     attachment_subtype="pdf") -> None
test_connection(record, password) -> None
classify_smtp_error(exc) -> dict
```

`to` überschreibt `record["recipient"]`. Der Bericht-Versand lässt es weg —
das Konto trägt seinen Empfänger. Der Teilen-Pfad setzt es: dort gibt der
Nutzer den Empfänger im Dialog ein, und der SMTP-Record liefert nur Transport
und Absender (s. „Teilen").

Verbindungsaufbau nach `security`, **fail-closed**:

- `"ssl"` → `SMTP_SSL` (implizites TLS, typisch 465)
- `"starttls"` → `SMTP` + `starttls()` (typisch 587)
- `"none"` → `SMTP` ohne TLS
- **alles andere → `ValueError`.** Kein `else`-Zweig, der bei unbekanntem
  Wert unverschlüsselt verbindet. Das Design sagt „TLS mit voller
  Zertifikatsprüfung, ohne Schalter zum Abschalten" — ein durchgerutschter
  Wert wäre genau so ein Schalter, nur unbeabsichtigt.

Weiteres:

- **TLS über `ssl.create_default_context()` mit voller Zertifikatsprüfung,
  ohne Schalter zum Abschalten.** Eine solche Option wird erfahrungsgemäß
  angeklickt, um ein Problem loszuwerden, und bleibt dann für immer an. Der
  Kontext wird auch an `starttls()` übergeben — ohne ihn fällt `smtplib` auf
  einen Kontext **ohne** Hostname- und Zertifikatsprüfung zurück.
- Fester Timeout (20 s) — sonst hängt der Worker unbegrenzt an einem stummen
  Server.
- `login()` nur bei gesetztem Benutzer.
- Die Verbindung wird immer geschlossen, auch wenn `quit()` scheitert:
  `quit()` ruft `close()` erst *nach* einem `QUIT`-Kommando, das auf einer
  toten Verbindung wirft — ohne ein `finally: server.close()` leckt der
  Filedescriptor.
- `test_connection` verbindet, loggt ein und schickt `noop()` — **keine
  Mail**.

`classify_smtp_error` ist ein **eigener** Klassifikator, Vorbild `webhook.py`
und nicht `mail_task.classify_mail_error`: dessen drei Kinds
(`filenotfound`/`offline`/`error`) würden alles Interessante zu
„unerwarteter Fehler mit Traceback" verschmelzen. Kinds:

| Kind | Auslöser |
|------|----------|
| `auth` | `SMTPAuthenticationError`; außerdem `SMTPNotSupportedError` aus `login()` |
| `recipient` | `SMTPRecipientsRefused`, `SMTPSenderRefused` |
| `tls` | `ssl.SSLError` (inkl. `SSLCertVerificationError`); `SMTPNotSupportedError` aus `starttls()` |
| `server` | jede sonstige `SMTPException` |
| `offline` | `mail.is_offline_error`, plus nacktes `OSError` ohne SMTP-Bezug |
| `error` | alles Übrige, mit Traceback |

Drei Details, die das Review aufgedeckt hat und die nicht verhandelbar sind:

- **`SMTPNotSupportedError` ist nicht immer TLS.** `smtplib` wirft sie auch
  aus `login()` („SMTP AUTH extension not supported") und aus
  `send_message()` (Nicht-ASCII-Adresse ohne SMTPUTF8). Ein Firmen-Relay ohne
  AUTH, bei dem versehentlich ein Benutzer eingetragen ist, meldete sonst
  „Verschlüsselung fehlgeschlagen" — der Nutzer dreht an TLS-Einstellungen,
  die nichts damit zu tun haben. Deshalb fängt `_open` `starttls()` und
  `login()` **einzeln** und übersetzt sie an Ort und Stelle.
- **`SMTPRecipientsRefused` hat kein `smtp_code`/`smtp_error`,** sondern
  `recipients` — ein Dict. Ohne eigenen Zweig zeigte die Meldung wörtlich
  `{'a@b': (550, b'5.1.1 User unknown')}` mit geschweiften Klammern und
  Bytes-Literal. Genau der häufigste Empfängerfehler.
- **`SMTPServerDisconnected` nach Timeout darf nicht „offline" heißen.**
  `smtplib` wirft sie aus einem `except OSError`-Block, und
  `is_offline_error` folgt `__context__` bis zum `TimeoutError` des Sockets.
  Ein Server, der die Verbindung annimmt und dann schweigt — der Fall, für den
  der Timeout überhaupt existiert —, meldete sonst „keine
  Internetverbindung". Der `SMTPException`-Zweig steht deshalb **vor** der
  Offline-Prüfung.

`_KIND_TEXTS` in `send_task.py` wächst um `recipient` und `tls`.

### Dispatcher (`src/dialogs/send_task.py`)

`perform_send` bekommt den Parameter `smtp_accounts` — die im Sende-Dialog
angehakten Records.

- `needs_pdf` zählt sie mit: SMTP hängt die PDF an wie der Mail-Kanal. Das
  PDF entsteht weiterhin genau einmal und nur, wenn ein Kanal es braucht.
- Scheitert die PDF-Erzeugung, fallen Mail **und** SMTP-Konten mit demselben
  Failure-Result aus; die JSON-Webhooks laufen weiter (bestehende Logik,
  erweitert).
- Jedes Konto liefert `{"channel": "smtp", "name": "<Konto> (<Empfänger>)", …}`
  — der Name allein reichte nicht: bei genau einem Ergebnis meldet der Dialog
  „Bericht wurde an {name} gesendet", und dort stand bisher immer eine
  Adresse.
- Ein Fehler in einem Konto bricht die übrigen Kanäle nicht ab; der Vertrag
  „wirft nie" gilt unverändert für den ganzen Dispatcher. Dazu gehört eine
  **Normalisierung wie beim Mail-Kanal**: sind SMTP-Konten gewählt, aber es
  gibt kein `mail`-Dict mit Betreff und HTML, wird nicht mit leerem Betreff
  gesendet, sondern je Konto ein Failure-Result erzeugt. Ein direkter
  Zugriff `mail["subject"]` wäre zudem ein `KeyError` **außerhalb** jedes
  `try` — der Runner schluckt ihn, `on_done` feuert nie, der Dialog steht auf
  „Sende…".
- Das Passwort holt der **Worker** über `keyring_store.get_secret(record)`,
  direkt vor dem Verbinden — nie im Tk-Callback.

### Teilen (`src/dialogs/share_task.py` und `share_dialog.py`)

`perform_share` bekommt statt der festen Gmail-Annahme einen
`transport`-Parameter: `None` heißt Gmail wie bisher, sonst ein SMTP-Record.

Drei Dinge am Dialog sind **Voraussetzung**, nicht Beiwerk:

1. **Das Credentials-Gate muss kippen.** Heute bricht `open_share_dialog` ab,
   bevor irgendetwas gebaut wird, wenn `credentials.json` fehlt. Ohne Änderung
   ist der gesamte SMTP-Teilen-Pfad für die Zielgruppe unerreichbar — der
   zweite Sendepfad wäre toter Code. Künftig: abbrechen nur, wenn weder
   `credentials.json` noch ein aktives SMTP-Konto existiert; sonst öffnen und
   „Gmail" in der Auswahl weglassen bzw. deaktivieren.
2. **Der Fehlerzweig muss die neuen Kinds kennen.** `on_done` verzweigt heute
   nur auf `filenotfound` und `offline` themed; alles andere geht in den rohen
   `messagebox.showerror` mit `res["tb"]`. Da `classify_smtp_error` für
   erwartete Fehler bewusst `tb=None` liefert, sähe der Nutzer bei einem
   falschen Passwort einen nativen Dialog mit der Zeile „None". Das verletzt
   die N14-Zweiteilung und das eigene Abnahmekriterium. Künftig: alle Kinds
   außer `error` themed über `format_result_summary`, der native
   Traceback-Dialog nur noch bei `kind == "error" and res.get("tb")`.
3. **Der Empfänger bleibt das Eingabefeld.** Der Teilen-Dialog fragt bewusst
   nach einer Adresse; das `recipient`-Feld des Kontos ist semantisch etwas
   anderes („wohin dieses Konto **den Bericht** schickt", typisch die
   Buchhaltung). Deshalb bekommt `smtp.send` den `to`-Parameter. Ein
   sichtbares, ausgefülltes Feld, das ignoriert wird, wäre eine Falle: das
   Share-JSON mit allen Arbeitszeiten ginge an jemand anderen als angezeigt.

Der Share-Doc-Bau selbst bleibt unangetastet.

### Unverändert

`settings["sender_email"]` bleibt der Gmail-Absender (er speist u. a. das
`sender`-Feld im Webhook-JSON-Payload) und wird von einem SMTP-Konto **nicht**
überschrieben — das ist eine Google-Identität, keine allgemeine
Absenderangabe.

## UI

### Neuer Tab „SMTP"

Im Settings-Dialog **hinter „Webhooks"**: Liste mit Hinzufügen / Bearbeiten /
Entfernen, gebaut wie `tab_webhooks.py` (`src/dialogs/settings_dialog/
tab_smtp.py`). Dazu `src/dialogs/smtp_dialog.py` als Geschwister von
`webhook_dialog.py` — über `theme.create_dialog`, themed Messageboxes,
„Speichern" und „Verbindung testen" beide über den `BackgroundTaskRunner`,
keine dialogspezifischen Stil-Extras (Theme bleibt einheitlich).

Zwei Hinweise stehen dort als Text, nicht als Fußnote:

- **Microsoft-Konten funktionieren nicht.** Outlook.com und Microsoft 365
  haben SMTP mit Basic Auth 2026 abgeschaltet (Ablehnung ab März,
  endgültig 30.04.2026) — **auch App-Passwörter** greifen dort nicht mehr,
  SMTP geht nur noch über OAuth2. Ohne diesen Hinweis liest sich das
  resultierende `535 Authentication unsuccessful` wie ein Tippfehler.
- **Gmail braucht ein App-Passwort** (16-stellig, setzt aktive 2FA voraus) —
  nicht das Kontopasswort.

Beim Bearbeiten bleibt das Passwortfeld **leer**, und „leer = unverändert".
Ein gespeichertes Secret wird nie zurück in ein Widget geholt. Beim
**Neuanlegen** ist ein Passwort Pflicht, sobald ein Benutzer gesetzt ist —
diese Prüfung sitzt im Dialog, nicht in `validate_record`.

„Verbindung testen" arbeitet auf den **aktuellen Feldwerten**, nicht auf dem
gespeicherten Record — sonst könnte man eine Korrektur nicht prüfen, ohne sie
vorher zu speichern. Das Passwort nimmt es aus dem Feld; ist das leer und
existiert der Record bereits, liest es der Worker über
`keyring_store.get_secret`. Die Erfolgsmeldung unterscheidet die Fälle: ohne
Benutzer wurde **keine** Zugangsdatei geprüft, nur die Erreichbarkeit.

### Sende-Dialog

Die Zielliste bekommt die aktivierten SMTP-Konten als eigene
Checkbox-Zeilen zwischen Mail und Webhooks.

Das Gating kippt von „`credentials.json` muss da sein" auf **„mindestens ein
Ziel"**:

```
mail_possible = bool(recipient) and os.path.exists(credentials.json)
smtp_possible = bool(smtp_store.enabled())
```

Abgebrochen wird nur, wenn Mail, SMTP und Webhooks alle leer sind. **Beide**
Abbruchtexte nennen künftig beide Wege — auch
`show_missing_credentials_dialog`, das sonst genau die Google-Sackgasse
bleibt, die das Feature abschaffen soll (und das derselbe Text ist, den auch
der Teilen-Dialog benutzt).

### Verdrahtung

Analog `webhook_store`: `SmtpStore` in `main.py` neben `WebhookStore`
anlegen, über `App` an Sende-, Einstellungs- **und Teilen-Dialog**
durchreichen. Letzterer bekommt heute keinen Store — das ist der einzige neue
Durchreichepfad.

## Tests

Alles Neue außer der Tk-Schicht ist pure Logik und wird getestet; die
UI-Schicht bleibt untestet (entschiedene Scope-Grenze M16, siehe
`docs/known-limitations.md`). Der Zuschnitt hält diese Grenze ein: die
Versandlogik lebt in `smtp.py`, die Passwort-Zustandslogik in
`keyring_store.persist_password` — nicht im Widget.

- `tests/test_mime_message.py` — UTF-8-Pflichten, Injection-Abwehr in `to`
  **und** `from_addr`, Anhang-Subtype, `from_addr` nur wenn übergeben
- `tests/test_smtp.py` — Verbindungsaufbau je `security` **inklusive der
  Abweisung unbekannter Werte**, der an `starttls()` übergebene TLS-Kontext,
  `to`-Override, und die Fehlerklassifikation gegen einen `smtplib`-Stub
- `tests/test_smtp_store.py` — Validierung, Quarantäne, Read-Only, Rollback
  nach Schreibfehler, Lock-Injektion, Härtung **auf der Temp-Datei**, und das
  Überspringen eines Datensatzes mit ungültigem `security`
- `tests/test_keyring_store.py` — Keyring-Pfad, Fallback-Pfad, Watchdog-Timeout,
  Löschen, und die vier Fälle von `persist_password`
- `tests/test_send_task_dispatch.py` — erweitert um den dritten Kanaltyp
  (unabhängiges Feuern, PDF-Fehler zieht SMTP mit, JSON-Webhooks laufen
  weiter, Normalisierung ohne `mail`)
- `tests/test_share_task.py` — erweitert um den `transport`-Parameter
- `tests/test_mail.py` — bleibt unverändert; grün heißt, der Umbau von
  `send_email` hat nichts verschoben

Alle neuen Tk-freien Module werden **vollständig** annotiert (Rückgabetyp und
alle Parameter) und in die Whitelist in `tests/test_type_annotations.py`
eingetragen.

## Abhängigkeiten & Build

- `keyring==25.7.0` gepinnt in `requirements.txt` (verlangt Python ≥3.9) und
  in der README-Tabelle der Abhängigkeiten ergänzt.
- **Drei transitive Pakete werden mitgepinnt** — eine bewusste, kommentierte
  Ausnahme von der Transitiv-Regel: `jaraco.functools`, `jaraco.context` und
  `importlib_metadata` fordern in ihren aktuellen Versionen bereits `>=3.10`.
  Der effektive Python-Boden liegt damit **exakt** auf unserem Release-Python,
  ohne Puffer; zieht jaraco seine Skeleton-Pakete auf `>=3.11`, bricht der
  Build still über eine Dep, die niemand angefasst hat, und der in CLAUDE.md
  vorgeschriebene 3.10-Gegencheck schlägt nicht an, weil er nur die direkte
  Dep betrachtet.
- **Nicht** in `requirements-test.txt`. Kein Test benutzt die echte Lib (alle
  schieben ein Fake-Modul in `sys.modules`), und `SecretStorage` zieht
  `cryptography` mit — eine Rust-Extension, also genau die Klasse, wegen der
  diese Datei überhaupt existiert.
- `scripts/build.py`: `--collect-all keyring`. **Redundant, und das gehört so
  im Kommentar zu stehen:** PyInstaller 6.20 bringt `hook-keyring.py` selbst
  mit (`collect_submodules("keyring.backends")` + `copy_metadata`); das
  keyring-Wheel enthält keinen eigenen Hook. Die Zeile bleibt als Absicherung
  gegen einen Wegfall dieses Core-Hooks — aber sie steht **nicht** in der
  Liste der zwingenden `--collect-all` in `tests/test_build.py`, weil sie
  keine Pflicht ist. Ein falsch begründeter Required-Test ist schlechter als
  keiner.

**Verifikation vor dem Release:** Das ist genau der Fall, für den CLAUDE.md
den Pre-Release vorschreibt — eine neue Dependency mit plattformabhängigen
Backends, auf der Windows-Dev-Maschine nicht für macOS und Linux prüfbar.
Also **Pre-Release über alle drei Plattformen**. Je Plattform zu prüfen:

1. Konto anlegen, Passwort speichern — landet es im Schlüsselbund oder im
   Datei-Fallback? (`keyring.core.get_keyring()` im gebauten Artefakt
   ausgeben lassen, statt am Symptom zu raten.)
2. Verbindungstest, echter Versand.
3. **Linux:** verhält sich die App ohne laufenden Secret Service sauber —
   Meldung statt Absturz, und vor allem: greift der Watchdog?
4. **macOS: zweimal bauen**, das Bundle austauschen, erneut senden. Kommt der
   Keychain-Dialog wieder? Wenn ja, ist das die dauerhafte Realität ohne
   Developer-ID-Signatur (s. u.) und gehört dokumentiert.

## Dokumentation

- README: neuer Abschnitt „E-Mail-Versand ohne Google (SMTP)" mit
  `*(ab X.Y.Z)*`-Marker; der bestehende Gmail-Abschnitt bekommt einen
  Querverweis. Zusätzlich nachzuziehen: der Block **Zugangsdaten** im
  Abschnitt Datenspeicherung (`smtp.json` fehlt dort), der Sicherheitshinweis
  „**Drei** Dateien im Datenordner sind Geheimnisse" (werden vier) und der
  Projektstruktur-Baum. Der Satz über den Schlüsselbund darf im Dev-Modus
  nicht mehr Schutz versprechen, als existiert: dort ist die ACL-Identität
  das Python-Executable, nicht die App.
- `docs/known-limitations.md`: **drei** Einträge —
  1. **Microsoft-Konten** lassen sich nicht per SMTP anbinden (OAuth2-only).
  2. **SMTP-Konten sind gerätelokal**: wie Webhooks und Urlaub reisen sie
     nicht per Drive-Sync.
  3. **macOS fragt nach jedem Update erneut nach dem Schlüsselbund.**
     PyInstaller signiert ad-hoc, das Keychain-ACL hängt am `cdhash`, der
     sich mit jedem Build ändert; „Immer erlauben" gilt deshalb nur für
     genau diesen Build. Zusätzlich verwirft `keyring` bei jeder
     Passwortänderung die ACL, weil es delete+add statt update macht.
- `CLAUDE.md` und `src/CLAUDE.md` sind an mehreren Stellen nachzuziehen, nicht
  nur um die neuen Modul-Einträge. Insbesondere: `secure_file` zählt dort
  „drei Secrets" und lädt ein, „einen **vierten** Schreibpfad" zu bauen —
  `smtp.json` **ist** der vierte; die Ausnahmeliste in `json_store`; „`tab_webhooks`
  als **einziger** Tab ohne Variablen"; „die **zwei** Netz-Kerne teilen sich
  `classify_mail_error`"; der „sechs Tabs"-Docstring in `settings_dialog/dialog.py`.

## Bewusst nicht dabei (YAGNI)

- **Kein OAuth2 für SMTP** (XOAUTH2). Es würde Microsoft-Konten
  zurückholen, wäre aber ein zweiter vollständiger Auth-Flow neben dem
  bestehenden.
- **Keine Anbieter-Presets.** Rein manuelle Eingabe; kein Anbieter-Katalog,
  der veraltet, wenn jemand seine Ports ändert.
- **Kein Reply-To / CC / BCC.**
- **Kein Abschalten der Zertifikatsprüfung.**
- **Keine Migration der bestehenden Secrets** (`token.json`,
  `credentials.json`, `webhooks.json`, `instance-secret`) in den
  Schlüsselbund — liegt als Idee mit den offenen Punkten in
  [Xveyn/Zeiterfassung#101](https://github.com/Xveyn/Zeiterfassung/issues/101).
- **Keine Zusammenführung der vier gehärteten Schreibpfade.** `smtp_store`
  kopiert die Mechanik von `webhook_store` (ACL-Härtung + Rename-Retry), wie
  `json_store` es für Secret-Writer ausdrücklich vorsieht. Dass es damit vier
  Kopien sind, ist ein bekannter Preis; ein gemeinsames
  `atomic_write_hardened_json` in `secure_file.py` wäre der richtige Ort,
  gehört aber nicht in dieses Feature.

## Was das Review korrigiert hat

Drei parallele Reviews (Status-Quo-Treue gegen den echten Code,
CLAUDE.md-Regelkonformität, technische Kritik) haben Revision 1 an folgenden
Stellen widerlegt. Festgehalten, damit die Begründungen nicht verloren gehen:

| Behauptung in Revision 1 | Befund |
|---|---|
| „In `send_email` stecken … die drei UTF-8-Pflichten" | Nur zwei. Das `<meta charset>` sitzt in `report.py`/`share_dialog.py` — und wäre als „liegt jetzt alles in `mime_message`" in die Regeldatei gewandert |
| SMTP gilt in beiden Sendepfaden | Der Teilen-Dialog bricht **vor** dem Aufbau ab, wenn `credentials.json` fehlt — der zweite Pfad wäre für die Zielgruppe unerreichbar gewesen |
| Eigener Klassifikator verhindert Traceback-Dialoge | Nur im Sende-Dialog. Der Teilen-Dialog hätte für jeden SMTP-Fehler einen nativen Dialog mit der Zeile „None" gezeigt |
| „TLS … ohne Schalter zum Abschalten" | Der `else`-Zweig in `_open` war genau so ein Schalter: jeder unbekannte `security`-Wert verband unverschlüsselt, und `_is_wellformed` prüfte Werte nicht |
| `keyring` gehört in `requirements-test.txt` | Kein Test benutzt die echte Lib, und `SecretStorage` zieht `cryptography` (Rust) in die CI |
| `--collect-all keyring` sei Pflicht, keyring bringe einen Hook mit | Der Hook gehört PyInstaller, nicht keyring; das zitierte Issue ist als Duplikat geschlossen. Die Zeile ist redundant |
| Python-Boden ≥3.9 | Die ungepinnten Transitiven fordern bereits `>=3.10` — exakt unser Release-Python, ohne Puffer |
| Worker statt UI-Thread genügt gegen hängende Schlüsselbunde | Nein: ein hängender Worker ruft `on_done` nie, der Dialog steht dauerhaft auf „Sende…". Der Watchdog ist Pflicht |

## Quellen

- [keyring auf PyPI](https://pypi.org/project/keyring/) — Version 25.7.0,
  `requires_python >=3.9`, plattformabhängige Transitive
- [jaraco/keyring#512](https://github.com/jaraco/keyring/issues/512) —
  Keychain-Prompt nach jedem Build unter PyInstaller (ad-hoc-Signatur)
- [jaraco/keyring#619](https://github.com/jaraco/keyring/issues/619) —
  `set_generic_password` macht delete+add statt update
- [pypa/pip#7883](https://github.com/pypa/pip/issues/7883),
  [python-poetry/poetry#8623](https://github.com/python-poetry/poetry/issues/8623)
  — blockierendes `collection.unlock()` ohne Timeout
- [Apple TN3127](https://developer.apple.com/documentation/technotes/tn3127-inside-code-signing-requirements)
  — Designated Requirement bei ad-hoc signiertem Code
- [Microsoft Q&A: SMTP AUTH für neue Outlook.com-Konten](https://learn.microsoft.com/en-us/answers/questions/5790786/newly-registered-personal-outlook-email-accounts-c)
- [Modern-Auth-Enforcement 2026](https://www.getmailbird.com/microsoft-modern-authentication-enforcement-email-guide/)
- [Gmail SMTP mit App-Passwort](https://smtpedia.com/gmail-email-settings-pop3-imap-smtp/)
