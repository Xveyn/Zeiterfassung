# OAuth-Token und Webhook-Secrets in den OS-Schlüsselbund — Design

**Datum:** 2026-09-18
**Status:** Design abgestimmt; Recherche R1–R6 und Plan-Review (2026-09-18) eingearbeitet, s. „Nachträge aus dem Plan-Review"
**Branch:** `feat/secrets-keyring`
**Issue:** Xveyn/Zeiterfassung#101 (Kontext-Check und Umfangsentscheidung im Issue-Kommentar vom 2026-09-18)

## Problem

Seit dem SMTP-Feature liegt ein erstes Secret im OS-Schlüsselbund (Windows
Credential Manager / macOS Keychain / Linux Secret Service). Die übrigen
Secrets stehen weiter als Klartext-JSON im Datenverzeichnis. Sie sind zwar
gehärtet geschrieben (`secure_file`: chmod 0600 + icacls-ACL), aber für jeden
lesbar, der an die Datei kommt: über Backups, Cloud-Ordner oder ein
Support-Zip mit dem Datenverzeichnis.

Die beiden wertvollsten sind:

- `token.json` mit dem **OAuth-Refresh-Token**, dem dauerhaften Zugang zu
  Gmail, Drive und Kalender;
- `webhooks.json` mit **Auth-Header-Werten und HMAC-Secrets**.

## Ziel

1. Der Refresh-Token und die Webhook-Secrets liegen im Schlüsselbund, sobald
   einer verfügbar ist. In den Dateien bleibt nur eine Referenz.
2. **Bestehende Installationen ziehen automatisch um.** Das passiert im
   Hintergrund beim Start, idempotent und ohne Risiko für den Zugang. Der
   Klartext verschwindet erst nach geprüftem Umzug. Danach erscheint einmal
   ein Hinweis.
3. Ohne Schlüsselbund, etwa auf Linux ohne Secret Service, bleibt alles wie
   heute.

## Umfang

| Secret | Stufe 1 | Begründung |
|---|---|---|
| Refresh-Token aus `token.json` | ✅ | höchster Wert |
| `auth.value` / `auth.secret` aus `webhooks.json` | ✅ | das SMTP-Muster passt 1:1 |
| `credentials.json` (OAuth-Client) | später ggf. | Das Client-Secret von Desktop-Clients gilt bei Google nicht als vertraulich und steht ohnehin auch in `token.json`. Der Umbau berührt Setup-Anleitung, Google-Tab-Status und drei Flows. |
| `instance-secret` | ❌ | Es wird in `single_instance.acquire()` **vor** dem Tk-Aufbau synchron gelesen. Ein hängender Linux-Schlüsselbund blockierte den Start bis zu 30 s (Watchdog). Der Nutzen ist gering (Localhost-Guard). |

`client_secret`, `client_id`, die Scopes und der Access-Token bleiben
bewusst in `token.json` (s. „Warum nur der Refresh-Token").

## Nachträge aus dem Plan-Review (2026-09-18)

Das kritische Review des Implementierungsplans hat den Plan in einer
Repo-Kopie durchgespielt, auch gegen den echten Windows-Schlüsselbund. Es
hat Punkte gefunden, die das Design ändern. Sie **gehen den Abschnitten
unten vor**.

1. **Speichern behält den Ort bei (B1).**
   - `save_credentials` schreibt eine bestehende `token.json` im Datei-Modus
     wieder als Datei, so wie heute. Den Schlüsselbund nutzt es nur, wenn
     der Token schon dort liegt oder es noch **keine** Datei gibt (frische
     Anmeldung).
   - **Umziehen darf ausschließlich `secret_migration`.** Sonst hätte der
     Start-Refresh (Access-Token nach Pause praktisch immer abgelaufen)
     den Token still und ohne Zurücklesen umgezogen, und der Hinweis wäre
     ausgeblieben.
2. **Der Schlüssel steht in der Datei, nicht im Pfad-Hash (W3).**
   `token.json` trägt `refresh_token_key` (`"google-oauth:" + uuid4`),
   einmal erzeugt und beim Speichern wiederverwendet, analog
   `webhook:<id>`.
   - Ein verschobener Datenordner (Junction, 8.3-Name, Backup) behält so
     seinen Token.
   - Zwei Datenverzeichnisse (Dev-Instanz) haben trotzdem getrennte
     Einträge.
   - Wer den Ordner auf einen **anderen Rechner** kopiert, muss Google
     neu verbinden und die Webhook-Secrets neu eingeben (dokumentiert).
3. **Eigener Service-Name pro Eintrag (W2).**
   - Die neuen Einträge liegen unter Service `"Zeiterfassung:" + schlüssel`
     (Nutzername = Schlüssel), nicht gemeinsam unter `"Zeiterfassung"`.
   - `WinVaultKeyring` schichtet mehrere Nutzernamen unter einem Service
     per ungeschütztem Lesen–Ändern–Schreiben um (`<user>@<service>`). Das
     ist nicht thread-sicher, und die SMTP-Passwörter wären mitbetroffen.
   - Mit einem Service pro Eintrag sind die Zielnamen deterministisch. Die
     SMTP-Einträge bleiben unverändert unter `"Zeiterfassung"`.
4. **Nur bei Änderung schreiben (W1).**
   - `keyring_store.put` merkt sich pro Prozess den zuletzt geschriebenen
     bzw. gelesenen Wert je Schlüssel und schreibt nur bei Änderung.
   - Sonst schriebe jeder stündliche Refresh neu. Unter macOS
     (`SecItemDelete`+`SecItemAdd`) ist das nicht atomar und womöglich
     prompt-auslösend; unter Linux kostet es bei hängendem Secret Service
     30 s pro Refresh.
5. **Ein Lock um Speichern und Umzug (W6).**
   - Beim Start erneuern mehrere Tasks gleichzeitig: Start-Refresh,
     Absender-Abruf, Sync-Pull, Kalender-Abgleich.
   - `token_store.TOKEN_LOCK` (RLock) umschließt `save_credentials` und
     den Token-Umzug, also Schreiben, Prüfen und Datei-Schreiben.
6. **Deinstallation räumt den Schlüsselbund ab (B2), entschieden.**
   - Die Exe kennt einen Modus `--forget-secrets`: Er liest `token.json`,
     `webhooks.json` und `smtp.json`, entfernt die zugehörigen Einträge
     und beendet sich ohne Tk, ohne Single-Instance-Guard und ohne
     Autostart-Migration.
   - `installer.iss` ruft ihn in `usUninstall` vor dem Löschen der
     Dateien. Die Zusage des Uninstallers („Google-Anmeldung wurde von
     diesem Rechner entfernt") bleibt damit wahr.
   - Nebenbefund: `smtp.json` fehlt bisher in `[UninstallDelete]`, obwohl
     die Datei im Datei-Fallback ein Passwort im Klartext trägt. Das wird
     mit korrigiert.
   - macOS/Linux haben keinen Uninstaller; dort wird dokumentiert, wie
     man die Einträge entfernt.
7. **„Eintrag fehlt" ist eine eigene Fehlerart (Review K2).** Bei
   Webhooks heißt sie `keyring_missing` („Zugangsdaten fehlen im
   Schlüsselbund"), nicht `keyring` („nicht erreichbar").
8. **Aufräumen erst nach dem Schreiben (Review K3).** `webhook_secrets.persist`
   liefert einen abzuräumenden Schlüssel zurück. Der Dialog entfernt ihn
   erst **nach** `store.save`, gleiche Regel wie `remove_record`.
9. **Randnotiz zu R3:** In google-auth 2.55 gilt ein fehlendes `expiry`
   als abgelaufen. Die Begründung „ohne Access-Token `expired=False`"
   trifft also nicht mehr allgemein zu. Die Entscheidung, den Access-Token
   in der Datei zu lassen, bleibt trotzdem richtig (Größenlimit, eine
   Stunde Gültigkeit).

## Architektur

### Warum nur der Refresh-Token

- **Windows-Größenlimit (R1, bestätigt).** `keyring`s `WinVaultKeyring`
  schreibt per `win32cred.CredWrite` und teilt dabei nicht auf. Der Blob ist
  UTF-16 kodiert und darf höchstens 2560 Byte groß sein, also höchstens
  **1280 Zeichen**. Wird das überschritten, antwortet `CredWrite` mit
  Fehler 1783 („The stub received bad data").
  - Ein reales `token.json` hat ~970 Zeichen.
  - Google nennt als Obergrenze **2048 Byte für Access-Tokens** und
    **512 Byte für Refresh-Tokens**.
  - Das ganze Token-JSON kann das Limit also reißen. Ein Refresh-Token
    belegt im schlechtesten Fall ~40 % davon.
- **Der Access-Token muss in der Datei bleiben.** Fehlt er, liefert
  google-auth `creds.valid = False`, aber auch `creds.expired = False`,
  solange `expiry` fehlt oder in der Zukunft liegt.
  - Alle Ladepfade (`mail`, `drive`, `gcal`) erneuern nur bei
    `creds.expired and creds.refresh_token`. Sonst gehen sie in den
    Consent-Flow bzw. in den Reauth-Fehler.
  - Ohne Access-Token müsste sich der Nutzer also neu anmelden, obwohl der
    Refresh-Token da ist.
  - Der Access-Token ist nur eine Stunde gültig. Der dauerhafte Zugang ist
    allein der Refresh-Token.
- **Die Datei bleibt erhalten** und behält alles außer dem Refresh-Token.
  Damit funktioniert der größte Teil der rund zehn Datei-Zugriffe
  unverändert:
  - `os.path.exists(token_path)` als Vorbedingung für „verbunden"
    (`background_tasks`, `scopes_dialog`, alle Service-Builder);
  - `oauth_utils.read_granted_scopes` / `token_lacks_scopes` (Scopes);
  - der mtime/size-Poll in `tab_google._refresh_scopes_status`;
  - die Diagnose in `mail.fetch_user_email`, die nur die Scopes liest.

### Neues Modul `src/token_store.py` (Tk-frei, vollständig annotiert)

Einzige Stelle, die OAuth-Credentials lädt und speichert.

```python
def load_credentials(token_path: str, scopes: list[str]) -> Credentials
def save_credentials(creds: Credentials, token_path: str) -> None
def forget_token(token_path: str) -> None
def keyring_key(token_path: str) -> str
class TokenKeyringUnavailable(Exception)
```

- **`load_credentials`** liest `token.json`.
  - Bei `refresh_token_location == "keyring"` holt es den Refresh-Token über
    `keyring_store` und setzt ihn in das Info-Dict. Danach folgt
    `Credentials.from_authorized_user_info(info, scopes)`.
  - Ohne das Feld (Alt-Format) oder bei `"file"` verhält es sich exakt wie
    heute `from_authorized_user_file`.
  - google-auth verlangt `refresh_token`, `client_id` und `client_secret`
    und wirft sonst `ValueError` („Authorized user info was not in the
    expected format, missing fields …"). Das gilt unverändert seit
    Einführung der Methode (R3). Liefert der Schlüsselbund `""` (Eintrag
    fehlt), prüft `load_credentials` das **vorher** und meldet den
    Reauth-Fall. Es lässt den `ValueError` nicht als unerwarteten Fehler
    durchlaufen.
  - Es ersetzt die fünf Aufrufe von `Credentials.from_authorized_user_file`
    in `mail.py` (3×: `fetch_user_email`, `refresh_token_if_needed`,
    `get_gmail_service`), `drive.py` und `gcal.py`.
- **`save_credentials`** ersetzt `oauth_utils.write_token` an allen Aufrufern
  (`mail`, `drive`, `gcal`).
  - Zuerst wird der Refresh-Token in den Schlüsselbund geschrieben.
  - Klappt das, geht die Datei **ohne** `refresh_token` und mit
    `refresh_token_location: "keyring"` raus. Dafür wird
    `creds.to_json(strip=["refresh_token"])` genutzt, nicht ein von Hand
    bearbeitetes Dict. Klappt es nicht, wird das vollständige JSON wie heute
    mit `"file"` geschrieben.
  - Der Datei-Schreibweg selbst bleibt `write_token`: atomar, gehärtet, mit
    Retry. Er bekommt dafür einen Parameter für das zu schreibende JSON,
    statt `creds.to_json()` selbst zu rufen.
- **`forget_token`** löscht `token.json` **und** den Schlüsselbund-Eintrag.
  Es ersetzt die `os.remove(token_path)` in `drive.reconnect` und
  `oauth_utils.discard_token_for_scope_upgrade`. Sonst blieben verwaiste
  Einträge im Schlüsselbund stehen.
- **`keyring_key`** liefert `"google-oauth:" + sha256(abspath(dirname(token_path)))[:12]`.
  - Der Schlüsselbund gehört dem OS-Nutzer, nicht der Installation. Ohne
    diesen Schlüssel läse und überschriebe eine Dev-Instanz
    (`python -m src.main`, eigenes Datenverzeichnis) den Token der
    installierten App.
  - Dieselbe Idee steckt im Port-Hash von `single_instance`.

### Webhooks: das SMTP-Muster

- Ein Datensatz trägt `auth.secret_location` (`"keyring"` | `"file"`).
  - Fehlt das Feld (Alt-Format), gilt `"file"`: die Werte stehen wie heute in
    `auth.value` / `auth.secret`.
  - Bei `"keyring"` fehlen die Felder in der Datei. Der Eintrag heißt dann
    `"webhook:" + id`. Das Präfix trennt ihn von den SMTP-Konten, die unter
    ihrer ID liegen.
- **Senden**: `send_task` löst das Secret im Worker auf und hängt es vor
  `webhook.deliver` in eine Kopie von `auth`. Muster und Fehlerart kommen vom
  SMTP-Kanal: `None` wird zu `kind: "keyring"`, „Schlüsselbund nicht
  erreichbar", und es wird **nicht** ohne Auth gesendet. Dasselbe gilt für
  den Test-Versand im Webhook-Dialog.
- **Webhook-Dialog**: Wie der SMTP-Dialog füllt er das Secret-Feld bei einem
  gespeicherten Datensatz **nicht** vor. Das Feld zeigt stattdessen
  „liegt im Schlüsselbund, leer lassen = unverändert".
  - Das ist eine sichtbare Änderung für bestehende Nutzer. Heute stehen die
    Werte im Klartext im Feld.
  - Beim Speichern entscheidet eine gemeinsame Funktion nach dem Vorbild von
    `keyring_store.persist_password`, wo der Wert landet. Sie ist Tk-frei
    und getestet.
- **Löschen** räumt den Eintrag ab. Dafür bekommt `WEBHOOKS_KIND` aus R12
  einen `after_delete`-Hook, analog zu `tab_smtp._delete_secret`.

### `keyring_store`: Erweiterung statt zweiter Schicht

Die vorhandenen Funktionen sind auf SMTP-Datensätze zugeschnitten
(`get_secret(record)` liest `password_location`/`password`). Neu kommen
schlüsselbasierte Grundfunktionen dazu:
`put(key, value) -> bool`, `fetch(key) -> str | None`, `remove(key)`.
Alle laufen hinter demselben Watchdog. Die SMTP-Funktionen bauen darauf auf
und behalten ihr Verhalten; ihre Tests bleiben unverändert.

### Umzug beim Start: `src/secret_migration.py` (Tk-frei, vollständig annotiert)

```python
def find_plaintext_secrets(base_path: str, webhook_store) -> Pending
def migrate(pending: Pending, ...) -> MigrationReport
```

- **Wann:** in `App.__init__` als Hintergrund-Task über den
  `BackgroundTaskRunner`, nach den bestehenden Start-Tasks, **nie** vor dem
  Tk-Aufbau. Einen Versionsvergleich braucht es nicht. Die Prüfung bei jedem
  Start ist idempotent und greift beim ersten Start nach dem Update von
  selbst. Sie greift auch später, wenn ein Linux-System erst nachträglich
  einen Secret Service bekommt.
- **Nur wenn nötig:** Der Schlüsselbund wird erst gefragt, wenn
  `find_plaintext_secrets` etwas findet. So löst ein normaler Start auf macOS
  keinen Keychain-Dialog aus.
- **Pro Secret einzeln, in dieser Reihenfolge:**
  1. `put` in den Schlüsselbund;
  2. `fetch` und mit dem Klartext vergleichen;
  3. nur bei Übereinstimmung die Datei atomar neu schreiben, mit entferntem
     Feld und gesetzter `location`.

  Ein Fehlschlag in 1 oder 2 lässt die Datei unverändert. Ein Abbruch
  zwischen 2 und 3 hinterlässt ebenfalls die unveränderte Datei, der nächste
  Start holt den Umzug nach.
- **Token und Webhooks unabhängig:** Scheitert eines, zieht das andere
  trotzdem um. Der Bericht nennt, was umgezogen ist.
- **Nebenläufigkeit:** Der Token-Umzug schreibt `token.json`. Zeitgleich
  könnte ein Refresh laufen (`BackgroundTaskRunner.refresh_token` beim Start)
  und ebenfalls schreiben. Deshalb läuft der Umzug **nach** dem
  Start-Refresh. Dessen `on_done` feuert heute nur im Fehlerfall, der Refresh
  bekommt also einen zusätzlichen Abschluss-Callback, der immer gerufen wird.
  Außerdem liest er die
  Datei unmittelbar vor dem Schreiben erneut und zieht nur um, wenn der
  Refresh-Token darin noch derselbe ist, den er verglichen hat.
  - R2: Google rotiert bei Desktop-Clients nicht bei jedem Refresh.
    google-auth übernimmt aber jeden `refresh_token`, den der Endpunkt
    liefert (`_handle_refresh_grant_response`).
  - Rotation ist also selten, aber jederzeit möglich. Die Prüfung bleibt
    deshalb.

### Hinweis nach dem Umzug

- Er erscheint **nur**, wenn wirklich etwas umgezogen ist, und zwar einmal.
  Beim nächsten Start gibt es nichts mehr zu finden.
- **Sichtbares Fenster:** themed Info-Dialog, bekannt-themed nach N14.
  Text-Entwurf: „Deine Google-Anmeldung und die Zugangsdaten deiner Webhooks
  liegen jetzt im Schlüsselbund des Betriebssystems statt im Klartext im
  Datenordner."
- **Unter macOS** kommt ein Satz dazu, **nicht** als „einmalig" formuliert:
  „macOS kann nach App-Updates erneut fragen, ob Zeiterfassung auf den
  Schlüsselbund zugreifen darf."
  - Grund (R4): Die Keychain-ACL („Immer erlauben") hängt an der
    Designated Requirement der Signatur.
  - Die ad-hoc-Signatur ändert sich mit jedem Build, und damit greift die
    alte Freigabe nach einem Update nicht mehr.
  - Abhilfe wäre eine stabile Signatur (Developer ID). Die liegt außerhalb
    dieses Vorhabens (s. „Bewusst nicht dabei").
- **Autostart mit `--minimized` oder Fenster im Tray:** Tray-Toast statt
  Pop-up. Ohne Tray gibt es nur einen Log-Eintrag.

## Fehlerverhalten

| Situation | Verhalten |
|---|---|
| Kein Schlüsselbund (NoKeyringError, fehlende Lib, D-Bus-Fehler) | Umzug unterbleibt, Dateien unverändert, Log (info), kein Hinweis. Nächster Start probiert erneut. |
| Watchdog-Timeout beim Umzug | wie oben, Log (warning) |
| Zurückgelesener Wert ≠ Klartext | Datei unverändert, Log (warning, **ohne** Wert und ohne ID, s. `keyring_store.delete_secret`). Der hängende Eintrag wird beim nächsten Umzug überschrieben. |
| Laufzeit: `location == "keyring"`, `fetch` liefert `None` (Timeout, gesperrt) | Token: `TokenKeyringUnavailable` bzw. die bestehenden Auth-Fehler der Wrapper. Die Meldung heißt „Schlüsselbund nicht erreichbar". **Keine** Datei-Änderung, **kein** Consent-Flow (Regel aus #129). Webhook: `kind: "keyring"`, kein Versand. |
| Laufzeit: Eintrag fehlt wirklich (`fetch` liefert `""`, z.B. im Credential Manager gelöscht) | Token: wie ein widerrufener Token, also „Google-Verbindung erneuern", Datei bleibt. Webhook: `kind: "keyring"` mit eigenem Text („Zugangsdaten fehlen im Schlüsselbund — Webhook bearbeiten und neu eingeben"). |
| Refresh schreibt einen rotierten Token, Schlüsselbund fällt aus | `save_credentials` schreibt das vollständige JSON mit `"file"`. Der neue Token geht nie verloren, der nächste Start zieht ihn wieder um. |
| `forget_token`: Eintrag lässt sich nicht löschen | Datei wird trotzdem gelöscht, Log (debug). Ein verwaister Eintrag ist harmlos, der nächste `save_credentials` überschreibt ihn. |

Alle neuen Catch-alls folgen der Regel aus `test_catch_all_handlers.py`:
Sie loggen, melden oder tragen eine Begründung im Handler, und der `try`
bleibt eng.

## Kompatibilität

- **Upgrade (alt → neu):** Alt-Formate ohne `…_location` gelten als
  `"file"`. Die neue Version liest sie ohne jeden Umzug exakt wie heute. Der
  Umzug ist ein Zusatz, keine Voraussetzung.
- **Gemischte Zustände** sind gültig: Der Token liegt im Schlüsselbund, ein
  Webhook in der Datei (z.B. weil sein Umzug scheiterte), oder umgekehrt.
- **Downgrade (neu → alt), eine dokumentierte Einschränkung:**
  - Eine alte Version kennt `refresh_token_location` nicht. Ihr fehlt der
    Refresh-Token. google-auth wirft dann `ValueError` („missing fields
    refresh_token", R3). Die alte Version bricht also **laut** ab, nicht
    still, und zeigt beim Senden bzw. Sync den Fehler mit Traceback. Abhilfe
    ist einmal „Google neu verbinden", das `token.json` neu schreibt.
  - Webhooks mit Auth senden in der alten Version ohne Wert.
  - Der Auto-Updater downgradet nie, betroffen ist nur ein manueller
    Rückschritt. Das wird in `docs/known-limitations.md` und im CHANGELOG
    festgehalten.
- **Kein Sync-Bezug:** `token.json` und `webhooks.json` reisen nicht per
  Drive-Sync und stehen nicht im Share-Doc.
- **Mehrere Datenverzeichnisse** eines OS-Nutzers bekommen getrennte
  Einträge (`keyring_key`). Webhook-IDs sind UUIDs.

## Tests

Alle Tests laufen mit einem **Fake-`keyring`-Modul** in `sys.modules`, weil
die CI `keyring` bewusst nicht installiert. Der Fake kann zusätzlich
„nicht verfügbar", „Timeout", „liefert anderen Wert zurück" und
„Eintrag fehlt" simulieren.

- **Kompatibilität:**
  - Eine `token.json`, wie sie das heutige `write_token` mit echten
    google-auth-Credentials schreibt, lädt über `load_credentials` zu
    gleichen Credentials (Token, Refresh-Token, Scopes, Client).
  - Ein Webhook-Datensatz im heutigen Format ergibt dieselben Header wie
    heute.
  - Beides gilt ohne Schlüsselbund und vor dem Umzug.
- **`token_store`:**
  - Roundtrip über den Schlüsselbund: Die Datei enthält danach keinen
    `refresh_token`, der Access-Token bleibt drin.
  - Fällt der Schlüsselbund aus, wird die Datei vollständig geschrieben
    (`"file"`).
  - `fetch → None` führt zu `TokenKeyringUnavailable`, die Datei bleibt
    unverändert.
  - `fetch → ""` führt zum Reauth-Pfad.
  - `forget_token` räumt Datei und Eintrag ab.
  - `keyring_key` unterscheidet zwei Datenverzeichnisse.
- **Nicht-interaktive Pfade:** Ein `TokenKeyringUnavailable` startet in
  `drive`/`gcal` mit `interactive=False` **keinen** Flow. Das ist die
  Regressionsgrenze zu #129.
- **`secret_migration`:**
  - Token und Webhooks ziehen um, die Dateien verlieren ihre Felder.
  - Weicht der zurückgelesene Wert ab, gibt es einen Timeout oder keinen
    Schlüsselbund, bleibt alles unverändert.
  - Bei einem Teil-Fehlschlag zieht der Rest um, und der Bericht stimmt.
  - Ein zweiter Lauf tut nichts.
  - Ein simulierter Abbruch nach `put`, vor dem Datei-Schreiben, hinterlässt
    eine gültige Datei. Der nächste Lauf holt den Umzug nach.
  - Hat sich der Refresh-Token zwischen Vergleich und Schreiben geändert,
    wird nicht umgezogen.
  - Ohne Klartext-Funde wird der Schlüsselbund **nicht** angesprochen.
- **Webhooks:**
  - `send_task` löst das Secret im Worker auf; `None` führt zu
    `kind: "keyring"` ohne Versand.
  - Die Speicher-Entscheidung (leer = unverändert, neu, Wechsel des Modus)
    ist parametrisiert getestet.
  - Löschen räumt den Eintrag ab.
- **Charakterisierung zuerst:** Tests, die das heutige Lese- und
  Schreibverhalten von `token.json` und das Header-Verhalten der Webhooks
  festhalten, werden **vor** dem Umbau geschrieben und laufen danach
  unverändert (Muster aus R12).
- Die Whitelist in `test_type_annotations.py` bekommt `token_store` und
  `secret_migration`. `keyring_store` steht dort schon, die neuen Funktionen
  sind also ebenfalls vollständig zu annotieren.

## Verifikation vor dem Merge

- `pytest`, `ruff`, `pyright` grün.
- **Windows, echte App (Frozen-Build aus `build.yml`)**, mit einer Kopie
  eines realen Datenverzeichnisses:
  1. Start: Umzug, Hinweis, Eintrag im Credential Manager sichtbar,
     `token.json` ohne `refresh_token`.
  2. Senden, Drive-Sync, Kalender-Abgleich und Webhook-Versand
     funktionieren.
  3. Neustart: kein zweiter Hinweis.
- **Pre-Release auf allen drei Plattformen** vor dem nächsten echten
  Release, zusammen mit dem offenen Pre-Release aus #123/R9:
  - macOS: Nach dem Umzug erscheint der Keychain-Prompt einmal, danach ist
    es still. Nach einem Update erscheint er laut R4 voraussichtlich erneut;
    das wird bestätigen, der Hinweistext deckt es ab.
  - Linux: mit Secret Service (Umzug) und ohne (alles bleibt).
  - Backend-Erkennung im Frozen-Build: laut R5 unkritisch, weil der
    PyInstaller-Core-Hook `hook-keyring.py` Backends samt Metadaten bündelt.
    Trotzdem auf allen drei Plattformen beobachten.

## Dokumentation

- `CLAUDE.md`: Strukturliste (`token_store.py`, `secret_migration.py`), die
  Beschreibung von `keyring_store` und im Abschnitt „Installation & Daten"
  die Tabelle der Benutzerdaten (was liegt noch in den Dateien).
- `src/CLAUDE.md`: der Abschnitt `secure_file` (vier Secret-Schreibpfade;
  was davon jetzt im Schlüsselbund liegt) und „Google-Integration" (Token
  über `token_store`).
- `docs/known-limitations.md`: Downgrade-Einschränkung und
  Windows-Größenlimit (warum nur der Refresh-Token).
- CHANGELOG-Eintrag gehört in den Release-PR.

## Recherche-Ergebnisse (R1–R6)

Recherchiert am 2026-09-18 aus dem Quellcode von `keyring==25.7.0`,
`google-auth` 2.55.0 (der Test-Pin; in `requirements.txt` kommt google-auth
nur transitiv, `to_json(strip=…)` und die Pflichtfeld-Prüfung sind aber
langjährig stabil) und `pyinstaller==6.20.0`, dazu aus GitHub-Issues und der
Google- und Microsoft-Doku.

| # | Frage | Ergebnis | Folge fürs Design |
|---|---|---|---|
| R1 | Windows-Größenlimit | `CRED_MAX_CREDENTIAL_BLOB_SIZE` = 2560 Byte, UTF-16 kodiert (pywin32-ctypes `create_unicode_buffer`), also **1280 Zeichen**. Wird es überschritten, kommt Fehler 1783 (jaraco/keyring#355). Google: Access-Token ≤ 2048 Byte, Refresh-Token ≤ 512 Byte. | bestätigt „nur der Refresh-Token" |
| R2 | Rotation von Refresh-Tokens | Bei Desktop-Clients ist Rotation nicht die Regel. google-auth übernimmt aber jeden gelieferten neuen `refresh_token` (`google/oauth2/_client.py::_handle_refresh_grant_response`). | Nebenläufigkeits-Prüfung im Umzug bleibt |
| R3 | Fehlender `refresh_token` | `ValueError` „… missing fields …", Pflichtfelder `refresh_token`/`client_id`/`client_secret`, unverändert seit Einführung (google-auth-library-python#226). `to_json(strip=…)` existiert. | `load_credentials` prüft vorher und meldet Reauth; `save_credentials` nutzt `strip`. Beim Downgrade bricht die alte Version laut, nicht still. |
| R4 | macOS-Keychain-Prompt | Die ACL hängt an der Designated Requirement; eine ad-hoc-Signatur ändert sie mit jedem Build, also **Prompt nach jedem Update erneut**. | Hinweistext angepasst; Developer-ID-Signatur bleibt außerhalb |
| R5 | Backends im Frozen-Build | Der Hook liegt im **PyInstaller-Core** (`PyInstaller/hooks/hook-keyring.py`: `collect_submodules('keyring.backends')` + `copy_metadata('keyring')`, seit PR #5245), **nicht** in hooks-contrib. `scripts/build.py` bündelt zusätzlich `--collect-all keyring`. | kein Handlungsbedarf |
| R6 | Linux Secret Service | `keyring` ruft `collection.unlock()` **ohne Timeout** (`SecretService.py`; der `timeout`-Parameter von SecretStorage existiert erst ab 3.5 und bleibt ungenutzt). Fehlt der Daemon: Backend nicht viable → `NoKeyringError`. Ein abgelehnter Prompt ergibt `KeyringLocked`. AppImage ist keine Sandbox, der D-Bus-Zugriff verhält sich wie bei nativen Programmen. | Watchdog bestätigt; alle drei Fälle münden in „Umzug unterbleibt" |

Nebenbefund, **außerhalb dieses Vorhabens**: Steht der OAuth-Client der App
in der Google Cloud Console noch auf „Testing", laufen Refresh-Tokens nach
**7 Tagen** ab. Das gilt unabhängig davon, wo sie gespeichert sind. Außerdem
gelten 6 Monate Inaktivität und höchstens 100 gültige Tokens pro Nutzer und
Client.

## Bewusst nicht dabei (YAGNI)

- **`credentials.json`** und **`instance-secret`** (s. Umfang).
- **Access-Token im Schlüsselbund.** Größenlimit, eine Stunde Gültigkeit.
- **Verschlüsselte Datei mit Schlüssel im Schlüsselbund.** Das bräuchte eine
  neue Abhängigkeit (AES, `cryptography`), und das nur für diesen Zweck.
- **Stabile macOS-Signatur (Developer ID + Notarisierung)**, die den
  Keychain-Prompt nach Updates vermiede (R4). Das wäre eine Änderung am
  Build- und Kostenmodell, keine an diesem Feature.
- **Rückweg „aus dem Schlüsselbund zurück in die Datei"** als Nutzerfunktion.
  Der Fallback beim Schreiben deckt den technischen Fall ab, einen
  Bedienweg dafür gibt es nicht.
