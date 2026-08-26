import socket
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from src.changelog import (
    extract_version_section, fetch_changelog_entry, parse_changelog_markdown,
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
