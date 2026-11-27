# Krankheitstage — Design

Stand: 2026-11-27. Issue: Xveyn#521. Folge-Issue: Xveyn#548 (Urlaub später ebenfalls in den
Sync). Umsetzung als gestapelte PRs auf `chore/neues-app-icon` (PR Xveyn#547), Branch
`feat/krankheitstage`; das Feature geht mit dem nächsten Release hinaus, vorher ausgiebig
getestet und reviewt.

Die Analyse im Issue stammt vom Stand 1.28.0 und schlug einen **gerätelokalen** Store vor. Das
ist überholt: Krankheitstage werden **synchronisiert**, zwischen Desktops und mit dem Handy.
Wo dieses Dokument dem Issue widerspricht, gilt dieses Dokument.

## Anlass

Wer nach Stunden abrechnet (Werkstudent, Minijob, Teilzeit), muss Krankheitstage dem
Arbeitgeber melden; sie werden fortgezahlt wie die Stunden, die an dem Tag angefallen wären.
Heute kennt die App dafür nichts: weder eine Markierung im Kalender noch eine Zeile im Bericht.
Behelf wäre eine Kategorie „Krank“ an der Ist-Zeit, und genau das soll es nicht sein (s.
„Wege“).

## Ziele

- Ein Kalendertag lässt sich als **Krankheitstag** markieren, einzeln oder als Zeitraum.
  Krankheit betrifft immer den **ganzen Tag**, nie einen Slot.
- Jeder Krankheitstag trägt die **Stunden**, die an ihm fortgezahlt werden (Minuten,
  vorbelegt, je Tag änderbar).
- Krankheitstage reisen **per Drive-Sync** zwischen Desktops und **zum Handy**; das Handy kann
  sie auch **eintragen und entfernen**.
- Sie erscheinen im Kalender (Desktop und PWA), auf Wunsch im Bericht (Mail-HTML, PDF), im
  Webhook und in der lokalen API.
- **Abwärtskompatibilität ist die wichtigste Eigenschaft** (s. „Abwärtskompatibilität“).

## Nicht-Ziele

- Diagnose, Freitext, Name je Krankheitsphase, Anhang der AU. Höchstens ein reiner Hinweistext
  (s. „Desktop-Oberfläche“).
- Push in den Google-Kalender. Auch kein Hinweis-Termin „Abwesend“.
- Krankheitstage in der Teilen-Datei (`share.py`).
- Erinnerungen zur AU-Frist (Desktop-Toast oder Web-Push). Der Relay sähe Zeitplan-IDs und
  `fire_at` im Klartext.
- Reservierungs-Erinnerungen an Krankheitstagen eigens unterdrücken. Der Weg dorthin ist,
  die Reservierungen beim Krankmelden zu löschen (s. „Regeln“).
- Den Urlaub synchronisieren (Xveyn#548).
- Stunden eines Krankheitstags **am Handy** bearbeiten. Das Handy markiert Tage; die Stunden
  rechnet der Desktop (s. „Handy“).
- Wochenlimit, Pausenpflicht, Footer-Summe des Kalenders: sie zählen Krankheit nicht.

## Anti-Ziele (was das Ergebnis zum Fehlschlag machte)

- Ein Versionssprung: `sync.SCHEMA_VERSION` bleibt 4, `share.SCHEMA_VERSION` 3, das
  Handy-`PROTOCOL` 2, `webhook.PAYLOAD_SCHEMA_VERSION` **2** (das Issue empfahl 3; verworfen,
  weil Empfänger, die genau auf 2 prüfen, sonst brechen).
- Ein Gerät mit älterer Version (Desktop bis 1.29, gecachte PWA) verliert Daten, bekommt eine
  neue Fehlermeldung oder fliegt aus dem Sync.
- Eine geänderte Ausgabe für Nutzer, die nie einen Krankheitstag eintragen oder das Häkchen
  „Krankheit ausweisen“ nicht setzen: bitgleicher Bericht, bitgleiches Webhook-Dokument,
  unveränderte API-Zahlen, unveränderte Sync-Bytes (kein Bereich `sick` im Doc, solange es keine
  Krankheitstage gibt — s. „Sync“).
- Gesundheitsdaten im Log, im Debug-Protokoll der PWA, in Fehlermeldungen oder in einer
  Datei, die die App ungefragt nach außen gibt.

## Wege, die zur Wahl standen

**A. Ein Datensatz je Kalendertag, eigener Bereich `sick` im Sync-Doc** — gewählt.
Abgleich je Tag nach „neuer gewinnt“ wie bei den Ist-Zeiten; die Krankheitsphase ist nur ein
Block aufeinanderfolgender Tage, keine eigene Identität.

**B. Perioden mit Kennung wie beim Urlaub, synchronisiert.** Verworfen: legen zwei Geräte
offline überlappende Zeiträume an, stehen nach dem Abgleich zwei Perioden über denselben
Tagen, und die Invariante „keine Überschneidung“ bräuchte eine eigene Konfliktlogik; für das
Handy käme ein Merge auf Periodenebene dazu, den es nirgends gibt.

**C. Feld am Ist-Zeit-Eintrag des Tages.** Verworfen: jede ältere App, die den Tag speichert,
verliert das Feld (bei den Notizen brauchte das eine aufwendige Erb-Regel), die alte PWA
ebenso; Teilen, Webhook, API, Wochenlimit und Pausenpflicht müssten es überall herausfiltern.
Ebenso verworfen (Issue): Krankheit als **Kategorie** an Ist-Zeiten — sie zählte als
Arbeitszeit, „Gesamt“ wäre keine reine Ist-Zeit mehr.

Der Preis von A: zwei direkt aneinanderstoßende Krankmeldungen erscheinen als ein Block (bei
einer Folgebescheinigung ist das richtig), und ein Block hat keinen Namen.

## Datenformat

### Lokale Datei `sick.json`

```
{ "YYYY-MM-DD": { "minutes": 450, "modified_at": "…Z", "device_id": "…", "deleted": false } }
```

- `minutes`: ganze Zahl 0–1440. 0 heißt: der Tag gehört zum Block (Wochenende, Feiertag
  mitten in einer Krankheitsphase), trägt aber keine Stunden — dieselbe Rolle wie die
  0-Minuten-Tage des Urlaubs.
- `modified_at`/`device_id`: wie bei den Ist-Zeiten (`utc_now_iso`, festes Format; der
  LWW-Vergleich ist ein String-Vergleich).
- `deleted: true` ist ein Tombstone (`minutes` 0). Tombstones gibt es **immer**, nicht nur mit
  Kalender-Event wie beim Urlaub: die Daten reisen, ein Löschen muss ein älteres Speichern
  eines anderen Geräts schlagen.
- **Block** = maximale Folge lebender Tage mit lückenlos aufeinanderfolgenden Daten. Ein Block
  ohne einen einzigen Tag mit Minuten > 0 ist erlaubt (Krankmeldung übers Wochenende), zählt
  aber im Bericht nicht.

Store `SickStore` (Modul-Vorschlag `src/sick_days.py`, Tk-frei, vollständig annotiert, unter
die Coverage-Untergrenze): am geteilten `data_lock` wie `Storage`/`VacationStore`; Mechanik über
`json_store.atomic_write_json`/`load_json_or_quarantine`; Speicher zurückrollen, wenn das
Schreiben scheitert (wie `Storage`). Lesen bereinigt (Fremddaten: `minutes` außerhalb 0–1440,
fehlende Felder, Nicht-Objekte → Datensatz übersprungen und geloggt, ohne Datum im Log).

Schnittstellen, die mindestens gebraucht werden: `day_minutes()` (`{ISO: minutes}` der lebenden
Tage, Form wie der Urlaubs-Snapshot, damit `report.filter_period` darauf läuft), `block_for(date)`
(von, bis, Tage), `save_range(days: {ISO: minutes})` (setzt Tage lebend, Stempel jetzt),
`delete_days(dates)` (Tombstones), `get_all_raw()`/`apply_merge()` für den Sync.

### Sync-Doc

Neuer, optionaler Bereich auf oberster Ebene, gleiche Form wie die Datei:

```
"sick": { "YYYY-MM-DD": { minutes, modified_at, device_id, deleted } }
```

Additiv **ohne Schema-Bump**, nach dem Muster von `devices` (Docstring `sync.py`):

- `build_local_doc` setzt `sick` nur, wenn der Store mindestens einen Datensatz (auch
  Tombstone) hat. Ohne Krankheitstage bleiben die Sync-Bytes wie bisher.
- `merge` vereinigt beide Seiten je Tag über dieselbe Gewinner-Ordnung wie die Einträge
  (`_lww_key`: Zeitstempel, Gerät, Wert) — symmetrisch, der Permutationstest
  (`tests/test_sync_determinism.py`) bekommt `sick` dazu. **Keine Konflikte**: zwei Stände
  eines Krankheitstags werden nie zur Entscheidung vorgelegt, der neuere gewinnt.
- **Fehlen heißt nie „gelöscht“.** Ein Gerät bis 1.29 baut sein `merge` aus festen Schlüsseln
  und lässt `sick` beim Hochladen weg; jedes neuere Gerät lädt seinen Stand beim nächsten Push
  wieder hoch. `apply_merged_doc` schreibt den Store nur, wenn das Doc den Bereich führt (wie
  den Geräte-Spiegel).
- `validate_remote_doc`: ein kaputter Bereich `sick` (kein Objekt) ist **kein**
  Validierungsfehler des Docs; er wird verworfen und geloggt (wie `devices`). Einzelne
  unbrauchbare Datensätze ebenso.
- Angewendet wird über `sync_journal.apply_merged_doc_journaled` (Crash-Recovery mit).
- Tombstone-Lebenszyklus: `compact_local` entfernt settled `sick`-Tombstones nach derselben
  Regel wie bei den Einträgen; der Startup-Sweep (`drop_orphan_tombstones`) verwirft sie auf
  Geräten, die nie gesynct haben (Marker `sync_history` gilt unverändert, der Handy-Abgleich
  setzt ihn schon).

Den Abschnitt „Tombstone-Lebenszyklus“ in `src/CLAUDE.md` und den Docstring von `sync.py`
ergänzen.

## Regeln

### Stunden je Krankheitstag (Vorbelegung)

Fortgezahlt wird, was an dem Tag angefallen wäre. Vorbelegt wird beim **Anlegen**, danach steht
der Wert fest (spätere Änderungen an Standardzeiten oder Reservierungen ändern bestehende
Krankheitstage nicht — wie beim Urlaub):

1. Hat der Tag eine **Reservierung** (nur bei `reservations_enabled`): deren Netto-Minuten
   (Spanne minus Pause, summiert über die Slots). Gilt auch am Wochenende — wer dort eingeplant
   war, hätte gearbeitet.
2. Sonst **Wochenende** (Sa/So) oder **Feiertag** des Bundeslands: 0. Ein Feiertag wird als
   Feiertag bezahlt (§ 4 Abs. 2 EFZG verweist auf § 2), und Feiertagsvergütung zählt die App
   nirgends.
3. Sonst nach der **Grundlage**, einer synchronisierten Einstellung `sick_hours_basis`:
   - `standard` (Vorgabe): die **Standardzeit des Wochentags**
     (`default_start_<tag>`/`default_end_<tag>` minus `default_pause`). Passt zu einem festen
     Dienstplan (§ 4 Abs. 1 EFZG: die regelmäßige Arbeitszeit des Tages).
   - `average_3m`: der **arbeitstägliche Durchschnitt der letzten drei Monate**, angelehnt an
     § 12 Abs. 4 TzBfG (Arbeit auf Abruf). Referenzzeitraum: die drei Kalendermonate vor dem
     ersten Tag des Blocks, aber frühestens ab dem ersten Tag mit erfasster Ist-Zeit (die App
     kennt den Beginn des Arbeitsverhältnisses nicht; § 12 nimmt bei kürzerem Verhältnis den
     kürzeren Zeitraum). Wert = Summe der Ist-Zeit-Minuten im Zeitraum (alle Kategorien) geteilt
     durch die Zahl seiner Werktage (Mo–Fr ohne Feiertage), wobei Urlaubs- und Krankheitstage
     mit Minuten > 0 aus beiden herausfallen (§ 12 Abs. 4 Satz 3). Ganze Minuten, abgerundet,
     höchstens 1440. So ergibt eine ganze kranke Woche Mo–Fr die durchschnittliche
     Wochenarbeitszeit, auch wenn sie im Referenzzeitraum auf weniger oder andere Tage fiel.
     Liegt im Zeitraum keine Ist-Zeit, gilt `standard`, und der Dialog sagt das.

Die Grundlage wählt man **im Krankheits-Dialog** (zwei Optionen, die Tagesliste rechnet sofort
neu); die Wahl wird als `sick_hours_basis` gemerkt. Sie steht in `SYNCED_SETTING_KEYS`, damit
jedes Gerät — auch der Desktop, der eine Krankmeldung vom Handy annimmt — gleich rechnet
(additiv wie `slot_order_mode`; `conflict_view.SETTING_LABELS` bekommt die Beschriftung). Am
Desktop lässt sich jeder Tag danach überschreiben (0–24 h). Ein eigener Pauschalwert
(`sick_hours_per_day`) entfällt. Die Regel liegt Tk-frei an **einer** Stelle (Planer nach dem
Muster von `vacation_plan.py`) und wird von Dialog, API und Handy-Abgleich gerufen.

**Hinweise statt Rechnung.** Der Dialog zeigt sachliche Hinweise, kürzt aber nichts:
- Umfasst der Block mehr als 42 Kalendertage: „Die Entgeltfortzahlung endet in der Regel nach
  sechs Wochen; danach zahlt meist die Krankenkasse. Welche Tage zählen, klärt dein
  Arbeitgeber.“ (§ 3 Abs. 1 EFZG; ob eine Folgeerkrankung dieselbe Krankheit ist, kann die App
  ohne Diagnose nicht wissen.)
- Immer ein Satz, dass die Stunden ein Vorschlag sind und die Abrechnung beim Arbeitgeber liegt
  (Wartezeit von vier Wochen, § 3 Abs. 3 EFZG, und Tarifverträge, § 4 Abs. 4, kennt die App
  nicht).

### Krankheit und Arbeitszeit am selben Tag

Schließen sich aus, wie beim Urlaub, nur für Tage mit Minuten > 0:

- Desktop und Handy lassen einen Krankheitstag nicht über Tage legen, die schon Ist-Zeit
  tragen (Meldung mit Tagesliste, `format_day_list`-Muster).
- Ein Krankheitstag öffnet keinen Ist-Zeit-Editor (Desktop: s. „Linksklick“; PWA: Reiter
  „Arbeitszeit“ gesperrt).
- Die lokale API lehnt `PUT /v1/entries/{date}` an einem Krankheitstag ab (`409 sick_day`,
  neuer Code in `pwa/test/fixtures/errors.json`), `DELETE` bleibt erlaubt.
- **Behandelt statt verhindert**, wo die Sperre nicht hinreicht (Sync von einem alten Gerät,
  Import, alte PWA): die Krankheitsminuten werden um die erfasste Ist-Zeit gekappt (Untergrenze
  0), gegen den bereits zeitraum- **und** kategoriegefilterten Ausschnitt — dieselbe Funktion
  wie beim Urlaub (`cap_by_worktime`, s. „Zeitraum-Kern“), beschriftet an Vorschau und Bericht.

### Krankheit und Reservierungen

Eine Krankmeldung über Tage mit Reservierungen **sperrt nicht** (anders als beim Urlaub).
Desktop-Dialog **und** PWA bieten „Reservierungen in diesem Zeitraum löschen“ an,
**standardmäßig an**, und zeigen das nur, wenn es dort (aktive) Reservierungen gibt. Gelöscht
wird über den normalen Weg der Reservierungen (Tombstone, Kalender-Abgleich wird angestoßen;
am Handy als Reservierungs-Tombstones im selben Abgleich, s. „Handy“). Bleiben sie stehen,
melden Desktop und Handy sie wie sonst als verpasst — die Entscheidung des Nutzers.

**Reihenfolge:** die Stunden eines Krankheitstags werden aus den Reservierungen **vor** deren
Löschung berechnet. Am Desktop heißt das: erst planen, dann löschen. Im Handy-Abgleich rechnet
der Desktop die fehlenden Minuten aus seinem Reservierungs-Stand **vor** dem Einmischen der
Handy-Reservierungen (`ReservationStore.merge_phone`); sonst fiele die Vorbelegung auf die
Standardzeit zurück, weil die Reservierung im selben Abgleich als gelöscht ankommt.

### Krankheit und Urlaub

- Eine Krankmeldung darf über Urlaubstage gelegt werden. **Krankheit gewinnt**: an diesen
  Tagen zählen die Urlaubsminuten 0, der Urlaub selbst bleibt unzerschnitten im Store. Im
  Kalender färbt Krankheit die Zelle, der Tooltip nennt beides.
- Einen **neuen Urlaub** über bestehende Krankheitstage (Minuten > 0) zu legen, sperrt der
  Urlaubs-Dialog und die API (`blocking_days` bekommt die Krankheitstage dazu; Meldung „An
  diesen Tagen bist du krank gemeldet“). Ein Urlaub, der wegen Sync auf Krankheit trifft, wird
  nach „Krankheit gewinnt“ behandelt.
- Im **Bericht und Webhook** greift „Krankheit gewinnt“ nur, wenn Krankheit ausgewiesen wird
  (Häkchen). Ohne Häkchen bleibt die Ausgabe bitgleich zu heute, und eine Kürzung des Urlaubs
  ohne Erklärung oder mit einer Erklärung, die die Krankheit verrät, gibt es nicht.
- Reihenfolge der Rechnung je Tag: erst Urlaub an Krankheitstagen auf 0, dann Krankheit um
  Ist-Zeit kappen, dann Urlaub um Ist-Zeit kappen. Ein Kalendertag kommt in „Zu vergüten
  gesamt“ nie auf mehr als `max(Ist, Krankheit oder Urlaub)`.
- Rechtlicher Hintergrund (§ 9 BUrlG verlangt ein ärztliches Zeugnis) wird **nicht** geprüft.
  Der Dialog nennt ihn in einem Hinweissatz, ohne Rechtsberatung.

### Zeitraum-Kern

`cap_by_worktime`, `CappedDay`, `cap_notice`, `_date_range`, `_holiday_dates`,
`apportion_minutes` und `format_day_list` werden von Urlaub und Krankheit gebraucht. Sie
wandern in ein gemeinsames Tk-freies Modul (Vorschlag `src/absence.py`); `vacations.py` und
`vacation_plan.py` re-exportieren die alten Namen, Urlaubs-Tests bleiben unverändert grün.
`cap_notice` bekommt das Substantiv als Parameter („Urlaub“/„Krankheit“); der Wortlaut für
den Urlaub bleibt bytegleich. Für Krankheit lautet er sachlich, nicht als Fehler („An 1 Tag
(…) ist Arbeitszeit erfasst; die Krankheitsstunden sind dort um …h gekürzt.“), weil ein
Krankheitstag mit Ist-Zeit nur über einen alten Stand entstehen kann.

## Desktop-Oberfläche

- **Eintragen:**
  - Im Tages-Dialog ein Knopf **„Krank melden…“**. Er öffnet den Krankheits-Dialog mit Von = Bis = diesem Tag. Der
    Tages-Dialog bleibt „rein zum Speichern“, das ist ein weiterer Speicherweg, kein Löschweg.
  - **Einstellungen → Arbeitszeit → „Krankheit verwalten“**: Liste der Blöcke (neueste zuerst, Zeitraum und
    Stunden), Neu/Bearbeiten/Löschen, Bauform wie „Urlaub verwalten“ (dort gibt es den
    Löschen-Knopf ebenfalls; der Hinweis „Löschen geht auch per Rechtsklick“ kommt mit).
- **Krankheits-Dialog** (`theme.create_dialog`, `theme.Form`):
  - Von, Bis (`date_row`).
  - Grundlage der Stunden: „Standardzeit des Wochentags“ oder „Durchschnitt der letzten 3
    Monate“ (s. „Stunden je Krankheitstag“), vorbelegt aus `sick_hours_basis`.
  - Aufklappbare Tagesliste mit den vorbelegten Stunden je Tag und der Summe; ein Wechsel der
    Grundlage rechnet neu, von Hand geänderte Tage bleiben (Muster `prune_overrides`).
  - Die Hinweise aus „Hinweise statt Rechnung“.
  - Das Häkchen „Reservierungen in diesem Zeitraum löschen“ (s. o.).
  - Ein Hinweissatz: „Frag deinen Arbeitgeber, ab wann eine AU nötig ist.“ Sinngemäß, ohne Paragraph als Rat.
  - Ohne gesetztes Bundesland derselbe Hinweis wie im Urlaubs-Dialog (Feiertage werden nicht erkannt).
  - Bearbeiten heißt: Tage außerhalb des neuen Bereichs werden Tombstones, die übrigen neu geschrieben.
  - Speichern ist gesperrt bei Ist-Zeit auf Tagen mit Minuten > 0.
  - Grenzen: höchstens 366 Tage je Block, 24 h je Tag.
- **Kalender** (`grid_renderer`):
  - Eigene Farbe (neue Palette-Konstante, z. B. `SICK_BG`/`SICK_BG_HOVER`, Kontrast wie
    `VACATION_BG`), Zelltext „krank“ plus Stundenzeile bei Minuten > 0 (ohne eigenen Schalter).
  - **Krankheit gewinnt** in der Zellfarbe über Urlaub, Feiertag und Wochenende.
  - Tooltip: „Krank“, Zeitraum des Blocks und die Stunden des Tages, dazu der Urlaub oder
    Feiertag darunter, wenn vorhanden (ein kombinierter Text, ein `attach_tooltip`).
- **Linksklick** auf einen Krankheitstag mit Minuten > 0 öffnet den Krankheits-Dialog für
  seinen Block (statt einer Meldung wie beim Urlaub). An einem 0-Minuten-Tag öffnet der
  Tages-Dialog normal.
- **Linksklick auf einen Urlaubstag** (Minuten > 0) zeigt weiter die Meldung „An einem
  Urlaubstag lässt sich keine Arbeitszeit erfassen“, aber mit einem zweiten Knopf
  **„Krank melden…“** (öffnet den Krankheits-Dialog mit diesem Tag). Sonst wäre „krank im
  Urlaub“ vom Kalender aus nur über die Einstellungen erreichbar, weil der Tages-Dialog dort
  nie aufgeht. Die Wurzel-CLAUDE.md („Urlaub“) beschreibt die Meldung entsprechend.
- **Rechtsklick**: die Lösch-Auswahl (`themed_ask_delete_choice`) bekommt die Einheit
  „Krankheit TT.MM.–TT.MM.“; gelöscht wird immer der ganze Block, mit Bestätigung.
  **macOS-✕**: `_should_show_delete_button(has_sick=…)`. PR mit `platform:macos`, vor dem Merge
  Pre-Release vorschlagen.
- Footer-Summe: unverändert reine Ist-Zeit.

## Ausgabewege

- **Bericht (Mail-HTML, PDF):**
  - Neues Häkchen **„Krankheit ausweisen“** im Zeitraum-Picker, standardmäßig aus, nur gebaut, wenn im Bestand ein
    Krankheitstag mit Minuten > 0 liegt.
  - Mit Häkchen kommt ein Block „Krankheit“ (Zeiträume nach `_vacation_runs`-Muster und Stunden, ohne Namen) unter den
    Urlaubs-Block.
  - **„Zu vergüten gesamt“ wandert ans Ende** und erscheint, sobald Urlaub oder Krankheit ausgewiesen und > 0 ist.
  - Fußnoten: Kappung durch Ist-Zeit (je Art) und „Krankheit im Urlaub“ („An N Tagen (…) lag Krankheit im Urlaub;
    diese Tage zählen als Krankheit.“).
  - „Gesamt“ bleibt reine Ist-Zeit; Summen nur über Minuten. Ohne Häkchen bitgleich.
- **Vorschau** des Pickers: „+ X h Krankheit“ und die Hinweiszeilen, aus derselben Rechnung wie der Bericht.
- **Webhook** (`build_json_payload`):
  - **Ohne Häkchen fehlen** `sick` und `sick_minutes` ganz: das Dokument ist bitgleich zu heute (anders als beim Urlaub, wo `vacation: null` mit dem Sprung auf Version 2 kam).
  - **Mit Häkchen** stehen beide immer drin: `sick` (`{ISO: minutes}` im Zeitraum, gekappt, `{}` wenn keiner darin liegt) und `sick_minutes` (Summe, 0 ohne). Für einen Empfänger heißt „fehlt“ damit „nicht ausgewiesen oder ältere App“, „vorhanden“ heißt „ausgewiesen“.
  - `vacation`/`vacation_minutes` sind an Krankheitstagen nur mit Häkchen gekürzt.
  - `PAYLOAD_SCHEMA_VERSION` bleibt 2; die Behauptung dazu in der Wurzel-CLAUDE.md und `tests/test_claude_md_claims.py` bleiben gültig.
  - Der Abschnitt zu `webhook.py` in der CLAUDE.md beschreibt die neuen Felder.
- **Lokale API:**
  - `GET /v1/sick?from&to`: Tage mit Minuten, ungekappt, wie die Urlaubsperioden.
  - `POST /v1/sick`: Bereich `{from, to, basis?, day_hours?}` (`basis` fehlt → `sick_hours_basis`), gerechnet über den Planer; die Ist-Zeit-Sperre gilt; Reservierungen werden **nicht** gelöscht.
  - `DELETE /v1/sick/{date}`: löscht den Block des Tages.
  - Auswertungen (`/v1/summary/…`): `sick_minutes` und `sick_capped_days`. `payable_minutes` schließt die Krankheit ein, und `vacation_minutes` ist an Krankheitstagen 0 (die API hat kein Häkchen).
  - Für Nutzer ohne Krankheitstage ändern sich die Zahlen nicht.
  - Danach `ctx.on_change`.
- **Nie:** Teilen-Datei, Google-Kalender.

## Handy

Muster der Reservierungen (`pwa/CLAUDE.md`, „Reservierungen“), mit Feature-Erkennung nach Regel 2.

- **Fähigkeit:** die Sync-Antwort trägt `sick_days: true`. Ohne sie zeigt die PWA keine
  Krankheit, bietet nichts an und sendet nichts; lokal Gespeichertes wird **nie** gelöscht und
  geht hinaus, sobald ein Desktop die Fähigkeit meldet.
- **Anfrage:** optional `sick: {ISO: {minutes?, modified_at, deleted}}`, ohne `device_id`,
  nur geänderte Tage, im ersten Päckchen. Geprüft als Fremddaten (Datum, Zeitstempel höchstens
  15 Minuten in der Zukunft, `minutes` 0–1440 oder fehlend, unbekannte Felder → `422
  invalid_entry`). Ein Desktop **bis 1.29** ignoriert das Feld; die PWA sendet es ohne Fähigkeit
  ohnehin nicht.
- **Minuten rechnet der Desktop.** Fehlt `minutes` an einem lebenden Tag: hat der Desktop dort
  schon einen lebenden Krankheitstag, bleibt dessen Wert; sonst gilt die Regel „Stunden je
  Krankheitstag“ (Reservierung, Wochenende/Feiertag, Standardzeit). Das Handy kennt weder
  Feiertage noch muss es die Regel nachbauen. Der Desktop hebt die Stempel an wie in
  `_phone_doc` (`last_pull_at + 1 s`), merged über `sync.merge` mit dem Handy als `local` und
  wendet über das Journal an; die Antwort trägt den Tag dann mit Minuten.
- **Antwort:** `sick` mit den lebenden Tagen und Tombstones im Lesefenster
  (`heute − Fenster … heute + WINDOW_AHEAD_DAYS`) plus gesendete Tage. Klein, zählt nicht ins
  Mengenbudget.
- **PWA-Oberfläche:**
  - Die Wochenansicht zeigt Krankheitstage (Farbe, „krank“, Stunden, sobald bekannt).
  - Der Tages-Editor bietet an Tagen im Fenster „Krank melden“ mit Bis-Datum (höchstens bis zum Fensterende).
  - Dazu das Häkchen „Reservierungen in diesem Zeitraum löschen“ (standardmäßig an, nur wenn
    der Desktop Reservierungen meldet und im Zeitraum welche liegen). Gesetzt, schreibt die PWA
    für diese Tage Reservierungs-Tombstones und schickt sie mit den Krankheitstagen im selben
    Abgleich (die Reservierungen gehen ohnehin im ersten Päckchen hinaus). Ein Tag, den der
    Desktop nie kannte (`synced_version` 0), wird nur lokal verworfen, wie bei „Tag leeren“.
  - An einem Krankheitstag ist der Reiter „Arbeitszeit“ gesperrt, mit Hinweis und „Krankheit entfernen“ (ganzer Block, mit Bestätigung).
  - Die Ist-Zeit-Sperre gilt lokal gegen die bekannten Tage.
  - Außerhalb des Fensters ist Krankheit gesperrt wie die Arbeitszeit (#273).
- **Speicher der PWA:** bevorzugt als Block in der **Meta** (wie `categories_edit`, kein
  IndexedDB-Upgrade). Ein eigener Object Store mit `VERSION` 3 nur, wenn vorher geprüft ist, dass
  ein noch offener Tab mit älterer PWA dadurch nicht in einen Fehlerbildschirm läuft.
- **Vertrag:** Live-Fixtures `sync-request.json`/`sync-response.json` um `sick` erweitern,
  vorher die Formen einfrieren (`compat/sync-request-pre-sick.json`,
  `compat/sync-response-pre-sick.json`); `tests/test_mobile_contract.py` und
  `test/compat.test.js` lesen sie.
- Debug-Protokoll und `log-scrub`: keine Krankheitstage, keine Daten; die Positivliste der
  Ereignisse bleibt unverändert.

## Abwärtskompatibilität

| Kombination | Verhalten |
|---|---|
| Desktop neu ↔ Desktop bis 1.29 (Drive) | Alter Desktop ignoriert `sick` und lässt den Bereich beim Push weg; neue Geräte laden ihn beim nächsten Push wieder hoch. Kein Datenverlust, kein Pausieren des Syncs. Der alte Desktop zeigt keine Krankheit und lässt dort Ist-Zeit zu → Kappung mit Hinweis. |
| PWA neu ↔ Desktop bis 1.29 | Keine Fähigkeit `sick_days` → Krankheit ist in der PWA unsichtbar, nichts wird gesendet. |
| PWA alt (gecacht) ↔ Desktop neu | Anfrage ohne `sick` ist gültig; das Antwortfeld wird ignoriert. Die alte PWA lässt Ist-Zeit an einem Krankheitstag zu → Kappung. |
| Webhook-Empfänger | Version 2; ohne Häkchen bitgleich; mit Häkchen zwei neue Felder. |
| API-Clients | Neue Routen und Felder; ohne Krankheitstage unveränderte Zahlen. |
| Teilen-Empfänger | Unverändert (keine Krankheit in der Datei). |
| Downgrade des Desktops | `sick.json` bleibt liegen und wird ignoriert; nach dem erneuten Upgrade wieder da. |

## Datenschutz und Entfernen

- `docs/datenschutz.md`:
  - Krankheitstage sind Gesundheitsdaten (Art. 9 DSGVO).
  - Gespeichert werden sie lokal (`sick.json`), bei eingeschaltetem Drive-Sync im App-Ordner des eigenen Google Drive, bei gekoppeltem Handy auf dem Handy.
  - Der Transport ist Ende-zu-Ende verschlüsselt, auch über den Relay. Der lokale Speicher der PWA ist noch unverschlüsselt, solange #490 die Verschlüsselung nicht eingeschaltet hat.
  - In Bericht und Webhook landen sie nur mit dem Häkchen.
  - Danach `scripts/privacy_fixtures.py` neu laufen lassen.
- Log: nie Datum oder Minuten eines Krankheitstags; `startup_info` bekommt keinen Eintrag (es
  gibt keinen Schalter).
- `sick.json` (und `sick.json.corrupt-*`) in `removal.py` (Nutzerdaten), `installer.iss`
  (`[UninstallDelete]`/`DeleteMatching`) und `.gitignore`; der Test, der die Listen
  zusammenhält, zieht mit.

## Reihenfolge der Umsetzung (gestapelte PRs)

Jeder PR hängt am vorigen, der erste an `chore/neues-app-icon`. Je PR: TDD, volle Suite, `ruff`,
`pyright`, bei PWA-Anteilen `node --test`, `biome lint` und `npm run typecheck`, kritisches
Review vor dem Öffnen, CLAUDE.md-Dateien im selben PR nachgezogen.

1. **Zeitraum-Kern** herausziehen, ohne Verhaltensänderung (Urlaubs-Tests unverändert grün).
2. **`SickStore`, Regeln und Sync:** Store, Planer (Stunden je Tag, Sperren, Kappung,
   „Krankheit gewinnt“), Bereich `sick` in Build/Merge/Apply/Validierung/Kompaktierung/Sweep,
   `removal`/`installer.iss`/`.gitignore`. Noch keine Oberfläche.
3. **Desktop-Oberfläche:** Krankheits-Dialog, „Krankheit verwalten“, Kalender, Tages-Dialog,
   Rechtsklick, macOS-✕, Sperre im Urlaubs-Dialog (`platform:macos`).
4. **Ausgabewege:** Bericht, Vorschau, Webhook.
5. **Lokale API** und `docs/datenschutz.md`.
6. **Handy-Abgleich, Desktop-Seite:** Anfrage/Antwort, Fähigkeit, eingefrorene Fixtures.
7. **PWA.**

Danach: Pre-Release über alle drei Plattformen plus Handy (Android, iOS), mit einer
Prüfliste als eigenem Issue (Muster #267/#487); README-Zeile mit `*(ab --VERSION--)*`,
CHANGELOG im Release-PR. Neue Funktion → Minor.

## Was Tests mindestens zeigen müssen

- Sync: Merge je Tag symmetrisch (Permutationstest); ein Doc ohne `sick` löscht nichts; ein
  Tombstone schlägt ein älteres Speichern; ein kaputter Bereich verwirft nicht das Doc; ein Doc
  ohne Krankheitstage ist bytegleich zu heute; Kompaktierung und Sweep entfernen
  `sick`-Tombstones nach den bestehenden Regeln; Journal-Recovery enthält `sick`.
- Durchschnitt: Referenzzeitraum über Monats- und Jahresgrenzen, kürzer ab erstem erfassten
  Tag, Urlaubs- und Krankheitstage herausgerechnet, Feiertage nicht im Nenner, Wochenendarbeit
  im Zähler, keine Ist-Zeit → Standardzeit mit Hinweis, Rundung, Obergrenze; eine kranke Woche
  Mo–Fr ergibt die Wochensumme des Durchschnitts.
- Regeln: Vorbelegung (Reservierung, Wochenende, Feiertag, Standardzeit, ohne Bundesland),
  Sperre gegen Ist-Zeit nur bei Minuten > 0, Kappung, „Krankheit gewinnt“ samt Reihenfolge,
  Block-Bildung über Monats- und Jahresgrenzen.
- Bericht/Webhook: bitgleich ohne Häkchen; Summen über Minuten gehen auf (Ist + Urlaub +
  Krankheit = „Zu vergüten gesamt“); Fußnoten.
- API: Routen, `409 sick_day`, Summen.
- Handy: alte Anfrage ohne `sick` wird angenommen; Antwort ohne Fähigkeit wird von der PWA
  verstanden (eingefrorene Fixtures); fehlende Minuten rechnet der Desktop; Stempel-Anhebung;
  Krankmeldung samt Reservierungs-Tombstones in einem Abgleich ergibt die Minuten aus der
  Reservierung, nicht aus der Standardzeit.
- Entfernen-Listen, Typannotationen, Catch-all-Regel, `test_pixel_scaling` für die neuen
  Dialoge.

## Bekannte Grenzen

- Ein alter Desktop am Drive-Sync zeigt keine Krankheit und kann Ist-Zeit darauf erfassen;
  die Kappung fängt die Zahl ab, nicht die Anzeige.
- Bis ein neues Gerät erneut pusht, fehlt der Bereich im Drive-Doc, nachdem ein altes Gerät
  hochgeladen hat; ein drittes Gerät sieht in dieser Zeit keine neuen Krankheitstage.
- Der Urlaub bleibt gerätelokal (Xveyn#548): „Krankheit gewinnt“ wirkt nur auf den Urlaub des
  Geräts, das den Bericht baut.
- Die Vorbelegung kennt keine individuellen Arbeitstage außer über Reservierungen,
  Standardzeiten und den Durchschnitt; wer an festen, aber wenigen Wochentagen arbeitet,
  korrigiert die Tagesliste von Hand (oder plant per Reservierung).
- Der Durchschnitt enthält Überstunden, die § 4 Abs. 1a EFZG ausnimmt: die App kennt die
  vereinbarte Arbeitszeit nicht. Er ist eine von mehreren üblichen Rechenweisen (je Werktag
  verteilt); der Arbeitgeber kann anders rechnen, und bei schwankender Arbeitszeit außerhalb
  von Arbeit auf Abruf nimmt die BAG-Rechtsprechung zwölf statt drei Monate.
- Die App prüft weder die sechs Wochen noch die vierwöchige Wartezeit; sie weist nur hin.
- Eine Reservierung, die nur am Handy angelegt wurde und im selben Abgleich mit der
  Krankmeldung gelöscht ankommt, kennt der Desktop nie: der Tag wird aus der Standardzeit
  vorbelegt.

## Dem Builder überlassen

- Modul- und Funktionsnamen, Aufteilung innerhalb der PRs.
- Genaues Layout von Krankheits-Dialog, Verwaltungsliste und PWA-Editor im Rahmen der
  Theme-Regeln.
- Palette-Werte (mit Kontrastprüfung am Desktop und `test/contrast.test.js` in der PWA).
- Die genauen Texte, solange sie sachlich bleiben und keine Rechtsberatung sind.

## Meine Entscheidungen (nicht ausdrücklich abgestimmt)

- Kein Konfliktdialog für Krankheitstage; der neuere Stand gewinnt.
- Vorbelegung aus Reservierung → Wochenende/Feiertag → Grundlage; kein `sick_hours_per_day`.
  Die Grundlage (Standardzeit oder Durchschnitt) hast du gewählt; meine Entscheidungen daran:
  Vorgabe `standard`; Durchschnitt je Werktag Mo–Fr verteilt; Referenzzeitraum drei
  Kalendermonate, frühestens ab dem ersten erfassten Tag; Grundlage im Dialog wählbar und als
  synchronisierte Einstellung gemerkt; sechs Wochen und Wartezeit nur als Hinweis.
- Krankheit und Ist-Zeit schließen sich aus (Sperre), die Kappung ist nur Sicherheitsnetz.
- Ein neuer Urlaub über Krankheitstage ist gesperrt; Krankheit über Urlaub ist erlaubt und
  gewinnt.
- „Krankheit gewinnt“ in Bericht/Webhook nur mit Häkchen, in der API immer.
- Webhook bleibt Version 2 (gegen die Empfehlung im Issue).
- Das Handy rechnet keine Minuten und bearbeitet keine Stunden.
- PWA-Speicher bevorzugt in der Meta.
- Außer `sick_hours_basis` keine eigenen Einstellungen (kein Schalter für die Stundenzeile,
  kein Pauschalwert).
- Linksklick auf einen Krankheitstag öffnet den Krankheits-Dialog, nicht eine Meldung; die
  Meldung an einem Urlaubstag bekommt „Krank melden…“.
- Webhook: ohne Häkchen fehlen die Felder (bitgleich), mit Häkchen stehen sie immer drin.
