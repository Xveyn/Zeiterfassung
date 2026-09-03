# scripts/

Entwickler-Skripte. **Nicht Teil der App** — nichts hier wird gebündelt oder
zur Laufzeit importiert.

Alle Skripte werden aus dem **Repo-Root** aufgerufen:

| Skript | Zweck |
|---|---|
| `build.py` | Plattform-Dispatcher für den PyInstaller-Build (`python scripts/build.py`) — siehe [`CLAUDE.md`](../CLAUDE.md), Abschnitt Build |
| `webhook_testserver.py` | lokaler Test-Empfänger für den Webhook-Versand (`python scripts/webhook_testserver.py`) |
| `smtp_testserver.py` | lokaler Test-Mailserver für den SMTP-Versand (`python scripts/smtp_testserver.py`) |

`build.py` gehört inhaltlich zum Repo-Root: es importiert aus `src/` und
arbeitet mit Pfaden relativ zur Wurzel (`dist/`, `assets/`, `installer.iss`).
Ein Bootstrap am Dateianfang legt deshalb das Repo-Root auf `sys.path` und
wechselt dorthin — der Aufruf funktioniert damit aus jedem Verzeichnis, aber
die Pfade in der Ausgabe beziehen sich immer auf die Wurzel.
