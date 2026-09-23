# scripts/

Entwickler-Skripte. **Nicht Teil der App** — nichts hier wird gebündelt oder
zur Laufzeit importiert.

Alle Skripte werden aus dem **Repo-Root** aufgerufen:

| Skript | Zweck |
|---|---|
| `build.py` | Plattform-Dispatcher für den PyInstaller-Build (`python scripts/build.py`) — siehe [`CLAUDE.md`](../CLAUDE.md), Abschnitt Build |
| `release_notes.py` | schneidet den Release-Body aus `CHANGELOG.md` (`--check` im `pre-check`-Job, `--out` im `publish`-Job) — siehe [`CLAUDE.md`](../CLAUDE.md), „Release-Body = CHANGELOG-Abschnitt" |
| `resolve_readme_version.py` | löst die Platzhalter `--VERSION--` in README und Screenshot-Namen auf und räumt alte Marker weg (`--check`/`--prune`) — siehe [`CLAUDE.md`](../CLAUDE.md), „README-Zeilen für Unveröffentlichtes markieren" |
| `archive_changelog.py` | verschiebt alles bis auf die neuesten Versionen aus `CHANGELOG.md` nach `CHANGELOG-archive.md` (`--check` zeigt nur an) — siehe [`CLAUDE.md`](../CLAUDE.md), „CHANGELOG-Archiv" |
| `demo_data.py` | legt Demo-Daten (Max Mustermann: Arbeitszeit, Reservierungen, Urlaub, SMTP-Konten, Webhooks) in den Datenordner des Repo-Modus, ohne den Schlüsselbund anzufassen (`python scripts/demo_data.py`, `--force`, `--ohne-kalender`) — Grundlage der [Screenshots](../docs/screenshots/README.md) |
| `webhook_testserver.py` | lokaler Test-Empfänger für den Webhook-Versand (`python scripts/webhook_testserver.py`) |
| `smtp_testserver.py` | lokaler Test-Mailserver für den SMTP-Versand (`python scripts/smtp_testserver.py`) |

`release_notes.py`, `resolve_readme_version.py` und `archive_changelog.py`
laufen **auch in der CI** (`release.yml`), sind aber trotzdem
Entwickler-Werkzeug: sie fassen nur Repo-Dateien an, nichts davon landet im
Build.

`demo_data.py` schreibt in den Datenordner des Repo-Modus (das Projekt-Root,
bzw. `ZEITERFASSUNG_DATA_DIR`); die Dateien dort sind gitignored. Liegen
schon Daten da, bricht es ab — `--force` ersetzt sie.

`build.py` gehört inhaltlich zum Repo-Root: es importiert aus `src/` und
arbeitet mit Pfaden relativ zur Wurzel (`dist/`, `assets/`, `installer.iss`).
Ein Bootstrap am Dateianfang legt deshalb das Repo-Root auf `sys.path` und
wechselt dorthin — der Aufruf funktioniert damit aus jedem Verzeichnis, aber
die Pfade in der Ausgabe beziehen sich immer auf die Wurzel.
