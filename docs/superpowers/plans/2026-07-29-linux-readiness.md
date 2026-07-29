# Linux-Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine AppImage-Installation, die ihr Icon findet, deren Autostart ein Update überlebt und die nach dem ersten Start im Anwendungsmenü steht.

**Architecture:** `paths.get_resource_path()` trennt gebündelte Programmdaten (`sys._MEIPASS`) von Nutzerdaten (`get_base_path()`); die Tray-Schicht und die Icon-Zugriffe ziehen darauf um. Ein neues Tk-freies Modul `src/desktop_entry.py` besitzt das `.desktop`-Dateiformat und schreibt den Menüeintrag; `autostart.refresh_linux_target()` zieht die bestehende Autostart-Datei auf den aktuellen `$APPIMAGE`-Pfad nach. Beide Selbstheilungen hängen im vorhandenen Startup-Block von `main.py`.

**Tech Stack:** Python 3.10+, stdlib only (`os`, `shutil`, `shlex`, `platform`, `sys`), pytest mit `monkeypatch`/`tmp_path`.

**Spec:** `docs/superpowers/specs/2026-07-29-linux-readiness-design.md`

## Global Constraints

- **Sprache:** Docstrings, Kommentare und Commit-Messages auf Deutsch — wie im ganzen Repo.
- **Python-Floor:** 3.10. Keine Syntax, die neuer ist (kein `match`-Zwang, keine 3.11-Typing-Features).
- **Tk-frei:** `desktop_entry.py` und `autostart.py` importieren kein `tkinter`. Sie müssen ohne Display testbar bleiben.
- **stdlib-only** in beiden Modulen — keine neue Abhängigkeit, `requirements.txt` wird nicht angefasst.
- **Best-effort, nie fatal:** jeder neue Startup-Schritt fängt `Exception`, loggt über `logging.getLogger(__name__)` und lässt die App weiterlaufen. Vorbild: `secure_file`, `main.py::main` (Logging-Setup).
- **Tests plattformunabhängig:** kein `skipif` auf `platform.system()` für die neuen Tests. Plattform wird per `monkeypatch.setattr("<modul>.platform.system", lambda: "Linux")` gesetzt, HOME per `monkeypatch.setenv`. Muster: `tests/test_autostart.py::TestLinuxAutostart.fake_home`.
- **Commit-Messages über Temp-Datei** (`git commit -F <datei>`) — PowerShell-Here-Strings und Git-Bash-Heredocs brechen hier an Sonderzeichen.
- **Verifikation vor jedem Commit:** `python -m pytest -q`, `python -m ruff check .`, `npx pyright@1.1.411`. Alle drei müssen sauber sein.
- **Branch:** `fix/linux-sni-tray-review`. Nicht neu abzweigen.

---

### Task 1: `paths.get_resource_path()`

Die Wurzel des Befunds: gebündelte Assets liegen in `sys._MEIPASS`, nicht im Nutzerdatenverzeichnis.

**Files:**
- Modify: `src/paths.py` (neue Funktion ans Dateiende)
- Test: `tests/test_paths.py` (anhängen)

**Interfaces:**
- Consumes: nichts
- Produces: `get_resource_path() -> str` — Verzeichnis, unter dem `assets/` liegt. Wird von Task 2, 3 und 5 benutzt.

- [ ] **Step 1: Write the failing tests**

An `tests/test_paths.py` anhängen:

```python
from src.paths import get_resource_path


class TestGetResourcePath:
    """get_resource_path liefert das BUNDLE-Verzeichnis (assets/), nicht das
    Nutzerdaten-Verzeichnis. Auf Windows fielen beide bisher zufällig zusammen,
    auf Linux/macOS nie — daher der eigene Helfer."""

    def test_frozen_uses_meipass(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.paths.sys.frozen", True, raising=False)
        monkeypatch.setattr("src.paths.sys._MEIPASS", str(tmp_path), raising=False)
        assert get_resource_path() == str(tmp_path)

    def test_frozen_without_meipass_falls_back_to_executable_dir(
            self, monkeypatch, tmp_path):
        # sys.frozen ohne _MEIPASS: kein PyInstaller-Bundle. Statt zu werfen
        # das Exe-Verzeichnis nehmen — dort lag assets/ auf Windows schon immer.
        monkeypatch.setattr("src.paths.sys.frozen", True, raising=False)
        monkeypatch.delattr("src.paths.sys._MEIPASS", raising=False)
        exe = tmp_path / "Zeiterfassung.exe"
        monkeypatch.setattr("src.paths.sys.executable", str(exe), raising=False)
        assert get_resource_path() == str(tmp_path)

    def test_script_mode_returns_repo_root(self, monkeypatch):
        monkeypatch.setattr("src.paths.sys.frozen", False, raising=False)
        root = get_resource_path()
        assert os.path.isdir(os.path.join(root, "assets"))

    def test_is_not_the_data_dir_when_they_differ(self, monkeypatch, tmp_path):
        """Der eigentliche Punkt: auf Linux zeigen die beiden Helfer
        auseinander. Fiele get_resource_path auf get_base_path zurück, wäre
        der Befund nicht behoben."""
        monkeypatch.setattr("src.paths.sys.frozen", True, raising=False)
        monkeypatch.setattr("src.paths.sys._MEIPASS", str(tmp_path / "bundle"),
                            raising=False)
        monkeypatch.setattr("src.paths.platform.system", lambda: "Linux")
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.delenv("ZEITERFASSUNG_DATA_DIR", raising=False)
        assert get_resource_path() != get_base_path()
```

`tests/test_paths.py` hat oben bereits `import os`, `import sys`, `import pytest` und `from src.paths import get_base_path` — es fehlt nur der Import von `get_resource_path`, den der Testblock oben schon mitbringt.

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_paths.py -q
```
Erwartet: FAIL mit `ImportError: cannot import name 'get_resource_path'`.

- [ ] **Step 3: Write the implementation**

Ans Ende von `src/paths.py`:

```python
def get_resource_path():
    """Verzeichnis der GEBÜNDELTEN Programmdaten (`assets/`) — read-only.

    Frozen: `sys._MEIPASS` (PyInstaller; onefile = Temp-Extraktion, onedir =
    `_internal/`). Script-Modus: Repo-Root. Fallback bei gesetztem
    `sys.frozen` ohne `_MEIPASS`: das Verzeichnis der Exe.

    ABGRENZUNG zu `get_base_path()` — das ist der ganze Zweck dieser Funktion:

    - `get_base_path()` liefert NUTZERdaten: schreibbar, persistent,
      plattformabhängig (`entries.json`, `settings.json`, `token.json`).
    - `get_resource_path()` liefert PROGRAMMdaten: read-only, kommt mit dem
      Build, verschwindet bei einer AppImage nach dem Beenden wieder.

    Auf Windows fallen beide zufällig zusammen (Nutzerdaten liegen dort im
    Installationsordner), auf macOS und Linux nie. Deshalb fand vorher jeder
    Icon-Zugriff über `get_base_path()` auf diesen Plattformen nichts. Wer
    eine mit dem Build ausgelieferte Datei sucht, nimmt diese Funktion.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return meipass
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_paths.py -q
python -m pytest -q
python -m ruff check .
```
Erwartet: alles grün, keine Regression in der Gesamtsuite.

- [ ] **Step 5: Commit**

```bash
git add src/paths.py tests/test_paths.py
git commit -F <temp-datei>
```
Message: `feat(paths): get_resource_path() als Gegenstück zu get_base_path()`

---

### Task 2: Tray- und Icon-Schicht auf `resource_path` umstellen

Behebt den Befund tatsächlich. Fasst Windows und macOS mit an — die Suite und ein Build-Test müssen das absichern.

**Files:**
- Modify: `src/tray.py` (Docstrings + `_PystrayBackend.__init__`/`_load_image`, `TrayIcon.__init__`/`start`)
- Modify: `src/tray_mac.py:35-48`
- Modify: `src/tray_linux.py` (`icon_pixmaps`, `LinuxTrayBackend.__init__`, `_serve`, `_notify`)
- Modify: `src/ui.py:95`, `:201-208`, `:473-474`
- Modify: `src/theme.py:646-668`
- Test: `tests/test_tray.py`, `tests/test_tray_linux.py`, `tests/test_tray_linux_dbus.py`

**Interfaces:**
- Consumes: `paths.get_resource_path()` aus Task 1
- Produces: alle drei Tray-Backends und die `TrayIcon`-Fassade nehmen als erstes Positionsargument `resource_path` statt `base_path`; `tray_linux.icon_pixmaps(resource_path, sizes=(32, 64, 128))`.

- [ ] **Step 1: Bestehende Tests auf den neuen Namen umschreiben (sie müssen danach rot sein)**

In `tests/test_tray_linux.py`:

```python
def test_backend_keeps_the_facade_constructor_signature():
    """Die Fassade instanziiert alle Backends gleich (tray.TrayIcon.start)."""
    backend = LinuxTrayBackend("res", on_show=lambda: None,
                               on_quit=lambda: None, actions=[])
    assert backend.resource_path == "res"
```

In `tests/test_tray.py::test_facade_instantiates_and_delegates` das Fake-Backend:

```python
    class FakeBackend:
        def __init__(self, resource_path, on_show, on_quit, actions=None):
            seen["init"] = (resource_path, on_show, on_quit, actions)
```
und die Assertion auf `seen["init"] == ("base", show, quit_, acts)` bleibt unverändert (der Wert ist nur ein String).

Neuer Test in `tests/test_tray_linux.py`, der den eigentlichen Befund festnagelt:

```python
def test_icon_pixmaps_takes_the_resource_path_not_the_data_dir(tmp_path):
    """Regression für den Linux-Icon-Befund: gesucht wird unter dem
    BUNDLE-Verzeichnis. Läge hier wieder get_base_path() an, fände die
    AppImage nie ein Icon und das SNI-Item bliebe leer."""
    pytest.importorskip("PIL")
    from PIL import Image
    bundle = tmp_path / "bundle" / "assets"
    bundle.mkdir(parents=True)
    Image.new("RGBA", (8, 8), (1, 2, 3, 4)).save(bundle / "margenheld-icon.png")
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    assert icon_pixmaps(str(tmp_path / "bundle"), sizes=(8,)) != []
    assert icon_pixmaps(str(data_dir), sizes=(8,)) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_tray.py tests/test_tray_linux.py -q
```
Erwartet: FAIL mit `AttributeError: 'LinuxTrayBackend' object has no attribute 'resource_path'`.

- [ ] **Step 3: Umbenennung durchziehen**

`src/tray.py` — in `_PystrayBackend.__init__` und `TrayIcon.__init__` jeweils:

```python
    def __init__(self, resource_path, on_show, on_quit, actions=None):
        self.resource_path = resource_path
```
und in `_PystrayBackend._load_image`:
```python
        png = os.path.join(self.resource_path, "assets", "margenheld-icon.png")
```
In `TrayIcon.start` die Backend-Instanziierung:
```python
        backend = backend_cls(
            self.resource_path, self._on_show, self._on_quit, self._actions)
```

`src/tray_mac.py:35-36` und `:48` analog (`self.base_path` → `self.resource_path`).

`src/tray_linux.py`:
```python
def icon_pixmaps(resource_path, sizes=(32, 64, 128)):
    ...
    png = os.path.join(resource_path, "assets", "margenheld-icon.png")
```
```python
    def __init__(self, resource_path, on_show, on_quit, actions=None):
        self.resource_path = resource_path
```
in `_serve`: `icon_pixmaps(self.resource_path)`; in `_notify`:
```python
        icon = os.path.join(self.resource_path, "assets", "margenheld-icon.png")
```

`src/ui.py`:
- Zeile 95: `self._setup_window_icon(get_resource_path())`
- Zeile 201: `def _setup_window_icon(self, resource_path):` und die beiden `os.path.join(resource_path, …)` darunter
- Zeile 473-474: `TrayIcon(get_resource_path(), …)` statt `self.base_path`
- `src/ui.py` importiert bisher **gar nichts** aus `src.paths`. Neue Zeile zu den `from src.…`-Importen (alphabetisch zwischen `src.grid_renderer` und `src.reminder_scheduler`):
  ```python
  from src.paths import get_resource_path
  ```

`src/theme.py:667`: `base = get_resource_path()` statt `get_base_path()`. `theme.py` importiert `get_base_path` bereits — den Import auf `from src.paths import get_base_path, get_resource_path` erweitern und prüfen, ob `get_base_path` dort noch anderweitig benutzt wird (`grep -n "get_base_path" src/theme.py`); wenn nicht, ganz ersetzen, damit ruff keinen ungenutzten Import meldet.

Zusätzlich in `tray.py` die Klassen-Docstring von `_PystrayBackend` und den Modul-Docstring dort anpassen, wo `base_path` erwähnt wird.

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest -q
python -m ruff check .
npx pyright@1.1.411
```
Erwartet: alles grün. `grep -rn "base_path" src/tray*.py` darf nichts mehr liefern.

- [ ] **Step 5: Windows-Regression am echten Artefakt prüfen**

Die Suite deckt den Windows-Pfad nicht ab — `_MEIPASS` gibt es nur im Frozen-Build. Deshalb:

```
python build.py
```
Danach den Inhalt von `dist\Zeiterfassung\` nach `%LOCALAPPDATA%\Programs\Zeiterfassung\` kopieren (Inno Setup fehlt lokal) und die App starten. Prüfen: **Fenster-Icon** in Titelleiste und Taskleiste vorhanden, **Tray-Icon** zeigt das Logo (nicht das weiße 16×16-Fallback-Rechteck aus `_load_image`), **Toast** mit Logo.

Schlägt das fehl, ist `_MEIPASS` im onedir-Build nicht das Verzeichnis mit `assets/` — dann `get_resource_path()` um einen Zweig ergänzen, der zusätzlich `dirname(sys.executable)` prüft, und den Befund im Plan notieren.

- [ ] **Step 6: Commit**

```bash
git add src/tray.py src/tray_mac.py src/tray_linux.py src/ui.py src/theme.py tests/
git commit -F <temp-datei>
```
Message: `fix(icons): Assets über get_resource_path statt über das Datenverzeichnis suchen`

---

### Task 3: `src/desktop_entry.py`

**Files:**
- Create: `src/desktop_entry.py`
- Modify: `src/autostart.py` (`_exec_line` entfernen, aus `desktop_entry` importieren)
- Test: `tests/test_desktop_entry.py` (neu)

**Interfaces:**
- Consumes: nichts aus früheren Tasks (`resource_path`/`data_path` kommen als Parameter)
- Produces:
  - `exec_line(target: str, arguments: str) -> str`
  - `ensure_icon(resource_path: str, data_path: str) -> str | None`
  - `menu_entry_path() -> str`
  - `write_menu_entry(target: str, icon_path: str | None) -> None`

- [ ] **Step 1: Write the failing tests**

`tests/test_desktop_entry.py`:

```python
# tests/test_desktop_entry.py
"""Menüeintrag und .desktop-Format — plattformunabhängig über tmp_path/HOME."""

import os

import pytest

from src.desktop_entry import (
    ensure_icon,
    exec_line,
    menu_entry_path,
    write_menu_entry,
)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    return tmp_path


def test_exec_line_leaves_simple_paths_alone():
    assert exec_line("/opt/Zeiterfassung.AppImage", "") == "/opt/Zeiterfassung.AppImage"


def test_exec_line_appends_arguments():
    assert exec_line("/opt/Z.AppImage", "--minimized") == "/opt/Z.AppImage --minimized"


def test_exec_line_quotes_paths_with_spaces():
    # Audit N12: unquoted zerbricht Exec an der GLib-Tokenisierung.
    assert exec_line("/opt/My Apps/Z.AppImage", "") == "'/opt/My Apps/Z.AppImage'"


def test_menu_entry_path_is_in_xdg_applications(fake_home):
    assert menu_entry_path() == os.path.join(
        str(fake_home), ".local", "share", "applications", "Zeiterfassung.desktop")


def test_write_menu_entry_creates_a_valid_entry(fake_home):
    write_menu_entry("/opt/Zeiterfassung.AppImage", "/data/icon.png")
    content = open(menu_entry_path(), encoding="utf-8").read()
    assert content.startswith("[Desktop Entry]\n")
    assert "Type=Application\n" in content
    assert "Name=Zeiterfassung\n" in content
    assert "Exec=/opt/Zeiterfassung.AppImage\n" in content
    assert "Icon=/data/icon.png\n" in content
    assert "Terminal=false\n" in content
    assert "Categories=Office;\n" in content


def test_write_menu_entry_omits_icon_line_when_there_is_no_icon(fake_home):
    """Eine Icon-Zeile mit leerem Wert wäre schlechter als keine."""
    write_menu_entry("/opt/Zeiterfassung.AppImage", None)
    content = open(menu_entry_path(), encoding="utf-8").read()
    assert "Icon=" not in content


def test_write_menu_entry_is_idempotent_and_refreshes_exec(fake_home):
    write_menu_entry("/opt/alt.AppImage", None)
    write_menu_entry("/opt/neu.AppImage", None)
    content = open(menu_entry_path(), encoding="utf-8").read()
    assert "Exec=/opt/neu.AppImage\n" in content
    assert "alt.AppImage" not in content


def test_ensure_icon_copies_the_bundled_png(tmp_path):
    bundle = tmp_path / "bundle" / "assets"
    bundle.mkdir(parents=True)
    (bundle / "margenheld-icon.png").write_bytes(b"PNGDATA")
    data = tmp_path / "data"
    data.mkdir()

    result = ensure_icon(str(tmp_path / "bundle"), str(data))
    assert result == str(data / "icon.png")
    assert (data / "icon.png").read_bytes() == b"PNGDATA"


def test_ensure_icon_does_not_copy_again_when_sizes_match(tmp_path):
    bundle = tmp_path / "bundle" / "assets"
    bundle.mkdir(parents=True)
    (bundle / "margenheld-icon.png").write_bytes(b"PNGDATA")
    data = tmp_path / "data"
    data.mkdir()
    ensure_icon(str(tmp_path / "bundle"), str(data))
    target = data / "icon.png"
    target.write_bytes(b"MARKIER")   # gleiche Länge wie b"PNGDATA"

    ensure_icon(str(tmp_path / "bundle"), str(data))
    assert target.read_bytes() == b"MARKIER"   # nicht überschrieben


def test_ensure_icon_recopies_when_size_differs(tmp_path):
    bundle = tmp_path / "bundle" / "assets"
    bundle.mkdir(parents=True)
    (bundle / "margenheld-icon.png").write_bytes(b"NEUEDATEN-LAENGER")
    data = tmp_path / "data"
    data.mkdir()
    (data / "icon.png").write_bytes(b"ALT")

    ensure_icon(str(tmp_path / "bundle"), str(data))
    assert (data / "icon.png").read_bytes() == b"NEUEDATEN-LAENGER"


def test_ensure_icon_returns_none_without_a_bundled_png(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    assert ensure_icon(str(tmp_path / "leer"), str(data)) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_desktop_entry.py -q
```
Erwartet: FAIL mit `ModuleNotFoundError: No module named 'src.desktop_entry'`.

- [ ] **Step 3: Write the implementation**

`src/desktop_entry.py`:

```python
# src/desktop_entry.py
"""Freedesktop-`.desktop`-Dateien: Menüeintrag und das gemeinsame Format.

Besitzer des Formats — `autostart.py` schreibt seine Autostart-Datei über das
`exec_line` von hier, statt eine zweite Quoting-Regel zu pflegen (Audit N17:
kein Modul benutzt den privaten Namen eines anderen). Richtung stimmt so:
Autostart ist ein Sonderfall einer .desktop-Datei, nicht umgekehrt.

Tk-frei und stdlib-only, damit ohne Display testbar.
"""

import logging
import os
import shlex
import shutil

logger = logging.getLogger(__name__)

ICON_FILENAME = "icon.png"
BUNDLED_ICON = os.path.join("assets", "margenheld-icon.png")


def exec_line(target, arguments):
    """Baut die `Exec=`-Zeile mit shell-korrektem Quoting (Audit N12): ein Pfad
    mit Leerzeichen o.ä. zerbricht die .desktop-Datei sonst. `shlex.quote`
    deckt sich mit GLibs Exec-Parsing (`g_shell_parse_argv`). Werte ohne
    Sonderzeichen bleiben unverändert."""
    parts = [shlex.quote(target)]
    if arguments:
        parts.extend(shlex.quote(a) for a in arguments.split())
    return " ".join(parts)


def menu_entry_path():
    return os.path.join(
        os.path.expanduser("~"),
        ".local", "share", "applications", "Zeiterfassung.desktop",
    )


def ensure_icon(resource_path, data_path):
    """Kopiert das gebündelte PNG einmalig ins Datenverzeichnis und liefert den
    Zielpfad (oder `None`).

    Nötig, weil `Icon=` den AppImage-Mount ÜBERLEBEN muss: ein Pfad in
    `sys._MEIPASS` ist tot, sobald die App beendet ist, und das Menü zeigte
    dann ein leeres Icon.

    Idempotent über einen Dateigrößen-Vergleich — bewusst ohne Hash: das Icon
    ändert sich praktisch nie, und ein Hash pro Start wäre Aufwand ohne
    Gegenwert.
    """
    source = os.path.join(resource_path, BUNDLED_ICON)
    if not os.path.exists(source):
        logger.warning("Gebündeltes Icon %s fehlt — Menüeintrag ohne Icon", source)
        return None
    target = os.path.join(data_path, ICON_FILENAME)
    try:
        if (os.path.exists(target)
                and os.path.getsize(target) == os.path.getsize(source)):
            return target
        shutil.copyfile(source, target)
        return target
    except OSError:
        logger.warning("Icon konnte nicht ins Datenverzeichnis kopiert werden",
                       exc_info=True)
        return None


def write_menu_entry(target, icon_path):
    """Schreibt `~/.local/share/applications/Zeiterfassung.desktop`.

    Wird bei jedem Start überschrieben, damit `Exec=` nach einem Update von
    selbst auf die neue AppImage zeigt — dieselbe Selbstheilung wie beim
    Autostart.

    `StartupWMClass` ist eine begründete Annahme (Tk leitet die WM-Klasse vom
    Basisnamen der Exe ab), nicht verifiziert. Stimmt sie nicht, gruppiert der
    Desktop das Fenster nur nicht unter dem Menüeintrag — kosmetisch.
    """
    path = menu_entry_path()
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=Zeiterfassung",
        "Comment=Arbeitszeiten erfassen, berichten und versenden",
        f"Exec={exec_line(target, '')}",
    ]
    if icon_path:
        lines.append(f"Icon={icon_path}")
    lines.extend([
        "Terminal=false",
        "Categories=Office;",
        "StartupWMClass=Zeiterfassung",
    ])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
```

- [ ] **Step 4: `autostart.py` auf den gemeinsamen Helfer umstellen**

`_exec_line` (aktuell `src/autostart.py:198-211`) ersatzlos löschen und oben importieren:

```python
from src.desktop_entry import exec_line
```
In `_enable_linux` den Aufruf anpassen:
```python
    exec_content = exec_line(target, arguments)
```
und die `content`-Zeile entsprechend (`f"Exec={exec_content}\n"`).

Prüfen, dass `tests/test_autostart.py::TestLinuxAutostart` weiter grün ist — die drei Quoting-Tests dort decken denselben Code über den neuen Pfad ab und sind der Beleg, dass der Umzug nichts verändert hat.

- [ ] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_desktop_entry.py tests/test_autostart.py -q
python -m pytest -q
python -m ruff check .
npx pyright@1.1.411
```
Erwartet: alles grün.

- [ ] **Step 6: Commit**

```bash
git add src/desktop_entry.py src/autostart.py tests/test_desktop_entry.py
git commit -F <temp-datei>
```
Message: `feat(linux): desktop_entry.py als Besitzer des .desktop-Formats`

---

### Task 4: `autostart.refresh_linux_target()`

**Files:**
- Modify: `src/autostart.py`
- Test: `tests/test_autostart.py` (neue Klasse anhängen)

**Interfaces:**
- Consumes: `resolve_autostart_target`, `_linux_desktop_path`, `_enable_linux` (alle bereits in `autostart.py`)
- Produces: `refresh_linux_target(base_path: str) -> None` — für den Startup-Hook in Task 5.

- [ ] **Step 1: Write the failing tests**

An `tests/test_autostart.py` anhängen:

```python
class TestRefreshLinuxTarget:
    """Nach einem Update liegt eine AppImage mit NEUEM Dateinamen auf der
    Platte (updater.pick_asset_url liefert Zeiterfassung-<ver>-x86_64.AppImage,
    und die App ersetzt sich nie selbst). Ohne Nachziehen startet bei jeder
    Anmeldung stillschweigend die Vorgängerversion."""

    @pytest.fixture
    def frozen_linux(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.delenv("HOMEDRIVE", raising=False)
        monkeypatch.delenv("HOMEPATH", raising=False)
        monkeypatch.setattr("src.autostart.platform.system", lambda: "Linux")
        monkeypatch.setattr("src.autostart.sys.frozen", True, raising=False)
        monkeypatch.setenv("APPIMAGE", "/home/sven/Zeiterfassung-2.0.0.AppImage")
        return tmp_path

    def test_rewrites_a_stale_exec_line(self, frozen_linux):
        from src.autostart import refresh_linux_target
        enable_autostart("/home/sven/Zeiterfassung-1.0.0.AppImage", "--minimized")
        refresh_linux_target(str(frozen_linux))
        content = open(_linux_desktop_path(), encoding="utf-8").read()
        assert "Exec=/home/sven/Zeiterfassung-2.0.0.AppImage --minimized" in content
        assert "1.0.0" not in content

    def test_noop_when_autostart_was_never_enabled(self, frozen_linux):
        from src.autostart import refresh_linux_target
        refresh_linux_target(str(frozen_linux))
        assert not os.path.exists(_linux_desktop_path())

    def test_noop_when_not_frozen(self, frozen_linux, monkeypatch):
        """Im Repo-Modus zeigte das Ziel sonst auf python.exe + Repo — dieselbe
        Selbstbeschädigung, gegen die migrate_legacy_autostart gegated ist."""
        from src.autostart import refresh_linux_target
        enable_autostart("/home/sven/Zeiterfassung-1.0.0.AppImage", "--minimized")
        monkeypatch.setattr("src.autostart.sys.frozen", False, raising=False)
        refresh_linux_target(str(frozen_linux))
        content = open(_linux_desktop_path(), encoding="utf-8").read()
        assert "1.0.0" in content

    def test_noop_on_other_platforms(self, frozen_linux, monkeypatch):
        from src.autostart import refresh_linux_target
        enable_autostart("/home/sven/Zeiterfassung-1.0.0.AppImage", "--minimized")
        monkeypatch.setattr("src.autostart.platform.system", lambda: "Windows")
        refresh_linux_target(str(frozen_linux))
        content = open(_linux_desktop_path(), encoding="utf-8").read()
        assert "1.0.0" in content

    def test_noop_without_appimage_env(self, frozen_linux, monkeypatch):
        """Nackte PyInstaller-Ausgabe aus build.yml: kein stabiler Pfad, auf den
        man zeigen könnte."""
        from src.autostart import refresh_linux_target
        enable_autostart("/home/sven/Zeiterfassung-1.0.0.AppImage", "--minimized")
        monkeypatch.delenv("APPIMAGE", raising=False)
        refresh_linux_target(str(frozen_linux))
        content = open(_linux_desktop_path(), encoding="utf-8").read()
        assert "1.0.0" in content
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_autostart.py::TestRefreshLinuxTarget -q
```
Erwartet: FAIL mit `ImportError: cannot import name 'refresh_linux_target'`.

- [ ] **Step 3: Write the implementation**

In `src/autostart.py` nach `migrate_legacy_autostart` einfügen:

```python
def refresh_linux_target(base_path):
    """Zieht die Autostart-Datei auf den aktuellen `$APPIMAGE`-Pfad nach.

    Der Updater ersetzt die AppImage nie selbst (`update_banner._open_download`
    öffnet nur den Browser), und die Assets tragen die Version im Dateinamen.
    Ohne diesen Schritt zeigt `~/.config/autostart/Zeiterfassung.desktop` nach
    jedem Update weiter auf die alte Datei — der Nutzer startet bei jeder
    Anmeldung stillschweigend die Vorgängerversion.

    Vier Gates, alle müssen zutreffen:
    1. frozen — im Repo-Modus zeigte das Ziel sonst auf python.exe + Repo
       (dieselbe Selbstbeschädigung, gegen die migrate_legacy_autostart
       gegated ist).
    2. Linux.
    3. `$APPIMAGE` gesetzt — die nackte PyInstaller-Ausgabe hat das nicht.
    4. Die Datei existiert bereits — wer keinen Autostart eingeschaltet hat,
       bekommt hier auch keinen.
    """
    if not getattr(sys, "frozen", False):
        return
    if platform.system() != "Linux":
        return
    if not os.environ.get("APPIMAGE"):
        return
    if not os.path.exists(_linux_desktop_path()):
        return
    target, arguments = resolve_autostart_target(base_path)
    _enable_linux(target, arguments)
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_autostart.py -q
python -m pytest -q
python -m ruff check .
```

- [ ] **Step 5: Commit**

```bash
git add src/autostart.py tests/test_autostart.py
git commit -F <temp-datei>
```
Message: `fix(autostart): Linux-Ziel beim Start auf die aktuelle AppImage nachziehen`

---

### Task 5: Startup-Hook und Dokumentation

**Files:**
- Modify: `src/main.py:491-498`
- Modify: `README.md` (Linux-Installationsabschnitt, Plattform-Tabelle)
- Modify: `src/CLAUDE.md` (Modul-Liste, paths-Abgrenzung)
- Modify: `docs/known-limitations.md`
- Test: `tests/test_main_linux_integration.py` (neu)

**Interfaces:**
- Consumes: `get_resource_path()` (Task 1), `desktop_entry.ensure_icon`/`write_menu_entry` (Task 3), `autostart.refresh_linux_target` (Task 4)
- Produces: nichts für spätere Tasks — das ist der letzte.

- [ ] **Step 1: Write the failing test**

`tests/test_main_linux_integration.py`:

```python
# tests/test_main_linux_integration.py
"""Der Startup-Hook: beide Selbstheilungen laufen, und ein Fehler darin darf
den Start NIE verhindern (best-effort, wie das Logging-Setup)."""

import pytest

from src.main import _refresh_linux_integration


@pytest.fixture
def linux_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr("src.main.platform.system", lambda: "Linux")
    monkeypatch.setattr("src.main.sys.frozen", True, raising=False)
    monkeypatch.setenv("APPIMAGE", "/home/sven/Zeiterfassung-2.0.0.AppImage")
    return tmp_path


def test_writes_menu_entry_and_refreshes_autostart(linux_frozen, monkeypatch):
    calls = []
    monkeypatch.setattr("src.main.refresh_linux_target",
                        lambda base: calls.append(("autostart", base)))
    monkeypatch.setattr("src.main.ensure_icon",
                        lambda res, data: "/data/icon.png")
    monkeypatch.setattr("src.main.write_menu_entry",
                        lambda target, icon: calls.append(("menu", target, icon)))

    _refresh_linux_integration(str(linux_frozen))

    assert ("autostart", str(linux_frozen)) in calls
    assert ("menu", "/home/sven/Zeiterfassung-2.0.0.AppImage",
            "/data/icon.png") in calls


def test_noop_on_windows(linux_frozen, monkeypatch):
    monkeypatch.setattr("src.main.platform.system", lambda: "Windows")
    calls = []
    monkeypatch.setattr("src.main.write_menu_entry",
                        lambda target, icon: calls.append("menu"))
    monkeypatch.setattr("src.main.refresh_linux_target", lambda base: None)
    _refresh_linux_integration(str(linux_frozen))
    assert calls == []


def test_noop_without_appimage_env(linux_frozen, monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    calls = []
    monkeypatch.setattr("src.main.write_menu_entry",
                        lambda target, icon: calls.append("menu"))
    monkeypatch.setattr("src.main.refresh_linux_target", lambda base: None)
    _refresh_linux_integration(str(linux_frozen))
    assert calls == []


def test_a_throwing_step_does_not_escape(linux_frozen, monkeypatch):
    """Ein nicht schreibbares ~/.local/share/applications darf den Start nicht
    verhindern — ungeschriebener Menüeintrag ist der Status quo, ein
    verhinderter Start wäre eine Regression."""
    def boom(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr("src.main.refresh_linux_target", boom)
    monkeypatch.setattr("src.main.ensure_icon", boom)
    monkeypatch.setattr("src.main.write_menu_entry", boom)

    _refresh_linux_integration(str(linux_frozen))   # darf nicht werfen
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_main_linux_integration.py -q
```
Erwartet: FAIL mit `ImportError: cannot import name '_refresh_linux_integration'`.

- [ ] **Step 3: Write the implementation**

In `src/main.py` — `os`, `platform`, `sys` und `logging` sind bereits auf Modulebene importiert (Zeilen 3–6), es fehlen nur die drei neuen Namen. Zeile 29 erweitern und zwei Zeilen ergänzen:

```python
from src.autostart import refresh_linux_target
from src.desktop_entry import ensure_icon, write_menu_entry
from src.paths import get_base_path, get_resource_path
```

**Bewusst auf Modulebene**, obwohl `migrate_legacy_autostart` zwei Zeilen weiter unten lazy **in** `main()` importiert wird: der Test monkeypatcht `src.main.refresh_linux_target` und braucht den Namen deshalb im Modul-Namensraum. Beide Module sind stdlib-only (`winreg` in `autostart` ist selbst lazy), es entsteht also kein Importrisiko für die CI.

Neue Funktion vor `main()`:

```python
def _refresh_linux_integration(base):
    """Linux-Desktop-Integration beim Start nachziehen (best-effort).

    Zwei Selbstheilungen mit derselben Ursache: der Updater ersetzt die
    AppImage nicht selbst, und ihr Dateiname trägt die Version. Beide Ziele
    zeigen sonst nach einem Update auf die alte Datei.

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
    try:
        write_menu_entry(appimage, ensure_icon(get_resource_path(), base))
    except Exception:
        logging.getLogger(__name__).warning(
            "Menüeintrag konnte nicht geschrieben werden", exc_info=True)
```

In `main()` direkt hinter dem `migrate_legacy_autostart`-Block:

```python
    _refresh_linux_integration(base)
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest -q
python -m ruff check .
npx pyright@1.1.411
```

- [ ] **Step 5: Dokumentation nachziehen**

`README.md`, Linux-Installationsabschnitt (nach dem `chmod +x`-Block) ergänzen:

```markdown
Beim ersten Start legt die App einen Eintrag im Anwendungsmenü an
(`~/.local/share/applications/Zeiterfassung.desktop`) und hält ihn danach
automatisch aktuell. Dasselbe gilt für den Autostart, falls aktiviert: beide
zeigen nach einem Update von selbst auf die neue AppImage — vorausgesetzt, du
startest die neue Datei einmal. Ein Integrationswerkzeug wie `appimaged` wird
nicht gebraucht.
```

`src/CLAUDE.md`, Modul-Liste um einen Eintrag ergänzen:

```markdown
- `src/desktop_entry.py` — Freedesktop-`.desktop`-Dateien: Menüeintrag
  (`~/.local/share/applications/`) und das gemeinsame `exec_line`-Quoting, das
  `autostart.py` mitbenutzt. Besitzer des Formats (Audit N17). `ensure_icon`
  legt eine persistente Icon-Kopie im Datenverzeichnis ab, weil `Icon=` den
  AppImage-Mount überleben muss.
```
und im `paths.py`-Abschnitt die Abgrenzung ergänzen:
```markdown
  `get_resource_path()` ist das Gegenstück: gebündelte Programmdaten
  (`sys._MEIPASS`), nicht Nutzerdaten. Icon-/Asset-Zugriffe gehen über diese
  Funktion — über `get_base_path()` fanden sie auf Linux und macOS nichts.
```

`docs/known-limitations.md`, neuer Abschnitt:

```markdown
## Linux: Reste nach dem Löschen der AppImage

Löscht der Nutzer die AppImage, bleiben Menüeintrag und Autostart-Datei
zurück und zeigen ins Leere. Die App kann nicht aufräumen, wenn sie nicht
mehr startet, und das AppImage-Format kennt keinen Deinstallations-Hook.
Gilt gleichermaßen für die zurückbleibenden Nutzerdaten inkl. `token.json` —
das ist plattformübergreifend erfasst in
[#183](https://github.com/margenheld/Zeiterfassung/issues/183).

Der Autostart heilt außerdem erst, **nachdem** die neue AppImage einmal
gestartet wurde. Wer die neue Version herunterlädt und nie öffnet, startet
weiter die alte — ohne Hinweis.
```

- [ ] **Step 6: Commit**

```bash
git add src/main.py tests/test_main_linux_integration.py README.md src/CLAUDE.md docs/known-limitations.md
git commit -F <temp-datei>
```
Message: `feat(linux): Desktop-Integration beim Start nachziehen`

---

## Abschluss

- [ ] **Volle Verifikation**

```
python -m pytest -q
python -m ruff check .
npx pyright@1.1.411
```

- [ ] **Push und PR**

```bash
git push origin fix/linux-sni-tray-review
```
PR gegen `margenheld:master` öffnen (`gh pr create --repo margenheld/Zeiterfassung --base master --head Xveyn:fix/linux-sni-tray-review --body-file <datei>`). Der PR löst #182 ab — das gehört in den Body, zusammen mit dem Hinweis, dass #182 danach geschlossen werden kann.

- [ ] **Im PR-Body vermerken, was NICHT verifiziert ist**

Das Tray-Gate und die Desktop-Integration sind auf der Windows-Dev-Maschine nicht prüfbar. Der Pre-Release-Vorschlag aus `CLAUDE.md` („Plattformspezifische PRs — Pre-Release vorschlagen") gilt hier voll: vor dem Merge einen Pre-Release bauen und auf Debian 13 / Plasma 6 durchgehen. Prüfliste steht in der Spec unter „Verifikation / Übergabe".
