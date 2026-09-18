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

**Möglicher Fix (später, im Rahmen von PR margenheld/Zeiterfassung#60):** Den
Pull nicht pausieren, wenn das pre-v3-Remote-Doc ausschließlich Einträge des
**eigenen** `device_id` enthält (= eigenes Alt-Doc, kein fremdes aktives Gerät)
— dann still nach v3 migrieren/pushen. Alternativ die Meldung so
umformulieren, dass sie den Einzelgerät-Fall mit abdeckt. Der Guard für echte
Multi-Device-Fälle bleibt unangetastet.

## Windows: Aufblitzen der hellen Titelleiste — behoben, mit Rest

Dialoge blitzten beim Öffnen kurz mit heller Titelleiste auf (gemessen
~56 ms), weil `apply_dark_titlebar` die Umfärbung per `window.after(100, …)`
aufschob, der Dialog aber schon vorher sichtbar war.

**Behoben:** Dialoge werden seit [Xveyn#34] verborgen aufgebaut
(`create_dialog` → `withdraw`) und erst von `center_dialog_on_parent`
sichtbar gemacht, wenn die Titelleiste bereits dunkel ist. Begründung und
die daran hängende Paarungs-Regel: [`CLAUDE.md`](../CLAUDE.md), Abschnitt
„Dialog-Styling".

**Was bleibt:** das **Hauptfenster**. Es ist von Anfang an sichtbar und hat
die Klammer aus `create_dialog`/`center_dialog_on_parent` nicht — beim Start
und beim Wiederherstellen aus dem Tray kann die Titelleiste weiterhin kurz
hell erscheinen. Derselbe Trick ginge dort nicht ohne Weiteres: ein
verborgen gestartetes Hauptfenster müsste sein `deiconify` mit dem
Tray-/`--minimized`-Pfad abstimmen.

**Sackgasse, die man nicht zweimal gehen muss:** das Fenster stattdessen per
`-alpha 0.0` unsichtbar zu halten. Ein Toplevel, das `-alpha` **vor** dem
`geometry()`-Aufruf bekommt, ignoriert die Positionierung dauerhaft (direkt
nach der Erzeugung: `+0+0`; nach einem ersten `update_idletasks`: ein
anderer falscher Offset). Auf Tk 8.6.15 reproduziert.

[Xveyn#34]: https://github.com/Xveyn/Zeiterfassung/issues/34

## Tests: die Tk-/UI-Schicht ist bewusst nicht automatisiert getestet

Getestet wird **Logik, nicht UI**. Dialog-Aufbau, Grid-Rendering und
Event-Bindings (auch das Rechtsklick-Löschmodell) haben keine automatisierten
Tests — weder headless-simuliert noch per `xvfb` mit echtem Tk.

**Warum:** Der Nutzen trägt die Kosten nicht. Widget-Tests sind die brüchigste
Testsorte — sie brechen bei Layout-Umbauten, ohne dass ein Verhalten kaputt
wäre, und erzeugen damit genau die Sorte Rot, die man wegklickt statt liest.
Dazu käme dauerhaft ein `xvfb`-Pfad in der CI, den sonst nichts braucht. Und
das, was wirklich nur auf der echten Plattform bricht — macOS-Sekundärklick
(`<Button-2>`/Control-Klick, ✕-Delete-Gate), Fenster-Chrome und die Darstellung
des Linux-Trays in Plasma (margenheld/Zeiterfassung#42) — deckt ein
Linux-Framebuffer strukturell ohnehin nicht ab. Beim Linux-Tray zeigt sich
dabei genau der Zuschnitt-Gedanke: die dbusmenu-Logik liegt D-Bus-frei in
`tray.linux.MenuState` und wird überall getestet, die Wire-Ebene gegen einen
echten `dbus-daemon` — offen bleibt nur, was Plasma daraus zeichnet.

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

**Herkunft:** Audit-Finding **M16** (margenheld/Zeiterfassung#131) stellte die
Grundsatzfrage („schließen oder als akzeptierte Lücke dokumentieren"),
**margenheld/Zeiterfassung#148** schlug den engen `xvfb`-Ausschnitt vor. Beide
sind mit dieser Entscheidung geschlossen — sie ist damit getroffen, nicht
vertagt. Ältere Specs, die „Audit M16 offen" schreiben, sind an dieser Stelle
überholt.

## Linux: Reste nach dem Löschen der AppImage

Löscht der Nutzer die AppImage, bleiben Menüeintrag und Autostart-Datei
zurück und zeigen ins Leere. Die App kann nicht aufräumen, wenn sie nicht
mehr startet, und das AppImage-Format kennt keinen Deinstallations-Hook.
Gilt gleichermaßen für die zurückbleibenden Nutzerdaten inkl. `token.json`
und `webhooks.json` — das ist plattformübergreifend erfasst in
[margenheld/Zeiterfassung#183](https://github.com/margenheld/Zeiterfassung/issues/183).

Der Autostart heilt außerdem erst, **nachdem** die neue AppImage einmal
gestartet wurde. Wer die neue Version herunterlädt und nie öffnet, startet
weiter die alte — ohne Hinweis.

Ist zusätzlich `appimaged` oder AppImageLauncher installiert, schreibt eines
dieser Tools beim ersten Start einen eigenen Menüeintrag
(`appimagekit_<hash>-Zeiterfassung.desktop`) neben unserem eigenen. Ergebnis:
zwei Einträge im Anwendungsmenü für dieselbe AppImage. Kein Datenverlust, rein
kosmetisch — die App schreibt ihren eigenen Eintrag unabhängig davon, weil sie
ohne eines dieser Tools sonst gar keinen bekäme.

## Webhooks: Split-Horizon-DNS gilt als öffentliche Adresse

Der Webhook-Versand erlaubt unverschlüsseltes `http://` nur für Adressen im
lokalen Netz: private IP-Literale (Loopback, RFC 1918, CGNAT, Link-Local,
IPv6-ULA), den Hostnamen `localhost` selbst (eigener Sonderfall, geprüft
**vor** der Suffix- und IP-Prüfung), die Suffixe
`.local`/`.lan`/`.home.arpa`/`.internal`/`.localhost` sowie sonstige
Single-Label-Namen. Für alles andere ist `https://` Pflicht — sonst gingen
Arbeitszeiten und, je nach Konfiguration, ein Bearer-Token im Klartext durchs
Netz.

Entschieden wird **allein an der Adresse in der URL**, ohne DNS-Auflösung.
Ein öffentlicher Name, der per Split-Horizon-DNS intern auf eine private
Adresse zeigt (`erp.firma.de` → `10.0.0.5`), gilt deshalb als öffentlich und
verlangt https, obwohl der Verkehr das lokale Netz nie verlässt.

**Warum nicht auflösen:** ein DNS-Lookup beim Speichern wäre langsam, offline
unmöglich und könnte später still anders ausgehen, ohne dass die App es
bemerkt — die Adresse wäre dann nach der einmaligen Prüfung dauerhaft als
„privat" eingestuft, auch wenn sie längst nach außen zeigt.

**Umgehung:** die interne Adresse direkt eintragen (`http://10.0.0.5/hook`).

Design: [`superpowers/specs/2026-08-26-webhook-versand-design.md`](superpowers/specs/2026-08-26-webhook-versand-design.md)

## Webhooks: urllib normalisiert die Schreibweise der Header-Namen

`urllib.request.Request.add_header` wendet `key.capitalize()` an,
`AbstractHTTPHandler.do_open` anschließend `name.title()`. Ein als
`X-API-Key` konfigurierter Header geht damit als `X-Api-Key` über die
Leitung.

HTTP-Header sind laut RFC case-insensitiv, das ist also regelkonform.
Empfänger, die den Namen per exaktem String-Vergleich prüfen (etwa
handgeschriebener Code in n8n oder Make), finden ihn trotzdem nicht.

**Bewusst nicht umgangen:** Die Schreibweise zu erhalten hieße, an urllibs
Header-Pfad vorbeizuschreiben — Eigenbau an einer Stelle, die sonst
zuverlässig funktioniert. **Umgehung:** beim Empfänger case-insensitiv
vergleichen, oder einen Header-Namen wählen, den `title()` unverändert
lässt (`X-Api-Key`, `Authorization`, `X-Hub-Signature-256`).

## SMTP: keine Microsoft-Konten

Der SMTP-Versand meldet sich mit Benutzer und Passwort an. Microsoft hat das
für Outlook.com und Microsoft 365 2026 abgeschaltet (Ablehnung ab März,
endgültig zum 30.04.2026) — auch App-Passwörter greifen dort nicht mehr, SMTP
läuft nur noch über OAuth2. Ein Microsoft-Postfach lässt sich deshalb nicht
als SMTP-Konto einrichten; wer eines nutzen will, geht über die Gmail-API
oder einen anderen Anbieter.

Ein eigener OAuth2-Flow für SMTP (XOAUTH2) würde das lösen, wäre aber ein
zweiter vollständiger Auth-Flow neben dem bestehenden — bewusst nicht gebaut.

## SMTP-Konten sind gerätelokal

Wie Webhooks und Urlaub reisen SMTP-Konten nicht per Drive-Sync: sie enthalten
Zugangsdaten, und die haben im Sync-Doc nichts verloren. Auf einem zweiten
Gerät müssen die Konten deshalb neu eingerichtet werden.

## Schlüsselbund (#101): bekannte Grenzen

Seit #101 liegen der OAuth-Refresh-Token und Webhook-Secrets (und, seit dem
SMTP-Feature, das SMTP-Passwort) im OS-Schlüsselbund statt im Klartext im
Datenordner, mit Datei-Fallback ohne verfügbaren Schlüsselbund. Daraus ergeben
sich sieben bekannte Grenzen.

### macOS fragt nach jedem App-Update erneut nach dem Schlüsselbund

Auf macOS hängt die Zugriffsberechtigung eines Keychain-Eintrags am
*Designated Requirement* des zugreifenden Programms. PyInstaller signiert die
`.app` per Default ad-hoc, und dabei ist dieses Requirement der `cdhash` —
der sich mit **jedem** Build ändert. „Immer erlauben" gilt deshalb nur für
genau den Build, für den es geklickt wurde; nach einem Update fragt macOS
erneut. Das ließe sich nur mit einer echten Developer-ID-Signatur beheben.

Zusätzlich schreibt `keyring` ein geändertes Passwort als Löschen-und-neu-
Anlegen statt als Update und verwirft dabei die Berechtigung — auch ohne
Update erscheint der Dialog also nach jeder Passwortänderung einmal wieder.

Der Zugriff läuft hinter einem 30-Sekunden-Watchdog (`keyring_store.py`) —
genug, um den Dialog in Ruhe zu lesen und das Anmeldepasswort zu tippen. Wer
innerhalb dieser Zeit bestätigt, sendet normal weiter; wer ihn abbricht,
bekommt eine Fehlermeldung statt eines stillen Fehlschlags. Antwortet der
Schlüsselbund auch nach 30 Sekunden nicht — der Dialog blieb unbeantwortet,
oder der Prompt kam aus einem anderen Grund gar nicht erst —, meldet die App
das ausdrücklich als „Passwort konnte nicht aus dem Schlüsselbund gelesen
werden" statt sich mit einem leeren Passwort anzumelden: eine leere Anmeldung
würde der Server mit „Zugangsdaten abgelehnt" quittieren, und der Nutzer
suchte das Problem beim Passwort statt beim Schlüsselbund.

### Downgrade: eine ältere Version liest den Refresh-Token nicht

Eine ältere App-Version kennt das Schlüsselbund-Format von `token.json` nicht
und übergibt sie ohne `refresh_token` an google-auth — die Bibliothek bricht
dann mit `ValueError: … missing fields refresh_token` ab. Abhilfe: einmal
Einstellungen → Google → „Google neu verbinden", das schreibt `token.json`
wieder im Format der installierten Version. Gleiches gilt für Webhooks mit
aktivierter Authentifizierung: eine ältere Version sendet dort ohne Wert im
Header bzw. signiert mit leerem HMAC-Secret, statt den Schlüsselbund zu lesen.

### Datenordner auf einen anderen Rechner kopiert

Der Schlüsselbund-Eintrag bleibt auf dem Ursprungsrechner — eine kopierte
`token.json`/`webhooks.json` trägt auf dem neuen Rechner nur noch den
Schlüssel, nicht das Secret. Google muss dort neu verbunden, Webhook-Secrets
müssen neu eingegeben werden.

### Windows-Größenlimit

Der Windows Credential Manager fasst höchstens 1280 Zeichen (UTF-16) pro
Eintrag. Google-Access-Tokens reservieren bis zu 2048 Byte — deshalb liegt nur
der Refresh-Token im Schlüsselbund, `token.json` behält Access-Token, Scopes,
Client und Ablauf unverändert als Datei (s. `src/CLAUDE.md`, Abschnitt
„Google-Integration").

### Extern gelöschter Eintrag fällt erst beim nächsten Start auf

`keyring_store` cacht geschriebene Werte pro Prozess und schreibt nur bei
Änderung neu (s. „macOS fragt nach jedem App-Update erneut" oben für den
Grund). Wird ein Eintrag außerhalb der App entfernt — von Hand in der
Anmeldeinformationsverwaltung/Schlüsselbundverwaltung —, merkt das laufende
App-Fenster das nicht sofort; erst der nächste Start liest den Schlüsselbund
wieder direkt und erkennt das Fehlen.

### Klartext-Reste außerhalb des Umzugs

Zwei Dateiarten können trotz Schlüsselbund kurzzeitig Klartext-Secrets
enthalten, ohne dass das ein Bug ist:

- Eine korrupte `webhooks.json` wird nach `webhooks.json.corrupt-<stamp>`
  quarantäniert statt stillschweigend verworfen (N4) — auch während
  `--forget-secrets` beim Deinstallieren. Diese Quarantäne-Datei kann ein
  Secret aus dem Alt-Format enthalten und bleibt danach im Datenordner
  liegen, bis sie von Hand gelöscht wird.
- Nach einem harten Prozessabbruch (Absturz, Kill) mitten im Schreiben von
  `token.json` kann eine Temp-Datei `.token-*.tmp` im Datenordner
  zurückbleiben (`oauth_utils.write_token_json`, vor dem atomaren
  `os.replace`). Sie ist harmlos für den nächsten Start, aber ebenfalls von
  Hand zu entfernen.

### Deinstallation wartet auf den Schlüsselbund

Der Windows-Uninstaller ruft `Zeiterfassung.exe --forget-secrets` und wartet
auf dessen Ende (`ewWaitUntilTerminated`), bevor er die Dateien löscht — aus
ihnen stammen die Schlüssel. Antwortet der Schlüsselbund nicht, greift pro
Eintrag der 30-Sekunden-Watchdog, und die Zeiten summieren sich (Token, jeder
Webhook, jedes SMTP-Konto im Schlüsselbund) — die Deinstallation steht dann
entsprechend lange ohne sichtbaren Fortschritt.
Sie läuft danach normal weiter, die betroffenen Einträge bleiben stehen.

### macOS/Linux haben keinen Uninstaller

`--forget-secrets` räumt der Windows-Uninstaller auf; macOS (`.app` in
`/Applications`) und Linux (AppImage) kennen keinen Deinstallations-Hook, der
das automatisch auslösen könnte (s. „Linux: Reste nach dem Löschen der
AppImage" oben). Wer die Schlüsselbund-Einträge dort von Hand entfernen will,
findet sie unter dem Service-Präfix `Zeiterfassung:` in der
„Schlüsselbundverwaltung" (macOS) bzw. „Passwörter und Schlüssel" (Linux,
GNOME Keyring/Seahorse — abhängig vom installierten Secret-Service-Backend).

## macOS: kein Selbst-Update

Windows und Linux laden ein Update in der App, prüfen es gegen die
Prüfsummen des Releases und installieren es (Details: `CLAUDE.md`, Abschnitt
„Update-Weg"). Auf macOS bleibt der Knopf beim heutigen Verhalten — er öffnet
den Download im Browser.

**Gründe:**

- **Das Bundle ist weder signiert noch notarisiert** — `scripts/build.py`
  enthält kein `codesign`. Ein Selbst-Update müsste das DMG mounten, nach
  `/Applications` schreiben und dabei mit Gatekeeper umgehen.
- **Nicht verifizierbar auf der Windows-Entwicklungsmaschine.** Die
  CLAUDE.md-Regel „Plattformspezifische PRs — Pre-Release vorschlagen" trägt
  hier allein nicht weit genug: ein Selbst-Updater ist genau die Fehlerklasse,
  die sich nicht per Update reparieren lässt, wenn sie einmal ausgeliefert ist.
- **CI baut nur arm64** — kein Intel-Artefakt zum Testen oder Ausliefern.

**Warum das später trotzdem lohnt:** Ausgerechnet macOS hätte den größten
Gewinn. Der heutige Browser-Download setzt beim Speichern der Datei das
Attribut `com.apple.quarantine`, und genau daran hängt die Gatekeeper-Warnung,
die Nutzer per Rechtsklick → Öffnen wegklicken müssen. Ein Download per
`urllib`, wie ihn Windows und Linux verwenden, setzt dieses Attribut **nicht**
— das erledigt LaunchServices beim Sichern aus dem Browser, nicht der
Netzwerk-Socket. Ein Selbst-Update auf dem Mac würde die Gatekeeper-Hürde
also nicht umgehen müssen, sondern schlicht nie auslösen. Das ist der
eigentliche Grund, die Lücke später zu schließen — nicht bloß Komfort auf
Augenhöhe mit den anderen beiden Plattformen.
