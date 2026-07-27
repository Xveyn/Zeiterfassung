import re

VERSION = "1.19.1"

# Kennung eines Releases: "1.19.0" (echtes Release) oder "1.19.0-pre.2"
# (Pre-Release, s. .github/workflows/release.yml). Kein anderes Suffix ist
# gültig — alles Übrige gilt als unbekannt und damit als "nicht neuer".
_RELEASE_ID = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-pre\.(\d+))?$")


def parse_release_id(release_id):
    """Vergleichsschlüssel `(major, minor, patch, pre_rank)` einer Release-
    Kennung (ohne v-Prefix), oder None wenn sie nicht dem Muster folgt.

    Ein echtes Release bekommt `pre_rank = 0`, `-pre.N` den Rang `N`. Damit
    gilt `1.19.0 < 1.19.0-pre.1 < 1.19.1` — die Umkehrung der Semver-Regel,
    aber die Praxis dieses Repos: ein Pre-Release wird IMMER nach dem
    gleichnamigen echten Release aus neuerem Code gebaut (v1.18.2 am
    2026-07-16, v1.18.2-pre.1 am 2026-07-20). Wer daran etwas ändert, muss
    diese Ordnung mitändern — s. CLAUDE.md, Abschnitt Pre-Releases.
    """
    match = _RELEASE_ID.match(release_id or "")
    if match is None:
        return None
    major, minor, patch, pre = match.groups()
    return (int(major), int(minor), int(patch), int(pre) if pre else 0)


def base_version(release_id):
    """Basisversion einer Kennung: '1.19.0-pre.2' -> '1.19.0'. Die Artefakte
    eines Pre-Releases tragen die reine Version im Namen (build.py benennt sie
    unabhängig vom Kanal), darum braucht der Asset-Match diese Form."""
    return (release_id or "").split("-pre.")[0]


def strip_tag_prefix(tag):
    """Git-Tag -> Release-Kennung: 'v1.19.0-pre.2' -> '1.19.0-pre.2'.

    Die eine Stelle, die das v-Prefix entfernt (updater.py und der
    Build-Stempel nutzen sie). Sowohl 'v' als auch 'V' — Tags sind normiert,
    defensiv ist billig."""
    tag = (tag or "").strip()
    return tag[1:] if tag[:1] in ("v", "V") else tag


# build_info wird beim Build von build.py generiert (gitignored) und von
# PyInstaller mitgebündelt. Beim Start aus dem Quellcode existiert es nicht —
# dann gilt Kanal "source". Der Import steht bewusst auf Modulebene (im
# try/except), damit PyInstaller die Abhängigkeit statisch erkennt.
try:
    from src import build_info as _build_info
except ImportError:
    _build_info = None


def _format_version_label(version, channel, sha, release_id=""):
    """Anzeige-Label für den Fenstertitel. Release → reine Version; Pre-Release
    (plattformübergreifender Test-Build) → die gestempelte Kennung inkl. Nummer
    ('1.19.0-pre.2'), ohne Stempel der alte '-pre'-Marker; jeder andere Kanal
    (dev/source) → '-dev'-Suffix, mit Kurz-SHA in Klammern falls vorhanden."""
    if channel == "release":
        return version
    if channel == "prerelease":
        return release_id or f"{version}-pre"
    if sha:
        return f"{version}-dev ({sha})"
    return f"{version}-dev"


def _stamped_release_id():
    """Release-Kennung aus dem beim Build gestempelten Tag ('v1.19.0-pre.2'
    -> '1.19.0-pre.2'). Leer, wenn kein Stempel existiert (Alt-Builds vor
    diesem Feature, Dev-/Repo-Modus) oder der Tag nicht dem Muster folgt."""
    raw = "" if _build_info is None else getattr(_build_info, "RELEASE_TAG", "")
    release_id = strip_tag_prefix(raw)
    return release_id if parse_release_id(release_id) is not None else ""


def installed_release_id():
    """Kennung des laufenden Builds für den Update-Vergleich. Ohne Stempel
    gilt die reine VERSION (Rang 0) — für ein echtes Release ist das exakt
    richtig, für einen Alt-Pre-Build die dokumentierte Grenze (er bekommt
    einmalig auch seinen eigenen Build angeboten)."""
    return _stamped_release_id() or VERSION


def version_label():
    """Versions-Label inkl. Kanal-Marker für die Titelzeile. Liest den beim Build
    gestempelten Kanal; fehlt build_info (Quellcode-Start), gilt 'source'."""
    if _build_info is None:
        channel, sha = "source", ""
    else:
        channel = getattr(_build_info, "CHANNEL", "dev")
        sha = getattr(_build_info, "GIT_SHA", "")
    return _format_version_label(VERSION, channel, sha, _stamped_release_id())
