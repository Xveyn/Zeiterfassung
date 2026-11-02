# Datenschutz: Datenflüsse der Handy-Erfassung über den Relay

> Beschreibung von Datenflüssen, keine Rechtsberatung.

Dieses Dokument sagt, **wer was bekommt, wo es liegt, wie lange und wie es gelöscht wird**. Es ist die
Quelle für Hinweistexte in der App. Die Zahlen darin prüft `tests/test_datenschutz_claims.py` gegen
`relay/src/validate.js`. Jeder PR der Kette (#358) ergänzt seinen Teil; was noch nicht festliegt, steht als
`Offen (PR n)`. Stand: PR 3a (Relay-Teil, Nachrichtenrahmen und Desktop-Kern).

## 1. Was der Relay sieht, und was nicht

Der Relay sieht: Pfad, Statuscode, `seq`, `n`, Nonce, Feldnamen, Größe, Zeitpunkte, IP, und das
Gerätetoken im Klartext; nie den Inhalt. Im Einzelnen:

- die Rahmen-Metadaten der Nutzlast im Klartext: den Pfad (Kopplung oder Abgleich), den Statuscode der
  Antwort, den Zähler `seq`, das Feld `n` der Antwort (die zurückgegebene Nonce der Anfrage), die Nonce
  und die Feldnamen des Umschlags,
- das Gerätetoken im Klartext der Nutzlast, neben dem Umschlag. Der Relay kann damit nichts entschlüsseln.
  Erneuert wird es nur nach einem **erfolgreichen** Abgleich; bis dahin, und danach bis die nächste Anfrage
  den Slot ersetzt, liegt es im Slot `req` (längstens bis zur Selbstreinigung nach 90 Tagen Leerlauf). Im LAN
  ist dasselbe Token zugleich gültiger Bearer für `GET /v1/ping` (Protokoll, Uhrzeit des Desktops,
  Standardfenster, und damit, ob die Kopplung noch gilt),
- Zeitpunkte der Nachrichten und deren Größen. Größe je Nachricht: höchstens 1 MiB (1048576 Bytes),
- die IP-Adresse der Verbindung (Rate-Limit und Cloudflare-Plattform).

Der Relay sieht **nie** den Inhalt: Der Chiffretext `c` des Umschlags verbirgt alle Einträge, Kategorien,
Namen und Einstellungen. Er ist Ende-zu-Ende verschlüsselt, der Relay hält keinen Schlüssel. Es gibt bewusst
keinen Klartext-Pfad für Inhalte (kein Vorschau-Feld, kein Debug-Dump).

Dasselbe gilt für jeden, der das Geheimnis der Box kennt (wer den QR-Code sieht, der Betreiber des Relays):
er sieht die Slots wie der Relay, also auch das Gerätetoken, aber nie den Inhalt. Offen (PR 3c, PR 5): was das für
die Kopplung über das Internet heißt (Erweiterung des Vertrauens gegenüber dem LAN), steht dann hier.

## 2. Aufbewahrung und Löschung

- Ein Slot liegt höchstens bis zum Ersetzen: jede neue Nachricht überschreibt den Slot ihrer Richtung, es gibt
  keine Historie.
- Aufbewahrung im Leerlauf: 90 Tage. Danach räumt sich die Box selbst auf (Alarm, `idleDays`).
- `DELETE /v1/box` löscht sofort alles und schließt die Verbindungen.
- Das Box-Geheimnis liegt am Desktop gerätelokal in `mobile_box.json`: gehärtet geschrieben (nur für den
  Nutzer lesbar, unter Windows per ACL), **nicht** im Schlüsselbund und nicht per Drive-Sync. Der Desktop
  kann eine Box mit `DELETE /v1/box` löschen (`box_relay.delete_box`, best effort: ist der Relay nicht
  erreichbar, bleibt das Lösen gültig und die Box verfällt von selbst).
- Offen (PR 3b): „Kopplung entfernen“, „Zeiterfassung entfernen“ und `--forget-secrets` räumen die Box mit ab.
  Bis dahin ruft nichts in der App das Löschen auf; eine Box bleibt dann höchstens 90 Tage im Leerlauf.

## 3. Plattform-Logs

Der eigene Code des Relays schreibt nichts mit (kein Geheimnis, keine Query, keine Nutzbytes). Die Plattform
kann von sich aus Aufruf-Logs führen: Cloudflare speichert sie, **wenn sie aktiviert sind**, bis zu 7 Tage
(URL und Metadaten). Im Worker ist `observability` ausdrücklich ausgeschaltet (`relay/wrangler.toml`). Die
Query trägt nur `role` und `have`; das Geheimnis steht im Header `Sec-WebSocket-Protocol`, nicht in der URL.

## 4. Standort

Das Durable Object der Box liegt in der EU-Jurisdiktion von Cloudflare (Ausführung und Speicherung).
**Nicht** davon erfasst ist der Worker selbst: er läuft pro Anfrage am nächstgelegenen Rand, die IP-Adresse
wird dort verarbeitet. Die Jurisdiktion lässt sich nachträglich nicht ändern, deshalb war das eine Entscheidung
von Anfang an. Das bestehende Push-Objekt (Erinnerungen) bleibt, wie es ist. Der Schalter dafür steht in
`relay/wrangler.toml` und wird nie im Cloudflare-Dashboard gesetzt: bis zum nächsten Ausrollen lägen neue
Objekte sonst womöglich außerhalb der EU-Jurisdiktion.

## 5. Beteiligte und Drittländer

- Cloudflare: Betrieb des Relays (Worker und Durable Object).
- GitHub (Microsoft): Auslieferung der Handy-Web-App über GitHub Pages; dabei sieht GitHub die IP-Adresse
  des Handys.
- Apple, Google, Mozilla: Web-Push-Dienste (nur für Erinnerungen); sie kennen den Abo-Endpunkt des Handys.

Offen (PR 5): Verweise auf die jeweiligen Bedingungen und der Hinweis, wann ein Auftragsverarbeitungsvertrag
nötig sein kann (hängt davon ab, wer die App wofür einsetzt).

## 6. Verantwortlichkeit

Offen (PR 5).

## 7. Freiwilligkeit und Transparenz

Offen (PR 4).

## 8. Datensparsamkeit

Offen (PR 5). Vorab, was der Relay festlegt: ein Slot je Richtung (Ersetzen statt Historie), kein Konto.

## 9. Schlüssel und Wiederherstellung

Der Relay hält keine Schlüssel, es gibt keine Wiederherstellung durch uns. Die Geräteschlüssel liegen am
Desktop im Schlüsselbund (Datei als Fallback), das Box-Geheimnis in `mobile_box.json` (s. 2.). Wer das
Box-Geheimnis kennt (sieht den QR-Code, Betreiber des Relays), kann den Slot des Gegenübers lesen (Gerätetoken im
Klartext, den versiegelten Umschlag), Slots überschreiben, den Desktop von der Box verdrängen und unversiegelte
Fehler fälschen, `DELETE /v1/box` auslösen. Er kann **nicht** Inhalte lesen oder synchronisieren: das braucht den
Geräteschlüssel. Das ist ein Störer- und Metadatenrisiko, kein Inhaltsleck.
Offen (PR 3b, PR 3c): Geht das Handy verloren, widerruft der Nutzer die Kopplung am Desktop; die Box wird dabei
mit gelöscht (ab PR 3b) und der Dialog sagt es (PR 3c).

## 10. Push getrennt halten

Offen (PR 5). Vorab: Push (`Device`) und Abgleich (`Box`) sind getrennte Objekte mit getrennten Geheimnissen.
