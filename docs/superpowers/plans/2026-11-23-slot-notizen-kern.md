# Notiz am Slot, PR 1: Kern am Desktop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Desktop kann Notizen an Ist-Zeit-Slots speichern, synchronisieren, über API und Handy-Abgleich annehmen und ausgeben, ohne dass sich für Nutzer ohne Notizen oder für ältere Versionen etwas ändert. Keine Oberfläche.

**Architecture:** Die Notiz liegt am Tag (`entry["notes"] = {Startzeit: Text}`), Slots behalten vier Felder. `Storage` ist die Lese-/Schreibgrenze: innerhalb der App trägt ein Slot `notiz`, wenn er eine Notiz hat. Ein neues reines Modul `src/slot_notes.py` hält alle Regeln; `sync.merge` ergänzt einen Stand ohne `notes` aus der Gegenseite und hebt dann den Stempel um 1 s an.

**Tech Stack:** Python 3.12, pytest, reine stdlib (`unicodedata`, `datetime`). Kein neues Paket.

**Spec:** `docs/superpowers/specs/2026-11-23-slot-notizen-design.md` (Xveyn#519). PR 2 (Desktop-Oberfläche, Bericht) und PR 3 (PWA) bekommen eigene Pläne.

**Branch:** `feat/slot-notizen-kern` von `master`. Spec und Plan gehen mit dem ersten Commit hinein. PR-Text mit `Refs #519`, kein `release:*`-Label.

## Global Constraints

- Kein Versionssprung: `sync.SCHEMA_VERSION` 4, `share.SCHEMA_VERSION` 3, `mobile_sync.PROTOCOL` 2, `webhook.PAYLOAD_SCHEMA_VERSION` 2.
- Slots auf der Platte und im Sync-Doc haben genau `start`, `end`, `pause`, `kategorie`. Notizen stehen nur unter `notes` am Eintrag, Schlüssel = Startzeit.
- `notes` wird nur geschrieben, wenn der Tag Notizen hat oder der überschriebene lebende Stand den Schlüssel schon trug. Ein Tag ohne Notiz wird Byte für Byte wie heute geschrieben.
- Ohne Notizen identisch zu heute: Merge-Gewinner, Stempel, Konflikte, Webhook-Dokument, Teilen-Datei.
- Notiz: einzeilig, getrimmt, keine Zeichen der Klassen `Cc`/`Cs`, höchstens 200 Zeichen. Eingaben werden abgelehnt, gespeicherte Daten bereinigt.
- App-intern heißt das Slot-Feld `notiz` und ist nur vorhanden, wenn nicht leer. Leser nehmen `slot.get("notiz", "")`.
- Repo-Regeln: Tk-freie Module vollständig annotiert mit `# pyright: reportOptionalMemberAccess=true`; Kommentare sagen das Warum, keine Historie, Docstrings in der Regel ≤ 8 Zeilen; `ruff check .` und `pyright` sauber; `pytest` grün.
- Commits enden mit `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>` und der Zeile `Claude-Session: https://claude.ai/code/session_01C9TQTpqHqaEXeGMCPPoL1c`.

## Review Focus

Eingaben, die die Spec nicht einzeln nennt und die am ehesten jemanden treffen. Jede hat ihren Test in der genannten Task.

1. `notes` am Eintrag ist kein Objekt, oder ein Wert ist kein Text (Handbearbeitung, fremdes Sync-Doc): Lesen, Speichern und Merge laufen durch, der Tag hat dann keine Notiz. → Task 1, 2, 3
2. Zwei gespeicherte Slots mit derselben Startzeit, oder `start` ist kein Text: kein Absturz, beide bzw. keiner zeigen die Notiz, nichts wird beim Speichern verdoppelt. → Task 2
3. Der Stand ohne `notes` trägt einen Stempel, der sich nicht lesen lässt (`""` nach einer Reparatur): es wird nicht geerbt, der Merge bleibt symmetrisch. → Task 3
4. Tombstone gegen lebenden Tag mit Notizen: es wird nichts geerbt, das Löschen gewinnt wie heute. → Task 3
5. Eine Notiz mit Steuerzeichen, einzelnem Surrogat oder Überlänge kommt über das Sync-Doc: sie wird beim Lesen bereinigt und lässt sich danach speichern. → Task 1, 2

## File Structure

| Datei | Aufgabe |
|---|---|
| `src/slot_notes.py` (neu) | Alle Regeln der Notiz, rein, ohne Importe aus `src` |
| `pwa/test/fixtures/note-cases.json` (neu) | Gemeinsame Fälle der Notiz-Regeln (PR 3 liest sie in JS) |
| `src/storage.py` | Lese-/Schreibgrenze |
| `src/sync.py` | Signatur, Erb-Regel, gelöste Konflikte, `resolve_conflict` |
| `src/api_entry_write.py`, `src/api_routes.py` | Lokale API |
| `src/mobile_sync.py` | Handy-Abgleich, Fähigkeit `slot_notes` |
| `pwa/test/fixtures/sync-response.json`, `compat/sync-response-pre-notes.json` | Vertrag der Antwort |
| `src/webhook.py`, `src/share.py` | Ausgabe |
| `CLAUDE.md`, `src/CLAUDE.md`, `pwa/CLAUDE.md` | Karte des Aufbaus |

---

### Task 1: Regeln der Notiz (`slot_notes`)

**Files:**
- Create: `src/slot_notes.py`, `tests/test_slot_notes.py`, `pwa/test/fixtures/note-cases.json`
- Modify: `tests/test_type_annotations.py` (`ANNOTATED_MODULES` um `"src/slot_notes.py"`)

**Interfaces (Produces):**

```python
MAX_NOTE_LEN = 200
SLOT_KEY = "notiz"     # am Slot: App-intern und auf dem Draht
ENTRY_KEY = "notes"    # am Eintrag: Datei und Sync-Doc

class NoteError(ValueError):      # .message: deutscher Satz ohne Slot-Präfix
def clean_note(value: object) -> str
def check_note(value: object) -> str
def group_key(note: str) -> str
def has_key(entry: Mapping[str, Any]) -> bool
def notes_of(entry: Mapping[str, Any]) -> dict[str, str]
def with_notes(slots: list[dict[str, Any]], notes: Mapping[str, str]) -> list[dict[str, Any]]
def effective_slots(new_slots: list[dict[str, Any]], old_slots: list[dict[str, Any]]) -> list[dict[str, Any]]
def notes_from_slots(slots: list[dict[str, Any]]) -> dict[str, str]
def supplement(entry: Mapping[str, Any], other: Mapping[str, Any]) -> dict[str, Any] | None
def bump_stamp(stamp: object) -> str | None
def resolution_notes(resolution: Mapping[str, Any], candidates: Sequence[Any],
                     replaced: Mapping[str, Any] | None) -> dict[str, str] | None
```

Verhalten, das Signatur und Name nicht festlegen:

- `clean_note`: kein Text → `""`; Zeichen der Klassen `Cc`/`Cs` entfernen (`unicodedata.category`), trimmen, auf 200 kürzen, erneut trimmen.
- `check_note`: liefert die getrimmte Notiz oder wirft `NoteError` mit genau einem dieser Texte: `"notiz muss Text sein."`, `"notiz darf keine Steuerzeichen enthalten."`, `"notiz darf höchstens 200 Zeichen haben."` (gezählt nach dem Trimmen).
- `group_key`: `note.strip().lower()` (bewusst nicht `casefold`).
- `has_key`: `"notes" in entry`, auch wenn der Wert kein Objekt ist.
- `notes_of`: bereinigte Notizen des Eintrags, nur Text-Schlüssel, die als `start` eines Slots des Eintrags vorkommen, nur nicht-leere Werte. Alles andere (kein Objekt, falsche Typen) ergibt `{}`.
- `with_notes`: Kopien der Slots; `notiz` wird gesetzt, wo `notes` für `slot["start"]` einen Wert hat, sonst bleibt der Slot ohne Schlüssel. Ein schon vorhandenes `notiz` im Slot wird vorher entfernt.
- `effective_slots`: je neuem Slot: trägt er `notiz`, gilt `clean_note` davon; sonst erbt er vom alten Slot mit gleichem `start` (alte Slots in App-Form). Ergebnis in App-Form (`notiz` nur wenn nicht leer). Slots, deren `start` kein Text ist, bekommen nie eine Notiz.
- `notes_from_slots`: `{start: notiz}` aus Slots in App-Form.
- `supplement`: nur wenn `entry` den Schlüssel nicht hat, `other` ihn hat, keiner `deleted is True` ist und `bump_stamp(entry["modified_at"])` nicht `None` ist: Kopie von `entry` mit `notes` = Notizen von `other`, beschränkt auf die Startzeiten von `entry` (auch `{}`). Sonst `None`.
- `bump_stamp`: `"%Y-%m-%dT%H:%M:%SZ"` plus eine Sekunde, sonst `None`.
- `resolution_notes` (Spec „Gelöste Konflikte“), in dieser Reihenfolge:
  1. `resolution` gelöscht (`deleted` wahr) → `None`.
  2. `resolution` hat `notes` → `notes_of({"slots": resolution["slots"], "notes": resolution["notes"]})`.
  3. Kandidaten (nur Objekte), deren Slots in den vier Feldern reihenfolgeunabhängig denen der Auflösung gleichen. Mehrere → der mit dem größten `(modified_at, device_id)`.
     - Hat er den Schlüssel → seine `notes_of`.
     - Sonst: hat ein anderer Kandidat den Schlüssel → dessen Notizen, beschränkt auf die Startzeiten der Auflösung. Sonst `None`.
  4. Kein Kandidat passt → `replaced` hat den Schlüssel: dessen Notizen, beschränkt auf die Startzeiten der Auflösung; sonst `None`.

`note-cases.json`: `{"max_len": 200, "clean": [{"in": …, "out": …}], "check": [{"in": …, "ok": true, "out": …}, {"in": …, "ok": false}], "group": [{"in": …, "key": …}]}`. Mindestens: leer, nur Leerzeichen, 200 und 201 Zeichen, Zeilenumbruch, Tab, `\u0000`, einzelnes Surrogat (`"\ud800"`), Umlaute, „Kunde Mustermann“ gegen „kunde mustermann “ (gleicher `key`), `"İ"` und `"ß"` (bleiben mit `lower()` verschieden von `"i"` bzw. `"ss"`). In `clean` zusätzlich Nicht-Texte (`null`, `5`, `true`, `[]`).

- [ ] **Step 1: Failing tests** in `tests/test_slot_notes.py`:
  - parametrisiert über jede Liste der Fixture (`clean_note`, `check_note` mit `pytest.raises(NoteError)` bei `ok: false`, `group_key`); ein Test, dass `max_len` der Fixture `MAX_NOTE_LEN` ist.
  - `notes_of`: `{"slots": [{"start": "08:00", …}], "notes": {"08:00": " K ", "09:00": "x", 5: "y", "08:00x": 1}}` → `{"08:00": "K"}`; `notes: "kaputt"`, `notes: None`, fehlender Schlüssel → `{}` (Review Focus 1).
  - `with_notes`: zwei Slots mit gleichem `start` bekommen beide die Notiz; Slot mit `start: None` keine; ein mitgebrachtes `notiz` wird verworfen (Review Focus 2).
  - `effective_slots`: ohne Schlüssel erbt bei gleichem `start`; `notiz: ""` erbt nicht und liefert keinen Schlüssel; geänderte Startzeit erbt nicht.
  - `supplement`: liefert `notes == {"08:00": "K"}` bzw. `{}`; `None` bei: Schlüssel vorhanden, `other` ohne Schlüssel, einer gelöscht, `modified_at == ""` (Review Focus 3).
  - `bump_stamp("2026-11-03T23:59:59Z") == "2026-11-04T00:00:00Z"`; `""`, `None`, `"2026-11-03 10:00"` → `None`.
  - `resolution_notes`: je ein Test für die Punkte 1–4, darunter „Auflösung = Slots von Kandidat B, B ohne Schlüssel, A mit `{"08:00": "K"}` und gleicher Startzeit → `{"08:00": "K"}`“ und „Auflösung = Slots von A mit `{"08:00": "KA"}`, `replaced` trägt `{"08:00": "KB"}` → `{"08:00": "KA"}`“.
- [ ] **Step 2:** `pytest tests/test_slot_notes.py -q` → FAIL (Modul fehlt).
- [ ] **Step 3:** `src/slot_notes.py` schreiben (erste Zeile `# pyright: reportOptionalMemberAccess=true`), Eintrag in `ANNOTATED_MODULES`.
- [ ] **Step 4:** `pytest tests/test_slot_notes.py tests/test_type_annotations.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(notizen): Regeln der Slot-Notiz (Refs #519)` (mit Spec und Plan).

### Task 2: Lese- und Schreibgrenze in `Storage`

**Files:**
- Modify: `src/storage.py` (`_user_shape`, `save`, `save_many`)
- Test: `tests/test_storage_notes.py` (neu)

**Interfaces:**
- Consumes: `slot_notes.notes_of`, `with_notes`, `effective_slots`, `notes_from_slots`, `has_key`.
- Produces: `Storage.get`/`get_all` liefern Slots in App-Form (`notiz` nur wenn nicht leer). `Storage.save(date, slots)` und `save_many` nehmen Slots mit oder ohne `notiz`. `get_all_raw`/`apply_merge` unverändert roh.

Regel beim Schreiben eines Tages: `alt` = bisheriger lebender Eintrag in App-Form (sonst `[]`); `eff = effective_slots(slots, alt)`; `notes = notes_from_slots(eff)`; gespeichert werden `_normalize_slot` je Slot (vier Felder) und `notes` genau dann, wenn `notes` nicht leer ist oder der bisherige Eintrag lebt und `has_key` wahr ist. Ein Tombstone als Vorgänger vererbt weder Notizen noch den Schlüssel.

- [ ] **Step 1: Failing tests** (jeweils mit `tmp_path`, Datei danach als JSON lesen):
  - Speichern ohne Notiz: der Eintrag in der Datei hat genau die Schlüssel `{"slots", "modified_at", "device_id", "deleted"}`; `get()` liefert Slots ohne `notiz`.
  - `save("2026-11-03", [{…"start": "08:00", "notiz": " Kunde Mustermann "}])` → Datei: Slot mit vier Feldern, `notes == {"08:00": "Kunde Mustermann"}`; `get()` → `notiz == "Kunde Mustermann"`.
  - Danach `save` derselben Slots **ohne** `notiz` und mit geänderter Pause → Notiz bleibt (Erben).
  - Danach `save` mit `notiz: ""` → `notes == {}` (Schlüssel bleibt, klebrig); `get()` ohne `notiz`.
  - Geänderte Startzeit ohne `notiz` → `notes == {}`.
  - `delete`, dann `save` ohne Notiz → Eintrag ohne `notes`.
  - `save_many` (Import-Weg): Tag mit Notiz, Update ohne `notiz` und gleicher Startzeit → Notiz bleibt.
  - Fremddaten in der Datei (direkt schreiben, dann laden): `notes: "x"`; `notes: {"08:00": 5}`; Notiz mit `"\n"`, 300 Zeichen und `"\ud800"`; Slot mit rohem `"notiz": "roh"`; zwei Slots mit `start: "08:00"` → `get()` wirft nicht, liefert bereinigte bzw. keine Notiz, rohes Slot-`notiz` ist weg; ein anschließendes `save(date, get(date)["slots"])` wirft nicht und schreibt jede Startzeit höchstens einmal in `notes` (Review Focus 1, 2, 5).
- [ ] **Step 2:** `pytest tests/test_storage_notes.py -q` → FAIL.
- [ ] **Step 3:** Umsetzen. `_user_shape`: `sanitize_slot`, dann `with_notes(…, notes_of(entry))`. `save`/`save_many` nach der Regel oben; der Rollback bei Schreibfehlern bleibt.
- [ ] **Step 4:** `pytest tests/test_storage_notes.py tests/test_storage.py tests/test_storage_hardening.py tests/test_storage_migration.py -q` → PASS, kein bestehender Test geändert.
- [ ] **Step 5: Commit** `feat(notizen): Storage trennt Notizen vom Slot (Refs #519)`.

### Task 3: Erb-Regel im Merge

**Files:**
- Modify: `src/sync.py` (`_slots_signature`, Eintrags-Schleife in `merge`)
- Test: `tests/test_sync_notes.py` (neu), `tests/test_sync_determinism.py` (`_random_doc` um `notes`)

**Interfaces:**
- Consumes: `slot_notes.notes_of`, `supplement`, `bump_stamp`.
- Produces: `sync.merge` unverändert in der Signatur.

Ablauf je Datum, wenn beide Seiten vorhanden sind: `loc2 = supplement(loc, rem) or loc`, `rem2 = supplement(rem, loc) or rem`; die ergänzte Seite (höchstens eine) merkt sich `(modified_at, device_id)`. `_merge_one(loc2, rem2, …)` wie bisher, die Kandidaten eines Konflikts behalten ihre Stempel. Trägt der Gewinner `(modified_at, device_id)` der ergänzten Seite, wird er durch eine Kopie mit `modified_at = bump_stamp(…)` ersetzt (auch im Konfliktfall nur der Gewinner, nie ein Kandidat). `_slots_signature` nimmt als fünftes Element `notes_of(entry).get(start, "")`.

Testhelfer im Testmodul: `old_rewrite(entry, *, modified_at, device_id, **slot_changes)` baut den Eintrag so, wie eine alte Version ihn schreibt (vier Schlüssel, kein `notes`).

- [ ] **Step 1: Failing tests** (Dokumente wie in `test_sync_determinism._doc`):
  - Altes Gerät ändert die Pause: lokal `(t1, A, notes {"08:00": "K"})`, remote `old_rewrite(…, t2, C, pause=30)`, `last_pull_at` zwischen t1 und t2 → Ergebnis: Pause 30, `notes == {"08:00": "K"}`, `modified_at == t2 + 1 s`, `device_id == C`, kein Konflikt.
  - Dasselbe mit vertauschten Seiten → gleicher Eintrag.
  - Altes Gerät ändert die Startzeit → `notes == {}`, Stempel `t2 + 1 s`.
  - Neuer Stand mit `notes: {}` (t3) gegen älteren mit Notiz (t1) → `{}`, Stempel t3 (keine Anhebung).
  - Schlüsselloser neuerer Stand gegen `notes: {}` → `{}`, Stempel + 1 s.
  - Beide ohne `notes`, verschiedene Slots → Ergebnis ist exakt das Objekt, das heute gewinnt (`==` gegen die Eingabe, Stempel unverändert).
  - Gleichstand: beide `(t, C)`, vier Felder gleich, eine Seite mit `notes`, die andere ohne → Ergebnis trägt `notes` und `t + 1 s`.
  - Zwei neue Geräte ergänzen denselben alten Stand unabhängig, dann `merge` ihrer Ergebnisse → kein Konflikt, gleicher Eintrag.
  - Reine Notiz-Änderung auf beiden Seiten nach `last_pull_at` → ein Konflikt, beide Kandidaten tragen ihre `notes`.
  - Tombstone (neuer) gegen lebenden Tag mit Notizen → Tombstone gewinnt unverändert (Review Focus 4).
  - Schlüsselloser Stand mit `modified_at == ""` gegen Stand mit Notizen → kein Erben, keine Ausnahme, `merge(a, b)` und `merge(b, a)` gleich (Review Focus 3).
  - `notes: "kaputt"` auf einer Seite → keine Ausnahme (Review Focus 1).
  - Permutationstest: `_random_doc` vergibt mit einer Wahrscheinlichkeit `notes` (`{}` oder mit Notiz zur Startzeit) und lässt den Schlüssel sonst weg; der bestehende Test auf Kommutativität und Idempotenz bleibt grün.
- [ ] **Step 2:** `pytest tests/test_sync_notes.py -q` → FAIL.
- [ ] **Step 3:** Umsetzen.
- [ ] **Step 4:** `pytest tests/test_sync_notes.py tests/test_sync.py tests/test_sync_determinism.py tests/test_sync_journal.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(notizen): Merge ergänzt Notizen, die ein alter Stand nicht kennt (Refs #519)`.

### Task 4: Gelöste Konflikte

**Files:**
- Modify: `src/sync.py` (Auflösungs-Schleife in `merge`, `resolve_conflict`)
- Test: `tests/test_sync_notes.py`

**Interfaces:**
- Consumes: `slot_notes.resolution_notes`, `notes_of`.
- Produces: `conflict["resolution"]` trägt bei Eintrags-Konflikten optional `notes` auf oberster Ebene. `resolve_conflict` bleibt in der Signatur gleich; `chosen_value` darf `notes` tragen, muss aber nicht (der Dialog reicht heute nur `slots` und `deleted`).

- Schleife in `merge`: `notes = resolution_notes(resolution, c.get("candidates") or [], section.get(c["key"]))`; ist das Ergebnis nicht `None`, bekommt `candidate` den Schlüssel `notes`. Die Ersetzungsbedingung bleibt.
- `resolve_conflict`, Eintrag, nicht gelöscht: `notes = resolution_notes(chosen_value, target["candidates"], storage.get_all_raw().get(target["key"]))`. Nicht `None` → `target["resolution"]` bekommt `notes`, und gespeichert werden die Slots mit ausdrücklichem `notiz` je Slot (`notes.get(start, "")`), damit `Storage.save` nicht vom bisherigen Stand erbt. `None` → wie heute.

- [ ] **Step 1: Failing tests:**
  - `resolve_conflict` mit `chosen_value` = Slots von Kandidat A (ohne `notes` im `chosen_value`), A trägt `{"08:00": "KA"}`, gespeichert ist B mit `{"08:00": "KB"}` → Storage und `resolution["notes"]` tragen `KA`.
  - Dieselbe Lage, gewählt wird B ohne Schlüssel (alter Stand), A mit `{"08:00": "KA"}` → `KA` (Erben vom anderen Kandidaten).
  - Kein Kandidat mit `notes`, kein `notes` im Bestand → `resolution` ohne `notes`, Datei-Eintrag ohne `notes`.
  - Heilung nach einem alten Gerät: lokal Eintrag `(t, A, notes {"08:00": "K"})` plus gelöster Konflikt mit `resolved_at == t`, `resolved_by == A`, `resolution` mit `notes`; remote dasselbe, aber der Eintrag ohne `notes` (so hinterlässt ihn die Schleife einer alten Version). `merge` → Eintrag mit `notes` und `modified_at == t + 1 s`, also `> resolved_at`. Ein zweites `merge` desselben Ergebnisses mit dem alten Remote ändert nichts mehr.
  - Auflösung ohne `notes` in der Schleife (altes Gerät hat aufgelöst, `resolved_at` neuer als der Eintrag): der Eintrag bekommt die Notizen des Kandidaten, dessen Slots der Auflösung gleichen.
- [ ] **Step 2:** `pytest tests/test_sync_notes.py -q` → FAIL.
- [ ] **Step 3:** Umsetzen.
- [ ] **Step 4:** `pytest tests/test_sync_notes.py tests/test_sync.py tests/test_sync_determinism.py tests/test_conflict_view.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(notizen): Konflikt-Auflösungen tragen und erben Notizen (Refs #519)`.

### Task 5: Lokale API

**Files:**
- Modify: `src/api_entry_write.py` (`_SLOT_KEYS`, `_parse_slot`, Fehlertext), `src/api_routes.py` (`_wire_slots`, `_put_entry`)
- Test: `tests/test_api_entry_write.py`, `tests/test_api_routes.py`

**Interfaces:**
- Consumes: `slot_notes.check_note`, `NoteError`, `effective_slots`.
- Produces: `parse_slots`/`parse_day_body` liefern je Slot die vier Felder und **zusätzlich `notiz` nur, wenn der Body es nennt** (geprüft, getrimmt, auch `""`). `mobile_sync` (Task 6) verlässt sich darauf.

- `_parse_slot`: `notiz` ist erlaubt; `NoteError` → `WriteError(422, "invalid_note", f"Slot {index}: {message}")`. Der Text der Meldung `invalid_slot` nennt `notiz` als erlaubtes Feld.
- `_wire_slots`: fünf Felder, `notiz` immer (`slot.get("notiz", "")`).
- `_put_entry`: `effective = effective_slots(slots, existing["slots"] if existing else [])`; `changed` vergleicht `existing["slots"]` mit `effective`; gespeichert wird `slots` (Storage erbt selbst); die Antwort liefert `_wire_slots(stored["slots"])`. Warnungen rechnen weiter auf `slots`.

- [ ] **Step 1: Failing tests:**
  - `parse_slots`: ohne `notiz` → kein Schlüssel im Ergebnis; mit `" K "` → `"K"`; `5`, `"a\nb"`, 201 Zeichen → `WriteError` 422 `invalid_note`; unbekanntes Feld weiter `invalid_slot`.
  - Route: `PUT` mit Notiz, `GET` zeigt `notiz`; `GET` eines Tages ohne Notiz zeigt `"notiz": ""`; `PUT` ohne `notiz` und geänderter Pause behält die Notiz (`changed: true`); derselbe `PUT` noch einmal → `changed: false`; `PUT` mit `"notiz": ""` entfernt sie (`changed: true`); `PUT` mit unverändertem Body ohne `notiz` auf einen Tag mit Notiz → `changed: false`.
- [ ] **Step 2:** `pytest tests/test_api_entry_write.py tests/test_api_routes.py -q` → die neuen FAIL.
- [ ] **Step 3:** Umsetzen. API-Doku unter `docs/` (nach `kategorie` in der Beschreibung der Slot-Felder suchen) um `notiz` und `invalid_note` ergänzen.
- [ ] **Step 4:** dieselben Tests → PASS. Bestehende Tests, die die Antwort eines `GET`/`PUT` auf Gleichheit prüfen, bekommen `"notiz": ""`.
- [ ] **Step 5: Commit** `feat(api): Notiz am Slot lesen und schreiben (Refs #519)`.

### Task 6: Handy-Abgleich

**Files:**
- Create: `pwa/test/fixtures/compat/sync-response-pre-notes.json` (Kopie der heutigen `sync-response.json`, vor jeder Änderung)
- Modify: `src/mobile_sync.py` (`_parse_entry`, `_phone_doc`, `_clean_slots`, `_clean_entry`, `_conflict_views`, `build_response`, `perform_sync`), `pwa/test/fixtures/sync-response.json`, `pwa/test/compat.test.js`
- Test: `tests/test_mobile_sync.py`, `tests/test_mobile_contract.py`

**Interfaces:**
- Consumes: `parse_slots` (Task 5), `slot_notes.notes_from_slots`, `notes_of`, `has_key`; die Erb-Regel aus Task 3.
- Produces (Draht): Antwort-Slots tragen `notiz` (immer, `""` ohne), ebenso die Slots in `conflicts[].versions[]`; die Antwort trägt `"slot_notes": true`. Anfrage-Slots dürfen `notiz` tragen.

- `_parse_entry`: tragen alle Slots `notiz` → Eintrag `{"slots": <vier Felder>, "notes": notes_from_slots(…), …}`; trägt keiner `notiz` → ohne `notes`; gemischt → `bad("notiz muss an allen Slots eines Tages stehen oder an keinem.")`.
- `_phone_doc(…, desktop_entries: Mapping[str, Any] | None = None)`: ein Handy-Eintrag mit `notes == {}` verliert den Schlüssel, wenn der Desktop-Eintrag dieses Datums fehlt, gelöscht ist oder den Schlüssel nicht hat. `perform_sync` übergibt `desktop_doc["entries"]`.
- `_clean_slots(raw, notes: Mapping[str, str] | None = None)`: fünf Felder; `_clean_entry` und `_conflict_views` reichen `notes_of(…)` hinein.
- Die Live-Anfrage `sync-request.json` bleibt in diesem PR unverändert (die PWA sendet `notiz` erst mit PR 3; dort wird ihr Vorgänger eingefroren).

- [ ] **Step 1:** `sync-response.json` nach `compat/sync-response-pre-notes.json` kopieren, unverändert.
- [ ] **Step 2: Failing tests:**
  - `parse_request`: Tag mit `notiz` an allen Slots → `entries[date]["notes"]`; ohne → kein Schlüssel; gemischt → `SyncError` 422 `invalid_entry`; ungültige Notiz → 422 `invalid_entry`.
  - `perform_sync`, alte PWA: Desktop-Tag mit Notiz, Anfrage ändert die Pause ohne `notiz` → gespeicherte Notiz bleibt; Antwort-Slot trägt sie.
  - Neue PWA löscht: Anfrage mit `notiz: ""` an allen Slots auf einen Tag mit Notiz → `notes == {}` im Bestand.
  - Neue PWA, Tag ohne Notizen am Desktop, Anfrage mit `notiz: ""` → gespeicherter Eintrag **ohne** `notes`.
  - Neue PWA setzt eine Notiz → im Bestand und in der Antwort.
  - Antwort: `slot_notes is True`; Konflikt-Versionen tragen `notiz`.
  - Vertrag (`test_mobile_contract.py`): die Live-Antwort hat die Form, die der Server sendet (bestehender Test, Fixture nachziehen); neu `test_pre_notes_response_is_really_pre_notes` (kein `slot_notes`, kein `notiz` in den Slots der eingefrorenen Datei); jede eingefrorene Anfrage unter `compat/` wird weiter angenommen (bestehende Tests bleiben unverändert grün).
- [ ] **Step 3:** `pytest tests/test_mobile_sync.py tests/test_mobile_contract.py -q` → die neuen FAIL.
- [ ] **Step 4:** Umsetzen; `sync-response.json` um `notiz` an jedem Eintrags- und Konflikt-Slot und `"slot_notes": true` ergänzen (ein Slot mit echter Notiz, die übrigen `""`). In `pwa/test/compat.test.js` einen Fall ergänzen, dass `parseSyncResponse` die eingefrorene Antwort `sync-response-pre-notes.json` annimmt (Muster der vorhandenen Fälle dort).
- [ ] **Step 5:** `pytest tests/test_mobile_sync.py tests/test_mobile_contract.py tests/test_mobile_routes.py tests/test_mobile_window.py tests/test_mobile_volume.py -q` → PASS. Dann `cd pwa && node --test` → PASS (die ausgelieferte PWA ignoriert die neuen Felder; schlägt ein Test fehl, der die Live-Antwort auf exakte Gleichheit prüft, ist das ein Befund für den PR-Text, kein Anlass, die PWA in diesem PR zu ändern, außer in der Erwartung des Tests).
- [ ] **Step 6: Commit** `feat(handy): Abgleich trägt Notizen, Fähigkeit slot_notes (Refs #519)`.

### Task 7: Webhook und Teilen

**Files:**
- Modify: `src/webhook.py` (`_project_slots`), `src/share.py` (`build_share_doc`)
- Test: `tests/test_webhook.py`, `tests/test_share.py`

**Interfaces:**
- Consumes: App-Form der Slots aus `Storage.get_all()`; `slot_notes.clean_note`.
- Produces: Webhook-Slot mit `notiz` nur, wenn nicht leer. Teilen-Datei: Slots mit genau vier Feldern.

- `share.py`: neue Funktion `_share_entry_shape(records: dict[str, Any]) -> dict[str, Any]` (Gegenstück zu `_share_reservation_shape`), in `build_share_doc` auf die Einträge angewandt. Sie projiziert auf `start`, `end`, `pause`, `kategorie` und lässt die Werte unverändert.

- [ ] **Step 1: Failing tests:**
  - Webhook: Slot mit Notiz → `"notiz": "Kunde Mustermann"` im Dokument; ohne Notiz → `json.dumps` des Dokuments ist identisch zu dem aus denselben Einträgen ohne jedes `notiz` (bitgleich); `PAYLOAD_SCHEMA_VERSION == 2`.
  - Teilen: `build_share_doc` aus einem Storage mit Notizen → kein Slot trägt `notiz`, `parse_share_doc(serialize_share_doc(doc))` nimmt das Dokument an, `schema_version == 3`.
  - Teilen, alter Absender: ein Dokument, das nach heutigem Muster direkt aus `{"slots": [vier Felder]}` gebaut ist, während die Datei `notes` am Eintrag trägt (Storage laden, `_user_shape` einer alten Version nachstellen: nur `{"slots": sanitize_slot(...)}`) → besteht den Validator.
  - Import (`apply_import`): Tag mit Notiz im Bestand, importierte Datei mit gleicher Startzeit und anderer Pause → Notiz bleibt.
- [ ] **Step 2:** `pytest tests/test_webhook.py tests/test_share.py -q` → die neuen FAIL.
- [ ] **Step 3:** Umsetzen.
- [ ] **Step 4:** `pytest tests/test_webhook.py tests/test_share.py tests/test_share_task.py tests/test_send_task_dispatch.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(notizen): Webhook nennt die Notiz, Teilen bleibt bei vier Feldern (Refs #519)`.

### Task 8: Doku und Gesamtprüfung

**Files:**
- Modify: `CLAUDE.md`, `src/CLAUDE.md`, `pwa/CLAUDE.md`, `docs/known-limitations.md`

- [ ] **Step 1:** Doku nachziehen, je eine Stelle pro Begründung:
  - `CLAUDE.md`, „Struktur“: Zeile für `src/slot_notes.py` (was es regelt, Format `notes` am Tag je Startzeit, klebriger Schlüssel, Gegenstück und Fixture); bei `src/storage.py` der Hinweis auf die App-Form mit `notiz`; bei `src/webhook.py` und `src/share.py` je ein Satz.
  - `src/CLAUDE.md`: im Absatz zu `storage.py` die Lese-/Schreibgrenze; im Absatz zu `sync.py` die Erb-Regel mit der Anhebung um 1 s und der Sonderfall der Auflösungs-Schleife; bei `mobile_sync.py` „Notizen reisen additiv mit“ (`slot_notes`, alle-oder-keiner je Tag); bei `api_entry_write.py`/`api_routes.py` das optionale Feld.
  - `pwa/CLAUDE.md`, „Kompatibilität“, Regel 4: `compat/sync-response-pre-notes.json` in die Liste der eingefrorenen Stände.
  - `docs/known-limitations.md`: die Grenzen aus der Spec, Abschnitt „Bekannte Grenzen“ (alte Version ändert Startzeit oder löscht; Rückkehr einer gelöschten Notiz in der Drei-Geräte-Reihenfolge; Anhebung um 1 s bei falsch gehenden Uhren).
- [ ] **Step 2:** `pytest -q` → alles grün außer den auf `master` schon roten Tests (vorher mit `git stash; pytest -q; git stash pop` oder auf `master` feststellen und im PR-Text nennen).
- [ ] **Step 3:** `ruff check .` → sauber. `pyright` → keine neuen Fehler.
- [ ] **Step 4:** `pytest --cov=src --cov-report=json tests/ -q`, dann `python scripts/coverage_gate.py coverage.json` → nicht unter `FLOOR`.
- [ ] **Step 5: Commit** `docs(notizen): Aufbau und Verträge der Slot-Notiz (Refs #519)`.

## Nicht in diesem PR

Tages-Dialog, Tooltip, Löschen-Dialog, Konfliktansicht, Bericht und README (PR 2); PWA samt `pwa/notes.js`, Live-Anfrage und deren eingefrorenem Vorgänger (PR 3); CHANGELOG und Version (Release-PR).
