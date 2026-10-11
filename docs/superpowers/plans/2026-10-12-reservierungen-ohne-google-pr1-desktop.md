# Reservierungen ohne Google — PR 1: Desktop entkoppeln

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reservierungen am Desktop hängen an einer eigenen Einstellung `reservations_enabled` statt an `gcal_enabled`; der Google-Kalender-Abgleich wird ein reiner Zusatz.

**Architecture:** Ein Tk-freies Gate `reservations.reservations_active(store, settings)` ersetzt die Prüfung auf `gcal_enabled` in `App._reservations_active`. Der Kalender-Push bekommt ein eigenes Gate (`gcal_enabled`) und reicht den Reservierungs-Store nur an `run_calendar_reconcile`, wenn Reservierungen an sind (sonst läuft nur der Urlaub-Push). Eine einmalige Migration setzt `reservations_enabled` für alle, die `gcal_enabled` schon an haben.

**Tech Stack:** Python 3.12, Tkinter, pytest. Reihenfolge der PRs: dies ist PR 1 von 3 (PR 2: Protokoll/Merge am Desktop, PR 3: PWA; eigene Pläne, nachdem dieser gemerged ist).

**Spec:** `docs/superpowers/specs/2026-10-12-reservierungen-ohne-google-design.md` (Abschnitt „PR 1")

## Global Constraints

- Neue Einstellungen sind **gerätelokal**: nicht in `SYNCED_SETTING_KEYS`.
- `reservations_enabled` Default `False`; Migration setzt es einmalig, wenn `gcal_enabled` an ist; Marker `reservations_migrated` wird **immer** gesetzt.
- Urlaub bleibt unabhängig von Reservierungen (`vacation_gcal_enabled`, nur `gcal_enabled` + Kalenderwahl).
- Catch-all-Regel: jeder `except Exception` loggt (`tests/test_catch_all_handlers.py`).
- Tk-freie Module in `tests/test_type_annotations.py` (u. a. `src/reservations.py`) werden **vollständig** annotiert.
- Neue UI-Texte auf Deutsch; Tk-Code wird nicht automatisiert getestet, die Logik liegt Tk-frei.
- Windows-PowerShell 5.1: keine `&&` in Befehlen; `;` oder `if ($?) { … }`.
- README: neue Features bekommen `*(ab --VERSION--)*` am fetten Namen. Kein Versionsbump, kein CHANGELOG in diesem PR (das gehört in den Release-PR).
- Arbeitsbranch: `feat/reservierungen-ohne-google` (nicht auf `master` committen).

## Review Focus

- Bestehender Nutzer mit `gcal_enabled=True`: nach dem Update sind seine Reservierungen weiter sichtbar (Migration) — Test in Task 1.
- Nutzer mit `gcal_enabled=False` und vorhandenen `reservations.json`-Daten: nach dem Update **keine** plötzlich sichtbaren Reservierungen (Default aus) — Test in Task 1.
- Kalender an, Reservierungen aus: der Abgleich importiert **keine** Kalender-Events in den (unsichtbaren) Store, der Urlaub-Push läuft weiter — Test in Task 2.
- Reservierungen an, Kalender aus: nichts wird gepusht, kein Fehlerdialog „Google-Verbindung abgelaufen" — Test in Task 2.
- Reservierungen aus, `reminders_enabled`/Sende-Erinnerung an: kein Toast für unsichtbare Reservierungen — Tests in Task 3.

---

## File Structure

| Datei | Änderung |
|---|---|
| `src/settings.py` | Defaults `reservations_enabled`, `reservations_migrated` |
| `src/reservations.py` | `reservations_active`, `migrate_reservations_enabled` (Tk-frei, annotiert) |
| `src/main.py` | Migration beim Start |
| `src/ui.py` | Gate, Kalender-Gate, Helfer `_active_reservation_store`, Aufrufstellen |
| `src/background_tasks.py` | Parameter `calendar_active`, `_reconcile_store()` |
| `src/sync_runtime.py` | `run_calendar_reconcile` verträgt `reservation_store=None` |
| `src/reminder_scheduler.py`, `src/send_reminder_scheduler.py` | Gate `reservations_enabled` |
| `src/dialogs/settings_dialog/tab_work.py`, `tab_rules.py` | Schalter „Reservierungen verwenden" |
| `src/dialogs/settings_dialog/tab_reminders.py` | Reservierungs-Abschnitte nur bei aktivem Schalter |
| `src/dialogs/settings_dialog/tab_google.py`, `src/dialogs/import_dialog.py` | Texte |
| `scripts/demo_data.py`, `README.md`, `CLAUDE.md`, `src/CLAUDE.md` | Doku |
| Tests | `tests/test_reservations.py`, `test_background_tasks.py`, `test_background_idle.py`, `test_sync_runtime_calendar.py`, `test_reminder_scheduler.py`, `test_send_reminder_scheduler.py`, `test_tab_rules.py`, `test_settings.py` |

---

### Task 0: Branch

- [ ] **Step 1: Branch anlegen und Spec + Plan committen**

```powershell
git checkout -b feat/reservierungen-ohne-google
git add docs/superpowers/specs/2026-10-12-reservierungen-ohne-google-design.md docs/superpowers/plans/2026-10-12-reservierungen-ohne-google-pr1-desktop.md
git commit -m "docs: Spec und Plan für Reservierungen ohne Google"
```

(Commit-Message-Footer laut Session-Vorgabe anhängen; mehrzeilige Messages per `git commit -F <Datei>`.)

---

### Task 1: Einstellungen, Gate-Funktion, Migration

**Files:**
- Modify: `src/settings.py` (nach `"gcal_calendar_id"`/`"last_calendar_sync_at"`, vor `"categories"`)
- Modify: `src/reservations.py` (Funktionen am Dateiende)
- Modify: `src/main.py:348-352` (Block nach dem Tombstone-Sweep)
- Test: `tests/test_reservations.py` (ggf. neue Datei, falls sie nicht existiert), `tests/test_settings.py`

**Interfaces:**
- Produces: `reservations_active(store: Any, settings: Any) -> bool`; `migrate_reservations_enabled(settings: Any) -> None`; Setting-Keys `reservations_enabled: bool`, `reservations_migrated: bool`.

- [ ] **Step 1: Failing tests schreiben** (`tests/test_reservations.py` ergänzen, Imports oben dazunehmen)

```python
from src.reservations import (
    migrate_reservations_enabled, reservations_active,
)
from src.settings import SYNCED_SETTING_KEYS, Settings


def test_reservations_enabled_is_off_by_default_and_device_local(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    assert settings.get("reservations_enabled") is False
    assert settings.get("reservations_migrated") is False
    assert "reservations_enabled" not in SYNCED_SETTING_KEYS
    assert "reservations_migrated" not in SYNCED_SETTING_KEYS


def test_reservations_active_needs_store_and_switch(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    store = object()
    assert reservations_active(store, settings) is False
    settings.set("reservations_enabled", True)
    assert reservations_active(store, settings) is True
    assert reservations_active(None, settings) is False


def test_reservations_active_ignores_gcal(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    settings.set("gcal_enabled", True)
    assert reservations_active(object(), settings) is False


def test_migration_turns_reservations_on_for_calendar_users(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    settings.set("gcal_enabled", True)
    migrate_reservations_enabled(settings)
    assert settings.get("reservations_enabled") is True
    assert settings.get("reservations_migrated") is True


def test_migration_leaves_users_without_calendar_off(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    migrate_reservations_enabled(settings)
    assert settings.get("reservations_enabled") is False
    assert settings.get("reservations_migrated") is True


def test_migration_runs_only_once(tmp_path):
    """Wer Reservierungen später bewusst ausschaltet, behält das — auch wenn
    der Kalender an ist."""
    settings = Settings(str(tmp_path / "settings.json"))
    settings.set("gcal_enabled", True)
    migrate_reservations_enabled(settings)
    settings.set("reservations_enabled", False)
    migrate_reservations_enabled(settings)
    assert settings.get("reservations_enabled") is False


def test_migration_persists(tmp_path):
    path = str(tmp_path / "settings.json")
    settings = Settings(path)
    settings.set("gcal_enabled", True)
    migrate_reservations_enabled(settings)
    again = Settings(path)
    assert again.get("reservations_enabled") is True
    assert again.get("reservations_migrated") is True
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/test_reservations.py -k "reservations_active or migration or enabled_is_off" -v`
Expected: FAIL (`ImportError: cannot import name 'migrate_reservations_enabled'`)

- [ ] **Step 3: Defaults ergänzen** (`src/settings.py`, direkt nach `"last_calendar_sync_at": "",`)

```python
    # Reservierungen verwenden (zukünftige Soll-Zeiten). Bis dahin hingen sie an
    # gcal_enabled; jetzt ist der Kalender-Abgleich ein Zusatz. Gerätelokal
    # (NICHT in SYNCED_SETTING_KEYS): wie gcal_enabled eine Entscheidung dieses
    # Rechners. `reservations_migrated` merkt die einmalige Umstellung
    # (reservations.migrate_reservations_enabled).
    "reservations_enabled": False,
    "reservations_migrated": False,
```

- [ ] **Step 4: Funktionen ergänzen** (`src/reservations.py`, am Ende; `Any` ist dort bereits importiert)

```python
def reservations_active(store: Any, settings: Any) -> bool:
    """True, wenn Reservierungen angezeigt und bearbeitet werden dürfen: ein
    Store existiert UND der Nutzer hat sie eingeschaltet. Unabhängig vom
    Google-Kalender — der ist nur ein optionaler Abgleich."""
    return store is not None and bool(settings.get("reservations_enabled"))


def migrate_reservations_enabled(settings: Any) -> None:
    """Einmalige Umstellung beim Start: wer den Kalender-Abgleich an hatte, sah
    bisher Reservierungen und behält sie. Der Marker wird auch ohne
    Umstellung gesetzt — ein später bewusst ausgeschalteter Schalter wird nie
    wieder überschrieben."""
    if settings.get("reservations_migrated"):
        return
    updates: dict[str, Any] = {"reservations_migrated": True}
    if settings.get("gcal_enabled"):
        updates["reservations_enabled"] = True
    settings.set_many(updates)
```

- [ ] **Step 5: Tests grün**

Run: `pytest tests/test_reservations.py tests/test_settings.py tests/test_type_annotations.py -v`
Expected: PASS

- [ ] **Step 6: Migration im Start verdrahten** (`src/main.py`, direkt **vor** dem `# N6: Tombstones …`-Kommentar; Import oben bei den übrigen `src.reservations`-Imports: `from src.reservations import ReservationStore, migrate_reservations_enabled`)

```python
    # Reservierungen hingen bis dahin an gcal_enabled (einmalige Umstellung,
    # s. reservations.migrate_reservations_enabled). Nicht-fatal wie die
    # übrigen Startschritte: ein Schreibfehler darf den Start nicht verhindern.
    try:
        migrate_reservations_enabled(settings)
    except Exception:
        logging.getLogger(__name__).exception(
            "Reservierungs-Umstellung fehlgeschlagen (nicht-fatal)")
```

Prüfe vorher mit `Grep "ReservationStore" src/main.py`, wie der Import dort geschrieben ist, und erweitere genau diese Zeile.

- [ ] **Step 7: Gesamte Suite für main/settings**

Run: `pytest tests/test_main.py tests/test_settings.py tests/test_catch_all_handlers.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```powershell
git add src/settings.py src/reservations.py src/main.py tests/test_reservations.py
git commit -m "feat(reservierungen): eigener Schalter reservations_enabled mit Migration"
```

---

### Task 2: App-Gate, Kalender-Gate und Reconcile ohne Reservierungen

**Files:**
- Modify: `src/sync_runtime.py:370-435` (`run_calendar_reconcile`)
- Modify: `src/background_tasks.py:26-42, 217-266`
- Modify: `src/ui.py:311-317, 112-117, 583-589, 561-567, 932-956`
- Test: `tests/test_sync_runtime_calendar.py`, `tests/test_background_tasks.py`, `tests/test_background_idle.py`

**Interfaces:**
- Consumes: `reservations_active` (Task 1).
- Produces: `run_calendar_reconcile(reservation_store=None, …)` überspringt den Reservierungs-Abgleich; `BackgroundTaskRunner(…, calendar_active=<callable -> bool>)` (ersetzt `reservations_active`); `App._active_reservation_store() -> store | None`.

- [ ] **Step 1: Failing tests** (`tests/test_sync_runtime_calendar.py`, nach `test_vacation_push_is_skipped`; `sync_history` ist dort bereits importiert)

```python
def test_reconcile_without_reservation_store_pushes_only_vacation(fake_calendar, tmp_path):
    """Kalender an, Reservierungen aus: nichts wird in den (unsichtbaren)
    Reservierungs-Store importiert, der Urlaub-Push läuft trotzdem."""
    store, pid = _vacation_store(tmp_path)
    result = run_calendar_reconcile(
        None, _settings(tmp_path), str(tmp_path),
        Storage(str(tmp_path / "entries.json")), vacation_store=store)

    assert result["ok"] is True
    assert result["limit_warnings"] == []
    assert "list_app_events" not in fake_calendar.calls
    assert len(fake_calendar.created_vacations) == 1
    assert not sync_history.ever_reconciled(str(tmp_path))


def test_reconcile_with_reservation_store_still_marks_reconciled(fake_calendar, tmp_path):
    result = _reconcile(tmp_path, _settings(tmp_path), None)
    assert result["ok"] is True
    assert "list_app_events" in fake_calendar.calls
    assert sync_history.ever_reconciled(str(tmp_path))
```

`tests/test_background_tasks.py`: Helfer `_runner` umbenennen (`reservations_active` → `calendar_active`) und neue Tests ergänzen. Ersetze Zeile 25 durch
`calendar_active=overrides.pop("calendar_active", lambda: False),` und in den Tests an den Zeilen 173-176, 212, 235 `reservations_active=` → `calendar_active=` (Testname `test_reconcile_on_start_skips_when_reservations_inactive` → `…_when_calendar_inactive`). Neu:

```python
def _capturing_reconcile(captured):
    def fake_reconcile(reservation_store, settings, base_path, storage,
                       data_lock=None, vacation_store=None):
        captured["store"] = reservation_store
        return {"ok": True, "error": "", "tb": "", "limit_warnings": []}
    return fake_reconcile


def test_trigger_reconcile_passes_store_only_when_reservations_enabled(monkeypatch):
    import src.background_tasks as bt_module

    sentinel = object()
    for enabled, expected in ((True, sentinel), (False, None)):
        captured = {}
        monkeypatch.setattr(bt_module, "run_calendar_reconcile",
                            _capturing_reconcile(captured))
        done = threading.Event()
        r = _runner(calendar_active=lambda: True, reservation_store=sentinel,
                    settings={"reservations_enabled": enabled})
        r.trigger_reconcile(lambda result: done.set())
        assert done.wait(timeout=5)
        assert captured["store"] is expected


def test_reconcile_on_start_passes_store_only_when_reservations_enabled(monkeypatch):
    import src.background_tasks as bt_module

    sentinel = object()
    for enabled, expected in ((True, sentinel), (False, None)):
        captured = {}
        monkeypatch.setattr(bt_module, "run_calendar_reconcile",
                            _capturing_reconcile(captured))
        got = threading.Event()
        r = _runner(calendar_active=lambda: True, reservation_store=sentinel,
                    settings={"reservations_enabled": enabled})
        r.reconcile_on_start(on_ok=lambda result: got.set())
        assert got.wait(timeout=5)
        assert captured["store"] is expected
```

`tests/test_background_idle.py:12`: `reservations_active=lambda: False` → `calendar_active=lambda: False`.

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/test_sync_runtime_calendar.py tests/test_background_tasks.py tests/test_background_idle.py -q`
Expected: FAIL (`TypeError … unexpected keyword argument 'calendar_active'`, bzw. `None` im Reconcile)

- [ ] **Step 3: `run_calendar_reconcile` anpassen** (`src/sync_runtime.py`)

Docstring-Zeile 372/375 ergänzen: „`reservation_store=None` überspringt den Reservierungs-Abgleich (Reservierungen aus, Kalender an); der Urlaub-Push läuft trotzdem." Dann den Block `result = reconcile_reservations(…) … limit_warnings = …` ersetzen durch:

```python
        limit_warnings: list = []
        if reservation_store is not None:
            result = reconcile_reservations(service, calendar_id, reservation_store,
                                            settings, data_lock=data_lock)
            sync_history.mark_reconciled(base)
            limit_warnings = check_dates_for_warnings(
                settings, storage.get_all(), result["imported_dates"])
```

(Der Rest — Urlaub-Push und `return` — bleibt unverändert.)

- [ ] **Step 4: `BackgroundTaskRunner` anpassen** (`src/background_tasks.py`)

Konstruktor: Parameter `reservations_active` → `calendar_active`, Zeile `self._reservations_active = reservations_active  # callable -> bool` → `self._calendar_active = calendar_active  # callable -> bool (Google-Kalender aktiv)`; Kommentar in Zeilen 37-41 sinngemäß anpassen (Positionsreihenfolge bleibt!). Neue Methode:

```python
    def _reconcile_store(self):
        """Reservierungs-Store für den Kalender-Abgleich — `None`, wenn
        Reservierungen aus sind: der Abgleich darf dann nichts in einen Store
        importieren, den die App nicht zeigt. Der Urlaub-Push läuft trotzdem."""
        if self._settings.get("reservations_enabled"):
            return self._reservation_store
        return None
```

In `reconcile_on_start` und `trigger_reconcile`: `if not self._reservations_active():` → `if not self._calendar_active():` und `self._reservation_store` im `run_calendar_reconcile`-Aufruf → `self._reconcile_store()`. Docstrings: „Gleicht beim Start den Google Kalender ab (Reservierungen, sofern an, und Urlaub)". Den Verweis in `purge_vacations` („Bewusst NICHT an `_reservations_active` gehängt") auf `_calendar_active` ändern.

- [ ] **Step 5: `App` anpassen** (`src/ui.py`)

Import ergänzen: `from src.reservations import reservations_active` (zu den vorhandenen `src.`-Imports sortiert einfügen). Ersetze `_reservations_active` (Zeilen 311-317) durch:

```python
    def _reservations_active(self):
        """True, wenn Reservierungen angezeigt/bearbeitet werden dürfen: ein
        Store existiert UND der Nutzer hat sie in den Einstellungen
        eingeschaltet (`reservations_enabled`). Unabhängig vom Google-Kalender
        — der gleicht sie nur optional ab."""
        return reservations_active(self.reservation_store, self.settings)

    def _active_reservation_store(self):
        """Der Reservierungs-Store für Dialoge — `None`, wenn Reservierungen
        aus sind (dann zeigen und prüfen die Dialoge keine)."""
        return self.reservation_store if self._reservations_active() else None

    def _calendar_push_active(self):
        """True, wenn der Google-Kalender-Abgleich läuft (Reservierungen,
        sofern an, und Urlaub)."""
        return bool(self.settings.get("gcal_enabled"))
```

`BackgroundTaskRunner(…)` (Zeile 112-114): `self._reservations_active` → `self._calendar_push_active`. `_on_vacation_change`-Docstring: „`trigger_reconcile` gatet auf `_calendar_push_active` (== gcal_enabled) — ohne Kalender-Sync ein No-op." In `_open_settings` (Zeile 567): `reservation_store=self.reservation_store,` → `reservation_store=self._active_reservation_store(),`. In `_open_dialog` (938-939): `reservation_store=(self.reservation_store if self._reservations_active() else None),` → `reservation_store=self._active_reservation_store(),`; der Kommentar darüber: „Bei ausgeschalteten Reservierungen KEIN reservation_store …". `_send` (945) und `_share` (954): `reservation_store=self.reservation_store` → `reservation_store=self._active_reservation_store()`. `_delete_day` (795-798) darf `self._reservations_active()` weiter benutzen; Docstring-Zeile 787-789 unverändert gültig.

- [ ] **Step 6: Tests grün + Nachbarn**

Run: `pytest tests/test_sync_runtime_calendar.py tests/test_background_tasks.py tests/test_background_idle.py tests/test_main.py tests/test_ui_delete.py tests/test_grid_renderer.py tests/test_grid_geometry.py -q`
Expected: PASS. Schlägt ein Test in `test_ui_*`/`test_main.py` wegen `_reservations_active`/`gcal_enabled` fehl, setzt er `gcal_enabled=True` als Stand-in für „Reservierungen an": auf `reservations_enabled=True` umstellen (`Grep "gcal_enabled" tests/` zeigt die Stellen; die in `test_gcal.py`, `test_mail.py`, `test_drive.py`, `test_google_tab_task.py` betreffen den Kalender selbst und bleiben).

- [ ] **Step 7: Commit**

```powershell
git add src/sync_runtime.py src/background_tasks.py src/ui.py tests/
git commit -m "feat(reservierungen): App-Gate über reservations_enabled, Kalender-Abgleich als Zusatz"
```

---

### Task 3: Erinnerungs-Scheduler

**Files:**
- Modify: `src/reminder_scheduler.py:60-84`, `src/send_reminder_scheduler.py:107-116`
- Test: `tests/test_reminder_scheduler.py`, `tests/test_send_reminder_scheduler.py`

**Interfaces:**
- Consumes: Setting `reservations_enabled` (Task 1).

- [ ] **Step 1: Failing tests**

`tests/test_reminder_scheduler.py`: `_make` bekommt einen Parameter und das Setting (ersetze die Funktion):

```python
def _make(reservation_by_date, entry_by_date, tray, minutes=15, enabled=True):
    settings = {"reminder_minutes_before": minutes, "reservations_enabled": enabled}
    return ReminderScheduler(
        root=None,
        settings=type("S", (), {"get": staticmethod(lambda k: settings[k])})(),
        storage=_FakeStore(entry_by_date),
        reservation_store=_FakeStore(reservation_by_date),
        get_tray=lambda: tray,
    )
```

und ergänzen:

```python
def test_poll_is_silent_when_reservations_are_off():
    tray = _FakeTray()
    sched = _make(
        {"2026-07-02": {"slots": [{"start": "09:00", "end": "17:00", "kategorie": "A"}]}},
        {}, tray, enabled=False)
    assert sched.poll(_now(16, 50)) == []
    assert tray.messages == []
```

`tests/test_send_reminder_scheduler.py`: in `_DEFAULTS` Zeile 20 `"gcal_enabled": False,` → `"reservations_enabled": False,`; in allen Tests, die `"gcal_enabled": True` setzen (Zeilen 127, 138, 155, 188 und `no_gcal` ab 166), `gcal_enabled` → `reservations_enabled`; `test_day_reminder_needs_both_switches` umbenennen in `…_needs_both_switches` beibehalten, die Variable `no_gcal` → `no_reservations`. Danach zusätzlich:

```python
def test_day_reminder_does_not_need_the_calendar():
    tray = _FakeTray()
    sched = _make({"send_reminder_reservations_enabled": True,
                   "reservations_enabled": True,
                   "send_reminder_last_fired_month": "2026-07"},
                  tray, _res_store("2026-07-15", "17:00", 15))
    assert sched.poll(_now(15, 16, 45)) is True
```

(`_DEFAULTS` enthält `gcal_enabled` dann nicht mehr — der Test belegt, dass der Scheduler den Key nicht liest: `_FakeSettings.get` würde sonst `KeyError` werfen.)

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/test_reminder_scheduler.py tests/test_send_reminder_scheduler.py -q`
Expected: FAIL (u. a. `KeyError: 'gcal_enabled'` und der Toast bei ausgeschalteten Reservierungen)

- [ ] **Step 3: `ReminderScheduler.poll` gaten** (`src/reminder_scheduler.py`, direkt nach dem `tray is None`-Return)

```python
        if not self._settings.get("reservations_enabled"):
            return []
```

- [ ] **Step 4: `SendReminderScheduler._poll_day` anpassen** (`src/send_reminder_scheduler.py`)

Docstring: „… UND eingeschaltete Reservierungen (`reservations_enabled`): ohne sie zeigt die App keine Reservierungen an (`App._reservations_active`), ein Toast dafür wäre nicht nachvollziehbar." und die Bedingung:

```python
        if not (self._settings.get("send_reminder_reservations_enabled")
                and self._settings.get("reservations_enabled")):
            return False
```

Auch den Modul-Docstring (Zeile 13: „… als auch `gcal_enabled` gesetzt sind") entsprechend auf `reservations_enabled` ändern.

- [ ] **Step 5: Tests grün**

Run: `pytest tests/test_reminder_scheduler.py tests/test_send_reminder_scheduler.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```powershell
git add src/reminder_scheduler.py src/send_reminder_scheduler.py tests/test_reminder_scheduler.py tests/test_send_reminder_scheduler.py
git commit -m "feat(reservierungen): Erinnerungen hängen an reservations_enabled statt am Kalender"
```

---

### Task 4: Einstellungs-Dialog

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_rules.py:86-110` (`work_updates`)
- Modify: `src/dialogs/settings_dialog/tab_work.py`
- Modify: `src/dialogs/settings_dialog/tab_reminders.py:34-90`
- Modify: `src/dialogs/settings_dialog/tab_google.py:543-545`
- Modify: `src/dialogs/import_dialog.py:209-218`
- Test: `tests/test_tab_rules.py`

**Interfaces:**
- Consumes: Setting `reservations_enabled` (Task 1).
- Produces: Formularfeld `reservations_enabled` im Work-Tab.

- [ ] **Step 1: Failing tests** (`tests/test_tab_rules.py`)

In `work_raw()` (Zeile 13-29) `"reservations_enabled": False,` ergänzen; in `_legacy_keys_base` (Zeile ~241-254) `"reservations_enabled"` aufnehmen; neu:

```python
def test_work_updates_writes_reservations_enabled():
    assert tr.work_updates(work_raw(reservations_enabled=True), OLD_WSL)[
        "reservations_enabled"] is True
    assert tr.work_updates(work_raw(reservations_enabled=False), OLD_WSL)[
        "reservations_enabled"] is False
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/test_tab_rules.py -q`
Expected: FAIL (`KeyError: 'reservations_enabled'`, `test_tabs_together_write_exactly_the_legacy_keys`)

- [ ] **Step 3: `work_updates` ergänzen** (`src/dialogs/settings_dialog/tab_rules.py`, im `updates`-Dict neben `"pause_warning_enabled"`)

```python
        "reservations_enabled": bool(raw["reservations_enabled"]),
```

- [ ] **Step 4: Work-Tab: Schalter** (`src/dialogs/settings_dialog/tab_work.py`)

Nach dem Werkstudenten-Block (nach `wsl_end_vars = wsl_end_row.vars`) und vor `# --- Verwalten ---`:

```python
        # --- Reservierungen ---
        reservations_var = tk.BooleanVar(value=settings.get("reservations_enabled"))
        form.section("Reservierungen")
        form.check("Reservierungen verwenden (zukünftige Soll-Zeiten)",
                   reservations_var)
        form.hint("Pro Tag eine Soll-Zeit planen, im Kalender als Punkt markiert. "
                  "Der Abgleich mit Google Kalender ist optional (Tab Google). "
                  "Erinnerungen dazu erscheinen nach erneutem Öffnen der "
                  "Einstellungen.")
```

und `self.reservations_var = reservations_var` bei den übrigen Attributen sowie in den Feldern

```python
        fields.add("reservations_enabled", reservations_var)
```

(nach `fields.add("pause_warning_enabled", pause_warning_var)`).

- [ ] **Step 5: Erinnerungen-Tab: Reservierungs-Abschnitte nur bei aktivem Schalter** (`src/dialogs/settings_dialog/tab_reminders.py`)

`RemindersTab` liest `reservations_enabled` beim Aufbau. Die Variablen und `FieldSet`-Einträge bleiben **immer** bestehen (sonst fehlen Schlüssel in `values()`), nur die Widgets der Reservierungs-Abschnitte entfallen. Konkret:

1. Vor dem Abschnitt „Reservierungen" (Zeile 34): `show_reservations = bool(settings.get("reservations_enabled"))`.
2. Variablen `reminders_var`, `minutes_var` bleiben wie sie sind; den Block
   `form.section("Reservierungen")` … `form.hint("Nur für Reservierungen mit Kategorie …")` in `if show_reservations:` einrücken.
3. Variablen `res_var`, `default_minutes_var` bleiben; den Block von `form.section("An Reservierungstagen")` bis zum `form.hint(hint)` in `if show_reservations:` einrücken und die Hinweis-Konstruktion (`hint = …; if not settings.get("gcal_enabled"): hint += …`) ersetzen durch den festen Text
   `form.hint("Welche Tage erinnern, legst du im Tages-Dialog fest.")`.
4. Im Docstring des Moduls einen Satz ergänzen: „Die Reservierungs-Abschnitte erscheinen nur, wenn Reservierungen eingeschaltet sind (Tab Arbeitszeit); die Werte bleiben erhalten."

- [ ] **Step 6: Google-Tab-Text** (`src/dialogs/settings_dialog/tab_google.py:543-545`)

`"Reservierungen mit Google Kalender abgleichen"` → `"Mit Google Kalender abgleichen (Reservierungen und Urlaub)"`.

- [ ] **Step 7: Import-Dialog-Hinweis** (`src/dialogs/import_dialog.py:209-218`)

Bedingung `not self.settings.get("gcal_enabled")` → `not self.settings.get("reservations_enabled")`, Text:
`"Hinweis: Reservierungen werden erst sichtbar, wenn sie in den\nEinstellungen (Tab Arbeitszeit) eingeschaltet sind."`.

- [ ] **Step 8: Tests**

Run: `pytest tests/test_tab_rules.py tests/test_settings_dialog.py tests/test_pixel_scaling.py tests/test_catch_all_handlers.py -q`
Expected: PASS

- [ ] **Step 9: Manuelle Sichtprüfung (einmal, Windows)**

Run: `python -m src.main` mit `$env:ZEITERFASSUNG_DATA_DIR` auf ein Scratch-Verzeichnis. Prüfen: Einstellungen → Arbeitszeit zeigt den Abschnitt „Reservierungen"; Schalter aus → Tab Erinnerungen ohne Reservierungs-Abschnitte (nach erneutem Öffnen); Tages-Dialog eines Zukunftstags ohne Reservierungs-Block; Schalter an → Block da, auch **ohne** Google-Kalender. Screenshot der Einstellungen für die PR-Beschreibung.

- [ ] **Step 10: Commit**

```powershell
git add src/dialogs tests/test_tab_rules.py
git commit -m "feat(reservierungen): Schalter in den Einstellungen, Reservierungs-Optionen nur wenn an"
```

---

### Task 5: Doku, Demo-Daten, Abschluss

**Files:**
- Modify: `scripts/demo_data.py:28-33, 186-190`
- Modify: `README.md` (Zeile 42-43, Abschnitt „Google-Kalender für Reservierungen einrichten")
- Modify: `CLAUDE.md` (Wurzel; Bezüge auf `_reservations_active`/`gcal_enabled`), `src/CLAUDE.md` (Abschnitt Erinnerungen in „Daten- & Persistenz-Schicht", der `gcal_enabled`-Satz)
- Test: `tests/test_demo_data.py`, `tests/test_claude_md_claims.py`

- [ ] **Step 1: Demo-Daten**

`scripts/demo_data.py`: im Settings-Dict `"reservations_enabled": True, "reservations_migrated": True,` ergänzen; den Docstring-Absatz „**Kalender-Abgleich:**" ersetzen durch: „**Reservierungen** sind eingeschaltet (`reservations_enabled`); der Kalender-Abgleich ist ein Zusatz und standardmäßig an, ohne Google-Anmeldung meldet die App nach dem Speichern „Google-Verbindung abgelaufen". `--ohne-kalender` schaltet ihn aus; die Reservierungen bleiben." (Sinngemäß, Stil der Datei.)

- [ ] **Step 2: README**

Zeile 42: `- **Reservierungen & Google-Kalender** *(ab --VERSION--)* — Zukünftige Arbeitszeiten pro Tag reservieren (in den Einstellungen einschaltbar, eigenes Konzept neben den Ist-Zeiten, im Kalender als violetter Eck-Punkt markiert); optionaler Abgleich mit einem wählbaren Google Kalender`. Im Abschnitt „Google-Kalender für Reservierungen einrichten (optional)" einen Satz ergänzen: Reservierungen funktionieren auch ohne Google; der Kalender gleicht sie (und Urlaub) nur zusätzlich ab und synchronisiert damit mehrere Geräte. Den Hinweis zu `reservations.json` (Zeile ~446) unverändert lassen.

- [ ] **Step 3: CLAUDE.md-Bezüge**

`Grep "_reservations_active|gcal_enabled" CLAUDE.md src/CLAUDE.md`. Anpassen: Beschreibung von `_reservations_active` (jetzt `reservations_enabled`), `send_reminder_scheduler`-Absatz in `src/CLAUDE.md` („verlangt … **und** `gcal_enabled`" → `reservations_enabled`), `BackgroundTaskRunner`-Hinweis (Parameter `calendar_active`), Satz bei `Urlaub` („`_reservations_active` prüft beides, und `trigger_reconcile`/`reconcile_on_start` kehren sonst früh zurück" → Gate ist `gcal_enabled`, Urlaub unabhängig von Reservierungen). Die vom Test geprüften harten Behauptungen (Required Checks, Matrix, Pins) nicht umformulieren.

- [ ] **Step 4: Gesamtlauf**

Run (PowerShell): `pytest -q ; ruff check . ; npx pyright`
Expected: alle grün (Test-Suite, Lint, Typecheck). Fehlschläge nicht wegerklären — Ursache beheben.

- [ ] **Step 5: Commit, Push, PR**

```powershell
git add -A
git commit -m "docs(reservierungen): README, CLAUDE.md und Demo-Daten für reservations_enabled"
git push -u origin feat/reservierungen-ohne-google
```

PR (Basis `master`) mit Beschreibung: Zusammenfassung, Migration, Screenshot, Hinweis „PR 1 von 3 (Stack)". Kein `release:*`-Label. Plattform-Label nicht nötig. Stacked-PR-Hinweis: PR 2 und 3 bauen auf diesem Branch auf (`gh stack`).

---

## Self-Review (Plan gegen Spec)

- Einstellung + Migration + Marker → Task 1. Gate-Austausch → Task 2. Kalender-Push nur bei `gcal_enabled` und Urlaub unabhängig → Task 2 (`calendar_active`, `_reconcile_store`, `run_calendar_reconcile(None)`).
- Ausblenden der Reservierungs-Optionen (Abschnitte im Erinnerungen-Tab) → Task 4. Google-Abschnitt bleibt sichtbar, Label geändert → Task 4 Step 6.
- Sende-Erinnerung/`ReminderScheduler`/Share-Dialog-Gate → Task 3 und `_active_reservation_store()` in Task 2 (Share-/Send-/Settings-Dialog).
- Tombstone-Sweep: Spec verlangt die Prüfung, dass Veto und Aussage zusammenpassen. Der Plan ändert `drop_orphan_reservation_tombstones` bewusst **nicht**: `sync_history.mark_reconciled` wird jetzt nur gesetzt, wenn wirklich abgeglichen wurde (Task 2 Step 3), und der Sweep greift weiter nur ohne Kalender-Partner (`never_reconciled`). Beides ist durch `test_reconcile_without_reservation_store_pushes_only_vacation` abgedeckt.
- Typkonsistenz: `reservations_active` (Modulfunktion, Task 1) vs. `App._reservations_active` (Methode) — bewusst gleiche Namen, die Methode delegiert. `calendar_active` (Runner-Parameter) heißt in allen Tasks gleich.
- Platzhalter: keine. Bekannte Unschärfe: Task 2 Step 6 verweist auf Tests, die `gcal_enabled` als Stand-in nutzen könnten; die Suche nach ihnen ist Teil des Schritts.
