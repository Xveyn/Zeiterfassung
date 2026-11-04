"""Die Datenschutzhinweise der App, Tk-frei: `docs/datenschutz.md` wird gebündelt und hier in anzeigefertige
Blöcke für den Dialog zerlegt (Einstellungen → App → „Datenschutzhinweise“).

Die Datei bleibt die einzige Quelle; verstanden wird nur die Teilmenge von Markdown, die sie benutzt
(Titel, Überschriften, Absätze, Listen mit Einrückung, Zitat, fett, Code, Links). Alles andere erscheint als
lesbarer Text, nie als Fehler und nie verschluckt. Links werden nur für `http(s)` anklickbar: das Dokument ist
Fremddatei im Sinne des Dialogs (ein späterer Autor könnte `javascript:` oder `file:` hineinschreiben).
"""
from __future__ import annotations

import logging
import os
import re
from typing import TypedDict

log = logging.getLogger(__name__)

PRIVACY_DOC_RELATIVE = ("docs", "datenschutz.md")
PRIVACY_DOC_URL = "https://github.com/Xveyn/Zeiterfassung/blob/master/docs/datenschutz.md"
FALLBACK_TEXT = (
    "Die Datenschutzhinweise konnten nicht geladen werden. Sie stehen im Projekt unter ")

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BULLET = re.compile(r"^(\s*)[-*]\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
# Eine einzeilige Konstruktion, die dieser Parser nicht kennt: Tabelle, nummerierte Liste, Codezaun, HTML.
_UNKNOWN = re.compile(r"^(\||\d+[.)]\s|```|~~~|<)")
# `[Text](URL)`; die URL darf eine Ebene Klammern enthalten (`javascript:alert(1)`), sonst bliebe ein `)` zurück.
_LINK = re.compile(r"\[([^\]]*)\]\(((?:[^()\s]|\([^()\s]*\))*)\)")


class Segment(TypedDict):
    text: str
    style: str                  # plain | bold | code | link
    url: str | None


class Block(TypedDict):
    kind: str                   # title | heading | quote | paragraph | bullet
    segments: list[Segment]
    level: int                  # Einrückung eines Bullets, sonst 0


def is_web_url(url: object) -> bool:
    """Nur `https://` und `http://` (Schema ohne Rücksicht auf Groß-/Kleinschreibung)."""
    return isinstance(url, str) and url.lower().startswith(("https://", "http://"))


def _segment(text: str, style: str = "plain", url: str | None = None) -> Segment:
    return {"text": text, "style": style, "url": url}


def parse_inline(text: str) -> list[Segment]:
    """`**fett**`, `` `code` `` und `[Text](URL)`; nicht geschlossene Auszeichnung bleibt als Text stehen."""
    segments: list[Segment] = []
    plain: list[str] = []

    def flush() -> None:
        if plain:
            segments.append(_segment("".join(plain)))
            plain.clear()

    i = 0
    while i < len(text):
        if text.startswith("**", i):
            end = text.find("**", i + 2)
            if end > i + 2:
                flush()
                segments.append(_segment(text[i + 2:end], "bold"))
                i = end + 2
                continue
        elif text[i] == "`":
            end = text.find("`", i + 1)
            if end > i + 1:
                flush()
                segments.append(_segment(text[i + 1:end], "code"))
                i = end + 1
                continue
        elif text[i] == "[":
            match = _LINK.match(text, i)
            if match:
                label, url = match.group(1), match.group(2)
                if label and is_web_url(url):
                    flush()
                    segments.append(_segment(label, "link", url))
                else:
                    plain.append(label)             # ohne Link: nur der Text, nie die URL
                i = match.end()
                continue
        plain.append(text[i])
        i += 1
    flush()
    return segments


def _block(kind: str, text: str, level: int = 0) -> Block:
    return {"kind": kind, "segments": parse_inline(text), "level": level}


def parse_privacy_markdown(text: str) -> list[Block]:
    """Das Dokument als Blöcke in Dokumentreihenfolge. Fortsetzungszeilen eines Absatzes, Zitats oder
    Bullets werden mit einem Leerzeichen zu einem Block zusammengeführt (das Dokument ist hart umgebrochen,
    das Text-Widget bricht selbst um)."""
    text = _HTML_COMMENT.sub("", text)
    blocks: list[tuple[str, int, list[str]]] = []
    open_last = False               # darf die nächste Zeile den letzten Block fortsetzen?

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            open_last = False
            continue
        heading = _HEADING.match(stripped)
        bullet = _BULLET.match(line)
        if heading and not line.startswith(" "):
            kind = "title" if len(heading.group(1)) == 1 else "heading"
            blocks.append((kind, 0, [heading.group(2).strip()]))
            open_last = False
        elif stripped.startswith(">"):
            body = stripped.lstrip(">").strip()
            if open_last and blocks[-1][0] == "quote":
                blocks[-1][2].append(body)
            else:
                blocks.append(("quote", 0, [body]))
                open_last = True
        elif bullet:
            blocks.append(("bullet", min(len(bullet.group(1)) // 2, 2), [bullet.group(2).strip()]))
            open_last = True
        elif _UNKNOWN.match(stripped):
            blocks.append(("paragraph", 0, [stripped]))
            open_last = False
        elif open_last:
            blocks[-1][2].append(stripped)
        else:
            blocks.append(("paragraph", 0, [stripped]))
            open_last = True
    return [_block(kind, " ".join(parts), level) for kind, level, parts in blocks]


def sections_only(blocks: list[Block]) -> list[Block]:
    """Ab der ersten Abschnittsüberschrift (`## …`): Titel, Zitat und Einleitung des Dokuments sind für das
    Repository geschrieben, nicht für die Anzeige. Ohne Überschrift bleibt alles stehen (nie ein leeres Fenster).
    Die PWA-Seite hält dieselbe Regel (`pwa/privacy-doc.js`, Fixture `privacy-blocks.json`)."""
    for index, block in enumerate(blocks):
        if block["kind"] == "heading":
            return blocks[index:]
    return blocks


def plain_text(blocks: list[Block]) -> str:
    """Der sichtbare Text, Blöcke durch Zeilenumbruch getrennt (Tests, Ersatzanzeige)."""
    return "\n".join("".join(s["text"] for s in block["segments"]) for block in blocks)


def load_privacy_doc(resource_dir: str) -> str | None:
    """Der gebündelte Text oder `None` (Datei fehlt, ist unlesbar oder kein UTF-8): der Dialog zeigt dann
    `fallback_blocks()`. Wirft nie."""
    path = os.path.join(resource_dir, *PRIVACY_DOC_RELATIVE)
    try:
        with open(path, encoding="utf-8-sig") as handle:       # ein BOM aus einem Windows-Editor ist kein Text
            return handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("Datenschutzhinweise nicht geladen (%s)", type(exc).__name__)
        return None


def fallback_blocks() -> list[Block]:
    """Der Ersatztext samt Link auf das Dokument im Repository."""
    segments: list[Segment] = [_segment(FALLBACK_TEXT), _segment(PRIVACY_DOC_URL, "link", PRIVACY_DOC_URL)]
    block: Block = {"kind": "paragraph", "segments": segments, "level": 0}
    return [block]

