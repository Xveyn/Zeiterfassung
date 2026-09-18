# Einstellungs-Dialog: Bausteine, Speichern je Tab, Neuschnitt — Design

**Datum:** 2026-09-18
**Status:** Design abgestimmt, Implementierungspläne folgen (einer je PR)
**Branch:** `feat/einstellungen-132` (Spec); Umsetzung in drei PRs
**Issue:** Xveyn/Zeiterfassung#132

## Problem

Der Einstellungs-Dialog (`src/dialogs/settings_dialog/`, ~2480 Zeilen,
`ttk.Notebook` mit sieben Tabs) ist über viele Features gewachsen, ohne dass
sein Aufbau mitgezogen wurde. Screenshots aller Tabs bei 100 % und 150 %
(Scratch-Daten) zeigen:

- **„App" ist überfüllt** (Bundesland, Fensteroptionen, Darstellung und alle
  Benachrichtigungen) und bestimmt die Dialoghöhe: **756 px bei 100 %,
  993 px bei 150 %**. Auf einem 1080p-Bildschirm mit Taskleiste ist das bei
  150 % knapp, ab 175 % läuft der Dialog aus dem Bild. Die übrigen Tabs haben
  dadurch viel Leerraum.
- **Zentrierte Überschriften** („— Werkstudenten-Limit —", `_shared.subheader`)
  über linksbündigem Inhalt, keine gemeinsame linke Kante.
- **Unruhige Kanten:** Beschriftungen haben keine gemeinsame Spalte, die Felder
  im Mail-Tab beginnen an zwei verschiedenen Stellen.
- **Abhängige Optionen** (Werkstudenten-Zeitraum, Erinnerungsminuten) sind auch
  dann bedienbar, wenn ihr Schalter aus ist.
- **SMTP/Webhooks** zeigen ohne Einträge eine leere blaue Fläche.
- **Updates:** der Changelog ist durch die Optionen vom Status getrennt.
- **Gemischtes Speichermodell:** die meisten Felder gelten erst mit
  „Speichern" (das den Dialog schließt, alle Tabs auf einmal), SMTP/Webhooks
  und die Google-Schalter sofort. „Abbrechen" verwirft nur einen Teil.

## Ziel

1. Ein einheitlicher, ruhiger Formular-Aufbau über alle Tabs — **im
   bestehenden Theme** (Farben und Schriften bleiben; nur Struktur: Überschriften,
   Spalten, Abstände, Hinweise, Ausgrauen).
2. **Gespeichert wird nur, was der Nutzer selbst speichert** — je Tab, mit
   Rückfrage beim Verlassen eines geänderten Tabs.
3. Sechs statt sieben Tabs, inhaltlich geschnitten:
   Arbeitszeit · Erinnerungen · Versand · Google · App · Updates.
4. Der Dialog passt bei jeder Skalierung auf den Bildschirm.

## Nicht-Ziele

- Kein neues visuelles Vokabular (keine Karten, keine neue Akzentfarbe,
  keine Seitenleisten-Navigation). Kann später auf die Bausteine aufsetzen.
- Kein „Alles sofort übernehmen" (Instant-Apply) — bewusst entschieden
  dagegen, der Nutzer speichert selbst.
- `import_dialog`/`vacation_dialog` behalten ihre handgebauten
  Scroll-Container; eine Umstellung auf den neuen Baustein ist ein möglicher
  Folge-PR, nicht Teil dieser Arbeit.
- Keine automatisierten UI-Tests (entschiedene Scope-Grenze, s. CLAUDE.md
  „Getestet wird Logik, nicht UI"). Tk-Aufbau wird per Screenshot belegt.

## Umsetzung in drei PRs

Nach jedem PR ist die App vollständig nutzbar. Reihenfolge Fundament →
Speichern → Neuschnitt, damit jeder Tab beim Neuschnitt nur einmal
angefasst wird.

### PR 1 — Bausteine (keine sichtbare Änderung)

**Ort.**
- `src/theme/form.py` (neu): Tk-Bausteine, eigene Schicht über `widgets`
  (Reihenfolge: `palette` → `fonts` → `widgets` → `form`). Re-Export über
  `src/theme/__init__.py`; importiert wird weiter `from src.theme import …`.
- `src/dialogs/settings_dialog/form_model.py` (neu): Tk-freie Logik, vollständig
  annotiert und in die Whitelist von `tests/test_type_annotations.py`
  eingetragen.
- `src/theme/palette.py`: zwei neue Konstanten — `SEPARATOR` (gedämpfte
  Trennlinie, dunkler als `TEXT_MUTED`) und `TEXT_DISABLED` (ausgegraute
  Beschriftungen/Felder).

**`Form`** — ein Tab ist genau ein Raster mit zwei Spalten: Spalte 0
Beschriftung, Spalte 1 Bedienelement. Weil alle Abschnitte eines Tabs im selben
Raster liegen, fluchten die Beschriftungen tabweit; die Spaltenbreite ergibt
sich aus der längsten Beschriftung (keine festen Pixel, skaliert mit
`ui_scale`). `Form` zählt Zeilen selbst — kein `row=7` mehr von Hand.

| Methode | Wirkung |
|---|---|
| `form.section(title, hint=None)` | Überschrift links, `FONT_BOLD`/`TEXT`, dahinter eine 1-px-Linie in `SEPARATOR` bis zum rechten Rand; optional Hinweis darunter. Ersetzt `_shared.subheader`. |
| `form.row(label, widget)` | Beschriftung in Spalte 0, Widget in Spalte 1, `sticky="w"`. |
| `form.check(text, var)` | Checkbox über beide Spalten. |
| `form.hint(text)` | `FONT_SMALL`/`TEXT_MUTED`, über beide Spalten; `wraplength` folgt per `<Configure>` der Formularbreite (auch bei 150 %). |
| `form.buttons(*specs)` | linksbündige Knopfreihe über beide Spalten. |
| `form.depends_on(var)` | Kontextmanager: Zeilen darin werden eingerückt und sind nur aktiv, solange `var` wahr ist. Verschachtelbar. |
| `empty_state(parent, text)` | gedämpfter Leertext für leere Listen. |

Beispiel verschachtelt: Sende-Erinnerung → (Tag, Uhrzeit, Verschiebung →
(auch Feiertage)).

**Ausgrauen.** `set_enabled(widget, on)` in `theme/form.py` kennt jede
benutzte Widget-Art (`tk.Entry`, `ttk.Combobox`, `tk.Checkbutton`,
`tk.Text`, `tk.Label`, die Label-Buttons aus `widgets`) und setzt Zustand
**und** Farben (`TEXT_DISABLED`, `disabledbackground`/`disabledforeground`,
ttk-State `disabled` mit passender `style.map`). Ein ausgegrautes Feld
behält seinen Wert.

**Scroll-Container.** `Form(parent, scroll=True)` legt das Raster in einen
Canvas mit `ttk.Scrollbar(style="Vertical.TScrollbar")` — der Stil existiert
bereits (dunkel, `apply_combobox_style` in `theme/widgets.py`). Die Leiste
erscheint nur, wenn der Inhalt höher ist als der Container. Mausrad:
- gebunden, solange der Zeiger über dem Container ist (`<Enter>`/`<Leave>`),
  Windows/macOS `<MouseWheel>`, Linux `<Button-4>`/`<Button-5>`;
- liegt der Zeiger über einem Widget, das selbst scrollt (`tk.Text`,
  `tk.Listbox`), scrollt nur dieses;
- über einer `ttk.Combobox` scrollt das Formular, und die Combobox ändert
  ihren Wert **nicht** (Widget-Binding mit `"break"` vor dem
  Klassen-Binding) — sonst verstellte man beim Scrollen versehentlich Werte.

**Tk-frei in `form_model.py` (getestet):**
- `enabled_states(parents: dict[str, str | None], values: dict[str, bool]) -> dict[str, bool]`
  — aktiv genau dann, wenn alle Vorfahren wahr sind.
- `is_dirty(baseline: dict, current: dict) -> bool` — normalisiert Typen
  (`"20"`, `20`, `20.0` gleich; `"08:00"` bleibt String), damit ein
  unveränderter Wert nicht als Änderung zählt.
- `wheel_units(system: str, delta: int, num: int | None) -> int` —
  Scrollschritte aus dem Event (Windows `delta/120`, macOS `delta`,
  Linux `num` 4/5).
- `body_height(natural: int, scale: float, screen_height: int) -> int` —
  Höhe des Tab-Körpers: `min(natural, BODY_MAX_HEIGHT * scale,
  screen_height - SCREEN_MARGIN * scale)`, mit `BODY_MAX_HEIGHT = 600` und
  `SCREEN_MARGIN = 160` (Basis 100 %). 600 entspricht in etwa dem heutigen
  Tab-Körper des App-Tabs; der Dialog wird also nie höher als heute.

**Themed Rückfrage.** `themed_ask_save_changes(parent, tab_title) ->
Literal["save", "discard", "cancel"]` in `theme/messagebox.py`, Knöpfe
„Speichern" (primary) · „Verwerfen" · „Zurück"; Escape/X = `"cancel"`.
Gebaut über `create_dialog` + `center_dialog_on_parent` (Paarungsregel).

### PR 2 — Speichern je Tab (Tabs bleiben die heutigen sieben)

**Tab-Schnittstelle.** Jede Tab-Klasse bekommt:

| Methode | Aufgabe |
|---|---|
| `title: str` | Name für die Rückfrage. |
| `values() -> dict` | aktueller Formularstand in Settings-Form (Schlüssel/Typen wie `settings.json`). |
| `validate() -> tuple[str, str] \| None` | `(Titel, Meldung)` oder `None`; die heutigen Prüfungen aus `save_settings`, je im zuständigen Tab. |
| `save() -> SaveOutcome` | schreibt über `settings.apply_updates`, inklusive Nebeneffekten des Tabs; `SaveOutcome.restart` = Neustart nötig. |
| `reset()` | Felder auf den zuletzt gespeicherten Stand. |

Aufteilung des heutigen `save_settings`:
- **Arbeitszeit:** Standardzeiten (`validate_entry`), Pause, Pausenwarnung,
  Stundenlohn, Werkstudenten-Limit (`validate_period`), `workweek_only`;
  danach `period_scan_needed`/`scan_period_for_warnings` → Warnung.
- **Bericht & Mail:** Empfänger, Name, Vorlage.
- **Google:** `device_name` (über `sanitize_device_name`), Kalender-ID
  (`resolve_calendar_id`, nur wenn `cal_map` geladen).
- **App:** Autostart **vor** dem Schreiben umschalten (scheitert es, wird
  nichts gespeichert — wie heute), Bundesland, Fensteroptionen,
  Benachrichtigungen (`parse_reminder_minutes`), Skalierung → `restart`.
- **Updates:** Häufigkeit, Pre-Releases, `auto_update_enabled` (nur wenn der
  Schalter gebaut wurde).
- **Webhooks/SMTP:** `values()` ist `{}`, nie geändert; ihre Unterdialoge
  speichern selbst (eigener Klick, eigenes Speichern).

**`SaveCoordinator`** (Tk-frei, in `form_model.py`, getestet mit Fake-Tabs):
- hält je Tab eine Baseline (`values()` beim Öffnen bzw. nach dem letzten
  Speichern), `dirty(tab)` über `is_dirty`;
- `request_switch(target) -> bool`, `request_close() -> bool`,
  `save_current() -> bool` mit injiziertem `ask(title) -> "save"|"discard"|"cancel"`
  und `show_error(title, msg)`:
  - nicht geändert → sofort erlaubt;
  - `"save"` → `validate()`; Fehler → `show_error`, bleibt im Tab (`False`);
    sonst `save()`, Baseline neu, erlaubt;
  - `"discard"` → `reset()`, erlaubt;
  - `"cancel"` → nicht erlaubt;
- nach jedem erfolgreichen `save()` einmal `on_change()`;
- `rebaseline(tab)` für Werte, die im Hintergrund nachgeladen werden
  (Kalenderliste im Google-Tab), damit ein Tab nicht beim Öffnen schon
  „geändert" ist.

**Tk-Anbindung in `dialog.py`:**
- Formular-Variablen melden Änderungen per `trace_add("write")`, die
  Mail-Textfelder per `<<Modified>>`; beides schaltet „Speichern" über
  `set_primary_button_enabled` aktiv/grau (je aktivem Tab).
- **Tab-Wechsel:** `<Button-1>` auf der Reiterleiste
  (`notebook.identify`/`index("@x,y")`) wird vor dem Wechsel abgefangen;
  `request_switch` → bei `False` `"break"`. Tastatur-Traversal
  (`enable_traversal`) ist heute nicht aktiv und bleibt aus.
- **Schließen:** Knopf „Schließen", `WM_DELETE_WINDOW` und Escape laufen über
  `request_close`.
- Knöpfe unten: **„Speichern" · „Schließen"**. Der Dialog bleibt nach dem
  Speichern offen; „Speichern" wird wieder grau.
- **Skalierung:** Speichern einer geänderten Skalierung startet die App wie
  heute sofort neu (`on_request_restart`); der Dialog geht dabei mit.
- Validierungsfehler springen nicht mehr in fremde Tabs (gespeichert wird
  nur der aktive).

**Was sofort gilt, bleibt sofort** — es sind Aktionen mit eigenem Klick, keine
Formularfelder: Anlegen/Bearbeiten/Entfernen von SMTP-Konten und Webhooks
(Unterdialog bzw. Rückfrage), Kategorien und Urlaub (eigene Dialoge), die
Google-Schalter für Sync und Kalender (starten den Consent; Hinweis „Diese
Schalter wirken sofort (Anmeldung im Browser)." bleibt).

### PR 3 — Neuschnitt auf sechs Tabs

Alle Tabs werden mit `Form(scroll=True)` gebaut.

| Tab (`initial_tab`-Schlüssel) | Abschnitte |
|---|---|
| **Arbeitszeit** (`work`) | **Arbeitswoche:** Nur Werktage · Wochenende anzeigen (aus App; grau, solange „Nur Werktage" an) · Bundesland (aus App, Hinweis „für Feiertage und Urlaub") — **Standardzeiten:** Mo–So Start/Ende · Standard-Pause · Pausenpflicht-Warnung — **Vergütung:** Stundenlohn + Hinweis — **Werkstudenten-Limit:** Schalter; Zeitraum und Limit abhängig — **Verwalten:** Kategorien… · Urlaub… |
| **Erinnerungen** (`reminders`) | **Reservierungen:** Toast-Erinnerung; Minuten vor Ende abhängig + Hinweis — **Monatliche Sende-Erinnerung:** Schalter; Tag/Uhrzeit, Wochenend-Verschiebung → auch Feiertage (verschachtelt) — **An Reservierungstagen:** Schalter; Standard-Minuten |
| **Versand** (`sending`) | **Absender:** Dein Name · Empfänger — **Mail-Vorlage:** Betreff · Anrede · Inhalt · Gruß · Platzhalter-Hinweis — **Zeitraum:** ab letzter Erinnerung vorbelegen; inkl. Monatstermine abhängig — **SMTP-Konten** und **Webhooks:** je kompakte Liste (3 Zeilen, Knöpfe rechts daneben, `empty_state` wenn leer) |
| **Google** (`google`) | **Konto:** credentials.json-Status · Absender · Berechtigungen · Anmeldung · Google neu verbinden — **Synchronisation:** Schalter · Gerät · Geräte-ID · Letzte Synchronisation · Konflikte — **Kalender:** Schalter · Kalender — **Erweitert:** Sync-Daten kompaktieren |
| **App** (`app`) | **Fenster:** Autostart · Immer im Vordergrund · In den Infobereich minimieren — **Darstellung:** Skalierung + Neustart-Hinweis — **Daten:** Datenordner öffnen · Daten importieren (aus Google) |
| **Updates** (`updates`) | Version, Status, „Jetzt prüfen"/„Installieren", direkt darunter der Changelog — **Optionen:** Häufigkeit · Pre-Releases · Automatisch installieren |

Die Tab-Schnittstelle aus PR 2 wandert mit: Felder, die den Tab wechseln,
ziehen ihren Anteil an `values()`/`validate()`/`save()` mit.
`SMTP`/`Webhooks` werden Abschnitte im Versand-Tab; `RecordListTab` wird dafür
zu einer einbettbaren Liste (Kompaktform, `empty_state`), die
`RecordListKind`-Aufteilung bleibt.

**Restbefunde, die dabei erledigt werden:**
- „Nur Werktage" blendet die Sa/So-Zeilen der Standardzeiten **sofort** aus
  (die `StringVar`s bleiben, s. `workweek.py`-Absatz in `src/CLAUDE.md`).
- Werkstudenten-Felder und alle übrigen abhängigen Optionen grau, solange ihr
  Schalter aus ist.
- Leere Listen zeigen den Leertext.
- `initial_tab` kennt die sechs Schlüssel oben; `"updates"` (Banner) bleibt.

## Tests

- **PR 1:** `tests/test_form_model.py` — `enabled_states` (verschachtelt,
  fehlender Vorfahr), `is_dirty` (Typ-Normalisierung, Text mit Zeilenenden),
  `wheel_units` (alle drei Plattformen), `body_height` (alle drei Grenzen).
  `test_dialog_reveal.py` deckt `themed_ask_save_changes` automatisch ab.
- **PR 2:** `SaveCoordinator` mit Fake-Tabs: Wechsel/Schließen je Antwort,
  Validierungsfehler hält fest, `on_change` genau einmal je Speichern,
  `rebaseline`, Tabs ohne Werte nie geändert. Je Tab: `values()` →
  `save()` → Settings-Inhalt wie der heutige `save_settings` (Tk-Variablen
  lassen sich ohne Fenster nicht bauen; geprüft wird daher über die
  Tk-freien Parse-/Validierungs-Helfer, die die Tabs nutzen).
- **PR 3:** keine neue Logik außer der Tab-Zuordnung; Beleg per
  Vorher/Nachher-Screenshots aller Tabs bei 100 % und 150 % (Harness mit
  `ZEITERFASSUNG_DATA_DIR` auf Scratch-Daten, keine Nutzerdaten).
- Durchgehend: `pytest`, `ruff check .`, `pyright` grün.

## Doku

- `src/CLAUDE.md`, Abschnitt „Dialoge": „zentrales, ablaufidentisches
  `save_settings`" → Tab-Schnittstelle + `SaveCoordinator` (PR 2); Tab-Liste,
  Versand-Tab mit eingebetteten Listen, der Satz über den Google-Tab als
  größten im Notebook (PR 3).
- `src/CLAUDE.md`, Abschnitt „Berichte & Plattform/Infra" → `theme/`: neue
  Schicht `form` (PR 1).
- Root-`CLAUDE.md`, „Dialog-Styling": Verweis auf `theme/form.py` als Weg für
  Formular-Layouts (PR 1).
- `CHANGELOG.md` mit dem Release, der PR 3 enthält.

## Risiken

- **Abfangen des Tab-Klicks:** `ttk.Notebook` hat kein Veto für
  Tab-Wechsel. Der `<Button-1>`-Weg deckt die Maus ab; programmatische
  `select`-Aufrufe (`initial_tab`) laufen vor dem ersten Edit und sind
  unkritisch.
- **Plattformen:** Mausrad-Events und ttk-Disabled-Styles unterscheiden sich
  unter Linux/macOS. Vor dem Merge von PR 1 bzw. PR 3 einen Pre-Release auf
  Linux testen; macOS bleibt ungetestet (bewusst offen).
- **Dirty-Fehlalarme** durch programmatische Variablen-Schreibzugriffe
  (Kalenderliste, Updates-Status) → `rebaseline`; Status-Labels sind keine
  Formularwerte und gehen nicht in `values()` ein.
