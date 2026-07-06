# Send/Share/Export nicht-blockierend (Audit M10) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die drei Dialoge `send_dialog`, `share_dialog`, `export_dialog` führen ihre blockierenden Operationen (PDF-Erzeugung, Gmail-Service inkl. OAuth, Mailversand) nicht mehr synchron im Klick-Handler aus, sondern über den `BackgroundTaskRunner` — die Tk-Mainloop friert nicht mehr ein.

**Architecture:** Je Dialog wandert der blockierende Kern in ein Tk-freies Modul `src/dialogs/<x>_task.py` als reine Funktion `perform_*(...) -> dict` (im Worker-Thread, fängt eigene Exceptions, persistiert selbst). Die zwei Netz-Kerne (send/share) teilen sich einen Fehler-Klassifikator `mail_task.classify_mail_error`. Die Dialog-Datei baut die Eingaben auf dem UI-Thread, deaktiviert den Primär-Button, startet `runner.run(fn, on_done)`; `on_done` (UI-Thread via `App._marshal_to_ui`) macht das `winfo_exists`-gegatete Feedback. Vorbild: `settings_dialog/oauth_task.py` (Audit H5).

**Tech Stack:** Python 3.10, tkinter, `unittest.mock`/`pytest` (monkeypatch), bestehender `BackgroundTaskRunner`.

## Global Constraints

- **Kein Verhaltensbruch:** exakt dieselben Meldungstexte, dieselbe Persistenz, dieselbe Fehler-Zweiteilung (themed für bekannte Fehler, `messagebox.showerror` mit Traceback für unerwartete) wie heute — nur nicht mehr auf dem UI-Thread.
- **`runner` ist required** an `open_send_dialog`/`open_share_dialog`/`open_export_dialog` — kein zweiter, synchroner Codepfad.
- **Fehler-Klassifikation zentral:** send/share nutzen `mail_task.classify_mail_error` (kein wortgleicher try/except-Block je Kern). Export nutzt ihn NICHT (kein Netz-Pfad, nur generischer Fehler).
- **Datumsanzeige deutsch** (`%d.%m.%Y`), intern ISO — unverändert, kein neuer Datumscode.
- **UTF-8-Mail-Pflichten** liegen in `report.py`/`mail.py` und werden nicht angefasst.
- **Headless CI:** `perform_*`/`classify_mail_error` sind Tk-frei und werden voll unit-getestet; die Tk-Verdrahtung (Dialog-Closures, Button-State) bleibt — wie bei H5/Audit M16 — ohne Unit-Test (Verifikation: `ruff` + `pytest` + Import-Smoke).
- **Basis:** lokaler Audit-Stack (`master`), setzt #121/#122/#123 voraus. `settings.set`/Store-Reads aus dem Worker sind durch den geteilten Store-Lock (#121) threadsicher.
- Kein `_label`-Direktzugriff aus den Dialogen (Audit N17) — Button-Text nur über den neuen `theme.set_button_text`-Helfer.

---

### Task 1: `theme.set_button_text`-Helfer

**Files:**
- Modify: `src/theme.py` (direkt nach `set_primary_button_enabled`)

**Interfaces:**
- Produces: `set_button_text(btn, text)` — setzt den sichtbaren Text eines `primary_button`/`secondary_button` (Frame+Label-Konstrukt), ohne dass Aufrufer auf das private `_label` zugreifen.

- [ ] **Step 1: Implementierung einfügen**

In `src/theme.py` unmittelbar nach der Funktion `set_primary_button_enabled` einfügen:

```python
def set_button_text(btn, text):
    """Setzt den sichtbaren Text eines label_button-Konstrukts (primary_/
    secondary_button). Kapselt den `_label`-Zugriff, damit Aufrufer nicht auf
    das private Innen-Widget greifen (Audit N17)."""
    btn._label.config(text=text)
```

- [ ] **Step 2: Lint + Import-Smoke**

Run: `python -m ruff check src/theme.py ; python -c "import src.theme as t; print(hasattr(t, 'set_button_text'))"`
Expected: `All checks passed!` und `True`

(Kein Tk-Unit-Test: `label_button` braucht einen Tk-Root, der headless in CI nicht verfügbar ist — der Helfer ist ein Einzeiler und wird durch die Dialog-Nutzung mitverifiziert.)

- [ ] **Step 3: Commit**

```bash
git add src/theme.py
git commit -m "feat(theme): set_button_text-Helfer für label_button (Audit M10)"
```

---

### Task 2: `mail_task.classify_mail_error` (TDD)

**Files:**
- Create: `src/dialogs/mail_task.py`
- Test: `tests/test_mail_task.py`

**Interfaces:**
- Produces: `classify_mail_error(e) -> dict`. Mappt eine Versand-Exception auf `{"ok": False, "kind": <"filenotfound"|"offline"|"error">, "error": e, "tb": <str|None>}`. **Muss aus einem aktiven `except`-Block gerufen werden** — der error-Fall liest den aktuellen Traceback über `traceback.format_exc()`.

- [ ] **Step 1: Failing tests schreiben**

`tests/test_mail_task.py`:

```python
"""classify_mail_error: gemeinsame Fehler-Zuordnung der Mail-Kerne (Audit M10)."""

import src.dialogs.mail_task as mt
from src.dialogs.mail_task import classify_mail_error


def test_classify_filenotfound():
    res = classify_mail_error(FileNotFoundError("credentials.json"))
    assert res["ok"] is False
    assert res["kind"] == "filenotfound"
    assert res["tb"] is None


def test_classify_offline(monkeypatch):
    monkeypatch.setattr(mt, "is_offline_error", lambda e: True)
    try:
        raise OSError("net")
    except Exception as e:
        res = classify_mail_error(e)
    assert res["kind"] == "offline"
    assert res["tb"] is None


def test_classify_generic_error_has_traceback(monkeypatch):
    monkeypatch.setattr(mt, "is_offline_error", lambda e: False)
    try:
        raise ValueError("boom")
    except Exception as e:
        res = classify_mail_error(e)
    assert res["kind"] == "error"
    assert "boom" in res["tb"]
```

- [ ] **Step 2: Tests laufen lassen (rot)**

Run: `python -m pytest tests/test_mail_task.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.dialogs.mail_task'`)

- [ ] **Step 3: `classify_mail_error` implementieren**

`src/dialogs/mail_task.py`:

```python
"""Gemeinsamer Fehler-Klassifikator für die Mail-Versand-Kerne (Audit M10).

send_task/share_task teilen sich diese Zuordnung einer Versand-Exception auf
ein Result-Dict. Export nutzt sie NICHT (kein Netz-Pfad).
"""

import traceback

from src.mail import is_offline_error


def classify_mail_error(e):
    """Mappt eine beim Mailversand aufgetretene Exception auf ein
    Fehler-Result-Dict:

    - FileNotFoundError -> kind "filenotfound" (fehlende credentials.json,
      erwartet; kein Traceback).
    - is_offline_error  -> kind "offline" (kein Netz; kein Traceback).
    - sonst             -> kind "error" mit Traceback.

    Muss aus einem aktiven `except`-Block gerufen werden — der error-Fall
    liest den aktuellen Traceback über traceback.format_exc()."""
    if isinstance(e, FileNotFoundError):
        return {"ok": False, "kind": "filenotfound", "error": e, "tb": None}
    if is_offline_error(e):
        return {"ok": False, "kind": "offline", "error": e, "tb": None}
    return {"ok": False, "kind": "error", "error": e, "tb": traceback.format_exc()}
```

- [ ] **Step 4: Tests laufen lassen (grün)**

Run: `python -m pytest tests/test_mail_task.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/mail_task.py tests/test_mail_task.py
git commit -m "feat(dialogs): geteilter Mail-Fehler-Klassifikator (Audit M10)"
```

---

### Task 3: `send_task.perform_send` (TDD)

**Files:**
- Create: `src/dialogs/send_task.py`
- Test: `tests/test_send_task.py`

**Interfaces:**
- Consumes: `mail_task.classify_mail_error` (Task 2).
- Produces: `perform_send(*, date_from, date_to, entries, name, categories, category_breakdown, credentials_path, token_path, recipient, subject, html, pdf_filename, sync_enabled, gcal_enabled, settings) -> dict`. Erfolg: `{"ok": True}`. Fehler: Rückgabe von `classify_mail_error` (`{"ok": False, "kind": ..., "error": ..., "tb": ...}`).

- [ ] **Step 1: Failing tests schreiben**

`tests/test_send_task.py`:

```python
"""perform_send: Tk-freier Worker-Kern des Sende-Dialogs (Audit M10)."""

import src.dialogs.send_task as st
from src.dialogs.send_task import perform_send


class _FakeSettings:
    def __init__(self, sender_email=""):
        self._d = {"sender_email": sender_email}
        self.sets = []

    def get(self, k):
        return self._d.get(k)

    def set(self, k, v):
        self.sets.append((k, v))
        self._d[k] = v


def _kwargs(**over):
    base = dict(
        date_from=None, date_to=None, entries={}, name="N",
        categories=None, category_breakdown=False,
        credentials_path="c.json", token_path="t.json",
        recipient="to@example.com", subject="Subj", html="<p>x</p>",
        pdf_filename="r.pdf",
        sync_enabled=False, gcal_enabled=False, settings=_FakeSettings(),
    )
    base.update(over)
    return base


def _patch_happy(monkeypatch, sent=None):
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")
    monkeypatch.setattr(st, "get_gmail_service", lambda *a, **k: "svc")

    def fake_send(service, to, subject, html, **k):
        if sent is not None:
            sent["to"] = to
            sent["bytes"] = k.get("attachment_bytes")
            sent["subtype"] = k.get("attachment_subtype")
        return "mid"

    monkeypatch.setattr(st, "send_email", fake_send)
    monkeypatch.setattr(st, "fetch_user_email", lambda *a, **k: "me@example.com")


def test_perform_send_success_sends_and_caches_sender(monkeypatch):
    sent = {}
    _patch_happy(monkeypatch, sent)
    s = _FakeSettings(sender_email="")
    res = perform_send(**_kwargs(settings=s))
    assert res == {"ok": True}
    assert sent["to"] == "to@example.com"
    assert sent["bytes"] == b"PDF"
    assert sent["subtype"] == "pdf"
    assert ("sender_email", "me@example.com") in s.sets


def test_perform_send_sender_cache_failure_is_swallowed(monkeypatch):
    _patch_happy(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("no net")

    monkeypatch.setattr(st, "fetch_user_email", boom)
    res = perform_send(**_kwargs())
    assert res == {"ok": True}


def test_perform_send_error_delegates_to_classifier(monkeypatch):
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")
    monkeypatch.setattr(st, "get_gmail_service", lambda *a, **k: "svc")

    def boom(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(st, "send_email", boom)
    sentinel = {"ok": False, "kind": "error", "error": None, "tb": "TB"}
    monkeypatch.setattr(st, "classify_mail_error", lambda e: sentinel)
    res = perform_send(**_kwargs())
    assert res is sentinel


def test_perform_send_missing_credentials_delegates_to_classifier(monkeypatch):
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")

    def missing(*a, **k):
        raise FileNotFoundError("credentials.json")

    monkeypatch.setattr(st, "get_gmail_service", missing)
    sentinel = {"ok": False, "kind": "filenotfound", "error": None, "tb": None}
    monkeypatch.setattr(st, "classify_mail_error", lambda e: sentinel)
    res = perform_send(**_kwargs())
    assert res is sentinel
```

- [ ] **Step 2: Tests laufen lassen (rot)**

Run: `python -m pytest tests/test_send_task.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.dialogs.send_task'`)

- [ ] **Step 3: `perform_send` implementieren**

`src/dialogs/send_task.py`:

```python
"""Worker-Kern des Sende-Dialogs (Audit M10): Tk-frei, wirft nie.

Erzeugt die PDF, holt den Gmail-Service (kann einen OAuth-Browser-Flow
auslösen), sendet die Mail und cached best-effort die Absender-Adresse.
Persistenz (settings.set) passiert hier im Worker -> überlebt einen
Dialog-Close. Fehler kommen als Result-Dict (classify_mail_error) zurück,
nie als Exception.
"""

import logging

from src.dialogs.mail_task import classify_mail_error
from src.mail import fetch_user_email, get_gmail_service, send_email
from src.report import generate_pdf

log = logging.getLogger(__name__)


def perform_send(*, date_from, date_to, entries, name, categories,
                 category_breakdown, credentials_path, token_path,
                 recipient, subject, html, pdf_filename,
                 sync_enabled, gcal_enabled, settings):
    try:
        pdf_bytes = generate_pdf(
            date_from, date_to, entries, name=name,
            categories=categories, category_breakdown=category_breakdown)
        service = get_gmail_service(
            credentials_path, token_path,
            sync_enabled=sync_enabled, gcal_enabled=gcal_enabled)
        send_email(service, recipient, subject, html,
                   attachment_bytes=pdf_bytes,
                   attachment_filename=pdf_filename,
                   attachment_subtype="pdf")
    except FileNotFoundError as e:
        return classify_mail_error(e)
    except Exception as e:
        log.exception("Senden fehlgeschlagen")
        return classify_mail_error(e)

    # Nach erfolgreichem Send ist der Token frisch — Absender-Adresse cachen.
    try:
        email = fetch_user_email(
            token_path, sync_enabled=sync_enabled, gcal_enabled=gcal_enabled)
        if email and email != settings.get("sender_email"):
            settings.set("sender_email", email)
    except Exception:
        log.exception("sender_email fetch after send failed")

    return {"ok": True}
```

- [ ] **Step 4: Tests laufen lassen (grün)**

Run: `python -m pytest tests/test_send_task.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/send_task.py tests/test_send_task.py
git commit -m "feat(send): perform_send-Worker-Kern extrahiert + getestet (Audit M10)"
```

---

### Task 4: `send_dialog` auf den Runner umstellen

**Files:**
- Modify: `src/dialogs/send_dialog.py` (Imports + `open_send_dialog`-Signatur + `do_send`)
- Modify: `src/ui.py` (`_send`)

**Interfaces:**
- Consumes: `send_task.perform_send`, `theme.set_button_text`, `theme.set_primary_button_enabled`.
- Produces: `open_send_dialog(parent, storage, settings, base_path, runner)` (runner required).

- [ ] **Step 1: Imports erweitern**

In `src/dialogs/send_dialog.py` die `theme`-Importzeile um `set_button_text, set_primary_button_enabled` erweitern und ergänzen:

```python
from src.dialogs.send_task import perform_send
```

(`generate_pdf`/`get_gmail_service`/`send_email`/`is_offline_error`/`fetch_user_email` werden im Dialog nicht mehr direkt gebraucht — die entsprechenden Importe entfernen; `generate_report`, `default_pdf_filename`, `validate_period`, `open_folder` bleiben.)

- [ ] **Step 2: Signatur + `do_send` ersetzen**

`open_send_dialog`-Signatur zu:

```python
def open_send_dialog(parent, storage, settings, base_path, runner):
```

Den gesamten `do_send`-Body durch die nicht-blockierende Variante ersetzen und die Button-Erzeugung so ändern, dass eine Referenz `send_btn` existiert:

```python
    busy = {"running": False}

    def do_send():
        if busy["running"]:
            return
        date_from, date_to = picker.get_range()
        if date_from is None:
            themed_showerror(dialog, "Ungültiges Datum", "Bitte ein gültiges Datum eingeben.")
            return
        ok, msg = validate_period(date_from, date_to)
        if not ok:
            themed_showerror(dialog, "Ungültiger Zeitraum", msg)
            return

        # Frisch lesen statt den Dialog-Snapshot zu senden — der Storage kann
        # sich bei offenem Dialog geändert haben (Hintergrund-Drive-Sync).
        entries = storage.get_all()
        categories = picker.get_categories()
        category_breakdown = picker.get_category_breakdown()

        html, total = generate_report(
            date_from, date_to, entries,
            greeting=settings.get("mail_greeting"),
            content=settings.get("mail_content"),
            closing=settings.get("mail_closing"),
            categories=categories,
            category_breakdown=category_breakdown,
        )
        if html is None:
            themed_showinfo(
                dialog, "Keine Einträge",
                f"Keine Einträge für {date_from.strftime('%d.%m.%Y')} – {date_to.strftime('%d.%m.%Y')} vorhanden.",
            )
            return

        label = f"{date_from.strftime('%d.%m.%Y')} – {date_to.strftime('%d.%m.%Y')}"
        subject = (
            settings.get("mail_subject")
            .replace("{zeitraum}", label)
            .replace("{gesamt}", f"{total}h")
        )
        pdf_filename = default_pdf_filename(date_from, date_to)

        busy["running"] = True
        set_primary_button_enabled(send_btn, False)
        set_button_text(send_btn, "Sende…")

        def fn():
            return perform_send(
                date_from=date_from, date_to=date_to, entries=entries,
                name=settings.get("name"), categories=categories,
                category_breakdown=category_breakdown,
                credentials_path=credentials_path, token_path=token_path,
                recipient=recipient, subject=subject, html=html,
                pdf_filename=pdf_filename,
                sync_enabled=settings.get("sync_enabled"),
                gcal_enabled=settings.get("gcal_enabled"),
                settings=settings,
            )

        def on_done(res):
            if res["ok"]:
                if dialog.winfo_exists():
                    dialog.destroy()
                themed_showinfo(
                    parent, "Gesendet",
                    f"Bericht für {label} wurde an {recipient} gesendet.",
                )
                return
            busy["running"] = False
            alive = dialog.winfo_exists()
            target = dialog if alive else parent
            if alive:
                set_primary_button_enabled(send_btn, True)
                set_button_text(send_btn, "Senden")
            kind = res["kind"]
            if kind == "filenotfound":
                themed_showerror(target, "Fehler", str(res["error"]))
            elif kind == "offline":
                themed_showerror(
                    target, "Keine Internetverbindung",
                    "Der Bericht konnte nicht gesendet werden, weil keine "
                    "Verbindung zum Internet besteht.\n\n"
                    "Bitte prüfe deine Internetverbindung und versuche es "
                    "dann erneut.",
                )
            else:
                messagebox.showerror(
                    "Senden fehlgeschlagen",
                    f"{type(res['error']).__name__}: {res['error']}\n\n{res['tb']}",
                    parent=target,
                )

        runner.run(fn, on_done)

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=1, column=0, pady=12)

    send_btn = primary_button(btn_frame, "Senden", do_send)
    send_btn.pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)
```

- [ ] **Step 3: Aufrufer in `ui.py` anpassen**

`src/ui.py` `_send`:

```python
    def _send(self):
        open_send_dialog(self.root, self.storage, self.settings, self.base_path, self._bg)
```

- [ ] **Step 4: Lint + Import-Smoke + volle Suite**

Run: `python -m ruff check src/dialogs/send_dialog.py src/ui.py ; python -c "import src.dialogs.send_dialog, src.ui" ; python -m pytest -q`
Expected: `All checks passed!`, kein Import-Fehler, gesamte Suite grün.

- [ ] **Step 5: Manuelle Verifikation (App)**

Run: `python -m src.main`
Prüfen: „Senden" öffnen, Zeitraum wählen, „Senden" klicken → Button zeigt „Sende…" und ist ausgegraut, Fenster bleibt bedienbar (kein Freeze). (Ohne gültige `credentials.json` erscheint stattdessen der Zugangsdaten-Dialog — auch ok, verifiziert den nicht-blockierenden Klick.)

- [ ] **Step 6: Commit**

```bash
git add src/dialogs/send_dialog.py src/ui.py
git commit -m "fix(send): Sende-Pfad über BackgroundTaskRunner, UI friert nicht ein (Audit M10)"
```

---

### Task 5: `share_task.perform_share` (TDD)

**Files:**
- Create: `src/dialogs/share_task.py`
- Test: `tests/test_share_task.py`

**Interfaces:**
- Consumes: `mail_task.classify_mail_error` (Task 2).
- Produces: `perform_share(*, payload, filename, credentials_path, token_path, recipient, subject, html, sync_enabled, gcal_enabled, save_default, settings) -> dict`. Erfolg: `{"ok": True}`. Fehler: Rückgabe von `classify_mail_error`.

- [ ] **Step 1: Failing tests schreiben**

`tests/test_share_task.py`:

```python
"""perform_share: Tk-freier Worker-Kern des Teilen-Dialogs (Audit M10)."""

import src.dialogs.share_task as st
from src.dialogs.share_task import perform_share


class _FakeSettings:
    def __init__(self):
        self.sets = []

    def set(self, k, v):
        self.sets.append((k, v))


def _kwargs(**over):
    base = dict(
        payload=b'{"x":1}', filename="share.json",
        credentials_path="c.json", token_path="t.json",
        recipient="to@example.com", subject="Subj", html="<p>x</p>",
        sync_enabled=False, gcal_enabled=False,
        save_default=False, settings=_FakeSettings(),
    )
    base.update(over)
    return base


def _patch_happy(monkeypatch, sent=None):
    monkeypatch.setattr(st, "get_gmail_service", lambda *a, **k: "svc")

    def fake_send(service, to, subject, html, **k):
        if sent is not None:
            sent["to"] = to
            sent["bytes"] = k.get("attachment_bytes")
            sent["subtype"] = k.get("attachment_subtype")
        return "mid"

    monkeypatch.setattr(st, "send_email", fake_send)


def test_perform_share_success_sends_json(monkeypatch):
    sent = {}
    _patch_happy(monkeypatch, sent)
    res = perform_share(**_kwargs())
    assert res == {"ok": True}
    assert sent["to"] == "to@example.com"
    assert sent["bytes"] == b'{"x":1}'
    assert sent["subtype"] == "json"


def test_perform_share_saves_default_recipient_when_requested(monkeypatch):
    _patch_happy(monkeypatch)
    s = _FakeSettings()
    res = perform_share(**_kwargs(save_default=True, recipient="x@y.z", settings=s))
    assert res["ok"] is True
    assert ("share_recipient", "x@y.z") in s.sets


def test_perform_share_does_not_save_when_not_requested(monkeypatch):
    _patch_happy(monkeypatch)
    s = _FakeSettings()
    perform_share(**_kwargs(save_default=False, settings=s))
    assert s.sets == []


def test_perform_share_error_delegates_to_classifier(monkeypatch):
    monkeypatch.setattr(st, "get_gmail_service", lambda *a, **k: "svc")

    def boom(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(st, "send_email", boom)
    sentinel = {"ok": False, "kind": "error", "error": None, "tb": "TB"}
    monkeypatch.setattr(st, "classify_mail_error", lambda e: sentinel)
    res = perform_share(**_kwargs())
    assert res is sentinel


def test_perform_share_missing_credentials_delegates_to_classifier(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError("credentials.json")

    monkeypatch.setattr(st, "get_gmail_service", missing)
    sentinel = {"ok": False, "kind": "filenotfound", "error": None, "tb": None}
    monkeypatch.setattr(st, "classify_mail_error", lambda e: sentinel)
    res = perform_share(**_kwargs())
    assert res is sentinel
```

- [ ] **Step 2: Tests laufen lassen (rot)**

Run: `python -m pytest tests/test_share_task.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.dialogs.share_task'`)

- [ ] **Step 3: `perform_share` implementieren**

`src/dialogs/share_task.py`:

```python
"""Worker-Kern des Teilen-Dialogs (Audit M10): Tk-frei, wirft nie.

Der Share-Doc-Bau + die Serialisierung laufen auf dem UI-Thread (schnell,
Klick-Zeit-Snapshot); dieser Worker bekommt den fertigen `payload` und
erledigt nur den blockierenden Teil: Gmail-Service holen (evtl. OAuth) +
senden + optional Standard-Empfänger persistieren.
"""

import logging

from src.dialogs.mail_task import classify_mail_error
from src.mail import get_gmail_service, send_email

log = logging.getLogger(__name__)


def perform_share(*, payload, filename, credentials_path, token_path,
                  recipient, subject, html, sync_enabled, gcal_enabled,
                  save_default, settings):
    try:
        service = get_gmail_service(
            credentials_path, token_path,
            sync_enabled=sync_enabled, gcal_enabled=gcal_enabled)
        send_email(service, recipient, subject, html,
                   attachment_bytes=payload,
                   attachment_filename=filename,
                   attachment_subtype="json")
    except FileNotFoundError as e:
        return classify_mail_error(e)
    except Exception as e:
        log.exception("Teilen fehlgeschlagen")
        return classify_mail_error(e)

    if save_default:
        settings.set("share_recipient", recipient)
    return {"ok": True}
```

- [ ] **Step 4: Tests laufen lassen (grün)**

Run: `python -m pytest tests/test_share_task.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/share_task.py tests/test_share_task.py
git commit -m "feat(share): perform_share-Worker-Kern extrahiert + getestet (Audit M10)"
```

---

### Task 6: `share_dialog` auf den Runner umstellen

**Files:**
- Modify: `src/dialogs/share_dialog.py` (Imports + Signatur + `do_send`)
- Modify: `src/ui.py` (`_share`)

**Interfaces:**
- Consumes: `share_task.perform_share`, `theme.set_button_text`, `build_share_doc`/`serialize_share_doc` (bereits importiert).
- Produces: `open_share_dialog(parent, storage, settings, base_path, runner, reservation_store=None)`.

- [ ] **Step 1: Imports erweitern**

Die `theme`-Importzeile in `src/dialogs/share_dialog.py` um `set_button_text` erweitern (`set_primary_button_enabled` ist schon dort) und ergänzen:

```python
from src.dialogs.share_task import perform_share
```

(`get_gmail_service`/`is_offline_error`/`send_email` werden im Dialog nicht mehr direkt gebraucht — entfernen; `build_share_doc`/`serialize_share_doc` bleiben.)

- [ ] **Step 2: Signatur + `busy`-Guard + `do_send` ersetzen**

Signatur zu:

```python
def open_share_dialog(parent, storage, settings, base_path, runner, reservation_store=None):
```

Direkt vor `def do_send():` das Flag anlegen und als erste Zeile im Handler den Re-Entrancy-Guard setzen:

```python
    busy = {"running": False}

    def do_send():
        if busy["running"]:
            return
        want_entries = include_entries_var.get()
        want_res = include_res_var.get()
        if not want_entries and not want_res:
            return
        if _selected_categories() == set():
            return
        share_recipient = recipient_var.get().strip()
        if not share_recipient:
            themed_showerror(dialog, "Empfänger fehlt", "Bitte eine E-Mail-Adresse angeben.")
            return
        sender_email = settings.get("sender_email") or ""
        display_name = settings.get("name") or sender_email or "anonym"

        doc = build_share_doc(
            storage, sender_email,
            reservation_store=reservation_store,
            include_entries=want_entries,
            include_reservations=want_res,
            categories=_selected_categories(),
        )
        payload = serialize_share_doc(doc)
        parts = []
        if want_entries:
            parts.append("Arbeitszeiten")
        if want_res:
            parts.append("Reservierungen")
        what = " und ".join(parts)
        subject = f"{what} geteilt von {display_name}"
        html = (
            "<html><head><meta charset=\"utf-8\"></head><body>"
            "<p>Hallo,</p>"
            f"<p>im Anhang findest Du meine {what} als JSON-Datei.</p>"
            "<p>Du kannst die Datei in der Zeiterfassung-App über "
            "<em>Einstellungen → Daten importieren</em> einlesen. "
            "Vor dem Import kannst Du einen Zeitraum auswählen und je "
            "Datentyp festlegen, was bei Konflikten passieren soll.</p>"
            f"<p>Viele Grüße<br/>{display_name}</p>"
            "</body></html>"
        )
        filename = (
            "zeiterfassung-share-"
            f"{doc['exported_at'][:10].replace('-', '')}.json"
        )

        busy["running"] = True
        set_primary_button_enabled(send_btn, False)
        set_button_text(send_btn, "Teile…")

        def fn():
            return perform_share(
                payload=payload, filename=filename,
                credentials_path=credentials_path, token_path=token_path,
                recipient=share_recipient, subject=subject, html=html,
                sync_enabled=settings.get("sync_enabled"),
                gcal_enabled=settings.get("gcal_enabled"),
                save_default=save_default_var.get(), settings=settings,
            )

        def on_done(res):
            if res["ok"]:
                if dialog.winfo_exists():
                    dialog.destroy()
                themed_showinfo(
                    parent, "Geteilt",
                    f"{what} wurden an {share_recipient} gesendet.",
                )
                return
            busy["running"] = False
            alive = dialog.winfo_exists()
            target = dialog if alive else parent
            if alive:
                set_button_text(send_btn, "Senden")
                _refresh_send_btn()
            kind = res["kind"]
            if kind == "filenotfound":
                themed_showerror(target, "Fehler", str(res["error"]))
            elif kind == "offline":
                themed_showerror(
                    target, "Keine Internetverbindung",
                    "Die Daten konnten nicht gesendet werden, weil keine "
                    "Verbindung zum Internet besteht.\n\n"
                    "Bitte prüfe deine Internetverbindung und versuche es "
                    "dann erneut.",
                )
            else:
                messagebox.showerror(
                    "Teilen fehlgeschlagen",
                    f"{type(res['error']).__name__}: {res['error']}\n\n{res['tb']}",
                    parent=target,
                )

        runner.run(fn, on_done)
```

Hinweis: `_refresh_send_btn` wird — wie schon heute — nach `do_send` definiert und per `cb_entries.config(command=...)` gebunden; der Aufruf aus `on_done` ist zur Laufzeit gültig (Late-Binding im Closure-Scope).

- [ ] **Step 3: Aufrufer in `ui.py` anpassen**

`src/ui.py` `_share`:

```python
    def _share(self):
        from src.dialogs.share_dialog import open_share_dialog
        open_share_dialog(
            self.root, self.storage, self.settings, self.base_path, self._bg,
            reservation_store=self.reservation_store,
        )
```

- [ ] **Step 4: Lint + Import-Smoke + volle Suite**

Run: `python -m ruff check src/dialogs/share_dialog.py src/ui.py ; python -c "import src.dialogs.share_dialog, src.ui" ; python -m pytest -q`
Expected: `All checks passed!`, kein Import-Fehler, Suite grün.

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/share_dialog.py src/ui.py
git commit -m "fix(share): Teilen-Pfad über BackgroundTaskRunner (Audit M10)"
```

---

### Task 7: `export_task.perform_export_pdf` (TDD)

**Files:**
- Create: `src/dialogs/export_task.py`
- Test: `tests/test_export_task.py`

**Interfaces:**
- Produces: `perform_export_pdf(*, date_from, date_to, entries, name, categories, category_breakdown) -> dict`. Erfolg: `{"ok": True, "pdf_bytes": <bytes|None>}` (None = keine Einträge). Fehler: `{"ok": False, "error": <Exception>, "tb": <str>}`. (Kein `kind` — Export hat keinen Netz-Pfad, nur den generischen Fehler.)

- [ ] **Step 1: Failing tests schreiben**

`tests/test_export_task.py`:

```python
"""perform_export_pdf: Tk-freier Worker-Kern des Export-Dialogs (Audit M10)."""

import src.dialogs.export_task as st
from src.dialogs.export_task import perform_export_pdf


def _kwargs(**over):
    base = dict(
        date_from=None, date_to=None, entries={}, name="N",
        categories=None, category_breakdown=False,
    )
    base.update(over)
    return base


def test_perform_export_success_returns_pdf_bytes(monkeypatch):
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")
    res = perform_export_pdf(**_kwargs())
    assert res == {"ok": True, "pdf_bytes": b"PDF"}


def test_perform_export_no_entries_returns_none(monkeypatch):
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: None)
    res = perform_export_pdf(**_kwargs())
    assert res == {"ok": True, "pdf_bytes": None}


def test_perform_export_error_sets_traceback(monkeypatch):
    def boom(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(st, "generate_pdf", boom)
    res = perform_export_pdf(**_kwargs())
    assert res["ok"] is False
    assert "boom" in res["tb"]
```

- [ ] **Step 2: Tests laufen lassen (rot)**

Run: `python -m pytest tests/test_export_task.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.dialogs.export_task'`)

- [ ] **Step 3: `perform_export_pdf` implementieren**

`src/dialogs/export_task.py`:

```python
"""Worker-Kern des Export-Dialogs (Audit M10): Tk-frei, wirft nie.

Nur die (potenziell teure) PDF-Erzeugung — kein Netz. Der anschließende
'Speichern unter'-Dialog und der Datei-Write bleiben im on_done auf dem
UI-Thread (asksaveasfilename ist Tk-gebunden).
"""

import logging
import traceback

from src.report import generate_pdf

log = logging.getLogger(__name__)


def perform_export_pdf(*, date_from, date_to, entries, name, categories,
                       category_breakdown):
    try:
        pdf_bytes = generate_pdf(
            date_from, date_to, entries, name=name,
            categories=categories, category_breakdown=category_breakdown)
    except Exception as e:
        log.exception("PDF-Erzeugung fehlgeschlagen")
        return {"ok": False, "error": e, "tb": traceback.format_exc()}
    return {"ok": True, "pdf_bytes": pdf_bytes}
```

- [ ] **Step 4: Tests laufen lassen (grün)**

Run: `python -m pytest tests/test_export_task.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/export_task.py tests/test_export_task.py
git commit -m "feat(export): perform_export_pdf-Worker-Kern extrahiert + getestet (Audit M10)"
```

---

### Task 8: `export_dialog` auf den Runner umstellen

**Files:**
- Modify: `src/dialogs/export_dialog.py` (Imports + Signatur + `do_export`)
- Modify: `src/ui.py` (`_export`)

**Interfaces:**
- Consumes: `export_task.perform_export_pdf`, `theme.set_button_text` (`set_primary_button_enabled` schon importiert).
- Produces: `open_export_dialog(parent, storage, settings, runner)`.

- [ ] **Step 1: Imports erweitern**

`generate_pdf`-Import aus `src.report` entfernen (nur noch `default_pdf_filename`); `theme`-Importzeile um `set_button_text` erweitern; ergänzen:

```python
from src.dialogs.export_task import perform_export_pdf
```

- [ ] **Step 2: Signatur + `busy`-Guard + `do_export` ersetzen**

Signatur zu:

```python
def open_export_dialog(parent, storage, settings, runner):
```

Direkt vor `def do_export():` das Flag, und `do_export` so ersetzen, dass `generate_pdf` in den Worker geht und `asksaveasfilename`+Write ins `on_done`:

```python
    busy = {"running": False}

    def do_export():
        if busy["running"]:
            return
        if picker.get_categories() == set():
            return
        date_from, date_to = picker.get_range()
        if date_from is None:
            themed_showerror(dialog, "Ungültiges Datum", "Bitte ein gültiges Datum eingeben.")
            return
        ok, msg = validate_period(date_from, date_to)
        if not ok:
            themed_showerror(dialog, "Ungültiger Zeitraum", msg)
            return

        # Frisch lesen (Hintergrund-Drive-Sync könnte den Storage geändert haben).
        entries = storage.get_all()
        categories = picker.get_categories()
        category_breakdown = picker.get_category_breakdown()

        busy["running"] = True
        set_primary_button_enabled(export_btn, False)
        set_button_text(export_btn, "Erzeuge…")

        def fn():
            return perform_export_pdf(
                date_from=date_from, date_to=date_to, entries=entries,
                name=settings.get("name"), categories=categories,
                category_breakdown=category_breakdown,
            )

        def on_done(res):
            busy["running"] = False
            if not dialog.winfo_exists():
                # Dialog geschlossen = Abbrechen -> Ergebnis verwerfen.
                return
            set_primary_button_enabled(export_btn, True)
            set_button_text(export_btn, "Exportieren")

            if not res["ok"]:
                messagebox.showerror(
                    "Export fehlgeschlagen",
                    f"{type(res['error']).__name__}: {res['error']}\n\n{res['tb']}",
                    parent=dialog,
                )
                return

            pdf_bytes = res["pdf_bytes"]
            if pdf_bytes is None:
                themed_showinfo(
                    dialog, "Keine Einträge",
                    f"Keine Einträge für {date_from.strftime('%d.%m.%Y')} – "
                    f"{date_to.strftime('%d.%m.%Y')} vorhanden.",
                )
                return

            path = filedialog.asksaveasfilename(
                parent=dialog,
                title="PDF speichern unter",
                initialfile=default_pdf_filename(date_from, date_to),
                defaultextension=".pdf",
                filetypes=[("PDF-Datei", "*.pdf")],
            )
            if not path:
                return

            try:
                with open(path, "wb") as f:
                    f.write(pdf_bytes)
            except OSError as e:
                themed_showerror(
                    dialog, "Export fehlgeschlagen",
                    f"Die Datei konnte nicht gespeichert werden:\n{e}")
                return

            dialog.destroy()
            themed_showinfo(parent, "Exportiert", f"PDF gespeichert unter\n{path}")

        runner.run(fn, on_done)
```

- [ ] **Step 3: Aufrufer in `ui.py` anpassen**

`src/ui.py` `_export`:

```python
    def _export(self):
        from src.dialogs.export_dialog import open_export_dialog
        open_export_dialog(self.root, self.storage, self.settings, self._bg)
```

- [ ] **Step 4: Lint + Import-Smoke + volle Suite**

Run: `python -m ruff check src/dialogs/export_dialog.py src/ui.py ; python -c "import src.dialogs.export_dialog, src.ui" ; python -m pytest -q`
Expected: `All checks passed!`, kein Import-Fehler, Suite grün.

- [ ] **Step 5: Manuelle Verifikation (App)**

Run: `python -m src.main`
Prüfen: „Exportieren" öffnen, Zeitraum wählen, „Exportieren" klicken → Button „Erzeuge…", danach erscheint der Speichern-Dialog, PDF wird geschrieben; UI bleibt bedienbar.

- [ ] **Step 6: Commit**

```bash
git add src/dialogs/export_dialog.py src/ui.py
git commit -m "fix(export): PDF-Erzeugung über BackgroundTaskRunner (Audit M10)"
```

---

### Task 9: Architektur-Doku nachziehen

**Files:**
- Modify: `src/CLAUDE.md` (Abschnitt „Threading-Modell")

**Interfaces:** keine (Doku).

- [ ] **Step 1: Threading-Modell-Absatz ergänzen**

Im Abschnitt „Threading-Modell" von `src/CLAUDE.md` nach der H5-Erwähnung ergänzen:

```markdown
Ebenso routen `send_dialog`/`share_dialog`/`export_dialog` ihre blockierenden
Operationen (PDF-Erzeugung, `get_gmail_service` inkl. OAuth, `send_email`) über
den injizierten `runner` (Audit M10): der blockierende Kern liegt Tk-frei in
`send_task`/`share_task`/`export_task` (`perform_*`, getestet); die zwei
Netz-Kerne teilen sich `mail_task.classify_mail_error`. `on_done` macht das
`winfo_exists`-gegatete Feedback, Persistenz passiert im Worker (überlebt
Dialog-Close), der Primär-Button ist während des Laufs deaktiviert.
```

- [ ] **Step 2: Commit**

```bash
git add src/CLAUDE.md
git commit -m "docs(architektur): send/share/export-Threading dokumentiert (Audit M10)"
```

---

## Abschluss

Nach Task 9: gesamte Suite grün (`python -m pytest -q`), `ruff check .` sauber, `npx pyright` weiterhin 0/0 (die neuen Module importieren nur bereits erlaubte Deps — kein neuer optionaler Import). Dann PR gegen `margenheld/master` (Branch ist auf den Stack gesetzt → GitHub-Diff enthält die Stack-Commits mit, bis die Basis-PRs #121–#123 gemergt sind).

## Self-Review-Notiz

- **Spec-Abdeckung:** Grundmuster (T3–T8), geteilter Klassifikator (T2, Spec-Abschnitt „Result-Dict & Fehlerabbildung"), Aufteilung je Dialog (T3/T4, T5/T6, T7/T8), Lauf-Feedback/busy-Guard/set_button_text (T1 + Wiring-Tasks), Close-Verhalten inkl. Export-Sonderfall (on_done-Steps), Verdrahtung `runner` required (Wiring-Tasks + ui.py), Tests (T2/T3/T5/T7), betroffene Dateien inkl. `src/CLAUDE.md` (T9) — alle abgedeckt.
- **Typkonsistenz:** `classify_mail_error` liefert `{"ok","kind","error","tb"}`; `perform_send`/`perform_share` geben es unverändert weiter; `perform_export_pdf` liefert `{"ok","pdf_bytes"}` bzw. `{"ok","error","tb"}` (kein `kind` — Export hat nur den generischen Fehler). `on_done` liest exakt diese Schlüssel. Konsistent.
