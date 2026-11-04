"""Der Parser hinter dem Dialog „Datenschutzhinweise“: aus `docs/datenschutz.md` werden anzeigefertige
Blöcke. Tk-frei; zusätzlich hält ein Test den Parser gegen die echte Datei, damit eine Änderung der
Doku die Anzeige nicht still verdirbt."""
import pathlib

from src import privacy_doc as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
REAL = (ROOT / "docs" / "datenschutz.md").read_text(encoding="utf-8")


def kinds(blocks):
    return [b["kind"] for b in blocks]


def text_of(block):
    return "".join(s["text"] for s in block["segments"])


def test_headings_and_title_are_recognised():
    blocks = pd.parse_privacy_markdown("# Titel\n\n## 1. Abschnitt\n")
    assert kinds(blocks) == ["title", "heading"]
    assert [text_of(b) for b in blocks] == ["Titel", "1. Abschnitt"]


def test_wrapped_lines_become_one_paragraph():
    blocks = pd.parse_privacy_markdown("erste Zeile\nzweite Zeile\n\nneuer Absatz\n")
    assert kinds(blocks) == ["paragraph", "paragraph"]
    assert text_of(blocks[0]) == "erste Zeile zweite Zeile"
    assert text_of(blocks[1]) == "neuer Absatz"


def test_bullets_and_nested_bullets_keep_their_level_and_join_continuations():
    blocks = pd.parse_privacy_markdown("- eins\n  weiter\n  - unter\n- zwei\n")
    assert kinds(blocks) == ["bullet", "bullet", "bullet"]
    assert [b["level"] for b in blocks] == [0, 1, 0]
    assert text_of(blocks[0]) == "eins weiter"
    assert text_of(blocks[1]) == "unter"


def test_blockquote_is_a_quote_block():
    blocks = pd.parse_privacy_markdown("> Beschreibung, keine\n> Rechtsberatung.\n")
    assert kinds(blocks) == ["quote"]
    assert text_of(blocks[0]) == "Beschreibung, keine Rechtsberatung."


def test_inline_bold_code_and_link_become_styled_segments():
    segments = pd.parse_inline("**a** und `b` und [c](https://x.example/y)")
    assert [(s["text"], s["style"]) for s in segments] == [
        ("a", "bold"), (" und ", "plain"), ("b", "code"), (" und ", "plain"), ("c", "link")]
    assert segments[-1]["url"] == "https://x.example/y"
    assert all(s["url"] is None for s in segments[:-1])


def test_links_without_http_scheme_or_text_stay_plain():
    for markup in ("[x](docs/a.md)", "[x](javascript:alert(1))", "[x](file:///c:/a)", "[](https://x.example)"):
        segments = pd.parse_inline(markup)
        assert not any(s["style"] == "link" for s in segments), markup
        rendered = "".join(s["text"] for s in segments)
        assert "](" not in rendered and "http" not in rendered.replace("x", ""), markup
    assert "".join(s["text"] for s in pd.parse_inline("[x](docs/a.md)")) == "x"
    assert "".join(s["text"] for s in pd.parse_inline("[x](javascript:alert(1))")) == "x"


def test_unclosed_markup_is_kept_as_text():
    for markup in ("**offen", "`offen", "[offen](", "[offen"):
        assert "".join(s["text"] for s in pd.parse_inline(markup)) == markup


def test_unknown_constructs_are_shown_as_plain_text_one_block_per_line():
    text = "| a | b |\n| c | d |\n\n1. eins\n\n```\ncode\n```\n\n<b>x</b>\n"
    blocks = pd.parse_privacy_markdown(text)
    assert set(kinds(blocks)) == {"paragraph"}
    joined = "\n".join(text_of(b) for b in blocks)
    for fragment in ("| a | b |", "| c | d |", "1. eins", "code", "<b>x</b>"):
        assert fragment in joined, fragment


def test_html_comments_are_removed():
    blocks = pd.parse_privacy_markdown("a\n<!-- weg\nauch weg -->\n\nb\n")
    assert [text_of(b) for b in blocks] == ["a", "b"]


def test_the_real_document_has_no_markdown_left_over():
    blocks = pd.parse_privacy_markdown(REAL)
    assert kinds(blocks).count("title") == 1
    assert kinds(blocks).count("heading") >= 10
    for block in blocks:
        text = text_of(block)
        assert not text.startswith(("## ", "# ", "- ", "> ")), text[:40]
        for segment in block["segments"]:
            for residue in ("**", "`", "]("):
                assert residue not in segment["text"], (residue, segment["text"][:60])
    plain = pd.plain_text(blocks)
    assert "keine Rechtsberatung" in plain
    assert "Aufbewahrung im Leerlauf: 90 Tage" in plain


def test_every_link_of_the_real_document_is_https():
    links = [s for b in pd.parse_privacy_markdown(REAL) for s in b["segments"] if s["style"] == "link"]
    assert links, "das Dokument hat keine Links mehr"
    assert all(s["url"].startswith("https://") for s in links)


def test_is_web_url_truth_table():
    for good in ("https://x.example", "http://x.example", "HTTPS://x.example"):
        assert pd.is_web_url(good) is True, good
    for bad in ("javascript:alert(1)", "file:///c:/a", "docs/a.md", "ftp://x", "", None, 5):
        assert pd.is_web_url(bad) is False, bad


def test_load_returns_the_text_and_none_when_missing(tmp_path):
    assert "# Datenschutz" in pd.load_privacy_doc(str(ROOT))
    assert pd.load_privacy_doc(str(tmp_path)) is None                      # Datei fehlt
    (tmp_path / "docs" / "datenschutz.md").mkdir(parents=True)            # Verzeichnis statt Datei
    assert pd.load_privacy_doc(str(tmp_path)) is None
    other = tmp_path / "other"
    (other / "docs").mkdir(parents=True)
    (other / "docs" / "datenschutz.md").write_bytes(b"\xff\xfe\x00")       # kein UTF-8
    assert pd.load_privacy_doc(str(other)) is None


def test_the_fallback_names_the_document_and_links_to_it():
    blocks = pd.fallback_blocks()
    assert len(blocks) == 1 and blocks[0]["kind"] == "paragraph"
    links = [s for s in blocks[0]["segments"] if s["style"] == "link"]
    assert [s["url"] for s in links] == [pd.PRIVACY_DOC_URL]
    assert "nicht geladen" in pd.plain_text(blocks)


def test_a_utf8_bom_does_not_turn_the_title_into_a_paragraph(tmp_path):
    """Ein Windows-Editor speichert gern „UTF-8 mit BOM“; `str.strip()` entfernt U+FEFF nicht, und der Titel
    erschiene roh als `# …`."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "datenschutz.md").write_bytes(b"\xef\xbb\xbf# Titel\n\nText\n")
    blocks = pd.parse_privacy_markdown(pd.load_privacy_doc(str(tmp_path)))
    assert kinds(blocks) == ["title", "paragraph"]
    assert text_of(blocks[0]) == "Titel"


# --- Datenschutz in der Web-App (#428) -----------------------------------------------------------------

PWA = ROOT / "pwa"


def test_the_web_app_links_the_same_document_the_desktop_shows():
    """`PRIVACY_SOURCE_URL` der PWA (Ersatzlink ihrer Datenschutzseite) und `PRIVACY_DOC_URL` des Desktops sind
    dieselbe Adresse (zwei Konstanten, ein Ziel)."""
    import re

    source = (PWA / "relay-client.js").read_text(encoding="utf-8")
    match = re.search(r"export const PRIVACY_SOURCE_URL = '([^']+)';", source)
    assert match, "PRIVACY_SOURCE_URL fehlt in pwa/relay-client.js"
    assert match.group(1) == pd.PRIVACY_DOC_URL


def test_the_document_names_the_contact_and_no_longer_calls_the_notice_open():
    text = REAL
    assert "Offen:" not in text, "der Hinweis auf die fehlende Datenschutzerklärung (#428) steht noch im Dokument"
    assert "https://github.com/Xveyn/Zeiterfassung/security/advisories/new" in text
    assert "https://github.com/Xveyn/Zeiterfassung/issues" in text
    assert "keine personenbezogenen Daten" in text


def test_the_dialog_starts_at_the_first_section():
    blocks = pd.sections_only(pd.parse_privacy_markdown(REAL))
    assert blocks[0]["kind"] == "heading"
    assert text_of(blocks[0]).startswith("1. Was der Relay sieht")
    assert "title" not in kinds(blocks)
    assert "Beschreibung von Datenflüssen" not in pd.plain_text(blocks)


def test_without_a_section_heading_everything_is_kept():
    blocks = pd.parse_privacy_markdown("# Titel\n\nnur Text\n")
    assert pd.sections_only(blocks) == blocks


def test_the_web_app_parser_gives_the_same_blocks():
    """Gleichlauf mit `pwa/privacy-doc.js`: die Fixture trägt die Blöcke dieses Parsers (der Node-Test liest sie)."""
    import json

    fixture = json.loads((PWA / "test" / "fixtures" / "privacy-blocks.json").read_text(encoding="utf-8"))
    assert fixture["document"] == pd.sections_only(pd.parse_privacy_markdown(REAL)), (
        "Fixture veraltet: python scripts/privacy_fixtures.py")
    for case in fixture["cases"]:
        assert case["blocks"] == pd.sections_only(pd.parse_privacy_markdown(case["markdown"])), case["markdown"]
