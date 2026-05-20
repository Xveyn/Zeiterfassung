# Google-Kalender-Reservierungen — Design

**Datum:** 2026-05-20
**Status:** Entwurf — Abschnitte 1–4 vom Auftraggeber freigegeben
**Kontext:** baut auf dem Branch `feat/multi-device-sync` auf

## 1. Ziel

Die Zeiterfassung soll *zukünftige Arbeitszeiten als „Reservierungen"* verwalten
und diese in einen Google Kalender schreiben, sodass der Zeitslot dort blockiert
ist. Eine Reservierung ist ein eigenständiges Konzept **neben** den erfassten
Ist-Zeiten — die beiden haben nichts miteinander zu tun.

Der Google Kalender ist dabei zugleich der **geräteübergreifende Speicher** der
Reservierungen: Reservierungen laufen *nicht* über die bestehende
Drive-Multi-Device-Sync.

## 2. Festgelegte Anforderungen

| Thema | Entscheidung |
|-------|--------------|
| Richtung | App → Google Kalender (Einweg-Push) |
| Modell | Reservierung = eigenständiges Konzept, unabhängig von Ist-Zeiten |
| Push-Zeitpunkt | Automatisch beim Speichern, im Hintergrund |
| Lebenszyklus | Reservierung und Ist-Zeit bleiben getrennt, keine Umwandlung |
| Ziel-Kalender | Vom User in den Einstellungen wählbar |
| Geräteübergreifend | Der Kalender selbst ist der gemeinsame Speicher (pull → merge → push). Kein Konflikt-Dialog. |
| Kalender-Auswahl | `gcal_calendar_id` wird über die Drive-Settings-Sync mitgenommen, damit alle Geräte denselben Kalender treffen |
| UI-Zugang | Erweiterter Tages-Dialog mit zwei Bereichen (Ist-Zeit + Reservierung) |

## 3. Nicht-Ziele (YAGNI)

- Keine Übernahme manuell im Google Kalender angelegter/geänderter Termine in die
  App. Die Integration ist Einweg; manuelle Änderungen an App-Events im Kalender
  werden beim nächsten Reconcile überschrieben (bewusst).
- Keine automatische Umwandlung einer Reservierung in eine Ist-Zeit.
- Kein `pause`-Feld auf Reservierungen — eine Reservierung ist ein
  zusammenhängender Kalender-Block.
- Maximal **eine Reservierung pro Tag** (konsistent zum bestehenden `Storage`,
  ISO-Datum als Schlüssel).
- Reservierungen sind **kein** neuer Datentyp in `sync.py`/Drive-Sync.
- Kein neuer „Abgleichen"-Button — der Reconcile läuft automatisch.

## 4. Architektur

### 4.1 Neue Dateien

| Datei | Aufgabe | Vorlage |
|-------|---------|---------|
| `src/gcal.py` | Google-Calendar-API-Wrapper: Service-Aufbau, Kalenderliste, Event-CRUD, **pure** Payload-/Parse-Helper. Google-Imports **lazy in den Funktionen** (CI installiert kein `requirements.txt`). | `src/mail.py` |
| `src/reservations.py` | `ReservationStore` — JSON-Persistenz der Reservierungen (lokaler Cache `reservations.json`). | `src/storage.py` |
| `src/reservations_sync.py` | **pure** `merge_reservations()` + Orchestrator `reconcile_reservations()`. Bekommt den fertig gebauten Calendar-Service als Parameter → keine Google-Imports im Modul. | `src/sync.py` |

### 4.2 Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `src/mail.py` | `get_scopes()` bekommt zusätzlichen Parameter `gcal_enabled`; fügt die Calendar-Scopes hinzu, wenn aktiv. Alle Caller von `get_scopes()` werden angepasst. |
| `src/settings.py` | Neue Keys in `DEFAULTS`: `gcal_enabled` (bool, False), `gcal_calendar_id` (str, ""), `last_calendar_sync_at` (str, ""). `gcal_calendar_id` zusätzlich in `SYNCED_SETTING_KEYS`. |
| `src/sync.py` | `SYNCED_SETTING_KEYS` (Duplikat der Whitelist) um `gcal_calendar_id` ergänzen — die Liste existiert in `settings.py` *und* `sync.py` und muss konsistent bleiben. |
| `src/dialogs/settings_dialog.py` | Neuer Bereich „Google Kalender": Checkbox `gcal_enabled` + Kalender-Dropdown. |
| `src/dialogs/entry_dialog.py` | Zweiter Bereich „Reservierung" (Start/Ende) zusätzlich zur „Ist-Zeit". |
| `src/ui.py` | Reservierungen im Grid darstellen; Reconcile bei App-Start und nach Reservierungs-Save anstoßen. `App.__init__` instanziiert/erhält den `ReservationStore`. |
| `src/main.py` | `ReservationStore` aufbauen und an `App` übergeben (analog zu `Storage`/`Settings`). |
| `requirements.txt` | Prüfen — `google-api-python-client` ist durch Gmail/Drive bereits vorhanden, voraussichtlich **keine** neue Dependency. |

### 4.3 Unangetastet

`src/sync.py` (bis auf die Whitelist-Zeile), `src/drive.py`, `src/conflicts_store.py`,
`src/storage.py` — die Drive-Multi-Device-Sync weiß von Reservierungen nichts.

## 5. Datenmodell

### 5.1 `reservations.json`

Eine Reservierung pro Tag, ISO-Datum als Schlüssel:

```json
{
  "2026-05-25": {
    "start": "09:00",
    "end": "17:00",
    "modified_at": "2026-05-20T10:00:00Z",
    "deleted": false,
    "gcal_event_id": "abc123"
  }
}
```

- `modified_at` — UTC-ISO mit `Z`-Suffix (über `_utc_now_iso()`, wie im übrigen Code).
- `deleted` — Tombstone-Flag. Eine gelöschte Reservierung behält die Zeile mit
  `deleted: true`, bis der Reconcile das Kalender-Event erfolgreich entfernt hat;
  danach wird die Zeile entfernt. Tombstones sind also **kurzlebig** (nur relevant,
  wenn beim Löschen kein Netz da war).
- `gcal_event_id` — `null`, bis die Reservierung erstmals in den Kalender
  gepusht wurde; danach die Event-ID, damit Updates/Deletes dasselbe Event treffen.
- **Kein** `device_id` (anders als bei `Storage`) — `reservations.json` wird nicht
  über Drive synchronisiert.

Atomic write (`.tmp` + `os.replace`) und Corrupt-File-Handling (`.corrupt-<stamp>`)
exakt wie in `storage.py`.

### 5.2 Kalender-Event

- `summary`: `"Arbeitszeit (reserviert)"`
- `description`: kurzer Hinweis, dass das Event von der Zeiterfassung verwaltet wird.
- `start.dateTime` / `end.dateTime`: lokale, *aware* Datetime mit UTC-Offset, gebaut
  über `datetime.combine(date, time).astimezone()` → `.isoformat()` enthält den
  Offset (z.B. `2026-05-25T09:00:00+02:00`). Kein IANA-Zeitzonenname nötig — das
  vermeidet das Windows-tzdata-Problem.
- `extendedProperties.private`:
  - `zeiterfassung: "reservation"` — Marker, über den der Pull „seine" Events
    findet (`privateExtendedProperty`-Filter); manuell angelegte Termine bleiben
    dadurch unangetastet.
  - `modified_at: "<iso>"` — Merge-Vergleichsbasis, unabhängig vom Google-eigenen
    `updated`-Feld (das beim Push aktualisiert würde und damit unbrauchbar wäre).

## 6. Reconcile (pull → merge → push)

Eine einzige Operation, immer im Hintergrund-Thread. Beteiligt: `gcal.py` (I/O),
`reservations_sync.py` (`merge_reservations`, pure), `ReservationStore`.

### 6.1 Ablauf

1. **Pull:** Events des gewählten Kalenders mit
   `privateExtendedProperty=zeiterfassung=reservation` listen. Events nach Datum
   gruppieren; existieren mehrere Events für denselben Tag, gewinnt das mit dem
   jüngsten `modified_at`, die übrigen werden zum Löschen vorgemerkt
   (Selbstheilung gegen seltene Race-Duplikate, siehe 6.3).
2. **Merge:** `merge_reservations(local_raw, remote_events, watermark)` →
   liefert `{ "merged": {...}, "plan": {"create": [...], "update": [...], "delete": [...]} }`.
   `watermark` = `settings.last_calendar_sync_at`.
3. **Push:** Plan auf den Kalender anwenden (Create/Update/Delete). Bei jedem
   erfolgreich erstellten Event die zurückgegebene `event_id` in den Merge-Stand
   schreiben.
4. **Persistieren:** Merge-Stand in den `ReservationStore` schreiben,
   `settings.last_calendar_sync_at = _utc_now_iso()` setzen.

### 6.2 Merge-Regeln (pro Datum D)

`L` = lokale Reservierung (echt, Tombstone, oder fehlend), `R` = Remote-Event
(oder fehlend), `W` = Wasserstand `last_calendar_sync_at`. Vergleich von
`modified_at` als ISO-String (wie in `sync.py`).

| Fall | Bedingung | Aktion |
|------|-----------|--------|
| 1 | `L` fehlt, `R` fehlt | nichts |
| 2 | `L` Tombstone, `R` fehlt | Tombstone entfernen |
| 3 | `L` Tombstone, `R` vorhanden | LWW: `L.modified_at >= R.modified_at` → Event **löschen**, Tombstone entfernen. Sonst → Remote-Update ist jünger → Tombstone entfernen, `R` lokal **übernehmen** |
| 4 | `L` echt, `R` vorhanden | LWW: jüngeres `modified_at` gewinnt. Lokal gewinnt → **Update** auf `R.event_id` pushen. Remote gewinnt → lokal mit `R` **überschreiben**. Gleichstand → lokal gewinnt (App ist autoritativ). Werte gleich → No-op |
| 5 | `L` echt, `R` fehlt | `L.modified_at > W` → lokale Neuanlage → Event **erstellen**. `L.modified_at <= W` → war beim letzten Sync da, jetzt remote weg → anderes Gerät hat gelöscht → lokal **verwerfen** |
| 6 | `L` fehlt, `R` vorhanden | `R` lokal **übernehmen** (der Kalender ist der Speicher; hätte das Gerät `D` gelöscht, gäbe es einen Tombstone) |

Diese Logik spiegelt `sync.py::_merge_one` — **ohne** den Konflikt-Erkennungs-Zweig.
Es gibt keinen Konflikt-Dialog: bei beidseitiger Änderung gewinnt still der jüngere
Stand.

### 6.3 Selbstheilung gegen Duplikate

Der einzige Weg zu zwei Events für denselben Tag ist ein enges Race (zwei Geräte
pullen beide den leeren Tag und erstellen je ein Event, bevor eines das andere
sieht). Schritt 1 (Pull) erkennt das: pro Tag gewinnt das jüngste Event, die
übrigen landen im `delete`-Plan. Damit ist der Zustand nach dem nächsten Reconcile
wieder eindeutig.

## 7. OAuth & Scopes

- Neue Scopes (nur wenn `gcal_enabled`):
  - `https://www.googleapis.com/auth/calendar.events` — Event-CRUD.
  - `https://www.googleapis.com/auth/calendar.calendarlist.readonly` — Kalenderliste
    fürs Dropdown.
- `get_scopes(sync_enabled, gcal_enabled)` liefert die Vereinigung aller aktiven
  Scopes. `token.json` bleibt das gemeinsame Token für Gmail, Drive und Calendar.
- `gcal.py::get_calendar_service()` spiegelt `get_gmail_service()` inkl. der
  **Scope-Upgrade-Erkennung**: hat das gespeicherte Token nicht alle angeforderten
  Scopes, wird ein frischer OAuth-Flow erzwungen. Fehlt `credentials.json`, kommt
  dieselbe klare Fehlermeldung wie bei Gmail.
- `gcal_enabled` wird **pro Gerät** gesetzt (nicht synchronisiert): jedes Gerät
  hat sein eigenes `token.json` und durchläuft den Consent selbst. Nur die
  *Auswahl* `gcal_calendar_id` konvergiert über die Drive-Settings-Sync.

## 8. UI

### 8.1 Tages-Dialog (`entry_dialog.py`)

- Der bestehende **Ist-Zeit**-Block (Start / Ende / Pause + Speichern / Löschen)
  bleibt unverändert.
- Darunter, durch einen Trenner abgesetzt, ein **Reservierung**-Block
  (Start / Ende, kein Pause) mit eigenem Speichern / Löschen.
- Der Reservierung-Block wird nur gebaut, wenn `date >= heute` **oder** für den Tag
  bereits eine Reservierung existiert (vergangene Tage kann man nicht neu
  reservieren, eine alt gewordene Reservierung aber noch sehen/löschen).
- Beide Blöcke speichern **unabhängig**. Validierung der Reservierung über
  `time_utils.validate_entry(start, end, 0)`.
- Die Reservierung wird **immer zuerst lokal** gespeichert, danach läuft der
  Reconcile — ein Kalender-Fehler verliert nie die Eingabe.
- Die Feiertags-Warnung beim Anlegen betrifft weiterhin nur die Ist-Zeit.

### 8.2 Grid-Darstellung (`ui.py`)

Ein Tag kann Ist-Zeit, Reservierung, beides oder nichts haben:

| Tag-Zustand | Zelle |
|-------------|-------|
| Nur Reservierung | „Geplant"-Look — abgesetzte Rahmenfarbe (neue Theme-Konstante, z.B. `RESERVATION_ACCENT` in `theme.py`), reservierte Zeit angezeigt |
| Nur Ist-Zeit | Wie bisher (Eintragszelle) |
| Beides | Ist-Zeitzelle als Primärdarstellung **+ kleiner Eck-Marker**; Tooltip zeigt die reservierte Zeit |
| Feiertag / Konflikt | Bestehende Logik bleibt vorrangig |

- Gilt für Monats- *und* Wochenansicht.
- Der Footer „Gesamt: Xh" zählt weiterhin **nur Ist-Zeiten**.
- Neue Farb-/Stil-Konstanten kommen nach dem Muster der vorhandenen `theme.py`-
  Konstanten dazu; die Pixel-Fixierung der Zellen (siehe `_build_entry_cell`)
  wird beibehalten.

### 8.3 Settings-Dialog (`settings_dialog.py`)

- Neuer Bereich „Google Kalender": Checkbox „Reservierungen mit Google Kalender
  abgleichen" (`gcal_enabled`) + Dropdown „Kalender".
- Das Dropdown wird im Hintergrund über `gcal.list_calendars()` befüllt; bis die
  Liste da ist, wird der gespeicherte Wert bzw. „Lädt…" angezeigt.
- Erste Aktivierung ohne Auswahl → Default `"primary"`.
- `gcal_calendar_id` wird mit `settings.set_synced(...)` gespeichert, damit die
  Auswahl über die Drive-Settings-Sync mitreist.

## 9. Trigger & Threading

- **App-Start:** Hintergrund-Reconcile in `App.__init__`, analog zu
  `_proactive_token_refresh` — nur wenn `gcal_enabled` und `gcal_calendar_id`
  gesetzt sind. Andernfalls No-op.
- **Nach Reservierungs-Save/Delete:** Der `on_change`-Pfad des Tages-Dialogs
  stößt einen Hintergrund-Reconcile an.
- Erfolgreicher Reconcile → `root.after(0, self._refresh)` rendert das Grid neu.
- Alle State-Mutationen aus dem Worker-Thread (Settings, Store) werden via
  `root.after(0, …)` auf den UI-Thread marshallt — wie beim bestehenden
  Update-Check.

## 10. Fehlerbehandlung (CLAUDE.md-Regeln)

- `--noconsole` schluckt stderr → alle Fehler im Kalender-Pfad werden über
  `messagebox.showerror` mit `traceback.format_exc()` sichtbar gemacht.
- **Start-Reconcile:** Fehler werden **still** verschluckt und nur ins Logfile
  geschrieben (ein Offline-Start darf nicht nerven — analog Token-Refresh und
  Update-Check).
- **Save-Reconcile:** Fehler werden als Messagebox gezeigt — der User hat aktiv
  gespeichert und erwartet Feedback.
- Auth-/Scope-Fehler werden über die Scope-Upgrade-Erkennung in
  `get_calendar_service()` zum OAuth-Re-Consent geleitet.
- Datenintegrität: Die Reservierung liegt nach dem lokalen Save sicher in
  `reservations.json`; schlägt der Reconcile fehl, wird sie beim nächsten
  erfolgreichen Reconcile nachgezogen.

## 11. Tests

CI (`.github/workflows/test.yml`) installiert nur `pytest` + `holidays`, **nicht**
`requirements.txt`. Konsequenz: alle Google-Imports in `gcal.py` liegen **lazy**
in den Funktionen (wie `mail.py` / `report.py::generate_pdf`), damit
`import src.gcal` und die Test-Sammlung in der CI durchlaufen.

| Testdatei | Inhalt |
|-----------|--------|
| `tests/test_reservations.py` | `ReservationStore`: CRUD, Tombstones, atomic write, Corrupt-File-Handling (spiegelt `test_storage.py`) |
| `tests/test_reservations_sync.py` | pure `merge_reservations()` — alle Merge-Fälle 1–6 aus 6.2, Duplikat-Selbstheilung, `event_id`-Übernahme |
| `tests/test_gcal.py` | pure Helper: Reservierung → Event-Payload (`dateTime` mit Offset, `extendedProperties`) und `parse_event()` zurück |
| `tests/test_settings.py` | neue Keys in `DEFAULTS`; `gcal_calendar_id` in `SYNCED_SETTING_KEYS` (in `settings.py` und `sync.py` konsistent) |

Echte Calendar-API-Calls (`list`/`insert`/`update`/`delete`) werden **nicht**
unit-getestet — wie der Gmail-Versand.

## 12. Abhängigkeiten & Build

- Die Calendar API nutzt dieselbe `googleapiclient`-Bibliothek wie Gmail/Drive
  (`build("calendar", "v3", …)`) → voraussichtlich **keine neue Dependency**;
  `requirements.txt` wird nur verifiziert.
- `build.py` bleibt unverändert (`googleapiclient` wird durch Gmail/Drive bereits
  gebündelt). Im Frozen-Build ist zu verifizieren, dass die Calendar-v3-Discovery
  auflöst.

## 13. Konventionen

Die Implementierung setzt durchgehend die bestehenden Muster fort:

- Neue Module spiegeln ihre Vorlagen: `gcal.py` ↔ `mail.py`,
  `reservations.py` ↔ `storage.py`, `reservations_sync.py` ↔ `sync.py`.
- Lazy Google-Imports, atomic JSON-Writes, `_utc_now_iso()` mit `Z`-Suffix.
- Fehler im Sendepfad als `messagebox` mit Traceback; Worker-Threads marshallen
  über `root.after(0, …)`.
- Deutschsprachige Kommentare/Strings im Stil der vorhandenen Dateien.
- Die Whitelist `SYNCED_SETTING_KEYS` muss in `settings.py` und `sync.py`
  identisch bleiben.

## 14. Release-Hinweis

Vor dem Merge nach `master`: `src/version.py` bumpen, `CHANGELOG.md` ergänzen,
passendes `release:*`-Label setzen (siehe CLAUDE.md „Release-Prozess").

## 15. Offene Punkte

Keine offenen Design-Entscheidungen. `reconcile_reservations()` ist als
Modulfunktion in `reservations_sync.py` festgelegt (4.1); im Implementierungsplan
ist nur noch festzulegen, von welchen Call-Sites aus sie angestoßen wird
(App-Start in `App.__init__`, Save-Pfad über den `on_change`-Callback des
Tages-Dialogs — siehe Abschnitt 9).
