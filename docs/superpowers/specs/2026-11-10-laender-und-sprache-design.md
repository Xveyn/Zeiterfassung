# Land, Region und Sprache: die Annahme „Deutschland und Deutsch" sichtbar machen

Stand: 2026-11-10. Entwurf zur Abstimmung, noch nichts gebaut.

## Anlass und Absicht

Die App ist deutsch-*only*: Deutsch steckt in rund 1.350 einzeiligen Literalen
in `src/` (inklusive Log-Texten) und in rund 204 in `pwa/views.js`,
`messages.js` und `view-model.js`. Dazu kommen `<html lang="de">` in
`index.html` und `datenschutz.html` sowie das feste `Intl.DateTimeFormat('de-DE')`
in `pwa/view-model.js`. „Deutschland" und „Deutsch" sind heute **eine**
verschmolzene Annahme, verteilt über die ganze Codebasis.

Es gibt **keinen konkreten Nutzer** für eine andere Sprache oder ein anderes
Land. Ziel ist, die Annahme an wenigen, benannten Stellen sichtbar zu machen,
bevor die zweite Oberfläche (die Handy-PWA) weiter wächst: jedes PWA-Feature
macht den späteren Schritt teurer. Englisch ist die naheliegende zweite
Sprache, aber **nicht Teil dieses Vorhabens** (s. Nicht-Ziele).

## Zwei Achsen

Die Einstellung teilt sich in zwei unabhängige Achsen:

- **Land/Region** → Feiertage, Datumsformat, Vorgaben des Arbeitsrechts.
- **Sprache** → Oberflächentexte.

Wer die Oberfläche auf Englisch stellt, aber in Deutschland arbeitet, braucht
weiter deutsche Feiertage; wer in Österreich arbeitet, braucht österreichische
bei deutscher Oberfläche. Eine Sprachwahl allein wäre sinnlos.

## Ziele

1. **Land und Region als Codes.** `settings["state"]` wird zu `country` und
   `region`. Das Anzeige-Label hängt an den Codes, nie umgekehrt;
   `holidays_de.code_for_state_label` entfällt.
2. **Feiertage über `holidays.country_holidays`** statt festem
   `holidays.Germany`. Die Länderliste ist zunächst nur `DE`; die Struktur
   trägt weitere Länder, ohne dass welche ergänzt werden müssen.
3. **Textschicht in der PWA:** Schlüssel statt Literale, ein Ort für alle
   Texte, `lang` im Dokument folgt der Sprache. Die Texte bleiben in dieser
   Runde **deutsch**.
4. **Datumsformat** über die beiden Helfer `time_utils.format_iso_date` und
   `format_iso_datetime`, gesteuert vom Land; in der PWA statt des festen
   `'de-DE'` aus derselben Quelle.
5. **Textschicht im Desktop** (Stufe 3) und **Länder-Beschriftung des
   Arbeitsrechts** (Stufe 5): gehören zum Feature, werden aber **zuletzt**
   gebaut (s. Vorgehen).

## Nicht-Ziele und Anti-Ziele

- **Keine zweite Sprache in dieser Runde.** Auch Englisch nicht. Die
  Textschicht muss tragen, ohne dass dies an einer echten Übersetzung belegt
  wird; ein Test stellt sicher, dass jeder Schlüssel einen Text hat.
- **Keine Länder über `DE` hinaus**, solange niemand sie braucht.
- **ISO bleibt intern unverändert:** Storage-Keys, Sync-Doc, gcal-Payloads,
  API-Zeitstempel. Nur die Anzeige ändert sich.
- **Keine Nachberechnung bestehender Urlaubsperioden** bei Wechsel von Land
  oder Region. Die `days` werden einmalig beim Anlegen berechnet (s.
  „Urlaub" in `CLAUDE.md`); das gehört in den Hinweistext.
- **Anti-Ziel:** Ein Umbau, der das Verhalten für bestehende deutsche Nutzer
  ändert. Mit `country="DE"` und derselben Region muss alles bitgleich
  bleiben (Feiertage, Berichte, Summen, API-Antworten, soweit nicht
  ausdrücklich erweitert).

## Befund im Code (Stand `6f0bce0`)

- **`holidays_de.py`** ist die einzige Stelle, die die Bibliothek anfasst.
  `STATES` hält Code-Label-Paare, `_holidays_cached` ruft
  `holidays.Germany(subdiv=…, language="de")` mit Retry wegen #116/#37
  (`de.mo` im Onefile-Build transient nicht sichtbar). Der Retry muss beim
  Umbau erhalten bleiben.
- **`"state"` wird an rund 14 Stellen in `src/` gelesen:** `settings.py`
  (Default `""`), `grid_renderer` (2×), `entry_dialog`, `send_dialog`,
  `vacation_dialog`, `send_reminder` (`monthly.get("state")`),
  `send_reminder_scheduler`, `mobile_reminders`, `api_routes`, `api_summary`,
  `tab_work` und `tab_rules` (Label→Code im Dialog).
  Treffer für `"state"` in `google_tab_task`/`tab_google` sind ein anderer
  Begriff (Token-Zustand) und nicht betroffen.
- **`state` ist gerätelokal** (nicht in `SYNCED_SETTING_KEYS`). Das bleibt für
  `country` und `region` richtig und macht die Migration einfach: sie läuft
  pro Gerät, ohne Sync-Schema-Bump.
- **`/v1/holidays/{YYYY}`** liefert `{year, state, holidays[{date, name}]}` mit
  deutschen Namen. `state == ""` unterscheidet „Bundesland fehlt" von „keine
  Feiertage".
- **Die PWA braucht keine eigene Feiertagstabelle:** Sende-Zeitpunkte rechnet
  der Desktop (`send_reminder.upcoming_send_times`).
- **`pwa/messages.js`** ist kein reiner Textspeicher: `offlineText` setzt Sätze
  aus Bausteinen zusammen und fügt eine Adresse ein; die Anrede wechselt
  zwischen „Ihre" und „du". Eine Textschicht braucht deshalb Parameter in den
  Texten und eine **einheitliche Anrede** (Entscheidung offen, s. u.).
- **Datumsformat in der PWA:** `Intl.DateTimeFormat('de-DE', …)` in
  `view-model.js`, plus handgebaute Formate in den Views (im Plan zu
  inventarisieren).

## Entscheidungen, die schon stehen

- Zielbild: Land/Region (Codes) getrennt von Sprache. Deutscher Text zunächst.
- Arbeitsweise: **ein Integrations-Branch, PRs der Reihe nach hinein**, jeder
  PR allein testbar. Der Branch geht **erst nach `master`, wenn alles durch
  ist:** fertig implementiert, getestet, reviewed, auf Handy **und** Desktop
  geprüft. Bis dahin kein Release, kein Versionsbump, kein CHANGELOG-Eintrag
  am Stand von `master`.
- Gearbeitet wird in einem Worktree (`.claude/worktrees/laender-sprache`).
- Die PWA wird lokal getestet (`scripts/pwa_devserver.py`, Browser-Test, am
  Handy).
- **Die PWA stellt ihre Sprache selbst ein.** Beim Koppeln übernimmt sie
  standardmäßig die Sprache des Desktops (der Desktop schickt sie additiv mit,
  fehlt sie, gilt Deutsch); danach ist die PWA-Einstellung maßgeblich und ein
  späterer Wechsel am Desktop ändert sie nicht. In dieser Runde gibt es nur
  Deutsch, die Einstellung und die Übernahme müssen aber in der Struktur
  angelegt sein.
- **`/v1/holidays/{YYYY}`:** `state` bleibt als Alias im Vertrag, `country` und
  `region` kommen additiv dazu. Die Namen folgen der Sprach-Einstellung (vorerst
  fest Deutsch), für Aufrufer ändert sich nichts.
- **Desktop-Textschicht und Länder-Beschriftung zuletzt**, niedrige Priorität.
  Sie halten den Merge nach `master` trotzdem auf: der Branch geht erst mit
  ihnen.

## Offene Entscheidungen (in der Planungsphase zu treffen)

1. **Reihenfolge der PRs.** Vermutung, nicht entschieden: Land/Region →
   Datumsformat → PWA-Textschicht → Desktop-Textschicht samt Aufbrechen der
   großen Dialoge → Arbeitsrecht. Wird beim Übergang zum Plan festgelegt.
2. **Vertrag von `/v1/holidays/{YYYY}`.** Fragen: Bleibt `state` als Feld
   (Kompatibilität) neben neuen `country`/`region`? Sprache der Namen: die des
   eingestellten Landes oder die des Aufrufers? Gehört in den Vertrag,
   **bevor** Land/Region landet.
3. **Anrede in der PWA** (du/Sie) für die Textschicht vereinheitlichen, oder
   den Mischzustand 1:1 übernehmen? Empfehlung: 1:1 übernehmen und die
   Vereinheitlichung als eigenen Schritt nach der Textschicht behandeln, damit
   der Umbau keine inhaltlichen Textänderungen mischt.
4. **Textschicht-Format** (Schlüssel, Parameter, Plural), PWA und Desktop
   getrennt oder gemeinsam; Entscheidung erst nach Sichtung der Literale.
5. **Migration von `state`:** einmalig beim Start (`country="DE"`,
   `region=<alt>`), alte Schlüssel stehen lassen oder entfernen, Verhalten bei
   einem unbekannten Altwert. Gerätelokaler Marker analog
   `linux_system_scale_migrated`.
6. **Land und Datumsformat in der PWA.** Die Sprache ist entschieden (s. u.,
   „Entscheidungen, die schon stehen"). Offen ist nur, woher das Land (und
   damit das Datumsmuster) kommt. Vermutung des Autors: wie bisher vom
   Desktop, additiv im Abgleich, ohne eigene PWA-Einstellung.

7. **Eigene Einstellung für das Datumsformat?** *Entschieden: nein.* Das Format
   wird nur aus Sprache und Land abgeleitet (Punkt 6). Eine getrennte
   Einstellung ließe sich später ergänzen, ohne etwas umzubauen.

## Annahmen (Entscheidungen des Autors, bitte prüfen)

Aus dem Gegenlesen der Spec; jede ließe sich ändern, ohne das Ziel zu ändern.

- **Verträge sind in beide Richtungen abwärtskompatibel.** Die PWA kommt per
  Pages aus `master` (`pages.yml` läuft nur auf Pushes dorthin), der
  Integrations-Branch wird also nie an Handys ausgeliefert. Nach dem Merge kann
  eine neue PWA trotzdem auf einen alten Desktop treffen. Neue Felder im
  Abgleich sind additiv (`PROTOCOL` bleibt 2); fehlen sie, nimmt die PWA
  `DE`/`de-DE`. Jeder PWA-PR trägt dafür einen Test, und ein älterer Desktop
  ignoriert die zusätzlichen Felder.
- **Migration von `state`:** einmalig beim Start, gerätelokal, mit Marker
  (Muster `linux_system_scale_migrated`). `country` wird `"DE"`, `region` der
  alte Wert; ein leerer oder unbekannter Altwert ergibt `region=""` (heutiges
  Verhalten „kein Bundesland", mit dem bisherigen Hinweis). Der alte Schlüssel
  `state` bleibt **stehen**, damit ein Downgrade oder eine parallele
  Dev-Instanz auf demselben Datenordner nicht ins Leere läuft. `country` ist nie
  leer, sondern Default `"DE"`.
- **Datumsformat hängt an Sprache und Land zusammen**, nicht an einer Achse
  allein (`en-US` gegen `en-GB`; auch Wochentags- und Monatsnamen). Die zwei
  Achsen sind für Feiertage und Arbeitsrecht unabhängig, für Datum und Zeit
  bilden sie zusammen ein **Locale** (Sprache plus Land, etwa `de-DE`). Die
  Helfer (`format_iso_date`/`format_iso_datetime`, in der PWA ein zentraler
  Formatierer statt des festen `'de-DE'`) nehmen dieses Locale als Parameter.
  Bevor es ein zweites Format gibt, prüft ein Test sie gegen ein künstliches
  Muster. Offen ist, ob der Nutzer das Datumsformat zusätzlich getrennt
  einstellen kann (Punkt 7). Im Desktop sind die Aufrufer zu inventarisieren,
  die an den Helfern vorbei formatieren; in der PWA die handgebauten Formate.
- **Textschicht-Format:** PWA und Desktop **getrennt**, je im Format ihrer
  Plattform (die PWA hat keinen Build). Der Vollständigkeitstest läuft je Seite
  in der eigenen Suite; ein gemeinsames Katalogformat bräuchte eine
  Vertrags-Fixture und bringt hier nichts.
- **Log-Texte sind nicht Teil der Desktop-Textschicht.** Sie bleiben deutsch
  (technisch, nicht für den Nutzer). Die rund 1.350 Literale sind eine obere
  Grenze, die Zahl der zu übersetzenden Oberflächentexte ist kleiner und wird im
  Plan gezählt. Tests, die auf Meldungstexte prüfen, ziehen mit.
- **Bibliothek:** `holidays==0.99` ist gepinnt und kennt `country_holidays` mit
  `subdiv` und `language`. `--collect-all holidays` bündelt alle Locales. Mit
  nur `DE` im Umfang ändert sich am Build nichts; der Retry gegen #116/#37 bleibt
  für den neuen Einstiegspunkt erhalten.
- **CI auf dem Integrations-Branch:** `test.yml` läuft auf jedem
  `pull_request`, also auch auf PRs gegen den Integrations-Branch.
  `readme-version` greift nur mit `release:*`-Label (die Stack-PRs tragen
  keines). Das Ruleset „Protect master" gilt nur für `master`; am Branch selbst
  ist nichts umzustellen. Version, CHANGELOG und README-Platzhalter kommen erst
  mit dem Merge nach `master`.

## Bekannte Grenzen (kein Bug)

- Urlaubs-`days` werden einmalig beim Anlegen berechnet; ein späterer Wechsel
  von Land oder Region korrigiert bestehende Perioden nicht. Hinweistext statt
  Nachberechnung.
- Ohne gesetzte Region kennt `holidays` für Deutschland keine regionalen
  Feiertage (heutiges Verhalten bei „kein Bundesland").

## Verifikation (Definition von „fertig")

- Alle bestehenden Tests grün, plus neue für Migration, Codes statt Labels und
  Textschicht (jeder Schlüssel hat einen Text, keine verwaisten Schlüssel).
- Für `country="DE"` verhalten sich Berichte, Feiertage und API unverändert.
- PWA: Browser-Test lokal, danach Test am echten Handy (Android und iOS sind
  vorhanden).
- Desktop: Test unter Linux und Windows; **macOS ist die Lücke** und wird über
  einen Pre-Release geprüft, sobald Desktop-Texte betroffen sind
  (`platform:*`-Labels nach Bedarf).
- Review jedes Stack-PRs und ein Gesamtreview des Branches vor dem Merge.
- Erst danach: Merge nach `master` mit Release-Verfahren (Version, CHANGELOG,
  README-Platzhalter).

## Dem Bauenden überlassen

Dateizuschnitt, Namen der Module und Funktionen (etwa `holidays_region`),
Format der Textschlüssel, Schnitt der PRs innerhalb der vereinbarten
Reihenfolge, Testaufbau.
