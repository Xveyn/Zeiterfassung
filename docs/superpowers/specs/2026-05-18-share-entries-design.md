# Arbeitszeiten teilen + importieren — Design

**Status:** Spec
**Datum:** 2026-05-18
**Verwandt:** [2026-05-14-multi-device-sync-design.md](2026-05-14-multi-device-sync-design.md) (die ursprüngliche Ideenskizze stand in `planned-features.md`, die inzwischen entfernt wurde — Ideen liegen jetzt im Issue-Tracker)

## Problem

User möchten ihre Zeiterfassungs-Einträge an eine zweite Person (Lebenspartner:in, Buchhalter:in, Steuerberater:in) weitergeben können, sodass die Empfängerin sie in ihrer eigenen Zeiterfassung-Instanz importieren kann. Anders als Multi-Device-Sync ist das ein einmaliger / gelegentlicher Transfer zwischen *zwei verschiedenen Usern* mit eigenen Datenbeständen — Konflikte sind die Regel, nicht die Ausnahme, und der Empfänger muss pro Import entscheiden, wie damit umgegangen wird.

## Scope

**Im Scope (MVP):**
- Export aller lokalen Einträge als JSON-Anhang per Gmail an eine konfigurierbare Empfänger-Adresse.
- Import eines solchen Anhangs auf Empfängerseite, mit Zeitraum-Filter (Von/Bis) und drei Konflikt-Modi (alles importieren / alles lokal / pro Tag entscheiden) und atomarer Anwendung.
- Defensive Validierung des Import-Files — defekte oder fremde Files dürfen den lokalen Bestand nicht beschädigen.

**Out of scope (bewusst):**
- Zeitraum-Filter beim Export (MVP: immer „alles"; als späterer Wunsch festgehalten in #179). Empfänger kann beim Import filtern — das deckt die meisten Anwendungsfälle ab.
- Settings-Übertragung — nur Entries werden geteilt.
- Verschlüsselung/Signing des Anhangs (Vertrauen in Mail-Transport-TLS).
- Automatischer Import beim Mail-Empfang.
- 2-Wege-Sync zwischen verschiedenen Usern (dafür existiert Multi-Device-Sync, aber nur für denselben User).
- Tombstones — das Share-Format kennt keine; der Empfänger soll durch Teilen nichts gelöscht bekommen.

## Ansatz

**Eigenes Wire-Format** statt Re-Use des Sync-Doc-Formats. Begründung: Sync-Metadaten (`device_id`, `modified_at`, `deleted`, `conflicts`) haben in einem Share-Kontext keine Bedeutung und würden bei Re-Use entweder semantisch falsch sein (foreign `device_id` im Storage des Empfängers) oder explizit gefiltert werden müssen. Ein eigenes, minimales Schema mit `kind`-Marker macht den Unterschied explizit und verhindert, dass künftige Sync-Semantik (z.B. Tombstone-Anwendung) versehentlich in den Share-Pfad blutet.

**Trennung pure / UI** folgt der Konvention von `sync.py` + `dialogs/conflicts_dialog.py`: Validierung, Diff, Apply leben in einem neuen pure-function-Modul `src/share.py`; die Dialoge in `src/dialogs/share_dialog.py` und `src/dialogs/import_dialog.py` orchestrieren UI und rufen ins pure Modul.

**Atomarität beim Import:** Der gesamte Import (Additionen + per-Modus-aufgelöste Konflikte) wird als ein Block angewendet. Wenn der Empfänger den Pro-Tag-Dialog abbricht, passiert nichts — keine Teilzustände, weil sonst der Bestand schwer nachvollziehbar wird.

## Datenmodell

### Share-File-Schema

```json
{
  "schema_version": 1,
  "kind": "zeiterfassung-share",
  "exported_at": "2026-05-18T12:00:00Z",
  "exported_by": "alice@example.com",
  "entries": {
    "2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30},
    "2026-05-15": {"start": "09:00", "end": "17:00", "pause": 45}
  }
}
```

Validation-Regeln (jede Verletzung → ganzer Import-Abbruch):

- Toplevel ist `dict`.
- `kind == "zeiterfassung-share"` (string-equal).
- `schema_version == 1` (int; höhere Versionen → spezifische Fehlermeldung „App-Update nötig").
- `entries` ist `dict`. Keys matchen `^\d{4}-\d{2}-\d{2}$` und sind valide ISO-Daten.
- Jeder Entry ist ein `dict` mit **exakt** den Keys `{"start", "end", "pause"}` — keine zusätzlichen, keine fehlenden.
- `start`, `end` matchen `^\d{2}:\d{2}$` und sind valide Uhrzeiten.
- `pause` ist `int >= 0`.

`exported_at` und `exported_by` sind reine Anzeige-Metadaten — werden in die UI gespiegelt, aber nicht für Logik verwendet. Werden tolerant geparst (Leerstring akzeptiert).

### Diff-Resultat

`diff_share_against_local(share_entries, storage, date_from=None, date_to=None)` liefert ein Dict mit drei Listen:

```python
{
  "additions": [(date_str, share_entry), ...],   # Tag nicht lokal
  "conflicts": [(date_str, local_entry, share_entry), ...],  # Tag lokal != share
  "untouched": [date_str, ...],                  # Tag lokal == share (no-op)
}
```

`date_from`/`date_to` sind optionale `datetime.date`-Filter (inclusive auf beiden Seiten). `None` bedeutet jeweils unbeschränkt. Einträge außerhalb des Ranges werden komplett aus dem Diff ausgeklammert — tauchen weder in additions noch conflicts noch untouched auf und werden auch nicht importiert. Vergleichsgrundlage für „identisch": `{start, end, pause}` per-Feld-Equality. `local_entry` ist das User-Shape aus `storage.get(date_str)` (kein Tombstone, kein device_id).

### Import-Decisions

Beim Apply-Schritt erhält `apply_import()` eine flache Liste von „was importiert werden soll":

```python
decisions = [
  {"date": "2026-05-14", "entry": {"start": "08:00", "end": "16:00", "pause": 30}},
  ...
]
```

Dialog-Logik baut diese Liste je nach gewähltem Modus:

- **Alles vom Import übernehmen:** `additions` + alle `conflicts` (share_entry-Seite).
- **Alles lokal behalten:** nur `additions`, conflicts werden komplett verworfen.
- **Pro Tag entscheiden:** `additions` + jene `conflicts`, bei denen der User „import" gewählt hat.

In allen drei Fällen sind `untouched`-Tage out — sie sind per Definition no-ops.

## Architektur

### Neue Module

- **`src/share.py`** — pure functions, kein Tk-Import, keine I/O auf Disk außerhalb von Storage-Calls:
  - `build_share_doc(storage, sender_email: str) -> dict`
  - `serialize_share_doc(doc: dict) -> bytes` (UTF-8 JSON, indent=2)
  - `parse_share_doc(raw_bytes: bytes) -> dict` — raises `ShareValidationError` mit menschenlesbarem Grund
  - `diff_share_against_local(share_entries: dict, storage) -> dict` (siehe oben)
  - `apply_import(storage, decisions: list) -> None` — wendet alle Decisions in **einem** Disk-Write an, via neuer Storage-Methode (siehe unten). Bei `OSError` mid-write bleibt der bestehende Bestand unverändert (tmp+replace).
  - `class ShareValidationError(Exception)` — Top-level-Exception mit `.reason` (string, deutsch)

- **`src/dialogs/share_dialog.py`** — Toplevel-Dialog „Arbeitszeiten teilen":
  - Funktion `open_share_dialog(parent, storage, settings, base_path)`
  - Recycelt `show_missing_credentials_dialog` aus `send_dialog.py` für Setup-Fehler.

- **`src/dialogs/import_dialog.py`** — Toplevel-Dialog „Arbeitszeiten importieren":
  - Funktion `open_import_dialog(parent, storage, settings, on_change)`
  - Enthält Summary-Modal und Pro-Tag-Modal (zweite `Toplevel` oder Frame-Swap im selben Window — Entscheidung im Implementierungs-Plan).

### Erweiterungen bestehender Module

- **`src/settings.py`** — `DEFAULTS`-Erweiterung um `"share_recipient": ""`. Bewusst **nicht** in `SYNCED_SETTING_KEYS`: Empfänger-Adresse für Teilen ist per-device sinnvoll und soll nicht über Sync auf andere Geräte des Senders propagieren (anders entscheiden wäre ein späterer separater Spike).

- **`src/dialogs/settings_dialog.py`** — neues Feld „Teilen mit:" direkt unter „Empfänger:". Single-line `dark_entry`, gespeichert via `set_many` (kein `set_synced`, weil nicht in der Whitelist).

- **`src/ui.py`** — zwei neue Einträge an die UI:
  - Footer/Header-Button „Teilen…" neben dem bestehenden „Monat senden" (oder als Menüeintrag, falls die Footer-Breite limitiert — Detail im Implementierungs-Plan).
  - Eintrag „Arbeitszeiten importieren…" — Settings-Dialog ist sinnvoller Anker (analog zu „Konflikte ansehen"), weil seltener Aktion.

- **`src/storage.py`** — neue Methode `save_many(updates: dict[str, dict]) -> None`. `updates` ist `{date_str: {start, end, pause}}`. Schreibt alle Einträge mit frischen `modified_at`/`device_id`/`deleted=False` in `_data` und ruft genau **einmal** `_save_to_disk()` — damit ist der Import auf File-Ebene atomar (tmp+replace). Leeres Dict ist No-op (kein Disk-Roundtrip).

- **`src/mail.py`** — `send_email()` kann bereits Anhänge versenden (bisher PDF); wir hängen JSON-Bytes an und setzen `Content-Type: application/json` über `MIMEApplication(..., _subtype="json")`. Falls die bestehende `send_email`-Signatur das nicht flexibel genug erlaubt, kommt eine kleine Verallgemeinerung (z.B. `attachment_bytes`, `attachment_filename`, `attachment_subtype`) — Detail im Implementierungs-Plan.

### Tests (neu)

- **`tests/test_share.py`** — pure-function-Tests:
  - Round-Trip: `build → serialize → parse` liefert äquivalentes Doc.
  - Reject-Cases: falsches `kind`, fehlende Pflichtfelder, falsche Datumsformate, falsche Uhrzeit-Formate, negative Pause, unbekannte Keys pro Entry, falsche `schema_version`, fremder JSON-Inhalt (Liste statt Dict), kaputtes JSON.
  - Diff-Cases: nur Additionen, nur Konflikte, nur Untouched, Mischung; Storage mit Tombstones (Tombstone-Tag zählt als „nicht lokal vorhanden" → addition).
  - Diff-Range-Cases: Filter klammert Tage links/rechts/beidseitig aus; Filter komplett außerhalb → leer; `None`-Grenzen verhalten sich wie unbeschränkt.
  - Apply: Alle drei Modi gegen einen echten `Storage` mit `tmp_path`. Atomar-Check: ein `apply_import`-Aufruf führt zu genau einem File-Write, der entweder vollständig durchgeht oder den Vorzustand belässt. Mock-Test gegen `Storage.save_many`, dass die Methode genau einmal aufgerufen wird (und nicht N-mal `save`).
  - `Storage.save_many` separat: schreibt einmal, schreibt alle Felder, leeres Dict ist No-op.
- Keine UI-Tests (folgt bestehender Konvention — kein UI-Test-Setup im Repo).

## Flow im Detail

### Export

1. User klickt „Teilen…" (Footer-Button oder Menü).
2. Pre-checks:
   - `settings.get("share_recipient")` nicht leer? Sonst Warn-Dialog „Bitte zuerst eine Empfänger-Adresse für das Teilen in den Einstellungen angeben."
   - `credentials.json` vorhanden? Sonst `show_missing_credentials_dialog` (recycled).
   - `storage.get_all()` nicht leer? Sonst Info-Dialog „Keine Einträge zum Teilen vorhanden."
3. Bestätigungs-Dialog: „Alle X Einträge an `share_recipient` senden? [Senden] [Abbrechen]"
4. Bei Senden:
   - `sender_email = settings.get("sender_email") or ""` (zu Anzeige-Zwecken im Doc).
   - `doc = build_share_doc(storage, sender_email)`
   - `payload = serialize_share_doc(doc)`
   - Gmail-Service-Aufbau via `get_gmail_service` (gleich wie PDF-Pfad).
   - Subject: `Arbeitszeiten geteilt von <name oder sender_email>`
   - HTML-Body (UTF-8, `<meta charset="utf-8">`): kurze deutsche Anleitung
     („Anbei meine Arbeitszeiten als JSON-Datei. Empfänger:in kann sie in der Zeiterfassung-App über *Einstellungen → Arbeitszeiten importieren…* einlesen.").
   - Anhang: `zeiterfassung-share-YYYYMMDD.json`, `application/json`, payload-bytes.
   - Bei Fehler: `messagebox.showerror` mit `traceback.format_exc()` (Pflicht aus CLAUDE.md, siehe „UI-Fehler sichtbar machen").
5. Erfolg: themed Info-Dialog „Geteilt mit `share_recipient`."

### Import

1. User klickt „Arbeitszeiten importieren…" (Settings-Dialog).
2. `tkinter.filedialog.askopenfilename(filetypes=[("Zeiterfassung Share", "*.json"), ("Alle Dateien", "*.*")])`.
3. Datei lesen → `parse_share_doc(raw_bytes)`.
   - Bei `ShareValidationError`: `messagebox.showerror("Datei ungültig", f"Die Datei kann nicht importiert werden:\n\n{e.reason}")`. Lokaler Bestand bleibt unverändert. Ende.
4. Initial-Range berechnen: `date_from`/`date_to` = min/max der Datums-Keys in `doc["entries"]` (voller Datenbereich der Datei).
5. `diff = diff_share_against_local(doc["entries"], storage, date_from, date_to)`.
6. **Summary-Modal mit Zeitraum-Filter:**

   ```
   Datei: zeiterfassung-share-20260518.json
   Geteilt von: alice@example.com   (oder: „unbekannt" wenn Feld leer)
   Exportiert: 2026-05-18 12:00 UTC

   Zeitraum filtern:
     Von:  [01].[04].[2026]    Bis:  [18].[05].[2026]
     (Voller Bereich der Datei: 2026-04-01 bis 2026-05-18)

   • 12 neue Tage werden importiert
   •  3 Tage haben Konflikte
   •  5 Tage sind identisch (übersprungen)
   •  0 Tage außerhalb des Zeitraums (ignoriert)

   Konflikt-Behandlung:
   (•) Alles vom Import übernehmen
   ( ) Alles lokal behalten
   ( ) Pro Tag entscheiden

   [Weiter]  [Abbrechen]
   ```

   - Von/Bis verwenden dieselben `dark_combo`-Day/Month/Year-Tripletts wie `send_dialog.py` (Recycling der `build_date_row`-Logik wäre ein Refactoring-Spike — MVP: dupliziert, Cleanup später).
   - Bei jeder Änderung der Von/Bis-Felder läuft `diff` neu, die Count-Zeilen aktualisieren live. Out-of-range-Count zeigt, wie viele Tage durch den Filter ausgeklammert wurden — Transparenz für den User.
   - Validation: `Von > Bis` → Inline-Hinweis statt sofortigem Recompute (siehe Edge-Cases).
   - „Abbrechen" oder Window-Close: Ende, kein Effekt.
   - „Weiter" mit `additions+conflicts == 0` (nichts zu tun): Info-Hinweis „Im gewählten Zeitraum sind alle Einträge bereits identisch — nichts zu importieren." Dialog bleibt offen, User kann Range anpassen oder abbrechen.
   - „Weiter" + Modus „alles import": baut Decisions, direkt zu Schritt 8.
   - „Weiter" + Modus „alles lokal": baut Decisions (nur additions), direkt zu Schritt 8.
   - „Weiter" + Modus „pro Tag" + conflicts > 0: zu Schritt 7.
   - „Weiter" + Modus „pro Tag" + conflicts == 0: behandelt wie „alles import" (keine Konflikte, also nichts zu entscheiden).

7. **Pro-Tag-Modal:**

   ```
   Pro Tag entscheiden:

   ┌─────────────┬──────────────────────┬──────────────────────┬─────────┐
   │ Datum       │ Lokal                │ Import               │ Wahl    │
   ├─────────────┼──────────────────────┼──────────────────────┼─────────┤
   │ 2026-05-14  │ 08:00—16:00 (P30)    │ 09:00—17:30 (P30)    │ (•)L( )I│
   │ 2026-05-15  │ 09:00—17:00 (P45)    │ 10:00—18:00 (P30)    │ ( )L(•)I│
   │ 2026-05-16  │ 08:00—12:00 (P0)     │ 08:00—16:00 (P30)    │ (•)L( )I│
   └─────────────┴──────────────────────┴──────────────────────┴─────────┘

   [Alle auf Import]  [Alle auf Lokal]    [Anwenden]  [Abbrechen]
   ```

   - Default-Wahl: „L" (lokal) für alle Zeilen — konservativer Default.
   - Bequemlichkeits-Buttons setzen alle Radios auf eine Seite.
   - „Abbrechen" / Close: **gesamter Import wird verworfen** (atomar). Additionen werden **nicht** angewendet — spec-Entscheidung.
   - „Anwenden": Decisions = additions + alle Konflikte mit Wahl „I". Weiter zu Schritt 8.

8. `apply_import(storage, decisions)` läuft. UI-Refresh via `on_change()`.
9. Bestätigung: themed Info-Dialog „X Einträge importiert, Y übersprungen."

## Interaktion mit bestehenden Features

**Multi-Device-Sync (aktivierter Empfänger):**
Nach `apply_import()` haben die importierten Einträge frische `modified_at` und die `device_id` des Empfänger-Geräts (kommt aus `storage.save()`). Sie wandern beim nächsten regulären Push ganz normal in den Drive-Sync — kein Sonderpfad nötig. Falls der Sync genau in dem Moment mid-pull ist, wird das vom bestehenden Mechanismus (LWW gegen `last_pull_at`) sauber behandelt.

**Settings-Dialog:**
Das neue Feld „Teilen mit:" sitzt direkt unter „Empfänger:" (PDF-Reporting). Beide bleiben unabhängig editierbar. Wenn der User für Teilen und Reporting dieselbe Adresse will, muss er sie zweimal eintragen — bewusst, weil die typischen Empfänger unterschiedlich sind (Stb vs. Lebenspartner).

**Mail-Send-Pipeline:**
Recycelt vollständig: gleicher OAuth-Flow, gleicher `get_gmail_service`, gleicher Token-Refresh-Pfad. Einzige potentielle Verallgemeinerung: `send_email()` muss optional einen JSON- statt PDF-Anhang akzeptieren — kleine Erweiterung der Signatur (Details im Implementierungs-Plan).

## Edge-Cases

- **Empfänger ohne `credentials.json`:** Import liest rein lokal — kein OAuth nötig auf Empfängerseite. Nur Sender braucht Gmail-Setup.
- **Datei ist altes `zeiterfassung.json` (legacy ohne `kind`):** `parse_share_doc` rejected mit „Diese Datei ist keine geteilte Zeiterfassung."
- **Datei aus zukünftiger App-Version (`schema_version: 2`):** rejected mit „Diese Datei wurde mit einer neueren Version erstellt. Bitte App aktualisieren."
- **Datei enthält `deleted: true`-Einträge (z.B. manuell mit Sync-Doc verwechselt):** rejected (unbekannter Key pro Entry). Niemand soll versehentlich Löschungen importieren.
- **Empfänger-Storage hat einen Tombstone für ein importiertes Datum:** Diff sieht den Tag als „nicht lokal" (Tombstones werden in `storage.get_all()` ausgefiltert), addition wird angewendet, `save_many` überschreibt den Tombstone mit frischen Daten (`deleted=False`) → erwünschtes Verhalten.
- **Riesige Files (z.B. 10 Jahre tägliche Einträge ≈ 3650 Tage):** JSON liegt im einstelligen MB-Bereich; Gmail-Anhang-Limit 25 MB — kein Problem. Per-Tag-Modal mit 3000 Zeilen ist UI-mäßig grenzwertig, aber MVP-akzeptabel (User wird in der Praxis kaum so viele Konflikte haben; Scrollbar reicht).
- **Empfänger hat keine Einträge:** Diff = nur additions, Pro-Tag-Modus zeigt leere Liste → Verhalten wie „alles import".
- **Sender hat keine Einträge:** Export-Pre-Check fängt das.
- **Zeitraum-Filter komplett außerhalb der Datei (z.B. Von=2030):** Diff liefert leere Listen → „Weiter" zeigt Info „nichts zu importieren", User passt Range an oder bricht ab.
- **Zeitraum-Filter `Von > Bis`:** Inline-Hinweis im Dialog („Von-Datum muss vor Bis-Datum liegen"); „Weiter" bleibt aktiv aber recomputet erst, wenn der Range wieder gültig ist. Alternativ Button-Disable — Implementierungs-Detail.
- **Datei ist leer (`entries: {}`):** initial-Range fällt zurück auf heute=heute (oder gibt's keinen sinnvollen Default — dann Default-Range = `(None, None)` und „nichts zu importieren"-Hinweis). Pragmatisch: Pre-Check vor Dialog-Öffnung fängt diesen Fall mit „Datei enthält keine Einträge".

## Offene Punkte (für Implementierungs-Plan, nicht für diese Spec)

- Footer-Button vs. Menüeintrag für „Teilen…" — abhängig von verfügbarer Footer-Breite (CLAUDE.md: window width is pinned).
- Pro-Tag-Modal als zweite `Toplevel` vs. Frame-Swap im Summary-Window — UX-Detail.
- `send_email()`-Signatur-Erweiterung: optional Parameter mit Default für PDF-Backward-Compat, oder neue interne Helper-Funktion — Implementierungs-Detail.

## Was wir NICHT bauen (Wiederholung Klarheit)

- Keinen 2-Wege-Sync zwischen verschiedenen Usern.
- Keinen automatischen Import bei Mail-Empfang.
- Keine Live-Kollaboration, keinen Push ohne Mail-Versand.
- Keine Zeitraum-Filter beim Export (MVP).
- Keine Settings-Übertragung (MVP).
- Keine Verschlüsselung/Signing (MVP).
