# Settings-Dialog: Umbau auf Tabs (UI/UX)

**Datum:** 2026-07-02
**Branch:** `feat/settings-tabs-ui`
**Scope:** Reiner Layout-/UX-Umbau von `src/dialogs/settings_dialog.py`. Keine Änderung an Geschäftslogik, Settings-Keys, Sync- oder OAuth-Verhalten.

## Problem

Der Settings-Dialog stapelt acht Themenblöcke in einer einzigen Spalte:
458 × 1113 px im Default-Zustand, 458 × 1421 px mit aufgeklappten Sections —
höher als ein 1440p-Monitor, auf 1080p-Geräten sind die Speichern-Buttons
unerreichbar. Weitere Befunde:

- Die Breite bleibt ungenutzt, alles wächst in die Höhe; die ▶/▼-Klapp-Sections
  sind ein Workaround für genau dieses Höhenproblem.
- Die Section „Gmail-Zugangsdaten" enthält historisch gewachsen auch
  Standardzeiten, Pause, Empfänger, Name, Stundenlohn und Bundesland.
- Inkonsistente Muster: manche Sections klappbar, andere nicht;
  „Kategorien verwalten" steht als Navigationsknopf zwischen den
  Commit-Buttons Speichern/Abbrechen.

## Lösung

`ttk.Notebook` mit 4 thematischen Tabs, darunter eine feste Button-Zeile.
Fenster fix (nicht resizable), Zielgröße ca. **650 × 550 px** bei 100 %
Skalierung. Modal, Dark-Titlebar, Zentrierung auf Parent, Escape-Bindung:
unverändert wie bisher.

```
┌─ Einstellungen ─────────────────────────────┐
│ [Arbeitszeit] [Bericht & Mail] [Google] [App]│
│ ┌─────────────────────────────────────────┐ │
│ │  (Tab-Inhalt)                           │ │
│ └─────────────────────────────────────────┘ │
│                     [Speichern] [Abbrechen] │
└─────────────────────────────────────────────┘
```

### Tab „Arbeitszeit"

- Standardzeiten Mo–So (Start/Ende-Combos) — dauerhaft sichtbar, kein
  Klapp-Toggle mehr; bei Platzbedarf zweispaltig (Mo–Do | Fr–So).
- Standard-Pause (Min).
- Werkstudenten-Limit: Aktivieren-Checkbox, Zeitraum von/bis, Limit (h/Woche) —
  ohne Klapp-Header.
- Button „Kategorien verwalten" (wandert aus der Commit-Zeile hierher).

### Tab „Bericht & Mail"

- Empfänger, Name, Stundenlohn (€, inkl. „optional"-Hinweis).
- Mail-Vorlage: Betreff, Anrede, Inhalt, Gruß + Platzhalter-Hinweis
  (`{zeitraum}`, `{gesamt}`).

### Tab „Google"

- Datenordner („Ordner öffnen") + credentials.json-Statuslabel (Polling
  wie bisher).
- Absender-Zeile + „Anmelden"/„Aktualisieren"-Button (OAuth im Thread,
  unverändert).
- Drive-Sync: Checkbox, Geräte-ID, letzte Synchronisation,
  „Konflikte ansehen (n)" (falls vorhanden), „Google neu verbinden",
  „Daten importieren", „Sync-Daten kompaktieren" (falls Bedingungen erfüllt).
- Google Kalender: Checkbox + Kalender-Combobox + Statuslabel.
- Kleiner Hinweis, dass die Sync-/Kalender-Schalter **sofort** wirken
  (inkl. OAuth-Browser-Flow) — dieses Verhalten bleibt bewusst unverändert.

### Tab „App"

- Bundesland (Feiertags-Lookup).
- Checkboxen: Wochenende anzeigen, Autostart, Immer im Vordergrund,
  Minimize-to-Tray.
- Darstellung: Skalierungs-Slider + Prozent-Label + Neustart-Hinweis
  (Slider-Styling `Display.Horizontal.TScale` unverändert).

### Entfällt ersatzlos

- Der `_section_header`-Klappmechanismus inkl. `_was_in_grid`-Logik und
  `winfo_manager()`-Workaround.
- Der „Standardzeiten: ▶"-Sub-Toggle (`toggle_times`).
- Die „— Titel — ▼"-Pseudo-Header; innerhalb der Tabs reichen normale
  Zwischenüberschriften, wo überhaupt nötig.
- Der initiale `mv_toggle()`-Aufruf vor dem Zentrieren.

## Technik

- **Notebook-Dark-Styling:** neuer Style-Block in `src/theme.py` analog
  `apply_combobox_style` — `TNotebook` (Hintergrund BG, kein Rahmen) und
  `TNotebook.Tab` (CELL_BG inaktiv, BG/ACCENT-freie Selected-Optik,
  TEXT/TEXT_MUTED, kein Fokus-Punktrahmen via `focuscolor`). Aufruf aus
  `settings_dialog`.
- Jeder Tab ist ein `tk.Frame(bg=BG)` als Notebook-Child mit eigenem,
  lokal nummeriertem Grid; die bisherige globale Row-Nummerierung (0–36)
  entfällt. Der `label(...)`-Helper bekommt den Ziel-Frame als Parameter.
- Alle Variablen, Callbacks und Threads (`save_settings`, `_refresh_sender`,
  `_on_sync_toggled`, `_on_gcal_toggled`, `_load_calendars`,
  `_reconnect_google`, Kompaktierung, `refresh_status`) bleiben funktional
  unverändert — nur die Widget-Parents wechseln.
- `save_settings` bleibt **eine** Funktion über alle Tabs und liest alle Vars
  wie bisher. Bei Validierungsfehlern wird zusätzlich per
  `notebook.select(tab)` auf den Tab mit dem fehlerhaften Feld gewechselt,
  bevor die Fehlermeldung erscheint (Standardzeiten/Werkstudenten-Limit →
  „Arbeitszeit").
- Keine Änderungen an `settings.py`, `sync.py`, `mail.py`, `drive.py`,
  `gcal.py`.

## Nicht-Ziele

- Keine Vereinheitlichung des Sofort-wirkt-vs-Speichern-Verhaltens
  (Sync/GCal-Checkboxen lösen weiterhin sofort den OAuth-Flow aus).
- Keine neuen Settings-Keys, keine Umbenennung bestehender Keys.
- Kein Umbau anderer Dialoge.

## Tests & Verifikation

- Bestehende Tests betreffen nur aus dem Dialog extrahierte pure Logik
  (`code_for_state_label`, `parse_hourly_rate`, `resolve_calendar_id` u. a.)
  und bleiben unberührt; kein Test instanziert den Dialog.
- Kein neuer CI-Test für die Widget-Struktur (Dialog braucht ein Display;
  CI hat keins).
- Lokale Verifikation per Screenshot-Skript (Dialog mit Temp-Settings
  rendern, alle 4 Tabs durchschalten, PNGs prüfen): Gesamthöhe ≤ 700 px
  bei 100 % Skalierung, Buttons sichtbar, alle Widgets pro Tab vorhanden.
- `pytest` + `ruff check .` müssen grün bleiben.
