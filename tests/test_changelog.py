import socket
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from src.changelog import (
    NO_CHANGES_NOTICE, extract_version_section, fetch_changelog_entry,
    parse_changelog_markdown, release_notes_for_display,
)


CHANGELOG_FIXTURE = """# Changelog

## 1.18.0 — 2026-07-20

### Hinzugefügt
- **Updates-Tab**: Neuer Tab zeigt den Update-Status.

### Behoben
- Kleinere Fehler behoben.

## 1.17.0 — 2026-07-03

### Hinzugefügt
- **PDF-Export**: Bericht als PDF speichern.
"""

LAST_ENTRY_FIXTURE = """# Changelog

## 1.0.0 — 2026-01-01

### Hinzugefügt
- Erste Version.
"""


class TestExtractVersionSection:
    def test_middle_version_stops_at_next_heading(self):
        section = extract_version_section(CHANGELOG_FIXTURE, "1.18.0")
        assert section is not None
        assert section.startswith("## 1.18.0")
        assert "Updates-Tab" in section
        assert "PDF-Export" not in section

    def test_last_version_reads_to_end_of_file(self):
        section = extract_version_section(CHANGELOG_FIXTURE, "1.17.0")
        assert section is not None
        assert section.startswith("## 1.17.0")
        assert "PDF-Export" in section

    def test_single_entry_file_reads_to_end(self):
        section = extract_version_section(LAST_ENTRY_FIXTURE, "1.0.0")
        assert section is not None
        assert "Erste Version" in section

    def test_missing_version_returns_none(self):
        assert extract_version_section(CHANGELOG_FIXTURE, "9.9.9") is None

    def test_empty_text_returns_none(self):
        assert extract_version_section("", "1.0.0") is None


def _text_response(text: str) -> BytesIO:
    return BytesIO(text.encode("utf-8"))


class TestFetchChangelogEntry:
    def test_happy_path_returns_parsed_section(self):
        with patch("src.changelog.urlopen", return_value=_text_response(CHANGELOG_FIXTURE)):
            entry = fetch_changelog_entry("MargenHeld/Zeiterfassung", "1.18.0")
        assert entry is not None
        assert "Updates-Tab" in entry

    def test_url_error_returns_none(self):
        with patch("src.changelog.urlopen", side_effect=URLError("offline")):
            assert fetch_changelog_entry("any/repo", "1.0.0") is None

    def test_http_404_returns_none(self):
        err = HTTPError(url="x", code=404, msg="Not Found", hdrs=None, fp=None)
        with patch("src.changelog.urlopen", side_effect=err):
            assert fetch_changelog_entry("any/repo", "1.0.0") is None

    def test_socket_timeout_returns_none(self):
        with patch("src.changelog.urlopen", side_effect=socket.timeout()):
            assert fetch_changelog_entry("any/repo", "1.0.0") is None

    def test_invalid_utf8_returns_none(self):
        with patch("src.changelog.urlopen", return_value=BytesIO(b"\xff\xfe\x00\x00")):
            assert fetch_changelog_entry("any/repo", "1.0.0") is None

    def test_version_not_in_fetched_text_returns_none(self):
        with patch("src.changelog.urlopen", return_value=_text_response(CHANGELOG_FIXTURE)):
            assert fetch_changelog_entry("any/repo", "9.9.9") is None


class TestParseChangelogMarkdown:
    """Wandelt den rohen Markdown-Abschnitt in anzeigefertige Zeilen fürs
    Tk-Text-Widget um: Markdown-Syntax (##/###/**) wird in Stil-Tags
    übersetzt statt roh gezeigt, hart umgebrochene Quellzeilen werden zu
    einem Absatz zusammengeführt (Tk übernimmt den Umbruch selbst)."""

    def test_empty_text_returns_empty_list(self):
        assert parse_changelog_markdown("") == []

    def test_strips_leading_version_heading(self):
        section = extract_version_section(CHANGELOG_FIXTURE, "1.18.0")
        lines = parse_changelog_markdown(section)
        rendered = "".join(
            seg_text
            for line in lines if line
            for seg_text, _tags in line["segments"]
        )
        assert "1.18.0" not in rendered
        assert "##" not in rendered

    def test_strips_html_comment_from_generated_notes(self):
        """GitHub stellt generierten Release-Notes einen HTML-Kommentar voran,
        sobald `.github/release.yml` existiert. Pre-Releases beziehen ihren
        Changelog aus genau diesem Body (`updater.resolve_check_result`) — der
        Kommentar landete damit roh im Updates-Tab.
        """
        notes = (
            "<!-- Release notes generated using configuration in "
            ".github/release.yml at v1.20.0-pre.2 -->\n"
            "\n"
            "## What's Changed\n"
            "* docs: irgendwas by @wer in https://example.invalid/pull/1\n"
        )
        lines = parse_changelog_markdown(notes)
        rendered = "".join(
            seg_text
            for line in lines if line
            for seg_text, _tags in line["segments"]
        )
        assert "<!--" not in rendered
        assert "release.yml" not in rendered
        assert "What's Changed" in rendered
        # Kein führender Absatzabstand da, wo der Kommentar stand.
        assert lines and lines[0] is not None

    def test_strips_multiline_html_comment(self):
        """Ein Kommentar kann mehrzeilig sein — GitHub bricht ihn je nach
        Taglänge um."""
        notes = "<!-- erste Zeile\nzweite Zeile -->\n\n## Titel\n"
        rendered = "".join(
            seg_text
            for line in parse_changelog_markdown(notes) if line
            for seg_text, _tags in line["segments"]
        )
        assert "erste Zeile" not in rendered
        assert "zweite Zeile" not in rendered
        assert "Titel" in rendered

    def test_category_heading_becomes_heading_segment(self):
        lines = parse_changelog_markdown("### Hinzugefügt\n- x\n")
        assert lines[0]["segments"] == [("Hinzugefügt", ("heading",))]

    def test_bullet_gets_marker_and_bold_title_segment(self):
        lines = parse_changelog_markdown("- **Titel**: Rest des Textes.")
        line = lines[0]
        assert line["hanging_indent"] is True
        assert line["segments"][0] == ("• ", ())
        assert ("Titel", ("bold",)) in line["segments"]
        assert all("**" not in seg for seg, _ in line["segments"])

    def test_wrapped_continuation_lines_join_into_one_bullet(self):
        text = (
            "- **Titel**: Erster Teil des Satzes,\n"
            "  der über mehrere Quellzeilen\n"
            "  umgebrochen wurde.\n"
        )
        lines = parse_changelog_markdown(text)
        assert len(lines) == 1
        full = "".join(seg for seg, _tags in lines[0]["segments"])
        assert "über mehrere Quellzeilen umgebrochen wurde." in full

    def test_plain_line_without_bullet_has_no_marker(self):
        lines = parse_changelog_markdown("Changelog konnte nicht geladen werden.")
        assert lines[0]["segments"] == [
            ("Changelog konnte nicht geladen werden.", ()),
        ]
        assert lines[0]["hanging_indent"] is False

    def test_blank_lines_collapse_to_single_separator(self):
        lines = parse_changelog_markdown("- a\n\n\n- b\n")
        assert lines == [
            {"segments": [("• ", ()), ("a", ())], "hanging_indent": True},
            None,
            {"segments": [("• ", ()), ("b", ())], "hanging_indent": True},
        ]


# Wie GitHub die Notes eines Pre-Releases liefert: ## -Überschrift,
# * -Bullets, Full-Changelog-Zeile — und CRLF-Zeilenenden.
GITHUB_NOTES_FIXTURE = (
    "## What's Changed\r\n"
    "* feat: Netto-Stunden je Tag by @margenheld in "
    "https://github.com/MargenHeld/Zeiterfassung/pull/162\r\n"
    "* fix: Footer-Rundung by @margenheld in "
    "https://github.com/MargenHeld/Zeiterfassung/pull/163\r\n"
    "\r\n"
    "**Full Changelog**: "
    "https://github.com/MargenHeld/Zeiterfassung/compare/v1.19.0...v1.19.0-pre.2\r\n"
)


def _plain(line):
    return "".join(text for text, _tags in line["segments"])


class TestParseGithubNotes:
    def test_double_hash_heading_is_kept_and_styled(self):
        lines = parse_changelog_markdown(GITHUB_NOTES_FIXTURE)
        first = lines[0]
        assert _plain(first) == "What's Changed"
        assert first["segments"][0][1] == ("heading",)

    def test_star_bullets_are_rendered_as_bullets(self):
        lines = parse_changelog_markdown(GITHUB_NOTES_FIXTURE)
        bullets = [ln for ln in lines if ln and ln["hanging_indent"]]
        assert len(bullets) == 2
        assert _plain(bullets[0]).startswith("• feat: Netto-Stunden je Tag")

    def test_full_changelog_line_stays_text_with_bold_segment(self):
        lines = parse_changelog_markdown(GITHUB_NOTES_FIXTURE)
        last = [ln for ln in lines if ln][-1]
        assert last["hanging_indent"] is False
        assert ("Full Changelog", ("bold",)) in last["segments"]

    def test_crlf_does_not_leak_into_output(self):
        lines = parse_changelog_markdown(GITHUB_NOTES_FIXTURE)
        assert not any("\r" in _plain(ln) for ln in lines if ln)


class TestVersionHeadingStrippingIsScoped:
    def test_changelog_version_heading_is_still_dropped(self):
        section = extract_version_section(CHANGELOG_FIXTURE, "1.18.0")
        lines = parse_changelog_markdown(section)
        assert not any(_plain(ln).startswith("1.18.0") for ln in lines if ln)

    def test_non_version_first_heading_is_not_dropped(self):
        lines = parse_changelog_markdown("## What's Changed\n* etwas\n")
        assert _plain(lines[0]) == "What's Changed"


# --- Blockquotes (Xveyn/Zeiterfassung#60) ---


def _texts(blocks):
    """Sichtbarer Text je Zeile; None bleibt als Absatzlücke stehen."""
    return [None if b is None else "".join(t for t, _ in b["segments"])
            for b in blocks]


def _tags(blocks):
    return [None if b is None else [tags for _, tags in b["segments"]]
            for b in blocks]


def test_blockquote_multiline_drops_markers():
    """Der Fehler aus #60: hart umgebrochene Zitatzeilen werden zu einer
    logischen Zeile zusammengeführt — ohne Marker-Strip landeten die '>' der
    Folgezeilen mitten im Satz."""
    md = "### Test\n\n> **Fett.** Erste Zeile,\n> zweite Zeile,\n> dritte Zeile.\n"
    assert _texts(parse_changelog_markdown(md)) == [
        "Test", None, "Fett. Erste Zeile, zweite Zeile, dritte Zeile."]


def test_blockquote_keeps_bold_tagging():
    blocks = parse_changelog_markdown("> **Fett.** Rest.\n")
    assert ("bold",) in _tags(blocks)[0]


def test_blockquote_bullets_are_recognised_as_bullets():
    md = "> - erster\n> - zweiter\n"
    assert _texts(parse_changelog_markdown(md)) == ["• erster", "• zweiter"]


def test_blockquote_heading_is_recognised_as_heading():
    blocks = parse_changelog_markdown("> ### Titel\n> Text.\n")
    assert _texts(blocks) == ["Titel", "Text."]
    assert _tags(blocks)[0] == [("heading",)]


def test_bare_quote_marker_is_a_paragraph_break():
    """Eine Zeile mit nur '>' trennt im Markdown zwei Zitat-Absätze — sie darf
    nicht als Textblock mit Inhalt '>' durchrutschen."""
    md = "> erster Absatz\n>\n> zweiter Absatz\n"
    assert _texts(parse_changelog_markdown(md)) == [
        "erster Absatz", None, "zweiter Absatz"]


def test_nested_quote_markers_are_all_removed():
    assert _texts(parse_changelog_markdown(">> tief\n")) == ["tief"]


def test_quote_marker_without_space_is_stripped():
    assert _texts(parse_changelog_markdown(">direkt\n")) == ["direkt"]


def test_greater_than_inside_text_is_untouched():
    """Gegenprobe: nur ein '>' am ZEILENANFANG ist Syntax. In generierten
    Release-Notes steht es auch mal mitten im PR-Titel."""
    md = "* fix: handle > in input by @x\n"
    assert _texts(parse_changelog_markdown(md)) == [
        "• fix: handle > in input by @x"]


# --- Markdown-Links (Nachbar von #60) ---


def test_link_shows_only_its_text():
    md = "Siehe [Xveyn/Zeiterfassung](https://github.com/Xveyn/Zeiterfassung) dort.\n"
    assert _texts(parse_changelog_markdown(md)) == [
        "Siehe Xveyn/Zeiterfassung dort."]


def test_bold_inside_link_stays_bold():
    """Die Link-Ersetzung muss VOR dem Fett-Split laufen — sonst laege die
    Markierung quer ueber Segmentgrenzen."""
    blocks = parse_changelog_markdown("[**Fett**](https://example.com) danach\n")
    assert _texts(blocks) == ["Fett danach"]
    assert blocks[0]["segments"][0] == ("Fett", ("bold",))


def test_link_inside_bold_stays_bold():
    blocks = parse_changelog_markdown("**[Text](https://example.com)** danach\n")
    assert _texts(blocks) == ["Text danach"]
    assert blocks[0]["segments"][0] == ("Text", ("bold",))


def test_two_links_in_one_line():
    md = "[eins](https://a.example) und [zwei](https://b.example)\n"
    assert _texts(parse_changelog_markdown(md)) == ["eins und zwei"]


def test_relative_link_target_is_dropped_too():
    md = "Details: [`src/CLAUDE.md`](src/CLAUDE.md).\n"
    assert _texts(parse_changelog_markdown(md)) == ["Details: `src/CLAUDE.md`."]


def test_image_syntax_leaves_no_stray_bang():
    md = "![Screenshot](assets/bild.png) danach\n"
    assert _texts(parse_changelog_markdown(md)) == ["Screenshot danach"]


def test_link_with_empty_target():
    assert _texts(parse_changelog_markdown("[Text]() danach\n")) == ["Text danach"]


def test_brackets_without_url_are_left_alone():
    """`[...]` ohne folgende Klammern ist normaler Text, keine Link-Syntax."""
    md = "Der Wert [optional] bleibt stehen.\n"
    assert _texts(parse_changelog_markdown(md)) == [
        "Der Wert [optional] bleibt stehen."]


def test_bare_url_is_left_alone():
    """Generierte Release-Notes tragen nackte URLs — die sollen bleiben."""
    md = "* feat: X by @y in https://github.com/o/r/pull/1\n"
    assert _texts(parse_changelog_markdown(md)) == [
        "• feat: X by @y in https://github.com/o/r/pull/1"]


def test_real_1_21_0_line_renders_clean():
    """Regressionsfall aus dem ausgelieferten CHANGELOG-Abschnitt 1.21.0."""
    md = ("> **Letztes Release aus diesem Repository.** Alle weiteren Versionen\n"
          "> erscheinen unter [Xveyn/Zeiterfassung](https://github.com/Xveyn/Zeiterfassung)\n"
          "> — siehe unten.\n")
    assert _texts(parse_changelog_markdown(md)) == [
        "Letztes Release aus diesem Repository. Alle weiteren Versionen "
        "erscheinen unter Xveyn/Zeiterfassung — siehe unten."]


# --- Pre-Release-Notes fuer die Anzeige aufbereiten ---

# Der unveraenderte Body von v1.22.0-pre.1, wie ihn die GitHub-API liefert.
PRE_NOTES_FIXTURE = (
    "<!-- Release notes generated using configuration in .github/release.yml"
    " at v1.22.0-pre.1 -->\n"
    "\n"
    "## What's Changed\n"
    "* feat(urlaub): Stundenzeile in der Kalenderzelle abschaltbar machen"
    " by @Xveyn in https://github.com/Xveyn/Zeiterfassung/pull/102\n"
    "* fix(ui): KW-Header verdeckt den \u201eWoche\"-Toggle nicht mehr"
    " by @Xveyn in https://github.com/Xveyn/Zeiterfassung/pull/103\n"
    "* feat(smtp): SMTP als zweiter Mailweg neben der Gmail-API"
    " by @Xveyn in https://github.com/Xveyn/Zeiterfassung/pull/104\n"
    "\n"
    "\n"
    "**Full Changelog**: https://github.com/Xveyn/Zeiterfassung/compare/"
    "v1.22.0...v1.22.0-pre.1\n"
)


def test_release_notes_for_display_keeps_only_the_titles():
    """Der ganze Fall in einem Test: aus dem echten Body werden drei nackte
    Bullet-Zeilen, Titel woertlich erhalten (inkl. Umlauten und typografischen
    Anfuehrungszeichen)."""
    assert release_notes_for_display(PRE_NOTES_FIXTURE) == (
        "* feat(urlaub): Stundenzeile in der Kalenderzelle abschaltbar machen\n"
        "* fix(ui): KW-Header verdeckt den \u201eWoche\"-Toggle nicht mehr\n"
        "* feat(smtp): SMTP als zweiter Mailweg neben der Gmail-API"
    )


def test_release_notes_for_display_drops_bare_urls():
    # Im Text-Widget nicht klickbar, und im 58 Zeichen schmalen Feld bricht
    # sie nur um — dieselbe Begruendung wie beim Markdown-Link-Strip.
    assert "http" not in release_notes_for_display(PRE_NOTES_FIXTURE)


def test_release_notes_for_display_drops_the_author_suffix():
    assert "@Xveyn" not in release_notes_for_display(PRE_NOTES_FIXTURE)
    assert " by " not in release_notes_for_display(PRE_NOTES_FIXTURE)


def test_release_notes_for_display_drops_the_full_changelog_line():
    # Ohne die URL bliebe sonst ein nacktes "Full Changelog:" ohne Ziel stehen.
    assert "Full Changelog" not in release_notes_for_display(PRE_NOTES_FIXTURE)


def test_release_notes_for_display_drops_the_whats_changed_heading():
    # Wiederholt nur das Label ueber der Box.
    assert "What's Changed" not in release_notes_for_display(PRE_NOTES_FIXTURE)


def test_release_notes_for_display_drops_the_generator_comment():
    assert "<!--" not in release_notes_for_display(PRE_NOTES_FIXTURE)


def test_release_notes_for_display_without_a_full_changelog_line():
    md = "## What's Changed\n* feat: X by @y in https://github.com/o/r/pull/1\n"
    assert release_notes_for_display(md) == "* feat: X"


def test_release_notes_for_display_falls_back_when_nothing_is_left():
    """Ein Pre-Release direkt nach einem Release hat keine PRs in den Notes.
    Eine leere Box saehe aus wie ein Ladefehler."""
    md = ("<!-- Release notes generated -->\n\n## What's Changed\n\n"
          "**Full Changelog**: https://github.com/o/r/compare/v1...v2\n")
    assert release_notes_for_display(md) == NO_CHANGES_NOTICE


def test_release_notes_for_display_on_empty_input():
    assert release_notes_for_display("") == NO_CHANGES_NOTICE


def test_release_notes_for_display_collapses_blank_runs():
    md = "## What's Changed\n\n\n* feat: A\n\n\n\n* feat: B\n"
    assert release_notes_for_display(md) == "* feat: A\n\n* feat: B"


def test_release_notes_for_display_keeps_a_url_that_is_the_whole_title():
    # Gegenprobe: der Strip haengt am " by @… in <url>"-Suffix bzw. an blanken
    # URLs — ein Titel ohne beides bleibt unangetastet.
    md = "## What's Changed\n* fix: Tippfehler in der README\n"
    assert release_notes_for_display(md) == "* fix: Tippfehler in der README"
