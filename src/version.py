VERSION = "1.15.2"

# build_info wird beim Build von build.py generiert (gitignored) und von
# PyInstaller mitgebündelt. Beim Start aus dem Quellcode existiert es nicht —
# dann gilt Kanal "source". Der Import steht bewusst auf Modulebene (im
# try/except), damit PyInstaller die Abhängigkeit statisch erkennt.
try:
    from src import build_info as _build_info
except ImportError:
    _build_info = None


def _format_version_label(version, channel, sha):
    """Anzeige-Label für den Fenstertitel. Release → reine Version; jeder andere
    Kanal (dev/source) → '-dev'-Suffix, mit Kurz-SHA in Klammern falls vorhanden."""
    if channel == "release":
        return version
    if sha:
        return f"{version}-dev ({sha})"
    return f"{version}-dev"


def version_label():
    """Versions-Label inkl. Kanal-Marker für die Titelzeile. Liest den beim Build
    gestempelten Kanal; fehlt build_info (Quellcode-Start), gilt 'source'."""
    if _build_info is None:
        channel, sha = "source", ""
    else:
        channel = getattr(_build_info, "CHANNEL", "dev")
        sha = getattr(_build_info, "GIT_SHA", "")
    return _format_version_label(VERSION, channel, sha)
