# Offene Sicherheitsfragen (Handy-Erfassung) — NICHT COMMITTEN

Arbeitsnotiz, bewusst **unversioniert**: `SECURITY.md` verlangt, Schwachstellen
nicht über öffentliche Issues zu melden. Diese Punkte kommen aus dem Review zu
PR 4a (#256, dort nur als Stichwort unter „Offene Spec-Fragen") und der
anschließenden Prüfung der PWA. Wenn sie erledigt sind, die Datei löschen;
Fixes laufen als normale PRs ohne Exploit-Beschreibung.

Stand: 2026-10-20. „Gelesen" = im Code belegt, nicht ausgeführt.

---

## 1. PWA teilt ihre Origin mit anderen Pages-Projekten

**Befund.** Die PWA liegt unter `https://xveyn.github.io/Zeiterfassung/`. Auf
derselben Origin liegen `/mathe-tools/` und `/BaluHost-Plugin-Market/` (beide
öffentlich, keine Custom Domain; `gh api repos/Xveyn/<repo>/pages`). Origin-
gebundener Speicher ist nicht pfadgescopt.

**Gelesen (`pwa/`):**
- Persistiert wird nur in IndexedDB (DB `zeiterfassung`, Stores `entries`,
  `meta`, `reservations`; `db.js:10,11,29`) und in der Cache API (nur statische
  App-Dateien, `sw-core.js`). Kein localStorage, sessionStorage, Cookie.
- `meta.token` (Gerätetoken) und `meta.key` (`k_dev`, base64url) stehen als
  Klartext-Strings im Datensatz `meta` (`store.js:25–36`, geschrieben
  `store.js:158,538`; Schlüssel gesetzt `sync.js:81–84`). `importKey(…, false, …)`
  in `crypto.js:48,85` schützt nichts, solange die Rohbytes in IndexedDB liegen.
- Server: `allowed_origins` = genau `PWA_ORIGIN` (`mobile_routes.py:55`,
  `mobile_service.py:215–217`) — gilt für die ganze Origin, nicht den Pfad.
- Der Kopplungscode wird nie persistiert (nur im Speicher, `app.js:95–117`).

**Folge.** Ein Skript, das auf einer anderen Seite dieser Origin läuft, kann
Token und `k_dev` lesen und gültige verschlüsselte `/v1/sync`-Umschläge bauen
(Einträge, Reservierungen, Kategorien lesen und schreiben). Die Ende-zu-Ende-
Verschlüsselung schützt dagegen nicht, der Angreifer hat den Schlüssel. Der
Replay-Zähler `seq` lässt sich überholen; die echte PWA bekommt dann `409
replay` und muss neu koppeln (Störung). Ein gestohlenes Token verlängert sich
bei jedem Abgleich selbst, bis das Gerät am Desktop widerrufen wird.

**Voraussetzungen** (begrenzen das Risiko): Zugriff auf eine der Seiten auf
`xveyn.github.io` (z. B. nachgeladener Fremdcode, kompromittierte Abhängigkeit
oder Repo) **und** Erreichbarkeit des Desktops im LAN (private IPv4,
`pairing.js:37–44`). Solange dort nur eigener statischer Code läuft, ist das
Risiko gering; es wächst mit jeder Fremdabhängigkeit. Nicht geprüft: was die
beiden anderen Projekte tatsächlich laden.

**Nebenbefund (Kollision, kein Angriff).** Die DB heißt generisch
`zeiterfassung`; ein anderes Projekt auf der Origin mit demselben Namen
kollidiert (Versionskonflikt, `onupgradeneeded`). Vermutung, nicht ausgeführt.

**Optionen.**
- **Eigene Origin** für die PWA (eigene (Sub-)Domain oder eigener Account/Org):
  einzige strukturelle Lösung. Berührt `PWA_ORIGIN`/`PWA_URL`
  (`mobile_routes.py:55,56`), den Pages-Workflow, Koppel-Link und `SECURITY.md`.
  Bestehende Kopplungen müssten neu erfolgen (Speicher gehört zur alten Origin).
- **DB-Name eindeutig** (z. B. `zeiterfassung-pwa`, mit Migration): löst nur die
  Kollision, nicht das Auslesen.
- **`k_dev` als nicht-extrahierbarer `CryptoKey`** in IndexedDB: Schlüssel nicht
  kopierbar, aber vom Skript weiter benutzbar; begrenzter Gewinn, mittlerer
  Aufwand (`crypto.js`, `sync.js`, `store.js`, `db.js`, Tests).
- **Schlüssel nur im Speicher / hinter Passphrase**: wirksam, kostet Komfort
  (Neukoppeln oder Eingabe bei jedem Start).

**Zu entscheiden:** Bedrohungsmodell. Empfehlung des Prüfers: DB-Name zuerst
(billig), dann je nach Modell eigene Origin.

---

## 2. Verbindungsplätze: ein LAN-Gerät kann alle 32 belegen

**Befund.** `api_server` nimmt höchstens 32 gleichzeitige Verbindungen an
(`_MAX_CONNECTIONS`, `api_server.py:55`), und zwar vor der Authentifizierung.
Auf der Handy-Instanz kann jedes Gerät im selben Netz ohne Token alle Plätze
belegen. Eine Verbindung lebt höchstens 15 s (`_REQUEST_DEADLINE_S`); wer
dauerhaft neue öffnet, hält die Plätze. Verfügbarkeit, kein Datenzugriff.

**Option.** Obergrenze pro Quell-IP (etwa 8) in
`_ApiHTTPServer.process_request` neben dem globalen Semaphor. Bremst ein
einzelnes Gerät, nicht mehrere; im Heimnetz ein vertretbarer Kompromiss.
Hinter NAT/Proxy teilten sich alle Clients eine IP — im Heimnetz ohne Proxy
unkritisch. Alternative: als bekannte Grenze in
`docs/known-limitations.md` (Abschnitt Handy-Erfassung) dokumentieren, wie es
für `api_server` schon gilt. Betrifft die Loopback-API nur durch lokale
Prozesse.

---

## Status

- Teil 1 und 2 aus #256 (Preflight ohne `Content-Length` an der 204, gemeinsame
  Host-/Origin-Prüfung, Mutationstests) sind ein eigener PR; diese beiden Punkte
  bleiben bis zur Entscheidung hier.
- Offen: Entscheidung zu 1 (Origin/Bedrohungsmodell), dann ob 2 Code oder
  Dokumentation wird. #256 selbst nennt beide Punkte nur stichwortartig; ob der
  Issue-Text so stehen bleiben soll, ist ebenfalls zu entscheiden.
