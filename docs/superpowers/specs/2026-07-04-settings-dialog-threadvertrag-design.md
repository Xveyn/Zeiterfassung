# Settings-Dialog: Thread-Vertrag & überlebende Persistenz (Audit H5)

> Design-Spec, 2026-07-04. Behebt Audit-Finding **H5** — die sechs Worker im
> `settings_dialog` umgehen den dokumentierten Thread-Vertrag und verlieren bei
> geschlossenem Dialog Ergebnisse. Branch `fix/settings-dialog-threadvertrag`
> (gestapelt auf #122 `fix/dialog-theme-helper`, da beide `settings_dialog.py`
> anfassen).

## Problem

`src/dialogs/settings_dialog.py` startet an sechs Stellen (Z. 299/378/490/556/634/681)
direkt `threading.Thread(target=…, daemon=True).start()` und liefert das Ergebnis
per **ungeschütztem** `dialog.after(0, …)` zurück. `src/CLAUDE.md` schreibt aber
**genau ein** Muster vor: Hintergrundarbeit über `BackgroundTaskRunner.run(fn, on_done)`,
Rückgabe über `App._marshal_to_ui` (gegen `TclError` abgesichert). Der Dialog ist die
einzige Ausnahme (auch im Audit als Positiv-Punkt 1 vermerkt: „Ausnahme ist nur
`settings_dialog`").

Der konkrete Schaden trifft die zwei OAuth-**Aktivieren**-Toggles:

- **#2 Drive-Sync aktivieren** (`_finish_oauth`, Z. 343): `cb_sync.config(state="normal")`
  läuft **vor** `settings.set("sync_enabled", True)`. Schließt der Nutzer den Dialog
  während des (minutenlangen) OAuth-Browser-Flows, wirft `dialog.after(0, …)` bzw.
  `cb_sync.config` einen `TclError` → der Daemon-Thread stirbt unbehandelt, und
  `settings.set("sync_enabled", True)` läuft **nie**, obwohl der Consent erfolgreich war.
- **#6 Kalender aktivieren** (`_finish_gcal_oauth`, Z. 645): `if not cb_gcal.winfo_exists():
    return` steht **vor** `settings.set("gcal_enabled", True)` → bei geschlossenem Dialog
  wird die Persistenz sauber, aber genauso folgenlos übersprungen. Gleicher Netto-Bug,
  andere Ursache.

Verschärfend: `src/logging_setup.py` installiert nur `sys.excepthook` + Tk-Hook, **kein**
`threading.excepthook`. Der Thread-Tod aus #2 landet damit nur auf dem per `--noconsole`
unterdrückten stderr — spurlos.

## Kategorisierung der sechs Worker

| # | Zeile | Worker | Persistiert Zustand? | Close-Verhalten heute |
|---|-------|--------|----------------------|-----------------------|
| #2 | 378 | Drive-Sync aktivieren (OAuth) | **ja** `sync_enabled=True` | Crash → Persistenz verloren |
| #6 | 681 | Kalender aktivieren (OAuth) | **ja** `gcal_enabled=True` | Guard-Skip → Persistenz verloren |
| #4 | 556 | Sync-Kompaktierung | Nebeneffekt im Worker | korrekt (`winfo_exists`-Guard) |
| #1 | 299 | Absender-Mail „Aktualisieren" | nein | UI-Display; Nebeneffekt überlebt im Worker |
| #3 | 490 | Google neu verbinden | nein | Token-Refresh überlebt; UI-Feedback verloren |
| #5 | 634 | Kalenderliste laden | nein | Combobox-Populate |

Nur #2/#6 verlieren echte Persistenz. Die anderen vier sind reines UI-Feedback bzw.
haben ihren Nebeneffekt bereits im Worker (überlebt ohnehin) — sie werden **aus
Konventionsgründen** mitmigriert, ihr Verhalten bleibt identisch.

## Entscheidungen (mit dem Nutzer abgestimmt)

1. **Umfang:** Alle sechs Worker einheitlich auf `BackgroundTaskRunner.run` umstellen
   (nicht nur die zwei Persistenz-Bugs). Verhindert strukturell den nächsten H5.
   **H4** (God-Function pro Tab entflechten) bleibt ein **separater** Punkt.
2. **OAuth-Semantik:** Schließt der Nutzer den Dialog während eines erfolgreichen
   OAuth-Flows, **überlebt die Persistenz** — `settings.set(…, True)` läuft trotzdem,
   das Feature ist beim nächsten Öffnen aktiv. Nur das UI-Feedback (Checkbox/Messagebox)
   entfällt. So liest auch das Audit den Bug.

## Kernmechanismus

`open_settings_dialog(...)` bekommt einen **keyword-only Parameter `runner`**
(= `App._bg`, der bestehende `BackgroundTaskRunner`), von `ui.py` durchgereicht.
Es gibt genau einen Aufrufer (`App._open_settings`); Tests injizieren einen Fake-Runner.

Jeder Worker wird zu:

```python
runner.run(fn, on_done)
```

mit einer klaren Zweiteilung:

- **`fn` — läuft im Daemon-Worker, überlebt den Dialog-Close.**
  Enthält das Blocking-I/O (OAuth-Flow, Netz-Call, Kompaktierung) **und die
  Persistenz, die überleben muss** (`settings.set(...)` — thread-safe seit dem
  Datenschicht-Lock aus #121). `fn` fängt seine Exceptions selbst und gibt ein
  Result-Dict zurück (`{"ok": True}` / `{"ok": False, "error": e, "tb": …}`); es
  **wirft nie** → kein stiller Thread-Tod, N19 (fehlendes try um `fn()` im Runner)
  bleibt unberührt und irrelevant für diesen Pfad.

- **`on_done(res)` — läuft auf dem UI-Thread über `App._marshal_to_ui` (TclError-gesichert).**
  Reihenfolge ist verbindlich:
  1. **überlebende UI zuerst:** `on_change()` (App-/root-scoped: Kalender-Refresh,
     Sync-Status-Label, Tray/Reminder, Absender-Fetch — **nicht** dialoggebunden) und
     ggf. `_load_calendars()`. Läuft auch bei geschlossenem Dialog, solange die Root
     lebt; der Marshal-Guard fängt den Shutdown-Sonderfall.
  2. **dann Dialog-Widget-Kosmetik:** `cb.config(...)`, `var.set(...)`, Messageboxen
     mit `parent=dialog` — jede über einen `winfo_exists`-Guard geschützt und
     übersprungen, wenn der Dialog weg ist.

Damit ist die Persistenz **strukturell** von der Dialog-Lebensdauer entkoppelt: sie
sitzt im `fn` (Worker) bzw. in der root-scoped ersten Hälfte von `on_done`, nie hinter
einem Dialog-Widget-Zugriff, der abbrechen könnte.

Alle sechs `threading.Thread(...)`- und alle `dialog.after(0, …)`-Stellen im Dialog
entfallen. `import threading` wird im Dialog überflüssig (prüfen und entfernen).
**Nicht betroffen:** der periodische UI-Timer `dialog.after(500, refresh_status)`
(Z. 242) — der läuft auf dem UI-Thread, verletzt keinen Thread-Vertrag und bleibt.

**Akzeptierter Randfall (Bestandsverhalten):** Schließt der Nutzer den Dialog während
eines laufenden OAuth-Flows und öffnet ihn sofort neu, liest der neue Dialog noch
`sync_enabled/gcal_enabled = False` und erlaubt einen zweiten Flow. Das konnte der
alte Code genauso; der zweite Flow nutzt das inzwischen gespeicherte Token (kein
zweiter Browser-Consent) und die zweite Persistenz ist idempotent. Kein Fix nötig.

## Per-Worker-Umsetzung

### #2 Drive-Sync aktivieren (`_on_sync_toggled` / `_do_oauth` / `_finish_oauth`)

Das (fn, on_done)-Paar entsteht über den gemeinsamen `build_oauth_enable_task`-Helfer
(s. Tests); der folgende Code zeigt das erzeugte Verhalten:

```python
def _on_sync_toggled():
    assert cb_sync is not None
    new_state = var_sync.get()
    if new_state and not settings.get("sync_enabled"):
        cb_sync.config(state="disabled")

        def fn():
            try:
                from src import drive
                drive.get_drive_service(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
            except Exception as e:
                return {"ok": False, "error": e, "tb": traceback.format_exc()}
            settings.set("sync_enabled", True)   # überlebt Dialog-Close
            return {"ok": True}

        def on_done(res):
            if res["ok"]:
                on_change()                       # root-scoped, überlebt
            if not cb_sync.winfo_exists():
                return                            # Dialog weg -> Kosmetik überspringen
            cb_sync.config(state="normal")
            if not res["ok"]:
                var_sync.set(False)
                messagebox.showerror(
                    "Synchronisation aktivieren",
                    f"OAuth-Flow fehlgeschlagen:\n\n{res['error']}\n\n{res['tb']}",
                    parent=dialog,
                )

        runner.run(fn, on_done)
        return
    if not new_state and settings.get("sync_enabled"):
        settings.set("sync_enabled", False)
        on_change()
```

### #6 Kalender aktivieren (`_on_gcal_toggled` / `_finish_gcal_oauth`)

Analog zu #2. `fn` persistiert bei Erfolg `settings.set("gcal_enabled", True)`.
`on_done` bei Erfolg: **nur** `on_change()` ist root-scoped und läuft vor dem Guard.
`_load_calendars()` ist dagegen **Dialog-Kosmetik** (setzt sofort
`cal_status.config(...)` und populiert die Dialog-Combobox) und gehört **hinter**
den `winfo_exists`-Guard — bei geschlossenem Dialog ist die Kalenderliste sinnlos
und der Widget-Zugriff würde werfen. Fehlerpfad: `var_gcal.set(False)` + Messagebox,
ebenfalls `winfo_exists`-geschützt.

### #4 Sync-Kompaktierung (`_on_compact_clicked` / `_show`)

`fn` = `_run_compaction_blocking(...)` (Nebeneffekt bereits im Worker). `on_done` = das
bestehende `_show(res)` (bereits `winfo_exists`-korrekt), nur von `dialog.after` auf
`runner.run` umgestellt. Verhalten unverändert.

### #1 Absender-Mail „Aktualisieren", #3 Google neu verbinden, #5 Kalenderliste laden

Reine UI-Worker ohne persistierten Zustand. Umstellung von `threading.Thread` +
`dialog.after` auf `runner.run(fn, on_done)`; die bestehenden `_finish_*`-Callbacks
werden zu `on_done`, ihre Dialog-Widget-Zugriffe über `winfo_exists` geschützt (teils
schon vorhanden, z. B. `_load_calendars_error` prüft `cal_status.winfo_exists()`).
`reconnect_busy["value"] = False` im `on_done` von #3. Verhalten unverändert.

## Betroffene Dateien

- `src/dialogs/settings_dialog.py` — sechs Worker umgestellt, `import threading` entfernt,
  `runner`-Parameter ergänzt.
- `src/ui.py` — `open_settings_dialog(..., runner=self._bg)` durchreichen.
- `src/CLAUDE.md` — Positiv-Notiz „Ausnahme ist nur `settings_dialog` (H5)" streichen bzw.
  auf „behoben" aktualisieren; im `settings_dialog`-Absatz den Runner-Vertrag festhalten.
- `tests/test_settings_dialog.py` — **neu**, siehe unten.

## Tests

Der Dialog wird bislang von **keinem** Test aufgerufen (Tk-gebunden, M16). Der injizierte
Runner macht die fn/on_done-Kontrakte erstmals headless prüfbar. Muster wie `_FakeRunner`
in `tests/test_sync_orchestrator.py`: synchroner Runner, der `fn()` sofort ausführt und
`on_done(result)` aufruft.

Da die Worker heute als Closures **innerhalb** `open_settings_dialog` leben, sind sie
nicht direkt aufrufbar. #2 und #6 sind zudem near-identisch (nur Service-Call +
Settings-Key unterscheiden sich). Beide werden daher über **einen gemeinsamen
modulweiten Builder** gelöst, z. B.

```python
def build_oauth_enable_task(*, service_fn, settings, setting_key,
                            checkbox, toggle_var, on_change, dialog,
                            error_title, on_success_dialog_ui=None):
    """Baut (fn, on_done) für einen OAuth-Aktivieren-Toggle: fn ruft service_fn()
    und persistiert setting_key=True bei Erfolg (überlebt Dialog-Close); on_done
    ruft on_change() (root-scoped, vor dem Guard) und danach die winfo_exists-
    geschützte Dialog-Kosmetik. on_success_dialog_ui (optional) läuft bei Erfolg
    NACH dem Guard — #6 hängt hier _load_calendars ein (Dialog-Kosmetik, s.o.);
    #2 lässt es weg. error_title ist der Messagebox-Titel des Fehlerpfads.
    Rückgabe: (fn, on_done) für runner.run(...)."""
```

Das entfernt zugleich die Duplikation zwischen #2 und #6. Der Builder ist ohne echten
Tk-Dialog testbar: Fake-`settings`, ein Fake-Widget mit steuerbarem `winfo_exists()`,
ein Recorder-`on_change` und ein Fake-Service-Callable (Erfolg vs. Exception). Abgedeckt:

1. **Persistenz überlebt Close:** OAuth-Erfolg + Widget `winfo_exists()→False` →
   `settings.set("sync_enabled", True)` wurde aufgerufen **und** `on_change` genau einmal;
   **kein** `cb.config`/Messagebox auf totem Widget.
2. **Normalfall (Dialog offen):** Erfolg → Persist + `on_change` + `cb.config("normal")`.
3. **Fehlerpfad:** OAuth wirft → **keine** Persistenz, `var.set(False)` + Fehler-Messagebox
   (bei offenem Dialog), sauberes Überspringen bei geschlossenem.
4. **gcal analog** inkl. `on_success_dialog_ui` (= `_load_calendars`): wird bei Erfolg
   **und offenem Dialog** aufgerufen, bei geschlossenem übersprungen.

Gesamtsuite muss grün bleiben (`pytest`), `ruff check .` sauber. Ein optionaler
Tk-Smoke (echter Dialog, ein Toggle) ist Kür; primär die headless-Kontrakte.

## Ausdrücklich außerhalb des Scopes

- **H4** — Aufteilung der ~930-Zeilen-`open_settings_dialog` pro Tab. Eigener Punkt/Branch.
- **N19** — fehlendes try um `fn()` in `BackgroundTaskRunner.run` bzw. globales
  `threading.excepthook`. Dieser Fix macht jedes `fn` selbstfangend, braucht N19 nicht.
- **M10** — `send_dialog`/`share_dialog`/`export_dialog` blockieren den Main-Thread.
  Eigenes Finding, anderer Dialog.
