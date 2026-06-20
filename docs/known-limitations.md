# Known Limitations

Persistente, bewusst (noch) nicht umgesetzte Limitierungen. Wird ergänzt, wenn neue dazukommen.

## Sync: Manuelle Tombstone-Kompaktierung

Mit dem Multi-Device-Sync-Feature (Design: [`superpowers/specs/2026-05-14-multi-device-sync-design.md`](superpowers/specs/2026-05-14-multi-device-sync-design.md)) entstehen zwei Arten von Tombstones:

- **Eintrags-Tombstones:** Gelöschte Tageseinträge bleiben als `{"deleted": true, "modified_at": ...}` im Sync-File, damit ein Delete sich gegen ein veraltetes Save eines anderen Geräts durchsetzt (Last-Write-Wins).
- **Konflikt-Tombstones:** Aufgelöste Konflikte (`resolved: true`) bleiben in der `conflicts`-Liste, damit andere Geräte die Resolution propagieren bzw. nicht versehentlich denselben Konflikt erneut anlegen.

**Praktische Auswirkung:** Bei normalem Gebrauch ist das viele Jahre unproblematisch — Größenordnung Kilobyte pro Jahr.

### Manuelle Kompaktierung

In den Einstellungen steht unter „Synchronisation" die Aktion **„Sync-Daten kompaktieren"**: Sie entfernt alle Eintrags- und Konflikt-Tombstones fleet-weit endgültig. Einmal ausführen genügt — alle anderen Geräte übernehmen die Bereinigung beim nächsten normalen Sync automatisch (über das `meta.gc_watermark`-Feld im Sync-Doc, Schema v2).

**Warum manuell statt automatisch:** In einem verteilten LWW-System ist sicheres automatisches GC ein bekannt hartes Problem. Sobald ein Tombstone weg ist, ist die Information „dieser Tag wurde gelöscht" verloren. Ein Gerät, das den Delete nie gesehen hat und noch einen lebenden Eintrag desselben Tages hält, würde ihn wieder auferstehen lassen (Resurrection). Die einzig vollständig sichere Vorbedingung — „alle Geräte haben den Tombstone gesehen" — lässt sich nicht zuverlässig automatisch ableiten. Die Kompaktierung wird daher zu einer bewussten, vom Nutzer ausgelösten Einmal-Aktion, die erfordert, dass alle Geräte aktuell und synchronisiert sind. Ausführliche Begründung: [`superpowers/specs/2026-06-09-tombstone-gc-design.md`](superpowers/specs/2026-06-09-tombstone-gc-design.md).

**Bedingung vor dem Ausführen:** Alle Geräte müssen auf einer Version mit Kompaktierungs-Support laufen und kürzlich synchronisiert haben. Die Aktion prüft beim Start, ob das Remote-Doc das neue Schema v2 trägt — ist das nicht der Fall (älteres Gerät hat zuletzt gepusht), bricht sie mit einem Hinweis ab.

### Akzeptierte Restrisiken

- **Altes Gerät offline während der Kompaktierung:** Ein Gerät auf einer Version ohne Kompaktierungs-Support, das beim Kompaktieren offline ist und danach mit veralteten, lebenden Daten zurückkehrt, kann Resurrection auslösen, weil es die Self-Heal-Suppression nicht kennt. Mitigation: der v1-Schema-Guard (Best-Effort-Erkennung aktiver v1-Geräte) und die Bestätigung. Ein zum Zeitpunkt der Aktion offline v1-Gerät bleibt unerkennbar — bewusst akzeptiert.
- **v2-Gerät mit Offline-Edit vor dem Watermark:** Ein v2-Gerät, das beim Kompaktieren offline war und einen lebenden Eintrag mit `modified_at` vor dem Watermark hält, verliert diesen Eintrag beim Zurückkehren (Regel 2 — Self-Heal-Suppression). Extrem selten in der Praxis (offline gewesene Geräte haben typischerweise keine alten unbewegten Einträge).
- **Clock-Skew:** Wie im bestehenden Sync — bei grob synchronen Uhren vernachlässigbar.

## Sync: Irreführende „älteres Gerät"-Meldung beim Einzelgerät-Upgrade auf v3

Mit dem Multi-Timeslot-/Kategorien-Feature steigt das Sync-Schema auf v3
(`slots` statt flacher `start/end/pause`-Keys). Der Pull-Pfad lehnt jedes
pre-v3-Remote-Doc ab (`sync._remote_is_pre_v3` in `src/main.py::_run_pull_in_background`)
und pausiert mit der Meldung `OLD_REMOTE_VERSION_MSG` („ein anderes Gerät nutzt
eine ältere App-Version").

**Symptom:** Ein Nutzer mit **nur einem Gerät**, der bisher v2 lokal *und* im
Sync genutzt hat, sieht beim **ersten** Start nach dem v3-Upgrade genau diese
Meldung — obwohl es gar kein anderes Gerät gibt. Der Guard greift hier auf das
**eigene**, zuletzt selbst gepushte v2-Doc auf Drive.

**Self-Heal:** Es korrigiert sich von selbst. Die lokalen Daten sind beim Start
bereits nach v3 migriert; der nächste Push (manuell oder beim Schließen)
überschreibt das Drive-Doc mit v3 — der `expected_etag` passt noch auf das
unveränderte v2-Doc, also kein Konflikt, kein Guard-Abbruch. Ab dem zweiten
Start ist alles normal.

**Auswirkung:** Reine UX-Kosmetik — **kein Datenverlust, kein Überschreiben**
fremder Daten. Nur die Meldung ist in diesem Einzelgerät-Fall einmalig
irreführend.

**Möglicher Fix (später, im Rahmen von PR #60):** Den Pull nicht pausieren,
wenn das pre-v3-Remote-Doc ausschließlich Einträge des **eigenen** `device_id`
enthält (= eigenes Alt-Doc, kein fremdes aktives Gerät) — dann still nach v3
migrieren/pushen. Alternativ die Meldung so umformulieren, dass sie den
Einzelgerät-Fall mit abdeckt. Der Guard für echte Multi-Device-Fälle bleibt
unangetastet.
