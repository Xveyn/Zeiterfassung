# Updates-Tab + Toast/Banner-Routing (Design)

**Datum:** 2026-07-15
**Branch:** TBD (Feature-Branch beim Implementierungsstart)
**Scope:** Neuer 5. Settings-Tab „Updates" (nach „App"), der den Update-Status
anzeigt, den Changelog-Eintrag der neuen Version lädt und die Check-Häufigkeit
konfigurierbar macht. Das bestehende Update-Banner über dem Kalender wird nur
noch gezeigt, wenn kein aktiver Toast-Kanal (Tray) zur Verfügung steht — sonst
übernimmt ein einmaliger Toast dieselbe Rolle.

## Ausgangslage (Status quo)

- `src/updater.py` (stdlib-only, Tk-frei): `check_latest_release(repo)` fragt
  einmalig die GitHub-API nach dem neuesten Release (`Release(version,
  html_url, assets)`), fehlertolerant (`None` bei jedem Fehler). `is_newer`,
  `should_check_today(last_check, today=None)` (Drosselung auf 1×/Kalendertag,
  hart codiert), `pick_asset_url` wählt das Plattform-Asset.
- `src/background_tasks.py::check_update(on_result)`: läuft im Worker-Thread,
  ruft `check_latest_release("MargenHeld/Zeiterfassung")` (Repo-String hier
  hart codiert), wertet `is_newer` aus, liefert `(release, newer)` an
  `on_result` auf dem UI-Thread. Gedrosselt über `should_check_today`.
- `src/update_banner.py::UpdateBanner.handle_check_result(release, newer)`:
  persistiert `last_update_check_at`, zeigt bei `newer` und noch nicht via
  `dismissed_version` ausgeblendeter Version einen dismissbaren Banner über
  dem Kalender (`_show`/`_open_download`/`_dismiss`).
- `ui.py::App.__init__` verdrahtet:
  `self._bg.check_update(on_result=self._update_banner.handle_check_result)`.
- Settings (gerätelokal, nicht synced): `last_update_check_at` (ISO-Datum),
  `dismissed_version` (String).
- Settings-Dialog (`src/dialogs/settings_dialog/dialog.py`): 4 Tabs
  (Arbeitszeit/Bericht & Mail/Google/App), je ein Tab eine Klasse in
  `tab_*.py`, die ihre Tk-Variablen als Attribute für `save_settings`
  exponiert. `GoogleTab` zeigt das etablierte Muster für async Arbeit im
  Dialog: `runner.run(fn, on_done)` (injizierter `BackgroundTaskRunner`,
  Audit H5) statt eigener Threads; manche `on_done`-Callbacks persistieren
  direkt (`settings.set(...)`), unabhängig vom Save-Button (z.B.
  `fetch_sender_email`).
- `src/tray.py::TrayIcon.notify(message, title="Zeiterfassung")` ist der
  bestehende Toast-Kanal; `is_supported()` gated die Plattform (Windows voll,
  macOS hinter `ZEIT_MACOS_TRAY=1` dormant, Linux kein Tray). Ein Tray läuft
  aktuell nur, wenn `minimize_to_tray`/`reminders_enabled`/
  `send_reminder_enabled` aktiv ist — `App._tray` ist sonst `None`.
- `CHANGELOG.md`: kuratiertes Markdown, ein `## X.Y.Z — Datum`-Heading pro
  Release, darunter `### Hinzugefügt/Geändert/Behoben/Intern`-Unterabschnitte.
  Wird im Repo gepflegt und ist im gebauten Artefakt auf dem Stand der
  **installierten** Version eingefroren — enthält den Eintrag einer neueren,
  noch nicht heruntergeladenen Version nicht.

## Getroffene Entscheidungen (aus dem Brainstorming)

1. **Changelog-Quelle:** `CHANGELOG.md` wird zur Laufzeit vom GitHub-Tag
   `v{version}` per HTTP geladen (`raw.githubusercontent.com`, stdlib
   `urllib`, kein Base64-Decoding wie bei der Contents-API nötig) und lokal
   auf den Abschnitt der Zielversion geparst.
2. **Banner-vs-Toast-Gate:** entscheidet sich an `App._tray is not None` zum
   Zeitpunkt des Check-Ergebnisses — nicht an reiner Plattform-Fähigkeit
   (`tray.is_supported()`). Läuft gerade ein Tray (aus welchem Grund auch
   immer), übernimmt ein Toast; sonst der bestehende Banner.
3. **Toast einmalig pro Version:** neues Settings-Feld
   `update_toast_shown_version` verhindert, dass der tägliche Hintergrund-Check
   denselben Toast wiederholt feuert.
4. **Updates-Tab-Datenquelle:** Live-Check, sobald der Tab erstmals
   ausgewählt wird (`<<NotebookTabChanged>>`) — **nicht** beim bloßen Öffnen
   des Settings-Dialogs, da alle Tabs dort eager gebaut werden und ein
   Eager-Check sonst bei jedem Dialog-Öffnen still die „gesehen"-Markierung
   setzen würde, ohne dass der Nutzer den Tab je gesehen hat (Präzisierung
   nach kritischem Plan-Review) — umgeht die Tagesdrosselung (explizite
   Nutzeraktion) + manueller „Jetzt prüfen"-Button mit Re-Entry-Guard für
   erneute Checks. Kein separates Zwischenspeichern eines Release-Snapshots
   in Settings nötig.
5. **Konfigurierbare Check-Häufigkeit:** neues Settings-Feld
   `update_check_frequency` (`"daily"`/`"weekly"`/`"monthly"`/`"never"`,
   Default `"daily"` = heutiges Verhalten unverändert) steuert ausschließlich
   den **Hintergrund**-Check (Banner/Toast-Trigger). Der Live-Check im
   Updates-Tab ist davon unabhängig und läuft immer, wenn der Tab geöffnet
   oder „Jetzt prüfen" geklickt wird.
6. **„Gesehen" = keine erneute Nachricht:** Findet der Live-Check im
   Updates-Tab eine neuere Version, wird das sofort als `dismissed_version`
   **und** `update_toast_shown_version` vermerkt (direkter Settings-Write
   beim Check-Ergebnis, nicht an den Save-Button gekoppelt — Präzedenzfall
   `fetch_sender_email`) — kein doppeltes Nerven durch Banner/Toast für eine
   Version, die der Nutzer im Tab bereits gesehen hat.
7. **Refactor `UpdateBanner`:** `handle_check_result` (persistiert
   `last_update_check_at` **und** entscheidet über Anzeige) wird aufgeteilt.
   Die Persistenz wandert in die neue Routing-Stelle in `ui.py` (läuft
   unabhängig davon, ob am Ende Banner oder Toast gezeigt wird); `UpdateBanner`
   behält nur noch die reine Anzeige-Entscheidung als `show_if_newer(release)`
   (prüft `dismissed_version`, ruft `_show`).

## Komponenten

### Neue Settings (gerätelokal, NICHT synced)
In `settings.py::DEFAULTS`:
- `update_check_frequency`: `str`, Default `"daily"`
- `update_toast_shown_version`: `str`, Default `""`

### `src/changelog.py` (neu, stdlib-only, Tk-frei)
Analog zu `updater.py` im Zuschnitt (reine Netzwerk-/Parse-Helfer, kein Tk):
```
def extract_version_section(changelog_text: str, version: str) -> str | None
# Findet "## {version}" (führendes "v" bereits gestrippt wie bei Release.version),
# liefert den Text ab dieser Zeile bis zur nächsten "## "-Zeile oder Dateiende.
# None, wenn die Version im Text nicht vorkommt.

def fetch_changelog_entry(repo: str, version: str, timeout: float = 5.0) -> str | None
# Lädt https://raw.githubusercontent.com/{repo}/v{version}/CHANGELOG.md,
# reicht den Text an extract_version_section weiter. None bei jedem Fehler
# (Netzwerk, HTTP-Fehler, Decode-Fehler, Version nicht gefunden) — wie
# check_latest_release nie eine Exception nach außen.
```
`extract_version_section` ist pur und ohne Netzwerk testbar (Fixture-Strings).

### `src/updater.py` (Erweiterung)
- `should_check_today(last_check, today=None)` wird zu
  `should_check(last_check, frequency, today=None)` verallgemeinert:
  `frequency == "never"` → immer `False`; sonst Intervall in Tagen
  (`daily`→1, `weekly`→7, `monthly`→30) statt der bisher hart codierten 1.
  Einziger bestehender Call-Site (`background_tasks.py::check_update`) wird
  entsprechend angepasst.
- Neue Konstante `REPO = "MargenHeld/Zeiterfassung"` (bisher in
  `background_tasks.py` hart codiert) — von `background_tasks.py` **und** dem
  neuen `tab_updates.py` importiert, keine zweite Quelle für den Repo-String.
- Neuer reiner Text-Helfer `update_toast_text(release) -> str`, z.B.
  `f"Version {release.version} verfügbar — Details unter Einstellungen → Updates."`

### `background_tasks.py::check_update` (Anpassung)
Liest `update_check_frequency` aus Settings, reicht es an `should_check`
weiter; sonst unverändert.

### `UpdateBanner` (Refactor)
- `handle_check_result(release, newer)` → `show_if_newer(release)`: kein
  `newer`-Parameter mehr (Aufrufer hat das schon geprüft, bevor er in den
  Banner-Zweig routet), keine `last_update_check_at`-Persistenz mehr (wandert
  zum Aufrufer). Prüft weiterhin `dismissed_version`, ruft `_show`.
- `_show`/`_open_download`/`_dismiss` unverändert.

### Toast/Banner-Routing (`ui.py::App`, neue private Methode)
Ersetzt die direkte Verdrahtung
`self._bg.check_update(on_result=self._update_banner.handle_check_result)`:
```
self._bg.check_update(on_result=self._on_update_check_result)

def _on_update_check_result(self, release, newer):
    self.settings.set("last_update_check_at", today_iso())
    if not newer:
        return
    if self._tray is not None:
        if release.version != self.settings.get("update_toast_shown_version"):
            self._tray.notify(update_toast_text(release))
            self.settings.set("update_toast_shown_version", release.version)
    else:
        self._update_banner.show_if_newer(release)
```
Reine Koordination (App-Zuständigkeit laut `src/CLAUDE.md`), kein neues
Komponenten-File nötig — `UpdateBanner` bleibt bewusst nur für die
Banner-Anzeige zuständig.

### Settings-Dialog: neuer Tab „Updates" (`tab_updates.py`, analog `tab_*.py`)
- Konstruktor `UpdatesTab(frame, settings, runner)` — braucht (anders als die
  anderen Tabs außer Google) den `runner` für async Arbeit.
- Baut beim Öffnen sofort die UI (Status-Zeile „Prüfe…", „Jetzt
  prüfen"-Button deaktiviert während des Laufs — Konvention aus
  Send-/Share-/Export-Dialogen) und stößt direkt einen Live-Check an:
  `runner.run(lambda: check_latest_release(REPO), on_done)`.
- `on_done(release_or_none)`:
  - `None` (Netzwerkfehler) → Statuszeile „Prüfung fehlgeschlagen", Button
    wieder aktiv.
  - Release, aber `not is_newer(VERSION, release.version)` → „Du hast die
    aktuelle Version (X.Y.Z)."
  - Release **und** neuer → Versionszeile + Download-Button (wie im Banner:
    `pick_asset_url` mit Fallback `html_url`, `webbrowser.open`), sofort
    `settings.set("dismissed_version", release.version)` +
    `settings.set("update_toast_shown_version", release.version)` (Entscheidung 6),
    **und** ein zweiter `runner.run`-Aufruf lädt
    `fetch_changelog_entry(REPO, release.version)`, dessen Ergebnis in einem
    `dark_text`-Widget (read-only) darunter erscheint — `None` → „Changelog
    konnte nicht geladen werden."
- „Jetzt prüfen"-Button triggert denselben Ablauf erneut.
- Dropdown „Automatisch prüfen:" (`dark_combo`, readonly) mit deutschen
  Labels (Täglich/Wöchentlich/Monatlich/Nie) → internes Value-Mapping auf
  `daily`/`weekly`/`monthly`/`never`; exponiert als `.frequency_var` für
  `save_settings` (liest den internen Value über eine kleine
  Label→Value-Zuordnung, analog `code_for_state_label`).
- `save_settings` in `dialog.py` ergänzt `"update_check_frequency": ...` im
  `updates`-Dict; Notebook-Registrierung um `notebook.add(tab_updates, text="Updates")`
  nach dem App-Tab.

## Fehler-/Edge-Handling
- `fetch_changelog_entry` liefert `None` bei jedem Fehler (Netzwerk, 404 —
  z.B. Tag existiert aus irgendeinem Grund nicht —, Decode-Fehler, Version
  nicht im Text gefunden) — der Tab zeigt dann nur die reine Versionsinfo
  ohne Changelog, kein Crash.
- Toast und Banner sind laut Entscheidung 2 **gegenseitig exklusiv** pro
  Check-Ergebnis (nie beide für denselben Fund) — wechselt der Nutzer
  zwischen Sessions den Tray-Zustand (z.B. Minimize-to-Tray aus-/angeschaltet),
  kann theoretisch für dieselbe Version einmal Toast und ein andermal Banner
  erscheinen, wenn zwischenzeitlich keiner der beiden „gesehen"-Marker
  gesetzt wurde. Akzeptiert (kein Datenintegritätsproblem, seltener Fall).
- `should_check(..., "never")` deaktiviert nur den **Hintergrund**-Check;
  „Jetzt prüfen" im Tab funktioniert davon unabhängig immer.
- Tab-Live-Check schlägt fehl (offline) → Statuszeile zeigt Fehler, kein
  Banner/Toast-Nebenwirkung (der Tab routet nicht über
  `_on_update_check_result`, sondern zeigt sein Ergebnis nur lokal).

## Tests
- `tests/test_updater.py`: `should_check` ersetzt `TestShouldCheckToday` —
  alle vier Frequenzen (`daily`/`weekly`/`monthly`/`never`) je mit
  gestern/heute/vor-Intervall/ungültigem `last_check`; `update_toast_text`
  (reiner String-Test).
- `tests/test_changelog.py` (neu): `extract_version_section` mit
  Fixture-Markdown (Version mittendrin, Version als letzter Eintrag ohne
  folgendes `## `, Version nicht vorhanden, leerer Text);
  `fetch_changelog_entry` mit gemocktem `urlopen` (Happy Path, 404,
  Netzwerkfehler, kaputtes UTF-8) — Muster wie `TestCheckLatestRelease`.
- `tests/test_update_banner.py`: bestehende Tests auf `show_if_newer`
  umgestellt (kein `newer`-Arg mehr, keine `last_update_check_at`-Assertion
  mehr dort).
- `tests/test_ui_*` oder neue Datei: `_on_update_check_result`-Routing pur
  testbar mit Fake-Tray/Fake-Settings/Fake-UpdateBanner (Tray vorhanden →
  `notify` aufgerufen + `update_toast_shown_version` gesetzt, kein zweiter
  Toast für dieselbe Version; kein Tray → `show_if_newer` aufgerufen).
- `tab_updates.py`/Dialog-Verdrahtung: Tk-abhängig, kein automatisierter Test
  (Projekt-Konvention) — manuelle Verifikation: Live-Check gegen eine echte,
  bereits existierende ältere Tag-Version (z.B. `v1.17.0`) bestätigt den
  echten Fetch+Parse-Pfad; „neuere Version verfügbar" lokal per temporärem
  Mock/Override simulieren (kein echtes neues Release nötig, um die
  Tab-Darstellung zu sehen).
- `pytest` + `ruff check .` bleiben grün.

## Nicht-Ziele
- Kein automatischer In-App-Download/Update — weiterhin nur Browser-Link
  (bestehende Design-Grenze M9, unverändert).
- Keine Persistenz eines Release-Snapshots über Neustarts hinweg für den Tab
  (Entscheidung 4) — der Tab prüft bei jedem Öffnen live.
- Kein Ausbau der Plattform-Unterstützung (Linux weiterhin ohne Tray, macOS
  weiterhin hinter Opt-in) — das Banner bleibt der Fallback-Kanal dort.
- Keine rückwirkende Anzeige mehrerer verpasster Versionen/Changelogs — nur
  die aktuell neueste Version wird geprüft und angezeigt (wie bisher).

## Plattform-Hinweis (Pre-Release)
Toast-vs-Banner-Routing ist auf der Windows-Dev-Maschine nicht für
macOS/Linux verifizierbar (Toast nur wo Tray läuft; Banner-Fallback dort, wo
nicht). Gemäß Root-`CLAUDE.md` vor dem nächsten echten Release einen
Pre-Release vorschlagen.
