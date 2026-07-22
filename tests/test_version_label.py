"""Build-Kanal-Marker im Fenstertitel (#45).

Getestet wird die reine Label-Formatierung `_format_version_label`. Der Reader
`version_label()` (liest das beim Build generierte build_info-Modul) und die
Tk-Titelzeile sind Verdrahtung und werden manuell verifiziert.
"""
from unittest.mock import patch

from src.version import (
    VERSION,
    _format_version_label,
    base_version,
    installed_release_id,
    parse_release_id,
    strip_tag_prefix,
)


def test_release_channel_is_plain_version():
    # Release: reine Version, SHA wird bewusst ignoriert.
    assert _format_version_label("1.14.1", "release", "abc1234") == "1.14.1"


def test_dev_build_shows_dev_and_sha():
    assert _format_version_label("1.14.1", "dev", "abc1234") == "1.14.1-dev (abc1234)"


def test_dev_without_sha_shows_only_dev():
    assert _format_version_label("1.14.1", "dev", "") == "1.14.1-dev"


def test_source_channel_shows_dev_without_sha():
    # Start aus dem Quellcode (kein build_info) → 'source', kein SHA.
    assert _format_version_label("1.14.1", "source", "") == "1.14.1-dev"


def test_prerelease_channel_shows_pre_marker():
    # Pre-Release (plattformübergreifender Test-Build): eigener '-pre'-Marker,
    # SHA wird wie beim Release nicht angehängt.
    assert _format_version_label("1.16.1", "prerelease", "abc1234") == "1.16.1-pre"
    assert _format_version_label("1.16.1", "prerelease", "") == "1.16.1-pre"


class TestParseReleaseId:
    def test_plain_release_gets_rank_zero(self):
        assert parse_release_id("1.19.0") == (1, 19, 0, 0)

    def test_prerelease_gets_its_number_as_rank(self):
        assert parse_release_id("1.19.0-pre.2") == (1, 19, 0, 2)

    def test_prerelease_ranks_above_its_own_release(self):
        # Repo-Konvention: der Pre-Release entsteht NACH dem gleichnamigen
        # Release, aus neuerem Code (v1.18.2 am 16.07., v1.18.2-pre.1 am 20.07.).
        assert parse_release_id("1.18.2-pre.1") > parse_release_id("1.18.2")

    def test_next_patch_ranks_above_any_prerelease(self):
        assert parse_release_id("1.18.3") > parse_release_id("1.18.2-pre.5")

    def test_prerelease_numbers_compare_numerically_not_lex(self):
        assert parse_release_id("1.18.2-pre.10") > parse_release_id("1.18.2-pre.9")

    def test_garbage_returns_none(self):
        assert parse_release_id("nightly") is None

    def test_two_part_version_returns_none(self):
        # Bewusste Verschärfung gegenüber dem alten _to_tuple: exakt X.Y.Z[-pre.N].
        assert parse_release_id("1.9") is None

    def test_empty_returns_none(self):
        assert parse_release_id("") is None

    def test_none_returns_none(self):
        assert parse_release_id(None) is None

    def test_other_suffix_returns_none(self):
        assert parse_release_id("1.19.0-rc.1") is None


class TestBaseVersion:
    def test_strips_pre_suffix(self):
        assert base_version("1.19.0-pre.2") == "1.19.0"

    def test_plain_version_unchanged(self):
        assert base_version("1.19.0") == "1.19.0"

    def test_empty_stays_empty(self):
        assert base_version("") == ""


class TestStripTagPrefix:
    def test_strips_lowercase_v(self):
        assert strip_tag_prefix("v1.19.0-pre.2") == "1.19.0-pre.2"

    def test_strips_uppercase_v(self):
        assert strip_tag_prefix("V1.19.0") == "1.19.0"

    def test_without_prefix_unchanged(self):
        assert strip_tag_prefix("1.19.0") == "1.19.0"

    def test_surrounding_whitespace_is_removed(self):
        assert strip_tag_prefix("  v1.19.0\n") == "1.19.0"

    def test_none_becomes_empty(self):
        assert strip_tag_prefix(None) == ""


class _FakeBuildInfo:
    def __init__(self, channel="release", sha="abc1234", release_tag=None):
        self.CHANNEL = channel
        self.GIT_SHA = sha
        if release_tag is not None:
            self.RELEASE_TAG = release_tag


class TestFormatVersionLabelWithStampedTag:
    def test_prerelease_with_stamped_tag_shows_number(self):
        assert _format_version_label(
            "1.19.0", "prerelease", "abc1234", "1.19.0-pre.2",
        ) == "1.19.0-pre.2"

    def test_prerelease_without_stamped_tag_falls_back_to_plain_marker(self):
        # Alt-Build ohne Stempel: heutiges Verhalten bleibt.
        assert _format_version_label("1.19.0", "prerelease", "abc1234", "") == "1.19.0-pre"

    def test_release_ignores_stamped_tag(self):
        assert _format_version_label("1.19.0", "release", "", "1.19.0") == "1.19.0"


class TestInstalledReleaseId:
    def test_stamped_prerelease_tag_wins(self):
        with patch("src.version._build_info",
                   _FakeBuildInfo(channel="prerelease", release_tag="v1.19.0-pre.2")):
            assert installed_release_id() == "1.19.0-pre.2"

    def test_uppercase_v_prefix_is_stripped(self):
        with patch("src.version._build_info",
                   _FakeBuildInfo(channel="prerelease", release_tag="V1.19.0-pre.2")):
            assert installed_release_id() == "1.19.0-pre.2"

    def test_missing_attribute_falls_back_to_version(self):
        # Alt-Build: build_info ohne RELEASE_TAG.
        with patch("src.version._build_info", _FakeBuildInfo(channel="release")):
            assert installed_release_id() == VERSION

    def test_empty_tag_falls_back_to_version(self):
        with patch("src.version._build_info",
                   _FakeBuildInfo(channel="dev", release_tag="")):
            assert installed_release_id() == VERSION

    def test_unparsable_tag_falls_back_to_version(self):
        with patch("src.version._build_info",
                   _FakeBuildInfo(channel="release", release_tag="v-nightly")):
            assert installed_release_id() == VERSION

    def test_no_build_info_falls_back_to_version(self):
        # Start aus dem Quellcode (python -m src.main).
        with patch("src.version._build_info", None):
            assert installed_release_id() == VERSION
