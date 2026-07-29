# Tray: „Nach Updates suchen" mit Ergebnis-Toast

**Datum:** 2026-07-27
**Status:** entworfen, freigegeben

## Problem

Der Update-Check läuft heute nur automatisch im Hintergrund (`BackgroundTaskRunner.check_update`,
gedrosselt über `update_check_frequency`, Default 1×/Kalendertag) oder manuell über
Einstellungen → Updates → „Jetzt prüfen". Beides setzt ein **sichtbares Fenster** voraus.

Wer die App per Minimize-to-Tray dauerhaft im Infobereich laufen lässt, muss das Fenster
also erst zurückholen und einen Dialog öffnen, nur um zu fragen: gibt es was Neues? Das
Tray-Menü kann das direkt beantworten — es hat mit dem Toast bereits den Kanal dafür.

## Lösung

Ein Menüeintrag **„Nach Updates suchen"** im Tray-Menü, dessen Ergebnis als Toast kommt.

### Menü

Der Eintrag kommt als weiteres Tupel in die `actions`-Liste in `ui.py::_apply_tray_setting`,
unterhalb von „Mit Google Drive synchronisieren", `visible=None` (immer sichtbar):

```
Anzeigen
────────────────
Arbeitszeiten senden
Teilen
Export
Mit Google Drive synchronisieren   (nur bei aktivem Sync)
Nach Updates suchen                 ← neu
────────────────
Beenden
```

Beide Backends rendern dieselbe Liste — Windows über die pystray-Schleife in
`_PystrayBackend.start`, macOS über `tray.build_menu_model`. Es entsteht **kein neuer
Plattformzweig**; der Unterschied „pystray wertet `visible` live aus, NSStatusItem nur
beim Aufbau" ist hier bedeutungslos, weil der Eintrag statisch sichtbar ist. Linux hat
kein Tray (`tray.is_supported`), dort existiert das Menü nicht.

### Ablauf

Klick → `root.after(0, self._tray_check_update)` (Muster aller Tray-Aktionen: der Callback
läuft im Backend-Thread und marshallt selbst auf den Tk-Thread) → `self._bg.run(fn, on_done)`
mit dem bestehenden Thread-Helfer. Der Worker ruft `updater.check_for_update(REPO,
include_prereleases)`, `on_done` läuft im UI-Thread und schickt den Text an
`self._tray.notify(...)`.

Ein laufender Check blockt den zweiten Klick über ein Instanz-Flag: ein Doppelklick soll
nicht zwei HTTP-Requests und zwei Toasts auslösen. Das Flag wird im `on_done` wieder
freigegeben — auch im Fehlerfall.

### Toast-Texte

Neue **Tk-freie** Funktion `updater.manual_check_toast_text(installed_id, release)`, gestützt
auf das vorhandene `resolve_check_result` (Single Source of Truth für die Fallunterscheidung):

| Fall | Toast |
|---|---|
| `release is None` (kein Netz, API-Fehler) | „Prüfung fehlgeschlagen — keine Verbindung?" |
| nicht neuer | „Du hast die aktuelle Version (`<installed_id>`)." |
| neuer | `update_toast_text(release)` — „Version X verfügbar — Details unter Einstellungen → Updates." |

Der manuelle Check meldet sich **in allen drei Fällen**. Das ist der bewusste Unterschied
zum Hintergrund-Check, der bei „alles aktuell" schweigt: hier hat der Nutzer aktiv gefragt,
und bei verstecktem Fenster ist der Toast die einzige Antwortmöglichkeit — ohne ihn wirkt
der Menüpunkt kaputt.

### Nebenwirkungen auf die Settings

- `last_update_check_at` wird gesetzt, **wenn die Abfrage geklappt hat** (es *war* dann eine
  Prüfung — so läuft der Hintergrund-Check nicht kurz darauf ein zweites Mal). Nach einem
  Fehlversuch bleibt der Wert stehen: eine gescheiterte Prüfung darf nicht als „heute schon
  geprüft" gelten, sonst schwiege auch der Hintergrund-Check den Rest des Tages.
- `update_toast_shown_version` wird gesetzt, **wenn** eine neuere Version gefunden wurde:
  der Nutzer hat die Meldung gesehen, der Hintergrund-Check soll dieselbe Version nicht
  erneut toasten (`_route_update_notification` vergleicht genau diesen Wert).
- Der Frequenz-Throttle (`updater.should_check`) wird **übergangen**: manuell heißt manuell.
- `prerelease_updates_enabled` wird respektiert — derselbe Kanal wie beim Hintergrund-Check.

### Bewusst nicht enthalten

- **Kein Banner, kein Fenster-Pop.** Der Toast verweist auf Einstellungen → Updates, wie der
  Hintergrund-Toast auch. Das Fenster ungefragt nach vorn zu reißen, während der Nutzer
  woanders arbeitet, wäre aufdringlicher als der Nutzen rechtfertigt.
- **Kein Klick-Handler auf dem Toast.** Toast-Aktivierung ist plattformabhängig und in
  pystray nicht sauber verdrahtbar; der Verweis im Text genügt.
- **Keine neue Einstellung.** Der Eintrag ist immer da, wenn es ein Tray gibt.

## Tests

**`tests/test_updater.py`** — `manual_check_toast_text` für die drei Fälle (pure, ohne Tk
und ohne Netz).

**`tests/test_ui_update_routing.py`** — die Verdrahtung:
- Der Eintrag steckt in den Tray-Actions.
- Klick löst genau einen Worker aus; das Ergebnis landet als `notify`-Text.
- Zweiter Klick während laufender Prüfung startet nichts.
- Nach Abschluss ist wieder ein Check möglich (Flag freigegeben, auch bei Fehler).
- `last_update_check_at` wird gesetzt; `update_toast_shown_version` nur bei gefundenem Update.

## Plattform-Anmerkung

Der Code ist plattformneutral (eine gemeinsame `actions`-Liste, kein `platform.system()`-Zweig),
daher greift die „Pre-Release vor dem Merge"-Empfehlung aus `CLAUDE.md` hier nicht zwingend.
Auf macOS ist das Tray ohnehin dormant (Opt-in `ZEIT_MACOS_TRAY=1`, #88) — der Eintrag wird
dort erst mit dem Mac-Gate sichtbar und ist über `build_menu_model` mit abgedeckt.
