# Known Limitations

Persistente, bewusst (noch) nicht umgesetzte Limitierungen. Wird ergänzt, wenn neue dazukommen.

## Sync: Tombstone-Kompaktierung ist manuell

Mit dem Multi-Device-Sync-Feature (Design: [`superpowers/specs/2026-05-14-multi-device-sync-design.md`](superpowers/specs/2026-05-14-multi-device-sync-design.md)) entstehen drei Arten von Tombstones:

- **Eintrags-Tombstones:** Gelöschte Tageseinträge bleiben als `{"deleted": true, "modified_at": ...}` im Sync-File, damit ein Delete sich gegen ein veraltetes Save eines anderen Geräts durchsetzt (Last-Write-Wins).
- **Konflikt-Tombstones:** Aufgelöste Konflikte (`resolved: true`) bleiben in der `conflicts`-Liste, damit andere Geräte die Resolution propagieren bzw. nicht versehentlich denselben Konflikt erneut anlegen.
- **Reservierungs-Tombstones:** Gelöschte Reservierungen bleiben als Marker liegen, bis der Kalender-Abgleich sie einlöst — sie steuern, dass das zugehörige Google-Kalender-Event beim nächsten Reconcile mit gelöscht wird (`reservations_sync._merge_one_date`, Fall 3).

**Praktische Auswirkung:** Bei normalem Gebrauch ist das viele Jahre unproblematisch — Größenordnung Kilobyte pro Jahr.

### Automatisch aufgeräumt: Geräte, die nie gesynct/abgeglichen haben

Seit 1.19.1 (Audit N6) verwirft die App beim Start Tombstones, die nie einen
Abnehmer bekommen können: `sync.drop_orphan_tombstones` (Eintrags-Tombstones)
und `reservations_sync.drop_orphan_reservation_tombstones`
(Reservierungs-Tombstones), gebündelt in `main._sweep_orphan_tombstones`. Ohne
Drive-Sync bzw. Kalender-Abgleich gibt es niemanden, gegen den ein Tombstone je
wirken könnte — und die Kompaktierung als einziger anderer GC-Pfad hängt am
Google-Tab, ist ohne Sync also gar nicht erreichbar.

Die Bedingung ist bewusst eng: Das jeweilige Feature muss **nie** aktiv gewesen
sein (`never_synced` / `never_reconciled`), nicht bloß gerade aus. Wer den Sync
abschaltet, dessen Remote kennt die gelöschten Tage weiter — fiele der Tombstone
hier, kämen sie beim Wiedereinschalten zurück.

Gegen einen Settings-Reset ist der Sweep zusätzlich abgesichert (Audit M4): ein
korruptes `settings.json` setzt `Settings` auf Defaults zurück, ein tatsächlich
gesyncter Rechner sähe dann wie „nie gesynct" aus und verlöre irreversibel seine
Tombstones (Resurrection gelöschter Tage). Die dauerhafte Gegenprobe ist ein
eigener, write-once geschriebener Marker neben den Nutzerdaten
(`sync_history.json`) — ist er gesetzt, unterbleibt der jeweilige Sweep. Die
Semantik ist durchgängig fail-safe: im Zweifel Tombstones behalten.

**Für Geräte, die am Sync teilnehmen, ändert das nichts** — dort wachsen die
Tombstones weiter, bis die Kompaktierung einmal ausgelöst wird.

### Manuelle Kompaktierung

In den Einstellungen steht im Tab **Google** die Aktion **„Sync-Daten kompaktieren"**: Sie entfernt alle Eintrags- und Konflikt-Tombstones fleet-weit endgültig. Einmal ausführen genügt — alle anderen Geräte übernehmen die Bereinigung beim nächsten normalen Sync automatisch (über das `meta.gc_watermark`-Feld im Sync-Doc, Schema v2).

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

## Windows: kurzes Aufblitzen der hellen Titelleiste beim Öffnen von Dialogen

`apply_dark_titlebar`/`disable_min_max` (`src/theme.py`) sind bewusst per
`window.after(100, …)` verzögert — frühere Tk-eigene Fenster-Property-Calls
würden das DWM-Farb-Attribut sonst clobbern. In diesem ~100ms-Fenster rendert
Windows die Titelleiste kurz im hellen Standard-Stil, bevor sie umgefärbt
wird.

**Warum nicht gefixt:** Ein Versuch, das Fenster bis dahin per `-alpha 0.0`
unsichtbar zu halten, macht `center_dialog_on_parent` auf diesem Windows/Tk-
Gespann dauerhaft kaputt — ein frisch erzeugtes Toplevel, das direkt
`-alpha 0.0` bekommt, ignoriert spätere `geometry()`-Aufrufe komplett (Dialog
landet bei `+0+0`). Details/Reproduktion: [`CLAUDE.md`](../CLAUDE.md)
(Abschnitt „Dialog-Styling"). Als Kompromiss akzeptiert.

## Tests: die Tk-/UI-Schicht ist bewusst nicht automatisiert getestet

Getestet wird **Logik, nicht UI**. Dialog-Aufbau, Grid-Rendering und
Event-Bindings (auch das Rechtsklick-Löschmodell) haben keine automatisierten
Tests — weder headless-simuliert noch per `xvfb` mit echtem Tk.

**Warum:** Der Nutzen trägt die Kosten nicht. Widget-Tests sind die brüchigste
Testsorte — sie brechen bei Layout-Umbauten, ohne dass ein Verhalten kaputt
wäre, und erzeugen damit genau die Sorte Rot, die man wegklickt statt liest.
Dazu käme dauerhaft ein `xvfb`-Pfad in der CI, den sonst nichts braucht. Und
das, was wirklich nur auf der echten Plattform bricht — macOS-Sekundärklick
(`<Button-2>`/Control-Klick, ✕-Delete-Gate), Linux/KDE-Tray (#42),
Fenster-Chrome — deckt ein Linux-Framebuffer strukturell ohnehin nicht ab.

**Was stattdessen greift** — das ist der eigentliche Punkt, nicht ein Verzicht
ohne Ersatz:

1. **Zuschnitt statt Testabdeckung.** Verhalten wird konsequent Tk-frei
   herausgezogen und dort getestet: `time_utils`, `sync`, `workweek`,
   `weekly_limit`, `pause_requirement`, `reminders`, `send_reminder`, die
   `*_task`-Kerne der Dialoge. Die kritische Schicht (Persistenz/Sync/Report)
   liegt damit bei ~90 % Abdeckung. Lebt Logik nur im Widget, ist sie am
   falschen Ort — der Fix ist das Herausziehen, nicht ein UI-Test.
2. **Plattform-Verifikation über den Pre-Release** (siehe `CLAUDE.md`,
   „Plattformspezifische PRs"), weil dort echte Fenster auf echten Systemen
   entstehen.

**Was das kostet — offen benannt:** Reine Verdrahtungs- und Crash-Fehler
(„Dialog wirft beim Öffnen", „Speichern liest die falsche Tk-Variable") fallen
erst beim manuellen Test auf. Das ist der akzeptierte Preis; wer eine
Dialog-Verdrahtung umbaut, verifiziert sie von Hand.

**Herkunft:** Audit-Finding **M16** (#131) stellte die Grundsatzfrage
(„schließen oder als akzeptierte Lücke dokumentieren"), **#148** schlug den
engen `xvfb`-Ausschnitt vor. Beide sind mit dieser Entscheidung geschlossen —
sie ist damit getroffen, nicht vertagt. Ältere Specs, die „Audit M16 offen"
schreiben, sind an dieser Stelle überholt.
