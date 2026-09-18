from src.paths import relaunch_command


def test_relaunch_command_frozen_uses_executable_directly():
    cmd = relaunch_command(["app.exe", "--foo"], "app.exe", True)
    assert cmd == ["app.exe", "--foo"]


def test_relaunch_command_repo_uses_module_invocation():
    cmd = relaunch_command(["src/main.py", "--foo"], "python", False)
    assert cmd == ["python", "-m", "src.main", "--foo"]


def test_relaunch_command_strips_minimized_frozen():
    cmd = relaunch_command(["app.exe", "--minimized", "--bar"], "app.exe", True)
    assert cmd == ["app.exe", "--bar"]


def test_relaunch_command_strips_minimized_repo():
    cmd = relaunch_command(["main.py", "--minimized"], "python", False)
    assert cmd == ["python", "-m", "src.main"]


def test_relaunch_command_prefers_the_appimage_file():
    """In der AppImage zeigt sys.executable in den temporären Mount, der mit
    der alten Instanz verschwindet — der Neustart muss die AppImage-Datei
    selbst starten, sonst stirbt der neue Prozess lautlos."""
    cmd = relaunch_command(["/tmp/.mount_Zeit/usr/bin/Zeiterfassung", "--minimized"],
                           "/tmp/.mount_Zeit/usr/bin/Zeiterfassung", True,
                           appimage="/home/sven/Zeiterfassung.AppImage")
    assert cmd == ["/home/sven/Zeiterfassung.AppImage"]


def test_relaunch_command_ignores_appimage_outside_the_frozen_build():
    cmd = relaunch_command(["main.py"], "python", False, appimage="/x.AppImage")
    assert cmd == ["python", "-m", "src.main"]


def test_relaunch_env_restores_the_original_library_path():
    """Die AppImage-Runtime ist ein fremdes Programm: sie darf nicht mit dem
    LD_LIBRARY_PATH starten, den PyInstaller auf das (gleich gelöschte)
    _MEI-Verzeichnis der alten Instanz gebogen hat."""
    from src.paths import relaunch_env
    env = relaunch_env({"LD_LIBRARY_PATH": "/tmp/_MEI123",
                        "LD_LIBRARY_PATH_ORIG": "/opt/lib", "HOME": "/h"},
                       frozen=True)
    assert env["LD_LIBRARY_PATH"] == "/opt/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in env
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert env["HOME"] == "/h"


def test_relaunch_env_drops_a_library_path_that_pyinstaller_invented():
    from src.paths import relaunch_env
    env = relaunch_env({"LD_LIBRARY_PATH": "/tmp/_MEI123"}, frozen=True)
    assert "LD_LIBRARY_PATH" not in env


def test_relaunch_env_keeps_the_library_path_in_repo_mode():
    """Im Repo-Modus hat PyInstaller nichts verbogen — der Pfad gehört dem Nutzer."""
    from src.paths import relaunch_env
    env = relaunch_env({"LD_LIBRARY_PATH": "/opt/lib"}, frozen=False)
    assert env["LD_LIBRARY_PATH"] == "/opt/lib"
