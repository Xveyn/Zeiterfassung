"""Build-Kennung der Handy-PWA (#280): `N/X.Y.Z (sha)`.

N = Commits unter pwa/ seit dem letzten echten Release, X.Y.Z = Version dieses
Releases (nicht `src/version.py`: auf master kann dort schon die nächste stehen).
`scripts/` ist kein Package, das Skript wird über seinen Pfad geladen.
"""

import importlib.util
import json
import pathlib

import pytest

_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "pwa_stamp.py"
_spec = importlib.util.spec_from_file_location("_pwa_stamp", _PATH)
stamp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stamp)


def test_label_format():
    assert stamp.build_label(4, "1.25.3", "abcdef1234567890") == "4/1.25.3 (abcdef123456)"


def test_label_zero_commits_keeps_format():
    assert stamp.build_label(0, "1.24.0", "abcdef1234567890") == "0/1.24.0 (abcdef123456)"


@pytest.mark.parametrize("tags,expected", [
    (["v1.24.0", "v1.24.0-pre.2", "v1.23.3"], "v1.24.0"),
    (["v1.9.0", "v1.10.0"], "v1.10.0"),
    (["v1.24.0-pre.1", "v1.23.3", "foo"], "v1.23.3"),
])
def test_latest_release_tag_ignores_prereleases(tags, expected):
    assert stamp.latest_release_tag(tags) == expected


def test_latest_release_tag_none():
    assert stamp.latest_release_tag(["v1.0.0-pre.1"]) is None


def test_stamp_site_replaces_placeholder_in_sw_core_and_manifest(tmp_path):
    (tmp_path / "sw-core.js").write_text("export const BUILD = '__BUILD__';\n", encoding="utf-8")
    (tmp_path / "manifest.webmanifest").write_text('{"version": "__BUILD__"}', encoding="utf-8")
    stamp.stamp_site(tmp_path, "4/1.24.0 (abc)")
    assert "'4/1.24.0 (abc)'" in (tmp_path / "sw-core.js").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "manifest.webmanifest").read_text(encoding="utf-8"))["version"] == "4/1.24.0 (abc)"


def test_stamp_site_fails_when_placeholder_missing(tmp_path):
    (tmp_path / "sw-core.js").write_text("nothing", encoding="utf-8")
    (tmp_path / "manifest.webmanifest").write_text('{"version": "__BUILD__"}', encoding="utf-8")
    with pytest.raises(SystemExit):
        stamp.stamp_site(tmp_path, "x")
