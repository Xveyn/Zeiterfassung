# „Zeiterfassung entfernen" in der App (macOS/Linux) — Design

Issue: Xveyn/Zeiterfassung#50, Punkt 4 der Klärungsliste.
Stand: 2026-10-02. Status: Entwurf, vom Maintainer in Abschnitten freigegeben.

## Ziel

Unter macOS und Linux gibt es keinen Uninstaller. Das Löschen der App lässt
Schlüsselbund-Einträge, Zugangsdaten, Autostart, Menüeintrag und Daten liegen.
Die App bekommt einen Menüpunkt, der das in einem Schritt aufräumt.

Maßstab ist der Windows-Uninstaller (`installer.iss`): Zugangsdaten gehen
immer, Nutzerdaten nur auf ausdrückliche Nachfrage, danach der Hinweis auf den
Widerruf im Google-Konto.

## Entschieden

- **Ansatz A:** Aufräumen in der laufenden App, mit eigenem Beenden-Pfad.
  Verworfen: ein Kindprozess `--remove` (keine Rückmeldung bei Fehlern,
  Prozess-Übergabe auf drei Plattformen unprüfbar) und eine reine CLI ohne
  Button (wird von niemandem gefunden).
- **Die App löscht ihre eigene Programmdatei nicht.** Sie nennt die Datei:
  Linux `$APPIMAGE`, macOS die `.app`. Grund: Pfad und Ort sind
  nutzergewählt, und unter macOS lässt sich ein Löschen nicht prüfen.
- **Nur macOS und Linux, nur im installierten Build** (`sys.frozen`). Windows
  behält den Uninstaller. Aus dem Repo heraus würde der Button Dev-Daten
  löschen.

## Ablauf

1. **Auslösen:** Button „Zeiterfassung entfernen…" im App-Tab, Bereich „Daten".
2. **Rückfrage:** Dialog über `theme.create_dialog`. Er listet, was entfernt
   wird (Zugangsdaten und Schlüsselbund, Autostart, Menüeintrag), und bietet
   das Häkchen „Auch Zeiten, Einstellungen und Protokoll löschen"
   (Standard: **aus**).
3. **Einstellungen-Dialog schließen, ohne zu speichern.** Er fragt beim
   Schließen nach ungespeicherten Änderungen; ein Speichern nach dem Löschen
   legte `settings.json` neu an.
4. **Ruhigstellen (UI-Thread):** Tray, Erinnerungen (`ReminderScheduler`,
   `SendReminderScheduler`) und Tages-Tick (`stop_day_watch`) stoppen,
   Single-Instance-Port freigeben. Den `sync_guard` nehmen und **nie**
   zurückgeben: jeder Sync-Einstieg überspringt dann seinen Lauf
   (Start-Pull, manuell, Tray, Quit-Push, Kompaktierung).
5. **Aufräumen (Worker über `BackgroundTaskRunner.run`):**
   1. `secret_migration.forget_all` — Schlüsselbund, **zuerst**, weil die
      Schlüssel in `token.json`/`webhooks.json`/`smtp.json` stehen.
   2. Autostart ausschalten (`autostart.disable_autostart`).
   3. Linux: Menüeintrag (`desktop_entry.menu_entry_path()`) und `icon.png`
      im Datenordner löschen.
   4. Vorbereitetes Update: liegt `pending_update_path` in den Settings, die
      Datei löschen (ca. 65 MB im Temp-Ordner).
   5. Zugangsdateien löschen: `token.json`, `instance-secret`,
      `webhooks.json`, `smtp.json`, `credentials.json`, liegengebliebene
      `.token-*.tmp`. `token.json` unter `oauth_utils.TOKEN_LOCK`, damit ein
      gleichzeitiger Token-Refresh sie nicht neu schreibt.
   6. Nur mit Häkchen: Nutzerdaten (`zeiterfassung.json`,
      `reservations.json`, `vacations.json`, `settings.json`,
      `conflicts.json`, `sync_history.json`, `sync-apply.journal`,
      `logs/`, `*.corrupt-*`). `settings.json` als **letzte** Datei, weil
      Schritt 4 sie liest.
   7. Datenordner entfernen, **nur wenn er leer ist**. Fremde Dateien bleiben.
6. **Abschluss:** Ergebnisdialog mit ✓/✗ je Schritt, dem Hinweis auf die
   selbst zu löschende Datei und — falls ein `token.json` da war — dem
   Widerrufslink `https://myaccount.google.com/permissions`. Danach beendet
   sich die App über einen eigenen Pfad **ohne** Sync-Push und **ohne**
   Anwenden eines vorbereiteten Updates (`root.destroy()`).

## Bausteine

- **`src/removal.py`** (neu, Tk-frei, vollständig annotiert, in die Whitelist
  von `tests/test_type_annotations.py`):
  - `plan_removal(base_path, with_data, system, environ, settings_get)` →
    Liste `(name, callable)`.
  - `run_removal(steps)` → Liste `StepResult(name, ok, error)`. Führt jeden
    Schritt einzeln in try/except aus, wirft nie, loggt jeden Fehler
    (Catch-all-Regel, Xveyn#73).
  - `app_file_hint(system, environ, executable)` → Pfad der selbst zu
    löschenden Datei oder `None`.
  - Die Dateilisten stehen **einmal** hier. Pfade kommen aus den
    vorhandenen Quellen, nicht aus Kopien.
- **`src/dialogs/removal_dialog.py`** (neu, dünn): Rückfrage und Ergebnisliste.
- **`ui.py::App.remove_application(with_data)`**: Schritte 3, 4 und 6.
- **`tab_app.py`**: der Button, bedingt über `platform.system() != "Windows"`
  und `sys.frozen`.

## Fehlerbehandlung

- Ein gescheiterter Schritt (z. B. Schlüsselbund-Timeout, 30 s pro Eintrag
  über den Watchdog) stoppt die übrigen nicht und steht rot im Ergebnis.
- Die App beendet sich auch bei Fehlern, aber erst nach dem Ergebnisdialog.
- Fehlerdialoge folgen der Konvention aus der Wurzel-CLAUDE.md:
  Ergebnisliste themed, ein unerwarteter Fehler im Worker nativ mit
  Traceback.

## Tests (alle Tk-frei)

- Reihenfolge: Schlüsselbund vor allen Dateischritten, `settings.json` zuletzt.
- Mit und ohne Häkchen.
- Fehlerisolation: ein Schritt wirft, die anderen laufen weiter.
- Fremde Datei im Datenordner bleibt, der Ordner bleibt dann ebenfalls.
- Linux- und macOS-Zweige über injiziertes `system`; Windows plant nichts.
- Die Dateilisten passen zu denen in `installer.iss` (Zugangsdaten) bzw. zu
  `README`/`Datenspeicherung` — als Assertion, nicht als Kopie.
- `pending_update_path` leer / gesetzt / Datei fehlt.

## Grenzen

- **macOS ist nicht prüfbar** (Entwicklung unter Windows, kein Mac für Tests).
  Der macOS-Zweig besteht nur aus den bereits vorhandenen Pfaden und
  `launchctl unload` über `disable_autostart`. Vor dem Release: Pre-Release
  und Test auf Linux; für macOS gilt die Regel „macOS nicht testbar" — der
  Punkt wird dokumentiert, nicht als Pflicht-Gate geführt.
- **Widerruf im Google-Konto** bleibt Handarbeit des Nutzers (wie unter
  Windows). Kein serverseitiger Widerruf — Punkt 3 der Klärungsliste bleibt
  offen.
- **Windows** bekommt den Button nicht. Punkt 1 (Programm/Daten trennen) ist
  davon unabhängig.
- **Fremde Hintergrundschreiber** sind geprüft (Sync über `sync_guard`,
  Tray/Erinnerungen/Tick gestoppt, `device_id` nur beim Start). Ein in
  diesem Moment laufender Daemon-Thread, der nichts davon ist, ist nicht
  ausgeschlossen; er stirbt mit `root.destroy()`.
