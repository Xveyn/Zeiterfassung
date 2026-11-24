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
  Notizen hat **oder** der Stand, den er überschreibt, den Schlüssel schon trug,
  auch ein Tombstone (dann leer, `{}`). Daraus folgen drei Bedeutungen:
  - Schlüssel fehlt: der Schreiber wusste nichts von Notizen an diesem Tag (alte
    Version, oder neue Version an einem Tag, der den Schlüssel nie trug, auch nicht
    vor einem Löschen).
  - `{}`: die Notizen dieses Tages wurden bewusst entfernt.
  - gefüllt: die Notizen dieses Tages.

  Auf dieser Unterscheidung beruht die Erb-Regel. **Tombstones tragen keine Notizen,
  aber den Schlüssel:** trug der gelöschte Stand ihn, steht im Tombstone `notes: {}`
  (Löschen am Desktop, Löschen am Handy, als gelöscht angewendete Auflösung). Ein
  danach neu angelegter Tag trägt den Schlüssel dann ebenfalls und erbt nichts aus
  dem Tombstone: am neuen Desktop schreibt `Storage` ihn direkt, einen ohne Schlüssel
  neu angelegten Tag (Handy, altes Gerät) ergänzt der Merge mit `{}`, sobald das
  mergende Gerät den Tombstone hält (s. „Erb-Regel im Merge“). Ohne das läse der Merge
  den neu angelegten Tag als Stand eines Schreibers, der nichts von Notizen weiß, und
  füllte die alte Notiz von einem Gerät nach, das noch den Stand vor dem Löschen hält.
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
  Kategorienamen) und keine Zeilentrenner `Zl`/`Zp`, höchstens `MAX_NOTE_LEN` = 200
  Zeichen (Code Points, nicht UTF-16-Einheiten). Getrimmt wird genau wie mit
  JavaScripts `trim()`, also auch U+FEFF, das Pythons `strip()` stehen ließe.
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
  Schlüssel trug, auch ein Tombstone). `delete` schreibt `notes: {}` in den
  Tombstone, wenn der gelöschte Stand den Schlüssel trug. Beide nehmen
  `notes_known`: dann schreiben sie den Schlüssel auch ohne Vorgänger, der ihn trug
  (Aufrufer ist `resolve_conflict`, s. „Gelöste Konflikte“); ohne das Argument bleibt
  alles wie beschrieben, `save_many` kennt es nicht.
- **Ein Slot ohne Schlüssel `notiz` erbt beim Speichern** die Notiz des bisher
  gespeicherten Slots mit derselben Startzeit. Ein Slot mit Schlüssel (auch `""`)
  gilt wie angegeben. Damit löscht kein interner Schreiber, der Notizen nicht
  kennt, versehentlich welche. Vorbild: `reservations.inherit_pause`.
- `get_all_raw` und `apply_merge` bleiben das Rohformat für den Sync.
- Wer ein festes Format ausgibt, projiziert weiter selbst (s. „Ausgabewege“).

## Erb-Regel im Merge (`sync.py`)

Der Fall, den sie abdeckt: eine alte Version speichert einen Tag neu. Sie baut den
Eintrag aus vier Schlüsseln, `notes` fehlt, und ihr neuerer Stempel gewinnt.

Vor dem Vergleich zweier Stände desselben Tages (beide vorhanden):

1. Fehlt genau einer Seite der Schlüssel `notes` und ist sie nicht gelöscht, erbt sie
   von der anderen: jede Notiz, deren Startzeit unter ihren eigenen Slots vorkommt.
   Sie bekommt den Schlüssel auch dann, wenn dabei nichts übrig bleibt (`{}`), und
   gilt als „ergänzt“. Ist die andere Seite ein Tombstone mit Schlüssel, bekommt sie
   `{}`: ein Tombstone vererbt keine Notizen, nur die Markierung (ein ohne Schlüssel
   neu angelegter Tag, s. „Datenformat“). Ein gelöschter Stand wird nie ergänzt.
   Fehlt der Schlüssel beiden Seiten, geschieht nichts.
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
  und ein schlüsselloser neuerer Stand erbt von ihm das leere `{}`. Das gilt auch
  für einen gelöschten Tag: sein Tombstone behält den Schlüssel, ein neu angelegter
  Tag trägt ihn (oder bekommt ihn im Merge vom Tombstone) und bekommt die alte Notiz
  nicht zurück. Der Tombstone selbst wird nie ergänzt und gewinnt oder verliert nach
  LWW. Ausnahmen bei alten Geräten und nach der Kompaktierung: s. „Bekannte Grenzen“.
- **Ohne Notizen ändert sich nichts:** fehlt `notes` auf beiden Seiten, sind
  Gewinner, Stempel und Konflikte dieselben wie heute. Für einen Bestand, der nie
  eine Notiz gesehen hat, ist das immer der Fall.
- Alte Geräte vergleichen weiter nur die vier Felder. Eine reine Notiz-Änderung
  ist für sie „gleich“, sie übernehmen dann den neueren Stempel samt `notes`.

Ein Stempel, der sich nicht anheben lässt (unlesbar, am Ende des Bereichs, Jahr vor
1000), bedeutet: keine Erbschaft.

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
  Kandidat, vom Stand, den die Auflösung ersetzt (hat weder der passende noch ein
  anderer Kandidat den Schlüssel, kommen die Notizen vom ersetzten Eintrag). Geerbt
  wird also nie blind vom vorläufigen Gewinner, sonst hinge die Notiz der verworfenen Version am
  gewählten Slot. Passen beide Kandidaten (sie unterscheiden sich nur in der
  Notiz), gilt der jüngere.
- **Je Tag gilt nur die jüngste Auflösung** (dieselbe LWW-Ordnung wie überall), und
  der Rückgriff auf den ersetzten Stand liest den Eintrag, wie er **vor allen
  Auflösungen** war, nie einen Zwischenstand der Schleife. Sonst hinge das Ergebnis
  an der Reihenfolge zweier Auflösungen für denselben Tag; die Symmetrie ist bindend.
  Geordnet wird nach dem, was die Auflösung selbst trägt (Zeitpunkt, Gerät, Slots,
  `deleted`, eigene `notes`; bei Gleichstand die Konflikt-ID), nicht nach abgeleiteten
  Notizen: die hängen am gemergten Eintrag, der sich durch das Anwenden ändert, und ein
  zweiter Merge wählte sonst die andere von zwei gleich gestempelten Auflösungen.
  Abgeleitet wird nur für die gewählte.
- **Ein Eintrag ohne `notes` erbt von der jüngsten Auflösung des Tages, wenn er deren
  Stempel und Gerät trägt** (`sync._resolve_entry`): genau diese Form baut die Schleife
  eines alten Geräts aus vier Schlüsseln. Er wird dabei um eine Sekunde angehoben, wenn er
  danach noch mit seinem Stempel und Gerät gewinnt. Nötig, wenn beide Seiten nur den Stand
  halten, den ein altes Gerät gestrippt hat. Ein anders gestempelter Eintrag ohne `notes`
  ist ein späterer Schreibvorgang (etwa ein gelöschter und neu angelegter Tag) und erbt
  nicht. Eine als gelöscht angewendete Auflösung trägt `notes: {}`, wenn sie selbst, der
  ersetzte Stand oder ein Kandidat den Schlüssel trägt.
- **Beim Auflösen stimmen Tag und Auflösung im Schlüssel überein** (`resolve_conflict`).
  Der Schlüssel gilt als bekannt, wenn der gespeicherte Stand oder ein Kandidat des
  Konflikts ihn trägt oder die Wahl eine nicht leere Notiz hat (am Slot oder unter
  `notes`); dann schreiben `Storage.save`/`delete` ihn mit `notes_known`. Die Auflösung
  trägt `notes` genau dann, wenn der eben geschriebene Tag oder Tombstone ihn trägt, mit
  dessen Notizen (`{}` beim Tombstone), sonst gar nicht, was der Aufrufer auch übergibt.
  Sonst schriebe ein als gelöscht aufgelöster Tag ohne Schlüssel einen Tombstone aus vier
  Schlüsseln, der bei gleichem Stempel über die Textform den Kandidaten mit Schlüssel
  schlägt (die Markierung ginge auf jedem Gerät verloren), und eine leere Notiz an einem
  Tag ohne Notizen ergänzte den Tag im nächsten Merge aus der Auflösung und höbe ihn auf
  jedem Gerät an.
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
| Lokale API, `PUT` | `notiz` optional je Slot, nur an Ist-Zeit-Slots (Reservierungs-Slots lehnen `notiz` weiter ab, `parse_slots(..., allow_note=…)`); fehlt es, erbt der Slot (gleiche Startzeit); Verstoß gegen die Regeln ist `422 invalid_note` | wie heute |
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
(`compat/sync-request-pre-notes.json`, `compat/sync-response-pre-notes.json`). Der
Zeitpunkt: das Live-Beispiel der Antwort ändert sich mit dem Desktop-Kern (PR 1), dort
wird `sync-response-pre-notes.json` eingefroren; das Live-Beispiel der Anfrage ändert
sich erst mit der PWA (PR 3), dort wird auch `sync-request-pre-notes.json` eingefroren.

**Import einer Teilen-Datei** schreibt über `save_many` Slots ohne `notiz`; ein
importierter Tag behält deshalb die Notizen der Slots, deren Startzeit bleibt.

## Desktop-Oberfläche

- **Tages-Dialog, Ist-Block:** jede Zeile bekommt hinter der Kategorie ein
  Notizfeld (Breite in Zeichen, nicht in Pixeln). Es schlägt die schon benutzten
  Notizen vor: zuerst die der gewählten Kategorie, danach alle übrigen, je neueste
  zuerst, zusammen höchstens 20, je Gruppierschlüssel einmal (eine Notiz wie ein
  Kunde oder Termin kommt an einem anderen Tag oft unter einer anderen Kategorie
  wieder); freier Text bleibt möglich. Der
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
  an jedem Tag mit, der Notizen hat oder hatte, auch über ein Löschen hinweg.
- **Eine gelöschte oder geänderte Notiz kann in einer gemischten Flotte
  zurückkommen.** Dafür braucht es drei Geräte in dieser Reihenfolge: ein neues
  Gerät entfernt oder ändert die Notiz, ein altes speichert denselben Tag danach
  neu (der Schlüssel fehlt dann im Sync-Doc), und ein drittes neues, das noch den
  Stand mit der alten Notiz hält, synchronisiert vor dem ersten. Es erbt die alte
  Notiz und macht sie zum neuesten Stand; alle Geräte enden ohne Konflikt bei der
  alten Notiz, die Änderung des ersten ist spurlos weg. Synchronisiert das erste
  Gerät zuerst, bleibt seine Fassung. Ganz schließen ließe sich das nur mit
  eigenen Zeitstempeln je Notiz.
- Das alte Gerät braucht dafür keine Bedienung: solange für den Tag ein gelöster
  Konflikt in der Liste steht, baut seine Schleife über die Auflösungen den Tag bei
  jedem Sync aus vier Schlüsseln neu.
- Den Schlüssel behalten die Löschungen am neuen Desktop, am Handy (über den
  Desktop) und eine als gelöscht aufgelöste Konflikt-Auflösung nach der Regel in
  „Gelöste Konflikte“. Ein Tombstone eines **alten** Geräts hat vier Schlüssel,
  ebenso einer, den die Auflösungs-Schleife eines alten Geräts neu baut (er gewinnt
  bei gleichem Stempel über die Textform). Ein danach neu angelegter Tag ohne
  Schlüssel kann von einem Gerät, das noch einen Stand mit Notiz hält, die alte Notiz
  zurückbekommen.
- Einen ohne Schlüssel neu angelegten Tag (Handy, altes Gerät) ergänzt nur ein Gerät,
  das den Tombstone mit Schlüssel hält. Synchronisiert vorher ein Gerät, das noch den
  Stand mit Notiz von vor dem Löschen hält, erbt der neue Tag die alte Notiz (dieselbe
  Reihenfolge-Abhängigkeit wie oben).
- Die Kompaktierung entfernt abgeschlossene Tombstones samt Markierung. Ein danach neu
  angelegter Tag wird ohne Schlüssel geschrieben, und ein Gerät, das seit vor dem
  Löschen offline war, kann die alte Notiz zurückbringen.
- Löst ein **altes** Gerät einen Konflikt auf, in dem sich die Stände nur in der
  Notiz unterscheiden, sieht es zwei gleiche Karten; es gilt dann der jüngere
  Stand.
- Die Anhebung um eine Sekunde macht den ergänzten Stand zum neuesten. Schon eine
  Sekunde reicht für einen unnötigen Konflikt: zeigt die Uhr eines Handys etwa eine
  Sekunde mehr als die des Desktops (oder läuft der Abgleich in derselben Sekunde wie
  das Speichern), ist der Stempel eines Tages mit Notiz danach jünger als der
  Abgleich-Zeitpunkt (`last_pull_at`), und die nächste Änderung einer PWA ohne `notiz`
  an diesem Tag wird ein Konflikt „Handy gegen Handy“ (Audit N2).
- Geteilte Arbeitszeiten kommen ohne Notizen an.
- Schreibt ein altes Gerät einen Tag genau eine Sekunde, bevor der Nutzer auf einem
  anderen Gerät den Konflikt für diesen Tag auflöst, kann die Anhebung um eine Sekunde
  den alten Stand auf den Stempel der Auflösung heben; dann entscheidet die Geräte-ID,
  und der alte Wert kann den aufgelösten in den Einträgen ersetzen (der Konflikt-
  Datensatz bleibt, ohne Notizen hätte die Auflösung gewonnen). Das geschieht auf einem
  neuen Gerät, das den alten Stand im selben Merge sieht, in dem es die Auflösung erst
  anwendet. Schreibt das alte Gerät in derselben Sekunde wie die Auflösung, entscheidet
  ohne Notizen die Geräte-ID, mit Notizen gewinnt der angehobene alte Stand immer.
  Symmetrisch und stabil, braucht eine gemischte Flotte mit Notizen; bewusst nur
  dokumentiert (`docs/known-limitations.md`). Möglicher Fix: die Anhebung erst nach den
  Auflösungen und nur, wenn der Eintrag danach noch der Gewinner ist.

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
6. Vorschläge im Eingabefeld aus bereits benutzten Notizen, die der Kategorie zuerst.
7. Auswertungen der lokalen API und Reservierungen bleiben ohne Notiz.
8. Der Schlüssel `notes` wird nur an Tagen geschrieben, die Notizen haben oder
   hatten. Tage ohne Notiz bleiben im Format unverändert.
9. Eine Auflösung ohne Notizen erbt vom gewählten Kandidaten; die Rückkehr einer
   gelöschten Notiz in der Drei-Geräte-Reihenfolge ist als Grenze akzeptiert.
10. Das Notizfeld im Tages-Dialog trägt die gedämpfte Beschriftung „Notiz:“ davor
    (ein leeres Feld ohne Beschriftung erklärt sich nicht) und ist 24 Zeichen breit.
    Eine ungültige Eingabe (über 200 Zeichen, Zeilenumbruch, Steuerzeichen) meldet der
    Dialog beim Speichern mit einem Satz und speichert nichts; gekürzt wird nie still.
11. Tooltip und Löschen-Dialog kürzen die Notiz auf 60 Zeichen mit „…“ (beide
    brechen nicht um); Konfliktdialog und Bericht zeigen sie ganz.
12. „Nach Notiz aufschlüsseln“ wird nur gebaut, wenn der Bestand überhaupt eine Notiz
    hat (wie „Urlaub ausweisen“): wer keine Notizen benutzt, sieht den Dialog unverändert.
13. Der Konfliktdialog übergibt beim Auflösen die Notizen der gewählten Karte
    ausdrücklich. Ohne das gälte bei zwei Ständen, die sich nur in der Notiz
    unterscheiden, immer der jüngere, auch wenn der Nutzer den älteren wählt.
    Eine Karte, deren Stand den Schlüssel `notes` nicht trägt (alte Version), zeigt die
    Notizen, die sie beim Auflösen erbt: die der anderen Karte an gleicher Startzeit.
