# src/autostart.py
import os
import platform
import plistlib
import shlex
import subprocess
import sys


SHORTCUT_NAME = "Zeiterfassung.lnk"
MACOS_LABEL = "com.margenheld.zeiterfassung"

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


def resolve_autostart_target(base_path):
    """Return (target, arguments) for the current runtime/platform.

    Frozen Windows/macOS: the executable itself.
    Frozen Linux: $APPIMAGE if set (persistent path), otherwise sys.executable.
    Script mode: Python interpreter + main.py.
    """
    if getattr(sys, "frozen", False):
        if platform.system() == "Linux":
            target = os.environ.get("APPIMAGE") or sys.executable
        else:
            target = sys.executable
        return target, "--minimized"
    main_py = os.path.join(base_path, "src", "main.py")
    return sys.executable, f"{main_py} --minimized"


def _get_startup_folder():
    return os.path.join(
        os.environ["APPDATA"],
        "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    )


def _get_shortcut_path():
    return os.path.join(_get_startup_folder(), SHORTCUT_NAME)


def _macos_plist_path():
    return os.path.join(
        os.path.expanduser("~"),
        "Library", "LaunchAgents", f"{MACOS_LABEL}.plist",
    )


def _linux_desktop_path():
    return os.path.join(
        os.path.expanduser("~"),
        ".config", "autostart", "Zeiterfassung.desktop",
    )


def enable_autostart(target, arguments=""):
    """Enable autostart on the current platform.

    target: path to executable (Windows .exe, macOS .app binary, Linux AppImage/binary)
    arguments: whitespace-separated CLI args
    """
    system = platform.system()
    if system == "Windows":
        _enable_windows(target, arguments)
    elif system == "Darwin":
        _enable_macos(target, arguments)
    elif system == "Linux":
        _enable_linux(target, arguments)
    else:
        raise RuntimeError(f"Autostart not supported on {system}")


def disable_autostart():
    system = platform.system()
    if system == "Windows":
        _disable_windows()
    elif system == "Darwin":
        _disable_macos()
    elif system == "Linux":
        _disable_linux()
    else:
        raise RuntimeError(f"Autostart not supported on {system}")


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


def _enable_macos(target, arguments):
    plist_path = _macos_plist_path()
    os.makedirs(os.path.dirname(plist_path), exist_ok=True)

    program_args = [target]
    if arguments:
        program_args.extend(arguments.split())

    plist = {
        "Label": MACOS_LABEL,
        "ProgramArguments": program_args,
        "RunAtLoad": True,
        "ProcessType": "Interactive",
    }
    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)

    subprocess.run(["launchctl", "unload", plist_path], check=False)
    subprocess.run(["launchctl", "load", "-w", plist_path], check=True)


def _disable_macos():
    plist_path = _macos_plist_path()
    if not os.path.exists(plist_path):
        return
    subprocess.run(["launchctl", "unload", plist_path], check=False)
    os.remove(plist_path)


def _exec_line(target, arguments):
    """Baut die Exec=-Zeile mit shell-korrektem Quoting (Audit N12): ein Pfad
    mit Leerzeichen o.ä. zerbricht die .desktop-Datei sonst. shlex.quote deckt
    sich mit GLibs Exec-Parsing (g_shell_parse_argv). `arguments` ist
    typischerweise ein Whitespace-getrennter String einfacher Flags (z.B. ""
    oder "--minimized"); im Nicht-Frozen-Modus kann es zusätzlich einen
    Skript-Pfad enthalten (resolve_autostart_target) — ein Leerzeichen darin
    würde fälschlich als Token-Grenze behandelt (vorbestehendes Verhalten, nicht
    durch diesen Fix eingeführt). Werte ohne Sonderzeichen bleiben unverändert
    (shlex.quote quotet nur bei Bedarf)."""
    parts = [shlex.quote(target)]
    if arguments:
        parts.extend(shlex.quote(a) for a in arguments.split())
    return " ".join(parts)


def _enable_linux(target, arguments):
    desktop_path = _linux_desktop_path()
    os.makedirs(os.path.dirname(desktop_path), exist_ok=True)

    exec_line = _exec_line(target, arguments)
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Zeiterfassung\n"
        f"Exec={exec_line}\n"
        "Hidden=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    with open(desktop_path, "w", encoding="utf-8") as f:
        f.write(content)


def _disable_linux():
    desktop_path = _linux_desktop_path()
    if os.path.exists(desktop_path):
        try:
            os.remove(desktop_path)
        except FileNotFoundError:
            pass
