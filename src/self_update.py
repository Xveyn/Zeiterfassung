"""In-App-Update für Windows und Linux: reine Logik, Tk-frei, stdlib-only.

Die App lädt das Plattform-Asset selbst, prüft es gegen den `SHA256SUMS` des
Releases und installiert es. macOS ist bewusst NICHT dabei — das Bundle ist
weder signiert noch notarisiert, und der Weg über DMG-Mount und
`/Applications` ist auf der Windows-Entwicklungsmaschine nicht verifizierbar
(s. `docs/known-limitations.md`).

**Was die Hash-Prüfung leistet und was nicht.** `SHA256SUMS` schützt gegen
abgebrochene und verfälschte Übertragung. Es schützt NICHT gegen ein
kompromittiertes Release: die Datei ist selbst unsigniert und liegt neben den
Assets, die sie beschreibt. Vertrauensanker bleibt TLS zu GitHub — derselbe
wie beim manuellen Download im Browser. Das löst den Audit-Vermerk M9 ein
(„ein In-App-Auto-Download OHNE Verifikation wäre eine echte Lücke"), ohne
mehr zu behaupten, als es trägt.
"""
from __future__ import annotations

import hashlib

# Name des Prüfsummen-Assets, das `release.yml` jedem Release beilegt.
SUMS_ASSET_NAME: str = "SHA256SUMS"

_HEX = set("0123456789abcdef")
_CHUNK_BYTES = 1024 * 1024


def parse_sha256sums(text: str) -> dict[str, str]:
    """`SHA256SUMS`-Text → {Dateiname: Hex-Digest}.

    Format ist das von coreutils `sha256sum`: `<digest>  <name>` (zwei
    Leerzeichen) bzw. `<digest> *<name>` im Binärmodus. Unbrauchbare Zeilen
    werden übersprungen statt zu werfen — eine kaputte Zeile darf den Rest
    der Datei nicht entwerten.
    """
    result: dict[str, str] = {}
    for raw in text.splitlines():
        parts = raw.strip().split(None, 1)
        if len(parts) != 2:
            continue
        digest = parts[0].lower()
        if len(digest) != 64 or not set(digest) <= _HEX:
            continue
        result[parts[1].strip().lstrip("*")] = digest
    return result


def verify_file(path: str, expected_hex: str) -> bool:
    """True, wenn die Datei den erwarteten SHA256 hat.

    Blockweise gelesen: die AppImage ist ~65 MB und hat im Speicher nichts zu
    suchen. Ein Lesefehler ist ein Prüf-Fehlschlag, kein Ausnahmefall — der
    Aufrufer behandelt beides gleich (Datei löschen, Update abbrechen).
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == (expected_hex or "").lower()
