# Notiz am Slot — Design

Stand: 2026-11-23. Issue: Xveyn#519. Etappe 1 von 2 (Etappe 2, die Standardnotiz
je Kategorie, bekommt ein eigenes Design).

## Anlass

Wer bei wechselnden Kunden oder auf Montage arbeitet, müsste heute je Kunde eine
eigene Kategorie anlegen, damit die Arbeitszeit zuordenbar bleibt. Die
Kategorienliste wird damit unübersichtlich. Gewünscht ist eine Notiz, die eine
Kategorie verfeinert: Kategorie „Montage“, Notiz „Kunde Mustermann“.

## Ziele

- Ein Ist-Zeit-Slot trägt eine optionale, einzeilige **Notiz**.
- Die Notiz lässt sich am Desktop (Tages-Dialog), am Handy (Tages-Editor der PWA)
  und über die lokale API setzen und lesen.
- Sie erscheint überall dort, wo heute die Kategorie eines Slots steht: Tooltip,
  Löschen-Dialog, Konfliktansicht, Bericht (Mail-HTML und PDF), Webhook, lokale
  API, Wochenliste der PWA.
- Der Bericht kann die „Summe je Kategorie“ zusätzlich **je Notiz** aufschlüsseln,
  als eigene Option neben der Kategorie-Aufschlüsselung.
- **Abwärtskompatibilität ist die wichtigste Eigenschaft** (s. nächster
  Abschnitt).

## Nicht-Ziele

- Notizen an Reservierungen, am Urlaub oder am ganzen Tag.
- Die Übernahme-Regeln aus dem Issue („immer“, „für einen Zeitraum“): das ist
  Etappe 2, eine Vorbelegung an der Kategorie. Hinweis für später: sie braucht
  einen eigenen synchronisierten Einstellungs-Schlüssel und passt nicht in
  `category_times` (`mobile_settings.parse_settings` lehnt dort unbekannte
  Felder ab).
- Filtern des Berichts nach Notiz. Der Kategorie-Filter bleibt der einzige Filter.
- Notizen in der Teilen-Datei (`share.py`). Geteilt werden weiter nur die vier
  Slot-Felder.
- Notizen in den Auswertungen der lokalen API (`/v1/summary/…`).
- Wochenlimit, Pausenpflicht und Erinnerungen lesen die Notiz nicht.

## Anti-Ziele (was das Ergebnis zum Fehlschlag machte)

- Ein Versionssprung in einem Format: `sync.SCHEMA_VERSION` bleibt 4,
  `share.SCHEMA_VERSION` 3, das Handy-`PROTOCOL` 2,
  `webhook.PAYLOAD_SCHEMA_VERSION` 2, die IndexedDB-`VERSION` der PWA unverändert.
- Eine neue Fehlermeldung oder ein Datenverlust bei jemandem, der nur eine Seite
  aktualisiert hat (alter Desktop am Drive-Sync, alte gecachte PWA, alter
  Empfänger einer Teilen-Datei, bestehender Webhook-Empfänger).
- Ein verändertes Verhalten für Nutzer, die nie eine Notiz eintragen: derselbe
  Merge-Ausgang, dieselben Zeitstempel, bitgleicher Bericht und bitgleiches
  Webhook-Dokument.

## Wege, die zur Wahl standen

| | A: Feld im Slot | B: Feld im Slot + Erben | C: eigener Store `notes.json` |
|---|---|---|---|
| Slot-Format | fünftes Feld | fünftes Feld | unverändert |
| Alte Version speichert den Tag | Notizen des Tages weg | bleiben (gleiche Startzeit) | bleiben (gleiche Startzeit) |
| Sync | mit dem Tag | mit dem Tag, plus Erb-Regel | eigener Abschnitt mit eigenem LWW, Tombstones, Aufräumen |
| Konflikte | Notiz ist Teil des Tages | Notiz ist Teil des Tages | Notiz läuft neben dem Tag |

Gewählt wurde **B**: derselbe Schutz gegen alte Versionen wie C, aber der Tag
bleibt die eine Einheit für Sync, Konflikte und Journal. C hätte dauerhaft einen
zweiten synchronisierten Store mit eigenem Tombstone-Lebenszyklus gebraucht.

**Eine Anpassung an B, nach der Wahl gefunden:** die Notiz liegt nicht *im* Slot,
sondern **am Tag, je Startzeit** (s. „Datenformat“). Grund: eine ältere App
(≤ 1.28) baut die Teilen-Datei aus `Storage.get_all()`, und `sanitize_slot`
behält unbekannte Slot-Felder. Bekäme sie per Drive-Sync einen Slot mit Notiz-Feld
und teilte diesen Zeitraum, enthielte ihre Datei ein unbekanntes Feld, und jeder
Empfänger lehnte sie mit „unbekannte Felder“ ab. Das ließe sich in ausgelieferten
Versionen nicht mehr beheben. Unbekannte Felder **am Tag** verlassen eine alte App
dagegen an keiner Stelle: `_user_shape` reicht nur `{slots}` weiter. Alle übrigen
Eigenschaften von B bleiben, die Erb-Regel wird sogar einfacher.

## Datenformat (Datei `zeiterfassung.json` und Drive-Sync-Doc)

```json
"2026-11-03": {
  "slots": [
    {"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Montage"},
    {"start": "13:00", "end": "17:00", "pause": 30, "kategorie": "Büro"}
  ],
  "notes": {"08:00": "Kunde Mustermann"},
  "modified_at": "2026-11-03T16:02:11Z",
  "device_id": "…",
  "deleted": false
}
```

- Slots behalten exakt ihre vier Felder.
- `notes` bildet die **Startzeit** eines Slots auf seine Notiz ab. Die Startzeit
  ist je Tag eindeutig, weil sich Slots nicht überlappen dürfen. Der Index
  scheidet aus: die Reihenfolge ändert sich beim Speichern (#520).
- `notes` enthält nur nicht-leere Notizen und nur Startzeiten, zu denen der Tag
  einen Slot hat.
- **Der Schlüssel `notes` ist „klebrig“:** ein Schreiber setzt ihn, sobald der Tag
  Notizen hat **oder** der Stand, den er überschreibt, den Schlüssel schon trug
  (dann auch leer, `{}`). Daraus folgen drei Bedeutungen:
  - Schlüssel fehlt: der Schreiber wusste nichts von Notizen an diesem Tag (alte
    Version, oder neue Version an einem Tag, der nie welche hatte).
  - `{}`: die Notizen dieses Tages wurden bewusst entfernt.
  - gefüllt: die Notizen dieses Tages.

  Auf dieser Unterscheidung beruht die Erb-Regel. Tombstones tragen keine Notizen.
- **Ein Tag, der nie eine Notiz hatte, wird exakt so geschrieben wie heute.** Wer
  keine Notizen benutzt, hat dieselbe Datei und dasselbe Sync-Doc wie mit 1.28.
- Für alte Versionen ist `notes` ein unbekannter Schlüssel am Eintrag. Geprüft:
  `validate_remote_doc` und `apply_merge` verlangen nur die Pflichtfelder,
  `_repair_entry_values` und `_strip_for_candidate` behalten Zusatzschlüssel,
  `_merge_one` reicht den gewinnenden Eintrag unverändert weiter. **Eine
  Ausnahme** gibt es, s. „Gelöste Konflikte“: die Schleife, die Auflösungen
  anwendet, baut den Eintrag aus vier Schlüsseln neu.

## Regeln der Notiz

Ein neues Tk-freies Modul `src/slot_notes.py` ist die eine Stelle dafür, mit dem
Gegenstück `pwa/notes.js`; den Gleichlauf hält eine gemeinsame Fixture
(`pwa/test/fixtures/note-cases.json`, Muster `slot-order-cases.json`).

- Text, getrimmt, einzeilig: keine Zeichen der Unicode-Klassen `Cc`/`Cs` (wie bei
  Kategorienamen), höchstens `MAX_NOTE_LEN` = 200 Zeichen.
- **Eingaben** (lokale API, Handy) werden geprüft und bei Verstoß abgelehnt.
- **Gespeicherte Daten** sind Fremddaten und werden an der Lese-Grenze bereinigt,
  nie abgelehnt: kein Text → keine Notiz, Steuerzeichen entfernt, Überlänge
  gekürzt, Schlüssel ohne passenden Slot ignoriert.
- **Gruppierschlüssel** für Summen und Vorschläge: getrimmt und mit `lower()`
  gefaltet (nicht `casefold()`, damit Python und JavaScript gleich falten, wie in
  `slot_order`). Angezeigt wird die Schreibweise des ersten Vorkommens in
  Datumsreihenfolge.

## Lese- und Schreibgrenze in `Storage`

Innerhalb der App sieht jeder Leser die Notiz **am Slot**; das Format mit `notes`
am Tag kennen nur `Storage` und der Sync.

- `get`/`get_all` liefern einen Slot mit `notiz`, **wenn er eine Notiz hat**; ohne
  Notiz fehlt der Schlüssel, der Slot sieht dann exakt aus wie heute (Leser
  nehmen `slot.get("notiz", "")`). Ein `notiz`, das roh im gespeicherten Slot
  steht (Handbearbeitung), wird an der Lese-Grenze verworfen: die einzige Quelle
  ist `notes` am Tag.
- `save`/`save_many` nehmen `notiz` aus den Slots und schreiben `notes` nach der
  Regel oben (gesetzt, wenn Notizen da sind oder der bisherige Stand den
  Schlüssel trug).
- **Ein Slot ohne Schlüssel `notiz` erbt beim Speichern** die Notiz des bisher
  gespeicherten Slots mit derselben Startzeit. Ein Slot mit Schlüssel (auch `""`)
  gilt wie angegeben. Damit löscht kein interner Schreiber, der Notizen nicht
  kennt, versehentlich welche. Vorbild: `reservations.inherit_pause`.
- `get_all_raw` und `apply_merge` bleiben das Rohformat für den Sync.
- Wer ein festes Format ausgibt, projiziert weiter selbst (s. „Ausgabewege“).

## Erb-Regel im Merge (`sync.py`)

Der Fall, den sie abdeckt: eine alte Version speichert einen Tag neu. Sie baut den
Eintrag aus vier Schlüsseln, `notes` fehlt, und ihr neuerer Stempel gewinnt.

Vor dem Vergleich zweier Stände desselben Tages (beide vorhanden, keiner
gelöscht):

1. Fehlt genau einer Seite der Schlüssel `notes`, erbt sie von der anderen: jede
   Notiz, deren Startzeit unter ihren eigenen Slots vorkommt. Sie bekommt den
   Schlüssel auch dann, wenn dabei nichts übrig bleibt (`{}`), und gilt als
   „ergänzt“. Fehlt der Schlüssel beiden Seiten, geschieht nichts.
2. Verglichen wird mit einer Signatur, die die Notizen einschließt
   (`_values_equal_entry`). Gewinner und Konflikt werden wie bisher bestimmt;
   die Konflikt-Kandidaten tragen die ergänzten Stände.
3. Trägt das Ergebnis Stempel und Gerät der ergänzten Seite (sie hat gewonnen,
   oder beide Seiten haben denselben Stempel und dasselbe Gerät), bekommt es den
   Stempel `modified_at + 1 s` (Gerät unverändert). Ohne die Anhebung hätten der
   ergänzte und der ursprüngliche Stand denselben Stempel und dasselbe Gerät; das
   alte Gerät hielte sie für gleich, behielte über den Wert-Tiebreak seinen
   eigenen (die Textform ohne `notes` sortiert höher) und lüde ihn wieder hoch.
   Die Drive-Datei kippte dann bei jedem Sync.

Eigenschaften, die Tests festhalten müssen:

- **Symmetrie** bleibt: `merge(A, B)` und `merge(B, A)` liefern dasselbe
  (`tests/test_sync_determinism.py`, um Notizen erweitert).
- **Zwei neue Geräte**, die denselben alten Stand unabhängig ergänzen, erzeugen
  denselben Eintrag (kein Konflikt).
- **Bewusst gelöscht bleibt gelöscht:** ein Stand mit `notes: {}` erbt nichts,
  und ein schlüsselloser neuerer Stand erbt von ihm das leere `{}`.
- **Ohne Notizen ändert sich nichts:** fehlt `notes` auf beiden Seiten, sind
  Gewinner, Stempel und Konflikte dieselben wie heute. Für einen Bestand, der nie
  eine Notiz gesehen hat, ist das immer der Fall.
- Alte Geräte vergleichen weiter nur die vier Felder. Eine reine Notiz-Änderung
  ist für sie „gleich“, sie übernehmen dann den neueren Stempel samt `notes`.

Dem Bauenden überlassen: wie mit einem Stempel umzugehen ist, der sich nicht als
`%Y-%m-%dT%H:%M:%SZ` lesen lässt (Vorschlag: dann nicht erben).

### Gelöste Konflikte

`merge` wendet am Ende jede gelöste Konflikt-Auflösung erneut an und baut den
Eintrag dabei aus `resolution` neu. Das betrifft die Notizen an drei Stellen:

- **Format:** eine Auflösung trägt `notes` auf oberster Ebene neben `slots` und
  `deleted`, nie im Slot (sonst gelangten Slot-Felder über diese Schleife in den
  Bestand alter Geräte). Neue Versionen schreiben sie beim Auflösen mit und
  übernehmen sie beim Anwenden.
- **Auflösung ohne `notes`** (ein altes Gerät hat aufgelöst; sein Dialog reicht
  nur `slots` und `deleted` weiter): sie bekommt die Notizen des Kandidaten,
  dessen Slots der Auflösung entsprechen. Die Kandidaten tragen `notes`, weil
  `_strip_for_candidate` alle Schlüssel behält. Fehlt diesem Kandidaten der
  Schlüssel, erbt er nach der Regel oben vom anderen Kandidaten; passt kein
  Kandidat, vom Stand, den die Auflösung ersetzt. Geerbt wird also nie blind vom
  vorläufigen Gewinner, sonst hinge die Notiz der verworfenen Version am
  gewählten Slot. Passen beide Kandidaten (sie unterscheiden sich nur in der
  Notiz), gilt der jüngere.
- **Alte Geräte entfernen `notes` in dieser Schleife.** Sie bauen den Eintrag aus
  vier Schlüsseln und ersetzen den vorhandenen auch bei gleichem Stempel, und der
  Gleichstand ist der Normalfall (`resolve_conflict` stempelt Auflösung und
  Eintrag in derselben Sekunde). Solange der Konflikt nicht kompaktiert ist,
  schreibt ein altes Gerät den Tag also bei jedem Sync ohne `notes` zurück. Das
  heilt Schritt 3 oben: der ergänzte Stand ist danach eine Sekunde jünger als die
  Auflösung, und die Schleife des alten Geräts ersetzt ihn nicht mehr. Dieser
  Ablauf braucht einen eigenen Test.

## Ausgabewege

| Weg | Form | Verhalten ohne Notiz |
|---|---|---|
| Lokale API, `GET` | `notiz` an jedem Slot, immer vorhanden | `""` |
| Lokale API, `PUT` | `notiz` optional je Slot; fehlt es, erbt der Slot (gleiche Startzeit); Verstoß gegen die Regeln ist `422 invalid_note` | wie heute |
| Handy-Abgleich, Antwort | `notiz` an jedem Slot (auch in den Konflikt-Kandidaten) und die Fähigkeit `slot_notes: true` | `""` |
| Handy-Abgleich, Anfrage | `notiz` optional je Slot, s. unten | wie heute |
| Webhook | `notiz` am Slot **nur, wenn nicht leer** | Dokument bitgleich zu heute |
| Teilen-Datei | nie; der Export projiziert ausdrücklich auf die vier Felder | unverändert v3 |
| Bericht | s. „Bericht“ | bitgleich zu heute |

**Handy-Abgleich.** Der Desktop ist die Seite, die schützt. Eine PWA sendet
`notiz` nur, wenn die letzte Antwort `slot_notes` nannte (Feature-Erkennung,
`pwa/CLAUDE.md` „Kompatibilität“, Regel 2), und dann an **allen** Slots eines
Tages. Am Desktop gilt je Tag: tragen alle Slots `notiz`, bekommt der Eintrag des
Handys `notes` nach derselben Regel wie beim Speichern (gesetzt, wenn Notizen da
sind oder der Tag am Desktop den Schlüssel schon trägt); trägt keiner `notiz`,
bleibt der Eintrag ohne `notes`, und die Erb-Regel im Merge greift, weil das
Handy dort die Seite `local` ist. Gemischt ist `422 invalid_entry`. Eine alte gecachte PWA, die einen
Tag mit Notiz bearbeitet, löscht die Notiz damit nicht. Vor der Änderung der
Live-Beispiele werden die Vorgänger eingefroren
(`compat/sync-request-pre-notes.json`, `compat/sync-response-pre-notes.json`).

**Import einer Teilen-Datei** schreibt über `save_many` Slots ohne `notiz`; ein
importierter Tag behält deshalb die Notizen der Slots, deren Startzeit bleibt.

## Desktop-Oberfläche

- **Tages-Dialog, Ist-Block:** jede Zeile bekommt hinter der Kategorie ein
  Notizfeld (Breite in Zeichen, nicht in Pixeln). Es schlägt die Notizen vor, die
  mit der gewählten Kategorie schon benutzt wurden (neueste zuerst, höchstens 20,
  je Gruppierschlüssel einmal), freier Text bleibt möglich. Der
  Reservierungs-Block bekommt kein Feld. Die Kategorie-Auswahl verändert die
  Notiz nicht (das wäre Etappe 2).
- **Tooltip und Löschen-Dialog:** `08:00-12:00  Montage · Kunde Mustermann`.
  Die Kalenderzelle selbst bleibt unverändert.
- **Konfliktdialog:** die Notiz ist ein weiteres Feld je Slot und wird wie die
  übrigen markiert, wenn sie sich unterscheidet (`conflict_view`).
- Im Modus „Eigene Reihenfolge“ wandert die Notiz mit ihrer Zeile.

## Bericht (Mail-HTML und PDF)

- **Zeile:** die Notiz steht in der Kategorie-Zelle, `Montage · Kunde Mustermann`
  (ohne Kategorie nur die Notiz). Keine neue Spalte, die Spaltenbreiten bleiben.
  Die Notiz in der Zeile ist nicht abschaltbar, wie die Kategorie.
- **Aufschlüsselung:** neue Option „Nach Notiz aufschlüsseln“ im Zeitraum-Baustein
  (`period_picker`), unter „Nach Kategorie aufschlüsseln“ und nur wählbar, wenn
  diese an ist; Vorgabe aus, wie dort. Sie gilt für Senden und Export.

  ```
  Kategorie               Stunden
  Büro                      8.0h
  Montage                  32.0h
     Kunde Mustermann      20.0h
     Kunde Müller           8.0h
     (ohne Notiz)           4.0h
  ```

  Unterzeilen bekommt nur eine Kategorie, in der mindestens ein Slot eine Notiz
  trägt. Sortiert nach Gruppierschlüssel, „(ohne Notiz)“ zuletzt. Summiert wird
  über **Minuten** (Regel „Summen nur über Minuten“); die Unterzeilen einer
  Kategorie ergeben exakt deren Summe. Sind alle Slots ohne Kategorie, einige
  aber mit Notiz, erscheint die Tabelle mit „(ohne Kategorie)“ und Unterzeilen
  (heute entfällt sie in diesem Fall).
- Gerechnet wird wie bisher auf dem zeitraum- und kategoriegefilterten
  Ausschnitt.

## Handy-PWA

- Tages-Editor (Reiter Ist-Zeit): ein Notizfeld je Slot mit Vorschlägen aus den
  lokal bekannten Notizen der Kategorie. Das Feld erscheint nur, wenn der Desktop
  `slot_notes` nennt; sonst sendet und zeigt die PWA keine Notiz.
- Wochenliste und Konfliktversionen zeigen die Notiz neben der Kategorie.
- Die PWA hält die Notiz in ihrem eigenen Speicher am Slot (`notiz`); ihre
  Änderungs-Signatur schließt sie ein, damit eine reine Notiz-Änderung als
  Änderung gilt.

## Reihenfolge der Umsetzung

Drei PRs, jeder für sich mergebar:

1. **Kern am Desktop, ohne Oberfläche:** `slot_notes`, Lese-/Schreibgrenze in
   `Storage`, Erb-Regel im Merge, lokale API, Handy-Abgleich samt Fähigkeit und
   eingefrorenen Vorgängern, Webhook, Projektion im Teilen-Export.
2. **Desktop-Oberfläche und Bericht:** Tages-Dialog, Tooltip, Löschen-Dialog,
   Konfliktdialog, Berichtszeile und Aufschlüsselung. README mit
   `*(ab --VERSION--)*`.
3. **PWA.** Kann unabhängig von einem Desktop-Release ausgerollt werden, weil sie
   die Funktion an `slot_notes` erkennt.

Die Doku (`CLAUDE.md` in Wurzel, `src/`, `pwa/`, `docs/known-limitations.md`)
zieht jeder PR für seinen Teil mit. Es ist eine neue Funktion, das Release wird
ein Minor.

## Bekannte Grenzen

- Ändert eine **alte** Version die Startzeit eines Slots oder löscht ihn, geht
  dessen Notiz verloren (die Zuordnung hängt an der Startzeit). Tauscht sie die
  Zeiten zweier Slots, wandern die Notizen mit den Zeiten.
- Zwischen zwei neuen Geräten gibt es diese Grenze nicht: sie schreiben `notes`
  an jedem Tag mit, der Notizen hat oder hatte.
- **Eine gelöschte Notiz kann in einer gemischten Flotte zurückkommen.** Dafür
  braucht es drei Geräte in dieser Reihenfolge: ein neues Gerät entfernt die
  Notiz, ein altes speichert denselben Tag danach neu (der Schlüssel fehlt dann
  im Sync-Doc), und ein drittes, das noch den Stand mit Notiz hält, synchronisiert
  vor dem ersten. Es erbt die Notiz und macht sie zum neuesten Stand. Synchronisiert
  das erste Gerät zuerst, bleibt sie gelöscht. Ganz schließen ließe sich das nur
  mit eigenen Zeitstempeln je Notiz.
- Löst ein **altes** Gerät einen Konflikt auf, in dem sich die Stände nur in der
  Notiz unterscheiden, sieht es zwei gleiche Karten; es gilt dann der jüngere
  Stand.
- Die Anhebung um eine Sekunde macht den ergänzten Stand zum neuesten; bei stark
  falsch gehenden Uhren kann daraus wie heute schon ein unnötiger Konflikt
  entstehen (Audit N2).
- Geteilte Arbeitszeiten kommen ohne Notizen an.

## Was Tests mindestens zeigen müssen

- „Alter Schreiber“ als Testhelfer (schreibt einen Tag mit vier Schlüsseln, ohne
  `notes`): Pause geändert → Notiz bleibt, Stempel + 1 s; Startzeit geändert →
  Notiz weg; alter Desktop und alte PWA.
- Gelöste Konflikte: das alte Gerät wendet eine Auflösung mit gleichem Stempel
  an und entfernt `notes`, das neue ergänzt und hebt an, danach bleibt der Stand
  auf beiden stehen; eine Auflösung ohne `notes` bekommt die Notizen des
  gewählten Kandidaten, nicht die des verworfenen.
- Die Regressionen der Anti-Ziele: Merge-Ausgang ohne Notizen identisch zu heute;
  ein Tag ohne Notiz wird Byte für Byte wie heute geschrieben;
  Bericht und Webhook ohne Notizen bitgleich; Teilen-Export ohne Notiz-Feld, auch
  wenn der Tag Notizen hat; eine nach altem Muster gebaute Teilen-Datei aus einem
  Bestand mit `notes` besteht den v3-Validator.
- Vertragstests des Handy-Abgleichs gegen die eingefrorenen Vorgänger in beiden
  Richtungen.
- Gleichlauf Python/JavaScript der Notiz-Regeln über die gemeinsame Fixture.

## Meine Entscheidungen (nicht ausdrücklich abgestimmt)

1. Notiz am Tag je Startzeit statt im Slot (Begründung oben).
2. Notiz in der Berichtszeile immer sichtbar; nur die Aufschlüsselung ist
   optional.
3. Webhook nennt `notiz` nur, wenn nicht leer; die lokale API immer.
4. Teilen ohne Notizen.
5. Grenzen: einzeilig, 200 Zeichen.
6. Vorschläge im Eingabefeld aus bereits benutzten Notizen der Kategorie.
7. Auswertungen der lokalen API und Reservierungen bleiben ohne Notiz.
8. Der Schlüssel `notes` wird nur an Tagen geschrieben, die Notizen haben oder
   hatten. Tage ohne Notiz bleiben im Format unverändert.
9. Eine Auflösung ohne Notizen erbt vom gewählten Kandidaten; die Rückkehr einer
   gelöschten Notiz in der Drei-Geräte-Reihenfolge ist als Grenze akzeptiert.
