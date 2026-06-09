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
