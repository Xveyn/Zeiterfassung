"""Build-Kanal-Marker im Fenstertitel (#45).

Getestet wird die reine Label-Formatierung `_format_version_label`. Der Reader
`version_label()` (liest das beim Build generierte build_info-Modul) und die
Tk-Titelzeile sind Verdrahtung und werden manuell verifiziert.
"""
from src.version import _format_version_label


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
