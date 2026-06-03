# Mitwirken

Danke für dein Interesse an Zeiterfassung! Beiträge sind willkommen — egal ob
Bugfix, Feature oder Doku-Korrektur.

## Entwicklungsumgebung

```bash
git clone https://github.com/margenheld/Zeiterfassung.git
cd Zeiterfassung
pip install -r requirements.txt
python -m src.main          # App aus dem Repo starten
```

Die App **muss** als Modul gestartet werden (`python -m src.main`), nicht als
Script — die Imports innerhalb von `src/` sind absolut (`from src...`).

Voraussetzungen und plattformspezifische Hinweise (z. B. Tkinter unter Linux)
stehen im [README](README.md#aus-dem-source-code).

## Tests

```bash
pytest                                   # alle Tests
pytest tests/test_storage.py             # eine Datei
pytest tests/test_storage.py::test_name  # einzelner Test
```

`pytest` ist das Gate: **alle Tests müssen grün sein, bevor ein PR gemerged wird.**
Wer testbares Verhalten ändert (Feature wie Bugfix), schreibt einen passenden Test
mit — bei Bugfixes idealerweise erst einen Test, der den Fehler reproduziert.

## Pull Requests

1. Branch von `master` abzweigen.
2. Änderung umsetzen, Tests grün halten.
3. PR gegen `master` öffnen mit einer kurzen Beschreibung, **was** sich verhält und
   **warum**.

Nur anfassen, was die Änderung verlangt, und den vorhandenen Stil matchen. `master`
ist protected — Merge erfolgt über PR.

## Commit-Konventionen

- Commit-**Typ** englisch im Conventional-Commits-Stil: `feat:`, `fix:`, `docs:`,
  `ci:`, `refactor:` … Der Body darf deutsch sein.
- Code und Bezeichner englisch; UI-Texte und Konversation deutsch.

## Wichtige Projekt-Konventionen

- **Datumsformat:** intern **immer ISO** (`YYYY-MM-DD`, Timestamps `…THH:MM…`) für
  Storage, Filter, Sync und Payloads. In der **UI immer deutsch** (`TT.MM.JJJJ`) über
  die Helfer in `src/time_utils.py` (`format_iso_date` / `format_iso_datetime`) — nicht
  roh `isoformat()`/`str()` ausgeben.
- **Sichtbare Fehler:** Fehler im Sendepfad (Gmail, PDF) müssen per
  `messagebox.showerror` mit `traceback.format_exc()` angezeigt werden — `--noconsole`
  im Build unterdrückt sonst jede Spur.
- Weitere Details (UTF-8 in der Mail-Pipeline, Build, CI-Eigenheiten) stehen in
  [`CLAUDE.md`](CLAUDE.md).

## Releases

Releases erstellt der Maintainer über ein `release:*`-Label am gemergten PR
(siehe [`CLAUDE.md`](CLAUDE.md#release-prozess)). Als Contributor musst du dich
darum nicht kümmern — Versionsbump und Changelog übernimmt der Maintainer beim
Release-PR.

## Sicherheit

Sicherheitslücken bitte **nicht** über öffentliche Issues melden, sondern wie in
[`SECURITY.md`](SECURITY.md) beschrieben.
