# Design: Dedizierter Dev-Mode

**Datum:** 2026-05-28
**Branch:** feat/dev-mode (von `master`)
**Status:** Entwurf zur Review

## Ziel

Ein dedizierter Entwickler-Modus, der ausschließlich über `python -m src.main --dev`
aktiviert wird. Er erlaubt das gefahrlose Durchklicken aller App-Flows ohne echte
Google-Dienste, ohne echte Nutzerdaten zu berühren, und macht zur Laufzeit sichtbar,
was die App tut.

Drei Bausteine plus ein UI-Indikator:

1. **Fake-Google-Layer** — Gmail, Drive und Calendar komplett gemockt (kein OAuth,
   kein Netzwerk, kanonische Erfolge, alles geloggt).
2. **Isoliertes Dev-Daten-Verzeichnis** — getrennt von echten Einträgen/Settings/Token,
   mit Sample-Daten geseedet.
3. **Konsolen-Fenster** — Live-Log-Viewer (DEBUG) mit Dev-Aktions-Buttons.
4. **Titel-Indikator** — „Dev-Mode" neben der Version im Fenstertitel.

## Nicht-Ziele

- Kein Python-REPL im Konsolen-Fenster (read-only Log + Buttons genügt).
- Keine separaten echten Test-Credentials gegen echte Google-APIs.
- Kein `--dev`-Schalter in der UI; Aktivierung nur über das CLI-Flag.
- Kein Dev-Code im Produktionspfad: `src/dev/` wird im Normalbetrieb nie importiert.

## Architektur

Neues, isoliertes Paket `src/dev/`:

```
src/dev/
  __init__.py     # activate() — installiert Fakes, Einstiegspunkt
  fakes.py        # Fake-Implementierungen der Google-Modul-Funktionen
  seed.py         # Sample-Daten ins Dev-Daten-Verzeichnis schreiben
  console.py      # Tk-Toplevel Log-Viewer + Aktions-Buttons
```

`src/dev/` wird **nur** importiert, wenn `--dev` gesetzt ist. Im Normalstart bleibt der
Import-Graph unverändert.

### Mock-Strategie: Monkeypatch der Modul-Funktionen

Alle Eintrittspunkte zu Google sind Modul-Funktionen, und alle Aufrufstellen rufen sie
(bis auf drei Dialog-Imports, s.u.) modul-qualifiziert auf. `activate()` ersetzt deshalb
beim Start die folgenden Attribute durch Fakes:

| Modul | Ersetzte Funktionen |
|-------|---------------------|
| `src.mail` | `get_gmail_service`, `send_email` |
| `src.drive` | `get_drive_service`, `find_sync_file`, `download`, `upload` |
| `src.gcal` | `get_calendar_service`, `list_app_events`, `create_event`, `update_event`, `delete_event` |

Damit muss kein googleapiclient-Resource-Chain (`service.files().list().execute()`)
nachgebaut werden — die Builder liefern nur ein Sentinel-Objekt, die eigentliche
Logik sitzt in den modul-qualifiziert aufgerufenen Operationen.

**Erforderliche Import-Vereinheitlichung:** Drei Dialoge importieren per
`from src.mail import get_gmail_service, send_email` — ein nach `activate()` gesetzter
Monkeypatch auf `src.mail` greift dort nicht, weil der Name beim Import gebunden wurde.
Umstellen auf modul-qualifizierten Zugriff:

- `src/dialogs/send_dialog.py`
- `src/dialogs/share_dialog.py`
- `src/dialogs/settings_dialog.py`

Konkret: `from src.mail import get_gmail_service, is_offline_error, send_email` →
`from src import mail` und an den Aufrufstellen `mail.get_gmail_service(...)`,
`mail.send_email(...)`, `mail.is_offline_error(...)`. Rein mechanisch, kein Verhaltensänderung
im Normalbetrieb.

## Komponenten

### 1. Aktivierung & Verdrahtung — `src/main.py`

Ganz am Anfang von `main()`, **vor** `get_base_path()`:

```python
dev_mode = "--dev" in sys.argv
if dev_mode:
    if not os.environ.get("ZEITERFASSUNG_DATA_DIR"):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        os.environ["ZEITERFASSUNG_DATA_DIR"] = os.path.join(repo, "dev-data")
    from src.dev import activate
    activate()
```

`activate()`:
1. Monkeypatcht die Tabelle oben.
2. Seedet Sample-Daten ins Dev-Daten-Verzeichnis, falls leer (s. Komponente 4).

`base = get_base_path()` liefert danach automatisch das Dev-Verzeichnis (Override greift).
`App(...)` bekommt `dev_mode=True` durchgereicht.

### 2. Fake-Google-Layer — `src/dev/fakes.py`

- `_Sentinel` — Platzhalter-Objekt, das die Builder zurückgeben. Wird nur durchgereicht,
  nie aufgerufen.
- `fake_get_gmail_service(*a, **k)` → `_Sentinel`.
- `fake_send_email(service, to, subject, html_body, attachment_bytes=None,
  attachment_filename=None, ...)` → loggt
  `DEV: würde Mail senden an=<to> betreff=<subject> anhang=<filename>` auf INFO,
  liefert `"dev-msg-<n>"`.
- `fake_get_drive_service(*a, **k)` → `_Sentinel`.
- Drive-Sync-Doc lebt prozessweit als Modul-State (`_drive_doc`, `_drive_version`):
  - `fake_find_sync_file(service)` → `"dev-file"` falls Doc existiert, sonst `None`.
  - `fake_download(service, file_id)` → `(json-bytes(_drive_doc), str(_drive_version))`.
  - `fake_upload(service, content, file_id=None, expected_etag=None)` → speichert Doc,
    erhöht Version, liefert `("dev-file", str(version))`.
- `fake_get_calendar_service(*a, **k)` → `_Sentinel`.
- Kalender-State (`_events: dict[event_id, event]`):
  - `fake_list_app_events(service, calendar_id)` → Liste der Events im erwarteten Format.
  - `fake_create_event(...)` → neue `event_id`, speichert, loggt.
  - `fake_update_event(...)` / `fake_delete_event(...)` → mutiert State, loggt.

Signaturen spiegeln die echten Funktionen exakt (siehe `src/mail.py`, `src/drive.py`,
`src/gcal.py`), damit die Aufrufer unverändert funktionieren.

`reset_state()` setzt Drive-Doc und Kalender zurück — vom „Sample-Daten neu laden"-Button
genutzt.

### 3. Konsolen-Fenster — `src/dev/console.py`

`DevConsole(root)`:
- Eigenes `tk.Toplevel`, Titel „Dev-Konsole".
- Read-only `Text`-Widget mit Scrollbar, monospaced, dunkles Theme passend zur App.
- `_TkLogHandler(logging.Handler)`: `emit()` formatiert den Record und schiebt ihn per
  `root.after(0, ...)` ins Text-Widget (thread-sicher — Logs kommen aus Worker-Threads).
  Autoscroll ans Ende. Handler wird am Root-Logger registriert; Root-Level auf `DEBUG`.
- Button-Leiste:
  - **Sync Pull** / **Sync Push** — triggern die vorhandenen Sync-Pfade (Callback von App).
  - **Token-Fehler simulieren** — setzt ein Flag, das `fake_*`-Auth einmalig
    `TokenAuthError` werfen lässt, um Fehler-UI zu testen.
  - **Sample-Daten neu laden** — `fakes.reset_state()` + `seed`-Reseed + UI-Refresh.
  - **Daten-Ordner öffnen** — `platform_open` auf das Dev-Verzeichnis.
  - **Log leeren** — Text-Widget leeren.
  - **Kopieren** — Text-Inhalt in die Zwischenablage.
- Schließt zusammen mit dem Hauptfenster (`root` ist Parent).

App-Anbindung: in `App.__init__`, wenn `dev_mode`, nach dem Bau der UI
`self._dev_console = DevConsole(self.root, app=self)` erzeugen. Die Buttons rufen
schmale Methoden auf `App` auf (Sync triggern, Refresh) — keine Logik im Fenster selbst.

### 4. Sample-Daten — `src/dev/seed.py`

`seed_if_empty(base_path)`:
- No-op, wenn `zeiterfassung.json` im Dev-Verzeichnis bereits existiert.
- Sonst schreiben:
  - `zeiterfassung.json` — eine Handvoll Einträge über die aktuelle und letzte Woche.
  - `settings.json` — sinnvolle Defaults (Empfänger-Mail Platzhalter, `sync_enabled`/
    `gcal_enabled` aus, damit nichts ungewollt triggert — die Buttons triggern explizit).
  - `credentials.json` + `token.json` — Dummy-Inhalte, damit `os.path.exists`-Checks
    und Token-Refresh-Pfade nicht nach OAuth fragen. (Die Fakes lesen sie nie aus.)

`reseed(base_path)` für den Button: löscht die Daten-Dateien und ruft `seed_if_empty`.

### 5. Titel-Indikator — `src/ui.py`

`App.__init__` bekommt `dev_mode=False`. Zeile 53:

```python
suffix = " — Dev-Mode" if dev_mode else ""
self.root.title(f"Zeiterfassung v{VERSION}{suffix}")
```

## Datenfluss

```
python -m src.main --dev
  └─ main(): ZEITERFASSUNG_DATA_DIR → ./dev-data
             src.dev.activate()  ── monkeypatch mail/drive/gcal + seed_if_empty()
             get_base_path() → ./dev-data
             App(dev_mode=True)
               ├─ Titel „… — Dev-Mode"
               └─ DevConsole(root)  ── _TkLogHandler am Root-Logger, Level DEBUG
  └─ Nutzer klickt „Senden" → mail.send_email (=fake) → Log: „DEV: würde Mail senden …"
  └─ Nutzer klickt „Sync Pull" → drive.find_sync_file/download (=fake) → In-Memory-Doc
```

## Fehlerbehandlung

- Fakes werfen im Normalfall nie — sie liefern kanonische Erfolge.
- „Token-Fehler simulieren" lässt den nächsten Auth-Aufruf `TokenAuthError` werfen, damit
  die echte Fehler-UI (Messagebox-Pfade in `mail.py`/Dialogen) getestet werden kann.
- `activate()` schlägt nur fehl, wenn `src/dev/` defekt ist — das wäre ein Entwicklerfehler
  und soll laut crashen (kein stilles Verschlucken).

## Tests

- `tests/test_dev_fakes.py`:
  - `fake_send_email` loggt und liefert eine ID, sendet nichts.
  - Drive-Fake Roundtrip: `upload` → `find_sync_file` → `download` liefert dasselbe Doc,
    Version steigt.
  - Calendar-Fake: `create_event` → `list_app_events` enthält das Event; `delete_event`
    entfernt es.
  - `reset_state()` leert Drive-Doc und Kalender.
- `tests/test_dev_activate.py`:
  - Nach `activate()` zeigen `mail.send_email`, `drive.upload`, `gcal.create_event` auf
    die Fakes.
  - **Guard:** Ein Import von `src.main` (ohne `--dev`) importiert `src.dev` nicht
    (Prüfung über `sys.modules`).
- Konsolen-Fenster: nur die Handler-Formatierung wird getestet (Record → erwartete Zeile);
  das Tk-Toplevel selbst wird nicht headless getestet.
- `tests/test_seed.py`: `seed_if_empty` legt Dateien an; zweiter Aufruf ist No-op;
  `reseed` schreibt neu.

CI-Hinweis (`.github/workflows/test.yml`): Die Fakes dürfen google-Libs **nicht** eager
importieren (CI installiert `requirements.txt` nicht). `TokenAuthError` kommt aus
`src.mail` (pure Python, kein C-Dep) — Import ist unbedenklich.

## Betroffene Dateien

| Datei | Änderung |
|-------|----------|
| `src/main.py` | `--dev`-Erkennung, ENV-Override, `src.dev.activate()`, `dev_mode` an `App` |
| `src/ui.py` | `App.__init__(dev_mode=False)`, Titel-Suffix, optional `DevConsole` erzeugen, schmale Sync/Refresh-Hooks für die Buttons |
| `src/dialogs/send_dialog.py` | Import-Vereinheitlichung `from src import mail` |
| `src/dialogs/share_dialog.py` | Import-Vereinheitlichung `from src import mail` |
| `src/dialogs/settings_dialog.py` | Import-Vereinheitlichung `from src import mail` |
| `src/dev/__init__.py` | neu — `activate()` |
| `src/dev/fakes.py` | neu — Fake-Funktionen + State |
| `src/dev/seed.py` | neu — Sample-Daten |
| `src/dev/console.py` | neu — Log-Viewer + Buttons |
| `tests/test_dev_fakes.py` | neu |
| `tests/test_dev_activate.py` | neu |
| `tests/test_seed.py` | neu |
| `.gitignore` | `dev-data/` ignorieren |
```
