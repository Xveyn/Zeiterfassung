# Relay-Abgleich: Doku und Widerruf-Hinweis (PR 5/5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Abgleich über den Relay ist für Nutzer und Verantwortliche nachlesbar (README, Bekannte Einschränkungen, Datenschutz), der Widerruf-Dialog sagt, dass die Box am Relay mit gelöscht wird, und #358 wird geschlossen.

**Architecture:** Eine kleine Code-Änderung (Tk-freie Texte in `tab_rules.py`, eingebunden in `tab_mobile.py`) mit Tests; sonst reine Doku. Keine Änderung am Protokoll, an PWA oder Relay.

**Tech Stack:** Python 3.12, pytest, Markdown.

**Spec:** `docs/superpowers/specs/2026-11-02-ios-relay-abgleich-design.md` (Abschnitte „Datenschutz“, „Sicherheit“, „PR-Schnitt“ 5). Vorgänger: PR 1–4 (#406, #412, #420, #424, #427). Zahlen und Verhalten: `relay/CLAUDE.md`, `relay/src/validate.js`.

## Global Constraints

- Doku deutsch; README nennt Nutzer-Verhalten, nicht Entwickler-Interna (Wurzel-`CLAUDE.md`).
- **README-Zeilen für Unveröffentlichtes** tragen `*(ab --VERSION--)*` (der Platzhalter, nie eine geratene Zahl); `scripts/resolve_readme_version.py` löst ihn im Release-PR auf.
- **Kein Versionsbump, kein CHANGELOG-Abschnitt in diesem PR:** der CHANGELOG-Abschnitt ist der Body des Releases und entsteht im Release-PR (Wurzel-`CLAUDE.md`, „Release-Prozess“). Die Stichpunkte stehen im PR-Text.
- `docs/datenschutz.md` beschreibt Datenflüsse, **keine Rechtsauskunft**; es behält den Satz „keine Rechtsberatung“. Zahlen darin prüft `tests/test_datenschutz_claims.py` gegen `relay/src/validate.js` (`Aufbewahrung im Leerlauf: 90 Tage`, `höchstens 1 MiB (1048576 Bytes)`): diese Formulierungen nicht umformulieren.
- Harte Behauptungen der Wurzel-`CLAUDE.md` prüft `tests/test_claude_md_claims.py`.
- Dokumentiert wird nur, was geprüft ist: Echtgerät-Stand siehe „Eingaben“.
- Shell: kein `&&` in Befehlen an den Nutzer (PowerShell 5.1); Commits enden mit `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; der letzte Commit/PR trägt `Closes #358`.

## Eingaben (Stand 2026-11-04) und Entscheidungen

- **Echtgerät-Stand:** iPad (Safari, als Web-App installiert), Desktop `1.25.2-pre.2`, Windows 11: Kopplung über den Relay, Abgleich mit Einträgen und Einstellungen **geprüft**. **Nicht geprüft** (und so zu dokumentieren, solange der Nutzer nichts anderes meldet): Desktop aus/im Ruhezustand, Neustart der Web-App, Widerruf am Desktop, Push auf iOS, Linux/macOS, Android über den Relay. Meldet der Nutzer vor der Umsetzung Ergebnisse, ersetzen sie „nicht geprüft“ an genau diesen Stellen.
- **Datenschutz Abschnitt 6 (Verantwortlichkeit)** beschreibt Tatsachen (der Betreiber des öffentlichen Relays ist der Maintainer des Repos, er verarbeitet IP-Adressen und Metadaten) und nennt die **Lücke** ausdrücklich: eine Datenschutzerklärung mit Kontaktangabe am Pages-Auftritt gibt es nicht. Dafür legt der Plan ein Issue an (Task 4), statt etwas zu behaupten. Selbst-Hosting (`RELAY_URL` einstellbar) ist als Option **erwähnt, nicht umgesetzt**.
- **Kein CHANGELOG hier** (s. Global Constraints).

## Review Focus

1. **Behauptung ohne Beleg:** nichts in README oder Einschränkungen sagt, ein Weg funktioniere, der nicht geprüft ist (Push auf iOS, Linux, macOS, Android über den Relay) (Task 2, 3).
2. **Widerruf bei mehreren Geräten:** ein Widerruf-Text, der von einem Gerät mit Box spricht, darf nicht für ein LAN-Gerät erscheinen; „Alle widerrufen“ nennt den Relay nur, wenn mindestens ein Gerät eine Box hat (Task 1).
3. **Zahlen und Fristen** in der Doku stimmen mit `relay/src/validate.js` überein (90 Tage, 1 MiB, 60 Puts je Minute) (Task 3, 4).
4. **README-Marker:** jede neue Zeile über Unveröffentlichtes trägt den Platzhalter, keine feste Versionsnummer (Task 2).
5. **Der Hinweis „fotografierter QR erlaubt das Koppeln von überall“** steht in `known-limitations.md` (die Spec nennt ihn dort ausdrücklich) (Task 3).

---

### Task 1: Widerruf-Hinweis nennt die Box am Relay

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_rules.py` (neue Texte bei `REVOKE_ERROR_TEXT`, ~Z. 575)
- Modify: `src/dialogs/settings_dialog/tab_mobile.py` (`_revoke`, `_revoke_all`: Text über die neuen Funktionen)
- Test: `tests/test_tab_rules.py`

**Interfaces:**
- Consumes: `RelayService.states_by_device() -> dict[str, str]` (nur Speicher; Geräte-IDs **mit** Box, s. PR 3c), die vorhandene Rückfrage `themed_askyesno(parent, title, text, lock_ms=600)`.
- Produces:
  - `revoke_prompt(name: str, *, has_box: bool) -> str` — ohne Box wortgleich zum heutigen Text („„{name}“ wird ausgesperrt und muss neu gekoppelt werden.\n\nFortfahren?“); mit Box zusätzlich ein Absatz: die Box dieses Handys am Relay wird gelöscht (best effort; ist der Relay nicht erreichbar, verfällt sie nach 90 Tagen), und das Handy meldet danach „Desktop antwortet nicht“, bis es neu gekoppelt ist.
  - `revoke_all_prompt(*, boxes: int) -> str` — bei `boxes == 0` wortgleich zum heutigen Text; sonst derselbe Zusatzabsatz im Plural mit der Zahl der Boxen.

- [ ] **Step 1: Failing tests** in `tests/test_tab_rules.py`:
  - `test_revoke_prompt_without_a_box_is_the_old_text`: `revoke_prompt("Pixel", has_box=False)` enthält „„Pixel“ wird ausgesperrt“ und weder „Relay“ noch „Box“.
  - `test_revoke_prompt_with_a_box_names_the_relay_the_deletion_and_the_phones_message`: enthält „Relay“, „gelöscht“, „90 Tage“, „Desktop antwortet nicht“, „neu gekoppelt“ und endet mit „Fortfahren?“.
  - `test_revoke_all_prompt_counts_the_boxes`: `boxes=0` ohne „Relay“; `boxes=1` und `boxes=3` nennen „Relay“, `boxes=3` die Zahl „3“.
  - `test_the_revoke_prompts_never_contain_a_secret_shaped_string`: kein 43-Zeichen-Base64url-Wort in den Texten (Muster `[A-Za-z0-9_-]{43}`).
- [ ] **Step 2:** `python -m pytest tests/test_tab_rules.py -q -k revoke` → FAIL (Funktionen fehlen).
- [ ] **Step 3: Implementieren** wie signiert; in `tab_mobile._revoke` `has_box = device_id in (self._relay.states_by_device() if self._relay else {})`, in `_revoke_all` `boxes = len(<States ∩ sichtbare Geräte>)` (nur nicht widerrufene Geräte der Liste zählen).
- [ ] **Step 4:** `python -m pytest tests/test_tab_rules.py -q`, `python -m ruff check src tests`, `npx pyright src/dialogs/settings_dialog` → grün/ohne Meldung. Manueller Rauchtest mit Fakes nach dem Muster aus PR 3c (Scratchpad-Skript: `MobileTab` mit Attrappe, `themed_askyesno` ersetzt, Text für ein Gerät mit und eines ohne Box prüfen).
- [ ] **Step 5: Commit** — `feat(mobile): Widerruf-Hinweis nennt die Box am Relay (Refs #358)`.

---

### Task 2: README

**Files:**
- Modify: `README.md` (Features-Zeile ~Z. 79, Abschnitt „Handy-Erfassung“: Voraussetzungen, Tabelle „Welcher Browser was kann“, Koppeln, Sicherheit in Kürze)

**Interfaces:** keine.

- [ ] **Step 1: Features-Zeile und Voraussetzungen.** Die Aussage „klappt derzeit nur mit Chrome auf Android; iOS … nicht funktionsfähig“ ersetzen: der Abgleich im WLAN klappt mit Chrome auf Android; für iPhone und iPad (und Firefox) läuft er optional **über einen Relay im Internet** `*(ab --VERSION--)*`, ebenfalls Ende-zu-Ende verschlüsselt, die Desktop-App muss laufen. „Voraussetzungen“ nennt beide Wege (gleiches WLAN **oder** Internet für den Relay).
- [ ] **Step 2: Tabelle.** Überschrift ohne „iOS ist noch nicht vollständig funktionsfähig“. Safari (iPhone/iPad): Web-App öffnen ✓, **Als App installieren ✓ (iPad geprüft)**, QR in der Web-App scannen ✓, **Abgleich über den Relay ✓ (iPad geprüft) `*(ab --VERSION--)*`**, Abgleich im WLAN ✗ (Mixed Content), Push-Erinnerungen „nicht geprüft“. Firefox: Relay „nicht geprüft“. Der Absatz zu Mixed Content bleibt als Erklärung, nennt aber den Relay als Ausweg statt „kein Weg gebaut“.
- [ ] **Step 3: Koppeln.** Neuer Schritt/Absatz: **„Über Relay koppeln (iPhone)“** — Einstellungen → Mobil → „Über Relay koppeln (iPhone)“, QR-Code nur **in der installierten Web-App** mit „QR-Code scannen“ scannen (nicht mit der Kamera-App: sie öffnet den Link im Browser, dessen Speicher nicht zur Web-App gehört), Namen bestätigen. Warnung: wer den QR-Code fotografiert, kann sich von überall im Internet koppeln, solange der Code gilt (5 Minuten); nur dem eigenen Handy zeigen.
- [ ] **Step 4: Sicherheit in Kürze.** Ein Satz: Beim Relay-Weg sieht der Relay (Cloudflare) Metadaten (dass und wann ein Handy abgleicht, Größen, IP-Adressen), nie Einträge oder Namen; Verweis auf `docs/datenschutz.md` und die neue Section in `docs/known-limitations.md` (Task 3).
- [ ] **Step 5:** `python scripts/resolve_readme_version.py --check` (der Platzhalter ist **erlaubt**, nur im Release-PR muss er aufgelöst sein) bzw. Ansicht der Ausgabe; `python -m pytest tests/test_claude_md_claims.py -q` grün.
- [ ] **Step 6: Commit** — `docs(readme): Abgleich ueber den Relay fuer iPhone und iPad (Refs #358)`.

---

### Task 3: Bekannte Einschränkungen

**Files:**
- Modify: `docs/known-limitations.md` (Z. ~474 „Nicht gelöst: Firefox und iOS“; Z. ~511 Aufzählungspunkt „Nur Chrome auf Android …“; neuer Abschnitt nach „Push-Relay (#331)“; Z. ~602 „Firefox und iOS haben vorerst nichts davon“)

**Interfaces:** keine.

- [ ] **Step 1: Bestehende Aussagen berichtigen.** Z. 474: „Nicht gelöst: Firefox und iOS …“ → im WLAN gelöst durch den Relay-Weg (s. neue Section), Mixed Content bleibt Grund, warum der LAN-Weg dort nicht geht. Der Punkt „Nur Chrome auf Android gleicht ab; iOS …“ (Z. ~511) wird zu „Im WLAN gleicht nur Chrome auf Android ab; iPhone, iPad und Firefox brauchen den Relay“ mit dem Stand der Prüfung (Safari/iPad: Kopplung und Abgleich über den Relay geprüft; Firefox nicht geprüft; Installation als App auf dem iPad geprüft). Z. ~602 (Push): „Firefox und iOS haben vorerst nichts davon“ präzisieren: mit dem Relay-Abgleich entsteht ein Plan; **ob Push auf iOS ankommt, ist nicht geprüft** (Web-Push braucht dort die installierte Web-App).
- [ ] **Step 2: Neue Section „Abgleich über den Relay (#358): ein zweiter Vertrauens-Ort“** (Aufbau wie „Push-Relay (#331)“), mit diesen Punkten, jeder mit Beleg im Code oder Spec:
  - **Was der Relay sieht / nicht sieht** (Pfad, Statuscode, `seq`, `n`, Nonce, Feldnamen, Größe, Zeitpunkte, IP, das Gerätetoken im Klartext; nie den Inhalt) und Verweis auf `docs/datenschutz.md`.
  - **Ein fotografierter QR-Code erlaubt das Koppeln von überall im Internet**, solange der Code gilt (5 Minuten); das Box-Geheimnis im QR gilt, bis die Box gelöscht wird (Widerruf, erneutes Koppeln, „Zeiterfassung entfernen“, 90 Tage Leerlauf). Wer es kennt, kann Slots überschreiben, den Desktop verdrängen, Fehler fälschen, die Box löschen — nie Inhalte lesen (Spec „Sicherheit“).
  - **Der Desktop muss laufen.** Ist er aus oder im Ruhezustand, meldet die Web-App nach höchstens 15 s „Desktop hat nicht geantwortet“ (Art `desktop_silent`), danach 30 s Ruhe bei automatischen Abgleichen. Die Anfrage bleibt in der Box und wird beim nächsten Verbinden des Desktops zugestellt.
  - **Nach einem Widerruf** am Desktop meldet das Handy dieselbe Meldung statt „widerrufen“ (die Box ist gelöscht, es gibt keine Antwort mit `token_revoked`); die Meldung nennt den Ausweg „neu koppeln“.
  - **Grenzen:** 1 MiB je Nachricht (zu große Antwort ⇒ `response_too_large`, Hinweis „Verlauf auf 90 Tage zurücksetzen“), höchstens 60 Nachrichten je Minute und Verbindung, je Rolle eine Verbindung (zwei Tabs der Web-App verdrängen sich: Meldung „zweite Verbindung“), ein Handy je Kopplung.
  - **Kontingent:** der kostenlose Cloudflare-Plan erlaubt 100 000 Worker-Anfragen am Tag **für alle Nutzer zusammen**; je Austausch fällt eine Verbindung an. Ist es aufgebraucht, antwortet der Relay nicht mehr, bis der Tag um ist (wie beim Push); Zahlen des `Box`-Objekts im Dashboard sind **nicht gemessen** (Spec „Offene Punkte“ 1–2).
  - **Nicht geprüft:** Safari im Hintergrund (schließt es die WebSocket sauber, Wiederverbinden mit `have`), Push auf iOS, Linux und macOS (Desktop-Seite, #421), Android über den Relay.
  - **iOS-Eigenheit:** Safari-Tab und installierte Web-App haben getrennten Speicher; iOS löscht den Tab-Speicher nach sieben Tagen ohne Nutzung. Die Web-App weist darauf hin.
- [ ] **Step 3:** `python -m pytest tests/test_claude_md_claims.py tests/test_datenschutz_claims.py -q` grün; Zahlen gegen `relay/src/validate.js` (`maxFrame`, `putsPerMinute`, `idleDays`) von Hand abgleichen.
- [ ] **Step 4: Commit** — `docs(limits): Abgleich ueber den Relay - Vertrauens-Ort und Grenzen (Refs #358)`.

---

### Task 4: Datenschutz schließen, Verantwortlichkeit, Issue, PR

**Files:**
- Modify: `docs/datenschutz.md` (Stand-Zeile; Abschnitte 2 (Z. ~61 „Offen (PR 3c)“), 5, 6, 7, 8, 10 und die Koppeln-Zeile ~Z. 37)

**Interfaces:** keine.

- [ ] **Step 1: Abschnitte füllen**, jeweils mit Verweis auf Code/Spec statt Behauptung:
  - **2 (Aufbewahrung):** „Offen (PR 3c)“ ersetzen: Widerruf-Dialog (Task 1) und Koppel-Dialog sagen es; Erinnerung an „Zeiterfassung entfernen“ bleibt.
  - **5 (Auftragsverarbeiter):** Cloudflare, GitHub/Microsoft, Apple/Google/Mozilla mit je einem Link auf deren Bedingungen/Datenschutzseite (Link-Ziele von Hand prüfen, nur offizielle Seiten) und dem Hinweis: ob ein Auftragsverarbeitungsvertrag nötig ist, hängt davon ab, wer die App wofür einsetzt (privat, Werkstudent mit eigener Erfassung, Arbeitgeber); der Text ist ein Hinweis, keine Zusage.
  - **6 (Verantwortlichkeit):** Betreiber des öffentlichen Relays ist der Maintainer des Repos; verarbeitet werden IP-Adressen und die Metadaten aus Abschnitt 1. **Eine Datenschutzerklärung mit Kontaktangabe am Pages-Auftritt fehlt** (Issue aus Step 3). Selbst-Hosting: `RELAY_URL` ist eine Konstante, ein Betrieb des Relays in eigenem Cloudflare-Konto ist in `relay/README.md` beschrieben, die App darauf umzustellen ist **nicht** vorgesehen.
  - **7 (Freiwilligkeit):** Opt-in je Gerät („Über Relay koppeln“), klare Sprache vor dem Einschalten (Einschalt-Hinweis, Koppel-Dialog), Ausschalten und Löschen jederzeit; **auf iOS ist der Relay Pflicht für die Handy-Erfassung** („ohne Relay kein Abgleich“), das steht dort ehrlich so.
  - **8 (Datensparsamkeit):** ein Slot je Richtung (Ersetzen statt Historie), kein Konto, keine Geräte-ID im Klartext außer dem Gerätetoken; das Gerätetoken ist ein Auth-Mittel, aber der Relay kann Verbindungen über die Zeit verknüpfen (Metadatenrisiko).
  - **10 (Push getrennt):** zwei Objekte, zwei Geheimnisse, zwei unverknüpfte Handles; wer beides nutzt, gibt dem Relay beide.
  - Stand-Zeile auf „PR 5“; **keine** `Offen (PR n)`-Marke bleibt, außer für die ausdrücklich genannte Datenschutzerklärung.
- [ ] **Step 2:** `python -m pytest tests/test_datenschutz_claims.py -q` grün (Zahlen-Formulierungen unverändert gelassen).
- [ ] **Step 3: Issue anlegen** (Befehl an den Nutzer ohne Backticks-Fallen, Text über `--body-file`): „Datenschutzerklärung und Kontaktangabe für den öffentlichen Relay und die Pages-Auftritt“ — Inhalt: Betreiber verarbeitet IP-Adressen und Metadaten (Abschnitt 1 und 6 von `docs/datenschutz.md`), eine Erklärung/ein Impressum am Pages-Auftritt fehlt, Entscheidung des Maintainers (wo, in welchem Umfang); `Refs #358`. Die Nummer in Abschnitt 6 eintragen.
- [ ] **Step 4: Gesamtlauf** — `python -m pytest -q` (bekannt rot lokal: `test_report_pdf_layout`), `python -m ruff check .`, `cd pwa; node --test` (bekannt rot unter Windows: `shell.test.js`, 11); Ergebnis nennen.
- [ ] **Step 5: Commit, Push, PR** — `docs(datenschutz): Abschnitte zum Relay-Abgleich geschlossen (Closes #358)`; PR „docs(mobile): Relay-Abgleich — Doku, Datenschutz, Widerruf-Hinweis (PR 5/5, Closes #358)“. Im PR-Text: Stichpunkte für den späteren CHANGELOG-Abschnitt (Release-PR), nicht geprüfte Wege, Verweis auf #421, #422, #423, #425, #426 und das neue Issue. **Push als Xveyn:** der aktive `gh`-Account kann Sven-MH sein; dann `GH_TOKEN="$(gh auth token --user Xveyn)"` nur für den Push- und den PR-Befehl setzen. Danach: **Release-Hinweis an den Nutzer**: ein Pre-Release nach diesem PR ist für Linux/macOS (#421) sinnvoll, ein echtes Release braucht den Release-PR mit CHANGELOG und `resolve_readme_version.py`.

---

## Self-Review

- **Spec-Abdeckung PR 5:** `known-limitations.md` (Task 3), READMEs (Task 2), CHANGELOG (bewusst im Release-PR, s. Entscheidung), Datenschutz-Abschnitte und Widerruf-/Koppel-Hinweise (Tasks 1, 4), Pre-Release-Test auf dem iPad (erledigt; Ergebnis unter „Eingaben“), `Closes #358` (Task 4).
- **Typkonsistenz:** `revoke_prompt(name, *, has_box)` und `revoke_all_prompt(*, boxes)` aus Task 1 werden nur in `tab_mobile` benutzt; keine Folgetasks hängen daran.
- **Proportion:** eine kleine Code-Änderung, sonst Dokumente; die Aufzählungen der Doku sind Inhaltsvorgaben, kein ausformulierter Text.
- **Offene Entscheidung des Nutzers:** Datenschutzerklärung/Impressum (Task 4 legt ein Issue an, entscheidet nichts); die nicht geprüften Wege bleiben „nicht geprüft“, bis der Nutzer testet.
