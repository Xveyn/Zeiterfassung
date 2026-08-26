# Projekt-Übernahme — Fork-Promotion nach `Xveyn/Zeiterfassung`

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

- [ ] **`LICENSE`: `Copyright (c) 2026 MargenHeld GmbH` bleibt stehen.**
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
- [ ] **Domain `margen-held.de`:** trägt die Security-Meldeadresse
      (`SECURITY.md:24`, `sven@margen-held.de`). Läuft die Domain aus und
      registriert sie jemand neu, empfängt dieser Passwort-Resets für jeden
      Account, der noch auf sie zeigt. → GitHub-Account auf eine private
      Adresse umstellen, 2FA-Recovery-Codes sichern.
- [ ] **Alten Repo-Namen `margenheld/Zeiterfassung` dauerhaft belegt lassen** —
      siehe das Squatting-Risiko in Abschnitt 3.
- [ ] `com.margenheld.zeiterfassung` verweist per Reverse-DNS-Konvention auf
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

- [ ] **Schritt 1 — Brücken-Release im ALTEN Repo.** Ein normales Release mit
      genau einer funktionalen Änderung: `updater.REPO` zeigt auf
      `Xveyn/Zeiterfassung`. Gebaut und veröffentlicht wird es noch im alten
      Repo, die Assets liegen also dort. Regulärer Prozess: `src/version.py`
      bumpen, CHANGELOG-Eintrag („Projekt umgezogen"), `release:patch`-Label,
      mergen.
- [ ] **Schritt 2 — verteilen lassen.** Nutzer sehen die Meldung im
      Updates-Tab/Banner, laden aus dem alten Repo, installieren. Ab dann fragt
      ihre App das neue Repo.
- [ ] **Schritt 3 — alle weiteren Releases im neuen Repo**, mit **höherer**
      Versionsnummer als die Brücke — sonst greift `is_newer` nicht und die
      Nutzer bekommen nie wieder ein Update angeboten.

**Nachzügler:** Wer die Brücke nie installiert, hängt dauerhaft am alten Repo.
Daher:

- [ ] Altes Repo **nicht löschen, nicht umbenennen**, Brücken-Release stehen
      lassen. README und Repo-Description dort auf „umgezogen nach …" ändern.
- [ ] **Archivieren erst ganz am Ende** — ein archiviertes Repo ist read-only,
      danach lässt sich dort kein weiteres Hinweis-Release mehr nachschieben.
- [ ] Erwartungsmanagement: `should_check` throttelt den Update-Check (Default
      1×/Tag). Wer die App wochenlang nicht öffnet, sieht die Meldung
      entsprechend später. Kein Handlungsbedarf.

**Squatting-Risiko:** Ohne Redirect fragen nicht migrierte Installationen
dauerhaft `MargenHeld/Zeiterfassung` ab. Wird der Name freigegeben und von
Dritten neu belegt, bekommen diese Nutzer fremde Assets zum Download angeboten.
Der alte Name muss dauerhaft belegt bleiben.

---

## 4. Fork-spezifische GitHub-Arbeit

- [ ] **Tags nachziehen.** Stand 2026-08-26: beide Seiten haben **46 Tags**, aber
      nicht dieselben — dem Fork fehlt `v1.20.0-pre.2`, upstream fehlt
      `v1.17.0-pre.1`. `git push origin --tags` schließt die Lücke im Fork.
      Ohne die Tags scheitern zwei Dinge: (a) `src/changelog.py:15` lädt
      `raw.githubusercontent.com/{repo}/v{version}/CHANGELOG.md` und findet für
      ältere Versionen nichts mehr; (b) das `pre-check`-Gate in `release.yml`
      verlangt für einen Pre-Release, dass `v<VERSION>` bereits existiert.
      **Vor jedem Umzugsschritt neu zählen** — die Zahl veraltet mit jedem
      Release.
- [ ] **GitHub-Releases werden nicht mitgeforkt.** Ein Fork enthält die
      Git-Historie, aber keine Release-Objekte und keine Assets. Alte
      Download-Links zeigen weiterhin ins alte Repo — funktioniert, solange es
      steht (siehe Abschnitt 3).
- [ ] **Fork-Beziehung lösen** (GitHub-Support, „detach fork"). Bis dahin zielen
      neue PRs per Default auf das Upstream → Gefahr, versehentlich ins alte
      Repo zu mergen. Übergangsweise immer das Base-Repo prüfen bzw.
      `gh pr create --repo Xveyn/Zeiterfassung` verwenden.
- [ ] **Issue-Nummern-Falle:** Alle `#NNN`-Referenzen in `CLAUDE.md`,
      `docs/known-limitations.md` und `AUDIT-2026-07-04.md` (#42, #96, #99,
      #118, #131, #148, #183 …) meinen das alte Repo. Im neuen Repo verlinkt
      GitHub `#42` auf dessen *eigenes* Issue 42 — semantisch falsch, sobald
      dort Issues entstehen. Gegenmaßnahme: bloße `#NNN` durch vollqualifizierte
      `margenheld/Zeiterfassung#42` ersetzen.
- [ ] **Branch Protection im Fork neu einrichten**, insbesondere den Required
      Check `test` (siehe `CLAUDE.md` → Tests/CI: ohne ihn bliebe der Check ewig
      „pending" und jeder PR dauerhaft blockiert).
- [ ] **Actions → Workflow permissions = „Read and write"** prüfen. `release.yml`
      pusht Tags und legt Releases über `secrets.GITHUB_TOKEN` an; steht der
      Account-Default auf read-only, bricht **jedes** Release. Eigene Secrets
      sind keine zu retten — die Workflows nutzen ausschließlich `GITHUB_TOKEN`.
- [ ] Stars, Watcher und Download-Zähler sind weg. Kosmetisch, aber bewusst
      entscheiden.

---

## 5. Code-Stelle: der Auto-Updater

`src/updater.py:35` — `REPO = "MargenHeld/Zeiterfassung"`, genutzt in
`src/ui.py`, `src/background_tasks.py` und
`src/dialogs/settings_dialog/tab_updates.py`. Diese Konstante ist in **jeder
bereits installierten App fest eingebacken** — deshalb die Update-Brücke aus
Abschnitt 3.

- [ ] Konstante auf `Xveyn/Zeiterfassung` setzen. Sie muss im **Brücken-Release
      des alten Repos** stecken, nicht erst im ersten Release des Forks.
- [ ] `src/changelog.py:15` baut
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

- [ ] `README.md:5` — Release- und Lizenz-Badges
- [ ] `CONTRIBUTING.md:9` — clone-URL
- [ ] `installer.iss:5` — `AppPublisherURL`
- [ ] `SECURITY.md:22-24` — Advisory-Link **und Meldeadresse**
      (`sven@margen-held.de` → neuer Verantwortlicher, siehe Abschnitt 2)
- [ ] `docs/known-limitations.md:149` — Issue-Link
- [ ] `AUDIT-2026-07-04.md` — PR-/Issue-Links (aktuell untracked)
- [ ] bloße `#NNN` in `CLAUDE.md` und `docs/` qualifizieren (siehe Abschnitt 4)

Die Zeilennummern stimmen zum Stand 2026-08-26 und sollten vor dem Nachziehen
kurz gegengeprüft werden.

---

## Stand der Vorbereitung

Ein Teil der Code- und Doku-Änderungen liegt bereits vor: der lokale Branch
`chore/fork-promotion` stellt `updater.REPO` um, zieht die Repo-URLs in
`README.md`/`CONTRIBUTING.md`/`installer.iss`/`SECURITY.md` nach, ergänzt die
eigene Copyright-Zeile in `LICENSE` und qualifiziert die Issue-Referenzen —
also die Abschnitte 5 und 7 sowie den ergänzenden Teil von Abschnitt 1.

Er zweigt allerdings von einem **57 Commits alten** Stand ab (vor dem
Webhook-Versand und vor der Verschiebung nach `scripts/`) und braucht einen
Rebase; Konflikte sind in `CLAUDE.md`, `README.md` und
`docs/known-limitations.md` zu erwarten, weil beide Seiten dort gewachsen sind.

Nicht vorbereitet und rein organisatorisch: alles aus Abschnitt 2, die
GitHub-Einstellungen aus Abschnitt 4 und das Brücken-Release selbst.

---

## Reihenfolge in einem Satz

Account- und Domain-Zugänge sichern → Tags in den Fork pushen → Brücken-Release
mit neuem `updater.REPO` **im alten Repo** → Fork aufsetzen (Branch Protection,
Actions-Permissions, detach fork) → Doku-URLs und Issue-Referenzen → altes Repo
als Archiv stehen und den Namen dauerhaft belegt lassen.
