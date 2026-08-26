"""Guards für die PyInstaller-Aufrufe in scripts/build.py.

Kein echter Build (das macht die CI) — nur die Kommandozeilen-Konstruktion,
weil an einzelnen Flags eine ganze Fehlerklasse hängt (#118: onefile-Extraktions-
Race). subprocess.run wird gemockt, PyInstaller läuft nie.

Das Skript liegt in `scripts/` und ist damit kein importierbares Modul —
`scripts` ist bewusst kein Package (dort liegen Werkzeuge, keine App-Teile).
Deshalb wird es hier über seinen Pfad geladen statt per `import build`.
Der Pfad wird vom Ort DIESER Datei abgeleitet, nicht vom Arbeitsverzeichnis,
damit der Test unabhängig davon läuft, von wo pytest gestartet wurde.
"""

import importlib.util
import pathlib

_BUILD_PY = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "build.py"
_spec = importlib.util.spec_from_file_location("_build_script", _BUILD_PY)
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def _capture_pyinstaller_cmd(monkeypatch, build_fn):
    """Ruft build_fn() mit gemocktem subprocess.run/Notices/Inno auf und
    liefert das PyInstaller-Kommando (der erste subprocess.run-Call)."""
    calls = []
    monkeypatch.setattr(build.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(build, "generate_third_party_notices", lambda: None)
    # Inno/create-dmg/appimagetool nicht suchen — nur der PyInstaller-Teil zählt.
    monkeypatch.setattr(build, "_find_inno_compiler", lambda: None, raising=False)
    monkeypatch.setattr(build.shutil, "which", lambda _name: None)
    build_fn()
    return calls[0]


def test_windows_builds_onedir_not_onefile(monkeypatch):
    """#118: Windows MUSS onedir bauen — onefile entpackt pro Start neu und
    triggert den Bootloader-DLL-Race."""
    cmd = _capture_pyinstaller_cmd(monkeypatch, build.build_windows)
    assert "--onedir" in cmd
    assert "--onefile" not in cmd


def test_windows_stays_noconsole(monkeypatch):
    """--noconsole darf beim Umbau nicht verloren gehen (sonst blitzt ein
    Konsolenfenster auf)."""
    cmd = _capture_pyinstaller_cmd(monkeypatch, build.build_windows)
    assert "--noconsole" in cmd


def test_linux_stays_onefile(monkeypatch):
    """Linux bleibt bewusst onefile — die AppImage mountet selbst, #118 ist
    Windows-spezifisch."""
    cmd = _capture_pyinstaller_cmd(monkeypatch, build.build_linux)
    assert "--onefile" in cmd
    assert "--onedir" not in cmd


def test_all_platforms_keep_mandatory_collect_all(monkeypatch):
    """Vier --collect-all müssen auf jeder Plattform gebündelt sein. Drei macht
    CLAUDE.md für PDF/Feiertage zur Pflicht (xhtml2pdf, reportlab, holidays) —
    ohne sie schlagen PDF-Erzeugung bzw. Feiertags-Lookup im Artefakt stumm
    fehl; pystray kommt fürs Tray/Minimize-to-Tray dazu (eigener Fehlermodus).
    `--collect-all` und der Paketname sind separate Listenelemente, daher
    Element-Test."""
    for build_fn in (build.build_windows, build.build_linux):
        cmd = _capture_pyinstaller_cmd(monkeypatch, build_fn)
        for pkg in ("xhtml2pdf", "reportlab", "holidays", "pystray"):
            assert pkg in cmd, f"{pkg} fehlt im {build_fn.__name__}-Kommando"


def test_linux_bundles_dbus_fast(monkeypatch):
    """Das SNI-Tray importiert dbus_fast lazy — ohne --collect-all fehlt es in
    der AppImage und das Tray stirbt beim Start statt beim Build (#42)."""
    cmd = _capture_pyinstaller_cmd(monkeypatch, build.build_linux)
    assert "dbus_fast" in cmd


def test_windows_does_not_bundle_dbus_fast(monkeypatch):
    """dbus_fast ist Linux-only (Marker in requirements.txt) — auf Windows wäre
    das --collect-all ein Build-Fehler."""
    cmd = _capture_pyinstaller_cmd(monkeypatch, build.build_windows)
    assert "dbus_fast" not in cmd
