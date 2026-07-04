# Settings-Dialog Aufteilung pro Tab (Audit H4) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die ~900-Zeilen-Funktion `open_settings_dialog` in ein Paket `src/dialogs/settings_dialog/` mit vier Tab-Klassen-Modulen zerlegen — verhaltensgleich, ohne einen einzigen Logik- oder UI-Unterschied.

**Architecture:** Reiner Code-Move: `settings_dialog.py` wird Paket; jede Tab-Klasse bekommt den bestehenden Abschnitts-Code **verbatim** in ihren `__init__` (lokale Namen und verschachtelte Closures bleiben unangetastet — nur der Frame-Name wird zu `frame` und am Ende werden die Vertrags-Attribute per `self.x = x` exponiert). `save_settings` bleibt zentral in `dialog.py`, liest die Variablen aber über Tab-Handles (`work.start_vars` statt Closure-Scope). Import-Pfade bleiben über `__init__.py`-Re-Exports stabil.

**Tech Stack:** Python 3.14, Tkinter, pytest, ruff. Keine neuen Dependencies.

## Global Constraints

- **Verhaltensgleich pro Stelle** (Spec): kein Logik-, Text-, Layout- oder Reihenfolge-Unterschied. Auch keine Gelegenheits-Fixes (hartkodierter Font `("Segoe UI", 8)`, M14-Duplikate, M10 — notieren, nicht fixen).
- **`save_settings` bleibt zentral und ablaufidentisch** in `dialog.py`; nur Variablen-Zugriffe wechseln auf Tab-Attribute.
- **Move-Technik:** Abschnitts-Code verbatim in `__init__` verschieben; innerhalb des verschobenen Blocks NUR den Tab-Frame-Namen ersetzen (`tab_work` → `frame` usw.); Vertrags-Attribute am Ende des `__init__` als `self.x = x`-Zuweisungen. Interne Closures/Locals NICHT auf `self._x` umschreiben.
- **H5-Invarianten unangetastet:** die `runner.run`-Worker, `winfo_exists`-Guards und Persistenz-im-`fn` ziehen unverändert mit um.
- **Import-Stabilität:** `from src.dialogs.settings_dialog import open_settings_dialog` (ui.py) funktioniert nach jedem Task; `build_oauth_enable_task` bleibt aus dem Paket importierbar.
- **Nach jedem Task grün:** `.venv/Scripts/python.exe -m pytest -q` → 750 passed / 3 skipped; `.venv/Scripts/python.exe -m ruff check .` → clean; Import-Smoke `.venv/Scripts/python.exe -c "import src.ui; print('ok')"`.
- **Zeilennummern** in den Tasks beziehen sich auf `src/dialogs/settings_dialog.py` @ Branch-Start (Commit von H5, 977 Zeilen). Nach Task 1 heißt die Datei `src/dialogs/settings_dialog/dialog.py` und die Nummern verschieben sich um ~44 nach oben — **die Banner-Kommentare `# ===================== Tab: … =====================` sind die verlässlichen Anker**, immer zuerst den umgebenden Code verifizieren.

Design-Referenz: `docs/superpowers/specs/2026-07-04-settings-dialog-split-design.md`.

---

## Task 1: Paket-Skelett — Datei-Move + `oauth_task.py` + Re-Exports

`settings_dialog.py` → `settings_dialog/dialog.py` (inhaltlich unverändert bis auf den Auszug von `build_oauth_enable_task`), neues Modul `oauth_task.py`, `__init__.py`-Re-Exports, Test-Import angepasst. Noch keine Tab-Extraktion.

**Files:**
- Move: `src/dialogs/settings_dialog.py` → `src/dialogs/settings_dialog/dialog.py` (per `git mv`)
- Create: `src/dialogs/settings_dialog/__init__.py`
- Create: `src/dialogs/settings_dialog/oauth_task.py`
- Modify: `tests/test_settings_dialog.py:1-8` (Import-Kopf)

**Interfaces:**
- Consumes: nichts.
- Produces: Paket `src.dialogs.settings_dialog` mit `open_settings_dialog` (aus `.dialog`) und `build_oauth_enable_task` (aus `.oauth_task`) im `__init__`-Namespace. `dialog.py` importiert `from src.dialogs.settings_dialog.oauth_task import build_oauth_enable_task`.

- [ ] **Step 1: Datei in Paket verschieben**

```bash
mkdir -p src/dialogs/settings_dialog
git mv src/dialogs/settings_dialog.py src/dialogs/settings_dialog/dialog.py
```

- [ ] **Step 2: `oauth_task.py` anlegen — `build_oauth_enable_task` ausschneiden**

Aus `src/dialogs/settings_dialog/dialog.py` die komplette Funktion `build_oauth_enable_task` (Original-Z. 32–72, inkl. Docstring) **ausschneiden** und in die neue Datei einfügen:

```python
# src/dialogs/settings_dialog/oauth_task.py
"""Generischer (fn, on_done)-Builder für OAuth-Aktivieren-Toggles (Audit H5).

Eigenes Modul (statt tab_google), weil der Builder keinen Tab-Bezug hat und
tests/test_settings_dialog.py sein messagebox im Funktions-Modul monkeypatcht.
"""

import traceback
from tkinter import messagebox


<hier die ausgeschnittene Funktion build_oauth_enable_task 1:1 einfügen>
```

In `dialog.py` dafür den Import ergänzen (bei den `from src...`-Imports):

```python
from src.dialogs.settings_dialog.oauth_task import build_oauth_enable_task
```

`dialog.py`-Importkopf prüfen: `traceback` und `messagebox` werden dort weiterhin gebraucht (Google-Tab-Worker) — **nicht** entfernen.

- [ ] **Step 3: `__init__.py` anlegen**

```python
# src/dialogs/settings_dialog/__init__.py
"""Einstellungen-Dialog als Paket (Audit H4): dialog.py trägt Chrome +
zentrales save_settings, die vier Tabs sind eigene Klassen-Module.
Öffentliche API unverändert re-exportiert."""

from src.dialogs.settings_dialog.dialog import open_settings_dialog
from src.dialogs.settings_dialog.oauth_task import build_oauth_enable_task

__all__ = ["open_settings_dialog", "build_oauth_enable_task"]
```

- [ ] **Step 4: Test-Import anpassen**

In `tests/test_settings_dialog.py` den Kopf (Z. 4–8):

```python
from unittest.mock import MagicMock

import src.dialogs.settings_dialog as sd
from src.dialogs.settings_dialog import build_oauth_enable_task
```

ersetzen durch (Alias `sd` bleibt, damit die `monkeypatch.setattr(sd.messagebox, …)`-Aufrufe im Rest der Datei unverändert weiter funktionieren — sie müssen das Modul patchen, in dem die Funktion lebt):

```python
from unittest.mock import MagicMock

import src.dialogs.settings_dialog.oauth_task as sd
from src.dialogs.settings_dialog.oauth_task import build_oauth_enable_task
```

- [ ] **Step 5: Suite + Ruff + Import-Smoke**

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -c "import src.ui; print('ok')"
```
Expected: 750 passed / 3 skipped; All checks passed; `ok`.

- [ ] **Step 6: Commit**

```bash
git add -A src/dialogs/settings_dialog tests/test_settings_dialog.py
git commit -m "refactor(settings): settings_dialog als Paket — dialog.py + oauth_task.py + Re-Exports (H4 Schritt 1)"
```

---

## Task 2: `_shared.py` + `WorkTab`

Grid-Helfer `label`/`subheader` in `_shared.py`; Arbeitszeit-Tab als `WorkTab`-Klasse. `dialog.py` verliert seine lokalen Helfer-Defs (die verbleibenden Inline-Tabs nutzen ab jetzt die importierten — identische Signatur, identisches Verhalten).

**Files:**
- Create: `src/dialogs/settings_dialog/_shared.py`
- Create: `src/dialogs/settings_dialog/tab_work.py`
- Modify: `src/dialogs/settings_dialog/dialog.py` (Helfer-Defs raus, Work-Block raus, `WorkTab` instanziieren, `save_settings`-Zugriffe umstellen)

**Interfaces:**
- Consumes: Paketstruktur aus Task 1.
- Produces:
  - `_shared.label(parent_frame, text, row, col=0, **grid_kw)` und `_shared.subheader(parent_frame, text, row, top_pad=16)` — byte-gleich zu Original-Z. 109–120.
  - `WorkTab(frame, dialog, settings)` mit Attributen `frame`, `start_vars`, `end_vars` (je `dict[str, tk.StringVar]`), `pause_var`, `wsl_enabled_var`, `wsl_start_vars`, `wsl_end_vars` (je `(day, month, year)`-Tupel von `tk.StringVar`), `wsl_hours_var`.

- [ ] **Step 1: `_shared.py` anlegen**

```python
# src/dialogs/settings_dialog/_shared.py
"""Gemeinsame Grid-Helfer der Settings-Tabs (label/subheader)."""

import tkinter as tk
from typing import Any

from src.theme import BG, FONT, FONT_BOLD, TEXT, TEXT_MUTED


def label(parent_frame, text, row, col=0, **grid_kw):
    kw: dict[str, Any] = dict(padx=10, pady=8, sticky="w")
    kw.update(grid_kw)
    lbl = tk.Label(parent_frame, text=text, font=FONT, bg=BG, fg=TEXT)
    lbl.grid(row=row, column=col, **kw)
    return lbl


def subheader(parent_frame, text, row, top_pad=16):
    tk.Label(
        parent_frame, text=f"— {text} —", font=FONT_BOLD,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=row, column=0, columnspan=2, padx=10, pady=(top_pad, 4))
```

- [ ] **Step 2: `tab_work.py` anlegen — Work-Block verbatim verschieben**

Neue Datei mit dieser Struktur; der Body ist der **verbatim ausgeschnittene** Block von Original-Z. 123–212 (Anker: von `label(tab_work, "Standardzeiten:", …)` bis einschließlich des „Kategorien verwalten"-`secondary_button`-Blocks). Im verschobenen Block **einzige Änderung:** jedes `tab_work` → `frame`.

```python
# src/dialogs/settings_dialog/tab_work.py
"""Tab „Arbeitszeit": Standardzeiten, Pause, Werkstudenten-Limit, Kategorien."""

import calendar
import datetime
import tkinter as tk

from src.dialogs.category_dialog import open_category_dialog
from src.dialogs.settings_dialog._shared import label, subheader
from src.settings import WEEKDAY_KEYS
from src.theme import (
    BG, CELL_BG, FONT, FONT_SMALL, PAUSE_VALUES, TEXT, TEXT_MUTED,
    TIME_VALUES, dark_combo, dark_entry, secondary_button,
)
from src.time_utils import DAYS_DE


class WorkTab:
    """Baut den Arbeitszeit-Tab; exponiert die Tk-Variablen, die
    save_settings in dialog.py liest (Vertrag siehe Spec H4)."""

    def __init__(self, frame, dialog, settings):
        <verbatim verschobener Block Z. 123–212, tab_work→frame>

        self.frame = frame
        self.start_vars = start_vars
        self.end_vars = end_vars
        self.pause_var = pause_var
        self.wsl_enabled_var = wsl_enabled_var
        self.wsl_start_vars = wsl_start_vars
        self.wsl_end_vars = wsl_end_vars
        self.wsl_hours_var = wsl_hours_var
```

Hinweis: `_wsl_date_row` bleibt als verschachtelte Funktion im `__init__` (Move-Technik, Global Constraints); `dialog` wird nur vom „Kategorien verwalten"-Lambda genutzt.

- [ ] **Step 3: `dialog.py` umbauen**

1. Die lokalen Defs `label` (Z. 109–114) und `subheader` (Z. 116–120) **löschen**; Import ergänzen: `from src.dialogs.settings_dialog._shared import label, subheader`. (Mail/Google/App-Blöcke rufen sie mit identischer Signatur weiter auf.)
2. Den Work-Block (Z. 122–212 inkl. Banner-Kommentar) **ersetzen** durch:
   ```python
   # ===================== Tab: Arbeitszeit =====================
   work = WorkTab(tab_work, dialog, settings)
   ```
   Import ergänzen: `from src.dialogs.settings_dialog.tab_work import WorkTab`.
3. In `save_settings` und im `tabs`-Dict die Work-Zugriffe umstellen (Substitutionstabelle — gilt für **jede** Vorkommnis in `dialog.py`):

   | alt | neu |
   |---|---|
   | `start_vars` | `work.start_vars` |
   | `end_vars` | `work.end_vars` |
   | `pause_var` | `work.pause_var` |
   | `wsl_enabled_var` | `work.wsl_enabled_var` |
   | `wsl_start_vars` | `work.wsl_start_vars` |
   | `wsl_end_vars` | `work.wsl_end_vars` |
   | `wsl_hours_var` | `work.wsl_hours_var` |
   | `tabs = {"work": tab_work, …}` | `tabs = {"work": work.frame, …}` (übrige Einträge unverändert) |

4. Import-Kopf von `dialog.py` trimmen: `calendar`, `open_category_dialog`, `PAUSE_VALUES`, `TIME_VALUES`, `dark_combo`*, `dark_entry`*, `DAYS_DE`* nur entfernen, wenn sie in `dialog.py` **nirgends mehr** vorkommen (`DAYS_DE` wird in `save_settings` Z. 841 weiter gebraucht → bleibt; `dark_combo`/`dark_entry` werden von Mail/Google/App-Blöcken noch gebraucht → bleiben vorerst). Verifikation per grep, nicht raten.

- [ ] **Step 4: Verifikation + grep**

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -c "import src.ui; print('ok')"
grep -n "start_vars\|wsl_" src/dialogs/settings_dialog/dialog.py
```
Expected: grün/clean/ok; alle grep-Treffer tragen das Präfix `work.`.

- [ ] **Step 5: Commit**

```bash
git add -A src/dialogs/settings_dialog
git commit -m "refactor(settings): WorkTab + _shared-Helfer extrahiert (H4 Schritt 2)"
```

---

## Task 3: `MailTab`

**Files:**
- Create: `src/dialogs/settings_dialog/tab_mail.py`
- Modify: `src/dialogs/settings_dialog/dialog.py`

**Interfaces:**
- Consumes: `_shared.label`, `_shared.subheader` (Task 2).
- Produces: `MailTab(frame, settings)` mit Attributen `frame`, `recipient_var`, `name_var`, `rate_var`, `subject_var`, `greeting_var`, `content_text` (tk.Text), `closing_text` (tk.Text).

- [ ] **Step 1: `tab_mail.py` anlegen — Mail-Block verbatim verschieben**

Block = Original-Z. 214–253 (Anker: Banner `# ===================== Tab: Bericht & Mail` bis zur Platzhalter-Hinweiszeile `…{zeitraum}, {gesamt}…` einschließlich). Einzige Änderung im Block: `tab_mail` → `frame`. Der hartkodierte Font `("Segoe UI", 8)` zieht **unverändert** mit (Audit-Randnotiz, bewusst kein Fix — Global Constraints).

```python
# src/dialogs/settings_dialog/tab_mail.py
"""Tab „Bericht & Mail": Empfänger, Name, Stundenlohn, Mail-Vorlage."""

import tkinter as tk

from src.dialogs.settings_dialog._shared import label, subheader
from src.theme import BG, FONT_SMALL, TEXT_MUTED, dark_entry, dark_text


class MailTab:
    """Baut den Bericht-&-Mail-Tab; exponiert die Variablen für save_settings."""

    def __init__(self, frame, settings):
        <verbatim verschobener Block Z. 214–253, tab_mail→frame>

        self.frame = frame
        self.recipient_var = recipient_var
        self.name_var = name_var
        self.rate_var = rate_var
        self.subject_var = subject_var
        self.greeting_var = greeting_var
        self.content_text = content_text
        self.closing_text = closing_text
```

(Import-Liste beim Verschieben gegen den tatsächlichen Block prüfen — sie muss exakt die im Block verwendeten Namen decken, nicht mehr.)

- [ ] **Step 2: `dialog.py` umbauen**

Mail-Block ersetzen durch `mail = MailTab(tab_mail, settings)` (Banner-Kommentar davor behalten); Import `from src.dialogs.settings_dialog.tab_mail import MailTab`. Substitutionen in `save_settings`:

| alt | neu |
|---|---|
| `recipient_var` | `mail.recipient_var` |
| `name_var` | `mail.name_var` |
| `rate_var` | `mail.rate_var` |
| `subject_var` | `mail.subject_var` |
| `greeting_var` | `mail.greeting_var` |
| `content_text` | `mail.content_text` |
| `closing_text` | `mail.closing_text` |
| `tabs`-Eintrag `"mail": tab_mail` | `"mail": mail.frame` |

Import-Kopf trimmen (nur grep-verifiziert; `dark_text` dürfte jetzt aus `dialog.py` verschwinden).

- [ ] **Step 3: Verifikation + Commit**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -c "import src.ui; print('ok')"
grep -n "recipient_var\|content_text\|closing_text" src/dialogs/settings_dialog/dialog.py
git add -A src/dialogs/settings_dialog
git commit -m "refactor(settings): MailTab extrahiert (H4 Schritt 3)"
```
Expected: grün/clean/ok; grep-Treffer nur mit `mail.`-Präfix.

---

## Task 4: `AppTab`

**Files:**
- Create: `src/dialogs/settings_dialog/tab_app.py`
- Modify: `src/dialogs/settings_dialog/dialog.py`

**Interfaces:**
- Consumes: `_shared.label`.
- Produces: `AppTab(frame, settings)` mit Attributen `frame`, `state_var`, `show_weekend_var`, `autostart_var`, `always_on_top_var`, `minimize_to_tray_var`, `scale_var` (tk.DoubleVar), `reminders_enabled_var`, `reminder_minutes_var`.

- [ ] **Step 1: `tab_app.py` anlegen — App-Block verbatim verschieben**

Block = Original-Z. 698–835 (Anker: Banner `# ===================== Tab: App` bis zur Hinweiszeile „Nur für Reservierungen mit Kategorie."). Änderungen im Block: `tab_app` → `frame`, und **eine** dokumentierte Äquivalenz-Anpassung: `ttk.Style(dialog)` (Original-Z. 767) → `ttk.Style(frame)` — ttk-Styles sind Interpreter-global, der Master dient nur der Interpreter-Bindung; `AppTab` braucht dadurch kein `dialog`-Handle (Spec-Festlegung).

```python
# src/dialogs/settings_dialog/tab_app.py
"""Tab „App": Bundesland, UI-Optionen, Skalierung, Benachrichtigungen."""

import tkinter as tk
from tkinter import ttk

from src.autostart import is_autostart_enabled
from src.dialogs.settings_dialog._shared import label
from src.holidays_de import STATES
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL, TEXT, TEXT_MUTED,
    dark_combo,
)


class AppTab:
    """Baut den App-Tab; exponiert die Variablen für save_settings."""

    def __init__(self, frame, settings):
        <verbatim verschobener Block Z. 698–835, tab_app→frame,
         ttk.Style(dialog)→ttk.Style(frame)>

        self.frame = frame
        self.state_var = state_var
        self.show_weekend_var = show_weekend_var
        self.autostart_var = autostart_var
        self.always_on_top_var = always_on_top_var
        self.minimize_to_tray_var = minimize_to_tray_var
        self.scale_var = scale_var
        self.reminders_enabled_var = reminders_enabled_var
        self.reminder_minutes_var = reminder_minutes_var
```

- [ ] **Step 2: `dialog.py` umbauen**

App-Block ersetzen durch `app = AppTab(tab_app, settings)`; Import `from src.dialogs.settings_dialog.tab_app import AppTab`. Substitutionen:

| alt | neu |
|---|---|
| `state_var` | `app.state_var` |
| `show_weekend_var` | `app.show_weekend_var` |
| `autostart_var` | `app.autostart_var` |
| `always_on_top_var` | `app.always_on_top_var` |
| `minimize_to_tray_var` | `app.minimize_to_tray_var` |
| `scale_var` | `app.scale_var` |
| `reminders_enabled_var` | `app.reminders_enabled_var` |
| `reminder_minutes_var` | `app.reminder_minutes_var` |
| `tabs`-Eintrag `"app": tab_app` | `"app": app.frame` |

Achtung Import-Trim: `is_autostart_enabled` wird in `save_settings` (Z. 877 `old_autostart = is_autostart_enabled()`) **weiter gebraucht** → bleibt in `dialog.py`. `STATES` verschwindet aus `dialog.py` (`code_for_state_label` bleibt). Grep-verifizieren.

- [ ] **Step 3: Verifikation + Commit**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -c "import src.ui; print('ok')"
grep -n "state_var\|scale_var\|autostart_var\|minimize_to_tray\|reminders_enabled\|reminder_minutes" src/dialogs/settings_dialog/dialog.py
git add -A src/dialogs/settings_dialog
git commit -m "refactor(settings): AppTab extrahiert (H4 Schritt 4)"
```
Expected: grün/clean/ok; grep-Treffer nur mit `app.`-Präfix (plus die `is_autostart_enabled`-Zeile ohne Var-Bezug).

---

## Task 5: `GoogleTab` (der Brocken)

**Files:**
- Create: `src/dialogs/settings_dialog/tab_google.py`
- Modify: `src/dialogs/settings_dialog/dialog.py`

**Interfaces:**
- Consumes: `_shared.label`, `_shared.subheader`, `oauth_task.build_oauth_enable_task`.
- Produces: `GoogleTab(frame, dialog, settings, base_path, on_change, runner, storage, conflicts_store, reservation_store, data_lock, sync_guard)` mit Attributen `frame`, `cal_map` (dict, wird von `_populate_calendars` **mutiert** — dieselbe Instanz muss `save_settings` erreichen), `cal_var`.

- [ ] **Step 1: `tab_google.py` anlegen — Google-Block verbatim verschieben**

Block = Original-Z. 256–696 (Anker: Banner `# ===================== Tab: Google` bis einschließlich `if settings.get("gcal_enabled"): _load_calendars()`). **Zusätzlich** wandert `creds_path = os.path.join(base_path, "credentials.json")` (Original-Z. 95) an den Anfang des `__init__` — es wird nur im Google-Block genutzt. Einzige Block-Änderung: `tab_google` → `frame`. Alle anderen Namen (`dialog`, `settings`, `base_path`, `on_change`, `runner`, `storage`, `conflicts_store`, `reservation_store`, `data_lock`, `sync_guard`) sind Konstruktor-Parameter mit **identischen Namen** — der verschobene Code referenziert sie unverändert.

```python
# src/dialogs/settings_dialog/tab_google.py
"""Tab „Google": Konto/Status, Absender, Drive-Sync (Konflikte/Import/
Reconnect/Kompaktierung) und Google-Kalender — inkl. der H5-Worker
(runner.run, Persistenz im fn, winfo_exists-Guards)."""

import logging
import os
import tkinter as tk
import traceback
from tkinter import messagebox

from src.dialogs.settings_dialog._shared import label, subheader
from src.dialogs.settings_dialog.oauth_task import build_oauth_enable_task
from src.platform_open import open_folder
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_SMALL, STATUS_OK, TEXT, TEXT_MUTED,
    dark_combo, secondary_button, themed_askyesno, themed_showerror,
    themed_showinfo, themed_showwarning,
)
from src.time_utils import format_iso_date


class GoogleTab:
    """Baut den Google-Tab; exponiert cal_map/cal_var für save_settings."""

    def __init__(self, frame, dialog, settings, base_path, on_change, runner,
                 storage, conflicts_store, reservation_store,
                 data_lock, sync_guard):
        creds_path = os.path.join(base_path, "credentials.json")

        <verbatim verschobener Block Z. 256–696, tab_google→frame>

        self.frame = frame
        self.cal_map = cal_map
        self.cal_var = cal_var
```

(Die Lazy-Imports im Block — `from src.dialogs.conflicts_dialog import ConflictsDialog`, `from src.dialogs.import_dialog import open_import_dialog`, `from src import drive`, `from src import gcal`, `from src.main import _run_compaction_blocking`, `from src.sync import NEWER_REMOTE_VERSION_MSG` — bleiben lazy an Ort und Stelle; CI-Konvention.)

- [ ] **Step 2: `dialog.py` umbauen**

1. Google-Block (Z. 256–696) ersetzen durch:
   ```python
   # ===================== Tab: Google =====================
   google = GoogleTab(
       tab_google, dialog, settings, base_path, on_change, runner,
       storage, conflicts_store, reservation_store, data_lock, sync_guard)
   ```
   Import `from src.dialogs.settings_dialog.tab_google import GoogleTab`; die Zeile `creds_path = …` (jetzt ~Z. 51) in `dialog.py` **löschen**.
2. Substitutionen: `cal_map` → `google.cal_map`, `cal_var` → `google.cal_var`, `tabs`-Eintrag `"google": tab_google` → `"google": google.frame`.
3. Import-Kopf von `dialog.py` **grep-verifiziert** trimmen — voraussichtlich fallen jetzt: `logging`, `os`, `traceback`, `messagebox`, `open_folder`, `format_iso_date`, `build_oauth_enable_task`-Import, `ACCENT`, `CELL_BG`, `FONT_SMALL`, `STATUS_OK`, `TEXT_MUTED`, `dark_combo`, `dark_entry`, `themed_askyesno`, `themed_showinfo`, `label`/`subheader`-Import (kein Inline-Block mehr) u. a. Behalten sicher: `datetime`, `tk`, `ttk`, `create_dialog`-Familie, `primary_button`, `secondary_button`, `themed_showerror`, `themed_showwarning`, Autostart-Namen, Settings-/time_utils-/weekly_limit-Namen, `WEEKDAY_KEYS`, `DAYS_DE`, `code_for_state_label`. **Jede Streichung nur nach grep** `grep -n "<name>" src/dialogs/settings_dialog/dialog.py`.

- [ ] **Step 3: Verifikation + Commit**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -c "import src.ui; print('ok')"
grep -n "cal_map\|cal_var" src/dialogs/settings_dialog/dialog.py
git add -A src/dialogs/settings_dialog
git commit -m "refactor(settings): GoogleTab extrahiert (H4 Schritt 5)"
```
Expected: grün/clean/ok; grep nur `google.`-präfixiert.

---

## Task 6: Doku + Abschluss-Bilanz

**Files:**
- Modify: `src/CLAUDE.md` (Dialoge-Absatz)

**Interfaces:**
- Consumes: fertige Paketstruktur aus Tasks 1–5.
- Produces: aktualisierte Architektur-Doku; Abnahme-Metriken.

- [ ] **Step 1: `src/CLAUDE.md` aktualisieren**

Im Abschnitt „## Dialoge (`src/dialogs/`)" den `settings_dialog`-Teil der Aufzählung („`settings_dialog` (4 Tabs über `ttk.Notebook` …)") ersetzen durch:

```
`settings_dialog/` (Paket, Audit H4: `dialog.py` trägt Chrome + zentrales,
ablaufidentisches `save_settings`; je Tab eine Klasse in `tab_work/`
`tab_mail`/`tab_google`/`tab_app`.py, die ihre Tk-Variablen als Attribute
für `save_settings` exponiert; `oauth_task.py` = H5-OAuth-Toggle-Builder;
Dark-Styling weiter via `theme.apply_notebook_style`)
```

- [ ] **Step 2: Abschluss-Bilanz erheben (Abnahme-Kriterien der Spec)**

```bash
wc -l src/dialogs/settings_dialog/*.py
grep -c "def \|class " src/dialogs/settings_dialog/dialog.py
grep -rn "settings_dialog" src/ tests/ --include="*.py" | grep -v "src/dialogs/settings_dialog/" | grep -v "settings_dialog import\|settings_dialog\." | head
```
Expected: `dialog.py` ≤ ~300 Zeilen; kein Modul außer `tab_google.py` (~470) über ~200; keine verwaisten Referenzen auf das alte Modul-Layout.

- [ ] **Step 3: Suite + Ruff final, Commit**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check .
git add src/CLAUDE.md
git commit -m "docs(architektur): settings_dialog-Paketstruktur dokumentiert (H4 Schritt 6)"
```

---

## Self-Review-Notiz (bereits geprüft)

- **Spec-Abdeckung:** Ziel-Struktur (Tasks 1–5 je Modul), zentrales `save_settings` (Substitutionstabellen 2–5), Move-Technik + Vertrags-Attribute (Global Constraints + jede Klasse), `oauth_task.py`-Begründung + Test-Umstellung (Task 1), `ttk.Style(frame)`-Äquivalenz (Task 4), `creds_path`-Umzug (Task 5), Doku + Zeilen-Bilanz (Task 6), Verifikation nach jedem Task.
- **Interaktiver End-Smoke** (Spec „Verifikation") ist bewusst KEIN Plan-Task: er obliegt Controller/Nutzer nach Abschluss (Tk-gebunden), wie bei H5.
- **Typ-/Namens-Konsistenz:** Handle-Namen `work`/`mail`/`google`/`app` durchgängig; Attribut-Listen identisch zwischen „Produces" und `self.x`-Blöcken; `tabs`-Dict wechselt in jedem Task genau seinen einen Eintrag auf `<handle>.frame`.
- **Bewusste Nicht-Änderungen:** hartkodierter Font zieht mit um (Task 3), H5-Worker unangetastet (Task 5), keine `validate()`/`collect()`-Verteilung.
