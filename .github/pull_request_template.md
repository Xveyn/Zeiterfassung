## Was ändert sich — und warum?

<!-- Kurz das Verhalten vorher/nachher. Bei Bezug zu einem Issue: „Closes #123". -->

## Checkliste

- [ ] `pytest` lokal grün
- [ ] `ruff check .` und `pyright` ohne neue Meldungen
- [ ] Verhaltensänderung ist durch einen Test abgedeckt (bei Bugfixes: der Test reproduziert den Fehler)
- [ ] Doku mitgezogen, falls nötig (README, `CLAUDE.md`, `src/CLAUDE.md`)

## Plattform

- [ ] Die Änderung wirkt sich **nur** auf macOS und/oder Linux aus

Falls angehakt: vor dem Merge einen **Pre-Release** bauen, damit sie dort getestet
werden kann (Actions → Release → „Run workflow" mit gesetztem `prerelease`-Häkchen,
siehe [`CLAUDE.md`](../CLAUDE.md#pre-releases-plattformübergreifende-test-builds)).

<!--
Release: Versionsbump (src/version.py), CHANGELOG-Eintrag und das release:*-Label
macht der Maintainer im Release-PR — als Contributor nichts zu tun.
-->
