"""Changelog-Eintrag einer Release-Version laden (stdlib-only, Tk-frei).

CHANGELOG.md wird im Repo gepflegt und ist im gebauten Artefakt auf dem
Stand der installierten Version eingefroren — den Eintrag einer neueren,
noch nicht heruntergeladenen Version gibt es dort nicht. Dieses Modul lädt
die Datei zur Laufzeit vom GitHub-Tag der Zielversion und extrahiert nur
deren Abschnitt.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.version import VERSION

_RAW_URL = "https://raw.githubusercontent.com/{repo}/v{version}/CHANGELOG.md"
_VERSION_HEADING = re.compile(r"^##\s+(\S+)\s", re.MULTILINE)
_BOLD = re.compile(r"\*\*(.+?)\*\*")
# Markdown-Link bzw. -Bild: nur der Linktext wird angezeigt, das Ziel
# faellt weg. Der Updates-Tab ist ein reines Text-Widget ohne Klick-Ziele,
# und eine roh mitgezeigte URL wuerde im 58 Zeichen schmalen Feld nur
# umbrechen. Das fuehrende `!?` nimmt die Bild-Syntax mit, sonst bliebe
# ein verwaistes "!" stehen.
_LINK = re.compile(r"!?\[([^\]]+)\]\([^)]*\)")
# Nur eine Versions-Überschrift ("## 1.18.0 — …") ist redundant zum Status-Text
# darüber. Die Notes eines Pre-Releases beginnen mit "## What's Changed" — die
# muss stehen bleiben.
_VERSION_HEADING_LINE = re.compile(r"^##\s+\d+\.\d+\.\d+")
# DOTALL, weil GitHub den Kommentar je nach Taglänge über mehrere Zeilen bricht.
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def extract_version_section(changelog_text: str, version: str) -> str | None:
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


def fetch_changelog_entry(repo: str, version: str,
                          timeout: float = 5.0) -> str | None:
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


def _split_bold(content: str) -> list[tuple[str, tuple[str, ...]]]:
    """Zerlegt `content` an `**bold**`-Markierungen in (Text, Tags)-Segmente
    (Tags leer bei Normaltext, `("bold",)` innerhalb der Markierung).

    Links werden vorher auf ihren Text reduziert. Die Reihenfolge ist wichtig:
    erst der Link, dann der Fett-Split. Andersherum laege eine Markierung wie
    `[**Fett**](url)` quer ueber Segmentgrenzen und der Link-Rest bliebe roh
    stehen. So funktionieren beide Verschachtelungen — `[**x**](url)` und
    `**[x](url)**`."""
    content = _LINK.sub(r"\1", content)
    segments = []
    pos = 0
    for m in _BOLD.finditer(content):
        if m.start() > pos:
            segments.append((content[pos:m.start()], ()))
        segments.append((m.group(1), ("bold",)))
        pos = m.end()
    if pos < len(content):
        segments.append((content[pos:], ()))
    return segments


def parse_changelog_markdown(text: str) -> list[dict[str, Any]]:
    """Wandelt einen Changelog-Abschnitt (Markdown) in anzeigefertige Zeilen
    für ein Tk-Text-Widget um (Tk-frei/ohne UI testbar).

    Verstanden werden beide Quellen: der kuratierte CHANGELOG.md-Abschnitt
    (`### `-Überschriften, `- `-Bullets) und die von GitHub generierten
    Release-Notes eines Pre-Releases (`## `-Überschriften, `* `-Bullets).

    CHANGELOG.md ist im Quelltext auf ~80 Spalten hart umgebrochen — roh in
    ein schmaleres Textfeld gekippt, wirkt das doppelt und falsch umgebrochen.
    Darum werden Fortsetzungszeilen eines Bullets/Absatzes hier zu einer
    einzigen logischen Zeile zusammengeführt; das Wrapping übernimmt danach
    das Text-Widget selbst (`wrap=tk.WORD`). Markdown-Syntax (`##`/`###`/`**`)
    wird nicht roh gezeigt, sondern in Stil-Tags übersetzt.

    Liefert eine Liste von Zeilen: `None` für eine Absatzlücke, sonst
    `{"segments": [(text, tags), ...], "hanging_indent": bool}` — `tags` ist
    `("heading",)`, `("bold",)` oder `()`; `hanging_indent` markiert Bullets,
    deren umgebrochene Folgezeilen unter dem Text (nicht unter dem `•`)
    einrücken sollen.
    """
    # HTML-Kommentare raus. GitHub stellt generierten Release-Notes seit dem
    # Anlegen von `.github/release.yml` einen Hinweis voran:
    #   <!-- Release notes generated using configuration in
    #        .github/release.yml at v1.20.0-pre.2 -->
    # Für Pre-Releases IST dieser Body die Changelog-Quelle
    # (updater.resolve_check_result) — ungefiltert stünde der Kommentar roh im
    # Updates-Tab. Das abschließende strip() nimmt die Leerzeile mit, die er
    # hinterlässt; sonst begänne die Anzeige mit einem Absatzabstand.
    text = _HTML_COMMENT.sub("", text).strip()

    raw_lines = text.splitlines()
    # Die Versions-Überschrift ("## 1.18.0 — ...") ist redundant zum Status-
    # Text darüber (z.B. "Du hast die aktuelle Version …") und wird nicht
    # mit angezeigt. Andere "## "-Überschriften (GitHub-Notes) bleiben.
    if raw_lines and _VERSION_HEADING_LINE.match(raw_lines[0]):
        raw_lines = raw_lines[1:]

    blocks = []
    for raw in raw_lines:
        line = raw.strip()
        # Blockquote-Marker abstreifen, BEVOR klassifiziert wird. Die
        # Reihenfolge ist der ganze Punkt:
        #   - vor dem Leerzeilen-Zweig, damit eine Zeile aus nur ">" (der
        #     Absatztrenner innerhalb eines Zitats) zur Absatzluecke wird und
        #     nicht als Textblock mit Inhalt ">" durchrutscht;
        #   - vor den Ueberschrift-/Bullet-Zweigen, damit "> ### Titel" und
        #     "> - Punkt" als solche erkannt werden.
        # Ohne den Strip landete der Marker im Text — und weil hart
        # umgebrochene Fortsetzungszeilen unten zu EINER logischen Zeile
        # zusammengefuehrt werden, standen die ">" der Folgezeilen mitten im
        # Satz. `while` statt `if` wegen verschachtelter Zitate (">>").
        # Nur der Zeilenanfang zaehlt: ein ">" im Fliesstext (etwa in einem
        # generierten PR-Titel) bleibt unberuehrt.
        while line.startswith(">"):
            line = line[1:].lstrip()
        if not line:
            if blocks and blocks[-1][0] != "blank":
                blocks.append(("blank", ""))
            continue
        if line.startswith("### "):
            blocks.append(("heading", line[4:].strip()))
            continue
        if line.startswith("## "):
            blocks.append(("heading", line[3:].strip()))
            continue
        if line.startswith("- ") or line.startswith("* "):
            blocks.append(("bullet", line[2:].strip()))
            continue
        # Fortsetzung einer hart umgebrochenen Bullet-/Textzeile.
        if blocks and blocks[-1][0] in ("bullet", "text"):
            kind, content = blocks[-1]
            blocks[-1] = (kind, f"{content} {line}")
        else:
            blocks.append(("text", line))

    rendered = []
    for kind, content in blocks:
        if kind == "blank":
            rendered.append(None)
        elif kind == "heading":
            rendered.append({"segments": [(content, ("heading",))], "hanging_indent": False})
        elif kind == "bullet":
            rendered.append({"segments": [("• ", ())] + _split_bold(content), "hanging_indent": True})
        else:
            rendered.append({"segments": _split_bold(content), "hanging_indent": False})
    return rendered
