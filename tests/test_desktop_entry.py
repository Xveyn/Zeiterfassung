# tests/test_desktop_entry.py
"""Menüeintrag und .desktop-Format — plattformunabhängig über tmp_path/HOME."""

import os

import pytest

from src.desktop_entry import (
    ensure_icon,
    exec_line,
    menu_entry_path,
    write_menu_entry,
)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    return tmp_path


def test_exec_line_leaves_simple_paths_alone():
    assert exec_line("/opt/Zeiterfassung.AppImage", "") == "/opt/Zeiterfassung.AppImage"


def test_exec_line_appends_arguments():
    assert exec_line("/opt/Z.AppImage", "--minimized") == "/opt/Z.AppImage --minimized"


def test_exec_line_quotes_paths_with_spaces():
    # Audit N12: unquoted zerbricht Exec an der GLib-Tokenisierung.
    assert exec_line("/opt/My Apps/Z.AppImage", "") == "'/opt/My Apps/Z.AppImage'"


def test_menu_entry_path_is_in_xdg_applications(fake_home):
    assert menu_entry_path() == os.path.join(
        str(fake_home), ".local", "share", "applications", "Zeiterfassung.desktop")


def test_menu_entry_path_honours_xdg_data_home(fake_home, monkeypatch, tmp_path):
    # Review-Finding 3 (2026-07-29): ohne diesen Abgleich schriebe die App an
    # ~/.local/share/applications vorbei, wenn der Nutzer XDG_DATA_HOME
    # gesetzt hat — der Eintrag entstünde, aber kein Menü fände ihn.
    custom = tmp_path / "custom-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(custom))
    assert menu_entry_path() == os.path.join(
        str(custom), "applications", "Zeiterfassung.desktop")


def test_write_menu_entry_creates_a_valid_entry(fake_home):
    write_menu_entry("/opt/Zeiterfassung.AppImage", "/data/icon.png")
    content = open(menu_entry_path(), encoding="utf-8").read()
    assert content.startswith("[Desktop Entry]\n")
    assert "Type=Application\n" in content
    assert "Name=Zeiterfassung\n" in content
    assert "Exec=/opt/Zeiterfassung.AppImage\n" in content
    assert "Icon=/data/icon.png\n" in content
    assert "Terminal=false\n" in content
    assert "Categories=Office;\n" in content


def test_write_menu_entry_omits_icon_line_when_there_is_no_icon(fake_home):
    """Eine Icon-Zeile mit leerem Wert wäre schlechter als keine."""
    write_menu_entry("/opt/Zeiterfassung.AppImage", None)
    content = open(menu_entry_path(), encoding="utf-8").read()
    assert "Icon=" not in content


def test_write_menu_entry_is_idempotent_and_refreshes_exec(fake_home):
    write_menu_entry("/opt/alt.AppImage", None)
    write_menu_entry("/opt/neu.AppImage", None)
    content = open(menu_entry_path(), encoding="utf-8").read()
    assert "Exec=/opt/neu.AppImage\n" in content
    assert "alt.AppImage" not in content


def test_ensure_icon_copies_the_bundled_png(tmp_path):
    bundle = tmp_path / "bundle" / "assets"
    bundle.mkdir(parents=True)
    (bundle / "margenheld-icon.png").write_bytes(b"PNGDATA")
    data = tmp_path / "data"
    data.mkdir()

    result = ensure_icon(str(tmp_path / "bundle"), str(data))
    assert result == str(data / "icon.png")
    assert (data / "icon.png").read_bytes() == b"PNGDATA"


def test_ensure_icon_does_not_copy_again_when_sizes_match(tmp_path):
    bundle = tmp_path / "bundle" / "assets"
    bundle.mkdir(parents=True)
    (bundle / "margenheld-icon.png").write_bytes(b"PNGDATA")
    data = tmp_path / "data"
    data.mkdir()
    ensure_icon(str(tmp_path / "bundle"), str(data))
    target = data / "icon.png"
    target.write_bytes(b"MARKIER")   # gleiche Länge wie b"PNGDATA"

    ensure_icon(str(tmp_path / "bundle"), str(data))
    assert target.read_bytes() == b"MARKIER"   # nicht überschrieben


def test_ensure_icon_recopies_when_size_differs(tmp_path):
    bundle = tmp_path / "bundle" / "assets"
    bundle.mkdir(parents=True)
    (bundle / "margenheld-icon.png").write_bytes(b"NEUEDATEN-LAENGER")
    data = tmp_path / "data"
    data.mkdir()
    (data / "icon.png").write_bytes(b"ALT")

    ensure_icon(str(tmp_path / "bundle"), str(data))
    assert (data / "icon.png").read_bytes() == b"NEUEDATEN-LAENGER"


def test_ensure_icon_returns_none_without_a_bundled_png(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    assert ensure_icon(str(tmp_path / "leer"), str(data)) is None
