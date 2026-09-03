# In-App-Update (Windows + Linux) — Implementierungsplan

> **Für agentische Worker:** ERFORDERLICHE SUB-SKILL: `superpowers:subagent-driven-development` (empfohlen) oder `superpowers:executing-plans`, um diesen Plan Aufgabe für Aufgabe umzusetzen. Schritte tragen Checkbox-Syntax (`- [ ]`) zur Nachverfolgung.

**Ziel:** Aus dem Download-Knopf wird auf Windows und Linux ein „Update installieren", das lädt, gegen `SHA256SUMS` prüft, installiert und neu startet — optional (Default aus) auch ohne Rückfrage.

**Architektur:** Ein neues Tk-freies Modul `src/self_update.py` hält alles Entscheidbare als pure Funktionen (Hash-Prüfung, Machbarkeits-Plan, Kommandokonstruktion). Windows startet ein Helfer-Skript, das auf das Prozessende wartet, `Setup.exe /SILENT` fährt und neu startet; Linux ersetzt die laufende AppImage per `os.replace` und `exec`t sich neu. macOS bleibt unverändert beim Browser-Weg.

**Tech-Stack:** Python 3.10+, stdlib only (`hashlib`, `urllib`, `subprocess`, `os`), Tkinter für die UI-Anbindung, pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-self-update-design.md`

## Globale Randbedingungen

- **Python 3.10** ist die Untergrenze (CI- und Release-Python). Keine `match`-Statements mit Struktur-Patterns, kein `X | Y` in `isinstance`.
- **Keine neuen Abhängigkeiten.** `self_update.py` ist stdlib-only, wie `updater.py` und `changelog.py`.
- **Summen nur über Minuten** ist hier nicht einschlägig; wohl aber: **Datumsformat intern ISO, in der UI deutsch** (`time_utils.format_iso_date`).
- **Tk-freie Module bekommen vollständige Annotationen** (Rückgabetyp *und* alle Parameter) und werden in `tests/test_type_annotations.py` eingetragen. `self_update.py` gehört dazu. Die UI-Schicht (`tab_updates.py`, `update_banner.py`, `ui.py`, `main.py`) bleibt unannotiert.
- **Jeder `except Exception` loggt, meldet oder trägt eine Begründung im Handler.** Durchgesetzt von `tests/test_catch_all_handlers.py` — ein nacktes `pass` lässt die Suite rot werden.
- **Fehlerdialoge:** kuratierte Meldung → `theme.themed_showerror`; Catch-all mit Traceback → rohes `tkinter.messagebox.showerror`.
- **Gerätelokale Settings** kommen **nicht** in `SYNCED_SETTING_KEYS`.
- **README-Ergänzungen für Unveröffentlichtes** tragen den Marker `*(ab 1.23.0)*`.
- **Kein Versionsbump, kein CHANGELOG, kein `release:*`-Label** in diesem PR — das gehört in den Release-PR.
- Vor jedem Commit: `pytest -q`, `ruff check .`, `npx pyright@1.1.411` müssen sauber sein.

---

### Task 1: `pick_asset_url` lernt Architekturen

Eigenständige Korrektur, auch ohne den Rest richtig. Heute bietet die App einem Intel-Mac die arm64-DMG an und einem arm64-Linux die x86_64-AppImage — beide laufen nicht.

**Files:**
- Modify: `src/updater.py:175-187`
- Modify: `src/dialogs/settings_dialog/tab_updates.py:214-218`
- Modify: `src/update_banner.py:81-91`
- Test: `tests/test_updater.py` (Klasse `TestPickAssetUrl`, ab Zeile 122)

**Interfaces:**
- Produces: `pick_asset_url(assets, system: str, latest_version: str, machine: str) -> str | None` — vierter Parameter ist `platform.machine()`; liefert `None`, wenn die Architektur nicht zum Asset passt.

- [ ] **Schritt 1: Fehlschlagende Tests schreiben**

An `tests/test_updater.py`, in der bestehenden Klasse `TestPickAssetUrl`, anhängen:

```python
    def test_intel_mac_gets_nothing(self):
        # CI baut nur arm64. Ohne Architektur-Pruefung bekaeme ein Intel-Mac
        # die arm64-DMG angeboten — sie laeuft dort nicht.
        assets = _three_assets("1.9.0")
        assert pick_asset_url(assets, "Darwin", "1.9.0", "x86_64") is None

    def test_arm_linux_gets_nothing(self):
        assets = _three_assets("1.9.0")
        assert pick_asset_url(assets, "Linux", "1.9.0", "aarch64") is None

    def test_apple_silicon_gets_the_dmg(self):
        assets = _three_assets("1.9.0")
        assert pick_asset_url(
            assets, "Darwin", "1.9.0", "arm64") == "https://example.com/dmg"

    def test_amd64_linux_gets_the_appimage(self):
        assets = _three_assets("1.9.0")
        assert pick_asset_url(
            assets, "Linux", "1.9.0", "x86_64") == "https://example.com/appimage"

    def test_windows_ignores_the_machine(self):
        # Der Setup-Name traegt keine Architektur; Windows-Builds sind x64.
        assets = _three_assets("1.9.0")
        assert pick_asset_url(
            assets, "Windows", "1.9.0", "AMD64") == "https://example.com/exe"
```

**Alle bestehenden** Tests der Klasse (aktuell sieben) bekommen den vierten Parameter passend zur Plattform: `"AMD64"` für Windows, `"arm64"` für Darwin, `"x86_64"` für Linux, `"x86_64"` für den `FreeBSD`-Fall.

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag prüfen**

Run: `python -m pytest tests/test_updater.py::TestPickAssetUrl -v`
Erwartet: FAIL — `TypeError: pick_asset_url() takes 3 positional arguments but 4 were given`

- [ ] **Schritt 3: Implementierung**

`src/updater.py`, `pick_asset_url` ersetzen:

```python
# platform.machine() liefert je nach OS verschiedene Schreibweisen fuer
# dieselbe Architektur. Nur diese Werte gelten als Treffer.
_ARM64 = {"arm64", "aarch64"}
_X86_64 = {"x86_64", "amd64"}


def pick_asset_url(assets: Any, system: str, latest_version: str,
                   machine: str) -> str | None:
    """Liefert die Download-URL für das Plattform-Asset oder None.

    `machine` ist `platform.machine()`. Die Prüfung ist nicht kosmetisch: die
    Asset-Namen tragen die Architektur fest verdrahtet (`-arm64.dmg`,
    `-x86_64.AppImage`), und weil das Release genau diese Dateien führt,
    passten die Namen vorher IMMER — ein Intel-Mac bekam die arm64-DMG
    angeboten, ein arm64-Linux die x86_64-AppImage. Beide laufen dort nicht.
    Mit dem In-App-Update wäre daraus eine automatische Fehlinstallation
    geworden, deshalb sagt die Funktion jetzt lieber None; der Aufrufer fällt
    dann auf die Release-Seite zurück.

    Windows ist ausgenommen: `Zeiterfassung_Setup.exe` trägt keine
    Architektur im Namen, und es gibt nur den x64-Build.
    """
    m = (machine or "").lower()
    if system == "Darwin" and m not in _ARM64:
        return None
    if system == "Linux" and m not in _X86_64:
        return None

    expected_name = {
        "Windows": "Zeiterfassung_Setup.exe",
        "Darwin": f"Zeiterfassung-{latest_version}-arm64.dmg",
        "Linux": f"Zeiterfassung-{latest_version}-x86_64.AppImage",
    }.get(system)
    if expected_name is None:
        return None
    for asset in assets:
        if asset.name == expected_name:
            return asset.url
    return None
```

- [ ] **Schritt 4: Aufrufer nachziehen**

`src/dialogs/settings_dialog/tab_updates.py`, Methode `_open_download`:

```python
    def _open_download(self, release):
        url = pick_asset_url(
            release.assets, platform.system(), release.version,
            platform.machine(),
        ) or release.html_url
        webbrowser.open(url)
```

`src/update_banner.py`, Methode `_open_download`: denselben vierten Parameter `platform.machine()` ergänzen. `import platform` steht dort bereits.

- [ ] **Schritt 5: Tests laufen lassen**

Run: `python -m pytest tests/test_updater.py -q` — Erwartet: alle grün
Run: `python -m pytest -q && python -m ruff check . && npx pyright@1.1.411`

- [ ] **Schritt 6: Commit**

```bash
git add src/updater.py src/dialogs/settings_dialog/tab_updates.py src/update_banner.py tests/test_updater.py
git commit -m "fix(updater): Asset-Auswahl beachtet die Architektur"
```

---

### Task 2: `self_update.py` — SHA256SUMS parsen und Datei prüfen

**Files:**
- Create: `src/self_update.py`
- Create: `tests/test_self_update.py`
- Modify: `tests/test_type_annotations.py` (Liste `ANNOTATED_MODULES`)

**Interfaces:**
- Produces:
  - `parse_sha256sums(text: str) -> dict[str, str]` — Dateiname → Hex-Digest (klein geschrieben)
  - `verify_file(path: str, expected_hex: str) -> bool`
  - `SUMS_ASSET_NAME: str` = `"SHA256SUMS"`

- [ ] **Schritt 1: Fehlschlagende Tests schreiben**

`tests/test_self_update.py` neu anlegen:

```python
"""Reine Logik des In-App-Updates (Tk-frei, ohne Netzwerk)."""

import hashlib

from src.self_update import parse_sha256sums, verify_file

# So sieht die Datei im Release wirklich aus (coreutils `sha256sum`,
# zwei Leerzeichen zwischen Digest und Name).
SUMS_FIXTURE = (
    "3f786850e387550fdab836ed7e6dc881de23001b3f786850e387550fdab836ed  "
    "Zeiterfassung_Setup.exe\n"
    "89e6c98d92887913cadf06b2adb97f26cde4849b0a3b1a4b1a4b1a4b1a4b1a4b  "
    "Zeiterfassung-1.22.0-x86_64.AppImage\n"
)


def test_parse_sha256sums_reads_name_and_digest():
    sums = parse_sha256sums(SUMS_FIXTURE)
    assert sums["Zeiterfassung_Setup.exe"] == (
        "3f786850e387550fdab836ed7e6dc881de23001b3f786850e387550fdab836ed")
    assert len(sums) == 2


def test_parse_sha256sums_ignores_blank_and_broken_lines():
    text = SUMS_FIXTURE + "\n" + "nurwas\n" + "zzz  Datei.txt\n"
    sums = parse_sha256sums(text)
    assert len(sums) == 2          # die beiden kaputten Zeilen fallen raus


def test_parse_sha256sums_handles_crlf():
    sums = parse_sha256sums(SUMS_FIXTURE.replace("\n", "\r\n"))
    assert "Zeiterfassung_Setup.exe" in sums


def test_parse_sha256sums_handles_binary_marker():
    # `sha256sum -b` schreibt " *name" statt "  name".
    text = ("3f786850e387550fdab836ed7e6dc881de23001b3f786850e387550fdab836ed"
            " *Zeiterfassung_Setup.exe\n")
    assert "Zeiterfassung_Setup.exe" in parse_sha256sums(text)


def test_parse_sha256sums_on_empty_text():
    assert parse_sha256sums("") == {}


def test_verify_file_accepts_the_matching_digest(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hallo welt")
    assert verify_file(str(f), hashlib.sha256(b"hallo welt").hexdigest())


def test_verify_file_rejects_a_different_digest(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hallo welt")
    assert not verify_file(str(f), hashlib.sha256(b"etwas anderes").hexdigest())


def test_verify_file_is_case_insensitive_about_the_digest(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hallo welt")
    assert verify_file(str(f), hashlib.sha256(b"hallo welt").hexdigest().upper())


def test_verify_file_on_missing_file_is_false(tmp_path):
    assert not verify_file(str(tmp_path / "gibtsnicht.bin"), "00" * 32)
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag prüfen**

Run: `python -m pytest tests/test_self_update.py -q`
Erwartet: FAIL — `ModuleNotFoundError: No module named 'src.self_update'`

- [ ] **Schritt 3: Implementierung**

`src/self_update.py` neu anlegen:

```python
"""In-App-Update für Windows und Linux: reine Logik, Tk-frei, stdlib-only.

Die App lädt das Plattform-Asset selbst, prüft es gegen den `SHA256SUMS` des
Releases und installiert es. macOS ist bewusst NICHT dabei — das Bundle ist
weder signiert noch notarisiert, und der Weg über DMG-Mount und
`/Applications` ist auf der Windows-Entwicklungsmaschine nicht verifizierbar
(s. `docs/known-limitations.md`).

**Was die Hash-Prüfung leistet und was nicht.** `SHA256SUMS` schützt gegen
abgebrochene und verfälschte Übertragung. Es schützt NICHT gegen ein
kompromittiertes Release: die Datei ist selbst unsigniert und liegt neben den
Assets, die sie beschreibt. Vertrauensanker bleibt TLS zu GitHub — derselbe
wie beim manuellen Download im Browser. Das löst den Audit-Vermerk M9 ein
(„ein In-App-Auto-Download OHNE Verifikation wäre eine echte Lücke"), ohne
mehr zu behaupten, als es trägt.
"""
from __future__ import annotations

import hashlib

# Name des Prüfsummen-Assets, das `release.yml` jedem Release beilegt.
SUMS_ASSET_NAME = "SHA256SUMS"

_HEX = set("0123456789abcdef")
_CHUNK_BYTES = 1024 * 1024


def parse_sha256sums(text: str) -> dict[str, str]:
    """`SHA256SUMS`-Text → {Dateiname: Hex-Digest}.

    Format ist das von coreutils `sha256sum`: `<digest>  <name>` (zwei
    Leerzeichen) bzw. `<digest> *<name>` im Binärmodus. Unbrauchbare Zeilen
    werden übersprungen statt zu werfen — eine kaputte Zeile darf den Rest
    der Datei nicht entwerten.
    """
    result: dict[str, str] = {}
    for raw in text.splitlines():
        parts = raw.strip().split(None, 1)
        if len(parts) != 2:
            continue
        digest = parts[0].lower()
        if len(digest) != 64 or not set(digest) <= _HEX:
            continue
        result[parts[1].strip().lstrip("*")] = digest
    return result


def verify_file(path: str, expected_hex: str) -> bool:
    """True, wenn die Datei den erwarteten SHA256 hat.

    Blockweise gelesen: die AppImage ist ~65 MB und hat im Speicher nichts zu
    suchen. Ein Lesefehler ist ein Prüf-Fehlschlag, kein Ausnahmefall — der
    Aufrufer behandelt beides gleich (Datei löschen, Update abbrechen).
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == (expected_hex or "").lower()
```

- [ ] **Schritt 4: Tests laufen lassen**

Run: `python -m pytest tests/test_self_update.py -q` — Erwartet: 9 passed

- [ ] **Schritt 5: Modul in die Annotations-Whitelist**

In `tests/test_type_annotations.py`, Liste `ANNOTATED_MODULES`, nach `"src/report.py"` ergänzen:

```python
    "src/self_update.py",
```

Run: `python -m pytest tests/test_type_annotations.py -q` — Erwartet: grün

- [ ] **Schritt 6: Commit**

```bash
git add src/self_update.py tests/test_self_update.py tests/test_type_annotations.py
git commit -m "feat(self-update): SHA256SUMS parsen und Dateien verifizieren"
```

---

### Task 3: Machbarkeits-Plan — `supports_self_update` und `plan_update`

Die eine Stelle, die entscheidet, ob ein Selbst-Update losgehen kann — und bei „nein" einen anzeigbaren Grund nennt.

**Files:**
- Modify: `src/self_update.py`
- Modify: `tests/test_self_update.py`

**Interfaces:**
- Produces:
  - `supports_self_update(system: str, frozen: bool) -> bool`
  - `UpdatePlan` (frozen dataclass): `asset_url: str`, `asset_name: str`, `sums_url: str`, `target: str`
  - `UpdateBlocked` (frozen dataclass): `reason: str`
  - `plan_update(release: Any, system: str, machine: str, frozen: bool, appimage: str, executable: str) -> UpdatePlan | UpdateBlocked`

**Abweichung von der Spec, bewusst:** `supports_self_update` bekommt **kein** `machine`. Die Architektur prüft bereits `pick_asset_url` (Task 1); sie hier zu wiederholen wäre eine zweite Stelle, die mit den Asset-Namen synchron gehalten werden müsste. Passt die Architektur nicht, liefert `pick_asset_url` `None` und `plan_update` blockt mit genau diesem Grund.

- [ ] **Schritt 1: Fehlschlagende Tests schreiben**

An `tests/test_self_update.py` anhängen:

```python
import pytest

from src.self_update import (
    UpdateBlocked, UpdatePlan, plan_update, supports_self_update,
)
from src.updater import Asset, Release


def _release(version="1.23.0", with_sums=True):
    assets = [
        Asset(name="Zeiterfassung_Setup.exe", url="https://x/exe"),
        Asset(name=f"Zeiterfassung-{version}-x86_64.AppImage", url="https://x/img"),
        Asset(name=f"Zeiterfassung-{version}-arm64.dmg", url="https://x/dmg"),
    ]
    if with_sums:
        assets.append(Asset(name="SHA256SUMS", url="https://x/sums"))
    return Release(version=version, html_url="https://x/rel", assets=tuple(assets))


@pytest.mark.parametrize("system,frozen,expected", [
    ("Windows", True, True),
    ("Linux", True, True),
    ("Darwin", True, False),     # bewusst nicht unterstuetzt
    ("Windows", False, False),   # Repo-Modus: nichts zu ersetzen
    ("Linux", False, False),
    ("FreeBSD", True, False),
])
def test_supports_self_update(system, frozen, expected):
    assert supports_self_update(system, frozen) is expected


def test_plan_update_on_windows_yields_setup_and_sums():
    plan = plan_update(_release(), "Windows", "AMD64", True, "",
                       r"C:\Apps\Zeiterfassung\Zeiterfassung.exe")
    assert isinstance(plan, UpdatePlan)
    assert plan.asset_name == "Zeiterfassung_Setup.exe"
    assert plan.asset_url == "https://x/exe"
    assert plan.sums_url == "https://x/sums"
    assert plan.target == r"C:\Apps\Zeiterfassung\Zeiterfassung.exe"


def test_plan_update_on_linux_targets_the_appimage():
    plan = plan_update(_release(), "Linux", "x86_64", True,
                       "/home/u/Apps/Zeiterfassung.AppImage", "/tmp/whatever")
    assert isinstance(plan, UpdatePlan)
    assert plan.asset_name == "Zeiterfassung-1.23.0-x86_64.AppImage"
    assert plan.target == "/home/u/Apps/Zeiterfassung.AppImage"


def test_plan_update_blocks_on_macos():
    blocked = plan_update(_release(), "Darwin", "arm64", True, "", "/A/Z.app")
    assert isinstance(blocked, UpdateBlocked)
    assert "macOS" in blocked.reason


def test_plan_update_blocks_in_repo_mode():
    blocked = plan_update(_release(), "Windows", "AMD64", False, "", "python.exe")
    assert isinstance(blocked, UpdateBlocked)


def test_plan_update_blocks_when_architecture_does_not_match():
    blocked = plan_update(_release(), "Linux", "aarch64", True,
                          "/home/u/Z.AppImage", "/tmp/x")
    assert isinstance(blocked, UpdateBlocked)
    assert "Architektur" in blocked.reason


def test_plan_update_blocks_without_a_sums_asset():
    blocked = plan_update(_release(with_sums=False), "Windows", "AMD64", True,
                          "", r"C:\Apps\Z.exe")
    assert isinstance(blocked, UpdateBlocked)
    assert "Prüfsumme" in blocked.reason


def test_plan_update_blocks_on_linux_without_appimage_env():
    # Die nackte PyInstaller-Ausgabe hat $APPIMAGE nicht.
    blocked = plan_update(_release(), "Linux", "x86_64", True, "", "/tmp/x")
    assert isinstance(blocked, UpdateBlocked)
    assert "AppImage" in blocked.reason
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag prüfen**

Run: `python -m pytest tests/test_self_update.py -q`
Erwartet: FAIL — `ImportError: cannot import name 'plan_update'`

- [ ] **Schritt 3: Implementierung**

An `src/self_update.py` anhängen. Oben ergänzen: `from dataclasses import dataclass`, `from typing import Any` und `from src.updater import pick_asset_url` — ein Import-Zyklus entsteht dadurch **nicht**, `updater.py` importiert `self_update` seinerseits nicht.

```python
@dataclass(frozen=True)
class UpdatePlan:
    """Alles, was der Ablauf braucht — ermittelt, bevor ein Byte fließt."""

    asset_url: str
    asset_name: str
    sums_url: str
    target: str     # Linux: $APPIMAGE; Windows: Pfad der laufenden Exe


@dataclass(frozen=True)
class UpdateBlocked:
    """Warum es NICHT losgehen kann — `reason` ist anzeigbarer Text."""

    reason: str


def supports_self_update(system: str, frozen: bool) -> bool:
    """Kann sich die App auf dieser Plattform selbst aktualisieren?

    Nur Windows und Linux, und nur im Frozen-Build: im Repo-Modus gibt es
    keine installierte Datei, die man ersetzen könnte, und `python -m
    src.main` aktualisiert man über git.
    """
    return bool(frozen) and system in ("Windows", "Linux")


def plan_update(release: Any, system: str, machine: str, frozen: bool,
                appimage: str, executable: str) -> "UpdatePlan | UpdateBlocked":
    """Prüft alle Voraussetzungen und liefert entweder den Plan oder den Grund.

    Bewusst EINE Stelle: jeder Abbruchgrund wird hier festgestellt, bevor
    heruntergeladen wird — ein halb geladenes Update, das dann an einer
    Kleinigkeit scheitert, wäre die schlechtere Erfahrung.

    `appimage` ist `$APPIMAGE` (nur Linux relevant), `executable` ist
    `sys.executable`.
    """
    if not supports_self_update(system, frozen):
        if system == "Darwin":
            return UpdateBlocked(
                "Unter macOS lädt die App das Update nicht selbst — "
                "der Download öffnet sich im Browser.")
        return UpdateBlocked(
            "Das Update aus der App heraus gibt es nur in der installierten "
            "Version.")

    asset_url = pick_asset_url(release.assets, system, release.version, machine)
    if asset_url is None:
        return UpdateBlocked(
            "Für die Architektur dieses Rechners gibt es in diesem Release "
            "keine passende Datei.")

    sums_url = next(
        (a.url for a in release.assets if a.name == SUMS_ASSET_NAME), None)
    if sums_url is None:
        return UpdateBlocked(
            "Dieses Release enthält keine Prüfsummen-Datei — die App "
            "installiert nur, was sie prüfen kann.")

    if system == "Linux":
        if not appimage:
            return UpdateBlocked(
                "Der Pfad der laufenden AppImage ist unbekannt "
                "($APPIMAGE nicht gesetzt).")
        target = appimage
    else:
        target = executable

    asset_name = {
        "Windows": "Zeiterfassung_Setup.exe",
        "Linux": f"Zeiterfassung-{release.version}-x86_64.AppImage",
    }[system]
    return UpdatePlan(asset_url=asset_url, asset_name=asset_name,
                      sums_url=sums_url, target=target)
```

- [ ] **Schritt 4: Tests laufen lassen**

Run: `python -m pytest tests/test_self_update.py -q` — Erwartet: alle grün
Run: `python -m pytest -q && python -m ruff check . && npx pyright@1.1.411`

- [ ] **Schritt 5: Commit**

```bash
git add src/self_update.py tests/test_self_update.py
git commit -m "feat(self-update): Machbarkeits-Plan mit Begruendung je Abbruch"
```

---

### Task 4: Download mit Fortschritt

**Files:**
- Modify: `src/self_update.py`
- Modify: `tests/test_self_update.py`

**Interfaces:**
- Produces:
  - `download_to(url: str, dest: str, on_progress: Callable[[int, int], None] | None = None, timeout: float = 30.0) -> bool`
  - `fetch_text(url: str, timeout: float = 15.0) -> str | None`

- [ ] **Schritt 1: Fehlschlagende Tests schreiben**

```python
from unittest.mock import patch


class _FakeResponse:
    def __init__(self, payload, length=None):
        self._payload = payload
        self._pos = 0
        self.headers = {"Content-Length": str(length if length is not None
                                              else len(payload))}

    def read(self, size):
        chunk = self._payload[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_to_writes_the_payload(tmp_path):
    from src.self_update import download_to
    dest = tmp_path / "out.bin"
    with patch("src.self_update.urlopen", return_value=_FakeResponse(b"x" * 5000)):
        assert download_to("https://x/f", str(dest)) is True
    assert dest.read_bytes() == b"x" * 5000


def test_download_to_reports_progress(tmp_path):
    from src.self_update import download_to
    seen = []
    with patch("src.self_update.urlopen", return_value=_FakeResponse(b"y" * 3000)):
        download_to("https://x/f", str(tmp_path / "o.bin"),
                    on_progress=lambda done, total: seen.append((done, total)))
    assert seen, "es muss mindestens einmal gemeldet werden"
    assert seen[-1] == (3000, 3000)


def test_download_to_removes_the_partial_file_on_error(tmp_path):
    from src.self_update import download_to
    import urllib.error
    dest = tmp_path / "out.bin"
    with patch("src.self_update.urlopen",
               side_effect=urllib.error.URLError("weg")):
        assert download_to("https://x/f", str(dest)) is False
    assert not dest.exists(), "eine halbe Datei darf nicht liegenbleiben"


def test_fetch_text_returns_none_on_error():
    from src.self_update import fetch_text
    import urllib.error
    with patch("src.self_update.urlopen",
               side_effect=urllib.error.URLError("weg")):
        assert fetch_text("https://x/sums") is None
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag prüfen**

Run: `python -m pytest tests/test_self_update.py -k "download_to or fetch_text" -v`
Erwartet: FAIL — `ImportError: cannot import name 'download_to'`

- [ ] **Schritt 3: Implementierung**

Oben in `src/self_update.py` ergänzen:

```python
import os
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.version import VERSION
```

und anhängen:

```python
def _request(url: str) -> Request:
    return Request(url, headers={"User-Agent": f"Zeiterfassung/{VERSION}"})


def fetch_text(url: str, timeout: float = 15.0) -> str | None:
    """Kleine Textdatei laden (die Prüfsummen). None bei jedem Fehler —
    nie eine Exception nach außen, analog `updater.check_latest_release`."""
    try:
        with urlopen(_request(url), timeout=timeout) as response:
            return response.read().decode("utf-8")
    except (URLError, OSError, UnicodeDecodeError):
        return None


def download_to(url: str, dest: str,
                on_progress: Callable[[int, int], None] | None = None,
                timeout: float = 30.0) -> bool:
    """Lädt `url` nach `dest`. True bei Erfolg.

    `on_progress(geladen, gesamt)` wird je Block gerufen; `gesamt` ist 0, wenn
    der Server keine Content-Length schickt. Der Callback läuft im
    Worker-Thread — Aufrufer marshallen selbst auf den UI-Thread.

    Bei JEDEM Fehler wird die angefangene Datei entfernt: eine halbe
    Setup.exe, die liegen bleibt, würde beim nächsten Versuch als fertig
    missverstanden oder vom Nutzer gefunden und ausgeführt.
    """
    try:
        with urlopen(_request(url), timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(dest, "wb") as handle:
                while True:
                    chunk = response.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        on_progress(done, total)
        return True
    except (URLError, OSError) as exc:
        log.warning("Update-Download fehlgeschlagen: %s", exc)
        try:
            os.remove(dest)
        except OSError:
            pass  # nichts angelegt oder schon weg — beides in Ordnung
        return False
```

Dazu oben `import logging` und `log = logging.getLogger(__name__)` ergänzen.

- [ ] **Schritt 4: Tests laufen lassen**

Run: `python -m pytest tests/test_self_update.py -q` — Erwartet: alle grün

- [ ] **Schritt 5: Commit**

```bash
git add src/self_update.py tests/test_self_update.py
git commit -m "feat(self-update): Download mit Fortschritt und Aufraeumen"
```

---

### Task 5: Windows anwenden — Helfer-Skript

**Files:**
- Modify: `src/self_update.py`
- Modify: `tests/test_self_update.py`

**Interfaces:**
- Produces:
  - `windows_helper_script(pid: int, setup_path: str, exe_path: str, log_path: str) -> str`
  - `apply_windows(exe_path: str, setup_path: str, pid: int) -> bool`

**Warum ein Helfer:** `installer.iss` setzt `AppMutex=ZeiterfassungAppMutex` und `CloseApplications=no`. Läuft die App noch, wenn Inno den Mutex prüft, bricht der Installer ab bzw. fragt nach. Und der `[Run]`-Eintrag trägt `skipifsilent`, startet die App nach einem stillen Lauf also **nicht**. Beides erledigt das Skript — `installer.iss` bleibt unangetastet.

- [ ] **Schritt 1: Fehlschlagende Tests schreiben**

```python
def test_windows_helper_script_quotes_every_path():
    from src.self_update import windows_helper_script
    script = windows_helper_script(
        4711,
        r"C:\Temp\Zeiterfassung_Setup.exe",
        r"D:\Programme (x86)\Zeiterfassung\Zeiterfassung.exe",
        r"C:\Temp\update.log")
    # Pfade mit Leerzeichen und Klammern sind hier der NORMALFALL.
    assert '"D:\\Programme (x86)\\Zeiterfassung\\Zeiterfassung.exe"' in script
    assert '"C:\\Temp\\Zeiterfassung_Setup.exe"' in script
    assert "4711" in script


def test_windows_helper_script_waits_then_installs_then_starts():
    from src.self_update import windows_helper_script
    script = windows_helper_script(1, "s.exe", "z.exe", "l.log")
    wait_at = script.index("tasklist")
    install_at = script.index("/SILENT")
    start_at = script.rindex("start ")
    assert wait_at < install_at < start_at, "Reihenfolge ist der ganze Punkt"


def test_windows_helper_script_uses_neither_verysilent_nor_suppressmsgboxes():
    from src.self_update import windows_helper_script
    script = windows_helper_script(1, "s.exe", "z.exe", "l.log")
    assert "/SILENT" in script
    assert "/VERYSILENT" not in script       # Fortschritt soll sichtbar sein
    assert "/SUPPRESSMSGBOXES" not in script  # echte Fehler sollen auffallen
    assert "/SMS" not in script               # nicht mehr dokumentiert


def test_windows_helper_script_has_a_wait_timeout():
    from src.self_update import windows_helper_script
    script = windows_helper_script(1, "s.exe", "z.exe", "l.log")
    # Ohne Obergrenze liefe der Helfer ewig, falls die PID nie verschwindet.
    assert "TRIES" in script
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag prüfen**

Run: `python -m pytest tests/test_self_update.py -k windows_helper -v`
Erwartet: FAIL — `ImportError: cannot import name 'windows_helper_script'`

- [ ] **Schritt 3: Implementierung**

```python
# Wie lange der Helfer auf das Ende der App wartet, bevor er aufgibt.
# 60 x 1 s: grosszuegig genug fuer einen langsamen Sync-Push beim Beenden,
# kurz genug, dass ein haengender Prozess den Nutzer nicht ewig blockiert.
_WAIT_TRIES = 60


def windows_helper_script(pid: int, setup_path: str, exe_path: str,
                          log_path: str) -> str:
    """Das Batch-Skript, das die App nach dem Beenden aktualisiert.

    Drei Schritte, und die Reihenfolge ist der ganze Punkt:
      1. warten, bis die App-PID verschwunden ist (sonst blockt `AppMutex`
         den Installer)
      2. `Setup.exe /SILENT /NORESTART` — bewusst OHNE `/VERYSILENT` (das
         Fortschrittsfenster ist das einzige Signal, dass etwas passiert) und
         OHNE `/SUPPRESSMSGBOXES` (macht „Abort" zur Standardantwort und
         verschluckte echte Fehler)
      3. die App wieder starten — der `[Run]`-Eintrag in `installer.iss`
         trägt `skipifsilent` und feuert im stillen Lauf nicht

    Der Exit-Code des Installers landet im Log neben der App: scheitert der
    Lauf, ist das die einzige Spur. Gestartet wird die App danach in JEDEM
    Fall — auch nach einem Fehlschlag ist eine laufende alte Version besser
    als gar keine.

    Alle Pfade sind gequotet: `D:\\Programme (x86)\\…` ist hier der Normalfall.
    """
    return "\n".join([
        "@echo off",
        "setlocal",
        f"set TRIES={_WAIT_TRIES}",
        ":wait",
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul',
        "if errorlevel 1 goto install",
        "set /a TRIES-=1",
        "if %TRIES% LEQ 0 goto install",
        "timeout /t 1 /nobreak >nul",
        "goto wait",
        ":install",
        f'"{setup_path}" /SILENT /NORESTART',
        f'echo Installer beendet mit %ERRORLEVEL% > "{log_path}"',
        f'start "" "{exe_path}"',
        f'del "{setup_path}" >nul 2>&1',
        "",
    ])


def apply_windows(exe_path: str, setup_path: str, pid: int) -> bool:
    """Schreibt den Helfer nach %TEMP% und startet ihn abgekoppelt.

    Der Aufrufer beendet die App unmittelbar danach — der Helfer wartet auf
    genau dieses Ende. `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`
    entkoppelt ihn, damit er das Ende der App überlebt; `CREATE_NO_WINDOW`
    hält das Konsolenfenster unsichtbar.
    """
    import subprocess
    import tempfile

    log_path = os.path.join(os.path.dirname(exe_path), "update.log")
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".cmd", delete=False, encoding="ascii", errors="replace")
    try:
        with handle:
            handle.write(windows_helper_script(
                pid, setup_path, exe_path, log_path))
        subprocess.Popen(
            ["cmd", "/c", handle.name],
            creationflags=(0x00000008 |   # DETACHED_PROCESS
                           0x00000200 |   # CREATE_NEW_PROCESS_GROUP
                           0x08000000),   # CREATE_NO_WINDOW
            close_fds=True)
        return True
    except OSError as exc:
        log.warning("Update-Helfer konnte nicht gestartet werden: %s", exc)
        return False
```

- [ ] **Schritt 4: Tests laufen lassen**

Run: `python -m pytest tests/test_self_update.py -q` — Erwartet: alle grün

- [ ] **Schritt 5: Commit**

```bash
git add src/self_update.py tests/test_self_update.py
git commit -m "feat(self-update): Windows-Helfer wartet, installiert, startet neu"
```

---

### Task 6: Linux anwenden — AppImage ersetzen und `.old` aufräumen

**Files:**
- Modify: `src/self_update.py`
- Modify: `src/main.py:153-168` (Funktion `_refresh_linux_integration`)
- Modify: `tests/test_self_update.py`

**Interfaces:**
- Produces:
  - `linux_apply_paths(appimage: str) -> tuple[str, str]` — `(temp_pfad, backup_pfad)`
  - `apply_linux(appimage: str, downloaded: str) -> str | None` — `None` bei Erfolg, sonst Fehlertext
  - `sweep_appimage_backup(appimage: str) -> bool`

- [ ] **Schritt 1: Fehlschlagende Tests schreiben**

```python
def test_linux_apply_paths_are_siblings_of_the_appimage():
    from src.self_update import linux_apply_paths
    tmp, backup = linux_apply_paths("/home/u/Apps/Zeiterfassung.AppImage")
    assert tmp.startswith("/home/u/Apps/")
    assert backup == "/home/u/Apps/Zeiterfassung.AppImage.old"
    assert tmp != backup


def test_apply_linux_replaces_the_file_and_keeps_a_backup(tmp_path):
    from src.self_update import apply_linux
    target = tmp_path / "Zeiterfassung.AppImage"
    target.write_bytes(b"alt")
    neu = tmp_path / "geladen.tmp"
    neu.write_bytes(b"neu")

    assert apply_linux(str(target), str(neu)) is None
    assert target.read_bytes() == b"neu"
    assert (tmp_path / "Zeiterfassung.AppImage.old").read_bytes() == b"alt"


def test_apply_linux_makes_the_new_file_executable(tmp_path):
    import os as _os
    import stat
    from src.self_update import apply_linux
    target = tmp_path / "Z.AppImage"
    target.write_bytes(b"alt")
    neu = tmp_path / "n.tmp"
    neu.write_bytes(b"neu")
    apply_linux(str(target), str(neu))
    assert _os.stat(str(target)).st_mode & stat.S_IXUSR


def test_apply_linux_restores_the_backup_when_replacing_fails(tmp_path):
    import os as _os
    from unittest.mock import patch
    from src.self_update import apply_linux
    target = tmp_path / "Z.AppImage"
    target.write_bytes(b"alt")
    neu = tmp_path / "n.tmp"
    neu.write_bytes(b"neu")

    # NUR der zweite os.replace scheitert. `os.replace` global zu werfen waere
    # zweierlei falsch: schon die Sicherung schluege fehl (die Funktion kaeme
    # nie zum Rollback), und weil die Dateien sich unter einem Mock gar nicht
    # bewegen, wuerde die Schluss-Assertion ohnehin nur die Ausgangslage
    # bestaetigen. Deshalb echte Aufrufe, mit einer gezielten Ausnahme.
    real_replace = _os.replace
    calls = []

    def flaky(src, dst):
        calls.append((src, dst))
        if len(calls) == 2:          # das Einsetzen der neuen Datei
            raise OSError("kein Platz")
        return real_replace(src, dst)

    with patch("src.self_update.os.replace", side_effect=flaky):
        error = apply_linux(str(target), str(neu))

    assert error is not None
    assert len(calls) == 3, "sichern, einsetzen (faellt), zurueckrollen"
    assert target.read_bytes() == b"alt", "die alte Datei muss zurueck sein"
    assert not (tmp_path / "Z.AppImage.old").exists()


def test_sweep_appimage_backup_removes_a_leftover(tmp_path):
    from src.self_update import sweep_appimage_backup
    target = tmp_path / "Z.AppImage"
    target.write_bytes(b"neu")
    (tmp_path / "Z.AppImage.old").write_bytes(b"alt")
    assert sweep_appimage_backup(str(target)) is True
    assert not (tmp_path / "Z.AppImage.old").exists()


def test_sweep_appimage_backup_without_a_leftover_is_false(tmp_path):
    from src.self_update import sweep_appimage_backup
    target = tmp_path / "Z.AppImage"
    target.write_bytes(b"neu")
    assert sweep_appimage_backup(str(target)) is False
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag prüfen**

Run: `python -m pytest tests/test_self_update.py -k "linux or sweep" -v`
Erwartet: FAIL — `ImportError: cannot import name 'linux_apply_paths'`

- [ ] **Schritt 3: Implementierung**

```python
_BACKUP_SUFFIX = ".old"


def linux_apply_paths(appimage: str) -> tuple[str, str]:
    """(Temp-Pfad für den Download, Backup-Pfad der laufenden Datei).

    Beide liegen NEBEN der AppImage, nicht in /tmp: `os.replace` ist nur
    innerhalb desselben Dateisystems atomar, und /tmp ist auf vielen Systemen
    ein eigenes (tmpfs).
    """
    directory = os.path.dirname(appimage) or "."
    name = os.path.basename(appimage)
    return (os.path.join(directory, f".{name}.update-{os.getpid()}"),
            appimage + _BACKUP_SUFFIX)


def apply_linux(appimage: str, downloaded: str) -> str | None:
    """Ersetzt die laufende AppImage durch die geladene Datei.

    None bei Erfolg, sonst ein anzeigbarer Fehlertext.

    Die laufende AppImage im Betrieb zu ersetzen ist der VORGESEHENE Weg —
    genau so arbeitet AppImageUpdate. Der Inode der gemounteten Datei bleibt
    bis zum Prozessende gültig, der laufende Prozess merkt nichts.

    Die alte Datei bleibt als `<name>.old` liegen: sie ist der Rollback, falls
    die neue Version gar nicht startet. Aufgeräumt wird sie beim nächsten
    erfolgreichen Start (`sweep_appimage_backup`, gerufen aus `main.py`) —
    dieselbe Idee wie AppImages `.zs-old`.
    """
    import stat

    _tmp, backup = linux_apply_paths(appimage)
    try:
        mode = os.stat(downloaded).st_mode
        os.chmod(downloaded, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as exc:
        return f"Die geladene Datei ließ sich nicht ausführbar machen: {exc}"

    try:
        os.replace(appimage, backup)
    except OSError as exc:
        return f"Die alte AppImage ließ sich nicht sichern: {exc}"

    try:
        os.replace(downloaded, appimage)
    except OSError as exc:
        try:
            os.replace(backup, appimage)
        except OSError:
            log.exception("Rollback der AppImage fehlgeschlagen")
        return f"Die neue AppImage ließ sich nicht einsetzen: {exc}"
    return None


def sweep_appimage_backup(appimage: str) -> bool:
    """Räumt ein `<name>.old` neben der laufenden AppImage weg. True, wenn
    etwas entfernt wurde.

    Läuft beim Start: dass dieser Prozess überhaupt so weit gekommen ist, IST
    der Beweis, dass die neue Datei startet — der Rollback wird nicht mehr
    gebraucht.
    """
    backup = appimage + _BACKUP_SUFFIX
    try:
        os.remove(backup)
        return True
    except OSError:
        return False
```

- [ ] **Schritt 4: Aufräumen beim Start verdrahten**

`src/main.py`, Funktion `_refresh_linux_integration` — Docstring korrigieren (ihre Prämisse kippt mit diesem Feature) und den Sweep ergänzen:

```python
def _refresh_linux_integration(base):
    """Linux-Desktop-Integration beim Start nachziehen (best-effort).

    Zwei Selbstheilungen mit derselben Ursache: wer die AppImage von Hand
    herunterlädt, bekommt eine Datei mit der Version im Namen — Menüeintrag
    und Autostart zeigten sonst auf die alte. (Das In-App-Update ersetzt
    dagegen `$APPIMAGE` an Ort und Stelle, dort ändert sich der Pfad nicht.)

    Dazu wird ein `<name>.old` weggeräumt, das das In-App-Update als Rollback
    hinterlassen hat: dass dieser Prozess läuft, IST der Beweis, dass die neue
    Datei startet.

    Fehler sind hier NIE fatal — ein nicht geschriebener Menüeintrag ist der
    Status quo, ein verhinderter Start wäre eine Regression (Muster wie beim
    Logging-Setup in main()).
    """
    try:
        refresh_linux_target(base)
    except Exception:
        logging.getLogger(__name__).warning(
            "Autostart-Pfad konnte nicht nachgezogen werden", exc_info=True)

    if platform.system() != "Linux" or not getattr(sys, "frozen", False):
        return
    appimage = os.environ.get("APPIMAGE")
    if not appimage:
        return

    from src.self_update import sweep_appimage_backup
    if sweep_appimage_backup(appimage):
        logging.getLogger(__name__).info(
            "Rollback-Datei des letzten Updates entfernt")

    try:
        write_menu_entry(appimage, ensure_icon(get_resource_path(), base))
    except Exception:
        logging.getLogger(__name__).warning(
            "Menüeintrag konnte nicht geschrieben werden", exc_info=True)
```

- [ ] **Schritt 5: Tests laufen lassen**

Run: `python -m pytest -q && python -m ruff check . && npx pyright@1.1.411`

- [ ] **Schritt 6: Commit**

```bash
git add src/self_update.py src/main.py tests/test_self_update.py
git commit -m "feat(self-update): AppImage ersetzen mit Rollback und Aufraeumen"
```

---

### Task 7: Updates-Tab — der Ein-Klick-Ablauf

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_updates.py`

**Interfaces:**
- Consumes: `self_update.plan_update`, `download_to`, `fetch_text`, `parse_sha256sums`, `verify_file`, `apply_windows`, `apply_linux`, `supports_self_update`; `UpdatePlan`/`UpdateBlocked`

**Kein neuer Test:** Der Tab ist Tk-gebunden — die dokumentierte M16-Grenze. Alles Entscheidbare liegt in den Tasks 2–6 und ist dort getestet.

- [ ] **Schritt 1: Knopfbeschriftung plattformabhängig**

In `__init__`, bei der Erzeugung von `self._download_btn` (Zeile ~61), den Text aus einer Konstanten ziehen und oben im Modul definieren:

```python
# Der Knopf heisst nur dort "Update installieren", wo die App das auch kann.
# Sonst bleibt es beim bisherigen Browser-Download.
_LABEL_INSTALL = "Update installieren"
_LABEL_DOWNLOAD = "Download"
```

```python
        self._can_self_update = supports_self_update(
            platform.system(), getattr(sys, "frozen", False))
        self._download_btn = secondary_button(
            btn_frame,
            _LABEL_INSTALL if self._can_self_update else _LABEL_DOWNLOAD,
            self._open_latest_download,
        )
```

`import sys` und `from src.self_update import supports_self_update` oben ergänzen.

- [ ] **Schritt 2: `_open_latest_download` verzweigen**

```python
    def _open_latest_download(self):
        # `set_secondary_button_enabled` graut den Knopf nur optisch aus, die
        # Bindung feuert weiter (s. dessen Docstring) — der Guard hier ist
        # das, was einen zweiten Klick waehrend des Downloads wirklich stoppt.
        if self._latest_release is None or self._updating:
            return
        if self._can_self_update:
            self._start_self_update(self._latest_release)
            return
        self._open_download(self._latest_release)
```

- [ ] **Schritt 3: Den Ablauf implementieren**

```python
    def _start_self_update(self, release):
        """Laden, pruefen, installieren — der Ein-Klick-Weg.

        Reihenfolge mit Absicht: `plan_update` stellt ALLE Abbruchgruende
        fest, bevor ein Byte fliesst. Ein halb geladenes Update, das dann an
        einer Kleinigkeit scheitert, waere die schlechtere Erfahrung.
        """
        plan = plan_update(
            release, platform.system(), platform.machine(),
            getattr(sys, "frozen", False),
            os.environ.get("APPIMAGE", ""), sys.executable)
        if isinstance(plan, UpdateBlocked):
            themed_showerror(self.frame, "Update nicht möglich", plan.reason)
            self._open_download(release)
            return

        set_primary_button_enabled(self._check_btn, False)
        # ACHTUNG: `set_secondary_button_enabled` aendert laut seinem Docstring
        # NUR die Optik — die Klick-Bindung bleibt aktiv. Der Callback muss
        # deshalb selbst ein No-op machen, siehe `self._updating`-Guard oben in
        # `_open_latest_download`.
        set_secondary_button_enabled(self._download_btn, False)
        self._updating = True

        if platform.system() == "Windows":
            local = os.path.join(tempfile.gettempdir(), plan.asset_name)
        else:
            # NEBEN die AppImage, nicht nach /tmp: `os.replace` ist nur
            # innerhalb desselben Dateisystems atomar, und /tmp ist auf vielen
            # Systemen ein eigenes (tmpfs).
            local = linux_apply_paths(plan.target)[0]

        def report(text):
            # Aus dem Worker-Thread: nie direkt ans Widget.
            self.frame.after(0, lambda: self._status_label.config(text=text))

        def work():
            sums_text = fetch_text(plan.sums_url)
            if sums_text is None:
                return "Die Prüfsummen ließen sich nicht laden."
            expected = parse_sha256sums(sums_text).get(plan.asset_name)
            if not expected:
                return "Für diese Datei steht keine Prüfsumme im Release."

            def progress(done, total):
                pct = f"{done * 100 // total} %" if total else f"{done // 1024} KB"
                report(f"Lade {plan.asset_name} … {pct}")

            if not download_to(plan.asset_url, local, on_progress=progress):
                return "Der Download ist fehlgeschlagen."

            report("Prüfe Prüfsumme …")
            if not verify_file(local, expected):
                try:
                    os.remove(local)
                except OSError:
                    pass  # Loeschen ist best-effort; die Datei wird nicht benutzt
                return ("Die Prüfsumme der geladenen Datei stimmt nicht. "
                        "Die Datei wurde verworfen.")
            return None

        def done(error):
            if not self.frame.winfo_exists():
                return
            if error is not None:
                self._updating = False
                set_primary_button_enabled(self._check_btn, True)
                set_secondary_button_enabled(self._download_btn, True)
                self._status_label.config(text="Update fehlgeschlagen")
                themed_showerror(self.frame, "Update fehlgeschlagen", error)
                return
            self._status_label.config(text="Installiere …")
            self._apply(plan, local)

        self._runner.run(work, done)

    def _apply(self, plan, local):
        """Anwenden und die App beenden bzw. neu starten."""
        if platform.system() == "Windows":
            if not apply_windows(plan.target, local, os.getpid()):
                themed_showerror(
                    self.frame, "Update fehlgeschlagen",
                    "Der Update-Helfer ließ sich nicht starten.")
                return
            self.frame.winfo_toplevel().quit()
            return

        error = apply_linux(plan.target, local)
        if error is not None:
            themed_showerror(self.frame, "Update fehlgeschlagen", error)
            return
        os.execv(plan.target, [plan.target])
```

Nötige Importe oben: `import os`, `import sys`, `import tempfile`; aus `src.self_update`: `UpdateBlocked, apply_linux, apply_windows, download_to, fetch_text, linux_apply_paths, parse_sha256sums, plan_update, supports_self_update, verify_file`; der vorhandene `src.theme`-Import wird um `set_secondary_button_enabled` und `themed_showerror` erweitert (beide sind dort exportiert, s. `src/theme/__init__.py`). In `__init__` zusätzlich `self._updating = False` setzen.

- [ ] **Schritt 4: Manuell gegenprüfen (Repo-Modus)**

Run: `python -m src.main` → Einstellungen → Updates → „Jetzt prüfen".
Erwartet: Der Knopf heißt **„Download"** (Repo-Modus ⇒ `supports_self_update` ist falsch), Verhalten unverändert wie heute.

- [ ] **Schritt 5: Suite und Linter**

Run: `python -m pytest -q && python -m ruff check . && npx pyright@1.1.411`

- [ ] **Schritt 6: Commit**

```bash
git add src/dialogs/settings_dialog/tab_updates.py
git commit -m "feat(self-update): Ein-Klick-Update im Updates-Tab"
```

---

### Task 8: Banner — derselbe Ablauf

**Files:**
- Modify: `src/update_banner.py`

- [ ] **Schritt 1: Knopftext und Klickziel**

Im `_show`-Aufbau (Zeile ~68) den Knopftext analog zu Task 7 wählen (`"Update installieren"` bzw. `"Download"`), Klick auf einen neuen `self._install_or_download(release)` legen.

- [ ] **Schritt 2: M9-Vermerk ersetzen**

Der Kommentar in `_open_download` beschreibt einen Zustand, den es nicht mehr gibt. Ersetzen durch die eingelöste Zusicherung:

```python
    def _open_download(self, release):
        # Fallback-Weg (macOS, unpassende Architektur, Repo-Modus): die App
        # oeffnet nur die URL, sie laedt und startet nichts selbst.
        #
        # M9 ist damit eingeloest, aber nur zur Haelfte weg: der In-App-Weg
        # (self_update.py) prueft JEDE geladene Datei gegen den SHA256SUMS des
        # Releases und installiert nichts Ungeprueftes. Was das leistet, steht
        # im Modul-Docstring dort — Schutz gegen kaputte Uebertragung, NICHT
        # gegen ein kompromittiertes Release; die Summen-Datei ist selbst
        # unsigniert. Vertrauensanker bleibt TLS zu GitHub.
        url = pick_asset_url(
            release.assets, platform.system(), release.version,
            platform.machine(),
        ) or release.html_url
        webbrowser.open(url)
```

- [ ] **Schritt 3: Ablauf anbinden**

`_install_or_download` ruft bei `supports_self_update` denselben Ablauf wie Task 7. Damit die Logik nicht zweimal existiert, wird der Ablauf aus Task 7 als Modulfunktion in `src/self_update.py` **nicht** dupliziert, sondern der Banner delegiert an den Updates-Tab-Weg, indem er den Einstellungsdialog auf dem Updates-Tab öffnet, wenn `supports_self_update` wahr ist:

```python
    def _install_or_download(self, release):
        # Bewusst KEIN zweiter Ablaufpfad: der Banner hat weder Statuszeile
        # noch Fortschrittsanzeige. Er schickt den Nutzer dorthin, wo beides
        # steht — ein Klick mehr, aber nur EINE Stelle, die das Update fährt.
        if self._can_self_update:
            self._open_updates_tab()
            return
        self._open_download(release)
```

`self._open_updates_tab` wird als Callback im Konstruktor injiziert (aus `ui.py`, wo der Einstellungsdialog ohnehin geöffnet wird) — dasselbe Muster wie die übrigen Banner-Callbacks.

- [ ] **Schritt 4: Suite und Linter**

Run: `python -m pytest -q && python -m ruff check . && npx pyright@1.1.411`

- [ ] **Schritt 5: Commit**

```bash
git add src/update_banner.py src/ui.py
git commit -m "feat(self-update): Banner fuehrt zum Update-Ablauf"
```

---

### Task 9: Automatik-Schalter und Anwenden beim Beenden

**Files:**
- Modify: `src/settings.py` (Defaults)
- Modify: `src/dialogs/settings_dialog/tab_updates.py`
- Modify: `src/ui.py` (`_quit_with_sync_push`)
- Modify: `tests/test_settings.py`

**Interfaces:**
- Produces: Setting `auto_update_enabled: bool` (Default `False`), **nicht** in `SYNCED_SETTING_KEYS`

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

In `tests/test_settings.py`:

```python
def test_auto_update_is_off_by_default_and_device_local():
    from src.settings import DEFAULTS, SYNCED_SETTING_KEYS
    assert DEFAULTS["auto_update_enabled"] is False
    # Ein Wert, den sich ein Mac und ein Windows-Rechner teilen, waere auf
    # einem der beiden systematisch falsch — der Mac kann gar nicht selbst
    # updaten. Dieselbe Begruendung wie beim Pre-Release-Haekchen.
    assert "auto_update_enabled" not in SYNCED_SETTING_KEYS


def test_pending_update_keys_are_device_local():
    # Ein Pfad aus dem %TEMP% eines anderen Rechners waere hier sinnlos.
    from src.settings import DEFAULTS, SYNCED_SETTING_KEYS
    assert DEFAULTS["pending_update_path"] == ""
    assert DEFAULTS["pending_update_sha256"] == ""
    assert "pending_update_path" not in SYNCED_SETTING_KEYS
    assert "pending_update_sha256" not in SYNCED_SETTING_KEYS
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag prüfen**

Run: `python -m pytest tests/test_settings.py -k auto_update -v`
Erwartet: FAIL — `KeyError: 'auto_update_enabled'`

- [ ] **Schritt 3: Default ergänzen**

`src/settings.py`, in `DEFAULTS` direkt nach `"prerelease_updates_enabled": False,`:

```python
    "auto_update_enabled": False,
```

- [ ] **Schritt 4: Schalter im Tab**

Der Tab benutzt **feste** `row=`-Nummern, keinen laufenden Zähler. Belegt sind heute: `btn_row=2`, `freq_row=3`, Pre-Release-Häkchen `4`, dessen Hinweiszeile `5`, `_changelog_label=6`, `_changelog_text=7`.

Das neue Häkchen kommt auf **6**, seine Hinweiszeile auf **7**; `_changelog_label` rückt auf **8**, `_changelog_text` auf **9** (beide `.grid(...)`-Aufrufe in `__init__` entsprechend anpassen).

Direkt nach der Hinweiszeile des Pre-Release-Häkchens (Zeile ~95) einfügen:

```python
        # Nur bauen, wo Selbst-Update ueberhaupt moeglich ist — ein Schalter
        # fuer ein Feature, das die Plattform nicht hat, ist Rauschen
        # (dieselbe Regel wie beim "Urlaub ausweisen"-Haekchen).
        self.auto_update_var = None
        if self._can_self_update:
            self.auto_update_var = tk.BooleanVar(
                value=bool(settings.get("auto_update_enabled")))
            tk.Checkbutton(
                frame, text="Updates automatisch installieren",
                variable=self.auto_update_var, font=FONT, bg=BG, fg=TEXT,
                selectcolor=CELL_BG, activebackground=BG, activeforeground=TEXT,
                cursor="hand2",
            ).grid(row=6, column=0, columnspan=2, padx=10, pady=(8, 0),
                   sticky="w")
            tk.Label(
                frame,
                text=("Lädt im Hintergrund und installiert beim nächsten "
                      "Beenden — nie mitten in der Arbeit."),
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
            ).grid(row=7, column=0, columnspan=2, padx=10, pady=(0, 4),
                   sticky="w")
```

Gespeichert wird der Wert dort, wo der Dialog auch `prerelease_updates_enabled` speichert — `self.auto_update_var` ist `None`, wenn der Schalter nicht gebaut wurde, und wird dann übersprungen.

- [ ] **Schritt 5: Auslöser und Anwenden beim Beenden**

Meldet `resolve_check_result` eine neuere Version **und** `auto_update_enabled` ist an, läuft derselbe `work()`-Teil wie in Task 7 (laden + prüfen), aber **ohne** `_apply`. Stattdessen merkt sich der Tab den verifizierten Pfad in `settings` (`pending_update_path`, ebenfalls gerätelokal, Default `""`), und der Banner zeigt „Update bereit — wird beim Beenden installiert".

In `src/ui.py`, `_quit_with_sync_push`, **nach** `self._sync.push_on_quit()` und **vor** `self.root.destroy()`:

```python
        # Ein vorbereitetes Update erst hier anwenden — die App macht ohnehin
        # zu, der Nutzer verliert keinen angefangenen Eintrag, und der
        # Neustart nach dem Update entfaellt.
        pending = self.settings.get("pending_update_path")
        if pending:
            self._apply_pending_update(pending)
```

Dazu in `src/ui.py`:

```python
    def _apply_pending_update(self, path):
        """Ein vorbereitetes Update beim Beenden anwenden (best-effort).

        Erneut geprueft wird hier bewusst: zwischen Download und Beenden
        koennen Stunden liegen, und Aufraeum-Tools leeren %TEMP%. Fehlt die
        Datei oder stimmt ihr Hash nicht mehr, faellt der Vorgang still aus —
        der naechste Update-Check beginnt von vorn. Ein Fehlschlag hier darf
        das Beenden NIE aufhalten.
        """
        from src.self_update import apply_linux, apply_windows, verify_file

        expected = self.settings.get("pending_update_sha256")
        self.settings.set_many({"pending_update_path": "",
                                "pending_update_sha256": ""})
        if not os.path.exists(path) or not verify_file(path, expected):
            logging.getLogger(__name__).info(
                "Vorbereitetes Update verworfen (Datei fehlt oder Hash "
                "stimmt nicht)")
            return

        if platform.system() == "Windows":
            apply_windows(sys.executable, path, os.getpid())
            return
        appimage = os.environ.get("APPIMAGE", "")
        if appimage:
            apply_linux(appimage, path)
```

Unter Linux wird **nicht** neu gestartet: die App war im Begriff zu enden, die neue Datei liegt beim nächsten Start bereit. Unter Windows startet der Helfer sie wieder — das ist sein normaler Ablauf und hier gewollt, weil der Installer sonst gegen eine noch laufende Instanz liefe.

`src/settings.py` bekommt dafür zwei weitere gerätelokale Defaults neben `auto_update_enabled`:

```python
    "pending_update_path": "",
    "pending_update_sha256": "",
```

Auch diese beiden **nicht** in `SYNCED_SETTING_KEYS` — ein Pfad aus dem `%TEMP%` eines anderen Rechners wäre dort sinnlos und im schlimmsten Fall irreführend.

- [ ] **Schritt 6: Suite und Linter**

Run: `python -m pytest -q && python -m ruff check . && npx pyright@1.1.411`

- [ ] **Schritt 7: Commit**

```bash
git add src/settings.py src/dialogs/settings_dialog/tab_updates.py src/ui.py tests/test_settings.py
git commit -m "feat(self-update): Automatik als Opt-in, angewendet beim Beenden"
```

---

### Task 10: Dokumentation

**Files:**
- Modify: `README.md` (Feature-Matrix „Plattform-Kompatibilität", Zeile ~499; Features-Abschnitt)
- Modify: `CLAUDE.md`
- Modify: `docs/known-limitations.md`

- [ ] **Schritt 1: README — Zeile in die Plattform-Matrix**

In der Tabelle unter „Plattform-Kompatibilität", nach der Zeile „Standalone-Binary (PyInstaller)":

```markdown
| Update aus der App | ✓ (lädt, prüft, installiert, startet neu) | — (Download im Browser) | ✓ (lädt, prüft, ersetzt die AppImage) |
```

Das `—` folgt der Konvention der Tabelle: nie allein, immer mit Grund bzw. Ersatz in Klammern. **Kein `○`** — das ist laut Legende für „implementiert, aber dormant" reserviert, und für macOS ist nichts implementiert.

- [ ] **Schritt 2: README — Feature-Zeile**

Im Abschnitt „App & Umgebung" eine Zeile mit Marker ergänzen:

```markdown
- **Update aus der App** *(ab 1.23.0)* — Unter Windows und Linux lädt die App ein Update selbst, prüft es gegen die Prüfsummen des Releases und installiert es; auf Wunsch automatisch beim nächsten Beenden. Unter macOS öffnet der Knopf weiterhin den Download im Browser
```

- [ ] **Schritt 3: `docs/known-limitations.md`**

Abschnitt ergänzen: macOS ohne Selbst-Update; Gründe (unsigniertes, nicht notarisiertes Bundle; auf der Windows-Dev-Maschine nicht verifizierbar; CI baut nur arm64) **und** der Grund, es später nachzuziehen: ein Download per `urllib` setzt `com.apple.quarantine` nicht, ein Selbst-Update umginge die Gatekeeper-Hürde also ganz.

- [ ] **Schritt 4: `CLAUDE.md`**

Neuer Abschnitt „Update-Weg" mit: den drei Plattformen; warum `installer.iss` unangetastet bleibt (`AppMutex` + `skipifsilent`, und dass die Datei nur über `build.yml` mit `installer`-Häkchen testbar ist); was die Hash-Prüfung leistet und was **nicht**; dass `auto_update_enabled` gerätelokal ist und warum.

- [ ] **Schritt 5: Commit**

```bash
git add README.md CLAUDE.md docs/known-limitations.md
git commit -m "docs: Update-Weg fuer Windows und Linux, macOS-Grenze"
```

---

## Verifikation vor dem PR

- [ ] `python -m pytest -q` — grün
- [ ] `python -m ruff check .` — 0 Fehler
- [ ] `npx pyright@1.1.411` — 0 Fehler
- [ ] **Windows-Durchstich lokal.** Workflow **Build** mit gesetztem `installer`-Häkchen starten, `zeiterfassung-windows-setup` herunterladen. **Vorher** `%LOCALAPPDATA%\Programs\Zeiterfassung\` sichern — dort liegen `credentials.json`, `conflicts.json`, `backup_jsons` und die Zeiteinträge. Dann: App aus der Installation starten, Update auslösen, prüfen dass die App beendet, der Installer still durchläuft und die App neu startet; `update.log` neben der Exe kontrollieren.
- [ ] **Negativtest Hash.** Eine Prüfsummen-Antwort mit falschem Digest erzwingen (lokal `fetch_text` patchen oder eine manipulierte Datei unterschieben) — die App darf **nichts** installieren und muss die geladene Datei löschen.
- [ ] **Linux** über einen Pre-Release, wie CLAUDE.md es für plattformspezifische Änderungen vorschreibt.
- [ ] Kein Versionsbump, kein CHANGELOG, kein `release:*`-Label.
