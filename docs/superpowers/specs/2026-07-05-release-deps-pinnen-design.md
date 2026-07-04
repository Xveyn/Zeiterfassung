# Release-Deps pinnen (Audit M17)

> Design-Spec, 2026-07-05. Behebt Audit-Finding **M17** — `requirements.txt`
> ist überwiegend `>=`-gerangt, dadurch sind Release-Builds nicht reproduzierbar.
> Branch `fix/pin-release-deps`, unabhängig von den übrigen offenen PRs
> (berührt nur `requirements.txt` + `.github/workflows/release.yml`).

## Problem

`requirements.txt` pinnte nur `holidays==0.99` exakt; der Rest waren `>=`-Ranges
(`xhtml2pdf>=0.2.11`, `pyinstaller>=6.0.0`, `google-*>=…`, `Pillow>=10.0.0`, …).
`release.yml` installiert in allen drei Build-Jobs (Z. 124/148/180)
`pip install -r requirements.txt pyinstaller pip-licenses` — jeder Build löst also
die jeweils neueste passende Version auf. Zwei Builds **derselben** App-Version
können unterschiedliche Lib-Stände bündeln; kein Lockfile, keine Hashes. Gerade
PyInstaller und xhtml2pdf sind für Verhaltensänderungen bekannt.

Zwei Nebenbefunde in `release.yml`:
- `pyinstaller` steht **doppelt** — in `requirements.txt` *und* nochmal auf der
  Install-Zeile.
- `pip-licenses` ist **gar nicht** gepinnt.

## Entscheidung (mit dem Nutzer abgestimmt)

**Direkte Deps exakt (`==`) pinnen.** Alle direkten Abhängigkeiten in
`requirements.txt` auf known-good `==`-Versionen. Bewusst **kein** Lockfile mit
transitiven Pins und **keine** Hashes (`--require-hashes`) — das wäre pro
Plattform unterschiedlich (pyobjc nur macOS, pystray nur Win/Linux), von der
Windows-Dev-Maschine nicht voll verifizierbar und für die Projektgröße
überdimensioniert. Transitive Deps (u. a. **reportlab** via xhtml2pdf) floaten
weiter — das ist die dokumentierte Grenze dieses Ansatzes.

## Lösung

### `requirements.txt` — direkte Deps gepinnt

| Paket | vorher | nachher | requires_python |
|---|---|---|---|
| google-auth-oauthlib | `>=1.0.0` | `==1.4.0` | >=3.10 |
| google-api-python-client | `>=2.0.0` | `==2.196.0` | >=3.7 |
| xhtml2pdf | `>=0.2.11` | `==0.2.17` | >=3.8 |
| pyinstaller | `>=6.0.0` | `==6.20.0` | >=3.8,<3.15 |
| holidays | `==0.99` | `==0.99` (unverändert) | >=3.10 |
| pystray | `>=0.19.0,<0.20` | `==0.19.5` | (pure python) |
| Pillow | `>=10.0.0` | `==12.2.0` | >=3.10 |
| pyobjc-framework-Cocoa (darwin) | `>=10.0` | `==12.2.1` | >=3.10 |

Alle Versionen sind **Python-3.10-tauglich** (CI-/Release-Python; per PyPI
`requires_python` geprüft) und stammen aus der lokalen, lauffähigen `.venv`
(Test-/Build-Umgebung) bzw. dem jeweils aktuellen PyPI-Stand.

### `release.yml` — Install-Zeilen bereinigt (3×)

`pip install -r requirements.txt pyinstaller pip-licenses`
→ `pip install -r requirements.txt pip-licenses==5.5.5`

- `pyinstaller`-Dublette entfällt (kommt jetzt gepinnt aus `requirements.txt`).
- `pip-licenses==5.5.5` gepinnt (die von `build.py::_write_third_party_notices`
  genutzten Flags `--format=plain-vertical`/`--with-license-file`/… sind in 5.x
  unverändert vorhanden).

## Verifikation

- **Konflikt-Check:** `pip install --dry-run -r requirements.txt` löst sauber
  auf, keine Versionskonflikte.
- **Suite:** `pytest tests/` → 717 passed, 3 skipped.
- **YAML:** `release.yml` validiert (5 Jobs unverändert).
- **Plattform-Gate (Pflicht vor echtem Release):** Da dies die
  Dependency-Auflösung des Release-Builds ändert und macOS/Linux von der
  Windows-Dev-Maschine nicht verifizierbar sind, ist vor dem nächsten echten
  Release ein **Pre-Release** über alle drei Plattformen zu bauen
  (CLAUDE.md-Konvention „Plattformspezifische PRs → Pre-Release vorschlagen").

## Ausdrücklich außerhalb des Scopes

- **Kein** transitives Lockfile / keine Hashes (`--require-hashes`) — bewusste
  Grenze (siehe Entscheidung). `reportlab` (PDF-kritisch, via xhtml2pdf) bleibt
  ungepinnt; wäre ein möglicher Folge-PR, falls volle PDF-Reproduzierbarkeit
  gewünscht ist.
- Keine Änderung an `build.py`, `test.yml` oder Quellcode.
- Kein Versionsbump / kein `release:*`-Label (reiner Infra-Fix).
