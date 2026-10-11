# Handy-Erfassung: das Lesefenster der PWA wachsen lassen (#250)

**Status:** Entwurf zur Freigabe · **Bezug:** #250 (Ausgangsidee), #221 (PWA), #290
(Kompatibilitätsregeln, `pwa/CLAUDE.md`, Abschnitt „Kompatibilität“)

## Ziel

Die PWA sieht heute die letzten 90 Tage (`WINDOW_DAYS`). Wer weiter zurück
blättert, sieht leere Wochen, die in Wahrheit nur nicht geladen sind. Künftig:

1. Der **Desktop gibt eine Obergrenze vor** (einstellbar, Standard 365 Tage).
2. Das **Handy bestimmt sein Fenster selbst**, innerhalb dieser Grenze, und
   **lädt ältere Zeiten nach**, wenn man darauf zugeht.

Nicht Teil davon: die volle Historie, seitenweises Laden, Delta-Antworten und
die Randwoche in den Wochensummen (alles weiter in #250, s. „Abgrenzung“).

## Ausgangslage (gemessen am Code)

- `mobile_sync.WINDOW_DAYS = 90` ist eine Konstante. Die Antwort trägt sie schon
  als `window_days`; die PWA richtet **alles** danach aus (`store.applyResponse`
  räumt saubere Tage außerhalb auf, `app.js` warnt im Editor bei Tagen außerhalb).
  Ein anderes Fenster braucht auf der PWA-Seite deshalb keine neue Aufräumlogik.
- Jede Antwort enthält das **ganze Fenster**, kein Delta. Die Kosten wachsen
  linear mit dem Fenster. **Gemessen** (verschlüsselte Antwort auf dem Draht,
  194 Byte je Slot-Tag, `mobile_crypto.seal`, Node-Messung für die PWA-Seite):

  | Fall | Tage | auf dem Draht | Desktop bauen+verschlüsseln | PWA parsen+anwenden |
  |---|---|---|---|---|
  | realistisch, 90 Tage, 5 Werktage/Woche, 2 Slots | 65 | 24 KB | < 1 ms | – |
  | realistisch, 365 Tage | 261 | **96 KB** | 1,4 ms | 6 ms |
  | viel: jeden Tag, 6 Slots | 365 | 271 KB | 4 ms | 10 ms |
  | sehr viel: 20 Slots/Tag | 365 | 750 KB | 12 ms | – |
  | Extrem: 50 Slots/Tag (`MAX_SLOTS`) | 365 | 1,8 MB | 28 ms | 45 ms |
  | Extrem, 50 Slots, 100-Zeichen-Kategorie | 365 | 4,0 MB | 39 ms | – |

  Rechen- und Speicherkosten sind auf beiden Seiten vernachlässigbar; **die Übertragung
  ist der einzige Engpass**. Die PWA bricht einen Abgleich nach 15 s ab
  (`AbortSignal.timeout`), der Server hat 10 s Socket-Timeout je Operation. Bei
  einem schwachen WLAN (1 Mbit/s) brauchen 4 MB gut 30 s — der Abgleich käme nie an
  und würde immer wieder abbrechen. Deshalb gibt es das Mengenlimit unten.
- `parse_request` ignoriert unbekannte Felder der Anfrage. Ein neues optionales
  Feld bricht kein Protokoll.
- „Fenster vergrößern“ aus #250 ist **kein** Löschrisiko: gelöscht wird nur, was
  die Antwort mit ihrem **eigenen** `window_days` als fehlend meldet. Neue Tage
  kommen als gewöhnliche Einträge.

## Entscheidungen

| Frage | Entscheidung |
|---|---|
| Wer bestimmt das Fenster? | Das Handy wünscht, der Desktop deckelt. |
| Obergrenze | Einstellung im Tab „Mobil“: 30 / 90 / 180 / 365 Tage, Standard **365**, gerätelokal, nicht in `SYNCED_SETTING_KEYS`. Hart gedeckelt auf 365 im Code. |
| Standardfenster ohne Wunsch | **90**, gedeckelt auf die Obergrenze (bei 30 also 30). Ein altes Handy sieht nichts Neues. |
| Mengenlimit | Der Desktop kürzt das gewährte Fenster, wenn die Einträge im Fenster mehr als **768 KiB** (Klartext, ≈ 1 MB auf dem Draht) ergäben; nie unter das Standardfenster. |
| Verhalten nach dem Nachladen | Das Wunschfenster **bleibt** auf dem Handy; im Verbindungsdialog steht es mit „Auf 90 zurücksetzen“. |
| Protokoll | `PROTOCOL` bleibt 2, rein additive Felder. |

## Protokoll (additiv)

**Anfrage** (`POST /v1/sync`), optional:

```json
{ "protocol": 2, "client_time": "…", "last_pull_at": "…", "window_days": 180, "entries": {} }
```

`window_days` ist der Wunsch des Handys. Fehlt es oder ist es ungültig (kein
Integer, `bool`, < 1), gilt der Standard.

**Antwort**, zwei Felder:

- `window_days` — das **gewährte** Fenster: `clamp(Wunsch oder 90, 1, Obergrenze)`.
- `window_max_days` — die Obergrenze des Desktops (die Einstellung).

Die Rechnung ist eine reine Funktion `mobile_sync.grant_window(wish, cap)`.

**Mengenlimit.** Nach `grant_window` summiert `fit_window` die Größe der Einträge von
heute rückwärts und beendet das Fenster vor dem ersten Tag, der das Budget
(`MAX_RESPONSE_ENTRY_BYTES = 768 KiB`) sprengt. Das **Standardfenster (90 Tage)
bleibt immer**, auch wenn es allein größer ist (so verhält es sich heute). Das
Ergebnis steht als `window_days` in der Antwort; liegt es unter dem Wunsch und
unter der Obergrenze, weiß die PWA: „gekürzt wegen der Datenmenge“. Tage, die das
Handy **selbst gesendet** hat, kommen immer zurück (heutige Regel). Das Budget
liegt weit über dem realistischen Fall (72 KB Klartext bei 365 Tagen) und bei
15 s Timeout noch bei etwa 0,6 Mbit/s erreichbar.
`window_max_days` fehlt bei einem Desktop vor dieser Änderung: die PWA erkennt
daran **per Feature-Erkennung**, dass das Fenster dort nicht wachsen kann (Regel 2
aus #290). Die Kopplungsantwort (`/v1/pair`) trägt weiter `window_days`, ohne
Wunsch: `grant_window(None, cap)`.

Der Wunsch wird **geklemmt, nicht abgelehnt**: kein neuer Fehlercode, keine
Änderung an `errors.json`.

### Verträglichkeit (Regeln aus #290)

| Kombination | Verhalten |
|---|---|
| neue PWA, alter Desktop | schickt den Wunsch, bekommt 90 und kein `window_max_days`; „Ältere laden“ zeigt „Dieser Desktop kann nicht mehr als 90 Tage liefern. Bitte die Desktop-App aktualisieren.“ |
| alte PWA, neuer Desktop | schickt keinen Wunsch, bekommt 90 (oder weniger bei kleiner Obergrenze); unbekannte Antwortfelder werden verworfen |
| Vorgänger-Fixtures | die Antwortform **vor** dieser Änderung wird eingefroren (`fixtures/compat/sync-response-pre-250.json`), die PWA muss sie weiter verstehen |

## Desktop

- `src/settings.py`: `mobile_window_max_days` (Standard 365), gerätelokal.
- `src/mobile_sync.py`: `DEFAULT_WINDOW_DAYS = 90`, `HARD_MAX_WINDOW_DAYS = 365`,
  `grant_window`. `parse_request` liest den Wunsch (tolerant). `build_response`
  bekommt das gewährte Fenster und die Obergrenze; das Sichtbarkeitsprädikat
  nutzt das gewährte Fenster statt der Konstante.
- `src/mobile_routes.py`: reicht die Einstellung durch (`ctx.settings`), liest
  sie bei **jedem** Abgleich neu — eine geänderte Obergrenze wirkt sofort, ohne
  Neustart der Handy-Instanz.
- `tab_mobile.py` / `tab_rules.py`: Auswahl „Verlauf auf dem Handy bis zu:
  30 / 90 / 180 / 365 Tage“ unter „Handy-Erfassung“, abhängig vom Schalter wie
  Port und Adresse; Hinweis „größere Fenster machen jeden Abgleich größer (365
  Tage ≈ 100 KB)“; `mobile_updates`/Validierung tolerant (Fremdwert → Standard).
- Gekappte Obergrenze wirkt auf bereits gewachsene Handys so: kleinere Antwort,
  die PWA räumt **saubere** Tage außerhalb auf, unübertragene bleiben (heutige
  Regel in `applyResponse`).

## PWA

- `store.js`: Meta `window_wish` (Standard 90, gerätelokal) und `window_max`
  (`null` = unbekannt/alter Desktop), beide aus bzw. für die Antwort.
- `sync.js`: die Anfrage trägt `window_days: window_wish`; `parseSyncResponse`
  liest `window_max_days` **tolerant** (fehlt/ungültig → `null`, kein
  Protokollfehler).
- Entscheidungen DOM-frei in einem neuen `window-policy.js`
  (getestet): `WINDOW_STEPS = [90, 180, 365]`, `stepFor(daysBack, max)` (kleinste
  Stufe, die die Zielwoche abdeckt, gedeckelt auf `max`), `canLoadOlder(...)`.
- Wochenansicht: liegt der Beginn der angezeigten Woche vor dem Fenster
  (`today − window_days`), zeigt sie statt leerer Tage den Hinweis „Ältere Zeiten
  sind noch nicht geladen.“ mit dem Knopf **„Ältere Zeiten laden“**. Tippen setzt
  `window_wish = stepFor(…)` und stößt einen Abgleich an; währenddessen läuft die
  gewohnte Statuszeile. Ist die Obergrenze erreicht oder unbekannt, steht statt
  des Knopfs der erklärende Text (s. Tabelle oben).
- Verbindungsdialog: Zeile „Verlauf“ — „180 Tage (Desktop erlaubt bis 365)“ — und
  „Auf 90 Tage zurücksetzen“ (nur wenn `window_wish > 90`). Zurücksetzen setzt
  den Wunsch und gleicht ab; die Aufräumregel wirft saubere Außentage weg.
- Der Editor warnt für Tage außerhalb weiter wie bisher (`outsideWindow` nutzt
  das gewährte Fenster).

## Fehler- und Randfälle

- **Gekürzt wegen der Menge:** die Wochenansicht sagt „Der Desktop liefert wegen der
  Datenmenge nur N Tage.“ (kein Knopf, der nichts bewirkt); ein späterer Abgleich
  liefert wieder mehr, sobald es das Budget zulässt.
- **Obergrenze am Desktop sinkt unter den Wunsch:** die Antwort gewährt weniger;
  die PWA zeigt „Der Desktop begrenzt den Verlauf auf N Tage.“ im Dialog. Der
  Wunsch bleibt gespeichert (steigt die Obergrenze wieder, gilt er wieder).
- **Handy lange offline (Self-Heal, `excluded`):** unverändert; ein größeres
  Fenster verliert dabei nichts zusätzlich, die Meldung bleibt gleich.
- **Sehr langsames WLAN / große Antwort:** der Abgleich hat schon einen Timeout
  mit eigener Fehlerart; die PWA bietet das Zurücksetzen auf 90 im Dialog an.
- **Größe der Antwort:** `MAX_ENTRIES` (400 Tage je Anfrage) und `MAX_BODY_BYTES`
  (1 MiB) begrenzen nur, was das Handy **sendet**; die Antwort hatte kein Limit —
  das ist das Mengenlimit oben. Auch die **Anfrage** wächst nicht mit dem Fenster:
  das Handy sendet nur seine unübertragenen Tage.

## Tests

- Python: `grant_window` (alle Randfälle, Obergrenze 30/90/365, Wunsch fehlt,
  ungültig, `bool`, zu groß), `parse_request` liest den Wunsch tolerant,
  `build_response` Fenster und Felder, Route liest die Einstellung je Abgleich,
  `mobile_updates`/Validierung, Einstellungs-Default.
- Vertrag: `sync-request.json` (Live) bekommt `window_days`, `sync-response.json`
  `window_max_days`; die Form-Tests prüfen beide Seiten. Eingefroren wird die
  Antwort **vor** der Änderung.
- PWA (`node --test`): `window-policy` (Stufen, Deckel, Randwochen), Store
  (Wunsch/Maximum persistieren), Request-Aufbau, tolerantes Parsen, Hinweistexte,
  Zurücksetzen räumt saubere Außentage und behält unübertragene.
- Im Browser (Dev-Server): zurückblättern, nachladen, Obergrenze am Desktop
  senken, zurücksetzen.

## Doku

`pwa/CLAUDE.md` (Fenster und Protokollfelder, `window-policy.js`), `src/CLAUDE.md`
(Route/Sync), `README.md` und `docs/known-limitations.md` (die Grenze „nur 90
Tage“ wird zu „bis zur eingestellten Obergrenze, höchstens 365“). Neue harte
Angaben der PWA-Doku (z. B. die Stufen) kommen in
`tests/test_pwa_claude_md_claims.py`.

## Abgrenzung (bleibt in #250)

Volle Historie und Seitenweise-Laden, Delta-Antworten, Randwochen-Kennzeichnung
der Wochensummen. Die Delta-Antwort ist die Voraussetzung für Fenster über 365
Tage, weil die PWA „Tag fehlt in der Antwort“ heute als Löschen deutet.

## Release

Der Desktop-Teil ist additiv; die Reihenfolge „Desktop zuerst“ aus #290 ist
eingehalten, weil die PWA ohne `window_max_days` nichts Neues versucht. Ein Release
ist nicht Teil dieser Arbeit.
