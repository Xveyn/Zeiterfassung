# Multi-Device-Sync via Google Drive — Design

**Status:** Spec  
**Datum:** 2026-05-14

## Problem

User können das Tool auf mehreren Geräten (Laptop, Desktop, Zweitrechner) mit demselben Google-Konto nutzen. Aktuell sind die Zeiteinträge rein lokal in `zeiterfassung.json`. Wer auf Gerät A einträgt und später auf Gerät B weiterarbeitet, fängt dort von vorne an. Ziel: Einträge und mailbezogene Einstellungen synchronisieren, ohne Datenverlust bei Offline-Bearbeitung mehrerer Geräte.

## Scope

**Synchronisiert wird:**
- Alle Zeiteinträge (Map `ISO-Datum → {start, end, pause}`)
- Eine Whitelist von Settings: `recipient`, `name`, `hourly_rate`, `mail_subject`, `mail_greeting`, `mail_content`, `mail_closing`
- Konflikte (als First-Class-Objekt, damit Resolutions auf andere Geräte propagieren)

**Nicht synchronisiert (bleibt pro Gerät):**
- `autostart`, `dismissed_version`, `last_update_check_at`, `state`
- Per-Wochentag-Default-Zeiten (`default_start_mon` etc.) und `default_pause` — bewusst gerätespezifisch, weil typische Defaults zwischen „Büro-Desktop" und „Heim-Laptop" abweichen können
- `show_weekend`
- `sync_enabled`, `device_id`, `last_pull_at`, `drive_etag` (Sync-Meta selbst)

**Opt-in:** Default off. Aktivierung erfordert OAuth-Re-Consent für den zusätzlichen Drive-Scope.

**Out of scope (bewusst):**
- Garbage Collection für Tombstones (siehe `docs/known-limitations.md`)
- Sync von `credentials.json` / `token.json` selbst — bleibt pro Gerät
- Echtzeit-Sync zwischen offenen Apps (es gibt kein Push vom Cloud-Backend)
- Mehrere User mit unterschiedlichen Google-Accounts auf einem Gerät

## Ansatz

**Backend:** Google Drive `appDataFolder` mit Scope `drive.appdata`. Eine einzelne versteckte JSON-Datei `zeiterfassung-sync.json` pro Google-Account, nur diese App sieht sie, kein UI-Müll im sichtbaren Drive des Users.

**Konfliktstrategie:** Last-Write-Wins pro Eintrag mit `modified_at`-Stempel als Default. Echte Konflikte (beide Seiten haben denselben Tag seit `last_pull_at` geändert) werden als persistente Konflikt-Objekte angelegt und vom User manuell aufgelöst. Resolutions propagieren über denselben Sync-Mechanismus.

**Sync-Trigger:** Pull beim App-Start (falls Sync aktiv + Netz da). Push manuell via Header-Button und automatisch beim sauberen App-Schließen. Kein Auto-Push nach jeder Edit — vermeidet API-Traffic und gibt User Kontrolle.

## Datenmodell

### Sync-File (`zeiterfassung-sync.json` in Drive `appDataFolder`)

```json
{
  "schema_version": 1,
  "entries": {
    "2026-05-14": {
      "start": "08:00",
      "end": "16:00",
      "pause": 30,
      "modified_at": "2026-05-14T10:30:00Z",
      "device_id": "abc-uuid-1",
      "deleted": false
    },
    "2026-05-13": {
      "start": null, "end": null, "pause": null,
      "modified_at": "2026-05-14T09:15:00Z",
      "device_id": "abc-uuid-1",
      "deleted": true
    }
  },
  "settings": {
    "recipient": {"value": "x@y.de", "modified_at": "...", "device_id": "..."},
    "name":      {"value": "Max",    "modified_at": "...", "device_id": "..."}
  },
  "conflicts": [
    {
      "id": "conflict-uuid-1",
      "kind": "entry",
      "key": "2026-05-14",
      "candidates": [
        {"value": {"start": "08:00", "end": "16:00", "pause": 30},
         "modified_at": "...", "device_id": "abc-uuid-1"},
        {"value": {"start": "09:00", "end": "17:00", "pause": 30},
         "modified_at": "...", "device_id": "def-uuid-2"}
      ],
      "detected_at": "2026-05-14T11:00:00Z",
      "resolved": false,
      "resolution": null,
      "resolved_at": null,
      "resolved_by": null
    }
  ]
}
```

`kind: "entry"` heute, `kind: "setting"` reserviert für Konflikte auf Settings-Feldern (gleicher Mechanismus, Key ist dann z. B. `"recipient"`).

### Lokale Erweiterungen

**`zeiterfassung.json` (Storage):** Eintragsobjekte bekommen zusätzlich `modified_at`, `device_id`, `deleted`. Bestehende Einträge ohne diese Felder beim ersten Lesen migrieren: `modified_at = mtime der Datei`, `device_id = own_device_id`, `deleted = false`.

**`settings.json` (Settings):** Neue Top-Level-Keys
- `sync_enabled` (bool, default false)
- `device_id` (str, einmal generiert per `uuid.uuid4()`)
- `last_pull_at` (str ISO, default `""`)
- `drive_etag` (str, default `""`) — Optimistic Locking für Push
- `synced` (dict) — interne Tracking-Struktur für die Settings-Whitelist, Form `{key: {"value": ..., "modified_at": ..., "device_id": ...}}`. Wird beim Setzen eines Whitelist-Keys automatisch mit aktualisiert. Die „Read-Side" (`get()`) liest weiterhin aus dem flachen Dict — die UI sieht keinen Unterschied.

**`conflicts.json` (neue Datei in `get_base_path()`):** Spiegel der `conflicts`-Liste aus dem Sync-File. Pro Gerät lokal vorgehalten, damit der Conflict-Dialog ohne Netzverbindung funktioniert. Wird beim Pull aus dem Sync-File überschrieben, beim Push aus diesem gelesen.

## Architektur

### Neue Module

**`src/sync.py`** — pure Logik, keine Drive-Calls. Komplett unit-testbar.

```
merge(local_doc, remote_doc, last_pull_at, device_id) -> merged_doc
build_local_doc(storage, settings, conflicts_store) -> local_doc
apply_merged_doc(merged_doc, storage, settings, conflicts_store)
resolve_conflict(conflict_id, chosen_value, conflicts_store, storage, device_id)
SYNCED_SETTING_KEYS = ("recipient", "name", "hourly_rate", "mail_subject",
                       "mail_greeting", "mail_content", "mail_closing")
```

**`src/drive.py`** — analog zu `mail.py`. Kapselt OAuth + Drive-REST-Calls.

```
DriveAuthError, DriveNetworkError, DriveConflictError  # Exceptions
get_drive_service(credentials_path, token_path) -> service
find_sync_file(service) -> file_id | None
download(service, file_id) -> (bytes, etag)
upload(service, content_bytes, file_id=None, expected_etag=None) -> (file_id, etag)
delete_sync_file(service, file_id)
```

**`src/dialogs/conflicts_dialog.py`** — neuer Modal-Dialog.

### Geänderte Module

**`src/storage.py`**
- `Storage.__init__(filepath, device_id)` — neuer Parameter
- Migrations-Pfad in `_load`: alte Einträge ohne Metadaten bekommen `modified_at = file_mtime` (oder Now bei fehlender Datei), `device_id = own_device_id`, `deleted = False`
- `save(date, start, end, pause)` stempelt `modified_at = now()`, `device_id = own_device_id`, `deleted = False`
- `delete(date)` setzt Tombstone statt physisches `del`: `{"start": None, "end": None, "pause": None, "modified_at": now(), "device_id": own_device_id, "deleted": True}`
- `get(date_str)` filtert Tombstones (gibt `None` wie bisher, wenn `deleted` oder fehlend)
- `get_all()` filtert Tombstones (kompatibel mit allen bestehenden Callern)
- Neu: `get_all_raw()` (inkl. Tombstones, nur für Sync)
- Neu: `apply_merge(merged_entries)` — überschreibt internen Dict, atomic write

**`src/settings.py`**
- Neue DEFAULTS für die Sync-Meta-Keys
- Neue Methode `set_synced(key, value)` — setzt im flachen Dict **und** in `_synced[key]` mit aktuellem `modified_at`/`device_id`. Die UI ruft beim Speichern der Mail-Settings diese Methode statt `set()`. Backwards-compat: `set()` für Whitelist-Keys leitet automatisch weiter.
- Neue Methode `get_synced_doc()` / `apply_synced(synced_dict)` für Sync

**`src/mail.py`**
- `SCOPES` wird abhängig vom Sync-State zusammengebaut: `gmail.send` immer, `drive.appdata` wenn `sync_enabled` oder beim Aktivierungs-Flow
- Bei aktivem Sync wird `token.json` mit beiden Scopes geschrieben. Beim Aktivieren neue OAuth-Runde mit erweitertem Scope.

**`src/main.py`**
- Beim Start: wenn `sync_enabled` → `sync.pull_and_apply()` non-blocking im Hintergrund-Thread; Ergebnis via `root.after()` auf UI-Thread
- Bei `WM_DELETE_WINDOW` (vor `destroy`): falls Sync aktiv und Daten dirty → blocking Push mit Timeout (z. B. 5s), Fehler werden geloggt aber nicht angezeigt (App schließt)

**`src/ui.py`**
- Header: Sync-Button rechts vom Settings-Button + Status-Label
- Status-Texte: „Synchronisiert" / „N Konflikte" / „Offline" / „Fehler: …" / „Synchronisiere…"
- Konflikt-Markierung im Kalender: Zelle mit aktiven Konflikt bekommt zusätzliches Farb-Tag und Tooltip
- Banner-Updater berücksichtigt Konflikt-Count

**`src/dialogs/settings_dialog.py`**
- Neue Sektion „Synchronisation":
  - Checkbox „Mit Google Drive synchronisieren"
  - Beim Aktivieren: OAuth-Flow mit `drive.appdata` triggern, Erfolg / Fehler anzeigen
  - Status-Text: letzte Sync-Zeit, Device-ID (zur Wiedererkennung im Konflikt-Dialog)
  - Button „Konflikte ansehen (N)" wenn N > 0 → öffnet ConflictsDialog
  - Beim Deaktivieren: optionaler Button „Sync-Daten in Drive löschen"

## Algorithmen

### Pull-and-Merge (`sync.pull_and_apply`)

```
1. service = drive.get_drive_service(...)
2. file_id = drive.find_sync_file(service)
3. if file_id is None:
       remote_doc = empty_doc()
       remote_etag = ""
   else:
       bytes, remote_etag = drive.download(service, file_id)
       remote_doc = json.loads(bytes)
4. local_doc = sync.build_local_doc(storage, settings, conflicts_store)
5. merged = sync.merge(local_doc, remote_doc, settings["last_pull_at"], device_id)
6. sync.apply_merged_doc(merged, storage, settings, conflicts_store)
7. settings.set("last_pull_at", now_iso())
8. settings.set("drive_etag", remote_etag)
```

### Merge-Funktion (Kern)

```
merge(local, remote, last_pull_at, device_id):
    merged = empty_doc()
    
    # Einträge
    for key in union(local.entries, remote.entries):
        l, r = local.entries.get(key), remote.entries.get(key)
        merged.entries[key], conflict = _merge_one(l, r, last_pull_at)
        if conflict:
            merged.conflicts.append(conflict)
    
    # Settings (Whitelist) — gleiche Logik wie Einträge, nur dict-Pfad statt entries-Pfad
    for key in SYNCED_SETTING_KEYS:
        l, r = local.settings.get(key), remote.settings.get(key)
        merged.settings[key], conflict = _merge_one(l, r, last_pull_at)
        if conflict:
            conflict["kind"] = "setting"
            merged.conflicts.append(conflict)
    
    # Bestehende Konflikte mergen (Union by ID)
    by_id = {c["id"]: c for c in local.conflicts}
    for rc in remote.conflicts:
        if rc["id"] in by_id:
            by_id[rc["id"]] = _merge_conflict(by_id[rc["id"]], rc)  # LWW auf resolved_at
        else:
            by_id[rc["id"]] = rc
    # neu erkannte Konflikte aus diesem Merge ergänzen (dedupe nach (kind, key, candidate-set))
    for c in newly_detected_conflicts:
        if not _equivalent_unresolved_exists(by_id.values(), c):
            by_id[c["id"]] = c
    merged.conflicts = list(by_id.values())
    
    # Apply Resolutions: für jeden resolved Konflikt, der einen Eintrag betrifft,
    # setze merged.entries[key] auf die Resolution (mit deren modified_at)
    for c in merged.conflicts:
        if c["resolved"]:
            target = merged.entries if c["kind"] == "entry" else merged.settings
            current = target.get(c["key"])
            if current is None or current["modified_at"] < c["resolved_at"]:
                target[c["key"]] = {**c["resolution"], "modified_at": c["resolved_at"],
                                    "device_id": c["resolved_by"]}
    
    return merged
```

```
_merge_one(local, remote, last_pull_at):
    if local is None: return (remote, None)
    if remote is None: return (local, None)
    if _values_equal(local, remote): return (local, None)
    local_changed = local["modified_at"] > last_pull_at
    remote_changed = remote["modified_at"] > last_pull_at
    if local_changed and remote_changed:
        # Konflikt
        winner = local if local["modified_at"] >= remote["modified_at"] else remote
        return (winner, make_conflict(local, remote))
    return (local if local["modified_at"] >= remote["modified_at"] else remote, None)
```

**Konflikt-Idempotenz:** Wenn derselbe Konflikt-State (gleicher Key, gleiche Kandidaten-Werte) bereits unresolved in `conflicts` existiert, wird kein neuer angelegt — wichtig, damit wiederholte Pulls vor Resolution nicht die Liste aufblähen.

### Push (`sync.push`)

```
1. doc = sync.build_local_doc(storage, settings, conflicts_store)
2. file_id = drive.find_sync_file(service)  # None bei Erstnutzung → upload erzeugt File
3. try:
       new_etag = drive.upload(service, json.dumps(doc).encode(), file_id,
                                expected_etag=settings["drive_etag"])
   except DriveConflictError:
       sync.pull_and_apply(service)             # 1× retry
       doc = sync.build_local_doc(...)
       new_etag = drive.upload(service, json.dumps(doc).encode(), file_id,
                                expected_etag=settings["drive_etag"])
4. settings.set("drive_etag", new_etag)
```

Wenn das zweite Push immer noch `DriveConflictError` wirft: User-sichtbarer Fehler-Toast, nicht weiter retry'en.

### Konflikt-Resolution (`sync.resolve_conflict`)

```
resolve_conflict(conflict_id, chosen_value, ...):
    c = conflicts_store.get(conflict_id)
    c["resolved"] = True
    c["resolution"] = chosen_value          # darf auch ein neuer, manuell editierter Wert sein
    c["resolved_at"] = now_iso()
    c["resolved_by"] = device_id
    if c["kind"] == "entry":
        storage.save(c["key"], **chosen_value)   # stempelt auch modified_at
    else:
        settings.set_synced(c["key"], chosen_value)
    conflicts_store.save()
```

## Fehlerbehandlung

| Situation | Verhalten |
|---|---|
| Sync deaktiviert | Komplett no-op, keine Drive-Calls, keine UI-Elemente |
| Kein Netz beim Pull beim Start | Banner „Offline — lokale Daten in Verwendung". Push-Button bleibt aktiv, schlägt fehl mit selbem Banner |
| Auth-Fehler (Token revoked) | Settings-Dialog Banner „Bitte neu mit Google verbinden". OAuth-Flow erneut anwerfbar |
| Drive-Quota überschritten | Push-Fehler-Toast, lokale Daten unverändert |
| Etag-Mismatch beim Push | Automatisch 1× Pull-Merge-Push-Retry. Bei wiederholtem Mismatch User-Toast |
| Korruptes Remote-File | Per Drive-API umbenennen zu `zeiterfassung-sync.corrupt-<ts>.json`, frisches File anlegen, Banner |
| Zwei Geräte resolven Konflikt gleichzeitig | LWW auf `resolved_at`. Kein User-Banner (Edge Case, beide Resolutions sind plausibel) |
| Lokale `conflicts.json` korrupt | Wie `storage.py` heute: umbenennen zu `.corrupt-<ts>`, leer starten. Beim nächsten Pull aus Remote wiederhergestellt |
| User deaktiviert Sync | Lokal: alles bleibt. Remote: bleibt liegen (User-Schutz). Optionaler Button „Sync-Daten in Drive löschen" |
| Sync läuft beim App-Close länger als 5s | Push abbrechen, lokal weiter, beim nächsten Start neu pushen (Daten lokal ja immer noch da) |

**Pflicht (per CLAUDE.md):** Alle Sync-Fehler im `messagebox.showerror` oder UI-Banner mit `traceback.format_exc()` zeigen — `--noconsole` versteckt sonst alles im gebauten Artefakt.

## Tests

**`tests/test_sync.py`** — Unit-Tests für `sync.py`, keine externen Abhängigkeiten:
- `_merge_one`: alle Permutationen (nur lokal, nur remote, gleich, unterschiedlich × {beide vor / einer nach / beide nach last_pull_at})
- Tombstone vs. Save in beiden Richtungen, Tombstone wins by `modified_at`
- `merge()`: Konflikt-Erkennung erzeugt korrekte Conflict-Objekte
- Konflikt-Idempotenz: wiederholter `merge()`-Call mit denselben Inputs erzeugt nicht mehrere identische unresolved Konflikte
- Resolution-Propagation: lokal hat resolved Konflikt, remote hat denselben unresolved → merged hat resolved + entries[key] auf Resolution-Wert gesetzt
- Race: beide Geräte resolven denselben Konflikt unterschiedlich → LWW auf `resolved_at`
- Settings-Sync: gleiche Logik für `SYNCED_SETTING_KEYS`, nicht-whitelisted Settings werden im Merge ignoriert

**`tests/test_storage_migration.py`** — Tests für die Migration alter `zeiterfassung.json`-Files ohne Metadaten:
- Datei ohne `modified_at`-Felder lädt erfolgreich
- Migrierte Einträge bekommen `modified_at` aus File-mtime, `device_id` aus Constructor
- Bestehende Tests in `test_storage.py` bleiben grün (Backwards-Compat)

**`tests/test_drive.py`** — wie `test_mail.py` heute, mit `unittest.mock` für `googleapiclient.discovery.build`:
- OAuth-Pfade (Token vorhanden, expired, refresh, fresh consent)
- `find_sync_file` mit / ohne Resultat
- `download`/`upload` Happy Path + Etag-Mismatch + Netzwerk-Fehler
- Keine Live-Drive-Calls in CI (analog zu Gmail-Tests, kein Credential-Setup im Workflow)

**`tests/test_sync_integration.py`** — End-to-End ohne Drive:
- Reales `Storage` + `Settings` + `Conflicts` → `build_local_doc` → durch `merge()` → `apply_merged_doc` zurück → keine Datenverluste, alle Round-Trips konsistent

**CI-Anpassung:** Eventuell `google-api-python-client`, `google-auth-oauthlib` als Test-Deps in `.github/workflows/test.yml` ergänzen (heute werden nur `pytest`, `holidays` installiert). Falls die Drive-Tests rein gemockt sind, reicht der Mock und keine zusätzliche Lib — präferiert.

**Manueller Test-Plan (vor Release):**
1. Zwei Geräte, beide mit demselben Google-Account, Sync auf beiden aktivieren → Initial-Sync, Daten erscheinen in beide Richtungen
2. Offline-Szenario: A offline, beide bearbeiten denselben Tag, A geht online und pullt → Konflikt erscheint auf A, Resolution auf A propagiert beim nächsten Sync auf B
3. Auth-Revoke in Google-Account-Settings → App zeigt Re-Connect-Banner beim nächsten Sync-Versuch
4. Sync deaktivieren auf einem Gerät → lokale Daten unverändert, Remote bleibt liegen, Reaktivierung führt zu sauberem Sync
5. Sync-Datei im Drive manuell löschen (über Drive-API, da `appDataFolder` nicht im UI sichtbar) → nächster Push legt frisches File an

## Migration & Backwards-Kompatibilität

- Bestehende `zeiterfassung.json` ohne Metadaten: lazy migration beim ersten Laden. Eintrag-Werte bekommen `modified_at = file_mtime`, `device_id = own_device_id`. Alte Einträge ohne `deleted`-Feld werden als `deleted=False` interpretiert.
- Bestehende `settings.json` ohne `sync_enabled`: lädt mit Default `False`, kein Verhalten ändert sich für den User
- Bestehender `token.json` mit nur `gmail.send`-Scope: funktioniert für Mail weiter. Wenn User Sync aktiviert → neuer Consent-Flow überschreibt `token.json` mit beiden Scopes. Wenn Aktivierung abgebrochen → alter Token bleibt.

## Offene Punkte (bewusst weggelassen)

- **Tombstone-GC:** Siehe `docs/known-limitations.md`. Erste Iteration ohne GC.
- **Selektives Sync-Disable pro Setting:** User könnte z. B. wollen, dass `hourly_rate` nicht synchronisiert wird. Alle-oder-keiner-Ansatz reicht für jetzt.
- **Conflict-Merge-Editor:** Aktuell „A oder B oder manuell neu". Ein echter Diff-Merge-Editor (z. B. Pause aus A + Zeiten aus B) ist denkbar, aber YAGNI.
- **Sync-Status-Push-Notification (Cross-Device):** Echtzeit-Awareness ist out of scope.
