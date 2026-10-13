# Reservierungen ohne Google-Kalender, auch auf dem Handy

Stand: 2026-10-12. Drei gestapelte PRs.

## Ziel

Reservierungen (zukünftige Soll-Zeiten) sollen **ohne** Google-Kalender
nutzbar sein. Der Nutzer entscheidet per Einstellung, ob er sie nutzt. Die
Handy-PWA kann sie wie der Desktop anlegen, ändern und löschen. Es gilt
weiterhin: nur heute und Zukunft.

Geräteübergreifend gibt es Reservierungen weiter nur über den
Google-Kalender. Wer nicht über Google synchronisiert, hat sie nur lokal
(und auf dem gekoppelten Handy). Das ist bewusst so entschieden.

## Ist-Zustand (Kurzfassung)

- `App._reservations_active()` (`src/ui.py`) ist `reservation_store is not None
  and gcal_enabled` und gatet Tages-Dialog, Rechtsklick-Löschen, Kalender-Marker,
  Sende-Erinnerung am Reservierungs-Slot und den Hinweis in `tab_reminders`.
- `ReminderScheduler` und Share-Dialog lesen den Store ohne Gate.
- `reservation_block_visible(day, today)` (`day >= today`) hängt nicht an Google
  und bleibt.
- Tombstones löst nur der Kalender-Reconcile ein; `drop_orphan_reservation_tombstones`
  verwirft sie, wenn nie abgeglichen wurde (`never_reconciled`).
- Die PWA und `mobile_sync.py` kennen keine Reservierungen.

## PR 1: Desktop entkoppeln

- Neue Einstellung `reservations_enabled`, Default `False`, **gerätelokal**
  (nicht in `SYNCED_SETTING_KEYS`).
- **Migration:** einmalig beim Start, Marker `reservations_migrated`
  (gerätelokal), Muster `dpi.migrate_ui_scale`. Ist `gcal_enabled` an, wird
  `reservations_enabled` gesetzt. Der Marker wird immer gesetzt, auch ohne
  Umstellung, damit ein später bewusst ausgeschalteter Wert nie überschrieben wird.
- `_reservations_active()` prüft `reservation_store is not None and
  reservations_enabled`.
- Der Kalender-Push (`trigger_reconcile`, `reconcile_on_start`) bleibt an
  `gcal_enabled` gebunden **und** an `_reservations_active`. Ist
  Reservierungen aus, wird nichts gepusht. Der Urlaub-Push bleibt unberührt
  (eigener Schalter `vacation_gcal_enabled`, nur an `gcal_enabled` und
  Kalenderwahl gekoppelt).
- **Einstellungen:** Schalter „Reservierungen verwenden" im Tab Arbeitszeit.
  Alles, was nur für Reservierungen da ist, wird bei ausgeschaltetem Schalter
  **ausgeblendet** statt ausgegraut (`FormRow`-Handle): der Abschnitt „An
  Reservierungstagen" im Tab Erinnerungen samt Standard-Minuten. Der Google-Kalender-
  Abschnitt bleibt sichtbar, weil auch der Urlaub-Push ihn nutzt; sein Schalter
  heißt künftig „Mit Google Kalender abgleichen" (Reservierungen und Urlaub).
  Der Hinweis „Braucht den Kalender-Abgleich" in `tab_reminders` entfällt.
- `send_reminder_scheduler` prüft `reservations_enabled` statt `gcal_enabled`.
  `ReminderScheduler` und Share-Dialog bekommen dasselbe Gate
  (`reservation_store` nur übergeben, wenn aktiv).
- **Tombstone-Sweep:** `never_reconciled` bleibt die Bedingung für Rechner ohne
  Kalender. Weil Reservierungen jetzt ohne Kalender existieren, würde der
  Sweep beim Start die Tombstones eines Rechners verwerfen, der die Funktion
  nutzt. Das ist unkritisch, solange kein Kalender-Partner existiert (ein
  Tombstone steuert nur das Löschen des Kalender-Events), und deshalb **gewollt**.
  Beim späteren Einschalten des Kalenders zeigt der Reconcile gelöschte Tage
  nicht wieder an, weil sie auch lokal verschwunden sind. In der Umsetzung ist zu
  prüfen, dass `sync_history`-Veto und diese Aussage zusammenpassen.
- Tests: Gate, Migration (alle drei Fälle), ausgeblendete Zeilen, Scheduler.
- README/CLAUDE.md: Abschnitt „Reservierungen & Google-Kalender" und der
  `_reservations_active`-Hinweis in `src/CLAUDE.md`.

## PR 2: Protokoll und Merge am Desktop

Additiv, `PROTOCOL` bleibt 2. **Zuerst** die aktuelle Form unter
`pwa/test/fixtures/compat/*-pre-reservations.json` einfrieren.

- **Anfrage** (optional): `reservations: {ISO: {slots: [{start, end, kategorie}], modified_at, deleted}}`.
  `parse_request` prüft als Fremddaten: Datum heute bis heute + 365 (sonst `422`
  für den Tag), Slot-Regeln wie bei Ist-Zeiten (`api_entry_write.parse_slots`,
  höchstens `MAX_SLOTS`), `modified_at` höchstens 15 Minuten in der Zukunft, die
  Uhrregel `clock_skew` vor den Einträgen. Nie `gcal_event_id` oder
  `send_reminder_minutes` vom Handy.
- **Merge:** `perform_sync` merged je Tag LWW (`modified_at`, Tiebreak wie
  `sync._lww_key`) in den `ReservationStore`, unter `data_lock`. Vorhandene
  Slots behalten `gcal_event_id` und `send_reminder_minutes` per Index
  (`ReservationStore.save` macht das). Ein Tombstone vom Handy löscht.
- **Antwort:** `reservations` mit allen aktiven Tagen von heute bis heute + 365,
  Form wie die Anfrage, **nur wenn** `reservations_enabled` an ist. Ein Tag, der
  in der Antwort fehlt, löscht ihn in der PWA nur im Zukunftsfenster.
  Reservierungen zählen nicht ins Mengenbudget der Ist-Zeiten.
- Ist `reservations_enabled` aus und das Handy sendet Reservierungen, werden sie
  ignoriert (nicht abgelehnt), die Antwort enthält kein Feld.
- Nach dem Merge ruft die Route `on_change`, das den Kalender-Abgleich anstößt,
  falls er aktiv ist (`trigger_reconcile`, wie im Tages-Dialog).
- Tests: `tests/test_mobile_sync.py`, `tests/test_mobile_contract.py` mit
  Fixtures, Lock-Reihenfolge `devices_lock` → `sync_guard` → `data_lock` bleibt.

## PR 3: PWA

- `store.js`/`db.js`: eigene Sammlung `reservations` mit `dirty_version`/
  `synced_version` wie bei den Ist-Zeiten; Anwenden der Antwort nur im
  Zukunftsfenster. `memory-adapter.js` und Tests ziehen mit.
- `sync.js`: sendet geänderte Reservierungstage, wendet `reservations` an.
  Fehlt das Feld in der Antwort, bleibt die Funktion verborgen (Feature-
  Erkennung, `parseReservations` liefert `null`).
- `view-model.js`/`views.js`: Marker in der Wochenansicht, Reservierungs-Block im
  Tages-Editor, nur für heute und Zukunft (`reservationBlockVisible`, Gleichlauf
  mit `reservation_block_visible` über eine Fixture). Löschen wie bei
  gespeicherten Slots nur über die vorhandene Lösch-Geste; in der Vergangenheit
  gar nichts.
- `PRECACHE` ergänzen, Version in `pwa/package.json` im Release-PR bumpen.
- `pwa/CLAUDE.md`: Modul- und Kompatibilitätsabschnitt.

## Nicht Teil dieser Arbeit

- Geräteübergreifender Sync von Reservierungen ohne Kalender.
- Konfliktdialog für Reservierungen (LWW genügt).
- Delta-Antworten.
- Aufräumen alter Reservierungen auf dem Handy (bleibt Desktop-Rechtsklick).

## Risiken

- Das „heute" des Handys kommt von der Handy-Uhr. Die Prüfung am Desktop nutzt
  seine eigene; die 15-Minuten-Regel fängt große Abweichungen ab. Tage an der
  Grenze können mit `422` abgelehnt werden und blockieren nur diesen Tag.
- Plattformspezifisch ist nichts, aber PR 1 ändert Einstellungs-UI: Pre-Release
  vor dem Release über alle drei Plattformen ist nicht nötig, ein
  Windows-Screenshot der Einstellungen genügt.
