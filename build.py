# build.py
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from src.version import VERSION

NOTICES_PATH = os.path.join("dist", "THIRD-PARTY-NOTICES.txt")

_NOTICES_HEADER = (
    "Zeiterfassung — Third-Party Software Notices\n"
    "============================================\n\n"
    "Diese Anwendung bündelt die unten aufgeführten Open-Source-Bibliotheken.\n"
    "Ihre Lizenzbedingungen und Copyright-Hinweise gelten unverändert fort und\n"
    "sind nachstehend im vollständigen Wortlaut wiedergegeben.\n\n"
    "Der eigene Quellcode der Zeiterfassung steht unter der MIT-Lizenz "
    "(siehe LICENSE).\n\n"
    "============================================\n\n"
)

_NOTICES_FALLBACK = (
    "THIRD-PARTY-NOTICES konnten beim Build nicht automatisch erzeugt werden\n"
    "(pip-licenses war nicht verfügbar). Die gebündelten Bibliotheken sind in\n"
    "requirements.txt aufgeführt; ihre Lizenztexte liegen den jeweiligen Paketen\n"
    "auf PyPI bei.\n"
)


def generate_third_party_notices():
    """Erzeugt dist/THIRD-PARTY-NOTICES.txt aus den im aktuellen Environment
    installierten Paketen (inkl. transitiver Deps) via pip-licenses.

    Fehlt pip-licenses lokal, wird — analog zum übersprungenen Pack-Schritt —
    nur gewarnt und ein Hinweis-Stub geschrieben, damit das Bündeln nie an einer
    fehlenden Datei scheitert. Im CI ist pip-licenses installiert, dort entsteht
    die echte Liste. Aufruf von print() im Child würde unter Windows an der
    cp1252-Konsole an Nicht-Latin1-Namen scheitern (z.B. „Grönholm"), daher
    PYTHONUTF8/PYTHONIOENCODING setzen und die Ausgabe selbst als UTF-8 schreiben.
    """
    os.makedirs("dist", exist_ok=True)
    cmd = [
        sys.executable, "-m", "piplicenses",
        "--format=plain-vertical",
        "--with-license-file", "--with-notice-file", "--no-license-path",
        "--with-authors", "--with-urls",
        # Reines Build-/Notices-Tooling, das nicht ins Artefakt gebündelt wird.
        "--ignore-packages", "pip-licenses", "prettytable", "wcwidth", "tomli",
    ]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", env=env,
        )
    except OSError as exc:
        result = None
        print(f"pip-licenses konnte nicht gestartet werden ({exc}) — schreibe Stub.")

    if result is not None and result.returncode == 0 and result.stdout.strip():
        body = _NOTICES_HEADER + result.stdout
        print(f"Third-Party-Notices erzeugt: {NOTICES_PATH}")
    else:
        if result is not None:
            print("pip-licenses nicht verfügbar oder fehlgeschlagen — schreibe Stub. "
                  "Für vollständige Notices: pip install pip-licenses")
        body = _NOTICES_HEADER + _NOTICES_FALLBACK

    with open(NOTICES_PATH, "w", encoding="utf-8") as f:
        f.write(body)


def _pyinstaller_common(extra_args):
    """Return the PyInstaller command with the mandatory flags prepended."""
    # PyInstaller's --add-data separator: ';' on Windows, ':' elsewhere.
    # os.pathsep happens to match, so we use it.
    add_data = f"assets{os.pathsep}assets"
    return [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--name", "Zeiterfassung",
        # build_info wird in einem function-/try-Import (src/version.py) geladen
        # und von PyInstaller sonst evtl. nicht erfasst — explizit einbündeln,
        # damit der Release-Kanal-Stempel im Artefakt landet.
        "--hidden-import", "src.build_info",
        "--add-data", add_data,
        "--collect-all", "xhtml2pdf",
        "--collect-all", "reportlab",
        "--collect-all", "holidays",
        "--collect-all", "pystray",
        *extra_args,
        "src/main.py",
    ]


def _find_inno_compiler():
    """Return the path to ISCC.exe, or None if Inno Setup is not installed."""
    on_path = shutil.which("ISCC")
    if on_path:
        return on_path
    for candidate in (
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Inno Setup 6", "ISCC.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Inno Setup 6", "ISCC.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
    ):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def build_windows():
    print(f"Building Zeiterfassung v{VERSION} (Windows) ...")
    # --onedir statt --onefile (#118): Onefile entpackt bei JEDEM Start alle
    # DLLs frisch in einen _MEIxxxxxx-Tempordner. Dieses Zeitfenster ist die
    # Wurzel einer ganzen Fehlerklasse — der Bootloader kann python310.dll
    # transient nicht laden ("Failed to load Python DLL", #118), holidays fand
    # de.mo transient nicht (#116), und der Skalierungs-Neustart musste den
    # _MEIPASS-Erbgang per PYINSTALLER_RESET_ENVIRONMENT umgehen (ui.py). Onedir
    # legt die Dateien einmalig entpackt ins Installationsverzeichnis
    # (Exe + _internal/) — kein Extraktions-Race pro Start mehr. macOS baut
    # ohnehin schon -D. installer.iss shippt entsprechend den ganzen Ordner.
    cmd = _pyinstaller_common([
        "--onedir",
        "--noconsole",
        "--icon", "assets/margenheld-icon.ico",
    ])
    subprocess.run(cmd, check=True)
    generate_third_party_notices()

    inno_compiler = _find_inno_compiler()
    if not inno_compiler:
        print("Inno Setup not found on PATH or in standard locations — skipping installer.")
        return
    print(f"Building installer v{VERSION} with {inno_compiler} ...")
    subprocess.run([inno_compiler, f"/DAppVer={VERSION}", "installer.iss"], check=True)
    print("Installer created: dist/Zeiterfassung_Setup.exe")


def build_macos():
    print(f"Building Zeiterfassung v{VERSION} (macOS) ...")
    cmd = _pyinstaller_common([
        "--windowed",
        "-D",
        "--icon", "assets/margenheld-icon.icns",
        "--osx-bundle-identifier", "com.margenheld.zeiterfassung",
        # tray_mac.py importiert AppKit/Foundation lazy → explizit bündeln,
        # sonst fehlt PyObjC im DMG und das native Tray fällt still aus (#88).
        "--collect-all", "objc",
        "--collect-all", "AppKit",
        "--collect-all", "Foundation",
    ])
    subprocess.run(cmd, check=True)
    generate_third_party_notices()

    # Notices in das App-Bundle legen, damit sie mit dem DMG ausgeliefert werden.
    app_resources = os.path.join("dist", "Zeiterfassung.app", "Contents", "Resources")
    if os.path.isdir(app_resources):
        shutil.copy2(NOTICES_PATH, os.path.join(app_resources, "THIRD-PARTY-NOTICES.txt"))

    arch = platform.machine()
    dmg_name = f"Zeiterfassung-{VERSION}-{arch}.dmg"
    dmg_path = os.path.join("dist", dmg_name)

    if shutil.which("create-dmg") is None:
        print("create-dmg not found on PATH — install with 'brew install create-dmg'. Skipping DMG.")
        return

    if os.path.exists(dmg_path):
        os.remove(dmg_path)

    print(f"Building DMG: {dmg_name} ...")
    subprocess.run([
        "create-dmg",
        "--volname", "Zeiterfassung",
        "--window-size", "500", "300",
        "--icon", "Zeiterfassung.app", "125", "150",
        "--app-drop-link", "375", "150",
        dmg_path,
        "dist/Zeiterfassung.app",
    ], check=True)
    print(f"DMG created: {dmg_path}")


def build_linux():
    print(f"Building Zeiterfassung v{VERSION} (Linux) ...")
    cmd = _pyinstaller_common([
        "--onefile",
    ])
    subprocess.run(cmd, check=True)
    generate_third_party_notices()

    if shutil.which("appimagetool") is None:
        print("appimagetool not found on PATH — skipping AppImage.")
        return

    appdir = os.path.join("dist", "AppDir")
    if os.path.exists(appdir):
        shutil.rmtree(appdir)
    os.makedirs(os.path.join(appdir, "usr", "bin"))

    shutil.copy2("dist/Zeiterfassung", os.path.join(appdir, "usr", "bin", "Zeiterfassung"))
    os.chmod(os.path.join(appdir, "usr", "bin", "Zeiterfassung"), 0o755)

    shutil.copy2("assets/margenheld-icon.png", os.path.join(appdir, "margenheld-icon.png"))
    shutil.copy2(NOTICES_PATH, os.path.join(appdir, "THIRD-PARTY-NOTICES.txt"))

    desktop = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Zeiterfassung\n"
        "Exec=Zeiterfassung\n"
        "Icon=margenheld-icon\n"
        "Categories=Office;\n"
    )
    with open(os.path.join(appdir, "Zeiterfassung.desktop"), "w", encoding="utf-8") as f:
        f.write(desktop)

    apprun = os.path.join(appdir, "AppRun")
    with open(apprun, "w", encoding="utf-8") as f:
        f.write('#!/bin/sh\nHERE="$(dirname "$(readlink -f "${0}")")"\nexec "$HERE/usr/bin/Zeiterfassung" "$@"\n')
    os.chmod(apprun, 0o755)

    arch = platform.machine()
    appimage_name = f"Zeiterfassung-{VERSION}-{arch}.AppImage"
    appimage_path = os.path.join("dist", appimage_name)
    if os.path.exists(appimage_path):
        os.remove(appimage_path)

    print(f"Building AppImage: {appimage_name} ...")
    env = os.environ.copy()
    env["ARCH"] = arch
    subprocess.run(["appimagetool", appdir, appimage_path], check=True, env=env)
    print(f"AppImage created: {appimage_path}")


def generate_build_info():
    """Schreibt src/build_info.py mit dem Build-Kanal-Stempel (#45). Wird beim
    Build erzeugt (gitignored) und von PyInstaller mitgebündelt — daher VOR dem
    eigentlichen Build aufrufen.

    Der Release-Workflow setzt ZEIT_RELEASE=1 → CHANNEL='release'; für einen
    Pre-Release-Lauf zusätzlich ZEIT_PRERELEASE=1 → CHANNEL='prerelease' (Vorrang
    vor 'release'). Lokales `python build.py` ohne Flag → 'dev' + Commit-Hash.
    Der Release-Tag taugt nicht zur Kanal-Erkennung (er wird erst nach dem Build
    gepusht) — daher die expliziten Flags. Für die Update-Prüfung reicht der
    Workflow ihn aber als ZEIT_RELEASE_TAG durch (Job `pre-check` berechnet ihn
    vor den Build-Jobs); ohne die Variable bleibt RELEASE_TAG leer."""
    if os.environ.get("ZEIT_PRERELEASE") == "1":
        channel = "prerelease"
    elif os.environ.get("ZEIT_RELEASE") == "1":
        channel = "release"
    else:
        channel = "dev"

    release_tag = os.environ.get("ZEIT_RELEASE_TAG", "")

    def _git(args):
        try:
            return subprocess.run(
                ["git", *args], capture_output=True, text=True, check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, OSError):
            return ""

    sha = _git(["rev-parse", "--short", "HEAD"])
    dirty = bool(_git(["status", "--porcelain"]))
    build_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    path = os.path.join("src", "build_info.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "# Generiert von build.py — NICHT committen (s. .gitignore).\n"
            f'CHANNEL = "{channel}"\n'
            f'GIT_SHA = "{sha}"\n'
            f'RELEASE_TAG = "{release_tag}"\n'
            f"GIT_DIRTY = {dirty}\n"
            f'BUILD_TIME = "{build_time}"\n'
        )
    print(f"build_info: CHANNEL={channel} TAG={release_tag or '-'} SHA={sha or '-'} DIRTY={dirty}")


def main():
    generate_build_info()
    system = platform.system()
    if system == "Windows":
        build_windows()
    elif system == "Darwin":
        build_macos()
    elif system == "Linux":
        build_linux()
    else:
        sys.exit(f"Unsupported platform: {system}")


if __name__ == "__main__":
    main()
