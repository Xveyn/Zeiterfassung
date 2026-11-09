# PWA: Trennen und lokale Daten löschen — Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Handy-PWA kann sich über den Relay vom Desktop abmelden und danach alle lokalen Daten löschen; der Desktop widerruft das Gerät und meldet es dem Nutzer.

**Architecture:** Neue verschlüsselte Route `POST /v1/unpair` im Umschlag des Abgleichs (gleiche Auth, `seq`, Token). Über den Relay legt die PWA die Anfrage in den `req`-Slot der Box und wartet nur auf das `ok` des Relays; der Desktop holt sie beim Verbinden ab. Die PWA-Ablaufsteuerung (`unpair.js`) und das Anzeigemodell der Rückfrage (`view-model.js`) sind DOM-frei und in Node getestet; Dialog und Verdrahtung kommen zuletzt.

**Tech Stack:** Python (pytest, Tk-freie Module), PWA in reinem JavaScript ohne Build (`node --test` in `pwa/`).

**Spec:** `docs/superpowers/specs/2026-11-09-pwa-trennen-design.md` (Issue #499). Der Abschnitt „Festlegungen des Entwurfs“ ist Teil der Anforderungen.

## Global Constraints

- `PROTOCOL` bleibt `2`, das Sync-Dokument bekommt **kein** Schema-Update; alles ist additiv.
- Route `POST /v1/unpair`, Fähigkeit `unpair: true` als Feld der Sync-Antwort (Muster `reservation_pause`).
- Datensatz-Felder `revoked_by` (Wert `"device"`) und `revoked_at` (Zeitstempel `YYYY-MM-DDTHH:MM:SSZ`), additiv.
- Rückfrage-Texte: „Ja, trennen und löschen“, „Trotzdem löschen“, „Erneut abgleichen“, „Abbrechen“; „Abbrechen“ ist vorausgewählt (`autofocus`).
- Nie in Log, Toast oder Dialog: Token, Geräte-ID, Box- oder Push-Geheimnis; nur der bereinigte Gerätename.
- PWA: DOM nur über `h()` (`dom.js`), kein `innerHTML`; neue Module in `sw-core.js` `PRECACHE` und in der Modulliste von `pwa/CLAUDE.md`.
- Neue Tk-freie Python-Module: Eintrag in der Whitelist von `tests/test_type_annotations.py` und Zeile `# pyright: reportOptionalMemberAccess=true`.
- Jeder Catch-all loggt, meldet oder trägt eine Begründung (`tests/test_catch_all_handlers.py`).
- Kommentare sagen das Warum, keine Geschichte (CLAUDE.md „Kommentare und Docstrings“).

## Review Focus

Eingaben und Lagen, die die Spec nahelegt, die aber leicht durchrutschen (jede hat einen Test in der genannten Task):

1. **Doppelklick auf „Ja, trennen und löschen“** sendet die Abmeldung genau einmal und löscht einmal (Task 6).
2. **Token abgelaufen oder bereits widerrufen** (Desktop antwortet 401): die PWA löscht trotzdem (Task 5/6).
3. **Gerät wurde inzwischen neu gekoppelt:** eine alte Abmeldung mit dem alten Token widerruft das neue Gerät **nicht** (Task 1).
4. **`tray.notify` oder Dialog wirft** (Backend defekt, Fenster zerstört): die Route antwortet trotzdem `ok`, der Widerruf bleibt geschrieben (Task 2/3).
5. **`wipe()` scheitert:** nichts wird als gelöscht gemeldet, der Dialog bleibt mit Fehlertext und freien Knöpfen (Task 6/7).

---

### Task 1: Desktop — Datensatz und Route `POST /v1/unpair`

**Files:**
- Modify: `src/mobile_pairing.py` (neben `revoke`, ca. Z. 268), `src/mobile_store.py` (Datensatz-Prüfung, ca. Z. 80–95), `src/mobile_routes.py` (`MobileContext`, `_sync`, `ROUTES`), `src/mobile_sync.py` (`build_response`, ca. Z. 388)
- Modify: `tests/mobile_phone.py` (Test-Handy), `pwa/test/fixtures/sync-response.json` falls der Vertragstest die neue Antwort-Eigenschaft verlangt
- Test: `tests/test_mobile_pairing.py`, `tests/test_mobile_store.py`, `tests/test_mobile_routes.py`, `tests/test_mobile_sync.py`, `tests/test_mobile_contract.py`

**Interfaces:**
- Produces:
  - `mobile_pairing.revoke_by_device(record: Mapping[str, Any], now: str) -> Record` — wie `revoke`, dazu `revoked_by="device"`, `revoked_at=now`.
  - `MobileContext.on_unpaired: Callable[[str, str], None] = _no_unpaired` — Aufruf `(device_id, name)` nach dem Freigeben aller Sperren.
  - Route `POST /v1/unpair` (nicht öffentlich, Scope `mobile`), Antwort verschlüsselt `{"ok": true}`.
  - Sync-Antwort trägt `"unpair": True` immer (auch ohne Reservierungen).
  - `Phone.unpair_request(self) -> dict[str, Any]` in `tests/mobile_phone.py` (Pfad `/v1/unpair`, Klartext `{}`) und `Phone.open_response(envelope, path)` bzw. eine Pfad-Variante von `open_sync_response`.

- [ ] **Step 1: Failing tests schreiben.** In `tests/test_mobile_routes.py` (Muster der `_sync`-Tests):
  - `test_unpair_revokes_the_device_and_answers_ok_encrypted`: Antwort 200, entschlüsselt `{"ok": True}`, Datensatz `revoked is True`, `revoked_by == "device"`, `revoked_at` gesetzt, `ctx.on_unpaired` einmal mit `(id, name)` aufgerufen.
  - `test_unpair_with_a_replayed_seq_is_409` und `test_unpair_with_an_old_token_after_repairing_is_401` (Neukoppeln vorher: Token-Hash passt nicht; Datensatz bleibt unwiderrufen).
  - `test_unpair_of_a_revoked_or_expired_device_is_401` (`token_revoked` bzw. `token_expired`).
  - `test_unpair_survives_a_failing_on_unpaired`: Callback wirft, Antwort trotzdem 200 und Widerruf geschrieben.
  - `test_unpair_is_refused_while_closing` (wie bei `_sync`).
  In `tests/test_mobile_pairing.py`: `revoke_by_device` setzt die Felder, löscht `previous_token_hash`; `issue_device` auf einem so widerrufenen Datensatz liefert einen Datensatz **ohne** `revoked_by`/`revoked_at` und `revoked is False`. In `tests/test_mobile_store.py`: ein Datensatz mit `revoked_by="device"` lädt; `revoked_by="x"` oder ein Nicht-String macht den Datensatz ungültig (wie die anderen Fremdfelder). In `tests/test_mobile_sync.py`: jede Antwort trägt `unpair is True`.
- [ ] **Step 2: Run:** `pytest tests/test_mobile_routes.py tests/test_mobile_pairing.py tests/test_mobile_store.py tests/test_mobile_sync.py -q` — erwartet FAIL.
- [ ] **Step 3: Implementieren.** `revoke_by_device` und die Store-Prüfung wie oben. Route `_unpair(request, ctx, principal) -> ApiResponse` in `src/mobile_routes.py`: denselben Vorspann wie `_sync` verwenden (Scope, `_refuse_while_closing`, Umschlag, unter `devices_lock`: Datensatz frisch lesen, Schlüssel holen, `_still_valid`, `seq` gegen `last_seq`, `open_envelope` mit Pfad `/v1/unpair`). Den gemeinsamen Teil als Hilfsfunktion herausziehen **nur**, wenn alle bisherigen `_sync`-Tests dabei grün bleiben; sonst den Vorspann kopieren und das im Docstring begründen. Danach `mobile_pairing.with_seq(record, seq)`, `revoke_by_device(seen, now)`, `ctx.devices.save(...)`, Antwort mit `response_key` sealen; **erst nach dem Freigeben des Locks** `_notify_unpaired(ctx, id, name)` (Catch-all mit Begründung, Muster `_notify_paired`). `ROUTES` um `_Route("POST", "/v1/unpair", _unpair)` ergänzen; `build_response` setzt `response["unpair"] = True`.
- [ ] **Step 4: Run** wie Schritt 2 plus `pytest tests/test_mobile_contract.py -q` — erwartet PASS (Fixtures und Vertragstest bei Bedarf nachziehen: `unpair` als boolesches Feld der Antwort, in `pwa/test/fixtures/sync-response.json`).
- [ ] **Step 5: Commit** `feat(mobile): Route /v1/unpair und Widerruf durch das Handy (Refs #499)`.

---

### Task 2: Desktop — Aufräumen nach der Abmeldung (`MobileService`)

**Files:**
- Modify: `src/mobile_service.py` (`__init__` ca. Z. 83–100, `revoke` Z. 327–341, neue Methoden), `src/ui.py` (`MobileContext(...)` ca. Z. 157–170: `on_unpaired` verdrahten kommt in Task 3)
- Test: `tests/test_mobile_service.py`, `tests/test_mobile_relay_e2e.py`

**Interfaces:**
- Consumes: `MobileContext.on_unpaired` (Task 1).
- Produces:
  - `MobileService._on_unpaired(device_id: str, name: str) -> None` — im Kontext des Dienstes (`dataclasses.replace(..., on_unpaired=self._on_unpaired)`): stößt `self._run(self._release_device, device_id)` an, ruft danach den äußeren Callback (`context.on_unpaired`).
  - `MobileService._release_device(device_id: str) -> None` — der Schwanz von `revoke` (Schlüssel entfernen, Relay-Objekte/Push abräumen, `_clean_boxes([id])`), von `revoke` mitbenutzt.
  - `MobileService.dismiss(device_id: str) -> bool` — entfernt den Datensatz, **nur** wenn `revoked_by == "device"`; sonst `False`. Liest/schreibt unter `devices_lock` über `devices.replace_all`.

- [ ] **Step 1: Failing tests.** `test_mobile_service.py`: `test_unpair_releases_key_relay_secret_and_box` (Fake-Schlüsselbund aus `tests/mobile_phone.py`, Box-Aufräumer als Mock: aufgerufen mit `[id]`), `test_unpair_calls_the_outer_callback_with_id_and_name`, `test_revoke_still_cleans_up` (Regression), `test_dismiss_removes_only_device_revoked_records` (normal widerrufenes und aktives Gerät bleiben, `False`). `test_mobile_relay_e2e.py`: **Handy sendet die Abmeldung, danach erst verbindet sich der Desktop**; der Desktop holt sie über den `have`-Cursor ab, widerruft, die Box wird abgeräumt (Aufbau der vorhandenen e2e-Tests im selben File und `tests/fakes_relay.py`).
- [ ] **Step 2: Run:** `pytest tests/test_mobile_service.py tests/test_mobile_relay_e2e.py -q` — erwartet FAIL.
- [ ] **Step 3: Implementieren** wie in Interfaces. Reihenfolge-Hinweis für den Bauenden: die Antwort ist zu diesem Zeitpunkt schon gesealt; ein Aufräumen, das die eigene Relay-Verbindung schließt, bevor die Antwort die Box erreicht, ist harmlos (das Handy wartet im Relay-Weg nie darauf). Thread-Regeln in `src/CLAUDE.md`, „Threading-Modell“, beachten: Schlüsselbund und Netz nur im Worker (`self._run`), nie im Server-Thread.
- [ ] **Step 4: Run** wie Schritt 2 plus `pytest tests/test_relay_service.py tests/test_relay_adapter.py -q` — PASS.
- [ ] **Step 5: Commit** `feat(mobile): Aufräumen nach der Abmeldung durch das Handy (Refs #499)`.

---

### Task 3: Desktop — Hinweis an den Nutzer

**Files:**
- Create: `src/unpair_notice.py`
- Modify: `src/ui.py` (neue Methode `_on_mobile_unpaired`, `MobileContext(on_unpaired=...)`), `tests/test_type_annotations.py` (Whitelist)
- Test: `tests/test_unpair_notice.py`, `tests/test_ui_unpair_notice.py` (Muster der bestehenden UI-Tests ohne echtes Tk, z. B. `tests/test_ui_delete.py`)

**Interfaces:**
- Produces:
  - `unpair_notice_channel(*, window_visible: bool, tray_available: bool) -> str` → `"dialog"` wenn Fenster sichtbar, sonst `"toast"` wenn Tray da, sonst `"log"`.
  - `unpair_notice_text(name: str) -> tuple[str, str]` — (Titel, Text) des Dialogs; `unpair_toast_text(name: str) -> str` — Text des Toasts (≤ 120 Zeichen, Name auf 40 gekürzt, leerer Name → „Ein Handy“).
  - `App._on_mobile_unpaired(device_id: str, name: str) -> None` — über `self._marshal_to_ui` (Aufruf kommt aus Server-/Relay-Thread); Weg wie `_notify_storage_repaired` (`ui.py` ca. Z. 435): `themed_showinfo` / `self._tray.notify(text)` / `logging.getLogger(__name__).info("Handy %s getrennt", device_id)` (nur die ID, nie der Name im Log); jeder Zweig in `try/except` mit Log, damit ein wirfendes `notify` die Kette nicht stört.

- [ ] **Step 1: Failing tests.** `test_unpair_notice.py`: Kanalwahl über alle vier Kombinationen (Fenster × Tray); Texte enthalten den Namen, nie `token`/`secret`; Namen mit Zeilenumbruch, Anführungszeichen, 500 Zeichen und leer; Rückgabetypen. `test_ui_unpair_notice.py`: mit Attrappen für `root.state()`, `_tray`, `themed_showinfo`: richtiger Kanal je Lage; `notify` wirft → kein Fehler nach außen; Plattform-Attrappen (Windows/Linux-Tray vorhanden, macOS ohne Tray → Log) belegen die Tabelle der Spec.
- [ ] **Step 2: Run:** `pytest tests/test_unpair_notice.py tests/test_ui_unpair_notice.py -q` — FAIL.
- [ ] **Step 3: Implementieren** (reine Funktionen, dann die UI-Methode). Verdrahtung: `on_unpaired=self._on_mobile_unpaired` im `MobileContext(...)` in `ui.py`.
- [ ] **Step 4: Run** wie Schritt 2 plus `pytest tests/test_type_annotations.py tests/test_catch_all_handlers.py -q` — PASS.
- [ ] **Step 5: Commit** `feat(ui): Hinweis, wenn sich ein Handy getrennt hat (Refs #499)`.

---

### Task 4: Desktop — Geräteliste zeigt „vom Handy getrennt“

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_rules.py` (`visible_devices` Z. 585–589, `device_row_text`), `src/dialogs/settings_dialog/tab_mobile.py` (`_revoke`, `_sync_buttons`)
- Test: `tests/test_tab_rules.py`, `tests/test_mobile_tab_wiring.py`

**Interfaces:**
- Consumes: `MobileService.dismiss(device_id) -> bool` (Task 2).
- Produces: `tab_rules.is_device_unpaired(record: Mapping[str, Any]) -> bool` (`revoked_by == "device"`); `visible_devices` behält diese Datensätze zusätzlich zu den nicht widerrufenen; `device_row_text` nennt sie „vom Handy getrennt am TT.MM.JJJJ HH:MM“ (`format_iso_datetime`) statt Gültigkeit/Relay-Zustand.

Hinweis: Das war in der Spec als „Geräteliste zeigt es“ vorgesehen, ist aber heute nicht so — `visible_devices` blendet alle widerrufenen aus. Diese Task schließt die Lücke bewusst klein: der Eintrag bleibt sichtbar und lässt sich entfernen.

- [ ] **Step 1: Failing tests.** `test_tab_rules.py`: `visible_devices` behält `revoked_by="device"`, blendet normal Widerrufene weiter aus; `device_row_text` enthält „vom Handy getrennt“ und das Datum, nie Token-Hash oder ID; defekter Zeitstempel → Platzhalter statt Ausnahme. `test_mobile_tab_wiring.py` (vorhandene Attrappen): auf einer getrennten Zeile ruft der Knopf `dismiss` (ohne Rückfrage, Beschriftung „Entfernen“), auf einer aktiven weiter `revoke` mit Rückfrage.
- [ ] **Step 2: Run:** `pytest tests/test_tab_rules.py tests/test_mobile_tab_wiring.py -q` — FAIL.
- [ ] **Step 3: Implementieren.** `_revoke` verzweigt über `is_device_unpaired`; läuft im Worker (`self._runner.run`), Ergebnis wie bisher über `_revoked`.
- [ ] **Step 4: Run** wie Schritt 2 — PASS.
- [ ] **Step 5: Commit** `feat(ui): getrennte Handys in der Geräteliste (Refs #499)`.

---

### Task 5: PWA — Abmelden über Transport und `SyncClient`

**Files:**
- Modify: `pwa/relay-transport.js` (`exchange`/`_attempt`), `pwa/sync.js` (`parseSyncResponse` Z. 105–140, `SyncClient`, neue Methode), `pwa/store.js` (Meta-Vorgaben ca. Z. 49, `applyResponse` ca. Z. 550), `pwa/test/fixtures/sync-response.json`
- Test: `pwa/test/relay-transport.test.js`, `pwa/test/sync.test.js`, `pwa/test/store.test.js`

**Interfaces:**
- Produces:
  - `RelayTransport.exchange({..., ackOnly = false})` — mit `ackOnly: true` löst die Methode beim `ok` des Relays mit `{status: 202, json: null}` auf; Relay unerreichbar bleibt Fehler wie bisher. `LanTransport.exchange` ignoriert die Option.
  - `SyncClient.unpair() -> Promise<{state: 'sent' | 'queued' | 'failed'}>` — wirft nie. `sent`: LAN, Desktop hat `ok` geantwortet; `queued`: Relay hat angenommen; `failed`: alles andere (auch 401/404, Zeitüberschreitung, nicht gekoppelt). Läuft unter derselben Sperre wie der Abgleich (`_runExclusive`-Muster, `SYNC_LOCK`), zählt `seq` wie `_runOnce` **vor** dem Senden hoch, Pfad `/v1/unpair`, Nutzlast `{}`.
  - `parseSyncResponse` liefert `unpair: raw.unpair === true`; Meta-Schlüssel `desktop_unpair` (Vorgabe `false`), gesetzt in `applyResponse` aus `parsed.unpair`.

- [ ] **Step 1: Failing tests.**
  - Transport: `ackOnly` löst beim `ok` mit `{status: 202, json: null}` auf, sendet genau einen `put`, wartet nicht auf `slot`; ohne `ok` (Relay stumm) → wie bisher `unreachable`.
  - `sync.test.js` („Abgleich über den Relay“ und LAN-Fake-Desktop): `unpair()` über LAN mit Antwort `{ok:true}` → `sent`; über Relay mit `ok` → `queued`; Desktop 404/401/Netzfehler → `failed`; `seq` steigt in allen Fällen um 1; zwei gleichzeitige `unpair()`-Aufrufe senden **einmal** (geteilter Lauf wie `sync()`); nicht gekoppelt → `failed` ohne Netz.
  - `store.test.js`: `desktop_unpair` folgt `parsed.unpair`; fehlt das Feld in einer Antwort, wird es `false`.
- [ ] **Step 2: Run:** `cd pwa && node --test test/relay-transport.test.js test/sync.test.js test/store.test.js` — FAIL.
- [ ] **Step 3: Implementieren** wie in Interfaces. Der Umschlag wird mit `_sealedPost` gebaut; für `ackOnly` die Antwort **nicht** öffnen (es gibt keine), sondern über einen neuen Parameter von `_sealedPost` (z. B. `ackOnly`) nach `exchange` den Status prüfen.
- [ ] **Step 4: Run:** `cd pwa && node --test` — alles grün (Fixtures und `compat`-Tests nachziehen, wo die neue Antwort-Eigenschaft sichtbar wird).
- [ ] **Step 5: Commit** `feat(pwa): Abmelden über den Relay im Sync-Client (Refs #499)`.

---

### Task 6: PWA — Ablauf (`unpair.js`) und Anzeigemodell der Rückfrage

**Files:**
- Create: `pwa/unpair.js`
- Modify: `pwa/view-model.js` (neuer Abschnitt neben „Reiter Verbindung“, ca. Z. 381–600), `pwa/sw-core.js` (`PRECACHE`)
- Test: `pwa/test/unpair.test.js`, `pwa/test/view-model.test.js`, `pwa/test/shell.test.js` (prüft den Precache)

**Interfaces:**
- Produces:
  - `performUnpair({ notifyDesktop, disablePush, clearSession, clearDebug, wipe, reload, log }) -> Promise<{ ok: boolean, notified: 'sent' | 'queued' | 'failed' | null, error?: Error }>` — alle Parameter Funktionen. Ablauf in dieser Reihenfolge: `notifyDesktop()` (liefert `unpair()`-Zustand), `disablePush()`, `clearSession()`, `clearDebug()`, `wipe()`, `reload()`. Fehler in den ersten vier Schritten werden über `log(label, error)` gemeldet und stoppen nichts; wirft `wipe()`, ist das Ergebnis `{ok: false, error}` **ohne** `reload()`. Ein zweiter Aufruf, solange der erste läuft, liefert dasselbe Versprechen (kein zweites Senden).
  - `unpairDialogModel({ transport, syncOk, openDays, desktopUnpair }) -> { summary: {kind: 'ok' | 'warn', text: string}, notifiesDesktop: boolean, warnDesktop: string | null, canRetry: boolean, confirmLabel: string }`. Regeln: `openDays > 0` → `summary.kind='warn'` mit Zahl („3 Tage sind noch nicht am Desktop.“, Einzahl „1 Tag …“), `canRetry`, `confirmLabel='Trotzdem löschen'`; sonst `ok` („Alle Tage sind am Desktop gesichert.“) und „Ja, trennen und löschen“. `notifiesDesktop = desktopUnpair && (transport === 'relay' || syncOk)`; ist es `false`, steht in `warnDesktop`: „Der Desktop erfährt nichts vom Trennen. Das Gerät bleibt dort in der Liste, bis du es unter Einstellungen → Mobil entfernst oder widerrufst.“, sonst `null`.

- [ ] **Step 1: Failing tests.** `unpair.test.js`: Reihenfolge der Aufrufe (Protokoll-Array); Fehler in jedem der ersten vier Schritte → die übrigen laufen, `wipe` und `reload` werden gerufen; `wipe` wirft → `ok:false`, `reload` nie; **Doppelaufruf** → `notifyDesktop` und `wipe` je einmal; `notified` gibt den Zustand von `notifyDesktop` weiter (auch bei `failed`, 401 oder 404 wird trotzdem gelöscht). `view-model.test.js`: `unpairDialogModel` in den Lagen: nichts offen/Relay, offen+gescheitert/Relay (benachrichtigt trotzdem), offen+gescheitert/LAN (warnt), `desktopUnpair=false` (warnt, auch bei Relay), Einzahl/Mehrzahl.
- [ ] **Step 2: Run:** `cd pwa && node --test test/unpair.test.js test/view-model.test.js` — FAIL.
- [ ] **Step 3: Implementieren.** `unpair.js` hält keinen DOM und keinen Zustand außer dem laufenden Versprechen; Modul in `PRECACHE` und in die Modulliste von `pwa/CLAUDE.md`.
- [ ] **Step 4: Run:** `cd pwa && node --test` — grün.
- [ ] **Step 5: Commit** `feat(pwa): Ablauf und Anzeigemodell des Trennens (Refs #499)`.

---

### Task 7: PWA — Abschnitt, Rückfrage-Dialog, Verdrahtung

**Files:**
- Modify: `pwa/views.js` (`connectionPanel` Z. 469–510 und neue Funktionen), `pwa/app.js` (`openSettings`-Handler ca. Z. 784, neue Methode `openUnpair`, Konstruktor: Verweis auf den Sitzungs-Slot der Sperre ca. Z. 90), `pwa/app.css`
- Test: `pwa/test/layout.test.js`, `pwa/test/contrast.test.js`, `pwa/test/shell.test.js`, ggf. `pwa/test/view-model.test.js`

**Interfaces:**
- Consumes: `performUnpair`, `unpairDialogModel` (Task 6), `SyncClient.unpair()`, `Store.pendingCount()` und `Store.categoriesDirty()` (nicht übertragene Einträge zählen beides; der Bauende prüft, ob `pendingCount()` Reservierungen mitzählt), `App.disablePush()`, `debugLog.clear()`.
- Produces:
  - `views.unpairSection(handlers)` — Abschnitt „Trennen“ am Ende von `connectionPanel`; Knopf „Trennen und lokale Daten löschen“ ruft `closeThen(() => handlers.unpair())`.
  - `views.unpairDialog(model, handlers) -> HTMLDialogElement` mit `handlers = { retry, confirm, cancel }`; `isRunning()`-Zustand: solange die Bestätigung läuft, sind alle Knöpfe `disabled`, `cancel`-Ereignis (Escape, Zurück-Geste) wird mit `preventDefault()` verworfen und der Klick auf den Hintergrund ignoriert; davor schließen alle drei. `data-focus`-Schlüssel `unpair-cancel`, `unpair-confirm`, `unpair-retry`.
  - `App.openUnpair()` — öffnet den Dialog, startet **sofort** `this.client.sync()` (geteilter Lauf, wartet einen laufenden ab) und zeigt „gleicht ab …“, solange es läuft; berechnet danach das Modell aus `store.pendingCount() + (store.categoriesDirty() ? 1 : 0)`, `meta.transport`, dem Ergebnis des Abgleichs und `meta.desktop_unpair`. Gab es nichts Offenes, entfällt der Abgleich (`openDays === 0` vorher). `retry` wiederholt den Abgleich; `confirm` ruft `performUnpair` mit: `notifyDesktop: () => this.client.unpair().then(r => r.state)`, `disablePush: () => this.disablePush()`, `clearSession: () => sessionSlot.write(null)`, `clearDebug: () => this.debugLog.clear()`, `wipe: () => vault.wipe()`, `reload: () => location.reload()`. Dafür `wipe` und `reload` als Konstruktor-Optionen neben `resetLocalData` hereinreichen (Muster dort, `main()` ca. Z. 1053) statt `resetLocalData` zu verändern. Misslingt `wipe`, zeigt der Dialog „Die lokalen Daten ließen sich nicht löschen. Bitte erneut versuchen.“ und gibt die Knöpfe frei.
  - CSS-Klassen `.unpair-*` (nur Token-Farben aus `app.css`, **keine** `opacity` auf Text, Hover nur in `@media (hover:hover)`); roter Löschknopf mit Kontrast ≥ 4,5:1 (`contrast.test.js` erfasst die Klasse).

- [ ] **Step 1: Failing tests.** `layout.test.js`: `.unpair-*`-Regeln ohne `opacity`; Knopf-Mindesthöhe 44 px; `contrast.test.js`: Text auf dem roten Knopf ≥ 4,5:1. `shell.test.js`: Precache enthält `./unpair.js`. Ein DOM-naher Test des Dialogs ist hier nicht Teil des Repos (UI wird nicht automatisiert getestet, nur Logik); die Verdrahtung prüft der Bauende im Browser (Schritt 4).
- [ ] **Step 2: Run:** `cd pwa && node --test test/layout.test.js test/contrast.test.js test/shell.test.js` — FAIL.
- [ ] **Step 3: Implementieren** wie in Interfaces; Muster für den Dialog: `confirmDialog` (`views.js` Z. 442) und `categoryEditDialog` (Z. 935), geöffnet über `openDialog` (Zurück-Geste).
- [ ] **Step 4: Verifizieren.** `cd pwa && node --test` grün. Im Browser (Playwright, Dev-Server `scripts/pwa_devserver.py --api-port 17655 --address <LAN-IP>`, `python -u`; Hinweise in `pwa/CLAUDE.md`, „Entwickeln und prüfen“): koppeln, Eintrag anlegen, Desktop stoppen → Rückfrage zeigt Warnung mit Zahl; Desktop an → „Alle Tage sind gesichert“; Abbrechen ändert nichts; Bestätigen → Einrichtungs-Screen, IndexedDB leer, am Dev-Desktop ist das Gerät widerrufen (`revoked_by` in `mobile_devices.json` der temporären Ablage). Nicht prüfbar im Dev-Server: Relay-Weg (nur gehostete PWA).
- [ ] **Step 5: Commit** `feat(pwa): Trennen und lokale Daten löschen im Reiter Verbindung (Refs #499)`.

---

### Task 8: Dokumentation und Abschluss

**Files:**
- Modify: `pwa/CLAUDE.md` (Modulliste: `unpair.js`; Abschnitt zum Reiter „Verbindung“ und zum Relay-Abgleich: Abmelden, Fähigkeit `unpair`), `src/CLAUDE.md` (Route, Callback `on_unpaired`, Aufräumweg), `CLAUDE.md` (Modulliste: `src/unpair_notice.py`), `docs/known-limitations.md` (LAN: keine Abmeldung ohne Erreichbarkeit; macOS ohne Tray-Toast; getrenntes Gerät bleibt bis „Entfernen“ in der Liste), `docs/superpowers/specs/2026-11-09-pwa-trennen-design.md` (Abschnitt „Desktop“: Geräteliste ist **neu** gebaut, nicht vorhanden)
- Test: `tests/test_claude_md_claims.py`, gesamte Suiten

- [ ] **Step 1: Dokumente anpassen** (Warum, nicht Geschichte).
- [ ] **Step 2: Gesamtläufe:** `pytest -q`, `cd pwa && node --test`, `ruff check .`, `pyright` — alles grün.
- [ ] **Step 3: Commit** `docs: Trennen und Löschen lokaler Daten (Refs #499)`.
- [ ] **Step 4: PR vorbereiten** (nicht ohne Rückfrage anlegen): `Closes #499`, Plattform-Labels entscheidet der Maintainer; Desktop-Änderung → Hinweis auf CHANGELOG/Release-Entscheidung (neue Funktion → Minor nach Projektregel). Nicht getestet: echtes Handy, iOS, Relay-Weg gegen den gehosteten Relay, echte Toasts auf Windows/macOS/Linux.
