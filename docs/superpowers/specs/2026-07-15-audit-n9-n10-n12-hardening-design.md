# Design: Audit-Härtung N9/N10/N12 (Sammel-PR)

> Stand 2026-07-15 · Follow-ups aus dem Audit-Tracking-Issue #131
> (Code-Audit 2026-07-04). Drei unabhängige NIEDRIG-Findings, gebündelt in
> einem Sammel-PR, da keins davon für sich einen eigenen PR rechtfertigt.

## Problem

- **N9** — `src/single_instance.py`s lokales SHOW/PING-Protokoll hat keine
  Authentifizierung: jeder lokale Prozess, der den (deterministisch aus dem
  Base-Path abgeleiteten) Port erreicht, kann `ZEIT-SHOW`/`ZEIT-PING`
  senden und wird bedient. Realer Schaden ist begrenzt (Port-Squatting
  degradiert bereits heute kontrolliert auf ungeschützten Start; ein
  gefälschtes SHOW holt bestenfalls das Fenster nach vorne), aber das
  Fehlen jeder Auth ist trotzdem ein offenes Finding.
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
Datei kein Nutzdaten enthält). Atomar geschrieben (Temp+`os.replace`, wie
`storage._save_to_disk`). Unter Unix zusätzlich `os.chmod(path, 0o600)`
best-effort (in `try/except OSError: pass`, analog zum bestehenden
Windows-No-Op-Muster in `oauth_utils.py`) — unter Windows kein Äquivalent
(das wäre M8-Scope).

**Wire-Format:** Handshake-Payload wird `MAGIC (9 Byte) + Secret (32 Byte)`
statt nur `MAGIC` (bisher `_MAGIC_SHOW`/`_MAGIC_PING`, je 9 Byte).
`_accept_loop` liest bis zu 64 Byte (Puffer-Marge), prüft das
9-Byte-Magic-Präfix **und** vergleicht die folgenden 32 Bytes gegen das
eigene Secret über `hmac.compare_digest` (zeitkonstant). Nur bei
**beidem** Match → `ZEIT-OK`. Bei Magic- oder Secret-Mismatch: Verbindung
ohne Antwort verwerfen (identischer Codepfad zum bestehenden
„unbekannte/leere Daten"-Fall in `_accept_loop`) — der Aufrufer landet im
bereits vorhandenen Degraded-Pfad („kein ZEIT-OK" → Start ohne Guard,
geloggt).

**API:** `acquire(base_path, show_requested)` lädt/erzeugt das Secret vor
dem Bind-Versuch und reicht es an `_Guard.__init__` sowie
`_notify_primary(port, show_requested, secret)` durch. Die öffentliche
Signatur von `acquire`/`serve`/`release` bleibt unverändert — nur intern
wird das Secret durchgereicht.

### 2. N10 — POST statt Query-Param für den tokeninfo-Call

`fetch_user_email` in `mail.py`: statt

```python
url = "https://oauth2.googleapis.com/tokeninfo?" + urlencode({"access_token": creds.token})
with urllib.request.urlopen(url, timeout=10) as resp:
```

wird der Access-Token als POST-Body übertragen:

```python
data = urlencode({"access_token": creds.token}).encode("ascii")
req = urllib.request.Request(
    "https://oauth2.googleapis.com/tokeninfo", data=data, method="POST")
with urllib.request.urlopen(req, timeout=10) as resp:
```

Rückgabewert-Handling (`json.load(resp)`, Fehlerpfad, Logging der
Response-Keys) bleibt unverändert — reine Transport-Änderung.

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

## Testing

- **N9:** neuer Test in `tests/test_single_instance.py` — roher
  `socket.create_connection`, sendet nur `_MAGIC_SHOW` **ohne** Secret →
  erwartet **kein** `ZEIT-OK` in der Antwort und dass der `serve()`-
  Callback nicht feuert. Bestehende Tests laufen unverändert (sie gehen
  ausschließlich über `acquire`/`serve`/`release`, fassen das Wire-Format
  nicht direkt an).
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
- **N12 Verifikationslücke:** `shlex.quote()`-Ausgabe ist POSIX-Shell-
  korrekt, aber die Desktop-Entry-Spec definiert formal eine eigene,
  leicht abweichende Quoting-Grammatik. In der Praxis parsen die
  gängigen Implementierungen (GLib/GNOME, KDE) shell-ähnlich; ein
  Restrisiko für exotische Autostart-Parser bleibt, das nur über den
  Pre-Release-Realtest auf echten Linux-Desktops sichtbar würde.
