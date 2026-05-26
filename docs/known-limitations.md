# Known Limitations

Persistente, bewusst (noch) nicht umgesetzte Limitierungen. Wird ergänzt, wenn neue dazukommen.

## Sync: Keine Tombstone-Garbage-Collection

Mit dem Multi-Device-Sync-Feature (Design: [`superpowers/specs/2026-05-14-multi-device-sync-design.md`](superpowers/specs/2026-05-14-multi-device-sync-design.md)) führen wir zwei Arten von Tombstones ein:

- **Eintrags-Tombstones:** Gelöschte Tageseinträge bleiben als `{"deleted": true, "modified_at": ...}` im Sync-File, damit ein Delete sich gegen ein veraltetes Save eines anderen Geräts durchsetzt (Last-Write-Wins).
- **Konflikt-Tombstones:** Aufgelöste Konflikte (`resolved: true`) bleiben in der `conflicts`-Liste, damit andere Geräte die Resolution propagieren bzw. nicht versehentlich denselben Konflikt erneut anlegen.

Beide wachsen **unbeschränkt** — es gibt keine Garbage-Collection-Logik.

**Praktische Auswirkung:** Bei normalem Gebrauch (gelegentliche Löschungen, wenige Konflikte) ist das viele Jahre unproblematisch — Größenordnung Kilobyte pro Jahr. Die Sync-Datei wird aber nie kleiner.

**Wann es relevant wird:**

- Wenn ein User aus Versehen Hunderte Einträge anlegt und löscht
- Wenn der Sync-File irgendwann spürbar groß wird (z. B. > 1 MB)
- Wenn aus Performance- oder Datenschutzgründen ein Aufräum-Mechanismus gewünscht ist

**Mögliche zukünftige Lösung:** GC-Schritt beim Pull, der Tombstones älter als z. B. 90 Tage entfernt — vorausgesetzt, alle Geräte haben seitdem mindestens einmal synchronisiert. Erfordert einen `last_seen_at`-Heartbeat pro Device im Sync-Meta, damit man weiß, ob ein Tombstone sicher entfernt werden kann.

Für die erste Iteration: bewusst weggelassen (YAGNI). Wenn Reports auftauchen, dass das Sync-File zu groß wird, in einem Folge-PR adressieren.
