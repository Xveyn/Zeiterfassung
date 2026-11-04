# Relay-Oberfläche (PR 3c/5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Nutzer kann in Einstellungen → Mobil ein Handy über den Relay koppeln (QR mit `#relay=`-Link) und sieht je Gerät den Zustand der Relay-Verbindung.

**Architecture:** Alle Entscheidungen (Texte, Zustandsübersetzung, Zeilentext) liegen Tk-frei in `tab_rules.py` und werden getestet; `tab_mobile.py` und `mobile_pair_dialog.py` bauen nur Widgets darum. Der Koppel-Dialog bekommt einen zweiten Modus „Relay“: Er ruft `RelayService.open_pairing()` im Worker (blockiert: Datei, Netz) statt `MobileService.pairing.open()` und zeigt nur den QR-Code, nie das Box-Geheimnis als Text.

**Tech Stack:** Python 3.12, Tkinter, pytest. Keine neue Abhängigkeit.

**Spec:** `docs/superpowers/specs/2026-11-02-ios-relay-abgleich-design.md` (Abschnitte „Desktop“, „Sicherheit“, „Hinweise für PR 3 (3a–3c) und PR 4“, „PR-Schnitt“ 3c). Vorgänger: `docs/superpowers/plans/2026-11-03-relay-verbindung.md` (3b, gemerged als #420).

## Global Constraints

- UI-Texte deutsch, Datum nur über `time_utils.format_iso_*` (Wurzel-`CLAUDE.md`).
- Neue Dialog-Elemente nur über `theme.*` (`create_dialog`, `Form`, `primary_button`/`secondary_button`); keine dialogspezifischen Stil-Extras. Pixelangaben über `theme.px()`, nie als Modulkonstante ausgewertet; `wraplength=`/`length=` nur mit `px(...)` (`tests/test_pixel_scaling.py`).
- Tk-Code wird nicht automatisiert getestet: Verhalten gehört in `tab_rules.py`, dort mit Tests.
- Docstrings: das Warum und der Vertrag, keine Historie, höchstens acht Zeilen (Wurzel-`CLAUDE.md`, „Kommentare und Docstrings“).
- Das Box-Geheimnis steht nie in Log, Text oder Statusfeld; im Dialog nur als QR-Code.
- `RelayService.open_pairing`/`close_pairing` blockieren (Datei, `delete_box`): **nur im Worker** über `BackgroundTaskRunner.run`, `on_done` im UI-Thread mit `winfo_exists`-/`TclError`-Schutz.
- Kein `&&` in Shell-Befehlen an den Nutzer (PowerShell 5.1); Commits enden mit `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`, Messages `... (Refs #358)`.
- Branch `feat/relay-oberflaeche` (von `master` nach #420). Kein Release vor PR 4: bis dahin versteht die gehostete PWA `#relay=` nicht.

## Entscheidungen, die der Plan trifft

- **Zwei Knöpfe, ein Dialog.** „Gerät koppeln“ bleibt der LAN-Weg; neu „Über Relay koppeln“ in einer **eigenen** Knopfzeile darunter (eine fünfte Schaltfläche in der bestehenden Reihe sprengt die festgenagelte Reiterbreite). Beide öffnen `open_pair_dialog`, der Modus `lan`/`relay` entscheidet.
- **Relay-Knopf aktiv, wenn** `settings.get("mobile_enabled")` (gespeicherter Stand, nicht das ungespeicherte Formular — der Dienst liest die Settings) **und** ein `RelayService` vorhanden **und** kein Widerruf/Test läuft. Er hängt **nicht** an `MobileService.status` (ein Desktop ohne LAN-Adresse darf per Relay koppeln).
- **Ablehnung ohne Grund:** `open_pairing` liefert `None`, ohne zu sagen warum (Dienst geschlossen, Handy-Erfassung aus, Store schreibgeschützt, ungebundener Rest). Der Dialog zeigt dafür **einen** Text (`RELAY_PAIR_REFUSED_TEXT`), der alle Ursachen nennt. Kein neuer Rückgabetyp (YAGNI).
- **Zustand je Gerät:** `RelayService.states_by_device()` (liest nur Speicher, UI-Thread erlaubt) enthält **genau** die Geräte mit Box. Fehlt eine ID dort, ist das Gerät LAN-only und die Zeile trägt keinen Relay-Zusatz.
- **Dev-Server (`scripts/pwa_devserver.py`) bleibt LAN-only.** Er baut keinen `RelayService`; `relay_link` zeigt auf `pwa_constants.PWA_URL` der gehosteten PWA. Ein Relay-QR gegen den lokalen Dev-Server entsteht nicht (der Test auf dem iPhone läuft gegen die gehostete PWA).
- **Kein eigener Zustimmungs-Haken für den Relay.** Der Warntext steht dauerhaft im Koppel-Dialog (Task 3); `mobile_notice_accepted` bleibt der LAN-Hinweis.

## Review Focus

Eingaben/Zustände, die die Spec nur andeutet und die am ehesten stören; jede Zeile hat ihren Test im besitzenden Task.

1. **Handy-Erfassung aus, aber Relay-Knopf gedrückt** (gespeicherter Stand aus): Knopf bleibt deaktiviert, kein Dialog (Task 4, `relay_pair_enabled`).
2. **`open_pairing()` → `None`:** Dialog zeigt den Ablehnungstext, **keinen** QR-Code und **keinen** Code-Text; „Neuer Code“ versucht es erneut (Task 1 Text, Task 3 Verhalten).
3. **Dialog schließen** (X, Escape, nach erfolgreichem Koppeln, „Schließen“): Sitzung wird synchron geschlossen, `close_pairing` genau einmal im Worker; der UI-Thread blockiert nie (Task 3).
4. **Zustand `replaced`** (ein anderer Desktop hat dieselbe Box verdrängt): die Zeile sagt, dass der Abgleich steht, bis neu verbunden wird, nicht nur „getrennt“ (Task 1).
5. **QR-Größe:** der Relay-Link (≈117 Zeichen, 45 Module) passt in `qr.qr_matrix`; ein künftig längerer Link darf nicht lautlos im Text-Fallback landen, der das Geheimnis nicht zeigen darf (Task 3: bei `QrTooLong`/`ImportError` im Relay-Modus **kein** Text-Fallback, nur Hinweis).
6. **Gerät ohne Box** neben einem mit Box: nur das zweite trägt einen Relay-Zusatz (Task 1).

---

### Task 1: Texte und Zeilenlogik in `tab_rules.py`

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_rules.py` (nach `device_row_text`, ~Z. 457–467, und bei den Pair-Konstanten ~Z. 542)
- Test: `tests/test_tab_rules.py`

**Interfaces:**
- Consumes: `src.relay_link.STATE_CONNECTING|CONNECTED|BACKOFF|REPLACED|STOPPED`, `src.relay_service.STATE_OFF` (alle Strings, `tab_rules` importiert sie als Werte, keine Klassen).
- Produces:
  - `RELAY_PAIR_HINT: str` — Text im Relay-Dialog: Verbindung läuft über den Relay-Dienst (Cloudflare); der sieht **Metadaten, nie Inhalte**; **ein fotografierter QR-Code erlaubt das Koppeln von überall im Internet, solange der Code gilt** — nur dem eigenen Handy zeigen.
  - `RELAY_PAIR_REFUSED_TEXT: str` — „Das Koppeln über den Relay ist gerade nicht möglich: Handy-Erfassung aus, Gerätedatei nicht schreibbar oder eine frühere Kopplung wird noch abgeschlossen. Später erneut versuchen („Neuer Code“).“
  - `relay_state_text(state: str) -> str` — deutscher Kurztext je Zustand.
  - `device_row_text(record, now, relay_state: str | None = None) -> str` — **bestehende** Funktion, neuer optionaler Parameter; ohne ihn bitgleich zu vorher.
  - `relay_pair_enabled(*, saved_enabled: bool, has_relay: bool, busy: bool) -> bool`.

- [ ] **Step 1: Failing tests** in `tests/test_tab_rules.py` (Namen und Kernzusicherungen):
  - `test_relay_state_text_covers_every_state`: für `connecting, connected, backoff, replaced, stopped, off` jeweils nichtleerer, **paarweise verschiedener** Text; `relay_state_text("unbekannt")` liefert einen nichtleeren Ersatztext, wirft nicht.
  - `test_the_replaced_state_says_the_sync_is_standing`: `"steht" in relay_state_text("replaced")` und `"verbinden" in …`.
  - `test_a_device_row_without_relay_state_is_unchanged`: `device_row_text(device(), NOW_ISO) == device_row_text(device(), NOW_ISO, None)` und enthält kein „Relay“.
  - `test_a_device_row_with_relay_state_appends_it_after_the_expiry`: `device_row_text(device(), NOW_ISO, "connected")` endet auf `relay_state_text("connected")`-Zusatz und enthält `"Relay"` **nach** `"gültig bis"`.
  - `test_relay_pair_enabled_truth_table`: nur `(True, True, False)` ist `True`; jede andere der 8 Kombinationen `False`.
  - `test_the_relay_pair_hint_warns_about_photographed_qr_and_names_the_limits`: `"fotografiert" in RELAY_PAIR_HINT`, `"Metadaten" in …`, `"Inhalt" in …`, `"unverschlüsselt" not in …`.
  - `test_the_refusal_text_names_all_three_causes`: enthält „aus“, „schreibbar“, „abgeschlossen“.

- [ ] **Step 2:** `python -m pytest tests/test_tab_rules.py -q` → die neuen Tests schlagen fehl (Namen unbekannt).

- [ ] **Step 3: Implementieren** wie oben signiert. Zustandstexte als `dict[str, str]` mit `.get(state, "Zustand unbekannt")`; `device_row_text` hängt `f"  —  Relay: {relay_state_text(relay_state)}"` an, nur wenn `relay_state is not None`. Der Warntext nennt weder Adresse noch Code.

- [ ] **Step 4:** `python -m pytest tests/test_tab_rules.py -q` → alle grün; dazu `python -m ruff check src tests` ohne Meldung.

- [ ] **Step 5: Commit** — `feat(mobile): Relay-Texte und Zeilenlogik fuer den Mobil-Tab (Refs #358)`.

---

### Task 2: Einschalt-Hinweis nennt den Relay

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_rules.py:357` (`FIRST_ENABLE_NOTICE`)
- Test: `tests/test_tab_rules.py:605-620`

**Interfaces:**
- Consumes/Produces: `FIRST_ENABLE_NOTICE: str` — Inhalt bleibt, plus **ein Absatz** vor „Jetzt einschalten?“: Für iPhones läuft der Abgleich optional über einen Relay-Dienst im Internet; er sieht, dass und wann ein Handy abgleicht und wie groß die Daten sind, **nie den Inhalt**; gekoppelt wird dort erst, wenn der Nutzer „Über Relay koppeln“ wählt.

- [ ] **Step 1: Failing test** `test_the_first_enable_notice_names_the_relay_and_what_it_cannot_see`: `"Relay" in notice`, `"nie den Inhalt" in notice`; die drei bestehenden Zusicherungen (`Ende-zu-Ende verschlüsselt`, `vertrauenswürdig`, `Autostart`) und die zwei Negativ-Tests (`unverschlüsselt`, `mitlesen` kommen **nicht** vor) bleiben unverändert grün.
- [ ] **Step 2:** `python -m pytest tests/test_tab_rules.py -k first_enable -q` → neuer Test rot.
- [ ] **Step 3:** Absatz einfügen; Wortwahl ohne „mitlesen“/„unverschlüsselt“.
- [ ] **Step 4:** `python -m pytest tests/test_tab_rules.py -q` → grün.
- [ ] **Step 5: Commit** — `feat(mobile): Einschalt-Hinweis nennt den Relay (Refs #358)`.

---

### Task 3: Koppel-Dialog im Modus „Relay“

**Files:**
- Modify: `src/dialogs/mobile_pair_dialog.py` (ganzer Dialog; ~217 Zeilen)
- Test: kein Tk-Test (Scope-Grenze); Quelltext-Zusicherung in Task 5.

**Interfaces:**
- Consumes: `RelayService.open_pairing() -> str | None`, `RelayService.close_pairing() -> None` (beide Worker), `BackgroundTaskRunner.run(fn, on_done=None)`, `qr.qr_matrix`/`qr.QrTooLong`, `RELAY_PAIR_HINT`, `RELAY_PAIR_REFUSED_TEXT` (Task 1), bestehend `pair_changes`/`pair_poll_view`/`paired_notice`.
- Produces: `open_pair_dialog(parent, service, *, relay=None, runner=None, mode="lan") -> None`. `mode="relay"` verlangt `relay` **und** `runner` (sonst `ValueError` vor dem Bauen). Ohne neue Argumente verhält sich der Dialog wie bisher (LAN).

- [ ] **Step 1: `_PairDialog.__init__`** nimmt `relay`, `runner`, `mode`; Fenstertitel „Handy koppeln“ (LAN) bzw. „Handy über Relay koppeln“. Im Relay-Modus **entfallen** `_address`, `_code_title`, `_code` (nie anzeigen: der Code allein nützt ohne Box-Geheimnis nichts, das Geheimnis soll nie als Text auf dem Bildschirm stehen); `_hint` trägt `RELAY_PAIR_HINT`, der Einleitungstext nennt „Kamera-App des Handys öffnen und den QR-Code scannen“ ohne den „Adresse eintippen“-Teil.

- [ ] **Step 2: `_new_code` im Relay-Modus.** Canvas leeren, `_result` leeren, „Neuer Code“ und Poll sperren (`_waiting = True`), dann `runner.run(relay.open_pairing, self._relay_opened)`. `_relay_opened(link)` (UI-Thread, `winfo_exists`/`TclError`-geschützt, ignoriert ein Ergebnis, wenn der Dialog inzwischen zu ist — in dem Fall `runner.run(relay.close_pairing)` **nicht** erneut, `_close` hat es schon getan):
  - `link is None` → `_blank_canvas()`, `_clear_code()`, `_countdown` leer, `_result` = `RELAY_PAIR_REFUSED_TEXT` in `STATUS_WARN`; kein Poll.
  - sonst `_before = service.list_devices()`, `_failures_before = service.pair_failures`, Countdown-Text sofort setzen (wie LAN), `_draw(link)`, `_schedule_poll()`.
  Der LAN-Zweig (`status.state != "running"` usw.) bleibt unverändert.

- [ ] **Step 3: `_draw` im Relay-Modus** — bei `QrTooLong`/`ImportError` **kein** Hinweis „Adresse und Code von Hand eintippen“ (gilt nur LAN), sondern `_result` = „Der QR-Code konnte nicht erzeugt werden. Das Koppeln über den Relay braucht ihn.“ in `STATUS_WARN`; Logzeile wie bisher, ohne den Link.

- [ ] **Step 4: Schließen.** `_close` und `_on_destroy` rufen weiterhin synchron `service.pairing.close()`. Im Relay-Modus zusätzlich **einmal** (Flag `_relay_closed`) `runner.run(relay.close_pairing)` — weder im UI-Thread noch zweimal (`_close` löst `<Destroy>` aus, das `_on_destroy` ruft). `_show_paired` ruft `_close` wie bisher.

- [ ] **Step 5:** `python -m pytest -q -k "pair or mobile or relay"` grün; `python -m ruff check src` und `npx pyright src/dialogs/mobile_pair_dialog.py` ohne neue Fehler.

- [ ] **Step 6: Commit** — `feat(mobile): Koppel-Dialog im Modus Relay (Refs #358)`.

---

### Task 4: Mobil-Tab — Relay-Knopf und Zustand je Gerät

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_mobile.py` (`__init__`, `_refresh_devices`, `_sync_buttons`, neue `_pair_relay`)
- Modify: `src/dialogs/settings_dialog/dialog.py:31,94` (neuer Parameter `relay_service=None`, an `MobileTab` durchreichen; Docstring-Zeile)
- Modify: `src/ui.py:639` (`relay_service=self._relay`)

**Interfaces:**
- Consumes: `RelayService.states_by_device() -> dict[str, str]` (nur Speicher, UI-Thread), `device_row_text(record, now, relay_state)`, `relay_pair_enabled(...)`, `open_pair_dialog(..., mode="relay")`.
- Produces: `MobileTab(frame, dialog, settings, mobile_service, runner, relay_service=None)`; `open_settings_dialog(..., relay_service=None)`.

- [ ] **Step 1: Knopfzeile.** Nach der bestehenden `form.buttons(...)`-Reihe eine **zweite** `form.buttons(("Über Relay koppeln (iPhone)", self._pair_relay))`, gespeichert als `self._relay_btn`; ein `form.hint(...)` darunter: „iPhone und Co.: der Abgleich läuft über den Relay-Dienst, nicht über das WLAN.“ Ohne `relay_service` (`None`) wird weder Knopf noch Hinweis gebaut.

- [ ] **Step 2: Zeilentext.** `_refresh_devices` holt je Poll `relay_states = self._relay.states_by_device() if self._relay else {}` und baut `texts = [device_row_text(r, now, relay_states.get(r["id"])) for r in records]`. Der bestehende Vergleich `texts == self._row_texts` bleibt: ein Zustandswechsel baut die Liste neu auf und erhält die Auswahl.

- [ ] **Step 3: Knopf-Zustand.** In `_sync_buttons`: `set_secondary_button_enabled(self._relay_btn, relay_pair_enabled(saved_enabled=bool(self._settings.get("mobile_enabled")), has_relay=self._relay is not None, busy=self._busy))`.

- [ ] **Step 4: `_pair_relay`.** Wie `_pair`: bricht ab bei `self._busy` oder wenn `relay_pair_enabled(...)` falsch ist; lazy Import von `open_pair_dialog` (Importzyklus, s. Kommentar in `_pair`); `open_pair_dialog(self._dialog, self._service, relay=self._relay, runner=self._runner, mode="relay")`; danach `_refresh_devices()` falls `_alive`.

- [ ] **Step 5: Durchreichen.** `dialog.py`: Parameter in der Signatur und im Docstring (ein Satz: „der `relay_service.RelayService` der App (#358); ohne ihn fehlt der Relay-Koppelknopf“), an `MobileTab` übergeben. `ui.py`: Argument ergänzen.

- [ ] **Step 6:** `python -m pytest -q` (ganze Suite; erwartet: wie vor dem Branch, nur `test_report_pdf_layout` rot — lokal bekannt, in der CI grün), `ruff`, `pyright` ohne neue Meldung.

- [ ] **Step 7: Commit** — `feat(mobile): Mobil-Tab - Relay-Kopplung und Zustand je Gerät (Refs #358)`.

---

### Task 5: Verdrahtungstest, Doku, manuelle Prüfung, PR

**Files:**
- Modify: `tests/test_relay_wiring.py` (neuer Test)
- Modify: `docs/datenschutz.md` (Z. 8 „Stand: PR 3c“, Z. 31 „Offen (PR 3c, PR 5)“ → Teil 3c erledigt benennen)
- Modify: `src/CLAUDE.md` (Absatz `relay_service.py`: „Die Oberfläche … kommt mit PR 3c“ → beschreibt Dialog-Modus und Tab; Abschnitt „Dialoge“: `mobile_pair_dialog`-Modi)
- Modify: `CLAUDE.md` (Wurzel, Modulliste: `mobile_pair_dialog.py`-/`tab_mobile.py`-Zeile um Relay-Modus ergänzen)

**Interfaces:** keine neuen.

- [ ] **Step 1: Failing test** in `tests/test_relay_wiring.py`: `test_the_settings_dialog_gets_the_relay_service` — AST-Suche in `ui.py` (Helfer des Tests nutzen): der Aufruf von `open_settings_dialog` trägt das Keyword `relay_service` mit Wert `self._relay`. Zweiter Test `test_the_relay_pair_dialog_closes_through_the_worker`: in `mobile_pair_dialog.py` kommt `close_pairing` nur als Argument von `runner.run(...)` vor, nie als direkter Aufruf (AST: kein `Call` mit Attribut `close_pairing` außerhalb eines `run`-Arguments).
- [ ] **Step 2:** `python -m pytest tests/test_relay_wiring.py -q` → rot, dann nach Task 3/4 grün (läuft die Tasks nacheinander, ist es hier schon grün: dann Test zuerst gegen `git stash`-freien Zustand prüfen, indem man die Zeile in `ui.py` kurz entfernt und wieder einsetzt).
- [ ] **Step 3: Doku.** `docs/datenschutz.md`: unter „Kopplung“ den Satz aufnehmen, dass der Koppel-Dialog den Warntext zeigt (fotografierter QR, Metadaten, nie Inhalte) und der QR-Code das Box-Geheimnis trägt; Offen-Marke von „PR 3c, PR 5“ auf „PR 5“ ändern. Die zwei `CLAUDE.md` wie oben; bei Änderung einer von `tests/test_claude_md_claims.py` geprüften Behauptung läuft der Test mit (`python -m pytest tests/test_claude_md_claims.py -q`).
- [ ] **Step 4: Manuelle Prüfung** (Tk ist nicht automatisiert getestet): `$env:ZEITERFASSUNG_DATA_DIR = <leeres Scratch-Verzeichnis>; python -m src.main`, Einstellungen → Mobil: (a) Handy-Erfassung aus → „Über Relay koppeln“ ausgegraut; (b) einschalten, speichern → Knopf aktiv, Dialog zeigt QR und Warntext, **keinen** Code-Text, Countdown läuft, „Neuer Code“ erzeugt einen neuen QR; (c) Dialog schließen → `mobile_box.json` hat kein `pending` mehr (Datei ansehen); (d) Skalierung 150 % und 200 %: Dialog und zweite Knopfzeile nicht abgeschnitten. Screenshot nach dem Muster aus der Memory „UI-Repro ohne Nutzerdaten“ (EnumWindows) und dem Nutzer zeigen. Hinweis: der Relay-Test mit echtem Handy folgt erst mit PR 4.
- [ ] **Step 5: Gesamtlauf** — `python -m pytest -q`, `python -m ruff check .`, `npx pyright`; Ergebnis nennen (bekannter Rotstand: `test_report_pdf_layout`, lokal).
- [ ] **Step 6: Commit, Push, PR** — `docs(mobile): Relay-Oberfläche in Datenschutz und CLAUDE.md (Refs #358)`; PR „feat(mobile): Relay-Oberfläche — Koppeln und Zustand im Mobil-Tab (PR 3c/5, Refs #358)“, Labels `platform:...` **keine** (Tk-Verhalten plattformneutral); im Body: Verweis auf #421 (Frozen-Test von `websockets`), PR 4 und 5 stehen aus, kein Release vor PR 4. Danach Pre-Release anstoßen (Actions → Release → `prerelease`), weil der Frozen-Test aus #421 erst mit dieser Oberfläche möglich ist.

---

## Self-Review

- **Spec-Abdeckung 3c:** Einstellungen → Mobil (Task 4) ✔; Koppel-Dialog mit `#relay=`-QR und Hinweis „fotografierter QR“ (Task 1 Text, Task 3) ✔; `FIRST_ENABLE_NOTICE` (Task 2) ✔; Statusanzeige (Task 1/4, je Gerät) ✔; Anpassung `test_tab_rules` (Task 1, 2) ✔; `#relay=`-QR des Dev-Servers → Entscheidung „bleibt LAN-only“ ✔. `datenschutz.md`/`known-limitations.md`: Datenschutz-Teil 3c in Task 5; `known-limitations.md` ausdrücklich PR 5.
- **Typkonsistenz:** `open_pair_dialog(parent, service, *, relay, runner, mode)` in Task 3 = Aufruf in Task 4 Step 4; `device_row_text(record, now, relay_state=None)` in Task 1 = Aufruf in Task 4 Step 2; `relay_pair_enabled` Keyword-only in Task 1 = Aufrufe in Task 4 Step 3/4; `relay_service`-Keyword in Task 4 = Test in Task 5.
- **Proportion:** Der Plan beschreibt Signaturen, Texte und Zusicherungen, keine Rümpfe.
- **Geprüft:** `RelayService` bekommt `self._mobile.context` (`ui.py`, `MobileService.context`), also zählt `pair_failures` im Relay-Dialog wie im LAN-Dialog.
- **Offen für den Implementierer:** ob die zweite `form.buttons`-Reihe bei 200 % umbricht (Task 5, Step 4d).
