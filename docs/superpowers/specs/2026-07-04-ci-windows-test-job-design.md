# Windows-Test-Job in CI (Audit M15)

> Design-Spec, 2026-07-04. Behebt Audit-Finding **M15** — `test.yml` hat keinen
> Windows-Job, obwohl Windows die Primärplattform ist. Branch
> `fix/ci-windows-test-job`, unabhängig von den offenen PRs #119–#124
> (berührt nur `.github/workflows/test.yml`).

## Problem

`.github/workflows/test.yml` hat drei Jobs: `test` (ubuntu-latest, py3.10),
`test-macos` (macos-latest) und `lint` (ruff, ubuntu). **Kein Windows-Job.**
Damit läuft Windows-spezifischer Code in CI nie:

- `src/autostart.py` — winreg-HKCU-Autostart (Schreiben/Lesen/Migration)
- `src/single_instance.py` — `SO_EXCLUSIVEADDRUSE`, `os.path.normcase`-Pfadlogik

Konkret existieren Tests, die per `skipif` **nur** auf win32 laufen und in CI
folglich nie ausgeführt werden:

- `tests/test_autostart.py` — drei winreg-Tests (`platform.system() != "Windows"`)
- `tests/test_single_instance.py:23` — `normcase`-Test (`sys.platform != "win32"`)

Windows ist laut `CLAUDE.md` die Dev-Primärplattform — genau dort ist der
CI-Blindfleck am teuersten.

## Entscheidung (mit dem Nutzer abgestimmt)

**Nur M15.** Ein `test-windows`-Job, der den bestehenden ubuntu-`test`-Job
1:1 spiegelt. **M18 (Pyright-Gate) bewusst ausgeklammert** — die Pyright-Baseline
ist nicht sauber (7 `reportMissingImports` für plattform-optionale Libs
`pystray`/`AppKit`/`Foundation`, keine echten Typfehler); ein Gate bräuchte
erst eine bewusste Entscheidung zum Umgang mit plattform-optionalen Importen.
Das ist ein separates Follow-up, kein Beifang dieses PRs.

## Lösung

Ein Job, identisch zum `test`-Job außer `runs-on`:

```yaml
  test-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: '3.10'
      - run: pip install pytest "holidays==0.99" google-api-python-client google-auth google-auth-oauthlib
      - run: pytest tests/
```

Festlegungen:

- **Gleiche `pip install`-Zeile wie der ubuntu-`test`-Job** — kein `pyobjc`
  (macOS), kein `pystray` (wird in `tray.py` lazy importiert; die Tests
  monkeypatchen `platform.system`, brauchen die reale Lib nicht — der
  ubuntu-Job installiert sie auch nicht und ist grün).
- **Python 3.10** wie alle anderen Jobs — eine Version, konsistent.
- **Platzierung** direkt nach `test-macos`, vor `lint` — die drei
  Plattform-Test-Jobs bleiben zusammen.

## Verifikation

- Lokal auf Windows: `pytest tests/test_autostart.py tests/test_single_instance.py`
  → **32 passed, 1 skipped** (der 1 Skip ist der macOS-only Autostart-Test).
- Lokal die Gesamtsuite grün, damit der Windows-Job in CI nicht an einem
  unabhängigen Bruch scheitert.
- YAML-Gültigkeit von `test.yml` geprüft.

## Ausdrücklich außerhalb des Scopes

- **M18 (Pyright-Gate)** — separates Follow-up (siehe Entscheidung).
- **M16** (fehlende reale Tk-/UI-Tests) — bewusste headless-CI-Lücke, nicht Teil
  von M15.
- Keine Änderung an `test`/`test-macos`/`lint` oder an Testcode.
