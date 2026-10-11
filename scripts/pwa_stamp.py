"""Stempelt die Build-Kennung der Handy-PWA (#280, #304): `P-N/X.Y.Z (sha)`.

    python scripts/pwa_stamp.py _site     # stempeln (pages.yml)
    python scripts/pwa_stamp.py --check   # Release-PR: PWA-Version gebumpt?

P ist die eigene Version der PWA aus `pwa/package.json` (Semver, im Release-PR
von Hand gebumpt, zusammen mit `src/version.py`). N ist die Zahl der Commits unter `pwa/` seit dem letzten **echten** Release,
X.Y.Z dessen Version — gelesen vom Tag, nicht aus `src/version.py`: auf master
kann dort schon die nächste, noch unveröffentlichte Version stehen. Pre-Releases
zählen nicht als Anker. Der Platzhalter `__BUILD__` steht in `sw-core.js`
(Cache-Name, Anzeige im Verbindungs-Dialog) und im Manifest (`version`);
ein Deploy bekommt dadurch immer einen eigenen Cache.

Weil jede Änderung unter `pwa/` sofort live geht, zählt N sie einzeln; ein
Release setzt N auf 0 zurück (der `publish`-Job stößt dafür `pages.yml` neu an).
`--check` hält Release-PRs an, solange P nicht größer ist als am letzten
Release-Tag (`pwa-version.yml`).

Läuft im Pages-Workflow (`pages.yml`), der dafür die ganze Historie samt Tags
auschecken muss. Reine stdlib, importiert nichts aus `src/`.
"""

import json
import os
import pathlib
import re
import subprocess
import sys

PLACEHOLDER = "__BUILD__"
STAMPED_FILES = ("sw-core.js", "manifest.webmanifest")
_RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
PACKAGE_JSON = "pwa/package.json"


def build_label(pwa_version: str, count: int, version: str, sha: str) -> str:
    return f"{pwa_version}-{count}/{version} ({sha[:12]})"


def pwa_version_from_text(text: str) -> str | None:
    """`version` aus dem Text einer `package.json`; `None`, wenn kaputt, nicht
    vorhanden oder kein reines `X.Y.Z` (ein Suffix würde sich mit dem Zähler
    `-N` der Kennung beißen)."""
    try:
        version = json.loads(text).get("version")
    except (ValueError, AttributeError):
        return None
    return version if isinstance(version, str) and _SEMVER.match(version) else None


def read_pwa_version(path: pathlib.Path) -> str:
    version = pwa_version_from_text(pathlib.Path(path).read_text(encoding="utf-8"))
    if version is None:
        sys.exit(f'{path}: "version" fehlt oder ist kein X.Y.Z')
    return version


def is_bumped(current: str, previous: str | None) -> bool:
    """`current` echt größer als `previous` (numerisch). Ohne Vorgänger (der
    Release-Tag trug noch keine PWA-Version) genügt jede gültige."""
    if previous is None:
        return True
    return _triple(current) > _triple(previous)


def _triple(version: str) -> tuple[int, int, int]:
    m = _SEMVER.match(version)
    assert m, version
    return (int(m[1]), int(m[2]), int(m[3]))


def latest_release_tag(tags: list[str]) -> str | None:
    """Höchstes echtes Release `vX.Y.Z` (numerisch, ohne `-pre.N`)."""
    found = [(tuple(int(p) for p in m.groups()), t)
             for t in tags if (m := _RELEASE_TAG.match(t))]
    return max(found)[1] if found else None


def stamp_site(site: pathlib.Path, label: str) -> None:
    """Ersetzt den Platzhalter in allen gestempelten Dateien; fehlt er, ist
    das ein Fehler (sonst lieferte ein Deploy den Platzhalter aus)."""
    for name in STAMPED_FILES:
        path = pathlib.Path(site) / name
        text = path.read_text(encoding="utf-8")
        if PLACEHOLDER not in text:
            sys.exit(f"Platzhalter {PLACEHOLDER} fehlt in {path}")
        # JSON-gültig einsetzen: die Kennung enthält nur Ziffern, ., /, (, ) und Hex.
        path.write_text(text.replace(PLACEHOLDER, label), encoding="utf-8")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def _latest_tag() -> str:
    tag = latest_release_tag(_git("tag", "--list", "v*").split())
    if tag is None:
        sys.exit("Kein echtes Release-Tag gefunden (Checkout ohne Tags/Historie?)")
    return tag


def _check() -> int:
    """Release-PR: `pwa/package.json` muss gegenüber dem letzten Release-Tag
    gebumpt sein — auch ohne PWA-Änderung, weil ein Release N zurücksetzt."""
    tag = _latest_tag()
    current = read_pwa_version(pathlib.Path(PACKAGE_JSON))
    try:
        previous = pwa_version_from_text(_git("show", f"{tag}:{PACKAGE_JSON}"))
    except subprocess.CalledProcessError:
        previous = None  # Datei gab es am Tag noch nicht
    if not is_bumped(current, previous):
        sys.exit(f"{PACKAGE_JSON}: Version {current} ist nicht größer als {previous} "
                 f"am letzten Release {tag}. Im Release-PR bumpen (s. CLAUDE.md).")
    print(f"PWA-Version {current} (zuvor {previous or 'keine'} am {tag})")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.exit("Aufruf: pwa_stamp.py <site-ordner> | --check")
    os.chdir(pathlib.Path(__file__).resolve().parent.parent)
    if argv[1] == "--check":
        return _check()
    tag = _latest_tag()
    count = int(_git("rev-list", "--count", f"{tag}..HEAD", "--", "pwa"))
    label = build_label(read_pwa_version(pathlib.Path(PACKAGE_JSON)), count, tag[1:],
                        _git("rev-parse", "HEAD"))
    stamp_site(pathlib.Path(argv[1]), label)
    print(label)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
