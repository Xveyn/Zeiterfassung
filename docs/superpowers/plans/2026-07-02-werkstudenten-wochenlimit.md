# Werkstudenten-Wochenlimit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein konfigurierbares Wochenstunden-Limit (Default 20h, Werkstudenten-Privileg § 6 Abs. 1 Nr. 3 SGB V) für einen einstellbaren Zeitraum, das beim manuellen Speichern einer Ist-Zeit und beim automatischen Kalender-Import warnt, wenn die Ist-Stunden-Summe (alle Kategorien) einer ISO-Woche das Limit überschreitet.

**Architecture:** Ein neues, Tk-freies Pure-Logik-Modul `src/weekly_limit.py` kapselt die komplette Berechnung (Zeitraum-Check, Wochenstunden-Summe, Überschreitungs-Ermittlung, Formatierung). `entry_dialog.py` ruft es synchron beim Speichern auf (bypassbare `themed_askyesno`-Warnung, analog zum bestehenden Feiertags-Dialog). `reservations_sync.py` liefert zusätzlich zurück, welche Daten in einem Sync-Lauf aus dem Kalender importiert wurden; `main.py::run_calendar_reconcile` prüft nur die ISO-Wochen dieser importierten Daten gegen die bestehenden Ist-Zeiten und reicht das Ergebnis über `background_tasks.py`/`ui.py` als nicht-blockierende `themed_showwarning` durch (Sync läuft im Hintergrund-Thread, kann nicht abgebrochen werden). `settings_dialog.py` scannt einmalig den kompletten Zeitraum, wenn das Feature aktiviert oder der Zeitraum geändert wird.

**Tech Stack:** Python 3, Tkinter, pytest (keine neuen Dependencies).

## Global Constraints

- Default AUS (`werkstudent_limit_enabled=False`) — bestehende Nutzer sehen ohne bewusste Aktivierung keine Verhaltensänderung (Abwärtskompatibilität, Entscheidung 1+7).
- Es zählen ausschließlich Ist-Zeiten (`Storage`), NICHT Reservierungen — Reservierungen sind laut `reservations.py`-Docstring zukünftige Soll-Zeiten (Entscheidung 2).
- Reine Warnung, kein Hard-Block — der User kann sich beim manuellen Speichern über eine Ja/Nein-Bestätigung hinwegsetzen (Entscheidung 3).
- Summe über ALLE Kategorien einer ISO-Woche, keine Kategorie-Filterung (Entscheidung 4).
- Automatischer Kalender-Sync prüft nur die ISO-Woche(n) der in diesem Lauf tatsächlich importierten (aus Google Calendar übernommenen) Reservierungs-Slots — kein voller Zeitraum-Scan pro Sync (Entscheidung 5, geklärt).
- Voller Zeitraum-Scan läuft einmalig im Settings-Dialog, wenn das Limit aktiviert, das Stundenlimit geändert oder der Zeitraum geändert wird (Entscheidung 6, geklärt; um Stundenlimit-Änderungen erweitert nach Adversarial-Review — sonst blieben Bestandsverstöße nach einer Limit-Verschärfung unsichtbar, obwohl das genau der Kontrollpunkt ist, an dem sie sichtbar werden sollen).
- Der Sync-Warn-Dialog erscheint bei jedem betroffenen Sync-Lauf erneut — kein "gesehen"-Zustand pro Woche (geklärt).
- Neue Settings-Keys brauchen keine `SCHEMA_VERSION`-Migration in `sync.py` (bestätigt durch Recherche: `migrate_doc_to_current` fasst `settings` unverändert durch; die Whitelist-Mechanik in `apply_synced`/`_load` ignoriert unbekannte Keys auf älteren App-Versionen bereits verlustfrei).

---

## Task 1: Settings — neue Werkstudenten-Limit-Keys

**Files:**
- Modify: `src/settings.py:8-12` (SYNCED_SETTING_KEYS), `src/settings.py:14-57` (DEFAULTS)
- Test: `tests/test_settings.py`

**Interfaces:**
- Produziert: `Settings.get("werkstudent_limit_enabled")` → `bool`, Default `False`
- Produziert: `Settings.get("werkstudent_limit_start")` / `"werkstudent_limit_end"` → ISO-Datumsstring (`"YYYY-MM-DD"`) oder `""`, Default `""`
- Produziert: `Settings.get("werkstudent_limit_max_hours")` → `float`, Default `20.0`
- Alle vier Keys sind Mitglied von `SYNCED_SETTING_KEYS` (reisen über Drive-Sync mit, wie `hourly_rate`/`categories`).

- [ ] **Step 1: Failing Tests schreiben**

An `tests/test_settings.py` anhängen (nach dem bestehenden `category_times`-Block, vor `test_split_synced_updates_partitions_by_whitelist`):

```python
# --- Werkstudenten-Limit (Wochenstunden-Grenze für einen Zeitraum, #98) ---


def test_werkstudent_limit_defaults(tmp_settings):
    assert tmp_settings.get("werkstudent_limit_enabled") is False
    assert tmp_settings.get("werkstudent_limit_start") == ""
    assert tmp_settings.get("werkstudent_limit_end") == ""
    assert tmp_settings.get("werkstudent_limit_max_hours") == 20.0


def test_werkstudent_limit_keys_are_synced():
    assert "werkstudent_limit_enabled" in SYNCED_SETTING_KEYS
    assert "werkstudent_limit_start" in SYNCED_SETTING_KEYS
    assert "werkstudent_limit_end" in SYNCED_SETTING_KEYS
    assert "werkstudent_limit_max_hours" in SYNCED_SETTING_KEYS


def test_werkstudent_limit_persists(tmp_path):
    path = str(tmp_path / "settings.json")
    s1 = Settings(path)
    s1.set_many({
        "werkstudent_limit_enabled": True,
        "werkstudent_limit_start": "2026-04-01",
        "werkstudent_limit_end": "2026-07-15",
        "werkstudent_limit_max_hours": 18.0,
    })
    s2 = Settings(path)
    assert s2.get("werkstudent_limit_enabled") is True
    assert s2.get("werkstudent_limit_start") == "2026-04-01"
    assert s2.get("werkstudent_limit_end") == "2026-07-15"
    assert s2.get("werkstudent_limit_max_hours") == 18.0
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_settings.py -k werkstudent -v`
Expected: FAIL — `assert None is False` (Key existiert noch nicht in DEFAULTS, `get()` liefert `None`).

- [ ] **Step 3: DEFAULTS und SYNCED_SETTING_KEYS erweitern**

In `src/settings.py` `SYNCED_SETTING_KEYS` (Zeilen 8-12) ersetzen:

```python
SYNCED_SETTING_KEYS = (
    "recipient", "name", "hourly_rate",
    "mail_subject", "mail_greeting", "mail_content", "mail_closing",
    "gcal_calendar_id", "categories", "category_times",
    "werkstudent_limit_enabled", "werkstudent_limit_start",
    "werkstudent_limit_end", "werkstudent_limit_max_hours",
)
```

In `DEFAULTS` (Zeilen 14-57) die letzte Zeile `"ui_scale": 1.0,` ergänzen um:

```python
    "ui_scale": 1.0,
    "werkstudent_limit_enabled": False,
    "werkstudent_limit_start": "",
    "werkstudent_limit_end": "",
    "werkstudent_limit_max_hours": 20.0,
}
```

- [ ] **Step 4: Tests laufen lassen, Erfolg bestätigen**

Run: `pytest tests/test_settings.py -v`
Expected: PASS (alle Tests, inkl. der drei neuen und aller bestehenden — keine Regression).

- [ ] **Step 5: Commit**

```bash
git add src/settings.py tests/test_settings.py
git commit -m "feat(settings): Werkstudenten-Wochenlimit-Keys (#98)"
```

---

## Task 2: `src/weekly_limit.py` — Pure Wochenlimit-Logik

**Files:**
- Create: `src/weekly_limit.py`
- Test: `tests/test_weekly_limit.py`
- Modify (Doku): `src/CLAUDE.md`, `CLAUDE.md` (Struktur-Liste)

**Interfaces:**
- Consumes: `src.time_utils.calculate_hours(start, end, pause_minutes=0)`, `get_week_dates(iso_year, iso_week)`, `get_week_label(iso_year, iso_week)` (Task 1 unverändert)
- Consumes: `Settings.get(key)`-Interface (auch ein plain `dict` mit `.get()` ist ausreichend — Tests nutzen dicts, wie `tests/test_background_tasks.py`)
- Produziert (für Task 3-6): `is_limit_active(settings, date_str) -> bool`, `week_ist_hours(all_entries, iso_year, iso_week) -> float`, `check_week_limit(settings, all_entries, date_str) -> dict | None`, `check_dates_for_warnings(settings, all_entries, date_strs) -> list[dict]`, `scan_period_for_warnings(settings, all_entries) -> list[dict]`, `format_limit_warnings(warnings) -> str`
- Produziert (für Task 8): `period_scan_needed(old, new) -> bool` — `old`/`new` sind Dicts `{"enabled": bool, "start": str, "end": str, "max_hours": float}`
- Überschreitungs-Dict-Form (von `check_week_limit`, `check_dates_for_warnings`, `scan_period_for_warnings`): `{"iso_year": int, "iso_week": int, "total_hours": float, "limit_hours": float}`

- [ ] **Step 1: Failing Tests schreiben**

Neue Datei `tests/test_weekly_limit.py`:

```python
from src.weekly_limit import (
    check_dates_for_warnings, check_week_limit, format_limit_warnings,
    is_limit_active, period_scan_needed, scan_period_for_warnings, week_ist_hours,
)


def _settings(enabled=True, start="2026-04-01", end="2026-07-15", max_hours=20.0):
    return {
        "werkstudent_limit_enabled": enabled,
        "werkstudent_limit_start": start,
        "werkstudent_limit_end": end,
        "werkstudent_limit_max_hours": max_hours,
    }


def _wsl(enabled=True, start="2026-04-01", end="2026-07-15", max_hours=20.0):
    return {"enabled": enabled, "start": start, "end": end, "max_hours": max_hours}


def _entry(slots):
    return {"slots": slots}


def _slot(start, end, pause=0, kategorie=""):
    return {"start": start, "end": end, "pause": pause, "kategorie": kategorie}


def test_is_limit_active_false_when_disabled():
    assert is_limit_active(_settings(enabled=False), "2026-05-04") is False


def test_is_limit_active_false_without_period():
    assert is_limit_active(_settings(start="", end=""), "2026-05-04") is False


def test_is_limit_active_false_outside_period():
    assert is_limit_active(_settings(), "2026-08-01") is False


def test_is_limit_active_true_inside_period():
    assert is_limit_active(_settings(), "2026-05-04") is True


def test_week_ist_hours_sums_all_categories_across_week():
    # KW 19/2026: Mo 2026-05-04 .. So 2026-05-10
    all_entries = {
        "2026-05-04": _entry([_slot("08:00", "12:00", kategorie="Büro")]),
        "2026-05-06": _entry([_slot("08:00", "12:00"),
                              _slot("13:00", "16:00", kategorie="Homeoffice")]),
    }
    assert week_ist_hours(all_entries, 2026, 19) == 11.0


def test_week_ist_hours_ignores_dates_outside_week():
    all_entries = {"2026-04-27": _entry([_slot("08:00", "16:00")])}  # KW 18
    assert week_ist_hours(all_entries, 2026, 19) == 0.0


def test_check_week_limit_none_when_under_limit():
    all_entries = {"2026-05-04": _entry([_slot("08:00", "12:00")])}
    assert check_week_limit(_settings(), all_entries, "2026-05-04") is None


def test_check_week_limit_none_when_inactive():
    all_entries = {
        d: _entry([_slot("08:00", "18:00")])
        for d in ("2026-05-04", "2026-05-05", "2026-05-06")
    }
    assert check_week_limit(_settings(enabled=False), all_entries, "2026-05-04") is None


def test_check_week_limit_returns_overshoot_when_over_limit():
    all_entries = {
        "2026-05-04": _entry([_slot("08:00", "18:00")]),  # 10h
        "2026-05-05": _entry([_slot("08:00", "18:00")]),  # 10h
        "2026-05-06": _entry([_slot("08:00", "13:00")]),  # 5h -> 25h total
    }
    result = check_week_limit(_settings(), all_entries, "2026-05-04")
    assert result == {
        "iso_year": 2026, "iso_week": 19, "total_hours": 25.0, "limit_hours": 20.0,
    }


def test_check_dates_for_warnings_dedupes_per_week():
    all_entries = {
        "2026-05-04": _entry([_slot("08:00", "20:00")]),  # 12h, KW 19
        "2026-05-05": _entry([_slot("08:00", "20:00")]),  # 12h -> 24h in KW 19
    }
    warnings = check_dates_for_warnings(
        _settings(), all_entries, ["2026-05-04", "2026-05-05", "2026-05-06"])
    assert len(warnings) == 1
    assert warnings[0]["iso_week"] == 19


def test_check_dates_for_warnings_skips_inactive_date_but_checks_active_one_in_same_week():
    """Regression (Adversarial-Review): Zeitraum startet mitten in der Woche
    — ein Datum VOR dem Start darf die Woche nicht als 'gesehen' markieren,
    sonst wird ein späteres, aktives Datum derselben ISO-Woche fälschlich
    übersprungen und ein realer Verstoß bleibt unbemerkt."""
    all_entries = {
        "2026-05-04": _entry([_slot("08:00", "18:00")]),  # Mo, vor Zeitraumstart, 10h
        "2026-05-07": _entry([_slot("08:00", "19:00")]),  # Do, im Zeitraum, 11h -> 21h total
    }
    warnings = check_dates_for_warnings(
        _settings(start="2026-05-06", end="2026-07-15"),
        all_entries, ["2026-05-04", "2026-05-07"])
    assert len(warnings) == 1
    assert warnings[0]["iso_week"] == 19


def test_scan_period_for_warnings_empty_when_disabled():
    assert scan_period_for_warnings(_settings(enabled=False), {}) == []


def test_scan_period_for_warnings_finds_all_overshooting_weeks():
    all_entries = {
        "2026-04-06": _entry([_slot("06:00", "20:00")]),  # KW 15, 14h — under
        "2026-05-04": _entry([_slot("06:00", "20:00")]),  # KW 19, 14h
        "2026-05-05": _entry([_slot("06:00", "20:00")]),  # KW 19, 14h -> 28h, over
    }
    warnings = scan_period_for_warnings(
        _settings(start="2026-04-01", end="2026-05-10"), all_entries)
    assert [w["iso_week"] for w in warnings] == [19]


def test_format_limit_warnings_lists_each_week():
    text = format_limit_warnings([
        {"iso_year": 2026, "iso_week": 19, "total_hours": 25.0, "limit_hours": 20.0},
    ])
    assert "25.00h" in text
    assert "20.00h" in text


def test_period_scan_needed_false_when_still_disabled():
    assert period_scan_needed(_wsl(enabled=False), _wsl(enabled=False)) is False


def test_period_scan_needed_true_on_activation():
    assert period_scan_needed(_wsl(enabled=False), _wsl(enabled=True)) is True


def test_period_scan_needed_false_when_deactivated():
    assert period_scan_needed(_wsl(enabled=True), _wsl(enabled=False)) is False


def test_period_scan_needed_true_on_period_change():
    assert period_scan_needed(_wsl(), _wsl(end="2026-08-01")) is True


def test_period_scan_needed_true_on_hours_change():
    """Adversarial-Review-Fix: eine Verschärfung des Stundenlimits bei
    unverändertem Zeitraum muss den Bestandsscan auch auslösen — genau dort
    werden neue Verstöße gegen bestehende Daten sichtbar."""
    assert period_scan_needed(_wsl(max_hours=20.0), _wsl(max_hours=10.0)) is True


def test_period_scan_needed_false_when_nothing_changed():
    assert period_scan_needed(_wsl(), _wsl()) is False
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_weekly_limit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.weekly_limit'`.

- [ ] **Step 3: Modul implementieren**

Neue Datei `src/weekly_limit.py`:

```python
"""Wochenstunden-Limit für einen konfigurierbaren Zeitraum (z.B. das
Werkstudenten-Privileg während der Vorlesungszeit, § 6 Abs. 1 Nr. 3 SGB V).

Pure Logik (kein Tk, kein I/O): prüft, ob die Ist-Stunden-Summe (alle
Kategorien; Reservierungen zählen NICHT mit, siehe reservations.py-Docstring)
einer ISO-Woche das konfigurierte Limit überschreitet, wenn ein Datum in den
konfigurierten Zeitraum fällt. Default ist das Limit deaktiviert
(`werkstudent_limit_enabled=False`, siehe settings.py DEFAULTS) — bestehende
Nutzer sehen ohne bewusste Aktivierung keinerlei Änderung im Verhalten.
"""

import datetime

from src.time_utils import calculate_hours, get_week_dates, get_week_label


def is_limit_active(settings, date_str):
    """True, wenn das Werkstudenten-Limit aktiv ist UND date_str (ISO) im
    konfigurierten Zeitraum liegt. Deaktiviertes Limit oder leerer/fehlender
    Zeitraum -> False."""
    if not settings.get("werkstudent_limit_enabled"):
        return False
    start = settings.get("werkstudent_limit_start")
    end = settings.get("werkstudent_limit_end")
    if not start or not end:
        return False
    return start <= date_str <= end


def week_ist_hours(all_entries, iso_year, iso_week):
    """Summe der Ist-Stunden (alle Kategorien) einer ISO-Woche.

    all_entries: {date_str: {slots: [...]}} wie von Storage.get_all()."""
    total = 0.0
    for day in get_week_dates(iso_year, iso_week):
        entry = all_entries.get(day.isoformat())
        if not entry:
            continue
        for slot in entry["slots"]:
            total += calculate_hours(
                slot.get("start"), slot.get("end"), slot.get("pause", 0))
    return round(total, 2)


def check_week_limit(settings, all_entries, date_str):
    """Prüft, ob date_str im konfigurierten Werkstudenten-Zeitraum liegt und
    die Ist-Stunden-Summe der zugehörigen ISO-Woche das Limit überschreitet.

    Liefert None (Limit inaktiv, Datum außerhalb, oder Summe <= Limit) oder
    ein Dict {iso_year, iso_week, total_hours, limit_hours} bei
    Überschreitung."""
    if not is_limit_active(settings, date_str):
        return None
    day = datetime.date.fromisoformat(date_str)
    iso = day.isocalendar()
    total = week_ist_hours(all_entries, iso.year, iso.week)
    limit = settings.get("werkstudent_limit_max_hours")
    if total <= limit:
        return None
    return {
        "iso_year": iso.year, "iso_week": iso.week,
        "total_hours": total, "limit_hours": limit,
    }


def check_dates_for_warnings(settings, all_entries, date_strs):
    """Prüft eine Menge von Daten (z.B. neu importierte Reservierungs-Slots)
    auf Wochenlimit-Überschreitung. Dedupliziert nach ISO-Woche (ein Datum
    pro Woche reicht für den Check). Liefert eine Liste von
    Überschreitungs-Dicts (siehe check_week_limit), höchstens eine pro
    betroffener Woche.

    Inaktive Daten (außerhalb des konfigurierten Zeitraums) werden VOR dem
    Dedupe gefiltert, nicht erst in check_week_limit — sonst markiert ein
    frühes, inaktives Datum die Woche fälschlich als 'geprüft' und ein
    späteres, aktives Datum derselben ISO-Woche würde nie berechnet (Bug:
    ein realer Verstoß nach Kalender-Import bliebe unbemerkt, wenn der
    Zeitraum mitten in einer Woche beginnt/endet)."""
    seen_weeks = set()
    warnings = []
    for date_str in sorted(set(date_strs)):
        if not is_limit_active(settings, date_str):
            continue
        iso = datetime.date.fromisoformat(date_str).isocalendar()
        week_key = (iso.year, iso.week)
        if week_key in seen_weeks:
            continue
        seen_weeks.add(week_key)
        result = check_week_limit(settings, all_entries, date_str)
        if result is not None:
            warnings.append(result)
    return warnings


def scan_period_for_warnings(settings, all_entries):
    """Scannt den kompletten konfigurierten Werkstudenten-Zeitraum (falls
    aktiv) Woche für Woche auf Limit-Überschreitung. Liefert eine Liste von
    Überschreitungs-Dicts (siehe check_week_limit), eine pro überschrittener
    Woche. Leere Liste, wenn das Limit inaktiv ist, kein/ungültiger Zeitraum
    konfiguriert ist, oder keine Woche überschritten wird."""
    if not settings.get("werkstudent_limit_enabled"):
        return []
    start = settings.get("werkstudent_limit_start")
    end = settings.get("werkstudent_limit_end")
    if not start or not end:
        return []
    start_date = datetime.date.fromisoformat(start)
    end_date = datetime.date.fromisoformat(end)
    if start_date > end_date:
        return []
    dates = []
    day = start_date
    while day <= end_date:
        dates.append(day.isoformat())
        day += datetime.timedelta(days=1)
    return check_dates_for_warnings(settings, all_entries, dates)


def format_limit_warnings(warnings):
    """Formatiert eine Liste von Überschreitungs-Dicts (siehe
    check_week_limit) zu einem mehrzeiligen Anzeige-Text für einen
    Warn-Dialog."""
    return "\n".join(
        f"– {get_week_label(w['iso_year'], w['iso_week'])}: "
        f"{w['total_hours']:.2f}h (Limit {w['limit_hours']:.2f}h)"
        for w in warnings
    )


def period_scan_needed(old, new):
    """Entscheidet, ob ein voller Zeitraum-Scan (scan_period_for_warnings)
    nötig ist, wenn sich die Werkstudenten-Limit-Settings von old nach new
    ändern. old/new: Dicts {"enabled", "start", "end", "max_hours"}.

    True bei Aktivierung (enabled False -> True) sowie bei jeder Zeitraum-
    oder Stundenlimit-Änderung, SOLANGE das Limit in new aktiv ist — eine
    Verschärfung des Stundenlimits bei unverändertem Zeitraum muss den Scan
    genauso auslösen wie eine Zeitraum-Änderung, weil genau das der
    Kontrollpunkt ist, an dem neue Verstöße gegen bestehende Daten sichtbar
    werden (Adversarial-Review-Fix). False, wenn new deaktiviert ist oder
    sich nichts geändert hat."""
    if not new["enabled"]:
        return False
    if not old["enabled"]:
        return True
    return (new["start"] != old["start"] or new["end"] != old["end"]
            or new["max_hours"] != old["max_hours"])
```

- [ ] **Step 4: Tests laufen lassen, Erfolg bestätigen**

Run: `pytest tests/test_weekly_limit.py -v`
Expected: PASS (20 Tests).

- [ ] **Step 5: Architektur-Doku aktualisieren**

In `src/CLAUDE.md`, Abschnitt „## Daten- & Persistenz-Schicht", nach der Zeile zu `sync.py`/`share.py` ergänzen:

```
- `weekly_limit.py` — pure Wochenstunden-Limit-Check (Werkstudenten-Privileg,
  #98). Kein eigener Persistenz-Zustand, operiert auf `Storage.get_all()`-
  Dicts und den `werkstudent_limit_*`-Settings-Keys.
```

In `CLAUDE.md` (Repo-Root), Abschnitt „## Struktur", nach der Zeile zu `src/reservations_sync.py` ergänzen:

```
- `src/weekly_limit.py` — Wochenstunden-Limit für einen konfigurierbaren Zeitraum (Werkstudenten-Privileg, #98); pure Logik, zählt nur Ist-Zeiten (nicht Reservierungen)
```

- [ ] **Step 6: Commit**

```bash
git add src/weekly_limit.py tests/test_weekly_limit.py src/CLAUDE.md CLAUDE.md
git commit -m "feat(weekly-limit): Wochenstunden-Limit-Kernlogik (#98)"
```

---

## Task 3: Manuelles Speichern im Tages-Dialog warnt bei Überschreitung

**Files:**
- Modify: `src/dialogs/entry_dialog.py:1-14` (Imports), `src/dialogs/entry_dialog.py:229-249` (`save_ist`)

**Interfaces:**
- Consumes: `check_week_limit(settings, all_entries, date_str)` (Task 2), `get_week_label(iso_year, iso_week)` (bestehend, `time_utils.py`)

Kein neuer automatisierter Test in diesem Task: `save_ist()`/`save_reservation()` sind Tk-Closures ohne Root-Fenster und werden im bestehenden Code nicht unit-getestet (`tests/test_entry_dialog.py` testet ausschließlich die reinen Helper-Funktionen des Moduls, z.B. `category_choices`). Die eigentliche Prüf-Logik ist bereits in Task 2 vollständig getestet; dieser Task ist reine, manuell zu verifizierende UI-Verdrahtung — analog zum bestehenden, ebenfalls ungetesteten Feiertags-Dialog in derselben Funktion.

- [ ] **Step 1: Imports erweitern**

In `src/dialogs/entry_dialog.py` Zeile 14 ersetzen:

```python
from src.time_utils import format_iso_weekday_date, get_week_label, validate_slots
from src.weekly_limit import check_week_limit
```

- [ ] **Step 2: `save_ist()` um den Wochenlimit-Check erweitern**

Zeilen 229-249 ersetzen:

```python
    def save_ist():
        # Ohne Slot deaktiviert; während Cooldown/Speichern geblockt.
        if not ist_rows or ist_save_locked["value"]:
            return
        ist_save_locked["value"] = True
        refresh_ist_save_state()  # sofort sperren gegen Doppelklick
        slots = [{
            "start": r["start"].get(),
            "end": r["end"].get(),
            "pause": int(r["pause"].get() or 0),
            "kategorie": category_from_display(r["kategorie"].get()),
        } for r in ist_rows]
        ok, msg = validate_slots(slots, with_pause=True)
        if not ok:
            themed_showinfo(dialog, "Hinweis", msg)
            ist_save_locked["value"] = False
            refresh_ist_save_state()  # Fehler → wieder freigeben
            return

        # Werkstudenten-Wochenlimit: prüft die ISO-Woche MIT den neuen Slots
        # (simulierter Post-Save-Stand), nicht den aktuellen Storage-Stand —
        # sonst würde eine Verlängerung, die erst über das Limit treibt,
        # nicht erkannt. Reine Warnung: der User kann trotzdem speichern.
        simulated_entries = storage.get_all()
        simulated_entries[date_str] = {"slots": slots}
        overshoot = check_week_limit(settings, simulated_entries, date_str)
        if overshoot is not None:
            week_label = get_week_label(overshoot["iso_year"], overshoot["iso_week"])
            confirm = themed_askyesno(
                dialog, "Wochenlimit überschritten",
                f"{week_label}: {overshoot['total_hours']:.2f}h Ist-Zeit "
                f"überschreiten das konfigurierte Werkstudenten-Limit von "
                f"{overshoot['limit_hours']:.2f}h/Woche.\n\nTrotzdem speichern?",
            )
            if not confirm:
                ist_save_locked["value"] = False
                refresh_ist_save_state()  # Abbruch → wieder freigeben
                return

        storage.save(date_str, slots)
        dialog.destroy()
        on_change()
```

`save_reservation()` bleibt unverändert — Reservierungen zählen laut Feature-Entscheidung nicht in die Wochensumme, ein Speichern dort löst daher bewusst keinen Check aus.

- [ ] **Step 3: Bestehende Tests laufen lassen (Regression)**

Run: `pytest tests/test_entry_dialog.py -v`
Expected: PASS (unverändert — dieser Task berührt keine der getesteten reinen Helper-Funktionen).

- [ ] **Step 4: Verify — manueller Durchlauf**

Da hier keine automatisierten Tests greifen (siehe oben), App manuell starten (`python -m src.main`) und durchklicken:
1. Einstellungen → Werkstudenten-Limit aktivieren, Zeitraum so setzen, dass „heute" darin liegt, Limit z.B. auf 1h setzen (kommt erst mit Task 8, für den Verify dieses Tasks vorerst per `Settings.set_many(...)` in einer Python-Shell oder testweise direkt in `settings.json` setzen).
2. Am heutigen Tag eine Ist-Zeit > 1h anlegen → erwartet: Warn-Dialog „Wochenlimit überschritten" mit Ja/Nein.
3. „Nein" klicken → Eintrag NICHT gespeichert (Kalenderzelle bleibt leer).
4. Erneut speichern, „Ja" klicken → Eintrag gespeichert wie gewohnt.
5. Limit-Feature deaktivieren (oder Zeitraum leeren) → derselbe Save-Vorgang zeigt KEINEN Warn-Dialog mehr.

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/entry_dialog.py
git commit -m "feat(entry-dialog): Warnung bei Wochenlimit-Überschreitung (#98)"
```

---

## Task 4: `reservations_sync.py` — importierte Daten tracken

**Files:**
- Modify: `src/reservations_sync.py` (komplette Datei, s.u. für exakte Diffs)
- Test: `tests/test_reservations_sync.py`

**Interfaces:**
- Produziert (für Task 5): `merge_reservations(local_raw, remote_events, watermark) -> {"merged": {...}, "plan": {...}, "imported_dates": list[str]}`
- Produziert (für Task 5): `reconcile_reservations(service, calendar_id, store, settings) -> {"imported_dates": list[str]}`
- `imported_dates`: sortierte Liste der Daten, an denen in diesem Merge-Lauf Remote-Events lokal übernommen wurden (`_adopt_remote`-Fälle: reiner Remote-Import, Tombstone-Verlust an neueren Remote-Stand, Remote gewinnt bei Konflikt). Lokal-gewinnt-Fälle (pushen nur zu Google) zählen NICHT als Import.

- [ ] **Step 1: Failing Tests schreiben**

In `tests/test_reservations_sync.py` folgende bestehende Tests um eine `imported_dates`-Assertion erweitern (jeweils die letzte Zeile der Funktion ergänzen):

`test_local_only_new_creates_event_per_slot` (Zeilen 21-29) — kein Import, nur Push:
```python
    assert res["imported_dates"] == []
```

`test_remote_only_is_imported_as_slots` (Zeilen 48-52) — reiner Import:
```python
    assert res["imported_dates"] == ["2026-06-01"]
```

`test_tombstone_older_than_remote_is_dropped` (Zeilen 145-151) — Remote gewinnt gegen veraltetes Tombstone:
```python
    assert res["imported_dates"] == ["2026-06-01"]
```

`test_remote_wins_adopts_remote_slots` (Zeilen 124-131) — Remote gewinnt bei Konflikt:
```python
    assert res["imported_dates"] == ["2026-06-01"]
```

Neuer Test, ans Ende der Merge-Test-Sektion (vor dem `# --- reconcile ---`-Kommentar bei Zeile 162):

```python
def test_local_wins_has_no_imported_dates():
    """Lokal gewinnt und pusht nur zu Google — kein Import, weil keine
    Remote-Daten lokal übernommen wurden."""
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(start="08:00", event_id="ev1")],
                              modified_at="2026-05-21T10:00:00Z")},
        [_remote(start="09:00", modified_at="2026-05-20T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert res["imported_dates"] == []
```

Neuer Reconcile-Test, ans Ende der Datei anhängen:

```python
def test_reconcile_returns_imported_dates(tmp_path, monkeypatch):
    """AP-Werkstudentenlimit: reconcile_reservations meldet zurück, welche
    Daten in diesem Lauf aus dem Kalender importiert wurden (#98)."""
    from src import gcal, reservations_sync
    from src.reservations import ReservationStore
    from src.settings import Settings

    store = ReservationStore(str(tmp_path / "res.json"))
    settings = Settings(str(tmp_path / "set.json"))

    monkeypatch.setattr(
        gcal, "list_app_events",
        lambda s, c: [{"date": "2026-06-01", "start": "09:00", "end": "17:00",
                       "kategorie": "", "modified_at": "2026-05-20T10:00:00Z",
                       "event_id": "ev1"}])
    monkeypatch.setattr(gcal, "update_event", lambda *a: None)
    monkeypatch.setattr(gcal, "delete_event", lambda *a: None)
    monkeypatch.setattr(gcal, "create_event", lambda *a: "unused")

    result = reservations_sync.reconcile_reservations(object(), "cal-1", store, settings)

    assert result["imported_dates"] == ["2026-06-01"]
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_reservations_sync.py -v`
Expected: FAIL — `KeyError: 'imported_dates'` in den erweiterten und dem neuen Merge-Test; `TypeError`/`KeyError` im neuen Reconcile-Test (Rückgabewert ist aktuell `None`).

- [ ] **Step 3: `imported_dates`-Tracking implementieren**

In `src/reservations_sync.py` `_adopt_remote` (Zeilen 26-32) ersetzen:

```python
def _adopt_remote(date, remotes, merged, imported_dates):
    """Remote gewinnt: die Slots des Tages = die Remote-Events."""
    merged[date] = {
        "slots": [_slot_from_event(ev) for ev in remotes],
        "modified_at": max(ev["modified_at"] for ev in remotes),
        "deleted": False,
    }
    imported_dates.add(date)
```

`_merge_one_date` (Zeilen 35-125): Signatur und alle drei `_adopt_remote`-Aufrufe anpassen. Zeile 35:

```python
def _merge_one_date(date, local, remotes, watermark, merged, plan, imported_dates):
```

Zeile 51 (Fall 2, nur remote):

```python
        _adopt_remote(date, remotes, merged, imported_dates)
```

Zeile 65 (Fall 3, Tombstone älter als Remote):

```python
        _adopt_remote(date, remotes, merged, imported_dates)  # Remote-Update jünger.
```

Zeile 89 (Fall 5, Remote gewinnt bei Konflikt):

```python
        _adopt_remote(date, remotes, merged, imported_dates)
        return
```

`merge_reservations` (Zeilen 128-151) ersetzen:

```python
def merge_reservations(local_raw, remote_events, watermark):
    """Pure Merge zwischen lokalen Reservierungs-Records und Kalender-Events.

    local_raw:     {date: {slots: [{start,end,kategorie,gcal_event_id}],
                           modified_at, deleted}}
    remote_events: Liste von {date, start, end, kategorie, modified_at, event_id}
    watermark:     last_calendar_sync_at (ISO-String, "" beim Erststart)

    Liefert {"merged": {...}, "plan": {"create": [...], "update": [...],
    "delete": [...]}, "imported_dates": [...]}.
    imported_dates: sortierte Liste der Daten, an denen Remote-Events lokal
    übernommen wurden (echter Kalender-Import, siehe _adopt_remote) — für
    den nachgelagerten Wochenlimit-Check (weekly_limit.py, #98). Lokal-
    gewinnt-Fälle (pushen nur zu Google) zählen NICHT als Import.
    """
    plan = {"create": [], "update": [], "delete": []}
    imported_dates = set()

    remote_by_date = {}
    for ev in remote_events:
        remote_by_date.setdefault(ev["date"], []).append(ev)

    merged = {}
    for date in set(local_raw.keys()) | set(remote_by_date.keys()):
        _merge_one_date(
            date, local_raw.get(date), remote_by_date.get(date, []),
            watermark, merged, plan, imported_dates,
        )
    return {"merged": merged, "plan": plan, "imported_dates": sorted(imported_dates)}
```

`reconcile_reservations` (Zeilen 154-196): Docstring und Rückgabewert anpassen. Zeile 154-166 ersetzen:

```python
def reconcile_reservations(service, calendar_id, store, settings):
    """Voller Kalender-Abgleich: pull → merge → push.

    Mutiert store und settings. Wirft bei Netz-/API-Fehlern weiter — der Caller
    entscheidet, ob still geloggt oder als Messagebox gezeigt wird.

    Liefert {"imported_dates": [...]} — die Daten, an denen in diesem Lauf
    Reservierungs-Slots aus dem Kalender importiert wurden (siehe
    merge_reservations), für den nachgelagerten Wochenlimit-Check (#98).
    """
    from src import gcal

    watermark = settings.get("last_calendar_sync_at") or ""
    local_snapshot = store.get_all_raw()
    remote_events = gcal.list_app_events(service, calendar_id)
    result = merge_reservations(local_snapshot, remote_events, watermark)
    merged, plan, imported_dates = result["merged"], result["plan"], result["imported_dates"]
```

Am Ende der Funktion (Zeilen 189-196) die letzten beiden Zeilen ersetzen:

```python
    store.apply_reconciled(merged)
    settings.set("last_calendar_sync_at", _utc_now_iso())
    return {"imported_dates": imported_dates}
```

- [ ] **Step 4: Tests laufen lassen, Erfolg bestätigen**

Run: `pytest tests/test_reservations_sync.py -v`
Expected: PASS (alle bestehenden + 6 neue/erweiterte Assertions).

- [ ] **Step 5: Commit**

```bash
git add src/reservations_sync.py tests/test_reservations_sync.py
git commit -m "feat(reservations-sync): importierte Daten pro Merge-Lauf tracken (#98)"
```

---

## Task 5: `main.py::run_calendar_reconcile` — Wochenlimit-Check für importierte Wochen

**Files:**
- Modify: `src/main.py:241-268`
- Test: `tests/test_main.py` (neu)

**Interfaces:**
- Consumes: `reconcile_reservations(...) -> {"imported_dates": [...]}` (Task 4), `check_dates_for_warnings(settings, all_entries, date_strs)` (Task 2)
- Ändert Signatur: `run_calendar_reconcile(reservation_store, settings, base, storage)` — neuer 4. Parameter `storage`
- Produziert (für Task 6): `run_calendar_reconcile(...) -> {"ok": bool, "error": str, "tb": str, "limit_warnings": list[dict]}` — `limit_warnings` ist neu im Rückgabe-Dict

- [ ] **Step 1: Failing Tests schreiben**

Neue Datei `tests/test_main.py`:

```python
"""run_calendar_reconcile: orchestriert reservations_sync + Werkstudenten-
Wochenlimit-Check für frisch importierte Reservierungs-Slots (#98).
gcal ist komplett gemockt (kein echtes Netzwerk/OAuth)."""

from src.main import run_calendar_reconcile
from src.reservations import ReservationStore
from src.settings import Settings
from src.storage import Storage


def _settings(tmp_path, **overrides):
    s = Settings(str(tmp_path / "settings.json"))
    s.set_many({"gcal_enabled": True, "gcal_calendar_id": "cal-1", **overrides})
    return s


def test_gcal_disabled_is_noop(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))  # gcal_enabled default False
    store = ReservationStore(str(tmp_path / "res.json"))
    storage = Storage(str(tmp_path / "ze.json"))
    result = run_calendar_reconcile(store, settings, str(tmp_path), storage)
    assert result == {"ok": True, "error": "", "tb": "", "limit_warnings": []}


def test_imported_reservation_over_limit_warns(tmp_path, monkeypatch):
    from src import gcal

    settings = _settings(
        tmp_path,
        werkstudent_limit_enabled=True,
        werkstudent_limit_start="2026-04-01",
        werkstudent_limit_end="2026-07-15",
        werkstudent_limit_max_hours=10.0,
    )
    store = ReservationStore(str(tmp_path / "res.json"))
    storage = Storage(str(tmp_path / "ze.json"))
    # KW19/2026 (2026-05-04..10) hat bereits 11h Ist-Zeit erfasst (> Limit 10h).
    storage.save("2026-05-04",
                 [{"start": "06:00", "end": "17:00", "pause": 0, "kategorie": ""}])

    monkeypatch.setattr(gcal, "get_calendar_service", lambda *a, **k: object())
    monkeypatch.setattr(
        gcal, "list_app_events",
        lambda s, c: [{"date": "2026-05-06", "start": "09:00", "end": "10:00",
                       "kategorie": "", "modified_at": "2026-05-01T00:00:00Z",
                       "event_id": "evt-1"}])
    monkeypatch.setattr(gcal, "update_event", lambda *a: None)
    monkeypatch.setattr(gcal, "delete_event", lambda *a: None)
    monkeypatch.setattr(gcal, "create_event", lambda *a: "new-id")

    result = run_calendar_reconcile(store, settings, str(tmp_path), storage)

    assert result["ok"] is True
    assert len(result["limit_warnings"]) == 1
    assert result["limit_warnings"][0]["iso_week"] == 19


def test_imported_reservation_under_limit_no_warning(tmp_path, monkeypatch):
    from src import gcal

    settings = _settings(
        tmp_path,
        werkstudent_limit_enabled=True,
        werkstudent_limit_start="2026-04-01",
        werkstudent_limit_end="2026-07-15",
        werkstudent_limit_max_hours=20.0,
    )
    store = ReservationStore(str(tmp_path / "res.json"))
    storage = Storage(str(tmp_path / "ze.json"))  # keine Ist-Zeit erfasst

    monkeypatch.setattr(gcal, "get_calendar_service", lambda *a, **k: object())
    monkeypatch.setattr(
        gcal, "list_app_events",
        lambda s, c: [{"date": "2026-05-06", "start": "09:00", "end": "10:00",
                       "kategorie": "", "modified_at": "2026-05-01T00:00:00Z",
                       "event_id": "evt-1"}])
    monkeypatch.setattr(gcal, "update_event", lambda *a: None)
    monkeypatch.setattr(gcal, "delete_event", lambda *a: None)
    monkeypatch.setattr(gcal, "create_event", lambda *a: "new-id")

    result = run_calendar_reconcile(store, settings, str(tmp_path), storage)

    assert result["limit_warnings"] == []
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_main.py -v`
Expected: FAIL — `TypeError: run_calendar_reconcile() takes 3 positional arguments but 4 were given`.

- [ ] **Step 3: `run_calendar_reconcile` erweitern**

In `src/main.py` Zeilen 241-268 komplett ersetzen:

```python
def run_calendar_reconcile(reservation_store, settings, base, storage):
    """Baut den Calendar-Service und fährt einen Reservierungs-Reconcile.

    Liefert {"ok": bool, "error": str, "tb": str, "limit_warnings": [...]}.
    Wirft NICHT — der Caller (UI-Thread) wertet das Dict aus. No-op, wenn
    gcal deaktiviert oder kein Kalender gewählt ist.

    limit_warnings (#98): Werkstudenten-Wochenlimit-Ergebnis (siehe
    weekly_limit.py) für die ISO-Wochen frisch importierter Reservierungs-
    Slots — geprüft werden dabei ausschließlich bereits erfasste Ist-Zeiten
    (storage), nicht die importierten Reservierungen selbst.
    """
    from src import gcal
    from src.reservations_sync import reconcile_reservations
    from src.weekly_limit import check_dates_for_warnings

    if not settings.get("gcal_enabled"):
        return {"ok": True, "error": "", "tb": "", "limit_warnings": []}
    calendar_id = settings.get("gcal_calendar_id")
    if not calendar_id:
        return {"ok": True, "error": "", "tb": "", "limit_warnings": []}

    try:
        service = gcal.get_calendar_service(
            os.path.join(base, "credentials.json"),
            os.path.join(base, "token.json"),
            sync_enabled=settings.get("sync_enabled"),
        )
        result = reconcile_reservations(service, calendar_id, reservation_store, settings)
        limit_warnings = check_dates_for_warnings(
            settings, storage.get_all(), result["imported_dates"])
        return {"ok": True, "error": "", "tb": "", "limit_warnings": limit_warnings}
    except Exception as e:
        logging.getLogger(__name__).exception("Kalender-Reconcile fehlgeschlagen")
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "tb": traceback.format_exc(), "limit_warnings": []}
```

- [ ] **Step 4: Tests laufen lassen, Erfolg bestätigen**

Run: `pytest tests/test_main.py -v`
Expected: PASS (3 Tests).

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat(main): Wochenlimit-Check im Kalender-Reconcile (#98)"
```

---

## Task 6: `BackgroundTaskRunner` — Storage durchreichen, Ergebnis mit `limit_warnings` an `on_ok`

**Files:**
- Modify: `src/background_tasks.py:22-29` (`__init__`), `src/background_tasks.py:127-157` (`reconcile_on_start`, `trigger_reconcile`)
- Test: `tests/test_background_tasks.py`

**Interfaces:**
- Ändert Signatur: `BackgroundTaskRunner.__init__(self, marshal, settings, base_path, reservation_store, reservations_active, storage=None)` — neuer optionaler 6. Parameter
- Ändert Contract: `reconcile_on_start(self, on_ok)` — `on_ok` wird jetzt mit `on_ok(result)` aufgerufen (vorher `on_ok()`, kein Argument)
- `trigger_reconcile(self, on_done)` bleibt unverändert im Contract (`on_done(result)` bereits bisher so)

- [ ] **Step 1: Failing Tests schreiben**

In `tests/test_background_tasks.py` die `_runner()`-Helper-Funktion (Zeilen 9-18) erweitern:

```python
def _runner(**overrides):
    kw = dict(
        marshal=lambda cb: cb(),          # synchron ausfuehren
        settings=overrides.pop("settings", {}),
        base_path=overrides.pop("base_path", "."),
        reservation_store=overrides.pop("reservation_store", None),
        reservations_active=overrides.pop("reservations_active", lambda: False),
        storage=overrides.pop("storage", None),
    )
    kw.update(overrides)
    return BackgroundTaskRunner(**kw)
```

Bestehenden Test `test_reconcile_on_start_skips_when_reservations_inactive` (Zeilen 61-67) anpassen — `on_ok` erwartet jetzt ein Argument:

```python
def test_reconcile_on_start_skips_when_reservations_inactive():
    ran = {"n": 0}
    r = _runner(reservations_active=lambda: False)
    r.reconcile_on_start(on_ok=lambda result: ran.__setitem__("n", ran["n"] + 1))
    import time
    time.sleep(0.2)
    assert ran["n"] == 0
```

Zwei neue Tests ans Dateiende anhängen:

```python
def test_reconcile_on_start_passes_storage_and_result_to_on_ok(monkeypatch):
    import src.main as main_module

    captured = {}

    def fake_reconcile(reservation_store, settings, base_path, storage):
        captured["storage"] = storage
        return {"ok": True, "error": "", "tb": "", "limit_warnings": ["w"]}

    monkeypatch.setattr(main_module, "run_calendar_reconcile", fake_reconcile)

    received = {}
    sentinel_storage = object()
    r = _runner(reservations_active=lambda: True, storage=sentinel_storage)
    r.reconcile_on_start(on_ok=lambda result: received.__setitem__("result", result))

    import time
    time.sleep(0.2)
    assert captured["storage"] is sentinel_storage
    assert received["result"]["limit_warnings"] == ["w"]


def test_trigger_reconcile_passes_storage_through(monkeypatch):
    import src.main as main_module

    captured = {}

    def fake_reconcile(reservation_store, settings, base_path, storage):
        captured["storage"] = storage
        return {"ok": True, "error": "", "tb": "", "limit_warnings": []}

    monkeypatch.setattr(main_module, "run_calendar_reconcile", fake_reconcile)

    done = threading.Event()
    sentinel_storage = object()
    r = _runner(reservations_active=lambda: True, storage=sentinel_storage)
    r.trigger_reconcile(lambda result: done.set())

    assert done.wait(timeout=5)
    assert captured["storage"] is sentinel_storage
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_background_tasks.py -v`
Expected: FAIL — `TypeError: BackgroundTaskRunner.__init__() got an unexpected keyword argument 'storage'`.

- [ ] **Step 3: `BackgroundTaskRunner` erweitern**

In `src/background_tasks.py` `__init__` (Zeilen 22-29) ersetzen:

```python
class BackgroundTaskRunner:
    def __init__(self, marshal, settings, base_path, reservation_store,
                 reservations_active, storage=None):
        self._marshal = marshal                          # App._marshal_to_ui
        self._settings = settings
        self._base_path = base_path
        self._reservation_store = reservation_store
        self._reservations_active = reservations_active  # callable -> bool
        self._storage = storage
```

`reconcile_on_start` (Zeilen 127-143) ersetzen:

```python
    def reconcile_on_start(self, on_ok):
        """Gleicht beim Start die Reservierungen mit dem Google Kalender ab.
        Fehler werden STILL geloggt (Offline-Start nicht stoeren); bei Erfolg
        on_ok(result) im UI-Thread (result enthaelt u.a. limit_warnings, #98)."""
        if not self._reservations_active():
            return

        def fn():
            from src.main import run_calendar_reconcile  # lazy: Circular-Import-Schutz
            return run_calendar_reconcile(
                self._reservation_store, self._settings, self._base_path, self._storage)

        def on_done(result):
            if result.get("ok"):
                on_ok(result)

        self.run(fn, on_done)
```

`trigger_reconcile` (Zeilen 145-157): nur den `fn()`-Aufruf innerhalb anpassen:

```python
    def trigger_reconcile(self, on_done):
        """Stoesst nach einer Reservierungsaenderung den Abgleich an. Das
        Ergebnis geht IMMER an on_done(result) (User hat aktiv gespeichert und
        erwartet Feedback)."""
        if not self._reservations_active():
            return

        def fn():
            from src.main import run_calendar_reconcile  # lazy: Circular-Import-Schutz
            return run_calendar_reconcile(
                self._reservation_store, self._settings, self._base_path, self._storage)

        self.run(fn, on_done)
```

- [ ] **Step 4: Tests laufen lassen, Erfolg bestätigen**

Run: `pytest tests/test_background_tasks.py -v`
Expected: PASS (alle bestehenden + 2 neue Tests).

- [ ] **Step 5: Commit**

```bash
git add src/background_tasks.py tests/test_background_tasks.py
git commit -m "feat(background-tasks): Storage durchreichen für Wochenlimit-Check (#98)"
```

---

## Task 7: `ui.py` — Storage verdrahten, Wochenlimit-Warnung anzeigen

**Files:**
- Modify: `src/ui.py:12-30` (Imports), `src/ui.py:115-118` (`BackgroundTaskRunner`-Instanziierung), `src/ui.py:167` (`reconcile_on_start`-Aufruf), `src/ui.py:178-200` (`_on_reconcile_done`)

**Interfaces:**
- Consumes: `format_limit_warnings(warnings)` (Task 2), `themed_showwarning(parent, title, message)` (bestehend, `theme.py`)
- Produziert: `App._show_limit_warnings(self, warnings)`, `App._on_reconcile_start_done(self, result)`

Kein neuer automatisierter Test: `App`-Methoden sind Tk-Root-gebunden und werden im bestehenden Code nicht direkt unit-getestet (`tests/test_ui_*.py` testet ausschließlich reine, aus `ui.py`/`sync_orchestrator.py` extrahierte Helper-Funktionen wie `_classify_sync_error`). `_on_reconcile_done` hat schon vor diesem Task keine direkte Testabdeckung — dieselbe Konvention gilt für die beiden neuen Methoden.

- [ ] **Step 1: Imports erweitern**

In `src/ui.py` Zeile 25-30 (theme-Import) `themed_showwarning` ergänzen:

```python
from src.theme import (
    BG, ACCENT, TEXT, TEXT_MUTED,
    FONT_HEADER, FONT_FOOTER, FONT_SMALL, apply_dark_titlebar, themed_askyesno, themed_ask_delete_choice, themed_showerror, themed_showinfo,
    themed_showwarning,
    icon_button, secondary_button, set_toggle_active, toggle_button,
    _stray_click_suppressed,
)
```

Neue Zeile nach dem `background_tasks`-Import (nach Zeile 18) einfügen:

```python
from src.weekly_limit import format_limit_warnings
```

- [ ] **Step 2: `self.storage` in `BackgroundTaskRunner` verdrahten**

Zeilen 115-118 ersetzen:

```python
        self._bg = BackgroundTaskRunner(
            self._marshal_to_ui, self.settings, self.base_path,
            self.reservation_store, self._reservations_active, self.storage,
        )
```

- [ ] **Step 3: `reconcile_on_start`-Aufruf und `_on_reconcile_done` anpassen**

Zeile 167 ersetzen:

```python
        self._bg.reconcile_on_start(on_ok=self._on_reconcile_start_done)
```

Neue Methoden nach `_on_reconcile_done` (nach Zeile 200) einfügen, `_on_reconcile_done` selbst (Zeilen 178-200) um den Warnungs-Aufruf erweitern:

```python
    def _on_reconcile_done(self, result):
        if not result.get("ok"):
            error = result.get("error", "?")
            if _classify_sync_error(error) == "auth":
                themed_showinfo(
                    self.root,
                    "Google-Verbindung abgelaufen",
                    "Die Reservierung wurde lokal gespeichert. Der "
                    "Kalender-Abgleich ist fehlgeschlagen, weil die Verbindung "
                    "zu Google abgelaufen oder widerrufen wurde.\n\nBitte "
                    "verbinde die App in den Einstellungen neu (Google-Kalender "
                    "aus- und wieder einschalten). Der Abgleich wird danach "
                    "automatisch nachgeholt.",
                )
            else:
                messagebox.showerror(
                    "Google-Kalender-Abgleich fehlgeschlagen",
                    f"Die Reservierung wurde lokal gespeichert, der Kalender-Abgleich "
                    f"ist aber fehlgeschlagen:\n\n{error}\n\n"
                    f"{result.get('tb', '')}\n\n"
                    "Der Abgleich wird beim nächsten Start erneut versucht.",
                )
        self._refresh()
        self._show_limit_warnings(result.get("limit_warnings"))

    def _on_reconcile_start_done(self, result):
        self._refresh()
        self._show_limit_warnings(result.get("limit_warnings"))

    def _show_limit_warnings(self, warnings):
        if not warnings:
            return
        themed_showwarning(
            self.root, "Wochenlimit überschritten",
            "Der Kalender-Import betrifft Wochen über dem konfigurierten "
            f"Werkstudenten-Limit:\n\n{format_limit_warnings(warnings)}",
        )
```

- [ ] **Step 4: Bestehende Tests laufen lassen (Regression)**

Run: `pytest -v`
Expected: PASS — alle Tests (die Import-/Konstruktor-Änderungen an `ui.py` selbst sind ungetestet, aber `pytest` importiert `src.ui` transitiv über `tests/test_ui_delete.py` etc., ein Syntax-/Importfehler würde hier auffallen).

- [ ] **Step 5: Verify — manueller Durchlauf**

App manuell starten, Google-Kalender-Sync aktivieren (falls noch nicht per Task-3-Verify geschehen), Werkstudenten-Limit aktivieren mit knappem Limit, in Google Calendar einen Termin im konfigurierten Zeitraum anlegen, der auf eine Woche mit bereits erfassten (über dem Limit liegenden) Ist-Zeiten fällt, dann in der App einen Reservierungs-Sync auslösen (Tages-Dialog → Reservierung speichern, oder App-Neustart) → erwartet: nicht-blockierender Warn-Dialog „Wochenlimit überschritten" nach dem Sync, App bleibt bedienbar.

- [ ] **Step 6: Commit**

```bash
git add src/ui.py
git commit -m "feat(ui): Wochenlimit-Warnung nach Kalender-Sync anzeigen (#98)"
```

---

## Task 8: Settings-Dialog — Werkstudenten-Limit-Sektion + einmaliger Zeitraum-Scan

**Files:**
- Modify: `src/dialogs/settings_dialog.py:1-25` (Imports), `src/dialogs/settings_dialog.py:773-781` (Einfügepunkt neue Sektion, vor `if settings.get("gcal_enabled")`), `src/dialogs/settings_dialog.py:785-856` (`save_settings`, Button-Frame-Row)

**Interfaces:**
- Consumes: `scan_period_for_warnings(settings, all_entries)`, `format_limit_warnings(warnings)`, `period_scan_needed(old, new)` (Task 2), `validate_period(date_from, date_to)` (bestehend, `time_utils.py`)

Kein neuer automatisierter Test: `open_settings_dialog` ist komplett Tk-Root-gebunden, es existiert keine `tests/test_settings_dialog.py` und kein etabliertes Muster dafür im Repo. Die Kernlogik (`scan_period_for_warnings`) ist über Task 2 vollständig getestet; dieser Task verdrahtet sie nur in die UI.

- [ ] **Step 1: Imports erweitern**

In `src/dialogs/settings_dialog.py` Zeilen 1-6 ergänzen (neue Top-Level-Imports `calendar`, `datetime`):

```python
import calendar
import datetime
import logging
import os
import threading
import tkinter as tk
import traceback
from tkinter import messagebox, ttk
from typing import Any
```

Zeile 24-25 (time_utils-Import) erweitern:

```python
from src.time_utils import format_iso_date, validate_period
from src.time_utils import DAYS_DE, validate_entry
from src.weekly_limit import format_limit_warnings, period_scan_needed, scan_period_for_warnings
```

- [ ] **Step 2: Neue Sektion „Werkstudenten-Limit" einfügen**

Vor Zeile 782 (`if settings.get("gcal_enabled"):`) — also direkt nach `cb_gcal.grid(row=30, ...)` (Zeile 780) und vor dem `if`-Block — folgenden Block einfügen:

```python
    # --- Werkstudenten-Limit (Wochenstunden-Grenze für einen Zeitraum, #98) ---
    wsl_header, wsl_widgets, wsl_toggle = _section_header(
        "Werkstudenten-Limit", row=34, top_pad=16)
    wsl_frame = tk.Frame(dialog, bg=BG)
    wsl_frame.grid(row=35, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="we")
    wsl_widgets.append(wsl_frame)

    wsl_enabled_var = tk.BooleanVar(value=settings.get("werkstudent_limit_enabled"))
    tk.Checkbutton(
        wsl_frame, text="Wochenstunden-Limit aktivieren", variable=wsl_enabled_var,
        font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT, cursor="hand2",
    ).pack(anchor="w")

    def _wsl_date_row(parent, label_text, default_date):
        row = tk.Frame(parent, bg=BG)
        row.pack(anchor="w", pady=(4, 0))
        tk.Label(row, text=label_text, font=FONT, bg=BG, fg=TEXT).pack(
            side=tk.LEFT, padx=(0, 5))
        month_values = [str(m) for m in range(1, 13)]
        year_values = [str(y) for y in range(2020, datetime.date.today().year + 3)]
        day_var = tk.StringVar(value=str(default_date.day))
        max_day = calendar.monthrange(default_date.year, default_date.month)[1]
        day_cb = dark_combo(row, day_var, [str(d) for d in range(1, max_day + 1)], width=3)
        day_cb.pack(side=tk.LEFT, padx=2)
        tk.Label(row, text=".", font=FONT, bg=BG, fg=TEXT).pack(side=tk.LEFT)
        month_var = tk.StringVar(value=str(default_date.month))
        dark_combo(row, month_var, month_values, width=3).pack(side=tk.LEFT, padx=2)
        tk.Label(row, text=".", font=FONT, bg=BG, fg=TEXT).pack(side=tk.LEFT)
        year_var = tk.StringVar(value=str(default_date.year))
        dark_combo(row, year_var, year_values, width=5).pack(side=tk.LEFT, padx=2)

        def _update_days(*_a):
            try:
                m = int(month_var.get())
                y = int(year_var.get())
                md = calendar.monthrange(y, m)[1]
            except (ValueError, KeyError):
                md = 31
            day_cb["values"] = [str(d) for d in range(1, md + 1)]
            if int(day_var.get()) > md:
                day_var.set(str(md))

        month_var.trace_add("write", _update_days)
        year_var.trace_add("write", _update_days)
        return day_var, month_var, year_var

    wsl_start_default = (
        datetime.date.fromisoformat(settings.get("werkstudent_limit_start"))
        if settings.get("werkstudent_limit_start") else datetime.date.today())
    wsl_end_default = (
        datetime.date.fromisoformat(settings.get("werkstudent_limit_end"))
        if settings.get("werkstudent_limit_end") else datetime.date.today())
    wsl_start_vars = _wsl_date_row(wsl_frame, "Zeitraum von:", wsl_start_default)
    wsl_end_vars = _wsl_date_row(wsl_frame, "bis:", wsl_end_default)

    wsl_hours_row = tk.Frame(wsl_frame, bg=BG)
    wsl_hours_row.pack(anchor="w", pady=(4, 0))
    tk.Label(wsl_hours_row, text="Limit (Stunden/Woche):", font=FONT, bg=BG, fg=TEXT).pack(
        side=tk.LEFT, padx=(0, 5))
    wsl_hours_var = tk.StringVar(value=str(settings.get("werkstudent_limit_max_hours")))
    dark_entry(wsl_hours_row, wsl_hours_var, width=6).pack(side=tk.LEFT)

```

- [ ] **Step 3: Button-Frame-Row verschieben**

Zeile 856 (`btn_frame.grid(row=33, column=0, columnspan=2, pady=12)`) ersetzen:

```python
    btn_frame.grid(row=36, column=0, columnspan=2, pady=12)
```

- [ ] **Step 4: `save_settings()` um Persistenz + einmaligen Zeitraum-Scan erweitern**

Zu Beginn von `save_settings()` (nach der bestehenden Zeit-Validierungsschleife, vor Zeile 796 `new_autostart = autostart_var.get()`) Zeitraum-Validierung und Werte-Parsing einfügen:

```python
        wsl_start_date = datetime.date(
            int(wsl_start_vars[2].get()), int(wsl_start_vars[1].get()),
            int(wsl_start_vars[0].get()))
        wsl_end_date = datetime.date(
            int(wsl_end_vars[2].get()), int(wsl_end_vars[1].get()),
            int(wsl_end_vars[0].get()))
        wsl_start_iso = wsl_start_date.isoformat()
        wsl_end_iso = wsl_end_date.isoformat()
        if wsl_enabled_var.get():
            ok, msg = validate_period(wsl_start_iso, wsl_end_iso)
            if not ok:
                themed_showerror(dialog, "Werkstudenten-Limit-Zeitraum ungültig", msg)
                return
        old_wsl_max_hours = settings.get("werkstudent_limit_max_hours")
        try:
            wsl_max_hours = float(wsl_hours_var.get())
        except ValueError:
            wsl_max_hours = old_wsl_max_hours

        old_wsl_enabled = settings.get("werkstudent_limit_enabled")
        old_wsl_start = settings.get("werkstudent_limit_start")
        old_wsl_end = settings.get("werkstudent_limit_end")
```

In das bestehende `updates`-Dict (Zeilen 821-836) vor der schließenden `}` ergänzen:

```python
            "werkstudent_limit_enabled": wsl_enabled_var.get(),
            "werkstudent_limit_start": wsl_start_iso,
            "werkstudent_limit_end": wsl_end_iso,
            "werkstudent_limit_max_hours": wsl_max_hours,
```

Nach `settings.apply_updates(updates)` (Zeile 840) und vor `on_change()`/`dialog.destroy()` (Zeilen 850-851) den einmaligen Zeitraum-Scan einfügen:

```python
        old_wsl = {
            "enabled": old_wsl_enabled, "start": old_wsl_start, "end": old_wsl_end,
            "max_hours": old_wsl_max_hours,
        }
        new_wsl = {
            "enabled": wsl_enabled_var.get(), "start": wsl_start_iso, "end": wsl_end_iso,
            "max_hours": wsl_max_hours,
        }
        if storage is not None and period_scan_needed(old_wsl, new_wsl):
            period_warnings = scan_period_for_warnings(settings, storage.get_all())
            if period_warnings:
                themed_showwarning(
                    dialog, "Wochenlimit überschritten",
                    "Im konfigurierten Zeitraum liegen bereits erfasste Wochen über "
                    f"dem Limit:\n\n{format_limit_warnings(period_warnings)}",
                )

```

- [ ] **Step 5: Bestehende Tests laufen lassen (Regression)**

Run: `pytest -v`
Expected: PASS — alle Tests (Syntax-/Importfehler in `settings_dialog.py` würden über die transitive `src.ui`-Importkette in `tests/test_ui_delete.py` etc. auffallen).

- [ ] **Step 6: Verify — manueller Durchlauf**

App manuell starten (`python -m src.main`), Einstellungen öffnen:
1. Sektion „Werkstudenten-Limit" ist sichtbar, standardmäßig eingeklappt-Verhalten wie andere Sektionen, Checkbox aus, Zeitraum-Felder auf heute, Limit-Feld zeigt „20.0".
2. Für eine bereits mit Ist-Zeiten befüllte Woche: Limit aktivieren, Zeitraum so wählen, dass diese Woche darin liegt, Limit niedriger als die erfasste Wochensumme setzen, Speichern klicken → erwartet: Warn-Dialog „Wochenlimit überschritten" erscheint EINMALIG direkt nach dem Speichern.
3. Dialog erneut öffnen, OHNE Zeitraum/Aktivierung zu ändern (nur z.B. Namen ändern), Speichern → erwartet: KEIN erneuter Warn-Dialog (weder Aktivierung noch Zeitraum haben sich geändert).
4. Zeitraum ändern (z.B. Enddatum), Speichern → erwartet: Warn-Dialog erscheint erneut, falls weiterhin überschrittene Wochen im (neuen) Zeitraum liegen.
5. Limit bei unverändertem Zeitraum senken (z.B. von 20h auf 10h) für eine Woche, die bereits mit Ist-Zeiten über dem neuen (aber unter dem alten) Limit liegt, Speichern → erwartet: Warn-Dialog erscheint trotz unverändertem Zeitraum/unveränderter Aktivierung (Adversarial-Review-Fix, Task 2 `period_scan_needed`).
6. Ungültigen Zeitraum eingeben (von nach bis) bei aktiviertem Limit, Speichern → erwartet: Fehlerdialog „Werkstudenten-Limit-Zeitraum ungültig", nichts wird gespeichert.

- [ ] **Step 7: Commit**

```bash
git add src/dialogs/settings_dialog.py
git commit -m "feat(settings-dialog): Werkstudenten-Limit-Sektion + Zeitraum-Scan (#98)"
```

---

## Übergabe

**VERHALTEN:** Neues, per Default deaktiviertes Wochenstunden-Limit für einen konfigurierbaren Zeitraum. Aktiv warnt es (bypassbar) beim manuellen Speichern einer Ist-Zeit und (nicht-blockierend, informativ) nach einem automatischen Kalender-Sync, wenn die Ist-Stunden-Summe (alle Kategorien) einer ISO-Woche das Limit überschreitet. Reservierungen selbst zählen nicht in die Summe. Ein vollständiger Zeitraum-Scan läuft einmalig beim Aktivieren/Ändern des Zeitraums in den Einstellungen.

**RISIKO:** Vier neue Sync-Settings-Keys (`werkstudent_limit_*`) — reisen über Drive-Sync mit, ältere App-Versionen ignorieren sie folgenlos (verifiziert über bestehende Whitelist-Mechanik, kein Schema-Bump nötig). `run_calendar_reconcile`/`BackgroundTaskRunner`/`merge_reservations`/`reconcile_reservations` haben neue Parameter/Rückgabewerte — betrifft nur interne Aufrufer (alle in diesem Plan mit-aktualisiert), keine externe Schnittstelle. Bei deaktiviertem Feature (Default) ist jeder neue Codepfad ein reines No-op.

**TEST je Schritt:** siehe „Verify"-Schritte in Task 3, 7, 8 (manuelle Durchläufe, da UI-Closures im Repo grundsätzlich nicht unit-getestet werden) sowie die automatisierten Tests in Task 1, 2, 4, 5, 6 (`pytest`).

Nach Abschluss aller Tasks: vollen Testlauf + Lint fahren:

```bash
pytest
ruff check .
```
