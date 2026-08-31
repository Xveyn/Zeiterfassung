# SMTP-Support — Design

**Datum:** 2026-08-31
**Status:** Design abgestimmt, Implementierungsplan ausstehend
**Branch:** `worktree-feat+smtp-support`

## Problem

Berichte verlassen die App heute ausschließlich über die Gmail-API. Wer sie
per Mail verschicken will, braucht ein eigenes Google-Cloud-Projekt mit
aktivierter Gmail-API, einen OAuth-Zustimmungsbildschirm und eine
`credentials.json` — beschrieben im README-Abschnitt „Gmail API einrichten".
Das ist für ein kleines Desktop-Tool eine hohe Einstiegshürde, und für alle,
die gar kein Google-Konto benutzen wollen, eine geschlossene Tür: der
Sende-Dialog bricht ohne `credentials.json` mit einem Hinweis auf das
Cloud-Setup ab.

Ein klassischer SMTP-Zugang (Server, Port, Benutzer, Passwort) ist der Weg,
den jeder Mail-Anbieter und jeder Firmen-Mailserver anbietet und den jeder
Mail-Client seit dreißig Jahren spricht.

## Ziel

SMTP wird ein **vollwertiger, gleichrangiger Mailweg neben der Gmail-API** —
in beiden Sendepfaden (Bericht senden und Teilen). Die App verlangt künftig,
dass **einer von beiden** Wegen eingerichtet ist, nicht mehr zwingend die
Gmail-API.

Struktur: **n SMTP-Konten**, jedes mit eigenem Empfänger, jedes im
Sende-Dialog einzeln ankreuzbar — exakt das Muster der Webhooks.

## Status Quo

- `src/mail.py` — `get_gmail_service()` (OAuth-Flow, `credentials.json` +
  `token.json`, Scope-Upgrade-Erkennung) und `send_email(service, to, subject,
  html, attachment…)`. In `send_email` stecken der MIME-Bau, die drei
  UTF-8-Pflichten und die Steuerzeichen-Abwehr gegen Header-Injection
  (Audit N11) — **verwoben mit** dem Gmail-Versand. Dazu Scope-Verwaltung und
  `is_offline_error`.
- Zwei Aufrufer senden tatsächlich: `dialogs/send_task.py::_send_mail`
  (Bericht) und `dialogs/share_task.py::perform_share` (Teilen). Beide holen
  sich selbst einen Gmail-Service — der Transport ist hart verdrahtet.
- `send_task.perform_send` ist seit Audit M10 bereits ein **Dispatcher** über
  Kanäle (Mail + n Webhooks), sammelt je Kanal ein Result-Dict und wirft nie.
- `webhook_store.py` ist das Vorbild für einen gerätelokalen Store mit
  Secrets: gehärtet geschrieben, reist nicht per Drive-Sync.
- Gating im Sende-Dialog: `mail_possible = recipient and
  os.path.exists(credentials.json)`; ohne Ziel bricht der Dialog ab.
- SMTP kommt im Repo bisher nirgends vor.

## Architektur-Entscheidung: gemeinsamer MIME-Bau, getrennte Transporte

Verworfen wurden zwei Alternativen:

- **SMTP baut seine Nachricht selbst** (`mail.py` bleibt unberührt): Die drei
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
Begründung wie bei den Webhooks: kein Secret im Sync-Doc.

Record:

```
{id, name, enabled, host, port,
 security: "starttls" | "ssl" | "none",
 username, from_addr, recipient,
 password_location: "keyring" | "file",
 password?}          # nur bei password_location == "file"
```

Die `id` trägt die Zuordnung, nicht der Name — der ist umbenennbar
(Webhook-Muster).

`validate_record` prüft:

- `name` nicht leer und im Store eindeutig
- `host` nicht leer
- `port` ganzzahlig, 1–65535
- `security` einer der drei erlaubten Werte
- `from_addr` und `recipient` nicht leer und ohne Steuerzeichen
- `username` **darf leer sein** (interner Relay ohne Auth)

Das Passwort prüft `validate_record` **nicht** — es steht bei aktivem
Schlüsselbund gar nicht im Record. Die Regel „bei gesetztem Benutzer ist ein
Passwort Pflicht" gehört deshalb in den Dialog, der das Eingabefeld besitzt,
und gilt dort nur beim **Neuanlegen**; beim Bearbeiten heißt ein leeres Feld
„unverändert" (s. UI).

Die Steuerzeichen-Prüfung von `from_addr`/`recipient` ist eine
Vorab-Validierung fürs UI; die verbindliche Abwehr sitzt im MIME-Bau (s.u.)
und gilt damit für beide Transporte.

### `src/keyring_store.py` (neu)

Kapselt den OS-Schlüsselbund (Windows Credential Manager / macOS Keychain /
Linux Secret Service) hinter drei Funktionen:

```
set_secret(record_id, password) -> "keyring" | "file"
get_secret(record) -> str
delete_secret(record_id) -> None
```

`import keyring` erfolgt **lazy innerhalb der Funktionen** — Pflicht, weil
die Importkette `src.ui → … → smtp_store` sonst die Lib in die CI zieht, die
bewusst nur `requirements-test.txt` installiert (gleiches Muster wie die
Google-Wrapper in `drive.py`/`gcal.py`).

Service-Name `Zeiterfassung`, Account ist die Record-`id`.

`set_secret` liefert zurück, wo das Secret gelandet ist; genau dieser Wert
steht als `password_location` im Record. Ist kein Backend verfügbar
(`keyring.errors.NoKeyringError`, oder `keyring.backends.fail.Keyring` als
aktives Backend), fällt es auf `"file"` zurück: das Passwort steht dann als
`password` im Record in der ohnehin gehärteten `smtp.json`. Der
Bearbeiten-Dialog zeigt den Zustand als eigene Zeile, nicht als Fußnote:

> „Passwort liegt im Windows-Schlüsselbund."
> „Kein Schlüsselbund verfügbar — das Passwort wird lokal in `smtp.json` gespeichert."

Zwei Regeln, die sonst später weh tun:

- **Löschen eines Kontos löscht auch sein Keyring-Secret** — sonst bleibt es
  dauerhaft verwaist.
- **Der Schlüsselbund wird nie im UI-Thread gelesen.** Auf Linux ist das ein
  D-Bus-Roundtrip, der hängen kann. Gelesen wird im Worker, unmittelbar vor
  dem Versand bzw. dem Verbindungstest.

## Versandpfad

### `src/mime_message.py` (neu, rein, stdlib-only)

```
build_message(*, to, subject, html,
              attachment_bytes=None, attachment_filename=None,
              attachment_subtype="pdf", from_addr=None)
```

Enthält den kompletten MIME-Bau: `MIMEText(html, "html", _charset="utf-8")`,
`Header(subject, "utf-8")`, optionaler `MIMEApplication`-Anhang mit
`Content-Disposition`, und die Steuerzeichen-Abwehr (`\r`, `\n`, `\x00`) —
die jetzt **auch `from_addr`** prüft: beim SMTP-Versand ist der Absender ein
zweites nutzergefülltes Headerfeld mit demselben Injection-Risiko. `from_addr`
wird nur gesetzt, wenn übergeben (Gmail braucht es nicht, dort ist der
authentifizierte Nutzer der Absender).

`mail.send_email` behält Signatur samt Legacy-Aliasen (`pdf_bytes`/
`pdf_filename`) und schrumpft auf `build_message(...)` → base64url →
API-Call. Kein Aufrufer ändert sich; `tests/test_mail.py` bleibt unverändert
grün und ist damit die Absicherung, dass der Umbau am Bestand nichts
verschiebt.

### `src/smtp.py` (neu, Tk-frei, stdlib-only)

```
send(record, password, *, subject, html,
     attachment_bytes=None, attachment_filename=None,
     attachment_subtype="pdf") -> None
test_connection(record, password) -> None
classify_smtp_error(exc) -> dict
```

- Verbindungsaufbau nach `security`: `SMTP_SSL` (implizites TLS, typisch
  465), `SMTP` + `starttls()` (typisch 587), oder blank.
- **TLS über `ssl.create_default_context()` mit voller Zertifikatsprüfung,
  ohne Schalter zum Abschalten.** Eine solche Option wird erfahrungsgemäß
  angeklickt, um ein Problem loszuwerden, und bleibt dann für immer an.
- Fester Timeout (20 s) — sonst hängt der Worker unbegrenzt an einem stummen
  Server.
- `login()` nur bei gesetztem Benutzer.
- `test_connection` verbindet, loggt ein und schickt `noop()` — **keine
  Mail**. Hängt am „Verbindung testen"-Button.

`classify_smtp_error` ist ein **eigener** Klassifikator, Vorbild `webhook.py`
und nicht `mail_task.classify_mail_error`: dessen drei Kinds
(`filenotfound`/`offline`/`error`) würden alles Interessante zu
„unerwarteter Fehler mit Traceback" verschmelzen. Kinds:

| Kind | Auslöser |
|------|----------|
| `auth` | `SMTPAuthenticationError` |
| `recipient` | `SMTPRecipientsRefused`, `SMTPSenderRefused` |
| `tls` | `ssl.SSLError`, `SMTPNotSupportedError` (STARTTLS nicht angeboten) |
| `offline` | über das vorhandene `mail.is_offline_error` |
| `server` | `SMTPServerDisconnected`, `SMTPResponseException` |
| `error` | alles Übrige, mit Traceback |

`_KIND_TEXTS` in `send_task.py` wächst um `recipient` und `tls`.

### Dispatcher (`src/dialogs/send_task.py`)

`perform_send` bekommt den Parameter `smtp_accounts` — die im Sende-Dialog
angehakten Records.

- `needs_pdf` zählt sie mit: SMTP hängt die PDF an wie der Mail-Kanal. Das
  PDF entsteht weiterhin genau einmal und nur, wenn ein Kanal es braucht.
- Scheitert die PDF-Erzeugung, fallen Mail **und** SMTP-Konten mit demselben
  Failure-Result aus; die JSON-Webhooks laufen weiter (bestehende Logik,
  erweitert).
- Jedes Konto liefert `{"channel": "smtp", "name": <Kontoname>, …}`.
- Ein Fehler in einem Konto bricht die übrigen Kanäle nicht ab; der Vertrag
  „wirft nie" gilt unverändert für den ganzen Dispatcher.
- Das Passwort holt der **Worker** über `keyring_store.get_secret(record)`,
  direkt vor dem Verbinden.

### Teilen (`src/dialogs/share_task.py`)

`perform_share` bekommt statt der festen Gmail-Annahme einen
`transport`-Parameter: `None` heißt Gmail wie bisher, sonst ein SMTP-Record.
Der Teilen-Dialog bekommt dafür eine Auswahlzeile „Versand über: Gmail |
⟨Kontoname⟩". Der Share-Doc-Bau selbst bleibt unangetastet.

### Unverändert

`settings["sender_email"]` bleibt der Gmail-Absender (er speist u.a. das
`sender`-Feld im Webhook-JSON-Payload) und wird von einem SMTP-Konto **nicht**
überschrieben — das ist eine Google-Identität, keine allgemeine
Absenderangabe.

## UI

### Neuer Tab „SMTP"

Im Settings-Dialog hinter „Webhooks": Liste mit Hinzufügen / Bearbeiten /
Entfernen, gebaut wie `tab_webhooks.py` (`src/dialogs/settings_dialog/
tab_smtp.py`). Dazu `src/dialogs/smtp_dialog.py` als Geschwister von
`webhook_dialog.py` — über `theme.create_dialog`, themed Messageboxes,
„Speichern" und „Verbindung testen" beide über den `BackgroundTaskRunner`,
keine dialogspezifischen Stil-Extras (Theme bleibt einheitlich).

„Verbindung testen" arbeitet auf den **aktuellen Feldwerten**, nicht auf dem
gespeicherten Record — sonst könnte man eine Korrektur nicht prüfen, ohne sie
vorher zu speichern. Das Passwort nimmt es aus dem Feld; ist das leer und
existiert der Record bereits, liest es der Worker über
`keyring_store.get_secret`.

Zwei Hinweise stehen dort als Text, nicht als Fußnote:

- **Microsoft-Konten funktionieren nicht.** Outlook.com und Microsoft 365
  haben SMTP mit Basic Auth 2026 abgeschaltet (Ablehnung ab März 2026,
  endgültig 30.04.2026) — **auch App-Passwörter** greifen dort nicht mehr,
  SMTP geht nur noch über OAuth2. Ohne diesen Hinweis liest sich das
  resultierende `535 Authentication unsuccessful` wie ein Tippfehler.
- **Gmail braucht ein App-Passwort** (16-stellig, setzt aktive 2FA voraus) —
  nicht das Kontopasswort.

Beim Bearbeiten bleibt das Passwortfeld **leer**, und „leer = unverändert".
Ein gespeichertes Secret wird nie zurück in ein Widget geholt. Beim
**Neuanlegen** dagegen ist ein Passwort Pflicht, sobald ein Benutzer gesetzt
ist — diese Prüfung sitzt hier im Dialog, nicht in `validate_record` (s.
Datenmodell).

### Sende-Dialog

Die Zielliste bekommt die aktivierten SMTP-Konten als eigene
Checkbox-Zeilen zwischen Mail und Webhooks.

Das Gating kippt von „`credentials.json` muss da sein" auf **„mindestens ein
Ziel"**:

```
mail_possible = bool(recipient) and os.path.exists(credentials.json)
smtp_possible = bool(smtp_store.enabled())
```

Abgebrochen wird nur, wenn Mail, SMTP und Webhooks alle leer sind. Der
Erklärtext dort muss beide Mailwege nennen — sonst schickt er jemanden ins
Google-Cloud-Setup, der es gar nicht braucht.

### Verdrahtung

Analog `webhook_store`: `SmtpStore` in `main.py` neben `WebhookStore`
anlegen, über `App` an Sende-, Einstellungs- **und Teilen-Dialog**
durchreichen. Letzterer bekommt heute keinen Store — das ist der einzige neue
Durchreichepfad.

## Tests

Alles Neue außer der Tk-Schicht ist pure Logik und wird getestet; die
UI-Schicht bleibt untestet (entschiedene Scope-Grenze M16, siehe
`docs/known-limitations.md`). Der Zuschnitt hält diese Grenze ein: die
Versandlogik lebt in `smtp.py`, nicht im Widget.

- `tests/test_mime_message.py` — UTF-8-Pflichten, Injection-Abwehr in `to`
  **und** `from_addr`, Anhang-Subtype, `from_addr` wird nur gesetzt, wenn
  übergeben
- `tests/test_smtp.py` — Verbindungsaufbau je `security` und die
  Fehlerklassifikation, gegen einen `smtplib`-Stub
- `tests/test_smtp_store.py` — Validierung, Quarantäne, Read-Only,
  gehärteter Schreibpfad
- `tests/test_keyring_store.py` — Keyring-Pfad, Fallback-Pfad, Löschen räumt
  das Secret ab
- `tests/test_send_task_dispatch.py` — erweitert um den dritten Kanaltyp
  (unabhängiges Feuern, PDF-Fehler zieht SMTP mit, JSON-Webhooks laufen
  weiter)
- `tests/test_mail.py` — bleibt unverändert; grün heißt, der Umbau von
  `send_email` hat nichts verschoben

Alle neuen Tk-freien Module werden **vollständig** annotiert (Rückgabetyp und
alle Parameter) und in die Whitelist in `tests/test_type_annotations.py`
eingetragen.

## Abhängigkeiten & Build

- `keyring==25.7.0` gepinnt in `requirements.txt` (verlangt Python ≥3.9,
  unser CI-/Release-Python 3.10 also grün) und in der README-Tabelle der
  Abhängigkeiten ergänzt. Transitive: `pywin32-ctypes` (Windows),
  `SecretStorage` + `jeepney` (Linux), `jaraco.classes/functools/context` —
  bewusst nicht gepinnt, wie alle transitiven Deps.
- Ebenfalls gepinnt in `requirements-test.txt`, damit `keyring_store` echt
  und nicht nur gegen einen Mock getestet wird (reines Python auf Ubuntu-CI).
- `scripts/build.py`: `--collect-all keyring` auf allen drei Plattformen. Der
  mitgelieferte PyInstaller-Hook hat historisch Backends im Frozen-Build
  verloren („No recommended backend was available", jaraco/keyring#399).

**Verifikation vor dem Release:** Das ist genau der Fall, für den CLAUDE.md
den Pre-Release vorschreibt — eine neue Dependency mit plattformabhängigen
Backends, auf der Windows-Dev-Maschine nicht für macOS und Linux prüfbar.
Also **Pre-Release über alle drei Plattformen**, bevor das in ein echtes
Release geht. Zu prüfen ist dort je Plattform: Konto anlegen, Passwort
speichern (landet es im Schlüsselbund oder im Datei-Fallback?),
Verbindungstest, echter Versand.

## Dokumentation

- README: neuer Abschnitt „E-Mail-Versand ohne Google (SMTP)" mit
  `*(ab X.Y.Z)*`-Marker; der bestehende Gmail-Abschnitt bekommt einen
  Querverweis, dass er nicht mehr der einzige Weg ist.
- `docs/known-limitations.md`: zwei Einträge —
  1. **Microsoft-Konten** lassen sich nicht per SMTP anbinden (OAuth2-only).
  2. **SMTP-Konten sind gerätelokal**: wie Webhooks und Urlaub reisen sie
     nicht per Drive-Sync und müssen auf jedem Gerät neu eingerichtet werden.

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

## Quellen

- [keyring auf PyPI](https://pypi.org/project/keyring/) — Version 25.7.0,
  `requires_python >=3.9`, plattformabhängige Transitive
- [jaraco/keyring#399](https://github.com/jaraco/keyring/issues/399) —
  Backend-Autodetect unter PyInstaller
- [Microsoft Q&A: SMTP AUTH für neue Outlook.com-Konten](https://learn.microsoft.com/en-us/answers/questions/5790786/newly-registered-personal-outlook-email-accounts-c)
- [Modern-Auth-Enforcement 2026](https://www.getmailbird.com/microsoft-modern-authentication-enforcement-email-guide/)
- [Gmail SMTP mit App-Passwort](https://smtpedia.com/gmail-email-settings-pop3-imap-smtp/)
