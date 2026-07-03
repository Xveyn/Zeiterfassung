# Autostart-Vereinheitlichung + Single-Instance-Guard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auf Windows kann nur noch **ein** Autostart-Eintrag existieren (App und Installer teilen denselben Registry-Run-Key); die Autostart-Checkbox zeigt den echten Zustand; Bestandsnutzer werden absichtserhaltend migriert; ein plattformübergreifender Single-Instance-Guard verhindert parallele Instanzen.

**Architecture:** Windows-Autostart wechselt von einem Startup-Shortcut auf den HKCU-Run-Registry-Wert `Zeiterfassung` (gleicher Wertname wie im Installer → strukturell ein Eintrag). Eine frozen-gegatete Migration überführt Alt-Shortcuts absichtserhaltend in die Registry. Ein neues Tk-freies Modul `single_instance.py` bindet beim Start einen pro-Nutzer abgeleiteten Localhost-Port; nur die Erstinstanz gewinnt den Bind (atomar), Folge­instanzen melden sich per Socket und beenden sich.

**Tech Stack:** Python stdlib (`winreg`, `socket`, `zlib`, `threading`), Tkinter (bestehend), pytest.

## Global Constraints

- **`import winreg` immer LAZY** (in der Funktion, nie auf Modulebene): CI läuft auf Ubuntu und importiert `autostart.py` über `tests → ui → settings_dialog → autostart`; ein Modul-Level-Import bräche jeden CI-Lauf. Gleiche Regel wie die Lazy-Google-Imports in `drive.py`/`gcal.py`.
- **Registry-Wertformat exakt wie der Installer:** Wertname `Zeiterfassung`, Daten `"<target>" --minimized` (Exe-Pfad in Anführungszeichen, Space, Argumente; ohne Argumente nur `"<target>"`). `installer.iss` bleibt unverändert.
- **Migration nur im Frozen-Build** (`sys.frozen`) und nur auf Windows — sonst Selbstbeschädigung im Repo-Modus.
- **Datum intern ISO / UI deutsch, UTF-8-Mail-Pipeline, Klick-Modell** — hier nicht berührt, gelten aber projektweit.
- **`autostart` bleibt device-lokal**, nicht in `SYNCED_SETTING_KEYS` aufnehmen.
- **Guard darf den Start nie blockieren**: jeder Fehlerpfad (belegter Fremd-Port, Bind-Fehler, Exception) endet im normalen (ggf. ungeschützten) Start.
- **Socket-Option plattformabhängig:** Windows `SO_EXCLUSIVEADDRUSE` (vor `bind`), POSIX `SO_REUSEADDR`. `SO_REUSEADDR` auf Windows würde den zweiten Bind gelingen lassen → Guard wirkungslos.
- Commit-Typ englisch (`feat:`/`fix:`/`docs:`/`test:`), Body/Beschreibung Deutsch ok. Kein `git push` (kein Trigger).

---

## Dateien-Überblick

| Datei | Verantwortung |
|-------|---------------|
| `src/autostart.py` | Windows-Backend Registry statt Shortcut; `is_autostart_enabled()`; `migrate_legacy_autostart()` |
| `src/single_instance.py` | **neu** — Tk-freier Guard: Port-Ableitung, plattform-Socket-Option, Protokoll, `acquire`/`serve`/`release` |
| `src/main.py` | Migration + Guard-`acquire` vor Tk-Bau; Guard an `App`; `serve()` nach Bau |
| `src/ui.py` | `App` hält Guard; `release()` vor Skalierungs-Relaunch und bei Quit |
| `src/dialogs/settings_dialog.py` | Checkbox-Init + `old_autostart` aus `is_autostart_enabled()` |
| `tests/test_autostart.py` | Windows-Klasse auf Registry umbauen; `is_autostart_enabled`, `migrate_legacy_autostart` |
| `tests/test_single_instance.py` | **neu** |
| `src/CLAUDE.md` | Guard-Modul + Registry-Vertrag dokumentieren |

---

### Task 1: Windows-Autostart von Shortcut auf Registry umstellen + `is_autostart_enabled()`

**Files:**
- Modify: `src/autostart.py` (`_enable_windows`, `_disable_windows`; neu: Registry-Helfer, `is_autostart_enabled`)
- Test: `tests/test_autostart.py` (Windows-Klasse `TestWindowsAutostart` umbauen; neue Klasse `TestIsAutostartEnabled`)

**Interfaces:**
- Consumes: `resolve_autostart_target(base_path)` (bestehend), `_get_shortcut_path()` (bestehend).
- Produces:
  - `is_autostart_enabled() -> bool` — plattform-dispatched Statusabfrage.
  - Modul-Konstanten `_RUN_KEY_SUBKEY: str`, `_RUN_VALUE_NAME: str` (test-patchbar).
  - `_windows_run_command(target: str, arguments: str) -> str` — baut den Registry-Datenstring.
  - Interne Helfer `_windows_registry_enabled() -> bool`, `_remove_legacy_shortcut() -> None`.
  - `enable_autostart(target, arguments)` / `disable_autostart()` behalten Signatur & Verhalten (nur Windows-Backend wechselt).

- [ ] **Step 1: Failing test — Registry-Datenstring-Format**

In `tests/test_autostart.py`, oben ergänzen:
```python
from src.autostart import is_autostart_enabled, _windows_run_command
```
Neuen Test hinzufügen (plattformunabhängig, reine String-Logik):
```python
def test_windows_run_command_matches_installer_format():
    cmd = _windows_run_command(r"C:\app\Zeiterfassung.exe", "--minimized")
    assert cmd == r'"C:\app\Zeiterfassung.exe" --minimized'


def test_windows_run_command_without_arguments():
    cmd = _windows_run_command(r"C:\app\Zeiterfassung.exe", "")
    assert cmd == r'"C:\app\Zeiterfassung.exe"'
```

- [ ] **Step 2: Run → verläuft fehlerhaft (ImportError)**

Run: `pytest tests/test_autostart.py::test_windows_run_command_matches_installer_format -v`
Expected: FAIL — `ImportError: cannot import name '_windows_run_command'`.

- [ ] **Step 3: Registry-Helfer + Konstanten implementieren**

In `src/autostart.py` unter die bestehenden Konstanten (`SHORTCUT_NAME`, `MACOS_LABEL`):
```python
_RUN_KEY_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE_NAME = "Zeiterfassung"


def _windows_run_command(target, arguments):
    """Baut den HKCU-Run-Datenstring — identisch zum Installer-Format:
    Exe in Anführungszeichen, dann (falls vorhanden) die Argumente."""
    if arguments:
        return f'"{target}" {arguments}'
    return f'"{target}"'


def _remove_legacy_shortcut():
    """Entfernt den Alt-Startup-Shortcut, falls vorhanden (tolerant)."""
    try:
        os.remove(_get_shortcut_path())
    except FileNotFoundError:
        pass


def _windows_registry_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_SUBKEY) as key:
            winreg.QueryValueEx(key, _RUN_VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
```

- [ ] **Step 4: `_enable_windows` / `_disable_windows` auf Registry umstellen**

In `src/autostart.py` den **kompletten** bestehenden `_enable_windows`-Body (VBS/cscript) und `_disable_windows`-Body ersetzen durch:
```python
def _enable_windows(target, arguments):
    import winreg
    command = _windows_run_command(target, arguments)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_SUBKEY) as key:
        winreg.SetValueEx(key, _RUN_VALUE_NAME, 0, winreg.REG_SZ, command)
    _remove_legacy_shortcut()


def _disable_windows():
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY_SUBKEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _RUN_VALUE_NAME)
    except FileNotFoundError:
        pass
    _remove_legacy_shortcut()
```
`import tempfile` (oben in `autostart.py`) wird danach **unbenutzt** (nur der alte VBS-Pfad nutzte `mkstemp`) → entfernen, sonst meldet `ruff` F401. `subprocess`/`plistlib` bleiben (macOS-Backend nutzt sie).

- [ ] **Step 5: `is_autostart_enabled()` implementieren**

In `src/autostart.py` nach `disable_autostart()` einfügen:
```python
def is_autostart_enabled():
    """Echter Autostart-Zustand (nicht das gespeicherte Setting).

    Windows: Registry-Run-Wert ODER Alt-Shortcut vorhanden (Shortcut-Fallback,
    falls die Migration einmal fehlschlägt). macOS/Linux: Plist- bzw.
    .desktop-Datei vorhanden."""
    system = platform.system()
    if system == "Windows":
        return _windows_registry_enabled() or os.path.exists(_get_shortcut_path())
    if system == "Darwin":
        return os.path.exists(_macos_plist_path())
    if system == "Linux":
        return os.path.exists(_linux_desktop_path())
    return False
```

- [ ] **Step 6: `_windows_run_command`-Tests grün**

Run: `pytest tests/test_autostart.py::test_windows_run_command_matches_installer_format tests/test_autostart.py::test_windows_run_command_without_arguments -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Windows-Registry-Tests schreiben (real winreg gegen Temp-Subkey)**

In `tests/test_autostart.py` die Klasse `TestWindowsAutostart` **komplett ersetzen** (die alten cscript/VBS-Tests entfallen). Nutzt echten `winreg` gegen einen throwaway HKCU-Subkey — schreibt **nie** in den echten Run-Key:
```python
@pytest.mark.skipif(platform.system() != "Windows", reason="Windows only")
class TestWindowsAutostart:
    @pytest.fixture
    def temp_run_key(self, monkeypatch):
        import winreg
        subkey = r"Software\ZeiterfassungTest\Run"
        monkeypatch.setattr("src.autostart._RUN_KEY_SUBKEY", subkey)
        yield subkey
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
        except FileNotFoundError:
            pass

    def test_enable_writes_registry_value(self, temp_run_key, fake_startup):
        import winreg
        enable_autostart(r"C:\app\Zeiterfassung.exe", "--minimized")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, temp_run_key) as key:
            value, _typ = winreg.QueryValueEx(key, "Zeiterfassung")
        assert value == r'"C:\app\Zeiterfassung.exe" --minimized'

    def test_disable_removes_registry_value(self, temp_run_key, fake_startup):
        import winreg
        enable_autostart(r"C:\app\Zeiterfassung.exe", "--minimized")
        disable_autostart()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, temp_run_key) as key:
            with pytest.raises(FileNotFoundError):
                winreg.QueryValueEx(key, "Zeiterfassung")

    def test_disable_without_value_no_error(self, temp_run_key, fake_startup):
        disable_autostart()  # kein Wert vorhanden → kein Fehler

    def test_enable_removes_legacy_shortcut(self, temp_run_key, fake_startup):
        shortcut = fake_startup / "Zeiterfassung.lnk"
        shortcut.write_text("fake")
        enable_autostart(r"C:\app\Zeiterfassung.exe", "--minimized")
        assert not shortcut.exists()
```

- [ ] **Step 8: `is_autostart_enabled`-Tests (alle Plattformen)**

In `tests/test_autostart.py` neue Klasse anfügen. macOS/Linux nutzen die vorhandenen `fake_home`-Muster; Windows den Temp-Key:
```python
class TestIsAutostartEnabled:
    def test_linux_true_when_desktop_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr("src.autostart.platform.system", lambda: "Linux")
        assert is_autostart_enabled() is False
        enable_autostart("/opt/Zeiterfassung.AppImage", "--minimized")
        assert is_autostart_enabled() is True

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS only")
    def test_macos_true_when_plist_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr("src.autostart.platform.system", lambda: "Darwin")
        (tmp_path / "Library" / "LaunchAgents").mkdir(parents=True)
        assert is_autostart_enabled() is False

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows only")
    def test_windows_true_when_registry_value_exists(self, monkeypatch, tmp_path):
        import winreg
        subkey = r"Software\ZeiterfassungTest\Run2"
        monkeypatch.setattr("src.autostart._RUN_KEY_SUBKEY", subkey)
        monkeypatch.setattr("src.autostart._get_startup_folder", lambda: str(tmp_path))
        assert is_autostart_enabled() is False
        enable_autostart(r"C:\app\Zeiterfassung.exe", "--minimized")
        try:
            assert is_autostart_enabled() is True
        finally:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
```
Hinweis: Der Linux-Test läuft auch in der Ubuntu-CI (kein skipif) — deckt `is_autostart_enabled` + `enable`/`disable` real ab.

- [ ] **Step 9: Volle Autostart-Tests grün**

Run: `pytest tests/test_autostart.py -v`
Expected: PASS (macOS/Linux-Klassen unverändert grün; Windows-Klassen laufen bzw. sind auf Nicht-Windows geskippt).

- [ ] **Step 10: Commit**

```bash
git add src/autostart.py tests/test_autostart.py
git commit -m "feat(autostart): Windows-Autostart auf HKCU-Run-Registry + is_autostart_enabled"
```

---

### Task 2: `migrate_legacy_autostart()` — Alt-Shortcut absichtserhaltend in die Registry überführen

**Files:**
- Modify: `src/autostart.py` (neu: `migrate_legacy_autostart`)
- Test: `tests/test_autostart.py` (neue Klasse `TestMigrateLegacyAutostart`)

**Interfaces:**
- Consumes: `resolve_autostart_target`, `_windows_registry_enabled`, `_enable_windows`, `_remove_legacy_shortcut`, `_get_shortcut_path`.
- Produces: `migrate_legacy_autostart(base_path: str) -> None` — no-op außer im Frozen-Windows-Build mit vorhandenem Alt-Shortcut.

- [ ] **Step 1: Failing tests — die vier Zustände**

In `tests/test_autostart.py` ergänzen (`from src.autostart import migrate_legacy_autostart` oben hinzufügen):
```python
@pytest.mark.skipif(platform.system() != "Windows", reason="Windows only")
class TestMigrateLegacyAutostart:
    @pytest.fixture
    def frozen_win(self, monkeypatch, tmp_path):
        import winreg
        subkey = r"Software\ZeiterfassungTest\RunMig"
        monkeypatch.setattr("src.autostart._RUN_KEY_SUBKEY", subkey)
        monkeypatch.setattr("src.autostart._get_startup_folder", lambda: str(tmp_path))
        monkeypatch.setattr("src.autostart.sys.frozen", True, raising=False)
        monkeypatch.setattr("src.autostart.sys.executable",
                            str(tmp_path / "Zeiterfassung.exe"), raising=False)
        yield tmp_path
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
        except FileNotFoundError:
            pass

    def test_state2_shortcut_only_writes_registry(self, frozen_win):
        (frozen_win / "Zeiterfassung.lnk").write_text("fake")
        migrate_legacy_autostart(str(frozen_win))
        from src.autostart import _windows_registry_enabled
        assert _windows_registry_enabled() is True
        assert not (frozen_win / "Zeiterfassung.lnk").exists()

    def test_state3_both_keeps_registry_drops_shortcut(self, frozen_win):
        enable_autostart(str(frozen_win / "Zeiterfassung.exe"), "--minimized")
        (frozen_win / "Zeiterfassung.lnk").write_text("fake")
        migrate_legacy_autostart(str(frozen_win))
        from src.autostart import _windows_registry_enabled
        assert _windows_registry_enabled() is True
        assert not (frozen_win / "Zeiterfassung.lnk").exists()

    def test_state4_nothing_stays_nothing(self, frozen_win):
        migrate_legacy_autostart(str(frozen_win))
        from src.autostart import _windows_registry_enabled
        assert _windows_registry_enabled() is False

    def test_idempotent_second_run_noop(self, frozen_win):
        (frozen_win / "Zeiterfassung.lnk").write_text("fake")
        migrate_legacy_autostart(str(frozen_win))
        migrate_legacy_autostart(str(frozen_win))  # kein Fehler, kein Shortcut mehr
        assert not (frozen_win / "Zeiterfassung.lnk").exists()

    def test_not_frozen_is_noop(self, frozen_win, monkeypatch):
        monkeypatch.setattr("src.autostart.sys.frozen", False, raising=False)
        (frozen_win / "Zeiterfassung.lnk").write_text("fake")
        migrate_legacy_autostart(str(frozen_win))
        from src.autostart import _windows_registry_enabled
        assert _windows_registry_enabled() is False          # nichts geschrieben
        assert (frozen_win / "Zeiterfassung.lnk").exists()   # Shortcut unangetastet
```

- [ ] **Step 2: Run → FAIL (ImportError)**

Run: `pytest tests/test_autostart.py::TestMigrateLegacyAutostart -v`
Expected: FAIL — `cannot import name 'migrate_legacy_autostart'`.

- [ ] **Step 3: `migrate_legacy_autostart` implementieren**

In `src/autostart.py` nach `is_autostart_enabled()` einfügen:
```python
def migrate_legacy_autostart(base_path):
    """Überführt einen Alt-Startup-Shortcut in den Registry-Run-Key —
    absichtserhaltend. Nur im Frozen-Windows-Build; sonst No-op (im Repo-Modus
    würde der Registry-Wert auf python.exe+Repo zeigen und den installierten
    Shortcut löschen — Selbstbeschädigung). Idempotent: ist der Shortcut weg,
    tut jeder weitere Lauf nichts."""
    if not getattr(sys, "frozen", False):
        return
    if platform.system() != "Windows":
        return
    if not os.path.exists(_get_shortcut_path()):
        return
    if not _windows_registry_enabled():
        target, arguments = resolve_autostart_target(base_path)
        _enable_windows(target, arguments)  # schreibt Registry + entfernt Shortcut
        return
    _remove_legacy_shortcut()
```

- [ ] **Step 4: Run → PASS**

Run: `pytest tests/test_autostart.py::TestMigrateLegacyAutostart -v`
Expected: PASS (auf Nicht-Windows geskippt).

- [ ] **Step 5: Commit**

```bash
git add src/autostart.py tests/test_autostart.py
git commit -m "feat(autostart): migrate_legacy_autostart — Alt-Shortcut absichtserhaltend in Registry"
```

---

### Task 3: Settings-Dialog-Checkbox liest den echten Zustand

**Files:**
- Modify: `src/dialogs/settings_dialog.py` (Import; Zeile ~713 Checkbox-Init; Zeile ~866 `old_autostart`)

**Interfaces:**
- Consumes: `is_autostart_enabled()` (Task 1).
- Produces: — (reine Wiring-Änderung; kein neuer Unit-Test, weil Tk-gebunden. Das Verhalten „Checkbox = echter Zustand" ist über `is_autostart_enabled()` in Task 1 getestet.)

- [ ] **Step 1: Import ergänzen**

In `src/dialogs/settings_dialog.py` die bestehende Import-Zeile
```python
from src.autostart import disable_autostart, enable_autostart, resolve_autostart_target
```
erweitern zu:
```python
from src.autostart import disable_autostart, enable_autostart, is_autostart_enabled, resolve_autostart_target
```

- [ ] **Step 2: Checkbox-Init aus dem echten Zustand**

In `src/dialogs/settings_dialog.py` (~Zeile 713) ersetzen:
```python
    autostart_var = tk.BooleanVar(value=settings.get("autostart"))
```
durch:
```python
    autostart_var = tk.BooleanVar(value=is_autostart_enabled())
```

- [ ] **Step 3: `old_autostart` aus dem echten Zustand**

In `src/dialogs/settings_dialog.py` (~Zeile 866) ersetzen:
```python
        old_autostart = settings.get("autostart")
```
durch:
```python
        old_autostart = is_autostart_enabled()
```
(So ist „unverändert gelassen" ein echtes No-op; der `updates`-Dict-Eintrag `"autostart": new_autostart` bleibt für Abwärtskompatibilität bestehen.)

- [ ] **Step 4: Verify — Suite grün + Lint**

Run: `pytest -q && ruff check .`
Expected: PASS (keine neuen Failures; die Wiring-Änderung bricht keine bestehenden Tests).

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/settings_dialog.py
git commit -m "fix(settings-ui): Autostart-Checkbox liest echten Zustand statt gespeichertem Flag"
```

---

### Task 4: `single_instance.py` — Tk-freier Single-Instance-Guard

**Files:**
- Create: `src/single_instance.py`
- Test: `tests/test_single_instance.py`

**Interfaces:**
- Consumes: — (stdlib only).
- Produces:
  - `acquire(base_path: str, show_requested: bool) -> _Guard | None` — `None` ⇒ ein Geschwister läuft, Aufrufer soll sich beenden; `_Guard` ⇒ Primär (ggf. degradiert-ungebunden).
  - `_derive_port(base_path: str) -> int` — deterministischer Port 20000–31999.
  - `class _Guard` mit `bound: bool`, `serve(show_fn: Callable[[], None]) -> None`, `release() -> None`.
  - Protokoll-Konstanten `_MAGIC_SHOW`, `_MAGIC_PING`, `_MAGIC_OK` (bytes).

- [ ] **Step 1: Failing test — Port-Ableitung**

Create `tests/test_single_instance.py`:
```python
# tests/test_single_instance.py
import socket
import sys
import threading

import pytest

from src.single_instance import _derive_port, acquire


def test_derive_port_deterministic_and_in_range():
    p1 = _derive_port(r"C:\Users\a\Zeiterfassung")
    p2 = _derive_port(r"C:\Users\a\Zeiterfassung")
    assert p1 == p2
    assert 20000 <= p1 < 32000


def test_derive_port_differs_per_path():
    assert _derive_port("/home/a") != _derive_port("/home/b")


@pytest.mark.skipif(sys.platform != "win32", reason="normcase ist nur auf Windows case-/separator-normalisierend")
def test_derive_port_normalizes_case_and_separators():
    a = _derive_port(r"C:\Users\A\Zeiterfassung")
    b = _derive_port(r"c:/users/a/zeiterfassung")
    assert a == b
```

- [ ] **Step 2: Run → FAIL (ModuleNotFoundError)**

Run: `pytest tests/test_single_instance.py::test_derive_port_deterministic_and_in_range -v`
Expected: FAIL — `No module named 'src.single_instance'`.

- [ ] **Step 3: Modul-Grundgerüst + `_derive_port`**

Create `src/single_instance.py`:
```python
# src/single_instance.py
"""Single-Instance-Guard (Tk-frei). Erstinstanz bindet einen pro-Nutzer
abgeleiteten Localhost-Port; Folgeinstanzen melden sich per Socket und beenden
sich. Blockiert den Start nie — jeder Fehlerpfad endet im (ggf. ungeschützten)
Weiterlauf."""
import logging
import os
import socket
import sys
import threading
import zlib

_MAGIC_SHOW = b"ZEIT-SHOW"
_MAGIC_PING = b"ZEIT-PING"
_MAGIC_OK = b"ZEIT-OK"
_ACK_TIMEOUT = 2.0          # großzügig gegen Boot-Last
_PORT_BASE = 20000
_PORT_SPAN = 12000          # Range 20000–31999, unter allen Ephemeral-Ranges

_log = logging.getLogger(__name__)


def _derive_port(base_path):
    norm = os.path.normcase(os.path.normpath(base_path))
    return _PORT_BASE + (zlib.crc32(norm.encode("utf-8")) % _PORT_SPAN)
```

- [ ] **Step 4: Run → PASS (Port-Tests)**

Run: `pytest tests/test_single_instance.py -k derive_port -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Failing test — Primär/Zweit-Erkennung + SHOW/PING**

In `tests/test_single_instance.py` ergänzen:
```python
def test_first_acquire_is_primary_second_exits(tmp_path):
    base = str(tmp_path)
    g1 = acquire(base, show_requested=True)
    try:
        assert g1 is not None and g1.bound is True
        g2 = acquire(base, show_requested=True)
        assert g2 is None            # Geschwister erkannt → Aufrufer beendet sich
    finally:
        g1.release()


def test_show_fires_callback_ping_does_not(tmp_path):
    base = str(tmp_path)
    g1 = acquire(base, show_requested=True)
    fired = threading.Event()
    g1.serve(lambda: fired.set())
    try:
        # SHOW → Callback feuert
        assert acquire(base, show_requested=True) is None
        assert fired.wait(timeout=3.0) is True

        # PING → Callback feuert NICHT
        fired.clear()
        assert acquire(base, show_requested=False) is None
        assert fired.wait(timeout=1.0) is False
    finally:
        g1.release()


def test_pending_show_before_serve_fires_on_serve(tmp_path):
    base = str(tmp_path)
    g1 = acquire(base, show_requested=True)
    try:
        assert acquire(base, show_requested=True) is None   # SHOW vor serve()
        fired = threading.Event()
        g1.serve(lambda: fired.set())                        # gepuffertes SHOW feuert nach
        assert fired.wait(timeout=3.0) is True
    finally:
        g1.release()


def test_foreign_occupant_yields_degraded_primary(tmp_path):
    base = str(tmp_path)
    port = _derive_port(base)
    squatter = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    squatter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    squatter.bind(("127.0.0.1", port))
    squatter.listen(1)
    try:
        g = acquire(base, show_requested=True)   # Port belegt, kein ZEIT-OK
        assert g is not None and g.bound is False  # degradiert, aber Start läuft
    finally:
        squatter.close()
```
Hinweis: `test_foreign_occupant` bindet den Port selbst; auf Windows würde ein zweiter `acquire`-Bind wegen `SO_EXCLUSIVEADDRUSE` scheitern, auf POSIX wegen belegtem Port — in beiden Fällen fällt `acquire` in den Notify-Pfad, bekommt kein `ZEIT-OK` und liefert den degradierten Guard.

- [ ] **Step 6: Run → FAIL (kein `acquire`)**

Run: `pytest tests/test_single_instance.py::test_first_acquire_is_primary_second_exits -v`
Expected: FAIL — `AttributeError: module 'src.single_instance' has no attribute 'acquire'`.

- [ ] **Step 7: `_Guard`, `_notify_primary`, `acquire` implementieren**

In `src/single_instance.py` anfügen:
```python
class _Guard:
    def __init__(self, port):
        self.port = port
        self.bound = False
        self._sock = None
        self._lock = threading.Lock()
        self._show_fn = None
        self._pending_show = False
        self._stop = False

    def _try_bind(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sys.platform == "win32":
            # Windows: verhindert, dass ein zweiter Prozess denselben Port bindet.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", self.port))
            sock.listen(5)
        except OSError:
            sock.close()
            return False
        sock.settimeout(0.5)
        self._sock = sock
        self.bound = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return True

    def _accept_loop(self):
        while not self._stop:
            sock = self._sock
            if sock is None:            # release() lief parallel → sauber raus
                break
            try:
                conn, _addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                try:
                    data = conn.recv(32)
                    if data.startswith(_MAGIC_SHOW):
                        conn.sendall(_MAGIC_OK)
                        self._fire_show()
                    elif data.startswith(_MAGIC_PING):
                        conn.sendall(_MAGIC_OK)
                except OSError:
                    pass

    def _fire_show(self):
        with self._lock:
            fn = self._show_fn
            if fn is None:
                self._pending_show = True
                return
        fn()

    def serve(self, show_fn):
        """Registriert den Fenster-Holen-Callback. Ein vor serve() eingetroffenes
        SHOW feuert jetzt nach."""
        with self._lock:
            self._show_fn = show_fn
            pending = self._pending_show
            self._pending_show = False
        if pending:
            show_fn()

    def release(self):
        """Listener stoppen und Port freigeben (No-op wenn nie gebunden)."""
        self._stop = True
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self.bound = False


def _notify_primary(port, show_requested):
    """Meldet sich bei der laufenden Instanz. True nur, wenn sie sich per
    ZEIT-OK als unsere App bestätigt."""
    msg = _MAGIC_SHOW if show_requested else _MAGIC_PING
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=_ACK_TIMEOUT) as sock:
            sock.sendall(msg)
            sock.settimeout(_ACK_TIMEOUT)
            return sock.recv(len(_MAGIC_OK)) == _MAGIC_OK
    except OSError:
        return False


def acquire(base_path, show_requested):
    """Erstinstanz → gebundener _Guard. Läuft schon eine (bestätigt per ZEIT-OK)
    → None (Aufrufer beendet sich). Port von Fremd-Software belegt → degradierter
    (ungebundener) _Guard, damit der Start nie blockiert."""
    port = _derive_port(base_path)
    guard = _Guard(port)
    if guard._try_bind():
        return guard
    if _notify_primary(port, show_requested):
        return None
    _log.warning("Single-Instance-Port %d belegt, kein ZEIT-OK — Start ohne Guard", port)
    return guard
```

- [ ] **Step 8: Run → alle Guard-Tests grün**

Run: `pytest tests/test_single_instance.py -v`
Expected: PASS (alle). Bei vereinzelt langsamem CI kann `test_show_fires_callback...` an Timing liegen — Timeouts sind großzügig (3 s) gewählt.

- [ ] **Step 9: Lint**

Run: `ruff check src/single_instance.py tests/test_single_instance.py`
Expected: keine Findings (ungenutzte Imports vermeiden: `time`/`monkeypatch` nur nutzen, wo importiert — ggf. unbenutzte Test-Imports entfernen).

- [ ] **Step 10: Commit**

```bash
git add src/single_instance.py tests/test_single_instance.py
git commit -m "feat(single-instance): Tk-freier Guard (pro-Nutzer-Port, SHOW/PING-Protokoll)"
```

---

### Task 5: Verdrahtung in `main.py` + `ui.py` (Migration, Guard-acquire/serve/release)

**Files:**
- Modify: `src/main.py` (`main()`: Migration + `acquire` vor Tk-Bau; Guard an `App`; `serve()` nach Bau)
- Modify: `src/ui.py` (`App.__init__` neuer Param `single_instance`; `restart_for_scaling` + `_quit_with_sync_push` rufen `release()`)

**Interfaces:**
- Consumes: `single_instance.acquire` / `_Guard.serve` / `_Guard.release` (Task 4); `autostart.migrate_legacy_autostart` (Task 2); `App._restore_from_tray` + `App._marshal_to_ui` (bestehend, `ui.py:444`/`:450`).
- Produces: `App.__init__(..., single_instance=None)` — speichert `self._single_instance`.

Reines Wiring (Tk-/Prozess-gebunden) → kein neuer Unit-Test; verifiziert per Suite-grün, Lint und manuellem End-to-End-Test (Doppelstart).

- [ ] **Step 1: `App.__init__` nimmt den Guard entgegen**

In `src/ui.py` die Signatur von `App.__init__` (Zeile ~56) erweitern:
```python
    def __init__(self, root, storage, settings, base_path=".", conflicts_store=None,
                 reservation_store=None, single_instance=None):
```
Direkt im Rumpf (bei den anderen `self.…`-Zuweisungen, nach `self.settings = settings`) ergänzen:
```python
        self._single_instance = single_instance
```

- [ ] **Step 2: `release()` vor dem Skalierungs-Relaunch**

In `src/ui.py::restart_for_scaling` (Zeile ~619) **vor** `subprocess.Popen(cmd)` einfügen:
```python
        if self._single_instance is not None:
            self._single_instance.release()
```
Begründung (als Kommentar mit aufnehmen):
```python
        # Port VOR dem Spawn freigeben, sonst fände die neue Instanz ihn noch
        # belegt, schickte SHOW und beendete sich — die App verschwände beim
        # bloßen Skalierungswechsel.
```
So steht es unmittelbar über dem `try:`/`Popen`. Fail-safety bleibt: schlägt `Popen` fehl, läuft die alte App weiter (dann kurz ungeschützt — akzeptabel).

- [ ] **Step 3: `release()` beim Quit**

In `src/ui.py::_quit_with_sync_push` (Zeile ~600) vor `self.root.destroy()` ergänzen:
```python
        if self._single_instance is not None:
            self._single_instance.release()
```

- [ ] **Step 4: `main.py` — Migration + `acquire` vor dem Tk-Aufbau**

In `src/main.py::main()` direkt **nach** dem `setup_logging`-Block und **vor** `settings = Settings(...)` einfügen:
```python
    from src import single_instance
    from src.autostart import migrate_legacy_autostart

    try:
        migrate_legacy_autostart(base)
    except Exception:
        logging.getLogger(__name__).warning(
            "Autostart-Migration fehlgeschlagen", exc_info=True)

    guard = None
    try:
        guard = single_instance.acquire(base, show_requested="--minimized" not in sys.argv)
        if guard is None:
            return  # Eine Instanz läuft bereits; sie hat SHOW/PING erhalten.
    except Exception:
        logging.getLogger(__name__).warning(
            "Single-Instance-Guard-Fehler — Start ohne Guard", exc_info=True)
        guard = None
```

- [ ] **Step 5: `main.py` — Guard an `App` reichen**

In `src/main.py` den `App(...)`-Aufruf (Zeile ~308) erweitern:
```python
    app = App(root, storage, settings, base_path=base, conflicts_store=conflicts_store,
              reservation_store=reservation_store, single_instance=guard)
```

- [ ] **Step 6: `main.py` — Listener nach dem App-Bau bedienen**

In `src/main.py` nach dem `App(...)`-Aufruf und nach `if "--minimized" in sys.argv: root.iconify()` einfügen (vor dem Sync-Block):
```python
    if guard is not None:
        guard.serve(lambda: app._marshal_to_ui(app._restore_from_tray))
```

- [ ] **Step 7: Verify — Suite grün + Lint**

Run: `pytest -q && ruff check .`
Expected: PASS (keine neuen Failures; `main.py`/`ui.py` importieren sauber).

- [ ] **Step 8: Manueller End-to-End-Test (Doppelstart)**

Aus dem Repo (zwei Terminals bzw. nacheinander):
```
python -m src.main
```
Dann **zweites** `python -m src.main` starten.
Erwartung: die zweite Instanz beendet sich sofort; das Fenster der ersten kommt nach vorn (SHOW, da ohne `--minimized`). Mit `python -m src.main --minimized` als zweiter Start: zweite Instanz beendet sich, **kein** Fenster-Pop (PING).
Evidenz (Log): `Single-Instance…` erscheint nur bei belegtem Fremd-Port; im Normalfall keine Warnung.

- [ ] **Step 9: Commit**

```bash
git add src/main.py src/ui.py
git commit -m "feat(app): Single-Instance-Guard + Autostart-Migration verdrahten"
```

---

### Task 6: Architektur-Referenz aktualisieren

**Files:**
- Modify: `src/CLAUDE.md` (Modul-Liste + Verträge)

**Interfaces:** — (Doku, kein Test.)

- [ ] **Step 1: Guard-Modul + Registry-Vertrag dokumentieren**

In `src/CLAUDE.md` im Abschnitt „Berichte & Plattform/Infra" (bei `autostart.py`) ergänzen:
- `autostart.py`: Windows-Backend nutzt den **HKCU-Run-Registry-Wert** `Zeiterfassung` (gleicher Wertname wie `installer.iss` → strukturell ein Eintrag); `import winreg` lazy (CI-Ubuntu). `is_autostart_enabled()` liest den echten Zustand (Registry **oder** Alt-Shortcut). `migrate_legacy_autostart()` überführt Alt-Shortcuts frozen-gegatet in die Registry.
- Neuer Eintrag `single_instance.py`: Tk-freier Single-Instance-Guard (pro-Nutzer-Port aus `get_base_path()`, `SO_EXCLUSIVEADDRUSE`/`SO_REUSEADDR`, SHOW/PING-Protokoll). `main.py` ruft `acquire()` vor dem Tk-Bau, `serve()` danach; `App.restart_for_scaling`/`_quit_with_sync_push` rufen `release()`.

- [ ] **Step 2: Commit**

```bash
git add src/CLAUDE.md
git commit -m "docs(src): Autostart-Registry-Vertrag + single_instance-Modul dokumentieren"
```

---

## Verifikation vor Abschluss (gesamt)

- [ ] `pytest -q` — alle Tests grün (Evidenz: Zusammenfassungszeile zeigen).
- [ ] `ruff check .` — keine Findings.
- [ ] Manueller Doppelstart-Test aus Task 5 Step 8 durchgeführt (Evidenz: Verhalten beschrieben).

## Übergabe

**VERHALTEN:** Windows-Autostart läuft künftig ausschließlich über den HKCU-Run-Registry-Wert `Zeiterfassung`; App-Checkbox und Installer schreiben denselben Wert → nie mehr zwei Autostart-Trigger. Die Checkbox zeigt den echten Zustand. Bestandsnutzer werden beim ersten Start des neuen (frozen) Builds absichtserhaltend migriert. Ein Guard verhindert parallele Instanzen und holt bei manuellem Zweitstart das vorhandene Fenster nach vorn.

**RISIKO:**
- *Registry-Format-Drift:* Weicht der App-Wert vom Installer-Wert ab (Wertname!), entstünden wieder zwei Einträge. Abgesichert durch `test_windows_run_command_matches_installer_format` + identischen Wertnamen; `installer.iss` bleibt bewusst unverändert.
- *Guard bei Fremd-Port:* Belegt Software den abgeleiteten Port, startet die App ungeschützt weiter (kein Block) — akzeptierter Degraded-Fall, geloggt.
- *Skalierungs-Relaunch:* Ohne `release()` vor `Popen` verschwände die App — durch Task 5 Step 2 abgedeckt.
- Migration ist frozen-only; im Repo-Modus passiert nichts (bewusst).

**TEST (manuell, QA/Prod-Pfad):**
1. *Doppelstart:* App starten, zweites Mal starten → zweite Instanz beendet sich, Fenster der ersten kommt nach vorn. (Task 5 Step 8)
2. *Autostart-Checkbox-Wahrheit (installiert):* Mit Installer-Häkchen „Mit Windows starten" installieren → App öffnen → Einstellungen: Checkbox ist **an** (nicht mehr fälschlich aus). Abhaken → Neustart des Rechners → App startet **nicht** automatisch (Registry-Wert weg).
3. *Migration (Bestandsnutzer-Simulation):* Vor Update Zustand 3 herstellen (Registry-Wert + Startup-Shortcut) → neuen Build starten → nur noch der Registry-Wert existiert, Shortcut ist weg, genau **eine** Instanz beim nächsten Boot.
