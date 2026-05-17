# Planned Features

Sammlung geplanter Features mit Skizze. Nicht ausimplementiert, kein
Spec-Ersatz — dient als Notizblock für Ideen, bevor sie in
`docs/superpowers/specs/` oder direkt in einen PR wandern.

---

## Arbeitszeiten an andere Mail teilen + importieren

**Status:** geplant, noch nicht implementiert.

### Idee

Ein User soll seine Arbeitszeiten an eine zweite E-Mail-Adresse teilen können
(Lebenspartner:in, Buchhalter:in, Steuerberater:in, …). Der Empfänger soll die
geteilten Daten in seiner eigenen Zeiterfassung-Instanz importieren können —
und entscheiden, was mit lokal bereits vorhandenen Einträgen passiert.

Unterscheidet sich vom bestehenden **Multi-Device-Sync** dadurch, dass es kein
kontinuierlicher 2-Wege-Sync zwischen *demselben User* ist, sondern ein
einmaliger / gelegentlicher Transfer zwischen *zwei verschiedenen Usern* mit
unterschiedlichen Datenbeständen. Konflikte werden hier deutlich häufiger
auftreten und müssen pro Import sinnvoll auflösbar sein.

### Settings (neu)

- Empfänger-Adresse(n) für das Teilen pflegen — analog zur bestehenden
  Empfänger-Liste für PDF-Versand, aber als separates Feld, damit man Teilen
  und Reporting unabhängig konfigurieren kann.
- Optional: Default-Zeitraum für den Export (z. B. „letzter Monat", „seit
  letztem Teilen", „alles"). MVP: nur „alles", Rest später.

### Export-Pfad

- Eintrag im Menü oder Settings-Dialog: „Arbeitszeiten teilen…".
- Erzeugt ein Transport-File (vermutlich JSON, kompatibel mit dem
  bestehenden `zeiterfassung.json`-Schema bzw. dessen Sync-Variante), packt
  es als Mail-Anhang und sendet es über die existierende Gmail-Pipeline.
- Subject/Body in Deutsch, Hinweis im Body wie der Empfänger das in seiner
  App importiert.

### Import-Pfad

Empfänger erhält Mail mit Anhang. Im Settings-Dialog (oder neuer
Top-Level-Menüpunkt) gibt's „Arbeitszeiten importieren…":

1. Datei-Picker → JSON-File auswählen.
2. Validierung des Schemas (defensiv: defekte / fremde Files dürfen den
   lokalen Bestand nicht zerschießen).
3. Konflikt-Erkennung: für jeden Tag im Import prüfen, ob lokal schon
   ein Eintrag existiert.
4. Konflikt-Auflösung — drei Modi, der User wählt **vor** dem Import:
   - **Alles vom Import übernehmen** — lokale konfliktbehaftete Tage werden
     mit Import-Werten überschrieben.
   - **Alles lokal behalten** — Import-Werte für konfliktbehaftete Tage
     werden verworfen, alle anderen (nicht-konfligierenden) Tage werden
     übernommen.
   - **Pro Tag entscheiden** — Modal mit Liste aller Konflikte: pro Zeile
     lokale vs. importierte Werte, Radio „lokal | import". Am Ende
     bestätigen, dann anwenden.

### Offene Fragen / spätere Entscheidungen

- Format: separates Schema vs. Re-Use des Sync-File-Formats? Re-Use ist
  pragmatisch, hat aber den Nachteil, dass das File interne Metadaten
  (`device_id`, `modified_at`, Tombstones) enthält, die der Empfänger nicht
  braucht — eventuell ein Strip-Step vor dem Versand.
- Tombstones aus dem Import: ignorieren? Anwenden? MVP: ignorieren (Empfänger
  soll durch Teilen nichts gelöscht bekommen).
- Settings teilen oder nur Entries? MVP: nur Entries — Empfänger soll nicht
  versehentlich seinen Stundenlohn überschrieben kriegen.
- Verschlüsselung/Signing des Anhangs? MVP: nein, vertrauen auf Mail-Transport
  (TLS). Falls später relevant, separater Spike.
- Pro-Tag-Entscheidung: was, wenn der Empfänger den Dialog abbricht? MVP:
  alle Pending-Konflikte verwerfen, nicht-konfligierende Tage trotzdem
  importieren? Oder ganzen Import abbrechen? — Wahrscheinlich Zweiteres
  (atomar), weil sonst Teilzustände entstehen, die schwer nachvollziehbar
  sind.

### Was wir NICHT bauen

- Kein 2-Wege-Sync zwischen zwei Usern (dafür ist Multi-Device-Sync gedacht,
  aber nur für *denselben* User).
- Kein automatischer Import beim Empfang einer Mail. Import ist immer ein
  expliziter User-Trigger.
- Keine Live-Kollaboration / kein Push an den Empfänger ohne Mail-Versand.
