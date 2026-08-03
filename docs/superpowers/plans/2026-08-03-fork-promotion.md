# Fork-Promotion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den Brücken-Release **v1.22.0** aus `margenheld/Zeiterfassung` vorbereiten, der `updater.REPO` auf `Xveyn/Zeiterfassung` umstellt und damit Bestandsinstallationen an das neue Zuhause übergibt.

**Architecture:** Reine Konstanten-, Text- und Metadaten-Änderung in einem PR gegen `margenheld/master`. Kein neues Modul, keine neue Abhängigkeit, kein Workflow-Eingriff — `release.yml` arbeitet mit `${{ github.repository }}` und ist von Haus aus repo-agnostisch. Die Umstellung wirkt erst, wenn Nutzer das daraus gebaute Release installieren; der CHANGELOG-Abschnitt ist die dafür entscheidende Nachricht.

**Tech Stack:** Python 3.10+, stdlib-only im betroffenen Code (`urllib` in `updater.py`/`changelog.py`), pytest, ruff, pyright, Inno Setup (nur `installer.iss`-Metadaten).

**Spec:** `docs/superpowers/specs/2026-08-03-fork-promotion-design.md`

## Global Constraints

- Zielversion ist **`1.22.0`**, der PR trägt das Label **`release:minor`**.
- Neuer Repo-String ist exakt **`Xveyn/Zeiterfassung`** (Groß-/Kleinschreibung wie hier).
- Alter Repo-String ist **`margenheld/Zeiterfassung`** in URLs und **`MargenHeld/Zeiterfassung`** in `src/updater.py`.
- **Nicht anfassen:** `com.margenheld.zeiterfassung` (`src/autostart.py:12`, `build.py:146`), `AppName=Zeiterfassung` in `installer.iss:2`, alle `assets/margenheld-icon.*`-Referenzen, die `MargenHeld/…`-Fixture-Strings in `tests/test_updater.py` und `tests/test_changelog.py`.
- **Kein** „Projekt umgezogen"-Hinweis im `README.md` — der gehört als Direkt-Commit ins alte Repo, nachdem das Release durch ist (Phase 5 der Spec), sonst wandert er in den Fork.
- Datumsformat im CHANGELOG: `## X.Y.Z — YYYY-MM-DD` (ISO), wie alle bestehenden Einträge.
- Commit-Messages auf Deutsch im Stil des Repos (`fix(scope): …`, `docs: …`, `chore: …`).

## Vorbedingungen

Bevor Task 1 startet:

1. **Zugang zum alten Repo ist dauerhaft gesichert** (Phase 1 der Spec): Login und Recovery-Adresse des GitHub-Accounts `margenheld` hängen nicht mehr an einem Firmenpostfach oder an `margen-held.de`, 2FA-Recovery-Codes liegen vor. Ohne diesen Zugang lässt sich das Brücken-Release nicht veröffentlichen — dann ist der ganze Plan hinfällig, nicht nur verzögert.
2. **PR #184 ist nach `margenheld/master` gemergt und als v1.21.0 released.** Solange das offen ist, ist die Zielversion dieses Plans falsch.
3. Der Arbeitsbranch **`chore/fork-promotion`** ist auf den neuen `master` rebased:

```bash
git fetch upstream
git rebase upstream/master
```

Der Branch enthält zu diesem Zeitpunkt genau zwei Doku-Commits (Spec und diesen Plan).

## File Structure

| Datei | Verantwortung in diesem PR |
|---|---|
| `src/updater.py` | Trägt die eine Konstante, an der die ganze Migration hängt |
| `src/version.py`, `CHANGELOG.md` | Release-Auslöser und die einzige Nutzer-Nachricht über den Umzug |
| `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `installer.iss`, `docs/known-limitations.md` | Nach außen sichtbare Repo-URLs |
| `LICENSE` | Urheberrechtsvermerk |
| `CLAUDE.md`, `src/CLAUDE.md`, `docs/known-limitations.md` | Issue-Referenzen, die im Fork sonst ins Leere zeigen |

---

### Task 1: `updater.REPO` auf den Fork umstellen

**Files:**
- Modify: `src/updater.py:35`

**Interfaces:**
- Consumes: nichts aus früheren Tasks.
- Produces: `src.updater.REPO: str` — der neue Wert `"Xveyn/Zeiterfassung"`. Konsumenten bleiben unverändert: `src/ui.py:545`, `src/background_tasks.py:127`, `src/dialogs/settings_dialog/tab_updates.py:153` (Update-Check) und `tab_updates.py:182` (Changelog-Abruf über `changelog.fetch_changelog_entry(REPO, version)`).

**Kein neuer Test.** `CLAUDE.md` → „Getestet wird Logik, nicht UI" gilt hier sinngemäß auch gegen Konfiguration: ein `assert REPO == "Xveyn/Zeiterfassung"` wäre eine Tautologie, die dieselbe Zeile zweimal schreibt und beim nächsten Umzug doppelte Arbeit macht. Die Absicherung ist die bestehende Suite (belegt, dass kein Test auf den alten Wert baut) plus die manuelle Verifikation nach dem Release.

- [ ] **Step 1: Belegen, dass kein Test auf den alten Wert assertiert**

Run:
```bash
grep -rn "MargenHeld" tests/
```

Expected: Genau vier Treffer, alle in `html_url`-/`compare`-Strings von API-Fixtures — `tests/test_updater.py:154`, `tests/test_updater.py:315`, `tests/test_changelog.py:159-164`. Keiner davon importiert oder vergleicht `updater.REPO`. Tauchen andere Treffer auf, hier stoppen und melden.

- [ ] **Step 2: Konstante ändern**

In `src/updater.py:35`:

```python
REPO = "Xveyn/Zeiterfassung"
```

- [ ] **Step 3: Volle Suite laufen lassen**

Run: `python -m pytest -q`
Expected: PASS, gleiche Anzahl Tests wie vorher.

- [ ] **Step 4: Commit**

```bash
git add src/updater.py
git commit -m "feat(updater): Update-Check auf Xveyn/Zeiterfassung umstellen"
```

---

### Task 2: Repo-URLs in der nach außen sichtbaren Doku

**Files:**
- Modify: `README.md:5`
- Modify: `CONTRIBUTING.md:9`
- Modify: `SECURITY.md:8`, `SECURITY.md:20-24`
- Modify: `installer.iss:5`
- Modify: `docs/known-limitations.md:149`

**Interfaces:**
- Consumes: nichts.
- Produces: nichts, was spätere Tasks referenzieren.

- [ ] **Step 1: README-Badge umstellen**

In `README.md:5` beide Vorkommen ersetzen — im Badge-Bild **und** im Link-Ziel:

Vorher:
```markdown
[![Release](https://img.shields.io/github/v/release/margenheld/Zeiterfassung?label=Release&color=success&logo=github)](https://github.com/margenheld/Zeiterfassung/releases/latest)
```

Nachher:
```markdown
[![Release](https://img.shields.io/github/v/release/Xveyn/Zeiterfassung?label=Release&color=success&logo=github)](https://github.com/Xveyn/Zeiterfassung/releases/latest)
```

Der Rest der Zeile (Python-, Platform-, License-Badges) bleibt unverändert.

- [ ] **Step 2: clone-URL in CONTRIBUTING**

In `CONTRIBUTING.md:9`:

Vorher:
```
git clone https://github.com/margenheld/Zeiterfassung.git
```

Nachher:
```
git clone https://github.com/Xveyn/Zeiterfassung.git
```

- [ ] **Step 3: SECURITY.md — Release-Link**

In `SECURITY.md:8`:

Vorher:
```markdown
[neueste Release](https://github.com/margenheld/Zeiterfassung/releases/latest)
```

Nachher:
```markdown
[neueste Release](https://github.com/Xveyn/Zeiterfassung/releases/latest)
```

- [ ] **Step 4: SECURITY.md — Meldeweg auf Advisories reduzieren**

Der Block ab „Bevorzugter Weg …" bis zur E-Mail-Zeile wird ersetzt. Die
Firmen-Domain `margen-held.de` fällt mit der Gesellschaft weg; eine Meldeadresse,
die niemand mehr liest — oder die später jemand anders registriert — ist
schlechter als keine.

Vorher:
```markdown
Bevorzugter Weg ist eine private Meldung über GitHub:

1. [**Security Advisories**](https://github.com/margenheld/Zeiterfassung/security/advisories/new) → „Report a vulnerability"

Alternativ per E-Mail an **sven@margen-held.de**.
```

Nachher:
```markdown
Meldungen laufen über die privaten
[**Security Advisories**](https://github.com/Xveyn/Zeiterfassung/security/advisories/new)
des Repositories → „Report a vulnerability".
```

Der Absatz davor („Bitte melde Sicherheitslücken **nicht** über öffentliche
GitHub-Issues.") und der danach („Hilfreich für eine schnelle Einschätzung:")
bleiben unverändert.

- [ ] **Step 5: installer.iss**

In `installer.iss:5`:

Vorher:
```
AppPublisherURL=https://github.com/margenheld/Zeiterfassung
```

Nachher:
```
AppPublisherURL=https://github.com/Xveyn/Zeiterfassung
```

`AppName` (Zeile 2), `AppPublisher` (Zeile 4) und `SetupIconFile` (Zeile 11)
bleiben unverändert — an `AppName` hängt mangels gesetzter `AppId` das
Upgrade-in-place bestehender Windows-Installationen.

- [ ] **Step 6: known-limitations Issue-Link**

In `docs/known-limitations.md:149`:

Vorher:
```markdown
[#183](https://github.com/margenheld/Zeiterfassung/issues/183).
```

Nachher:
```markdown
[margenheld/Zeiterfassung#183](https://github.com/margenheld/Zeiterfassung/issues/183).
```

Bewusst **nicht** auf den Fork umgebogen: Issue 183 existiert im alten Repo und
wird nicht mitwandern. Der Link bleibt korrekt, nur der Linktext wird
eindeutig — sonst liest sich `#183` im Fork wie dessen eigenes Issue.

- [ ] **Step 7: Verifizieren, dass keine umzustellende URL übrig ist**

Run:
```bash
grep -n "github.com/margenheld" README.md CONTRIBUTING.md SECURITY.md installer.iss
```

Expected: keine Ausgabe (Exit-Code 1).

Run:
```bash
git grep -n "margen-held.de" -- ':!docs/superpowers'
```

Expected: keine Ausgabe. Die Pfad-Ausnahme ist nötig, weil Spec und Plan die
Adresse zitieren, um ihre Streichung zu begründen; ein `grep -r` über alles
träfe zusätzlich das untrackte `docs/project-handover.md`.

- [ ] **Step 8: Suite und Linter**

Run: `python -m pytest -q ; ruff check .`
Expected: beides sauber. (Reine Textänderungen, aber `installer.iss`-Tippfehler fallen sonst erst im Release-Build auf.)

- [ ] **Step 9: Commit**

```bash
git add README.md CONTRIBUTING.md SECURITY.md installer.iss docs/known-limitations.md
git commit -m "docs: Repo-URLs auf Xveyn/Zeiterfassung umstellen"
```

---

### Task 3: LICENSE um die eigene Copyright-Zeile ergänzen

**Files:**
- Modify: `LICENSE:3`

**Interfaces:**
- Consumes: nichts. Produces: nichts.

Die bestehende Zeile wird **ergänzt, nicht ersetzt**. MIT verlangt, dass der
vorhandene Vermerk in allen Kopien erhalten bleibt („shall be included in all
copies") — die MargenHeld-Zeile zu entfernen wäre ein Lizenzverstoß, eine
zweite Zeile daneben ist zulässig und beschreibt die geteilte Urheberschaft.

- [ ] **Step 1: Zeile ergänzen**

Vorher:
```
MIT License

Copyright (c) 2026 MargenHeld GmbH

Permission is hereby granted, free of charge, to any person obtaining a copy
```

Nachher:
```
MIT License

Copyright (c) 2026 MargenHeld GmbH
Copyright (c) 2026 Xveyn

Permission is hereby granted, free of charge, to any person obtaining a copy
```

- [ ] **Step 2: Commit**

```bash
git add LICENSE
git commit -m "docs(license): eigene Copyright-Zeile ergaenzen"
```

---

### Task 4: Issue-Referenzen vollqualifizieren

**Files:**
- Modify: `CLAUDE.md` — Zeilen 105, 112, 113, 114, 129, 130, 386, 414, 418, 419
- Modify: `src/CLAUDE.md` — Zeilen 101, 195, 233, 309, 310
- Modify: `docs/known-limitations.md` — Zeilen 78, 112, 136, 137

**Interfaces:**
- Consumes: nichts. Produces: nichts.

Bloße `#NNN` verlinkt GitHub im Fork auf **dessen eigene** Issues — sobald dort
Issue 42 entsteht, zeigt jede `#42`-Erwähnung auf das falsche Ticket.
`margenheld/Zeiterfassung#42` rendert in beiden Repos korrekt, der Schritt ist im
alten Repo also unschädlich.

**Präzise Ersetzungen** (jeweils nur das genannte Vorkommen in der genannten Zeile):

| Datei:Zeile | Vorher | Nachher |
|---|---|---|
| `CLAUDE.md:105` | `siehe #42)` | `siehe margenheld/Zeiterfassung#42)` |
| `CLAUDE.md:112` | `macOS-Gate in #96.` | `macOS-Gate in margenheld/Zeiterfassung#96.` |
| `CLAUDE.md:113` | `seit #99 umgesetzt` | `seit margenheld/Zeiterfassung#99 umgesetzt` |
| `CLAUDE.md:114` | `als #100 weiterhin` | `als margenheld/Zeiterfassung#100 weiterhin` |
| `CLAUDE.md:129` | `nicht → #118;` | `nicht → margenheld/Zeiterfassung#118;` |
| `CLAUDE.md:130` | `#116; der` | `margenheld/Zeiterfassung#116; der` |
| `CLAUDE.md:386` | `(#131) und dessen Verfeinerung #148` | `(margenheld/Zeiterfassung#131) und dessen Verfeinerung margenheld/Zeiterfassung#148` |
| `CLAUDE.md:414` | `(Werkstudenten-Privileg, #98)` | `(Werkstudenten-Privileg, margenheld/Zeiterfassung#98)` |
| `CLAUDE.md:418` | `` `ZEIT_MACOS_TRAY=1`, #88)`` | `` `ZEIT_MACOS_TRAY=1`, margenheld/Zeiterfassung#88)`` |
| `CLAUDE.md:419` | `` `ZEIT_LINUX_TRAY=1`, #42)`` | `` `ZEIT_LINUX_TRAY=1`, margenheld/Zeiterfassung#42)`` |
| `src/CLAUDE.md:101` | `abgeschnitten, #92).` | `abgeschnitten, margenheld/Zeiterfassung#92).` |
| `src/CLAUDE.md:195` | `(Werkstudenten-Privileg, #98).` | `(Werkstudenten-Privileg, margenheld/Zeiterfassung#98).` |
| `src/CLAUDE.md:233` | `-Retry, #135).` | `-Retry, margenheld/Zeiterfassung#135).` |
| `src/CLAUDE.md:309` | `NSStatusItem-Backend, #88)` | `NSStatusItem-Backend, margenheld/Zeiterfassung#88)` |
| `src/CLAUDE.md:310` | `über D-Bus, #42).` | `über D-Bus, margenheld/Zeiterfassung#42).` |
| `docs/known-limitations.md:78` | `im Rahmen von PR #60)` | `im Rahmen von PR margenheld/Zeiterfassung#60)` |
| `docs/known-limitations.md:112` | `in Plasma (#42)` | `in Plasma (margenheld/Zeiterfassung#42)` |
| `docs/known-limitations.md:136` | `**M16** (#131) stellte` | `**M16** (margenheld/Zeiterfassung#131) stellte` |
| `docs/known-limitations.md:137` | `**#148** schlug` | `**margenheld/Zeiterfassung#148** schlug` |

**Ausdrücklich nicht ändern:** `` `#118` `` in `CLAUDE.md:137` steht in einem
Code-Span. GitHub verlinkt darin nicht, die Falle greift dort also nicht — und
vollqualifiziert würde der Backtick-Text nur länger.

- [ ] **Step 1: Ersetzungen vornehmen**

Alle 19 Tabellenzeilen abarbeiten (20 Referenzen — `CLAUDE.md:386` trägt
zwei). Zeilennummern verschieben sich
nicht (keine Zeile wird eingefügt oder entfernt), Zeilenumbrüche in den
Fließtext-Absätzen dürfen aber nachgezogen werden, wo die Zeile durch die
längere Referenz unschön überläuft.

- [ ] **Step 2: Verifizieren, dass keine bloße Referenz übrig ist**

Run:
```bash
grep -nE "(^|[^/])#[0-9]{2,3}" CLAUDE.md src/CLAUDE.md docs/known-limitations.md
```

Expected: Genau ein Treffer — `` `#118` `` in `CLAUDE.md:137` (der bewusst
ausgenommene Code-Span). Jeder weitere Treffer ist eine übersehene Referenz.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md src/CLAUDE.md docs/known-limitations.md
git commit -m "docs: Issue-Referenzen fuer den Umzug vollqualifizieren"
```

---

### Task 5: Version und CHANGELOG

**Files:**
- Modify: `src/version.py:3`
- Modify: `CHANGELOG.md` (neuer Abschnitt ganz oben, direkt unter `# Changelog`)

**Interfaces:**
- Consumes: `src.updater.REPO` aus Task 1 (der CHANGELOG-Text beschreibt dessen Wirkung).
- Produces: `src.version.VERSION == "1.22.0"` — gelesen von `release.yml` (Tag-Berechnung und Pre-Check), `installer.iss` (per `/DAppVer=`) und `version.installed_release_id()`.

Dieser Task kommt **zuletzt**, damit die Versionszeile nicht über mehrere
Rebases mitwandert und damit der CHANGELOG-Text auf den bereits geschriebenen
Änderungen aufsetzt.

- [ ] **Step 1: Version setzen**

In `src/version.py:3`:

```python
VERSION = "1.22.0"
```

- [ ] **Step 2: CHANGELOG-Abschnitt einfügen**

Direkt unter der Überschrift `# Changelog` und vor `## 1.21.0` einfügen. Das
Datum ist das geplante Merge-Datum im Format `YYYY-MM-DD`.

Dieser Abschnitt ist die **einzige Umzugsmeldung, die Bestandsnutzer je zu sehen
bekommen**: Der Updates-Tab zeigt genau ihn (`changelog.fetch_changelog_entry`
lädt ihn vom Tag), während die GitHub-Release-Notes daneben automatisch aus den
PR-Titeln generiert werden und den Umzug nicht erwähnen. Er muss deshalb sagen,
*dass* umgezogen wird und *dass* dieses Update Voraussetzung für alle künftigen
ist:

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

- [ ] **Step 3: Verifizieren, dass der Abschnitt maschinell gefunden wird**

`changelog.extract_version_section` sucht die Überschrift per Regex
`^##\s+(\S+)\s` und vergleicht das erste Token exakt mit der Version. Ein
Tippfehler in der Überschrift bliebe sonst bis nach dem Release unentdeckt:

```bash
python -c "from src.changelog import extract_version_section; print(extract_version_section(open('CHANGELOG.md', encoding='utf-8').read(), '1.22.0')[:80])"
```

Expected: Die ersten Zeichen des neuen Abschnitts, beginnend mit `## 1.22.0`. Bei
`None` stimmt die Überschrift nicht.

- [ ] **Step 4: Commit**

```bash
git add src/version.py CHANGELOG.md
git commit -m "chore(release): Version 1.22.0 — Umzug nach Xveyn/Zeiterfassung"
```

---

### Task 6: Gesamt-Verifikation und PR

**Files:** keine Änderung.

**Interfaces:**
- Consumes: alle vorherigen Tasks.
- Produces: den PR gegen `margenheld/master` mit Label `release:minor`.

- [ ] **Step 1: Vollständige lokale Verifikation**

Run: `python -m pytest -q`
Expected: PASS.

Run: `ruff check .`
Expected: `All checks passed!`

Run: `npx pyright`
Expected: unveränderte Fehler-/Warnungszahl gegenüber `master` (dieser PR fasst keinen typrelevanten Code an).

- [ ] **Step 2: Diff gegenlesen**

Run: `git diff upstream/master --stat`
Expected: genau diese Dateien — `CHANGELOG.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `LICENSE`, `README.md`, `SECURITY.md`, `docs/known-limitations.md`, `docs/superpowers/plans/2026-08-03-fork-promotion.md`, `docs/superpowers/specs/2026-08-03-fork-promotion-design.md`, `installer.iss`, `src/CLAUDE.md`, `src/updater.py`, `src/version.py`.

Taucht `build.py`, `src/autostart.py` oder eine `assets/`-Datei auf, ist etwas aus der Constraints-Liste angefasst worden — zurücknehmen.

- [ ] **Step 3: Branch pushen**

```bash
git push -u origin chore/fork-promotion
```

- [ ] **Step 4: PR gegen das ALTE Repo öffnen**

Das Base-Repo ist bewusst `margenheld/Zeiterfassung` — dort wird das
Brücken-Release gebaut, weil nur dort die Bestandsinstallationen nachfragen.

Beschreibung zuerst in eine Datei schreiben (Heredocs und PowerShell-Here-Strings
scheitern auf dieser Maschine, `--body-file` ist der verlässliche Weg):

```markdown
Letztes Release aus diesem Repository. Das Projekt zieht nach
`Xveyn/Zeiterfassung` um; dieses Repo wird danach archiviert.

Der PR stellt `updater.REPO` auf den Fork um. Weil ein Fork keine Redirects
erbt, erfahren Bestandsinstallationen nur über ein Release **aus diesem Repo**
vom Umzug — daher der Weg über einen normalen Release-PR statt eines direkten
Cut-overs im Fork. Der CHANGELOG-Abschnitt ist die einzige Umzugsmeldung, die
Nutzer im Updates-Tab zu sehen bekommen.

Sonst nur Text: Repo-URLs (README-Badge, CONTRIBUTING, SECURITY, installer.iss),
Streichung der Security-Meldeadresse zugunsten der GitHub-Advisories, eigene
Copyright-Zeile in LICENSE, und vollqualifizierte Issue-Referenzen, damit `#NNN`
im Fork nicht auf dessen eigene Issues zeigt.

Bewusst unangetastet: `com.margenheld.zeiterfassung`, `AppName=Zeiterfassung`
(kein `AppId` gesetzt — daran hängt das Windows-Upgrade-in-place) und die
`assets/margenheld-icon.*`-Referenzen.

Design: `docs/superpowers/specs/2026-08-03-fork-promotion-design.md`
Plan: `docs/superpowers/plans/2026-08-03-fork-promotion.md`
```

```bash
gh pr create --repo margenheld/Zeiterfassung --base master \
  --title "chore(release): v1.22.0 — Projekt zieht nach Xveyn/Zeiterfassung um" \
  --body-file pr-body.md
```

- [ ] **Step 5: Label setzen — ohne das passiert nichts**

```bash
gh pr edit <nr> --repo margenheld/Zeiterfassung --add-label "release:minor"
```

`release.yml` triggert ausschließlich über das Label; ohne es wird der PR
gemergt, aber kein Release gebaut und kein Tag gesetzt.

- [ ] **Step 6: Nach dem Merge — Release verifizieren**

Run: `gh release view v1.22.0 --repo margenheld/Zeiterfassung`
Expected: Release existiert mit den drei Artefakten (Windows-Setup, macOS-DMG, Linux-AppImage).

---

## Danach: Handarbeit auf GitHub (kein Code)

Diese Schritte sind nicht Teil des PRs, aber ohne sie trägt die Brücke nicht.
Reihenfolge ist bindend — Details und Begründungen in Phase 4 und 5 der Spec.

- [ ] Fork-`master` auf den Stand nach dem Merge bringen **und Tag `v1.22.0` in den Fork pushen** (`git push origin v1.22.0`) — sonst findet `changelog.py` den Eintrag dieser Version im neuen Zuhause nicht mehr.
- [ ] Branch Protection auf `Xveyn/Zeiterfassung:master`, Required Check **`test`** (nicht `test-matrix` — die Matrix meldet nur Contexts mit Suffix).
- [ ] Settings → Actions → General → Workflow permissions = **„Read and write"**.
- [ ] Fork-Verknüpfung lösen („detach fork" über GitHub-Support). Bis dahin `gh pr create --repo Xveyn/Zeiterfassung` explizit angeben.
- [ ] Alt-Release-Objekte im Fork löschen (`v1.14.1`, `v1.15.0`, `v1.17.0`, `v1.17.0-pre.1`, `v1.20.0-pre.1`) — **ohne `--cleanup-tag`**, die Tags müssen bleiben.
- [ ] Erstes Fork-Release mit Version **> 1.22.0** bauen.
- [ ] Altes Repo: README und Description auf „umgezogen nach …" (Direkt-Commit), Brücken-Release stehen lassen, **Repo-Namen dauerhaft belegt halten**.
- [ ] **Erst ganz zuletzt** archivieren — read-only heißt, danach ist kein Hinweis-Release mehr möglich.

## Manuelle Verifikation nach dem Release

1. Eine Installation auf **1.21.0** öffnen → der Updates-Tab muss **1.22.0** melden, inklusive des Umzugstexts aus dem CHANGELOG.
2. 1.22.0 installieren, dann das erste Fork-Release veröffentlichen → der Updates-Tab derselben Installation muss es finden. Das ist der eigentliche Beweis, dass die Brücke trägt.
