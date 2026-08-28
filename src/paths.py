# src/paths.py
import os
import platform
import sys


def get_base_path():
    """Return the directory where data files should be stored.

    Script mode: repo root (parent of src/).
    Frozen Windows: directory containing the .exe (unchanged for compatibility).
    Frozen macOS: ~/Library/Application Support/Zeiterfassung.
    Frozen Linux/other: $XDG_DATA_HOME/Zeiterfassung or ~/.local/share/Zeiterfassung.

    Override: `ZEITERFASSUNG_DATA_DIR` setzt den base_path direkt — gedacht
    für Dev-Setups, in denen `python -m src.main` aus dem Repo auf die
    installierte Daten-Ablage zugreifen soll (Hard-/Symlinks scheitern,
    weil alle Stores per `os.replace(tmp, target)` atomar speichern und
    dabei den Verzeichniseintrag ersetzen).

    Ensures the directory exists on macOS/Linux.
    """
    override = os.environ.get("ZEITERFASSUNG_DATA_DIR")
    if override:
        return override

    if not getattr(sys, "frozen", False):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    system = platform.system()
    if system == "Windows":
        return os.path.dirname(sys.executable)
    if system == "Darwin":
        base = os.path.join(
            os.path.expanduser("~"),
            "Library", "Application Support", "Zeiterfassung",
        )
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share"
        )
        base = os.path.join(xdg, "Zeiterfassung")

    os.makedirs(base, exist_ok=True)
    return base


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


def relaunch_command(argv, executable, frozen):
    """Baut das Kommando, um die App neu zu starten (nach UI-Skalierungs-
    Änderung). Im Frozen-Build ist `executable` die App-Exe selbst; im
    Repo-Modus wird `python -m src.main` aufgerufen. `--minimized` wird
    entfernt, weil der Nutzer nach einer interaktiven Skalierungsänderung das
    Fenster sehen will, nicht ein erneut minimiertes."""
    rest = [a for a in argv[1:] if a != "--minimized"]
    if frozen:
        return [executable] + rest
    return [executable, "-m", "src.main"] + rest
