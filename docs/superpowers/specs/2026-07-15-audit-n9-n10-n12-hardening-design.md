# Design: Audit-Härtung N9/N10/N12 (Sammel-PR)

> Stand 2026-07-15 · Follow-ups aus dem Audit-Tracking-Issue #131
> (Code-Audit 2026-07-04). Drei unabhängige NIEDRIG-Findings, gebündelt in
> einem Sammel-PR, da keins davon für sich einen eigenen PR rechtfertigt.

## Problem

- **N9** — `src/single_instance.py`s lokales SHOW/PING-Protokoll hat keine
  Authentifizierung: jeder Prozess, der den (deterministisch aus dem
  Base-Path abgeleiteten) 127.0.0.1-Port erreicht, kann `ZEIT-SHOW`/
  `ZEIT-PING` senden und wird bedient.

  **Ehrliches Bedrohungsmodell (bestimmt den Scope des Fixes):** Am
  Handshake hängt **nichts Destruktives** — `ZEIT-SHOW` holt nur das
  Fenster nach vorn (`_fire_show`), `ZEIT-PING` tut gar nichts. Das
  Finding ist also ein Cross-User-**Nuisance**-Vektor, kein Daten-/
  Integritätsrisiko. Ein Prozess **desselben Nutzers** kann die neue
  Secret-Datei ohnehin lesen (gleiche Rechte wie `token.json`) und den
  Fix trivial umgehen — er ist aber auch nie die Bedrohung (er kann
  ohnehin alle Nutzerdaten lesen). Geschlossen wird **ausschließlich**
  der Vektor „*anderer* lokaler Nutzer auf einer Mehrbenutzer-Maschine":
  der erreicht zwar den Loopback-Port (127.0.0.1 ist nicht
  nutzergetrennt), kann aber die `0600`-Secret-Datei nicht lesen. Auf
  **Windows** fehlt die explizite ACL (das wäre M8) → der Schutz hängt
  dort an der per-User-Isolation von `%LOCALAPPDATA%`. Der Fix ist damit
  bewusst schmal; er schließt das offene Finding, ohne mehr zu
  versprechen, als er hält.
- **N10** — `src/mail.py::fetch_user_email` hängt den OAuth-Access-Token
  als Query-Parameter an die `tokeninfo`-URL. Der Endpoint unterstützt
  denselben Aufruf per POST-Body, was das Leck-Risiko über URL-Logging
  (Proxies, Server-Logs) vermeidet.
- **N12** — `src/autostart.py::_enable_linux` schreibt `target`/`arguments`
  ungequotet in die `Exec=`-Zeile der `.desktop`-Datei. Ein Pfad mit
  Leerzeichen zerbricht den Autostart-Eintrag nach der Desktop-Entry-Spec.

## Ziele / Nicht-Ziele

**Ziele:** alle drei Findings beheben, verhaltensgleich für den
Normalfall (keine Sonderzeichen/kein fremder Prozess), mit Tests, die den
jeweiligen Angriffs-/Fehlerfall abdecken.

**Nicht-Ziele:**
- Kein Windows-ACL-Hardening für die neue Secret-Datei (das ist M8, ein
  eigenes, noch offenes Finding für `token.json` — konsistent unbehandelt
  lassen statt hier stillschweigend mitzulösen).
- Kein Wechsel von TCP auf plattformspezifische IPC-Primitive für N9
  (Named Pipe/Unix-Socket) — im Brainstorming verworfen: großer Umbau
  eines bewusst plattform-einheitlichen Moduls für einen Bedrohungsfall
  ohne echten Netzwerk-Angreifer.
- Kein Replay-Schutz (HMAC-Challenge) für N9 — verworfen, da der
  Zusatzaufwand (Nonce-Zustand, mehr Testfälle) den Bedrohungsfall
  (Single-User-Desktop, lokal-only) nicht rechtfertigt.
- Keine rückwirkende Migration/Kompatibilitätslogik für den kurzen
  Moment während eines In-Place-Updates, in dem eine alte (secret-lose)
  Instanz auf einen neuen Client treffen könnte (siehe Risiken).

## Design

### 1. N9 — Shared-Secret-Auth für den Single-Instance-Handshake

**Neue Datei** `instance-secret` in `base_path` (gleiches Verzeichnis wie
`settings.json`/`token.json`): 32 Zufallsbytes (`os.urandom(32)`), beim
ersten `acquire()` erzeugt, falls nicht vorhanden oder falsch groß
(korrupt/leer → neu erzeugen, kein Quarantäne-Mechanismus nötig, da die
Datei kein Nutzdaten enthält). Schreiben folgt exakt dem Muster von
`oauth_utils.write_token` (mkstemp im selben Verzeichnis → schreiben →
`os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)` in `try/except OSError:
pass` [Windows: chmod ist dort selbst ein OS-No-op, kein Extra-Code nötig
— echtes Windows-ACL-Härten bliebe M8-Scope] → `os.replace` mit demselben
Retry-Backoff gegen transiente `PermissionError` wie bei `token.json`,
Issue #135). Zweitverwendung dieses Musters statt Neuerfindung.

**Crash-Sicherheit (Modul-Invariante "blockiert den Start nie"):** Laden
**und** Erzeugen des Secrets läuft in `acquire()` komplett in
`try/except OSError`. Schlägt beides fehl (Verzeichnis nicht
lesbar/schreibbar — in der Praxis nur denkbar, wenn `base_path` schon
für `settings.json`/`storage.json` kaputt wäre, also ein ohnehin
fataler Zustand für die App), wird eine Warnung geloggt und `secret =
None` gesetzt. Mit `secret = None` überspringen `_Guard`/`_accept_loop`
und `_notify_primary` den Secret-Vergleich vollständig — Fallback ist das
**alte, unauthentifizierte Protokoll** (Magic-Byte-Vergleich wie vor
diesem Fix), nie eine Exception, die den Start abbricht.

**Asymmetrie des Fallbacks (bewusst akzeptiert):** Der Fallback ist nur
dann verhaltensgleich zum alten Protokoll, wenn die **Primär**-Instanz
zurückfällt (ihr `_accept_loop` prüft dann nur `startswith(MAGIC)` und
ignoriert das Secret des neuen Clients → akzeptiert, Zweitinstanz beendet
sich). Fällt umgekehrt die **Zweit**-Instanz zurück (schickt nur MAGIC),
während die Primäre ein echtes Secret erwartet, lehnt die Primäre ab
(Secret-Mismatch) → die Zweitinstanz bekommt kein `ZEIT-OK` und läuft als
degradierte Zweitinstanz weiter. Das ist **derselbe** Ausgang wie heute
schon beim Fremd-Port-Squatter (Test
`test_foreign_occupant_yields_degraded_primary`) und liegt damit im
bestehenden Best-Effort-Vertrag des Moduls
(„blockiert den Start nie, Guard ist best-effort") — es ist kein neuer
Fehlerfall, nur einer, den der Secret-Fallback in einem seltenen
Einzelfall auslösen kann. Voraussetzung ist ohnehin, dass die Secret-
Datei für die Zweit-, aber nicht die Erstinstanz unlesbar ist — ein
transienter, sehr seltener Zustand.

**Wire-Format:** Handshake-Payload wird `MAGIC (9 Byte) + Secret (32 Byte)`
= **41 Byte fix** statt nur `MAGIC` (bisher `_MAGIC_SHOW`/`_MAGIC_PING`, je
9 Byte). Weil damit eine **feste Länge** nötig wird (nicht mehr nur ein
`startswith`-Präfix), muss `_accept_loop` **genau** die erwartete Länge
lesen: eine kleine Read-Schleife (`recv` bis 41 Byte gesammelt **oder**
`_ACK_TIMEOUT`/leerer recv → Verbindung verwerfen), nicht ein einzelnes
`recv(64)`. Grund: TCP ist ein Stream; ein einzelnes `recv` darf legal
weniger als 41 Byte liefern, und ein Teil-Read würde eine **legitime**
Geschwister-Instanz fälschlich als Secret-Mismatch abweisen (→ degradierte
Zweitinstanz). Auf Loopback mit 41 Byte ist das extrem selten, aber die
feste Länge macht das korrekte Lesen zur Pflicht, nicht zur Kür.

Danach: 9-Byte-Magic-Präfix prüfen **und** die 32 Secret-Bytes zeitkonstant
über `hmac.compare_digest` gegen das eigene Secret vergleichen. Nur bei
**beidem** Match → `ZEIT-OK`. Bei Magic- oder Secret-Mismatch (oder
Timeout/Short-Read): Verbindung ohne Antwort verwerfen (identischer
Codepfad zum bestehenden „unbekannte/leere Daten"-Fall in `_accept_loop`)
— der Aufrufer landet im bereits vorhandenen Degraded-Pfad („kein ZEIT-OK"
→ Start ohne Guard, geloggt).

**API:** `acquire(base_path, show_requested)` lädt/erzeugt das Secret vor
dem Bind-Versuch und reicht es an `_Guard.__init__` sowie
`_notify_primary(port, show_requested, secret)` durch. Die öffentliche
Signatur von `acquire`/`serve`/`release` bleibt unverändert — nur intern
wird das Secret durchgereicht.

### 2. N10 — POST statt Query-Param für den tokeninfo-Call

`fetch_user_email` in `mail.py`: statt

```python
url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"access_token": creds.token})
with urllib.request.urlopen(url, timeout=10) as resp:
```

wird der Access-Token als POST-Body übertragen:

```python
data = urllib.parse.urlencode({"access_token": creds.token}).encode("ascii")
req = urllib.request.Request(
    "https://oauth2.googleapis.com/tokeninfo", data=data, method="POST")
with urllib.request.urlopen(req, timeout=10) as resp:
```

Rückgabewert-Handling (`json.load(resp)`, Fehlerpfad, Logging der
Response-Keys) bleibt unverändert — reine Transport-Änderung.

**Verifiziert (2026-07-15):** Der tokeninfo-Endpoint akzeptiert
`access_token` per POST-Body mit `application/x-www-form-urlencoded`
([Google OAuth2-Doku](https://developers.google.com/identity/protocols/oauth2),
[REST-Beispiel](https://csdcorp.com/blog/coding/oauth2-get-a-token-via-rest-google-sign-in/)).
`urllib.request` setzt den `Content-Type`-Header automatisch, sobald
`data` gesetzt ist — kein manueller Header nötig.

### 3. N12 — shlex.quote() für Exec=

`_enable_linux` in `autostart.py`: `target` und jedes (leerzeichen-
getrennte) Element von `arguments` einzeln durch `shlex.quote()`
schicken, bevor sie in die `Exec=`-Zeile geschrieben werden:

```python
from shlex import quote

def _exec_line(target, arguments):
    parts = [quote(target)]
    if arguments:
        parts.extend(quote(a) for a in arguments.split())
    return " ".join(parts)
```

`shlex.quote()` liefert POSIX-Shell-korrektes Quoting (Single-Quote-
basiert) und deckt sich damit, wie GLib (`g_shell_parse_argv`) — die
Basis der GNOME/KDE-Autostart-Tokenisierung — den `Exec`-Wert in der
Praxis parst. Für Werte ohne Sonderzeichen (der heutige Normalfall:
`/opt/Zeiterfassung.AppImage`, `--minimized`) ist die Ausgabe identisch
zum unquotierten String (`shlex.quote` quotet nur bei Bedarf).

`arguments.split()` nimmt an, dass `arguments` ein Whitespace-getrennter
String einfacher Flags ist — das trifft für die heutige Aufrufseite zu
(`arguments` ist immer `""` oder `"--minimized"`, gesetzt in
`enable_autostart`). Ein Argument, das selbst ein Leerzeichen enthalten
soll, ist damit nicht darstellbar; das ist aber auch heute schon so und
kein Ziel dieses Fixes.

## Testing

- **N9:** neuer Test in `tests/test_single_instance.py` — roher
  `socket.create_connection`, sendet nur `_MAGIC_SHOW` **ohne** Secret →
  erwartet **kein** `ZEIT-OK` in der Antwort und dass der `serve()`-
  Callback nicht feuert. Zweiter neuer Test für die Crash-Sicherheit:
  Secret-Datei-Pfad auf ein nicht schreibbares Verzeichnis zeigen lassen
  (oder `os.replace`/`open` passend monkeypatchen, um `OSError` zu
  erzwingen) → `acquire()` liefert trotzdem einen gebundenen Guard
  zurück (kein Crash), altes Magic-only-Protokoll funktioniert weiter.
  Bestehende Tests laufen unverändert (sie gehen ausschließlich über
  `acquire`/`serve`/`release`, fassen das Wire-Format nicht direkt an).
- **N10:** bestehender Test
  `test_fetch_user_email_uses_tokeninfo_not_gmail_getprofile` bleibt
  Kern-Test; Mock von `urllib.request.urlopen` ggf. um eine Prüfung
  erweitern, dass ein `Request`-Objekt mit `method="POST"` reinkommt statt
  eines reinen URL-Strings.
- **N12:** bestehende Tests (`test_enable_writes_desktop_file`,
  `test_enable_without_arguments_has_no_trailing_space`) bleiben grün.
  Neuer Test: `target` mit Leerzeichen im Pfad (`/opt/My App.AppImage`) →
  erwartet gequotete `Exec=`-Zeile.
- Gesamt: `pytest` + `ruff check .` headless für alle drei. N12 zusätzlich
  Pre-Release-Empfehlung vor dem nächsten echten Release (Linux-
  spezifisch, auf der Windows-Dev-Maschine nicht gegen eine echte
  Desktop-Umgebung verifizierbar — siehe Root-`CLAUDE.md`,
  „Plattformspezifische PRs — Pre-Release vorschlagen").

## Risiken

- **N9 Upgrade-Fenster:** während eines In-Place-Updates könnte eine kurz
  laufende alte Instanz (kennt kein Secret) einen Handshake eines neuen
  Clients erhalten; ihre alte `_accept_loop`-Logik (`startswith(MAGIC)`,
  ignoriert den Rest) würde fälschlich `ZEIT-OK` antworten. Bewusst nicht
  behandelt (siehe Nicht-Ziele) — das Fenster ist klein und der
  Schadensfall bleibt derselbe Nuisance-Fall wie heute ungefixt.
- **N9 Secret-Datei-Lebenszyklus:** die Datei wird nie rotiert/gelöscht
  (analog zu `token.json`). Kein Cleanup-Pfad in diesem PR — außerhalb
  des Scopes.
- **N9 Fallback deaktiviert die Auth:** greift der Crash-Sicherheits-
  Fallback (`secret = None`), ist der Handshake für diesen Lauf wieder
  komplett unauthentifiziert — bewusst in Kauf genommen (siehe Design),
  da die Alternative ein Startup-Crash wäre. Bleibt der Verzeichnis-
  Fehler dauerhaft bestehen, bleibt N9 für die betroffene Installation
  dauerhaft ungefixt, aber die App startet weiter.
- **N12 Verifikationslücke:** `shlex.quote()`-Ausgabe ist POSIX-Shell-
  korrekt, aber die Desktop-Entry-Spec definiert formal eine eigene,
  leicht abweichende Quoting-Grammatik. In der Praxis parsen die
  gängigen Implementierungen (GLib/GNOME, KDE) shell-ähnlich; ein
  Restrisiko für exotische Autostart-Parser bleibt, das nur über den
  Pre-Release-Realtest auf echten Linux-Desktops sichtbar würde.
