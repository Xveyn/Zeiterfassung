# Tombstone-Kompaktierung für den Multi-Device-Sync (manuell)

**Datum:** 2026-06-09
**Status:** Design (zur Umsetzung)
**Bezug:** löst die in [`docs/known-limitations.md`](../../known-limitations.md) festgehaltene Limitierung „Sync: Keine Tombstone-Garbage-Collection" auf. Baut auf [`2026-05-14-multi-device-sync-design.md`](2026-05-14-multi-device-sync-design.md) auf.

## Problem

Der Multi-Device-Sync führt zwei Arten von Tombstones, die **unbeschränkt** wachsen und nie entfernt werden:

1. **Eintrags-Tombstones** — gelöschte Tageseinträge bleiben als `{"deleted": true, "start": null, "end": null, "pause": null, "modified_at": …}` im Storage und im Drive-Sync-File (`storage.py::delete`). Nötig, damit ein Delete sich per Last-Write-Wins gegen ein veraltetes Save eines anderen Geräts durchsetzt.
2. **Konflikt-Tombstones** — aufgelöste Konflikte (`resolved: true`) bleiben in der `conflicts`-Liste (`sync.py::merge`), damit die Resolution propagiert und derselbe Konflikt nicht erneut angelegt wird.

Praktisch unkritisch (KB/Jahr), aber das Sync-File wird nie kleiner.

## Warum manuell statt automatisch

Sicheres **automatisches** Tombstone-GC in einem verteilten LWW-System ist ein bekannt hartes Problem: sobald ein Tombstone weg ist, ist die Information „dieser Tag wurde gelöscht" verloren. Ein Gerät, das den Delete nie gesehen hat und noch einen *lebenden* Eintrag desselben Tages hält, würde diesen wieder auferstehen lassen (Resurrection). Die einzig vollständig sichere Vorbedingung — „alle Geräte haben den Tombstone gesehen" — lässt sich nicht zuverlässig aus dem Sync-Doc ableiten, insbesondere weil **alte Client-Versionen** (Sync ohne Kompaktierungs-Support) sich nicht in einer Geräte-Registry ankündigen und die Self-Heal-Logik nicht kennen. Eine automatische GC-Heuristik würde die Daten-Integrität an einer **stillen, nicht erzwingbaren Betriebsbedingung** aufhängen.

**Entscheidung:** Die Kompaktierung wird zu einer **bewussten, vom Nutzer ausgelösten Einmal-Aktion** an einem definierten Zeitpunkt (statt eines Hintergrund-Automatismus). Damit verschiebt sich die „Fleet ist bereit"-Zusicherung auf eine explizite Handlung — die einfachste korrekte Form für eine Single-User-App, bei der der Nutzer seine eigenen Geräte kennt.

### Akzeptierte Restrisiken (bewusste Entscheidung)

- **Altes Client-Gerät (v1), das während der Kompaktierung offline ist und später mit veralteten, lebenden Daten zurückkehrt:** Resurrection möglich, weil v1 die Self-Heal-Suppression (siehe unten) nicht kennt. Mitigation: die Kompaktierung verweigert, wenn der aktuelle Remote-Stand nicht v2 ist (Best-Effort-Erkennung aktiver v1-Geräte), und fordert eine explizite Nutzer-Bestätigung („alle Geräte aktuell & synchronisiert"). Ein zu diesem Zeitpunkt offline-v1-Gerät bleibt unerkennbar — bewusst akzeptiert.
- **v2-Gerät mit echtem Offline-Edit, dessen `modified_at` vor dem Watermark liegt:** würde beim Self-Heal verworfen statt hochgeladen (extrem selten, vgl. „tote Gerät in der Schublade hat keine Offline-Edits").
- **Clock-Skew:** alle Zeitvergleiche sind geräteübergreifend — wie schon im bestehenden Sync. Bei grob synchronen Uhren vernachlässigbar.

## Datenmodell — Schema-Version 1 → 2

Das Sync-Doc bekommt einen schlanken `meta`-Block mit **einem** Feld:

```json
{
  "schema_version": 2,
  "entries":   { … },
  "settings":  { … },
  "conflicts": [ … ],
  "meta": { "gc_watermark": "<ISO>" }
}
```

- `meta.gc_watermark` — Zeitpunkt der letzten Kompaktierung. Tombstones mit `modified_at`/`resolved_at` **vor** diesem Wert gelten fleet-weit als erledigt und werden entfernt. **Wird ausschließlich durch die Kompaktierungs-Aktion gesetzt** (nicht automatisch im Merge berechnet). Monoton nicht-fallend.
- **Keine** Geräte-Registry, **keine** Heartbeats, **kein** Cutoff. Bewusst weggelassen — die manuelle Auslösung ersetzt die automatische „alle haben gesehen"-Berechnung.

**Lokale Persistenz:** ein nicht-synchronisierter Settings-Key `gc_watermark: str` — exakt das Muster der bestehenden lokalen Bookkeeping-Keys `last_pull_at` / `drive_etag`. Nötig, damit ein Push **ohne** vorausgehenden Pull den `meta`-Block korrekt mit hochlädt (Symmetrie zum `build_local_doc` → `merge` → `apply_merged_doc`-Roundtrip).

**Backwards-Kompatibilität:** Ein altes Doc (Schema v1, kein `meta`) wird beim Lesen als `{gc_watermark: ""}` behandelt. Leeres Watermark (`""`) → weder Drop noch Suppression → exakt heutiges Verhalten. Ein nicht aktualisiertes v1-Gerät lädt sein Doc ohne `meta` hoch und setzt das Remote-Watermark damit zurück (`""`). Weil das Watermark im Merge **monoton** gehandhabt wird, gewinnt das höhere lokale Watermark eines v2-Geräts beim nächsten Merge zurück — ein v1-Clobber **verzögert** also höchstens die Propagation, **erzeugt** aber kein Drop/keine Suppression (das tut nur die manuelle Aktion). Auf der v2-Seite geht durch den Clobber **keine** Live-Daten verloren (Regel 1 entfernt nur Tombstones; Regel 2 ist auf `remote.gc_watermark` gegated, und `last_pull_at < ""` ist nie wahr → keine Spurious-Suppression).

Die Resurrection-Gefahr durch ein v1-Gerät ist allerdings **nicht** auf das v1-Gerät beschränkt: hält ein v1-Gerät noch einen *lebenden* Eintrag eines anderswo gelöschten-und-kompaktierten Tages, lädt es ihn beim Push wieder hoch — ein korrektes v2-Gerät pullt ihn dann (`_merge_one(None, remote_live)` → remote gewinnt) und der Tag **erscheint auch auf v2 wieder**. Gleiche Wurzel (v1 kennt Regel 2 nicht) und gleiche akzeptierte Risikoklasse; die Mitigationen (Schema-Guard + Bestätigung) zielen genau darauf.

## Algorithmus

Entscheidungs-Logik in `sync.py` (pure, unit-testbar). Orchestrierung (Pull→Check→Kompaktieren→Push) in `main.py`/`ui.py` analog zum bestehenden manuellen Sync.

### Kompaktierungs-Aktion (vom Nutzer ausgelöst)

1. **Bestätigungs-Dialog** mit klarem Warnhinweis: „Entfernt alte gelöschte Einträge endgültig aus dem Sync. Nur ausführen, wenn alle deine Geräte auf der aktuellen Version sind und kürzlich synchronisiert haben."
2. **Frischer Pull** des Remote-Docs — **immer** das Ergebnis dieses Pulls prüfen, **nie** ein gecachtes/älteres Remote-Doc (sonst entgeht ein v1-Gerät, das zwischen dem letzten Hintergrund-Sync und dieser Aktion gepusht hat, dem Guard).
3. **v1-Schema-Guard:** ist das frisch gepullte Remote-Doc `schema_version < 2` bzw. ohne `meta`, ist gerade ein älteres Gerät aktiv → **abbrechen** mit Hinweis „Ein Gerät nutzt noch eine ältere Version — bitte erst alle Geräte aktualisieren." (Best-Effort; ein *offline* v1-Gerät bleibt unerkennbar, daher zusätzlich die Bestätigung aus Schritt 1.)
4. **Watermark setzen + lokal kompaktieren (ein lokaler Schreibvorgang):** `gc_watermark = now` in den Settings-Cache persistieren **und** Eintrags-Tombstones (`deleted==true`, `modified_at < now`) sowie aufgelöste Konflikte (`resolved==true`, `resolved_at < now`) aus dem lokalen Store entfernen. Beide Effekte lokal festschreiben, **bevor** gepusht wird.
5. **Push** des kompaktierten Docs (inkl. neuem Watermark).

Die Verbreitung auf die anderen Geräte erledigt deren nächster normaler Sync über die Merge-Regeln unten — **einmal kompaktieren genügt fleet-weit.**

**Partial-Failure / Recovery (Invariante):** Schlägt der Push (Schritt 5) fehl, ist der teilweise angewandte Zustand **sicher** — kein Datenverlust, keine Resurrection. Lokal gilt dann `gc_watermark = now`, lokale Tombstones sind weg; der Remote ist **unverändert** (Push fehlgeschlagen), andere Geräte also unbeeinflusst. Beim nächsten normalen Sync gewinnt das höhere lokale Watermark (monoton), Regel 1 entfernt die im Remote noch vorhandenen settled Tombstones, und der Push lädt das kompaktierte Doc hoch → die Aktion **vollendet sich selbst**. Kein Locking/keine Transaktion nötig; ein Implementierer darf den Halb-Zustand bewusst stehen lassen.

### Merge-Regeln (in `merge`, bei jedem Sync — Signatur unverändert)

`merge(local, remote, last_pull_at)` propagiert das Watermark und wendet zwei Regeln an. **`now`/`cutoff` werden nicht gebraucht** — das Watermark kommt fertig aus dem Doc.

```
watermark = max(local.meta.gc_watermark, remote.meta.gc_watermark)   # monoton
merged.meta.gc_watermark = watermark
excluded  = (last_pull_at != "" UND last_pull_at < remote.meta.gc_watermark)
```

**Regel 1 — Kompaktierung propagieren (für alle Geräte):** Aus dem Merge-Ergebnis entfernen:
- jeden Eintrag mit `deleted == true` und `modified_at < watermark`;
- jeden Konflikt mit `resolved == true`, `resolved_at` nicht leer/None, und `resolved_at < watermark`.

Läuft als **letzter** Schritt im `merge`, nach der bestehenden Resolution-Application (`sync.py:174-198`), damit ein gerade angewandter Resolution-Wert nicht durch das Entfernen seines Konflikts verloren geht. Ein resolved Konflikt mit `resolved_at` `None`/`""` wird behalten (defensiv gegen `None < str`). Unresolved Konflikte werden nie entfernt.

So lässt ein Gerät, das den Delete bereits gesehen hat (lokaler Tombstone), diesen fallen und lädt ihn nicht erneut hoch → die Kompaktierung **bleibt** fleet-weit bestehen.

**Regel 2 — Self-Heal-Suppression (nur für exkludierte Geräte):** Im Merge-Zweig „lokal vorhanden, remote fehlt" (`remote is None`, `local is not None`):
- wenn `excluded` UND `local.modified_at < remote.meta.gc_watermark` → **verwerfen** (nicht übernehmen, nicht hochladen). Verhindert Resurrection eines anderswo gelöschten Tages durch ein zurückkehrendes Gerät.
- sonst → behalten (bisheriges Verhalten: lokaler Wert gewinnt).

**Warum die `excluded`-Bedingung essentiell ist:** ein Erstsync-Gerät (`last_pull_at == ""`) mit vorbestehender lokaler Historie (migrierte Einträge, altes `modified_at`) ist **nicht** `excluded` → seine Historie wird normal hochgeladen statt verworfen. Nur ein lange offline gewesenes Gerät (`last_pull_at` alt, `< watermark`) löst Suppression aus — genau der Zielfall.

**Wirksamkeit über den App-Lifecycle:** Regel 2 lebt nur im `merge` (Pull-Pfad / Konflikt-Retry-Pull). Das genügt, weil `main.py` beim **Start pullt** und beim **Schließen pusht**: ein zurückkehrendes v2-Gerät pullt zuerst, dabei räumt Regel 2 seine veralteten Einträge ab — **bevor** sein Quit-Push sie hochladen könnte. (Der Konflikt-Retry-Pfad `main.py:112-124` aktualisiert `last_pull_at` bewusst nicht — das bleibt so; ein dort gesetztes `last_pull_at` würde die `excluded`-Erkennung vor dem unmittelbaren Re-Push aushebeln.)

### Robustheit gegen falsche Nutzer-Zusicherung (reiner v2-Fleet)

Selbst wenn der Nutzer die „alle synchronisiert"-Bestätigung **falsch** gibt und ein v2-Gerät beim Kompaktieren offline war: Regel 2 fängt es ab. Das zurückkehrende v2-Gerät ist `excluded` (`last_pull_at < watermark`) und verwirft seinen veralteten lebenden Eintrag → keine Resurrection. Die Bestätigung + der Schema-Guard sind damit primär ein Schutz gegen **v1**-Geräte (die Regel 2 nicht haben).

### Persistenz (in `apply_merged_doc`)

Schreibt `merged.meta.gc_watermark` in den lokalen Settings-Cache (`gc_watermark`), zusätzlich zum bestehenden Anwenden von entries/settings/conflicts. `apply_merge` (`storage.py:119`) entfernt durch Regel 1 nur Einträge — es werden nie Einträge mit fehlenden Pflichtfeldern erzeugt, der Required-Key-Validator bleibt erfüllt.

## Betroffene Dateien

| Datei | Änderung |
|-------|----------|
| `src/sync.py` | `SCHEMA_VERSION = 2`; Watermark-Propagation + Regel 1 (Drop, als letzter Schritt) + Regel 2 (excluded-Suppression) in `merge` (**Signatur unverändert**); `build_local_doc` übernimmt `gc_watermark` aus Settings in `meta`; `apply_merged_doc` persistiert `meta.gc_watermark`; neue pure Helfer `compact_doc(doc, now)` / Strip-Logik |
| `src/settings.py` | neuer lokaler (nicht-synchronisierter) Key in `DEFAULTS`: `gc_watermark = ""` |
| `src/storage.py` | lokales Entfernen settled Tombstones über **Wiederverwendung von `apply_merge`** mit vorgefiltertem Dict (kein zweiter Strip-Pfad — Required-Key-Validator und Atomic-Write bleiben auf einem Pfad) |
| `src/main.py` | Orchestrierung der Kompaktierung: Pull → v1-Schema-Guard → Watermark/Compact → Push (analog `_run_pull_in_background`/`_run_push_blocking`, Fehler per `messagebox.showerror`+`traceback` sichtbar machen) |
| `src/ui.py` / `src/dialogs/settings_dialog.py` | Button „Sync-Daten kompaktieren" bei den Sync-Controls + Bestätigungs-Dialog mit Warnhinweis |
| `docs/known-limitations.md` | Eintrag von „kein GC" auf „manuelle Kompaktierung vorhanden" umschreiben: bewusste Entscheidung gegen Auto-GC, akzeptierte Restrisiken (v1-offline-Rückkehr, v2-Offline-Edit-Edge, Clock-Skew) |
| `tests/test_sync.py` | neue Tests, siehe unten |

## Invarianten (Review-Fokus)

1. **Watermark nur manuell:** `merge` setzt das Watermark **nie** hoch außer per Propagation (`max`); es steigt ausschließlich durch die Kompaktierungs-Aktion.
2. **Monotones Watermark:** `merged.meta.gc_watermark = max(local, remote)` — fällt nie zurück (ein v1-`meta`-Verlust wird durch das höhere lokale Watermark wieder eingeholt).
3. **Regel 1 propagiert & bleibt:** ein einmal kompaktierter Tombstone (`< watermark`) wird auf keinem v2-Gerät erneut hochgeladen.
4. **Regel 2 nur für exkludierte Geräte:** Erstsync- und normal genutzte Geräte verlieren nie lokale Daten durch Suppression.
5. **Drop nach Resolution-Application:** kein resolved-Wert geht verloren.
6. **Keine Verhaltensänderung ohne Watermark:** bei `gc_watermark == ""` verhält sich `merge` exakt wie heute (kein Drop, keine Suppression).
7. **Idempotenz:** wiederholter `merge` mit identischen Inputs erzeugt identisches Ergebnis.

## Tests (`tests/test_sync.py` + `tests/test_storage.py`, ohne externe Deps)

- **Watermark-Propagation:** `max(local, remote)`; Monotonie (remote-`meta` fehlt → lokales Watermark gewinnt); v1-Doc ohne `meta` → Watermark `""`.
- **Regel 1 (Drop):** Eintrags-Tombstone `modified_at < watermark` entfernt; `== watermark` bleibt (strikte Grenze); `> watermark` (frischer Delete) bleibt und propagiert normal. Konflikt resolved `< watermark` weg; `resolved_at` `None`/`""` bleibt (kein Crash); unresolved bleibt; resolved-Wert wird vor Drop korrekt in entries angewandt.
- **Regel 1 propagiert & bleibt:** Gerät B mit lokalem Tombstone pullt kompaktierten Remote → B verwirft Tombstone lokal und lädt ihn nicht erneut hoch.
- **Regel 2 (Suppression):** `excluded`-Gerät verwirft alten remote-fehlenden lebenden Eintrag; Erstsync-Gerät (`last_pull_at == ""`) behält/lädt hoch; frischer Offline-Edit (`modified_at >= watermark`) bleibt.
- **Falsche Zusicherung, reiner v2-Fleet:** v2-Straggler wird durch Regel 2 abgefangen (kein Resurrection).
- **Kompaktierungs-Aktion (pure Teile):** `compact_doc(doc, now)` setzt Watermark + strippt settled Tombstones/Konflikte; idempotent bei erneutem Lauf. Zweimal-Kompaktieren in Folge (zweiter Lauf ohne verbliebene settled Tombstones) ist ein sauberer No-op, der das Watermark dennoch aufs neue `now` setzt (wiederholte User-Klicks dürfen nicht fehlschlagen).
- **Backwards-compat:** v1-Doc ohne `meta` → kein Drop/keine Suppression, Ergebnis wie bisher.
- **Idempotenz:** doppelter `merge`.

Hinweis: der v1-Schema-Guard und der Bestätigungs-Dialog sind UI-/Orchestrierungs-Logik in `main.py`/`ui.py`; manueller Verify-Pfad (kein Unit-Test) in der Übergabe dokumentieren.

## Bewusst weggelassen (YAGNI)

- **Automatisches GC, Geräte-Registry, Heartbeat, Cutoff, Self-Heal-Auto-Advance** — durch die manuelle Auslösung ersetzt (Kern dieser Design-Entscheidung).
- **Hard-Block gegen Alt-Geräte / ETag-Push-Schutz** — pre-existing Sync-Verhalten (Push-Clobber, Drive v3 ohne wirksamen ETag), nicht Teil dieser Spec.
- **Auto-Kompaktierung nach Zeitplan / Schwellwert** — kann später ergänzt werden, falls je ein zu großes File berichtet wird.
