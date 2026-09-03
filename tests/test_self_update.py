"""Reine Logik des In-App-Updates (Tk-frei, ohne Netzwerk)."""

import hashlib

import pytest

from src.self_update import (
    UpdateBlocked, UpdatePlan, parse_sha256sums, plan_update,
    supports_self_update, verify_file,
)
from src.updater import Asset, Release

# So sieht die Datei im Release wirklich aus (coreutils `sha256sum`,
# zwei Leerzeichen zwischen Digest und Name).
SUMS_FIXTURE = (
    "3f786850e387550fdab836ed7e6dc881de23001b3f786850e387550fdab836ed  "
    "Zeiterfassung_Setup.exe\n"
    "89e6c98d92887913cadf06b2adb97f26cde4849b0a3b1a4b1a4b1a4b1a4b1a4b  "
    "Zeiterfassung-1.22.0-x86_64.AppImage\n"
)


def test_parse_sha256sums_reads_name_and_digest():
    sums = parse_sha256sums(SUMS_FIXTURE)
    assert sums["Zeiterfassung_Setup.exe"] == (
        "3f786850e387550fdab836ed7e6dc881de23001b3f786850e387550fdab836ed")
    assert len(sums) == 2


def test_parse_sha256sums_ignores_blank_and_broken_lines():
    text = SUMS_FIXTURE + "\n" + "nurwas\n" + "zzz  Datei.txt\n"
    sums = parse_sha256sums(text)
    assert len(sums) == 2          # die beiden kaputten Zeilen fallen raus


def test_parse_sha256sums_handles_crlf():
    sums = parse_sha256sums(SUMS_FIXTURE.replace("\n", "\r\n"))
    assert "Zeiterfassung_Setup.exe" in sums


def test_parse_sha256sums_handles_binary_marker():
    # `sha256sum -b` schreibt " *name" statt "  name".
    text = ("3f786850e387550fdab836ed7e6dc881de23001b3f786850e387550fdab836ed"
            " *Zeiterfassung_Setup.exe\n")
    assert "Zeiterfassung_Setup.exe" in parse_sha256sums(text)


def test_parse_sha256sums_on_empty_text():
    assert parse_sha256sums("") == {}


def test_verify_file_accepts_the_matching_digest(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hallo welt")
    assert verify_file(str(f), hashlib.sha256(b"hallo welt").hexdigest())


def test_verify_file_rejects_a_different_digest(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hallo welt")
    assert not verify_file(str(f), hashlib.sha256(b"etwas anderes").hexdigest())


def test_verify_file_is_case_insensitive_about_the_digest(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hallo welt")
    assert verify_file(str(f), hashlib.sha256(b"hallo welt").hexdigest().upper())


def test_verify_file_on_missing_file_is_false(tmp_path):
    assert not verify_file(str(tmp_path / "gibtsnicht.bin"), "00" * 32)


def _release(version="1.23.0", with_sums=True):
    assets = [
        Asset(name="Zeiterfassung_Setup.exe", url="https://x/exe"),
        Asset(name=f"Zeiterfassung-{version}-x86_64.AppImage", url="https://x/img"),
        Asset(name=f"Zeiterfassung-{version}-arm64.dmg", url="https://x/dmg"),
    ]
    if with_sums:
        assets.append(Asset(name="SHA256SUMS", url="https://x/sums"))
    return Release(version=version, html_url="https://x/rel", assets=tuple(assets))


@pytest.mark.parametrize("system,frozen,expected", [
    ("Windows", True, True),
    ("Linux", True, True),
    ("Darwin", True, False),     # bewusst nicht unterstuetzt
    ("Windows", False, False),   # Repo-Modus: nichts zu ersetzen
    ("Linux", False, False),
    ("FreeBSD", True, False),
])
def test_supports_self_update(system, frozen, expected):
    assert supports_self_update(system, frozen) is expected


def test_plan_update_on_windows_yields_setup_and_sums():
    plan = plan_update(_release(), "Windows", "AMD64", True, "",
                       r"C:\Apps\Zeiterfassung\Zeiterfassung.exe")
    assert isinstance(plan, UpdatePlan)
    assert plan.asset_name == "Zeiterfassung_Setup.exe"
    assert plan.asset_url == "https://x/exe"
    assert plan.sums_url == "https://x/sums"
    assert plan.target == r"C:\Apps\Zeiterfassung\Zeiterfassung.exe"


def test_plan_update_on_linux_targets_the_appimage():
    plan = plan_update(_release(), "Linux", "x86_64", True,
                       "/home/u/Apps/Zeiterfassung.AppImage", "/tmp/whatever")
    assert isinstance(plan, UpdatePlan)
    assert plan.asset_name == "Zeiterfassung-1.23.0-x86_64.AppImage"
    assert plan.target == "/home/u/Apps/Zeiterfassung.AppImage"


def test_plan_update_blocks_on_macos():
    blocked = plan_update(_release(), "Darwin", "arm64", True, "", "/A/Z.app")
    assert isinstance(blocked, UpdateBlocked)
    assert "macOS" in blocked.reason


def test_plan_update_blocks_in_repo_mode():
    blocked = plan_update(_release(), "Windows", "AMD64", False, "", "python.exe")
    assert isinstance(blocked, UpdateBlocked)


def test_plan_update_blocks_when_architecture_does_not_match():
    blocked = plan_update(_release(), "Linux", "aarch64", True,
                          "/home/u/Z.AppImage", "/tmp/x")
    assert isinstance(blocked, UpdateBlocked)
    assert "Architektur" in blocked.reason


def test_plan_update_blocks_without_a_sums_asset():
    blocked = plan_update(_release(with_sums=False), "Windows", "AMD64", True,
                          "", r"C:\Apps\Z.exe")
    assert isinstance(blocked, UpdateBlocked)
    assert "Prüfsumme" in blocked.reason


def test_plan_update_blocks_on_linux_without_appimage_env():
    # Die nackte PyInstaller-Ausgabe hat $APPIMAGE nicht.
    blocked = plan_update(_release(), "Linux", "x86_64", True, "", "/tmp/x")
    assert isinstance(blocked, UpdateBlocked)
    assert "AppImage" in blocked.reason
