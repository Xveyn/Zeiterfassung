# Settings-Dialog Thread-Vertrag (Audit H5) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die sechs Hintergrund-Worker in `settings_dialog.py` auf das eine sanktionierte Muster (`BackgroundTaskRunner.run(fn, on_done)`) umstellen, sodass die OAuth-Aktivieren-Persistenz einen Dialog-Close überlebt und kein Worker mehr am dokumentierten Thread-Vertrag vorbei arbeitet.

**Architecture:** `open_settings_dialog` bekommt den bestehenden `BackgroundTaskRunner` (`App._bg`) injiziert. Jeder Worker wird `runner.run(fn, on_done)`: `fn` läuft im Daemon-Thread und enthält Blocking-I/O **plus** die überlebende Persistenz (`settings.set(...)`, thread-safe seit #121); `on_done` läuft via `App._marshal_to_ui` auf dem UI-Thread, ruft root-scoped Survivor (`on_change`) zuerst und schützt danach jeden Dialog-Widget-Zugriff mit `winfo_exists`. Die zwei near-identischen OAuth-Aktivieren-Toggles (#2/#6) teilen sich einen modulweiten, headless-testbaren Builder `build_oauth_enable_task`.

**Tech Stack:** Python 3.14, Tkinter, pytest. Kein neuer Dependency.

## Global Constraints

- **Ein Muster (CLAUDE.md):** Hintergrundarbeit ausschließlich über `BackgroundTaskRunner.run(fn, on_done)`; Rückgabe über `App._marshal_to_ui` (root.after, TclError-gesichert). Nach diesem Plan **kein** `threading.Thread` und **kein** `dialog.after(0, …)` mehr in `settings_dialog.py`. Der reine UI-Timer `dialog.after(500, refresh_status)` (Z. 242) ist **kein** Worker und bleibt unangetastet.
- **Persistenz überlebt Dialog-Close:** `settings.set(...)` steht im `fn` (Worker-Thread), nie hinter einem Dialog-Widget-Zugriff. `settings.set` ist seit #121 thread-safe (geteilter `data_lock`).
- **`on_done`-Reihenfolge:** root-scoped Survivor (`on_change()`) **vor** dem `winfo_exists`-Guard; Dialog-Widget-Kosmetik (`config`/`var.set`/Messagebox/`_load_calendars`) **danach**, jeweils übersprungen wenn der Dialog weg ist.
- **`fn` wirft nie:** jedes `fn` fängt seine Exceptions selbst und gibt ein Result-Dict zurück (`{"ok": True, ...}` / `{"ok": False, "error": e, "tb": str}`). Damit kein stiller Thread-Tod.
- **Result-Dict-Form:** `{"ok": bool}`; im Fehlerfall zusätzlich `"error"` (Exception) und `"tb"` (str). Worker mit Nutzlast ergänzen einen eigenen Schlüssel (`"email"`, `"items"`); die Kompaktierung reicht das Result von `_run_compaction_blocking` unverändert durch.
- **Tests:** Gesamtsuite `pytest` grün, `ruff check .` sauber. Der Dialog ist Tk-gebunden (M16) → **headless getestet wird nur der Builder** `build_oauth_enable_task`; die Verdrahtung der übrigen Worker wird über die grüne Gesamtsuite + einen manuellen Tk-Smoke abgesichert.
- **Außerhalb Scope:** H4 (God-Function-Split), N19 (`threading.excepthook`), M10 (andere Dialoge). Nicht anfassen.

Design-Referenz: `docs/superpowers/specs/2026-07-04-settings-dialog-threadvertrag-design.md`.

---

## Task 1: `build_oauth_enable_task`-Builder (modulweit, TDD)

Der DRY-Kern für #2/#6: baut ein testbares `(fn, on_done)`-Paar für einen OAuth-Aktivieren-Toggle. Wird in Task 2 verdrahtet; hier nur der Helfer + seine Tests. Noch **kein** Aufrufer im Dialog.

**Files:**
- Modify: `src/dialogs/settings_dialog.py` (neuer modulweiter Helfer nach den Imports, vor `def open_settings_dialog`)
- Test: `tests/test_settings_dialog.py` (neu)

**Interfaces:**
- Consumes: nichts (nur stdlib `traceback` + `messagebox`, beide bereits in `settings_dialog.py` importiert)
- Produces:
  ```python
  build_oauth_enable_task(*, service_fn, settings, setting_key, checkbox,
                          toggle_var, on_change, dialog, error_title,
                          on_success_dialog_ui=None) -> tuple[fn, on_done]
  # fn() -> {"ok": True} | {"ok": False, "error": Exception, "tb": str}
  # on_done(res) -> None
  ```
  Verhalten: `fn` ruft `service_fn()`; bei Erfolg `settings.set(setting_key, True)` (überlebt Close) und `{"ok": True}`, sonst `{"ok": False, "error", "tb"}`. `on_done`: bei Erfolg `on_change()` (vor Guard); dann `if not checkbox.winfo_exists(): return`; `checkbox.config(state="normal")`; bei Erfolg `on_success_dialog_ui()` (falls gesetzt), bei Fehler `toggle_var.set(False)` + `messagebox.showerror(error_title, …, parent=dialog)`.

- [ ] **Step 1: Failing-Test-Datei anlegen**

Datei `tests/test_settings_dialog.py`:

```python
"""build_oauth_enable_task: fn/on_done-Kontrakt eines OAuth-Aktivieren-Toggles,
headless (der Dialog selbst ist Tk-gebunden, M16)."""

from unittest.mock import MagicMock

import src.dialogs.settings_dialog as sd
from src.dialogs.settings_dialog import build_oauth_enable_task


class _FakeSettings:
    def __init__(self):
        self.sets = []

    def set(self, key, value):
        self.sets.append((key, value))


class _FakeCheckbox:
    """Fake tk.Checkbutton: steuerbares winfo_exists + config-Rekorder."""
    def __init__(self, alive=True):
        self._alive = alive
        self.config_calls = []

    def winfo_exists(self):
        return self._alive

    def config(self, **kwargs):
        self.config_calls.append(kwargs)


class _FakeVar:
    def __init__(self):
        self.value = True

    def set(self, v):
        self.value = v


def _build(*, service_ok=True, alive=True, on_success_ui=None):
    settings = _FakeSettings()
    checkbox = _FakeCheckbox(alive=alive)
    var = _FakeVar()
    on_change = MagicMock()

    def service_fn():
        if not service_ok:
            raise RuntimeError("boom")

    fn, on_done = build_oauth_enable_task(
        service_fn=service_fn, settings=settings, setting_key="sync_enabled",
        checkbox=checkbox, toggle_var=var, on_change=on_change,
        dialog=object(), error_title="Titel",
        on_success_dialog_ui=on_success_ui,
    )
    return settings, checkbox, var, on_change, fn, on_done


def test_success_persists_and_updates_ui(monkeypatch):
    monkeypatch.setattr(sd.messagebox, "showerror", lambda *a, **k: None)
    ui = MagicMock()
    settings, checkbox, var, on_change, fn, on_done = _build(on_success_ui=ui)
    on_done(fn())
    assert settings.sets == [("sync_enabled", True)]
    on_change.assert_called_once_with()
    assert {"state": "normal"} in checkbox.config_calls
    ui.assert_called_once_with()
    assert var.value is True  # kein Revert


def test_success_persists_even_when_dialog_closed(monkeypatch):
    monkeypatch.setattr(sd.messagebox, "showerror", lambda *a, **k: None)
    ui = MagicMock()
    settings, checkbox, var, on_change, fn, on_done = _build(alive=False,
                                                             on_success_ui=ui)
    on_done(fn())
    assert settings.sets == [("sync_enabled", True)]   # Persistenz überlebt
    on_change.assert_called_once_with()                 # root-scoped, läuft
    assert checkbox.config_calls == []                  # kein Widget-Zugriff
    ui.assert_not_called()                              # Dialog-Kosmetik übersprungen


def test_failure_no_persist_and_reverts(monkeypatch):
    errors = []
    monkeypatch.setattr(sd.messagebox, "showerror",
                        lambda *a, **k: errors.append(a))
    settings, checkbox, var, on_change, fn, on_done = _build(service_ok=False)
    on_done(fn())
    assert settings.sets == []          # keine Persistenz bei Fehler
    on_change.assert_not_called()
    assert {"state": "normal"} in checkbox.config_calls
    assert var.value is False           # Revert
    assert errors                       # Fehler-Messagebox gezeigt


def test_failure_dialog_closed_skips_all_ui(monkeypatch):
    errors = []
    monkeypatch.setattr(sd.messagebox, "showerror",
                        lambda *a, **k: errors.append(a))
    settings, checkbox, var, on_change, fn, on_done = _build(service_ok=False,
                                                             alive=False)
    on_done(fn())
    assert settings.sets == []
    on_change.assert_not_called()
    assert checkbox.config_calls == []
    assert var.value is True            # kein Revert (Dialog weg)
    assert errors == []


def test_success_without_on_success_ui(monkeypatch):
    monkeypatch.setattr(sd.messagebox, "showerror", lambda *a, **k: None)
    settings, checkbox, var, on_change, fn, on_done = _build(on_success_ui=None)
    on_done(fn())  # darf nicht werfen
    assert settings.sets == [("sync_enabled", True)]
    assert {"state": "normal"} in checkbox.config_calls
```

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_dialog.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_oauth_enable_task'`.

- [ ] **Step 3: Builder implementieren**

In `src/dialogs/settings_dialog.py` **nach dem Import-Block** (nach Z. 30) und **vor** `def open_settings_dialog` einfügen:

```python
def build_oauth_enable_task(*, service_fn, settings, setting_key, checkbox,
                            toggle_var, on_change, dialog, error_title,
                            on_success_dialog_ui=None):
    """Baut (fn, on_done) für einen OAuth-Aktivieren-Toggle (Drive-Sync / Kalender).

    fn (Worker-Thread): ruft service_fn() und persistiert setting_key=True bei
    Erfolg — läuft im Thread und überlebt daher einen Dialog-Close. Fängt seine
    Exceptions selbst, wirft nie.

    on_done (UI-Thread via App._marshal_to_ui): ruft on_change() (App-/root-scoped)
    VOR dem winfo_exists-Guard, danach die Dialog-Kosmetik (checkbox, toggle_var,
    Messagebox, optional on_success_dialog_ui) — übersprungen, wenn der Dialog weg
    ist. on_success_dialog_ui ist Dialog-Kosmetik (z.B. Kalenderliste laden) und
    läuft daher NACH dem Guard.
    """
    def fn():
        try:
            service_fn()
        except Exception as e:
            return {"ok": False, "error": e, "tb": traceback.format_exc()}
        settings.set(setting_key, True)
        return {"ok": True}

    def on_done(res):
        if res["ok"]:
            on_change()
        if not checkbox.winfo_exists():
            return
        checkbox.config(state="normal")
        if res["ok"]:
            if on_success_dialog_ui is not None:
                on_success_dialog_ui()
        else:
            toggle_var.set(False)
            messagebox.showerror(
                error_title,
                f"OAuth-Flow fehlgeschlagen:\n\n{res['error']}\n\n{res['tb']}",
                parent=dialog,
            )

    return fn, on_done
```

- [ ] **Step 4: Test laufen lassen — muss bestehen**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_dialog.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Ruff + Commit**

Run: `.venv/Scripts/python.exe -m ruff check src/dialogs/settings_dialog.py tests/test_settings_dialog.py`
Expected: All checks passed.

```bash
git add src/dialogs/settings_dialog.py tests/test_settings_dialog.py
git commit -m "feat(settings): build_oauth_enable_task — testbarer OAuth-Toggle-Task (H5)"
```

---

## Task 2: Runner verdrahten + #2/#6 auf den Builder umstellen

`open_settings_dialog` bekommt den `runner`-Parameter, `ui.py` reicht `self._bg` durch, und die zwei OAuth-Aktivieren-Toggles nutzen `build_oauth_enable_task` + `runner.run`. Die alten `_finish_oauth`/`_finish_gcal_oauth`-Callbacks und ihre Threads entfallen.

**Files:**
- Modify: `src/dialogs/settings_dialog.py` (Signatur; `_on_sync_toggled`; `_on_gcal_toggled`; Löschen von `_finish_oauth`, `_finish_gcal_oauth`)
- Modify: `src/ui.py:356-365` (Aufruf um `runner=self._bg` ergänzen)

**Interfaces:**
- Consumes: `build_oauth_enable_task(...)` aus Task 1; `App._bg` (bestehender `BackgroundTaskRunner` mit `.run(fn, on_done)`)
- Produces: `open_settings_dialog(parent, settings, base_path, on_change, *, runner, conflicts_store=None, storage=None, reservation_store=None, on_request_restart=None, data_lock=None, sync_guard=None)` — `runner` ist **required keyword-only**.

- [ ] **Step 1: Signatur um `runner` erweitern**

In `src/dialogs/settings_dialog.py` die Signatur (aktuell Z. 33-36) ändern zu:

```python
def open_settings_dialog(parent, settings, base_path, on_change, *,
                         runner, conflicts_store=None, storage=None,
                         reservation_store=None, on_request_restart=None,
                         data_lock=None, sync_guard=None):
```

Und den Docstring-Absatz (nach „…von App durchgereicht.") um eine Zeile ergänzen:

```
    runner: der App-BackgroundTaskRunner (App._bg); alle Hintergrund-Worker des
    Dialogs laufen über runner.run(fn, on_done) (Audit H5).
```

- [ ] **Step 2: Aufrufer in `ui.py` anpassen**

In `src/ui.py` den Aufruf (Z. 356-365) um `runner=self._bg,` ergänzen:

```python
        open_settings_dialog(
            self.root, self.settings, self.base_path,
            on_change=_on_change,
            runner=self._bg,
            conflicts_store=self.conflicts_store,
            storage=self.storage,
            reservation_store=self.reservation_store,
            on_request_restart=self.restart_for_scaling,
            data_lock=self._data_lock,
            sync_guard=self._sync_guard,
        )
```

- [ ] **Step 3: #2 Drive-Sync-Toggle umstellen**

In `src/dialogs/settings_dialog.py` die Funktion `_finish_oauth` (aktuell Z. 343-355) **löschen** und `_on_sync_toggled` (aktuell Z. 357-382) ersetzen durch:

```python
    def _on_sync_toggled():
        assert cb_sync is not None
        new_state = var_sync.get()
        if new_state and not settings.get("sync_enabled"):
            cb_sync.config(state="disabled")

            def _service():
                from src import drive
                drive.get_drive_service(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )

            fn, on_done = build_oauth_enable_task(
                service_fn=_service, settings=settings,
                setting_key="sync_enabled", checkbox=cb_sync,
                toggle_var=var_sync, on_change=on_change, dialog=dialog,
                error_title="Synchronisation aktivieren",
            )
            runner.run(fn, on_done)
            return
        if not new_state and settings.get("sync_enabled"):
            settings.set("sync_enabled", False)
            on_change()
```

Hinweis: `cb_sync` ist ein echtes `tk.Checkbutton` — `config(state="disabled")` ist hier gültig (anders als beim icon_button). Diese synchrone Vor-Deaktivierung bleibt im Toggle-Handler.

- [ ] **Step 4: #6 Kalender-Toggle umstellen**

`_finish_gcal_oauth` (aktuell Z. 645-660) **löschen** und `_on_gcal_toggled` (aktuell Z. 662-685) ersetzen durch:

```python
    def _on_gcal_toggled():
        assert cb_gcal is not None
        new_state = var_gcal.get()
        if new_state and not settings.get("gcal_enabled"):
            cb_gcal.config(state="disabled")

            def _service():
                from src import gcal
                gcal.get_calendar_service(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    sync_enabled=settings.get("sync_enabled"),
                )

            fn, on_done = build_oauth_enable_task(
                service_fn=_service, settings=settings,
                setting_key="gcal_enabled", checkbox=cb_gcal,
                toggle_var=var_gcal, on_change=on_change, dialog=dialog,
                error_title="Google Kalender aktivieren",
                on_success_dialog_ui=_load_calendars,
            )
            runner.run(fn, on_done)
            return
        if not new_state and settings.get("gcal_enabled"):
            settings.set("gcal_enabled", False)
            on_change()
```

`_load_calendars` ist oberhalb bereits definiert (aktuell Z. 611) und damit im Closure sichtbar.

- [ ] **Step 5: Gesamtsuite + Ruff**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: alle grün (bestehende Zahl + 5 aus Task 1), keine Fehler.

Run: `.venv/Scripts/python.exe -m ruff check .`
Expected: All checks passed.

- [ ] **Step 6: Commit**

```bash
git add src/dialogs/settings_dialog.py src/ui.py
git commit -m "refactor(settings): #2/#6 OAuth-Toggles über runner.run; Persistenz überlebt Close (H5)"
```

---

## Task 3: Restliche Worker migrieren, `import threading` entfernen, Doku

Die vier verbleibenden Worker (#1 Absender-Mail, #3 Neu verbinden, #4 Kompaktierung, #5 Kalenderliste) auf `runner.run` umstellen, den nun unbenutzten `import threading` entfernen und `src/CLAUDE.md` aktualisieren. #1 zieht `settings.set("sender_email", …)` in den Worker.

**Files:**
- Modify: `src/dialogs/settings_dialog.py` (`_refresh_sender`/#1, `_reconnect_google`/#3, `_on_compact_clicked`/#4, `_load_calendars`/#5; `_finish_refresh_ok`, `_finish_refresh_error`, `_finish_reconnect`, `_load_calendars_error` löschen/einfalten; `import threading` entfernen)
- Modify: `src/CLAUDE.md:92`

**Interfaces:**
- Consumes: `runner` (Signatur aus Task 2), `_run_compaction_blocking` (lazy aus `src.main`), `_populate_calendars` (bestehender Helfer, bleibt)
- Produces: nichts Neues (interne Umstellung)

- [ ] **Step 1: #1 Absender-Mail (`_refresh_sender`) umstellen**

`_refresh_sender` (aktuell Z. 265-299) den Thread-Block ersetzen und `_finish_refresh_ok`/`_finish_refresh_error` (Z. 301-319) **löschen**. Neu — ab `_set_sender_btn_text("Verbinde…")`:

```python
        _set_sender_btn_text("Verbinde…")

        def _fn():
            from src.mail import fetch_user_email, get_gmail_service
            try:
                get_gmail_service(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    sync_enabled=settings.get("sync_enabled"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
                email = fetch_user_email(
                    os.path.join(base_path, "token.json"),
                    sync_enabled=settings.get("sync_enabled"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
            except Exception as e:
                return {"ok": False, "error": e, "tb": traceback.format_exc()}
            if email:
                settings.set("sender_email", email)   # Cache überlebt Close
            return {"ok": True, "email": email}

        def _on_done(res):
            if not sender_label.winfo_exists():
                return
            _set_sender_btn_text("Aktualisieren")
            if not res["ok"]:
                messagebox.showerror(
                    "Anmeldung fehlgeschlagen",
                    "OAuth-Flow oder Userinfo-Aufruf fehlgeschlagen:\n\n"
                    f"{res['error']}\n\n{res['tb']}",
                    parent=dialog,
                )
                return
            email = res["email"]
            sender_label.config(
                text=email if email
                else "(nicht verfügbar — Scope fehlt evtl.)")

        runner.run(_fn, _on_done)
```

Der `import`-Zeilenkopf von `_refresh_sender` (aktuell Z. 267-268 `from src.dialogs.send_dialog import …` / `from src.mail import …`) bleibt für den synchronen `show_missing_credentials_dialog`-Pfad wie gehabt; der `from src.mail import …` dort wird nicht mehr gebraucht (er steht jetzt im `_fn`) — entferne die `from src.mail import fetch_user_email, get_gmail_service`-Zeile aus `_refresh_sender`, die `from src.dialogs.send_dialog import show_missing_credentials_dialog`-Zeile bleibt.

- [ ] **Step 2: #3 Google-neu-verbinden (`_reconnect_google`) umstellen**

`_finish_reconnect` (aktuell Z. 448-463) **löschen** und den Thread-Block in `_reconnect_google` (aktuell Z. 477-490, ab `def _do():`) ersetzen durch:

```python
        def _fn():
            from src import drive
            try:
                drive.reconnect(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
            except Exception as e:
                return {"ok": False, "error": e, "tb": traceback.format_exc()}
            return {"ok": True}

        def _on_done(res):
            reconnect_busy["value"] = False
            if not dialog.winfo_exists():
                return
            if res["ok"]:
                themed_showinfo(
                    dialog, "Google neu verbunden",
                    "Die Google-Berechtigungen wurden erneuert. Die "
                    "Synchronisation sollte jetzt wieder funktionieren.",
                )
                return
            messagebox.showerror(
                "Google neu verbinden",
                "Die Neuverbindung ist fehlgeschlagen:\n\n"
                f"{res['error']}\n\n{res['tb']}",
                parent=dialog,
            )

        runner.run(_fn, _on_done)
```

- [ ] **Step 3: #4 Kompaktierung (`_on_compact_clicked`) umstellen**

Den Thread-Block (aktuell Z. 549-556, `def _do(): … threading.Thread(...)`) ersetzen durch:

```python
            def _fn():
                from src.main import _run_compaction_blocking
                return _run_compaction_blocking(
                    storage, settings, conflicts_store, base_path,
                    data_lock=data_lock, sync_guard=sync_guard)

            runner.run(_fn, _show)
```

`_show(res)` (aktuell Z. 513-547) bleibt unverändert — es ist bereits `winfo_exists`-geschützt und dient direkt als `on_done`.

- [ ] **Step 4: #5 Kalenderliste (`_load_calendars`) umstellen**

`_load_calendars` (aktuell Z. 611-634) den Thread-Block ersetzen und `_load_calendars_error` (aktuell Z. 636-643) **löschen** (in `_on_done` eingefaltet). `_populate_calendars` (aktuell Z. 597-609) **bleibt**. Neu:

```python
    def _load_calendars():
        cal_status.config(text="Kalenderliste wird geladen…")

        def _fn():
            from src import gcal
            try:
                service = gcal.get_calendar_service(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    sync_enabled=settings.get("sync_enabled"),
                )
                items = gcal.list_calendars(service)
            except Exception as e:
                return {"ok": False, "error": e, "tb": traceback.format_exc()}
            return {"ok": True, "items": items}

        def _on_done(res):
            if not cal_status.winfo_exists():
                return
            if not res["ok"]:
                cal_status.config(text="Kalenderliste nicht verfügbar")
                messagebox.showerror(
                    "Google Kalender",
                    "Kalenderliste konnte nicht geladen werden:\n\n"
                    f"{res['error']}\n\n{res['tb']}",
                    parent=dialog,
                )
                return
            _populate_calendars(res["items"])

        runner.run(_fn, _on_done)
```

- [ ] **Step 5: `import threading` entfernen + verifizieren**

Prüfen, dass kein `threading`-Bezug mehr übrig ist:

Run: `.venv/Scripts/python.exe -m pytest -q` — noch nichts geändert außer Steps 1-4; hier nur als Zwischenlauf optional.

Dann `import threading` (aktuell Z. 5) in `src/dialogs/settings_dialog.py` löschen. Verifikation:

Run (Bash): `grep -n "threading" src/dialogs/settings_dialog.py`
Expected: keine Ausgabe (leer).

- [ ] **Step 6: `src/CLAUDE.md` aktualisieren**

In `src/CLAUDE.md` den Satz (Z. 91-92):

```
gegen `TclError` abgesichert, falls das Fenster zwischenzeitlich zu ist). Keine direkten
`threading.Thread`-Aufrufe in `ui.py` mehr.
```

ersetzen durch:

```
gegen `TclError` abgesichert, falls das Fenster zwischenzeitlich zu ist). Keine direkten
`threading.Thread`-Aufrufe in `ui.py` **oder den Dialogen** mehr — auch `settings_dialog`
routet seine Worker seit Audit H5 über einen injizierten `BackgroundTaskRunner`
(`open_settings_dialog(..., runner=App._bg)`): Persistenz im Worker (überlebt
Dialog-Close), UI-Feedback im `winfo_exists`-geschützten `on_done`.
```

- [ ] **Step 7: Gesamtsuite + Ruff**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: alle grün.

Run: `.venv/Scripts/python.exe -m ruff check .`
Expected: All checks passed.

- [ ] **Step 8: Manueller Tk-Smoke (Sichtprüfung der Verdrahtung)**

Da die Verdrahtung Tk-gebunden ist, einmal den Dialog real öffnen:

Run: `.venv/Scripts/python.exe -m src.main`
Prüfen: Einstellungen öffnen → Google-Tab → „Aktualisieren" (Absender) löst Fetch aus ohne Crash; Dialog schließen und erneut öffnen funktioniert. (OAuth-Toggles nur prüfen, falls `credentials.json` vorhanden — sonst kommt der freundliche Hinweis, ebenfalls ok.)

- [ ] **Step 9: Commit**

```bash
git add src/dialogs/settings_dialog.py src/CLAUDE.md
git commit -m "refactor(settings): restliche Worker über runner.run, import threading raus, Doku (H5)"
```

---

## Self-Review-Notiz (bereits geprüft)

- **Spec-Abdeckung:** alle 6 Worker (Task 2: #2/#6; Task 3: #1/#3/#4/#5), Builder + Tests (Task 1), Persistenz-im-Worker (#2/#6/#1), `on_change`-vor-Guard, `_load_calendars` hinter Guard (Task 2 Step 4 via `on_success_dialog_ui`), `import threading`-Entfernung + Doku (Task 3), `after(500)`-Timer bewusst unangetastet.
- **Signatur-Konsistenz:** `build_oauth_enable_task(...)` identisch in Task 1 (Definition) und Task 2 (Aufruf #2/#6); Result-Dict `{"ok", "error", "tb"}` durchgängig; `runner`-Param in Task 2 eingeführt, in Task 3 genutzt.
- **Reihenfolge-Abhängigkeit:** Task 1 → 2 → 3 (Task 2 führt `runner` ein, Task 3 nutzt es; `import threading` fällt erst in Task 3, wenn alle Worker migriert sind).
