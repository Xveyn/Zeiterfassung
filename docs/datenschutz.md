# Datenschutz: Datenflüsse der Handy-Erfassung über den Relay

> Beschreibung von Datenflüssen, keine Rechtsberatung.

Dieses Dokument sagt, **wer was bekommt, wo es liegt, wie lange und wie es gelöscht wird**. Es ist die
Quelle für Hinweistexte in der App. Die Zahlen darin prüft `tests/test_datenschutz_claims.py` gegen
`relay/src/validate.js`. Jeder PR der Kette (#358) ergänzt seinen Teil; was noch nicht festliegt, steht als
`Offen (PR n)`. Stand: PR 1 (der Relay-Teil, die Box).

## 1. Was der Relay sieht, und was nicht

Der Relay sieht:

- verschlüsselte Daten (Chiffretext). Größe je Nachricht: höchstens 1 MiB (1048576 Bytes),
- Zeitpunkte der Nachrichten und deren Größen,
- das Gerätetoken im Klartext der Nutzlast, neben dem verschlüsselten Umschlag. Der Relay kann damit nichts
  entschlüsseln; das Token wird bei jedem Abgleich erneuert,
- die IP-Adresse der Verbindung (Rate-Limit und Cloudflare-Plattform).

Vom Umschlag selbst ist nichts lesbar (kein Inhalt, keine Feldnamen). Der Relay sieht **nie** Einträge, Kategorien oder Namen: die Nutzbytes sind Ende-zu-Ende verschlüsselt, der
Relay hält keinen Schlüssel. Es gibt bewusst keinen Klartext-Pfad (kein Vorschau-Feld, kein Debug-Dump).

## 2. Aufbewahrung und Löschung

- Ein Slot liegt höchstens bis zum Ersetzen: jede neue Nachricht überschreibt den Slot ihrer Richtung, es gibt
  keine Historie.
- Aufbewahrung im Leerlauf: 90 Tage. Danach räumt sich die Box selbst auf (Alarm, `idleDays`).
- `DELETE /v1/box` löscht sofort alles und schließt die Verbindungen.
- Offen (PR 3): „Kopplung entfernen“, „Zeiterfassung entfernen“ und `--forget-secrets` räumen die Box mit ab.

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

Offen (PR 3).

## 10. Push getrennt halten

Offen (PR 5). Vorab: Push (`Device`) und Abgleich (`Box`) sind getrennte Objekte mit getrennten Geheimnissen.
