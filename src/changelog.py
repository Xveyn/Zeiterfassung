"""Changelog-Eintrag einer Release-Version laden (stdlib-only, Tk-frei).

CHANGELOG.md wird im Repo gepflegt und ist im gebauten Artefakt auf dem
Stand der installierten Version eingefroren — den Eintrag einer neueren,
noch nicht heruntergeladenen Version gibt es dort nicht. Dieses Modul lädt
die Datei zur Laufzeit vom GitHub-Tag der Zielversion und extrahiert nur
deren Abschnitt.
"""
import re
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.version import VERSION

_RAW_URL = "https://raw.githubusercontent.com/{repo}/v{version}/CHANGELOG.md"
_VERSION_HEADING = re.compile(r"^##\s+(\S+)\s", re.MULTILINE)


def extract_version_section(changelog_text, version):
    """Extrahiert den Abschnitt zu `version` aus dem vollen CHANGELOG.md-Text:
    von der Zeile '## {version} ...' bis zur nächsten '## '-Überschrift oder
    zum Dateiende. None, wenn `version` nicht als Überschrift vorkommt."""
    headings = list(_VERSION_HEADING.finditer(changelog_text))
    for i, m in enumerate(headings):
        if m.group(1) != version:
            continue
        start = m.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(changelog_text)
        return changelog_text[start:end].strip()
    return None


def fetch_changelog_entry(repo, version, timeout=5.0):
    """Lädt CHANGELOG.md vom Release-Tag `v{version}` und liefert den
    Abschnitt dieser Version. None bei jedem Fehler (Netzwerk, HTTP-Fehler,
    Decode-Fehler, Version nicht im Text gefunden) — nie eine Exception nach
    außen, analog updater.py::check_latest_release."""
    url = _RAW_URL.format(repo=repo, version=version)
    request = Request(url, headers={"User-Agent": f"Zeiterfassung/{VERSION}"})
    try:
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except (URLError, OSError, UnicodeDecodeError):
        return None
    return extract_version_section(text, version)
