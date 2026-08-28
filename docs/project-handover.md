# Projekt-Übernahme — Fork-Promotion nach `Xveyn/Zeiterfassung`

> [!NOTE]
> **Der Umzug ist am 2026-08-26 vollzogen.** `Xveyn/Zeiterfassung` ist das
> kanonische Repository (`fork: false`, kein `parent`), trägt alle 48 Tags, und
> das Brücken-Release `v1.21.0` liegt in **beiden** Repos.
> `margenheld/Zeiterfassung` ist Archiv — dort erscheint kein Release mehr.
>
> Dieses Dokument bleibt als **Protokoll** stehen: die Begründungen erklären
> weiterhin, warum Dinge so sind, wie sie sind (Lizenz-Zeile, `AppId`,
> `com.margenheld.*`, das dauerhaft belegte alte Repo). Abgehakt ist, was
> nachprüfbar erledigt ist; die offenen Kreuze unten sind **echte Restarbeit**.
>
> Die drei Repo-Settings, die den Release-Prozess hier trugen, sind am
> 2026-08-28 nachgezogen: die `release:*`-Labels angelegt, Actions →
> Workflow permissions auf **Read and write**, und `master` ist protected
> (Abschnitt 4). Damit ist der Release-Weg im neuen Repo erstmals vollständig.
>
> Zustand geprüft am 2026-08-28.

Checkliste für den Umzug des Projekts weg von der **MargenHeld GmbH**.

**Entschieden:** `Xveyn/Zeiterfassung` (bisher Fork) wird das neue Zuhause,
`margenheld/Zeiterfassung` bleibt als Archiv stehen. Die Alternative — ein
GitHub-Repo-Transfer — wurde verworfen: sie bräuchte die aktive Mitwirkung der
GmbH i. L. **vor** ihrer Löschung im Handelsregister und wäre damit vom Timing
der Liquidation abhängig. Die Fork-Promotion ist jederzeit einseitig
durchführbar.

Lizenz ist MIT und bleibt MIT.

> Kein Rechtsrat. Die juristischen Punkte gehören einmal anwaltlich
> gegengelesen.

---

## Was der Weg kostet

Nichts davon ist ein Hindernis, aber alles davon will bewusst entschieden sein:

| | Folge |
|---|---|
| Issues/PRs inkl. Nummern | bleiben im alten Repo; `#NNN`-Referenzen müssen qualifiziert werden (Abschnitt 4) |
| Releases + Assets + Download-Zähler | alte bleiben im alten Repo, neue entstehen ab dem Fork |
| Alte URLs | redirecten **nicht** |
| Auto-Updater bei Bestandsinstallationen | **Brücken-Release im alten Repo zwingend** (Abschnitt 3) |
| Branch Protection / Actions-Settings | im Fork neu einrichten |
| Fork-Badge / PR-Default-Target | Support-Anfrage „detach fork" nötig |
| Stars / Watcher | weg |

---

## 1. Lizenz

- [x] **`LICENSE`: `Copyright (c) 2026 MargenHeld GmbH` bleibt stehen.**
      MIT verlangt das ausdrücklich („shall be included in all copies").
      Eine eigene Zeile für die eigenen Beiträge *ergänzen* ist zulässig, die
      bestehende ersetzen nicht.

Dass ein Fork die Rolle des kanonischen Projekts übernimmt, ist exakt der von
MIT vorgesehene Fall — die Lizenz gewährt `use, copy, modify, merge, publish,
distribute, sublicense, and/or sell`. Es braucht dafür **keine** Vereinbarung
mit der GmbH und keine Rechteübertragung.

Man wird dadurch nicht Rechteinhaber am Altbestand: in DE ist das Urheberrecht
selbst nicht übertragbar, übertragen würden ausschließliche Nutzungsrechte —
und die bräuchten den Weg über die GmbH, den wir gerade nicht gehen. Praktisch
fast folgenlos, weil MIT `sublicense` erlaubt. Was nicht geht: die bereits
erteilte MIT-Lizenz für den Altbestand zurücknehmen.

---

## 2. Firmenauflösung: was praktisch verschwindet

Der am ehesten übersehene Teil. **Alles davon vor der Abschaltung erledigen** —
ohne Zugang zum alten Repo ist das Brücken-Release aus Abschnitt 3 unmöglich,
und damit der ganze Umzug.

- [ ] **GitHub-Account/Org `margenheld`:** Hängen Login oder Recovery-Adresse an
      einem Firmenpostfach? Mit dessen Abschaltung ist der Zugang weg.
- [ ] **Domain `margen-held.de`:** trug die Security-Meldeadresse — aus
      `SECURITY.md` inzwischen **ersatzlos entfernt**, Meldungen laufen nur noch
      über die GitHub Security Advisories des neuen Repos. Offen bleibt der
      organisatorische Teil:
      (`SECURITY.md:24`, `sven@margen-held.de`). Läuft die Domain aus und
      registriert sie jemand neu, empfängt dieser Passwort-Resets für jeden
      Account, der noch auf sie zeigt. → GitHub-Account auf eine private
      Adresse umstellen, 2FA-Recovery-Codes sichern.
- [ ] **Dauerauflage — alten Repo-Namen `margenheld/Zeiterfassung` belegt lassen** —
      siehe das Squatting-Risiko in Abschnitt 3.
- [x] `com.margenheld.zeiterfassung` verweist per Reverse-DNS-Konvention auf
      eine Domain, die künftig nicht mehr uns gehört. Technisch folgenlos →
      **nicht jetzt anfassen**, sondern beim nächsten ohnehin breaking
      macOS-Change mitziehen (Begründung in Abschnitt 6).

**Google Cloud: nichts zu tun.** Laut README legt jeder Nutzer sein eigenes
Cloud-Projekt und seine eigene `credentials.json` an. Es gibt keinen zentralen
OAuth-Client und keinen Verifizierungsstatus — also auch kein Risiko, dass
Bestandsnutzer beim Owner-Wechsel den Zugriff auf ihre `appDataFolder`-Sync-Daten
verlieren.

---

## 3. Die Update-Brücke

**Grundlage:** Die App aktualisiert sich **nie selbst**. `update_banner._open_download`
und `tab_updates._open_download` machen beide nur `webbrowser.open(url)` — auf
die Asset-URL, ersatzweise auf `release.html_url`; installiert wird manuell
(vgl. Kommentar in `src/autostart.py:228`). Der Updater ist also ein reiner
**Melder**. Das heißt: die Migration kann nicht stillschweigend passieren, aber
sie ist technisch simpel — es muss nur die *Meldung* beim Nutzer ankommen.

- [x] **Schritt 1 — Brücken-Release im ALTEN Repo: `1.21.0`.** *(erledigt: `margenheld/Zeiterfassung` `v1.21.0`, 4 Assets, 2026-08-26.)* Gebaut und
      veröffentlicht wird es noch hier, die Assets liegen also im alten Repo.
      Es trägt zwei Dinge zugleich: die seit `1.20.0` aufgelaufenen Features
      (u.a. den Webhook-Versand) **und** die Umstellung von `updater.REPO` auf
      `Xveyn/Zeiterfassung`. Regulärer Prozess: `src/version.py` auf `1.21.0`,
      CHANGELOG-Eintrag mit eigenem Absatz zum Umzug, `release:minor`-Label,
      mergen.

      **Entschieden: die Brücke fährt mit, statt ein eigenes Patch-Release zu
      bekommen.** Ein separates Release wäre sauberer trennbar, kostet aber
      einen zweiten Durchlauf durch den ganzen Prozess (drei Plattform-Builds,
      Tag, Assets) für eine einzige geänderte Konstante — und die Nutzer
      müssten zweimal aktualisieren, statt einmal. Der Umzug bleibt trotzdem
      sichtbar: er steht im CHANGELOG, in den Release-Notes und im
      README-Banner.
- [ ] **Schritt 2 — verteilen lassen.** *(läuft — nichts zu tun; endet erst, wenn niemand mehr auf einer Version < 1.21.0 sitzt.)* Nutzer sehen die Meldung im
      Updates-Tab/Banner, laden aus dem alten Repo, installieren. Ab dann fragt
      ihre App das neue Repo.
- [ ] **Schritt 3 — alle weiteren Releases im neuen Repo**, mit **höherer**
      Versionsnummer als die Brücke — sonst greift `is_newer` nicht und die
      Nutzer bekommen nie wieder ein Update angeboten.

**Nachzügler:** Wer die Brücke nie installiert, hängt dauerhaft am alten Repo.
Daher:

- [ ] **Dauerauflage —** altes Repo **nicht löschen, nicht umbenennen**, Brücken-Release stehen
      lassen. Der README-Banner dazu liegt bereits im Fork-Promotion-PR; die
      **Repo-Description** in den GitHub-Settings ist separat nachzuziehen (sie
      steht in keiner Datei).
- [x] **Banner im neuen Repo** — aus der Gegenrichtung formuliert: dass das
      Projekt bis `1.21.0` unter `margenheld/Zeiterfassung` lag und hier
      fortgeführt wird, mit Verweis auf die dortigen Alt-Releases und die
      Issue-Historie. Anders als der Banner im alten Repo darf dieser später
      wieder verschwinden — der alte muss dauerhaft stehen bleiben, er ist die
      Landekarte für alte Links.
- [ ] **Archivieren erst ganz am Ende** — ein archiviertes Repo ist read-only,
      danach lässt sich dort kein weiteres Hinweis-Release mehr nachschieben.
- [x] Erwartungsmanagement: `should_check` throttelt den Update-Check (Default
      1×/Tag). Wer die App wochenlang nicht öffnet, sieht die Meldung
      entsprechend später. Kein Handlungsbedarf.

**Squatting-Risiko:** Ohne Redirect fragen nicht migrierte Installationen
dauerhaft `MargenHeld/Zeiterfassung` ab. Wird der Name freigegeben und von
Dritten neu belegt, bekommen diese Nutzer fremde Assets zum Download angeboten.
Der alte Name muss dauerhaft belegt bleiben.

---

## 4. Fork-spezifische GitHub-Arbeit

- [x] **Tags nachgezogen.** Stand 2026-08-28: `Xveyn` hat **48** Tags,
      `margenheld` **47** — der neue Ort ist vollständig. Historischer Stand
      2026-08-26: beide Seiten hatten **46 Tags**, aber
      nicht dieselben — dem Fork fehlt `v1.20.0-pre.2`, upstream fehlt
      `v1.17.0-pre.1`. `git push origin --tags` schließt die Lücke im Fork.
      Ohne die Tags scheitern zwei Dinge: (a) `src/changelog.py:15` lädt
      `raw.githubusercontent.com/{repo}/v{version}/CHANGELOG.md` und findet für
      ältere Versionen nichts mehr; (b) das `pre-check`-Gate in `release.yml`
      verlangt für einen Pre-Release, dass `v<VERSION>` bereits existiert.
      **Vor jedem Umzugsschritt neu zählen** — die Zahl veraltet mit jedem
      Release.
- [x] **Zur Kenntnis — GitHub-Releases werden nicht mitgeforkt.** Ein Fork enthält die
      Git-Historie, aber keine Release-Objekte und keine Assets. Alte
      Download-Links zeigen weiterhin ins alte Repo — funktioniert, solange es
      steht (siehe Abschnitt 3).
- [x] **Fork-Beziehung gelöst** (`fork: false`, kein `parent` — geprüft
      2026-08-28). Der lokale `upstream`-Remote wurde am selben Tag entfernt,
      `master` trackt `origin`. Historische Begründung: bis dahin zielten
      neue PRs per Default auf das Upstream → Gefahr, versehentlich ins alte
      Repo zu mergen. Übergangsweise immer das Base-Repo prüfen bzw.
      `gh pr create --repo Xveyn/Zeiterfassung` verwenden.
- [x] **Issue-Nummern-Falle entschärft:** In `CLAUDE.md`, `src/CLAUDE.md` und
      `docs/known-limitations.md` steht keine bloße `#NNN` mehr — alle Referenzen
      sind vollqualifiziert und zeigen damit korrekt ins Archiv. **Offen ist nur
      die Anschlußfrage,** ob sie stattdessen auf die am 2026-08-26 ins neue Repo
      kopierten Issues zeigen sollen (Mapping alt→neu, z. B. `#42→#8`,
      `#131→#40`, `#183→#50`). Ursprünglicher Wortlaut: Alle
      `#NNN`-Referenzen in `CLAUDE.md`,
      `docs/known-limitations.md` und `AUDIT-2026-07-04.md` (#42, #96, #99,
      #118, #131, #148, #183 …) meinen das alte Repo. Im neuen Repo verlinkt
      GitHub `#42` auf dessen *eigenes* Issue 42 — semantisch falsch, sobald
      dort Issues entstehen. Gegenmaßnahme: bloße `#NNN` durch vollqualifizierte
      `margenheld/Zeiterfassung#42` ersetzen.
- [x] **Branch Protection eingerichtet** (2026-08-28). `master` war bis dahin
      **nicht** protected (`HTTP 404 Branch not protected`), obwohl `CLAUDE.md`
      sie als gegeben beschreibt. Gesetzt sind jetzt die Required Checks
      `test`, `lint`, `typecheck`, `test-macos`, `test-windows` — ohne `strict`
      (ein PR muss nicht auf den aktuellen `master` nachgezogen werden),
      ohne Review-Pflicht (Solo-Maintainer kann den eigenen PR nicht
      approven), `enforce_admins: false` für den in `CLAUDE.md` beschriebenen
      Admin-Bypass, Force-Push und Branch-Löschung blockiert. Weiterhin
      maßgeblich ist der Required
      Check `test` (siehe `CLAUDE.md` → Tests/CI: ohne ihn bliebe der Check ewig
      „pending" und jeder PR dauerhaft blockiert).
- [x] **Actions → Workflow permissions auf „Read and write"** (2026-08-28).
      Stand bis dahin auf `read` — in dem Zustand wäre **jedes** Release
      gescheitert. `release.yml`
      pusht Tags und legt Releases über `secrets.GITHUB_TOKEN` an; steht der
      Account-Default auf read-only, bricht **jedes** Release. Eigene Secrets
      sind keine zu retten — die Workflows nutzen ausschließlich `GITHUB_TOKEN`.
- [x] **Labels `release:major|minor|patch` angelegt** (2026-08-28, Farben und
      Beschreibungen identisch zum alten Repo). Sie fehlten hier; `release.yml`
      triggert ausschließlich auf sie (siehe `CLAUDE.md` → Release-Prozeß) —
      ohne sie wäre ein Release-PR durchgelaufen, ohne ein Release zu erzeugen.
- [x] Zur Kenntnis — Stars, Watcher und Download-Zähler sind weg. Kosmetisch, aber bewusst
      entscheiden.

---

## 5. Code-Stelle: der Auto-Updater

`src/updater.py:35` — `REPO = "MargenHeld/Zeiterfassung"`, genutzt in
`src/ui.py`, `src/background_tasks.py` und
`src/dialogs/settings_dialog/tab_updates.py`. Diese Konstante ist in **jeder
bereits installierten App fest eingebacken** — deshalb die Update-Brücke aus
Abschnitt 3.

- [x] Konstante auf `Xveyn/Zeiterfassung` gesetzt (`src/updater.py:35`). Sie muss im **Brücken-Release
      des alten Repos** stecken, nicht erst im ersten Release des Forks.
- [x] `src/changelog.py:15` baut
      `https://raw.githubusercontent.com/{repo}/v{version}/CHANGELOG.md` — der
      Grund, warum die Tags im Fork vollständig sein müssen (Abschnitt 4). Die
      `MargenHeld/…`-Vorkommen in `tests/test_changelog.py` sind reine
      Fixture-Daten, unkritisch.

---

## 6. Bewusst NICHT anfassen

- **`com.margenheld.zeiterfassung`** — `src/autostart.py:12` (`MACOS_LABEL`) und
  `scripts/build.py:160` (`--osx-bundle-identifier`). Ändern = verwaister LaunchAgent
  unter `~/Library/LaunchAgents/`, und macOS behandelt die App als komplett neue
  (Berechtigungen/TCC von vorn). Entweder so lassen oder mit expliziter
  Migration in `autostart.py`.
- **`AppName=Zeiterfassung`** in `installer.iss` — dort ist **kein `AppId`**
  gesetzt, Inno leitet die AppId aus dem AppName ab. An ihr hängt das
  Upgrade-in-place bestehender Windows-Installationen.
  `AppPublisher`/`AppPublisherURL` (Zeile 4–5) sind dagegen gefahrlos änderbar —
  reine Anzeige in „Apps & Features".
- **`assets/margenheld-icon.*`** — referenziert in `scripts/build.py`, `installer.iss`,
  `src/theme.py`, `src/tray.py`, `src/tray_linux.py`, `src/tray_mac.py`,
  `src/desktop_entry.py` und Tests. Rein kosmetisch; falls umbenennen, dann als
  eigener PR, nicht nebenbei. Die Linux-`.desktop`-Seite ist bereits neutral
  (`icon.png` / `Zeiterfassung.desktop`).

---

## 7. Textstellen nachziehen

- [x] `README.md` — Release- und Lizenz-Badges zeigen auf `Xveyn`
- [x] `CONTRIBUTING.md` — clone-URL
- [x] `installer.iss:5` — `AppPublisherURL`
- [x] `SECURITY.md` — Advisory-Link umgestellt, die Meldeadresse
      `sven@margen-held.de` ist ersatzlos entfernt
- [x] `docs/known-limitations.md` — Issue-Link vollqualifiziert
- [x] bloße `#NNN` in `CLAUDE.md` und `docs/` qualifiziert (siehe Abschnitt 4)
- [ ] `AUDIT-2026-07-04.md` — 59 bloße `#NNN`. Die Datei ist weiterhin
      **untracked**, GitHub rendert sie also nirgends; erst beim Einchecken
      relevant.

`AppPublisher=Margenheld` in `installer.iss:4` steht bewusst noch so da — reine
Anzeige in „Apps & Features", Änderung gefahrlos, aber nicht Teil des Umzugs.

---

## Was noch offen ist

Der Code- und Doku-Teil (Abschnitte 1, 5, 7) ist mit dem Brücken-Release
`1.21.0` ausgeliefert. Was bleibt, ist **kein Code**:

Die drei GitHub-Settings aus Abschnitt 4 sind am 2026-08-28 erledigt. Was
bleibt, ist organisatorisch:

| Offen | Abschnitt | Wirkung |
|---|---|---|
| Zugänge/Recovery des Accounts `margenheld` sichern | 2 | ohne sie kein Nachschieben im Archiv |
| Repo-Description im alten Repo nachziehen | 3 | Kosmetik, aber Teil der Landekarte für alte Links |
| `margenheld/Zeiterfassung` archivieren | 3 | **zuletzt** — danach read-only |
| Issue-Referenzen auf die Kopien im neuen Repo umbiegen | 4 | offene Anschlußfrage, kein Fehler |

Dauerauflagen (nie „erledigt"): den alten Repo-Namen belegt lassen und das
Brücken-Release dort stehen lassen.

---

## Reihenfolge in einem Satz

Account- und Domain-Zugänge sichern → Tags in den Fork pushen →
Brücken-Release `1.21.0` mit neuem `updater.REPO` **im alten Repo** → Fork aufsetzen (Branch Protection,
Actions-Permissions, detach fork) → Doku-URLs und Issue-Referenzen → altes Repo
als Archiv stehen und den Namen dauerhaft belegt lassen.
