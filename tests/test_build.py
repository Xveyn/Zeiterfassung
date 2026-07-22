"""Guards für die PyInstaller-Aufrufe in build.py.

Kein echter Build (das macht die CI) — nur die Kommandozeilen-Konstruktion,
weil an einzelnen Flags eine ganze Fehlerklasse hängt (#118: onefile-Extraktions-
Race). subprocess.run wird gemockt, PyInstaller läuft nie.
"""

import build


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
    """Die vier --collect-all sind auf jeder Plattform Pflicht (CLAUDE.md) —
    ohne sie schlagen PDF/Feiertage im Artefakt stumm fehl. `--collect-all`
    und der Paketname sind separate Listenelemente, daher Element-Test."""
    for build_fn in (build.build_windows, build.build_linux):
        cmd = _capture_pyinstaller_cmd(monkeypatch, build_fn)
        for pkg in ("xhtml2pdf", "reportlab", "holidays", "pystray"):
            assert pkg in cmd, f"{pkg} fehlt im {build_fn.__name__}-Kommando"
