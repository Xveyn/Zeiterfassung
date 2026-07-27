# Google-Scope-Anzeige — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Im Google-Tab der Einstellungen sichtbar machen, welche OAuth-Scopes das Google-Konto der App tatsächlich gewährt hat — read-only, hinter einem Button in einem eigenen Modal.

**Architecture:** Zwei Tk-freie Logik-Bausteine plus ein reines Render-Modal. `oauth_utils.read_granted_scopes` liest die Scopes aus `token.json`; `mail.scope_overview` bewertet sie gegen das, was die aktuellen Einstellungen brauchen (`mail.get_scopes`), und liefert drei Zustände; `dialogs/scopes_dialog.py` zeichnet das Ergebnis. Der Google-Tab bekommt nur einen Button.

**Tech Stack:** Python 3.10, Tkinter, pytest. Keine neuen Abhängigkeiten.

**Spec:** `docs/superpowers/specs/2026-07-27-google-scopes-anzeige-design.md`
**Issue:** [#120](https://github.com/margenheld/Zeiterfassung/issues/120)

## Global Constraints

- Bezeichner englisch, UI-Texte und Docstrings deutsch (CONTRIBUTING.md).
- Neue Dialoge entstehen über `theme.create_dialog(...)`, nicht über handgebaute `Toplevel`-Boilerplate; `center_dialog_on_parent` nach dem Widget-Aufbau. Keine dialogspezifischen Stil-Extras — das Theme bleibt einheitlich (CLAUDE.md „Dialog-Styling").
- `src/oauth_utils.py` darf **nicht** aus `src/mail.py` importieren (`mail` importiert `oauth_utils` — Rückimport wäre ein Zyklus).
- `src/mail.py` bleibt auf Modulebene Google-frei (Lazy-Imports in den Funktionen), damit die CI ohne `requirements.txt` importieren kann.
- Keine neue Einstellung, kein persistierter Zustand, kein Widerruf-Pfad.
- Vor jedem Commit: `python -m pytest -q`, `python -m ruff check .`, `npx --no-install pyright` — alle drei sauber.
- Commits im Conventional-Commits-Stil (`feat:`, `refactor:`, `docs:`), Body deutsch.

## File Structure

| Datei | Verantwortung |
|---|---|
| `src/oauth_utils.py` (ändern) | `read_granted_scopes(token_path)` — einzige Leselogik für die Scopes im Token; `discard_token_for_scope_upgrade` zieht darauf. |
| `src/mail.py` (ändern) | `SCOPE_LABELS`, `ScopeStatus`, `scope_overview(...)` — Bewertung neben den vorhandenen Scope-Konstanten und `get_scopes`. |
| `src/dialogs/scopes_dialog.py` (neu) | Modal, reines Rendering, keine Entscheidungslogik. |
| `src/dialogs/settings_dialog/tab_google.py` (ändern) | Eine Button-Zeile „Berechtigungen: [Anzeigen]". |
| `tests/test_oauth_utils.py`, `tests/test_mail.py` (ändern) | Tests der beiden puren Bausteine. |
| `README.md`, `src/CLAUDE.md` (ändern) | Feature-Erwähnung und Dialog-Liste. |

---

### Task 1: `read_granted_scopes` in `oauth_utils`

**Files:**
- Modify: `src/oauth_utils.py` (Funktion `discard_token_for_scope_upgrade`, aktuell am Dateiende)
- Test: `tests/test_oauth_utils.py`

**Interfaces:**
- Consumes: nichts (erster Task).
- Produces: `read_granted_scopes(token_path) -> list[str] | None`. `None` = Datei fehlt, ist unlesbar, enthält kaputtes JSON **oder** hat ein `scopes`-Feld, das keine Liste ist. Leere Liste = Datei war lesbar, enthält aber keine Scopes. Task 3 unterscheidet „fehlt" von „unlesbar" selbst per `os.path.exists`.

- [ ] **Step 1: Write the failing tests**

Ans Ende von `tests/test_oauth_utils.py` anfügen (der Import in Zeile 13 muss `read_granted_scopes` mit aufnehmen: `from src.oauth_utils import write_token, discard_token_for_scope_upgrade, read_granted_scopes`):

```python
def test_read_granted_scopes_returns_the_list(tmp_path):
    path = str(tmp_path / "token.json")
    _write_token_file(path, ["a", "b"])

    assert read_granted_scopes(path) == ["a", "b"]


def test_read_granted_scopes_returns_none_for_missing_file(tmp_path):
    assert read_granted_scopes(str(tmp_path / "fehlt.json")) is None


def test_read_granted_scopes_returns_none_for_broken_json(tmp_path):
    path = str(tmp_path / "token.json")
    with open(path, "w") as f:
        f.write("not json")

    assert read_granted_scopes(path) is None


def test_read_granted_scopes_returns_empty_list_when_key_missing(tmp_path):
    """Lesbare Datei ohne scopes-Key: leere Liste, NICHT None — der Aufrufer
    unterscheidet „nichts gewährt" von „nicht lesbar"."""
    path = str(tmp_path / "token.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"token": "t"}, f)

    assert read_granted_scopes(path) == []


def test_read_granted_scopes_returns_none_for_non_list_scopes(tmp_path):
    """Ein scopes-Feld, das keine Liste ist, ist unbrauchbar — nicht als
    „keine Scopes" durchwinken."""
    path = str(tmp_path / "token.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"token": "t", "scopes": "gmail.send"}, f)

    assert read_granted_scopes(path) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_oauth_utils.py -q -p no:warnings`
Expected: FAIL beim Import — `ImportError: cannot import name 'read_granted_scopes' from 'src.oauth_utils'`

- [ ] **Step 3: Implement `read_granted_scopes`**

In `src/oauth_utils.py` **vor** `discard_token_for_scope_upgrade` einfügen:

```python
def read_granted_scopes(token_path):
    """Die im `token.json` tatsächlich gewährten OAuth-Scopes.

    Liefert die Liste, oder `None`, wenn die Datei fehlt, nicht lesbar ist,
    kaputtes JSON enthält oder ein `scopes`-Feld trägt, das keine Liste ist.
    Eine leere Liste heißt dagegen: Datei war lesbar, es sind keine Scopes
    vermerkt. Die Unterscheidung braucht die Anzeige im Google-Tab, um
    „noch nicht angemeldet" von „nicht lesbar" zu trennen (#120).

    Konservativ wie der ganze Token-Pfad: bei Zweifeln lieber `None` als eine
    falsche Behauptung über die gewährten Rechte.
    """
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    scopes = data.get("scopes")
    if scopes is None:
        return []
    if not isinstance(scopes, list):
        return None
    return scopes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_oauth_utils.py -q -p no:warnings`
Expected: PASS (alle, auch die bestehenden `discard_*`-Tests)

- [ ] **Step 5: Refactor `discard_token_for_scope_upgrade` auf den neuen Helfer**

In `src/oauth_utils.py` den Lese-Block der Funktion ersetzen. Vorher:

```python
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            granted = set(json.load(f).get("scopes") or [])
    except (OSError, ValueError):
        return False
```

Nachher:

```python
    granted = read_granted_scopes(token_path)
    if granted is None:
        # Nicht lesbar → konservativ: Token unangetastet lassen, statt einen
        # womöglich gültigen wegzuwerfen.
        return False
```

Die Zeile darunter muss dann auf ein Set vergleichen:

```python
    if set(scopes).issubset(set(granted)):
        return False
```

- [ ] **Step 6: Run the full suite to verify nothing regressed**

Run: `python -m pytest -q -p no:warnings`
Expected: PASS — insbesondere die vier bestehenden `discard_*`-Tests, deren Verhalten unverändert bleibt.

- [ ] **Step 7: Lint und Typecheck**

Run: `python -m ruff check . && npx --no-install pyright src/oauth_utils.py tests/test_oauth_utils.py`
Expected: „All checks passed!" und „0 errors"

- [ ] **Step 8: Commit**

```bash
git add src/oauth_utils.py tests/test_oauth_utils.py
git commit -m "refactor(oauth): read_granted_scopes als einzige Lesestelle der Token-Scopes"
```

---

### Task 2: `scope_overview` in `mail.py`

**Files:**
- Modify: `src/mail.py` (direkt unter `get_scopes`, vor dem `SCOPES`-Legacy-Alias in Zeile 38)
- Test: `tests/test_mail.py`

**Interfaces:**
- Consumes: nichts aus Task 1 (die beiden Bausteine sind unabhängig; erst Task 3 verbindet sie).
- Produces:
  - `ScopeStatus = namedtuple("ScopeStatus", ["scope", "label", "status"])`, `status ∈ {"active", "unused", "missing"}`
  - `SCOPE_LABELS: dict[str, str]` — Scope-URL → deutsches Klartext-Label
  - `scope_overview(granted, sync_enabled, gcal_enabled) -> tuple[list[ScopeStatus], list[str]]` — bewertete Scopes in fester Reihenfolge plus unbekannte Extras als rohe URLs, alphabetisch sortiert.

- [ ] **Step 1: Write the failing tests**

Zuerst den Import-Block in `tests/test_mail.py` (Zeile 69–75) erweitern — die Scope-Konstanten stehen dort **noch nicht** drin:

```python
from src.mail import (  # noqa: E402
    refresh_token_if_needed,
    is_offline_error,
    TokenAuthError,
    TokenNetworkError,
    get_scopes,
    scope_overview,
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_LIST_SCOPE,
    DRIVE_APPDATA_SCOPE,
    GMAIL_SEND_SCOPE,
    USERINFO_EMAIL_SCOPE,
)
```

Dann ans Ende der Datei anfügen:

```python
class TestScopeOverview:
    """#120: bewertet die im Token gewährten Scopes gegen das, was die
    aktuellen Einstellungen brauchen."""

    def _all_granted(self):
        return [GMAIL_SEND_SCOPE, USERINFO_EMAIL_SCOPE, DRIVE_APPDATA_SCOPE,
                CALENDAR_EVENTS_SCOPE, CALENDAR_LIST_SCOPE]

    def test_everything_granted_and_enabled_is_active(self):
        entries, extras = scope_overview(
            self._all_granted(), sync_enabled=True, gcal_enabled=True)
        assert [e.status for e in entries] == ["active"] * 5
        assert extras == []

    def test_keeps_a_stable_order_core_drive_calendar(self):
        entries, _ = scope_overview(
            self._all_granted(), sync_enabled=True, gcal_enabled=True)
        assert [e.scope for e in entries] == [
            GMAIL_SEND_SCOPE, USERINFO_EMAIL_SCOPE, DRIVE_APPDATA_SCOPE,
            CALENDAR_EVENTS_SCOPE, CALENDAR_LIST_SCOPE]

    def test_granted_but_feature_switched_off_is_unused(self):
        """Wer den Sync abschaltet, behält die Drive-Berechtigung im Token —
        genau diese Diskrepanz soll sichtbar werden."""
        entries, _ = scope_overview(
            self._all_granted(), sync_enabled=False, gcal_enabled=False)
        by_scope = {e.scope: e.status for e in entries}
        assert by_scope[DRIVE_APPDATA_SCOPE] == "unused"
        assert by_scope[CALENDAR_EVENTS_SCOPE] == "unused"
        assert by_scope[GMAIL_SEND_SCOPE] == "active"

    def test_needed_but_not_granted_is_missing(self):
        entries, _ = scope_overview(
            [GMAIL_SEND_SCOPE, USERINFO_EMAIL_SCOPE],
            sync_enabled=True, gcal_enabled=False)
        by_scope = {e.scope: e.status for e in entries}
        assert by_scope[DRIVE_APPDATA_SCOPE] == "missing"

    def test_neither_granted_nor_needed_is_omitted(self):
        """Kalender nie eingeschaltet, nie gewährt → taucht gar nicht auf."""
        entries, _ = scope_overview(
            [GMAIL_SEND_SCOPE, USERINFO_EMAIL_SCOPE],
            sync_enabled=False, gcal_enabled=False)
        assert [e.scope for e in entries] == [GMAIL_SEND_SCOPE, USERINFO_EMAIL_SCOPE]

    def test_unknown_scopes_land_in_extras(self):
        """Altlast einer früheren Version oder manuell erteilt: anzeigen statt
        verschweigen — aber ohne Zustandsbewertung."""
        entries, extras = scope_overview(
            [GMAIL_SEND_SCOPE, USERINFO_EMAIL_SCOPE, "https://example.test/auth/foo"],
            sync_enabled=False, gcal_enabled=False)
        assert extras == ["https://example.test/auth/foo"]
        assert all(e.scope != "https://example.test/auth/foo" for e in entries)

    def test_every_known_scope_has_a_label(self):
        entries, _ = scope_overview(
            self._all_granted(), sync_enabled=True, gcal_enabled=True)
        assert all(e.label and e.label != e.scope for e in entries)

    def test_none_granted_is_treated_as_nothing_granted(self):
        """Defensiv: der Aufrufer fängt None ab, aber die Funktion darf daran
        nicht scheitern."""
        entries, extras = scope_overview(None, sync_enabled=False, gcal_enabled=False)
        assert [e.status for e in entries] == ["missing", "missing"]
        assert extras == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mail.py -q -p no:warnings`
Expected: FAIL beim Import — `ImportError: cannot import name 'scope_overview' from 'src.mail'`

- [ ] **Step 3: Implement labels, namedtuple und `scope_overview`**

In `src/mail.py` direkt nach `get_scopes` einfügen. Der `namedtuple`-Import gehört an den Dateikopf (`from collections import namedtuple`, zu den übrigen stdlib-Imports in Zeile 2–8):

```python
ScopeStatus = namedtuple("ScopeStatus", ["scope", "label", "status"])

SCOPE_LABELS = {
    GMAIL_SEND_SCOPE: "E-Mail senden",
    USERINFO_EMAIL_SCOPE: "Eigene E-Mail-Adresse lesen",
    DRIVE_APPDATA_SCOPE: "Google Drive: App-Datenordner",
    CALENDAR_EVENTS_SCOPE: "Google Kalender: Termine lesen und schreiben",
    CALENDAR_LIST_SCOPE: "Google Kalender: Kalenderliste lesen",
}

# Anzeigereihenfolge: erst der Kern, dann die zuschaltbaren Features.
_SCOPE_ORDER = [
    GMAIL_SEND_SCOPE, USERINFO_EMAIL_SCOPE, DRIVE_APPDATA_SCOPE,
    CALENDAR_EVENTS_SCOPE, CALENDAR_LIST_SCOPE,
]


def scope_overview(granted, sync_enabled, gcal_enabled):
    """Bewertet die gewährten Scopes gegen die aktuell gebrauchten (#120).

    `granted`: Scopes aus dem Token (`oauth_utils.read_granted_scopes`); `None`
    wird wie „nichts gewährt" behandelt — die Unterscheidung „nicht lesbar"
    trifft der Aufrufer, bevor er hier hereinkommt.

    Liefert `(entries, extras)`:
    - `entries`: `ScopeStatus` je bekanntem Scope in fester Reihenfolge, mit
      `active` (gewährt und gebraucht), `unused` (gewährt, Funktion aus) oder
      `missing` (gebraucht, fehlt — der nächste Zugriff erzwingt über
      `oauth_utils.discard_token_for_scope_upgrade` einen frischen Consent).
      Weder gewährt noch gebraucht → gar kein Eintrag, sonst stünde die Liste
      voll mit Zeug, das den Nutzer nichts angeht.
    - `extras`: gewährte Scopes, die diese App nicht kennt (Altlast, manuell
      erteilt) — roh und sortiert, ohne Bewertung.
    """
    granted_set = set(granted or ())
    needed = set(get_scopes(sync_enabled, gcal_enabled))
    entries = []
    for scope in _SCOPE_ORDER:
        is_granted = scope in granted_set
        is_needed = scope in needed
        if not is_granted and not is_needed:
            continue
        if is_granted and is_needed:
            status = "active"
        elif is_granted:
            status = "unused"
        else:
            status = "missing"
        entries.append(ScopeStatus(scope, SCOPE_LABELS[scope], status))
    return entries, sorted(granted_set - set(_SCOPE_ORDER))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mail.py -q -p no:warnings`
Expected: PASS

- [ ] **Step 5: Lint, Typecheck, volle Suite**

Run: `python -m pytest -q -p no:warnings && python -m ruff check . && npx --no-install pyright src/mail.py tests/test_mail.py`
Expected: alles grün, „0 errors"

- [ ] **Step 6: Commit**

```bash
git add src/mail.py tests/test_mail.py
git commit -m "feat(oauth): scope_overview bewertet gewaehrte gegen gebrauchte Scopes"
```

---

### Task 3: Modal und Button im Google-Tab

**Files:**
- Create: `src/dialogs/scopes_dialog.py`
- Modify: `src/dialogs/settings_dialog/tab_google.py` (Zeilen 141–206: neue Button-Zeile in Row 3, danach Row-Nummern um 1 verschoben)
- Modify: `README.md` (Projektstruktur-Zeile `dialogs/`, Feature-Liste), `src/CLAUDE.md` (Abschnitt „Dialoge")

**Interfaces:**
- Consumes: `oauth_utils.read_granted_scopes(token_path)` (Task 1), `mail.scope_overview(granted, sync_enabled, gcal_enabled)` und `mail.ScopeStatus` (Task 2).
- Produces: `open_scopes_dialog(parent, settings, base_path)` — öffnet das Modal und liefert das `Toplevel` zurück.

Für diesen Task gibt es **keine automatisierten Tests**: es ist reines Tk-Rendering ohne Entscheidungslogik, konsistent mit der übrigen UI-Schicht (Audit M16 ist offen und bewusst nicht Teil dieses Features). Verifiziert wird manuell in Step 5.

- [ ] **Step 1: Modal anlegen**

Neue Datei `src/dialogs/scopes_dialog.py`:

```python
"""Modal: welche OAuth-Scopes das Google-Konto der App gewährt hat (#120).

Read-only. Die Bewertung macht `mail.scope_overview`, gelesen wird über
`oauth_utils.read_granted_scopes` — hier passiert nur Rendering.

Bewusst ein Modal statt einer Liste im Google-Tab: der Tab ist mit 480 px
bereits der größte im Notebook (das alle Tabs auf diese Höhe zwingt), die
Liste inline kostete +156 px. Nebeneffekt: das Modal liest `token.json` beim
Öffnen und ist damit per Konstruktion immer frisch — kein Poll, keine
Invalidierung nach einem Re-Consent.
"""

import os
import tkinter as tk

from src.mail import scope_overview
from src.oauth_utils import read_granted_scopes
from src.theme import (
    ACCENT, BG, FONT, FONT_BOLD, FONT_SMALL, STATUS_OK, TEXT, TEXT_MUTED,
    center_dialog_on_parent, create_dialog, secondary_button,
)

# Zustand → (Zeichen, Farbe). Zeichen statt Farbe allein, damit die Liste
# auch ohne Farbwahrnehmung lesbar bleibt.
_MARKS = {
    "active": ("✓", STATUS_OK),
    "unused": ("○", TEXT_MUTED),
    "missing": ("✗", ACCENT),
}

_LEGEND = ("✓ gewährt und genutzt    ○ gewährt, zurzeit ungenutzt    "
           "✗ fehlt, wird neu angefragt")


def open_scopes_dialog(parent, settings, base_path):
    """Öffnet das Berechtigungs-Modal und liefert den Toplevel zurück."""
    token_path = os.path.join(base_path, "token.json")
    granted = read_granted_scopes(token_path)

    dialog = create_dialog(parent, "Berechtigungen")
    body = tk.Frame(dialog, bg=BG)
    body.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

    tk.Label(
        body, text="Berechtigungen des Google-Kontos", font=FONT_BOLD,
        bg=BG, fg=TEXT,
    ).pack(anchor="w", pady=(0, 8))

    if granted is None:
        message = (
            "Berechtigungen nicht lesbar."
            if os.path.exists(token_path)
            else "Noch nicht angemeldet — es sind keine Berechtigungen gewährt."
        )
        tk.Label(body, text=message, font=FONT, bg=BG, fg=TEXT_MUTED).pack(anchor="w")
    else:
        entries, extras = scope_overview(
            granted,
            settings.get("sync_enabled"),
            settings.get("gcal_enabled"),
        )
        for entry in entries:
            mark, color = _MARKS[entry.status]
            tk.Label(
                body, text=f"{mark}  {entry.label}", font=FONT, bg=BG, fg=color,
            ).pack(anchor="w", pady=(4, 0))
            tk.Label(
                body, text=f"     {entry.scope}", font=FONT_SMALL,
                bg=BG, fg=TEXT_MUTED,
            ).pack(anchor="w")

        if extras:
            tk.Label(
                body, text="Weitere Berechtigungen", font=FONT_BOLD,
                bg=BG, fg=TEXT,
            ).pack(anchor="w", pady=(12, 4))
            for scope in extras:
                tk.Label(
                    body, text=f"     {scope}", font=FONT_SMALL,
                    bg=BG, fg=TEXT_MUTED,
                ).pack(anchor="w")

        tk.Label(
            body, text=_LEGEND, font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(12, 0))

    secondary_button(body, "Schließen", dialog.destroy).pack(anchor="e", pady=(16, 0))

    center_dialog_on_parent(dialog, parent)
    return dialog
```

- [ ] **Step 2: Button in den Google-Tab einhängen**

In `src/dialogs/settings_dialog/tab_google.py` **nach** dem Block, der `sender_btn` packt (aktuell Zeile 133–139), einfügen:

```python
        label(frame, "Berechtigungen:", row=3, pady=(0, 4))
        scopes_row = tk.Frame(frame, bg=BG)
        scopes_row.grid(row=3, column=1, padx=10, pady=(0, 4), sticky="w")

        def _open_scopes():
            from src.dialogs.scopes_dialog import open_scopes_dialog
            open_scopes_dialog(dialog, settings, base_path)

        secondary_button(
            scopes_row, "Anzeigen", _open_scopes, padx=12, pady=2,
        ).pack(side=tk.LEFT)
```

- [ ] **Step 3: Die nachfolgenden Grid-Zeilen um 1 verschieben**

Im selben File, alle fünf Stellen (aktuelle Zeilennummern in Klammern):

| Element | vorher | nachher |
|---|---|---|
| `subheader(frame, "Synchronisation", row=…)` (141) | `row=3` | `row=4` |
| Hinweis-Label „Diese Schalter wirken sofort…" (145) | `row=4` | `row=5` |
| `cb_sync.grid(...)` (189) | `row=5` | `row=6` |
| Label „Geräte-ID: …" (196) | `row=6` | `row=7` |
| Label „Letzte Synchronisation: …" (202) | `row=7` | `row=8` |
| `next_google_row = 8` (206) | `8` | `9` |

- [ ] **Step 4: Suite, Lint, Typecheck**

Run: `python -m pytest -q -p no:warnings && python -m ruff check . && npx --no-install pyright`
Expected: dieselbe Testzahl wie am Ende von Task 2 (dieser Task fügt keine Tests hinzu), „All checks passed!", „0 errors". Die bestehenden `tests/test_settings_dialog.py`-Tests müssen grün bleiben; schlagen sie fehl, stimmt eine Row-Nummer nicht.

- [ ] **Step 5: Manuell verifizieren (Windows)**

```bash
python -m src.main
```

Einstellungen (⚙) → Tab **Google** → „Berechtigungen: **Anzeigen**". Prüfen:
1. Das Modal öffnet mittig über dem Settings-Dialog, dunkel gethemt, Escape schließt es.
2. Mit vorhandener `token.json`: die gewährten Scopes stehen mit ✓/○ da, technische URL jeweils darunter, Legende unten.
3. `token.json` temporär umbenennen → „Noch nicht angemeldet — es sind keine Berechtigungen gewährt."; danach zurückbenennen.
4. Der Google-Tab ist durch die neue Zeile nur um eine Button-Höhe gewachsen; die Sync-Zeilen darunter stehen unverändert und nicht verrutscht.

- [ ] **Step 6: Doku nachziehen**

`README.md` — in der Projektstruktur die `dialogs/`-Zeile um `scopes` ergänzen:

```
│   ├── dialogs/           # Modal-Dialoge (entry, send, export, settings, share, import, conflicts, category, scopes) + geteilter period_picker
```

`README.md` — im Abschnitt „Einstellungen" ans Ende der Tabelle:

```
| **Berechtigungen** | Zeigt, welche Google-Berechtigungen (OAuth-Scopes) das Konto der App gewährt hat — inkl. solcher, die noch gewährt, aber zurzeit ungenutzt sind |
```

`src/CLAUDE.md` — im Abschnitt „Dialoge (`src/dialogs/`)" die Aufzählung um `scopes_dialog` erweitern und einen Satz anfügen:

```
`scopes_dialog` zeigt read-only, welche OAuth-Scopes im `token.json` gewährt sind,
bewertet gegen die aktuell gebrauchten (`mail.scope_overview`): ✓ genutzt, ○ gewährt
aber Funktion aus, ✗ gebraucht aber fehlt. Bewusst ein Modal statt einer Liste im
Google-Tab (der ist mit 480 px schon der größte im Notebook) — und es liest
`token.json` beim Öffnen, ist also ohne Poll immer aktuell.
```

- [ ] **Step 7: Commit**

```bash
git add src/dialogs/scopes_dialog.py src/dialogs/settings_dialog/tab_google.py README.md src/CLAUDE.md
git commit -m "feat(settings): Google-Tab zeigt die gewaehrten OAuth-Scopes (#120)"
```

---

## Abschluss

- [ ] `python -m pytest -q`, `python -m ruff check .`, `npx --no-install pyright` ein letztes Mal über alles.
- [ ] PR gegen `margenheld/Zeiterfassung:master` öffnen, `Closes #120` im Body, Hinweis auf den Stapel (#172 → #173 → #174 → dieser).
