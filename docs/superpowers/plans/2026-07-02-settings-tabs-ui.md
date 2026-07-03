# Settings-Dialog auf Tabs — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den in die Höhe gewachsenen, teils einklappbaren Settings-Dialog in einen `ttk.Notebook` mit 4 thematischen Tabs umbauen, sodass er die Fensterbreite nutzt und auf allen Skalierungsstufen (75–200 %) auf den Bildschirm passt.

**Architecture:** Reiner Layout-/UX-Umbau von `open_settings_dialog`. Ein neuer Theme-Helfer `apply_notebook_style` liefert das Dark-Styling für das Notebook. Der Dialog bekommt statt einer globalen Grid-Reihe (0–36) vier `tk.Frame`-Tabs mit je lokalem Grid; jedes bestehende Widget/Callback wird unverändert in seinen Ziel-Tab umgehängt. `save_settings` bleibt eine Funktion über alle Tabs und springt bei Validierungsfehlern auf den betroffenen Tab. Keine Geschäftslogik, keine Settings-Keys, keine OAuth-/Sync-Pfade ändern sich.

**Tech Stack:** Python 3, Tkinter/ttk (clam-Theme), Pillow (nur für die lokale Screenshot-Verifikation).

**Referenz-Spec:** `docs/superpowers/specs/2026-07-02-settings-tabs-ui-design.md`

## Global Constraints

- Datumsformat: intern ISO (`YYYY-MM-DD`), in der UI deutsch über `src/time_utils.py::format_iso_date`. Hier nicht relevant (keine neuen datumsanzeigenden Stellen), aber bestehende `format_iso_date`-Nutzung in der Sync-Zeile bleibt.
- Keine neuen Google-Imports auf Modulebene (CI installiert kein `requirements.txt`); die bestehenden Lazy-Imports in den Callbacks bleiben lazy.
- Klick-Modell unangetastet — dieser Dialog hat keine Lösch-Pfade.
- `pytest` **und** `ruff check .` müssen grün bleiben.
- Dialog bleibt `resizable(False, False)`, modal (`grab_set`), Dark-Titlebar, zentriert auf Parent.
- Öffentliche Signatur von `open_settings_dialog(parent, settings, base_path, on_change, *, conflicts_store=None, storage=None, reservation_store=None, on_request_restart=None)` bleibt **unverändert**; Rückgabewert bleibt `None` (Aufrufer `src/ui.py:343` wertet keinen aus).
- Verifikation der UI läuft lokal per Screenshot-Harness (Windows-Dev-Maschine hat ein Display; CI nicht) — kein neuer CI-Test, der einen Tk-Root braucht.

**Vorab lokal verifiziert** (Screenshot-Harness, identische Maschine/Fonts): Dialogmaße 443×573 px @100 %, 601×760 @150 %, 792×915 @200 %. Damit passt der Dialog auch @200 % in eine 1080p-Arbeitsfläche (~1030 px nutzbar) → **kein Scroll-Fallback nötig**. Der dichteste Tab ist „Google".

---

### Task 1: Theme-Helfer `apply_notebook_style`

**Files:**
- Modify: `src/theme.py` (neue Funktion direkt nach `apply_combobox_style`, vor `dark_entry` — nach Zeile 211)

**Interfaces:**
- Produces: `apply_notebook_style(dialog) -> None` — konfiguriert die ttk-Styles `Dark.TNotebook` und `Dark.TNotebook.Tab`. Setzt **kein** Theme (Voraussetzung: `apply_combobox_style` lief vorher und hat `theme_use("clam")` gesetzt). Nutzt die bereits in `theme.py` definierten Farben `BG`, `CELL_BG`, `CELL_BG_HOVER`, `TEXT`, `TEXT_MUTED`, `FONT`.

- [ ] **Step 1: Funktion implementieren**

In `src/theme.py` direkt nach dem Ende von `apply_combobox_style` (nach der `Vertical.TScrollbar`-`style.map`, Zeile 211) einfügen:

```python
def apply_notebook_style(dialog):
    """Dark-Styling für ttk.Notebook (Tab-Leiste + Inhaltsfläche).

    MUSS nach apply_combobox_style laufen — das setzt global theme_use("clam");
    diese Funktion setzt selbst KEIN Theme. Aktiver Tab bekommt BG (verschmilzt
    mit der Inhaltsfläche), inaktive CELL_BG/TEXT_MUTED, Hover CELL_BG_HOVER.
    bordercolor/lightcolor/darkcolor der Notebook-Fläche auf BG, sonst zeichnet
    clam einen hellen 3D-Rand um den Inhalt, der aus dem Dark-Theme fällt.
    focuscolor=BG unterdrückt den Punktrahmen um den Tab-Text bei Fokus.
    ACCENT wird bewusst NICHT verwendet — das ist der rote Fehler-/Lösch-Akzent."""
    style = ttk.Style(dialog)
    style.configure(
        "Dark.TNotebook",
        background=BG, borderwidth=0, tabmargins=(6, 6, 6, 0),
        bordercolor=BG, lightcolor=BG, darkcolor=BG,
    )
    style.configure(
        "Dark.TNotebook.Tab",
        background=CELL_BG, foreground=TEXT_MUTED,
        bordercolor=BG, lightcolor=CELL_BG, darkcolor=CELL_BG,
        padding=(14, 6), font=FONT, focuscolor=BG,
    )
    style.map(
        "Dark.TNotebook.Tab",
        background=[("selected", BG), ("active", CELL_BG_HOVER)],
        foreground=[("selected", TEXT), ("active", TEXT)],
        lightcolor=[("selected", BG)],
        darkcolor=[("selected", BG)],
    )
```

- [ ] **Step 2: Smoke-Test lokal (Import + Style baut ohne Fehler)**

Scratchpad-Datei `smoke_notebook.py` schreiben und ausführen:

```python
import tkinter as tk
from tkinter import ttk
from src.theme import apply_combobox_style, apply_notebook_style

root = tk.Tk()
root.withdraw()
apply_combobox_style(root)
apply_notebook_style(root)
nb = ttk.Notebook(root, style="Dark.TNotebook")
f = tk.Frame(nb)
nb.add(f, text="Test")
print("ok")
root.destroy()
```

Run: `python smoke_notebook.py`
Expected: Ausgabe `ok`, kein TclError.

- [ ] **Step 3: Ruff**

Run: `ruff check src/theme.py`
Expected: keine Findings.

- [ ] **Step 4: Commit**

```bash
git add src/theme.py
git commit -m "feat(theme): apply_notebook_style — Dark-Styling für ttk.Notebook"
```

---

### Task 2: `settings_dialog.py` auf Tabs umbauen

**Files:**
- Modify: `src/dialogs/settings_dialog.py` (Import-Zeile + kompletter Rewrite von `open_settings_dialog`)

**Interfaces:**
- Consumes: `apply_notebook_style` aus Task 1.
- Produces: unveränderte öffentliche Signatur (s. Global Constraints), Rückgabe `None`.

**Was sich strukturell ändert (Überblick, Details im Code unten):**
- `apply_notebook_style` zusätzlich zum bestehenden `from src.theme import (...)` importieren.
- Nach `apply_combobox_style(dialog)` folgt `apply_notebook_style(dialog)`.
- Ein `ttk.Notebook` (gepackt) mit vier `tk.Frame`-Tabs (`tab_work`, `tab_mail`, `tab_google`, `tab_app`); darunter die Button-Zeile (gepackt). Der Dialog hat nur noch diese zwei direkten Kinder.
- Der `label(...)`-Helfer bekommt den Ziel-Frame als **erstes** Argument. Neuer Helfer `subheader(frame, text, row, top_pad=16)` für die „— Titel —"-Zwischenüberschriften.
- **Ersatzlos entfernt:** `_section_header` samt Collapse-/`_was_in_grid`-Logik, `times_label`/`toggle_times` (Standardzeiten sind dauerhaft sichtbar), der finale `mv_toggle()`-Aufruf, alle `*_widgets`/`*_toggle`-Variablen.
- „Kategorien verwalten" wandert aus der Button-Zeile in den Tab „Arbeitszeit".
- `save_settings` springt bei jedem der drei Abbruch-Pfade auf den zuständigen Tab: Standardzeit ungültig → `work`, WSL-Zeitraum ungültig → `work`, Autostart-Fehler → `app`. Die Wochenlimit-**Warnung** (kein Abbruch) springt ebenfalls auf `work`.

- [ ] **Step 1: Datei komplett ersetzen**

Kompletten Inhalt von `src/dialogs/settings_dialog.py` durch Folgendes ersetzen:

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

from src.autostart import disable_autostart, enable_autostart, resolve_autostart_target
from src.platform_open import open_folder
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL,
    PAUSE_VALUES, STATUS_OK, TEXT, TEXT_MUTED, TIME_VALUES,
    apply_app_icon, apply_combobox_style, apply_dark_titlebar,
    apply_notebook_style, attach_unfocus_on_click,
    center_dialog_on_parent, disable_min_max,
    dark_combo, dark_entry, dark_text,
    primary_button, secondary_button,
    themed_askyesno, themed_showinfo, themed_showwarning, themed_showerror,
)
from src.dialogs.category_dialog import open_category_dialog
from src.holidays_de import STATES, code_for_state_label
from src.settings import WEEKDAY_KEYS, clamp_ui_scale, parse_hourly_rate, resolve_calendar_id
from src.time_utils import format_iso_date, validate_period
from src.time_utils import DAYS_DE, validate_entry
from src.weekly_limit import format_limit_warnings, period_scan_needed, scan_period_for_warnings


def open_settings_dialog(parent, settings, base_path, on_change, *,
                         conflicts_store=None, storage=None,
                         reservation_store=None, on_request_restart=None):
    """Modaler Dialog zum Bearbeiten der App-Einstellungen, aufgeteilt auf vier
    Tabs (Arbeitszeit / Bericht & Mail / Google / App).

    on_change wird nach erfolgreichem Speichern aufgerufen, damit der Kalender
    sich aktualisiert. conflicts_store und storage sind optional; sind sie
    gesetzt, erscheint im Google-Tab der Sync-Block mit Konflikte-Button.
    """
    dialog = tk.Toplevel(parent)
    dialog.title("Einstellungen")
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.focus_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)
    disable_min_max(dialog)
    apply_app_icon(dialog)

    apply_combobox_style(dialog)
    apply_notebook_style(dialog)

    creds_path = os.path.join(base_path, "credentials.json")

    notebook = ttk.Notebook(dialog, style="Dark.TNotebook")
    notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))

    tab_work = tk.Frame(notebook, bg=BG)
    tab_mail = tk.Frame(notebook, bg=BG)
    tab_google = tk.Frame(notebook, bg=BG)
    tab_app = tk.Frame(notebook, bg=BG)
    notebook.add(tab_work, text="Arbeitszeit")
    notebook.add(tab_mail, text="Bericht & Mail")
    notebook.add(tab_google, text="Google")
    notebook.add(tab_app, text="App")

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

    # ===================== Tab: Arbeitszeit =====================
    label(tab_work, "Standardzeiten:", row=0, pady=(10, 4), sticky="nw")
    times_frame = tk.Frame(tab_work, bg=BG)
    times_frame.grid(row=0, column=1, padx=10, pady=(10, 4), sticky="w")

    tk.Label(times_frame, text="Start", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
        row=0, column=1, padx=2)
    tk.Label(times_frame, text="Ende", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
        row=0, column=2, padx=2)

    start_vars = {}
    end_vars = {}
    for i, (key, lbl) in enumerate(zip(WEEKDAY_KEYS, DAYS_DE), start=1):
        tk.Label(times_frame, text=lbl, font=FONT, bg=BG, fg=TEXT, width=3, anchor="w").grid(
            row=i, column=0, padx=(0, 8), pady=2)
        start_vars[key] = tk.StringVar(value=settings.get(f"default_start_{key}"))
        dark_combo(times_frame, start_vars[key], TIME_VALUES).grid(
            row=i, column=1, padx=2, pady=2)
        end_vars[key] = tk.StringVar(value=settings.get(f"default_end_{key}"))
        dark_combo(times_frame, end_vars[key], TIME_VALUES).grid(
            row=i, column=2, padx=2, pady=2)

    label(tab_work, "Standard-Pause (Min):", row=1)
    pause_var = tk.StringVar(value=str(settings.get("default_pause")))
    dark_combo(tab_work, pause_var, PAUSE_VALUES).grid(
        row=1, column=1, padx=10, pady=8, sticky="w")

    subheader(tab_work, "Werkstudenten-Limit", row=2)
    wsl_frame = tk.Frame(tab_work, bg=BG)
    wsl_frame.grid(row=3, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="we")

    wsl_enabled_var = tk.BooleanVar(value=settings.get("werkstudent_limit_enabled"))
    tk.Checkbutton(
        wsl_frame, text="Wochenstunden-Limit aktivieren", variable=wsl_enabled_var,
        font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT, cursor="hand2",
    ).pack(anchor="w")

    def _wsl_date_row(parent_frame, label_text, default_date):
        row = tk.Frame(parent_frame, bg=BG)
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

    secondary_button(
        tab_work, "Kategorien verwalten",
        lambda: open_category_dialog(dialog, settings),
    ).grid(row=4, column=0, columnspan=2, padx=10, pady=(12, 8), sticky="w")

    # ===================== Tab: Bericht & Mail =====================
    label(tab_mail, "Empfänger:", row=0, pady=(10, 8))
    recipient_var = tk.StringVar(value=settings.get("recipient"))
    dark_entry(tab_mail, recipient_var, width=25).grid(row=0, column=1, padx=10, pady=(10, 8))

    label(tab_mail, "Name:", row=1)
    name_var = tk.StringVar(value=settings.get("name"))
    dark_entry(tab_mail, name_var, width=25).grid(row=1, column=1, padx=10, pady=8)

    label(tab_mail, "Stundenlohn (€):", row=2)
    rate_var = tk.StringVar(value=str(settings.get("hourly_rate") or ""))
    dark_entry(tab_mail, rate_var, width=10).grid(row=2, column=1, padx=10, pady=8, sticky="w")
    tk.Label(
        tab_mail, text="(optional – nur für dich sichtbar)", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=2, column=1, padx=(120, 10), pady=8, sticky="w")

    subheader(tab_mail, "Mail-Vorlage", row=3)

    label(tab_mail, "Betreff:", row=4, pady=4)
    subject_var = tk.StringVar(value=settings.get("mail_subject"))
    dark_entry(tab_mail, subject_var, width=35).grid(row=4, column=1, padx=10, pady=4)

    label(tab_mail, "Anrede:", row=5, pady=4)
    greeting_var = tk.StringVar(value=settings.get("mail_greeting"))
    dark_entry(tab_mail, greeting_var, width=35).grid(row=5, column=1, padx=10, pady=4)

    label(tab_mail, "Inhalt:", row=6, pady=4, sticky="nw")
    content_text = dark_text(tab_mail, 35, 3)
    content_text.grid(row=6, column=1, padx=10, pady=4)
    content_text.insert("1.0", settings.get("mail_content"))

    label(tab_mail, "Gruß:", row=7, pady=4, sticky="nw")
    closing_text = dark_text(tab_mail, 35, 2)
    closing_text.grid(row=7, column=1, padx=10, pady=4)
    closing_text.insert("1.0", settings.get("mail_closing"))

    tk.Label(
        tab_mail, text="Platzhalter: {zeitraum}, {gesamt}", font=("Segoe UI", 8),
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=8, column=0, columnspan=2, padx=10, pady=(0, 8))

    # ===================== Tab: Google =====================
    subheader(tab_google, "Google-Konto", row=0, top_pad=10)

    label(tab_google, "Datenordner:", row=1, pady=4)
    creds_row = tk.Frame(tab_google, bg=BG)
    creds_row.grid(row=1, column=1, padx=10, pady=4, sticky="w")

    def open_data_folder():
        try:
            open_folder(base_path)
        except Exception as e:
            logging.getLogger(__name__).exception("Datenordner konnte nicht geöffnet werden")
            messagebox.showerror(
                "Ordner konnte nicht geöffnet werden",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=dialog,
            )

    secondary_button(creds_row, "Ordner öffnen", open_data_folder, padx=12, pady=2).pack(side=tk.LEFT)

    status_label = tk.Label(creds_row, text="", font=FONT_SMALL, bg=BG)
    status_label.pack(side=tk.LEFT, padx=(10, 0))

    def refresh_status():
        if not status_label.winfo_exists():
            return
        if os.path.exists(creds_path):
            status_label.config(text="✓ credentials.json vorhanden", fg=STATUS_OK)
        else:
            status_label.config(text="✗ credentials.json fehlt", fg=ACCENT)
        dialog.after(500, refresh_status)

    refresh_status()

    # Absender-Zeile: zeigt die authentifizierte E-Mail-Adresse, die ui.py
    # im Hintergrund über OAuth2-userinfo abruft und in settings cached.
    label(tab_google, "Absender:", row=2, pady=(0, 4))
    sender_row = tk.Frame(tab_google, bg=BG)
    sender_row.grid(row=2, column=1, padx=10, pady=(0, 4), sticky="w")
    sender_label = tk.Label(
        sender_row,
        text=settings.get("sender_email") or "(noch nicht ermittelt)",
        font=FONT, bg=BG, fg=TEXT_MUTED,
    )
    sender_label.pack(side=tk.LEFT)

    def _set_sender_btn_text(text):
        # secondary_button ist ein Frame+Label-Konstrukt (kein tk.Button),
        # der Text liegt am inneren `_label`. Kein -state-Option — wir
        # markieren den laufenden Zustand nur über den Text.
        if hasattr(sender_btn, "_label"):
            sender_btn._label.config(text=text)

    def _refresh_sender():
        """OAuth-Flow + userinfo-Fetch im Thread, danach Label aktualisieren."""
        from src.dialogs.send_dialog import show_missing_credentials_dialog
        from src.mail import fetch_user_email, get_gmail_service

        if not os.path.exists(creds_path):
            # Konsistent mit Senden/Teilen: freundlicher Hinweis + „Datenordner
            # öffnen" statt OAuth-Traceback bei fehlender credentials.json.
            show_missing_credentials_dialog(dialog, base_path)
            return

        _set_sender_btn_text("Verbinde…")

        def _do():
            try:
                # OAuth-Flow läuft, falls Token fehlt oder Scopes upgegradet werden müssen.
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
                err = e
                tb = traceback.format_exc()
                dialog.after(0, lambda: _finish_refresh_error(err, tb))
                return
            dialog.after(0, lambda: _finish_refresh_ok(email))

        threading.Thread(target=_do, daemon=True).start()

    def _finish_refresh_ok(email):
        if not sender_label.winfo_exists():
            return
        _set_sender_btn_text("Aktualisieren")
        if email:
            settings.set("sender_email", email)
            sender_label.config(text=email)
        else:
            sender_label.config(text="(nicht verfügbar — Scope fehlt evtl.)")

    def _finish_refresh_error(err, tb):
        if not sender_label.winfo_exists():
            return
        _set_sender_btn_text("Aktualisieren")
        messagebox.showerror(
            "Anmeldung fehlgeschlagen",
            f"OAuth-Flow oder Userinfo-Aufruf fehlgeschlagen:\n\n{err}\n\n{tb}",
            parent=dialog,
        )

    sender_btn = secondary_button(
        sender_row,
        "Aktualisieren" if settings.get("sender_email") else "Anmelden",
        _refresh_sender,
        padx=12, pady=2,
    )
    sender_btn.pack(side=tk.LEFT, padx=(10, 0))

    subheader(tab_google, "Synchronisation", row=3)
    tk.Label(
        tab_google, text="Diese Schalter wirken sofort (Anmeldung im Browser).",
        font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
    ).grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="w")

    var_sync = tk.BooleanVar(value=settings.get("sync_enabled"))

    # Forward-Deklaration: die Closures unten referenzieren cb_sync, das erst
    # weiter unten als Checkbutton erzeugt wird. Beim ersten Aufruf der
    # Closures (User-Interaktion) ist cb_sync garantiert gesetzt — das assert
    # narrowt den Typ für Pylance.
    cb_sync: tk.Checkbutton | None = None

    def _finish_oauth(err, tb):
        assert cb_sync is not None
        cb_sync.config(state="normal")
        if err is None:
            settings.set("sync_enabled", True)
            on_change()
            return
        messagebox.showerror(
            "Synchronisation aktivieren",
            f"OAuth-Flow fehlgeschlagen:\n\n{err}\n\n{tb}",
            parent=dialog,
        )
        var_sync.set(False)

    def _on_sync_toggled():
        assert cb_sync is not None
        new_state = var_sync.get()
        if new_state and not settings.get("sync_enabled"):
            cb_sync.config(state="disabled")

            def _do_oauth():
                err = None
                tb = ""
                try:
                    from src import drive
                    drive.get_drive_service(
                        os.path.join(base_path, "credentials.json"),
                        os.path.join(base_path, "token.json"),
                        gcal_enabled=settings.get("gcal_enabled"),
                    )
                except Exception as e:
                    err = e
                    tb = traceback.format_exc()
                dialog.after(0, lambda: _finish_oauth(err, tb))

            threading.Thread(target=_do_oauth, daemon=True).start()
            return
        if not new_state and settings.get("sync_enabled"):
            settings.set("sync_enabled", False)
            on_change()

    cb_sync = tk.Checkbutton(
        tab_google, text="Mit Google Drive synchronisieren",
        variable=var_sync, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
        command=_on_sync_toggled,
    )
    cb_sync.grid(row=5, column=0, columnspan=2, padx=10, pady=(4, 0), sticky="w")

    device_id = settings.get("device_id") or "(noch nicht gesetzt)"
    device_id_short = device_id[:8] + "…" if len(device_id) > 8 else device_id
    tk.Label(
        tab_google, text=f"Geräte-ID: {device_id_short}", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=6, column=0, columnspan=2, padx=10, pady=(2, 0), sticky="w")

    last = format_iso_date(settings.get("last_pull_at"), fallback="noch nie")
    tk.Label(
        tab_google, text=f"Letzte Synchronisation: {last}", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=7, column=0, columnspan=2, padx=10, pady=(2, 4), sticky="w")

    # Ab hier wachsen im Google-Tab optionale Zeilen (Konflikte, Kompaktieren)
    # dynamisch — deshalb eine laufende Row-Nummer statt fixer Konstanten.
    next_google_row = 8
    unresolved = 0
    if conflicts_store is not None:
        unresolved = conflicts_store.count_unresolved()
    if unresolved > 0:
        def _open_conflicts_dialog():
            from src.dialogs.conflicts_dialog import ConflictsDialog
            ConflictsDialog(dialog, storage, settings, conflicts_store)

        secondary_button(
            tab_google,
            f"Konflikte ansehen ({unresolved})",
            _open_conflicts_dialog,
            padx=12, pady=2,
        ).grid(row=next_google_row, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")
        next_google_row += 1

    def _open_import_dialog():
        from src.dialogs.import_dialog import open_import_dialog

        def _after_import():
            on_change()
            dialog.destroy()

        open_import_dialog(
            dialog, storage, settings, _after_import,
            reservation_store=reservation_store,
        )

    btn_row = tk.Frame(tab_google, bg=BG)
    btn_row.grid(row=next_google_row, column=0, columnspan=2, padx=10, pady=(4, 8), sticky="w")
    next_google_row += 1

    # label_button liefert einen tk.Frame (keine -state-Option) — Doppelklick-
    # Schutz daher über ein Flag statt cb.config(state=...).
    reconnect_busy = {"value": False}

    def _finish_reconnect(err, tb):
        reconnect_busy["value"] = False
        if not dialog.winfo_exists():
            return
        if err is None:
            themed_showinfo(
                dialog, "Google neu verbunden",
                "Die Google-Berechtigungen wurden erneuert. Die "
                "Synchronisation sollte jetzt wieder funktionieren.",
            )
            return
        messagebox.showerror(
            "Google neu verbinden",
            f"Die Neuverbindung ist fehlgeschlagen:\n\n{err}\n\n{tb}",
            parent=dialog,
        )

    def _reconnect_google():
        if reconnect_busy["value"]:
            return
        if not themed_askyesno(
            dialog, "Google neu verbinden",
            "Die App fragt die Google-Berechtigungen neu ab. Dazu öffnet sich "
            "ein Browser-Fenster zur Anmeldung — bitte dort die Freigabe "
            "bestätigen.\n\nFortfahren?",
        ):
            return
        reconnect_busy["value"] = True

        def _do():
            err, tb = None, ""
            try:
                from src import drive
                drive.reconnect(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
            except Exception as e:
                err, tb = e, traceback.format_exc()
            dialog.after(0, lambda: _finish_reconnect(err, tb))

        threading.Thread(target=_do, daemon=True).start()

    reconnect_btn = secondary_button(
        btn_row, "Google neu verbinden", _reconnect_google, padx=12, pady=2)
    reconnect_btn.pack(side=tk.LEFT)

    if storage is not None:
        secondary_button(
            btn_row, "Daten importieren", _open_import_dialog, padx=12, pady=2,
        ).pack(side=tk.LEFT, padx=(8, 0))

    if settings.get("sync_enabled") and storage is not None and conflicts_store is not None:
        def _on_compact_clicked():
            confirmed = themed_askyesno(
                dialog,
                "Sync-Daten kompaktieren",
                "Entfernt alte gelöschte Einträge endgültig aus dem Sync.\n\n"
                "Nur ausführen, wenn ALLE deine Geräte auf der aktuellen Version "
                "sind und kürzlich synchronisiert haben.\n\nFortfahren?",
            )
            if not confirmed:
                return

            def _show(res):
                if not dialog.winfo_exists():
                    return
                if res.get("reason") == "old_version":
                    themed_showwarning(
                        dialog,
                        "Kompaktierung abgebrochen",
                        "Ein Gerät nutzt noch eine ältere Version — bitte erst "
                        "alle Geräte aktualisieren und synchronisieren.",
                    )
                elif res.get("reason") == "newer_version":
                    from src.sync import NEWER_REMOTE_VERSION_MSG
                    themed_showwarning(
                        dialog, "Update erforderlich", NEWER_REMOTE_VERSION_MSG,
                    )
                elif not res.get("ok"):
                    detail = f"{res.get('error', '?')}\n\n{res.get('tb', '')}"
                    themed_showerror(
                        dialog,
                        "Kompaktierung fehlgeschlagen",
                        f"Die Kompaktierung ist fehlgeschlagen:\n\n{detail}",
                    )
                else:
                    themed_showinfo(
                        dialog,
                        "Kompaktierung", "Sync-Daten wurden kompaktiert.",
                    )

            def _do():
                from src.main import _run_compaction_blocking
                res = _run_compaction_blocking(
                    storage, settings, conflicts_store, base_path)
                dialog.after(0, lambda: _show(res))

            threading.Thread(target=_do, daemon=True).start()

        secondary_button(
            tab_google, "Sync-Daten kompaktieren", _on_compact_clicked,
            padx=12, pady=2,
        ).grid(row=next_google_row, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")
        next_google_row += 1

    subheader(tab_google, "Google Kalender", row=next_google_row)
    next_google_row += 1

    var_gcal = tk.BooleanVar(value=settings.get("gcal_enabled"))
    cb_gcal: tk.Checkbutton | None = None

    # Kalender-Auswahl: Combobox zeigt Klarnamen, gespeichert wird die ID.
    # cal_map summary->id wird im Hintergrund per API befüllt.
    cal_map: dict[str, str] = {}
    cal_var = tk.StringVar(value=settings.get("gcal_calendar_id") or "primary")

    gcal_check_row = next_google_row
    cal_label_row = next_google_row + 1
    cal_status_row = next_google_row + 2

    cb_gcal = tk.Checkbutton(
        tab_google, text="Reservierungen mit Google Kalender abgleichen",
        variable=var_gcal, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    )
    cb_gcal.grid(row=gcal_check_row, column=0, columnspan=2, padx=10, pady=(4, 0), sticky="w")

    tk.Label(tab_google, text="Kalender:", font=FONT, bg=BG, fg=TEXT).grid(
        row=cal_label_row, column=0, padx=10, pady=4, sticky="w")
    cal_combo = dark_combo(tab_google, cal_var, [cal_var.get()], width=30)
    cal_combo.grid(row=cal_label_row, column=1, padx=10, pady=4, sticky="w")

    cal_status = tk.Label(tab_google, text="", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED)
    cal_status.grid(row=cal_status_row, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="w")

    def _populate_calendars(items):
        if not cal_combo.winfo_exists():
            return
        cal_map.clear()
        for it in items:
            cal_map[it["summary"]] = it["id"]
        cal_combo["values"] = list(cal_map.keys()) or [cal_var.get()]
        # Gespeicherte ID auf den passenden Klarnamen zurückmappen.
        stored_id = settings.get("gcal_calendar_id") or "primary"
        for summary, cid in cal_map.items():
            if cid == stored_id:
                cal_var.set(summary)
                break
        cal_status.config(text="")

    def _load_calendars():
        cal_status.config(text="Kalenderliste wird geladen…")

        def _do():
            try:
                from src import gcal
                service = gcal.get_calendar_service(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    sync_enabled=settings.get("sync_enabled"),
                )
                items = gcal.list_calendars(service)
            except Exception as e:
                tb = traceback.format_exc()
                # e/tb als Default-Argumente binden: das Lambda läuft via
                # dialog.after() VERZÖGERT — bis dahin hat Python die
                # except-Variable `e` am Blockende gelöscht (impliziter del),
                # ein freier Zugriff gäbe NameError.
                dialog.after(
                    0, lambda e=e, tb=tb: _load_calendars_error(e, tb))
                return
            dialog.after(0, lambda: _populate_calendars(items))

        threading.Thread(target=_do, daemon=True).start()

    def _load_calendars_error(err, tb):
        if cal_status.winfo_exists():
            cal_status.config(text="Kalenderliste nicht verfügbar")
        messagebox.showerror(
            "Google Kalender",
            f"Kalenderliste konnte nicht geladen werden:\n\n{err}\n\n{tb}",
            parent=dialog,
        )

    def _finish_gcal_oauth(err, tb):
        assert cb_gcal is not None
        if not cb_gcal.winfo_exists():
            return  # Dialog wurde während des OAuth-Flows geschlossen.
        cb_gcal.config(state="normal")
        if err is None:
            settings.set("gcal_enabled", True)
            on_change()
            _load_calendars()
            return
        messagebox.showerror(
            "Google Kalender aktivieren",
            f"OAuth-Flow fehlgeschlagen:\n\n{err}\n\n{tb}",
            parent=dialog,
        )
        var_gcal.set(False)

    def _on_gcal_toggled():
        assert cb_gcal is not None
        new_state = var_gcal.get()
        if new_state and not settings.get("gcal_enabled"):
            cb_gcal.config(state="disabled")

            def _do_oauth():
                err, tb = None, ""
                try:
                    from src import gcal
                    gcal.get_calendar_service(
                        os.path.join(base_path, "credentials.json"),
                        os.path.join(base_path, "token.json"),
                        sync_enabled=settings.get("sync_enabled"),
                    )
                except Exception as e:
                    err, tb = e, traceback.format_exc()
                dialog.after(0, lambda: _finish_gcal_oauth(err, tb))

            threading.Thread(target=_do_oauth, daemon=True).start()
            return
        if not new_state and settings.get("gcal_enabled"):
            settings.set("gcal_enabled", False)
            on_change()

    cb_gcal.config(command=_on_gcal_toggled)

    if settings.get("gcal_enabled"):
        _load_calendars()

    # ===================== Tab: App =====================
    label(tab_app, "Bundesland:", row=0, pady=(10, 8))
    state_labels = [lbl for _, lbl in STATES]
    current_code = settings.get("state")
    current_label = next(
        (lbl for code, lbl in STATES if code == current_code),
        STATES[0][1],
    )
    state_var = tk.StringVar(value=current_label)
    dark_combo(tab_app, state_var, state_labels, width=22).grid(
        row=0, column=1, padx=10, pady=(10, 8), sticky="w")

    # Gerätelokale UI-Optionen. Alle in app_frame (ein Grid-Member), damit die
    # pack-Interna dieses Frames unberührt bleiben.
    app_frame = tk.Frame(tab_app, bg=BG)
    app_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=(4, 4), sticky="we")

    show_weekend_var = tk.BooleanVar(value=settings.get("show_weekend"))
    tk.Checkbutton(
        app_frame, text="Wochenende (Sa/So) im Kalender anzeigen",
        variable=show_weekend_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).pack(anchor="w")

    autostart_var = tk.BooleanVar(value=settings.get("autostart"))
    tk.Checkbutton(
        app_frame, text="Autostart (minimiert bei Anmeldung)",
        variable=autostart_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).pack(anchor="w")

    always_on_top_var = tk.BooleanVar(value=settings.get("always_on_top"))
    tk.Checkbutton(
        app_frame, text="Immer im Vordergrund",
        variable=always_on_top_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).pack(anchor="w")

    minimize_to_tray_var = tk.BooleanVar(value=settings.get("minimize_to_tray"))
    tk.Checkbutton(
        app_frame, text="Beim Schließen in den Infobereich minimieren",
        variable=minimize_to_tray_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).pack(anchor="w")

    # --- Darstellung (UI-Skalierung, gerätelokal) ---
    tk.Label(
        app_frame, text="— Darstellung —", font=FONT_BOLD,
        bg=BG, fg=TEXT_MUTED,
    ).pack(pady=(12, 4))
    scale_row = tk.Frame(app_frame, bg=BG)
    scale_row.pack(fill="x")
    tk.Label(
        scale_row, text="Skalierung:", font=FONT, bg=BG, fg=TEXT,
    ).pack(side=tk.LEFT, padx=(0, 8))

    # ttk.Scale statt klassischer tk.Scale: das clam-Theme ist via
    # apply_combobox_style aktiv, klassische tk.Scale rendert unter Windows
    # einen hellen System-Trough/-Regler. Wert in eigenem Label (kein
    # showvalue-Kasten); auf 5er-Schritte gerastert (ttk.Scale kennt kein
    # resolution). Akzent analog dark_entry: Ruhe TEXT_MUTED, Press ACCENT.
    scale_style = ttk.Style(dialog)
    scale_style.configure(
        "Display.Horizontal.TScale",
        background=TEXT_MUTED, troughcolor=CELL_BG,
        bordercolor=CELL_BG, darkcolor=TEXT_MUTED, lightcolor=TEXT_MUTED,
    )
    scale_style.map(
        "Display.Horizontal.TScale",
        background=[("pressed", ACCENT)],
        darkcolor=[("pressed", ACCENT)],
        lightcolor=[("pressed", ACCENT)],
    )
    scale_var = tk.DoubleVar(value=round(settings.get("ui_scale") * 100))
    scale_value_label = tk.Label(
        scale_row, text=f"{round(scale_var.get() / 5) * 5} %", font=FONT,
        bg=BG, fg=TEXT_MUTED, width=5, anchor="w",
    )

    def _on_scale(_raw):
        scale_value_label.config(text=f"{round(scale_var.get() / 5) * 5} %")

    scale_widget = ttk.Scale(
        scale_row, from_=75, to=200, orient="horizontal",
        variable=scale_var, command=_on_scale, length=200,
        style="Display.Horizontal.TScale",
    )
    scale_widget.bind(
        "<ButtonPress-1>", lambda _e: scale_value_label.config(fg=ACCENT), add="+",
    )
    scale_widget.bind(
        "<ButtonRelease-1>", lambda _e: scale_value_label.config(fg=TEXT_MUTED), add="+",
    )
    scale_widget.pack(side=tk.LEFT)
    scale_value_label.pack(side=tk.LEFT, padx=(8, 0))
    tk.Label(
        app_frame, text="Änderung startet die App neu.", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).pack(anchor="w", pady=(2, 0))

    # ===================== Speichern / Buttons =====================
    tabs = {"work": tab_work, "mail": tab_mail, "google": tab_google, "app": tab_app}

    def save_settings():
        for key, lbl in zip(WEEKDAY_KEYS, DAYS_DE):
            ok, msg = validate_entry(start_vars[key].get(), end_vars[key].get())
            if not ok:
                notebook.select(tabs["work"])
                themed_showerror(
                    dialog,
                    "Standard-Arbeitszeit ungültig",
                    f"{lbl}: {msg}",
                )
                return

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
                notebook.select(tabs["work"])
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

        new_autostart = autostart_var.get()
        old_autostart = settings.get("autostart")

        # Autostart-Toggle muss vor dem Settings-Write passieren, weil
        # er failen kann und dann nichts persistiert werden soll.
        if new_autostart != old_autostart:
            try:
                if new_autostart:
                    target, arguments = resolve_autostart_target(base_path)
                    enable_autostart(target, arguments)
                else:
                    disable_autostart()
            except Exception as e:
                notebook.select(tabs["app"])
                themed_showerror(
                    dialog,
                    "Autostart-Fehler",
                    f"Autostart konnte nicht geändert werden:\n{e}",
                )
                return

        hourly_rate = parse_hourly_rate(rate_var.get())
        selected_code = code_for_state_label(state_var.get())
        old_scale = settings.get("ui_scale")
        new_scale = clamp_ui_scale((round(scale_var.get() / 5) * 5) / 100)

        updates = {
            "autostart": new_autostart,
            "default_pause": int(pause_var.get()),
            "recipient": recipient_var.get(),
            "name": name_var.get(),
            "mail_subject": subject_var.get(),
            "mail_greeting": greeting_var.get(),
            "mail_content": content_text.get("1.0", "end-1c"),
            "mail_closing": closing_text.get("1.0", "end-1c"),
            "hourly_rate": hourly_rate,
            "state": selected_code,
            "show_weekend": show_weekend_var.get(),
            "always_on_top": always_on_top_var.get(),
            "minimize_to_tray": minimize_to_tray_var.get(),
            "ui_scale": new_scale,
            "werkstudent_limit_enabled": wsl_enabled_var.get(),
            "werkstudent_limit_start": wsl_start_iso,
            "werkstudent_limit_end": wsl_end_iso,
            "werkstudent_limit_max_hours": wsl_max_hours,
        }
        for key in WEEKDAY_KEYS:
            updates[f"default_start_{key}"] = start_vars[key].get()
            updates[f"default_end_{key}"] = end_vars[key].get()
        settings.apply_updates(updates)
        # Kalender-Auswahl: Klarname zurück auf ID mappen, als Sync-Setting
        # speichern. Nur wenn die Kalenderliste schon geladen ist (cal_map
        # gefüllt) — sonst würde ein vorschnelles Speichern "primary" festschreiben.
        if settings.get("gcal_enabled") and cal_map:
            selected_cal_id = resolve_calendar_id(
                cal_map, cal_var.get(), settings.get("gcal_calendar_id"))
            if selected_cal_id != settings.get("gcal_calendar_id"):
                settings.set_synced("gcal_calendar_id", selected_cal_id)

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
                notebook.select(tabs["work"])
                themed_showwarning(
                    dialog, "Wochenlimit überschritten",
                    "Im konfigurierten Zeitraum liegen bereits erfasste Wochen über "
                    f"dem Limit:\n\n{format_limit_warnings(period_warnings)}\n\n"
                    "Grobe Näherung, keine rechtliche Bewertung.",
                )

        on_change()
        dialog.destroy()
        if on_request_restart is not None and new_scale != old_scale:
            on_request_restart()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(pady=12)
    primary_button(btn_frame, "Speichern", save_settings).pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    attach_unfocus_on_click(dialog)
    dialog.bind("<Escape>", lambda _e: dialog.destroy())
    center_dialog_on_parent(dialog, parent)
```

- [ ] **Step 2: Bestehende Tests laufen lassen (dürfen nicht brechen)**

Run: `pytest -q`
Expected: PASS — kein Test instanziert den Dialog; die aus dem Dialog extrahierte pure Logik (`code_for_state_label`, `parse_hourly_rate`, `resolve_calendar_id`) ist unverändert.

- [ ] **Step 3: Ruff**

Run: `ruff check .`
Expected: keine Findings. (Insbesondere kein ungenutzter Import — `format_iso_date`, alle Theme-Symbole werden verwendet; `FONT_BOLD` in `subheader`/Darstellung.)

- [ ] **Step 4: Screenshot-Verifikation @100/150/200 %**

Scratchpad-Datei `verify_settings.py` schreiben (nutzt die ECHTEN Repo-Module) und ausführen:

```python
import os
import tempfile
import tkinter as tk
from PIL import ImageGrab
from src.settings import Settings
from src.theme import init_fonts
from src.dialogs.settings_dialog import open_settings_dialog

OUT = os.path.dirname(os.path.abspath(__file__))


def run_at(pct):
    tmp = tempfile.mkdtemp()
    st = Settings(os.path.join(tmp, "settings.json"))
    st.set("ui_scale", pct / 100)
    root = tk.Tk()
    root.withdraw()
    init_fonts(root, st.get("ui_scale"))
    open_settings_dialog(root, st, tmp, lambda: None)
    dialog = root.winfo_children()[0]
    nb = [w for w in dialog.winfo_children() if w.winfo_class() == "TNotebook"][0]

    def grab(name):
        dialog.geometry("+0+0")
        dialog.attributes("-topmost", True)
        dialog.lift()
        dialog.update_idletasks()
        dialog.update()
        x, y = dialog.winfo_rootx(), dialog.winfo_rooty()
        w, h = dialog.winfo_width(), dialog.winfo_height()
        sw, sh = dialog.winfo_screenwidth(), dialog.winfo_screenheight()
        ImageGrab.grab(bbox=(x, y, min(x + w, sw), min(y + h, sh))).save(
            os.path.join(OUT, name))
        return w, h

    def do():
        for i, key in enumerate(("work", "mail", "google", "app")):
            nb.select(i)
            dialog.update_idletasks()
            w, h = grab(f"v_{key}_{pct}.png")
            print(f"{pct}% {key} {w}x{h}")
        root.destroy()

    root.after(500, do)
    root.mainloop()


for p in (100, 150, 200):
    run_at(p)
```

Run: `python verify_settings.py`
Expected: 12 PNGs. Prüfen (Read-Tool auf die PNGs):
- **@100 %:** alle vier Tabs vollständig, Höhe ~570 px, Speichern/Abbrechen sichtbar.
- **@200 %:** „Google"-Tab (dichtester) vollständig, Höhe ≤ ~1030 px, Buttons sichtbar, nichts abgeschnitten.
- Aktiver Tab hebt sich klar vom inaktiven ab (heller Inhaltston vs. dunklere Reiter).
- Kein heller 3D-Rand um die Inhaltsfläche.

Falls @200 % der Google-Tab wider Erwarten überläuft: Canvas+Scrollbar-Fallback **nur für tab_google** nach Vorbild `src/dialogs/import_dialog.py:445-485` nachrüsten. (Vorab-Verifikation ergab 792×915 → nicht erwartet.)

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/settings_dialog.py
git commit -m "feat(settings): Dialog auf ttk.Notebook mit 4 Tabs umbauen

- Arbeitszeit / Bericht & Mail / Google / App statt einer langen Spalte
- Klapp-Sections (_section_header) entfernt, Standardzeiten dauerhaft sichtbar
- Kategorien-Button in den Arbeitszeit-Tab
- save_settings springt bei Validierungsfehlern auf den betroffenen Tab
- passt @75-200 % auf den Bildschirm (443x573 @100, 792x915 @200)"
```

---

### Task 3: Doku nachziehen

**Files:**
- Modify: `src/CLAUDE.md` (Dialoge-Abschnitt — kurzer Hinweis auf die Tab-Struktur)

**Interfaces:** keine.

- [ ] **Step 1: Dialog-Beschreibung ergänzen**

In `src/CLAUDE.md` im Abschnitt „## Dialoge (`src/dialogs/`)" die `settings_dialog`-Nennung um den Zusatz ergänzen (im bestehenden Satz):

> `settings_dialog` (4 Tabs über `ttk.Notebook`: Arbeitszeit / Bericht & Mail / Google / App; Dark-Styling via `theme.apply_notebook_style`)

- [ ] **Step 2: Commit**

```bash
git add src/CLAUDE.md
git commit -m "docs(src): Settings-Dialog-Tab-Struktur in der Architektur-Referenz vermerken"
```

---

## Self-Review (durch den Plan-Autor bereits durchlaufen)

- **Spec-Abdeckung:** 4-Tab-Aufteilung (Task 2), `apply_notebook_style` inkl. Hover + Rand-Abdunklung (Task 1), Entfall der Klapp-Mechanik (Task 2), Fehlerpfad→Tab für alle drei Abbrüche + Warnung (Task 2 `save_settings`), Skalierungs-Verifikation 100/150/200 % (Task 2 Step 4), Doku (Task 3). Kein offener Spec-Punkt.
- **Platzhalter:** keine — vollständiger Dateiinhalt statt „analog zu…".
- **Typ-/Namenskonsistenz:** `apply_notebook_style` identisch in Task 1 (Definition) und Task 2 (Import/Aufruf); Style-Namen `Dark.TNotebook`/`Dark.TNotebook.Tab` konsistent; `tabs`-Dict-Keys `work/mail/google/app` konsistent mit den `notebook.select(tabs[...])`-Aufrufen.
- **Pre-Release-Hinweis (Root-CLAUDE.md):** Beim PR vorschlagen, einen Pre-Release zu triggern — `ttk.Notebook` unter clam rendert auf macOS/Linux mit anderen Font-Metriken; das Tab-Rendering ist auf der Windows-Dev-Maschine nicht vollständig verifizierbar.
