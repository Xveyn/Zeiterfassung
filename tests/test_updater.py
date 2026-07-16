import json
import socket
from datetime import date
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from src.updater import (
    Asset, Release, check_latest_release, frequency_for_label, is_newer,
    pick_asset_url, resolve_check_result, should_check, today_iso,
    update_toast_text,
)


class TestIsNewer:
    def test_same_version_is_not_newer(self):
        assert is_newer("1.8.3", "1.8.3") is False

    def test_higher_minor_is_newer(self):
        assert is_newer("1.8.3", "1.9.0") is True

    def test_lower_is_not_newer(self):
        assert is_newer("1.9.0", "1.8.3") is False

    def test_two_digit_patch_compares_numerically_not_lex(self):
        assert is_newer("1.8.3", "1.8.10") is True

    def test_higher_major_is_newer(self):
        assert is_newer("1.8.3", "2.0.0") is True


class TestTodayIso:
    def test_returns_iso_date_string(self):
        result = today_iso()
        # Roundtrip-Parse stellt sicher, dass es ein gültiges ISO-Datum ist
        assert date.fromisoformat(result) == date.today()


class TestShouldCheck:
    def test_empty_string_daily_returns_true(self):
        assert should_check("", "daily", today=date(2026, 4, 28)) is True

    def test_none_daily_returns_true(self):
        assert should_check(None, "daily", today=date(2026, 4, 28)) is True

    def test_daily_yesterday_returns_true(self):
        assert should_check("2026-04-27", "daily", today=date(2026, 4, 28)) is True

    def test_daily_today_returns_false(self):
        assert should_check("2026-04-28", "daily", today=date(2026, 4, 28)) is False

    def test_daily_invalid_string_returns_true(self):
        assert should_check("not-a-date", "daily", today=date(2026, 4, 28)) is True

    def test_weekly_six_days_ago_returns_false(self):
        assert should_check("2026-04-22", "weekly", today=date(2026, 4, 28)) is False

    def test_weekly_seven_days_ago_returns_true(self):
        assert should_check("2026-04-21", "weekly", today=date(2026, 4, 28)) is True

    def test_monthly_twenty_nine_days_ago_returns_false(self):
        assert should_check("2026-03-31", "monthly", today=date(2026, 4, 29)) is False

    def test_monthly_thirty_days_ago_returns_true(self):
        assert should_check("2026-03-30", "monthly", today=date(2026, 4, 29)) is True

    def test_never_returns_false_even_without_last_check(self):
        assert should_check("", "never", today=date(2026, 4, 28)) is False

    def test_never_returns_false_even_long_overdue(self):
        assert should_check("2020-01-01", "never", today=date(2026, 4, 28)) is False


class TestFrequencyForLabel:
    def test_known_label_maps_to_value(self):
        assert frequency_for_label("Wöchentlich") == "weekly"

    def test_unknown_label_falls_back_to_daily(self):
        assert frequency_for_label("Quatsch") == "daily"


class TestUpdateToastText:
    def test_contains_version_and_hint(self):
        from src.updater import Release
        release = Release(version="1.9.0", html_url="https://x", assets=())
        text = update_toast_text(release)
        assert "1.9.0" in text
        assert "Updates" in text


def _three_assets(version: str) -> list[Asset]:
    return [
        Asset(name="Zeiterfassung_Setup.exe", url="https://example.com/exe"),
        Asset(name=f"Zeiterfassung-{version}-arm64.dmg", url="https://example.com/dmg"),
        Asset(name=f"Zeiterfassung-{version}-x86_64.AppImage", url="https://example.com/appimage"),
    ]


class TestPickAssetUrl:
    def test_windows_picks_exe(self):
        assets = _three_assets("1.9.0")
        assert pick_asset_url(assets, "Windows", "1.9.0") == "https://example.com/exe"

    def test_darwin_picks_arm_dmg(self):
        assets = _three_assets("1.9.0")
        assert pick_asset_url(assets, "Darwin", "1.9.0") == "https://example.com/dmg"

    def test_linux_picks_appimage(self):
        assets = _three_assets("1.9.0")
        assert pick_asset_url(assets, "Linux", "1.9.0") == "https://example.com/appimage"

    def test_unknown_system_returns_none(self):
        assets = _three_assets("1.9.0")
        assert pick_asset_url(assets, "FreeBSD", "1.9.0") is None

    def test_missing_asset_returns_none(self):
        assets = [Asset(name="Zeiterfassung-1.9.0-x86_64.AppImage", url="u")]
        assert pick_asset_url(assets, "Windows", "1.9.0") is None

    def test_version_mismatch_in_dmg_name_returns_none(self):
        assets = [Asset(name="Zeiterfassung-1.8.0-arm64.dmg", url="u")]
        assert pick_asset_url(assets, "Darwin", "1.9.0") is None


def _api_response(payload: dict) -> BytesIO:
    return BytesIO(json.dumps(payload).encode("utf-8"))


HAPPY_PAYLOAD = {
    "tag_name": "v1.9.0",
    "html_url": "https://github.com/MargenHeld/Zeiterfassung/releases/tag/v1.9.0",
    "assets": [
        {"name": "Zeiterfassung_Setup.exe", "browser_download_url": "https://example.com/exe"},
        {"name": "Zeiterfassung-1.9.0-arm64.dmg", "browser_download_url": "https://example.com/dmg"},
        {"name": "Zeiterfassung-1.9.0-x86_64.AppImage", "browser_download_url": "https://example.com/appimage"},
    ],
}


class TestCheckLatestRelease:
    def test_happy_path_strips_v_prefix_and_parses_assets(self):
        with patch("src.updater.urlopen", return_value=_api_response(HAPPY_PAYLOAD)):
            release = check_latest_release("MargenHeld/Zeiterfassung")
        assert release is not None
        assert release.version == "1.9.0"
        assert release.html_url.endswith("/v1.9.0")
        assert len(release.assets) == 3
        assert release.assets[0].name == "Zeiterfassung_Setup.exe"
        assert release.assets[0].url == "https://example.com/exe"

    def test_url_error_returns_none(self):
        with patch("src.updater.urlopen", side_effect=URLError("offline")):
            assert check_latest_release("any/repo") is None

    def test_http_404_returns_none(self):
        err = HTTPError(url="x", code=404, msg="Not Found", hdrs=None, fp=None)
        with patch("src.updater.urlopen", side_effect=err):
            assert check_latest_release("any/repo") is None

    def test_socket_timeout_returns_none(self):
        with patch("src.updater.urlopen", side_effect=socket.timeout()):
            assert check_latest_release("any/repo") is None

    def test_invalid_json_returns_none(self):
        with patch("src.updater.urlopen", return_value=BytesIO(b"not json{{")):
            assert check_latest_release("any/repo") is None

    def test_missing_tag_name_returns_none(self):
        payload = {"html_url": "x", "assets": []}
        with patch("src.updater.urlopen", return_value=_api_response(payload)):
            assert check_latest_release("any/repo") is None

    def test_missing_html_url_returns_none(self):
        payload = {"tag_name": "v1.9.0", "assets": []}
        with patch("src.updater.urlopen", return_value=_api_response(payload)):
            assert check_latest_release("any/repo") is None

    def test_malformed_assets_are_filtered(self):
        # Asset ohne browser_download_url + Asset als String → werden geskippt
        payload = {
            "tag_name": "v1.9.0",
            "html_url": "x",
            "assets": [
                {"name": "ok", "browser_download_url": "u1"},
                {"name": "incomplete"},                       # ohne URL
                "not-a-dict",                                 # falscher Typ
                {"name": "ok2", "browser_download_url": "u2"},
            ],
        }
        with patch("src.updater.urlopen", return_value=_api_response(payload)):
            release = check_latest_release("any/repo")
        assert release is not None
        assert len(release.assets) == 2
        assert {a.name for a in release.assets} == {"ok", "ok2"}

    def test_uppercase_v_prefix_is_stripped(self):
        payload = dict(HAPPY_PAYLOAD, tag_name="V1.9.0")
        with patch("src.updater.urlopen", return_value=_api_response(payload)):
            release = check_latest_release("any/repo")
        assert release is not None
        assert release.version == "1.9.0"


class TestResolveCheckResult:
    def test_no_connection_returns_failure_status_without_changelog(self):
        result = resolve_check_result("1.18.0", None)
        assert result == {
            "status_text": "Prüfung fehlgeschlagen — keine Verbindung?",
            "show_download": False,
            "changelog_version": None,
            "persist": None,
            "latest_release": None,
        }

    def test_current_version_shows_changelog_of_installed_version(self):
        # Ohne verfügbares Update soll trotzdem der Changelog der
        # installierten Version sichtbar sein (statt komplett ausgeblendet).
        release = Release(version="1.18.0", html_url="https://x", assets=())
        result = resolve_check_result("1.18.0", release)
        assert result["status_text"] == "Du hast die aktuelle Version (1.18.0)."
        assert result["show_download"] is False
        assert result["changelog_version"] == "1.18.0"
        assert result["persist"] is None
        assert result["latest_release"] is None

    def test_newer_release_shows_download_and_persists_dismissal(self):
        release = Release(version="1.19.0", html_url="https://x", assets=())
        result = resolve_check_result("1.18.0", release)
        assert result["status_text"] == "Version 1.19.0 verfügbar"
        assert result["show_download"] is True
        assert result["changelog_version"] == "1.19.0"
        assert result["persist"] == {
            "dismissed_version": "1.19.0",
            "update_toast_shown_version": "1.19.0",
        }
        assert result["latest_release"] is release
