# Testbenachrichtigung und Kalender-Markierung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Ein Knopf „Testbenachrichtigung“ am Desktop (Einstellungen → Mobil, je gekoppeltes Gerät) **und** in der Web-App (Einstellungen → Verbindung) schickt über eine neue Relay-Route sofort einen Push, ohne den Zeitplan des Handys anzufassen. (2) Ein farbiger Punkt im Kalender samt Tooltip-Zeile zeigt Tage, an denen die Sende-Erinnerung an einer Reservierung hängt. Beides in einem PR (Folgearbeit zu #331).

**Architecture:** `relay/` bekommt `POST /v1/test` (Durable Object sendet sofort, mit Abkühlzeit je Gerät). Die PWA erkennt die feste Test-Nutzlast im Service Worker und zeigt eine eigene Meldung; ihr `RelayClient` und der Desktop (`push_relay.send_test`, `MobileService.send_test`) rufen die Route auf. Der Kalender-Punkt ist ein zweiter Canvas-Punkt neben dem violetten Reservierungs-Punkt; der Tooltip-Text kommt aus einer reinen Funktion.

**Tech Stack:** Cloudflare Worker/Durable Object (`node --test`), PWA (`node --test`), Python 3.12 + Tkinter, `pytest`.

**Spec:** Issue #340 (Befund, Entscheidungen: Weg B, Bernstein, Web-App-Knopf gleich mit) und `docs/superpowers/specs/2026-10-21-pwa-push-erinnerungen-design.md`.

## Global Constraints

- Deutsch in Doku, Kommentaren und Texten; TDD; Catch-all-Regeln (`tests/test_catch_all_handlers.py`); Tk-freie Module vollständig annotiert (`tests/test_type_annotations.py`).
- Der Relay loggt nichts (`relay/CLAUDE.md`); das Relay-Geheimnis steht in keinem Log und keinem Fehlertext (Desktop wie PWA).
- Jede neue Laufzeitdatei der PWA steht in `PRECACHE`; Konstanten, die Relay, PWA und Desktop teilen, hält ein Test zusammen (Muster `RELAY_URL`).
- Der Relay ist nie Voraussetzung: jeder Fehler des Testaufrufs bleibt ein Text im Dialog, nie eine Ausnahme.
- Kalender: Pixelangaben durch `px()` (`tests/test_pixel_scaling.py`); genau **ein** `attach_tooltip` pro Zelle; Farben aus `theme/palette.py`.
- Reihenfolge beim Ausrollen: erst Relay (`npx wrangler deploy`, durch den Maintainer), dann Web-App (Pages) und Desktop. Ein Desktop oder eine Web-App gegen einen alten Relay bekommt `404 not_found` und meldet das als „Relay kennt den Test noch nicht“.
- Die Nutzertexte der Meldungen stehen **einmal** je Seite (Desktop `tab_rules.py`, PWA `messages.js`); die Fehlercodes des Relays sind der Vertrag zwischen den Seiten.

## Review Focus

- Zweimal kurz hintereinander testen: die zweite Anfrage bekommt `429 too_soon` und löst keinen weiteren Push aus; ein anderes Gerät ist davon unberührt.
- Gerät ohne Abo am Relay (`409 no_subscription`) und mit totem Abo (`410 gone`, das Objekt räumt sich dabei auf) — der Test darf keinen Zeitplan ändern oder löschen.
- Der Test-Push darf einen vorhandenen Zeitplan weder ersetzen noch den Alarm verstellen.
- Eine ältere Web-App, die die Test-Nutzlast nicht kennt, zeigt die allgemeine Benachrichtigung (Chrome verlangt eine sichtbare), nie nichts.
- Kalender: Tag mit Reservierung **ohne** Markierung zeigt nur den violetten Punkt; mit Markierung zwei Punkte; Funktion in den Einstellungen aus → kein Bernstein-Punkt; Markierung an einem gelöschten Slot oder Tombstone → kein Punkt; Feiertags-, Urlaubs- und leere Zellen tragen den Punkt wie den violetten.
- macOS: ✕ oben links bleibt frei, Hover färbt beide Punkte mit, Skalierung 200 %.

## Festlegungen (meine, im PR sichtbar zu machen)

- **Test-Nutzlast:** der feste Text `zeiterfassung-test` (`TEST_PAYLOAD`), ohne Verschlüsselung. Er verrät nichts (Push-Inhalte sind an das Abo verschlüsselt, nur der Relay mit dem VAPID-Schlüssel kann senden), und der Service Worker erkennt ihn vor dem Entschlüsseln.
- **Abkühlzeit:** 10 Sekunden je Gerät im Durable Object (`LIMITS.testCooldownSeconds`), zusätzlich zum Rate-Limit je Adresse.
- **Antwortcodes von `POST /v1/test`:** `204` gesendet, `409 no_subscription`, `410 gone` (Abo tot, Objekt geräumt), `429 too_soon`, `502 push_failed` (Push-Dienst nahm es nicht an: `retry`/`drop`).
- **Texte** (Desktop und Web-App gleich): gesendet „Testbenachrichtigung gesendet. Sie sollte in wenigen Sekunden erscheinen.“; `no_subscription` „Der Relay kennt dieses Gerät nicht (mehr). Am Handy die Benachrichtigungen aus- und wieder einschalten.“; `gone` „Das Abo des Handys ist abgelaufen. Am Handy die Benachrichtigungen neu erlauben.“; `too_soon` „Bitte einen Moment warten und dann erneut versuchen.“; `rate_limited` „Zu viele Anfragen an den Relay, später erneut versuchen.“; `unknown_route` „Der Relay kennt den Test noch nicht (muss neu ausgerollt werden).“; `offline` „Der Relay ist nicht erreichbar.“; `push_failed` „Der Push-Dienst hat die Nachricht nicht angenommen.“
- **Titel der Test-Meldung:** „Testbenachrichtigung“, Text „Der Weg Relay → Handy funktioniert.“, `tag: test`.
- **Kalender-Farbe:** `REMINDER_ACCENT = "#fbbf24"` (Bernstein). Punkt links neben dem violetten (gleiche Größe, Abstand `px(3)`), nur wenn `send_reminder_enabled` ∧ `send_reminder_reservations_enabled` und ein Slot einen gültigen `send_reminder_minutes` (0–120) trägt.
- **Tooltip-Zeile:** `Erinnerung ans Verschicken: <N> min vor Ende (<HH:MM> Uhr)` unter dem Abschnitt „Reservierung:“; bei N = 0 `zum Ende (<HH:MM> Uhr)`.

---

### Task 1: Relay — `POST /v1/test`

**Files:** Modify `relay/src/device.js`, `relay/src/worker.js` (ROUTES), `relay/src/validate.js` (`LIMITS`), `relay/src/push.js` (`TEST_PAYLOAD`), `relay/test/device.test.js`, `relay/test/worker.test.js`, `relay/CLAUDE.md`, `relay/README.md`

**Interfaces:**
- Produces: `export const TEST_PAYLOAD = 'zeiterfassung-test'` in `push.js`; `LIMITS.testCooldownSeconds = 10`; Route `POST /v1/test` (Bearer wie die übrigen, kein Body nötig, ein Body wird gelesen und verworfen) mit den Codes aus „Festlegungen“.
- Consumes: `sendPush(subscription, blob, env)` → `'ok' | 'gone' | 'retry' | 'drop'` (vorhanden).

- [ ] **Step 1: Tests.** `device.test.js`: `ok` → `204`, der Fake-`send` bekommt genau `TEST_PAYLOAD`, `items` und Alarm unverändert; ohne Abo `409 no_subscription` und kein Sendeaufruf; `gone` → `410 gone` und `storage` leer (Objekt geräumt, Alarm weg); `retry`/`drop` → `502 push_failed` und Abo bleibt; zweite Anfrage innerhalb von 10 s → `429 too_soon` ohne Sendeaufruf, nach 10 s wieder `204`; ein wirfender `send` → `502`; die Abkühlzeit steht nur im Speicher dieses Objekts (zwei Objekte unabhängig). `worker.test.js`: `POST /v1/test` wird wie die übrigen geroutet (Hash des Geheimnisses, 401 ohne Bearer, `GET` → 405 mit `Allow: POST`, Preflight erlaubt `POST`), `TEST_PAYLOAD` ist ein nicht leerer Text unter `LIMITS.maxBlob`.
- [ ] **Step 2:** `cd relay && node --test` (Node 22) — Expected: FAIL.
- [ ] **Step 3: Implementiere** `#test(request)` in `device.js` (Body lesen, `lastTest` im Speicher, Ergebnis abbilden; bei `gone` nur räumen, wenn das Abo noch dasselbe ist, wie in `#run`); Route in `ROUTES`.
- [ ] **Step 4:** Run — Expected: PASS (alle Relay-Tests). `relay/CLAUDE.md` und `relay/README.md` um die Route ergänzen.
- [ ] **Step 5: Commit** `feat(relay): Testroute POST /v1/test (#340)`.

### Task 2: Web-App — Testknopf und Test-Meldung

**Files:** Modify `pwa/relay-client.js`, `pwa/push-message.js`, `pwa/sw.js`, `pwa/messages.js` (oder `view-model.js`, wo `pushModel` liegt), `pwa/view-model.js`, `pwa/views.js`, `pwa/app.js`, `pwa/test/relay-client.test.js`, `pwa/test/push-message.test.js`, `pwa/test/view-model.test.js`, `pwa/test/shell.test.js`, `tests/test_push_relay.py` (Vertragstest der Konstante)

**Interfaces:**
- Produces: `RelayClient.sendTest(secret) → Promise<void>` (wirft `RelayError` mit `kind` aus `'no_subscription' | 'gone' | 'too_soon' | 'rate_limited' | 'unknown_route' | 'offline' | 'push_failed' | 'unauthorized' | 'server'`); `TEST_PAYLOAD` (gleicher Text wie am Relay); `describeTest() → {title, body, tag}`; `testResultText(kind) → string` (Texte aus „Festlegungen“); `pushModel` bekommt `canTest` (nur Zustand `on` mit Geheimnis).
- Consumes: `RELAY_URL`, `RelayError` (vorhanden).

- [ ] **Step 1: Tests.** `relay-client.test.js`: `POST /v1/test` mit Bearer und ohne Body; `204` → Erfolg; `410`/`409`/`429 too_soon`/`429 rate_limited` (unterschieden am Body `error`)/`404`→`unknown_route`/`502`→`push_failed`/Netzfehler → `offline`; Fehlertexte ohne Geheimnis. `push-message.test.js`: `describeTest()` liefert die Texte und `tag: 'test'`; alle neun Ergebnistexte; eine Konstanten-Gleichheit gegen `relay/src/push.js` (Regex auf `TEST_PAYLOAD`, wie in `tests/test_push_relay.py` für `RELAY_URL`). `view-model.test.js`: `pushModel` liefert `canTest` nur bei `on` und gesetztem Geheimnis. `shell.test.js`: `sw.js` prüft die Test-Nutzlast **vor** dem Entschlüsseln und zeigt in jedem Fall eine Benachrichtigung.
- [ ] **Step 2:** `cd pwa && node --test` — Expected: FAIL.
- [ ] **Step 3: Implementiere** `sendTest`, die beiden Funktionen, den Zweig im `push`-Handler von `sw.js` (`event.data.text() === TEST_PAYLOAD` → `describeTest()`), den Knopf „Testbenachrichtigung senden“ in `pushSection` (Zustand „sendet …“, Ergebnistext im Statusfeld) und `App.sendTestPush()` (liest das Geheimnis aus der Meta, fängt jeden Fehler ab).
- [ ] **Step 4:** Run `node --test` — Expected: PASS. Von Hand: `python scripts/pwa_devserver.py`, Benachrichtigungen einschalten, Knopf drücken (setzt einen deployten Relay mit Task 1 voraus).
- [ ] **Step 5: Commit** `feat(pwa): Testbenachrichtigung in den Einstellungen (#340)`.

### Task 3: Desktop — `push_relay.send_test`, Dienst und Knopf im Reiter „Mobil“

**Files:** Modify `src/push_relay.py`, `src/mobile_service.py`, `src/dialogs/settings_dialog/tab_mobile.py`, `src/dialogs/settings_dialog/tab_rules.py`, `tests/test_push_relay.py`, `tests/test_mobile_service.py`, `tests/test_tab_rules.py`, `tests/test_mobile_tab_wiring.py`

**Interfaces:**
- Produces: `push_relay.send_test(secret, *, opener=None, timeout=TIMEOUT_S, base_url=RELAY_URL) -> str` — liefert genau einen von `"ok" | "no_subscription" | "gone" | "too_soon" | "rate_limited" | "unknown_route" | "offline" | "push_failed" | "unauthorized" | "server"`, **wirft nie**, loggt weder Geheimnis noch Ausnahmetext.  Der Desktop sendet keine Nutzlast, die kennt nur der Relay.
- Produces: `MobileService.send_test(device_id: str) -> str` — wie oben, plus `"no_secret"`, wenn das Gerät kein Geheimnis hat (Worker, kein Aufruf am Relay); `MobileService.can_test(device_id) -> bool` (nur Speicher, UI-Thread).
- Produces: `tab_rules.test_push_text(kind: str) -> str` (die Texte aus „Festlegungen“ plus `no_secret`: „Das Handy hat Benachrichtigungen noch nicht eingeschaltet oder noch nicht abgeglichen.“).
- Consumes: `MobileRelayStore.get` (vorhanden).

- [ ] **Step 1: Tests.** `push_relay`: je Statuscode/Body der Relay-Antwort die richtige Art (204 → `ok`; 409 → `no_subscription`; 410 → `gone`; 429 mit `too_soon` bzw. `rate_limited`; 404 → `unknown_route`; 401 → `unauthorized`; 502 → `push_failed`; übrige 5xx → `server`), Netzfehler/Zeitüberschreitung → `offline`, Methode `POST` ohne Body, Bearer-Header, kein Redirect, nichts im Log (`caplog`); die Konstante `TEST_PAYLOAD` des Relays steht **nicht** im Desktop-Code. `MobileService`: `send_test` mit Geheimnis ruft `send_test` einmal (Fake), ohne Geheimnis `no_secret` und keinen Aufruf, nicht unter `devices_lock`, unbekanntes Gerät `no_secret`; `can_test` spiegelt `known_ids`. `tab_rules`: alle Arten haben einen Text, kein Text enthält ein Geheimnis-Muster. `test_mobile_tab_wiring`: der Knopf ist verdrahtet und läuft über den Runner.
- [ ] **Step 2:** `pytest tests/test_push_relay.py tests/test_mobile_service.py tests/test_tab_rules.py tests/test_mobile_tab_wiring.py -q` — Expected: FAIL.
- [ ] **Step 3: Implementiere** die Funktionen; im Reiter ein Knopf „Testbenachrichtigung“ neben „Widerrufen“ (aktiv nur bei gewähltem Gerät mit `can_test`), Aufruf im Worker, Ergebnis als Text in der Statuszeile des Reiters (vorhandene Meldezeile nutzen, nicht als Modal).
- [ ] **Step 4:** Run — Expected: PASS. Von Hand: Reiter öffnen, Knopf drücken (setzt den deployten Relay voraus).
- [ ] **Step 5: Commit** `feat(mobile): Testbenachrichtigung im Reiter Mobil (#340)`.

### Task 4: Kalender — Punkt und Tooltip für die Sende-Erinnerung

**Files:** Modify `src/theme/palette.py` (`REMINDER_ACCENT`), `src/theme/__init__.py` (Re-Export), `src/send_reminder.py` (`marked_slot`, `reminder_tooltip_line`), `src/grid_renderer.py` (`_add_reminder_marker`, `_build_tooltip_text`, `_hover`), `tests/test_send_reminder.py`, `tests/test_grid_tooltip*.py` (passende Datei suchen: `grep -ln _build_tooltip_text tests`), `tests/test_ui_hover.py`

**Interfaces:**
- Produces: `send_reminder.marked_slot(slots: Iterable[Mapping]) -> tuple[str, int] | None` — `(Ende "HH:MM", Minuten)` des ersten Slots mit gültigem `send_reminder_minutes` (0–120, kein `bool`), sonst `None`; `send_reminder.reminder_tooltip_line(end: str, minutes: int) -> str` (Text aus „Festlegungen“); `GridRenderer._build_tooltip_text(..., reminder=None)` mit `reminder = (end, minutes)` hängt die Zeile unter „Reservierung:“.
- Produces: `GridRenderer._reminder_marker_active(reservation) -> tuple[str, int] | None` — nur wenn `send_reminder_enabled` ∧ `send_reminder_reservations_enabled` ∧ Reservierung vorhanden.

- [ ] **Step 1: Tests.** `marked_slot`: erster gültiger Slot, `None` ohne Markierung, `True`/`"5"`/`-1`/`121`/`None` ungültig; `reminder_tooltip_line`: `15` → „Erinnerung ans Verschicken: 15 min vor Ende (17:20 Uhr)“ aus Ende `17:35`, `0` → „zum Ende (17:35 Uhr)“; `_build_tooltip_text` mit und ohne `reminder`, Reihenfolge unter „Reservierung:“, kein Eintrag ohne Reservierung; `_hover` färbt den neuen Marker mit (`_reminder_marker`); `tests/test_pixel_scaling.py` bleibt grün (keine rohen Pixelzahlen).
- [ ] **Step 2:** `pytest tests/test_send_reminder.py tests/test_ui_hover.py -q` und die Tooltip-Testdatei — Expected: FAIL.
- [ ] **Step 3: Implementiere** `marked_slot`/`reminder_tooltip_line` in `send_reminder.py`; in `_build_day_cell` den Marker nach `_add_reservation_marker` setzen (Canvas wie der violette, `place(relx=1.0, x=-(px(3) + box), y=px(3), anchor="ne")`), `_hover`-Attributliste um `_reminder_marker` ergänzen.
- [ ] **Step 4:** Run — Expected: PASS; `pytest -q` und `ruff check .`. Von Hand: Reservierung mit Markierung anlegen, Tag im Monat und in der Woche prüfen, Hover, 200 % Skalierung; macOS: Pre-Release (Label `platform:macos`).
- [ ] **Step 5: Commit** `feat(kalender): Punkt und Tooltip für die Sende-Erinnerung (#340)`.

### Task 5: Doku

**Files:** Modify `CLAUDE.md` (Struktur: `push_relay.py`, `relay/`), `src/CLAUDE.md` (Abschnitt `mobile_*`), `pwa/CLAUDE.md` („Benachrichtigungen“), `relay/CLAUDE.md`, `docs/known-limitations.md`, `README.md` (`*(ab --VERSION--)*` beim Absatz „Erinnerungen aufs Handy“ um den Test erweitern)

- [ ] **Step 1:** Abschnitte schreiben; Festlegungen aus diesem Plan übernehmen; Ausroll-Reihenfolge (Relay zuerst) in `relay/README.md` unter „Aktualisieren“ nennen.
- [ ] **Step 2:** `pytest -q`, `ruff check .`, `cd pwa && node --test`, `cd relay && node --test` (Node 22), `pytest tests/test_claude_md_claims.py -q` — Expected: alles grün.
- [ ] **Step 3: Commit** `docs: Testbenachrichtigung und Sende-Erinnerung im Kalender (#340)`.
