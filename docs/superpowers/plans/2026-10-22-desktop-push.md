# Desktop: Push-Erinnerungen aufs Handy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Desktop schaltet die Handy-Erinnerungen ein (Tab „Erinnerungen“), liefert der PWA im Abgleich den Block `reminders`, speichert das Relay-Geheimnis des Handys gehärtet und räumt beim Widerruf dessen Relay-Objekt ab (PR 4 von 5 aus #331).

**Architecture:** Neue Tk-freie Module (`mobile_reminders.py` baut den Block und liest das Geheimnis, `mobile_relay_store.py` hält die Geheimnisse, `push_relay.py` löscht Relay-Objekte), eine reine Funktion `send_reminder.upcoming_send_times` für die Sende-Zeitpunkte. Verdrahtet wird über `mobile_sync.perform_sync`, `mobile_routes`, `MobileService` und den Reiter „Erinnerungen“. Die PWA (PR 3, `pwa/CLAUDE.md` „Benachrichtigungen“) ist fertig und wartet auf den Block.

**Tech Stack:** Python 3.12, Tkinter (nur der Reiter), `pytest`, stdlib `urllib`.

**Spec:** `docs/superpowers/specs/2026-10-21-pwa-push-erinnerungen-design.md` (Abschnitt „Desktop“). PWA-Seite: `pwa/CLAUDE.md`, Fixture `pwa/test/fixtures/reminders-contract.json`.

## Global Constraints

- Deutsch in Doku, Kommentaren und Texten; TDD; jeder Catch-all loggt oder trägt eine Begründung (`tests/test_catch_all_handlers.py`); Tk-freie Module vollständig annotiert (Whitelist in `tests/test_type_annotations.py`).
- Neue Einstellungen sind **gerätelokal**, nicht in `SYNCED_SETTING_KEYS`: `mobile_push_enabled` (False), `mobile_push_reservation` (True), `mobile_push_send` (True), `mobile_push_suppress_toast` (False).
- `PROTOCOL` bleibt 2; `reminders` in der Antwort und `push` in der Anfrage sind additiv. Die Live-Fixtures `sync-response.json`/`sync-request.json` bleiben **unverändert** (die PWA-Tests hängen daran); der Vertrag liegt in `reminders-contract.json`.
- Zeitpunkte auf dem Draht: `YYYY-MM-DDTHH:MM:SSZ` (UTC); der Block trägt höchstens 62 Tage und höchstens 200 Zeitpunkte, aufsteigend, eindeutig.
- Das Relay-Geheimnis (43 Zeichen base64url) steht in keinem Log, keinem Fehlertext und nicht in `mobile_devices.json` (die schreibt jeder Abgleich).
- Der Relay ist nie Voraussetzung: jeder Fehler beim Löschen am Relay bleibt ein Logeintrag und hält den Widerruf nicht auf.
- Neue Datei im Datenordner → `removal.py` (`CREDENTIAL_FILES`), `installer.iss` (`[UninstallDelete]`), `.gitignore`.

## Review Focus

- Sommerzeit-Wechsel: eine Sende-Zeit in der übersprungenen Stunde (02:30 am Umstelltag) darf weder werfen noch doppelt erscheinen.
- Monatskürze/Verschiebung: Tag 31 im Februar, Verschiebung über Monatsgrenzen bleibt im Zielmonat (`scheduled_datetime`), Zeiten in der Vergangenheit entfallen.
- Ausgeschaltet heißt **leerer Block**, nicht fehlender: sonst bliebe der alte Plan am Relay stehen.
- Toast wird nur unterdrückt, wenn die Handy-Erinnerung die Art wirklich abdeckt (Schalter an, Art angehakt, mindestens ein Gerät mit bekanntem Geheimnis und nicht widerrufen).
- Ungültiges `push` in der Anfrage kippt den Abgleich nicht; ein Geheimnis wird nur bei Änderung geschrieben (kein `icacls` je Abgleich).
- Widerruf bei nicht erreichbarem Relay: Gerät ist widerrufen, Fehler im Log, Geheimnis lokal entfernt.
- Frist des Relays: nichts über 89 Tage (der Block endet bei 62).

## Festlegungen (meine, im PR sichtbar zu machen)

- **Ablage des Geheimnisses:** eigene Datei `mobile_relay.json` (`{device_id: secret}`), geschrieben über `secure_file.write_secret_json`, nur bei Änderung; kein Schlüsselbund (das Geheimnis schützt nur das Relay-Objekt des Handys, sein Verlust lässt Dritte höchstens Erinnerungen löschen oder ersetzen). *Alternative: Schlüsselbund wie `mobile_keys`; teurer, hier nicht nötig.*
- **Phone-Erinnerung ist unabhängig vom Toast-Schalter:** „Minuten vor Ende“ (`reminder_minutes_before`) gilt für beide; der Reiter schaltet die Zeile frei, sobald eines von beiden an ist.
- **Reservierungs-Block** nur mit eingeschalteten Reservierungen (`reservations_enabled`); **Sende-Block** aus Monats- und Tages-Erinnerung zusammen.
- **Ungültiges `push.relay_secret`** wird verworfen (Logzeile ohne Wert), nicht mit `422` beantwortet.
- **Verwaiste Relay-Objekte** nach `prune` (Gerät 30 Tage nach Ablauf vergessen) werden nicht aktiv gelöscht; sie verfallen am Relay nach 90 Tagen. Die lokalen Geheimnisse entfallen sofort (`retain`).
- **Der Reiter** zeigt den Abschnitt „Handy“ nur, wenn die Handy-Instanz vorhanden ist (`mobile_service`).

---

### Task 1: Einstellungen

**Files:** Modify `src/settings.py` (DEFAULTS), `src/dialogs/settings_dialog/tab_rules.py` (`reminders_updates`, `validate_reminders` unverändert), `tests/test_settings*.py` (passende Datei suchen: `grep -l SYNCED_SETTING_KEYS tests`)

**Interfaces:**
- Produces: die vier Schlüssel oben in `DEFAULTS`; `reminders_updates(values)` liefert sie mit.

- [ ] **Step 1: Tests.** `test_mobile_push_defaults`: Standardwerte `False/True/True/False`; `test_mobile_push_keys_are_device_local`: keiner steht in `SYNCED_SETTING_KEYS`; `test_reminders_updates_carry_the_phone_keys` (Bool-Werte werden als `bool` übernommen); `test_tabs_together_write_exactly_the_legacy_keys` (bestehend) um die vier Schlüssel erweitern.
- [ ] **Step 2:** `pytest tests/ -k "mobile_push or legacy_keys or reminders_updates" -q` — Expected: FAIL.
- [ ] **Step 3: Implementiere** die vier `DEFAULTS` mit Kommentar „gerätelokal“ und `reminders_updates` (Bool-Felder wie `reminders_enabled`).
- [ ] **Step 4:** Run — Expected: PASS.
- [ ] **Step 5: Commit** `feat(mobile): Einstellungen für Handy-Erinnerungen (#331)`.

### Task 2: `send_reminder.upcoming_send_times` — die Sende-Zeitpunkte

**Files:** Modify `src/send_reminder.py`, `tests/test_send_reminder.py`

**Interfaces:**
- Produces: `upcoming_send_times(now: datetime.datetime, *, monthly: Mapping | None, daily_slots: Iterable[tuple[datetime.date, str, int]], days: int = 62, tz: datetime.tzinfo | None = None) -> list[str]` — `monthly = {day, time, shift, state, holidays}` oder `None`; `daily_slots` = `(Datum, Ende "HH:MM", Minuten)` der markierten Reservierungs-Slots. Liefert sortierte, eindeutige UTC-Stempel `YYYY-MM-DDTHH:MM:SSZ`, nur `> now`, höchstens `days` Tage voraus, höchstens 200. `now` ist naiv lokal; `tz=None` heißt Systemzone.
- Consumes: `scheduled_datetime`, `free_dates_for_month`, `_parse_hhmm_on` (vorhanden).

- [ ] **Step 1: Tests** mit fester Zone (`datetime.timezone(timedelta(hours=2))`): Monatstermin 18:00 → 16:00Z; Vergangenes entfällt; Tag 31 im 30-Tage-Monat und im Februar geclamped; Verschiebung über Wochenende landet im Zielmonat; Tages-Slot Ende 12:00 − 30 min → 09:30Z; dieselbe Zeit aus Monat und Tag erscheint einmal; mehr als `days` Tage entfällt; Sommerzeit mit `zoneinfo.ZoneInfo("Europe/Berlin")`: 02:30 am 2026-03-29 wirft nicht und liefert genau einen Stempel; `monthly=None` und keine Slots → `[]`.
- [ ] **Step 2:** `pytest tests/test_send_reminder.py -k upcoming -q` — Expected: FAIL.
- [ ] **Step 3: Implementiere** über die Monate, die das Fenster berührt; naive lokale Zeit → UTC mit `tz` bzw. `astimezone()`; Stempel mit `%Y-%m-%dT%H:%M:%SZ`.
- [ ] **Step 4:** Run — Expected: PASS. **Step 5: Commit** `feat(send-reminder): Sende-Zeitpunkte für die nächsten 62 Tage (#331)`.

### Task 3: `mobile_reminders.py` — Block und Geheimnis

**Files:** Create `src/mobile_reminders.py`, `tests/test_mobile_reminders.py`; Modify `tests/test_mobile_contract.py`, `tests/test_type_annotations.py` (Whitelist)

**Interfaces:**
- Produces: `build_block(settings, reservation_store, now: datetime.datetime, *, tz=None) -> dict` mit `{"reservation": {"enabled": bool, "minutes_before": int}, "send": {"enabled": bool, "at": list[str]}}`. `reservation.enabled` = `mobile_push_enabled ∧ mobile_push_reservation ∧ reservations_enabled`; `minutes_before` = `reminder_minutes_before` (0–1440, sonst 15); `send.enabled` = `mobile_push_enabled ∧ mobile_push_send ∧ (send_reminder_enabled ∨ (send_reminder_reservations_enabled ∧ reservations_enabled))`; `at` = `upcoming_send_times(...)` (leer, wenn `enabled` falsch). Ohne `reservation_store` keine Tages-Slots.
- Produces: `parse_push(raw: object) -> str | None` — `raw["relay_secret"]`, genau 43 Zeichen `[A-Za-z0-9_-]`, sonst `None`.
- Produces: `RELAY_SECRET_RE`.

- [ ] **Step 1: Tests.** Block: Schalter aus → beide `enabled` falsch, `at == []`, Block trotzdem vollständig; alle Kombinationen der Haken; Reservierungen aus → keine Reservierungs-Erinnerung und keine Tages-Zeiten; `at` enthält Monats- und Tages-Zeiten gemischt und sortiert; `parse_push`: gültig, 42/44 Zeichen, falsche Zeichen, Nicht-Text, `None`, fehlendes Feld. Contract: `reminders-contract.json` — `response_reminders` hat dieselbe Form wie `build_block` (gleiche Schlüssel, `at` gültige Stempel), `request_push.relay_secret` besteht `parse_push`.
- [ ] **Step 2:** Run `pytest tests/test_mobile_reminders.py tests/test_mobile_contract.py -q` — Expected: FAIL.
- [ ] **Step 3: Implementiere** beide Funktionen; Markierte Tages-Slots aus `reservation_store.get_all_raw()` über `send_reminder.marked_reminder_dates`/Slots mit `send_reminder_minutes`.
- [ ] **Step 4:** Run — Expected: PASS. **Step 5: Commit** `feat(mobile): reminders-Block und Relay-Geheimnis (#331)`.

### Task 4: Abgleich — `push` lesen, `reminders` antworten

**Files:** Modify `src/mobile_sync.py` (`SyncRequest.relay_secret`, `parse_request`, `build_response(..., reminders=None)`, `perform_sync`), `src/mobile_routes.py` (Sync-Handler), `tests/test_mobile_sync.py`, `tests/test_mobile_routes.py`, `src/CLAUDE.md` (später, Task 9)

**Interfaces:**
- Consumes: `build_block`, `parse_push` (Task 3).
- Produces: `SyncRequest.relay_secret: str | None = None`; die Antwort trägt **immer** `reminders` (auch ausgeschaltet); `perform_sync` rechnet den Block **nach** dem Anwenden (mit `now` als lokale Desktop-Zeit); der Handler ruft nach Erfolg `MobileContext.relay_store.set(device_id, secret)`, wenn ein gültiges Geheimnis kam und es sich ändert.

- [ ] **Step 1: Tests.** Antwort enthält `reminders` auch bei `mobile_push_enabled=False`; `parse_request` übernimmt ein gültiges Geheimnis, verwirft ein ungültiges **ohne** Fehler und ohne es zu loggen; eine Anfrage ohne `push` (Vorgänger-Fixture `compat`) bleibt gültig; der Handler speichert das Geheimnis dem Gerät aus dem **Token** zu (nie aus dem Body); gleiches Geheimnis zweimal → ein Schreibvorgang.
- [ ] **Step 2:** Run `pytest tests/test_mobile_sync.py tests/test_mobile_routes.py -q` — Expected: FAIL.
- [ ] **Step 3: Implementiere** die Felder; `MobileContext` bekommt `relay_store`.
- [ ] **Step 4:** Run — Expected: PASS (auch `tests/test_mobile_contract.py`). **Step 5: Commit** `feat(mobile): Abgleich trägt reminders und nimmt das Relay-Geheimnis an (#331)`.

### Task 5: `mobile_relay_store.py` — Geheimnisse gehärtet ablegen

**Files:** Create `src/mobile_relay_store.py`, `tests/test_mobile_relay_store.py`; Modify `src/removal.py`, `installer.iss`, `.gitignore`, `src/main.py`, `src/ui.py`, `tests/test_removal.py`, `tests/test_secret_writers.py`, `tests/test_type_annotations.py`

**Interfaces:**
- Produces: `class RelayStore(filepath: str = "mobile_relay.json", lock: threading.RLock | None = None)` mit `get(device_id) -> str | None`, `set(device_id, secret) -> bool` (`True` nur bei Änderung), `remove(device_id) -> str | None` (gibt das entfernte Geheimnis zurück), `retain(ids: Iterable[str]) -> None`, `known_ids() -> set[str]`. Datei über `secure_file.write_secret_json`; kaputte Datei → `load_json_or_quarantine`; Datensätze mit ungültigem Geheimnis werden beim Laden übersprungen.

- [ ] **Step 1: Tests** gegen eine Temp-Datei: Hin und zurück, `set` mit gleichem Wert schreibt nicht (Zähler am Schreiber), `retain` entfernt fremde, kaputte Datei wird quarantäniert, ungültiger Wert wird beim Laden verworfen, Datei hat Besitzer-Rechte (`0600` unter POSIX). `test_removal`: Datei steht in `CREDENTIAL_FILES` und in `installer.iss`; `test_secret_writers`: der neue Schreiber ist eingetragen.
- [ ] **Step 2:** Run — Expected: FAIL.
- [ ] **Step 3: Implementiere**; `main.py` baut den Store, `App(mobile_relay_store=…)` reicht ihn an `MobileService`/`MobileContext`.
- [ ] **Step 4:** Run `pytest -q` — Expected: PASS. **Step 5: Commit** `feat(mobile): gehärteter Speicher für Relay-Geheimnisse (#331)`.

### Task 6: `push_relay.py` und Widerruf

**Files:** Create `src/push_relay.py`, `tests/test_push_relay.py`; Modify `src/mobile_service.py` (`revoke`, `revoke_all`, `prune`-Pfad), `tests/test_mobile_service.py`, `tests/test_mobile_contract.py`

**Interfaces:**
- Produces: `RELAY_URL` (gleich der PWA-Konstante; Test liest `pwa/relay-client.js`), `delete_device(secret: str, *, opener=urllib.request.urlopen, timeout: float = 10.0) -> bool` — `DELETE /v1/device` mit Bearer, **wirft nie**, `True` nur bei 2xx. Logt ohne Geheimnis und ohne URL-Parameter.
- Changes: `MobileService.revoke(device_id)` / `revoke_all()` holen das Geheimnis (`relay_store.remove`/`retain([])` → entfernte Werte), rufen **nach** Freigabe der Gerätesperre `delete_device` je Geheimnis (Worker!) und räumen den Schlüsselbund wie bisher.

- [ ] **Step 1: Tests.** `delete_device`: Methode/Pfad/Header über einen Fake-`opener`, 204 → `True`, `HTTPError` 401/429/500 → `False`, `URLError`/`TimeoutError` → `False`, nichts davon wirft, das Geheimnis steht in keiner Logzeile (`caplog`). Contract: `RELAY_URL` stimmt mit der Konstante in `pwa/relay-client.js` überein. Service: `revoke` löscht das lokale Geheimnis und ruft `delete_device` einmal mit ihm; scheitert der Aufruf, ist das Gerät trotzdem widerrufen; `revoke_all` ruft es je Gerät; ein Gerät ohne Geheimnis ruft nichts.
- [ ] **Step 2:** Run — Expected: FAIL.
- [ ] **Step 3: Implementiere** (`urllib.request.Request(..., method="DELETE")`, kein Redirect-Folgen wie `webhook.py`).
- [ ] **Step 4:** Run — Expected: PASS. **Step 5: Commit** `feat(mobile): Widerruf löscht das Relay-Objekt (#331)`.

### Task 7: Reiter „Erinnerungen“ — Abschnitt „Handy“

**Files:** Modify `src/dialogs/settings_dialog/tab_reminders.py`, `src/dialogs/settings_dialog/dialog.py` (übergibt `show_phone`), `src/dialogs/settings_dialog/tab_rules.py` (Texte), `tests/test_tab_rules.py`

**Interfaces:**
- Produces: `phone_hint(*, device_count: int, enabled: bool) -> str` in `tab_rules.py` (Tk-frei): ohne gekoppeltes Gerät „Noch kein Handy gekoppelt (Einstellungen → Mobil).“, mit „N Handy(s) gekoppelt.“; Abschnitt „Handy“ mit Schalter „Auch aufs Handy senden“ (`mobile_push_enabled`), abhängig darunter „Reservierungs-Erinnerung“, „Sende-Erinnerung“, „Toast am Desktop unterdrücken, wenn aufs Handy gesendet wird“; die Zeile „Minuten vor Ende“ ist frei, sobald Toast **oder** Handy-Reservierung an ist (abgeleitete `BooleanVar`, Muster `shift_active`).

- [ ] **Step 1: Tests** für `phone_hint` (0, 1, 2 Geräte; widerrufene zählen nicht) und dass `reminders_updates` die vier Schlüssel schreibt (Task 1).
- [ ] **Step 2:** Run `pytest tests/test_tab_rules.py -q` — Expected: FAIL.
- [ ] **Step 3: Implementiere** `phone_hint` und den Abschnitt (nur mit Handy-Instanz); UI wird nicht automatisiert getestet (Scope-Grenze). Von Hand: App starten, Abschnitt prüfen, speichern, neu öffnen.
- [ ] **Step 4:** Run — Expected: PASS. **Step 5: Commit** `feat(mobile): Abschnitt „Handy“ im Reiter Erinnerungen (#331)`.

### Task 8: Toast nur unterdrücken, wenn das Handy ihn abdeckt

**Files:** Modify `src/reminder_scheduler.py`, `src/send_reminder_scheduler.py`, `src/ui.py`, `src/mobile_reminders.py` (`phone_covers`), `tests/test_mobile_reminders.py`, `tests/test_reminder_scheduler.py`, `tests/test_send_reminder_scheduler.py`

**Interfaces:**
- Produces: `phone_covers(settings, relay_ids: Collection[str], kind: Literal["reservation", "send"]) -> bool` — wahr nur, wenn `mobile_push_enabled ∧ mobile_push_suppress_toast ∧` Art angehakt (und Reservierungen für „reservation“) `∧ relay_ids` nicht leer. Beide Scheduler bekommen einen Parameter `phone_covers: Callable[[str], bool]` (Standard: immer falsch) und zeigen den Toast nicht, wenn er wahr liefert; `App` übergibt eine Funktion über `MobileService`/`RelayStore.known_ids()` **gefiltert auf nicht widerrufene Geräte**.

- [ ] **Step 1: Tests.** `phone_covers`: jede fehlende Bedingung → falsch (Schalter aus, Unterdrücken aus, Art abgehakt, keine Geräte, Reservierungen aus); Scheduler: Toast bleibt aus, wenn `phone_covers` wahr ist, sonst kommt er; der Fired-Marker (Monats-Kanal) wird **trotzdem** gesetzt (sonst käme der Toast nach dem Ausschalten des Handys nachträglich).
- [ ] **Step 2:** Run — Expected: FAIL.
- [ ] **Step 3: Implementiere**; `tests/test_mobile_wiring.py` um die neue Verdrahtung erweitern.
- [ ] **Step 4:** Run `pytest -q` — Expected: PASS. **Step 5: Commit** `feat(mobile): Desktop-Toast entfällt, wenn das Handy ihn abdeckt (#331)`.

### Task 9: Doku und README

**Files:** Modify `src/CLAUDE.md` (Abschnitt `mobile_sync.py`, neue Module), `CLAUDE.md` (Struktur: `mobile_reminders.py`, `mobile_relay_store.py`, `push_relay.py`), `pwa/CLAUDE.md` („PR 4 von #331“ → erledigt, Fixture-Umzug), `docs/known-limitations.md` (Relay-Objekt nach `prune`, Handy-Toast), `README.md` (`*(ab --VERSION--)*` bei der Handy-Funktion)

- [ ] **Step 1:** Abschnitte schreiben; Festlegungen aus diesem Plan übernehmen.
- [ ] **Step 2:** `pytest tests/test_claude_md_claims.py -q` und `pytest -q`, `ruff check .`, `cd pwa && node --test` — Expected: alles grün.
- [ ] **Step 3: Commit** `docs: Handy-Erinnerungen am Desktop (#331)`.
