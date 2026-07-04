# Design: Threadsicherheit der Datenschicht (Audit H1/H2/M1)

> Stand 2026-07-04 · Branch `fix/dialog-accent-bar` · Ansatz A aus dem
> Brainstorming zum Audit `AUDIT-2026-07-04.md`.

## Problem

Die vier Stores (`storage.py`, `settings.py`, `conflicts_store.py`,
`reservations.py`) werden aus mehreren Threads konkurrierend gelesen und
geschrieben, besitzen aber **kein einziges Lock** (das einzige `threading.Lock`
in `src/` liegt in `single_instance.py:33`). Beteiligte Threads:

- **UI-Thread:** Dialog-Saves/Deletes (`storage.save/delete/save_many`,
  `settings.set*`, `conflicts_store.save_all`).
- **Startup-Pull-Daemon** (`main.py:353` → `_run_pull_in_background`):
  `build_local_doc` → `merge` → `apply_merged_doc`.
- **Sync-Worker** (`_run_push_blocking`/`_run_compaction_blocking`, jeweils über
  `BackgroundTaskRunner.run` **plus** einen inneren Timeout-Thread).
- **Reconcile-Worker** (`reservations_sync.reconcile_reservations`) auf
  `ReservationStore`.

Daraus die drei Audit-Findings:

- **H1 — Lost Update:** `build_local_doc` (Snapshot) → `merge` →
  `apply_merge` (`storage.py:157`: `self._data = dict(merged_entries)`, kompletter
  Replace). Ein UI-Save zwischen Snapshot und Replace wird überschrieben. Fenster
  ist beim Drive-Sync **klein** (Snapshot liegt bereits *nach* dem Download,
  Pull `main.py:99`/Push `:152`), aber ohne Lock real.
- **H2 — keine Re-Entrancy + geteilte `.tmp`:** `on_sync_clicked`
  (`sync_orchestrator.py:167`) hat keinen „läuft bereits"-Guard; Startup-Pull,
  Tray-Sync und Manual-Sync können parallel laufen. Alle Stores schreiben in
  denselben festen `self.filepath + ".tmp"` → zwei parallele `_save_to_disk`
  schreiben interleaved → `os.replace` aktiviert korruptes JSON (Datenverlust
  via Quarantäne beim nächsten Start).
- **M1 — verwaister Timeout-Worker:** `_run_push_blocking` (`main.py:169-174`)
  joint mit Timeout; der Daemon-Thread läuft danach weiter und kann später noch
  `apply_merged_doc`/`set_many` ausführen — parallel zur UI oder im Shutdown.

## Ziele / Nicht-Ziele

**Ziele:** H1, H2 und M1 an der Wurzel schließen; Konsistenz mit vorhandenen
Mustern; deterministisch testbar; minimale Signatur-/API-Störung; keine
UI-Freezes.

**Nicht-Ziele (bewusst außerhalb dieses Durchgangs):**
- **M6** store-übergreifende Transaktionalität (Crash *zwischen* den vier
  Apply-Writes bleibt möglich — der Lock serialisiert, macht aber nicht
  transaktional).
- **N1** `fsync` vor `os.replace`.
- **H5** `settings_dialog`-Thread-Vertrag (eigener Befund; der neue Settings-Lock
  macht dessen konkurrierende Writes immerhin *atomar*, behebt aber die
  `TclError`-Verlustproblematik nicht).
- **M2/M3** Drive Optimistic-Locking / Split-Brain.

## Ansatz A — Ein geteilter RLock + atomarer Apply + Sync-Guard

### Teil 1 — Geteilter RLock in allen vier Stores (→ H2b, Dict-Races)

Ein einziger `threading.RLock`, in `main.py` erzeugt und in alle vier
Store-Konstruktoren injiziert. Jede öffentliche Lese- **und** Schreibmethode
kapselt ihren Body in `with self._lock:`.

- Konstruktor-Signatur additiv: `__init__(..., lock=None)`. Bei `lock=None`
  legt der Store einen **eigenen** `RLock` an → bestehende Tests, die Stores
  direkt instanziieren, bleiben unverändert und trotzdem intern sicher.
- **`RLock`** (nicht `Lock`), weil (a) `settings.set` → `set_many` reentrant ist
  und (b) der atomare Apply-Block (Teil 2) den Lock hält, während er
  Store-Methoden aufruft, die ihn erneut nehmen.
- Zu kapselnde Methoden:
  - `Storage`: `get_all`, `get_all_raw`, `get`, `save`, `delete`, `save_many`,
    `apply_merge`.
  - `Settings`: `get`, `set_many`, `set_synced`, `apply_synced`,
    `get_synced_doc`.
  - `ConflictsStore`: `get_all`, `save_all`, `count_unresolved`.
  - `ReservationStore`: `get_all`, `get_all_raw`, `get`, `save`, `delete`,
    `apply_reconciled`.
  - Iterierende/kopierende Reads (`get_all`, `get_all_raw`) **müssen** gelockt
    sein: der echte Hazard ist ein In-Place-Write (`self._data[k] = …` in
    `save`) während ein anderer Thread in `dict()`/`json.dump` iteriert →
    `RuntimeError: dictionary changed size during iteration`. (Ein kompletter
    Replace wie in `apply_merge` mutiert das alte Dict dagegen nicht.)
  - `__init__`/`_load`/`_migrate_*` laufen vor dem Teilen des Locks
    (single-threaded beim Boot) — kein Lock nötig, aber unschädlich.
- Der **feste `.tmp`-Pfad bleibt** — mit serialisierten Writes ist er sicher;
  eindeutige Temp-Namen wären mit Lock redundant (YAGNI). Zweite Prozesse sind
  durch `single_instance` ausgeschlossen.

### Teil 2 — Atomarer Sync-Apply unter dem geteilten Lock (→ H1)

In den drei Flow-Funktionen in `main.py` wird der Block
`build_local_doc → merge → apply_merged_doc → last_pull_at/etag setzen` in
`with data_lock:` geklammert. Da der lokale Snapshot **innerhalb** des Locks
unmittelbar vor dem Apply gelesen wird, kann kein UI-Save interleaven → H1 zu.
Kein separater Rebase-Nachbau nötig (anders als `reservations_sync`, das *vor*
dem Netzwerk snapshotet).

- **Der Daten-Lock wird NIE über Netzwerk gehalten.** Die Block-Grenzen sind
  pro Flow verschieden, weil Push/Kompaktierung nach dem Apply noch uploaden:
  - **Pull** (`_run_pull_in_background`): Download ungelockt →
    `with data_lock:` { `build_local_doc` → `merge` → `apply_merged_doc` →
    `set_many(last_pull_at, drive_etag)` }. (Kein Netz nach dem Apply — ein
    Block reicht.)
  - **Push** (`_run_push_blocking`): Download ungelockt → `with data_lock:`
    { `build_local_doc` → `merge` → `apply_merged_doc` → zweites
    `build_local_doc` (Upload-Doc) → `json.dumps` } → **Upload ungelockt** →
    `set_many(last_pull_at, drive_etag)` danach (Store-Methode lockt selbst,
    kein äußerer Block nötig). Ein UI-Save zwischen Upload-Snapshot und
    `set_many` bleibt korrekt: LWW über `modified_at` gewinnt beim nächsten
    Merge (bestehende Semantik, nicht verschlechtert).
  - **Kompaktierung** (`_run_compaction_blocking`): Download ungelockt →
    `with data_lock:` { `build_local_doc` → `merge` → `apply_merged_doc` →
    `set(last_pull_at)` → `compact_local` → `build_local_doc` (Upload-Doc) →
    `json.dumps` } → Upload ungelockt → `set(drive_etag)` danach.
- Gehalten wird der Lock nur über `merge()`/`compact_local` (pure CPU, sub-ms
  bei Personal-App-Datenmengen) + die lokalen Disk-Writes → vernachlässigbarer
  UI-Stall.
- Verdrahtung des `data_lock`: in `main.py` erzeugt, an die vier Stores **und**
  an `App` übergeben; `App` reicht ihn an `SyncOrchestrator` (für
  `_run_push_blocking`/`push_on_quit`) und an den Startup-Pull-Thread weiter.
  Die Flow-Funktionen bekommen ihn als expliziten Parameter (kein Zugriff auf
  `storage._lock`).

### Teil 3 — Sync-Re-Entrancy-Guard (→ H2a, M1 benign)

Ein separater **plain `threading.Lock`** (der **Sync-Guard**, nicht der
Daten-Lock), ebenfalls in `main.py` erzeugt und an `App`/`SyncOrchestrator` +
Startup-Pull + Settings-Dialog (Kompaktierung) verteilt.

**Hartes Constraint — Guard-Lifecycle lebt im Worker, nie im UI-Done-Callback:**

- `App._marshal_to_ui` verwirft Callbacks still, wenn das Fenster geschlossen
  ist (`ui.py:451-455`) — ein Release im Done-Callback kann leaken.
- Entscheidender: `push_on_quit` blockiert den **UI-Thread** in
  `guard.acquire(timeout=…)`. Solange der UI-Thread blockiert, verarbeitet die
  Mainloop keine `after(0)`-Callbacks — ein Release im Done-Callback könnte
  also **nie** feuern, während der Quit darauf wartet. Jeder Quit während
  eines laufenden Syncs würde deterministisch in den Timeout laufen und den
  Abschluss-Push überspringen.
- Daher die Invariante: **Released wird der Guard im `finally` des Threads,
  der die Store-Mutationen ausführt** — beim Push/der Kompaktierung ist das der
  *innere* `_do`-Thread von `_run_push_blocking`/`_run_compaction_blocking`,
  NICHT der äußere `_push`-Worker (der released sonst beim Join-Timeout,
  während der innere Thread noch schreibt — der Verwaiste liefe wieder
  ungeguarded). Acquire am Sync-Einstieg:
  `if not guard.acquire(blocking=False): return {"ok": False, "skipped": True}`.
  Ob Acquire im Einstiegs-Thread + Release im inneren Thread (cross-thread,
  für plain `Lock` legal) oder beides in den inneren Thread wandert, entscheidet
  der Implementierungsplan — die Invariante (Release erst nach der letzten
  Store-Mutation, nie im UI-Callback, nie beim Join-Timeout) ist fix.
- Der Guard **muss** ein plain `Lock` bleiben (nie `RLock`): `Lock.release()`
  ist aus jedem Thread erlaubt, `RLock` erzwingt Owner-Release (`RuntimeError`)
  — relevant, da Quit-Acquire (UI-Thread) und Worker-Release (Daemon-Thread)
  denselben Guard mischen ([threading-Doku](https://docs.python.org/3/library/threading.html)).

Die Sync-Einstiege:

- **Startup-Pull** (`main.py`): Guard-Wrapper um den Thread-Target-Body
  (non-blocking-skip).
- **Manual-Sync** (`on_sync_clicked`): Guard-Acquire im `_push`-Worker
  (Release gemäß Invariante im innersten Thread);
  zusätzlich **Sync-Button deaktivieren** im UI-Thread vor `runner.run`
  (sichtbares Feedback), Re-Enable im Done-Callback. `skipped`-Result im
  Done-Callback: kein Fehlerdialog, nur `update_status_label()`.
- **Tray-Sync** (`tray_sync`): Guard im Worker; `skipped` → kein Toast.
- **Quit-Push** (`push_on_quit`): `guard.acquire(timeout=5)` auf dem UI-Thread
  ist mit Worker-Release korrekt: läuft ein Sync, wird der Guard frei, sobald
  dessen Upload endet; danach eigener Push (+ Release im `finally`). Schlägt
  das Acquire fehl → skip + Log; lokale Daten bleiben erhalten und syncen beim
  nächsten Start (bestehende Failure-Semantik der Suffix-Meldung).
  **Worst-Case-Quit-Dauer: 5 s Guard + 5 s Push-Timeout ≈ 10 s** (heute 5 s) —
  bewusster Trade-off, dokumentieren.
- **Kompaktierung** (Aufrufer ist `settings_dialog.py:546`!): Guard im Worker;
  `skipped`-Result → themed Hinweis „Synchronisation läuft gerade — bitte kurz
  warten" (user-getriggerte Aktion braucht Feedback, kein stiller Skip).

Verhalten sonst: **überspringen, kein Queueing**.

**M1 wird benign, nicht eliminiert:** Da der Guard im Worker-`finally` liegt,
hält der innere Timeout-Thread von `_run_push_blocking` ihn nach dem
Join-Timeout einfach weiter, bis er wirklich fertig ist — ein „verwaister"
Worker blockiert damit nur weitere Syncs (korrekt: er *ist* der laufende Sync),
statt parallel zu ihnen zu schreiben. Sein *später* Apply ist (a) atomar über
den Daten-Lock und (b) liest den lokalen Stand frisch innerhalb des Locks → er
kann **nicht korrumpieren**. Rest-Kaveat: Nach `root.destroy()` + Ende von
`main()` beendet der Interpreter-Shutdown Daemon-Threads **hart** (Kill beim
nächsten GIL-Take) — der Worker kann also mitten in der 4-Store-Apply-Sequenz
sterben. Jede *Einzeldatei* bleibt dank tmp+`os.replace` intakt; eine
Cross-Store-Inkonsistenz (z. B. Watermark hinkt) ist genau **M6** und bleibt
als solches außerhalb dieses Durchgangs. Das strukturelle Entfernen des
inneren Timeout-Threads wäre ein größerer Umbau und ist ebenfalls **nicht Teil
dieses Durchgangs**.

### Reservations (angrenzend, mitgenommen)

`ReservationStore` erhält denselben Lock (Write-Atomizität Reconcile-Thread vs.
UI-Save). Der bestehende Rebase+Apply in `reservations_sync.py:199-205` wird
**inklusive** `settings.set("last_calendar_sync_at", …)` in `with data_lock:`
geklammert — billig und konsistent, damit nicht ein Store-Sync ungelockt
bleibt. Klar gekennzeichnet als „angrenzend", nicht Kern-H1/H2.

## Lock-Ordnung / Deadlock-Analyse

- Zwei Locks: **Sync-Guard** (außen) und **Daten-Lock** (innen, im Apply-Block).
  Immer in dieser Schachtelung → kein Zyklus. Der Guard wird bewusst über den
  Netzwerkteil gehalten (er *soll* Syncs serialisieren); der Daten-Lock nie.
- Nur der Sync-Apply-Pfad hält den Daten-Lock über mehrere Store-Aufrufe; die
  verschachtelten Store-Methoden re-akquirieren denselben `RLock` reentrant.
- Kein anderer Pfad hält zwei Store-Locks gleichzeitig (es ist ohnehin ein
  geteilter Lock) → keine Ordnungsprobleme zwischen Stores.

## Teststrategie (deterministisch, keine Timing-Asserts)

Wegen fehlendem Windows-CI (M15) und bekannter Flakiness der einen Socket-Test-
Stelle (N23) ausschließlich `threading.Event`-Barrieren statt `sleep`:

1. **Guard-Skip (deterministisch):** Fake-`_push`, das auf ein `Event` blockiert;
   zweiter Sync-Aufruf während des ersten → wird übersprungen, `_push` genau
   einmal ausgeführt.
2. **Atomarer Apply / kein Lost Update (deterministisch):** Sync-Thread hält den
   geteilten Lock, simuliert langsamen Merge (wartet auf Test-`Event`); ein
   UI-Thread ruft `storage.save(dateX, …)` und blockiert nachweislich am Lock;
   nach Freigabe landet der Save **nach** dem `apply_merge`-Replace und
   überlebt deshalb (Ordering durch Serialisierung — NICHT über
   `modified_at`-Vergleich, der bei Sekundenauflösung im Test identisch wäre,
   vgl. Audit N2). Beweist die Serialisierung des Interleaves.
3. **Stress-Robustheit (stochastisch, ohne Timing-Assert):** N Threads mit
   gemischten `save`/`delete`/`apply_merge` auf einem Store mit geteiltem Lock +
   Temp-Datei; nach `join` ist die Datei stets valides JSON und keine Exception
   geflogen. Moderate Iterationszahl.

Bestehende Store-/Sync-Tests bleiben grün (Konstruktor `lock=None`-Default).

## Betroffene Dateien (Überblick)

- `src/storage.py`, `src/settings.py`, `src/conflicts_store.py`,
  `src/reservations.py` — `lock=None`-Param + `with self._lock:` in den Methoden.
- `src/main.py` — Lock + Guard erzeugen, an Stores/App/Pull-Thread verdrahten;
  Apply-Block in `_run_pull_in_background`/`_run_push_blocking`/
  `_run_compaction_blocking` klammern; Startup-Pull-Guard.
- `src/ui.py` (`App`) — `data_lock`/`sync_guard` durchreichen.
- `src/sync_orchestrator.py` — Guard-Wrapper im `_push`-Worker;
  `push_on_quit`-Acquire; Button-Disable/Re-Enable; `skipped`-Handling in den
  Done-Callbacks; Lock/Guard an `_run_push_blocking` weiter.
- `src/dialogs/settings_dialog.py` — Kompaktierungs-Aufruf (Z. 546) bekommt
  Guard + Daten-Lock durchgereicht; `skipped` → themed Hinweis.
- `src/reservations_sync.py` — Rebase+Apply-Block klammern (angrenzend).
- `tests/` — neue Tests 1–3; ggf. `src/CLAUDE.md` „Threading-Modell" ergänzen.

## Risiken

- **UI-Stall:** Daten-Lock über Disk-Writes → kurzer Stall bei langsamer Platte.
  Für Ein-Nutzer-App mit seltenen Writes akzeptiert.
- **Contention:** Ein globaler Lock serialisiert auch unabhängige Stores.
  Bei Personal-App praktisch null.
- **Quit-Dauer:** Worst Case ~10 s (5 s Guard-Wait + 5 s Push-Timeout) statt
  heute 5 s, wenn beim Beenden gerade ein Sync läuft. Akzeptierter Trade-off
  gegen den parallelen Doppel-Push.
- **Backward-Compat:** `lock=None`-Default hält bestehende Tests unverändert.
- **M1-Rest:** dokumentiert-benignes Restverhalten (redundanter, atomarer
  Disk-Write; Interpreter-Shutdown-Kill mitten in der Sequenz = M6, out of
  scope).
