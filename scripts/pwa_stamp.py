"""Stempelt die Build-Kennung der Handy-PWA (#280): `N/X.Y.Z (sha)`.

    python scripts/pwa_stamp.py _site

N ist die Zahl der Commits unter `pwa/` seit dem letzten **echten** Release,
X.Y.Z dessen Version — gelesen vom Tag, nicht aus `src/version.py`: auf master
kann dort schon die nächste, noch unveröffentlichte Version stehen. Pre-Releases
zählen nicht als Anker. Der Platzhalter `__BUILD__` steht in `sw-core.js`
(Cache-Name, Anzeige im Verbindungs-Dialog) und im Manifest (`version`);
ein Deploy bekommt dadurch immer einen eigenen Cache.

Läuft im Pages-Workflow (`pages.yml`), der dafür die ganze Historie samt Tags
auschecken muss. Reine stdlib, importiert nichts aus `src/`.
"""

import os
import pathlib
import re
import subprocess
import sys

PLACEHOLDER = "__BUILD__"
STAMPED_FILES = ("sw-core.js", "manifest.webmanifest")
_RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def build_label(count: int, version: str, sha: str) -> str:
    return f"{count}/{version} ({sha[:12]})"


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


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.exit("Aufruf: pwa_stamp.py <site-ordner>")
    os.chdir(pathlib.Path(__file__).resolve().parent.parent)
    tag = latest_release_tag(_git("tag", "--list", "v*").split())
    if tag is None:
        sys.exit("Kein echtes Release-Tag gefunden (Checkout ohne Tags/Historie?)")
    count = int(_git("rev-list", "--count", f"{tag}..HEAD", "--", "pwa"))
    label = build_label(count, tag[1:], _git("rev-parse", "HEAD"))
    stamp_site(pathlib.Path(argv[1]), label)
    print(label)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
