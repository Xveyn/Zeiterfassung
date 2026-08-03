# Fork-Promotion — `Xveyn/Zeiterfassung` wird die Source of Truth

Design für den Umzug des Projekts vom Upstream `margenheld/Zeiterfassung` in den
Fork `Xveyn/Zeiterfassung`. Der Upstream wird anschließend archiviert.

Entspricht **Variante B** aus dem Arbeitsdokument `docs/project-handover.md`
(bewusst untracked). Dieses Design ersetzt dessen Abschnitte 5, 6 und 8 —
die dortigen Ausgangswerte sind an zwei Stellen überholt (siehe unten).

---

## Ausgangslage

`margenheld/Zeiterfassung` ist nicht archiviert, `Xveyn/Zeiterfassung` ist noch
als Fork verknüpft. Letztes echtes Release ist **v1.20.0** (29.07.2026), offen
ist **PR #184** (Linux-SNI-Tray + Readiness) gegen `margenheld/master`.

Zwei Annahmen aus `project-handover.md` sind überholt — beide entlasten den Plan:

| `project-handover.md` | Verifizierter Stand (03.08.2026) |
|---|---|
| Fork hat 33 Tags, upstream 44 → `git push origin --tags` nötig | **44/44 vollständig**, plus die eigenen Test-Tags `v1.17.0-pre.1` und `v1.20.0-pre.1`. Nichts nachzuziehen. |
| Actions/Release-Pipeline im Fork neu einrichten | **Läuft bereits** — `release.yml` hat am 30.07.2026 per `workflow_dispatch` erfolgreich einen Pre-Release im Fork gebaut. |

Offen bleibt im Fork: **keine Branch Protection** auf `master`, die
Fork-Verknüpfung, und fünf Alt-Releases aus Testbauten — darunter **v1.17.0 als
„Latest"**, was die Startseite des Forks bis zum ersten echten Release dort
falsch beschriftet.

## Entschiedene Fragen

| Frage | Entscheidung |
|---|---|
| Update-Brücke für Bestandsinstallationen | **Ja** — letztes Release aus dem alten Repo, bevor archiviert wird |
| Verhältnis zu PR #184 | #184 zuerst als **v1.21.0** releasen (inkl. Linux-Pre-Release-Test), Brücke danach |
| Versionssprung der Brücke | **minor → v1.22.0**, Label `release:minor` |
| Security-Meldeadresse | Nur GitHub Security Advisories; `sven@margen-held.de` **ersatzlos streichen** |
| LICENSE | MargenHeld-Zeile bleibt, eigene Copyright-Zeile **ergänzen** |
| Alt-Releases im Fork | Release-Objekte löschen, **Tags behalten** |
| „Umgezogen"-Hinweis im README des alten Repos | **Nicht** im PR — Direkt-Commit auf `margenheld/master` nach dem Release |

## Warum eine Brücke überhaupt nötig ist

`src/updater.py:35` — `REPO = "MargenHeld/Zeiterfassung"` — ist in **jeder bereits
installierten App fest eingebacken**. Genutzt in `src/ui.py:545`,
`src/background_tasks.py:127` und `src/dialogs/settings_dialog/tab_updates.py:153`;
dieselbe Konstante wird in `tab_updates.py:182` an
`changelog.fetch_changelog_entry` weitergereicht, deckt also Update-Check **und**
Changelog-Abruf ab.

Ein Fork erbt keine Redirects. Ohne Brücke fragen alle Bestandsinstallationen
dauerhaft das alte Repo ab und erfahren nie von einem Update. Die App
aktualisiert sich nie selbst — `update_banner._open_download` und
`tab_updates._open_download` machen beide nur `webbrowser.open(url)`. Der Updater
ist ein reiner **Melder**; die Migration kann also nicht stillschweigend
passieren, ist technisch aber trivial, sobald die Meldung ankommt.

---

## Ablauf

### Phase 1 — Zugänge sichern (zeitkritisch, außerhalb von Git)

Vor jeder Abschaltung von Firmen-Infrastruktur:

- GitHub-Account/Org `margenheld`: Login und Recovery-Adresse von einem
  Firmenpostfach bzw. `margen-held.de` auf eine private Adresse umstellen.
- 2FA-Recovery-Codes sichern.

Ohne diesen Zugang ist das Brücken-Release unmöglich — und damit der ganze Plan.

### Phase 2 — PR #184 als v1.21.0 aus dem alten Repo

Regulärer Prozess, keine Sonderbehandlung: Linux-Pre-Release triggern (Konvention
„Plattformspezifische PRs" in `CLAUDE.md`), auf Linux/KDE testen,
`src/version.py` → `1.21.0`, CHANGELOG-Eintrag, Label `release:minor`, mergen.

Der Brücken-PR stackt darauf und wird nach dem Merge auf `master` rebased.

### Phase 3 — Der Brücken-PR (v1.22.0)

Zweigt von `master` ab (nach Phase 2), geht gegen `margenheld/master`, trägt
Label **`release:minor`**. Bewusst klein gehalten: jeder Nutzer muss ihn
installieren, damit die Umstellung greift.

#### Code

| Datei | Änderung |
|---|---|
| `src/updater.py:35` | `REPO = "Xveyn/Zeiterfassung"` |
| `src/version.py` | `VERSION = "1.22.0"` |
| `CHANGELOG.md` | Abschnitt `## 1.22.0` — siehe „Umzugstext" unten |

#### Doku und Metadaten

| Datei | Änderung |
|---|---|
| `README.md:5` | Release-Badge (`img.shields.io/github/v/release/…`) und dessen Link auf den Fork |
| `CONTRIBUTING.md:9` | clone-URL |
| `SECURITY.md:8` | Link „neuestes Release" |
| `SECURITY.md:22` | Advisory-Link |
| `SECURITY.md:24` | Zeile „Alternativ per E-Mail an **sven@margen-held.de**." **ersatzlos entfernen** |
| `installer.iss:5` | `AppPublisherURL` |
| `docs/known-limitations.md:149` | Issue-Link |
| `LICENSE` | Zeile `Copyright (c) 2026 Xveyn` **unter** der bestehenden MargenHeld-Zeile ergänzen; die bestehende bleibt unverändert stehen (MIT: „shall be included in all copies") |

#### Issue-Referenzen vollqualifizieren

Bloße `#NNN` verlinken im Fork auf dessen *eigene* Issues — semantisch falsch,
sobald dort welche entstehen. Ersetzen durch `margenheld/Zeiterfassung#NNN`;
vollqualifizierte Refs rendern in **beiden** Repos korrekt, der Schritt ist im
alten Repo also unschädlich.

Betroffen sind 21 Vorkommen in drei Dateien:

- `CLAUDE.md` — Zeilen 105, 112, 113, 114, 129, 130, 137, 386 (×2), 414, 418, 419
- `src/CLAUDE.md` — Zeilen 101, 195, 233, 309, 310
- `docs/known-limitations.md` — Zeilen 78, 112, 136, 137

`AUDIT-2026-07-04.md` ist untracked und enthält bereits vollqualifizierte Links —
kein Handlungsbedarf.

#### Nicht im PR

Der „Projekt umgezogen"-Hinweis im README **des alten Repos**: Er würde über den
Merge in den Fork mitwandern und dort dauerhaft falsch stehen. Kommt in Phase 5
als Direkt-Commit auf `margenheld/master`.

#### Umzugstext im CHANGELOG

Der CHANGELOG-Abschnitt ist die **einzige Umzugsmeldung, die Bestandsnutzer je zu
sehen bekommen**: Der Updates-Tab zeigt genau diesen Abschnitt (`changelog.py`
lädt ihn vom Tag), während die GitHub-Release-Notes daneben automatisch aus den
PR-Titeln generiert werden und den Umzug nicht erwähnen. Er muss deshalb sagen,
*dass* umgezogen wird und *dass* dieses Update Voraussetzung für alle künftigen
ist — nicht bloß „Repository-URL angepasst".

Entwurf (Datum beim Schreiben des PRs auf den geplanten Release-Tag setzen,
wie bei jedem CHANGELOG-Eintrag):

```markdown
## 1.22.0 — 2026-08-XX

### Geändert
- **Das Projekt ist umgezogen.** Zeiterfassung wird ab sofort unter
  `github.com/Xveyn/Zeiterfassung` weiterentwickelt; das bisherige Repository
  wird archiviert und erhält keine Updates mehr. **Dieses Update ist
  Voraussetzung dafür, künftige Versionen angeboten zu bekommen** — die
  Update-Prüfung dieser Version fragt bereits den neuen Ort ab. Wer es
  überspringt, bleibt dauerhaft auf dem alten Stand stehen, ohne einen Hinweis
  darauf zu erhalten. An der App selbst ändert sich nichts: gleiche
  Installation, gleiche Daten, gleiche Einstellungen.
```

### Phase 4 — Fork wird das neue Zuhause

Handarbeit auf GitHub, kein Code:

- **Branch Protection** auf `master` einrichten, Required Check **`test`**.
  Nicht `test-matrix` — ein Matrix-Job meldet seine Contexts ausschließlich mit
  Suffix (`test-matrix (3.10)` …); `test` ist der schlanke Sammel-Job, der
  genau dafür existiert (`CLAUDE.md` → Tests/CI).
- **Settings → Actions → General → Workflow permissions = „Read and write"**
  gegenprüfen. `release.yml` pusht Tags und legt Releases über
  `secrets.GITHUB_TOKEN` an; steht der Default auf read-only, bricht jedes
  Release. Eigene Secrets gibt es keine zu übertragen.
- **Fork-Verknüpfung lösen** („detach fork" über den GitHub-Support). Bis dahin
  zielen neue PRs per Default auf das alte Repo. Übergangsweise immer das
  Base-Repo prüfen bzw. `gh pr create --repo Xveyn/Zeiterfassung` verwenden.
- **Alt-Releases aufräumen:** die fünf Release-Objekte aus Testbauten löschen
  (`v1.14.1`, `v1.15.0`, `v1.17.0`, `v1.17.0-pre.1`, `v1.20.0-pre.1`).
  **Ohne `--cleanup-tag`** — die Tags müssen bleiben, `changelog.py` lädt
  `raw.githubusercontent.com/{repo}/v{version}/CHANGELOG.md` und das
  `pre-check`-Gate in `release.yml` prüft Tag-Existenz.
- **Fork-`master` auf den Stand nach dem Brücken-Merge bringen und den Tag
  `v1.22.0` in den Fork pushen** — sonst findet `changelog.py` den Eintrag
  dieser Version im neuen Zuhause nicht mehr.
- Lokal: `git remote set-url origin`/`upstream` aufräumen.
- Repo-Description und README des Forks prüfen.

### Phase 5 — Ausrollen, dann archivieren

- **Erstes Fork-Release muss > 1.22.0 sein** (also ≥ 1.22.1), sonst greift
  `updater.is_newer` bei niemandem und es wird nie wieder ein Update angeboten.
- Altes Repo: README und Repo-Description auf „umgezogen nach …" (Direkt-Commit,
  siehe Phase 3), Brücken-Release stehen lassen.
- **Alten Repo-Namen dauerhaft belegt lassen.** Nicht migrierte Installationen
  fragen `MargenHeld/Zeiterfassung` dauerhaft ab. Wird der Name freigegeben und
  von Dritten neu belegt, bekommen diese Nutzer fremde Assets zum Download
  angeboten — Supply-Chain-Risiko, nicht bloß Kosmetik.
- **Archivieren ganz zuletzt.** Ein archiviertes Repo ist read-only; danach lässt
  sich dort kein weiteres Hinweis-Release mehr nachschieben.
- Erwartungsmanagement: `updater.should_check` throttelt den Check (Default
  1×/Tag). Wer die App wochenlang nicht öffnet, sieht die Meldung entsprechend
  später. Kein Handlungsbedarf.

---

## Bewusst nicht angefasst

- **`com.margenheld.zeiterfassung`** — `src/autostart.py:12` (`MACOS_LABEL`) und
  `build.py:146` (`--osx-bundle-identifier`). Ändern hinterlässt einen verwaisten
  LaunchAgent unter `~/Library/LaunchAgents/`, und macOS behandelt die App als
  komplett neue (Berechtigungen/TCC von vorn). Nur mit expliziter Migration in
  `autostart.py` und dann als eigener PR.
- **`AppName=Zeiterfassung`** in `installer.iss` — dort ist **kein `AppId`**
  gesetzt, Inno leitet die AppId aus dem AppName ab. Daran hängt das
  Upgrade-in-place bestehender Windows-Installationen.
  `AppPublisher`/`AppPublisherURL` sind dagegen gefahrlos änderbar (reine Anzeige
  in „Apps & Features").
- **`assets/margenheld-icon.*`** — referenziert in `build.py`, `installer.iss`,
  `src/theme.py`, `src/tray.py`, `src/tray_linux.py`, `src/tray_mac.py`,
  `src/desktop_entry.py` und mehreren Tests. Rein kosmetisch; falls überhaupt,
  dann als eigener PR.
- **`updater.REPO`-Vorkommen in `tests/test_updater.py` und
  `tests/test_changelog.py`** — reine Fixture-Daten (`html_url`-Strings in
  API-Antworten), keine Assertion auf die Konstante.

## Verifikation

Automatisiert vor dem Merge: `pytest` grün, `ruff check .` sauber,
`npx pyright` unverändert. Die Änderung ist eine Konstanten- und Textänderung
ohne neue Abhängigkeiten; ein neuer Test ist nicht sinnvoll (getestet wird
Logik, nicht Konfiguration).

Manuell nach dem Brücken-Release:

1. Eine Installation auf 1.21.0 muss 1.22.0 im Updates-Tab melden — inklusive
   des Umzugstexts aus dem CHANGELOG.
2. Nach Installation von 1.22.0 muss der Updates-Tab das **erste Fork-Release**
   finden. Das ist der eigentliche Beweis, dass die Brücke trägt, und geht erst
   nach Phase 5 Schritt 1.
